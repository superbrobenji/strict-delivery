# Stream breakdown (2026-11-02): strict-delivery framework, all remaining work

The human schedule for the plan `docs/strict-delivery/plans/2026-10-31-strict-delivery-framework.md`, the last planning step (owner Q-PL-1 (a)). Copied from the reviewed draft `.superpowers/sdd/2026-10-31-strict-delivery-framework-plans/stream-breakdown-draft.md` (sections 1-7; its findings and its edit list are applied to the plan and specs and are not repeated). Owner answers: Q-BDr-1 (a), Q-BD-4 (a), Q-BD-5 (a), Q-BD-7 (a), Q-BD-8 (a), Q-BDr2-1 (a); controller rulings Q-BD-1, Q-BD-2, Q-BD-3, Q-BD-6 and the `done` field under Q-BD-7 (a). Not a checked record: section 6 is the content of the future `breakdown.yml` (`breakdown/1`), written before `program create`.


The last planning step (owner directive and Q-PL-1 (a), 2026-11-02, L:381-382). Revision 2 applies the review `stream-breakdown-review.md` (F-BDr-1..12) and the owner answers and controller rulings of L:393.

**Two artefacts, by owner answer Q-BD-7 (a) and review F-BDr-8.** `program create --plan 2026-10-31-strict-delivery-framework` checks one `breakdown.yml` against this plan and against `streams.yml` (P615:2054-2060). At that moment every pre-program task (1c..P4, B2, C2, D) is done. So:
- **Part I, the pre-program schedule (sections 2-5):** the session's working schedule from now to the programs block's last PR. It is not a checked record. P2.2's checker does not exist yet, and the session coordinates these streams by hand (P:5517).
- **Part II, the program record (section 6):** the `breakdown/1` content committed before `program create`. Every pre-program task is in `done`; the streams are exactly the program's (including `residual`, Q-BD-4 (a)); and ownership that moves during the program is written with `period` (Q-BD-7 (a)). Its schema additions are listed under "Plan and spec edits".

**Citation keys.**
- `P:<n>`: the plan at `5283c51`.
- `P615:<n>`: the plan at `615bc21`, the head of `block/b1c` (used for text that changed after 5283c51: the breakdown schema, 3d.2's heading, Block 6's Rules N/T note).
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
  - L: 3 h. The L tasks are 2a.1, 2c.3, P2.2, 3a.2, 3b.2, 4d.1 and 4e.1.
- E (block or stream PR end: final review, verifier, owner approval, merge, read-back, post-merge gates, MERGED line): 1.5 h.
- A sub-block end without a PR: 1 h.
- U (update from `main` before a merge, P:5560): 0.25 h.
- Records migration step (P:1011): 0.25 h.
- Agent count per active task: 2 (implementer and reviewer). A block end also counts 2. Each program stream controller counts 1, and each group sub-controller counts 1.
- t = 0 is now (2026-11-02, 1c0.1 fix round for U1 running, L:393; 1c.1 running).

---

## 2. Pre-program streams (Part I)

| id | period | branch | owns (paths) | open tasks | starts when |
|---|---|---|---|---|---|
| `a` | now -> program start | `block/b1c` (1c0), `block/b1c1`, `block/b1d`, `block/b2b`, `block/b2c`, `block/p1`..`p4` | residual: every path not owned by `b`, `c` or `d` in the same window (P:5527). The five shared files stay A's (P:5532), except the `__main__.py` window below. | 1c0.1 (fix round), 1c.1-1c.3, 1d.1, 1d.2, 2b.1-2b.3, 2c.1 (with `ask --overrides`), 2c.2, 2c.3, P1.1-P4.3 | running |
| `b` | -> PR-B2 merged | `block/sb2` | P:5525 row, plus B2.2's added prose (Q-BD-5 (a)) | B2.1, B2.2, B2.3 | PR-1c0 merged (L:374) |
| `c` | -> PR-C2 merged | `block/sc2` | P:5526 row | none: C2.1 and C2.2 are complete (L:313, L:352); only the PR is left | PR-C2 may merge after PR-1c0 (P:6956) |
| `d` | PR-1c0 merged -> PR-D merged | `block/sd1` | 2a.1 Files without `decisions_cli` (Q-2a1-1 (a), L:387): `gates/lib/migrations.py`, `gates/schemas/decision.yml`, `gates/lib/decisions.py`, `tests/test_playbook_drift.py`, `tests/test_migrations.py`, `tests/test_decisions_lib.py`, and `gates/lib/store.py` and `tests/test_store.py` **both from PR-1c merged** (order rule O2; R2:F-BDr2-3). 2a.2: `gates/schemas/claim.yml`, `gates/lib/claims.py`, `gates/lib/gitinfo.py` (additive `blob_id`), `tests/test_claims_lib.py`. 2a.3: `gates/gate_claims.py`, `tests/test_gate_claims.py`, and `gates/__main__.py` `GATES["claims"]` **from PR-1d merged** (order rule O3). | 2a.1, 2a.2, 2a.3 | PR-1c0 merged and `sd1` updated (L:389) |

