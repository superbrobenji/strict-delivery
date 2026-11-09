---
name: strict-delivery
description: "Use at the start of every session, after a compaction, and before every change of any size (code, tests, tools, CI, docs, specs, plans, memory notes, pull-request bodies, issue text): precedence, roles and tiers, decision classes, owner questions, verification by direct check and contradiction, change kinds, pipeline and gates, session resume and continuation. Overrides superpowers."
---
# Strict delivery

## When it applies

Invoke this skill at the start of every session, after a compaction, and before every change of any size: code, tests, tools, CI, docs, specs, plans, memory notes, pull-request bodies and issue text.

The role prompt blocks in `skills/strict-delivery/prompts/` and the base playbook in `playbook/` hold the rules in detail; this skill names where each rule lives.

## Precedence

Precedence, highest first:

1. The target repository's `CLAUDE.md`, its managed block plus the project text.
2. The strict-delivery skill and prompt blocks.
3. The project playbook, in `.strict-delivery/playbooks/`.
4. The base playbook, in `playbook/`.
5. The superpowers skills, unmodified.

Where superpowers says otherwise (for example "do not re-run the suite" for reviewers), the higher layer wins.

## Roles and tiers

The roles, with their prompt blocks, minimum tiers and finding states, are in `playbook/roles.md`: `program_controller`, `stream_controller`, `controller`, `implementer`, `implementer_transcription`, `task_reviewer`, `final_reviewer`, `final_verifier`, `exception_reviewer`, `audit_reviewer`, `audit_verifier` and `investigator`.

Every dispatch carries its role's prompt block byte for byte and names a tier, never a model; config `models.tiers` maps each tier to a model.

A controller dispatches workers within the configured depth and concurrency limits, and workers never dispatch.

## Decision classes

A question in an owner-only class is always the owner's: the agent that needs it writes the question with its options and their cost, and that path halts until the owner answers.

The classes are config `decision_classes.owner_only`; a project may add its own classes and never drops a default one.

Default owner-only classes: `triage`, `spec-direction`, `scope`, `merge-grant`, `model-policy`, `issue-close`, `finding-class`, `rule-override`, `program-create`, `stream-ownership`, `stream-merge`, `request-dispute`, `program-close`.

`playbook/decisions.md` says what the owner decides in each class.

A controller rules only inside an approved plan, only on a plan-vs-spec or task-vs-task conflict the spec settles, and ledgers each ruling as `Ruling: what -- why -- cost if wrong -- spec cite`; every other open point is an owner question.

## Owner questions

Search before asking: before a question is asked, search for its answer with `decisions find` and the candidates `decisions ask` prints; until those print, search by hand by the question's topics, paths and words of at least 4 characters over the decision records, the ledger, the plan's owner answers, the stream breakdown and the specs, and run `git log -S` on every line the question quotes.

A question found answered is cited, not asked.

A printed question shows, in this order: id, class, the question, the recommended option with its cost, every alternative with its cost, effect, topics and `applies_to`; a question in class `model-policy` carries no recommended option, and the record's `source` names the report or handoff the question came from.

Questions wait for the next stop and go as one batch, never one at a time: `decisions batch --since` with the last cut-off commit prints the new questions and, under `Also open`, every earlier open question given whole, grouped by `source`.

An agent restarts as soon as every question with its `source` has an answered record, while others in the batch may still be open.

Only the session writes decision records; workers never do, and the rest is in `playbook/decisions.md`.

## Verification method

Every statement read or written is a hypothesis until it is checked twice: verify it directly, then by contradiction (assume it false, derive what would then be observable, and run that check), and record both commands with their output.

A statement with no executable check is not written; a divergence is reported with both quotes and no side taken.

The input-domain method, stated in full in `playbook/review.md` section "Input domains": every task that takes an argument or reads a file carries an input-domain table, one row per dimension with its expected verdict and a test, and a row with no test is a finding; the oracle is the production path compared with an independent expected value; an implementer lists every unstated behaviour and stops with NEEDS_DECISION; reviewers keep no out-of-scope bucket for the task's own code; and each finding's class is written `class: <dimension>: <members>`.

## Change kinds

Each kind of change has its superpowers skill: a new rule, feature or format with no settled design goes through superpowers:brainstorming to an owner-approved design and then a spec edit; a plan change goes through superpowers:writing-plans against the spec; execution goes through superpowers:subagent-driven-development or superpowers:executing-plans under the strict prompt blocks.

A controller that has not invoked the skill for the change in its current context dispatches no writer for it.

## Pipeline and gates

Every change, any size, is a register row before work starts.

Each task runs an implementer, a task review and the fix loop until a clean pass; each block ends with a final review and, where the profile enables it (strict), a top-tier final verifier.

Before every commit, `python3 -m gates run_all` and the test command in config `commands.test` are green, with a clean tree.

The base branch is protected: every change reaches it by a pull request on all-green, merged by merge commit on the owner's approval, and the ledger records each merge as a `MERGED` line.

## Session resume

A session or agent that starts with no memory of the work (a compaction, a new session, a continuation) resumes in this order, which `playbook/sessions.md` section "Start order" states in full:

1. Invoke every skill in the handoff's `skills`, in order.
2. Read the default session load (`in-force.md` and the open decisions) and the session kind's context list, then the handoff's `required_reads` and the ledger from line `ledger_from`.
3. Dispatch one read-only `investigator` with the fixed questions of `playbook/sessions.md` (Q1-Q9; a program session G1-G4); it changes nothing.
4. Write the ledger line `Resume check: head=<sha>; differences: <none or Q-ids>; report <path>.`
5. Report where things stand and what comes next, with the findings, before any edit or dispatch other than the investigator's.
6. With no difference, take over at once; with any difference, stop and wait for the owner (an agent: status NEEDS_DECISION naming each difference).

This is skill text; no hook holds the session.

A continued worker never dispatches, so its dispatcher runs the check before the continuation dispatch and puts the report in the continue brief.

## Continuation

Continuation is automatic: an agent that reaches a checkpoint, 80 % of its token or time budget, or a usage-limit stop writes its handoff and returns, and its dispatcher at once dispatches a fresh agent of the same role with a continue prompt built from the handoff, the ledger and the status page.

Nothing continues from inherited memory, and the owner never clears the session and re-prompts.

One block runs per agent context, at most `block.max_tasks` tasks, with a clean worktree at every checkpoint.

A statement that a handoff is complete carries three outputs, pasted: `git status --porcelain --untracked-files=all`, the handoff field check and the background-job check; "safe to clear" is never said, since nothing is cleared at any level.

The background-job check: every agent reaps its background jobs before it reports; a poll loop has a bounded timeout and never matches its own command line; a job no longer needed is stopped with TaskStop, never by pattern-killing processes; and the report lists each background job id as finished or stopped.

Before a controller ledgers a child's result, it lists the child's background job ids from its transcript: each has a completion record, or is stopped with TaskStop and the stop is ledgered; a notice that a child is waiting on its own background work leaves its task open.

The handoff fields are in `playbook/sessions.md` section "Handoffs and continuation".

## Document locations

Specs live in `docs/strict-delivery/specs/`, plans in `docs/strict-delivery/plans/` and reviews in `docs/strict-delivery/reviews/`.

These locations override the default save paths of the superpowers skills: a superpowers skill that names another path saves here instead.

## Judgment, not gated

The rules of `playbook/rules.md` whose `enforced by` column reads `judgment` have no gate: every agent applies them, and reviewers check them by judgment.

A rule is overridden only by a decision of class `rule-override`, and a rule marked `fixed: yes` never is.
