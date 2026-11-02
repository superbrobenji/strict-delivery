# strict-delivery framework: design

Date: 2026-10-31. Status: approved by the owner 2026-10-31. Owner: superbrobenji.

## 1. Purpose

A public, language- and project-agnostic Claude Code framework that brings the
"strict delivery" way of working (proven in the lap-timer repository) to any repository:
every change tracked, every claim verified, owner decisions logged and binding, agents
dispatched by role under a contract, and all of it enforced by gates that run in Claude
sessions and, where the project installs them, in git hooks and in CI. Large efforts run as
programs of parallel streams, specified in the programs and streams design (section 11).

Success criteria:

- A developer installs the plugin, runs `/strict-delivery:init` in any repository (any
  language, or none), answers a few questions, and has a working, gated setup with
  `doctor` and `run_all` green.
- The rigor is selectable (light / standard / strict) without forking the framework.
- Enforcement runs in Claude sessions by default; local git hooks (default on) and CI
  (default off) are init options that extend it to commits made outside Claude (section 4).
- Large, mature projects stay cheap to work in: no state file grows without bound and no
  session loads history it does not need.
- lap-timer can later migrate onto it and delete its private copy of the gates.

Non-goals for v0.1: Windows support; non-Claude agent harnesses (Codex, Cursor); CI
systems other than GitHub Actions; language-specific lint rule packs (for example
Power of 10 for C), which arrive later as optional adapters.

## 2. Inputs and what is not carried over

Source: lap-timer `tools/gates/` (main at `fe3f146`, strict-delivery b1-b4), the
`strict-delivery` skill and its eight role prompt blocks, the strict-delivery spec and
umbrella plan, the playbooks and the owner feedback rules.

Carried over, rewritten generically: gate logic for register, claims, decisions,
dispatch and run_all; the Claude Code hooks; the git hook shims and installer; the role
prompt blocks; the method rules (as base-playbook rules, section 8).

Not carried over:

- No decision, finding or claim rows. Every target repository, and this framework repository
  itself, starts with empty registers. The developer owns their own log.
- No lap-timer history: decision numbers, `LEGACY_PACKAGES`, the D34 "Order" clause,
  `comment_patterns` naming lap-timer plans, lap-timer's owner identity.
- No project-specific rules: Power of 10, Unity `test_*.c` detection, ESP-IDF, flashing,
  OTA windows, firmware build lists. These become lap-timer's local playbook and, where
  generic, future adapters.
- No lap-timer state as test fixtures (the repository is public). Tests use synthetic
  fixtures.

## 3. Packaging and repository layout

The repository is the plugin and its own marketplace.

```
strict-delivery/
  .claude-plugin/plugin.json          name strict-delivery; depends on superpowers
  .claude-plugin/marketplace.json     self-hosted marketplace entry
  skills/strict-delivery/SKILL.md     method, precedence, decision classes, pipeline
  skills/strict-delivery/prompts/     one strict block per role prompt file
  playbook/                           base playbook (section 8), plugin-owned
  commands/init.md doctor.md upgrade.md
  hooks/hooks.json                    SessionStart, UserPromptSubmit, PreToolUse(Agent, Bash, Edit/Write), PostToolUse(Read), SubagentStop
  gates/                              Python package, standard library only
    lib/                              result, yamlsub, git, registers, config, schema migrations
    schemas/<kind>.yml                one schema per file kind (appendix A)
    gate_schema.py gate_register.py gate_claims.py gate_decisions.py gate_dispatch.py
    gate_streams.py gate_context.py gate_cites.py gate_drift.py gate_index.py gate_checkpoint.py
    gate_cleanup.py gate_evidence.py
    run_all.py
    __main__.py                       `python3 -m gates <command>`
  templates/                          rendered into the target repository by init/upgrade
  profiles/light.yml standard.yml strict.yml
  tests/
  scripts/release.py                  release script (framework repository only; not used by targets)
  docs/strict-delivery/specs/ docs/strict-delivery/plans/
```

Runtime: Python 3.9 or newer, standard library only. No PyYAML; state and config use the
strict YAML subset (section 6). Claude Code hook logic is Python (`python3 -m gates hook
<event>`); each `hooks.json` entry, like the git hook shims, is one POSIX sh line that changes to the plugin directory and execs `python3 -m gates`. Windows is not supported in v0.1, but no hook
logic lives in shell, which keeps a later port cheap.

Superpowers is a declared dependency. Precedence, highest first: the target repository's
`CLAUDE.md` (managed block plus project text), the strict-delivery skill and prompt blocks,
the project playbook, the base playbook, superpowers unmodified. The skill and the CLAUDE.md
managed block name the document locations (section 5), which override superpowers' default
`docs/superpowers/` save paths. Where superpowers
says otherwise (for example "do not re-run the suite" for reviewers), the higher layer wins.

## 4. Invocation and lifecycle

Install once per machine:

```
/plugin marketplace add superbrobenji/strict-delivery
/plugin install strict-delivery@strict-delivery
```

`/strict-delivery:init`, once per repository, interactive and idempotent:

1. Read the commands the project already has (package.json scripts, Makefile targets, Maven
   or Gradle wrappers, Cargo, go, pyproject tool entries, ...) and offer them for `test`,
   `test_one`, `lint` and `build`. Detection invents nothing and only proposes; the owner
   confirms, edits or leaves out each command.
2. Ask for profile and model map (default from the profile's `defaults`, section 12). Ask the two extras' questions:
   local git hooks (pre-commit, pre-push), default **yes**; the GitHub Actions workflow,
   default **no**, since not every project can use it or may run it. Ask `merge.mode`: `host` (the owner merges pull requests on the host) or `controller` (the owner approves in chat and the controller runs `gh pr merge`) (owner answer Q-M1). Offer to configure host branch protection on the base branch (pull request required for everyone including administrators, merge-commit method only) (owner directive 2026-11-01).
3. Write `.strict-delivery/config.yml`, empty state directories, the CLAUDE.md managed block
   (between `<!-- strict-delivery:begin schema=claude-block/1 version=<framework version> -->`
   and `<!-- strict-delivery:end -->`; the rest of CLAUDE.md is untouched), and the extras
   answered yes: the git hook shims, the CI workflow. It also writes the subagent depth and concurrency limits the owner chooses into the project's `.claude/settings.json` `env` block, as `CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH` and `CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS` (section 10; measured limits in the programs and streams design, section 4.2).
   - Init and upgrade never overwrite. They refuse to write any path that already exists
     and is not framework-managed, except that `upgrade` rewrites `.strict-delivery/config.yml` and state records only to move the version pin and apply registered schema migrations. Framework-managed means a managed block between the
     framework's begin and end markers in CLAUDE.md or `.gitignore` (inserting the block into an
     existing file for the first time is allowed; text outside the markers is never changed), or
     a file carrying the framework's generated-file header. They list every conflict and
     write nothing until the owner resolves it.
   - Existing superpowers documents (`docs/superpowers/specs/` and `docs/superpowers/plans/`)
     are proposed for migration into `docs/strict-delivery/specs/` and
     `docs/strict-delivery/plans/`. Each move uses `git mv`, so history follows the file.
     Every tracked reference to a moved path is rewritten.
   - A migration whose target already exists is a conflict, as above. The migration is part
     of the diff in step 5 and happens only on the owner's word.
