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
    page_title="مُنشئ تحديات المحتوى",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# قواعد CSS الشاملة لفرض RTL على كل عناصر Streamlit وإضافة تنسيق
st.markdown("""
<style>
    /* ---------------------------------
    *** قواعد CSS الشاملة لـ RTL وتفادي القص ***
    ----------------------------------- */
    
    html, body, .block-container, .stApp {
        direction: rtl !important;
    }
    h1, h2, h3, h4, h5, h6, p, .stMarkdown, .stText { 
        text-align: right !important;
        direction: rtl !important;
    }
    textarea, input, .st-emotion-cache-1jm6hrl, .st-emotion-cache-1jm6hrl * { 
        direction: rtl !important;
        text-align: right !important;
    }
    
    /* 💥 FIX: تطبيق التفاف النص (Word Break) لتفادي قص الكلمات الطويلة */
    .stMarkdown, .stText, .stCode, .stMetric, .st-emotion-cache-1jm6hrl, .st-emotion-cache-1ftn75r {
        word-break: break-word !important;
        white-space: normal !important;
    }
    /* تعديل خاص على شفرة الـ st.code لضمان الالتفاف */
    .stCode pre {
        white-space: pre-wrap !important;
        word-break: break-word !important;
        text-align: right !important;
    }


    /* ---------------------------------
    *** تنسيق زر الإجراء (Button Styling) ***
    ----------------------------------- */
    .stButton>button {
        font-weight: bold;
        width: 100%; 
        direction: rtl !important;
        background-color: #3b82f6; /* أزرق داكن للإيحاء بالإبداع والنمو */
        color: white;
        border: none;
        border-radius: 8px;
        padding: 10px 20px;
        font-size: 1.1em;
        transition: all 0.3s ease;
        box-shadow: 0 4px 15px rgba(59, 130, 246, 0.4); 
    }
    .stButton>button:hover {
        background-color: #2563eb; 
        box-shadow: 0 6px 20px rgba(59, 130, 246, 0.6); 
        transform: translateY(-2px); 
    }

    /* تنسيق خاص لأقسام النتيجة */
    .challenge-section {
        background-color: #ebf8ff; /* خلفية زرقاء فاتحة */
        padding: 20px;
        border-radius: 12px;
        margin-bottom: 25px;
        border: 2px solid #3b82f6; /* حدود زرقاء */
        box-shadow: 0 4px 12px rgba(0,0,0,0.05);
    }
    .challenge-section h3 {
        color: #1e3a8a; /* لون أزرق غامق جداً للعناوين الفرعية */
        text-align: right !important;
        border-bottom: 3px solid #3b82f6; 
        padding-bottom: 5px;
        margin-top: 0;
        margin-bottom: 15px;
        font-weight: 700;
    }
    .hashtag-tag {
        display: inline-block;
        background-color: #bfdbfe;
        color: #1e40af;
        padding: 5px 10px;
        border-radius: 15px;
        margin-left: 10px;
        font-weight: bold;
        font-size: 0.9em;
        margin-bottom: 5px;
    }
    
    /* --- التنسيق الجديد لتصغير خط الملخص --- */
    .summary-item {
        margin-bottom: 10px;
        padding: 8px 15px;
        border-radius: 6px;
        background-color: #e0f2fe; /* أزرق فاتح جداً */
        border-right: 4px solid #3b82f6;
    }
    .summary-item strong {
        display: block;
        font-size: 0.85em; /* تصغير حجم الخط للعناوين الفرعية (الاسم، الهدف، الخ...) */
        color: #1e3a8a;
        margin-bottom: 3px;
    }
    .summary-item span {
        font-size: 1em; /* تصغير حجم الخط للمحتوى الفعلي */
        color: #0c4a6e;
    }
    /* -------------------------------------- */


    /* حل مشكلة st.caption */
    .rtl-caption {
        direction: rtl !important;
        text-align: right !important;
        margin-top: -15px; 
        font-size: 0.9em; 
        color: rgba(49, 51, 63, 0.6); 
    }
    
    /* ---------------------------------
    *** تنسيق حقوق النشر (الـ Footer المُعزز) ***
    ----------------------------------- */
    
    /* إخفاء التذييل الافتراضي لـ Streamlit للتحكم بالتذييل الخاص بنا */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}

    /* التذييل الخاص بنا مع طبقة عليا لضمان ظهوره (z-index) */
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
        z-index: 1000; /* قيمة عالية لضمان الظهور فوق كل شيء */
    }

    /* إصلاح تنسيق الشرح داخل Expander (للتنسيق العربي) */
    .expander-content {
        text-align: right !important;
        direction: rtl !important;
    }
    .expander-content ul { 
        padding-right: 15px !important;
        margin-right: 0px !important;
    }
    .expander-content li {
        text-align: right !important;
    }

</style>
""", unsafe_allow_html=True)


