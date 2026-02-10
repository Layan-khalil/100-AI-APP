
import streamlit as st
import uuid
import hashlib
import os
import pandas as pd

from supabase import create_client, Client
from google import genai
from google.genai import types

# =========================================================
# 0) إعداد الصفحة (RTL + Wide)
# =========================================================
st.set_page_config(
    page_title=" منشئ المحتوى المفقود",
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

APP_ID = "missing-topic-generator"

# =========================================================
# 2) CSS — RTL + Responsive + Button + Footer + جدول
# =========================================================
st.markdown(
    """
<style>
html, body, [data-testid="stAppViewContainer"], .main {
    direction: rtl !important;
    text-align: right !important;
    font-family: "Cairo", sans-serif;
}

/* حاوية عامة لو احتجناها */
.app-container {
    max-width: 1000px;
    margin: 0 auto;
    padding: 0 14px;
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

/* الجدول RTL */
[data-testid="stDataFrame"] table {
    direction: rtl !important;
    text-align: right !important;
}
[data-testid="stDataFrame"] table thead tr th {
    text-align: right !important;
}
[data-testid="stDataFrame"] table tbody tr td {
    text-align: right !important;
}

/* الموبايل */
@media (max-width: 600px) {
    .app-container {
        padding: 0 10px;
    }
    li {
        line-height: 2.1;
    }
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
# 3) دوال التتبع (نفس نمط التطبيق الأول)
# =========================================================
def get_session_visitor_id() -> str:
    """توليد/استرجاع معرف الزائر داخل جلسة Streamlit."""
    if "visitor_id" not in st.session_state:
        st.session_state["visitor_id"] = str(uuid.uuid4())
    return st.session_state["visitor_id"]


def track_visit():
    """تسجيل زيارة في Supabase (analytics + visitor_logs)."""
    visitor_id = get_session_visitor_id()
    try:
        supabase.rpc(
            "track_visit",
            {"p_app_id": APP_ID, "p_visitor_id": visitor_id},
        ).execute()
    except Exception as e:
        print(f"[track_visit] Error: {e}")


def track_cta_event():
    """زيادة عداد CTA في analytics عند الضغط على زر التحليل."""
    try:
        supabase.rpc("increment_cta", {"p_app_id": APP_ID}).execute()
    except Exception as e:
        print(f"[increment_cta] Error: {e}")


track_visit()  # تشغيل التتبع بمجرد فتح التطبيق

# =========================================================
# 4) كاش + دوال مساعدة لتنسيق الرد
# =========================================================
def get_content_hash(text: str) -> str:
    """هاش ثابت يجمع منشوراتك + منشورات المنافسين."""
    normalized = " ".join(text.strip().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def parse_gap_response(raw: str):
    """
    نتوقّع فورمات على الشكل:

    SUMMARY: نص الملخص...

    TOPICS:
    1. عنوان || السبب || الشكل
    2. ...
    """
    if not raw:
        return "", []

    lines = [l.strip() for l in raw.splitlines() if l.strip()]
    summary = ""
    topics = []

    in_topics = False
    for line in lines:
        # سطر الملخص
        if line.upper().startswith("SUMMARY:") or line.startswith("ملخص:"):
            summary = line.split(":", 1)[1].strip()
            continue

        # بداية قائمة المواضيع
        if line.upper().startswith("TOPICS"):
            in_topics = True
            continue

        if not in_topics:
            continue

        # نتوقع: "1. العنوان || السبب || الشكل"
        if line[0].isdigit() and "." in line:
            try:
                after_dot = line.split(".", 1)[1].strip()
                parts = [p.strip(" |") for p in after_dot.split("||")]
                if len(parts) >= 3:
                    topics.append(
                        {
                            "topic_title": parts[0],
                            "gap_reason": parts[1],
                            "format_suggestion": parts[2],
                        }
                    )
            except Exception:
                continue

    return summary, topics


def get_or_create_gap_analysis(my_posts: str, competitor_posts: str):
    """
    - يحاول قراءة النتيجة من جدول viral_scores_cache
    - إذا لم يجدها → يستدعي Gemini ويحفظ النتيجة في الكاش
    - يرجع (summary, topics_list)
    """
    combined = my_posts.strip() + "\n\n---\n\n" + competitor_posts.strip()
    content_hash = get_content_hash(combined)

    # 1) قراءة الكاش
    try:
        res = (
            supabase.table("viral_scores_cache")
            .select("analysis_text")
            .eq("app_id", APP_ID)
            .eq("content_hash", content_hash)
            .limit(1)
            .execute()
        )
        if res.data and len(res.data) > 0:
            raw = res.data[0]["analysis_text"]
            summary, topics = parse_gap_response(raw)
            if topics:
                return summary, topics
    except Exception as e:
        print(f"[cache read] Error: {e}")

    # 2) لا يوجد كاش → استدعاء Gemini
    raw = analyze_content_gaps(my_posts, competitor_posts)
    if not raw:
        return "", []

    summary, topics = parse_gap_response(raw)

    # 3) حفظ في الكاش (النص الخام)
    try:
        supabase.table("viral_scores_cache").insert(
            {
                "app_id": APP_ID,
                "content_hash": content_hash,
                "analysis_text": raw,
            }
        ).execute()
    except Exception as e:
        print(f"[cache write] Error: {e}")

    return summary, topics


# =========================================================
# 5) استدعاء Gemini بفورمات نصي بسيط (بدون JSON)
# =========================================================
def analyze_content_gaps(my_posts, competitor_posts) -> str:
    """
    يطلب من Gemini تحليل الفجوات ويعيد نصًا منسقًا (SUMMARY + TOPICS).
    """

    prompt = f"""
أنت خبير استراتيجي في المحتوى التسويقي متخصص في تحليل فجوات المحتوى (Content Gaps).

مهمتك:
- مقارنة قائمة منشورات "العميل" مع قائمة منشورات "المنافسين".
- استخراج 5 إلى 7 مواضيع مهمة للجمهور لم يتم تغطيتها جيداً أو تم تجاهلها.
- التركيز على المواضيع التي تناسب صانع محتوى/مستقل/ريادي في مجال الأعمال الرقمية والذكاء الاصطناعي.

قائمة منشورات العميل:
{my_posts}

قائمة منشورات المنافسين:
{competitor_posts}

أعد النتيجة بالصيغة التالية تماماً، بدون أي شروح إضافية أو Markdown أو كود:

SUMMARY: اكتب هنا ملخصاً تحليلياً من سطرين كحد أقصى يوضح الفرق بين نمط محتوى العميل والمنافسين، وما نوع المواضيع التي تنقص استراتيجية العميل حالياً.

TOPICS:
1. عنوان موضوع مفقود مقترح || شرح مختصر لماذا يعتبر هذا الموضوع فجوة مهمة للجمهور (مع ربطه بما ينشره العميل وما يهمله المنافسون) || اقتراح الشكل الأنسب للمحتوى (مثل: ريلز قصير، كروسيل، لايف، ثريد...)
2. عنوان موضوع ثانٍ || ... || ...
3. ...
4. ...
5. ...
6. (إن لزم)
7. (إن لزم)

احرص على:
- أن يكون عدد البنود في قائمة TOPICS بين 5 و 7.
- أن تكون اللغة عربية واضحة ومقنعة ومباشرة.
- عدم إضافة أي نص قبل كلمة SUMMARY أو بعد آخر سطر من المواضيع.
"""

    try:
        response = genai_client.models.generate_content(
            model="gemini-2.0-flash-exp",
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.3,
                top_p=0.8,
                top_k=32,
                max_output_tokens=1200,
            ),
        )
    except Exception as e:
        st.error(f"حدث خطأ أثناء الاتصال بمحرك التحليل: {e}")
        return ""

    return response.text or ""


# =========================================================
# 6) واجهة المستخدم
# =========================================================
st.title("🧩 منشئ المحتوى المفقود")
st.caption("حلّل منشوراتك ومنشورات منافسيك لاكتشاف المواضيع التي يتوقعها جمهورك ولم تُغطَّ بعد.")

with st.expander("ℹ️ ما الذي تفعله هذه الأداة؟", expanded=True):
    st.markdown(
        """
هذه الأداة تساعدك على تحليل فجوات المحتوى (**Content Gaps**) بين:

- ما تنشره أنت حالياً (بوستات، ريلز، فيديوهات، مقالات…)
- وما ينشره منافسوك في نفس السوق أو النيتش.

النتيجة النهائية هي:
- 🧠 مواضيع مهمّة لم تتناولها بعد، لكنها منطقية جداً لشخص مثلك.
- 🎯 أسباب تجعل هذه المواضيع جذابة ومطلوبة من جمهورك.
- 🎬 اقتراحات واضحة لأفضل صيغة نشر لكل موضوع (ريلز، كروسيل، لايف، ثريد…).

الهدف: أن تخرجي من الأداة بقائمة جاهزة من أفكار محتوى **استراتيجية** بدلاً من نشر عشوائي.
"""
    )

col1, col2 = st.columns(2)

with col1:
    my_posts_input = st.text_area(
        "✍️ منشوراتك / محتوياتك الأخيرة (العناوين أو الملخصات):",
        height=260,
        placeholder="مثال:\n"
        "1. رحلتي مع بناء 100 تطبيق ذكاء اصطناعي\n"
        "2. كيف أتعلم البرمجة من الصفر\n"
        "3. عادات يومية رفعت إنتاجيتي في العمل الحر\n"
        "4. أخطائي الأولى مع العملاء وكيف تفاديتها...\n",
    )

with col2:
    competitor_posts_input = st.text_area(
        "📌 منشورات المنافسين الأخيرة (العناوين أو الملخصات):",
        height=260,
        placeholder="مثال:\n"
        "1. كيف تحصل على أول عميل على Upwork\n"
        "2. أفضل أدوات الذكاء الاصطناعي لصنّاع المحتوى\n"
        "3. خطوات بناء براند شخصي قوي على LinkedIn\n"
        "4. استراتيجيات تسويق بالمحتوى لرواد الأعمال...\n",
    )

analyze_button = st.button("🎯 تحليل الفجوات واقتراح المواضيع")

# =========================================================
# 7) تنفيذ التحليل وعرض النتائج
# =========================================================
if analyze_button:
    if not my_posts_input.strip() or not competitor_posts_input.strip():
        st.warning("يرجى إدخال منشوراتك ومنشورات منافسيك أولاً.")
    elif len(my_posts_input.strip()) < 50 or len(competitor_posts_input.strip()) < 50:
        st.warning("للحصول على تحليل دقيق، يُفضّل إدخال وصف أو عناوين كافية (50 حرفاً على الأقل لكل جانب).")
    else:
        # تسجيل ضغطة الزر في analytics
        track_cta_event()

        with st.spinner("🔎 جاري تحليل الفجوات واستخراج المواضيع الاستراتيجية..."):
            summary, topics = get_or_create_gap_analysis(
                my_posts_input, competitor_posts_input
            )

        if not topics:
            st.error("حدثت مشكلة في الحصول على نتيجة التحليل. جرّبي تعديل المدخلات أو إعادة المحاولة لاحقاً.")
        else:
            st.subheader("📌 ملخّص النمط العام للمحتوى")
            if summary:
                st.markdown(summary)
            else:
                st.markdown("لم يتم توليد ملخص واضح من النموذج.")

            st.markdown("---")
            st.subheader("🧩 قائمة المواضيع المفقودة (Missing Topics)")

            df = pd.DataFrame(topics)
            df.columns = ["الموضوع المقترح", "سبب الأهمية والفجوة", "اقتراح شكل المحتوى"]
            st.dataframe(df, use_container_width=True)

# =========================================================
# 8) الفوتر
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
