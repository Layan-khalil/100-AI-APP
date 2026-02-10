
import streamlit as st
import uuid
import hashlib
from supabase import create_client, Client
from google import genai
from google.genai import types

# ==============================
# 0) إعدادات الصفحة أولاً
# ==============================
st.set_page_config(
    page_title="Viral Scorer | مُحلّل الانتشار",
    layout="centered"
)

# ==============================
# 1) تحميل الـ Secrets والاتصال
# ==============================
try:
    SUPABASE_URL = st.secrets["SUPABASE_URL"]
    SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
    GOOGLE_API_KEY = st.secrets["GOOGLE_API_KEY"]
except Exception:
    st.error("⚠️ فشل في تحميل المفاتيح السرّية (Secrets). تأكدي من ضبطها في Streamlit Cloud.")
    st.stop()

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
genai_client = genai.Client(api_key=GOOGLE_API_KEY)

APP_ID = "viral-potential-scorer-v1"
# =========================
#  CSS & Responsive Styling
# =========================
st.markdown("""
<style>

html, body, [data-testid="stAppViewContainer"], .main {
    direction: rtl !important;
    text-align: right !important;
    font-family: "Cairo", sans-serif;
}

/************  محتوى الصفحة الرئيسي  ************/

.app-container {
    max-width: 900px;
    margin: 0 auto;
    padding: 0 14px;
}
.stButton > button {
    background-color: #e63946 !important;
    color: #ffffff !important;
    font-weight: 800;
    border-radius: 28px;
    border: none;
    padding: 12px 18px;
    height: 3.2em;
    width: 100%;
    font-size: 17px;
    transition: 0.2s ease-in-out;
}

.stButton > button:hover {
    background-color: #c82333 !important;
    transform: scale(1.01);
}


/************  العناوين  ************/

h1,h2,h3,h4,h5,h6 {
    direction: rtl !important;
    text-align: right !important;
    margin-right: 0;
}

/************  الفقرات والنصوص  ************/

p, div {
    direction: rtl !important;
    text-align: right !important;
    word-break: break-word;
    line-height: 1.9;
}

/************  القوائم — لضمان ظهور الأرقام  ************/

ol, ul {
    direction: rtl !important;
    text-align: right !important;
    list-style-position: inside !important; /* يمنع قصّ الأرقام */
    padding-right: 0 !important;
    margin-right: 0 !important;
}

ol li, ul li {
    margin: 8px 0;
    padding-right: 6px;
}

/************  تحسين القراءة على الموبايل  ************/

@media (max-width: 600px) {

    .app-container {
        padding: 0 10px;
    }

    ol, ul {
        list-style-position: inside !important; /* ضروري لعدم قص الأرقام */
    }

    li {
        line-height: 2.1;
    }
}

/************  الفوتر  ************/
.footer-container {
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
""", unsafe_allow_html=True)
# ==============================
# 3) دوال التتبع مع Supabase
# ==============================

def get_session_visitor_id() -> str:
    """توليد/استرجاع معرف الزائر داخل جلسة Streamlit."""
    if "visitor_id" not in st.session_state:
        st.session_state["visitor_id"] = str(uuid.uuid4())
    return st.session_state["visitor_id"]


def track_visit():
    """استدعاء دالة track_visit في Supabase لتسجيل الزيارة."""
    visitor_id = get_session_visitor_id()
    try:
        supabase.rpc(
            "track_visit",
            {"p_app_id": APP_ID, "p_visitor_id": visitor_id},
        ).execute()
    except Exception as e:
        # لا نكسر التطبيق إذا حدث خطأ
        print(f"[track_visit] Error: {e}")


def track_cta_event():
    """استدعاء دالة increment_cta في Supabase عند الضغط على زر التحليل."""
    try:
        supabase.rpc("increment_cta", {"p_app_id": APP_ID}).execute()
    except Exception as e:
        print(f"[increment_cta] Error: {e}")


# تشغيل تتبع الزيارة فور تحميل الصفحة
track_visit()

# ==============================
# 4) الكاش: ثبات النتيجة لنفس النص
# ==============================

