import streamlit as st
import os
import json
import hashlib
import re
from supabase import create_client, Client
from google import genai
from google.genai import types
from postgrest.exceptions import APIError
import random
import time

# =========================================================
# 0) إعداد الصفحة
# =========================================================
st.set_page_config(page_title="وثيقة الشخصية الرقمية", layout="wide", initial_sidebar_state="collapsed")

# =========================================================
# ✅ 0.1) UI Language Switch (label flips like previous tools)
# =========================================================
if "ui_lang" not in st.session_state:
    st.session_state["ui_lang"] = "AR"

_current_lang = st.session_state["ui_lang"]
toggle_label = "English" if _current_lang == "AR" else "العربية"
lang_toggle = st.toggle(toggle_label, value=(_current_lang == "EN"))
st.session_state["ui_lang"] = "EN" if lang_toggle else "AR"
IS_EN = (st.session_state["ui_lang"] == "EN")

# =========================================================
# ✅ 0.2) Text dictionary (كل واجهة التطبيق + placeholders)
# =========================================================
TXT = {
    "title": "Integrated Digital Persona Document" if IS_EN else "👤 وثيقة الشخصية الرقمية المتكاملة",
    "btn_generate": "Generate persona" if IS_EN else "توليد الشخصية",
    "caption": (
        "Enter 3 inputs and get: persona + tone + a complete 30-day content plan + communication boundaries."
        if IS_EN
        else
        "اكتب 3 معلومات… واحصل على وثيقة Persona كاملة: هوية + نبرة + خطة محتوى 30 يوم + حدود تواصل."
    ),
    "exp_title": "What does this tool do?" if IS_EN else "ما الذي تفعله هذه الأداة؟",
    "exp_body": (
        "Most people create content without a clear identity, which causes inconsistent messaging.\n"
        "This tool generates a practical Persona document that acts as a reference for your identity, tone, and content direction.\n\n"
        "You will receive:\n"
        "• Persona name + short bio\n"
        "• Tone of voice + style + keywords\n"
        "• A complete 30-day content plan (day-by-day)\n"
        "• Communication boundaries (what to talk about / avoid, DM & comments policy)\n\n"
        "Example input:\n"
        "Field: Fitness coach\n"
        "Goal: Attract clients\n"
        "Audience: Busy women who want short workouts\n\n"
        "Example output (short):\n"
        "Name: The Busy Fit Coach\n"
        "Tone: Friendly, motivating\n"
        "Day 1: 30-sec Reel: “3-minute workout for busy days” + CTA: Save & follow\n\n"
        "Designed for creators, freelancers, founders, and anyone moving from random posting to a clear digital presence."
        if IS_EN
        else
        "معظم الناس تنشر محتوى بدون هوية واضحة، فيتغير الأسلوب وتضيع الرسالة.\n"
        "هذه الأداة تبني لك وثيقة Persona عملية تكون مرجع ثابت لهويتك ونبرة تواصلك واتجاه محتواك.\n\n"
        "ستحصل على:\n"
        "• اسم + نبذة شخصية\n"
        "• نبرة الصوت + أسلوب الكلام + كلمات مفتاحية\n"
        "• خطة محتوى كاملة لمدة 30 يوم (يوم بيوم)\n"
        "• حدود تواصل (شو تحكي/شو تتجنب + سياسة الرسائل والتعليقات)\n\n"
        "مثال إدخال:\n"
        "المجال: مدربة لياقة\n"
        "الهدف: جذب عملاء\n"
        "الجمهور: نساء مشغولات بدهم تمارين سريعة\n\n"
        "مثال مخرجات (مختصر):\n"
        "الاسم: مدربة اللياقة للنساء المشغولات\n"
        "النبرة: ودودة ومحفّزة\n"
        "اليوم 1: Reel 30 ثانية: “تمرين 3 دقائق لليوم المزدحم” + CTA: احفظي وتابعي\n\n"
        "مناسبة لصنّاع المحتوى، المستقلين، رواد الأعمال، وكل شخص يريد حضور رقمي واضح بدل النشر العشوائي."
    ),
    "field_label": "Specialization / Field" if IS_EN else "مجال العمل/التخصص",
    "goal_label": "Main goal" if IS_EN else "الهدف الأساسي",
    "aud_label": "Target audience description" if IS_EN else "وصف الجمهور المستهدف",
    "field_ph": "e.g., Emotional intelligence coach / AI educator / E-commerce consultant" if IS_EN else "مثال: مدرب ذكاء عاطفي / تعليم AI / مستشار تجارة إلكترونية",
    "goal_ph": "e.g., Build audience, attract clients, sell a service or course" if IS_EN else "مثال: بناء جمهور، جذب عملاء، بيع خدمة أو كورس",
    "aud_ph": "Describe who you want to reach: age, pain points, goals, platforms..." if IS_EN else "اكتب وصف تفصيلي: العمر، المشاكل، الأهداف، المنصات التي يستخدموها…",
    "warn_fill": "Please fill all fields." if IS_EN else "يرجى تعبئة كافة الحقول.",
    "wait": "Please wait a few seconds before trying again." if IS_EN else "يرجى الانتظار قليلاً قبل المحاولة مجدداً.",
    "spinner": "Generating persona and plan..." if IS_EN else "جاري توليد الشخصية والخطة...",
    "err": "Error:" if IS_EN else "حدث خطأ:",
    "res_title": "Result" if IS_EN else "النتيجة",
    "sec1": "Persona identity & core message" if IS_EN else "👤 الهوية والرسالة الأساسية",
    "name": "Suggested name" if IS_EN else "الاسم المقترح",
    "bio": "Short bio" if IS_EN else "النبذة التعريفية",
    "sec2": "Tone of voice & communication style" if IS_EN else "🗣️ نبرة الصوت وأسلوب التواصل",
    "tone": "Tone" if IS_EN else "النبرة",
    "style": "Style" if IS_EN else "الأسلوب",
    "keywords": "Voice keywords" if IS_EN else "كلمات نستخدمها",
    "sec3": "30-day content plan" if IS_EN else "📅 خطة المحتوى (30 يوماً)",
    "day": "Day" if IS_EN else "اليوم",
    "type": "Type" if IS_EN else "النوع",
    "platform": "Platform" if IS_EN else "المنصة",
    "cta": "CTA" if IS_EN else "CTA",
    "sec4": "Communication boundaries & policies" if IS_EN else "🛡️ حدود التواصل وسياسات القناة",
    "talk": "✅ Topics to focus on" if IS_EN else "✅ مواضيع نركز عليها",
    "avoid": "❌ Topics to avoid" if IS_EN else "❌ مواضيع نتجنبها",
    "dm": "📩 DM policy" if IS_EN else "📩 سياسة الرسائل",
    "comments": "💬 Comment policy" if IS_EN else "💬 سياسة التعليقات",

    "plain_title": "📄 Export as Plain Text" if IS_EN else "📄 تصدير كنص واحد",
    "plain_hint": "Copy the text below or download it as .txt" if IS_EN else "انسخي النص التالي أو حمّليه كملف .txt",
    "plain_btn": "Generate Plain Text" if IS_EN else "تجهيز النص الموحد",

    "fb_title": "Feedback" if IS_EN else "ساعدنا في تطوير الأداة",
    "fb_q": "How was your experience?" if IS_EN else "كيف كانت تجربتك مع هذه الأداة؟",
    "fb_yes": "This tool was useful for me" if IS_EN else "هذه الأداة كانت مفيدة بالنسبة لي",
    "fb_no": "This tool was not useful" if IS_EN else "هذه الأداة لم تكن مفيدة",
    "fb_missing": "What was missing? (one sentence)" if IS_EN else "ما الذي كان ناقصاً؟ (جملة واحدة)",
    "fb_exp": "Quick feedback (3 questions)" if IS_EN else "فيدباك سريع (3 أسئلة)",
    "fb_p1": "1) What problem were you trying to solve?" if IS_EN else "1) ما المشكلة التي كنت تحاول حلّها؟",
    "fb_p2": "2) Did it help? Why yes/no?" if IS_EN else "2) هل ساعدتك الأداة؟ لماذا نعم/لا؟",
    "fb_p3": "3) What would make this a must-use tool for you?" if IS_EN else "3) ما الذي سيجعل هذه الأداة «لازم تُستخدم» بالنسبة لك؟",
    "fb_btn": "Submit feedback" if IS_EN else "إرسال الفيدباك",
    "fb_warn": "Write at least one line." if IS_EN else "اكتب سطر واحد على الأقل 🙏",
    "fb_ok": "Feedback saved ✅ Thank you!" if IS_EN else "تم حفظ الفيدباك ✅ شكرًا لك!",
    "fb_err": "Supabase error:" if IS_EN else "خطأ من Supabase:",
}

