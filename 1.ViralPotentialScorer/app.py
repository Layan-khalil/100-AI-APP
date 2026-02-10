import streamlit as st
import uuid
import hashlib
import os
import time
import html
from datetime import datetime, timezone

from supabase import create_client, Client
from postgrest.exceptions import APIError

from google import genai
from google.genai import types
from google.api_core.exceptions import ResourceExhausted, ServiceUnavailable, DeadlineExceeded

# ==============================
# 0) Page Config
# ==============================
st.set_page_config(
    page_title="مُحلّل الانتشار الفيروسي",
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
# 1) Secrets + Clients
# ==============================
def get_secret(key: str):
    return st.secrets.get(key) or os.environ.get(key)

SUPABASE_URL = get_secret("SUPABASE_URL")
SUPABASE_KEY = get_secret("SUPABASE_KEY")
GOOGLE_API_KEY = get_secret("GOOGLE_API_KEY")

if not all([SUPABASE_URL, SUPABASE_KEY, GOOGLE_API_KEY]):
    st.error("⚠️ Missing secrets in Secrets / Env." if IS_EN else "⚠️ مفاتيح الربط ناقصة في Secrets أو Env.")
    st.stop()

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
genai_client = genai.Client(api_key=GOOGLE_API_KEY)

APP_ID = "viral-potential-scorer-v1"

# ==============================
# ✅ Working model selector (fix 404/invalid model)
# ==============================
MODEL_CANDIDATES = [
    "gemini-2.0-flash-001",
    "gemini-1.5-flash-001",
    "gemini-1.5-pro-001",
]

def get_working_model():
    if "working_model" in st.session_state:
        return st.session_state["working_model"]

    for m in MODEL_CANDIDATES:
        try:
            genai_client.models.generate_content(
                model=m,
                contents="test",
                config=types.GenerateContentConfig(max_output_tokens=1),
            )
            st.session_state["working_model"] = m
            return m
        except Exception:
            continue

    st.session_state["working_model"] = MODEL_CANDIDATES[0]
    return MODEL_CANDIDATES[0]

# =========================
#  CSS & Responsive Styling
# =========================
DIR = "ltr" if IS_EN else "rtl"
ALIGN = "left" if IS_EN else "right"

st.markdown(f"""
<style>
#MainMenu {{ visibility: hidden; }}
footer {{ visibility: hidden; }}
div[data-testid="stToolbar"] {{ visibility: hidden; }}
div[data-testid="stStatusWidget"] {{ visibility: hidden; }}
div[data-testid="stDecoration"] {{ visibility: hidden; }}
div[class*="viewerBadge_container"] {{ display: none !important; }}
div[class*="viewerBadge_link"] {{ display: none !important; }}
div[class*="viewerBadge_text"] {{ display: none !important; }}

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

h1,h2,h3,h4,h5,h6 {{
    direction: {DIR} !important;
    text-align: {ALIGN} !important;
}}
p, div {{
    direction: {DIR} !important;
    text-align: {ALIGN} !important;
    word-break: break-word;
    line-height: 1.9;
}}
ol, ul {{
    direction: {DIR} !important;
    text-align: {ALIGN} !important;
    list-style-position: inside !important;
    padding-right: 0 !important;
    margin-right: 0 !important;
}}

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
# 3) Tracking (Visit + CTA)
# ==============================
def get_session_visitor_id() -> str:
    if "visitor_id" not in st.session_state:
        st.session_state["visitor_id"] = str(uuid.uuid4())
    return st.session_state["visitor_id"]

def track_visit():
    visitor_id = get_session_visitor_id()
    try:
        supabase.rpc("track_visit", {"p_app_id": APP_ID, "p_visitor_id": visitor_id}).execute()
    except Exception:
        pass

def track_cta_event():
    try:
        supabase.rpc("increment_cta", {"p_app_id": APP_ID}).execute()
    except Exception:
        pass

track_visit()

# ==============================
# 4) Cache + Analysis (FIXED)
# ==============================
def get_content_hash(text: str) -> str:
    normalized = " ".join(text.strip().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

def cache_get(content_hash: str):
    try:
        res = (
            supabase.table("viral_scores_cache")
            .select("analysis_text")
            .eq("app_id", APP_ID)
            .eq("content_hash", content_hash)
            .limit(1)
            .execute()
        )
        if res.data and res.data[0].get("analysis_text"):
            return res.data[0]["analysis_text"]
    except Exception:
        pass
    return None

def cache_set(content_hash: str, analysis_text: str):
    # ✅ upsert بدل insert لتفادي duplicate / constraint issues
    try:
        supabase.table("viral_scores_cache").upsert(
            {
                "app_id": APP_ID,
                "content_hash": content_hash,
                "analysis_text": analysis_text,
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
            on_conflict="app_id,content_hash",
        ).execute()
    except Exception:
        pass

def build_prompt(text: str) -> str:
    if IS_EN:
        return f"""
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
    return f"""
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

def get_or_create_analysis(text: str) -> str:
    content_hash = get_content_hash(text)

    cached = cache_get(content_hash)
    if cached:
        return cached

    model_name = get_working_model()

    gen_config = types.GenerateContentConfig(
        temperature=0.7,
        top_p=0.9,
        max_output_tokens=4000,
    )

    prompt = build_prompt(text)

    MAX_RETRIES = 4
    INITIAL_DELAY = 2
    last_error = None

    for attempt in range(MAX_RETRIES):
        try:
            response = genai_client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=gen_config,
            )
            analysis_text = (response.text or "").strip()
            if analysis_text:
                cache_set(content_hash, analysis_text)
                return analysis_text

            last_error = "Empty response from model"
        except (ResourceExhausted, ServiceUnavailable, DeadlineExceeded) as e:
            last_error = str(e)
            time.sleep(INITIAL_DELAY * (attempt + 1))
        except Exception as e:
            last_error = str(e)
            break

    # ✅ الآن رح يرجع سبب الخطأ بدل رسالة عامة
    if IS_EN:
        return f"⚠️ Generation failed.\nReason: {last_error or 'Unknown error'}"
    return f"⚠️ فشل في توليد التحليل.\nالسبب: {last_error or 'خطأ غير معروف'}"

# ==============================
# 5) UI
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
    analysis = st.session_state.get(f"{APP_ID}_analysis", "") or ""
    safe_analysis = html.escape(analysis)

    st.markdown(f"""
    <div class="result-box">
        <div class="result-title">{"📊 Analysis Results:" if IS_EN else "📊 نتائج التحليل:"}</div>
        <div class="result-text">{safe_analysis}</div>
    </div>
    """, unsafe_allow_html=True)

# ==============================
# 6) Footer
# ==============================
st.markdown("""
<div class="footer-container">
  <span>جميع الحقوق محفوظة ©️ 2026 | AI Product Builder - Layan Khalil</span>
</div>
""", unsafe_allow_html=True)
