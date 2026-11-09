# Programs and streams: design

Date: 2026-10-31. Status: approved by the owner 2026-10-31. Owner: superbrobenji.
Extends and amends `docs/strict-delivery/specs/2026-10-31-strict-delivery-framework-design.md`
(the main spec). Where they differ, this document wins; section 15 lists every main-spec edit.

## 1. Intent

A large effort run as one long line of work takes unacceptably long. The framework must let a
repository run a large effort as a **virtual team**: several agents, each owning one section of
the effort, working in parallel, steered by one human through one lean session.

The structure must hold over long efforts without three failure modes:

- **Hallucination and context drift.** No agent depends on memory of a long session. Every agent
  starts from written state (plan, handoff, status page, in-force decisions) and verifies claims
  against the repository (main spec §8 "No claim is trusted").
- **Gaps.** Every file and every piece of work has exactly one owner within an effort. Unowned
  work is caught and assigned, never silently dropped.
- **Conflicts.** No two agents in one effort own the same file. Shared work moves only through
  explicit rules and tracked requests.

## 2. Goals, non-goals, anti-goals

Goals:
- Maximum safe parallelism for large efforts.
- A lean human session: it sees the whole picture through one generated overview and receives
  only owner questions and stream reports.
- No manual `/clear` and re-prompt at any level: agents continue themselves from handoffs.
- Several humans, each on their own branch and each using the framework, merge their work to
  main without framework-made conflicts (ids, registers, program folders).
- A lean tree: per-effort documents are cleaned when the effort is done; git history keeps them.

Non-goals:
- Coordinating agents of *different* humans. Each human's effort is self-contained; clashes
  between humans' code are ordinary git and pull-request review.
- Streams for small work. Small work stays a plain plan (main spec §17 blocks, unchanged).

Anti-goals (failure even if it works):
- A global truth recorded only in a per-effort document that is later cleaned.
- Ids or folder names that carry a person's name or handle (they read as ownership and create
  tension between people).
- The human session filling with implementation detail.

## 3. Concepts

- **Plan:** an ordinary plan (main spec §8, §17) run by one controller. Used for small work.
- **Program:** a large effort, split into streams by a program plan. Used only when the owner
  plans a large effort.
- **Stream:** one section of a program: a sequence of ordinary blocks on its own branches and
  worktrees, run by one stream controller, owning a set of files.
- **Owner (human):** the human driving the session. "Owner" and file ownership are local to one
  human's effort: they exist so that agents do not collide. Another human's effort has its own
  owner and its own ownership map, and may own the same file for its own agents. There is no
  global owner setting. Answers and withdrawals come only from the human: the PreToolUse hook
  refuses `decisions decide` and `decisions withdraw` from any subagent, and the human runs them
  (`!` prefix) or the main session (the program session) records the owner's exact words. Each answer records the
  git identity (`git config user.email`) as `answered_at.by`.
- **Interface:** anything one stream needs from another (API, shared module, data format). Agreed
  in the program's spec before streams start; the owner rules on any later conflict.

## 4. Roles and hierarchy

| Level | Role | Runs as | Does | Never |
|---|---|---|---|---|
| 1 | program session | the owner's Claude Code session (thin shell) | talks to the owner; shows the overview; relays owner questions in one batch; by default acts as the program controller itself (row 1a; owner answer Q-H5 (a)); in `controller` mode merges a pull request on the owner's chat approval (section 5) | implements, reviews, or holds detail |
| 1a | program_controller (a separate agent only when the configured depth allows; otherwise the program session does these duties) | agent dispatched by the program session | reads the status page, handoffs, requests; dispatches and re-dispatches stream controllers; mints ids and writes request records for its program; runs syncs; returns owner questions and reports to the session | implements, reviews; merges, except the sync's merges (section 10) and, in `controller` mode, a pull request on the owner's chat approval |
| 1 (2 under a separate program_controller) | stream_controller | agent dispatched by the program session or a program_controller | runs one stream's plan block by block in its own worktree: dispatches sub-controllers, implementers, reviewers, verifiers as main spec §10; raises cross-stream requests; returns owner questions (stopping NEEDS_DECISION) and checkpoint or completion reports; merges its group branches into its stream branch (section 4.1); opens the stream's pull request to the base branch when the stream is finished | edits another stream's files or status row; merges any pull request, pushes to the base branch or merges the integration branch into its own; rebases another stream; works around an owner question |
| 2+ | controller (sub-controller; may dispatch a sub-controller, owner answer Q-H3), implementer, task/final reviewer, final verifier, exception reviewer, audit roles, investigator | as main spec §10 | unchanged | unchanged |

