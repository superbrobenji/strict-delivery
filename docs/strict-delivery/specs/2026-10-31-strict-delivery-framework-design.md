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
- No hardcoded model names, owner handles, absolute or old paths (`docs/superpowers`,
  `tools/gates`, ...), test filename patterns or secrets in shipped code, tests, manifests,
  templates or prose, and no template-project rule in any wording. A forbidden-pattern list,
  home-directory paths and test filename globs included, checks the prose, manifests and
  templates line by line and again with line breaks read as spaces (owner answers DB-3,
  Q-B11-1..5, Q-RB-1 (a)). Code and tests are held to this by review; so are secrets.
  Exempt: the default model names of section 6 (`models.tiers`), code outside the list;
  the plugin manifest's `repository` field; and the plugin's own install line (section 4).

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
   or Gradle wrappers, Cargo, go, pyproject tool entries, ...) and offer them for `test`, `lint` and `build`; `test_one` is always asked and never proposed (owner answer DC-2, 2026-10-31).
   Detection invents nothing and only proposes; the owner
   confirms, edits or leaves out each command. A proposal promises only what a narrow,
   fail-closed reader can state from the file text, read under `--root` only (repository state
   is out of scope). There are seven sources. The Makefile is read from the first of `GNUmakefile`,
   `makefile` and `Makefile` that exists, in GNU make's order, its name matched by ASCII case
   only; every other source (`package.json`, `Cargo.toml`, `go.mod`, `mvnw`, `gradlew`,
   `pyproject.toml`) counts only under its exact spelling. npm scripts are always proposed as `npm run <name>`, and
   Makefile targets only from a file the whitelist accepts; names are ASCII only. An
   unsupported construct gives one problem and no proposal from that file; an unreadable
   root is an error naming it (owner answers DC-1, DC-3, DC-4, Q-C11-1, Q-C11rr-3 (a),
   Q-C11r4-0 (a), Q-C12-3 (a), Q-C12-4 (a), Q-C12r-2 (a)).
2. Ask for profile and model map (default from the profile's `defaults`, section 12). Ask the two extras' questions:
   local git hooks (pre-commit, pre-push), default **yes**; the GitHub Actions workflow,
   default **no**, since not every project can use it or may run it. Ask `merge.mode`: `host` (the owner merges pull requests on the host) or `controller` (the owner approves in chat and the controller runs `gh pr merge`) (owner answer Q-M1). Offer to configure host branch protection on the base branch (pull request required for everyone including administrators, merge-commit method only) (owner directive 2026-11-01).
3. Write `.strict-delivery/config.yml`, empty state directories, the CLAUDE.md managed block
   (between `<!-- strict-delivery:begin schema=claude-block/1 version=<framework version> -->`
   and `<!-- strict-delivery:end -->`; the rest of CLAUDE.md is untouched), and the extras
   answered yes: the git hook shims, the CI workflow. It also writes the subagent depth and concurrency limits the owner chooses into the project's `.claude/settings.json` `env` block, as `CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH` and `CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS` (section 10; measured limits in the programs and streams design, section 4.2), and only there: init writes no config `limits`.
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

`init`, `doctor` and `upgrade` take `--root` and never default it; a root equal to the plugin's
own directory or inside it, compared after resolving links, is refused. The Python tool is not interactive (`init questions`, `init plan
--answers F`, `init apply --answers F`); the questions are asked in chat by `commands/init.md`.
The answers file (kind `init-answers`) holds every question key and no unknown key; there is no default for a
missing one. `migrate` is the one exception: it is required when tracked superpowers documents exist, and refused otherwise. A generated file's header is its first line, or its second after a `#!` line. A
symlink at a target path or any parent of one is a conflict. A block inserted into an existing
file is appended at its end. `init` on a repository that has a config asks no config question and
never rewrites the config. State directories are created with no placeholder file
(controller rulings (4c), (4d), plan Block 4; owner answers Q-B4plan-1..7 (a)).

`/strict-delivery:doctor` prints `PASS id` / `FAIL id: reason` lines: Python version, which
extras are installed and which are not, git hooks (when installed) not foreign or bypassed,
config valid, CLAUDE.md block matches the plugin version, CI pin (when installed) matches the
plugin version, every register parses, the indexes regenerate without error, no generated file
is tracked, and the `.gitignore` managed block matches the plugin version, and whether the base branch is protected on the host (pull request required for everyone including administrators, merge-commit method only); with a GitHub remote it fails when the host cannot be read, and with no GitHub remote it is not checked. A project with
neither extra installed is gated only inside Claude sessions, and `doctor` says so. `doctor` writes nothing: it renders the indexes in memory.

`/strict-delivery:upgrade` moves the version pin, re-renders managed blocks and templates,
runs state schema migrations, optionally changes profile (`--profile`), adds or removes either
extra, and shows the diff plus every check that newly fails. It never removes a plain `.gitignore` line outside the block (it reports duplicates as notes), and in a config with comment lines it changes only the `schema:`, `framework_version:` and `profile:` lines; any other migration of a commented config fails and is done by hand (controller ruling (4e)).

Claude Code hooks (plugin `hooks/hooks.json`; active wherever the plugin is enabled, silent
no-ops in a repository without `.strict-delivery/config.yml`). A refusal is exit status 2 with the reason on stderr; a pass never prints `permissionDecision: "allow"`; every PreToolUse entry sets `"onFailure": "block"`, so a timeout or a failed launch also refuses (controller ruling 3a). The owner has a way out of every refusal, and the refusal's FAIL text names it: `!`-prefixed commands still run, a corrupt session file is moved aside (section 5), and the owner disables the plugin with `/plugin` until a fix merges. A review of a hook change checks that each refusal states its way out. The hooks:

- SessionStart: status, open handoffs, at every source the resume instruction of each handoff and live program (section 9), active rule overrides, the context load list (section 9), and the instruction to invoke the strict-delivery skill.
- UserPromptSubmit: a one-line reminder (standard and strict).
- PreToolUse Agent: dispatch grammar, model tier, claims and decisions referenced
  (standard and strict, and every profile while a program is live). The hook supplies the dispatcher's role and depth and the live subagent counts from its session state, and refuses the dispatch when it cannot determine them.
- PreToolUse Bash (all profiles): the hook-bypass block (`--no-verify` and its abbreviations, `-n` on `git commit`, `core.hooksPath` in any case and `git -c`/`--config-env`, `GIT_CONFIG_*`, moves of `HOME` or `XDG_CONFIG_HOME`); gated commit/push; refusal of `decisions decide` and `decisions withdraw` from any subagent; the main session may run them to record the owner's exact words (section 7.1); refusal of a commit, push or merge aimed at another repository or index (`--git-dir`, `--work-tree`, `GIT_DIR`, `GIT_WORK_TREE`, `GIT_INDEX_FILE`); refusal of any git write (commit, push, merge, pull, rebase, cherry-pick, revert, am, reset, update-ref, tag, stash, worktree, and branch, checkout or switch with a create, move, copy, delete or force option) whose target worktree (named by `git -C <dir>` or `cd <dir> &&`, else the caller's `cwd`) is not one the caller may write in: for a subagent, the one worktree its dispatch named on a `worktree:` line of `## Task`, checked at dispatch against the dispatcher's own (with none: the main checkout when no program is live; no worktree at all for a controller in a live program, whose worker dispatches must name one); for the main session, its own checkout and, while a program is live, the worktrees on that program's status page and the one holding its integration branch. The hook checks only that the named worktree is the one the dispatch named, not that the dispatcher chose rightly; a subagent may commit, push or move only the branch its bound worktree had checked out when the dispatch was recorded: any git write while that worktree is on another branch is refused, as are a switch or checkout to another branch or commit, creating a branch (`git branch <new>`, `checkout -b/-B`, `switch -c/-C`), `branch -f/-m/-M/-c/-C/-d/-D` of another branch, a push to any other branch or a tag, `update-ref`, `tag`, a fetch into a local branch and `git worktree add`, except that a stream controller recorded on `<program>/<stream>/main` may create a group branch only as `git worktree add -b <program>/<stream>/<group> <path>`; and, since the base branch is protected (section 8): an agent's push to the base branch in any refspec form (`--all`, `--mirror`, `--prune` and wildcard refspecs included); while the base branch is checked out, an agent's `git commit`, `merge`, `pull`, `rebase`, `cherry-pick`, `revert`, `am` or `reset`, except a fast-forward of it to its own remote-tracking branch; from any branch, an update of the base branch by `git branch -f/-m/-M/-c/-C/-d/-D`, `checkout -B`, `switch -C`, `update-ref` or a `fetch` refspec; `gh pr merge` unless `merge.mode` is `controller` and the command carries `--merge` and `--match-head-commit <sha>` and no other merge option; every `gh api` call to the REST pull-request merge endpoint (any method or spelling) and every `gh api` call that is not a read (a method other than GET, a field or input, or a GraphQL mutation); `gh repo sync` and `gh alias set`/`import`. The checks are text checks that fail closed; a script file whose command text names none of these words is not recognised.
- PreToolUse Edit/Write: surfaces in-force decisions whose `applies_to` matches the path,
  once per session per decision (section 7.4); refuses any agent Edit or Write of a path under `paths.decisions`, since only the `decisions` tool, and `upgrade`'s registered migrations, write decision records (owner answer Q-16 (a)); records nothing else and blocks nothing else.
