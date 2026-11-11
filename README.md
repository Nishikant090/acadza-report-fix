# Report → Fix

Turns free-text student error reports on JEE/NEET questions into safe, surgical fixes, and gives faculty a review console they can clear at 10 PM.

- **`results.json`**: triage of all 44 reports (the auto-scored deliverable)
- **`console/`**: faculty review console (static site, deploy as-is)
- **`PROMPTS.md`**: every prompt in the product, verbatim; build log; where the AI was wrong
- **`PRODUCT.md`**: one-page product thinking
- **`bonus_findings.json`**: 11 defects nobody reported
- **`BRIEF.md`**: the original assignment brief

## Project layout

```
acadza-report-fix/
├── data/                    # input, untouched: questions.json, reports.json, taxonomy.json
├── engine/                  # the triage pipeline (Python 3.10+, stdlib only)
│   ├── run.py               #   orchestration + safety guards → writes results.json and console/data.js
│   ├── detectors.py         #   deterministic checks (blank/missing/duplicate options, LaTeX leaks, malformed keys, injection…)
│   ├── prompts.py           #   the two model prompts (blind solver, triage)
│   ├── llm.py               #   minimal Claude Messages API client + response cache
│   ├── htmltext.py          #   HTML + MathML → readable text for prompts and checks
│   ├── test_guards.py       #   12 safety tests (scope, injection, unconfirmed key changes…)
│   └── cache/               #   recorded model outputs (solver.json, triage.json)
├── console/                 # the faculty console: index.html, app.js, styles.css, data.js (generated)
├── results.json             # deliverable
├── bonus_findings.json      # unreported defects
├── PROMPTS.md  PRODUCT.md  BRIEF.md  README.md
└── netlify.toml  vercel.json
```

## Run it

```bash
python engine/run.py                 # replays recorded model outputs: no key, no cost, deterministic
python engine/test_guards.py         # safety tests
# open console/index.html in a browser, or serve it:
python -m http.server -d console 8000
```

Live mode, which calls Claude for every question whose prompt changed or isn't cached:

```bash
ANTHROPIC_API_KEY=sk-... python engine/run.py --live
```

## Pipeline

```
reports ──group by question──▶ 1 deterministic checks ──▶ 2 BLIND SOLVE ──▶ 3 TRIAGE ──▶ 4 GUARDS (code) ──▶ route
                                 (no LLM, free)            (stem+options      (record + checks     scope · find-exactly-once ·
                                                            only: no key,      + blind solve +      key change must match blind
                                                            no solution,       all reports;         solve · injection → human ·
                                                            no comment)        comments untrusted)  auto:false → human · conf ≥ 0.8
```

- **The model proposes; code routes.** No prompt can make an edit auto-apply. Only `guard()` in `run.py` decides `auto_apply`.
- **The key is checked by a witness that never saw it.** An `answer_key` change auto-applies only if the blind solver independently reaches the new key. A `no_error` that the blind solver contradicts is escalated, never silently closed.
- **One call per question, not per report.** The 3 reports on the LCR question share one solve and one triage, so they get consistent verdicts and one edit.

Result on the 44 reports: **22 auto-apply · 6 faculty review · 16 no change**. 11 more defects found in questions nobody reported.

## Console

The queue is grouped by question, in three sections:

1. **Needs your decision**: human-only repairs (figure, duplicate options, unsound, chapter, syllabus)
2. **Auto-applied · spot-check**: already live. Keep, edit, or revert in one click
3. **No change · replies ready**: the question is fine. Approve to send replies

Within each section, cases are sorted by **urgency = harm severity × (1 + 0.5 × extra reporters)**. A wrong answer key scores 10 because it takes marks from every student who solved it correctly. A spelling slip scores 1. A wrong key reported by 3 students scores 20 and goes to the top.

For each case the console shows: a one-line headline of what changed, a rendered before/after diff (MathML renders natively), the old and new key on the option list, the blind solve, every automatic check and guard, each student's comment with the reply they will get, and Approve / Edit / Reject with keyboard shortcuts (J/K/A/E/R). Every action goes into the audit log, which can be exported as JSON.

> The live console loads **precomputed results**. It makes no AI calls. Decisions and the audit log are stored in the reviewer's browser (localStorage). In production these would be POSTed to the API.

## Deploy

Deploy the `console/` folder as-is (already configured in `netlify.toml` / `vercel.json`):

- **Netlify Drop:** drag the `console` folder onto https://app.netlify.com/drop
- **Vercel:** `npx vercel --prod` from the repo root
- **GitHub Pages:** copy `console/` to `docs/`, then Settings → Pages → deploy from branch, folder `/docs`