def get_content_hash(text: str) -> str:
    """هاش ثابت للنص لضمان نفس النتيجة دائماً لنفس المحتوى."""
    normalized = " ".join(text.strip().split())  # إزالة المسافات الزائدة
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def get_or_create_analysis(text: str) -> str:
    """
    1) يحاول قراءة التحليل من جدول viral_scores_cache
    2) إذا لم يجده، يستدعي Gemini ثم يخزن النتيجة في الكاش
    """
    content_hash = get_content_hash(text)

    # 1) حاول قراءة الكاش
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
            cached_text = res.data[0]["analysis_text"]
            if cached_text:
                return cached_text
    except Exception as e:
        print(f"[cache read] Error: {e}")

    # 2) لم نجد كاش → استدعاء Gemini
    gen_config = types.GenerateContentConfig(
        temperature=0.0,
        top_p=0.1,
        top_k=1,
        max_output_tokens=900,
    )

    prompt = f"""
أنت خبير محتوى فيروسي ومتخصص في نموذج STEPPS لجونا بيرجر.

المطلوب:
- حلّل النص التالي بناءً على **ستة عوامل STEPPS** فقط:
  1) Social Currency (العملة الاجتماعية)
  2) Triggers (المحفّزات)
  3) Emotion (المشاعر)
  4) Public (الظهور العام)
  5) Practical Value (القيمة العملية)
  6) Stories (القصص)

قواعد صارمة:
- لا تحسب ولا تعرض "نتيجة نهائية" من 100 أو أي مجموع للأرقام.
- اكتفِ فقط بإعطاء تقييم رقمي من 10 لكل عامل + شرح من سطرين إلى ثلاثة كحد أقصى.
- اكتب المخرجات كلها بالعربية، ووضّح اسم كل عامل ثم الدرجة ثم الشرح.
- رتّب العوامل من 1 إلى 6 بنفس الترتيب السابق.
- لا تذكر أي معادلات حسابية ولا نسبة مئوية إجمالية.

النص المراد تحليله:
{text}
"""

    response = genai_client.models.generate_content(
        model="gemini-2.0-flash-exp",
        contents=prompt,
        config=gen_config,
    )

    analysis_text = response.text or ""

    # 3) تخزين النتيجة في الكاش (Best-effort)
    try:
        supabase.table("viral_scores_cache").insert(
            {
                "app_id": APP_ID,
                "content_hash": content_hash,
                "analysis_text": analysis_text,
            }
        ).execute()
    except Exception as e:
        print(f"[cache write] Error: {e}")

    return analysis_text


# ==============================
# 5) واجهة المستخدم
# ==============================

st.title("🎯 مُحلّل احتمالية انتشار المحتوى الفيروسي")

with st.expander("💡 كيف يعمل هذا المحلل؟"):
    st.markdown(
        """
          هذه الأداة تحلل نصّك (منشور، تغريدة، سكريبت فيديو...) بناءً على ستة عوامل:
        
        1. **Social Currency – العملة الاجتماعية:**  
           هل يجعل المحتوى الشخص الذي يشاركه يبدو أذكى، أعمق، أو أكثر خبرة؟
        
        2. **Triggers – المحفّزات:**  
           هل يرتبط المحتوى بمواقف وأحداث متكرّرة في حياة الناس (روتين، أماكن، عبارات يومية)؟
        
        3. **Emotion – المشاعر:**  
           إلى أي درجة يثير النص مشاعر قوية مثل الدهشة، الحماس، الفضول، الإلهام أو حتى الغضب البنّاء؟
        
        4. **Public – الظهور العلني:**  
           هل من السهل رؤية هذا السلوك أو تقليده؟ هل المحتوى قابل للمحاكاة أمام الآخرين؟
        
        5. **Practical Value – القيمة العملية:**  
           هل يقدم النص فائدة ملموسة، نصائح قابلة للتطبيق، أو يوفر وقتاً/مالاً/جهداً على المتلقي؟
        
        6. **Stories – القصص:**  
           هل المعلومة مغلفة داخل قصة أو مثال حي يجعل الرسالة سهلة التذكّر والمشاركة؟
        """,
        unsafe_allow_html=False,
    )

post_text = st.text_area(
    "✍️ أدخل نص المنشور / التغريدة / سكريبت الفيديو هنا:",
    height=170,
    placeholder="اكتب هنا النص الكامل الذي تريد قياس قابليته للانتشار (منشور، تغريدة، سكريبت فيديو، رسالة مبيعات...)",
)

if st.button("تحليل الآن 🚀"):
    if not post_text or len(post_text.strip()) < 20:
        st.warning("الرجاء إدخال نص حقيقي لا يقل عن 20 حرفاً ليتم تحليله.")
    else:
        # تسجيل الـ CTA في Supabase
        track_cta_event()

        with st.spinner("⏳ جاري تحليل النص "):
            analysis = get_or_create_analysis(post_text.strip())

        if not analysis.strip():
            st.error("لم يصلنا رد واضح من نموذج الذكاء الاصطناعي. حاولي مرة أخرى أو اختصري النص.")
        else:
            st.markdown(
                """
                <div class="result-box">
                    <div class="result-title">📊 تحليل النص وفق عوامل STEPPS الستّة:</div>
                    <div class="result-text">
                """,
                unsafe_allow_html=True,
            )

            # مخرجات التحليل (مع الحفاظ على الـ line breaks)
            st.markdown(analysis, unsafe_allow_html=False)

            st.markdown("</div></div>", unsafe_allow_html=True)

# ==============================
# 6) الفوتر
# ==============================
st.markdown("""
<div class="footer-container">
  <span class="rtl-text">جميع الحقوق محفوظة © 2026 |</span>
  <span class="ltr-text">AI Product Builder - Layan Khalil</span>
</div>
""", unsafe_allow_html=True)


