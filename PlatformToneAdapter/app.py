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
from google.api_core.exceptions import ResourceExhausted, ServiceUnavailable, DeadlineExceeded

# =================================================================
# 0) PAGE CONFIG
# =================================================================
st.set_page_config(
    page_title="مُكيف نبرة المحتوى",
    layout="wide",
    initial_sidebar_state="collapsed",
)

APP_ID = "7-tone-adapter"

# =================================================================
# 1) LANGUAGE SWITCH
# =================================================================
if "ui_lang" not in st.session_state:
    st.session_state["ui_lang"] = "AR"

lang_toggle = st.toggle("English", value=(st.session_state["ui_lang"] == "EN"))
st.session_state["ui_lang"] = "EN" if lang_toggle else "AR"
IS_EN = (st.session_state["ui_lang"] == "EN")

# =================================================================
# 2) TEXT DICTIONARY (NO FOOTER HERE)
# =================================================================
TXT = {
    "title": "🗣️ Content Tone Adapter (5 Platforms)" if IS_EN else "🗣️ مُكيف نبرة المحتوى حسب المنصة (5 منصات)",
    "sub": "Turn one post into platform-optimized versions for LinkedIn, TikTok, X, Instagram, and Facebook."
    if IS_EN else
    "حوّل منشورك ليناسب LinkedIn، TikTok، X، Instagram، و Facebook.",
    "exp_title": "💡 What does this tool do?" if IS_EN else "💡 ما الذي تفعله هذه الأداة؟",
    "exp_body": (
        """
This tool takes one original post and rewrites it into 5 versions, each matching the best tone and style for:
- **LinkedIn** (professional, insightful)
- **TikTok** (casual, hook-driven)
- **X** (short, direct)
- **Instagram** (storytelling + many hashtags)
- **Facebook** (friendly + discussion-driven)

**What you get:**
- A platform-ready post for each platform
- Built-in CTA + hashtags aligned with each platform

**Example input:**
"AI isn’t just changing tools — it’s changing how we think, work, and create."

**What happens:**
TikTok / Instagram tone:  
"AI just changed the way I work… and no one is talking about this."

X (Twitter) tone:  
"AI isn’t replacing people. It’s replacing workflows."
"""
        if IS_EN
        else
        """
هذه الأداة تأخذ منشور واحد وتعيد كتابته 5 مرات، كل مرة بنبرة مختلفة تناسب أفضل أسلوب لكل منصة:
- **LinkedIn** (احترافي + متعمق)
- **TikTok** (عفوي + سريع + خطّاف)
- **X** (مختصر + مباشر)
- **Instagram** (قصصي/إلهامي + هاشتاغات كثيرة)
- **Facebook** (ودود + يشجع النقاش)

**ماذا تستفيد؟**
- منشور جاهز لكل منصة بنفس الفكرة
- CTA + هاشتاغات مناسبة لكل منصة

**مثال مدخلات:**
"الذكاء الاصطناعي يغيّر كل شيء."

**المخرجات**

نبرة لينكدإن:  
"الذكاء الاصطناعي لا يغيّر الأدوات فقط، بل يغيّر طريقة عملنا وتفكيرنا وصناعة المحتوى."
نبرة إنستغرام / تيك توك:  
"الذكاء الاصطناعي غيّر طريقة شغلي بالكامل… والغريب إن قليل ناس منتبهة لهذا الشي."
نبرة X (تويتر):  
"الذكاء الاصطناعي لا يستبدل الأشخاص… بل يستبدل طريقة العمل."""
    ),
    "input_label": "Original post / idea" if IS_EN else "المنشور الأصلي أو الفكرة التي تريد تكييفها",
    "input_ph": "Write your content here..." if IS_EN else "اكتب هنا المحتوى الذي تريد تحويله...",
    "btn": "🔄 Adapt content now" if IS_EN else "🔄 تكييف المحتوى الآن",
    "warn_empty": "Please paste your original post first." if IS_EN else "الرجاء إدخال المنشور الأصلي أولاً.",
    "spinner": "Adapting tone for 5 platforms..." if IS_EN else "جاري إعادة الصياغة لخمس منصات...",
    "out_title": "✨ Adapted Posts" if IS_EN else "✨ المنشورات المُكيفة حسب المنصة",
    "tone": "Tone" if IS_EN else "النبرة",
    "fb_title": "Feedback" if IS_EN else "ساعدنا نطوّر الأداة",
    "fb_q": "How was your experience?" if IS_EN else "كيف كانت تجربتك مع هذه الأداة؟",
    "fb_yes": "This tool was useful for me" if IS_EN else "هذه الأداة كانت مفيدة بالنسبة لي",
    "fb_no": "This tool was not useful" if IS_EN else "هذه الأداة لم تكن مفيدة",
    "fb_missing": "What was missing? (one sentence)" if IS_EN else "ما الذي كان ناقصاً؟ (جملة واحدة)",
    "fb_exp": "Quick feedback (3 questions)" if IS_EN else "فيدباك سريع (3 أسئلة)",
    "fb_p1": "1) What problem were you trying to solve?" if IS_EN else "1) ما المشكلة التي كنت تحاول حلّها؟",
    "fb_p2": "2) Did it help? Why yes/no?" if IS_EN else "2) هل ساعدتك الأداة؟ لماذا نعم/لا؟",
    "fb_p3": "3) What would make this a must-use tool for you?" if IS_EN else "3) ما الذي سيجعل هذه الأداة «لازم تُستخدم» بالنسبة لك؟",
    "fb_btn": "Submit feedback" if IS_EN else "إرسال الفيدباك",
    "fb_warn": "Write at least one line." if IS_EN else "اكتب سطر واحد على الأقل 🙏",
    "fb_ok": "Feedback saved ✅ Thank you!" if IS_EN else "تم حفظ الفيدباك ✅ شكرًا لك!",
    "fb_err": "Supabase error:" if IS_EN else "خطأ من Supabase:",
    "err_missing_secrets": "⚠️ Missing secrets in Secrets / Env." if IS_EN else "⚠️ مفاتيح الربط ناقصة في Secrets أو Env.",
    "wait": "Please wait a few seconds before trying again." if IS_EN else "يرجى الانتظار قليلاً قبل المحاولة مجدداً.",
}

