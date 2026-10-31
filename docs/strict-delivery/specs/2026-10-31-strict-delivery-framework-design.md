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
  hooks/hooks.json                    SessionStart, UserPromptSubmit, PreToolUse(Agent, Bash, Edit/Write), PostToolUse(Read)
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
  docs/strict-delivery/specs/ docs/strict-delivery/plans/
```

Runtime: Python 3.9 or newer, standard library only. No PyYAML; state and config use the
strict YAML subset (section 6). Claude Code hook logic is Python (`python3 -m gates hook
<event>`), not shell, so it does not depend on a POSIX shell; the git hook shims are a
one-line POSIX sh exec of `python3 -m gates`. Windows is not supported in v0.1, but no hook
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
2. Ask for profile and model map (default from the profile). Ask the two extras' questions:
   local git hooks (pre-commit, pre-push), default **yes**; the GitHub Actions workflow,
   default **no**, since not every project can use it or may run it.
3. Write `.strict-delivery/config.yml`, empty state directories, the CLAUDE.md managed block
   (between `<!-- strict-delivery:begin schema=claude-block/1 version=<framework version> -->`
   and `<!-- strict-delivery:end -->`; the rest of CLAUDE.md is untouched), and the extras
   answered yes: the git hook shims, the CI workflow.
   - Init and upgrade never overwrite. They refuse to write any path that already exists
     and is not framework-managed. Framework-managed means a managed block between the
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
is tracked, and the `.gitignore` managed block matches the plugin version. A project with
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
  (standard and strict, and every profile while a program is live).
- PreToolUse Bash: hook-bypass block (`--no-verify`, `-n`, `core.hooksPath`,
  `GIT_CONFIG_*`, HOME moves), gated commit/push, and refusal of `decisions decide` and
  `decisions withdraw` from any agent (section 7.1) (all profiles).
- PreToolUse Edit/Write: surfaces in-force decisions whose `applies_to` matches the path,
  once per session per decision (section 7.4); records nothing, blocks nothing.
- PostToolUse Read: read receipts for the context contract (section 9).

Enforcement: the framework enforces through what the plugin installs, the Claude Code hooks
(they run the gates before a commit or push an agent makes, and check dispatches, edits and
reads) and the skill's rules. The two extras extend the same gates to commits made outside
Claude: the git pre-commit and pre-push hooks, and the CI workflow, which checks out
`superbrobenji/strict-delivery` at the pinned tag and runs `python3 -m gates run_all`.

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
  state/plans/<plan>/ledger.md handoff.md mutations/
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
  the effort that resolved them). After a merge, and at a program's close, the cleanup step
  deletes them from the tree. They stay in git history. Evidence that cites them uses the form
  `<sha>:<path>`, resolved with `git cat-file` (and required to name a commit in the
  repository), never a file at HEAD.
- Ignored, never committed: generated files (state indexes, `in-force.md`, `INDEX.md`), read
  receipts, agent scratch workspaces. The SessionStart hook, `python3 -m gates index` and CI
  (when installed) regenerate the generated files before use.
- `init` writes the ignore entries between
  `# strict-delivery:begin schema=gitignore-block/1 version=<framework version>` and
  `# strict-delivery:end` in `.gitignore`. The rest of `.gitignore` is untouched, and
  `doctor` checks the block.

## 6. Config and the YAML subset

`config.yml` keys (required unless marked):

- `framework_version`, `profile` (light | standard | strict).
- `commands`: `test`, `test_one` (a template holding `{id}`), `lint`, `build` (each a shell
  string or list; optional `mutate`). Gates run them and never know the language or the test
  framework (section 13a).
- `paths`: every path in section 5.
- `ids`: the id format of section 7.2 (`<PREFIX>-<YYYYMMDD>-<xxxx>`, prefixes `DEC`, `F`,
  `C`, `R`).
- `models.tiers`: tier name to model id (defaults: tier1 haiku, tier2 sonnet, tier3 opus,
  tier4 the top-tier model). `roles` (section 10). `top_tier_roles`, `top_tier_fallback`.
- `decision_classes.owner_only`: default list in section 7.1; projects add their own
  (for example `hardware`).
- `block.max_tasks`, `rulings.max_per_block`, `dispatch.max_prompt_chars`, budgets per role.
- `drift.estimate_factor` (optional, default 1.5; `gate_drift`, section 9).
- `overrides`: profile keys changed for this repository; each entry names the owner decision
  that authorised it.

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
from any agent, and the human runs them (`!` prefix) or the program session records the
owner's exact words. In a plain plan the same holds for the controller's session. Each answer
records the git identity (`git config user.email`) as `answered_at.by`. A hand edit of a record
cannot be told apart from a tool write; it is valid when the schema holds, and pull-request review
is where a human checks who answered. Nothing may reference an unanswered decision id
(`gate_decisions`).

