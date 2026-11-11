"""Deterministic checks. Cheap, no LLM, run on every question before any model call.

Everything here is a *signal*, never a verdict. The triage step reads these signals,
and the guards in run.py use some of them as hard requirements.
"""
import json
import re

from htmltext import to_text

LETTERS = "ABCD"

INJECTION_RE = re.compile(
    r"ignore (all )?(previous|prior|above) instructions|you are (now )?(the )?\w+ (bot|assistant|admin)"
    r"|system prompt|mark (this|it) (report )?as|change the (answer|key) to|as an ai|developer mode",
    re.I,
)
LANG_RE = re.compile(r"\b(hindi|english|marathi|tamil|telugu|bengali|gujarati|kannada|odia|urdu)\b", re.I)
KEYBOARD_ROWS = ("qwertyuiop", "asdfghjkl", "zxcvbnm")
LATEX_RE = re.compile(r"\\(frac|dfrac|sqrt|times|AA|alpha|beta|theta|lambda|mu|pi|left|right|text|mathrm|circ)\b|\$[^$]+\$")
EXAM_TAG_RE = re.compile(r"\(\s*(NEET|JEE|AIPMT|AIIMS|JEE Main|JEE Advanced|BITSAT|KCET|MHT[- ]CET)[^)]*\d{4}[^)]*\)", re.I)
FIGURE_RE = re.compile(r"\b(figure|shown below|as shown|diagram|graph shown|given circuit)\b", re.I)
NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")


def block(q):
    return q.get(q["questionType"]) or {}


def parse_options(question_html):
    """Return {letter: text} for (A)..(D) found in the question text.

    Uses the *last* run of (A),(B),... so that 'Assertion (A):' in the stem is not
    mistaken for option A.
    """
    text = to_text(question_html)
    marks = [(m.start(), m.end(), m.group(1)) for m in re.finditer(r"\(([A-D])\)", text)]
    start = None
    for i in range(len(marks) - 1, -1, -1):
        if marks[i][2] == "A":
            seq = [m[2] for m in marks[i:]]
            if seq[: min(len(seq), 2)] in (["A", "B"], ["A"]) or len(seq) == 1:
                start = i
                break
    if start is None:
        return text, {}
    run = marks[start:]
    opts = {}
    for j, (s, e, letter) in enumerate(run):
        end = run[j + 1][0] if j + 1 < len(run) else len(text)
        opts[letter] = text[e:end].strip()
    stem = text[: run[0][0]].strip()
    return stem, opts


def norm(s):
    return re.sub(r"[\s\u00a0]+", "", s).lower()


def answer_format_problem(q):
    t = q["questionType"]
    a = block(q).get("answer")
    if t == "scq":
        if not (isinstance(a, str) and len(a) == 1 and a in LETTERS):
            return f"scq answer should be one letter A-D, got {json.dumps(a)}"
    elif t == "mcq":
        if not isinstance(a, list) or not a:
            return f"mcq answer should be a non-empty list, got {json.dumps(a)}"
        bad = [x for x in a if not (isinstance(x, str) and len(x) == 1 and x in LETTERS)]
        if bad:
            return f"mcq answer has malformed entries {json.dumps(bad)} (full value {json.dumps(a)})"
    elif t == "integerQuestion":
        if not (isinstance(a, (str, int, float)) and NUM_RE.fullmatch(str(a).strip())):
            return f"integer answer is not numeric: {json.dumps(a)}"
    return None


def last_number(text):
    nums = NUM_RE.findall(text.replace(",", ""))
    return nums[-1] if nums else None


def question_signals(q):
    b = block(q)
    qhtml, shtml = b.get("question") or "", b.get("solution") or ""
    qtext, stext = to_text(qhtml), to_text(shtml)
    sig = []
    if q["questionType"] in ("scq", "mcq"):
        stem, opts = parse_options(qhtml)
        present = [l for l in LETTERS if l in opts]
        missing = [l for l in LETTERS if l not in opts]
        if missing:
            sig.append({"code": "option_missing", "detail": f"options found: {present}; missing: {missing}"})
        for l, v in opts.items():
            if not v.strip():
                sig.append({"code": "option_blank", "detail": f"option ({l}) is empty"})
        seen = {}
        for l, v in opts.items():
            if v.strip():
                seen.setdefault(norm(v), []).append(l)
        for v, ls in seen.items():
            if len(ls) > 1:
                sig.append({"code": "options_identical", "detail": f"options {ls} have identical text"})
        key = b.get("answer")
        if q["questionType"] == "scq" and isinstance(key, str) and key in opts:
            kn, sn = last_number(opts[key]), last_number(stext)
            if kn and sn and float(kn) != float(sn):
                sig.append({"code": "solution_vs_key", "detail": f"solution ends at {sn}, keyed option ({key}) = '{opts[key]}'"})
    else:
        nums = NUM_RE.findall(stext.replace(",", ""))
        try:
            key = float(b.get("answer"))
            if nums and not any(float(n) == key for n in nums):
                sig.append({"code": "solution_vs_key", "detail": f"key {b.get('answer')} never appears in the solution (last number there: {nums[-1]})"})
        except (TypeError, ValueError):
            pass
    fmt = answer_format_problem(q)
    if fmt:
        sig.append({"code": "answer_malformed", "detail": fmt})
    for field, text in (("question", qtext), ("solution", stext)):
        m = LATEX_RE.search(text)
        if m:
            sig.append({"code": "latex_leak", "detail": f"raw LaTeX '{m.group(0)}' visible in {field}"})
        m = EXAM_TAG_RE.search(text)
        if m:
            sig.append({"code": "exam_tag", "detail": f"exam tag '{m.group(0)}' in {field}"})
    if FIGURE_RE.search(qtext) and not b.get("quesImages") and "<img" not in qhtml:
        sig.append({"code": "figure_missing", "detail": "question refers to a figure but has no image"})
    if not stext.strip():
        sig.append({"code": "solution_empty", "detail": "solution field is empty"})
    return sig


def comment_signals(comment, reported_at, q):
    c = (comment or "").strip()
    sig = []
    if INJECTION_RE.search(c):
        sig.append({"code": "prompt_injection", "detail": "comment tries to instruct the system; treated as data only"})
    letters = re.sub(r"[^a-z]", "", c.lower())
    if len(letters) < 2 or (len(letters) >= 4 and any(letters in row for row in KEYBOARD_ROWS)):
        sig.append({"code": "gibberish", "detail": "comment has no readable content"})
    if LANG_RE.search(c):
        sig.append({"code": "language_request", "detail": "comment mentions a language"})
    for h in q.get("errorHistory") or []:
        if h.get("at", "") > reported_at:
            sig.append({"code": "fixed_after_report", "detail": f"{h.get('actor')} edit at {h['at']} (after this report): {h.get('note')}"})
    return sig