# =========================================================
# 1) المفاتيح وتهيئة العميل
# =========================================================
def get_secret(key: str):
    return st.secrets.get(key) or os.environ.get(key)

SUPABASE_URL = get_secret("SUPABASE_URL")
SUPABASE_KEY = get_secret("SUPABASE_KEY")
GOOGLE_API_KEY = get_secret("GOOGLE_API_KEY")

if not all([SUPABASE_URL, SUPABASE_KEY, GOOGLE_API_KEY]):
    st.error("⚠️ Missing secrets in Secrets / Env." if IS_EN else "⚠️ مفاتيح الربط ناقصة في Secrets أو Env.")
    st.stop()

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
genai_client = genai.Client(api_key=GOOGLE_API_KEY)

# ✅ موديلات صحيحة
MODEL_CANDIDATES = [
    "gemini-2.0-flash-001",
    "gemini-1.5-flash-001",
    "gemini-1.5-pro-001",
]

def get_working_model():
    """تحديد الموديل المتاح وتخزينه لتجنب استهلاك الوقت في كل محاولة"""
    if "working_model" in st.session_state:
        return st.session_state["working_model"]

    for m in MODEL_CANDIDATES:
        try:
            genai_client.models.generate_content(
                model=m,
                contents="test",
                config=types.GenerateContentConfig(max_output_tokens=1),
            )
            st.session_state["working_model"] = m
            return m
        except Exception:
            continue

    st.session_state["working_model"] = MODEL_CANDIDATES[0]
    return MODEL_CANDIDATES[0]

