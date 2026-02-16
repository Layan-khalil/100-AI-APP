import streamlit as st
import uuid
import hashlib
import os
import re
import pandas as pd

from supabase import create_client, Client
from google import genai
from google.genai import types
from google.api_core.exceptions import ResourceExhausted, ServiceUnavailable, DeadlineExceeded

# =========================================================
# 0) PAGE CONFIG
# =========================================================
st.set_page_config(
    page_title="منشئ المحتوى المفقود",
    layout="wide",
    initial_sidebar_state="collapsed",
)

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
    return st.secrets.get(key) or os.environ.get(key)

SUPABASE_URL = get_secret("SUPABASE_URL")
SUPABASE_KEY = get_secret("SUPABASE_KEY")
GOOGLE_API_KEY = get_secret("GOOGLE_API_KEY")

if not all([SUPABASE_URL, SUPABASE_KEY, GOOGLE_API_KEY]):
    st.error("⚠️ Missing API keys in Secrets / Environment Variables." if IS_EN else "⚠️ مفاتيح الربط ناقصة في Secrets أو Environment Variables.")
    st.stop()

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
genai_client = genai.Client(api_key=GOOGLE_API_KEY)

APP_ID = "missing-topic-generator"

# =========================================================
# 3) MODEL (FLEXIBLE) + RETRY
# =========================================================
MODEL_CANDIDATES = [
    "gemini-2.5-flash-001",
    "gemini-2.5-flash",
    "gemini-2.0-flash-001",
    "gemini-2.0-flash",
]

def get_working_model():
    if "working_model" in st.session_state:
        return st.session_state["working_model"]

    for m in MODEL_CANDIDATES:
        try:
            genai_client.models.generate_content(
                model=m,
                contents="test",
                config=types.GenerateContentConfig(max_output_tokens=1),
            )
            st.session_state["working_model"] = m
            return m
        except Exception:
            continue

    st.session_state["working_model"] = MODEL_CANDIDATES[0]
    return MODEL_CANDIDATES[0]

def call_model_with_retry(model: str, prompt: str, cfg: types.GenerateContentConfig, retries: int = 3):
    last_err = None
    for attempt in range(retries):
        try:
            resp = genai_client.models.generate_content(model=model, contents=prompt, config=cfg)
            return resp.text or ""
        except (ResourceExhausted, ServiceUnavailable, DeadlineExceeded) as e:
            last_err = e
        except Exception as e:
            last_err = e
            break
    raise last_err if last_err else RuntimeError("Unknown model error")

# =========================================================
# 4) TRACKING (VISIT + CTA)
# =========================================================
def get_session_visitor_id() -> str:
    if "visitor_id" not in st.session_state:
        st.session_state["visitor_id"] = str(uuid.uuid4())
    return st.session_state["visitor_id"]

def track_visit():
    try:
        supabase.rpc("track_visit", {"p_app_id": APP_ID, "p_visitor_id": get_session_visitor_id()}).execute()
    except Exception:
        pass

def track_cta_event():
    try:
        supabase.rpc("increment_cta", {"p_app_id": APP_ID}).execute()
    except Exception:
        pass

track_visit()

