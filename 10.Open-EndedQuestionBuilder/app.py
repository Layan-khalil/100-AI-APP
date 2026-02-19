import streamlit as st
import os
import json
import time
import re
import hashlib
from datetime import datetime, timezone

from supabase import create_client, Client
from postgrest.exceptions import APIError

from google import genai
from google.genai import types as g_types
from google.api_core.exceptions import ResourceExhausted, ServiceUnavailable, DeadlineExceeded


# =========================================================
# 0) PAGE CONFIG
# =========================================================
st.set_page_config(
    page_title="Open Question Builder",
    layout="wide",
    initial_sidebar_state="collapsed",
)

APP_ID = "8-open-question-builder"

MODEL_CANDIDATES = [
    "gemini-2.0-flash-001",
    "gemini-1.5-flash-001",
    "gemini-1.5-pro-001",
]

MAX_RETRIES = 4
INITIAL_DELAY = 3


# =========================================================
# 1) LANGUAGE SWITCH
# =========================================================
if "ui_lang" not in st.session_state:
    st.session_state["ui_lang"] = "AR"

lang_toggle = st.toggle("English", value=(st.session_state["ui_lang"] == "EN"))
st.session_state["ui_lang"] = "EN" if lang_toggle else "AR"
IS_EN = (st.session_state["ui_lang"] == "EN")

DIR = "ltr" if IS_EN else "rtl"
ALIGN = "left" if IS_EN else "right"


TXT = {
    "title": "💡 Open Question Builder" if IS_EN else "💡 مُنشئ الأسئلة المفتوحة",
    "sub": (
        "Generate a discussion-triggering, open-ended question + a short effectiveness analysis."
        if IS_EN else
        "أنشئ سؤالًا مفتوحًا يُحفّز نقاشًا طويلًا + تحليل قصير لماذا سينجح."
    ),
    "exp_title": "💡 What does this tool do?" if IS_EN else "💡 ما الذي تفعله هذه الأداة؟",
    "exp_body": (
        "- Generates **one** open-ended question that cannot be answered with Yes/No.\n"
        "- Then explains briefly **why** this question drives long comments.\n\n"
        "**Tip:** Specific topics + clear goal = better question."
        if IS_EN else
        "- تُولّد **سؤال واحد** مفتوح لا يمكن الرد عليه بـ نعم/لا.\n"
        "- ثم تشرح باختصار **لماذا** هذا السؤال سيجلب تعليقات طويلة.\n\n"
        "**نصيحة:** موضوع محدد + هدف واضح = سؤال أقوى."
    ),
    "topic": "1) Topic / Context" if IS_EN else "1) الموضوع / سياق السؤال",
    "goal": "2) Goal / Response type" if IS_EN else "2) الهدف / نوع الرد المطلوب",
    "aud": "3) Target audience (optional)" if IS_EN else "3) الجمهور المستهدف (اختياري)",
    "btn": "🔥 Generate question" if IS_EN else "🔥 توليد سؤال مفتوح",
    "warn_empty": "Please fill Topic and Goal." if IS_EN else "رجاءً املأ الموضوع والهدف.",
    "spinner": "Generating..." if IS_EN else "جاري التوليد...",
    "result_title": "💬 Suggested Question" if IS_EN else "💬 السؤال المقترح",
    "analysis_title": "✨ Why it works" if IS_EN else "✨ لماذا سينجح؟",
    "fb_title": "📝 Feedback" if IS_EN else "📝 ساعدنا نطوّر الأداة",
    "fb_q": "How was your experience?" if IS_EN else "كيف كانت تجربتك؟",
    "fb_yes": "This tool was useful for me" if IS_EN else "هذه الأداة كانت مفيدة بالنسبة لي",
    "fb_no": "This tool was not useful" if IS_EN else "هذه الأداة لم تكن مفيدة",
    "fb_missing": "What was missing? (one sentence)" if IS_EN else "ما الذي كان ناقصاً؟ (جملة واحدة)",
    "fb_exp": "Quick feedback (3 questions)" if IS_EN else "فيدباك سريع (3 أسئلة)",
    "fb_p1": "1) What problem were you trying to solve?" if IS_EN else "1) ما المشكلة التي كنتِ تحاولي حلّها؟",
    "fb_p2": "2) Did it help? Why yes/no?" if IS_EN else "2) هل ساعدتك؟ لماذا نعم/لا؟",
    "fb_p3": "3) What would make this a must-use tool for you?" if IS_EN else "3) ما الذي سيجعلها أداة «لازم تُستخدم»؟",
    "fb_btn": "✅ Submit feedback" if IS_EN else "✅ إرسال الفيدباك",
    "fb_warn": "Write at least one line." if IS_EN else "اكتب سطر واحد على الأقل 🙏",
    "fb_ok": "Feedback saved ✅" if IS_EN else "تم حفظ الفيدباك ✅",
    "wait": "Please wait a few seconds before trying again." if IS_EN else "استني شوي قبل المحاولة مرة ثانية.",
    "err_missing_secrets": "⚠️ Missing secrets in Secrets/Env." if IS_EN else "⚠️ مفاتيح الربط ناقصة في Secrets/Env.",
}


