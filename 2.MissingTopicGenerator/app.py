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
# 3) CSS — match your style
# =========================================================
st.markdown(
    f"""
<style>
/* Hide Streamlit chrome */
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

h1, h2, h3, h4, h5, h6 {{
    direction: {DIR} !important;
    text-align: {ALIGN} !important;
}}

p, div, span, label, li, [data-testid="stMarkdownContainer"] {{
    direction: {DIR} !important;
    text-align: {ALIGN} !important;
    unicode-bidi: plaintext !important;
    line-height: 1.8 !important;
    word-break: break-word;
}}

[data-testid="stExpander"] * {{
    direction: {DIR} !important;
    text-align: {ALIGN} !important;
    unicode-bidi: plaintext !important;
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

[data-testid="stDataFrame"] table {{
    direction: {DIR} !important;
    text-align: {ALIGN} !important;
}}
[data-testid="stDataFrame"] table thead tr th {{
    text-align: {ALIGN} !important;
}}
[data-testid="stDataFrame"] table tbody tr td {{
    text-align: {ALIGN} !important;
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
.footer-container .rtl-text {{
    direction: rtl;
    unicode-bidi: plaintext;
    font-weight: 600;
}}
.footer-container .ltr-text {{
    direction: ltr;
    unicode-bidi: plaintext;
}}
</style>
""",
    unsafe_allow_html=True,
)

# =========================================================
# 4) Tracking (visit + CTA)
# =========================================================
def get_session_visitor_id() -> str:
    if "visitor_id" not in st.session_state:
        st.session_state["visitor_id"] = str(uuid.uuid4())
    return st.session_state["visitor_id"]

def track_visit():
    visitor_id = get_session_visitor_id()
    try:
        supabase.rpc("track_visit", {"p_app_id": APP_ID, "p_visitor_id": visitor_id}).execute()
    except Exception:
        pass

def track_cta_event():
    try:
        supabase.rpc("increment_cta", {"p_app_id": APP_ID}).execute()
    except Exception:
        pass

track_visit()

# =========================================================
# 5) Caching helpers
# =========================================================
def get_content_hash(text: str) -> str:
    normalized = " ".join(text.strip().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

def parse_gap_response(raw: str):
    """
    Expect EXACT format:
    SUMMARY: ...
    TOPICS:
    1. title || reason || format
    ...
    """
    if not raw:
        return "", []

    lines = [l.strip() for l in raw.splitlines() if l.strip()]
    summary = ""
    topics = []
    in_topics = False

    for line in lines:
        if line.upper().startswith("SUMMARY:"):
            summary = line.split(":", 1)[1].strip()
            continue

        if line.upper().startswith("TOPICS"):
            in_topics = True
            continue

        if not in_topics:
            continue

        m = re.match(r"^\d+\.\s*(.*)$", line)
        if not m:
            continue

        after_dot = m.group(1).strip()
        parts = [p.strip(" |") for p in after_dot.split("||")]
        if len(parts) >= 3:
            topics.append(
                {
                    "topic_title": parts[0],
                    "gap_reason": parts[1],
                    "format_suggestion": parts[2],
                }
            )

    return summary, topics

def cache_read(app_id: str, content_hash: str):
    try:
        res = (
            supabase.table("viral_scores_cache")
            .select("analysis_text")
            .eq("app_id", app_id)
            .eq("content_hash", content_hash)
            .limit(1)
            .execute()
        )
        if res.data and len(res.data) > 0:
            return res.data[0].get("analysis_text") or ""
    except Exception:
        pass
    return ""

def cache_write(app_id: str, content_hash: str, analysis_text: str):
    try:
        supabase.table("viral_scores_cache").insert(
            {"app_id": app_id, "content_hash": content_hash, "analysis_text": analysis_text}
        ).execute()
    except Exception:
        pass

# =========================================================
# 6) Model call with retry + candidates (No 404 crash)
# =========================================================
# =========================================================
# 7) Model selection (NO 404) + retry
# =========================================================
MODEL_CANDIDATES = [
    "gemini-2.0-flash",
    "gemini-1.5-flash",
    "gemini-1.5-pro",
]

def get_working_model() -> str:
    """
    يجرّب موديلات معروفة ويختار أول موديل يشتغل فعلياً.
    بيحفظ الاختيار في session_state لتجنب الفحص كل مرة.
    """
    if "working_model" in st.session_state:
        return st.session_state["working_model"]

    test_cfg = types.GenerateContentConfig(max_output_tokens=1, temperature=0)

    for m in MODEL_CANDIDATES:
        try:
            _ = genai_client.models.generate_content(
                model=m,
                contents="ping",
                config=test_cfg,
            )
            st.session_state["working_model"] = m
            return m
        except Exception:
            continue

    # إذا ما اشتغل ولا موديل (نادر)
    st.session_state["working_model"] = MODEL_CANDIDATES[0]
    return MODEL_CANDIDATES[0]

def call_model_with_retry(prompt: str, cfg: types.GenerateContentConfig, retries: int = 3) -> str:
    """
    يستخدم موديل شغال 100% (get_working_model) + retries لأخطاء الضغط.
    """
    model_name = get_working_model()
    last_err = None

    for attempt in range(retries):
        try:
            resp = genai_client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=cfg,
            )
            text = (resp.text or "").strip()
            if text:
                return text
            last_err = RuntimeError("Empty response")
        except Exception as e:
            last_err = e
            time.sleep(1.5 * (attempt + 1))

    raise last_err if last_err else RuntimeError("Unknown model error")

