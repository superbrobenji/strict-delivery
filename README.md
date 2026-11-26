# strict-delivery

A Claude Code plugin that brings a strict way of delivering software to any repository:
every change is tracked, every claim is checked, owner decisions are logged and binding,
agents are dispatched by role under a fixed contract, and gates enforce all of it in Claude
sessions and, optionally, in git hooks and CI. Large efforts run as programs of parallel
streams.

Status (2026-11-26): **pre-release, under active development toward v0.1.** Nothing here is
installable yet: `init`, `doctor` and `upgrade` are not merged. The plugin will be enabled in
this repository once its Bash hook lands (see "Where v0.1 stands"). The repository builds itself with its own process, so the history,
ledger and plan are public on purpose.

## What it will look like in your project (v0.1)

Install once per machine, then once per repository:

```
/plugin marketplace add superbrobenji/strict-delivery
/plugin install strict-delivery@strict-delivery
/strict-delivery:init
```

`init` proposes your existing test, lint and build commands, asks for a profile
(`light`, `standard`, `strict`), a model map, whether to install git hooks and a CI
workflow, and who merges pull requests, and offers to set up branch protection on the base
branch. It never overwrites your files; it writes its own files and managed blocks, adds the
subagent limits to `.claude/settings.json`, and can move existing superpowers docs under
`docs/strict-delivery/` (with `git mv`, rewriting references to them):

```
.strict-delivery/config.yml      settings: profile, commands, model tiers, budgets
.strict-delivery/context.yml     what each session and role must read
.strict-delivery/state/          decisions, findings, claims; plan and program records while live
docs/strict-delivery/            architecture overview; specs, plans, reviews per effort
CLAUDE.md, .gitignore            a managed block each; your own text is untouched
.git/hooks/, .github/workflows/  optional extras
```

The gates engine, base playbook, agent prompt blocks and Claude Code hooks stay inside the
plugin and update with it. Gates run as `python3 -m gates` (Python 3.9+, standard library
only), so the target project can be in any language.

### Profiles

| | light | standard | strict |
|---|---|---|---|
| register row per change, binding decisions, no gate bypass | yes | yes | yes |
| claims register (doc statements checked) | no | yes | yes |
| dispatch contract and model tiers enforced | no | yes | yes |
| adversarial top-tier verifier per stream | no | no | yes |
| mutation proof that tests can fail | no | per finding | every pin |
| pre-commit | schema, register, decisions gates | `run_all` (every gate) | `run_all`, then `commands.test` |
| tasks per block | no cap | 5 | 3 |

This repository is configured as `strict`. `run_all`, the git hooks and CI already enforce it
here; the Claude Code hooks are being finished (the Bash hook is the last one), and until the
plugin is enabled the agents follow the remaining rules by hand.

## Repository layout

The product (what ships in the plugin):

- `gates/`: the gates engine (`gate_*.py`), its library (`lib/`), record tools (`tools/`) and schemas (`schemas/`)
- `playbook/`: the base rules people and agents follow
- `skills/strict-delivery/`: the Claude Code skill and one prompt block per agent role
- `tests/`: the framework's test suite (run on Python 3.9 and 3.13)

How the framework is being built (process for this repository only):

- `docs/strict-delivery/specs/`: the design specs, the source of truth
- `docs/strict-delivery/plans/`: the implementation plan (blocks and tasks)
- `.strict-delivery/`: this repository's own config and run state (ledger, handoffs, mutation transcripts)
- `CLAUDE.md`, `.claude/`: rules and settings for agents working here

`main` is protected: every change lands by pull request, administrators included. By process
every pull request lands as a merge commit; restricting the host's merge methods to that is a
planned owner step.

## Done so far

