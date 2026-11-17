# Process v2 roll-in Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Carry the owner-approved delivery-process design (process v2) into every document that states the old rules: the three specs, the base playbook, the skill and its prompt blocks, the framework plan, the stream breakdown, README.md, and the tests that pin their text.

**Architecture:** Five edit groups with disjoint file sets, each on its own group branch and worktree cut from `docs/process-v2`, merged one at a time by the controller. Each doc change lands with the test change that pins it in one commit (spec §8a, "Commits"). The `finding-class` removal is a sixth group that waits only for the program controller's answer on the one gates/ code line it needs.

**Tech Stack:** Markdown; Python 3.9 / 3.13 `unittest` (tests/test_playbook.py, tests/test_prompt_blocks.py, tests/test_skill.py, tests/prose_check.py, tests/test_playbook_drift.py, tests/test_config.py).

**Spec:** `docs/strict-delivery/specs/2026-11-17-delivery-process-changes-design.md` ("the design", sections 5.1-5.9; owner 2026-11-17, "approved, roll it in"). Evidence: /Users/benji/.superpowers/diagnosing-superpowers/44732c5c-bbb1-43f1-9b61-c829ccc37387/design-vs-actual.md (every line to change, with file:line), report.md, fix-caused-findings.md.

## Global Constraints

