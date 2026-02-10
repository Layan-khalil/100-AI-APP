import streamlit as st
import os
from supabase import create_client, Client
from google import genai
from google.genai import types

# =========================================================
# 0) إعداد الصفحة (RTL + Wide)
# =========================================================
st.set_page_config(
    page_title="مولِّد الخطافات (Hooks) - التطبيق 3",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# =========================================================
# 1) تحميل المفاتيح (Secrets / Env) وتهيئة العملاء
# =========================================================
def get_secret(key: str):
    """يحاول قراءة القيمة من st.secrets ثم من متغيرات البيئة."""
    if key in st.secrets:
        return st.secrets[key]
    return os.environ.get(key)


SUPABASE_URL = get_secret("SUPABASE_URL")
SUPABASE_KEY = get_secret("SUPABASE_KEY")
GOOGLE_API_KEY = get_secret("GOOGLE_API_KEY")

missing = []
if not SUPABASE_URL:
    missing.append("SUPABASE_URL")
if not SUPABASE_KEY:
    missing.append("SUPABASE_KEY")
if not GOOGLE_API_KEY:
    missing.append("GOOGLE_API_KEY")

if missing:
    st.error(
        "⚠️ القيم التالية غير موجودة في Secrets أو Environment Variables:\n\n"
        + "\n".join(f"• {m}" for m in missing)
    )
    st.stop()

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
genai_client = genai.Client(api_key=GOOGLE_API_KEY)

# هذا معرف التطبيق في analytics (CTA فقط)
APP_ID = "app3-hook-generator"

# =========================================================
# 2) CSS — RTL + Responsive + Footer + Expander بدون هوامش
# =========================================================
st.markdown(
    """
<style>
html, body, [data-testid="stAppViewContainer"], .main {
    direction: rtl !important;
    text-align: right !important;
    font-family: "Cairo", sans-serif;
}

/* الأزرار */
.stButton > button {
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
}
.stButton > button:hover {
    background-color: #c82333 !important;
    transform: scale(1.01);
}

/* العناوين */
h1, h2, h3, h4, h5, h6 {
    direction: rtl !important;
    text-align: right !important;
}

/* النصوص العامة */
p, div {
    direction: rtl !important;
    text-align: right !important;
    line-height: 1.9;
}

/* القوائم */
ol, ul {
    direction: rtl !important;
    text-align: right !important;
    list-style-position: inside !important;
    padding-right: 0 !important;
    margin-right: 0 !important;
}
ol li, ul li {
    margin: 4px 0;
    padding-right: 4px;
}

/* Expander بدون هوامش (يبدأ من أقصى اليمين) */
[data-testid="stExpander"] details {
    padding: 0 !important;
}
[data-testid="stExpander"] div[role="region"] {
    padding: 0 !important;
    margin: 0 !important;
}
[data-testid="stExpander"] div[role="region"] * {
    margin-right: 0 !important;
    padding-right: 0 !important;
}

/* الفوتر */
.footer-container {
    width: 100%;
    text-align: center;
    margin-top: 40px;
    padding-top: 16px;
    border-top: 1px solid #666;
    font-size: 13px;
    display: flex;
    justify-content: center;
    gap: 6px;
    flex-wrap: wrap;
}
.footer-container .rtl-text {
    direction: rtl;
    unicode-bidi: plaintext;
    font-weight: 600;
}
.footer-container .ltr-text {
    direction: ltr;
    unicode-bidi: plaintext;
}
</style>
""",
    unsafe_allow_html=True,
)

# =========================================================
# 3) CTA فقط (بدون Views/Unique/Returning وبدون Sessions)
# =========================================================
def track_cta_event(app_id: str):
    """زيادة عداد CTA في analytics عند الضغط على زر."""
    try:
        supabase.rpc("increment_cta", {"p_app_id": app_id}).execute()
    except Exception:
        # لا نعرض تحذير للمستخدم (حسب طلبك) — فقط نتجاهل بهدوء
        pass

# =========================================================
# 4) توليد Hooks عبر Gemini
# =========================================================
def generate_hooks(niche: str, audience: str, goal: str, tone: str, platform: str, count: int = 10) -> str:
    prompt = f"""
أنت كاتب تسويق عربي محترف متخصص في كتابة Hooks قوية.

المطلوب:
- اكتب {count} خطافات (Hooks) قصيرة وقوية لصناعة محتوى على منصة {platform}.
- المجال/النيتش: {niche}
- الجمهور المستهدف: {audience}
- الهدف من المحتوى: {goal}
- النبرة المطلوبة: {tone}

شروط مهمة جداً:
- اكتب الخطافات بالعربي فقط.
- لا تكتب أي مقدمة أو شرح.
- كل Hook يكون في سطر مستقل، ومُرقّم من 1 إلى {count}.
- تجنب الحشو، وركز على الإثارة والوضوح.
"""

    try:
        response = genai_client.models.generate_content(
            model="gemini-2.0-flash-exp",
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.7,
                top_p=0.9,
                top_k=40,
                max_output_tokens=900,
            ),
        )
        return response.text or ""
    except Exception as e:
        st.error(f"حدث خطأ أثناء التوليد: {e}")
        return ""

