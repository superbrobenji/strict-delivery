# v0.2 design notes (working record of the owner conversation)

Status: working notes, not the spec. Each decision is quoted or paraphrased from the owner, dated, and carried into the v0.2 design spec. Inventory: `.superpowers/sdd/2026-10-31-strict-delivery-framework/v02-inventory.md`.

## Scope and order (2026-11-26)

- In v0.2: inventory groups A (V2-01..05), B (V2-06..09, V2-24), C (V2-10..23, V2-36, V2-39..42), D (V2-26..29, V2-34, V2-35, V2-37, V2-38, V2-43..49), F (V2-50, V2-51), plus B1 (mutants on changed lines, targeted fix-round re-runs, at most 10 final-review mutants) and B2 (the merge check takes the stream suite plus CI, no third suite run).
- v0.3: group E (V2-30..33), tracked in `2026-11-26-v03-candidates.md`. Out of every release: hardware tuning (V2-53), the dropped build-state items (V2-54), the lap-timer migration (V2-55).
- V2-25 (stale open findings on main) is v0.1 work.
- Stage order: B (the tool gaps "slow everything down"), then A, C, F, D. Each stage merges before the next starts.

## Success and failure (2026-11-26)

- Failure, owner's words: "if it takes as long as v0.1 did, if it made no improvements to delivery time while maintaining quality standards, if i have to change the spec halfway through due to improper planning that wasn't thorough enough."
- Target: under one week from the approved plan and breakdown (step 6) to the v0.2 tag, excluding usage-limit stops, with an extra week of leeway. Steps 1-6 (conversation, design spec, reviewer check, owner approval, plan with every coverage table, breakdown, owner approval) are planning.
- Quality bar unchanged: the same gates, zero-bug rule, task and final reviews, mutation evidence, verifier pass. Speed comes from B, F and better planning only.
- Time-use targets (this build's `time-targets.md`) also apply to v0.2 and are reported daily; planned-versus-actual is tracked from day one; a spec change after approval is an owner question with its cause recorded.
- Every new feature is discussed and planned properly with the owner before it enters the spec.

## Feature decisions

### V2-08 Closing findings (2026-11-26)

- Owner: "close it automatically once the fix merges and its test is pinned"; option (a) "computed, not written", "including the squash fallback and other 2 edge cases".
- `findings.effective_status(record)` is the one function every reader uses (register gate, `findings list`, INDEX open findings, loopstats, doctor). It returns closed when (1) the record's fix commit is reachable from the base branch (one `git rev-list` over the base per run), (2) the pinned test exists on the base, and (3) the pinned mutation transcript exists and shows that test failing with the fix reverted. Otherwise: "fixed, waiting to merge" (fix not on the base) or "fixed, owes a test" (merged, no pin). The record file is not rewritten.
- Squash or rebase merges: when the fix commit is not on the base, the fix is accepted when a base commit carries the same patch (patch-id match) and the pinned test is on the base; otherwise the record stays "waiting to merge" and doctor flags it.
- A fix reverted later: the record still reads closed; the pinned test fails in CI, which catches the regression as a new finding.
- Records with no pin (most of today's open ones) show "fixed, owes a test" until pinned; nothing is closed silently.

### V2-06 and V2-07 Who found a finding; loop statistics for inherited and pre-review findings (2026-11-26)

- Owner: "yes go with that" (on the recommendation below).
- Every finding record carries two fixed facts: `found_by` (implementer, task_review, final_review, verifier, other) and `found_in` (task id and round where it was first raised). The owner (`owner.task`) may move; these two never change. This is also V2-06 (review kind).
- `loopstats` counts only findings with `found_in.task` equal to the task and `found_by` a review of that task; every other finding of the task is printed on a separate line, for example `carried in: 3 (4d.1 r5: LOW x3), pre-review: 1 (MEDIUM)`, and never enters X, W or the verdict.
- A task reaches CLEAN only when every carried-in and pre-review finding is fixed or registered against a named task (zero-bug rule): they cannot stop or prolong the loop, but they block the sign-off.
- The rework share and the late-findings measure come from the same facts: a finding first raised by a final review or verifier in code a task review already passed counts as late (target under 20 %).
- Rejected: counting carried-in findings at a lower weight (mixes two questions; arbitrary weights).

### V2-09 Empty brief sections (2026-11-26)

- Owner: "yes both match, go ahead".
- `check dispatch` fails every required section (Role, Brief, Findings, Claims, Budget, Model, Report, Task) whose body is empty or whitespace only, one line each: `FAIL dispatch.section.<name>: empty`. A section saying "None." has content and passes. The strict block keeps its byte-for-byte check.

### V2-24 This repository's nonconforming handoffs (2026-11-26)

- Owner: "yes both match". Treated as v0.1 data clean-up (the program controller's owed handoff/1 rewrites, docs PR); V2-04 (handoffs written only by the checkpoint tool) prevents a recurrence in v0.2.

### V2-01 Class members in the finding record (2026-11-26)

- Owner: "yes that matches, go with members in the record".
- `findings new` takes each class member explicitly (`--member <text>`, repeatable), found by a search, not only the case hit; `gate_register` refuses a finding whose class has no members.
- The record holds `members: [{id, text, test, status, found_by, found_in}]`. A member is resolved when it names its test; the finding cannot close (V2-08) until every member is resolved, so class-completeness is checked by the tools.
- A member found by a later review is added to the same record with its own `found_by` and `found_in` (it feeds the late-findings measure); it does not become a new finding.
- Records without a member list (older ones) stay valid and count as one member until edited.