# =================================================================
# 3) SECRETS + CLIENTS
# =================================================================
def get_secret(key: str):
    return st.secrets.get(key) or os.environ.get(key)

SUPABASE_URL = get_secret("SUPABASE_URL")
SUPABASE_KEY = get_secret("SUPABASE_KEY")
GOOGLE_API_KEY = get_secret("GOOGLE_API_KEY")

if not all([SUPABASE_URL, SUPABASE_KEY, GOOGLE_API_KEY]):
    st.error(TXT["err_missing_secrets"])
    st.stop()

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
genai_client = genai.Client(api_key=GOOGLE_API_KEY)

# =================================================================
# 4) MODEL (stable fallback + stored)
# =================================================================
MODEL_CANDIDATES = [
    "gemini-2.0-flash-001",
    "gemini-1.5-flash-001",
    "gemini-1.5-pro-001",
]

def get_working_model():
    if "working_model_tone" in st.session_state:
        return st.session_state["working_model_tone"]

    for m in MODEL_CANDIDATES:
        try:
            genai_client.models.generate_content(
                model=m,
                contents="test",
                config=types.GenerateContentConfig(max_output_tokens=1),
            )
            st.session_state["working_model_tone"] = m
            return m
        except Exception:
            continue

    st.session_state["working_model_tone"] = MODEL_CANDIDATES[0]
    return MODEL_CANDIDATES[0]

# =================================================================
# 5) CTA + CACHE + RATE LIMIT
# =================================================================
def track_cta_event(app_id: str):
    try:
        supabase.rpc("increment_cta", {"p_app_id": app_id}).execute()
    except Exception:
        pass

def make_content_hash(text: str):
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()

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
        return json.loads(res.data[0]["analysis_text"]) if res.data else None
    except Exception:
        return None

def cache_set(app_id: str, content_hash: str, analysis: dict):
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

def can_call_model(min_seconds: int = 10) -> bool:
    now = time.time()
    last = st.session_state.get("last_model_call_ts_tone", 0.0)
    if (now - last) < min_seconds:
        return False
    st.session_state["last_model_call_ts_tone"] = now
    return True

# =================================================================
# 6) FEEDBACK RPC
# =================================================================
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

# =================================================================
# 7) HELPERS
# =================================================================
def get_platform_emoji(platform_key: str):
    emojis = {
        "LinkedIn": "🔗",
        "TikTok": "🎵",
        "X_Twitter": "🐦",
        "Instagram": "📸",
        "Facebook": "👥",
    }
    return emojis.get(platform_key, "📌")

