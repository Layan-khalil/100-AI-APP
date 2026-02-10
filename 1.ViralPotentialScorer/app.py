import streamlit as st
import uuid
import hashlib
from supabase import create_client, Client
from google import genai
from google.genai import types
import time 
from postgrest.exceptions import APIError

# ✅ NEW (فقط لتفادي Error + retries)
from google.api_core.exceptions import ResourceExhausted, ServiceUnavailable, DeadlineExceeded

# ==============================
# 0) إعدادات الصفحة أولاً
# ==============================
st.set_page_config(
    page_title="  مُحلّل الانتشار الفيروسي",
    layout="centered"
)

# ==============================
# ✅ Language Switch
# ==============================
if "ui_lang" not in st.session_state:
    st.session_state["ui_lang"] = "AR"

lang_choice = st.toggle("English", value=(st.session_state["ui_lang"] == "EN"))
st.session_state["ui_lang"] = "EN" if lang_choice else "AR"
IS_EN = (st.session_state["ui_lang"] == "EN")

# ==============================
# 1) تحميل الـ Secrets والاتصال
# ==============================
try:
    SUPABASE_URL = st.secrets["SUPABASE_URL"]
    SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
    GOOGLE_API_KEY = st.secrets["GOOGLE_API_KEY"]
except Exception:
    st.error("⚠️ فشل في تحميل المفاتيح السرّية (Secrets). تأكد من ضبطها في Streamlit Cloud.")
    st.stop()

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
genai_client = genai.Client(api_key=GOOGLE_API_KEY)

APP_ID = "viral-potential-scorer-v1"

# ✅ استخدام نسخة مستقرة لضمان عدم حدوث Error 404
MODEL_NAME = "gemini-1.5-flash"

# =========================
#  CSS & Responsive Styling
# =========================
DIR = "ltr" if IS_EN else "rtl"
ALIGN = "left" if IS_EN else "right"

st.markdown(f"""
<style>

/* إخفاء شريط Streamlit العلوي */
#MainMenu {{ visibility: hidden; }}

/* إخفاء الفوتر الافتراضي */
footer {{ visibility: hidden; }}

/* إخفاء أي عنصر فيه Created by / Avatar */
div[data-testid="stToolbar"] {{ visibility: hidden; }}
div[data-testid="stStatusWidget"] {{ visibility: hidden; }}
div[data-testid="stDecoration"] {{ visibility: hidden; }}

/* إخفاء شريط الأسفل بالكامل (mobile + desktop) */
div[class*="viewerBadge_container"] {{ display: none !important; }}
div[class*="viewerBadge_link"] {{ display: none !important; }}
div[class*="viewerBadge_text"] {{ display: none !important; }}

/************ محتوى الصفحة الرئيسي  ************/
.app-container {{
    max-width: 900px;
    margin: 0 auto;
    padding: 0 14px;
}}

html, body, [data-testid="stAppViewContainer"], .main {{
    direction: {DIR} !important;
    text-align: {ALIGN} !important;
    font-family: "Cairo", sans-serif;
}}

.stButton > button {{
    background-color: #e63946 !important;
    color: #ffffff !important;
    font-weight: 800;
    border-radius: 28px;
    border: none;
    padding: 12px 18px;
    height: 3.2em;
    width: 100%;
    font-size: 17px;
    transition: 0.2s ease-in-out;
}}

.stButton > button:hover {{
    background-color: #c82333 !important;
    transform: scale(1.01);
}}

/************ العناوين  ************/
h1,h2,h3,h4,h5,h6 {{
    direction: {DIR} !important;
    text-align: {ALIGN} !important;
    margin-right: 0;
}}

/************ الفقرات والنصوص  ************/
p, div {{
    direction: {DIR} !important;
    text-align: {ALIGN} !important;
    word-break: break-word;
    line-height: 1.9;
}}

/************ القوائم  ************/
ol, ul {{
    direction: {DIR} !important;
    text-align: {ALIGN} !important;
    list-style-position: inside !important;
    padding-right: 0 !important;
    margin-right: 0 !important;
}}

/************ ✅ صندوق النتيجة  ************/
.result-box {{
    background: transparent !important;
    border: 2px solid rgba(230,57,70,0.45);
    border-radius: 18px;
    padding: 16px 16px;
    margin-top: 14px;
}}
.result-title {{
    color: #ffffff !important;
    font-weight: 900;
    font-size: 18px;
    margin-bottom: 10px;
}}
.result-text {{
    color: #ffffff !important;
    white-space: pre-wrap;
    word-break: break-word;
    line-height: 2.0;
}}

/************ الفوتر  ************/
.footer-container {{
    width: 100%;
    text-align: center;
    margin-top: 45px;
    padding-top: 20px;
    border-top: 1px solid #666;
    font-size: 13px;
    display: flex;
    justify-content: center;
    gap: 6px;
    flex-wrap: wrap;
    direction: rtl !important;
}}
</style>
""", unsafe_allow_html=True)

