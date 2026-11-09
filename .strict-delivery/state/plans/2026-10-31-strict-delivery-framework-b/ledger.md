# Stream b ledger (plan 2026-10-31-strict-delivery-framework, block sb2)

Block B2 started 2026-11-09: `block/sb2` cut from `main` 13ca17e (owner answer Q-DOCS-1 (e)), worktree `../strict-delivery-worktrees/b/sb2`.
PC1 tables for B2.1-B2.3 refreshed against 13ca17e (git-ignored scratch `task-B2.<n>-domain-v2.md`); owner 2026-11-09 "recommended for all": Q-B21-2..6 (a), Q-B22v2-1..5 (a), Q-B23v2-1..2 (a), Q-B2R-1 (a) (rulings PR-1, R1, R-v2-1..6 confirmed as owner answers), Q-B21U-1..7 (a).
Owner directive 2026-11-09: small format, syntax, layout, helper-contract, naming, wording and test-detail questions are the controller's, logged as decisions.
Decision (owner delegation 2026-11-09): every spec cross-reference dropped from a rules.md row is restored, as plain `spec §<n>` or design-name text -- the rule text is spec §8's -- cost if wrong: longer cells.
B2.1 f8780e7 `docs(playbook): base rules SD-R1..SD-R19`; review: F-B21R-1 MEDIUM (class: table_rows input: table shape), F-B21R-2 LOW (class: rules.md bytes: control and separator characters), F-B21R-3 LOW (class: sentence pin check: sentence boundaries), F-B21R-4 LOW (class: rule text fidelity: spec §8 bullet content dropped or reworded); fix round 1 689162e.
B2.1 re-review 1: F-B21RR-1 LOW (class: sentence pin check: sentence boundaries: terminator followed by a closer or non-ASCII space), F-B21RR-2 LOW (class: rule text fidelity: spec §8 cross-reference or gate attribution dropped); fix round 2 ca3c29c.
B2.1 re-review 2: F-B21RR2-1 LOW (class: sentence pin check: sentence boundaries: terminator with any closer run followed with no whitespace by an uppercase letter, a Cf character, or a CJK/fullwidth terminator), task-caused. LOW run 2 of 2 (owner Q-CONV-1 (a), DN-1 (b)): LOW_PLATEAU, B2.1 loop ends; F-B21RR2-1 registered against Task B2.2.
Request (owner DN-4 (a)): zero-bugs wording "fixed, or registered as a LOW under LOW_PLATEAU, and otherwise never deferred": B2.2 review.md "Fix loop" and its plan key phrase; B2.3 controller.md "Zero bugs." and its pin.
CHECKPOINT sb2 B2.1 head=ca3c29c tests=1125/1125 gates=PASS next=B2.2
