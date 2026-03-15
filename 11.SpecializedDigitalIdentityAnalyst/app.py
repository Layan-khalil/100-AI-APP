import streamlit as st
import os
import json
import time
import hashlib
from datetime import datetime, timezone

from supabase import create_client, Client
from postgrest.exceptions import APIError

from google import genai
from google.genai import types as g_types
from google.api_core.exceptions import ResourceExhausted, ServiceUnavailable, DeadlineExceeded


# =========================================================
# 0) PAGE CONFIG
# =========================================================

st.set_page_config(
    page_title="Digital Identity Analyzer",
    layout="wide",
    initial_sidebar_state="collapsed",
)

APP_ID = "11-digital-identity-analyzer"

MODEL_CANDIDATES = [
    "gemini-2.0-flash-001",
    "gemini-1.5-flash-001",
    "gemini-1.5-pro-001",
]

MAX_RETRIES = 4
INITIAL_DELAY = 3
CACHE_VERSION_TAG = "identity_v1"


# =========================================================
# 1) LANGUAGE SWITCH
# =========================================================

if "ui_lang" not in st.session_state:
    st.session_state["ui_lang"] = "AR"

lang_toggle = st.toggle("English", value=(st.session_state["ui_lang"] == "EN"))
st.session_state["ui_lang"] = "EN" if lang_toggle else "AR"

IS_EN = (st.session_state["ui_lang"] == "EN")


TXT = {
"title":"Digital Identity Analyzer" if IS_EN else "محلل الهوية الرقمية",
"sub":(
"Analyze the consistency between your content, visual branding and declared identity."
if IS_EN else
"تحليل التناسق بين محتواك وهويتك المعلنة والهوية البصرية."
),
"identity":"Your declared identity" if IS_EN else "هويتك المعلنة",
"goal":"Your content goal" if IS_EN else "هدف المحتوى",
"samples":"Content samples" if IS_EN else "عينات المحتوى",
"upload":"Upload profile screenshot" if IS_EN else "ارفع لقطة شاشة للحساب",
"btn":"Analyze identity" if IS_EN else "تحليل الهوية",
"result":"Analysis Result" if IS_EN else "نتيجة التحليل",
"matrix":"Consistency Matrix" if IS_EN else "مصفوفة التناسق",
"summary":"Observed Identity" if IS_EN else "الهوية الفعلية",
"strategy":"Strategic Adjustments" if IS_EN else "التعديلات الاستراتيجية",
"warn":"Fill all required fields" if IS_EN else "يرجى تعبئة كل الحقول",
"spinner":"Analyzing..." if IS_EN else "جاري التحليل",

"fb_title":"Feedback" if IS_EN else "الفيدباك",
"fb_q":"How was your experience?" if IS_EN else "كيف كانت تجربتك؟",
"fb_yes":"Useful tool" if IS_EN else "الأداة مفيدة",
"fb_no":"Not useful" if IS_EN else "الأداة غير مفيدة",
"fb_missing":"What was missing?" if IS_EN else "ما الذي كان ناقصاً؟",
"fb_exp":"Quick feedback" if IS_EN else "فيدباك سريع",
"fb_p1":"What problem were you trying to solve?" if IS_EN else "ما المشكلة التي حاولت حلها؟",
"fb_p2":"Did it help? Why?" if IS_EN else "هل ساعدتك؟ لماذا؟",
"fb_p3":"What would make this tool essential?" if IS_EN else "ما الذي سيجعل هذه الأداة ضرورية؟",
"fb_btn":"Submit feedback" if IS_EN else "إرسال الفيدباك",
"fb_warn":"Write at least one line." if IS_EN else "اكتب سطر واحد على الأقل",
"fb_ok":"Feedback saved" if IS_EN else "تم حفظ الفيدباك"
}


# =========================================================
# 2) SECRETS
# =========================================================

def get_secret(key):
    return st.secrets.get(key) or os.environ.get(key)

SUPABASE_URL = get_secret("SUPABASE_URL")
SUPABASE_KEY = get_secret("SUPABASE_KEY")
GOOGLE_API_KEY = get_secret("GOOGLE_API_KEY") or get_secret("GEMINI_API_KEY")

if not all([SUPABASE_URL, SUPABASE_KEY, GOOGLE_API_KEY]):
    st.error("Missing secrets")
    st.stop()

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
genai_client = genai.Client(api_key=GOOGLE_API_KEY)


# =========================================================
# 3) CACHE
# =========================================================

def make_hash(identity,goal,samples):

    payload=f"{CACHE_VERSION_TAG}||{identity}||{goal}||{samples}"

    return hashlib.sha256(payload.encode()).hexdigest()


def cache_get(hash_id):

    try:

        res=supabase.table("viral_scores_cache")\
        .select("analysis_text")\
        .eq("app_id",APP_ID)\
        .eq("content_hash",hash_id)\
        .limit(1).execute()

        data=res.data or []

        if data:
            txt=data[0]["analysis_text"]
            return json.loads(txt)

    except:
        pass

    return None


def cache_set(hash_id,payload):

    try:

        supabase.table("viral_scores_cache").upsert({

        "app_id":APP_ID,
        "content_hash":hash_id,
        "analysis_text":json.dumps(payload),
        "created_at":datetime.now(timezone.utc).isoformat()

        },on_conflict="app_id,content_hash").execute()

    except:
        pass


# =========================================================
# 4) MODEL PICKER
# =========================================================

