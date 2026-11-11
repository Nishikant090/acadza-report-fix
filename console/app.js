/* Report → Fix faculty console. Static, no build step. Data comes from data.js (written by engine/run.py). */
(() => {
  const D = window.DATA;
  const Q = D.questions;
  const TAX = D.taxonomy;
  const $ = (s, el = document) => el.querySelector(s);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  // ---------- persistence (per-browser; production would POST these to the API) ----------
  const store = {
    get(k, d) { try { const v = localStorage.getItem(k); return v ? JSON.parse(v) : d; } catch { return d; } },
    set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* private mode: keep in memory */ } },
  };
  let decisions = store.get("rf.decisions", {});
  let audit = store.get("rf.audit", []);
  const reviewerEl = $("#reviewer");
  reviewerEl.value = store.get("rf.reviewer", "");
  reviewerEl.addEventListener("change", () => store.set("rf.reviewer", reviewerEl.value.trim()));
  const reviewer = () => reviewerEl.value.trim() || "faculty (unnamed)";

  // theme
  const savedTheme = store.get("rf.theme", null);
  if (savedTheme) document.documentElement.dataset.theme = savedTheme;
  $("#themeBtn").onclick = () => {
    const dark = document.documentElement.dataset.theme ? document.documentElement.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
    document.documentElement.dataset.theme = dark ? "light" : "dark";
    store.set("rf.theme", document.documentElement.dataset.theme);
  };

  $("#modeNote").textContent = `Precomputed run · ${D.cases.reduce((n, c) => n + c.reports.length, 0)} reports on ${D.cases.length} questions · no live AI calls from this page`;

  // ---------- labels ----------
  const VERDICT = {
    defect: ["Defect", "defect"], no_error: ["No error", "ok"], display_issue: ["Display issue", "info"], app_issue: ["App issue", "info"],
    language_mode: ["Language request", "info"], already_fixed: ["Already fixed", "ok"], not_actionable: ["Not actionable", ""],
  };
  const HEAD = {
    answer_key: (e) => `Answer key is wrong: ${fmtAns(e.find)} → ${fmtAns(e.replace)}`,
    stem_data: () => "A value the question needs was missing; added from the solution",
    option_repair: () => "An option was missing or blank; restored",
    spelling: () => "Spelling fix", noise: () => "Stray text removed", exam_reference: () => "Exam tag removed from the question",
    markup_leak: () => "Raw LaTeX was showing; replaced with real math", answer_form: () => "Unit added to the question",
    notation: () => "Lost symbol restored", solution_fix: () => "Solution has a wrong step; corrected",
    solution_missing: () => "Solution missing; written", type_mismatch: () => "Stored as the wrong question type",
    identical_options: () => "Two options are identical; needs a new distractor", diagram: () => "Figure is missing; needs an upload",
    wrong_question: () => "Question and solution don't belong together", unsound: () => "No option is correct as written; needs a rewrite",
    wrong_chapter: () => "Filed under the wrong chapter", syllabus: () => "Student says out of syllabus; confirm",
  };
  const HEAD_NONDEFECT = {
    no_error: "Key verified. The student made a mistake", display_issue: "Content is fine. Display/loading problem",
    app_issue: "Content is fine. App recorded the wrong thing", language_mode: "Language request. Content is fine",
    already_fixed: "Already fixed in the live record", not_actionable: "Unreadable report. Question checked, nothing found",
  };
  const ROUTE = {
    faculty_review: { sec: "Needs your decision", hint: "AI may not write these. Confirm the triage, or override it.", ok: "Confirm", no: "Override" },
    auto_apply: { sec: "Auto-applied · spot-check", hint: "Already live. Keep it, edit it, or revert in one click.", ok: "Keep fix", no: "Revert" },
    no_change: { sec: "No change · replies ready", hint: "Question is fine. Approve to send the replies.", ok: "Send replies", no: "Reopen" },
  };
  const fmtAns = (a) => (a === null || a === undefined ? "could not solve" : Array.isArray(a) ? "[" + a.map((x) => (x === "" ? "∅ blank" : x)).join(", ") + "]" : String(a));

  // ---------- case model ----------
  const routeOf = (c) => (c.reports.some((r) => r.route === "faculty_review") ? "faculty_review" : c.reports.some((r) => r.route === "auto_apply") ? "auto_apply" : "no_change");
  const lead = (c) => [...c.reports].sort((a, b) => (b.verdict === "defect") - (a.verdict === "defect") || (b.edit ? 1 : 0) - (a.edit ? 1 : 0))[0];
  const headline = (c) => { const r = lead(c); return r.verdict === "defect" ? (HEAD[r.repair] || (() => r.repair))(r.edit || {}) : HEAD_NONDEFECT[r.verdict]; };
  const cases = D.cases.map((c) => ({ ...c, route: routeOf(c) }));
  const order = ["faculty_review", "auto_apply", "no_change"];
  cases.sort((a, b) => order.indexOf(a.route) - order.indexOf(b.route) || b.urgency - a.urgency || b.reports.length - a.reports.length);
  const fromHash = new URLSearchParams(location.hash.slice(1)).get("q");
  let sel = cases.some((c) => c.questionId === fromHash) ? fromHash : cases[0]?.questionId;
  let editing = false, rejecting = false;

  // ---------- html helpers ----------
  function clean(html) {
    const t = document.createElement("template");
    t.innerHTML = html || "";
    t.content.querySelectorAll("script,iframe,object,embed,link,style,form").forEach((n) => n.remove());
    t.content.querySelectorAll("*").forEach((n) => [...n.attributes].forEach((a) => {
      if (/^on/i.test(a.name) || /^\s*javascript:/i.test(a.value)) n.removeAttribute(a.name);
    }));
    return t.innerHTML;
  }
  const textOf = (html) => { const t = document.createElement("template"); t.innerHTML = html || ""; return t.content.textContent.replace(/\s+/g, " ").trim(); };
  function options(html) {
    const text = textOf(html);
    const marks = [...text.matchAll(/\(([A-D])\)/g)];
    let start = -1;
    for (let i = marks.length - 1; i >= 0; i--) if (marks[i][1] === "A") { start = i; break; }
    if (start < 0) return {};
    const run = marks.slice(start), out = {};
    run.forEach((m, j) => { const end = j + 1 < run.length ? run[j + 1].index : text.length; out[m[1]] = text.slice(m.index + 3, end).trim(); });
    return out;
  }
  const stem = (html) => { const t = textOf(html); const i = t.search(/\(A\)(?![\s\S]*\(A\))/); return (i > 0 ? t.slice(0, i) : t).trim(); };

  // Highlight the changed region of before/after HTML without breaking MathML or tags.
  function diffMarks(before, after) {
    let p = 0;
    while (p < before.length && p < after.length && before[p] === after[p]) p++;
    let s = 0;
    while (s < before.length - p && s < after.length - p && before[before.length - 1 - s] === after[after.length - 1 - s]) s++;
    const widen = (str, a, b) => {
      // never cut inside a tag
      const lt = str.lastIndexOf("<", a - 1), gt = str.lastIndexOf(">", a - 1);
      if (lt > gt) a = lt;
      const nlt = str.indexOf("<", b), ngt = str.indexOf(">", b);
      if (ngt !== -1 && (nlt === -1 || ngt < nlt)) b = ngt + 1;
      // never cut inside <math>…</math>
      const mo = str.lastIndexOf("<math", a), mc = str.lastIndexOf("</math>", a);
      if (mo !== -1 && mo > mc) a = mo;
      const no = str.indexOf("<math", b), nc = str.indexOf("</math>", b);
      if (nc !== -1 && (no === -1 || nc < no)) b = nc + 7;
      return [a, b];
    };
    let [a1, b1] = widen(before, p, before.length - s);
    let [a2, b2] = widen(after, p, after.length - s);
    const a = Math.min(a1, a2), sb = Math.min(before.length - b1, after.length - b2);
    const B = before.slice(a, before.length - sb), A = after.slice(a, after.length - sb);
    const visible = (x) => !!x && (textOf(x) !== "" || /<math|<img/.test(x));
    return {
      before: before.slice(0, a) + (visible(B) ? `<mark class="del">${B}</mark>` : B) + before.slice(before.length - sb),
      after: after.slice(0, a) + (A ? `<mark class="ins">${A}</mark>` : `<mark class="ins empty"></mark>`) + after.slice(after.length - sb),
    };
  }

  // ---------- queue ----------
  function renderQueue() {
    const el = $("#queue");
    let html = "";
    for (const route of order) {
      const list = cases.filter((c) => c.route === route);
      if (!list.length) continue;
      const pending = list.filter((c) => !decisions[c.questionId]).length;
      html += `<div class="qsec"><h3><span>${ROUTE[route].sec}</span><span>${pending}/${list.length} open</span></h3><p>${ROUTE[route].hint}</p></div>`;
      for (const c of list) {
        const q = Q[c.questionId], r = lead(c), dec = decisions[c.questionId];
        const u = c.severity >= 8 ? "u3" : c.severity >= 4 ? "u2" : c.severity > 0 ? "u1" : "";
        html += `<button class="qitem ${c.questionId === sel ? "sel" : ""} ${dec ? "done" : ""}" data-q="${c.questionId}">
          <span class="urg ${u}" title="Urgency ${c.urgency}">${c.urgency || "–"}</span>
          <span style="min-width:0">
            <span class="qline1">${esc(headline(c).split(":")[0])}${dec ? `<span class="statusdot ${dec.status}">${dec.status === "approved" ? "✓ " + esc(ROUTE[route].ok) : dec.status === "edited" ? "✎ Edited" : "✕ " + esc(ROUTE[route].no)}</span>` : ""}</span>
            <span class="qline2">${esc(stem(q.question).slice(0, 90))}</span>
            <span class="qline3"><span class="ch">${esc(q.subject)} · ${esc(q.chapter)}</span><span>${c.reports.length} report${c.reports.length > 1 ? "s" : ""}</span></span>
          </span></button>`;
      }
    }
    el.innerHTML = html;
    el.querySelectorAll(".qitem").forEach((b) => (b.onclick = () => select(b.dataset.q)));
  }

  function select(qid, scroll = true) {
    sel = qid; editing = false; rejecting = false;
    history.replaceState(null, "", "#q=" + qid);
    renderQueue(); renderDetail();
    if (scroll) $(`.qitem[data-q="${qid}"]`)?.scrollIntoView({ block: "nearest" });
    $("#detail").scrollTop = 0;
  }

  // ---------- detail ----------
  function renderDetail() {
    const c = cases.find((x) => x.questionId === sel);
    if (!c) { $("#detail").innerHTML = `<div class="empty">Nothing in the queue.</div>`; return; }
    const q = Q[c.questionId], r = lead(c), dec = decisions[c.questionId], R = ROUTE[c.route];
    const edit = dec?.edit ?? r.edit;
    const rep = r.repair ? TAX.repairs[r.repair] : null;
    const [vl, vc] = VERDICT[r.verdict] || [r.verdict, ""];

    let h = `<div class="crumbs"><span>${esc(q.subject)} › ${esc(q.chapter)}</span><span>·</span><span>${esc(q.questionType.toUpperCase())}</span><span>·</span><span class="mono">${c.questionId}</span></div>
      <div class="headline">${esc(headline(c))}</div>
      <p class="why">${esc(r.evidence)}</p>
      <div class="decision">
        <button class="btn primary" id="okBtn">${esc(R.ok)} <kbd>A</kbd></button>
        ${edit || c.reports.length ? `<button class="btn" id="editBtn">Edit <kbd>E</kbd></button>` : ""}
        <button class="btn danger" id="noBtn">${esc(R.no)} <kbd>R</kbd></button>
        <span class="chip ${vc}">${vl}</span>
        ${rep ? `<span class="chip ${rep.auto ? "accent" : "warn"}">${esc(r.repair)} · ${rep.auto ? "auto-allowed" : "human only"}</span>` : ""}
        <span class="conf" title="Model confidence"><span class="bar"><i style="width:${Math.round((r.confidence || 0) * 100)}%"></i></span><span class="mono">${Math.round((r.confidence || 0) * 100)}%</span></span>
        <span class="state">${dec ? `${dec.status === "rejected" ? "✕" : "✓"} ${esc(dec.status)} by ${esc(dec.by)} · ${new Date(dec.at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}` : "Open"}</span>
      </div>`;
    if (rejecting) {
      h += `<div class="card"><div class="body"><label for="reason" style="font-size:13px;color:var(--muted)">Why are you overriding the AI? (goes in the audit log)</label>
        <textarea id="reason" class="edit" placeholder="e.g. key is actually correct; student's method is wrong"></textarea>
        <div class="editbar"><button class="btn danger" id="confirmNo">${esc(R.no)}</button><button class="btn" id="cancelNo">Cancel</button></div></div></div>`;
    }

    // what changes
    h += `<div class="card"><h4><span>What changes</span>${edit ? `<span class="mono" style="text-transform:none;letter-spacing:0">field: ${esc(edit.field)}</span>` : ""}</h4>`;
    if (!edit) {
      h += `<div class="nochange">${r.verdict === "defect" ? `No automatic edit. <b>${esc(rep?.label || "")}</b> Faculty must author this fix.` : "Nothing in the question changes. Only the student reply goes out."}</div>`;
    } else if (edit.field === "answer") {
      const opts = options(q.question);
      const newKey = [].concat(edit.replace), oldKey = [].concat(edit.find);
      h += `<div class="keyswap"><span class="keybox old"><small>was</small>${esc(fmtAns(edit.find))}</span><span class="arrow">→</span><span class="keybox new"><small>now</small>${esc(fmtAns(edit.replace))}</span>
        <span class="keynote">Independent solve (never saw the key): <b>${esc(fmtAns(c.solve.answer))}</b>. ${esc(c.solve.working)}</span></div>`;
      if (Object.keys(opts).length) {
        h += `<div class="body" style="border-top:1px solid var(--line)">` + Object.entries(opts).map(([L, t]) => {
          const isNew = newKey.includes(L), isOld = oldKey.some((k) => String(k).split(/,\s*/).includes(L)) && !isNew;
          return `<div class="optrow ${isNew ? "key" : isOld ? "oldkey" : ""}"><span class="L">${L}</span><span>${esc(t)}</span>${isNew ? `<span class="tag">NEW KEY</span>` : isOld ? `<span class="tag">OLD KEY</span>` : ""}</div>`;
        }).join("") + `</div>`;
      }
    } else {
      const before = q[edit.field] || "";
      const after = before.split(edit.find).join(edit.replace);
      const m = diffMarks(before, after);
      h += `<div class="diff"><div class="before"><div class="lbl">Before</div><div class="qhtml">${clean(m.before)}</div></div>
        <div class="after"><div class="lbl">After</div><div class="qhtml">${clean(m.after)}</div></div></div>`;
      if (editing) {
        h += `<div class="srcdiff"><label style="font-size:12px;color:var(--muted)">Replacement HTML for the highlighted text (must stay within <b>${esc(edit.field)}</b>)</label>
          <textarea id="editReplace" class="edit code">${esc(edit.replace)}</textarea></div>`;
      }
      h += `<details class="srcdiff"><summary>Exact source change</summary><pre class="d mono">${esc(edit.find)}</pre><pre class="i mono">${esc(edit.replace) || "(deleted)"}</pre></details>`;
    }
    h += `</div>`;

    // why we believe it
    const guards = [...new Set(c.reports.flatMap((x) => x.guard))];
    const sigs = [...c.signals, ...c.reports.flatMap((x) => x.signals)];
    h += `<div class="card"><h4>Why the AI believes this</h4><div class="body">
      <dl class="facts">
        <dt>Stored key</dt><dd class="mono">${esc(fmtAns(q.answer))}</dd>
        <dt>Independent solve</dt><dd><span class="mono">${esc(fmtAns(c.solve.answer))}</span> <span style="color:var(--muted)">(${Math.round(c.solve.confidence * 100)}%, saw stem + options only)</span>${c.solve.missing ? `<br><span class="flag">Missing: ${esc(c.solve.missing)}</span>` : ""}</dd>
        <dt>Automatic checks</dt><dd>${sigs.length ? `<ul class="checks">${sigs.map((s) => `<li><span class="${s.code === "prompt_injection" ? "b" : "h"}">●</span><span><b>${esc(s.code.replace(/_/g, " "))}</b>: ${esc(s.detail)}</span></li>`).join("")}</ul>` : `<span style="color:var(--muted)">No structural problems found</span>`}</dd>
        <dt>Safety guards</dt><dd>${guards.length ? `<ul class="checks">${guards.map((g) => `<li><span class="${/^(BLOCK)/.test(g) ? "b" : /^(HOLD|ESCALATE)/.test(g) ? "h" : "g"}">${/^(BLOCK|HOLD|ESCALATE)/.test(g) ? "▲" : "✓"}</span><span>${esc(g)}</span></li>`).join("")}</ul>` : `<span style="color:var(--muted)">n/a: nothing to write</span>`}</dd>
      </dl></div></div>`;

    // reports + replies
    h += `<div class="card"><h4><span>Student reports (${c.reports.length}) and replies</span></h4>`;
    for (const x of c.reports) {
      const [v2, vc2] = VERDICT[x.verdict] || [x.verdict, ""];
      const reply = dec?.replies?.[x.reportId] ?? x.student_reply;
      const inj = x.signals.some((s) => s.code === "prompt_injection");
      h += `<div class="rep"><div class="meta"><span class="mono">${x.reportId}</span><span>${esc(x.source)}</span><span>${new Date(x.reportedAt).toLocaleString([], { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}</span><span class="chip ${vc2}">${v2}</span>${inj ? `<span class="chip defect">instruction in comment, ignored</span>` : ""}</div>
        <div class="quote">“${esc(x.comment)}”</div>
        ${editing ? `<textarea class="edit" data-reply="${x.reportId}">${esc(reply)}</textarea>` : `<div class="reply"><div class="who2">Reply to student</div>${esc(reply)}</div>`}
      </div>`;
    }
    h += `</div>`;
    if (editing) h += `<div class="editbar" style="margin-bottom:16px"><button class="btn primary" id="saveEdit">Save &amp; approve</button><button class="btn" id="cancelEdit">Cancel</button></div>`;

    // full question
    h += `<div class="card"><h4><span>Question as students see it now</span>${(q.quesImages || []).length ? "" : ""}</h4><div class="body qhtml">${clean(q.question)}</div>
      <details class="sol"><summary>Stored solution</summary><div class="qhtml">${clean(q.solution)}</div></details></div>`;

    $("#detail").innerHTML = h;
    $("#okBtn").onclick = () => decide("approved");
    $("#noBtn").onclick = () => { rejecting = true; editing = false; renderDetail(); $("#reason")?.focus(); };
    if ($("#editBtn")) $("#editBtn").onclick = () => { editing = true; rejecting = false; renderDetail(); };
    if ($("#confirmNo")) { $("#confirmNo").onclick = () => decide("rejected", { note: $("#reason").value.trim() }); $("#cancelNo").onclick = () => { rejecting = false; renderDetail(); }; }
    if ($("#saveEdit")) {
      $("#cancelEdit").onclick = () => { editing = false; renderDetail(); };
      $("#saveEdit").onclick = () => {
        const replies = {};
        document.querySelectorAll("textarea[data-reply]").forEach((t) => (replies[t.dataset.reply] = t.value.trim()));
        let newEdit = edit;
        const ta = $("#editReplace");
        if (ta && edit) newEdit = { ...edit, replace: ta.value };
        decide("edited", { edit: newEdit, replies });
      };
    }
  }

  function decide(status, extra = {}) {
    const c = cases.find((x) => x.questionId === sel), r = lead(c);
    const entry = {
      at: new Date().toISOString(), by: reviewer(), action: status === "approved" ? ROUTE[c.route].ok : status === "edited" ? "Edited & approved" : ROUTE[c.route].no,
      status, questionId: c.questionId, reportIds: c.reports.map((x) => x.reportId), route: c.route, verdict: r.verdict, repair: r.repair,
      aiEdit: r.edit, finalEdit: extra.edit ?? (status === "rejected" ? null : r.edit), note: extra.note || "", replies: extra.replies || null,
    };
    decisions[c.questionId] = { status, by: entry.by, at: entry.at, edit: extra.edit, replies: extra.replies };
    audit.unshift(entry);
    store.set("rf.decisions", decisions); store.set("rf.audit", audit);
    toast(`${entry.action} · logged`);
    updateCounts();
    const next = cases.find((x) => !decisions[x.questionId]);
    select(next ? next.questionId : c.questionId);
  }

  // ---------- bonus + audit pages ----------
  function renderBonus() {
    const rows = D.bonus.map((b) => {
      const q = Q[b.questionId];
      return `<tr><td><b>${esc(q.subject)}</b> · ${esc(q.chapter)}<br><span style="color:var(--muted);font-size:13px">${esc(stem(q.question).slice(0, 110))}</span></td>
        <td><span class="chip ${TAX.repairs[b.repair]?.auto ? "accent" : "warn"}">${esc(b.repair)}</span><br><span style="font-size:12px;color:var(--muted)">${esc(b.field)}</span></td>
        <td>${esc(b.detail)}${b.edit ? `<div class="mono" style="margin-top:6px"><span style="background:var(--del);padding:1px 4px;border-radius:4px">${esc(b.edit.find)}</span> → <span style="background:var(--ins);padding:1px 4px;border-radius:4px">${esc(b.edit.replace)}</span></div>` : ""}</td></tr>`;
    }).join("");
    $("#view-bonus").innerHTML = `<h2>Found without a report</h2><p class="lead">While triaging, the AI also read every question with no reports. These are proposals only; nothing here is auto-applied.</p>
      <table class="tbl"><thead><tr><th style="width:34%">Question</th><th style="width:14%">Repair</th><th>Finding</th></tr></thead><tbody>${rows}</tbody></table>`;
  }
  function renderAudit() {
    const rows = audit.map((a) => `<tr><td class="mono">${new Date(a.at).toLocaleString()}</td><td>${esc(a.by)}</td><td><b>${esc(a.action)}</b>${a.note ? `<br><span style="color:var(--muted)">“${esc(a.note)}”</span>` : ""}</td>
      <td class="mono">${esc(a.reportIds.join(", "))}<br><span style="color:var(--muted)">${esc(a.questionId)}</span></td><td>${esc(a.repair || a.verdict)}</td></tr>`).join("");
    $("#view-audit").innerHTML = `<div style="display:flex;justify-content:space-between;align-items:end;gap:12px;flex-wrap:wrap"><div><h2>Audit log</h2>
      <p class="lead">Every approve, edit and override, with who and when. Stored in this browser; export to hand over.</p></div>
      <div style="display:flex;gap:8px;margin-bottom:18px"><button class="btn" id="exportBtn">Export JSON</button><button class="btn danger" id="resetBtn">Reset demo</button></div></div>
      ${audit.length ? `<table class="tbl"><thead><tr><th>When</th><th>Who</th><th>Action</th><th>Reports</th><th>Repair</th></tr></thead><tbody>${rows}</tbody></table>` : `<div class="empty card">No actions yet. Approve or override something in the queue.</div>`}`;
    $("#exportBtn").onclick = () => {
      const a = document.createElement("a");
      a.href = URL.createObjectURL(new Blob([JSON.stringify(audit, null, 2)], { type: "application/json" }));
      a.download = `audit-${new Date().toISOString().slice(0, 10)}.json`; a.click();
    };
    $("#resetBtn").onclick = () => { if (confirm("Clear all decisions and the audit log in this browser?")) { decisions = {}; audit = []; store.set("rf.decisions", {}); store.set("rf.audit", []); updateCounts(); renderAudit(); renderQueue(); renderDetail(); } };
  }
  function updateCounts() { $("#auditCount").textContent = audit.length; $("#bonusCount").textContent = D.bonus.length; }

  // ---------- tabs, keys, toast ----------
  let tab = "queue";
  document.querySelectorAll("#tabs button").forEach((b) => (b.onclick = () => {
    tab = b.dataset.tab;
    document.querySelectorAll("#tabs button").forEach((x) => x.classList.toggle("on", x === b));
    $("#view-queue").hidden = tab !== "queue"; $("#view-bonus").hidden = tab !== "bonus"; $("#view-audit").hidden = tab !== "audit";
    if (tab === "bonus") renderBonus(); if (tab === "audit") renderAudit();
  }));
  document.addEventListener("keydown", (e) => {
    if (tab !== "queue" || e.target.matches("input, textarea") || e.metaKey || e.ctrlKey || e.altKey) return;
    const i = cases.findIndex((c) => c.questionId === sel);
    const k = e.key.toLowerCase();
    if (k === "j" || e.key === "ArrowDown") { e.preventDefault(); select(cases[Math.min(i + 1, cases.length - 1)].questionId); }
    else if (k === "k" || e.key === "ArrowUp") { e.preventDefault(); select(cases[Math.max(i - 1, 0)].questionId); }
    else if (k === "a") decide("approved");
    else if (k === "e") $("#editBtn")?.click();
    else if (k === "r") { e.preventDefault(); $("#noBtn").click(); }
    else if (k === "?") $("#keys").hidden = !$("#keys").hidden;
  });
  let tt;
  function toast(msg) { const t = $("#toast"); t.textContent = msg; t.classList.add("on"); clearTimeout(tt); tt = setTimeout(() => t.classList.remove("on"), 1800); }

  updateCounts(); renderQueue(); renderDetail();
  const startTab = new URLSearchParams(location.hash.slice(1)).get("tab");
  if (startTab) document.querySelector(`#tabs button[data-tab="${startTab}"]`)?.click();
})();
