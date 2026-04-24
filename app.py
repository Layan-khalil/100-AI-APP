import streamlit as st
from google import genai
from google.genai import types as g_types
import json
import re

# =================================================================
# 1. إعدادات الصفحة والتنسيق (RTL & Professional UI)
# =================================================================

st.set_page_config(
    page_title="مُقيّم نضج الرد الاحترافي",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# قواعد CSS لفرض التنسيق والزر العريض والمحاذاة
st.markdown("""
<style>
    /* فرض اتجاه اليمين للغة العربية */
    html, body, .block-container, .stApp { direction: rtl !important; }
    h1, h2, h3, h4, h5, h6, p, .stMarkdown, .stText, .stAlert, label { text-align: right !important; direction: rtl !important; }

    /* محاذاة الـ Expander لليمين */
    div[data-testid="stExpander"] .stMarkdown p, 
    div[data-testid="stExpander"] .stMarkdown li {
        text-align: right !important;
        direction: rtl !important;
    }

    /* === تنسيق الزر العريض (Stretch) === */
    div.stButton > button { 
        font-weight: bold !important; 
        width: 100% !important; 
        background-color: #0ea5e9 !important; /* أزرق احترافي */
        color: white !important; 
        border-radius: 10px !important; 
        padding: 15px !important; 
        font-size: 1.2em !important; 
        border: none !important;
        box-shadow: 0 4px 15px rgba(14, 165, 233, 0.3) !important; 
        display: block !important;
        margin-top: 10px !important;
    }
    div.stButton > button:hover { 
        background-color: #0284c7 !important; 
        transform: translateY(-2px) !important; 
    }

    /* بطاقة النتائج */
    .maturity-card {
        background-color: #f0f9ff;
        padding: 25px;
        border-radius: 15px;
        border-right: 8px solid #0ea5e9;
        margin-top: 25px;
        text-align: right !important;
    }

    .score-badge {
        padding: 10px 20px;
        border-radius: 30px;
        font-weight: bold;
        font-size: 1.5em;
        display: inline-block;
        margin-bottom: 15px;
    }

    .custom-footer {
        position: fixed; bottom: 0; right: 0; left: 0;
        text-align: center; padding: 10px;
        background-color: #f8fafc; color: #64748b;
        font-size: 0.85em; border-top: 1px solid #e2e8f0; z-index: 100;
    }

    #MainMenu, footer, header { visibility: hidden; }
</style>
""", unsafe_allow_html=True)

# =================================================================
# 2. تهيئة نموذج Gemini
# =================================================================
client = None
try:
    # استخدام مفتاح فارغ للبيئة
    client = genai.Client(api_key="")
except Exception:
    client = None

# =================================================================
# 3. دالة تقييم النضج وإعادة الصياغة
# =================================================================

def score_response(draft):
    if not client:
        return {"error": "فشل الاتصال بالذكاء الاصطناعي."}

    system_instruction = (
        "You are a Corporate Communications Expert and Psychologist. "
        "Analyze the user's draft response to a criticism. "
        "1. Score the maturity from 1 to 100. "
        "2. Identify 'Emotional Traps' (e.g., defensiveness, passive-aggression). "
        "3. Provide a 'Mature Version' that is professional, firm, and non-reactive. "
        "Output ONLY in Arabic JSON."
    )

    # هيكل البيانات المطلوبة
    response_schema = {
        "type": "OBJECT",
        "properties": {
            "score": {"type": "NUMBER"},
            "level": {"type": "STRING"},
            "emotional_traps": {"type": "ARRAY", "items": {"type": "STRING"}},
            "mature_version": {"type": "STRING"},
            "why_change": {"type": "STRING"}
        },
        "required": ["score", "level", "emotional_traps", "mature_version", "why_change"]
    }

    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash-preview-09-2025',
            contents=f"حلل هذه المسودة: {draft}",
            config=g_types.GenerateContentConfig(
                system_instruction=system_instruction,
                response_mime_type="application/json",
                response_schema=response_schema
            )
        )
        return json.loads(response.text)
    except Exception as e:
        # آلية احتياطية في حال فشل الـ JSON المنظم
        return {"error": "حدث خطأ أثناء تحليل النص، يرجى المحاولة لاحقاً."}

# =================================================================
# 4. واجهة المستخدم
# =================================================================

st.title("⚖️ مُقيّم نضج الرد (Response Maturity Scorer)")
st.write("حول ردودك الاندفاعية إلى ردود احترافية رصينة تحفظ مكانتك.")

with st.expander("💡 لماذا تحتاج لهذه الأداة؟"):
    st.markdown("""
    <div style="text-align: right; direction: rtl;">
    في بيئة العمل أو المنصات العامة، الردود الاندفاعية غالباً ما تظهرنا بمظهر الضعيف أو غير المتزن. 
    هذه الأداة تساعدك على:
    <ul>
        <li>كشف المشاعر المكبوتة في كلماتك (كالعدوانية السلبية).</li>
        <li>قياس مدى احترافية الرد قبل إرساله.</li>
        <li>الحصول على صياغة 'باردة' وفعالة تنهي الجدال لصالحك.</li>
    </ul>
    </div>
    """, unsafe_allow_html=True)

st.markdown("---")

# منطقة الإدخال
draft_input = st.text_area(
    "اكتبي هنا مسودة الرد التي فكرتِ بها (أفرغي غضبك هنا!):", 
    placeholder="مثلاً: أنتم دائماً تتأخرون وتلقون باللوم علي، هذا غير عادل أبداً...",
    height=150
)

# الزر العريض
if st.button("🚀 تقييم النضج وإعادة الصياغة", use_container_width=True):
    if not draft_input.strip():
        st.warning("الرجاء إدخال نص المسودة أولاً.")
    else:
        with st.spinner("جاري تحليل النبرة العاطفية وقياس مستوى الاحترافية..."):
            result = score_response(draft_input)
            
            if "error" in result:
                st.error(result["error"])
            else:
                # عرض النتيجة
                score = result.get('score', 0)
                color = "#ef4444" if score < 50 else "#f59e0b" if score < 80 else "#10b981"
                
                st.markdown(f"""
                <div class="maturity-card">
                    <div style="text-align: center;">
                        <span class="score-badge" style="background-color: {color}; color: white;">
                            درجة النضج: {score}/100
                        </span>
                        <h4>المستوى: {result.get('level', '')}</h4>
                    </div>
                    <hr>
                    <p>⚠️ <b>الأفخاخ العاطفية المكتشفة:</b> {', '.join(result.get('emotional_traps', []))}</p>
                    <p>💡 <b>لماذا تم التغيير؟</b> {result.get('why_change', '')}</p>
                    <div style="background-color: white; padding: 15px; border-radius: 10px; border: 1px dashed #0ea5e9;">
                        <p>✅ <b>الرد الاحترافي المقترح:</b></p>
                        <p style="font-size: 1.1em; color: #1e293b;">{result.get('mature_version', '')}</p>
                    </div>
                </div>
                """, unsafe_allow_html=True)

st.markdown('<div style="height: 100px;"></div>', unsafe_allow_html=True)
st.markdown(
    '<div class="custom-footer">جميع الحقوق محفوظة © 2026 | AI Product Builder - Layan Khalil</div>', 
    unsafe_allow_html=True
)