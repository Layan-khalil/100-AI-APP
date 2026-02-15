import streamlit as st
import uuid
import hashlib
import os
import time
import re
import pandas as pd

from supabase import create_client, Client
from google import genai
from google.genai import types

# =========================================================
# 0) Page config
# =========================================================
st.set_page_config(
    page_title="منشئ المحتوى المفقود",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# =========================================================
# 1) Language switch
# =========================================================
if "ui_lang" not in st.session_state:
    st.session_state["ui_lang"] = "AR"

lang_choice = st.toggle("English", value=(st.session_state["ui_lang"] == "EN"))
st.session_state["ui_lang"] = "EN" if lang_choice else "AR"
IS_EN = (st.session_state["ui_lang"] == "EN")

DIR = "ltr" if IS_EN else "rtl"
ALIGN = "left" if IS_EN else "right"

# =========================================================
# 2) Secrets / Env + Clients
# =========================================================
def get_secret(key: str):
    if key in st.secrets:
        return st.secrets[key]
    return os.environ.get(key)

SUPABASE_URL = get_secret("SUPABASE_URL")
SUPABASE_KEY = get_secret("SUPABASE_KEY")
GOOGLE_API_KEY = get_secret("GOOGLE_API_KEY")

missing = []
if not SUPABASE_URL: missing.append("SUPABASE_URL")
if not SUPABASE_KEY: missing.append("SUPABASE_KEY")
if not GOOGLE_API_KEY: missing.append("GOOGLE_API_KEY")

if missing:
    st.error(
        ("⚠️ Missing secrets/env vars:\n\n" if IS_EN else "⚠️ القيم التالية غير موجودة في Secrets أو Environment Variables:\n\n")
        + "\n".join(f"• {m}" for m in missing)
    )
    st.stop()

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
genai_client = genai.Client(api_key=GOOGLE_API_KEY)

APP_ID = "missing-topic-generator"

# =========================================================
# 3) CSS
# =========================================================
st.markdown(
    f"""
<style>
#MainMenu {{ visibility: hidden; }}
footer {{ visibility: hidden; }}
header {{ visibility: hidden; }}
div[data-testid="stToolbar"] {{ visibility: hidden; }}
div[data-testid="stStatusWidget"] {{ visibility: hidden; }}
div[data-testid="stDecoration"] {{ visibility: hidden; }}
div[class*="viewerBadge_container"] {{ display: none !important; }}

html, body, [data-testid="stAppViewContainer"], .main {{
    direction: {DIR} !important;
    text-align: {ALIGN} !important;
    font-family: "Cairo", sans-serif !important;
}}

.stButton > button {{
    background-color: #e63946 !important;
    color: #ffffff !important;
    font-weight: 800 !important;
    border-radius: 28px !important;
    border: none !important;
    padding: 10px 20px !important;
    height: 3.1em !important;
    width: 100% !important;
    font-size: 17px !important;
    transition: 0.2s ease-in-out !important;
}}
.stButton > button:hover {{
    background-color: #c82333 !important;
    transform: scale(1.01);
}}

.footer-container {{
    width: 100%;
    text-align: center !important;
    margin-top: 40px;
    padding-top: 16px;
    border-top: 1px solid #666;
    font-size: 13px;
    display: flex;
    justify-content: center;
    gap: 6px;
    flex-wrap: wrap;
}}
</style>
""",
    unsafe_allow_html=True,
)

# =========================================================
# 4) Tracking
# =========================================================
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

# =========================================================
# 5) Model Helpers (Fixing the 404 & selection)
# =========================================================
def get_working_model():
    # نستخدم gemini-1.5-flash كخيار مستقر جداً لتجنب مشاكل الـ 404
    return "gemini-1.5-flash"

def call_model_with_retry(prompt: str, cfg: types.GenerateContentConfig, retries: int = 3) -> str:
    model_name = get_working_model()
    for attempt in range(retries):
        try:
            resp = genai_client.models.generate_content(model=model_name, contents=prompt, config=cfg)
            if resp.text: return resp.text.strip()
        except Exception:
            time.sleep(1.5 * (attempt + 1))
    return ""

# =========================================================
# 6) Analysis Core (ROOT FIX HERE)
# =========================================================
def get_content_hash(text: str) -> str:
    normalized = " ".join(text.strip().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

def parse_gap_response(raw: str):
    if not raw: return "", []
    lines = [l.strip() for l in raw.splitlines() if l.strip()]
    summary, topics, in_topics = "", [], False
    for line in lines:
        if line.upper().startswith("SUMMARY:"):
            summary = line.split(":", 1)[1].strip()
        elif line.upper().startswith("TOPICS"):
            in_topics = True
        elif in_topics:
            m = re.match(r"^\d+\.\s*(.*)$", line)
            if m:
                parts = [p.strip() for p in re.split(r"\s*\|\|\s*", m.group(1).strip())]
                if len(parts) >= 3:
                    topics.append({"topic_title": parts[0], "gap_reason": parts[1], "format_suggestion": " || ".join(parts[2:])})
    return summary, topics

def analyze_content_gaps(my_posts: str, competitor_posts: str) -> str:
    # Prompt logic...
    if IS_EN:
        prompt = f"Analyze gaps between these client posts: {my_posts} and competitors: {competitor_posts}. Return SUMMARY: ... and TOPICS: 1. Title || Reason || Format..."
    else:
        prompt = f"حلل فجوات المحتوى بين منشورات العميل: {my_posts} والمنافسين: {competitor_posts}. النتيجة يجب أن تكون SUMMARY: ... ثم TOPICS: 1. العنوان || السبب || القالب..."
    
    cfg = types.GenerateContentConfig(temperature=0.3, max_output_tokens=1400)
    return call_model_with_retry(prompt, cfg)

def get_or_create_gap_analysis(my_posts, competitor_posts):
    """
    ROOT FIX: Always returns 3 values to avoid 'too many values to unpack' error.
    Returns: (summary, topics, was_cached)
    """
    combined = my_posts.strip() + "\n\n---\n\n" + competitor_posts.strip()
    content_hash = get_content_hash(combined)

    # 1) Cache Read
    try:
        res = supabase.table("viral_scores_cache").select("analysis_text").eq("app_id", APP_ID).eq("content_hash", content_hash).limit(1).execute()
        if res.data:
            summary, topics = parse_gap_response(res.data[0]["analysis_text"])
            return summary, topics, True # Found in cache
    except: pass

    # 2) AI Call
    raw = analyze_content_gaps(my_posts, competitor_posts)
    if not raw:
        return "", [], False # Failed

    # 3) Cache Write
    try:
        supabase.table("viral_scores_cache").insert({"app_id": APP_ID, "content_hash": content_hash, "analysis_text": raw}).execute()
    except: pass

    summary, topics = parse_gap_response(raw)
    return summary, topics, False

# =========================================================
# 7) UI
# =========================================================
st.title("🧩 " + ("Missing Topic Generator" if IS_EN else "منشئ المحتوى المفقود"))

col1, col2 = st.columns(2)
with col1:
    my_posts_input = st.text_area("✍️ " + ("Your recent posts:" if IS_EN else "منشوراتك الأخيرة:"), height=250, key="my_posts")
with col2:
    competitor_posts_input = st.text_area("📌 " + ("Competitor posts:" if IS_EN else "منشورات المنافسين:"), height=250, key="comp_posts")

if st.button("🎯 " + ("Analyze gaps" if IS_EN else "تحليل الفجوات")):
    if my_posts_input.strip() and competitor_posts_input.strip():
        track_cta_event()
        with st.spinner("Analyzing..."):
            # Fixed call here to match the 3 return values
            sum_res, top_res, cached_res = get_or_create_gap_analysis(my_posts_input, competitor_posts_input)
            
            st.session_state["has_result"] = True
            st.session_state["summary"] = sum_res
            st.session_state["topics"] = top_res
            st.session_state["was_cached"] = cached_res
    else:
        st.warning("Please fill both fields.")

if st.session_state.get("has_result"):
    st.subheader("📊 " + ("Analysis Summary" if IS_EN else "ملخص التحليل"))
    st.write(st.session_state["summary"])
    
    if st.session_state["topics"]:
        df = pd.DataFrame(st.session_state["topics"])
        st.dataframe(df, use_container_width=True)

st.markdown("""<div class="footer-container">جميع الحقوق محفوظة © 2026 | AI Product Builder - Layan Khalil</div>""", unsafe_allow_html=True)
