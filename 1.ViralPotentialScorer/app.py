import streamlit as st
import os
import json
import uuid
import hashlib
import time
import re
from datetime import datetime, timezone

from supabase import create_client, Client
from postgrest.exceptions import APIError

from google import genai
from google.genai import types
from google.api_core.exceptions import ResourceExhausted, ServiceUnavailable, DeadlineExceeded

# =========================================================
# 0) PAGE CONFIG
# =========================================================
st.set_page_config(
    page_title="مُحلّل الانتشار الفيروسي",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# =========================================================
# 1) LANGUAGE SWITCH (AR/EN)
# =========================================================
if "ui_lang" not in st.session_state:
    st.session_state["ui_lang"] = "AR"

lang_toggle = st.toggle("English", value=(st.session_state["ui_lang"] == "EN"))
st.session_state["ui_lang"] = "EN" if lang_toggle else "AR"
IS_EN = (st.session_state["ui_lang"] == "EN")

DIR = "ltr" if IS_EN else "rtl"
ALIGN = "left" if IS_EN else "right"

# =========================================================
# 2) SECRETS
# =========================================================
def get_secret(key: str):
    return st.secrets.get(key) or os.environ.get(key)

SUPABASE_URL = get_secret("SUPABASE_URL")
SUPABASE_KEY = get_secret("SUPABASE_KEY")
GOOGLE_API_KEY = get_secret("GOOGLE_API_KEY")

if not all([SUPABASE_URL, SUPABASE_KEY, GOOGLE_API_KEY]):
    st.error("⚠️ Missing secrets in Secrets / Env." if IS_EN else "⚠️ مفاتيح الربط ناقصة في Secrets أو Env.")
    st.stop()

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
genai_client = genai.Client(api_key=GOOGLE_API_KEY)

APP_ID = "viral-potential-scorer-v1"

# =========================================================
# 2.1) PICK A WORKING GEMINI MODEL (auto)
# =========================================================
MODEL_CANDIDATES = [
    "gemini-2.5-flash-001",
    "gemini-2.5-flash",
    "gemini-2.0-flash-001",
    "gemini-2.0-flash",
    "gemini-1.5-flash-001",
    "gemini-1.5-flash",
]

def get_working_model_name() -> str:
    """
    يجرّب أكثر من موديل ويختار أول موديل يشتغل على API key الحالي.
    يخزّن النتيجة في session_state لتجنب إعادة التجربة كل مرة.
    """
    if "working_model" in st.session_state and st.session_state["working_model"]:
        return st.session_state["working_model"]

    test_cfg = types.GenerateContentConfig(
        temperature=0.0,
        max_output_tokens=8,
    )

    last_err = None
    for m in MODEL_CANDIDATES:
        try:
            _ = genai_client.models.generate_content(
                model=m,
                contents="ping",
                config=test_cfg,
            )
            st.session_state["working_model"] = m
            return m
        except Exception as e:
            # جرّبي التالي لو كان NotFound / unsupported
            s = str(e)
            last_err = e
            if ("404" in s) or ("NOT_FOUND" in s) or ("is not found" in s) or ("not supported" in s):
                continue
            # أخطاء ثانية (صلاحيات/مفتاح/شبكة) خلّينا نكمل ونشوف غيره
            continue

    # إذا ولا موديل اشتغل
    st.session_state["working_model"] = MODEL_CANDIDATES[0]
    raise RuntimeError(
        "No working Gemini model found for this API key / environment. "
        f"Last error: {last_err}"
    )



# =========================================================
# 3) CSS (same style + hide Streamlit header + footer hidden)
# =========================================================
st.markdown(
    f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Cairo:wght@400;700;800&display=swap');

/* Hide Streamlit chrome */
#MainMenu {{ visibility: hidden; }}
header {{ visibility: hidden; }}
footer {{ visibility: hidden; }}
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
    font-family: 'Cairo', sans-serif !important;
}}

* {{ box-sizing: border-box; }}

h1, h2, h3, h4, h5, h6,
p, div, span, li,
[data-testid="stMarkdownContainer"] {{
    direction: {DIR} !important;
    text-align: {ALIGN} !important;
    unicode-bidi: plaintext !important;
    line-height: 1.85 !important;
    word-break: break-word !important;
}}

