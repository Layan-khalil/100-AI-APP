import streamlit as st
from google import genai
from google.genai import types 
from google.api_core.exceptions import ResourceExhausted, ServiceUnavailable, DeadlineExceeded 
import json 
import time 

# =================================================================
# 1. إعدادات الصفحة و RTL/Responsive CSS
# =================================================================

st.set_page_config(
    page_title=" مُنشئ الأسئلة المفتوحة",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# قواعد CSS الشاملة لفرض RTL/تفادي القص وتطبيق التنسيق
st.markdown("""
<style>
    /* ---------------------------------
    *** قواعد CSS الشاملة لـ RTL والتنسيق ***
    ----------------------------------- */
    
    html, body, .block-container, .stApp {
        direction: rtl !important;
    }
    /* تعديل لضمان محاذاة كل النص لليمين */
    h1, h2, h3, h4, h5, h6, p, .stMarkdown, .stText, .stCode, .st-emotion-cache-1jm6hrl { 
        text-align: right !important;
        direction: rtl !important;
    }
    
    /* === إصلاح المحاذاة في حقول الإدخال لتكون الكتابة من اليمين === */
    /* استهداف حقول النص والمناطق النصية وصناديق الاختيار لفرض RTL */
    textarea, input, 
    .stTextInput > div > div > input, 
    .stTextArea > div > textarea,
    .stSelectbox > label, .stSelectbox > div > div { 
        direction: rtl !important;
        text-align: right !important;
    }
    
    /* === إصلاح محاذاة القوائم (النقاط النجمية) === */
    ul, ol {
        list-style-position: outside !important; /* Outside works better for Streamlit markdown lists */
        padding-right: 0px !important; 
        padding-left: 0px !important;
        margin-right: 1.5rem !important; /* لإضافة إزاحة من اليمين للقائمة */
        margin-left: 0 !important;
        text-align: right !important;
        direction: rtl !important;
    }
    li {
        text-align: right !important;
        direction: rtl !important;
        /* هذا يضمن أن النص داخل كل نقطة يبدأ من اليمين */
    }
    /* ------------------------------------ */
    
    .stTextArea {
        height: 100px !important; 
    }

    /* ---------------------------------
    *** تنسيق زر الإجراء (Button Styling) ***
    ----------------------------------- */
    .stButton>button {
        font-weight: bold;
        width: 100%; 
        direction: rtl !important;
        background-color: #9333ea; /* بنفسجي جذاب */
        color: white;
        border: none;
        border-radius: 8px;
        padding: 10px 20px;
        font-size: 1.1em;
        transition: all 0.3s ease;
        box-shadow: 0 4px 15px rgba(147, 51, 234, 0.4); 
    }
    .stButton>button:hover {
        background-color: #7e22ce; 
        box-shadow: 0 6px 20px rgba(147, 51, 234, 0.6); 
        transform: translateY(-2px); 
    }
    
    /* ---------------------------------
    *** تنسيق بطاقة النتيجة (Question Card) ***
    ----------------------------------- */
    .question-card {
        padding: 25px;
        border-radius: 12px;
        margin-top: 30px;
        background-color: #f5f3ff; /* خلفية بنفسجية فاتحة جداً */
        border-left: 5px solid #9333ea;
        box-shadow: 0 4px 12px rgba(0,0,0,0.1);
    }
    .question-title {
        font-size: 1.6em;
        font-weight: bold;
        color: #1e293b;
        margin-bottom: 10px;
        text-align: right !important;
    }
    .analysis-section {
        border-top: 1px solid #ddd;
        padding-top: 15px;
        margin-top: 20px;
        text-align: right !important;
    }
    
    /* ---------------------------------
    *** تنسيق حقوق النشر (الـ Footer المُعزز) ***
    ----------------------------------- */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}

    .custom-footer {
        position: fixed;
        left: 0;
        bottom: 0;
        width: 100%;
        background-color: #f0f0f5; 
        color: #888888;
        text-align: center !important; 
        padding: 10px;
        font-size: 0.8em;
        border-top: 1px solid #dddddd;
        z-index: 1000; 
    }

</style>
""", unsafe_allow_html=True)


# =================================================================
# 2. تهيئة نموذج Gemini 
# =================================================================
client = None
MAX_RETRIES = 5 
INITIAL_DELAY = 5

try:
    API_KEY = st.secrets.get("GEMINI_API_KEY", "")
    if not API_KEY:
        st.warning("⚠️ لم يتم العثور على مفتاح GEMINI_API_KEY. يرجى إضافته إلى ملف secrets.toml.")
    else:
        client = genai.Client(api_key=API_KEY)
except Exception as e:
    st.error(f"خطأ غير متوقع أثناء التهيئة: {e}")
    client = None

# =================================================================
# 3. دالة توليد الأسئلة المفتوحة
# =================================================================

def generate_open_question(topic, goal, audience):
    """
    تستخدم نموذج Gemini لتوليد سؤال مفتوح مصمم لإثارة النقاش العميق.
    """
    if not client:
        return {"error": "فشل الاتصال بـ Gemini API."}, []

    # تعليمات النظام: تضمن أن النموذج يعمل كمُحفز للمحادثات ويخرج JSON
    system_prompt = (
        "You are a 'Conversation Catalyst' designed to generate highly engaging, open-ended questions for social media "
        "that compel detailed, long-form responses and opinions, strictly avoiding simple Yes/No answers. "
        "The final output MUST be a structured JSON object in Arabic, containing ONLY the keys: 'GeneratedQuestion' and 'EffectivenessAnalysis'. "
        "Do not include any introductory or closing text outside the JSON structure."
    )
    
    # الاستعلام للمستخدم
    prompt = f"""
    Based on the following inputs, generate a single, highly effective open-ended question that encourages a long, detailed discussion. 
    Then, provide a brief analysis of why this specific question structure is effective for driving engagement.

    * **Topic (الموضوع/المحور):** {topic}
    * **Goal/Response Type (الهدف من السؤال):** {goal}
    * **Target Audience (الجمهور المستهدف):** {audience}
    """
    
    # تحديد الهيكل المطلوب للـ JSON
    response_schema = types.Schema(
        type=types.Type.OBJECT,
        properties={
            "GeneratedQuestion": types.Schema(type=types.Type.STRING, description="The open-ended question generated in Arabic."),
            "EffectivenessAnalysis": types.Schema(type=types.Type.STRING, description="A brief analysis in Arabic explaining why the question structure will drive long, detailed responses.")
        },
        required=["GeneratedQuestion", "EffectivenessAnalysis"]
    )

    config = types.GenerateContentConfig(
        system_instruction=system_prompt,
        response_mime_type="application/json",
        response_schema=response_schema
    )

    # حلقة إعادة المحاولة
    for attempt in range(MAX_RETRIES):
        try:
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt,
                config=config 
            )
            
            # Since grounding is not used, we only process the JSON text
            raw_text = response.text.strip()
            
            try:
                if raw_text:
                    result = json.loads(raw_text)
                    return result, []
                else:
                    return {"error": "استجابة النموذج كانت فارغة."}, []
            except json.JSONDecodeError as json_err:
                return {"error": f"فشل تحليل استجابة JSON: {json_err}. النص الخام: {raw_text[:200]}..."}, []

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