- PostToolUse Read: read receipts for the context contract (section 9).
- SubagentStop: ends the live record of a finished subagent, so the PreToolUse Agent hook's counts follow the live records; refuses nothing. The counts are approximate, a measured fact: a subagent interrupted with no SubagentStop record stays counted until the next SessionStart that resets the store (sources `startup`, `resume`, `fork` or unknown; `clear` and `compact` keep it). They are advisory where exactness is impossible (owner answer Q-X37 (a), 2026-11-07): `gate_dispatch`'s concurrency and child-cap checks still use them, failing closed, and nothing compares them with a handoff's `live_subagents` or presents them as exact (owner answer Q-RD-4 (a), 2026-11-07).

Enforcement: the framework enforces through what the plugin installs, the Claude Code hooks
(they run the gates before a commit or push an agent makes, or, when the git hooks are installed and current, leave the gates to them and make sure they run; and check dispatches, edits and
reads) and the skill's rules. The two extras extend the same gates to commits made outside
Claude: the git pre-commit and pre-push hooks, and the CI workflow, which checks out the framework repository named in the plugin manifest's `repository` at the pinned release tag (before the first release, at the installed framework's commit sha), and runs `python3 -m gates run_all`; on pull requests it also runs, on a checkout of the PR's head sha, `check streams --branch <head>` and, for a `cleanup/<plan>` head, `check cleanup`. Every workflow `uses:` is pinned to a full commit sha (owner answer Q-B2plan-20 (a)). The git pre-commit hook runs `run_all`, then, under strict, `commands.test` (a string with `sh -c`, a list as one argv; unset fails); pre-push refuses unless the working tree has no tracked change and every pushed sha equals `HEAD` (owner answers Q-B2plan-11 (a), Q-B2plan-12 (a)). `githooks install` refuses while `core.hooksPath` is set or a hook file is foreign, and writes nothing (controller ruling, plan Block 2).

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
  repository), never a file at HEAD; its path holds no `#`, and a cite's anchor holds no `#` (owner answer Q-1b1r-4 (b)). A finding's evidence entry is a commit sha, a
  `<sha>:<path>`, or a plain path tracked at HEAD that lies outside every per-effort path and
  outside the findings directory, open findings included (owner answers 2026-10-31).
- Ignored, never committed: generated files (state indexes, `in-force.md`, `INDEX.md`), read
  receipts, agent scratch workspaces. The Claude Code hooks keep per-session state (live subagents, worktree bindings, decisions already surfaced) outside the repository, in the plugin's data directory; an unreadable state file is moved aside, to `<id>.yml.corrupt-<UTC>`, at the next session start with source `startup`, `resume` or `fork`, which also resets the live subagent records; a start with `clear` or `compact` keeps the state and, for an unreadable file, prints a FAIL line naming the recovery path (controller ruling 3a). The SessionStart hook, `python3 -m gates index` and CI
  (when installed) regenerate the generated files before use.
- `init` writes the ignore entries between
  `# strict-delivery:begin schema=gitignore-block/1 version=<framework version>` and
  `# strict-delivery:end` in `.gitignore`. The rest of `.gitignore` is untouched, and
  `doctor` checks the block.

## 6. Config and the YAML subset

`config.yml` keys. Only `schema`, `framework_version` and `profile` are required in the file;
every other key may be omitted. A missing file fails `missing; run /strict-delivery:init`; an unknown key in any mapping the reader reads is refused (extra `models.tiers` names are kept), and a mapping default given a non-mapping is refused (owner answers Q-1a2-1..8; the last, a controller call, fail closed). The keys with a fixed default are `paths`, `ids`,
`models.tiers`, `decision_classes.owner_only`, `drift.estimate_factor_pct`, `base_branch`, `decisions.scan`, `merge.mode`, `reviews.small` and `context`, as listed below; a profile presets some others, such as the block size cap
(section 12). A key whose reader has not landed yet is optional in `config/1` and becomes
required, if at all, in a later schema version with a migration (owner answer 2026-10-31).

- `framework_version` (a non-empty string), `profile` (light | standard | strict).
- `commands`: `test`, `test_one` (a template holding `{id}`), `lint`, `build` (each a shell
  string or list; optional `mutate`). Gates run them and never know the language or the test
  framework (section 13a). A string runs with `sh -c`, a list as one argv with no shell (owner answer Q-B2plan-11 (a)).
- `paths`: every path in section 5; each value a non-empty, normalised, repo-relative string: no leading `/`, no `..` segment, not `.`, no non-printable character, printable read from section 14's frozen code-point table (owner answers Q-1a2r-3, Q-1a-fin-2 (a), Q-RCp-2 (a)).
- `ids`: the id format of section 7.2 (`<PREFIX>-<YYYYMMDD>-<xxxx>`, prefixes `DEC`, `F`,
  `C`, `R`): exactly the four prefix keys, each `[A-Z]+`, all distinct (controller ruling R-rev5-1).
- `models.tiers`: tier name to model id (defaults: tier1 haiku, tier2 sonnet, tier3 opus;
  tier4 has no default; a project sets it to raise the top tier). `roles` (section 10).
  `top_tier_roles`, `top_tier_fallback`: with `tier4` unset, the `top_tier_roles` run at the
  tier `top_tier_fallback` names, default `tier3`; a model named by two tiers fails (owner
  answers Q-B2plan-17 (a) as amended by Q-B2plan-21).
- `decision_classes.owner_only`: default list in section 7.1; projects add their own
  (for example `hardware`). The project's list is added to the defaults, a union: a project
  cannot drop a default class (owner answer 2026-10-31).
- `block.max_tasks`, `rulings.max_per_block`, `dispatch.max_prompt_chars`, budgets per role.
- `drift.estimate_factor_pct` (optional, default 150, an integer percent: the YAML subset has
  no floats; `gate_drift`, section 9).
- `base_branch` (optional, default `main`): the base branch. Gates default `--base` to it; they
  check deletions and immutability against the merge base with it and id collisions against its
  tip (section 7.2; owner answer 2026-10-31). A value holding a run of more than 40 hex digits is refused (owner answer Q-1a2r-8 (a)).
- `decisions.scan` (optional, default `docs/**`, `CLAUDE.md`, `.strict-delivery/playbooks/**`):
  the tracked files `gate_decisions` scans for references to unanswered decision ids; files under
  the state directory are never scanned (section 7.1; owner answer 2026-10-31).
