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
    page_title=" فحص الازدحام الزمني",
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
    /* ------------------------------------ */
    
    .stTextArea {
        height: 150px !important; 
    }

    /* ---------------------------------
    *** تنسيق زر الإجراء (Button Styling) ***
    ----------------------------------- */
    .stButton>button {
        font-weight: bold;
        width: 100%; 
        direction: rtl !important;
        background-color: #059669; /* أخضر جذاب */
        color: white;
        border: none;
        border-radius: 8px;
        padding: 10px 20px;
        font-size: 1.1em;
        transition: all 0.3s ease;
        box-shadow: 0 4px 15px rgba(5, 150, 105, 0.4); 
    }
    .stButton>button:hover {
        background-color: #047857; 
        box-shadow: 0 6px 20px rgba(5, 150, 105, 0.6); 
        transform: translateY(-2px); 
    }
    
    /* ---------------------------------
    *** تنسيق بطاقات النتيجة ***
    ----------------------------------- */
    .result-card {
        padding: 20px;
        border-radius: 12px;
        margin-top: 20px;
        box-shadow: 0 6px 15px rgba(0,0,0,0.1);
    }
    .status-header {
        font-size: 1.5em;
        font-weight: bold;
        padding: 10px;
        border-radius: 6px;
        margin-bottom: 15px;
        text-align: center !important;
        color: white;
    }
    
    /* ألوان الحالة */
    .status-high { background-color: #dc2626; } /* أحمر */
    .status-medium { background-color: #f59e0b; } /* أصفر/برتقالي */
    .status-low { background-color: #10b981; } /* أخضر */

    .analysis-section {
        border-top: 1px solid #eee;
        padding-top: 15px;
        margin-top: 15px;
        /* التأكد من محاذاة كل النص في هذا القسم لليمين */
        text-align: right !important; 
        direction: rtl !important;
    }
    .analysis-section p {
        text-align: right !important;
        direction: rtl !important;
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
# 3. دالة فحص الازدحام الزمني 
# =================================================================

def check_saturation(content_idea, platform):
    """
    تستخدم نموذج Gemini مع Google Search Grounding لتحليل ازدحام الموضوع.
    تم إزالة الإخراج المُنظم JSON نهائياً لتجنب التعارض مع خاصية البحث، وإضافة فحص آمن لـ groundingMetadata.
    """
    if not client:
        return {"error": "فشل الاتصال بـ Gemini API."}, []

    # تعليمات النظام: تفرض إخراج JSON خام بدون أي إضافات، وهو الآن الطريقة الوحيدة لتمكين البحث
    system_prompt = (
        "Act as a professional Content Trend Analyst specializing in social media saturation. "
        "Your task is to analyze the user's content idea against recent online activity (using Google Search grounding). "
        "Determine the current saturation level of the topic on the specified platform (Low, Medium, or High). "
        "Provide a clear recommendation (Publish Now, Postpone, or Adapt) and a justification based on your analysis. "
        "The output MUST be a structured JSON object in Arabic, containing ONLY the keys: 'SaturationLevel', 'Recommendation', and 'Justification'. "
        "Do not include any introductory text, closing remarks, or Markdown code fences (```json or ```)."
    )

    # الاستعلام للمستخدم
    prompt = f"""
    قم بتحليل مستوى الازدحام (Saturation) للمحتوى المقترح التالي على المنصة المحددة.
    
    * **الفكرة/الموضوع:** {content_idea}
    * **المنصة المستهدفة:** {platform}
    
    اعتمد في تحليلك على الترندات والمنشورات الحديثة جداً التي تجدها عبر البحث.
    """
    
    # Configuration: يحتوي الآن على system_instruction و tools فقط
    config = types.GenerateContentConfig(
        system_instruction=system_prompt,
        tools=[{"google_search": {}}]
    )

    # حلقة إعادة المحاولة
    for attempt in range(MAX_RETRIES):
        try:
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt,
                config=config 
            )
            
            # Extract Grounding Sources (FIX: Use hasattr for safe access)
            sources = []
            if response.candidates and response.candidates[0]:
                candidate = response.candidates[0]
                # التحقق الآمن مما إذا كانت الخاصية موجودة قبل محاولة الوصول إليها
                if hasattr(candidate, 'groundingMetadata') and candidate.groundingMetadata:
                    sources = candidate.groundingMetadata.groundingAttributions
            
            # === JSON Sanitization and Parsing (CRUCIAL now) ===
            raw_text = response.text.strip()
            
            # إزالة علامات الكود ماركداون المحتملة إذا أخطأ النموذج
            if raw_text.startswith("```json"):
               if raw_text.endswith("```"):
                     raw_text = raw_text[:-len("```")].strip()
                
            # محاولة قراءة JSON
            try:
                if raw_text:
                    result = json.loads(raw_text)
                    return result, sources
                else:
                    return {"error": "استجابة النموذج كانت فارغة أو تم مسحها أثناء التنظيف."}, []
            except json.JSONDecodeError as json_err:
                # إذا فشل التحليل، نعرض النص الخام للمساعدة في التصحيح
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

st.title("🚦 فحص الازدحام الزمني للمحتوى")
st.subheader("تحليل ترندات النشر وتحديد التوقيت الأمثل لنجاح فكرتك.")

# === 🌟 الشرح التفصيلي للهدف ===
with st.expander("💡 كيف تعمل الأداة؟"):
    st.markdown("""
        تستخدم هذه الأداة **نموذج Gemini** لـ **البحث في جوجل (Grounding)** بشكل مباشر عن الترندات الحديثة والمنشورات الأخيرة المتعلقة بفكرتك ومقارنتها بالمنصة المستهدفة.
        
        **الهدف:** تحديد ما إذا كان الموضوع مُشبعاً (Over-saturated) أو "مُتعباً" للجمهور حالياً.
        
        **مستويات الازدحام والتوصيات:**
        
        * 🟢 **منخفض:** الموضوع غير مُغطى بكثرة حالياً. (انشر الآن)
        * 🟡 **متوسط:** يوجد اهتمام لكن يمكنك التميز بتعديل الزاوية. (عدّل الفكرة)
        * 🔴 **مرتفع:** الموضوع مُغطى بكثافة في هذه الفترة. (أجل النشر)
    """)

st.markdown("---")

# ----------------------------------------------------
# منطقة الإدخال
# ----------------------------------------------------
col1, col2 = st.columns([3, 1])

with col1:
    content_idea = st.text_area(
        "الفكرة/الموضوع الذي تريد فحصه:", 
        placeholder="مثلاً: تأثير الذكاء الاصطناعي التوليدي على وظائف المحاسبين في الربع الأخير.",
        height=100,
        key="content_idea_input"
    )

with col2:
    platform = st.selectbox(
        "المنصة المستهدفة:", 
        options=['LinkedIn', 'X (Twitter)', 'TikTok', 'Instagram', 'Facebook', 'المدونات والمقالات'],
        key="platform_select"
    )

# ----------------------------------------------------
# زر التشغيل
# ----------------------------------------------------
if st.button("🔍 فحص الازدحام الزمني الآن", width='stretch'):
    if not content_idea:
        st.warning("الرجاء إدخال فكرة المحتوى أولاً للمتابعة.")
        st.stop()
    
    with st.spinner("جاري تحليل الترندات الحديثة ومستويات الازدحام عبر الإنترنت... (قد يستغرق 10-15 ثانية)"):
        # استدعاء دالة التحليل
        analysis_data, sources = check_saturation(content_idea, platform)

    if analysis_data and "error" in analysis_data:
        st.error(f"فشل التحليل: {analysis_data['error']}")
    
    elif analysis_data:
        st.markdown("---")
        st.markdown("## 📊 نتائج تحليل الازدحام الزمني")

        # تعيين الحالة واللون
        level = analysis_data.get("SaturationLevel", "غير محدد")
        
        if level == "مرتفع":
            status_class = "status-high"
            status_emoji = "🔴"
        elif level == "متوسط":
            status_class = "status-medium"
            status_emoji = "🟡"
        else: # منخفض أو غير محدد
            status_class = "status-low"
            status_emoji = "🟢"

        # عرض بطاقة النتيجة
        st.markdown(f'<div class="result-card">', unsafe_allow_html=True)
        
        # عرض مستوى الازدحام والتوصية
        st.markdown(f'<div class="{status_class} status-header">{status_emoji} مستوى الازدحام: {level}</div>', unsafe_allow_html=True)
        st.info(f'**✅ التوصية:** {analysis_data.get("Recommendation", "لا توجد توصية.")}')
        
        # عرض التحليل والتبرير
        st.markdown('<div class="analysis-section">', unsafe_allow_html=True)
        st.markdown('**تفسير وتبرير التحليل:**')
        st.markdown(analysis_data.get("Justification", "لا يوجد تبرير من النموذج."))
        st.markdown('</div>', unsafe_allow_html=True)
        
        st.markdown('</div>', unsafe_allow_html=True)

        # عرض مصادر البحث المستخدمة (Grounding)
        if sources:
            st.markdown("---")
            st.markdown("#### 🌐 مصادر البحث المستخدمة:")
            source_list = ""
            for i, source in enumerate(sources):
                title = source.get('title', 'لا يوجد عنوان')
                uri = source.get('uri', '#')
                source_list += f'{i+1}. [{title}]({uri})\n'
            st.markdown(source_list)


# =================================================================
# 5. التذييل (Footer)
# =================================================================
st.markdown(
    '<div class="custom-footer">جميع الحقوق محفوظة © 2026 | AI Product Creator - Layan Khalil</div>', 
    unsafe_allow_html=True
)