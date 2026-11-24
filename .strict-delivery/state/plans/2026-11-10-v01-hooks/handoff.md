---
schema: handoff/1
---
# Stream hooks handoff (program 20261110-v01, sub-blocks 3b and 5a)

## plan
docs/strict-delivery/plans/2026-10-31-strict-delivery-framework.md

## spec
docs/strict-delivery/specs/2026-10-31-strict-delivery-framework-design.md; docs/strict-delivery/specs/2026-10-31-programs-and-streams-design.md; docs/strict-delivery/specs/2026-11-02-session-resume-and-questions-design.md

## branch
block/hooks-main (the PR-5a head: sub-block 5a merged at c025108 and group 3b, Task 3b.1, merged at 3194b4f)

## head
4341602 plus this checkpoint commit

## base
main 3f65424 (merge-base); origin/main has since moved to 738babe (PR-P4)

## ledger
.strict-delivery/state/plans/2026-11-10-v01-hooks/ledger.md

## resume line
Resume strict-delivery plan docs/strict-delivery/plans/2026-10-31-strict-delivery-framework.md at PR-5a: review 2 of fix rounds 1-2 (ch/pr5a-review-2.md), then the full suite on the PR head and gh pr create; branch block/hooks-main; open questions: none.

## block
5a (with 3b.1 carried)

## next task
After PR-5a merges: Task 3b.2 after merged runtime and PR-P3; 3c and R3 per the breakdown.

## findings in flight
FR-1..FR-4 (F-20261122-z68a, -w7i4, -byyn, -qkja) and F3b-1, F3b-2 (F-20261122-snkg, -98sa): fixed in 7698a44..4341602, under review 2. FR-5 (F-20261122-m9w7): closed by the 3b final review and this checkpoint. Registered open LOWs: F5-1, F5-2, F5-3 (F-20261122-q7y6, -2v5n, -nvbn).

## open decisions
none.

## rulings
none taken in this sub-block end.

## grant
PR-5a merge: the program controller merges after reading the reports.

## live subagents
PR-5a review 2 (task_reviewer, read only, scratch worktree).
