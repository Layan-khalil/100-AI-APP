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
    page_title="Viral Timing Analyst",
    layout="wide",
    initial_sidebar_state="collapsed",
)

APP_ID = "6-viral-timing-analyst"
MODEL_NAME = "gemini-1.5-flash"  # ✅ stable model (avoid google_search tool issues)
MAX_RETRIES = 3
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


# =========================================================
# 2) SECRETS / CLIENTS
# =========================================================
def get_secret(key: str):
    if key in st.secrets:
        return st.secrets.get(key)
    return os.environ.get(key)

SUPABASE_URL = get_secret("SUPABASE_URL")
SUPABASE_KEY = get_secret("SUPABASE_KEY")
GOOGLE_API_KEY = get_secret("GOOGLE_API_KEY") or get_secret("GEMINI_API_KEY")

missing = [k for k, v in {
    "SUPABASE_URL": SUPABASE_URL,
    "SUPABASE_KEY": SUPABASE_KEY,
    "GOOGLE_API_KEY (or GEMINI_API_KEY)": GOOGLE_API_KEY
}.items() if not v]

if missing:
    st.error(("Missing secrets: " if IS_EN else "مفاتيح ناقصة: ") + ", ".join(missing))
    st.stop()

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
genai_client = genai.Client(api_key=GOOGLE_API_KEY)


# =========================================================
# 3) CSS (same vibe as your previous tools)
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
div[class*="viewerBadge_link"] {{ display: none !important; }}
div[class*="viewerBadge_text"] {{ display: none !important; }}

html, body, [data-testid="stAppViewContainer"], .main {{
    direction: {DIR} !important;
    text-align: {ALIGN} !important;
    font-family: "Cairo", sans-serif !important;
}}

h1, h2, h3, h4, h5, h6, p, div, span, label, li,
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

.stButton > button {{
    font-weight: 800 !important;
    width: 100% !important;
    background-color: #f97316 !important;
    color: white !important;
    border-radius: 12px !important;
    padding: 11px 18px !important;
    font-size: 1.05em !important;
    border: none !important;
    box-shadow: 0 4px 15px rgba(249,115,22,0.45) !important;
}}
.stButton > button:hover {{
    background-color: #ea580c !important;
    transform: scale(1.01);
}}

.rtl-caption {{
    direction: {DIR} !important;
    text-align: {ALIGN} !important;
    margin-top: -8px;
    font-size: 0.9em;
    color: rgba(49, 51, 63, 0.62);
}}

.result-card {{
    margin-top: 18px;
    padding: 22px;
    border-radius: 14px;
    background: #fff7ed;
    border-right: 8px solid #f97316;
    box-shadow: 0 4px 12px rgba(0,0,0,0.12);
}}

.result-title {{
    font-size: 1.25em;
    font-weight: 900;
    color: #1e293b;
    margin-bottom: 10px;
}}

.time-pill {{
    background: #fef3c7;
    color: #78350f;
    padding: 12px 14px;
    border-radius: 10px;
    font-size: 1.05em;
    font-weight: 800;
    text-align: center !important;
    border: 1px solid #fcd34d;
}}

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
# 4) CACHE HELPERS (Supabase viral_scores_cache)
# =========================================================
def build_content_hash(topic: str, audience: str, content_type: str, lang: str) -> str:
    payload = f"{(topic or '').strip()}||{(audience or '').strip()}||{(content_type or '').strip()}||{lang}"
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


# =========================================================
# 5) CTA COUNT (same as your previous tools)
# =========================================================
def track_cta_event(app_id: str):
    try:
        supabase.rpc("increment_cta", {"p_app_id": app_id}).execute()
    except Exception:
        # ما نكسر التطبيق لو RPC مش موجود
        pass


# =========================================================
# 6) FEEDBACK (RPC)
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
# 7) MODEL CALL
# =========================================================
def clean_json_text(text: str) -> str:
    if not text:
        return ""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    return match.group(0) if match else text.strip()

