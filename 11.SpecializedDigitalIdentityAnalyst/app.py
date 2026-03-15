import streamlit as st
from google import genai
from google.genai import types as g_types
import json
import time
from google.api_core.exceptions import ResourceExhausted, ServiceUnavailable, DeadlineExceeded

# =========================================================
# Page Setup
# =========================================================

st.set_page_config(
    page_title="Digital Identity Analyzer",
    layout="wide"
)

# =========================================================
# RTL + Styling
# =========================================================

st.markdown("""
<style>

html, body, .stApp {
direction: rtl;
text-align: right;
}

.result-card{
background:#f0f9ff;
padding:25px;
border-radius:10px;
border-right:6px solid #0ea5e9;
margin-top:20px;
}

.score-high{background:#10b981;color:white;padding:5px 12px;border-radius:6px}
.score-medium{background:#f59e0b;color:white;padding:5px 12px;border-radius:6px}
.score-low{background:#ef4444;color:white;padding:5px 12px;border-radius:6px}

</style>
""", unsafe_allow_html=True)

# =========================================================
# Language Switch
# =========================================================

lang = st.radio(
"Language / اللغة",
["العربية","English"],
horizontal=True
)

TEXT = {
"العربية":{
"title":"🔬 محلل الهوية الرقمية",
"analyze":"🚀 بدء التحليل",
"identity":"هويتك / تخصصك",
"goal":"هدف المحتوى",
"samples":"عينات المحتوى",
"upload":"رفع لقطة شاشة",
"instructions":"💡 التعليمات"
},
"English":{
"title":"🔬 Digital Identity Analyzer",
"analyze":"🚀 Analyze",
"identity":"Your Identity",
"goal":"Content Goal",
"samples":"Content Samples",
"upload":"Upload Screenshot",
"instructions":"💡 Instructions"
}
}

T = TEXT[lang]

st.title(T["title"])

# =========================================================
# Instructions Expander
# =========================================================

with st.expander(T["instructions"]):

    st.markdown("""
Example structured input:

--- Post 1 ---
Type: Reel  
Engagement: High  
Text: Blockchain will reshape finance...

--- Post 2 ---
Type: Carousel  
Engagement: Medium  
Text: 5 lessons about startup growth...
""")

# =========================================================
# Inputs
# =========================================================

samples = st.text_area(T["samples"], height=200)

col1,col2 = st.columns(2)

with col1:
    identity = st.text_area(T["identity"], height=120)

with col2:
    goal = st.text_area(T["goal"], height=120)

image = st.file_uploader(
T["upload"],
type=["png","jpg","jpeg"]
)

# =========================================================
# Gemini Client
# =========================================================

client=None

try:
    API_KEY=st.secrets.get("GEMINI_API_KEY","")
    if API_KEY:
        client=genai.Client(api_key=API_KEY)
except:
    pass

# =========================================================
# Image helper
# =========================================================

def image_part(file):
    if file:
        return g_types.Part.from_bytes(
            data=file.getvalue(),
            mime_type=file.type
        )

# =========================================================
# Model Analysis
# =========================================================

def analyze(image,identity,goal,samples):

    if not client:
        return {"error":"API Key missing"}

    prompt=f"""

Analyze the digital identity.

Identity:
{identity}

Goal:
{goal}

Content samples:
{samples}

Return JSON:

ConsistencyMatrix
ObservedIdentitySummary
StrategicAdjustments

Scores must be:
عالي
متوسط
منخفض
"""

    contents=[image,g_types.Part(text=prompt)]

    response=client.models.generate_content(
        model="gemini-2.5-flash",
        contents=contents
    )

    txt=response.text.strip()

    try:
        return json.loads(txt)
    except:
        return {"error":txt}

# =========================================================
# Run Analysis
# =========================================================

if st.button(T["analyze"]):

    if not samples or not identity or not goal or not image:
        st.warning("Please fill all fields")
        st.stop()

    img=image_part(image)

    with st.spinner("Analyzing..."):
        result=analyze(img,identity,goal,samples)

    if "error" in result:
        st.error(result["error"])

    else:

        matrix=result["ConsistencyMatrix"]

        def score(s):
            if s=="عالي":
                return f'<span class="score-high">{s}</span>'
            if s=="متوسط":
                return f'<span class="score-medium">{s}</span>'
            return f'<span class="score-low">{s}</span>'

        st.markdown("## 📊 Consistency Matrix")

        st.markdown(f"""
<div class="result-card">

Text vs Identity: {score(matrix["Textual_Identity_Score"])}

Text vs Goal: {score(matrix["Textual_Goal_Score"])}

Visual vs Identity: {score(matrix["Visual_Identity_Score"])}

Visual vs Goal: {score(matrix["Visual_Goal_Score"])}

</div>
""",unsafe_allow_html=True)

        st.markdown("## 🧠 Identity Summary")

        st.write(result["ObservedIdentitySummary"])

        st.markdown("## 🚀 Strategic Adjustments")

        st.write(result["StrategicAdjustments"])

# =========================================================
# Feedback
# =========================================================

st.markdown("---")

st.subheader("Feedback")

rating=st.slider("Rate this tool",1,5)

feedback=st.text_area("Your feedback")

if st.button("Submit Feedback"):
    st.success("Thank you for your feedback!")
