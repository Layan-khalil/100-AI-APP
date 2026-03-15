import streamlit as st
from google import genai
from google.genai import types as g_types # تم استخدام الاسم المستعار لتجنب التعارض
from io import BytesIO
import base64
import json 
from google.api_core.exceptions import ResourceExhausted, ServiceUnavailable, DeadlineExceeded
import time

# =================================================================
# 1. إعدادات الصفحة و RTL/Responsive CSS
# =================================================================

st.set_page_config(
    page_title="مُحلّل الهوية الرقمية",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# قواعد CSS لفرض RTL/التنسيق
st.markdown("""
<style>
    /* ---------------------------------
    *** قواعد CSS الشاملة لـ RTL والتنسيق ***
    ----------------------------------- */
    html, body, .block-container, .stApp { direction: rtl !important; }
    h1, h2, h3, h4, h5, h6, p, .stMarkdown, .stText, .stAlert { text-align: right !important; direction: rtl !important; }

    /* === تنسيق الزر والألوان === */
    .stButton>button { 
        font-weight: bold; width: 100%; 
        background-color: #0ea5e9; /* أزرق سماوي */
        color: white; border-radius: 8px; padding: 10px 20px; 
        font-size: 1.1em; transition: all 0.3s ease; 
        box-shadow: 0 4px 15px rgba(14, 165, 233, 0.4); 
    }
    .stButton>button:hover { background-color: #0284c7; box-shadow: 0 6px 20px rgba(14, 165, 233, 0.6); transform: translateY(-2px); }

    /* === تنسيق بطاقة النتيجة === */
    .analysis-card { 
        padding: 30px; border-radius: 12px; margin-top: 30px; 
        background-color: #f0f9ff; border-right: 8px solid #0ea5e9; 
        box-shadow: 0 4px 12px rgba(0,0,0,0.15); 
    }
    .result-title { font-size: 1.6em; font-weight: bold; color: #1e293b; margin-bottom: 20px; border-bottom: 2px solid #bae6fd; padding-bottom: 10px;}
    
    /* === تنسيق المصفوفة والنتائج === */
    .score-high, .score-medium, .score-low {
        font-weight: bold;
        padding: 6px 12px;
        border-radius: 4px;
        color: white;
        text-align: center;
        display: inline-block;
        min-width: 80px;
    }
    .score-high { background-color: #10b981; } /* أخضر */
    .score-medium { background-color: #f59e0b; } /* برتقالي */
    .score-low { background-color: #dc2626; } /* أحمر */

    .matrix-table {
        width: 100%;
        border-collapse: collapse;
        margin-top: 15px;
    }
    .matrix-table th, .matrix-table td {
        border: 1px solid #e0f2fe;
        padding: 12px;
        text-align: center;
        vertical-align: middle;
    }
    .matrix-table th {
        background-color: #e0f7ff;
        color: #0c4a6e;
        font-weight: 700;
        font-size: 1.05em;
    }
    .matrix-table td:first-child {
        text-align: right;
        font-weight: 600;
        background-color: #f8ffff;
    }
    
    /* === تنسيق التذييل (Footer) الجديد === */
    .custom-footer {
        position: fixed; /* تثبيت في أسفل النافذة */
        bottom: 0;
        right: 0;
        left: 0;
        width: 100%;
        text-align: center; /* توسيط النص */
        padding: 10px 0;
        background-color: #f8f8f8; /* خلفية رمادية فاتحة */
        color: #64748b; /* لون النص */
        font-size: 0.85em;
        border-top: 1px solid #e2e8f0;
        z-index: 100; /* ضمان بقائه فوق المحتوى */
    }

    #MainMenu, footer, header { visibility: hidden; }
</style>
""", unsafe_allow_html=True)


# =================================================================
# 2. تهيئة نموذج Gemini (Multimodal)
# =================================================================
client = None
MAX_RETRIES = 3
INITIAL_DELAY = 5

try:
    # استخدام مفتاح API إذا كان موجودًا في بيئة التشغيل
    API_KEY = st.secrets.get("GEMINI_API_KEY", "")
    if API_KEY:
        client = genai.Client(api_key=API_KEY)
except Exception as e:
    st.error(f"خطأ غير متوقع أثناء التهيئة: {e}")
    client = None

# دالة لتحويل ملف الصورة المرفوع إلى Base64
def file_to_base64_part(uploaded_file):
    """يقرأ ملف Streamlit المرفوع ويحوله إلى تنسيق inlineData للـ API."""
    if uploaded_file is not None:
        return g_types.Part.from_bytes( 
            data=uploaded_file.getvalue(),
            mime_type=uploaded_file.type
        )
    return None

# =================================================================
# 3. دالة التحليل المُركَّب والمُهيكل
# =================================================================

def hybrid_analyze(image_part, identity, goal, content_samples):
    """
    تستخدم نموذج Gemini مع مدخلات نصية مُهيكلة وصورية لتوليد مصفوفة الاتساق.
    """
    if not client:
        return {"error": "فشل الاتصال بـ Gemini API. يرجى التأكد من توفير مفتاح API صالح."}, []

    # --- System Prompt ---
    system_prompt = (
        "You are a highly specialized Digital Identity Analyst. Your task is to perform a deep analysis of the user's content, "
        "leveraging the provided structured text samples (for deep message analysis) and the screenshot (for visual analysis). "
        "The analysis MUST culminate in generating the required Consistency Matrix scores. "
        "The score values MUST be strictly: 'عالي', 'متوسط', or 'منخفض'. "
        
        "Output MUST be a structured JSON object. Ensure all text inside the JSON values is clearly formatted in Arabic."
    )
    
    # --- User Prompt ---
    prompt = f"""
    قم بتحليل الهوية الرقمية بناءً على المدخلات التالية:
    
    1. **الهوية/التخصص المُعلن:** {identity}
    2. **الهدف الاستراتيجي للمحتوى:** {goal}
    3. **عينات المحتوى المُهيكلة (الرجاء تحليل هذه النصوص لتحديد النبرة، العمق، والتنوع):**
    ---
    {content_samples}
    ---
    
    4. **الهوية البصرية (من الصورة المرفوعة):** (حلل الألوان، جودة التصميم، والخطوط الظاهرة في لقطة الشاشة).
    
    قم بملء مصفوفة الاتساق أدناه بناءً على التحليل، ثم قدم ملخصاً ونصائح استراتيجية مُعمقة:
    """
    
    # --- Response Schema ---
    response_schema = g_types.Schema(
        type=g_types.Type.OBJECT,
        properties={
            "ConsistencyMatrix": g_types.Schema(
                type=g_types.Type.OBJECT,
                properties={
                    "Textual_Identity_Score": g_types.Schema(type=g_types.Type.STRING, enum=["عالي", "متوسط", "منخفض"], description="Score for Textual Consistency vs. Declared Identity."),
                    "Textual_Goal_Score": g_types.Schema(type=g_types.Type.STRING, enum=["عالي", "متوسط", "منخفض"], description="Score for Textual Consistency vs. Strategic Goal (Call-to-Action/Conversion)."),
                    "Visual_Identity_Score": g_types.Schema(type=g_types.Type.STRING, enum=["عالي", "متوسط", "منخفض"], description="Score for Visual Consistency vs. Declared Identity (Professionalism/Style)."),
                    "Visual_Goal_Score": g_types.Schema(type=g_types.Type.STRING, enum=["عالي", "متوسط", "منخفض"], description="Score for Visual Consistency vs. Strategic Goal (Clarity/Branding for Conversion)."),
                },
                required=["Textual_Identity_Score", "Textual_Goal_Score", "Visual_Identity_Score", "Visual_Goal_Score"]
            ),
            "ObservedIdentitySummary": g_types.Schema(type=g_types.Type.STRING, description="A detailed summary of the observed persona based on the combined analysis of text and image."),
            "StrategicAdjustments": g_types.Schema(type=g_types.Type.STRING, description="Immediate, actionable advice derived from the Matrix scores, focusing on where the low scores exist.")
        },
        required=["ConsistencyMatrix", "ObservedIdentitySummary", "StrategicAdjustments"]
    )

    config = g_types.GenerateContentConfig(
        system_instruction=system_prompt,
        response_mime_type="application/json",
        response_schema=response_schema
    )
    
    # Fix: استخدام Constructor Part() مع الكلمة المفتاحية 'text'
    contents = [image_part, g_types.Part(text=prompt)] 

    for attempt in range(MAX_RETRIES):
        try:
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=contents,
                config=config 
            )
            
            # JSON Processing
            raw_text = response.text.strip()
            # Clean up potential markdown formatting from the response
            if raw_text.startswith("```json"):
                raw_text = raw_text.strip("```json").strip("```").strip()
            
            try:
                if raw_text:
                    return json.loads(raw_text), []
                else:
                    return {"error": "استجابة النموذج كانت فارغة."}, []
            except json.JSONDecodeError as json_err:
                return {"error": f"فشل تحليل استجابة JSON: {json_err}. النص الخام: {raw_text[:500]}..."}, []

        except (ResourceExhausted, ServiceUnavailable, DeadlineExceeded) as e:
            if attempt < MAX_RETRIES - 1:
                delay = INITIAL_DELAY * (2 ** attempt) 
                st.warning(f"⚠️ فشلت المحاولة {attempt + 1} بسبب ضغط الخادم. سيتم إعادة المحاولة بعد {delay} ثواني...")
                time.sleep(delay)
            else:
                st.error(f"خطأ بالتوليد (API): فشلت جميع المحاولات. التفاصيل: {e}")
                return {"error": str(e)}, []
        except Exception as e:
            st.error(f"خطأ غير متوقع: {e}")
            return {"error": str(e)}, []

    return {"error": "فشل غير محدد في توليد المحتوى بعد محاولات متعددة."}, []


