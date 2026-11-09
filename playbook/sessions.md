# Base playbook: sessions

How a session starts, works in blocks, checkpoints, hands off and continues, and how it plans, commits and dispatches.

## Session kinds

- `plan`: a plain plan's controller session. In a plain plan the main session is the plan's controller and dispatches every role.
- `program`: the owner's session in a program. It talks to the owner, shows the overview, relays owner questions in one batch, and by default acts as the program controller itself.
- `program-controller`: an agent, only when a separate program_controller runs; it reads its handoff and its context list.
- `stream-<id>-block`: an agent running one stream's blocks, one after another, in the stream worktree on the stream branch; its context list is looked up as `stream-block`.
- `sync`: run by the program controller after every merge into the base branch and at the start of each working day (`playbook/streams.md`, "Syncs").

`.strict-delivery/context.yml` lists the required reads per session kind and role, each entry `{path, lines, why}`; SessionStart prints the list for the session kind, and `python3 -m gates context <kind>` prints it on demand.

## Start order

Every session reads the default session load first: `in-force.md` and the open decisions, then its kind's context list. A `program` session reads, in order: the CLAUDE.md block, `in-force.md`, `INDEX.md`, the live programs' status pages, then `python3 -m gates context program`.

A session or agent that starts with no memory of the work (a compaction, a new session, a continuation) resumes in this order:

1. Invoke every skill in the handoff's `skills`, in order.
2. Read the default session load and start order above, then the handoff's `required_reads` with their line ranges, and the ledger from line `ledger_from`.
3. Dispatch one read-only `investigator` with the fixed questions below (Q1-Q9; a program session G1-G4). It changes nothing and reports to the session.
4. Write the prose ledger line `Resume check: head=<sha>; differences: <none or Q-ids>; report <path>.` (no new ledger keyword).
5. Report where things stand and what comes next, with the findings, to the owner (an agent: to its dispatcher, as a message), before any edit or dispatch other than the investigator's.
6. With no difference, take over at once: start the next streams, or resume in-progress ones as they were. With any difference, stop and wait for the owner (an agent: status NEEDS_DECISION naming each difference).

This is skill text; no hook holds the session. A program session keeps no handoff: after any compaction it re-reads the overview and the status pages, and its investigator checks the status page's program facts. A continued worker never dispatches, so its dispatcher runs the check before the continuation dispatch and puts the report in the continue brief.

The investigator answers each question with one line, `Q<n> <fact>: match` or `Q<n> <fact>: differs: <recorded value> vs <real value> (<command>)`; `G<n>` the same.

For a handoff:

- Q1 each `worktrees` entry: `git -C <path> merge-base --is-ancestor <head> HEAD` exits 0 and `git -C <path> symbolic-ref --quiet --short HEAD` equals `branch` (no output for `null`).
- Q2 each entry's `git -C <path> status --porcelain --untracked-files=all`, without the handoff's and the ledger's lines, equals `porcelain`.
- Q3 the handoff's `head` is an ancestor of `HEAD` of its worktree, and its `branch` is that worktree's branch.
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

## Blocks and checkpoints

