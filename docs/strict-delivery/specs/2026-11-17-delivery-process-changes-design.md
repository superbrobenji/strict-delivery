# Delivery process changes: design

Date: 2026-11-17. Status: draft for owner approval. Changes: the main design spec (`2026-10-31-strict-delivery-framework-design.md`, "MS"), the programs and streams design (`2026-10-31-programs-and-streams-design.md`, "PD"), the session-resume design (`2026-11-02-session-resume-and-questions-design.md`, "SR"), the base playbook, the skill and its prompt blocks, and this repository's plan and breakdown.

## 1. Intent

The framework exists so Claude can deliver large pieces of work autonomously and quickly while keeping code at the quality of a careful pre-AI team. Work runs in two phases:

- **Planning** carries the owner's involvement. Spec, plan and stream breakdown are written and reviewed until they are the source of truth.
- **Implementation** then runs on its own, using:
  - the planned parallelism (streams, sub-controllers, worktrees);
  - gates against drift, hallucination and assumption;
  - a ledger, playbooks, decision logs and findings that keep every decision traceable, so another person and their agents can pick the work up.

Quality comes from standards set in planning and in the ways of working (playbooks, decision logs, findings), not from the number of reviews.

A process review of this repository's own build (2026-10-31 to 2026-11-17) found the opposite of the intent:

| Bucket | Share of 410 wall-clock hours |
|---|---|
| Work | 22% |
| Usage-limit stops | 38% |
| Waiting on owner answers | 39% |

Further evidence from that review:

- About 400-430 owner questions were asked, and most answers were "recommended".
- Many tasks ran 5-17 fix rounds.
- An adversarial verifier ran per block and per round.
- 21 of 32 sampled "caused by a fix" findings were really introduced by the fix. 12 of those came from fixes that added new behaviour imitating another system.
- Mean concurrency was 1-2 agents against a planned 25.

Evidence is in /Users/benji/.superpowers/diagnosing-superpowers/44732c5c-bbb1-43f1-9b61-c829ccc37387/: report.md, design-vs-actual.md and fix-caused-findings.md.

Most of the loss came from the design itself, not from drift:

- The verifier and owner approval run per block of at most 3 tasks.
- The fix loop has no binding stop: the math is advisory, except LOW_PLATEAU.
- Finding-class rulings are owner-only.
- A full suite runs at every commit.
- Document re-reviews run "until a clean pass".
- There is no rule for an absent owner or a usage-limit reset.

## 2. Goals

- An effort of this repository's size reaches its release in about a week of wall-clock once its plan is approved.
- After plan approval, the owner is involved only for the owner-only classes, and their absence blocks only the work that needs the answer.
- Fix loops end by rule, not by owner leave.
- A fix cannot make the code it touches worse.
- Quality stays at the bar the standards set; nothing below is a quality cut.

## 3. Non-goals

- No scope cut of v0.1 (owner, 2026-11-17: "i don't like the options of cutting").
- No change to the profiles' gate list or to what the gates check, except where a section below says so.
- No usage pacing in the framework. Claude Code does not expose the account's usage, so a project that wants pacing writes it as a playbook rule or a repository rule (owner, 2026-11-17).

## 4. Anti-goals

- Faster delivery bought by skipping the standards, the adversarial review or the decision record.
- Agents deciding owner-only matters because the owner is away.
- Opus as the default model for every role (owner, 2026-11-10 and 2026-11-17).

## 5. Decisions (owner, 2026-11-17, unless marked "builder's call")

### 5.1 Tests: touched areas per task, full suites at the edges

- **Each commit's gate** is:
  - the test modules of the changed files, plus every test module that imports a changed module, on every supported runtime;
  - every enabled gate check;
  - a clean tree.
- **The full test suite** runs:
  - on the head of each pull request;
  - at the end of a stream, before the adversarial review;
  - in that review.
- This replaces the per-commit full suite (MS :621 "pre-commit" row for strict, SKILL.md:89, plan :35, :52).
- The strict pre-commit hook still runs `run_all`, then `commands.test`. A project's `commands.test` decides what that covers. Builder's call: a strict project may set `commands.test` to its targeted runner, with the full suite left to the PR and stream-end runs.

### 5.2 One adversarial review per stream

- **The final verifier** (the adversarial reviewer, top tier) runs once per stream, at its end, over everything the stream delivered, including what it already merged.
  - It checks by proof by contradiction that the delivered code is as claimed (plan and spec) and of quality (the standards).
  - It no longer runs per block or per pull request, and it is not re-run after the fixes it causes. Those fixes get a review of their diff (5.4).
