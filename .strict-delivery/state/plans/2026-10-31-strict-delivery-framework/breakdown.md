# Stream breakdown (2026-11-02): strict-delivery framework, all remaining work

The human schedule for the plan `docs/strict-delivery/plans/2026-10-31-strict-delivery-framework.md`, the last planning step (owner Q-PL-1 (a)). Copied from the reviewed stream-breakdown draft, a git-ignored working file that this record does not cite (sections 1-7; its findings and its edit list are applied to the plan and specs and are not repeated). Owner answers: Q-BDr-1 (a), Q-BD-4 (a), Q-BD-5 (a), Q-BD-7 (a), Q-BD-8 (a), Q-BDr2-1 (a); controller rulings Q-BD-1, Q-BD-2, Q-BD-3, Q-BD-6 and the `done` field under Q-BD-7 (a). Not a checked record: section 6 is the content of the future `breakdown.yml` (`breakdown/1`), written before `program create`.


The last planning step (owner directive and Q-PL-1 (a), 2026-11-02, L:381-382). Revision 2 applies the review `stream-breakdown-review.md` (F-BDr-1..12) and the owner answers and controller rulings of L:393. Revision 5 (2026-11-08) applies owner answers Q-DOCS-1 (e), Q-RD8b-1 (a), Q-RD8b-2 (b) and Q-RD8c-1 (b): Task 1c0.2 and the docs-only PR's final review and verifier run before PR-1c0 merges, on a branch cut from `block/b1c`'s head, and after PR-1c0 only the docs-only PR's tail remains (cut from `main`, cherry-pick, gates (U), then the rest of its end: approval, merge, read-back, post-merge gates, `MERGED` line; 3.75); every stream (`b`, `c`, `d`) and Task 1c.2 start after it; of the tied shortest queue orders the one with PR-C2 earliest is kept; Task P2.1 is L + 1 h (4 h) (section 4; +2.25 h, S = 56.0, 93.0 h). Revision 4 (2026-11-08) applies owner answers Q-F80RR3-3 (a) (Task P2.1 class L, +1.0 h from PR-P2 on) and Q-F80W-13 (a) (the release `stream-ownership` decision before `program create`), and the branch cuts that Q-F80W-12 (a) requires (section 6.2). Revision 3 (2026-11-07) applies the session-resume plan revision (P078:7536, P078:7538; owner approval L:500; Q-RCp-2 (a), L:515; Q-PLG-1 (a), L:545), the rulings L:541 and L:551, owner answer Q-BRV-1 (a) (the interim-skill removal is Task R5.1 in residual sub-block R5 with its own PR), docs review finding F-DR-6 and its reviews; its edits are applied to the plan and to this file (L:561).

**Two artefacts, by owner answer Q-BD-7 (a) and review F-BDr-8.** `program create --plan 2026-10-31-strict-delivery-framework` checks one `breakdown.yml` against this plan and against `streams.yml` (P615:2054-2060). At that moment every pre-program task (1c..P4, B2, C2, D) is done. So:
- **Part I, the pre-program schedule (sections 2-5):** the session's working schedule from now to the programs block's last PR. It is not a checked record. P2.2's checker does not exist yet, and the session coordinates these streams by hand (P:5517).
- **Part II, the program record (section 6):** the `breakdown/1` content committed before `program create`. Every pre-program task is in `done`; the streams are exactly the program's (including `residual`, Q-BD-4 (a)); and ownership that moves during the program is written with `period` (Q-BD-7 (a)). Its schema additions are listed under "Plan and spec edits".

**Citation keys.**
- `P:<n>`: the plan at `5283c51`.
- `P615:<n>`: the plan at `615bc21`, the head of `block/b1c` (used for text that changed after 5283c51: the breakdown schema, 3d.2's heading, Block 6's Rules N/T note).
- `P078:<n>`: the plan at `0783046`, the head of `block/docs-resume` (used for the nodes, edges and text of the session-resume revision, revision 3; P078:7536-7538). `P:<n>` keeps its `5283c51` pin. Task R5.1, which the plan gains with revision 3 (owner answer Q-BRV-1 (a)), is cited by its task id.
- `L:<n>`: the working copy of the ledger (`.strict-delivery/state/plans/2026-10-31-strict-delivery-framework/ledger.md`).
- `R:F-BDr-n`: the review.

Every statement was checked directly (the cited line says it) and by contradiction (a search for text that would break it). The review's corrections were re-derived from the cited lines, not copied.

**Binding inputs to this revision.**
- L:393: Q-BDr-1 (a), stream D = 2a.1, 2a.2, 2a.3, and 2c.2 returns to A; Q-BD-4 (a); Q-BD-5 (a); Q-BD-7 (a); Q-BD-8 (a). Controller rulings: Q-BD-1 (`ask --overrides` to A, after PR-1d), Q-BD-2 (P3 alongside P4), Q-BD-3 (Rq-5-4 landed by A before the program), Q-BD-6 (PR-1c0 carries only docs already reviewed). Q-BD-9 is moot: this session runs at depth 5, concurrency 30.
- L:387: 1c.2 and 2a.1 wait for PR-1c0. L:389: D's order is 2a.1 -> 2a.2 (then 2a.3), all after PR-1c0.
- Coordinator facts: 2a.1 Step 5 needs 1c.2; 2b.1 waits for PR-2a, which is now PR-D; 1c.1 is running on `block/b1c1`.

```yaml
max_concurrent: 25   # measured: 25 ran at once with the variable set to 30; the boundary was not measured (P:864-865; R:F-BDr-9)
max_depth: 5         # the session runs with CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH=5 (L:393); the default tree uses levels 1-3 (P:1701)
```

---

## 1. Units (unchanged from revision 1)

- Task classes:
  - S: 1 h.
  - M: 2 h.
  - L: 3 h. The L tasks are 2a.1, 2c.3, P2.1 (L + 1 h: 4 h, outside the classes; class L by owner answer Q-F80RR3-3 (a), plus 1 h for the event order and `residual_reachable` that owner answer Q-RD8-1 (a) moves into it, owner answer Q-RD8b-2 (b)), P2.2, 3a.2, 3b.2, 4d.1 and 4e.1.
- E (block or stream PR end: final review, verifier, owner approval, merge, read-back, post-merge gates, MERGED line): 1.5 h. The docs-only PR's tail after PR-1c0 (owner answer Q-RD8c-1 (b)): U (0.25 h), then the rest of its end after its earlier final review and verifier (the owner's approval of the head, merge, read-back, post-merge gates, `MERGED` line), taken as 1.0 h: 1.25 h.
- A sub-block end without a PR: 1 h.
- U (update from `main` before a merge, P:5560): 0.25 h. The update comes before the final review (P078:6251, "At the update from `main` before the final review"), the full commit gate re-runs on that head (P:5560), and the owner approves the reviewed head (P078:5314). So a PR's E follows its last U, and an update after another PR's merge restarts the E (U + E = 1.75 h; revision 3).
- Records migration step (P:1011): 0.25 h.
- Agent count per active task: 2 (implementer and reviewer). A block end also counts 2. Each program stream controller counts 1, and each group sub-controller counts 1.
- t = 0 is now (2026-11-02, 1c0.1 fix round for U1 running, L:393; 1c.1 running).

---

## 2. Pre-program streams (Part I)

