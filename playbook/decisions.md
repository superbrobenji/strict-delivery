# Base playbook: decisions

The decision log is the only home of the owner's rulings. A decision is an owner question with at least two options and their cost, one of them recommended (none in class `model-policy`); the owner is the human driving the effort. Records live one file per id under `paths.decisions` and are written by `python3 -m gates decisions ask|decide|find|withdraw|batch`.

## Asking

A point the spec, the plan or an owner answer already states is applied as written and not asked. A plan-vs-spec or task-vs-task conflict that the spec settles is a controller ruling, never a question: inside an approved plan only, at most `rulings.max_per_block` per block, ledgered as `Ruling: what -- why -- cost if wrong -- spec cite`; a plan-vs-spec conflict is corrected to the spec and the correction is ledgered. Any other open point, and every point in an owner-only class, is an owner question, and the path that needs it halts until it is answered.

Search before asking. Before a question is asked, search for its answer: `decisions find <terms> [--path P] [--topic T]` returns the in-force decisions and follows `supersedes` chains to the current ruling. `decisions ask` runs that search on the new question's topics, paths and keywords and prints candidates; the record carries `checked_against`. Until `decisions ask` prints candidates, the search runs by hand: the terms are the question's topics, its paths and its words of at least 4 characters; the sources are the decision records, the ledger, the plan's owner answers and its "Owner answers applied" lines, the stream breakdown and its edits, and both specs; and `git log -S` runs on every line the question quotes. A question found answered is cited, not asked. Whether a candidate is a true duplicate is reviewer judgment.

The printed question. A question shows, in this order: id, class, the question, the recommended option with its cost, every alternative with its cost (no cap on alternatives), effect, topics and `applies_to`. The tool-only fields (`schema`, `status`, `asked_at`, `asked_by`, `checked_against`, `supersedes`, `source`) are not printed. A question has at least two options: one recommended option plus at least one alternative. `decisions ask` requires the recommended option for every class except `model-policy`, whose questions carry none. Owner question ids are `Q-<scope>-<n>`, and `source` names the report or handoff the question came from.

The batch. Questions are asked as one batch at the next stop, never one at a time. A batch is kept small and recommends the fail-closed option where one exists. `decisions batch --since` with a cut-off commit (`python3 -m gates decisions batch --since <sha>`) prints the open records of the working tree: the records whose files did not exist at the cut-off commit under `New`, every other open record under `Also open`, each given whole with the same fields; within each section there is one header per `source`. A cut-off that is not an ancestor of `HEAD`, or none, makes every open record new. An answered question drops out. The session commits the new records, prints the batch and records that commit as the next cut-off, `batch_cut`, in its handoff (for a program, on the status page). Printing writes nothing, so the batch never depends on the session's memory.

Restarts. Each agent restarts as soon as every question with its `source` has an answered record, while others in the batch may still be open; only the asking branch of the tree waits. A worker or reviewer that stopped with `NEEDS_DECISION` and returned is replaced by its controller with a fresh agent of the same role whose brief carries "Owner answers (date), binding", printed by `decisions batch --answered --source <path>` from that source's answered records. A controller still alive and waiting is told to continue. A controller that handed off is rebuilt by `continue`, which refuses while any of its questions is unanswered. Only the session writes decision records; workers never do, and never change anything for a question. Fix and re-review rounds run until a clean pass.

## Answering

Answers and withdrawals come only from the human who owns the effort. The PreToolUse Bash hook refuses `decisions decide` and `decisions withdraw` from any subagent: the human runs them (the `!` prefix), or the main session (the program session, or the controller's session in a plain plan) records the owner's exact words. `decisions decide` writes the answer, sets `status: answered` and regenerates the indexes in one step; it records the git identity (`git config user.email`) as `answered_at.by` and refuses when that identity is unset. `decisions withdraw` records `withdrawn{at, by, reason}` instead of the answer fields. Agents never edit a record by hand: the PreToolUse Edit/Write hook refuses any agent Edit or Write under `paths.decisions`. A hand edit by the human is valid when the schema holds; pull-request review is where a human checks who answered. Once a question is answered the plan states only the chosen option, and task text is edited before dispatch when the answer differs from the recommendation. A pull-request merge approval is not a decision record: in `controller` mode the owner approves in chat naming the pull request and its head sha, in `host` mode the owner's merge on the host is the approval, and the plan's ledger records each merge as a `MERGED` line. Nothing may reference an unanswered decision id (`gate_decisions`).

## Lasting decisions

Decisions are the only home of lasting rules. A decision with `effect: lasting` needs `landed_in`: the decision is rolled into a playbook under `paths.playbooks`, `CLAUDE.md` or `paths.architecture`, `landed_in` cites that place, and the place cites the decision id. A decision's `landed_in` is never a spec, because specs are cleaned with their effort; a spec may cite a decision id to mark where and why it was made. A resolved decision (answered, withdrawn or superseded) is permanent and immutable: a change is a new decision that names the old one in `supersedes`, and resolved rulings stay binding. `in-force.md` is generated with one row per lasting decision still in effect (id, topic, rule summary, `landed_in`); the default session load is `in-force.md` and the open decisions, and everything else is found with `decisions find` or surfaced by path. Agent memory only points to decisions; it never holds the rule itself.

## Owner-only classes

A question in one of these classes is always the owner's, never a controller ruling: the agent that needs it writes the question with its options and their cost and stops. The default classes come from config `decision_classes.owner_only`; a project may add its own classes to that list, and the project's list is added to the defaults, so a project cannot drop a default class.

| slug | the owner decides |
|---|---|
| triage | audit triage |
| spec-direction | spec-vs-code direction |
| scope | plan scope |
| merge-grant | merge grants |
| model-policy | model and cost policy |
| issue-close | closing an issue |
| finding-class | narrowing or widening a finding's class |
| rule-override | rule overrides |
| program-create | a program, its streams, owned paths and interfaces |
| stream-ownership | moving a path between streams or assigning an unowned path |
| stream-merge | merge order, and stacking on another stream's unmerged branch |
| request-dispute | a disputed cross-stream request |
| program-close | closing a program |
