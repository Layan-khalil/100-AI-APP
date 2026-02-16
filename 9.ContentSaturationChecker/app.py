import streamlit as st
import os
import json
import time
import uuid
import hashlib
import re
from google import genai
from google.genai import types
from google.api_core.exceptions import ResourceExhausted, ServiceUnavailable, DeadlineExceeded

# (اختياري) Supabase لو متوفر في أدواتك السابقة
try:
    from supabase import create_client, Client
except Exception:
    create_client = None
    Client = None

# =========================================================
# 0) Page config
# =========================================================
st.set_page_config(
    page_title="فحص الازدحام الزمني",
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
# 2) Secrets helper
# =========================================================
def get_secret(key: str, default: str = "") -> str:
    if key in st.secrets:
        return str(st.secrets.get(key, default))
    return str(os.environ.get(key, default))

GEMINI_API_KEY = get_secret("GEMINI_API_KEY") or get_secret("GOOGLE_API_KEY")

SUPABASE_URL = get_secret("SUPABASE_URL")
SUPABASE_KEY = get_secret("SUPABASE_KEY")

# =========================================================
# 3) Initialize clients
# =========================================================
client = None
try:
    if not GEMINI_API_KEY:
        st.error("⚠️ Missing GEMINI_API_KEY / GOOGLE_API_KEY in Secrets or Environment Variables.")
        st.stop()
    client = genai.Client(api_key=GEMINI_API_KEY)
except Exception as e:
    st.error(f"API connection failed: {e}")
    st.stop()

supabase = None
APP_ID = "9-time-saturation-checker"

if SUPABASE_URL and SUPABASE_KEY and create_client:
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception:
        supabase = None

# =========================================================
# 4) CSS (Hide Streamlit header + RTL/LTR + style)
# =========================================================
st.markdown(
    f"""
<style>
/* Hide Streamlit UI */
#MainMenu {{ visibility: hidden; }}
footer {{ visibility: hidden; }}
header {{ visibility: hidden; }}
div[data-testid="stToolbar"] {{ visibility: hidden; }}
div[data-testid="stStatusWidget"] {{ visibility: hidden; }}
div[data-testid="stDecoration"] {{ visibility: hidden; }}
div[class*="viewerBadge_container"] {{ display: none !important; }}
div[class*="viewerBadge_link"] {{ display: none !important; }}
div[class*="viewerBadge_text"] {{ display: none !important; }}

/* Global direction */
html, body, [data-testid="stAppViewContainer"], .main {{
    direction: {DIR} !important;
    text-align: {ALIGN} !important;
    font-family: "Cairo", sans-serif !important;
}}

h1,h2,h3,h4,h5,h6,p,div,span,label,li,[data-testid="stMarkdownContainer"] {{
    direction: {DIR} !important;
    text-align: {ALIGN} !important;
    unicode-bidi: plaintext !important;
    line-height: 1.75 !important;
}}

/* Inputs direction */
textarea, input,
.stTextInput > div > div > input,
.stTextArea > div > textarea {{
    direction: {DIR} !important;
    text-align: {ALIGN} !important;
}}

/* Button */
.stButton>button {{
    font-weight: 800 !important;
    width: 100% !important;
    background-color: #059669 !important;
    color: #ffffff !important;
    border: none !important;
    border-radius: 10px !important;
    padding: 11px 18px !important;
    font-size: 1.05em !important;
    transition: all 0.25s ease !important;
    box-shadow: 0 4px 15px rgba(5, 150, 105, 0.35) !important;
}}
.stButton>button:hover {{
    background-color: #047857 !important;
    transform: translateY(-2px) !important;
    box-shadow: 0 6px 20px rgba(5, 150, 105, 0.55) !important;
}}

/* Result card */
.result-card {{
    padding: 20px;
    border-radius: 12px;
    margin-top: 20px;
    box-shadow: 0 6px 15px rgba(0,0,0,0.08);
    background: rgba(255,255,255,0.02);
    border: 1px solid rgba(0,0,0,0.06);
}}
.status-header {{
    font-size: 1.3em;
    font-weight: 900;
    padding: 12px;
    border-radius: 8px;
    margin-bottom: 12px;
    text-align: center !important;
    color: #ffffff !important;
}}
.status-high {{ background-color: #dc2626; }}
.status-medium {{ background-color: #f59e0b; }}
.status-low {{ background-color: #10b981; }}

.analysis-section {{
    border-top: 1px solid rgba(0,0,0,0.08);
    padding-top: 14px;
    margin-top: 14px;
}}
/* Footer always RTL like your tools */
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
.footer-container, .footer-container * {{
    direction: rtl !important;
    text-align: center !important;
}}
</style>
""",
    unsafe_allow_html=True,
)

# =========================================================
# 5) Tracking + Feedback (Supabase optional)
# =========================================================
def get_session_visitor_id() -> str:
    if "visitor_id" not in st.session_state:
        st.session_state["visitor_id"] = str(uuid.uuid4())
    return st.session_state["visitor_id"]

def track_visit():
    if not supabase:
        return
    try:
        supabase.rpc("track_visit", {"p_app_id": APP_ID, "p_visitor_id": get_session_visitor_id()}).execute()
    except Exception:
        pass

def track_cta_event():
    if not supabase:
        return
    try:
        supabase.rpc("increment_cta", {"p_app_id": APP_ID}).execute()
    except Exception:
        pass

def save_feedback_via_rpc(app_name, useful, missing_reason, problem_text, helpful_reason, must_use_text):
    if not supabase:
        raise RuntimeError("Supabase not configured")
    return supabase.rpc("submit_app_feedback", {
        "p_app_name": app_name,
        "p_useful": useful,
        "p_missing_reason": missing_reason,
        "p_problem_text": problem_text,
        "p_helpful_reason": helpful_reason,
        "p_must_use_text": must_use_text,
    }).execute()

track_visit()

# =========================================================
# 6) Cache helpers (local cache + optional Supabase cache table)
# =========================================================
def get_hash(*parts: str) -> str:
    normalized = "||".join([" ".join((p or "").strip().split()) for p in parts])
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

def cache_get(app_id: str, content_hash: str):
    # 1) Try Supabase cache if exists
    if supabase:
        try:
            res = (
                supabase.table("viral_scores_cache")
                .select("analysis_text")
                .eq("app_id", app_id)
                .eq("content_hash", content_hash)
                .limit(1)
                .execute()
            )
            if res.data:
                return res.data[0].get("analysis_text")
        except Exception:
            pass
    return None

def cache_set(app_id: str, content_hash: str, analysis_text: str):
    if not supabase:
        return
    try:
        supabase.table("viral_scores_cache").insert({
            "app_id": app_id,
            "content_hash": content_hash,
            "analysis_text": analysis_text
        }).execute()
    except Exception:
        pass

@st.cache_data(show_spinner=False, ttl=60 * 60 * 6)
def local_cache_compute(content_hash: str, payload_json: str) -> str:
    # مجرد حامل، لأن st.cache_data يحتاج args
    return payload_json

# =========================================================
# 7) Model selection (flexible fallback)
# =========================================================
MODEL_CANDIDATES = [
    get_secret("MODEL_NAME", "").strip(),
    "gemini-2.5-flash",
    "gemini-2.5-flash-001",
]
MODEL_CANDIDATES = [m for m in MODEL_CANDIDATES if m]

@st.cache_resource
def get_working_model_name():
    # نجرب نموذج واحد صغير مع google_search config (لأن أداتنا تعتمد عليها)
    test_prompt = "Return ONLY JSON: {\"ok\": true}"
    cfg = types.GenerateContentConfig(
        system_instruction="Return ONLY JSON.",
        tools=[{"google_search": {}}],
    )
    last_err = None
    for m in MODEL_CANDIDATES:
        try:
            _ = client.models.generate_content(model=m, contents=test_prompt, config=cfg)
            return m
        except Exception as e:
            last_err = e
            continue
    raise RuntimeError(f"No working Gemini model found. Last error: {last_err}")

# =========================================================
# 8) Grounding sources extraction (safe)
# =========================================================
def extract_sources(resp, limit: int = 5):
    sources = []
    try:
        if resp.candidates and len(resp.candidates) > 0:
            cand = resp.candidates[0]
            if hasattr(cand, "groundingMetadata") and cand.groundingMetadata:
                atts = getattr(cand.groundingMetadata, "groundingAttributions", []) or []
                for a in atts[:limit]:
                    # حسب شكل attribution عندك
                    title = ""
                    uri = ""
                    if isinstance(a, dict):
                        title = a.get("title", "") or ""
                        uri = a.get("uri", "") or ""
                    else:
                        title = getattr(a, "title", "") or ""
                        uri = getattr(a, "uri", "") or ""
                    if title or uri:
                        sources.append({"title": title, "uri": uri})
    except Exception:
        pass
    return sources

# =========================================================
# 9) Core function: saturation check (with caching + retries)
# =========================================================
MAX_RETRIES = 4
INITIAL_DELAY = 2

def build_system_prompt() -> str:
    if IS_EN:
        return (
            "Act as a professional Content Trend Analyst specializing in social media saturation. "
            "Use Google Search grounding. Determine saturation level for the topic on the specified platform. "
            "Return ONLY a JSON object with EXACT keys: "
            "'SaturationLevel' (Low/Medium/High), 'Recommendation' (Publish Now/Postpone/Adapt), 'Justification'. "
            "No markdown. No extra text."
        )
    return (
        "تصرّف كخبير تحليل ترندات متخصص في قياس ازدحام الأفكار على منصات السوشال ميديا. "
        "استخدم Google Search grounding. حدّد مستوى الازدحام للفكرة على المنصة. "
        "أعد النتيجة فقط بصيغة JSON وبالمفاتيح التالية حصراً: "
        "'SaturationLevel' (منخفض/متوسط/مرتفع), 'Recommendation' (انشر الآن/أجّل النشر/عدّل الزاوية), 'Justification'. "
        "ممنوع Markdown أو نص إضافي."
    )

def build_user_prompt(content_idea: str, platform: str) -> str:
    if IS_EN:
        return f"""
Analyze saturation for this idea on the target platform using very recent signals from search.

Idea: {content_idea}
Platform: {platform}

Return ONLY JSON with keys:
SaturationLevel, Recommendation, Justification
"""
    return f"""
حلّل مستوى الازدحام (Saturation) للفكرة التالية على المنصة المحددة بالاعتماد على إشارات حديثة جداً من البحث.

الفكرة: {content_idea}
المنصة: {platform}

أعد فقط JSON بالمفاتيح:
SaturationLevel, Recommendation, Justification
"""

def sanitize_json_text(raw_text: str) -> str:
    t = (raw_text or "").strip()
    if t.startswith("```"):
        t = t.replace("```json", "").replace("```", "").strip()
    return t

def extract_first_json_object(text: str) -> str:
    """يحاول اقتناص أول { ... } من أي نص."""
    if not text:
        return ""
    m = re.search(r"\{.*\}", text, re.DOTALL)
    return m.group(0).strip() if m else text.strip()

def sanitize_json_text(text: str) -> str:
    """تنظيف قوي للنص قبل json.loads."""
    if not text:
        return ""

    t = text.strip()

    # شيل كود بلوك إن ظهر
    t = re.sub(r"^```json\s*", "", t, flags=re.IGNORECASE).strip()
    t = re.sub(r"^```\s*", "", t).strip()
    t = re.sub(r"\s*```$", "", t).strip()

    # اقتناص JSON فقط إن كان فيه كلام زائد
    t = extract_first_json_object(t)

    # استبدال الاقتباسات الذكية
    t = (t.replace("“", '"').replace("”", '"')
           .replace("‘", "'").replace("’", "'"))

    # حذف أحرف التحكم (سبب شائع لـ Invalid control character)
    t = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]", "", t)

    return t.strip()

