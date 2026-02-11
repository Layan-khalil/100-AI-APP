import os
import re
import json
import time
import uuid
import hashlib
from datetime import datetime, timezone

import streamlit as st
from supabase import create_client, Client
from postgrest.exceptions import APIError

from google import genai
from google.genai import types as g_types
from google.api_core.exceptions import ResourceExhausted, ServiceUnavailable, DeadlineExceeded
from google.genai.errors import ClientError

# =========================================================
# 0) PAGE CONFIG
# =========================================================
st.set_page_config(
    page_title="Viral Timing Analyst",
    layout="wide",
    initial_sidebar_state="collapsed",
)

APP_ID = "6-viral-timing-analyst"

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

# =========================================================
# 2) SECRETS / ENV (NO KEYS IN CODE)
# =========================================================
def get_secret(key: str) -> str | None:
    # Prefer st.secrets, fallback to env vars
    try:
        if key in st.secrets:
            return st.secrets.get(key)
    except Exception:
        pass
    return os.environ.get(key)

SUPABASE_URL = get_secret("SUPABASE_URL")
SUPABASE_KEY = get_secret("SUPABASE_KEY")
GOOGLE_API_KEY = get_secret("GOOGLE_API_KEY") or get_secret("GEMINI_API_KEY")

missing = []
if not SUPABASE_URL:
    missing.append("SUPABASE_URL")
if not SUPABASE_KEY:
    missing.append("SUPABASE_KEY")
if not GOOGLE_API_KEY:
    missing.append("GOOGLE_API_KEY (or GEMINI_API_KEY)")

if missing:
    st.error(
        ("⚠️ Missing secrets/env:\n\n" if IS_EN else "⚠️ مفاتيح ناقصة في Secrets/Env:\n\n")
        + "\n".join([f"- {m}" for m in missing])
    )
    st.stop()

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
genai_client = genai.Client(api_key=GOOGLE_API_KEY)