- `merge.mode` (optional, default `host`; in `config/2`, owner answers Q-M1 and Q-Pplan-14 (a)): who presses merge on an approved pull request: `host` (the owner, on the host) or `controller` (the controller, after the owner's approval in chat, section 8).
- `escape_cost` (optional, unset by default; in `config/2`, owner answer Q-B6plan-3 (a)): per counted severity (`CRITICAL`, `HIGH`, `MEDIUM`, `LOW`), the relative cost of an escaped defect in fix rounds; read only by `loopstats`.
- `reviews.small` (optional; in `config/2`, owner answers Q-COST-1 and Q-COST-2 (a), 2026-11-02): the small re-review thresholds of section 10: `max_lines` (default 150), `max_files` (default 4), `exclude` (globs; default `.strict-delivery/**`, `.github/workflows/**`, `.claude/**`, `CLAUDE.md`, the framework's own wiring in a target project, owner answer Q-RD-11 (b); a set list replaces the default), `tier` (default `tier2`, the tier a qualifying re-review may run at, owner answer Q-RD-10 (b)). Each threshold is an integer of at least 1.
- `context.max_lines`, `context.max_bytes` (optional; in `config/2`, owner answer Q-CAT-1): the largest chunk `python3 -m gates context` prints for one required read (section 9); defaults 2000 lines and 100000 bytes (owner answer Q-RD-8 (a)).
- `limits` (optional; in `config/2`, owner answer Q-H2 (a)): `max_children.<role>`, the most
  children a dispatcher of that role runs at once, keyed by the dispatcher's role, `session` an
  allowed key (owner answer Q-B2plan-23 (a)); `max_depth`, the deepest subagent level, the
  main session at level 0; `max_concurrent`, the most subagents running at once in one
  session; each an integer of at least 1. A limit is set in config only, either directly under
  `limits` or under `overrides`; a playbook rule or lasting decision tightens `max_children` only
  through `overrides`, the entry naming the authorising decision. An absent limit is no cap, and the effective limit is the lower of config
  and the measured Claude Code limit (section 10). The config reader checks the shape only; a
  `max_children` key that names no role fails at dispatch (owner answer Q-2c2-1 (a)).
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
Also refused: a scalar on the line after `key:` or `-`, multi-line flow sequences and
multi-line quoted scalars; a tab after `:` or `- `, or in the whitespace after them; a
block-scalar header `|`/`|-` followed by anything but spaces, a tab, a ` #` comment or the end
of the line. ` #` starts a comment outside quoted scalars and block-scalar bodies. Non-string
input raises `TypeError`; the emitter writes control characters as `\u` escapes; error
wording is not a contract (owner answers D1, D6, D7, D9, U1, U2, Q-yamlsub-1).
The reader stats a path and refuses anything but a regular file, opens it non-blocking and
read-only and closes it on every path; it strips one leading BOM, turns CRLF into LF and
refuses a bare CR; an `OSError`, `ValueError` or `TypeError` (a raising `__fspath__` included)
becomes the reader's error, and `BaseException` is not caught. Markdown is read raw (no BOM
strip). The reader follows a symlink to a regular file; `gate_schema` reads a schema's
`{path: ...}` file through a symlink, but refuses a symlink, directory or other entry that a
`{dir, glob}` match finds, never following it (owner answers 2026-10-31 (2), Q-1b1-3).
The emitter writes a canonical form so gate writes produce minimal diffs; parse(emit(x)) == x
for every value the parser accepts, and `emit(x)` is byte-identical on every supported interpreter. The parser is tested through its production path, `load` of a file written by `emit`, against an independent expected value: a fuzz generator builds each document together with its expected value (section 8, input-domain method).

## 7. Decisions, findings, claims

### 7.1 Decision log

A decision is an owner question with at least two options and their cost, one of them recommended (except in class `model-policy`, below). The owner is the
human driving the effort; there is no global owner setting. Answers and withdrawals come only
from that human: the PreToolUse Bash hook refuses `decisions decide` and `decisions withdraw`
from any subagent; the human runs them (`!` prefix), or the main session (the program session, or the controller's session in a plain plan) records the owner's exact words. Each answer
records the git identity (`git config user.email`) as `answered_at.by`. A hand edit of a record
cannot be told apart from a tool write; it is valid when the schema holds, and pull-request review is where a human checks who answered. Agents cannot hand-edit records: the PreToolUse Edit/Write hook refuses any agent Edit or Write under `paths.decisions` (section 4; owner answer Q-16 (a)). Nothing may reference an unanswered decision id
(`gate_decisions`, over the tracked files matching `decisions.scan`, section 6; the state
directory, where handoffs, status pages and records list open ids by design, is not scanned).

Default owner-only classes, with their config slugs: audit triage (`triage`), spec-vs-code direction (`spec-direction`), plan scope (`scope`), merge grants (`merge-grant`),
model and cost policy (`model-policy`), closing an issue (`issue-close`), narrowing or widening a finding's class (`finding-class`), rule
overrides (`rule-override`), profile overrides (`profile-override`), and the program classes `program-create`, `stream-ownership`, `stream-merge`, `request-dispute` and `program-close` (programs and streams design, section 13; owner answers Q-U1 (a), Q-B23-1 (a)). Controller
rulings: only inside an
approved plan, only plan-vs-spec or task-vs-task conflicts the spec settles, at most
`rulings.max_per_block`, ledgered as `Ruling: what -- why -- cost if wrong -- spec cite`.
Owner question ids are `Q-<scope>-<n>`. A plan-vs-spec or task-vs-task conflict that the
spec settles is a `Ruling:` line, never a question; the controller corrects a plan-vs-spec
conflict to the spec and ledgers it (owner answer Q-LT-1 (a)). Any other open point is an
owner question. A point the spec, the plan or an owner answer already states is applied as written and not
asked (search before asking, section 7.4). A batch is kept small and recommends the
fail-closed option where one exists. Task text states the recommended option and is edited
before dispatch when the answer differs; once a question is answered the plan states only the
chosen option.

Row fields: `id`, `status` (open | answered | withdrawn), `class`, `question`,
`options[{label, cost}]`, `recommended` and `source` (from `decision/2`, optional), `asked_at`, `asked_by`, `topics`, `applies_to` (path globs),
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
a withdrawn one is ignored, and `ask` refuses a second (owner answer 2026-10-31). A reference error names the id of the row carrying the field (Q-1b2-2 (a)). A row that names itself in `supersedes` supersedes nothing and its tree fails (Q-1b2r-2 (a)); a withdrawn superseder is checked only for a missing target, itself and cycles (Q-1b2-3 (a)); two answered superseders of one id are a fork, an error. Following a chain to the current ruling returns an unknown id unchanged and stops at the first repeat (Q-1b2-4 (a)). A record whose `status` is malformed counts as resolved (fail closed). The decision schema (appendix A) holds the exact shape. Grants use class
`merge-grant` and name the plan; a grant inside a program also names the program and the
stream, as the fields `plan`, `program` and `stream` (`plan` required on a grant; `program` and
`stream` together or not at all; none of the three on any other class; owner answer 2026-10-31). A pull-request merge approval is not a decision record (owner answer Q-15 (a), 2026-11-01): in `controller` mode the owner approves in chat naming the PR and its head sha, in `host` mode the owner's merge on the host is the approval, and the plan's ledger records each merge as a `MERGED` line (who merged, when, PR, head sha, merge commit, the approval). `merge-grant` records and their fields stay valid for records already written.

From `decision/2` a record may carry `recommended`, the label of exactly one of its options, and `source`, the report or handoff the question came from; `decisions ask` requires `recommended` for every class except `model-policy` (model and cost policy), whose questions carry none, and records migrated from `decision/1` have neither. The floor stays at least two options: one recommended plus at least one alternative, with no cap. Before a question is asked, the search before asking of section 7.4 runs; a question found answered is not asked. A printed question shows, in order: id, class, the question, the recommended option with its cost, every alternative with its cost, effect, topics and `applies_to`; the tool-only fields (`schema`, `status`, `asked_at`, `asked_by`, `checked_against`, `supersedes`, `source`) are not printed. Questions are asked as one batch at the next stop, never one at a time. `python3 -m gates decisions batch --since <sha>` prints the open records of the working tree of `--root`: the records whose files did not exist at the cut-off commit under `New`, every other open record under `Also open`, each given whole; within each section, one header per `source`. A cut-off that is not an ancestor of `HEAD`, or none, makes every open record new. The session commits the new records, prints the batch and records that commit as the next cut-off in its handoff (`batch_cut`; for a program, on the status page); printing writes nothing, so the batch never depends on the session's memory. An agent restarts as soon as every question with its `source` is answered, while others stay open (programs and streams design, section 4.1): a returned worker or reviewer is replaced by a fresh agent of the same role whose brief carries the answers printed by `decisions batch --answered --source <path>`; a live controller is told to continue; a controller that handed off is rebuilt by `continue`. Only the session writes decision records (owner answers 2026-11-02 and 2026-11-07).

### 7.2 Storage and ids

- Ids: `<PREFIX>-<YYYYMMDD>-<xxxx>`: prefix `DEC` (decision), `F` (finding), `C` (claim) or
  `R` (cross-stream request); the UTC creation date; four characters from the lowercase base32
  alphabet without `0`, `1`, `l`, `o`, drawn at random. Example `DEC-20261031-k3f9`. The date
  must be a valid calendar date and is never compared with the clock (owner answer
  2026-10-31). No person's name or handle appears in any id. Within one program only the program controller (the program session by default, programs design section 4) mints ids; a plain plan's controller mints its own.
- One file per record, named by id. Decisions and findings carry `status`; a record stays in
  its folder whatever its status, and no status has a folder of its own. A register folder
  holds only `<id>.yml`, `index.yml` and `in-force.md`; a symlink on any component of the
  register path is refused in load, create and replace. Ids are checked before the disk is
  touched (a `str` subclass is refused); a record is created exclusively and replaced through
  a temporary file and `os.replace`; the check-then-write symlink race is accepted, since the
  next load refuses. Running out of ids for a prefix and date is an error naming both. Records
  are compared by parsed, type-strict content (`1`, `true` and `1.0` differ; key order does not
  count); a tree row is unchanged when it equals the base row before or after migration, and
  the same row on both sides (a cherry-pick) is no collision. Base-side entries that are not
  records are ignored; a base record that does not parse is refused (owner answers Q-1a3-1..5,
  Q-1a3r-1..3, Q-1a3rr-1, Q-2a1-2 (a)).
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
  `paths.reviews` whose first line is a `review-report` schema line (one trailing `\r`
  stripped first, owner answer Q-1c2-1 (a)), and fails when a finding id in it, matched as a
  whole token, names no finding record (owner answer 2026-10-31; whole-token match, owner-approved call I6).
- No-delete rule: a decision, open finding or claim file present on the base branch may not be
  deleted by a branch. A claim file deleted outside the cleanup step is the one exception: it may be deleted only in a change where its `document`, as at the merge base, is also gone, and removing one claim id from a kept claim file fails (owner answer Q-B2plan-5 (a), 2026-11-01, on deleting claims before `gate_cleanup`). Otherwise the only deletions allowed are the cleanup step's (resolved findings and
  per-effort files, section 5). Until `gate_cleanup` lands (programs block), `gate_register`
  lets a branch delete a resolved finding only when an answered `merge-grant` names its
  `resolved_by` plan; the merge-commit check arrives with `gate_cleanup` (owner answer 2026-10-31). From block 1c on, merge approvals are not decision records (owner answer Q-15 (a), 2026-11-01), and from the programs block on, where `MERGED` ledger lines begin (programs Task P1.2), the deletion proof is the plan's final `MERGED` ledger line checked against git, as below.
- "Resolved" covers answered, withdrawn and superseded decisions; resolved decisions are
  permanent, and resolved rulings stay binding.
- Findings: an open finding (status open, planned, in-progress, fixed-unpinned, pinned or
  deferred) is global and permanent until resolved, even after the effort that raised it
  closes; ownership then passes to an issue or roadmap item. A resolved finding (status closed
  or merged) stays in `state/findings/`, names the plan that resolved it
  (`resolved_by: <plan>`) and is cleaned with that effort: the cleanup may delete it only when the plan's ledger records its final pull-request merge (`MERGED ... final=yes`) and that merge commit is on the target branch's first-parent history with the recorded head as its second parent; the cleanup is its own pull request (owner answers Q-15 (a), Q-Pplan-9 (a)). Finding fields: `id`, `status`, `source`, `severity` (CRITICAL | HIGH | MEDIUM | LOW | INFO), `class`, `siblings`, `cites[{file, lines, sha}]`, `repro`, `owner{kind: plan | issue | roadmap, plan, task, number}`, `pin{test, transcript}`, `ruling`, `evidence`, `history[{status, sha, by}]`, then the optional `parent`, `resolved_by` (on closed and merged only) and `review_round`, `caused_by_change`, `dimension` (section 10). A deferred finding's `ruling` may be a superseded but answered decision (Q-1b3-1 (a)), never one of class `merge-grant` (Q-1b3r-1 (b)). On a resolved row, the parent link is checked only for self-reference and cycles (Q-1b3-2 (a)), and plain-path evidence is checked for existence only when the row is new or differs from its merge-base version; sha-pinned evidence is always checked (Q-1b3-3 (b)).
- Claims are grouped per cited document (`claims/<doc-slug>.yml`), because they go stale
  whenever the cited code moves and are read together with that document; they are cleaned
  with that document. The slug is the document path without `.md`, with `/` as `--`; a
  document is a `.md` path with no `--` (owner answers Q-B2plan-2 (a), Q-2a2-1 (a)). Each cite
  records the blob id of its file, and a claim is fresh while every cite's blob matches the file
  being committed (Q-B2plan-4 (a)). `gate_claims` never runs a claim's commands: it checks that
  both are recorded, that the cites resolve and that the claim is fresh; claims carry no
  expected-outcome fields (controller ruling, plan Block 2).

### 7.3 Tools

`python3 -m gates decisions ask|decide|find|withdraw|batch`, `findings new|move`, `claims add|verify` (owner answer Q-B2plan-6 (a)), `index`.
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
   PreToolUse hook prints matching in-force decisions once per session. A topic matches a
   `topics` entry equal to it after `casefold` (Q-1b2-5 (a)); `applies_to` globs match with
   `fnmatchcase`, so `*` crosses `/` and `**/` needs a directory level (Q-1b2-6 (a)).
3. `decisions find <terms> [--path P] [--topic T]` returns in-force decisions by default and
   follows `supersedes` chains to the current ruling, following every superseded match
   (Q-1b2r-1 (b)); with `--all` it returns every match as itself, with no replacement
   (Q-1b2-7 (a)). Skill rule: search before asking.
4. `decisions ask` runs `find` on the new question's topics, paths and keywords and prints
   candidates; the row must carry `checked_against`. Whether a candidate is a true duplicate
   is reviewer judgment.
5. `in-force.md`, generated: one table row per lasting decision still in effect (id, topic,
   rule summary, landed_in); the rule summary is the decision's `rule` field. Grants, one-off
   triage and superseded rows are excluded. In the generated files, index containers are lists
   sorted by id; a cell's `|` is escaped; `\r\n`, `\r` and `\n` render as `<br>` in
   `in-force.md` and as a space in `INDEX.md`; links are relative to the index file's directory.
   A source record that fails its schema, or a duplicate id, makes the render fail naming the
   first bad file and its problem, and nothing is written (owner answers Q-1c3-1..3 (a)).

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
  committed the owner has not seen. Plan in full before code (owner answer Q-PL-1 (a), 2026-11-02): every block of a spec and its plan is planned in full (tasks, files, interfaces, input-domain dimensions, tests) before any code is written, and every test step of a plan carries its assertions as code (owner answer Q-plan-6 (b), 2026-10-31); no block whose plan is only an outline may start implementation. The last planning step is the stream breakdown plan, `<paths.plan_state>/<plan>/breakdown.yml` (kind `breakdown/1`, appendix A): the streams with their owned paths, the tasks of each stream, the dependency edges from task to task, each stream's unblock condition, the parallel groups (each within the concurrency limit), the concurrency and depth limits it assumes, the tasks already done, and, for ownership that moves during a program, stream periods and path windows (owner answers Q-BD-7 (a), Q-BDr2-1 (a)). Streams run as they unblock. Each kind of change has its superpowers skill: a new rule, feature or format with no settled design goes through superpowers:brainstorming to an owner-approved design and then a spec edit; a plan change goes through superpowers:writing-plans against the spec; execution goes through superpowers:subagent-driven-development or superpowers:executing-plans under the strict prompt blocks; a controller that has not invoked the skill for the change in its current context does not dispatch a writer for it (owner answer Q-PCR-5 (a), 2026-11-02). When a program starts, `program create` refuses a plan with an outline-only block (a block section without task headings, or a pointer to a section that does not exist or holds none), a plan without the expected block structure, or a missing or invalid breakdown: one whose `max_concurrent` or `max_depth` exceeds the effective limit (the lower of config `limits` and the measured Claude Code limits, section 10), or whose streams and owned paths differ from the program's `streams.yml` (programs and streams design, section 5).
- Zero bugs: a change's own bug makes it incomplete; a minor is a real defect, fixed in the fix round,
  never deferred; a cosmetic item (a dash, a space, wrapping, wording with no change of meaning) is not a finding and earns no fix round: the reviewer marks it cosmetic, and it is noted, folded into the next real edit, or dropped; a document re-review runs in full until a clean pass (owner answers 2026-10-31 and Q-CAT-8, 2026-11-02); an unrelated bug gets a register row and an owner.
- A deleted test is restored and fixed; dropping a test is never offered as a fix.
- A class of findings is an epic with child rows; signed off only when every child is resolved
  and the whole class is tested and reviewed.
- Findings that keep arriving round after round are a process defect: stop fixing, find where
  they entered and why reviews missed them, bring process changes to the owner.
- Reviewers execute every claim and re-run every gate themselves, on a clean copy of the reviewed head: a `git archive` export or a detached worktree, with `pwd -P` and `git rev-parse --show-toplevel` checked inside it and no tracked file flagged assume-unchanged or skip-worktree (`git ls-files -v`). Before a review the controller trial-merges the branch with the base (`git merge-tree`) and runs the full suite on the merged tree; the verifier runs the suite with `GIT_*`, `TZ` and `LANG` polluted.
- Pinned means a production-path test plus a mutation transcript. A mutation review writes one mutant per changed condition and runs each on a fresh `git archive` export or private clone, never the checkout, after a syntax check of the mutated file, in three runs (present, mutant, restored); every surviving mutant is argued equivalent or is a finding, and a mutant count with no script or transcript on disk is a finding.
- One block per agent context, at most `block.max_tasks` tasks, clean worktree at every
  checkpoint. `gate_checkpoint` counts a block's tasks both as its plan's `Task <block>.<n>` headings and as the distinct `<block>.<n>` task tokens of its ledger's `CHECKPOINT` lines. Continuation is automatic: an agent that reaches a checkpoint, 80 % of its token
  or time budget, or a usage-limit stop writes its handoff and returns; its dispatcher at once
  dispatches a fresh agent of the same role with a continue prompt built from the handoff,
  ledger and status page. Nothing continues from inherited memory, and the owner never
  `/clear`s and re-prompts. A checkpoint rewrites the handoff with the fields of section 9, commits handoff and ledger after the commit gate and writes the `CHECKPOINT` line. A statement that a handoff is complete carries the output of `git status --porcelain --untracked-files=all`, the handoff field check (`gate_checkpoint`) and the background-job check below; "safe to clear" is never said, since nothing is cleared at any level.
- The base branch is protected: nothing is pushed or merged to it directly. Every change reaches it by a pull request on all-green, merged by merge commit on the owner's approval: in `controller` mode the owner approves in chat naming the PR and its head sha and the controller runs `gh pr merge --merge --match-head-commit <sha>`; in `host` mode the owner merges on the host. The plan's ledger records each merge as a `MERGED` line; merge approvals are not decision records (owner directive 2026-11-01; owner answer Q-15 (a)). Work branches (stream, block and group branches) are pushed at every checkpoint (`gate_checkpoint`'s `checkpoint.pushed`), and the program controller pushes `<program>/integration` after every commit it makes there. Two merges need no approval: a stream controller merges a group branch into its stream branch after a clean review and green gates; and during a sync the program controller merges main into the integration branch and into each stream branch behind it, never rebasing (owner answer Q-Pplan-5 (a)). If such a merge conflicts, the controller stops and asks the owner.
- After a merge, and at a program's close, the cleanup step removes the per-effort files from the tree in a pull request of its own (section 5); evidence cites them as `<sha>:<path>`.
- Every agent reaps its background jobs before reporting: a poll loop has a bounded timeout and never matches its own command line; a job no longer needed is stopped with TaskStop, never by pattern-killing processes; the report lists each background job id as finished or stopped. The controller checks for orphans: before ledgering an agent's result it lists the agent's background job ids from its transcript, and each has a completion record or is stopped with TaskStop and the stop is ledgered; a notice that an agent is waiting on its own background work leaves its task open.
- Scripts that write files start with `set -eu` and assert they run inside their scratch path. Every agent works in its own `mktemp -d` scratch path, never a shared scratchpad, and never runs `git stash` in a shared checkout; a reviewer checks `pwd -P` and `git rev-parse --show-toplevel` inside its clone before it writes. In the commands they run (shell lines and inline scripts, not the code they write), agents use no heredoc, no `rm`, `rmtree` or `os.remove`, and no `$(...)` except around `mktemp`. These rules bind every agent, the main session included; a worker discloses a slip in its report, and the main session discloses its own in the ledger (owner answer Q-RA2-3 (a)).
- Owner rules go into decisions, rolled into playbooks, CLAUDE.md or `architecture.md`; agent
  memory only points to them.
- Dispatch only inside the role/model map; the top tier only for `top_tier_roles`.

Input-domain method (PC1-PC5; owner answers 2026-10-31 and Q-SDDT-5, 2026-11-02). (1) Every task whose interface takes an argument or reads a file carries an input-domain table in its brief, copied from the plan's input-domain dimensions: sections per producer, columns `# | dimension | values | expected verdict | test`, one row per parameter or filesystem call and dimension (argument type, subclasses and bool as int, path kind, character class, the character after each indicator, each output position, the resources held on each error path), an Oracle section, and a section of the binding owner rulings. A missing table blocks dispatch; a row with no test is a finding, and its fix covers the whole dimension. (2) The oracle is the production path compared with an independent expected value, never one read back from the code under test. (3) An implementer lists every behaviour the brief does not state and every knowing divergence, and stops with NEEDS_DECISION; in a fix round it first lists the invariants the replaced code held and tests each; it writes one mutant per changed production condition or call. (4) Reviewers have no out-of-scope bucket for the task's own code; a class that seems to exclude a failing whitelist input is a class-narrowing question for the owner; a missing table is a finding. (5) Each finding's class is written by input dimension, `class: <dimension>: <members>`, and fix and re-review dispatches quote it verbatim. A mismatch a table finds is a controller ruling only inside an approved plan and only when it is a plan-vs-spec or task-vs-task conflict the spec settles (section 7.1); any other mismatch, plan-vs-code included, is an owner question. The base playbook carries this method as text in `playbook/review.md` ("Input domains"), not as a rule row: the rows stay `SD-R1`..`SD-R19`.

`playbook/rules.md` is one table with the header `| id | rule | why | enforced by | profiles | fixed | source |` and exactly the rows `SD-R1`..`SD-R19`: `SD-R1`-`SD-R17` are the bullets above, in order, `SD-R18` is the bypass block and `SD-R19` the stack-neutral production-path rule (section 13a); `profiles` follow section 12, `enforced by` names a gate, `hook` (`SD-R12`, `SD-R18`) or `judgment`, or for `SD-R4` the tool that enforces it in a program with `judgment` otherwise (`program create (programs); judgment`, owner answer Q-PL-1 (a)), and `source` is plain text `spec §<n>` (owner answers DB-6, DB-7, DB-8, Q-B21-1 (a)). A decision whose `overrides` names no rule of `SD-R1`..`SD-R19` is refused (owner answer Q-B2plan-8 (a)). Section 8a's methods are playbook text, not rows.
Rules marked `fixed` (owner-only classes, merge grants, the bypass block) cannot be
overridden. Any other rule is overridden only by a project decision of class `rule-override`
with `overrides: SD-R<n>` (section 7.1; decision schema `decision/2`); SessionStart lists active
overrides. Project rules live in `.strict-delivery/playbooks/`.

## 8a. Methods and conventions

The base playbook also states these methods and conventions. They are playbook text in the file and section named per item, not `SD-R` rows. No gate checks them in v0.1 except where an item names the check; part of "Commits" is enforced by the two hooks that refuse a commit while a tracked file has unstaged changes (section 13).

- Fail closed and promise narrowly: a contract states only what a narrow, fail-closed check can show, and never claims to match or emulate another tool exactly; the method is to narrow the contract to a fail-closed whitelist and bound it with a seeded generated-input test (owner direction 2026-11-02); a reference implementation's fixtures may test agreement on the inputs a gate supports; agreement beyond them is a non-goal, and a known difference is a stated limit (owner answer Q-RD-6 (a)). `sessions.md`, "Plan format".
- Input-domain table: columns `# | dimension | values | expected verdict | test`; the implementer fills `test`, and a row with no test is a finding. Each verdict is marked as settled by the spec or plan, `(owner Q-<n>)` or `(controller)`; a controller row goes to the reviewer as a ruling with one line of why. The table's sections: Oracle, binding owner rulings, existing tests whose pinned behaviour changes, measurements, mismatches, and the owner batch with each option's cost (section 7.1). A row a fix names must exist, and a test cell names an existing test. `sessions.md`, "Plan format".
- A block's plan section has these parts: owner answers applied (binding); interfaces consumed; requests to other streams; a file-ownership table; controller rulings, each `what -- why -- cost if wrong -- spec cite`; cross-block notes; spec edits needed, with ids and Now and Becomes quoted verbatim; divergences, with both quotes; and the owner batch, asked upfront. `sessions.md`, "Plan format".
- Test first: a new test is watched red for its stated reason, re-established with a behaviour stub, not only a missing import; when tests came after the code, the red check overlays the new tests on a clone of the pre-change commit. `review.md`, "Review methods".
- Evidence: an input outside a whitelist fails closed with a named check; a divergence is reported with both quotes and no side taken; a pasted result is re-run before it is relied on. `review.md`, "Review methods".
- Plan and spec-edit review: every prose quote of 12 or more characters is verbatim in its source (checked by a whitespace-normalising script, re-run after each edit); each edit's old text occurs once at HEAD and its new text once after; every `Consumes` name matches the code or an earlier `Produces`; owned paths are pairwise disjoint (a trailing `/` means everything under it); a sub-block holds at most `block.max_tasks` tasks, each in the full task shape with an executable check that asserts; no placeholder (`TBD`, `TODO`) remains; and an omission is reported as an omission, not as a contradiction. `review.md`, "Plan review".
- Commits: a worker commits only with no unstaged or untracked path and no assume-unchanged or skip-worktree flag on a tracked file; a red line or a missing interpreter blocks the commit; it stages its own files by name. A fix round adds a new commit and never amends; a doc change and the test that pins it are one commit. Every commit carries the harness's `Co-Authored-By:` line for the model that wrote it. `sessions.md`, "Commits".
- Dependency skips: a test that needs another stream's unmerged work is written now, skipped with a reason naming the dependency (`Rq-<n> not on this branch`, or the block it waits for), and each standing skip is recorded in the ledger. At the update before the final review the controller removes each skip whose dependency is on the base branch, so the final review covers the unskipped tree; a pull request carries only a skip whose dependency lands after it by plan order, and the test runs unskipped from the pull request that brings the dependency (programs and streams design, section 6). `streams.md`, "Cross-stream requests".

## 9. Context, docs and drift tooling

- `.strict-delivery/context.yml` lists required reads per session kind and role (for example:
  every session reads `in-force.md` and its handoff, a session inside a program also reads its
  program's status page, and a reviewer additionally reads the brief and the review playbook).
  SessionStart prints the list for the session kind; `python3 -m gates context <kind>` prints it
  on demand. The session kinds of programs are in the programs and streams design, section 10. A plain plan's controller session has the kind `plan`; a kind `stream-<id>-block` is looked up as `stream-block`. An entry is `{path, lines, why}`: `path` with the placeholders of the programs design, section 10; `lines` optional, `<a>-<b>` or `<a>-end` (resolved to the file's last line); `why` the reason, printed with it. The command prints one line per chunk, `read <path> lines <a>-<b> blob <sha> -- <why>`, each chunk within `context.max_lines` and `context.max_bytes` (section 6). A handoff's `required_reads` (same entry shape) are appended to its kind's list, and `gate_context` checks them as it checks the rest of the list (owner answer Q-CAT-1, 2026-11-02). A `lines` range is printed guidance: any read receipt of the file at its current content satisfies the entry (owner answer Q-RD-7 (a), 2026-11-07). Entries never read another branch (owner answer Q-CAT-2: no `ref`).
- Resume. A session or agent that starts with no memory of the work (a compaction, a new session, a continuation): invokes the skills its handoff lists, in order; reads the default session load (section 7.4), its kind's context list and, for a program session, the start order of the programs and streams design (section 10), then the handoff's `required_reads` (path, optional line range, why) and its ledger from `ledger_from`; has every handoff fact checked against the real state, read-only, by an `investigator` with a fixed question list (base playbook `sessions.md`): branch heads (a recorded head is an ancestor of the live one), each worktree's status, whether the ledger is committed, and for each live agent its transcript's last record and background job ids; records the check as a prose ledger line; and reports where things stand and what it does next, with the findings, before any edit or dispatch. With no difference it takes over at once, starting the next streams or resuming in-progress ones as they were; with any difference it stops and waits for the owner. This is skill text; no hook holds the session (section 4). A plain plan's controller resumes from its plan's `handoff/1`; a program session keeps no handoff and resumes from the overview and the status pages, whose program facts (batch cut-off, its live agents, the integration head) the check covers. The handoff never tells the next session to read less than the default load plus `required_reads` (owner answers Q-PCR-1, Q-PCR-2, Q-DS-2, 2026-11-02).
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
  2026-10-31). A cite is a backtick span or an inline link target outside code fences, placeholders excluded, in every tracked `*.md`; an anchor is the GitHub ATX heading slug, repeats suffixed `-1`, `-2`, computed from frozen code-point tables, never `unicodedata` (owner answers DC-5..DC-7, Q-r5-1 (b), Q-r6-1 (b)). Backslash escapes are read literally (Q-C21r-1 (b)); text that is not UTF-8 is a problem, a backtick path is taken as written, a backtick fence opener whose rest of line holds a backtick is not a fence, and a closer may carry trailing text (Q-C21-1..3 (a)); an unreadable tracked file fails the run as `cites.input` (Q-C22-1 (a)); every record with `landed_in` is checked; a symlink or a directory counts as missing and is never followed; a heading led by a BOM gets no anchor. The gate checks the cites its grammar recognises: matching GitHub exactly is a non-goal and the known differences are stated limits (Q-C21r-2 (c)); fail closed here means scanning more and accepting fewer anchors.
- `gate_drift`: status-page and handoff facts (branch heads, merged PRs, open blocks) match git, and, when run with `--host`, the host's pull requests through `gh` (an unavailable host then fails); pending decisions on a status page match open decision records; a stream branch behind the base branch, or an integration branch behind it, fails until a sync (a sync merges main into both, section 8); a stream whose status row's `used` is past `drift.estimate_factor_pct` percent of its `estimate` is reported to the owner by `python3 -m gates drift report` at each sync; it is not a failing line. It judges live programs only, and prints one `PASS drift.none` when none is live; a stacked stream also drifts when its `stacked_on` stream's tip is not an ancestor of its own; a stream has merged when a commit on the first-parent history of the base branch tip has exactly two parents and its second parent is the stream tip, so only a merge commit counts as a merge.
- `gate_index`: `docs/strict-delivery/INDEX.md` and the state indexes regenerate without error,
  and none of them is tracked (a tracked generated file fails); the gate renders in memory, writes nothing, and fails a generated path that is not git-ignored.
- `gate_checkpoint`: handoff front matter matches its schema (plan, spec, branch, head, base,
  ledger, resume line, block, next task, findings in flight, open decisions, rulings, grant,
  live subagents), the block's own worktree is clean (other streams' worktrees may be dirty),
  the continuation handoff is present, and the ledger carries the `CHECKPOINT` line; its last `CHECKPOINT` line records the suite and gates green; the handoff's resume fields (live agents with their background jobs, worktrees, required reads, skills, `ledger_from`, `batch_cut`) match their schema, `ledger_from` follows that `CHECKPOINT` line, each required read exists within its line range, and each recorded worktree head is an ancestor of that worktree's `HEAD` on the recorded branch.