def safe_json_loads(raw: str):
    """
    محاولة json.loads بشكل آمن.
    ترجع (obj, error_str). إذا نجحت error_str = None
    """
    try:
        return json.loads(raw), None
    except json.JSONDecodeError as e:
        return None, str(e)

def repair_json_with_model(client, model_name: str, broken_json_text: str):
    """
    إصلاح JSON بواسطة الموديل (بدون google_search).
    يرجع dict أو None
    """
    repair_prompt = f"""
Fix the following JSON to be valid JSON.
Return ONLY valid JSON (no markdown, no explanation).

BROKEN_JSON:
{broken_json_text}
""".strip()

    try:
        resp = client.models.generate_content(
            model=model_name,
            contents=repair_prompt,
            config=types.GenerateContentConfig(
                temperature=0.0,
                max_output_tokens=700,
            ),
        )
        cleaned = sanitize_json_text(getattr(resp, "text", "") or "")
        obj, err = safe_json_loads(cleaned)
        return obj if not err else None
    except Exception:
        return None    

def check_saturation(content_idea: str, platform: str):
    if not client:
        return {"error": "API connection failed"}, []

    model_name = get_working_model_name()

    # cache key includes language
    content_hash = get_hash(APP_ID, content_idea, platform, st.session_state["ui_lang"])

    # 1) Supabase cache
    cached = cache_get(APP_ID, content_hash)
    if cached:
        try:
            payload = json.loads(cached)
            return payload.get("result", {}), payload.get("sources", [])
        except Exception:
            cached = None  # ✅ ignore corrupted cache

    # 2) local cache
    lc = local_cache_compute(content_hash, "")
    if lc:
        try:
            payload = json.loads(lc)
            return payload.get("result", {}), payload.get("sources", [])
        except Exception:
            lc = None  # ✅ ignore corrupted local cache

    cfg = types.GenerateContentConfig(
        system_instruction=build_system_prompt(),
        tools=[{"google_search": {}}],
        temperature=0.2,
        max_output_tokens=900,
    )

    prompt = build_user_prompt(content_idea, platform)

    last_err = None
    for attempt in range(MAX_RETRIES):
        try:
            resp = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=cfg
            )

            sources = extract_sources(resp, limit=5)  # ✅ smaller payload
            raw0 = getattr(resp, "text", "") or ""
            raw = sanitize_json_text(raw0)

            if not raw:
                   return {"error": "Empty model response"}, []

            result, err = safe_json_loads(raw)