# =========================================================
# 2) SECRETS / CLIENTS
# =========================================================
def get_secret(key: str):
    return st.secrets.get(key) or os.environ.get(key)

SUPABASE_URL = get_secret("SUPABASE_URL")
SUPABASE_KEY = get_secret("SUPABASE_KEY")
GOOGLE_API_KEY = get_secret("GOOGLE_API_KEY") or get_secret("GEMINI_API_KEY")

if not all([SUPABASE_URL, SUPABASE_KEY, GOOGLE_API_KEY]):
    st.error(TXT["err_missing_secrets"])
    st.stop()

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
genai_client = genai.Client(api_key=GOOGLE_API_KEY)


# =========================================================
# 3) CSS (RTL/LTR unified)
# =========================================================
st.markdown(
    f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Cairo:wght@400;700;800;900&display=swap');

/* Hide streamlit chrome */
#MainMenu {{ visibility: hidden !important; }}
header {{ visibility: hidden !important; }}
footer {{ visibility: hidden !important; }}
div[data-testid="stToolbar"] {{ visibility: hidden !important; }}
div[data-testid="stStatusWidget"] {{ visibility: hidden !important; }}
div[data-testid="stDecoration"] {{ visibility: hidden !important; }}
div[class*="viewerBadge_container"] {{ display: none !important; }}
div[class*="viewerBadge_link"] {{ display: none !important; }}
div[class*="viewerBadge_text"] {{ display: none !important; }}

/* RTL/LTR Global */
html, body, [data-testid="stAppViewContainer"], .main {{
    direction: {DIR} !important;
    text-align: {ALIGN} !important;
    font-family: "Cairo", sans-serif !important;
}}

h1, h2, h3, h4, h5, h6, p, div, span, label, li, [data-testid="stMarkdownContainer"] {{
    direction: {DIR} !important;
    text-align: {ALIGN} !important;
    unicode-bidi: plaintext !important;
    line-height: 1.75 !important;
}}

textarea, input {{
    direction: {DIR} !important;
    text-align: {ALIGN} !important;
}}

/* Button */
.stButton > button {{
    font-weight: 900 !important;
    width: 100% !important;
    background-color: #7c3aed !important;
    color: #ffffff !important;
    border-radius: 14px !important;
    padding: 11px 18px !important;
    font-size: 1.05em !important;
    border: none !important;
    box-shadow: 0 4px 16px rgba(124,58,237,0.35) !important;
}}
.stButton > button:hover {{
    filter: brightness(0.95);
    transform: scale(1.01);
}}

/* Result card */
.result-card {{
    margin-top: 18px;
    padding: 22px;
    border-radius: 14px;
    background: #f5f3ff;
    border-right: {("0" if IS_EN else "8")}px solid #7c3aed;
    border-left: {("8" if IS_EN else "0")}px solid #7c3aed;
    box-shadow: 0 4px 12px rgba(0,0,0,0.10);
    color: #111111 !important;
}}
.result-title {{
    font-size: 1.2em;
    font-weight: 900;
    color: #1e293b !important;
    margin-bottom: 10px;
}}
.result-block {{
    background: rgba(255,255,255,0.65);
    border: 1px solid rgba(0,0,0,0.06);
    border-radius: 12px;
    padding: 14px 16px;
    margin-top: 10px;
    white-space: pre-wrap;
    word-break: break-word;
}}

/* Footer */
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
# 4) MODEL PICKER (ping once + store)
# =========================================================
def get_working_model() -> str:
    if "working_model_openq" in st.session_state:
        return st.session_state["working_model_openq"]

    cfg = g_types.GenerateContentConfig(max_output_tokens=8, temperature=0.0)

    for m in MODEL_CANDIDATES:
        try:
            _ = genai_client.models.generate_content(model=m, contents="ping", config=cfg)
            st.session_state["working_model_openq"] = m
            return m
        except Exception:
            continue

    st.session_state["working_model_openq"] = MODEL_CANDIDATES[0]
    return MODEL_CANDIDATES[0]


# =========================================================
# 5) CTA COUNT + CACHE + RATE LIMIT
# =========================================================
def track_cta_event(app_id: str):
    try:
        supabase.rpc("increment_cta", {"p_app_id": app_id}).execute()
    except Exception:
        pass

def make_hash(topic: str, goal: str, audience: str, lang: str) -> str:
    payload = f"{topic.strip()}||{goal.strip()}||{(audience or '').strip()}||{lang}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()

def cache_get(app_id: str, content_hash: str):
    try:
        res = (
            supabase.table("viral_scores_cache")
            .select("analysis_text")
            .eq("app_id", app_id)
            .eq("content_hash", content_hash)
            .limit(1)
            .execute()
        )
        data = getattr(res, "data", None) or []
        if data and isinstance(data, list):
            txt = data[0].get("analysis_text")
            if txt:
                return json.loads(txt) if isinstance(txt, str) else txt
    except Exception:
        pass
    return None

def cache_set(app_id: str, content_hash: str, payload: dict):
    try:
        supabase.table("viral_scores_cache").upsert(
            {
                "app_id": app_id,
                "content_hash": content_hash,
                "analysis_text": json.dumps(payload, ensure_ascii=False),
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
            on_conflict="app_id,content_hash",
        ).execute()
    except Exception:
        pass

def can_call_model(min_seconds: int = 8) -> bool:
    now = time.time()
    last = st.session_state.get("last_model_call_ts_openq", 0.0)
    if (now - last) < min_seconds:
        return False
    st.session_state["last_model_call_ts_openq"] = now
    return True


# =========================================================
# 6) FEEDBACK RPC
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
# 7) MODEL CALL (Open Question)
# =========================================================
def _extract_json_block(t: str) -> str:
    if not t:
        return ""
    s = t.strip()
    if s.startswith("```"):
        s = s.replace("```json", "").replace("```", "").strip()
    # try to locate first { ... last }
    start = s.find("{")
    end = s.rfind("}")
    if start != -1 and end != -1 and end > start:
        return s[start:end + 1]
    return s

def generate_open_question(topic: str, goal: str, audience: str, is_en: bool) -> dict:
    lang_name = "English" if is_en else "Arabic"

    system_prompt = (
        "You are a Conversation Catalyst for social media. "
        "Generate ONE highly engaging open-ended question that compels long, detailed responses and opinions "
        "and avoids simple Yes/No answers. "
        f"Return output in {lang_name}. "
        "Return ONLY valid JSON. No extra text."
    )

    prompt = f"""
Generate ONE open-ended question + a short analysis explaining why it works.

Inputs:
- Topic: {topic}
- Goal/Response type: {goal}
- Target Audience: {audience}

Return ONLY JSON with EXACT keys:
{{
  "GeneratedQuestion": "string",
  "EffectivenessAnalysis": "string"
}}
"""

    response_schema = {
        "type": "OBJECT",
        "properties": {
            "GeneratedQuestion": {"type": "STRING"},
            "EffectivenessAnalysis": {"type": "STRING"},
        },
        "propertyOrdering": ["GeneratedQuestion", "EffectivenessAnalysis"],
    }

    cfg = g_types.GenerateContentConfig(
        system_instruction=system_prompt,
        response_mime_type="application/json",
        response_schema=response_schema,
        temperature=0.5,
        max_output_tokens=700,
    )

    last_err = None
    for attempt in range(MAX_RETRIES):
        try:
            resp = genai_client.models.generate_content(
                model=get_working_model(),
                contents=prompt,
                config=cfg,
            )
            raw = _extract_json_block(getattr(resp, "text", "") or "")
            if not raw:
                return {"error": "Empty response" if is_en else "استجابة فارغة"}
            return json.loads(raw)

        except (ResourceExhausted, ServiceUnavailable, DeadlineExceeded) as e:
            last_err = e
            time.sleep(INITIAL_DELAY * (attempt + 1))
        except Exception as e:
            last_err = e
            break

    return {"error": str(last_err) if last_err else ("Model error" if is_en else "خطأ في الموديل")}


# =========================================================
# 8) UI
# =========================================================
st.title(TXT["title"])
st.caption(TXT["sub"])

with st.expander(TXT["exp_title"], expanded=True):
    st.markdown(TXT["exp_body"])

st.markdown("---")

col1, col2 = st.columns([2, 1])
with col1:
    topic = st.text_area(TXT["topic"], height=140, placeholder=("e.g., AI tools & content saturation..." if IS_EN else "مثال: تشبّع المحتوى في الذكاء الاصطناعي..."))
with col2:
    audience = st.text_input(TXT["aud"], placeholder=("e.g., founders, creators, AI builders" if IS_EN else "مثال: مؤسسين، صناع محتوى، AI builders"))

goal = st.text_area(TXT["goal"], height=110, placeholder=("What do you want people to write?" if IS_EN else "شو بدك الناس تكتب؟ (آراء/تجارب/نقاش...)"))

# session state
if f"{APP_ID}_has_result" not in st.session_state:
    st.session_state[f"{APP_ID}_has_result"] = False
if f"{APP_ID}_result" not in st.session_state:
    st.session_state[f"{APP_ID}_result"] = None

if st.button(TXT["btn"]):
    t = (topic or "").strip()
    g = (goal or "").strip()
    a = (audience or "").strip()

    if not t or not g:
        st.warning(TXT["warn_empty"])
        st.stop()

    # CTA count
    track_cta_event(APP_ID)

    # rate limit (client-side)
    if not can_call_model(min_seconds=8):
        st.warning(TXT["wait"])
        st.stop()

    # caching
    c_hash = make_hash(t, g, a, st.session_state["ui_lang"])
    cached = cache_get(APP_ID, c_hash)

    if cached and isinstance(cached, dict) and "GeneratedQuestion" in cached:
        st.session_state[f"{APP_ID}_result"] = cached
        st.session_state[f"{APP_ID}_has_result"] = True
    else:
        with st.spinner(TXT["spinner"]):
            res = generate_open_question(t, g, a, IS_EN)

        if isinstance(res, dict) and "error" not in res:
            cache_set(APP_ID, c_hash, res)
            st.session_state[f"{APP_ID}_result"] = res
            st.session_state[f"{APP_ID}_has_result"] = True
        else:
            st.error(res.get("error", "Unknown error"))


# =========================================================
# 9) RESULTS + FEEDBACK
# =========================================================
data = st.session_state.get(f"{APP_ID}_result") if st.session_state.get(f"{APP_ID}_has_result") else None

if isinstance(data, dict) and data and "GeneratedQuestion" in data:
    st.markdown("---")
    st.markdown(
        f"""
<div class="result-card">
  <div class="result-title">{TXT["result_title"]}</div>
  <div class="result-block">{data.get("GeneratedQuestion","—")}</div>

  <div class="result-title" style="margin-top:14px;">{TXT["analysis_title"]}</div>
  <div class="result-block">{data.get("EffectivenessAnalysis","—")}</div>
</div>
""",
        unsafe_allow_html=True,
    )

    # Feedback
    st.divider()
    st.subheader(TXT["fb_title"])

    feedback_choice = st.radio(
        TXT["fb_q"],
        (TXT["fb_yes"], TXT["fb_no"]),
        key=f"{APP_ID}_feedback_choice",
    )
    useful = (feedback_choice == TXT["fb_yes"])

    missing_reason = None
    if not useful:
        missing_reason = st.text_input(
            TXT["fb_missing"],
            max_chars=200,
            key=f"{APP_ID}_missing_reason",
        )

    with st.expander(TXT["fb_exp"], expanded=False):
        problem_text = st.text_area(TXT["fb_p1"], max_chars=280, key=f"{APP_ID}_problem_text")
        helpful_reason = st.text_area(TXT["fb_p2"], max_chars=280, key=f"{APP_ID}_helpful_reason")
        must_use_text = st.text_area(TXT["fb_p3"], max_chars=280, key=f"{APP_ID}_must_use_text")

        submit_feedback = st.button(TXT["fb_btn"], key=f"{APP_ID}_submit_feedback")
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
                st.warning(TXT["fb_warn"])
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
                    st.success(TXT["fb_ok"])
                except APIError as e:
                    try:
                        st.json(e.args[0])
                    except Exception:
                        st.write(str(e))
                except Exception as e:
                    st.exception(e)


# =========================================================
# 10) FOOTER
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
