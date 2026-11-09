---
name: strict-delivery-repo
description: "Use at the start of every session in this repository, after a compaction or in a new session, and before every change: this repository's paths, the resume flow, checkpoints, background jobs, owner questions and the by-hand checklist. Read with the user-level strict-delivery skill."
---
# strict-delivery: this repository

This is this repository's interim process text until the framework delivers it (session-resume design §3.12, §5; plan Task 1c0.2). The user-level skill stays unchanged.

## Invoke first

1. Invoke the user-level `strict-delivery` skill, then this one (`strict-delivery-repo`).
2. Where the two differ on a path, this skill wins. On every other rule the user-level skill and this repository's merged prompt blocks bind; superpowers skills stay unmodified and rank below both (main spec §3).
3. The main session reads `skills/strict-delivery/prompts/controller.md` as it is on `main` (`git show origin/main:skills/strict-delivery/prompts/controller.md`) and follows it as its own block (session-resume design §3.12).

## Paths in this repository

- Specs: `docs/strict-delivery/specs/` (the main spec, the programs and streams design, the session-resume design).
- Plans: `docs/strict-delivery/plans/` (this plan: `docs/strict-delivery/plans/2026-10-31-strict-delivery-framework.md`).
- Plan state: `.strict-delivery/state/plans/<plan>/`, holding `ledger.md`, `handoff.md` and `breakdown.md` (for this plan: `.strict-delivery/state/plans/2026-10-31-strict-delivery-framework/`).
- Prompt blocks: `skills/strict-delivery/prompts/`, one file per role. A dispatch carries its role's block verbatim, as on `main` (`git show origin/main:skills/strict-delivery/prompts/<role>.md`), never edited.
- Gates: the enabled `python3 -m gates check <gate>` list. On this branch's base: `check schema`, and `check cites` (registered; it fails `cites.input` until its module lands, Task C2.2). `check decisions` is enabled from Task 1c.1 and `check register` from Task 1c.2, each as soon as it lands (P:39, plan "Process for this plan", "Bootstrap"); neither is registered on this branch; `python3 -m gates run_all` replaces the list once block 2b lands (Task 2b.3).
- Test command (plan Global Constraints): `/usr/bin/python3 -m unittest discover -s tests -t . -v` and `/opt/homebrew/bin/python3.13 -m unittest discover -s tests -t . -v`.
- The file paths the user-level skill names belong to another repository and do not apply here; use the paths above.

## Session resume

A session or agent that starts with no memory of the work (a compaction, a new session, a continuation) runs these six steps in order (plan Process bullet "Session resume"; session-resume design §3.1):

1. Invoke every skill in the handoff's `skills`, in order.
2. Read the default session load and start order: spec §7.4, `in-force.md` and the open decisions; spec §9, the context list of the session's kind; for a program session, programs design §10: the CLAUDE.md block, `in-force.md`, `INDEX.md`, the live programs' status pages and `python3 -m gates context program`. Then read the handoff's `required_reads` with their line ranges, and the ledger from line `ledger_from`.
3. Dispatch one read-only `investigator` with the fixed questions of section "Investigator check" (Q1-Q9; a program session G1-G4). It changes nothing and reports to the session.
4. Write the prose ledger line `Resume check: head=<sha>; differences: <none or Q-ids>; report <path>.` (no new ledger keyword).
5. Report where things stand and what comes next, with the findings, to the owner (an agent: to its dispatcher, as a message, controller block "Report contract."), before any edit or any dispatch but the investigator's.
6. With no difference, take over at once: start the next streams, or resume in-progress ones as they were. With any difference, stop and wait for the owner (an agent: status NEEDS_DECISION naming each difference).

A program session keeps no handoff: after any compaction it re-reads the overview and the status pages (programs design §4.4), and its investigator checks the status page's program facts. A continued worker never dispatches (spec §10), so its dispatcher runs the check before the continuation dispatch and puts the report in the continue brief.

## Investigator check

The investigator answers each question with one line, `Q<n> <fact>: match` or `Q<n> <fact>: differs: <recorded value> vs <real value> (<command>)`; `G<n>` the same.