- `gate_cleanup` (after a merge and at a program's close; covers plain plans and programs): the
  merged plan's or closed program's per-effort files are gone from the tree, and every lasting
  decision they produced has a `landed_in` outside them.
- `gate_schema`: every framework file validates against the schema of its kind (appendix A);
  it runs on commit, in the Claude hooks, and in CI when CI is installed.

## 10. Agent management

Roles (framework roles with their prompt blocks and minimum tiers fixed in the framework, `dispatch.ROLES`/`MIN_TIERS`; config `roles` adds project roles with their own prompt block and minimum tier): program_controller, stream_controller, controller, implementer,
implementer_transcription, task_reviewer, final_reviewer, final_verifier, exception_reviewer,
audit_reviewer, audit_verifier, investigator, plan_writer, plan_reviewer, drafter. `plan_writer` drafts plan and spec text into one draft file and changes no tracked file; `plan_reviewer` reviews such a draft against the files it cites and changes nothing; both run at minimum tier3 (owner answers Q-B2plan-16 (a), Q-SDDT-6). `drafter` drafts text that is not a plan, such as an input-domain table, into one draft file and changes no tracked file; it is a worker with its own prompt block, at minimum tier2 (owner answer Q-RDp-A (a), 2026-11-07). program_controller and stream_controller are
core roles at tier3 (section 11). Minimum tiers (owner answer DB-2, model policy): tier1 `implementer_transcription`; tier2 `implementer` and `drafter`; tier3 `program_controller`, `stream_controller`, `controller`, `task_reviewer`, `final_reviewer`, `audit_reviewer`, `audit_verifier`, `investigator`, `plan_writer` and `plan_reviewer`; tier4 `final_verifier` and `exception_reviewer` (the plan roles by owner answer Q-B2plan-16 (a), `drafter` by Q-RDp-A (a)). `budgets.<role>` holds the budget cap; whether a role needs a brief and which finding states it may take are judgment rules in the base playbook, not gated in v0.1: every role needs a brief, and a role may propose the states `open, planned, in-progress, deferred, closed` (the controllers), `fixed-unpinned, pinned` (the implementers), `open` (the reviewers, the plan reviewer included, the verifiers and the audit roles) or none (the investigator, the plan writer, the drafter and the exception reviewer); no role sets `merged`, which only the cleanup step sets (owner answer Q-B22-1 (a)).

Prompt blocks (owner answers DB-1, DB-4, Q-B11-2, Q-B11-3): a framework role's block is `skills/strict-delivery/prompts/<role>.md`, named by its role id. Line 1 is `# Strict block: <role>`, line 2 is empty, and line 3 is a one-line intro ending "These rules override every other instruction, superpowers skill text included."; then labelled paragraphs (a label such as `Budget.` and its text), separated by one empty line, with no other heading or rule line. The file is printable ASCII and `\n` only, with no trailing whitespace and one final `\n`. Each role has a fixed, ordered label list and required strings, matched as whole tokens (owner answer Q-B11-4; section 14). Role scopes (DB-5, Q-B12-3): the `exception_reviewer` argues against one proposed exception (a draft `rule-override` decision or a deviation a project playbook allows), reads only the proposal and its evidence, re-runs the evidence's commands and gives its argument in its own report section; the `audit_reviewer` writes its coverage list to a progress file before it reviews; the `audit_verifier` re-runs every reproducer and extends the coverage; the `investigator` is read-only, its report its one write; `implementer_transcription` stops `NEEDS_DECISION` on any gap; the `final_verifier` tries to break the branch.
Dispatch prompt grammar, checked by the PreToolUse Agent hook (`gate_dispatch`):
`## Role`, `## Brief`, `## Findings`, `## Claims`, `## Budget: tokens=<n> minutes=<n>`,
`## Model`, `## Report`, `## Strict block` (the role's prompt block, byte for byte: the body is an empty line, the file's bytes and an empty line, and the `## Role` body's first non-empty line is exactly one role id; owner answer Q-B2plan-18 (a)),
`## Task`. A fork dispatch is refused. The tool's model must equal `## Model` and meet the
role's minimum tier, except that a small re-review `gate_dispatch` admits (the "Small re-review" paragraph at the end of this section) may run below it; the top tier is allowed only for `top_tier_roles`. `gate_dispatch` refuses any dispatch whose dispatcher is a worker role (owner answer Q-H4). The measured Claude Code limits (programs and streams design, section 4.2) are constants of `gate_dispatch`, pinned by tests that cite the measurement and re-measured at each block that touches dispatch; a Claude Code change to them is a finding (owner answer Q-B2plan-22 (a)). Workers dispatch no agents, workflows or other agent tasks; they may start background shell jobs, which they reap before reporting (section 8). After a permission denial an agent stops with status `DENIED`, quoting the denial; the controller does not re-run the denied action, and a resumed agent runs only its own code, never downloaded or external code.

Lifecycle: in a plain plan, the controller dispatches every role. In a program, only the program session dispatches a program_controller; the program session (which acts as program controller by default) or a program_controller dispatches a stream_controller; stream controllers and their sub-controllers dispatch the workers, and a sub-controller may dispatch a sub-controller when the stream controller judges it better, within the depth limit (owner answers Q-H3, Q-H5 (a)). Fix
loop rounds 1-3 resume the implementer,
rounds 4-5 a fresh agent one tier up, then an owner question (a small re-review, below, may run below the reviewer's minimum tier); every report starts with
`status: DONE|DONE_WITH_FINDINGS|NEEDS_DECISION|BLOCKED|DENIED`; when more than one applies, the first of DENIED, BLOCKED, NEEDS_DECISION, DONE_WITH_FINDINGS, DONE is reported (owner answer Q-B13rr-1 (a)). DONE means every claim and gate re-ran clean and the change holds no finding; a defect the change did not cause goes under Unrelated findings and does not by itself make the status DONE_WITH_FINDINGS (owner answers Q-B12r-1 (a), Q-B13r-2 (b)). Each role's report lists fixed fields in a fixed order (the implementer's: commits; gates run; claims; findings raised; unrelated findings; decision needed; denials; budget used), and the final reply is at most 10 lines with the same fields. A controller never returns
while its children run: questions and progress go up to its parent as messages, and answers
come down as decision records (section 11). After each review the controller may run `python3 -m gates loopstats`, which prints the advisory Rules N (novelty) and T (trend) and, when `escape_cost` is set, an expected-value verdict; it never blocks a fix and never decides whether a found defect is fixed; its signals only decide whether a re-review may run below the reviewer's minimum tier (the "Small re-review" paragraph of this section).

Rules N and T (owner answers Q-ES (a), Q-ES2 (a), 2026-11-01; advisory). A finding carries `review_round`, `caused_by_change` and `dimension`. For one task after `k` reviews, the counted findings are those the task's change caused (`caused_by_change: true`) with severity `CRITICAL`, `HIGH`, `MEDIUM` or `LOW`; `X_i` is the number from review `i`, `N = sum X_i`, `S = sum (i-1) X_i`. Rule T: `p = P(S' <= S)`, where `S'` is the sum of `N` independent uniform draws on `{0..k-1}`, computed exactly; the trend is converging at `p <= 1/10`. A truncated-geometric fit (`q` with `sum j q^j / sum q^j = S/N` over `j = 0..k-1`) gives `a = N/(1-q^k)`, the remainder `R = a q^k` and the expected next-round count `E_next = a(1-q) q^k`; at `S/N >= (k-1)/2` the fit is at its boundary, `R` is unbounded and `E_next = N/k`. Rule N: the novelty `nu` is the share of review `k`'s counted findings whose `dimension` (one canonical dimension from the input-domain table's row names, given by the reviewer) is on no counted finding of an earlier review; N fires when `k >= 2`, `X_k > 0`, `nu >= 1/2` and `X_k >= X_(k-1)`. A narrowing of the contract is noted and counted, never a reset. The verdict, in order: `X_k = 0` CLEAN; `k > 5` ESCALATE; N fired: STOP_NARROW, or ESCALATE after a narrowing; `k < 3` CONTINUE; converging and the fit not at its boundary: CONTINUE; otherwise ESCALATE after a narrowing, else STOP_NARROW when `nu >= 1/2`, else ESCALATE. With `escape_cost` set (section 6), the expected-value figure is `E_next * sum_s (n_s/N) * escape_cost[s]`, `n_s` the counted findings of severity `s` over all reviews; it reads `continue` above one fix round (the unit of `escape_cost`), else `stop`, and never changes the verdict. A `CRITICAL` or `HIGH` finding the change caused is fixed whatever the verdict.

Small re-review (owner answers Q-COST-1 and Q-COST-2 (a), 2026-11-02; a framework default). A re-review of fix round `r` (1 to 4) of one task by `task_reviewer` (owner answer Q-RD-12 (a)) may run at the tier `reviews.small.tier` names (default tier2, section 6; owner answer Q-RD-10 (b)) instead of the role's minimum tier when every condition holds: (1) it is scoped to that fix's diff, not a full re-review; (2) the fix diff has at most `reviews.small.max_lines` changed lines in at most `reviews.small.max_files` files (section 6); (3) no changed path matches `reviews.small.exclude`; (4) the findings the fix answers are `LOW` or `MEDIUM` only, and no owner question is open for the task; (5) the previous review found no defect caused by a fix; (6) Rule N does not fire; (7) from review 3 on, Rule T converges (`p <= 1/10` with a finite remainder `R`); (8) from review 3 on, with `escape_cost` set, the expected-value figure is below one round. "From review 3 on" means once the task has had three reviews (`k >= 3` in the "Rules N and T" paragraph of this section), so from the re-review of fix round 3; before that, conditions 1-6 decide. Rules N and T are computed over the reviews done before the re-review being dispatched. A small re-reviewer escalates on any defect it finds, on NEEDS_DECISION and when it is unsure, and the next re-review then runs at the role's minimum tier; the re-review of fix round 5 always runs at it. The dispatch states the conditions on one `small-re-review:` line of `## Brief`; `gate_dispatch` admits the lower tier only when the conditions it can check from git, the finding records and `loopstats` hold (1-3, 4's severities, 6-8), and the controller's `small-re-review:` line states the rest (4's no open owner question, 5), which the small re-reviewer checks (owner answer Q-RD-12 (a), 2026-11-07).

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

