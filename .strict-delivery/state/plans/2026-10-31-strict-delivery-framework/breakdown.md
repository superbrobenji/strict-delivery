# Stream breakdown (2026-11-02): strict-delivery framework, all remaining work

The human schedule for the plan `docs/strict-delivery/plans/2026-10-31-strict-delivery-framework.md`, the last planning step (owner Q-PL-1 (a)). Copied from the reviewed stream-breakdown draft, a git-ignored working file that this record does not cite (sections 1-7; its findings and its edit list are applied to the plan and specs and are not repeated). Owner answers: Q-BDr-1 (a), Q-BD-4 (a), Q-BD-5 (a), Q-BD-7 (a), Q-BD-8 (a), Q-BDr2-1 (a); controller rulings Q-BD-1, Q-BD-2, Q-BD-3, Q-BD-6 and the `done` field under Q-BD-7 (a). Not a checked record: section 6 is the content of the future `breakdown.yml` (`breakdown/1`), written before `program create`.


**Revision 7 (2026-11-17, process v2).** Revision 7 applies the owner-approved delivery-process design (`docs/strict-delivery/specs/2026-11-17-delivery-process-changes-design.md`, cited "PV2"; owner "approved, roll it in", L:869) and re-bases the remaining schedule to t = 0 = 2026-11-17 14:00 SAST, the roll-in. What changed, and why:
1. **Commit gate (PV2:5.1).** A commit runs the touched-area tests, the enabled gate checks and a clean tree, not the full suite. The task classes S, M and L are kept as they were (conservative: no task hour is cut); the one full suite per PR runs on the PR head and sits inside R.
2. **One verifier per stream (PV2:5.2).** The adversarial verifier runs once per stream, at its end (V), over everything the stream delivered; it leaves every PR end. R keeps its revision 6 figures (conservative), and each stream gets V = 1.0 h plus 0.5 h for the review of its fix diffs. The pending verifiers of PR-unicode, PR-2b1, PR-2b-rest and PR-2c3 become the one verifier at stream a's end (PV2 section 7).
3. **Merge on demand (PV2:5.2; roll-in plan D7).** A block opens its own PR only when a task of another stream consumes it (an edge of sections 3.2 or 6, or a `Consumes:` line); every other block rides its stream's final PR; in the program each consumed sub-block opens its own PR (section 6.1). Sections 4 and 6.1 mark each PR row "on demand (consumer: X)" or "stream final PR".
4. **No owner leave rounds (PV2:5.4, 5.6, 5.7).** The binding Rules N and T verdict ends each fix loop, an owner question blocks only the work that depends on it, and a usage-limit stop is checkpointed and resumed. Owner latency stays modelled as 0 h, as in revision 6. Wall-clock time depends on the owner's answers to owner-only questions and on usage limits (PV2:5.6, 5.7), which this schedule does not model.
5. **State at t = 0** is read from the program ledger and the stream a log (section 4, "State at t = 0"). PR-docs6 has merged (#16), PR-tests is folded into stream a's final PR, and Task F1b and PR-loopstats are new rows.
6. **Result.** The critical path is about 60.0 h from t = 0 (sections 5 and 7; the roadmap to v0.1.0 is in section 7). Stream a is 3.0 h further along than revision 6's schedule (PR-P3 at 33.0 h from t = 0, was 36.0 h from revision 6's t = 0), and the one stream-end verifier that sits on the path (`release`; `config`'s runs after PR-config, beside `release`) adds 1.5 h, so the total is 1.5 h under revision 6's 61.5 h. Revision 6 tables and paragraphs stay below, marked "history"; the revision 7 tables are marked "revision 7".

The last planning step (owner directive and Q-PL-1 (a), 2026-11-02, L:381-382). Revision 6 (2026-11-14) applies the owner's answers of 2026-11-10 and 2026-11-14 and re-bases the remaining schedule to t = 0 at PR-1d2's merge (#11, 2ab84d6, L:807; main now 81f9027, L:812): (1) a clean update from `main` after the final review re-runs only the gates (Q-SPD-4 (a), plan and breakdown for now; line U of section 1; L:795); (2) the program's 17 PRs are folded into 7 (section 6; Q-SPD-1 (a), Q-SPD-2 (a); L:795) and sub-block 4a is split (Q-SPD-3 (a); L:795); (3) Task 2c.3 is pulled forward: PR-2b1, then PR-2c3 beside PR-2b-rest, PR-2c1 after them (L:797); (4) Q-PLP-1 (a) (stream a's files open to program streams by per-file windows and two hunk-scoped files), Q-PLP-3 (a) (P1.1 and P1.2 start at PR-2c3, P1.3 after PR-2c1), Q-PLP-4 (a) (the plugin is enabled after PR-hooks; PR-residual/R5 is the first merge after the enablement, amending Q-BRV-3 (a)) and Q-PLP-5 (a) (Task 2c.3 adds `gitinfo.is_ancestor`) (L:800); (5) the program's early tasks start now (owner 2026-11-14 "work full width", L:814, which supersedes "wait for PR-2c3", L:797 and L:800); (6) tasks 1u.1 (F1) and 1u.2 (U1) (PR-unicode) and the test-only PR are added to stream a (L:803-804), off the critical path, as is the revision-6 docs PR; the critical path is about 61.5 h from t = 0 (section 7). E15b no longer binds: stream b wrote the FIXED_RULES test and it merged in PR-B2 (#12, 0ec38e6; the test is 0d92a39; L:802, L:805). Revision 2 applies the review `stream-breakdown-review.md` (F-BDr-1..12) and the owner answers and controller rulings of L:393. Revision 5 (2026-11-08) applies owner answers Q-DOCS-1 (e), Q-RD8b-1 (a), Q-RD8b-2 (b) and Q-RD8c-1 (b): Task 1c0.2 and the docs-only PR's final review and verifier run before PR-1c0 merges, on a branch cut from `block/b1c`'s head, and after PR-1c0 only the docs-only PR's tail remains (cut from `main`, cherry-pick, gates (U), then the rest of its end: approval, merge, read-back, post-merge gates, `MERGED` line; 3.75); every stream (`b`, `c`, `d`) and Task 1c.2 start after it; of the tied shortest queue orders the one with PR-C2 earliest is kept; Task P2.1 is L + 1 h (4 h) (section 4; +2.25 h, S = 56.0, 93.0 h). Revision 4 (2026-11-08) applies owner answers Q-F80RR3-3 (a) (Task P2.1 class L, +1.0 h from PR-P2 on) and Q-F80W-13 (a) (the release `stream-ownership` decision before `program create`), and the branch cuts that Q-F80W-12 (a) requires (section 6.2). Revision 3 (2026-11-07) applies the session-resume plan revision (P078:7536, P078:7538; owner approval L:500; Q-RCp-2 (a), L:515; Q-PLG-1 (a), L:545), the rulings L:541 and L:551, owner answer Q-BRV-1 (a) (the interim-skill removal is Task R5.1 in residual sub-block R5 with its own PR), docs review finding F-DR-6 and its reviews; its edits are applied to the plan and to this file (L:561).

**Two artefacts, by owner answer Q-BD-7 (a) and review F-BDr-8.** `program create --plan 2026-10-31-strict-delivery-framework` checks one `breakdown.yml` against this plan and against `streams.yml` (P615:2054-2060). At that moment every pre-program task (1c..P4, B2, C2, D) is done. So:
- **Part I, the pre-program schedule (sections 2-5):** the session's working schedule from now to the programs block's last PR. It is not a checked record. P2.2's checker does not exist yet, and the session coordinates these streams by hand (P:5517).
- **Part II, the program record (section 6):** the `breakdown/1` content committed before `program create`. Every pre-program task is in `done`; the streams are exactly the program's (including `residual`, Q-BD-4 (a)); and ownership that moves during the program is written with `period` (Q-BD-7 (a)). Its schema additions are listed under "Plan and spec edits".

**Citation keys.**
- `P:<n>`: the plan at `5283c51`.
- `P615:<n>`: the plan at `615bc21`, the head of `block/b1c` (used for text that changed after 5283c51: the breakdown schema, 3d.2's heading, Block 6's Rules N/T note).
- `P078:<n>`: the plan at `0783046`, the head of `block/docs-resume` (used for the nodes, edges and text of the session-resume revision, revision 3; P078:7536-7538). `P:<n>` keeps its `5283c51` pin. Task R5.1, which the plan gains with revision 3 (owner answer Q-BRV-1 (a)), is cited by its task id.
- `P81:<n>`: the plan at `81f9027`, main after PR-1d2, PR-B2, #13 and #14 (used for revision 6; it differs from the plan at `87f5e43` only after its line 6602, `git diff -U0 87f5e43 81f9027`). The plan is revised in parallel with this revision; its new revision-6 text is cited by section name (for example plan section "Program grouping for v0.1"), never by a line number.
- `L:<n>`: the working copy of the ledger (`.strict-delivery/state/plans/2026-10-31-strict-delivery-framework/ledger.md`).
- `R:F-BDr-n`: the review.
- Revision 7 keys. `PV2:<section>`: the design `docs/strict-delivery/specs/2026-11-17-delivery-process-changes-design.md`. `P7:<n>`: the plan at `abee8f6` (main after #20; `grep -n "Consumes:"` gives the lines cited). `L:<n>` in revision 7 text is line n of `git show origin/block/docs-resume:.strict-delivery/state/plans/2026-10-31-strict-delivery-framework/ledger.md` (871 lines at t = 0; the same file as the working copy of the older citations). `SL:<n>` is line n of the stream a log, and `EL:<n>` line n of the evidence stream log, both in `.superpowers/sdd/2026-10-31-strict-delivery-framework/` (untracked; `stream-a6-log.md`, `stream-evidence-log.md`).

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

## 1. Units

### Revision 7 units (2026-11-17, process v2; used by the revision 7 tables of sections 4 to 7)

- **Task classes S 1 h, M 2 h, L 3 h, unchanged and kept on purpose.** The touched-area commit gate (PV2:5.1) removes the full suite from each commit, so a task could take less than its class; no estimate is cut (conservative). The L tasks and P2.1 (4 h) are as in revision 6.
- **U 0.25 h**: update from `main`, only if something merged after the PR's cut. The clean update of revision 6 is kept (plan Process "Update from `main` and the clean update"; PV2 changes nothing there): a PR whose R finishes before its predecessor merges takes U + T = 0.75 h after that merge; otherwise its U comes before R.
- **R: final review with one full suite on the PR head, 1.0 h** (PV2:5.1, 5.2: touched-area tests, one full suite on the PR head, the `final_reviewer` review). Revision 6's larger R is kept for the PRs that carry more sub-blocks, earlier sub-blocks of their stream included (section 6.1): hooks 1.25 h, records 1.5 h, config 2.0 h; a PR that carries one sub-block, or only V's fixes, has R 1.0 h. There is no verifier in a PR end any more; R keeps its figure although the verifier hour left it (conservative).
- **T 0.5 h**: the owner's approval, the merge, the read-back, the post-merge gates and the `MERGED` line.
- **PR end** = U + R + T = 1.75 h (1.5 h with no U; 0.75 h after the predecessor's merge when R was already done).
- **V 1.0 h plus 0.5 h** (1.5 h), once per stream, at the stream's end (PV2:5.2): the verifier's run, which holds the stream-end full suite (PV2:5.1), and the review of its fix diffs. It runs after the stream's last block (after that block's merge when it merged on demand); no on-demand PR waits for it, and its fixes go in the stream's final PR or, when every block already merged on demand, in a small follow-up PR (opened only if V finds a defect), which is then the final PR. Stream a's V covers everything stream a delivered: PR-unicode, PR-2b1, PR-2b-rest, PR-2c3, PR-2c1, PR-P1, PR-P2, PR-P4, PR-P3 and what rides the final PR (1t.1, F1b). A defect it finds in merged code is fixed in the stream's final PR, which consumer streams take by their next update (PV2:5.2).
- **Sub-block end without a PR: 1.0 h**, kept from revision 6 (conservative). **H1 0.5 h** (the block-end procedure of Task 2b.3 under the runner's lock, SL:19). **Sweep 0.5 h** (PR-2c3's literal sweep 0.25 h as in revision 6, plus 0.25 h for the finding-class removal that the config/2 rewrite keeps, L:870, SL:30). **Cut 0.25 h**: a branch cut or update after a merge it waits for, as in revision 6 (for example PR-2b1 at 3.0, work from 3.25).
- **Owner latency 0 h**: there are no owner leave rounds (PV2:5.4: the binding verdict ends each loop; PV2:5.6: only dependent work waits). Wall-clock time depends on the owner's answers to owner-only questions and on usage limits (PV2:5.6, 5.7); this schedule does not model either.
- **Caps.** Concurrency 25 (section 6.2); per-stream child cap 4 (L:866), checked in section 6.2. Agent count: 1 per stream controller and per group sub-controller, 2 per active task, end, R, T and V.
- **t = 0** is 2026-11-17 14:00 SAST (the roll-in). **Calendar readings** of an h figure, both stated in section 7: 24 h per day (t = 0 plus h hours) and 8 working hours per day (Monday to Friday, 09:00 to 17:00 SAST; the 3 h left of 2026-11-17 count first).

### Revision 6 units (history; unchanged from revision 1 apart from the notes)

- Task classes:
  - S: 1 h.
  - M: 2 h.
  - L: 3 h. The L tasks are 2a.1, 2c.3, P2.1 (L + 1 h: 4 h, outside the classes; class L by owner answer Q-F80RR3-3 (a), plus 1 h for the event order and `residual_reachable` that owner answer Q-RD8-1 (a) moves into it, owner answer Q-RD8b-2 (b)), P2.2, 3a.2, 3b.2, 4d.1 and 4e.1.
- E (block or stream PR end: final review, verifier, owner approval, merge, read-back, post-merge gates, MERGED line): 1.5 h. The docs-only PR's tail after PR-1c0 (owner answer Q-RD8c-1 (b)): U (0.25 h), then the rest of its end after its earlier final review and verifier (the owner's approval of the head, merge, read-back, post-merge gates, `MERGED` line), taken as 1.0 h: 1.25 h.
- A sub-block end without a PR: 1 h.
- U (update from `main` before a merge, P:5560): 0.25 h. The update comes before the final review (P078:6251, "At the update from `main` before the final review"), the full commit gate re-runs on that head (P:5560), and the owner approves the reviewed head (P078:5314). So a PR's E follows its last U, and an update after another PR's merge restarts the E (U + E = 1.75 h; revision 3), unless it is clean (revision 6, owner 2026-11-10, schedule cut 1; plan Process "Update from `main` and the clean update"): a clean U after the final review re-runs only the gates, so the PR then needs only the rest of its end, and a queued PR merges U + T = 0.75 h after the merge before it. E = R + T: R (final review and verifier) 1.0 h for a PR of at most three sub-blocks plus 0.25 h for each further sub-block; T (merge under the owner's grant, read-back, post-merge gates, `MERGED` line) 0.5 h.
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

**Revision 6: stream a's ownership opens to program streams (owner answer Q-PLP-1 (a), L:800; owner "work full width", L:814).** Program tasks start before stream a's last pre-program writer of some of their paths has merged, and stream `a` owns every path not listed for `b`, `c` or `d` in the same window (P:5527). Under Q-PLP-1 (a) there are two kinds of window. (1) File windows open at the merge of stream a's last pre-program writer of each path, in the table below. (2) Hunk-scoped windows in two shared files, open from the first program task that writes them while stream a still writes the rest of the file: `package` may write only `COMMANDS["hook"]` in `gates/__main__.py` and `run_all.version` (the function, its call and its tests in `tests/test_run_all.py`); `config` may add only new test methods in `tests/test_config.py`. Whoever merges second resolves textual conflicts in its own hunks at its update before review, and the controller's hand check before each merge lists every shared-file hunk with its owner. (L:800 words the hunk-scoped windows as "named hunks in __main__.py and config.yml"; the option's own text above names `tests/test_config.py`, not `config.yml`; the two wordings differ and are reported, not resolved.) Until the programs tool is registered (after PR-P3), these windows are checked by hand, and they are not in the section 6 record, whose `paths` hold the whole-file windows from `program-start`.

| path(s) | program task(s) | pre-program last writer | window |
|---|---|---|---|
| `gates/__main__.py`, `gates/producers.py`, `gates/run_all.py`, `tests/test_run_all.py` | 3d.1 (registry lines), later the config Rq commits (Q-SPD-2 (a)) | 2b.1 through P3.3 and P4.2 (P81:1497, 1559, 1722, 1876, 2330, 2539, 2630, 2828, 2887, 2932) | hunk-scoped (`COMMANDS["hook"]`, `run_all.version` and its tests) for `package` from PR-2b1; whole files to `package`, then `config`, from PR-P3 |
| `tests/test_config.py` | 4a.2, 4a.3 | P3.1 (P81:2721) | new test methods only, hunk-scoped; whole file to `config` from PR-P3 |
| `gates/lib/config.py` | 4a.2, 4a.3 | 2c.2 (and 1d2) | `config` from PR-2c3 |
| `gates/lib/schema.py`, `gates/gate_schema.py`, `tests/test_schema_lib.py`, `tests/test_gate_schema.py` | 4a.1 | P2.1 (P81:2421) | `config` from PR-P2 |
| `skills/strict-delivery/SKILL.md`, `tests/test_skill.py`, `playbook/decisions.md` | 4a.3 | 2c.3 (P81:1878); stream b until PR-B2 | `config` from PR-2c3 |
| `gates/gate_decisions.py`, `tests/test_gate_decisions.py` | 4b.1 | none pending | `config` from launch |
| `gates/lib/dispatch.py`, `gates/gate_dispatch.py`, `tests/test_dispatch_lib.py`, `tests/test_gate_dispatch.py` | 4b.2, R4.1 | P4.3 (P81:2997) | `config` from PR-P4 |
| `gates/lib/checkpoints.py`, `tests/test_checkpoints_lib.py` | 6K.1 | P1.2 (creates) | `records` from PR-P1 |
| `gates/gate_checkpoint.py`, `tests/test_gate_checkpoint.py` | 6K.2 | P3.1 (P81:2716-2721) | `records` from PR-P3 |
| `gates/tools/index.py`, `gates/schemas/overview.yml`, `tests/test_index.py` | 5b.1 | none pending | `records` from launch (used after PR-P3) |
| `gates/lib/gitinfo.py`, `gates/tools/githooks.py` | 3b.2 | P3.1, P3.2 | `hooks` from PR-P3 (3b.2 does those edits last) |
| `skills/strict-delivery/prompts/program_controller.md`, `tests/test_prompt_blocks.py`, `tests/prose_check.py` | R1.1 | P4.3 (P81:2999) | `records` from PR-P4 |
| `CLAUDE.md`, `.gitignore` | 4e.3 (Rq-4-5) | none pending | `config` from PR-P3 (Q-SPD-2 (a) said "from program start"; there is no writer either way) |
| the plan file | the revision-6 docs edit and the reorder route-ins | PR-B2 | the revision-6 docs PR, cut after PR-B2 merged and merged before the first program PR (PR-package, 7.25 h) |
| every other path | | | `a` until PR-P3 merges; then the program's `residual` |

The early starters (3a.1, 3b.1, 4c.1, 4c.2) create only new files (plan Tasks 3a.1, 3b.1, 4c.1, 4c.2 Files), so they need no window.

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
| 1d3.1 | a | PR-1d3 | set by its planning round | M `result.py`, `gitinfo.py`, `store.py` (expected) | plan Task 1d3.1 (owner DN-3 (b)); registered findings, not yet planned; its planning round sets its estimate and its place in the schedule; not in sections 4-5 until then, so no figure of this breakdown changes |
| 2a.1 | d | PR-D | L | section 2 row `d` (2a.1 part); records migration by the session (P:1011) | P:884-892 |
| 2a.2 | d | PR-D | M | C `claim.yml`, `claims.py`; M `gitinfo.py`; T | P:1016-1019 |
| 2a.3 | d | PR-D | M | C `gate_claims.py`; M `__main__.py` (O3); T | P:1122-1125 |
| B2.1 | b | PR-B2 | M | C `playbook/rules.md`; T `test_playbook.py` | P:5838-5840 |
| B2.2 | b | PR-B2 | M (+0.5 h for the folded 3d.2 prose) | C five playbook files; M `test_playbook.py`, `prose_check.py` | P:5939-5941; Q-BD-5 (a) |
| B2.3 | b | PR-B2 | M | C `SKILL.md`; M `prompts/controller.md`, two paragraphs of nine worker prompt blocks, `tests/test_prompt_blocks.py` (phrase pins); T `test_skill.py`, `test_prompt_blocks.py` | P:6030-6032; P078:6775-6777 |
| 2b.1 | a | PR-2b1 (revision 6, L:797) | M | C `run_all.py`; M `__main__.py`, `tests/test_playbook.py` (FIXED_RULES test, plan stream rules "Cross-stream order"; revision 6: stream b wrote that test in PR-B2, L:802, so it is no longer 2b.1's work); T | P:1180-1183 |
| 2b.2 | a | PR-2b-rest (revision 6, L:797) | M | C `tools/githooks.py`; M `__main__.py`, `gitinfo.py`; T | P:1241-1244 |
| 2b.3 | a | PR-2b-rest (revision 6, L:797) | M | C workflow; M `.strict-delivery/config.yml`; T `test_self_adoption.py` | P:1331-1334 |
| 2c.1 | a | PR-2c1 (revision 6, L:797) | M | C `tools/claims_cli.py`; M `__main__.py`, `producers.py`, `tools/decisions_cli.py` (`ask --overrides`, Q-BD-1); T `test_claims_cli.py`, `test_decisions_cli.py` | P:1393-1396; P:890 |
| 2c.2 | a | PR-2c3 (revision 6, L:797) | M | P:1442-1450 list (incl. `tests/helpers.py`) | P:1441 |
| 2c.3 | a | PR-2c3 (revision 6, L:797) | L | C `dispatch.py`, `gate_dispatch.py`; M `__main__.py`, `test_playbook_drift.py`, and (Q-PLP-5 (a), L:800) `gates/lib/gitinfo.py` (additive `is_ancestor`, which P1.3's Files drop), `tests/test_gitinfo.py`; T | P:1513-1516 |
| P1.1-P1.3 | a | PR-P1 | M each | P:1745-1747, P:1812-1814, P:1887-1891 | |
| P2.1, P2.3 | a | PR-P2 | P2.1 L + 1 h (4 h, owner answer Q-RD8b-2 (b): the event order and `residual_reachable` of owner answer Q-RD8-1 (a); class L by owner answer Q-F80RR3-3 (a): it also builds `merge.merged_errors` and the gitinfo `changed_paths`, `rev_list` and `parents`, owner answer Q-F80W-21 (a)), P2.3 M | P:1962-1965, P:2096-2099; P2.1 also `gates/lib/merge.py`, `gates/schemas/merged-log.yml`, `gates/lib/gitinfo.py`, `gates/lib/schema.py`, `tests/test_merge_lib.py`, `tests/test_gitinfo.py`, `tests/test_schema_lib.py` (plan Task P2.1 Files) | |
| P2.2 | a | PR-P2 | L | C `program_cli.py`, `lib/breakdown.py`, `schemas/breakdown.yml`; M `__main__.py`, `producers.py`; T | P615:2042-2044 |
| P3.1, P3.3 | a | PR-P3 | M | P:2179-2186 (`merge.py` exists from P2.1, plan Task P3.1 Files), P:2301-2304 | |
| P3.2 | a | PR-P3 | M (+0.5 h for Rq-5-4) | C `cleanup.py`; M `findings.py`, `gitinfo.py` (`last_text`, plus Rq-5-4's `is_ignored`, `first_parent`, `deleted_paths`, `upstream_of`, Q-BD-3; plan Task P3.2 Files); T | P:2247-2250; P:4325-4329 |
| P4.1-P4.3 | a | PR-P4 | M each | P:2360-2363, P:2402-2405, P:2466-2470 (prompt files written by A, B merged first, P:5531) | |
| 1u.1 (F1) | a | PR-unicode (group G3, revision 6) | small (class not stated, L:803) | M `gates/lib/result.py` (the argparse invalid-choice text, which differs by interpreter); T `tests/test_result.py` or a new `tests/test_argparse_text.py`; not `gates/run_all.py`, `gates/__main__.py`, `tests/test_run_all.py` (group G0) and not 1u.2's files | L:801 (the finding F1, in `gates/lib/result.py` at lines 97-100 of its argparse handling); L:803 (new small task in stream a); L:808, L:813 (in progress, re-dispatched 2026-11-14) |
| 1u.2 (U1) | a | PR-unicode (group G3, revision 6) | small (class not stated, L:804) | C `gates/lib/fold_table.py`, `tests/test_fold_table.py`; M `gates/lib/decisions.py`, `tests/test_decisions_lib.py`, `tests/test_decisions_cli.py` (the frozen fold table; P2.1 Create -> Consume) | `git show --stat 3555d92`; L:804; done at 3555d92 on `block/a-unicode` (L:813) |
| 1t.1 | a | PR-tests (the test-only PR, revision 6; the plan's Task 1t.1) | small (class not stated, L:803) | T only: cheaper fixtures and the midnight-UTC flaky fix at `tests/test_findings_cli.py:86`, `tests/test_decisions_cli.py:146-147`, `:596`, `:615`, `:631`; no top-level cache (Q-1a-fin-1 kept) | L:803: added, after PR-2c3 |

Ids of the three revision-6 tasks. Decision (owner delegation 2026-11-09): the tasks take the plan's ids, 1u.1 (the plan's Task 1u.1 (F1)), 1u.2 (Task 1u.2 (U1)) and 1t.1 (Task 1t.1), not the bare F1 and U1 or a provisional id -- P2.2's `breakdown_errors` refuses a task id without `.`, and a record id with no task heading in the plan fails at registration -- cost if wrong: an id renamed in this record and in the plan before registration, text only. The ledger's names F1 and U1 (L:801, L:803, L:804) stay in parentheses beside the ids.

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
| E15b | 2a.1, B2.1 | 2b.1 (FIXED_RULES test) | C | plan stream rules "Cross-stream order"; P:5582. **Moot since revision 6 (L:802; the merge is L:805): stream b wrote the test and it merged in PR-B2 (0d92a39 in #12, 0ec38e6); it binds nothing.** |
| E17 | 2b.1 | 2b.2 | C | P:1249 |
| E18 | 2b.1, 2b.2, 1c.3 | 2b.3 | C | P:1339 |
| E20 | 2a.2, 2b.2 | 2c.1 | C | P:1401; hook test P:1427 |
| E20b | 1d.1, 2a.1 | 2c.1 (`ask --overrides`) | F+C | P:890, P:914 |
| E20c | 2a.1 | 2c.1 (`ask --recommend`, `--source`) | C | `decision/2` `recommended` and `source` rules (P078:1148, P078:1703) |
| E12 | 2b.1 | 2c.2 | C | Step 4 runs `run_all` (P:1506); satisfied now that 2c.2 runs in PR-2c (R:F-BDr-3 resolved by Q-BDr-1 (a)) |
| E22 | 2c.2, 2a.2 | 2c.3 | C | `config.load` limits, `claims.load/stale_errors` P:1521 |
| E23 | 2a.1 | 2c.3 | F | `test_playbook_drift.py` P:1515 |
| E27, E28 | B2.1 -> B2.2 -> B2.3 | | C | P:5946, P:6037 |
| E30 | 2c.3 | P1.2 | C | `dispatch.ROLES` P:1819. Revision 6 (Q-PLP-3 (a), L:800): P1.1 and P1.2 start at PR-2c3's merge (merge wait in section 4); they share no file with 2c.1 |
| E30b | 2c.1 | P1.3 | O | revision 6 (Q-PLP-3 (a), L:800): P1.3 starts after PR-2c1 merged, because both write `gates/__main__.py` and `gates/producers.py` (P81:2330, P81:1722); P1.3's Files drop `gitinfo.is_ancestor` (Q-PLP-5 (a), L:800) |
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

**Revision 6 order notes: the groups of the 2c.3 pull-forward (L:797).** After PR-B2, Task 2b.1 alone is PR-2b1. Once PR-2b1 and PR-1d2 are on main, group X (Tasks 2c.2 -> 2c.3, PR-2c3) and group Y (Tasks 2b.2 -> 2b.3, PR-2b-rest) run in parallel, and Task 2c.1 (PR-2c1) follows them (E20). 2c.2's Step 4 needs only 2b.1's `run_all` (E12; P81:1867), so X does not wait for Y.
- The groups' files are not disjoint. Shared: `gates/__main__.py` (2c.3 `GATES["dispatch"]`, P81:1876; 2b.2 `COMMANDS["githook"]` and `COMMANDS["githooks"]`, P81:1559); `.strict-delivery/config.yml` (2c.2 tag `config/2` and `reviews.small.exclude`, P81:1789; 2b.3 `commands.test` and `top_tier_roles`, P81:1660); `gates/lib/gitinfo.py` (2b.2 `unstaged_paths` and `hooks_dir`, P81:1559; 2c.3 `is_ancestor`, Q-PLP-5 (a)). Possibly shared: 2b's new tests `tests/test_githooks.py` and `tests/test_self_adoption.py`, because 2c.2 rewrites every `config/1` literal left in stream a's tests (P81:1792); unverified until those tests exist. All are stream a's own paths, so no other stream edits them.
- Order. Decision (owner delegation 2026-11-09): X and Y stay parallel; PR-2b-rest merges first; PR-2c3 takes its update from `main` before its final review and runs 2c.2's literal sweep as a commit after that update (0.25 h, in the 10.75 h of section 4) -- this keeps both groups parallel at no ownership cost and the sweep then covers 2b's new tests -- cost if wrong: a conflict or a red result at that update, 0.25-1 h before PR-2c3's review, on the critical path.
- Two plan sentences presume the old order and are route-in edits of the revision-6 docs PR: P81:1792 ("Task 2c.2 runs in A's sub-block 2c after 2b's pull request, so Step 4's `run_all` holds as written") and P81:1718 (Task 2c.1, "Runs after 2b's pull request has merged"; it still holds if read as PR-2b-rest).

---

## 4. Pre-program PRs, unblock conditions, schedule

The session merges one PR at a time and updates each branch before its merge (P:5560).

### Revision 7: state at t = 0 (2026-11-17 14:00 SAST)

Each fact cites a ledger line (L), a log line (SL, EL; keys at the top of this file) or the command that shows it.

| fact at t = 0 | source |
|---|---|
| `main` is `abee8f6` (#20, docs/reg8); PR-1d2 was #11; #12-#16 and #18-#20 have merged, #17 is open | `git log --first-parent --merges --oneline origin/main \| head` (#20, #19, #18, #16, #15, #14, #13, #11, ...) |
| Observed 15 minutes after t = 0: PR-unicode merged as #21 at 14:14:58 SAST (`8b952dd`), 1.25 h before this schedule has it (1.5 h). The schedule keeps the t = 0 state the roll-in fixed; counting #21 at 0.25 moves every chain figure from PR-2b1 on 1.25 h earlier (60.0 h becomes 58.75 h). | `gh pr list --state all --limit 1`; `git log --first-parent -1 origin/main` |
| PR-2b1 = #17 (Task 2b.1) is open, head `41cff11`; its final review and its verifier are done at that head (DONE_WITH_FINDINGS, LOW only); it was held for PR-unicode (owner answer Q-A2-1 (a)) | `gh pr view 17 --json headRefOid,state`; L:821; L:827 |
| PR-unicode (1u.1, 1u.2): `block/a-unicode` head `261be3f` holds F1 round 5 (merge `261be3f`); F1 review 4 ended in the ESCALATE verdict (3 MEDIUM, 2 LOW registered against a named follow-up F1b); the final review was dispatched 13:56 and the one full suite on the head ran 2410 OK on both interpreters; the branch took `abee8f6` at 11:35, so no U. Owner Q-G3-F1R3-1 (a) (allowlist) | SL:15, SL:28, SL:29, SL:31; L:847 |
| PR-2b-rest (2b.2, 2b.3): `block/b2b-rest` `c66451a`, CI four cells green (run 44047777537); the 2b.2 re-review 3 and the 2b.3 review 1 are done (11:40, 11:54); left: the block-end full suite and H1 on the head after #17 merges, the final review, the PR | L:865; SL:16, SL:17, SL:19 |
| PR-2c3 (2c.2, 2c.3): `block/b2c3` `ae7f56e`, both task loops LOW_PLATEAU; the final review is held until #17 and PR-2b-rest are on `main`; then the update, the literal sweep, and the finding-class removal (config.py:39) that the config/2 rewrite keeps | L:824; SL:12; L:870; SL:30 |
| Hooks Task 3b.1 is merged into `20261110-v01/hooks/main` (`3194b4f`); runtime Task 3a.1 is done (`cefb955` = `20261110-v01/runtime/main`) | L:868; L:818 |
| Task 6E.3 (loopstats) is dispatched on `20261110-v01/evidence/loopstats`; its implementer is done at `1e0aa22` (modelled as a class M task from t = 0, as dispatched); the `escape_cost` part waits for config/2 (PR-2c3); Rq-6-1 is routed to stream a | L:869, L:871; EL:15; `git log -1 origin/20261110-v01/evidence/loopstats` |
| Config 4c is not started: Task 4c.1 waits for measurement M-B4-1, which needs this checkout installed as a plugin, and `plugin.json` arrives with Task 3d.1; no `config` branch exists | L:837; L:814; `git branch -a --list '*config*'` (empty) |
| Per-stream child cap 4 (was 2); the docs roll-in (groups A-F, branch `docs/process-v2`) is in flight with another controller | L:866; L:869 |

Divergence reported, not resolved. The roll-in brief and L:865 list "an opus re-review of ec7a8f6" and "2b.3 review 1" as left for PR-2b-rest; SL:16 and SL:17 show both done. The figures do not depend on which is right: both reviews are at most 1.0 h and PR-2b-rest's own work starts only after PR-2b1 merges at 3.25 h.

### Revision 7 per-PR table (h from t = 0; each cell shows its sum)

Rule for each merge time: a PR whose tasks and V finish after its predecessor's merge costs U + R + T; a PR whose R finishes first costs U + T = 0.75 h after the predecessor's merge (section 1). "Cut" is the 0.25 h of a branch update after a merge. All units are the revision 7 units of section 1.

| PR | tasks | mark | timeline (sum -> h from t = 0) | merged at |
|---|---|---|---|---|
| PR-unicode (#21) | 1u.1 (F1), 1u.2 (U1) | merged (owner order Q-A2-1 (a), L:827: merges before PR-2b1); not on demand by D7 (same stream), kept as it is (PV2 section 7) | R in flight 1.0 + T 0.5 = 1.5 -> 1.5 (no U, SL:15) | merged as #21 (`8b952dd`, 2026-11-17 14:14, observed; the schedule keeps its figure, t = 0 does not move): **1.5** |
| PR-2b1 (#17) | 2b.1 | on demand (consumer: `package` Task 3d.1, whose Consumes line names `run_all.check`, P7:3945; PR-2b-rest and PR-2c3 are stacked on it, L:822) | after PR-unicode 1.5: U 0.25 + R 1.0 + T 0.5 = 1.75 -> 3.25. Not a clean update: PR-unicode's diff changes `gates/lib/result.py` (`git diff --name-only origin/main...origin/block/a-unicode`), which Task 2b.1's Consumes line names (P7:1654: `result.run_check/Result/GateError/gate_args`), so plan:41 condition (3) fails and the final review runs again | merged as #17 (`412de25`, 2026-11-17 15:16, observed; the schedule keeps its figure, t = 0 does not move): **3.25** |
| PR-loopstats | 6E.3 (core) | on demand (consumer: `config` R2.3 and R4.1, edges 6E.3 -> R2.3 and 6E.3 -> R4.1; and every controller's Rules N and T, PV2:5.4) | 6E.3 (M) 0 + 2.0 = 2.0; after PR-2c3 7.75: U 0.25 + R 1.0 + T 0.5 = 1.75 -> 9.5 (not clean: Task 6E.3 consumes `config.load`, P7:5819, and PR-2c3 changes `config.py`) | merged as #22 (`a128a39`, 2026-11-17, observed; the schedule keeps its figure, t = 0 does not move): **9.5** |
| PR-2b-rest | 2b.2, 2b.3 | on demand (consumers: `hooks` Tasks 3b.2 and 3b.3, P7:3610, P7:3726; `config` Tasks 4d.3 and 4e.1, P7:4718, P7:4797) | after PR-2b1 3.25: U 0.25 + H1 0.5 + R 1.0 + T 0.5 = 2.25 -> 5.5 | merged as #23 (`86bd806`, 2026-11-17 18:53, observed; the schedule keeps its figure, t = 0 does not move): **5.5** |
| PR-2c3 | 2c.2, 2c.3 | on demand (consumers: `config` Tasks 4a.2 and 4a.3, section 6 `unblock`; `hooks` 3c.2 `gate_dispatch.check`, P7:3864; `records` the 6E.3b `escape_cost` part, L:871) | after PR-2b-rest 5.5: U 0.25 + sweep 0.5 + R 1.0 + T 0.5 = 2.25 -> 7.75 | **7.75** |
| PR-2c1 | 2c.1 | on demand by order, not by consumption (E30b, owner answer Q-PLP-3 (a): P1.3 starts after PR-2c1; no Consumes line of another stream names `claims_cli`, `grep -n "Consumes:" P7 \| grep -c claims_cli` = 0). By D7 alone it would ride the final PR | 2c.1 (M) starts at PR-2b-rest 5.5 + cut 0.25 = 5.75, 5.75 + 2.0 = 7.75; U 0.25 + R 1.0 from 7.75 = 9.0; after PR-loopstats 9.5: U 0.25 + T 0.5 = 0.75 -> 10.25 | **10.25** |
| PR-package | 3d.1, Rq-4-1 | on demand (consumers: `config` Tasks 4a.2, 4d.1 and R2.1, `residual` R5.1, `hooks` 3b.2 and 3c: edges 3d.1 -> 4a.2, 4d.1, R2.1, R5.1; section 6 `unblock`) | 3d.1 + Rq-4-1: cut 3.25 + 0.25 = 3.5, 3.5 + 2.5 = 6.0; U 0.25 + R 1.0 from 7.75 (PR-2c3's merge) = 9.0; after PR-2c1 10.25: U 0.25 + T 0.5 = 0.75 -> 11.0; V 1.5 after the merge -> 12.5, off the path (no PR waits for it) | **11.0** |
| PR-docs-v2 (the roll-in docs PR, groups A-F) | docs only | not a stream task; in flight with another controller (L:869) | its own work is not modelled; one merge-queue gap U 0.25 + T 0.5 = 0.75 after PR-package: 11.0 + 0.75 -> 11.75 | **11.75** |
| PR-P1 | P1.1-P1.3 | on demand (consumers: `records` 6E.1 and 6K.1, section 6 `unblock`) | cut 7.75 + 0.25 = 8.0; P1.1 8.0 + 2.0 = 10.0; P1.2 10.0 + 2.0 = 12.0; P1.3 12.0 + 2.0 = 14.0 (after PR-2c1, 10.25: Q-PLP-3 (a) holds); U 0.25 + R 1.0 + T 0.5 = 1.75 -> 15.75 | **15.75** |
| PR-P2 | P2.1-P2.3 | on demand (consumers: `runtime` 3a.2, `config` 4a.1, `hooks` 5a.1) | cut 15.75 + 0.25 = 16.0; P2.1 (L + 1 h) 16.0 + 4.0 = 20.0; P2.2 (L) \|\| P2.3 20.0 + 3.0 = 23.0; R 1.0 + T 0.5 = 1.5 -> 24.5 (no U: nothing merges after its cut) | **24.5** |
| PR-P4 | P4.1-P4.3 | on demand (consumers: `config` 4b.2, `records` R1.1, `hooks` 3c.2) | cut 24.5 + 0.25 = 24.75; P4.1 \|\| P4.3 24.75 + 2.0 = 26.75; P4.2 26.75 + 2.0 = 28.75; R 1.0 + T 0.5 = 1.5 -> 30.25 | **30.25** |
| PR-runtime | 3a.1 (done), 3a.2 | on demand (consumers: `hooks` 3b.2, 3c.1, 3c.2, R3.1; `records` 6K.2; `residual` R5.1: edges from 3a.2) | 3a.2 (L) 24.75 + 3.0 = 27.75; R 1.0 -> 28.75; after PR-P4 30.25: clean U 0.25 + T 0.5 = 0.75 -> 31.0; V 1.5 after the merge -> 32.5, off the path (no PR waits for it) | **31.0** |
| PR-P3 | P3.1-P3.3 (+Rq-5-4) | on demand (consumers: `hooks` 3b.3, `config` 4d.1, `records` 5b, 5c, 6K.2) | cut 24.75; tasks 24.75 + 6.5 = 31.25; U 0.25 + R 1.0 + T 0.5 = 1.75 -> 33.0 | **33.0** |
| stream a's V | the verifier over stream a | not a PR | after PR-P3 33.0, in the playbook's order (the final review first, then the verifier): final review R 1.0 -> 34.0; V 1.0 + fix-diff review 0.5 = 1.5 -> 35.5 | 35.5 |
| PR-a-final | 1t.1 (S), F1b (S), V's fix diffs | stream final PR (nothing consumes 1t.1 or F1b) | 1t.1 16.0 + 1.0 = 17.0 and F1b 1.75 + 1.0 = 2.75 are done long before; after PR-P3 33.0: R 1.0 -> 34.0; V 1.5 -> 35.5; U 0.25 + T 0.5 = 0.75 -> 36.25 | **36.25** |

The program's PRs and their V are in section 6.1 (PR-6E 33.75, PR-5a 34.5, PR-4c 35.25, PR-5b 39.5, PR-5c 40.25, PR-6K 42.0, PR-4d 43.0, PR-R3 43.75, PR-records 45.25, PR-hooks 47.0, PR-residual/R5 47.75, PR-R4 49.25, PR-config 52.0, PR-release 59.25). The queue order is the order of the "merged at" column, and every merge after PR-2c3 is off the critical path until PR-P1 (section 5).

Decisions (owner delegation 2026-11-09, builder's call within design 5.1-5.7):
- **Decision: stream a's final PR is a small PR cut after the stream's last on-demand merge (PR-P3), so V runs beside the consumer streams and not in front of PR-P3** -- why: PR-P3 is on the path and consumed by `hooks`, `config` and `records` at once (PV2:5.2 "defects found late" lets V's fixes go in the final PR or a small follow-up PR) -- cost if wrong: if the owner reads "final PR" as PR-P3 itself, V (1.5 h) goes before PR-P3 and the total grows by 1.5 h (60.0 to 61.5 h).
- **Decision: the off-path merges (PR-loopstats, PR-2c1, PR-package, PR-docs-v2) take the gap after PR-2c3** -- why: until PR-2c3 the chain has no waiting phase, so a merge inside it costs the next PR a clean update (0.25 h) or a U + T (0.75 h) each; after PR-2c3, P1 is in work for 6 h and the merges are free -- cost if wrong: loopstats merges 5.5 h sooner at 0.75 h on the path (right after PR-2b1) if the owner wants Rules N and T by script earlier.
- **Decision: PR-2b1 takes U + R + T, not the clean update** -- why: PR-unicode changes `result.py`, which Task 2b.1 consumes (plan:41 condition (3)) -- cost if wrong: if the update is clean, 1.0 h less on the path.
- **Decision: PR-2b-rest does its block-end full suite and H1 after #17 merges (SL:19), costing H1 0.5 h besides R** -- cost if wrong: 0.5 h.
- **Decision: PR-2c1 stays its own PR** (order edge E30b, Q-PLP-3 (a)) although D7 alone would let it ride -- cost if wrong: one PR end (1.75 h of work, off the path) saved, and P1.3 starts without waiting.
- **Decision: Task 1t.1 and Task F1b ride PR-a-final; F1b is a class S task** (the ESCALATE verdict registered it, SL:28; no plan task exists yet, so its id and class are provisional) -- cost if wrong: the task is renamed or re-classed; both end long before V.
- **Decision: config 4c starts after PR-package merges (M-B4-1 0.5 h at 11.0-11.5, then 4c 4.5 h)**, not at t = 0 as in revision 6, because M-B4-1 needs `plugin.json` from Task 3d.1 (L:814, L:837) -- cost if wrong: 4c runs earlier; 4c has 16 h of slack (4c ends 17.0, 4d starts 33.25).
- **Decision: PR-docs-v2 is placed as one gap after PR-package** (its own work is another controller's) -- cost if wrong: if it merges earlier, each PR then updating pays a clean update of 0.25 h, up to 0.75 h on the path.
- **Decision: `residual` R5.1 starts at 38.25, after the 5b and 5c ends** (wave rule, section 6.2) -- cost if wrong: none; R5 waits for the enablement after PR-hooks (45.0) in any case.

**Revision 6 table (history; t = 0 is PR-1d2's merge, #11, 2ab84d6, L:807; h from t = 0).** Decision (owner delegation 2026-11-09): every figure is the figure of the launch schedule (the program controller's untracked launch schedule of 2026-11-10, not in the repository; its figures are restated here in full; not revision 5, whose figures are in S+ units; "the launch schedule" below means it) in h from 2026-11-10, less 3.75 h, the 3.75 h being PR-1d2's merge time on that schedule's clock, except where the row says it is derived -- one constant keeps every order and gap, and each re-based figure is written in full in this record, so no reader needs the launch schedule -- cost if wrong: every figure off by the error in that constant, the order unchanged. Merged rows carry the PR number and merge sha. The clean update (line U of section 1) is used: a queued PR merges U + T = 0.75 h after the merge before it; R is 1.0 h and T 0.5 h.

| PR | tasks | starts when | merges after (on `main` first) | timeline (h from t = 0) | merged |
|---|---|---|---|---|---|
| PR-B2 | B2.1-B2.3, the FIXED_RULES test (0d92a39) | done | PR-1d (merge queue) | stream b DONE (L:802); final review and verifier clean | merged #12, 0ec38e6 (L:805) |
| PR-1d2 | 1d2.1 | done | PR-B2 | clean update 7091e34 (L:807) | merged #11, 2ab84d6 (L:807): **t = 0** |
| PR-B2 follow-up | span tests for `tests/prose_check.py` (UR-1 follow-up) | done | PR-1d2 | stream b (L:809) | merged #13, 427ec10 (L:810) |
| README | the README overview, no task | done | #13 | L:812 | merged #14, 81f9027 (L:812) |
| PR-2b1 | 2b.1 | running: group G0, `block/b2b1` 6f77345, final review re-dispatched 2026-11-14 (L:813) | PR-B2, PR-1d2 (E15; E15b is moot) | 2b.1 done; U (after PR-1d2) before its review; R 1.0; T 0.5 | **3.0** |
| PR-unicode | 1u.1, 1u.2 | running: group G3, 1u.2 (U1) done at 3555d92 on `block/a-unicode`, 1u.1 (F1) re-dispatched (L:813) | none | off the critical path; takes the earliest merge-queue gap after PR-2b1: U + T = 0.75 | **3.75** (derived: 3.0 + 0.75) |
| PR-docs6 (the revision-6 docs PR) | docs only: plan, breakdown, UR-1 register row | running (L:814); Decision (owner delegation 2026-11-09): streams work from the framework plan's task sections plus the ledgered owner answers and the revision-6 docs pull request, which is cut after PR-B2 merges and merged before PR-package -- the framework plan is already planned in full, and the stream plans are its derived records -- cost if wrong: a stream re-dispatched after a docs correction (about 0.5 h) | PR-unicode | off the critical path; the next gap, U + T = 0.75 | **4.5** (derived: 3.75 + 0.75) |
| PR-package (program, section 6.1) | 3d.1 | after PR-2b1 (Q-PLP-1 (a)) | PR-docs6 | 3d.1 and Rq-4-1 3.25-5.75; R 1.0; T 0.5 | **7.25** (program PR; section 6.1) |
| PR-2b-rest | 2b.2, 2b.3 | PR-2b1 (E17, E18) | PR-2b1 | 2b.2 3.25-5.25; 2b.3 5.25-7.25; R 7.25-8.25; T 8.25-8.75 | **8.75** |
| PR-2c3 | 2c.2, 2c.3 (with `gitinfo.is_ancestor`, Q-PLP-5 (a)) | PR-2b1 (E12), PR-1d2 (E11c) | PR-2b-rest (its update) | 2c.2 3.25-5.25; 2c.3 (L) 5.25-8.25; waits for PR-2b-rest at 8.75; U 8.75-9.0; 2c.2's literal sweep as a commit after that update 9.0-9.25 (0.25); R 9.25-10.25; T 10.25-10.75 | **10.75** |
| PR-2c1 | 2c.1 | PR-2b-rest (E20), PR-1d (E20b), PR-D | PR-2c3 | 2c.1 9.0-11.0; U 11.0-11.25; R 11.25-12.25; T 12.25-12.75 | **12.75** |
| PR-tests | 1t.1 (the test-only task) | PR-2c3 (L:803) | PR-2c1 | off the critical path; the gap after PR-2c1: U + T = 0.75 | **13.5** (derived: 12.75 + 0.75) |
| PR-P1 | P1.1-P1.3 | P1.1 and P1.2 at PR-2c3, P1.3 after PR-2c1 (Q-PLP-3 (a), L:800) | PR-2c3, PR-2c1 | P1.1, P1.2 and P1.3 serial 6 h, 11.0-17.0 (P1.3 from 15.0, after PR-2c1 at 12.75: 2.25 h of slack); U 17.0-17.25; R 17.25-18.25; T 18.25-18.75 | **18.75** |
| PR-P2 | P2.1-P2.3 | PR-P1 | PR-P1 | start 19.0; P2.1 (L + 1 h) 4 h; P2.2 (L) \|\| P2.3 3 h; R; T (no U: nothing merges after its cut) | **27.5** |
| PR-P4 | P4.1-P4.3 | PR-P2 (Q-BD-2) | PR-P2 | start 27.75; P4.1 \|\| P4.3 and P4.2 4 h; R; T | **33.25** |
| PR-P3 | P3.1-P3.3 (+Rq-5-4) | PR-P2 (Q-BD-2) | PR-P2; update after PR-P4 | start 27.75; 6.5 h to 34.25; U (after PR-P4, 33.25) 34.25-34.5, before its review; R; T | **36.0** |
| program setup and registration | program plans, `streams.yml`, `breakdown.yml` (Part II), the owner's `stream-ownership` decision for `release`'s version sites and `program-create` decision, `program create --plan`, worktrees, M1-M10 and M-B4-1 | PR-P3 (registration only; the early streams run unregistered, L:814) | none | about 2 h from about 40.25 (wave cap); **off the critical path** | none |

No critical-path figure moves for PR-unicode, PR-docs6 and PR-tests: each takes a merge-queue gap of U + T = 0.75 h (PR-unicode 3.0 to 3.75, PR-docs6 3.75 to 4.5, PR-tests 12.75 to 13.5) in which no critical-path PR is waiting. The next critical-path merges are PR-2b-rest (8.75; its update from `main`, which takes both earlier merges, comes before its review at 7.25) and PR-P1 (18.75, whose update before its review at 17.0 takes PR-tests); PR-2c1's merge (12.75) is on the path only through P1.3, which starts at 15.0.

**Revision 5 table (history; the merged rows are annotated with PR number and merge sha).**

| PR | tasks | starts when | merges after (on `main` first) | timeline (h) | merged |
|---|---|---|---|---|---|
| PR-1c0 | 1c0.1 + reviewed docs (6890aff, 615bc21; Q-BD-6) | running | none | U1 fix and re-review to 1.0, then E | **2.5** (merged #4, f83747a) |
| PR-C2 | (done) | the docs-only PR (owner answer Q-DOCS-1 (e)) | the docs-only PR (first in the merge queue after it, owner answer Q-RD8b-1 (a)) | U after the docs-only PR (3.75), then E: C2's final review ran before PR-1c0 (L:352), so the update restarts it (P078:7522, "Block C2 end:** final review, verifier, then the pull-request flow"; the update rule above) | **5.5** (merged #7, e6db60f) |
| PR-1c | 1c.1, 1c.2, 1c.3 | running; 1c.2 after the docs-only PR (owner answer Q-DOCS-1 (e); was after PR-1c0, L:387) | the docs-only PR, PR-C2 (merge queue) | 1c.1 to 2.0; 1c.3 (group worktree, L:206 precedent) 2.0 to 4.0; `b1c1`'s update from `main` 3.75 to 4.0; 1c.2 4.0 to 6.0; U (after PR-C2, 5.5); E | **7.75** (merged #6, 1faa1f2) |
| PR-resume-docs (the docs-only PR, Q-BD-6) | 1c0.2, after the session-resume design and its plan, spec and breakdown edits (P078:564; L:541) | the docs edit set's clean re-review (1c0.2, then the final review and verifier, in parallel with PR-1c0's remaining work, on a branch cut from `block/b1c`'s head); the tail after PR-1c0 merged (P078:564; owner answer Q-DOCS-1 (e)) | PR-1c0 only: it is the first merge after PR-1c0; every stream (`b`, `c`, `d`) and Task 1c.2 start after it (owner answer Q-DOCS-1 (e); revision 4 merged it after PR-C2 and PR-1c, at 8.25) | 1c0.2, its final review and verifier before PR-1c0's merge (re-checked at the cherry-pick if PR-1c0's code changed after them); the tail: cut from `main`, cherry-pick, gates (U) 2.5 to 2.75; the rest of its end 2.75 to 3.75 (the owner's approval of the head, the merge, read-back, post-merge gates, `MERGED` line; owner answer Q-RD8c-1 (b)) | **3.75** (merged #5, 13ca17e) |
| PR-D | 2a.1, 2a.2, 2a.3 | the docs-only PR (owner answer Q-DOCS-1 (e); L:389) | the docs-only PR, PR-1c (E09), PR-1d (O3) | `sd1`'s update 3.75 to 4.0; 2a.1 4.0 to 7.0; wait for PR-1c (7.75), then U and records, store.py and test_store.py part 0.5 h, commit at 8.75; 2a.2 8.75 to 10.75; 2a.3 10.75 to 12.75, then, after PR-1d (13.75), U and its `GATES["claims"]` commit, to 14.0 (O3); E | **15.5** (merged #10, 87f5e43) |
| PR-B2 | B2.1, B2.2, B2.3 | the docs-only PR (`sb2` cut from `main` after it, owner answer Q-DOCS-1 (e)) | PR-1c0, the docs-only PR, PR-C2, PR-1c (merge queue) | B2.1 3.75 to 5.75; B2.2 to 8.25; B2.3 to 10.25; U (after PR-1c, 7.75); E | **12.0** (before PR-1d in the merge queue: the shortest order, revision 3) (merged #12, 0ec38e6) |
| PR-1d | 1d.1, 1d.2, 1d.3 | PR-1c | PR-1c, PR-B2 (merge queue) | 1d.1 \|\| 1d.2 7.75 to 9.75; 1d.3 (E06b) 9.75 to 11.75; U after PR-B2's merge (12.0); E | **13.75** (merged #8, f6b703a) |
| PR-1d2 | 1d2.1 | PR-D (E11b) | PR-D | 1d2.1 15.5 to 17.5; E | **19.0** (merged #11, 2ab84d6) |
| PR-2b | 2b.1, 2b.2, 2b.3 | PR-D (E15) and PR-B2 (E15b) | PR-D, PR-B2, PR-1c, PR-1d2 (its U) | 15.5 to 21.5; U (after PR-1d2, 19.0); E | **23.25** |
| PR-2c | 2c.1, 2c.2, 2c.3 | PR-2b (E12, E20), PR-1d (E20b), PR-D | PR-2b | 2c.1 \|\| 2c.2 23.25 to 25.25; 2c.3 (L) to 28.25; E (nothing merges after its cut, so no U) | **29.75** |
| PR-P1 | P1.1-P1.3 | PR-2c (P:1692) | PR-2c | serial 6 h; E | **37.25** |
| PR-P2 | P2.1-P2.3 | PR-P1 | PR-P1 | P2.1 (L + 1 h, owner answer Q-RD8b-2 (b)) 4 h; P2.2 (L) \|\| P2.3 3 h; E | **45.75** |
| PR-P4 | P4.1-P4.3 | PR-P2 (Q-BD-2) | PR-P2 | P4.1 \|\| P4.3 2 h; P4.2 2 h; E | **51.25** |
| PR-P3 | P3.1-P3.3 (+Rq-5-4) | PR-P2 (Q-BD-2) | PR-P2; update after PR-P4 (shared `__main__.py`, `test_self_adoption.py`) | 6.5 h; U (after PR-P4); E | **54.0** |
| program setup | program plans (written from about 36.25 h on, in parallel), `streams.yml`, `breakdown.yml` (Part II), the owner's `stream-ownership` decision for `release`'s version sites (asked and answered before `program create`, owner answer Q-F80W-13 (a)), the owner's `program-create` decision, `program create --plan`, worktrees, M1-M10 (P:2559) and M-B4-1 (P:3325) | PR-P1..P4 | — | 2 h | **S = 56.0** |

The rows from PR-2b to program setup are replaced by the revision 6 table above (revision 5 figures, kept as history); the merged rows are the same facts with their PR numbers and merge shas (`git log --first-parent --merges 81f9027`). Docs PR #9 (1ae992d) is not a row of this table.

Notes.
- FIXED_RULES test (F-BD-4). PR-D (15.5) merges after B2's final review (about 10.25-12.0) and after PR-B2 (12.0). So by P:5582 the "B2 merges first" branch applies, and A writes the test: in 2b.1, which is A's first task after both PRs are on `main` (plan stream rules, "Cross-stream order"). B2 does not wait, and its final review is not re-run.
- PR-C2 carries `cites` into `run_all` from the start, because C2 merges before 2b.1 starts (P:1191, P:5574).

**Pre-program waves, revision 6 (history; cap 25).** The windows are the launch schedule's windows less 3.75 h (the rule of the revision 6 table above; the windows before t = 0 are history). The counting rule is the program table's (section 6.2): 1 per controller and per sub-controller, 2 per active task and per end, streams `a` and `b` at 3 each while only their controller and one end or task are live. The counts here are the pre-program streams only (stream a, stream b, the revision-6 docs PR); section 6.2 adds the program streams and gives each window's total.

| wave | window | what runs (pre-program streams only) | agents |
|---|---|---|---|
| PA1 | 0-3.0 | stream a: controller 1, group G0's end (PR-2b1's final review) 2, group G3 sub-controller 1 and 1u.1 2 = 6; stream b: route-in PR 3 (L:814); PR-docs6: 2 tasks (plan, breakdown) 4 | 13 |
| PA2 | 3.0-10.75 | stream a: controller 1, groups X and Y sub-controllers 2, 2c.2/2c.3 and 2b.2/2b.3 4 = 7; G3's end 3; stream b 3; PR-docs6's end 2 (to 4.5) | 15 |
| PA3 | 10.75-27.5 | stream a: 2c.1 and P1, then P2, up to 7; PR-tests: sub-controller 1 and 1t.1 2 | 10 |
| PA4 | 27.5-36.0 | stream a: P3, P4 and their ends 7 | 7 |

**Pre-program waves, revision 5 (history; cap 25; peak 15):**

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

**Revision 7 (t = 0 = 2026-11-17 14:00 SAST; process v2): PR-unicode (1.5) -> PR-2b1 (3.25) -> PR-2b-rest (5.5) -> PR-2c3 (7.75) -> cut 0.25, P1.1-P1.3 / PR-P1 (15.75) -> cut 0.25, P2 / PR-P2 (24.5) -> cut 0.25, the P3 tasks (31.25) -> PR-P3 (33.0).** The pre-program part is 33.0 h from t = 0 (revision 6: 36.0 h from its t = 0); the whole path is 60.0 h (section 7). Arithmetic of the pre-program part, each step its unit cost: PR-unicode R 1.0 + T 0.5 = 1.5; PR-2b1 U 0.25 + R 1.0 + T 0.5 = 1.75, 1.5 + 1.75 = 3.25; PR-2b-rest U 0.25 + H1 0.5 + R 1.0 + T 0.5 = 2.25, 3.25 + 2.25 = 5.5; PR-2c3 U 0.25 + sweep 0.5 + R 1.0 + T 0.5 = 2.25, 5.5 + 2.25 = 7.75; cut 7.75 + 0.25 = 8.0, P1.1 + P1.2 + P1.3 = 3 x 2.0 = 6.0, 8.0 + 6.0 = 14.0, PR-P1 1.75, 14.0 + 1.75 = 15.75; cut 16.0, P2.1 4.0 + P2.2 \|\| P2.3 3.0 = 7.0, 16.0 + 7.0 = 23.0, R + T 1.5, 24.5; cut 24.75, the P3 tasks 6.5, 31.25, PR-P3 U + R + T 1.75, 33.0.
- Slack. The P4 chain (cut 24.75, 4.0 h of tasks, R + T 1.5: PR-P4 at 30.25) has 0.25 h of slack before PR-P3's update: PR-runtime merges 0.75 h after PR-P4, at 31.0, and PR-P3's update starts at 31.25. Everything that merges between PR-2c3 (7.75) and PR-P1's update (14.0) is off the path: PR-loopstats 9.5 (1.75 h of slack), PR-2c1 10.25 (1.75 h; P1.3 starts at 12.0 and needs it), PR-package 11.0 and PR-docs-v2 11.75 (2.25 h each). Stream a's V (33.0 to 34.5) and PR-a-final (36.25) have 2.0 h of slack (PR-5b's clean update starts when its review ends, at 38.25).
- No tie. PR-runtime (3a.2 24.75 + 3.0 = 27.75, R 1.0 -> 28.75, clean U + T after PR-P4 30.25 -> 31.0; its V no longer sits before it, section 6.1) merges 0.25 h before PR-P3's update at 31.25, which the P3 tasks (24.75 + 6.5) set alone. A delay of the P3 tasks moves PR-P3; so does a delay of PR-P4 by more than 0.25 h.
- If PR-unicode's merge is counted at its observed 0.25 h (section 4, state at t = 0), every figure of this chain from PR-2b1 on is 1.25 h earlier; section 7 gives the total (58.75 h).

**Revision 6 (history; t = 0 at PR-1d2's merge, 2ab84d6; revision-6 figures are the launch schedule's less 3.75 h, the Decision of the revision 6 table above; clean update; 2c.3 pulled forward; Q-PLP-3 (a)): PR-2b1 (3.0) -> 2b.2, 2b.3 / PR-2b-rest (8.75) -> PR-2c3's update, literal sweep and end (10.75; 2c.2 and 2c.3 end at 8.25 and wait 0.5 h for that update) -> P1 / PR-P1 (18.75) -> P2 (27.5) -> P3 (36.0) -> the program chain of section 7 (registration and setup are off the path).** The pre-program part is 36.0 h from t = 0; the whole path is about 61.5 h (section 7). The revision 5 path (93.0 h from 2026-11-02) is kept below as history. PR-unicode, PR-docs6 and PR-tests take merge-queue gaps (section 4) and move no figure of this path.

Revision 6 slack and checks (history). PR-2c1 (12.75) has 2.25 h of slack before P1.3 starts at 15.0 (Q-PLP-3 (a)). The path to PR-2c3 passes through PR-2b-rest's merge, not through 2c.3's end: 2b.2 and 2b.3 end at 7.25 and PR-2b-rest merges at 8.75, while 2c.2 and 2c.3 end at 8.25, so PR-2c3's update waits until 8.75 (E12 and E11c are met at 3.0). The launch schedule's path line names 2c.2 -> 2c.3 / PR-2c3 (14.5 there, 10.75 here), while its own table puts PR-2c3's update after PR-2b-rest (12.5 there, 8.75 here); both are stated and neither is ruled on here.

**Revision 5: PR-1c0 (2.5) -> the docs-only PR's tail: U, approval, merge, read-back, post-merge gates (3.75) -> B2.1, B2.2, B2.3 -> PR-B2's U and E -> PR-B2 (12.0) -> PR-1d's U and E -> PR-1d (13.75) -> U and 2a.3's `GATES["claims"]` commit (O3) -> PR-D (15.5) -> 2b.1, 2b.2, 2b.3 -> PR-2b (23.25) -> 2c.2 -> 2c.3 -> PR-2c (29.75) -> P1 (37.25) -> P2, with P2.1 at L + 1 h (45.75) -> P3 (54.0) -> setup (S = 56.0).**

Revision 3: the update comes before the final review (P078:6251; P:5560), so an update after another PR's merge restarts that PR's E (line U of section 1); from revision 6 only an update that is not clean does (line U). Revision 5 (owner answers Q-DOCS-1 (e), Q-RD8b-1 (a), Q-RD8b-2 (b), Q-RD8c-1 (b)): Task 1c0.2 and the docs-only PR's final review and verifier run before PR-1c0 merges, so after it only the docs-only PR's tail remains and it is the first merge after PR-1c0 (3.75: its tail is U plus the rest of its end, 1.25 h, owner answer Q-RD8c-1 (b)); PR-C2, PR-1c, PR-B2, PR-1d and PR-D follow in the queue, and every stream and Task 1c.2 start at 3.75 (`sb2`, cut then) or after their branch's update (4.0). Of the 20 feasible orders of those five, three give the shortest path, S = 56.0: (PR-C2, PR-1c, PR-B2, PR-1d, PR-D), kept here as the one with PR-C2 earliest (owner answer Q-RD8b-1 (a)), (PR-1c, PR-C2, PR-B2, PR-1d, PR-D), and (PR-1c, PR-B2, PR-1d, PR-D, PR-C2), which merges PR-C2 after 2b.1 starts; the best order with PR-1d before PR-B2 is (PR-1c, PR-1d, PR-B2, PR-D, PR-C2), S = 57.0. Within the 16 of those orders that also merge PR-C2 before 2b.1 starts (the PR-C2 note in the Notes above), the shortest is still 56.0 and the best with PR-1d before PR-B2 is (PR-1c, PR-C2, PR-1d, PR-B2, PR-D), S = 57.25. Revision 4's figures (120 orders of six PRs with the docs-only PR among them, S = 53.75, 54.75 and 55.0, with P2.1 at 3 h) are replaced: the docs-only PR's tail (U and the rest of its end, 1.25 h) now comes before every stream starts, and Task P2.1 is 1 h longer (L + 1 h, owner answer Q-RD8b-2 (b)), so the path, through B2 as in revision 4, moves +2.25 h. Slack: PR-1c's line, 0.25 h (1d.3 ends at 11.75, before PR-B2's merge at 12.0, which sets PR-1d's U); the 2a.1 -> 2a.2 -> 2a.3 work (12.75) 1.0 h; PR-1d2 (19.0) 2.5 h before it would hold PR-2b's U.

---

## 6. Program record (Part II, the future `breakdown.yml`)

The schema fields `done`, `period`, `residual` and path windows are the additions stated in plan Task P2.2 (`breakdown/1`) and Task P2.1 (`streams/1`). Period events are `program-start`, `merged:<stream>/<sub-block>` (the PR that carries that sub-block read back as merged, from its `MERGED` line; one stream PR can carry several sub-blocks, as `init4`'s carries 4c, 4d and 4e: plan Task P2.3, owner answer Q-F80W-2), `merged:<stream>` (the stream's last sub-block merge: its last `merged:<stream>/<sub-block>` event; `final=yes` marks the plan's last PR and is not used, F-BDr3-2) and `program-close` (R2:F-BDr2-1; plan Task P2.2, and Task P1.2's `MERGED` line).

```yaml
schema: breakdown/1
plan: 2026-10-31-strict-delivery-framework
max_concurrent: 25
max_depth: 5
done: [1a.1, 1a.2, 1a.3, 1b.1, 1b.2, 1b.3, 1c0.1, 1c0.2, 1c.1, 1c.2, 1c.3, 1d.1, 1d.2,
       1d.3, 1d2.1, 1d3.1, 2a.1, 2a.2, 2a.3, 2b.1, 2b.2, 2b.3, 2c.1, 2c.2, 2c.3,
       P1.1, P1.2, P1.3, P2.1, P2.2, P2.3, P3.1, P3.2, P3.3, P4.1, P4.2, P4.3,
       B1.1, B1.2, B1.3, B2.1, B2.2, B2.3, C1.1, C1.2, C2.1, C2.2, 1u.1, 1u.2, 1t.1]
streams:   # revision 6: seven streams (Q-SPD-1 (a)). `done` above is the forecast for registration (about 40.25 h, section 4), not the state now, and holds only tasks finished by then: the pre-program tasks, 1u.1, 1u.2 and 1t.1 (PR-unicode 3.75, PR-tests 13.5). The program tasks of PRs merged before registration, 3d.1 (PR-package 7.25) and 3a.1, 3a.2 (PR-runtime 34.0), are not in it yet: at registration these three are added to `done` and dropped from their streams' `tasks`, from every group that names them (g-w1a names 3a.1, g-w2a names 3d.1, g-w4a names 3a.2; P2.2 refuses a group naming an unknown task) and from every edge that names them (P2.2 refuses a `done` task in a stream or named by an edge; until then the streams, groups and edges below keep them, the edges being: 3a.1 -> 3a.2, 3a.1 -> 3c.1, 3a.2 -> 3b.2, 3a.2 -> 3c.1, 3a.2 -> 3c.2, 3a.2 -> 6K.2, 3a.2 -> R3.1, 3a.2 -> R5.1, 3d.1 -> 4a.2, 3d.1 -> 4d.1, 3d.1 -> R2.1, 3d.1 -> R5.1, 12 edges). Decision (owner delegation 2026-11-09): the registration precondition "`done:` listing every finished task" is read as finished and merged -- 3b.1, 4c.1, 4c.2 and 6E.3 finish before 40.25 but their PRs merge later (PR-hooks 44.25, PR-config 55.0, PR-records 45.5), so they stay in their streams and out of `done` -- cost if wrong: registration refuses a task listed in both, fixed by dropping it from its stream, minutes. Ownership before registration is section 2's table, hand-checked
  - {id: residual, residual: true, period: {from: program-start, until: program-close},
     tasks: [R5.1],
     unblock: "R5.1 (the interim-skill removal, Q-BRV-1 (a)) after merged:runtime, merged:package and merged:hooks, once the owner's enablement of the plugin is ledgered after PR-hooks and after every live branch has updated from main (Q-PLP-4 (a)); PR-residual/R5 is the first program merge after the enablement, amending Q-BRV-3 (a) (45.0 h from t = 0 at the earliest; P078:3091, P078:3787-3788)"}
  - {id: package, period: {from: program-start, until: merged:package}, paths: [P:2553 row without the 3d.2 paths], tasks: [3d.1],
     unblock: "3d.1 after PR-2b1 (it consumes run_all.check; its registry lines are hunk-scoped until PR-P3, Q-PLP-1 (a)); PR after Rq-4-1 has landed; the first program merge (7.25 h from t = 0)"}
  - {id: runtime, period: {from: program-start, until: merged:runtime}, paths: [P:2550 row], tasks: [3a.1, 3a.2],
     unblock: "3a.1 at t = 0 (starts now, L:814); 3a.2 after PR-P2 and M1-M10 (it consumes programs.live_programs, gitinfo.current_branch and checkpoints.parse_handoff); the PR merges U + T after PR-P4 (34.0 h)"}
  - {id: hooks, period: {from: program-start, until: merged:hooks},
     paths: [P:2551 row, P:2552 row, P:4366-4489 Files,
             {path: gates/hooks/post_read.py, from: merged:runtime}, {path: gates/hooks/session_start.py, from: merged:runtime},
             {path: tests/test_hook_entry.py, from: merged:runtime}, {path: tests/test_hook_session_start.py, from: merged:runtime},   # Q-SPD-2
             gates/lib/gitinfo.py, gates/tools/githooks.py],   # whole files from PR-P3, i.e. from program-start: Q-PLP-1 (a), section 2's table
     tasks: [3b.1, 3b.2, 3b.3, 3c.1, 3c.2, 5a.1, 5a.2, 5a.3, R3.1, R3.2],
     unblock: "3b.1 at t = 0 (starts now, L:814); 5a after PR-P2 (5a.1 consumes programs.load_program and dispatch.ROLES); 3b.2 after merged:runtime and merged:package, its gitinfo.py and githooks.py edits after PR-P3; 3b.3 after PR-P3 (merge.agent_may_merge); 3c.1 after merged:runtime and merged:package; 3c.2 after PR-P4 and PR-P2 (gate_dispatch, programs.live_programs); R3 after the 3b, 3c and 5a ends in the stream branch"}
  - {id: records, period: {from: program-start, until: merged:records},
     paths: [P:4551, P:4608, P:4665, P:4730 Files, P:4812 row, P:4813 row,
             skills/strict-delivery/prompts/program_controller.md, tests/test_prompt_blocks.py, tests/prose_check.py],   # Q-SPD-2; R1.1's files from PR-P4 (Q-PLP-1 (a), section 2's table)
     tasks: [R1.1, 5b.1, 5b.2, 5c.1, 5c.2, 6E.1, 6E.2, 6E.3, 6K.1, 6K.2],
     unblock: "6E.3 after PR-2c3 (escape_cost is declared in config/2 by 2c.2); 6E.1 and 6K.1 after PR-P1; R1.1 after PR-P4 (program_controller.md is created by P4.3); 5b and 5c after PR-P3 (Rq-5-4 is on main from P3.2); 6K.2 after merged:runtime and PR-P3 (worktrees.same_repository, P078:5807); the 5c end after the R1 end in the stream branch (Rq-5-5)"}
  - {id: config, period: {from: program-start, until: merged:config},
     paths: [P:3377 row, playbook/decisions.md, skills/strict-delivery/SKILL.md, tests/test_skill.py,   # last three by the Q-BD-8 (a) stream-ownership decision
             P:3378 row, P:3379 row, CLAUDE.md, .gitignore,
             gates/__main__.py, gates/producers.py, gates/run_all.py, tests/test_run_all.py],   # whole files from PR-P3, i.e. from program-start (Q-PLP-1 (a) with Q-SPD-2 (a); replaces residual's window and Q-BD-8 (a)'s merged:residual/R2; not Q-SPD-2 (a)'s `merged:package` and program-start windows (L:795), which Q-PLP-1 (a) (L:800) moves to PR-P3, for CLAUDE.md and .gitignore)
     tasks: [4a.1, 4a.2, 4a.3, 4b.1, 4b.2, 4c.1, 4c.2, 4d.1, 4d.2, 4d.3, 4e.1, 4e.2, 4e.3, R2.1, R2.2, R2.3, R4.1],
     unblock: "4c.1 at t = 0 once M-B4-1 is measured, 4c.2 after 4c.1 (prose_check.FORBIDDEN rows are on main since PR-B2); 4a.1 after PR-P2; 4a.2 after 4a.1, merged:package and PR-2c3; 4a.3 after 4a.2, PR-2c3 and the 4a end; 4b.1 after 4a.2 and the 4a end (4b starts after the 4a end in the stream branch, Q-SPD-3 (a) as the plan's "Program grouping for v0.1" states it); 4b.2 after 4a.3 and PR-P4, and not before 44.25 (wave cap, the Decision of section 6.1); 4d.1 and 4d.3 after PR-P3 (merge.MODES), the 4a end and the 4c end; with Q-SPD-3 (a) sub-block 4a is 4a.1-4a.2 and 4b is 4a.3, 4b.1, 4b.2; R2.1 after merged:hooks/5a and merged:package, then R2.2 after merged:records/5b and merged:records/5c and R2.3 after merged:records/6E, serially (all three edit gates/__main__.py); R4.1 after the 4b end and PR-loopstats, the 6E.3 merge (P078:5329); the Rq-4-2, Rq-4-5, Rq-4-3 commits at the end of 4e.3 after the R2 end (order P:3362); the Rq-4-5 commit also removes the interim CLAUDE.md text of Task 1c0.2 (P078:3846)"}
  - {id: release, period: {from: merged:config, until: program-close}, paths: [P:4814 row incl. the version sites], tasks: [6R.1, 6R.2, 6R.3],
     unblock: "after every other stream has merged (P:4799; P078:5309); the version sites by the `stream-ownership` decision, asked and answered before `program create` (owner answer Q-F80W-13 (a)), so their windows are in this record from `create`"}
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
  - {from: 3d.1, to: R2.1}        # orders package's registry window before config's R2 (Q-SPD-2 (a); owner Q-F80-1 (a); Block 3 registration ruling)
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
groups:   # revision 6: antichains, each within 25 tasks; formed per window of the revision-6 timeline (section 6.2) by the window in which a task starts, a task joining the first group of its window that holds no task it is ordered against (an edge, direct or through other edges); recomputed from the revision-6 timeline, not copied from revision 5
  - {id: g-w1a, tasks: [3a.1, 3b.1, 4c.1]}                  # 0 to 3.0
  - {id: g-w1b, tasks: [4c.2]}                              # 0 to 3.0, after 4c.1
  - {id: g-w2a, tasks: [3d.1]}                              # 3.0 to 10.75
  - {id: g-w3a, tasks: [6E.3, 6E.1, 6K.1]}                  # 10.75 to 27.5
  - {id: g-w3b, tasks: [6E.2]}
  - {id: g-w4a, tasks: [3a.2, 4a.1, 5a.1, R1.1]}            # 27.5 to 36.0
  - {id: g-w4b, tasks: [4a.2, 5a.2, 3b.2]}
  - {id: g-w4c, tasks: [4a.3, 4b.1, 5a.3]}
  - {id: g-w5a, tasks: [4d.1, 5b.1, 5c.1, 3b.3, 3c.1, 3c.2, R5.1, 6K.2, R3.1]}   # 36.0 to 44.25
  - {id: g-w5b, tasks: [5b.2, 5c.2, 4d.2, R3.2]}
  - {id: g-w5c, tasks: [4d.3]}
  - {id: g-w6a, tasks: [4e.1, R2.1, R2.2, R4.1, R2.3]}      # 44.25 to 55.0 (R2.1-R2.3 and R4.1 are the plan's tasks). Decision (owner delegation 2026-11-09): R2.1 to R2.3 run serially (R2.1 when hooks merges; R2.2 and R2.3 after records merges) -- all three edit `gates/__main__.py` (P:6097, P:6116, P:6135) -- cost if wrong: none (2.5 h slack, section 7)
  - {id: g-w6b, tasks: [4e.2, 4b.2]}                        # 4b.2 44.25 to 46.25 (held by the wave cap, section 6.1; before R4.1 in g-w6a, not ordered against 4e.2)
  - {id: g-w6c, tasks: [4e.3]}
  - {id: g-w7a, tasks: [6R.1]}                              # 55.0 to 61.5
  - {id: g-w7b, tasks: [6R.2]}
  - {id: g-w7c, tasks: [6R.3]}
```
`R1.1`..`R3.2` are new plan tasks (plan section "Stream `residual`"). They are written here as the record must name them. `R4.1` is plan Task R4.1 (P078:6156) and `R5.1` plan Task R5.1 (owner answer Q-BRV-1 (a)), both added by the session-resume revision (revision 3). Revision 6 (owner 2026-11-10, schedule cut 2): R1.1 runs in stream `records`, R2.x and R4.1 in `config` and R3.x in `hooks`, with their sub-block ids kept; `residual` keeps R5.1 and its residual ownership.

### 6.1 Program PRs and unblock conditions

**Revision 7 (process v2).** Each program stream has one V (PV2:5.2), run after the stream's last block (after that block's merge when it merged on demand); no on-demand PR waits for it, and its fixes go in the stream's final PR or, when every block already merged on demand, in a small follow-up PR, opened only if V finds a defect, which is then the final PR. A sub-block opens its own on-demand PR as soon as it is ready when a task of another stream consumes it (D7). The edges of the YAML above give ten consumed sub-blocks: 3a (PR-runtime), 3d (PR-package), 5a (PR-5a), 5b (PR-5b), 5c (PR-5c), 6E (6E.3 in PR-loopstats, 6E.1-6E.2 in PR-6E), 6K (PR-6K), R3 (PR-R3), R4 (PR-R4) and 4e (PR-config, which carries R2 with it). The `Consumes:` lines of `release`'s Tasks 6R.1 and 6R.2 name two more, which D7's `Consumes:` clause counts (plan review 3, R3-4): 4d (`init`, Task 4d.1; PR-4d) and 4c (`managed.put_block`, `templates.render`, Tasks 4c.1-4c.2; PR-4c); twelve in all. A PR cut from the stream branch carries every earlier sub-block of its stream that is not yet merged, since a work branch is never rebased (PV2:5.2; plan review 3, R3-3): PR-5a carries 3b.1 (merged into `20261110-v01/hooks/main` as `3194b4f`, not on `main`, before the 5a group is cut at 24.75), PR-R3 carries the rest of 3b (3b.2, 3b.3) and 3c, PR-R4 carries 4b, PR-4d carries 4a, PR-5b carries R1 (the R1 end, 32.5, is on the stream branch before the 5b group is cut at 33.25; the 5c end also waits for the R1 end, plan "Program grouping") and PR-6E carries 6E.3b. A PR that carries earlier sub-blocks has the stream's larger R (section 1). With them gone, the stream final PRs of `hooks` and `records` carry only V's fixes: PR-hooks and PR-records are small follow-up PRs, opened only if V finds a defect, and their slots stay in the queue below (conservative: the plugin enablement, Q-PLP-4 (a), follows PR-hooks); PR-config carries 4e and R2; `residual` and `release` are not consumed and their PRs are their stream final PRs, each after its V. For a consumed sub-block the 1.0 h sub-block end becomes its PR end: R 1.0 h from its tasks' end, then a clean U 0.25 + T 0.5 after the PR before it in the queue (merge = the larger of tasks' end + 0.25 + R + 0.5 and the previous merge + 0.75). The merge-queue order, with the merge times of this section and of section 4: PR-unicode 1.5, PR-2b1 3.25, PR-2b-rest 5.5, PR-2c3 7.75, PR-loopstats 9.5, PR-2c1 10.25, PR-package 11.0, PR-docs-v2 11.75, PR-P1 15.75, PR-P2 24.5, PR-P4 30.25, PR-runtime 31.0, PR-P3 33.0, PR-6E 33.75, PR-5a 34.5, PR-4c 35.25, PR-a-final 36.25, PR-5b 39.5, PR-5c 40.25, PR-6K 42.0, PR-4d 43.0, PR-R3 43.75, PR-records 45.25, PR-hooks 47.0, PR-residual/R5 47.75, PR-R4 49.25, PR-config 52.0, PR-release 59.25. The streams still run unregistered until the program is registered after PR-P3; the registration (about 2 h, section 4) is off the path. The section 6 YAML is changed by revision 7 only in the `unblock` strings of R2.1, R2.2, R2.3 and R4.1 (below): its `done`, `streams`, `edges` and `groups` are the registration record and are re-based when the program is registered; three notes for that day: (1) task F1b (provisional id, a class S task of stream `a`) is new, and so is 6E.3b (the `escape_cost` part of loopstats, class S, a task of `records` after PR-2c3), so the YAML gains both; (2) task 1t.1 rides PR-a-final, not a PR of its own; (3) the `groups` windows are recomputed from the revision 7 times below. The `unblock` strings of the YAML for R2.1, R2.2, R2.3 and R4.1, rewritten by revision 7, name the consumed sub-block's merge (`merged:hooks/5a`, `merged:records/5b` and `/5c`, `merged:records/6E`, PR-loopstats), as the plan's "Program grouping for v0.1" states it (plan review 3, R3-2), so the starts of R2.1 (43.25), R2.2, R2.3 and R4.1 (44.5) keep their figures (Decision below) and the path stays 60.0 h.

- Withdrawn 2026-11-17 by the controller: it contradicted design 5.2 (plan review 2, R2-2)
- Decision (owner delegation 2026-11-09): stream `config`'s V runs after PR-config, beside `release` -- why: V runs after the stream's last block and no on-demand PR waits for it, for every stream alike (the rule above: stream a's V waits for PR-P3, `package`'s for PR-package, `runtime`'s for PR-runtime, `hooks`' for PR-R3, `records`' for PR-6K); PR-config is on demand (consumer `release` 6R.1; its gate holds no verifier, PV2:5.2) and carries only 4e and R2 (4c has PR-4c, 4a and 4d PR-4d, 4b and R4 PR-R4), so every block of `config` merges on demand and a defect V finds goes in a small follow-up PR, opened only if V finds one, which is then `config`'s final PR (PV2:5.2); 6R.1 waits for PR-config's merge (P:4799) and not for `config`'s V -- cost if wrong: V (1.5 h) goes before PR-config, +1.5 h on the path (60.0 to 61.5 h)
- Decision (owner delegation 2026-11-09): PR-6E (ready at 21.5), PR-5a (ready at 32.0) and PR-4c (ready at 17.0) merge in the gap after PR-P3 (33.75, 34.5, 35.25), not as soon as they are ready -- why: a merge between PR-P2's cut (16.0) and PR-P3's update costs the chain a clean update of 0.25 h (PR-P2 and PR-P4 carry no U in their figures), their consumers start at 43.25 (R2.1) and 44.5 (R2.2, R2.3), and `release` (PR-4c's consumer) starts at 52.25; the later consumed sub-blocks (5b, 5c, 6K, R3, 4d, R4) are ready after PR-a-final and merge U + T after the PR before them -- cost if wrong: PR-6E merged when ready (22.25) or PR-4c merged when ready (17.75) puts a U 0.25 into PR-P2, +0.25 h on the path (60.0 to 60.25 h)
- Decision (owner delegation 2026-11-09): the starts of R2.1 (43.25), R2.2 and R2.3 (44.5) and R4.1 (44.5) are kept at their first-draft figures although the PRs they consume merge earlier (PR-5a 34.5, PR-6E 33.75, PR-5b 39.5, PR-5c 40.25, PR-loopstats 9.5) -- why: R2.1 at 34.75 would put the window PW6 at 28 agents, over the cap of 25 (section 6.2), R2.2 and R2.3 follow R2.1's end (44.25 + 0.25) and R4.1 the 4b end (44.25 + 0.25) -- cost if wrong: none on the path, R2 and R4 end earlier

| PR | stream, mark | starts | timeline (sum -> h from t = 0) | merged at |
|---|---|---|---|---|
| PR-package (3d.1, Rq-4-1) | `package`; on demand (consumers: `config` 4a.2, 4d.1, R2.1; `residual` R5.1; `hooks` 3b.2, 3c; edges 3d.1 -> 4a.2, 4d.1, R2.1, R5.1) | 3.5 (PR-2b1 3.25 + cut 0.25; Q-PLP-1 (a)) | 3d.1 and Rq-4-1 3.5 + 2.5 = 6.0; U 0.25 + R 1.0 from 7.75 (PR-2c3's merge) = 9.0; clean U 0.25 + T 0.5 after PR-2c1 (10.25) -> 11.0; V 1.0 + 0.5 = 1.5 after the merge -> 12.5, off the path | **11.0** |
| PR-loopstats (6E.3) | `records`; on demand (consumers: `config` R2.3 and R4.1; edges 6E.3 -> R2.3 and 6E.3 -> R4.1) | 0 | 6E.3 (M) 0 + 2.0 = 2.0; U 0.25 + R 1.0 + T 0.5 = 1.75 from PR-2c3 (7.75) -> 9.5; 6E.3b (`escape_cost`, S) 9.75 + 1.0 = 10.75 rides PR-6E | merged as #22 (`a128a39`, 2026-11-17, observed; the schedule keeps its figure, t = 0 does not move): **9.5** |
| PR-runtime (3a.1 done, 3a.2) | `runtime`; on demand (consumers: `hooks` 3b.2, 3c.1, 3c.2, R3.1; `records` 6K.2; `residual` R5.1) | 24.75 (PR-P2 24.5 + 0.25; M1-M10) | 3a.2 (L) 24.75 + 3.0 = 27.75; R 1.0 -> 28.75; clean U 0.25 + T 0.5 after PR-P4 (30.25) -> 31.0; V 1.5 after the merge -> 32.5, off the path | **31.0** |
| PR-5a (5a.1-5a.3) | `hooks`; on demand (consumer: `config` R2.1, edge 5a.3 -> R2.1); 3b.1 is on the stream branch before this PR is cut (`3194b4f` on `20261110-v01/hooks/main`, not on `main`), so it carries 3b.1 | 24.75 (PR-P2 24.5 + 0.25) | 5a.1-5a.3 24.75 + 6.0 = 30.75; R 1.25 (5a and 3b.1) -> 32.0; clean U 0.25 + T 0.5 after PR-6E (33.75) -> 34.5 | **34.5** |
| PR-R3 (3b, 3c, R3.1, R3.2) | `hooks`; on demand (consumer: `release` 6R.1, edge R3.2 -> 6R.1); cut from the stream branch after the 3b and 3c ends, so it carries 3b (3b.2, 3b.3; 3b.1 went with PR-5a) and 3c (a work branch is never rebased; 5a is already merged in PR-5a) | 3b.1 done (L:868); 3b.2 from 31.25; R3 at 37.5 (the 3b and 3c ends) | 3b.2 (L) from 31.25 (PR-runtime 31.0 + 0.25) to 34.5, its gitinfo and githooks part, the last 1.25 h, 33.25 + 1.25 = 34.5 (PR-P3 33.0 + 0.25); 3b.3 34.5 + 2.0 = 36.5, 3b end -> 37.5; 3c.1 \|\| 3c.2 34.5 + 2.0 = 36.5, 3c end -> 37.5; R3.1 \|\| R3.2 37.5 + 2.0 = 39.5; R 1.25 (3b, 3c and R3) -> 40.75; clean U 0.25 + T 0.5 after PR-4d (43.0) -> 43.75 | **43.75** |
| PR-hooks (V's fixes) | `hooks`; stream final PR (V's fixes only: 3b and 3c went with PR-R3 and 5a with PR-5a, so it is a small follow-up PR, opened only if V finds a defect; its slot is kept, conservative, because the plugin enablement, Q-PLP-4 (a), follows it) | after V | V after PR-R3 (43.75) 1.5 -> 45.25; U 0.25 + R 1.0 + T 0.5 = 1.75 -> 47.0; after PR-records (45.25): clean U 0.25 + T 0.5 = 0.75 -> 46.0, the lesser | **47.0** |
| PR-6E (6E.1, 6E.2, 6E.3b) | `records`; on demand (consumers: `config` R2.3, edge 6E.2 -> R2.3; `release` 6R.1, edge 6E.2 -> 6R.1); 6E.3b is on the stream branch before this PR is cut, so it carries it | 6E.3b at 9.75 (PR-loopstats 9.5 + 0.25); 6E.1 at 16.0 (PR-P1 15.75 + 0.25) | 6E.3b (`escape_cost`, S) 9.75 + 1.0 = 10.75; 6E.1, 6E.2 serial 16.0 + 4.0 = 20.0; R 1.5 (6E and 6E.3b) -> 21.5; clean U 0.25 + T 0.5 after PR-P3 (33.0, the gap after it, Decision above) -> 33.75 | **33.75** |
| PR-4c (4c.1, 4c.2) | `config`; on demand (consumer: `release` 6R.2 `Consumes:` line, `managed.put_block` and `templates.render` of Tasks 4c.1-4c.2; D7's `Consumes:` clause) | M-B4-1 11.0 (PR-package) | M-B4-1 11.0 + 0.5 = 11.5; 4c.1 + 4c.2 11.5 + 4.5 = 16.0; R 1.0 -> 17.0 (the 4c end, which gates 4d.1); clean U 0.25 + T 0.5 after PR-5a (34.5, the gap after PR-P3, Decision above) -> 35.25 | **35.25** |
| PR-5b (R1, 5b.1, 5b.2) | `records`; on demand (consumer: `config` R2.2, edge 5b.2 -> R2.2); it carries R1, which is on the stream branch before 5b is cut (the R1 end, 32.5, is before the 5b group's cut at 33.25) | R1.1 at 30.5 (PR-P4 30.25 + 0.25); 5b at 33.25 (PR-P3 33.0 + 0.25) | R1.1 30.5 + 1.0 = 31.5, R1 end -> 32.5; 5b \|\| 5c (two groups) 33.25 + 4.0 = 37.25; R 1.5 (R1 and 5b) -> 38.75; after PR-a-final (36.25): clean U 0.25 + T 0.5 = 0.75 -> 39.5 | **39.5** |
| PR-5c (5c.1, 5c.2) | `records`; on demand (consumer: `config` R2.2, edge 5c.2 -> R2.2); R1 went with PR-5b, so it carries 5c only (the 5c end still waits for the R1 end) | 5c at 33.25 (PR-P3 33.0 + 0.25) | 5c 33.25 + 4.0 = 37.25; R 1.0 -> 38.25; after PR-5b (39.5): clean U 0.25 + T 0.5 = 0.75 -> 40.25 | **40.25** |
| PR-6K (6K.1, 6K.2) | `records`; on demand (consumer: `release` 6R.1, edge 6K.2 -> 6R.1) | 6K.1 at 16.0 (PR-P1 15.75 + 0.25); 6K.2 at 38.25 (after merged:runtime and PR-P3; held to the end of PR-5c's R, when a slot of the stream's 4 frees, section 6.2) | 6K.1 16.0 + 2.0 = 18.0; 6K.2 38.25 + 2.0 = 40.25; R 1.0 -> 41.25; after PR-5c (40.25): clean U 0.25 + T 0.5 = 0.75 -> 42.0 | **42.0** |
| PR-records (V's fixes) | `records`; stream final PR (V's fixes only: R1 went with PR-5b and 6E.3b with PR-6E, so it is a small follow-up PR, opened only if V finds a defect; its slot is kept, conservative) | after V | V after PR-6K (42.0) 1.5 -> 43.5; U 0.25 + R 1.0 + T 0.5 = 1.75 -> 45.25 (PR-R3, 43.75, merges before it: 44.5 is the lesser) | **45.25** |
| PR-residual/R5 (R5.1) | `residual`; stream final PR (nothing consumes R5.1) | 38.25 (held to the 5b/5c end, wave rule, section 6.2) | R5.1 (S) 38.25 + 1.0 = 39.25; R 1.0 -> 40.25; V 1.5 -> 41.75; waits for the enablement (after PR-hooks 47.0 and every live branch's update, Q-PLP-4 (a)); the first merge after it: U 0.25 + T 0.5 = 0.75 after PR-hooks (47.0) -> 47.75 | **47.75** |
| PR-4d (4a, 4d) | `config`; on demand (consumer: `release` 6R.1 `Consumes:` line, `init` of Task 4d.1; D7's `Consumes:` clause); it carries 4a, which is on the stream branch before this PR is cut and not yet merged | 4a.1 at 24.75 (PR-P2 24.5 + 0.25); 4d.1 at 33.25 (PR-P3 33.0 + 0.25) | 4a.1 24.75 + 2.0 = 26.75, 4a.2 -> 28.75, 4a end -> 29.75; 4a.3 \|\| 4b.1 29.75 + 2.5 = 32.25 (the 4b group, which rides PR-R4); 4d.1-4d.3 33.25 + 7.0 = 40.25, 4d end -> 41.25 (the gate of 4e in the stream branch, kept; R runs from the tasks' end and covers it); U 0.25 + R 2.0 (4a and 4d) -> 42.5; T 0.5 -> 43.0 (after PR-6K, 42.0: 42.75 is the lesser; PR-4d merges before PR-R3, whose queue place is after it) | **43.0** |
| PR-R4 (4b, R4.1) | `config`; on demand (consumer: `release` 6R.1, edge R4.1 -> 6R.1); cut from the stream branch with 4b on it, so it carries 4b (4a and 4d went with PR-4d, 4c with PR-4c) | 4b.2 at 41.25 (held to the 4d end); R4.1 at 44.5 (the 4b end 44.25 + 0.25; PR-loopstats merged at 9.5, #22) | 4b.2 41.25 + 2.0 = 43.25, 4b end -> 44.25; R4.1 44.5 + 2.0 = 46.5; U 0.25 + R 2.0 (4b and R4) -> 48.75; T 0.5 -> 49.25 (after PR-residual/R5, 47.75: 48.5 is the lesser) | **49.25** |
| PR-config (4e, R2) | `config`; on demand (consumer: `release` 6R.1, edge 4e.3 -> 6R.1); it carries what no earlier PR carried (4e and R2), so every block of `config` has merged on demand once it merges and V's fixes go in a small follow-up PR, which is then the stream's final PR | 4e.1 at 41.25 (the 4d end) | 4e.1-4e.3 41.25 + 7.0 = 48.25; R2.1 43.25 + 1.0 = 44.25 (start kept, Decision above; it needs PR-5a 34.5 and PR-package 11.0); R2.2, R2.3 serial 44.5 + 2.0 = 46.5 (R2.1's end 44.25 + 0.25; they need PR-5b 39.5, PR-5c 40.25 and PR-6E 33.75), R2 end -> 47.5; Rq commits 48.25 + 1.0 = 49.25; U 0.25 (it takes PR-R4, 49.25) + R 2.0 + T 0.5 = 2.75 -> 52.0; V 1.5 after the merge, beside `release` (Decision above) -> 53.5, off the path | **52.0** |
| PR-release (6R) | `release`; stream final PR | 52.25 (PR-config 52.0 + 0.25; after every other stream, P:4799) | 6R.1 52.25 + 2.0 = 54.25; 6R.2 54.25 + 2.0 = 56.25; final review R 1.0 -> 57.25; V 1.5 -> 58.75; T 0.5 -> 59.25 (no U: nothing merges after its cut); 6R.3 (the tag on the owner's word) 0.75 -> 60.0 | **59.25**, tag **60.0** |

Slack of the program chains against the Rq commits (48.25): R2 ends 47.5 (0.75 h); PR-R4 merges 49.25, as PR-config's update starts (49.25), so it has no slack: its chain (4b.2 from the 4d end 41.25, the 4b end 44.25, R4.1 44.5 to 46.5, R 2.0 with U and T) ties with the Rq commits, a second zero-slack chain of the same 60.0 h (plan review 3, R3-3); the merges before it in the queue (PR-4d 43.0, PR-R3 43.75, PR-records 45.25, PR-hooks 47.0, PR-residual/R5 47.75) can each slip at least 0.75 h before PR-R4's queue term (the PR before it + 0.75, binding from 48.5) binds. PR-4c (35.25) and PR-4d (43.0) are off the path: PR-4c is held in the gap after PR-P3, and PR-4d merges 6.25 h before PR-config's update. PR-runtime has 0.25 h (section 5). 4c has 16.0 h. `config`'s V (52.0 to 53.5) ends 2.75 h before `release`'s V starts (56.25). Revision 6's sub-block 4b rule (4a.3 and 4b.1 start at the 4a end, 4b.2 held to the 4d end by the wave cap) is kept: 4b.2 starts at 41.25, as revision 6's started at the 4d end (44.25).

Revision 6 (history): one row per program PR, in the merge-queue order, in h from t = 0 (PR-1d2's merge, 2ab84d6; there is no S). Each figure is the launch schedule's less 3.75 h (the Decision of section 4's revision 6 table), except the t = 0 starters (3a.1 and 3b.1 0-2.0, 4c 0-4.5 with its end to 5.5, L:814). The clean update (line U of section 1) applies: a queued PR's U is 0.25 h and, after the final review, re-runs only the gates; R is 1.0 h (hooks 1.25, records 1.5, config 2.0 for more sub-blocks) and T 0.5 h. The merge-queue order is: PR-B2, PR-1d2 (t = 0), PR-2b1 3.0, PR-unicode 3.75, PR-docs6 4.5, PR-package 7.25, PR-2b-rest 8.75, PR-2c3 10.75, PR-2c1 12.75, PR-tests 13.5, PR-P1 18.75, PR-P2 27.5, PR-P4 33.25, PR-runtime 34.0, PR-P3 36.0, PR-hooks 44.25, PR-records 45.5, PR-residual/R5 as the first merge after the enablement (45.0 at the earliest; its place against PR-records is set by when the owner enables the plugin; the launch schedule's order is records, then R5 after the enablement, and its 45.0 and PR-records' 45.5 are 0.5 h apart, under the 0.75 h spacing above: with records first at 45.5, R5 merges at 46.25; with R5 first at 45.0, records merges at 45.75 and R2.2 and R2.3 still start at 45.75 and R4.1 at the 4b end, 47.25; either way PR-config and the path do not move, section 7's slack), PR-config 55.0, PR-release 61.5. The streams run unregistered until the program is registered after PR-P3 (about 40.25 h, section 4). Sub-block 4b. The launch schedule starts 4a.3 and 4b.1 at 31.75, before the 4a end (32.75); the plan's owner-answer text (Q-SPD-3 (a), L:795; plan section "Program grouping for v0.1") says "4b and 4d start after the 4a end in the stream branch". Decision (owner delegation 2026-11-09): this record follows the plan: 4a.3 and 4b.1 start at the 4a end, 32.75 (4a.3 32.75-35.25, 4b.1 32.75-35.25, each the launch schedule's 2.5 h for the pair; 4b.2 could then run 35.25-37.25, after 4a.3, 4b.1 and PR-P4 at 33.25, and the 4b end 37.25-38.25, each 1.0 h later than before) -- the plan's rule is the owner's answer, the launch schedule's overlap is a derived figure -- cost if wrong: the 4b start moves back 1.0 h, nothing on the path. The shifted 4b.2 and its end would run 35.25-38.25, which makes PW5 27 at 37.25-38.25 (24 plus 4b's 3, section 6.2), over the cap of 25; so 4b.2 is held to 44.25 (PW6 has room), the 4b end is 47.25, and R4.1 (after the 4b end and PR-records) runs 47.25-49.25, end 50.25, 1.0 h before the Rq commits at 51.25 (R4 had 2.5 h); PR-config stays 55.0 and the path of section 7 does not move. The hold is a wave-start rule of the kind the launch schedule used to keep the peak at or under 25 -- cost if wrong: R4's slack 1.0 h instead of 2.5 h.

| PR | starts | merges after | timeline (h from t = 0) | merged |
|---|---|---|---|---|
| PR-package (3d.1, Rq-4-1) | 3.25, after PR-2b1 (Q-PLP-1 (a)) | PR-2b1, PR-docs6 | 3d.1 and Rq-4-1 3.25-5.75; R 1.0; T 0.5 (first program merge) | **7.25** |
| PR-runtime (3a.1, 3a.2) | 0 (3a.1) | PR-P4 | 3a.1 0-2.0; 3a.2 27.75-30.75 after PR-P2 (27.5) and M1-M10; the PR waits for PR-P4 (33.25); U + T 0.75 | **34.0** |
| PR-hooks (3b, 3c, 5a, R3) | 0 (3b.1) | PR-runtime, PR-package (3b.2, 3c); PR-P3 (3b.3) | 3b.1 0-2.0; 5a 27.75-33.75, end 34.75; 3b.2 34.25-37.25 (its gitinfo and githooks part after PR-P3, 36.0); 3b.3 37.25-39.25; 3b end 40.25; 3c 37.25-39.25, end 40.25; R3 40.25-42.25; U 0.25; R 1.25 h; T 0.5 | **44.25** |
| PR-records (R1, 5b, 5c, 6E, 6K) | 10.75 (6E.3, after PR-2c3) | PR-runtime (6K.2) | 6E.3 11.0-13.0; 6E.1 and 6E.2 19.0-23.0, 6E end 24.0; 6K.1 19.0-21.0; R1.1 33.5-34.5, R1 end 35.5; 5b and 5c 36.25-40.25, ends 41.25; 6K.2 40.25-42.25 (wave cap), 6K end 43.25; U 0.25; R 1.5 h; T 0.5 | **45.5** |
| PR-residual/R5 (R5.1, Q-BRV-1 (a)) | about 37.25 (after PR-P3) | PR-runtime, PR-package, PR-hooks and the enablement (Q-PLP-4 (a)) | R5.1 about 37.25-38.25; the PR waits for the enablement, which the owner gives after PR-hooks and every live branch's update; it is the first program merge after it, amending Q-BRV-3 (a) | **45.0 at the earliest** (46.25 behind PR-records at 45.5; with R5 at 45.0, PR-records moves to 45.75; off the path) |
| PR-config (4a-4e, R2, R4) | 0 (4c.1, after M-B4-1) | PR-package (4a.2), PR-2c3 (4a.2, 4a.3), PR-hooks (R2.1), PR-records (R2.2, R2.3, R4.1) | 4c 0-4.5, end 5.5; 4a.1 27.75-29.75; 4a.2 29.75-31.75; 4a end 32.75; 4a.3 32.75-35.25, 4b.1 32.75-35.25; 4d 36.25-43.25, end 44.25; 4b.2 44.25-46.25, 4b end 47.25 (held to 44.25 by the wave cap); 4e 44.25-51.25; R2.1 44.5-45.5; R2.2, R2.3 serial 45.75-47.75; R2 end 48.75; R4.1 47.25-49.25, end 50.25; Rq commits 51.25-52.25; U 0.25; R 2.0 h; T 0.5 | **55.0** |
| PR-release (6R) | after all of the above | all | 6R.1 55.25-57.25; 6R.2 57.25-59.25; E 1.5 to 60.75; 6R.3 (tag on the owner's word) 0.75 h (revision 5 had 1.0 h) | **61.5** |

### 6.2 Program waves (cap 25; review F-BDr-9; revision 6 is history, revision 7 above it)

**Revision 7 waves (cap 25 agents; per-stream child cap 4).** The counting rule is the rule below with V counted as 2 (verifier and fix-diff reviewer): 1 per stream controller and per group sub-controller, 2 per active task, end, R, T and V; a stream waiting for a merge counts 0 (`hooks` counts from 24.75, `config` from 11.0, `package` from 3.5). The docs roll-in (another controller, L:869; groups A-F) is not scheduled here; until its PR merges (11.75) it is counted at its own cap, 9 (1 controller and at most 4 children, each counted 2). A stream's direct children are its group sub-controllers (1 each) and the tasks or ends it runs itself (2 each); the maximum in any window is 4, at the cap of 4 (`records` at 33.25-33.75: the 5b and 5c groups with PR-6E's end; `hooks` at 36.5-37.5: the 3b and 3c ends 2 + 2; `records` at 37.25-38.25: PR-5b's R and PR-5c's R 2 + 2; `config` at 40.25-41.25: the 4d end and PR-4d's end 2 + 2, at 41.25-43.0: the 4b.2 and 4e groups with PR-4d's end, at 43.25-44.25: the 4b end 2, the 4e group and the R2.1 group, at 46.5-47.5: the 4e and R2 groups with PR-R4's end, and at 48.25-49.25: the Rq commits 2 and PR-R4's end 2; the other windows have at most 3, `a` at 1.75-2.75 among them: F1b group 1 and PR-2b1's end 2). Task 6K.2 is held to 38.25, when PR-5c's R ends (started at 37.25 it would put `records` at 5 with PR-5b's and PR-5c's R: 1 + 2 + 2). Peak counts are the sum of the live rows at the stated time (a session script, not kept, over the revision 7 figures of sections 4 and 6.1).

| wave | window (h from t = 0) | what runs at the peak | agents (peak) |
|---|---|---|---|
| PW1 | 0 to 1.5 | stream a 3 (controller 1, PR-unicode's final review 2); records 4 (controller 1, evidence group 1, task 6E.3 2); docs roll-in 9 | **16** (7 without the roll-in) |
| PW2 | 1.5 to 7.75 | at 1.75: stream a 6 (controller 1, F1b group 3, PR-2b1's end 2); records 4 (to 3.25); docs roll-in 9 = 19. At 6.0: stream a 7 (controller 1, G2 group 3, 2c.1 group 3); package 0 (its tasks end at 6.0 and its update waits for PR-2c3's merge at 7.75); docs roll-in 9 = 16 | **19** |
| PW3 | 7.75 to 11.75 | at 8.0: stream a 7 (controller 1, 2c.1 group 3, P1 group 3); package 3 (PR end 2); records 4 (controller 1, evidence group 1, PR-loopstats' end 2); docs roll-in 9 | **23** |
| PW4 | 11.75 to 24.5 | at 16.0: stream a 7 (controller 1, 1t.1 group 3, P2.1 group 3); records 7 (controller 1, 6E group 3, 6K.1 group 3); config 4 (controller 1, M-B4-1 and 4c group 3); package's V (controller 1, V 2) adds 3 at 11.75-12.5, far under the peak | **18** |
| PW5 | 24.5 to 33.0 | at 31.25: stream a 3 (controller 1, PR-P3's update 2); runtime 3 (controller 1, V 2 from 31.0); hooks 6 (controller 1, PR-5a's review 2, 3b.2 group 3); records 4 (controller 1, R1 group 3); config 6 (controller 1, 4b group with 4a.3 and 4b.1, 5); at 30.5 the count is 21 (hooks 4, runtime 3 with PR-runtime's end 2, stream a 4) | **22** |
| PW6 | 33.0 to 43.0 | at 34.5: stream a 3 (controller 1, PR-a-final's end 2); hooks 9 (controller 1, 3b.3 group 3, 3c group with two tasks 5); records 7 (controller 1, 5b group 3, 5c group 3); config 6 (controller 1, 4d group 3, PR-4c's end 2 from 34.5 to 35.25). `residual` R5.1 is held to 38.25, where 5b and 5c end, so that this window stays at 25 (with R5.1 at 33.25 it would be 28, over the cap); the PR ends of PR-6E (33.0-33.75), PR-5a (33.75-34.5) and PR-4c (34.5-35.25) take 2 agents each, one at a time, and keep the window at 25 (20 at 33.25, 25 at 34.5); the later PR ends (PR-5b 37.25-39.5, PR-5c 37.25-38.25 and 39.5-40.25, PR-6K 40.25-42.0, PR-4d 40.25-43.0) fall where the window counts at most 19 (at 38.5: hooks 6, records 6 (controller 1, the 6K.2 group 3, PR-5b's end 2), residual 3, config 4); R2.1 started at 34.75 would make the window 28 (Decision of section 6.1) | **25** |
| PW7 | 43.0 to 52.0 | at 43.25: hooks 3 (controller 1, PR-R3's end 2, 43.0-43.75); records 3 (controller 1, V 2, to 43.5); config 10 (controller 1, 4b.2 group 3, 4e group 3, R2 group 3); from 44.5 the R4 group replaces 4b.2: 16 | **16** |
| PW8 | 52.0 to 60.0 | release 3 (controller 1, 6R.x or V or its end 2) from 52.25; config 3 (controller 1, V 2) from 52.0 to 53.5 | **6** |

All revision 7 waves are at or under the measured 25; PW6 is the tightest, at the cap (25, with PR-4c's end at 34.5-35.25), and PW3 is next (23, with the docs roll-in counted at its cap). The roll-in's real count is not known; if it exceeded 11 agents, PW3 would pass 25 and PR-package's end (3 agents; off the path, 2.25 h of slack) would be the work held. Launches past the limit are refused, not queued (P:862).

**Revision 6 waves (history).**

Each count is the peak of the agents live in the window: 1 per stream controller and per group sub-controller (a stream waiting for a merge is stopped and counts 0), 2 per active task, per sub-block end and per PR end, streams `a` and `b` and the other pre-program work as in section 4 (revision 6). The windows are the launch schedule's windows less 3.75 h (section 4's rule). PW1 to PW3 are recounted, because revision 6 adds work to them: PW1 for the t = 0 starters (L:814), PW2 (22; the launch schedule's window had 18) for stream b, PR-docs6, PR-unicode's end and 4c.2, PW3 (20; the launch schedule's window had 17) for PR-tests (12.75-13.5) and for records starting at 10.75 after PR-2c3. PW4 to PW7 are the launch schedule's counts (the peaks counted there, with the same rule), rechecked for the 4b change below: with 4b starting after the 4a end, PW4's config count does not rise (4a end 2 and a controller and sub-controller 2 at 31.75-32.75, config 4; then 4a.3 and 4b.1 from 32.75 to 35.25, 2 each with the controller and the sub-controller, config 6, within the row's 4-7; after PR-runtime merges at 34.0 the window is at most stream a 7, hooks 6, records 4 and config 6, 23), and 4b.2 with its end (3 agents: the task or end 2 and its sub-controller 1) moves out of PW5: the launch schedule's 24 holds at 37.25-39.25 (hooks 10, records 7, config 4, residual 3), and 4b.2 or its end there would make 27. In PW6 the count of 13 keeps its config peak of 10 (4e, R2.2 and 4b.2 with their sub-controllers and the controller).
| wave | window | what runs | agents (peak) |
|---|---|---|---|
| PW1 | 0 to 3.0 | stream a 6 (controller 1, G0's end 2, G3 sub-controller 1, 1u.1 2); stream b 3 (L:814); PR-docs6 4 (plan and breakdown tasks, 2 each); runtime 4 (controller, 3a group, 3a.1); hooks 4 (controller, 3b group, 3b.1); config 4 (controller, 4c group, 4c.1) | **25** |
| PW2 | 3.0 to 10.75 | stream a 7 (controller, groups X and Y, their four task agents); G3's end 3; stream b 3; PR-docs6's end 2 (to 4.5); package 3 (controller, 3d.1); config's 4c.2 and end 4 (to 5.5) | **22** |
| PW3 | 10.75 to 27.5 | stream a up to 7 (2c.1, then P1, then P2); records up to 10 (6E.3, then 6E.1, 6E.2, 6K.1); PR-tests 3 (sub-controller, 1t.1) | **20** |
| PW4 | 27.5 to 36.0 | stream a (P3, P4 and their ends) 7; runtime 4 (3a.2); hooks (5a, then 3b.2) 4-6; config (4a, then 4b with two siblings) 4-7; records (R1) 4 | **24** (at about 33.25, i.e. 37.0 on the launch schedule's clock less 3.75) |
| PW5 | 36.0 to 44.25 | hooks (3b, 3c two groups) 10; records (5b, 5c, then 6K) 7-10; config (4d) 4; residual 3; registration from 40.25 at 2 | **24** |
| PW6 | 44.25 to 55.0 | config (4e, R2, R4, 4b.2 and its end, end) up to 10; the hooks and records ends 2-3 | **13** |
| PW7 | 55.0 to 61.5 | release = 1 | 6R.x = 2, 3 |

All waves are at or under the measured 25; PW1 is at it with the t = 0 starters, so no stream or task may be added to the first window. Launches past the limit are refused, not queued (P:862). If PR-docs6's two tasks are counted with a controller (5 instead of 4), PW1 is 26 and one of the t = 0 starters (4c.1, which waits for M-B4-1 in any case, L:814) starts later; the 25 is the count under the stated rule.

The program end is set by one chain, not by the merge queue: PR-2b1 (3.0) -> PR-2b-rest (8.75) -> PR-2c3 (10.75) -> PR-P1 (18.75) -> PR-P2 (27.5) -> PR-P3 (36.0) -> 4d.1-4d.3 and the 4d end (44.25) -> 4e.1-4e.3 (51.25) -> the Rq commits (52.25) -> PR-config (55.0) -> 6R.1, 6R.2, PR-release, 6R.3 (61.5), about 61.5 h from t = 0. The other chains have slack: R2 ends at 48.75, 2.5 h before the Rq commits start at 51.25 (the launch schedule's "about 5 h" for hooks to R2.1 and its "3.5 h" slack in Decisions 5, 8 and 9 do not follow from its own figures; the 2.5 h here does); R4.1 ends at 50.25 (4b.2 held to 44.25, section 6.1), 1.0 h before the Rq commits; PR-runtime, PR-residual/R5 and PR-package are off the path; registration (about 2 h from about 40.25) and PR-unicode, PR-docs6 and PR-tests are off it. The hooks and records PRs merge at 44.25 and 45.5, before the Rq commits. The plugin is enabled after PR-hooks and every live branch's update (Q-PLP-4 (a)).

---

## 7. Critical path and estimate (draft's unit costs)

**Revision 7 (2026-11-17, process v2; t = 0 = 2026-11-17 14:00 SAST): PR-unicode (1.5) -> PR-2b1 (3.25) -> PR-2b-rest (5.5) -> PR-2c3 (7.75) -> P1.1-P1.3 / PR-P1 (15.75) -> P2 / PR-P2 (24.5) -> the P3 tasks (31.25) -> PR-P3 (33.0) -> 4d.1-4d.3 and the 4d end (41.25) -> 4e.1-4e.3 (48.25) -> the Rq commits (49.25) -> PR-config (52.0) -> 6R.1, 6R.2 (56.25) -> PR-release's final review (57.25) -> stream `release`'s V (58.75) -> PR-release (59.25) -> 6R.3, the tag (60.0) = 60.0 working hours from t = 0.** Stream `config`'s V (52.0 to 53.5) runs beside `release` and is off the path (section 6.1 Decision).

How the 60.0 h adds up (forward, each step its unit cost; every figure of the chain):
1.5 (PR-unicode R 1.0 + T 0.5) + 1.75 (PR-2b1) + 2.25 (PR-2b-rest) + 2.25 (PR-2c3) = 7.75; + 0.25 (cut) + 6.0 (P1.1-P1.3) + 1.75 (PR-P1) = 15.75; + 0.25 + 7.0 (P2.1 4.0 + P2.2 \|\| P2.3 3.0) + 1.5 (R + T) = 24.5; + 0.25 + 6.5 (P3 tasks) + 1.75 (PR-P3) = 33.0; + 0.25 + 7.0 (4d.1 3.0 + 4d.2 2.0 + 4d.3 2.0) + 1.0 (4d end) = 41.25; + 7.0 (4e.1 3.0 + 4e.2 2.0 + 4e.3 2.0) = 48.25; + 1.0 (Rq commits) = 49.25; + 2.75 (PR-config U 0.25 + R 2.0 + T 0.5) = 52.0; + 0.25 + 4.0 (6R.1 2.0 + 6R.2 2.0) = 56.25; + 1.0 (R) + 1.5 (V) + 0.5 (T) = 59.25; + 0.75 (6R.3) = 60.0.

Checked by a different route, backwards from the release (each step subtracted, ending at t = 0): 60.0 - 0.75 (6R.3) = 59.25; - 0.5 (PR-release T) = 58.75; - 1.5 (V release) = 57.25; - 1.0 (PR-release R) = 56.25; - 4.0 (6R.1, 6R.2) = 52.25; - 0.25 (cut) = 52.0; - 2.75 (PR-config) = 49.25; - 1.0 (Rq) = 48.25; - 7.0 (4e) = 41.25; - 1.0 (4d end) = 40.25; - 7.0 (4d) = 33.25; - 0.25 = 33.0; - 1.75 (PR-P3) = 31.25; - 6.5 (P3 tasks) = 24.75; - 0.25 = 24.5; - 1.5 (PR-P2 R + T) = 23.0; - 3.0 = 20.0; - 4.0 = 16.0; - 0.25 = 15.75; - 1.75 (PR-P1) = 14.0; - 6.0 (P1) = 8.0; - 0.25 = 7.75; - 2.25 (PR-2c3) = 5.5; - 2.25 (PR-2b-rest) = 3.25; - 1.75 (PR-2b1) = 1.5; - 1.5 (PR-unicode) = 0.0. A longest-path pass over the section 4 and 6.1 rows (a forward and a backward pass; a session script, not kept) gives the same 60.0 h and the zero-slack chain above, with PR-runtime (31.0) 0.25 h off it and a second zero-slack chain beside the 4e step: 4b.2 from the 4d end (41.25) + 2.0 + 1.0 (4b end) = 44.25, + 0.25 + 2.0 (R4.1) = 46.5, + 0.25 + 2.0 (R) + 0.5 = PR-R4 49.25, equal to the Rq commits' end (49.25), from which PR-config's U starts (section 6.1, plan review 3, R3-3).

By kind (they re-add to 60.0): tasks 6.0 + 7.0 + 6.5 + 7.0 + 7.0 + 1.0 + 4.0 = 38.5 (P1, P2, P3, 4d, 4e, Rq, 6R); sub-block end 1.0 (4d); PR ends 1.5 + 1.75 + 2.25 + 2.25 + 1.75 + 1.5 + 1.75 + 2.75 + 1.5 = 17.0 (PR-unicode, PR-2b1, PR-2b-rest, PR-2c3, PR-P1, PR-P2, PR-P3, PR-config, PR-release); V 1.5 (`release`; `config`'s V is off the path); cuts 5 x 0.25 = 1.25; the tag 0.75. 38.5 + 1.0 + 17.0 + 1.5 + 1.25 + 0.75 = 60.0.

Against revision 6 (61.5 h from its own t = 0): the chain from PR-P1 on is the same work; PR-2c3 is at 7.75 h from today's t = 0 (revision 6 had it at 10.75 from its t = 0), 3.0 h earlier, because PR-2b1 is built and reviewed, PR-2b-rest and PR-2c3 are built, and only their ends remain; the one V on the path adds 1.5 h (stream `release`; stream `config`'s V runs beside it, off the path); 61.5 - 3.0 + 1.5 = 60.0. The per-PR verifier removed from the PR ends saves nothing here because R keeps revision 6's figures (conservative, section 1); the other process v2 gains (no fix rounds past the verdict, no owner leave rounds, targeted commit gates) are not hours of this schedule.

Sensitivities (each stated, none applied): PR-unicode merged at 0.25 h (#21, section 4): -1.25 h, 58.75 h. Stream a's V before PR-P3, if the owner reads "final PR" as PR-P3: +1.5 h, 61.5 h (section 4, first Decision). Stream `config`'s V before PR-config (section 6.1 Decision): +1.5 h, 61.5 h. PR-2b1's update clean: -1.0 h, 59.0 h. PR-6E merged when ready instead of in the gap after PR-P3 (section 6.1 Decision): +0.25 h, 60.25 h. Counting an extra owner round or a usage-limit stop: not modelled (section 1).

### Roadmap to v0.1.0 (revision 7)

Milestones in order, in h from t = 0 (2026-11-17 14:00 SAST) with the arithmetic of each, and the calendar date under two readings. **24 h reading:** the work runs around the clock, date = t = 0 plus the h figure. **8 h reading:** 8 working hours per day, Monday to Friday, 09:00 to 17:00 SAST, no holiday, the 3 h left of Tuesday 2026-11-17 counted first (so t = 11.0 is Wednesday 17:00, t = 19.0 Thursday 17:00, and each further 8 h one more weekday). Neither reading models owner answers to owner-only questions or usage limits (sections 1 and 5). A milestone is the merge of the PR, or the end of the step named.

| milestone | h from t = 0 | arithmetic | 24 h reading | 8 h reading |
|---|---|---|---|---|
| t = 0 (the roll-in) | 0.0 | | Tue 17 Nov 14:00 | Tue 17 Nov 14:00 |
| PR-unicode merged (#21) | 1.5 | 0 + 1.0 + 0.5 | Tue 17 Nov 15:30 | Tue 17 Nov 15:30 |
| PR-2b1 (#17) merged: `run_all` | 3.25 | 1.5 + 0.25 + 1.0 + 0.5 | Tue 17 Nov 17:15 | Wed 18 Nov 09:15 |
| PR-2b-rest merged: hooks shims, CI workflow | 5.5 | 3.25 + 0.25 + 0.5 + 1.0 + 0.5 | Tue 17 Nov 19:30 | Wed 18 Nov 11:30 |
| PR-2c3 merged: `config/2`, `check dispatch` | 7.75 | 5.5 + 0.25 + 0.5 + 1.0 + 0.5 | Tue 17 Nov 21:45 | Wed 18 Nov 13:45 |
| PR-loopstats merged | 9.5 | 7.75 + 0.25 + 1.0 + 0.5 | Tue 17 Nov 23:30 | Wed 18 Nov 15:30 |
| PR-package merged: plugin manifests | 11.0 | 9.5 + 0.75 + 0.75 (PR-2c1 at 10.25) | Wed 18 Nov 01:00 | Wed 18 Nov 17:00 |
| PR-P1 merged | 15.75 | 7.75 + 0.25 + 6.0 + 1.75 | Wed 18 Nov 05:45 | Thu 19 Nov 13:45 |
| PR-P2 merged | 24.5 | 15.75 + 0.25 + 7.0 + 1.5 | Wed 18 Nov 14:30 | Fri 20 Nov 14:30 |
| PR-P4 merged | 30.25 | 24.5 + 0.25 + 4.0 + 1.5 | Wed 18 Nov 20:15 | Mon 23 Nov 12:15 |
| PR-runtime merged | 31.0 | 30.25 + 0.25 + 0.5 | Wed 18 Nov 21:00 | Mon 23 Nov 13:00 |
| PR-P3 merged: merge and cleanup tools | 33.0 | 24.5 + 0.25 + 6.5 + 1.75 | Wed 18 Nov 23:00 | Mon 23 Nov 15:00 |
| PR-6E merged | 33.75 | 33.0 + 0.25 + 0.5 | Wed 18 Nov 23:45 | Mon 23 Nov 15:45 |
| PR-5a merged | 34.5 | 33.75 + 0.25 + 0.5 | Thu 19 Nov 00:30 | Mon 23 Nov 16:30 |
| PR-4c merged (`managed`, `templates`) | 35.25 | 34.5 + 0.25 + 0.5 | Thu 19 Nov 01:15 | Tue 24 Nov 09:15 |
| stream a's verifier done (after its final review) | 35.5 | 33.0 + 1.0 + 1.0 + 0.5 | Thu 19 Nov 01:30 | Tue 24 Nov 09:30 |
| PR-a-final merged (stream a ends) | 36.25 | 35.5 + 0.25 + 0.5 | Thu 19 Nov 02:15 | Tue 24 Nov 10:15 |
| PR-5b merged (carries R1) | 39.5 | 37.25 + 1.5 + 0.25 + 0.5 | Thu 19 Nov 05:30 | Tue 24 Nov 13:30 |
| PR-5c merged | 40.25 | 39.5 + 0.25 + 0.5 | Thu 19 Nov 06:15 | Tue 24 Nov 14:15 |
| 4d end (`init`, `doctor`) | 41.25 | 33.0 + 0.25 + 7.0 + 1.0 | Thu 19 Nov 07:15 | Tue 24 Nov 15:15 |
| PR-6K merged | 42.0 | 40.25 + 1.0 + 0.25 + 0.5 | Thu 19 Nov 08:00 | Tue 24 Nov 16:00 |
| PR-4d merged (`init`, `doctor`; carries 4a) | 43.0 | 40.25 + 0.25 + 2.0 + 0.5 | Thu 19 Nov 09:00 | Tue 24 Nov 17:00 |
| PR-R3 merged | 43.75 | 43.0 + 0.25 + 0.5 | Thu 19 Nov 09:45 | Wed 25 Nov 09:45 |
| PR-records merged (V's fixes only) | 45.25 | 42.0 + 1.5 + 0.25 + 1.0 + 0.5 | Thu 19 Nov 11:15 | Wed 25 Nov 11:15 |
| PR-hooks merged (V's fixes only) | 47.0 | 43.75 + 1.5 + 0.25 + 1.0 + 0.5 | Thu 19 Nov 13:00 | Wed 25 Nov 13:00 |
| PR-residual/R5 merged (interim skill removed) | 47.75 | 47.0 + 0.25 + 0.5 | Thu 19 Nov 13:45 | Wed 25 Nov 13:45 |
| 4e end (`upgrade`, adoption, fixtures) | 48.25 | 41.25 + 7.0 | Thu 19 Nov 14:15 | Wed 25 Nov 14:15 |
| Rq commits done | 49.25 | 48.25 + 1.0 | Thu 19 Nov 15:15 | Wed 25 Nov 15:15 |
| PR-R4 merged (carries 4b) | 49.25 | 46.5 + 0.25 + 2.0 + 0.5 | Thu 19 Nov 15:15 | Wed 25 Nov 15:15 |
| PR-config merged | 52.0 | 49.25 + 0.25 + 2.0 + 0.5 | Thu 19 Nov 18:00 | Thu 26 Nov 10:00 |
| stream `config`'s V done (beside `release`) | 53.5 | 52.0 + 1.0 + 0.5 | Thu 19 Nov 19:30 | Thu 26 Nov 11:30 |
| 6R.2 done (profiles end to end) | 56.25 | 52.0 + 0.25 + 2.0 + 2.0 | Thu 19 Nov 22:15 | Thu 26 Nov 14:15 |
| stream `release`'s V done (after its final review) | 58.75 | 56.25 + 1.0 + 1.0 + 0.5 | Fri 20 Nov 00:45 | Thu 26 Nov 16:45 |
| PR-release merged | 59.25 | 58.75 + 0.5 | Fri 20 Nov 01:15 | Fri 27 Nov 09:15 |
| **v0.1.0 tag (6R.3)** | **60.0** | 59.25 + 0.75 | **Fri 20 Nov 02:00** | **Fri 27 Nov 10:00** |

Total: 60.0 working hours from 2026-11-17 14:00 SAST. At 24 h a day that is 2 days 12.0 h, so the tag is Friday 2026-11-20 about 02:00. At 8 working hours a day it is 3 + 7 x 8 + 1.0 = 60.0, that is the 3 h of Tuesday, seven full weekdays (Wednesday 18 to Thursday 26, skipping the weekend) and 1.0 h of Friday 27, so the tag is Friday 2026-11-27 about 10:00 (Wednesday 2026-11-25 if weekends also work 8 h). PR-unicode's observed merge at 0.25 h (section 4) would move every figure after PR-2b1 earlier by 1.25 h (58.75 h: Friday 2026-11-20 00:45, or Thursday 2026-11-26 16:45). PR-docs-v2 is a gap in the queue, not a milestone of the path.

**Revision 6 (history; 2026-11-14, t = 0 at PR-1d2's merge, 2ab84d6; cuts 1 and 2; sub-block 4a split by Q-SPD-3 (a); Task 2c.3 pulled forward; Q-PLP-1 (a), -3 (a), -4 (a), -5 (a)): PR-2b1 (3.0) -> 2c.2 -> 2c.3 (8.25) and 2b.2, 2b.3 / PR-2b-rest (8.75) -> PR-2c3 (10.75) -> P1 (18.75) -> P2 with P2.1 at L + 1 h (27.5) -> P3 with Rq-5-4 (36.0) -> 4d.1-4d.3 and the 4d end (44.25) -> 4e.1-4e.3 (51.25) -> the Rq commits (52.25) -> PR-config (55.0) -> 6R.1, 6R.2, PR-release, 6R.3 (61.5) ≈ 61.5 working hours from t = 0. Revision 5's path (93.0 h from 2026-11-02) is kept below as history.**

**Revision 5: PR-1c0 (2.5) -> the docs-only PR's tail (3.75) -> B2.1-B2.3 / PR-B2 (12.0) -> PR-1d's U and E (13.75) -> 2a.3's `GATES["claims"]` commit (O3) -> PR-D (15.5) -> 2b.1-2b.3 -> PR-2b (23.25) -> 2c.2 -> 2c.3 -> PR-2c (29.75) -> P1 (37.25) -> P2 with P2.1 at L + 1 h (45.75) -> P3 with Rq-5-4 (54.0) -> setup (56.0) -> 3a.1, 3a.2 / PR-runtime (S+6.75) -> R5.1 / PR-residual/R5 (S+9.5) -> the merge queue, each merge U + E after the one before: PR-cfg4 (S+11.25), -context, -evidence, -bash, -rules4, -tools, -checkpoint, -docs, PR-residual/R3, /R2, /R4, PR-init4 (S+30.5) -> 6R.1, 6R.2, PR-release, 6R.3 (S+37.0) ≈ 93.0 working hours.**

- Against revision 1 (80 h): +6.75 h. The added time comes from the L:387/L:389 waits, E09 (including 0.5 h for the store.py window, R2:F-BDr2-3) and E15, and is offset by Q-BD-8 (a) (no A-R6 PR, −2.25 h) and by folding 3d.2.
- The review's corrected figure was 90.75 h with D's old scope, and 87.25 h under its Q-BDr-1 (a). The review re-checked 86.25 h (review 2); the store.py window adds 0.5 h, giving 86.75 h. The remaining 0.5 h below the review's 87.25 h comes from 1c.3 running alongside 1c.2 in a group worktree. It is my scheduling choice; without it the path is 87.75 h.
- Revision 3 (session-resume revision, F-DR-6 and its reviews): +3.0 h, 89.75 h. Pre-program +0.75 h: +1.0 h because Task 1d.3 (M, after 1d.1) lengthens PR-1d, which updates after PR-B2 and merges at 12.5, and O3 holds PR-D to 14.25 (was 13.25); -0.25 h because PR-2c no longer needs a U (nothing merges after its cut), so it ends 6.5 h after PR-2b, not 6.75 h. Program +2.25 h (S+34.75 -> S+37.0): with every E after its PR's last U, the program's PRs, each cut before the merges it follows, form a merge queue in which, from PR-residual/R5 (S+9.5, after its own update following PR-runtime) on, each merge follows the one before by U + E = 1.75 h, to PR-init4 at S+30.5. Task R5.1 is merged first after PR-runtime, as MS:715 ("removed once the plugin is enabled") and owner answer Q-BRV-1 (a) (L:555, "merged about S+8.25") put it, kept by owner answer Q-BRV-3 (a) at a cost of about 0.5 h: the shortest unforced order found merges R5 after PR-context (S+10.25) and ends at S+36.5 (beam search, an upper bound; wave cap unchecked). Revision 4 (owner answer Q-F80RR3-3 (a)): Task P2.1 is class L (3 h, not 2 h), since it also builds `merge.merged_errors` and three gitinfo functions (owner answer Q-F80W-21 (a)); P2.1 is on the critical path, so PR-P2 (43.5), PR-P4 (49.0), PR-P3 (51.75), S (53.75) and the total (90.75 h) each move +1.0 h, the program's S+ times are unchanged, and the waves keep their counts. The classes M for 1c0.2, 1d.3 and R4.1 and S for R5.1 are this revision's estimates. Revision 5 (owner answers Q-DOCS-1 (e), Q-RD8b-1 (a), Q-RD8b-2 (b), Q-RD8c-1 (b)): Task 1c0.2 and the docs-only PR's final review and verifier run before PR-1c0 merges, on a branch cut from `block/b1c`'s head, so the docs-only PR merges at 3.75 (was 8.25), after only its tail (cut from `main`, cherry-pick, gates (U), then the rest of its end, 1.0 h: approval, merge, read-back, post-merge gates, `MERGED` line; owner answer Q-RD8c-1 (b)); every stream and Task 1c.2 start after it. So B2.1 starts at 3.75 (was 2.5) and 1c.2 at 4.0 (was 2.75); with PR-C2 kept first in the queue (of the three tied shortest orders, the one with PR-C2 earliest), PR-C2 (5.5, was 4.25), PR-1c (7.75, was 6.5), PR-B2 (12.0, was 10.75), PR-1d (13.75, was 12.5), PR-D (15.5, was 14.25), PR-1d2 (19.0, was 17.75), PR-2b (23.25, was 22.0), PR-2c (29.75, was 28.5) and PR-P1 (37.25, was 36.0) each move +1.25 h; Task P2.1 is L + 1 h (4 h, owner answer Q-RD8b-2 (b)), so PR-P2 (45.75, was 43.5), PR-P4 (51.25, was 49.0), PR-P3 (54.0, was 51.75), S (56.0, was 53.75) and the total (93.0 h, was 90.75 h) each move +2.25 h; the critical path runs through B2 as in revision 4, now after the docs-only PR's tail and its approval; the program's S+ times and waves are unchanged, and the pre-program waves are re-cut at the new merges (peak 15, unchanged).
- Range: about 54 h if every task takes 1 h; about 118 h if every task takes 3 h (revision 2's figures; revision 3 does not recompute them). The path has 28 owner approvals (revision 2: 15; revision 4: 27): the pre-program PR-1c0, the docs-only PR, PR-B2, PR-1d, PR-D, PR-2b, PR-2c, P1, P2 and P3 (revision 5, owner answer Q-DOCS-1 (e): the docs-only PR's approval is in its tail, on the path); the release `stream-ownership` decision and the `program-create` decision, both before `program create` (owner answer Q-F80W-13 (a)); PR-runtime, PR-residual/R5, PR-cfg4, -context, -evidence, -bash, -rules4, -tools, -checkpoint, -docs, PR-residual/R3, /R2, /R4, PR-init4 and PR-release; the 6R.3 tag.
