# Process learnings carried into the framework (draft for owner review)

Status: draft, revision 2, 2026-11-24, program controller. Owner direction (2026-11-24): "we need to also implement the findings to the framework and carry relevant mitigations to it too to prevent similar problems in the future with the framework." Owner scope rule (2026-11-24): "anything to do with my hardware constraints due to this project should be playbook constraints and not the framework. same with token limits unless otherwise specified. also do not bring in changes to the framework that is just specific workings for the current repo in it's current state."

Source: the ledger on `block/docs-resume`, 2026-11-24 entries. Each row says what went wrong while building v0.1, what the framework should do so its users do not hit it, and where that change lands. Section numbers are those of `docs/strict-delivery/specs/2026-10-31-strict-delivery-framework-design.md`; exact spec text and plan tasks follow the owner's approval of this list.

## Framework changes

| # | What happened | Framework change | Lands in |
|---|---|---|---|
| A1 | An update from main that touched a consumed module restarted a whole-PR final review, re-reading code already reviewed. | Delta final review: after an update from main, the final review covers the update diff, the main changes to consumed modules and how the PR uses them, and a full suite on the new head. A fresh whole-PR review only when the PR's own code changed beyond reviewed fix diffs. | §10 Agent management; `final_reviewer.md`, `controller.md` |
| A2 | Findings arrived one class member per round (4c.1: symlink target, then parent, then search-only directory; 5b.1: tip symlink, then directory); loops ran to ESCALATE and leftovers became a new task (5b.3). | Class-complete findings: a finding lists every class member from a search; the fix tests each member; a re-review checks the list for missing siblings first. `findings new` takes a members list; `gate_register` refuses a class with no members. | §7; §10; `task_reviewer.md`, `final_reviewer.md`, `implementer.md`; `gates/lib/findings.py` |
| A3 | Path-handling code missed the same hostile inputs task after task. | Standard hardening rows: every input-domain table for code that reads, writes or walks paths carries symlink, directory, FIFO, parent swap, equal or nested configured paths, non-UTF-8 and outside-root rows from round 1; `check dispatch` warns when a path-handling brief's table lacks them. | §8a Methods and conventions; `drafter.md`; `gate_dispatch` |
| A4 | An ESCALATE stop produced a new task and PR for three small leftovers. | After ESCALATE or STOP_NARROW, the owner question recommends folding open LOW/MEDIUM findings into a planned task of the same stream that touches the same code; a new task only when none exists or the fix is large. | §10; `controller.md` |
| B5 | A newer git (2.56.1) left a detached auto-maintenance lock that broke a ".git unchanged" test; an older git did not. | Test fixtures that create repositories disable `maintenance.auto` and `gc.auto`; the base playbook's testing section says so. | §8 Base playbook (testing); §14 |
| C1 | A record type was written free-form for weeks before its schema check landed, which would then have failed 28 records. | A record's schema is checked from the first commit that writes such a record: the schema and its producer registration land with or before the producer, never in a later request. | §13 Gate contract; `plan_writer.md` |
| C2 | Hand-written handoff files missed a required field and failed their schema. | Handoff files are written only by the checkpoint tool, never by hand; `doctor` lists nonconforming handoffs. | §4; §9; `controller.md` |
| C3 | A PR opened with a placeholder in its body, and agents may not edit PR bodies afterwards. | The PR body is rendered from records before `gh pr create`; a check refuses unresolved placeholders in the body file. | §11; a `pr-body` check |
| D3 | A classifier denial was nearly routed around (the same edit by another tool). | `controller.md` states: a denied action is surfaced to the owner; the same effect by another tool or command is the same action. | §10; `controller.md` |

## Kept out of the framework (owner scope rule)

Into this repository's own playbook and stream rules (`_program/stream-common.md`, and this repository's playbook entry when it has one), not the framework:

- Hardware: the machine-wide suite slot, mutant batch slots, shared suite lock and turnstile, one batch per stream, the worker cap, slot cleanup on interrupt (B3, B4).
- Run-cost tuning: mutants only on changed lines with targeted fix-round re-runs and at most 10 final-review mutants (B1); the merge gate accepting the stream's suite plus CI instead of a third suite run (B2). These were adopted for this machine's time and token budget; they become framework rules only if the owner says so.

Dropped as specific to building this framework in its current state:

- D1: `hooks.json` naming handler modules that are not on `main` yet. Adopters receive a complete plugin.
- D2: tracking the plugin enable point as a program event.

## Question for the owner

Which rows are in v0.1 and which go to v0.2? Recommendation: A1, A2 (prompt text), A4, B5, C3 and D3 in v0.1, since they are prompt text or small checks; A2's tool change, A3's dispatch warning, C1 and C2 in v0.2, since each is a new feature with its own tests.