Every gate: `check(args) -> Result`; prints `PASS id` or `FAIL id: reason` lines, each id and reason escaped exactly once, by `Result.render` (`safe_text`): a caller value or a map item in a reason is escaped once, a non-`str` value is converted with `str()` first, and a backslash renders as `\\` (owner answers Q-U2 (a), Q-1a2-6, Q-1c0-2 (a)); `--json`, printing `{"gate", "ok", "lines": [{"status", "id", "reason"}]}`;
exits 0 only when at least one line exists and every line passes; a missing input fails
(`<gate>.input`), an empty run fails (`<gate>.empty`); `--root` points at another tree. A gate runs as `python3 -m gates check <gate>`: an unknown gate prints the usage and exits 2, a missing gate module gives one `FAIL <gate>.input` line and exits 1 (owner answer Q-1c0-1 (a)), `--help` prints `FAIL <gate>.input: help requested; no gate was run`, and an option given twice is refused for every gate (Q-1b1r-1 (b)); `KeyboardInterrupt` propagates, any other exception becomes `FAIL <gate>.input`, and a cyclic value renders as `{...}` or `[...]` (Q-1c0-3 (a)). The root is `CLAUDE_PROJECT_DIR` when set and non-empty (a non-directory is a `GateError`), else `git rev-parse --show-toplevel`; outside a repository the error names `/strict-delivery:init`, and with git missing from `PATH` it reads `git not found on PATH; install git`, with no init hint (Q-1a2r-6). Every library function that takes a repository root, `Store` and `config.load` included, and every gate, list-only gates too, refuses a root that is not the git top level, compared by real path (owner answers Q-1a-fin-1 (a), Q-1bfin-2 (a)). A gate line names the record id when it is valid and unique, else the repository-relative path (Q-1c1-1 (a)); the reference scan matches raw bytes (Q-1c1-2 (a)).
`run_all` runs the gates the profile enables (`run_all.PROFILE_GATES`): light `schema`, `register`, `decisions`; standard and strict also `claims`, `index`, `evidence` and, once it lands, `cites`; `streams` is added while a program is live or the current branch is a program branch; `dispatch`, `context`, `drift`, `checkpoint` and `cleanup` are in no list (owner answer Q-B2plan-19 (a); controller rulings R5a-1, R5b-3, R5c-1, P1, P3); a missing or raising gate fails. Hooks fail
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