def _extract_json_block(t: str) -> str:
    if not t:
        return ""
    s = t.strip()
    if s.startswith("```"):
        s = s.replace("```json", "").replace("```", "").strip()
    if s.startswith("{") and s.endswith("}"):
        return s
    start = s.find("{")
    end = s.rfind("}")
    if start != -1 and end != -1 and end > start:
        return s[start:end + 1]
    return s

# =================================================================
# 8) CSS (RTL/LTR strict + same tools style) + SIMPLE FOOTER TAG
# =================================================================
DIR = "ltr" if IS_EN else "rtl"
ALIGN = "left" if IS_EN else "right"

st.markdown(
    f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Cairo:wght@400;700&display=swap');

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
    font-family: 'Cairo', sans-serif !important;
}}

h1, h2, h3, h4, h5, h6, p, div, span, li, [data-testid="stMarkdownContainer"] {{
    direction: {DIR} !important;
    text-align: {ALIGN} !important;
    unicode-bidi: plaintext !important;
    line-height: 1.8 !important;
}}

textarea, input {{
    direction: {DIR} !important;
    text-align: {ALIGN} !important;
}}

.stButton > button {{
    background-color: #f75d5d !important;
    color: white !important;
    border: none !important;
    border-radius: 14px !important;
    font-weight: 800 !important;
    height: 3.2em !important;
    width: 100% !important;
}}
.stButton > button:hover {{
    filter: brightness(0.95);
    transform: scale(1.01);
}}

.post-container {{
    padding: 15px;
    margin-bottom: 16px;
    border-radius: 12px;
    border: 1px solid rgba(0,0,0,0.12);
    background-color: rgba(0,0,0,0.03);
}}
.post-title {{
    font-weight: 800;
    margin: 0 0 8px 0;
}}
.post-content {{
    white-space: pre-wrap;
    word-break: break-word;
}}

footer.custom-footer {{
    width: 100%;
    text-align: center;
    margin-top: 45px;
    padding-top: 18px;
    border-top: 1px solid #666;
    font-size: 13px;
    display: block;
    direction: rtl !important;
}}
</style>
""",
    unsafe_allow_html=True,
)

# =================================================================
# 9) GENERATION LOGIC (retry)
# =================================================================
MAX_RETRIES = 4
INITIAL_DELAY = 4

def adapt_tone(original_post: str):
    if not genai_client:
        return {"error": "Gemini client is not initialized."}

    lang_name = "English" if IS_EN else "Arabic"

    system_prompt = (
        "You are a professional content strategist. "
        "Take the original post and rewrite it five times to match the best tone and practices for each platform. "
        "Each post must include a suitable CTA and relevant hashtags (Instagram should have more hashtags). "
        f"Return output in {lang_name}. "
        "Return ONLY JSON and strictly follow the schema."
    )

    prompt = f"""
Rewrite the following post to fit: LinkedIn, TikTok, X, Instagram, Facebook.

ORIGINAL POST:
{original_post}

TONE RULES:
1) LinkedIn: Professional, insightful, value-focused.
2) TikTok: Casual, hook-driven, direct engagement.
3) X: Sharp, short, straight to the point.
4) Instagram: Storytelling + 10-15 hashtags.
5) Facebook: Friendly, community-focused, invites discussion.