def get_model():

    if "model_identity" in st.session_state:
        return st.session_state["model_identity"]

    for m in MODEL_CANDIDATES:

        try:

            genai_client.models.generate_content(model=m,contents="ping")

            st.session_state["model_identity"]=m

            return m

        except:
            continue

    return MODEL_CANDIDATES[0]


# =========================================================
# 5) MODEL CALL
# =========================================================

def analyze_identity(identity,goal,samples,image_part):

    prompt=f"""
Analyze digital identity.

Identity:
{identity}

Goal:
{goal}

Content:
{samples}

Return JSON:

ConsistencyMatrix
ObservedIdentitySummary
StrategicAdjustments
"""

    schema={
    "type":"OBJECT",
    "properties":{

    "ConsistencyMatrix":{
    "type":"OBJECT",
    "properties":{
    "Textual_Identity_Score":{"type":"STRING"},
    "Textual_Goal_Score":{"type":"STRING"},
    "Visual_Identity_Score":{"type":"STRING"},
    "Visual_Goal_Score":{"type":"STRING"}
    }
    },

    "ObservedIdentitySummary":{"type":"STRING"},
    "StrategicAdjustments":{"type":"STRING"}
    }

    }

    config=g_types.GenerateContentConfig(
    system_instruction="You are digital identity strategist",
    response_mime_type="application/json",
    response_schema=schema
    )

    contents=[image_part,g_types.Part(text=prompt)]

    for attempt in range(MAX_RETRIES):

        try:

            resp=genai_client.models.generate_content(
            model=get_model(),
            contents=contents,
            config=config
            )

            return json.loads(resp.text)

        except (ResourceExhausted,ServiceUnavailable,DeadlineExceeded):

            time.sleep(INITIAL_DELAY*(attempt+1))

    return {"error":"Model failed"}


# =========================================================
# 6) UI
# =========================================================

st.title(TXT["title"])
st.caption(TXT["sub"])

samples=st.text_area(TXT["samples"],height=200)

col1,col2=st.columns(2)

with col1:
    identity=st.text_area(TXT["identity"],height=120)

with col2:
    goal=st.text_area(TXT["goal"],height=120)

image=st.file_uploader(TXT["upload"],type=["png","jpg","jpeg"])


# =========================================================
# 7) BUTTON
# =========================================================

if st.button(TXT["btn"]):

    if not identity or not goal or not samples or not image:

        st.warning(TXT["warn"])

        st.stop()

    hash_id=make_hash(identity,goal,samples)

    cached=cache_get(hash_id)

    if cached:

        result=cached

    else:

        img=g_types.Part.from_bytes(
        data=image.getvalue(),
        mime_type=image.type
        )

        with st.spinner(TXT["spinner"]):

            result=analyze_identity(identity,goal,samples,img)

        cache_set(hash_id,result)

    if "error" in result:

        st.error(result["error"])

    else:

        matrix=result["ConsistencyMatrix"]

        st.markdown(f"### {TXT['matrix']}")

        st.json(matrix)

        st.markdown(f"### {TXT['summary']}")

        st.write(result["ObservedIdentitySummary"])

        st.markdown(f"### {TXT['strategy']}")

        st.write(result["StrategicAdjustments"])


# =========================================================
# 8) FEEDBACK (UPDATED)
# =========================================================

st.divider()

st.subheader(TXT["fb_title"])

feedback_choice = st.radio(
    TXT["fb_q"],
    (TXT["fb_yes"], TXT["fb_no"]),
    key=f"{APP_ID}_feedback_choice",
)

useful = (feedback_choice == TXT["fb_yes"])

missing_reason = None
if not useful:
    missing_reason = st.text_input(
        TXT["fb_missing"],
        max_chars=200,
        key=f"{APP_ID}_missing_reason",
    )

with st.expander(TXT["fb_exp"], expanded=False):

    problem_text = st.text_area(
        TXT["fb_p1"],
        max_chars=280,
        key=f"{APP_ID}_problem_text"
    )

    helpful_reason = st.text_area(
        TXT["fb_p2"],
        max_chars=280,
        key=f"{APP_ID}_helpful_reason"
    )

    must_use_text = st.text_area(
        TXT["fb_p3"],
        max_chars=280,
        key=f"{APP_ID}_must_use_text"
    )

    submit_feedback = st.button(
        TXT["fb_btn"],
        key=f"{APP_ID}_submit_feedback"
    )

    if submit_feedback:

        has_any_text = any(
            [
                (missing_reason or "").strip(),
                (problem_text or "").strip(),
                (helpful_reason or "").strip(),
                (must_use_text or "").strip(),
            ]
        )

        if (not useful) and (not has_any_text):
            st.warning(TXT["fb_warn"])

        else:
            try:

                supabase.rpc(
                    "submit_app_feedback",
                    {
                        "p_app_name": APP_ID,
                        "p_useful": useful,
                        "p_missing_reason": (missing_reason or "").strip() or None,
                        "p_problem_text": (problem_text or "").strip() or None,
                        "p_helpful_reason": (helpful_reason or "").strip() or None,
                        "p_must_use_text": (must_use_text or "").strip() or None,
                    },
                ).execute()

                st.success(TXT["fb_ok"])

            except APIError as e:
                try:
                    st.json(e.args[0])
                except:
                    st.write(str(e))

            except Exception as e:
                st.exception(e)


# =========================================================
# 9) FOOTER
# =========================================================

st.markdown(
"""
<div style="text-align:center;margin-top:40px;font-size:12px;">
© 2026 AI Product Builder - Layan Khalil
</div>
""",
unsafe_allow_html=True
)