# =================================================================
# 4. واجهة المستخدم (Streamlit UI)
# =================================================================

st.title("🔬 مُحلّل الهوية الرقمية (المصفوفة المُركَّبة)")
st.subheader("لضمان أعلى جودة، نوفر للنموذج عينات مُهيكلة وصورة للتحليل.")

# === 🌟 الشرح التفصيلي للهدف ===
with st.expander("💡 التعليمات: كيف تدخل البيانات لضمان أفضل تحليل؟"):
    st.markdown("""
        **1. عينات المحتوى المُهيكلة (ضروري):**
        * الرجاء نسخ ولصق النصوص لآخر 3-5 منشورات.
        * **لكل منشور، يجب تحديد نوعه ومستوى تفاعله (تقديري):**
            * **مثال على إدخال مُهيكل:**
                ```
                --- بوست 1 ---
                النوع: فيديو قصير
                التفاعل: عالي
                النص: (اكتب النص كاملاً)
                --- بوست 2 ---
                النوع: نص/صورة ثابتة
                التفاعل: متوسط
                النص: (اكتب النص كاملاً)
                ```
        
        **2. لقطة الشاشة (ضروري):**
        * التقطي صورة واحدة لصفحتك الرئيسية (لتحليل الهوية البصرية، الألوان، الخطوط، وتنسيق الصور).
    """)

