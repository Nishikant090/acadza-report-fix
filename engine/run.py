"""Report -> Fix pipeline.

  python engine/run.py            # replay cached model outputs (no key needed)
  ANTHROPIC_API_KEY=... python engine/run.py --live   # call Claude for anything not cached

Stages
  0. group reports by question (one model call per question, not per report)
  1. deterministic checks on the question and on each comment          detectors.py
  2. blind solve: model sees stem + options only                        prompts.SOLVER_*
  3. triage: model sees record + checks + blind solve + all reports     prompts.TRIAGE_*
  4. guards: code decides the route; the model only proposes            guard()
  5. write results.json, bonus_findings.json, console/data.js
"""
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import llm  # noqa: E402
import prompts as P  # noqa: E402
from detectors import block, comment_signals, parse_options, question_signals  # noqa: E402
from htmltext import to_text  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
AUTO_MIN_CONF = 0.80
SEVERITY = {
    "answer_key": 10, "type_mismatch": 9, "unsound": 9, "stem_data": 8, "option_repair": 8,
    "diagram": 7, "identical_options": 7, "wrong_question": 7, "solution_fix": 5, "solution_missing": 5,
    "markup_leak": 4, "notation": 4, "answer_form": 3, "wrong_chapter": 3, "syllabus": 2,
    "spelling": 1, "noise": 1, "exam_reference": 1,
}


def load(name):
    return json.loads((ROOT / "data" / name).read_text(encoding="utf-8"))


def same_answer(a, b):
    norm = lambda x: sorted(x) if isinstance(x, list) else (str(x).strip().upper() if x is not None else None)
    try:
        return float(a) == float(b)
    except (TypeError, ValueError):
        return norm(a) == norm(b)


def is_pure_insertion(old, new):
    """True if `new` is `old` with one contiguous chunk inserted (nothing deleted or changed)."""
    if len(new) < len(old):
        return False
    i = 0
    while i < len(old) and old[i] == new[i]:
        i += 1
    return old[i:] == new[len(new) - (len(old) - i):]


def apply_edit(q, edit):
    """Return (before, after) of the edited field, or raise ValueError if the edit is not surgical/valid."""
    b = block(q)
    f = edit["field"]
    if f == "answer":
        if json.dumps(b.get("answer")) != json.dumps(edit["find"]):
            raise ValueError(f"answer edit 'find' {json.dumps(edit['find'])} != stored {json.dumps(b.get('answer'))}")
        return b.get("answer"), edit["replace"]
    if f == "questionType":
        if q["questionType"] != edit["find"]:
            raise ValueError("questionType find does not match")
        return q["questionType"], edit["replace"]
    cur = b.get(f) or ""
    n = cur.count(edit["find"])
    if n != 1:
        raise ValueError(f"'find' occurs {n} times in {f} (must be exactly 1)")
    return cur, cur.replace(edit["find"], edit["replace"], 1)


