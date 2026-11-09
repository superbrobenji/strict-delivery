# Base playbook: review

How work is reviewed and verified, how the fix loop runs and when it stops. The mutation review and the clean-copy review are rules, not text here: `playbook/rules.md` rows `SD-R9` and `SD-R10`.

## Task review

A `task_reviewer` judges one task's diff. Reviewers execute every claim and re-run every gate themselves, on a clean copy of the reviewed head (row `SD-R9`); before a review the controller trial-merges the branch with the base branch and runs the full suite on the merged tree. A reviewer has no out-of-scope bucket for the task's own code: one defect the change caused goes in findings, one it did not cause goes under Unrelated findings with file:line, a reproducer and its class statement, and gets a register row and an owner. A cosmetic item (a dash, a space, wrapping, wording with no change of meaning) is not a finding: the reviewer marks it cosmetic, and it is noted, folded into the next real edit, or dropped. The report is DONE when every claim and gate re-ran clean and the task's diff holds no finding.

## Final review

At a block's end a `final_reviewer` reviews the whole branch against the base branch, not one task: every commit, the sum of the diff and the seams between tasks. It checks that each task's claims were true at the commit that made them and are still true at the tip, that no later commit undid an earlier fix, and that the branch matches the plan section it was built from. A block ends in this order: final review, top-tier verifier, the owner's approval, merge, post-merge gates, checkpoint.

## Verifier

After a clean final review the `final_verifier` tries to break the finished branch. It runs at the top tier, `tier4`, which only the `top_tier_roles` use (or at the configured `top_tier_fallback` when the project sets no `tier4`). It assumes the reviewers missed something: it runs every gate and the test command itself on every interpreter the brief names, runs the suite with `GIT_*`, `TZ` and `LANG` polluted, and feeds each gate and check inputs from outside its whitelist, at the edges of every input-domain row, and in the combinations no single task covered. Its report is DONE only when it could not break the change.

## Fix loop

Zero bugs: a change's own bug makes it incomplete. A minor is a real defect: it is fixed, or registered as a LOW under LOW_PLATEAU, and otherwise never deferred. A cosmetic item is not a finding and earns no fix round. A document re-review runs in full until a clean pass. A deleted test is restored and fixed; dropping a test is never offered as a fix. A class of findings is an epic with child rows, signed off only when every child is resolved and the whole class is tested and reviewed.

Each finding goes back to the implementer with its class quoted verbatim, and every fix is re-reviewed. Fix rounds 1-3 resume the implementer; rounds 4-5 go to a fresh agent one tier up; after round 5 the controller stops and raises an owner question. A small re-review may run below the reviewer's minimum tier ("Small re-review").

LOW_PLATEAU: after two consecutive reviews whose change-caused findings are all LOW (a review with no change-caused finding counts as all-LOW), the loop ends and those LOWs are registered against a named follow-up task instead of being fixed, and the work moves to the final review. A review with no change-caused finding at all is clean, so LOW_PLATEAU ends the loop at a review that holds LOW findings, after a review that held only LOW findings or none. A change-caused CRITICAL or HIGH finding is always fixed, whatever any signal says. Until `python3 -m gates loopstats` exists, the controller applies LOW_PLATEAU by hand.

## Input domains

The input-domain method binds every task, plan and review:

1. Every task whose interface takes an argument or reads a file carries an input-domain table in its brief, copied from the plan's input-domain dimensions: sections per producer, columns `# | dimension | values | expected verdict | test`, one row per parameter or filesystem call and dimension (argument type, subclasses and bool as int, path kind, character class, the character after each indicator, each output position, the resources held on each error path), an Oracle section and a section of the binding owner rulings. A missing table blocks dispatch; a row with no test is a finding, and its fix covers the whole dimension.
2. The oracle is the production path compared with an independent expected value, never one read back from the code under test.
3. An implementer lists every behaviour the brief does not state and every knowing divergence, and stops with NEEDS_DECISION. In a fix round it first lists the invariants the replaced code held and tests each. It writes one mutant per changed production condition or call.
4. Reviewers have no out-of-scope bucket for the task's own code. A class that seems to exclude a failing whitelist input is a class-narrowing question for the owner. A missing table is a finding.
5. Each finding's class is written by input dimension, `class: <dimension>: <members>`, and fix and re-review dispatches quote it verbatim.

A mismatch a table finds is a controller ruling only inside an approved plan, and only when it is a plan-vs-spec or task-vs-task conflict the spec settles; any other mismatch, plan-vs-code included, is an owner question.

## Small re-review

The config key `reviews.small` sets the small re-review. A re-review of fix round 1 to 4 of one task by `task_reviewer` may run at the tier `reviews.small.tier` names (default `tier2`) instead of the role's minimum tier when every condition holds:

