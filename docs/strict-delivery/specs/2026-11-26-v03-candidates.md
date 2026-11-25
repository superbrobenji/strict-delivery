# v0.3 candidates (tracking list)

Status: a list to keep track of, not a design. Owner, 2026-11-26: "E can be v0.3; let's just create a candidate list for v0.3 for now to keep track." Ids are those of the v0.2 inventory (`.superpowers/sdd/2026-10-31-strict-delivery-framework/v02-inventory.md`); items added later get new ids here.

| ID | Item | Source |
|---|---|---|
| V2-30 | Windows support | v0.1 design spec non-goals |
| V2-31 | Agent harnesses other than Claude Code (Codex, Cursor) | v0.1 design spec non-goals |
| V2-32 | CI systems other than GitHub Actions (GitLab CI "until users need it") | v0.1 design spec non-goals |
| V2-33 | Optional language-specific lint adapters (for example Power of 10 for C) | v0.1 design spec ("arrive later") |

Not candidates for any framework release: hardware tuning of this repository's machine (inventory V2-53: suite and mutant slots, locks, worker cap, slot cleanup), the two items dropped as build-state workarounds (V2-54), and the lap-timer migration (V2-55, a separate project).
| V2-35 | Strict pre-commit cell: run_all plus the touched tests on every supported runtime (deferred by the owner 2026-11-26: "running on pr is ok even for strict mode") | v0.1 design spec; v0.2 design notes |