def guard(q, res, solve, csig, tax):
    """Code-level safety policy. Returns (route, guard_notes, after_value)."""
    notes = []
    verdict, repair, edit = res["verdict"], res.get("repair"), res.get("edit")
    if verdict not in tax["verdicts"]:
        notes.append(f"BLOCK unknown verdict {verdict}")
        return "faculty_review", notes, None
    if verdict != "defect":
        if res.get("repair") or edit:
            notes.append("dropped repair/edit: verdict is not a defect")
        res["repair"], res["edit"] = None, None
        # a 'no_error' that the blind solver contradicts must not silently close
        if verdict == "no_error" and solve.get("answer") is not None and not same_answer(solve["answer"], block(q).get("answer")):
            notes.append(f"ESCALATE blind solve says {solve['answer']}, key says {block(q).get('answer')}")
            return "faculty_review", notes, None
        return "no_change", notes, None
    if repair not in tax["repairs"]:
        notes.append(f"BLOCK unknown repair {repair}")
        return "faculty_review", notes, None
    rule = tax["repairs"][repair]
    if not rule["auto"]:
        if edit:
            notes.append("dropped edit: repair is auto:false (human must author)")
            res["edit"] = None
        notes.append(f"{repair} is human-only per taxonomy")
        return "faculty_review", notes, None
    if not edit:
        notes.append("defect without a concrete edit")
        return "faculty_review", notes, None
    # scope
    if edit["field"] not in rule["fields"]:
        notes.append(f"BLOCK field '{edit['field']}' outside scope {rule['fields']} of {repair}")
        res["edit"] = None
        return "faculty_review", notes, None
    try:
        before, after = apply_edit(q, edit)
    except ValueError as e:
        notes.append(f"BLOCK {e}")
        return "faculty_review", notes, None
    notes.append(f"scope ok: {edit['field']} in {rule['fields']}; find matched exactly once")
    route = "auto_apply"
    # repair-specific invariants
    if repair == "answer_key":
        if solve.get("answer") is None or not same_answer(solve["answer"], edit["replace"]):
            notes.append(f"HOLD blind solve ({solve.get('answer')}) does not confirm new key {edit['replace']}")
            route = "faculty_review"
        elif solve.get("confidence", 0) < 0.8:
            notes.append("HOLD blind solve confidence < 0.8")
            route = "faculty_review"
        else:
            notes.append(f"blind solve independently gives {solve['answer']}")
    if repair == "spelling":
        if re.findall(r"\d", edit["find"]) != re.findall(r"\d", edit["replace"]) or "<" in edit["find"] + edit["replace"]:
            notes.append("HOLD spelling edit moves a digit or tag")
            route = "faculty_review"
    if repair == "answer_form" and not is_pure_insertion(edit["find"], edit["replace"]):
        notes.append("HOLD answer_form must be additive")
        route = "faculty_review"
    if repair == "option_repair":
        s0, o0 = parse_options(before)
        s1, o1 = parse_options(after)
        if s0 != s1:
            notes.append("HOLD option_repair changed the stem")
            route = "faculty_review"
        elif any(o0.get(l, "").strip() and o0[l] != o1.get(l) for l in o0):
            notes.append("HOLD option_repair changed a non-empty option")
            route = "faculty_review"
        else:
            notes.append("stem and existing options unchanged")
    if any(s["code"] == "prompt_injection" for s in csig):
        notes.append("HOLD comment contains instructions; never auto-apply from it")
        route = "faculty_review"
    if res.get("confidence", 0) < AUTO_MIN_CONF:
        notes.append(f"HOLD confidence {res.get('confidence')} < {AUTO_MIN_CONF}")
        route = "faculty_review"
    return route, notes, after


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    live = "--live" in sys.argv
    qs = {q["_id"]: q for q in load("questions.json")}
    reports = load("reports.json")
    tax = load("taxonomy.json")
    stats = defaultdict(int)
    groups = defaultdict(list)
    for r in reports:
        groups[r["questionId"]].append(r)

    repairs_txt = "\n".join(f"- {k}: fields={v['fields']} auto={str(v['auto']).lower()} - {v['label']}" for k, v in tax["repairs"].items())
    verdicts_txt = ", ".join(tax["verdicts"])
    triage_system = P.TRIAGE_SYSTEM.format(verdicts=verdicts_txt, repairs=repairs_txt)

    results, cases, bonus = [], [], []
    for qid, q in qs.items():
        b = block(q)
        qsig = question_signals(q)
        solve = llm.call("solver", qid, P.SOLVER_SYSTEM, P.SOLVER_USER.format(
            qtype=q["questionType"], subject=q["subject"], chapter=q["chapter"], question_text=to_text(b.get("question"))), stats)
        reps = sorted(groups.get(qid, []), key=lambda r: r["reportedAt"])
        csigs = {r["reportId"]: comment_signals(r["comment"], r["reportedAt"], q) for r in reps}
        user = P.TRIAGE_USER.format(
            qid=qid, qtype=q["questionType"], subject=q["subject"], chapter=q["chapter"], updated=q["updatedAt"],
            question_html=b.get("question"), answer=json.dumps(b.get("answer")), solution_html=b.get("solution"),
            qimgs=len(b.get("quesImages") or []), simgs=len(b.get("solutionImages") or []),
            history=json.dumps(q.get("errorHistory") or []),
            signals="\n".join(f"- {s['code']}: {s['detail']}" for s in qsig) or "- none",
            solve=json.dumps(solve, ensure_ascii=False),
            reports="\n".join(P.REPORT_ITEM.format(rid=r["reportId"], source=r["source"], at=r["reportedAt"],
                                                  flags=",".join(s["code"] for s in csigs[r["reportId"]]),
                                                  comment=r["comment"].replace("<", "&lt;")) for r in reps) or "(no reports - proactive scan)")
        tri = llm.call("triage", qid, triage_system, user, stats)
        by_id = {x["reportId"]: x for x in tri.get("reports", [])}
        case_reports = []
        for r in reps:
            res = dict(by_id[r["reportId"]])
            route, notes, after = guard(q, res, solve, csigs[r["reportId"]], tax)
            out = {
                "reportId": r["reportId"], "questionId": qid, "verdict": res["verdict"], "repair": res.get("repair"),
                "edit": res.get("edit"), "route": route, "confidence": res.get("confidence"),
                "evidence": res["evidence"], "student_reply": res["student_reply"],
            }
            results.append(out)
            case_reports.append({**out, "comment": r["comment"], "source": r["source"], "reportedAt": r["reportedAt"],
                                 "studentId": r["studentId"], "signals": csigs[r["reportId"]], "guard": notes,
                                 "after": after})
        for u in tri.get("unreported", []):
            bonus.append({"questionId": qid, **u})
        if case_reports:
            defects = [c for c in case_reports if c["verdict"] == "defect"]
            sev = max([SEVERITY.get(c["repair"], 0) for c in defects] or [0])
            urgency = round(sev * (1 + 0.5 * (len(case_reports) - 1)), 1)
            cases.append({"questionId": qid, "urgency": urgency, "severity": sev, "reports": case_reports,
                          "signals": qsig, "solve": solve})

    order = {r["reportId"]: i for i, r in enumerate(reports)}
    results.sort(key=lambda r: r["reportId"])
    (ROOT / "results.json").write_text(json.dumps(results, indent=1, ensure_ascii=False), encoding="utf-8")
    (ROOT / "bonus_findings.json").write_text(json.dumps(bonus, indent=1, ensure_ascii=False), encoding="utf-8")
    console = {
        "generatedWith": {"solver": llm.MODELS["solver"], "triage": llm.MODELS["triage"],
                          "prompts": [P.SOLVER_VERSION, P.TRIAGE_VERSION], "mode": "live" if live else "cached"},
        "taxonomy": tax, "cases": cases, "bonus": bonus,
        "questions": {qid: {"_id": qid, "questionType": q["questionType"], "subject": q["subject"], "chapter": q["chapter"],
                            "level": q["level"], "errorHistory": q.get("errorHistory"), **{k: block(q).get(k) for k in ("question", "solution", "answer", "quesImages")}}
                      for qid, q in qs.items()},
    }
    (ROOT / "console" / "data.js").write_text("window.DATA = " + json.dumps(console, ensure_ascii=False) + ";\n", encoding="utf-8")

    routes = defaultdict(int)
    for r in results:
        routes[r["route"]] += 1
    print(f"{len(results)} reports on {len(cases)} questions -> {dict(routes)}")
    print(f"bonus (unreported) findings: {len(bonus)}")
    print(f"model calls: api={stats['api_calls']} cached={stats['cache_hits']} tokens in/out={stats['input_tokens']}/{stats['output_tokens']}")
    held = [(r["reportId"], n) for c in cases for r in c["reports"] for n in r["guard"] if n.startswith(("BLOCK", "HOLD", "ESCALATE"))]
    for rid, n in held:
        print(f"  guard {rid}: {n}")


if __name__ == "__main__":
    main()
