# strict-delivery framework: design

Date: 2026-10-31. Status: approved by the owner 2026-10-31. Owner: superbrobenji.

## 1. Purpose

A public, language- and project-agnostic Claude Code framework that brings the
"strict delivery" way of working (proven in the lap-timer repository) to any repository:
every change tracked, every claim verified, owner decisions logged and binding, agents
dispatched by role under a contract, and all of it enforced by gates that run locally,
in git hooks and in CI.

Success criteria:

- A developer installs the plugin, runs `/strict-delivery:init` in any repository (any
  language, or none), answers a few questions, and has a working, gated setup with
  `doctor` and `run_all` green.
- The rigor is selectable (light / standard / strict) without forking the framework.
- Enforcement does not depend on Claude: git hooks and CI gate collaborators who never
  installed the plugin.
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
  `comment_patterns` naming lap-timer plans, the owner handle.
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
    gate_register.py gate_claims.py gate_decisions.py gate_dispatch.py
    gate_streams.py gate_context.py gate_cites.py gate_drift.py gate_index.py gate_checkpoint.py
    gate_evidence.py
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
2. Ask for profile, owner handle (default: the gh login, else `git config user.name`), and
   model map (default from the profile).
3. Write `.strict-delivery/config.yml`, empty state directories, the CLAUDE.md managed block
   (between `<!-- strict-delivery:begin -->` and `<!-- strict-delivery:end -->`; the rest of
   CLAUDE.md is untouched), the CI workflow and the git hook shims.
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

`/strict-delivery:doctor` prints `PASS id` / `FAIL id: reason` lines: Python version, git
hooks installed and not foreign or bypassed, config valid, CLAUDE.md block matches the plugin
version, CI pin matches the plugin version, every register parses, the indexes regenerate without error, no generated file is tracked,
and the `.gitignore` managed block matches the plugin version.

`/strict-delivery:upgrade` moves the version pin, re-renders managed blocks and templates,
runs state schema migrations, optionally changes profile (`--profile`), and shows the diff
plus every check that newly fails.

Claude Code hooks (plugin `hooks/hooks.json`; active wherever the plugin is enabled, silent
no-ops in a repository without `.strict-delivery/config.yml`):

- SessionStart: status, open handoffs, active rule overrides, the context load list
  (section 9), and the instruction to invoke the strict-delivery skill.
- UserPromptSubmit: a one-line reminder (standard and strict).
- PreToolUse Agent: dispatch grammar, model tier, claims and decisions referenced
  (standard and strict).
- PreToolUse Bash: hook-bypass block (`--no-verify`, `-n`, `core.hooksPath`,
  `GIT_CONFIG_*`, HOME moves) and gated commit/push (all profiles).
- PreToolUse Edit/Write: surfaces in-force decisions whose `applies_to` matches the path,
  once per session per decision (section 7.4); records nothing, blocks nothing.
- PostToolUse Read: read receipts for the context contract (section 9).

Enforcement without Claude: the git pre-commit and pre-push hooks and the CI workflow run
the same gates. The CI workflow checks out `superbrobenji/strict-delivery` at the pinned tag
and runs `python3 -m gates run_all`. The Claude hooks are best-effort textual checks; git
hooks and CI are the enforcement.

Versioning: semver tags. The plugin version, the CLAUDE.md block version, the CI pin and
`framework_version` in config must agree; `doctor` and `run_all` fail when they do not.

## 5. Target repository layout