# ✅ محاولة ثانية: اقتناص JSON فقط + تنظيف مرة أخرى
            if err:
                raw2 = sanitize_json_text(extract_first_json_object(raw0))
                result, err = safe_json_loads(raw2)

# ✅ محاولة ثالثة: إصلاح JSON عبر الموديل (بدون Search)
            if err:
               fixed = repair_json_with_model(client, model_name, raw2 if 'raw2' in locals() else raw)
               if fixed:
                 result, err = fixed, None

            if err:
    # لعرض جزء صغير فقط للمساعدة
               snippet = (raw[:220] + "…") if len(raw) > 220 else raw
               return {"error": f"JSON parse failed: {err}. Snippet: {snippet}"}, []

            payload_json = json.dumps(
                {"result": result, "sources": sources},
                ensure_ascii=False
            )

            # save to local cache
            local_cache_compute(content_hash, payload_json)

            # save to supabase cache
            cache_set(APP_ID, content_hash, payload_json)

            return result, sources

        except (ResourceExhausted, ServiceUnavailable, DeadlineExceeded) as e:
            last_err = e
            time.sleep(INITIAL_DELAY * (attempt + 1))
        except json.JSONDecodeError as e:
            return {"error": f"JSON parse failed: {e}"}, []
        except Exception as e:
            last_err = e
            time.sleep(INITIAL_DELAY * (attempt + 1))

    return {"error": str(last_err) if last_err else "Unknown error"}, []