/* Buttons */
.stButton > button {{
    background-color: #e63946 !important;
    color: white !important;
    font-weight: 800 !important;
    border-radius: 28px !important;
    width: 100% !important;
    height: 3.2em !important;
    border: none !important;
    font-size: 17px !important;
}}
.stButton > button:hover {{
    filter: brightness(0.95);
    transform: scale(1.01);
}}

hr {{ margin: 18px 0 !important; }}

/* Result container */
.result-box {{
    border: 2px solid rgba(230,57,70,0.45);
    border-radius: 18px;
    padding: 18px;
    margin-top: 14px;
}}

.result-title {{
    font-weight: 900;
    font-size: 18px;
    margin-bottom: 14px;
}}

.result-text {{
    white-space: pre-wrap;
    word-break: break-word;
    line-height: 1.9 !important;
}}

/* ===== STEPPS SCORE DESIGN ===== */

.score-row {{
    margin-bottom: 22px;
}}

.score-header {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
    font-weight: 800;
    font-size: 15.5px;
}}

.score-header span:first-child {{
    flex: 1;
}}

.score-header span:last-child {{
    min-width: 45px;
    text-align: end;
    opacity: 0.9;
}}

.score-bar {{
    width: 100%;
    height: 9px;
    background: rgba(255,255,255,0.08);
    border-radius: 12px;
    overflow: hidden;
    margin-top: 6px;
}}

.score-fill {{
    height: 100%;
    background: #e63946;
    border-radius: 12px;
    transition: width 0.6s ease;
}}

/* Footer */
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

/* ===== Testimonials Slider ===== */

.testimonial-title,
.testimonial-wrapper,
.testimonial-card,
.testimonial-text,
.testimonial-author {{
    direction: ltr !important;
    text-align: center !important;
}}

.testimonial-title {{
  text-align:center;
  font-size:20px;
  font-weight:800;
  margin: 10px 0 12px 0;
}}

.testimonial-wrapper {{
  display:flex;
  gap:14px;
  overflow-x:auto;
  padding: 8px 8px 14px 8px;
  scroll-snap-type:x mandatory;
}}

.testimonial-card {{
  flex: 0 0 auto;
  width: 320px;
  max-width: 86vw;
  background: rgba(255,255,255,0.03);
  border: 1px solid rgba(255,255,255,0.14);
  border-left: 5px solid #e63946;
  border-radius: 14px;
  padding: 16px;
  min-height: 220px;
  display:flex;
  flex-direction:column;
  justify-content:center;
}}

.testimonial-text {{
  color: var(--text-color) !important;
  font-size: 14px;
  line-height: 1.6;
}}

.testimonial-author {{
  margin-top:12px;
  font-weight:700;
  opacity: 0.75;
  font-size: 13px;
}}
</style>
""",
    unsafe_allow_html=True,
)

# =========================================================
# 4) Analytics + Feedback RPC + Visitor
# =========================================================
def get_visitor_id() -> str:
    if "visitor_id" not in st.session_state:
        st.session_state["visitor_id"] = str(uuid.uuid4())
    return st.session_state["visitor_id"]

def track_visit():
    # اختياري: إذا ما عندك rpc track_visit احذفيه أو خليّه pass
    try:
        supabase.rpc("track_visit", {"p_app_id": APP_ID, "p_visitor_id": get_visitor_id()}).execute()
    except Exception:
        pass

def track_cta_event():
    try:
        supabase.rpc("increment_cta", {"p_app_id": APP_ID}).execute()
    except Exception:
        pass

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

track_visit()

# =========================================================
# 5) Cache helpers
# =========================================================
def make_content_hash(text: str) -> str:
    normalized = " ".join((text or "").strip().split())
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
            return res.data[0].get("analysis_text")
    except Exception:
        pass
    return None

def cache_set(app_id: str, content_hash: str, analysis_text: str):
    try:
        supabase.table("viral_scores_cache").upsert(
            {
                "app_id": app_id,
                "content_hash": content_hash,
                "analysis_text": analysis_text,
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
            on_conflict="app_id,content_hash",
        ).execute()
    except Exception:
        pass

# =========================================================
# 6) Model call (retry)
# =========================================================
def call_model_with_retry(model: str, prompt: str, cfg: types.GenerateContentConfig, retries: int = 3) -> str:
    last_err = None
    for attempt in range(retries):
        try:
            resp = genai_client.models.generate_content(model=model, contents=prompt, config=cfg)
            return resp.text or ""
        except (ResourceExhausted, ServiceUnavailable, DeadlineExceeded) as e:
            last_err = e
            time.sleep(2 * (attempt + 1))
            continue
        except Exception as e:
            last_err = e
            break
    raise last_err if last_err else RuntimeError("Unknown model error")

# =========================================================
# 7) Generate analysis (STEPPS)
# =========================================================
def generate_stepps_analysis(text: str) -> str:
    current_model = get_working_model_name()
    cfg = types.GenerateContentConfig(
        temperature=0.6,
        top_p=0.9,
        max_output_tokens=4000,
    )

    if IS_EN:
       prompt = f"""
