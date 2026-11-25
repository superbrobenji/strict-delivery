# v0.2 design notes (working record of the owner conversation)

Status: working notes, not the spec. Each decision is quoted or paraphrased from the owner, dated, and carried into the v0.2 design spec. Inventory: `.superpowers/sdd/2026-10-31-strict-delivery-framework/v02-inventory.md`.

## Scope and order (2026-11-26)

- In v0.2: inventory groups A (V2-01..05), B (V2-06..09, V2-24), C (V2-10..23, V2-36, V2-39..42), D (V2-26..29, V2-34, V2-35, V2-37, V2-38, V2-43..49), F (V2-50, V2-51), plus B1 (mutants on changed lines, targeted fix-round re-runs, at most 10 final-review mutants) and B2 (the merge check takes the stream suite plus CI, no third suite run).
- v0.3: group E (V2-30..33), tracked in `2026-11-26-v03-candidates.md`. Out of every release: hardware tuning (V2-53), the dropped build-state items (V2-54), the lap-timer migration (V2-55).
- V2-25 (stale open findings on main) is v0.1 work.
- Stage order: B (the tool gaps "slow everything down"), then A, C, F, D. Each stage merges before the next starts.

## Success and failure (2026-11-26)

- Failure, owner's words: "if it takes as long as v0.1 did, if it made no improvements to delivery time while maintaining quality standards, if i have to change the spec halfway through due to improper planning that wasn't thorough enough."
- Target: under one week from the approved plan and breakdown (step 6) to the v0.2 tag, excluding usage-limit stops, with an extra week of leeway. Steps 1-6 (conversation, design spec, reviewer check, owner approval, plan with every coverage table, breakdown, owner approval) are planning.
- Quality bar unchanged: the same gates, zero-bug rule, task and final reviews, mutation evidence, verifier pass. Speed comes from B, F and better planning only.
- Time-use targets (this build's `time-targets.md`) also apply to v0.2 and are reported daily; planned-versus-actual is tracked from day one; a spec change after approval is an owner question with its cause recorded.
- Every new feature is discussed and planned properly with the owner before it enters the spec.

## Feature decisions

### V2-08 Closing findings (2026-11-26)

- Owner: "close it automatically once the fix merges and its test is pinned"; option (a) "computed, not written", "including the squash fallback and other 2 edge cases".
- `findings.effective_status(record)` is the one function every reader uses (register gate, `findings list`, INDEX open findings, loopstats, doctor). It returns closed when (1) the record's fix commit is reachable from the base branch (one `git rev-list` over the base per run), (2) the pinned test exists on the base, and (3) the pinned mutation transcript exists and shows that test failing with the fix reverted. Otherwise: "fixed, waiting to merge" (fix not on the base) or "fixed, owes a test" (merged, no pin). The record file is not rewritten.
- Squash or rebase merges: when the fix commit is not on the base, the fix is accepted when a base commit carries the same patch (patch-id match) and the pinned test is on the base; otherwise the record stays "waiting to merge" and doctor flags it.
- A fix reverted later: the record still reads closed; the pinned test fails in CI, which catches the regression as a new finding.
- Records with no pin (most of today's open ones) show "fixed, owes a test" until pinned; nothing is closed silently.

### V2-06 and V2-07 Who found a finding; loop statistics for inherited and pre-review findings (2026-11-26)

- Owner: "yes go with that" (on the recommendation below).
- Every finding record carries two fixed facts: `found_by` (implementer, task_review, final_review, verifier, other) and `found_in` (task id and round where it was first raised). The owner (`owner.task`) may move; these two never change. This is also V2-06 (review kind).
- `loopstats` counts only findings with `found_in.task` equal to the task and `found_by` a review of that task; every other finding of the task is printed on a separate line, for example `carried in: 3 (4d.1 r5: LOW x3), pre-review: 1 (MEDIUM)`, and never enters X, W or the verdict.
- A task reaches CLEAN only when every carried-in and pre-review finding is fixed or registered against a named task (zero-bug rule): they cannot stop or prolong the loop, but they block the sign-off.
- The rework share and the late-findings measure come from the same facts: a finding first raised by a final review or verifier in code a task review already passed counts as late (target under 20 %).
- Rejected: counting carried-in findings at a lower weight (mixes two questions; arbitrary weights).

### V2-09 Empty brief sections (2026-11-26)

- Owner: "yes both match, go ahead".
- `check dispatch` fails every required section (Role, Brief, Findings, Claims, Budget, Model, Report, Task) whose body is empty or whitespace only, one line each: `FAIL dispatch.section.<name>: empty`. A section saying "None." has content and passes. The strict block keeps its byte-for-byte check.

### V2-24 This repository's nonconforming handoffs (2026-11-26)

- Owner: "yes both match". Treated as v0.1 data clean-up (the program controller's owed handoff/1 rewrites, docs PR); V2-04 (handoffs written only by the checkpoint tool) prevents a recurrence in v0.2.

### V2-01 Class members in the finding record (2026-11-26)

- Owner: "yes that matches, go with members in the record".
- `findings new` takes each class member explicitly (`--member <text>`, repeatable), found by a search, not only the case hit; `gate_register` refuses a finding whose class has no members.
- The record holds `members: [{id, text, test, status, found_by, found_in}]`. A member is resolved when it names its test; the finding cannot close (V2-08) until every member is resolved, so class-completeness is checked by the tools.
- A member found by a later review is added to the same record with its own `found_by` and `found_in` (it feeds the late-findings measure); it does not become a new finding.
- Records without a member list (older ones) stay valid and count as one member until edited.

### V2-02 Hardening section in every coverage table (2026-11-26)

- Owner: "yes that matches, go with the fixed section".
- Every input-domain table has a fixed hardening section listing the standard cases (symlink target; directory; FIFO or special file; a parent swapped after the check; equal or nested configured paths; non-UTF-8 names and contents; outside the root). Each case is a row with its test or `not applicable: <reason>`.
- `check dispatch` warns (does not fail) when the section is missing or a case is unanswered, naming the cases; the warning shows in the dispatch result and the ledger. The reviewer checks every "not applicable" reason.
- The standard case list lives once, in the base playbook, so a new case updates every checklist.

### V2-03 Schemas from the first record (2026-11-26)

- Owner: "yes that matches, go ahead".
- Gate rule: `check schema` fails any file under a framework record directory (findings, decisions, claims, plan state, programs, mutation transcripts) that no registered schema covers; free-text locations are listed as exceptions in config. A new record kind cannot be committed before its schema.
- Planning rule (plan_writer, controller, plan-review checklist): a schema and its producer registration land in the same task as the first writer of that record, or earlier, never in a later registry task.
- Older free-form records stay excluded by name (owner Q-RS1-1 (a)).

### V2-04 Handoffs written only by the tool (2026-11-26)

- Owner: "yes that matches, go ahead".
- `python3 -m gates checkpoint write --plan <slug> ...` writes handoff.md from fields (block, next steps, live subagents, required reads, ...) and refuses missing or bad fields with a named error.
- The Edit/Write hook (pre_edit, on main from PR-tools) refuses a direct edit of a handoff.md under the plan-state directory; the refusal names the command.
- `doctor` and the checkpoint gate report a nonconforming handoff with the failing field.
- Escape: the existing rule-override decision can allow a direct edit in an owner-recorded emergency.

### V2-05 gates timeuse (2026-11-26)

- Owner: "yes that matches, go ahead".
- Reads the project's local Claude Code transcripts only (never sent anywhere), with the rules of this build's timeuse.py: tool calls timed and categorised, model turns attributed by role, controller waits on children not double-counted, suspended time counted as idle.
- `python3 -m gates timeuse [--day YYYY-MM-DD | --since ...] [--json]` prints the agent-hour shares and the flow measures (budget endings, controller start-up, fix rounds per task, late findings from V2-06).
- Optional `timeuse.targets` in config: a share outside target prints WARN, never fails a gate.
- One time-use line in each checkpoint/handoff; the program status page shows the latest shares; two days outside target is suggested as an owner process question.
- An unrecognised transcript shape prints "transcript format not recognised" instead of numbers. The HTML pie page stays this repository's local convenience.

### Stage C, the recorded fixes (2026-11-26)

- Owner: "yes git 2.30, plain fixes for the rest".
- V2-10: one shared safe-read helper for the "file read by path after a check" class (UF-1, UF-3, UF-4, U6, U8), one test per member.
- V2-11..22, V2-21, V2-23: plain fix tasks grouped by area (shell quoting of the printed git command; unmerged path listed once; identical help heading on 3.9 and 3.13; parser argument by keyword; table renderer code span; run_all import-check order; decisions scanner grammar; integers over 4300 digits; output stream; import failure kind; breakdown syntax; stale skill prose; the docs claim about agents kept alive). Full case lists and hardening rows; no behaviour change beyond the fix.
- V2-39..42: the four approved, never-scheduled tasks carried in as written with their existing findings.
- V2-36: the minimum git version is 2.30; `doctor` reports an older git and the gates refuse with a clear message.

### Stage F, CI and mutation rules as framework rules (2026-11-26)

- Owner: "yes that matches" (profile split), then "any CI in the framework should be optional for users with a proper backup" and CI jobs "named in a way that identifiable and easy to understand", then "yes that matches, go ahead".
- init's CI template: the suite in parallel shards per os/python with each "all tests passed" job failing unless every shard passed; a mutation job running every planted-bug table the PR adds or changes (CI3 format, validated: a table naming a missing test or line is refused). The shard splitter and mutant runner ship in the framework.
- Profiles: light = no mutation job, one CI full suite; standard = mutants per PR on changed lines; strict = standard plus at most 10 targeted final-review mutants and fix-round re-runs (B1).
- Rules text: the full suite on a PR head is CI on that exact head; mutation results are read from CI; the merge check takes the stream suite plus CI, no third suite (B2); reviewers may run at most 5 local spot mutants.
- CI optional: init asks; config `ci: github | none` (per job kind: suite and mutants may differ). Fallback: `python3 -m gates suite` and `python3 -m gates mutants` run locally and write a result record bound to the exact head (head sha, interpreters, counts, pass/fail); the merge check accepts it for that sha only and refuses a stale or missing one. Worker counts and run locks are config with safe defaults; this machine's values stay in the repository playbook.
- Names: every job `strict-delivery: <what it does> (<where>)`, e.g. "tests 2 of 5 (ubuntu, python 3.9)", "all tests passed (ubuntu, python 3.9)", "mutation tests 1 of 4 (ubuntu, python 3.9 + 3.13)", "mutation summary", "process gates (ubuntu, python 3.13)", "pull request checks"; a test pins the form; `upgrade` handles renaming checks that branch protection requires. This repository's CI is renamed in v0.2.

### V2-26 Cleanup: clean and lean (2026-11-26)

- Owner: "everything that's no longer needed should be removed. everything should stay clean and lean. we do not ever want dead files or folders building over time"; history kept "for a specified amount of time ... default of 6 months and make it a user config that's also asked at init"; "yes that matches, go ahead".
- Automatic at a plan's last merge (post-merge step): mark the plan merged (INDEX moves it to Done; stream tooling stops treating it as live); remove its clean worktrees; delete its branches local and remote once each is confirmed merged into the base; remove framework-registered scratch and temp directories (mutant slots and the like); remove its dead live files (handoff.md) in the cleanup commit.
- Never automatic: a dirty worktree or a branch with commits not on the base is reported, never deleted; nothing the framework did not create is touched.
- Standing sweep: `doctor` and `gates cleanup --check` list stale items anywhere (worktrees of merged branches, merged branches, old framework temp dirs, untracked files in record directories); `gates cleanup` removes the safe ones.
- History retention: `cleanup.history_retention` (default 6 months; `forever`; `0` = at merge), asked by init. When it passes, the sweep opens a cleanup PR that removes the merged plan's ledger, finding and decision records and mutation transcripts from the working tree (git history keeps them; doctor shows how to look one up). Never removed: in-force decisions, open findings, and records a live plan still references. The clock starts at the plan's MERGED line date.

### V2-27 Role rules gated before they break (2026-11-26)

- Owner: "all of those, gate every one of them"; "yes that matches, go ahead".
- Forbidden shell forms: the Bash hook refuses heredocs, `$(...)` other than mktemp, backticks, `<(...)`, rm, `sed -i`, `python3 -c` and `python3 -`, direct `python3 -m unittest`; config `bash.forbidden` (strict profile defaults to this list); each refusal names the rule and the allowed alternative and is logged.
- Placeholders: the Agent hook's dispatch check refuses placeholder text (PLACEHOLDER, TODO, <...>, FILL IN and the like) in a brief.
- Coverage table: implementer and reviewer briefs must name the task's input-domain table by path and sha256; missing or mismatched is refused.
- Stopping runs: the runners write a per-job state file (waiting / started); the hook refuses stopping a started run and allows stopping a waiting one.
- Foreign checkouts: each dispatch names the agent's worktree; the Bash hook refuses state-changing git commands (merge, checkout, commit, reset, stash, branch) aimed at any other checkout, by cd, `git -C` or the working directory.
- Finding states by role: `findings` commands check the caller's role from its dispatch (implementers cannot close or pin their own findings; only reviewers record findings; only controllers repoint owner.task); the role table lives in the base playbook.
- Every refusal names rule and alternative and is counted in time-use; an owner override decision can lift one refusal.

### V2-28 Playbook methods gated (2026-11-26)

- Owner: "all of them, gate every one".
- Table rows name real tests: every test a coverage table names must exist (test defs, both interpreters' discovery).
- No weakened assertion in a fix: a fix commit that deletes an assertion or replaces it with a weaker one fails unless the change is recorded and approved (a decision or the review's explicit acceptance).
- Pinned behaviour has its mutation transcript: covered by V2-08.
- Commit messages: a commit-msg hook checks the conventional type, a task or finding id, and the attribution line.
- Cross-stream test-literal edits stay exact unions: a merge with a test-literal conflict keeps every line of both sides.
- Reports carry their required sections (status, claims, findings, budget): the report schema is checked at commit.
- Tests call the production path: stays a reviewer judgment, plus a warning when a test imports a private helper of the code under test.

### V2-29 Config keys become required (2026-11-26)

- Owner: "yes that matches, go ahead".
- `config/3`: every key whose reader exists is required; keys nothing reads are refused (a typo cannot silently do nothing). New v0.2 keys: `ci`, `cleanup.history_retention`, `timeuse.targets`, `bash.forbidden`, runner limits.
- `upgrade` migrates config/2: fills defaults, asks for the init-asked keys (history retention, CI), shows the diff before writing (managed.py overwrite, 4e.1).
- Until upgraded, gates read config/2 with defaults filled and doctor says "config/2: run /strict-delivery:upgrade".
- Rule: a key enters config in the task that adds its reader (as V2-03 for schemas).

### V2-34 Pressure-test scenarios (2026-11-26)

- Owner: "all of those, make a scenario for every one"; "yes that matches, go ahead".
- One scenario each: flake claimed without proof; merge on a red check; skip mutants because "it is small"; "too small for the process"; get around a refused command with another tool; stop a run early. Each is a fixture repository plus a prompt that sets the trap.
- Run headless (`claude -p`) with the skill and the role's strict block loaded, on each model the process uses (sonnet implementer and reviewer, opus controller and final reviewer).
- Judged mechanically from the transcript's actions (forbidden merge or command run, step skipped, second tool used, or the stop and owner question written); no model grader.
- `python3 -m gates scenarios` on demand, and automatically before a release and when a prompt block or the skill text changes; opt-in (token cost), never per PR.
- Every new rule break seen in a real build becomes a scenario.

### V2-35 Strict pre-commit test cell (2026-11-26)

- Owner: "i think we can defer that rule. running on pr is ok even for strict mode".
- Not in v0.2. For every profile, pre-commit runs `run_all` only; the tests run on the PR (CI, or the local fallback record). The v0.2 spec amends the v0.1 spec sentence for the strict cell accordingly. Tracked in the v0.3 candidate list as deferred.

### V2-37 Checks on merge and cherry-pick commits (2026-11-26)

- Owner: "yes that matches, go ahead".
- init and upgrade install a `pre-merge-commit` hook running the pre-commit checks; a merge that would break run_all is refused before its commit exists.
- The Bash hook refuses a plain `git cherry-pick` and a plain `git revert` (both create a commit without the pre-commit hook) and names the form that runs the checks: `--no-commit` then `git commit`. `git commit --amend` already runs pre-commit and needs nothing (correction 2026-11-26: the first wording listed it in error). Which git commands skip which hooks is verified against git 2.30 and the current git during planning.
- A human cherry-pick outside an agent still skips local checks; CI's process-gates job catches it on the PR, and doctor documents the gap.

### V2-38 Program status view (2026-11-26)

- Owner: "that looks good. also add a done list".
- Header: program, progress (tasks done/total, PRs merged/total), planned versus actual ("day 3 of 7, 1 day behind"), the owner queue (open questions by id, oldest first), time-use shares against targets.
- One row per stream: stream, now (task and step), state (building, in review, fix round k, PR open, CI running, waiting, done), waiting on (owner question id, CI run, mutation slot, another PR), open PR and its CI, open findings by severity, last merge, planned versus actual.
- Below: the merge queue in order, main's latest CI result, and a done list (each merged PR with its tasks, merge time and merge sha, newest first).
- Everything derived from git, the records, the handoffs and CI; nothing maintained by hand. `python3 -m gates program status` prints it; the index tool renders it into the program status page.

### V2-43 Executable claims, claim/2 (2026-11-26)

- Owner: "yes that matches, go ahead".
- A claim/2 record stores the direct check (command, expected result) and the disproof check (command, the result that would show the claim false); results match by exit code and a pattern, not exact text.
- `python3 -m gates claims run` re-runs every claim at the current head and reports which still hold; the claims gate runs the ones a PR depends on, so a merge cannot rest on a claim that no longer holds.
- Claim commands obey the Bash hook rules (read-only: no state-changing or network commands) with a per-command time limit.
- claim/1 records stay valid as text and show "not executable" until upgraded.

### V2-44 Interactive init (2026-11-26)

- Owner: "yes that matches, go ahead".
- `python3 -m gates init --interactive` asks each question in the terminal with its default and the answers-file validation (re-asks until valid), saves an answers file, shows the plan and asks before apply.
- The slash command asks the same questions in chat, one by one, from the same list.
- One question list in code (id, text, default, validation) generates the terminal prompts, the chat prompts, the answers-file schema and the docs.
- Without a terminal (CI, a pipe) `--interactive` refuses: "no terminal; use --answers".

### V2-45 Drift for plain plans (2026-11-26)

- Owner: "yes that matches, go ahead".
- `check drift --plan <slug>`: the plan branch behind the base (with the exact safe update command, the 5c/5c.3 advice text); the handoff's current block and next tasks against what is committed and merged; the plan's status rows against git; planned versus actual time in the program-view form.
- Read-only, a short report; run by the SessionStart hook and on demand.

### V2-46 context.enforced as a profile key (2026-11-26)

- Owner: "yes that matches, go ahead".
- Profiles state `context.enforced` explicitly (strict true; standard and light false); a project overrides it in config like any profile key (an override decision when it loosens strict); doctor shows the effective value and its source. No behaviour change when unset.

### V2-47 Orphaned agents (2026-11-26)

- Owner: "yes that matches, go ahead".
- Orphans: an agent recorded started by the Agent/SubagentStop hooks with no handback whose parent has ended; an agent a handoff lists live that the hooks show finished or silent past a limit; a runner job whose state file (V2-27) shows it running with its owner gone.
- Checked at session start, at every checkpoint/handoff write, and by doctor; each orphan printed with role, task, last activity and the suggested action (resume, wait, let its job finish). A handoff cannot be written while an orphan of that controller is unexplained.
- Never kills or stops anything; ending work stays a controller or owner decision.

### V2-48 Bash hook limits (2026-11-26)

- Owner: "yes that matches, go ahead".
- Closed: a command that runs a script file (`bash x.sh`, `python3 x.py`, `./x`) has the file's text checked by the same rules (refusal names file and line); `gh` passes only allow-listed subcommands (unknown subcommands, aliases, extensions refused); a git subcommand that is not git's own is refused unless allowed in config.
- Documented as stated limits (docs and doctor): network access from inside programs, anything computed at run time. The hook is not a sandbox; the permission classifier and the user's permission settings remain the protections there.

### V2-49 Clean-update rule in the spec (2026-11-26)

- Owner: "yes that matches, go ahead".
- The v0.2 design spec states the rule in full: a clean update (no conflict; no changed path shared with the PR; no module named in the PR tasks' Consumes lines changed; gates pass on the merged head) needs only the gates re-run; a conflict in test literals only, each resolved as the exact union, needs a short review of the merge plus CI; anything else needs a delta final review (A1).

## Conversation status

- 2026-11-26: every v0.2 feature has been discussed with the owner. Next: the v0.2 design spec written from these notes, a builder check, then the owner's approval.