# =========================================================
# ✅ حماية من النقر المتكرر + Retry
# =========================================================
def can_call_model(min_seconds: int = 12) -> bool:
    now = time.time()
    last = st.session_state.get("last_model_call_ts", 0.0)
    if (now - last) < min_seconds:
        return False
    st.session_state["last_model_call_ts"] = now
    return True

def call_model_with_retry(model: str, prompt: str, cfg: types.GenerateContentConfig, retries: int = 4) -> str:
    last_err = None
    for attempt in range(retries):
        try:
            resp = genai_client.models.generate_content(model=model, contents=prompt, config=cfg)
            return resp.text or ""
        except Exception as e:
            last_err = e
            msg = str(e)
            if any(x in msg for x in ["429", "RESOURCE_EXHAUSTED", "503", "UNAVAILABLE"]):
                sleep_s = (2 ** attempt) + random.uniform(0.2, 0.8)
                time.sleep(sleep_s)
                continue
            raise
    raise last_err

# =========================================================
# 2) CSS (RTL للعربي / LTR للإنجليزي + الفوتر دائمًا RTL)
# =========================================================
DIR = "ltr" if IS_EN else "rtl"
ALIGN = "left" if IS_EN else "right"

st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Cairo&display=swap');
#MainMenu {{ visibility: hidden; }}
footer {{ visibility: hidden; }}
div[data-testid="stToolbar"] {{ visibility: hidden; }}
div[data-testid="stStatusWidget"] {{ visibility: hidden; }}
div[data-testid="stDecoration"] {{ visibility: hidden; }}
div[class*="viewerBadge_container"] {{ display: none !important; }}
div[class*="viewerBadge_link"] {{ display: none !important; }}
div[class*="viewerBadge_text"] {{ display: none !important; }}