def parse_numbered_lines(text: str):
    lines = [l.strip() for l in (text or "").splitlines() if l.strip()]
    # نحاول نلتقط فقط السطور المرقمة
    hooks = []
    for l in lines:
        # يقبل "1)" أو "1." أو "1-"
        if l[:1].isdigit():
            hooks.append(l)
    return hooks if hooks else lines

# =========================================================
# 5) واجهة المستخدم
# =========================================================
st.title("🧠 مولِّد الخطافات التسويقية (Hooks)")

st.caption("اكتبي معلومات بسيطة… وخذي خطافات جاهزة تساعدك تبدأي المحتوى بقوة وتشدّي انتباه الجمهور من أول سطر.")

with st.expander("ℹ️ ما الذي تفعله هذه الأداة؟", expanded=True):
    st.markdown(
        """
هذه الأداة تساعدك تكتبي **Hooks** قوية (الجمل الأولى) اللي بتحدد إذا الناس رح تكمل قراءة/مشاهدة أو لا.

كيف تستخدمينها؟
- تحددي **مجالك** والجمهور اللي بتحكي معه.
- بتختاري هدف المنشور والنبرة (جدية/حماسية/ساخرة…).
- الأداة بتطلع لك خطافات جاهزة، مناسبة للنشر فورًا أو للتعديل السريع.

ليش مهمّة؟
لأنه أقوى محتوى ممكن يفشل إذا بدايته ضعيفة… والـ Hook هو اللي “يفتح الباب” للتفاعل.
"""
    )

col1, col2 = st.columns(2)

with col1:
    niche = st.text_input("📌 ما مجالك/موضوعك؟", placeholder="مثال: ذكاء اصطناعي للمستقلين / براند شخصي / تسويق...")
    audience = st.text_input("👥 مين جمهورك؟", placeholder="مثال: مستقلين عرب / أصحاب مشاريع / طلاب CS...")
    platform = st.selectbox("📱 على أي منصة؟", ["Instagram Reels", "TikTok", "LinkedIn", "YouTube Shorts", "X (Twitter)"])

with col2:
    goal = st.selectbox("🎯 هدف المحتوى", ["رفع التفاعل", "جذب عملاء", "زيادة الثقة", "تعليم/شرح", "بيع خدمة/منتج"])
    tone = st.selectbox("🗣️ النبرة", ["قوية وحاسمة", "ودودة وبسيطة", "ملهمة ومحفّزة", "ساخرة خفيفة", "احترافية جدًا"])
    count = st.number_input(
        "🔢 عدد الخطافات",
        min_value=0,
        max_value=10,
        value=5,
        step=1,
    )

    # ✅ ضعي هذا السطر هنا تمامًا
    count = int(max(0, min(10, count)))
generate_btn = st.button("⚡ توليد الخطافات")

# =========================================================
# 6) تنفيذ التوليد + عرض Markdown (فقرات مرقّمة)
# =========================================================
if generate_btn:
    if not niche.strip() or not audience.strip():
        st.warning("يرجى إدخال المجال والجمهور المستهدف أولاً.")
    else:
        # CTA فقط: كل كبسة زر +1
        track_cta_event(APP_ID)

        with st.spinner("✨ جاري توليد الخطافات..."):
            raw = generate_hooks(niche, audience, goal, tone, platform, count=count)

        hooks = parse_numbered_lines(raw)

        if not hooks:
            st.error("لم يتم توليد نتائج واضحة. جرّبي تغيير المدخلات أو إعادة المحاولة.")
        else:
            st.subheader("✅ الخطافات الجاهزة")
            # عرض داخل Markdown كفقرات مرقّمة
            for line in hooks:
                st.markdown(f"- {line}")

# =========================================================
# 7) الفوتر
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