- Models: program_controller and stream_controller at the reviewer tier (tier3); the top tier stays
  only for the roles in `top_tier_roles`, by default the final verifier and the exception reviewer (main spec §10).
- Dispatch: only the program session dispatches a program_controller; the program session or a program_controller dispatches a stream_controller; stream controllers and sub-controllers dispatch sub-controllers and workers; `gate_dispatch` refuses any dispatch from a worker role and any dispatch that leaves too few levels below it for the depth limit (owner answers Q-H1..Q-H5, 2026-11-01). Each new role has a prompt block in `skills/strict-delivery/prompts/`.
- Depth-aware tree (owner answer Q-H5 (a)): by default the program session itself acts as program controller (status page, ids, requests, syncs, one question batch); stream_controller runs at level 1, sub-controllers at level 2, workers at level 3. A separate program_controller agent, and nested sub-controllers, are used only when the configured depth allows them.
- Both new roles are core to the framework, not an add-on.

### 4.1 Parallel work inside a stream

A stream is not one agent at a time. It runs as a tree of worktrees:

```
<worktrees>/<program>/<stream>/main      stream worktree, stream branch <program>/<stream>/main
<worktrees>/<program>/<stream>/<group>   child worktree per sub-controller, branch <program>/<stream>/<group>
   implementers and reviewers work in the child worktree (or their own grandchild worktree per task)
```

- The stream plan marks which task groups run in parallel. Groups running at the same time own
  disjoint file sets. Each level's set is a subset of its parent's: program, then stream, then
  group, then task. `gate_plan` refuses a plan whose parallel groups overlap: a task in two groups, or a group holding two tasks joined by a path of edges. It also refuses two non-residual streams whose owned paths overlap while their windows intersect, comparing paths as section 12 compares owned paths; two windows on one path are disjoint when they are chained (one's `until` is the other's `from`) or ordered by the breakdown's edges (owner answer Q-F80-1 (a)).
- Worktree paths mirror branch paths in nested folders. The stream worktree sits at
  `<stream>/main`, beside its groups, not above them: a group worktree nested inside the stream
  worktree shows there as an untracked folder and leaves it unclean. Ids match `[a-z0-9][a-z0-9-]*`, so dashes
  are allowed and `/` is not.
- Each sub-controller runs its group's tasks (implement, review, fix loop as main spec §6-§10). A sub-controller may dispatch a sub-controller when the stream controller judges it better, within the depth limit (owner answer Q-H3).
  The stream controller merges each group branch into the stream branch, one group at a time,
  after a clean review and green gates; this merge needs no owner grant. It re-runs the gates at
  the stream head after each merge. The owner approves only pull-request merges into the base branch (section 5; owner answers Q-M4 (a), Q-15 (a)).
- Owner questions raised at any depth travel upward as messages (section 4.3). Only the asking
  branch of the tree waits; its siblings continue.

### 4.2 How agents run in Claude Code (verified 2026-10-31)

- An agent can dispatch its own agents, which run in the background. Measured 2026-11-01: with `CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH` unset, subagents at levels 1-2 carry the dispatch tool and level 3 is a leaf; set to N, levels 1-N carry it. With `CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS` unset, a launch beyond 20 concurrent subagents is refused, not queued; the variable raises the limit (30 let 25 run at once). `init` writes both into the project's `.claude/settings.json` (main spec section 4).
- An agent stays alive while any of its children run. So a controller never returns to its
  parent while its children work. Questions and progress go up as messages (`SendMessage` to the
  parent, or to the main session), not as returns.