html, body, [data-testid="stAppViewContainer"], .main {{
    direction: {DIR} !important;
    text-align: {ALIGN} !important;
    font-family: 'Cairo', sans-serif !important;
}}

h1, h2, h3, h4, h5, h6, p, div, span, li, .stMarkdown {{
    direction: {DIR} !important;
    text-align: {ALIGN} !important;
    unicode-bidi: plaintext !important;
    white-space: pre-wrap !important;
    word-wrap: break-word !important;
    line-height: 1.9;
}}

.stButton > button {{
    background-color: #e63946 !important;
    color: white !important;
    border-radius: 28px;
    height: 3em;
    width: 100%;
    font-weight: 800;
}}

.footer-container {{
    width: 100%;
    text-align: center;
    margin-top: 45px;
    padding-top: 20px;
    border-top: 1px solid #666;
    font-size: 13px;
    display: flex;
    justify-content: center;
    gap: 6px;
    flex-wrap: wrap;
}}
.footer-container, .footer-container * {{
    direction: rtl !important;
    text-align: center !important;
}}
</style>
""", unsafe_allow_html=True)

# =========================================================
# 3) Analytics + Feedback RPC + Cache
# =========================================================
APP_ID = "4-persona-builder"

def track_cta_event(app_id: str):
    try:
        supabase.rpc("increment_cta", {"p_app_id": app_id}).execute()
    except Exception:
        pass

def save_feedback_via_rpc(app_name, useful, missing_reason, problem_text, helpful_reason, must_use_text):
    return supabase.rpc(
        "submit_app_feedback",
        {
            "p_app_name": app_name,
            "p_useful": useful,
            "p_missing_reason": missing_reason,
            "p_problem_text": problem_text,
            "p_helpful_reason": helpful_reason,
            "p_must_use_text": must_use_text,
        },
    ).execute()

def make_content_hash(text: str) -> str:
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()

def cache_get(app_id: str, content_hash: str):
    try:
        res = (
            supabase.table("viral_scores_cache")
            .select("analysis_text")
            .eq("app_id", app_id)
            .eq("content_hash", content_hash)
            .limit(1)
            .execute()
        )
        return json.loads(res.data[0]["analysis_text"]) if res.data else None
    except Exception:
        return None

def cache_set(app_id: str, content_hash: str, analysis: dict):
    try:
        supabase.table("viral_scores_cache").upsert(
            {
                "app_id": app_id,
                "content_hash": content_hash,
                "analysis_text": json.dumps(analysis, ensure_ascii=False),
            },
            on_conflict="app_id,content_hash",
        ).execute()
    except Exception:
        pass

# =========================================================
# 4) منطق التوليد (نفس المنطق + لغة output حسب السويتش)
# =========================================================
def clean_json_text(text: str):
    match = re.search(r"\{.*\}", text, re.DOTALL)
    return match.group(0) if match else text

def generate_persona_safe(field, goal, audience):
    current_model = get_working_model()

    if IS_EN:
        prompt = f"""
Create a professional Persona document in English:
Field: {field} | Goal: {goal} | Audience: {audience}

Return JSON only (no extra text) including these sections (section3 must be 30 full days):
{{
  "section1": {{"name": "Persona name", "bio": "Short bio"}},
  "section2": {{"tone": ["Tone 1", "Tone 2"], "style": "Communication style", "voice_keywords": ["keywords"]}},
  "section3": [
    {{"day": 1, "content_type": "Type", "idea": "Content idea", "cta": "CTA", "platform": "Platform"}}
  ],
  "section4": {{
    "talk_about": ["Topics to focus on"],
    "avoid_talking_about": ["Topics to avoid"],
    "dm_policy": "DM policy",
    "comment_policy": "Comment policy"
  }}
}}