You are a viral content expert specialized in Jonah Berger's STEPPS framework.

Analyze the following text using ONLY the six STEPPS factors:

1) Social Currency
2) Triggers
3) Emotion
4) Public
5) Practical Value
6) Stories

IMPORTANT OUTPUT RULES (must follow exactly):

- Start each section using this exact format:

[Social Currency: X/10]
Write a 3–5 line explanation here.

[Triggers: X/10]
Write a 3–5 line explanation here.

[Emotion: X/10]
Write a 3–5 line explanation here.

[Public: X/10]
Write a 3–5 line explanation here.

[Practical Value: X/10]
Write a 3–5 line explanation here.

[Stories: X/10]
Write a 3–5 line explanation here.

- After finishing all six factors, add:

[Improvements]
- Provide exactly 3 specific improvements for THIS text.

STRICT RULES:
- Do not use markdown.
- Do not use bullet symbols except under Improvements.
- Do not change the bracket format.
- Do not add any introduction or conclusion.
- Language: English.

Text:
{text}
"""
    else:
       prompt = f"""
أنت خبير محتوى فيروسي متخصص في نموذج STEPPS لجونا بيرجر.

حلّل النص التالي باستخدام عوامل STEPPS الستّة فقط:

1) العملة الاجتماعية (Social Currency)
2) المحفّزات (Triggers)
3) المشاعر (Emotion)
4) الظهور العام (Public)
5) القيمة العملية (Practical Value)
6) القصص (Stories)

مهم جداً — يجب الالتزام بالشكل التالي حرفياً:

[Social Currency: X/10]
اكتب شرحاً من 3 إلى 5 أسطر.

[Triggers: X/10]
اكتب شرحاً من 3 إلى 5 أسطر.

[Emotion: X/10]
اكتب شرحاً من 3 إلى 5 أسطر.

[Public: X/10]
اكتب شرحاً من 3 إلى 5 أسطر.

[Practical Value: X/10]
اكتب شرحاً من 3 إلى 5 أسطر.

[Stories: X/10]
اكتب شرحاً من 3 إلى 5 أسطر.

بعد الانتهاء أضف:

[Improvements]
- اكتب 3 تحسينات محددة لهذا النص فقط.

قواعد صارمة:
- لا تستخدم Markdown.
- لا تضف مقدمة أو خاتمة.
- لا تغيّر شكل الأقواس [].
- لا تضف أي نص خارج هذا التنسيق.
- اللغة: العربية.

النص:
{text}
"""
    return call_model_with_retry(current_model, prompt, cfg, retries=3).strip()
def extract_stepps_scores(analysis_text):
    pattern = r"\[(.*?)\:\s*(\d+)\/10\]"
    matches = re.findall(pattern, analysis_text)

    scores = {}
    for name, value in matches:
        scores[name.strip()] = int(value)

    return scores    
def render_score(label, score):
    percent = int(score) * 10
    st.markdown(f"""
    <div class="score-row">
        <div class="score-header">
            <span>⭐ {label}</span>
            <span>{score}/10</span>
        </div>
        <div class="score-bar">
            <div class="score-fill" style="width:{percent}%"></div>
        </div>
    </div>
    """, unsafe_allow_html=True)
# =========================================================
# 8) UI
# =========================================================
if IS_EN:
    st.title("🎯 Viral Potential Scorer")
    st.caption("Analyze your text using STEPPS to understand what helps it spread — and how to improve it.")
else:
    st.title("🎯 مُحلّل احتمالية انتشار المحتوى الفيروسي")
    st.caption("حلّل نصك بعوامل STEPPS لتفهم لماذا ينتشر المحتوى — وكيف ترفعه لمستوى أقوى.")

with st.expander("💡 What does this tool do?" if IS_EN else "💡 ما الذي تفعله هذه الأداة؟", expanded=True):
    if IS_EN:
        st.markdown("""