4. Run `doctor`.
5. Show the diff. Nothing is committed without the owner's word.

`/strict-delivery:doctor` prints `PASS id` / `FAIL id: reason` lines: Python version, which
extras are installed and which are not, git hooks (when installed) not foreign or bypassed,
config valid, CLAUDE.md block matches the plugin version, CI pin (when installed) matches the
plugin version, every register parses, the indexes regenerate without error, no generated file
is tracked, and the `.gitignore` managed block matches the plugin version, and whether the base branch is protected on the host (pull request required for everyone including administrators, merge-commit method only); with a GitHub remote it fails when the host cannot be read, and with no GitHub remote it is not checked. A project with
neither extra installed is gated only inside Claude sessions, and `doctor` says so.

`/strict-delivery:upgrade` moves the version pin, re-renders managed blocks and templates,
runs state schema migrations, optionally changes profile (`--profile`), adds or removes either
extra, and shows the diff plus every check that newly fails.

Claude Code hooks (plugin `hooks/hooks.json`; active wherever the plugin is enabled, silent
no-ops in a repository without `.strict-delivery/config.yml`):

- SessionStart: status, open handoffs, active rule overrides, the context load list
  (section 9), and the instruction to invoke the strict-delivery skill.
- UserPromptSubmit: a one-line reminder (standard and strict).
- PreToolUse Agent: dispatch grammar, model tier, claims and decisions referenced
  (standard and strict, and every profile while a program is live). The hook supplies the dispatcher's role and depth and the live subagent counts from its session state, and refuses the dispatch when it cannot determine them.
- PreToolUse Bash (all profiles): the hook-bypass block (`--no-verify` and its abbreviations, `-n` on `git commit`, `core.hooksPath` in any case and `git -c`/`--config-env`, `GIT_CONFIG_*`, moves of `HOME` or `XDG_CONFIG_HOME`); gated commit/push; refusal of `decisions decide` and `decisions withdraw` from any subagent; the main session may run them to record the owner's exact words (section 7.1); refusal of a commit, push or merge aimed at another repository or index (`--git-dir`, `--work-tree`, `GIT_DIR`, `GIT_WORK_TREE`, `GIT_INDEX_FILE`); refusal of any git write (commit, push, merge, pull, rebase, cherry-pick, revert, am, reset, update-ref, tag, stash, worktree, and branch, checkout or switch with a create, move, copy, delete or force option) whose target worktree (named by `git -C <dir>` or `cd <dir> &&`, else the caller's `cwd`) is not one the caller may write in: for a subagent, the one worktree its dispatch named on a `worktree:` line of `## Task`, checked at dispatch against the dispatcher's own (with none: the main checkout when no program is live; no worktree at all for a controller in a live program, whose worker dispatches must name one); for the main session, its own checkout and, while a program is live, the worktrees on that program's status page and the one holding its integration branch. The hook checks only that the named worktree is the one the dispatch named, not that the dispatcher chose rightly; a subagent may commit, push or move only the branch its bound worktree had checked out when the dispatch was recorded: any git write while that worktree is on another branch is refused, as are a switch or checkout to another branch or commit, creating a branch (`git branch <new>`, `checkout -b/-B`, `switch -c/-C`), `branch -f/-m/-M/-c/-C/-d/-D` of another branch, a push to any other branch or a tag, `update-ref`, `tag`, a fetch into a local branch and `git worktree add`, except that a stream controller recorded on `<program>/<stream>/main` may create a group branch only as `git worktree add -b <program>/<stream>/<group> <path>`; and, since the base branch is protected (section 8): an agent's push to the base branch in any refspec form (`--all`, `--mirror`, `--prune` and wildcard refspecs included); while the base branch is checked out, an agent's `git commit`, `merge`, `pull`, `rebase`, `cherry-pick`, `revert`, `am` or `reset`, except a fast-forward of it to its own remote-tracking branch; from any branch, an update of the base branch by `git branch -f/-m/-M/-c/-C/-d/-D`, `checkout -B`, `switch -C`, `update-ref` or a `fetch` refspec; `gh pr merge` unless `merge.mode` is `controller` and the command carries `--merge` and `--match-head-commit <sha>` and no other merge option; every `gh api` call to the REST pull-request merge endpoint (any method or spelling) and every `gh api` call that is not a read (a method other than GET, a field or input, or a GraphQL mutation); `gh repo sync` and `gh alias set`/`import`. The checks are text checks that fail closed; a script file whose command text names none of these words is not recognised.
- PreToolUse Edit/Write: surfaces in-force decisions whose `applies_to` matches the path,
  once per session per decision (section 7.4); refuses any agent Edit or Write of a path under `paths.decisions`, since only the `decisions` tool, and `upgrade`'s registered migrations, write decision records (owner answer Q-16 (a)); records nothing else and blocks nothing else.
- PostToolUse Read: read receipts for the context contract (section 9).
- SubagentStop: ends the live record of a finished subagent, so the PreToolUse Agent hook's counts stay exact; refuses nothing.

Enforcement: the framework enforces through what the plugin installs, the Claude Code hooks
(they run the gates before a commit or push an agent makes, or, when the git hooks are installed and current, leave the gates to them and make sure they run; and check dispatches, edits and
reads) and the skill's rules. The two extras extend the same gates to commits made outside
Claude: the git pre-commit and pre-push hooks, and the CI workflow, which checks out the framework repository named in the plugin manifest's `repository` at the pinned release tag (before the first release, at the installed framework's commit sha), and runs `python3 -m gates run_all`; on pull requests it also runs, on a checkout of the PR's head sha, `check streams --branch <head>` and, for a `cleanup/<plan>` head, `check cleanup`.

Versioning: semver tags. The plugin version, the CLAUDE.md block version, the CI pin (when the
CI workflow is installed) and `framework_version` in config must agree; `doctor` and `run_all`
fail when they do not.

## 5. Target repository layout

```
.strict-delivery/
  config.yml                          repository settings: profile, commands, paths, id
                                      format, budgets
  context.yml                         required reads per session kind and role
  state/decisions/<id>.yml            every decision, one file each, open or resolved
  state/decisions/index.yml           generated, git-ignored
  state/decisions/in-force.md         generated, git-ignored
  state/findings/<id>.yml             every finding, one file each; a resolved finding stays
                                      until the cleanup removes it
  state/findings/index.yml            generated, git-ignored
  state/claims/<doc-slug>.yml         claims about one document
    state/plans/<plan>/ledger.md handoff.md breakdown.yml mutations/
                                      live plans only; cleaned when the plan merges
  state/programs/<program>/status.md streams.yml requests/ sync-log.md
                                      live programs only, on the program's integration
                                      branch; cleaned when the program closes
  playbooks/                          project playbook (local rules)
  receipts/                           git-ignored read receipts
docs/strict-delivery/architecture.md  living architecture overview; cites decision ids
docs/strict-delivery/INDEX.md         the program session's overview; generated, git-ignored
docs/strict-delivery/specs/ plans/ reviews/
                                      specs, plans and review reports; namespaced so a
                                      project's own docs/ is never touched; cleaned when
                                      their effort is done
CLAUDE.md                             managed block + project text
.github/workflows/strict-delivery.yml optional extra (section 4)
.git/hooks/pre-commit pre-push        optional extra (section 4), shims
```