1. It is scoped to that fix's diff, not a full re-review.
2. The fix diff has at most `reviews.small.max_lines` changed lines in at most `reviews.small.max_files` files.
3. No changed path matches `reviews.small.exclude`.
4. The findings the fix answers are LOW or MEDIUM only, and no owner question is open for the task.
5. The previous review found no defect caused by a fix.
6. Rule N does not fire.
7. From review 3 on, Rule T converges (`p <= 1/10` with a finite remainder `R`).
8. From review 3 on, with `escape_cost` set, the expected-value figure is below one round.

"From review 3 on" means once the task has had three reviews, so from the re-review of fix round 3; before that, conditions 1-6 decide. Rules N and T are computed over the reviews done before the re-review being dispatched. The dispatch states the conditions on one `small-re-review:` line of `## Brief`. The dispatch check admits the lower tier only when the conditions it can check from git, the finding records and `loopstats` hold (1-3, the severities of 4, and 6-8); the controller's `small-re-review:` line states the rest (no open owner question in 4, and 5), which the small re-reviewer checks. A small re-reviewer must escalate on any defect it finds, on NEEDS_DECISION and when it is unsure, and the next re-review then runs at the role's minimum tier; the re-review of fix round 5 always runs at it.

## Process-defect stop

Findings that keep arriving round after round are a process defect. The controller does not start another fix round: it must stop fixing, find where the findings entered and why reviews missed them, and bring process changes to the owner.

## Rules N and T

After each review the controller may run `python3 -m gates loopstats`, which prints the advisory signals Rule N (novelty) and Rule T (trend) and, when `escape_cost` is set, an expected-value verdict, and ledgers its `Loopstats:` line (`Loopstats: <task> r<k>: X=<...> p=<p> q=<q> nu=<nu> -> <VERDICT>`). The signals never block a fix and never decide whether a found defect is fixed; they decide whether a re-review may run below the reviewer's minimum tier, and LOW_PLATEAU ends the fix loop ("Fix loop").

A finding carries `review_round`, `caused_by_change` and `dimension`. For one task after `k` reviews, the counted findings are those the task's change caused (`caused_by_change: true`) with severity CRITICAL, HIGH, MEDIUM or LOW; `X_i` is the number from review `i`, `N = sum X_i` and `S = sum (i-1) X_i`.

- Rule T: `p = P(S' <= S)`, where `S'` is the sum of `N` independent uniform draws on `{0..k-1}`, computed exactly; the trend is converging at `p <= 1/10`. A truncated-geometric fit (`q` with `sum j q^j / sum q^j = S/N` over `j = 0..k-1`) gives `a = N/(1-q^k)`, the remainder `R = a q^k` and the expected next-round count `E_next = a(1-q) q^k`; at `S/N >= (k-1)/2` the fit is at its boundary, `R` is unbounded and `E_next = N/k`.
- Rule N: the novelty `nu` is the share of review `k`'s counted findings whose `dimension` (one canonical dimension from the input-domain table's row names, given by the reviewer) is on no counted finding of an earlier review; Rule N fires when `k >= 2`, `X_k > 0`, `nu >= 1/2` and `X_k >= X_(k-1)`. A narrowing of the contract is noted and counted, never a reset.

The verdict, in order: `X_k = 0` CLEAN; LOW_PLATEAU as "Fix loop" states it; `k > 5` ESCALATE; Rule N fired: STOP_NARROW, or ESCALATE after a narrowing; `k < 3` CONTINUE; converging and the fit not at its boundary: CONTINUE; otherwise ESCALATE after a narrowing, else STOP_NARROW when `nu >= 1/2`, else ESCALATE. With `escape_cost` set, the expected-value figure is `E_next * sum_s (n_s/N) * escape_cost[s]`, `n_s` the counted findings of severity `s` over all reviews; it reads `continue` above one fix round, else `stop`, and never changes the verdict. A CRITICAL or HIGH finding the change caused is fixed whatever the verdict.

## Review methods

- Test first: a new test is watched red for its stated reason, re-established with a behaviour stub, not only a missing import. When tests came after the code, the red check overlays the new tests on a clone of the pre-change commit.
- Evidence: an input outside a whitelist fails closed with a named check; a divergence is reported with both quotes and no side taken; a pasted result is re-run before it is relied on.
- No claim is trusted: each is verified directly and by contradiction, and both commands are recorded.
- Pinned means a production-path test plus a mutation transcript; the mutation review and the clean-copy review run as `playbook/rules.md` rows `SD-R10` and `SD-R9` state them.

## Plan review

A review of a plan or a spec edit checks:

- every prose quote of 12 or more characters is verbatim in its source, by a whitespace-normalising script re-run after each edit;
- each edit's old text occurs once at HEAD, and its new text occurs once after the edit;
- every `Consumes` name matches the code or an earlier `Produces`;
- owned paths are pairwise disjoint (a trailing `/` means everything under it);
- a sub-block holds at most `block.max_tasks` tasks, each in the full task shape with an executable check that asserts;
- no placeholder (`TBD`, `TODO`) remains;
- an omission is reported as an omission, not as a contradiction.