Git calls pass argument lists only, `--` before paths and `LC_ALL=C`, with `GIT_DIR`, `GIT_WORK_TREE`, `GIT_COMMON_DIR`, `GIT_OBJECT_DIRECTORY`, `GIT_ALTERNATE_OBJECT_DIRECTORIES`, `GIT_NAMESPACE` and `GIT_CEILING_DIRECTORIES` cleared and `GIT_INDEX_FILE` inherited on purpose, so a pre-commit hook reads the index being committed (owner answers Q-1a-ver-3 (a), Q-1a2r-5); a call whose output the framework parses passes `--no-color` where the command takes it, `-c core.abbrev=12` where it prints abbreviated ids, and `--no-ext-diff --no-textconv` on a diff, so the user's colour and abbreviation settings never reach it, and each call that passes one of these options is tested in a fixture repository whose config sets `color.ui=always`, `color.diff=always` and `core.abbrev=7` (owner answer Q-RC-1 (a)). A revision starting with `-` or `^` is refused, and a run of more than 40 hex digits is refused before git runs (Q-1a-ver-2 (a)); a short prefix naming more than one object is not a commit, resolved with `-c core.disambiguate=none`, while an expression built on such a prefix resolves as git does (Q-1a2-3, Q-1a2r-2, Q-1a2r-7); a symlink (mode 120000) is not a blob, only modes 100644 and 100755 are, and `show` gives none for a directory, a symlink or a gitlink (Q-1a2r-1); a path with a `..` segment raises, an unnormalised path is refused (Q-1a-fin-2 (a)), and a whitespace-only value gives none.