- **Merge when someone needs it.** A block whose code another stream consumes, through an edge in the breakdown, opens its pull request as soon as it is ready.
  - Gate: touched-area tests, one full suite on the PR head, and the final branch review against the plan and the standards.
  - The final branch review is the existing `final_reviewer` role at tier3 (MS §10). It is separate from the final verifier and cheaper than it.
  - Blocks no other stream waits on stay on the stream branch and go out with the stream's final pull request.
- **Defects found late.** A defect the stream-end verifier finds in already-merged code is fixed under 5.3 in the stream's final pull request, or in a small follow-up pull request. A consumer stream takes it by its next update from the base branch.
- **The verifier's findings** enter the stream's fix loop (builder's call):
  - The 5.4 math runs over that loop. The verifier's report counts as review 1, and each review of a fix diff counts as the next review.
  - A CRITICAL or HIGH finding is always fixed, and the stream's final pull request does not merge while one is open.
  - If ESCALATE leaves one open, the owner question blocks only that pull request.
  - Consumer streams do not stop. They keep the merged code and take the fix when it lands.
- This resolves the contradiction between PD :141 and PD :142 in favour of :142, with the merge-on-demand exception above.

### 5.3 Fixes may only narrow or correct

- **A fix round's diff may only:**
  - narrow: refuse the bad input and fail closed;
  - correct existing behaviour to what the plan already says.
- **It may not add new modelled behaviour.** No new branch that re-implements another system's rules (a parser, a shell, a library's error text, a file system's semantics).
- **A finding whose resolution needs new behaviour** becomes a planned task with its own input-domain table, through the plan-change path. It is not a fix round.
- **Reviewer duty.** A reviewer checks every fix diff against this rule. A violation is itself a finding.
- **Blame is tested** (builder's call, from the review's 3 misattributed findings out of 32). A finding labelled "caused by the fix" or "caused by round N" counts as such only when its reproducer passes on the fix commit's parent and fails on the fix commit. The reviewer records both runs. Otherwise the finding is pre-existing: it is still handled, but it does not count against the fix.
- **The test for "narrow or correct"** (builder's call). A fix diff passes when every branch it adds or changes does one of two things:
  - refuses input with a named error, failing closed, where the code previously accepted or crashed;
  - makes behaviour match a plan or spec sentence that the fix report quotes.

  It fails when a branch newly accepts input the code used to refuse, or reproduces another system's behaviour that no quoted plan or spec sentence requires.

  The reviewer applies the test. On a disagreement, the controller rules and logs `Decision (controller)`.
- **Where new behaviour goes** (builder's call). A finding that needs new behaviour is first narrowed in the fix round: the input is refused, so the code is safe. A register row then names a proposed new task.
  - Adding that task to the plan is a plan change, so the owner approves it (`scope`).
  - Under 5.6 that approval blocks only the new task, never the stream.
- This narrows implementer.md:9 ("fix the whole dimension"), task_reviewer.md:11 ("no out-of-scope bucket") and review.md's "re-run the whole dimension":
  - the dimension is re-checked;
  - widening the behaviour is out of scope for a fix.

### 5.4 The stopping math is binding, and built first

- **Rules N and T and the verdict ladder of MS §10 ("Rules N and T") become binding.** The text is unchanged: CLEAN, LOW_PLATEAU, k > 5 ESCALATE, STOP_NARROW, CONTINUE.
  - STOP_NARROW: the loop stops. Open findings are handled by 5.3: narrowed in one last round, or registered for a planned task.
  - ESCALATE: the loop stops. Open LOW and MEDIUM findings are registered against a named follow-up task. An open CRITICAL or HIGH finding becomes an owner question that blocks only that task (5.6).
  - A change-caused CRITICAL or HIGH finding is fixed whatever the verdict (unchanged).
- **Reviews of fix rounds** are scoped to the fix diff plus the finding's dimension, and run at the small re-review tier when MS §10's conditions hold (unchanged).
- **`loopstats` (plan Task 6E.3) is built first.** It starts now, in its own worktree.
  - Its only tie to config/2, the optional `escape_cost`, is read once config/2 lands (builder's call).
  - Until `loopstats` merges, controllers compute Rules N and T by hand, as MS §10 already says, and ledger the verdict.
- This changes MS :577 and :579 ("advisory, except LOW_PLATEAU"), review.md:21 (owner question after round 5), the controller and reviewer prompt blocks, and SKILL.md:87 ("until a clean pass").

### 5.5 Finding-class rulings leave the owner-only list

- **`finding-class` is removed from the default owner-only classes** (MS :329, controller.md:15 and :19, review.md:32).
  - The controller applies 5.3 and the 5.4 verdicts.
  - It logs `Decision (controller): class -- action -- cost if wrong`.
- **What still reaches the owner, under classes that already exist:**
  - a class whose resolution would change shipped user-facing behaviour, the spec, or scope (`spec-direction`, `scope`);
  - an ESCALATE verdict with an open CRITICAL or HIGH finding.

### 5.6 The owner's absence blocks only what depends on the answer

- **Unchanged and now enforced:** "Only the asking branch of the tree waits; its siblings continue" (PD :98-99).
  - A stream keeps running every sub-controller and task that does not depend on an open owner question.
  - A controller never pauses a whole stream on a question.
  - When nothing independent is left, the stream checkpoints and waits.
- **No agent decides an owner-only question** because the owner is away.
- **Owner-only classes stay as listed**, minus `finding-class` (5.5): architecture (`spec-direction`), model and cost (`model-policy`), scope, merge grants, rule and profile overrides, and the program classes.

### 5.7 Usage-limit stops: checkpoint, then resume on reset

- **Before a usage-limit stop** (a 429, or a limit message), every controller checkpoints: clean tree, branch pushed, handoff written.
- **On reset, work resumes without waiting for the owner.** The session that owns the program schedules a wake-up at the reset time the limit message names, and re-dispatches from the handoffs.
  - This needs the session left open (builder's call: Claude Code's scheduled wake-up or cron tool; if neither is available, the handoff names the resume command and the owner runs it).
- No usage pacing (section 3).

### 5.8 Models follow the spec tiers

- **Every dispatch names its model explicitly**, at the role's minimum tier from MS §10 (already the rule).
  - Implementers and drafters run at tier2.
  - Controllers, reviewers and investigators run at tier3.
  - The final verifier runs at the top tier or its fallback.
  - Small re-reviews run at `reviews.small.tier`.
  - Opus is never the default for every role.
- Unchanged in the spec; recorded here because execution drifted from it until 2026-11-10.

### 5.9 Planning reviews: stricter than code, bounded by the same math

Plan, spec and breakdown reviews (plan_reviewer):

- Re-reviews read the whole document, because it is the source of truth (stricter than code).
- An edit corrects only what was flagged, and adds no new design (the 5.3 rule for documents).
- The 5.4 math stops the loop, replacing "a document re-review runs in full until a clean pass" (review.md:19, SR :89).
- When the loop stops, open LOW and MEDIUM findings are fixed in one final edit pass, not registered (builder's call for MEDIUM).
  - An open HIGH or CRITICAL finding is always fixed.
  - If ESCALATE leaves one open, it goes to the owner, who is involved in planning anyway.
- One adversarial review runs at the end of planning, over the spec, plan and breakdown together, before the owner approves the plan.
- After approval, plan text changes only through the plan-change path. A finding in implementation never reopens the planning loop.

## 6. Constraints

- **Code merges.** Every change still lands by pull request. The merge grant, the ledger, the decision log, the register and the gates stay as they are.
- **Bounded loops.** A loop the 5.4 math stops never ends with a known CRITICAL or HIGH change-caused defect merged.
- **Spec traceability.** The spec edits cite this design and the owner answers of 2026-11-17.

## 7. Applying it to this repository's v0.1 build

- **On the owner's approval of this design**, the program controller first rewrites the common rules for stream controllers (`strict-delivery-worktrees/_program/stream-common.md`).
  - They carry the full text of 5.1-5.9, adapted to this repository, and cite this design.
  - Every running controller re-reads them.
  - Until the spec edits merge, the common rules govern this build, and they win where they differ from the current spec.
- **The docs pull request** in the next bullets is itself reviewed under the new rules (5.9).
- **Plan and breakdown edits:**
  - Task 6E.3 moves to "start now";
  - per-block verifiers are dropped in favour of stream-end verifiers;
  - stream PRs follow the merge-on-demand rule;
  - the process section cites this design.
- **Spec, skill, playbook and prompt-block edits** land as one docs pull request, built by stream b with a plan review under 5.9.
- **Work in flight continues.** PR-unicode, PR-2b1, PR-2b-rest and PR-2c3 finish under the new rules. Their pending verifiers become one verifier at stream a's end, unless another stream needs their code first (5.2).

## 8. Left to the builder

- The exact wording of each spec, playbook, skill and prompt-block edit, within the decisions above.
- How a controller finds "test modules that import a changed module" (for example `git grep -l`, or an import scan).
- The wake-up mechanism for 5.7, and its fallback.
- Which breakdown edges count as "another stream consumes this block" for 5.2.