st.markdown("---")

# ----------------------------------------------------
# منطقة الإدخال
# ----------------------------------------------------

# حقل عينات المحتوى النصي
content_samples = st.text_area(
    "1. الصق هنا نصوص آخر منشوراتك مُهيكلة (بالتنسيق الموضح أعلاه):", 
    placeholder="مثلاً: --- بوست 1 --- النوع: فيديو... التفاعل: عالي... النص:...",
    key="samples_input",
    height=250
)

col1, col2 = st.columns(2)

with col1:
    identity = st.text_area(
        "2. هويتك/تخصصك المُعلن:", 
        placeholder="مثلاً: خبير استراتيجي في تقنية البلوكتشين.",
        key="identity_input",
        height=100
    )

with col2:
    goal = st.text_area(
        "3. الهدف الحالي لمحتواك:", 
        placeholder="مثلاً: بناء علامة تجارية موثوقة لجذب طلبات الاستشارة.",
        key="goal_input",
        height=100
    )

# حقل رفع الصورة
uploaded_file = st.file_uploader(
    "4. رفع لقطة شاشة (صورة) لصفحتك الرئيسية (لتحليل الهوية البصرية):",
    type=["png", "jpg", "jpeg"],
    help="الصورة مطلوبة لتحليل الألوان والخطوط وجودة التصميم."
)