One block per agent context, at most `block.max_tasks` tasks; the worktree is clean at every checkpoint. No limit has a default. The triggers hold for every controller, the main session included: a block or task checkpoint, 80 % of the token or time budget, or a usage-limit stop. At a checkpoint the controller appends the ledger line `CHECKPOINT <block> <task> head=<short sha> tests=<passed>/<total> gates=<PASS|n/a> next=<task id>`, rewrites the handoff beside the ledger, and commits both after the commit gate. `gate_checkpoint` counts a block's tasks both as its plan's task headings and as the distinct task tokens of the ledger's `CHECKPOINT` lines, and checks that the block's own worktree is clean (other streams' worktrees may be dirty), that the last `CHECKPOINT` line records the suite and gates green, and that the handoff matches its schema. Work branches are pushed at every checkpoint. A work branch is never rebased: it takes the base branch by a merge, ledgered as an `UPDATE` line, and a conflict, or a red result the merge brought, stops the stream `BLOCKED`. A block ends in this order: final review, top-tier verifier, the owner's approval, merge, post-merge gates, checkpoint.

## Handoffs and continuation

The handoff (`handoff/1`) carries the fields `gate_checkpoint` checks: plan, spec, branch, head, base, ledger, resume line, block, next task, findings in flight, open decisions, rulings, grant and live subagents. Its resume fields are: `live_subagents` as entries (agent, task, worktree, transcript, last record, background job ids with their state); `worktrees` (path, branch, head, and the `git status --porcelain --untracked-files=all` output without the handoff's and the ledger's own lines); `required_reads` (path, optional line range, why); `skills`, in invocation order; `ledger_from`, the ledger line after the `CHECKPOINT` line just written; and `batch_cut`, the commit of the last printed owner batch, or none. Each question in it carries its recommended option and `source`. The handoff never tells the next session to read less than the default load plus `required_reads`.

Continuation is automatic, at every agent level: an agent that reaches a checkpoint, 80 % of its token or time budget, or a usage-limit stop writes its handoff and returns `status: DONE` with `next:` (or `BLOCKED: budget`). Its dispatcher at once dispatches a fresh agent of the same role with a continue prompt built from the handoff, the ledger and the status page. Nothing continues from inherited memory, and the owner never clears the conversation and re-prompts. The program session cannot clear its own conversation; it stays lean by holding no detail.

A statement that a handoff is complete carries three outputs, pasted: `git status --porcelain --untracked-files=all`, the handoff field check (`gate_checkpoint`), and the background-job check. "Safe to clear" is never said: nothing is cleared at any level.

Background jobs. Before ledgering an agent's result, the controller lists the agent's background job ids from its transcript; each has a completion record, or is stopped with TaskStop and the stop is ledgered. A notice that an agent is waiting on its own background work leaves its task open. The session reaps its own jobs before it reports.

## Agent tree

By default the session acts as program controller: it keeps the status page, mints ids, writes requests, runs syncs and asks one question batch. The levels below it: stream controller at level 1, sub-controller at level 2, workers at level 3. Deeper levels, a separate program_controller agent and nested sub-controllers, run only within the configured depth. Only the program session dispatches a program_controller; the program session or a program_controller dispatches a stream_controller; stream controllers and sub-controllers dispatch sub-controllers and workers. A controller never returns while its children run, and workers never dispatch: a worker dispatches no agent, workflow or other agent task, and the dispatch check refuses any dispatch from a worker role.

## Plan format

Fail closed and promise narrowly: a contract states only what a narrow, fail-closed check can show, and never claims to match or emulate another tool exactly. Narrow the contract to a fail-closed whitelist and bound it with a seeded generated-input test. A reference implementation's fixtures may test agreement on the inputs a gate supports; agreement beyond them is a non-goal, and a known difference is a stated limit.

Every task whose interface takes an argument or reads a file carries an input-domain table in its brief, copied from the plan's input-domain dimensions. Its columns are `# | dimension | values | expected verdict | test`, one row per parameter or filesystem call and dimension. The implementer fills `test`, and a row with no test is a finding. Each verdict is marked as settled by the spec or plan, as an owner question, or as a controller ruling; a controller row goes to the reviewer as a ruling with one line of why. The table's sections are: Oracle, binding owner rulings, existing tests whose pinned behaviour changes, measurements, mismatches, and the owner batch with each option's cost. A row a fix names must exist, and a test cell names an existing test.

A block's plan section has these parts: owner answers applied (binding); interfaces consumed; requests to other streams; a file-ownership table; controller rulings, each `what -- why -- cost if wrong -- spec cite`; cross-block notes; spec edits needed, with ids and their Now and Becomes text quoted verbatim; divergences, with both quotes; and the owner batch, asked upfront.

## Agent rules

Workers dispatch no agents, workflows or other agent tasks. They may start background shell jobs, which they reap before reporting: a poll loop has a bounded timeout and never matches its own command line; a job no longer needed is stopped with TaskStop, never by pattern-killing processes; the report lists each background job id as `finished` or `stopped`. After a permission denial an agent stops with status DENIED, quoting the denial; the controller does not re-run the denied action, and a resumed agent runs only its own code, never downloaded or external code. Every agent works in its own `mktemp -d` scratch path and never runs `git stash` in a shared checkout; in the commands it runs it uses no heredoc, no `rm`, `rmtree` or `os.remove`, and no command substitution except around `mktemp`. A worker discloses a slip in its report, and the main session discloses its own in the ledger.

## Commits

A worker commits only with no unstaged or untracked path and no assume-unchanged or skip-worktree flag on a tracked file. A red line or a missing interpreter blocks the commit. It stages its own files by name. A fix round adds a new commit and never amends. A doc change and the test that pins it are one commit. Every commit carries the harness's `Co-Authored-By:` line for the model that wrote it. The two commit hooks refuse a commit while a tracked file has unstaged changes.

## Planning

Every block of a spec and its plan is planned in full before any code is written: tasks, files, interfaces, input-domain dimensions and tests, and every test step of a plan carries its assertions as code. No block whose plan is only an outline may start implementation. The last planning step is the stream breakdown plan, `<paths.plan_state>/<plan>/breakdown.yml` (kind `breakdown/1`): the streams with their owned paths, the tasks of each stream, the dependency edges from task to task, each stream's unblock condition, the parallel groups (each within the concurrency limit), the concurrency and depth limits it assumes, the tasks already done, and, for ownership that moves during a program, stream periods and path windows. Streams run as they unblock. In a program, `program create` refuses a plan with an outline-only block or without a valid breakdown.

Each kind of change has its superpowers skill. A new rule, feature or format with no settled design goes through superpowers:brainstorming to an owner-approved design, then a spec edit. A plan change goes through superpowers:writing-plans against the spec. Execution goes through superpowers:subagent-driven-development or superpowers:executing-plans under the strict prompt blocks. A controller that has not invoked the skill for the change in its current context dispatches no writer for it.