# =========================================================
# 7) Gemini prompt (simple text output, no JSON)
# =========================================================
def analyze_content_gaps(my_posts: str, competitor_posts: str) -> str:
    if IS_EN:
        prompt = f"""
You are a content strategy expert specializing in Content Gap analysis.

Task:
- Compare "Client posts" vs "Competitor posts"
- Extract 5 to 7 missing topics that the audience expects, but the client isn't covering well
- Focus on topics suitable for an AI/product builder/creator/freelancer in business + AI

Client posts:
{my_posts}

Competitor posts:
{competitor_posts}

Return EXACTLY this format (no markdown, no extra text):

SUMMARY: Write a 1-2 sentence summary describing the gap between the client's content and competitors, and what the client is missing.
TOPICS:
1. Missing topic title || Why this is a valuable gap for the audience (tie it to what client posts vs competitors) || Best format (Reel, carousel, live, thread, etc.)
2. ...
3. ...
4. ...
5. ...
6. (if needed)
7. (if needed)

Rules:
- TOPICS count must be 5 to 7
- Keep it clear, direct, practical
- Do not add anything before SUMMARY or after the last topic line
"""
    else:
        prompt = f"""
أنت خبير استراتيجي محتوى متخصص في تحليل فجوات المحتوى (Content Gaps).

مهمتك:
- مقارنة قائمة منشورات "العميل" مع قائمة منشورات "المنافسين"
- استخراج 5 إلى 7 مواضيع مهمة للجمهور لم يتم تغطيتها جيداً أو تم تجاهلها
- التركيز على المواضيع المناسبة لصانع محتوى/مستقل/ريادي في مجال الأعمال الرقمية والذكاء الاصطناعي

قائمة منشورات العميل:
{my_posts}

قائمة منشورات المنافسين:
{competitor_posts}

أعد النتيجة بالصيغة التالية تماماً، بدون أي شروح إضافية أو Markdown أو كود:

SUMMARY: اكتب هنا ملخصاً تحليلياً من سطرين كحد أقصى يوضح الفرق بين نمط محتوى العميل والمنافسين، وما نوع المواضيع التي تنقص استراتيجية العميل حالياً.
TOPICS:
1. عنوان موضوع مفقود مقترح || شرح مختصر لماذا يعتبر هذا الموضوع فجوة مهمة للجمهور (مع ربطه بما ينشره العميل وما يهمله المنافسون) || اقتراح الشكل الأنسب للمحتوى (مثل: ريلز قصير، كروسيل، لايف، ثريد...)
2. ...
3. ...
4. ...
5. ...
6. (إن لزم)
7. (إن لزم)

احرص على:
- أن يكون عدد البنود في TOPICS بين 5 و 7
- أن تكون اللغة عربية واضحة ومقنعة ومباشرة
- عدم إضافة أي نص قبل SUMMARY أو بعد آخر سطر من المواضيع
"""

    cfg = types.GenerateContentConfig(
        temperature=0.3,
        top_p=0.85,
        top_k=32,
        max_output_tokens=1400,
    )

    try:
        text, used_model = call_model_with_retry(prompt, cfg, retries=3)
        return text
    except Exception as e:
        st.error(("Model/API error: " if IS_EN else "خطأ في الاتصال أو الموديل: ") + str(e))
        return ""