Important:
- section3 must contain exactly 30 items from day 1 to day 30.
- content_type examples: Short video, Story, Post, Long video, Live, Carousel.
- platform examples: LinkedIn, Instagram, TikTok, YouTube.
"""
    else:
        prompt = f"""
أنشئ وثيقة شخصية رقمية (Persona) احترافية باللغة العربية:
المجال: {field} | الهدف: {goal} | الجمهور: {audience}

المطلوب رد JSON فقط يتضمن الأقسام التالية (30 يوماً كاملة):
{{
  "section1": {{"name": "اسم الشخصية", "bio": "نبذة"}},
  "section2": {{"tone": ["نبرة1", "نبرة2"], "style": "أسلوب الكلام", "voice_keywords": ["كلمات"]}},
  "section3": [ {{"day": 1, "content_type": "نوع", "idea": "فكرة محتوى", "cta": "طلب", "platform": "المنصة"}} ],
  "section4": {{
    "talk_about": ["مواضيع للنقاش"],
    "avoid_talking_about": ["مواضيع للتجنب"],
    "dm_policy": "سياسة الخاص",
    "comment_policy": "سياسة التعليقات"
  }}
}}
* ملاحظة هامة: يجب أن يحتوي section3 على 30 يوماً كاملة بدون أي اختصار.
"""

    try:
        cfg = types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.5,
            max_output_tokens=4000,
        )
        raw_text = call_model_with_retry(current_model, prompt, cfg, retries=4)
        return json.loads(clean_json_text(raw_text))
    except Exception as e:
        return {"error": str(e)}

# =========================================================
# 4.1) Plain Text Builder (for export)
# =========================================================
def build_plain_text(data: dict, is_en: bool) -> str:
    s1 = data.get("section1", {}) or {}
    s2 = data.get("section2", {}) or {}
    s3 = data.get("section3", []) or []
    s4 = data.get("section4", {}) or {}

    if is_en:
        out = []
        out.append("INTEGRATED PERSONA DOCUMENT")
        out.append("")
        out.append("1) IDENTITY")
        out.append(f"- Name: {s1.get('name','—')}")
        out.append(f"- Bio: {s1.get('bio','—')}")
        out.append("")
        out.append("2) TONE & STYLE")
        out.append(f"- Tone: {', '.join(s2.get('tone', []) or []) or '—'}")
        out.append(f"- Style: {s2.get('style','—')}")
        out.append(f"- Keywords: {', '.join(s2.get('voice_keywords', []) or []) or '—'}")
        out.append("")
        out.append("3) 30-DAY CONTENT PLAN")
        for item in s3:
            d = item.get("day", "—")
            out.append(f"Day {d}: {item.get('idea','—')}")
            out.append(f"  Type: {item.get('content_type','—')} | Platform: {item.get('platform','—')} | CTA: {item.get('cta','—')}")
        out.append("")
        out.append("4) COMMUNICATION BOUNDARIES")
        out.append(f"- Talk about: {', '.join(s4.get('talk_about', []) or []) or '—'}")
        out.append(f"- Avoid: {', '.join(s4.get('avoid_talking_about', []) or []) or '—'}")
        out.append(f"- DM policy: {s4.get('dm_policy','—')}")
        out.append(f"- Comment policy: {s4.get('comment_policy','—')}")
        return "\n".join(out)

    else:
        out = []
        out.append("وثيقة الشخصية الرقمية المتكاملة")
        out.append("")
        out.append("1) الهوية")
        out.append(f"- الاسم: {s1.get('name','—')}")
        out.append(f"- النبذة: {s1.get('bio','—')}")
        out.append("")
        out.append("2) النبرة وأسلوب التواصل")
        out.append(f"- النبرة: {', '.join(s2.get('tone', []) or []) or '—'}")
        out.append(f"- الأسلوب: {s2.get('style','—')}")
        out.append(f"- كلمات مفتاحية: {', '.join(s2.get('voice_keywords', []) or []) or '—'}")
        out.append("")
        out.append("3) خطة محتوى 30 يوم")
        for item in s3:
            d = item.get("day", "—")
            out.append(f"اليوم {d}: {item.get('idea','—')}")
            out.append(f"  النوع: {item.get('content_type','—')} | المنصة: {item.get('platform','—')} | CTA: {item.get('cta','—')}")
        out.append("")
        out.append("4) حدود التواصل")
        out.append(f"- مواضيع نركز عليها: {', '.join(s4.get('talk_about', []) or []) or '—'}")
        out.append(f"- مواضيع نتجنبها: {', '.join(s4.get('avoid_talking_about', []) or []) or '—'}")
        out.append(f"- سياسة الرسائل: {s4.get('dm_policy','—')}")
        out.append(f"- سياسة التعليقات: {s4.get('comment_policy','—')}")
        return "\n".join(out)

# =========================================================
# 5) واجهة المستخدم (كلها تتبدل حسب اللغة)
# =========================================================
st.title(TXT["title"])
st.caption(TXT["caption"])

with st.expander(TXT["exp_title"], expanded=True):
    st.markdown(TXT["exp_body"])

# ==============================
# Testimonials (EN only + LTR always)
# shows for both languages
# ==============================
st.markdown("---")
st.markdown(
    """