# =================================================================
# 2. تهيئة نموذج Gemini 
# =================================================================
client = None
MAX_RETRIES = 3
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
# 3. دالة توليد التحدي الرئيسية
# =================================================================

def generate_challenge(topic, duration):
    """
    يولد فكرة تحدي محتوى كاملة (Content Challenge) في هيكل JSON.
    """
    if not client:
        return {"error": "فشل الاتصال بـ Gemini API."}
        
    system_prompt = (
        "أنت استراتيجي إبداعي مختص في تحديات المحتوى (Content Challenges) المصممة لزيادة المحتوى الذي يولده المستخدم (UGC) بشكل كبير. "
        "مهمتك هي إنشاء تحدي اجتماعي متكامل، يقدم قيمة للجمهور ويضمن مشاركة يومية قوية على منصات مثل انستغرام وتيك توك. "
        "يجب أن يكون الإخراج في تنسيق JSON حصراً يتبع المخطط المحدد بدقة باللغة العربية."
    )

    prompt = f"""
    أريد خطة تحدي محتوى كاملة.
    
    **1. الموضوع/التخصص:** {topic}
    **2. المدة المطلوبة:** {duration} يوماً
    
    **المهام:**
    1.  ابتكار اسم جذاب وتحديد الهدف الرئيسي للتحدي.
    2.  تحديد الخطوات اليومية (Task) لكل يوم، وتوضيح نوع المحتوى (UGC Type) المطلوب للمشاركة (صورة، فيديو، قصة نصية).
    3.  توفير هاشتاغ رسمي واحد رئيسي و 3-5 هاشتاجات إضافية.
    4.  تحديد قواعد واضحة وبسيطة للمشاركة في التحدي.
    """
    
    # مخطط JSON لضمان مخرجات منظمة
    response_schema = {
        "type": "OBJECT",
        "properties": {
            "ChallengeName": {
                "type": "STRING",
                "description": "اسم جذاب ومثير للتحدي."
            },
            "Theme": {
                "type": "STRING",
                "description": "الموضوع الأساسي أو المفهوم العام للتحدي."
            },
            "Goal": {
                "type": "STRING",
                "description": "الهدف الاستراتيجي من التحدي (مثلاً: زيادة الوعي بالعلامة التجارية، جمع 100 محتوى UGC)."
            },
            "DurationDays": {
                "type": "INTEGER",
                "description": "مدة التحدي بالأيام."
            },
            "OfficialHashtag": {
                "type": "STRING",
                "description": "الهاشتاغ الرسمي والفريد للتحدي."
            },
            "BonusHashtags": {
                "type": "ARRAY",
                "description": "3-5 هاشتاجات إضافية ذات صلة لدعم الوصول.",
                "items": {"type": "STRING"}
            },
            "Rules": {
                "type": "ARRAY",
                "description": "قواعد واضحة ومختصرة للمشاركة في التحدي.",
                "items": {"type": "STRING"}
            },
            "ChallengeSteps": {
                "type": "ARRAY",
                "description": "قائمة المهام اليومية بالتفصيل.",
                "items": {
                    "type": "OBJECT",
                    "properties": {
                        "Day": {"type": "INTEGER"},
                        "Task": {"type": "STRING", "description": "مهمة اليوم التي يجب على المستخدم تنفيذها."},
                        "UGC_Type": {"type": "STRING", "description": "نوع المحتوى المطلوب مشاركته (صورة، فيديو قصير، قصة نصية)."}
                    }
                }
            }
        },
        "propertyOrdering": ["ChallengeName", "Theme", "Goal", "DurationDays", "OfficialHashtag", "BonusHashtags", "Rules", "ChallengeSteps"]
    }

    # حلقة إعادة المحاولة
    for attempt in range(MAX_RETRIES):
        try:
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    response_mime_type="application/json",
                    response_schema=response_schema
                )
            )
            return json.loads(response.text)

        except (ResourceExhausted, ServiceUnavailable, DeadlineExceeded) as e:
            if attempt < MAX_RETRIES - 1:
                delay = INITIAL_DELAY * (2 ** attempt) 
                st.warning(f"⚠️ فشلت المحاولة {attempt + 1} بسبب ضغط الخادم. سيتم إعادة المحاولة بعد {delay} ثواني...")
                time.sleep(delay)
            else:
                st.error(f"خطأ بالتوليد (API): فشلت جميع المحاولات. التفاصيل: {e}")
                return {"error": str(e)}
        except Exception as e:
            st.error(f"خطأ غير متوقع: {e}")
            return {"error": str(e)}

    return {"error": "فشل غير محدد في توليد المحتوى بعد محاولات متعددة."}


