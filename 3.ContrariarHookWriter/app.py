import streamlit as st
import os
import time
import hashlib
import re

from supabase import create_client, Client
from google import genai
from google.genai import types

# أخطاء شائعة من Google SDK (مش ضروري تكون كلها موجودة بكل البيئات، لذلك بنعمل try)
try:
    from google.api_core.exceptions import ResourceExhausted, ServiceUnavailable, DeadlineExceeded, NotFound
except Exception:
    ResourceExhausted = ServiceUnavailable = DeadlineExceeded = NotFound = Exception

# =========================================================
# 0) إعداد الصفحة (RTL + Wide)
# =========================================================
st.set_page_config(
    page_title="مولِّد الخطافات",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# =========================================================
# ✅ UI Language Switch (للواجهة فقط)
# =========================================================
if "ui_lang" not in st.session_state:
    st.session_state["ui_lang"] = "AR"

lang_choice = st.toggle("English", value=(st.session_state["ui_lang"] == "EN"))
st.session_state["ui_lang"] = "EN" if lang_choice else "AR"
IS_EN = (st.session_state["ui_lang"] == "EN")

# =========================================================
# 1) تهيئة العملاء
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
    st.error(("⚠️ Missing secrets:\n\n" if IS_EN else "⚠️ القيم ناقصة:\n\n") + "\n".join(f"• {m}" for m in missing))
    st.stop()

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
genai_client = genai.Client(api_key=GOOGLE_API_KEY)

# هذا معرف التطبيق (CTA + cache + feedback)
APP_ID = "2-contrarian-hook-writer"

# =========================================================
# 2) CSS (اتجاه حسب الواجهة)
# =========================================================
DIR = "ltr" if IS_EN else "rtl"
ALIGN = "left" if IS_EN else "right"

st.markdown(f"""
<style>

/* Hide Streamlit chrome (header/top bar/footer badges) */
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
    font-family: "Cairo", sans-serif;
}}

/* الأزرار */
.stButton > button {{
    background-color: #e63946 !important;
    color: #ffffff !important;
    font-weight: 800;
    border-radius: 28px;
    border: none;
    padding: 10px 20px;
    height: 3em;
    width: 100%;
    font-size: 17px;
    transition: 0.2s ease-in-out;
}}
.stButton > button:hover {{
    background-color: #c82333 !important;
    transform: scale(1.01);
}}

/* العناوين */
h1, h2, h3, h4, h5, h6 {{
    direction: {DIR} !important;
    text-align: {ALIGN} !important;
}}

/* النصوص العامة */
p, div {{
    direction: {DIR} !important;
    text-align: {ALIGN} !important;
    line-height: 1.9;
}}

/* القوائم */
ol, ul {{
    direction: {DIR} !important;
    text-align: {ALIGN} !important;
    list-style-position: inside !important;
    padding-right: 0 !important;
    margin-right: 0 !important;
}}
ol li, ul li {{
    margin: 4px 0;
    padding-right: 4px;
}}

/* Expander بدون هوامش */
[data-testid="stExpander"] details {{
    padding: 0 !important;
}}
[data-testid="stExpander"] div[role="region"] {{
    padding: 0 !important;
    margin: 0 !important;
}}
[data-testid="stExpander"] div[role="region"] * {{
    margin-right: 0 !important;
    padding-right: 0 !important;
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
""", unsafe_allow_html=True)

# =========================================================
# 3) Helpers: CTA + Feedback
# =========================================================
def track_cta_event(app_id: str):
    try:
        supabase.rpc("increment_cta", {"p_app_id": app_id}).execute()
    except Exception:
        pass

def save_feedback_via_rpc(app_name, useful, missing_reason, problem_text, helpful_reason, must_use_text):
    return supabase.rpc("submit_app_feedback", {
        "p_app_name": app_name,
        "p_useful": useful,
        "p_missing_reason": missing_reason,
        "p_problem_text": problem_text,
        "p_helpful_reason": helpful_reason,
        "p_must_use_text": must_use_text,
    }).execute()

# =========================================================
# 4) لغة الإخراج حسب المدخلات (مش حسب UI)
# =========================================================
def detect_output_is_english(text: str) -> bool:
    ar = len(re.findall(r"[\u0600-\u06FF]", text or ""))
    la = len(re.findall(r"[A-Za-z]", text or ""))
    return la > ar  # إذا الإنجليزي أكثر => output EN

# =========================================================
# 5) Cache helpers (viral_scores_cache)
# =========================================================
def get_content_hash(text: str) -> str:
    normalized = " ".join((text or "").strip().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

def read_cached_output(content_hash: str) -> str | None:
    try:
        res = (
            supabase.table("viral_scores_cache")
            .select("analysis_text")
            .eq("app_id", APP_ID)
            .eq("content_hash", content_hash)
            .limit(1)
            .execute()
        )
        return res.data[0].get("analysis_text") if res.data else None
    except Exception:
        return None

def write_cached_output(content_hash: str, raw: str):
    try:
        supabase.table("viral_scores_cache").insert({
            "app_id": APP_ID,
            "content_hash": content_hash,
            "analysis_text": raw,
        }).execute()
    except Exception:
        pass

# =========================================================
# 6) ✅ إصلاح خطأ الموديلات: موديلات + اختبار + عدم كسر التطبيق
# =========================================================
MODEL_CANDIDATES = [
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-1.5-flash",
]

def pick_working_model(test_prompt: str = "ping") -> str:
    cached = st.session_state.get("WORKING_GEMINI_MODEL")
    if cached:
        return cached

    last_err = None
    for m in MODEL_CANDIDATES:
        try:
            _ = genai_client.models.generate_content(
                model=m,
                contents=test_prompt,
                config=types.GenerateContentConfig(
                    temperature=0.1,
                    top_p=0.8,
                    top_k=32,
                    max_output_tokens=16,
                ),
            )
            st.session_state["WORKING_GEMINI_MODEL"] = m
            return m
        except Exception as e:
            last_err = e
            continue

    # ✅ بدل RuntimeError redacted: رسالة واضحة للمستخدم + stop
    st.error(
        ("⚠️ No supported Gemini model is available for this deployment. "
         "Check your Google API key / enabled models, then redeploy.\n\n"
         f"Last error: {repr(last_err)}")
        if IS_EN else
        ("⚠️ لا يوجد موديل Gemini متاح لهذا النشر حاليًا. "
         "تأكد من GOOGLE_API_KEY وأن الموديلات مفعلة بحسابك.\n\n"
         f"آخر خطأ: {repr(last_err)}")
    )
    st.stop()
    return MODEL_CANDIDATES[0]  # لن يصل هنا

def call_model(prompt: str) -> str:
    # retries + fallback بين الموديلات (حتى لو cached غلط)
    last_err = None
    for attempt in range(3):
        for m in MODEL_CANDIDATES:
            try:
                response = genai_client.models.generate_content(
                    model=m,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        temperature=0.7,
                        top_p=0.9,
                        top_k=40,
                        max_output_tokens=1500,  # عالي لتجنب القطع
                    ),
                )
                st.session_state["WORKING_GEMINI_MODEL"] = m
                return response.text or ""
            except (NotFound,) as e:
                last_err = e
                continue
            except (ResourceExhausted, ServiceUnavailable, DeadlineExceeded) as e:
                last_err = e
                time.sleep(1.5 * (2 ** attempt))
                continue
            except Exception as e:
                last_err = e
                continue

    st.error(("⚠️ AI service error. Try again later.\n" if IS_EN else "⚠️ خطأ من خدمة الذكاء الاصطناعي. جرّب مرة ثانية لاحقًا.\n") + str(last_err))
    return ""

# =========================================================
# 7) Parsing: فقط أرقام 1. 2. ... بدون bullets
# =========================================================
def parse_numbered_lines(text: str) -> list[str]:
    lines = [l.strip() for l in (text or "").splitlines() if l.strip()]
    hooks = []
    for l in lines:
        # يقبل فقط: 1. نص
        if re.match(r"^\d+\.\s+.+", l):
            hooks.append(l)
    return hooks

def strip_number_prefix(line: str) -> str:
    return re.sub(r"^\d+\.\s*", "", line.strip()).strip()

# =========================================================
# 8) Prompt builder + ضمان العدد EXACT
# =========================================================
def build_prompt(out_is_en: bool, niche, audience, goal, tone, platform, count) -> str:
    if out_is_en:
        return f"""
You are a professional marketing copywriter.

Write EXACTLY {count} hooks for {platform}.
Niche: {niche}
Audience: {audience}
Goal: {goal}
Tone: {tone}

Mandatory rules:
- Output language: English ONLY.
- EXACTLY {count} lines.
- Each line MUST start with a number only like: 1. 2. 3. ...
- NO bullets, NO dashes, NO extra symbols.
- Each hook must be a complete understandable sentence (not one word).
- No intro, no explanation, no extra text.

Return ONLY the numbered hooks.
"""
    else:
        return f"""
أنت كاتب تسويق عربي محترف.

اكتب {count} خطافات بالضبط لمنصة {platform}.
المجال: {niche}
الجمهور: {audience}
الهدف: {goal}
النبرة: {tone}

شروط إلزامية:
- لغة الإخراج عربية 100% (ممنوع أي حروف لاتينية).
- اكتب {count} خطافات بالضبط.
- كل خطاف في سطر مستقل.
- كل سطر يجب أن يبدأ برقم فقط بهذا الشكل: 1. 2. 3. ...
- ممنوع استخدام نقاط • أو شرطات - أو أي رموز أخرى.
- كل خطاف جملة كاملة مفهومة، وليس كلمة واحدة.
- بدون أي مقدمة أو شرح.

أعد فقط الأسطر المرقمة.
"""

def ensure_exact_count(out_is_en: bool, raw: str, count: int, niche: str, audience: str, goal: str, tone: str, platform: str) -> tuple[str, list[str]]:
    hooks_lines = parse_numbered_lines(raw)
    # حولها لنصوص بدون ترقيم داخلي
    hooks = [strip_number_prefix(h) for h in hooks_lines]

    # إصلاح إذا ناقص/شاكلته
    if len(hooks) != count:
        repair_prompt = build_prompt(out_is_en, niche, audience, goal, tone, platform, count) + f"""

Previous output (do not repeat it, just fix):
{raw}
"""
        raw2 = call_model(repair_prompt)
        hooks_lines = parse_numbered_lines(raw2)
        hooks = [strip_number_prefix(h) for h in hooks_lines]

        # إذا لسا ناقص: اطلب فقط المتبقي
        if len(hooks) < count:
            missing_n = count - len(hooks)
            if out_is_en:
                add_prompt = f"""
Generate ONLY the remaining {missing_n} hooks in English.
Rules:
- Provide EXACTLY {missing_n} lines
- Continue numbering from {len(hooks)+1}. to {count}.
- No extra text.
Context:
Niche: {niche}
Audience: {audience}
Goal: {goal}
Tone: {tone}
Platform: {platform}
"""
            else:
                add_prompt = f"""
ولّد فقط {missing_n} خطافات إضافية (المتبقية) بالعربية.
شروط:
- بالضبط {missing_n} سطر
- أكمل الترقيم من {len(hooks)+1}. إلى {count}.
- بدون أي نص إضافي
السياق:
المجال: {niche}
الجمهور: {audience}
الهدف: {goal}
النبرة: {tone}
المنصة: {platform}
"""
            extra_raw = call_model(add_prompt)
            extra_lines = parse_numbered_lines(extra_raw)
            extra_hooks = [strip_number_prefix(h) for h in extra_lines]
            hooks.extend(extra_hooks)

    # قص/تثبيت
    hooks = [h.strip() for h in hooks if h.strip()]
    hooks = hooks[:count]

    # إذا فشل بشكل نادر: حشو آمن
    while len(hooks) < count:
        hooks.append("Write a hook that matches your niche and goal clearly." if out_is_en else "اكتب خطافًا واضحًا مرتبطًا بمجالك وهدفك بشكل مباشر.")

    final_raw = "\n".join([f"{i+1}. {hooks[i]}" for i in range(count)]).strip()
    return final_raw, hooks

# =========================================================
# 9) Main generate_hooks مع Cache
# =========================================================
def generate_hooks(niche: str, audience: str, goal: str, tone: str, platform: str, count: int) -> tuple[bool, str, list[str]]:
    combined_inputs = f"{niche}\n{audience}\n{goal}\n{tone}\n{platform}"
    out_is_en = detect_output_is_english(combined_inputs)

    prompt = build_prompt(out_is_en, niche, audience, goal, tone, platform, count)

    cache_key_text = f"v3||out_en={out_is_en}||count={count}||platform={platform}||niche={niche}||audience={audience}||goal={goal}||tone={tone}"
    content_hash = get_content_hash(cache_key_text)

    cached = read_cached_output(content_hash)
    if cached:
        cached_lines = parse_numbered_lines(cached)
        cached_hooks = [strip_number_prefix(h) for h in cached_lines][:count]
        cached_hooks = [h for h in cached_hooks if h]
        # ضمان العدد حتى لو الكاش قديم
        while len(cached_hooks) < count:
            cached_hooks.append("Write a hook that matches your niche and goal clearly." if out_is_en else "اكتب خطافًا واضحًا مرتبطًا بمجالك وهدفك بشكل مباشر.")
        return out_is_en, cached, cached_hooks[:count]

    raw = call_model(prompt)
    if not raw:
        return out_is_en, "", []

    final_raw, hooks = ensure_exact_count(out_is_en, raw, count, niche, audience, goal, tone, platform)

    # خزّن الناتج النهائي
    write_cached_output(content_hash, final_raw)
    return out_is_en, final_raw, hooks

# =========================================================
# 10) UI
# =========================================================
st.title("🧠 Hook Generator" if IS_EN else "🧠 مولِّد الخطافات التسويقية (Hooks)")
st.caption(
    "Enter a few details and get scroll-stopping hooks." if IS_EN
    else
    "أدخل تفاصيل بسيطة… وخذ خطافات جاهزة تساعدك تبدأ المحتوى بقوة وتشد انتباه الجمهور من أول سطر."
)

with st.expander("ℹ️ What does this tool do?" if IS_EN else "ℹ️ ما الذي تفعله هذه الأداة؟", expanded=True):
    st.markdown(
        """
This tool helps you write powerful hooks (opening lines) that decide whether people keep scrolling or stop.
- Define your niche and audience
- Choose a goal and tone
- Get ready-to-use hooks
"""
        if IS_EN else
        """
هذه الأداة تساعدك تكتب **خطافات** قوية (الجمل الأولى) التي تحدد إذا كان الناس سيكملون القراءة/المشاهدة أم لا.
- حدّد مجالك والجمهور
- اختر الهدف والنبرة
- خذ خطافات جاهزة للنشر
"""
    )

col1, col2 = st.columns(2)

with col1:
    niche = st.text_input("📌 Your niche/topic?" if IS_EN else "📌 ما مجالك/موضوعك؟", placeholder="Example: AI for freelancers..." if IS_EN else "مثال: ذكاء اصطناعي للمستقلين...")
    audience = st.text_input("👥 Who is your audience?" if IS_EN else "👥 مين جمهورك؟", placeholder="Example: founders, creators..." if IS_EN else "مثال: صناع محتوى، أصحاب مشاريع...")
    platform = st.selectbox("📱 Platform" if IS_EN else "📱 على أي منصة؟", ["Instagram Reels", "TikTok", "LinkedIn", "YouTube Shorts", "X (Twitter)"])

with col2:
    goal = st.selectbox(
        "🎯 Goal" if IS_EN else "🎯 هدف المحتوى",
        ["Increase engagement", "Get clients", "Build trust", "Teach/Explain", "Sell a service/product"] if IS_EN
        else
        ["رفع التفاعل", "جذب عملاء", "زيادة الثقة", "تعليم/شرح", "بيع خدمة/منتج"]
    )
    tone = st.selectbox(
        "🗣️ Tone" if IS_EN else "🗣️ النبرة",
        ["Bold & decisive", "Friendly & simple", "Inspiring & motivating", "Lightly sarcastic", "Very professional"] if IS_EN
        else
        ["قوية وحاسمة", "ودودة وبسيطة", "ملهمة ومحفّزة", "ساخرة خفيفة", "احترافية جدًا"]
    )
    count = st.number_input("🔢 Number of hooks" if IS_EN else "🔢 عدد الخطافات", min_value=1, max_value=10, value=5, step=1)

generate_btn = st.button("⚡ Generate hooks" if IS_EN else "⚡ توليد الخطافات")

# =========================================================
# 11) تنفيذ التوليد + تثبيت النتائج
# =========================================================
if generate_btn:
    if not niche.strip() or not audience.strip():
        st.warning("Please enter niche and audience first." if IS_EN else "يرجى إدخال المجال والجمهور المستهدف أولاً.")
    else:
        track_cta_event(APP_ID)
        with st.spinner("✨ Generating..." if IS_EN else "✨ جاري التوليد..."):
            out_is_en, final_raw, hooks = generate_hooks(niche, audience, goal, tone, platform, int(count))
            st.session_state[f"{APP_ID}_has_result"] = True
            st.session_state[f"{APP_ID}_hooks"] = hooks
            st.session_state[f"{APP_ID}_out_is_en"] = out_is_en

# =========================================================
# 12) عرض النتائج + Feedback
# =========================================================
if st.session_state.get(f"{APP_ID}_has_result"):
    hooks = st.session_state.get(f"{APP_ID}_hooks", [])
    if hooks:
        st.subheader("✅ Ready hooks" if IS_EN else "✅ الخطافات الجاهزة")
        for i, h in enumerate(hooks, start=1):
            st.markdown(f"{i}. {h}")

        st.divider()
        st.subheader("📝 Help us improve based on your feedback" if IS_EN else "📝 ساعدنا نطور الأداة بناءا على رأيك ")

        feedback_choice = st.radio(
            "How was your experience?" if IS_EN else "كيف كانت تجربتك مع هذه الأداة؟",
            ("This tool was useful for me", "This tool was not useful") if IS_EN
            else ("هذه الأداة كانت مفيدة بالنسبة لي", "هذه الأداة لم تكن مفيدة"),
            key=f"{APP_ID}_feedback_choice"
        )

        useful = (feedback_choice == ("This tool was useful for me" if IS_EN else "هذه الأداة كانت مفيدة بالنسبة لي"))

        missing_reason = None
        if not useful:
            missing_reason = st.text_input(
                "What was missing? (one sentence)" if IS_EN else "ما الذي كان ناقصاً؟ (جملة واحدة)",
                max_chars=200,
                key=f"{APP_ID}_missing_reason"
            )

        with st.expander("💬 Quick feedback (3 questions)" if IS_EN else "💬 أعطني فيدباك سريع من فضلك (3 أسئلة)", expanded=False):
            problem_text = st.text_area(
                "1) What problem were you trying to solve?" if IS_EN else "1) ما المشكلة التي كنت تحاول حلّها؟",
                max_chars=280,
                key=f"{APP_ID}_problem_text"
            )
            helpful_reason = st.text_area(
                "2) Did it help? Why yes/no?" if IS_EN else "2) هل ساعدتك الأداة؟ لماذا نعم/لا؟",
                max_chars=280,
                key=f"{APP_ID}_helpful_reason"
            )
            must_use_text = st.text_area(
                "3) What would make this a must-use tool for you?" if IS_EN else "3) ما الذي سيجعل هذه الأداة «لازم تُستخدم» بالنسبة لك؟",
                max_chars=280,
                key=f"{APP_ID}_must_use_text"
            )

            submit_feedback = st.button("✅ Submit feedback" if IS_EN else "✅ إرسال الفيدباك", key=f"{APP_ID}_submit_feedback")

            if submit_feedback:
                has_any_text = any([
                    (missing_reason or "").strip(),
                    (problem_text or "").strip(),
                    (helpful_reason or "").strip(),
                    (must_use_text or "").strip()
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
# 13) Footer
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