<style>
/* =========================
   Testimonials (Fix Light/Dark)
   ========================= */

/* Title */
.testimonial-title{
  text-align:center;
  font-size:20px;
  font-weight:800;
  margin: 10px 0 12px 0;
  direction:ltr !important;
  unicode-bidi: plaintext !important;
  color: #111827;            /* ✅ واضح بالوضع الفاتح */
}

/* Wrapper */
.testimonial-wrapper{
  display:flex;
  gap:14px;
  overflow-x:auto;
  padding: 8px 8px 14px 8px;
  scroll-snap-type:x mandatory;
  -webkit-overflow-scrolling: touch;
}
.testimonial-wrapper::-webkit-scrollbar{height:8px;}
.testimonial-wrapper::-webkit-scrollbar-thumb{
  background: rgba(0,0,0,0.18);  /* ✅ مناسب للفاتيح */
  border-radius: 99px;
}

/* Card */
.testimonial-card{
  flex: 0 0 auto;
  width: 320px;
  max-width: 85vw;

  background: #ffffff;              /* ✅ ثابت وواضح بالوضع الفاتح */
  border: 1px solid rgba(0,0,0,0.08);
  border-left: 5px solid #e63946;
  border-radius: 14px;
  padding: 16px 16px 14px 16px;
  scroll-snap-align:center;

  direction:ltr !important;
  text-align:center !important;
  unicode-bidi: plaintext !important;

  height:auto !important;
  min-height: unset !important;

  box-shadow: 0 6px 18px rgba(0,0,0,0.06); /* ✅ شكل احترافي */
}

/* Text */
.testimonial-text{
  color: #111827 !important;     /* ✅ نص غامق واضح */
  font-size: 14px;
  line-height: 1.6;
  margin:0 !important;
  padding:0 !important;

  direction:ltr !important;
  text-align:center !important;
  unicode-bidi: plaintext !important;

  opacity: 1 !important;         /* ✅ يمنع أي بهتان */
}

/* Author */
.testimonial-author{
  margin-top:10px;
  font-weight:700;
  color: #6b7280 !important;     /* ✅ رمادي واضح */
  font-size: 13px;

  direction:ltr !important;
  text-align:center !important;
  unicode-bidi: plaintext !important;

  opacity: 1 !important;
}