Default owner-only classes: audit triage, spec-vs-code direction, plan scope, merge grants,
model and cost policy, closing an issue, narrowing or widening a finding's class, rule
overrides, and the program classes `program-create`, `stream-ownership`, `stream-merge`,
`request-dispute` and `program-close` (programs and streams design, section 13). Controller
rulings: only inside an
approved plan, only plan-vs-spec or task-vs-task conflicts the spec settles, at most
`rulings.max_per_block`, ledgered as `Ruling: what -- why -- cost if wrong -- spec cite`.

Row fields: `id`, `status` (open | answered | withdrawn), `class`, `question`,
`options[{label, cost}]`, `asked_at`, `asked_by`, `topics`, `applies_to` (path globs),
`checked_against` (ids), `effect` (lasting | one-off), `supersedes` (optional id), then on
answer `answer`, `answered_at{at, by}`, `landed_in` (required when `effect: lasting`).
Superseded is not a status: a decision is superseded when a later decision names it in
`supersedes`. The decision schema (appendix A) holds the exact shape. Grants use class
`merge-grant` and name the plan; a grant inside a program also names the program and the
stream.

### 7.2 Storage and ids

- Ids: `<PREFIX>-<YYYYMMDD>-<xxxx>`: prefix `DEC` (decision), `F` (finding), `C` (claim) or
  `R` (cross-stream request); the UTC creation date; four characters from the lowercase base32
  alphabet without `0`, `1`, `l`, `o`, drawn at random. Example `DEC-20261031-k3f9`. No
  person's name or handle appears in any id. Within one program only the program controller
  mints ids; a plain plan's controller mints its own.
- One file per record, named by id. Decisions and findings carry `status`; a record stays in
  its folder whatever its status, and no status has a folder of its own.
- Shapes: `gate_decisions` and `gate_register` read record fields from the decision and
  finding schemas, and `gate_claims` from the claim schema (appendix A), never from
  hand-coded field lists.
- Invariants (`gate_decisions`, `gate_register`): no id appears twice across the tree, and a
  pull request's ids are checked against the base branch too; a resolved record is immutable
  (a change is a new decision with `supersedes`); a decision's `landed_in` is never a spec.
- No-delete rule: a decision, open finding or claim file present on the base branch may not be
  deleted by a branch. The only deletions allowed are the cleanup step's (resolved findings and
  per-effort files, section 5).
- "Resolved" covers answered, withdrawn and superseded decisions; resolved decisions are
  permanent, and resolved rulings stay binding.
- Findings: an open finding (status open, planned, in-progress, fixed-unpinned, pinned or
  deferred) is global and permanent until resolved, even after the effort that raised it
  closes; ownership then passes to an issue or roadmap item. A resolved finding (status closed
  or merged) stays in `state/findings/`, names the plan that resolved it
  (`resolved_by: <plan>`) and is cleaned with that effort: the cleanup may delete it only
  when that plan's merge grant is answered and its merge commit exists on the target branch.
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
   `effect: lasting` requires `landed_in`, the cite resolves, and it is not a spec.
2. Scope tags: `applies_to` path globs and `topics`. At dispatch, the brief's file list is
   matched and in-force decisions are listed in the dispatch check output. On Edit/Write, the
   PreToolUse hook prints matching in-force decisions once per session.
3. `decisions find <terms> [--path P] [--topic T]` returns in-force decisions by default and
   follows `supersedes` chains to the current ruling. Skill rule: search before asking.
4. `decisions ask` runs `find` on the new question's topics, paths and keywords and prints
   candidates; the row must carry `checked_against`. Whether a candidate is a true duplicate
   is reviewer judgment.
5. `in-force.md`, generated: one line per lasting decision still in effect (id, topic, rule
   summary, landed_in). Grants, one-off triage and superseded rows are excluded.

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
  committed the owner has not seen.
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
  checkpoint. Continuation is automatic: an agent that reaches a checkpoint, 80 % of its token
  or time budget, or a usage-limit stop writes its handoff and returns; its dispatcher at once
  dispatches a fresh agent of the same role with a continue prompt built from the handoff,
  ledger and status page. Nothing continues from inherited memory, and the owner never
  `/clear`s and re-prompts.