def get_or_create_gap_analysis(my_posts: str, competitor_posts: str):
    combined = f"{st.session_state['ui_lang']}||{my_posts.strip()}||---||{competitor_posts.strip()}"
    content_hash = get_content_hash(combined)

    cached = cache_read(APP_ID, content_hash)
    if cached:
        summary, topics = parse_gap_response(cached)
        if topics:
            return summary, topics, True

    raw = analyze_content_gaps(my_posts, competitor_posts)
    if not raw:
        return "", [], False

    summary, topics = parse_gap_response(raw)
    if topics:
        cache_write(APP_ID, content_hash, raw)

    return summary, topics, False

# =========================================================
# 8) UI
# =========================================================
st.title("🧩 " + ("Missing Topic Generator" if IS_EN else "منشئ المحتوى المفقود"))
st.caption(
    "Analyze your posts vs competitors to discover missing content topics."
    if IS_EN
    else "حلّل منشوراتك ومنشورات منافسيك لاكتشاف المواضيع التي يتوقعها جمهورك ولم تُغطَّ بعد."
)

with st.expander("ℹ️ " + ("What does this tool do?" if IS_EN else "ما الذي تفعله هذه الأداة؟"), expanded=True):
    if IS_EN:
        st.markdown("""
This tool helps you find **Content Gaps** between:
- What you post (titles / summaries)
- What competitors post in the same niche

You will get:
- ✅ 5–7 missing topic ideas that make sense for your audience  
- ✅ Why each topic matters (the gap explanation)  
- ✅ Best format suggestion (Reel / carousel / live / thread)

**Example input:**
Client:
1) Building 100 AI tools in 100 days  
2) Lessons from shipping Streamlit apps  
Competitors:
1) How to get your first client  
2) Positioning & pricing for freelancers  
3) Content strategy frameworks

**Example output:**
A list of missing topics like: pricing, positioning, case studies, content distribution, etc.
""")
    else:
        st.markdown("""
هذه الأداة تساعدك على تحليل فجوات المحتوى (**Content Gaps**) بين:
- ما تنشره أنت حالياً (عناوين/ملخصات)
- وما ينشره منافسوك في نفس السوق أو النيتش

ستحصلين على:
- ✅ 5–7 مواضيع مفقودة (جاهزة للنشر)
- ✅ سبب مهم لكل موضوع ولماذا هو فجوة حالياً
- ✅ اقتراح أفضل شكل محتوى (ريلز / كروسيل / لايف / ثريد…)

**مثال سريع للمدخلات:**
منشوراتك:
1) تحدي 100 أداة AI  
2) دروس من نشر تطبيقات Streamlit  
المنافسون:
1) كيف تحصل على أول عميل  
2) التسعير والتموضع  
3) استراتيجيات المحتوى

**المخرجات:**
قائمة مواضيع مفقودة مثل: التسعير، التموضع، دراسات حالة، توزيع المحتوى… إلخ.
""")