```
.strict-delivery/
  config.yml
  state/decisions/open/DEC-0001.yml
  state/decisions/resolved/DEC-0001-0050.yml
  state/decisions/index.yml           generated, git-ignored
  state/decisions/in-force.md         generated, git-ignored
  state/findings/open/F-0001.yml
  state/findings/resolved/F-0001-0050.yml
  state/findings/index.yml            generated, git-ignored
  state/claims/<doc-slug>.yml
  state/plans/<plan>/ledger.md handoff.md mutations/
                                      live plans only; pruned after merge
  program/status.md                   stream status and sync log
  program/context.yml                 required reads per session kind
  playbooks/                          project playbook (local rules)
  receipts/                           git-ignored read receipts
docs/strict-delivery/INDEX.md         generated map of specs, plans, state; git-ignored
docs/strict-delivery/specs/ plans/ reviews/
                                      specs, plans and review reports; namespaced so a
                                      project's own docs/ is never touched; a merged
                                      plan's review reports are pruned after merge
CLAUDE.md                             managed block + project text
.github/workflows/strict-delivery.yml
.git/hooks/pre-commit pre-push        shims
```

All paths are config keys with these defaults.

Lean tree. Only what CI, the git hooks or a collaborator needs is tracked: config,
registers, claims, the status page, context, playbooks, specs and plans, plus the workspace
and review reports of each live (unmerged) plan. The rest stays out:
- Generated files (state indexes, `in-force.md`, `INDEX.md`) are git-ignored and never
  committed. The SessionStart hook, `python3 -m gates index` and CI regenerate them before use.
- After a merge, the post-merge step deletes the merged plan's workspace
  (`state/plans/<plan>/`) and its review reports from the tree. They stay in git history.
  Evidence that cites them uses the form `<sha>:<path>`, resolved with `git cat-file` (and
  required to name a commit in the repository), never a file at HEAD.
- `init` writes the ignore entries between `# strict-delivery:begin` and
  `# strict-delivery:end` in `.gitignore`. The rest of `.gitignore` is untouched, and
  `doctor` checks the block.

## 6. Config and the YAML subset

`config.yml` keys (required unless marked):

- `framework_version`, `profile` (light | standard | strict), `owner.handle`.
- `commands`: `test`, `test_one` (a template holding `{id}`), `lint`, `build` (each a shell
  string or list; optional `mutate`). Gates run them and never know the language or the test
  framework (section 13a).
- `paths`: every path in section 5.
- `ids`: patterns and widths for decisions (`DEC-NNNN`), findings (`F-NNNN`), claims
  (`C-NNNN`).
- `state.shard_size` (default 50; fixed at init, changed only by an `upgrade` migration).
- `models.tiers`: tier name to model id (defaults: tier1 haiku, tier2 sonnet, tier3 opus,
  tier4 the top-tier model). `roles` (section 10). `top_tier_roles`, `top_tier_fallback`.
- `decision_classes.owner_only`: default list in section 7.1; projects add their own
  (for example `hardware`).
- `block.max_tasks`, `rulings.max_per_block`, `dispatch.max_prompt_chars`, budgets per role.
- `streams` (optional, section 11).
- `overrides`: profile keys changed for this repository; each entry names the owner decision
  that authorised it.

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

A decision is an owner question with at least two options and their cost. Only the owner
handle answers. Nothing may reference an unanswered decision id (`gate_decisions`).

Default owner-only classes: audit triage, spec-vs-code direction, plan scope, merge grants,
model and cost policy, closing an issue, narrowing or widening a finding's class, rule
overrides. Controller rulings: only inside an approved plan, only plan-vs-spec or task-vs-task
conflicts the spec settles, at most `rulings.max_per_block`, ledgered as
`Ruling: what -- why -- cost if wrong -- spec cite`.

Row fields: `id`, `class`, `question`, `options[{label, cost}]`, `asked_at`, `asked_by`,
`topics`, `applies_to` (path globs), `checked_against` (ids), `effect` (lasting | one-off),
`supersedes` (optional id), then on answer `answer`, `answered_at{at, by}`, `landed_in`
(required when `effect: lasting`). Grants use class `merge-grant` and name the plan.

### 7.2 Sharded storage

- `open/` holds one file per open record, named by id.
- `resolved/` holds shards by fixed id range of `shard_size`: `DEC-0137` lives in
  `resolved/DEC-0101-0150.yml`. The shard is computed from the id; lookup needs no index.
  Records answered out of order land in their range's shard; rows are sorted by id. A shard
  may be partial while ids in its range are open.