All paths are config keys with these defaults. Each path's responsibility, writer and cleanup
rule are in the programs and streams design, section 7.

Lean tree. Three kinds of path:
- Global, tracked and permanent on main: config, `context.yml`, decisions, open findings,
  playbooks, `architecture.md`, and the framework wiring (CLAUDE.md and `.gitignore` managed
  blocks, the extras).
- Per effort, tracked while live and cleaned when done: specs, plans, program folders, plan
  workspaces, review reports, claims (with the document they cite) and resolved findings (with
  the effort that resolved them). After a merge, and at a program's close, the cleanup step deletes them from the tree, in a pull request of its own; in v0.1 it sets no finding to `merged` (owner answer Q-Pplan-9 (a)). They stay in git history. Evidence that cites them uses the form
  `<sha>:<path>`, resolved with `git cat-file` (and required to name a commit in the
  repository), never a file at HEAD. A finding's evidence entry is a commit sha, a
  `<sha>:<path>`, or a plain path tracked at HEAD that lies outside every per-effort path and
  outside the findings directory, open findings included (owner answers 2026-10-31).
- Ignored, never committed: generated files (state indexes, `in-force.md`, `INDEX.md`), read
  receipts, agent scratch workspaces. The Claude Code hooks keep per-session state (live subagents, worktree bindings, decisions already surfaced) outside the repository, in the plugin's data directory; an unreadable state file is moved aside at the next session start. The SessionStart hook, `python3 -m gates index` and CI
  (when installed) regenerate the generated files before use.
- `init` writes the ignore entries between
  `# strict-delivery:begin schema=gitignore-block/1 version=<framework version>` and
  `# strict-delivery:end` in `.gitignore`. The rest of `.gitignore` is untouched, and
  `doctor` checks the block.

## 6. Config and the YAML subset

`config.yml` keys. Only `schema`, `framework_version` and `profile` are required in the file;
every other key may be omitted. The keys with a fixed default are `paths`, `ids`,
`models.tiers`, `decision_classes.owner_only`, `drift.estimate_factor_pct`, `base_branch`, `decisions.scan` and `merge.mode`, as listed below; a profile presets some others, such as the block size cap
(section 12). A key whose reader has not landed yet is optional in `config/1` and becomes
required, if at all, in a later schema version with a migration (owner answer 2026-10-31).

- `framework_version`, `profile` (light | standard | strict).
- `commands`: `test`, `test_one` (a template holding `{id}`), `lint`, `build` (each a shell
  string or list; optional `mutate`). Gates run them and never know the language or the test
  framework (section 13a).
- `paths`: every path in section 5.
- `ids`: the id format of section 7.2 (`<PREFIX>-<YYYYMMDD>-<xxxx>`, prefixes `DEC`, `F`,
  `C`, `R`).
- `models.tiers`: tier name to model id (defaults: tier1 haiku, tier2 sonnet, tier3 opus;
  tier4 has no default: a project that uses top-tier roles sets it). `roles` (section 10).
  `top_tier_roles`, `top_tier_fallback`.
- `decision_classes.owner_only`: default list in section 7.1; projects add their own
  (for example `hardware`). The project's list is added to the defaults, a union: a project
  cannot drop a default class (owner answer 2026-10-31).
- `block.max_tasks`, `rulings.max_per_block`, `dispatch.max_prompt_chars`, budgets per role.
- `drift.estimate_factor_pct` (optional, default 150, an integer percent: the YAML subset has
  no floats; `gate_drift`, section 9).
- `base_branch` (optional, default `main`): the base branch. Gates default `--base` to it; they
  check deletions and immutability against the merge base with it and id collisions against its
  tip (section 7.2; owner answer 2026-10-31).
- `decisions.scan` (optional, default `docs/**`, `CLAUDE.md`, `.strict-delivery/playbooks/**`):
  the tracked files `gate_decisions` scans for references to unanswered decision ids; files under
  the state directory are never scanned (section 7.1; owner answer 2026-10-31).