# =================================================================
# 4. واجهة المستخدم (Streamlit UI)
# =================================================================

st.title("💡 مُنشئ تحديات المحتوى (Content Challenge Generator)")

# === 🌟 الشرح التفصيلي للهدف ===
with st.expander("💡 حول مُنشئ تحديات المحتوى"):
    st.markdown("""
        <div class="expander-content">
        
        **مُنشئ تحديات المحتوى** هو أداة استراتيجية لزيادة المحتوى الذي يولده المستخدم (UGC) بشكل هائل، مما يعزز مصداقية علامتك التجارية ويقلل من عبء إنشاء المحتوى.

        #### ما هو الهدف؟
        * تحويل الجمهور العادي إلى **مشاركين نشطين ومروجين مجانيين** لمنتجك أو رسالتك.
        * إنشاء **خطة يومية جاهزة للنشر** تضمن تفاعلاً مستمراً لعدة أيام.

        #### كيف يعمل التحدي؟
        التطبيق يولد خطة تتضمن:
        1.  **هدف استراتيجي واضح** (مثل زيادة عدد المتابعين أو بناء مكتبة من شهادات العملاء).
        2.  **مهام يومية** تتطلب من المشارك إنتاج نوع معين من المحتوى (صورة، فيديو، نص) ومشاركته باستخدام الهاشتاغ الرسمي.
        3.  **قواعد بسيطة** لضمان سير التحدي بسلاسة.

        **باختصار:** هي خطتك الجاهزة لإطلاق حملة تسويق اجتماعية مدفوعة بالجمهور!
        
        </div>
    """, unsafe_allow_html=True)

st.markdown("---")

col1, col2 = st.columns([3, 1])

with col1:
    topic = st.text_input(
        "الموضوع أو التخصص الذي تريد إنشاء تحدٍ حوله:", 
        placeholder="مثلاً: التخطيط المالي للمبتدئين، اللياقة البدنية في المنزل، تعلم لغة جديدة.",
        key="topic_input"
    )

with col2:
    duration = st.number_input(
        "مدة التحدي (بالأيام):", 
        min_value=3, 
        max_value=30, 
        value=7,
        key="duration_input"
    )

st.markdown('<div class="rtl-caption">المدة المثالية لمعظم التحديات هي 5 إلى 7 أيام.</div>', unsafe_allow_html=True)