# ==============================
# 3) دوال التتبع
# ==============================
def get_session_visitor_id() -> str:
    if "visitor_id" not in st.session_state:
        st.session_state["visitor_id"] = str(uuid.uuid4())
    return st.session_state["visitor_id"]

def track_visit():
    visitor_id = get_session_visitor_id()
    try:
        supabase.rpc("track_visit", {"p_app_id": APP_ID, "p_visitor_id": visitor_id}).execute()
    except: pass

def track_cta_event():
    try:
        supabase.rpc("increment_cta", {"p_app_id": APP_ID}).execute()
    except: pass

track_visit()

def save_feedback_via_rpc(app_name, useful, missing_reason, problem_text, helpful_reason, must_use_text):
    return supabase.rpc("submit_app_feedback", {
        "p_app_name": app_name, "p_useful": useful, "p_missing_reason": missing_reason,
        "p_problem_text": problem_text, "p_helpful_reason": helpful_reason, "p_must_use_text": must_use_text,
    }).execute()

# ==============================
# 4) الكاش والتحليل (التعديل المطلوب هنا)
# ==============================
def get_content_hash(text: str) -> str:
    normalized = " ".join(text.strip().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

def get_or_create_analysis(text: str) -> str:
    """
    1) يحاول قراءة التحليل من جدول viral_scores_cache
    2) إذا لم يجده، يستدعي Gemini ثم يخزن النتيجة في الكاش
    """
    content_hash = get_content_hash(text)

    # 1) حاول قراءة الكاش
    try:
        res = (
            supabase.table("viral_scores_cache")
            .select("analysis_text")
            .eq("app_id", APP_ID)
            .eq("content_hash", content_hash)
            .limit(1)
            .execute()
        )
        if res.data and len(res.data) > 0:
            cached_text = res.data[0]["analysis_text"]
            if cached_text:
                return cached_text
    except Exception as e:
        print(f"[cache read] Error: {e}")

    # 2) لم نجد كاش → استدعاء Gemini (تم رفع max_output_tokens لضمان عدم النقص)
    gen_config = types.GenerateContentConfig(
        temperature=0.7, # رفعنا الحرارة قليلاً ليكون التحليل أكثر تدفقاً
        top_p=0.9,
        max_output_tokens=4000, # تم الرفع من 1600 إلى 4000 لضمان اكتمال الـ 6 نقاط
    )

    if IS_EN:
        prompt = f"""
You are a viral content expert specialized in Jonah Berger's STEPPS framework.
Analyze the following text using ONLY the six STEPPS factors:
1) Social Currency
2) Triggers
3) Emotion
4) Public
5) Practical Value
6) Stories

Rules:
- Give a score out of 10 for each factor.
- Provide a detailed 3-4 line explanation for each point.
- Ensure the analysis is deep and complete for all 6 points.
- Do NOT provide a final total percentage.
- Language: English.

Text to analyze:
{text}
"""
    else:
        prompt = f"""
أنت خبير محتوى فيروسي متخصص في نموذج STEPPS لجونا بيرجر.
حلّل النص التالي بناءً على عوامل STEPPS الستّة بشكل مفصل وكامل:
1) Social Currency (العملة الاجتماعية)
2) Triggers (المحفّزات)
3) Emotion (المشاعر)
4) Public (الظهور العام)
5) Practical Value (القيمة العملية)
6) Stories (القصص)

قواعد:
- أعطِ درجة من 10 لكل عامل.
- اشرح كل نقطة في 3-4 أسطر مفصلة.
- تأكد من إكمال التحليل للنقاط الستة كاملة دون توقف.
- لا تذكر نسبة مئوية إجمالية.
- اللغة: العربية.

النص المراد تحليله:
{text}
"""

    MAX_RETRIES = 3
    INITIAL_DELAY = 2
    analysis_text = ""

    for attempt in range(MAX_RETRIES):
        try:
            response = genai_client.models.generate_content(
                model=MODEL_NAME,
                contents=prompt,
                config=gen_config,
            )
            if response.text:
                analysis_text = response.text
                break
        except (ResourceExhausted, ServiceUnavailable, DeadlineExceeded):
            time.sleep(INITIAL_DELAY * (attempt + 1))
        except Exception:
            break

    if not analysis_text.strip():
        return "⚠️ Error in generation" if IS_EN else "⚠️ فشل في توليد التحليل"

    # 3) تخزين النتيجة في الكاش
    try:
        supabase.table("viral_scores_cache").insert(
            {
                "app_id": APP_ID,
                "content_hash": content_hash,
                "analysis_text": analysis_text,
            }
        ).execute()
    except Exception as e:
        print(f"[cache write] Error: {e}")

    return analysis_text
# ==============================
# 5) واجهة المستخدم
# ==============================
if IS_EN:
    st.title("🎯 Viral Potential Scorer")
    with st.expander("💡 How does it work?"):
        st.markdown("""
This tool analyzes your text (post, tweet, video script...) using the 6 STEPPS factors:
1. **Social Currency** | 2. **Triggers** | 3. **Emotion** | 4. **Public** | 5. **Practical Value** | 6. **Stories**
""")
else:
    st.title("🎯 مُحلّل احتمالية انتشار المحتوى الفيروسي")
    with st.expander("💡 كيف يعمل هذا المحلل؟"):
        st.markdown("""
هذه الأداة تحلل نصّك بناءً على ستة عوامل:
1) **العملة الاجتماعية** | 2) **المحفّزات** | 3) **المشاعر** | 4) **الظهور العلني** | 5) **القيمة العملية** | 6) **القصص**
""")

st.markdown("---")

# --- Testimonials Section (كما هي تماماً) ---
st.markdown("""
<style>
.testimonial-wrapper, .testimonial-card, .testimonial-text, .testimonial-author, .testimonial-title {
    direction: ltr !important; text-align: center !important;
}
.testimonial-title { text-align:center; font-size:20px; font-weight:800; margin: 10px 0 12px 0; }
.testimonial-wrapper { display:flex; gap:14px; overflow-x:auto; padding: 8px 8px 14px 8px; scroll-snap-type:x mandatory; -webkit-overflow-scrolling: touch; }
.testimonial-wrapper::-webkit-scrollbar { height:8px; }
.testimonial-wrapper::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.18); border-radius: 99px; }
.testimonial-card {
    flex: 0 0 auto; width: 320px; max-width: 85vw; background: rgba(255,255,255,0.03);
    border: 1px solid rgba(255,255,255,0.14); border-left: 5px solid #e63946; border-radius: 14px;
    padding: 16px; scroll-snap-align:center; height:auto !important;
}
.testimonial-text { color: rgba(255,255,255,0.92); font-size: 14px; line-height: 1.6; }
.testimonial-author { margin-top:10px; font-weight:700; color: rgba(255,255,255,0.72); font-size: 13px; }
</style>
<div class="testimonial-title">💬 What users are saying</div>
<div class="testimonial-wrapper">
    <div class="testimonial-card"><div class="testimonial-text">I was looking for help improving how I write my posts, and this tool genuinely helped me. What makes it a must-use is how many people are moving toward content creation today — having guidance like this makes a real difference.</div><div class="testimonial-author">— Yousef Khalil</div></div>
    <div class="testimonial-card"><div class="testimonial-text">The tool helped me understand what actually helps a post reach more people, especially because it analyzes viral factors with percentages and clear explanations.</div><div class="testimonial-author">— Sally Daibes</div></div>
    <div class="testimonial-card"><div class="testimonial-text">Great tool. It helped me create a post that attracts advice and real experiences from others. I recommend creators and anyone interested in content to try it.</div><div class="testimonial-author">— Salem Khalil</div></div>
    <div class="testimonial-card"><div class="testimonial-text">Love the initiative.</div><div class="testimonial-author">— Dany Kitishian</div></div>
    <div class="testimonial-card"><div class="testimonial-text">Honestly impressive. I tested it on one of my posts and immediately saw where the tool could help improve performance. Well done.</div><div class="testimonial-author">— Salem Khalil</div></div>
</div>
""", unsafe_allow_html=True)

# --- Inputs ---
if IS_EN:
    post_text = st.text_area("✍️ Paste your post / tweet / video script here:", height=220, placeholder="Write the full text...")
    btn_label = "Analyze now 🚀"
else:
    post_text = st.text_area("✍️ أدخل نص المنشور / التغريدة هنا:", height=220, placeholder="اكتب النص الكامل هنا...")
    btn_label = "تحليل الآن 🚀"

if st.button(btn_label):
    if not post_text or len(post_text.strip()) < 20:
        st.warning("Please enter a real text." if IS_EN else "الرجاء إدخال نص حقيقي.")
    else:
        track_cta_event()
        with st.spinner("⏳ Analyzing..." if IS_EN else "⏳ جاري التحليل..."):
            analysis = get_or_create_analysis(post_text.strip())
        st.session_state[f"{APP_ID}_has_result"] = True
        st.session_state[f"{APP_ID}_analysis"] = analysis

# --- Result View ---
if st.session_state.get(f"{APP_ID}_has_result"):
    analysis = st.session_state.get(f"{APP_ID}_analysis", "")
    if analysis.strip():
        st.markdown(f"""
        <div class="result-box">
            <div class="result-title">{"📊 Analysis Results:" if IS_EN else "📊 نتائج التحليل:"}</div>
            <div class="result-text">{analysis}</div>
        </div>
        """, unsafe_allow_html=True)

# ==============================
# 6) الفوتر
# ==============================
st.markdown("""
<div class="footer-container">
  <span>جميع الحقوق محفوظة © 2026 | AI Product Builder - Layan Khalil</span>
</div>
""", unsafe_allow_html=True)