- `merge.mode` (optional, default `host`; in `config/2`, owner answers Q-M1 and Q-Pplan-14 (a)): who presses merge on an approved pull request: `host` (the owner, on the host) or `controller` (the controller, after the owner's approval in chat, section 8).
- `escape_cost` (optional, unset by default; in `config/2`, owner answer Q-B6plan-3 (a)): per counted severity (`CRITICAL`, `HIGH`, `MEDIUM`, `LOW`), the relative cost of an escaped defect in fix rounds; read only by `loopstats`.
- `overrides`: changes to a profile's `policy` keys, or to `limits` keys, for this repository (section 12); an entry is `<dotted key>: {value, decision}`, and the decision is an answered, in-force decision of class `profile-override` (section 7.1).

Streams are not configured here: each program carries its own ownership map in its
`streams.yml` (section 11).

The YAML subset (`gates/lib/yamlsub.py`, own parser and emitter): block mappings, block
sequences, flow sequences of scalars, plain/single/double-quoted scalars, `|` block scalars,
comments, integers, booleans, null. Refused with a line number: anchors, aliases, tags,
merge keys, duplicate keys, tabs for indentation, flow mappings, multi-document streams,
integers longer than 1000 characters and nesting deeper than 50 levels (owner answer
2026-10-31; the emitter refuses the same two limits with an error, since emitted text has
no line yet). One nesting level is each mapping, block sequence or flow sequence.
The emitter writes a canonical form so gate writes produce minimal diffs; parse(emit(x)) == x
for every value the parser accepts.

## 7. Decisions, findings, claims

### 7.1 Decision log

A decision is an owner question with at least two options and their cost. The owner is the
human driving the effort; there is no global owner setting. Answers and withdrawals come only
from that human: the PreToolUse Bash hook refuses `decisions decide` and `decisions withdraw`
from any subagent; the human runs them (`!` prefix), or the main session (the program session, or the controller's session in a plain plan) records the owner's exact words. Each answer
records the git identity (`git config user.email`) as `answered_at.by`. A hand edit of a record
cannot be told apart from a tool write; it is valid when the schema holds, and pull-request review is where a human checks who answered. Agents cannot hand-edit records: the PreToolUse Edit/Write hook refuses any agent Edit or Write under `paths.decisions` (section 4; owner answer Q-16 (a)). Nothing may reference an unanswered decision id
(`gate_decisions`, over the tracked files matching `decisions.scan`, section 6; the state
directory, where handoffs, status pages and records list open ids by design, is not scanned).

Default owner-only classes: audit triage, spec-vs-code direction, plan scope, merge grants,
model and cost policy, closing an issue, narrowing or widening a finding's class, rule
overrides, profile overrides (`profile-override`), and the program classes `program-create`, `stream-ownership`, `stream-merge`, `request-dispute` and `program-close` (programs and streams design, section 13). Controller
rulings: only inside an
approved plan, only plan-vs-spec or task-vs-task conflicts the spec settles, at most
`rulings.max_per_block`, ledgered as `Ruling: what -- why -- cost if wrong -- spec cite`.

Row fields: `id`, `status` (open | answered | withdrawn), `class`, `question`,
`options[{label, cost}]`, `asked_at`, `asked_by`, `topics`, `applies_to` (path globs),
`checked_against` (ids), `effect` (lasting | one-off), `supersedes` (optional id), then on
answer `answer`, `answered_at{at, by}`, `landed_in` (required when `effect: lasting`) and the
optional `rule` (a one-line rule summary, written at `decide`); on withdrawal
`withdrawn{at, by, reason}` instead of the answer fields (owner answers 2026-10-31).
A decision of class `rule-override` may carry the optional `overrides: SD-R<n>`, the base
playbook rule it overrides, matching `SD-R[1-9][0-9]*`; no other class carries it, and the
decision tools refuse a value that names a `fixed` rule (section 8). The field arrives in
`decision/2`, with a migration from `decision/1`, before block 3's SessionStart reads it
(owner answers 2026-10-31).
`asked_at`, `answered_at.at` and `withdrawn.at` are commit shas checked for shape only (7 to 40
lowercase hex characters), never for existence; `decide` and `withdraw` refuse when
`git config user.email` is unset (owner answers 2026-10-31).
Superseded is not a status: a decision is superseded when a later answered decision names it
in `supersedes`. At most one open or answered decision may name a given id in `supersedes`;
a withdrawn one is ignored, and `ask` refuses a second (owner answer 2026-10-31). The decision schema (appendix A) holds the exact shape. Grants use class
`merge-grant` and name the plan; a grant inside a program also names the program and the
stream, as the fields `plan`, `program` and `stream` (`plan` required on a grant; `program` and
`stream` together or not at all; none of the three on any other class; owner answer 2026-10-31). A pull-request merge approval is not a decision record (owner answer Q-15 (a), 2026-11-01): in `controller` mode the owner approves in chat naming the PR and its head sha, in `host` mode the owner's merge on the host is the approval, and the plan's ledger records each merge as a `MERGED` line (who merged, when, PR, head sha, merge commit, the approval). `merge-grant` records and their fields stay valid for records already written.

### 7.2 Storage and ids

- Ids: `<PREFIX>-<YYYYMMDD>-<xxxx>`: prefix `DEC` (decision), `F` (finding), `C` (claim) or
  `R` (cross-stream request); the UTC creation date; four characters from the lowercase base32
  alphabet without `0`, `1`, `l`, `o`, drawn at random. Example `DEC-20261031-k3f9`. The date
  must be a valid calendar date and is never compared with the clock (owner answer
  2026-10-31). No person's name or handle appears in any id. Within one program only the program controller (the program session by default, programs design section 4) mints ids; a plain plan's controller mints its own.
- One file per record, named by id. Decisions and findings carry `status`; a record stays in
  its folder whatever its status, and no status has a folder of its own.
- Shapes: `gate_decisions` and `gate_register` read record fields from the decision and
  finding schemas, and `gate_claims` from the claim schema (appendix A), never from
  hand-coded field lists.
- Invariants (`gate_decisions`, `gate_register`): no id appears twice across the tree, and a
  pull request's ids are checked against the base branch too (config `base_branch`, section 6;
  deletions and immutability are checked against the merge base with it); a resolved record is
  immutable (a change is a new decision with `supersedes`), except that a finding's status moves
  from `closed` to `merged`, set only by the cleanup step (owner answer 2026-10-31; in v0.1 the cleanup step is a pull request made by hand and sets no `merged`, owner answer Q-Pplan-9 (a)), and that a
  change which is exactly a registered schema migration of the base row is not an immutability
  change: the gates migrate the base row with the registered migrations before comparing, so a
  schema version change and `upgrade` can migrate resolved records (owner answer 2026-10-31); a
  decision's `landed_in` is never a spec. `gate_register` also reads every tracked file under
  `paths.reviews` whose first line is a `review-report` schema line, and fails when a finding
  id in it names no finding record (owner answer 2026-10-31).
- No-delete rule: a decision, open finding or claim file present on the base branch may not be
  deleted by a branch. The only deletions allowed are the cleanup step's (resolved findings and
  per-effort files, section 5). Until `gate_cleanup` lands (programs block), `gate_register`
  lets a branch delete a resolved finding only when an answered `merge-grant` names its
  `resolved_by` plan; the merge-commit check arrives with `gate_cleanup` (owner answer 2026-10-31). From block 1c on, merge approvals are not decision records (owner answer Q-15 (a), 2026-11-01), and from the programs block on, where `MERGED` ledger lines begin (programs Task P1.2), the deletion proof is the plan's final `MERGED` ledger line checked against git, as below.
- "Resolved" covers answered, withdrawn and superseded decisions; resolved decisions are
  permanent, and resolved rulings stay binding.
- Findings: an open finding (status open, planned, in-progress, fixed-unpinned, pinned or
  deferred) is global and permanent until resolved, even after the effort that raised it
  closes; ownership then passes to an issue or roadmap item. A resolved finding (status closed
  or merged) stays in `state/findings/`, names the plan that resolved it
  (`resolved_by: <plan>`) and is cleaned with that effort: the cleanup may delete it only when the plan's ledger records its final pull-request merge (`MERGED ... final=yes`) and that merge commit is on the target branch's first-parent history with the recorded head as its second parent; the cleanup is its own pull request (owner answers Q-15 (a), Q-Pplan-9 (a)).
- Claims are grouped per cited document (`claims/<doc-slug>.yml`), because they go stale
  whenever the cited code moves and are read together with that document; they are cleaned
  with that document.

### 7.3 Tools

`python3 -m gates decisions ask|decide|find|withdraw`, `findings new|move`, `index`.
`decisions ask` and `findings new` mint ids (section 7.2). `decide` (the human only,
section 7.1) writes the answer, sets `status: answered` and regenerates the indexes in one
step. Hand edits remain valid when the schema holds; gates check them.

### 7.4 How an agent knows a decision is already made

1. Decisions are the only home of lasting rules. A lasting decision is rolled into a
   playbook, CLAUDE.md or `architecture.md`; the decision's `landed_in` cites that place and
   the place cites the decision id. Specs may cite decision ids to mark where and why a
   decision was made, but a spec is never a `landed_in`, because specs are cleaned. Gate:
   `effect: lasting` requires `landed_in`, the cite resolves, and it is not a spec. The cite is
   a file under `paths.playbooks`, `CLAUDE.md` or `paths.architecture` that contains the
   decision id; its anchor is checked by `gate_cites` (owner answer 2026-10-31).
2. Scope tags: `applies_to` path globs and `topics`. At dispatch, the brief's file list is
   matched and in-force decisions are listed in the dispatch check output. On Edit/Write, the
   PreToolUse hook prints matching in-force decisions once per session.
3. `decisions find <terms> [--path P] [--topic T]` returns in-force decisions by default and
   follows `supersedes` chains to the current ruling. Skill rule: search before asking.
4. `decisions ask` runs `find` on the new question's topics, paths and keywords and prints
   candidates; the row must carry `checked_against`. Whether a candidate is a true duplicate
   is reviewer judgment.