- Merge only on all-green under an owner grant; the merge runs as its own command. The owner
  grants merges into a program's integration branch and into main. Two exceptions: a
  stream controller merges a group branch into its stream branch without a grant, after a
  clean review and green gates; and during a sync the program controller merges main into the
  integration branch without a grant when main is ahead of it. If that merge conflicts, the
  controller stops and asks the owner.
- After a merge, and at a program's close, the cleanup step removes the per-effort files from
  the tree (section 5); evidence cites them as `<sha>:<path>`.
- Every agent reaps its background jobs before reporting; the controller checks for orphans.
- Scripts that write files start with `set -eu` and assert they run inside their scratch path.
- Owner rules go into decisions, rolled into playbooks, CLAUDE.md or `architecture.md`; agent
  memory only points to them.
- Dispatch only inside the role/model map; the top tier only for `top_tier_roles`.

Rules marked `fixed` (owner-only classes, merge grants, the bypass block) cannot be
overridden. Any other rule is overridden only by a project decision with `overrides: SD-R<n>`;
SessionStart lists active overrides. Project rules live in `.strict-delivery/playbooks/`.

## 9. Context, docs and drift tooling

- `.strict-delivery/context.yml` lists required reads per session kind and role (for example:
  every session reads `in-force.md` and its handoff, a session inside a program also reads its
  program's status page, and a reviewer additionally reads the brief and the review playbook).
  SessionStart prints the list for the session kind; `python3 -m gates context <kind>` prints it
  on demand. The session kinds of programs are in the programs and streams design, section 10.
- Read receipts: a PostToolUse hook on Read appends a `{path, sha}` row to
  `receipts/<session>.yml` (git-ignored), a YAML file with a top-level `schema:` key and a
  `reads:` list. `gate_context` fails a dispatch or commit when a required read
  is missing or was read at a different content hash (strict); it warns only (light, standard).
- `gate_cites`: every `path:line` and `path#anchor` cite in tracked docs resolves at HEAD.
- `gate_drift`: status-page and handoff facts (branch heads, merged PRs, open blocks) match git and,
  when available, GitHub; pending decisions on a status page match open decision records; a
  stream branch behind `<program>/integration`, or an integration branch behind main, fails
  until a sync (a sync merges main into the integration branch, section 8); a block past
  `drift.estimate_factor` of its estimate is reported to the owner.
- `gate_index`: `docs/strict-delivery/INDEX.md` and the state indexes regenerate without error,
  and none of them is tracked (a tracked generated file fails).
- `gate_checkpoint`: handoff front matter matches its schema (plan, spec, branch, head, base,
  ledger, resume line, block, next task, findings in flight, open decisions, rulings, grant,
  live subagents), the block's own worktree is clean (other streams' worktrees may be dirty),
  the continuation handoff is present, and the ledger carries the `CHECKPOINT` line.