- The program controller refreshes itself (budget or lifetime) only at a sync, when every stream
  is at a checkpoint. It never hands off while children are mid-block, so nothing is orphaned. A program session acting as program controller does not refresh; it stays lean as section 4.4 says.

### 4.3 Questions and reports flow up

A blocked agent writes its question (options and cost, the recommended option, and the report it came from as `source`) into its handoff, then messages its
parent: sub-controller to stream controller, stream controller to program controller, program controller to the program session (directly to the program session when it acts as program controller). The session batches the questions for the owner. Answers go
down as decision records, and the waiting agent is told to continue. Completion and checkpoint
reports travel the same path. Each agent restarts as soon as every question it raised is answered (main spec section 7.1); the session asks them with their `source` and prints every batch with `decisions batch`.

### 4.4 Automatic continuation (replaces "stop for the owner's `/clear`")

At every agent level (a separate program_controller included), an agent that reaches a checkpoint, 80 % of its token or time
budget, or a usage-limit stop writes its handoff and returns `status: DONE` with `next:` (or
`BLOCKED: budget`). Its dispatcher immediately dispatches a fresh agent of the same role with a
continue prompt built from the handoff, ledger and status page. Nothing continues from inherited
memory. The owner never `/clear`s and re-prompts.

The program session cannot clear its own conversation (a Claude Code limit). It stays lean by
holding no detail: after any compaction it re-reads the overview (section 9) and the status
pages. The main spec's judgment rule "refusing continue without the owner's /clear after a
checkpoint" is removed; one block per agent context stays.

## 5. Lifecycle of a program

1. The owner, through the program session, writes the program's spec (including every
   cross-stream interface) and its program plan. The plan defines each stream: id, purpose,
   stream plan, owned paths, shared files and their rules, estimate, dependencies, merge order,
   and a `## Deferred` table. Approving it is an owner decision of class `program-create`.
   Everything in the program's spec and plan is planned in full before any code; no block that is only an outline may start implementation. The last planning step is the stream breakdown plan, `.strict-delivery/state/plans/<plan>/breakdown.yml` (kind `breakdown/1`, main spec section 8 and appendix A): streams with owned paths, tasks per stream, dependency edges from task to task, unblock conditions, and parallel groups within the concurrency limit, with the concurrency and depth limits it assumes, the tasks already done, and stream periods and path windows for ownership that moves during the program (owner answers Q-BD-7 (a), Q-BDr2-1 (a); the tasks already done: a controller ruling under Q-BD-7 (a)). `program create` refuses a plan with an outline-only block or without a valid breakdown (a breakdown is valid only within the effective concurrency and depth limits and with the same streams, owned paths (with their windows) and periods as `streams.yml`), and streams start as their unblock conditions hold (owner answer Q-PL-1 (a), 2026-11-02). The program plan states its estimate unit once (section 11), and the breakdown's schedule is estimated in it; `breakdown/1` itself holds no estimate. Its parallel groups count two agents per active task (implementer and reviewer) and per block end, and one per stream controller and per group sub-controller, against the concurrency limit. This framework's own plan, for example, estimates in hours by task class: S 1 h, M 2 h, L 3 h; a block or stream end with its pull request 1.5 h, a sub-block end without one 1 h; an update from the base branch 0.25 h.
2. The program controller (the program session itself by default, section 4; a separate program_controller only when the configured depth allows) creates the integration branch `<program>/integration` from main, with its own worktree, and the program folder on it (section 7), then dispatches one stream controller per ready stream. Each stream branch starts from main (owner answer Q-M4 (a)).
3. Streams run. Owner questions flow up and are asked as one batch; answers flow down as decision
   records. Cross-stream needs flow as requests (section 6). Progress, estimate use and blockers
   show on the status page. Interfaces are frozen once merged: a change to one is a plan change the owner rules on, and a later task changes an earlier task's code only when that change is ratified. A work branch is never rebased, since a rebase orphans reviewed shas; it takes the base branch by a merge, ledgered as `UPDATE <block> from=<branch>@<sha> head=<sha> tests=<passed>/<total> gates=<PASS|n/a>`, and a conflict, or a red result the merge brought, stops the stream `BLOCKED`. A block ends in this order: final review, top-tier verifier, the owner's approval, merge, post-merge gates, checkpoint.
