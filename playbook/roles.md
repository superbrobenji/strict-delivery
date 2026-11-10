# Base playbook: roles

Each framework role has a prompt block, a minimum tier, a budget cap, whether it needs a brief, and the finding states it may propose (spec §10). The prompt blocks and minimum tiers are fixed in the framework and are the same in every profile; config `roles` adds only project roles, each with its own prompt block and minimum tier. Every role needs a brief. No role sets the finding state that only the cleanup step sets.

| role | prompt block | minimum tier | needs brief | finding states |
|---|---|---|---|---|
| program_controller | skills/strict-delivery/prompts/program_controller.md | tier3 | yes | open, planned, in-progress, deferred, closed |
| stream_controller | skills/strict-delivery/prompts/stream_controller.md | tier3 | yes | open, planned, in-progress, deferred, closed |
| controller | skills/strict-delivery/prompts/controller.md | tier3 | yes | open, planned, in-progress, deferred, closed |
| implementer | skills/strict-delivery/prompts/implementer.md | tier2 | yes | fixed-unpinned, pinned |
| implementer_transcription | skills/strict-delivery/prompts/implementer_transcription.md | tier1 | yes | fixed-unpinned, pinned |
| task_reviewer | skills/strict-delivery/prompts/task_reviewer.md | tier3 | yes | open |
| final_reviewer | skills/strict-delivery/prompts/final_reviewer.md | tier3 | yes | open |
| final_verifier | skills/strict-delivery/prompts/final_verifier.md | tier4 | yes | open |
| exception_reviewer | skills/strict-delivery/prompts/exception_reviewer.md | tier4 | yes | none |
| audit_reviewer | skills/strict-delivery/prompts/audit_reviewer.md | tier3 | yes | open |
| audit_verifier | skills/strict-delivery/prompts/audit_verifier.md | tier3 | yes | open |
| investigator | skills/strict-delivery/prompts/investigator.md | tier3 | yes | none |

## Model tiers

A role runs at its minimum tier or above, and a dispatch names a tier, never a model: config `models.tiers` maps each tier to the model the project uses. The top tier, `tier4`, is allowed only for the roles in `top_tier_roles`, by default `final_verifier` and `exception_reviewer`. `tier4` has no default model; while it is unset, the `top_tier_roles` run at the tier `top_tier_fallback` names, default `tier3`. A small re-review that the dispatch check admits may run below the reviewer's minimum tier (`playbook/review.md`, "Small re-review").

## Budget cap

Each role's budget cap is config `budgets.<role>`; the framework sets no default cap. Every brief states its budget in tokens and minutes, never in tool calls, and an agent stops at its next step boundary when it nears either limit.

## Dispatch contract

A dispatch prompt carries these headings, in this order: `## Role`, `## Brief`, `## Findings`, `## Claims`, `## Budget: tokens=<n> minutes=<n>`, `## Model`, `## Report`, `## Strict block`, `## Task`. The first non-empty line of the `## Role` body is exactly one role id. The `## Strict block` body is an empty line, the role's prompt block byte for byte, and an empty line; the block is never edited. A fork dispatch is refused. The dispatch's model equals `## Model` and meets the role's minimum tier. A worker role dispatches no agent, and a dispatch whose dispatcher is a worker role is refused (`gate_dispatch`).

## Report contract

Every report starts with the line `status: DONE|DONE_WITH_FINDINGS|NEEDS_DECISION|BLOCKED|DENIED`, holding one of those values. When more than one applies, the first of DENIED, BLOCKED, NEEDS_DECISION, DONE_WITH_FINDINGS, DONE is reported. DONE means every claim and gate re-ran clean and the change holds no finding; a defect the change did not cause goes under Unrelated findings and does not by itself make the status DONE_WITH_FINDINGS. Each role's report lists its fixed fields in a fixed order (the implementer's: commits; gates run; claims; findings raised; unrelated findings; decision needed; denials; budget used), and the final reply is at most ten lines with the same fields. A controller never returns while its children run: questions and progress go up to its parent as messages, and answers come down as decision records.
