# Process learnings carried into the framework (draft for owner review)

Status: draft, 2026-11-24, program controller. Owner direction (2026-11-24): "we need to also implement the findings to the framework and carry relevant mitigations to it too to prevent similar problems in the future with the framework."

Source: the ledger on `block/docs-resume`, 2026-11-24 entries, and the owner answers named in each row. Each row says what went wrong while building v0.1 with this process, what the framework should do so its users do not hit it, and where in the framework that change lands. Section numbers are those of `docs/strict-delivery/specs/2026-10-31-strict-delivery-framework-design.md`; the exact spec text and plan tasks are written after the owner approves this list.

## A. Review loops and final reviews

| # | What happened | Framework change | Lands in |
|---|---|---|---|
| A1 | Every update from main that touched a consumed module restarted a whole-PR final review (1-2 h each), re-reading code already reviewed. | Delta final review: after an update from main, the final review covers the update diff, the main changes to consumed modules and how the PR uses them, and a full suite on the new head. A fresh whole-PR review only when the PR's own code changed beyond reviewed fix diffs. | §10 Agent management; `final_reviewer.md`, `controller.md` prompt blocks |
| A2 | Findings arrived one class member per round (4c.1: symlink target, then parent, then search-only directory; 5b.1: tip symlink, then directory). Loops ran to ESCALATE and leftovers became new tasks (5b.3). | Class-complete findings: a finding lists every class member from a search; the fix tests each member; a re-review checks the list for missing siblings first. `findings new` takes a members list; `gate_register` refuses a class with no members. | §7 Decisions, findings, claims; §10; `task_reviewer.md`, `final_reviewer.md`, `implementer.md`; `gates/lib/findings.py` |
| A3 | Path-handling code missed the same hostile inputs task after task. | Standard hardening rows: every input-domain table for code that reads, writes or walks paths carries symlink, directory, FIFO, parent swap, equal or nested configured paths, non-UTF-8 and outside-root rows from round 1. `check dispatch` warns when a path-handling brief's table lacks them. | §8a Methods and conventions; `drafter.md`; `gate_dispatch` |
| A4 | An ESCALATE stop produced a new task and PR for three small leftovers. | The owner question after ESCALATE or STOP_NARROW recommends folding open LOW/MEDIUM findings into a planned task of the same stream that touches the same code; a new task only when none exists or the fix is large. | §10; `controller.md` |

## B. Test and mutation cost

| # | What happened | Framework change | Lands in |
|---|---|---|---|
| B1 | Whole-module mutant tables (86-100 ids) took 1-3.5 h per batch and starved other work. | Mutation volume rule: tables plant bugs only in lines the task adds or changes; fix rounds re-run only their own mutants and the survivors they target; a final reviewer runs at most 10 targeted mutants. | §8a; §13a Evidence contract; `implementer.md`, reviewer blocks |
| B2 | Each PR head ran the full suite three times (stream, program controller, CI). | Merge gate accepts the stream's logged full suite on the exact head sha plus CI green; the merging controller runs the record checks, `run_all` and the ancestor check only. | §11 Programs and streams (merge); `program_controller.md` |
| B3 | Parallel streams on one machine overloaded it (load 55-60 on 10 cores): suites timed out, batches starved suites and each other. | A machine-local runner for target projects' parallel work: one full-suite slot; mutant batches in a fixed number of slots, shared lock so they never run beside a full suite; a turnstile so a waiting suite is not starved; one batch per stream; a per-batch worker cap. Configurable (`runner.suite_slots`, `runner.batch_slots`, `runner.batch_jobs`). | §11; §6 Config; new `gates/tools/runner.py` (today: `_program/par_suite.py`, `par_mutants.py`, outside the repository) |
| B4 | A stopped mutant batch left slot worktrees with mutants applied. | The runner restores and removes slots on interrupt (signal handler) and lists leftovers in `doctor`. | B3's runner; §4 `doctor` |
| B5 | CI's newer git (Homebrew 2.56.1) left a detached auto-maintenance lock that broke a ".git unchanged" test; local Apple git 2.50.1 did not. | Test fixtures that create repositories disable `maintenance.auto` and `gc.auto`; `init`'s generated test helper and the playbook say so. | §14 Testing the framework itself; §8 Base playbook |

## C. Process records and PRs

| # | What happened | Framework change | Lands in |
|---|---|---|---|
| C1 | Mutation transcripts were written free-form for weeks, then a new schema check would have failed 28 of them. | A record schema is checked from the first commit that writes such a record: a producer's schema lands with or before the producer, never in a later registry request. | §13 Gate contract; `plan_writer.md` (task ordering rule) |
| C2 | Three handoff files lacked `block:` and failed handoff/1; SessionStart printed FAIL lines. | Handoff files are written only by the `continue`/checkpoint tool, never by hand; `doctor` lists nonconforming handoffs. | §4; §9 Context; `controller.md` |
| C3 | A PR opened with a placeholder line in its body, and no agent may edit PR bodies afterwards. | The PR body is rendered from records before `gh pr create`; a check refuses unresolved placeholders (`FULLSUITE`, `<head>`) in the body file. | §11; `gate_checkpoint` or a new `pr-body` check |

## D. Enablement and ordering

| # | What happened | Framework change | Lands in |
|---|---|---|---|
| D1 | `hooks/hooks.json` on main routes Bash, Agent and Edit to handler modules not yet on main; the hook fails closed, so enabling the plugin would refuse every such call. The enable point in the plan came before the handlers. | `hooks.json` registers a hook event only together with its handler module (a package test fails when an entry names a missing module), and the enable point is "all registered handlers present", checked by `doctor`. | §3 Packaging; §16 The framework repository's own process; `tests/test_plugin_manifest.py` |
| D2 | The program controller missed asking the owner at the enable point. | Owner-action points in a plan (enable, measure, approve) are listed in the breakdown as events; `program` status prints the ones reached and not yet ledgered. | §11; `gates/tools/program_cli.py` |
| D3 | A classifier denial was nearly routed around (same edit, other tool). | `controller.md` states: a denied action is surfaced to the owner; the same effect by another tool or command is the same action. | §10; `controller.md` |

## Questions for the owner

1. Which rows are in v0.1 and which go to v0.2? Recommendation: A1, A2 (prompt text only), A4, B1, B2, B5, C3, D1, D3 in v0.1. They are prompt or check text, and D1 protects every adopter at the moment they enable the plugin. A2's tool change, A3's dispatch warning, B3, B4, C1, C2 and D2 go to v0.2, because each is a new feature with its own tests.
2. Does B3 (a runner inside the framework) belong in the framework at all, or stay a recipe in the playbook?