This tool scores your content using **Jonah Berger’s STEPPS** (the most popular viral-content framework).

It helps you:
- Understand **why** your post may (or may not) spread
- Identify the **weakest factors** holding it back
- Get **specific edits** to make the same message more shareable

**Example input**
> “How to make AI presentations in PowerPoint in 8 steps…”

**Example output**
- Strong **Practical Value** (clear steps)
- Weak **Emotion** (needs stronger hook / tension)
- Improvements: add a punchy story + sharper trigger + clearer call to share
""")
        st.markdown("### STEPPS explained")
        st.markdown("""
- **Social Currency:** Does sharing this make people look smart or “in the know”?
- **Triggers:** Does something in daily life remind people of this content?
- **Emotion:** Does it trigger strong feelings (awe, anger, excitement, anxiety, hope)?
- **Public:** Is it visible / easy to copy / easy to show?
- **Practical Value:** Does it give real useful value people want to pass on?
- **Stories:** Is the message wrapped in a story people can retell?
""")
    else:
        st.markdown("""
هذه الأداة تقيم محتواك باستخدام نموذج **STEPPS** لجونا بيرجر (أشهر إطار لفهم المحتوى الفيروسي).

تساعدك على:
- فهم **ليش** منشورك ممكن ينتشر أو لا
- كشف **أضعف عامل** يعيق الانتشار
- الحصول على **تعديلات واقعية** لتحسين نفس النص بدل كتابة شيء جديد

**مثال مدخلات**
> “كيف تعمل عروض PowerPoint بالذكاء الاصطناعي بخطوات بسيطة…”

**مثال مخرجات**
- **قيمة عملية عالية** (خطوات واضحة)
- **مشاعر ضعيفة** (بدها هوك أقوى/توتر/قصة)
- تحسينات: قصة قصيرة + Trigger واضح + CTA للنشر/الحفظ
""")
        st.markdown("### شرح عوامل STEPPS")
        st.markdown("""
- **العملة الاجتماعية:** هل مشاركة المحتوى تجعل الشخص يبدو ذكي/مميز/سبق الآخرين؟
- **المحفّزات:** هل في شيء يومي يذكّر الناس بهذا الموضوع فيرجعوا ينشروه؟
- **المشاعر:** هل يثير مشاعر قوية (دهشة/حماس/غضب/خوف/أمل)؟
- **الظهور العام:** هل سهل يظهر للناس ويتقلّد (قابل للمشاركة/التطبيق/الاستعراض)؟
- **القيمة العملية:** هل فيه فائدة حقيقية “تستاهل مشاركة”؟
- **القصص:** هل الرسالة موجودة داخل قصة سهلة إعادة سردها؟
""")

st.markdown("---")

# Testimonials
TESTIMONIALS_HTML = r"""
<div class="testimonial-title">💬 What users are saying</div>
<div class="testimonial-wrapper">

  <div class="testimonial-card">
    <div class="testimonial-text">
      The app works far better now! The plain text download is an excellent addition.
    </div>
    <div class="testimonial-author">— User feedback</div>
  </div>

  <div class="testimonial-card">
    <div class="testimonial-text">
      Great tool. It helped me create a post that attracts advice and real experiences from others.
      I recommend creators and anyone interested in content to try it.
    </div>
    <div class="testimonial-author">— Salem Khalil</div>
  </div>

  <div class="testimonial-card">
    <div class="testimonial-text">
      The tool helped me understand what actually helps a post reach more people,
      especially because it analyzes viral factors with clear explanations.
    </div>
    <div class="testimonial-author">— Sally Daibes</div>
  </div>

  <div class="testimonial-card">
    <div class="testimonial-text">
      Love the initiative.
    </div>
    <div class="testimonial-author">— Dany Kitishian</div>
  </div>

