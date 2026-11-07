# Session resume, owner questions and spec catch-up: design

Date: 2026-11-02, revised 2026-11-07. Status: approved 2026-11-02; revised and approved 2026-11-07 (owner 'looks good'). Line cites (P:, MS:, PD:, plan:, spec:) in this document name lines at commit 228c872, the text it was designed against; the splice of its edits moved them. Framework spec: `docs/strict-delivery/specs/2026-10-31-strict-delivery-framework-design.md` (here "main spec", MS). Programs design: `docs/strict-delivery/specs/2026-10-31-programs-and-streams-design.md` (PD). Plan: `docs/strict-delivery/plans/2026-10-31-strict-delivery-framework.md` (P). Owner answers: ledger `.strict-delivery/state/plans/2026-10-31-strict-delivery-framework/ledger.md` (L), the lines from "Owner 2026-11-02 directive: scrap all post-/clear work" on. Root-cause input (provenance only, a git-ignored dispatch note): session-resume-investigation.md in .superpowers/sdd/2026-10-31-strict-delivery-framework/ (PC-R1 to PC-R5, adopted). Precedence check (provenance only, a git-ignored dispatch note): post-clear-answer-check-2026-11-03.md in the same folder (rows X-n).

**Precedence rule (owner, 2026-11-03):** where an answer given after the 2026-11-02 `/clear` contradicts, narrows or widens a pre-existing owner answer, ruling or settled plan or spec text, the pre-existing text wins ("the ones found was planned with better information"). This revision applies it to every such row (X-7, X-10, X-11, X-12, X-15, X-17, X-19, X-20, X-27, X-30, X-31, X-34, X-36, X-38, X-41, X-43), with the owner's answers Q-X27, Q-X35 and Q-X37 (L, 2026-11-07) where the record could not decide.

Everything here is a framework feature (spec and plan), not only this repository's process. This repository applies it by hand until the framework delivers it.

## 1. Intent

Three problems, one design.

**Resume.** After the owner's `/clear`, a fresh session started from a committed handoff did not continue where the last one stopped. It acted before reading, trusted an incomplete handoff, took agents with live background jobs as finished, and never loaded the superpowers skills. The owner's words: "the new session should have picked up exactly where the previous one left off. it shouldn've known were to look for missing context. the skills should've pointed it in the right files and folders. it shouldn've done it's research before making any edits at all. then take over and continue with the plan. starting the next streams or resuming in progress ones as they were. the whole point of this framework is for this very problem to never happen." The investigation found why: the old session ran about 52 hours in one context and never checkpointed (RC1); the handoff was free-form and told the reader to read less (RC2); nothing told a resumed session to load skills or research first (RC3); no one checked agents' background jobs (RC4); "safe to clear" was said with no check (RC5). Under the precedence rule the framework keeps its pre-existing answer (L:81; PD §2, §4.4; MS §8): no `/clear` and re-prompt at any level, the main session included. The safeguard therefore covers what still starts a context with no memory: a compaction, a lost or new session, and every continuation agent.

**Owner questions.** Questions reach the owner in batches from several agents. When a new batch arrives before the last is answered, the owner must not scroll up to find the earlier ones. Each question needs one fixed shape with a recommended option, and the printed batch must be deterministic.

**Spec catch-up.** Rules, methods, formats, owner answers and rulings were decided in dispatch notes, the plan or the ledger and never reached the specs; the per-entry context-reads design is the owner's example. A review of every note in the git-ignored dispatch-note folder .superpowers/sdd/ (provenance only; Q-SDD-1, Q-SDDT-3) found them; Appendix S lists every one with its target section, and all of them enter the specs with this design (Q-SDDT-1), as amended in Appendix S's answer block.

Success, in the owner's words: the context stays "smaller and runs a bit cheaper per run on a very long running session", and the design "prevent[s] hallucinations and context drift".

## 2. Goals, non-goals, anti-goals

Goals:
- After a compaction or in a new session, the main session continues exactly where the last context stopped, reading the default load, the start order and what the handoff names, no more.
- No agent is taken as finished while it still has a background job.
- Every printed owner question has the same fields; a new batch never hides older open questions.
- An agent restarts as soon as its own questions are answered.
- A question is asked only after the framework's search-before-asking method finds no answer (MS §7.4, ruling R-rev3-2).

Non-goals:
- Reading the whole repository at every resume (owner: "it doesn't have to read every file every time"). The full read of 2026-11-02 was a one-off recovery.
- Changing automatic continuation or the no-`/clear` rule at any level (PD §4.4, L:81).
- Changing who owns or answers a question.

Anti-goals (a failure even if it technically works):
- A resumed session that edits or dispatches before it has reported its findings, or carries on past a difference between the handoff and the real state.
- A checker that fixes what it finds.
- A printed batch whose content depends on the session's memory.
- Guesses shown to the owner without a check against the repository (owner: "always check before guessing").

## 3. Decisions

### 3.1 The resume flow (PC-R2)

A session that starts with no memory of the work (a compaction, a new session, a continuation):