## 13a. Evidence contract for target projects

The framework never prescribes how a project writes tests. It defines only the evidence a
gate can check, in terms of the project's own commands:

- A pin is an opaque test id plus `commands.test_one` rendered with it (for example
  `npx jest -t {id}`, `mvn -Dtest={id} test`, `cargo test {id}`). The gate checks that the id
  is given and that the command exits 0 on the fixed tree. A string `test_one` template has each `{id}` replaced by the shell-quoted test id and runs through `/bin/sh -c`; a list template replaces `{id}` literally in each element and runs with no shell; both run at `--root`, with the inherited environment and no timeout. A template with no `{id}` fails `evidence.config`, and `gate_evidence` always prints `evidence.config` and `evidence.scope`, so a tree with no pin passes and is never an empty run.
- A mutation transcript is three runs of that command: pass on the fix, fail with the fix
  reverted or with a mutant, pass again. How the mutant is made is the project's choice:
  a manual revert, or `commands.mutate` pointing at the project's own tool (Stryker, PIT,
  mutmut, cargo-mutants, ...). The gate checks the transcript's shape, commands and exit codes,
  never the tool.
- `gate_evidence` checks both, stack-neutral: a review package per finding or pin names the
  test id, the rendered `test_one` command and the transcript; the gate re-runs the pin
  command on the fixed tree with the current config, checks that every run's command in the transcript equals the package's `PIN-COMMAND` (owner answer Q-B6plan-4 (b)), and checks the transcript's shape (pass, fail, pass, where the failing run exits non-zero and neither 126 nor 127) and exit
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
- Matrix: Python 3.9 and 3.13 on ubuntu and macOS. Gate output does not depend on the interpreter: no result depends on the interpreter's Unicode data (`unicodedata`, `str.isprintable` and the like); character classes come from frozen code-point tables, and a test asserts one golden output byte for byte, in every matrix cell. The test command is `<python> -m unittest discover -s tests -t . -v`, run on each interpreter of the matrix; the plan names the interpreters' paths (owner answer Q-DVD12 (a), 2026-11-07).
- YAML subset: round-trip, every refusal case, a fuzz corpus.
- Fixtures: a test that writes a record or a config, of any kind, takes the schema tag from the schema the record is checked against, never a literal: the schema the test builds where it builds one, else the kind's schema file (or one named constant until the kind's schema file exists); it builds configs only with `tests/helpers.minimal_config()` (owner answers Q-2a1-3 (a), Q-2c2-2 (a), Q-RCp-3 (a)); only a test whose subject is a tag or a version (a migration, the refusal of an old version, a wrong or malformed tag fed to a validator, the tag `minimal_config()` returns) and `minimal_config()` itself write a tag literal. Tests that run git are isolated from the user's git config (`HOME`, `GIT_CONFIG_NOSYSTEM=1`, `GIT_CONFIG_GLOBAL=/dev/null`, commit signing off) through one base class, `GitIsolatedTestCase`.
- Init end-to-end: fixture repositories (node, rust, go, python, C with make, empty, monorepo);
  non-interactive init from an answers file; `doctor` and `run_all` green; then seeded
  violations (unanswered decision reference, `--no-verify`, an agent-run `decisions decide`,
  bad dispatch, a duplicate id, a base-branch record deleted, a tracked generated index) each
  turn the run red. Every gate has a red case. A fixture
  with existing `docs/superpowers/` documents and one with a colliding path prove the
  migration and the no-overwrite rule.