5. `in-force.md`, generated: one table row per lasting decision still in effect (id, topic,
   rule summary, landed_in); the rule summary is the decision's `rule` field. Grants, one-off
   triage and superseded rows are excluded.

Default session load: `in-force.md` and the open decisions. Everything else via `find` or path
surfacing.

## 8. Base playbook

Plugin-owned, versioned, read in place from the plugin (not copied; upgrades update it). The
CLAUDE.md managed block points at it.

```
playbook/rules.md      SD-R<n> rules: rule, why, enforcing gate (or "judgment"), profiles, fixed?
playbook/roles.md      roles, model tiers, dispatch contract, report contract
playbook/decisions.md  the decision log (section 7) in operating terms
playbook/sessions.md   session kinds, start order, blocks, checkpoints, handoffs
playbook/streams.md    programs and streams (section 11)
playbook/review.md     task and final review, verifier, fix loop, process-defect stop
```

Initial rule set, rewritten from lap-timer rulings without their history:

- Every change, any size, is a register row before work starts.
- No claim is trusted: verify directly and by contradiction, record both commands.
- Owner-only classes are questions in the log; the path halts until answered.
- Report before plan: after an audit, the owner rules on triage before any plan; no plan is
  committed the owner has not seen. Plan in full before code (owner answer Q-PL-1 (a), 2026-11-02): every block of a spec and its plan is planned in full (tasks, files, interfaces, input-domain dimensions, tests) before any code is written; no block whose plan is only an outline may start implementation. The last planning step is the stream breakdown plan, `<paths.plan_state>/<plan>/breakdown.yml` (kind `breakdown/1`, appendix A): the streams with their owned paths, the tasks of each stream, the dependency edges from task to task, each stream's unblock condition, the parallel groups (each within the concurrency limit), and the concurrency and depth limits it assumes. Streams run as they unblock. When a program starts, `program create` refuses a plan with an outline-only block (a block section without task headings, or a pointer to a section that does not exist or holds none), a plan without the expected block structure, or a missing or invalid breakdown: one whose `max_concurrent` or `max_depth` exceeds the effective limit (the lower of config `limits` and the measured Claude Code limits, section 10), or whose streams and owned paths differ from the program's `streams.yml` (programs and streams design, section 5).
- Zero bugs: a change's own bug makes it incomplete; review minors are fixed in the fix round,
  never deferred; an unrelated bug gets a register row and an owner.
- A deleted test is restored and fixed; dropping a test is never offered as a fix.
- A class of findings is an epic with child rows; signed off only when every child is resolved
  and the whole class is tested and reviewed.
- Findings that keep arriving round after round are a process defect: stop fixing, find where
  they entered and why reviews missed them, bring process changes to the owner.
- Reviewers execute every claim and re-run every gate themselves.
- Pinned means a production-path test plus a mutation transcript.
- One block per agent context, at most `block.max_tasks` tasks, clean worktree at every
  checkpoint. `gate_checkpoint` counts a block's tasks both as its plan's `Task <block>.<n>` headings and as the distinct `<block>.<n>` task tokens of its ledger's `CHECKPOINT` lines. Continuation is automatic: an agent that reaches a checkpoint, 80 % of its token
  or time budget, or a usage-limit stop writes its handoff and returns; its dispatcher at once
  dispatches a fresh agent of the same role with a continue prompt built from the handoff,
  ledger and status page. Nothing continues from inherited memory, and the owner never
  `/clear`s and re-prompts.
- The base branch is protected: nothing is pushed or merged to it directly. Every change reaches it by a pull request on all-green, merged by merge commit on the owner's approval: in `controller` mode the owner approves in chat naming the PR and its head sha and the controller runs `gh pr merge --merge --match-head-commit <sha>`; in `host` mode the owner merges on the host. The plan's ledger records each merge as a `MERGED` line; merge approvals are not decision records (owner directive 2026-11-01; owner answer Q-15 (a)). Work branches are pushed at every checkpoint. Two merges need no approval: a stream controller merges a group branch into its stream branch after a clean review and green gates; and during a sync the program controller merges main into the integration branch and into each stream branch behind it, never rebasing (owner answer Q-Pplan-5 (a)). If such a merge conflicts, the controller stops and asks the owner.
- After a merge, and at a program's close, the cleanup step removes the per-effort files from the tree in a pull request of its own (section 5); evidence cites them as `<sha>:<path>`.
- Every agent reaps its background jobs before reporting; the controller checks for orphans.
- Scripts that write files start with `set -eu` and assert they run inside their scratch path.
- Owner rules go into decisions, rolled into playbooks, CLAUDE.md or `architecture.md`; agent
  memory only points to them.
- Dispatch only inside the role/model map; the top tier only for `top_tier_roles`.

Rules marked `fixed` (owner-only classes, merge grants, the bypass block) cannot be
overridden. Any other rule is overridden only by a project decision of class `rule-override`
with `overrides: SD-R<n>` (section 7.1; decision schema `decision/2`); SessionStart lists active
overrides. Project rules live in `.strict-delivery/playbooks/`.

## 9. Context, docs and drift tooling