# =========================================================
# 3) CSS (MATCH YOUR TOOLS STYLE + HIDE STREAMLIT HEADER/BADGES)
# =========================================================
st.markdown(
    f"""
<style>
/* Hide streamlit chrome */
#MainMenu {{ visibility: hidden; }}
header {{ visibility: hidden; }}
footer {{ visibility: hidden; }}
div[data-testid="stToolbar"] {{ visibility: hidden; }}
div[data-testid="stStatusWidget"] {{ visibility: hidden; }}
div[data-testid="stDecoration"] {{ visibility: hidden; }}
div[class*="viewerBadge_container"] {{ display: none !important; }}
div[class*="viewerBadge_link"] {{ display: none !important; }}
div[class*="viewerBadge_text"] {{ display: none !important; }}

/* Global */
html, body, [data-testid="stAppViewContainer"], .main {{
    direction: {DIR} !important;
    text-align: {ALIGN} !important;
    font-family: "Cairo", system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif !important;
}}
* {{ box-sizing: border-box; }}

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

/* Button */
.stButton > button {{
    font-weight: 800 !important;
    width: 100% !important;
    background-color: #f97316 !important;
    color: #ffffff !important;
    border: none !important;
    border-radius: 14px !important;
    padding: 10px 18px !important;
    height: 3.2em !important;
    font-size: 17px !important;
    box-shadow: 0 4px 15px rgba(249,115,22,0.35) !important;
    transition: 0.2s ease-in-out;
}}
.stButton > button:hover {{
    background-color: #ea580c !important;
    transform: scale(1.01);
}}

/* Result cards */
.analysis-card {{
    background-color: #fff7ed;
    border-right: 8px solid #f97316;
    border-radius: 16px;
    padding: 18px 18px;
    margin-top: 14px;
    box-shadow: 0 6px 18px rgba(0,0,0,0.08);
}}
.analysis-title {{
    font-size: 1.25em;
    font-weight: 900;
    color: #1f2937;
    margin-bottom: 10px;
}}
.time-prediction {{
    background-color: #fef3c7;
    color: #78350f;
    padding: 12px 14px;
    border-radius: 12px;
    font-size: 1.05em;
    font-weight: 900;
    margin-top: 10px;
    text-align: center !important;
    border: 2px solid #fcd34d;
}}

.small-note {{
    font-size: 0.9em;
    color: rgba(49, 51, 63, 0.65);
    margin-top: -8px;
}}

/* Footer (your classic style, always RTL) */
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
# 4) VISITOR / CTA (OPTIONAL, SAFE)
# =========================================================
def get_visitor_id() -> str:
    if "visitor_id" not in st.session_state:
        st.session_state["visitor_id"] = str(uuid.uuid4())
    return st.session_state["visitor_id"]

def track_visit():
    try:
        # If you already have this RPC in your DB, it will work. If not, it won't break the app.
        supabase.rpc("track_visit", {"p_app_id": APP_ID, "p_visitor_id": get_visitor_id()}).execute()
    except Exception:
        pass

def track_cta():
    try:
        supabase.rpc("increment_cta", {"p_app_id": APP_ID}).execute()
    except Exception:
        pass

track_visit()

# =========================================================
# 5) CACHE (viral_scores_cache: app_id, content_hash, analysis_text, created_at)
# =========================================================
def build_content_hash(topic: str, audience: str, content_type: str, lang: str) -> str:
    payload = "||".join([
        APP_ID,
        (topic or "").strip(),
        (audience or "").strip(),
        (content_type or "").strip(),
        (lang or "").strip(),
    ])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()

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
        data = getattr(res, "data", None) or []
        if data and isinstance(data, list) and data[0].get("analysis_text"):
            return data[0]["analysis_text"]
    except Exception:
        pass
    return None

def cache_set(content_hash: str, analysis_text: str):
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

# =========================================================
# 6) FEEDBACK (submit_app_feedback RPC)
# =========================================================
def save_feedback_via_rpc(app_name, useful, missing_reason, problem_text, helpful_reason, must_use_text):
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
# 7) MODEL CALL (NO google_search tools to avoid ClientError)
# =========================================================
MODEL_CANDIDATES = [
    "gemini-1.5-flash",
    "gemini-2.0-flash",
    "gemini-1.5-pro",
]

def extract_json(text: str) -> dict:
    if not text:
        return {}
    s = text.strip()
    # remove code fences if any
    s = s.replace("```json", "").replace("```", "").strip()
    m = re.search(r"\{.*\}", s, re.DOTALL)
    if m:
        s = m.group(0)
    return json.loads(s)

def call_model_with_retry(prompt: str, cfg, retries: int = 3, delay: int = 2):
    last_err = None
    for model in MODEL_CANDIDATES:
        for attempt in range(retries):
            try:
                resp = genai_client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=cfg,
                )
                return (resp.text or "").strip(), model
            except (ResourceExhausted, ServiceUnavailable, DeadlineExceeded) as e:
                last_err = e
                time.sleep(delay * (attempt + 1))
                continue
            except ClientError as e:
                # Model not available / permission / bad request.
                last_err = e
                break
            except Exception as e:
                last_err = e
                break
    raise last_err if last_err else RuntimeError("Unknown model error")

def analyze_timing(topic: str, audience: str, content_type: str) -> dict:
    lang_name = "English" if IS_EN else "Arabic"

    if IS_EN:
        system = (
            "You are a Viral Timing Analyst. "
            "You must return ONLY valid JSON and nothing else."
        )
        prompt = f"""
Return ONLY JSON using this schema:
{{
  "BestTimePrediction": {{"DayOfWeek":"", "TimeWindow":"", "Timezone":""}},
  "WhyThisTiming": ["", "", ""],
  "AudienceAssumptions": ["", "", ""],
  "PracticalPostingPlan": ["", "", "", ""],
  "Confidence": "Low/Medium/High",
  "Notes": ""
}}

Inputs:
Topic: {topic}
Audience: {audience if audience else "General"}
Content type: {content_type}

Rules:
- Give a realistic best-practice recommendation (not claiming guaranteed virality).
- Use the user's local timezone: Asia/Hebron (UTC+2).
- Keep it practical and specific.
Language: {lang_name}
"""
    else:
        system = (
            "أنت محلل توقيت للنشر (Viral Timing Analyst). "
            "مهمتك إعطاء توصية عملية وواقعية لأفضل وقت نشر بناءً على أفضل الممارسات العامة. "
            "يجب أن تُخرج JSON فقط وبدون أي شرح خارج JSON."
        )
        prompt = f"""
أخرج JSON فقط بنفس هذا الشكل:
{{
  "BestTimePrediction": {{"DayOfWeek":"", "TimeWindow":"", "Timezone":""}},
  "WhyThisTiming": ["", "", ""],
  "AudienceAssumptions": ["", "", ""],
  "PracticalPostingPlan": ["", "", "", ""],
  "Confidence": "Low/Medium/High",
  "Notes": ""
}}

المدخلات:
الموضوع: {topic}
الجمهور: {audience if audience else "عام"}
نوع المحتوى: {content_type}

قواعد:
- التوصية تكون "أفضل ممارسة" وليست وعد بالـ viral.
- استخدم توقيت فلسطين: Asia/Hebron (UTC+2).
- خلي الخطة عملية ومحددة.
اللغة: {lang_name}
"""

    cfg = g_types.GenerateContentConfig(
        system_instruction=system,
        temperature=0.35,
        max_output_tokens=1400,
    )

    raw, used_model = call_model_with_retry(prompt, cfg, retries=3, delay=2)
    data = extract_json(raw)
    data["_meta"] = {"model_used": used_model}
    return data

# =========================================================
# 8) UI TEXT
# =========================================================
if IS_EN:
    st.title("⏱️ Viral Timing Analyst")
    st.caption("A practical best-time recommendation (not a promise of virality). Uses Asia/Hebron timezone (UTC+2).")
else:
    st.title("⏱️ مُحلّل توقيت الـ Viral")
    st.caption("توصية عملية كأفضل ممارسة (مش وعد بالـ viral). يعتمد توقيت فلسطين Asia/Hebron (UTC+2).")

with st.expander("💡 What does this tool do?" if IS_EN else "💡 ما الذي تفعله هذه الأداة؟", expanded=True):
    if IS_EN:
        st.markdown("""
This tool helps you pick a **better posting window** for your topic and content type.

**What you get:**
- A recommended **day + time window** (in your timezone)
- Why this timing makes sense (in plain language)
- A small posting plan you can follow this week

**Who it’s for:**
Creators, founders, marketers, and anyone trying to build consistency.

**Example input:**
- Topic: *AI presentations in PowerPoint*
- Audience: *Students + early-career professionals*
- Type: *Long LinkedIn post*

**Example output idea (simplified):**
- Best time: *Tuesday 11:00–13:00*
- Reason: *midday attention + work breaks + professional audience habits*
""")
    else:
        st.markdown("""
هذه الأداة تساعدك تختاري **نافذة نشر أفضل** حسب موضوعك ونوع المحتوى.

**ماذا ستحصلين؟**
- توصية **يوم + نافذة زمنية** (بتوقيت فلسطين)
- لماذا هذا التوقيت منطقي (بشكل مفهوم)
- خطة نشر صغيرة تمشي عليها هذا الأسبوع

**لمن هذه الأداة؟**
صنّاع محتوى، أصحاب مشاريع، مسوّقين، وأي شخص بدّه يبني “نشر ذكي” مع الاستمرارية.

**مثال مدخلات:**
- الموضوع: *العروض بالذكاء الاصطناعي داخل PowerPoint*
- الجمهور: *طلاب + موظفين جدد*
- النوع: *منشور لينكدإن طويل*

**فكرة مخرجات (تبسيط):**
- أفضل وقت: *الثلاثاء 11:00–13:00*
- السبب: *تركيز منتصف اليوم + استراحات عمل + عادات جمهور لينكدإن*
""")

st.markdown("---")

# =========================================================
# 9) INPUTS
# =========================================================
col1, col2 = st.columns(2)

with col1:
    topic = st.text_input(
        "1) Topic" if IS_EN else "1) الموضوع",
        placeholder="e.g., AI presentations in PowerPoint" if IS_EN else "مثال: ريادة الأعمال / الذكاء الاصطناعي / التسويق",
    )

with col2:
    audience = st.text_input(
        "2) Audience (optional)" if IS_EN else "2) الجمهور (اختياري)",
        placeholder="e.g., students / founders / Gen Z" if IS_EN else "مثال: طلاب / صناع محتوى / جيل زد",
    )

content_type = st.selectbox(
    "3) Content type" if IS_EN else "3) نوع المحتوى",
    (
        "Long post (LinkedIn/Blog)" if IS_EN else "مقال/منشور طويل (LinkedIn/Blog)",
        "Short video (Reels/TikTok)" if IS_EN else "فيديو قصير (Reels/TikTok)",
        "Image/Carousel" if IS_EN else "صورة/كاروسيل",
        "Thread (X)" if IS_EN else "سلسلة تغريدات (X)",
        "Podcast clip" if IS_EN else "مقتطف بودكاست",
    ),
)

st.markdown(
    f'<div class="small-note">{("Tip: If you post for Palestine/Gulf, keep lunch + evening windows in mind."
    if IS_EN else "ملاحظة: إذا جمهورك فلسطين/الخليج، انتبهي لنوافذ وقت الغدا + المساء.")}</div>',
    unsafe_allow_html=True,
)

# =========================================================
# 10) RUN + CACHE
# =========================================================
btn_label = "🚀 Analyze best time" if IS_EN else "🚀 حلّل أفضل توقيت"
if st.button(btn_label):
    if not (topic or "").strip():
        st.warning("Please enter a topic." if IS_EN else "الرجاء إدخال الموضوع.")
        st.stop()

    track_cta()

    c_hash = build_content_hash(topic, audience, content_type, st.session_state["ui_lang"])
    cached = cache_get(c_hash)

    if cached:
        try:
            result = json.loads(cached)
            st.session_state[f"{APP_ID}_result"] = result
            st.session_state[f"{APP_ID}_has_result"] = True
        except Exception:
            pass

    if not st.session_state.get(f"{APP_ID}_has_result"):
        with st.spinner("Analyzing..." if IS_EN else "جاري التحليل..."):
            try:
                result = analyze_timing(topic.strip(), (audience or "").strip(), content_type)
                st.session_state[f"{APP_ID}_result"] = result
                st.session_state[f"{APP_ID}_has_result"] = True
                cache_set(c_hash, json.dumps(result, ensure_ascii=False))
            except Exception as e:
                st.error("API connection failed." if IS_EN else "فشل الاتصال بالـ API.")
                # Print full details to logs (Streamlit Cloud logs)
                print("[ViralTimingAnalyst Error]", repr(e))
                st.stop()

# =========================================================
# 11) RESULTS
# =========================================================
if st.session_state.get(f"{APP_ID}_has_result"):
    data = st.session_state.get(f"{APP_ID}_result", {}) or {}

    pred = data.get("BestTimePrediction", {}) or {}
    day = pred.get("DayOfWeek", "—")
    window = pred.get("TimeWindow", "—")
    tz = pred.get("Timezone", "Asia/Hebron (UTC+2)") or "Asia/Hebron (UTC+2)"

    st.markdown("---")

    st.markdown(
        f"""
<div class="analysis-card">
  <div class="analysis-title">{("✅ Recommendation" if IS_EN else "✅ التوصية")}</div>
  <div class="time-prediction">
    {("Best day" if IS_EN else "اليوم المُوصى به")}: {day}
    &nbsp;|&nbsp;
    {("Window" if IS_EN else "النافذة")}: {window}
    &nbsp;|&nbsp;
    {("Timezone" if IS_EN else "التوقيت")}: {tz}
  </div>
</div>
""",
        unsafe_allow_html=True,
    )

    # Sections
    colA, colB = st.columns(2)

    with colA:
        st.markdown("### 🔍 " + ("Why this timing?" if IS_EN else "لماذا هذا التوقيت؟"))
        why = data.get("WhyThisTiming", [])
        if isinstance(why, list) and why:
            for x in why:
                st.markdown(f"- {x}")
        else:
            st.markdown("—")

        st.markdown("### 👥 " + ("Audience assumptions" if IS_EN else "افتراضات عن الجمهور"))
        aa = data.get("AudienceAssumptions", [])
        if isinstance(aa, list) and aa:
            for x in aa:
                st.markdown(f"- {x}")
        else:
            st.markdown("—")

    with colB:
        st.markdown("### 🧭 " + ("Practical posting plan" if IS_EN else "خطة نشر عملية"))
        pp = data.get("PracticalPostingPlan", [])
        if isinstance(pp, list) and pp:
            for i, x in enumerate(pp, 1):
                st.markdown(f"{i}. **{x}**")
        else:
            st.markdown("—")

        st.markdown("### 📌 " + ("Notes" + (" & confidence" if IS_EN else " والثقة")))
        conf = data.get("Confidence", "—")
        notes = data.get("Notes", "")
        st.info((f"Confidence: {conf}\n\n{notes}".strip()) if IS_EN else (f"مستوى الثقة: {conf}\n\n{notes}".strip()))

    # Meta (optional)
    used_model = (data.get("_meta", {}) or {}).get("model_used", "")
    if used_model:
        st.caption(("Model used: " if IS_EN else "الموديل المستخدم: ") + used_model)

    # =========================================================
    # 12) FEEDBACK (Same style)
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
        )

    with st.expander("Quick feedback (3 questions)" if IS_EN else "فيدباك سريع (3 أسئلة)", expanded=False):
        problem_text = st.text_area(
            "1) What problem were you trying to solve?"
            if IS_EN else "1) ما المشكلة التي كنت تحاول حلّها؟",
            max_chars=280,
            key=f"{APP_ID}_problem_text",
        )
        helpful_reason = st.text_area(
            "2) Did it help? Why yes/no?"
            if IS_EN else "2) هل ساعدتك الأداة؟ لماذا نعم/لا؟",
            max_chars=280,
            key=f"{APP_ID}_helpful_reason",
        )
        must_use_text = st.text_area(
            "3) What would make this a must-use tool for you?"
            if IS_EN else "3) ما الذي سيجعل هذه الأداة «لازم تُستخدم» بالنسبة لك؟",
            max_chars=280,
            key=f"{APP_ID}_must_use_text",
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
                st.error("Supabase APIError" if IS_EN else "خطأ من Supabase")
                try:
                    st.json(e.args[0])
                except Exception:
                    st.write(str(e))
            except Exception as e:
                st.error("Unexpected error" if IS_EN else "خطأ غير متوقع")
                st.write(str(e))
                print("[Feedback Error]", repr(e))

# =========================================================
# 13) FOOTER (SIMPLE HTML, YOUR STYLE)
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