For a handoff:
- Q1 each `worktrees` entry: `git -C <path> merge-base --is-ancestor <head> HEAD` exits 0 and `git -C <path> symbolic-ref --quiet --short HEAD` equals `branch` (no output for `null`).
- Q2 each entry's `git -C <path> status --porcelain --untracked-files=all`, without the handoff's and the ledger's lines, equals `porcelain`.
- Q3 the handoff's `head` is an ancestor of `HEAD` of its worktree and its `branch` is that worktree's branch (the P:2330 rule).
- Q4 the ledger is committed (`git status --porcelain -- <ledger>` empty) and its line `ledger_from - 1` is its last `CHECKPOINT` line.
- Q5 each `live_subagents` entry: the last record of its `transcript` equals `last_record`.
- Q6 each entry: every background job id its transcript starts has a completion record or a TaskStop, and the states agree with `jobs` (a job with neither is `running`).
- Q7 no agent transcript of the session newer than the handoff's commit is missing from `live_subagents`.
- Q8 each `required_reads` path exists and its line range lies within the file.
- Q9 the open decision records equal `open_decisions`, each `findings_in_flight` id has a record, and `batch_cut`, when set, is an ancestor of `HEAD`.

For a program session:
- G1 each stream's handoff, read as the committed file at the tip of its stream branch (`git -C <root> show <branch>:<path>`, never from the integration worktree), parses, names that `branch`, and its `head` is an ancestor of the branch tip.
- G2 each status row's `branch` and `next task` equal that stream's handoff.
- G3 each `Agent:` line of the status page: Q5-Q7 on its transcript.
- G4 the status page's `Integration:` head is an ancestor of the tip of `<program>/integration`, and `Batch-cut:`, when not `none`, is too.

## Checkpoints and complete handoffs

- Triggers, unchanged, for every controller, the main session included (controller block "Continuation."): a block or task checkpoint, 80 % of the token or time budget, or a usage-limit stop. One block per agent context, at most `block.max_tasks` tasks. No limit has a default (Q-H2, P:1779).
- At a checkpoint: append the `CHECKPOINT <block> <task> head=<short sha> tests=<passed>/<total> gates=<PASS|n/a> next=<task id>` line to the ledger and rewrite `handoff.md` beside it (plan Process bullet "Checkpoint after every task"), then commit both after the commit gate.
- The handoff fields: the fields spec §9 lists for `gate_checkpoint` (plan, spec, branch, head, base, ledger, resume line, block, next task, findings in flight, open decisions, rulings, grant, live subagents), plus `live_subagents` as entries (agent, task, worktree, transcript, last record, background job ids with their state), `worktrees` (path, branch, head, `git status --porcelain --untracked-files=all` output without the handoff's and the ledger's own lines), `required_reads` (path, optional line range, why), `skills` (in invocation order), `ledger_from` (the ledger line after the `CHECKPOINT` line just written) and `batch_cut` (the commit of the last printed owner batch, or none); each question carries its recommended option and `source`.
- The handoff never tells the next session to read less than the default load and start order plus `required_reads`.
- A statement that a handoff is complete carries three outputs, pasted: `git status --porcelain --untracked-files=all`; the handoff field check (by hand against the field list above until `python3 -m gates check checkpoint --plan <plan>` exists, Task P1.3); and the background-job check of section "Background jobs".
- "Safe to clear" is never said: nothing is cleared at any level.

## Background jobs

- Before ledgering an agent's result, the controller lists the agent's background job ids from its transcript. Each has a completion record, or is stopped with TaskStop and the stop is ledgered.
- A notice that an agent "is waiting on its own background work" leaves its task open.
- The session reaps its own jobs before it reports (spec §8; controller block "Background work.").
- Workers: a poll loop has a bounded timeout and never matches its own command line; a job no longer needed is stopped with TaskStop, not `pkill`; the report lists each background id as `finished` or `stopped` (plan Process bullet "Background jobs"; session-resume design §3.4).

## Skill per change kind

- A new rule, feature or format with no settled design: superpowers:brainstorming to an owner-approved design, then a spec edit.
- A plan change: superpowers:writing-plans against the spec.
- Execution: superpowers:subagent-driven-development or superpowers:executing-plans, under the strict blocks.
- A controller that has not invoked the skill for the change in its current context dispatches no writer for it (plan Process bullet "Skill per change kind"; session-resume design §3.5).