/* ✅ Dark Mode override */
@media (prefers-color-scheme: dark){
  .testimonial-title{
    color: rgba(255,255,255,0.92) !important;
  }

  .testimonial-wrapper::-webkit-scrollbar-thumb{
    background: rgba(255,255,255,0.22);
  }

  .testimonial-card{
    background: rgba(255,255,255,0.03);
    border: 1px solid rgba(255,255,255,0.14);
    box-shadow: 0 8px 24px rgba(0,0,0,0.35);
  }

  .testimonial-text{
    color: rgba(255,255,255,0.92) !important;
  }

  .testimonial-author{
    color: rgba(255,255,255,0.72) !important;
  }
}
</style>

<div class="testimonial-title">💬 What users are saying</div>

<div class="testimonial-wrapper">
  <div class="testimonial-card">
    <div class="testimonial-text">A solid AI tool — simple, practical, and worth trying.</div>
    <div class="testimonial-author">— Abdul Razzaq</div>
  </div>

  <div class="testimonial-card">
    <div class="testimonial-text">It worked well and gave me a clearer direction.</div>
    <div class="testimonial-author">— Imad Tawil</div>
  </div>

  <div class="testimonial-card">
    <div class="testimonial-text">
      Excellent tool and clearly built with real effort. Adding a small example showing how a user benefits from the output would make it even easier for first-time users.
    </div>
    <div class="testimonial-author">— Salem Khalil</div>
  </div>

  <div class="testimonial-card">
    <div class="testimonial-text">
      Useful and simplifies my strategy. Exporting the advice as one plain text would make it easier — especially if it becomes available as an app.
    </div>
    <div class="testimonial-author">— Rashid Dossett</div>
  </div>

  <div class="testimonial-card">
    <div class="testimonial-text">
      Well done. More input space would make entering information easier and clearer. A few styling improvements could also enhance the overall experience.
    </div>
    <div class="testimonial-author">— Sarda Kedir</div>
  </div>