- The design's decisions are binding; the wording is the builder's (design §8). An edit states the design's rule; it adds no new design (design 5.9, "An edit corrects only what was flagged, and adds no new design").
- No change to the profiles' gate list or to what the gates check (design §3), so no `gates/` edit except the one Group F may get leave for.
- Spec traceability (design §6): each spec edit cites the design section and "owner 2026-11-17".
- Tests that pin text are updated to the new text and stay as strict as before: a check is re-pointed, never deleted or loosened. A mutation-style negative case (`assertNotEqual`, a broken variant list) keeps its count and gets a variant of the new text.
- Prompt-block format (spec §10): printable ASCII, `\n` only, no trailing whitespace, labelled paragraphs, fixed label lists. A label is not added or renamed unless the label list test changes with it; prefer changing a paragraph's sentences over adding labels.
- Unchanged by the design and kept: the merge grant, the ledger, the decision log, the register, the gates (design §6); small re-review conditions (design 5.4); model tiers (design 5.8); fix rounds 1-3 resume the implementer and rounds 4-5 go one tier up (the design changes only what follows round 5).
- Commit gate (design 5.1; stream-common.md): the targeted test modules on `/usr/bin/python3` and `/opt/homebrew/bin/python3.13` (each changed file's test modules plus every test module that reads or imports it, found with `git grep -l`), `python3 -m gates check` schema, decisions, register, cites, claims exit 0, a clean tree. Full suite only on the PR head.
- Commit messages cite the design section (for example `docs(spec): MS §10 binding Rules N and T (design 5.4)`).

## Decisions taken here (owner delegation 2026-11-09 / builder's call, design §8)

- D1. Rounds after 5: "then an owner question" becomes "then the Rules N and T verdict": the re-review of fix round 5 is review 6, so `k > 5` ESCALATE stops the loop; ESCALATE registers open LOW/MEDIUM against a named follow-up task and turns an open CRITICAL/HIGH into an owner question that blocks only that task (design 5.4). -- why: the design keeps the verdict ladder text and makes it binding. -- cost if wrong: one sentence per file.
- D2. A plain plan (no program) counts as one stream: its final verifier runs once, before its last pull request, over everything the plan delivered (design 5.2 applied to the plain-plan case). -- cost if wrong: a sentence in MS §10 and review.md.
- D3. Class narrowing or widening becomes a controller decision under the fix rule (design 5.5): "a class-narrowing question for the owner" becomes "a class-narrowing question for the controller, which rules under the fix rule and logs `Decision (controller): class -- action -- cost if wrong`"; the owner is asked only when the resolution changes shipped user-facing behaviour, the spec or scope (`spec-direction`, `scope`), or on ESCALATE with an open CRITICAL/HIGH. -- cost if wrong: the pinned phrase in prose_check and test_prompt_blocks.
- D4. "Registered as a LOW under LOW_PLATEAU, and otherwise never deferred" becomes "registered as a LOW under LOW_PLATEAU, or registered against a named task when the binding verdict (STOP_NARROW, ESCALATE) stops the loop, and otherwise never deferred"; "LOW_PLATEAU" stays in the sentence so the deferral checker's rule (a deferral names its verdict) keeps holding, widened to the two other verdicts. -- cost if wrong: SD_R5 constants.
- D5. The `drafter` role's strict block is `investigator` (read-only, stream-common.md), so text edits that change tracked files run as `implementer` (tier2, sonnet, the same tier as drafter). -- cost if wrong: none in tier or cost.
- D6. Usage-limit resume (design 5.7): the wake-up is Claude Code's scheduled wake-up or cron tool in the session that owns the program; fallback: the handoff names the resume command and the owner runs it. A usage-limit stop is not a budget checkpoint: the dispatcher does not re-dispatch at once (the limit is account-wide); it re-dispatches at the reset.
- D7. Which breakdown edges count as "another stream consumes this block" (design 5.2, §8): a block is consumed when an edge in the breakdown's section 3.2 or 6 goes from one of its tasks to a task of another stream, or a `Consumes:` line of another stream's task names its module.

## Review Focus

1. A rule changed in one file and left old in another (for example "owner question after round 5" fixed in review.md but not in controller.md, MS §10 or the plan's Roles line). Check: `git grep -n -e "then an owner question" -e "until a clean pass" -e "advisory, except" -e "per block" -e "top-tier verifier" -e "path halts" -e "halt that path" -e "class-narrowing question for the owner"` over specs, playbook, skills, plan and README returns only historical text (quoted history, revision tables, the design itself).
2. A pinned test weakened while being re-pointed (a deleted assertion, a shortened phrase list, a removed negative variant). Check: for each changed test file, `git diff --stat` and a count of `assert` calls before and after; equal or higher.
3. A verifier sentence that still runs per block or per PR, or re-runs after its own fixes.
4. The strict pre-commit row changed by mistake: design 5.1 keeps `run_all`, then `commands.test` in the strict pre-commit hook; only the agents' commit gate and the full-suite points change.
5. Breakdown arithmetic: every figure of the revision 7 schedule re-adds from its stated unit costs and start times.

---

## Group A: the three specs (implementer, sonnet; worktree `.../docs/process-v2-a`, branch `docs/process-v2-a`)

**Files:** Modify `docs/strict-delivery/specs/2026-10-31-strict-delivery-framework-design.md` (MS), `docs/strict-delivery/specs/2026-10-31-programs-and-streams-design.md` (PD), `docs/strict-delivery/specs/2026-11-02-session-resume-and-questions-design.md` (SR). No test pins spec text; the gates `cites` and `claims` run on them.

### Task A1: MS edits

- [ ] MS §7.1 (:328-331 "Default owner-only classes" and the controller-rulings sentence that follows): add after the class list the 5.5 rule: finding-class rulings are the controller's (D3), what still reaches the owner, and "an open owner question blocks only the work that depends on its answer (design 5.6)". Do NOT remove `finding-class` from the list yet (Group F).
- [ ] MS §7.1 batch sentence ("A batch is kept small ..."): add that only the asking branch waits and no agent decides an owner-only question because the owner is away (5.6).
- [ ] MS §8 bullet 3 (:479 "Owner-only classes are questions in the log; the path halts until answered."): "...; only the work that depends on the answer halts, every independent task continues (design 5.6)".
- [ ] MS §8 Zero-bugs bullet (:482-483): D4 wording; "a document re-review runs in full until a clean pass" becomes the 5.9 rule: "a document re-review reads the whole document, an edit corrects only what was flagged, the Rules N and T verdict stops the loop, and open LOW and MEDIUM findings then get one final edit pass".
- [ ] MS §8: add a bullet-free sentence after the Zero-bugs bullet? No: keep the bullet count (SD-R1..SD-R17 map to the bullets in order). Put the fix rule (5.3) into the "Findings that keep arriving" bullet's neighbour text as a new paragraph after the bullet list, beside "Input-domain method": "Fix rule (design 5.3): ..." covering narrow-or-correct, the pass/fail test, new behaviour becomes a planned task (scope approval blocks only that task), reviewer duty, tested blame.
- [ ] MS §8 reviewers bullet (:487 "Before a review the controller trial-merges ... and runs the full suite on the merged tree"): the full suite runs on the PR head, at stream end before the verifier, and in the verifier; a task review runs the touched-area modules (5.1).
- [ ] MS §8 continuation bullet (:490-494): a usage-limit stop checkpoints and the dispatcher re-dispatches at the reset, not at once (5.7, D6).
- [ ] MS §8a "Commits": the commit gate is the touched-area modules plus the enabled gates and a clean tree (5.1).
- [ ] MS §10 Lifecycle (:571-572 "then an owner question"): D1. Same paragraph (:575) "may run ... advisory": binding.
- [ ] MS §10 "Rules N and T" header "(...; advisory, except LOW_PLATEAU ...)": binding (design 5.4, owner 2026-11-17); add STOP_NARROW and ESCALATE actions (5.4 bullets), the fix-round re-review scope (fix diff plus the finding's dimension), and that the controller computes by hand and ledgers until `loopstats` merges.
- [ ] MS §10 new paragraph "Verifier and merges" (5.2, D2): verifier once per stream at its end; not re-run after its own fixes, whose diffs get a task review; its findings enter the stream's loop as review 1; open CRITICAL/HIGH blocks only the stream's final PR; merge on demand (D7) gated by touched-area tests, one full suite on the PR head and a fresh `final_reviewer`; defects found late fixed in the final PR or a small follow-up PR.
- [ ] MS §10 new paragraph "Owner absence and usage limits" (5.6, 5.7, D6).
- [ ] MS §10 "Planning reviews" sentence (5.9), or place it in §8a's "Plan and spec-edit review" item: re-reviews read the whole document; edits correct only what was flagged; the math stops the loop; open LOW/MEDIUM fixed in one final edit pass; HIGH/CRITICAL always fixed; ESCALATE with one open goes to the owner; one adversarial review over spec, plan and breakdown at the end of planning; after approval plan text changes only by the plan-change path.
- [ ] MS §11 bullet "a finished stream opens its own pull request" (:602): add merge on demand and the stream-end verifier.
- [ ] MS §12 table row "top-tier final verifier": `no | no | once per stream, at its end`; keep "pre-commit" row values; add under the table: "Agents' commit gate under every profile: the touched-area test modules, the enabled gates, a clean tree; the full suite runs on each pull request's head, at a stream's end before the verifier, and in the verifier (design 5.1). The strict pre-commit hook still runs `run_all`, then `commands.test`; a project's `commands.test` decides what that covers."
- [ ] MS §18 (owner choices): one bullet "Owner 2026-11-17: process v2, the design `2026-11-17-delivery-process-changes-design.md` 5.1-5.9".
- [ ] Commit `docs(spec): MS process v2 (design 5.1-5.7, 5.9)`.

### Task A2: PD edits

- [ ] PD §4.1 (:98-99): after "Only the asking branch of the tree waits; its siblings continue." add 5.6: a stream keeps every independent sub-controller and task running, never pauses a stream on a question, checkpoints and waits when nothing independent is left; no agent decides an owner-only question because the owner is away.
- [ ] PD §4.2 / §4.4 (:120-124): usage-limit stop: checkpoint, then the session that owns the program schedules a wake-up at the reset time and re-dispatches from the handoffs (5.7, D6); a budget checkpoint still re-dispatches at once.
- [ ] PD §5 step 3 (:141 "A block ends in this order: final review, the top-tier final verifier ..., the owner's approval, merge, ..."): resolved per 5.2 for :142: a block ends with its final review on the stream branch; a block another stream consumes opens its PR when ready (touched-area tests, one full suite on the PR head, the final branch review, the owner's approval, merge); the final verifier runs once at the stream's end, before the stream's final PR.
- [ ] PD §5 step 4 (:142): keep "Blocks accumulate on the stream branch"; add the merge-on-demand exception and the late-defect rule.
- [ ] Commit `docs(spec): PD merge on demand, owner absence, usage-limit resume (design 5.2, 5.6, 5.7)`.

### Task A3: SR edit

- [ ] SR §3.8 (:89 "Fix and re-review rounds run until a clean pass (L:98, X-43)."): "Fix and re-review rounds run until the binding Rules N and T verdict of MS §10 stops the loop; document re-reviews follow the planning-review rule of MS §10 (design 5.4, 5.9; owner 2026-11-17)."
- [ ] SR "The batch" line (:73 area, "Questions are batched at the next stop"): keep; add "only the asking branch waits (design 5.6)" if the line states a halt.
- [ ] Commit `docs(spec): SR fix loop stops by the binding verdict (design 5.4, 5.9)`.

## Group B: base playbook (implementer, sonnet; branch `docs/process-v2-b`)

**Files:** Modify `playbook/review.md`, `playbook/rules.md`, `playbook/decisions.md`, `playbook/sessions.md`, `playbook/streams.md`, `playbook/roles.md` (only where they state an old rule). Test: `tests/test_playbook.py`, `tests/test_playbook_drift.py`, and the readers `tests/test_skill.py` (playbook table at :379) run as targeted modules.

### Task B1: review.md

- [ ] "Task review" (:7): the controller trial-merges and runs the touched-area modules before a task review; the full suite runs on the PR head, at stream end before the verifier, and in the verifier (5.1). Reviewer: a fix diff is checked against the fix rule (5.3); blame is tested on the fix commit's parent and the fix commit (5.3).
- [ ] "Final review" (:11): a `final_reviewer` reviews a branch before its pull request (merge on demand, or the stream's final PR); the end order becomes: final review, (at the stream's end only) the full suite and the top-tier verifier and the review of its fix diffs, the owner's approval, merge, post-merge gates, checkpoint. Re-point `BLOCK_END_ORDER` and `VERIFIER_PROFILE` in tests/test_playbook.py (:1602-1606) to the new sentences; keep the verifier-term checker (:1609 on) and its negative list (:1786-1788) with the new wording's negatives.
- [ ] "Verifier" (:15): once per stream at its end, over everything the stream delivered, merged parts included; not re-run after its own fixes (5.2, D2).
- [ ] "Fix loop" (:19-23): D4; the document re-review sentence (5.9); D1 for "after round 5"; a new paragraph "Fix rule" (5.3: narrow or correct, the pass/fail test, new behaviour becomes a planned task, reviewer duty, tested blame, re-review scoped to the fix diff plus the finding's dimension); STOP_NARROW and ESCALATE actions. Re-point the Fix loop phrase list (test_playbook.py:1354-1355: keep "rounds 1-3", "rounds 4-5", "cosmetic", "never deferred", "LOW_PLATEAU"; "owner question" stays only if the new text still names the ESCALATE owner question, which it does) and add phrases "narrow", "fails closed", "parent".
- [ ] "Input domains" item 4 (:32): D3.
- [ ] "Rules N and T" (:58): binding, not advisory; keep "never blocks a fix" (a change-caused CRITICAL/HIGH is fixed whatever the verdict) only if still true: rewrite to "The verdict is binding (design 5.4): it decides when the fix loop stops; it never stops a change-caused CRITICAL or HIGH from being fixed". Re-point test_playbook.py:1583-1586 ("apart from the LOW_PLATEAU verdict") to the new invariant phrase, in every stem it checks. Keep LOW_PLATEAU_BY_HAND (:1649) or re-point it to "the controller applies the verdict and the weighted tally by hand" with the same negative (:1740).
- [ ] "Plan review" (:76-84): add the 5.9 bullets.
- [ ] Commit (doc and test together) `docs(playbook): review.md process v2 (design 5.1-5.4, 5.9)`.

### Task B2: rules.md, decisions.md, sessions.md, streams.md, roles.md

- [ ] rules.md SD-R3: "the path halts until the owner answers" becomes "only the work that depends on the answer halts until the owner answers (design 5.6)". `fixed: yes` stays.
- [ ] rules.md SD-R5: D4 and the 5.9 document sentence; the `why` cell keeps its meaning. Re-point SD_R5_LOW_PLATEAU (test_playbook.py:34, :1693) and the why pin (:77, :1817).
- [ ] rules.md SD-R9: full suite points per 5.1.
- [ ] rules.md SD-R11: usage-limit stop per 5.7 / D6.
- [ ] decisions.md "Asking" (:7) "the path that needs it halts": 5.6 wording. "The batch" (:13): questions still go as one batch; add that nothing independent waits on it. "Restarts" (:15) "Fix and re-review rounds run until a clean pass." becomes "Fix and re-review rounds run until the binding Rules N and T verdict stops the loop." Re-point test_playbook.py:1365 (row D9) to that sentence.
- [ ] decisions.md "Owner-only classes" intro: add 5.5's controller rule (D3). The `finding-class` row stays until Group F.
- [ ] sessions.md "Handoffs and continuation" and "Start order" step 6 ("with any difference, stop and wait for the owner"): usage-limit resume (D6); a difference stops only the work it affects (5.6) -- only if the sentence states a whole-session halt; the resume-check difference that needs an owner answer still waits for it.
- [ ] streams.md: merge on demand and the stream-end verifier (5.2) where it states per-block PRs; owner absence (5.6).
- [ ] roles.md: only if it states fix-round or verifier cadence; tiers unchanged.
- [ ] Run test_playbook, test_playbook_drift, test_skill on both interpreters; commit `docs(playbook): rules, decisions, sessions, streams process v2 (design 5.1-5.7)`.

## Group C: skill and prompt blocks (implementer, sonnet; branch `docs/process-v2-c`)

**Files:** Modify `skills/strict-delivery/SKILL.md`, `skills/strict-delivery/prompts/{controller,implementer,task_reviewer,final_reviewer,final_verifier}.md` (others only if they state a changed rule; no `plan_reviewer.md` exists on this branch). Test: `tests/test_prompt_blocks.py`, `tests/test_skill.py`, `tests/prose_check.py` (and `tests/test_playbook.py` as a reader).

### Task C1: prompt blocks

- [ ] controller.md "Finding class." (:15): D3 replaces "Narrowing or widening a class is an owner question."; keep the process-defect sentence.
- [ ] controller.md "Owner-only decisions." (:19): "halt that path, and report status NEEDS_DECISION when nothing else can proceed" becomes "only the work that depends on it waits; keep every independent task running; report NEEDS_DECISION only when nothing independent is left; never decide it because the owner is away" (5.6). Class list unchanged until Group F.
- [ ] controller.md "Continuation." (:21): D1 ("then the Rules N and T verdict, binding: compute it after each review and ledger the `Loopstats:` line; STOP_NARROW ...; ESCALATE ..."); usage-limit stop per D6. Re-point CTRL_FIX_LOOP (test_prompt_blocks.py:1162) from "owner question" to the new phrase (for example "binding"), with the negative variants at :1337-1339 re-pointed one for one; :1734 and :2037 exact paragraph pins re-pointed.
- [ ] controller.md "Merge and checkpoint." (:23): merge on demand and the once-per-stream verifier (5.2).
- [ ] controller.md "Zero bugs." (:17): D4. Re-point :1547.
- [ ] implementer.md "Input domain." (:9) "Fix the whole dimension a finding names, not only the reproduced value." becomes "Cover the whole dimension a finding names, not only the reproduced value, by narrowing: refuse what the plan does not state, failing closed." and "Unstated behaviour." (:11) gains the fix rule: a fix round may only narrow or correct (5.3), every added branch refuses input with a named error or matches a quoted plan/spec sentence, and a needed new behaviour is reported under Decision needed as a proposed task after the input is refused. Re-point :2205 ("Fix the whole dimension") with its negative.
- [ ] implementer.md "Commit gate." (:13): the touched-area modules (each changed file's test modules plus every test module that imports a changed module) on every interpreter the brief names, plus `python3 -m gates run_all`; the full suite runs at the points the brief names (5.1). Re-point :226 if it pins `commands.test` in this block only; keep `commands.test` where the block still names it.
- [ ] task_reviewer.md "Method." (:7): re-run the touched-area modules and `run_all`; check every fix diff against the fix rule (a violation is a finding) and test blame on parent vs fix commit, recording both runs (5.3). "No out-of-scope bucket." (:11): D3 ("class-narrowing question for the controller"), and "widening a fix's behaviour is out of scope for a fix round; the dimension is re-checked" (5.3). Re-point prose_check.py:70, test_prompt_blocks.py:48, :75, :1604, :1630, the R-OOS mutation row (:1834) to the new phrase.
- [ ] final_reviewer.md: "Verdict." "whether the branch may go to the final verifier" becomes "whether the branch may open its pull request (and, at a stream's end, go to the final verifier)"; D3 in "No out-of-scope bucket.".
- [ ] final_verifier.md: intro "once" stays; "Adversarial scope." adds: once per stream, over everything the stream delivered, merged parts included; it is not re-run after its own fixes (5.2).
- [ ] Commit (blocks and tests together) `docs(skill): prompt blocks process v2 (design 5.2-5.7)`.

### Task C2: SKILL.md

- [ ] "Decision classes" (:37): "that path halts until the owner answers" becomes 5.6 wording. Add 5.5's controller rule sentence.
- [ ] "Owner questions" (:59, :61): batch stays; nothing independent waits.
- [ ] "Pipeline and gates" (:87): "the fix loop until a clean pass" becomes "the fix loop until the binding Rules N and T verdict stops it; a fix only narrows or corrects (design 5.3)"; "each block ends with a final review and ... a top-tier final verifier" becomes merge on demand plus one verifier per stream (5.2). (:89) the commit gate per 5.1; the full suite on each PR head, at stream end and in the verifier. Re-point SKILL_PHRASES["Pipeline and gates"] (test_skill.py) to keep four phrases that the new text holds ("`python3 -m gates run_all`", "all-green", "pull request", "owner's approval").
- [ ] "Continuation" (:110): usage-limit per D6. Keep the pinned phrases.
- [ ] Commit `docs(skill): SKILL.md process v2 (design 5.1-5.7)`.

## Group D: the framework plan (implementer, sonnet; branch `docs/process-v2-d`)

**Files:** Modify `docs/strict-delivery/plans/2026-10-31-strict-delivery-framework.md`. No test pins it.

- [ ] "Process for this plan": a first bullet "Process v2 (owner 2026-11-17)" citing the design and stating that it supersedes, for the rest of v0.1: the per-block verifier (now one per stream, 5.2), per-PR blocks (merge on demand, D7), the per-commit full suite in Global Constraints "Test command" and PC3's "The full suites run once per commit" (5.1), the owner question after round 5 (D1), "dispatch waits for the answers" in "Owner questions are batched" (5.6), PC4's class-narrowing owner question (D3, 5.5); and adds the fix rule (5.3). Edit each of those sentences in place to the new rule (the history stays in the ledger).
- [ ] "Blocks" bullet: "Under the strict profile each block ends with a final review (opus) and a top-tier final verifier" becomes the 5.2 rule.
- [ ] "Roles" bullet: "fix rounds 4-5 one tier up" stays; add the D1 sentence.
- [ ] "Small re-review" bullet: unchanged except "until `loopstats` exists" stays.
- [ ] Task 6E.3 heading and Block 6 intro (:5513-5530, :5802): Task 6E.3 starts now (design 5.4), on group branch `20261110-v01/evidence/loopstats`, dispatched by the program controller; it reads `escape_cost` once config/2 lands (the `escape_cost` part deferred to after config/2). Its Interfaces and tests are not changed. Its "advisory" sentences (plan :5874-5884, and every other plan sentence calling the loopstats verdict advisory) say instead that the verdict binds the controller (design 5.4, process rule); loopstats' exit-code contract (exit 0 whatever the verdict, refusals exit 1) and its printed wording stay exactly as the plan has them (stream evidence input, relayed by the program controller 2026-11-17). The same applies to MS :577 and :579 in Task A1.
- [ ] Every "per block" or "per sub-block" verifier sentence in Program grouping for v0.1, How block 3 runs, Block 4/5/6 intros and Block 3 end: becomes the stream-end verifier; PR order follows merge on demand (D7). Find them with `git grep -n -i -e "verifier" -e "block end" -e "sub-block end"` on the plan; edit only sentences that state the cadence, not task content.
- [ ] Commit `docs(plan): process v2 in the process section, 6E.3 starts now, stream-end verifiers (design 5.1-5.6, §7)`.

## Group E: breakdown revision 7 and README (implementer, sonnet; branch `docs/process-v2-e`)

**Files:** Modify `.strict-delivery/state/plans/2026-10-31-strict-delivery-framework/breakdown.md`, `README.md`.

- [ ] Breakdown: add "Revision 7 (2026-11-17, process v2)" at the top of sections 1, 4, 5, 6.1, 6.2 and 7, keeping revision 6 as history. Units: E splits into R (final review, per PR) and T (approval, merge, read-back, post-merge gates, MERGED line, 0.5 h); the verifier V (1.0 h, plus its fix-diff reviews 0.5 h) once per stream at the stream's end; a PR's full suite on its head is in R. t = 0 is 2026-11-17 (the design's approval). State at t = 0 from the program ledger tail (`git show origin/block/docs-resume:.strict-delivery/state/plans/2026-10-31-strict-delivery-framework/ledger.md`) and the stream reports under `/Users/benji/projects/personal/strict-delivery/.superpowers/sdd/2026-10-31-strict-delivery-framework/`: PR-unicode, #17 (PR-2b1), PR-2b-rest, PR-2c3 in flight; hooks 3b.1 merged into hooks/main; runtime 3a.1 done; 6E.3 dispatched. No owner leave rounds (the binding verdict ends each loop). Mark which PRs open on demand (D7) and which ride their stream's final PR. Write the new critical path, a per-PR timeline table and a roadmap to v0.1.0 with the arithmetic in each cell.
- [ ] README: profile row "adversarial top-tier verifier per block" becomes "... per stream"; "Done so far" and "Merged pull requests" to the current main (#1-#20, git log); "Roadmap to v0.1" and "Target" to the revision 7 figures, in plain words.
- [ ] Commit `docs(breakdown): revision 7 under process v2 (design 5.1, 5.2, §7)`.

## Group F: `finding-class` leaves the default owner-only list (owner answer (a), 2026-11-17, relayed by the program controller: this PR edits exactly gates/lib/config.py:39 and tests/test_config.py:18-19, its only gates/ change; runs after Groups B and C merge, since it touches their files)

**Files:** `docs/strict-delivery/specs/2026-10-31-strict-delivery-framework-design.md:330`, SR :211 (C-15), `playbook/decisions.md:37`, `skills/strict-delivery/SKILL.md:41`, the ten prompt blocks' owner-only lists, `tests/test_playbook.py:1318`, `tests/test_skill.py:24`, :431, `tests/test_prompt_blocks.py:1728-1815`; and, only with leave, `gates/lib/config.py:39`, `tests/test_config.py:18-19`.

- [ ] Drop the token everywhere in one commit; the cross-checks (test_skill.py:377-379, test_config.py:132) stay and pass; run tests.test_config, tests.test_skill, tests.test_playbook, tests.test_prompt_blocks on both interpreters.

## Execution and review

- Groups A-E run in parallel (child worktrees beside the group worktree, disjoint files; at most 4 children at once), then the controller merges each group branch into `docs/process-v2`, re-running the targeted modules at the merged head.
- Review (design 5.9): a `plan_reviewer` (opus) reads the whole changed set against the design; edits correct only what was flagged; the Rules N and T math stops the loop; open LOW and MEDIUM findings get one final edit pass; then one `final_verifier` (opus) over spec, plan and breakdown together.
- Then the full suite on the PR head and `gh pr create --base main`.