# =========================================================
# 5) FEEDBACK RPC (نفس نمط أدواتك)
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
# 6) CACHING (viral_scores_cache)
# =========================================================
def get_content_hash(text: str) -> str:
    normalized = " ".join(text.strip().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

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
        if res.data:
            return res.data[0]["analysis_text"]
    except Exception:
        pass
    return None

def cache_set(app_id: str, content_hash: str, analysis_text: str):
    try:
        supabase.table("viral_scores_cache").insert(
            {"app_id": app_id, "content_hash": content_hash, "analysis_text": analysis_text}
        ).execute()
    except Exception:
        pass

# =========================================================
# 7) PARSING (FLEXIBLE) - يدعم 1) أو - أو * أو ترقيم
# =========================================================
# =========================================================
# 7) PARSING (ROBUST & FLEXIBLE)
# =========================================================
def parse_gap_response(raw: str):
    if not raw:
        return "", []

    summary = ""
    topics = []

    # 1) استخراج الملخص - نبحث عن أي نص يبدأ بـ SUMMARY أو ملخص
    summary_match = re.search(r"(?:SUMMARY|ملخص)\s*[:：]\s*(.*?)(?=(?:TOPICS|المواضيع)|$)", raw, re.DOTALL | re.IGNORECASE)
    if summary_match:
        summary = summary_match.group(1).strip()

    # 2) استخراج المواضيع - منطق "صيد" البيانات المرن
    # سنبحث عن الأسطر التي تحتوي على فواصل (||) أو ( | ) الخاصة بجداول الماركدون
    lines = raw.splitlines()
    for line in lines:
        line = line.strip()
        # إذا كان السطر هو رأس الجدول أو سطر التنسيق (---) نتجاهله
        if "---" in line and "|" in line: continue
        
        # تحويل جداول Markdown إلى صيغة الـ || إذا وجدت
        if line.startswith("|") and line.endswith("|"):
            line = " || ".join([p.strip() for p in line.split("|") if p.strip()])

        if "||" in line:
            # تنظيف الترقيم (1. أو -)
            clean_line = re.sub(r"^(?:\d+[\.\)\-]*|[-*•])\s*", "", line).strip()
            parts = [p.strip() for p in clean_line.split("||")]
            
            if len(parts) >= 3:
                topics.append({
                    "topic_title": parts[0],
                    "gap_reason": parts[1],
                    "format_suggestion": parts[2],
                })
    
    # تنظيف الملخص من أي نجوم (Markdown)
    summary = summary.replace("**", "").replace("__", "").strip()
    return summary, topics

def get_or_create_gap_analysis(my_posts: str, competitor_posts: str):
    combined_text = f"{my_posts}\n---\n{competitor_posts}\nLANG={st.session_state.get('ui_lang', 'AR')}"
    content_hash = get_content_hash(combined_text)

    # 1) كاش
    cached_text = cache_get(APP_ID, content_hash)
    if cached_text:
        s, t = parse_gap_response(cached_text)
        if t: return s, t, True, None

    # 2) استدعاء الموديل مع Force JSON-like structure
    model_name = get_working_model()
    original_prompt = build_prompt(my_posts, competitor_posts)
    
    # إضافة أمر حاسم في نهاية البرومبت
    final_prompt = original_prompt + "\n\nCRITICAL: You MUST use '||' as a separator. Do NOT use Markdown tables. Format: Title || Reason || Format"

    try:
        # تقليل الحرارة لأقصى درجة لضمان الالتزام
        cfg = types.GenerateContentConfig(temperature=0.0, max_output_tokens=2000)
        raw_text = call_model_with_retry(model_name, final_prompt, cfg, retries=3)
        
        # 3) تحليل
        s, t = parse_gap_response(raw_text)

        # إذا فشل التحليل برغم كل شيء، نقوم بمحاولة أخيرة يدوية
        if not t:
            # محاولة البحث عن أي نمط منظم في النص
            return s, [], False, "لم يتمكن الموديل من تنسيق الإجابة، يرجى المحاولة مرة أخرى."

        cache_set(APP_ID, content_hash, raw_text)
        return s, t, False, None

    except Exception as e:
        return "", [], False, str(e)
# =========================================================
# 8) PROMPT - PERSONAL BRANDING + FORMAT OPTIONS محددة
# =========================================================
ALLOWED_FORMATS_AR = "ريلز / بوست / كاروسيل / فيديو / مقال"
ALLOWED_FORMATS_EN = "Reel / Post / Carousel / Video / Article"


# =========================================================
# 8) PROMPT - PERSONAL BRANDING + SMEG (ORIGINAL TEXT + ROBUST ADDITIONS)
# =========================================================
def build_prompt(my_posts: str, competitor_posts: str) -> str:
    # خيارات الأشكال المتاحة بناءً على اللغة
    format_options = ALLOWED_FORMATS_EN if IS_EN else ALLOWED_FORMATS_AR
    
    if IS_EN:
        return f"""
You are a Personal Branding content strategist specializing in Content Gap analysis across social platforms.

Your task:
- Understand the creator’s content style, positioning, and messaging.
- Compare it with competitors that achieve higher engagement.
- Identify missing angles or topics that reduce trust, authority, or engagement.

Use SMEG framework when relevant:
S — Story (personal experience)
M — Meaning (insight or perspective)
E — Emotion (emotional trigger)
G — Guidance (practical takeaway)

IMPORTANT (Robust Handling Additions):
- The input may contain long, unstructured paragraphs, stories, or links. Focus on the core message and ignore URLs.
- Do not assume equal number of posts.
- The "Best format" MUST be ONLY one of these options exactly: {format_options}
- Return EXACTLY in the format below using '||' as a separator.

Creator posts:
{my_posts}

Competitors posts:
{competitor_posts}

Return EXACTLY in this format (no markdown, no bullets, no extra text):

SUMMARY: Write a 1–2 line summary explaining the biggest gap in the creator’s personal branding content.

TOPICS:
1. Missing topic title || Why this is an important gap (mention missing SMEG element if relevant) || Best format
2. Missing topic title || Why this is an important gap || Best format
3. Missing topic title || Why this is an important gap || Best format
4. Missing topic title || Why this is an important gap || Best format
5. Missing topic title || Why this is an important gap || Best format
6. (if needed)
7. (if needed)
"""

    else:
        return f"""
أنت خبير استراتيجية محتوى متخصص في بناء البراند الشخصي وتحليل فجوات المحتوى.

مهمتك:
- فهم نمط محتوى صاحب الحساب (الأسلوب، الرسائل، الزوايا المتكررة).
- مقارنة ذلك مع محتوى المنافسين الذين يحققون تفاعل أعلى.
- استخراج المواضيع أو الزوايا الناقصة التي تجعل المحتوى أقل جذباً أو ثقة أو مشاركة.

استخدم إطار SMEG عند الحاجة:
S — Story: قصة أو تجربة شخصية.
M — Meaning: فكرة أو معنى يغيّر طريقة التفكير.
E — Emotion: عنصر عاطفي يحفّز التفاعل.
G — Guidance: خطوة عملية أو توجيه واضح.

مهم جداً (إضافات لضمان معالجة الفقرات):
- النصوص قد تكون طويلة، فقرات قصصية، أو غير منظمة وتحوي روابط؛ حلل المضمون وتجاهل الروابط.
- لا تفترض أن عدد المنشورات متساوٍ.
- خانة "الشكل المقترح" يجب أن تكون فقط واحدة من: {format_options}
- التزم تماماً باستخدام الفاصل '||' بين الأجزاء.

منشورات صاحب الحساب:
{my_posts}

منشورات المنافسين:
{competitor_posts}

أعد النتيجة بالصيغة التالية تماماً (بدون Markdown وبدون أي نص إضافي):

SUMMARY: ملخص من سطرين يوضح أكبر فجوة في محتوى البراند الشخصي لديك.

TOPICS:
1. عنوان موضوع مفقود || لماذا هذه فجوة (مع ذكر عنصر SMEG الناقص إن وجد) || الشكل المقترح
2. عنوان موضوع مفقود || لماذا هذه فجوة || الشكل المقترح
3. عنوان موضوع مفقود || لماذا هذه فجوة || الشكل المقترح
4. عنوان موضوع مفقود || لماذا هذه فجوة || الشكل المقترح
5. عنوان موضوع مفقود || لماذا هذه فجوة || الشكل المقترح
6. (إن لزم)
7. (إن لزم)
"""
def get_or_create_gap_analysis(my_posts: str, competitor_posts: str):
    """
    الدالة الرئيسية لجلب التحليل من الكاش أو توليده عبر الموديل.
    """
    # إنشاء Hash فريد بناءً على المدخلات واللغة
    combined_text = (
        f"{my_posts}\n---\n{competitor_posts}\n"
        f"LANG={st.session_state.get('ui_lang', 'AR')}"
    )
    content_hash = get_content_hash(combined_text)

    # =========================
    # 1) محاولة القراءة من الكاش
    # =========================
    cached_text = cache_get(APP_ID, content_hash)
    if cached_text:
        s, t = parse_gap_response(cached_text)
        if t: # إذا نجح التحليل نرجع النتيجة
            return s, t, True, None

    # =========================
    # 2) استدعاء الموديل (في حال عدم وجود كاش أو فشله)
    # =========================
    model_name = get_working_model()
    prompt = build_prompt(my_posts, competitor_posts)

    cfg = types.GenerateContentConfig(
        temperature=0.3, # تقليل الحرارة لزيادة الالتزام بالتنسيق
        top_p=0.9,
        max_output_tokens=2000,
    )

    try:
        # استدعاء الموديل مع خاصية إعادة المحاولة (Retry)
        raw_text = call_model_with_retry(
            model_name,
            prompt,
            cfg,
            retries=3
        )
        
        # حفظ الرد الخام في الكاش للاستخدام المستقبلي
        cache_set(APP_ID, content_hash, raw_text)

        # =========================
        # 3) تحليل النتيجة النهائية
        # =========================
        s, t = parse_gap_response(raw_text)

        # التحقق النهائي لضمان وجود مواضيع
        if not t:
            return s, [], False, "Parsing failed: AI output was not in the correct '||' format. Please try again."

        return s, t, False, None

    except Exception as e:
        return "", [], False, f"Model Error: {str(e)}"
# =========================================================
# 9) CSS (Hide Streamlit header + RTL/LTR + Red button + Footer RTL)
# =========================================================
st.markdown(
    f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Cairo:wght@400;700&display=swap');

#MainMenu {{ visibility: hidden; }}
header {{ visibility: hidden; }}
footer {{ visibility: hidden; }}
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

h1,h2,h3,h4,h5,h6,p,div,span,label,li,[data-testid="stMarkdownContainer"] {{
  direction: {DIR} !important;
  text-align: {ALIGN} !important;
  unicode-bidi: plaintext !important;
  line-height: 1.75 !important;
}}

textarea, input {{
  direction: {DIR} !important;
  text-align: {ALIGN} !important;
}}

.stButton > button {{
  background-color: #e63946 !important;
  color: white !important;
  font-weight: 800 !important;
  border-radius: 14px !important;
  width: 100% !important;
  height: 3.2em !important;
  border: none !important;
}}
.stButton > button:hover {{
  filter: brightness(0.95);
  transform: scale(1.01);
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
# 10) UI TEXTS + PLACEHOLDERS (PERSONAL BRANDING)
# =========================================================
TITLE = "🧩 Missing Content Generator" if IS_EN else "🧩 منشئ المحتوى المفقود"
CAPTION = "Compare your content vs competitors to discover missing topics that grow your personal brand." if IS_EN else "قارن محتواك مع المنافسين لتكتشف مواضيع مفقودة ترفع قوة براندك الشخصي."

LABEL_MY = "✍️ Your recent content (titles / summaries)" if IS_EN else "✍️ محتواك الأخير (عناوين / ملخصات)"
LABEL_COMP = "📌 Competitors content (titles / summaries)" if IS_EN else "📌 محتوى المنافسين (عناوين / ملخصات)"
BTN = "🎯 Analyze gaps & suggest topics" if IS_EN else "🎯 تحليل الفجوات واقتراح المواضيع"

PH_MY = (
"""Example (Personal Branding):
- My story: from CS student to AI builder
- What I learned from building 5 tools
- Mistakes I made in positioning
- How I write better hooks
- Behind-the-scenes of my workflow
"""
if IS_EN else
"""مثال (براند شخصي):
- قصتي: من طالبة CS إلى AI Builder
- ماذا تعلمت من بناء 5 أدوات
- أخطاء وقعت فيها بالتموضع
- كيف أكتب Hooks أقوى
- خلف الكواليس: كيف أشتغل يومياً
"""
)

PH_COMP = (
"""Example (Competitors):
- How to build authority on LinkedIn
- My weekly content system
- Case study: how I got 10 clients
- Personal brand messaging framework
- Content distribution checklist
"""
if IS_EN else
"""مثال (منافسين):
- كيف تبني Authority على LinkedIn
- نظام محتوى أسبوعي ثابت
- Case Study: كيف جبت 10 عملاء
- إطار واضح لرسائل البراند الشخصي
- Checklist لتوزيع المحتوى
"""
)

# =========================================================
# 11) HEADER + EXPANDER (شرح + مثال)
# =========================================================
st.title(TITLE)
st.caption(CAPTION)

with st.expander("What is this tool?" if IS_EN else "ما هي هذه الأداة؟", expanded=True):
    if IS_EN:
        st.markdown(f"""
This tool finds **missing topics** in your personal branding content.

It compares:
- Your recent content
- Competitors’ content

Then it outputs:
- A short summary of your biggest gap
- **5–7 missing topics** with:
  - Why it matters (personal brand angle)
  - Best format (**ONLY**: {ALLOWED_FORMATS_EN})

**Mini example**
If you post mostly about “tools”, and competitors post about “positioning + case studies”:
You’ll get missing topics like: “your positioning statement”, “proof & case studies”, “content distribution system”, etc.
""")
    else:
        st.markdown(f"""
هذه الأداة تكشف **المواضيع المفقودة** في محتواك لبناء البراند الشخصي.

تقارن بين:
- محتواك الحالي
- محتوى المنافسين

ثم تعطيك:
- ملخص سريع لأكبر فجوة عندك
- **5–7 مواضيع مفقودة** مع:
  - لماذا هي مهمة (من زاوية البراند الشخصي)
  - الشكل الأنسب للنشر (**فقط**: {ALLOWED_FORMATS_AR})

**مثال صغير**
إذا أنت تنشر كثير عن “الأدوات”، والمنافسون ينشرون عن “التموضع + دراسات الحالة”:
ستظهر لك مواضيع مثل: “جملة تموضعك”، “إثباتات وتجارب”، “نظام توزيع المحتوى”… إلخ.
""")

st.markdown("---")

# =========================================================
# 12) INPUTS
# =========================================================
col1, col2 = st.columns(2)
with col1:
    my_input = st.text_area(LABEL_MY, height=240, placeholder=PH_MY)
with col2:
    comp_input = st.text_area(LABEL_COMP, height=240, placeholder=PH_COMP)

# =========================================================
# 13) RUN
# =========================================================
if st.button(BTN):
    if not my_input.strip() or not comp_input.strip():
        st.warning("Please fill both fields." if IS_EN else "يرجى تعبئة الحقلين أولاً.")
    else:
        track_cta_event()
        with st.spinner("Analyzing..." if IS_EN else "جاري التحليل..."):
            summary, topics, was_cached, err = get_or_create_gap_analysis(my_input.strip(), comp_input.strip())

        if err:
            st.error(f"Model error: {err}" if IS_EN else f"خطأ من الموديل: {err}")
        elif not topics:
            st.error("No clear topics returned — try adding more details." if IS_EN else "لم تظهر مواضيع واضحة — جرّب إضافة تفاصيل أكثر.")
        else:
            st.session_state["res_sum"] = summary
            st.session_state["res_top"] = topics
            st.session_state["is_cached"] = was_cached

# =========================================================
# 14) RESULTS
# =========================================================
# =========================================================
# RESULTS
# =========================================================
if "res_sum" in st.session_state:
    st.markdown("---")

    st.subheader("📊 Summary" if IS_EN else "📊 ملخص التحليل")
    st.info(st.session_state["res_sum"] or "—")

    st.subheader("🧩 Suggested missing topics" if IS_EN else "🧩 المواضيع المقترحة")

    df = pd.DataFrame(st.session_state["res_top"])
    df.columns = [
        "Topic" if IS_EN else "الموضوع",
        "Why it matters" if IS_EN else "سبب الأهمية",
        "Best format" if IS_EN else "الشكل المقترح",
    ]
    st.table(df)


# =========================================================
# FEEDBACK UI
# =========================================================
st.divider()

st.subheader(
    "📝 Help us improve based on your feedback"
    if IS_EN
    else "📝 ساعدنا نطور الأداة بناءً على رأيك"
)

feedback_choice = st.radio(
    "How was your experience?"
    if IS_EN
    else "كيف كانت تجربتك مع هذه الأداة؟",
    (
        "This tool was useful for me",
        "This tool was not useful",
    )
    if IS_EN
    else (
        "هذه الأداة كانت مفيدة بالنسبة لي",
        "هذه الأداة لم تكن مفيدة",
    ),
    key=f"{APP_ID}_feedback_choice",
)

useful = (
    feedback_choice
    == (
        "This tool was useful for me"
        if IS_EN
        else "هذه الأداة كانت مفيدة بالنسبة لي"
    )
)

missing_reason = None
if not useful:
    missing_reason = st.text_input(
        "What was missing? (one sentence)"
        if IS_EN
        else "ما الذي كان ناقصاً؟ (جملة واحدة)",
        max_chars=200,
        key=f"{APP_ID}_missing_reason",
    )

with st.expander(
    "💬 Quick feedback (3 questions)"
    if IS_EN
    else "💬 أعطني فيدباك سريع من فضلك (3 أسئلة)",
    expanded=False,
):
    problem_text = st.text_area(
        "1) What problem were you trying to solve?"
        if IS_EN
        else "1) ما المشكلة التي كنت تحاول حلّها؟",
        max_chars=280,
        key=f"{APP_ID}_problem_text",
    )

    helpful_reason = st.text_area(
        "2) Did it help? Why yes/no?"
        if IS_EN
        else "2) هل ساعدتك الأداة؟ لماذا نعم/لا؟",
        max_chars=280,
        key=f"{APP_ID}_helpful_reason",
    )

    must_use_text = st.text_area(
        "3) What would make this a must-use tool for you?"
        if IS_EN
        else "3) ما الذي سيجعل هذه الأداة «لازم تُستخدم» بالنسبة لك؟",
        max_chars=280,
        key=f"{APP_ID}_must_use_text",
    )

    submit_feedback = st.button(
        "✅ Submit feedback" if IS_EN else "✅ إرسال الفيدباك",
        key=f"{APP_ID}_submit_feedback",
    )

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
            st.warning(
                "Write at least one line 🙏"
                if IS_EN
                else "اكتب سطر واحد على الأقل 🙏"
            )
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
                st.success(
                    "Feedback saved ✅ Thank you!"
                    if IS_EN
                    else "تم حفظ الفيدباك ✅ شكرًا لك!"
                )
            except Exception as e:
                st.error(
                    ("Feedback error: " if IS_EN else "خطأ في حفظ الفيدباك: ")
                    + str(e)
                )
# =========================================================
# 16) FOOTER (RTL always)
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