1. Loads every skill the handoff lists under `skills`, in order (3.5).
2. Reads the default session load and start order (MS:372 `in-force.md` and the open decisions; MS:427 the context list; PD:249-250 for a program session: the CLAUDE.md block, `in-force.md`, `INDEX.md`, the live programs' status pages, `python3 -m gates context program`), then the handoff's `required_reads` (paths, with line ranges where given) and the ledger from `ledger_from` (X-7). A program session holds no detail and re-reads the overview and status pages after any compaction (PD:125-127, X-10).
3. Has every handoff fact checked against the real state, read-only, by an agent of the existing `investigator` role: branch heads (a recorded head is an ancestor of the live one, as P:1905's `checkpoint.head` rule), each worktree's status, whether the ledger is committed, and, for each `live_subagents` entry, its transcript's last record and its background job ids. The checker changes nothing and reports findings to the main session.
4. Records the check as a prose ledger line (no new ledger keyword: Q-Pplan-1 (a), X-19).
5. Reports to the owner a short "where we are, what I will do next", with the checker's findings. No edit and no dispatch happens before this report.
6. With no differences, takes over at once: starts the next streams or resumes in-progress ones as they were. With any difference, it stops and waits for the owner (skill text, not a hook: X-20).

### 3.2 The handoff (PC-R1)

No new handoff kind (X-17). A plain plan's controller session resumes from its plan's `handoff/1` (MS:177, MS:427); a program session keeps no handoff and resumes from the overview and status pages (PD:125-127, PD:249-251). `handoff/1` (Task P1.2) gains: each live agent's task, worktree, last record and background job ids with their state (`live_subagents` as entries, not bare strings); `worktrees` (path, branch, head, `git status --porcelain` output); `required_reads` (path, optional line range, why); `skills`; `ledger_from` (the ledger line after the last `CHECKPOINT`); question items gain `recommended` and `source`. For a program, the status page carries the facts a program session must check that the stream handoffs do not (the plan's choice of fields). The handoff never tells the next session to read less than the default load plus `required_reads`.

### 3.3 Checkpoints (PC-R3)

The pre-existing triggers stand for every controller, the main session included, since in a plain plan the main session is the plan's controller (MS:271, MS:430): one block per agent context, at most `block.max_tasks` tasks, and a checkpoint at a block or task checkpoint, 80 % of the token or time budget, or a usage-limit stop (controller block "Continuation.", MS:405; X-11). No limit has a default (Q-H2, P:1449; X-12). A checkpoint rewrites the handoff, commits handoff and ledger after the commit gate (P:33), and writes the `CHECKPOINT` line. "Safe to clear" is never said (no `/clear` at any level); a claim that a handoff is complete carries the output of `git status --porcelain --untracked-files=all`, the handoff field check and the background-job check (RC5).

### 3.4 Background jobs (PC-R4)

Before ledgering an agent's result, the controller lists the agent's background job ids from its transcript. Each has a completion record, or is stopped with TaskStop and the stop is ledgered. A notice that an agent "is waiting on its own background work" leaves its task open. Workers: a poll loop has a bounded timeout and never matches its own command line; a job no longer needed is stopped with TaskStop, not `pkill`; the report lists each background id as `finished` or `stopped`.

### 3.5 Which superpowers skill for which change (PC-R5)

A new rule, feature or format with no settled design goes through superpowers:brainstorming to an owner-approved design, then a spec edit. A plan change goes through superpowers:writing-plans against the spec. Execution goes through superpowers:subagent-driven-development or superpowers:executing-plans under the strict blocks (P:3; X-15). A controller that has not invoked the skill for the change in its current context does not dispatch a writer for it.

### 3.6 One owner question

A printed question shows: id, class, the question, the recommended option with its cost, every alternative with its cost (no cap on alternatives), effect, topics, applies_to. Tool-only fields are not printed (schema, status, asked_at, asked_by, checked_against, supersedes, source). At least two options, as today: one recommended plus at least one alternative. A recommended option is required for every class except `model-policy`, whose questions carry none. Before a question is asked, the search-before-asking method runs (MS §7.4, R-rev3-2, L:103): candidates from the question's topics, paths and words of at least 4 characters, over the decision records and, until the tool exists, by hand over the ledger, the plan's owner answers and "Owner answers applied" lines, the breakdown and its edits, both specs, and the history of every line the question quotes; a question found answered is not asked. decision/2 (Task 2a.1) gains the recommended option and an optional `source` field (Q-X27 (a)).

### 3.7 Batches

- Each group's questions are reported as normal.
- When a new batch arrives while earlier questions are open, the message has the new batch, then a section "Also open" with every earlier open question, given whole with the same fields. Owners, areas and ids do not change; the section is for reading ease only. An answered question drops out.
- Within each section, questions are grouped by `source` (the report or handoff the question came from), one header per source; `topics` stay subject tags for `find` (Q-X27 (a), X-27).
- The batch is printed by a tool from the open decision records, so it is deterministic. New batch = open records whose files did not exist at the cut-off commit; all other open records go under "Also open". The session commits the new records, prints the batch, and records the commit's sha as the next cut-off in its handoff (no new ledger keyword, X-19). Printing writes nothing.
- Questions are batched at the next stop, never asked one at a time (P:53, MS:498).

### 3.8 Restarting agents

Each agent restarts as soon as every question with its `source` has an answered record; others in the batch may still be open (PD §4.1: "Only the asking branch of the tree waits; its siblings continue"). By position in the tree (PD §3, Q-H5 (a) default):
- A worker or reviewer stopped with `NEEDS_DECISION` and returned: its controller dispatches a fresh agent of the same role whose brief carries "Owner answers (date), binding", printed by the tool from that source's answered records.
- A controller still alive waiting: the session tells it to continue (PD §4.3).
- A controller that handed off: `continue` (Task P4.2) builds a fresh one; it already refuses while any of that controller's questions is unanswered.

Only the session writes decision records; workers never do, and never change anything for a question. Fix and re-review rounds run until a clean pass (L:98, X-43).

### 3.9 The no-`/clear` rule

Unchanged (X-10): PD §2 (line 29), §4.4 and MS §8 (line 410) stand. Nothing in this design rewords them.

### 3.10 What is enforced and what is skill text (Q-DS-1, as limited by X-20)

Enforced by gates: `gate_checkpoint` checks the `handoff/1` fields of 3.2 and the head-ancestor rule. No hook holds the session (the Edit/Write hook "records nothing else and blocks nothing else", MS:150). Everything else (the resume flow, the stop on a difference, checkpoint triggers, the background-job procedure, the skill per change kind, search before asking, the batch format, restarts) is text in this repository's strict-delivery skill (`skills/strict-delivery/SKILL.md`, Task B2.3) and the playbook, with the interim project skill standing in until then. Superpowers stays unmodified (MS:85-89).

### 3.11 Spec catch-up rules (Q-SDDT-1..6, as amended)

- Every row of Appendix S enters the specs (Q-SDDT-1), with the amendments in its answer block.
- Divergences follow Appendix S section 2's directions, amended by the precedence rule (Appendix S answer block).
- PC1-PC5 are framework rules, in the base playbook and the spec (Q-SDDT-5).
- `plan_writer` and `plan_reviewer` stand as framework roles at tier3, with stream A's request to stream B for their prompt prose, as Q-B2plan-16 (a) set (P:7030; X-30; provenance only: the git-ignored block-2 draft, block-2-draft.md, line 916); the spec §10 role list gains them.
- Dispatches carry this repository's merged prompt blocks (`skills/strict-delivery/prompts/<role>.md` on `main`) verbatim, which supersedes the ledger L20 ruling (Q-SDDT-4, X-28).
- Controller rulings stay within MS:280-281 ("only plan-vs-spec or task-vs-task conflicts the spec settles"); row C-16 is read that way (X-31).

### 3.12 Interim, until the framework delivers

This repository gets a project skill and a `CLAUDE.md` with this repository's paths (Q-PCR-6 (a)); the user-level skill stays unchanged. The interim skill also carries, as a checklist, the by-hand form of every framework rule whose tool or skill text is not built yet, each with its cite, from the method audit (provenance only: the git-ignored dispatch note method-audit-2026-11-03.md in .superpowers/sdd/2026-10-31-strict-delivery-framework/; owner Q-AUD-1): at least the search before asking (MS §7.4), the verification method's contradiction check, `Ruling:` lines and their cap (MS:282), the full commit gate (P:33), the dispatch grammar for every role, the 80 % budget line, the report contracts, the fix loop and D30, the small-re-review rule (L:406-408), PC5 class statements, owner batching (P:53), relaying each finding's substance, and the main session following the controller block.

## 4. Where it lands (checked against the plan and specs)

| Piece | Home | Status of that home |
|---|---|---|
| Handoff fields (3.2) | `handoff/1`, Task P1.2 (plan:1809-1830); checked by `gate_checkpoint`, Tasks P1.3 and 6K; program facts on the status page (Task P2.1) | planned |
| Resume steps (3.1) | `playbook/sessions.md` "Start order" and "Handoffs and continuation" (Task B2.2, plan:6140-6142); SKILL.md "Continuation" (Task B2.3); SessionStart hook text, every source (`startup`, `resume`, `fork`, `clear`, `compact`, absent or unknown; owner answer Q-RA2-1 (c)) (Task 3a.2, plan:2765, 2780) | planned |
| Checkpoints (3.3) | controller block "Continuation." and "Merge and checkpoint." (`skills/strict-delivery/prompts/controller.md` on main), unchanged triggers; MS §8 | merged |
| Background jobs (3.4) | every role's "Background work." paragraph; MS §8 line 413 | merged; spec line has no procedure |
| Skill per change kind (3.5) | SKILL.md (Task B2.3); `playbook/sessions.md` "Planning" (Task B2.2) | planned |
| Question record (3.6) | decision/2 with `recommended` and `source`, Task 2a.1 (plan:882) | planned, not dispatched |
| Search before asking (3.6) | MS §7.4 (unchanged); `decisions find`/`ask`, Task 1d.1; by hand until then | planned |
| Printed format, batches (3.6, 3.7) | MS §7.1; `playbook/decisions.md` "Asking" (Task B2.2); `decisions batch`, Task 1d.3 | planned |
| Program-level batches | `questions list` and `ask`, Task P4.1 | planned; same printed format |
| Restart (3.8) | Task P4.2 `continue`; controller block "Continuation." | planned / merged |
| Interim skill and CLAUDE.md (3.12) | Task 1c0.2 | planned |

Constraints found in the repository that the plan must respect:
- decision/1 options are exactly `{label, cost}` (`tests/test_decisions_lib.py` T14); `recommended` and `source` are decision/2 changes, with the migration.
- The open-decision scan (`gate_decisions`) fails on any open decision id in `docs/**`, `CLAUDE.md` or the playbooks; a printed batch is stdout only.
- `gate_cites` checks every tracked lowercase `*.md`; the interim `CLAUDE.md` and this document cite only paths that resolve.
- No limit gets a default (Q-H2, P:1449).
- The ledger keyword set stays Q-Pplan-1 (a)'s five (P:7040).
- The interim `CLAUDE.md` carries no lines that look like the managed-block markers (Task 4c.2; Rq-4-5).
- Prompt-block tests pin key phrases and forbid model names, owner handles, row ids and lap-timer paths in blocks.
- Plan rule Q-BD-6: this design and its plan edits go in a docs-only PR.
- Shape changes are new schema versions with a migration (MS:592-593; Q-X37 and F-RDr3-1 apply it to `hook-session`).
- Pace: stop at about 95 % weekly usage (L:408; X-41).

## 5. Calls made by the controller (owner to check)

- One design document for the three problems.
- The new decisions subcommand is `decisions batch --since <sha>`; P4.1's program-level output uses the same printer. It reads the records in the working tree of `--root` (the integration worktree for a program). With no recorded cut-off, or one that is not an ancestor of HEAD, every open record is "new". Existing decision/1 records migrate with no recommended option and no source; the tool prints them without either.
- The cut-off sha lives in `handoff/1` (`batch_cut`) for a plain plan; for a program, on the status page. Field names are the plan's choice.
- `ledger_from` is a ledger line number, recomputed by any migration that renumbers the ledger (P1.3 Step 5).
- The interim project skill is `strict-delivery-repo` under `.claude/skills/`; the interim `CLAUDE.md` states that this repository's paths replace the user-level skill's lap-timer paths and names both skills. The interim files are removed when block 3 enables the plugin and when Rq-4-5 lands the managed block, by the streams that own those paths then (`residual`, `init4`).
- This repository applies 3.1-3.8 by hand from approval on: `handoff.md` carries the new fields in its body until P1.2 gives `handoff/1` its schema, and batches are written by hand in the 3.7 shape until the tool exists.

## 6. Left to the builder (writing-plans)

- Exact field names and types in `handoff/1`, the status page and decision/2, and the migrations.
- The read-only check's brief and fixed question list for the investigator.
- Test cases and input-domain tables (PC1) for each changed task.
- Which existing tasks are edited and which new tasks are added, per stream ownership, with the stream breakdown updated.
- The exact spec and playbook wording, within the decisions above.

## Appendix S. Spec catch-up catalog (owner answers Q-SDDT-1..6, Q-CAT-1..8)

Every row below enters the specs as part of this design (owner answer Q-SDDT-1). Built by a read-only investigator from the nine SDD audit reports; controller spot-checks: all 123 source ids placed once, quotes at MS:104-105, MS:396-397, L:98, P:3358 re-read.

Abbreviations: MS = `docs/strict-delivery/specs/2026-10-31-strict-delivery-framework-design.md`; PD = `docs/strict-delivery/specs/2026-10-31-programs-and-streams-design.md`; P = `docs/strict-delivery/plans/2026-10-31-strict-delivery-framework.md`; L = `.strict-delivery/state/plans/2026-10-31-strict-delivery-framework/ledger.md`; DD = this design `docs/strict-delivery/specs/2026-11-02-session-resume-and-questions-design.md`. Note folders: N = .superpowers/sdd/2026-10-31-strict-delivery-framework-plans/, F = .superpowers/sdd/2026-10-31-strict-delivery-framework/, B = ...-framework-b/, C = ...-framework-c/, D = ...-framework-d/ (every note folder here is git-ignored; its files are named as provenance only), PR/x = `origin/main:skills/strict-delivery/prompts/x.md`.

Class key: OA = owner answer or directive; CR = controller ruling; M = method; CV = convention; FMT = format.

Owner answers on this appendix (ledger, 2026-11-02, "recommended for all is good"):
- Section 3: N-1 adopted (Q-CAT-1); N-2 rejected (Q-CAT-2); N-3 adopted (Q-CAT-3); N-4 adopted (Q-CAT-4).
- Section 2, overriding the directions in the table where they differ: V-3, the spec gains the exception that shared hooks turn on once every live stream branch has the gate (Q-CAT-5); V-6, the spec is edited to the measured fact that the Agent hook's counts are approximate, advisory where exactness is impossible (Q-CAT-6); V-10, the catch-up states `PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX=<fresh dir> python3 -W error -m unittest discover -s tests -t .` on both interpreters (Q-CAT-7); V-11, the spec states both: a cosmetic item (no change of meaning) is not a finding and earns no fix round, a minor is a real defect, fixed, never deferred (Q-CAT-8). Every other divergence follows the table's direction (Q-SDDT-2).
- Amended 2026-11-07 by the precedence rule (owner, 2026-11-03) and Q-X35, Q-X37: N-3 is dropped (MS:433, a receipt is stale after any edit, the session's own included; X-34); N-4 compares owned paths by case-fold and NFC through a frozen generated table, the same on every Python (Q-X35 (a)); V-3 follows MS:602 ("enabled as soon as it lands"), so the plan's rulings at P:876 and P:2631 are corrected to the spec (X-36; the skill's "plan-vs-spec is corrected to the spec"); V-6: MS:152 is edited to the measured fact, the hook's live counts are approximate and advisory where exactness is impossible (Q-X37 (a)); V-10: the test command stays P:33's (X-38). Row C-16 is read within MS:280-281 (X-31).
- Rows C-27 and C-42 do not exist (numbering gaps, nothing lost: all 123 source ids are placed).
- Source ids (F-SDD...) and note cites (N/, F/, B/, C/ prefixes) point at the git-ignored review reports and dispatch notes of 2026-11-02; they are provenance, not required reads.

### 1. Catch-up items

#### MS §2 (what is not carried over) and shipped content

| id | rule | source ids | best note cite | plan | ledger | class |
|---|---|---|---|---|---|---|
| C-1 | No hardcoded model names, owner handles, absolute or old paths (`docs/superpowers`, `tools/gates`, ...), test filename patterns or secrets in shipped code, tests, manifests, templates or prose; no template-project rule in any wording; checked by a forbidden-pattern list, also with line breaks read as spaces (Q-B11-5). Exempt: the plugin manifest `repository` field and the plugin's own install line. | F-SDD1-2, F-SDD2-8, F-SDD4-3 | B/task-B1.1-brief.md:18-28; N/later-blocks-brief.md:14 | P:17, P:3279-3294, P:5763-5773 | L:119 (DB-3), L:164 (Q-B11-1..5) | OA, CV |

#### MS §4 (init, hooks, git hooks, CI)

| id | rule | source ids | best note cite | plan | ledger | class |
|---|---|---|---|---|---|---|
| C-3 | Detection: a proposal promises only what a narrow, fail-closed reader can state from the file text; an unsupported construct gives one `Problem` and no proposals from that file; repository state is out of scope; ASCII-only names; DC-1 seven-row source table; DC-3 detection reads `root` only; DC-4 always `npm run <name>`; Q-C11-1 an unreadable root is a `GateError`; Makefile names as listed, other sources only under their exact spelling. | F-SDD5-2, +F-SDD1-9 | C/task-C1.2-domain.md:13; C/task-C1.1-brief.md:7 | P:3358, P:6979-6982; main:P:2249, :2268, :2348 | L:119, L:181, L:245 (Q-C11r4-0), L:301 | OA |
| C-4 | `init`/`doctor`/`upgrade` behaviour: `--root` required, the plugin's own directory refused; the Python tool is not interactive (`init questions \| plan \| apply --answers F`), interactivity lives in `commands/init.md`; generated-file header on line 1 (line 2 after `#!`); a symlink at a target or parent is a conflict; inserted block appended at the end; `init` on an existing config asks no config questions and never rewrites it; no placeholder files; every answers-file key required; subagent limits only in `.claude/settings.json` `env`; `doctor` writes nothing; `upgrade` never removes plain `.gitignore` lines and edits only the `schema:`/`framework_version:`/`profile:` lines of a commented config. | F-SDD2-14 | N/block-4-draft.md:32, :72-88 | P:3357, P:3395-3415 | L:362 (Q-B4plan-1..7 (a)); the rest controller rulings | CR |
| C-5 | Hook output contract (ruling 3a): a refusal is exit 2 with the reason on stderr; a pass never prints `permissionDecision: "allow"`; every PreToolUse entry sets `"onFailure": "block"`. | F-SDD1-15 | N/block-3-draft.md:58 | P:2614 | none (controller ruling 3a) | CR |
| C-6 | The owner has a way out of every hook refusal, and the hook's FAIL text names it: `!`-prefixed commands still run; a corrupt session file is moved aside (`<id>.yml.corrupt-<UTC>`); the plugin is disabled with the owner's `/plugin` command until a fix merges; SessionStart sources `startup`, `resume`, `fork` reset. A review checks each refusal has a stated route. | F-SDDG1-5, F-SDDG3-3 | N/block-3-review.md:83-86; N/block-3-review2.md:62-72 | P:3322, P:2666, P:2765 | none | CR, M |
| C-7 | Git hooks and CI: `commands.test` as a string runs with `sh -c`, as a list as one argv; on strict an unset key fails (Q-B2plan-11); pre-push refuses unless the tree is clean and every pushed sha equals HEAD (Q-B2plan-12); `githooks install` refuses when `core.hooksPath` is set or a hook is foreign (ruling); every workflow `uses:` is pinned to a full commit sha (Q-B2plan-20). | F-SDD1-14 | N/block-2-draft.md:45, :904-909, :931-932 | P:875 | L:245 | OA, CR |

#### MS §5 (paths, evidence forms)

| id | rule | source ids | best note cite | plan | ledger | class |
|---|---|---|---|---|---|---|
| C-8 | `#` is refused in `<sha>:<path>` evidence paths and in cite anchors (Q-1b1r-4 (b)). | F-SDDG2-3 | N/task-1b.1-review.md:96-98 | none | L:188 | OA |

#### MS §6 (config, YAML subset, readers)

| id | rule | source ids | best note cite | plan | ledger | class |
|---|---|---|---|---|---|---|
| C-9 | The `limits` key: `max_children.<role>` (no cap by default, set in config only, tightened through `overrides`, keyed by the dispatcher's role, `session` an allowed key), `max_depth`, `max_concurrent`, with units (adopted spec edit SE-5, never applied); 2c.2 checks only shape, the key set is checked where `ROLES` exists (Q-2c2-1). No limit has a default (the L:424 main-session defaults are withdrawn by the precedence rule, X-12). | F-SDD1-3, F-SDD2-2, F-SDD5-5 | N/programs-draft.md:15, :850; N/block-2-draft.md:940-949; D/task-2c.2-domain.md:13, :123 | P:848, P:1449 | L:218 (Q-H2), L:245 (Q-B2plan-23), L:387 (Q-2c2-1), L:424 | OA |
| C-10 | `top_tier_fallback`: with `tier4` unset the top-tier roles run at `models.top_tier_fallback`, default `tier3`; a model named by two tiers fails (Q-B2plan-17 as amended by Q-B2plan-21). | F-SDD4-18, +F-SDD1-12 | N/block-2-draft.md:922-924; B/task-B2.2-domain.md:52 | P:1539, P:3361, P:4842 | L:245, L:250 | OA |
| C-11 | Config value rules: each `paths` value a non-empty, normalised, repo-relative `str` (no leading `/`, no `..`, not `.`, no non-printable character); `ids` holds exactly the four prefix keys, each `[A-Z]+`, all distinct (R-rev5-1); `base_branch` holds no run of more than 40 hex digits; empty `framework_version` refused; unknown key in a read mapping refused, extra `models.tiers` names kept; a mapping default given a non-mapping refused; missing file says `missing; run /strict-delivery:init`. | F-SDDG2-5, F-SDDG4-3, +F-SDDG1-1 | F/task-1a.2-domain.md:15-27; N/task-1a.2-brief.md:15, :21 | P:99 (non-printable rule not in P) | L:107, L:113, L:118, L:136, L:162 | OA, CR |
| C-12 | Unknown keys are refused in every schema (OQ-16). | F-SDD3-12 | F/task-1b.1-domain.md:176 | P:28 | none (P's owner answers 2026-10-31) | OA |
| C-13 | YAML subset rulings: a scalar on the line after `key:`/`-`, multi-line flow sequences and multi-line quoted scalars refused (D7); a tab after `:` or `- ` refused (U1); block-scalar header rules (U2); ` #` starts a comment outside quoted scalars and block bodies (Q-yamlsub-1); control characters emitted as `\u` escapes (D6); non-str input raises TypeError (D1); error wording is not a contract (D9). | F-SDD3-15 | F/task-1a.1-domain-filled.md:58-70 | Task 1a.1 | L:31, L:51, L:75 | OA |
| C-14 | Reader contract: stat and refuse a non-regular file, open `O_RDONLY\|O_NONBLOCK`, no fd left open; strip one leading BOM, CRLF to LF, bare CR refused; OSError/ValueError/TypeError (and a raising `__fspath__`, R8-b) become the reader's error, BaseException is not caught; markdown is read raw (no BOM strip); a `{path: ...}` symlink is read (Q-1b1-3), other symlinks refused, never followed. | F-SDDG4-5 | F/task-1a.1-report.md:90-91, :144-148; F/task-1a.1-domain.md:35-37 | partly (`O_NONBLOCK` in P) | L:43 (2), L:181 | OA, CR |

#### MS §7.1 (decisions, questions, rulings)

| id | rule | source ids | best note cite | plan | ledger | class |
|---|---|---|---|---|---|---|
| C-15 | The default owner-only classes have slugs: `triage`, `spec-direction`, `scope`, `merge-grant`, `model-policy`, `issue-close`, `finding-class`, `rule-override`, plus `profile-override` and the five program slugs. | F-SDD4-9 | B/task-B1.3-report.md:128 | P:6212 | L:276 (Q-U1), L:374 (Q-B23-1) | OA, CV |
| C-16 | Owner batch and plan-text conventions: question ids `Q-<scope>-<n>`; anything the spec or plan settles becomes a `Ruling:` not a question; keep the batch small; fail-closed option preferred; task text states the recommended option and is edited before dispatch if the answer differs; once answered the plan states one thing and dead (b) text is removed. (The recommended option itself and the printed shape: DD §3.6.) | F-SDD1-6 | N/later-blocks-brief.md:19; N/block-3-draft.md:807; N/docs-b1c-review.md:27 | P:53, P:1691 | none | CV |
| C-17 | `supersedes` and reference edge rules: `find` follows every superseded match (Q-1b2r-1 (b)); a self-superseding row counts nowhere (Q-1b2r-2); a fork of answered superseders raises GateError (Q-1b2-4); a withdrawn superseder is checked only for a missing target, itself and cycles (Q-1b2-3); `current` returns an unknown id unchanged and stops at the first repeat; the reference is the id of the row carrying the field (Q-1b2-2); whole-token matching (Q-rev2-2); a malformed status counts as resolved (CR); a review report's first line has one trailing `\r` stripped (Q-1c2-1). | F-SDDG1-3, F-SDDG4-7 | N/task-1b.2-rereview1.md:17-45; F/task-1b.2-domain.md:112-198 | P:23, P:344 | L:99, L:202, L:239, L:387 | OA, CR |
| C-18 | Scope-tag matching: a topic matches one `topics` entry after `casefold` (Q-1b2-5); `applies_to` uses `fnmatchcase`, `*` crosses `/`, `**/` needs a directory level (Q-1b2-6); `find --all` (`include_all`) does no replacement (Q-1b2-7). | F-SDD3-13 | F/task-1b.2-domain.md:201-212 | P:393 | L:103, L:202 | OA |

#### MS §7.2-§7.4 and Appendix A (records, claims, schemas, generated files)

| id | rule | source ids | best note cite | plan | ledger | class |
|---|---|---|---|---|---|---|
| C-19 | Claims: `gate_claims` never runs a claim's commands, checks both are recorded, cites resolve and the claim is fresh; claims carry no expected-outcome fields; freshness is a blob id per cite (Q-B2plan-4); the claim file slug is the path with `/` as `--` (Q-B2plan-2) and a claim document must be a `.md` path with no `--` (Q-2a2-1); a `claims add \| verify` tool (Q-B2plan-6, MS §7.3). The deletion rule is V-2. | F-SDD1-10, F-SDD2-9, F-SDD5-4 | N/block-2-draft.md:43, :884-895; D/task-2a.2-brief.md:110 | P:873, P:1026, P:7030 | L:245, L:387 | OA, CR |
| C-20 | Register folders and comparison: only `<id>.yml`, `index.yml`, `in-force.md`; symlinks refused; resolved records compared by parsed, type-strict content (1, true, 1.0 differ; key order ignored); a tree row is unchanged when it equals the base row before or after migration (Q-2a1-2); base-side non-record entries ignored, a non-parsing base record refused; cherry-pick is no collision; `str` subclass ids refused; mint exhaustion GateError naming prefix and date; ids checked before touching disk; exclusive create, the check-then-write symlink race accepted (next load refuses); replace via temp file and `os.replace`. | F-SDDG2-4, F-SDDG4-6, +F-SDDG1-1, +F-SDD5-4 | N/task-1a.3-report.md:28-32; F/task-1a.3-domain.md:16-60 | P:1068 (dimensions only) | L:141, L:150, L:153, L:387 | OA, CR |
| C-21 | Finding records: a superseded but answered decision counts as a deferred finding's `ruling` (Q-1b3-1), never one of class `merge-grant` (Q-1b3r-1 (b)); parent-link checks on resolved rows (Q-1b3-2); plain-path evidence on resolved unchanged rows not checked for existence (Q-1b3-3 (b)); the `owner` map with kind `plan\|issue\|roadmap`; the field list (incl. C-56's fields). | F-SDD1-18 | N/task-1b.3-brief.md:73-75; N/plan-rev3-review.md:37-41 | none cited | L:263 | OA |
| C-22 | Schema language: a field spec has `type`, `required` (default true), `nullable`, `required_when`, `absent_when` (with `required` refused), `min` an int >= 0, `items` with no conditions; the types `str, text, int, bool, enum, list, map, any-map, id, sha, glob, cite, sha-path` with their semantics; markdown table header byte-exact plus `\|---\|` separator (Q-1b1-2); `FAIL schema.context.<path>: missing` (Q-1b1-4); upgrade hint only for a matching kind and differing version. | F-SDDG1-4, F-SDDG4-8 | F/task-1b.1-domain.md:36-63, :92, :145; N/task-1b.1-report.md:22-24 | P:261, P:267-280 | L:105, L:181, L:187, L:188 | FMT, OA |
| C-23 | Generated files: index containers are lists sorted by id (Q-1c3-1); `\r\n`/`\r`/`\n` render as `<br>` in `in-force.md` cells and a space in `INDEX.md` (Q-1c3-2); a bad source file makes `render` raise naming it, nothing written (Q-1c3-3); `\|` escaped; links relative to the index file's directory. | F-SDDG4-9 | F/task-1c.3-domain.md:44-116 | none | L:387 | OA, CR |

#### MS §8 (process, base playbook)

| id | rule | source ids | best note cite | plan | ledger | class |
|---|---|---|---|---|---|---|
| C-2 | Fail closed; never match or emulate another tool exactly; narrow, stated promises; method: narrow a contract to a fail-closed whitelist, bound it with a seeded generated-input test. (Tension with Q-r5-1 (b) is V-15.) | F-SDD1-1, F-SDD3-10 | N/later-blocks-brief.md:14; F/task-1c.1-domain.md:96; N/edgecase-stopping-research.md:89, :110-113 | P:3065 | none for the general rule (L:221 stream C only) | OA |
| C-24 | PC1-PC5 are framework rules: input-domain table per task (one row per parameter and dimension, each with a test; a row with no test is a finding; a missing table blocks dispatch); PC2 oracle = production path plus an independent expected value; PC3 unstated behaviour stops at NEEDS_DECISION, one mutant per changed condition; PC4 reviewers have no out-of-scope bucket, a missing table is a finding; PC5 `class: <dimension>: <members>`. (F-SDD2-17's batching and restart part: DD §3.7-§3.8.) | F-SDD1-5, F-SDD2-17, F-SDD3-6, F-SDD4-4, F-SDD5-9 | F/task-1a.1-investigation.md:146-191; PR/controller.md:9-15 | P:46-51 | L:43, L:435 (Q-SDDT-5) | OA, M |
| C-25 | Input-domain table format: columns `# \| dimension \| values \| expected verdict \| test`; legend (implementer fills test; row with no test is a finding); markers settled / `(owner Q-n)` / `(controller)` (controller rows go to the reviewer as rulings, one line of why); sections Oracle, binding owner rulings, existing tests whose pinned behaviour changes, measurements, mismatches, owner batch "(a, recommended)" with costs; a row named by a fix must exist and a test cell names an existing test. P:52 defines the format by a git-ignored note. | F-SDD3-8, F-SDD4-5, +F-SDD5-9 | F/task-1a.1-domain.md:8-9; B/task-B1.1-domain.md:6-10, :102, :106 | P:52 | none | FMT, CV |
| C-26 | A block's plan section has a fixed section set: owner answers applied (binding); interfaces consumed; requests to other streams; file ownership table; controller rulings in `what -- why -- cost if wrong -- spec cite`; cross-block notes; spec edits needed (SE-ids, Now/Becomes, verbatim); divergences (both quotes); owner batch (upfront). | F-SDD2-16 | N/block-4-draft.md:24-93, :979-1017 | P:1681ff, P:3326ff, P:4797ff, P:53 | none | FMT |
| C-28 | Mutation review method: one mutant per changed condition; every survivor is argued equivalent or is a finding; mutants run on a `git archive` export or private clone, never the checkout, one fresh copy per mutant, with an `ast.parse` guard and three runs (present, mutant, restored). | F-SDD5-10 | C/task-C1.1-rereview1.md:115-122; C/block-C1-final-review.md:39 | P:49, P:4882 | none | M |
| C-29 | Review methods: trial merge (`git merge-tree`) and full suite on the merged tree before review; red-first re-established with a behaviour stub, not only a missing import; a mutant count with no script or transcript on disk is a finding; the verifier runs the suite with `GIT_*`, `TZ`, `LANG` polluted; reviewers gate a clean copy of the reviewed head (`git archive` or detached worktree, `pwd -P` and `show-toplevel` checked) and check `git ls-files -v \| grep '^[a-zS]'` is empty. | F-SDDG2-11, F-SDDG4-10 | N/task-1b.3-review.md:24-33, :83; F/task-1a.1-review.md:13, :16 | none | L:261 (results only) | M |
| C-30 | Test first, watched red for the stated reason; when tests came after the code, the red check is an overlay of the new tests on a clone of the pre-change sha. | F-SDDG3-2 | N/task-1c0.1-report.md:43, :105 | P:5878 (block text, no overlay) | none (L:243, L:379, L:391 rely on it) | M |
| C-31 | Plan and spec-edit review checklist: every prose quote of 12+ characters verbatim in its source (whitespace-normalised script, re-checked after edits); each edit's `old` occurs once at HEAD and `new` once after; every `Consumes` name matched against code and Produces lists; ownership pairwise disjoint (trailing `/` = everything under); at most 3 tasks per sub-block with the full task shape; every task has an executable check with asserts; no placeholders (`TBD\|TODO`); an omission is labelled as such, not as a contradiction. | F-SDDG1-7, F-SDDG3-4 | N/streams-bc-review.md:16-17; N/block-2-review.md:9, :114 | P:38, P:51 (parts) | none | M |
| C-32 | Every agent uses its own `mktemp -d`, never the shared scratchpad; no `git stash` in the shared checkout; reviewers check `pwd -P` and `show-toplevel` inside their clone before writing. | F-SDD3-14 | F/task-1a.1-review-final.md:113-114 | none | L:69, L:207, L:211 | CR |
| C-33 | Agent shell limits: no heredocs, no `rm`/`rmtree`/`os.remove`, no `$(...)` except `mktemp`; a slip is disclosed in the report. | F-SDDG1-6, F-SDDG2-13, F-SDDG3-6 | N/streams-bc-rev7-report.md:69-70; N/task-1c0.1-report.md:104 | none | L:132 (origin), L:209, L:231, L:248, L:379 | CV |
| C-34 | Worker commit gate and evidence: commit only with no unstaged or untracked path and no assume-unchanged/skip-worktree flag; a red line or missing interpreter blocks the commit; stage own files by name; an input outside a whitelist fails closed with a named check; a divergence is reported with both quotes, no side taken; a pasted result is re-run before it is relied on. | F-SDD4-11 | PR/implementer.md:9, :13; PR/controller.md:5, :23 | none | none | CV |
| C-35 | Commits: a fix round adds a new commit, never amends; a doc change and the test that pins it are one commit (a split would leave a red commit). | F-SDDG4-11 | F/task-1a.1-report.md:36; B/task-B1.3-report.md:124, :150 | none | none | CV |
| C-36 | Every commit carries the harness's `Co-Authored-By:` line for the model that wrote it (area 5 and gap 3 judged it repo-local; under Q-SDDT-1 it is listed). | F-SDDG2-10 | N/block-1a-verifier.md:11 | P:32 | none (controller ruling 2026-11-01 quoted at P:32) | CR |
| C-37 | Work branches (stream, block, group) are pushed at every checkpoint (`checkpoint.pushed`); the program controller pushes `<program>/integration` after every commit it makes there. Partly present: PD:254 pushes the integration branch at the end of a sync. | F-SDDG2-8 | N/programs-review3.md:46-51 | P:1704, P:1907, P:4814 | L:267 | OA |
| C-38 | A test that needs another stream's unmerged work is written now with a skip naming the dependency (`Rq-<n> not on this branch`); the controller removes the skips at the update, before the final review, so no PR carries known skips. | F-SDD5-8, +F-SDD2-10 | C/task-C2.2-brief.md:103; N/block-6-draft.md:31 | none | L:313, L:320 | CR |
| C-58 | Base playbook `rules.md`: columns `id \| rule \| why \| enforced by \| profiles \| fixed \| source`; exactly `SD-R1`..`SD-R19` (SD-R1-17 in MS §8 order, SD-R18 the bypass block, SD-R19 the stack-neutral production path, DB-6); fixed set `{SD-R3, SD-R12, SD-R18}`; profiles derived from §12, plain-text `source` matching `spec §\d+[a-z]?` (DB-7, DB-8); SD-R12 enforced by `hook` (Q-B21-1); an `overrides` outside SD-R1-19 refused (Q-B2plan-8). | F-SDD4-14, F-SDD1-8 | B/task-B2.1-domain.md:34-89; N/streams-bc-draft.md:1258-1261; N/block-2-draft.md:901-903 | P:5981-6019 | L:119, L:245, L:374 | OA, FMT |

#### MS §9 (gates)

| id | rule | source ids | best note cite | plan | ledger | class |
|---|---|---|---|---|---|---|
| C-43 | `gate_cites` grammar and contract: cites are backtick spans and inline link targets outside fences, placeholders excluded (DC-5); every tracked `*.md` (DC-6); GitHub ATX slug with `-1`/`-2` repeats (DC-7), frozen code-point tables, no `unicodedata` (Q-r5-1 (b), Q-r6-1 (b)); backslash escapes read literally (Q-C21r-1 (b)); not-UTF-8, backtick path verbatim, fence opener/closer (Q-C21-1..3); an unreadable tracked file fails the run as `cites.input` (Q-C22-1); every record with `landed_in` checked; symlinks/directories count as missing, never followed; a BOM-led heading gets no anchor; S1-S3 known limits, matching GitHub exactly is a non-goal (Q-C21r-2 (c)); "fail closed" = scan more, accept fewer anchors. | F-SDD5-3, +F-SDD1-9 | C/task-C2.1-brief.md:9, :377-379; C/task-C2.2-brief.md:100-102 | P:6478, P:6487, P:6983-6985; sc2:P:2410-2418 | L:119, L:138, L:263, L:279, L:288 | OA, CR |
| C-44 | `gate_drift`/`gate_index` rulings: a stacked stream also drifts when its `stacked_on` stream moves; live programs only, one `PASS drift.none`; "has merged" = a two-parent commit on the base's first-parent history whose second parent is the stream tip; merges are merge commits only; `gate_index` writes nothing and checks the generated files are git-ignored. | F-SDD1-22 | N/block-5-draft.md:23, :56-64 | P:4354 | none (controller rulings) | CR |
| C-45 | What `run_all` runs per profile (`PROFILE_GATES`): never `dispatch` (Q-B2plan-19); `gate_context` and `gate_drift` in no `run_all` list; `index` on standard and strict only; `cites` joins later. | F-SDD1-13 | N/block-2-draft.md:44, :929; N/block-5-draft.md:48, :57, :60 | the block 2/5 tasks | L:245 | CR, OA |

#### MS §10 (agent management)

| id | rule | source ids | best note cite | plan | ledger | class |
|---|---|---|---|---|---|---|
| C-46 | Framework roles `plan_writer` and `plan_reviewer` exist in `dispatch.ROLES` (Q-B2plan-16 (a), standing per Q-SDDT-6). Gap to close: MS §10's role list lacks them, no minimum tier is fixed (L:406 gives "plan writers/reviewers tier3" inside the small-re-review rule), and no task sends the request; Q-B22-2 (a) defers their `roles.md` rows. | F-SDD1-11 | N/block-2-draft.md:914-921 | P:3597, P:7030 | L:240, L:245, L:374, L:406, L:435 | OA |
| C-47 | Minimum tier per role (DB-2): tier1 `implementer_transcription`; tier2 `implementer`; tier3 controllers, reviewers, audit roles, investigator; tier4 `final_verifier`, `exception_reviewer`. `roles.md` values (Q-B22-1): needs brief yes for every role; finding states per role (controllers `open, planned, in-progress, deferred, closed`; implementers `fixed-unpinned, pinned`; reviewers, verifiers, audit roles `open`; investigator and exception_reviewer none; `merged` none). | F-SDD1-7, F-SDD4-15 | N/streams-bc-draft.md:1255; B/task-B2.2-domain.md:106 | P:1622, P:6091 | L:119, L:374 | OA (model policy) |
| C-48 | Prompt-block file format: `skills/strict-delivery/prompts/<role>.md`, `<role>` a `SPEC_ROLES` id (DB-1); line 1 `# Strict block: <role>`, line 2 empty, line 3 the intro ending "These rules override every other instruction, superpowers skill text included." (DB-4); labelled paragraphs separated by one empty line; no other heading or rule line (Q-B11-3); printable ASCII and `\n` only (Q-B11-2), LF, no trailing whitespace, one final `\n`. | F-SDD4-1, +F-SDD1-8 | B/task-B1.1-brief.md:33-37 | P:5776-5781 | L:119, L:164 | FMT, OA |
| C-49 | Per-role paragraph labels (`LABELS`) and required strings (`REQUIRED`), matched as whole tokens (Q-B11-4). | F-SDD4-2 | B/task-B1.1-brief.md:38-70 | P:5784-5815 | L:164 | FMT |
| C-50 | Role scopes: `exception_reviewer` argues against one proposed exception (a draft `rule-override` decision or a playbook-allowed deviation), reads only the proposal and its evidence, re-runs the evidence's commands, argument in its own report section (DB-5, Q-B12-3); `audit_reviewer` writes its coverage list to a progress file first; `audit_verifier` re-runs every reproducer and extends coverage; `investigator` is read-only, its report its one write; `implementer_transcription` stops NEEDS_DECISION on any gap; `final_verifier` tries to break the branch. | F-SDD4-10, +F-SDD1-8 | B/task-B1.2-brief.md:14, :43 | P:5897, P:5933 | L:119, L:202 | OA, CV |
| C-51 | Report contract field lists per role (e.g. implementer: commits; gates run; claims; findings raised; unrelated findings; decision needed; denials; budget used), with a final reply of at most 10 lines with the same fields. | F-SDD4-6 | B/block-B1-fix-report.md:14; PR/implementer.md:25 | none | L:218 (Q-B12r-1), L:319 (F-B1f-2 fix) | FMT, OA |
| C-52 | Status by cause: DONE when every claim and gate re-ran clean and the change holds no finding; a defect the change did not cause (or outside the audited area) goes under Unrelated findings and does not by itself make DONE_WITH_FINDINGS. | F-SDD4-7 | PR/task_reviewer.md:13; PR/audit_reviewer.md:21 | none | L:218, L:254 (Q-B13r-2 (b)) | OA |
| C-53 | Status precedence: when more than one status applies, report the first of DENIED, BLOCKED, NEEDS_DECISION, DONE_WITH_FINDINGS, DONE. | F-SDD4-8 | B/task-B1.3-report.md (fix round 3); PR/controller.md:29 | none | L:288 (Q-B13rr-1) | OA |
| C-54 | "No subagents" bans agents, workflows and other agent tasks only; a worker may start background shell jobs, which it reaps (the reaping procedure is DD §3.4). | F-SDD4-12 | B/task-B1.1-report.md:44 | none | L:193 | OA |
| C-55 | After a permission denial the agent stops with DENIED, quoting it; the controller does not re-run the denied action; a resumed agent uses only its own code (no downloaded or external code). | F-SDDG2-12 | N/streams-bc-review7.md:15, :56, :62 | none | L:145, L:147 | CR |
| C-56 | Rules N and T: advisory; T at p <= 0.10, N when at least half of a round's findings are in new dimensions; no reset on narrowing, narrowing noted; the reviewer assigns one canonical dimension from the table's row names; the definitions (`ALPHA = 1/10`, `NOVELTY = 1/2`, `FIX_ROUND_CAP = 5`, verdict order CLEAN/ESCALATE/STOP_NARROW/CONTINUE); finding fields `review_round`, `caused_by_change`, `dimension`. P:5092 points at a git-ignored note for the formulas. | F-SDD1-4, F-SDD2-1, F-SDD4-13 | N/block-6-draft.md:43, :301-330; N/edgecase-stopping-research.md:78-94 | P:4839, P:5092, P:5098-5120 | L:258, L:263, L:374 | OA, M |
| C-57 | Dispatch semantics: the exact `## Role` / `## Strict block` body layout (Q-B2plan-18); the measured limits are pinned as constants, re-measured at each block that touches dispatch, and a Claude Code change is a finding (Q-B2plan-22). | F-SDD1-12 | N/block-2-draft.md:925-927, :937-939 | P:2457 | L:245 | OA |

#### MS §13 (gate and library contract)

| id | rule | source ids | best note cite | plan | ledger | class |
|---|---|---|---|---|---|---|
| C-39 | Every library function taking a repository root refuses a root that is not the git top level (realpath/`samefile`), `Store` and `config.load` included; list-only gates too. | F-SDD3-11, +F-SDD1-17 | F/task-1c0-domain.md:154 | P:492-497 | L:162, L:319 | OA |
| C-40 | A symlink on any component of the register path is refused in load, create and replace (Q-1a3r-1); a gate line names the record id when it is valid and unique, else the repo-relative path (Q-1c1-1); the reference scan matches raw bytes (Q-1c1-2). | F-SDD1-17 | F/task-1a.3-rereview1.md:74; N/task-1c.1-brief.md:62-63 | none cited | L:150, L:387 | OA |
| C-41 | Line ids and reasons are escaped exactly once, by `Result.render` (`safe_text`); a caller value or map item in a reason is escaped once; a backslash renders as `\\`. | F-SDD2-7, +F-SDD1-17 | N/block-1a-final-review.md:56 | P:486, P:511, P:6851 | L:118, L:319 (Q-U2), L:372 (Q-1c0-2) | CV, OA |
| C-59 | Gate CLI contract: `--json` shape `{"gate","ok","lines":[{status,id,reason}]}`; `--help` gives `FAIL <name>.input: help requested; no gate was run`; KeyboardInterrupt propagates, any other exception becomes `FAIL x.input`; non-str values `str()` then escaped (Q-1a2-6); `python3 -m gates check <gate>`, an unknown gate gives usage and exit 2; an option given twice is refused for every gate via `gate_args` `_Once` (Q-1b1r-1 (b), L:195); a missing gate module gives one `FAIL <gate>.input` line, exit 1 (Q-1c0-1); cycles render as `{...}`/`[...]` (Q-1c0-3). | F-SDDG1-2, F-SDDG2-2, F-SDDG4-1 | F/task-1a.2-domain.md:62-68; N/task-1b.1-review.md:83-89; F/task-1c.1-domain.md:22-24 | P:90, P:5049 | L:113, L:118, L:188, L:195, L:372 | OA, CR |
| C-60 | Root discovery: `CLAUDE_PROJECT_DIR` when set and non-empty, a non-directory is a GateError; else `git rev-parse --show-toplevel`; outside a repo names `/strict-delivery:init`; git missing from PATH gives `git not found on PATH; install git`, no init hint (Q-1a2r-6). | F-SDDG4-2 | F/task-1a.2-domain.md:40-41; F/task-1c.1-domain.md:18-19 | P:90 | L:113, L:118 | OA |
| C-61 | Git revision and path rules: a value starting with `-` or `^` is refused (Q-1a-ver-2); a run of more than 40 hex digits refused before git runs; an ambiguous short prefix is False (Q-1a2-3, Q-1a2r-2), resolved with `-c core.disambiguate=none`; an expression on an ambiguous prefix resolves as git does (Q-1a2r-7); a symlink (120000) is not a blob, modes 100644/100755 only; `show` gives None for a directory, symlink or gitlink; a `..` segment raises; unnormalised paths refused (Q-1a-fin-2); whitespace-only gives None. | F-SDDG1-1, F-SDDG2-1, F-SDDG4-4 | F/task-1a.2-domain.md:49-55; N/block-1a-verifier.md:80, :161, :185 | P:99 (config part), P:1242 | L:113, L:118, L:128, L:131, L:162, L:173 | OA, CR |
| C-62 | Pinned git invocation: argument lists only, `--` before paths, `LC_ALL=C`, `GIT_*` cleared (`CLEARED_ENV`, seven names, Q-1a-ver-3) with `GIT_INDEX_FILE` inherited on purpose (Q-1a2r-5); output pinned with `-c color.*=never`, `core.abbrev=12`, `--no-ext-diff --no-textconv`. | F-SDD3-5 | F/lap-timer-streams-and-ports.md:49, :153, :162; F/task-1a.2-domain.md:56 | P:169, P:1242, P:2771 (no `color.*`/`core.abbrev`) | L:118, L:173 | M, OA |

#### MS §13a (evidence contract)

| id | rule | source ids | best note cite | plan | ledger | class |
|---|---|---|---|---|---|---|
| C-63 | Pin rendering: a string template has each `{id}` replaced by `shlex.quote(<test id>)` and runs via `/bin/sh -c`; a list template replaces `{id}` literally per element and runs with no shell; at `--root`, inherited environment, no timeout; no `{id}` fails `evidence.config`; run 2 must exit non-zero and neither 126 nor 127; `gate_evidence` always prints `evidence.config` and `evidence.scope`. | F-SDD2-13 | N/block-6-draft.md:75-87 | P:4872, P:4878, P:4881 | none cited (B6 batch L:362) | CR |
| C-64 | The package's `PIN-COMMAND` must equal every run's command in the transcript, and the re-run uses the current config (Q-B6plan-4 (b)). | F-SDDG2-6 | N/block-6-review.md:71-73, :103 | P:4926, P:4954 | L:362 | OA |

#### MS §14 (testing the framework)

| id | rule | source ids | best note cite | plan | ledger | class |
|---|---|---|---|---|---|---|
| C-65 | Framework prose is tested by required strings as whole tokens in a named paragraph (Q-B12-1, Q-B13-1); key rule sentences pinned in full (Q-B13r-1 (b), narrowed by F-B13rr-2); a harmless rewording of an unpinned phrase never fails the suite; every content sentence of a prose Produces has an executable check or is deleted. | F-SDD4-16 | B/task-B1.2-brief.md:41; B/task-B1.3-brief.md:56 | Tasks B1.2/B1.3 Step 1 | L:202, L:218, L:254 | M, OA |
| C-66 | Tests never write schema-tag literals: take the tag from the schema file; build configs only with `tests/helpers.minimal_config()`. | F-SDD5-6 | D/task-2a.1-domain.md:181; D/task-2c.2-domain.md:127 | P:1446, P:7135 (Q-2a1-3 not in P) | L:387 | OA |
| C-67 | Tests that run git are isolated from the user's git config (`HOME`, `GIT_CONFIG_NOSYSTEM=1`, `GIT_CONFIG_GLOBAL=/dev/null`, signing off) through a `GitIsolatedTestCase` base class. | F-SDDG1-8 | N/plan-rev5-review.md:24 | P:103 | L:105 | M |
| C-68 | Gate output does not depend on the interpreter: one golden output asserted byte for byte in every matrix cell; no `unicodedata`-dependent results. | F-SDDG2-14 | N/block-6-review.md:64-68 | P:5150, P:6484-6486 | L:138 (cites only) | M |

#### MS §15 (releases)

| id | rule | source ids | best note cite | plan | ledger | class |
|---|---|---|---|---|---|---|
| C-69 | Each release tag is annotated, sits on the release PR's merge commit, is created locally after the merge is read back, and is pushed only on the owner's word. | F-SDD2-15 | N/block-6-draft.md:110 | P:4906, P:5506 | none | CR |

#### PD (programs and streams design)

| id | rule | source ids | best note cite | plan | ledger | class |
|---|---|---|---|---|---|---|
| C-70 | PD §7.2/§12: a program is live when a local branch `<p>/integration` exists and its tip holds `<paths.programs>/<p>/streams.yml` (`programs.live_programs`), never read from the current branch's tree. | F-SDD2-3 | N/programs-draft.md:39 | P:1720 | none | CR |
| C-71 | PD §7.2: a spec is in a plan's per-effort set only when no other live plan's handoff names it in `spec`. | F-SDD2-4 | N/programs-draft.md:45 | P:1726 | none | CR |
| C-72 | PD §12: the program folder and global record directories are owned by program commits on `<program>/integration`; a merge whose second parent is reachable from the `base_branch` tip is exempt from the ownership check; a combined-testing merge of a stream head may change only that stream's paths. | F-SDD2-5 | N/programs-draft.md:42 | P:1723, P:2152 | none | CR |
| C-73 | PD §11 / Appendix A: status-row `estimate` and `used` are non-negative decimal integers in the unit of the stream's `estimate`, one unit per program; breakdown estimation units (S 1 h, M 2 h, L 3 h, E 1.5 h, U 0.25 h, 2 agents per task). | F-SDD2-6, F-SDD1-21 | N/programs-draft.md:43; N/stream-breakdown-draft.md:29-40; N/block-5-draft.md:23 | P:1724, P:4789 (D5-1) | none | CR, M |
| C-74 | PD §6/§12: shared registration files have one owner; a registry line lands only with or after its module, as one commit right after that merge; tests needing a missing line are skipped with `Rq-<n> not on this branch`; receiver `package` while live, else A. Partly superseded for block 4 by Q-BD-8 (a) (L:393). | F-SDD2-10 | N/block-4-draft.md:46-49; N/block-6-draft.md:31 | P:4332, P:4442, P:4827 | L:335, L:355, L:393 | CR |
| C-75 | PD §7/§12: inside a program, gates (`gate_drift`, `overview/2`) read global records at the tip of `<program>/integration`. | F-SDDG2-7 | N/block-6-review.md:41 | P:4320, P:4684, P:4693 | L:319 (Q-Pplan-12) | OA, CR |
| C-76 | PD §4-§5, §10; MS Appendix A: interfaces are frozen once merged (a change is a plan change the owner rules on; earlier tasks' code not changed by later tasks unless ratified); never rebase a work branch (it orphans reviewed shas); the `UPDATE ... from=main@<sha> head=<sha> tests= gates=` line, a conflict stops the stream BLOCKED; block-end order: final review, top-tier verifier, approval, merge, post-merge gates, checkpoint. | F-SDD1-19 | N/streams-bc-draft.md:40, :52-55 | P:5688 area | L:119 (DS-2), L:170 (Q-1a-rr2-1) | M, OA |
| C-77 | PD §7.2, MS §7.2, Appendix A: a `MERGED` line counts only when tied to its plan (the merge's diff changes a path under `<paths.plan_state>/<plan>/`), `by` names the merger (in `controller` mode the owner's chat words ledgered verbatim), and a commit not found locally fails with `update <base_branch> from the remote`. | F-SDDG2-9 | N/programs-review5.md:32-48; N/programs-review7.md:9 | P:1831, P:2230, P:2232 | L:292, L:319 (base answers) | CR |

### 2. Divergences

Each quote was re-read with `sed -n <line>p` (Evidence E2). Direction follows Q-SDDT-2 (L:435): a later owner answer wins with a spec edit; otherwise the plan is corrected to the spec. Dates of spec text: `git log --reverse -S` (Evidence E3).

| id | quotes | later owner answer | direction | source ids |
|---|---|---|---|---|
| V-1 | MS:104-105 "offer them for `test`, `test_one`, `lint` and `build`" vs P:3358 "`test_one` is always asked and never proposed (DC-2)" (also P:6982) | L:119 DC-2 (spec sentence present since 63222e0, 2026-10-31) | spec edited to match DC-2 | F-SDD5-1, F-SDD1-9 |
| V-2 | MS:329-330 "The only deletions allowed are the cleanup step's (resolved findings and per-effort files, section 5)" vs N/block-2-draft.md:892 "(a) Recommended: a claim file may be deleted only in a change where its `document` ... is also gone" | L:245 Q-B2plan-5 (a), 2026-11-01 (spec sentence from 35dc155, 2026-10-31) | spec edited to match Q-B2plan-5 (a) | +F-SDD1-10 |
| V-3 | MS:601-602 "Each gate is enabled on this repository as soon as it lands" vs P:876 "this repository's shared hooks directory gets the hooks only after block 2b merges into `main` and every live stream branch has updated" (also P:2631; N/streams-bc-draft.md:61) | none (controller rulings) | plan corrected to spec (P:876, P:2631); owner to check, since the rulings guard stream branches | F-SDD1-16 |
| V-4 | MS:186-189 and PD:186 "`docs/strict-delivery/reviews/<plan>/` \| review reports" vs P:5688 / N/streams-bc-draft.md:39 "Per-stream dispatch artifacts live in the main checkout under .superpowers/sdd/... (git-ignored)"; P:52 and P:5092 make git-ignored notes the source of the table format and the Rules N/T formulas | none | plan corrected to spec (reports tracked; P:52, P:5092 point at spec text) | F-SDD1-20 |
| V-5 | P:1717 "at most five per sub-block" vs P:3415 / P:4860 "`rulings.max_per_block` has no preset, so it is absent and no cap applies"; MS:281-282 "at most `rulings.max_per_block`" | none (L:107 "3 of 5" are tallies) | plan corrected to spec (cap from config; "five" only if this repo sets it) | F-SDD2-11 |
| V-6 | MS:152 "so the PreToolUse Agent hook's counts stay exact" vs N/block-6-draft.md:96 "That store is a hook-side approximation" (M4), basis of P:4891 | none (spec text from 2eebf4e, 2026-11-02) | plan corrected to spec by the rule; owner to check: M4 is a measured fact, so the spec sentence may be the wrong side | F-SDD2-12 |
| V-7 | MS:261 "parse(emit(x)) == x" vs P:48 "for a parser: `load` of a file written by `emit`" and F/task-1a.1-investigation.md:163 "`emit(v)` is byte-identical on both interpreters" | L:43 PC1-PC5 adopted (INV:161 "owner decision: spec text"); L:435 Q-SDDT-5 | spec edited to match PC2 | F-SDD3-7 |
| V-8 | MS:280-281 "only plan-vs-spec or task-vs-task conflicts the spec settles" vs F/task-1c0-domain.md:169 "Mismatches found (plan vs code; controller to settle, not owner)" and F/task-1c.1-domain.md:11 "(controller) are calls the spec or plan settles by implication" | none | plan and briefs corrected to spec (P has no such text; the playbook routes them as MS allows) | F-SDD3-9 |
| V-9 | P:5678 "The plan file and both specs belong to the session controller and the owner; no stream edits them" and PD:266 "every changed path owned by the committing stream" vs L:319 "Q-B1f-2 (a) task-section plan edits allowed, ownership check skips the plan file for them" | L:319 (2026-11-02) | spec edited to match Q-B1f-2 (a) (PD §12), P:5678 updated | F-SDD4-17, F-SDD5-7 |
| V-10 | P:33 "`/usr/bin/python3 -m unittest discover -s tests -t . -v`" vs C/block-C1-final-review.md:26 "`PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX="$(mktemp -d)" python3 -W error -m unittest discover -s tests -t .`" | none | no spec text (MS §14 states only the matrix): the rule gives no side; owner picks the command the catch-up states | F-SDD5-11 |
| V-11 | MS:396-397 "review minors are fixed in the fix round, never deferred" vs L:98 "purely cosmetic findings ... do not earn a fix round: note, fold into the next real edit, or drop" | L:98 (2026-10-31; spec sentence present since 63222e0) | spec edited to match L:98; owner to check that "cosmetic" is distinct from "minor" | F-SDDG3-1 |
| V-12 | P:6959 "Q-plan-6 (b) every block-1 test step carries its assertions as code" vs L:97 "Q6b (test steps carry assertion code)" (no block limit) and N/streams-bc-review.md:25 "every task has assertion code" | L:97 | spec states L:97's wording for every plan's test steps (MS §8 "Plan in full"); P:6959 widened | F-SDDG3-5 |
| V-13 | MS:463 "`## Budget: tokens=<n> minutes=<n>`" vs B/task-B1.3-report.md:95 "About 45 tool calls of 90" | none | spec stands; briefs corrected (P has no tool-call budgets) | F-SDDG4-12 |
| V-14 | P:1449 "Spec §6 gains the `limits` key" vs MS §6 key list (MS:219-249) with no `limits` entry | L:218 Q-H2 (a) | spec edited (C-9) | +F-SDD1-3, +F-SDD2-2, +F-SDD5-5 |
| V-15 | F/task-1c.1-domain.md:96 "Owner direction 2026-11-02: fail closed; never emulate another tool exactly" vs L:138 "slugify ... tested against github-slugger fixtures" (2026-11-01) | the 2026-11-02 direction; L:279 Q-C21r-2 (c) already records S1-S3 as known limits | spec states the direction (C-2) and C-43's known limits; owner to check the fixture tests stay inside it | +F-SDD3-10 |

### 3. Never-adopted proposals (owner yes/no)

| id | proposal | cite | what adopting it changes | source ids |
|---|---|---|---|---|
| N-1 | `context.yml` entries `{path, lines, why, ref?}`, `lines` as `a-b` or `a-end` (resolved and split within `context.max_lines`/`context.max_bytes`), output `<path> lines a-b blob <sha> -- <why>`; a handoff `context_files` list appended to the stream's read list. | F/lap-timer-streams-and-ports.md:43-47, :313-319 | MS §9 and Appendix A `context` row gain an entry shape and two config keys; P:4386 (`every`/`kinds`/`roles` lists of `str`) is rewritten; Task 5 receipts read ranges. Note: DD §3.2 already gives `required_reads` "path, optional line range, why" for the session handoff only. | F-SDD3-1 |
| N-2 | Cross-stream reads from another stream's pushed branch: `ref: stream:<id>`, branch name from the status page. | F/lap-timer-streams-and-ports.md:280, :317-319, :393 | MS §9/PD §10 read lists for sync and program kinds; the context loader resolves refs; partly overtaken by P:4392-4397's `{integration}` placeholder. | F-SDD3-2 |
| N-3 | A session's own Edit refreshes its read receipt (pre-edit blob sha keyed by tool-use id); edits by other writers do not. | F/lap-timer-streams-and-ports.md:200 | MS:431-433 receipt rule changes (today an own edit makes the receipt stale); PostToolUse Edit hook and P:4518 change. | F-SDD3-3 |
| N-4 | Owned paths compared after normalisation, case-folding and Unicode NFC (reuse `_overlap_key`). | F/lap-timer-streams-and-ports.md:126, :327 | PD §4.1 and §12 `gate_streams`/`gate_plan` overlap checks gain the comparison; new tests. | F-SDD3-4 |
