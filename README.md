# strict-delivery

A Claude Code plugin that brings a strict way of delivering software to any repository:
every change is tracked, every claim is checked, owner decisions are logged and binding,
agents are dispatched by role under a fixed contract, and gates enforce all of it in Claude
sessions and, optionally, in git hooks and CI. Large efforts run as programs of parallel
streams.

Status: **pre-release, under active development toward v0.1.** Nothing here is installable
yet. The repository builds itself with its own process, so the history, ledger and plan are
public on purpose.

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
| adversarial top-tier verifier per block | no | no | yes |
| mutation proof that tests can fail | no | per finding | every pin |
| pre-commit | schema, register, decisions gates | `run_all` (every gate) | `run_all` plus the gate suite on every supported runtime |
| tasks per block | no cap | 5 | 3 |

This repository is configured as `strict` and follows it by hand for now: `run_all`, the git
hooks and CI that will enforce it arrive in the next steps of the roadmap.

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

Merged pull requests: #1-#13.

## Roadmap to v0.1

1. `run_all`, git hooks and CI as this repository's own commit gate
2. The claims tool, config version 2, and `gate_dispatch`: every agent dispatch checked for its contract and model tier
3. Checkpoints and handoffs; the `program` tool for parallel streams; merge policy and cleanup; the owner-question path and automatic continuation
4. Packaging as a plugin: runtime, Claude Code hooks, records and evidence, config profiles, `init`, `doctor`, `upgrade`
5. Context and docs: required reads per session and role with read receipts, the generated overview (`INDEX.md`), drift checks
6. Release 0.1.0: end-to-end tests of the three profiles, release script, changelog

A few smaller follow-up blocks (for example Block 1d3) are registered, not yet scheduled; the plan has the full list.

Target: mid-November 2026. Progress and every decision are in the ledger under
`.strict-delivery/state/plans/`.

## License

See [LICENSE](LICENSE).