col1, col2 = st.columns(2)

if IS_EN:
    my_ph = "Example:\n1. Building 100 AI tools\n2. Lessons from Streamlit\n3. My freelancing mistakes...\n"
    comp_ph = "Example:\n1. Getting first client\n2. Pricing & positioning\n3. LinkedIn growth strategy...\n"
else:
    my_ph = "مثال:\n1. رحلتي مع بناء 100 تطبيق ذكاء اصطناعي\n2. دروس من نشر تطبيقات Streamlit\n3. أخطائي الأولى مع العملاء...\n"
    comp_ph = "مثال:\n1. كيف تحصل على أول عميل\n2. التسعير وبناء عرض قوي\n3. بناء براند شخصي على LinkedIn...\n"

with col1:
    my_posts_input = st.text_area(
        "✍️ " + ("Your recent posts (titles/summaries):" if IS_EN else "منشوراتك / محتوياتك الأخيرة (العناوين أو الملخصات):"),
        height=280,
        placeholder=my_ph,
        key="my_posts",
    )

with col2:
    competitor_posts_input = st.text_area(
        "📌 " + ("Competitors recent posts (titles/summaries):" if IS_EN else "منشورات المنافسين الأخيرة (العناوين أو الملخصات):"),
        height=280,
        placeholder=comp_ph,
        key="comp_posts",
    )

btn = st.button("🎯 " + ("Analyze gaps & generate topics" if IS_EN else "تحليل الفجوات واقتراح المواضيع"))

# =========================================================
# 9) Run analysis + Results
# =========================================================
if btn:
    if not my_posts_input.strip() or not competitor_posts_input.strip():
        st.warning("Please add both sides first." if IS_EN else "يرجى إدخال منشوراتك ومنشورات منافسيك أولاً.")
    elif len(my_posts_input.strip()) < 50 or len(competitor_posts_input.strip()) < 50:
        st.warning(
            "For better results, add more text (50+ chars each)."
            if IS_EN
            else "للحصول على تحليل أدق، يُفضّل إدخال وصف/عناوين كافية (50 حرفاً على الأقل لكل جانب)."
        )
    else:
        track_cta_event()
        with st.spinner("Analyzing..." if IS_EN else "🔎 جاري تحليل الفجوات واستخراج المواضيع..."):
            summary, topics, was_cached = get_or_create_gap_analysis(my_posts_input, competitor_posts_input)

        st.session_state["has_result"] = True
        st.session_state["summary"] = summary
        st.session_state["topics"] = topics
        st.session_state["was_cached"] = was_cached

if st.session_state.get("has_result") and st.session_state.get("topics"):
    summary = st.session_state.get("summary", "")
    topics = st.session_state.get("topics", [])
    was_cached = st.session_state.get("was_cached", False)

    st.subheader("📌 " + ("Summary" if IS_EN else "ملخّص النمط العام للمحتوى"))
    st.markdown(summary if summary else ("No summary generated." if IS_EN else "لم يتم توليد ملخص واضح."))

    if was_cached:
        st.caption("⚡ Loaded from cache" if IS_EN else "⚡ تم جلب النتيجة من الكاش")

    st.markdown("---")
    st.subheader("🧩 " + ("Missing Topics" if IS_EN else "قائمة المواضيع المفقودة"))

    df = pd.DataFrame(topics)

    if IS_EN:
        df.columns = ["Suggested topic", "Why it matters", "Best content format"]
    else:
        df.columns = ["الموضوع المقترح", "سبب الأهمية والفجوة", "اقتراح شكل المحتوى"]

    st.dataframe(df, use_container_width=True)

# =========================================================
# 10) Footer (same style)
# =========================================================
st.markdown(
    """
<div class="footer-container">
  <span class="rtl-text">جميع الحقوق محفوظة © 2026 |</span>
  <span class="ltr-text">AI Product Builder - Layan Khalil</span>
</div>
""",
    unsafe_allow_html=True,
)