def analyze_timing(topic: str, audience: str, content_type: str, is_en: bool) -> dict:
    lang_name = "English" if is_en else "Arabic"

    # ✅ مهم: بنتجنب google_search tool تماماً، وبنخليها "Analyst" بالمعرفة العامة + heuristics
    system_prompt = (
        "You are a Viral Timing Analyst. "
        "You do not browse the web. You infer from platform norms and audience behavior patterns. "
        "Return ONLY a valid JSON object."
    )

    prompt = f"""
Generate best posting time recommendations based on the user's topic and audience.
Return ONLY JSON in {lang_name} with EXACT keys:

{{
  "BestTimePrediction": {{
    "DayOfWeek": "string",
    "TimeWindowUTC": "string"
  }},
  "WhyThisTiming": "string",
  "Assumptions": ["string", "string"],
  "TipsToValidate": ["string", "string", "string"]
}}

Inputs:
- Topic: {topic}
- Audience: {audience}
- ContentType: {content_type}

Rules:
- Time must be in UTC (GMT+0) explicitly.
- Give a practical time window like "17:00–19:00 UTC".
- Keep it realistic and helpful.
"""

    cfg = g_types.GenerateContentConfig(
        system_instruction=system_prompt,
        temperature=0.4,
        max_output_tokens=1400,
    )

    last_err = None
    for attempt in range(MAX_RETRIES):
        try:
            resp = genai_client.models.generate_content(
                model=MODEL_NAME,
                contents=prompt,
                config=cfg,
            )
            raw = clean_json_text(getattr(resp, "text", "") or "")
            return json.loads(raw)
        except (ResourceExhausted, ServiceUnavailable, DeadlineExceeded) as e:
            last_err = e
            time.sleep(INITIAL_DELAY * (attempt + 1))
        except Exception as e:
            last_err = e
            break

    return {
        "error": str(last_err) if last_err else ("Model error" if is_en else "خطأ في الموديل")
    }


# =========================================================
# 8) UI
# =========================================================
if IS_EN:
    st.title("⏱️ Viral Timing Analyst (UTC)")
    st.caption("Find the best posting window in **UTC (GMT+0)** based on your topic, audience, and content type.")
else:
    st.title("⏱️ مُحلّل توقيت الـ Viral (بتوقيت UTC)")
    st.caption("تحديد أفضل نافذة نشر **بتوقيت UTC (GMT+0)** حسب موضوعك وجمهورك ونوع المحتوى.")

with st.expander("💡 What is this tool?" if IS_EN else "💡 ما هي هذه الأداة؟", expanded=True):
    if IS_EN:
        st.markdown("""
This tool helps you pick a **best posting window (in UTC)** based on:
- your topic (what you're posting about),
- your audience (who should see it),
- and your content format.

It does **not** promise virality.
It gives a **smart starting point** (timing hypothesis) + a short plan to validate it.

**Example input:**
- Topic: A long post about building AI tools in public for 30 days
- Audience: AI builders & creators
- Type: LinkedIn long post

**Example output:**
- Best window: Tue–Thu, 16:00–18:00 UTC
- Why: overlaps work breaks in Europe + late afternoon US
- Tips: test 2–3 time windows, track saves/comments, keep topic constant
""")
    else:
        st.markdown("""
هذه الأداة تساعدك تختاري **أفضل نافذة نشر بتوقيت UTC (GMT+0)** بناءً على:
- موضوعك (شو بتنشر؟)
- جمهورك (لمين موجّه؟)
- نوع المحتوى (بوست طويل/فيديو قصير/…).

هي **ما بتوعدك بالـ viral**،
بس بتعطيك **نقطة بداية ذكية** (فرضية توقيت) + طريقة بسيطة تتأكدي منها بالتجربة.

**مثال مدخلات:**
- الموضوع: فقرة طويلة عن رحلتك ببناء أدوات ذكاء اصطناعي لمدة 30 يوم
- الجمهور: AI builders وصناع محتوى
- النوع: بوست طويل على لينكدإن

**مثال مخرجات:**
- أفضل نافذة: الثلاثاء–الخميس، 16:00–18:00 UTC
- السبب: بتغطي استراحة شغل أوروبا + آخر دوام بأمريكا
- نصائح: جرّبي 2–3 أوقات، راقبي الحفظ والتعليقات، وخلي المحتوى ثابت بالتجارب
""")


st.markdown("---")

if IS_EN:
    topic = st.text_area(
        "1) Topic / Post content (can be long):",
        height=200,
        placeholder="Write a long paragraph about your AI journey, with details + questions...",
    )
    st.caption("Tip: paste the full paragraph. The tool will still output time in UTC.")
    audience = st.text_input(
        "2) Audience (optional):",
        placeholder="e.g., AI builders, founders, creators, students",
    )
    content_type = st.selectbox(
        "3) Content type:",
        (
            "Long post (LinkedIn / Blog)",
            "Short video (Reels / TikTok)",
            "Image / infographic",
            "Thread (X)",
            "Podcast",
        ),
    )
    btn_label = "🚀 Analyze best time (UTC)"
