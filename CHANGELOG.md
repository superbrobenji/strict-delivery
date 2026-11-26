# Changelog

This project follows semantic versioning (semver). Before 1.0 a breaking change is allowed, and it comes with a migration that `upgrade` runs; 1.0 freezes the config and state schemas.

## Unreleased

- Gates: `python3 -m gates check <gate>` and `python3 -m gates run_all` run the gates a profile enables: `schema`, `register`, `decisions`, `cites`, `claims`, `index`, `evidence` and, while a program is live, `streams`; `dispatch`, `context`, `drift`, `checkpoint` and `cleanup` run on their own. Every gate prints `PASS id` or `FAIL id: reason` lines, and its text is identical on Python 3.9 and 3.13.
- Tools: records are written through commands, never by hand: `decisions` (`ask`, `decide`, `withdraw`, `find`, `batch`), `findings`, `claims`, `questions`, `receipt`, `context`, `continue`, `drift`, `index`, `program`, `githooks` and `loopstats`.
- Schemas and migrations: every data file carries `schema: <kind>/<version>`; a shape change is a new schema version plus a migration from the old one, each tested from an old fixture; the registered migrations run in `upgrade`.
- Init, doctor and upgrade: `init` proposes the project's own test, lint and build commands, writes `.strict-delivery/config.yml`, the CLAUDE.md and `.gitignore` managed blocks and the optional git hooks and CI workflow, and never overwrites a file it does not manage; `doctor` checks the install, writes nothing and fails when the plugin, block, CI and config versions disagree; `upgrade` moves the version pin, re-renders the blocks and runs the migrations.
- The plugin: the skill and one prompt block per agent role; the base playbook (rules, roles, decisions, review, sessions and streams); and the Claude Code hooks (session start, prompt reminder, checks on agent dispatch, shell commands and edits, read receipts, and subagent stop), which refuse with a stated way out.
- Programs and streams: the `program` tool and the `streams`, `checkpoint` and `cleanup` gates run a large effort as parallel streams, each in its own worktree and branch, with checkpoints, handoffs, a merge policy and an owner-question path.
- Profiles: `light`, `standard` and `strict` are presets of the config, differing in the gates they run, the review and mutation evidence they ask for, the size cap of a block and the pre-commit command; a policy key changes only through a recorded owner decision.