- `.strict-delivery/context.yml` lists required reads per session kind and role (for example:
  every session reads `in-force.md` and its handoff, a session inside a program also reads its
  program's status page, and a reviewer additionally reads the brief and the review playbook).
  SessionStart prints the list for the session kind; `python3 -m gates context <kind>` prints it
  on demand. The session kinds of programs are in the programs and streams design, section 10. A plain plan's controller session has the kind `plan`; a kind `stream-<id>-block` is looked up as `stream-block`.
- Read receipts: a PostToolUse hook on Read appends a `{path, sha}` row for every Read, partial reads included (`path` is the file's real absolute path and `sha` the git blob id of its bytes), to
  `receipts/<session>.yml` (git-ignored), a YAML file with a top-level `schema:` key and a
  `reads:` list. `gate_context` reports each required read that is missing or was read at a different content hash as a failing line, under every profile. The Claude Code hooks refuse the dispatch or commit on it under `strict` and print it as a warning under `light` and `standard`. It checks the reads of the session making the dispatch or commit; a role that neither dispatches nor commits gets its list printed, not gated.
- `gate_cites`: every `path:line` and `path#anchor` cite in tracked docs resolves in the tree
  being committed: docs and cited targets are the tracked files as read from the working tree,
  not from `HEAD`, so a doc and the target it cites can land in one commit. The working tree
  is the tree being committed for an agent's commit through the Claude Code PreToolUse Bash
  hook, which refuses a `git commit` inside a compound command, or with a `GIT_INDEX_FILE` override, for a commit made outside Claude when the git pre-commit hook is installed and not
  bypassed, and in CI, which checks out the commit itself; both hooks refuse a commit while a
  tracked file has unstaged changes, and section 13 states the conditions (owner answers
  2026-10-31).
- `gate_drift`: status-page and handoff facts (branch heads, merged PRs, open blocks) match git, and, when run with `--host`, the host's pull requests through `gh` (an unavailable host then fails); pending decisions on a status page match open decision records; a stream branch behind the base branch, or an integration branch behind it, fails until a sync (a sync merges main into both, section 8); a stream whose status row's `used` is past `drift.estimate_factor_pct` percent of its `estimate` is reported to the owner by `python3 -m gates drift report` at each sync; it is not a failing line.
- `gate_index`: `docs/strict-delivery/INDEX.md` and the state indexes regenerate without error,
  and none of them is tracked (a tracked generated file fails).
- `gate_checkpoint`: handoff front matter matches its schema (plan, spec, branch, head, base,
  ledger, resume line, block, next task, findings in flight, open decisions, rulings, grant,
  live subagents), the block's own worktree is clean (other streams' worktrees may be dirty),
  the continuation handoff is present, and the ledger carries the `CHECKPOINT` line; its last `CHECKPOINT` line records the suite and gates green.
- `gate_cleanup` (after a merge and at a program's close; covers plain plans and programs): the
  merged plan's or closed program's per-effort files are gone from the tree, and every lasting
  decision they produced has a `landed_in` outside them.
- `gate_schema`: every framework file validates against the schema of its kind (appendix A);
  it runs on commit, in the Claude hooks, and in CI when CI is installed.

## 10. Agent management

Roles (framework roles with their prompt blocks and minimum tiers fixed in the framework, `dispatch.ROLES`/`MIN_TIERS`; config `roles` adds project roles with their own prompt block and minimum tier): program_controller, stream_controller, controller, implementer,
implementer_transcription, task_reviewer, final_reviewer, final_verifier, exception_reviewer,
audit_reviewer, audit_verifier, investigator. program_controller and stream_controller are
core roles at tier3 (section 11). `budgets.<role>` holds the budget cap; whether a role needs a brief and which finding states it may take are judgment rules in the base playbook, not gated in v0.1.

Dispatch prompt grammar, checked by the PreToolUse Agent hook (`gate_dispatch`):
`## Role`, `## Brief`, `## Findings`, `## Claims`, `## Budget: tokens=<n> minutes=<n>`,
`## Model`, `## Report`, `## Strict block` (the role's prompt block, byte for byte),
`## Task`. A fork dispatch is refused. The tool's model must equal `## Model` and meet the
role's minimum tier; the top tier is allowed only for `top_tier_roles`. `gate_dispatch` refuses any dispatch whose dispatcher is a worker role (owner answer Q-H4).

Lifecycle: in a plain plan, the controller dispatches every role. In a program, only the program session dispatches a program_controller; the program session (which acts as program controller by default) or a program_controller dispatches a stream_controller; stream controllers and their sub-controllers dispatch the workers, and a sub-controller may dispatch a sub-controller when the stream controller judges it better, within the depth limit (owner answers Q-H3, Q-H5 (a)). Fix
loop rounds 1-3 resume the implementer,
rounds 4-5 a fresh agent one tier up, then an owner question; every report starts with
`status: DONE|DONE_WITH_FINDINGS|NEEDS_DECISION|BLOCKED|DENIED`. A controller never returns
while its children run: questions and progress go up to its parent as messages, and answers
come down as decision records (section 11). After each review the controller may run `python3 -m gates loopstats`, which prints the advisory Rules N (novelty) and T (trend) and, when `escape_cost` is set, an expected-value verdict; it never blocks and never decides whether a found defect is fixed.

## 11. Programs and streams

Specified in full in
[`2026-10-31-programs-and-streams-design.md`](2026-10-31-programs-and-streams-design.md); in
brief:

- Small work is a plain plan run by one controller. A large effort is a program, split by a
  program plan into streams; each stream owns a disjoint set of files and runs its own blocks in
  its own worktrees under one stream_controller. By default the owner's lean program session itself acts as program controller; a separate program_controller runs only when the configured depth allows (owner answer Q-H5 (a)).
- A stream never edits another stream's file: it raises a cross-stream request, which the
  program controller records and the owning stream implements.
- Each program keeps its status page, ownership map (`streams.yml`), requests and sync log in
  its program folder on its integration branch; only the program controller commits there, apart from the sync's merges; it never merges into the base branch (owner answer Q-M4 (a)).
- Branches: `<program>/integration`, stream branch `<program>/<stream>/main`, group branch
  `<program>/<stream>/<group>`. No branch is named `<program>` or `<program>/<stream>`, because
  git refuses a ref that is also another ref's directory; the stream id `integration` and the
  group id `main` are refused. Program, stream and group ids match `[a-z0-9][a-z0-9-]*` (no `/`,
  so a group can never be another group's directory). Worktrees mirror the branches in nested
  folders:
  `<worktrees>/<program>/<stream>/main` for a stream and `<worktrees>/<program>/<stream>/<group>`
  for a group. Dashes are allowed in ids.
- A stream controller merges each group branch into its stream branch after a clean review and
  green gates, with no owner approval; a finished stream opens its own pull request to the base branch, merged on the owner's approval (section 8; owner answer Q-M4 (a)).
- Questions travel up as messages and are asked as one batch; answers travel down as decision
  records. Agents continue themselves from handoffs (section 8).
- `gate_streams` checks ownership, shared-file rules, status rows and request records; it and
  `gate_dispatch` run wherever a program is live, whatever the profile.

## 12. Profiles

| | light | standard | strict |
|---|---|---|---|
| register row per change | yes | yes | yes |
| decision log + owner-only gate | yes | yes | yes |
| claims register | no | yes | yes |
| dispatch grammar + model tiers | no | yes | yes |
| top-tier final verifier | no | no | yes |
| review package + mutation transcript | no | per finding | every pin |
| pre-commit | schema, register, decisions | run_all | run_all + gate suite on every supported runtime |
| block size cap | none | 5 tasks | 3 tasks |
| context read receipts | advisory | advisory | enforced |
| programs and streams | available | available | available |
| bypass block | yes | yes | yes |

`gate_schema` runs in every profile. Wherever a program is live, `gate_streams` and
`gate_dispatch` run, whatever the profile.
A profile is a preset of config keys in two parts: `defaults`, keys a repository sets directly (such as `top_tier_roles`), for which the profile supplies init's default, and `policy`, keys changed per repository only under `overrides`. An `overrides` entry is `<dotted key>: {value, decision}`, for a policy key or a `limits` key, and the decision is an answered, in-force decision of class `profile-override` (section 7.1).

## 13. Gate contract

Every gate: `check(args) -> Result`; prints `PASS id` or `FAIL id: reason` lines; `--json`;
exits 0 only when at least one line exists and every line passes; a missing input fails
(`<gate>.input`), an empty run fails (`<gate>.empty`); `--root` points at another tree.
`run_all` runs the gates the profile enables; a missing or raising gate fails. Hooks fail
closed on internal error. Two hooks refuse a commit while any tracked file has unstaged
changes, before any gate runs, so the gates they run read the tree being committed: the
Claude Code PreToolUse Bash hook, for a commit an agent makes (section 4), and the git
pre-commit hook, for a commit made outside Claude when that extra is installed (section 4).
When the git hooks are installed and current, the PreToolUse Bash hook runs its refusals and leaves the gates to the git pre-commit and pre-push hooks, which the bypass block keeps from being skipped.
The PreToolUse hook refuses a Bash command that runs `git commit` inside a compound command, or with a `GIT_INDEX_FILE` override,
so a commit runs as its own command, and its check runs before that command, so the index the
commit records changes only through the commit itself (owner answers 2026-11-01). The bypass block refuses an agent's `--no-verify`; a
human's `--no-verify`, or a repository without the git hooks, commits outside Claude with no
gate run. CI checks out the pushed commit, so there the working tree is the commit (owner answers 2026-10-31). The git pre-push hook refuses a push to the base branch, and the PreToolUse Bash hook refuses an agent's push or merge to it (section 4; owner directive 2026-11-01).

## 13a. Evidence contract for target projects

The framework never prescribes how a project writes tests. It defines only the evidence a
gate can check, in terms of the project's own commands:

- A pin is an opaque test id plus `commands.test_one` rendered with it (for example
  `npx jest -t {id}`, `mvn -Dtest={id} test`, `cargo test {id}`). The gate checks that the id
  is given and that the command exits 0 on the fixed tree.
- A mutation transcript is three runs of that command: pass on the fix, fail with the fix
  reverted or with a mutant, pass again. How the mutant is made is the project's choice:
  a manual revert, or `commands.mutate` pointing at the project's own tool (Stryker, PIT,
  mutmut, cargo-mutants, ...). The gate checks the transcript's shape, commands and exit codes,
  never the tool.
- `gate_evidence` checks both, stack-neutral: a review package per finding or pin names the
  test id, the rendered `test_one` command and the transcript; the gate re-runs the pin
  command on the fixed tree and checks the transcript's shape (pass, fail, pass) and exit
  codes. It runs per section 12: under standard it checks the pinned findings a branch adds or changes against the merge base with `base_branch`; under strict, every pinned finding in the tree; light does not run it.
- No test filename patterns, no test framework detection, no test-style or TDD rules in any
  gate. Lap-timer's `test_*.py`/`test_*.c` detection and `test_<module>::test_<name>` pin form
  are not carried over.
- "Production-path" (the test drives the real code path, not a mock of it) stays a reviewer
  judgment rule, worded stack-neutral in the base playbook.
- Stack testing practice (React Testing Library, JUnit, table tests, ...) belongs in the
  project playbook, written by the developer. Optional adapter packs are out of core.

## 14. Testing the framework itself

These tests live in, and run on, the framework repository only; nothing here is shipped into or
imposed on a target repository. Fixture repositories exist to prove that init, detection and
the gates behave on those layouts, not to say how such projects should test.

- The lap-timer gate suite, ported and generalised, with synthetic fixtures; history-specific
  cases dropped.
- Matrix: Python 3.9 and 3.13 on ubuntu and macOS.
- YAML subset: round-trip, every refusal case, a fuzz corpus.
- Init end-to-end: fixture repositories (node, rust, go, python, C with make, empty, monorepo);
  non-interactive init from an answers file; `doctor` and `run_all` green; then seeded
  violations (unanswered decision reference, `--no-verify`, an agent-run `decisions decide`,
  bad dispatch, a duplicate id, a base-branch record deleted, a tracked generated index) each
  turn the run red. Every gate has a red case. A fixture
  with existing `docs/superpowers/` documents and one with a colliding path prove the
  migration and the no-overwrite rule.
- Hooks: JSON event fixtures into each hook script.
- Profiles: the same fixture repository under each profile runs exactly the gates the profile
  table names.
- Skill pressure scenarios (headless `claude -p` runs against rationalisation traps such as
  "too small for the process"): an opt-in workflow, not default CI, because of cost.
- The framework's own fixes: production-path test plus mutation transcript.

## 15. Release

Semver tags and `CHANGELOG.md`. A release script (`scripts/release.py`, framework repository only) bumps together every literal version that section 4 requires to agree: plugin.json, marketplace.json, and this repository's CLAUDE.md and `.gitignore` block versions and `framework_version`; templates render the version at init and hold none. It never commits, pushes or tags; the release reaches main by pull request, and tags are pushed on the owner's word. Every data file carries
`schema: <kind>/<version>` (appendix A). A shape change is a new schema version plus a
migration from the old version, which `upgrade` runs; every migration is tested from an old
fixture to the new version. Before 1.0, breaking changes are allowed with a migration; 1.0
freezes the config and state schemas.

## 16. The framework repository's own process

- The repository adopts itself at the strict profile with empty registers, and answers yes to the local git hooks; its own matrix workflow (`.github/workflows/strict-delivery.yml`) stands in for the CI extra, which `doctor` reports as a project workflow. Owner: superbrobenji.
- Bootstrap: the first block builds lib, the YAML subset and the register and decision gates
  while no gates exist; this is stated in its first report and the judgment rules apply. Each
  gate is enabled on this repository as soon as it lands; from then every change is gated.
- lap-timer's migration onto the framework is a separate, later sub-project in the lap-timer
  repository.
- lap-timer is the reference the framework is generalised from, not a dependency. Everything
  about this framework (findings, decisions, plans) is tracked in this repository only. As
  lap-timer's strict-delivery matures, its changes are reviewed for porting; a lap-timer
  finding or change enters this repository only after the owner is asked and agrees.

## 17. Delivery blocks (the plan refines these)

1. lib, YAML subset, the schema checker (`gate_schema`) with the config, decision and finding
   schemas and the generated in-force, index and overview kinds (appendix A), one-file-per-record
   registers with the id format of section 7.2 and the no-delete rule, `gate_register`,
   `gate_decisions`, decisions/findings tools (`ask`,
   `decide`, `find`, indexes, `in-force.md`).
2. `gate_claims`, `gate_dispatch`, `run_all`, git hook shims and installer, self-adoption, and the decision schema `decision/2` (the optional `overrides`, section 7.1) with its migration; `config/2` with its migration carries `merge.mode` (owner answer Q-Pplan-14 (a)) and the optional `escape_cost` (owner answer Q-B6plan-3 (a)).

Programs block, placed after block 2 so this repository can run its remaining blocks as a
program: the program_controller and stream_controller prompt blocks, automatic continuation,
the upward-question path, a basic `gate_checkpoint`, `gate_streams`, and `gate_cleanup` (for
plain plans and programs). The plan fixes its exact order.

3. Plugin: skill, role prompt blocks, base playbook, Claude Code hooks.
4. `init`, `doctor`, `upgrade`, templates, CI workflow template, stack detection, the
   no-overwrite rule and the superpowers document migration.
5. Context, docs and drift tooling in full (`gate_context`, receipts, `gate_cites`,
   `gate_drift`, `gate_index`).
6. `gate_checkpoint` in full, `gate_evidence` (section 13a), profile end-to-end tests,
   release 0.1.0.

## 18. Owner choices recorded in this design

Audience public; tiered profiles; plugin plus init command; depends on superpowers and
overrides it; Python standard library only; strict YAML subset; v0.1 covers the landed core
plus all docs and agent management, including program tooling designed here; lap-timer
migrates later; name `strict-delivery`; one file per record with dated random-suffix ids
(section 7.2); registers ship empty, framework rules ship as the base playbook;
repository created public on GitHub; programs and streams as specified in the programs and
streams design (section 11); local git hooks (default on) and CI (default off) as init
options (section 4); one schema per file kind, checked by `gate_schema` (appendix A).

Section 6 review added: the framework's own tests are separate from, and never imposed on,
target projects; target projects meet an evidence contract built on their own commands
(section 13a); init's detection only offers the project's existing commands.

Answered 2026-10-31: licence MIT; evidence is gated in v0.1 by a stack-neutral
`gate_evidence` in block 6 (section 13a), chosen over leaving it to reviewer judgment until
v0.2, at a cost of about one block of work; v0.1 CI is GitHub Actions only and there is no
Windows support, with Claude Code hook logic written in Python so a later Windows port stays
cheap (section 3); GitLab CI is left out until users need it. lap-timer is the reference
only, and its findings enter this repository only with the owner's agreement (section 16).

## 19. Open questions for the owner

None.

## Appendix A. Data shapes

Every framework file has a kind, and every kind has exactly one schema at
`gates/schemas/<kind>.yml`, written in the YAML subset (section 6). A schema states the
required and optional fields, their types and allowed values, id formats (section 7.2) and
cross-references to other records; for a markdown file it states the exact front matter and
table headers. Every data file carries `schema: <kind>/<version>`; a shape change is a new
version plus a tested migration that `upgrade` runs (section 15). Where the line sits:

- YAML files: a top-level `schema: <kind>/<version>` key.
- Markdown files with YAML front matter (handoff): `schema: <kind>/<version>` in the front
  matter.
- Other framework markdown files (status page, sync log, ledger, `INDEX.md`, `in-force.md`,
  review reports): the first line is `<!-- schema: <kind>/<version> -->`.
- Managed blocks: the begin marker,
  `<!-- strict-delivery:begin schema=claude-block/1 version=<framework version> -->` in
  CLAUDE.md and `# strict-delivery:begin schema=gitignore-block/1 version=<framework version>`
  in `.gitignore`. The end markers stay plain.
- Mutation transcripts: the first line is `<!-- schema: mutation-transcript/1 -->`. A review package is the `PIN`, `PIN-TEST` and `PIN-COMMAND` lines of a review report; a transcript's lines are `FINDING`, `TEST`, `MUTANT` and three `RUN` lines, and a transcript sits directly in a plan's `mutations/` folder.
- Read receipts: a YAML file with a top-level `schema:` key. `gate_schema` does not read receipts (git-ignored, local); `gate_context` validates the receipt file it reads and fails closed on a bad one.
- Hook session state: a YAML file whose first key is `schema: hook-session/1`, kept in the plugin's data directory (section 5); it lives in no tree, so `gate_schema` never reads it, and its reader checks it.
- File lists: a schema's `files` glob may hold `/`-separated segments (`*/handoff.md`), each segment but the last matching real directories; a front-matter kind's schema (format `front-matter`) checks the front matter only (programs block Task P1.1).

`gate_schema` validates every framework file against the schema of its kind, on commit, in the
Claude hooks, and in CI when CI is installed. A kind's schema file becomes required when the
gate or tool that produces that kind lands. `gate_schema` fails when a required kind has no
schema file, or when a schema file is not named in this table; kinds whose producer has not
landed are not checked. A kind's producer has landed when a gate or tool in the installed
framework version declares that kind in its `produces` list; `gate_schema` reads those lists.
One stated exception: `gate_schema` always checks the config kind, though no gate or tool
produces it before `init` (owner answer 2026-10-31). Every schema refuses a key it does not
declare. A generated file (in-force, decision-index, finding-index, overview) that is absent on
disk is skipped, since it is regenerated before use (owner answers 2026-10-31). The decision
schema carries the optional `rule`, the `withdrawn{at, by, reason}` map and the grant fields `plan`, `program` and `stream` (section 7.1; kept for records already written, since pull-request merge approvals are ledger `MERGED` lines, not records, owner answer Q-15 (a)). From `decision/2` it also carries the optional
`overrides` (section 7.1), with a tested migration from `decision/1` that lands before block 3's
SessionStart reads the field (owner answer 2026-10-31). The first overview version, `overview/1`, holds
only the sections block 1 can fill (architecture, open findings, in-force decisions); the specs-and-plans and live-program sections come in `overview/2`; being generated and git-ignored, an `overview/1` file is migrated by regenerating it (`python3 -m gates index`) (owner answer 2026-10-31).
Block 1 carries the config, decision and finding schemas, plus the generated in-force,
decision-index, finding-index and overview kinds, because block 1's tools produce them
(section 17).

| Kind | Schema file | Purpose |
|---|---|---|
| config | `gates/schemas/config.yml` | `.strict-delivery/config.yml`, the repository settings (section 6) |
| decision | `gates/schemas/decision.yml` | one decision record (section 7.1) |
| finding | `gates/schemas/finding.yml` | one finding record (section 7.2) |
| claim | `gates/schemas/claim.yml` | the claims about one document (section 7.2) |
| request | `gates/schemas/request.yml` | one cross-stream request record (section 11) |
| streams | `gates/schemas/streams.yml` | a program's ownership map (section 11) |
| context | `gates/schemas/context.yml` | required reads per session kind and role (section 9) |
| handoff | `gates/schemas/handoff.yml` | a plan's handoff front matter (section 9) |
| ledger | `gates/schemas/ledger.yml` | a plan ledger's line formats (`CHECKPOINT`, `Ruling:`, `Request:`, `UPDATE`, `MERGED`); a line led by one of these words must match its form, any other line is prose (owner answer Q-Pplan-1 (a)) |
| status | `gates/schemas/status.yml` | a program's status page table (section 11) |
| sync-log | `gates/schemas/sync-log.yml` | a program's sync log (section 11) |
| overview | `gates/schemas/overview.yml` | the sections of `INDEX.md` (section 5) |
| in-force | `gates/schemas/in-force.yml` | the generated `in-force.md` (section 7.4) |
| decision-index | `gates/schemas/decision-index.yml` | the generated `state/decisions/index.yml` (section 5) |
| finding-index | `gates/schemas/finding-index.yml` | the generated `state/findings/index.yml` (section 5) |
| mutation-transcript | `gates/schemas/mutation-transcript.yml` | one mutation transcript (section 13a) |
| review-report | `gates/schemas/review-report.yml` | one review report or review package (section 13a) |
| receipt | `gates/schemas/receipt.yml` | one session's read receipts (section 9) |
| breakdown | `gates/schemas/breakdown.yml` | a plan's stream breakdown, `<paths.plan_state>/<plan>/breakdown.yml` (section 8): `plan`, `max_concurrent` and `max_depth` (the limits assumed), `streams` (each `id`, owned `paths`, `tasks`, `unblock`), `edges` (`from` task, `to` task: `to` waits for `from`), `groups` (parallel groups: `id`, `tasks`); owner answer Q-PL-1 (a) |
| claude-block | `gates/schemas/claude-block.yml` | the CLAUDE.md managed block (section 4) |
| gitignore-block | `gates/schemas/gitignore-block.yml` | the `.gitignore` managed block (section 5) |
| profile | `gates/schemas/profile.yml` | a profile preset in the plugin (section 12) |
| init-answers | `gates/schemas/init-answers.yml` | the answers file of a non-interactive `init` (section 4) |