# ----------------------------------------------------
# زر التشغيل
# ----------------------------------------------------
if st.button("🚀 بدء التحليل المُركَّب والمصفوفة", width='stretch'):
    
    content_samples_clean = content_samples.strip()
    identity_clean = identity.strip()
    goal_clean = goal.strip()

    # التحقق من الإدخال
    if not uploaded_file or not identity_clean or not goal_clean or not content_samples_clean:
        st.warning("الرجاء إكمال جميع الحقول الأربعة (النصوص، الهوية، الهدف، ورفع الصورة) للمتابعة.")
        st.stop()
    
    # تحقق من الحد الأدنى للبيانات
    is_identity_readable = len(identity_clean) >= 10
    is_goal_readable = len(goal_clean) >= 10
    is_samples_enough = len(content_samples_clean) >= 100 # نرفع الحد لضمان وجود عينات كافية

    if not is_identity_readable or not is_goal_readable or not is_samples_enough:
        st.warning("الرجاء إدخال وصف مفهوم وكافٍ للهوية والهدف، وتقديم عينات محتوى تفوق 100 حرف.")
        st.stop()

    # تحويل الملف المرفوع لمدخل API
    image_part = file_to_base64_part(uploaded_file)
    
    with st.spinner("جاري بناء المصفوفة وتحليل النصوص والهوية البصرية..."):
        # استدعاء دالة التحليل
        analysis_data, _ = hybrid_analyze(image_part, identity_clean, goal_clean, content_samples_clean)

    if analysis_data and "error" in analysis_data:
        st.error(f"فشل التحليل: {analysis_data['error']}")
    
    elif analysis_data:
        st.markdown("---")
        st.markdown("## 📈 نتائج تحليل الهوية الرقمية المُركَّبة")

        # 1. عرض المصفوفة (Consistency Matrix)
        matrix = analysis_data.get("ConsistencyMatrix", {})
        
        # دالة مساعدة لتنسيق الدرجات
        def format_score(score):
            if score == "عالي":
                return f'<span class="score-high">{score}</span>'
            elif score == "متوسط":
                return f'<span class="score-medium">{score}</span>'
            else:
                return f'<span class="score-low">{score}</span>'

        st.markdown('<div class="result-title">مصفوفة الاتساق المتعددة (Consistency Matrix)</div>', unsafe_allow_html=True)
        
        matrix_html = f"""
        <table class="matrix-table">
            <thead>
                <tr>
                    <th>البعد الذي يتم تقييمه</th>
                    <th>مقارنةً بالهوية المعلنة</th>
                    <th>مقارنةً بالهدف الاستراتيجي</th>
                </tr>
            </thead>
            <tbody>
                <tr>
                    <td>التناسق النصي (الرسالة والنبرة)</td>
                    <td>{format_score(matrix.get("Textual_Identity_Score", "-"))}</td>
                    <td>{format_score(matrix.get("Textual_Goal_Score", "-"))}</td>
                </tr>
                <tr>
                    <td>التناسق البصري (الألوان والتصميم)</td>
                    <td>{format_score(matrix.get("Visual_Identity_Score", "-"))}</td>
                    <td>{format_score(matrix.get("Visual_Goal_Score", "-"))}</td>
                </tr>
            </tbody>
        </table>
        """
        st.markdown(matrix_html, unsafe_allow_html=True)

        # 2. ملخص الهوية الملحوظة
        st.markdown('<div style="height: 30px;"></div>', unsafe_allow_html=True)
        st.markdown('<div class="result-title">ملخص الهوية الملحوظة (نصياً وبصرياً)</div>', unsafe_allow_html=True)
        st.markdown(f'**{analysis_data.get("ObservedIdentitySummary", "لم يتم توليد الملخص.")}**', unsafe_allow_html=True)

        # 3. التعديلات الاستراتيجية الفورية
        st.markdown('<div style="height: 30px;"></div>', unsafe_allow_html=True)
        st.markdown('<div class="result-title">تعديلات استراتيجية فورية</div>', unsafe_allow_html=True)
        st.markdown(analysis_data.get("StrategicAdjustments", "لم يتم توليد التعديلات."), unsafe_allow_html=True)
        
        st.markdown('</div>', unsafe_allow_html=True)


# =================================================================
# 5. التذييل (Footer)
# =================================================================
st.markdown(
    '<div class="custom-footer">جميع الحقوق محفوظة © 2026 | AI Product Creator - Layan Khalil</div>', 
    unsafe_allow_html=True
)