</div>
"""
st.markdown(TESTIMONIALS_HTML, unsafe_allow_html=True)

# Inputs
if IS_EN:
    post_text = st.text_area(
        "✍️ Paste your post / tweet / video script here:",
        height=220,
        placeholder="Write the full text here…",
    )
    btn_label = "Analyze now 🚀"
else:
    post_text = st.text_area(
        "✍️ أدخل نص المنشور / التغريدة / سكربت الفيديو هنا:",
        height=220,
        placeholder="اكتب النص الكامل هنا…",
    )
    btn_label = "تحليل الآن 🚀"

# Session state for result
if f"{APP_ID}_has_result" not in st.session_state:
    st.session_state[f"{APP_ID}_has_result"] = False
if f"{APP_ID}_analysis" not in st.session_state:
    st.session_state[f"{APP_ID}_analysis"] = ""

if st.button(btn_label):
    if not post_text or len(post_text.strip()) < 20:
        st.warning("Please enter a real text (20+ chars)." if IS_EN else "الرجاء إدخال نص حقيقي (20+ حرف).")
    else:
        track_cta_event()

        c_hash = make_content_hash(f"lang={st.session_state['ui_lang']}||{post_text.strip()}")
        cached = cache_get(APP_ID, c_hash)

        if cached:
            analysis = cached
        else:
            with st.spinner("⏳ Analyzing..." if IS_EN else "⏳ جاري التحليل..."):
                analysis = generate_stepps_analysis(post_text.strip())
            if analysis and not analysis.startswith("⚠️"):
                cache_set(APP_ID, c_hash, analysis)

        st.session_state[f"{APP_ID}_has_result"] = True
        st.session_state[f"{APP_ID}_analysis"] = analysis

# Result
if st.session_state.get(f"{APP_ID}_has_result"):

    raw_analysis = st.session_state.get(f"{APP_ID}_analysis", "")

    if raw_analysis and raw_analysis.strip():

        # =========================
        # CLEAN RESULT (ONE SOURCE)
        # =========================

        cleaned_analysis = raw_analysis

        # remove accidental HTML
        cleaned_analysis = re.sub(r"<[^>]+>", "", cleaned_analysis)

        # fix RTL numbering
        cleaned_analysis = re.sub(
            r"\n\s*(\d+)[\.\)]",
            lambda m: f"\n{m.group(1)}️⃣",
            cleaned_analysis
        )

        # normalize spacing
        cleaned_analysis = re.sub(
            r"\n{3,}", "\n\n", cleaned_analysis.strip()
        )

        # version for display
        formatted_analysis = (
            cleaned_analysis
            .replace("\n\n", "<br><br>")
            .replace("\n", "<br>")
        )

        # =========================
        # DISPLAY RESULT
        # =========================

        st.markdown("---")

        st.markdown(
            f"""
<div class="result-box">
    <div class="result-title">
        {"📊 Analysis Results" if IS_EN else "📊 نتائج التحليل"}
    </div>

    <div class="result-text">
        {formatted_analysis}
    </div>
</div>
""",
            unsafe_allow_html=True,
        )

        # =========================
        # COPY SECTION
        # =========================

        st.markdown("### 📋 Copy" if IS_EN else "### 📋 نسخ النص")

        st.text_area(
            "",
            value=cleaned_analysis,
            height=240,
            key=f"{APP_ID}_copy_area",
        )

# =========================================================
# 9) FEEDBACK (after result)
# =========================================================
if st.session_state.get(f"{APP_ID}_has_result"):
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
            "1) What problem were you trying to solve?" if IS_EN else "1) ما المشكلة التي كنت تحاول حلّها؟",
            max_chars=280,
            key=f"{APP_ID}_problem_text",
        )
        helpful_reason = st.text_area(
            "2) Did it help? Why yes/no?" if IS_EN else "2) هل ساعدتك الأداة؟ لماذا نعم/لا؟",
            max_chars=280,
            key=f"{APP_ID}_helpful_reason",
        )
        must_use_text = st.text_area(
            "3) What would make this a must-use tool for you?" if IS_EN else "3) ما الذي سيجعل هذه الأداة «لازم تُستخدم» بالنسبة لك؟",
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
                    st.error("Supabase error:" if IS_EN else "خطأ من Supabase:")
                    try:
                        st.json(e.args[0])
                    except Exception:
                        st.write(str(e))
                except Exception as e:
                    st.exception(e)

# =========================================================
# 10) FOOTER (your classic style)
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





