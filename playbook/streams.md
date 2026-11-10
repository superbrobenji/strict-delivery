# Base playbook: streams

Small work is a plain plan run by one controller. A large effort is a program, split by a program plan into streams that run in parallel.

## Programs and streams

Each stream owns a disjoint set of files: each stream owns a set of files disjoint from the other streams' at every commit, and path windows can move a file from one stream to another. A stream runs its own blocks in its own worktrees under one stream_controller. By default the owner's lean program session itself acts as program controller; a separate program_controller runs only when the configured depth allows. The program_controller and the stream_controller run at `tier3`.

- The program controller (the program session by default) creates the integration branch `<program>/integration` from the base branch, with its own worktree and the program folder on it, then dispatches one stream controller per ready stream. Each stream branch starts from the base branch.
- Branches: `<program>/integration`, stream branch `<program>/<stream>/main`, group branch `<program>/<stream>/<group>`. Program, stream and group ids match `[a-z0-9][a-z0-9-]*`; the stream id `integration` and the group id `main` are refused. Worktrees mirror the branches in nested folders: `<worktrees>/<program>/<stream>/main` for a stream, beside its groups at `<worktrees>/<program>/<stream>/<group>`, never above them.
- A stream is a tree of worktrees: the stream plan marks which task groups run in parallel, and groups running at the same time own disjoint file sets. Each level's file set is a subset of its parent's: program, then stream, then group, then task.
- The stream controller merges each group branch into the stream branch, one group at a time, after a clean review and green gates, with no owner approval, and re-runs the gates at the stream head after each merge.
- Owner questions raised at any depth travel up as messages, sub-controller to stream controller to program controller to the program session, which asks them as one batch; only the asking branch of the tree waits. Answers travel down as decision records.
- Interfaces are frozen once merged: a change to one is a plan change the owner rules on.
- `gate_streams` checks ownership, shared-file rules, status rows and request records on every commit in a program; a changed path that no stream owns and that is not a shared file fails until the program controller assigns it (class `stream-ownership`). A shared file is `append-rows` (whole rows added at the end) or `own-row` (only the committing stream's row). A stream may edit only its own task sections of its plan, and never a spec.
- When every stream is done the program closes, an owner decision of class `program-close`, and the cleanup step removes the program's per-effort files from the tree in a pull request of its own.

## Cross-stream requests

A stream never edits another stream's file. When stream A needs a change in a file stream B owns, A raises a request; the program controller writes it as a record under the program folder on the integration branch, and B implements it in its own file. Only the program controller creates or changes a request file; a stream reads requests from `<program>/integration`.

- A request moves `open` to `accepted`, `disputed` or `withdrawn`; `accepted` to `done` or `withdrawn`; `disputed` to `accepted` or `withdrawn` with a `request-dispute` decision. `done` and `withdrawn` are final, and a request file is never deleted while the program is live.
- B may dispute a request that conflicts with the spec or with B's work; the dispute becomes an owner question, and the owner's ruling is a decision record the request cites.
- A's work that waits on a request shows the request id in its status row's `blockers`.
- A shared registration file has one owner; every other stream adds its line by request. A line lands only in the same pull request as the module it names, or after that module has reached the base branch.

Dependency skips. A test that needs another stream's unmerged work is written now and skipped with a reason naming its dependency (`Rq-<n> not on this branch`, or the block it waits for), and each standing skip is recorded in the ledger while it stands. At the update before the final review the controller removes each skip whose dependency is on the base branch, so the final review covers the unskipped tree. A pull request carries only a skip whose dependency lands after it by plan order, and the test runs unskipped from the pull request that brings the dependency.

## Syncs

A `sync` is run by the program controller after every merge into the base branch, and at the start of each working day:

1. Fetch and fast-forward the local base branch from the remote; run `gate_drift`.
2. Merge the base branch into each stream branch that is behind it, as its own command, never a rebase.
3. When the base branch is ahead of the integration branch, merge it into the integration branch, with no owner approval. If any merge conflicts, stop and ask the owner.
4. Merge the stream heads into the integration branch for combined testing, and run the gates and the suite there.
5. Collect every pending owner question for one batch, and update the status rows.
6. Run `gate_drift` again and expect it to pass, update the sync log, and push the integration branch.

A sync merges, never rebases: a rebase orphans reviewed commits. The integration branch holds only program records and combined testing; it never merges into the base branch, and a merge of the integration branch into a stream branch fails. Only the program controller commits on the integration branch, apart from the sync's merges. A separate program controller refreshes itself only at a sync, when every stream is at a checkpoint.

## Status page

Each program keeps a status page, `programs/<program>/status.md`, on the integration branch; only the program controller edits it, from the streams' messages and handoffs, and stream branches never carry a copy. It is a table with the header `stream | block | branch | worktree | next task | estimate | used | status | blockers | pending decisions | delivers`. `status` is one of `ready`, `running`, `blocked`, `checkpoint`, `merged` or `closed`; `merged` means the stream's pull request has merged into the base branch. `estimate` and `used` are non-negative whole numbers in the program's one estimate unit. Under the table the page carries the program facts a program session checks at resume: `Batch-cut:` (the commit of the last printed program batch), one `Agent:` line per live child of the program session (agent, stream, task, transcript, last record, background job ids with their state) and `Integration:` (the integration head at the last sync or commit). `gate_drift` checks the status rows against git and the pending decisions against the open records; a stream whose `used` is past `drift.estimate_factor_pct` percent of its `estimate` is reported to the owner at each sync.

## Pull-request flow

The base branch is protected: nothing is pushed or merged to the base branch directly. The Bash hook refuses agents' pushes and merges to the base branch. Every change reaches it by a pull request on all-green, merged by merge commit on the owner's approval.

- A finished stream opens one pull request to the base branch from its stream branch.
- In `controller` mode the owner approves in chat, naming the pull request and its head sha, and the controller runs `gh pr merge --merge --match-head-commit` with that head sha as its argument. In `host` mode the owner merges on the host.
- The stream plan's ledger records the merge as a `MERGED` line (who merged, when, the pull request, its head sha, the merge commit, the approval; in `controller` mode the owner's chat words verbatim), and the program controller copies that line into the program's merged record on the integration branch. The approval is not a decision record.
- Work branches are pushed at every checkpoint, and the program controller pushes `<program>/integration` after every commit it makes there.
- After every merge a sync runs.
