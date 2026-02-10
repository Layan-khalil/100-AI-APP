import streamlit as st
import uuid
import hashlib
import time
from supabase import create_client, Client
from google import genai
from google.genai import types
from google.api_core.exceptions import ResourceExhausted, ServiceUnavailable, DeadlineExceeded

# =====================================
# Page Config
# =====================================
st.set_page_config(
    page_title="Viral Potential Scorer",
    layout="centered"
)

# =====================================
# Language Switch
# =====================================
if "ui_lang" not in st.session_state:
    st.session_state["ui_lang"] = "AR"

lang_toggle = st.toggle("English", value=(st.session_state["ui_lang"] == "EN"))
st.session_state["ui_lang"] = "EN" if lang_toggle else "AR"
IS_EN = st.session_state["ui_lang"] == "EN"

# =====================================
# Secrets
# =====================================
SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
GOOGLE_API_KEY = st.secrets["GOOGLE_API_KEY"]

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
genai_client = genai.Client(api_key=GOOGLE_API_KEY)

APP_ID = "viral-potential-scorer-v1"
MODEL_NAME = "gemini-1.5-flash"

# =====================================
# CSS (FIX LINE SPACING ISSUE)
# =====================================
DIR = "ltr" if IS_EN else "rtl"
ALIGN = "left" if IS_EN else "right"

st.markdown(f"""
<style>

html, body, .stApp {{
    direction:{DIR};
    text-align:{ALIGN};
}}

p {{
    margin: 6px 0 !important;
    line-height: 1.6 !important;
}}

.result-text {{
    white-space: pre-wrap;
    line-height: 1.7;
}}

footer {{
    text-align:center;
    margin-top:40px;
    color:#777;
    font-size:13px;
}}

.stButton > button {{
    background:#e63946;
    color:white;
    font-weight:700;
    border-radius:20px;
    width:100%;
}}

</style>
""", unsafe_allow_html=True)

# =====================================
# Helpers
# =====================================
def get_hash(text):
    return hashlib.sha256(text.encode()).hexdigest()

def get_analysis(text):

    content_hash = get_hash(text)

    # ---- cache read ----
    try:
        res = supabase.table("viral_scores_cache")\
            .select("analysis_text")\
            .eq("app_id", APP_ID)\
            .eq("content_hash", content_hash)\
            .limit(1).execute()

        if res.data:
            return res.data[0]["analysis_text"]
    except:
        pass

    # ---- prompt ----
    if IS_EN:
        prompt = f"""
Analyze this content using STEPPS framework:
Social Currency, Triggers, Emotion, Public, Practical Value, Stories.
Give score /10 and explanation for each.
Language: English.

{text}
"""
    else:
        prompt = f"""
حلل هذا النص باستخدام نموذج STEPPS:
العملة الاجتماعية، المحفزات، المشاعر، الظهور العلني، القيمة العملية، القصص.
اعط درجة من 10 وشرح لكل عامل.
اللغة العربية.

{text}
"""

    for _ in range(3):
        try:
            response = genai_client.models.generate_content(
                model=MODEL_NAME,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.7,
                    max_output_tokens=3000
                )
            )
            analysis = response.text
            break
        except (ResourceExhausted, ServiceUnavailable, DeadlineExceeded):
            time.sleep(2)
    else:
        return "Error generating analysis"

    # ---- cache write ----
    try:
        supabase.table("viral_scores_cache").insert({
            "app_id": APP_ID,
            "content_hash": content_hash,
            "analysis_text": analysis
        }).execute()
    except:
        pass

    return analysis

# =====================================
# UI
# =====================================

st.title(
    "🎯 Viral Potential Scorer"
    if IS_EN else
    "🎯 مُحلّل احتمالية الانتشار الفيروسي"
)

# -------- Expander STEPPS --------
with st.expander("💡 STEPPS Framework Explanation" if IS_EN else "💡 شرح نموذج STEPPS"):

    if IS_EN:
        st.markdown("""
**STEPPS** explains why people share content:

- **Social Currency** — makes people look smart when sharing.
- **Triggers** — reminds people of your content regularly.
- **Emotion** — strong emotions increase sharing.
- **Public** — visible content spreads faster.
- **Practical Value** — useful content gets saved & shared.
- **Stories** — stories make ideas memorable.
""")
    else:
        st.markdown("""
نموذج **STEPPS** يشرح لماذا ينتشر المحتوى:

- **العملة الاجتماعية**: المحتوى الذي يجعل الشخص يبدو ذكياً عند مشاركته.
- **المحفزات**: أشياء تذكّر الناس بالمحتوى باستمرار.
- **المشاعر**: المحتوى الذي يثير مشاعر قوية ينتشر أكثر.
- **الظهور العلني**: كلما كان المحتوى مرئياً زادت فرصة انتشاره.
- **القيمة العملية**: المحتوى المفيد يتم حفظه ومشاركته.
- **القصص**: القصة تجعل الفكرة أسهل للتذكر والنقل.
""")

st.markdown("---")

# -------- Testimonials --------
st.markdown("""
<div class="testimonial-title">💬 What users are saying</div>
<div class="testimonial-wrapper">
<div class="testimonial-card">
Great tool. Helped me understand why some posts perform better.
</div>
<div class="testimonial-card">
Simple but powerful analysis. Very useful for creators.
</div>
</div>
""", unsafe_allow_html=True)

# -------- Input --------
post_text = st.text_area(
    "Paste content here" if IS_EN else "أدخل النص هنا",
    height=200
)

if st.button("Analyze 🚀" if IS_EN else "تحليل 🚀"):
    if len(post_text.strip()) < 20:
        st.warning("Enter valid content" if IS_EN else "أدخل نص حقيقي")
    else:
        with st.spinner("Analyzing..."):
            result = get_analysis(post_text)

        st.markdown(f"""
        <div class="result-text">{result}</div>
        """, unsafe_allow_html=True)

# -------- Footer --------
st.markdown("""
<footer>
© 2026 AI Product Builder — Layan Khalil
</footer>
""", unsafe_allow_html=True)