| id | period | branch | owns (paths) | open tasks | starts when |
|---|---|---|---|---|---|
| `a` | now -> program start | `block/b1c` (1c0), the docs-only PR's branches (1c0.2, its final review and verifier: a branch cut from `block/b1c`'s head, the docs commits of `block/docs-resume` cherry-picked onto it, before PR-1c0 merges; the PR's own branch: cut from `main`'s tip after PR-1c0, the reviewed commits cherry-picked onto it, L:541; it merges right after PR-1c0, owner answer Q-DOCS-1 (e)), `block/b1c1`, `block/b1d`, `block/b1d2`, `block/b2b`, `block/b2c`, `block/p1`..`p4` | residual: every path not owned by `b`, `c` or `d` in the same window (P:5527). The five shared files stay A's (P:5532), except the `__main__.py` window below. | 1c0.1 (fix round), 1c0.2, 1c.1-1c.3, 1d.1-1d.3, 1d2.1, 2b.1-2b.3, 2c.1 (with `ask --overrides`), 2c.2, 2c.3, P1.1-P4.3 | running |
| `b` | -> PR-B2 merged | `block/sb2` | P:5525 row, plus B2.2's added prose (Q-BD-5 (a)) | B2.1, B2.2, B2.3 | the docs-only PR merged: `sb2` is cut from a `main` that holds it (owner answer Q-DOCS-1 (e); was PR-1c0 merged, L:374) |
| `c` | -> PR-C2 merged | `block/sc2` | P:5526 row | none: C2.1 and C2.2 are complete (L:313, L:352); only the PR is left | PR-C2 merges after the docs-only PR, by `sc2`'s update from `main` (owner answer Q-DOCS-1 (e); P:6956 allows it after PR-1c0) |
| `d` | the docs-only PR merged -> PR-D merged | `block/sd1` | 2a.1 Files without `decisions_cli` (Q-2a1-1 (a), L:387): `gates/lib/migrations.py`, `gates/schemas/decision.yml`, `gates/lib/decisions.py`, `tests/test_playbook_drift.py`, `tests/test_migrations.py`, `tests/test_decisions_lib.py`, and `gates/lib/store.py` and `tests/test_store.py` **both from PR-1c merged** (order rule O2; R2:F-BDr2-3). 2a.2: `gates/schemas/claim.yml`, `gates/lib/claims.py`, `gates/lib/gitinfo.py` (additive `blob_id`), `tests/test_claims_lib.py`. 2a.3: `gates/gate_claims.py`, `tests/test_gate_claims.py`, and `gates/__main__.py` `GATES["claims"]` **from PR-1d merged** (order rule O3). | 2a.1, 2a.2, 2a.3 | the docs-only PR merged and `sd1` updated (owner answer Q-DOCS-1 (e); L:389) |

**Order rules that resolve the overlaps (R:F-BDr-7).** Each is checked against the schedule in section 4.
- **O1 `gates/lib/gitinfo.py` (a and d).**
  - 1c0.1's changes reach `main` before D starts (L:389).
  - D's `blob_id` (2a.2) reaches `main` with PR-D.
  - A's next writer, 2b.2, starts only after PR-D, because 2b.1 waits for PR-D (E15). So there is no concurrent writer.
- **O2 `gates/lib/store.py` (1c.2 and 2a.1).**
  - 1c.2 adds its private merge-base row helpers (mismatch M2, L:383; store.py order L:387) on `block/b1c1`.
  - 2a.1 writes its `base_errors` change (P:889) only after `sd1` has merged `main` containing PR-1c. Its commit waits for PR-1c anyway (E09).
  - The same window covers `tests/test_store.py`. 1c.2 may test its new helpers there (mismatch M2, L:383); 2a.1's `base_errors` rows (P:892) are written after the update.
  - Until then 2a.1 works in its other files. The `store.py` and `test_store.py` part takes about 0.5 h after the update, so 2a.1 commits at 8.75, not 8.25 (R2:F-BDr2-3).
  - So both files are A's until PR-1c merges and D's after: one writer at a time.