- Invariants (`gate_decisions`, `gate_register`): every id exists exactly once across
  `open/` and `resolved/`; ids have no gaps; a resolved row is immutable (a change is a new
  decision with `supersedes`); a record in `open/` is open; a row in `resolved/` is resolved.
- "Resolved" covers answered, withdrawn and superseded decisions; resolved rulings stay binding.
- Findings use the same scheme. `open/` holds states open, planned, in-progress,
  fixed-unpinned, pinned and deferred; `resolved/` holds closed and merged.
- Claims are grouped per cited document (`claims/<doc-slug>.yml`), because they go stale
  whenever the cited code moves and are read together with that document.

### 7.3 Tools

`python3 -m gates decisions ask|decide|find|withdraw`, `findings new|move`, `index`.
`decide` (owner only) writes the answer, moves the record into its shard and regenerates
the indexes in one step. Hand edits remain valid when the schema holds; gates check them.

### 7.4 How an agent knows a decision is already made

1. Docs carry the current truth, decisions carry the history. A lasting ruling is written into
   the spec, CLAUDE.md or a playbook; the decision row's `landed_in` cites that place and the
   doc line cites the decision id. Gate: `effect: lasting` requires `landed_in`, and the cite
   resolves.
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

Default session load: `in-force.md` and `open/`. Everything else via `find` or path surfacing.

## 8. Base playbook

Plugin-owned, versioned, read in place from the plugin (not copied; upgrades update it). The
CLAUDE.md managed block points at it.

```
playbook/rules.md      SD-R<n> rules: rule, why, enforcing gate (or "judgment"), profiles, fixed?
playbook/roles.md      roles, model tiers, dispatch contract, report contract
playbook/decisions.md  the decision log (section 7) in operating terms
playbook/sessions.md   session kinds, start order, blocks, checkpoints, handoffs
playbook/streams.md    multi-stream work
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
- One block per context, at most `block.max_tasks` tasks, clean tree at every checkpoint, stop
  for the owner's `/clear`.
- Merge only on all-green under an owner grant; the merge runs as its own command.
- After a merge, prune the merged plan's workspace and review reports from the tree; evidence
  cites them as `<sha>:<path>`.
- Every agent reaps its background jobs before reporting; the controller checks for orphans.
- Scripts that write files start with `set -eu` and assert they run inside their scratch path.
- Owner rules go into spec, CLAUDE.md or playbooks; agent memory only points to them.
- Dispatch only inside the role/model map; the top tier only for `top_tier_roles`.

Rules marked `fixed` (owner-only classes, merge grants, the bypass block) cannot be
overridden. Any other rule is overridden only by a project decision with `overrides: SD-R<n>`;
SessionStart lists active overrides. Project rules live in `.strict-delivery/playbooks/`.

## 9. Program tooling (context and docs)

- `program/context.yml` lists required reads per session kind (for example: every session
  reads `in-force.md`, the status page and its handoff; a reviewer additionally reads the brief and
  the review playbook). SessionStart prints the list for the session kind.
- Read receipts: a PostToolUse hook on Read appends `{session, path, sha}` to
  `receipts/` (git-ignored). `gate_context` fails a dispatch or commit when a required read
  is missing or was read at a different content hash (strict); it warns only (light, standard).
- `gate_cites`: every `path:line` and `path#anchor` cite in tracked docs resolves at HEAD.
- `gate_drift`: status-page and handoff facts (branch heads, merged PRs, open blocks) match git and,
  when available, GitHub.
- `gate_index`: `docs/strict-delivery/INDEX.md` and the state indexes regenerate without error,
  and none of them is tracked (a tracked generated file fails).
- `gate_checkpoint`: handoff front matter matches its schema (plan, spec, branch, head, base,
  ledger, resume line, block, next task, findings in flight, open decisions, rulings, grant,
  live subagents), the tree is clean, the ledger carries the `CHECKPOINT` line. After a merge it
  checks that the merged plan's workspace and review reports are gone from the tree.

