# PRODUCT.md

**Who loses most when a question is broken?** The student who got it *right*. A wrong or malformed key (LCR 50 V keyed as 130 V, an MCQ key stored as `"A, B, D"`) takes marks from exactly the students who did the physics correctly. It also teaches them to doubt a method that works, weeks before JEE. That damage repeats for every student who meets the question until someone fixes it. The student who reports a typo loses a second of reading.

How the design reflects this:
- **Urgency = harm × reach.** A wrong key scores 10, missing data or option 8, a solution error 5, a spelling slip 1. Each extra reporter adds 50%. The 3-student wrong-key case is first in its section, and the "plexux" typo is near the bottom.
- **Wrong keys get fixed fast and safely.** They auto-apply, but only when a solver that never saw the key reaches the same new answer. Everything else waits for a human.
- **The reply tells the student they were right**, in plain words: "You're right… the key was wrong; it's (A)." A student who was wrong gets the one step they missed, not "checked, no error". R004 gets both: the key *was* wrong, and 8225 is wrong too.

**What I would never let the AI auto-apply**
1. **An answer-key change the independent solve does not reproduce.** If the solver says "can't tell" or disagrees, a human decides. A wrong "fix" to a key is worse than the original bug, because it now carries our authority.
2. **Authored content**: new distractors, figures, rewrites of unsound questions, a solution written from scratch for a question we can't solve. The taxonomy allows auto-restoring a missing option. I would tighten that in production so that only a blank option whose value is *derivable* (R011's 1 : 1) auto-fills, while an invented distractor (R009's 5 m/s) waits for a teacher.
3. **Anything triggered by a comment that contains instructions** (R027), and any chapter move or syllabus removal. Those change what students are assigned, not just what they read.

**One metric for week 1: the revert rate of auto-applied fixes**, the share of auto-applied edits that faculty revert or edit in the spot-check queue. It measures the one thing that would make faculty stop trusting the system. Target < 2% overall and **0** on `answer_key`. Any key revert pauses key auto-apply until we understand why.

**One idea beyond the brief: catch broken questions before anyone reports them, and repair the damage after.**
- *Detect.* Most students never tap "Report". But a wrong key leaves a signature in the attempt data: strong students (top quartile on the test) pick the same non-key option far more often than weak ones. A nightly job can flag questions where top-quartile agreement on one non-key option exceeds about 40% and send them through this same pipeline with no report attached. The "Found without a report" tab already proves the pipeline works without a report (11 extra defects here).
- *Repair.* When a key changes, re-score every past attempt on that question. Then send the affected students one line: "Your answer to Q… was right; we fixed our key and your score." That turns our mistake into a moment of trust, and it is the message a stressed 17-year-old remembers.
