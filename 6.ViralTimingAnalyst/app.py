import streamlit as st
from google import genai
from google.genai import types as g_types
from google.api_core.exceptions import ResourceExhausted, ServiceUnavailable, DeadlineExceeded
import json 
import time
import re

# =================================================================
# 1. إعدادات الصفحة و RTL/Responsive CSS
# =================================================================

st.set_page_config(
    page_title="مُحلّل توقيت الـ Viral",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# قواعد CSS لفرض RTL والتنسيق الأصلي (الزر العريض والنتائج)
st.markdown("""
<style>
    /* قواعد CSS الشاملة لـ RTL والتنسيق */
    html, body, .block-container, .stApp { direction: rtl !important; }
    h1, h2, h3, h4, h5, h6, p, .stMarkdown, .stText, .stAlert, label { text-align: right !important; direction: rtl !important; }

    /* === تنسيق محتوى الـ Expander ليكون محاذياً لليمين تماماً وبداية السطر === */
    div[data-testid="stExpander"] .stMarkdown p, 
    div[data-testid="stExpander"] .stMarkdown li,
    div[data-testid="stExpander"] .stMarkdown div,
    div[data-testid="stExpander"] label {
        text-align: right !important;
        direction: rtl !important;
        display: block;
        width: 100%;
    }

    /* === تنسيق الزر ليصبح بعرض الشاشة (Stretch) === */
    div.stButton > button { 
        font-weight: bold; 
        width: 100% !important; 
        background-color: #f97316; 
        color: white !important; 
        border-radius: 8px; 
        padding: 10px 20px; 
        font-size: 1.1em; 
        transition: all 0.3s ease; 
        box-shadow: 0 4px 15px rgba(249, 115, 22, 0.5); 
        display: block !important;
    }
    div.stButton > button:hover { 
        background-color: #ea580c; 
        box-shadow: 0 6px 20px rgba(249, 115, 22, 0.7); 
        transform: translateY(-2px); 
    }

    /* === تنسيق بطاقة النتيجة === */
    .analysis-card { 
        padding: 30px; border-radius: 12px; margin-top: 30px; 
        background-color: #fff7ed; 
        border-right: 8px solid #f97316; 
        box-shadow: 0 4px 12px rgba(0,0,0,0.15); 
    }
    .result-title { 
        font-size: 1.6em; font-weight: bold; color: #1e293b; margin-bottom: 20px; 
        border-bottom: 2px solid #fdba74; padding-bottom: 10px;
    }
    
    .time-prediction {
        background-color: #fef3c7; 
        color: #78350f; 
        padding: 15px;
        border-radius: 8px;
        font-size: 1.2em;
        font-weight: 700;
        margin-top: 20px;
        text-align: center !important;
        border: 2px solid #fcd34d;
    }
    
    .custom-footer {
        position: fixed;
        bottom: 0; right: 0; left: 0;
        width: 100%; text-align: center;
        padding: 10px 0; background-color: #f8f8f8;
        color: #64748b; font-size: 0.85em;
        border-top: 1px solid #e2e8f0; z-index: 100;
    }

    #MainMenu, footer, header { visibility: hidden; }
</style>
""", unsafe_allow_html=True)


# =================================================================
# 2. تهيئة نموذج Gemini (حصراً بالإصدار المتاح)
# =================================================================
client = None
MAX_RETRIES = 3
INITIAL_DELAY = 5

try:
    API_KEY = st.secrets.get("GEMINI_API_KEY", "")
    if API_KEY:
        client = genai.Client(api_key=API_KEY) 
except Exception:
    client = None

# =================================================================
# 3. دالة تحليل التوقيت
# =================================================================

def analyze_timing(topic, audience, content_type):
    if not client:
        return {"error": "فشل الاتصال بـ Gemini API."}, []

    # الموديل المدعوم حصراً في هذه البيئة للبحث هو gemini-2.5-flash-preview-09-2025
    model_name = 'gemini-2.5-flash-preview-09-2025'

    system_prompt = (
        "You are a specialized Viral Timing Analyst. Use Google Search data. "
        "Return ONLY a JSON object with: 'BestTimePrediction' (DayOfWeek, TimeWindow), 'AnalysisSummary', 'SearchQueryUsed'. "
        "Language: Arabic."
    )
    
    prompt = f"Best viral posting time for: Topic: {topic}, Audience: {audience}, Type: {content_type}. Search for latest trends."
    
    # لا نستخدم response_mime_type لتجنب التعارض مع أداة البحث (خطأ 400)
    config = g_types.GenerateContentConfig(
        system_instruction=system_prompt,
        tools=[{"google_search": {}}]
    )
    
    for attempt in range(MAX_RETRIES):
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=config 
            )
            
            raw_text = response.text.strip()
            # استخراج JSON يدوياً لتفادي أخطاء التنسيق
            json_match = re.search(r'({.*})', raw_text, re.DOTALL)
            if json_match:
                return json.loads(json_match.group(1)), []
            else:
                return json.loads(raw_text), []

        except (ResourceExhausted, ServiceUnavailable, DeadlineExceeded):
            if attempt < MAX_RETRIES - 1:
                time.sleep(INITIAL_DELAY * (attempt + 1))
                continue
            return {"error": "الخادم مشغول حالياً، يرجى المحاولة بعد دقيقة."}, []
        except Exception as e:
            return {"error": str(e)}, []

    return {"error": "فشل التحليل بعد عدة محاولات."}, []