</div>
""",
    unsafe_allow_html=True,
)

# ------------------------------
# Inputs (expanded as requested)
# ------------------------------
col1, col2 = st.columns(2)
with col1:
    f_in = st.text_area(TXT["field_label"], placeholder=TXT["field_ph"], height=90)
    g_in = st.text_area(TXT["goal_label"], placeholder=TXT["goal_ph"], height=90)
with col2:
    a_in = st.text_area(TXT["aud_label"], placeholder=TXT["aud_ph"], height=220)

if st.button(TXT["btn_generate"]):
    if not all([f_in.strip(), g_in.strip(), a_in.strip()]):
        st.warning(TXT["warn_fill"])
    else:
        track_cta_event(APP_ID)
        c_hash = make_content_hash(f"lang={st.session_state['ui_lang']}||{f_in}||{g_in}||{a_in}")
        cached = cache_get(APP_ID, c_hash)

        if cached:
            res = cached
        else:
            if not can_call_model(min_seconds=12):
                st.warning(TXT["wait"])
                st.stop()
            with st.spinner(TXT["spinner"]):
                res = generate_persona_safe(f_in, g_in, a_in)
                if "error" not in res:
                    cache_set(APP_ID, c_hash, res)

        if "error" in res:
            err_msg = str(res["error"])
            if "429" in err_msg or "RESOURCE_EXHAUSTED" in err_msg:
                st.warning(
                    "⚡ The tool is currently busy. Please try again in a few seconds."
                    if IS_EN
                    else
                    "⚡ الأداة مشغولة حالياً، يرجى المحاولة بعد ثوانٍ قليلة."
                )
            else:
                st.error(f"{TXT['err']} {err_msg}")
        else:
            st.session_state["persona_result"] = res
            st.session_state["persona_has_result"] = True

# =========================================================
# 6) عرض النتائج + Plain Text Export + Feedback
# =========================================================
if st.session_state.get("persona_has_result") and "persona_result" in st.session_state:
    data = st.session_state["persona_result"]
    st.subheader(TXT["res_title"])

    with st.expander(TXT["sec1"], expanded=True):
        st.write(f"**{TXT['name']}:** {data.get('section1', {}).get('name', '—')}")
        st.write(f"**{TXT['bio']}:** {data.get('section1', {}).get('bio', '—')}")

    with st.expander(TXT["sec2"], expanded=False):
        s2 = data.get("section2", {})
        st.write(f"**{TXT['tone']}:** {', '.join(s2.get('tone', []) or [])}")
        st.write(f"**{TXT['style']}:** {s2.get('style', '—')}")
        st.write(f"**{TXT['keywords']}:** {', '.join(s2.get('voice_keywords', []) or [])}")

    with st.expander(TXT["sec3"], expanded=False):
        for item in data.get("section3", []) or []:
            st.markdown(f"**{TXT['day']} {item.get('day', '—')}:** {item.get('idea', '—')}")
            st.caption(
                f"{TXT['type']}: {item.get('content_type', '—')} | "
                f"{TXT['platform']}: {item.get('platform', '—')} | "
                f"{TXT['cta']}: {item.get('cta', '—')}"
            )

    with st.expander(TXT["sec4"], expanded=False):
        s4 = data.get("section4", {})
        st.write(f"**{TXT['talk']}:** " + ", ".join(s4.get("talk_about", []) or []))
        st.write(f"**{TXT['avoid']}:** " + ", ".join(s4.get("avoid_talking_about", []) or []))
        st.info(f"**{TXT['dm']}:** {s4.get('dm_policy', '—')}")
        st.info(f"**{TXT['comments']}:** {s4.get('comment_policy', '—')}")

    # ------------------------------
    # Plain Text Export (new)
    # ------------------------------
    st.divider()
    st.subheader(TXT["plain_title"])
    st.caption(TXT["plain_hint"])

    if st.button(TXT["plain_btn"], key=f"{APP_ID}_plain_btn"):
        st.session_state[f"{APP_ID}_plain_text"] = build_plain_text(data, IS_EN)

    plain_text_val = st.session_state.get(f"{APP_ID}_plain_text")
    if plain_text_val:
        st.text_area(
            label="",
            value=plain_text_val,
            height=320,
            key=f"{APP_ID}_plain_area",
        )
        st.download_button(
            label="⬇️ Download .txt" if IS_EN else "⬇️ تحميل ملف .txt",
            data=plain_text_val.encode("utf-8"),
            file_name="persona_document.txt",
            mime="text/plain",
            key=f"{APP_ID}_plain_download",
        )

    # ------------------------------
    # Feedback (as-is)
    # ------------------------------
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
        problem_text = st.text_area(TXT["fb_p1"], max_chars=280, key=f"{APP_ID}_problem_text")
        helpful_reason = st.text_area(TXT["fb_p2"], max_chars=280, key=f"{APP_ID}_helpful_reason")
        must_use_text = st.text_area(TXT["fb_p3"], max_chars=280, key=f"{APP_ID}_must_use_text")

        submit_feedback = st.button(TXT["fb_btn"], key=f"{APP_ID}_submit_feedback")

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
                    save_feedback_via_rpc(
                        app_name=APP_ID,
                        useful=useful,
                        missing_reason=(missing_reason or "").strip() or None,
                        problem_text=(problem_text or "").strip() or None,
                        helpful_reason=(helpful_reason or "").strip() or None,
                        must_use_text=(must_use_text or "").strip() or None,
                    )
                    st.success(TXT["fb_ok"])
                except APIError as e:
                    st.error(TXT["fb_err"])
                    try:
                        st.json(e.args[0])
                    except Exception:
                        st.write(str(e))
                except Exception as e:
                    st.exception(e)

# =========================================================
# 7) Footer (دائمًا RTL)
# =========================================================
st.markdown(
    """
<div class="footer-container">
  <span>جميع الحقوق محفوظة © 2026 |</span>
  <span>AI Product Builder - Layan Khalil</span>
</div>
""",
    unsafe_allow_html=True,
)