4. Blocks accumulate on the stream branch. A finished stream opens its own pull request to the base branch, merged by merge commit on the owner's approval (main spec section 8; owner answers Q-M4 (a), Q-15 (a)): in `controller` mode the owner approves in chat naming the PR and its head sha and the controller runs `gh pr merge --merge --match-head-commit`; in `host` mode the owner merges on the host. The stream plan's ledger records the merge as a `MERGED` line, and the program controller copies that line into the program's merged record on the integration branch, checked by the merge checks before it is written and on every run; `gate_streams` reads the window events from that record (owner answer Q-F80W-6 (b)); the approval is not a decision record. A `MERGED` line counts only when it is tied to its plan (the merge's own diff, from its first parent, changes a path under `<paths.plan_state>/<plan>/`); `merged_by` names the merger, and in `controller` mode `approval` holds the owner's chat words verbatim; a merge commit not found locally fails with `update <base_branch> from the remote`. After every merge a sync runs (section 10). The integration branch holds only program records and combined testing; it never merges into the base branch, and the program's global records reach the base branch by one records pull request at close (owner answer Q-Pplan-12 (a)). Only the program controller commits on the integration branch, apart from the sync's merges.
5. When every stream is done, the program closes: an owner decision of class `program-close`.
   Lasting rulings are already in the decision register and rolled into playbooks, CLAUDE.md or
   `architecture.md` (section 8). Then the cleanup step removes the program folder, the program's
   specs and plans, plan workspaces, review reports and resolved findings from the tree (section 7).

## 6. Cross-stream requests

When stream A needs a change in a file stream B owns, A never edits it. A raises a request; the
program controller writes it as a record; B implements it in its own file.

- Path: `.strict-delivery/state/programs/<program>/requests/R-<YYYYMMDD>-<xxxx>.yml`.
- Fields: `id, from_stream, to_stream, files, interface (spec section cite), need (what and why),
  status (open | accepted | done | disputed | withdrawn), raised_at {sha, by}, resolution
  {commits, at, by}`, and `decision` (a decision id, required when `disputed` was ruled).