st.title("💡 مُنشئ الأسئلة المفتوحة")
st.subheader("صمم سؤالاً يُجبر جمهورك على إبداء الرأي وكتابة تعليقات طويلة ومُفصَّلة.")

# === 🌟 الشرح التفصيلي للهدف ===
with st.expander("❓ ما هو السؤال المفتوح الفعّال؟"):
    st.markdown("""
        السؤال المفتوح الفعّال هو الذي لا يمكن الإجابة عليه بـ "نعم" أو "لا" أو بكلمة واحدة. هو سؤال:
        
        * ✅ **يتطلب تبريراً:** "لماذا" أو "كيف" أو "ماذا لو".
        * ✅ **يستدعي الخبرة الشخصية:** "ما هي أسوأ تجربة لك؟" أو "ما هو أهم درس تعلمته؟"
        * ✅ **يحتوي على جدل أو مقارنة:** "ما هي إيجابيات وسلبيات..." أو "أين تقع في هذا الجدال؟"
    """)

st.markdown("---")

# ----------------------------------------------------
# منطقة الإدخال
# ----------------------------------------------------

# استخدمنا col1 للحجم الأكبر و col2 للحجم الأصغر لتقسيم الإدخال
col1, col2 = st.columns([2, 1])

with col1:
    topic = st.text_area(
        "1. الموضوع/المحور الذي يدور حوله السؤال (مثال: مستقبل العمل عن بُعد):", 
        placeholder="الرجاء وصف الموضوع بوضوح.",
        key="topic_input",
        height=100
    )

