"""LexiGuide AI - AI-powered micro-legal assistant (Streamlit edition)."""
import base64
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path

import requests
import streamlit as st

st.set_page_config(page_title="LexiGuide AI", page_icon="⚖️", layout="wide")

KB = json.loads((Path(__file__).parent / "kb.json").read_text(encoding="utf-8"))
CIVIL = {"deposit", "consumer", "cheque"}
JURS = ["Tamil Nadu, India", "Karnataka, India", "Maharashtra, India", "Delhi, India", "Other / not sure"]
DEFAULT_MODELS = "gemini-3.8-flash,gemini-3.5-flash-lite"
API = "https://generativelanguage.googleapis.com/v1beta/models/{}:generateContent"
DISC = ("**Disclaimer.** LexiGuide AI gives general legal information only, not legal advice. "
        "Verify details with the issuing authority or a qualified lawyer.")
PAGES = [("home", "🏠", "Home"), ("ask", "💬", "Ask Legal Question"), ("upload", "☁️", "Upload & Analyse Document"),
         ("traffic", "🚗", "Traffic & Civil Issues"), ("docs", "📄", "My Documents"),
         ("history", "🕘", "History"), ("settings", "⚙️", "Settings")]
EXAMPLES = ["I was fined ₹1,000 for not wearing a helmet in Chennai",
            "My landlord won’t return my deposit after I moved out",
            "A cheque I received bounced, what now?",
            "My car was towed from a no-parking zone"]

