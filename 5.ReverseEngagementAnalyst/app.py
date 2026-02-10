import streamlit as st
import os
import json
import time
import hashlib
from datetime import datetime, timezone
from supabase import create_client, Client
from postgrest.exceptions import APIError
from google import genai
from google.genai import types
import re

# =========================================================
# 0) PAGE CONFIG
# =========================================================
st.set_page_config(
    page_title="محلّل التفاعل المضاد",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# =========================================================
# LANGUAGE SWITCH
# =========================================================
if "ui_lang" not in st.session_state:
    st.session_state["ui_lang"] = "AR"

lang_toggle = st.toggle("English", value=(st.session_state["ui_lang"] == "EN"))
st.session_state["ui_lang"] = "EN" if lang_toggle else "AR"
IS_EN = (st.session_state["ui_lang"] == "EN")

# =========================================================
# SECRETS
# =========================================================
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

APP_ID = "5-reverse-engagement"

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

# =========================================================
# CACHE + CTA
# =========================================================
def make_content_hash(text: str):
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()

def cache_get(app_id, content_hash):
    try:
        res = (
            supabase.table("viral_scores_cache")
            .select("analysis_text")
            .eq("app_id", app_id)
            .eq("content_hash", content_hash)
            .limit(1)
            .execute()
        )
        return json.loads(res.data[0]["analysis_text"]) if res.data else None
    except Exception:
        return None

def cache_set(app_id, content_hash, analysis):
    try:
        supabase.table("viral_scores_cache").upsert(
            {
                "app_id": app_id,
                "content_hash": content_hash,
                "analysis_text": json.dumps(analysis, ensure_ascii=False),
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
            on_conflict="app_id,content_hash",
        ).execute()
    except Exception:
        pass

def track_cta_event(app_id):
    try:
        supabase.rpc("increment_cta", {"p_app_id": app_id}).execute()
    except Exception:
        pass

# =========================================================
# FEEDBACK (same style as previous tools)
# =========================================================
def save_feedback_via_rpc(
    app_name: str,
    useful: bool,
    missing_reason: str | None,
    problem_text: str | None,
    helpful_reason: str | None,
    must_use_text: str | None,
):
    return supabase.rpc(
        "submit_app_feedback",
        {
            "p_app_name": app_name,
            "p_useful": useful,
            "p_missing_reason": missing_reason,
            "p_problem_text": problem_text,
            "p_helpful_reason": helpful_reason,
            "p_must_use_text": must_use_text,
        },
    ).execute()

# =========================================================
# RTL / LTR CSS (STRICT)
# =========================================================
DIR = "ltr" if IS_EN else "rtl"
ALIGN = "left" if IS_EN else "right"

st.markdown(
    f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Cairo:wght@400;700&display=swap');
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

html, body, [data-testid="stAppViewContainer"], .main {{
    direction: {DIR} !important;
    text-align: {ALIGN} !important;
    font-family: 'Cairo', sans-serif !important;
}}

* {{
    box-sizing: border-box;
}}

h1, h2, h3, h4, h5, h6,
p, div, span, li,
[data-testid="stMarkdownContainer"] {{
    direction: {DIR} !important;
    text-align: {ALIGN} !important;
    unicode-bidi: plaintext !important;
    line-height: 1.75 !important;
}}

[data-testid="stExpander"] * {{
    direction: {DIR} !important;
    text-align: {ALIGN} !important;
    unicode-bidi: plaintext !important;
}}

[data-testid="stTextInput"] label,
[data-testid="stTextArea"] label,
[data-testid="stRadio"] label,
[data-testid="stCaptionContainer"] {{
    direction: {DIR} !important;
    text-align: {ALIGN} !important;
    unicode-bidi: plaintext !important;
}}

.stButton > button {{
    background-color: #f75d5d !important;
    color: white !important;
    font-weight: 800 !important;
    border-radius: 14px !important;
    width: 100% !important;
    height: 3.3em !important;
    border: none !important;
}}

.stButton > button:hover {{
    filter: brightness(0.95);
    transform: scale(1.01);
}}

hr {{
    margin: 18px 0 !important;
}}

/* Footer always RTL like your previous tools */
.footer-container {{
    width: 100%;
    text-align: center;
    margin-top: 45px;
    padding-top: 18px;
    border-top: 1px solid #666;
    font-size: 13px;
    display: flex;
    justify-content: center;
    gap: 6px;
    flex-wrap: wrap;
    direction: rtl !important;
}}
.footer-container, .footer-container * {{
    direction: rtl !important;
    text-align: center !important;
}}
</style>
""",
    unsafe_allow_html=True,
)

# =========================================================
# HEADER + CAPTION
# =========================================================
if IS_EN:
    st.title("🔎 Reverse Engagement Analyzer")
    st.caption("Turn negative comments into a clear plan to fix perception and improve your message.")
else:
    st.title("🔎 محلل التفاعل المضاد")
    st.caption("حوّل التعليقات السلبية إلى خطة واضحة لتصحيح الانطباع وتحسين رسالتك.")

# =========================================================
# EXPANDER (short + clear + example)
# =========================================================
with st.expander("What is this tool?" if IS_EN else "ما هي هذه الأداة؟", expanded=True):
    if IS_EN:
        st.markdown("""
This tool helps you understand negative comments instead of ignoring them.

Sometimes people leave critical feedback on:
- Your posts or videos
- Your product or service
- A campaign or a new idea

Behind these comments, there is often a real concern or something unclear to your audience.

This tool analyzes negative feedback to help you discover:
- What is actually frustrating your audience
- Where the blind spots exist in your message or product
- What can be improved in a practical way

Designed for creators, founders, marketers, and anyone who wants to turn criticism into improvement instead of taking it as an attack.

The goal is not to judge your content,
but to help you see things from your audience’s perspective and make better decisions.
""")
    else:
        st.markdown("""
هذه الأداة تساعدك على فهم التعليقات السلبية بدل تجاهلها.

أحياناً الناس تكتب تعليقات ناقدة على:
- منشوراتك أو فيديوهاتك
- منتجك أو خدمتك
- إعلان أو فكرة جديدة

لكن خلف هذه التعليقات يوجد غالباً سبب حقيقي أو نقطة غير واضحة للجمهور.

هذه الأداة تحلل التعليقات السلبية وتساعدك على اكتشاف:
- ما الذي يزعج الجمهور فعلاً
- أين توجد النقاط العمياء في الرسالة أو المنتج
- ماذا يمكن تحسينه بشكل عملي

مقدمة لصنّاع المحتوى، أصحاب المشاريع، المسوّقين، وأي شخص يريد تحويل النقد إلى فرصة تحسين بدلاً من اعتباره هجوماً.

الهدف ليس الحكم على المحتوى،
بل مساعدتك على رؤية الصورة من زاوية الجمهور وبناء قرارات أفضل.
""")

# =========================================================
# TESTIMONIALS (LTR always)  ✅ FIXED: خارج الـexpander + بدون كسر نصوص بايثون
# =========================================================
st.markdown("---")

TESTIMONIALS_HTML = r"""
<style>
.testimonial-title{
  text-align:center;
  font-size:20px;
  font-weight:800;
  margin: 10px 0 12px 0;
  direction:ltr !important;
  unicode-bidi: plaintext !important;
  color: inherit !important; /* يشتغل مع light/dark */
}
.testimonial-wrapper{
  display:flex;
  gap:14px;
  overflow-x:auto;
  padding: 8px 8px 14px 8px;
  scroll-snap-type:x mandatory;
  -webkit-overflow-scrolling: touch;
}
.testimonial-wrapper::-webkit-scrollbar{height:8px;}
.testimonial-wrapper::-webkit-scrollbar-thumb{
  background: rgba(0,0,0,0.18);
  border-radius: 99px;
}

/* ✅ توحيد طول الكروت + مساحة أكبر للكلام */
.testimonial-card{
  flex: 0 0 auto;
  width: 320px;
  max-width: 86vw;
  background: #0e1117;
  border: 1px solid rgba(255,255,255,0.14);
  border-left: 5px solid #e63946;
  border-radius: 14px;
  padding: 16px;
  scroll-snap-align:center;

  direction:ltr !important;
  text-align:center !important;
  unicode-bidi: plaintext !important;

  min-height: 220px; /* ✅ نفس الطول لكل الكروت */
  display:flex;
  flex-direction:column;
  justify-content:center;
}

.testimonial-text{
  color: rgba(255,255,255,0.92) !important; /* ✅ واضح حتى لو الثيم فاتح */
  font-size: 13px;
  line-height: 1.55;
  margin:0 !important;
  padding:0 !important;

  direction:ltr !important;
  text-align:center !important;
  unicode-bidi: plaintext !important;
}

.testimonial-author{
  margin-top:12px;
  font-weight:700;
  color: rgba(255,255,255,0.75) !important;
  font-size: 13px;

  direction:ltr !important;
  text-align:center !important;
  unicode-bidi: plaintext !important;
}
</style>

<div class="testimonial-title">💬 What users are saying</div>

<div class="testimonial-wrapper">
  <div class="testimonial-card">
    <div class="testimonial-text">
      I tested the tool on a TikTok product, and the analysis was better than expected.
    </div>
    <div class="testimonial-author">— Saleem Khalil</div>
  </div>

  <div class="testimonial-card">
    <div class="testimonial-text">
      Love this idea. Most tools ignore negative comments or label them as ‘hate’, but this actually helps understand why people react that way.
      Super useful for creators who want to improve instead of getting defensive.
    </div>
    <div class="testimonial-author">— Rohit Gautam</div>
  </div>
</div>
"""
st.markdown(TESTIMONIALS_HTML, unsafe_allow_html=True)

# =========================================================
# INPUTS + PLACEHOLDERS
# =========================================================
if IS_EN:
    ctx_val = st.text_input(
        "📌 What received the negative comments?",
        placeholder="Example: A video explaining how to start a business with no capital",
    )
    st.caption("Briefly describe the product, post, message, or idea people reacted to.")
    comm_val = st.text_area(
        "🧾 Paste negative comments here",
        height=200,
        placeholder="Example:\n- This feels generic.\n- I don’t trust this.\n- Too salesy.\n- What’s the real value?\n(You can paste many comments.)",
    )
    btn_label = "🚨 Analyze Blind Spots"
else:
    ctx_val = st.text_input(
        "📌 ما هو الشيء الذي حصلت عليه التعليقات السلبية؟",
        placeholder=" مثال: فيديو نشرته على الانستغرام أشرح فيه للجمهور كيف تبدأ مشروع بدون رأس مال  ",
    )
    st.caption("اكتب بإختصار: هل في فكرة، إعلان، منتج، فيديو، أو بوست")

    comm_val = st.text_area(
        "🧾 الصق التعليقات السلبية هنا",
        height=200,
        placeholder="مثال:\n- الكلام عام.\n- ما حسّيت بمصداقية.\n- تسويق زيادة.\n- شو القيمة الحقيقية؟\n(بإمكانك تلصقي عدة تعليقات.)",
    )
    btn_label = "🚨 تحليل النقاط العمياء"

# =========================================================
# MODEL LOGIC (unchanged)
# =========================================================
def clean_json_text(text):
    match = re.search(r"\{.*\}", text, re.DOTALL)
    return match.group(0) if match else text

def analyze_reverse_engagement(raw_comments, context, lang_name):
    current_model = get_working_model()
    prompt = f"""
Analyze the following negative comments to identify blind spots.

Context: {context}
Comments: {raw_comments}

Return ONLY JSON in {lang_name}:
{{
  "BlindSpotCategories": ["category 1", "category 2"],
  "CoreBlindSpot": "The most dangerous blind spot",
  "ActionableInsights": ["step 1", "step 2", "step 3"],
  "SentimentSummary": "Summary of overall negative sentiment"
}}
* Note: Provide deep, non-shortened analysis.
"""
    cfg = types.GenerateContentConfig(
        response_mime_type="application/json",
        temperature=0.5,
        max_output_tokens=4000,
    )
    resp = genai_client.models.generate_content(model=current_model, contents=prompt, config=cfg)
    return json.loads(clean_json_text(resp.text))

# =========================================================
# RUN
# =========================================================
if st.button(btn_label):
    if not comm_val.strip():
        st.warning("Please add comments." if IS_EN else "يرجى إضافة التعليقات.")
    else:
        track_cta_event(APP_ID)

        c_hash = make_content_hash(f"{ctx_val}{comm_val}{st.session_state['ui_lang']}")
        cached = cache_get(APP_ID, c_hash)

        if cached:
            res = cached
        else:
            with st.spinner("Analyzing..." if IS_EN else "جاري التحليل..."):
                l_name = "English" if IS_EN else "Arabic"
                res = analyze_reverse_engagement(comm_val, ctx_val, l_name)
                if "error" not in res:
                    cache_set(APP_ID, c_hash, res)

        if "error" in res:
            st.error(res["error"])
        else:
            st.session_state["reverse_res"] = res
            st.session_state["has_result"] = True

# =========================================================
# RESULTS (RTL/LTR enforced by CSS)
# =========================================================
if st.session_state.get("has_result") and "reverse_res" in st.session_state:
    data = st.session_state["reverse_res"]

    st.markdown("---")

    if IS_EN:
        st.header("📊 Results")
        st.markdown("### 🎯 Critical Blind Spot")
        st.warning(data.get("CoreBlindSpot", "—"))

        col1, col2 = st.columns(2)
        with col1:
            st.markdown("#### 🔴 Criticism Categories")
            cats = data.get("BlindSpotCategories", [])
            if isinstance(cats, list) and cats:
                for cat in cats:
                    st.markdown(f"- {cat}")
            else:
                st.markdown("—")

        with col2:
            st.markdown("#### 💔 Sentiment Summary")
            st.info(data.get("SentimentSummary", "—"))

        st.markdown("### 🛠️ Action Steps")
        steps = data.get("ActionableInsights", [])
        if isinstance(steps, list) and steps:
            for i, step in enumerate(steps, 1):
                st.markdown(f"{i}. **{step}**")
        else:
            st.markdown("—")

    else:
        st.header("📊 نتائج التحليل")
        st.markdown("### 🎯 أخطر نقطة عمياء")
        st.warning(data.get("CoreBlindSpot", "—"))

        col1, col2 = st.columns(2)
        with col1:
            st.markdown("#### 🔴 فئات النقد")
            cats = data.get("BlindSpotCategories", [])
            if isinstance(cats, list) and cats:
                for cat in cats:
                    st.markdown(f"- {cat}")
            else:
                st.markdown("—")

        with col2:
            st.markdown("#### 💔 ملخص المشاعر")
            st.info(data.get("SentimentSummary", "—"))

        st.markdown("### 🛠️ خطوات إصلاح فورية")
        steps = data.get("ActionableInsights", [])
        if isinstance(steps, list) and steps:
            for i, step in enumerate(steps, 1):
                st.markdown(f"{i}. **{step}**")
        else:
            st.markdown("—")

    # =========================================================
    # FEEDBACK (same as previous tools)
    # =========================================================
    st.divider()
    st.subheader("📝 Feedback" if IS_EN else "📝 ساعدنا نطوّر الأداة بناءً على رأيك")

    feedback_choice = st.radio(
        "How was your experience?" if IS_EN else "كيف كانت تجربتك مع هذه الأداة؟",
        ("This tool was useful for me", "This tool was not useful") if IS_EN
        else ("هذه الأداة كانت مفيدة بالنسبة لي", "هذه الأداة لم تكن مفيدة"),
        key=f"{APP_ID}_feedback_choice",
    )

    useful = feedback_choice == ("This tool was useful for me" if IS_EN else "هذه الأداة كانت مفيدة بالنسبة لي")

    missing_reason = None
    if not useful:
        missing_reason = st.text_input(
            "What was missing? (one sentence)" if IS_EN else "ما الذي كان ناقصاً؟ (جملة واحدة)",
            max_chars=200,
            key=f"{APP_ID}_missing_reason",
            placeholder="Example: needs clearer steps / export option / more detailed categories" if IS_EN
            else "مثال: بدي خطوات أوضح / خيار تصدير / تفاصيل أكثر",
        )

    with st.expander("Quick feedback (3 questions)" if IS_EN else "فيدباك سريع (3 أسئلة)", expanded=False):
        problem_text = st.text_area(
            "1) What problem were you trying to solve?"
            if IS_EN
            else "1) ما المشكلة التي كنت تحاول حلّها؟",
            max_chars=280,
            key=f"{APP_ID}_problem_text",
            placeholder="Example: I want to understand why people react negatively" if IS_EN
            else "مثال: بدي أفهم ليش الناس بتنتقد / شو نقطة الضعف",
        )

        helpful_reason = st.text_area(
            "2) Did it help? Why yes/no?"
            if IS_EN
            else "2) هل ساعدتك الأداة؟ لماذا نعم/لا؟",
            max_chars=280,
            key=f"{APP_ID}_helpful_reason",
            placeholder="Example: It pinpointed the main issue + gave steps" if IS_EN
            else "مثال: حددت المشكلة الأساسية + أعطتني خطوات",
        )

        must_use_text = st.text_area(
            "3) What would make this a must-use tool for you?"
            if IS_EN
            else "3) ما الذي سيجعل هذه الأداة «لازم تُستخدم» بالنسبة لك؟",
            max_chars=280,
            key=f"{APP_ID}_must_use_text",
            placeholder="Example: export PDF / save history / compare versions" if IS_EN
            else "مثال: تصدير PDF / حفظ النتائج / مقارنة نسخ",
        )

        submit_feedback = st.button("✅ Submit feedback" if IS_EN else "✅ إرسال الفيدباك", key=f"{APP_ID}_submit_feedback")

        if submit_feedback:
            has_any_text = any(
                [
                    (missing_reason or "").strip(),
                    (problem_text or "").strip(),
                    (helpful_reason or "").strip(),
                    (must_use_text or "").strip(),
                ]
            )

            if (not useful) and (not has_any_text):
                st.warning("Write at least one line." if IS_EN else "اكتب سطر واحد على الأقل 🙏")
            else:
                try:
                    save_feedback_via_rpc(
                        app_name=APP_ID,
                        useful=useful,
                        missing_reason=(missing_reason or "").strip() or None,
                        problem_text=(problem_text or "").strip() or None,
                        helpful_reason=(helpful_reason or "").strip() or None,
                        must_use_text=(must_use_text or "").strip() or None,
                    )
                    st.success("Feedback saved ✅" if IS_EN else "تم حفظ الفيدباك ✅ شكرًا لك!")
                except APIError as e:
                    st.error("Supabase APIError:" if IS_EN else "خطأ من Supabase:")
                    try:
                        st.json(e.args[0])
                    except Exception:
                        st.write(str(e))
                except Exception as e:
                    st.exception(e)

# =========================================================
# FOOTER (HTML direct)
# =========================================================
st.markdown(
    """
<div class="footer-container">
  <span>جميع الحقوق محفوظة © 2026 |</span>
  <span>AI Product Builder - Layan Khalil</span>
</div>
""",
    unsafe_allow_html=True,
)
