import streamlit as st
import os
import json
import time
import hashlib
import re
from datetime import datetime, timezone

# محاولة استيراد supabase بشكل آمن
try:
    from supabase import create_client, Client
    from postgrest.exceptions import APIError
except ImportError:
    create_client = None
    Client = None
    APIError = Exception

from google import genai
from google.genai import types as g_types
from google.api_core.exceptions import ResourceExhausted, ServiceUnavailable, DeadlineExceeded


# =========================================================
# 0) PAGE CONFIG
# =========================================================

st.set_page_config(
    page_title="Digital Identity Analyzer",
    layout="wide",
    initial_sidebar_state="collapsed",
)

APP_ID = "11-digital-identity-analyzer"

MODEL_CANDIDATES = [
    "gemini-2.0-flash-exp",
    "gemini-1.5-flash",
    "gemini-1.5-pro",
]

MAX_RETRIES = 4
INITIAL_DELAY = 3
CACHE_VERSION_TAG = "identity_v3"


# =========================================================
# 1) LANGUAGE SWITCH & GLOBAL RTL FIX
# =========================================================

if "ui_lang" not in st.session_state:
    st.session_state["ui_lang"] = "AR"

lang_toggle = st.toggle("English", value=(st.session_state["ui_lang"] == "EN"))
st.session_state["ui_lang"] = "EN" if lang_toggle else "AR"

IS_EN = (st.session_state["ui_lang"] == "EN")

DIR = "ltr" if IS_EN else "rtl"
ALIGN = "left" if IS_EN else "right"

# كود CSS مكثف لفرض اتجاه اليمين لليسار ومنع انقلاب الكلمات العربية
st.markdown(f"""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Cairo:wght@400;700&display=swap');

    html, body, [data-testid="stAppViewContainer"], .main {{
        direction: {DIR} !important;
        text-align: {ALIGN} !important;
        font-family: 'Cairo', sans-serif !important;
    }}

    [data-testid="stMarkdownContainer"] p, 
    [data-testid="stMarkdownContainer"] h1, 
    [data-testid="stMarkdownContainer"] h2, 
    [data-testid="stMarkdownContainer"] h3 {{
        direction: {DIR} !important;
        text-align: {ALIGN} !important;
        unicode-bidi: plaintext !important;
    }}

    /* إصلاح حقول الإدخال لتكون RTL */
    .stTextArea textarea, .stTextInput input {{
        direction: {DIR} !important;
        text-align: {ALIGN} !important;
    }}
    
    /* منع الـ JSON من الانقلاب (يجب أن يبقى LTR) */
    code, pre {{
        direction: ltr !important;
        text-align: left !important;
    }}
</style>
""", unsafe_allow_html=True)

# =========================================================
# 2) FIXED ARABIC TEXTS (داخل متغير TXT)
# =========================================================

TXT = {
    "title": "Digital Identity Analyzer" if IS_EN else "محلل الهوية الرقمية",
    "sub": (
        "Analyze consistency between your content and declared identity."
        if IS_EN else "حلل التناسق بين محتواك وهويتك المعلنة والهوية البصرية."
    ),
    "identity": "Your declared identity" if IS_EN else "هويتك المعلنة",
    "goal": "Your content goal" if IS_EN else "هدف المحتوى",
    "samples": "Content samples" if IS_EN else "عينات المحتوى",
    "upload": "Upload profile screenshot" if IS_EN else "ارفع لقطة شاشة للحساب",
    "btn": "Analyze identity" if IS_EN else "تحليل الهوية",
    "result": "Analysis Result" if IS_EN else "نتيجة التحليل",
    "matrix": "Consistency Matrix" if IS_EN else "مصفوفة التناسق",
    "summary": "Observed Identity" if IS_EN else "الهوية الفعلية الملاحظة",
    "strategy": "Strategic Adjustments" if IS_EN else "التعديلات الاستراتيجية المقترحة",
    "warn": "Fill all required fields" if IS_EN else "يرجى تعبئة جميع الحقول المطلوبة",
    "spinner": "Analyzing..." if IS_EN else "جاري التحليل، يرجى الانتظار...",

    "fb_title": "Feedback" if IS_EN else "رأيك يهمنا",
    "fb_q": "How was your experience?" if IS_EN else "كيف كانت تجربتك مع الأداة؟",
    "fb_yes": "Useful tool" if IS_EN else "الأداة مفيدة جداً",
    "fb_no": "Not useful" if IS_EN else "الأداة غير مفيدة",
    "fb_missing": "What was missing?" if IS_EN else "ما الذي كان ينقص الأداة؟",
    "fb_exp": "Quick feedback" if IS_EN else "تقديم فيدباك سريع",
    "fb_p1": "What problem were you solving?" if IS_EN else "ما المشكلة التي حاولت حلها؟",
    "fb_p2": "Did it help? Why?" if IS_EN else "هل ساعدتك الأداة؟ ولماذا؟",
    "fb_p3": "What would make it essential?" if IS_EN else "ما الذي يجعل هذه الأداة ضرورية لك؟",
    "fb_btn": "Submit feedback" if IS_EN else "إرسال التقييم",
    "fb_warn": "Write at least one line." if IS_EN else "يرجى كتابة سطر واحد على الأقل.",
    "fb_ok": "Feedback saved" if IS_EN else "تم حفظ رأيك بنجاح، شكراً لك!"
}