if st.button("🚀 إنشاء تحدي المحتوى الآن", width='stretch'):
    if not topic:
        st.warning("الرجاء تحديد موضوع التحدي أولاً.")
        st.stop()
    
    with st.spinner("جاري صياغة خطة التحدي الاستراتيجية..."):
        challenge_plan = generate_challenge(topic, duration)

    if challenge_plan and "error" in challenge_plan:
        st.error(f"فشل التوليد: {challenge_plan['error']}")
    
    elif challenge_plan:
        st.markdown("---")
        st.markdown("## ✅ خطة التحدي جاهزة للنشر!")

        # ----------------------------------------------------
        # 1. الملخص الرئيسي (تم التعديل لتصغير الخط)
        # ----------------------------------------------------
        st.markdown('<div class="challenge-section">', unsafe_allow_html=True)
        st.markdown("<h3>📋 ملخص التحدي</h3>", unsafe_allow_html=True)
        
        # استخدام التنسيق HTML الجديد مع الفئة summary-item
        st.markdown(f"""
        <div class="summary-item">
            <strong>اسم التحدي الجذاب:</strong>
            <span>{challenge_plan.get("ChallengeName", "غير محدد")}</span>
        </div>
        <div class="summary-item">
            <strong>الهدف الاستراتيجي:</strong>
            <span>{challenge_plan.get("Goal", "غير محدد")}</span>
        </div>
        <div class="summary-item">
            <strong>المفهوم الأساسي:</strong>
            <span>{challenge_plan.get("Theme", "غير محدد")}</span>
        </div>
        """, unsafe_allow_html=True)
        
        st.markdown('</div>', unsafe_allow_html=True)

        # ----------------------------------------------------
        # 2. الهاشتاجات والقواعد
        # ----------------------------------------------------
        col_hash, col_rules = st.columns(2)
        
        with col_hash:
            st.markdown('<div class="challenge-section" style="background-color:#eff6ff; border: 2px solid #93c5fd;">', unsafe_allow_html=True)
            st.markdown("<h3># الهاشتاجات الرسمية</h3>", unsafe_allow_html=True)
            
            st.subheader("الهاشتاغ الرسمي:")
            st.code(challenge_plan.get("OfficialHashtag", "#تحدي_المحتوى_الجديد"))
            
            st.subheader("هاشتاجات إضافية (لزيادة الوصول):")
            bonus_hashtags = challenge_plan.get("BonusHashtags", [])
            if bonus_hashtags:
                st.markdown(''.join([f'<span class="hashtag-tag">{h}</span>' for h in bonus_hashtags]), unsafe_allow_html=True)
            st.markdown('</div>', unsafe_allow_html=True)
        
        with col_rules:
            st.markdown('<div class="challenge-section" style="background-color:#eff6ff; border: 2px solid #93c5fd;">', unsafe_allow_html=True)
            st.markdown("<h3>📜 قواعد المشاركة الأساسية</h3>", unsafe_allow_html=True)
            rules = challenge_plan.get("Rules", [])
            if rules:
                for idx, rule in enumerate(rules):
                    st.markdown(f'**{idx + 1}.** {rule}')
            st.markdown('</div>', unsafe_allow_html=True)

        # ----------------------------------------------------
        # 3. خطة التحدي اليومية
        # ----------------------------------------------------
        st.markdown('<div class="challenge-section">', unsafe_allow_html=True)
        st.markdown("<h3>📅 الخطة اليومية المفصلة (لزيادة UGC)</h3>", unsafe_allow_html=True)

        steps = challenge_plan.get("ChallengeSteps", [])
        if steps:
            for step in steps:
                day = step.get("Day")
                task = step.get("Task")
                ugc_type = step.get("UGC_Type")
                
                st.markdown(f"""
                <div style="border-right: 5px solid #3b82f6; padding-right: 15px; margin-bottom: 10px; background-color: #f7fbff; border-radius: 4px;">
                    <p style="font-weight: bold; font-size: 1.1em; color: #1e3a8a; margin-bottom: 5px;">اليوم {day}: {task}</p>
                    <p style="font-style: italic; font-size: 0.9em; color: #6b7280; margin-top: 0;">نوع المحتوى المطلوب: {ugc_type}</p>
                </div>
                """, unsafe_allow_html=True)
        
        st.markdown('</div>', unsafe_allow_html=True)
            
# =================================================================
# 5. التذييل (Footer)
# =================================================================
st.markdown(
    '<div class="custom-footer">جميع الحقوق محفوظة @ 2026 | AI Product Creator - Layan Khalil</div>', 
    unsafe_allow_html=True
)