with col2:
    audience = st.text_input(
        "3. الجمهور المستهدف (مثال: رواد الأعمال، مهندسو البرمجيات):", 
        placeholder="أدخل الجمهور",
        key="audience_input"
    )

goal = st.text_area(
    "2. الهدف من السؤال ونوع الرد المطلوب (مثال: الحصول على آراء شخصية مفصلة عن التحديات والمكاسب):",
    placeholder="ماذا تريد من الجمهور أن يكتب؟",
    key="goal_input",
    height=80
)

# ----------------------------------------------------
# زر التشغيل
# ----------------------------------------------------
if st.button("🔥 توليد سؤال مفتوح مُحفِّز للنقاش", width='stretch'):
    
    topic_clean = topic.strip()
    goal_clean = goal.strip()
    
    # 1. تحقق من الإدخال العام (للتأكد من عدم ترك الحقل فارغاً)
    if not topic_clean or not goal_clean:
        st.warning("الرجاء إدخال الموضوع والهدف من السؤال للمتابعة.")
        st.stop()
        
    # 2. تحقق من القراءة والمعنى (لمنع الكلمات العشوائية)
    # نتحقق من أن النص يحتوي على 10 أحرف و 3 كلمات على الأقل
    is_topic_readable = len(topic_clean) >= 10 and len(topic_clean.split()) >= 3
    is_goal_readable = len(goal_clean) >= 10 and len(goal_clean.split()) >= 3
    
    if not is_topic_readable or not is_goal_readable:
        st.warning("الرجاء ادخال مواضيع وأهداف مفهومة وقابلة للقراءة (يجب أن يحتوي الحقل على 10 أحرف و 3 كلمات على الأقل).")
        st.stop()
    
    with st.spinner("جاري صياغة سؤالك المفتوح الأكثر فاعلية..."):
        # استدعاء دالة التوليد
        question_data, _ = generate_open_question(topic, goal, audience)

    if question_data and "error" in question_data:
        st.error(f"فشل التوليد: {question_data['error']}")
    
    elif question_data:
        st.markdown("---")
        st.markdown("## 💬 السؤال المفتوح المُقترح")

        # عرض بطاقة النتيجة
        st.markdown('<div class="question-card">', unsafe_allow_html=True)
        
        # السؤال
        st.markdown('<div class="question-title">السؤال:</div>', unsafe_allow_html=True)
        st.markdown(f'**{question_data.get("GeneratedQuestion", "لم يتم توليد السؤال.")}**')
        
        # تحليل الفعالية
        st.markdown('<div class="analysis-section">', unsafe_allow_html=True)
        st.markdown('**✨ تحليل فعالية السؤال (لماذا سينجح؟):**')
        st.markdown(question_data.get("EffectivenessAnalysis", "لا يوجد تحليل من النموذج."))
        st.markdown('</div>', unsafe_allow_html=True)
        
        st.markdown('</div>', unsafe_allow_html=True)


# =================================================================
# 5. التذييل (Footer)
# =================================================================
st.markdown(
    '<div class="custom-footer">جميع الحقوق محفوظة © 2026 | AI Product Creator - Layan Khalil</div>', 
    unsafe_allow_html=True
)