Important:
- Output language: {lang_name}
- Output JSON only.
"""

    response_schema = {
        "type": "OBJECT",
        "properties": {
            "LinkedIn": {"type": "OBJECT", "properties": {"Tone": {"type": "STRING"}, "Post": {"type": "STRING"}}},
            "TikTok": {"type": "OBJECT", "properties": {"Tone": {"type": "STRING"}, "Post": {"type": "STRING"}}},
            "X_Twitter": {"type": "OBJECT", "properties": {"Tone": {"type": "STRING"}, "Post": {"type": "STRING"}}},
            "Instagram": {"type": "OBJECT", "properties": {"Tone": {"type": "STRING"}, "Post": {"type": "STRING"}}},
            "Facebook": {"type": "OBJECT", "properties": {"Tone": {"type": "STRING"}, "Post": {"type": "STRING"}}},
        },
        "propertyOrdering": ["LinkedIn", "TikTok", "X_Twitter", "Instagram", "Facebook"],
    }

    model = get_working_model()

    for attempt in range(MAX_RETRIES):
        try:
            resp = genai_client.models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    response_mime_type="application/json",
                    response_schema=response_schema,
                    temperature=0.5,
                    max_output_tokens=2400,
                ),
            )
            raw_text = resp.text or ""
            candidate = _extract_json_block(raw_text)
            return json.loads(candidate)

        except (ResourceExhausted, ServiceUnavailable, DeadlineExceeded) as e:
            if attempt < MAX_RETRIES - 1:
                delay = INITIAL_DELAY * (2 ** attempt)
                st.warning((f"⚠️ Server busy… retry in {delay}s") if IS_EN else (f"⚠️ ضغط خادم… إعادة المحاولة بعد {delay} ثواني."))
                time.sleep(delay)
                continue
            return {"error": str(e)}

        except Exception as e:
            return {"error": str(e)}

    return {"error": "Unknown error"}

# =================================================================
# 10) UI
# =================================================================
st.title(TXT["title"])
st.caption(TXT["sub"])

with st.expander(TXT["exp_title"], expanded=True):
    st.markdown(TXT["exp_body"])

st.markdown("---")

original_post = st.text_area(
    TXT["input_label"],
    placeholder=TXT["input_ph"],
    height=170,
    key="original_post_input",
)

# Session state for results
if f"{APP_ID}_has_result" not in st.session_state:
    st.session_state[f"{APP_ID}_has_result"] = False
if f"{APP_ID}_result" not in st.session_state:
    st.session_state[f"{APP_ID}_result"] = None

# Button
if st.button(TXT["btn"]):
    if not (original_post or "").strip():
        st.warning(TXT["warn_empty"])
        st.stop()

    track_cta_event(APP_ID)

    if not can_call_model(min_seconds=10):
        st.warning(TXT["wait"])
        st.stop()

    c_hash = make_content_hash(f"lang={st.session_state['ui_lang']}||{original_post.strip()}")
    cached = cache_get(APP_ID, c_hash)

    if cached:
        result = cached
    else:
        with st.spinner(TXT["spinner"]):
            result = adapt_tone(original_post)
        if isinstance(result, dict) and "error" not in result:
            cache_set(APP_ID, c_hash, result)

    if not isinstance(result, dict) or "error" in result:
        msg = (result.get("error") if isinstance(result, dict) else "Unknown error")
        if any(x in str(msg) for x in ["429", "RESOURCE_EXHAUSTED", "503", "UNAVAILABLE"]):
            st.warning("⚡ The tool is currently busy. Please try again in a few seconds." if IS_EN else "⚡ الأداة مشغولة حالياً، جرّبي بعد ثواني.")
        else:
            st.error(msg)
    else:
        st.session_state[f"{APP_ID}_has_result"] = True
        st.session_state[f"{APP_ID}_result"] = result

# =================================================================
# 11) RESULTS
# =================================================================
data = st.session_state.get(f"{APP_ID}_result") if st.session_state.get(f"{APP_ID}_has_result") else None

if isinstance(data, dict) and data:
    st.markdown("---")
    st.markdown(f"## {TXT['out_title']}")

    platforms = [
        ("LinkedIn", "LinkedIn"),
        ("TikTok", "TikTok"),
        ("X_Twitter", "X"),
        ("Instagram", "Instagram"),
        ("Facebook", "Facebook"),
    ]

    for key, display_name in platforms:
        item = data.get(key, {}) or {}
        tone = item.get("Tone", "—")
        post = item.get("Post", "—")
        emoji = get_platform_emoji(key)

        st.markdown(
            f"""
<div class="post-container">
  <div class="post-title">{emoji} {display_name} ({TXT['tone']}: {tone})</div>
  <div class="post-content">{post}</div>
</div>
""",
            unsafe_allow_html=True,
        )

    # =========================================================
    # 12) FEEDBACK (after results)
    # =========================================================
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
                    st.error(TXT["fb_err"])
                    try:
                        st.json(e.args[0])
                    except Exception:
                        st.write(str(e))
                except Exception as e:
                    st.exception(e)

# =================================================================
# 13) FOOTER (SIMPLE, NO TXT)
# =================================================================
st.markdown(
    """
<footer class="custom-footer">
  جميع الحقوق محفوظة © 2026 | AI Product Builder - Layan Khalil
</footer>
""",
    unsafe_allow_html=True,
)

