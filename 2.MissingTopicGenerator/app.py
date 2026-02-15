import streamlit as st
import uuid
import hashlib
import os
import time
import re
import pandas as pd

from supabase import create_client, Client
from google import genai
from google.genai import types

# =========================================================
# 0) Page config
# =========================================================
st.set_page_config(
    page_title="منشئ المحتوى المفقود",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# =========================================================
# 1) Language switch
# =========================================================
if "ui_lang" not in st.session_state:
    st.session_state["ui_lang"] = "AR"

lang_choice = st.toggle("English", value=(st.session_state["ui_lang"] == "EN"))
st.session_state["ui_lang"] = "EN" if lang_choice else "AR"
IS_EN = (st.session_state["ui_lang"] == "EN")

DIR = "ltr" if IS_EN else "rtl"
ALIGN = "left" if IS_EN else "right"

# =========================================================
# 2) Secrets & Clients
# =========================================================
SUPABASE_URL = st.secrets.get("SUPABASE_URL") or os.environ.get("SUPABASE_URL")
SUPABASE_KEY = st.secrets.get("SUPABASE_KEY") or os.environ.get("SUPABASE_KEY")
GOOGLE_API_KEY = st.secrets.get("GOOGLE_API_KEY") or os.environ.get("GOOGLE_API_KEY")

if not all([SUPABASE_URL, SUPABASE_KEY, GOOGLE_API_KEY]):
    st.error("⚠️ Missing API Keys in Secrets.")
    st.stop()

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
genai_client = genai.Client(api_key=GOOGLE_API_KEY)
APP_ID = "missing-topic-generator"

# =========================================================
# 3) Helper Functions (FIXED PARSING)
# =========================================================

def get_content_hash(text: str) -> str:
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()

def parse_gap_response(raw: str):
    """
    تحليل النص الخام المسترجع من AI وضمان استخراج الملخص والمواضيع بدقة.
    """
    if not raw:
        return "", []

    summary = ""
    topics = []
    
    # استخراج الملخص باستخدام البحث عن الكلمة المفتاحية SUMMARY
    summary_match = re.search(r"SUMMARY:(.*?)(?=TOPICS:|$)", raw, re.DOTALL | re.IGNORECASE)
    if summary_match:
        summary = summary_match.group(1).strip()

    # استخراج المواضيع: نبحث عن الأسطر التي تبدأ برقم تليها النقاط
    # الصيغة المتوقعة: 1. العنوان || السبب || القالب
    topic_lines = re.findall(r"^\d+\.\s*(.*)", raw, re.MULTILINE)
    
    for line in topic_lines:
        parts = [p.strip() for p in line.split("||")]
        if len(parts) >= 3:
            topics.append({
                "topic_title": parts[0],
                "gap_reason": parts[1],
                "format_suggestion": " || ".join(parts[2:])
            })
            
    return summary, topics

def get_or_create_gap_analysis(my_posts, competitor_posts):
    """
    إرجاع النتيجة كاملة (الملخص + المواضيع + الكاش) لضمان عدم حدوث ValueError.
    """
    combined_text = f"{my_posts}\n---\n{competitor_posts}"
    content_hash = get_content_hash(combined_text)

    # 1. محاولة القراءة من الكاش
    try:
        res = supabase.table("viral_scores_cache").select("analysis_text").eq("app_id", APP_ID).eq("content_hash", content_hash).limit(1).execute()
        if res.data:
            s, t = parse_gap_response(res.data[0]["analysis_text"])
            return s, t, True
    except: pass

    # 2. استدعاء الموديل في حال عدم وجود كاش
    prompt = f"""
    أنت خبير استراتيجية محتوى. قارن بين منشورات العميل ومنشورات المنافسين.
    العميل: {my_posts}
    المنافسون: {competitor_posts}
    
    أعطني النتيجة بالصيغة التالية تماماً:
    SUMMARY: (اكتب هنا ملخص الفجوة في سطرين)
    TOPICS:
    1. العنوان المقترح || سبب الأهمية || شكل المحتوى (ريلز، بوست، الخ)
    2. العنوان المقترح || سبب الأهمية || شكل المحتوى
    ... وهكذا لـ 5 مواضيع.
    """
    
    try:
        response = genai_client.models.generate_content(
            model="gemini-1.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(temperature=0.4)
        )
        raw_text = response.text
        
        # حفظ في الكاش
        supabase.table("viral_scores_cache").insert({
            "app_id": APP_ID,
            "content_hash": content_hash,
            "analysis_text": raw_text
        }).execute()
        
        s, t = parse_gap_response(raw_text)
        return s, t, False
    except Exception as e:
        st.error(f"Error: {str(e)}")
        return "", [], False

# =========================================================
# 4) UI Layout
# =========================================================
st.markdown(f"<style>body {{ direction: {DIR}; text-align: {ALIGN}; }}</style>", unsafe_allow_html=True)

st.title("🧩 منشئ المحتوى المفقود")
col1, col2 = st.columns(2)

with col1:
    my_input = st.text_area("✍️ منشوراتك الأخيرة:", height=200)
with col2:
    comp_input = st.text_area("📌 منشورات المنافسين:", height=200)

if st.button("🎯 تحليل الفجوات واقتراح المواضيع"):
    if my_input and comp_input:
        with st.spinner("جاري التحليل..."):
            # تفكيك 3 قيم لضمان عدم حدوث الخطأ (Expected 2)
            summary, topics, was_cached = get_or_create_gap_analysis(my_input, comp_input)
            
            st.session_state["res_sum"] = summary
            st.session_state["res_top"] = topics
            st.session_state["is_cached"] = was_cached
    else:
        st.warning("يرجى إدخال البيانات في كلا الحقلين.")

# عرض النتائج كاملة
if "res_sum" in st.session_state:
    st.markdown("---")
    st.subheader("📊 ملخص التحليل")
    st.info(st.session_state["res_sum"])
    
    if st.session_state["res_top"]:
        st.subheader("🧩 المواضيع المقترحة")
        df = pd.DataFrame(st.session_state["res_top"])
        df.columns = ["الموضوع", "السبب", "الشكل المقترح"]
        st.table(df) # استخدام Table لضمان ظهور النص كاملاً
    else:
        st.error("لم يتم العثور على مواضيع واضحة، حاول إضافة تفاصيل أكثر.")

st.markdown(f"<div style='text-align:center; padding:20px;'>جميع الحقوق محفوظة ©️ 2026 | Layan Khalil</div>", unsafe_allow_html=True)