## 10. Agent management

Roles (config `roles`; defaults per profile; projects may add roles with their own prompt
block): controller, implementer, implementer_transcription, task_reviewer, final_reviewer,
final_verifier, exception_reviewer, audit_reviewer, audit_verifier, investigator. Each role
names its prompt block, minimum tier, budget cap, whether it needs a brief, and which finding
states it may take.

Dispatch prompt grammar, checked by the PreToolUse Agent hook (`gate_dispatch`):
`## Role`, `## Brief`, `## Findings`, `## Claims`, `## Budget: tokens=<n> minutes=<n>`,
`## Model`, `## Report`, `## Strict block` (the role's prompt block, byte for byte),
`## Task`. A fork dispatch is refused. The tool's model must equal `## Model` and meet the
role's minimum tier; the top tier is allowed only for `top_tier_roles`.

Lifecycle: only a controller dispatches; fix loop rounds 1-3 resume the implementer, rounds
4-5 a fresh agent one tier up, then an owner question; every report starts with
`status: DONE|DONE_WITH_FINDINGS|NEEDS_DECISION|BLOCKED|DENIED`.

## 11. Streams

Optional. Config `streams`: id, decision and finding id ranges, owned paths, shared
append-only files. `gate_streams` checks that new ids fall inside the creating stream's range,
that a stream's commits touch only its owned paths plus shared files, and that shared files
are only appended to. The status page shows one row per stream. Sync sessions are their own session
kind in `context.yml`.

## 12. Profiles

| | light | standard | strict |
|---|---|---|---|
| register row per change | yes | yes | yes |
| decision log + owner-only gate | yes | yes | yes |
| claims register | no | yes | yes |
| dispatch grammar + model tiers | no | yes | yes |
| top-tier final verifier | no | no | yes |
| review package + mutation transcript | no | per finding | every pin |
| pre-commit | register, decisions | run_all | run_all + gate suite on every supported runtime |
| block size cap | none | 5 tasks | 3 tasks |
| context read receipts | advisory | advisory | enforced |
| streams | optional | optional | optional |
| bypass block | yes | yes | yes |

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
  violations (unanswered decision reference, `--no-verify`, missing owner, bad dispatch, shard
  invariant broken, a tracked generated index) each turn the run red. Every gate has a red case. A fixture
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
template CI pin and the CLAUDE.md block version together. Every state file carries
`schema: N`; every migration is tested from an old fixture to the new schema. Before 1.0,
breaking changes are allowed with a migration; 1.0 freezes the config and state schemas.

## 16. The framework repository's own process

- The repository adopts itself at the strict profile with empty registers. Owner:
  superbrobenji.
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

1. lib, YAML subset, sharded registers, `gate_register`, `gate_decisions`, decisions/findings
   tools (`ask`, `decide`, `find`, indexes, `in-force.md`).
2. `gate_claims`, `gate_dispatch`, `run_all`, git hook shims and installer, self-adoption.
3. Plugin: skill, role prompt blocks, base playbook, Claude Code hooks.
4. `init`, `doctor`, `upgrade`, templates, CI workflow template, stack detection, the
   no-overwrite rule and the superpowers document migration.
5. Program tooling (`gate_context`, receipts, `gate_cites`, `gate_drift`, `gate_index`) and
   streams (`gate_streams`).
6. `gate_checkpoint`, `gate_evidence` (section 13a), profile end-to-end tests, release 0.1.0.

## 18. Owner choices recorded in this design

Audience public; tiered profiles; plugin plus init command; depends on superpowers and
overrides it; Python standard library only; strict YAML subset; v0.1 covers the landed core
plus all docs and agent management, including program tooling designed here; lap-timer
migrates later; name `strict-delivery`; one file per open record and fixed-range shards of 50
for resolved records; registers ship empty, framework rules ship as the base playbook;
repository created public on GitHub.

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