- `gate_cleanup` (after a merge and at a program's close; covers plain plans and programs): the
  merged plan's or closed program's per-effort files are gone from the tree, and every lasting
  decision they produced has a `landed_in` outside them.
- `gate_schema`: every framework file validates against the schema of its kind (appendix A);
  it runs on commit, in the Claude hooks, and in CI when CI is installed.

## 10. Agent management

Roles (config `roles`; defaults per profile; projects may add roles with their own prompt
block): program_controller, stream_controller, controller, implementer,
implementer_transcription, task_reviewer, final_reviewer, final_verifier, exception_reviewer,
audit_reviewer, audit_verifier, investigator. program_controller and stream_controller are
core roles at tier3 (section 11). Each role
names its prompt block, minimum tier, budget cap, whether it needs a brief, and which finding
states it may take.

Dispatch prompt grammar, checked by the PreToolUse Agent hook (`gate_dispatch`):
`## Role`, `## Brief`, `## Findings`, `## Claims`, `## Budget: tokens=<n> minutes=<n>`,
`## Model`, `## Report`, `## Strict block` (the role's prompt block, byte for byte),
`## Task`. A fork dispatch is refused. The tool's model must equal `## Model` and meet the
role's minimum tier; the top tier is allowed only for `top_tier_roles`.

Lifecycle: in a plain plan, the controller dispatches every role. In a program, only the
program session dispatches a program_controller, only a program_controller dispatches a
stream_controller, and stream controllers and their sub-controllers dispatch the workers. Fix
loop rounds 1-3 resume the implementer,
rounds 4-5 a fresh agent one tier up, then an owner question; every report starts with
`status: DONE|DONE_WITH_FINDINGS|NEEDS_DECISION|BLOCKED|DENIED`. A controller never returns
while its children run: questions and progress go up to its parent as messages, and answers
come down as decision records (section 11).

## 11. Programs and streams

Specified in full in
[`2026-10-31-programs-and-streams-design.md`](2026-10-31-programs-and-streams-design.md); in
brief:

- Small work is a plain plan run by one controller. A large effort is a program, split by a
  program plan into streams; each stream owns a disjoint set of files and runs its own blocks in
  its own worktrees under one stream_controller. A program_controller runs the program for the
  owner's lean program session.
- A stream never edits another stream's file: it raises a cross-stream request, which the
  program controller records and the owning stream implements.
- Each program keeps its status page, ownership map (`streams.yml`), requests and sync log in
  its program folder on its integration branch; only the program controller commits there,
  apart from the merges the owner grants.
- Branches: `<program>/integration`, stream branch `<program>/<stream>/main`, group branch
  `<program>/<stream>/<group>`. No branch is named `<program>` or `<program>/<stream>`, because
  git refuses a ref that is also another ref's directory; the stream id `integration` and the
  group id `main` are refused. Program, stream and group ids match `[a-z0-9][a-z0-9-]*` (no `/`,
  so a group can never be another group's directory). Worktrees mirror the branches in nested
  folders:
  `<worktrees>/<program>/<stream>/main` for a stream and `<worktrees>/<program>/<stream>/<group>`
  for a group. Dashes are allowed in ids.
- A stream controller merges each group branch into its stream branch after a clean review and
  green gates, with no owner grant; the owner grants merges into the integration branch and into
  main (section 8).
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
A profile is a preset of config keys. Any key may be changed per repository under
`overrides`, each naming the authorising owner decision.

## 13. Gate contract

Every gate: `check(args) -> Result`; prints `PASS id` or `FAIL id: reason` lines; `--json`;
exits 0 only when at least one line exists and every line passes; a missing input fails
(`<gate>.input`), an empty run fails (`<gate>.empty`); `--root` points at another tree.
`run_all` runs the gates the profile enables; a missing or raising gate fails. Hooks fail
closed on internal error.

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
  codes. It runs per finding (standard) or on every pin (strict), per section 12; light does
  not run it.
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

Semver tags and `CHANGELOG.md`. A release script bumps plugin.json, marketplace.json, the
template CI pin and the CLAUDE.md block version together. Every data file carries
`schema: <kind>/<version>` (appendix A). A shape change is a new schema version plus a
migration from the old version, which `upgrade` runs; every migration is tested from an old
fixture to the new version. Before 1.0, breaking changes are allowed with a migration; 1.0
freezes the config and state schemas.

## 16. The framework repository's own process

- The repository adopts itself at the strict profile with empty registers, and answers yes to
  both extras (local git hooks and the CI workflow). Owner: superbrobenji.
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
2. `gate_claims`, `gate_dispatch`, `run_all`, git hook shims and installer, self-adoption.

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
- Mutation transcripts: the first line is `<!-- schema: mutation-transcript/1 -->`.
- Read receipts: a YAML file with a top-level `schema:` key.

`gate_schema` validates every framework file against the schema of its kind, on commit, in the
Claude hooks, and in CI when CI is installed. A kind's schema file becomes required when the
gate or tool that produces that kind lands. `gate_schema` fails when a required kind has no
schema file, or when a schema file is not named in this table; kinds whose producer has not
landed are not checked. A kind's producer has landed when a gate or tool in the installed
framework version declares that kind in its `produces` list; `gate_schema` reads those lists.
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
| ledger | `gates/schemas/ledger.yml` | a plan ledger's line formats (`CHECKPOINT`, `Ruling:`, ...) |
| status | `gates/schemas/status.yml` | a program's status page table (section 11) |
| sync-log | `gates/schemas/sync-log.yml` | a program's sync log (section 11) |
| overview | `gates/schemas/overview.yml` | the sections of `INDEX.md` (section 5) |
| in-force | `gates/schemas/in-force.yml` | the generated `in-force.md` (section 7.4) |
| decision-index | `gates/schemas/decision-index.yml` | the generated `state/decisions/index.yml` (section 5) |
| finding-index | `gates/schemas/finding-index.yml` | the generated `state/findings/index.yml` (section 5) |
| mutation-transcript | `gates/schemas/mutation-transcript.yml` | one mutation transcript (section 13a) |
| review-report | `gates/schemas/review-report.yml` | one review report or review package (section 13a) |
| receipt | `gates/schemas/receipt.yml` | one session's read receipts (section 9) |
| claude-block | `gates/schemas/claude-block.yml` | the CLAUDE.md managed block (section 4) |
| gitignore-block | `gates/schemas/gitignore-block.yml` | the `.gitignore` managed block (section 5) |