- Schemas and the YAML subset parser; the shared gate library
- Gates: `schema`, `decisions`, `register`, `cites`, `claims`
- Record tools: decisions (`ask`, `decide`, `withdraw`, `find`, `batch`) and findings (`new`, `move`)
- Stack command detection (the input for `init`)
- Base playbook, the skill and the agent prompt blocks, with a checker for their text
- Gate output identical on Python 3.9 and 3.13, the two tested versions (frozen Unicode tables)
- Gate command-line error text identical on both versions (a restricted argument parser) and a frozen case-fold table for decision text (#21)
- Playbook and prompt-block rules from the build so far: a threshold for asking the owner, an explicit model on every dispatch, no handback while child agents run (#15, #19)
- The plan and the stream breakdown re-based on the owner's answers of 2026-11-10 and 2026-11-14 (revision 6, #16), and the findings register kept current (#18, #20)
- This overview itself (#14)
- `run_all`, every enabled gate in one command (#17), `loopstats`, the fix-loop stopping math (#22), and the git hooks tool `gates/tools/githooks.py` with the CI workflow (#23)
- `findings new` loop fields: `--review-round`, `--caused-by-change` and `--dimension` write the finding fields `loopstats` counts (#24)
- Process rules rolled in: the binding fix loop, narrow-only fixes, merge on demand (#25)
- Plugin packaging: `plugin.json`, `marketplace.json`, the `run_all` version check (#26)
- Config version 2 and `gate_dispatch`: every agent dispatch checked for its contract and model tier (#27); the claims tool (`claims add`, `claims verify`) and decision options (#28)
- Programs of parallel streams: the schema vocabulary, handoff and ledger schemas (#29); the programs library, the `program` command and `gate_streams` (#30); owner questions, automatic continuation and dispatch for live programs (#32); pull-request merge policy, final merge and cleanup pull requests (#35)
- Evidence: the evidence schemas, `check evidence` and mutation-transcript checks (#31)
- Context and docs: context files, read receipts and `gate_context` (#33); the generated overview and `gate_index`, the checkpoints library (#37); the drift facts library and `gate_drift` (#39, #43)
- Stream runtime for the Claude Code hooks (#36); the Edit/Write and Agent hooks (#42)
- `gate_checkpoint` in full (#41)
- CI: the test suite split into five parallel shard jobs per cell (#40); tests never start git's file-system monitor (#34)

Merged pull requests: #1-#37 and #39-#43 (#38 is open).

## Where v0.1 stands

The work runs as five parallel streams. Every code pull request gets a final review, mutation
evidence for each pinned finding and a green CI run on its exact head before it merges.

| Stream | Done | In progress | Still to come |
|---|---|---|---|
| config | (none merged yet) | config profiles and their checks (4a-4c, #38: open, CI green on its head, a records commit still owed); `init` (4d.1-4d.2) and `doctor` (4d.3) | `upgrade` (4e.1), the slash command files and this repository's adoption (4e.2), fixture repositories and the `init` end-to-end tests (4e.3) |
| hooks | runtime, Edit/Write and Agent hooks (#36, #42) | the Bash hook (3b.2), on a branch and not merged: by the owner's decision it will refuse a chained or piped command that mixes git with a write, rather than guessing where it points | 3b.3, then the Bash hook PR; the plugin is enabled in this repository after it |
| records | overview, checkpoints, drift (#37, #39, #41, #43) | the tip-reader task 5b.3 | drift hardening (5c.4) |
| residual | the program controller's sync text (#37) | residual batch 1, the registry requests (#44 open) | the process-learning tasks L1 and L2, batch 2 (the index and drift registry rows, context in the hooks, loopstats conditions in `gate_dispatch`, the interim skill's removal) |
| ci | the sharded CI suite (#40) | mutation tests per pull request on CI (CI3) and a faster local suite (CI2), both at top priority | |

After the streams: one adversarial verifier pass over everything each stream delivered,
then the `release` stream (6R: end-to-end tests of the three profiles, the release script,
the changelog) and the 0.1.0 tag.

Estimate (ledger, 2026-11-26 14:15): the plugin enabled in this repository around 2026-11-29
to 2026-11-30, and the v0.1.0 tag around 2026-12-04 to 2026-12-06. No date is committed; the
estimate does not include usage-limit stops. Progress and every decision are in the ledger under `.strict-delivery/state/plans/`.

## v0.2 (designed, planning in progress)

v0.2 makes the framework faster to deliver with, without lowering the quality bar. Its
design is approved: `docs/strict-delivery/specs/2026-11-26-v02-design.md`, on the
`block/docs-resume` branch until it merges. Work starts after the v0.1.0 tag, with a target
of under one week from the start of v0.2 work to the v0.2 tag (one more week of leeway). It
is built in five stages, each merged before the next:

1. Stage B, the tool gaps that slowed v0.1 down: who found a finding and in which round;
   loop statistics that count only a task's own review findings, while findings carried in
   from other tasks still block sign-off; findings that close
   automatically once the fix is merged and its test pinned (including squash merges); briefs
   with empty sections refused.
2. Stage A, records and process tooling: a finding records every member of its class; a
   fixed hardening section in every input-domain table; a schema for every record kind from
   its first record; handoffs written only by a tool; `gates timeuse`, which measures where
   agent time goes against targets.
3. Stage C, the recorded fixes: one shared safe-read helper and the open findings left from
   v0.1; git 2.30 as the minimum version.
4. Stage F, CI and mutation rules: mutation tests per pull request on changed lines; the
   full suite on a pull request is CI on its exact head; profiles that set how much each run
   costs; CI optional, with local `gates suite` and `gates mutants` as the fallback; CI jobs
   named for what they do.
5. Stage D, gates, views and stated limits: automatic clean-up of merged work, with history
   kept for a configurable time (six months by default); role and method rules turned into
   gates; required config keys (`config/3`); pressure-test scenarios for agents; checks on
   merge, cherry-pick, revert and rebase commits; a program status view; claims whose checks
   are re-run; an interactive `init`; drift checks for single plans; detection of orphaned
   agents; the Bash hook reading the scripts it is asked to run.

## v0.3 (candidates)

Tracked in `docs/strict-delivery/specs/2026-11-26-v03-candidates.md` (on `block/docs-resume`
until it merges); none of these is designed yet:

- Windows support
- agent harnesses other than Claude Code
- CI systems other than GitHub Actions
- optional language-specific lint adapters
- a strict pre-commit cell that also runs the touched tests

## License

See [LICENSE](LICENSE).