# =================================================================
# 4. واجهة المستخدم
# =================================================================

st.title("⏱️ مُحلّل توقيت الـ Viral (الانتشار العالمي)")
st.subheader("يتوقع أفضل نافذة نشر من خلال تحليل توقيت انتشار المواضيع المُماثلة عالمياً.")

with st.expander("💡 التعليمات: كيف يعمل هذا المحلل؟"):
    st.markdown("""
        <div style="text-align: right; direction: rtl;">
        هذا الأداة تستخدم الذكاء الاصطناعي وبحث جوجل المباشر لـ:
        <ol>
            <li>البحث عن المحتوى الشائع والمنتشر <b>مؤخراً</b> في نطاق موضوعك.</li>
            <li>تحليل <b>التوقيت الزمني</b> لنشر تلك المواضيع الناجحة.</li>
            <li>استخلاص نافذة زمنية موحدة بالاعتماد على التوقيت العالمي (GMT+0).</li>
        </ol>
        </div>
    """, unsafe_allow_html=True)

st.markdown("---")

col1, col2 = st.columns(2)
with col1:
    topic = st.text_input("1. الموضوع:", placeholder="مثلاً: ريادة الأعمال")
with col2:
    audience = st.text_input("2. الجمهور (اختياري):", placeholder="مثلاً: جيل زد")

content_type = st.selectbox(
    "3. نوع المحتوى:",
    ("مقال/منشور طويل (LinkedIn/Blog)", "فيديو قصير (Reels/TikTok)", "إنفوجرافيك/صورة ثابتة", "سلسلة تغريدات (X)", "بودكاست")
)

# الزر بعرض الشاشة
if st.button("🚀 تحليل التوقيت الفيروسي العالمي"):
    if not topic.strip():
        st.warning("الرجاء إدخال الموضوع.")
    else:
        with st.spinner("جاري البحث والتحليل العالمي... يرجى الانتظار"):
            analysis_data, _ = analyze_timing(topic.strip(), audience.strip(), content_type)

        if "error" in analysis_data:
            st.error(f"فشل التحليل: {analysis_data['error']}")
        elif analysis_data:
            prediction = analysis_data.get("BestTimePrediction", {})
            st.markdown(f"""
            <div class="time-prediction">
                اليوم المُوصى به: {prediction.get("DayOfWeek", "-")} | النافذة: {prediction.get("TimeWindow", "-")}
            </div>
            """, unsafe_allow_html=True)

            st.markdown('<div class="result-title">شرح وتحليل التوقيت</div>', unsafe_allow_html=True)
            st.write(analysis_data.get("AnalysisSummary", ""))
            st.info(f"استعلام البحث المستخدم: {analysis_data.get('SearchQueryUsed', '---')}")

st.markdown(
    '<div class="custom-footer">جميع الحقوق محفوظة © 2026 | AI Product Creator - Layan Khalil</div>', 
    unsafe_allow_html=True
)