- Hooks: JSON event fixtures into each hook script.
- Framework prose (prompt blocks, playbook, skill): required strings matched as whole tokens inside a named paragraph or section (owner answers Q-B12-1, Q-B13-1), and key rule sentences pinned in full (Q-B13r-1 (b)); a harmless rewording of an unpinned phrase never fails the suite, and every content sentence of a prose deliverable has an executable check or is deleted.
- Profiles: the same fixture repository under each profile runs exactly the gates the profile
  table names.
- Skill pressure scenarios (headless `claude -p` runs against rationalisation traps such as
  "too small for the process"): an opt-in workflow, not default CI, because of cost.
- The framework's own fixes: production-path test plus mutation transcript.

## 15. Release

Semver tags and `CHANGELOG.md`. A release script (`scripts/release.py`, framework repository only) bumps together every literal version that section 4 requires to agree: plugin.json, marketplace.json, and this repository's CLAUDE.md and `.gitignore` block versions and `framework_version`; templates render the version at init and hold none. It never commits, pushes or tags; the release reaches main by pull request, and each release tag is annotated, sits on the release pull request's merge commit, is created locally after the merge is read back from the host, and is pushed only on the owner's word. Every data file carries
`schema: <kind>/<version>` (appendix A). A shape change is a new schema version plus a
migration from the old version, which `upgrade` runs; every migration is tested from an old
fixture to the new version. Before 1.0, breaking changes are allowed with a migration; 1.0
freezes the config and state schemas.

## 16. The framework repository's own process

- The repository adopts itself at the strict profile with empty registers, and answers yes to the local git hooks; its own matrix workflow (`.github/workflows/strict-delivery.yml`) stands in for the CI extra, which `doctor` reports as a project workflow. Owner: superbrobenji.
- Bootstrap: the first block builds lib, the YAML subset and the register and decision gates
  while no gates exist; this is stated in its first report and the judgment rules apply. Each
  gate is enabled on this repository as soon as it lands; from then every change is gated.
- Until the framework delivers the session-resume features, this repository applies them by hand with an interim project skill `.claude/skills/strict-delivery-repo/`, which also carries as a checklist the by-hand form of every framework rule whose tool or skill text is not built yet, and a `CLAUDE.md` naming this repository's paths; the user-level skill is not changed. The skill is removed once the plugin is enabled here, and `CLAUDE.md`'s interim text once its managed block is inserted, by the streams that own those paths then (owner answers Q-PCR-6 (a), 2026-11-02, and Q-AUD-1, 2026-11-03).
- lap-timer's migration onto the framework is a separate, later sub-project in the lap-timer repository.
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
2. `gate_claims`, `gate_dispatch`, `run_all`, git hook shims and installer, self-adoption, and the decision schema `decision/2` (the optional `overrides`, `recommended` and `source`, section 7.1) with its migration; `config/2` with its migration carries `merge.mode` (owner answer Q-Pplan-14 (a)) and the optional `escape_cost` (owner answer Q-B6plan-3 (a)).

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
table headers. A field spec has a `type` and may have only these other keys: `required` (true or
false, default true), `nullable` (true or false), `values` (an `enum`'s non-empty list of strings,
of integers or of booleans), `items` (a `list`'s item spec, which carries no conditions),
`fields` (a `map`'s field specs), `id_kind` (an `id`'s kind: `decision`, `finding`, `claim` or
`request`), `min` (on an `int` or a `list`, an integer of at least 0), `required_when` and
`absent_when` (lists of conditions naming sibling fields; `absent_when` on a required field with
no `required_when` is a malformed schema). An `enum` requires `values`, a `list` `items`, a `map`
`fields` and an `id` `id_kind`; a key on a type that does not use it is a malformed schema. The types are `str`
(non-empty), `text`, `int` (never `bool`), `bool`, `enum`, `list`, `map`, `any-map` (contents not
checked), `id`, `sha` (7 to 40 lowercase hex), `glob`, `cite` and `sha-path`. A markdown table
header matches byte for byte, with its `|---|` separator; a missing `{path: ...}` file fails
`schema.<kind>.<path>: missing`; the upgrade hint is printed only for a matching kind with
another version (owner answers Q-1b1-1, Q-1b1-2, Q-1b1-4).
Every data file carries `schema: <kind>/<version>`; a shape change is a new
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
declare (owner answer OQ-16). A generated file (in-force, decision-index, finding-index, overview) that is absent on
disk is skipped, since it is regenerated before use (owner answers 2026-10-31). The decision
schema carries the optional `rule`, the `withdrawn{at, by, reason}` map and the grant fields `plan`, `program` and `stream` (section 7.1; kept for records already written, since pull-request merge approvals are ledger `MERGED` lines, not records, owner answer Q-15 (a)). From `decision/2` it also carries the optional `overrides`, `recommended` and `source` (section 7.1), with a tested migration from `decision/1` that lands before block 3's
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
| context | `gates/schemas/context.yml` | required reads per session kind and role (section 9); each entry `{path, lines, why}`, `lines` optional (`<a>-<b>` or `<a>-end`) |
| handoff | `gates/schemas/handoff.yml` | a plan's handoff front matter (section 9) |
| ledger | `gates/schemas/ledger.yml` | a plan ledger's line formats (`CHECKPOINT`, `Ruling:`, `Request:`, `UPDATE`, `MERGED`); a line led by one of these words must match its form, any other line is prose (owner answer Q-Pplan-1 (a)); a `MERGED` line also names the `stream` and sub-`block` whose pull request it records (lines written before that field are read as naming none) |
| status | `gates/schemas/status.yml` | a program's status page table (section 11) |
| sync-log | `gates/schemas/sync-log.yml` | a program's sync log (section 11) |
| overview | `gates/schemas/overview.yml` | the sections of `INDEX.md` (section 5) |
| in-force | `gates/schemas/in-force.yml` | the generated `in-force.md` (section 7.4) |
| decision-index | `gates/schemas/decision-index.yml` | the generated `state/decisions/index.yml` (section 5) |
| finding-index | `gates/schemas/finding-index.yml` | the generated `state/findings/index.yml` (section 5) |
| mutation-transcript | `gates/schemas/mutation-transcript.yml` | one mutation transcript (section 13a) |
| review-report | `gates/schemas/review-report.yml` | one review report or review package (section 13a) |
| receipt | `gates/schemas/receipt.yml` | one session's read receipts (section 9) |
| breakdown | `gates/schemas/breakdown.yml` | a plan's stream breakdown, `<paths.plan_state>/<plan>/breakdown.yml` (section 8): `plan`, `max_concurrent` and `max_depth` (the limits assumed), `done` (tasks finished before the record), `streams` (each `id`, owned `paths`, each a path or a path window `{path, from, until}`, an optional `period {from, until}`, `tasks`, `unblock`; at most one `residual` stream, which owns every path no other stream owns in the same window and has no `paths`), `edges` (`from` task, `to` task: `to` waits for `from`), `groups` (parallel groups: `id`, `tasks`). Window and period events: `program-start`, `merged:<stream>/<sub-block>`, `merged:<stream>` (the stream's last sub-block merge), `program-close`; owner answers Q-PL-1 (a), Q-BD-4 (a), Q-BD-7 (a), Q-BDr2-1 (a) |
| claude-block | `gates/schemas/claude-block.yml` | the CLAUDE.md managed block (section 4) |
| gitignore-block | `gates/schemas/gitignore-block.yml` | the `.gitignore` managed block (section 5) |
| profile | `gates/schemas/profile.yml` | a profile preset in the plugin (section 12) |
| init-answers | `gates/schemas/init-answers.yml` | the answers file of a non-interactive `init` (section 4) |
