import streamlit as st
from google import genai
from google.genai import types
from google.api_core.exceptions import ResourceExhausted, ServiceUnavailable, DeadlineExceeded
import json
import time
import re

# =========================================================
# 1️⃣ PAGE CONFIG
# =========================================================
st.set_page_config(
    page_title="Viral Timing Analyst",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# =========================================================
# 2️⃣ LANGUAGE SWITCH
# =========================================================
if "ui_lang" not in st.session_state:
    st.session_state["ui_lang"] = "AR"

lang_toggle = st.toggle("English", value=(st.session_state["ui_lang"] == "EN"))
st.session_state["ui_lang"] = "EN" if lang_toggle else "AR"
IS_EN = st.session_state["ui_lang"] == "EN"

DIR = "ltr" if IS_EN else "rtl"
ALIGN = "left" if IS_EN else "right"

# =========================================================
# 3️⃣ CSS (نفس نمط أدواتك)
# =========================================================
st.markdown(f"""
<style>

#MainMenu {{visibility:hidden;}}
footer {{visibility:hidden;}}
header {{visibility:hidden;}}

html, body, .stApp {{
    direction:{DIR};
    text-align:{ALIGN};
}}

h1,h2,h3,h4,p,label {{
    direction:{DIR};
    text-align:{ALIGN};
}}

.stButton > button {{
    background:#e63946;
    color:white;
    font-weight:800;
    width:100%;
    border-radius:28px;
    height:3.2em;
}}

.time-box {{
    background:#fff7ed;
    border-right:6px solid #f97316;
    padding:18px;
    border-radius:12px;
    font-size:18px;
    font-weight:700;
    text-align:center;
}}

.result-box {{
    border:1px solid rgba(230,57,70,0.4);
    border-radius:16px;
    padding:16px;
    margin-top:12px;
}}

.footer-container {{
    width:100%;
    text-align:center;
    margin-top:50px;
    padding-top:20px;
    border-top:1px solid #666;
    font-size:13px;
}}

.testimonial-wrapper {{
  display:flex;
  gap:14px;
  overflow-x:auto;
  padding:10px;
}}

.testimonial-card {{
  min-width:300px;
  background:rgba(255,255,255,0.04);
  border:1px solid rgba(255,255,255,0.15);
  border-left:5px solid #e63946;
  border-radius:14px;
  padding:14px;
  text-align:center;
  direction:ltr;
}}

</style>
""", unsafe_allow_html=True)

# =========================================================
# 4️⃣ GEMINI INIT
# =========================================================
client = None
try:
    API_KEY = st.secrets.get("GEMINI_API_KEY","")
    if API_KEY:
        client = genai.Client(api_key=API_KEY)
except:
    client = None

MODEL_NAME = "gemini-1.5-flash"

# =========================================================
# 5️⃣ ANALYSIS FUNCTION
# =========================================================
def analyze_timing(topic, audience, content_type):

    if not client:
        return {"error":"API connection failed"}

    prompt = f"""
You are a viral timing analyst.

Return ONLY JSON:

{{
"BestTimePrediction": {{
"DayOfWeek":"",
"TimeWindow":""
}},
"AnalysisSummary":"",
"SearchQueryUsed":""
}}

Topic: {topic}
Audience: {audience}
Content type: {content_type}
"""

    cfg = types.GenerateContentConfig(
        temperature=0.6,
        max_output_tokens=1200
    )

    for _ in range(3):
        try:
            resp = client.models.generate_content(
                model=MODEL_NAME,
                contents=prompt,
                config=cfg
            )

            raw = resp.text.strip()
            match = re.search(r'{{.*}}', raw, re.DOTALL)
            if match:
                return json.loads(match.group())

        except (ResourceExhausted, ServiceUnavailable, DeadlineExceeded):
            time.sleep(2)

    return {"error":"Model error"}

# =========================================================
# 6️⃣ UI
# =========================================================

st.title("⏱️ Viral Timing Analyst" if IS_EN else "⏱️ مُحلّل توقيت الانتشار")

with st.expander("💡 How this tool works" if IS_EN else "💡 كيف تعمل الأداة"):
    if IS_EN:
        st.markdown("""
This tool analyzes when similar content performs best.

It helps you:
- Understand audience activity timing
- Publish when attention is highest
- Increase chances of engagement

Example:
AI content for creators often performs better Tuesday evenings.
""")
    else:
        st.markdown("""
هذه الأداة تحلل توقيت انتشار المحتوى المشابه لموضوعك.

تساعدك على:
- فهم أوقات نشاط الجمهور
- النشر في الوقت الذي يكون فيه الانتباه أعلى
- زيادة فرصة التفاعل

مثال:
محتوى الذكاء الاصطناعي غالباً يحقق تفاعل أعلى مساء الثلاثاء.
""")

st.markdown("---")

col1, col2 = st.columns(2)

topic = col1.text_input("Topic" if IS_EN else "الموضوع")
audience = col2.text_input("Audience (optional)" if IS_EN else "الجمهور (اختياري)")

content_type = st.selectbox(
    "Content Type" if IS_EN else "نوع المحتوى",
    ["LinkedIn Post","Short Video","Tweet","Image","Podcast"]
)

if st.button("Analyze 🚀" if IS_EN else "تحليل 🚀"):
    with st.spinner("Analyzing..." if IS_EN else "جاري التحليل..."):
        result = analyze_timing(topic,audience,content_type)

    if "error" in result:
        st.error(result["error"])
    else:
        pred = result["BestTimePrediction"]
        st.markdown(f"""
        <div class="time-box">
        {pred.get("DayOfWeek")} | {pred.get("TimeWindow")}
        </div>
        """, unsafe_allow_html=True)

        st.markdown("### Analysis" if IS_EN else "### شرح التحليل")
        st.write(result["AnalysisSummary"])

# =========================================================
# 7️⃣ TESTIMONIALS
# =========================================================
st.markdown("---")

st.markdown("""
<div class="testimonial-wrapper">
<div class="testimonial-card">
Great tool. Helped me rethink when I publish content.
<br><b>— Yousef Khalil</b>
</div>

<div class="testimonial-card">
Very useful insight for creators trying to improve reach.
<br><b>— Sally Daibes</b>
</div>

<div class="testimonial-card">
Simple idea but extremely practical.
<br><b>— Salem Khalil</b>
</div>
</div>
""", unsafe_allow_html=True)

# =========================================================
# 8️⃣ FEEDBACK
# =========================================================
st.markdown("---")

st.subheader("Feedback")

feedback = st.text_area("Your feedback...")
if st.button("Submit"):
    st.success("Thank you for your feedback!")

# =========================================================
# 9️⃣ FOOTER
# =========================================================
st.markdown("""
<div class="footer-container">
جميع الحقوق محفوظة © 2026 | AI Product Builder - Layan Khalil
</div>
""", unsafe_allow_html=True)
