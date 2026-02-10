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
    page_title=" محلل التفاعل المضاد",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# قواعد CSS الشاملة لفرض RTL على كل عناصر Streamlit وإضافة تنسيق
st.markdown("""
<style>
    /* ---------------------------------
    *** قواعد CSS الشاملة لـ RTL ***
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
    
    /* ---------------------------------
    *** تنسيق زر الإجراء (Button Styling) ***
    ----------------------------------- */
    .stButton>button {
        font-weight: bold;
        width: 100%; 
        direction: rtl !important;
        background-color: #f75d5d; /* أحمر داكن للإيحاء بالتحليل السلبي */
        color: white;
        border: none;
        border-radius: 8px;
        padding: 10px 20px;
        font-size: 1.1em;
        transition: all 0.3s ease;
        box-shadow: 0 4px 15px rgba(247, 93, 93, 0.4); 
    }
    .stButton>button:hover {
        background-color: #e04b4b; 
        box-shadow: 0 6px 20px rgba(247, 93, 93, 0.6); 
        transform: translateY(-2px); 
    }

    /* تنسيق خاص لأقسام النتيجة */
    .analysis-section {
        background-color: #fff0f0; /* خلفية حمراء فاتحة */
        padding: 20px;
        border-radius: 12px;
        margin-bottom: 25px;
        border: 2px solid #f75d5d; /* حدود حمراء */
        box-shadow: 0 4px 12px rgba(0,0,0,0.05);
    }
    .analysis-section h3 {
        color: #b30000; /* لون أحمر غامق جداً للعناوين الفرعية */
        text-align: right !important;
        border-bottom: 3px solid #f75d5d; 
        padding-bottom: 5px;
        margin-top: 0;
        margin-bottom: 15px;
        font-weight: 700;
    }
    .insight-item {
        margin-bottom: 8px;
        padding-right: 20px;
        position: relative;
        font-size: 1em;
    }
    .insight-item::before {
        content: '🔴'; /* نقطة حمراء */
        font-weight: bold;
        display: inline-block;
        width: 1em;
        margin-right: -1em;
        position: absolute;
        right: 0;
    }
    .core-blind-spot {
        font-size: 1.2em;
        font-weight: bold;
        color: #b30000;
        background-color: #ffdddd;
        padding: 10px;
        border-radius: 6px;
        border-right: 5px solid #b30000;
    }

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

    /* ---------------------------------
    *** إصلاح تنسيق الشرح داخل Expander ***
    ----------------------------------- */
    .st-emotion-cache-1ftn75r ul { /* UL element inside expander */
        padding-right: 0px !important;
        margin-right: 0px !important;
        list-style-position: inside !important;
    }
    .st-emotion-cache-1ftn75r li {
        text-align: right !important;
        padding-right: 0px !important;
        margin-right: 0px !important;
    }
    .expander-content {
        text-align: right !important;
        direction: rtl !important;
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
    # ⚠️ ملاحظة: يجب أن يكون مفتاح API متاحاً في بيئة Streamlit Secrets
    API_KEY = st.secrets.get("GEMINI_API_KEY", "")
    if not API_KEY:
        st.warning("⚠️ لم يتم العثور على مفتاح GEMINI_API_KEY. يرجى إضافته إلى ملف secrets.toml.")
    else:
        client = genai.Client(api_key=API_KEY)
except Exception as e:
    st.error(f"خطأ غير متوقع أثناء التهيئة: {e}")
    client = None

# =================================================================
# 3. دالة التحليل الرئيسية
# =================================================================

def analyze_reverse_engagement(raw_comments, context):
    """
    يحلل التعليقات السلبية لتحديد النقاط العمياء (Blind Spots) في الرسالة أو المنتج.
    """
    if not client:
        return {"error": "فشل الاتصال بـ Gemini API."}
        
    system_prompt = (
        "أنت محلل تفاعل مضاد (Reverse Engagement Analyst) صارم وغير متحيز. "
        "مهمتك هي تجاهل الإيجابيات والتركيز حصريًا على التعليقات السلبية والأسئلة الصعبة "
        "لتشخيص وتحديد نقاط الضعف والفهم الخاطئ (النقاط العمياء) في رسالة العميل أو منتجه. "
        "يجب أن يكون الإخراج في تنسيق JSON حصراً يتبع المخطط المحدد بدقة."
    )

    prompt = f"""
    إليك مجموعة من التعليقات السلبية/الأسئلة الصعبة التي تم جمعها من تفاعل الجمهور. 
    التحليل يهدف لتحديد أين أخطأ المنتج أو الرسالة في التواصل.
    
    **السياق الإضافي (لمحة عن المنتج/الرسالة):** {context}

    **التعليقات الخام (Raw Comments):**
    ---
    {raw_comments}
    ---

    **المهام:**
    1.  **BlindSpotCategories:** تحديد 3 إلى 5 فئات رئيسية متكررة تسبب الإحباط أو سوء الفهم (مثل: التسعير غير واضح، صعوبة الاستخدام، وعد غير حقيقي، غياب خاصية معينة).
    2.  **CoreBlindSpot:** تحديد نقطة الضعف الأكثر أهمية أو ضرراً على المدى الطويل.
    3.  **ActionableInsights:** اقتراح 3-5 خطوات تنفيذية مباشرة لمعالجة نقطة الضعف الأساسية (CoreBlindSpot).
    4.  **SentimentSummary:** تلخيص سريع لأقوى المشاعر السلبية الظاهرة في التعليقات (إحباط، شك، غضب، ارتباك).
    """
    
    # مخطط JSON لضمان مخرجات منظمة
    response_schema = {
        "type": "OBJECT",
        "properties": {
            "BlindSpotCategories": {
                "type": "ARRAY",
                "description": "3-5 فئات رئيسية للضعف أو سوء الفهم.",
                "items": {"type": "STRING"}
            },
            "CoreBlindSpot": {
                "type": "STRING",
                "description": "أهم وأخطر نقطة ضعف تم اكتشافها."
            },
            "ActionableInsights": {
                "type": "ARRAY",
                "description": "3-5 خطوات تنفيذية لمعالجة المشكلة الأساسية.",
                "items": {"type": "STRING"}
            },
            "SentimentSummary": {
                "type": "STRING",
                "description": "ملخص للمشاعر السلبية المسيطرة."
            }
        },
        "propertyOrdering": ["BlindSpotCategories", "CoreBlindSpot", "ActionableInsights", "SentimentSummary"]
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

st.title("🔎 محلل التفاعل المضاد (Reverse Engagement Analyst)")

# === 🌟 الشرح التفصيلي للهدف (المحتوى الجديد) 🌟 ===
with st.expander("💡 شرح مفصل لهدف المنصة (النقطة العمياء)"):
    # استخدام HTML/Markdown مع التنسيق اليدوي لإصلاح المحاذاة
    st.markdown("""
        <div class="expander-content">
        
        ### الهدف الأساسي: اكتشاف "النقاط العمياء" التي تمنع النمو

        في عالم التسويق والمحتوى، يركز الجميع على الإعجابات (Likes) والمشاركات (Shares). هذه المقاييس رائعة للغرور، لكنها نادراً ما تخبركِ **بأين تكمن المشكلة الحقيقية.**

        #### ما هي "النقطة العمياء"؟
        هي فجوة أو سوء فهم موجود بين ما **تظنين** أن جمهورك فهمه، وبين ما **فهموه بالفعل**.

        **مثال:**
        
        <ul style="list-style-type: none; padding-right: 0; margin-right: 0;">
            <li> • ما تظنينه (الإيجابيات): "منتجي رخيص وسهل الاستخدام!" (هذا ما سيؤدي إلى الإعجاب).</li>
            <li> • ما يظنه الجمهور (السلبيات): "التسعير غالي، لأنني لم أفهم القيمة التي أحصل عليها مقارنةً بـ $100، ورسالتك لم تشرح الفرق." (هذا ما سيؤدي إلى تعليق سلبي/صعب).</li>
        </ul>

        #### دور التطبيق
        تطبيق "محلل التفاعل المضاد" يتجاهل الإيجابيات، ويعمل كـ "منقب" عن هذا الذهب السلبي. إنه يقوم بثلاثة أمور رئيسية:
        
        <ul style="list-style-type: disc; padding-right: 15px; margin-right: 0;">
            <li>التجميع والفرز: يجمع كل الشكاوى والأسئلة الصعبة في مكان واحد.</li>
            <li>تشخيص الضعف: يحلل التعليقات ليرى ما هي الفئة الأكثر تكراراً التي تسبب الإحباط (هل هي التسعير؟ الجودة؟ سوء الفهم للرسالة؟).</li>
            <li>التحويل إلى خطة: يحول هذا النقد السلبي إلى **خطوات تنفيذية (Actionable Insights)** يجب اتخاذها. بدلاً من أن تقولي "علينا أن نكون أفضل"، يقول لكِ: "عليكِ إضافة صفحة مبيعات تشرح بوضوح ميزة (X) لمواجهة سوء فهم التسعير."</li>
        </ul>

        **باختصار:** الهدف هو تحويل النقد من مصدر إزعاج إلى **خارطة طريق واضحة جداً** لتحسين المنتج، وتعديل الرسالة التسويقية، وبالتالي ضمان نمو حقيقي ومستدام.
        
        </div>
    """, unsafe_allow_html=True)

st.markdown("---")

# مساعدة المستخدم بمثال
example_comments = """
السعر مبالغ فيه جداً مقابل الميزات المتاحة. المنافس يقدم نفس الخصائص بنصف المبلغ.
لماذا لا يوجد دعم فني مباشر؟ الإيميلات لا تكفي لحل مشاكلي الفورية.
لقد وعدتم بأن المنتج يعمل على جميع الأجهزة القديمة، لكنه لا يعمل على جهازي اللوحي. هذا إعلان مضلل!
الواجهة معقدة جداً، أحتاج 3 خطوات لأصل إلى إعداد بسيط. يجب تبسيط العملية.
أين أجد سياسة الاسترجاع؟ لم يتم ذكرها بوضوح في صفحة الشراء.
"""

context = st.text_input(
    "لمحة عن المنتج/الرسالة (السياق):", 
    placeholder="مثلاً: نحن نقدم برنامج اشتراك شهري لتحسين الإنتاجية.",
    key="context_input"
)
st.markdown('<div class="rtl-caption">قدم وصفاً مختصراً للمنتج أو الخدمة لضمان تحليل أدق.</div>', unsafe_allow_html=True)

raw_comments = st.text_area(
    "التعليقات السلبية/الأسئلة الصعبة (الصقها هنا):", 
    placeholder=example_comments,
    height=300,
    key="comments_input"
)
st.markdown('<div class="rtl-caption">انسخ والصق مجموعة من التعليقات أو الملاحظات التي تشير إلى شكاوى، ارتباك، أو أسئلة تحدي.</div>', unsafe_allow_html=True)

if st.button("🚨 تحليل النقاط العمياء الآن", width='stretch'):
    if not raw_comments:
        st.warning("الرجاء لصق التعليقات لبدء التحليل.")
        st.stop()
    
    with st.spinner("جاري تحليل التفاعل المضاد وتشخيص نقاط الضعف..."):
        analysis_result = analyze_reverse_engagement(raw_comments, context)

    if analysis_result and "error" in analysis_result:
        st.error(f"فشل التحليل: {analysis_result['error']}")
    
    elif analysis_result:
        st.markdown("---")
        st.markdown("## 🛑 نتائج تحليل التفاعل المضاد")

        # ----------------------------------------------------
        # 1. أهم نقطة عمياء
        # ----------------------------------------------------
        with st.container():
            st.markdown('<div class="analysis-section">', unsafe_allow_html=True)
            st.markdown("<h3>🎯 Core Blind Spot (أخطر نقطة ضعف)</h3>", unsafe_allow_html=True)
            st.markdown(f'<p class="core-blind-spot"> {analysis_result.get("CoreBlindSpot", "غير محدد")} </p>', unsafe_allow_html=True)
            st.markdown('</div>', unsafe_allow_html=True)

        col_cat, col_sum = st.columns(2)
        
        # ----------------------------------------------------
        # 2. فئات الضعف الرئيسية
        # ----------------------------------------------------
        with col_cat:
            with st.container():
                st.markdown('<div class="analysis-section" style="background-color:#ffebeb; border: 2px solid #ff9999;">', unsafe_allow_html=True)
                st.markdown("<h3>🔍 Blind Spot Categories (فئات الضعف المتكررة)</h3>", unsafe_allow_html=True)
                categories = analysis_result.get("BlindSpotCategories", [])
                if categories:
                    for item in categories:
                         st.markdown(f'<p class="insight-item" style="color: #660000; font-weight: 500;"> {item} </p>', unsafe_allow_html=True)
                st.markdown('</div>', unsafe_allow_html=True)
        
        # ----------------------------------------------------
        # 3. ملخص المشاعر
        # ----------------------------------------------------
        with col_sum:
            with st.container():
                st.markdown('<div class="analysis-section" style="background-color:#ffebeb; border: 2px solid #ff9999;">', unsafe_allow_html=True)
                st.markdown("<h3>💔 Sentiment Summary (ملخص المشاعر السلبية)</h3>", unsafe_allow_html=True)
                summary = analysis_result.get("SentimentSummary", "غير محدد")
                st.info(summary)
                st.markdown('</div>', unsafe_allow_html=True)

        # ----------------------------------------------------
        # 4. خطوات تنفيذية
        # ----------------------------------------------------
        with st.container():
            st.markdown('<div class="analysis-section">', unsafe_allow_html=True)
            st.markdown("<h3>🛠️ Actionable Insights (خطوات تنفيذية فورية)</h3>", unsafe_allow_html=True)
            insights = analysis_result.get("ActionableInsights", [])
            if insights:
                for idx, item in enumerate(insights):
                    st.markdown(f'**{idx + 1}.** {item}')
            st.markdown('</div>', unsafe_allow_html=True)
            
# =================================================================
# 5. التذييل (Footer)
# =================================================================
# يتم حقن التذييل في HTML بعد عرض كل محتوى التطبيق
st.markdown(
    '<div class="custom-footer">جميع الحقوق محفوظة © 2026 | AI Product Creator - Layan Khalil</div>', 
    unsafe_allow_html=True
)