- **O3 `gates/__main__.py` (2a.3 and A's 1d).**
  - 1d.1 and 1d.2 register their commands (P:726, P:782) until PR-1d merges at 13.75. Task 1d.3 adds no `COMMANDS` key (P078:961), but PR-1d merges only after it.
  - 2a.3 adds `GATES["claims"]` (P:1124) after `sd1` merges `main` containing PR-1d. 2a.3 runs from 10.75 to 12.75 (2a.1 commits at 8.75, line O2 above; section 4, row PR-D); its `GATES["claims"]` commit then waits for PR-1d (13.75) and a U, to 14.0 (revision 3: O3 is now on the critical path; the 2a work has 1.0 h of slack, revision 5).
  - No other D task touches `__main__.py`.
- **O4 `tests/helpers.py`, `.strict-delivery/config.yml`, `gates/lib/config.py`, `gates/schemas/config.yml`.** 2c.2 is A's again (L:393), so D owns none of these (R:F-BD-3 part resolved). 2c.2 also edits `migrations.py` (P:1445) after PR-D (E11).
- **O5 `config/1` literals (R:F-BDr-12).** 2c.2 is A's, so A fixes literals in A's own tests. Brief rule for 1c and 1d: build config only through `helpers.minimal_config()` or `make_repo`.
- **O6 `tests/test_playbook_drift.py`.** D creates it (2a.1), and A's 2c.3 edits it (P:1515) after PR-D.

---

## 3. Pre-program tasks and edges (task -> task only; merge waits in section 4)

### 3.1 Nodes

| id | stream | PR | cls | owned paths (C create, M modify, T test) | src |
|---|---|---|---|---|---|
| 1c0.1 | a | PR-1c0 | fix round (U1, L:393) | see P:483-484 | P:480 |
| 1c0.2 | a | PR-resume-docs | M | C `.claude/skills/strict-delivery-repo/SKILL.md`, `CLAUDE.md`; no tracked test (the check script runs from `mktemp -d`, P078:568) | P078:562-567 |
| 1c.1 | a | PR-1c | M (running) | C `gate_decisions.py`; M `__main__.py`; T | P:561-563 |
| 1c.2 | a | PR-1c | M | C `gate_register.py`; M `__main__.py`, `store.py` (helpers, mismatch M2, L:383); T | P:619-621; L:383, L:387 |
| 1c.3 | a | PR-1c | M | C `tools/__init__.py`, `tools/index.py`, 4 schemas; M `__main__.py`, `producers.py`, `.gitignore`, `tests/test_schema_lib.py` (K6, L:383); T | P:667-669 |
| 1d.1 | a | PR-1d | M | C `tools/decisions_cli.py`; M `__main__.py`, `producers.py`; T | P:725-727 |
| 1d.2 | a | PR-1d | M | C `tools/findings_cli.py`; M `__main__.py`, `producers.py`; T | P:781-783 |
| 1d.3 | a | PR-1d | M | C `lib/batch.py`; M `tools/decisions_cli.py` (subcommand `batch`); T `test_batch.py`, `test_decisions_cli.py` | P078:963-966 |
| 1d2.1 | a | PR-1d2 | M | C `print_table.py`, `tests/test_print_table.py`; M `result.py`, `config.py`, `schema.py`, `decisions.py`, `yamlsub.py`, `tests/test_schema_lib.py` | plan Task 1d2.1 (owner Q-RCp-2 (a)) |
| 2a.1 | d | PR-D | L | section 2 row `d` (2a.1 part); records migration by the session (P:1011) | P:884-892 |
| 2a.2 | d | PR-D | M | C `claim.yml`, `claims.py`; M `gitinfo.py`; T | P:1016-1019 |
| 2a.3 | d | PR-D | M | C `gate_claims.py`; M `__main__.py` (O3); T | P:1122-1125 |
| B2.1 | b | PR-B2 | M | C `playbook/rules.md`; T `test_playbook.py` | P:5838-5840 |
| B2.2 | b | PR-B2 | M (+0.5 h for the folded 3d.2 prose) | C five playbook files; M `test_playbook.py`, `prose_check.py` | P:5939-5941; Q-BD-5 (a) |
| B2.3 | b | PR-B2 | M | C `SKILL.md`; M `prompts/controller.md`, two paragraphs of nine worker prompt blocks, `tests/test_prompt_blocks.py` (phrase pins); T `test_skill.py`, `test_prompt_blocks.py` | P:6030-6032; P078:6775-6777 |
| 2b.1 | a | PR-2b | M | C `run_all.py`; M `__main__.py`, `tests/test_playbook.py` (FIXED_RULES test, plan stream rules "Cross-stream order"); T | P:1180-1183 |
| 2b.2 | a | PR-2b | M | C `tools/githooks.py`; M `__main__.py`, `gitinfo.py`; T | P:1241-1244 |
| 2b.3 | a | PR-2b | M | C workflow; M `.strict-delivery/config.yml`; T `test_self_adoption.py` | P:1331-1334 |
| 2c.1 | a | PR-2c | M | C `tools/claims_cli.py`; M `__main__.py`, `producers.py`, `tools/decisions_cli.py` (`ask --overrides`, Q-BD-1); T `test_claims_cli.py`, `test_decisions_cli.py` | P:1393-1396; P:890 |
| 2c.2 | a | PR-2c | M | P:1442-1450 list (incl. `tests/helpers.py`) | P:1441 |
| 2c.3 | a | PR-2c | L | C `dispatch.py`, `gate_dispatch.py`; M `__main__.py`, `test_playbook_drift.py`; T | P:1513-1516 |
| P1.1-P1.3 | a | PR-P1 | M each | P:1745-1747, P:1812-1814, P:1887-1891 | |
| P2.1, P2.3 | a | PR-P2 | P2.1 L + 1 h (4 h, owner answer Q-RD8b-2 (b): the event order and `residual_reachable` of owner answer Q-RD8-1 (a); class L by owner answer Q-F80RR3-3 (a): it also builds `merge.merged_errors` and the gitinfo `changed_paths`, `rev_list` and `parents`, owner answer Q-F80W-21 (a)), P2.3 M | P:1962-1965, P:2096-2099; P2.1 also `gates/lib/merge.py`, `gates/schemas/merged-log.yml`, `gates/lib/gitinfo.py`, `gates/lib/schema.py`, `tests/test_merge_lib.py`, `tests/test_gitinfo.py`, `tests/test_schema_lib.py` (plan Task P2.1 Files) | |
| P2.2 | a | PR-P2 | L | C `program_cli.py`, `lib/breakdown.py`, `schemas/breakdown.yml`; M `__main__.py`, `producers.py`; T | P615:2042-2044 |
| P3.1, P3.3 | a | PR-P3 | M | P:2179-2186 (`merge.py` exists from P2.1, plan Task P3.1 Files), P:2301-2304 | |
| P3.2 | a | PR-P3 | M (+0.5 h for Rq-5-4) | C `cleanup.py`; M `findings.py`, `gitinfo.py` (`last_text`, plus Rq-5-4's `is_ignored`, `first_parent`, `deleted_paths`, `upstream_of`, Q-BD-3; plan Task P3.2 Files); T | P:2247-2250; P:4325-4329 |
| P4.1-P4.3 | a | PR-P4 | M each | P:2360-2363, P:2402-2405, P:2466-2470 (prompt files written by A, B merged first, P:5531) | |

### 3.2 Edges

| # | from | to | kind | source |
|---|---|---|---|---|
| E05 | 1c.1 | 1c.2 | O | shared `__main__.py` `GATES` line on `b1c1` (L:383); 1c.2 also waits for the docs-only PR, which merges right after PR-1c0 (section 4; owner answer Q-DOCS-1 (e)) |
| E06 | 1c.3 | 1d.1, 1d.2 | C | `index.regenerate` P:732, P:788 |
| E06b | 1d.1 | 1d.3 | C+F | SERIAL, same module `tools/decisions_cli.py` (P078:961, P078:965) |
| E09 | 1c.1, 1c.2 | 2a.1 | O | Step 5 runs `check decisions` and `check register` before the commit (P:1011); review F-BDr-2; coordinator fact |
| E10 | 2a.1 | 2a.2 | C | `migrations.migrate` P:1026; L:389 |
| E11 | 2a.1 | 2c.2 | C+F | `migrations.*` P:1460; edits `migrations.py` P:1445 |
| E11b | 2a.1 | 1d2.1 | F | `decisions.py` is stream `d`'s until PR-D merges (section 2 row `d`) |
| E11c | 1d2.1 | 2c.2 | F | `config.py`; 2c.2 starts from `main` holding PR-1d2 |
| E13 | 2a.2 | 2a.3 | C | `claims.*` P:1130 |
| E13b | 1d.1, 1d.2 | 2a.3 (its `__main__.py` commit) | F | O3 |
| E15 | 1c.1, 1c.2, 2a.3 | 2b.1 | C | `__main__.GATES` P:1188; strict tuple P:1214-1216; the real-gates fixture test (R:F-BDr-1, P:1231) |
| E15b | 2a.1, B2.1 | 2b.1 (FIXED_RULES test) | C | plan stream rules "Cross-stream order"; P:5582 |
| E17 | 2b.1 | 2b.2 | C | P:1249 |
| E18 | 2b.1, 2b.2, 1c.3 | 2b.3 | C | P:1339 |
| E20 | 2a.2, 2b.2 | 2c.1 | C | P:1401; hook test P:1427 |
| E20b | 1d.1, 2a.1 | 2c.1 (`ask --overrides`) | F+C | P:890, P:914 |
| E20c | 2a.1 | 2c.1 (`ask --recommend`, `--source`) | C | `decision/2` `recommended` and `source` rules (P078:1148, P078:1703) |
| E12 | 2b.1 | 2c.2 | C | Step 4 runs `run_all` (P:1506); satisfied now that 2c.2 runs in PR-2c (R:F-BDr-3 resolved by Q-BDr-1 (a)) |
| E22 | 2c.2, 2a.2 | 2c.3 | C | `config.load` limits, `claims.load/stale_errors` P:1521 |
| E23 | 2a.1 | 2c.3 | F | `test_playbook_drift.py` P:1515 |
| E27, E28 | B2.1 -> B2.2 -> B2.3 | | C | P:5946, P:6037 |
| E30 | 2c.3 | P1.2 | C | `dispatch.ROLES` P:1819 |
| E31, E32 | P1.1 -> P1.2 -> P1.3 | | C | P:1819, P:1896; the session-resume edits leave P1.2 -> P1.3 unchanged (P078:7536) |
| E33 | P1.1, P1.3 | P2.1 | C | P:1970 |
| E34 | P2.1 | P2.2, P2.3 | C | P:2048, P:2104 |
| E34b | 2c.3 | P2.2 | C | `dispatch.limits_of` P615:2049 |
| E35 | P1.2, P1.3, P2.3, 2b.2, 2c.2 | P3.1 | C | P:2191 |
| E36, E37 | P3.1 -> P3.2 -> P3.3 | | C | P:2255, P:2309 |
| E38 | P1.2, P2.1, 1d.1 | P4.1 | C | P:2368; P2.1's `Batch-cut:` status fact (P078:2402) |
| E38c | 1d.3 | P4.1, P4.2 | C | P4.1 through Task 1d.3's command `decisions batch` (P078:2860), P4.2 through `batch.render_answers` (P078:2901) |
| E38d | 2c.1 | P4.1 | C | `ask --recommend`, `--source` (P078:2856, P078:2861) |
| E39 | P4.1, 2c.3 | P4.2 | C | P:2410 |
| E38b | 2c.3, P2.1 | P4.3 | C | P:2475 |

The draft's E16 (PR-C2 -> 2b.1) and E40 (PR-B2 -> P4.3) are now notes, not edges. P:1191 and P:5531 make both conditional (R:F-BDr-10). E26, whose end was a test name, is replaced by E15b.

---

## 4. Pre-program PRs, unblock conditions, schedule

The session merges one PR at a time and updates each branch before its merge (P:5560).

| PR | tasks | starts when | merges after (on `main` first) | timeline (h) | merged |
|---|---|---|---|---|---|
| PR-1c0 | 1c0.1 + reviewed docs (6890aff, 615bc21; Q-BD-6) | running | none | U1 fix and re-review to 1.0, then E | **2.5** |
| PR-C2 | (done) | the docs-only PR (owner answer Q-DOCS-1 (e)) | the docs-only PR (first in the merge queue after it, owner answer Q-RD8b-1 (a)) | U after the docs-only PR (3.75), then E: C2's final review ran before PR-1c0 (L:352), so the update restarts it (P078:7522, "Block C2 end:** final review, verifier, then the pull-request flow"; the update rule above) | **5.5** |
| PR-1c | 1c.1, 1c.2, 1c.3 | running; 1c.2 after the docs-only PR (owner answer Q-DOCS-1 (e); was after PR-1c0, L:387) | the docs-only PR, PR-C2 (merge queue) | 1c.1 to 2.0; 1c.3 (group worktree, L:206 precedent) 2.0 to 4.0; `b1c1`'s update from `main` 3.75 to 4.0; 1c.2 4.0 to 6.0; U (after PR-C2, 5.5); E | **7.75** |
| PR-resume-docs (the docs-only PR, Q-BD-6) | 1c0.2, after the session-resume design and its plan, spec and breakdown edits (P078:564; L:541) | the docs edit set's clean re-review (1c0.2, then the final review and verifier, in parallel with PR-1c0's remaining work, on a branch cut from `block/b1c`'s head); the tail after PR-1c0 merged (P078:564; owner answer Q-DOCS-1 (e)) | PR-1c0 only: it is the first merge after PR-1c0; every stream (`b`, `c`, `d`) and Task 1c.2 start after it (owner answer Q-DOCS-1 (e); revision 4 merged it after PR-C2 and PR-1c, at 8.25) | 1c0.2, its final review and verifier before PR-1c0's merge (re-checked at the cherry-pick if PR-1c0's code changed after them); the tail: cut from `main`, cherry-pick, gates (U) 2.5 to 2.75; the rest of its end 2.75 to 3.75 (the owner's approval of the head, the merge, read-back, post-merge gates, `MERGED` line; owner answer Q-RD8c-1 (b)) | **3.75** |
| PR-D | 2a.1, 2a.2, 2a.3 | the docs-only PR (owner answer Q-DOCS-1 (e); L:389) | the docs-only PR, PR-1c (E09), PR-1d (O3) | `sd1`'s update 3.75 to 4.0; 2a.1 4.0 to 7.0; wait for PR-1c (7.75), then U and records, store.py and test_store.py part 0.5 h, commit at 8.75; 2a.2 8.75 to 10.75; 2a.3 10.75 to 12.75, then, after PR-1d (13.75), U and its `GATES["claims"]` commit, to 14.0 (O3); E | **15.5** |
| PR-B2 | B2.1, B2.2, B2.3 | the docs-only PR (`sb2` cut from `main` after it, owner answer Q-DOCS-1 (e)) | PR-1c0, the docs-only PR, PR-C2, PR-1c (merge queue) | B2.1 3.75 to 5.75; B2.2 to 8.25; B2.3 to 10.25; U (after PR-1c, 7.75); E | **12.0** (before PR-1d in the merge queue: the shortest order, revision 3) |
| PR-1d | 1d.1, 1d.2, 1d.3 | PR-1c | PR-1c, PR-B2 (merge queue) | 1d.1 \|\| 1d.2 7.75 to 9.75; 1d.3 (E06b) 9.75 to 11.75; U after PR-B2's merge (12.0); E | **13.75** |
| PR-1d2 | 1d2.1 | PR-D (E11b) | PR-D | 1d2.1 15.5 to 17.5; E | **19.0** |
| PR-2b | 2b.1, 2b.2, 2b.3 | PR-D (E15) and PR-B2 (E15b) | PR-D, PR-B2, PR-1c, PR-1d2 (its U) | 15.5 to 21.5; U (after PR-1d2, 19.0); E | **23.25** |
| PR-2c | 2c.1, 2c.2, 2c.3 | PR-2b (E12, E20), PR-1d (E20b), PR-D | PR-2b | 2c.1 \|\| 2c.2 23.25 to 25.25; 2c.3 (L) to 28.25; E (nothing merges after its cut, so no U) | **29.75** |
| PR-P1 | P1.1-P1.3 | PR-2c (P:1692) | PR-2c | serial 6 h; E | **37.25** |
| PR-P2 | P2.1-P2.3 | PR-P1 | PR-P1 | P2.1 (L + 1 h, owner answer Q-RD8b-2 (b)) 4 h; P2.2 (L) \|\| P2.3 3 h; E | **45.75** |
| PR-P4 | P4.1-P4.3 | PR-P2 (Q-BD-2) | PR-P2 | P4.1 \|\| P4.3 2 h; P4.2 2 h; E | **51.25** |
| PR-P3 | P3.1-P3.3 (+Rq-5-4) | PR-P2 (Q-BD-2) | PR-P2; update after PR-P4 (shared `__main__.py`, `test_self_adoption.py`) | 6.5 h; U (after PR-P4); E | **54.0** |
| program setup | program plans (written from about 36.25 h on, in parallel), `streams.yml`, `breakdown.yml` (Part II), the owner's `stream-ownership` decision for `release`'s version sites (asked and answered before `program create`, owner answer Q-F80W-13 (a)), the owner's `program-create` decision, `program create --plan`, worktrees, M1-M10 (P:2559) and M-B4-1 (P:3325) | PR-P1..P4 | — | 2 h | **S = 56.0** |

Notes.
- FIXED_RULES test (F-BD-4). PR-D (15.5) merges after B2's final review (about 10.25-12.0) and after PR-B2 (12.0). So by P:5582 the "B2 merges first" branch applies, and A writes the test: in 2b.1, which is A's first task after both PRs are on `main` (plan stream rules, "Cross-stream order"). B2 does not wait, and its final review is not re-run.
- PR-C2 carries `cites` into `run_all` from the start, because C2 merges before 2b.1 starts (P:1191, P:5574).

**Pre-program waves (cap 25; peak 15):**

| wave | window | agents |
|---|---|---|
| W1 | 0-3.75 | 1c0 fix and end 4; 1c.1 2; 1c.3 2; this revision 1; docs writer 1; 1c0.2 2; the docs-only PR's final review, verifier and tail 2 (to 3.75) = 14 |
| W2 | 3.75-7.75 | 1c.3 2 (to 4.0); C2's U and end 2 (3.75 to 5.5); 1c.2 2 (4.0 to 6.0); 1c's U and end 2 (6.0 to 7.75); 2a.1 2; B2.1 and B2.2 2 (from 3.75); PC1 drafters 2 (from 3.75, when the streams start) = 14 |
| W3 | 7.75-15.5 | 1d.1, 1d.2 4 (then 1d.3 2); 2a.1's store.py part, 2a.2 or 2a.3 2; B2.2 and B2.3 2 (to 10.25); B2's U and end 2 (10.25 to 12.0); 1d end 2 (12.0 to 13.75); D end 2 (14.0 to 15.5); PC1 drafter 1 = 15 |
| W4 | 15.5-23.25 | 2b.x 2; 1d2.1 2; 1d2 end 2; 2b end 2; PC1 drafter 1 = 9 |
| W5 | 23.25-29.75 | 2c.1, 2c.2 4 (then 2c.3 2); 2c end 2 = 6 |
| W6-W8 | 29.75-54.0 | P1 4; P2 6; P3 and P4 with both ends 10; program-plan writer and reviewer 2 = at most 12 |

Antichains (all edges checked; E09 binds only 2a.1's Step 5 commit, which runs "on `block/sd1` after it has merged `main` containing block 1c's pull request", P078:1287, so 2a.1's work is in the first set): {1c0.2, 1c.3, 1c.2, 2a.1, B2.1}, {1d.3, 2a.2, B2.3}, {1d2.1, 2b.1}, {1d.1, 1d.2, 2a.2, B2.3}, {2c.1, 2c.2}, {P2.2, P2.3}, {P3.1, P4.1, P4.3}.

---

## 5. Pre-program critical path

**PR-1c0 (2.5) -> the docs-only PR's tail: U, approval, merge, read-back, post-merge gates (3.75) -> B2.1, B2.2, B2.3 -> PR-B2's U and E -> PR-B2 (12.0) -> PR-1d's U and E -> PR-1d (13.75) -> U and 2a.3's `GATES["claims"]` commit (O3) -> PR-D (15.5) -> 2b.1, 2b.2, 2b.3 -> PR-2b (23.25) -> 2c.2 -> 2c.3 -> PR-2c (29.75) -> P1 (37.25) -> P2, with P2.1 at L + 1 h (45.75) -> P3 (54.0) -> setup (S = 56.0).**

Revision 3: the update comes before the final review (P078:6251; P:5560), so an update after another PR's merge restarts that PR's E (line U of section 1). Revision 5 (owner answers Q-DOCS-1 (e), Q-RD8b-1 (a), Q-RD8b-2 (b), Q-RD8c-1 (b)): Task 1c0.2 and the docs-only PR's final review and verifier run before PR-1c0 merges, so after it only the docs-only PR's tail remains and it is the first merge after PR-1c0 (3.75: its tail is U plus the rest of its end, 1.25 h, owner answer Q-RD8c-1 (b)); PR-C2, PR-1c, PR-B2, PR-1d and PR-D follow in the queue, and every stream and Task 1c.2 start at 3.75 (`sb2`, cut then) or after their branch's update (4.0). Of the 20 feasible orders of those five, three give the shortest path, S = 56.0: (PR-C2, PR-1c, PR-B2, PR-1d, PR-D), kept here as the one with PR-C2 earliest (owner answer Q-RD8b-1 (a)), (PR-1c, PR-C2, PR-B2, PR-1d, PR-D), and (PR-1c, PR-B2, PR-1d, PR-D, PR-C2), which merges PR-C2 after 2b.1 starts; the best order with PR-1d before PR-B2 is (PR-1c, PR-1d, PR-B2, PR-D, PR-C2), S = 57.0. Within the 16 of those orders that also merge PR-C2 before 2b.1 starts (the PR-C2 note in the Notes above), the shortest is still 56.0 and the best with PR-1d before PR-B2 is (PR-1c, PR-C2, PR-1d, PR-B2, PR-D), S = 57.25. Revision 4's figures (120 orders of six PRs with the docs-only PR among them, S = 53.75, 54.75 and 55.0, with P2.1 at 3 h) are replaced: the docs-only PR's tail (U and the rest of its end, 1.25 h) now comes before every stream starts, and Task P2.1 is 1 h longer (L + 1 h, owner answer Q-RD8b-2 (b)), so the path, through B2 as in revision 4, moves +2.25 h. Slack: PR-1c's line, 0.25 h (1d.3 ends at 11.75, before PR-B2's merge at 12.0, which sets PR-1d's U); the 2a.1 -> 2a.2 -> 2a.3 work (12.75) 1.0 h; PR-1d2 (19.0) 2.5 h before it would hold PR-2b's U.

---

## 6. Program record (Part II, the future `breakdown.yml`)

The schema fields `done`, `period`, `residual` and path windows are the additions stated in plan Task P2.2 (`breakdown/1`) and Task P2.1 (`streams/1`). Period events are `program-start`, `merged:<stream>/<sub-block>` (the PR that carries that sub-block read back as merged, from its `MERGED` line; one stream PR can carry several sub-blocks, as `init4`'s carries 4c, 4d and 4e: plan Task P2.3, owner answer Q-F80W-2), `merged:<stream>` (the stream's last sub-block merge: its last `merged:<stream>/<sub-block>` event; `final=yes` marks the plan's last PR and is not used, F-BDr3-2) and `program-close` (R2:F-BDr2-1; plan Task P2.2, and Task P1.2's `MERGED` line).

```yaml
schema: breakdown/1
plan: 2026-10-31-strict-delivery-framework
max_concurrent: 25
max_depth: 5
done: [1a.1, 1a.2, 1a.3, 1b.1, 1b.2, 1b.3, 1c0.1, 1c0.2, 1c.1, 1c.2, 1c.3, 1d.1, 1d.2,
       1d.3, 1d2.1, 2a.1, 2a.2, 2a.3, 2b.1, 2b.2, 2b.3, 2c.1, 2c.2, 2c.3,
       P1.1, P1.2, P1.3, P2.1, P2.2, P2.3, P3.1, P3.2, P3.3, P4.1, P4.2, P4.3,
       B1.1, B1.2, B1.3, B2.1, B2.2, B2.3, C1.1, C1.2, C2.1, C2.2]
streams:
  - {id: residual, residual: true, period: {from: program-start, until: program-close},
     tasks: [R1.1, R2.1, R2.2, R2.3, R3.1, R3.2, R4.1, R5.1],
     unblock: "R1.1 at program start; R1 PR first (docs needs it); R2.1 after merged:context and merged:package; R2.2 after merged:docs; R2.3 after merged:evidence; R3.x after merged:context, merged:runtime, merged:tools, merged:bash; R4.1 after merged:evidence, merged:rules4 (P078:5329); R5.1 (the interim-skill removal, Q-BRV-1 (a)) at the plugin enable point: after merged:runtime and merged:package, once the owner's enablement is ledgered (Q-PLG-1 (a); P078:3091, P078:3787-3788)"}
  - {id: runtime, period: {from: program-start, until: merged:runtime}, paths: [P:2550 row], tasks: [3a.1, 3a.2],
     unblock: "at program start; 3a.2 after M1-M10"}
  - {id: package, period: {from: program-start, until: merged:package}, paths: [P:2553 row without the 3d.2 paths], tasks: [3d.1],
     unblock: "at program start; PR after Rq-4-1 has landed"}
  - {id: bash, period: {from: program-start, until: merged:bash}, paths: [P:2551 row], tasks: [3b.1, 3b.2, 3b.3],
     unblock: "3b.1 at program start; 3b.2 after merged:runtime and merged:package"}
  - {id: tools, period: {from: merged:package, until: merged:tools}, paths: [P:2552 row], tasks: [3c.1, 3c.2],
     unblock: "after merged:runtime and merged:package"}
  - {id: cfg4, period: {from: program-start, until: merged:cfg4},
     paths: [P:3377 row, playbook/decisions.md, skills/strict-delivery/SKILL.md, tests/test_skill.py],   # last three by the Q-BD-8 (a) stream-ownership decision
     tasks: [4a.1, 4a.2, 4a.3], unblock: "4a.1 at program start; 4a.2 after merged:package"}
  - {id: rules4, period: {from: merged:cfg4, until: merged:rules4}, paths: [P:3378 row], tasks: [4b.1, 4b.2],
     unblock: "after merged:cfg4"}
  - {id: init4, period: {from: program-start, until: merged:init4},
     paths: [P:3379 row,
             {path: gates/__main__.py, from: merged:residual/R2}, {path: gates/producers.py, from: merged:residual/R2},
             {path: gates/run_all.py, from: merged:residual/R2}, {path: tests/test_run_all.py, from: merged:residual/R2},
             {path: CLAUDE.md, from: merged:residual/R2}, {path: .gitignore, from: merged:residual/R2}],   # Q-BD-8 (a); windows: Q-BDr2-1
     tasks: [4c.1, 4c.2, 4d.1, 4d.2, 4d.3, 4e.1, 4e.2, 4e.3],
     unblock: "4c after M-B4-1; 4d after merged:cfg4 and merged:package; the Rq-4-2, Rq-4-5, Rq-4-3 commits at the end of 4e.3 after merged:residual/R2 (window start); the Rq-4-5 commit also removes the interim CLAUDE.md text of Task 1c0.2 (P078:3846)"}
  - {id: context, period: {from: program-start, until: merged:context}, paths: [P:4366-4489 Files], tasks: [5a.1, 5a.2, 5a.3],
     unblock: "at program start"}
  - {id: docs, period: {from: program-start, until: merged:docs}, paths: [P:4551, P:4608, P:4665, P:4730 Files], tasks: [5b.1, 5b.2, 5c.1, 5c.2],
     unblock: "at program start (Rq-5-4 is on main from P3.2); the 5c end after merged:residual/R1 (Rq-5-5)"}
  - {id: evidence, period: {from: program-start, until: merged:evidence}, paths: [P:4812 row], tasks: [6E.1, 6E.2, 6E.3],
     unblock: "at program start"}
  - {id: checkpoint, period: {from: program-start, until: merged:checkpoint}, paths: [P:4813 row], tasks: [6K.1, 6K.2],
     unblock: "at program start; 6K.2 after merged:runtime (worktrees.same_repository, P078:5807)"}
  - {id: release, period: {from: merged:init4, until: program-close}, paths: [P:4814 row incl. the version sites], tasks: [6R.1, 6R.2, 6R.3],
     unblock: "after every other stream and residual R2, R3 and R4 have merged (P:4799; P078:5309); the version sites by the `stream-ownership` decision, asked and answered before `program create` (owner answer Q-F80W-13 (a)), so their windows are in this record from `create`"}
edges:   # task -> task only
  - {from: 3a.1, to: 3a.2}        # P:2697
  - {from: 3b.1, to: 3b.2}        # P:2891
  - {from: 3a.2, to: 3b.2}        # hookio, transcript, worktrees P:2891
  - {from: 3b.2, to: 3b.3}        # P:3007
  - {from: 3a.2, to: 3c.1}        # hookio P:3101
  - {from: 3a.1, to: 3c.1}        # session P:3101
  - {from: 3a.2, to: 3c.2}        # P:3145
  - {from: 3d.1, to: 4a.2}        # plugin.framework_dir P:3520; P:3328
  - {from: 4a.1, to: 4a.2}        # P:3332
  - {from: 4a.2, to: 4a.3}        # P:3332
  - {from: 4a.2, to: 4b.1}        # config overrides P:3632
  - {from: 4a.3, to: 4b.2}        # roles, budgets, dispatch P:3668
  - {from: 4b.1, to: 4b.2}        # P:3332
  - {from: 4c.1, to: 4c.2}        # P:3332
  - {from: 4c.2, to: 4d.1}        # P:3848
  - {from: 4a.2, to: 4d.1}        # profiles.load P:3848
  - {from: 3d.1, to: 4d.1}        # plugin.version, repository_slug P:3848
  - {from: 4d.1, to: 4d.2}        # P:3936
  - {from: 4d.2, to: 4d.3}        # P:4006
  - {from: 4d.3, to: 4e.1}        # doctor.check P:4092
  - {from: 4e.1, to: 4e.2}        # P:4170
  - {from: 4e.2, to: 4e.3}        # P:3332
  - {from: 5a.1, to: 5a.2}        # P:4299
  - {from: 5a.2, to: 5a.3}        # P:4494
  - {from: 5b.1, to: 5b.2}        # P:4614
  - {from: 5c.1, to: 5c.2}        # P:4736
  - {from: 6E.1, to: 6E.2}        # P:5014
  - {from: 6K.1, to: 6K.2}        # P:5296
  - {from: 3a.2, to: 6K.2}        # worktrees.same_repository P078:5807
  - {from: 3d.1, to: R2.1}        # orders package's registry window before residual R2's (owner Q-F80-1 (a); Block 3 registration ruling)
  - {from: 5a.3, to: R2.1}        # registry line after its module (P:4321)
  - {from: 5a.2, to: R2.1}
  - {from: 5b.2, to: R2.2}
  - {from: 5c.2, to: R2.2}
  - {from: 6E.2, to: R2.3}
  - {from: 6E.3, to: R2.3}
  - {from: 5a.3, to: R3.2}        # gate_context into the hooks (P:4354)
  - {from: 5a.2, to: R3.1}        # receipts.record
  - {from: 3a.2, to: R3.1}        # post_read, session_start
  - {from: 3c.2, to: R3.2}        # pre_agent
  - {from: 3b.3, to: R3.2}        # pre_bash gated commit
  - {from: 6E.3, to: R4.1}        # loopstats.small_signals P078:6165
  - {from: 4b.2, to: R4.1}        # dispatch.py as Task 4b.2 left it P078:6165
  - {from: 3a.2, to: R5.1}        # enable point: hooks/hooks.json on main (P078:3091)
  - {from: 3d.1, to: R5.1}        # enable point: plugin.json, marketplace.json (P078:3091)
  - {from: 4e.3, to: 6R.1}        # repo_fixtures P:5362
  - {from: 6K.2, to: 6R.1}
  - {from: 6E.2, to: 6R.1}
  - {from: R3.2, to: 6R.1}        # hook behaviour of context (P:5361-5366)
  - {from: R4.1, to: 6R.1}        # Task 6R.1 waits for Block R4 P078:6191
  - {from: 6R.1, to: 6R.2}
  - {from: 6R.2, to: 6R.3}
groups:   # antichains, each within 25 tasks
  - {id: g-start, tasks: [3a.1, 3d.1, 3b.1, 4a.1, 4c.1, 6K.1, 5a.1, R1.1, 6E.1, 6E.3]}
  - {id: g-mid, tasks: [3a.2, 4a.2, 4c.2, 5a.2, 6E.2]}        # 6K.2 moved to g-hooks: edge 3a.2 -> 6K.2
  - {id: g-hooks, tasks: [3b.2, 3c.1, 3c.2, 4a.3, 5b.1, 5c.1, 6K.2]}
```
`R1.1`..`R3.2` are new plan tasks (plan section "Stream `residual`"). They are written here as the record must name them. `R4.1` is plan Task R4.1 (P078:6156) and `R5.1` plan Task R5.1 (owner answer Q-BRV-1 (a)), both added by the session-resume revision (revision 3).

### 6.1 Program PRs and unblock conditions

| PR | starts | merges after | timeline (from S = 56.0; each PR's U follows the last earlier merge and precedes its E, P078:6251, P:5560) | merged |
|---|---|---|---|---|
| PR-residual/R1 (event merged:residual/R1) (R1.1, Rq-5-5 prose) | S | — | S, 1 h, E | S+2.5 |
| PR-package (3d.1, Rq-4-1) | S | Rq-4-1 landed (P:3359) | 2 h + 0.5; U after PR-residual/R1 (S+2.5); E | **S+4.25** |
| PR-runtime | S | — | 3a.1 2 h, 3a.2 3 h; U after PR-package; E | **S+6.75** |
| PR-residual/R5 (event merged:residual/R5) (R5.1, the interim-skill removal, Q-BRV-1 (a)) | the enable point: PR-runtime (S+6.75) and PR-package merged, the enablement ledgered | PR-runtime, PR-package | R5.1 (S) S+6.75 to S+7.75; U after PR-runtime (residual's branch is cut at program start, and PR-residual/R1, PR-package and PR-runtime merge after it); E | **S+9.5** |
| PR-cfg4 | S | PR-package | 4a.1 to S+2; 4a.2 S+4.5 to S+6.5; 4a.3 + decisions.md row 2.5 h to S+9.0; U after PR-residual/R5; E | **S+11.25** |
| PR-context | S | — | 6 h (to S+6); U after PR-cfg4; E | **S+13.0** |
| PR-evidence | S+4.25 (wave cap) | — | (6E.1, 6E.2) \|\| 6E.3, 4 h; group merge 0.5 (to S+8.75); U after PR-context; E | **S+14.75** |
| PR-bash | S | PR-runtime, PR-package | 3b.1 to S+2; 3b.2 S+7.0 to S+10.0; 3b.3 to S+12.0; U after PR-evidence; E | **S+16.5** |
| PR-rules4 | S+11.5 | PR-cfg4 | 4 h (to S+15.5); U after PR-bash; E | **S+18.25** |
| PR-tools | S+7.0 | PR-runtime, PR-package | 2 h (to S+9.0); U after PR-rules4; E | **S+20.0** |
| PR-checkpoint | S+2.5 (PW1) | PR-runtime (6K.2, edge 3a.2 -> 6K.2) | 6K.1 S+2.5 to S+4.5; 6K.2 S+8.25 (wave cap) to S+10.25; U after PR-tools; E | **S+21.75** |
| PR-docs | S+10.25 (wave cap) | PR-residual/R1 (event merged:residual/R1) | two groups of 4 h; 0.5 (to S+14.75); U after PR-checkpoint; E | **S+23.5** |
| PR-residual/R3 (R3.1, R3.2) | S+20.0 (merged:tools) | PR-context, -runtime, -tools, -bash | 2 h (to S+22.0); U after PR-docs; E | **S+25.25** |
| PR-residual/R2 (R2.1-R2.3) | S+23.5 | PR-package, -context, -docs, -evidence | 1 h (parallel, to S+24.5); U after PR-residual/R3; E | **S+27.0** |
| PR-residual/R4 (event merged:residual/R4) (R4.1, Rq-6-5) | S+18.25 | PR-evidence, PR-rules4 (P078:5329) | 2 h (to S+20.25); U after PR-residual/R2; E | **S+28.75** |
| PR-init4 | S | PR-cfg4, PR-package; registry window after merged:residual/R2 | 4c to S+4, sub-end S+5; 4d from S+11.5: 4d.1 to S+14.5, 4d.2 to S+16.5, 4d.3 to S+18.5, sub-end S+19.5; 4e.1 to S+22.5, 4e.2 to S+24.5, 4e.3 to S+26.5; after merged:residual/R2 (S+27.0) a U, then the Rq-4-2, Rq-4-5, Rq-4-3 commits 1 h to S+28.25 (order P:3362); U after PR-residual/R4; E | **S+30.5** |
| PR-release | after all of the above | all | 6R.1 to S+32.5; 6R.2 to S+34.5; E to S+36.0; 6R.3 (tag on the owner's word) | **S+37.0** |

### 6.2 Program waves (cap 25; review F-BDr-9; revision 3)

Each count is the peak of the agents live in the window: 1 per stream controller and group sub-controller (a stream waiting in the merge queue keeps its controller), 2 per active task and per PR end (its U and E). The intervals were listed in the revision-3 working draft (git-ignored, so not a cite) and summed by script; the peaks are the ones ledgered at L:558.

| wave | window | what runs | agents (peak) |
|---|---|---|---|
| PW1 | S to S+4.25 | controllers of runtime, package, bash, cfg4, init4, context, residual, checkpoint (from S+2.5); 3a.x, 3d.1, 3b.1, 4a.1, 4c.x and the 4c end, 5a.x, R1.1 and the R1 end, 6K.1, the package end; 1 PC1 drafter to S+4 | **22** |
| PW2 | S+4.25 to S+9.5 | evidence (from S+4.25) + loopstats group, tools (from S+6.75); 3a.2 and the runtime end, 4a.2, 4a.3, 5a.x, 6E.x, 3b.2, 3c.x, R5.1 and the R5 end, 6K.2 from S+8.25 | **23** (at S+7) |
| PW3 | S+9.5 to S+16.5 | docs (from S+10.25) + 2 groups, rules4 (from S+11.25); the cfg4, context, evidence and bash ends one after another; 3b.3, 4b.x, 4d.x, 5b.x, 5c.x | **23** (at S+11.5) |
| PW4 | S+16.5 to S+23.5 | the rules4, tools, checkpoint and docs ends; R4.1, R3.1 and R3.2; 4d.x, 4e.x | **14** (at S+20.0, where R4.1 overlaps R3.1 and R3.2) |
| PW5 | S+23.5 to S+30.5 | R2.x; the R3, R2, R4 and init4 ends; 4e.x, the Rq commits | 12 |
| PW6 | S+30.5 to S+37.0 | release = 1 | 6R.x = 2, 3 |

All waves are at or under the measured 25 and leave at least 2 slots. Launches past the limit are refused, not queued (P:862). Evidence starts at S+4.25, after the package end, and 6K.2 at S+8.25, after the 6E groups: either earlier would bring PW1 or PW2 to 24 or 25.

The program end is set by the merge queue (revision 3): every stream branch is cut at program start, except `tools`, `rules4` and `release`, which cut theirs when they start, after `merged:package`, `merged:cfg4` and `merged:init4`, and each `residual` sub-block's group branch, cut from `main` when the sub-block starts and merged into `residual/main` after that branch's update from `main` (plan Process and section Stream `residual`, owner answer Q-F80W-12 (a): a commit is judged at the merges that are its ancestors), so each PR's update after the merge before it restarts its final review (P078:6251, P:5560). PR-residual/R5 is no exception: its branch is cut at program start too, so it updates after PR-runtime and merges at max(S+7.75, S+6.75) + 1.75 = S+9.5. From PR-residual/R5 (S+9.5) on, each merge follows the one before by U + E = 1.75 h, so PR-init4 merges at S+9.5 + 12 x 1.75 = S+30.5. Docs, evidence, checkpoint and tools wait in the queue with their work done. Tasks do wait on those merges: by residual's `unblock`, R3.x starts after merged:tools (S+20.0), R2.2 after merged:docs (S+23.5), R2.3 and R4.1 after merged:evidence; release starts after every other stream has merged, checkpoint and evidence included. In this order none of these waits sets a merge time: R3 merges at max(S+22.0, S+23.5) + 1.75 = S+25.25 and R2 at max(S+24.5, S+25.25) + 1.75 = S+27.0, each paced by the merge before it. A reorder that merges docs, evidence or tools later delays R2.x, R3.x or R4.1, and through R2 the Rq commits of init4.

---

## 7. Critical path and estimate (draft's unit costs)

**PR-1c0 (2.5) -> the docs-only PR's tail (3.75) -> B2.1-B2.3 / PR-B2 (12.0) -> PR-1d's U and E (13.75) -> 2a.3's `GATES["claims"]` commit (O3) -> PR-D (15.5) -> 2b.1-2b.3 -> PR-2b (23.25) -> 2c.2 -> 2c.3 -> PR-2c (29.75) -> P1 (37.25) -> P2 with P2.1 at L + 1 h (45.75) -> P3 with Rq-5-4 (54.0) -> setup (56.0) -> 3a.1, 3a.2 / PR-runtime (S+6.75) -> R5.1 / PR-residual/R5 (S+9.5) -> the merge queue, each merge U + E after the one before: PR-cfg4 (S+11.25), -context, -evidence, -bash, -rules4, -tools, -checkpoint, -docs, PR-residual/R3, /R2, /R4, PR-init4 (S+30.5) -> 6R.1, 6R.2, PR-release, 6R.3 (S+37.0) ≈ 93.0 working hours.**

- Against revision 1 (80 h): +6.75 h. The added time comes from the L:387/L:389 waits, E09 (including 0.5 h for the store.py window, R2:F-BDr2-3) and E15, and is offset by Q-BD-8 (a) (no A-R6 PR, −2.25 h) and by folding 3d.2.
- The review's corrected figure was 90.75 h with D's old scope, and 87.25 h under its Q-BDr-1 (a). The review re-checked 86.25 h (review 2); the store.py window adds 0.5 h, giving 86.75 h. The remaining 0.5 h below the review's 87.25 h comes from 1c.3 running alongside 1c.2 in a group worktree. It is my scheduling choice; without it the path is 87.75 h.
- Revision 3 (session-resume revision, F-DR-6 and its reviews): +3.0 h, 89.75 h. Pre-program +0.75 h: +1.0 h because Task 1d.3 (M, after 1d.1) lengthens PR-1d, which updates after PR-B2 and merges at 12.5, and O3 holds PR-D to 14.25 (was 13.25); -0.25 h because PR-2c no longer needs a U (nothing merges after its cut), so it ends 6.5 h after PR-2b, not 6.75 h. Program +2.25 h (S+34.75 -> S+37.0): with every E after its PR's last U, the program's PRs, each cut before the merges it follows, form a merge queue in which, from PR-residual/R5 (S+9.5, after its own update following PR-runtime) on, each merge follows the one before by U + E = 1.75 h, to PR-init4 at S+30.5. Task R5.1 is merged first after PR-runtime, as MS:715 ("removed once the plugin is enabled") and owner answer Q-BRV-1 (a) (L:555, "merged about S+8.25") put it, kept by owner answer Q-BRV-3 (a) at a cost of about 0.5 h: the shortest unforced order found merges R5 after PR-context (S+10.25) and ends at S+36.5 (beam search, an upper bound; wave cap unchecked). Revision 4 (owner answer Q-F80RR3-3 (a)): Task P2.1 is class L (3 h, not 2 h), since it also builds `merge.merged_errors` and three gitinfo functions (owner answer Q-F80W-21 (a)); P2.1 is on the critical path, so PR-P2 (43.5), PR-P4 (49.0), PR-P3 (51.75), S (53.75) and the total (90.75 h) each move +1.0 h, the program's S+ times are unchanged, and the waves keep their counts. The classes M for 1c0.2, 1d.3 and R4.1 and S for R5.1 are this revision's estimates. Revision 5 (owner answers Q-DOCS-1 (e), Q-RD8b-1 (a), Q-RD8b-2 (b), Q-RD8c-1 (b)): Task 1c0.2 and the docs-only PR's final review and verifier run before PR-1c0 merges, on a branch cut from `block/b1c`'s head, so the docs-only PR merges at 3.75 (was 8.25), after only its tail (cut from `main`, cherry-pick, gates (U), then the rest of its end, 1.0 h: approval, merge, read-back, post-merge gates, `MERGED` line; owner answer Q-RD8c-1 (b)); every stream and Task 1c.2 start after it. So B2.1 starts at 3.75 (was 2.5) and 1c.2 at 4.0 (was 2.75); with PR-C2 kept first in the queue (of the three tied shortest orders, the one with PR-C2 earliest), PR-C2 (5.5, was 4.25), PR-1c (7.75, was 6.5), PR-B2 (12.0, was 10.75), PR-1d (13.75, was 12.5), PR-D (15.5, was 14.25), PR-1d2 (19.0, was 17.75), PR-2b (23.25, was 22.0), PR-2c (29.75, was 28.5) and PR-P1 (37.25, was 36.0) each move +1.25 h; Task P2.1 is L + 1 h (4 h, owner answer Q-RD8b-2 (b)), so PR-P2 (45.75, was 43.5), PR-P4 (51.25, was 49.0), PR-P3 (54.0, was 51.75), S (56.0, was 53.75) and the total (93.0 h, was 90.75 h) each move +2.25 h; the critical path runs through B2 as in revision 4, now after the docs-only PR's tail and its approval; the program's S+ times and waves are unchanged, and the pre-program waves are re-cut at the new merges (peak 16, was 15).
- Range: about 54 h if every task takes 1 h; about 118 h if every task takes 3 h (revision 2's figures; revision 3 does not recompute them). The path has 28 owner approvals (revision 2: 15; revision 4: 27): the pre-program PR-1c0, the docs-only PR, PR-B2, PR-1d, PR-D, PR-2b, PR-2c, P1, P2 and P3 (revision 5, owner answer Q-DOCS-1 (e): the docs-only PR's approval is in its tail, on the path); the release `stream-ownership` decision and the `program-create` decision, both before `program create` (owner answer Q-F80W-13 (a)); PR-runtime, PR-residual/R5, PR-cfg4, -context, -evidence, -bash, -rules4, -tools, -checkpoint, -docs, PR-residual/R3, /R2, /R4, PR-init4 and PR-release; the 6R.3 tag.