# =========================================================
# 10) UI copy (AR/EN) + Expander
# =========================================================
if IS_EN:
    st.title("🚦 Content Saturation Checker")
    st.subheader("Checks whether your idea is over-posted right now — and what you should do next.")
else:
    st.title("🚦 فحص الازدحام الزمني للمحتوى")
    st.subheader("يفحص إن كانت فكرتك مُشبعة حالياً — ويعطيك توصية واضحة ماذا تفعل الآن.")

with st.expander("💡 How it works + example" if IS_EN else "💡 كيف تعمل الأداة؟ + مثال", expanded=False):
    if IS_EN:
        st.markdown("""
This tool uses **Gemini + Google Search grounding** to scan very recent signals around your idea and estimate saturation on your chosen platform.

### What you get
- **SaturationLevel:** Low / Medium / High  
- **Recommendation:** Publish Now / Adapt / Postpone  
- **Justification:** short reasoning you can act on

### Example
**Idea:** “AI is replacing entry-level marketing tasks”  
**Platform:** LinkedIn  
If the topic is everywhere this week → **High** → **Postpone** or **Adapt** (pick a sharper angle, add a case study, or target a smaller niche).
""")
    else:
        st.markdown("""
هذه الأداة تستخدم **Gemini + بحث جوجل (Grounding)** لفحص إشارات حديثة جداً حول فكرتك وتقدير مستوى الازدحام على المنصة التي اخترتها.

### ماذا ستأخذ من الأداة؟
- **مستوى الازدحام:** منخفض / متوسط / مرتفع  
- **التوصية:** انشر الآن / عدّل الزاوية / أجّل النشر  
- **التبرير:** سبب واضح يساعدك تتخذ قرار سريع

### مثال صغير
**الفكرة:** “الذكاء الاصطناعي يغيّر وظائف التسويق للمبتدئين”  
**المنصة:** LinkedIn  
إذا كان الموضوع منتشر بكثافة هذا الأسبوع → **مرتفع** → الأفضل **تأجيله** أو **تعديل الزاوية** (تجربة شخصية، دراسة حالة، أو استهداف نيتش أضيق).
""")