# ---------------------------------------------------------------- styling
st.markdown("""
<style>
.stApp{background:
  linear-gradient(rgba(28,37,48,.05) 1px,transparent 1px) 0 0/56px 56px,
  linear-gradient(90deg,rgba(28,37,48,.05) 1px,transparent 1px) 0 0/56px 56px,
  radial-gradient(620px 440px at 0% 0%,rgba(188,211,238,.85),transparent),
  radial-gradient(540px 440px at 100% 100%,rgba(217,228,242,.95),transparent),#f4f6f8;}
[data-testid=stSidebar]{background:rgba(255,255,255,.55);backdrop-filter:blur(14px);border-right:1px solid rgba(28,37,48,.09)}
[data-testid=stSidebar] .stButton>button{justify-content:flex-start;border-radius:12px;border:1px solid rgba(28,37,48,.09);background:rgba(255,255,255,.8)}
[data-testid=stHeader]{background:transparent}
div[data-testid=stVerticalBlockBorderWrapper]{background:rgba(255,255,255,.72);border-radius:18px;backdrop-filter:blur(12px)}
.stButton>button[kind=primary]{border-radius:12px;font-weight:600}
h1,h2,h3{letter-spacing:-.02em}
.hero{text-align:center;padding:10px 0 4px}
.hero h1{font-size:clamp(32px,5vw,52px);line-height:1.1;font-weight:650}
.hero h1 span{color:#3b6ea8}
.pill{display:inline-block;font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:#6b7785;border:1px solid rgba(28,37,48,.1);border-radius:99px;padding:4px 14px;background:rgba(255,255,255,.7)}
.muted{color:#6b7785}
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------- state
ss = st.session_state
ss.setdefault("page", "home")
ss.setdefault("history", [])
ss.setdefault("docs", [])
ss.setdefault("last", None)
ss.setdefault("q", "")


def secret(name):
    try:
        return st.secrets.get(name)
    except Exception:
        return None


def get_key():
    return (ss.get("key") or secret("GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY") or "").strip().strip("\"'")


def get_models():
    return ss.get("models") or secret("GEMINI_MODELS") or DEFAULT_MODELS


def goto(page, **kw):
    ss.page = page
    for k, v in kw.items():
        ss[k] = v


def now():
    return datetime.now().strftime("%d %b %Y, %H:%M")


# ---------------------------------------------------------------- Gemini
def parse_json(text):
    return json.loads(re.sub(r"```json|```", "", text).strip())


def gemini(parts, status=None):
    """Call Gemini with retries and model fallback. Returns parsed JSON."""
    key = get_key()
    if not key:
        raise RuntimeError("No Gemini API key. Add it in Settings or in the app Secrets.")
    body = {"contents": [{"parts": parts}],
            "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json"}}
    last = None
    for model in [m.strip() for m in get_models().split(",") if m.strip()]:
        for attempt in range(2):
            if status:
                status(f"Asking {model}… (attempt {attempt + 1} of 2)")
            try:
                r = requests.post(API.format(model), json=body, timeout=75,
                                  headers={"x-goog-api-key": key, "Content-Type": "application/json"})
            except requests.Timeout:
                last = RuntimeError(f"{model} took too long to respond")
                continue
            except requests.RequestException as e:
                raise RuntimeError(f"Network error: {e}")
            try:
                d = r.json()
            except ValueError:
                d = {}
            if r.ok:
                try:
                    text = "".join(p.get("text", "") for p in d["candidates"][0]["content"]["parts"])
                    return parse_json(text)
                except (KeyError, IndexError, ValueError):
                    last = RuntimeError("Gemini returned an empty or unreadable answer (possibly blocked by safety filters)")
                    break
            last = RuntimeError(d.get("error", {}).get("message") or f"Gemini error {r.status_code}")
            if r.status_code in (429, 500, 503, 504):
                if attempt == 0:
                    time.sleep(2)
                continue
            if r.status_code == 404:
                break
            raise last
    raise last or RuntimeError("No model available")


# ---------------------------------------------------------------- pipeline
def retrieve(q):
    text = q.lower()
    scored = []
    for e in KB:
        s = sum((2 if len(w.strip()) > 5 else 1) for w in e["k"].split(",") if w.strip() in text)
        if s:
            scored.append((s, e))
    return [e for _, e in sorted(scored, key=lambda x: -x[0])[:3]]


def build_prompt(q, jur, ctx):
    blocks = "\n\n".join(f"[{i + 1}] {e['t']}\nRule: {e['r']}\nPenalty: {e['p']}\nSteps: {'; '.join(e['s'])}\n"
                         f"Evidence: {'; '.join(e['e'])}" for i, e in enumerate(ctx))
    return f"""You are LexiGuide AI, a micro-legal information assistant for common traffic and civil infractions.
Use ONLY the CONTEXT below for rules and penalties. If the context does not cover something, say so in "uncertainty" and do not invent laws, sections or amounts.
Write in short, plain language for a non-lawyer. This is information, not legal advice.

USER INCIDENT: {q}
JURISDICTION: {jur}

CONTEXT:
{blocks}

Return JSON with exactly these keys:
{{"issue":"one-sentence identified issue","category":"short category","confidence":"high|medium|low","explanation":"2-3 plain sentences","rules":["applicable rules or obligations"],"penalties":["possible penalties where documented"],"verify":["things the user should double-check on their notice"],"next_steps":["ordered practical steps"],"evidence":["evidence to collect"],"uncertainty":"what is unknown or varies by state/authority","sources":[numbers of context entries used]}}"""


def as_list(v):
    return [str(x) for x in v if x] if isinstance(v, list) else ([str(v)] if v else [])


def offline(ctx):
    e = ctx[0]
    return {"issue": e["t"], "category": "Matched from knowledge base", "confidence": "medium", "explanation": e["r"],
            "rules": [x["r"] for x in ctx], "penalties": [x["p"] for x in ctx],
            "verify": ["Confirm the offence, date, place and vehicle number on your notice",
                       "Check the deadline to pay or contest"],
            "next_steps": e["s"], "evidence": e["e"],
            "uncertainty": "Offline mode shows stored entries without tailoring to your situation.",
            "sources": list(range(1, len(ctx) + 1))}


def validate(o, ctx):
    conf = o.get("confidence") if o.get("confidence") in ("high", "medium", "low") else "low"
    src = [int(n) for n in as_list(o.get("sources")) if str(n).isdigit() and 1 <= int(n) <= len(ctx)]
    v = {"issue": str(o.get("issue") or "Issue not identified"), "category": str(o.get("category") or "General"),
         "confidence": conf, "explanation": str(o.get("explanation") or ""),
         "rules": as_list(o.get("rules")), "penalties": as_list(o.get("penalties")),
         "verify": as_list(o.get("verify")), "next_steps": as_list(o.get("next_steps")),
         "evidence": as_list(o.get("evidence")),
         "uncertainty": str(o.get("uncertainty") or "Rules and amounts vary by state and authority; confirm with the issuing office."),
         "sources": src or list(range(1, len(ctx) + 1))}
    if not v["next_steps"]:
        v["next_steps"] = ["Read the notice carefully", "Contact the issuing authority", "Consider speaking to a lawyer"]
    return v


# ---------------------------------------------------------------- UI helpers
def bullets(title, items):
    if items:
        with st.container(border=True):
            st.caption(title.upper())
            for i in items:
                st.markdown(f"- {i}")


def checklist(title, items, prefix):
    if items:
        with st.container(border=True):
            st.caption(title.upper())
            for i, it in enumerate(items):
                st.checkbox(it, key=f"{prefix}{i}")


def show_result(r):
    v, ctx = r["v"], r["ctx"]
    with st.container(border=True):
        st.caption("IDENTIFIED ISSUE")
        st.subheader(v["issue"])
        st.markdown(f"`{v['category']}` `Confidence: {v['confidence']}` `{r['jur']}` `{'Gemini' if r['ai'] else 'Offline'}`")
        if v["explanation"]:
            st.write(v["explanation"])
    bullets("Applicable rules", v["rules"])
    bullets("Possible penalties", v["penalties"])
    bullets("What to verify", v["verify"])
    checklist("Recommended next steps", v["next_steps"], "ns")
    checklist("Evidence checklist", v["evidence"], "ev")
    with st.container(border=True):
        st.caption("SOURCES & LIMITS")
        for n in v["sources"]:
            st.markdown(f"- Knowledge base: {ctx[n - 1]['t']}")
        st.markdown(f"**Uncertainty:** {v['uncertainty']}")
    st.warning(DISC)


def show_doc(a):
    with st.container(border=True):
        st.caption("DOCUMENT IDENTIFIED")
        st.subheader(a["doc_type"])
        st.write(a["summary"])
    if a["details"]:
        with st.container(border=True):
            st.caption("KEY DETAILS")
            for d in a["details"]:
                st.markdown(f"- **{d['label']}:** {d['value']}")
    bullets("Possible next steps", a["steps"])
    bullets("Deadlines to watch", a["deadlines"])
    with st.container(border=True):
        st.caption("LIMITS")
        st.write(a["uncertainty"])


# ---------------------------------------------------------------- sidebar
with st.sidebar:
    st.markdown("### ⚖️ LexiGuide AI")
    st.caption("Your Legal Assistant")
    for key, icon, label in PAGES:
        st.button(f"{icon}  {label}", key=f"nav_{key}", use_container_width=True,
                  type="primary" if ss.page == key else "secondary", on_click=goto, args=(key,))
    st.divider()
    st.caption("Gemini connected" if get_key() else "Offline mode · add a Gemini key in Settings")

page = ss.page

# ---------------------------------------------------------------- Home
if page == "home":
    with st.container(border=True):
        st.title(f"Hello, {ss.get('name') or 'User'} 👋")
        st.write("Your AI-powered legal assistant. Ask questions, upload documents, get clear answers and stay informed about your rights.")
        st.markdown("💬 Simple language &nbsp;&nbsp; ✓ Information with cautions &nbsp;&nbsp; 🔒 Privacy-conscious")
    cards = [("💬", "Ask Legal Question", "Type your question in simple language and get easy-to-understand information.", "ask"),
             ("☁️", "Upload & Analyse Document", "Upload a PDF, JPG or PNG to identify the document, key details and possible next steps.", "upload"),
             ("🚗", "Traffic & Civil Issues", "Explore common traffic, parking, vehicle-document and selected civil issues.", "traffic"),
             ("📄", "My Documents", "Review analyses saved in this session.", "docs"),
             ("🕘", "History", "Revisit your earlier questions and document analyses.", "history"),
             ("⚙️", "Settings", "Connect Gemini, set your name and manage your saved data.", "settings")]
    for row in (cards[:3], cards[3:]):
        cols = st.columns(3)
        for col, (ic, t, d, k) in zip(cols, row):
            with col, st.container(border=True):
                st.markdown(f"## {ic}")
                st.markdown(f"**{t}**")
                st.caption(d)
                st.button("Open →", key=f"card_{k}", use_container_width=True, on_click=goto, args=(k,))
    st.markdown("### How it works")
    steps = [("01 Query & input", "Your description is validated and tagged with a location."),
             ("02 Intent detection", "The infraction category and key facts are identified."),
             ("03 Knowledge retrieval", "Matching rules and penalties are pulled from the curated base."),
             ("04 Gemini reasoning", "A grounded prompt makes Gemini explain only what the context supports."),
             ("05 Validation", "Structure, uncertainty and the disclaimer are checked before display.")]
    for col, (t, d) in zip(st.columns(5), steps):
        with col, st.container(border=True):
            st.markdown(f"**{t}**")
            st.caption(d)
    st.markdown("### About the project")
    st.write("**AI-Powered Micro-Legal Assistant for Common Traffic & Civil Infractions** · Minor Project–I (10214CS601), "
             "Department of Computer Science & Engineering, School of Computing, Vel Tech Rangarajan Dr. Sagunthala R&D Institute of Science and Technology.")
    st.caption("Supervisor: Dr. K. Dinesh Kumar, Associate Professor · Team: N. Yajna Venkata Shiridi, Y. Mohan Laxmi Balaji, S. Hakesh Sai Ram")

# ---------------------------------------------------------------- Ask
elif page == "ask":
    st.markdown('<div class="hero"><span class="pill">Traffic &amp; civil infractions · plain language</span>'
                '<h1>Understand your notice. <span>Know your next step.</span></h1>'
                '<p class="muted">Describe what happened. LexiGuide AI classifies the issue, retrieves the relevant rules '
                'from a curated knowledge base, and explains them with a practical checklist.</p></div>', unsafe_allow_html=True)
    with st.container(border=True):
        st.text_area("Describe the incident", key="q", height=110, label_visibility="collapsed",
                     placeholder="e.g. I got an e-challan for not wearing a helmet in Chennai last week. What does it mean and what should I do?")
        c1, c2 = st.columns([3, 1])
        jur = c1.selectbox("Jurisdiction", JURS, label_visibility="collapsed")
        go = c2.button("Explain it to me", type="primary", use_container_width=True)
        ex = st.columns(len(EXAMPLES))
        for col, e in zip(ex, EXAMPLES):
            col.button(e, key=f"ex_{e[:12]}", use_container_width=True, on_click=lambda e=e: ss.update(q=e))
    if go:
        q = ss.q.strip()
        if len(q) < 8:
            st.info("Please describe the incident in a sentence or two.")
        else:
            with st.status("Working…", expanded=True) as s:
                s.write("✓ 1. Input validated")
                ctx = retrieve(q)
                s.write(f"✓ 2. Classified · ✓ 3. Retrieved {len(ctx)} knowledge entries")
                if not ctx:
                    s.update(label="No match", state="error")
                    ss.last = None
                    st.warning("I couldn’t match this to an entry in the knowledge base. Try mentioning the offence "
                               "(for example helmet, parking, cheque, deposit) or what the notice says.")
                else:
                    ai, raw = False, None
                    if get_key():
                        try:
                            raw = gemini([{"text": build_prompt(q, jur, ctx)}], status=lambda m: s.write(m))
                            ai = True
                        except Exception as err:
                            st.warning(f"Gemini unavailable: {err}. Showing offline results instead. "
                                       "Use Settings → Test connection to find a working model.")
                    raw = raw or offline(ctx)
                    s.write("✓ 5. Validated")
                    ss.last = {"v": validate(raw, ctx), "ctx": ctx, "jur": jur, "ai": ai}
                    ss.history.insert(0, {"type": "question", "q": q, "jur": jur, "issue": ss.last["v"]["issue"], "t": now()})
                    s.update(label="Done", state="complete", expanded=False)
    if ss.last:
        show_result(ss.last)

# ---------------------------------------------------------------- Upload
elif page == "upload":
    st.header("Upload & Analyse Document")
    st.caption("PDF, JPG or PNG up to 10 MB. The file is sent to Gemini for analysis and is not stored; only the result is kept for this session.")
    with st.container(border=True):
        f = st.file_uploader("Choose a file", type=["pdf", "jpg", "jpeg", "png"], label_visibility="collapsed")
        jur = st.selectbox("Jurisdiction", JURS, key="ujur")
        go = st.button("Analyse document", type="primary")
    if go:
        if not f:
            st.info("Choose a file first.")
        elif not get_key():
            st.warning("Document analysis needs Gemini. Add your key in Settings.")
        elif f.size > 10 * 1024 * 1024:
            st.warning("Please choose a file under 10 MB.")
        else:
            mime = {"pdf": "application/pdf", "png": "image/png"}.get(f.name.rsplit(".", 1)[-1].lower(), "image/jpeg")
            kb = "\n".join(f"- {e['t']}: {e['r']} Penalty: {e['p']}" for e in KB)
            prompt = f"""You are LexiGuide AI. Analyse the attached document (for example a traffic challan, notice, agreement or letter).
Identify what it is, summarise it in plain language, extract key details exactly as shown (notice number, dates, amounts, offence, section, authority, vehicle number, deadlines) and suggest practical next steps.
Use KNOWLEDGE only for rules and penalties. Never invent facts that are not visible in the document; write "not visible" for unreadable fields. If the document cites something KNOWLEDGE does not cover, say so in "uncertainty".
JURISDICTION: {jur}

KNOWLEDGE:
{kb}

Return JSON: {{"doc_type":"","summary":"","details":[{{"label":"","value":""}}],"steps":[""],"deadlines":[""],"uncertainty":""}}"""
            with st.spinner("Analysing…"):
                try:
                    raw = gemini([{"inline_data": {"mime_type": mime, "data": base64.b64encode(f.getvalue()).decode()}},
                                  {"text": prompt}])
                    a = {"id": time.time_ns(), "t": now(), "name": f.name,
                         "doc_type": str(raw.get("doc_type") or "Unidentified document"),
                         "summary": str(raw.get("summary") or ""),
                         "details": [{"label": str(d.get("label")), "value": str(d.get("value", ""))}
                                     for d in raw.get("details", []) if isinstance(d, dict) and d.get("label")],
                         "steps": as_list(raw.get("steps")), "deadlines": as_list(raw.get("deadlines")),
                         "uncertainty": str(raw.get("uncertainty") or "Check every detail against the original document.")}
                    ss.docs.insert(0, a)
                    ss.history.insert(0, {"type": "document", "q": a["name"], "issue": a["doc_type"], "t": a["t"]})
                    show_doc(a)
                    st.success("Saved to My Documents.")
                    st.warning(DISC)
                except Exception as err:
                    st.error(f"Analysis failed: {err}")

# ---------------------------------------------------------------- Traffic & Civil
elif page == "traffic":
    st.header("Traffic & Civil Issues")
    st.caption("The curated knowledge base. Fines follow the Motor Vehicles (Amendment) Act, 2019; states may vary.")
    c1, c2 = st.columns([3, 2])
    s = c1.text_input("Search", placeholder="Search issues…", label_visibility="collapsed").lower()
    kind = c2.radio("Type", ["All", "Traffic", "Civil"], horizontal=True, label_visibility="collapsed")
    shown = [e for e in KB if (kind == "All" or (kind == "Civil") == (e["id"] in CIVIL))
             and s in f"{e['t']} {e['k']} {e['r']}".lower()]
    if not shown:
        st.info("No matching issues.")
    for e in shown:
        with st.expander(f"{e['t']}  ·  {'Civil' if e['id'] in CIVIL else 'Traffic'}"):
            st.markdown(f"**Rule:** {e['r']}")
            st.markdown(f"**Penalty:** {e['p']}")
            st.markdown("**Next steps:** " + " → ".join(e["s"]))
            st.button("Ask about this", key=f"ask_{e['id']}", on_click=goto, args=("ask",),
                      kwargs={"q": f"What should I know about this: {e['t'].lower()}?"})

# ---------------------------------------------------------------- Documents
elif page == "docs":
    st.header("My Documents")
    st.caption("Analyses saved in this session. Original files are never kept.")
    if not ss.docs:
        st.info("No saved documents yet. Analyse one from Upload & Analyse Document.")
    for a in list(ss.docs):
        with st.expander(f"{a['name']}  ·  {a['t']}"):
            show_doc(a)
            if st.button("Delete", key=f"del_{a['id']}"):
                ss.docs = [d for d in ss.docs if d["id"] != a["id"]]
                st.rerun()

# ---------------------------------------------------------------- History
elif page == "history":
    st.header("History")
    st.caption("Your recent questions and document analyses in this session.")
    if not ss.history:
        st.info("Nothing here yet. Your questions and analyses will appear here.")
    for i, h in enumerate(ss.history):
        with st.container(border=True):
            st.caption(f"{h['t']} · {h['type']}" + (f" · {h['jur']}" if h.get("jur") else ""))
            st.markdown(f"**{h['q']}**")
            st.caption(h.get("issue", ""))
            if h["type"] == "question":
                st.button("Ask again", key=f"redo_{i}", on_click=goto, args=("ask",), kwargs={"q": h["q"]})
    if ss.history and st.button("Clear history"):
        ss.history = []
        st.rerun()

# ---------------------------------------------------------------- Settings
elif page == "settings":
    st.header("Settings")
    st.caption("Get a free Gemini key at aistudio.google.com/apikey. For a permanent setup, add it to the app’s Secrets "
               "(see README). A key typed here lasts only for this session.")
    with st.container(border=True):
        ss.name = st.text_input("Your name", value=ss.get("name", ""), placeholder="User")
        ss.key = st.text_input("Gemini API key", value=ss.get("key", ""), type="password", placeholder="AIza…")
        ss.models = st.text_input("Models (comma-separated, tried in order)", value=get_models())
        st.caption("Gemini key found." if get_key() else "No key yet.")
        if st.button("Test connection & auto-select model", type="primary"):
            key = get_key()
            if not key:
                st.warning("Add your Gemini API key first.")
            else:
                skip = re.compile(r"tts|image|live|audio|transcribe|embed|imagen|veo|computer|robot|native|omni|lyria|antigravity|translate")
                try:
                    r = requests.get("https://generativelanguage.googleapis.com/v1beta/models?pageSize=200",
                                     headers={"x-goog-api-key": key}, timeout=30)
                    d = r.json()
                    if not r.ok:
                        st.error(f"Google rejected the key ({r.status_code}): {d.get('error', {}).get('message', 'unknown error')}")
                    else:
                        names = [m["name"].replace("models/", "") for m in d.get("models", [])
                                 if "generateContent" in m.get("supportedGenerationMethods", [])]
                        names = [n for n in names if re.search("flash|pro", n) and not skip.search(n)]
                        names.sort(key=lambda n: ("lite" in n, [-ord(c) for c in n]))
                        st.success(f"Key is valid. {len(names)} candidate models found.")
                        ok = []
                        for n in names[:8]:
                            try:
                                p = requests.post(API.format(n), timeout=25,
                                                  headers={"x-goog-api-key": key, "Content-Type": "application/json"},
                                                  json={"contents": [{"parts": [{"text": "Reply with the single word OK"}]}]})
                                good = p.ok
                                msg = "works" if good else f"{p.status_code} {p.json().get('error', {}).get('message', '')[:100]}"
                            except Exception as e:
                                good, msg = False, str(e)[:100]
                            st.write(f"{'✅' if good else '❌'} `{n}`: {msg}")
                            if good:
                                ok.append(n)
                                if len(ok) >= 3:
                                    break
                        if ok:
                            ss.models = ",".join(ok)
                            st.success(f"Using: {', '.join(ok)}")
                        else:
                            st.warning("No model answered right now. 503 = Google overloaded (retry in a few minutes), "
                                       "429 = quota, 403 = key permissions.")
                except Exception as e:
                    st.error(f"Could not reach Google: {e}")
    with st.container(border=True):
        st.download_button("Download my activity (JSON)",
                           json.dumps({"history": ss.history, "docs": ss.docs}, ensure_ascii=False, indent=1),
                           file_name="lexiguide_activity.json", mime="application/json")
        if st.button("Clear all saved data"):
            ss.history, ss.docs, ss.last = [], [], None
            st.success("Cleared.")

st.caption("LexiGuide AI provides general legal information only. It is not legal advice and does not replace a lawyer.")
