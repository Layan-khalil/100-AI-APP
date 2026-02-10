import streamlit as st
from google import genai
from google.genai import types 
# استيراد الأخطاء الصحيحة ومكتبة time للانتظار
from google.api_core.exceptions import ResourceExhausted, ServiceUnavailable, DeadlineExceeded 
import json 
from pandas import DataFrame 
import time # تم إضافة هذا الاستيراد للانتظار بين المحاولات

# تعريف ثوابت إعادة المحاولة
MAX_RETRIES = 3
INITIAL_DELAY = 5 # ثواني انتظار أولية

# =================================================================
# 1. إعدادات الصفحة و RTL/Responsive CSS
# =================================================================

st.set_page_config(
    page_title=" وثيقة الشخصية الرقمية ",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# قواعد CSS الشاملة لفرض RTL على كل عناصر Streamlit وإضافة تنسيق الـ Footer
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
    
    /* استهداف أزرار التفاعل (Responsive) */
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

    /* تنسيق خاص لأقسام الـ Persona */
    .persona-section {
        background-color: #ffffff;
        padding: 20px;
        border-radius: 12px;
        margin-bottom: 25px;
        border: 1px solid #e0e0e0;
        box-shadow: 0 4px 12px rgba(0,0,0,0.05);
    }
    .persona-section h3 {
        color: #004d99; /* لون أزرق غامق للعناوين الفرعية */
        text-align: right !important;
        border-bottom: 3px solid #007bff; /* خط تحت العنوان */
        padding-bottom: 5px;
        margin-top: 0;
        margin-bottom: 15px;
        font-weight: 700;
    }
    .list-item {
        margin-bottom: 5px;
        padding-right: 15px;
        position: relative;
    }
    .list-item::before {
        content: '•';
        color: #007bff;
        font-weight: bold;
        display: inline-block;
        width: 1em;
        margin-right: -1em;
        position: absolute;
        right: 0;
    }

    /* حل مشكلة st.caption */
    .rtl-caption {
        direction: rtl !important;
        text-align: right !important;
        margin-top: -15px; 
        font-size: 0.9em; 
        color: rgba(49, 51, 63, 0.6); 
    }
    
    /* تنسيق حقوق النشر (الـ Footer) */
    .footer {
        position: fixed;
        left: 0;
        bottom: 0;
        width: 100%;
        background-color: #f0f2f6; 
        color: #808080;
        text-align: center !important; 
        padding: 5px;
        font-size: 0.75em;
        border-top: 1px solid #e0e0e0;
        z-index: 100;
    }
</style>
""", unsafe_allow_html=True)


# =================================================================
# 2. تهيئة نموذج Gemini 
# =================================================================
client = None
try:
    API_KEY = st.secrets.get("GEMINI_API_KEY", "")
    if not API_KEY:
        st.warning("⚠️ لم يتم العثور على مفتاح GEMINI_API_KEY. يرجى إضافته إلى ملف secrets.toml.")
    else:
        # تهيئة بسيطة للعميل
        client = genai.Client(api_key=API_KEY)
except Exception as e:
    st.error(f"خطأ غير متوقع أثناء التهيئة: {e}")
    client = None

# =================================================================
# 3. دالة توليد شخصية المؤثر (Persona) مع آلية إعادة المحاولة
# =================================================================

def generate_influencer_persona(field, goal, audience):
    """
    يستخدم Gemini لبناء وثيقة شخصية رقمية متكاملة بـ 8 أقسام.
    تستخدم آلية إعادة المحاولة للتعامل مع أخطاء المهلة والضغط (503/429).
    """
    if not client:
        return {"error": "فشل الاتصال بـ Gemini API. يرجى التحقق من المفتاح."}
        
    system_prompt = (
        "أنت استراتيجي علامات تجارية رقمية من الطراز الأول. مهمتك هي إنشاء وثيقة "
        "شخصية (Persona) شاملة تتجاوز الوصف السطحي، لتكون خارطة طريق للنمو الرقمي "
        "على مدار 90 يوماً وتحدد الهوية المستقبلية بعد 6 أشهر. "
        "يجب أن يكون الإخراج في تنسيق JSON حصراً يتبع المخطط المحدد بدقة."
    )

    prompt = f"""
    يرجى توليد وثيقة شخصية رقمية متكاملة بـ 8 أقسام بناءً على المعايير التالية:

    1. **مجال العمل/التخصص:** {field}
    2. **الهدف الرئيسي للمؤثر:** {goal}
    3. **الجمهور المستهدف (التفصيلي):** {audience}

    **التعليمات الخاصة بالتوليد:**
    - يجب أن تكون الأقسام 6 و 7 و 8 (الخطة، التطوير، التحول) قابلة للتنفيذ وعملية جداً.
    - يجب أن تكون "قصة الأصل" (Section 2) مؤثرة وتحدد صراعاً واضحاً.
    - يجب توليد 30 منشوراً مختلفاً في القسم 6 (30 يوم، منشور واحد في كل يوم).
    - يجب أن يكون السبب في "لماذا يجب على الناس المتابعة" مقنعاً وواضحاً.
    """
    
    # مخطط JSON مفصل لضمان مخرجات منظمة لجميع الأقسام الـ 8
    response_schema = {
        "type": "OBJECT",
        "properties": {
            "section1": {
                "type": "OBJECT",
                "properties": {
                    "persona_name": {"type": "STRING", "description": "اسم الشخصية"},
                    "definition": {"type": "STRING", "description": "تعريف 3-4 جمل"},
                    "core_message": {"type": "STRING", "description": "الرسالة الجوهرية"},
                    "primary_purpose": {"type": "STRING", "description": "الغرض المهني الأساسي"}
                }
            },
            "section2": {
                "type": "OBJECT",
                "properties": {
                    "how_it_started": {"type": "STRING", "description": "كيف بدأت؟"},
                    "existential_questions": {"type": "STRING", "description": "الأسئلة الوجودية"},
                    "conflict": {"type": "STRING", "description": "الصراع"},
                    "turning_point": {"type": "STRING", "description": "نقطة التحول"}
                }
            },
            "section3": {
                "type": "OBJECT",
                "properties": {
                    "tone": {"type": "ARRAY", "items": {"type": "STRING"}},
                    "unique_vocabulary": {"type": "ARRAY", "items": {"type": "STRING"}},
                    "style": {"type": "ARRAY", "items": {"type": "STRING"}}
                }
            },
            "section4": {
                "type": "OBJECT",
                "properties": {
                    "content_types_to_publish": {"type": "ARRAY", "items": {"type": "STRING"}},
                    "prohibited_content": {"type": "ARRAY", "items": {"type": "STRING"}},
                    "formula": {"type": "STRING"}
                }
            },
            "section5": {
                "type": "OBJECT",
                "properties": {
                    "stage": {"type": "STRING"},
                    "fears": {"type": "STRING"},
                    "seeking": {"type": "STRING"},
                    "cry_about": {"type": "STRING"},
                    "risk": {"type": "STRING"}
                }
            },
            "section6": {
                "type": "ARRAY",
                "description": "خطة 30 يوم محتوى (بحد أقصى 30 عنصر)",
                "items": {
                    "type": "OBJECT",
                    "properties": {
                        "day": {"type": "INTEGER"},
                        "content_type": {"type": "STRING"},
                        "idea_summary": {"type": "STRING"},
                        "cta": {"type": "STRING"},
                        "platform": {"type": "STRING"}
                    }
                }
            },
            "section7": {
                "type": "OBJECT",
                "properties": {
                    "values_to_develop": {"type": "ARRAY", "items": {"type": "STRING"}},
                    "required_sources": {"type": "ARRAY", "items": {"type": "STRING"}},
                    "daily_habits": {"type": "ARRAY", "items": {"type": "STRING"}},
                    "skills_roadmap": {"type": "ARRAY", "items": {"type": "STRING"}},
                    "checkpoints": {"type": "ARRAY", "items": {"type": "STRING"}}
                }
            },
            "section8": {
                "type": "OBJECT",
                "properties": {
                    "after_6_months": {"type": "STRING"},
                    "new_identity": {"type": "STRING"},
                    "say_goodbye_to": {"type": "STRING"},
                    "why_follow": {"type": "STRING"}
                }
            }
        },
        "propertyOrdering": ["section1", "section2", "section3", "section4", "section5", "section6", "section7", "section8"]
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
                # تم حذف 'request_options' لتجنب الخطأ
            )
            # إذا نجحت، نرجع النتيجة
            return json.loads(response.text)

        # التقاط الأخطاء التي تحتاج لإعادة محاولة: الضغط (429) أو الخدمة غير متوفرة (503) أو انتهاء المهلة (DeadlineExceeded)
        except (ResourceExhausted, ServiceUnavailable, DeadlineExceeded) as e:
            if attempt < MAX_RETRIES - 1:
                delay = INITIAL_DELAY * (2 ** attempt) # تأخير متزايد: 5, 10, 20 ثانية...
                st.warning(f"⚠️ فشلت المحاولة {attempt + 1} بسبب ضغط الخادم (503/429/Timeout). سيتم إعادة المحاولة بعد {delay} ثواني...")
                time.sleep(delay)
            else:
                # إذا كانت هذه آخر محاولة
                st.error(f"خطأ بالتوليد (API): فشلت جميع المحاولات ({MAX_RETRIES}). يرجى المحاولة لاحقاً. التفاصيل: {e}")
                return {"error": str(e)}
        except Exception as e:
            # التقاط أي أخطاء أخرى غير متوقعة
            st.error(f"خطأ غير متوقع: {e}")
            return {"error": str(e)}

    # لن يتم الوصول إلى هذا السطر إلا إذا فشلت جميع المحاولات في Catch الأخطاء
    return {"error": "فشل غير محدد في توليد المحتوى بعد محاولات متعددة."}


# =================================================================
# 4. دالة مساعدة لعرض الأقسام المفصلة (للقوائم والجداول)
# =================================================================

def display_list_section(title, data):
    """عرض قسم يحتوي على قائمة أو عناصر رئيسية."""
    st.markdown(f"**{title}:**")
    if isinstance(data, list):
        for item in data:
            st.markdown(f'<p class="list-item">{item}</p>', unsafe_allow_html=True)
    elif isinstance(data, str):
        st.write(data)

# =================================================================
# 5. واجهة المستخدم (Streamlit UI)
# =================================================================

st.title("👤 منشئ شخصية المؤثر المتكاملة")
st.markdown('8 أقسام كاملة لتأسيس شخصية مؤثرة قادرة على بناء جمهور ونفوذ رقمي', unsafe_allow_html=True)
st.caption("يرجى تعبئة الحقول ببيانات حقيقية ذات معنى لتحقيق أفضل النتائج ! ")
st.markdown("---")
col1, col2 = st.columns(2)

with col1:
    field = st.text_input("مجال العمل/التخصص:", key="field_input_ui")
with col2:
    goal = st.text_input("الهدف من بناء الشخصية:", key="goal_input_ui")

audience = st.text_area("الجمهور المستهدف:", key="audience_input_ui")

if st.button("✨ توليد شخصية الآن", use_container_width=True):
    if not field or not goal or not audience:
        st.warning("املأ جميع الحقول 🙏")
    else:
        with st.spinner("جاري بناء وثيقة شخصية كاملة... قد تستغرق العملية وقتاً..."):
            persona = generate_influencer_persona(field, goal, audience)

        if persona and not "error" in persona:
            st.markdown("---")
            st.markdown("## ✅ وثيقة الشخصية الرقمية المتكاملة (8 أقسام)")

            # ----------------------------------------------------
            # 1. SECTION 1 — الهوية الأساسية
            # ----------------------------------------------------
            with st.container():
                st.markdown('<div class="persona-section">', unsafe_allow_html=True)
                st.markdown("<h3>🔥 SECTION 1 — الهوية الأساسية</h3>", unsafe_allow_html=True)
                id_data = persona.get('section1', {})
                st.write(f"**اسم الشخصية:** **{id_data.get('persona_name', 'غير محدد')}**")
                st.write(f"**من هي هذه الشخصية؟:** {id_data.get('definition', 'غير محدد')}")
                st.write(f"**الرسالة الجوهرية:** {id_data.get('core_message', 'غير محدد')}")
                st.write(f"**الغرض المهني الأساسي:** {id_data.get('primary_purpose', 'غير محدد')}")
                st.markdown('</div>', unsafe_allow_html=True)

            # ----------------------------------------------------
            # 2. SECTION 2 — Origin Story
            # ----------------------------------------------------
            with st.container():
                st.markdown('<div class="persona-section">', unsafe_allow_html=True)
                st.markdown("<h3>🔥 SECTION 2 — سرد أصل الشخصية (Origin Story)</h3>", unsafe_allow_html=True)
                origin_data = persona.get('section2', {})
                st.write(f"**كيف بدأت؟:** {origin_data.get('how_it_started', 'غير محدد')}")
                st.write(f"**الأسئلة الوجودية:** {origin_data.get('existential_questions', 'غير محدد')}")
                st.write(f"**الصراع (Conflict):** {origin_data.get('conflict', 'غير محدد')}")
                st.write(f"**نقطة التحول:** {origin_data.get('turning_point', 'غير محدد')}")
                st.markdown('</div>', unsafe_allow_html=True)
            
            # ----------------------------------------------------
            # 3. SECTION 3 & 4 (التواصل والإطار) - في أعمدة
            # ----------------------------------------------------
            col_comm, col_frame = st.columns(2)

            with col_comm:
                with st.container():
                    st.markdown('<div class="persona-section">', unsafe_allow_html=True)
                    st.markdown("<h3>🔥 SECTION 3 — خصائص التواصل واللغة</h3>", unsafe_allow_html=True)
                    comm_data = persona.get('section3', {})
                    display_list_section("النبرة", comm_data.get('tone', []))
                    display_list_section("مفردات خاصة", comm_data.get('unique_vocabulary', []))
                    display_list_section("الأسلوب", comm_data.get('style', []))
                    st.markdown('</div>', unsafe_allow_html=True)

            with col_frame:
                with st.container():
                    st.markdown('<div class="persona-section">', unsafe_allow_html=True)
                    st.markdown("<h3>🔥 SECTION 4 — Content Style Framework</h3>", unsafe_allow_html=True)
                    frame_data = persona.get('section4', {})
                    display_list_section("أنواع المحتوى المنشور", frame_data.get('content_types_to_publish', []))
                    display_list_section("المحتوى الممنوع نشره", frame_data.get('prohibited_content', []))
                    st.write(f"**الصيغة المُتبعة (Formula):** {frame_data.get('formula', 'قيمة + قصة + دعوة للتطبيق')}")
                    st.markdown('</div>', unsafe_allow_html=True)

            # ----------------------------------------------------
            # 4. SECTION 5 — Audience Journey
            # ----------------------------------------------------
            with st.container():
                st.markdown('<div class="persona-section">', unsafe_allow_html=True)
                st.markdown("<h3>🔥 SECTION 5 — Audience Journey (رحلة الجمهور)</h3>", unsafe_allow_html=True)
                audience_data = persona.get('section5', {})
                st.write(f"**الجمهور في أي مرحلة؟:** {audience_data.get('stage', 'غير محدد')}")
                st.write(f"**شو الذي يخاف منه؟:** {audience_data.get('fears', 'غير محدد')}")
                st.write(f"**شو اللي ببحث عنه؟:** {audience_data.get('seeking', 'غير محدد')}")
                st.write(f"**شو الذي سيبكي عليه؟ (المشاعر):** {audience_data.get('cry_about', 'غير محدد')}")
                st.write(f"**شو الذي يمكنه يخسره؟:** {audience_data.get('risk', 'غير محدد')}")
                st.markdown('</div>', unsafe_allow_html=True)

            # ----------------------------------------------------
            # 5. SECTION 6 — محتوى 30 يوم جاهز (جدول)
            # ----------------------------------------------------
            with st.expander("✨ اضغط هنا لمشاهدة خطة المحتوى الجاهزة لـ 30 يوم", expanded=False):
                st.markdown("<h3>🔥 SECTION 6 — محتوى 30 يوم جاهز (خطة النشر)</h3>", unsafe_allow_html=True)
                content_30_days = persona.get('section6', [])
                if content_30_days and isinstance(content_30_days, list) and content_30_days[0].get('day'):
                    df = DataFrame(content_30_days)
                    df.columns = ["اليوم", "نوع المحتوى", "ملخص الفكرة", "الدعوة للإجراء (CTA)", "المنصة المقترحة"]
                    st.dataframe(df.set_index('اليوم'), use_container_width=True)
                else:
                    st.warning("لم يتم توليد خطة محتوى الـ 30 يوم بشكل صحيح. (قد يكون خطأ مؤقتاً في API)")

            # ----------------------------------------------------
            # 6. SECTION 7 — برنامج تطوير الشخصية لمدة 90 يوم
            # ----------------------------------------------------
            with st.expander("🚀 اضغط هنا لمشاهدة برنامج تطوير الشخصية لـ 90 يوم", expanded=False):
                st.markdown("<h3>🔥 SECTION 7 — برنامج تطوير الشخصية لمدة 90 يوم</h3>", unsafe_allow_html=True)
                dev_data = persona.get('section7', {})
                
                if dev_data:
                    st.markdown("#### ⚡ القيم والمهارات")
                    display_list_section("قيم يجب أن تطورها", dev_data.get('values_to_develop', []))
                    display_list_section("مهارات لازم تطورها (Skills Roadmap)", dev_data.get('skills_roadmap', []))
                    
                    st.markdown("#### 📚 المصادر والعادات")
                    display_list_section("مصادر يجب أن تقرأها/تتابعها", dev_data.get('required_sources', []))
                    display_list_section("عادات يومية (Daily Habits)", dev_data.get('daily_habits', []))
                    display_list_section("Checkpoints كل أسبوع (قياس الأثر)", dev_data.get('checkpoints', []))

            # ----------------------------------------------------
            # 7. SECTION 8 — Personal Transformation Map
            # ----------------------------------------------------
            with st.container():
                st.markdown('<div class="persona-section">', unsafe_allow_html=True)
                st.markdown("<h3>🔥 SECTION 8 — Personal Transformation Map (خارطة التحول)</h3>", unsafe_allow_html=True)
                trans_data = persona.get('section8', {})
                st.write(f"**🧠 كيف سيصبح بعد 6 شهور؟:** {trans_data.get('after_6_months', 'غير محدد')}")
                st.write(f"**🧠 ما هي هويته الجديدة؟:** {trans_data.get('new_identity', 'غير محدد')}")
                st.write(f"**🧠 ما الذي سيودعُه؟:** {trans_data.get('say_goodbye_to', 'غير محدد')}")
                
                st.markdown("---")
                st.write(f"**⭐ النتيجة النهائية: لماذا يجب على الناس المتابعة؟** {trans_data.get('why_follow', 'غير محدد')}")
                st.markdown('</div>', unsafe_allow_html=True)

        elif persona and "error" in persona:
             # الرسالة ستظهر من دالة generate_influencer_persona
            pass
            
# 8. حقوق النشر (الـ Footer)
st.markdown(
    '<div class="footer">جميع الحقوق محفوظة © 2026 | AI Product Creator - Layan Khalil</div>',
    unsafe_allow_html=True
)