st.markdown("---")

# =========================================================
# 11) Inputs
# =========================================================
col1, col2 = st.columns([3, 1])

if IS_EN:
    idea_ph = "Write your idea clearly (2–6 lines is perfect)."
    idea_label = "Your content idea:"
    plat_label = "Target platform:"
    btn_label = "🔍 Check saturation now"
else:
    idea_ph = "اكتب فكرتك بوضوح (2–6 أسطر ممتاز)."
    idea_label = "الفكرة/الموضوع الذي تريد فحصه:"
    plat_label = "المنصة المستهدفة:"
    btn_label = "🔍 فحص الازدحام الآن"

with col1:
    content_idea = st.text_area(
        idea_label,
        placeholder=idea_ph,
        height=260,
        key="content_idea_input",
    )

with col2:
    platform = st.selectbox(
        plat_label,
        options=["LinkedIn", "X (Twitter)", "TikTok", "Instagram", "Facebook", "Blogs / Articles"] if IS_EN
        else ["LinkedIn", "X (Twitter)", "TikTok", "Instagram", "Facebook", "المدونات والمقالات"],
        key="platform_select",
    )

# =========================================================
# 12) Run button
# =========================================================
if st.button(btn_label, use_container_width=True):
    if not content_idea or len(content_idea.strip()) < 10:
        st.warning("Please write a real idea (at least 10 chars)." if IS_EN else "اكتب فكرة حقيقية (على الأقل 10 أحرف).")
        st.stop()

    track_cta_event()

    with st.spinner("Analyzing recent signals..." if IS_EN else "جاري تحليل إشارات حديثة جداً..."):
        analysis_data, sources = check_saturation(content_idea.strip(), platform)

    st.session_state["has_result"] = True
    st.session_state["analysis_data"] = analysis_data
    st.session_state["sources"] = sources