else:
    topic = st.text_area(
        "1) الموضوع / نص المنشور (ممكن يكون طويل):",
        height=200,
        placeholder="اكتب فقرة طويلة عميقة عن مشوارك بالذكاء الاصطناعي مع أسئلة وتفاصيل...",
    )
    st.caption("ملاحظة: النتيجة رح تطلع بتوقيت UTC (GMT+0).")
    audience = st.text_input(
        "2) الجمهور (اختياري):",
        placeholder="مثال: صناع محتوى، مؤسسين، طلاب، AI builders",
    )
    content_type = st.selectbox(
        "3) نوع المحتوى:",
        (
            "مقال/منشور طويل (LinkedIn/Blog)",
            "فيديو قصير (Reels/TikTok)",
            "إنفوجرافيك/صورة ثابتة",
            "سلسلة تغريدات (X)",
            "بودكاست",
        ),
    )
    btn_label = "🚀 تحليل أفضل وقت (UTC)"


# =========================================================
# 9) RUN + CTA + CACHE
# =========================================================
if st.button(btn_label):
    if not topic.strip():
        st.warning("Please enter the topic." if IS_EN else "الرجاء إدخال الموضوع.")
    else:
        # ✅ CTA count on click (as you asked)
        track_cta_event(APP_ID)

        c_hash = build_content_hash(topic, audience, content_type, st.session_state["ui_lang"])
        cached = cache_get(APP_ID, c_hash)

        if cached and isinstance(cached, dict) and "BestTimePrediction" in cached:
            st.session_state["timing_res"] = cached
            st.session_state["has_result"] = True
        else:
            with st.spinner("Analyzing..." if IS_EN else "جاري التحليل..."):
                res = analyze_timing(topic.strip(), audience.strip(), content_type, IS_EN)
                if "error" not in res:
                    cache_set(APP_ID, c_hash, res)
                    st.session_state["timing_res"] = res
                    st.session_state["has_result"] = True
                else:
                    st.error(res["error"])


# =========================================================
# 10) RESULTS
# =========================================================
if st.session_state.get("has_result") and st.session_state.get("timing_res"):
    data = st.session_state["timing_res"]
    pred = data.get("BestTimePrediction", {}) if isinstance(data, dict) else {}

    day = pred.get("DayOfWeek", "-")
    window = pred.get("TimeWindowUTC", "-")

    st.markdown(
        f"""
<div class="result-card">
  <div class="time-pill">
    {"Recommended day:" if IS_EN else "اليوم المُوصى به:"} {day} &nbsp; | &nbsp;
    {"Window (UTC):" if IS_EN else "النافذة (UTC):"} {window}
  </div>

  <div class="result-title" style="margin-top:16px;">
    {"Why this timing?" if IS_EN else "ليش هذا التوقيت؟"}
  </div>
  <div>{data.get("WhyThisTiming", "—")}</div>

  <div class="result-title" style="margin-top:16px;">
    {"Assumptions" if IS_EN else "الافتراضات"}
  </div>
  <div>
    {"".join([f"<div>• {x}</div>" for x in (data.get("Assumptions", []) or [])]) or "—"}
  </div>

  <div class="result-title" style="margin-top:16px;">
    {"How to validate quickly" if IS_EN else "كيف تتأكدي بسرعة؟"}
  </div>
  <div>
    {"".join([f"<div>• {x}</div>" for x in (data.get("TipsToValidate", []) or [])]) or "—"}
  </div>
</div>
""",
        unsafe_allow_html=True,
    )

    # =========================================================
    # 11) FEEDBACK
    # =========================================================
    st.divider()
    st.subheader("📝 Feedback" if IS_EN else "📝 ساعدينا نطوّر الأداة")

    feedback_choice = st.radio(
        "How was your experience?" if IS_EN else "كيف كانت تجربتك؟",
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
            placeholder="Example: needs clearer output / better time windows / export" if IS_EN
            else "مثال: بدي نتيجة أوضح / نوافذ أدق / تصدير",
        )

    with st.expander("Quick feedback (3 questions)" if IS_EN else "فيدباك سريع (3 أسئلة)", expanded=False):
        problem_text = st.text_area(
            "1) What problem were you trying to solve?"
            if IS_EN else "1) ما المشكلة التي كنتِ تحاولي تحلّيها؟",
            max_chars=280,
            key=f"{APP_ID}_problem_text",
        )
        helpful_reason = st.text_area(
            "2) Did it help? Why yes/no?"
            if IS_EN else "2) هل ساعدتك؟ لماذا نعم/لا؟",
            max_chars=280,
            key=f"{APP_ID}_helpful_reason",
        )
        must_use_text = st.text_area(
            "3) What would make this a must-use tool for you?"
            if IS_EN else "3) ما الذي سيجعلها أداة «لازم تُستخدم» عندك؟",
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
                    st.error("Supabase APIError:" if IS_EN else "خطأ من Supabase:")
                    try:
                        st.json(e.args[0])
                    except Exception:
                        st.write(str(e))
                except Exception as e:
                    st.exception(e)


# =========================================================
# 12) FOOTER (old style)
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