## Owner questions

- What is asked (owner directive 2026-11-09): small format, syntax, byte or whitespace, wording, layout, naming, test-detail, test-helper-contract and error-return-shape questions inside the plan's intent are not asked; the controller takes the option it would recommend and ledgers `Decision (owner delegation): what -- why -- cost if wrong`, outside the rulings cap. The owner gets work added or removed, plan and spec changes, architecture choices, framework or process changes, agent models and costs, merge-blocking risk, and anything irreversible or otherwise important; a question in a `decision_classes.owner_only` class is always asked; when unsure, ask. Search before asking, by hand until `decisions ask` prints candidates (Task 1d.1): by the question's topics, paths and words of at least 4 characters, over the ledger, the plan's owner-answer sections and every task's "Owner answers applied" line, the stream breakdown and its edits, both specs and the session-resume design, and through `git log -S` of every plan or spec line the question quotes. A question found answered is not asked; the answer is cited instead. Each kept question lists its search terms and says "no answer found".
- Printed fields, in this order: id, class, the question, the recommended option with its cost (none for class `model-policy`), every alternative with its cost (at least one; no cap), effect, topics, `applies_to`. The tool-only fields (schema, status, asked_at, asked_by, checked_against, supersedes, source) are not printed.
- One batch per stop: questions raised mid-task wait for the next stop (a review verdict or the block end) and go as one batch, never one at a time.
- `Also open`: when a new batch arrives while earlier questions are open, the message holds the new batch, then a section `Also open` with every earlier open question given whole, with the same fields. An answered question drops out.
- Grouping: within each section the questions are grouped by `source`, the report or handoff each came from, one header per source; topics stay subject tags.
- These come from the plan Process bullet on owner questions and session-resume design §3.6-§3.7.

## Restarting agents

An agent restarts as soon as every question with its `source` has an answered record; others in the batch may still be open (session-resume design §3.8). By its position in the tree:
- A worker or reviewer stopped with NEEDS_DECISION and returned: its controller dispatches a fresh agent of the same role whose brief carries "Owner answers (date), binding" for its source.
- A controller still alive and waiting: the session tells it to continue.
- A controller that handed off: `continue` (Task P4.2) builds a fresh one.

Only the session writes decision records; workers never do, and never change anything for a question. Fix and re-review rounds run until a clean pass (L:98, X-43).

## By-hand checklist

Until the framework delivers each rule's tool or skill text, these bind the session and every dispatch it makes (session-resume design §3.12; owner answer Q-AUD-1 (a), L:491). CB is the controller block, `skills/strict-delivery/prompts/controller.md`:

- B1 the main session follows CB as its own block (§3.12; Q-AUD-1 (a), L:491);
- B2 every statement read or written is checked directly and by contradiction, both commands recorded; no unchecked guess is shown to the owner (CB "Verification method."; L:415);
- B3 search before asking, by topics, paths and words of at least 4 characters, over the ledger, the plan's owner-answer sections and "Owner answers applied" lines, the breakdown and its edits, both specs and the design, plus `git log -S` of every quoted line; each kept question lists its search terms and says "no answer found" (spec §7.4; L:103; L:490);
- B4 an owner-only class is never decided or inferred from chat (CB "Owner-only decisions."; spec §7.1);
- B5 questions wait for the next stop and go as one batch, with `Also open` and every printed field, `applies_to` included (P:55; MS:606; design §3.6-§3.7);
- B6 only the controller rules, only on plan-vs-spec or task-vs-task conflicts the spec settles, each ledgered as `Ruling: what -- why -- cost if wrong -- spec cite` before the next dispatch, at most `rulings.max_per_block` per block; a plan-vs-spec conflict is corrected to the spec by the controller (MS:332-334; CB "Rulings."; owner Q-LT-1 (a));
- B7 the commit gate for every commit, state commits included: the test command of P:35 on both interpreters, every enabled `check <gate>`, an empty `git status --porcelain --untracked-files=all` (P:35); a checkpoint commits the handoff and the ledger after that gate (design §3.3, DD:60), and the ledger is committed after each owner answer (Q-AUD-1 (a), L:491);
- B8 every dispatch has the nine headings in order, and `## Strict block` is the role's merged block byte for byte (MS:566-570; CB "Dispatch discipline."; Q-SDDT-4 L:435); a role with no merged block on `main` (`plan_writer`, `plan_reviewer`, and `drafter`, the framework role of owner Q-RDp-A (a)), until the plan roles' blocks merge, carries the `investigator` merged block verbatim, with the draft-only rule in the brief (owner Q-RDp-B (a));
- B9 every child gets the Budget line and the 80 % stop (CB "Budget."; P:41);
- B10 every report's first line is `status:` with one of the five values, in the stated precedence (MS:574-575; CB "Report contract.");
- B11 the fix loop (rounds 1-3 resume, rounds 4-5 a fresh agent one tier up, then an owner question) and the process-defect stop (MS §8: findings that keep arriving round after round: stop fixing, find where they entered and why reviews missed them, bring the process change to the owner) (MS:487-488; MS:573-574; CB "Continuation.", "Finding class.");
- B12 the small-re-review rule, its check recorded per re-review (L:406-L:408): only a `task_reviewer` re-review qualifies; it runs at the tier of the config key `reviews.small.tier`, default tier2; a fix touching an excluded path never qualifies, the framework default being the framework's own wiring (`.strict-delivery/**`, `.github/workflows/**`, `.claude/**`, `CLAUDE.md`) plus L:406's list in this repository's config; the controller's `small-re-review:` line states condition 4's no open owner question and condition 5, and the gate, once built, checks conditions 1-3, condition 4's severities and 6-8 (by hand until then) (owner Q-RD-10 (b), Q-RD-11 (b), Q-RD-12 (a), L:516);
- B13 each finding's class `class: <dimension>: <members>` is ledgered and quoted in fix dispatches (P:53; CB "Finding class.");
- B14 each finding is relayed by its substance, not by counts (owner L:488);
- B15 document re-reviews run in full until a clean pass; a cosmetic item (no change of meaning) is not a finding and earns no fix round, and a minor is a real defect, fixed, or registered as a LOW under LOW_PLATEAU, and otherwise never deferred (owner L:98; Q-CAT-8 L:442; design §3.8, X-43; Q-CONV-1 (a) L:687, DN-4 (b));
- B16 the plan file and both specs belong to the session controller and the owner; a stream edits only its own task sections of the plan, and never another stream's file: it writes the need under `## Requests` and stops at a step boundary if blocked (owner Q-B1f-2 (a) L:319; design Appendix S V-9; P:6271-6272);
- B17 an owner-approved design is committed at approval, in the docs-only pull request that carries it, before the plan and spec edits built on it (Q-BD-6, DD:136);
- B18 the agent shell rules bind every agent, the main session included: temporary files only in its own `mktemp -d`, never the shared scratchpad; no `git stash` in the shared checkout; no heredocs; no `rm`, `rmtree` or `os.remove`; no `$(...)` except `mktemp`; a slip is disclosed in the report, and the main session's in the ledger (design Appendix S C-32, C-33; L:132; owner Q-RA2-3 (a));
- B19 `## Model` names the model the role's resolved tier maps to, as MS:569 requires; every other line of a brief or report names tiers, never a model (CB "Dispatch discipline.", read under owner Q-RA2-4 (b); P:1921; P:2935).

## Until the framework delivers

- The new handoff fields are body sections of `handoff.md`, one per field, headed by the field name, until Task P1.2 gives the handoff/1 schema these fields; Task P1.3 Step 5 moves them into the front matter (session-resume design §5).
- Owner batches are written by hand in the shape of session-resume design §3.7 until Task 2c.1 is on `main`; from then on the session commits the new records, prints the batch with `python3 -m gates decisions batch --since <cut-off>` and records that commit as the handoff's `batch_cut` (session-resume design §5; owner Q-RA2-2 (a)).
- The search before asking runs by hand until Task 1d.1's `decisions ask` prints candidates.
- This skill is removed once the plugin is enabled here (MS:715; owner answer Q-PLG-1 (a); stream `residual`, Task R5.1), and the interim text of `CLAUDE.md` by Rq-4-5 (stream `init4`).