# =========================================================
# 3) SECRETS & SETUP
# =========================================================

def get_secret(key):
    return st.secrets.get(key) or os.environ.get(key)

SUPABASE_URL = get_secret("SUPABASE_URL")
SUPABASE_KEY = get_secret("SUPABASE_KEY")
GOOGLE_API_KEY = get_secret("GOOGLE_API_KEY") or get_secret("GEMINI_API_KEY")

if not all([SUPABASE_URL, SUPABASE_KEY, GOOGLE_API_KEY]):
    st.error("Missing Secrets!")
    st.stop()

supabase = create_client(SUPABASE_URL, SUPABASE_KEY) if create_client else None
genai_client = genai.Client(api_key=GOOGLE_API_KEY)


# =========================================================
# 4) CACHE & LOGIC
# =========================================================

def make_hash(identity, goal, samples):
    payload = f"{CACHE_VERSION_TAG}||{identity}||{goal}||{samples}"
    return hashlib.sha256(payload.encode()).hexdigest()

def cache_get(hash_id):
    if not supabase: return None
    try:
        res = supabase.table("viral_scores_cache").select("analysis_text").eq("app_id", APP_ID).eq("content_hash", hash_id).limit(1).execute()
        if res.data: return json.loads(res.data[0]["analysis_text"])
    except: pass
    return None

def cache_set(hash_id, payload):
    if not supabase or not payload or "error" in payload: return
    try:
        supabase.table("viral_scores_cache").upsert({
            "app_id": APP_ID, "content_hash": hash_id, "analysis_text": json.dumps(payload), "created_at": datetime.now(timezone.utc).isoformat()
        }, on_conflict="app_id,content_hash").execute()
    except: pass

def get_model():
    if "model_identity" in st.session_state: return st.session_state["model_identity"]
    for m in MODEL_CANDIDATES:
        try:
            genai_client.models.generate_content(model=m, contents="ping")
            st.session_state["model_identity"] = m
            return m
        except: continue
    return "gemini-1.5-flash"

def extract_json_safely(text):
    if not text: return None
    text = re.sub(r"```json\s*|```", "", text).strip()
    start, end = text.find('{'), text.rfind('}')
    if start != -1 and end != -1:
        try: return json.loads(text[start:end+1])
        except: return None
    return None

def analyze_identity(identity, goal, samples, image_part):
    prompt = f"Analyze identity. Declared: {identity}. Goal: {goal}. Content: {samples}. Return JSON with ConsistencyMatrix, ObservedIdentitySummary, StrategicAdjustments."
    
    config = g_types.GenerateContentConfig(
        system_instruction="You are a professional strategist. Always respond in valid JSON.",
        temperature=0.1,
        max_output_tokens=1500
    )

    for attempt in range(MAX_RETRIES):
        try:
            response = genai_client.models.generate_content(model=get_model(), contents=[image_part, g_types.Part(text=prompt)], config=config)
            data = extract_json_safely(response.text)
            if data: return data
        except: time.sleep(INITIAL_DELAY * (attempt + 1))
    return {"error": "Analysis failed."}

# =========================================================
# 5) MAIN UI
# =========================================================

st.title(TXT["title"])
st.caption(TXT["sub"])

samples = st.text_area(TXT["samples"], height=150)
c1, c2 = st.columns(2)
with c1: identity = st.text_area(TXT["identity"], height=100)
with c2: goal = st.text_area(TXT["goal"], height=100)
image = st.file_uploader(TXT["upload"], type=["png", "jpg", "jpeg"])

if st.button(TXT["btn"]):
    if not all([identity, goal, samples, image]):
        st.warning(TXT["warn"])
    else:
        h = make_hash(identity, goal, samples)
        res = cache_get(h)
        if not res:
            img = g_types.Part.from_bytes(data=image.getvalue(), mime_type=image.type)
            with st.spinner(TXT["spinner"]):
                res = analyze_identity(identity, goal, samples, img)
            cache_set(h, res)
        
        if "error" in res:
            st.error(res["error"])
        else:
            st.markdown(f"### {TXT['matrix']}")
            st.json(res.get("ConsistencyMatrix", {}))
            st.markdown(f"### {TXT['summary']}")
            st.write(res.get("ObservedIdentitySummary", ""))
            st.markdown(f"### {TXT['strategy']}")
            st.write(res.get("StrategicAdjustments", ""))

# =========================================================
# 6) FOOTER
# =========================================================

st.markdown('<div style="text-align:center;margin-top:50px;font-size:12px;">© 2026 Layan Khalil</div>', unsafe_allow_html=True)