# =========================================================
# 13) Show results
# =========================================================
if st.session_state.get("has_result"):
    analysis_data = st.session_state.get("analysis_data", {}) or {}
    sources = st.session_state.get("sources", []) or []

    if "error" in analysis_data:
        st.error(("Analysis failed: " if IS_EN else "فشل التحليل: ") + str(analysis_data["error"]))
    else:
        st.markdown("---")
        st.markdown("## 📊 Results" if IS_EN else "## 📊 نتائج التحليل")

        level = (analysis_data.get("SaturationLevel") or "").strip()

        # normalize status mapping for both languages
        level_low = ["Low", "منخفض"]
        level_med = ["Medium", "متوسط"]
        level_high = ["High", "مرتفع"]

        if level in level_high:
            status_class, status_emoji = "status-high", "🔴"
        elif level in level_med:
            status_class, status_emoji = "status-medium", "🟡"
        else:
            status_class, status_emoji = "status-low", "🟢"

        rec = analysis_data.get("Recommendation", "—")
        just = analysis_data.get("Justification", "—")

        st.markdown('<div class="result-card">', unsafe_allow_html=True)
        st.markdown(
            f'<div class="{status_class} status-header">{status_emoji} '
            + (f"Saturation level: {level}" if IS_EN else f"مستوى الازدحام: {level}")
            + "</div>",
            unsafe_allow_html=True,
        )

        st.info((f"✅ Recommendation: {rec}" if IS_EN else f"✅ التوصية: {rec}"))

        st.markdown('<div class="analysis-section">', unsafe_allow_html=True)
        st.markdown(("**Justification:**" if IS_EN else "**تفسير وتبرير التحليل:**"))
        st.markdown(just)
        st.markdown("</div>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

        # sources
        if sources:
            st.markdown("---")
            st.markdown("#### 🌐 Sources used" if IS_EN else "#### 🌐 مصادر البحث المستخدمة")
            for i, s in enumerate(sources, start=1):
                title = s.get("title", "Untitled")
                uri = s.get("uri", "")
                if uri:
                    st.markdown(f"{i}. [{title}]({uri})")
                else:
                    st.markdown(f"{i}. {title}")

# =========================================================
# 14) Feedback UI (Supabase optional)
# =========================================================
st.markdown("---")
st.subheader("📝 Feedback" if IS_EN else "📝 فيدباك")

if not supabase:
    st.caption("Feedback saving is disabled (Supabase not configured)." if IS_EN else "حفظ الفيدباك غير مفعل (Supabase غير مضبوط).")
else:
    feedback_choice = st.radio(
        "How was your experience?" if IS_EN else "كيف كانت تجربتك مع هذه الأداة؟",
        ("This tool was useful for me", "This tool was not useful") if IS_EN
        else ("هذه الأداة كانت مفيدة بالنسبة لي", "هذه الأداة لم تكن مفيدة"),
        key=f"{APP_ID}_feedback_choice",
    )

    useful = (feedback_choice == ("This tool was useful for me" if IS_EN else "هذه الأداة كانت مفيدة بالنسبة لي"))

    missing_reason = None
    if not useful:
        missing_reason = st.text_input(
            "What was missing? (one sentence)" if IS_EN else "ما الذي كان ناقصاً؟ (جملة واحدة)",
            max_chars=200,
            key=f"{APP_ID}_missing_reason",
        )

    with st.expander("💬 Quick feedback (3 questions)" if IS_EN else "💬 فيدباك سريع (3 أسئلة)", expanded=False):
        problem_text = st.text_area(
            "1) What were you trying to decide?" if IS_EN else "1) ما القرار الذي كنت تحاول اتخاذه؟",
            max_chars=280,
            key=f"{APP_ID}_problem_text",
        )
        helpful_reason = st.text_area(
            "2) Did it help? Why yes/no?" if IS_EN else "2) هل ساعدتك الأداة؟ لماذا نعم/لا؟",
            max_chars=280,
            key=f"{APP_ID}_helpful_reason",
        )
        must_use_text = st.text_area(
            "3) What would make this a must-use tool?" if IS_EN else "3) ما الذي سيجعل هذه الأداة «لازم تُستخدم»؟",
            max_chars=280,
            key=f"{APP_ID}_must_use_text",
        )

        submit_feedback = st.button("✅ Submit feedback" if IS_EN else "✅ إرسال الفيدباك", key=f"{APP_ID}_submit_feedback")

        if submit_feedback:
            has_any_text = any([
                (missing_reason or "").strip(),
                (problem_text or "").strip(),
                (helpful_reason or "").strip(),
                (must_use_text or "").strip(),
            ])

            if (not useful) and (not has_any_text):
                st.warning("Write at least one line 🙏" if IS_EN else "اكتب سطر واحد على الأقل 🙏")
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
                    st.success("Feedback saved ✅ Thank you!" if IS_EN else "تم حفظ الفيدباك ✅ شكرًا لك!")
                except Exception as e:
                    st.error(("Feedback error: " if IS_EN else "خطأ في حفظ الفيدباك: ") + str(e))

# =========================================================
# 15) Footer (fixed HTML style)
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