**Order rules that resolve the overlaps (R:F-BDr-7).** Each is checked against the schedule in section 4.
- **O1 `gates/lib/gitinfo.py` (a and d).**
  - 1c0.1's changes reach `main` before D starts (L:389).
  - D's `blob_id` (2a.2) reaches `main` with PR-D.
  - A's next writer, 2b.2, starts only after PR-D, because 2b.1 waits for PR-D (E15). So there is no concurrent writer.
- **O2 `gates/lib/store.py` (1c.2 and 2a.1).**
  - 1c.2 adds its private merge-base row helpers (Q-1c2-1 (a), L:387; L:383) on `block/b1c1`.
  - 2a.1 writes its `base_errors` change (P:889) only after `sd1` has merged `main` containing PR-1c. Its commit waits for PR-1c anyway (E09).
  - The same window covers `tests/test_store.py`. 1c.2 may test its new helpers there (Q-1c2-1 (a)); 2a.1's `base_errors` rows (P:892) are written after the update.
  - Until then 2a.1 works in its other files. The `store.py` and `test_store.py` part takes about 0.5 h after the update, so 2a.1 commits at 7.5, not 7.0 (R2:F-BDr2-3).
  - So both files are A's until PR-1c merges and D's after: one writer at a time.
- **O3 `gates/__main__.py` (2a.3 and A's 1d).**
  - 1d.1 and 1d.2 register their commands (P:726, P:782) until PR-1d merges at 10.25.
  - 2a.3 adds `GATES["claims"]` (P:1124) after `sd1` merges `main` containing PR-1d. 2a.3 runs from 9.0 to 11.0, so this costs only a U inside the task.
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
| 1c.1 | a | PR-1c | M (running) | C `gate_decisions.py`; M `__main__.py`; T | P:561-563 |
| 1c.2 | a | PR-1c | M | C `gate_register.py`; M `__main__.py`, `store.py` (helpers, Q-1c2-1 (a)); T | P:619-621; L:383, L:387 |
| 1c.3 | a | PR-1c | M | C `tools/__init__.py`, `tools/index.py`, 4 schemas; M `__main__.py`, `producers.py`, `.gitignore`, `tests/test_schema_lib.py` (K6, L:383); T | P:667-669 |
| 1d.1 | a | PR-1d | M | C `tools/decisions_cli.py`; M `__main__.py`, `producers.py`; T | P:725-727 |
| 1d.2 | a | PR-1d | M | C `tools/findings_cli.py`; M `__main__.py`, `producers.py`; T | P:781-783 |
| 2a.1 | d | PR-D | L | section 2 row `d` (2a.1 part); records migration by the session (P:1011) | P:884-892 |
| 2a.2 | d | PR-D | M | C `claim.yml`, `claims.py`; M `gitinfo.py`; T | P:1016-1019 |
| 2a.3 | d | PR-D | M | C `gate_claims.py`; M `__main__.py` (O3); T | P:1122-1125 |
| B2.1 | b | PR-B2 | M | C `playbook/rules.md`; T `test_playbook.py` | P:5838-5840 |
| B2.2 | b | PR-B2 | M (+0.5 h for the folded 3d.2 prose) | C five playbook files; M `test_playbook.py`, `prose_check.py` | P:5939-5941; Q-BD-5 (a) |
| B2.3 | b | PR-B2 | M | C `SKILL.md`; T `test_skill.py` | P:6030-6032 |
| 2b.1 | a | PR-2b | M | C `run_all.py`; M `__main__.py`, `tests/test_playbook.py` (FIXED_RULES test, edit E-6); T | P:1180-1183 |
| 2b.2 | a | PR-2b | M | C `tools/githooks.py`; M `__main__.py`, `gitinfo.py`; T | P:1241-1244 |
| 2b.3 | a | PR-2b | M | C workflow; M `.strict-delivery/config.yml`; T `test_self_adoption.py` | P:1331-1334 |
| 2c.1 | a | PR-2c | M | C `tools/claims_cli.py`; M `__main__.py`, `producers.py`, `tools/decisions_cli.py` (`ask --overrides`, Q-BD-1); T `test_claims_cli.py`, `test_decisions_cli.py` | P:1393-1396; P:890 |
| 2c.2 | a | PR-2c | M | P:1442-1450 list (incl. `tests/helpers.py`) | P:1441 |
| 2c.3 | a | PR-2c | L | C `dispatch.py`, `gate_dispatch.py`; M `__main__.py`, `test_playbook_drift.py`; T | P:1513-1516 |
| P1.1-P1.3 | a | PR-P1 | M each | P:1745-1747, P:1812-1814, P:1887-1891 | |
| P2.1, P2.3 | a | PR-P2 | M | P:1962-1965, P:2096-2099 | |
| P2.2 | a | PR-P2 | L | C `program_cli.py`, `lib/breakdown.py`, `schemas/breakdown.yml`; M `__main__.py`, `producers.py`; T | P615:2042-2044 |
| P3.1, P3.3 | a | PR-P3 | M | P:2179-2186, P:2301-2304 | |
| P3.2 | a | PR-P3 | M (+0.5 h for Rq-5-4) | C `cleanup.py`; M `findings.py`, `gitinfo.py` (`last_text`, plus Rq-5-4's `is_ignored`, `first_parent`, `deleted_paths`, `upstream_of`, Q-BD-3, edit E-16); T | P:2247-2250; P:4325-4329 |
| P4.1-P4.3 | a | PR-P4 | M each | P:2360-2363, P:2402-2405, P:2466-2470 (prompt files written by A, B merged first, P:5531) | |

### 3.2 Edges

| # | from | to | kind | source |
|---|---|---|---|---|
| E05 | 1c.1 | 1c.2 | O | shared `__main__.py` `GATES` line on `b1c1` (L:383); 1c.2 also waits for PR-1c0 (section 4) |
| E06 | 1c.3 | 1d.1, 1d.2 | C | `index.regenerate` P:732, P:788 |
| E09 | 1c.1, 1c.2 | 2a.1 | O | Step 5 runs `check decisions` and `check register` before the commit (P:1011); review F-BDr-2; coordinator fact |
| E10 | 2a.1 | 2a.2 | C | `migrations.migrate` P:1026; L:389 |
| E11 | 2a.1 | 2c.2 | C+F | `migrations.*` P:1460; edits `migrations.py` P:1445 |
| E13 | 2a.2 | 2a.3 | C | `claims.*` P:1130 |
| E13b | 1d.1, 1d.2 | 2a.3 (its `__main__.py` commit) | F | O3 |
| E15 | 1c.1, 1c.2, 2a.3 | 2b.1 | C | `__main__.GATES` P:1188; strict tuple P:1214-1216; the real-gates fixture test (R:F-BDr-1, P:1231) |
| E15b | 2a.1, B2.1 | 2b.1 (FIXED_RULES test) | C | edit E-6; P:5582 |
| E17 | 2b.1 | 2b.2 | C | P:1249 |
| E18 | 2b.1, 2b.2, 1c.3 | 2b.3 | C | P:1339 |
| E20 | 2a.2, 2b.2 | 2c.1 | C | P:1401; hook test P:1427 |
| E20b | 1d.1, 2a.1 | 2c.1 (`ask --overrides`) | F+C | P:890, P:914 |
| E12 | 2b.1 | 2c.2 | C | Step 4 runs `run_all` (P:1506); satisfied now that 2c.2 runs in PR-2c (R:F-BDr-3 resolved by Q-BDr-1 (a)) |
| E22 | 2c.2, 2a.2 | 2c.3 | C | `config.load` limits, `claims.load/stale_errors` P:1521 |
| E23 | 2a.1 | 2c.3 | F | `test_playbook_drift.py` P:1515 |
| E27, E28 | B2.1 -> B2.2 -> B2.3 | | C | P:5946, P:6037 |
| E30 | 2c.3 | P1.2 | C | `dispatch.ROLES` P:1819 |
| E31, E32 | P1.1 -> P1.2 -> P1.3 | | C | P:1819, P:1896 |
| E33 | P1.1, P1.3 | P2.1 | C | P:1970 |
| E34 | P2.1 | P2.2, P2.3 | C | P:2048, P:2104 |
| E34b | 2c.3 | P2.2 | C | `dispatch.limits_of` P615:2049 |
| E35 | P1.2, P1.3, P2.3, 2b.2, 2c.2 | P3.1 | C | P:2191 |
| E36, E37 | P3.1 -> P3.2 -> P3.3 | | C | P:2255, P:2309 |
| E38 | P1.2, P2.1, 1d.1 | P4.1 | C | P:2368 |
| E39 | P4.1, 2c.3 | P4.2 | C | P:2410 |
| E38b | 2c.3, P2.1 | P4.3 | C | P:2475 |

The draft's E16 (PR-C2 -> 2b.1) and E40 (PR-B2 -> P4.3) are now notes, not edges. P:1191 and P:5531 make both conditional (R:F-BDr-10). E26, whose end was a test name, is replaced by E15b.

---

## 4. Pre-program PRs, unblock conditions, schedule

The session merges one PR at a time and updates each branch before its merge (P:5560).

| PR | tasks | starts when | merges after (on `main` first) | timeline (h) | merged |
|---|---|---|---|---|---|
| PR-1c0 | 1c0.1 + reviewed docs (6890aff, 615bc21; Q-BD-6) | running | none | U1 fix and re-review to 1.0, then E | **2.5** |
| PR-C2 | (done) | — | PR-1c0 | U and re-run | **3.25** |
| PR-1c | 1c.1, 1c.2, 1c.3 | running; 1c.2 after PR-1c0 (L:387) | PR-1c0 | 1c.1 to 2.0; 1c.3 (group worktree, L:206 precedent) 2.0 to 4.0; 1c.2 2.75 to 4.75; U; E | **6.5** |
| PR-D | 2a.1, 2a.2, 2a.3 | PR-1c0 (L:389) | PR-1c0, PR-1c (E09), PR-1d (O3) | 2a.1 2.75 to 5.75; wait for PR-1c, then U and records, store.py and test_store.py part 0.5 h, commit at 7.5; 2a.2 7.5 to 9.5; 2a.3 9.5 to 11.5 (U for PR-1d inside); U; E | **13.25** |
| PR-B2 | B2.1, B2.2, B2.3 | PR-1c0 | PR-1c0 | B2.1 to 4.5; B2.2 to 7.0; B2.3 to 9.0; U; E | **10.75** (after PR-1d in the merge queue) |
| PR-1d | 1d.1, 1d.2 | PR-1c | PR-1c | 1d.1 \|\| 1d.2 6.5 to 8.5; U; E | **10.25** |
| PR-2b | 2b.1, 2b.2, 2b.3 | PR-D (E15) and PR-B2 (E15b) | PR-D, PR-B2, PR-1c | 13.25 to 19.25; U; E | **21.0** |
| PR-2c | 2c.1, 2c.2, 2c.3 | PR-2b (E12, E20), PR-1d (E20b), PR-D | PR-2b | 2c.1 \|\| 2c.2 21.0 to 23.0; 2c.3 (L) to 26.0; U; E | **27.75** |
| PR-P1 | P1.1-P1.3 | PR-2c (P:1692) | PR-2c | serial 6 h; E | **35.25** |
| PR-P2 | P2.1-P2.3 | PR-P1 | PR-P1 | P2.1 2 h; P2.2 (L) \|\| P2.3 3 h; E | **41.75** |
| PR-P4 | P4.1-P4.3 | PR-P2 (Q-BD-2) | PR-P2 | P4.1 \|\| P4.3 2 h; P4.2 2 h; E | **47.25** |
| PR-P3 | P3.1-P3.3 (+Rq-5-4) | PR-P2 (Q-BD-2) | PR-P2; update after PR-P4 (shared `__main__.py`, `test_self_adoption.py`) | 6.5 h; U; E | **50.0** |
| program setup | program plans (written from about 35 h on, in parallel), `streams.yml`, `breakdown.yml` (Part II), the owner's `program-create` decision, `program create --plan`, worktrees, M1-M10 (P:2559) and M-B4-1 (P:3325) | PR-P1..P4 | — | 2 h | **S = 52.0** |

Notes.
- FIXED_RULES test (F-BD-4). PR-D (13.25) merges after B2's final review (about 9.0-10.75). So by P:5582 the "B2 merges first" branch applies, and A writes the test: in 2b.1, which is A's first task after both PRs are on `main` (edit E-6). B2 does not wait, and its final review is not re-run.
- PR-C2 carries `cites` into `run_all` from the start, because C2 merges before 2b.1 starts (P:1191, P:5574).

**Pre-program waves (cap 25; peak 13):**

| wave | window | agents |
|---|---|---|
| W1 | 0-2.75 | 1c0 fix and end 4; 1c.1 2; 1c.3 2; C2 re-check 1; this revision 1; docs writer 1 = 11 |
| W2 | 2.75-6.5 | 1c.2 2; 2a.1 2; B2.1 and B2.2 2; 1c end 2; PC1 drafters 2 = 10 |
| W3 | 6.5-13.25 | 1d.1, 1d.2 4; 2a.2 or 2a.3 2; B2.3 and B2 end 2; 1d end 2; D end 2; PC1 drafter 1 = 13 |
| W4 | 13.25-21.0 | 2b.x 2; 2b end 2; PC1 drafter 1 = 5 |
| W5 | 21.0-27.75 | 2c.1, 2c.2 4 (then 2c.3 2); 2c end 2 = 6 |
| W6-W8 | 27.75-50.0 | P1 4; P2 6; P3 and P4 with both ends 10; program-plan writer and reviewer 2 = at most 12 |

Antichains (all edges checked): {1c.3, 1c.2, 2a.1, B2.1}, {1d.1, 1d.2, 2a.2, B2.3}, {2c.1, 2c.2}, {P2.2, P2.3}, {P3.1, P4.1, P4.3}.

---

## 5. Pre-program critical path

**PR-1c0 (2.5) -> 1c.2 -> PR-1c (6.5) -> 2a.1 commit (7.5) -> 2a.2 -> 2a.3 -> PR-D (13.25) -> 2b.1, 2b.2, 2b.3 -> PR-2b (21.0) -> 2c.2 -> 2c.3 -> PR-2c (27.75) -> P1 (35.25) -> P2 (41.75) -> P3 (50.0) -> setup (S = 52.0).**

---

## 6. Program record (Part II, the future `breakdown.yml`)

The schema fields `done`, `period`, `residual` and path windows are the additions listed in edits E-12 and E-13. Period events are `program-start`, `merged:<stream>/<sub-block>` (that sub-block's PR read back as merged, from its `MERGED` line), `merged:<stream>` (the stream's last sub-block merge: its last `merged:<stream>/<sub-block>` event; `final=yes` marks the plan's last PR and is not used, F-BDr3-2) and `program-close` (R2:F-BDr2-1; edits E-12, E-21).

```yaml
schema: breakdown/1
plan: 2026-10-31-strict-delivery-framework
max_concurrent: 25
max_depth: 5
done: [1a.1, 1a.2, 1a.3, 1b.1, 1b.2, 1b.3, 1c0.1, 1c.1, 1c.2, 1c.3, 1d.1, 1d.2,
       2a.1, 2a.2, 2a.3, 2b.1, 2b.2, 2b.3, 2c.1, 2c.2, 2c.3,
       P1.1, P1.2, P1.3, P2.1, P2.2, P2.3, P3.1, P3.2, P3.3, P4.1, P4.2, P4.3,
       B1.1, B1.2, B1.3, B2.1, B2.2, B2.3, C1.1, C1.2, C2.1, C2.2]
streams:
  - {id: residual, residual: true, period: {from: program-start, until: program-close},
     tasks: [R1.1, R2.1, R2.2, R2.3, R3.1, R3.2],
     unblock: "R1.1 at program start; R1 PR first (docs needs it); R2.1 after merged:context; R2.2 after merged:docs; R2.3 after merged:evidence; R3.x after merged:context, merged:runtime, merged:tools, merged:bash"}
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
     unblock: "4c after M-B4-1; 4d after merged:cfg4 and merged:package; the Rq-4-2, Rq-4-5, Rq-4-3 commits at the end of 4e.3 after merged:residual/R2 (window start)"}
  - {id: context, period: {from: program-start, until: merged:context}, paths: [P:4366-4489 Files], tasks: [5a.1, 5a.2, 5a.3],
     unblock: "at program start"}
  - {id: docs, period: {from: program-start, until: merged:docs}, paths: [P:4551, P:4608, P:4665, P:4730 Files], tasks: [5b.1, 5b.2, 5c.1, 5c.2],
     unblock: "at program start (Rq-5-4 is on main from P3.2); the 5c end after merged:residual/R1 (Rq-5-5)"}
  - {id: evidence, period: {from: program-start, until: merged:evidence}, paths: [P:4812 row], tasks: [6E.1, 6E.2, 6E.3],
     unblock: "at program start"}
  - {id: checkpoint, period: {from: program-start, until: merged:checkpoint}, paths: [P:4813 row], tasks: [6K.1, 6K.2],
     unblock: "at program start"}
  - {id: release, period: {from: merged:init4, until: program-close}, paths: [P:4814 row incl. the version sites], tasks: [6R.1, 6R.2, 6R.3],
     unblock: "after every other stream and residual R2 and R3 have merged (P:4799); 6R.2 after the stream-ownership decision"}
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
  - {from: 4e.3, to: 6R.1}        # repo_fixtures P:5362
  - {from: 6K.2, to: 6R.1}
  - {from: 6E.2, to: 6R.1}
  - {from: R3.2, to: 6R.1}        # hook behaviour of context (P:5361-5366)
  - {from: 6R.1, to: 6R.2}
  - {from: 6R.2, to: 6R.3}
groups:   # antichains, each within 25 tasks
  - {id: g-start, tasks: [3a.1, 3d.1, 3b.1, 4a.1, 4c.1, 6K.1, 5a.1, R1.1, 6E.1, 6E.3]}
  - {id: g-mid, tasks: [3a.2, 4a.2, 4c.2, 6K.2, 5a.2, 6E.2]}
  - {id: g-hooks, tasks: [3b.2, 3c.1, 3c.2, 4a.3, 5b.1, 5c.1]}
```

`R1.1`..`R3.2` are new plan tasks (edit E-14). They are written here as the record must name them.

### 6.1 Program PRs and unblock conditions

| PR | starts | merges after | timeline (from S = 52.0) | merged |
|---|---|---|---|---|
| PR-residual/R1 (event merged:residual/R1) (R1.1, Rq-5-5 prose) | S | — | S, 1 h, E | S+2.5 |
| PR-package (3d.1, Rq-4-1) | S | Rq-4-1 landed (P:3359) | 2 h + 0.5; E | **S+4** |
| PR-checkpoint | S | — | 4 h; E | S+5.5 |
| PR-runtime | S | — | 3a.1 2 h, 3a.2 3 h; E | S+6.5 |
| PR-context | S | — | 6 h; E | S+7.5 |
| PR-evidence | S+4 (wave cap) | — | (6E.1, 6E.2) \|\| 6E.3, 4 h; group merge 0.5; E | S+10 |
| PR-tools | S+6.75 | PR-runtime, PR-package | 2 h; E | S+10.25 |
| PR-cfg4 | S | PR-package | 4a.1 to S+2; 4a.2 S+4.25 to S+6.25; 4a.3 + decisions.md row 2.5 h to S+8.75; E | **S+10.25** |
| PR-bash | S | PR-runtime, PR-package | 3b.1 to S+2; 3b.2 S+6.75 to S+9.75; 3b.3 to S+11.75; U; E | S+13.5 |
| PR-docs | S+10.25 (wave cap) | PR-residual/R1 (event merged:residual/R1) | two groups of 4 h; 0.5; E | S+16.25 |
| PR-rules4 | S+10.5 | PR-cfg4 | 4 h; E | S+16 |
| PR-residual/R3 (R3.1, R3.2) | S+13.5 | PR-context, -runtime, -tools, -bash | 2 h; E | S+17 |
| PR-residual/R2 (R2.1-R2.3) | S+16.25 | PR-context, -docs, -evidence | 1 h (parallel); E | S+18.75 |
| PR-init4 | S | PR-cfg4, PR-package; registry window after merged:residual/R2 | 4c to S+4, sub-end S+5; 4d from S+10.5: 4d.1 to S+13.5, 4d.2 to S+15.5, 4d.3 to S+17.5, sub-end S+18.5; 4e.1 to S+21.5, 4e.2 to S+23.5, 4e.3 to S+25.5; Rq-4-2, Rq-4-5, Rq-4-3 commits in the window 1 h (order P:3362); U; E | **S+28.25** |
| PR-release | after all of the above | all | 6R.1 to S+30.25; 6R.2 to S+32.25; E to S+33.75; 6R.3 (tag on the owner's word) | **S+34.75** |

### 6.2 Program waves (cap 25; review F-BDr-9)

| wave | window | controllers | tasks | agents |
|---|---|---|---|---|
| PW1a | S to S+2.5 | runtime, package, bash, cfg4, init4, context, residual = 7 | 3a.1, 3d.1, 3b.1, 4a.1, 4c.1, 5a.1, R1.1 or its end = 7 x 2; plus 1 PC1 drafter | **22** |
| PW1b | S+2.5 to S+4 | runtime, package, bash, cfg4, init4, context, checkpoint (starts S+2.5, after residual R1 has merged) = 7; residual idle = 1 | 3d.1 end, 3a.1/3a.2, 3b.1 (or bash idle), 4a.1 (or waiting), 4c.x, 5a.x, 6K.1 = 7 x 2; plus 1 PC1 drafter | **23** |
| PW2 | S+4 to S+6.75 | runtime, bash (idle), cfg4, init4, checkpoint, context, evidence + loopstats group, residual (idle) = 9 | 3a.2, 4a.2, 4c.2 or the 4c end, 6K.1/6K.2, 5a.2, 6E.1, 6E.3 = 7 x 2 | **23** |
| PW3a | S+6.75 to S+10.25 | bash, tools, cfg4, init4, context (ending), evidence + group, residual = 8 | 3b.2, 3c.1, 3c.2, 4a.3, 5a.3 or the 5a end, 6E.2 = 6 x 2 | **20** |
| PW3b | S+10.25 to S+18.75 | bash, rules4, init4, docs + 2 groups, residual = 7 | 3b.3, 4b.x, 4d.x, 5b.x, 5c.x, R2 or R3 = 6 x 2 | **19** |
| PW4 | S+18.75 to S+28.25 | init4 = 1 | 4e.x = 2 | 3 |
| PW5 | S+28.25 to S+34.75 | release = 1 | 6R.x = 2 | 3 |

All waves are at or under the measured 25 and leave at least 2 slots. Launches past the limit are refused, not queued (P:862), so PW1 keeps one slot for a PC1 drafter (R2:F-BDr2-2). Checkpoint starts at S+2.5, half an hour later than the review's S+2: at S+2 residual's R1 end is still running and the wave would reach 25. Checkpoint then merges at S+8, well within its slack.

Docs and evidence start later than the plan allows (P:4299, P:4796) only because of the cap. Their slack is about 6.5 h (R2:F-BDr2-5): init4's request commits start at S+25.5 and need R2 merged; R2 takes about 2.75 h (1 h, U, E); so docs and evidence must merge by about S+22.75, and docs merges at S+16.25.

---

## 7. Critical path and estimate (draft's unit costs)

**PR-1c0 (2.5) -> 1c.2 (L:387 wait) -> PR-1c (6.5) -> 2a.1 commit (E09; 7.5) -> 2a.2 -> 2a.3 -> PR-D (13.25) -> 2b.1-2b.3 -> PR-2b (21.0) -> 2c.2 -> 2c.3 -> PR-2c (27.75) -> P1 (35.25) -> P2 (41.75) -> P3 with Rq-5-4 (50.0) -> setup (52.0) -> 3d.1 / PR-package (S+4) -> 4a.2, 4a.3 / PR-cfg4 (S+10.25) -> 4d.1-4d.3 -> 4e.1-4e.3 and the Rq-4 window / PR-init4 (S+28.25) -> 6R.1, 6R.2, PR-release, 6R.3 (S+34.75) ≈ 86.75 working hours.**

- Against revision 1 (80 h): +6.75 h. The added time comes from the L:387/L:389 waits, E09 (including 0.5 h for the store.py window, R2:F-BDr2-3) and E15, and is offset by Q-BD-8 (a) (no A-R6 PR, −2.25 h) and by folding 3d.2.
- The review's corrected figure was 90.75 h with D's old scope, and 87.25 h under its Q-BDr-1 (a). The review re-checked 86.25 h (review 2); the store.py window adds 0.5 h, giving 86.75 h. The remaining 0.5 h below the review's 87.25 h comes from 1c.3 running alongside 1c.2 in a group worktree. It is my scheduling choice; without it the path is 87.75 h.
- Range: about 54 h if every task takes 1 h; about 118 h if every task takes 3 h. The path also has 15 owner approvals.