- Writer: only the program controller (the program session by default, section 4) creates or changes a request file, on the integration branch. A stream asks it to, and reads requests from `<program>/integration`.
- B may dispute a request (it conflicts with the spec or with B's work): the dispute becomes an
  owner question; the owner's ruling is a decision record the request cites.
- Transitions: `open -> accepted | disputed | withdrawn`; `accepted -> done | withdrawn`; `disputed -> accepted | withdrawn`, with the `request-dispute` decision; `done` and `withdrawn` are final; a request file is never deleted while the program is live (owner answer Q-Pplan-4 (a)).
- A's work that waits on a request shows the request id in its status row's `blockers`.
- A shared registration file (a command registry, a gate list) has one owner; every other stream adds its line by request. A line lands only in the same pull request as the module it names or after that module has reached the base branch, and a test that needs a line not yet landed is skipped with the reason `Rq-<n> not on this branch` (main spec section 8a). The receiver is the file's owning stream while it is live, else the residual owner; a `stream-ownership` decision may instead give a stream its own rows (owner answer Q-BD-8 (a)).
- `gate_streams` checks the schema, that `to_stream` owns every listed file, that `done` cites
  commits on B's branch that touch those files, and that no stream changed a file it does not own.

## 7. Folders and files

### 7.1 Global: tracked, permanent on main, shared by everyone

| Path | Responsibility | Written |
|---|---|---|
| `.strict-delivery/config.yml` | repository settings: profile, commands, paths, id format, budgets | init, upgrade; changes need a decision |
| `.strict-delivery/state/decisions/<id>.yml` | every decision, one file each; the only home of lasting rules | `decisions` tools |
| `.strict-delivery/state/findings/<id>.yml` | every finding: open findings, permanent until resolved, and resolved findings, which stay until the cleanup (section 8.3) | `findings` tools |
| `.strict-delivery/playbooks/` | project rules; each rule cites the decision that made it | agent-drafted, landed only with owner approval |
| `.strict-delivery/context.yml` | required reads per session kind and role | agent-drafted, owner-approved |
| `docs/strict-delivery/architecture.md` | living architecture overview; cites decision ids | agent-drafted, owner-approved |
| CLAUDE.md managed block, `.gitignore` managed block, CI workflow | framework wiring | init, upgrade |

### 7.2 Per effort: tracked while live, cleaned when done, cited afterwards as `<sha>:<path>`

| Path | Responsibility | Cleaned when |
|---|---|---|
| `docs/strict-delivery/specs/<spec>.md` | an effort's spec; marks where decisions were made by citing their ids | the spec's effort is done: a spec is in a plan's per-effort set only when no other live plan's handoff names it in `spec` |
| `docs/strict-delivery/plans/<plan>.md` | a plan (stream plan, plain plan, or program plan) | the plan is done |
| `.strict-delivery/state/programs/<program>/` | `status.md`, `streams.yml` (the local ownership map; an `owns` item may be a path window `{path, from, until}`, a stream may carry a `period` `{from, until}` (absent: the whole program) whose bounds a plain item and a missing window bound take (owner answers Q-F80a-1 (a), Q-F80r-1 (a)), and at most one `residual` stream owns every path no other stream owns in the same window, owner answers Q-BDr2-1 (a), Q-BD-4 (a)), `requests/`, `sync-log.md`, `merged.md` (the program controller's copies of its streams' `MERGED` lines, owner answer Q-F80W-6 (b)); lives on the integration branch, committed only by the program controller, never merged into the base branch. A program is live while a local branch `<program>/integration` exists whose tip holds `<paths.programs>/<program>/streams.yml`; liveness is never read from the current branch's tree | the program closes |
| `.strict-delivery/state/plans/<plan>/` | ledger, handoff, stream breakdown (`breakdown.yml`), mutation transcripts | the plan merges |
| `docs/strict-delivery/reviews/<plan>/` | review reports | the plan merges |
| `.strict-delivery/state/claims/<doc-slug>.yml` | claims about one document | with that document |
| resolved findings in `.strict-delivery/state/findings/` | closed and merged findings | with the effort that resolved them |

### 7.3 Ignored: never committed

| Path | Responsibility |
|---|---|
| `docs/strict-delivery/INDEX.md` | the program session's overview (section 9) |
| `.strict-delivery/state/decisions/in-force.md`, `index.yml`, `findings/index.yml` | generated lookups |
| `.strict-delivery/receipts/` | read receipts |
| agent scratch workspaces | per session |

Program folders are named `<YYYYMMDD>-<slug>` (no person's name); a name already on main or on
the branch is refused.

## 8. Records and ids

### 8.1 Ids

`<PREFIX>-<YYYYMMDD>-<xxxx>`: prefix `DEC`, `F`, `C`, `R`; the UTC creation date; four characters
from the lowercase base32 alphabet without `0`, `1`, `l`, `o`, drawn at random. Example
`DEC-20261031-k3f9`. No person's name or handle appears in any id.

- Deletion proof: a resolved finding names the plan that resolved it (`resolved_by: <plan>`).
  The cleanup may delete it only when the plan's ledger records its final pull-request merge (`MERGED ... final=yes`) and that merge commit is on the target branch's first-parent history with the recorded head as its second parent; the cleanup is its own pull request (owner answers Q-15 (a), Q-Pplan-9 (a)).
- Uniqueness: `gate_decisions` / `gate_register` fail any id present twice across the tree; a PR's
  ids are checked against the base branch too.
- No gap rule. Its job (spotting a deleted record) moves to the no-delete rule: a decision, open
  finding or claim file present on the base branch may not be deleted by a branch; the only
  deletions allowed are the cleanup step's (resolved findings and per-effort files, section 7.2).
- Within one program, only the program controller (the program session by default) mints ids, so two of its agents never race.
  A plain plan's controller mints its own.

### 8.2 Decisions

One file per decision, open or resolved; open versus resolved is a field, not a folder. The
fixed-range shards of the main spec §7.2 are removed. Resolved decisions are permanent. A lasting
decision lands in a playbook, CLAUDE.md or `architecture.md`; its `landed_in` cites that place
and the place cites the decision id. Specs may cite decision ids to mark where and why a decision
was made, but a spec is never a decision's `landed_in`, because specs are cleaned.

### 8.3 Findings

Open findings are global and permanent until resolved, even after the effort that raised them
closes; ownership then passes to an issue or roadmap item. Resolved findings stay in
`state/findings/` with a resolved status and are cleaned with the effort that resolved them.

## 9. The program session's overview

`docs/strict-delivery/INDEX.md`, generated on every session start and by
`python3 -m gates index`, never edited by hand:

- architecture: a link to `architecture.md` and its section headings;
- specs and plans grouped as **todo**, **in progress** (with the program, stream and block running
  it) and **done** (with the merge commit, read from git history after cleanup);
- each live program: its status page rows, open requests, pending owner questions, read at the tip of `<program>/integration`;
- open findings by severity; in-force decisions count with a link to `in-force.md`.

States are derived from git, plan ledgers and status pages; nothing in the index is typed.

## 10. Session kinds and syncs

- `program`: the owner's session. Start order: CLAUDE.md block, `in-force.md`, `INDEX.md`, the
  live programs' status pages, then `python3 -m gates context program`.
- `program-controller` (only when a separate program_controller runs), `stream-<id>-block`: agents; each reads its handoff and its context list.
  A stream's blocks run one after another in the stream worktree
  (`<worktrees>/<program>/<stream>/main`), on the stream branch `<program>/<stream>/main`.
- `sync`: run by the program controller after every merge into the base branch, and at the start of each working day: fetch and fast-forward the local base branch from the remote; run `gate_drift`; merge main into each stream branch that is behind it, as its own command, never a rebase (owner answer Q-Pplan-5 (a)); when main is ahead of `<program>/integration`, merge main into the integration branch, with no owner approval (if a merge conflicts, stop and ask the owner); merge the stream heads into the integration branch for combined testing and run the gates and the suite there (owner answer Q-M4 (a)); collect every pending owner question for one batch; update status rows; run `gate_drift` again and expect it to pass before the sync log line; update the sync log; push the integration branch.

## 11. Status page

`programs/<program>/status.md`: a table with header exactly `stream | block | branch | worktree |
next task | estimate | used | status | blockers | pending decisions | delivers`; `status` is one of `ready | running | blocked | checkpoint | merged | closed`; `merged` means the stream's pull request has merged into the base branch. `estimate` and `used` are non-negative decimal integers in the unit of the stream's `estimate` in `streams.yml`, one unit per program. The page lives on the integration
branch and only the program controller (the program session by default, section 4) edits it, from the streams' messages and handoffs. Stream
branches never carry a copy, so rows never conflict at a merge. Under the table the page carries the program facts a program session checks at resume that the stream handoffs do not: `Batch-cut:` (the commit of the last printed program batch), one `Agent:` line per live child of the program session (agent, stream, task, transcript, last record, background job ids with their state) and `Integration:` (the integration head at the last sync or commit).

## 12. Gates

- `gate_streams` (on every commit in a program; in CI per commit `base..HEAD`): `streams.yml`
  schema; owned paths disjoint within the program at every commit (two streams' entries on one path are never open together: a window is open from the time its `from` event holds until its `until` event holds, and a plain path, or a window's missing bound, takes the stream's period, the whole program when it has none), compared after case-folding and Unicode NFC through a frozen generated table (Unicode 13.0.0), so the comparison gives the same result on every Python (owner answers Q-CAT-4, 2026-11-02, and Q-X35 (a), 2026-11-07), the same comparison deciding which entry owns a changed path, and the breakdown's owned paths checked the same way before the program starts, where the breakdown's edges order the windows (section 5); `streams.yml` has no edges, so its own check refuses only the pairs that no order separates, those not chained with one of the two for the whole program (owner answers Q-F80-1 (a), Q-F80RR-1 (a)); every changed path owned by the committing stream (the plan file excepted: a stream may edit its own task sections of its plan, owner answer Q-B1f-2 (a), 2026-11-02, each changed hunk of it inside one of the committing stream's own task sections, else the change fails; never a spec), judged by the owner in the window at the commit (an event counts for a commit when the merge that makes it hold is an ancestor of that commit, owner answer Q-F80W-12 (a); a window event `merged:<stream>/<sub-block>` holds once the `MERGED` line of the pull request that carries that sub-block passes the merge checks (one stream pull request can carry several sub-blocks: those whose tasks were checkpointed at heads the pull request holds, owner answer Q-F80W-2); `merged:<stream>` once every sub-block of the stream has; a path no stream's open window covers is the residual stream's, and a path that open windows of two streams cover fails), or a shared file used under its rule; status rows one per stream and edited only as
  section 11 allows; request records as section 6. The committing stream is read from the branch
  (`<program>/<stream>/...`); commits on `<program>/integration` are program commits. The base for `base..HEAD` is the base branch, or the stream branch named as `stacked_on` in `streams.yml` until that stream's last merge, `merged:<stacked_on>`, holds; a stacked stream's pull request targets the base branch and opens only after that event, and a merge from its parent's branch is an update, not judged (owner answer Q-F80W-9 (a)); a merge of the integration branch into a stream branch fails (owner answer Q-M4 (a)). A changed path that no stream owns and that is not a shared file fails; the
  program controller assigns it (class `stream-ownership`). Shared files have one of two rules:
  `append-rows` (whole rows added at the end) or `own-row` (only the committing stream's row).
  Each stream owns its own plan workspace; the program controller owns the program folder and is
  the only writer of global records within the program: the program folder and the global record directories are owned by program commits on `<program>/integration` and by no stream. A merge whose second parent is reachable from the tip of the base branch (a sync's merge of main) is exempt from the ownership check, and a combined-testing merge of a stream head into the integration branch may change only that stream's paths.
- `gate_decisions`, `gate_register`: new id format; uniqueness against the base branch; no-delete
  rule; one file per record; `landed_in` never a spec.
- `gate_dispatch`: the two new roles, their dispatchers and tiers. It runs whenever a program is
  live, whatever the profile.
- `gate_checkpoint`: clean means the block's own worktree; other streams' worktrees are allowed;
  continuation handoff present.
- `gate_drift`: status-row branches and heads match git; pending decisions match the open records at the tip of `<program>/integration`, where a program's global records live until its records pull request;
  a stream branch behind the base branch, or an integration branch behind it, fails until a sync; a stream whose status row's `used` is past
  `drift.estimate_factor_pct` percent (default 150) of its `estimate` is reported to the owner by `drift report` at each sync; it is not a failing line.
- `gate_index`: INDEX.md and indexes regenerate without error and none is tracked.
- `gate_cleanup` (post-merge and at program close): the merged plan's or closed program's
  per-effort files are gone from the tree, and every lasting decision they produced has a
  `landed_in` outside them.

## 12a. Enforcement and optional extras

The framework enforces through what the plugin installs: Claude Code hooks (they run the gates
before a commit or push an agent makes, and check dispatches, edits and reads) and the skill's
rules. Two extras are offered by `init` as questions:

- local git hooks (pre-commit, pre-push), which gate commits made outside Claude: default **yes**;
- the GitHub Actions workflow: default **no**, since not every project can use it or may run it.

Both can be added or removed later with `upgrade`. This repository answers yes to both. A
project that answers no to both is gated only inside Claude sessions, and `doctor` says so.

## 13. Owner-only decision classes added

`program-create` (a program, its streams, owned paths, interfaces), `stream-ownership` (moving a
path between streams or assigning an unowned path), `stream-merge` (merge order, stacking on
another stream's unmerged branch), `request-dispute` (a disputed cross-stream request),
`program-close`.

## 14. Multiple humans

- Each human's effort is self-contained: its own branches, program folders, ownership map and
  owner answers. The framework never coordinates two humans' agents.
- What the framework guarantees at PR time: ids never collide (section 8.1); records are one file
  each, so registers merge cleanly; program folders never share a name; generated files are
  ignored; base-branch records are never deleted by a branch.
- What stays ordinary git: code conflicts, and two humans' decisions that disagree, which their
  reviewers resolve in the PR like any design disagreement.

## 15. Changes to the main spec (applied on approval)

- §1 success criteria: "enforcement does not depend on Claude" becomes "enforcement runs in
  Claude sessions by default; local git hooks (default on) and CI (default off) are init options
  that extend it to commits made outside Claude" (section 12a).
- §4: init asks the two extras' questions; `doctor` reports what is and is not installed.
- §5 layout, §7.1-7.3: replaced by sections 7 and 8 here (one file per record, new ids, no
  shards, no gap rule, no-delete rule, findings split, lasting decisions never land in specs).
- §6: `ids` config becomes the id format of section 8.1; `state.shard_size` removed; `streams`
  moves out of global config into each program's `streams.yml`.
- §8 rules: "one block per context ... stop for the owner's `/clear`" becomes automatic
  continuation (section 4.4); "Owner rules go into spec, CLAUDE.md or playbooks" becomes "into
  decisions, rolled into playbooks, CLAUDE.md or architecture.md".
- §9: `program/status.md` and `program/context.yml` move per section 7; `gate_checkpoint`,
  `gate_drift`, `gate_index` as section 12.
- §10: the two new roles and dispatch rules.
- §11: replaced by this document (linked).
- §12 profiles: programs are available in every profile; `gate_streams` runs wherever a program
  is live.
- §17 blocks: see section 16.

## 16. Effect on the current plan

- Task 1a.1 (YAML subset) is unaffected.
- Task 1a.2 (config) and Task 1a.3 (store) are re-specified: id format of section 8.1, one file
  per record, no shards, no gap rule, no-delete rule against a base ref.
- Tasks 1b.1-1c.2 (schemas, gates, tools) adopt the new ids and record layout; `decisions ask`
  and `findings new` mint ids.
- Programs and streams become their own delivery block, placed after block 2 so this repository
  can run its remaining blocks as a program. It carries the minimum it relies on from later
  blocks: the two new prompt blocks, the continuation rule, the upward-question path, a basic
  `gate_checkpoint`, and `gate_streams`. The full context, drift and index tooling still lands in
  block 5, and checkpoint and evidence in block 6. The plan update fixes the exact order.

## 17. Left to the builder

File and function names inside `gates/`; the exact base32 alphabet check; the overview's layout;
the sync's command sequence; how the continuation prompt is rendered from a handoff, within the
rules above.

## 18. Calls made by the controller (for the owner to check)

- Program folders named `<YYYYMMDD>-<slug>`.
- Decision open/resolved as a field, not folders.
- Branch names: `<program>/integration`, stream branch `<program>/<stream>/main`, group branch
  `<program>/<stream>/<group>`; no branch is named `<program>` or `<program>/<stream>` (git refuses
  a ref that is also a ref's directory). Stream ids `integration` and group ids `main` are
  refused; program, stream and group ids match `[a-z0-9][a-z0-9-]*`.
- program_controller and stream_controller at tier3.
- The programs block placed after block 2.
- Shared-file rules limited to `append-rows` and `own-row`; unowned changed paths fail.
- Each stream owns its plan workspace; the program controller owns the program folder.
- Resolved findings carry `resolved_by: <plan>` as the deletion proof.
- Stacking declared as `stacked_on` in `streams.yml`.
- Child worktree and branch naming in section 4.1.
- Decisions and findings carry `status` (decisions: `open | answered | withdrawn`; superseded is
  derived from a later answered decision's `supersedes`); resolved findings stay in
  `state/findings/` with a resolved status until the cleanup removes them.
- `gate_cleanup` is delivered in the programs block and covers both programs and plain plans.
