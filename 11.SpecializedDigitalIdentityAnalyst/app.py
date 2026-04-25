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

try:
    from supabase import create_client, Client
except Exception:
    create_client = None
    Client = None

# =========================================================
# 0) Page config
# =========================================================
st.set_page_config(
    page_title="محلل الهوية الرقمية",
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
SUPABASE_URL   = get_secret("SUPABASE_URL")
SUPABASE_KEY   = get_secret("SUPABASE_KEY")

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
APP_ID   = "10-digital-identity-analyzer"

if SUPABASE_URL and SUPABASE_KEY and create_client:
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception:
        supabase = None

# =========================================================
# 4) CSS
# =========================================================
st.markdown(
    f"""
<style>
/* Hide Streamlit UI chrome */
#MainMenu {{ visibility: hidden; }}
footer    {{ visibility: hidden; }}
header    {{ visibility: hidden; }}
div[data-testid="stToolbar"]      {{ visibility: hidden; }}
div[data-testid="stStatusWidget"] {{ visibility: hidden; }}
div[data-testid="stDecoration"]   {{ visibility: hidden; }}
div[class*="viewerBadge_container"] {{ display: none !important; }}

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
textarea, input,
.stTextInput > div > div > input,
.stTextArea  > div > textarea {{
    direction: {DIR} !important;
    text-align: {ALIGN} !important;
}}

/* Button */
.stButton>button {{
    font-weight: 800 !important;
    width: 100% !important;
    background-color: #0ea5e9 !important;
    color: #ffffff !important;
    border: none !important;
    border-radius: 10px !important;
    padding: 11px 18px !important;
    font-size: 1.05em !important;
    transition: all 0.25s ease !important;
    box-shadow: 0 4px 15px rgba(14, 165, 233, 0.35) !important;
}}
.stButton>button:hover {{
    background-color: #0284c7 !important;
    transform: translateY(-2px) !important;
    box-shadow: 0 6px 20px rgba(14, 165, 233, 0.55) !important;
}}

/* Score badges */
.score-high   {{ background-color: #10b981; color: #fff; font-weight: 800; padding: 5px 14px; border-radius: 6px; display: inline-block; }}
.score-medium {{ background-color: #f59e0b; color: #fff; font-weight: 800; padding: 5px 14px; border-radius: 6px; display: inline-block; }}
.score-low    {{ background-color: #dc2626; color: #fff; font-weight: 800; padding: 5px 14px; border-radius: 6px; display: inline-block; }}

/* Matrix table */
.matrix-table {{
    width: 100%; border-collapse: collapse; margin-top: 14px;
}}
.matrix-table th, .matrix-table td {{
    border: 1px solid #e0f2fe; padding: 12px; text-align: center; vertical-align: middle;
}}
.matrix-table th {{
    background-color: #e0f7ff; color: #0c4a6e; font-weight: 700; font-size: 1.05em;
}}
.matrix-table td:first-child {{
    text-align: {ALIGN}; font-weight: 600; background-color: #f8ffff;
}}

/* Result card */
.result-card {{
    padding: 22px; border-radius: 12px; margin-top: 20px;
    box-shadow: 0 6px 15px rgba(0,0,0,0.08);
    background: rgba(255,255,255,0.02);
    border: 1px solid rgba(0,0,0,0.06);
}}
.result-title {{
    font-size: 1.25em; font-weight: 900; color: #0c4a6e;
    border-bottom: 2px solid #bae6fd; padding-bottom: 8px; margin-bottom: 14px;
}}
.analysis-section {{
    border-top: 1px solid rgba(0,0,0,0.08);
    padding-top: 14px; margin-top: 14px;
}}

/* Upload area hint */
.upload-hint {{
    font-size: 0.88em; color: #64748b; margin-top: 6px;
    direction: {DIR} !important; text-align: {ALIGN} !important;
}}

/* Footer */
.footer-container {{
    width: 100%; text-align: center; margin-top: 45px;
    padding-top: 20px; border-top: 1px solid #666;
    font-size: 13px; display: flex; justify-content: center;
    gap: 6px; flex-wrap: wrap; direction: rtl !important;
}}
.footer-container, .footer-container * {{
    direction: rtl !important; text-align: center !important;
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
        "p_app_name":      app_name,
        "p_useful":        useful,
        "p_missing_reason": missing_reason,
        "p_problem_text":   problem_text,
        "p_helpful_reason": helpful_reason,
        "p_must_use_text":  must_use_text,
    }).execute()

track_visit()

# =========================================================
# 6) Cache helpers
# =========================================================
def get_hash(*parts: str) -> str:
    normalized = "||".join([" ".join((p or "").strip().split()) for p in parts])
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

def cache_get(app_id: str, content_hash: str):
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
            "app_id":       app_id,
            "content_hash": content_hash,
            "analysis_text": analysis_text,
        }).execute()
    except Exception:
        pass

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
    """اختبار نماذج multimodal — بدون google_search لأن الأداة تعتمد على الصورة."""
    test_prompt = "Return ONLY JSON: {\"ok\": true}"
    cfg = types.GenerateContentConfig(
        system_instruction="Return ONLY JSON.",
        response_mime_type="application/json",
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
# 8) File helper
# =========================================================
def file_to_part(uploaded_file):
    if uploaded_file is not None:
        return types.Part.from_bytes(
            data=uploaded_file.getvalue(),
            mime_type=uploaded_file.type,
        )
    return None

# =========================================================
# 9) Core analysis function
# =========================================================
MAX_RETRIES   = 4
INITIAL_DELAY = 2

def build_system_prompt() -> str:
    if IS_EN:
        return (
            "You are a senior Digital Identity Analyst specializing in social media personal branding. "
            "Analyze the user's text samples and profile screenshot together. "
            "Produce a strict JSON response with these exact keys: "
            "'ConsistencyMatrix' (object), 'ObservedIdentitySummary' (string), "
            "'StrategicAdjustments' (string), 'QuickWins' (array of 3 short strings). "
            "Matrix sub-keys: Textual_Identity_Score, Textual_Goal_Score, "
            "Visual_Identity_Score, Visual_Goal_Score — each MUST be one of: High / Medium / Low."
        )
    return (
        "أنت محلل هوية رقمية متخصص في البراندينج الشخصي على منصات التواصل الاجتماعي. "
        "حلّل عينات النصوص ولقطة الملف الشخصي معاً. "
        "أنتج استجابة JSON صارمة بهذه المفاتيح بالضبط: "
        "'ConsistencyMatrix' (كائن), 'ObservedIdentitySummary' (نص), "
        "'StrategicAdjustments' (نص), 'QuickWins' (مصفوفة من 3 نصوص قصيرة قابلة للتنفيذ). "
        "مفاتيح المصفوفة الفرعية: Textual_Identity_Score, Textual_Goal_Score, "
        "Visual_Identity_Score, Visual_Goal_Score — كل قيمة MUST تكون: عالي / متوسط / منخفض."
    )

def build_user_prompt(identity: str, goal: str, platform: str, content_samples: str) -> str:
    if IS_EN:
        return (
            f"Declared identity: {identity}\n"
            f"Strategic goal: {goal}\n"
            f"Primary platform: {platform}\n\n"
            f"Content samples (last 3-5 posts):\n---\n{content_samples}\n---\n\n"
            "Also analyze the uploaded screenshot for visual identity (colors, fonts, layout quality).\n"
            "Return ONLY a valid JSON object."
        )
    return (
        f"الهوية المُعلنة: {identity}\n"
        f"الهدف الاستراتيجي: {goal}\n"
        f"المنصة الأساسية: {platform}\n\n"
        f"عينات المحتوى (آخر 3-5 منشورات):\n---\n{content_samples}\n---\n\n"
        "حلّل أيضاً لقطة الشاشة المرفوعة للهوية البصرية (الألوان، الخطوط، جودة التصميم).\n"
        "أعد فقط كائن JSON صحيح وكامل."
    )

def extract_json_safely(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"```json\s*|```", "", text).strip()
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    start = text.find("{")
    end   = text.rfind("}")
    if start != -1 and end != -1:
        return text[start:end + 1]
    return text

def analyze_identity(image_part, identity: str, goal: str, platform: str, content_samples: str):
    if not client:
        return {"error": "API connection failed"}, []

    model_name   = get_working_model_name()
    content_hash = get_hash(APP_ID, identity, goal, platform, content_samples, st.session_state["ui_lang"])

    # كاش نصي فقط (الصورة لا تُخزَّن)
    cached = cache_get(APP_ID, content_hash)
    if cached:
        try:
            return json.loads(cached), []
        except Exception:
            pass

    response_schema = types.Schema(
        type=types.Type.OBJECT,
        properties={
            "ConsistencyMatrix": types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "Textual_Identity_Score": types.Schema(
                        type=types.Type.STRING,
                        enum=(["High","Medium","Low"] if IS_EN else ["عالي","متوسط","منخفض"]),
                    ),
                    "Textual_Goal_Score": types.Schema(
                        type=types.Type.STRING,
                        enum=(["High","Medium","Low"] if IS_EN else ["عالي","متوسط","منخفض"]),
                    ),
                    "Visual_Identity_Score": types.Schema(
                        type=types.Type.STRING,
                        enum=(["High","Medium","Low"] if IS_EN else ["عالي","متوسط","منخفض"]),
                    ),
                    "Visual_Goal_Score": types.Schema(
                        type=types.Type.STRING,
                        enum=(["High","Medium","Low"] if IS_EN else ["عالي","متوسط","منخفض"]),
                    ),
                },
                required=["Textual_Identity_Score","Textual_Goal_Score",
                          "Visual_Identity_Score","Visual_Goal_Score"],
            ),
            "ObservedIdentitySummary": types.Schema(type=types.Type.STRING),
            "StrategicAdjustments":    types.Schema(type=types.Type.STRING),
            "QuickWins": types.Schema(
                type=types.Type.ARRAY,
                items=types.Schema(type=types.Type.STRING),
            ),
        },
        required=["ConsistencyMatrix","ObservedIdentitySummary",
                  "StrategicAdjustments","QuickWins"],
    )

    cfg = types.GenerateContentConfig(
        system_instruction=build_system_prompt(),
        response_mime_type="application/json",
        response_schema=response_schema,
        temperature=0.0,
        max_output_tokens=2000,
    )

    prompt_part  = types.Part(text=build_user_prompt(identity, goal, platform, content_samples))
    contents     = [image_part, prompt_part]

    last_err = None
    for attempt in range(MAX_RETRIES):
        try:
            resp     = client.models.generate_content(model=model_name, contents=contents, config=cfg)
            raw_text = getattr(resp, "text", "") or ""
            json_str = extract_json_safely(raw_text)

            if not json_str:
                last_err = "Empty response"
                continue

            try:
                result = json.loads(json_str)
                required = ["ConsistencyMatrix","ObservedIdentitySummary",
                            "StrategicAdjustments","QuickWins"]
                if all(k in result for k in required):
                    cache_set(APP_ID, content_hash, json.dumps(result, ensure_ascii=False))
                    return result, []
                else:
                    last_err = "Missing JSON keys"
            except json.JSONDecodeError as e:
                last_err = f"JSON Error: {e}"

        except (ResourceExhausted, ServiceUnavailable, DeadlineExceeded) as e:
            last_err = e
            delay = INITIAL_DELAY * (2 ** attempt)
            st.warning(
                f"⚠️ {'Retrying in' if IS_EN else 'إعادة المحاولة خلال'} {delay}s... "
                f"({'attempt' if IS_EN else 'محاولة'} {attempt+1}/{MAX_RETRIES})"
            )
            time.sleep(delay)
        except Exception as e:
            last_err = e
            time.sleep(INITIAL_DELAY * (attempt + 1))

    return {"error": f"{'Analysis failed' if IS_EN else 'فشل التحليل'}: {str(last_err)}"}, []

# =========================================================
# 10) UI copy (AR/EN)
# =========================================================
if IS_EN:
    st.title("🔬 Digital Identity Analyzer")
    st.caption("Upload your last posts + a profile screenshot → get a Consistency Matrix + instant strategic fixes.")
else:
    st.title("🔬 محلل الهوية الرقمية")
    st.subheader("الصق منشوراتك الأخيرة + ارفع لقطة ملفك الشخصي → احصل على مصفوفة الاتساق وتوصيات استراتيجية فورية.")

with st.expander("💡 How it works" if IS_EN else "💡 كيف تعمل الأداة؟", expanded=False):
    if IS_EN:
        st.markdown("""
**What it does:** Compares what you *say* you are vs. what your content and visuals actually communicate.

**What you get:**
- **Consistency Matrix** — 4 scores: Textual × Identity, Textual × Goal, Visual × Identity, Visual × Goal
- **Observed Identity Summary** — what your content actually projects
- **Strategic Adjustments** — fixes for low scores
- **Quick Wins** — 3 things you can do today

**How to fill in content samples:**
```
--- Post 1 ---
Type: carousel
Engagement: high
Text: (paste full text)
--- Post 2 ---
Type: text post
Engagement: medium
Text: (paste full text)
```
""")
    else:
        st.markdown("""
**ماذا تفعل:** تقارن بين ما تقول إنك عليه وما يوصله محتواك وهويتك البصرية فعلياً.

**ماذا ستحصل:**
- **مصفوفة الاتساق** — 4 درجات: النص × الهوية، النص × الهدف، البصري × الهوية، البصري × الهدف
- **ملخص الهوية الملحوظة** — ما يعكسه محتواك فعلياً
- **تعديلات استراتيجية** — معالجة نقاط الضعف
- **انتصارات سريعة** — 3 خطوات تنفذها اليوم

**طريقة إدخال عينات المحتوى:**
```
--- بوست 1 ---
النوع: كاروسيل
التفاعل: عالي
النص: (الصق النص كاملاً)
--- بوست 2 ---
النوع: نص
التفاعل: متوسط
النص: (الصق النص كاملاً)
```
""")

st.markdown("---")

# =========================================================
# 11) Inputs
# =========================================================
if IS_EN:
    samples_label  = "1. Paste your last 3–5 posts (structured):"
    samples_ph     = "--- Post 1 ---\nType: ...\nEngagement: high\nText: ..."
    identity_label = "2. Your declared identity / niche:"
    identity_ph    = "e.g. AI systems builder helping founders automate workflows"
    goal_label     = "3. Your current strategic goal:"
    goal_ph        = "e.g. attract inbound consulting leads from LinkedIn"
    platform_label = "4. Primary platform:"
    upload_label   = "5. Upload a screenshot of your profile page (for visual analysis):"
    upload_hint    = "One screenshot of your home/profile feed — colors, fonts, layout."
    btn_label      = "🚀 Run Identity Analysis"
else:
    samples_label  = "1. الصق آخر 3-5 منشورات (مُهيكلة):"
    samples_ph     = "--- بوست 1 ---\nالنوع: ...\nالتفاعل: عالي\nالنص: ..."
    identity_label = "2. هويتك / تخصصك المُعلن:"
    identity_ph    = "مثلاً: باني أنظمة ذكاء اصطناعي يساعد المؤسسين على أتمتة العمليات"
    goal_label     = "3. هدفك الاستراتيجي الحالي:"
    goal_ph        = "مثلاً: جذب عملاء استشارات من LinkedIn"
    platform_label = "4. المنصة الأساسية:"
    upload_label   = "5. ارفع لقطة شاشة لملفك الشخصي (للتحليل البصري):"
    upload_hint    = "لقطة واحدة للصفحة الرئيسية — الألوان والخطوط والتصميم."
    btn_label      = "🚀 بدء تحليل الهوية"

content_samples = st.text_area(
    samples_label,
    placeholder=samples_ph,
    height=260,
    key="samples_input",
)

col1, col2 = st.columns([2, 1])

with col1:
    identity = st.text_area(
        identity_label,
        placeholder=identity_ph,
        height=100,
        key="identity_input",
    )
    goal = st.text_area(
        goal_label,
        placeholder=goal_ph,
        height=100,
        key="goal_input",
    )

with col2:
    platform = st.selectbox(
        platform_label,
        options=(["LinkedIn","X (Twitter)","Instagram","TikTok","Facebook","Threads"]
                 if IS_EN else
                 ["LinkedIn","X (Twitter)","Instagram","TikTok","Facebook","Threads"]),
        key="platform_select",
    )
    uploaded_file = st.file_uploader(
        upload_label,
        type=["png","jpg","jpeg","webp"],
        key="profile_screenshot",
    )
    st.markdown(f'<p class="upload-hint">💡 {upload_hint}</p>', unsafe_allow_html=True)

# =========================================================
# 12) Run button
# =========================================================
if st.button(btn_label, use_container_width=True):
    identity_clean = identity.strip()
    goal_clean     = goal.strip()
    samples_clean  = content_samples.strip()

    # Validation
    errors = []
    if not uploaded_file:
        errors.append("الصورة مطلوبة لتحليل الهوية البصرية." if not IS_EN else "Profile screenshot is required for visual analysis.")
    if len(identity_clean) < 10:
        errors.append("اكتب هويتك بوضوح (10 أحرف على الأقل)." if not IS_EN else "Describe your identity clearly (min 10 chars).")
    if len(goal_clean) < 10:
        errors.append("اكتب هدفك الاستراتيجي (10 أحرف على الأقل)." if not IS_EN else "Describe your goal clearly (min 10 chars).")
    if len(samples_clean) < 100:
        errors.append("أضف عينات محتوى كافية (100 حرف على الأقل)." if not IS_EN else "Add enough content samples (min 100 chars).")

    if errors:
        for e in errors:
            st.warning(e)
        st.stop()

    track_cta_event()
    image_part = file_to_part(uploaded_file)

    with st.spinner("جاري تحليل النصوص والهوية البصرية..." if not IS_EN else "Analyzing text and visual identity..."):
        analysis_data, _ = analyze_identity(
            image_part, identity_clean, goal_clean,
            platform, samples_clean
        )

    st.session_state["has_result"]    = True
    st.session_state["analysis_data"] = analysis_data

# =========================================================
# 13) Show results
# =========================================================
if st.session_state.get("has_result"):
    analysis_data = st.session_state.get("analysis_data", {}) or {}

    if "error" in analysis_data:
        st.error(("Analysis failed: " if IS_EN else "فشل التحليل: ") + str(analysis_data["error"]))
    else:
        st.markdown("---")
        st.markdown("## 📊 Results" if IS_EN else "## 📊 نتائج التحليل")

        # ---- Score color helper ----
        HIGH_VALS   = ["High",   "عالي"]
        MEDIUM_VALS = ["Medium", "متوسط"]

        def badge(score: str) -> str:
            if score in HIGH_VALS:
                return f'<span class="score-high">{score}</span>'
            if score in MEDIUM_VALS:
                return f'<span class="score-medium">{score}</span>'
            return f'<span class="score-low">{score}</span>'

        matrix = analysis_data.get("ConsistencyMatrix", {})

        # ---- Consistency Matrix ----
        st.markdown('<div class="result-card">', unsafe_allow_html=True)

        if IS_EN:
            matrix_html = f"""
            <div class="result-title">Consistency Matrix</div>
            <table class="matrix-table">
                <thead>
                    <tr>
                        <th>Dimension</th>
                        <th>vs. Declared Identity</th>
                        <th>vs. Strategic Goal</th>
                    </tr>
                </thead>
                <tbody>
                    <tr>
                        <td>Textual (message & tone)</td>
                        <td>{badge(matrix.get("Textual_Identity_Score", "-"))}</td>
                        <td>{badge(matrix.get("Textual_Goal_Score", "-"))}</td>
                    </tr>
                    <tr>
                        <td>Visual (colors & design)</td>
                        <td>{badge(matrix.get("Visual_Identity_Score", "-"))}</td>
                        <td>{badge(matrix.get("Visual_Goal_Score", "-"))}</td>
                    </tr>
                </tbody>
            </table>
            """
        else:
            matrix_html = f"""
            <div class="result-title">مصفوفة الاتساق</div>
            <table class="matrix-table">
                <thead>
                    <tr>
                        <th>البعد</th>
                        <th>مقارنةً بالهوية المعلنة</th>
                        <th>مقارنةً بالهدف الاستراتيجي</th>
                    </tr>
                </thead>
                <tbody>
                    <tr>
                        <td>التناسق النصي (الرسالة والنبرة)</td>
                        <td>{badge(matrix.get("Textual_Identity_Score", "-"))}</td>
                        <td>{badge(matrix.get("Textual_Goal_Score", "-"))}</td>
                    </tr>
                    <tr>
                        <td>التناسق البصري (الألوان والتصميم)</td>
                        <td>{badge(matrix.get("Visual_Identity_Score", "-"))}</td>
                        <td>{badge(matrix.get("Visual_Goal_Score", "-"))}</td>
                    </tr>
                </tbody>
            </table>
            """

        st.markdown(matrix_html, unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

        # ---- Observed Identity Summary ----
        st.markdown('<div class="result-card">', unsafe_allow_html=True)
        st.markdown(
            f'<div class="result-title">{"Observed Identity Summary" if IS_EN else "ملخص الهوية الملحوظة"}</div>',
            unsafe_allow_html=True,
        )
        st.markdown(analysis_data.get("ObservedIdentitySummary", "—"))
        st.markdown("</div>", unsafe_allow_html=True)

        # ---- Strategic Adjustments ----
        st.markdown('<div class="result-card">', unsafe_allow_html=True)
        st.markdown(
            f'<div class="result-title">{"Strategic Adjustments" if IS_EN else "تعديلات استراتيجية فورية"}</div>',
            unsafe_allow_html=True,
        )
        st.markdown(analysis_data.get("StrategicAdjustments", "—"))
        st.markdown("</div>", unsafe_allow_html=True)

        # ---- Quick Wins (NEW) ----
        quick_wins = analysis_data.get("QuickWins", [])
        if quick_wins:
            st.markdown('<div class="result-card">', unsafe_allow_html=True)
            st.markdown(
                f'<div class="result-title">{"⚡ Quick Wins — Do These Today" if IS_EN else "⚡ انتصارات سريعة — نفّذها اليوم"}</div>',
                unsafe_allow_html=True,
            )
            for i, win in enumerate(quick_wins[:3], 1):
                st.markdown(f"**{i}.** {win}")
            st.markdown("</div>", unsafe_allow_html=True)

# =========================================================
# 14) Feedback UI (Supabase optional)
# =========================================================
st.markdown("---")
st.subheader("📝 Feedback" if IS_EN else "📝 فيدباك")

if not supabase:
    st.caption(
        "Feedback saving is disabled (Supabase not configured)."
        if IS_EN else
        "حفظ الفيدباك غير مفعل (Supabase غير مضبوط)."
    )
else:
    feedback_choice = st.radio(
        "How was your experience?" if IS_EN else "كيف كانت تجربتك مع هذه الأداة؟",
        (("This tool was useful for me", "This tool was not useful")
         if IS_EN else
         ("هذه الأداة كانت مفيدة بالنسبة لي", "هذه الأداة لم تكن مفيدة")),
        key=f"{APP_ID}_feedback_choice",
    )

    useful = feedback_choice in ("This tool was useful for me", "هذه الأداة كانت مفيدة بالنسبة لي")

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
            max_chars=280, key=f"{APP_ID}_problem_text",
        )
        helpful_reason = st.text_area(
            "2) Did it help? Why yes/no?" if IS_EN else "2) هل ساعدتك الأداة؟ لماذا نعم/لا؟",
            max_chars=280, key=f"{APP_ID}_helpful_reason",
        )
        must_use_text = st.text_area(
            "3) What would make this a must-use tool?" if IS_EN else "3) ما الذي سيجعل هذه الأداة «لازم تُستخدم»؟",
            max_chars=280, key=f"{APP_ID}_must_use_text",
        )

        if st.button("✅ Submit feedback" if IS_EN else "✅ إرسال الفيدباك", key=f"{APP_ID}_submit_feedback"):
            has_text = any([
                (missing_reason  or "").strip(),
                (problem_text    or "").strip(),
                (helpful_reason  or "").strip(),
                (must_use_text   or "").strip(),
            ])
            if (not useful) and (not has_text):
                st.warning("Write at least one line 🙏" if IS_EN else "اكتب سطر واحد على الأقل 🙏")
            else:
                try:
                    save_feedback_via_rpc(
                        app_name=APP_ID, useful=useful,
                        missing_reason=(missing_reason or "").strip() or None,
                        problem_text=(problem_text    or "").strip() or None,
                        helpful_reason=(helpful_reason or "").strip() or None,
                        must_use_text=(must_use_text   or "").strip() or None,
                    )
                    st.success("Feedback saved ✅ Thank you!" if IS_EN else "تم حفظ الفيدباك ✅ شكرًا لك!")
                except Exception as e:
                    st.error(("Feedback error: " if IS_EN else "خطأ في حفظ الفيدباك: ") + str(e))

# =========================================================
# 15) Footer
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
