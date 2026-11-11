"""Safety tests for the guard layer. Run: python engine/test_guards.py"""
import copy
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from run import ROOT, guard, is_pure_insertion  # noqa: E402

TAX = json.loads((ROOT / "data" / "taxonomy.json").read_text(encoding="utf-8"))
QS = {q["_id"]: q for q in json.loads((ROOT / "data" / "questions.json").read_text(encoding="utf-8"))}
LCR = QS["60f744b3f1b9bc7cc7b4a949"]          # key C, true answer A
SOLVE_A = {"answer": "A", "confidence": 0.99}


def res(**kw):
    base = {"verdict": "defect", "repair": "answer_key", "edit": {"field": "answer", "find": "C", "replace": "A"}, "confidence": 0.95}
    base.update(kw)
    return base


class Guards(unittest.TestCase):
    def test_good_answer_key_auto_applies(self):
        route, notes, after = guard(LCR, res(), SOLVE_A, [], TAX)
        self.assertEqual(route, "auto_apply")
        self.assertEqual(after, "A")

    def test_key_change_not_confirmed_by_blind_solve_is_held(self):
        route, notes, _ = guard(LCR, res(edit={"field": "answer", "find": "C", "replace": "B"}), SOLVE_A, [], TAX)
        self.assertEqual(route, "faculty_review")

    def test_scope_violation_blocked(self):
        # a 'spelling' repair may not touch the answer field
        route, notes, _ = guard(LCR, res(repair="spelling"), SOLVE_A, [], TAX)
        self.assertEqual(route, "faculty_review")
        self.assertTrue(any("outside scope" in n for n in notes))

    def test_injection_never_auto(self):
        route, _, _ = guard(LCR, res(), SOLVE_A, [{"code": "prompt_injection"}], TAX)
        self.assertEqual(route, "faculty_review")

    def test_find_must_match_exactly_once(self):
        r = res(repair="spelling", edit={"field": "question", "find": "ohm", "replace": "Ohm"})
        q = QS["60f742f6660d187cc13a8078"]  # 'ohm' appears 5 times
        route, notes, _ = guard(q, r, {"answer": "C", "confidence": 0.9}, [], TAX)
        self.assertEqual(route, "faculty_review")

    def test_human_only_repair_drops_edit(self):
        r = res(repair="identical_options", edit={"field": "question", "find": "x", "replace": "y"})
        route, _, _ = guard(LCR, r, SOLVE_A, [], TAX)
        self.assertEqual(route, "faculty_review")
        self.assertIsNone(r["edit"])

    def test_no_error_contradicted_by_solver_escalates(self):
        route, _, _ = guard(LCR, res(verdict="no_error", repair=None, edit=None), SOLVE_A, [], TAX)
        self.assertEqual(route, "faculty_review")

    def test_low_confidence_held(self):
        route, _, _ = guard(LCR, res(confidence=0.6), SOLVE_A, [], TAX)
        self.assertEqual(route, "faculty_review")

    def test_spelling_cannot_move_digits(self):
        q = QS["61dffbec08489156b684bd22"]
        r = res(repair="spelling", edit={"field": "question", "find": "Epithellial tisue", "replace": "Epithelial tissue 2"})
        route, _, _ = guard(q, r, {"answer": "A", "confidence": 0.9}, [], TAX)
        self.assertEqual(route, "faculty_review")

    def test_option_repair_cannot_change_stem(self):
        q = QS["68e872546e45ba37dcc16bc0"]
        r = res(repair="option_repair", edit={"field": "question", "find": "certain distance", "replace": "fixed distance"})
        route, _, _ = guard(q, r, {"answer": None, "confidence": 0.9}, [], TAX)
        self.assertEqual(route, "faculty_review")

    def test_pure_insertion(self):
        self.assertTrue(is_pure_insertion("force is", "force (in N) is"))
        self.assertFalse(is_pure_insertion("force is", "force was"))


class Results(unittest.TestCase):
    def test_results_file_is_complete_and_safe(self):
        results = json.loads((ROOT / "results.json").read_text(encoding="utf-8"))
        reports = json.loads((ROOT / "data" / "reports.json").read_text(encoding="utf-8"))
        self.assertEqual({r["reportId"] for r in results}, {r["reportId"] for r in reports})
        for r in results:
            self.assertIn(r["verdict"], TAX["verdicts"])
            self.assertIn(r["route"], ("auto_apply", "faculty_review", "no_change"))
            if r["route"] == "auto_apply":
                rule = TAX["repairs"][r["repair"]]
                self.assertTrue(rule["auto"], r["reportId"])
                self.assertIn(r["edit"]["field"], rule["fields"], r["reportId"])
            if r["verdict"] != "defect":
                self.assertEqual(r["route"], "no_change", r["reportId"])
            self.assertTrue(1 <= r["student_reply"].count(".") + r["student_reply"].count("!") + r["student_reply"].count("?") <= 6)


if __name__ == "__main__":
    unittest.main(verbosity=1)
