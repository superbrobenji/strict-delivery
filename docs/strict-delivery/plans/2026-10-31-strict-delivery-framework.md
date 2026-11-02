# strict-delivery framework Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build block 1 of the strict-delivery framework (main spec §17.1): the gate library, the strict YAML subset, the schema checker `gate_schema` with the block-1 schemas, one-file-per-record decision and finding registers with dated random-suffix ids and the no-delete rule, `gate_decisions`, `gate_register`, and the decisions, findings and index tools. Block 2, the programs block and blocks 3-6 are outlined at the end.

**Architecture:** A standard-library Python package `gates/` at the repository root, run as `python3 -m gates <command>`. `gates/lib/` holds pure modules (YAML subset, result contract, config, git, ids and record store, schema checker, decision and finding rules); `gates/schemas/<kind>.yml` holds one schema per file kind; gates and tools are thin CLIs over the library. Every gate reads a target tree given by `--root` (default: the repository root) and that tree's `.strict-delivery/config.yml`.

**Tech Stack:** Python 3.9+ standard library only (`unittest`, `argparse`, `subprocess`, `fnmatch`, `dataclasses`, `random`, `datetime`); git.

**Spec:** `docs/strict-delivery/specs/2026-10-31-strict-delivery-framework-design.md` and `docs/strict-delivery/specs/2026-10-31-programs-and-streams-design.md` (the design wins where they differ, design preamble). Both are binding; executors read both.

## Global Constraints

- Runtime (spec §3): "Python 3.9 or newer, standard library only. No PyYAML". Tests are `unittest`; no third-party runner.
- YAML (spec §6): state and config use the strict YAML subset of `gates/lib/yamlsub.py`; every other YAML feature is refused with a line number.
- Language- and project-agnostic: no hardcoded model names, paths or test filename patterns in gate code; everything comes from config, with the defaults of spec §5 and §6.
- Ids (spec §7.2): "`<PREFIX>-<YYYYMMDD>-<xxxx>`: prefix `DEC` (decision), `F` (finding), `C` (claim) or `R` (cross-stream request); the UTC creation date; four characters from the lowercase base32 alphabet without `0`, `1`, `l`, `o`, drawn at random. Example `DEC-20261031-k3f9`. The date must be a valid calendar date and is never compared with the clock (owner answer 2026-10-31). No person's name or handle appears in any id."
- Records (spec §7.2): "One file per record, named by id. Decisions and findings carry `status`; a record stays in its folder whatever its status, and no status has a folder of its own." No shards, no gap rule (design §8.1).
- Data files (spec §15, Appendix A): "Every data file carries `schema: <kind>/<version>`". YAML files carry it as a top-level key; generated markdown files as the first line `<!-- schema: <kind>/<version> -->`.
- No-delete (spec §7.2): "a decision, open finding or claim file present on the base branch may not be deleted by a branch. The only deletions allowed are the cleanup step's (resolved findings and per-effort files, section 5)."
- Uniqueness (spec §7.2): "no id appears twice across the tree, and a pull request's ids are checked against the base branch too (config `base_branch`, section 6; deletions and immutability are checked against the merge base with it); a resolved record is immutable (a change is a new decision with `supersedes`), except that a finding's status moves from `closed` to `merged`, set only by the cleanup step (owner answer 2026-10-31), and that a change which is exactly a registered schema migration of the base row is not an immutability change: the gates migrate the base row with the registered migrations before comparing, so a schema version change and `upgrade` can migrate resolved records (owner answer 2026-10-31); a decision's `landed_in` is never a spec."
- Whole-token match (used in Tasks 1b.2, 1c.1 and 1c.2): an id occurs in a text as a whole token when the character before it and the character after it are each either outside `[0-9A-Za-z_-]` or the start or end of the text. So with prefix `F`, `XF-20261031-k3f9` and `F-20261031-k3f9a` hold no finding id (owner-approved call, I6).
- Names (owner-approved call, I7): the `paths` key names, the schema-file vocabulary of Task 1b.1, and the file and function names in this plan are the plan's choice under design §17 ("File and function names inside `gates/`").
- Answers (spec §7.1): "there is no global owner setting. Answers and withdrawals come only from that human"; "Each answer records the git identity (`git config user.email`) as `answered_at.by`." No config key names an owner. The PreToolUse Bash refusal of `decisions decide` and `decisions withdraw` from agents lands in block 3; until then the controller never runs either command; the human runs them with the `!` prefix.
- Evidence (spec §5): cites of per-effort files use "the form `<sha>:<path>`, resolved with `git cat-file` (and required to name a commit in the repository), never a file at HEAD."
- Base branch (owner OQ-4): config `base_branch`, default `main`; gates default `--base` to it, check deletions and immutability against the merge base with it, and check id collisions against its tip.
- Unknown keys (owner OQ-16): every schema refuses keys it does not declare.
- Generated files (spec §5): "Ignored, never committed: generated files (state indexes, `in-force.md`, `INDEX.md`)".
- Gate contract (spec §13): "`check(args) -> Result`; prints `PASS id` or `FAIL id: reason` lines; `--json`; exits 0 only when at least one line exists and every line passes; a missing input fails (`<gate>.input`), an empty run fails (`<gate>.empty`); `--root` points at another tree."
- Registers ship empty. No lap-timer decisions, findings, claims, decision numbers or state as fixtures; the repository is public, so tests build synthetic fixtures in temp directories.
- Every commit carries the harness's `Co-Authored-By:` line for the model that wrote it (controller ruling 2026-11-01: honest authorship; commits made before this line read `Claude Opus 5.5` or `Claude Sonnet 5.5` and are not rewritten).
- Test command, every task, both interpreters (strict profile): `/usr/bin/python3 -m unittest discover -s tests -t . -v` (3.9.6) and `python3.13 -m unittest discover -s tests -t . -v` (Homebrew `/opt/homebrew/bin/python3.13`). Both pass before every commit, and the tree is clean after it.

## Process for this plan

- Bootstrap (spec §16): no gates existed when block 1a started; judgment rules apply by hand and the block-1a report says so. "Each gate is enabled on this repository as soon as it lands": `check schema` from Task 1b.1, `check decisions` from Task 1c.1, `check register` from Task 1c.2. From each enabling task on, the commit gate is the test command on both interpreters plus every enabled `python3 -m gates check <gate>` exiting 0, with a clean tree (`git status --porcelain --untracked-files=all` empty). `run_all` replaces this list in block 2.
- Blocks. Spec §17 block 1 is split under the strict cap of 3 tasks per block into sub-blocks **1a** (Tasks 1a.1-1a.3), **1b** (1b.1-1b.3), **1c0** (Task 1c0.1; owner answer F-docs-11 (c), 2026-11-02), **1c** (1c.1-1c.3) and **1d** (1d.1-1d.2), each on its own branch (`block/b1a`, `block/b1b`, `block/b1c` for 1c0, `block/b1c1` for 1c, `block/b1d`) and each with its own pull request from block 1c0 on. Under the strict profile each block ends with a final review (opus) and a top-tier final verifier. Blocks 1a and 1b then took an owner merge grant given in chat and ledgered verbatim, the merge as its own command, and the checkpoint. From block 1c on, `main` is protected (owner directive 2026-11-01) and every block, of every stream, ends in the pull-request flow: push the block branch; open a pull request to `main`; the owner approves it in chat naming the PR and its head sha; the controller runs `gh pr merge <n> --merge --match-head-commit <sha>`; the merge is read back from the host (`gh pr view <n> --json number,headRefOid,mergeCommit,mergedAt,mergedBy`); the post-merge gates run on `main` updated from the remote; the merge is ledgered verbatim (from programs Task P1.2 as the `MERGED` line), written as the next branch's first commit; then the checkpoint and continuation. Merge approvals are not decision records (owner answer Q-15 (a), 2026-11-01).
- Continuation (spec §8, design §4.4) replaces stopping for `/clear`: at a checkpoint, at 80 % of its token or time budget, or at a usage-limit stop, the controller writes its handoff and returns `status: DONE` with `next:` (or `BLOCKED: budget`); its dispatcher at once dispatches a fresh controller with a continue prompt built from the handoff and ledger. One block per agent context stays. Nothing continues from inherited memory.
- Checkpoint after every task: append one line to `.strict-delivery/state/plans/2026-10-31-strict-delivery-framework/ledger.md`:
  `CHECKPOINT <block> <task> head=<short sha> tests=<passed>/<total> gates=<PASS|n/a> next=<task id>`
  and rewrite `handoff.md` beside it. Its front matter carries `schema: handoff/1` and the fields spec §9 lists for `gate_checkpoint` (plan, spec, branch, head, base, ledger, resume line, block, next task, findings in flight, open decisions, rulings, grant, live subagents). From programs Task P1.3 the fields are those of `handoff/1` (Task P1.2), the checkpoint commit is pushed, and the step runs `python3 -m gates check checkpoint --plan <plan>`. The resume line reads:
  `Resume strict-delivery plan docs/strict-delivery/plans/2026-10-31-strict-delivery-framework.md at <next task>; branch <branch>; head <sha>; open questions: <ids or none>.`
  The tree is clean after the checkpoint commit.
- Owner answers recorded 2026-10-31, before the decision log existed, that still stand: the split of block 1; `asked_at` and `answered_at.at` are commit shas; the `check <gate>` command form; the LICENSE holder; Python 3.13 installed locally; execution subagent-driven; the strict profile and full v0.1 scope. Superseded by the specs: the owner handle (now: the human answers and the git identity is recorded), `withdraw` "owner-only" (now: human only), `schema: 1` wrappers (now `schema: <kind>/<version>`), shards. Replaced by the owner's 2026-10-31 answers OQ-1..OQ-18 (section "Owner answers (2026-10-31)" at the end of this plan): the `decisions.scan` defaults (OQ-10) among them.
- Process changes adopted by the owner 2026-10-31 after the Task 1a.1 convergence stop. They apply to this plan's briefs and dispatches now, and are written into this repository's own prompt blocks in block 3; the shared user-level skill is not changed:
  - PC1: every task whose Produces list takes an argument or reads a file carries an input-domain table in its brief. The table has one row per parameter or filesystem call and dimension, and each row gives values, the expected verdict and a test name. Dimensions include argument type (subclasses, bool as int), path kind, character class, the character after each indicator, each output position, and the resources held on each error path. A missing table blocks dispatch.
  - PC2: briefs state the oracle as the production path plus an independent expected value (for a parser: `load` of a file written by `emit`, and a fuzz generator that builds each document with its expected value).
  - PC3: an implementer lists every behaviour the brief does not state, and every knowing divergence, and stops NEEDS_DECISION. In a fix round it first lists the invariants the replaced code held and tests each. It writes one mutant per changed production condition or call.
  - PC4: reviewers have no out-of-scope bucket for this task's own code. A class that seems to exclude a failing whitelist input is a class-narrowing question for the owner. A missing input-domain table is a finding.
  - PC5: the ledger writes each finding's class by input dimension (`class: <dimension>: <members>`), and fix and re-review dispatches quote it verbatim.
- Input-domain tables. Every task below carries an **Input-domain dimensions** list naming the dimensions its table must cover. Before dispatch the controller drafts the full table at `.superpowers/sdd/2026-10-31-strict-delivery-framework/task-<id>-domain.md`, in the format of `task-1a.1-domain.md` (sections per producer; columns `# | dimension | values | expected verdict | test`; an Oracle section; a section of binding owner rulings).
- Owner questions are batched (owner, 2026-10-31). Before each task's dispatch, the controller lists every table row whose verdict the specs, this plan and earlier rulings do not settle, and sends them to the owner as one batch with options and costs; dispatch waits for the answers. Questions raised mid-task are held to the next stop (a review verdict or the block end), never asked one at a time. The first batch (OQ-1..OQ-18) is answered; its answers are written into the tasks below and listed in "Owner answers (2026-10-31)".
- Roles (this repository's dispatch policy, from the strict-delivery skill's roles table; spec §10 states only tiers): implementer sonnet; task reviewer and final reviewer opus; final verifier and exception reviewer the top tier only.

## Review Focus

1. A branch deletes a decision or open-finding file that exists on the base branch (a `git rm` of an "obsolete" record, or a rebase that drops the commit adding it). The gate fails `decisions.base.deleted.<id>` (or `register.base.deleted.<id>`), naming the base ref, and says records on the base are never deleted. Tests: `test_deleted_base_record_fails` in Task 1a.3 (library) and `test_deleted_base_decision_fails` in Task 1c.1 (gate).
2. A person hand-fixes a typo in an answered decision. The gate fails `decisions.base.immutable.<id>` and names `supersedes` as the remedy. Test in Task 1c.1: `test_edited_answered_decision_fails_with_remedy`.
3. A hand-written id breaks the format: uppercase (`DEC-20261031-K3F9`), an excluded character (`DEC-20261031-l0o1`), a three- or five-character suffix, or a file name that is not the row's id. The gate fails naming the file and states the expected form and alphabet. Test in Task 1a.3: `test_hand_written_bad_ids_refused`.
4. Evidence cites a review report that the post-merge cleanup has since deleted: a plain path then fails, and a `<sha>:<path>` whose sha is gone (a rebased-away branch) fails naming the sha. A `<sha>:<path>` at a real commit passes after the file is deleted from HEAD. Test in Task 1b.3: `test_evidence_sha_path_survives_cleanup`.
5. A gate run outside a git repository, or in one without `.strict-delivery/config.yml`, fails `<gate>.input` with a message naming `/strict-delivery:init`, never a traceback. Test in Task 1a.2: `test_missing_config_names_init`.

---

## Block 1a: library foundations (branch `block/b1a`)

### Task 1a.1: strict YAML subset parser and emitter — COMPLETE

Complete: commits `c4f36f1..004854a` (115 tests; closing review clean). Code: `gates/lib/yamlsub.py`, `tests/test_yamlsub.py`, `LICENSE`; input-domain table `.superpowers/sdd/2026-10-31-strict-delivery-framework/task-1a.1-domain.md`. Do not change this code in later tasks; a defect found in it is an unrelated finding for the owner.

**Interfaces (Produces, used by every later task):**
- `class YamlError(Exception)` with `line: int` (1-based; 0 = whole file) and `reason: str`; `str(e) == f"line {line}: {reason}"`.
- `parse(text: str) -> object` (`dict` with `str` keys, `list`, `str`, `int`, `bool`, `None`; empty or comment-only gives `None`; non-`str` input raises `TypeError`).
- `load(path: str, shown: str) -> object`: every failure, path problems included, is a `YamlError` whose reason starts with `shown`.
- `emit(value: object) -> str`: canonical text ending in one `\n`; `parse(emit(x)) == x`.
- `class EmitError(ValueError)`; `MAX_DEPTH = 50`, `MAX_INT_CHARS = 1000`.

### Task 1a.2: result contract, config loader, git helpers

**Files:**
- Create: `gates/lib/result.py`, `gates/lib/config.py`, `gates/lib/gitinfo.py`, `gates/__main__.py`, `gates/producers.py`
- Test: `tests/helpers.py`, `tests/test_result.py`, `tests/test_config.py`, `tests/test_gitinfo.py`

**Owner answers applied:** OQ-1, OQ-2, OQ-4, OQ-10, OQ-16.

**Interfaces:**
- Consumes: `yamlsub.load`, `YamlError`, `emit`.
- Produces:
  - `result.py`: `@dataclass Line(status: str, id: str, reason: str = "")`; `@dataclass Result(gate: str, lines: list)` with `ok() -> bool`, `fail(id: str, reason: str) -> None`, `passed(id: str) -> None`, `render(as_json: bool) -> str`; `class GateError(Exception)`; `gate_args(prog: str) -> argparse.ArgumentParser` (adds `--root`; help goes to stderr); `run_check(name: str, check, args: list) -> Result` and `run_gate(name: str, check, argv: Optional[list] = None) -> int`: `--json` is honoured only as `argv[0]`; `SystemExit`, any `Exception` and an empty `Result` become FAIL lines (`<name>.input` or `<name>.empty`); `--help` gives `FAIL <name>.input: help requested; no gate was run`; `KeyboardInterrupt` propagates. `repo_root() -> str` (`CLAUDE_PROJECT_DIR` when set and non-empty, else `git rev-parse --show-toplevel`, else `GateError`). `safe_text(s: str) -> str` escapes non-printables so every line id and reason is one line.
  - `config.py`: `CONFIG_PATH = ".strict-delivery/config.yml"`; `DEFAULTS: dict` with:
    - `paths`: `state: .strict-delivery/state`, `decisions: .strict-delivery/state/decisions`, `findings: .strict-delivery/state/findings`, `claims: .strict-delivery/state/claims`, `plan_state: .strict-delivery/state/plans`, `programs: .strict-delivery/state/programs`, `playbooks: .strict-delivery/playbooks`, `receipts: .strict-delivery/receipts`, `context: .strict-delivery/context.yml`, `architecture: docs/strict-delivery/architecture.md`, `index: docs/strict-delivery/INDEX.md`, `specs: docs/strict-delivery/specs`, `plans: docs/strict-delivery/plans`, `reviews: docs/strict-delivery/reviews` (spec §5);
    - `ids`: the four prefixes, `decision: DEC`, `finding: F`, `claim: C`, `request: R`, and nothing else (OQ-2: only the prefixes are configurable; date and suffix rules are fixed in `ids.py`); a prefix is `[A-Z]+`;
    - `base_branch: main` (OQ-4);
    - `decisions.scan: ["docs/**", "CLAUDE.md", ".strict-delivery/playbooks/**"]` (OQ-10);
    - `models.tiers`: `tier1: haiku`, `tier2: sonnet`, `tier3: opus` (spec §6: "defaults: tier1 haiku, tier2 sonnet, tier3 opus; tier4 has no default"); `tier4` has no default: a project that uses top-tier roles sets it (owner Q-rev2-1);
    - `drift.estimate_factor_pct: 150` (spec §6, "optional, default 150");
    - `decision_classes.owner_only`: `["triage", "spec-direction", "scope", "merge-grant", "model-policy", "issue-close", "finding-class", "rule-override", "program-create", "stream-ownership", "stream-merge", "request-dispute", "program-close"]` (spec §7.1; the first eight slugs are the owner-approved ones of the earlier plan, the last five are the spec's own).
  - `config.load(root: str) -> dict`: deep merge of the file over `DEFAULTS` (a mapping merges key by key; `decision_classes.owner_only` merges as a union: the file's slugs are added to the default list, and a project cannot drop a default (owner Q-plan-1, spec §6); any other value replaces), then the key checks (OQ-1: only `schema`, `framework_version` and `profile` must be in the file; every key with a default may be omitted; OQ-16: a top-level key not in `CONFIG_KEYS` is refused with `GateError` naming it; `models`, `models.tiers` and `drift`, when present, are mappings; each `models.tiers` value present is a non-empty `str`, the four `ids` prefixes are distinct (controller ruling R-rev5-1), and `drift.estimate_factor_pct` is an `int` (not `bool`) of at least 1, else `GateError` naming the key). `CONFIG_KEYS` is the spec §6 key set plus `schema`: `schema`, `framework_version`, `profile`, `commands`, `paths`, `ids`, `models`, `roles`, `top_tier_roles`, `top_tier_fallback`, `decision_classes`, `block`, `rulings`, `dispatch`, `budgets`, `drift`, `overrides`, `base_branch`, `decisions`. Always: `framework_version` a `str`; `profile` one of `light`, `standard`, `strict`; each `paths` value a non-empty, normalised, repo-relative `str` (no leading `/`, no `..` segment); `schema` equal to `config/1`; `ids` exactly the four prefix keys; `base_branch` a non-empty `str` with no run of more than 40 hex digits (gitinfo refuses such a revision; owner Q-1a2r-8); `decisions.scan` a list of non-empty `str` globs; `decision_classes.owner_only` in the file a non-empty list of non-empty `str` (as the config schema's `min: 1`, Task 1b.1). No `owner` key is read. A missing file raises `GateError(".strict-delivery/config.yml: missing; run /strict-delivery:init")`; a `YamlError` raises `GateError` carrying the file and line; a top level that is not a mapping raises `GateError`.
  - `gitinfo.py` (C locale; messages name the git command, never the directory): `head_sha(root) -> str`; `commit_exists(root, sha) -> bool` (`git cat-file -e <sha>^{commit}`); `blob_exists(root, sha, path) -> bool` (`git cat-file -e <sha>:<path>`, true only for a blob); `tracked_files(root) -> frozenset` (index entries of mode 100644 or 100755 only); `show(root, ref, path) -> Optional[str]` (`None` when the path is absent at `ref`); `ls_tree(root, ref, directory) -> list` (repo-relative paths of regular files directly in `directory` at `ref`; empty when the directory is absent); `merge_base(root, a, b) -> str`; `user_email(root) -> Optional[str]` (`git config user.email`, `None` when unset or empty); every git failure other than these documented `None`/`False`/empty results raises `GateError`.
  - `producers.py`: `PRODUCER_MODULES: tuple` of dotted module names, empty here; each later gate or tool module defines `PRODUCES: tuple` of kind names and is appended to this tuple by its task (Appendix A "declares that kind in its `produces` list").
  - `__main__.py`: `COMMANDS: dict` mapping a command name to `Callable[[list], int]`; `main(argv: list) -> int` dispatches `argv[0]`, returns 2 with usage on stderr for an unknown or missing command. Block 1 registers `check` (`check <gate> [args]`), `decisions`, `findings` and `index` as later tasks land.
  - `tests/helpers.py`: `minimal_config() -> dict` (`schema: config/1`, `framework_version: "0.0.0"`, `profile: strict`; nothing else); `make_repo(tmp: str, config: Optional[dict] = None) -> str` (`git init -b main`, so the first branch is `main` whatever `init.defaultBranch` says; a fixed author and committer identity and date, `user.email` set to `fixture@example.invalid`; `GitIsolatedTestCase(unittest.TestCase)`, the base class of every test that runs git, patches `os.environ` for each test with `unittest.mock.patch.dict` (`HOME` = the test's temp directory, `GIT_CONFIG_NOSYSTEM=1`, `GIT_CONFIG_GLOBAL=/dev/null`), so production code, which inherits `os.environ`, sees an unset repo `user.email` as unset, writes `emit(config or minimal_config())` to `.strict-delivery/config.yml`, commits); `commit_all(root: str, msg: str) -> str` returns the new sha; `write_record(root: str, rel: str, row: dict) -> str` writes `emit(row)`.

**Input-domain dimensions:** `config.load`: required keys (each of `schema`, `framework_version`, `profile` missing), file kind (missing, directory, FIFO, symlink, unreadable), YAML failure, top-level type (`None`, list, scalar), each read key's type (str subclass, `bool` as `int`, `None`, empty), `profile` values (case, whitespace, unknown), each `paths` value (absolute, `..`, `./`, `//`, trailing `/`, empty, non-str), deep-merge shapes (mapping over scalar, scalar over mapping, list replacing list), unknown top-level keys (`owner`, a typo such as `profle`), `ids` values (extra key, missing key, lowercase prefix, empty, two kinds sharing one prefix: refused), `base_branch` (empty, non-str, a run of 41 or more hex digits in any case: refused), `decisions.scan` (empty list, non-str item), `decision_classes.owner_only` (not a list, empty list: refused, non-str item, empty-str item, a new slug added to the defaults, a default slug restated, an attempt to drop a default by listing only `hardware`: the defaults stay), `models.tiers` (absent: defaults tier1-3 and no `tier4`; a project `tier4` kept; a tier value non-str or empty: refused; an extra tier name kept), `models`, `models.tiers` or `drift` not a mapping: refused; `drift.estimate_factor_pct` (absent: 150; 0, negative, `bool`, str `"1.5"`: refused). `repo_root`: `CLAUDE_PROJECT_DIR` unset, empty, non-directory; not a git repository. `gitinfo`: `root` kinds, ref forms (full sha, short sha, ambiguous short sha, branch, tag, nonexistent ref, a value starting with `-`), path forms (spaces, unicode, leading `-`, absent, directory, symlink, submodule), unset `user.email`. `run_gate` argv: `--json` first or later, `--help`, unknown flag, empty. `Result` text: newline, CR, control characters, non-str reason; check raising `Exception`, `SystemExit(0)`, `SystemExit("x")`, `KeyboardInterrupt`.

- [ ] **Step 1: Write the failing tests** (`tests/test_result.py`, `tests/test_config.py`, `tests/test_gitinfo.py`). Signatures and key asserts:
  ```python
  # test_result.py
  def test_empty_result_fails_empty():        # check returns Result("x", [])
      assert out == "FAIL x.empty: ...\n" and code == 1
  def test_exception_becomes_input_fail():    # check raises ValueError("boom")
      assert out.startswith("FAIL x.input:") and code == 1
  def test_json_only_as_first_arg():          # ["--json"] gives JSON; ["--root", r, "--json"] gives FAIL x.input
  def test_newline_in_reason_is_one_line():   # reason "a\nb\r"
      assert len(out.splitlines()) == 1
  def test_keyboard_interrupt_propagates():
      with self.assertRaises(KeyboardInterrupt): run_gate("x", raising_check, [])
  # test_config.py
  def test_defaults_merged():                 # make_repo(tmp) with minimal_config()
      assert cfg["paths"]["decisions"] == ".strict-delivery/state/decisions"
      assert "program-close" in cfg["decision_classes"]["owner_only"]
      assert cfg["models"]["tiers"]["tier2"] == "sonnet" and cfg["drift"]["estimate_factor_pct"] == 150
      assert "tier4" not in cfg["models"]["tiers"]               # Q-rev2-1
  def test_owner_only_merges_as_union():      # Q-plan-1: file owner_only: [hardware]
      assert set(cfg["decision_classes"]["owner_only"]) == set(DEFAULTS["decision_classes"]["owner_only"]) | {"hardware"}
  def test_owner_only_bad_values():           # subTests: "triage" (str), [], [1], [""]
      with self.assertRaises(GateError): config.load(root)
  def test_missing_config_names_init():       # Review Focus 5; git repo without config, and non-git dir via run_gate
      assert out.startswith("FAIL x.input:") and "/strict-delivery:init" in out and "Traceback" not in err
  def test_bad_profile():                     # subTests: "Strict", " strict", "loose", 1, None
      with self.assertRaises(GateError) as e: config.load(root)
      assert "profile" in str(e.exception)
  def test_paths_must_be_relative_normalised():  # subTests: "/abs", "a/../b", "./a", "a//b", "a/", "", 1
      with self.assertRaises(GateError) as e: config.load(root)
      assert "paths." in str(e.exception)
  def test_yaml_error_names_file_and_line():  # config text "a: [1\n"
      assert ".strict-delivery/config.yml" in msg and "line 1" in msg
  def test_only_three_keys_required():        # OQ-1; subTests drop each of schema, framework_version, profile
      assert key in str(e.exception)
  def test_unknown_key_refused():             # OQ-16: owner: {handle: x}; also profle: strict
      assert "owner" in str(e.exception)
  def test_ids_only_prefixes():               # OQ-2
      assert config.load(root_with({"ids": {"decision": "X"}}))["ids"]["decision"] == "X"
      with self.assertRaises(GateError): config.load(root_with({"ids": {"width": 4}}))
  def test_base_branch_and_scan_defaults():   # OQ-4, OQ-10
      assert cfg["base_branch"] == "main"
      assert cfg["decisions"]["scan"] == ["docs/**", "CLAUDE.md", ".strict-delivery/playbooks/**"]
  # test_gitinfo.py
  def test_make_repo_branch_is_main():        # F5: with init.defaultBranch unset
      assert git(root, "symbolic-ref", "HEAD") == "refs/heads/main"
  def test_head_and_commit_exists():
      assert gitinfo.commit_exists(root, gitinfo.head_sha(root)) is True
      assert gitinfo.commit_exists(root, "0" * 40) is False
  def test_blob_exists_only_for_blobs():      # a tree path and a missing path
      assert gitinfo.blob_exists(root, head, "dir") is False and gitinfo.blob_exists(root, head, "nope") is False
  def test_untracked_file_not_in_tracked():
      assert "new.txt" not in gitinfo.tracked_files(root)
  def test_show_absent_path_is_none():
      assert gitinfo.show(root, "HEAD", "nope") is None
  def test_ls_tree_absent_dir_is_empty():
      assert gitinfo.ls_tree(root, "HEAD", "nope") == []
  def test_user_email_unset_is_none():
      assert gitinfo.user_email(root) is None
  def test_not_a_repo_is_gate_error():
      with self.assertRaises(GateError): gitinfo.head_sha(plain_dir)
  ```
- [ ] **Step 2: Run the test command; expect FAIL** (`ModuleNotFoundError` for `gates.lib.result`).
- [ ] **Step 3: Implement the four modules and `tests/helpers.py`.** Every subprocess call passes an argument list (never a shell string), `LC_ALL=C`, and `--` before user paths.
- [ ] **Step 4: Run the test command on both interpreters; expect PASS.**
- [ ] **Step 5: Commit** `feat(lib): gate result contract, config loader, git helpers`, then checkpoint.

### Task 1a.3: ids and the one-file-per-record store

**Files:**
- Create: `gates/lib/ids.py`, `gates/lib/store.py`
- Test: `tests/test_ids.py`, `tests/test_store.py`

**Owner answers applied:** OQ-3, OQ-4, OQ-5, OQ-6.

**Interfaces:**
- Consumes: `yamlsub.load/emit`, `config.load`, `result.GateError`, `gitinfo.show/ls_tree/merge_base`.
- Produces:
  - `ids.py`: `ALPHABET = "23456789abcdefghijkmnpqrstuvwxyz"` (the 32 characters of `0-9a-z` without `0`, `1`, `l`, `o`; the only reading of spec §7.2 that is 32 characters long and admits the example `k3f9`; design §17 leaves the exact check to the builder; owner-approved call, I1). `id_pattern(prefix: str) -> re.Pattern` matching `rf"{prefix}-([0-9]{{8}})-[{ALPHABET}]{{4}}"` by `fullmatch`. `id_problem(value: object, prefix: str) -> str` (`""` when valid, else the reason, which states the expected form and the alphabet; OQ-3: the date must be a valid calendar date, checked with `datetime.datetime.strptime(d, "%Y%m%d")` after the 8-digit match, so `20260230` and `20261399` are refused; no comparison with the clock). `mint(prefix: str, existing: set, today: datetime.date, rng: random.Random) -> str` draws 4 characters with `rng.choice(ALPHABET)` and redraws while the id is in `existing`. `utc_today() -> datetime.date` (`datetime.datetime.now(datetime.timezone.utc).date()`).
  - `store.py`: `@dataclass(frozen=True) Record(id: object, row: dict, file: str)` (`id` is the row's `id` value, `None` when the row has none; the store never validates fields; `file` repo-relative). `class Store` with `__init__(self, root: str, kind: str, cfg: dict)` (`kind` is `"decision"` or `"finding"`; the directory is `cfg["paths"]["decisions"]` or `cfg["paths"]["findings"]`; the prefix from `cfg["ids"]`); `load() -> list` (every `*.yml` file directly in the directory except `index.yml`, as a `Record`; a missing directory is an empty store; a file that does not load, is not a regular file, or is not a top-level mapping raises `GateError` naming the file); `path_for(id: str) -> str`; `create(row: dict) -> str` (creates the register directory and its parents when absent, then writes `emit(row)` to `<id>.yml`; refuses an existing file with `GateError`); `replace(row: dict) -> str` (rewrites an existing file; refuses a missing one). The store never validates fields; the schema checker does.
  - `store_errors(records: list, prefix: str) -> list` of `(suffix, reason)` pairs: `id.<file>` (the row's `id` fails `id_problem`), `name.<file>` (file stem differs from the row's `id`), `duplicate.<id>` (one id in more than one file; the reason lists every file).
  - `base_errors(root: str, store: Store, base: str, is_resolved: Callable[[dict], bool], may_delete: Callable[[dict], bool]) -> list` of `(suffix, reason)` pairs, where `base` is the base branch ref (OQ-4: callers pass `--base`, default `cfg["base_branch"]`); deletions and immutability compare the working tree with `mb = merge_base(root, base, "HEAD")`, collisions with the tip of `base`: `deleted.<id>` (a record file at `mb` is absent now and `may_delete(row_at_base)` is false; reason `<file> exists on <base>; records on the base branch are never deleted`); `immutable.<id>` (a record resolved at `mb` differs now; reason for decisions `resolved records are immutable; record the change as a new decision with supersedes: <id>`, for findings `... as a new finding`; neither exception in spec §7.2 arises in block 1: `closed -> merged`, set only by the cleanup step, because `merged` is unreachable there (OQ-6), and a registered schema migration of the base row, because block 1 registers none (block 2's `decision/2` task adds the registry and the migrate-before-compare step, plan edit E6), so a closed finding changed in any way fails here, as does any other resolved record); `collision.<id>` (an id added since the merge base that also exists at `base` with different content; reason `id <id> already exists on <base>; mint a new id`). For decisions `may_delete` is always false; for findings it is supplied by Task 1b.3 (OQ-5).

**Input-domain dimensions:** `id_problem`: value type (`str` subclass, `int`, `None`, `bool`, bytes), case, each excluded character (`0`, `1`, `l`, `o`) and each uppercase letter, suffix length 3 and 5, prefix (wrong kind, lowercase, extra `-`), date (non-digits, 7 or 9 digits, invalid calendar dates such as `20260230` and `20261399`, far future: accepted when the calendar date is valid), surrounding whitespace, trailing newline. `mint`: `existing` holding the drawn id (forced by a seeded `rng`), `today` near the UTC day boundary. `Store.load`: file kinds in the directory (subdirectory, symlink, FIFO, `*.yaml`, hidden file, `index.yml`, `in-force.md`), file content (YAML error, top-level list or scalar, empty file). `create`/`replace`: existing or missing file, unwritable directory. `base_errors`: base ref (absent ref, base equal to HEAD, base ahead of the merge base, shallow history), record deleted, renamed with `git mv` to another id, open record changed, resolved record changed, closed finding changed to merged, id added on both sides, base without the directory.

- [ ] **Step 1: Write the failing tests** (`tests/test_ids.py`, `tests/test_store.py`):
  ```python
  # test_ids.py
  def test_alphabet_is_32_chars_without_0_1_l_o():
      assert len(ALPHABET) == 32 and not set("01lo") & set(ALPHABET) and set("k3f9") <= set(ALPHABET)
  def test_example_id_valid():
      assert id_problem("DEC-20261031-k3f9", "DEC") == ""
  def test_hand_written_bad_ids_refused():    # Review Focus 3
      for v in ["DEC-20261031-K3F9", "DEC-20261031-l0o1", "DEC-20261031-k3f", "DEC-20261031-k3f9a",
                "F-20261031-k3f9", "DEC-2026103-k3f9", " DEC-20261031-k3f9", "DEC-20261031-k3f9\n", 7, None, True]:
          assert id_problem(v, "DEC") != "" and (not isinstance(v, str) or ALPHABET in id_problem(v, "DEC"))
  def test_date_must_be_calendar_valid():     # OQ-3
      assert id_problem("DEC-20260230-k3f9", "DEC") and id_problem("DEC-20261399-k3f9", "DEC")
      assert id_problem("DEC-20240229-k3f9", "DEC") == "" and id_problem("DEC-20991231-k3f9", "DEC") == ""
  def test_mint_redraws_on_collision():       # first = mint("DEC", set(), d, random.Random(0))
      new = mint("DEC", {first}, d, random.Random(0))
      assert new != first and id_pattern("DEC").fullmatch(new)
  def test_mint_uses_given_date():
      assert mint("F", set(), datetime.date(2026, 10, 31), random.Random(1)).startswith("F-20261031-")
  # test_store.py
  def test_missing_dir_is_empty_store():
      assert Store(root, "decision", cfg).load() == []
  def test_load_skips_index_yml():            # index.yml and in-force.md beside one record
      assert [r.id for r in store.load()] == [ID]
  def test_create_refuses_existing():
      with self.assertRaises(GateError): store.create(row)   # second create
  def test_unloadable_file_names_file():      # "a: [1\n", a top-level list, a subdirectory named x.yml
      assert path in str(e.exception)
  def test_name_mismatch():
      assert ("name." + file, ANY) in store_errors(records, "DEC")
  def test_duplicate_id_lists_files():
      assert suffix == "duplicate." + ID and file_a in reason and file_b in reason
  def test_deleted_base_record_fails():       # Review Focus 1: commit, git rm, base="HEAD"
      assert ("deleted." + ID, ANY) in base_errors(root, store, "HEAD", is_resolved, lambda row: False)
      assert "records on the base branch are never deleted" in reason
  def test_renamed_record_is_deleted_plus_new():  # git mv A.yml B.yml
      assert "deleted." + A in suffixes
  def test_resolved_change_is_immutable_open_change_is_not():
      assert "immutable." + RESOLVED_ID in suffixes and "immutable." + OPEN_ID not in suffixes
      assert "supersedes: " + RESOLVED_ID in reason
  def test_closed_finding_changed_to_merged_is_immutable():  # spec §7.2 exception is the cleanup step's only
      assert "immutable." + F_ID in suffixes
  def test_collision_with_base():             # id added on branch and on base tip after the fork
      assert ("collision." + ID, ANY) in errs and "mint a new id" in reason
  def test_deletion_checked_at_merge_base():  # record added on base tip after the fork
      assert not any(s.startswith("deleted.") for s, _ in errs)
  def test_absent_base_ref_is_gate_error():
      with self.assertRaises(GateError): base_errors(root, store, "no-such-ref", is_resolved, never)
  ```
- [ ] **Step 2: Run the test command; expect FAIL.**
- [ ] **Step 3: Implement `gates/lib/ids.py` and `gates/lib/store.py`.**
- [ ] **Step 4: Run the test command on both interpreters; expect PASS.**
- [ ] **Step 5: Commit** `feat(lib): dated random ids and the one-file-per-record store`, then checkpoint. **Block 1a end:** final review, verifier, merge grant, merge, checkpoint, continuation (Process for this plan).

---

## Block 1b: schemas (branch `block/b1b`)

### Task 1b.1: schema checker, `gate_schema`, config schema; enable `check schema`

**Files:**
- Create: `gates/lib/schema.py`, `gates/gate_schema.py`, `gates/schemas/config.yml`, `.strict-delivery/config.yml` (this repository); Modify: `gates/__main__.py` (register `check schema`)
- Test: `tests/test_schema_lib.py`, `tests/test_gate_schema.py`

**Owner answers applied:** OQ-1, OQ-14, OQ-16, OQ-17.

**Interfaces:**
- Consumes: `yamlsub.load`, `config.load`, `result.*`, `producers.PRODUCER_MODULES`.
- Produces:
  - `schema.KNOWN_KINDS: tuple` = `("config", "decision", "finding", "claim", "request", "streams", "context", "handoff", "ledger", "status", "sync-log", "overview", "in-force", "decision-index", "finding-index", "mutation-transcript", "review-report", "receipt", "claude-block", "gitignore-block")` (Appendix A table, in order).
  - Schema file format (`gates/schemas/<kind>.yml`, YAML subset). Top-level keys: `kind` (equals the file stem), `version` (positive int), `format` (`yaml` | `markdown`), `files` (list of `{path: <paths key or "config">}` or `{dir: <paths key>, glob: <fnmatch pattern>, exclude: [names]}`), then for `yaml` `fields`, for `markdown` `first_line` (exact text) and optionally `table` (exact header cells, in order) or `headings` (exact `## ` headings, in order). A field spec is a mapping with `type` and optional `required` (default `true`), `nullable` (default `false`), `values`, `items`, `fields`, `id_kind`, `min`, `required_when`, `absent_when`. Types: `str` (non-empty), `text` (any `str`), `int` (not `bool`; optional `min`, the least value), `bool`, `enum` (`values`), `list` (`items`, `min`, the least length), `map` (`fields`), `any-map` (a mapping whose contents this version does not check; OQ-1; owner-approved call, I5), `id` (`id_kind`: `decision`, `finding`, `claim` or `request`; the prefix is `cfg["ids"][<id_kind>]`; checked with `ids.id_problem`), `sha` (7-40 lowercase hex), `glob` (non-empty), `cite` (normalised repo-relative path, optional `#anchor`), `sha-path` (`<sha>:<path>`, shape only). A field with `required_when` is required only when a condition matches and optional otherwise, whatever `required` says. `required_when` and `absent_when` (also inside a nested `map`, where they name sibling keys of that map) are lists of conditions `{<sibling field>: [values]}`; a condition matches when every sibling it lists has one of its values, and the rule applies when any condition matches. Every YAML data file's `schema` key must equal `<kind>/<version>`. A key a `map` or the top level does not declare is refused: `<dotted.path>: unknown key` (OQ-16). Flow notation such as `[{dir: ...}]` in this plan is shorthand: schema files are written with block mappings, because the subset refuses flow mappings (spec §6).
  - `class SchemaError(Exception)` (a malformed schema file; names the file and the key). `load_schema(path: str) -> Schema`; `schemas(dirpath: str = <package>/schemas) -> dict` (kind to `Schema`). `validate(schema: Schema, value: object, cfg: dict) -> list` of `"<dotted.path>: <problem>"`; a wrong or missing `schema:` tag gives `schema: expected <kind>/<version>, got <x>; run /strict-delivery:upgrade` when the kind matches and the version differs. `validate_markdown(schema: Schema, text: str) -> list`. `produced_kinds() -> set` (union of `PRODUCES` over `PRODUCER_MODULES`; an import failure raises `GateError` naming the module). `files_of(schema: Schema, root: str, cfg: dict) -> list` (repo-relative paths that exist).
  - `gate_schema.py`: `PRODUCES = ()`; `check(args: list) -> Result`, gate `schema`, args `--root`. Lines: `schema.kinds` (every produced kind, plus `config`, which is always checked as the one stated exception to the producer rule (OQ-14), has `gates/schemas/<kind>.yml`; every schema file's stem is in `KNOWN_KINDS` and loads; failures `schema.kinds.<kind>`); config first and raw: a missing or unreadable config file, or a YAML error in it, gives `FAIL schema.input` with the same message `config.load` gives (naming `/strict-delivery:init` for a missing file; Review Focus 5); otherwise `yamlsub.load` of `.strict-delivery/config.yml` is validated against `config.yml` (not through `config.load`, so the tag, upgrade hint, `profile` and unknown-key errors appear as `FAIL schema.config.<file>: <error>`); only when that passes does the gate call `config.load` for the other kinds, and a `GateError` from it then gives `FAIL schema.input`; when the raw config check fails, no other kind is checked; one `schema.<kind>` per checked kind (PASS when every file validates; else `FAIL schema.<kind>.<file>: <error>` per error; a generated file (decision-index, finding-index, in-force, overview) that is absent on disk is skipped, OQ-17).
  - `gates/schemas/config.yml`: `config/1`, `files: [{path: config}]`, fields (OQ-1): required `schema`, `framework_version` `str`, `profile` `enum [light, standard, strict]`; optional `paths` `map` of the `DEFAULTS` keys (each `str`, each optional), `ids` `map {decision, finding, claim, request}` (each `str`, optional), `base_branch` `str`, `decisions` `map {scan: list of glob, required: false}`, `decision_classes` `map {owner_only: list of str, min: 1, required: false}` (spec §6: both have defaults); optional and `any-map` (or `list`/`str` as §6 types them, contents unchecked) for the keys whose reader has not landed: `commands`, `models`, `roles`, `block`, `rulings`, `dispatch`, `budgets`, `drift`, `overrides` (`any-map`), `top_tier_roles` (`list` of `str`), `top_tier_fallback` (`str`). They become required in a later `config/<n>` with a migration.
  - This repository's `.strict-delivery/config.yml`: `schema: config/1`, `framework_version: "0.0.0"`, `profile: strict`; nothing else (every other key takes its default).

**Input-domain dimensions:** schema file (missing for a checked kind, stem not in `KNOWN_KINDS`, `kind` differing from stem, YAML error, unknown `type`, unknown field-spec key, `version` 0 or `bool` or str, `format` unknown); `required_when`/`absent_when` at top level and inside a nested `map` (condition key absent, condition value of another type, both conditions matching); `int` with `min` (below, equal, above); each type against each wrong value type (`bool` as `int`, `str` subclass, `None`, empty `str`, empty list, nested depth); `required`, `nullable`, `required_when`, `absent_when` combinations (sibling absent, sibling of another type); `schema:` tag (missing, wrong kind, older and newer version, non-str, `decision/1 ` with trailing space); markdown text (first line absent, with BOM, with CRLF, with trailing space, wrong kind; table header cells reordered, extra column, extra spaces, missing; headings reordered or missing); `produces` (module missing, raising on import, `PRODUCES` not a tuple, kind not in `KNOWN_KINDS`); `files` resolution (paths key unknown, directory missing, glob matching a directory or symlink); the config file (each required key missing, an unknown top-level key, an unknown key inside `paths` or `ids`, an `any-map` key holding a list); generated files absent, present and valid, present and invalid.

- [ ] **Step 1: Write the failing tests** (`tests/test_schema_lib.py`, `tests/test_gate_schema.py`):
  ```python
  # test_schema_lib.py
  def test_known_kinds_match_appendix():
      assert KNOWN_KINDS == ("config", "decision", "finding", "claim", "request", "streams", "context",
          "handoff", "ledger", "status", "sync-log", "overview", "in-force", "decision-index",
          "finding-index", "mutation-transcript", "review-report", "receipt", "claude-block", "gitignore-block")
  def test_each_type_accepts_and_refuses():   # one subTest per (type, value)
      assert validate(s("int"), {"v": True}, cfg) == ["v: ..."]      # bool is not int
      assert validate(s("str"), {"v": ""}, cfg) and validate(s("sha"), {"v": "ABC1234"}, cfg)
      assert validate(s("any-map"), {"v": {"x": [1]}}, cfg) == [] and validate(s("any-map"), {"v": []}, cfg)
  def test_required_when_and_absent_when():   # sibling absent, sibling of another type
      assert validate(cond, {"status": "open", "answer": "x"}, cfg)        # absent_when matched
      assert validate(cond, {"status": "answered"}, cfg)                   # required_when matched
  def test_conditions_inside_nested_map():    # nested map: required_when/absent_when name keys of that map
      assert validate(nested, {"o": {"kind": "issue", "number": 3}}, cfg) == []
      assert any(e.startswith("o.number:") for e in validate(nested, {"o": {"kind": "issue"}}, cfg))
      assert any(e.startswith("o.plan:") for e in validate(nested, {"o": {"kind": "issue", "number": 3, "plan": "p"}}, cfg))
  def test_int_min():
      assert validate(s("int", min=1), {"v": 0}, cfg) and validate(s("int", min=1), {"v": 1}, cfg) == []
  def test_schema_tag_version_mismatch_names_upgrade():
      assert "schema: expected decision/1, got decision/2; run /strict-delivery:upgrade" in errs
  def test_markdown_first_line_and_table_exact():  # BOM, CRLF, trailing space, reordered cells: each an error
      assert validate_markdown(sch, "<!-- schema: in-force/1 -->\n...") == []
  def test_malformed_schema_file_is_schema_error():  # unknown type, version 0, kind != stem
      with self.assertRaises(SchemaError) as e: load_schema(path)
      assert path in str(e.exception)
  def test_produced_kinds_import_failure_names_module():
      assert "tests.fixtures.raising_producer" in str(e.exception)
  # test_gate_schema.py
  def test_this_repos_schema_files_load():
      assert all(stem in KNOWN_KINDS for stem in schemas())
  def test_valid_config_passes():
      assert "PASS schema.config" in out and code == 0
  def test_config_wrong_tag_fails():          # schema: config/2
      assert "FAIL schema.config." in out
  def test_schema_file_not_in_table_fails_kinds():  # gates/schemas/widget.yml in a fixture schema dir
      assert "FAIL schema.kinds.widget" in out
  def test_produced_kind_without_schema_fails_kinds():  # fixture producer declares claim
      assert "FAIL schema.kinds.claim" in out
  def test_unproduced_kind_not_checked():
      assert "schema.claim" not in out
  def test_config_checked_without_producer():  # OQ-14: profile: loose
      assert "FAIL schema.config." in out
  def test_unknown_key_refused():             # OQ-16: top level profle: x, and paths: {stat: x}
      assert "profle: unknown key" in out and "paths.stat: unknown key" in out
  def test_absent_generated_file_skipped():   # OQ-17: fixture producer of in-force, no file
      assert "PASS schema.in-force" in out    # and a present invalid in-force.md gives FAIL schema.in-force.<file>
  def test_missing_config_is_input_fail():
      assert out.startswith("FAIL schema.input:") and "/strict-delivery:init" in out
  def test_config_yaml_error_is_input_fail():  # config.yml holding "a: [b"
      assert out.startswith("FAIL schema.input:")
  def test_empty_decisions_map_passes():      # decisions: {} and decision_classes: {} reach validate as caller values (the YAML subset cannot parse {}); absent maps go through the gate
      assert "PASS schema.config" in out
  def test_json_output_shape():
      assert json.loads(out)                  # parses; it carries the same lines as the text form
  ```
- [ ] **Step 2: Run the test command; expect FAIL.**
- [ ] **Step 3: Implement `schema.py`, `gate_schema.py`, `schemas/config.yml`.**
- [ ] **Step 4: Run the test command on both interpreters; expect PASS.**
- [ ] **Step 5: Enable on this repository.** Write `.strict-delivery/config.yml`; run `python3 -m gates check schema`; expect every line `PASS` and exit 0.
- [ ] **Step 6: Commit** `feat(gates): schema checker, gate_schema, config schema; enable check schema`, then checkpoint with `gates=PASS`.

### Task 1b.2: decision schema and decision rules

**Files:**
- Create: `gates/schemas/decision.yml`, `gates/lib/decisions.py`
- Test: `tests/test_decisions_lib.py`

**Owner answers applied:** OQ-7, OQ-8, OQ-9, OQ-11, OQ-12, OQ-16.

**Interfaces:**
- Consumes: `schema.load_schema/validate`, `ids.id_problem`, `store.Record`, `gitinfo.tracked_files`, `config.load`.
- Produces:
  - `gates/schemas/decision.yml` (`decision/1`, `files: [{dir: decisions, glob: "*.yml", exclude: [index.yml]}]`). Fields (spec §7.1): `id` (`id`, `id_kind: decision`), `status` (`enum [open, answered, withdrawn]`), `class` (`str`), `question` (`str`), `options` (`list`, `min: 2`, items `map {label: str, cost: str}`), `asked_at` (`sha`), `asked_by` (`str`), `topics` (`list` of `str`), `applies_to` (`list` of `glob`), `checked_against` (`list` of `id`, `id_kind: decision`), `effect` (`enum [lasting, one-off]`), `supersedes` (`id`, `id_kind: decision`, `required: false`), `answer` (`str`; `required_when: [{status: [answered]}]`, `absent_when: [{status: [open, withdrawn]}]`), `answered_at` (`map {at: sha, by: str}`; same conditions; OQ-11: `at` checked for shape only, 7-40 lowercase hex, never for existence), `rule` (`str`, `required: false`, `absent_when: [{status: [open, withdrawn]}]`; OQ-12: the one-line rule summary written at `decide`; absent when open or withdrawn: owner-approved call, I4), `withdrawn` (`map {at: sha, by: str, reason: str}`; `required_when: [{status: [withdrawn]}]`, `absent_when: [{status: [open, answered]}]`; OQ-7), `plan` (`str`; `required_when: [{class: [merge-grant]}]`; absent for every other class; OQ-8), `program` and `stream` (`str`, `required: false`; merge grants only; OQ-8), `landed_in` (`list` of `cite`, `min: 1`; `required_when: [{status: [answered], effect: [lasting]}]`, `absent_when: [{effect: [one-off]}, {status: [open]}, {status: [withdrawn]}]`; spec §7.1: on withdrawal `withdrawn{at, by, reason}` "instead of the answer fields"), `asked_at` likewise shape only (OQ-11). `options` has `min: 2` for every class, grants included (spec §7.1: "A decision is an owner question with at least two options and their cost").
  - `decisions.py`: `validate(row: dict, cfg: dict) -> list` (schema errors, plus `class: <x> is not in decision_classes.owner_only`, against the merged list of Task 1a.2; for class `merge-grant`: `plan` has no `/` and no whitespace (both rules owner-approved calls, I9), and `program` and `stream` are both present or both absent and each matches `[a-z0-9][a-z0-9-]*`, and `stream` is not `integration` (spec §11); for any other class `plan`, `program` and `stream` are absent); `landed_errors(row: dict, root: str, cfg: dict, tracked: frozenset) -> list` (each `landed_in` cite, anchor stripped, is a tracked file that contains the row's id as a whole token (Global Constraints, "Whole-token match"; owner Q-rev2-2), and is on the allow-list (OQ-9): under `cfg["paths"]["playbooks"]`, exactly `CLAUDE.md`, or exactly `cfg["paths"]["architecture"]`; any other place fails `landed_in: <cite> is not a playbook, CLAUDE.md or architecture.md`; the anchor is not checked here, `gate_cites` checks it in block 5; a cite under `cfg["paths"]["specs"]` always fails `landed_in: <cite> is a spec; specs are cleaned, land the rule in a playbook, CLAUDE.md or architecture.md`); `is_resolved(row) -> bool` (`status != "open"`); `superseded_ids(records: list) -> set` (ids named in `supersedes` by an answered record only; a row that names itself counts nowhere: it is not a superseder for `superseded_ids`, `current`, `in_force` or `fork.<id>`, and its `supersedes.<id>` self error fails the tree; owner Q-1b2r-2); `ref_errors(records: list) -> list` of `(suffix, reason)`: `supersedes.<id>` (target missing, not answered, the row itself, or a cycle), `checked.<id>` (a `checked_against` id with no record); `current(records: list, id: str) -> str` (follows `supersedes` forward through answered records to the newest id); two open or answered records superseding one id is a `ref_errors` failure `fork.<id>`; a withdrawn superseder is ignored (owner Q-decisions-1 (b)); `in_force(records: list) -> list` (answered, `effect: lasting`, not superseded, class not `merge-grant`); `find(records: list, terms: list, path: Optional[str], topic: Optional[str], include_all: bool) -> list` (case-insensitive match of every term over question, answer and topics; `path` matched with `fnmatch.fnmatchcase` against each `applies_to` glob; every match, whatever its status, effect or class, replaced by `current(...)`, without repeats; in force only unless `include_all`, and with `include_all` no replacement; owner Q-1b2r-1).

**Input-domain dimensions:** every field against wrong types (from the schema checker); `status` against the presence of `answer`, `answered_at`, `rule`, `landed_in` and `withdrawn` (full matrix); `class` against `plan`, `program`, `stream` (grant with none, plan only, plan and program only, all three; non-grant with any; `plan` with `/` or space; `stream` with uppercase or `/`, `stream: integration`); `effect` against `landed_in`; `options` count 0, 1, 2 and empty `label` or `cost`; `class` (default list, a config-added class such as `hardware`, unknown, case); `landed_in` cite forms (plain path, `path#anchor`, path under `paths.specs`, absolute, `..`, untracked, tracked but lacking the id, the id only as a prefix of a longer token (fails), directory, a file under `paths.playbooks`, `CLAUDE.md`, `paths.architecture`, `README.md`, `path#missing-anchor` on an allowed file); `supersedes` (self, missing, open target, withdrawn target, chain of 3, cycle, two records superseding one); `checked_against` (empty, unknown id, wrong prefix); `find` terms (empty list, case, unicode, regex metacharacters), `path` glob semantics (`*` across `/`, `**`), `topic` exact or partial; `asked_at` and `answered_at.at` (7, 40, 41 hex characters, uppercase hex, a well-formed sha of no commit: accepted).

- [ ] **Step 1: Write the failing tests** (`tests/test_decisions_lib.py`; `OPEN`, `ANSWERED`, `WITHDRAWN` are valid fixture rows):
  ```python
  def test_valid_open_and_answered_rows():
      assert validate(OPEN, cfg) == [] and validate(ANSWERED, cfg) == []
  def test_status_field_matrix():             # subTest per status x {answer, answered_at, rule, landed_in, withdrawn}
      assert validate({**WITHDRAWN, "landed_in": ["CLAUDE.md"]}, cfg)       # F1: landed_in refused when withdrawn
      assert validate({**OPEN, "rule": "x"}, cfg) and validate({**ANSWERED, "withdrawn": W}, cfg)
  def test_one_option_refused_for_every_class():  # subTest per default class
      assert validate({**OPEN, "class": c, "options": [OPT]}, cfg)
  def test_lasting_answer_needs_landed_in():
      assert any(e.startswith("landed_in:") for e in validate(drop(ANSWERED, "landed_in"), cfg))
  def test_one_off_must_not_have_landed_in():
      assert validate({**ANSWERED, "effect": "one-off"}, cfg)              # landed_in still present
  def test_landed_in_spec_refused():          # docs/strict-delivery/specs/x.md contains the id
      assert "landed_in: docs/strict-delivery/specs/x.md is a spec; specs are cleaned, land the rule in a playbook, CLAUDE.md or architecture.md" in errs
  def test_landed_in_must_contain_id():       # CLAUDE.md tracked, without the id
      assert landed_errors(row, root, cfg, tracked)
  def test_withdrawn_row_shape():             # OQ-7
      assert validate(WITHDRAWN, cfg) == [] and validate(drop(WITHDRAWN, "withdrawn"), cfg)
      assert validate({**WITHDRAWN, "answer": "x"}, cfg) and validate({**OPEN, "withdrawn": W}, cfg)
  def test_grant_fields():                    # OQ-8
      assert validate(drop(GRANT, "plan"), cfg) and validate({**GRANT, "program": "p"}, cfg)
      assert validate({**OPEN, "plan": "p"}, cfg) and validate({**GRANT, "plan": "a/b"}, cfg)
  def test_landed_in_allow_list():            # OQ-9
      assert landed_errors(row_citing(".strict-delivery/playbooks/x.md"), root, cfg, tracked) == []
      assert landed_errors(row_citing("CLAUDE.md#no-such-anchor"), root, cfg, tracked) == []
      assert "landed_in: README.md is not a playbook, CLAUDE.md or architecture.md" in landed_errors(row_citing("README.md"), root, cfg, tracked)
  def test_sha_shape_only():                  # OQ-11: "a" * 40 names no commit
      assert validate({**ANSWERED, "asked_at": "a" * 40}, cfg) == []
      assert validate({**ANSWERED, "asked_at": "a" * 41}, cfg) and validate({**ANSWERED, "asked_at": "A" * 7}, cfg)
  def test_rule_optional_absent_when_open():  # OQ-12, I4
      assert validate(drop(ANSWERED, "rule"), cfg) == [] and validate({**OPEN, "rule": "r"}, cfg)
  def test_class_outside_owner_only_refused():  # I9
      assert "class: style is not in decision_classes.owner_only" in validate({**OPEN, "class": "style"}, cfg)
  def test_config_added_class_accepted():     # cfg with owner_only: [hardware] merged
      assert validate({**OPEN, "class": "hardware"}, cfg_hw) == []
  def test_in_force_excludes_superseded_grants_one_off():
      assert [r.id for r in in_force(records)] == [LASTING_CURRENT]
  def test_find_follows_supersedes_chain():   # A <- B <- C
      assert [r.id for r in find(records, ["term"], None, None, False)] == [C]
  def test_supersedes_cycle_and_fork_fail():
      assert any(x.startswith("supersedes.") for x in cycle_suffixes) and "fork." + A in fork_suffixes
  def test_withdrawn_superseder_ignored():    # Q-decisions-1: B supersedes A, B withdrawn, C supersedes A; records are store.Record (Q-1b2-1)
      assert ref_errors([A, B_withdrawn, C_open]) == [] and A.id not in superseded_ids([A, B_withdrawn, C_open])
      assert ("fork." + A.id) in [s for s, _ in ref_errors([A, B_open, C_open])]
  def test_find_by_path_glob_and_topic():     # applies_to ["src/*"] matches "src/a/b.py" (fnmatchcase)
      assert ids_for(path="src/a/b.py") == [D] and ids_for(topic="ids") == [D]
  ```
- [ ] **Step 2: Run the test command; expect FAIL.**
- [ ] **Step 3: Implement `schemas/decision.yml` and `decisions.py`.**
- [ ] **Step 4: Run the test command on both interpreters and `python3 -m gates check schema`; expect PASS.**
- [ ] **Step 5: Commit** `feat(lib): decision schema, rules, in-force and find`, then checkpoint.

### Task 1b.3: finding schema and finding rules

**Files:**
- Create: `gates/schemas/finding.yml`, `gates/lib/findings.py`
- Test: `tests/test_findings_lib.py`

**Owner answers applied:** OQ-5, OQ-6, OQ-15, OQ-16; Q-1b3-1 (a) a superseded but still answered decision counts as a deferred finding's `ruling`; Q-1b3-2 (a) a resolved row's `parent` is checked for self-reference and cycles only, not for a missing parent; Q-1b3-3 (b) a plain-path evidence entry of a resolved row is checked for existence in `tracked` only when the row changed against the merge base, sha-pinned entries always; Q-1b3r-1 (b) a deferred finding's `ruling` names an answered decision whose class is not `merge-grant`; Q-ES (a) owner 2026-11-01: three optional fields `review_round`, `caused_by_change` and `dimension` (below).

**Controller rows (brief 2026-11-01; input-domain rows E20, D5 fail closed):** records are `store.Record` lists and a suffix names the row carrying the field (as Task 1b.2); "answered" checks test `status == "answered"` and `decisions.validate(row, cfg) == []`, never `decisions.is_resolved`; `finding.yml` declares the required `schema` field; `commit_exists(root, sha)` and `blob_exists(root, sha, path)` take `root` first.

**Interfaces:**
- Consumes: `schema.*`, `ids.id_problem`, `decisions.validate`, `gitinfo.commit_exists/blob_exists/tracked_files`, `store.Record`.
- Produces:
  - `findings.py` constants: `STATUSES = ["open", "planned", "in-progress", "fixed-unpinned", "pinned", "deferred", "closed", "merged"]` (spec §7.2); `RESOLVED = {"closed", "merged"}`; `SEVERITIES = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]`; `TRANSITIONS = {"open": ["planned", "deferred", "closed"], "planned": ["in-progress", "open", "deferred"], "in-progress": ["fixed-unpinned", "pinned", "planned"], "fixed-unpinned": ["pinned"], "pinned": ["closed", "merged"], "deferred": ["open", "planned"], "closed": ["merged"], "merged": []}` (the table the owner approved with the earlier plan). OQ-6: only the cleanup step (programs block) may set `merged`; in block 1 `merged` is unreachable and `closed` is final, so `validate` refuses `status: merged` and any `merged` history entry with `status: merged is set only by the cleanup step`.
  - `gates/schemas/finding.yml` (`finding/1`, `files: [{dir: findings, glob: "*.yml", exclude: [index.yml]}]`). Fields: `id` (`id`, `id_kind: finding`), `status` (`enum` of `STATUSES`), `source` (`str`), `severity` (`enum` of `SEVERITIES`), `class` (`str`), `siblings` (`list` of `str`), `cites` (`list` of `map {file: str, lines: str, sha: sha}`), `repro` (`str`, `nullable`), `owner` (`map`, fields declared in the schema, never hand-coded (spec §7.2; controller ruling R-rev3-1): `kind` (`enum [plan, issue, roadmap]`), `plan` (`str`; `required_when: [{kind: [plan, roadmap]}]`, `absent_when: [{kind: [issue]}]`), `task` (`str`; `required_when: [{kind: [plan]}]`, `absent_when: [{kind: [issue, roadmap]}]`), `number` (`int`, `min: 1`; `required_when: [{kind: [issue]}]`, `absent_when: [{kind: [plan, roadmap]}]`); any other key gives `owner.<key>: unknown key` (OQ-16)), `pin` (`map {test: str, transcript: sha-path}`, `nullable`; owner Q-plan-4), `ruling` (`id`, `id_kind: decision`, `nullable`), `evidence` (`list` of `str`), `history` (`list`, `min: 1`, items `map {status: enum of STATUSES, sha: sha, by: str}`), `parent` (`id`, `id_kind: finding`, `required: false`), `resolved_by` (`str`; `required_when: [{status: [closed, merged]}]`, `absent_when: [{status: [open, planned, in-progress, fixed-unpinned, pinned, deferred]}]`; spec §7.2 "names the plan that resolved it (`resolved_by: <plan>`)"; a plan name has no `/` and no whitespace, an owner-approved call, I9), and three optional fields, absent is valid, shape-checked only, no cross-field rules (owner Q-ES): `review_round` (`int`, `min: 1`; the review round that raised the finding), `caused_by_change` (`bool`; the change under review caused it), `dimension` (`str`; one canonical input dimension, the input-domain table's row name).
  - `validate(row: dict, cfg: dict) -> list`; `transition_errors(row) -> list` (history starts at `open`; each step is in `TRANSITIONS`; the last history status equals `status`); `evidence_errors(row: dict, root: str, cfg: dict, decision_records: list, tracked: frozenset, changed: bool = True) -> list` (`changed` is true when the row is new or differs from its merge-base version; Q-1b3-3; the default fails closed; `deferred` needs `ruling` naming an answered decision whose class is not `merge-grant` (Q-1b3r-1); `closed` needs at least one evidence entry; `pinned` needs `pin` and a review-report entry in `evidence` under `cfg["paths"]["reviews"]`; `pin.test` is an opaque non-empty string, never matched against a pattern (spec §13a); `pin.transcript` is a `<sha>:<path>` only (owner Q-plan-4), with `commit_exists(sha)` and `blob_exists(sha, path)`, and its path under `<paths.plan_state>/<owner.plan>/mutations/` when the owner kind is `plan`, else under `<paths.plan_state>/*/mutations/` for any plan (owner Q-rev2-3); OQ-15: an evidence entry is a commit sha (`commit_exists`), a `<sha>:<path>` (`commit_exists(root, sha)` and `blob_exists(root, sha, path)`), or a plain path that `tracked` holds (checked only while the row is unresolved or `changed`) and that lies outside every per-effort path (`paths.specs`, `paths.plans`, `paths.plan_state`, `paths.reviews`, `paths.programs`, `paths.claims`) and outside `paths.findings`, open findings included (owner Q-plan-5, spec §5); per-effort files, review reports, transcripts and finding records are cited only as `<sha>:<path>`); `epic_errors(records: list) -> list` of `(suffix, reason)` (`parent.<id>`: the parent is missing, is the row itself, or forms a cycle; `epic.<id>`: a resolved parent with an unresolved child); `is_resolved(row) -> bool` (`status in RESOLVED`); `may_delete(row: dict, root: str, cfg: dict, decision_records: list) -> bool` (OQ-5: true only when the row is resolved and an answered decision of class `merge-grant` has `plan` equal to the row's `resolved_by`; the merge-commit check arrives with `gate_cleanup`).

**Input-domain dimensions:** every field against wrong types; `owner` kinds against their key sets (unknown `kind`, `kind` missing, extra key, missing key, `number` 0, negative, `bool`, str; `owner` not a mapping); `history[].status` outside `STATUSES`; every `(from, to)` pair of `STATUSES` (64 pairs); `history` (empty, first not `open`, last differing from `status`, any `merged` entry); evidence entry forms (bare full sha, short sha, ambiguous short sha, tree or blob sha as the commit, `<sha>:<path>` with the path absent at the sha, a directory at the sha, a path holding `:`, a plain tracked path, a plain untracked path, absolute, `..`, a plain tracked path under each per-effort path, a plain tracked path to an open and to a resolved finding under `paths.findings`: refused, a plain tracked path under `paths.playbooks`); `pin.transcript` form and location (a plain path: refused, `<sha>:<path>` with the sha not a commit or the path absent at it, inside and outside `mutations/`, another plan's folder with owner kind `plan`: refused, any plan's folder with another owner kind: accepted); `ruling` target (missing, open, withdrawn, superseded, answered); `resolved_by` (missing on `closed` and `merged`, present on `open`, holding `/` or whitespace); `parent` (missing, self, two-step cycle, resolved parent with open child); `may_delete` cases (unresolved row; resolved with no grant, with an open grant, with a withdrawn grant, with an answered grant for another plan, with an answered grant for its plan).

- [ ] **Step 1: Write the failing tests** (`tests/test_findings_lib.py`; `FINDING` is a valid open row, `ev(...)` calls `evidence_errors(row, root, cfg, decisions, tracked)`):
  ```python
  def test_valid_finding():
      assert validate(FINDING, cfg) == []
  def test_owner_shapes():                    # F8
      assert validate({**FINDING, "owner": {"kind": "plan", "plan": "p", "task": "1a.2"}}, cfg) == []
      assert any(e.startswith("owner.task:") for e in validate({**FINDING, "owner": {"kind": "plan", "plan": "p"}}, cfg))
      assert any(e.startswith("owner.plan:") for e in validate({**FINDING, "owner": {"kind": "issue", "number": 3, "plan": "p"}}, cfg))  # absent_when
      assert "owner.x: unknown key" in validate({**FINDING, "owner": {"kind": "issue", "number": 3, "x": 1}}, cfg)
      for n in [0, -1, True, "3"]: assert validate({**FINDING, "owner": {"kind": "issue", "number": n}}, cfg)
  def test_history_status_enum():
      assert validate({**FINDING, "history": [{"status": "done", "sha": SHA, "by": "x"}]}, cfg)
  def test_pin_test_is_opaque():
      assert validate({**PINNED, "pin": {"test": "npx jest -t 'adds totals'", "transcript": SHA + ":" + T}}, cfg) == []
  def test_transition_table_all_pairs():      # 64 subTests
      assert (transition_errors(row(a, b)) == []) == (b in TRANSITIONS[a])
  def test_history_last_equals_status():
      assert transition_errors({**FINDING, "status": "planned"})
  def test_merged_unreachable_in_block_1():   # OQ-6
      assert "status: merged is set only by the cleanup step" in " ".join(validate(MERGED, cfg))
      assert validate(CLOSED, cfg) == []
  def test_deferred_needs_answered_ruling():  # subTests: missing, open, withdrawn ruling
      assert ev({**DEFERRED, "ruling": OPEN_DEC})
  def test_resolved_by_required_on_closed_and_merged():
      assert validate(drop(CLOSED, "resolved_by"), cfg) and validate({**FINDING, "resolved_by": "p"}, cfg)
  def test_evidence_sha_path_survives_cleanup():  # Review Focus 4; r = docs/strict-delivery/reviews/p/r.md, deleted after commit c
      assert ev({**CLOSED, "evidence": [c + ":" + r]}) == []
      assert ev({**CLOSED, "evidence": [r]}) and ev({**CLOSED, "evidence": ["f" * 40 + ":" + r]})
      assert ev({**CLOSED, "evidence": [c + ":no/such/file"]})
  def test_plain_path_evidence_outside_per_effort_only():  # OQ-15, Q-plan-5
      assert ev({**CLOSED, "evidence": [".strict-delivery/playbooks/x.md"]}) == []
      for p in ["docs/strict-delivery/reviews/p/r.md", ".strict-delivery/state/findings/" + OPEN_F + ".yml",
                ".strict-delivery/state/findings/" + CLOSED_F + ".yml"]:
          assert ev({**CLOSED, "evidence": [p]})
  def test_transcript_is_sha_path_under_mutations():  # Q-plan-4
      assert ev({**PINNED, "pin": {"test": "t", "transcript": c + ":.strict-delivery/state/plans/p/mutations/F.txt"}}) == []
      assert ev({**PINNED, "pin": {"test": "t", "transcript": ".strict-delivery/state/plans/p/mutations/F.txt"}})
      assert ev({**PINNED, "pin": {"test": "t", "transcript": c + ":.strict-delivery/state/plans/p/F.txt"}})
  def test_resolved_plain_path_checked_only_when_changed():  # Q-1b3-3
      gone = {**CLOSED, "evidence": ["renamed/away.md"]}
      assert ev(gone) and ev(gone, changed=False) == []
      assert ev({**CLOSED, "evidence": [c + ":no/such/file"]}, changed=False)
  def test_epic_resolved_parent_with_open_child_fails():
      assert ("epic." + PARENT, ANY) in epic_errors(records)
  def test_may_delete():                      # OQ-5; each grant is a store.Record(row['id'], row, path)
      assert may_delete(CLOSED, root, cfg, [answered_grant(plan=CLOSED["resolved_by"])]) is True
      for d in [[], [open_grant], [withdrawn_grant], [answered_grant(plan="other")]]: assert may_delete(CLOSED, root, cfg, d) is False
      assert may_delete(FINDING, root, cfg, [answered_grant(plan="p")]) is False
  ```
- [ ] **Step 2: Run the test command; expect FAIL.**
- [ ] **Step 3: Implement `schemas/finding.yml` and `findings.py`.**
- [ ] **Step 4: Run the test command on both interpreters and `python3 -m gates check schema`; expect PASS.**
- [ ] **Step 5: Commit** `feat(lib): finding schema and rules; sha:path evidence`, then checkpoint. **Block 1b end:** as block 1a.

---

## Block 1c0: library hardening and the `cites` registration (branch `block/b1c`)

Owner answer F-docs-11 (c) (2026-11-02): this task is a sub-block of its own, with its own pull request from `block/b1c`, so block 1c keeps the cap of 3 tasks. Its id is `1c0.1` (checkpoint `CHECKPOINT 1c0 1c0.1 ...`, `next=1c.1`), so Task 6K.1's counting (`### Task <block>.<n>:` headings, `<block>.` ledger tokens) gives block 1c0 one task and block 1c three (docs review 2, F-docs2-3). Ledger lines that say `1c.0` are history.

### Task 1c0.1: library hardening (owner Q-U2, Q-1bfin-2, U-1bfin-1); register `check cites` (owner Q-C2fin-1 (a))

**Files:**
- Modify: `gates/lib/result.py` (`_raw`, `run_check`), `gates/lib/gitinfo.py` (the root-taking functions), `gates/lib/store.py` (`Store`, `base_errors`; the reasons at lines 71 and 227), `gates/lib/config.py` (`load`), `gates/lib/findings.py` (`evidence_errors`, `may_delete`; the reason at line 94), `gates/lib/schema.py` (the reason at line 350), `gates/lib/decisions.py` (the reason at line 122), `gates/__main__.py` (`GATES` gains `cites`; `_check` imports inside the gate's check)
- Test: `tests/test_result.py`, `tests/test_gitinfo.py`, `tests/test_store.py`, `tests/test_config.py`, `tests/test_findings_lib.py`, `tests/test_decisions_lib.py`, `tests/test_schema_lib.py`, `tests/test_gate_schema.py` (the dispatcher tests)

**Owner answers applied:** Q-U2 (a map item in a reason is escaped exactly once); Q-1bfin-2 (a) (every library function taking a repository root refuses a root that is not the top level); U-1bfin-1 (`store.base_errors` checks that the `Store` it is given belongs to the root it is given); Q-1a-fin-1 (the existing `_require_toplevel` rule, now applied everywhere); Q-C2fin-1 (a) (stream A registers `cites` in the `check` dispatcher in this task, stream C's request R-20261102-bn3p); Q-1c0-1 (a), Q-1c0-2 (a), Q-1c0-3 (a), Q-1c0-4 (a) (owner, 2026-11-02; below).

**Interfaces:**
- Consumes: `gitinfo._require_toplevel/toplevel`, `result.Result/render/safe_text/_exc_text/run_check`, `store.Store/base_errors`, `config.load`, `findings.evidence_errors/may_delete`, `decisions.landed_errors`, `helpers.make_repo/GitIsolatedTestCase`.
- Produces (every signature unchanged):
  - `result._raw(x)` gains a mapping case: a `dict` renders as `{` + `, `.join(`_raw(key) + ": " + _raw(value)`) + `}`, in insertion order, recursively, like the list case. It keeps the ids of the containers on the current path and renders a container that contains itself as `{...}` (a map) or `[...]` (a list), as `repr` does; depth past the recursion limit is not handled (Q-1c0-3 (a)). So `Result.render`'s one `safe_text` pass is the only escaping a map key or value gets: a backslash in a value prints as `\\`, never `\\\\`, and a newline as `\n`, never `\\n`.
  - `run_check`'s `GateError` branch renders a single argument with `_raw` instead of `str(e)`, so a map reason gets the same one-pass rendering; without this the map case of `_raw` alone cannot make `test_map_item_escaped_once` pass (PC1 table mismatch M1).
  - The other reasons that format a caller value with `%s` or `str()` pass it through `_raw` (Q-1c0-2 (a); `class: reason value: map`): `store.py:71` (`cannot use id ...`), `store.py:227` (`file name ... differs from the record id ...`), `schema.py:350` (`schema: expected ..., got ...`), `findings.py:94` (`status: ... differs from the last history entry ...`) and `decisions.py:122` (the `landed_in` cite). One test each.
  - Root check (Q-1bfin-2 (a)): every library function with a `root` parameter calls `gitinfo._require_toplevel(root)` before any other work, and so raises `GateError`: for a subdirectory of a repository the text is `git rev-parse --show-toplevel: root must be the repository top level`; for a missing path or a directory outside any repository it is `git rev-parse --show-toplevel failed (exit 128)`, from `toplevel(root)` inside the check (measured 2026-11-02 on both). Newly covered: `gitinfo.head_sha`, `commit_exists`, `merge_base`, `user_email`; `store.Store.__init__` (so `load`, `create` and `replace` inherit it) and `store.base_errors`; `config.load`; `findings.evidence_errors` and `findings.may_delete`. Already covered and unchanged: `gitinfo.blob_exists`, `tracked_files`, `show`, `ls_tree`, `decisions.landed_errors`, `schema.entries_of`, and `schema.files_of` through `entries_of`. `gitinfo.toplevel` is the one exception: it is how the top level is found. Gates already resolve `--root` to the top level, so their behaviour does not change; a missing config still fails `<gate>.input` naming `/strict-delivery:init` (Review Focus 5).
  - `store.base_errors(root, store, base, is_resolved, may_delete)`: before reading git, it raises `GateError("base_errors: the store's root <a> is not the root given <b>")` unless `os.path.samefile(store.root, root)` (U-1bfin-1), so a record set from one tree is never compared with another tree's history.
  - `gates/__main__.py`: `GATES` gains `"cites": "gates.gate_cites"` (Q-C2fin-1 (a); R-20261102-bn3p). The import stays lazy and moves inside the check callable `_check` passes to `run_gate`, so the gate contract covers it: no other command, `check schema` included, imports `gates.gate_cites`. `gates/gate_cites.py` is stream C's (Task C2.2) and is not on `block/b1c`; until C's pull request has merged, `check cites` prints one line `FAIL cites.input: gates/gate_cites.py missing (stream C, Task C2.2)` and exits 1, `--json` honoured, never a traceback; any other import failure becomes `FAIL cites.input: <Type>: <text>` (Q-1c0-1 (a)). No commit gate runs `check cites` before then. `gates/producers.py` is not changed (C2.2 declares no kind here).
- Existing tests this task changes on purpose (PC1 table mismatch M6): `tests/test_gitinfo.py`'s `assertIsNone(gitinfo.user_email(plain))` on a non-repository directory (now `GateError`, exit 128 text); `tests/test_config.py::test_missing_config_through_run_gate`'s non-git case (now `FAIL x.input: git rev-parse --show-toplevel failed (exit 128)`; the top-level case keeps the init hint); `tests/test_gate_schema.py::test_E2_check_command_form`'s usage line (now `gates: cites, schema`). The implementer edits exactly these three and names them in the report.
- Cross-stream note: stream C's `tests/test_gate_cites.py` has a line that pins today's repr-style output for a map item in a reason. It changes when C next updates from `main` past this task. That line is C's to fix in its own file (stream rules, "Keeping up with `main`"); A raises no edit to it.

**Input-domain dimensions:**
- `_raw` values: a flat `dict`; nested `dict` in `list` and `list` in `dict`; keys and values holding a backslash, a newline, a tab, a quote, a non-printable character, non-ASCII; an empty `dict`; a `dict` subclass (`OrderedDict`); a non-`str` key (`int`, `None`); a value that is a `GateError` reason passed through `run_check` (the decisions reason path) and a map item as `gate_cites` prints it.
- Root forms, for each newly covered function: the top level; a subdirectory; a symlink to the top level (`samefile` accepts it); a path with a trailing `/`; a missing path; a regular file; a directory outside any repository; a linked worktree's top level (accepted); a bare repository.
- `base_errors` stores: a `Store` built on the same root; on a symlink to it (accepted); on another clone of the same repository (refused); on a subdirectory (refused already at `Store(...)`).
- `config.load`: a subdirectory of a repository that has a config (refused, not silently read from the top level).
- Dispatcher: `check cites` with `gates/gate_cites.py` absent (this branch: one `FAIL cites.input` line, exit 1, also under `--json`), present (after stream C merges), and failing to import for another reason; `check schema` run in-process (must not import `gates.gate_cites`); the usage line lists `cites`.
- Reasons (Q-1c0-2 (a)): a map value at each of the five reason sites; a self-containing `dict` and `list` (Q-1c0-3 (a)).

- [ ] **Step 1: Write the failing tests:**
  ```python
  # test_result.py
  def test_map_item_escaped_once():            # Q-U2
      r = run_check("g", lambda a: (_ for _ in ()).throw(GateError({"k": "a\\b\nc"})), [])
      assert r.render() == "FAIL g.input: {k: a\\\\b\\nc}"
  def test_nested_map_and_list_escaped_once():
      assert _raw({"a": ["x\\y", {"b": "\n"}]}) == "{a: [x\\y, {b: \n}]}"
  # test_gitinfo.py, test_store.py, test_config.py, test_findings_lib.py
  def test_subdirectory_root_refused_everywhere():   # Q-1bfin-2 (a); subTest per function
      for call in (lambda r: head_sha(r), lambda r: commit_exists(r, "HEAD"), lambda r: merge_base(r, "HEAD", "HEAD"),
                   lambda r: user_email(r), lambda r: Store(r, "decision", cfg), lambda r: config.load(r),
                   lambda r: evidence_errors(ROW, r, cfg, [], frozenset()), lambda r: may_delete(ROW, r, cfg, [])):
          with self.assertRaises(GateError) as e: call(sub)
          assert "root must be the repository top level" in str(e.exception)
          with self.assertRaises(GateError) as e: call(missing)
          assert "git rev-parse --show-toplevel failed" in str(e.exception)
  def test_symlinked_top_level_accepted():
      assert head_sha(link) == head_sha(root)
  def test_base_errors_refuses_foreign_store():      # U-1bfin-1
      with self.assertRaises(GateError) as e: base_errors(root, Store(clone, "decision", cfg), "HEAD", is_resolved, never)
      assert "is not the root given" in str(e.exception)
  # test_decisions_lib.py
  def test_decision_reason_with_map_item_escaped_once():
      assert "\\\\\\\\" not in render_of(map_reason_case)
  # test_gate_schema.py (dispatcher)
  def test_cites_registered_lazily():               # Q-C2fin-1 (a)
      assert gates_main.GATES["cites"] == "gates.gate_cites"
      gates_main.main(["check", "schema", "--root", root])
      assert "gates.gate_cites" not in sys.modules
  def test_check_cites_missing_module_fails_closed():   # Q-1c0-1 (a); skipTest once gates/gate_cites.py exists
      assert code == 1 and out == "FAIL cites.input: gates/gate_cites.py missing (stream C, Task C2.2)\n"
  def test_check_cites_runs():                      # Q-1c0-4 (a); skipTest naming gates/gate_cites.py while it is absent (until stream C merges)
      assert code == 0 and all(l.startswith("PASS cites.") for l in lines_of(minimal_make_repo_tree))   # reaches the gate only; C's tests cover verdicts
  def test_raw_self_containing_containers():        # Q-1c0-3 (a)
      d = {}; d["a"] = d; l = []; l.append(l)
      assert _raw(d) == "{a: {...}}" and _raw(l) == "[[...]]"
  def test_reason_sites_render_map_once():          # Q-1c0-2 (a); subTest per site: store.py:71, :227, schema.py:350, findings.py:94, decisions.py:122
      assert "\\\\\\\\" not in rendered and "{'" not in rendered
  ```
- [ ] **Step 2: Run the test command; expect FAIL.**
- [ ] **Step 3: Implement** the `_raw` mapping case, the root checks and the `base_errors` store check. Add `"cites": "gates.gate_cites"` to `GATES`. Write one mutant per changed condition (PC3): drop each `_require_toplevel` call, drop the `samefile` check, render a `dict` with `str()`, drop the `cites` entry, import every `GATES` module at load time, let the import error escape `_check`, use `str(e)` again in `run_check`, revert each reason site to `%s`, and drop the cycle guard; each mutant must fail a test.
- [ ] **Step 4: Run the test command on both interpreters with `-W error`, and every enabled gate (`check schema`); expect PASS.**
- [ ] **Step 5: Commit** `fix(lib): escape map items once; every root-taking function refuses a non-toplevel root; base_errors checks its store's root; register check cites`, then checkpoint. This lands the registration part of R-20261102-bn3p; its `run_all` part waits for block 2 (stream rules, "Cross-stream order"). Checkpoint line: `CHECKPOINT 1c0 1c0.1 head=<sha> tests=<p>/<t> gates=PASS next=1c.1`. **Block 1c0 end:** final review, verifier, then the pull-request flow of Process for this plan, "Blocks" (branch `block/b1c`); checkpoint; continuation.

---

## Block 1c: gates and indexes (branch `block/b1c1`)

Block 1c starts from `main` after block 1c0's pull request has merged.

### Task 1c.1: `gate_decisions`; enable `check decisions`

**Files:**
- Create: `gates/gate_decisions.py`; Modify: `gates/__main__.py` (register `check decisions`)
- Test: `tests/test_gate_decisions.py`

**Owner answers applied:** OQ-4, OQ-9, OQ-10.

**Interfaces:**
- Consumes: `Store`, `store_errors`, `base_errors`, `decisions.*`, `gitinfo.*`, `result.*`, `config.load`.
- Produces: `PRODUCES = ()`; `check(args: list) -> Result` (gate `decisions`) and `main(argv=None) -> int`. Arguments: `--root`, `--base REF` (default `cfg["base_branch"]`; OQ-4; an absent ref fails `decisions.input`). Categories, each printing one `PASS decisions.<cat>` when nothing in it failed: `schema` (`decisions.schema.<id>` per `decisions.validate` error), `store` (`decisions.store.<suffix>`), `base` (`decisions.base.<suffix>` from `base_errors` with `may_delete` always false), `landed` (`decisions.landed.<id>`), `refs` (`decisions.refs.<suffix>` from `ref_errors`), `open-ref` (OQ-10: the scanned files are the tracked files matching any `cfg["decisions"]["scan"]` glob (`fnmatch.fnmatchcase`, so `*` crosses `/`) and not under `cfg["paths"]["state"]`; no scanned file references the id of an open decision; one line per occurrence, `FAIL decisions.open-ref.<file>:<line>`, reason `<file>:<line> references unanswered <id>; the human answers it first`), `scan` (`FAIL decisions.scan.<file>`; an unreadable scanned file fails here and withholds the `open-ref` PASS). Ids are matched as whole tokens (Global Constraints, "Whole-token match").

**Input-domain dimensions:** argv (`--root` missing directory or not a repo, `--base` absent ref, `--json` position, unknown flag); repository states (no config, empty registers, no decisions directory, a finding file in the decisions directory); each category's failing inputs as listed in Tasks 1a.3 and 1b.2; open-reference scan (scan globs matching, not matching, a file under `paths.state` that a glob matches, a config with `decisions.scan: []`; file kinds: binary, invalid UTF-8, symlink, large; id positions: line start, line end, inside a code block, as a prefix of a longer token (`DEC-20261031-k3f9a`), as a suffix of a longer token (`XDEC-20261031-k3f9`, `_DEC-...`, `-DEC-...`), between punctuation (`(DEC-20261031-k3f9),`), in a handoff `open_decisions` field (under `paths.state`, so not scanned), in another decision's `checked_against` or `supersedes` (registers, not scanned)).

- [ ] **Step 1: Write the failing tests** (`tests/test_gate_decisions.py`; each builds a repo with `helpers.make_repo` and writes records with `helpers.write_record`; `out, code = run(root, *args)` calls `gate_decisions.main`):
  ```python
  def test_empty_registers_pass_every_category():
      for c in ["schema", "store", "base", "landed", "refs", "open-ref", "scan"]: assert "PASS decisions." + c in out
      assert code == 0
  def test_deleted_base_decision_fails():     # Review Focus 1, --base HEAD after git rm
      assert "FAIL decisions.base.deleted." + ID in out
  def test_edited_answered_decision_fails_with_remedy():  # Review Focus 2
      assert "FAIL decisions.base.immutable." + ID in out and "supersedes" in line_for(out, ID)
  def test_lasting_landed_in_must_cite_id():
      assert "FAIL decisions.landed." + ID in out
  def test_landed_in_spec_fails():
      assert "FAIL decisions.landed." + ID in out and "is a spec" in out
  def test_supersedes_open_decision_fails_refs():
      assert "FAIL decisions.refs.supersedes." in out
  def test_open_ref_in_docs_fails():          # docs/a.md line 3 holds OPEN_ID
      assert "docs/a.md:3 references unanswered " + OPEN_ID + "; the human answers it first" in out
  def test_open_ref_in_untracked_file_ignored():
      assert "PASS decisions.open-ref" in out
  def test_open_ref_longer_token_ignored():   # F6: OPEN_ID + "a", "X" + OPEN_ID, "_" + OPEN_ID, "-" + OPEN_ID
      assert "PASS decisions.open-ref" in out
  def test_open_ref_whole_token_at_edges():   # "(" + OPEN_ID + ")," and OPEN_ID alone at end of file
      assert out.count("references unanswered " + OPEN_ID) == 2
  def test_open_ref_state_dirs_excluded():    # .strict-delivery/state/plans/p/handoff.md
      assert "PASS decisions.open-ref" in out
  def test_open_ref_in_playbook_fails():
      assert ".strict-delivery/playbooks/x.md:1 references unanswered " + OPEN_ID in out
  def test_default_base_is_merge_base_with_main():  # branch off main deletes a record committed on main; no --base
      assert "FAIL decisions.base.deleted." + ID in out
  def test_landed_in_outside_allow_list_fails():  # OQ-9: README.md
      assert "FAIL decisions.landed." + ID in out
  def test_answered_ref_passes():
      assert "PASS decisions.open-ref" in out and code == 0
  def test_missing_config_is_input_fail():
      assert out.startswith("FAIL decisions.input:")
  def test_json_output_shape():
      assert json.loads(out)                  # parses; it carries the same lines as the text form
  ```
- [ ] **Step 2: Run the test command; expect FAIL.**
- [ ] **Step 3: Implement `gates/gate_decisions.py`.** Config is read from the target `--root`, never from the code checkout.
- [ ] **Step 4: Run the test command on both interpreters; expect PASS.**
- [ ] **Step 5: Enable on this repository.** Run `python3 -m gates check decisions` and `python3 -m gates check schema`; expect all `PASS`, exit 0.
- [ ] **Step 6: Commit** `feat(gates): gate_decisions; enable check decisions`, then checkpoint with `gates=PASS`.

### Task 1c.2: `gate_register`; enable `check register`

**Files:**
- Create: `gates/gate_register.py`; Modify: `gates/__main__.py` (register `check register`)
- Test: `tests/test_gate_register.py`

**Owner answers applied:** OQ-4, OQ-5, OQ-6, OQ-18.

**Interfaces:**
- Consumes: `Store`, `store_errors`, `base_errors`, `findings.*`, `decisions.is_resolved`, `gitinfo.*`, `result.*`.
- Produces: `PRODUCES = ()`; `check(args: list) -> Result` (gate `register`), `main(argv=None) -> int`; arguments `--root`, `--base REF` (as Task 1c.1). Categories (line ids `register.<cat>.<id>` for schema, transition, evidence and epic; `register.<cat>.<suffix>` for store and base): `schema`, `store`, `base` (with `may_delete=lambda row: findings.may_delete(row, root, cfg, decision_records)`), `transition`, `evidence`, `epic`, `report` (OQ-18: every tracked file under `cfg["paths"]["reviews"]` whose first line matches `<!-- schema: review-report/[1-9][0-9]* -->` is a review report; every finding id in it, matched as a whole token (Global Constraints, "Whole-token match") with the finding prefix, names a finding record, else `FAIL register.report.<file>: <id> is not in the register`; files without that first line are ignored; a missing reviews directory is no reports). Ids across both registers are unique: a decision id inside the findings directory, or the reverse, fails `register.store.id.<file>` through the prefix check.

**Input-domain dimensions:** argv as Task 1c.1; repository states (no findings directory, a decision file in the findings directory); each category's failing inputs as listed in Tasks 1a.3 and 1b.3; base cases for findings (open finding deleted, resolved finding deleted with and without an answered grant for its `resolved_by` plan, closed changed to merged, resolved finding edited); report scanning (first line exact, with BOM, with CRLF, with version 0, on line 2; id as a prefix or a suffix of a longer token, such as `F-20261031-k3f9a` and `XF-20261031-k3f9`; an unknown id that is a well-formed whole token; reviews directory missing; untracked report).

- [ ] **Step 1: Write the failing tests** (`tests/test_gate_register.py`; `out, code = run(root, *args)` calls `gate_register.main`):
  ```python
  def test_empty_registers_pass():
      for c in ["schema", "store", "base", "transition", "evidence", "epic", "report"]: assert "PASS register." + c in out
  def test_deleted_open_finding_fails():
      assert "FAIL register.base.deleted." + F in out
  def test_deleted_resolved_finding_needs_grant():  # OQ-5
      assert "FAIL register.base.deleted." + F in out_without_grant
      assert "register.base.deleted." + F not in out_with_answered_grant_for_resolved_by
  def test_edited_resolved_finding_fails_immutable():
      assert "FAIL register.base.immutable." + F in out
  def test_closed_to_merged_refused():        # OQ-6
      assert "FAIL register.schema." + F in out and "cleanup step" in line_for(out, F)
  def test_illegal_transition_fails():        # history open -> pinned
      assert "FAIL register.transition." + F in out
  def test_closed_without_resolved_by_fails_schema():
      assert "FAIL register.schema." + F in out
  def test_decision_file_in_findings_dir_fails():
      assert "FAIL register.store.id." in out
  def test_missing_config_is_input_fail():
      assert out.startswith("FAIL register.input:")
  def test_report_cites_unknown_finding():    # OQ-18; first line <!-- schema: review-report/1 -->
      assert "FAIL register.report.docs/strict-delivery/reviews/p/r.md: F-20261031-zzzz is not in the register" in out
  def test_report_whole_token_match():        # F6: "XF-20261031-k3f9" and "F-20261031-k3f9a", no such records
      assert "PASS register.report" in out
  def test_untagged_report_ignored():         # first line on line 2, BOM, version 0: each ignored
      assert "PASS register.report" in out
  ```
- [ ] **Step 2: Run the test command; expect FAIL.**
- [ ] **Step 3: Implement `gates/gate_register.py`.**
- [ ] **Step 4: Run the test command on both interpreters; expect PASS.**
- [ ] **Step 5: Enable on this repository.** Run `python3 -m gates check register`, `check decisions` and `check schema`; expect all `PASS`, exit 0.
- [ ] **Step 6: Commit** `feat(gates): gate_register; enable check register`, then checkpoint with `gates=PASS`.

### Task 1c.3: indexes, `in-force.md`, overview; their schemas; ignore generated files

**Files:**
- Create: `gates/tools/__init__.py`, `gates/tools/index.py`, `gates/schemas/decision-index.yml`, `gates/schemas/finding-index.yml`, `gates/schemas/in-force.yml`, `gates/schemas/overview.yml`; Modify: `gates/__main__.py` (register `index`), `gates/producers.py` (add `gates.tools.index`), `.gitignore`
- Test: `tests/test_index.py`

**Owner answers applied:** OQ-12, OQ-13, OQ-17.

**Interfaces:**
- Consumes: `Store`, `decisions.in_force/superseded_ids/is_resolved`, `findings.is_resolved`, `schema.validate/validate_markdown`, `yamlsub.emit`, `config.load`.
- Produces:
  - `index.py`: `PRODUCES = ("decision-index", "finding-index", "in-force", "overview")`; `render(root: str, cfg: dict) -> dict` (repo-relative path to text, for the four files); `regenerate(root: str, cfg: dict) -> list` (creates missing parent directories, writes `render`'s files, returns their paths; output is byte-identical across runs and interpreters); `main(argv: list) -> int` for `python3 -m gates index [--root R]`.
  - `<paths.decisions>/index.yml`: `schema: decision-index/1`, `decisions:` mapping each id to `{file, status, class, topics}`, where `status` is `superseded` for a superseded answered decision and the record's `status` otherwise.
  - `<paths.findings>/index.yml`: `schema: finding-index/1`, `findings:` mapping each id to `{file, status, severity, owner}` (`owner` rendered as one string, such as `plan:<plan>/<task>`, `issue:<n>`, `roadmap:<plan>`).
  - `<paths.decisions>/in-force.md`: first line `<!-- schema: in-force/1 -->`, then `# In-force decisions (generated; do not edit)`, then a table with header `id | topics | rule | landed_in` (owner-approved call, I8), one row per `in_force(...)` decision (spec §7.4 "one table row per lasting decision still in effect (id, topic, rule summary, landed_in)"), `rule` is the decision's `rule` field (OQ-12), an empty cell when the record has none (owner-approved call, I2); `|` inside a cell escaped as `\|`.
  - `<paths.index>` (`INDEX.md`): first line `<!-- schema: overview/1 -->`, then (OQ-13: only the sections block 1 can fill) the headings `## Architecture` (a link to `paths.architecture` and its `## ` headings, or `none` when the file is absent), `## Open findings` (count per severity in `SEVERITIES` order, then one line per open finding), `## In-force decisions` (the count and a link to `in-force.md`); its schema's `headings` lists exactly these three. Specs and plans by state and live programs come in `overview/2` with a migration (programs block or block 5).
  - The four schema files, matching the above.
  - `.gitignore` gains the four generated paths (spec §5). They are plain lines here; the managed `.gitignore` block arrives with `init` in block 4.

**Input-domain dimensions:** registers (empty, missing directories, one record of each status, superseded chains, grants, one-off answers); text in cells (`|`, newline, backtick, unicode, leading `#`); `topics` and `landed_in` (empty list, several); render ordering (ids sorted by string); `--root` forms; directory missing (created), write failures (path is a directory, read-only); idempotence across runs and across both interpreters; the three sections with no data (no architecture file, no findings, no decisions); absent generated files under `gate_schema` (skipped, OQ-17).

- [ ] **Step 1: Write the failing tests** (`tests/test_index.py`; `files = render(root, cfg)`):
  ```python
  def test_index_lists_every_record():
      assert set(parse(files[DEC_INDEX])["decisions"]) == ALL_DEC_IDS and set(parse(files[F_INDEX])["findings"]) == ALL_F_IDS
  def test_superseded_status_in_decision_index():
      assert parse(files[DEC_INDEX])["decisions"][A]["status"] == "superseded"
  def test_finding_owner_rendered_as_one_string():
      assert [parse(files[F_INDEX])["findings"][f]["owner"] for f in (F_PLAN, F_ISSUE, F_ROADMAP)] == ["plan:p/1a.2", "issue:3", "roadmap:p"]
  def test_in_force_md_excludes_superseded_grants_one_off():
      assert rows(files[IN_FORCE]) == [[LASTING, "ids", "rule text", "CLAUDE.md"]]
  def test_cell_pipe_escaped():               # rule "a|b"
      assert "a\\|b" in files[IN_FORCE]
  def test_regenerate_is_idempotent():
      assert read_all(regenerate(root, cfg)) == read_all(regenerate(root, cfg))
  def test_rendered_files_validate_against_their_schemas():
      assert all(errors_for(kind, text) == [] for kind, text in kinds_and_texts(files))
  def test_generated_paths_ignored_in_this_repo():  # each of the four paths under this repository's config
      assert subprocess.run(["git", "check-ignore", "-q", "--", p], cwd=REPO).returncode == 0
  def test_overview_sections():               # OQ-13
      assert headings(files[INDEX_MD]) == ["## Architecture", "## Open findings", "## In-force decisions"]
      assert files[INDEX_MD].splitlines()[0] == "<!-- schema: overview/1 -->"
  def test_in_force_rule_column():            # OQ-12, I2
      assert rows(files[IN_FORCE])[0][2] == "rule text" and rows(no_rule_files[IN_FORCE])[0][2] == ""
  def test_in_force_first_lines():            # I8
      assert files[IN_FORCE].splitlines()[:2] == ["<!-- schema: in-force/1 -->", "# In-force decisions (generated; do not edit)"]
  def test_gate_schema_skips_absent_generated():  # OQ-17: delete the four files
      assert gate_schema.check(["--root", root]).ok()
  ```
- [ ] **Step 2: Run the test command; expect FAIL.**
- [ ] **Step 3: Implement `index.py`, the four schemas, the `.gitignore` lines.**
- [ ] **Step 4: Run the test command on both interpreters; run `python3 -m gates index`, then `check schema`, `check decisions`, `check register`; expect all `PASS` and `git status --porcelain --untracked-files=all` empty (the generated files are ignored).**
- [ ] **Step 5: Commit** `feat(tools): decision and finding indexes, in-force.md, overview; generated files ignored`, then checkpoint. **Block 1c end:** final review, verifier, then the pull-request flow of Process for this plan, "Blocks"; checkpoint; continuation.

---

## Block 1d: record tools (branch `block/b1d`)

### Task 1d.1: `decisions ask | decide | withdraw | find`

**Files:**
- Create: `gates/tools/decisions_cli.py`; Modify: `gates/__main__.py` (register `decisions`), `gates/producers.py` (add `gates.tools.decisions_cli`)
- Test: `tests/test_decisions_cli.py`

**Owner answers applied:** OQ-7, OQ-8, OQ-11, OQ-12.

**Interfaces:**
- Consumes: `Store`, `ids.mint/utc_today`, `decisions.*`, `gitinfo.head_sha/user_email`, `index.regenerate`, `config.load`.
- Produces: `PRODUCES = ("decision",)`; `main(argv: list) -> int` for `python3 -m gates decisions <sub>`:
  - `ask --class C --question Q --option "LABEL::COST" (at least twice) [--topic T]... [--applies-to GLOB]... --effect lasting|one-off [--supersedes ID] --by WHO [--plan P [--program X --stream S]] [--root R]` (OQ-8: `--plan` required for class `merge-grant` and refused for any other class; `--program` and `--stream` together, grants only). Finds candidates (spec §7.4; controller ruling R-rev3-2) as the union, in id order without repeats, of: `find(records, [], None, t, True)` for each `--topic` t; every record with an `applies_to` glob equal to an `--applies-to` glob or matching it either way under `fnmatch.fnmatchcase`, each replaced by `current(records, id)` as `find` does; and `find(records, [w], None, None, True)` for each word w of the question (split on non-alphanumerics, case-folded, 4 or more characters); prints `candidate <id>: <question>` lines; mints the id with `mint(cfg["ids"]["decision"], <every id in both registers>, utc_today(), random.SystemRandom())`; writes the record with `status: open`, `checked_against` = the candidate ids, `asked_at` = HEAD sha, `asked_by` = WHO; refuses `--supersedes X` when an open or answered record already supersedes X (owner Q-decisions-1 (b)); validates before writing (exit 1 and nothing written on any error); regenerates the indexes; prints the new id last.
  - `decide ID --answer TEXT [--rule TEXT] [--landed-in CITE]...` (`--rule` writes the optional `rule` field, OQ-12): the human runs it (spec §7.1; the agent refusal is block 3's hook). Refused (exit 1, nothing written) when the record is not `open`, when validation or `landed_errors` fails, or when `user_email` is `None` (OQ-11: message `set git config user.email; the answer records it`). Otherwise sets `status: answered`, `answer`, `answered_at: {at: <HEAD sha>, by: <user.email>}`, `landed_in`, writes with `Store.replace`, and regenerates the indexes in the same run (spec §7.3).
  - `withdraw ID --reason R`: the human runs it; open records only; writes `status: withdrawn` and `withdrawn: {at: <HEAD sha>, by: <user.email>, reason: R}` (OQ-7), refused like `decide` when `user.email` is unset (owner-approved call, I3; spec §7.1); regenerates.
  - `find TERM... [--path P] [--topic T] [--all]`: prints `<id> [<topics>] <question> -> <answer>` lines; exit 0 even with no hits.

**Input-domain dimensions:** each flag missing, repeated, empty; `--option` without `::`, with several `::`, empty label or cost, one option only; `--class` outside the config list; `--supersedes` unknown, open, withdrawn, a target already superseded by an open or answered record (refused) or only by a withdrawn one (accepted); question text with newline, unicode, `: `, leading `-`; `decide` and `withdraw` on a missing id, an answered or withdrawn record, a malformed id; `user.email` unset or empty; grant flags (`--plan` on a non-grant, a grant without `--plan`, `--program` without `--stream`); `--rule` empty or multi-line; `--landed-in` forms as Task 1b.2; register directory missing (created by `Store.create`), write failures after validation (read-only); mint collision forced by a seeded generator in the test.

- [ ] **Step 1: Write the failing tests** (`tests/test_decisions_cli.py`; `code, out, err = cli(root, "ask", ...)` calls `decisions_cli.main`; `rec(id)` loads the record):
  ```python
  def test_ask_writes_open_record_with_candidates():  # an answered record shares topic "ids"
      assert "candidate " + OLD + ": " in out and rec(new)["status"] == "open" and rec(new)["checked_against"] == [OLD]
      assert rec(new)["asked_by"] == "controller" and out.splitlines()[-1] == new
  def test_ask_one_option_writes_nothing():
      assert code == 1 and listdir(decisions_dir) == before
  def test_ask_id_format_and_date():
      assert id_problem(new, "DEC") == "" and new.split("-")[1] == utc_today().strftime("%Y%m%d")
  def test_decide_records_git_email():
      assert rec(ID)["answered_at"]["by"] == "fixture@example.invalid" and rec(ID)["status"] == "answered"
  def test_decide_without_email_refused():    # OQ-11; user.email unset
      assert code == 1 and "set git config user.email; the answer records it" in err and rec(ID) == before
  def test_ask_grant_fields():                # OQ-8
      assert grant_without_plan_code == 1 and triage_with_plan_code == 1
      assert rec(grant)["plan"] == "2026-10-31-strict-delivery-framework"
  def test_decide_writes_rule():              # OQ-12
      assert rec(ID)["rule"] == "one-line rule"
  def test_decide_lasting_without_landed_in_refused():
      assert code == 1 and rec(ID)["status"] == "open"
  def test_decide_landed_in_spec_refused():
      assert code == 1 and "is a spec" in err
  def test_decide_answered_record_refused():
      assert code == 1 and rec(ID) == before
  def test_withdraw_shape():                  # OQ-7
      assert rec(ID)["withdrawn"]["by"] == "fixture@example.invalid" and rec(ID)["withdrawn"]["reason"] == "dup"
  def test_withdraw_without_email_refused():  # I3
      assert code == 1 and rec(ID)["status"] == "open"
  def test_find_in_force_default_and_all():   # a superseded and a withdrawn record match the term
      assert ids(find_out) == [CURRENT] and {CURRENT, WITHDRAWN_ID} <= set(ids(find_all_out))
  def test_gates_pass_after_ask_and_decide():
      assert gate_decisions.check(["--root", root]).ok() and gate_schema.check(["--root", root]).ok()
  ```
- [ ] **Step 2: Run the test command; expect FAIL.**
- [ ] **Step 3: Implement `decisions_cli.py`.**
- [ ] **Step 4: Run the test command on both interpreters and every enabled gate; expect PASS.**
- [ ] **Step 5: Commit** `feat(tools): decisions ask, decide, withdraw, find`, then checkpoint.

### Task 1d.2: `findings new | move`

**Files:**
- Create: `gates/tools/findings_cli.py`; Modify: `gates/__main__.py` (register `findings`), `gates/producers.py` (add `gates.tools.findings_cli`)
- Test: `tests/test_findings_cli.py`

**Owner answers applied:** OQ-6, OQ-15.

**Interfaces:**
- Consumes: `Store`, `ids.mint/utc_today`, `findings.*`, `gitinfo.head_sha`, `index.regenerate`, `config.load`.
- Produces: `PRODUCES = ("finding",)`; `main(argv: list) -> int`:
  - `new --source S --severity SEV --class TEXT --owner-kind plan|issue|roadmap (--plan P --task T | --number N | --plan P) [--parent ID] [--cite FILE:LINES@SHA]... --by WHO [--root R]` (kind `plan` requires both `--plan` and `--task`, kind `issue` requires `--number`, kind `roadmap` requires `--plan` alone, as the `owner` key rules of Task 1b.3): mints an `F` id as Task 1d.1 does; writes `status: open`, `history: [{status: open, sha: <HEAD>, by: WHO}]`, `pin: null`, `ruling: null`, `repro: null`, empty `siblings` and `evidence`; validates first; regenerates; prints the id.
  - `move ID --to STATUS --by WHO [--evidence E]... [--ruling DEC] [--pin-test T --pin-transcript CITE] [--resolved-by PLAN]`: refuses an illegal transition, an invalid result, any change to a resolved record, and `--to merged` (OQ-6: only the cleanup step sets `merged`); appends `{status, sha: <HEAD>, by: WHO}` to `history`; sets `resolved_by` when STATUS is in `RESOLVED` (required then); writes with `Store.replace`; regenerates.

**Input-domain dimensions:** each flag missing, repeated, empty; `--owner-kind` against `--plan`/`--task`/`--number` combinations; `--number` 0, negative, non-numeric; `--cite` forms (no `@`, no `:`, bad sha); every `(from, to)` pair through `move`; `--resolved-by` missing on `closed`, present on `planned`; evidence forms (commit sha, `<sha>:<path>`, plain tracked path outside per-effort paths, plain per-effort path: refused; OQ-15); `--ruling` open or unknown; `move` on a missing id or a resolved record; `--to merged` from `closed` and from `pinned`.

- [ ] **Step 1: Write the failing tests** (`tests/test_findings_cli.py`; `code, out, err = cli(root, "new", ...)` calls `findings_cli.main`):
  ```python
  def test_new_writes_open_record():
      assert rec(f)["status"] == "open" and rec(f)["history"] == [{"status": "open", "sha": head, "by": "controller"}]
      assert rec(f)["pin"] is None and rec(f)["siblings"] == [] and rec(f)["evidence"] == []
  def test_new_plan_owner_needs_task():       # F7: --owner-kind plan --plan p, no --task
      assert code == 1 and listdir(findings_dir) == before
  def test_move_through_lifecycle_to_closed():  # open, planned, in-progress, pinned, closed --resolved-by p
      assert [h["status"] for h in rec(f)["history"]] == ["open", "planned", "in-progress", "pinned", "closed"]
      assert rec(f)["resolved_by"] == "p"
  def test_move_illegal_transition_refused():  # open -> pinned
      assert code == 1 and rec(f) == before
  def test_move_closed_needs_resolved_by():
      assert code == 1 and rec(f) == before
  def test_move_deferred_needs_answered_ruling():  # --ruling names an open decision
      assert code == 1 and rec(f) == before
  def test_move_resolved_record_refused():
      assert code == 1 and rec(f) == before
  def test_move_to_merged_refused():          # OQ-6, from closed and from pinned
      assert code == 1 and "cleanup step" in err
  def test_move_plain_review_path_evidence_refused():  # OQ-15
      assert code == 1 and rec(f) == before
  def test_move_plain_findings_path_evidence_refused():  # Q-plan-5
      assert code == 1 and rec(f) == before
  def test_move_plain_pin_transcript_refused():  # Q-plan-4
      assert code == 1 and rec(f) == before
  def test_gates_pass_after_cli_lifecycle():
      assert gate_register.check(["--root", root]).ok() and gate_schema.check(["--root", root]).ok()
  ```
- [ ] **Step 2: Run the test command; expect FAIL.**
- [ ] **Step 3: Implement `findings_cli.py`.**
- [ ] **Step 4: Run the test command on both interpreters and every enabled gate; run `python3 -m gates index`; expect PASS and a clean tree.**
- [ ] **Step 5: Commit** `feat(tools): findings new and move`, then checkpoint. **Block 1d end:** final review, verifier; the pull request, the owner's chat approval and `gh pr merge --merge --match-head-commit` (Process for this plan, "Blocks"; owner Q-15 (a)); checkpoint; continuation.

---

## Block 2 (sub-blocks 2a, 2b, 2c)

Spec §17 block 2: "`gate_claims`, `gate_dispatch`, `run_all`, git hook shims and installer, self-adoption, and the decision schema `decision/2` (the optional `overrides`, section 7.1) with its migration." Under the strict cap of 3 tasks per block it is split into three sub-blocks:
- **2a** (Tasks 2a.1-2a.3): `decision/2` and claims.
- **2b** (Tasks 2b.1-2b.3): `run_all`, the git hooks, and self-adoption.
- **2c** (Tasks 2c.1-2c.3): the claims tool (2c.1), `config/2` with `limits`, `merge` and `escape_cost` (2c.2), and `gate_dispatch` (2c.3).

Each sub-block has its own branch (`block/b2a`, `block/b2b`, `block/b2c`) and starts from the tip of `main`. Each ends as block 1d does: final review, verifier, the pull request, the owner's chat approval and `gh pr merge --merge --match-head-commit` (Process for this plan, "Blocks"; owner Q-15 (a)), checkpoint, continuation.

Only Task 2c.3 waits for block B1 to merge into `main` and for A to update from `main` (stream rules, "Cross-stream order": "The block-2 task that lands `gate_dispatch`"). Tasks 2c.1 and 2c.2 depend only on 2a and 2b (2c.1's hook test needs 2b.2's hook), and run first.

The commit gate is the block-1 gate list until Task 2b.3. From Task 2b.3's commit on, it is `python3 -m gates run_all` plus the test command on both interpreters, with a clean tree (Process for this plan: "`run_all` replaces this list in block 2").

The owner answered this block's questions on 2026-11-01 (section "Owner answers", "Block 2 (2026-11-01)"); the task text states each answer.

Owner answers on the controller tree, recorded since the first draft, are binding here:
- **Q-H1:** `program_controller` is kept.
- **Q-H2:** per-role child caps `limits.max_children.<role>` live in config, with no cap by default. A playbook or lasting decision may tighten them, and `gate_dispatch` enforces them.
- **Q-H3:** a sub-controller (`controller`) may dispatch a sub-controller when the stream agent judges that better.
- **Q-H4:** `gate_dispatch` refuses any dispatch from a worker role.

- **Q-H5 (a), answered:** the tree is depth-aware.
  - By default the session acts as program controller: stream at level 1, sub-controller at level 2, workers at level 3.
  - A separate `program_controller`, and nested sub-controllers, are used only when the configured depth allows them.

**Environment facts (coordinator measurements, 2026-11-01).** The main session is level 0.
- **Depth.**
  - With `CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH` unset, subagents at levels 1-2 have the Agent tool. So subagents exist down to level 3, and level 3 is a leaf.
  - With the variable set to 5, levels 1-5 have the Agent tool and level 6 has none, so subagents exist down to level 6.
  - The mapping used here: the deepest subagent level is `N + 1` when the variable is set to `N`, and 3 when it is unset. This comes from these two measurements, not from documentation. Q-B2plan-22 pins it, and a change in Claude Code is caught by re-measuring.
- **Concurrency.**
  - With `CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS` unset, Claude Code refuses (does not queue) a launch beyond 20 concurrent subagents.
  - With the variable set to 30, 25 ran at once.
  - The concurrent limit is 20 when unset (measured: launches past 20 are refused); when set it is taken as the variable's value (inferred: 25 ran at once under 30, so the limit is at least 25; not measured at the boundary).
- **Both limits can be raised per process.** The first draft's "values above 3 are undocumented" is superseded.

**Cross-block notes.**
- **Block 4 (owner answer, binding there, not here):** `init` offers the depth and concurrency limits as config, written into the project's `.claude/settings.json` `env` block as `CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH` and `CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS`. Task 2c.3's gate reads the same variables (Q-B2plan-22).
- **Not in block 2:** `dispatch.max_prompt_chars` (spec §6). It has no default and gets no reader here; it lands with the profiles in block 4.
- **Block 3's PreToolUse Agent hook supplies `dispatcher`, `program_live` and the live counts** to `gate_dispatch` (Task 2c.3). It must not invent a count it cannot determine: an absent count fails `dispatch.input`.

**Controller rulings (spec or plan settles each; ledgered in this form when the block starts):**
- Controller ruling: `gate_claims` never runs a claim's `direct` or `contradiction` command; it checks that both are recorded, that the cites resolve and that the claim is fresh. Claims carry no expected-outcome fields; that shape follows from the execution ruling, since expected outcomes serve only a gate that runs the commands (the first draft's Q-1 (b) cost) -- the outline names the checks ("direct and contradiction commands, staleness from the cited paths"), spec §8 gives execution to reviewers, and running shell from data files on every commit is outside the outline -- cost if wrong: a later version adds expected outcomes and execution with a `claim/2` migration -- plan "Later blocks" Block 2; spec §8 "Reviewers execute every claim and re-run every gate themselves" (was Q-B2plan-1 and Q-B2plan-3).
- Controller ruling: `run_all.PROFILE_GATES` is light `(schema, register, decisions)`; standard and strict `(schema, register, decisions, claims)` -- spec §12 states both rows -- cost if wrong: one table edit -- spec §12 "claims register | no | yes | yes" and the light pre-commit cell "schema, register, decisions" (was the list part of Q-B2plan-9; the `cites` part is D4, the `dispatch` part is in Q-B2plan-19).
- Controller ruling: `githooks install` refuses when `core.hooksPath` is set, and refuses to replace any hook file without the framework header, listing every conflict and writing nothing -- spec §4 lists `core.hooksPath` among the bypasses, doctor checks hooks "not foreign or bypassed", and the no-overwrite rule refuses foreign files -- cost if wrong: projects with their own hooks merge by hand -- spec §4 (PreToolUse Bash bypass list; doctor; "Init and upgrade never overwrite") (was Q-B2plan-14).
- Controller ruling: this repository's shared hooks directory gets the hooks only after block 2b merges into `main` and every live stream branch has updated from `main`; until then Task 2b.3 exercises the hook in a disposable clone -- the shared hooks directory would run `githook` on stream branches where it does not exist yet -- cost if wrong: the hook goes live one merge later than it could -- plan, stream rules "Cross-stream order" ("no gate runs against files that are not there yet") (was Q-B2plan-15).

---

## Block 2a: `decision/2` and claims (branch `block/b2a`)

### Task 2a.1: `decision/2`, `FIXED_RULES`, the migration registry, migrate-before-compare

**Files:**
- Create: `gates/lib/migrations.py`, `tests/test_playbook_drift.py` (stream A's file; see "Drift tests" below)
- Modify:
  - `gates/schemas/decision.yml`: version 2, `overrides`.
  - `gates/lib/decisions.py`: `FIXED_RULES`; `KNOWN_RULES` under Q-B2plan-8 (a); the current tag; the `overrides` rules.
  - `gates/lib/store.py`: `base_errors` migrates rows before comparing.
  - `gates/tools/decisions_cli.py`: `ask --overrides`, Q-B2plan-7.
- Records: every record under this repository's `paths.decisions` has its tag migrated in the same commit. The session controller writes them (F-B2p-10; Step 5).
- Test: `tests/test_migrations.py`, `tests/test_decisions_lib.py`, `tests/test_store.py`, `tests/test_decisions_cli.py`, `tests/test_playbook_drift.py`. `tests/test_playbook.py` gains the `FIXED_RULES` test only when the stream rules' "Cross-stream order" gives it to A.

**Owner answers applied:** DB-6, DB-9, F-1, F-2, F-r3-3 (cross-stream order), DS-3, OQ-16; Q-B2plan-7, Q-B2plan-8.

**Drift tests (F-B2p-5; the stream-A-file route).**
- **Where.** `tests/test_playbook_drift.py` is a new file owned by A. It reads `playbook/rules.md` and, from Task 2c.3, `playbook/roles.md`, and never edits them. Reading another stream's file is allowed; only editing is refused (design §6).
- **Each test** asserts strict equality: `KNOWN_RULES` equals every rule id in `rules.md`, and `MIN_TIERS` equals the `minimum tier` column of `roles.md`. There is no `expectedFailure` marker (F-B2p2-1): measured, it hides a mismatch and fails on a match.
- **When it runs.**
  - The test runs only when its B file exists on the branch being tested.
  - When the file is absent, the test is skipped with the named reason `playbook/<stem>.md absent on this branch: block B2 not merged`. That is the only skip.
  - When the file is present and the sets differ, the test fails, naming both sets.
  - A file that is present but unreadable, or has no table, fails. It never skips.
- **On stream B's branch**, after B updates from `main` past the task that adds the test (DS-2), the file is present and the test compares for real.
  - B's tables follow the same owner answers as A's constants (DB-6, DB-2), which B's own tests assert. So the test passes there unless there is real drift.
  - On real drift, the side that differs from the owner answer is fixed. If B's table is wrong, B fixes its own file. If A's constant is wrong, B raises a cross-stream request to A, which fixes its constant; while A's fix is pending, B stops BLOCKED (stream rules, "Requests"). A never edits B's file, and B never edits this test.
- **Stream C** runs the test once B2 is on `main` and C has updated. The same rule applies, with C raising the request.
- **Who updates it.** A owns and updates the test, before and after B2 merges. When B2 merges, `playbook/` passes to A (DS-3), and the test is unchanged.
- **Ledger.** While B2 is unmerged, A's checkpoint lines carry `open: drift test <name> skipped (B2 not merged)`, so the skip is never silent.
- **Meanwhile** each constant is also asserted against its literal owner value (DB-6, DB-2, spec §10; F-B2p-4). B's own tests assert the same literals against B's tables (Task B2.1 rows, Task B2.2 `TIERS`). The gap before B2 merges is therefore covered through the shared owner answers.
- **Not moved.** The `FIXED_RULES` test keeps its existing "Cross-stream order" entry and file (`tests/test_playbook.py`), as the plan already states.

**Interfaces:**
- Consumes: `schema.load_schema/validate/SCHEMAS_DIR`, `decisions.validate/CLASS_GRANT`, `store.Store/base_errors/store_errors`, `gitinfo.merge_base/show/ls_tree`, `ids.id_problem`, `decisions_cli.main` (Task 1d.1), `helpers.make_repo/commit_all/write_record/GitIsolatedTestCase`.
- Produces:
  - `gates/schemas/decision.yml`:
    - `version: 2`.
    - Every `decision/1` field is unchanged.
    - New field `overrides` (`str`, `required: false`). Spec §7.1: "A decision of class `rule-override` may carry the optional `overrides: SD-R<n>` ... matching `SD-R[1-9][0-9]*`; no other class carries it".
    - The class rule lives in `decisions.validate`, because `required_when`/`absent_when` match listed values only and the class list is open (config union, Task 1a.2).
  - `migrations.py`:
    - `MIGRATIONS: dict` maps `(kind: str, from_version: int)` to a pure function `row -> new row` that never mutates its argument. Entry `("decision", 1)` sets `schema: decision/2` and changes nothing else. Task 2c.2 adds `("config", 1)`.
    - `current_version(kind: str) -> int` returns the `version` of `gates/schemas/<kind>.yml`; a `SchemaError` passes through.
    - `migrate(kind: str, row: object) -> object` applies the registered steps in order when `row` is a `dict` whose `schema` is exactly `<kind>/<n>`, `n` is below `current_version(kind)`, and every step from `n` up is registered.
    - In every other case `migrate` returns `row` unchanged: non-dict, missing or malformed tag, another kind, `n` at or above current, or a missing step. An unmigratable base row is then compared as it stands, and any change still fails `immutable.<id>` (fail-closed).
  - `decisions.py`:
    - `FIXED_RULES: tuple = ("SD-R3", "SD-R12", "SD-R18")` (owner F-2).
    - Under Q-B2plan-8 (a), `KNOWN_RULES: tuple` = `("SD-R1", ..., "SD-R19")`, nineteen ids (DB-6).
    - `validate` checks the tag against `decision/<current_version("decision")>` instead of the literal `decision/1`.
    - When `overrides` is present, `validate` adds:
      - `overrides: <v> does not match SD-R[1-9][0-9]*` (`re.fullmatch`);
      - `overrides: only class rule-override carries it`;
      - `overrides: <v> is a fixed rule and cannot be overridden`;
      - under Q-B2plan-8 (a), `overrides: <v> is not a base playbook rule`.
  - `store.base_errors`:
    - The signature is unchanged.
    - Each row at the merge base and each row at the tip of `base` is passed through `migrations.migrate(store.kind, row)` before comparing.
    - `deleted.<id>` still calls `may_delete` with the unmigrated base row.
    - A record equal to its migrated base row passes. Any other change to a resolved record fails `immutable.<id>` (spec §7.2, F-1).
  - `decisions_cli`:
    - `ask` gains `[--overrides SD-R<n>]` (Q-B2plan-7 (a)), written into the open record and validated before writing.
    - `decide` takes no `--overrides`.
  - `tests/test_playbook.py::test_fixed_rules_match_decisions_constant`, only when A writes it per "Cross-stream order".

**Input-domain dimensions:**
- `overrides` value: each of `SD-R1`, `SD-R19`, `SD-R0`, `SD-R01`, `SD-R`, `sd-r3`, `SD-R3 `, ` SD-R3`, `SD-R3\n`, `SD-R3a`, `SD-R20` (Q-B2plan-8); each `FIXED_RULES` member; `int`, `None`, `""`, a `str` subclass, a list.
- `class` against `overrides`: `rule-override` with and without it; every other default class, and a config-added class, with it.
- `status` against `overrides`: open, answered, withdrawn.
- Schema tag: `decision/1`, `decision/2`, `decision/3`, `decision/2 ` (trailing space), missing, non-str.
- `migrate` input: non-dict; a tag of another kind; `n` of 0, current, above current; a gap in `MIGRATIONS`; `decision/1` with every other field invalid.
- Base comparison:
  - a resolved base row migrated exactly;
  - migrated plus one other field changed;
  - migrated plus `overrides` added;
  - an open record changed;
  - a base row with a malformed tag, changed;
  - a `decision/1` tip row with the same content as a `decision/2` branch row.
- `ask --overrides`: missing, repeated, empty, with `--class rule-override`, with any other class, naming a fixed rule.
- Record migration of this repository: no records; open, answered and withdrawn records.

- [ ] **Step 1: Write the failing tests:**
  ```python
  # test_migrations.py
  def test_decision_1_migrates_to_2():
      assert migrate("decision", {**ROW_V1}) == {**ROW_V1, "schema": "decision/2"} and ROW_V1["schema"] == "decision/1"
  def test_unmigratable_rows_unchanged():      # subTests: [], {"schema": "finding/1"}, {"schema": "decision/0"}, {"schema": "decision/2"}, {"schema": "decision/9"}, {}
      assert migrate("decision", row) == row
  def test_current_version_reads_schema_file():
      assert current_version("decision") == 2
  def test_registered_steps():                 # spec §15: "every migration is tested from an old fixture"
      assert set(MIGRATIONS) == {("decision", 1)}
  # test_decisions_lib.py
  def test_fixed_rules_literal():              # F-2, literal owner value (F-B2p-4)
      assert FIXED_RULES == ("SD-R3", "SD-R12", "SD-R18")
  def test_known_rules_literal():              # DB-6, Q-B2plan-8 (a)
      assert KNOWN_RULES == tuple("SD-R%d" % n for n in range(1, 20))
  def test_overrides_form():                   # subTests per value above
      assert any(e.startswith("overrides:") for e in validate({**OVERRIDE, "overrides": v}, cfg))
  def test_overrides_only_on_rule_override():
      assert "overrides: only class rule-override carries it" in validate({**OPEN, "overrides": "SD-R2"}, cfg)
  def test_overrides_fixed_rule_refused():     # literal list, not the constant
      for r in ("SD-R3", "SD-R12", "SD-R18"):
          assert "overrides: %s is a fixed rule and cannot be overridden" % r in validate({**OVERRIDE, "overrides": r}, cfg)
  def test_overrides_unknown_rule_refused():   # Q-B2plan-8 (a)
      assert "overrides: SD-R20 is not a base playbook rule" in validate({**OVERRIDE, "overrides": "SD-R20"}, cfg)
  def test_decision_1_tag_names_upgrade():
      assert "schema: expected decision/2, got decision/1; run /strict-delivery:upgrade" in validate({**OPEN, "schema": "decision/1"}, cfg)
  # test_store.py
  def test_migrated_answered_record_is_not_immutable():   # F-1
      assert not any(s.startswith("immutable.") for s, _ in base_errors(root, store, "HEAD", is_resolved, never))
  def test_migrated_and_edited_record_is_immutable():
      assert "immutable." + ID in [s for s, _ in base_errors(root, store, "HEAD", is_resolved, never)]
  def test_migrated_tip_row_is_no_collision():
      assert not any(s.startswith("collision.") for s, _ in errs)
  # test_decisions_cli.py
  def test_ask_writes_overrides():
      assert rec(new)["overrides"] == "SD-R2" and rec(new)["class"] == "rule-override"
  def test_ask_fixed_override_writes_nothing():
      assert code == 1 and "fixed rule" in err and listdir(decisions_dir) == before
  # test_playbook_drift.py
  def test_known_rules_match_rules_md():       # skipTest only when playbook/rules.md is absent (Drift tests); strict on presence
      assert set(KNOWN_RULES) == rule_ids(read("playbook/rules.md"))
  def test_drift_helper_fails_on_mismatch():   # fixture rules.md in a temp dir missing SD-R19: compare() raises AssertionError naming both sets
      with self.assertRaises(AssertionError): compare(KNOWN_RULES, fixture_path)
  def test_drift_helper_skips_only_when_absent():   # absent path -> SkipTest with the named reason; empty file -> AssertionError
      with self.assertRaises(unittest.SkipTest): compare(KNOWN_RULES, missing_path)
  ```
- [ ] **Step 2: Run the test command; expect FAIL** (`ModuleNotFoundError: gates.lib.migrations`).
- [ ] **Step 3: Implement** `migrations.py`, the schema version, the `decisions.py` and `store.py` changes, and `ask --overrides`.
- [ ] **Step 4: Write `test_fixed_rules_match_decisions_constant`** only if `playbook/rules.md` and `tests/test_playbook.py` are on `main` and are A's (B2 merged, DS-3). Otherwise ledger that stream B writes it ("Cross-stream order").
- [ ] **Step 5: Migrate the records (session controller).** The implementer stops before the commit with status DONE and the code uncommitted. The session controller, the only writer of decision records (stream rules, "Shared files"), migrates every record under `paths.decisions` with `migrations.migrate` and `Store.replace`, never by hand. It then runs the test command on both interpreters and every enabled gate (`check schema`, `check decisions`, `check register`), expects PASS, and makes the commit.
- [ ] **Step 6: Commit** `feat(lib): decision/2 with overrides, FIXED_RULES, schema migration registry` (code and migrated records together, so `check schema` and `check decisions` stay green), then checkpoint.

### Task 2a.2: claim schema and claim rules

**Files:**
- Create: `gates/schemas/claim.yml`, `gates/lib/claims.py`
- Modify: `gates/lib/gitinfo.py`, an additive change that leaves every existing signature as it is: `blob_id` (Q-B2plan-4 (a)).
- Test: `tests/test_claims_lib.py`

**Owner answers applied:** OQ-4, OQ-16; controller ruling on claim execution and shape; Q-B2plan-2, Q-B2plan-4, Q-B2plan-5.

**The freshness reference (F-B2p-1; owner answer Q-B2plan-4 (a), a blob id per cite).** The draft's first design is not adopted: it compared a commit sha with the working tree, so a commit could not change a cited file while its claim exists. Each cite records the blob id of the cited file, and freshness compares it with the file being committed.

**Interfaces:**
- Consumes: `schema.load_schema/validate/SCHEMAS_DIR`, `ids.id_problem`, `gitinfo.tracked_files/commit_exists/show/ls_tree/merge_base`, `migrations.migrate`, `yamlsub.load/parse`, `result.GateError`, `config.load`.
- Produces:
  - `gates/schemas/claim.yml` (`claim/1`, `files: [{dir: claims, glob: "*.yml"}]`):
    - top-level `schema` and `document` (`str`, the repo-relative path of the document the claims are about, per Q-B2plan-2);
    - `claims` (`list`, `min: 1`), items `map`: `id` (`id`, `id_kind: claim`), `text` (`str`), `cites` (`list`, `min: 1`), `direct` (`str`, a command), `contradiction` (`str`, a command), `by` (`str`).
    - Spec §8: "No claim is trusted: verify directly and by contradiction, record both commands." Spec §7.2: "`gate_claims` [reads record fields] from the claim schema (appendix A), never from hand-coded field lists."
    - Each cite is a `map {path: str, lines: str (optional, <n> or <first>-<last>), blob: sha (40 hex)}`, and there is no claim-level sha (Q-B2plan-4 (a)).
  - `gitinfo.blob_id(root: str, path: str) -> str`: `git hash-object -- <path>`, run with `-C root`. It applies the same clean filters as `git add`, so the id equals the blob the path would be committed as.
  - `@dataclass(frozen=True) ClaimFile(file: str, row: dict)`.
  - `load(root: str, cfg: dict) -> list` reads every `*.yml` directly under `cfg["paths"]["claims"]`. A missing directory is empty. A file that does not load, is not a regular file, or is not a top-level mapping raises `GateError` naming it.
  - `slug(document: str) -> str`, per Q-B2plan-2 (a): the path without its last `.md` suffix, each `/` replaced by `--`.
  - `validate(row: object, cfg: dict) -> list` returns schema errors plus a document-path problem and per-cite form problems (lines positive, `first <= last`).
  - `file_errors(files: list, prefix: str) -> list` of `(suffix, reason)`:
    - `name.<file>`: the file stem differs from `slug(document)`;
    - `id.<file>`: an id fails `id_problem`;
    - `duplicate.<id>`: an id appears more than once; the reason lists every file.
  - `document_errors(cf: ClaimFile, tracked: frozenset) -> list` checks that `document` and each cited path are tracked.
  - `stale_errors(cf: ClaimFile, root: str, base: Optional[str]) -> list` of `(id, reason)` (Q-B2plan-4 (a)):
    - A claim is fresh when each cite's `blob` equals `gitinfo.blob_id(root, path)`. The working tree is the tree being committed under the pre-commit hook's unstaged refusal (F-3), so a commit can change a cited file and record the new blob in the same commit.
    - A claim fails when the cited path is absent or untracked. A line cite compares the whole file.
  - `base_errors(root: str, cfg: dict, files: list, base: str) -> list` of `(suffix, reason)` (no-delete extended to claim files, spec §7.2; Q-B2plan-5 (a)):
    - against `mb = gitinfo.merge_base(root, base, "HEAD")`:
      - `deleted.<file>`: a claim file at `mb` is gone, unless its `document` at `mb` is also gone;
      - `removed.<id>`: a claim id at `mb` is no longer in any file whose file is still present;
    - against the tip of `base`:
      - `collision.<id>`: an id added since `mb` exists at the tip with different content.
    - There is no immutability check. Rows are passed through `migrations.migrate("claim", row)` first.

**Input-domain dimensions:**
- Every field against wrong types.
- `claims` empty, missing, not a list.
- Unknown key at the top level and in a claim or cite.
- `document` forms: absolute, `..`, `./`, trailing `/`, untracked, a directory, not `.md`.
- `slug`: nested path, no `.md`, `.md` inside a directory name, unicode, a file name that is another document's slug.
- Cite forms:
  - (a) `blob` short, uppercase, the blob of another file; `lines` `0`, `5-3`, `3-`.
  - (b) and (c) `p`, `p:3`, `p:3-5`, `p:0`, `p:5-3`, `p:`, `p:a`, `p:3-`, a path holding `:`.
- Every option: absolute or `..` paths, untracked, binary, invalid UTF-8, CRLF, no final newline, a path subject to a clean filter or `core.autocrlf` (for (a), `blob_id` matches `git add`).
- Freshness:
  - the cited file unchanged;
  - one byte changed and staged in the same commit as the new reference: (a) passes when the blob is updated, fails when not; (b) passes once, then must be re-verified;
  - deleted; renamed;
  - a claim added together with the file it cites;
  - a change outside the cited lines.
- Base cases:
  - a claim file deleted with its document kept;
  - a claim file deleted with its document deleted;
  - a claim id removed from a kept file;
  - an id moved to another file;
  - an id added on both sides;
  - base without the claims directory;
  - an absent base ref.
- `load` file kinds: subdirectory, symlink, FIFO, `*.yaml`, hidden file.

- [ ] **Step 1: Write the failing tests** (`tests/test_claims_lib.py`; written for the option the owner chose; the (a) form shown):
  ```python
  def test_valid_claim_file():
      assert validate(CLAIM_FILE, cfg) == []
  def test_both_commands_required():           # spec §8; subTest per key
      assert any(e.startswith("claims[0].%s:" % k) for e in validate(without(CLAIM_FILE, k), cfg))
  def test_unknown_key_refused():              # OQ-16
      assert "claims[0].x: unknown key" in validate(with_key(CLAIM_FILE, "x"), cfg)
  def test_slug():
      assert slug("docs/strict-delivery/plans/x.md") == "docs--strict-delivery--plans--x"
  def test_file_name_must_be_slug():
      assert ("name." + rel, ANY) in file_errors([ClaimFile(rel, CLAIM_FILE)], "C")
  def test_duplicate_id_across_files():
      assert suffix == "duplicate." + CID and f1 in reason and f2 in reason
  def test_unchanged_cite_is_fresh():
      assert stale_errors(cf, root, None) == []
  def test_changed_cite_with_updated_blob_is_fresh():   # F-B2p-1: cited file and claim change in one commit
      assert stale_errors(cf_updated, root, None) == []
  def test_changed_cite_without_update_is_stale():
      assert [i for i, _ in stale_errors(cf, root, None)] == [CID]
  def test_claim_added_with_its_file_is_fresh():
      assert stale_errors(cf_new, root, None) == []
  def test_blob_id_matches_git_add():          # (a); file with CRLF under core.autocrlf
      assert gitinfo.blob_id(root, p) == git(root, "rev-parse", ":" + p)   # after git add p
  def test_deleted_claim_file_fails():
      assert ("deleted." + rel, ANY) in base_errors(root, cfg, load(root, cfg), "HEAD")
  def test_claim_file_cleaned_with_document_passes():  # Q-B2plan-5 (a)
      assert base_errors(root, cfg, load(root, cfg), "HEAD") == []
  def test_removed_claim_id_fails():
      assert ("removed." + CID, ANY) in errs
  def test_collision_with_base():
      assert ("collision." + CID, ANY) in errs
  def test_absent_base_ref_is_gate_error():
      with self.assertRaises(GateError): base_errors(root, cfg, files, "no-such-ref")
  ```
- [ ] **Step 2: Run the test command; expect FAIL.**
- [ ] **Step 3: Implement `schemas/claim.yml`, `claims.py`** (and `gitinfo.blob_id`: an argument list, `LC_ALL=C`, `--` before the path, as in Task 1a.2).
- [ ] **Step 4: Run the test command on both interpreters and every enabled gate; expect PASS.** `claim` has no producer yet, so `check schema` does not check claim files (Appendix A).
- [ ] **Step 5: Commit** `feat(lib): claim schema and rules; freshness of cited files`, then checkpoint.

### Task 2a.3: `gate_claims`; enable `check claims`

**Files:**
- Create: `gates/gate_claims.py`
- Modify: `gates/__main__.py` (`GATES["claims"]`)
- Test: `tests/test_gate_claims.py`

**Owner answers applied:** OQ-4, OQ-14; controller ruling on claim execution; Q-B2plan-4, Q-B2plan-5, Q-B2plan-6.

**Interfaces:**
- Consumes: `claims.*`, `gitinfo.tracked_files`, `result.Result/gate_args/run_gate`, `config.load`, `__main__.GATES`.
- Produces:
  - `PRODUCES = ()` (Task 2c.1's claims tool declares `claim`, Q-B2plan-6 (a)).
  - `check(args: list) -> Result` (gate `claims`) and `main(argv=None) -> int`.
  - Arguments: `--root`, and `--base REF` (default `cfg["base_branch"]`; an absent ref fails `claims.input`).
  - Categories, each with one `PASS claims.<cat>` when clean:
    - `schema`: `claims.schema.<file>`;
    - `store`: `claims.store.<suffix>`;
    - `document`: `claims.document.<file>`;
    - `stale`: `claims.stale.<id>`, run per Q-B2plan-4;
    - `base`: `claims.base.<suffix>`.
  - The gate never runs a claim's commands (controller ruling).

**Input-domain dimensions:**
- argv: `--root` missing or not a repo; `--base` an absent ref; `--json` position; an unknown flag; repeated `--root`.
- Repository states: no config; no claims directory; an empty claims directory; a decision file in the claims directory.
- Each category's failing inputs from Task 2a.2.
- Inside a git pre-commit hook with `GIT_INDEX_FILE` set (Q-1a2r-5).
- A stale claim whose document is under `paths.specs`.

- [ ] **Step 1: Write the failing tests** (`out, code = run(root, *args)` calls `gate_claims.main`):
  ```python
  def test_empty_register_passes_every_category():
      for c in ["schema", "store", "document", "stale", "base"]: assert "PASS claims." + c in out
      assert code == 0
  def test_stale_claim_fails():
      assert "FAIL claims.stale." + CID in out and code == 1
  def test_cited_file_and_claim_changed_together_pass():   # F-B2p-1, Q-B2plan-4 (a)
      assert "PASS claims.stale" in out
  def test_deleted_claim_file_fails():
      assert "FAIL claims.base.deleted." in out
  def test_commands_never_run():               # direct: "touch ran"
      assert not os.path.exists(os.path.join(root, "ran"))
  def test_missing_config_is_input_fail():
      assert out.startswith("FAIL claims.input:")
  def test_json_output_shape():
      assert json.loads(out)
  ```
- [ ] **Step 2: Run the test command; expect FAIL.**
- [ ] **Step 3: Implement `gates/gate_claims.py`.** Config is read from `--root`.
- [ ] **Step 4: Run the test command on both interpreters.**
- [ ] **Step 5: Enable on this repository.** Run `check claims`, `check schema`, `check decisions` and `check register`; expect all PASS.
- [ ] **Step 6: Commit** `feat(gates): gate_claims; enable check claims`, then checkpoint with `gates=PASS`. **Block 2a end:** as block 1d.

---

## Block 2b: `run_all`, git hooks, self-adoption (branch `block/b2b`)

### Task 2b.1: `run_all`

**Files:**
- Create: `gates/run_all.py`
- Modify: `gates/__main__.py` (`COMMANDS["run_all"]`)
- Test: `tests/test_run_all.py`

**Owner answers applied:** OQ-1; controller ruling on `PROFILE_GATES`; stream rules "Cross-stream order" (`cites`, D4); Q-B2plan-19 (the `dispatch` part), Q-B2plan-24 (version source).

**Interfaces:**
- Consumes: `result.run_check/Result/GateError/gate_args`, `config.load`, `__main__.GATES`, each gate module's `check(args)`.
- Produces:
  - `run_all.PROFILE_GATES: dict` (controller ruling).
    - `cites` is appended per the stream rules' "Cross-stream order": to every profile when `gates/gate_cites.py` is on `main` when this task starts, else through Task C2.2's request.
    - Whether light also gets `cites` is D4: both quotes are below, and no side is taken. The task follows the plan text until the owner rules.
    - Under Q-B2plan-19 (a), `dispatch` is in no profile's list.
  - `run_all.BASE_GATES: tuple = ("decisions", "register", "claims")`: the gates that take `--base` (F-B2p-9). `schema` and `cites` take `--root` only (Task C2.2: "Argument: `--root`").
  - `check(args: list) -> Result` (gate `run_all`) and `main(argv: list) -> int` for `python3 -m gates run_all [--json] [--root R] [--base REF]`:
    - for each gate of `PROFILE_GATES[cfg["profile"]]`, in order, call `run_check(gate, module.check, ["--root", root] + (["--base", base] if gate in BASE_GATES and base is given else []))`;
    - every sub-gate line is kept verbatim, in order;
    - a gate absent from `GATES`, a failed import, or a missing or non-callable `check` gives `FAIL run_all.missing.<gate>: <reason>` (spec §13: "a missing or raising gate fails");
    - a raising gate becomes its own `<gate>.input` line;
    - `run_all` emits no version line in block 2 (Q-B2plan-24 (a)). Spec §4's agreement check starts in the block that lands the second listed source (block 3's `.claude-plugin/plugin.json`), comparing `framework_version` with it.

**Input-domain dimensions:**
- Profile: each of the three.
- Gate list: a name absent from `GATES`; an import raising; no `check`; `check` not callable; a gate raising; an empty `Result`; a non-`Result`.
- `--base`: forwarded exactly to `BASE_GATES`; an absent ref.
- argv: `--json` first or later; `--root` missing or repeated; an unknown flag; `--help`.
- Config: missing; a YAML error.
- Output order and exit code.

- [ ] **Step 1: Write the failing tests** (gate modules patched in `GATES`. Tests that run the real gates build a temporary repository with `helpers.make_repo`, whose first branch is `main`, or pass `--base HEAD`. No test relies on this checkout having a local `main`; F-B2p-3):
  ```python
  def test_profile_gates_literal():            # spec §12 (controller ruling); full tuples (F-B2p-4). The implementer writes the one
      # variant matching main at task start: CITES = () when gates/gate_cites.py is absent, else ("cites",); LIGHT_CITES equals CITES under the plan text, () if the owner rules D4 for spec §12's light column
      assert PROFILE_GATES == {"light": ("schema", "register", "decisions") + LIGHT_CITES,
                               "standard": ("schema", "register", "decisions", "claims") + CITES,
                               "strict": ("schema", "register", "decisions", "claims") + CITES}
  def test_base_gates_literal():
      assert BASE_GATES == ("decisions", "register", "claims")
  def test_strict_runs_profile_gates_in_order():
      assert gate_order(out)[:4] == ["schema", "register", "decisions", "claims"] and code == 0
  def test_missing_gate_fails():
      assert "FAIL run_all.missing.claims:" in out and code == 1
  def test_raising_gate_fails():
      assert "FAIL claims.input:" in out and code == 1
  def test_base_forwarded_only_to_base_gates():
      assert seen_args["decisions"][-2:] == ["--base", "x"] and "--base" not in seen_args["schema"]
  def test_version_line():                     # Q-B2plan-24 (a): no run_all.version line
      assert "run_all.version" not in out      # Q-B2plan-24 (a)
  def test_missing_config_is_input_fail():
      assert out.startswith("FAIL run_all.input:") and "/strict-delivery:init" in out
  def test_real_gates_pass_on_fixture_repo():  # make_repo fixture, --base HEAD
      assert code == 0
  ```
- [ ] **Step 2: Run the test command; expect FAIL.**
- [ ] **Step 3: Implement `gates/run_all.py`**.
- [ ] **Step 4: Run the test command on both interpreters, every enabled gate, and `python3 -m gates run_all`; expect PASS.**
- [ ] **Step 5: Commit** `feat(gates): run_all runs the profile's gates`, then checkpoint.

### Task 2b.2: git hook shims, `githook`, the installer

**Files:**
- Create: `gates/tools/githooks.py`
- Modify: `gates/__main__.py` (`COMMANDS["githook"]`, `COMMANDS["githooks"]`), `gates/lib/gitinfo.py` (additive: `unstaged_paths`, `hooks_dir`)
- Test: `tests/test_githooks.py`

**Owner answers applied:** F-3, F-r3-1, Q-1a2r-5; controller ruling on `core.hooksPath` and foreign hooks; Q-B2plan-11, Q-B2plan-12, Q-B2plan-13.

**Interfaces:**
- Consumes: `run_all.check`, `Result.render`, `result.GateError`, `gitinfo.toplevel/head_sha`, `config.load`.
- Produces:
  - `gitinfo.unstaged_paths(root: str) -> list` lists the tracked paths whose working-tree content differs from the index git is using.
    - It runs `git -C root diff --name-only -z --no-ext-diff --no-textconv` with `GIT_INDEX_FILE` inherited.
    - A relative `GIT_INDEX_FILE` (git gives the hook `.git/index`) resolves against `root`, because every gitinfo call runs with `-C root` (`gitinfo._run`).
    - A stat-only change is not listed. A deleted tracked file and an intent-to-add file are.
  - `gitinfo.hooks_dir(root: str) -> str`: `git rev-parse --git-path hooks`, made absolute.
  - `githook <pre-commit|pre-push> --root R [git's args]` (`main(argv: list) -> int`; F-B2p-2):
    - **Root rule.** The root is always the `--root` value, which the shim passes, because the shim's `cd` makes the current directory the framework's (Q-B2plan-13 (a)).
    - `CLAUDE_PROJECT_DIR` is never read. Every git call runs with `-C root`, and `commands.test` runs with `cwd=root`.
    - `pre-commit`:
      - when `unstaged_paths` is non-empty, print `FAIL githook.unstaged: <path>: tracked file has unstaged changes; stage it or stash it, so the gates read the tree being committed` and exit 1 before any gate runs (spec §13, F-3);
      - otherwise run `run_all.check(["--root", root])`;
      - on the strict profile, then run `commands.test` per Q-B2plan-11.
    - `pre-push`: per Q-B2plan-12.
  - `githooks install [--root R]`, backed by `install(root: str, framework: str) -> list`:
    - writes `pre-commit` and `pre-push` into `hooks_dir(root)` with mode `0o755`;
    - each file has three lines: `#!/bin/sh`, the header `# strict-delivery: generated by python3 -m gates githooks install; do not edit`, and the exec line of Q-B2plan-13 (a);
    - conflicts and `core.hooksPath` follow the controller ruling;
    - a file with the header is rewritten, byte-identical on a second run.
  - `githooks status [--root R]`: `PASS githooks.<name>`, or `FAIL githooks.<name>: missing | foreign | stale`. This is the input for block 4's `doctor`.

**Input-domain dimensions:**
- Working tree at commit:
  - clean;
  - a file staged, then changed again;
  - a file changed and not staged;
  - a file deleted and not staged;
  - `git add -N`;
  - a stat-only touch (passes);
  - an untracked file (passes);
  - `git commit -a` (the temporary index holds the change, so it passes);
  - `git commit <path>` with another file staged and changed (refused).
- `GIT_INDEX_FILE`: absolute, relative `.git/index`, relative with the shim's `cd` into the framework directory (F-B2p-2).
- `CLAUDE_PROJECT_DIR` naming another repository: ignored.
- A linked worktree.
- `run_all` failing, passing, raising.
- Strict `commands.test`: per Q-B2plan-11.
- Pre-push stdin: per Q-B2plan-12.
- Installer:
  - no hooks directory;
  - a foreign hook;
  - an own hook;
  - an own hook edited by hand;
  - `core.hooksPath` set;
  - a read-only hooks directory;
  - a bare repository.
- The shim run by a real `git commit`.

- [ ] **Step 1: Write the failing tests** (real `git commit` in `helpers.make_repo` repositories under `GitIsolatedTestCase`; the shim installed with `install(root, FRAMEWORK)` pointing at this checkout):
  ```python
  def test_unstaged_change_refuses_commit_before_gates():   # F-3
      assert proc.returncode != 0 and "githook.unstaged: a.txt" in proc.stdout + proc.stderr and gates_called == []
  def test_commit_a_with_unstaged_change_passes_check():
      assert "githook.unstaged" not in out
  def test_partial_commit_with_other_staged_change_refused():
      assert proc.returncode != 0
  def test_relative_index_file_with_cd_shim():  # F-B2p-2, Q-B2plan-13 (a)
      assert "githook.unstaged: a.txt" in out  # the target's index is read, not the framework's
  def test_root_ignores_claude_project_dir():
      assert proc.returncode == 0
  def test_clean_tree_runs_run_all():
      assert "PASS schema.config" in out and proc.returncode == 0
  def test_failing_gate_refuses_commit():
      assert proc.returncode != 0 and git(root, "rev-parse", "HEAD") == before
  def test_install_refuses_foreign_hook():
      assert code == 1 and read(hook) == FOREIGN
  def test_hooks_path_refused():
      assert code == 1 and "core.hooksPath" in err
  def test_shim_shape():
      lines = read(hook).splitlines()
      assert len(lines) == 3 and lines[0] == "#!/bin/sh" and lines[1].startswith("# strict-delivery: generated") and lines[2].startswith(("exec ", "cd "))
  def test_status_reports_stale_shim():
      assert "FAIL githooks.pre-commit: stale" in out
  ```
- [ ] **Step 2: Run the test command; expect FAIL.**
- [ ] **Step 3: Implement `githooks.py` and the two `gitinfo` additions.**
- [ ] **Step 4: Run the test command on both interpreters and `python3 -m gates run_all`; expect PASS.**
- [ ] **Step 5: Commit** `feat(tools): git hook shims, githook pre-commit and pre-push, installer`, then checkpoint.

### Task 2b.3: self-adoption: CI workflow, hooks, `run_all` as the commit gate

**Files:**
- Create: `.github/workflows/strict-delivery.yml`
- Modify: `.strict-delivery/config.yml`, only the keys Q-B2plan-11 and Q-B2plan-21 set
- Test: `tests/test_self_adoption.py`

**Owner answers applied:** spec §16; controller ruling on hook install timing; Q-B2plan-11, Q-B2plan-20, Q-B2plan-21.

**Interfaces:**
- Consumes: `run_all.main`, `githooks.install/status`, `index.main` (Task 1c.3), `config.load`.
- Produces:
  - The workflow:
    - triggers: `push` and `pull_request`;
    - matrix: an ubuntu and a macOS runner, crossed with `3.9` and `3.13` (runner labels and action references per Q-B2plan-20);
    - steps: checkout with full history; set up Python; `python -m unittest discover -s tests -t . -v`; `python -m gates index`; `python -m gates run_all --base origin/<base>`;
    - `<base>` is the pull request's base branch, or, on push, the default branch from the event payload.
  - Hook install per the controller ruling (after the block-2b merge).
  - From this commit, the commit gate is `run_all` plus the suite on both interpreters.

**Input-domain dimensions:**
- The workflow file: not a framework data file; no `schema:` line.
- The four matrix cells.
- Base on push to the default branch, on a pull request, on push to another branch.
- A shallow clone.
- The suite under CI: no test relies on a local `main` (F-B2p-3).
- Linked worktrees of live streams (controller ruling).

- [ ] **Step 1: Write the failing tests** (`tests/test_self_adoption.py`):
  ```python
  def test_workflow_matrix():
      assert pythons(text) == ["3.9", "3.13"] and len(oses(text)) == 2
  def test_workflow_runs_suite_index_run_all_in_order():
      assert step_order(text) == ["unittest", "index", "run_all"]
  def test_workflow_full_history():
      assert "fetch-depth: 0" in text
  def test_workflow_names_no_branch():
      assert "origin/main" not in text
  def test_actions_pinned():                   # Q-B2plan-20 (a)
      assert all(re.fullmatch(r"[^@\s]+@[0-9a-f]{40}", u) for u in uses(text))
  def test_run_all_passes_on_a_copy_with_main():   # F-B2p-3: git clone this checkout into a temp dir, create local main from HEAD
      assert run_all_code == 0
  ```
- [ ] **Step 2: Run the test command; expect FAIL.**
- [ ] **Step 3: Write the workflow** (and the config keys of Q-B2plan-11 (a) and Q-B2plan-21: `commands.test`, one string that runs the suite on both interpreters; `top_tier_roles: [final_verifier, exception_reviewer]`, with `tier4` unset).
- [ ] **Step 4: Exercise the hooks in a disposable clone** (`mktemp -d`):
  - install;
  - one clean commit (passes);
  - one commit with an unstaged tracked change (refused before any gate);
  - ledger both outputs.
- [ ] **Step 5: Run the test command on both interpreters and `python3 -m gates run_all`; expect PASS.**
- [ ] **Step 6: Commit** `feat(ci): self-adoption: CI workflow, git hooks, run_all commit gate`, then checkpoint.
  - After the push, the first CI run is green on all four cells before the block-2b final review.
  - After the block-2b merge, the session controller confirms every live stream branch has updated from `main`, installs the hooks in this repository, runs `githooks status` (all PASS), and ledgers the hook path and shim text.
  - **Block 2b end:** as block 1d.

---

## Block 2c: claims tool, `config/2`, `gate_dispatch` (branch `block/b2c`)

### Task 2c.1: `claims add | verify`

Runs before block B1 merges; it depends only on 2a (F-B2p-8).

**Files:**
- Create: `gates/tools/claims_cli.py`
- Modify: `gates/__main__.py` (`COMMANDS["claims"]`), `gates/producers.py` (add `gates.tools.claims_cli`)
- Test: `tests/test_claims_cli.py`

**Owner answers applied:** controller ruling on claim shape; Q-B2plan-2, Q-B2plan-4, Q-B2plan-6.

**Interfaces:**
- Consumes: `claims.*`, `ids.mint/utc_today`, `gitinfo.head_sha`, `gitinfo.blob_id` (Q-B2plan-4 (a)), `yamlsub.emit`, `config.load`, and the ids of every register.
- Produces: `PRODUCES = ("claim",)`; `main(argv: list) -> int`:
  - `add --document D --text T --cite C (at least once) --direct CMD --contradiction CMD --by WHO [--root R]`:
    - mints `C-<YYYYMMDD>-<xxxx>` with `random.SystemRandom()`;
    - records freshness as each cite's `blob` from `gitinfo.blob_id` (Q-B2plan-4 (a));
    - appends to `<paths.claims>/<slug(D)>.yml`;
    - validates the whole file before writing;
    - prints the id last.
  - `verify ID --by WHO`, run after the caller has re-run both commands:
    - refuses when a cited path has unstaged changes, so the recorded reference holds the verified text;
    - otherwise re-records freshness as `add` does.

**Input-domain dimensions:**
- Each flag missing, repeated, empty.
- `--document` and `--cite` forms of Task 2a.2.
- Text with a newline, unicode, `: `, a leading `-`.
- `verify` on an unknown id, a malformed id, a cited file with unstaged changes.
- A mint collision across the three registers.
- The claims directory missing.

- [ ] **Step 1: Write the failing tests:**
  ```python
  def test_add_writes_fresh_claim():
      assert out.splitlines()[-1] == cid and id_problem(cid, "C") == "" and gate_claims.check(["--root", root]).ok()
  def test_add_without_contradiction_writes_nothing():
      assert code == 1 and listdir(claims_dir) == before
  def test_change_and_verify_in_one_commit():  # F-B2p-1: edit cited file, git add, verify, commit through the hook
      assert proc.returncode == 0
  def test_verify_refuses_unstaged_cited_file():
      assert code == 1 and rec(cid) == before
  def test_gate_schema_checks_claims_now():
      assert "PASS schema.claim" in out
  ```
- [ ] **Step 2: Run the test command; expect FAIL.**
- [ ] **Step 3: Implement `claims_cli.py`.**
- [ ] **Step 4: Run the test command on both interpreters and `python3 -m gates run_all`; expect PASS.**
- [ ] **Step 5: Commit** `feat(tools): claims add and verify`, then checkpoint.

### Task 2c.2: `config/2` with `limits`, `merge` and `escape_cost`, and its migration

**Files:**
- Modify:
  - `gates/schemas/config.yml`: version 2, `limits`, `merge` (owner Q-Pplan-14 (a), 2026-11-02) and `escape_cost` (owner Q-B6plan-3 (a), 2026-11-02).
  - `gates/lib/config.py`: `CONFIG_KEYS` gains `limits`, `merge` and `escape_cost`; `DEFAULTS["merge"] = {"mode": "host"}`; the tag check uses the current version; the `limits` and `escape_cost` checks (no `DEFAULTS["limits"]` and no `DEFAULTS["escape_cost"]`: both are absent by default).
  - `gates/lib/migrations.py`: the `("config", 1)` step.
  - `.strict-delivery/config.yml`: tag `config/2`, migrated in the same commit.
  - `tests/helpers.py` (A's shared file): `minimal_config()` returns `schema: config/2`. Otherwise every `make_repo` test fails once `config.load` refuses `config/1`. Measured by the reviewer: no `config/1` literal exists on `block/sb1`, `block/sc1` or `block/sc2` outside A's files.
  - `tests/test_decisions_lib.py`: its `config/1` literal becomes `config/2`.
  - Any other `config/1` literal in A's tests: the implementer greps for them and lists them in the report.
- Test: `tests/test_config.py`, `tests/test_migrations.py`, `tests/test_gate_schema.py`
- **Spec and plan edits, made before dispatch by the session controller with the owner's approval.** These are Q-H2's consequence; the plan and specs belong to the session controller and the owner.
  - Spec §6 gains the `limits` key: `max_children`, `max_depth`, `max_concurrent`, with their units; every limit is absent by default (no default value). It also gains `merge` (`mode: host | controller`, default `host`; owner Q-M1, Q-Pplan-14 (a)) and `escape_cost` (unset by default; spec edit SE6-2, owner Q-B6plan-3 (a); applied 2026-11-02).
  - Plan Task 1a.2 changes in three places: `CONFIG_KEYS` ("the spec §6 key set plus `schema`") gains `limits`, `merge` and `escape_cost`; `DEFAULTS` gains only `merge: {mode: host}` (no `limits` or `escape_cost` default); and "`schema` equal to `config/1`" becomes "equal to the current config version".

**Why a new config version.** Q-H2 puts `limits.max_children.<role>` in config. `config.load` refuses a top-level key outside `CONFIG_KEYS` (OQ-16), and `config/1`'s schema refuses unknown keys. So adding `limits` is a shape change, and spec §15 requires "a new schema version plus a migration from the old version". The migration is placed here, in the registry Task 2a.1 created, before Task 2c.3 reads the key.

**Owner answers applied:** Q-H2, OQ-1, OQ-16; Q-B2plan-22, Q-B2plan-23; Q-M1, Q-Pplan-14 (a); Q-B6plan-3 (a).

**Interfaces:**
- Consumes: `migrations.MIGRATIONS/migrate/current_version`, `config.load/DEFAULTS/CONFIG_KEYS`, `schema.validate`.
- Produces:
  - `config/2` adds the optional key `limits`, a mapping with three keys:
    - `max_children`: a mapping from key to `int` ≥ 1, where absent means no cap (Q-H2). A key names the dispatcher's role; `session` is an allowed key (Q-B2plan-23 (a)).
    - `max_depth`: an `int` ≥ 1, the deepest subagent level allowed, with the main session at level 0.
    - `max_concurrent`: an `int` ≥ 1, the most subagents running at once in one session.
  - Both `max_depth` and `max_concurrent` are absent by default. When one is absent, only the Claude Code value counts (Task 2c.3, `limits_of`).
  - A playbook rule or lasting decision tightens a cap only by having `limits.max_children` changed under spec §6's `overrides`, the entry naming the authorising decision; a decision with no config change tightens nothing (Q-B2plan-23 (a)).
  - `config/2` also adds the optional `merge` (`map {mode: enum [host, controller]}`), default `host` (fail-closed: no agent merges unless the project says so). Its reader is programs Task P3.1; this repository sets `controller` there.
  - `config/2` also adds the optional `escape_cost` (`map {CRITICAL, HIGH, MEDIUM, LOW}`, each an `int` with `min: 0`), unset by default (no `DEFAULTS` entry). When the map is present all four severities are required, and an unknown key is refused (OQ-16). Its reader is block 6 Task 6E.3 (`loopstats`), which only reads it (Q-B6plan-3 (a)).
  - `MIGRATIONS[("config", 1)]` sets `schema: config/2` and nothing else.
  - `config.load` accepts only `config/<current>` and refuses the older tag. It names `run /strict-delivery:upgrade`, as `gate_schema` does.

**Input-domain dimensions:**
- `limits` absent, empty, or not a mapping.
- `max_children`:
  - not a mapping;
  - a key that is neither a `ROLES` id nor, under Q-B2plan-23 (a), `session` (refused);
  - values `0`, `-1`, `True`, `"2"`.
- `max_depth` and `max_concurrent`: absent, `0`, `bool`, `str`, very large.
- Tag `config/1` after this task: `gate_schema` and `config.load` refuse it with the upgrade hint, and `migrate` gives `config/2`.
- `merge`: absent (default `host`), `{mode: controller}`, `{mode: auto}`, not a mapping, an unknown key.
- `escape_cost`: absent (unset); all four `0`; all four set; one severity missing; an unknown key (`INFO`); values `-1`, `True`, `"2"`; not a mapping.
- This repository's config migrated.

- [ ] **Step 1: Write the failing tests:**
  ```python
  def test_config_1_migrates_to_2():
      assert migrate("config", {"schema": "config/1", "profile": "strict"}) == {"schema": "config/2", "profile": "strict"}
  def test_limits_accepted_and_checked():      # subTests per bad value
      assert config.load(root_with({"limits": {"max_children": {"stream_controller": 4}}}))["limits"]["max_children"]["stream_controller"] == 4
  def test_no_limits_by_default():             # Q-H2; depth and concurrency fall back to Claude Code's values (Task 2c.3)
      assert config.load(root).get("limits", {}) == {}
  def test_minimal_config_is_current():
      assert helpers.minimal_config()["schema"] == "config/2"
  def test_config_1_refused_with_upgrade_hint():
      assert "/strict-delivery:upgrade" in str(e.exception)
  def test_merge_mode_default_and_checked():   # Q-Pplan-14 (a); subTests per bad value
      assert config.load(root)["merge"]["mode"] == "host"
  def test_escape_cost_optional_and_checked():  # Q-B6plan-3 (a); subTests per bad value
      assert "escape_cost" not in config.load(root)
  def test_this_repo_config_is_current():
      assert "PASS schema.config" in out
  ```
- [ ] **Step 2: Run the test command; expect FAIL.**
- [ ] **Step 3: Implement**, and migrate this repository's `.strict-delivery/config.yml` with `migrations.migrate` (a config file, not a global record, so the implementer writes it).
- [ ] **Step 4: Run the test command on both interpreters and `python3 -m gates run_all`; expect PASS.**
- [ ] **Step 5: Commit** `feat(lib): config/2 with limits, merge and escape_cost; config migration`, then checkpoint.

### Task 2c.3: dispatch rules and `gate_dispatch`; enable `check dispatch`

Starts only after block B1 merges into `main` and A updates from `main`.

**Files:**
- Create: `gates/lib/dispatch.py`, `gates/gate_dispatch.py`
- Modify: `gates/__main__.py` (`GATES["dispatch"]`), `tests/test_playbook_drift.py` (the `MIN_TIERS` drift test; see Task 2a.1, "Drift tests")
- Test: `tests/test_dispatch_lib.py`, `tests/test_gate_dispatch.py`, `tests/test_playbook_drift.py`

**Owner answers applied:** DB-1, DB-2, Q-H1, Q-H2, Q-H3, Q-H4, Q-H5 (a); stream rules "Cross-stream order"; Q-B2plan-16, Q-B2plan-17, Q-B2plan-18, Q-B2plan-19, Q-B2plan-22, Q-B2plan-23.

**Interfaces:**
- Consumes: Task B1.1's prompt-block format; `config.load` (`models.tiers`, `top_tier_roles`, `limits`); `result.*`; and, under Q-B2plan-19 (a), `decisions.in_force` and `claims.load/stale_errors`.
- Produces:
  - `dispatch.HEADINGS: tuple`: the spec §10 headings, in order. The budget heading is matched as `## Budget: tokens=<n> minutes=<n>`, where `n` is a positive decimal integer with no leading zero.
  - `dispatch.ROLES: tuple`: the spec §10 roles in spec order, `program_controller` kept (Q-H1). Plus the project roles Q-B2plan-16 admits.
  - `dispatch.CONTROLLER_ROLES: tuple = ("program_controller", "stream_controller", "controller")`. Every other role in `ROLES` is a worker. `session` is the main session's own dispatcher id and is not a role.
  - `dispatch.MIN_TIERS: dict` (DB-2), under Q-B2plan-16 (a).
  - `dispatch.DISPATCHERS: dict`, keyed by `program_live` (`True` or `False`), then by child role, giving the dispatcher ids allowed to dispatch that child. Sources: spec §10 lifecycle, prog §4, Q-H3, Q-H5 (a). F-B2p2-5: a plain plan and a program are told apart.
    - **A program is live.** The session acts as program controller (Q-H5 (a)). Prog §4: the program session never "implements, reviews, or holds detail".
      - `program_controller`: `("session",)`;
      - `stream_controller`: `("session", "program_controller")`;
      - `controller`: `("stream_controller", "controller")` (Q-H3);
      - every worker: `("stream_controller", "controller")` (spec §10: "stream controllers and their sub-controllers dispatch the workers").
    - **No program is live (plain plan).** Spec §10: "in a plain plan, the controller dispatches every role". The session is that controller (spec §7.1: "In a plain plan the same holds for the controller's session").
      - `program_controller` and `stream_controller`: `()`, so both are refused;
      - `controller`: `("session", "controller")`;
      - every worker: `("session", "controller")`.
  - `dispatch.LEVELS_BELOW: dict = {"program_controller": 2, "stream_controller": 1, "controller": 1}`: the least number of levels a controller-role child needs under it. A `program_controller` needs a stream and then a worker. A stream or sub-controller needs a worker. Workers need 0 (F-B2p2-4). `depth_ok(role: str, dispatcher_depth: int, max_depth: int) -> bool` is `dispatcher_depth + 1 + LEVELS_BELOW.get(role, 0) <= max_depth`.
  - `parse(prompt: str) -> tuple` of `(sections: dict, errors: list)`. Every line starting `## ` is a heading. The headings must be exactly `HEADINGS`, in order, each once. Text before `## Role` is an error.
  - `role_of(body: str) -> str` (Q-B2plan-18 (a)). A non-role raises `ValueError`, reported as `FAIL dispatch.role`.
  - `block_errors(body: str, role: str, prompts_dir: str) -> list` (Q-B2plan-18 (a)): the body equals `"\n" + <file> + "\n"`.
  - `tier_of(model: str, cfg: dict) -> Optional[int]` (Q-B2plan-17 (a)). A model named by two tiers raises `ValueError`, reported as `FAIL dispatch.tier`.
  - **Top tier when `tier4` is unset** (owner Q-B2plan-21, amending Q-B2plan-17 (a)): a `top_tier_roles` role is checked against the tier named by `models.top_tier_fallback`, which defaults to `tier3`; a project raises the top tier by setting `tier4`. `top_tier_fallback` naming a tier that is unset or not `tier1`-`tier4` fails `dispatch.tier`. Input rows: `tier4` unset with fallback default; fallback set to `tier2`; fallback naming `tier9`; `tier4` set (fallback ignored).
  - `limits_of(cfg: dict, env: Mapping[str, str]) -> tuple` of `(max_depth, max_concurrent)` (F-B2p2-3: fails closed when a variable is unset).
    - **The Claude Code value.**
      - Depth is `N + 1` when `CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH` is set to `N`, else `CLAUDE_DEFAULT_DEPTH = 3`.
      - Concurrency is `N` when `CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS` is set to `N`, else `CLAUDE_DEFAULT_CONCURRENT = 20`.
      - The mapping and both defaults are the measured facts at the top of this section. They are module constants, pinned by tests that cite the measurement (Q-B2plan-22).
    - **Effective limit.** The minimum of `limits.max_depth` / `limits.max_concurrent` (when set) and the Claude Code value. The Claude Code value always counts, set or unset.
    - An environment value that is not a decimal integer of at least 1 raises `ValueError`, reported as `FAIL dispatch.input`.
  - `gate_dispatch.check(args)`, gate `dispatch`:
    - **Arguments.** `--root`; `--prompts DIR`, defaulting to `skills/strict-delivery/prompts` beside the installed `gates` package and never under `--root` (spec §3); and `--input FILE`.
    - **Input file.** A JSON object with:
      - `prompt` (`str`, required);
      - `subagent_type` and `model` (`str`, optional);
      - `dispatcher` (required): an object with four fields:
        - `id`: a `ROLES` id or `"session"`;
        - `depth`: an `int` ≥ 0, the dispatcher's level, 0 = the main session;
        - `live_children`: an `int` ≥ 0, the dispatcher's running children;
        - `live_total`: an `int` ≥ 0, the session's running subagents.
      - `program_live` (`bool`, required).
      - **Who supplies the context.** The caller supplies `dispatcher` and `program_live`: block 3's PreToolUse Agent hook, which counts live subagents and takes `program_live` from `programs.live_programs` (programs Task P2.1), and P4 for the program roles. An absent or malformed field fails `dispatch.input` (fail-closed). The gate cannot count for itself, so the cap and concurrency checks are only as exact as the caller's count (F-B2p2-10). The caller must not supply a count it cannot determine.
    - **Lines:**
      - `dispatch.input`;
      - `dispatch.fork`: `subagent_type` is `fork` (spec §10);
      - `dispatch.grammar`;
      - `dispatch.role`;
      - `dispatch.dispatcher`: FAIL when `dispatcher.id` is a worker role (Q-H4: "refuses any dispatch from a worker role"), or is not in `DISPATCHERS[program_live][role]`;
      - `dispatch.depth`: FAIL when `dispatcher.depth + 1 + LEVELS_BELOW.get(role, 0)` exceeds `max_depth`. A controller dispatch that leaves no level for its workers is refused at dispatch, not later (F-B2p2-4);
      - `dispatch.concurrency`: FAIL when `live_total + 1` exceeds `max_concurrent`. Claude Code refuses rather than queues past its limit, so the gate refuses first;
      - `dispatch.children`: FAIL when the cap of Q-B2plan-23 is set and `live_children + 1` exceeds it (Q-H2);
      - `dispatch.model`: the tool's `model` equals the `## Model` body's single line; an absent tool model fails (spec §10);
      - `dispatch.tier`;
      - `dispatch.top-tier`;
      - `dispatch.block`;
      - under Q-B2plan-19 (a): `dispatch.claims`, `dispatch.decisions`, and one `PASS dispatch.in-force.<id>` per in-force decision whose `applies_to` matches a path named in `## Brief`.
    - **Q-H5 (a) under the default depth.** The limit is 3, so the default tree passes: session (level 0) dispatching a stream (level 1, needs 1 below), a sub-controller (level 2, needs 1 below), and workers (level 3).
      - A separate `program_controller` at level 1 needs two levels below it: stream at 2, worker at 3. That fits within 3 but leaves no room for a sub-controller.
      - A stream at level 2 dispatching a `controller` at level 3 is refused: level 3 + 1 > 3.
      - Raising the depth (env and config) admits deeper trees, with no tree shape written into the gate.
  - **This repository's own dispatches (F-B2p-7, F-B2p2-2).** They pass only when written in the grammar:
    - `## Budget: tokens=<n> minutes=<n>` and `## Task` present;
    - `## Role` a role id;
    - `## Strict block` byte-equal to that role's file;
    - the dispatch tool's `model` set;
    - `dispatcher` and `program_live` supplied.
  - The current dispatches use a bare `## Budget`, no `## Task`, prose roles and edited strict blocks, so they fail.
  - Final reviewers, final verifiers and investigators map onto their spec roles unchanged.
  - Plan writers, drafting agents and plan reviewers are not mapped onto `implementer` or `task_reviewer`. Those blocks override every other instruction and impose TDD, mutation transcripts and commits (Task B1.1's `implementer.md`), and the reviewer block reviews task code. A draft-only Brief cannot limit them. Q-B2plan-16 decides the roles these dispatches use.

**Input-domain dimensions:**
- Input file: missing; a directory; invalid JSON; a list; `prompt` absent or non-str.
- `dispatcher`:
  - absent; not an object;
  - `id` unknown, a worker, `session`;
  - `depth` negative, `bool`, at the limit, above it;
  - `live_children` and `live_total` at, below and above their limits.
- `program_live`: absent, non-bool, `True`, `False`.
- Depth with `LEVELS_BELOW`: each controller role dispatched at each level 0-3 under limits 3 and 6. Expected under limit 3:
  - `program_controller` from level 0 passes, and from level 1 is refused;
  - `stream_controller` and `controller` pass from levels 0-1, and are refused from level 2;
  - workers pass from levels 0-2.
- `limits_of`:
  - env unset;
  - env `1`, `2`, `5`, `0`, `-1`, `abc`, `""`, `" 5"`;
  - config above, equal to and below the Claude Code value;
  - config set and env unset: the effective value is never above 3 or 20 (F-B2p2-3).
- `subagent_type`: `fork`, `Fork`, absent.
- Headings: missing; reordered; duplicated; an extra `## X`; `##Role`; `### Role`; a `## ` line inside `## Brief`; a preamble; CRLF; a BOM.
- Budget forms: `tokens=0`, `01`, `-1`, `1.5`, `minutes` missing, extra spaces, a bare `## Budget`.
- Role body: a role id alone; a role id with trailing text; an unknown role; `program_controller` before P4's prompt file exists.
- Every (program_live, dispatcher, child) triple over `{True, False}` × (`ROLES ∪ {session}`) × `ROLES` (2 × 13 × 12), against `DISPATCHERS`.
- Model: absent; equal; different; different case; two lines; named by no tier; named by two tiers; `tier4` unset.
- Tier: each role at, above and below `MIN_TIERS`; top tier inside and outside `top_tier_roles`.
- Strict block: byte-equal; a trailing space; a missing final empty line; CRLF; another role's block; the file missing.
- Limits: config only; env only; both; neither (Q-B2plan-22).
- Config: missing.

- [ ] **Step 1: Write the failing tests** (fixture prompt files in temp directories; B's paths are never read except by the drift test):
  ```python
  # test_dispatch_lib.py
  def test_roles_literal():                    # spec §10, Q-H1 (F-B2p-4)
      assert ROLES[:12] == ("program_controller", "stream_controller", "controller", "implementer", "implementer_transcription",
          "task_reviewer", "final_reviewer", "final_verifier", "exception_reviewer", "audit_reviewer", "audit_verifier", "investigator")
  def test_min_tiers_literal():                # DB-2, the full table
      assert MIN_TIERS == {"implementer_transcription": 1, "implementer": 2, "controller": 3, "program_controller": 3,
          "stream_controller": 3, "task_reviewer": 3, "final_reviewer": 3, "audit_reviewer": 3, "audit_verifier": 3,
          "investigator": 3, "final_verifier": 4, "exception_reviewer": 4}
  def test_dispatchers_all_triples():          # 2 x 13 x 12 subTests against the expected table written out in the test
      assert (d in DISPATCHERS[live][child]) == EXPECTED[(live, d, child)]
  def test_program_session_may_not_dispatch_workers():   # F-B2p2-5
      assert "session" not in DISPATCHERS[True]["implementer"] and "session" in DISPATCHERS[False]["implementer"]
  def test_limits_measured_mapping():          # coordinator measurements 2026-11-01
      assert limits_of({}, {}) == (3, 20) and limits_of({}, {"CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH": "5"})[0] == 6
      assert limits_of({"limits": {"max_depth": 5, "max_concurrent": 30}}, {}) == (3, 20)   # env unset: never fails open
      assert limits_of({"limits": {"max_concurrent": 10}}, {"CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS": "30"})[1] == 10
  def test_controller_needs_levels_below():    # F-B2p2-4, limit 3
      assert depth_ok("program_controller", 0, 3) and not depth_ok("program_controller", 1, 3) and not depth_ok("controller", 2, 3) and depth_ok("implementer", 2, 3)
  def test_headings_exact_order():
      assert parse(GOOD)[1] == [] and parse(swap(GOOD, "## Brief", "## Role"))[1]
  def test_block_byte_for_byte():
      assert block_errors("\n" + BLOCK + "\n", "implementer", d) == [] and block_errors("\n" + BLOCK + " \n", "implementer", d)
  def test_model_in_two_tiers_is_error():
      with self.assertRaises(ValueError): tier_of("m", {"models": {"tiers": {"tier3": "m", "tier4": "m"}}})
  # test_gate_dispatch.py
  def test_valid_dispatch_passes():
      assert code == 0 and "PASS dispatch.block" in out and "PASS dispatch.dispatcher" in out
  def test_worker_dispatcher_refused():        # Q-H4; subTest per worker role
      assert "FAIL dispatch.dispatcher" in out
  def test_sub_controller_may_dispatch_sub_controller():   # Q-H3
      assert "PASS dispatch.dispatcher" in out
  def test_depth_limit():                      # depth 2 dispatcher at max_depth 3 passes; depth 3 fails
      assert "PASS dispatch.depth" in ok_out and "FAIL dispatch.depth" in deep_out
  def test_concurrency_limit():
      assert "FAIL dispatch.concurrency" in out
  def test_child_cap():                        # Q-H2
      assert "FAIL dispatch.children" in capped_out and "PASS dispatch.children" in uncapped_out
  def test_absent_dispatcher_fails_input():
      assert out.startswith("FAIL dispatch.input")
  def test_fork_refused():
      assert "FAIL dispatch.fork" in out
  def test_absent_tool_model_fails():
      assert "FAIL dispatch.model" in out
  def test_below_min_tier_fails():
      assert "FAIL dispatch.tier" in out
  def test_top_tier_only_for_top_tier_roles():
      assert "FAIL dispatch.top-tier" in out
  def test_prompts_never_read_from_root():
      assert "PASS dispatch.block" in out
  # test_playbook_drift.py
  def test_min_tiers_match_roles_md():         # skipTest only when playbook/roles.md is absent (Task 2a.1, Drift tests)
      assert {r: "tier%d" % t for r, t in MIN_TIERS.items()} == tiers_column(read("playbook/roles.md"))
  ```
- [ ] **Step 2: Run the test command; expect FAIL.**
- [ ] **Step 3: Implement `dispatch.py` and `gate_dispatch.py`.**
- [ ] **Step 4: Run the test command on both interpreters and `python3 -m gates run_all`; expect PASS.**
- [ ] **Step 5: Enable on this repository.**
  - Build a dispatch JSON in a `mktemp -d` directory from the real `skills/strict-delivery/prompts/implementer.md`, with `dispatcher` `{id: session, depth: 0, live_children: 0, live_total: 0}` and `program_live: false`.
  - Run `python3 -m gates check dispatch --input <file>`; expect every line PASS.
  - Ledger the dispatch template that Q-B2plan-16's answer gives this repository's plan writers and reviewers. `run_all` does not run this gate (Q-B2plan-19 (a)).
- [ ] **Step 6: Commit** `feat(gates): gate_dispatch: grammar, dispatcher, depth and limits, model and tier, strict block; enable check dispatch`, then checkpoint with `gates=PASS`. **Block 2c end:** as block 1d; this ends block 2.

---

## Programs block (sub-blocks P1, P2, P3, P4)

Spec §17: "Programs block, placed after block 2 so this repository can run its remaining blocks as a program: the program_controller and stream_controller prompt blocks, automatic continuation, the upward-question path, a basic `gate_checkpoint`, `gate_streams`, and `gate_cleanup` (for plain plans and programs). The plan fixes its exact order." Programs design §16: "It carries the minimum it relies on from later blocks". The outline's order P1-P4 stands, each a sub-block of at most 3 tasks:
- **P1** (Tasks P1.1-P1.3): schema vocabulary for nested and front-matter files, the handoff and ledger schemas (with the `MERGED` line), basic `gate_checkpoint`.
- **P2** (Tasks P2.1-P2.3): program records (streams, request, status, sync log), the `program` tool, `gate_streams`.
- **P3** (Tasks P3.1-P3.3): the pull-request merge policy (`merge.mode`, merges checked against the ledger's `MERGED` lines, no push to the base branch), cleanup rules with the merge-commit half of the deletion proof, `gate_cleanup`.
- **P4** (Tasks P4.1-P4.3): the upward-question path, automatic continuation, `gate_dispatch` for live programs with the two prompt blocks.

Each sub-block has its own branch (`block/p1` ... `block/p4`) from the tip of `main`, starts after block 2 has merged into `main`, and is pushed at every checkpoint. It ends in the pull-request flow (owner directive and Q-15 below): final review, verifier, a pull request to `main` (`gh pr create`), the owner's approval in chat naming the PR and its head sha, `gh pr merge <n> --merge --match-head-commit <that sha>` (GitHub refuses the merge if the head moved), the merge read back from the host (`gh pr view <n> --json number,headRefOid,mergeCommit,mergedAt,mergedBy`), the post-merge gate run on an updated `main`, and a `MERGED` ledger line (Task P1.2) as the first commit of the next branch (the next sub-block's branch, or the cleanup branch after the plan's last PR, with `final=yes`). The commit gate is `python3 -m gates run_all` plus the test command on both interpreters, with a clean tree (block 2, Task 2b.3). From Task P1.3 the checkpoint step also runs `python3 -m gates check checkpoint --plan 2026-10-31-strict-delivery-framework`, and expects PASS after the checkpoint commit.

Owner answers (2026-11-02): every question of the programs batch was answered (a) (section "Programs block (2026-11-02)" in the owner answers below). The tasks state those answers.

**Owner answers applied across the block (binding, 2026-11-01; written into the specs by edits SE-1..SE-19, listed in "Programs block (2026-11-02)" in the owner answers below):**
- **Q-H1:** `program_controller` stays a role.
- **Q-H2:** per-role child caps `limits.max_children.<role>` in config (block 2, Task 2c.2), no cap by default, tightened only through recorded config overrides (block-2 answer Q-B2plan-23 (a): the key names the dispatcher's role; `session` is a key).
- **Q-H3:** a sub-controller (`controller`) may dispatch a sub-controller when the stream agent judges it better.
- **Q-H4:** `gate_dispatch` refuses any dispatch from a worker role.
- **Q-H5 (a):** depth-aware tree. By default the session itself acts as program controller (status page, ids, requests, syncs, one question batch); `stream_controller` runs at level 1, sub-controllers at level 2, workers at level 3. A separate `program_controller` agent and nested sub-controllers are used only when the configured depth allows them (block 2's `dispatch.depth_ok` and `LEVELS_BELOW` decide; nothing in this block writes a tree shape into a gate).
- **Measured Claude Code facts (2026-11-01):** with `CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH` unset the Agent tool exists at levels 1-2 (level 3 is a leaf); set to 5 it exists at levels 1-5; with `CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS` unset a launch past 20 is refused, not queued; set to 30, 25 ran at once. Block 2 pins these as `dispatch.limits_of` constants (Q-B2plan-22 (a)). A controller stays alive while its children run; questions go up by `SendMessage`; answers come down as decision records. Block 4's `init` writes both variables into the project `.claude/settings.json`; this repository already carries depth 5 and concurrency 30 there (commit 1e5bdc1), and Task P4.3 pins them with a test.
- **Block 2 answers consumed:** all (a), and Q-B2plan-21 as answered (plan Task 2c.3 and "### Block 2 (2026-11-01)"): "a `top_tier_roles` role is checked against the tier named by `models.top_tier_fallback`, which defaults to `tier3`; a project raises the top tier by setting `tier4`". So `tier4` is unset by default. Every model choice in this block (Task P4.2's `## Model`) resolves the tier the way `gate_dispatch` checks it, fallback included; this block names no model.
- **Owner directive, pull-request flow (binding, 2026-11-01):**
  - `main` is a protected branch in this repository and in every target repository: nothing merges or pushes to it directly. On this repository GitHub branch protection is already on (pull request required, admins enforced).
  - Work branches (stream, block, group) are pushed to the remote at checkpoints, so no work is lost (Task P1.3 checks it). The program controller also pushes `<program>/integration` after every commit it makes there, because CI reads `streams.yml` and the requests from it (Task P2.2).
  - A finished stream opens a pull request to `main`. Each sub-block of a plain plan is its own PR, so a plan merges several times.
  - **Q-M1:** the PR merge mode is a per-project setting: the owner merges on the host, or the owner approves in chat and the controller runs `gh pr merge`. This repository uses the second. Config key `merge.mode` lands per Q-Pplan-14; its reader is Task P3.1.
  - **Q-M4 (a):** each finished stream opens its own PR to `main`. The integration branch holds only program records (status page, requests, sync log, and the global records the program controller writes) and combined testing; it is never a merge stop on the way to `main` and never merges into it. Stream branches start from `main` and are judged against it (Task P2.3); how global records written there reach `main` is Q-Pplan-12.
- **Q-15 (a), merge approvals (binding, 2026-11-01):** approvals are not decision records in the repository.
  - `controller` mode (this repository): the owner approves in chat, naming the PR; the controller runs `gh pr merge <n> --merge --match-head-commit <the sha the owner approved>`, so GitHub refuses the merge if the head moved.
  - `host` mode: the owner's merge on the host is the approval.
  - In both modes the plan's ledger records who approved, when, the PR number, the head sha and the merge commit, read back from the host after the merge: the `MERGED` line (Task P1.2), whose `final=yes` marks the plan's last PR. "A PR merged" and "the plan's last PR" come from these lines, checked against git (Tasks P3.1, P3.2). Those checks prove that a merge of this plan's PR happened and merged exactly the recorded head sha, and that the recorded approval named that PR and sha; the approval itself rests on the owner's chat record and the ledger line (`approval`: the owner's words verbatim with the PR number and head sha they named, or `host`), which the owner reviews at the block end (review 5 F-Pp5-2). This settles what the revision-4 Q-Pplan-13 asked (keying on the PR, a `final` marker), so it is no longer a question; the grant-record machinery of revisions 3-4 (grant fields, grant commits, `gate_grant`) is removed.
- **Q-16 (a) (binding, 2026-11-01):** block 3's hook refuses any agent Edit or Write under `paths.decisions`; only the `decisions` tool writes there, and it refuses answers from agents (cross-block notes; spec edit SE-19).
- **Owner Q-ES (2026-11-01):** the optional finding fields `review_round`, `caused_by_change` and `dimension` (Task 1b.3 fix round) and the Block 6 `loopstats` tool with optional `escape_cost`. Tasks P3.2 and P3.3 read findings only for `status`, `resolved_by` and `owner`, and pass the other fields through untouched; nothing here writes or checks the Q-ES fields.

**Interfaces consumed from block 2 (the approved draft, by exact name):** `migrations.MIGRATIONS/migrate/current_version`; `config.load` with `config/2` `limits.max_children/max_depth/max_concurrent`; `run_all.PROFILE_GATES/BASE_GATES/check/main`; `githook pre-commit|pre-push` and `githooks install|status`; `gitinfo.unstaged_paths/hooks_dir/blob_id`; `claims.load/slug/stale_errors/base_errors`, `ClaimFile`; `dispatch.HEADINGS/ROLES/CONTROLLER_ROLES/MIN_TIERS/DISPATCHERS/LEVELS_BELOW/depth_ok/parse/role_of/block_errors/tier_of/limits_of`; `gate_dispatch.check` with its input object (`prompt`, `subagent_type`, `model`, `dispatcher {id, depth, live_children, live_total}`, `program_live`) and its lines `dispatch.input|fork|grammar|role|dispatcher|depth|concurrency|children|model|tier|top-tier|block|claims|decisions|in-force.<id>`. From block 1: `schema.*`, `store.Record/store_errors`, `ids.mint/id_problem/utc_today`, `decisions.validate/is_resolved/in_force/landed_errors/find`, `findings.may_delete/is_resolved/RESOLVED`, `gitinfo.toplevel/head_sha/commit_exists/show/ls_tree/merge_base/tracked_files/user_email`, `result.Result/GateError/gate_args/run_check/run_gate`, `decisions_cli.main`, `index.regenerate`, `helpers.make_repo/commit_all/write_record/GitIsolatedTestCase`.

**Controller rulings (spec settles each; ledgered in this form in the sub-block named, at most five per sub-block):**
- (P1) Controller ruling: `gate_checkpoint` and (P3) `gate_cleanup` are not in `run_all`'s lists; the checkpoint step runs `check checkpoint --plan <plan>`, and the cleanup change (Q-Pplan-9) runs `check cleanup` -- both gates need the plan or program they judge, which a commit does not name, and the spec places them at a checkpoint and after a merge -- cost if wrong: one `PROFILE_GATES` edit and a plan argument source -- spec §8 "clean worktree at every checkpoint", §9 "`gate_cleanup` (after a merge and at a program's close ...)".
- (P1, ledgered once, covering P2's `program` tool) Controller ruling: a gate or tool may be the producer that turns on `gate_schema` for a kind: `gate_checkpoint` declares `handoff` and `ledger` (timing per Q-Pplan-2); the `program` tool declares `streams`, `status`, `sync-log` and `request` -- the spec allows either -- cost if wrong: the declaration moves to another module -- spec Appendix A "A kind's producer has landed when a gate or tool in the installed framework version declares that kind in its `produces` list".
- (P2) Controller ruling (was Q-Pplan-7): a program is live when a local branch `<p>/integration` exists and its tip holds `<paths.programs>/<p>/streams.yml` (`programs.live_programs`), never from the current branch's tree; `gate_streams` joins `run_all`, and `gate_dispatch` checks the caller's `program_live`, whenever one is live, whatever the profile -- the program folder lives only on the integration branch and under Q-H5 (a) the session's own checkout is not that branch, so a current-branch reading would refuse every stream dispatch -- cost if wrong: a program whose integration branch exists only on a remote reads as not live in that clone -- programs design §7.2 "lives on the integration branch, committed only by the program controller"; spec §12 "Wherever a program is live, `gate_streams` and `gate_dispatch` run, whatever the profile".
- (P2) Controller ruling: the `program` tool writes program files only when the current branch is `<program>/integration` (where that branch is checked out is Q-Pplan-11); this is how "only the program controller" is enforced, since no tool can tell who calls it -- cost if wrong: a stream branch could carry a request edit until `gate_streams` refuses it -- programs design §6 "only the program controller creates or changes a request file, on the integration branch", §11 "The page lives on the integration branch".
- (P2) Controller ruling: `program create` refuses unless `--decision` names an answered decision of class `program-create` -- cost if wrong: a program starts without the owner's approval on record -- programs design §5 "Approving it is an owner decision of class `program-create`".
- (P2) Controller ruling: each stream implicitly owns `<paths.plan_state>/<its plan slug>/`; the program folder and the global record directories (`paths.decisions`, `paths.findings`) are owned by program commits on `<program>/integration` and by no stream; a merge commit whose second parent is reachable from the tip of `base_branch` (a sync's merge of main, into integration or into a stream branch) is exempt from the ownership check; and a merge of a stream head into `<program>/integration` for combined testing may change only paths that stream owns -- cost if wrong: one ownership rule, or every sync merge failing `gate_streams` -- programs design §12 "Each stream owns its own plan workspace; the program controller owns the program folder and is the only writer of global records within the program"; §10 "merge main into the integration branch, with no owner grant"; §14 "What stays ordinary git: code conflicts"; owner Q-M4 (a) "combined testing".
- (P2) Controller ruling (was Q-Pplan-10): a status row's `estimate` and `used` are non-negative decimal integers in the unit of the stream's `estimate` in `streams.yml`, which the program plan states (one unit per program) -- the drift check compares the two as numbers in one unit, so free text cannot serve it -- cost if wrong: a `status/2` migration -- programs design §12 `gate_drift`: "a block past `drift.estimate_factor_pct` percent (default 150) of its estimate is reported to the owner".
- (P3) Controller ruling: a pull request merges with a merge commit (`gh pr merge --merge`; on the host, the merge-commit method), never squash or rebase -- a squash or rebase merge leaves the reviewed branch commits out of `main`'s history, so `<sha>:<path>` evidence and the merge-commit proof stop resolving once the branch is deleted -- cost if wrong: the evidence rule needs another anchor -- spec §5 "`<sha>:<path>`, resolved with `git cat-file` (and required to name a commit in the repository)"; spec §7.2 "its merge commit exists on the target branch".
- (P3) Controller ruling: a spec is in a plan's per-effort set only when no other live plan's handoff names it in `spec` -- cost if wrong: a spec shared by two plans is cleaned while one still runs -- programs design §7.2 "`docs/strict-delivery/specs/<spec>.md` ... the spec's effort is done".

**Cross-block notes.**
- **Block 3:** the PreToolUse Agent hook supplies `dispatcher` and `program_live` (block 2). It takes `program_live` from `programs.live_programs` (Task P2.1; controller ruling on live programs), and runs `gate_dispatch` whenever `dispatch.required(root, cfg)` (Task P4.3) is true, so a live program is gated on the light profile too (spec §12).
- **Stream B (Q-PL-1 (a), owner 2026-11-02):** a cross-stream request to B, raised by A when Task P2.2 starts (stream rules, "Requests"): Task B2.2's `playbook/sessions.md` writes the planning steps for agents: plan every block of the spec and plan in full before any code (no outline-only block starts implementation), then write the stream breakdown plan last (`<paths.plan_state>/<plan>/breakdown.yml`, `breakdown/1`: streams and owned paths, tasks per stream, dependency edges, unblock conditions, parallel groups within the concurrency limit, the assumed concurrency and depth), and run streams as they unblock. The same request covers Task B2.1's `playbook/rules.md` row `SD-R4` (review F-QPL-5): its rule text also states plan in full before code and the stream breakdown as the last planning step, and its `enforced by` reads `program create` (Task P2.2) for a program, judgment otherwise. If B2 has merged by then, the request goes to whoever owns `playbook/sessions.md` and `playbook/rules.md` (DS-3).
- **Block 3 (stream B or A):** `playbook/streams.md` and `playbook/sessions.md` describe the Q-H5 default tree, the session as program controller and the PR flow. While B is live this is a cross-stream request to B, raised in Task P4.3 (stream rules, "Requests").
- **Block 3 (PR flow, Q-15):** the PreToolUse Bash hook refuses an agent's `git push` whose destination is the base branch, and an agent's `git merge` or `git commit` while the base branch is checked out; it refuses an agent's `gh pr merge` unless `merge.agent_may_merge(cfg)` (Task P3.1) and the command carries `--merge` and `--match-head-commit <40 hex>`. It also refuses every other agent route to a merge or a base-branch update (review 5 F-Pp5-3): `gh api` calls to the REST merge endpoint (`repos/<owner>/<repo>/pulls/<n>/merge`, any method or path spelling) and GraphQL `mergePullRequest` (a `gh api graphql` body holding it), and `git push` to the base branch in any refspec form (`<remote> <base>`, `HEAD:<base>`, `refs/heads/<base>`, `:<base>`, `--all`, `--mirror`). The owner's chat approval itself cannot be checked by a hook; the ledger's `MERGED` line records it.
- **Block 3 (Q-16):** the PreToolUse Edit/Write hook refuses any agent Edit or Write of a path under `paths.decisions` (spec §4 currently: it "records nothing, blocks nothing"); only `python3 -m gates decisions` writes there, and its `decide` and `withdraw` stay refused to agents by the Bash hook.
- **Block 4:** `init` writes `CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH` and `CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS` into the project `.claude/settings.json` `env` block (owner answer; spec edit SE-6). It asks `merge.mode` (Q-M1), and offers to configure host branch protection on the base branch (pull request required, merge-commit method only) through `gh api`, with `doctor` reporting what is and is not set (owner directive; this repository already has protection on).
- **Block 5:** `overview/2` (live programs and specs and plans by state in `INDEX.md`, Task 1c.3) and `gate_drift` (status rows against git, the numeric estimate check) are not in this block; they consume `programs.load_program` and the status rows of Task P2.1.
- **Block 6:** `gate_checkpoint` in full extends Task P1.3's gate; nothing here is re-planned there.

---

## Block P1: checkpoints (branch `block/p1`)

### Task P1.1: schema vocabulary: nested globs, front matter, line formats

**Files:**
- Modify: `gates/lib/schema.py` (additive: every existing schema file loads and validates exactly as before), `gates/gate_schema.py` (dispatch on the new format)
- Test: `tests/test_schema_lib.py`, `tests/test_gate_schema.py`

**Owner answers applied:** I7 (the schema-file vocabulary is the plan's choice), OQ-16, OQ-17.

**Why.** Programs design §7.2 puts handoffs and ledgers at `state/plans/<plan>/`, and status pages, ownership maps, requests and sync logs at `state/programs/<program>/...`. Task 1b.1's `files` items name one directory and one glob over its entries, so none of these kinds can be listed. Spec Appendix A gives the handoff "YAML front matter" with `schema: <kind>/<version>` in it, and the ledger "line formats (`CHECKPOINT`, `Ruling:`, ...)"; Task 1b.1's markdown format holds only `first_line`, `table` and `headings`.

**Interfaces:**
- Consumes: `schema.load_schema/validate/validate_markdown/entries_of/files_of/LayoutError/SchemaError`, `yamlsub.parse/YamlError`, `gate_schema.check`.
- Produces:
  - A `dir` item's `glob` may hold `/`-separated segments (`*/handoff.md`, `*/requests/*.yml`). `load_schema` refuses an empty segment, `.`, `..`, a leading or trailing `/`.
    - Each segment but the last matches entry names of a real directory; a matching entry that is a symlink raises `LayoutError` naming it ("is a symlink; directories must be real directories", as Task 1b.1's parent check); a matching regular file or other non-directory is skipped.
    - The last segment matches as before, and `exclude` compares with the last segment's name only.
    - `entries_of` returns the matches sorted by full repo-relative path. A one-segment glob behaves exactly as before.
  - `format: front-matter`, with `fields` as for `yaml` (the same `fields.schema` rule).
    - `validate_front_matter(schema: Schema, text: object, cfg: dict) -> list`: line 1 is exactly `---`; the front matter runs to the next line that is exactly `---`; it is parsed with `yamlsub.parse` and checked with `validate`. The body after the closing line is free text.
    - Errors: `front matter: first line must be '---'`, `front matter: no closing '---' line`, `front matter: line <n>: <YAML reason>` (the YAML line plus 1, so it is the file's line), `front matter: must be a mapping`, then each `validate` error.
  - Markdown `lines` (optional, beside `first_line` and with or without `table` or `headings`): a list of `{word: str, pattern: str}`.
    - `load_schema` refuses an empty `word`, a `word` holding whitespace, a repeated `word`, and a `pattern` that `re.compile` refuses (`SchemaError` naming the item).
    - `validate_markdown` adds `line <n>: '<word>' line does not match <pattern>` for every line after the first whose first space-delimited token, from column 0 and with one trailing `:` removed, equals `word`, and which `re.fullmatch(pattern, line)` does not match. A line that starts with a space is never keyword-led.
  - `gate_schema` checks a `front-matter` kind with `validate_front_matter`, under the same producer rule and line ids as every other kind.

**Input-domain dimensions:**
- Glob segments: `*/handoff.md`, `*/requests/*.yml`, `a//b`, `./x`, `../x`, `/x`, `x/`, a segment with `[` classes.
- Entry kinds at each level: directory, regular file, symlink to a directory, symlink to a file, FIFO, hidden directory, a name with a space or non-ASCII; nesting 1, 2, 3 levels; a missing middle directory; `exclude` naming a middle segment (no effect) and the last.
- Front matter: no opening line; the opening line not first; no closing line; empty front matter; closing `--- ` with a trailing space; `...` as the closer; CRLF; a BOM; a non-mapping; a YAML error on its line 3 (reported as file line 4); unknown key (OQ-16); the body holding `---`.
- `lines`: a word with and without a trailing colon; the word mid-line; leading spaces; a pattern without anchors (`fullmatch` decides); an invalid regex; a repeated word; `lines` with `table`, with `headings`, alone; a line equal to the word only.
- Every existing schema file and fixture under the old vocabulary: unchanged result.

- [ ] **Step 1: Write the failing tests:**
  ```python
  # test_schema_lib.py
  def test_nested_glob_lists_files_in_subdirectories():
      assert files_of(sch("*/handoff.md"), root, cfg) == ["s/plans/a/handoff.md", "s/plans/b/handoff.md"]
  def test_nested_glob_symlinked_directory_refused():
      with self.assertRaises(LayoutError): files_of(sch("*/handoff.md"), root_with_link, cfg)
  def test_nested_glob_file_in_middle_skipped():
      assert files_of(sch("*/handoff.md"), root_with_plain_file_named_c, cfg) == ["s/plans/a/handoff.md"]
  def test_bad_glob_segments_refused():        # subTests: "a//b", "./x", "../x", "/x", "x/"
      with self.assertRaises(SchemaError): load_schema(write_schema(glob=g))
  def test_front_matter_valid():
      assert validate_front_matter(HSCH, "---\nschema: h/1\nplan: p\n---\nbody\n", cfg) == []
  def test_front_matter_yaml_line_is_file_line():
      assert "front matter: line 4:" in validate_front_matter(HSCH, "---\nschema: h/1\nplan: p\nx: [\n---\n", cfg)[0]
  def test_front_matter_missing_closer():
      assert validate_front_matter(HSCH, "---\nschema: h/1\n", cfg) == ["front matter: no closing '---' line"]
  def test_lines_pattern_checked():
      assert validate_markdown(LSCH, "<!-- schema: l/1 -->\nCHECKPOINT bad\nprose CHECKPOINT x\n") == \
          ["line 2: 'CHECKPOINT' line does not match " + LSCH_PATTERN]
  def test_lines_word_with_colon():            # word "Ruling" matches "Ruling: ..." and "Ruling (x): ..."
      assert len(validate_markdown(RSCH, "<!-- schema: l/1 -->\nRuling (x): y\n")) == 1
  def test_invalid_regex_refused():
      with self.assertRaises(SchemaError): load_schema(write_schema(lines=[{"word": "X", "pattern": "("}]))
  def test_old_schemas_unchanged():            # config.yml and decision.yml load; fixture results equal Task 1b.1's
      assert [load_schema(p).files for p in REPO_SCHEMAS] == EXPECTED_FILES
  # test_gate_schema.py
  def test_front_matter_kind_checked_once_produced():
      assert "FAIL schema.h." in out and code == 1
  ```
- [ ] **Step 2: Run the test command; expect FAIL.**
- [ ] **Step 3: Implement** the three additions in `schema.py` and the `gate_schema` dispatch.
- [ ] **Step 4: Run the test command on both interpreters and `python3 -m gates run_all`; expect PASS.**
- [ ] **Step 5: Commit** `feat(lib): schema vocabulary for nested globs, front matter and line formats`, then checkpoint.

### Task P1.2: handoff and ledger schemas and rules

**Files:**
- Create: `gates/schemas/handoff.yml`, `gates/schemas/ledger.yml`, `gates/lib/checkpoints.py`
- Test: `tests/test_checkpoints_lib.py`

**Owner answers applied:** OQ-16; Q-Pplan-1; Process for this plan, "Checkpoint after every task" (the `CHECKPOINT` line, the resume line, the spec §9 field list); stream rules ("Request:" and `UPDATE` lines).

**Interfaces:**
- Consumes: `schema.load_schema/validate_front_matter/validate_markdown/SCHEMAS_DIR` (Task P1.1), `ids.id_problem`, `dispatch.ROLES` (block 2), `config.load`.
- Produces:
  - `gates/schemas/handoff.yml` (`handoff/1`, `format: front-matter`, `files: [{dir: plan_state, glob: "*/handoff.md"}]`). Fields, the spec §9 list plus what continuation and the upward path need (names are the plan's choice, I7):
    - `schema`; `plan` (`str`); `spec` (`list` of `str`, `min: 1`); `branch` (`str`); `head` (`sha`); `base` (`sha`); `ledger` (`str`); `resume` (`str`); `block` (`str`); `next_task` (`str`);
    - `findings_in_flight` (`list` of `id`, `id_kind: finding`); `open_decisions` (`list` of `id`, `id_kind: decision`); `rulings` (`int`, `min: 0`, rulings used in this block); `grant` (`str`, `nullable`: the PR approval awaited or given, `pr=<n> head=<40 hex>`; under Q-15 (a) approvals are not decision records); `live_subagents` (`list` of `str`);
    - `role` (`str`); `budget` (`map {tokens: int min 1, minutes: int min 1}`);
    - `program`, `stream` (`str`, `required: false`);
    - `questions` (`list`; items `map {qid: str, class: str, question: str, effect: enum [lasting, one-off], options: list min 2 of map {label: str, cost: str}}`). Programs design §4.3: "A blocked agent writes its question (options and cost) into its handoff".
  - `gates/schemas/ledger.yml` (`ledger/1`, markdown, `first_line: "<!-- schema: ledger/1 -->"`, `files: [{dir: plan_state, glob: "*/ledger.md"}]`, `lines`), patterns per Q-Pplan-1 (a):
    - `CHECKPOINT`: `CHECKPOINT <block> <task> head=<7-40 lowercase hex> tests=<n>/<n> gates=<PASS|n/a> next=<task>`, each `<...>` one token with no space;
    - `Ruling`: `Ruling: <what> -- <why> -- <cost if wrong> -- <spec cite>`, exactly three ` -- ` separators, each part non-empty (spec §7.1);
    - `Request`: `Request: <id> from=<stream> to=<stream> files=<paths> need=<text> status=<open|done|disputed>`, optionally `sha=<hex>` (stream rules);
    - `UPDATE`: `UPDATE <block> from=<branch>@<hex> head=<hex> tests=<n>/<n> gates=<PASS|n/a>` (stream rules).
    - `MERGED` (owner Q-15 (a)): `MERGED pr=<n> head=<40 hex> merge=<40 hex> merged_by=<token> at=<YYYY-MM-DDTHH:MM:SSZ> final=<yes|no> approval=<approval>`, where `<approval>` is `host` (host mode: the owner's merge on the host is the approval) or, in controller mode, `chat pr=<n> head=<40 hex> words=<the owner's chat words verbatim, to the end of the line, non-empty>` (the PR number and head sha the owner named, then the words). One line per merged PR of this plan, read back from the host after the merge (`merged_by` is the host account that merged, `mergedBy`; `at` is `mergedAt`), written as the first commit of the next branch; `final=yes` on the plan's last PR only. `approval` is last because `words` runs to the end of the line.
    - The schema patterns accept any `<PREFIX>-<YYYYMMDD>-<xxxx>` id; the configured prefix is checked by `ledger_errors`.
  - `checkpoints.py`:
    - `plan_slug(plan_path: str) -> str`: the basename without its final `.md`; a path not ending `.md` raises `ValueError`.
    - `resume_line(row: dict) -> str`: `Resume strict-delivery plan <plan> at <next_task>; branch <branch>; head <head>; open questions: <ids or none>.`, where the ids are `open_decisions` then each question's `qid`, joined by `, ` (Process for this plan).
    - `parse_handoff(text: str) -> dict` (the front matter; `ValueError` with the `validate_front_matter` errors).
    - `handoff_errors(row: dict, cfg: dict) -> list`: `resume` equals `resume_line(row)`; `plan` lies under `paths.plans` and ends `.md`; `ledger` equals `<paths.plan_state>/<plan_slug(plan)>/ledger.md`; `role` is in `dispatch.ROLES`; `program` and `stream` both present or both absent, each matching `[a-z0-9][a-z0-9-]*`; `qid` values unique and matching `[a-z0-9][a-z0-9-]*`; each question's `class` is in `decision_classes.owner_only` (a handoff question is an owner question, spec §7.1).
    - `checkpoint_lines(text: str) -> list` of dicts (`block`, `task`, `head`, `passed`, `total`, `gates`, `next`), in file order.
    - `merged_lines(text: str) -> list` of dicts (`pr`, `head`, `merge`, `merged_by`, `at`, `final`, `approval` (`host` or `chat`), and for `chat` `approval_pr`, `approval_head`, `words`), in file order; `ledger_errors` adds `line <n>: pr <n> recorded twice` and `line <n>: final=yes after a final line`.
    - `ledger_errors(text: str, cfg: dict) -> list`: the schema errors, plus `line <n>: tests passed > total`, plus `line <n>: <id>` for a `Request:` id failing `id_problem(id, cfg["ids"]["request"])`.
  - No module declares `handoff` or `ledger` yet, so `gate_schema` does not check these files (Appendix A).

**Input-domain dimensions:**
- Every handoff field against wrong types; unknown key; `spec` empty; `grant` null, `pr=3 head=<40 hex>`, a short sha, a decision id (refused); `budget` keys 0, `bool`, missing.
- `resume`: equal; one character off; `open questions: none` with and without ids; ids order.
- `plan` outside `paths.plans`, not `.md`, `..`; `ledger` another plan's.
- `role` each `ROLES` id and an unknown one; `program` without `stream`.
- `questions`: empty; one option; repeated `qid`; `qid` with `/`; `class` outside `owner_only`; `effect` other.
- Ledger lines: each keyword with a conforming line, a trailing word, a missing field, `gates=FAIL`, `tests=5/4`, uppercase hex, a 6-hex sha; `Ruling:` with two and with four separators, an empty part; `Ruling (x):` (refused under Q-Pplan-1 (a)); `Request:` with another prefix; a keyword mid-line; the first line missing.
- `MERGED` lines: conforming host and chat forms; short sha; `final=maybe`; `approval=other`; `chat` with empty `words`; `chat` without `pr=` or `head=`; words holding `=`, quotes, non-ASCII; `by=` instead of `merged_by=`; `at` without `Z`; one PR twice; two `final=yes` lines.
- `plan_slug`: nested path, `x.md.md`, no suffix.

- [ ] **Step 1: Write the failing tests:**
  ```python
  def test_valid_handoff():
      assert validate_front_matter(load_schema(HANDOFF_YML), HANDOFF_TEXT, cfg) == [] and handoff_errors(parse_handoff(HANDOFF_TEXT), cfg) == []
  def test_resume_line_must_match_fields():
      assert "resume: expected '" + resume_line(ROW) + "'" in handoff_errors({**ROW, "resume": "x"}, cfg)
  def test_resume_lists_decisions_then_qids():
      assert resume_line({**ROW, "open_decisions": [D1], "questions": [Q1]}).endswith("open questions: %s, q1." % D1)
  def test_program_and_stream_together():
      assert any(e.startswith("stream:") for e in handoff_errors({**ROW, "program": "20261101-x"}, cfg))
  def test_question_class_must_be_owner_only():
      assert any("class" in e for e in handoff_errors({**ROW, "questions": [{**Q1, "class": "chat"}]}, cfg))
  def test_checkpoint_line_forms():            # subTests per form above
      assert bool(errs(LEDGER_HEAD + line)) == expected_bad
  def test_ruling_needs_four_parts():
      assert errs(LEDGER_HEAD + "Ruling: a -- b -- c\n") and not errs(LEDGER_HEAD + "Ruling: a -- b -- c -- d\n")
  def test_tests_passed_not_above_total():
      assert "line 2: tests passed > total" in ledger_errors(LEDGER_HEAD + "CHECKPOINT 1a 1a.1 head=abcdef1 tests=5/4 gates=PASS next=1a.2\n", cfg)
  def test_merged_line_form_and_single_final():   # owner Q-15 (a)
      assert merged_lines(LEDGER_HEAD + MERGED_FINAL)[0]["final"] == "yes"
      assert any("final=yes after a final line" in e for e in ledger_errors(LEDGER_HEAD + MERGED_FINAL + MERGED_FINAL2, cfg))
  def test_checkpoint_lines_parsed_in_order():
      assert [c["next"] for c in checkpoint_lines(LEDGER)] == ["1a.2", "1a.3"]
  def test_plan_slug():
      assert plan_slug("docs/strict-delivery/plans/x.md") == "x"
  ```
- [ ] **Step 2: Run the test command; expect FAIL.**
- [ ] **Step 3: Implement** the two schemas and `checkpoints.py`.
- [ ] **Step 4: Run the test command on both interpreters and `python3 -m gates run_all`; expect PASS** (no producer yet, so this repository's own handoff and ledger are not checked).
- [ ] **Step 5: Commit** `feat(lib): handoff and ledger schemas and rules`, then checkpoint.

### Task P1.3: basic `gate_checkpoint`; enable `check checkpoint`

**Files:**
- Create: `gates/gate_checkpoint.py`
- Modify: `gates/__main__.py` (`GATES["checkpoint"]`); `gates/producers.py` (add `gates.gate_checkpoint`, timing per Q-Pplan-2); `gates/lib/gitinfo.py` (additive: `current_branch`, `dirty_paths`, `is_ancestor`, `upstream_sha`, `remotes`)
- Records: this repository's `.strict-delivery/state/plans/2026-10-31-strict-delivery-framework/handoff.md` and `ledger.md` are migrated to `handoff/1` and `ledger/1` by the session controller (Step 5).
- Test: `tests/test_gate_checkpoint.py`, `tests/test_gitinfo.py`

**Owner answers applied:** controller rulings (not in `run_all`; producer declaration); owner directive (push at checkpoints; `main` protected); Q-Pplan-1, Q-Pplan-2; DS-3.

**Interfaces:**
- Consumes: `checkpoints.*` (Task P1.2), `schema.*`, `gitinfo.head_sha/commit_exists/toplevel`, `result.*`, `config.load`.
- Produces:
  - `gitinfo.current_branch(root: str) -> Optional[str]`: `git symbolic-ref --quiet --short HEAD`; `None` when HEAD is detached.
  - `gitinfo.dirty_paths(root: str) -> list`: `git status --porcelain=v1 -z --untracked-files=all --ignored=no` paths of the worktree at `root` only, with `GIT_INDEX_FILE` inherited as every gitinfo call. A path in another linked worktree is never listed.
  - `gitinfo.is_ancestor(root: str, a: str, b: str) -> bool`: `git merge-base --is-ancestor`; exit 1 is `False`; any other failure raises `GateError`.
  - `gate_checkpoint`: `PRODUCES = ("handoff", "ledger")`, or `()` while stream B or C is live under Q-Pplan-2 (a) (the gate then validates only the plan it is run for). The deferred declaration is scheduled: from P1.3's checkpoint, every A checkpoint writes the prose ledger line `Open: handoff/ledger producer declaration waits for B and C to merge` (prose, not a keyword line); the block-end step of the first programs sub-block (P1-P4) that ends after the last of B and C has merged into `main` makes the one-line `producers.py` commit with the migration of their workspaces (DS-3), runs `run_all`, and ledgers `Closed: handoff/ledger producer declared at <sha>`. If B or C is still live when P4 ends, the item carries into the program run and the first A block end after their merge makes it. `check(args: list) -> Result` (gate `checkpoint`), `main(argv=None) -> int`. Arguments `--root`, `--plan SLUG` (required; absent or not matching `[a-z0-9][a-z0-9-]*` fails `checkpoint.input`). Lines, each with one `PASS` when clean:
    - `checkpoint.handoff`: `<paths.plan_state>/<plan>/handoff.md` present, a regular file, valid against `handoff/1` and `handoff_errors` (spec §9: "the continuation handoff is present");
    - `checkpoint.ledger`: the ledger the handoff names is present and valid, and holds at least one `CHECKPOINT` line (spec §9: "the ledger carries the `CHECKPOINT` line");
    - `checkpoint.agree`: the last `CHECKPOINT` line's `block` equals the handoff's `block`, its `next` equals `next_task`, and its `head` and the handoff's `head` name the same commit;
    - `checkpoint.head`: the handoff's `head` is an ancestor of (or equal to) `HEAD`, and its `branch` equals `current_branch` (detached HEAD fails, naming it);
    - `checkpoint.clean`: `dirty_paths(root)` is empty; the reason lists every path (spec §9: "the block's own worktree is clean (other streams' worktrees may be dirty)");
    - `checkpoint.pushed` (owner directive: work branches are pushed at checkpoints): the current branch is not `base_branch`; when the repository has a remote, the branch has an upstream (`@{upstream}`) and its local tracking ref names `HEAD`'s commit, read from local refs only (no network); with no remote at all the line passes with the reason `no remote configured`. The checkpoint step is therefore: commit, `git push -u <remote> <branch>` as its own command, then `check checkpoint`.
  - `gitinfo.upstream_sha(root: str) -> Optional[str]` (additive): the commit of `@{upstream}`, `None` when the branch has none; `gitinfo.remotes(root) -> list`.

**Input-domain dimensions:**
- Push state: no remote; a remote and no upstream; upstream behind `HEAD`; upstream equal; upstream ahead (fails: the local branch is not the pushed one); the current branch is `base_branch` (fails).
- argv: `--plan` missing, empty, with `/`, `..`, unknown plan; `--root` not a repo; repeated `--plan`; `--json` position.
- Files: handoff absent, a directory, a symlink, invalid front matter; ledger absent, no `CHECKPOINT` line.
- Agreement: last line older than handoff; `next` differs; `head` short vs full form of the same commit; head not a commit.
- Branch: detached; another branch; a linked worktree on the right branch.
- Cleanliness: clean; a staged change; an unstaged change; an untracked file; an ignored file (passes); a dirty sibling linked worktree (passes); inside a git hook with `GIT_INDEX_FILE` set.
- This repository's migrated files.

- [ ] **Step 1: Write the failing tests:**
  ```python
  def test_valid_checkpoint_passes():
      for c in ["handoff", "ledger", "agree", "head", "clean"]: assert "PASS checkpoint." + c in out
      assert code == 0
  def test_dirty_sibling_worktree_passes():    # git worktree add ../w; touch ../w/x
      assert "PASS checkpoint.clean" in out
  def test_untracked_file_fails_clean():
      assert "FAIL checkpoint.clean: " in out and "x.txt" in out
  def test_next_task_disagreement_fails():
      assert "FAIL checkpoint.agree" in out
  def test_missing_handoff_fails():
      assert "FAIL checkpoint.handoff" in out
  def test_detached_head_fails():
      assert "FAIL checkpoint.head" in out and "detached" in out
  def test_missing_plan_argument_is_input_fail():
      assert out.startswith("FAIL checkpoint.input:")
  def test_short_and_full_head_agree():
      assert "PASS checkpoint.agree" in out
  def test_unpushed_checkpoint_fails():        # fixture bare remote; commit after the push
      assert "FAIL checkpoint.pushed" in out and "PASS checkpoint.pushed" in pushed_out
  def test_no_remote_passes_pushed_with_reason():
      assert "PASS checkpoint.pushed" in out
  def test_checkpoint_on_base_branch_fails():
      assert "FAIL checkpoint.pushed" in out
  # test_gitinfo.py
  def test_dirty_paths_ignores_other_worktrees():
      assert dirty_paths(main_wt) == [] and dirty_paths(other_wt) == ["x"]
  def test_is_ancestor():
      assert is_ancestor(root, first, second) and not is_ancestor(root, second, first)
  ```
- [ ] **Step 2: Run the test command; expect FAIL.**
- [ ] **Step 3: Implement** `gate_checkpoint.py` and the three gitinfo functions.
- [ ] **Step 4: Run the test command on both interpreters and `python3 -m gates run_all`; expect PASS.**
- [ ] **Step 5: Migrate this repository's plan workspace (session controller).** The implementer stops before the commit with status DONE. The session controller rewrites `handoff.md` to `handoff/1` (every field; `role: controller`; the unknown key `in_progress_outside_plan` moves into the body) and gives `ledger.md` the first line `<!-- schema: ledger/1 -->`; keyword lines that do not conform are rewritten per Q-Pplan-1, keeping their text. Under Q-Pplan-2 (a), when stream B's or C's workspace is on this branch (their last block merged, DS-3), the controller migrates it the same way. It then runs the suite on both interpreters, `run_all`, and, after the commit, `check checkpoint --plan 2026-10-31-strict-delivery-framework`; expects PASS.
- [ ] **Step 6: Commit** `feat(gates): basic gate_checkpoint; handoff and ledger schemas checked`, then checkpoint with `gates=PASS`. **Block P1 end:** as block 1d.

---

## Block P2: program records and `gate_streams` (branch `block/p2`)

### Task P2.1: program names, the four program schemas, program rules

**Files:**
- Create: `gates/lib/programs.py`, `gates/schemas/streams.yml`, `gates/schemas/request.yml`, `gates/schemas/status.yml`, `gates/schemas/sync-log.yml`
- Modify: `gates/lib/gitinfo.py` (additive: `local_branches`)
- Test: `tests/test_programs_lib.py`

**Owner answers applied:** OQ-16, I7; controller rulings on ownership, live programs and status numbers; Q-Pplan-4.

**Interfaces:**
- Consumes: `schema.*` (Task P1.1), `ids.id_problem`, `gitinfo.show/ls_tree/merge_base/commit_exists/is_ancestor`, `migrations.migrate`, `yamlsub.parse/load`, `config.load`, `store.store_errors`, `store.Record`.
- Produces:
  - `gitinfo.local_branches(root: str) -> list`: every `refs/heads/` short name, sorted (`git for-each-ref --format=%(refname:short) refs/heads`).
  - Names (spec §11, programs design §18):
    - `NAME_RE = "[a-z0-9][a-z0-9-]*"`.
    - `program_problem(name: object) -> str`: `<YYYYMMDD>-<slug>` with a valid calendar date and the whole name matching `NAME_RE`; `""` when valid. Programs design §7.3: "Program folders are named `<YYYYMMDD>-<slug>` (no person's name)".
    - `stream_problem(id)`: `NAME_RE`, and not `integration`. `group_problem(id)`: `NAME_RE`, and not `main`.
    - `parse_branch(name: str) -> Optional[tuple]`: `<p>/integration` gives `("integration", p, None, None)`; under Q-Pplan-12 (a), `<p>/records` gives `("records", p, None, None)` and the stream id `records` is refused too; `<p>/<s>/main` gives `("stream", p, s, None)`; `<p>/<s>/<g>` gives `("group", p, s, g)`; a name whose first component passes `program_problem` but whose shape or ids are wrong raises `ValueError` naming the rule; any other name gives `None` (not a program branch).
    - `branch_of(p, s=None, g=None) -> str` and `worktree_of(worktrees, p, s, g=None) -> str` (`<worktrees>/<p>/<s>/main` or `<worktrees>/<p>/<s>/<g>`; spec §11).
  - `gates/schemas/streams.yml` (`streams/1`, `files: [{dir: programs, glob: "*/streams.yml"}]`): `schema`, `program` (`str`), `plan` (`str`, the program plan), `specs` (`list` of `str`), `worktrees` (`str`), `streams` (`list`, `min: 1`; items `map {id: str, purpose: str, plan: str, owns: list min 1 of str, estimate: int min 0, depends_on: list of str, merge_order: int min 1, stacked_on: str required false}`), `shared` (`list`; items `map {path: str, rule: enum [append-rows, own-row]}`). Programs design §5 lists what the plan defines per stream; §12 gives the two shared rules.
  - `gates/schemas/request.yml` (`request/1`, `files: [{dir: programs, glob: "*/requests/*.yml"}]`): programs design §6's fields: `id` (`id`, `id_kind: request`), `from_stream`, `to_stream` (`str`), `files` (`list` min 1 of `str`), `interface` (`cite`), `need` (`str`), `status` (`enum [open, accepted, done, disputed, withdrawn]`), `raised_at` (`map {sha: sha, by: str}`), `resolution` (`map {commits: list min 1 of sha, at: sha, by: str}`; `required_when: [{status: [done]}]`), `decision` (`id`, `id_kind: decision`, `required: false`).
  - `gates/schemas/status.yml` (`status/1`, markdown, `first_line: "<!-- schema: status/1 -->"`, `table` = the eleven headers of spec §11, exactly `stream | block | branch | worktree | next task | estimate | used | status | blockers | pending decisions | delivers`).
  - `gates/schemas/sync-log.yml` (`sync-log/1`, markdown, `first_line: "<!-- schema: sync-log/1 -->"`, `lines`: `SYNC integration=<hex> main=<hex> merged-main=<yes|no> updated=<stream ids|none> combined=<stream ids|none> tests=<PASS|FAIL> questions=<ids|none>`). Under Q-M4 (a) a sync merges main into the integration branch, updates each stream branch behind main (Q-Pplan-5), merges the stream heads named in `combined` into integration and runs `run_all` and the suite there (combined testing), and collects the question batch. The sync's command sequence is the builder's (programs design §17); the line records its outcome. Why here although the outline's P2 names only the streams, request and status schemas: `sync-log.md` is one of the four files of the program folder (programs design §7.2), `program create` writes it with the others, and the sync duty of P4.3's prompt blocks needs a checked place to record each sync (programs design §10: "update status rows and the sync log"); without a schema and a producer, `gate_schema` would leave it unchecked (Appendix A).
  - `@dataclass(frozen=True) Program(name: str, streams: dict, status_text: str, requests: list, sync_log: str, ref: Optional[str])`; `requests` holds `store.Record`s.
  - `load_program(root: str, cfg: dict, name: str, ref: Optional[str]) -> Program`: reads `<paths.programs>/<name>/` from the working tree (`ref` `None`) or from a commit with `gitinfo.show` and `ls_tree`. A missing `streams.yml` or a file that does not parse raises `GateError` naming it. Rows pass through `migrations.migrate` before use.
  - `streams_errors(row: dict, name: str, cfg: dict) -> list`:
    - `program` equals the folder name and passes `program_problem`; stream ids pass `stream_problem` and are unique; `depends_on` and `stacked_on` name other streams; `stacked_on` has no cycle; `merge_order` values are distinct; each stream `plan` lies under `paths.plans`.
    - `worktrees` is a relative, normalised path that, resolved against the main worktree (the parent of `git rev-parse --path-format=absolute --git-common-dir`, the same base as Task P2.2), lies outside the main worktree's top level; absolute paths are refused (they carry a home directory). It is never resolved against `--root`, which under Q-Pplan-11 (a) is often the integration worktree. Design §4.1 and the stream rules keep worktrees outside the checkout. `worktrees_dir(root, row) -> str` returns the resolved absolute directory, the one value P2.2 and `status_errors` use.
    - Owned entries are exact repo-relative paths or directory prefixes ending `/` (the convention of the stream rules' ownership table). Two streams overlap when an entry equals another or one is a `/` prefix of the other: `owns: <a> (stream <s>) overlaps <b> (stream <t>)`. An owned entry under the program folder, `paths.decisions` or `paths.findings`, or equal to a `shared` path, is refused (controller ruling).
  - `owner_of(streams: dict, plan_state: str, path: str) -> Optional[str]`: the stream whose entry covers `path`, including each stream's implicit `<plan_state>/<plan slug>/` (controller ruling); `None` when no stream owns it. `shared_rule(streams, path) -> Optional[str]`.
  - `status_rows(text: str) -> list` of dicts keyed by the eleven headers (cells stripped, `\|` unescaped); a row with another cell count is an error row.
  - `status_errors(rows: list, streams: dict) -> list`: one row per stream and no other; `status` in `ready | running | blocked | checkpoint | merged | closed` (spec §11; `merged` means the stream's PR has merged into `base_branch`, Q-M4 (a)); `branch` equals `branch_of(p, s)`; `worktree` equals `worktree_of(...)`; `estimate` and `used` per the controller ruling on status numbers: non-negative decimal integers, in the unit of the stream's `estimate` in `streams.yml`; `blockers` is `none` or comma-separated request ids that name records of this program; `pending decisions` is `none` or comma-separated decision ids.
  - `request_errors(program: Program, root: str, cfg: dict) -> list` of `(suffix, reason)`: `store_errors(program.requests, cfg["ids"]["request"])` (file name equals id, ids well formed and unique); `to.<id>`: `to_stream` owns every listed file (`owner_of`); `from.<id>`: `from_stream` is a stream and differs from `to_stream`; `done.<id>`: each `resolution.commits` sha is a commit reachable from `branch_of(p, to_stream)` (or from the tip of `base_branch` once that stream's PR has merged; never from `<p>/integration`, which only holds combined-testing merges, Q-M4 (a)) that touches a listed file (programs design §6: "`done` cites commits on B's branch that touch those files"); `decision.<id>`: a present `decision` names an answered decision of class `request-dispute`.
  - `request_base_errors(now: Program, base: Program) -> list` (Q-Pplan-4 (a)): `deleted.<id>` (a request at the base is gone); `transition.<id>` (a status change outside `REQUEST_TRANSITIONS`); `dispute.<id>` (leaving `disputed` without `decision`); `immutable.<id>` (a `done` or `withdrawn` request changed).
  - `REQUEST_TRANSITIONS = {"open": ("accepted", "disputed", "withdrawn"), "accepted": ("done", "withdrawn"), "disputed": ("accepted", "withdrawn"), "done": (), "withdrawn": ()}` under Q-Pplan-4 (a).
  - `live_programs(root: str, cfg: dict) -> list` per the controller ruling on live programs: every program name `p` for which a local branch `<p>/integration` exists and its tip holds `<paths.programs>/<p>/streams.yml`; sorted.

**Input-domain dimensions:**
- Names: `20261101-x`, `20261301-x` (bad date), `20261101-` , `20261101-X`, `20261101-a/b`, `x`; stream `integration`, group `main`, `-a`, `a_b`.
- Branches: `p/integration`, `p/records` (Q-Pplan-12 (a)), stream id `records`, `p/s/main`, `p/s/g`, `p/integration/x`, `p/s`, `p/integration/main`, `p/s/g/h`, `main`, `block/p1`, `feature/x` (first component not a program name: `None`).
- `streams.yml`: each field wrong type; unknown key; folder name differs from `program`; duplicate stream; `stacked_on` cycle of 2; `depends_on` unknown; duplicate `merge_order`; `worktrees` absolute, `../w`, `w` (inside the repo), `../../w`; `worktrees: ../w` read with `--root` the integration worktree `<W>/<p>/integration` (resolves to the main worktree's sibling `w`, never `<W>/<p>/w`; review F-Pp2-1); owned overlaps (equal, prefix, `a/` vs `ab/`, `a` vs `a/`); owned under the program folder, under `paths.decisions`; owned equal to a shared path.
- `owner_of`: exact; under a prefix; the implicit plan workspace; another stream's workspace; unowned.
- Status page: header off by one space; a missing row; an extra row; a row with 10 cells; each status value and `done`; branch and worktree off; `estimate` `-1`, `1.5`, `03`; `blockers` naming another program's request; `\|` in `delivers`.
- Requests: file name differs from id; duplicate id across files; a decision id in the requests folder; `to_stream` not owning one file; `done` with no resolution, a sha not a commit, a commit on another stream's branch, a commit reachable only from `<p>/integration` (refused), a commit on `base_branch` after the owner stream's PR merged (accepted), a commit touching no listed file; every `(from, to)` status pair (25) against `REQUEST_TRANSITIONS`; deleted; `decision` open, withdrawn, another class.
- `live_programs`: no branches; an integration branch without the folder; two programs; a stream branch only.
- `load_program` from the working tree and from a ref; a missing folder; a YAML error.

- [ ] **Step 1: Write the failing tests:**
  ```python
  def test_program_names():
      assert program_problem("20261101-x") == "" and program_problem("20261301-x") and program_problem("x")
  def test_parse_branch():
      assert parse_branch("20261101-x/s/main") == ("stream", "20261101-x", "s", None) and parse_branch("block/p1") is None
      with self.assertRaises(ValueError): parse_branch("20261101-x/integration/main")
  def test_owned_overlap_refused():
      assert any("overlaps" in e for e in streams_errors(with_owns(S, {"a": ["src/"], "b": ["src/x.py"]}), NAME, cfg))
  def test_absolute_worktrees_refused():
      assert any(e.startswith("worktrees:") for e in streams_errors({**S, "worktrees": "/w"}, NAME, cfg))
  def test_plan_workspace_owned_implicitly():
      assert owner_of(S, PLAN_STATE, PLAN_STATE + "/a-plan/ledger.md") == "a"
  def test_status_rows_one_per_stream():
      assert any("missing row" in e for e in status_errors(status_rows(PAGE_WITHOUT_B), S))
  def test_status_header_exact():              # schema check of the table header
      assert validate_markdown(load_schema(STATUS_YML), PAGE.replace("next task", "next  task"))
  def test_request_to_stream_must_own_files():
      assert ("to." + RID, ANY) in request_errors(prog_with(req_files=["b-owned.py", "a-owned.py"]), root, cfg)
  def test_done_needs_commit_on_owner_branch():
      assert ("done." + RID, ANY) in request_errors(prog_with(done_sha=OTHER_STREAM_SHA), root, cfg)
  def test_request_transitions():              # 25 subTests
      assert (("transition." + RID, ANY) in request_base_errors(now, base)) == (b not in REQUEST_TRANSITIONS[a] and a != b)
  def test_live_programs_from_integration_branches():
      assert live_programs(root, cfg) == ["20261101-x"]
  ```
- [ ] **Step 2: Run the test command; expect FAIL.**
- [ ] **Step 3: Implement** `programs.py`, the four schemas and `local_branches`.
- [ ] **Step 4: Run the test command on both interpreters and `python3 -m gates run_all`; expect PASS** (no producer yet).
- [ ] **Step 5: Commit** `feat(lib): program names, streams, request, status and sync-log schemas and rules`, then checkpoint.

### Task P2.2: the `program` tool

**Files:**
- Create: `gates/tools/program_cli.py`; `gates/lib/breakdown.py` and `gates/schemas/breakdown.yml` (the plan checks of owner answer Q-PL-1 (a): no task owned `gate_plan` or plan checks, so they land here, in the task where a program starts)
- Modify: `gates/__main__.py` (`COMMANDS["program"]`), `gates/producers.py` (add `gates.tools.program_cli`)
- Test: `tests/test_program_cli.py`, `tests/test_breakdown.py`

**Owner answers applied:** controller rulings (producer; integration-branch writer; `program-create` decision); Q-Pplan-4, Q-Pplan-11; Q-PL-1 (a) (plan in full before code; the stream breakdown is the last planning step; main spec §8 and Appendix A, programs design §5 step 1).

**Interfaces:**
- Consumes: `programs.*` (Task P2.1), `dispatch.limits_of` (Task 2c.3), `ids.mint/utc_today`, `decisions.is_resolved`, `store.Store("decision")`, `gitinfo.current_branch/head_sha/local_branches/show`, `yamlsub.emit`, `config.load`, and the ids of every register (decisions, findings, claims, every program's requests).
- Produces: `PRODUCES = ("streams", "status", "sync-log", "request", "breakdown")`; `main(argv: list) -> int` for `python3 -m gates program <sub>`. Every subcommand refuses (exit 1, nothing written) unless `current_branch` is `<program>/integration`, validates every file it writes before writing it, and writes with `yamlsub.emit` or the canonical table form.
  - `gates/schemas/breakdown.yml` (`breakdown/1`, YAML, `files: "<paths.plan_state>/*/breakdown.yml"`): `plan` (`str`, the plan slug, equal to the folder name); `max_concurrent`, `max_depth` (`int`, `min: 1`: the limits the breakdown assumes); `streams` (`list`, `min: 1`) of `map {id: str [a-z0-9][a-z0-9-]*, paths: list of str (min 1; a trailing `/` owns every path under it), tasks: list of str (min 1, task ids), unblock: str ("at program start" or the condition, naming tasks or streams)}`; `edges` (`list`, may be empty) of `map {from: str, to: str}` (`to` waits for `from`); `groups` (`list`, `min: 1`) of `map {id: str, tasks: list of str (min 1)}`. Unknown keys refused.
  - `breakdown.breakdown_errors(row: dict) -> list` of `(suffix, reason)`: stream ids unique; a task id in more than one stream; owned paths that overlap between streams (equal, or one a `/`-prefix of the other); an edge naming an unknown task, an edge from a task to itself, a cycle (the reason names one cycle); a group naming an unknown task, a task in two groups, a group holding two tasks joined by a path of edges, a group larger than `max_concurrent`.
  - `breakdown.plan_errors(plan_text: str, row: dict) -> list` of `(suffix, reason)` ("outline-only"; fail closed, review F-QPL-1). Line-based, fences not special:
    - A task heading is a line `### Task <id>:` or `#### Task <id>:`, the colon right after the id (the same rule as Task 6K.1's `plan_tasks`). A heading with anything between the id and the colon (`### Task 3d.2 (only if ...):`) is not a task heading. A conditional task writes its condition after the colon, and the breakdown lists it like any other task, with the condition in its stream's `unblock`.
    - A block heading is `## Block <id>` or `### Block <id>` followed by `:` or ` (`, or `## Stream <name>, sub-block <id>` followed by ` (` or the end of the line; `<id>` is `[0-9A-Za-z]+`. `### Block <id>` counts only inside a `## Stream` section (owner-answer and divergence headings elsewhere are not blocks).
    - `outline.structure`: the plan has no block heading at all (a plan without the expected structure fails).
    - `outline.block.<id>`: a block heading whose section (up to the next heading of the same or a higher level) holds no task heading `Task <id>.<n>:`, unless it is an umbrella: a later block heading exists whose id starts with `<id>` and is longer (`## Block 2 (sub-blocks ...)` then `## Block 2a`), and every such sub-block passes. Another `## ` heading holding `(sub-blocks <id>, <id>, ...)` (`## Programs block (sub-blocks P1, P2, P3, P4)`) is an umbrella over exactly the listed ids, each of which must be a passing block heading. Checked on this plan at the commit that states the rule: 37 block headings, all passing, and all six `## Later blocks` pointers resolving; a prose-only `## Block 7:` and a bare bullet both fail.
    - `outline.later.<n>`: a bullet under a heading that starts `## Later blocks` whose text does not read `Planned in full in section "<X>"`, or whose `<X>` is not the text of a block heading of the plan, or names one that fails `outline.block`.
    - `outline.task.<id>`: a task of the breakdown with no task heading in the plan; `outline.unplanned.<id>`: a task heading of the plan in no stream of the breakdown.
  - `create <program> --streams FILE --decision DEC --plan SLUG [--root R]`: first refuses (exit 1, nothing written) when `<paths.plans>/<SLUG>.md` or `<paths.plan_state>/<SLUG>/breakdown.yml` is missing, when the breakdown fails `breakdown/1`, `breakdown_errors` or `plan_errors`, each reason printed (owner answer Q-PL-1 (a): a program does not start on an outline-only plan or without a valid breakdown); when the breakdown's `max_concurrent` or `max_depth` exceeds the effective limit, `dispatch.limits_of(cfg, os.environ)` (Task 2c.3: the lower of config `limits` (Task 2c.2) and the measured Claude Code limits, failing closed when the environment does not say; when config leaves a limit unset, the Claude Code value alone counts) (review F-QPL-2); and unless the breakdown agrees with the streams file: the same set of stream ids, each stream's `paths` equal as a set to its `owns`, the breakdown's `plan` equal to `--plan`, and `--plan` equal to the streams file's `plan` (review F-QPL-3; one ownership map, the one `gate_streams` enforces); then refuses an invalid name, a name whose folder exists in the working tree, at `HEAD`, or at the tip of `base_branch` (programs design §7.3: "a name already on main or on the branch is refused"), an id that is not an answered `program-create` decision, and a streams file that fails `streams/1` or `streams_errors`. It writes `streams.yml`, `status.md` (one row per stream: `block` and `next task` `none`, `estimate` from `streams.yml`, `used` `0`, `status` `ready`, `blockers` and `pending decisions` `none`, `delivers` the stream's `purpose`) and `sync-log.md` (its first line).
    - Where it runs (owner answer Q-Pplan-11 (a)): the session first creates the branch and its worktree with one git command of its own, `git worktree add -b <program>/integration <worktrees>/<program>/integration <base_branch>`, and runs `create` (and every later `program`, `questions` and `decisions` write of the program) with `--root` that worktree. `create` then also refuses when the top level of `--root` is not `<worktrees>/<program>/integration`, with `<worktrees>` from the streams file resolved against the main worktree (the parent of `git rev-parse --path-format=absolute --git-common-dir`). The main checkout is never switched.
  - After every successful write the tool prints `push <program>/integration`; the program controller pushes the integration branch as its own command (owner directive; CI reads program files from it).
  - `status <program> <stream> [--block B] [--next-task T] [--used N] [--status S] [--blockers IDS] [--pending IDS] [--delivers TEXT]`: rewrites that one row; every other row is byte-identical.
  - `request new <program> --from S --to T --file F (at least once) --interface CITE --need TEXT --by S`: mints `R-<YYYYMMDD>-<xxxx>` with `ids.mint(cfg["ids"]["request"], <every id>, utc_today(), random.SystemRandom())`, writes `requests/<id>.yml` with `status: open` and `raised_at {sha: HEAD, by}`, prints the id last (spec §7.2: "Within one program only the program controller mints ids").
  - `request set <program> <id> --status S [--commit SHA]... [--decision DEC] --by S`: applies one transition of `REQUEST_TRANSITIONS`; `done` needs `--commit` (writes `resolution {commits, at: HEAD, by}`); leaving `disputed` needs `--decision`.
  - `sync-log <program> --main SHA --merged-main yes|no [--updated S]... [--combined S]... --tests PASS|FAIL [--question DEC]...`: appends one `SYNC` line with `integration=HEAD`.

**Input-domain dimensions:**
- Branch: `<program>/integration`; another program's integration; a stream branch; `main`; detached.
- `--root` (Q-Pplan-11 (a)): the integration worktree at `<worktrees>/<program>/integration`; the main checkout with `<program>/integration` checked out (refused); a worktree on the right branch at another path (refused); `<worktrees>` given as `../w` from the main worktree.
- `create`: each refusal above; streams file missing, a YAML error, a directory; `--decision` open, withdrawn, another class, unknown; folder present only on `main`.
- `--plan` and the breakdown (Q-PL-1 (a)): plan file missing; breakdown missing, a YAML error, a directory, a wrong `plan`; a `## Later blocks` bullet without `Planned in full in section` (fails), with it naming an existing block section with tasks (passes), naming no heading (fails), and naming a section without tasks (fails); a plan with no block heading (fails `outline.structure`); a `## Block 7:` section with prose only (fails); an umbrella with passing sub-blocks (passes) and with none (fails); `### Block <id>` outside a `## Stream` section (ignored); a breakdown task with no heading; a plan task heading in no stream; `### Task` and `#### Task` headings; a heading `### Task 3d.2 (only if ...):` (not a task heading: a breakdown naming `3d.2` fails `outline.task.3d.2`, as Task 6K.1 does not count it either), and `### Task 3d.2: ... (only if ...)` (a task heading).
- Limits (F-QPL-2): breakdown `max_concurrent` equal to and one above the effective limit; config `limits` unset (Claude Code value alone), set lower than Claude Code, set higher; the depth variable unset (fails closed as `limits_of` does).
- Agreement with the streams file (F-QPL-3): equal; a stream only in one file; equal ids with a path only in one; paths equal in another order (passes); `--plan` differing from the streams file's `plan`; the breakdown's `plan` differing from `--plan`.
- `breakdown_errors`: duplicate stream ids; a task in two streams; overlapping paths (`a/` and `a/b.py`, equal paths, `a` and `ab`, which do not overlap); an edge to an unknown task, a self edge, a two-task and a three-task cycle; an empty `edges`; a group with an unknown task, a task in two groups, two dependent tasks (directly and through a third), a group of `max_concurrent` tasks (passes) and of `max_concurrent + 1` (fails); `max_concurrent` and `max_depth` `0`, `True`, `"2"`.
- `status`: unknown stream; each field value against `status_errors`; text holding `|`, a newline, non-ASCII.
- `request new`: each flag missing, repeated, empty; `--to` not owning a file; `--from` equal to `--to`; a mint collision forced by a seeded generator; the requests folder missing.
- `request set`: every transition pair; `done` without `--commit`; a commit not on the owner's branch; `--decision` absent when leaving `disputed`.
- `sync-log`: a sha not a commit; repeated `--stream`.
- Write failures after validation (read-only folder).

- [ ] **Step 1: Write the failing tests** (`code, out, err = cli(root, ...)`; repositories from `helpers.make_repo` with a branch `20261101-x/integration` checked out):
  ```python
  def test_create_writes_three_files_that_validate():
      assert code == 0 and gate_schema.check(["--root", root]).ok() and status_rows(read(STATUS))[0]["status"] == "ready"
  def test_create_refuses_outline_only_plan():   # Q-PL-1 (a)
      assert code == 1 and "Planned in full" in err and not exists(FOLDER)
  def test_create_refuses_missing_or_invalid_breakdown():   # Q-PL-1 (a); subTest per case
      assert code == 1 and "breakdown" in err and not exists(FOLDER)
  def test_create_refuses_breakdown_over_effective_limits():   # F-QPL-2; subTest per config and environment
      assert code == 1 and "max_concurrent" in err and not exists(FOLDER)
  def test_create_refuses_breakdown_disagreeing_with_streams():   # F-QPL-3; subTest per case
      assert code == 1 and "streams" in err and not exists(FOLDER)
  def test_plan_errors_fail_closed():           # F-QPL-1; subTest per case: no block heading, prose-only block, dangling pointer, pointer to a taskless section
      assert plan_errors(case_text, row) != []
  def test_conditional_heading_form():          # F-QPL-4
      assert ("outline.task.3d.2" in suffixes(plan_errors("### Task 3d.2 (only if x): y", row_3d2))) and not plan_errors("### Task 3d.2: y (only if x)", row_3d2)
  # test_breakdown.py
  def test_cycle_found_and_named():
      assert any(s == "edges" and "t1 -> t2 -> t1" in r for s, r in breakdown_errors(row_with_cycle))
  def test_group_over_concurrency_or_with_dependent_tasks_fails():   # subTest per case
      assert breakdown_errors(bad_group_row) != []
  def test_overlapping_paths_fail_and_prefix_without_slash_passes():
      assert breakdown_errors(row_paths("a/", "a/b.py")) and not breakdown_errors(row_paths("a", "ab"))
  def test_plan_errors_this_repository_plan_passes_its_headings():   # every Later blocks bullet points to a detailed section
      assert [e for e in plan_errors(read(PLAN), row_of_every_task(read(PLAN))) if e[0].startswith("outline")] == []
  def test_create_needs_answered_program_create():
      assert code == 1 and "program-create" in err and not exists(FOLDER)
  def test_create_refuses_name_on_main():
      assert code == 1 and not exists(FOLDER)
  def test_refused_off_integration_branch():   # subTest per branch kind
      assert code == 1 and "<program>/integration".replace("<program>", NAME) in err
  def test_status_rewrites_one_row():
      assert lines(read(STATUS))[3:] == before_other_rows and status_rows(read(STATUS))[0]["used"] == "3"
  def test_request_new_mints_and_prints_id():
      assert id_problem(out.splitlines()[-1], "R") == "" and rec(rid)["status"] == "open"
  def test_request_done_needs_commit():
      assert code == 1 and rec(rid)["status"] == "accepted"
  def test_leaving_dispute_needs_decision():
      assert code == 1 and rec(rid)["status"] == "disputed"
  def test_sync_line_appended():
      assert read(SYNC).splitlines()[-1].startswith("SYNC integration=")
  ```
- [ ] **Step 2: Run the test command; expect FAIL.**
- [ ] **Step 3: Implement** `program_cli.py`, `breakdown.py` and `schemas/breakdown.yml`.
- [ ] **Step 4: Run the test command on both interpreters and `python3 -m gates run_all`; expect PASS** (this repository has no program folder, so the four kinds have no files).
- [ ] **Step 5: Commit** `feat(tools): program create, status, request and sync-log; breakdown/1 and the plan checks at program start`, then checkpoint.

### Task P2.3: `gate_streams`; `run_all` runs it while a program is live

**Files:**
- Create: `gates/gate_streams.py`
- Modify: `gates/__main__.py` (`GATES["streams"]`); `gates/run_all.py` (`LIVE_PROGRAM_GATES`); `gates/lib/gitinfo.py` (additive: `changed_paths`, `rev_list`, `parents`, `commit_paths`, `merge_head`)
- Test: `tests/test_gate_streams.py`, `tests/test_run_all.py`, `tests/test_gitinfo.py`

**Owner answers applied:** controller rulings (live in `run_all`; ownership of program folder and records; main-merge exemption; live programs); owner directive and Q-M4 (a); Q-Pplan-4, Q-Pplan-5, Q-Pplan-12.

**Interfaces:**
- Consumes: `programs.*`, `gitinfo.current_branch/merge_base/is_ancestor/show/local_branches`, `run_all.PROFILE_GATES/check`, `result.*`, `config.load`.
- Produces:
  - gitinfo, every call with `-C root`, `GIT_INDEX_FILE` inherited, `--no-renames` so both sides of a rename count:
    - `changed_paths(root: str, a: str, b: Optional[str]) -> list`: `git diff --name-only -z --no-renames a [b]`; `b` `None` compares with the working tree.
    - `rev_list(root, a, b) -> list` (`a..b`, oldest first); `parents(root, sha) -> list`; `commit_paths(root, sha) -> list` (the diff against its first parent; a root commit lists every path); `merge_head(root) -> Optional[str]` (`MERGE_HEAD` when a merge is in progress).
  - `gate_streams`: `PRODUCES = ()`, `check(args)` (gate `streams`), `main(argv=None) -> int`. Arguments: `--root`; `--branch NAME` (default `current_branch`; detached with no `--branch` fails `streams.input`, so CI passes the branch); `--base REF` (accepted and ignored for `run_all` uniformity: the base is derived below).
  - Which program and stream: `parse_branch(branch)`. A program branch with a bad shape fails `streams.branch`. On a branch that is not a program branch, the gate checks each live program's files only, and prints `PASS streams.none` when no program is live (gate contract: never an empty run).
  - Program files are read from `<program>/integration` (programs design §6: a stream "reads requests from `<program>/integration`"); an absent integration branch fails `streams.input`.
  - The base (Q-M4 (a): stream branches start from `main` and merge into it by PR): `base_branch`, or `branch_of(p, stacked_on)` when the stream is stacked (programs design §12 names the integration branch here; spec edit SE-12). The commits judged are `rev_list(merge_base(base, HEAD), HEAD)`, each by its `commit_paths`, plus the tree being committed (`changed_paths(root, "HEAD", None)`), so each commit is checked on its own (programs design §12: "in CI per commit `base..HEAD`").
  - Lines:
    - `streams.map.<program>`: `streams_errors`;
    - `streams.status.<program>`: `status_errors`;
    - `streams.request.<suffix>`: `request_errors`, and `request_base_errors` against the program at the merge base of the integration branch with `HEAD`;
    - `streams.owned.<path>` on a stream or group branch: a changed path owned by another stream, or by nobody and not shared, fails; the reason names the owner, or says "no stream owns it; the program controller assigns it (class `stream-ownership`)" (programs design §12). A change under the program folder or a global record directory fails (controller ruling). A merge commit whose second parent is reachable from the tip of `base_branch` (an update from main, per Q-Pplan-5) is not judged: it brings main's own changes.
    - `streams.owned.<path>` on `<program>/integration`: a non-merge commit, and the tree being committed when `merge_head` is `None`, may change only the program folder and the global record directories (programs design §5: "Only the program controller commits on the integration branch, apart from these merges"; Q-M4 (a): integration holds only program records). A merge whose second parent is reachable from the tip of `base_branch` is exempt (controller ruling). Any other merge (combined testing), and the tree being committed while a merge is in progress, may change only paths the merged stream owns, identified as the stream whose branch the second parent is reachable from; none found fails.
    - `streams.owned.<path>` on `<program>/records` (Q-Pplan-12 (a)), judged against the merge base with `base_branch`: only the global record directories may change.
    - `streams.integration.<sha>`: on a stream, group or records branch, a judged merge commit whose second parent is reachable from `<program>/integration` and not from the tip of `base_branch` fails: integration content (other streams' code from combined testing) never flows into a branch that opens a PR to `main` (Q-M4 (a): integration is never a merge stop on the way to `main`).
    - `streams.shared.<path>`: a shared file changed under `append-rows` must equal its base text followed by whole new table rows (`|`-led lines) only; under `own-row` only rows whose first cell is the committing stream may differ, be added or be removed.
  - CI: on a pull request HEAD is detached, so the workflow step that creates the local integration branches and runs `check streams --branch <head ref>` lands in Task P3.1 (review 3 F-Pp3-4).
  - `run_all`: `LIVE_PROGRAM_GATES: tuple = ("streams",)`, appended to the profile's list when `programs.live_programs(root, cfg)` is non-empty or the current branch is a program branch (controller ruling). `PROFILE_GATES` is unchanged.

**Input-domain dimensions:**
- argv: `--branch` absent with HEAD detached; a non-program branch; a malformed program branch; `--base` given.
- Branch kinds: integration, stream, group, stacked stream; no live program; two live programs.
- Changed paths: owned by the committing stream; owned by another stream; unowned; the own plan workspace; another stream's plan workspace; under the program folder; under `paths.decisions`; a rename across owners (both sides judged); a deletion; an untracked file (not judged: not committed).
- Commit shapes: one bad commit followed by a revert (still fails: per commit); a merge of main into a stream branch (exempt); a merge of the integration branch into a stream branch (fails `streams.integration`); a group merge into the stream branch; on integration, a merge of main, a merge of a stream head (combined testing), a merge of an unknown branch, a conflict resolution in progress; on `<p>/records`, a record-only commit and a commit touching code.
- Base: a stream branch created from `main` (judged against `main`); a stacked stream (judged against its `stacked_on` branch); `main` advanced after the stream started.
- Shared files: `append-rows` with a row added at the end, a row edited, a row added in the middle, a non-row line added; `own-row` with own row edited, another stream's row edited, own row added, another's row removed.
- Requests and status: each failing input of Task P2.1, read from the integration branch.
- `run_all`: no program (no `streams` line); a live program on each profile (light included).
- Inside a git pre-commit hook with `GIT_INDEX_FILE` set.

- [ ] **Step 1: Write the failing tests** (a fixture program created with `program create` on `20261101-x/integration`, streams `a` and `b`, worktrees added with `git worktree add`):
  ```python
  def test_own_change_passes():
      assert "PASS streams.owned" in out and code == 0
  def test_other_streams_file_fails():
      assert "FAIL streams.owned.b-owned.py" in out and "stream b" in out
  def test_unowned_path_names_stream_ownership():
      assert "FAIL streams.owned.new.txt" in out and "stream-ownership" in out
  def test_change_then_revert_still_fails():   # per commit, programs design §12
      assert "FAIL streams.owned.b-owned.py" in out
  def test_stream_may_not_edit_request():
      assert "FAIL streams.owned." in out and "requests/" in out
  def test_integration_merged_into_stream_fails():   # Q-M4 (a)
      assert "FAIL streams.integration." in out
  def test_stream_judged_against_main():
      assert "PASS streams.owned" in out and code == 0
  def test_integration_merge_of_main_exempt():
      assert code == 0
  def test_integration_non_merge_outside_folder_fails():
      assert "FAIL streams.owned.src/x.py" in out
  def test_append_rows_rule():
      assert "PASS streams.shared" in appended_out and "FAIL streams.shared." in edited_out
  def test_no_live_program_passes_with_one_line():
      assert out.strip() == "PASS streams.none" and code == 0
  def test_detached_without_branch_is_input_fail():
      assert out.startswith("FAIL streams.input:")
  # test_run_all.py
  def test_streams_runs_when_program_live_on_light():
      assert "streams" in gate_order(out) and "streams" not in gate_order(no_program_out)
  ```
- [ ] **Step 2: Run the test command; expect FAIL.**
- [ ] **Step 3: Implement** `gate_streams.py`, the gitinfo additions and `run_all`'s live gate list.
- [ ] **Step 4: Run the test command on both interpreters and `python3 -m gates run_all`; expect PASS** (no live program here, so `run_all` does not run `streams`; `python3 -m gates check streams` prints `PASS streams.none`).
- [ ] **Step 5: Commit** `feat(gates): gate_streams; run_all runs it while a program is live`, then checkpoint with `gates=PASS`. **Block P2 end:** as block 1d.

---

## Block P3: merge policy and cleanup (branch `block/p3`)

**Owner step before P3 starts (ledgered with the owner's words):** set this repository's host merge methods to merge commits only (squash and rebase merges disabled). Branch protection is already on (pull request required, admins enforced); the merge method is not yet recorded as set. Block 4's `init` offers the same for target repositories.

### Task P3.1: the pull-request merge policy: `merge.mode`, `MERGED` lines checked against git, no push to the base branch

**Files:**
- Create: `gates/lib/merge.py`
- Modify:
  - Config (owner answer Q-Pplan-14 (a)): Block 2's Task 2c.2 already adds `merge` to `config/2`, and this task only reads it. `.strict-delivery/config.yml` gets `merge: {mode: controller}` (owner Q-M1 for this repository).
  - `gates/gate_checkpoint.py` (Task P1.3's gate gains `checkpoint.merges`).
  - `gates/tools/githooks.py` (`githook pre-push` refuses a push to the base branch).
  - `.github/workflows/strict-delivery.yml`: a pull-request job that checks out `github.event.pull_request.head.sha` with full history (not the test-merge ref, review 4 F-Pp4-4), creates local `<p>/integration` branches from the fetched `origin/*/integration` refs, and runs `check streams --branch <head ref>`. The existing `run_all` job is unchanged.
- Test: `tests/test_merge_lib.py`, `tests/test_gate_checkpoint.py`, `tests/test_config.py`, `tests/test_migrations.py`, `tests/test_githooks.py`, `tests/test_self_adoption.py`

**Owner answers applied:** owner directive (`main` protected); Q-M1; Q-M4 (a); Q-15 (a); controller ruling on the merge method; Q-Pplan-14; OQ-1, OQ-16.

**Interfaces:**
- Consumes: `migrations.*`, `config.load`, `checkpoints.merged_lines/ledger_errors` (Task P1.2), `gitinfo.is_ancestor/parents/rev_list/commit_exists/changed_paths` (Tasks P1.3, P2.3), `githooks` (block 2, Task 2b.2), `result.*`.
- Produces:
  - `merge` config: optional `merge` (`map {mode: enum [host, controller]}`), default `host` (fail-closed: no agent merges unless the project says so).
  - `merge.MODES = ("host", "controller")`; `merge.agent_may_merge(cfg) -> bool` (`mode == "controller"`). Block 3's Bash hook calls it before an agent's `gh pr merge` (cross-block notes).
  - `merge.merged_errors(root: str, cfg: dict, plan: str, line: dict) -> list` of `(suffix, reason)` for one `MERGED` line of plan slug `plan`:
    - `merge.<pr>`: `merge` names a commit on the first-parent history of the local `base_branch` (`rev_list --first-parent`), with exactly two parents; a commit not found locally fails with `update <base_branch> from the remote`;
    - `head.<pr>`: the merge commit's second parent is `head` (under `--match-head-commit` the merged head is exactly the approved sha; in `host` mode `head` is the host's `headRefOid`);
    - `plan.<pr>` (review 5 F-Pp5-1, review 6 F-Pp6-1): the merge's own diff, from its first parent to the merge commit (`changed_paths(root, merge + "^1", merge)`), changes at least one path under `<paths.plan_state>/<plan>/`. Merely holding the ledger in the head's tree is not enough, since every branch cut from a `main` that already holds this plan's ledger holds it too; a line copied from another plan's ledger names a merge that did not touch this plan's workspace, so it does not count. Every PR of a plan carries at least its checkpoint lines, so an honest merge always passes; a PR that touches only code fails (fail-closed);
    - `approval.<pr>`: `approval` is `chat` when `merge.mode` is `controller` and `host` when it is `host`; for `chat`, the named `pr` and `head` equal the line's `pr` and `head`.
  - What the checks prove, stated plainly (review 5 F-Pp5-2): that a merge commit for this plan's PR exists on the base branch and merged exactly the head sha recorded, and, in controller mode, that the recorded approval named that PR and sha. They cannot prove the owner said the words: the approval rests on the owner's chat record and the ledger line, which the owner reviews at the block end.
  - `gate_checkpoint` line `checkpoint.merges`: every `MERGED` line of the plan's ledger passes `merged_errors(root, cfg, plan, line)` (PASS when there is none).
  - `githook pre-push`: in addition to block 2's rule (Q-B2plan-12 (a)), a stdin line whose remote ref is `refs/heads/<base_branch>` fails `githook.base: <base_branch> is protected; open a pull request` before any gate runs (owner directive).

**Input-domain dimensions:**
- Config: `merge` absent (default `host`), `{mode: controller}`, `{mode: auto}`, not a map, unknown key.
- `MERGED` line against git: a real `--no-ff` merge whose second parent is `head`; a squash (one parent); a merge whose second parent is another commit (the head moved); a merge off the first-parent line; a sha unknown locally; `approval` disagreeing with `merge.mode`; a `chat` approval naming another PR or head; a line copied from another plan's ledger (review 5 F-Pp5-1); another plan's PR whose branch was cut from a `main` that already holds this plan's ledger (its head tree holds this ledger, its merge diff does not touch this plan's workspace: fails; review 6 F-Pp6-1); a PR that touches only code (fails); a PR that touches this plan's ledger (passes); a PR that touches both plans' workspaces (counts for both).
- Pre-push: pushing a work branch; pushing `HEAD:main`; deleting the remote base branch; base branch configured as another name.
- Workflow: the PR job's checkout is the head sha with full history; integration branches created before `check streams`.

- [ ] **Step 1: Write the failing tests:**
  ```python
  # test_merge_lib.py
  def test_default_mode_is_host():
      assert not agent_may_merge(config.load(root)) and agent_may_merge(config.load(root_controller))
  def test_merged_line_checked_against_git():  # owner Q-15 (a)
      assert merged_errors(root, cfg_controller, "p", LINE) == []
      assert ("head." + PR, ANY) in merged_errors(root, cfg_controller, "p", {**LINE, "head": OTHER})
  def test_line_copied_from_another_plan_fails():   # review 5 F-Pp5-1, review 6 F-Pp6-1
      # fixture: main already holds p's ledger; the other plan's branch is cut from that main, touches only q's workspace, and is merged --no-ff
      assert ("plan." + PR, ANY) in merged_errors(root, cfg_controller, "p", OTHER_PLAN_LINE)
  def test_code_only_pr_fails_plan_check():
      assert ("plan." + PR, ANY) in merged_errors(root_code_only, cfg_controller, "p", LINE_CODE_ONLY)
  def test_chat_approval_must_name_pr_and_head():   # review 5 F-Pp5-2
      assert ("approval." + PR, ANY) in merged_errors(root, cfg_controller, "p", {**LINE, "approval_head": OTHER})
  def test_squash_is_no_merge():               # controller ruling on the merge method
      assert ("merge." + PR, ANY) in merged_errors(root_squashed, cfg_controller, "p", LINE)
  # test_gate_checkpoint.py
  def test_checkpoint_checks_merged_lines():
      assert "FAIL checkpoint.merges" in bad_out and "PASS checkpoint.merges" in good_out
  # test_config.py
  def test_this_repo_merge_mode():             # owner Q-M1
      assert config.load(REPO)["merge"]["mode"] == "controller"
  # test_githooks.py
  def test_push_to_base_refused():
      assert proc.returncode != 0 and "githook.base" in proc.stdout + proc.stderr
  # test_self_adoption.py
  def test_pr_job_checks_out_head_sha():       # review 4 F-Pp4-4
      assert "github.event.pull_request.head.sha" in text and "check streams --branch" in text
  ```
- [ ] **Step 2: Run the test command; expect FAIL.**
- [ ] **Step 3: Implement**, set this repository's `merge.mode`; cite Q-M1 in the commit body.
- [ ] **Step 4: Run the test command on both interpreters and `python3 -m gates run_all`; expect PASS.** From here every `MERGED` line is checked at each checkpoint.
- [ ] **Step 5: Commit** `feat(gates): PR merge policy: merge.mode, MERGED lines checked against git, no push to the base branch`, then checkpoint.

### Task P3.2: per-effort sets, the plan's final merge, the deletion proof completed

**Files:**
- Create: `gates/lib/cleanup.py`
- Modify: `gates/lib/findings.py` (`may_delete` gains the merge check; signature unchanged); `gates/lib/gitinfo.py` (additive: `last_text`)
- Test: `tests/test_cleanup_lib.py`, `tests/test_findings_lib.py`, `tests/test_gate_register.py`

**Owner answers applied:** OQ-5, OQ-6; controller rulings (shared specs; merge method); Q-M4 (a); Q-15 (a); Q-Pplan-9.

**Interfaces:**
- Consumes: `checkpoints.merged_lines/plan_slug/parse_handoff` (Task P1.2), `merge.merged_errors` (Task P3.1), `programs.load_program/live_programs` (Task P2.1), `decisions.is_resolved/in_force`, `findings.may_delete/RESOLVED`, `claims.load/slug`, `gitinfo.show/ls_tree/merge_base/tracked_files`, `config.load`.
- Produces:
  - `gitinfo.last_text(root: str, ref: str, path: str) -> Optional[str]`: the file's text at `ref`, or, when it is absent there, its text at the parent of the newest commit reachable from `ref` that deleted it (`git log -1 --diff-filter=D --format=%H <ref> -- <path>`); `None` when it never existed.
  - `plan_ledger(root, cfg, plan) -> Optional[str]`: `last_text(root, "HEAD", <paths.plan_state>/<plan>/ledger.md)`, falling back to the working tree first. A cleanup PR deletes the ledger, so this reads the version its deletion removed.
  - `final_merge(root: str, cfg: dict, plan: str) -> Optional[dict]` (Q-15 (a)): the plan ledger's `MERGED` line with `final=yes`, when it passes `merged_errors(root, cfg, plan, line)` (so a line copied from another plan never ends this one); `None` otherwise. The plan has merged when this exists; every earlier `MERGED` line is a merge of the plan, not its end.
  - `findings.may_delete(row, root, cfg, decision_records)`: Task 1b.3's grant rule is replaced (Q-15 (a): no grant records exist for PR merges) by `final_merge(root, cfg, row["resolved_by"])` existing (spec §7.2: "the merge-commit check arrives with `gate_cleanup`"; spec edit SE-18). Task 1c.2's `gate_register` behaviour follows with no gate change; its tests gain the case. The fields Q-ES adds to findings are not read.
  - `plan_effort(root: str, cfg: dict, plan: str, at: str) -> list`: the repo-relative per-effort paths of plan slug `plan` as of commit `at` (programs design §7.2): `<paths.plans>/<plan>.md`; every tracked path under `<paths.plan_state>/<plan>/` and `<paths.reviews>/<plan>/`; each `spec` path the plan's handoff at `at` names, unless the handoff of another live plan (any other `handoff.md` at the tip of `base_branch`) names it too (controller ruling); every claim file whose `document` is one of these; every finding with a resolved status and `resolved_by: <plan>`.
  - `program_effort(root, cfg, program, at) -> list`: the program's `plan` and `specs` from `streams.yml` (read at the tip of `<program>/integration`), and `plan_effort` of each stream plan at its final merge. The program folder never reaches `base_branch` under Q-M4 (a), so it is not in the set.
  - `cited_decisions(root: str, paths: list, at: str, prefix: str) -> list`: the decision ids found as whole tokens in those files at `at`.
  - Under Q-Pplan-9 (a), `merged` stays unreachable: `findings.validate` keeps refusing it (OQ-6).

**Input-domain dimensions:**
- `final_merge`: no `MERGED` line; only `final=no` lines (this repository's sub-block PRs; review 3 F-Pp3-1); a `final=yes` line that fails `merged_errors`; the ledger deleted at `HEAD` (read from before its deletion); the ledger never existed.
- `last_text`: present; deleted once; deleted, re-added and deleted again (newest deletion wins); never existed.
- `may_delete`: an unresolved row; resolved with a final merge (allowed); resolved with only non-final merges (refused); resolved with a final line whose merge is a squash (refused).
- `plan_effort`: plan file absent at `at`; handoff absent at `at` (no spec added); a spec shared with a live plan; claims on a per-effort document and on a kept one; resolved findings of this and of another plan; open findings owned by the plan (not in the set; judged by the gate).
- `program_effort`: two streams, one merged and one not (refused upstream by the gate); a stream plan absent.
- `cited_decisions`: ids in code blocks, as longer tokens, in a binary file.

- [ ] **Step 1: Write the failing tests:**
  ```python
  def test_plan_not_merged_until_final_line():   # review 3 F-Pp3-1, Q-15 (a)
      assert final_merge(root_nonfinal_only, cfg, "p") is None and final_merge(root_final, cfg, "p")["pr"] == "12"
  def test_ledger_read_from_before_its_deletion():
      assert "MERGED pr=12" in plan_ledger(root_cleanup_branch, cfg, "p")
  def test_may_delete_needs_final_merge():     # spec §7.2
      assert not findings.may_delete(RESOLVED_ROW, root_nonfinal_only, cfg, decs) and findings.may_delete(RESOLVED_ROW, root_final, cfg, decs)
  def test_plan_effort_lists_per_effort_paths():
      assert set(plan_effort(root, cfg, "p", MERGE_SHA)) == {PLAN_MD, LEDGER, HANDOFF, REVIEW, SPEC, CLAIM_FILE, RESOLVED_F}
  def test_shared_spec_kept():
      assert SPEC not in plan_effort(root_two_plans, cfg, "p", MERGE_SHA)
  def test_program_folder_not_in_program_effort():   # Q-M4 (a)
      assert not any(p.startswith(PROGRAMS + "/") for p in program_effort(root, cfg, NAME, None))
  def test_cited_decisions_whole_token():
      assert cited_decisions(root, [PLAN_MD], MERGE_SHA, "DEC") == [D1]
  # test_gate_register.py
  def test_resolved_finding_deletion_needs_final_merge():
      assert "FAIL register.base.deleted." + FID in out
  ```
- [ ] **Step 2: Run the test command; expect FAIL.**
- [ ] **Step 3: Implement** `cleanup.py`, the `may_delete` change and `last_text`.
- [ ] **Step 4: Run the test command on both interpreters and `python3 -m gates run_all`; expect PASS.**
- [ ] **Step 5: Commit** `feat(lib): per-effort sets, the plan's final merge, deletion proof completed`, then checkpoint.

### Task P3.3: `gate_cleanup`; the cleanup pull request

**Files:**
- Create: `gates/gate_cleanup.py`
- Modify: `gates/__main__.py` (`GATES["cleanup"]`), `.github/workflows/strict-delivery.yml` (in the pull-request job at the head sha, a `check cleanup --plan <x>` step for `cleanup/<x>` heads, per Q-Pplan-9 (a))
- Test: `tests/test_gate_cleanup.py`, `tests/test_self_adoption.py`

**Owner answers applied:** controller ruling (not in `run_all`); OQ-9; owner directive; Q-15 (a); Q-Pplan-9.

**Interfaces:**
- Consumes: `cleanup.*` (Task P3.2), `decisions.landed_errors/is_resolved`, `store.Store`, `findings.RESOLVED`, `gitinfo.tracked_files`, `result.*`, `config.load`.
- Produces: `PRODUCES = ()`; `check(args)` (gate `cleanup`), `main(argv=None) -> int`. Arguments: `--root`; exactly one of `--plan SLUG` or `--program NAME` (neither or both fails `cleanup.input`); `--decision DEC`, required with `--program` (the `program-close` decision) and refused with `--plan`. Lines, each with one `PASS` when clean (spec §9; programs design §12):
  - `cleanup.merge`: `final_merge` exists for the plan; for a program, `--decision` names an answered `program-close` decision and every stream plan has its final merge; with none the gate stops after this line, since nothing else is defined.
  - `cleanup.gone.<path>`: each path of `plan_effort` / `program_effort` at that final merge commit is absent from the tracked files.
  - `cleanup.owner.<id>`: an open finding whose owner is `plan` with this plan has not passed to an issue or roadmap item (programs design §8.3: "ownership then passes to an issue or roadmap item").
  - `cleanup.open.<id>`: a decision cited in the per-effort files at the merge commit is still open.
  - `cleanup.landed.<id>`: a cited `lasting` decision fails `landed_errors` at the current tree, so its rule no longer lands outside the cleaned files ("every lasting decision they produced has a `landed_in` outside them").
- Under Q-Pplan-9 (a): the cleanup is its own pull request from a branch `cleanup/<plan>` (or `cleanup/<program>` at close) cut from the updated `base_branch`; its first commit appends the final `MERGED` line to the plan's ledger, its second removes, with `git rm`, the set `cleanup.gone` names; the workflow runs `check cleanup` for such heads; it merges like any PR, on the owner's approval (Q-15 (a)).

**Input-domain dimensions:**
- argv: neither, both, `--plan` unknown, `--program` without `--decision`.
- Merge: no final line; final line failing `merged_errors`; only non-final lines.
- Paths: all gone; one left; a review report left; a resolved finding left; a claim file left; a shared spec kept (passes).
- Findings: open finding owned by the plan; moved to an issue (passes).
- Decisions: cited open; cited lasting with `landed_in` removed since; cited one-off (not judged); superseded lasting (its superseder judged by `in_force`).
- Program: one stream not merged; a stream plan's workspace left; `program-close` open.
- Workflow: a `cleanup/<plan>` head (step runs at the head sha); any other head (step skipped).

- [ ] **Step 1: Write the failing tests:**
  ```python
  def test_clean_after_final_merge_passes():
      for c in ["merge", "gone", "owner", "open", "landed"]: assert "PASS cleanup." + c in out
      assert code == 0
  def test_left_ledger_fails():
      assert "FAIL cleanup.gone." + LEDGER in out
  def test_no_final_merge_stops_after_merge_line():
      assert "FAIL cleanup.merge" in out and "cleanup.gone" not in out
  def test_open_finding_still_owned_by_plan_fails():
      assert "FAIL cleanup.owner." + FID in out
  def test_cited_open_decision_fails():
      assert "FAIL cleanup.open." + DID in out
  def test_lasting_decision_unlanded_fails():
      assert "FAIL cleanup.landed." + DID in out
  def test_program_close_needs_decision():
      assert out.startswith("FAIL cleanup.input:")
  # test_self_adoption.py
  def test_workflow_runs_cleanup_for_cleanup_heads():
      assert "gates check cleanup --plan" in text
  ```
- [ ] **Step 2: Run the test command; expect FAIL.**
- [ ] **Step 3: Implement** `gate_cleanup.py` and the workflow step.
- [ ] **Step 4: Run the test command on both interpreters and `python3 -m gates run_all`; expect PASS.**
- [ ] **Step 5: Enable.** This repository has no finished plan yet, so the gate is exercised in a `mktemp -d` clone with a local bare remote: two sub-block branches of a fixture plan merged with `git merge --no-ff` (the PR merge commit's shape), their `MERGED` lines (the second `final=yes`) written as the next branch's first commit, then `cleanup/<fixture>` removing the set; run `check cleanup --plan <fixture>`; expect PASS; ledger it. Its first real run is this plan's own close.
- [ ] **Step 6: Commit** `feat(gates): gate_cleanup for plans and programs; cleanup pull requests`, then checkpoint with `gates=PASS`. **Block P3 end:** as block 1d.

---

## Block P4: questions, continuation, dispatch (branch `block/p4`)

### Task P4.1: the upward-question path

**Files:**
- Create: `gates/tools/questions_cli.py`
- Modify: `gates/__main__.py` (`COMMANDS["questions"]`)
- Test: `tests/test_questions_cli.py`

**Owner answers applied:** Q-H5 (a); Q-Pplan-8; spec §7.1 (answers from the human only).

**Interfaces:**
- Consumes: `checkpoints.parse_handoff/handoff_errors/plan_slug`, `programs.load_program/branch_of/live_programs`, `decisions_cli.main` (`ask`), `store.Store("decision")`, `gitinfo.show/current_branch`, `config.load`.
- Produces: `main(argv: list) -> int` for `python3 -m gates questions <sub>`:
  - Sources, per Q-Pplan-8 (a): with `--program P`, the committed `handoff.md` at the tip of each stream branch `branch_of(P, s)`, at the path `<paths.plan_state>/<plan slug of s>/handoff.md`; with `--plan SLUG --ref REF`, that one handoff at `REF`. A missing branch or handoff is an error line and exit 1.
  - The tag: a question `qid` of plan `x` is tied to its decision by the topic `q:<x>:<qid>` (a topic string; no schema change).
  - `list (--program P | --plan SLUG --ref REF)`: one line per question: `pending <x>:<qid> <stream or plan>: <question>` when no decision carries the tag; `asked <x>:<qid> -> <DEC id>` when an open one does; `answered <x>:<qid> -> <DEC id>` when an answered one does; withdrawn decisions are ignored. Exit 0.
  - `ask (--program P | --plan SLUG --ref REF) --by WHO`: for each pending question, calls `decisions_cli.main(["ask", "--class", class, "--question", text, "--option", "label::cost", ..., "--effect", effect, "--topic", tag, "--by", WHO])`, so the session asks every new question as one batch, each a decision record (programs design §4.3: "The session batches the questions for the owner. Answers go down as decision records"). Prints `asked <x>:<qid> -> <id>` per question; a failing `ask` stops with exit 1 after reporting what was asked.
  - Who runs it: the session acting as program controller (Q-H5 (a)), or a separate `program_controller` when one is used, with `--root` the integration worktree under Q-Pplan-11 (a), so the decision records it writes are program commits on `<program>/integration` (controller ruling on ownership); the human answers with `decisions decide` (spec §7.1). Relaying the answer down by `SendMessage` is prompt prose (Task P4.3).

**Input-domain dimensions:**
- Sources: a program with two streams, one with questions; a stream branch missing; a handoff missing at the tip; an invalid handoff; an uncommitted question in a worktree (not read under (a)).
- Tags: no decision; open; answered; withdrawn then re-asked; two decisions with one tag (error naming both).
- `ask`: zero pending (exit 0, nothing asked); two pending; `decisions ask` refusing one (an unknown class); `--by` missing.
- Question text holding newlines, `::`, non-ASCII.

- [ ] **Step 1: Write the failing tests:**
  ```python
  def test_list_marks_pending_asked_answered():
      assert lines(out) == ["pending a-plan:q1 a: Which?", "asked a-plan:q2 -> " + D2, "answered a-plan:q3 -> " + D3]
  def test_ask_writes_one_decision_per_pending_question():
      assert [rec(d)["topics"] for d in new_ids] == [["q:a-plan:q1"]] and rec(new_ids[0])["status"] == "open"
  def test_ask_twice_asks_nothing_new():
      assert second_new_ids == []
  def test_uncommitted_question_not_read():    # Q-Pplan-8 (a)
      assert "q9" not in out
  def test_two_decisions_one_tag_is_error():
      assert code == 1 and D4 in err and D5 in err
  ```
- [ ] **Step 2: Run the test command; expect FAIL.**
- [ ] **Step 3: Implement** `questions_cli.py`.
- [ ] **Step 4: Run the test command on both interpreters and `python3 -m gates run_all`; expect PASS.**
- [ ] **Step 5: Commit** `feat(tools): questions list and ask: the upward-question path`, then checkpoint.

### Task P4.2: automatic continuation: `continue`

**Files:**
- Create: `gates/tools/continue_cli.py`
- Modify: `gates/__main__.py` (`COMMANDS["continue"]`)
- Test: `tests/test_continue_cli.py`

**Owner answers applied:** Q-H5 (a); programs design §4.4 and §17 ("how the continuation prompt is rendered from a handoff, within the rules above"); block-2 answers Q-B2plan-18 (a) (layout of `## Role` and `## Strict block`).

**Interfaces:**
- Consumes: `checkpoints.*`, `programs.load_program/status_rows/live_programs`, `questions_cli` tags (Task P4.1), `dispatch.HEADINGS/MIN_TIERS/tier_of`, `gate_dispatch.check`, `gitinfo.show`, `config.load`.
- Produces: `main(argv: list) -> int` for `python3 -m gates continue --plan SLUG [--ref REF] [--prompts DIR] [--input-json FILE --dispatcher ID --depth N --live-children N --live-total N]`:
  - Reads the plan's handoff and ledger (working tree, or at `REF`), and, when the handoff names `program` and `stream`, that stream's status row from the integration branch.
  - Refuses (exit 1, nothing printed on stdout):
    - `live_subagents` non-empty: children are still running and nothing is orphaned (programs design §4.2);
    - any handoff question whose tag has no answered decision (the agent waits for its answer);
    - an invalid handoff or ledger; a role whose resolved tier (below) has no model in `models.tiers`, or a `top_tier_fallback` naming a tier that is unset or not `tier1`-`tier4` (the same verdicts as `dispatch.tier`).
  - Prints a dispatch prompt in the spec §10 grammar, the headings exactly `dispatch.HEADINGS`:
    - `## Role`: the handoff's `role`;
    - `## Brief`: the continue instruction (`Continue <plan> at <next_task>; branch <branch>; head <head>`), the handoff path, the ledger lines after the last `CHECKPOINT` line verbatim, the status row verbatim, and each answered decision id from the questions; `program: <p>` and `stream: <s>` lines when set (Task P4.3 reads them);
    - `## Findings`: `findings_in_flight`, or `None.`;
    - `## Claims`: `None.`;
    - `## Budget: tokens=<t> minutes=<m>` from `budget`;
    - `## Model`: the model of the role's resolved tier, the rule `gate_dispatch` checks (Task 2c.3, owner Q-B2plan-21): `tier<MIN_TIERS[role]>`, except that a `top_tier_roles` role whose minimum tier is `tier4` takes the tier named by `models.top_tier_fallback` (default `tier3`) while `tier4` is unset; with `tier4` set, the fallback is ignored;
    - `## Report`: the spec §10 status line;
    - `## Strict block`: an empty line, the bytes of `<prompts>/<role>.md`, an empty line;
    - `## Task`: `Resume at <next_task> from the handoff; nothing continues from inherited memory.`
  - With `--input-json FILE`: also writes the `gate_dispatch` input object (`prompt`, `model`, `subagent_type` absent, `dispatcher` from the four flags, `program_live` from `live_programs`).

**Input-domain dimensions:**
- Handoff: valid; `live_subagents` one entry; a pending, an asked-only and an answered question; invalid front matter; `role` with a tier that has no model; `program` set and unset.
- Tier resolution (Q-B2plan-21): `role: final_verifier` with `tier4` unset and the fallback default (the `tier3` model); with `top_tier_fallback: tier2`; with the fallback naming `tier9` (refused); with `tier4` set (the `tier4` model, fallback ignored); a tier4 role outside `top_tier_roles` (refused, as `dispatch.top-tier`).
- Ledger: lines after the last `CHECKPOINT` none, several; no `CHECKPOINT` line (refused as an invalid ledger).
- Status page: row present; row missing (refused).
- Prompts directory: the role's file missing; CRLF in the file (bytes kept).
- `--input-json`: each flag missing, negative, `bool`-like text.
- Output: passes `gate_dispatch.check` for a plain plan dispatcher (`session`, depth 0) and for a stream dispatcher in a fixture program.

- [ ] **Step 1: Write the failing tests:**
  ```python
  def test_continue_prompt_passes_gate_dispatch():   # fixture prompts dir; dispatcher session, depth 0, program_live false
      assert gate_dispatch.check(["--root", root, "--prompts", pdir, "--input", jfile]).ok()
  def test_headings_in_order():
      assert [l for l in out.splitlines() if l.startswith("## ")][:4] == ["## Role", "## Brief", "## Findings", "## Claims"]
  def test_live_subagents_refused():
      assert code == 1 and out == "" and "orphan" in err
  def test_unanswered_question_refused():
      assert code == 1 and "q1" in err
  def test_ledger_tail_in_brief():
      assert "Dispatched: x" in brief(out) and "CHECKPOINT" not in brief(out)
  def test_model_from_min_tier():
      assert section(out, "## Model").strip() == cfg["models"]["tiers"]["tier3"]
  def test_top_tier_role_uses_fallback_when_tier4_unset():   # owner Q-B2plan-21
      assert section(out_fv, "## Model").strip() == cfg["models"]["tiers"]["tier3"] and gate_dispatch.check(fv_args).ok()
  def test_tier4_set_ignores_fallback():
      assert section(out_fv_t4, "## Model").strip() == "m4"
  ```
- [ ] **Step 2: Run the test command; expect FAIL.**
- [ ] **Step 3: Implement** `continue_cli.py`.
- [ ] **Step 4: Run the test command on both interpreters and `python3 -m gates run_all`; expect PASS.**
- [ ] **Step 5: Commit** `feat(tools): continue renders the continuation dispatch from handoff, ledger and status page`, then checkpoint.

### Task P4.3: `gate_dispatch` for live programs; the two prompt blocks; this repository's limits

Starts only after the two prompt files are on `main` and A has updated from `main` (Q-Pplan-6; the same wait as Task 2c.3's).

**Files:**
- Modify: `gates/lib/dispatch.py` (`required`, `program_errors`), `gates/gate_dispatch.py` (lines `dispatch.program`, `dispatch.stream`)
- Not created here: `.claude/settings.json` already holds this repository's limits (commit 1e5bdc1: depth 5, concurrency 30); this task only pins it with a test.
- Prompt files: `skills/strict-delivery/prompts/program_controller.md` and `stream_controller.md` and their `tests/prose_check.py` rows, by the route of Q-Pplan-6.
- Test: `tests/test_dispatch_lib.py`, `tests/test_gate_dispatch.py`, `tests/test_self_adoption.py`

**Owner answers applied:** Q-H1, Q-H3, Q-H4, Q-H5 (a); measured facts; DB-1, DB-2, DS-3; controller ruling on live programs; Q-Pplan-6.

**Interfaces:**
- Consumes: `dispatch.*` and `gate_dispatch.check` (block 2), `programs.live_programs/load_program` (Task P2.1), `config.load`.
- Produces:
  - `dispatch.required(root: str, cfg: dict) -> bool`: `True` when the profile is `standard` or `strict`, or `live_programs` is non-empty (spec §12: "Wherever a program is live, `gate_streams` and `gate_dispatch` run, whatever the profile"). Block 3's hook calls it.
  - `dispatch.program_errors(sections: dict, role: str, root: str, cfg: dict, program_live: bool) -> list` of `(suffix, reason)`:
    - `program`: the input's `program_live` differs from `bool(live_programs(root, cfg))` (the caller's claim is checked against git; fail-closed);
    - `program`: a `program_controller` or `stream_controller` dispatch whose `## Brief` holds no line `program: <p>` naming a live program;
    - `stream`: a `stream_controller` dispatch whose `## Brief` holds no line `stream: <s>` naming a stream of that program's `streams.yml` on its integration branch.
  - `gate_dispatch` prints `dispatch.program` and `dispatch.stream` lines (PASS when clean), after `dispatch.dispatcher`. Block 2's `DISPATCHERS`, `LEVELS_BELOW` and limits are unchanged: they already admit the session (Q-H5 (a)) and a sub-controller (Q-H3) and refuse workers (Q-H4).
  - The two prompt blocks, written by the route of Q-Pplan-6, carry these decisions (the brief to their writer quotes each):
    - both: the Q-H5 (a) tree and that the depth limit decides when a separate `program_controller` or nested sub-controllers are used; a controller never returns while its children run; questions go into the handoff (committed, Q-Pplan-8) and up by `SendMessage`; answers come down as decision ids; continuation by `python3 -m gates continue`; `status:` report contract; work branches are pushed at every checkpoint and nothing is ever pushed or merged to the base branch directly (owner directive);
    - `program_controller` (also what the session follows when it acts as one): mints ids and writes program files and global records only through `program`, `questions` and `decisions` in the integration worktree (Q-Pplan-11); runs syncs (merge main into integration, update stream branches from main per Q-Pplan-5, combined testing by merging stream heads into integration, never merging integration anywhere) and appends the `SYNC` line; relays the owner's chat approval of a finished stream's PR (naming its head sha) and, in `controller` mode, runs `gh pr merge <n> --merge --match-head-commit <sha>`, then reads the merge back from the host for the stream's `MERGED` line (Q-15 (a)); brings global records to the base branch per Q-Pplan-12; refreshes only at a sync, when every stream is at a checkpoint (programs design §4.2); never implements or reviews;
    - `stream_controller`: runs its plan block by block in `<worktrees>/<program>/<stream>/main` on a branch cut from the base branch; dispatches sub-controllers and workers within the depth limit; merges group branches into its stream branch after a clean review and green gates; when the stream is finished, opens its pull request to the base branch (`gh pr create`) and reports up; never merges that PR, never merges the integration branch into its own, never edits another stream's files or status row; raises requests; stops NEEDS_DECISION on an owner question.
  - The pin: `test_repo_subagent_limits` asserts the committed `.claude/settings.json` (1e5bdc1) equals `{"env": {"CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH": "5", "CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS": "30"}}`, so a later edit is a visible test change.

**Input-domain dimensions:**
- `program_live` in the input: true and false, against zero and one live program.
- `## Brief` program lines: absent; naming a closed program (no integration branch); naming a live one; two `program:` lines; leading spaces; `stream:` naming an unknown stream; `stream:` for a `program_controller` (ignored).
- Roles: `program_controller` and `stream_controller` from `session` at depth 0 and 1 under limits 3 and 6 (block 2's table applies unchanged); a worker as dispatcher (Q-H4).
- `required`: each profile, with and without a live program.
- Prompt files: present and byte-equal; absent (`dispatch.block` fails, as block 2).
- `.claude/settings.json` (committed): values are strings; no other key; the test fails on any change.

- [ ] **Step 1: Write the failing tests:**
  ```python
  # test_dispatch_lib.py
  def test_required_on_light_when_program_live():
      assert required(root_live, LIGHT) and not required(root_none, LIGHT) and required(root_none, STRICT)
  def test_program_live_claim_checked_against_git():
      assert ("program", ANY) in program_errors(secs, "implementer", root_live, cfg, False)
  def test_stream_controller_names_known_stream():
      assert ("stream", ANY) in program_errors(secs_unknown_stream, "stream_controller", root_live, cfg, True)
  # test_gate_dispatch.py
  def test_session_dispatches_stream_controller_in_live_program():   # Q-H5 (a), real fixture program
      assert "PASS dispatch.dispatcher" in out and "PASS dispatch.stream" in out and code == 0
  def test_stream_controller_without_live_program_refused():
      assert "FAIL dispatch.dispatcher" in out or "FAIL dispatch.program" in out
  # test_self_adoption.py
  def test_repo_subagent_limits():             # owner answer 2026-11-01; file committed at 1e5bdc1
      assert json.load(open(".claude/settings.json")) == {"env": {"CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH": "5", "CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS": "30"}}
  ```
- [ ] **Step 2: Run the test command; expect FAIL.**
- [ ] **Step 3: Implement** the two dispatch additions.
- [ ] **Step 4: Run the test command on both interpreters and `python3 -m gates run_all`; expect PASS.**
- [ ] **Step 5: Enable.** In a `mktemp -d` clone: create a fixture program with `program create` (a fixture `program-create` decision, plan and `breakdown.yml` in the clone only), render a `stream_controller` dispatch from the real prompt file, run `python3 -m gates check dispatch --input <file>` with `dispatcher {id: session, depth: 0, live_children: 0, live_total: 0}`; expect every line PASS; ledger it. Raise the block-3 request for `playbook/streams.md` and `playbook/sessions.md` (cross-block notes) when B is live.
- [ ] **Step 6: Commit** `feat(gates): gate_dispatch for live programs; program and stream controller prompt blocks; pin subagent limits`, then checkpoint with `gates=PASS`. **Block P4 end:** as block 1d; this ends the programs block. The next step, running blocks 3-6 as a program, starts with the owner's `program-create` decision.

---

## Block 3: plugin packaging and Claude Code hooks (program streams `runtime`, `bash`, `tools`, `package`)

Spec §17: "3. Plugin: skill, role prompt blocks, base playbook, Claude Code hooks." The plan's outline line for block 3 is the scope, exactly. Stream B (Tasks B1.1-B2.3) delivers the skill `skills/strict-delivery/SKILL.md`, the role prompt blocks (PC1-PC5 written into them) and the base playbook (`SD-R<n>`). Block 3 packages those files and does not plan them again. What block 3 builds:
- `.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json`, and the version agreement check that starts with `plugin.json` (Q-B2plan-24 (a)).
- `hooks/hooks.json` and the hooks as `python3 -m gates hook <event>`: SessionStart, UserPromptSubmit, PreToolUse Agent, Bash and Edit/Write, PostToolUse Read, plus SubagentStop for the live-subagent count (spec edit SE-B3-1).
- The Bash branch: the bypass block; refusal of `decisions decide` and `decisions withdraw` from any subagent (spec §4, §7.1, as edited by SE-B3-2 and SE-B3-7; Q-B3plan-6 (b)); the gated commit, which refuses a `git commit` while any tracked file has unstaged changes before any gate runs (spec §13, F-r3-1), and refuses `git commit` inside a compound command or with a `GIT_INDEX_FILE` override (Q-r4-1 (a), Q-r4-2 (a)); the gated push; and the pull-request-flow refusals (Q-15 (a), programs cross-block notes, spec §4 as edited by SE-17).
- The Edit/Write branch: refusal of an agent Edit or Write under `paths.decisions` (owner Q-16 (a), spec §4 and §7.1 as edited by SE-19), and surfacing of in-force decisions whose `applies_to` matches, once per session per decision (spec §7.4).
- The Agent branch: `gate_dispatch` (block 2, Task 2c.3) run with the `dispatcher` object (`id`, `depth`, `live_children`, `live_total`) and `program_live` (`programs.live_programs`, Task P2.1), whenever `dispatch.required(root, cfg)` (Task P4.3) is true. The hook never invents a count it cannot determine. An absent field fails `dispatch.input` (block 2 cross-block note).
- SessionStart lists active overrides from answered `rule-override` decisions' `overrides` field (`decision/2`, block 2) and refuses nothing. `decisions.validate` already refuses an override of a fixed rule when it is written (block 2).

### How block 3 runs (program)

Blocks 3-6 run as one program after the programs block (owner's `program-create` decision; programs design §5). The session acts as program controller (Q-H5 (a)). Block 3 has four streams with disjoint file ownership, each of one sub-block of at most 3 tasks, each ending in its own pull request to `main` (Q-M4 (a); controller mode, Q-15 (a): the owner approves in chat naming the PR and head sha, the controller runs `gh pr merge <n> --merge --match-head-commit <sha>`, the merge is read back and ledgered as a `MERGED` line). Stream branches `<program>/<stream>/main`, group branches `<program>/<stream>/<group>` (programs design §4.1). The commit gate is `python3 -m gates run_all` plus the test command on both interpreters, with a clean tree, and from Task P1.3 the checkpoint step runs `check checkpoint`.

| Stream | Sub-block, tasks | Starts | Parallel groups |
|---|---|---|---|
| `runtime` | 3a: 3a.1 session store; 3a.2 hook entry, `hooks.json`, SessionStart, UserPromptSubmit, PostToolUse Read | at program start | serial (3a.2 consumes 3a.1) |
| `package` | 3d: 3d.1 manifests and `run_all.version`; 3d.2 (conditional) playbook streams and sessions prose | at program start | 3d.1 and 3d.2 in parallel (disjoint files) |
| `bash` | 3b: 3b.1 shell scanner; 3b.2 bypass block, decide/withdraw, gated commit; 3b.3 push, base branch, `gh` | 3b.1 at program start; 3b.2 after streams `runtime` and `package` have merged into `main` and `bash` has updated from `main` | 3b.1 runs beside `runtime`; 3b.2 then 3b.3 serial (same files) |
| `tools` | 3c: 3c.1 Edit/Write; 3c.2 Agent and SubagentStop | after streams `runtime` and `package` have merged into `main` and `tools` has updated from `main` | 3c.1 and 3c.2 in parallel (disjoint files) |

`runtime`, `package` and `bash` (3b.1) run in parallel from the start; `bash` (3b.2-3b.3) and `tools` run in parallel after `runtime` and `package` merge. If either is not on `main` when `bash` finishes 3b.1, `bash` ledgers the wait and stops `BLOCKED: waiting for runtime and package` (stream rules, "Cross-stream order").

**File ownership (`streams.yml`; exact paths; a trailing `/` means every path under it).** Paths not listed stay with the program's residual owner.

| Stream | Owns |
|---|---|
| `runtime` | `gates/hook.py`; `gates/hooks/__init__.py`, `gates/hooks/session_start.py`, `gates/hooks/prompt_submit.py`, `gates/hooks/post_read.py`; `gates/lib/hookio.py`, `gates/lib/session.py`, `gates/lib/transcript.py`, `gates/lib/worktrees.py`; `hooks/hooks.json`; `tests/hookrun.py`, `tests/test_session_store.py`, `tests/test_transcript.py`, `tests/test_worktrees.py`, `tests/test_hookio.py`, `tests/test_hook_entry.py`, `tests/test_hook_session_start.py`; its plan workspace |
| `bash` | `gates/lib/shellscan.py`, `gates/lib/bashpolicy.py`, `gates/hooks/pre_bash.py`; `gates/lib/gitinfo.py` (additive only); `gates/tools/githooks.py` (additive refactor only); `tests/test_shellscan.py`, `tests/test_bashpolicy.py`, `tests/test_hook_bash.py`; its plan workspace |
| `tools` | `gates/hooks/pre_edit.py`, `gates/hooks/pre_agent.py`, `gates/hooks/subagent_stop.py`; `tests/test_hook_edit.py`, `tests/test_hook_agent.py`; its plan workspace |
| `package` | `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`; `gates/lib/plugin.py`; `gates/__main__.py`, `gates/producers.py`, `gates/run_all.py`, `tests/test_run_all.py` (controller ruling, binding for the program of blocks 3-6); `tests/test_plugin_manifest.py`; under Task 3d.2 only, `playbook/streams.md`, `playbook/sessions.md`, `tests/test_playbook.py`; its plan workspace |

**Shared registration files (controller ruling, binding for the program of blocks 3-6).** `gates/__main__.py`, `gates/producers.py`, `gates/run_all.py` and `tests/test_run_all.py` are owned by stream `package`. Controller ruling for all blocks (F-B3p-19): registry requests land with `package` while it is live, else with A (DS-3). Every other stream, here and in blocks 4-6, adds its line to these files only by such a request (programs design §6; `R-` request records minted by the program controller). Standing receiver step: before `package`'s final review, `package` lands every registry request open at that time, in a commit per request, and the controller marks each `status=done` with its sha; when `package`'s PR merges, its registry paths pass to A (DS-3), and every later request (blocks 4-6) lands with A. `.claude-plugin/plugin.json` and `marketplace.json` pass the same way, and move on to block 6's release stream only through that block's `stream-ownership` decision. In block 3 there is one request, known now and so planned into Task 3d.1: `COMMANDS["hook"]`, a lazy wrapper that imports `gates.hook` and calls its `main(argv)`; while `gates/hook.py` is absent the wrapper exits 2 with `FAIL hook.missing: gates.hook is not installed` (fail closed). `runtime`'s own tests call `gates.hook.main` in a subprocess (`python3 -c "import sys, gates.hook; sys.exit(gates.hook.main(sys.argv[1:]))" <Event>`); `tests/hookrun.py` uses `python3 -m gates hook` when `COMMANDS` has `hook`, and that form otherwise. Streams `bash` (from 3b.2) and `tools` start only after both `runtime` and `package` have merged into `main`, so their tests run the production entry `python3 -m gates hook`. `gates/lib/plugin.py` (the plugin-version reader and the two repository readers `repository_url` and `repository_slug`) is `package`'s; block 4 consumes it.

`gates/hook.py` (owned by `runtime`) names every handler module from Task 3a.2 on, including the modules `bash` and `tools` create later. A missing handler module fails closed (Task 3a.2), and no Claude Code session in this repository runs these hooks until the controller ruling on enabling (below) is met, so nothing is bricked in between. `tests/hookrun.py` is `runtime`'s test helper; `bash` and `tools` import it and never edit it (a change is a request to `runtime`).

**Measured Claude Code facts (session controller, before Task 3a.2 is dispatched).** Block 3 relies on hook behaviour the documentation states only in part (hooks reference read 2026-11-02: common input fields `session_id`, `transcript_path`, `cwd`, `hook_event_name`, and `agent_id`/`agent_type` "when the hook fires inside a subagent"; PreToolUse exit 2 "routes the same way as `deny`" and other non-zero exits are non-blocking; `additionalContext` on PreToolUse; SessionStart and UserPromptSubmit stdout added as context; SubagentStop input `agent_id`, `agent_type`, `agent_transcript_path` (the subagent's transcript "in a nested `subagents/` folder"); Agent `tool_input` fields `prompt`, `description`, `subagent_type`, `model`; plugin hook processes receive `CLAUDE_PLUGIN_ROOT`, `CLAUDE_PLUGIN_DATA`, `CLAUDE_PROJECT_DIR`). The docs also state (hooks reference, 2026-11-02): "On `PreToolUse`, a timed-out `command`, `http`, or `mcp_tool` hook doesn't block the tool call, except for hooks whose failure blocks the action", and a `command` hook blocks on failure when it sets `"onFailure": "block"`; the default timeout is 600 s for `command` hooks, lowered to 30 on `UserPromptSubmit`. So every PreToolUse entry in `hooks.json` sets `"onFailure": "block"` (fail-closed directive), and M7 checks it.

The probe is a plugin in a `mktemp -d` directory, never committed, whose every hook appends its stdin JSON to a log in that directory and exits 0 (exit 2 for the one PreToolUse case M5 and M7 need). The session controller loads it with `claude --plugin-dir <probe>` in a disposable clone and drives each case below with a scripted prompt, then reads the log. It ledgers field names and verdicts only, never values. Each measurement has a stated pass:
- M1: one main-session Bash call and one Bash call from a dispatched subagent. Pass: the subagent's PreToolUse input has `agent_id`, and the main session's has none.
- M2: the same two records. Pass: equal `session_id`.
- M3: three subagents: a foreground one, a background one, and one dispatched with `subagent_type: fork`. Pass for the first two: the transcript found from a hook fired inside each (its `transcript_path`, or the nested `subagents/` layout from the main transcript and `agent_id`) has, as its first user entry, the dispatch prompt byte for byte. The fork is recorded separately: if its first user entry is not its dispatch prompt, the fork's own dispatches fail `dispatch.input` and its stop never matches. That is the fail-closed side, and the fork is refused by `gate_dispatch` (`dispatch.fork`) whenever the gate is required.
- M4: SubagentStop for the foreground and background subagents of M3, and for a fourth subagent interrupted by the human (Esc) on the controller's request. Pass: one SubagentStop each with `agent_transcript_path`. If the interrupted one has none, its record stays live until the next SessionStart with source `startup`, `resume` or `fork` (an over-count; stated limit).
- M5: a PreToolUse hook that exits 2 with stderr `M5-deny`, and one that prints `additionalContext` `M5-context`. Pass: the model's next turn quotes both strings.
- M6 (owner step): the controller asks the human to type `!true` once in the probe session. Pass: the log has no PreToolUse record for that command. If it fails, the block stops, because the human could then not answer decisions inside Claude (Q-B3plan-6).
- M7: a PreToolUse hook with `timeout: 1`, `onFailure: "block"`, that sleeps 5 s; and one whose command is `exec /nonexistent-python3` (exit 127) with `onFailure: "block"`. Pass: both tool calls are blocked. If the second goes ahead, ruling (3a)'s limit on a missing `python3` stands as stated.
- M8: one call of each of `Agent`, `Bash`, `Edit`, `Write`, `MultiEdit`, `NotebookEdit`, `Read`, with matchers listing those names. Pass: the logged `tool_name`s are exactly these, with path fields `file_path` (Edit, Write, MultiEdit, Read) and `notebook_path` (NotebookEdit). Fail: any other name, or `Task` present, which adds `"Task": "agent"` to `TOOL_GROUPS` and `Task` to the Agent matcher.
- M9: the entry `cd "${CLAUDE_PLUGIN_ROOT}" && exec python3 -m gates hook <Event>` as written in `hooks.json`. Pass: the probe log shows stdin arrived intact and `CLAUDE_PLUGIN_DATA` is an absolute path.
- M10: in a subagent, `cd <dir>` in one Bash call, then `pwd` in the next; and the same in the main session, with the next PreToolUse input's `cwd` logged, once for a directory inside the working directories and once for a sibling worktree outside them (`../<worktree>`). Pass: the logged `cwd` values are the ones the Bash tool documents (a subagent's `cd` never carries; the main session's carries only inside the working directories), which is why ruling (3b) admits only the `git -C` and `cd <dir> &&` forms and why the program session names its stream and integration worktrees explicitly. Owner path when a write is refused for the session outside its allowed worktrees: the human runs it with `!`. Expected from the reviewer's direct check (2026-11-02): the subagent's `cd` does not carry, the main session's does. This decides ruling (3b) on commit targets: if the subagent's `cd` does carry, the `cd <dir> && ...` form is still allowed and nothing else changes.

The tests pin the shapes as fixtures built from these field names (synthetic values). A measurement that contradicts how a task uses it stops that task `NEEDS_DECISION`, as Q-B2plan-22 does for the subagent limits.

**Owner answers applied across the block (binding):** the controller ruling of 2026-11-02 on shared registration files (above); Q-16 (a); Q-15 (a); Q-M1 and `merge.agent_may_merge` (Task P3.1); Q-H1-Q-H5 (a); Q-B2plan-19 (a) (`gate_dispatch` lists in-force decisions and checks claims and decisions; the hook passes its lines on), Q-B2plan-21 (top tier fallback), Q-B2plan-22 (measured limits), Q-B2plan-23 (a), Q-B2plan-24 (a); F-3, F-r3-1, Q-r4-1 (a), Q-r4-2 (a), Q-1a2r-5; DB-6, DB-9, F-2; OQ-16 (unknown keys refused); owner directives: protected `main`, fail closed, narrow stated promises, no hardcoded model names, paths, owner handles or test filename patterns, Python 3.9+ standard library, copy nothing from another project, registers ship empty.

**Interfaces consumed (by exact name, from the signed-off plans):** `result.Result/GateError/gate_args/run_check/safe_text`; `config.load/DEFAULTS`; `gitinfo.toplevel/head_sha/unstaged_paths/hooks_dir/current_branch/upstream_sha/remotes/tracked_files/user_email`; `store.Store(root, kind, cfg).load()`; `decisions.in_force/superseded_ids/is_resolved/validate`; `index.regenerate(root, cfg)`; `run_all.check/main/PROFILE_GATES/BASE_GATES`; `githook pre-commit|pre-push` and `githooks install|status` (`gates/tools/githooks.py`); `dispatch.ROLES/role_of/parse/required`; `gate_dispatch.check` with its input object and lines; `programs.live_programs(root, cfg)`; `merge.agent_may_merge(cfg)`; `checkpoints.parse_handoff(text)`; `helpers.make_repo/commit_all/write_record/GitIsolatedTestCase`; B's `skills/strict-delivery/SKILL.md` front matter (line 2 `name: strict-delivery`, Task B2.3).

**Controller rulings (spec or plan settles each; ledgered in the sub-block named, at most five per sub-block):**
- (3a) Controller ruling: a PreToolUse refusal is exit status 2 with the reason on stderr; a pass never prints `permissionDecision: "allow"` (which would skip the user's own permission prompts), only optional `additionalContext`; any internal error in a PreToolUse hook is exit 2, and every PreToolUse entry sets `"onFailure": "block"` so a timeout or a failed launch blocks too (M7) -- spec §13 "Hooks fail closed on internal error" -- cost if wrong: one output format change; stated limit, only if M7's second case goes ahead: a machine without `python3` fails open (block 4's `doctor` checks the Python version) -- spec §13; hooks reference (exit 2 blocks the tool call, stderr is the reason; `onFailure: "block"`).
- (3a) Settled by spec edit SE-B3-5 (owner answer Q-SE-1 (a), 2026-11-02): each `hooks.json` entry is `cd "${CLAUDE_PLUGIN_ROOT}" && exec python3 -m gates hook <Event>`; the hook takes its root from the input's `cwd` (its git top level), never from the process directory or `CLAUDE_PROJECT_DIR` -- a target repository's own top-level `gates/` package would otherwise shadow the framework (the reason block 2 chose Q-B2plan-13 (a) for the git shims), and the logic stays in Python -- spec §3 as edited by SE-B3-5 ("each `hooks.json` entry, like the git hook shims, is one POSIX sh line that changes to the plugin directory and execs `python3 -m gates`"); Q-B2plan-13 (a).
- (3a) Controller ruling: the PostToolUse Read entry is registered and writes nothing until block 5 lands receipts and the receipt schema -- the plan's outline gives "read receipts and the receipt schema" to block 5 -- cost if wrong: none; block 5 fills `gates/hooks/post_read.py` -- plan "Later blocks", Block 5.
- (3a) Controller ruling: SessionStart's context load list is spec §7.4's default session load (`in-force.md`, regenerated first, and the open decisions) until block 5's `context.yml` exists; "active overrides" are answered `rule-override` decisions with an `overrides` field that are neither superseded nor withdrawn -- spec §7.4 "Default session load: `in-force.md` and the open decisions"; §7.1 "Superseded is not a status: a decision is superseded when a later answered decision names it" -- cost if wrong: one filter -- spec §4, §7.1, §7.4, §8.
- (3b) Controller ruling: the bypass list reads as follows: `--no-verify` and every option starting `--no-v` (git accepts unambiguous abbreviations) in a git command; `-n` alone or inside a short-option cluster for `git commit` only (for `git push`, `-n` is `--dry-run`); `hooksPath` case-insensitively anywhere (git config keys are case-insensitive), and `git -c` / `--config-env` before a subcommand; any `GIT_CONFIG_*` assignment or mention; HOME moves are any assignment, `export`, `unset`, `declare`/`typeset`/`readonly`/`local`, or `env -u` of `HOME` or `XDG_CONFIG_HOME`, since both relocate git's global config -- spec §4 lists "`--no-verify`, `-n`, `core.hooksPath`, `GIT_CONFIG_*`, HOME moves" -- cost if wrong: one table edit; spec edit SE-B3-2 names `XDG_CONFIG_HOME` and `-c` -- spec §4.
- (3b) Controller ruling (F-B3p-2): a subagent's `cd` does not carry to its next Bash call (M10; the Bash tool: `cd` carries "only in the main session"), and stream worktrees sit outside the main checkout, so a git write (`bashpolicy.GIT_WRITES`: `commit`, `push`, `merge`, `pull`, `rebase`, `cherry-pick`, `revert`, `am`, `reset`, `update-ref`, `tag`, `stash`, `worktree`, and `branch`, `checkout`, `switch` with a create, move, copy, delete or force option) may name its worktree in exactly two forms: `git -C <dir> <subcommand> ...` (one `-C`, first among the git options) and `cd <dir> && git <subcommand> ...` (exactly one `cd` with one plain word, `&&`, then one plain git command; the scanner reports it as plain with `cd = <dir>`). Its target is the git top level of `<dir>` (joined to `cwd`, `realpath`ed), or of `cwd` when neither form is used, and that top level is the root for every check (config, clean tree, branch, base, gates). The target must be one of the caller's allowed worktrees (F-B3p-13, F-B3p-14, F-B3p-15):
  - a subagent (a call with `agent_id`): exactly the worktree bound to it at dispatch (ruling (3c) on worktree binding), whether it names it or uses its default `cwd`; so its plain write in the main checkout is refused unless its bound worktree is the main checkout; an agent with no bound worktree (its record not found, a controller dispatched with none, or the store unavailable) is refused every git write;
  - the main session, no program live: the top level of its `cwd` only;
  - the main session, a program live (the session as default program controller, Q-H5 (a)): the top level of its `cwd`, each worktree named in the `worktree` column of a live program's status page (`programs.status_rows`, Task P2.1, read at the tip of `<program>/integration`), and the worktree that has `<program>/integration` checked out (`git worktree list --porcelain`); nowhere else. A path the hook cannot resolve is not allowed.
  Refused: any other target, including a top level of another repository, more than one `-C`, `--git-dir`, `--work-tree`, `--namespace`, `--super-prefix`, `--exec-path`, `--bare`; assignments of `GIT_DIR`, `GIT_WORK_TREE`, `GIT_COMMON_DIR`, `GIT_OBJECT_DIRECTORY`, `GIT_INDEX_FILE`; and the hook process itself inheriting `GIT_INDEX_FILE`, `GIT_DIR` or `GIT_WORK_TREE` (an inherited variable reaches the Bash tool too) -- the hook's checks must read the index and branch the commit records, and the compound rule exists so nothing runs between the check and the commit; a lone `cd` before it changes no index -- cost if wrong: a subagent that legitimately works in two worktrees is refused in the second (it is dispatched once per worktree instead); the session in a plain plan cannot write in a sibling worktree (the human runs it with `!`, or a program is created); stated limit: the binding is only as right as the dispatch's `worktree:` line, which the dispatcher writes and the hook checks against the dispatcher's own allowed worktrees (ruling (3c)) -- spec §13 "so a commit runs as its own command, and its check runs before that command, so the index the commit records changes only through the commit itself"; Q-r4-1 (a), Q-r4-2 (a); programs design §4.1 (worktree per stream and group).
- (3b) Controller ruling: a `git push` with no refspec is refused when the current branch is the base branch, when its `branch.<b>.merge` is `refs/heads/<base>`, when `push.default` is `matching`, or when the remote has a configured `remote.<r>.push`; `--all`, `--mirror`, `--prune` and any refspec holding `*` are refused -- each form can update the base branch without naming it -- cost if wrong: an agent names its refspec explicitly -- spec §4 "refusal of an agent's push to the base branch in any refspec form".
- (3b) Controller ruling (was Q-B3plan-2): the Bash checks are fail-closed text checks: a command whose text holds a bypass word, or `decision` with `decide`/`withdraw`, is refused even inside quotes; a command that mentions `git` with `commit`, `push`, `merge` or `pull` (aliases resolved), or `gh` with `pr merge` or `api`, is refused unless it is exactly one plain simple command whose program is `git` (or `gh`), or the `cd <dir> &&` form above -- the owner directive "Fail closed; never 'match another tool exactly'; narrow, stated promises" settles it, and a recogniser-only check runs any unlisted wrapper with no check -- cost if wrong: false refusals (`grep "git commit" docs`, a commit message containing `--no-verify`, a heredoc or `2>&1` on a commit), which agents rewrite; stated limit either way: a script file or interpreter (`sh c.sh`, `python3 x.py`) whose text names neither word is not caught -- owner directive (fail closed); spec §4, §13.
- (3b) Controller ruling (was Q-B3plan-4): `gh api` is allowed for reads only (no method other than GET, no field or input, a GraphQL query with no `mutation`), and the REST merge endpoint in any spelling is refused with every method, GET included -- plan, programs cross-block note: "It also refuses every other agent route to a merge or a base-branch update ... `gh api` calls to the REST merge endpoint (`repos/<owner>/<repo>/pulls/<n>/merge`, any method or path spelling)", and the protected-`main` directive; enumerating write endpoints admits ref, contents and merges writes to the base -- cost if wrong: agents use `gh pr comment`, `gh pr create` and the like instead of raw API writes, and a merge-status read goes through `gh pr view` -- spec §4 as edited by SE-B3-2.
- (3c) Controller ruling: the PreToolUse Agent hook counts a subagent as live from the moment its dispatch passes until a SubagentStop whose transcript's first prompt has the same SHA-256; a dispatcher whose own record it cannot find, or a session store it cannot read, gives no `dispatcher` field, so `gate_dispatch` fails `dispatch.input` -- block 2: "It must not invent a count it cannot determine: an absent count fails `dispatch.input`" -- cost if wrong: a dispatch that another hook denies after this one passed stays counted until the next SessionStart with source `startup`, `resume` or `fork` (the one reset rule; an over-count, the fail-closed side; ruling (3a) and Task 3a.2 use the same rule) -- plan Block 2, "Cross-block notes".
- (3c) Controller ruling (F-B3p-13): an agent's worktree is bound at dispatch. The field is one line in the dispatch prompt's `## Task` body, `worktree: <absolute path>` (the first line of that body matching `^worktree: /`; a second such line fails), which the Agent hook reads with `dispatch.parse` and checks before the gate verdict counts: the path `realpath`s to the top level of a worktree of the same repository (equal `git rev-parse --git-common-dir`), and it is one of the dispatcher's allowed worktrees (ruling (3b) on commit targets) or, for a dispatcher bound to a stream worktree on branch `<p>/<s>/main`, a group worktree on a branch `<p>/<s>/<g>` (programs design §4.1); else `FAIL hook.agent.worktree: <reason>`. A dispatch with no `worktree:` line binds the main checkout (the session's `cwd` top level) when no program is live; when a program is live, a worker dispatch without one is refused (`FAIL hook.agent.worktree: a worker in a live program names its worktree`), and a controller-role dispatch without one binds nothing, so that controller may dispatch but makes no git write. The bound path is stored in the dispatch record (`session.add_dispatch(..., worktree)`) and found again by the prompt's SHA-256, like the role and depth -- the hook cannot tell which worktree is an agent's own from git alone, since every stream and group worktree shares one repository; the dispatcher's brief is the one place that states it -- cost if wrong: one `## Task` line in every dispatch of a live program (the program controller's prompt renderer, Task P4.2, writes it; a request to its owner); no change to `gates/lib/dispatch.py`, whose grammar already admits any `## Task` text -- programs design §4.1; spec §10 (`## Task` heading).
- (3c) Controller ruling: the Edit/Write refusal matches any target path whose case-folded segments contain the case-folded segments of `paths.decisions` as a contiguous run, so another worktree's or clone's decision directory is refused too, and so is a case variant on a case-insensitive volume -- "under `paths.decisions`" must hold in every checkout an agent can reach -- cost if wrong: an unrelated directory with the same trailing segments cannot be edited by agents -- spec §4 PreToolUse Edit/Write; owner Q-16 (a).
- (3d) Controller ruling: `run_all.version` compares `framework_version` with the `version` of `.claude-plugin/plugin.json` beside the installed `gates` package; `marketplace.json`'s entry carries the same version, held equal by a test, not by `run_all` -- Q-B2plan-24 (a), plan Task 2b.1: "Spec §4's agreement check starts in the block that lands the second listed source (block 3's `.claude-plugin/plugin.json`), comparing `framework_version` with it."; spec §4 lists plugin version, CLAUDE.md block version, CI pin and `framework_version`, and spec §15 bumps `marketplace.json` too -- cost if wrong: one more line -- spec §4 "Versioning", §15.
- (3d) Controller ruling: the hooks go live in this repository (the owner enables the plugin from this checkout's marketplace) only after all four block-3 streams have merged into `main` and every live stream branch has updated from `main`; until then every hook is exercised through `python3 -m gates hook` in tests and in a disposable clone -- a live PreToolUse hook would route to handler modules that do not exist yet on other branches and refuse every call -- cost if wrong: the hooks go live one merge later than they could -- plan Block 2 controller ruling on hook install timing (precedent); stream rules "Cross-stream order".

**Plan choices (design §17 names, owner-approved call I7), stated because they carry a spec edit:** the hook session state lives at `${CLAUDE_PLUGIN_DATA}/sessions/<session_id>.yml` with a lock file beside it, outside every repository, as a strict-YAML-subset file whose first key is `schema: hook-session/1`, checked by its reader (`session.state_errors`) because no tree holds it (spec edit SE-B3-3). When `CLAUDE_PLUGIN_DATA` is unset, the Agent hook cannot count (fail closed under the ruling above) and the Edit/Write hook surfaces on every matching edit instead of once.

**Cross-block notes.**
- **Block 4:** `doctor` reports whether the plugin's hooks are active for the repository and runs `run_all.version`; the CLAUDE.md block version joins `run_all.version` when block 4 lands it, and how spec §4's CI pin is met is block 4's to state (blocks 4 and 6 agree the CI template holds no version) (spec §4: "The plugin version, the CLAUDE.md block version, the CI pin (when the CI workflow is installed) and `framework_version` in config must agree; `doctor` and `run_all` fail when they do not."). Block 4 reads the plugin version and `repository_slug` through `gates/lib/plugin.py` (Task 3d.1); its registry requests land with `package` while it is live, else with A (DS-3). `init` writes the subagent limits into `.claude/settings.json` (owner answer).
- **Block 5:** `gates/hooks/post_read.py` writes receipts; SessionStart prints `context.yml`'s list instead of the default load; `gate_context` joins the Agent hook and the gated commit (spec §9: "`gate_context` fails a dispatch or commit when a required read is missing").
- **Block 6:** the release script bumps the version in `plugin.json` and the `marketplace.json` entry (spec §15 also lists the CLAUDE.md block; blocks 4 and 6 agree the CI template holds no version, so block 3 names no CI pin); Claude Code resolves version constraints against tags named `<plugin-name>--v<version>` (plugin dependencies reference), which sits beside the spec's semver tags; block 6 decides whether to push both.

---

## Stream `runtime`, sub-block 3a (branch `<program>/runtime/main`)

### Task 3a.1: the hook session store

**Files:**
- Create: `gates/lib/session.py`
- Test: `tests/test_session_store.py`

**Owner answers applied:** plan choice on session state (SE-B3-3); OQ-16; fail closed (owner directive); block 2 cross-block note (no invented counts).

**Interfaces:**
- Consumes: `yamlsub.load/emit` (Task 1a.1), `result.GateError`.
- Produces:
  - `class SessionUnavailable(GateError)`.
  - `SESSION_ID = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")`.
  - `session_dir(env: Mapping[str, str]) -> str`: `<CLAUDE_PLUGIN_DATA>/sessions`; raises `SessionUnavailable` when the variable is unset, empty or not absolute.
  - `locked(env: Mapping[str, str], session_id: str, timeout_s: int = 10)`: a context manager yielding the state dict and writing it back on a clean exit.
    - It refuses an id that does not match `SESSION_ID`.
    - It creates the directory with mode `0o700`, and refuses one that is a symlink or not owned by the current uid.
    - It takes `fcntl.flock(LOCK_EX)` on `<id>.lock` (opened `O_CREAT | O_NOFOLLOW`, mode `0o600`), polling `LOCK_NB` until `timeout_s`, and raises `SessionUnavailable` on timeout.
    - It reads `<id>.yml` (absent gives the empty state); on exit it writes `<id>.yml.tmp` and `os.replace`s it.
    - A file that fails `state_errors` raises `SessionUnavailable` whose message names the file and the recovery path: `the session state file <path> is unreadable (<error>); start a new session (SessionStart moves it aside), or as the human delete it: rm '<path>'`. It is never reset silently mid-session.
  - State shape (`hook-session/1`, closed key sets): `{schema: hook-session/1, session: <id>, dispatches: [{sha: <64 hex>, role: <str>, depth: <int ≥ 1>, parent: <str>, worktree: <absolute path or "">, branch: <str or "">}], surfaced: [<decision id>]}`. `parent` is `session` or an `agent_id`; `worktree` is the path bound at dispatch, `""` for none; `branch` is the branch checked out in that worktree when the binding was recorded, `""` for none or a detached HEAD (ruling (3c) on worktree binding; F-B3p-20).
  - `state_errors(state: object, session_id: str) -> list`: every key unknown or missing, every wrong type (`bool` is not an `int`), `session` differing from the file name's id.
  - `reset(env, session_id) -> Optional[str]` (F-B3p-3): under the lock, never parsing the old file when it is unreadable. A readable file keeps `surfaced` and empties `dispatches`. An unreadable one (any read, YAML or `state_errors` failure) is renamed, without being parsed, to `<id>.yml.corrupt-<UTC yyyymmddThhmmss>` (a numeric suffix added if taken), a fresh empty state is written, and the new name is returned so SessionStart can report it. A lock file that is a symlink, or a directory owned by another uid, still raises (those are not corruption the store may repair).
  - `prompt_sha(prompt: str) -> str`: SHA-256 of the UTF-8 bytes, lowercase hex.
  - `add_dispatch(state, sha, role, depth, parent, worktree, branch)`, `end_dispatch(state, sha) -> bool` (removes one entry with that sha; `False` when none), `live_total(state) -> int`, `live_children(state, parent) -> int`.
  - `lookup(state, sha) -> Optional[tuple]`: `(role, depth, worktree, branch)` when every live entry with that sha agrees on all four, `None` when there is none or they disagree.
  - `mark_surfaced(state, decision_id) -> bool`: `True` the first time.

**Input-domain dimensions:**
- `CLAUDE_PLUGIN_DATA`: unset; empty; relative; absolute and absent (created); a file; a symlink to a directory; a directory owned by another uid (simulated by patching `os.stat`'s uid check).
- `session_id`: valid; empty; 129 characters; `..`; `a/b`; a NUL; non-ASCII; `str` subclass; not a `str`.
- State file: absent; empty; valid; unknown key; `depth` `True`, `0`, `"1"`; `sha` 63 or 65 hex, uppercase; `session` naming another id; a YAML error; a symlink in place of the file.
- Lock: free; held by another process (timeout raises); the process killed while holding it (the lock is released with the descriptor).
- Concurrency: two processes adding 50 dispatches each: 100 entries.
- `lookup`: none; one; two agreeing; two disagreeing in `depth` or `role`.
- `end_dispatch`: matching; none; duplicates (one removed).
- `reset`: readable file (keeps `surfaced`); YAML error; `state_errors` failure; not UTF-8; a directory in place of the file; a `.corrupt-` name already taken; nothing parsed from a corrupt file (checked by a file whose parse would raise a distinct error).
- `lookup` with `worktree`: two entries agreeing on role and depth but not on worktree (`None`).

- [ ] **Step 1: Write the failing tests** (`tests/test_session_store.py`, temp directories as `CLAUDE_PLUGIN_DATA`):
  ```python
  def test_unset_plugin_data_is_unavailable():
      with self.assertRaises(SessionUnavailable): session_dir({})
  def test_relative_plugin_data_is_unavailable():
      with self.assertRaises(SessionUnavailable): session_dir({"CLAUDE_PLUGIN_DATA": "rel"})
  def test_bad_session_ids_refused():              # subTest per id
      with self.assertRaises(SessionUnavailable): enter(locked(env, sid))
  def test_round_trip_and_mode():
      with locked(env, "s1") as st: add_dispatch(st, SHA, "implementer", 1, "session")
      with locked(env, "s1") as st: assert live_total(st) == 1 and live_children(st, "session") == 1
      assert stat.S_IMODE(os.stat(lockfile).st_mode) == 0o600 and stat.S_IMODE(os.stat(sdir).st_mode) == 0o700
  def test_corrupt_state_fails_closed_never_resets():
      with self.assertRaises(SessionUnavailable): enter(locked(env, "s1"))
      assert read(state_file) == CORRUPT
  def test_symlinked_state_refused():
      with self.assertRaises(SessionUnavailable): enter(locked(env, "s1"))
  def test_lock_timeout():                       # a child process holds the lock
      with self.assertRaises(SessionUnavailable): enter(locked(env, "s1", timeout_s=1))
  def test_parallel_writers_lose_nothing():      # two subprocesses x 50 add_dispatch
      assert live_total(final) == 100
  def test_lookup_ambiguous_is_none():
      assert lookup(st_two_depths, SHA) is None and lookup(st_one, SHA) == ("controller", 2, "/w/p/s/main", "p/s/main")
  def test_reset_keeps_surfaced():
      assert st["dispatches"] == [] and st["surfaced"] == ["DEC-20261101-k3f9"]
  def test_reset_moves_corrupt_file_aside_unparsed():   # F-B3p-3
      moved = reset(env, "s1")
      assert read(moved) == CORRUPT and live_total(fresh_state()) == 0
  def test_unreadable_message_names_recovery():
      assert "rm '" + state_file + "'" in str(e.exception) and "start a new session" in str(e.exception)
  def test_lookup_carries_worktree():          # F-B3p-13
      assert lookup(st, SHA) == ("implementer", 3, "/w/p/s/g", "p/s/g") and lookup(st_two_worktrees, SHA) is None
  ```
- [ ] **Step 2: Run the test command; expect FAIL.**
- [ ] **Step 3: Implement `gates/lib/session.py`.**
- [ ] **Step 4: Run the test command on both interpreters and `python3 -m gates run_all`; expect PASS.**
- [ ] **Step 5: Commit** `feat(lib): hook session store: locked per-session state outside the repository`, then checkpoint.

### Task 3a.2: `python3 -m gates hook`, `hooks/hooks.json`, SessionStart, UserPromptSubmit, PostToolUse Read

**Files:**
- Create: `gates/hook.py`, `gates/hooks/__init__.py`, `gates/hooks/session_start.py`, `gates/hooks/prompt_submit.py`, `gates/hooks/post_read.py`, `gates/lib/hookio.py`, `gates/lib/transcript.py`, `gates/lib/worktrees.py`, `hooks/hooks.json`, `tests/hookrun.py`
- Not modified here: `gates/__main__.py` (`COMMANDS["hook"]` is stream `package`'s, Task 3d.1)
- Test: `tests/test_hookio.py`, `tests/test_hook_entry.py`, `tests/test_hook_session_start.py`, `tests/test_transcript.py`, `tests/test_worktrees.py`

**Owner answers applied:** controller rulings (3a) above; M1, M2, M5, M8, M9; DB-9 and F-2 (overrides listed, refused nothing); spec §4 "silent no-ops in a repository without `.strict-delivery/config.yml`"; spec §5 (SessionStart regenerates the generated files).

**Interfaces:**
- Consumes: `session.locked/reset/SessionUnavailable` (Task 3a.1); `gitinfo.toplevel/current_branch`; `config.load`; `store.Store`; `decisions.in_force/superseded_ids`; `index.regenerate`; `programs.live_programs`; `checkpoints.parse_handoff`; `result.safe_text`.
- Produces:
  - `hookio.EVENTS = ("SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "SubagentStop")`.
  - `hookio.TOOL_GROUPS: dict`: `{"Agent": "agent", "Bash": "bash", "Edit": "edit", "Write": "edit", "MultiEdit": "edit", "NotebookEdit": "edit", "Read": "read"}`, plus `"Task": "agent"` only if M8 shows the name.
  - `@dataclass HookContext`: `event`, `tool_name: Optional[str]`, `tool_input: dict`, `session_id: str`, `agent_id: Optional[str]`, `transcript_path: Optional[str]`, `cwd: str`, `root: str`, `cfg: Optional[dict]`, `cfg_error: Optional[str]`, `framework_dir: str`, `env: Mapping[str, str]`, `raw: dict`.
  - `@dataclass Outcome`: `deny: list` (FAIL lines; non-empty means refuse), `context: list` (lines for `additionalContext`), `text: list` (plain stdout lines, SessionStart and UserPromptSubmit only).
  - `hookio.parse(event: str, data: bytes) -> dict`: UTF-8 (strict); `json.loads` with `object_pairs_hook` refusing duplicate keys; an object whose `hook_event_name` equals `event`; `session_id` matching `session.SESSION_ID`; `cwd` an absolute `str`; for tool events `tool_name` a `str` and `tool_input` an object; `agent_id`, when present, matching `SESSION_ID`. Anything else raises `GateError("hook.input: ...")`.
  - `hookio.context(event, raw, env, framework_dir) -> Optional[HookContext]`: `None` (silent no-op) when `cwd` is not inside a git work tree or `<toplevel>/.strict-delivery/config.yml` does not exist (`os.path.lexists`); otherwise `cfg = config.load(root)`, and a `GateError` from it sets `cfg_error` (the handler decides; the hook is not silent then).
  - `hookio.render(event: str, outcome: Outcome) -> tuple` of `(stdout: str, stderr: str, code: int)`:
    - PreToolUse with `deny`: `("", "\n".join(deny) + "\n", 2)`.
    - PreToolUse with only `context`: stdout `{"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": "<lines>"}}`, code 0. Never a `permissionDecision`.
    - SessionStart and UserPromptSubmit: the `text` lines on stdout, code 0.
    - PostToolUse and SubagentStop: nothing, code 0.
  - `hook.HANDLERS: dict`, keyed `(event, group)`, each a dotted module defining `handle(ctx: HookContext) -> Outcome`:
    - `("SessionStart", None)`: `gates.hooks.session_start`;
    - `("UserPromptSubmit", None)`: `gates.hooks.prompt_submit`;
    - `("PreToolUse", "agent")`: `gates.hooks.pre_agent` (stream `tools`);
    - `("PreToolUse", "bash")`: `gates.hooks.pre_bash` (stream `bash`);
    - `("PreToolUse", "edit")`: `gates.hooks.pre_edit` (stream `tools`);
    - `("PostToolUse", "read")`: `gates.hooks.post_read`;
    - `("SubagentStop", None)`: `gates.hooks.subagent_stop` (stream `tools`).
  - `hook.main(argv: list) -> int` for `python3 -m gates hook <Event>`: reads stdin bytes, parses, builds the context, imports the handler, renders, writes, exits.
    - Fail closed: any exception (a parse error, a missing or raising handler module, a handler returning a non-`Outcome`) gives, for PreToolUse, exit 2 with `FAIL hook.<event>: <safe reason>; the strict-delivery hook fails closed; the human can disable the plugin with /plugin, and !-prefixed commands still run` (F-B3p-11); for SessionStart and UserPromptSubmit, that line on stdout and exit 0; for PostToolUse and SubagentStop, exit 0 with nothing printed (they refuse nothing; a lost SubagentStop leaves a count high, the fail-closed side).
    - A PreToolUse for a tool outside `TOOL_GROUPS`: exit 0, nothing printed (the matchers do not send one).
    - A wrong argv (`hook` with no event, an unknown event, extra arguments): exit 2.
  - `hooks/hooks.json`: `{"description": ..., "hooks": {...}}` with one entry per `HANDLERS` key. Matchers `Agent` (and `Task` under M8), `Bash`, `Edit|Write|MultiEdit|NotebookEdit`, `Read`. Each command is exactly `cd "${CLAUDE_PLUGIN_ROOT}" && exec python3 -m gates hook <Event>` (ruling (3a), spec edit SE-B3-5). Every PreToolUse entry sets `"onFailure": "block"` (M7). No `timeout` key is set: Claude Code's defaults apply, 600 s for command hooks and 30 s on UserPromptSubmit, which stays within that because it reads only config.
  - `session_start.handle(ctx)`. The `text` lines, in order:
    - `strict-delivery: profile <p>; branch <b|detached>; base <base_branch>; live programs: <names|none>`;
    - `regenerate: PASS` after `index.regenerate(root, cfg)`, or `FAIL hook.session-start.index: <reason>`;
    - `handoff <path>: <resume line>` for each `<paths.plan_state>/*/handoff.md` in the working tree, sorted; an unparseable one gives `FAIL hook.session-start.handoff.<path>: <reason>`;
    - `open decision <id>: <question's first line>` for each open record;
    - `override <SD-Rn> by <id>: <rule or question's first line>` for each active override (controller ruling);
    - `load: <paths.decisions>/in-force.md and the open decisions above` (the default load, controller ruling);
    - `Invoke the <name> skill before any change.`, where `<name>` is line 2 of `<framework_dir>/skills/strict-delivery/SKILL.md` after `name: `; a missing or malformed file gives `FAIL hook.session-start.skill: <reason>`.
    - With source `startup`, `resume` or `fork` (a forked session inherits no live subagents), `session.reset(env, session_id)` runs first. When it moved a corrupt file aside, the line `FAIL hook.session-start.session: <path> was unreadable and was moved to <new path>; live subagent counts restart at zero` is printed; `SessionUnavailable` gives `FAIL hook.session-start.session: <reason>`, whose reason names the recovery path. With `clear` or `compact` the state is kept. An unknown source is treated as `startup`.
    - With `cfg_error`: one `FAIL hook.session-start.config: <reason>; run /strict-delivery:doctor` line, then the skill line.
  - `prompt_submit.handle(ctx)`: on `standard` and `strict`, one line `strict-delivery (<profile>): follow the <name> skill; decisions are asked, never assumed`; on `light`, nothing; with `cfg_error`, the config FAIL line.
  - `post_read.handle(ctx)`: returns an empty `Outcome` (controller ruling; block 5 fills it).
  - `transcript.first_prompt(path: str, max_bytes: int = 4194304) -> Optional[str]` and `transcript.own_transcript(ctx: HookContext) -> Optional[str]`, as Task 3c.2 states them (F-B3p-17: created and tested here, beside `HookContext`; streams `bash` and `tools` consume them).
  - `worktrees.allowed(ctx: HookContext, root: str, cfg: dict, state: Optional[dict]) -> tuple` of `(tops: frozenset, fails: list)` (F-B3p-18; ruling (3b) on commit targets): for a subagent, `{worktree}` from `session.lookup(state, prompt_sha(first_prompt(own_transcript(ctx))))`, or an empty set with the fail `this agent has no bound worktree (<reason>)` when the store (`state` is `None`), the record or its worktree is missing; for the session, the `cwd` top level, plus, while `programs.live_programs(root, cfg)` is non-empty, each live program's status-page `worktree` cells (`programs.status_rows`, Task P2.1) and the worktree holding `<program>/integration`.
  - `worktrees.worktree_list(root: str) -> list` of `(path, branch_or_None)` from `git worktree list --porcelain -z`, run with the environment `gitinfo` uses (`gitinfo.CLEARED_ENV` removed, `LC_ALL=C`); `worktrees.bound_branch(top: str) -> Optional[str]`: the branch checked out at `top`, `None` when detached; `worktrees.same_repository(a: str, b: str) -> bool`: equal `git rev-parse --path-format=absolute --git-common-dir`.
  - `tests/hookrun.py`: `run_hook(event: str, payload: dict, env: dict, cwd: str) -> CompletedProcess`, which runs `[sys.executable, "-m", "gates", "hook", event]` (the production entry) when `gates.__main__.COMMANDS` has `hook`, else `[sys.executable, "-c", "import sys, gates.hook; sys.exit(gates.hook.main(sys.argv[1:]))", event]`, with `cwd` set to the framework checkout and the payload on stdin; `payload(event, root, **fields) -> dict` builds a measured-shape input.

**Input-domain dimensions:**
- argv: none; unknown event; extra argument; each of the five events.
- stdin: empty; not UTF-8; a BOM; not JSON; a JSON list; duplicate keys; `hook_event_name` differing from argv; `session_id` missing, bad characters, 129 characters; `cwd` relative, missing, not a `str`; `tool_input` not an object; `agent_id` present and malformed.
- Root: `cwd` outside any repository (silent); a repository without config (silent); a subdirectory of the root; a linked worktree; config with a YAML error (`cfg_error`); `CLAUDE_PROJECT_DIR` naming another repository (ignored).
- Handler: missing module; module without `handle`; `handle` raising; returning `None`.
- Render: each event with deny, context only, text only, nothing.
- SessionStart sources: `startup`, `resume`, `fork`, `clear`, `compact`, absent, unknown; a corrupt session file at `startup` (moved aside, FAIL line) and at `compact` (kept; FAIL line naming the recovery path).
- `hooks.json`: `onFailure: "block"` on every PreToolUse entry and on no other.
- SessionStart data: no handoffs; two handoffs (sorted); a malformed handoff; no decisions; an open decision; an answered `rule-override` with `overrides`, one superseded, one withdrawn, one without the field; `SKILL.md` absent, line 2 malformed; `index.regenerate` raising.
- Profiles for UserPromptSubmit: light, standard, strict.
- `hooks.json`: every `HANDLERS` key present once; every command byte-exact; valid JSON with the `hooks` wrapper.
- `transcript` and `worktrees`: Task 3c.2's transcript rows; `allowed` for a subagent with a record, without one, with `worktree: ""`, with the store unavailable; for the session with no program, with a live program (status-page worktrees and the integration worktree), with a status cell naming a missing path (not allowed); `worktree_list` with a detached worktree, a path holding a space, a prunable worktree; `same_repository` for two worktrees of one repository and for another repository.

- [ ] **Step 1: Write the failing tests** (`helpers.make_repo` repositories under `GitIsolatedTestCase`; hooks run through `tests/hookrun.py`):
  ```python
  # test_hook_entry.py
  def test_no_config_is_silent():              # spec §4
      p = run_hook("PreToolUse", payload("PreToolUse", bare_repo, tool_name="Bash", tool_input={"command": "git commit --no-verify"}), env, FW)
      assert p.returncode == 0 and p.stdout == "" and p.stderr == ""
  def test_outside_git_is_silent():
      assert p.returncode == 0 and p.stdout == ""
  def test_malformed_input_fails_closed_for_pretooluse():   # subTest per bad stdin
      assert p.returncode == 2 and "hook.input" in p.stderr
  def test_missing_handler_fails_closed():     # HANDLERS patched to a module that does not exist
      assert code == 2 and "fails closed" in err
  def test_raising_handler_fails_closed():
      assert code == 2
  def test_event_mismatch_refused():
      assert p.returncode == 2
  def test_pass_never_allows():                # a handler returning context only
      assert json.loads(out) == {"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": "x"}}
  def test_claude_project_dir_ignored():
      assert seen_root == root
  def test_hooks_json_matches_handlers():
      data = json.load(open("hooks/hooks.json"))
      assert entries(data) == EXPECTED_ENTRIES and all(c == 'cd "${CLAUDE_PLUGIN_ROOT}" && exec python3 -m gates hook ' + e for e, c in commands(data))
  # test_hook_session_start.py
  def test_lists_active_overrides_only():      # DB-9; superseded, withdrawn and field-less excluded
      assert override_lines(out) == ["override SD-R7 by DEC-20261101-k3f9: <rule>"]
  def test_refuses_nothing():
      assert p.returncode == 0
  def test_names_the_skill():
      assert "Invoke the strict-delivery skill before any change." in out
  def test_regenerates_in_force():
      assert os.path.isfile(os.path.join(root, ".strict-delivery/state/decisions/in-force.md"))
  def test_startup_resets_live_counts():
      assert live_total(state_after) == 0
  def test_compact_keeps_live_counts():
      assert live_total(state_after) == 1
  def test_fork_resets_live_counts():          # F-B3p-12 (i)
      assert live_total(state_after) == 0
  def test_corrupt_state_at_startup_reported_and_recovered():   # F-B3p-3
      assert "was unreadable and was moved to" in out and live_total(fresh_state()) == 0
  def test_pretooluse_entries_block_on_failure():   # F-B3p-4
      assert all(h.get("onFailure") == "block" for h in pretooluse_handlers(data)) and not any("onFailure" in h for h in other_handlers(data))
  def test_config_error_named():
      assert "FAIL hook.session-start.config:" in out and "/strict-delivery:doctor" in out
  def test_prompt_submit_by_profile():         # subTest per profile
      assert (out == "") == (profile == "light")
  def test_allowed_worktrees_for_subagent_and_session():   # F-B3p-18
      assert allowed(ctx_sub, root, cfg, st)[0] == {wt} and allowed(ctx_session_live, root, cfg, st)[0] == {main, status_wt, integration_wt}
  def test_unbound_subagent_has_no_worktree():
      assert allowed(ctx_unknown, root, cfg, st) == (frozenset(), [ANY])
  def test_first_prompt_shapes():               # str content, list of text blocks, malformed line, over max_bytes
      assert [first_prompt(p) for p in FIXTURES] == EXPECTED
  def test_post_read_writes_nothing():
      assert listdir_after == listdir_before and p.returncode == 0
  ```
- [ ] **Step 2: Run the test command; expect FAIL.**
- [ ] **Step 3: Implement** the entry, `hookio`, `transcript`, `worktrees`, the three handlers and `hooks.json`.
- [ ] **Step 4: Run the test command on both interpreters and `python3 -m gates run_all`; expect PASS.** Then in a `mktemp -d` clone, run `run_hook` for SessionStart by hand and ledger the output.
- [ ] **Step 5: Commit** `feat(hooks): python3 -m gates hook entry, hooks.json, SessionStart, UserPromptSubmit, PostToolUse Read`, then checkpoint. **Stream `runtime` end:** final review, verifier, PR to `main`, the owner's approval in chat naming the PR and head sha, `gh pr merge --merge --match-head-commit`, `MERGED` line.

---

## Stream `bash`, sub-block 3b (branch `<program>/bash/main`)

### Task 3b.1: the shell scanner

**Files:**
- Create: `gates/lib/shellscan.py`
- Test: `tests/test_shellscan.py`

**Owner answers applied:** Q-r4-1 (a) (a commit runs as its own command); controller rulings (3b) on Bash text checks and on commit targets (the `cd <dir> &&` form).

**Interfaces:**
- Consumes: nothing from block 3.
- Produces:
  - `@dataclass(frozen=True) Scan`: `plain: bool`, `cd: Optional[str]` (the directory of the one allowed compound form, below), `assignments: tuple` of `(name, value)`, `argv: tuple` (words after the leading assignments, quotes removed; set only when `plain`), `reason: str` (empty when plain, else the first construct that made it not plain), `words: tuple` (best-effort words of the whole text, quotes removed, operators as their own tokens; an unbalanced quote leaves the rest as one word).
  - `scan(text: str) -> Scan`. The text is plain when it is exactly one simple command:
    - words made of unquoted characters outside `| & ; < > ( ) $ \` " ' \\` and whitespace, single-quoted strings, double-quoted strings with no unescaped `$` or backtick (inside them `\$`, `` \` ``, `\"`, `\\` and backslash-newline are escapes), and backslash escapes outside quotes;
    - no unquoted newline except trailing newlines, which are dropped; backslash-newline outside quotes joins lines;
    - no word that is `{`, `}`, `!`, `[[`, `]]`, or that starts with `#` (a comment);
    - leading words of the form `NAME=value` (`NAME` matching `[A-Za-z_][A-Za-z0-9_]*`) become `assignments`.
    - The one allowed compound form (ruling (3b) on commit targets): exactly `cd <word> && <rest>`, where `cd <word>` is a simple command of two plain words with no assignments and `<rest>` is plain by the rules above; then `plain` is `True`, `cd` is the unquoted word, and `argv`/`assignments` are `<rest>`'s. `cd` with no word, two words, `-`, an option, a second `&&`, `;` or `||` in its place, or anything after `<rest>` is not plain.
    - Anything else is not plain, with `reason` one of: `operator <op>` (`;`, `&&`, `||`, `|`, `&`, newline), `grouping`, `substitution` (`$(`, backtick, `<(`, `>(`), `expansion` (`$` outside single quotes, `$'...'`), `redirection` (`<`, `>`, `<<`, `<<<`, `>&` and the rest, heredocs included), `comment`, `reserved word`, `unbalanced quote`.
  - `token_in(text: str, word: str, casefold: bool = False) -> bool`: `word` occurs in `text` as a whole token under the Global Constraints boundary (`[0-9A-Za-z_-]` on neither side), inside quotes or not.

**Input-domain dimensions:**
- Separators, each unquoted and inside single and double quotes: `;`, `&&`, `||`, `|`, `&`, newline, a trailing newline, CRLF.
- Grouping: `( )`, `{ ...; }`, `$( )`, backticks, `<( )`, `>( )`.
- Expansions: `$X`, `${X}`, `"$X"`, `'$X'` (plain), `$'..'`, `\$X` (plain).
- Redirections: `>`, `2>&1`, `<`, `<<EOF`, `<<-'EOF'`, `<<<`.
- Quotes: unbalanced single and double; `''` empty word; adjacent quoted parts `a'b'"c"`; a newline inside quotes (plain); `\"` inside double quotes; a backslash before an ordinary character.
- Words: `{`, `}`, `!` alone and inside a word (`HEAD@{1}` plain); `#` at word start and mid-word (`a#b` plain).
- Assignments: `A=1 git`, `A= git` (empty value), `1A=x` (not an assignment), `A=1` alone, an assignment after the program word (an argument).
- Characters: tabs, non-ASCII, NUL.
- The `cd` form: `cd /w/x && git commit -m m` (plain, `cd = /w/x`); `cd '/w/a b' && git push`; `cd /w/x; git commit`; `cd /w/x || git commit`; `cd && git commit`; `cd - && git commit`; `cd -P /w && git commit`; `cd /w/x && cd y && git commit`; `cd /w/x && git commit && git push`; `cd $W && git commit` (expansion: not plain).
- `token_in`: at the start and end; next to `-`, `_`, a digit, `.`, `/`, `"`; case-folded.

- [ ] **Step 1: Write the failing tests** (`tests/test_shellscan.py`; each case a subTest with the expected `plain` and `reason`):
  ```python
  def test_plain_commit():
      s = scan("git commit -m 'a && b'")
      assert s.plain and s.argv == ("git", "commit", "-m", "a && b")
  def test_separators_not_plain():             # ; && || | & newline, unquoted
      assert not scan("git add x && git commit").plain and scan("git add x && git commit").reason == "operator &&"
  def test_grouping_and_substitution_not_plain():   # ( ) { ...; } $( ) backticks
      assert all(not scan(t).plain for t in ("(git commit)", "{ git commit; }", "echo $(git commit)", "echo `git commit`"))
  def test_heredoc_not_plain():
      assert scan("git commit -F - <<'EOF'\nmsg\nEOF").reason == "redirection"
  def test_double_quoted_dollar_not_plain():
      assert scan('git commit -m "$MSG"').reason == "expansion" and scan("git commit -m '$MSG'").plain
  def test_assignments_split():
      assert scan("GIT_INDEX_FILE=x git commit").assignments == (("GIT_INDEX_FILE", "x"),)
  def test_unbalanced_quote_not_plain():
      assert scan("git commit -m 'oops").reason == "unbalanced quote"
  def test_cd_form_is_the_only_plain_compound():   # F-B3p-2
      s = scan("cd /w/x && git commit -m m")
      assert s.plain and s.cd == "/w/x" and s.argv == ("git", "commit", "-m", "m")
      assert not any(scan(t).plain for t in ("cd /w/x; git commit", "cd /w/x && cd y && git commit", "cd /w/x && git commit && git push", "cd - && git commit"))
  def test_token_boundaries():
      assert token_in("xgit commit", "git") is False and token_in("a 'git' b", "git") and token_in("core.HooksPath", "hookspath", True)
  ```
- [ ] **Step 2: Run the test command; expect FAIL.**
- [ ] **Step 3: Implement `gates/lib/shellscan.py`.**
- [ ] **Step 4: Run the test command on both interpreters and `python3 -m gates run_all`; expect PASS.**
- [ ] **Step 5: Commit** `feat(lib): shell scanner for the Bash hook`, then checkpoint. If stream `runtime` has not merged into `main`, ledger the wait and stop `BLOCKED: waiting for runtime`.

### Task 3b.2: the Bash branch: bypass block, `decide`/`withdraw`, the gated commit

Starts after streams `runtime` and `package` have merged into `main` and `bash` has merged `main` into its branch.

**Files:**
- Create: `gates/lib/bashpolicy.py`, `gates/hooks/pre_bash.py`
- Modify: `gates/lib/gitinfo.py` (additive: `aliases`, `config_value`), `gates/tools/githooks.py` (additive refactor: `status_result`, `pre_commit_result`, `pre_push_result`; `main` and its output unchanged)
- Test: `tests/test_bashpolicy.py`, `tests/test_hook_bash.py`

**Owner answers applied:** spec §4, §7.1, §13; F-3, F-r3-1, Q-r4-1 (a), Q-r4-2 (a), Q-1a2r-5; Q-B2plan-11 (strict `commands.test`); controller rulings (3a, 3b) above; Q-B3plan-1 (a), Q-B3plan-6 (b).

**Interfaces:**
- Consumes: `shellscan.scan/token_in` (Task 3b.1); `hookio.HookContext/Outcome`, `transcript.*`, `worktrees.allowed/bound_branch/same_repository` (Task 3a.2); `gitinfo.unstaged_paths/current_branch`; `githooks` (block 2); `config.load`.
- Produces:
  - `gitinfo.aliases(root: str) -> dict`: `git config -z --get-regexp ^alias\.`, name to expansion; `{}` when there are none.
  - `gitinfo.config_value(root: str, key: str) -> Optional[str]`.
  - `githooks.status_result(root: str, framework: str) -> Result`, `githooks.pre_commit_result(root: str) -> Result`, `githooks.pre_push_result(root: str, updates: list) -> Result`: the bodies of `githooks status`, `githook pre-commit` and `githook pre-push` returned instead of printed. Block 2's and P3.1's `test_githooks.py` pass unchanged.
  - `@dataclass Policy`: `root`, `cfg`, `cfg_error`, `env`, `aliases`, `branch: Optional[str]`, `base: str`, `agent_key: str` (`session` or the `agent_id`), `cwd: str`, `state_access` (a callable entering `session.locked`, to read the dispatch-time worktree binding).
  - Consumes `worktrees.allowed(ctx, root, cfg, state)` and `worktrees.bound_branch(top)` (Task 3a.2, stream `runtime`) for the target check; a `fails` result is reported under `hook.bash.target`.
  - `bashpolicy.target_root(scan: Scan, argv_C: Optional[str], p: Policy) -> tuple` of `(root: Optional[str], fails: list)`: the git top level of the named directory (joined to `cwd`, `realpath`ed), or of `cwd` when neither `-C` nor `cd` is used; `FAIL hook.bash.target: <top> is not a worktree this caller may write in (allowed: <tops>)` unless it is in `worktrees.allowed(...)`. Applied to every subcommand in `GIT_WRITES`, plain or not. The returned root's config is loaded and used for every later check.
  - `bashpolicy.COMMIT_WORDS = ("commit",)`, `PUSH_WORDS = ("push",)`, `MERGE_WORDS = ("merge", "pull")`.
  - `bashpolicy.effective_words(text: str, aliases: dict) -> set`: the whole-token git words of `text`, where any alias name occurring as a token after `git` adds the words of its expansion, and an alias whose expansion starts with `!` adds `commit`, `push` and `merge` (fail closed).
  - `bashpolicy.text_refusals(text: str) -> list` (no config needed; runs first on every command, all profiles):
    - `FAIL hook.bash.bypass.no-verify` for a token starting `--no-v` (ruling (3b) on text checks: anywhere in the text);
    - `FAIL hook.bash.bypass.hooks-path` for `hookspath` case-folded anywhere;
    - `FAIL hook.bash.bypass.git-config-env` for `GIT_CONFIG_` anywhere, and for `--config-env`;
    - `FAIL hook.bash.bypass.home` for a HOME or XDG_CONFIG_HOME move (controller ruling);
    - `FAIL hook.bash.decide` when the text holds `decision` (case-folded, as a substring) and `decide` or `withdraw` as a whole token, with the reason `decisions decide and withdraw come only from the human, who runs them with the ! prefix, or from the main session recording the owner's exact words (spec §7.1)`. It applies only to a call with `agent_id` (a subagent, M1), so the main session can record the owner's exact words (Q-B3plan-6 (b)). `text_refusals` therefore takes `agent_id: Optional[str]`.
  - `bashpolicy.commit_refusals(text: str, p: Policy, run_gates: Callable[[str], Result]) -> list`, applied when `effective_words` holds `commit`:
    - not `scan(text).plain`: `FAIL hook.bash.compound: git commit runs as its own command (<reason>)` (Q-r4-1 (a));
    - plain, but the program word (after `env` and its options, which are unwrapped; any `env` option other than `-i`, `-u NAME` and `NAME=V` is refused) is not `git` by basename: `FAIL hook.bash.not-git` (ruling (3b) on text checks);
    - an assignment, or an `env` operand, of `GIT_INDEX_FILE`: `FAIL hook.bash.index` (Q-r4-2 (a)); of `GIT_DIR`, `GIT_WORK_TREE`, `GIT_COMMON_DIR` or `GIT_OBJECT_DIRECTORY`: `FAIL hook.bash.target`; the hook process inheriting `GIT_INDEX_FILE`, `GIT_DIR` or `GIT_WORK_TREE`: `FAIL hook.bash.target` (controller ruling);
    - a git option before the subcommand other than `--no-pager`, `-P` and one leading `-C <dir>`: `FAIL hook.bash.global-option.<opt>` (`-c` is also a bypass); `-C <dir>` and the scanner's `cd` go through `target_root`, and its FAILs are kept;
    - the subcommand, alias-resolved, is `commit`, and its arguments hold `-n` (a short cluster, read left to right; the clusters `-m`, `-F`, `-c`, `-C`, `-t` take the rest of the cluster or the next word as their value, which is skipped): `FAIL hook.bash.bypass.n-flag`;
    - `cfg_error`: `FAIL hook.bash.config: <reason>; no commit runs until the config loads`;
    - then `unstaged_paths(root)` non-empty: `FAIL hook.bash.unstaged: <path>: tracked file has unstaged changes; stage it or stash it, so the gates read the tree being committed` for each path, before any gate runs (spec §13, F-r3-1);
    - then the gates (Q-B3plan-1 (a)): `run_gates(root)` runs `githooks.pre_commit_result(root)` only when `githooks.status_result(root, framework)` has a FAIL line for `pre-commit` (missing, foreign or stale). Each FAIL line of the result is kept, under `FAIL hook.bash.gates`.
  - `pre_bash.handle(ctx) -> Outcome`: `command` must be a `str` (else `FAIL hook.bash.input`); `deny` = `text_refusals` + `commit_refusals` (+ Task 3b.3's lists).
- An `Outcome` with no FAIL lines lets the command run; nothing is printed.

**Input-domain dimensions:**
- The outline's cases, each a test through `python3 -m gates hook PreToolUse` on a temporary repository:
  - `git add x && git commit`: refused, no gate run;
  - `git commit` joined by each of `;`, `||`, `|`, `&` and a newline: refused;
  - `git commit` inside `( )`, `{ ...; }`, `$( )`, backticks, `sh -c` / `bash -c` and `eval`: refused;
  - `GIT_INDEX_FILE=x git commit` and `env GIT_INDEX_FILE=x git commit`: refused;
  - `git commit -m "a && b"`: not compound, so the clean-tree check decides;
  - a lone `git commit` on a clean tree: the gates run;
  - a tracked file staged and then changed again: `git commit` refused with no gate run;
  - `git commit -a` with an unstaged tracked change: refused the same way;
  - a deleted tracked file not yet staged: refused;
  - a clean tree: the gates run.
- Bypass (ruling (3b) on text checks): `--no-verify`; `--no-veri`; `--no-verbose` (refused, fail closed); `-n`; `-an`; `-nm x`; `-mn` (message `n`: not a bypass); `-m -n` (message `-n`); `git push -n` (dry-run: not refused by the `-n` rule); `-c core.hooksPath=/dev/null`; `git config core.HooksPath x`; `GIT_CONFIG_COUNT=1`; `GIT_CONFIG_GLOBAL=x`; `HOME=/tmp git commit`; `export HOME=x`; `env -u HOME git commit`; `XDG_CONFIG_HOME=x`; `--no-verify` inside a quoted message (refused, ruling (3b) on text checks).
- Who runs `decide` (Q-B3plan-6 (b)): the main session (no `agent_id`: allowed); a subagent (refused).
- Commit targets (ruling (3b); fixtures seed the session store with a dispatch record and a transcript whose first prompt carries the `worktree:` line): a subagent bound to worktree W: `git -C W commit` and `cd W && git commit -m m` (pass on); a plain `git commit` from its default `cwd` in the main checkout (refused, F-B3p-15); `git -C W2 commit` for another worktree of the same repository (refused); a subagent bound to the main checkout: plain `git commit` (passes on); a subagent with no record, a record with `worktree: ""`, or the store unavailable (every git write refused); the session, no program live: `git commit` in its `cwd` (passes on), `git -C <sibling worktree> commit` (refused); the session, a program live: `git -C <worktree on the status page> merge main` and `git -C <integration worktree> commit` (pass on, F-B3p-14), `git -C <worktree not on the page> merge main` (refused); `git -C <another repository> commit` (refused); `git -C a -C b commit` (refused); a relative `-C` path joined to `cwd`; a symlinked path (resolved); a non-write (`git -C W status`, `git -C W log`: no target check); the unstaged check reading the named worktree, not `cwd`'s.
- `decide`/`withdraw`: `python3 -m gates decisions decide ...`; `python3 -I -m gates decisions withdraw ...`; `cd x; python3 -m gates decisions decide`; `sh -c 'python3 -m gates decisions decide'`; `python3 -c "from gates.tools import decisions_cli; decisions_cli.main(['decide'])"`; `decisions ask` (allowed); `grep decide notes.md` without `decision` (allowed).
- Wrappers: `echo git commit` and `grep "git commit" docs` (refused, ruling (3b) on text checks); `/usr/bin/git commit` (git); `env -i git commit` (git; `-i` allowed); `env -S 'git commit'` (refused); `command git commit`, `nohup git commit`, `xargs git commit` (not git: refused).
- Aliases: `git ci` with `alias.ci = commit` (gated); `git ci --no-verify` (refused); `alias.x = !git commit` used as `git x` (refused); an alias used inside a compound command whose text never says `commit` (refused).
- Targets: `git --git-dir=x commit`; `git --work-tree=x commit`; `GIT_DIR=x git commit`; `GIT_INDEX_FILE` in the hook's own environment.
- Config: present and valid; YAML error (`hook.bash.config` for a commit; text refusals still apply; other commands pass).
- Gates (Q-B3plan-1 (a)): git hooks installed and current; missing; foreign; stale; `run_all` failing; strict `commands.test` failing.
- `command`: absent; not a `str`; empty; very long.

- [ ] **Step 1: Write the failing tests** (`tests/test_bashpolicy.py` for the pure lists with `run_gates` recorded; `tests/test_hook_bash.py` through `tests/hookrun.py` on `helpers.make_repo` repositories, the gate runner observed by a marker file the fixture `commands.test` writes):
  ```python
  def test_add_and_commit_refused_no_gate_run():
      p = bash(root, "git add x && git commit -m m")
      assert p.returncode == 2 and "hook.bash.compound" in p.stderr and not gates_ran()
  def test_each_separator_refused():           # ; || | & newline
      assert all(bash(root, "true%sgit commit -m m" % sep).returncode == 2 for sep in ("; ", " || ", " | ", " & ", "\n"))
  def test_each_wrapper_refused():             # ( ) { ...; } $( ) backticks sh -c bash -c eval
      assert all(bash(root, t).returncode == 2 for t in WRAPPED)
  def test_index_override_refused():
      assert "hook.bash.index" in bash(root, "GIT_INDEX_FILE=x git commit -m m").stderr
      assert "hook.bash.index" in bash(root, "env GIT_INDEX_FILE=x git commit -m m").stderr
  def test_quoted_separator_reaches_clean_tree_check():
      p = bash(dirty_root, 'git commit -m "a && b"')
      assert "hook.bash.unstaged" in p.stderr and "hook.bash.compound" not in p.stderr
  def test_lone_commit_on_clean_tree_runs_gates():   # Q-B3plan-1 (a), with no git hooks installed
      assert bash(clean_root, "git commit -m m").returncode == 0 and gates_ran()
  def test_staged_then_changed_refused_before_gates():
      assert "hook.bash.unstaged: a.txt" in p.stderr and not gates_ran()
  def test_commit_a_with_unstaged_change_refused():
      assert "hook.bash.unstaged: a.txt" in bash(root, "git commit -a -m m").stderr
  def test_unstaged_deletion_refused():
      assert "hook.bash.unstaged: gone.txt" in p.stderr
  def test_bypass_forms():                     # subTest per row of the bypass dimension
      assert ("hook.bash.bypass" in bash(root, cmd).stderr) == expected
  def test_decide_and_withdraw_refused_from_subagents():   # Q-B3plan-6 (b)
      assert all("hook.bash.decide" in bash(root, c, agent_id="a1").stderr for c in DECIDE_FORMS) and bash(root, ASK, agent_id="a1").returncode == 0
      assert "hook.bash.decide" not in bash(root, DECIDE_FORMS[0]).stderr
  def test_subagent_commits_in_bound_worktree():           # F-B3p-2, F-B3p-13
      assert "hook.bash.target" not in bash(main, "git -C %s commit -m m" % wt, agent_id="a1").stderr
      assert "hook.bash.target" not in bash(main, "cd %s && git commit -m m" % wt, agent_id="a1").stderr
  def test_subagent_plain_write_in_main_checkout_refused():  # F-B3p-15
      assert "hook.bash.target" in bash(main, "git commit -m m", agent_id="a1").stderr
  def test_other_worktree_and_other_repo_refused():
      assert "hook.bash.target" in bash(main, "git -C %s commit -m m" % wt2, agent_id="a1").stderr
      assert "hook.bash.target" in bash(main, "git -C %s commit -m m" % other_repo).stderr
  def test_unbound_subagent_refused_every_write():
      assert all("hook.bash.target" in bash(main, c, agent_id="a9").stderr for c in ("git commit -m m", "git -C %s push origin x" % wt))
  def test_program_session_writes_in_program_worktrees_only():   # F-B3p-14
      assert "hook.bash.target" not in bash(main_live, "git -C %s merge main" % status_wt).stderr
      assert "hook.bash.target" not in bash(main_live, "git -C %s commit -m m" % integration_wt).stderr
      assert "hook.bash.target" in bash(main_live, "git -C %s merge main" % unlisted_wt).stderr
  def test_unstaged_check_reads_named_worktree():
      assert "hook.bash.unstaged: a.txt" in bash(main_clean, "git -C %s commit -m m" % dirty_wt, agent_id="a2").stderr
  def test_alias_resolved():
      assert "hook.bash.bypass.no-verify" in bash(aliased_root, "git ci --no-verify").stderr
  def test_healthy_git_hooks_skip_double_run():     # Q-B3plan-1 (a)
      assert bash(hooked_clean_root, "git commit -m m").returncode == 0 and not gates_ran()
  def test_config_error_refuses_commit_only():
      assert bash(broken_root, "git commit -m m").returncode == 2 and bash(broken_root, "ls").returncode == 0
  ```
- [ ] **Step 2: Run the test command; expect FAIL.**
- [ ] **Step 3: Implement** `bashpolicy` (text and commit lists), `pre_bash`, the two `gitinfo` reads and the `githooks` refactor.
- [ ] **Step 4: Run the test command on both interpreters and `python3 -m gates run_all`; expect PASS.**
- [ ] **Step 5: Commit** `feat(hooks): Bash hook: bypass block, decide and withdraw refused, gated commit`, then checkpoint.

### Task 3b.3: the Bash branch: push, the base branch, `gh`

**Files:**
- Modify: `gates/lib/bashpolicy.py`, `gates/hooks/pre_bash.py`
- Test: `tests/test_bashpolicy.py`, `tests/test_hook_bash.py`

**Owner answers applied:** owner directive (protected `main`); Q-15 (a); Q-M1; spec §4 as edited by SE-17; Q-B2plan-12 (a) (pre-push); controller rulings (3b) on refspec-less pushes, text checks, `gh api` and commit targets; Q-B3plan-1 (a), Q-B3plan-3 (a).

**Interfaces:**
- Consumes: Task 3b.2's `Policy`, `effective_words`, `githooks.pre_push_result/status_result`; `merge.agent_may_merge(cfg)` (Task P3.1); `gitinfo.current_branch/config_value/remotes/upstream_sha`.
- Produces (each list applied when its words occur; the plain-command rule and the target and global-option refusals of Task 3b.2 apply to push and merge the same way, under the ids `hook.bash.compound`, `hook.bash.target`, `hook.bash.global-option`):
  - `bashpolicy.push_refusals(text, p, run_gates) -> list` (`push` in `effective_words`):
    - `--all`, `--mirror`, `--prune`, `--delete`/`-d` naming the base, a refspec with `*`: `FAIL hook.bash.base.push`;
    - each refspec `[+]<src>[:<dst>]`: the destination (`dst`, else `src`, with `HEAD` read as the current branch) with `refs/heads/` stripped equals `base`: `FAIL hook.bash.base.push: <base> is protected; open a pull request`; `:<base>` likewise;
    - no refspec: the controller ruling's four cases;
    - then the gated push (Q-B3plan-1 (a)): `githooks.pre_push_result(root, updates)` runs only when `status_result` fails `pre-push`; `updates` are built from the refspecs (a source that does not resolve to `HEAD`'s commit fails `FAIL hook.bash.push-source: push another branch from a checkout of it` before any gate, matching Q-B2plan-12 (a)).
  - `bashpolicy.base_refusals(text, p) -> list`, when the current branch is `base`:
    - `commit`, `merge`, `pull`, `rebase`, `cherry-pick`, `revert`, `am` or `reset` as the subcommand: `FAIL hook.bash.base.checked-out: <base> is checked out; work on a branch and open a pull request`;
    - except (Q-B3plan-3 (a)) exactly `git pull --ff-only`, `git pull --ff-only <r> <base>` and `git merge --ff-only <r>/<base>`, where `<r>` is `branch.<base>.remote`.
  - `bashpolicy.ref_refusals(text, p) -> list`, for a subagent only (F-B3p-20): a bound agent may commit, push or move only its recorded branch, the `branch` of its dispatch record (`session.lookup`), never the branch checked out at the time of the command. Refused with `FAIL hook.bash.ref: this agent works only on <recorded branch>`:
    - any git write (`GIT_WRITES`) while `worktrees.bound_branch(top)` differs from the recorded branch (the worktree was switched away), and every git write when the recorded branch is `""`;
    - `git switch <other>`, `git checkout <other>` (a branch name, a commit, `-`, `--detach`), `git switch -c/-C`, `git checkout -b/-B` (switching or creating; `git checkout -- <paths>` and `git checkout <paths>` with `--` restore files and are not refused);
    - `git branch <new>` (creating), and `git branch` with `-f`, `-m`, `-M`, `-c`, `-C`, `-d` or `-D` naming any branch other than the recorded one;
    - a push refspec whose destination (after `HEAD` resolution, `refs/heads/` stripped) is not the recorded branch, or is a tag; a push with no refspec whose resolved destination is not the recorded branch;
    - `git update-ref` and `git tag` (any); a `git fetch` refspec with a local destination;
    - `git worktree add` in any form, except the group-branch rule below.
  - Group branches (programs design §4.1): only a `stream_controller` whose recorded branch is `<p>/<s>/main` may create one, and only as `git worktree add -b <p>/<s>/<g> <path> [<start>]` with `<g>` matching `[a-z0-9][a-z0-9-]*`, `<g>` not `main`, and no `-B`, `--force` or `--detach`; the new worktree is then bound to its workers at dispatch (ruling (3c), group rule). Every other branch creation by a subagent is refused. The main session is not limited by this list (the base refusals still apply).
  - Wherever the current branch is: `git branch` with `-f`, `-m`, `-M`, `-c`, `-C`, `-d` or `-D` naming `base`; `git checkout -B <base>`, `git switch -C <base>`; `git update-ref` naming `refs/heads/<base>` or `<base>`; a `git fetch` refspec whose destination is `<base>`: `FAIL hook.bash.base.update`.
  - `bashpolicy.gh_refusals(text, p) -> list` (the token `gh` with `pr merge`, `api`, `repo sync` or `alias`):
    - not plain: `FAIL hook.bash.compound`;
    - `gh pr merge`: refused unless `merge.agent_may_merge(cfg)`, and the arguments hold `--merge` (or `-m`) and `--match-head-commit <40 lowercase hex>` (also `=` form), and every other argument is one of `--delete-branch`/`-d`, `--subject`/`-t <x>`, `--body`/`-b <x>`, `--body-file`/`-F <x>`, `--repo`/`-R <x>`, or at most one PR selector. Anything else (`--admin`, `--auto`, `--squash`, `--rebase`, ...) fails `FAIL hook.bash.pr-merge: <reason>`;
    - `gh api` (ruling (3b), was Q-B3plan-4): first the endpoint is normalised (leading `/`, a host prefix, a query string and repeated `/` stripped, percent-decoded, case-folded); one matching `repos/*/*/pulls/*/merge` fails `FAIL hook.bash.gh-api: the pull-request merge endpoint is refused with every method` whatever the method (F-B3p-10). Otherwise the call is allowed only when no `-X`/`--method` other than `GET` is given, no `-f`, `-F`, `--field`, `--raw-field` or `--input` is given, and the endpoint is not `graphql`; or the endpoint is `graphql`, the query comes from `-f query=<text>` or `--raw-field query=<text>`, and the text holds neither a case-folded whole token `mutation` nor `mergePullRequest`. Anything else fails `FAIL hook.bash.gh-api`;
    - `gh repo sync`, `gh alias set`, `gh alias import`: `FAIL hook.bash.gh-sync` / `FAIL hook.bash.gh-alias` (each can update the host's base branch or hide a merge).
  - Stated limits (narrow promise): commands that reach the host other than through `git` and `gh` (for example `curl` with a token), `gh` aliases and extensions that exist before the session, git external subcommands (`git-<name>` on `PATH`), and script files or interpreters whose command text names none of the checked words (`sh c.sh`, `python3 x.py` holding a commit, a push, a merge or `decisions decide`) are not recognised; host branch protection on the base branch (owner directive) is the backstop for the host, and pull-request review for the rest.

**Input-domain dimensions:**
- Push refspecs: `origin main`; `origin HEAD:main`; `origin refs/heads/main`; `origin :main`; `origin +main`; `origin x:refs/heads/main`; `origin 'HEAD:ma''in'` (quotes joined); `--all`; `--mirror`; `--prune`; `--delete main`; `-d main`; `origin 'refs/heads/*:refs/heads/*'`; `origin feature` (passes); `origin HEAD` on a feature branch (passes); the base configured as `trunk`.
- Refspec-less push: on the base; on a branch whose upstream merge is the base; `push.default=matching`; `remote.origin.push` set; on a feature branch tracking itself (passes).
- Gated push: hooks healthy (no gate run); hooks missing (gates run); a source other than `HEAD` (refused before gates).
- Bound agent's branch (F-B3p-20): recorded `p/s/g`; `git switch p/s2/g` then `git commit` (the switch refused; and with the worktree switched by the human, the commit refused); `git checkout p/s2/g`, `git checkout -`, `git checkout --detach`, `git checkout HEAD~1` (refused); `git checkout -- a.txt` and `git checkout HEAD -- a.txt` (pass on); `git branch new` (refused); a stream controller recorded on `p/s/main`: `git worktree add -b p/s/g2 ../g2` (passes on), `git worktree add -b p/s2/g ../g` (refused), `git worktree add -B p/s/g2 ../g2` (refused), `git worktree add ../x p/s/g` (refused); an implementer running `git worktree add -b p/s/g3 ../g3` (refused); a record with `branch: ""` (every write refused).
- Bound agent's refs (`ref_refusals`): `push origin HEAD` and `push origin HEAD:<its branch>` (pass); `push origin +HEAD:<other stream's branch>`, `push origin HEAD:refs/tags/v1`, `push` with no refspec whose upstream is another branch (refused); `branch -f <other> HEAD`, `branch -D <other>`, `checkout -b x`, `switch -C x`, `update-ref refs/heads/x HEAD`, `tag v1`, `fetch origin a:b` (refused); a bound worktree on a detached HEAD (every push refused); the same commands from the main session (not refused by this list).
- Base checked out: each subcommand of the list; the three fast-forward forms (pass, Q-B3plan-3 (a)); `git pull` without `--ff-only`; `git merge --ff-only feature`; `git merge --ff-only origin/main` where `branch.main.remote` is `upstream`.
- Base update elsewhere: `git branch -f main x`; `git checkout -B main`; `git switch -C main`; `git update-ref refs/heads/main x`; `git fetch origin main:main`; `git branch -f feature x` (passes).
- `gh pr merge`: `merge.mode` host; controller with the two flags (passes); each flag missing; a 39- and 41-hex sha; uppercase hex; `--admin`; `--auto`; `--squash`; two selectors; inside a compound command.
- `gh api`: a GET (passes); `-X POST`; `--method=PUT`; `-f x=y` without `-X`; `--input f`; `graphql` with a query (passes) and a mutation; `-F query=@file`; the merge endpoint spelt `/repos/o/r/pulls/1/merge`, `repos/o/r/pulls/1/merge?x=1`, `https://api.github.com/repos/o/r/pulls/1/merge`, `repos/O/R/PULLS/1/MERGE`, `repos/o/r/pulls/1%2Fmerge`, each with GET, PUT and no method (all refused); `repos/o/r/pulls/1` GET (passes).
- Push from a worktree: `git -C <own worktree> push origin <branch>` (passes); `cd <own worktree> && git push origin HEAD:main` (refused, base push).
- `gh repo sync`; `gh alias set pm 'pr merge'`.

- [ ] **Step 1: Write the failing tests:**
  ```python
  def test_push_to_base_any_refspec_refused():  # subTest per refspec row
      assert "hook.bash.base.push" in bash(root, "git push " + spec).stderr
  def test_refspec_less_push_cases():
      assert "hook.bash.base.push" in bash(on_main, "git push").stderr and bash(on_feature, "git push").returncode == 0
  def test_commit_and_merge_on_base_refused():
      assert all("hook.bash.base.checked-out" in bash(on_main, c).stderr for c in ON_BASE)
  def test_fast_forward_update_allowed():      # Q-B3plan-3 (a)
      assert bash(on_main, "git pull --ff-only").returncode == 0 and bash(on_main, "git merge --ff-only origin/main").returncode == 0
  def test_switch_away_refused_and_commit_after_switch_refused():   # F-B3p-20
      assert "hook.bash.ref" in bash(main, "git -C %s switch p/s2/g" % wt, agent_id="a1").stderr
      git(wt, "switch", "-q", "other")            # the worktree moved outside the hook
      assert "hook.bash.ref" in bash(main, "git -C %s commit -m m" % wt, agent_id="a1").stderr
  def test_file_restore_checkout_allowed():
      assert "hook.bash.ref" not in bash(main, "git -C %s checkout -- a.txt" % wt, agent_id="a1").stderr
  def test_group_branch_only_by_stream_controller():
      assert "hook.bash.ref" not in bash(main, "git -C %s worktree add -b p/s/g2 ../g2" % stream_wt, agent_id="sc").stderr
      assert all("hook.bash.ref" in bash(main, c, agent_id=a).stderr for c, a in GROUP_REFUSALS)
  def test_bound_agent_pushes_only_its_branch():   # ref moves of other branches refused
      assert bash(main, "git -C %s push origin HEAD" % wt, agent_id="a1").returncode == 0
      assert all("hook.bash.ref" in bash(main, c % wt, agent_id="a1").stderr for c in ("git -C %s push origin +HEAD:p/s2/main", "git -C %s branch -f p/s2/g HEAD", "git -C %s tag v1", "git -C %s update-ref refs/heads/x HEAD"))
  def test_base_update_elsewhere_refused():
      assert all("hook.bash.base.update" in bash(on_feature, c).stderr for c in UPDATES)
  def test_pr_merge_policy():                  # Q-15 (a), Q-M1
      assert bash(controller_root, "gh pr merge 7 --merge --match-head-commit " + SHA40).returncode == 0
      assert "hook.bash.pr-merge" in bash(host_root, "gh pr merge 7 --merge --match-head-commit " + SHA40).stderr
      assert "hook.bash.pr-merge" in bash(controller_root, "gh pr merge 7 --merge --admin --match-head-commit " + SHA40).stderr
  def test_merge_endpoint_refused_with_every_method():   # F-B3p-10
      assert all("hook.bash.gh-api" in bash(root, "gh api %s %s" % (m, ep)).stderr for m in ("", "-X GET", "-X PUT") for ep in MERGE_SPELLINGS)
  def test_gh_api_writes_refused():            # ruling (3b) on gh api
      assert all("hook.bash.gh-api" in bash(root, c).stderr for c in API_WRITES) and bash(root, "gh api repos/o/r/pulls/1").returncode == 0
  def test_graphql_merge_refused():
      assert "hook.bash.gh-api" in bash(root, "gh api graphql -f query='mutation { mergePullRequest(input: {}) { clientMutationId } }'").stderr
  ```
- [ ] **Step 2: Run the test command; expect FAIL.**
- [ ] **Step 3: Implement** the three lists and wire them into `pre_bash.handle`.
- [ ] **Step 4: Run the test command on both interpreters and `python3 -m gates run_all`; expect PASS.** In a `mktemp -d` clone with a bare remote: one gated commit, one push of a feature branch, one refused push to `main`, run through `run_hook`; ledger the outputs.
- [ ] **Step 5: Commit** `feat(hooks): Bash hook: push and base-branch refusals, gh merge policy`, then checkpoint. **Stream `bash` end:** as stream `runtime`.

---

## Stream `tools`, sub-block 3c (branch `<program>/tools/main`)

Starts after streams `runtime` and `package` have merged into `main` and `tools` has merged `main` into its branch. Tasks 3c.1 and 3c.2 run in parallel as two groups (`<program>/tools/edit`, `<program>/tools/agent`); their file sets are disjoint.

### Task 3c.1: the Edit/Write branch

**Files:**
- Create: `gates/hooks/pre_edit.py`
- Test: `tests/test_hook_edit.py`

**Owner answers applied:** Q-16 (a); spec §4 (as edited by SE-19), §7.4 item 2; controller ruling on path matching; plan choice on session state (surfacing without a store); M5, M8.

**Interfaces:**
- Consumes: `hookio.HookContext/Outcome`; `session.locked/mark_surfaced/SessionUnavailable`; `store.Store(root, "decision", cfg).load()`; `decisions.in_force`; `config.DEFAULTS`.
- Produces:
  - `pre_edit.target(ctx) -> str`: `tool_input["file_path"]` (Edit, Write, MultiEdit) or `tool_input["notebook_path"]` (NotebookEdit), a non-empty `str`, else `FAIL hook.edit.input`; a relative path is joined to `cwd`; the result is normalised.
  - `pre_edit.under_decisions(path: str, decisions_rel: str) -> bool`: per the controller ruling, over both the lexical path and `os.path.realpath` of its deepest existing ancestor joined with the rest.
  - `handle(ctx) -> Outcome`:
    - `under_decisions` with `cfg["paths"]["decisions"]` (with `cfg_error`, `config.DEFAULTS["paths"]["decisions"]`) gives `deny = ["FAIL hook.edit.decisions: <path>: decision records are written only by python3 -m gates decisions (owner answer Q-16 (a)); answers and withdrawals come from the human"]`;
    - otherwise, for a target inside `root` (no `cfg_error`), every in-force decision with an `applies_to` glob matching the repo-relative path (`fnmatch.fnmatchcase`) that `mark_surfaced` reports new gives a `context` line `in-force <id>: <rule, else the question's first line>; landed_in <cites>`. With `SessionUnavailable`, every match is surfaced (no memory). A record load error gives a `context` line `FAIL hook.edit.decisions-load: <reason>` and no refusal (spec §4: "blocks nothing else").

**Input-domain dimensions:**
- Tool: Edit, Write, MultiEdit, NotebookEdit; a path field missing, empty, not a `str`.
- Path kind: absolute inside the decisions directory; relative from a subdirectory `cwd`; with `..` leading into it; through a symlinked parent; a case variant (`.Strict-Delivery/State/Decisions/x.yml`); the decisions directory itself; another worktree's decisions directory; a sibling `decisions-old/` (passes); `paths.decisions` configured elsewhere (the configured one is refused, the default passes); config unloadable (the default refused).
- Surfacing: no match; one match surfaced once then not again in the session; a new session surfaces again; two decisions; a superseded decision (not in force, not surfaced); a target outside `root`; the store unavailable (surfaced every time); a malformed record.

- [ ] **Step 1: Write the failing tests:**
  ```python
  def test_agent_edit_under_decisions_refused():   # Q-16 (a); subTest per path kind and tool
      assert p.returncode == 2 and "hook.edit.decisions" in p.stderr
  def test_case_variant_and_other_worktree_refused():
      assert all(edit(root, path).returncode == 2 for path in (CASE_VARIANT, OTHER_WORKTREE_RECORD))
  def test_sibling_directory_allowed():
      assert edit(root, ".strict-delivery/state/decisions-old/x.yml").returncode == 0
  def test_surfaces_once_per_session():         # spec §7.4
      assert "in-force DEC-20261101-k3f9" in ctx(first) and ctx(second) == ""
  def test_new_session_surfaces_again():
      assert "in-force DEC-20261101-k3f9" in ctx(other_session)
  def test_surfacing_blocks_nothing():
      assert p.returncode == 0
  def test_no_store_surfaces_every_time():
      assert ctx(first) and ctx(second)
  ```
- [ ] **Step 2: Run the test command; expect FAIL.**
- [ ] **Step 3: Implement `gates/hooks/pre_edit.py`.**
- [ ] **Step 4: Run the test command on both interpreters and `python3 -m gates run_all`; expect PASS.**
- [ ] **Step 5: Commit** `feat(hooks): Edit/Write hook: decision records refused to agents, in-force decisions surfaced once per session`, then checkpoint.

### Task 3c.2: the Agent branch and SubagentStop

**Files:**
- Create: `gates/hooks/pre_agent.py`, `gates/hooks/subagent_stop.py`
- Test: `tests/test_hook_agent.py`

**Owner answers applied:** block 2 cross-block note (the hook supplies `dispatcher`, `program_live` and the live counts and invents none); programs cross-block note (`programs.live_programs`, `dispatch.required`); Q-H2-Q-H5 (a); Q-B2plan-19 (a), Q-B2plan-22, Q-B2plan-23 (a); controller ruling on live counts; M1-M5.

**Interfaces:**
- Consumes: `session.*` (Task 3a.1); `hookio.*`, `transcript.*`, `worktrees.allowed/bound_branch/same_repository/worktree_list` (Task 3a.2); `gate_dispatch.check`, `dispatch.role_of/parse/required`; `programs.live_programs`; `result.run_check`.
- Produces:
  - (Specified here, created and tested by stream `runtime` in Task 3a.2.) `transcript.first_prompt(path: str, max_bytes: int = 4194304) -> Optional[str]`: the text of the first user entry of a JSONL transcript (a `str` content, or the concatenated `text` blocks of a list content), per M3's measured shape; `None` for an absent file, no user entry, a malformed line before it, or more than `max_bytes` read first.
  - `transcript.own_transcript(ctx) -> Optional[str]`: the transcript of the agent a hook fires in, per M3 (`None` when `agent_id` is absent).
  - `pre_agent.dispatcher(ctx, state) -> Optional[dict]`:
    - no `agent_id`: `{"id": "session", "depth": 0}`;
    - else `lookup(state, prompt_sha(first_prompt(own_transcript(ctx))))` gives `{"id": role, "depth": depth}`; anything missing or ambiguous gives `None`.
    - When not `None`, `live_children = live_children(state, agent_id or "session")` and `live_total = live_total(state)` are added.
  - `pre_agent.handle(ctx) -> Outcome`, holding the session lock for the whole call:
    1. `cfg_error`: `deny = ["FAIL hook.agent.config: <reason>"]` (whether the gate is required cannot be known; fail closed).
    2. `required = dispatch.required(root, cfg)`.
    3. Build the gate input: `prompt` (the tool's, which must be a `str`), `subagent_type` and `model` when present, `dispatcher` from step 4 (omitted when `None` or when the store is unavailable), `program_live = bool(programs.live_programs(root, cfg))` (omitted when that raises).
    4. When `required`: write the input to a file in a `tempfile.TemporaryDirectory()`, run `run_check("dispatch", gate_dispatch.check, ["--root", root, "--input", file])`. Any FAIL line gives `deny` = every FAIL line. A pass gives `context` = the `PASS dispatch.in-force.<id>` lines (spec §7.4 item 2).
    4a. Whatever `required` is: `pre_agent.worktree_of(ctx, prompt, dispatcher, state) -> tuple` of `(path, fails)` applies ruling (3c) on worktree binding (the `worktree:` line of `## Task`, checked against the dispatcher's allowed worktrees, `worktrees.allowed`, or the group rule; the main checkout with no program live; a worker in a live program without one refused; a controller without one bound to `""`). Its fails join `deny`.
    5. On a pass, or when not `required`: `add_dispatch(state, prompt_sha(prompt), role, dispatcher_depth + 1, agent_id or "session", path, worktrees.bound_branch(path) or "" if path else "")` (the branch is read once, here, and never re-read; F-B3p-20), where `role` is `role_of` of the `## Role` body, or `unknown` when not `required` and it does not parse. When not `required` and the dispatcher is unknown, nothing is recorded and the dispatch is allowed (no gate applies); a later dispatch from that child, if the gate is then required, fails `dispatch.input`.
    6. `SessionUnavailable` when `required`: the gate runs with `dispatcher` omitted, so it fails `dispatch.input` (controller ruling).
  - `subagent_stop.handle(ctx) -> Outcome`: `end_dispatch(state, prompt_sha(first_prompt(<agent_transcript_path>)))`; an unreadable transcript, no match or `SessionUnavailable` changes nothing; always an empty `Outcome`.

**Input-domain dimensions:**
- Dispatcher: the session (no `agent_id`); a recorded `stream_controller` at depth 1; a `controller` at depth 2; a worker (its record found; `gate_dispatch` refuses under Q-H4); an agent with no record (dispatched before the store existed); two records with the same prompt and different depths (ambiguous: omitted); a transcript missing, malformed, over `max_bytes`, whose first user entry is a list of blocks.
- Counts: zero live; at the configured `limits.max_children.<dispatcher role>` (Q-B2plan-23 (a)); at `max_concurrent`; after a SubagentStop; after an unmatched SubagentStop (unchanged); after SessionStart `startup`, `resume` or `fork` (zero each).
- Depth (Q-H5 (a), limit 3): the session dispatching a `stream_controller` (passes); a stream dispatching a `controller` (passes); a `controller` at level 2 dispatching a `controller` (refused, `dispatch.depth`); a `controller` at level 2 dispatching an `implementer` (passes); limit 6 via `CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH=5`.
- `program_live`: no integration branch; a live program; `live_programs` raising.
- `required`: light without a program (no gate; recorded); light with a live program (gated); standard; strict.
- Store: available; `CLAUDE_PLUGIN_DATA` unset (gated dispatch refused with `dispatch.input`); lock timeout.
- Tool input: `prompt` absent or not a `str`; `subagent_type` `fork`; `model` absent.
- Parallel: two dispatches in one message (two hook processes): both recorded, the second sees the first in `live_total`.
- Worktree line (ruling (3c)): absent with no program live (main checkout bound); absent for a worker in a live program (refused); absent for a `stream_controller` in a live program (bound `""`); present and on the status page, from the session (bound); a group worktree `<p>/<s>/<g>` from a stream bound to `<p>/<s>/main` (bound); another stream's worktree from that stream (refused); a relative path; two `worktree:` lines; a path of another repository; a path that does not exist; a symlink to an allowed worktree (resolved, bound).

- [ ] **Step 1: Write the failing tests** (gate inputs observed by patching `gate_dispatch.check` in the pure tests; end-to-end tests run the real gate with fixture prompt files under `--prompts` defaults pointed at the real `skills/strict-delivery/prompts/`):
  ```python
  def test_session_dispatch_context():          # block 2 cross-block note
      assert seen["dispatcher"] == {"id": "session", "depth": 0, "live_children": 0, "live_total": 0} and seen["program_live"] is False
  def test_nested_dispatcher_from_record():     # M1, M3
      assert seen["dispatcher"]["id"] == "stream_controller" and seen["dispatcher"]["depth"] == 1
  def test_unknown_dispatcher_omitted_fails_input():
      assert "dispatcher" not in seen and "FAIL dispatch.input" in p.stderr and p.returncode == 2
  def test_counts_follow_stop():
      assert live_total(after_stop) == live_total(before_stop) - 1
  def test_unmatched_stop_changes_nothing():
      assert state_after == state_before
  def test_no_store_refuses_gated_dispatch():
      assert p.returncode == 2 and "dispatch.input" in p.stderr
  def test_light_without_program_not_gated():
      assert p.returncode == 0 and gate_calls == []
  def test_light_with_live_program_gated():     # spec §12
      assert gate_calls
  def test_in_force_lines_passed_as_context():  # spec §7.4, Q-B2plan-19 (a)
      assert "PASS dispatch.in-force.DEC-20261101-k3f9" in json.loads(p.stdout)["hookSpecificOutput"]["additionalContext"]
  def test_worker_dispatch_refused():           # Q-H4
      assert "FAIL dispatch.dispatcher" in p.stderr
  def test_controller_at_depth_two_cannot_open_a_level():   # Q-H5 (a), limit 3
      assert "FAIL dispatch.depth" in p.stderr
  def test_worktree_bound_at_dispatch():        # F-B3p-13
      assert lookup(state_after, sha)[2:] == (realpath(status_wt), "p/s/main") and "hook.agent.worktree" in worker_without_line_live.stderr
  def test_stream_cannot_bind_another_streams_worktree():
      assert "hook.agent.worktree" in p.stderr
  def test_parallel_dispatches_both_counted():
      assert live_total(final) == 2
  ```
- [ ] **Step 2: Run the test command; expect FAIL.**
- [ ] **Step 3: Implement** `pre_agent.py` and `subagent_stop.py` (`transcript.py` and `worktrees.py` are on `main` from stream `runtime`).
- [ ] **Step 4: Run the test command on both interpreters and `python3 -m gates run_all`; expect PASS.**
- [ ] **Step 5: Commit** `feat(hooks): Agent hook runs gate_dispatch with dispatcher context; SubagentStop ends live records`, then checkpoint. **Stream `tools` end:** as stream `runtime`.

---

## Stream `package`, sub-block 3d (branch `<program>/package/main`)

Tasks 3d.1 and 3d.2 run in parallel as two groups; their file sets are disjoint.

### Task 3d.1: `plugin.json`, `marketplace.json`, `run_all.version`, `COMMANDS["hook"]`

**Files:**
- Create: `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, `gates/lib/plugin.py`
- Modify: `gates/run_all.py` (the `run_all.version` line), `gates/__main__.py` (`COMMANDS["hook"]`, the request of stream `runtime`)
- Test: `tests/test_plugin_manifest.py`, `tests/test_run_all.py`

**Owner answers applied:** Q-B2plan-24 (a); controller ruling on the version check; controller ruling on shared registration files; spec §3 ("name strict-delivery; depends on superpowers"), §4 ("Versioning"), §15; Q-B3plan-5 (a); the LICENSE holder (owner answer 2026-10-31).

**Interfaces:**
- Consumes: `run_all.check` (block 2); `config.load`.
- Produces:
  - `.claude-plugin/plugin.json`: `name` `strict-delivery`; `version` equal to this repository's `framework_version` (`"0.0.0"` until block 6's release); `description` (one sentence); `author.name` the LICENSE holder; `license` `MIT`; `repository` the repository URL; `dependencies` `[{"name": "superpowers", "marketplace": "claude-plugins-official"}]` (Q-B3plan-5 (a)). No component keys: `skills/`, `hooks/hooks.json` and (block 4) `commands/` load from their default locations (plugin manifest reference: "Without it, Claude Code loads the components it finds in the standard layout"; `hooks` "Loaded together with `hooks/hooks.json`"). `playbook/` is plugin content the skill points at, not a component.
  - `.claude-plugin/marketplace.json`: `name` `strict-delivery` (the install line of spec §4: `strict-delivery@strict-delivery`); `owner.name` the LICENSE holder; `plugins: [{name: strict-delivery, source: "./", version: <the same version>, description}]`; `allowCrossMarketplaceDependenciesOn` naming `claude-plugins-official`, the dependency's marketplace (Q-B3plan-5 (a)).
  - `plugin.framework_dir() -> str`: the directory holding the installed `gates` package.
  - `plugin.manifest(framework_dir: str) -> dict`: `<dir>/.claude-plugin/plugin.json`, UTF-8, `json.loads` refusing duplicate keys, an object; `GateError` naming the file otherwise.
  - `plugin.VERSION = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\Z")`.
  - `plugin.version(framework_dir: str) -> str`: the manifest's `version`, a `str` (not a subclass check by `type(...) is str`) matching `VERSION` exactly (strict `X.Y.Z`: no `v`, no pre-release or build suffix, no leading zeros, no whitespace); `GateError` naming the value otherwise.
  - `plugin.REPOSITORY = re.compile(r"https://github\.com/([A-Za-z0-9-]+)/([A-Za-z0-9._-]+?)(\.git)?\Z")`.
  - `plugin.repository_url(framework_dir: str) -> str`: the manifest's `repository`, a `str` fully matching `REPOSITORY`, returned as written; `GateError` naming the value otherwise.
  - `plugin.repository_slug(framework_dir: str) -> str`: `<owner>/<name>` from the same match (`.git` dropped); the same `GateError`. Block 4 consumes `repository_slug` (its Rq-4-1 (ii), which names this contract) and `version`; Block 4's request for `plugin.repository` is satisfied by these two names, and its draft is aligned to them by the controller.
  - `gates/__main__.py`: `COMMANDS["hook"]`, a lazy wrapper: `importlib.import_module("gates.hook").main(argv)`; an `ImportError` of `gates.hook` itself prints `FAIL hook.missing: gates.hook is not installed` to stderr and returns 2 (fail closed).
  - `run_all`: after the profile's gates, one line `PASS run_all.version` when `cfg["framework_version"] == plugin.version(framework_dir())`, else `FAIL run_all.version: framework_version <x> does not match the plugin version <y>; run /strict-delivery:upgrade`; a manifest error gives `FAIL run_all.version: <reason>` (fail closed).

**Input-domain dimensions:**
- Manifest: absent; not UTF-8; invalid JSON; a list; duplicate keys; `version` absent, `""`, `0` (an int), `"0.0.0 "`, `"v0.1.0"`, `"0.1"`, `"0.01.0"`, `"0.1.0-rc1"`, `"0.1.0+b"`, `"１.0.0"` (full-width digit); equal; different. `repository` absent, empty, with a space, `http://`, another host, a trailing `/`, `.git` (slug drops it), an owner with `_` (refused).
- `COMMANDS["hook"]`: `gates/hook.py` present (delegates, exit code passed through); absent (`hook.missing`, exit 2); `gates/hook.py` present but itself raising `ImportError` for another module (not reported as `hook.missing`; exit 2 with `FAIL hook.import: <module>`, `ImportError.name` telling the two apart).
- `marketplace.json`: entry version equal and different (test); `source` `./`; `name`s.
- `run_all`: each profile (the line comes last); `--root` naming another tree (the version compared is the target's `framework_version` against the installed plugin's); missing config (`run_all.input` first, no version line).
- Content checks: no model name, owner handle, absolute path or test filename pattern in either manifest (B's forbidden list, Task B1.1, applied by the test), except in `plugin.json`'s `repository` value, which must name the repository's owner (docs review 2, F-docs2-4); the test removes that one field before the check.

- [ ] **Step 1: Write the failing tests:**
  ```python
  # test_plugin_manifest.py
  def test_plugin_manifest_shape():
      m = json.load(open(".claude-plugin/plugin.json"))
      assert m["name"] == "strict-delivery" and set(m) <= ALLOWED_KEYS and "hooks" not in m and "skills" not in m
  def test_versions_agree():                   # controller ruling; spec §15
      assert plugin_version() == marketplace_entry()["version"] == config.load(REPO)["framework_version"]
  def test_dependency_declared():              # spec §3; Q-B3plan-5 (a)
      assert m["dependencies"] == EXPECTED_DEPENDENCY
  def test_no_forbidden_strings():             # Task B1.1's list
      assert forbidden_hits(without_repository(read(".claude-plugin/plugin.json")) + read(".claude-plugin/marketplace.json")) == []
  def test_forbidden_check_skips_only_repository():  # F-docs2-4
      assert forbidden_hits(without_repository(manifest_with_handle_in("description"))) != [] and forbidden_hits(without_repository(manifest_with_handle_in("repository"))) == []
  # test_run_all.py
  def test_version_line_passes_when_equal():   # Q-B2plan-24 (a)
      assert "PASS run_all.version" in out
  def test_version_mismatch_names_upgrade():
      assert "FAIL run_all.version:" in out and "/strict-delivery:upgrade" in out and code == 1
  def test_bad_manifest_fails_closed():        # subTest per manifest row
      assert "FAIL run_all.version:" in out
  def test_strict_semver_only():               # subTest per version row
      with self.assertRaises(GateError): plugin.version(fixture_dir(v))
  def test_repository_readers():                # F-B3p-19 (i); subTest per repository row
      assert plugin.repository_url(REPO_FW) == json.load(open(".claude-plugin/plugin.json"))["repository"]
      assert plugin.repository_slug(fixture_dir("https://github.com/o/n.git")) == "o/n"
  def test_hook_command_fails_closed_when_absent():   # gates/hook.py hidden in a copy of the package
      assert p.returncode == 2 and "hook.missing" in p.stderr
  ```
  The block-2 test `test_version_line` (`"run_all.version" not in out`, under Q-B2plan-24 (a)) is replaced by these, as Q-B2plan-24 (a) foresaw.
- [ ] **Step 2: Run the test command; expect FAIL.**
- [ ] **Step 3: Write both manifests and `gates/lib/plugin.py`; add the line to `run_all`.**
- [ ] **Step 4: Run the test command on both interpreters and `python3 -m gates run_all`; expect PASS.** If the `claude` CLI is available to the controller, `claude plugin validate .` is run once and its verdict ledgered (not a test: the suite stays standard-library and offline).
- [ ] **Step 5: Commit** `feat(plugin): plugin.json and marketplace.json; run_all checks the plugin version`, then checkpoint.

### Task 3d.2: `playbook/streams.md` and `playbook/sessions.md` (only if Task P4.3's request to stream B was not done before B's last merge)

**Files:**
- Modify: `playbook/streams.md`, `playbook/sessions.md`, `tests/test_playbook.py`
- Test: `tests/test_playbook.py`, `tests/prose_check.py` (format, unchanged)

**Owner answers applied:** programs cross-block note ("Block 3 (stream B or A): `playbook/streams.md` and `playbook/sessions.md` describe the Q-H5 default tree, the session as program controller and the PR flow"); DS-3 (B's paths pass to A after B's last merge); Q-H5 (a); Q-15 (a); Q-M4 (a); owner directive (protected `main`).

**Interfaces:**
- Consumes: B's playbook format (Task B2.2) and `tests/prose_check.py`'s forbidden list.
- Produces: in `playbook/sessions.md`, the session acting as program controller by default, the levels (stream 1, sub-controller 2, workers 3; deeper only within the configured depth), workers never dispatch; in `playbook/streams.md`, the PR flow (a PR to `main` per finished stream, the owner's approval naming PR and head sha, `gh pr merge --merge --match-head-commit`, the `MERGED` line) and that the Bash hook refuses pushes and merges to the base branch. One test per added fact (phrases asserted).

**Input-domain dimensions:**
- The two files' existing sections kept byte-for-byte outside the edited sections; the forbidden list (no model names, owner handles, paths outside the repository); the facts each asserted once.

- [ ] **Step 1: Write the failing tests** (`test_sessions_names_default_tree`, `test_streams_names_pr_flow`, each asserting the phrases).
- [ ] **Step 2: Run the test command; expect FAIL.**
- [ ] **Step 3: Edit the two files.**
- [ ] **Step 4: Run the test command on both interpreters and `python3 -m gates run_all`; expect PASS.**
- [ ] **Step 5: Commit** `docs(playbook): default agent tree and the pull-request flow`, then checkpoint. **Stream `package` end:** the standing receiver step (land every open registry request, one commit each, the controller marks each done with its sha), then as stream `runtime`; after the merge, registry requests land with A (DS-3).

### Block 3 end (session controller, after all four streams have merged)

- Every live stream branch has updated from `main` (controller ruling on enabling).
- In a `mktemp -d` clone, load the plugin with `claude --plugin-dir <clone>` and repeat M1-M9 against the real hooks; ledger the verdicts.
- Ask the owner to enable the plugin for this repository (the owner's own `/plugin marketplace add` and `/plugin install`, run by the human); ledger the enablement and the SessionStart output of the next session.
- From then on this repository's agent commits, pushes, dispatches and edits go through the hooks.
- The owner's way out when a hook fails closed on every call (a handler bug, a partial update, a corrupt session file; F-B3p-11): `!`-prefixed commands still run (M6); a corrupt session file is moved aside by starting a new session, or deleted by the human with the `rm` the FAIL line prints; the plugin is disabled with the owner's own `/plugin` command until a fix merges. The hook's FAIL message says so (Task 3a.2).

---

## Block 4 (streams `cfg4`, `rules4`, `init4`; sub-blocks 4a-4e)

Spec §17 block 4: "`init`, `doctor`, `upgrade`, templates, CI workflow template, stack detection, the no-overwrite rule and the superpowers document migration." The plan's outline adds profiles `light`, `standard` and `strict`, the claude-block and gitignore-block schemas, an answers file for non-interactive runs, tested schema migrations in `upgrade`, and the fixture repositories (node, rust, go, python, C with make, empty, monorepo). Stack detection is stream C's (Tasks C1.1-C1.2, `gates/lib/detect.py`), and block 4 only calls it.

Blocks 3-6 run as one program after the programs block. Block 4 is three streams with disjoint file ownership (table below). Each sub-block holds at most 3 tasks:
- **Stream `cfg4`, block 4a** (Tasks 4a.1-4a.3): the schema vocabulary for managed blocks and the four new or declared schema files, with `files: []` allowed; profiles and the profile merge in `config.load`; `overrides`; typed readers for `roles`, `budgets`, `block`, `rulings` and `dispatch`.
- **Stream `rules4`, block 4b** (Tasks 4b.1-4b.2): `gate_decisions` checks each override's authorising decision; `gate_dispatch` reads project roles, budget caps and `dispatch.max_prompt_chars`.
- **Stream `init4`, block 4c** (Tasks 4c.1-4c.2): managed blocks and the no-overwrite write planner; templates and their renderer.
- **Stream `init4`, block 4d** (Tasks 4d.1-4d.3): `init`; the superpowers document migration and the branch-protection offer; `doctor`.
- **Stream `init4`, block 4e** (Tasks 4e.1-4e.3): `upgrade`; the slash command files and this repository's adoption; the fixture repositories and init end to end.

**Parallelism.**
- **Before block 4c starts (session controller, ledgered): measurement M-B4-1.** Install this checkout as a plugin in a scratch Claude Code session. Run a throwaway command file whose body runs `printf '%s\n' "${CLAUDE_PLUGIN_ROOT}"`. Record whether the variable expands in a command file body, and to which directory. This mirrors block 3's M9 for `hooks.json`.
  - The (4c) interactivity ruling and Task 4e.2's command files are written to the measured form (`cd "${CLAUDE_PLUGIN_ROOT}" && python3 -m gates <cmd> --root "$OLDPWD" ...`).
  - If it does not expand, the fallback goes to the owner as one question at that point: the command files first run a helper, `python3 -c` importing `gates.lib.plugin` from the installed plugin cache path that Claude Code reports. It is not assumed.
- Block 4a (`cfg4`) and block 4c (`init4`) run in parallel from the start. They share no file and consume nothing from each other. Task 4a.2 starts only when block 3's `package` Task 3d.1 (`gates/lib/plugin.py`) is on `main` and `cfg4` has merged `main`. Until then `cfg4` runs Task 4a.1, and if 4a.1 is done it waits, ledgered.
- Block 4b (`rules4`) starts when `cfg4`'s pull request has merged into `main`. It consumes `config.load`'s typed `overrides`, `roles`, `budgets` and `dispatch` (Tasks 4a.2, 4a.3).
- Block 4d starts when `cfg4` has merged and `init4` has merged `main` into its stream branch. It consumes `profiles.load`, `plugin.version` and `plugin.repository_slug` (block 3, with request Rq-4-1 done), and the `init-answers` schema.
- Blocks 4b and 4d/4e run in parallel.
- Inside every sub-block, tasks run in order (each builds on the one before). Exceptions are named in the task.

**Branches, merges, checkpoints.** Stream branches are `<program>/<stream>/main` (programs design §4.1), cut from `main` (owner Q-M4 (a)), and pushed at every checkpoint. A finished stream opens its own pull request to `main`. The merge follows the PR flow of the programs block: final review, verifier, the owner's approval in chat naming the PR and its head sha, `gh pr merge <n> --merge --match-head-commit <sha>` (this repository's `merge.mode: controller`), the merge read back from the host, the post-merge gate run on `main`, and the `MERGED` ledger line. Checkpoints go in each stream's plan workspace, as the program plan names it. The commit gate is `python3 -m gates run_all` plus the test command on both interpreters, with a clean tree.

The owner answered this block's questions Q-B4plan-1..7 on 2026-11-02 (section "Owner answers", "Blocks 3-6 (2026-11-02)"); the task text states each answer.

**Owner answers and directives applied across the block (binding):**
- **Extras (spec §4, programs design §12a):** local git hooks default **yes**; the GitHub Actions workflow default **no**. Both can be added or removed later with `upgrade`.
- **Subagent limits (owner 2026-11-01; Block 2 cross-block notes):** `init` offers `CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH` and `CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS` and writes them into the project's `.claude/settings.json` `env` block. Task 2c.3's `dispatch.limits_of` reads the same variables. This repository already carries depth 5 and concurrency 30 (commit 1e5bdc1; programs Task P4.3 pins them).
- **`merge.mode` (owner Q-M1, Q-Pplan-14 (a)):** the key is in `config/2` (Task 2c.2), with `host | controller` and default `host`. `init` asks it and writes it.
- **Protected base (owner directive, 2026-11-01):** `main` is protected in every target repository. `init` offers to configure host branch protection on the base branch through `gh api`: a pull request required for everyone including administrators, and merge commits as the only merge method (spec §4, SE-15, as edited by SE-B4-6; owner answer Q-SE-2 (a), 2026-11-02). `host.calls` sends `"enforce_admins": true`, and `doctor` checks it. `doctor` reports what is set and what is not.
- **No-overwrite (spec §4):** `init` and `upgrade` "refuse to write any path that already exists and is not framework-managed", "list every conflict and write nothing until the owner resolves it". `upgrade`'s writes to the config and records (version pin and registered migrations) need spec edit SE-B4-4.
- **Target root (F-B4p-1):** `init`, `doctor` and `upgrade` require `--root`; they never default it from the current directory. They refuse (`<cmd>.input: <root> is the framework's own directory; pass the target repository's top level`) a root equal to `plugin.framework_dir()` or inside it, compared after `os.path.realpath`. So a command run with `cd "${CLAUDE_PLUGIN_ROOT}"` can never write into the plugin.
- **Detection only proposes (spec §4, §18; DC-1..DC-4; Q-C11-2; Q-C12-1..5; Q-C12r-1, Q-C12r-2):** `init` shows `detect.detect(root)`'s proposals, each with its `source`, and its problems. It writes only the commands the owner keeps. `test_one` is always asked and never proposed (DC-2).
- **Migration (spec §4):** existing `docs/superpowers/specs/` and `docs/superpowers/plans/` documents move with `git mv`, every tracked reference is rewritten, and this happens only on the owner's word.
- **Migrations (spec §15; Task 2a.1):** `upgrade` runs `migrations.migrate` from Block 2's registry. `store.base_errors` accepts the records it migrates (F-1).
- **Top tier (Q-B2plan-21):** `tier4` is unset by default, and `models.top_tier_fallback` defaults to `tier3`. No file in this block names a model.
- **Fail closed. No hardcoded model names, paths, owner handles or test filename patterns. Python 3.9+ standard library only. Strict YAML subset. Nothing copied from any other project.** Tests build synthetic fixtures in temp directories.

**Interfaces consumed (exact names; checked against the plan text or the code as cited):**
- Block 1: `yamlsub.load/parse/emit/YamlError`; `result.Result/GateError/gate_args/run_check/run_gate`; `config.load/DEFAULTS/CONFIG_KEYS/CONFIG_PATH` (code, `gates/lib/config.py` on `block/b1c`); `schema.load_schema/validate/validate_markdown/schemas/scan_dir/files_of/entries_of/KNOWN_KINDS/FORMATS/SchemaError/LayoutError` (code); `gate_schema.check`; `store.Store` (a missing register directory loads as empty, code `_dir_exists`); `decisions.in_force/is_resolved/superseded_ids`; `ids.id_problem`; `gitinfo.toplevel/head_sha/tracked_files/show/user_email` (code); `index.render/regenerate` (Task 1c.3); `helpers.make_repo/commit_all/write_record/GitIsolatedTestCase`; `producers.PRODUCER_MODULES`.
- Block 2: `migrations.MIGRATIONS/migrate/current_version` (2a.1); `run_all.PROFILE_GATES/BASE_GATES/check/main` (2b.1); `githooks.install(root, framework)`, `githooks status`, the shim header `# strict-delivery: generated by python3 -m gates githooks install; do not edit` (2b.2); `config/2` `limits` and `merge` (2c.2); `dispatch.ROLES/CONTROLLER_ROLES/MIN_TIERS/parse/role_of/block_errors/limits_of`, `gate_dispatch.check` and its lines (2c.3).
- Programs block: `merge.MODES/agent_may_merge` (P3.1); `programs.live_programs` (P2.1, used through `run_all`).
- Stream C: `detect.detect(root) -> Detection`, `Detection(proposals, problems)`, `Proposal(slot, command, source)`, `Problem(source, reason)`, `SLOTS`, `SOURCES` (code, `block/sc1` `gates/lib/detect.py`; `detect` raises `GateError` for a non-`str` root, a non-directory and an unsearchable directory).
- Block 3 (block-3 draft, stream `package`, Task 3d.1): `plugin.framework_dir() -> str`, `plugin.manifest(framework_dir) -> dict`, `plugin.version(framework_dir) -> str`; the `run_all.version` line (Q-B2plan-24 (a): "grows as blocks 3 and 4 land the others"); the PreToolUse Bash hook's entry `python3 -m gates hook`. Block 4 writes no plugin reader of its own.

**Requests to other streams (program rule: one owner per file; controller ruling, binding for the blocks 3-6 program).** `gates/__main__.py`, `gates/producers.py`, `gates/run_all.py` and `tests/test_run_all.py` belong to block 3's stream `package`. Block 4 adds its lines by request:
- **Rq-4-1 → `package` (before Task 4a.2; blocks 4a.2 and 4d):** (i) `plugin.version` fully matches `(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)` (X.Y.Z, no leading zeros, the same pattern as block 6's 6R.2), and raises `GateError` otherwise; (ii) add `plugin.repository_slug(framework_dir) -> str`. It returns `<owner>/<name>` from the manifest's `repository`, which must fully match `https://github\.com/([A-Za-z0-9-]+)/([A-Za-z0-9._-]+?)(\.git)?`, and raises `GateError` otherwise. Tests are in `package`'s `tests/test_plugin_manifest.py`.
- **When and to whom Rq-4-2, Rq-4-3 and Rq-4-5 land (F-B4p2-1).** Each is raised in the task named, and lands only after `init4`'s pull request has merged into `main` and the receiver has merged `main`. Until then the modules they name (`gates/tools/init.py`, `doctor.py`, `upgrade.py`, `gates/lib/managed.py`, `templates.py`) are not on `main`. A `PRODUCER_MODULES` entry for a missing module turns `check schema` red (`schema.produced_kinds`: "a module that cannot be used is a GateError"), and so does a version line that reads them. Each lands as one commit right after that merge.
  - Receiver: block 3's `package` stream if it is still live. Otherwise the residual owner, A, the session controller's stream (DS-3 pattern: a finished stream's paths pass to A).
  - Order: Rq-4-2, then Rq-4-5 (this repository's blocks), then Rq-4-3, which fails on a repository without the CLAUDE.md block.
  - Until Rq-4-2 lands, `init4` runs its tools as `python3 -m gates.tools.<name>` (each module has a `__main__` guard calling `main(sys.argv[1:])`), and its tests call `<module>.main`.
- **Rq-4-2 (raised in Tasks 4d.1, 4d.3, 4e.1):** `COMMANDS["init"]`, `["doctor"]`, `["upgrade"]` in `gates/__main__.py`, each a lazy wrapper that imports `gates.tools.<name>` inside the call (`lambda argv: importlib.import_module("gates.tools.init").main(argv)`, as `_check` already does for `GATES`), so a broken or absent module never breaks other `python3 -m gates` commands, hooks included; and `gates.tools.init` in `producers.PRODUCER_MODULES`.
- **Rq-4-3 (raised in Task 4e.1):** extend the `run_all.version` line. The CLAUDE.md block version, and when `.github/workflows/strict-delivery.yml` is framework-managed its pin, must equal `plugin.version`. A missing block fails `run_all.version: CLAUDE.md managed block missing; run /strict-delivery:init`. Tests go in `tests/test_run_all.py`. Block 4 supplies the readers (`managed.find_block`, `templates.ci_pin`).
- **Rq-4-4 → owner of `playbook/decisions.md` (Task 4a.3):** the `profile-override` row (cross-block notes).
- **Rq-4-5 (raised in Task 4e.2) → `.gitignore`'s owner (A, the shared-file owner, unless `streams.yml` names another stream): this repository's adoption.**
  - The receiver runs `python3 -m gates upgrade apply --root <its checkout> --hooks yes --ci no` (Q-B4plan-7 (a)). That inserts the CLAUDE.md block and the `.gitignore` block.
  - It then removes, by hand, the plain `.gitignore` lines that duplicate a block entry (ruling (4e)), runs `doctor --root <checkout>` (all PASS, lines ledgered), and commits `CLAUDE.md` and `.gitignore` in one commit.
  - `CLAUDE.md` therefore belongs to that receiver, not to `init4`.
  - `.gitignore` is never edited by an append. In target repositories it changes only through `init`/`upgrade`'s managed block.

**File ownership (each path has one owner stream; "modify" means the stream owns that file for this program).**

| Stream | Owns |
|---|---|
| `cfg4` | `gates/lib/schema.py`, `gates/gate_schema.py`, `gates/lib/config.py` (the `config.yml` schema keeps these keys as `any-map`; the checks are code, per the (4a) ruling), `gates/schemas/claude-block.yml`, `gates/schemas/gitignore-block.yml`, `gates/schemas/profile.yml`, `gates/schemas/init-answers.yml`, `gates/lib/profiles.py`, `profiles/`, `tests/test_schema_lib.py`, `tests/test_gate_schema.py`, `tests/test_config.py`, `tests/test_profiles.py` |
| `rules4` | `gates/gate_decisions.py`, `gates/lib/dispatch.py`, `gates/gate_dispatch.py`, `tests/test_gate_decisions.py`, `tests/test_dispatch_lib.py`, `tests/test_gate_dispatch.py` |
| `init4` | `gates/lib/managed.py`, `gates/lib/templates.py`, `gates/lib/docmove.py`, `gates/lib/host.py`, `gates/tools/init.py`, `gates/tools/doctor.py`, `gates/tools/upgrade.py`, `templates/`, `commands/`, `tests/test_managed.py`, `tests/test_templates.py`, `tests/test_init.py`, `tests/test_docmove.py`, `tests/test_host.py`, `tests/test_doctor.py`, `tests/test_upgrade.py`, `tests/test_commands.py`, `tests/repo_fixtures.py`, `tests/test_init_e2e.py` |

No block-4 stream owns `gates/__main__.py`, `gates/producers.py`, `gates/run_all.py`, `tests/test_run_all.py`, `gates/lib/plugin.py`, `gates/tools/githooks.py` or `.gitignore`. Changes to them are the requests above.

**Controller rulings (spec or plan settles each; ledgered in this form in the sub-block named; at most five per sub-block):**
- (4c) Controller ruling: the Python tool is not interactive. `init questions` prints the questions with detected proposals and defaults, `init plan --answers F` prints what would change and writes nothing, and `init apply --answers F` writes. The interactivity lives in `commands/init.md`: Claude asks the owner each question in chat, writes the answers file, shows `init plan`'s output, and runs `init apply` on the owner's word. -- Why: spec §3 puts hook and tool logic in Python, and a Bash tool call cannot answer prompts on a terminal. The outline's "answers file for non-interactive runs" then serves both routes. -- Cost if wrong: a terminal prompt loop is added later on top of the same answers model. -- Spec §4 "`/strict-delivery:init`, once per repository, interactive and idempotent"; §4 step 5 "Show the diff. Nothing is committed without the owner's word".
- (4c) Controller ruling: a path counts as framework-managed only in three cases: a managed block between the framework's markers in `CLAUDE.md` or `.gitignore`; a first-time block insertion into such a file; or a file whose first line, or second line after a `#!` line, is `# strict-delivery: generated by <tool>; do not edit`. A symlink at a target path, or at any parent of one, is a conflict. -- Why: spec §4 defines framework-managed by exactly these markers and the header. A symlinked target would write outside the tree. -- Cost if wrong: an owner replaces a symlink by hand. -- Spec §4 "Framework-managed means a managed block between the framework's begin and end markers in CLAUDE.md or `.gitignore` ... or a file carrying the framework's generated-file header".
- (4c) Controller ruling: a block's text outside the markers is never changed, removed or reordered. Inserting a block into an existing file appends it at the end. When the file does not end in a newline, one newline is appended first; that is an addition, not a change. -- Why: spec §4. -- Cost if wrong: blocks always sit at the end of the file. -- Spec §4 "inserting the block into an existing file for the first time is allowed; text outside the markers is never changed".
- (4c) Controller ruling, under spec edit SE-B4-5: the CI template names no owner handle; the framework repository comes from `plugin.repository_slug`.
  - The pin is the tag `v<plugin.version>` once that tag exists.
  - Before the first release (plugin version `0.0.0`, no tag), the pin is the full 40-hex commit sha of the installed framework, read with `git -C <framework_dir> rev-parse HEAD`. If the framework directory is not a git checkout, `ci: true` is refused (`init.answers: ci: no release tag and no framework commit to pin; answer ci: false until v0.1.0`).
  - It is never a branch: a branch moves without a commit in the target repository (the reason behind Q-B2plan-20 (a)).
  - The template fetches either form the same way: `git init`, `git fetch --depth 1 origin <ref>`, `git checkout --detach FETCH_HEAD`.
  - The template's third-party actions use the same full-sha pins as this repository's own workflow, and a test keeps the two equal.
  - -- Why: the owner directive forbids hardcoded owner handles, spec §4 asks for a pinned checkout, and no tag exists before block 6's release. -- Cost if wrong: one placeholder; pre-release adopters pin a sha that `upgrade` moves to the tag later. -- Spec §4 "checks out `superbrobenji/strict-delivery` at the pinned tag" (edited by SE-B4-5); §15 "the template CI pin".
- (4d) Controller ruling: `init` on a repository whose `.strict-delivery/config.yml` already exists asks no config questions and never rewrites the config. It writes only absent framework-managed pieces (blocks, state directories, the extras answered yes). A config that fails `config.load` stops `init` with `run /strict-delivery:doctor` and `/strict-delivery:upgrade`. -- Why: the config carries no generated-file header, so it is not framework-managed, and init is idempotent. -- Cost if wrong: re-running init cannot change answers; `upgrade` and hand edits under a decision do (programs design §7.1: config "changes need a decision"). -- Spec §4 "interactive and idempotent"; "refuse to write any path that already exists and is not framework-managed".
- (4d) Controller ruling: state directories are created on disk with no placeholder file. -- Why: git tracks no empty directory, and `Store` loads a missing register directory as empty (Task 1a.3, `Store._dir_exists`). -- Cost if wrong: a `.gitkeep` per directory, which `gate_register` would have to skip. -- Spec §4 step 3 "empty state directories".
- (4d) Controller ruling: the answers file is a data file of kind `init-answers`. Every question key is required, and unknown keys are refused. The one exception is `migrate`: it is required when tracked superpowers documents exist, and refused otherwise. There is no fallback to a default for a missing key. -- Why: a non-interactive run must not decide anything the owner did not answer, and OQ-16 refuses unknown keys. -- Cost if wrong: answers files must be complete. -- Spec §15 / Appendix A "Every data file carries `schema: <kind>/<version>`"; OQ-16.
- (4d) Controller ruling: the subagent limits go only into `.claude/settings.json`'s `env`. Config `limits` stays absent unless the owner sets it. -- Why: `dispatch.limits_of` takes the minimum of config and the Claude Code value, so the env value alone sets the effective limit, and Q-H2 keeps limits absent by default. -- Cost if wrong: one more config key written. -- Block 2 cross-block notes; Task 2c.2 "every limit is absent by default".
- (4d) Controller ruling: `doctor` writes nothing. It checks "the indexes regenerate without error" with `index.render` (in memory), never `index.regenerate`. -- Why: a check command that writes would change the tree it reports on. -- Cost if wrong: none. -- Spec §4 doctor list.
- (4e) Controller ruling: `upgrade` inserts the `.gitignore` managed block and never removes plain lines outside it. It reports, as notes, every plain line that duplicates a block entry. This repository's duplicate plain lines are removed by hand by `.gitignore`'s owner, in the Rq-4-5 commit that also inserts the block. -- Why: spec §4 forbids changing text outside the markers, and `init4` does not own `.gitignore`. The outline's "plain `.gitignore` lines becoming the managed block" is met by the Rq-4-5 commit, not by the tool. -- Cost if wrong: owners delete duplicates by hand. -- Spec §4 "text outside the markers is never changed".
- (4e) Controller ruling, under spec edit SE-B4-4 (the spec's no-overwrite sentence does not yet allow it): `upgrade` changes a non-managed data file only by registered migrations and the version pin. For `.strict-delivery/config.yml`, it replaces exactly the top-level `schema:` and `framework_version:` lines (and `profile:` under `--profile`) when the migration changes nothing else. Any other config migration is applied only when the file has no comment line; otherwise it fails `upgrade.config: migration changes more than the tag and the file has comments; migrate by hand`. -- Why: the YAML subset drops comments on re-emit, and dropping text is an overwrite. -- Cost if wrong: hand migration of a commented config, for a migration that changes more than the tag; none exists yet. -- Spec §4 "Init and upgrade never overwrite" (with SE-B4-4); §6 "canonical form so gate writes produce minimal diffs".
- (4e) Controller ruling: the seeded violations of spec §14 that need block 3's hook (an agent's `--no-verify`, an agent-run `decisions decide`, a bad dispatch through PreToolUse Agent) join Task 4e.3 only if block 3's hook entry is on `main` when 4e.3 starts. Otherwise block 6's profile end-to-end tests add them (cross-block note). The gate-only violations always land in 4e.3. -- Why: no test may run against code that is not on the branch (stream rules, "Cross-stream order"). -- Cost if wrong: three red cases arrive one block later. -- Spec §14 "Init end-to-end ... seeded violations"; §17 block 6 "profile end-to-end tests".
- (4a) Controller ruling: typing a key that `config/1` declared as `any-map` (`roles`, `budgets`, `block`, `rulings`, `dispatch`, `overrides`), once its reader lands, needs no new config version. -- Why: precedent from the answered Q-B2plan-11 (a): "`commands` gets a reader (still optional in `config/1` and `config/2`)". OQ-1 calls these keys "optional ... whose reader has not landed". -- Cost if wrong: a `config/3` with an identity migration. -- Spec §6 "A key whose reader has not landed yet is optional in `config/1`".
- (4a) Controller ruling: profiles preset only the keys whose per-profile values spec §12 gives. That is `block.max_tasks` (light none, standard 5, strict 3), plus the `top_tier_roles` default (Q-B4plan-4 (a)). `rulings.max_per_block`, `dispatch.max_prompt_chars` and `budgets` have no preset (absent: no cap). -- Why: the spec gives no value for them, and inventing a cap is not this plan's call. -- Cost if wrong: a profile file gains a key. -- Spec §12 "block size cap | none | 5 tasks | 3 tasks"; Block 2 note "`dispatch.max_prompt_chars` ... has no default".

**Cross-block notes.**
- **Block 3 (`package`):** Rq-4-1..3 above. `plugin.json` carries `version` and `repository`. `commands/` loads from its default location (block-3 3d.1: "No component keys"), so Task 4e.2 needs no manifest change.
- **Block 6:** the release site list (block-6 draft: "the CI workflow template, `superbrobenji/strict-delivery@v<v>`") is reconciled at the splice. Block 4's template renders the repository and pin at `init` and holds no literal, so it falls under block 6's "A template that renders the version at `init` ... is left off the list".
- **Block 3 or stream B (prose):** by Q-B4plan-4 (a), the default `decision_classes.owner_only` gains `profile-override`. B's `test_owner_only_matches_config_defaults` (Task B2.3) compares `config.DEFAULTS` with `playbook/decisions.md`. So Task 4a.3 raises Rq-4-4 to whoever owns `playbook/decisions.md` (B while live, else A; DS-3) to add the class row in the same merge window. Until that row lands, 4a.3 stops BLOCKED before its commit (stream rules, "Requests").
- **Block 5:** `gate_index` ("a tracked generated file fails") overlaps `doctor.generated-tracked`. Both read the same paths (`index.render`'s keys); neither re-plans the other.
- **Block 6:** the profile end-to-end tests ("the same fixture repository under each profile runs exactly the gates the profile table names", spec §14) reuse `tests/repo_fixtures.py` (Task 4e.3) by reading it, and add the hook-dependent seeded violations if 4e.3 did not (ruling above). The release script bumps nothing in block 4's files: the CI template and the CLAUDE.md block template hold no version literal, and both render the plugin version at `init`/`upgrade`. So both fall under block 6's "A template that renders the version at `init` ... is left off the list" (as the block-3 note above says for the CI template). After a release, target repositories move their pins with `upgrade`.
- **Not in block 4:** readers for `block.max_tasks` and `rulings.max_per_block` (block 6's `gate_checkpoint` in full counts tasks and ledger `Ruling` lines). Block 4 lands their shapes and the preset only.

---

## Block 4a: schema vocabulary, profiles, typed config (stream `cfg4`)

### Task 4a.1: the managed-block schema format; claude-block, gitignore-block, profile and init-answers schemas

**Files:**
- Modify: `gates/lib/schema.py` (`FORMATS` gains `managed-block`; `files` items gain `{file: <name>}`; `KNOWN_KINDS` gains `profile` and `init-answers`; `LOADER_ONLY_KINDS = ("profile", "init-answers")`; `_check_files` accepts `files: []` for exactly those kinds; `validate_managed_block`), `gates/gate_schema.py` (dispatches the new format)
- Create: `gates/schemas/claude-block.yml`, `gates/schemas/gitignore-block.yml`, `gates/schemas/profile.yml`, `gates/schemas/init-answers.yml`
- Test: `tests/test_schema_lib.py`, `tests/test_gate_schema.py`
- Spec edit SE-B4-1 (Appendix A rows for `profile` and `init-answers`), made by the session controller with the owner's approval before dispatch.

**Owner answers applied:** I7 (vocabulary is the plan's choice), OQ-16, OQ-17; spec Appendix A marker forms.

**Interfaces:**
- Consumes: `schema.load_schema/validate/files_of/entries_of/scan_dir/KNOWN_KINDS/FORMATS/SchemaError`, `gate_schema.check`, P1.1's front-matter and `lines` vocabulary (unchanged).
- Produces:
  - **The file item `{file: <name>}`.** A literal file name directly in `--root`, matching `[A-Za-z0-9._-]+` and neither `.` nor `..`. `files_of` lists it when it exists as a regular file. A symlink raises `LayoutError` (as Task 1b.1's parent check). `load_schema` refuses any other form with `SchemaError`.
  - **`format: managed-block`**, with the keys `comment: html | hash` and `files`. The markers for kind `k` at version `n`:
    - `html` begin `<!-- strict-delivery:begin schema=k/n version=V -->`; end `<!-- strict-delivery:end -->`.
    - `hash` begin `# strict-delivery:begin schema=k/n version=V`; end `# strict-delivery:end`.
    - `V` fully matches `[0-9]+\.[0-9]+\.[0-9]+`.
  - `validate_managed_block(schema: Schema, text: object) -> list`. A marker-like line is one whose text, after the comment opener (`<!-- ` or `# `), starts with `strict-delivery:begin` or `strict-delivery:end`.
    - Marker-like lines are compared whole, with no leading or trailing whitespace and no `\r`. A text with none returns `[]`, and the file is not yet a framework file (gate side: skipped).
    - Errors: `block: begin marker malformed: line <n>`; `block: more than one begin marker`; `block: no end marker`; `block: end marker before begin marker: line <n>`; `block: more than one end marker`. A well-formed begin with another kind or version gives `schema: expected <kind>/<version>, got <x>; run /strict-delivery:upgrade` (the existing message form).
    - The body is not checked here. `doctor` compares it with the render (Task 4d.3).
  - `gate_schema` checks a `managed-block` kind under the producer rule. `init` declares `claude-block` and `gitignore-block` (Task 4d.1). Line ids are as for every kind (`schema.<kind>`, `schema.<kind>.<file>`).
  - Schema files:
    - `claude-block.yml`: `comment: html`, `files: [{file: CLAUDE.md}]`, version 1.
    - `gitignore-block.yml`: `comment: hash`, `files: [{file: .gitignore}]`, version 1.
    - `profile.yml` (`format: yaml`, `files: []`, read by `profiles.load` only), fields:
      - `schema` `str`;
      - `profile` `enum [light, standard, strict]`;
      - `defaults` `map {top_tier_roles: list of str, required: false; top_tier_fallback: str, required: false}`;
      - `policy` `map {block: map {max_tasks: int, min 1, required: false}, required: false}`.
    - `init-answers.yml` (`format: yaml`, `files: []`, read by `init` only), fields. Every one is required except `migrate`, per the (4d) ruling; a slot or limit the owner leaves out is an absent key inside the map, never an absent map:
      - `schema`; `profile` `enum`;
      - `models` `any-map` (required; checked as `models.tiers` in code; the owner's answer, defaulted in the question from the profile);
      - `commands` `map {test, test_one, lint, build: str, each optional}`;
      - `git_hooks` `bool`; `ci` `bool`;
      - `merge_mode` `enum [host, controller]`;
      - `subagents` `map {depth: int min 1, concurrent: int min 1, each optional}`;
      - `protect_base` `bool`;
      - `migrate` `bool`, optional (presence is checked by `init`, ruling);
      - `base_branch` `str`.
    - **`files: []` (F-B4p-5).** Today `_check_files` raises "must be a non-empty list" (`gates/lib/schema.py:128-129`). After this task it accepts an empty list only when the schema's `kind` is in `LOADER_ONLY_KINDS`. Any other kind with `files: []` still raises `SchemaError` with the same message. Such a kind's `files_of` and `entries_of` return `[]`, so `gate_schema` checks no file of it, while its schema file still loads under `schema.kinds`. Owner: `cfg4` (it owns `schema.py`).

**Input-domain dimensions:**
- `{file: ...}` item: `CLAUDE.md`, `.gitignore`, `a/b`, `..`, `.`, empty, non-str; the target missing, a regular file, a directory, a symlink to a file, a dangling symlink, a FIFO.
- `comment`: `html`, `hash`, missing, other, non-str.
- Text: none, `""`, no marker-like line, a well-formed block, a block at line 1 and at EOF, text before and after, a CRLF file, a BOM before line 1, a marker with a leading space, a marker with a trailing space, two begins, two ends, end before begin, begin without end, a begin of another kind, version `1.2`, `1.2.3.4`, `01.2.3` (matches: no leading-zero rule), `v1.2.3`, an empty version, `schema=claude-block/0`, `/2`, the html marker in `.gitignore` (not marker-like for `hash`: not checked), a `# strict-delivery: generated by` header line (not marker-like).
- Kinds: each of the four new schema files loads and validates its fixtures. Every existing schema and fixture gives the same result as before.
- `KNOWN_KINDS`: a schema file stem outside it still fails `schema.kinds.<kind>`.
- `files`: `[]` for `profile` and `init-answers` (accepted); `[]` for `decision` and for an unknown-to-the-tuple kind (refused, "must be a non-empty list"); not a list (refused); a non-empty list for `profile` (accepted, checked as before).

- [ ] **Step 1: Write the failing tests:**
  ```python
  # test_schema_lib.py
  def test_file_item_lists_root_file():
      assert files_of(load_schema(CB), root, cfg) == ["CLAUDE.md"]
  def test_file_item_symlink_refused():
      with self.assertRaises(LayoutError): files_of(load_schema(CB), root_with_link, cfg)
  def test_file_item_bad_names_refused():      # subTests: "a/b", "..", ".", "", 3
      with self.assertRaises(SchemaError): load_schema(write_schema(files=[{"file": n}]))
  def test_managed_block_valid():
      assert validate_managed_block(CBS, "x\n<!-- strict-delivery:begin schema=claude-block/1 version=0.1.0 -->\nb\n<!-- strict-delivery:end -->\ny\n") == []
  def test_no_marker_lines_is_not_a_framework_file():
      assert validate_managed_block(CBS, "# Project\ntext\n") == []
  def test_managed_block_errors():             # subTests per malformed text above, each its exact message
      assert validate_managed_block(CBS, text) == [expected]
  def test_managed_block_old_version_names_upgrade():
      assert validate_managed_block(CBS, OLD) == ["schema: expected claude-block/1, got claude-block/0; run /strict-delivery:upgrade"]
  def test_hash_block_ignores_html_markers():
      assert validate_managed_block(GBS, "<!-- strict-delivery:end -->\n") == []
  def test_empty_files_only_for_loader_only_kinds():   # F-B4p-5
      assert load_schema(write_schema(kind="profile", files=[])).files == []
      with self.assertRaises(SchemaError): load_schema(write_schema(kind="decision", files=[]))
  def test_loader_only_kind_lists_no_files():
      assert files_of(load_schema(PROFILE_SCHEMA), root, cfg) == []
  def test_known_kinds_gain_two():
      assert {"profile", "init-answers"} <= set(KNOWN_KINDS)
  # test_gate_schema.py
  def test_claude_block_checked_once_produced():   # PRODUCER_MODULES patched to a module declaring claude-block
      assert "FAIL schema.claude-block.CLAUDE.md: block: no end marker" in out
  def test_claude_block_not_checked_before_producer():
      assert "claude-block" not in out
  def test_this_repos_schema_files_load():
      assert "PASS schema.kinds" in out
  ```
- [ ] **Step 2: Run the test command; expect FAIL.**
- [ ] **Step 3: Implement** the vocabulary, the gate dispatch and the four schema files.
- [ ] **Step 4: Run the test command on both interpreters and `python3 -m gates run_all`; expect PASS.**
- [ ] **Step 5: Commit** `feat(schema): managed-block format, root file items, claude-block, gitignore-block, profile and init-answers schemas`, then checkpoint.

### Task 4a.2: profiles, and the profile merge in `config.load`

Starts when block 3's Task 3d.1 (`gates/lib/plugin.py`) is on `main` and `cfg4` has merged `main`.

**Files:**
- Create: `gates/lib/profiles.py`, `profiles/light.yml`, `profiles/standard.yml`, `profiles/strict.yml`
- Modify: `gates/lib/config.py` (`load` merges the profile; `overrides` shape; policy keys refused at top level)
- Test: `tests/test_profiles.py`, `tests/test_config.py`
- Spec edit SE-B4-2 (§6 and §12: `overrides` shape and policy keys), before dispatch (Q-B4plan-4 (a)).

**Owner answers applied:** OQ-1, OQ-16; Q-B2plan-21, Q-B2plan-23 (a); Q-B4plan-4 (a); rulings on presets and `any-map` typing.

**Interfaces:**
- Consumes: `plugin.framework_dir` (block 3; the profiles directory is never read from `--root`, spec §3), `yamlsub.load`, `schema.load_schema/validate`, `config.load/DEFAULTS/_merge_map` (internal), `ids.id_problem`, `result.GateError`.
- Produces:
  - `profiles.PROFILES: tuple = ("light", "standard", "strict")`.
  - `profiles.load(name: str, framework: Optional[str] = None) -> dict`:
    - Reads `<framework>/profiles/<name>.yml` (default `plugin.framework_dir()`) and validates it against `profile.yml`. The `profile` field must equal `name`.
    - Returns `{"defaults": {...}, "policy": {...}}`.
    - A missing, symlinked or invalid file raises `GateError` naming it.
  - `profiles.policy_keys(preset: dict) -> frozenset` of dotted keys (`block.max_tasks`).
  - The three files (Q-B4plan-4 (a) and the ruling on presets):
    - light: `defaults: {top_tier_roles: [final_verifier, exception_reviewer]}`, `policy: {}`;
    - standard: the same `defaults`, `policy: {block: {max_tasks: 5}}`;
    - strict: the same `defaults`, `policy: {block: {max_tasks: 3}}`.
  - `config.load` (signature unchanged):
    1. Read the file, checking the keys as before.
    2. `cfg = DEFAULTS`, then the profile's `defaults` (for keys the file omits), then the file's keys.
    3. A file key that is in `policy_keys` fails `config: <key>: preset by profile <p>; change it under overrides with the authorising decision`.
    4. Then the profile's `policy`.
    5. Then each `overrides` entry's value.
    6. Then `_validate`.
  - `overrides` (config): a mapping from a dotted key to `{value: <scalar or list>, decision: <id>}`.
    - The key must be in `policy_keys`, or start with `limits.` (Q-B2plan-23 (a)), and name a key the schema knows.
    - `value` passes the same check as the direct key.
    - `decision` passes `ids.id_problem(v, cfg["ids"]["decision"])`.
    - Errors name `overrides.<key>`. Authorisation (answered, in force, class) is `gate_decisions`' job (Task 4b.1).
  - **`limits`, two routes (F-B4p-14).** A direct top-level `limits` stays allowed, unchanged from Task 2c.2, whose tests and frozen behaviour accept it; `limits` is not preset by any profile, so it is not a policy key. The `overrides` route exists for Q-B2plan-23 (a): when a playbook rule or lasting decision tightens a cap, the change goes under `overrides` with that decision, and `gate_decisions` checks the decision. When both set the same key, the override wins (step 5). A direct edit is a config change, and programs design §7.1 says "changes need a decision", but no gate checks that. This is stated, not hidden: making direct `limits` override-only would be a change to Task 2c.2, which is a plan change for the owner, not taken here.
  - The merged `cfg` keeps `cfg["overrides"]` as written, for Task 4b.1.

**Input-domain dimensions:**
- `framework` argument: absent (`plugin.framework_dir()`), a temp fixture directory, a directory without `profiles/`.
- `profiles.load`: each name, an unknown name, a file whose `profile` differs, an unknown key, `max_tasks` of 0, `True` or `"3"`.
- Merge order: a key in profile `defaults` set in the file (the file wins); a policy key set in the file (refused); an override of a policy key (applied); an override of `limits.max_children.stream_controller` (applied, Q-B2plan-23 (a)); an override of `paths.state` (refused); an override value failing its key's check; `decision` malformed; `overrides` not a mapping; an entry missing `value` or `decision`; an extra key.
- Profile absent from the framework directory: `config.load` raises naming the file (every gate fails closed).
- This repository's config: loads unchanged.

- [ ] **Step 1: Write the failing tests:**
  ```python
  def test_direct_limits_still_allowed():       # Task 2c.2 unchanged (F-B4p-14)
      assert config.load(root_with({"limits": {"max_depth": 4}}))["limits"]["max_depth"] == 4
  def test_profile_files_literal():             # spec §12 and ruling: full content, F-B2p-4 style
      assert [profiles.load(p)["policy"] for p in PROFILES] == [{}, {"block": {"max_tasks": 5}}, {"block": {"max_tasks": 3}}]
  def test_policy_key_in_file_refused():
      assert "preset by profile strict; change it under overrides" in str(ctx.exception)
  def test_override_applies_value():
      assert config.load(root_with(OVR_MAX_TASKS_4))["block"]["max_tasks"] == 4
  def test_override_of_non_policy_key_refused():
      assert "overrides.paths.state" in str(ctx.exception)
  def test_limits_override_allowed():           # Q-B2plan-23 (a)
      assert config.load(root_with(OVR_CAP))["limits"]["max_children"]["stream_controller"] == 2
  def test_profile_file_missing_fails_closed():
      assert "profiles/strict.yml" in str(ctx.exception)
  def test_this_repo_config_loads():
      assert config.load(REPO)["block"]["max_tasks"] == 3
  ```
- [ ] **Step 2: Run the test command; expect FAIL.**
- [ ] **Step 3: Implement** `profiles.py`, the three profile files and the merge.
- [ ] **Step 4: Run the test command on both interpreters and `python3 -m gates run_all`; expect PASS.**
- [ ] **Step 5: Commit** `feat(config): profiles light, standard, strict; profile merge and overrides`, then checkpoint.

### Task 4a.3: typed readers for `roles`, `budgets`, `block`, `rulings`, `dispatch`; the `profile-override` class

**Files:**
- Modify: `gates/lib/config.py` (`_validate` checks the five keys; `DEFAULTS["decision_classes"]["owner_only"]` gains `profile-override`, Q-B4plan-4 (a))
- Test: `tests/test_config.py`
- Spec edits: SE-B4-2 (§7.1 default list, Q-B4plan-4 (a)); SE-B4-3 (§10, Q-B4plan-6 (a)).
- Request: to the owner of `playbook/decisions.md` for the `profile-override` row (cross-block notes). The commit waits for it.

**Owner answers applied:** Q-B2plan-16 (a) (framework roles `plan_writer` and `plan_reviewer` are in `dispatch.ROLES`); Q-B4plan-4 (a), Q-B4plan-6 (a); ruling on `any-map` typing.

**Interfaces:**
- Consumes: `config._validate`. `config.py` imports nothing from `dispatch`: it checks the role-id shape only, and `gate_dispatch` refuses a project id that collides with `dispatch.ROLES` (Task 4b.2).
- Produces (all optional; absent means no cap and no project role):
  - `roles`: a mapping from a project role id (`[a-z][a-z0-9_]*`) to `{prompt: <normalised repo-relative path ending .md>, min_tier: tier1|tier2|tier3|tier4}` (Q-B4plan-6 (a)). Unknown keys are refused.
  - `budgets`: a mapping from a role id (framework or project) to `{tokens: int >= 1, minutes: int >= 1}`, each optional.
  - `block`: `{max_tasks: int >= 1}`; `rulings`: `{max_per_block: int >= 1}`; `dispatch`: `{max_prompt_chars: int >= 1}`.
  - Errors: `config: <dotted key>: <reason>`, each raised as `GateError` by `config.load`.

**Input-domain dimensions:**
- Each key: absent, `{}`, not a mapping, an unknown subkey.
- `roles` id: `x`, `plan_writer` (a framework role: shape passes here, and `gate_dispatch` refuses the collision), `X`, `1x`, `a-b`, `""`. `prompt`: `p.md`, `../p.md`, `/p.md`, `a//b.md`, `p.txt`, empty. `min_tier`: each of the four, `tier5`, `3`.
- Integers: `0`, `-1`, `True`, `"5"`, very large.
- `owner_only` union: a project list with and without `profile-override`, which is always present.

- [ ] **Step 1: Write the failing tests:**
  ```python
  def test_roles_shape_accepted():
      assert config.load(root_with(ROLES_OK))["roles"]["doc_writer"]["min_tier"] == "tier2"
  def test_roles_shape_refusals():              # subTests per bad value above
      with self.assertRaises(GateError): config.load(root_with(bad))
  def test_budgets_block_rulings_dispatch_ints():   # subTests 0, -1, True, "5"
      with self.assertRaises(GateError): config.load(root_with(bad))
  def test_profile_override_is_default_owner_only():   # Q-B4plan-4 (a)
      assert "profile-override" in config.load(root)["decision_classes"]["owner_only"]
  ```
- [ ] **Step 2: Run the test command; expect FAIL.**
- [ ] **Step 3: Implement** the checks and the default class.
- [ ] **Step 4: Run the test command on both interpreters and `python3 -m gates run_all`; expect PASS.** Before the commit, the requested `playbook/decisions.md` row must be on this branch (after a merge of `main`), so B's drift test passes.
- [ ] **Step 5: Commit** `feat(config): typed roles, budgets, block, rulings and dispatch keys; profile-override class`, then checkpoint.
- **Block 4a end (stream `cfg4` finished):** PR flow as above.

---

## Block 4b: override authorisation and dispatch readers (stream `rules4`; after `cfg4` merges)

### Task 4b.1: `gate_decisions` checks each override's decision

**Files:**
- Modify: `gates/gate_decisions.py`
- Test: `tests/test_gate_decisions.py`

**Owner answers applied:** Q-B4plan-4 (a); Q-decisions-1 (superseded only once the superseder is answered); spec §6 and §12 ("each naming the authorising owner decision").

**Interfaces:**
- Consumes: `config.load` (`cfg["overrides"]`), `store.Store`, `decisions.in_force/is_resolved/superseded_ids`.
- Produces: one line per `overrides` entry, `decisions.override.<key>`:
  - PASS when the named decision exists under `paths.decisions`, is answered, is in force (not superseded, not withdrawn), and is of class `profile-override` (Q-B4plan-4 (a));
  - otherwise `FAIL decisions.override.<key>: <id> <is missing | is open | is withdrawn | is superseded by <id> | has class <c>; a profile override needs class profile-override>`.
  - No line is printed when there are no overrides. The gate's other lines are unchanged.

**Input-domain dimensions:**
- The decision: missing; open; answered; withdrawn; superseded by an open superseder (still in force) or an answered one (superseded); each class (only `profile-override` passes); one decision named by two overrides.
- `overrides`: absent; empty; two entries.
- Key text in the line id: dots kept verbatim (`decisions.override.block.max_tasks`).

- [ ] **Step 1: Write the failing tests:**
  ```python
  def test_override_with_answered_decision_passes():
      assert "PASS decisions.override.block.max_tasks" in out
  def test_override_with_open_decision_fails():
      assert "FAIL decisions.override.block.max_tasks: " + DID + " is open" in out
  def test_override_superseded_by_answered_fails():
      assert "is superseded by " + NEW in out
  def test_override_wrong_class_fails():        # Q-B4plan-4 (a)
      assert "has class scope; a profile override needs class profile-override" in out
  def test_no_overrides_no_line():
      assert "decisions.override" not in out
  ```
- [ ] **Step 2-4:** run (FAIL), implement, run both interpreters and `run_all` (PASS).
- [ ] **Step 5: Commit** `feat(gates): decisions checks each config override's authorising decision`, then checkpoint.

### Task 4b.2: `gate_dispatch` reads project roles, budget caps and `dispatch.max_prompt_chars`

**Files:**
- Modify: `gates/lib/dispatch.py`, `gates/gate_dispatch.py`
- Test: `tests/test_dispatch_lib.py`, `tests/test_gate_dispatch.py`

**Owner answers applied:** spec §10 ("projects may add roles with their own prompt block"); Q-B2plan-16 (a), Q-B2plan-18 (a), Q-H4; Q-B4plan-6 (a).

**Interfaces:**
- Consumes: `dispatch.ROLES/CONTROLLER_ROLES/MIN_TIERS/DISPATCHERS/parse/role_of/block_errors/tier_of`, `config.load` (`roles`, `budgets`, `dispatch`).
- Produces:
  - `dispatch.roles_of(cfg: dict) -> tuple`: `ROLES` plus the project role ids, in sorted order.
    - A project id equal to a framework role raises `ValueError`, reported as `FAIL dispatch.role: <id>: a project role may not reuse a framework role id`.
    - Project roles are workers: they are never in `CONTROLLER_ROLES` and never a dispatcher (Q-H4), and they take the worker row of `DISPATCHERS`.
  - `dispatch.min_tier_of(role: str, cfg: dict) -> int`: `MIN_TIERS[role]` for a framework role; for a project role, the number in its `min_tier`.
  - `dispatch.prompt_path(role: str, cfg: dict, prompts_dir: str, root: str) -> str`: the framework prompt directory for a framework role (unchanged); `<root>/<roles.<id>.prompt>` for a project role. A project prompt that is missing or a symlink fails `dispatch.block`.
  - New lines in `gate_dispatch`:
    - `dispatch.budget`: FAIL when `budgets.<role>` is set and the `## Budget` tokens or minutes exceed it, naming both numbers.
    - `dispatch.size`: FAIL when `dispatch.max_prompt_chars` is set and `len(prompt)` (Python characters) exceeds it.
  - The order of every existing line is unchanged. The new lines follow `dispatch.block`.

**Input-domain dimensions:**
- Project role: absent; one; id colliding with a framework role; dispatched by `session`, a controller, and another project role (refused); prompt file missing, symlink, byte-different from `## Strict block`.
- `min_tier` against the tool model's tier: below, equal, above.
- Budget: tokens and minutes each below, equal, above the cap; the cap absent; a cap for a role not dispatched.
- Size: a prompt of `max - 1`, `max`, `max + 1` characters, with a non-ASCII character counted once.

- [ ] **Step 1: Write the failing tests:**
  ```python
  def test_project_role_dispatch_passes():
      assert "PASS dispatch.role" in out and "PASS dispatch.block" in out
  def test_project_role_collision_fails():
      assert "a project role may not reuse a framework role id" in out
  def test_project_role_cannot_dispatch():      # Q-H4
      assert "FAIL dispatch.dispatcher" in out
  def test_budget_cap_exceeded():
      assert "FAIL dispatch.budget: tokens 50001 exceeds the cap 50000" in out
  def test_prompt_size_boundary():              # max passes, max + 1 fails
      assert ("FAIL dispatch.size" in over) and ("FAIL dispatch.size" not in at)
  ```
- [ ] **Step 2-4:** run (FAIL), implement, run both interpreters and `run_all` (PASS).
- [ ] **Step 5: Commit** `feat(gates): dispatch reads project roles, budget caps and the prompt size cap`, then checkpoint.
- **Block 4b end (stream `rules4` finished):** PR flow.

---

## Block 4c: managed blocks, write planner, templates (stream `init4`; parallel with 4a)

### Task 4c.1: `managed.py`: markers, the generated header, the no-overwrite write planner

**Files:**
- Create: `gates/lib/managed.py`
- Test: `tests/test_managed.py`

**Owner answers applied:** spec §4 no-overwrite; Appendix A marker forms; rulings (4c) on framework-managed paths and text outside markers.

**Interfaces:**
- Consumes: `result.GateError`; nothing from `cfg4`. The marker text is the Appendix A form, which Task 4a.1's schema checks too. A test written after 4a.1 is on this branch asserts that `put_block` output passes `validate_managed_block`; until then it is skipped with the reason `managed-block schema format not on this branch`, and the checkpoint line says so.
- Produces:
  - `HTML = "html"`, `HASH = "hash"`; `begin_marker(style: str, kind: str, version: str) -> str`; `end_marker(style: str) -> str`.
  - `@dataclass(frozen=True) Block(begin: int, end: int, kind: str, version: str, body: str)`: 0-based line indexes of the two marker lines, and the text between them.
  - `find_block(text: str, style: str) -> Optional[Block]`: `None` when the text has no marker-like line. `ManagedError` (a `GateError`) is raised on every malformed case of Task 4a.1's list, with the same reason text.
  - `put_block(text: Optional[str], style: str, kind: str, version: str, body: str) -> str`:
    - `None` gives a new text holding only the block.
    - A text with no block gets the block appended (ruling).
    - A text with one block gets that block's marker and body replaced.
    - The text outside the markers is byte-identical in every case.
    - `body` must end in `\n` and hold no marker-like line, else `ManagedError`.
  - `HEADER_RE`: `# strict-delivery: generated by [^;\n]+; do not edit`. `is_generated(text: str) -> bool`: line 1 matches, or line 1 starts with `#!` and line 2 matches.
  - `@dataclass(frozen=True) Write(path: str, text: str, kind: str)`, where `kind` is `file` (whole file), `claude-block` or `gitignore-block` (block insertion; `text` is then the block body, and the version is passed to `plan`).
  - `plan(root: str, writes: list, version: str) -> tuple` of `(actions: list, conflicts: list)`:
    - An action is `(path, new_text)`.
    - A conflict is `"<path>: <reason>"`: `exists and is not framework-managed`; `is a symlink`; `parent <p> is not a directory`; `managed block malformed: <reason>`; `two writes name the same path`.
    - An action whose new text equals the file's text is dropped.
  - `apply(root: str, actions: list) -> list` of written paths. Each file goes to a temporary file in its directory, then `os.replace`. Parent directories are created. `apply` refuses (`GateError`) when it is called with an action that `plan` would now report as a conflict (re-checked at apply time).

**Input-domain dimensions:**
- `find_block`/`put_block`: every Task 4a.1 text row; `text` of `None`, `""`, a file without a final newline, CRLF outside the block (kept), a block at EOF without a final newline after the end marker; a body without a final newline; a body holding a marker-like line; a version change only; a body change only.
- `is_generated`: header on line 1; on line 2 after `#!/bin/sh`; on line 2 without a shebang (false); on line 3; with a trailing space (false); with `do not edit.` (false); an empty file.
- `plan`: path absent; a regular file with the header; one without; a symlink (to a file, dangling); a parent that is a file; a parent that is a symlink; a `CLAUDE.md` with no block, with a block, with a malformed block; two writes to one path; an unchanged rewrite (dropped).
- `apply`: a read-only directory (`GateError` naming the path; files written before it stay, and the report lists them); the path replaced by a symlink between `plan` and `apply` (refused).

- [ ] **Step 1: Write the failing tests:**
  ```python
  def test_put_block_appends_and_keeps_outside():
      new = put_block("a\nb", HTML, "claude-block", "0.1.0", "x\n")
      assert new.startswith("a\nb\n") and new.endswith("<!-- strict-delivery:end -->\n")
  def test_put_block_replaces_only_inside():
      assert outside(put_block(WITH_BLOCK, HTML, "claude-block", "0.2.0", "y\n")) == outside(WITH_BLOCK)
  def test_plan_refuses_foreign_file():
      assert plan(root, [Write("x.yml", "a\n", "file")], "0.1.0")[1] == ["x.yml: exists and is not framework-managed"]
  def test_plan_rewrites_generated_file():
      assert plan(root, [Write("w.yml", NEW, "file")], "0.1.0")[0] == [("w.yml", NEW)]
  def test_plan_symlink_conflict():
      assert plan(root, writes, "0.1.0")[1] == ["CLAUDE.md: is a symlink"]
  def test_is_generated_rows():                 # subTests per row above
      assert is_generated(text) is expected
  def test_put_block_output_passes_schema():    # skipped until Task 4a.1 is on the branch (named reason)
      assert validate_managed_block(load_schema(CB_SCHEMA), put_block(None, HTML, "claude-block", "0.1.0", "x\n")) == []
  ```
- [ ] **Step 2-4:** run (FAIL), implement, run both interpreters and `run_all` (PASS).
- [ ] **Step 5: Commit** `feat(lib): managed blocks, generated-file header, no-overwrite write planner`, then checkpoint.

### Task 4c.2: templates and their renderer

**Files:**
- Create: `gates/lib/templates.py`, `templates/claude-block.md`, `templates/gitignore-block.txt`, `templates/ci/strict-delivery.yml`
- Test: `tests/test_templates.py`

**Owner answers applied:** spec §3 (precedence; the managed block names document locations), §4 (CI), §5 (ignored files), §8 ("The CLAUDE.md managed block points at it"); Q-B2plan-20 (a); SE-17 (the pull-request job); ruling (4c) on the CI template.

**Interfaces:**
- Consumes: `yamlsub.load` (to parse the rendered workflow in tests only).
- Produces:
  - `templates.TEMPLATES_DIR`: `templates/` beside the `gates` package.
  - `render(name: str, ctx: dict) -> str`:
    - Each `{{key}}` is replaced by `ctx[key]` (a `str`).
    - A placeholder missing from `ctx`, a `ctx` key no placeholder uses, a non-`str` value, or a value holding a newline raises `GateError`.
    - The output always ends in `\n`.
  - `claude_block_body(cfg: dict) -> str`, rendering `claude-block.md`:
    - It names the document locations from `cfg["paths"]` (`specs`, `plans`, `reviews`, `architecture`, `playbooks`) and the base playbook in the plugin.
    - It states the precedence of spec §3 and that superpowers' default save paths are overridden.
    - It tells Claude to invoke the strict-delivery skill.
    - It names no model, no owner handle, and no path that is not taken from `cfg`.
  - `gitignore_block_body(cfg: dict) -> str`: one line each for `<paths.decisions>/index.yml`, `<paths.decisions>/in-force.md`, `<paths.findings>/index.yml`, `<paths.index>`, `<paths.receipts>/`, in that order. These are the files `index.render` returns (Task 1c.3) plus the receipts directory (spec §5).
  - `ci_pin(version: str, framework_sha: Optional[str]) -> str`, per the (4c) ruling:
    - `v<version>` when `version != "0.0.0"`;
    - else `framework_sha`, which must be 40 lowercase hex;
    - else `GateError("no release tag and no framework commit to pin")`.
  - `pin_of(text: str) -> Optional[str]`: the ref in a rendered workflow's fetch line, for `doctor` and Rq-4-3.
  - `ci_workflow(cfg: dict, pin: str, repository: str) -> str`, rendering `ci/strict-delivery.yml`:
    - line 1 is `# strict-delivery: generated by python3 -m gates init; do not edit`;
    - `on: push, pull_request`;
    - one job on the same runner label and the same `actions/checkout` and `actions/setup-python` full-sha pins as this repository's `.github/workflows/strict-delivery.yml`;
    - Python `3.9`;
    - project checkout with `fetch-depth: 0`;
    - the framework fetched into `"$RUNNER_TEMP/strict-delivery"` with `git init`, `git fetch --depth 1 https://github.com/<repository> <pin>`, `git checkout --detach FETCH_HEAD` (the same lines for a tag or a sha);
    - `python3 -m gates index --root "$GITHUB_WORKSPACE"` and `python3 -m gates run_all --root "$GITHUB_WORKSPACE" --base origin/<base>`, run from that clone, with `<base>` from the event as in Task 2b.3;
    - on `pull_request`, the steps of this repository's pull-request job of Task P3.1, and for a cleanup head `check cleanup` (SE-17).

**Input-domain dimensions:**
- `render`: every placeholder supplied; one missing; one extra; a value with `\n`; a non-`str` value; `{{` with no closing; a key with a space; an empty template.
- `cfg["paths"]`: defaults; every path changed; a path with a space (rendered verbatim; YAML-quoted in the workflow).
- `ci_pin`: `0.1.0` (tag); `0.0.0` with a 40-hex sha; `0.0.0` with `None`, a 39-hex or an uppercase sha (refused). `repository`: `o/n`. `pin_of`: a tag, a sha, no fetch line, two fetch lines (`None`).
- The rendered workflow: `yamlsub` cannot parse GitHub's YAML features, so tests check its lines.
- Drift against this repository's workflow: the `uses:` shas and runner label equal; a changed pin in either file fails the test.

- [ ] **Step 1: Write the failing tests:**
  ```python
  def test_render_refuses_missing_and_extra():
      with self.assertRaises(GateError): render("claude-block.md", {})
  def test_gitignore_body_from_paths():
      assert gitignore_block_body(DEFAULT_CFG).splitlines() == [
          ".strict-delivery/state/decisions/index.yml", ".strict-delivery/state/decisions/in-force.md",
          ".strict-delivery/state/findings/index.yml", "docs/strict-delivery/INDEX.md", ".strict-delivery/receipts/"]
  def test_gitignore_body_matches_index_render():   # every index.render key is ignored
      assert set(index.render(root, cfg)) <= set(gitignore_block_body(cfg).splitlines())
  def test_ci_pins_tag_and_repository():
      assert "git fetch --depth 1 https://github.com/o/n v0.1.0" in ci_workflow(cfg, ci_pin("0.1.0", None), "o/n")
  def test_ci_pin_before_release_is_sha_never_branch():
      assert ci_pin("0.0.0", SHA40) == SHA40
      with self.assertRaises(GateError): ci_pin("0.0.0", None)
  def test_pin_of_round_trip():
      assert pin_of(ci_workflow(cfg, SHA40, "o/n")) == SHA40
  def test_ci_actions_match_this_repo_workflow():   # Q-B2plan-20 (a)
      assert uses(ci_workflow(cfg, "v0.1.0", "o/n")) <= uses(read(".github/workflows/strict-delivery.yml"))
  def test_ci_header_is_generated():
      assert is_generated(ci_workflow(cfg, "v0.1.0", "o/n"))
  def test_templates_name_no_model_or_handle():     # every tier model in DEFAULTS, and the plugin repository owner
      assert not any(m in text for m in MODEL_IDS + [OWNER_FROM_GIT_REMOTE] for text in RENDERED)
  ```
- [ ] **Step 2-4:** run (FAIL), implement, run both interpreters and `run_all` (PASS).
- [ ] **Step 5: Commit** `feat(templates): CLAUDE.md and .gitignore managed blocks, CI workflow template pinned to a tag`, then checkpoint.
- Block 4c ends without a PR: stream `init4` continues into 4d on the same stream branch, after merging `main` once `cfg4` has merged (DS-2 form: a merge of `main`, never a rebase).

---

## Block 4d: `init`, migration and protection, `doctor` (stream `init4`; after `cfg4` merges)

### Task 4d.1: `init questions | plan | apply`

**Files:**
- Create: `gates/tools/init.py`
- Requests: Rq-4-2 (`COMMANDS["init"]`, `producers` entry `gates.tools.init`), landed after `init4`'s PR merges (receiver per "When and to whom").
- Test: `tests/test_init.py`

**Owner answers applied:** spec §4 steps 1-3 and 5; extras defaults; subagent limits; Q-M1; DC-2; rulings (4c, 4d); Q-B4plan-1 (a), Q-B4plan-7 (a).

**Interfaces:**
- Consumes: `detect.detect/Detection/Proposal/Problem/SLOTS`; `profiles.load/PROFILES`; `plugin.framework_dir/version/repository` (block 3, Rq-4-1); `migrations.current_version`; `schema.load_schema/validate`; `yamlsub.load/emit`; `config.DEFAULTS/CONFIG_PATH`; `managed.plan/apply/Write`; `templates.claude_block_body/gitignore_block_body/ci_pin/ci_workflow`; `githooks.install(root, framework)`; `merge.MODES`; `gitinfo.toplevel/hooks_dir`.
- Produces:
  - `PRODUCES = ("claude-block", "gitignore-block")`.
  - `main(argv: list) -> int` for `python3 -m gates init <questions|plan|apply> --root R [--answers F] [--json]`.
    - `--root` is required; a missing `--root` exits 2 with usage.
    - The root must be a git top level (`gitinfo.toplevel(root) == realpath(root)`), else `init.input`.
    - A root equal to or inside `realpath(plugin.framework_dir())` is refused with `init.input: <root> is the framework's own directory; pass the target repository's top level` (F-B4p-1).
  - **Linked worktree root (F-B4p-13).** Files are written in the worktree as for any root. The hook shims go into `gitinfo.hooks_dir(root)`, which for a linked worktree is the shared common git directory. So `plan` prints a note: `hooks go to <dir>, shared by every worktree of this repository`. `apply` installs them there; this is git's own layout (Block 2's install-timing ruling for this repository rests on the same fact). A submodule's hooks directory is its own `.git/modules/<name>/hooks`, which gets no note.
  - `questions(root: str) -> dict`, printed as JSON with `--json`, else as text. It writes nothing:
    - `proposals`: `[{slot, command, source}]` in `detect` order;
    - `problems`: `[{source, reason}]`;
    - `ask_test_one: true`;
    - `profiles`, with `default_profile: "standard"`;
    - `models`: `DEFAULTS["models"]["tiers"]`;
    - `defaults: {git_hooks: true, ci: false, merge_mode: "host", protect_base: true}`;
    - `subagents: {current: <the env values in .claude/settings.json, or null>}`;
    - `superpowers_docs`: the tracked files Task 4d.2 would move (empty until 4d.2 lands);
    - `initialised`: whether the config exists (ruling).
  - `load_answers(path: str) -> dict`: `init-answers/1`, every key required by the ruling, and `models` checked as `models.tiers`. An error is `init.answers: <dotted key>: <reason>`.
  - `plan_init(root: str, answers: dict) -> InitPlan` with `writes`, `conflicts`, `settings` (the JSON change or conflict), `moves` and `host_calls` (both empty until 4d.2), and `notes`.
    - `.strict-delivery/config.yml`, only when absent:
      - `schema: config/<current_version("config")>`;
      - `framework_version: <plugin.version>`;
      - `profile`;
      - `commands` with only the answered slots;
      - `models: {tiers: ...}` only when it differs from the default;
      - `base_branch` only when not `main`;
      - `merge: {mode: <merge_mode>}`.
    - The state directories of `cfg["paths"]` (`decisions`, `findings`, `claims`, `plan_state`, `programs`, `playbooks`), as mkdir actions.
    - The CLAUDE.md block and the `.gitignore` block (`Write(..., "claude-block" | "gitignore-block")`).
    - The CI workflow when `ci` is true (`.github/workflows/strict-delivery.yml`), with `ci_pin(plugin.version, <framework sha or None>)` per the (4c) ruling. A refused pin is `init.answers: ci: ...`.
    - The git hook shims when `git_hooks` is true, through `githooks.install` at apply time. Its own conflicts (foreign hook, `core.hooksPath`; Task 2b.2 ruling) are gathered into `conflicts` by a dry check of `githooks status`.
    - `.claude/settings.json` per Q-B4plan-1 (a):
      - absent: create `{"env": {...}}` with the answered `subagents` keys as decimal strings (`json.dumps(indent=2, sort_keys=True) + "\n"`);
      - present and already holding equal values: nothing;
      - present otherwise: a conflict naming the exact JSON members to add.
      - `subagents: {}` means no settings change.
  - `plan` prints the conflicts and exits 1, or prints each action as a unified diff (`difflib`, `a/` and `b/` paths), the mkdirs, the hook files and the settings change, then exits 0. It writes nothing.
  - `apply` re-plans. Any conflict prints all of them, writes nothing and exits 1. Otherwise it writes in this order: config, directories, blocks, CI, settings, hooks. It then prints `git -C root status --porcelain --untracked-files=all` and exits 0. It never runs `git add` (except the moves of 4d.2), `git commit` or `git push`.

**Input-domain dimensions:**
- Root: `--root` missing (exit 2); not a repository; a subdirectory of one; a linked worktree top level (files written in the worktree; hooks note naming the shared directory); a bare repository (`init.input`); the framework directory itself; a directory inside it; a symlink resolving into it (all refused, nothing written).
- CI pin: plugin version `0.1.0` (tag); `0.0.0` with the framework a git checkout (sha); `0.0.0` with the framework not a git checkout (`ci: true` refused).
- Answers file: missing; a directory; a YAML error; each required key missing; an unknown key; `profile` unknown; `commands.test_one` without `{id}` (accepted: the template's contents are the project's, spec §13a); a command with a newline (refused: one shell string per slot, `config` reader); `subagents.depth` 0, `True`, `"5"`; `merge_mode` other; `migrate` present with no superpowers documents (refused).
- Detection: no proposals; proposals from several sources; a `Problem` (shown, never fatal); `detect` raising `GateError` (`init.input`).
- Existing paths: none; a foreign `.github/workflows/strict-delivery.yml`; a managed one; `CLAUDE.md` absent, with project text, with a block; `.gitignore` absent, with plain lines; a foreign `pre-commit` hook; `core.hooksPath` set; `.claude/settings.json` absent, with other keys, with equal env values, with different env values, invalid JSON (a conflict naming the parse error), a symlink.
- Initialised repository (ruling): config present and valid (no config write; second run prints no actions); config present and invalid (stops).
- Idempotence: `apply` twice; the second `plan` prints no action.
- Output: `--json` and text forms; exit codes 0/1/2.

- [ ] **Step 1: Write the failing tests:**
  ```python
  def test_questions_lists_detect_proposals_in_order():
      assert q["proposals"] == [{"slot": p.slot, "command": p.command, "source": p.source} for p in detect(root).proposals]
  def test_questions_never_proposes_test_one():  # DC-2
      assert q["ask_test_one"] is True and all(p["slot"] != "test_one" for p in q["proposals"])
  def test_extras_defaults():                    # spec §4
      assert q["defaults"]["git_hooks"] is True and q["defaults"]["ci"] is False
  def test_plan_writes_nothing():
      assert snapshot(root) == before and code == 0
  def test_apply_writes_config_blocks_and_hooks():
      assert config.load(root)["merge"]["mode"] == "controller" and find_block(read("CLAUDE.md"), HTML).kind == "claude-block"
  def test_conflict_writes_nothing():            # foreign workflow + ci: true
      assert code == 1 and ".github/workflows/strict-delivery.yml: exists and is not framework-managed" in out and snapshot(root) == before
  def test_settings_created_with_env():          # Q-B4plan-1 (a)
      assert json.loads(read(".claude/settings.json")) == {"env": {"CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH": "5", "CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS": "30"}}
  def test_existing_settings_never_rewritten():  # different values: conflict, file byte-identical
      assert code == 1 and read(".claude/settings.json") == ORIGINAL
  def test_second_apply_is_noop():
      assert plan_out_second == "no changes\n"
  def test_never_commits():
      assert git(root, "rev-list", "--count", "HEAD") == before_count
  def test_written_config_passes_gate_schema():
      assert "PASS schema.config" in out
  def test_root_required():                      # F-B4p-1
      assert main(["apply", "--answers", ans]) == 2
  def test_framework_dir_refused_as_root():      # root == framework dir, and a subdirectory of it
      assert "is the framework's own directory" in out and snapshot(fw) == before
  def test_linked_worktree_hooks_note():
      assert "shared by every worktree" in plan_out
  ```
- [ ] **Step 2-4:** run (FAIL), implement, run both interpreters and `run_all` (PASS).
- [ ] **Step 5: Commit** `feat(tools): init questions, plan and apply with the no-overwrite rule`, then checkpoint.

### Task 4d.2: superpowers document migration; the branch-protection offer

**Files:**
- Create: `gates/lib/docmove.py`, `gates/lib/host.py`
- Modify: `gates/tools/init.py` (`moves`, `host_calls`, `questions.superpowers_docs`, `apply` runs both on the owner's answers)
- Test: `tests/test_docmove.py`, `tests/test_host.py`, `tests/test_init.py`

**Owner answers applied:** spec §4 (migration); owner directive (protected base); controller ruling P3 (merge commits only); Q-B4plan-3 (a), Q-B4plan-5 (a); SE-B4-6 (admins enforced).

**Interfaces:**
- Consumes: `gitinfo.tracked_files/toplevel`, `config.load` (`paths.specs`, `paths.plans`, `base_branch`), `managed.plan` (a target is checked the same way).
- Produces:
  - `docmove.SOURCES = ("docs/superpowers/specs/", "docs/superpowers/plans/")`, the spec §4 names.
  - `docmove.plan_moves(root: str, cfg: dict) -> tuple` of `(moves, conflicts, notes)`:
    - A move is `(src, dst)`: every tracked file under a source, mapped to `<paths.specs>/` or `<paths.plans>/` with its sub-path kept.
    - A `dst` that exists, tracked or not, is a conflict (spec §4).
    - An untracked file under a source is a note, not moved (`git mv` moves tracked files).
  - `docmove.rewrites(root: str, moves: list) -> tuple` of `(changes, notes)` (Q-B4plan-5 (a)):
    - For every tracked file that decodes as UTF-8 and holds no NUL, each occurrence of a moved `src`, or of a source directory prefix, is replaced by its target.
    - An occurrence counts only when the character before it and the character after it are outside `[A-Za-z0-9._/-]`, or are the text's ends. Longer paths are replaced first.
    - A change is `(path, new_text)`. Each other occurrence of a moved file's base name is a note `path:line: mentions <name>; not rewritten`.
    - Moved files are rewritten at their new paths.
  - `docmove.apply_moves(root: str, moves: list, changes: list) -> None`: creates target parents, runs `git -C root mv -- <src> <dst>` per move with the test-isolated git environment, then writes the changes. A failed `git mv` raises `GateError` naming it; the moves made before it stay staged, and the report lists them.
  - `host.github_remote(root: str) -> Optional[str]`: the `owner/name` of the `origin` remote URL when its host is `github.com` (`https://github.com/o/n(.git)?` or `git@github.com:o/n(.git)?`), else `None`.
  - `host.read_state(root: str, slug: str, branch: str) -> dict` of `{protected: bool, pr_required: bool, admins: bool, merge_commit: bool, squash: bool, rebase: bool}`:
    - It uses `gh api repos/<slug>/branches/<branch>/protection` (HTTP 404 means unprotected) and `gh api repos/<slug>`.
    - A missing `gh` executable, an unauthenticated `gh`, or any other failure raises `HostError` (a `GateError`) naming the command and its stderr's first line.
  - `host.calls(state: dict, slug: str, branch: str) -> list` of argv lists (Q-B4plan-3 (a)):
    - When `protected` is false: `gh api -X PUT repos/<slug>/branches/<branch>/protection --input -` with body `{"required_status_checks": null, "enforce_admins": true, "required_pull_request_reviews": {"required_approving_review_count": 0}, "restrictions": null}`. The `admins` setting is wanted (SE-B4-6).
    - When the merge methods differ from merge-commit only: `gh api -X PATCH repos/<slug> -F allow_merge_commit=true -F allow_squash_merge=false -F allow_rebase_merge=false`.
    - When `protected` is true and a wanted setting is missing: no call, and a note naming each missing setting.
  - `init`:
    - `questions.superpowers_docs` lists the moves.
    - `plan` prints the moves, the rewrites as diffs, the notes and the host calls verbatim.
    - `apply` runs `apply_moves` only when `migrate` is true, and the host calls only when `protect_base` is true. Both run after the file writes.
    - With `protect_base` true and no GitHub remote: a note, no call, exit 0.
    - With `protect_base` true and `HostError`: `FAIL init.protection: <reason>`, exit 1 after the file writes, which stay (the report says so).

**Input-domain dimensions:**
- Sources: absent; empty; one spec; nested sub-paths; an untracked file; a file with a space or non-ASCII name; a target that exists (tracked, untracked, a directory).
- References: the exact path; the path followed by `#anchor`, `)`, `:12`, a backtick, EOL; preceded by `/`, `.`, a letter (not replaced); `docs/superpowers/specs/a.md` inside `xdocs/superpowers/...` (not replaced); a path that is a prefix of another moved path (longest first); a relative link `../plans/a.md` (a note only); a binary file; a non-UTF-8 file (skipped, noted); the moved file referring to itself.
- History: `git log --follow --format=%H <dst>` holds the original commit after the move is committed (test commits it).
- `migrate`: false (nothing moved, no diff); true.
- Remote: none; `origin` on GitHub (https, ssh); another host; another remote name only.
- Host state (fake `gh` on `PATH`, a script the test writes into its own temp directory, recording argv and stdin): unprotected; protected with everything; protected missing admins; methods all allowed; `gh` missing; `gh` exits 1 (unauthenticated); 404 then success; malformed JSON.

- [ ] **Step 1: Write the failing tests:**
  ```python
  def test_moves_keep_subpaths():
      assert plan_moves(root, cfg)[0] == [("docs/superpowers/plans/x/p.md", "docs/strict-delivery/plans/x/p.md")]
  def test_target_exists_conflict_and_nothing_moved():
      assert conflicts == ["docs/strict-delivery/specs/a.md: exists"] and snapshot(root) == before
  def test_reference_rewritten_at_path_boundary():   # Q-B4plan-5 (a)
      assert new_text == "see `docs/strict-delivery/specs/a.md#x` and xdocs/superpowers/specs/a.md\n"
  def test_relative_link_is_note_only():
      assert any("mentions a.md; not rewritten" in n for n in notes)
  def test_history_follows_move():
      assert ORIGINAL_SHA in git(root, "log", "--follow", "--format=%H", "--", "docs/strict-delivery/specs/a.md").split()
  def test_migration_only_on_word():
      assert os.path.exists(join(root, "docs/superpowers/specs/a.md"))   # answers migrate: false
  def test_protection_put_only_when_unprotected():  # Q-B4plan-3 (a)
      assert calls(UNPROTECTED, "o/n", "main")[0][:4] == ["gh", "api", "-X", "PUT"] and calls(PROTECTED_NO_PR_RULE, "o/n", "main") == []
  def test_merge_methods_patch():
      assert ["-F", "allow_squash_merge=false"] == patch_args[6:8]
  def test_gh_missing_fails_closed():
      assert "FAIL init.protection:" in out and code == 1
  ```
- [ ] **Step 2-4:** run (FAIL), implement, run both interpreters and `run_all` (PASS).
- [ ] **Step 5: Commit** `feat(tools): init migrates superpowers documents with git mv and offers base-branch protection`, then checkpoint.

### Task 4d.3: `doctor`

**Files:**
- Create: `gates/tools/doctor.py`
- Modify: `gates/tools/init.py` (`apply` ends with `doctor`, spec §4 step 4)
- Requests: Rq-4-2 (`COMMANDS["doctor"]`), landed after `init4`'s PR merges.
- Test: `tests/test_doctor.py`

**Owner answers applied:** spec §4 doctor list; programs design §12a ("doctor says so"); owner directive (protection reported); Q-B4plan-2 (a), Q-B4plan-7 (a); SE-B4-6; ruling (4d) on a read-only doctor.

**Interfaces:**
- Consumes: `config.load`, `plugin.framework_dir/version/repository`, `managed.find_block/is_generated`, `templates.*` (with `pin_of`), `githooks status`, `gate_schema.check`, `index.render`, `gitinfo.tracked_files`, `dispatch.limits_of` (env parsing), `host.github_remote/read_state`, `merge.MODES`.
- Produces: `check(args: list) -> Result`, gate id `doctor`, and `main(argv: list) -> int` for `python3 -m gates doctor --root R [--json]`.
  - `--root` is required, and the framework directory or a path inside it is refused as `doctor.input` (F-B4p-1).
  - `doctor` is a command, not in `GATES` or `run_all`.
  - Lines, in order:
  - `doctor.python`: `sys.version_info >= (3, 9)`.
  - `doctor.input`: config missing or invalid (`config.load`'s message, naming `/strict-delivery:init` when missing). It stops here.
  - `doctor.version`: `framework_version` equals `plugin.version`, else names `/strict-delivery:upgrade`.
  - `doctor.extras`: PASS whose reason lists each extra as installed or not. With neither installed, the reason is `neither extra installed: this repository is gated only inside Claude sessions`.
    - Installed means: a `pre-commit` or `pre-push` file in `hooks_dir` carries the shim header (git hooks), and `.github/workflows/strict-delivery.yml` exists and carries the generated header (CI).
    - A workflow at that path without the header is not the CI extra. The reason names it (`CI: <path> is a project workflow, not the framework template`), and no `doctor.ci` line is printed. This is this repository's state (Q-B4plan-7 (a)).
  - `doctor.githooks.<name>`: when the hooks extra is installed, the `githooks status` lines restated (`missing | foreign | stale` fail), plus FAIL when `core.hooksPath` is set (spec §4 "not foreign or bypassed").
  - `doctor.ci`: when the CI extra is installed, the workflow equals `ci_workflow(cfg, ci_pin(...), plugin.repository_slug(...))`. Otherwise it fails naming `pin` (`pin_of` differs) or `stale`.
  - `doctor.claude-block`, `doctor.gitignore-block`: the block is present, well-formed, at `plugin.version`, and its body equals the render. Failures: `missing`, `malformed: <reason>`, `version <x> differs from the plugin <y>`, `stale; run /strict-delivery:upgrade`.
  - `doctor.registers`: `gate_schema.check(["--root", root])` is ok, else lists its failing ids.
  - `doctor.indexes`: `index.render(root, cfg)` raises nothing.
  - `doctor.generated-tracked`: no key of `index.render` is in `gitinfo.tracked_files`.
  - `doctor.subagents`: PASS naming each env value of `.claude/settings.json`, or `unset (Claude Code default)`. It fails when `settings.json` is invalid JSON or a value is not a decimal integer of at least 1 (`limits_of`'s rule).
  - `doctor.merge-mode`: PASS naming `cfg["merge"]["mode"]`.
  - `doctor.protection`:
    - no GitHub `origin`: PASS `not checked: no GitHub remote` (spec §4 "when the host can be read");
    - otherwise PASS when `pr_required` and merge-commit-only and `admins` hold (SE-B4-6);
    - else FAIL naming each missing setting;
    - a `HostError`: FAIL `cannot read <slug>: <reason>` (Q-B4plan-2 (a)).

**Input-domain dimensions:**
- Root: `--root` missing (exit 2); the framework directory and a path inside it (refused).
- `init apply`'s exit code (F-B4p-16): `apply` exits 1 when any doctor line FAILs, and 0 only when every doctor line passes. The written files stay either way, and the report says so.
- Python version (patched `sys.version_info`): 3.8, 3.9, 3.13.
- Config: missing, invalid, valid.
- `plugin.json`: absent (`doctor.version` FAIL naming the plugin), version equal, different.
- Each extra: installed, absent, foreign (hook without header), stale shim, `core.hooksPath` set.
- Blocks: missing, malformed, old version, stale body, current; CLAUDE.md absent.
- CI: absent; a project workflow without the header (not installed, named in `doctor.extras`, no `doctor.ci` line); managed with another pin; managed and current, with a tag pin and with a sha pin.
- Registers: valid, one invalid record. Indexes: render raising (a malformed record). Generated files: none tracked, one tracked.
- settings.json: absent, no `env`, values `5`, `0`, `abc`, invalid JSON.
- Remote and host state: the rows of Task 4d.2.
- `init apply` output ends with doctor's lines.

- [ ] **Step 1: Write the failing tests:**
  ```python
  def test_fresh_init_doctor_green():
      assert code == 0 and all(l.startswith("PASS") for l in lines)
  def test_neither_extra_says_so():              # spec §4
      assert "PASS doctor.extras: neither extra installed: this repository is gated only inside Claude sessions" in out
  def test_stale_block_fails_naming_upgrade():
      assert "FAIL doctor.claude-block: stale; run /strict-delivery:upgrade" in out
  def test_ci_pin_mismatch():
      assert "FAIL doctor.ci: pin" in out
  def test_tracked_index_fails():
      assert "FAIL doctor.generated-tracked:" in out
  def test_no_github_remote_protection_not_checked():   # spec §4 "when the host can be read"
      assert "PASS doctor.protection: not checked: no GitHub remote" in out
  def test_github_remote_unprotected_fails():
      assert "FAIL doctor.protection: pull request not required" in out
  def test_doctor_writes_nothing():
      assert snapshot(root) == before
  def test_init_apply_ends_with_doctor():
      assert out.rstrip().splitlines()[-1].startswith(("PASS doctor.", "FAIL doctor."))
  ```
- [ ] **Step 2-4:** run (FAIL), implement, run both interpreters and `run_all` (PASS).
- [ ] **Step 5: Commit** `feat(tools): doctor`, then checkpoint.

---

## Block 4e: `upgrade`, commands and adoption, fixture repositories (stream `init4`)

### Task 4e.1: `upgrade plan | apply`; version sources in `run_all`

The `run_all.version` extension is request Rq-4-3, raised at this task's start and landed only after `init4`'s PR merges and Rq-4-5 is on `main` (order above). `upgrade` does not wait for it.

**Files:**
- Create: `gates/tools/upgrade.py`
- Requests: Rq-4-2 (`COMMANDS["upgrade"]`), Rq-4-3 (`run_all.version` reads the block version and the managed CI pin; tests in `tests/test_run_all.py`), both landed after `init4`'s PR merges (receiver per "When and to whom").
- Test: `tests/test_upgrade.py`

**Owner answers applied:** spec §4 (upgrade), §15 ("every migration is tested from an old fixture"); F-1; Q-B2plan-24 (a); rulings (4e); SE-B4-4; Q-B4plan-1 (a) (settings untouched by upgrade); Q-B4plan-7 (a).

**Interfaces:**
- Consumes: `migrations.MIGRATIONS/migrate/current_version`, `schema.schemas/files_of/validate/validate_front_matter`, `yamlsub.load/emit`, `managed.*`, `templates.*`, `plugin.framework_dir/version/repository`, `githooks.install`, `profiles.load`, `doctor.check`, `run_all.check`, `store.Store`.
- Produces:
  - `main(argv: list) -> int` for `python3 -m gates upgrade <plan|apply> --root R [--profile P] [--hooks yes|no] [--ci yes|no]`. `--root` is required, and the framework directory or a path inside it is refused as `upgrade.input` (F-B4p-1).
  - `plan_upgrade(root: str, opts: dict) -> UpgradePlan`:
    1. Read the config raw (`yamlsub.load`), migrate it with `migrate("config", row)`, and set `framework_version` to `plugin.version` and, under `--profile`, `profile`. Text edits follow the ruling. The merged config used below comes from the migrated row.
    2. For every kind whose schema format is `yaml` or `front-matter`, migrate every file `files_of` lists.
       - YAML files are re-emitted.
       - Front-matter files keep their body byte-identical, and only the front matter is re-emitted.
       - A file whose tag is older than current with a gap in `MIGRATIONS`, or a markdown kind below its current version, is `FAIL upgrade.migrate.<file>: no registered migration from <tag>` (fail closed: nothing written).
    3. Re-render both managed blocks at the plugin version, inserting a missing block (ruling: plain duplicate lines become notes).
    4. Re-render the CI workflow (pin from `ci_pin`) when it is managed or `--ci yes`. Under `--ci yes`, a foreign workflow at the path is a conflict, never overwritten. Under `--ci no`, a managed workflow is removed, and a foreign one is left untouched with the note `<path>: a project workflow, not the framework template; left as is`. That is this repository's adoption route (Q-B4plan-7 (a)).
    5. Re-install the hook shims when installed or `--hooks yes`. Under `--hooks no`, the shims with the header are removed, and a foreign hook is a conflict.
    6. Under `--profile`, an `overrides` key that is not a policy key of the new profile is a conflict.
  - `plan` prints the diffs, removals and notes, and writes nothing.
  - `apply`:
    - runs `doctor.check` and `run_all.check` before writing;
    - writes (conflicts: nothing written, exit 1);
    - runs both again;
    - prints the diff (`git diff` plus untracked files), then every line that was PASS or absent before and is FAIL after, under the heading `newly failing:`;
    - exits 1 when that list is non-empty.
    - It never commits, and never touches `.claude/settings.json`.
  - `upgrade` writes `.strict-delivery/config.yml` and register records only under spec edit SE-B4-4. Record files are written through `Store.replace`.

**Input-domain dimensions:**
- Old fixtures (spec §15), one per registered migration: `config/1` with and without comments; `decision/1` records (open, answered, withdrawn); then `upgrade apply`; `check decisions --base <the fixture's base>` passes (F-1, migrate-before-compare).
- A `decision/1` record with a gap (a fake `decision/0`): refused, nothing written.
- A front-matter kind (handoff) at current: untouched. A markdown kind (ledger) with an old first line: refused.
- Config: only the tag changes (line edit, comments kept); a fake migration changing a key in a commented file (refused); `framework_version` quoted and unquoted.
- Blocks: absent (inserted), old version, current; this repository's plain `.gitignore` lines (kept, notes listed).
- Extras: each of `--hooks yes|no`, `--ci yes|no` against installed, absent, foreign. `--ci no` with a foreign workflow leaves it byte-identical, with a note. The CI pin moves from a sha to `v<x>` once the plugin version is a release.
- Root: `--root` missing (exit 2); the framework directory and a path inside it (refused).
- `--profile` to each profile, with and without overrides of `block.max_tasks`.
- Newly failing: none; one (a seeded stale record); a line failing before and after (not listed).
- Idempotence: a second `apply` changes nothing and lists nothing.
- (Rq-4-3's rows are `package`'s: block present, equal, different, missing; CI absent, foreign, managed equal, managed different.)

- [ ] **Step 1: Write the failing tests:**
  ```python
  def test_upgrade_migrates_old_fixture():       # spec §15
      assert rec(DID)["schema"] == "decision/%d" % current_version("decision") and run_all_code == 0
  def test_config_tag_line_edit_keeps_comments():
      assert read(CFG).splitlines()[1] == "# my comment" and "config/%d" % current_version("config") in read(CFG)
  def test_gap_refused_writes_nothing():
      assert "FAIL upgrade.migrate." in out and snapshot(root) == before
  def test_plain_gitignore_lines_kept_and_noted():
      assert read(".gitignore").startswith(OLD_PLAIN) and "duplicates a block entry" in out
  def test_ci_no_removes_managed_only():
      assert not exists(WF) and code == 0
  def test_ci_no_leaves_foreign_workflow():      # Q-B4plan-7 (a) adoption route
      assert read(WF) == FOREIGN and "a project workflow, not the framework template; left as is" in out
  def test_ci_yes_foreign_workflow_conflict():
      assert code == 1 and read(WF) == FOREIGN
  def test_newly_failing_listed():
      assert "newly failing:\nFAIL decisions." in out and code == 1
  def test_second_apply_noop():
      assert plan_out == "no changes\n"
  def test_framework_dir_refused_as_root():      # F-B4p-1
      assert "is the framework's own directory" in out and snapshot(fw) == before
  ```
- [ ] **Step 2-4:** run (FAIL), implement, run both interpreters and `run_all` (PASS).
- [ ] **Step 5: Commit** `feat(tools): upgrade runs schema migrations, re-renders managed files, changes profile and extras`, then checkpoint.

### Task 4e.2: slash command files; this repository's adoption, rehearsed and requested

Starts when block 3's `.claude-plugin/plugin.json` is on `main` and merged into `init4`, and M-B4-1 is ledgered.

**Files:**
- Create: `commands/init.md`, `commands/doctor.md`, `commands/upgrade.md`
- Not touched on `init4`'s branch: `CLAUDE.md` and `.gitignore`. This repository's adoption is Rq-4-5, landed by `.gitignore`'s owner after `init4`'s PR merges (F-B4p2-2). This task rehearses the adoption in a disposable clone and writes the request.
- Test: `tests/test_commands.py` (the rehearsal runs on a temp clone, never on this checkout's tracked files; `tests/test_self_adoption.py` is not block 4's).

**Owner answers applied:** spec §16 as edited by SE-B4-7 (this repository adopts itself at strict; its own workflow stands in for the CI extra); rulings (4c) on interactivity and (4e) on `.gitignore`; Q-B4plan-7 (a).

**This repository's CI workflow (F-B4p-2).** `.github/workflows/strict-delivery.yml` here is this repository's own matrix workflow (Task 2b.3, extended by P3.1 and P3.3). It has no generated header, so it is not framework-managed, and `upgrade` never overwrites it:
- `--ci yes` would report it as a conflict and write nothing.
- The adoption runs `--ci no` (Q-B4plan-7 (a)). The file is left byte-identical with a note, and `doctor.extras` names it as a project workflow. The §16 edit (SE-B4-7) says this repository's own workflow stands in for the CI extra.

**Interfaces:**
- Consumes: `init`, `doctor`, `upgrade` CLIs.
- Produces:
  - `commands/init.md` tells Claude to:
    1. run `init questions --json`;
    2. ask the owner, one batch in chat, for each slot's command (each proposal shown with its source, plus `test_one` always), the profile, the model map (default from the profile), the two extras (hooks default yes, CI default no), the subagent depth and concurrency (offered, written to `.claude/settings.json`), `merge.mode` (host or controller), the base-branch protection offer, and, when listed, the migration;
    3. write the answers file into a fresh `mktemp -d` directory;
    4. run `init plan` and show its output whole;
    5. run `init apply` only on the owner's word;
    6. never commit.
  - `commands/doctor.md` runs `doctor` and shows the lines whole.
  - `commands/upgrade.md` runs `upgrade plan` with the owner's flags, shows it, and runs `upgrade apply` on the owner's word.
  - **How a command file invokes the framework.** In the form measured by M-B4-1 (session controller, before block 4c): `cd "${CLAUDE_PLUGIN_ROOT}" && python3 -m gates <cmd> ... --root "$OLDPWD"`, or the owner-chosen fallback if M-B4-1 failed. Every invocation passes `--root` explicitly (F-B4p-1).
  - The rehearsal: `git clone` this checkout into a `mktemp -d` directory, then run `python3 -m gates.tools.upgrade apply --root <clone> --hooks yes --ci no` (the module form until Rq-4-2 lands). In the clone:
    - `CLAUDE.md` holds the block;
    - `.gitignore` holds the block, and the notes list exactly the plain lines that duplicate it (`.superpowers/` and `__pycache__/` are not framework entries);
    - the workflow is byte-identical;
    - after the duplicates are removed in the clone, `doctor --root <clone>` is all PASS except `doctor.protection`, which reads the clone's `origin` (a local path, so `not checked`).
  - The request text for Rq-4-5 names the command, the notes' duplicate lines, and the expected doctor lines. The real `doctor.protection` against this repository's host is checked and ledgered by the receiver.

**Input-domain dimensions:**
- Command files: the forbidden strings of Task B1.1 (read from `tests/prose_check.py` when present on the branch; else the literal list of model names and the superpowers save path); each names its CLI subcommands exactly as `main` accepts them (parsed and checked against `init.main(["--help"])` output).
- Command files: every `python3 -m gates` line carries `--root` (F-B4p-1).
- Rehearsal (in the clone): a second `upgrade plan` prints no changes; `git check-ignore` holds for every block entry; the duplicate-line notes equal the clone's actual duplicates; the workflow is byte-identical; this checkout's tracked files are unchanged by the test.

- [ ] **Step 1: Write the failing tests:**
  ```python
  def test_commands_name_real_subcommands():
      assert set(subcommands(read("commands/init.md"))) <= {"questions", "plan", "apply"}
  def test_commands_free_of_forbidden_strings():
      assert not forbidden_hits(read_all("commands/"))
  def test_rehearsal_writes_both_blocks():       # in a temp clone of this checkout
      assert find_block(read(clone, "CLAUDE.md"), HTML) and find_block(read(clone, ".gitignore"), HASH)
  def test_rehearsal_notes_list_duplicates():
      assert noted_duplicates(out) == set(plain_lines(read(clone, ".gitignore"))) & set(block_lines(read(clone, ".gitignore")))
  def test_rehearsal_workflow_untouched():       # Q-B4plan-7 (a)
      assert read(clone, WF) == read(REPO, WF)
  def test_rehearsal_leaves_checkout_alone():
      assert tracked_hashes(REPO) == before
  def test_command_lines_pass_root():
      assert all("--root" in l for l in gates_lines(read_all("commands/")))
  ```
- [ ] **Step 2: Run; expect FAIL.**
- [ ] **Step 3: Write the command files; run the rehearsal; write the Rq-4-5 request text into the report (command, duplicate lines, expected doctor lines).**
- [ ] **Step 4: Run both interpreters and `run_all`; expect PASS.**
- [ ] **Step 5: Commit** `feat(plugin): init, doctor and upgrade commands`, then checkpoint. The session controller records Rq-4-5 (and Rq-4-2, Rq-4-3) to be landed after `init4`'s PR merges, in the order stated above.

### Task 4e.3: fixture repositories and init end to end

May run in parallel with Task 4e.2 (disjoint files) once Task 4e.1 is committed, in a group branch `<program>/init4/fixtures` (programs design §4.1).

**Files:**
- Create: `tests/repo_fixtures.py`, `tests/test_init_e2e.py`
- Test: those two

**Owner answers applied:** spec §14 (init end to end); DC-1..DC-4 (expected proposals); ruling (4e) on seeded hook violations; registers ship empty (synthetic fixtures only).

**Interfaces:**
- Consumes: `init`, `doctor`, `run_all`, `githooks`, `detect.SOURCES`, `helpers.make_repo/commit_all/GitIsolatedTestCase`, `decisions_cli.main` (to seed an open decision).
- Produces:
  - `repo_fixtures.LAYOUTS: dict` maps a name to a builder `(root) -> expected proposals`, for `node`, `rust`, `go`, `python`, `c_make`, `empty` and `monorepo`.
    - Each builder writes synthetic files only:
      - `node`: `package.json` with `test`, `lint`, `build` scripts;
      - `rust`: `Cargo.toml`;
      - `go`: `go.mod`;
      - `python`: `pyproject.toml` with `[tool.pytest.ini_options]` and `[tool.ruff]`;
      - `c_make`: `Makefile` with `test:` and `build:`;
      - `empty`: nothing;
      - `monorepo`: `packages/a/package.json` and `packages/b/Cargo.toml` only, so nothing is proposed (DC-3).
    - The expected proposals are written as literals from Task C1.2's table, never computed by `detect`.
  - `repo_fixtures.superpowers(root)` (two tracked documents and a referencing README) and `repo_fixtures.colliding(root)` (the same plus an existing `docs/strict-delivery/specs/<same name>`).
  - The end-to-end flow per layout:
    1. `make_repo`;
    2. builder;
    3. `init questions --json` proposals equal the literals;
    4. an answers file with every required key (F-B4p-12):
       - `schema: init-answers/1`;
       - `profile: standard`. Not strict: strict pre-commit runs `commands.test` (Q-B2plan-11 (a)), and the fixtures' `npm run test`, `cargo test` and so on are not runnable in the test environment. Not light: standard runs `claims` too, the wider gate list.
       - `models: {tiers: <DEFAULTS tiers>}`;
       - `commands`: every proposal accepted, plus `test_one: "true {id}"`;
       - `git_hooks: true`, `ci: false`, `merge_mode: host`, `protect_base: false`, `subagents: {}`, `base_branch: main`;
       - `migrate` only for the superpowers fixtures;
    5. `init apply --root <fixture>` exit 0;
    6. `git add -A` and a real `git commit` through the installed shim, exit 0;
    7. `doctor` exit 0 and `run_all` exit 0.
  - Seeded violations, each on a fresh copy of the green `node` fixture, each turning `run_all` (or `doctor`) red with its named line:
    - an unanswered decision id referenced in `docs/` (`decisions.open-ref`);
    - a duplicate id (`register` or `decisions` collision);
    - a base-branch record deleted on a branch (`decisions.base.deleted.<id>`);
    - a tracked generated index (`doctor.generated-tracked`);
    - the hook cases only per the ruling.
  - The migration fixture, with `migrate: true`: both documents at their targets, `git log --follow` reaching the original commit, the README rewritten. The colliding fixture: `init apply` exit 1 naming the conflict, and the tree byte-identical (`git status --porcelain` and a hash of every file).

**Input-domain dimensions:**
- Each of the seven layouts.
- Each seeded violation, alone.
- Migration: `migrate: true` and `false`; collision.
- Both interpreters (the test command), with the shim invoking `python3` from `PATH`.
- A fixture run never touches this checkout (temp directories only; `GIT_CONFIG_*` isolation as `GitIsolatedTestCase`).

- [ ] **Step 1: Write the failing tests:**
  ```python
  def test_layout_proposals_match_table():       # subTest per layout
      assert proposals(root) == LITERAL[name]
  def test_layout_init_doctor_run_all_green():   # subTest per layout
      assert (apply_code, commit_code, doctor_code, run_all_code) == (0, 0, 0, 0)
  def test_seeded_violation_turns_red():         # subTest per violation
      assert code != 0 and expected_line in out
  def test_superpowers_migration_end_to_end():
      assert exists(TARGET) and ORIGINAL_SHA in follow_log(TARGET) and "docs/strict-delivery/specs/" in read("README.md")
  def test_collision_writes_nothing():
      assert code == 1 and tree_hash(root) == before
  ```
- [ ] **Step 2-4:** run (FAIL until the fixtures are built), implement, run both interpreters and `run_all` (PASS).
- [ ] **Step 5: Commit** `test(init): fixture repositories and init end to end`, then checkpoint.
- **Block 4e end (stream `init4` finished):** merge the fixtures group branch into the stream branch, then final review, verifier and the PR flow.

---

## Block 5: context, docs and drift tooling (streams `context` and `docs`; sub-blocks 5a, 5b, 5c)

Spec §17 block 5: "Context, docs and drift tooling in full (`gate_context`, receipts, `gate_cites`, `gate_drift`, `gate_index`)." Plan outline, Block 5: "`context.yml` and its schema, read receipts and the receipt schema, `gate_context`, `gate_cites` (delivered by stream C in Tasks C2.1-C2.2; block 5 does not plan it again), `gate_drift` ..., and `gate_index` ...". Programs block, cross-block notes: "**Block 5:** `overview/2` (live programs and specs and plans by state in `INDEX.md`, Task 1c.3) and `gate_drift` (status rows against git, the numeric estimate check) are not in this block; they consume `programs.load_program` and the status rows of Task P2.1." So block 5 also carries `overview/2`.

Block 5 runs inside the program that runs blocks 3-6, after the programs block has merged. It is two streams with disjoint files, and three sub-blocks of at most 3 tasks:
- **Stream `context`** (stream branch `<program>/context/main`):
  - **5a** (Tasks 5a.1-5a.3): the `context.yml` schema and lookup with this repository's `context.yml`; read receipts and the receipt schema; `gate_context`.
- **Stream `docs`** (stream branch `<program>/docs/main`), two groups that run in parallel (programs design §4.1), each on its group branch, merged into the stream branch by the stream controller after a clean review and green gates:
  - **5b** (group `index`, branch `<program>/docs/index`; Tasks 5b.1-5b.2): `overview/2` in `INDEX.md`; `gate_index`, and the check that `gate_cites` is enabled.
  - **5c** (group `drift`, branch `<program>/docs/drift`; Tasks 5c.1-5c.2): the drift library; `gate_drift` and `drift report`.

**Parallelism.** 5a, 5b and 5c share no file, so all three run at once. Inside a sub-block the tasks are SERIAL (each consumes the one before). The waits are the cross-stream requests below, each named at the step that needs it.

`<program>` is the program's `<YYYYMMDD>-<slug>` name, fixed by the program plan. Each stream needs a plan of its own (each stream owns `<paths.plan_state>/<its plan slug>/`, programs block controller ruling on ownership); the program plan names them. Each stream branch starts from the tip of `main` (Q-M4 (a)), is pushed at every checkpoint, and follows `main` by a merge of `main` at a sync (Q-Pplan-5 (a)). Each sub-block ends with a final review (tier3), the final verifier (top tier: `tier4` when set, else `models.top_tier_fallback`, default `tier3`, Q-B2plan-21), and a checkpoint. When a stream's last sub-block has ended, the stream controller opens the stream's pull request to `main` (`gh pr create`). The owner approves it in chat, naming the PR and its head sha. The program controller runs `gh pr merge <n> --merge --match-head-commit <that sha>` (this repository's `merge.mode: controller`, Q-M1), reads the merge back from the host, and writes the `MERGED` line in the first commit of the cleanup branch (`final=yes`; Q-15 (a), Q-Pplan-9 (a)). The commit gate is `python3 -m gates run_all` plus the test command on both interpreters, with a clean tree. Each checkpoint also runs `python3 -m gates check checkpoint --plan <stream plan slug>` (Task P1.3) and expects PASS.

The owner answered this block's questions Q-B5plan-2..5 on 2026-11-02 (section "Owner answers", "Blocks 3-6 (2026-11-02)"); the task text states each answer.

**Owner answers applied across the block (binding):**
- Owner directive, pull-request flow, and Q-M4 (a): stream branches start from `main` and are judged against it; the integration branch holds only program records and combined testing, and never merges into `main`. So `gate_drift` measures a stream branch, and the integration branch, against `main`, never a stream against integration. Main spec §9 and programs design §12 already say so (SE-12, applied on block/b1c): "a stream branch behind the base branch, or an integration branch behind it, fails until a sync".
- Q-15 (a): merges are recorded as ledger `MERGED` lines (Task P1.2), checked against git by Task P3.1. `gate_drift` does not re-check them.
- Q-Pplan-8 (a): a stream's handoff is read at the tip of its stream branch. `gate_drift` reads the same handoff.
- Q-Pplan-12 (a): global records written during the program live on `<program>/integration` until the records PR. `gate_drift` and `overview/2` read a program's decision records at the tip of `<program>/integration`.
- Programs controller rulings: live programs come from `programs.live_programs`; a status row's `estimate` and `used` are non-negative integers in the unit of the stream's `estimate` in `streams.yml`; merges are merge commits only.
- Q-H5 (a): the session acts as program controller by default. That changes nothing in this block's code. Session kinds are named under Task 5a.1.
- Q-B2plan-21: no model is named here; every role resolves its tier as `gate_dispatch` checks it.
- OQ-1, OQ-16, OQ-17, I7: every schema refuses unknown keys; generated kinds absent on disk are skipped; file and function names are the plan's choice.

**Interfaces consumed (by exact name):**
- Block 1: `result.Result/GateError/gate_args/run_gate/run_check`; `config.load/DEFAULTS` (`paths.context`, `paths.receipts`, `paths.index`, `paths.plans`, `paths.specs`, `paths.plan_state`, `paths.programs`, `drift.estimate_factor_pct`, `base_branch`, `profile`); `yamlsub.parse/load/emit/YamlError`; `schema.load_schema/validate/validate_markdown/SCHEMAS_DIR/KNOWN_KINDS/GENERATED_KINDS`; `store.Store(root, kind, cfg)`, `store.Record(id, row, file)`; `decisions.in_force/is_resolved`; `findings.is_resolved`; `gitinfo.toplevel/head_sha/commit_exists/tracked_files/show/ls_tree/merge_base`; `index.render/regenerate/PRODUCES` (Task 1c.3); `gate_schema.check`.
- Block 2: `dispatch.ROLES`; `run_all.PROFILE_GATES/check`; `migrations.current_version`.
- Programs block: `checkpoints.parse_handoff/handoff_errors/plan_slug` (P1.2); `gitinfo.current_branch/is_ancestor` (P1.3); `programs.live_programs/load_program/Program/status_rows/status_errors/branch_of/worktrees_dir/NAME_RE`, `gitinfo.local_branches` (P2.1); `gitinfo.parents/rev_list` (P2.3); `cleanup.final_merge` (P3.2; for done plans in 5b.1).
- Stream C: `gates/gate_cites.py` (`PRODUCES = ()`, `check(args)`, `main(argv=None)`), checked on block/sc2 at 2df51c0. Block 5 plans none of it again.

**Cross-stream requests (the program controller mints each `R-` id).** Registry files (controller ruling, binding for the blocks 3-6 program): `gates/__main__.py`, `gates/producers.py`, `gates/run_all.py` and `tests/test_run_all.py` belong to block 3's `package` stream. Every other stream adds its lines by cross-stream request, received by `package` while it is live and by A once `package` has merged (DS-3; controller ruling for all blocks). A request lands its registry line only in the same PR as the module it names, or after that module has reached `main`, so `check schema` and `run_all` never go red on `main` or on a stream that updates from it (review F-B5p-1: `schema.produced_kinds` raises for a producer module that cannot be imported, and `run_all` fails `run_all.missing.<gate>`). Block 5's modules reach `main` only with its stream PRs, so Rq-5-1..3 are raised at each sub-block's start and land after the stream PR that carries their modules has merged. Each "Registration" step below runs then, on `main` updated from the remote, and the tests that read a registry skip with the named reason `<Rq id> not on this branch` until then. While a skip stands, every checkpoint line carries `open: <Rq id> (registration after merge)`, so no skip is silent.
- **Rq-5-1 `gates/__main__.py` (`package`):** `GATES["context"] = "gates.gate_context"`, `GATES["index"] = "gates.gate_index"`, `GATES["drift"] = "gates.gate_drift"`; `COMMANDS["context"]` (`gates.tools.context_cli.main`), `COMMANDS["receipt"]` (`gates.tools.receipt_cli.main`), `COMMANDS["drift"]` (`gates.tools.drift_cli.main`). Lands after stream `context`'s PR (the `context`/`receipt` rows) and after stream `docs`'s PR (the `index`/`drift` rows). Read by the Registration steps of 5a.1, 5a.2, 5a.3, 5b.2 and 5c.2.
- **Rq-5-2 `gates/producers.py` (`package`):** add `gates.gate_context` (R5a-5). Lands after stream `context`'s PR. Read by 5a.3's Registration step.
- **Rq-5-3 `gates/run_all.py` and `tests/test_run_all.py` (`package`):** `index` appended to the `standard` and `strict` tuples of `PROFILE_GATES`, not to `light` (R5b-3). Lands after stream `docs`'s PR. Read by 5b.2's Registration step.
- **Rq-5-4 `gates/lib/gitinfo.py` (additive, to that file's owner under the program plan; additive functions name no module, so they may land first; every call with `-C root`, `GIT_INDEX_FILE` inherited, as every gitinfo call):**
  - `is_ignored(root: str, path: str) -> bool`: `git check-ignore -q --no-index -- <path>`; exit 0 is `True`, exit 1 is `False`, anything else raises `GateError`. Needed by 5b.2.
  - `first_parent(root: str, ref: str) -> list`: `git rev-list --first-parent <ref>`, newest first. Needed by 5c.1.
  - `deleted_paths(root: str, ref: str, directory: str) -> list`: the repo-relative paths under `directory` that some commit reachable from `ref` deleted and that are absent at `ref` (`git log --diff-filter=D --name-only --format= --no-renames <ref> -- <directory>`, deduplicated, sorted). Needed by 5b.1.
  - `upstream_of(root: str, branch: str) -> Optional[str]`: the commit of `<branch>@{upstream}` read from local refs (`git rev-parse --verify --quiet <branch>@{upstream}`), `None` when the branch has none. Needed by 5c.1.
- **Rq-5-5 `skills/strict-delivery/prompts/program_controller.md`** (prose; owner per Q-Pplan-6 (a)): at each sync, first update the local base branch with `git -C <checkout that has the base branch> fetch <remote>` and then `git -C <that checkout> merge --ff-only <remote>/<base_branch>`, each as its own command (allowed by block 3's Q-B3plan-3 (a), a fast-forward-only update of the local base branch to its own remote), then run `python3 -m gates check drift --program <p>` as programs design §10 orders (its FAIL lines list what the sync must fix); after the merges and updates, run it again and expect PASS before the `SYNC` line (with `--host` both times where the remote is GitHub, Q-B5plan-2 (a)); then run `python3 -m gates drift report --program <p>` and put each `over` line in the sync's owner batch (R5c-2). Needed by: the 5c sub-block end.

**Controller rulings (spec or plan settles each; ledgered in this form, at most five per sub-block):**

Sub-block 5a:
- **R5a-1.** Controller ruling: `gate_context` is in no `run_all` list. Block 3's hooks call it with the session's key, kind and role, before a dispatch (PreToolUse Agent) and before an agent's commit (PreToolUse Bash, gated commit). A commit made outside Claude (git hook, CI) gets no context check -- receipts exist only for Claude sessions, and a git commit names no session -- cost if wrong: a profile gate list edit and a session source for git hooks -- spec §9 "a PostToolUse hook on Read appends ... `gate_context` fails a dispatch or commit"; spec §4 "PostToolUse Read: read receipts for the context contract".
- **R5a-2.** Controller ruling: the reads checked are the ones required of the session that makes the dispatch or the commit: its own kind and role. They are never the dispatched agent's, which has read nothing yet -- cost if wrong: a dispatch-time rule nobody can meet -- spec §9 "fails a dispatch or commit when a required read is missing".
- **R5a-3.** Controller ruling: `gate_context` prints a `FAIL` line for a missing or stale read under every profile. Whether the caller refuses on it is `context.enforced(cfg)`: true only on `strict`. On `light` and `standard`, block 3's hook prints the lines as a warning and lets the call through -- the gate contract has only PASS and FAIL lines; text output drops a PASS line's reason (`Result.render` keeps it only under `--json`), so a warning carried on a PASS line would be invisible in the text a hook prints, and the facts are the same under every profile -- cost if wrong: the gate grows a profile branch -- spec §13 gate contract; spec §9 "fails ... (strict); it warns only (light, standard)"; spec §12 "context read receipts | advisory | advisory | enforced". Spec edit S5-1.
- **R5a-4.** Controller ruling: every successful Read appends a receipt, a partial read (offset or limit) included. The row's `path` is the absolute `os.path.realpath` of the file read. Its `sha` is the git blob id of the file's raw bytes (`sha1(b"blob <n>\0" + bytes)`, no clean filters), computed in Python with no subprocess -- spec §9 gives `{path, sha}` and no condition on the read; the status page lives in the integration worktree, outside the session's own tree, so a repo-relative path cannot name it; a raw-bytes id compares the same content at read time and at gate time -- cost if wrong: a partial read satisfies a required read; a `receipt/2` migration -- spec §9 "appends a `{path, sha}` row".
- **R5a-5.** Controller ruling: the session kinds are `program`, `program-controller`, `stream-block` (a kind written `stream-<id>-block` is looked up as `stream-block`, with `{stream}` = `<id>`) and `sync` (programs design §10), plus `plan` for a plain plan's controller session. `gate_context` declares `PRODUCES = ("context",)`; `receipt` is not declared (Q-B5plan-5 (b)) -- programs design §10 lists the program kinds; spec §7.1 names "the controller's session" of a plain plan, which needs a kind; Appendix A lets a gate be the producer of a kind -- cost if wrong: a kind renamed, or a producer moved -- spec §9 "The session kinds of programs are in the programs and streams design, section 10"; Appendix A "A kind's producer has landed when a gate or tool ... declares that kind in its `produces` list".

Sub-block 5b:
- **R5b-1.** Controller ruling: `overview/2`'s migration is regeneration. There is no `("overview", 1)` entry in `migrations.MIGRATIONS`. `index` overwrites an `overview/1` file, and the SessionStart hook and `python3 -m gates index` regenerate before use -- `MIGRATIONS` maps dict rows (Task 2a.1), while `INDEX.md` is generated markdown, git-ignored and rebuilt before use -- cost if wrong: an `overview/1` file left on disk fails `gate_schema` until `index` runs -- Appendix A "come in `overview/2` with a migration"; spec §5 "regenerate the generated files before use". Spec edit S5-3.
- **R5b-2.** Controller ruling: `gate_index` calls `index.render` and writes nothing. It checks that every generated path is untracked and git-ignored -- a gate that writes files changes the tree it judges; spec §5 makes the generated files ignored as well as uncommitted -- cost if wrong: a write failure (for example a parent that is a file) is not caught by the gate -- spec §9 "regenerate without error, and none of them is tracked"; spec §5 "Ignored, never committed: generated files".
- **R5b-3.** Controller ruling: `index` joins `run_all` for `standard` and `strict` only -- spec §12's light pre-commit cell names exactly "schema, register, decisions", the same literal reading block 2 took -- cost if wrong: one tuple edit (it follows the owner's D4 ruling on `cites` if that ruling reads the light cell otherwise) -- spec §12 pre-commit row.

Sub-block 5c:
- **R5c-1.** Controller ruling: `gate_drift` is in no `run_all` list. It runs at each sync, first as programs design §10 orders (after a fetch of the base branch), and again after the sync's merges, expecting PASS before the `SYNC` line; and on demand (`python3 -m gates check drift`) -- programs design §10: the sync "run[s] `gate_drift`"; the second run is how the sync shows it ended clean (divergence D5-5, spec edit S5-7); as a commit gate it would fail every stream's commits whenever `main` moved, and a stream cannot sync itself -- cost if wrong: drift shows only at syncs -- programs design §10, §12; spec §9 "fails until a sync".
- **R5c-2.** Controller ruling (was Q-B5plan-1): the estimate check compares each status row's `used` with that row's `estimate`, the stream's estimate, and an overrun is reported, not failed. `gate_drift` prints no estimate line; `python3 -m gates drift report` prints one `over` line per overrun, and the sync puts each in the owner batch (Rq-5-5). The page holds no per-block estimate: `program create` writes the row's `estimate` from `streams.yml`, and `program status` cannot change it (Task P2.2). Spec §9 separates, in one sentence, drift that "fails until a sync" from an overrun that "is reported to the owner" -- cost if wrong: a `drift.estimate` line, or a `status/2` with a block estimate -- programs controller ruling on status numbers; spec §9 "a block past `drift.estimate_factor_pct` percent of its estimate is reported to the owner". Spec edit S5-2; divergence D5-1.
- **R5c-3.** Controller ruling: a stacked stream (`stacked_on` in `streams.yml`) also drifts when its `stacked_on` stream's branch tip is not an ancestor of its own tip -- that branch is its base for `base..HEAD` (Task P2.3; programs design §12) -- cost if wrong: one false FAIL kind -- programs design §12 "or the stream branch named as `stacked_on`".
- **R5c-4.** Controller ruling: `gate_drift` judges live programs only. A plain plan's handoff facts are `gate_checkpoint`'s (`checkpoint.head`, `checkpoint.agree`, `checkpoint.merges`, Tasks P1.3, P3.1). With no live program and no `--program`, the gate prints one `PASS drift.none` -- the spec's drift facts (status page, stream branches, integration) exist only in programs, and the gate contract forbids an empty run -- cost if wrong: a plain-plan mode added later -- spec §9; spec §13 "an empty run fails".
- **R5c-5.** Controller ruling: a stream "has merged" when a commit on the first-parent history of the tip of `base_branch` has exactly two parents and its second parent is the stream branch's tip. Ancestry alone never counts, because a stream branch just cut from `main`, with no commits yet, is an ancestor of `main` -- programs controller ruling: merges are merge commits only; Task P3.1's `merge.<pr>` and `head.<pr>` use the same shape -- cost if wrong: a fast-forward merge reads as not merged -- spec §7.2 "its merge commit exists on the target branch".

**Cross-block notes.**
- **Block 3 (hooks).** PostToolUse Read calls `receipts.record(root, cfg, session, file_path)` with the hook input's session id and `tool_input.file_path`; a raising call is reported and never blocks the Read (PostToolUse runs after the read). SessionStart prints `context.required(...)` for the session's kind. PreToolUse Agent and the PreToolUse Bash gated commit run `gate_context.check(["--root", R, "--session", S, "--kind", K, "--role", ROLE, ...])` and refuse on a FAIL only when `context.enforced(cfg)` (R5a-3). Block 3 must also find out, by measurement, whether a subagent's hook input carries a session key distinct from its parent's. If it does not, receipts pool across one session's agents, and the promise narrows to "someone in this session read it". The promise is stated in block 3's section either way. Order: block 3's receipt and context hook branches land after sub-block 5a has merged into `main` and block 3's stream has updated from `main` (no gate runs against files that are not there yet).
- **Block 4 (init, doctor).** `init` writes a default `.strict-delivery/context.yml` (once `context` is produced, `gate_schema` requires the file in every target repository), and `doctor` reports a missing one. Profiles may later make `context.enforced` a profile key; until then it reads `profile`.
- **Block 6 (review F-B5p-10).** Block 5 adds only `index` to `run_all` (standard and strict, R5b-3). `context` (R5a-1) and `drift` (R5c-1) are in no `run_all` list, and `cites` is as block 2 and D4 left it. `gate_context` prints the same lines under every profile; only block 3's hook treats them differently (R5a-3). Block 6's profile end-to-end tests should assert these rows and that hook behaviour, not a "passes with a warning" line through `run_all`.
- **Block 3 (`package` stream).** Lands Rq-5-1..3 after the Block 5 stream PRs that carry their modules (registry ruling above). A test that fails at a post-merge Registration step is fixed by the stream that owns the registry file the request edited: block 3's `package` stream, or A once that stream has merged (DS-3). Block 5's stream is finished by then and does not edit the registry file.
- **Programs block (Task P3.1).** Its "update `<base_branch>` from the remote" reason uses the same command as Rq-5-5: `git -C <checkout that has the base branch> fetch <remote>`, then `git -C <that checkout> merge --ff-only <remote>/<base_branch>`. Both depend on block 3's Q-B3plan-3 (a).

---

## Block 5a: context contract and read receipts (stream `context`, branch `<program>/context/main`)

### Task 5a.1: `context.yml` schema, the lookup, `python3 -m gates context`; this repository's `context.yml`

**Files:**
- Create: `gates/schemas/context.yml`, `gates/lib/context.py`, `gates/tools/context_cli.py`, `.strict-delivery/context.yml` (this repository; content owner-approved at the task review, programs design §7.1 "agent-drafted, owner-approved")
- Test: `tests/test_context_lib.py`, `tests/test_context_cli.py`

**Owner answers applied:** OQ-16, I7; R5a-5 (kinds); programs design §7.1.

**Interfaces:**
- Consumes: `schema.load_schema/validate/SCHEMAS_DIR`, `yamlsub.load/YamlError`, `config.load`, `dispatch.ROLES`, `programs.load_program/worktrees_dir/NAME_RE`, `gitinfo.toplevel`, `result.GateError`.
- Produces:
  - `gates/schemas/context.yml` (`context/1`, `format: yaml`, `files: [{path: context}]`). Fields: `schema` (`str`); `every` (`list` of `str`, required: false: reads for every session); `kinds` (`map`, required: false; keys exactly the five of `context.KINDS`, each optional, each a `list` of `str`); `roles` (`any-map`, required: false; values `list` of `str`; key check in `context_errors`).
  - `context.py`:
    - `KINDS = ("plan", "program", "program-controller", "stream-block", "sync")`.
    - `PLACEHOLDERS = ("plan", "program", "stream", "brief", "integration")`, plus `paths.<key>` for every key of `cfg["paths"]`.
    - `kind_of(name: str) -> tuple`: `("stream-block", "<id>")` for `stream-<id>-block` with `<id>` matching `NAME_RE`; `(name, None)` for a name in `KINDS`; `ValueError` naming `KINDS` otherwise.
    - `load(root: str, cfg: dict) -> dict`: reads `<paths.context>` with `yamlsub.load`, validates against `context/1` and `context_errors`; a missing file raises `GateError` naming `/strict-delivery:init`; any error raises `GateError` listing every problem.
    - `context_errors(row: dict, cfg: dict) -> list`: each `roles` key is in `dispatch.ROLES`. Each entry is a non-empty string whose `{...}` placeholders are all in the placeholder set, with no unmatched brace. After substitution it is a normalised relative path (no `..`, no leading `/`), except that `{integration}` may stand only first and `{brief}` may stand only alone. Entries within one list are unique.
    - `required(ctx: dict, kind: str, role: Optional[str], values: dict) -> list` of `(entry, resolved)`: `every`, then `kinds[kind]`, then `roles[role]`, in file order with duplicates by entry dropped. `resolved` is the substituted path, or `None` when a placeholder has no value in `values` (`plan`, `program`, `stream`, `brief`, `integration`; `paths.<key>` always resolves).
    - `values_for(root: str, cfg: dict, kind: str, plan=None, program=None, stream=None, brief=None) -> dict`: the given values. With `program`, also `integration`: `<worktrees_dir(root, streams row)>/<program>/integration`, with the streams row read by `load_program(root, cfg, program, "<program>/integration")`. With kind `stream-<id>-block`, `stream` is `<id>` (a different `--stream` raises `ValueError`).
    - `absolute(root: str, resolved: str) -> str`: `os.path.realpath` of `resolved` joined to `toplevel(root)` (an `{integration}` or absolute `{brief}` path stands as given).
  - `context_cli.main(argv: list) -> int` for `python3 -m gates context <kind> [--role R] [--plan S] [--program P] [--stream S] [--brief PATH] [--root R]` (spec §9: "`python3 -m gates context <kind>` prints it on demand"): one line per required read, `read <absolute path>`, or `unresolved <entry>: needs {<placeholder>}`; exit 0 when every entry resolved, 1 otherwise, 2 on bad arguments or a load error (message on stderr).
  - This repository's `.strict-delivery/context.yml`: `every: ["{paths.decisions}/in-force.md"]`; `kinds.plan` and `kinds.stream-block`: `"{paths.plan_state}/{plan}/handoff.md"`, `"{paths.plan_state}/{plan}/ledger.md"`, `"{paths.plans}/{plan}.md"`; `kinds.program`: `"{integration}/{paths.programs}/{program}/status.md"`; `kinds.program-controller` and `kinds.sync`: the status page, `"{integration}/{paths.programs}/{program}/streams.yml"`; `kinds.stream-block` also the status page; `roles` for `task_reviewer`, `final_reviewer`, `final_verifier`, `exception_reviewer`: `"{brief}"` and `playbook/review.md`. Spec §9's example is the source. The owner approves the exact file at the task review (programs design §7.1); a change is edited in before the commit.

**Input-domain dimensions:**
- File: absent (names init); a directory; a symlink; empty; YAML error with line; `schema` other kind or version; unknown top-level key (OQ-16); `kinds` key outside `KINDS`; `roles` key outside `ROLES`; a list holding a non-string, an empty string, a duplicate.
- Placeholders: each name; unknown `{x}`; `{paths.nokey}`; `{` unmatched; `}}`; two in one entry; `{integration}` not first; `{brief}` with text around it; an entry resolving to `../x`, `/x`, `a//b`, `./a`.
- `kind_of`: each kind; `stream-a-block`; `stream--block`; `stream-A-block`; `stream-a`; `block`; empty.
- `required`: order of `every`, kind and role; duplicates across lists; role `None`; role without a list; values missing for each placeholder (unresolved, never dropped).
- `values_for`: program live and absent (no integration branch: `GateError`); `worktrees` resolution from a linked worktree root (P2.1's rule, never `--root`); `--stream` disagreeing with the kind.
- CLI: kind missing; unknown kind; repeated flag; `--json` (not accepted: a tool, not a gate); `--root` not a repo; exit codes 0, 1, 2.
- `absolute`: symlinked root (macOS `/tmp` to `/private/tmp`); relative brief; absolute brief.
- This repository's file validates and every entry resolves for `plan` with `--plan 2026-10-31-strict-delivery-framework`.

- [ ] **Step 1: Write the failing tests:**
  ```python
  # test_context_lib.py
  def test_required_orders_every_kind_role():
      assert [e for e, _ in required(CTX, "plan", "task_reviewer", VALS)] == ["{paths.decisions}/in-force.md", "{paths.plan_state}/{plan}/handoff.md", "{brief}"]
  def test_unresolved_placeholder_kept():
      assert ("{paths.plan_state}/{plan}/handoff.md", None) in required(CTX, "plan", None, {})
  def test_stream_kind_normalised():
      assert kind_of("stream-docs-block") == ("stream-block", "docs")
      with self.assertRaises(ValueError): kind_of("stream-A-block")
  def test_unknown_placeholder_refused():
      assert any("{x}" in e for e in context_errors({**ROW, "every": ["{x}/a"]}, cfg))
  def test_dotdot_after_substitution_refused():
      assert any(".." in e for e in context_errors({**ROW, "every": ["{paths.plans}/../a"]}, cfg))
  def test_role_key_must_be_a_role():
      assert any("roles" in e for e in context_errors({**ROW, "roles": {"nobody": ["a"]}}, cfg))
  def test_missing_file_names_init():
      with self.assertRaises(GateError) as cm: load(root_without_context, cfg)
      assert "/strict-delivery:init" in str(cm.exception)
  def test_integration_resolved_from_main_worktree():   # --root is the integration worktree; worktrees: ../w
      assert values_for(integ_root, cfg, "program", program=P)["integration"] == realpath(W + "/" + P + "/integration")
  def test_this_repository_context_resolves_for_plan():
      assert all(r is not None for _, r in required(load(REPO, cfg), "plan", None, {"plan": "2026-10-31-strict-delivery-framework"}))
  # test_context_cli.py
  def test_prints_absolute_reads():
      assert code == 0 and out.splitlines()[0] == "read " + realpath(root + "/.strict-delivery/state/decisions/in-force.md")
  def test_unresolved_exit_1():
      assert code == 1 and "unresolved {paths.plan_state}/{plan}/handoff.md: needs {plan}" in out
  ```
- [ ] **Step 2: Run the test command; expect FAIL.**
- [ ] **Step 3: Implement** the schema, `context.py`, `context_cli.py`; draft this repository's `context.yml`.
- [ ] **Step 4: Run the test command on both interpreters and `python3 -m gates run_all`; expect PASS** (no module declares `context` yet, so `gate_schema` does not check the file).
- [ ] **Step 5: Commit** `feat(lib): context.yml schema, lookup and the context command`, then checkpoint. The owner's approval of `.strict-delivery/context.yml` is ledgered verbatim before this commit.
- [ ] **Registration (after stream `context`'s PR has merged and Rq-5-1 has landed; run on `main` updated from the remote by the program controller, ledgered in this stream's plan ledger on the cleanup branch):** `python3 -m gates context plan --plan <this stream's plan slug>` exits 0; `test_context_command_registered` (in `tests/test_context_cli.py`, skipped with the reason `Rq-5-1 not on this branch` only while `"context" not in COMMANDS`) runs for real.

### Task 5a.2: read receipts, the receipt schema, `python3 -m gates receipt add`

**Files:**
- Create: `gates/schemas/receipt.yml`, `gates/lib/receipts.py`, `gates/tools/receipt_cli.py`
- Test: `tests/test_receipts_lib.py`, `tests/test_receipt_cli.py`

**Owner answers applied:** R5a-4; spec §5 (receipts git-ignored; `.gitignore` already holds `.strict-delivery/receipts/`); Appendix A ("Read receipts: a YAML file with a top-level `schema:` key").

**Interfaces:**
- Consumes: `schema.load_schema/validate`, `yamlsub.load/emit`, `config.load`, `result.GateError`.
- Produces:
  - `gates/schemas/receipt.yml` (`receipt/1`, `files: [{dir: receipts, glob: "*.yml"}]`): `schema` (`str`); `reads` (`list`; items `map {path: str, sha: sha}`). Exactly the two keys of spec §9.
  - `receipts.py`:
    - `SESSION_RE = "[A-Za-z0-9][A-Za-z0-9_-]{0,127}"`; `session_problem(key: object) -> str` (`""` when valid; a non-`str`, `/`, `.`, empty, 129 characters are refused).
    - `content_sha(path: str) -> str`: the 40-hex git blob id of the file's raw bytes (R5a-4); a non-regular file or an unreadable one raises `GateError`.
    - `record(root: str, cfg: dict, session: str, path: str) -> dict`: refuses a bad session key; resolves `path` with `os.path.realpath` (a relative path is joined to `root` first); computes `content_sha`; creates `<paths.receipts>/` when missing (a symlink or non-directory there raises `GateError`); opens `<session>.yml` with `O_WRONLY | O_APPEND | O_CREAT`, and writes `schema: receipt/1\nreads:\n` only when the file is empty, under `fcntl.flock(LOCK_EX)`; then the row as `yamlsub.emit` of a one-item list, each line indented two spaces, in one `os.write`. Returns the row. Parallel Read hooks of one session cannot interleave or lose rows.
    - `load(root: str, cfg: dict, session: str) -> list` of `{path, sha}` rows: `[]` when the file is absent; a file that fails `receipt/1` raises `GateError` naming it.
  - `receipt_cli.main(argv)` for `python3 -m gates receipt add --session S --path P [--root R]`: calls `record`, prints the row, exit 0; any refusal exits 1 with the reason on stderr. (The block-3 hook calls `record` directly; the command exists for people and tests.)

**Input-domain dimensions:**
- Session key: UUID; `a`; empty; `../x`; `a/b`; `.`; 128 and 129 characters; non-ASCII; `int`; `None`.
- Path: relative; absolute; through a symlink (recorded as the real path); outside the repository (recorded); a directory; a FIFO; missing; unreadable (mode 000); a file with CRLF (raw bytes hashed); an empty file (`e69de29b...`); binary bytes; a name with spaces, quotes, `#`, `: `, non-ASCII (emitted and re-loaded equal).
- Receipts directory: missing (created); a file; a symlink; read-only.
- Receipt file: absent; empty (header written); header present; a truncated last line from a crash (`load` fails naming the file; the next `record` still appends; the Read hook reports it and never blocks; no commit gate reads the file (Q-B5plan-5 (b)), and only `gate_context` for that session fails closed, naming the file and `delete it to start the session's receipts again`); 20 processes appending at once (all 20 rows present, the file loads).
- `content_sha` against `git hash-object --no-filters`: equal for every file above.
- CLI: flag missing, repeated; exit codes.

- [ ] **Step 1: Write the failing tests:**
  ```python
  def test_record_appends_path_and_blob_id():
      row = record(root, cfg, SID, "a.txt")
      assert row == {"path": realpath(root + "/a.txt"), "sha": git_hash_object_no_filters(root, "a.txt")} and load(root, cfg, SID) == [row]
  def test_symlink_recorded_as_real_path():
      assert record(root, cfg, SID, "link.txt")["path"] == realpath(root + "/a.txt")
  def test_bad_session_refused():                 # subTests: "", "../x", "a/b", "x" * 129, 3
      with self.assertRaises(GateError): record(root, cfg, s, "a.txt")
  def test_parallel_appends_keep_every_row():     # 20 subprocesses
      assert len(load(root, cfg, SID)) == 20
  def test_awkward_names_round_trip():            # "a: b#c 'd\".md", non-ASCII
      assert load(root, cfg, SID)[0]["path"].endswith(NAME)
  def test_file_validates_against_receipt_schema():
      assert validate(load_schema(RECEIPT_YML), yamlsub.load(full, rel), cfg) == []
  def test_directory_path_refused():
      with self.assertRaises(GateError): record(root, cfg, SID, "dir")
  ```
- [ ] **Step 2: Run the test command; expect FAIL.**
- [ ] **Step 3: Implement** the schema, `receipts.py`, `receipt_cli.py`.
- [ ] **Step 4: Run the test command on both interpreters and `python3 -m gates run_all`; expect PASS.**
- [ ] **Step 5: Commit** `feat(lib): read receipts and the receipt schema`, then checkpoint.
- [ ] **Registration (as 5a.1's, after Rq-5-1):** `python3 -m gates receipt add --session t --path README.md` in a scratch clone exits 0; `test_receipt_command_registered` runs for real.

### Task 5a.3: `gate_context`; enforcement by profile; the producer declaration

**Files:**
- Create: `gates/gate_context.py`
- Modify: `gates/lib/context.py` (additive: `enforced`)
- Test: `tests/test_gate_context.py`

**Owner answers applied:** R5a-1, R5a-2, R5a-3, R5a-5; spec §12 ("context read receipts | advisory | advisory | enforced"); Q-B5plan-4 (a) (the promise stated for roles that neither dispatch nor commit); Q-B5plan-5 (b) (receipts not declared).

**Interfaces:**
- Consumes: `context.*` (Task 5a.1), `receipts.load/content_sha/session_problem` (Task 5a.2), `result.*`, `config.load`.
- Produces:
  - `context.enforced(cfg: dict) -> bool`: `cfg["profile"] == "strict"`.
  - `gate_context`: `PRODUCES = ("context",)` (Q-B5plan-5 (b): `gate_schema` never reads the git-ignored receipts, and `receipts.load` validates a receipt file against `receipt/1` for `gate_context` alone, which fails closed on a bad one as `context.input`; spec edit S5-8; R5a-5); `check(args: list) -> Result` (gate `context`); `main(argv=None) -> int`. Arguments: `--root`; `--session KEY` (required); `--kind KIND` (required); `--role ROLE`; `--plan`, `--program`, `--stream`, `--brief`. A missing or invalid required argument, an unknown kind or role, or a `context.load` error fails `context.input` (a missing `context.yml` names `/strict-delivery:init`).
  - Lines:
    - `context.unresolved.<entry>`: a required entry with no value for a placeholder.
    - `context.file.<path>`: a resolved required path that is not a readable regular file now.
    - `context.read.<path>`: no receipt row in the session's file has that `path` (fail reason `not read in this session`), or no such row's `sha` equals `content_sha(path)` now (fail reason `read at <sha>, now <sha>: read it again`, giving the newest row's sha).
    - One `PASS context.reads` when nothing failed. A session with no receipt file and a non-empty list fails each `context.read.*`. An empty required list prints `PASS context.reads` (never an empty run).
  - The narrow promise, stated in the module docstring and in Task 5a.3's report: the gate checks the reads of the session that makes a dispatch or a commit through Claude Code. It does not check reads of a role that neither dispatches nor commits (reviewers, verifiers, investigators): for them the context list is printed, not gated (Q-B5plan-4 (a)). A receipt proves the file was opened at that content, not that it was read in full (R5a-4: the Read tool truncates long files even without offset or limit, so a full read cannot be told apart).

**Input-domain dimensions:**
- argv: each required flag missing, empty, repeated; `--session ../x`; unknown kind; unknown role; `--json` first and later; `--root` not a repo; missing config; missing `context.yml`.
- Receipts: none; one row matching; a row with another sha and a later matching row (passes: any row matching); only a stale row; a row for a symlink path vs a required path through the real path (both realpath: match); a corrupt receipt file (`context.input`).
- Required files: present; deleted after the read (`context.file`); replaced by a directory; unreadable.
- Lists: empty; `every` only; kind and role overlapping; an unresolved placeholder with and without a receipt.
- Profiles: `light`, `standard`, `strict`: identical lines and exit codes; `enforced` true only on `strict`.
- Producer: once declared, `gate_schema` checks `context.yml` (required: a missing one fails `schema.context.<path>: missing`); this repository passes. Receipts (Q-B5plan-5 (b)): a truncated receipt file and a `receipts` path that is a symlink: `check schema` and `run_all` pass and `gate_context` for that session fails `context.input` naming the file.

- [ ] **Step 1: Write the failing tests:**
  ```python
  def test_all_read_passes():
      assert out.strip() == "PASS context.reads" and code == 0
  def test_missing_read_fails_naming_path():
      assert "FAIL context.read." + realpath(INFORCE) + ": not read in this session" in out and code == 1
  def test_stale_read_fails_with_both_shas():
      assert "read at " + OLD + ", now " + NEW in out
  def test_reread_after_change_passes():
      assert code == 0
  def test_unresolved_placeholder_fails():
      assert "FAIL context.unresolved.{paths.plan_state}/{plan}/handoff.md" in out
  def test_same_result_every_profile():           # subTests light, standard, strict
      assert (out, code) == (strict_out, strict_code)
  def test_enforced_only_on_strict():
      assert [enforced({**cfg, "profile": p}) for p in ("light", "standard", "strict")] == [False, False, True]
  def test_missing_context_file_names_init():
      assert out.startswith("FAIL context.input:") and "/strict-delivery:init" in out
  def test_empty_list_passes():
      assert out.strip() == "PASS context.reads" and code == 0
  def test_producer_makes_context_yml_required():   # fixture repo, PRODUCER_MODULES patched to include gates.gate_context
      assert "FAIL schema.context..strict-delivery/context.yml: missing" in schema_out
  ```
- [ ] **Step 2: Run the test command; expect FAIL.**
- [ ] **Step 3: Implement** `gate_context.py` and `context.enforced`.
- [ ] **Step 4: Run the test command on both interpreters and `python3 -m gates run_all`; expect PASS.**
- [ ] **Step 5: Commit** `feat(gates): gate_context checks a session's required reads`, then checkpoint.
- [ ] **Registration (after stream `context`'s PR has merged and Rq-5-1 and Rq-5-2 have landed, on `main` updated from the remote):** run `python3 -m gates check schema` (now checks `.strict-delivery/context.yml`; never local receipts, Q-B5plan-5 (b)) and `python3 -m gates check context --session <a receipt file of this session> --kind plan --plan <slug>`; expect PASS for the first, and for the second the lines the receipts warrant. `test_gate_context_registered` and `test_gate_context_declared_producer` run for real.

**Block 5a end (after Step 5, before any Registration step):** final review, verifier, checkpoint; stream `context` is finished, and its PR to `main` follows the flow at the top of this section. The Registration steps of 5a.1-5a.3 run after that PR has merged and Rq-5-1/Rq-5-2 have landed.

---

## Block 5b: `INDEX.md` and `gate_index` (stream `docs`, group `index`, branch `<program>/docs/index`)

### Task 5b.1: `overview/2`: specs and plans by state, live programs

**Files:**
- Modify: `gates/tools/index.py` (render of `INDEX.md`), `gates/schemas/overview.yml` (version 2)
- Test: `tests/test_index.py`

**Owner answers applied:** OQ-13 (the later sections in `overview/2`); R5b-1 (migration by regeneration); programs design §9; Q-Pplan-8 (a), Q-Pplan-12 (a).

**Interfaces:**
- Consumes: `index.render` (Task 1c.3, extended), `programs.live_programs/load_program/status_rows/branch_of`, `checkpoints.parse_handoff/plan_slug`, `cleanup.final_merge`, `store.Store`, `decisions.in_force`, `gitinfo.show/ls_tree/tracked_files/deleted_paths` (Rq-5-4), `yamlsub.parse`.
- Produces:
  - `gates/schemas/overview.yml`: `version: 2`, `first_line: "<!-- schema: overview/2 -->"`, `headings` exactly `## Architecture`, `## Specs and plans`, `## Live programs`, `## Open findings`, `## In-force decisions`.
  - `INDEX.md` (`render`'s `<paths.index>` entry), every line derived, nothing typed (programs design §9: "States are derived from git, plan ledgers and status pages"):
    - `## Architecture`, `## Open findings`, `## In-force decisions`: as `overview/1`.
    - `## Specs and plans`, with `### Todo`, `### In progress`, `### Done`, each `none` when empty, entries sorted by path:
      - plan `<paths.plans>/<slug>.md` present in the working tree is **in progress** when `<paths.plan_state>/<slug>/handoff.md` is present (line `- <path> (block <handoff block>)`), or when it is a live program's `plan` or a stream's `plan` (line `- <path> (program <p>, stream <s>, block <status row block>)`); **done** when `final_merge(root, cfg, slug)` exists (`- <path> (merged <merge sha>; cleanup pending)`); **todo** otherwise. Precedence: done, then in progress, then todo, so a plan whose handoff is present and whose `final=yes` line passes (the cleanup branch, whose first commit adds that line, Q-Pplan-9 (a)) reads done. On `main` between the work PR's merge and the cleanup PR's merge, `final_merge` at `HEAD` is `None` (the line is only on `cleanup/<slug>`), so the plan reads in progress there; stated, not hidden.
      - plan deleted from `<paths.plans>` in history reachable from `HEAD` (`deleted_paths`, `*.md` directly under it): **done**, `- <path> (merged <final_merge merge sha>)`, or `(merge not recorded)` when `final_merge` is `None`.
      - spec under `<paths.specs>`: **in progress** when the `spec` list of a present handoff, or of a stream handoff at its stream branch tip, names it; **done** when deleted in history; **todo** otherwise.
    - `## Live programs`: per program of `live_programs`, sorted, `### <program>`, read at `<program>/integration`. It lists the status rows as lines `- <stream> | <block> | <status> | used <used> of <estimate> | blockers <blockers> | pending <pending decisions>`; then `Open requests:` with one line per request in `open`, `accepted` or `disputed` (`- <id> <from_stream> -> <to_stream> <status>: <need>`); then `Pending owner questions:` with one line per id in the rows' `pending decisions` cells, joined with the open decision records at that ref (`- <id>: <question>`, or `- <id>: no open record`); `none` for each empty list.
    - No content line starts with `## `: every derived line starts with `- `, a fixed label or `### `, and cell or question text is passed through as is after that prefix (newlines become `\n` by `safe_text`).
  - `render` stays byte-identical across runs and interpreters; it raises `GateError` naming the file for a program or handoff that does not load.
  - Migration: none registered (R5b-1). `regenerate` overwrites an `overview/1` file.

**Input-domain dimensions:**
- Plans: none; present with a handoff; present in a live program (stream plan and program plan); present with a final merge; present with a handoff and a passing final merge (done wins); on `main` after the work PR and before the cleanup PR (in progress); present with only `final=no` lines (still in progress or todo); deleted with and without a final merge; deleted, re-added (present wins); a non-`.md` file; a nested file under `<paths.plans>/x/` (not a plan).
- Specs: named by a working-tree handoff; named only by a stream handoff at a stream tip; named by none; deleted; a handoff whose `spec` names a missing file (listed in progress, with the name as given).
- Live programs: none (`none`); two, sorted; a status row with `\|` in `delivers`; text starting `## `; a request in each of the five statuses; a pending id with an open record, an answered record, no record; an integration branch whose `streams.yml` does not parse (`GateError`).
- History: shallow clone (deleted plans unknown: `deleted_paths` returns what it can see; stated); a repository with no commits beyond the root.
- Old file: an `overview/1` `INDEX.md` present before `regenerate` (overwritten; `gate_schema` passes after).
- Idempotence and both interpreters.

- [ ] **Step 1: Write the failing tests:**
  ```python
  def test_overview_2_headings():
      assert headings(files[INDEX_MD]) == ["## Architecture", "## Specs and plans", "## Live programs", "## Open findings", "## In-force decisions"]
      assert files[INDEX_MD].splitlines()[0] == "<!-- schema: overview/2 -->"
  def test_plan_states():
      assert section(files[INDEX_MD], "### Todo") == ["- docs/strict-delivery/plans/t.md"]
      assert "- docs/strict-delivery/plans/p.md (block 2a)" in section(files[INDEX_MD], "### In progress")
  def test_deleted_plan_done_with_merge_commit():   # plan merged by --no-ff with a final=yes MERGED line, then cleaned
      assert "- docs/strict-delivery/plans/d.md (merged %s)" % MERGE in section(files[INDEX_MD], "### Done")
  def test_stream_plan_in_progress_from_status_row():
      assert "(program 20261101-x, stream a, block 5a)" in files[INDEX_MD]
  def test_live_program_requests_and_questions():
      assert "- %s a -> b open: need x" % RID in files[INDEX_MD] and "- %s: which?" % DEC in files[INDEX_MD]
  def test_no_content_line_is_a_heading():         # delivers text "## x"
      assert headings(files[INDEX_MD]) == EXPECTED_HEADINGS
  def test_overview_1_file_overwritten():
      regenerate(root, cfg); assert read(INDEX_MD).startswith("<!-- schema: overview/2 -->")
  def test_regenerate_is_idempotent():
      assert read_all(regenerate(root, cfg)) == read_all(regenerate(root, cfg))
  ```
- [ ] **Step 2: Run the test command; expect FAIL.**
- [ ] **Step 3: Implement** (waits on Rq-5-4 `deleted_paths`; until it is on `main` and the stream has updated, the stream raises it and works on nothing else in this group).
- [ ] **Step 4: Run the test command on both interpreters, `python3 -m gates index`, `python3 -m gates run_all`; expect PASS and a clean tree.**
- [ ] **Step 5: Commit** `feat(tools): overview/2: specs and plans by state, live programs`, then checkpoint.

### Task 5b.2: `gate_index`; `gate_cites` enabled

**Files:**
- Create: `gates/gate_index.py`
- Test: `tests/test_gate_index.py`

**Owner answers applied:** R5b-2, R5b-3; stream rules "Cross-stream order" (`cites` in `run_all`); D4 (whatever the owner ruled in block 2).

**Interfaces:**
- Consumes: `index.render`, `schema.load_schema/validate/validate_markdown/SCHEMAS_DIR`, `gitinfo.tracked_files/is_ignored` (Rq-5-4), `result.*`, `config.load`; reads `run_all.PROFILE_GATES` and `__main__.GATES` in tests only.
- Produces: `gate_index`: `PRODUCES = ()`; `check(args: list) -> Result` (gate `index`); `main(argv=None) -> int`. Argument `--root`. Lines:
  - `index.render`: `index.render(root, cfg)` raised (`GateError` text, or the exception type and text); the gate stops after this line.
  - `index.valid.<path>`: a rendered text fails its kind's schema (`validate` of the parsed YAML, or `validate_markdown`).
  - `index.tracked.<path>`: a generated path is in `tracked_files(root)` (the index, so a staged `git add -f` counts): "generated; never commit it: `git rm --cached <path>`".
  - `index.ignored.<path>`: a generated path is not ignored (`is_ignored`): "add it to `.gitignore` (spec §5)".
  - One `PASS index.<check>` for each of `render`, `valid`, `tracked`, `ignored` when nothing in it failed.
- `gate_cites` enabled: the test `test_cites_enabled` asserts `GATES["cites"] == "gates.gate_cites"` and that `"cites"` is in `PROFILE_GATES["standard"]` and `PROFILE_GATES["strict"]`, and in `PROFILE_GATES["light"]` exactly as D4 was ruled. No file of stream C or of `run_all` is edited here. If the assertion fails, the stream raises a request to `run_all`'s owner, never a local edit.

**Input-domain dimensions:**
- Generated paths: each of the four tracked (committed; staged only); ignored and not ignored; a path ignored through a negated pattern (`!INDEX.md`: not ignored).
- Render: a record that fails to load (render raises); a program that does not load; an empty repository; config `paths.index` moved.
- Valid: a render whose output fails its schema (monkeypatched render).
- argv: `--root` not a repo; missing config (`index.input` naming init); `--json`.
- Inside a git pre-commit hook with `GIT_INDEX_FILE` set.
- `run_all`: `index` runs on `standard` and `strict`, not on `light`.

- [ ] **Step 1: Write the failing tests:**
  ```python
  def test_clean_repo_passes():
      for c in ("render", "valid", "tracked", "ignored"): assert "PASS index." + c in out
      assert code == 0
  def test_tracked_generated_file_fails():         # git add -f docs/strict-delivery/INDEX.md (staged, not committed)
      assert "FAIL index.tracked.docs/strict-delivery/INDEX.md" in out and code == 1
  def test_unignored_generated_file_fails():
      assert "FAIL index.ignored." in out
  def test_render_error_stops():
      assert out.startswith("FAIL index.render:") and "index.tracked" not in out
  def test_gate_writes_nothing():
      assert listing_before == listing_after
  def test_missing_config_names_init():
      assert out.startswith("FAIL index.input:") and "/strict-delivery:init" in out
  def test_index_in_standard_and_strict_only():     # Rq-5-3; skipped with reason "Rq-5-3 not on this branch" until it lands
      assert "index" in PROFILE_GATES["standard"] and "index" in PROFILE_GATES["strict"] and "index" not in PROFILE_GATES["light"]
  def test_cites_enabled():
      assert GATES["cites"] == "gates.gate_cites" and "cites" in PROFILE_GATES["strict"]
  ```
- [ ] **Step 2: Run the test command; expect FAIL.**
- [ ] **Step 3: Implement** `gate_index.py` (waits on Rq-5-4 `is_ignored`).
- [ ] **Step 4: Run the test command on both interpreters and `python3 -m gates run_all`; expect PASS.**
- [ ] **Step 5: Commit** `feat(gates): gate_index`, then checkpoint.
- [ ] **Block 5b end:** final review, verifier, checkpoint; the stream controller merges `<program>/docs/index` into `<program>/docs/main`.
- [ ] **Registration (after stream `docs`'s PR has merged and Rq-5-1 and Rq-5-3 have landed, on `main` updated from the remote):** `python3 -m gates check index` and `python3 -m gates run_all` print `PASS index.*` on this repository; the two skipped tests run for real.

---

## Block 5c: `gate_drift` (stream `docs`, group `drift`, branch `<program>/docs/drift`)

### Task 5c.1: the drift library

**Files:**
- Create: `gates/lib/drift.py`
- Test: `tests/test_drift_lib.py`

**Owner answers applied:** SE-12 (stream and integration measured against `main`); R5c-2, R5c-3, R5c-5; Q-Pplan-8 (a), Q-Pplan-12 (a); Q-B5plan-3 (a).

**Interfaces:**
- Consumes: `programs.load_program/status_rows/branch_of/Program`, `checkpoints.parse_handoff/handoff_errors/plan_slug`, `gitinfo.is_ancestor/local_branches/parents/show/ls_tree/first_parent/upstream_of` (Rq-5-4), `store.Record`, `yamlsub.parse`, `config.load`.
- Produces (each returns a list of `(suffix, reason)`; `p` the program, `s` a stream id, `base` the tip of `base_branch`):
  - `decisions_at(root: str, cfg: dict, ref: str) -> list` of `store.Record`: the decision records under `<paths.decisions>` at `ref` (`ls_tree` + `show` + `yamlsub.parse`); a file that does not parse raises `GateError` naming it.
  - `merged_at(root: str, base: str, tip: str) -> Optional[str]`: the merge commit of R5c-5 (a first-parent commit of `base` with exactly two parents, the second equal to `tip`), else `None`.
  - `integration_errors(root, cfg, p) -> list`: `integration.<p>`: `base` is not an ancestor of `<p>/integration` ("integration is behind <base_branch>; run a sync").
  - `stream_errors(root, cfg, prog: Program, row: dict, stream: dict) -> list`, for the row's status:
    - `branch.<s>`: status `running`, `blocked` or `checkpoint` and no local branch `branch_of(p, s)`.
    - `behind.<s>`: the branch exists, status is not `merged`/`closed`, and `base` is not an ancestor of its tip ("behind <base_branch>; run a sync", SE-12); for a stacked stream, also the `stacked_on` stream's branch tip (R5c-3).
    - `base` (once per program, before the row checks; review F-B5p-6): when `upstream_of(root, base_branch)` is not `None` and is not an ancestor of the local `base_branch`, fail `update <base_branch> from the remote: git -C <checkout that has the base branch> fetch <remote>, then git -C <that checkout> merge --ff-only <remote>/<base_branch>` (Rq-5-5; block 3's Q-B3plan-3 (a)), read from local refs only (no network). A host merge reaches the local base branch only after a fetch.
    - `merged.<s>`: status `merged` or `closed` and `merged_at(root, base, tip)` is `None` (the reason adds `if the PR merged on the host, update <base_branch> from the remote`); or another status while the branch tip has a `merged_at` commit ("the stream has merged at <sha>; set status merged"). A `merged`/`closed` row whose branch is gone fails ("stream branches are kept until the program closes"; Q-B5plan-3 (a)).
    - `handoff.<s>`: status `running`, `blocked` or `checkpoint`: the handoff `<paths.plan_state>/<plan_slug(stream plan)>/handoff.md` at the branch tip is present, passes `parse_handoff` and `handoff_errors`, its `branch` equals `branch_of(p, s)`, its `head` is an ancestor of (or equal to) the tip, and the row's `block` and `next task` equal the handoff's `block` and `next_task`. Status `ready`: the row's `block` and `next task` are `none`.
    - `pending.<s>`: each id in `pending decisions` names a record in `decisions_at(root, cfg, "<p>/integration")` whose status is `open`; and every open record there with a topic `q:<plan slug of s>:<qid>` (Task P4.1's tag) is listed in that cell (spec §9: "pending decisions on a status page match open decision records").
    - `blockers.<s>`: each request id in `blockers` names a request of this program whose status is `open`, `accepted` or `disputed`.
  - `over_estimate(row: dict, pct: int) -> Optional[str]`: `None` when `used * 100 <= estimate * pct`; else `over <s> used=<used> estimate=<estimate> limit=<pct>%`. An `estimate` of 0 with `used` above 0 is over.
  - `host_errors(root, cfg, prog: Program, runner=subprocess.run) -> list` (with `--host`, Q-B5plan-2 (a)): per stream, `gh pr list --head <branch> --base <base_branch> --state all --json number,state,headRefOid,mergeCommit` run with `-R` unset (the repository of `root`'s remote) and a 30-second timeout. `host.<s>`: the status is `merged` but no PR is `MERGED` with `mergeCommit.oid` equal to `merged_at`'s commit; or a PR is `MERGED` while the status is not `merged`/`closed`. `host`: `gh` missing, unauthenticated, non-zero, timed out, or output that is not the expected JSON list fails, with the reason (fail-closed; no partial pass).

**Input-domain dimensions:**
- Local base: no upstream (no `base` failure); upstream equal; upstream ahead of local `main` after a `gh pr merge` (fails `base`, and a `merged` row's reason names the update); local ahead of upstream (passes).
- Git shapes: stream branch equal to `main` (an ancestor, not merged: R5c-5); one commit ahead; behind `main`; merged by `--no-ff` (second parent the tip); merged and then one more commit on the branch (tip no longer the second parent: `merged` fails, status not merged also has no merge: `behind` judged); a squash merge (no two-parent commit: not merged); a merge off the first-parent line (not merged); stacked stream behind its `stacked_on` branch; integration equal, ahead, behind `main`.
- Rows: each of the six statuses against each branch state (present, absent); `block`/`next task` equal, different, `none`; `pending decisions` naming an open, answered, withdrawn, missing record, and an open `q:` record not listed; `blockers` naming a request in each of the five statuses and one of another program.
- Handoffs at the tip: absent, invalid front matter, `branch` another branch, `head` not an ancestor (a rebased-away sha), `head` equal to tip, short sha.
- Estimates: `used` below, equal to, above the limit; `estimate` 0; `pct` 100 and 150; large integers.
- Host (Q-B5plan-2 (a)): `gh` absent; exit 1; auth error; timeout; invalid JSON; empty list; one merged PR whose merge commit matches, one that does not; an open PR for a merged row; two PRs for one head.
- Records: a decision file that does not parse at the integration tip.

- [ ] **Step 1: Write the failing tests** (fixture: `program create` on `20261101-x/integration`, streams `a` and `b`, branches cut from `main`, merges with `git merge --no-ff`):
  ```python
  def test_fresh_branch_is_not_merged():
      assert merged_at(root, MAIN, A_TIP_EQUAL_MAIN) is None
  def test_no_ff_merge_found():
      assert merged_at(root, MAIN, A_TIP) == MERGE
  def test_stream_behind_main_fails():
      assert ("behind.a", ANY) in stream_errors(root, cfg, prog, row("a", "running"), S["a"])
  def test_integration_behind_main_fails():
      assert integration_errors(root, cfg, P)[0][0] == "integration." + P
  def test_running_row_must_match_handoff():
      assert ("handoff.a", ANY) in stream_errors(root, cfg, prog, {**row("a", "running"), "next task": "5a.9"}, S["a"])
  def test_merged_status_without_merge_fails():
      assert ("merged.a", ANY) in stream_errors(root, cfg, prog, row("a", "merged"), S["a"])
  def test_merged_branch_with_running_status_fails():
      assert any("set status merged" in r for _, r in stream_errors(root, cfg, prog, row("a", "running"), S["a"]))
  def test_pending_must_be_open_and_complete():
      assert ("pending.a", ANY) in stream_errors(root, cfg, prog, {**row("a", "running"), "pending decisions": "none"}, S["a"])  # an open q:a-plan:q1 record exists
  def test_stacked_behind_parent_fails():
      assert ("behind.b", ANY) in stream_errors(root, cfg, prog, row("b", "running"), S["b"])
  def test_over_estimate():
      assert over_estimate({"stream": "a", "used": "16", "estimate": "10"}, 150) == "over a used=16 estimate=10 limit=150%"
      assert over_estimate({"stream": "a", "used": "15", "estimate": "10"}, 150) is None
  def test_host_failure_is_a_fail():               # runner raising FileNotFoundError, exit 1, bad JSON
      assert host_errors(root, cfg, prog, runner=bad)[0][0] == "host"
  ```
- [ ] **Step 2: Run the test command; expect FAIL.**
- [ ] **Step 3: Implement** `drift.py` (waits on Rq-5-4 `first_parent`).
- [ ] **Step 4: Run the test command on both interpreters and `python3 -m gates run_all`; expect PASS.**
- [ ] **Step 5: Commit** `feat(lib): drift facts: status rows and handoffs against git`, then checkpoint.

### Task 5c.2: `gate_drift`; `python3 -m gates drift report`

**Files:**
- Create: `gates/gate_drift.py`, `gates/tools/drift_cli.py`
- Test: `tests/test_gate_drift.py`, `tests/test_drift_cli.py`

**Owner answers applied:** R5c-1, R5c-2, R5c-4; Q-B5plan-2 (a).

**Interfaces:**
- Consumes: `drift.*` (Task 5c.1), `programs.live_programs/load_program/status_rows/status_errors`, `result.*`, `config.load`.
- Produces:
  - `gate_drift`: `PRODUCES = ()`; `check(args: list) -> Result` (gate `drift`); `main(argv=None) -> int`. Arguments: `--root`; `--program P` (repeatable; default every live program); `--host` (Q-B5plan-2 (a)). A named program that is not live fails `drift.input`. With no live program and no `--program`: one `PASS drift.none` (R5c-4).
  - Lines: `drift.base` once (5c.1's `base` check); then per program, read at `<p>/integration`: `drift.integration.<p>`; then per status row `drift.branch.<p>.<s>`, `drift.behind.<p>.<s>`, `drift.merged.<p>.<s>`, `drift.handoff.<p>.<s>`, `drift.pending.<p>.<s>`, `drift.blockers.<p>.<s>`; with `--host`, `drift.host.<p>.<s>` (and `drift.host.<p>` for a `gh` failure). One `PASS drift.<check>.<p>` per check with nothing failed. Rows are first validated with `status_errors`; an invalid page fails `drift.status.<p>` and the row checks are skipped for that program.
  - The estimate is not a gate line (R5c-2): `drift_cli.main(argv)` for `python3 -m gates drift report [--program P]... [--root R]` prints one `over_estimate` line per row over `drift.estimate_factor_pct`, or `none`; exit 0, or 1 when a program does not load.

**Input-domain dimensions:**
- argv: `--program` absent, repeated, not live, malformed; `--host` with and without (Q-B5plan-2 (a)); `--json`; `--root` a linked worktree (the integration worktree; refs shared); missing config.
- Programs: none live (`PASS drift.none`); one; two, sorted; an invalid status page; a `streams.yml` that does not load (`drift.input`).
- Every `stream_errors` failure surfaced under its line id; ordering by program, then stream, then check.
- Report: no row over; one over; `pct` from config 120; a program that does not load.
- Run from a stream worktree, from the integration worktree, from the main checkout: same lines.

- [ ] **Step 1: Write the failing tests:**
  ```python
  def test_no_program_passes_one_line():
      assert out.strip() == "PASS drift.none" and code == 0
  def test_in_sync_program_passes():
      assert "FAIL" not in out and code == 0
  def test_behind_main_fails_until_sync():          # main advanced; then the sync: merge main into integration and into a
      assert "FAIL drift.behind.%s.a" % P in before and "FAIL drift.integration." + P in before and code_after == 0
  def test_unknown_program_input():
      assert out.startswith("FAIL drift.input:")
  def test_invalid_status_page_skips_rows():
      assert "FAIL drift.status." + P in out and "drift.handoff." + P not in out
  def test_same_lines_from_every_worktree():
      assert out_main == out_integration == out_stream
  # test_drift_cli.py (R5c-2)
  def test_report_lists_over_rows():
      assert out.strip() == "over a used=16 estimate=10 limit=150%" and code == 0
  def test_report_none():
      assert out.strip() == "none"
  ```
- [ ] **Step 2: Run the test command; expect FAIL.**
- [ ] **Step 3: Implement** `gate_drift.py` and `drift_cli.py`.
- [ ] **Step 4: Run the test command on both interpreters and `python3 -m gates run_all`; expect PASS** (`run_all` does not run `drift`, R5c-1).
- [ ] **Step 5: Commit** `feat(gates): gate_drift; drift report`, then checkpoint.
- [ ] **Block 5c end (Rq-5-5 raised):** final review, verifier, checkpoint; the stream controller merges `<program>/docs/drift` into `<program>/docs/main`. Stream `docs` is finished after 5b and 5c, and its PR to `main` follows the flow at the top of this section.
- [ ] **Registration (after stream `docs`'s PR has merged and Rq-5-1 has landed):** `python3 -m gates check drift` on this repository's live program prints no FAIL after a sync; `test_gate_drift_registered` runs for real.

### Block 5 divergences (both quotes; settled by the rulings named)

- **D5-1 (estimate per block or per stream).** Spec §9: "a block past `drift.estimate_factor_pct` percent of its estimate is reported to the owner." Programs block, controller ruling: "a status row's `estimate` and `used` are non-negative decimal integers in the unit of the stream's `estimate` in `streams.yml`"; Task P2.2: `create` writes "`estimate` from `streams.yml`", and `status` has no `--estimate`. Ruled as R5c-2 (per row); spec edit S5-2.
- **D5-2 (warn vs the gate contract).** Spec §9: "it warns only (light, standard)". Spec §13: a gate "prints `PASS id` or `FAIL id: reason` lines"; `Result.render`'s text output prints no reason on a PASS line (only `--json` keeps it). Ruled as R5a-3; spec edit S5-1.
- **D5-3 (overview migration).** Appendix A: "`overview/2` with a migration". Task 2a.1: "`MIGRATIONS: dict` maps `(kind: str, from_version: int)` to a pure function `row -> new row`". Ruled as R5b-1; spec edit S5-3.
- **D5-5 (sync order).** Programs design §10: "`sync`: run by the program controller after every merge into the base branch, and at the start of each working day: run `gate_drift`; merge main into each stream branch that is behind it, ...". R5c-1 and Rq-5-5: drift runs first as quoted, and again "after the sync's merges, expecting PASS before the `SYNC` line", after a fetch of the base branch (review F-B5p-6: the local base branch lacks a host merge until fetched). Spec edit S5-7.
- **D4 (block 2's open divergence).** Whether `light` runs `cites`. Task 5b.2 asserts whatever the owner ruled and edits nothing; R5b-3 reads the light cell literally for `index`.

---

## Block 6 (streams `evidence`, `checkpoint`, `release`; sub-blocks 6E, 6K, 6R)

Spec §17 block 6: "`gate_checkpoint` in full, `gate_evidence` (section 13a), profile end-to-end tests, release 0.1.0." The plan outline adds "the mutation-transcript and review-report schemas", "the release script, `CHANGELOG.md`, and tag `v0.1.0`". The owner's Q-ES and Q-ES2 (ledger, 2026-11-01) add the advisory `loopstats` tool "in Block 6 next to gate_evidence", with the optional config `escape_cost`.

Blocks 3-6 run as one program after the programs block. The program plan names the program (`<program>` below). Block 6 adds three streams to it, with disjoint file ownership. Each stream has its own plan and one sub-block of at most 3 tasks:
- **6E, stream `evidence`** (Tasks 6E.1-6E.3): the two evidence schemas and their parsing library, `gate_evidence`, `loopstats`.
- **6K, stream `checkpoint`** (Tasks 6K.1-6K.2): `gate_checkpoint` in full. It extends Task P1.3's gate and Task P3.1's `checkpoint.merges`, and changes nothing else.
- **6R, stream `release`** (Tasks 6R.1-6R.3): the profile end-to-end tests, the release script and `CHANGELOG.md`, the release pull request and the tag.

**Parallelism.**
- 6E and 6K are PARALLEL. Their files are disjoint (ownership table below), and neither consumes the other.
- Inside 6E, Tasks 6E.1 and 6E.2 are SERIAL. Task 6E.3 is PARALLEL with them, as its own group branch. Its file set is disjoint from 6E.1-6E.2's (programs design §4.1: "Groups running at the same time own disjoint file sets"), because registry lines are requests to stream `package`, not edits made here.
- Inside 6K, Task 6K.2 follows 6K.1 (SERIAL).
- 6R is SERIAL after every other stream of the program. It starts only when 6E, 6K, every block 3-5 stream, and stream `package`'s Block 6 registry requests (Rq-6-1..Rq-6-4) have merged into `main`. 6R.1 tests the whole shipped gate set, and 6R.2-6R.3 bump files that blocks 3 and 4 create.

**Branches, worktrees, pull requests.** These follow programs design §11 and Task P2.2:
- Stream branches are `<program>/evidence/main`, `<program>/checkpoint/main` and `<program>/release/main`. Task 6E.3's group branch is `<program>/evidence/loopstats`. Each starts from `main` (Q-M4 (a)).
- Branches are pushed at every checkpoint (Task P1.3, `checkpoint.pushed`).
- A finished stream opens its own pull request to `main` (Q-M4 (a)). The owner approves in chat, naming the PR and its head sha. The controller then runs `gh pr merge <n> --merge --match-head-commit <sha>` (Q-15 (a)), reads the merge back from the host, and writes a `MERGED` ledger line (Task P1.2).
- Each stream has its own plan and opens one PR, so each of the three PRs is its plan's last. Each `MERGED` line therefore carries `final=yes`, and each plan's cleanup PR (Q-Pplan-9 (a)) follows it. The cleanup PRs are not part of this block.
- The commit gate is the test command on both interpreters plus `python3 -m gates run_all`, with a clean tree. Each checkpoint also runs `python3 -m gates check checkpoint --plan <the stream's plan slug>`.

**Ownership (stream rules, "File ownership"; controller ruling for the blocks 3-6 program: `gates/__main__.py`, `gates/producers.py`, `gates/run_all.py` and `tests/test_run_all.py` belong to block 3's stream `package`):**

| Stream | Owns |
|---|---|
| evidence | `gates/lib/evidence.py`, `gates/gate_evidence.py`, `gates/schemas/mutation-transcript.yml`, `gates/schemas/review-report.yml`, `gates/lib/loopstats.py`, `gates/loopstats.py`; `tests/test_evidence_lib.py`, `tests/test_gate_evidence.py`, `tests/test_loopstats.py` |
| checkpoint | `gates/gate_checkpoint.py`, `gates/lib/checkpoints.py`, `tests/test_gate_checkpoint.py`, `tests/test_checkpoints_lib.py` |
| release | `tests/test_profiles_e2e.py`, `scripts/release.py`, `tests/test_release.py`, `CHANGELOG.md`. From the `stream-ownership` decision of Task 6R.2 onward, also the version sites: `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, `CLAUDE.md`, `.gitignore`, `.strict-delivery/config.yml` |

**Requests to stream `package` (programs design §6; `R-` records minted by the program controller).** Each registry line lands only with or after its module. Stream `evidence` raises each request when its module's PR has merged into `main`. The receiver lands all four in one PR: `package` while it is live, else A (DS-3; controller ruling for all blocks). Until then, the tests in 6E that need a registry line are skipped with the reason `Rq-6-<n> not on this branch` (the Block 5 pattern). They run for real in `package`'s PR and in Task 6R.1.
- **Rq-6-1 `gates/__main__.py`:** `GATES["evidence"] = "gates.gate_evidence"`; `COMMANDS["loopstats"]`, a wrapper calling `gates.loopstats.main(argv)`.
- **Rq-6-2 `gates/producers.py`:** add `gates.gate_evidence`, which declares `("mutation-transcript", "review-report")`. From then on, `gate_schema` checks every transcript and review report.
- **Rq-6-3 `gates/run_all.py` and `tests/test_run_all.py`:**
  - `evidence` joins `PROFILE_GATES["standard"]` and `PROFILE_GATES["strict"]`, never `light`.
  - `evidence` also joins `BASE_GATES` (Q-B6plan-1 (a)).
  - The test asserts full literal tuples in the order the program plan fixes once for every block's `run_all` request (Task 2b.1's style). No test asserts a position such as "last".
- **Rq-6-4 `tests/test_run_all.py`:** `run_all --base x` forwards `--base` to `evidence` (Q-B6plan-1 (a)).

The owner answered this block's questions Q-B6plan-1..6 on 2026-11-02 (section "Owner answers", "Blocks 3-6 (2026-11-02)"); the task text states each answer.

**Owner answers applied across the block (binding):**
- **Q-ES (a), 2026-11-01:** "adopt Rules N and T as advisory signals (p<=0.10, half new; no reset on narrowing, narrowing noted; reviewer assigns one canonical dimension from the input table row names)". The finding fields `review_round`, `caused_by_change` and `dimension` landed in Task 1b.3 at bfe187c. "loopstats tool in Block 6 next to gate_evidence; rule text in stream B review playbook".
- **Q-ES2 (a), 2026-11-01:** "optional config escape_cost per severity (relative, in fix rounds), unset by default; loopstats prints the expected-value verdict as advice beside Rules N and T (Block 6)".
- **Protected `main`, Q-M4 (a), Q-15 (a):** as in "Programs block (2026-11-02)". The release reaches `main` by PR. The tag is pushed only on the owner's word.
- **Q-B2plan-21:** `tier4` is unset by default and `models.top_tier_fallback` defaults to `tier3`. Every `## Model` this block dispatches resolves the tier the way `gate_dispatch` checks it, and no model is named here.
- **Q-B2plan-24 (a):** no `gates.__version__`. The version sources are the files spec §4 lists, which Task 6R.2 bumps.
- **Q-Pplan-9 (a):** the cleanup is a follow-up PR by hand, and `merged` stays unreachable in v0.1.
- **Q-Pplan-12 (a):** global records written on the integration branch reach `main` only by the records PR at program close. Inside a program, `checkpoint.records` therefore reads records at `<program>/integration` (Task 6K.2).
- **Result interface (Task 1a.2):** `Result.passed(id)` takes no reason, and text output shows none. Every PASS line in this block is a bare id. Information that a passing line would carry is either its own line id or nothing. No change to `result.py` is planned.

**Interfaces consumed (by exact name; checked against `block/b1c` at 3094724 and the signed-off sections):**
- Block 1: `findings.validate/is_resolved/RESOLVED/SEVERITIES` and the finding fields of `finding.yml` (`pin {test, transcript}`, `evidence`, `owner {kind, plan, task}`, `severity`, `review_round`, `caused_by_change`, `dimension`); `findings._split` is private, so `evidence.py` keeps its own `<sha>:<path>` split with the same rule (`schema._SHA` head, first `:`); `store.Store(root, kind, cfg).load() -> [Record(id, row, file)]`; `gitinfo.show(root, ref, path) -> Optional[str]`, `ls_tree`, `commit_exists`, `blob_exists`, `merge_base`, `tracked_files`, `head_sha`; `yamlsub.parse`; `result.Result/Line/GateError/gate_args/run_check/run_gate`; `config.load`; `schema.load_schema/validate_markdown/produced_kinds/KNOWN_KINDS`; `helpers.make_repo/commit_all/write_record/GitIsolatedTestCase`.
- Block 2: `run_all.PROFILE_GATES/BASE_GATES/check/main`; `migrations.migrate/current_version`; `config/2` (Task 2c.2), with `escape_cost` (Q-B6plan-3 (a)).
- Programs block:
  - Task P1.1: `schema.validate_front_matter`, markdown `lines`;
  - Task P1.2: `checkpoints.parse_handoff/handoff_errors/checkpoint_lines/merged_lines/ledger_errors/plan_slug/resume_line`;
  - Task P1.3: `gate_checkpoint.check` with lines `checkpoint.input|handoff|ledger|agree|head|clean|pushed`; `gitinfo.current_branch/dirty_paths/is_ancestor/upstream_sha/remotes`;
  - Task P3.1: the line `checkpoint.merges` ("every `MERGED` line of the plan's ledger passes `merged_errors(root, cfg, plan, line)`");
  - Task P2.1: `programs.live_programs`.
- Blocks 3-5, from their drafts (block-3-draft.md, block-4-draft.md, block-5-draft.md), reconciled when the sections are spliced in. A different name is a plan edit, never a silent change:
  - block 3, stream `package`: `.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json`; `gates/lib/plugin.py` (`plugin.version`); the `run_all.version` line; the four registry files. Also `hook` (`python3 -m gates hook <event>`) for 6R.1's hook cases, and `playbook/review.md` with the Rules N and T text (Q-ES; the request below).
  - block 4:
    - `config.load` applies the profile presets, which set only `block.max_tasks` (light none, standard 5, strict 3). `rulings.max_per_block` has no preset, so it is absent and no cap applies ((4a) ruling).
    - `init` with an answers file, and `doctor`.
    - `tests/repo_fixtures.py` (Task 4e.3).
    - `templates.render` and `managed.put_block` (Tasks 4c.1-4c.2). The CI template renders its pin at `init` and holds no literal version (block 4, cross-block note to Block 6).
  - block 5:
    - `index` joins `run_all` under standard and strict (R5b-3).
    - `gate_context` and `gate_drift` are in no `run_all` list (R5a-1, R5c-1).
    - `context.enforced(cfg)` is true only on strict, and block 3's hooks refuse on it (R5a-3).
    - `drift.decisions_at(root, cfg, ref)`.

**Controller rulings (spec, plan or binding ruling settles each; ledgered in this form when the sub-block starts; at most five per sub-block):**
- (6E) Controller ruling: the pin command is rendered from `commands.test_one`, and the form decides how it runs.
  - A string template has every `{id}` replaced by `shlex.quote(<test id>)` and runs through `/bin/sh -c`.
  - A list template has `{id}` replaced literally inside each element and runs with no shell. Its display form is `shlex.join`.
  - Either form runs at `--root`, with the inherited environment and no timeout.
  - A template with no `{id}`, or of any other type, fails `evidence.config`.
  - Why: spec §6 "`test_one` (a template holding `{id}`) ... (each a shell string or list ...)", and §13a's examples `npx jest -t {id}`, which carry a bare `{id}`. Quoting the id means a test id holding `;` or a space cannot change the command.
  - Cost if wrong: a template that quotes `{id}` itself (`-t '{id}'`) is quoted twice and must drop its own quotes.
- (6E) Controller ruling: `gate_evidence` always prints `evidence.config` and `evidence.scope`, so a tree with no pinned finding passes, as Task 1c.2's empty registers do, and is never an empty run.
  - Why: spec §13 "an empty run fails (`<gate>.empty`)" covers a gate with no line at all, and `run_all` runs `gate_evidence` on every commit under standard and strict, before any finding exists.
  - Cost if wrong: every new project fails `run_all` until its first pin.
- (6E) Controller ruling: in a transcript, runs 1 and 3 must exit 0, and run 2 must exit non-zero and neither 126 nor 127 (the POSIX shell's "found but not executable" and "not found").
  - Why: spec §13a "fail with the fix reverted or with a mutant": a run 2 that only failed to start is no failing test.
  - Cost if wrong: a project whose test runner really exits 126 or 127 on a test failure cannot pin.
- (6E) Controller ruling: `loopstats` refuses (exit 1, writing nothing) when:
  - any finding of the task lacks `review_round` or `caused_by_change`;
  - a counted finding lacks `dimension`;
  - `escape_cost` is set without all four counted severities, each an integer of at least 0, with no `INFO` (never counted).
  - Once the numbers are computed, it exits 0 whatever the verdict.
  - Why: Q-ES "advisory signals" makes it no gate, and failing closed means statistics over a partly classified series cannot mislead the owner question they feed.
  - Cost if wrong: a task with legacy findings needs its fields filled before `loopstats` runs.
- (6K) Controller ruling: `live_subagents` is checked for type only (P1.2), never against running agents.
  - Why: a checkpoint is taken while siblings legitimately run. Parallel groups checkpoint one by one, and spec §10 "A controller never returns while its children run" is a rule about returning, not about a checkpoint, so no live count proves a checkpoint wrong. Block 3 does keep a per-session live-subagent store (SubagentStop hook; `live_total`, `live_children`) for `gate_dispatch`. That store is a hook-side approximation: an interrupted subagent with no SubagentStop transcript stays live until the next SessionStart (block 3, M4). Comparing it with the handoff would fail correct checkpoints. Spec §9 lists the field among the handoff's.
  - Cost if wrong: an orphan is caught only by the controller's own check (spec §8 "the controller checks for orphans"). A later version can compare `live_subagents` with block 3's store once M4 shows that the store is exact.
- (6K) Controller ruling: when the handoff names a `program`, `checkpoint.records` reads decision and finding records at the tip of the local branch `<program>/integration`, never in the stream worktree. A missing local branch fails the line, naming it.
  - Why: Q-Pplan-12 (a), and programs design §12 "the program controller ... is the only writer of global records within the program". A stream's handoff questions (Task P4.1) name records that exist only there. The live-program rule reads local branches (controller ruling P2, `programs.live_programs`).
  - Cost if wrong: a clone without that local branch fails its stream checkpoints until it fetches the branch.
- (6R) Controller ruling: the release script is `scripts/release.py`, run as `python3 scripts/release.py <version>`, not a `python3 -m gates` command.
  - Why: a target repository never releases the framework, and `gates/` ships into every adopter's plugin cache as the runtime. Spec §15 "A release script"; spec §3's layout lists what ships (spec edit SE6-3 adds the line).
  - Cost if wrong: the script moves into `gates/`.
- (6R) Controller ruling: the script bumps every version source on this repository that spec §4 requires to agree, and that holds a literal version: the plugin and marketplace versions, this repository's CLAUDE.md block version, its `.gitignore` block version, and its `framework_version`. The managed blocks are rewritten through block 4's `managed.put_block`. Templates render the version at `init` and hold none, so they are off the list.
  - Why: spec §4 "The plugin version, the CLAUDE.md block version, the CI pin (when the CI workflow is installed) and `framework_version` in config must agree; `doctor` and `run_all` fail when they do not". Spec §15 lists four of them (spec edit SE6-1).
  - Cost if wrong: one list edit.
- (6R) Controller ruling: the version sites belong to other streams, so the release stream gets them through an owner decision of class `stream-ownership`, which the program controller asks before Task 6R.2. That decision moves the five paths of the ownership table to `release` once their owning streams have merged. The decision is asked, never assumed.
  - Why: programs design §13: `stream-ownership` covers "moving a path between streams or assigning an unowned path". §12: "every changed path owned by the committing stream". `.gitignore` is owned by no block-4 stream (block 4: "No block-4 stream owns ... `.gitignore`").
  - Cost if wrong: if the owner declines, the release runs as a plain plan after the program closes, with the same tasks.
- (6R) Controller ruling: the script never commits, pushes, tags or merges. The tag `v0.1.0` (Q-B6plan-6 (a)) is annotated, sits on the release PR's merge commit, is created locally after the merge is read back, and is pushed only on the owner's word.
  - Why: protected `main` and Q-15 (a); spec §15 "Semver tags"; an unpushed tag can still move at no cost.
  - Cost if wrong: the tag is re-pointed before the push.

**Cross-block notes.**
- **Stream B / block 3 (Q-ES "rule text in stream B review playbook"):** Task B2.2's `review.md` carries no Rules N and T text yet. When 6E.3 starts, the owner of `playbook/review.md` (stream B, or A after DS-3) gets a cross-stream request for:
  - one paragraph in the fix-loop section, stating Rules N and T and the decision table of Task 6E.3, naming `python3 -m gates loopstats` and the `Loopstats:` ledger line;
  - its key-phrase row in `tests/test_playbook.py`.
  - This block does not edit that file.
- **Block 3, stream `package`:** Rq-6-1..Rq-6-4 above. The block-3 note on tag names (`<plugin-name>--v<version>`) is settled by Q-B6plan-6 (a): `v0.1.0` only.
- **Block 4:** `init` offers `escape_cost` only as a commented example (unset by default, Q-ES2). `doctor` needs nothing new. Block 4's note "block 6's `gate_checkpoint` in full counts tasks and ledger `Ruling` lines" matches Task 6K.1: rulings are counted from the ledger's `Ruling` lines by position (`ledger_rulings`), and the handoff's `rulings` must equal that count.
- **Block 5:** context enforcement and drift sit outside `run_all` (R5a-1, R5c-1). Task 6R.1 tests context through the hook and `context.enforced`, and leaves drift out of the gate set.

---

## Block 6E: evidence (stream `evidence`, branch `<program>/evidence/main`)

### Task 6E.1: the mutation-transcript and review-report schemas; `evidence.py`

**Files:**
- Create: `gates/schemas/mutation-transcript.yml`, `gates/schemas/review-report.yml`, `gates/lib/evidence.py`
- Test: `tests/test_evidence_lib.py`

**Owner answers applied:** OQ-16; OQ-18 (the `review-report` first line stays `gate_register`'s key); Q-plan-4 (the transcript is `<sha>:<path>` only); Q-rev2-3 (the transcript lies under `mutations/`); Q-B6plan-4 (b) (what the commands are compared with); controller rulings 6E (rendering, run-2 exit set).

**Interfaces:**
- Consumes: `schema.load_schema/validate_markdown` with P1.1's `lines`; `gitinfo.show`; `schema._SHA`; `ids.id_problem`.
- Produces:
  - `gates/schemas/mutation-transcript.yml`: `mutation-transcript/1`, markdown, `first_line: "<!-- schema: mutation-transcript/1 -->"`, `files: [{dir: plan_state, glob: "*/mutations/*"}]`.
    - Every file directly in a `mutations/` folder is a transcript. P1.1's segments match one level each, so a nested path under `mutations/` cannot be listed. `gate_evidence` refuses such a transcript (Task 6E.2), so `gate_schema` never misses one that is used.
    - `lines`:
      - `FINDING`: `FINDING <id>`, where the id is any `<PREFIX>-<YYYYMMDD>-<xxxx>` and the prefix is checked by `transcript_errors`;
      - `TEST`: `TEST <test id>`, the test id running to the end of the line, non-empty;
      - `MUTANT`: `MUTANT <how>`, free text to the end of the line, non-empty: a manual revert, or the `commands.mutate` run (spec §13a: "How the mutant is made is the project's choice");
      - `RUN`: `RUN <1|2|3> <fix|mutant> exit=<-?[0-9]+> command=<the command run, to the end of the line, non-empty>`.
    - Lines that do not start with a keyword are free text (the captured output, notes).
  - `gates/schemas/review-report.yml`: `review-report/1`, markdown, `first_line: "<!-- schema: review-report/1 -->"`, `files: [{dir: reviews, glob: "*/*.md"}]`.
    - `lines` form the review package, one group per pin:
      - `PIN`: `PIN <finding id> transcript=<sha>:<path>`, the sha matching `schema._SHA` (7-40 lowercase hex), compared with `pin.transcript` as a string;
      - `PIN-TEST`: `PIN-TEST <finding id> <test id to the end of the line>`;
      - `PIN-COMMAND`: `PIN-COMMAND <finding id> <command to the end of the line>`.
    - The rest is the report's free text. A report with no `PIN` lines is valid, since not every review pins.
  - `evidence.py`:
    - `render_pin(cfg: dict, test_id: str) -> tuple`: `(display: str, run: object)`, where `run` is the shell string or the argv list (controller ruling). It raises `GateError` naming `commands.test_one` when the key is absent, when it is neither a non-empty `str` nor a non-empty list of `str`, or when it holds no `{id}`. It also raises when `test_id` is empty or holds a newline.
    - `run_pin(root: str, run: object) -> int`: the exit code, from `subprocess.run(..., cwd=root, shell=isinstance(run, str))`, with output discarded. `OSError` returns 127.
    - `parse_transcript(text: str) -> dict`: `{finding, test, mutant, runs: [{n, phase, exit, command}]}`, in file order. It raises `ValueError` listing every `validate_markdown` error.
    - `transcript_errors(parsed: dict, finding_id: str, test_id: str, command: str, cfg: dict) -> list`. It checks:
      - exactly one each of `FINDING`, `TEST` and `MUTANT`;
      - `finding == finding_id`, with the finding prefix checked by `ids.id_problem`;
      - `test == test_id`;
      - exactly three `RUN` lines, numbered `1, 2, 3`, with phases `fix, mutant, fix`;
      - every run's `command == command`, where `command` is the package's `PIN-COMMAND` (Q-B6plan-4 (b));
      - the exit codes of the controller ruling.
    - `package_entries(text: str) -> dict`: finding id to `{transcript, test, command}`. It raises `ValueError` on schema errors, on a finding id with a `PIN` line but missing `PIN-TEST` or `PIN-COMMAND` (or the reverse), and on any of the three repeated for one id.
    - `split_cite(entry: str) -> Optional[tuple]`: `(sha, path)` when the text before the first `:` matches `schema._SHA` (the rule of `findings._split`) and the path is non-empty; else `None`.

**Input-domain dimensions:**
- `render_pin`:
  - Template forms: a string with one `{id}`, with two, with none; a list with `{id}` in one element, in none; an empty string; an empty list; a list holding a non-`str`; `int`; `bool`; `None`; `commands` absent; `test_one` absent.
  - Test ids: plain; with a space; with `'`; with `;`; with `$()`; non-ASCII; empty; with a newline.
  - Each rendered display, for strings and for lists.
- `run_pin`: exit 0, 1, 2; a missing program in list form (127); a shell `exit 3`; a signal-killed child (the negative code returned as given); `cwd` honoured.
- Transcript lines:
  - each keyword conforming; a trailing space; a missing field; `RUN 4`; `RUN 1 mutant`; `exit=` empty; `exit=+1`; `command=` empty;
  - a keyword mid-line; a leading space (free text); the first line missing, with a BOM, with CRLF;
  - two `FINDING` lines; no `MUTANT`; four `RUN` lines; runs out of order;
  - run 2 exiting 0, 1, 126, 127, -11, 255; run 1 exiting 1; run 3 exiting 1;
  - a command one character off; a finding id with another prefix; a test id with trailing spaces.
- Package lines: a full group; `PIN` without `PIN-TEST`; `PIN-TEST` repeated; two findings interleaved; `transcript=` with a 6-hex sha, with no path, with a path holding `:` (the first `:` splits); an id with the decision prefix.
- `split_cite`: a 7-hex and a 40-hex sha; 6; 41; uppercase hex; no `:`; an empty path; a path holding `:`.
- Every existing schema file still loads. `KNOWN_KINDS` already holds both kinds (Task 1b.1).

- [ ] **Step 1: Write the failing tests** (`tests/test_evidence_lib.py`; `T(...)` builds a transcript text from its keyword lines; `CFG` has `commands: {test_one: "runtests -k {id}"}`):
  ```python
  def test_render_string_quotes_id():
      assert render_pin(CFG, "adds totals")[0] == "runtests -k 'adds totals'"
      assert render_pin(CFG, "a;rm x")[0] == "runtests -k 'a;rm x'"
  def test_render_list_has_no_shell():
      d, run = render_pin({**CFG, "commands": {"test_one": ["runtests", "-k", "{id}"]}}, "a b")
      assert run == ["runtests", "-k", "a b"] and d == "runtests -k 'a b'"
  def test_render_refuses_bad_templates():     # subTests: no {id}, "", [], [1], 3, True, None, key absent
      with self.assertRaises(GateError): render_pin(bad_cfg, "x")
  def test_run_pin_exit_codes():
      assert run_pin(root, "exit 0") == 0 and run_pin(root, "exit 3") == 3 and run_pin(root, ["/no/such/prog"]) == 127
  def test_valid_transcript():
      p = parse_transcript(T(FINDING=F, TEST="t", MUTANT="revert", RUNS=[(1, "fix", 0), (2, "mutant", 1), (3, "fix", 0)], CMD=D))
      assert transcript_errors(p, F, "t", D, CFG) == []
  def test_run_two_exit_set():                 # controller ruling: 126 and 127 are no failing test
      for code, ok in [(1, True), (255, True), (-11, True), (0, False), (126, False), (127, False)]:
          assert (transcript_errors(parse_transcript(T(..., RUNS=[(1, "fix", 0), (2, "mutant", code), (3, "fix", 0)])), F, "t", D, CFG) == []) == ok
  def test_runs_order_and_count():             # subTests: 2 runs, 4 runs, 2-1-3, phases fix-fix-fix
      assert transcript_errors(parse_transcript(bad), F, "t", D, CFG)
  def test_command_must_equal_given_command():
      assert any("command" in e for e in transcript_errors(parse_transcript(T(..., CMD=D + " ")), F, "t", D, CFG))
  def test_transcript_schema_errors_raise():   # first line missing; "RUN 1 fix exit= command=x"
      with self.assertRaises(ValueError): parse_transcript(bad_text)
  def test_package_entries():
      assert package_entries(REPORT) == {F: {"transcript": SHA + ":" + TP, "test": "t", "command": D}}
  def test_package_group_incomplete_raises():  # PIN without PIN-COMMAND; PIN-TEST twice
      with self.assertRaises(ValueError): package_entries(bad_report)
  def test_report_without_pins_is_empty():
      assert package_entries("<!-- schema: review-report/1 -->\nprose\n") == {}
  ```
  Oracle (PC2): the production path (`parse_transcript` of a file committed in a temp repository and read back with `gitinfo.show`) against hand-written literal dicts. A generator also builds 200 seeded transcripts, each with a known verdict for a mutation of one field.
- [ ] **Step 2: Run the test command; expect FAIL.**
- [ ] **Step 3: Implement** the two schemas and `evidence.py`. Neither kind is declared until Rq-6-2 lands.
- [ ] **Step 4: Run the test command on both interpreters and `python3 -m gates run_all`; expect PASS.**
- [ ] **Step 5: Commit** `feat(lib): mutation-transcript and review-report schemas; evidence parsing`, then checkpoint.

### Task 6E.2: `gate_evidence`

**Files:**
- Create: `gates/gate_evidence.py`
- Test: `tests/test_gate_evidence.py`
- Requests: Rq-6-1 (`GATES`), Rq-6-2 (producers), Rq-6-3 and Rq-6-4 (`run_all`), raised when this stream's PR has merged.

**Owner answers applied:** Q-B6plan-1 (scope per profile); Q-B6plan-4 (command comparison); controller rulings 6E; OQ-4 (merge base with `base_branch`); Q-Pplan-9 (a).

**Interfaces:**
- Consumes: `evidence.*` (Task 6E.1), `findings.validate`, `store.Store`, `gitinfo.show/merge_base/commit_exists/blob_exists`, `config.load`, `result.*`.
- Produces:
  - `gate_evidence`: `PRODUCES = ("mutation-transcript", "review-report")` (read by `gate_schema` once Rq-6-2 lists the module). The implementer confirms that this repository has no file under `<plan_state>/*/mutations/` or `<reviews>/*/*.md` on `main`, and reports it.
  - `check(args: list) -> Result` (gate `evidence`), `main(argv=None) -> int`; `--root`, `--base REF` (default `base_branch`, as Task 1c.1).
  - Scope by profile (Q-B6plan-1 (a)):
    - `light`: only `PASS evidence.config` and `PASS evidence.scope` (spec §13a "light does not run it"). `run_all` does not list the gate under light.
    - `standard`: findings with a `pin` that are new or differ from their version at the merge base with `--base` (as Task 1c.2's `changed`).
    - `strict`: every finding row in the tree with a `pin`.
  - Lines:
    - `evidence.config`: when a row is in scope, `commands.test_one` renders (`render_pin` with the first row's test id); otherwise PASS.
    - `evidence.scope`: always PASS.
    - `evidence.package.<id>`: an evidence entry `<sha>:<path>`, with `path` under `paths.reviews`, reads (`show`) as a review report whose `package_entries` hold `<id>` with `test == pin.test` and `transcript == pin.transcript`, and whose `command` equals the transcript's three commands (Q-B6plan-4 (b)). The reason names what is missing or which field differs.
    - `evidence.transcript.<id>`: `pin.transcript`'s path sits directly in a `mutations/` folder (a deeper path fails, naming the rule). `show(sha, path)` parses, and `transcript_errors` is empty. The command it compares with is the package's `command` (Q-B6plan-4 (b)).
    - `evidence.rerun.<id>`: `run_pin(root, run) == 0` with the command rendered from the current config, on the working tree (spec §13a "re-runs the pin command on the fixed tree"). The reason gives the display and the exit code.
    - A finding row that fails `findings.validate` is skipped, since `gate_register` owns that failure. An unreadable register, or a missing config, is `evidence.input`.

**Input-domain dimensions:**
- Profile: each of the three. For strict, an unchanged pinned row is in scope; for standard it is out, and a changed one is in.
- Row status with a pin: `pinned`, `closed`, `merged` (fixtures only; `findings.validate` refuses it, so the row is skipped). A row with no pin.
- Package:
  - no review-report entry; an entry under another directory; a report at a sha without the group;
  - each of `test`, `command` and `transcript` one character off; two reports, only the second holding the group;
  - a report whose first line is missing.
- Transcript: valid; each `transcript_errors` failure; a path nested below `mutations/`; a blob that is not UTF-8.
- Command comparison (Q-B6plan-4 (b)): `test_one` changed after the transcript was written: package and transcript pass, and the re-run decides.
- Re-run: exit 0; exit 1; a missing program; a command that writes into the tree (the gate does not check cleanliness).
- Config: `test_one` absent with no row in scope (PASS); with rows in scope (FAIL `evidence.config`, and those rows' other lines are not run).
- `--base`: absent; an unknown ref (`evidence.input`); given twice (`_Once`).

- [ ] **Step 1: Write the failing tests** (`tests/test_gate_evidence.py`, calling `gate_evidence.main` directly; `pinned_repo(profile)` builds a repository with one pinned finding, its committed transcript and review report, and `test_one: "sh check.sh {id}"`, where `check.sh` exits 0 when the fix file holds `fixed`):
  ```python
  def test_strict_valid_pin_passes():
      assert ids(out) == ["config", "scope", "package." + F, "transcript." + F, "rerun." + F] and code == 0
  def test_rerun_fails_on_broken_tree():       # write "broken" into the fix file
      assert "FAIL evidence.rerun." + F in out and "exit 1" in out
  def test_transcript_with_passing_mutant_fails():
      assert "FAIL evidence.transcript." + F in out
  def test_nested_transcript_refused():
      assert "FAIL evidence.transcript." + F in out and "mutations/" in out
  def test_package_command_mismatch_fails():
      assert "FAIL evidence.package." + F in out and "command" in out
  def test_changed_test_one():                 # Q-B6plan-4 (b): package and transcript pass, re-run decides
      assert ("FAIL evidence.transcript." + F in out) == (answer == "a")
  def test_light_not_run():
      assert out.splitlines() == ["PASS evidence.config", "PASS evidence.scope"] and code == 0
  def test_standard_skips_unchanged_rows():    # Q-B6plan-1 (a)
      assert "evidence.rerun." + F not in out and code == 0
  def test_standard_checks_changed_rows():
      assert "FAIL evidence.rerun." + F in broken_changed_out
  def test_empty_register_passes():
      assert out.splitlines() == ["PASS evidence.config", "PASS evidence.scope"] and code == 0
  def test_missing_test_one_with_pin_fails():
      assert "FAIL evidence.config:" in out and "commands.test_one" in out
  def test_produces_both_kinds():
      assert gate_evidence.PRODUCES == ("mutation-transcript", "review-report")
  def test_check_evidence_registered():        # skipped "Rq-6-1 not on this branch" while "evidence" not in GATES
      assert subprocess_out("python3 -m gates check evidence").startswith("PASS evidence.config")
  ```
- [ ] **Step 2: Run the test command; expect FAIL.**
- [ ] **Step 3: Implement** `gate_evidence.py`.
- [ ] **Step 4: Run the test command on both interpreters and `python3 -m gates run_all`; expect PASS.**
- [ ] **Step 5: Commit** `feat(gates): gate_evidence`, then checkpoint.

### Task 6E.3: `loopstats` (group branch `<program>/evidence/loopstats`, PARALLEL with 6E.1-6E.2)

**Files:**
- Create: `gates/lib/loopstats.py`, `gates/loopstats.py`
- Test: `tests/test_loopstats.py`
- Request: Rq-6-1 (`COMMANDS["loopstats"]`), raised with the stream's others.

**Owner answers applied:** Q-ES (a), Q-ES2 (a); Q-B6plan-3 (a) (`escape_cost` declared in `config/2`); controller ruling 6E (refusals, advisory exit). The research and its formulas are in `.superpowers/sdd/2026-10-31-strict-delivery-framework-plans/edgecase-stopping-research.md`, §1 and §3.1-§3.3, with its sources cited there. Nothing is copied from another project.

**Definitions (research §1, as adopted):**
- Counted findings for a task: those with `owner.kind == plan`, `owner.plan == <plan slug>`, `owner.task == <task>`, `caused_by_change: true`, and `severity` in `CRITICAL, HIGH, MEDIUM, LOW`.
- `k` is `--rounds`, the number of reviews done so far. A clean review raises no finding, so `k` is given, not derived.
- `X_i` is the number of counted findings with `review_round == i`, for `i = 1..k`. `N = sum X_i` and `S = sum (i-1) X_i`.
- Novelty `nu_k` is the share of round `k`'s counted findings whose `dimension` appears on no counted finding of an earlier round. It is undefined when `X_k = 0`.
- Narrowings come from `--narrowed R`, which may repeat: the contract was narrowed after review `R`. They are noted and counted, and the series is never reset (Q-ES "no reset on narrowing, narrowing noted").

**Interfaces:**
- Consumes: `store.Store`, `findings.validate/SEVERITIES`, `config.load`, `result.GateError`.
- Produces (`gates/lib/loopstats.py`). All arithmetic is in `fractions.Fraction` and integers, apart from `u`:
  - `ALPHA = Fraction(1, 10)`, `NOVELTY = Fraction(1, 2)`, `FIX_ROUND_CAP = 5` (spec §10: "rounds 4-5 a fresh agent one tier up, then an owner question"), `COUNTED = ("CRITICAL", "HIGH", "MEDIUM", "LOW")`.
  - `trend(counts: list) -> dict`: `{N, S, p, u}`.
    - `p = P(S' <= S)`, where `S'` is the sum of `N` independent uniform draws on `{0..k-1}`, computed exactly by integer convolution as `Fraction(count, k**N)`.
    - `u = (S - N(k-1)/2) / sqrt(N(k^2-1)/12)`, a float (IEEE `sqrt` is correctly rounded), printed with its sign to 2 places. It is `None` when `N == 0` or `k < 2`.
  - `geo_fit(counts: list) -> dict`: `{q, boundary, a, R, E_next}`, using the truncated-geometric mean `m(q) = sum j q^j / sum q^j` over `j = 0..k-1`, which increases in `q`.
    - When `S == 0`: `q = 0`, `R = 0`, `E_next = 0`.
    - When `S/N >= (k-1)/2`: `boundary = True`, `q = 1`, `R = None` (unbounded), `E_next = Fraction(N, k)`.
    - Otherwise `q` solves `m(q) = S/N` by Fraction bisection on `(0, 1)`. It stops at the first midpoint where `m(mid) == S/N` exactly, else after 64 steps, taking the final midpoint. Then `a = N/(1-q^k)`, `R = a q^k` and `E_next = a(1-q)q^k`.
    - It is `None` when `k < 2` or `N == 0`.
  - `rule_n(counts, novelty) -> bool`: `k >= 2`, `X_k > 0`, `novelty >= NOVELTY` and `X_k >= X_{k-1}`.
  - `verdict(counts, novelty, narrowed: int) -> tuple`: `(word, reason)`, from research §3.3, checked in order:
    1. `X_k == 0` gives `CLEAN`;
    2. `k > FIX_ROUND_CAP` gives `ESCALATE` (`fix rounds exhausted`);
    3. `rule_n` gives `STOP_NARROW`, or `ESCALATE` when `narrowed >= 1`;
    4. `k < 3` gives `CONTINUE` (`insufficient data`);
    5. `p <= ALPHA` and the fit not at the boundary give `CONTINUE` (`converging`);
    6. otherwise: `ESCALATE` when `narrowed >= 1`; else `STOP_NARROW` when `novelty >= NOVELTY`; else `ESCALATE` (`same dimensions recur`).
  - `ev(counts, severities: dict, escape_cost: Optional[dict]) -> Optional[dict]`: `{value, verdict}`.
    - `value = E_next * sum_s (n_s / N) * escape_cost[s]`, where `n_s` is the count of counted findings of severity `s` over all rounds.
    - `verdict` is `continue` when `value > 1` (one fix round, the unit of `escape_cost`, Q-ES2), else `stop`.
    - It is `None` when `escape_cost` is unset or `geo_fit` is `None`.
  - `report(rows: list, plan: str, task: str, rounds: int, narrowed: list, cfg: dict) -> dict`. It raises `GateError` per the controller ruling, and on `review_round > rounds`, `rounds < 1`, or a narrowing outside `1..rounds-1`.
- Produces (`gates/loopstats.py`, the CLI): `main(argv) -> int` for `[--plan SLUG] --task TASK --rounds K [--narrowed R]... [--root R] [--json]`, with `--plan` required and matching `[a-z0-9][a-z0-9-]*`. On a refusal it exits 1 with `loopstats: <reason>`. Otherwise it exits 0 and prints exactly the lines below, with numbers rounded by `Fraction` (half to even) to 3 places:
  ```
  LOOPSTATS plan=<slug> task=<task> rounds=<k> X=<x1,...,xk> N=<n> S=<s> narrowed=<r1,..|none>
  RULE-T p=<p> u=<±u|n/a> q=<q|1(boundary)|n/a> R=<r|unbounded|n/a> E_next=<e|n/a>
  RULE-N nu=<nu|n/a> fired=<yes|no>
  EV <value=<v> -> continue|stop | unset: escape_cost not configured | n/a: no fit>
  VERDICT <CLEAN|CONTINUE|STOP_NARROW|ESCALATE> (<reason>)
  NOTE CRITICAL or HIGH findings caused by the change are fixed whatever the verdict      (only when round k holds one)
  Loopstats: <task> r<k>: X=<...> p=<p> q=<q> nu=<nu> -> <VERDICT>
  ```
  - The last line is the ledger line the controller copies. It is prose under `ledger/1`, whose keyword set it is not in (Q-Pplan-1 (a)).
  - The EV line is advice only and never changes `VERDICT` (Q-ES2 "as advice").
- `escape_cost` (Q-B6plan-3 (a)): declared in `config/2` by Task 2c.2, as an optional map `{CRITICAL, HIGH, MEDIUM, LOW}`, each an `int` with `min: 0`. All four are required when the map is present, unknown keys are refused (OQ-16), and there is no default. This task only reads it.

**Input-domain dimensions:**
- argv: `--plan` missing, empty, with `/`, `..`; `--task` missing or empty; `--rounds` 0, -1, `x`, `3.0`, absent; `--narrowed` 0, equal to `rounds`, repeated, non-integer; `--json` position; `--root` not a repository; an unknown flag.
- Rows:
  - excluded: another plan's or task's finding; owner kind `issue`; severity `INFO` (excluded from `X`, but still needs the fields); `caused_by_change: false`;
  - refused: `review_round` missing; `caused_by_change` missing; `review_round > rounds`; a row failing `findings.validate` (named);
  - `dimension` missing: refused on a counted finding, allowed on an uncounted one.
- Series: `k = 1, 2, 3, 5, 6`; `N = 0`; `S = 0`; flat; rising; halving; every research row (`4,5`, `4,5,3`, `4,5,3,5`, `8,4,2,1`, `6,3,1`, `6,2,0`, `3,3,3`); `X_k = 0` after findings.
- Novelty: all new; exactly half new (fires); none new; a dimension first seen on an uncounted finding (still new).
- Narrowings: none, one, two; the Makefile walk-through of research §3.3.
- `escape_cost`: unset; all four; one missing; `INFO` present; a negative; `bool`; a string; all zero (`stop`); a boundary fit (`E_next = N/k`).
- Determinism: one golden output, asserted byte for byte on every interpreter the CI matrix runs (Task 2b.3: 3.9 and 3.13 on two operating systems), and by both interpreters of the local test command.

- [ ] **Step 1: Write the failing tests** (`tests/test_loopstats.py`; the CLI tests call `gates.loopstats.main` directly):
  ```python
  RESEARCH = {(4, 5, 3, 5): "0.585", (8, 4, 2, 1): "0.005", (4, 5, 3): "0.431", (6, 2, 0): "0.007", (3, 3, 3): "0.580", (6, 3, 1): "0.040"}
  def test_trend_p_matches_research_and_brute_force():   # PC2: research table plus itertools.product enumeration
      for counts, want in RESEARCH.items():
          assert fmt3(trend(list(counts))["p"]) == want
          assert trend(list(counts))["p"] == brute_force_p(counts)    # sum over product(range(k), repeat=N), N <= 17
  def test_geo_fit_research_rows():
      g = geo_fit([8, 4, 2, 1]); assert g["q"] == Fraction(1, 2) and g["E_next"] == Fraction(1, 2)   # exact hit at the first midpoint
      assert fmt3(geo_fit([4, 5, 3])["q"]) == "0.882" and fmt3(geo_fit([6, 2, 0])["q"]) == "0.220"
      g = geo_fit([4, 5, 3, 5]); assert g["boundary"] and g["R"] is None and g["E_next"] == Fraction(17, 4)
      assert geo_fit([5, 0, 0])["q"] == 0 and geo_fit([5]) is None
  def test_boundary_iff_u_nonnegative():       # research §3.1; 400 seeded vectors
      for counts in seeded_vectors(400): assert geo_fit(counts)["boundary"] == (trend(counts)["u"] >= 0)
  def test_makefile_walkthrough():             # research §3.3, novelty 1, narrowed after review 2
      assert verdict([4, 5], 1, 0)[0] == "STOP_NARROW"
      assert verdict([4, 5, 3], 1, 1)[0] == "ESCALATE" and verdict([4, 5, 3, 5], 1, 1)[0] == "ESCALATE"
  def test_decision_table_rows():              # one subTest per table row
      assert verdict([3, 0], 0, 0)[0] == "CLEAN"
      assert verdict([8, 4, 2, 1], Fraction(1, 4), 0) == ("CONTINUE", "converging")
      assert verdict([1, 1, 1, 1, 1, 1], 0, 0)[0] == "ESCALATE"      # k=6 > FIX_ROUND_CAP
      assert verdict([3, 3, 3], Fraction(1, 4), 0)[0] == "ESCALATE" and verdict([3, 3, 3], Fraction(1, 2), 0)[0] == "STOP_NARROW"
  def test_ev_verdict():
      assert ev([8, 4, 2, 1], {"MEDIUM": 15}, COST_ALL_ONE)["verdict"] == "stop"
      assert ev([4, 5, 3, 5], {"MEDIUM": 17}, COST_ALL_ONE)["verdict"] == "continue"
      assert ev([4, 5], {"MEDIUM": 9}, None) is None
  def test_cli_refuses_unclassified_finding(): # controller ruling
      assert code == 1 and "review_round" in err and F in err
  GOLDEN = "LOOPSTATS plan=p task=1x.1 rounds=4 X=4,5,3,5 N=17 S=26 narrowed=2\n...\nLoopstats: 1x.1 r4: X=4,5,3,5 p=0.585 q=1(boundary) nu=1.000 -> ESCALATE\n"   # full literal at dispatch
  def test_cli_output_golden():                # fixture: counts 4,5,3,5, all MEDIUM, all new dimensions, --narrowed 2; runs in every CI cell
      assert out == GOLDEN
  def test_escape_cost_shape_refused():        # subTests: missing LOW, INFO present, -1, True, "2"
      assert code == 1 and "escape_cost" in err
  def test_loopstats_command_registered():     # skipped "Rq-6-1 not on this branch" while "loopstats" not in COMMANDS
      assert subprocess_out("python3 -m gates loopstats ...") == GOLDEN
  ```
- [ ] **Step 2: Run the test command; expect FAIL.**
- [ ] **Step 3: Implement** the library and CLI.
- [ ] **Step 4: Run the test command on both interpreters and `python3 -m gates run_all`; expect PASS.**
- [ ] **Step 5: Commit** `feat(gates): loopstats: advisory Rules N and T and the escape-cost verdict`, then checkpoint.
  - The stream controller merges the group branch into `<program>/evidence/main` after a clean review and green gates (spec §8).
  - It raises the `playbook/review.md` request (cross-block notes).
  - **Block 6E end:** final review, verifier, PR to `main` (`final=yes`), then Rq-6-1..Rq-6-4 to `package`.

---

## Block 6K: `gate_checkpoint` in full (stream `checkpoint`, branch `<program>/checkpoint/main`)

The basic gate (Task P1.3, with P3.1's `checkpoint.merges`) covers the spec §9 list: handoff front matter, the clean own worktree, the handoff's presence and the `CHECKPOINT` line, plus push and merges. "In full" adds what spec §8, §6 and the playbook table give `gate_checkpoint` beyond that:
- the block size cap of SD-R11, whose `enforced by` is `gate_checkpoint` (Task B2.1). Spec §8: "One block per agent context, at most `block.max_tasks` tasks". Spec §12: "block size cap | none | 5 tasks | 3 tasks";
- the rulings cap (spec §6 `rulings.max_per_block`);
- agreement between the handoff's facts and the registers and git;
- the last checkpoint's state (Q-B6plan-5 (a)).

### Task 6K.1: `checkpoints.py`: block task count, record agreement

**Files:**
- Modify: `gates/lib/checkpoints.py` (additive)
- Test: `tests/test_checkpoints_lib.py`

**Owner answers applied:** Q-B6plan-2 (d) (what counts as a task); Q-B6plan-5 (a) (the last line's state); Q-Pplan-1 (a); controller rulings 6K.

**Interfaces:**
- Consumes: `checkpoints.checkpoint_lines/parse_handoff` (Task P1.2), `findings.is_resolved`, `store.Record`, `gitinfo.ls_tree/show`, `yamlsub.parse`.
- Produces:
  - `ledger_tasks(lines: list, block: str) -> list`: the distinct `task` tokens of the `CHECKPOINT` lines of `block` that start with `<block>.` and have at least one more character, in first-seen order (`1a.1` under `1a`; not `block-end` or `merged`).
  - `plan_tasks(plan_text: str, block: str) -> list`: the `<block>.<rest>` ids of the plan's lines of the form `### Task <block>.<rest>:` or `#### Task <block>.<rest>:`, in order. A repeated id raises `ValueError`.
  - `ledger_rulings(ledger_text: str, block: str) -> int`: the number of `Ruling` lines in the block's segment of the ledger.
    - A `Ruling` line is one whose first token, taken by P1.1's rule (column 0, one trailing `:` removed), is `Ruling`.
    - P1.2's `Ruling: <what> -- <why> -- <cost if wrong> -- <spec cite>` form has no block field. So a line belongs to a block by position. The block's segment starts after the last `CHECKPOINT` line of another block that comes before the block's first `CHECKPOINT` line (or after the last `CHECKPOINT` line of any block, when the block has none yet), or at the file start. It runs to the end of the file.
    - Rulings made before a block's first checkpoint, and rulings after its last one, therefore count for it.
    - No `block=` field is added to P1.2's form, so no request goes to the programs block.
  - `cap_errors(handoff: dict, lines: list, plan_text: str, cfg: dict, rulings: int) -> list`, where `rulings` is `ledger_rulings` for the handoff's block:
    - The task count is both `ledger_tasks` and `plan_tasks`, with an error for each count over the cap (Q-B6plan-2 (d)).
    - The error is `block: <n> tasks in <source> exceed block.max_tasks <m>`, where `<source>` is `ledger` or `plan`, when `cfg["block"]["max_tasks"]` is set.
    - `rulings: <n> Ruling lines in the ledger exceed rulings.max_per_block <m>` when `cfg["rulings"]["max_per_block"]` is set (block 4: no preset, so a project sets it) and the ledger count `rulings > m`. The cap is judged on the ledger count, never on the handoff's self-reported number.
    - `rulings: handoff says <h>, ledger has <n>` when the handoff's `rulings` field differs from the ledger count. This check runs whether or not a cap is set.
    - A set value that is not an `int` of at least 1 (`bool` refused) raises `GateError` naming the key. An unset key gives no error.
  - `records_at(root: str, cfg: dict, ref: str, kind: str) -> list` of `store.Record`: the records of `kind` (`decision` or `finding`) under its configured directory at `ref` (`ls_tree`, `show`, `yamlsub.parse`). A file that does not parse raises `GateError` naming it. Block 5's `drift.decisions_at` does the same for decisions; at splice, the two are reconciled so that one calls the other, and neither is copied.
  - `record_errors(handoff: dict, findings: list, decisions: list) -> list`:
    - `findings_in_flight.<id>: no finding record`;
    - `findings_in_flight.<id>: resolved (status <s>)`;
    - `open_decisions.<id>: no decision record`;
    - `open_decisions.<id>: status <s>, not open`.
  - `last_line_errors(lines: list) -> list` (Q-B6plan-5 (a)): `last CHECKPOINT: gates=<g>` unless `gates == "PASS"`, and `last CHECKPOINT: tests <p>/<t>` unless `p == t`; `no CHECKPOINT line` when empty.

**Input-domain dimensions:**
- `ledger_tasks`: tokens `1a.1`, `1a.10`, `1a.` (no task), `1ab.1` under `1a` (no task), `block-end`, `merged`; a task repeated (counted once); other blocks' lines; an empty ledger.
- `plan_tasks`: `### Task 1a.1:` and `#### Task B2.1:` headings; a heading inside a code fence (counted as written: the rule is line-based, and the gate ignores fences; stated in the test); `### Task 1a.1 (only under ...)`, which has no colon right after the id (not counted, test pins it); a duplicate id; the block absent from the plan (0 tasks).
- `cap_errors`:
  - `max_tasks` unset, 1, 3, 5, 0, -1, `True`, `"3"`; counts at the cap, one over, under, from each source;
  - `max_per_block` with the same values; the ledger count at the cap and one over;
  - the handoff's `rulings` equal to the ledger count, one below it, one above it.
- `ledger_rulings`:
  - rulings before the block's first checkpoint, between its checkpoints, and after its last;
  - rulings of the previous block (not counted);
  - a block with no checkpoint yet;
  - an empty ledger;
  - `Ruling (x):` (counted, and refused by `ledger_errors` under Q-Pplan-1 (a));
  - `Ruling` mid-line or after leading spaces (not counted);
  - a block that appears again after another block's checkpoint (the segment starts after that other block's line, so only the latest run is counted; this is stated in the test).
- `records_at`: the ref missing (`GateError`); the directory absent at the ref (no records); an unparsable file; a non-record file name.
- `record_errors`: an id in flight that is open, planned, pinned, closed, merged, missing; an open decision that is answered, withdrawn, open, missing; empty lists.
- `last_line_errors`: `gates=PASS` with `5/5`; `gates=n/a`; `4/5`; only older lines red.

- [ ] **Step 1: Write the failing tests:**
  ```python
  def test_ledger_tasks_counts_prefixed_tokens_once():
      assert ledger_tasks(lines("1a 1a.1", "1a 1a.1", "1a 1a.2", "1a block-end", "1b 1b.1", "1a 1ab.1"), "1a") == ["1a.1", "1a.2"]
  def test_plan_tasks_reads_headings():
      assert plan_tasks("### Task 1a.1: x\n### Task 1a.2: y\n### Task 1b.1: z\n", "1a") == ["1a.1", "1a.2"]
  def test_cap_over_fails_and_unset_passes():  # Q-B6plan-2 (d): both sources
      assert cap_errors(H("1a", rulings=0), four_tasks, PLAN_FOUR, cfg_cap(3), 0) == [
          "block: 4 tasks in ledger exceed block.max_tasks 3", "block: 4 tasks in plan exceed block.max_tasks 3"]
      assert cap_errors(H("1a", rulings=0), four_tasks, PLAN_FOUR, cfg_cap(None), 0) == []
  def test_cap_bad_value_raises():             # subTests: 0, -1, True, "3"
      with self.assertRaises(GateError): cap_errors(H("1a", rulings=0), [], "", cfg_cap(v), 0)
  def test_rulings_cap():
      assert cap_errors(H("1a", rulings=6), [], "", cfg_rulings(5), 6) == ["rulings: 6 Ruling lines in the ledger exceed rulings.max_per_block 5"]
  def test_handoff_rulings_must_match_ledger():
      assert cap_errors(H("1a", rulings=2), [], "", cfg_rulings(None), 3) == ["rulings: handoff says 2, ledger has 3"]
  def test_ledger_rulings_segment():           # Ruling before 1b's first checkpoint counts for 1b; 1a's rulings do not
      text = HEAD + "Ruling: a -- b -- c -- d
CHECKPOINT 1a 1a.3 ...
Ruling: e -- f -- g -- h
CHECKPOINT 1b 1b.1 ...
Ruling: i -- j -- k -- l
"
      assert ledger_rulings(text, "1b") == 2 and ledger_rulings(text, "1a") == 1
  def test_records_at_reads_another_ref():     # decision committed only on branch p/integration
      assert [r.id for r in records_at(root, cfg, "p/integration", "decision")] == [D] and records_at(root, cfg, "HEAD", "decision") == []
  def test_record_agreement():
      assert record_errors(H(findings_in_flight=[CLOSED_F]), [rec(CLOSED_F, "closed")], []) == ["findings_in_flight.%s: resolved (status closed)" % CLOSED_F]
      assert record_errors(H(open_decisions=[D]), [], [rec(D, "answered")]) == ["open_decisions.%s: status answered, not open" % D]
  def test_last_line_only():                   # Q-B6plan-5 (a)
      assert last_line_errors(lines("1a 1a.1 tests=4/5 gates=PASS", "1a 1a.2 tests=5/5 gates=PASS")) == []
      assert last_line_errors(lines("1a 1a.2 tests=5/5 gates=n/a")) == ["last CHECKPOINT: gates=n/a"]
  ```
- [ ] **Step 2: Run the test command; expect FAIL.**
- [ ] **Step 3: Implement** the functions.
- [ ] **Step 4: Run the test command on both interpreters and `python3 -m gates run_all`; expect PASS.**
- [ ] **Step 5: Commit** `feat(lib): checkpoint block cap, rulings cap, record agreement`, then checkpoint.

### Task 6K.2: `gate_checkpoint` in full

**Files:**
- Modify: `gates/gate_checkpoint.py`
- Test: `tests/test_gate_checkpoint.py`

**Owner answers applied:** controller rulings 6K and P1 (not in `run_all`); Q-B6plan-2 (d), Q-B6plan-5 (a); Q-Pplan-12 (a); owner directive (push at checkpoints).

**Interfaces:**
- Consumes: Task 6K.1; Tasks P1.3 and P3.1's gate; `store.Store`; `gitinfo.commit_exists/is_ancestor/tracked_files/show`; `config.load`.
- Produces new lines, each with one bare `PASS` when clean. The P1.3 and P3.1 lines are unchanged:
  - `checkpoint.cap`: `cap_errors` is empty, with the plan read from the working tree at the handoff's `plan` and `rulings = ledger_rulings(<ledger text>, <handoff block>)`. It covers SD-R11, the rulings cap, and the agreement between the handoff's and the ledger's ruling counts.
  - `checkpoint.records`: `record_errors` is empty. Records are read by `store.Store` in the worktree for a plain plan, and by `records_at(..., "<program>/integration", ...)` when the handoff has `program` (controller ruling). An unreadable register is `checkpoint.input`.
  - `checkpoint.base`: the handoff's `base` is a commit and an ancestor of (or equal to) its `head`.
  - `checkpoint.files`: the handoff's `plan` and every `spec` entry are tracked files.
  - `checkpoint.last`: `last_line_errors` is empty (Q-B6plan-5 (a)).
  - Line order is fixed: `handoff, ledger, agree, head, clean, pushed, merges, cap, records, base, files, last`. When `checkpoint.handoff` or `checkpoint.ledger` fails, the lines that need the parsed file are not printed, as P1.3 already does for `agree`.
- This repository: the gate runs on its own plan workspace at every checkpoint from this task's commit on. The implementer runs it before the commit and lists any red line in the report. A red line on the live block stops the task NEEDS_DECISION.

**Input-domain dimensions:**
- Each new line, failing and passing, through the production entry `python3 -m gates check checkpoint --plan <slug>` on a temp repository.
- Profile presets: light (no cap), standard (5), strict (3); an `overrides` entry changing the cap (block 4's override form).
- `base`: not a commit; not an ancestor of `head`; equal to `head`; the short form.
- `files`: the plan untracked; a spec deleted; a spec renamed; two specs, one missing.
- `records`:
  - plain plan: as Task 6K.1, through the gate;
  - program: the record on `<p>/integration` only (PASS); the record only in the worktree (FAIL: the integration branch is the truth); `<p>/integration` absent locally (FAIL naming it); the decisions directory absent on it.
- `last`: per Q-B6plan-5 (a).
- Order: the exact id list above, with P3.1's `merges` in its place.
- This repository's migrated workspace.

- [ ] **Step 1: Write the failing tests:**
  ```python
  def test_full_checkpoint_passes():
      assert ids(out) == ["handoff", "ledger", "agree", "head", "clean", "pushed", "merges", "cap", "records", "base", "files", "last"] and code == 0
  def test_fourth_task_over_strict_cap_fails():   # strict preset; ledger and plan with 1x.1-1x.4
      assert "FAIL checkpoint.cap: block: 4 tasks in ledger exceed block.max_tasks 3" in out
  def test_light_has_no_cap():
      assert "PASS checkpoint.cap" in out
  def test_resolved_finding_in_flight_fails():
      assert "FAIL checkpoint.records" in out and CLOSED_F in out
  def test_program_records_read_from_integration():   # Q-Pplan-12 (a): open decision committed only on p/integration
      assert "PASS checkpoint.records" in out
  def test_program_without_local_integration_fails():
      assert "FAIL checkpoint.records" in out and "p/integration" in out
  def test_base_not_ancestor_fails():
      assert "FAIL checkpoint.base" in out
  def test_untracked_spec_fails():
      assert "FAIL checkpoint.files" in out
  def test_red_last_checkpoint_fails():        # Q-B6plan-5 (a)
      assert "FAIL checkpoint.last" in out
  def test_handoff_missing_prints_no_dependent_lines():
      assert "checkpoint.cap" not in out and "FAIL checkpoint.handoff" in out
  ```
- [ ] **Step 2: Run the test command; expect FAIL.**
- [ ] **Step 3: Implement** the five lines.
- [ ] **Step 4: Run the test command on both interpreters and `python3 -m gates run_all`. After the commit and push, run `python3 -m gates check checkpoint --plan <slug>`; expect PASS.**
- [ ] **Step 5: Commit** `feat(gates): gate_checkpoint in full: block cap, records, base, files, last line`, then checkpoint. **Block 6K end:** final review, verifier, PR to `main` (`final=yes`).

---

## Block 6R: profiles end to end, release, tag (stream `release`, branch `<program>/release/main`)

Starts only when every other stream of the program has merged into `main` (including `package`'s Block 6 requests), the integration branch has synced, and this branch starts from that `main`.

### Task 6R.1: profile end-to-end tests

**Files:**
- Create: `tests/test_profiles_e2e.py`
- Test: the same file

**Owner answers applied:** spec §12; spec §14 ("Profiles: the same fixture repository under each profile runs exactly the gates the profile table names"); Q-B6plan-1 (a); R5a-1, R5a-3, R5b-3, R5c-1; Q-B2plan-19 (a) (`dispatch` in no `run_all` list); D4 as answered.

**Interfaces:**
- Consumes:
  - block 4: `init` (non-interactive, answers file, profile) and `tests/repo_fixtures.py`, read and not changed. One fixture is used, the python one, because §14 says "the same fixture repository".
  - block 3: `python3 -m gates hook <event>`, and `run_all.version`.
  - block 5: `context.enforced`, `gate_context`.
  - this block: `gate_checkpoint`, `gate_evidence`.
  - `doctor`.
- Produces tests only. The oracle (PC2) is a literal written from spec §12 and the recorded rulings, never read from `PROFILE_GATES`. It compares sets: order is `test_run_all.py`'s concern (Rq-6-3).
  ```python
  # gate ids printed by run_all, the "run_all" line itself excluded
  EXPECTED = {
      "light":    {"schema", "register", "decisions"} | CITES_LIGHT,   # spec §12 light pre-commit cell; cites per D4
      "standard": {"schema", "register", "decisions", "claims", "cites", "index", "evidence"},   # claims: §12 row; cites: stream rules; index: R5b-3; evidence: §12 row, Rq-6-3
      "strict":   {"schema", "register", "decisions", "claims", "cites", "index", "evidence"},
  }
  # context, drift, dispatch, checkpoint, cleanup, streams: in no run_all list (R5a-1, R5c-1, Q-B2plan-19 (a), controller rulings P1/P3, streams only while a program is live)
  ```
  `CITES_LIGHT` is `{"cites"}` or `set()`, following the owner's D4 answer as recorded at dispatch.

**Input-domain dimensions:**
- Profile × gate in `run_all`: for every gate of any `EXPECTED` set, one seeded violation must turn `run_all` red under each profile whose set lists the gate, and leave it green under each that does not. The violations:
  - an unanswered decision cited in `docs/` (`decisions`);
  - a finding with an illegal transition (`register`);
  - a stale claim (`claims`);
  - a broken cite (`cites`);
  - a tracked generated index (`index`);
  - a pinned finding whose re-run fails in a changed row (`evidence`: red under standard and strict);
  - an unchanged pinned row whose re-run fails (strict red, standard green; Q-B6plan-1 (a));
  - a config with an unknown key (`schema`).
- Context × profile, through the hook (R5a-3), not through `run_all`: a dispatch with a required read missing is refused by `python3 -m gates hook PreToolUse` under strict, and allowed with the `context.*` FAIL lines printed as a warning under light and standard. `context.enforced(cfg)` is `True` only for strict.
- Drift: not in any `run_all` set. A drifted status row leaves `run_all` green under every profile, and `check drift` fails.
- `check checkpoint` × profile: a fourth task in one block passes under light and standard and fails under strict; a sixth task fails under standard.
- `doctor` is green after `init` under each profile.
- The gate set printed by `run_all` equals `EXPECTED[profile]` exactly.

- [ ] **Step 1: Write the failing tests:**
  ```python
  def test_run_all_gate_set_per_profile():     # subTests per profile
      assert gate_set(run_all_out(fixture(profile))) - {"run_all"} == EXPECTED[profile]
  def test_each_gate_red_exactly_where_listed():   # subTests per (profile, violation)
      assert (code != 0) == (gate in EXPECTED[profile])
  def test_evidence_scope_by_profile():
      assert red == {"light": False, "standard": False, "strict": True}   # unchanged pinned row, broken re-run
  def test_context_enforced_only_on_strict_through_hook():
      assert hook_refused == {"light": False, "standard": False, "strict": True} and all("FAIL context." in o for o in hook_out.values())
  def test_drift_outside_run_all():
      assert run_all_code_with_drift == {p: 0 for p in PROFILES} and check_drift_code != 0
  def test_checkpoint_cap_by_profile():
      assert fourth_task_fails == {"light": False, "standard": False, "strict": True} and sixth_task_fails["standard"]
  def test_doctor_green_after_init():
      assert doctor_code[profile] == 0
  ```
- [ ] **Step 2: Run the test command.** Expect PASS wherever blocks 2-6 already deliver the behaviour. The tests are kept either way, because this task's product is the pinned contract across blocks. The report lists the tests that failed.
- [ ] **Step 3: No production code.** A red test is a finding against the block that owns the behaviour. It is filed with `findings new` and raised to the session. This task does not fix another stream's code.
- [ ] **Step 4: Run the test command on both interpreters and `python3 -m gates run_all`; expect PASS.**
- [ ] **Step 5: Commit** `test(e2e): every profile runs exactly its gates`, then checkpoint.

### Task 6R.2: `scripts/release.py` and `CHANGELOG.md`

**Files:**
- Create: `scripts/release.py`, `CHANGELOG.md`
- Test: `tests/test_release.py`
- Before dispatch: the program controller asks the owner-only `stream-ownership` decision of the controller ruling (6R), moving the five version-site paths to `release`. Dispatch waits for the answer. If it is declined, the stream stops `BLOCKED`, and the release runs as a plain plan after the program closes.

**Owner answers applied:** controller rulings 6R (location, version sites, route, no commit or push or tag); spec §15; Q-B2plan-24 (a); Q-B6plan-6 (tag names; the script only prints them).

**Interfaces:**
- Consumes: `plugin.version` (block 3); `managed.put_block`, `templates.render` (block 4), used for the managed blocks so their begin markers are written exactly as `init` writes them; `config.load`.
- Produces:
  - `RELEASE_SITES`: the literal version sites of the controller ruling, reconciled at splice:
    - `.claude-plugin/plugin.json` (`"version": "<v>"`);
    - `.claude-plugin/marketplace.json` (the strict-delivery entry's `"version": "<v>"`);
    - this repository's `CLAUDE.md` block and `.gitignore` block (begin marker `version=<v>`, rewritten with `managed.put_block`);
    - `.strict-delivery/config.yml` (`framework_version: "<v>"`).
    - JSON sites are edited by exact text: the one `"version": "<old>"` occurrence of the right object.
  - `main(argv) -> int` for `python3 scripts/release.py <X.Y.Z> [--date YYYY-MM-DD] [--root R]`. It exits 1, writing nothing, when:
    - the argument is not `MAJOR.MINOR.PATCH` (decimal, no leading zeros);
    - the sites disagree on the current version (each disagreeing site is listed);
    - the new version is not greater than the current one (integer triples);
    - a JSON site does not match exactly once;
    - the tree is not clean;
    - the current branch is `base_branch`, or HEAD is detached;
    - `CHANGELOG.md` has no `## Unreleased` heading, has two, or the section under it is empty.
  - On success it rewrites each site's version and turns `## Unreleased` into `## <X.Y.Z> - <date>` (UTC today by default) under a new empty `## Unreleased`. It then prints the changed paths and the next commands (commit, push, PR, and after the merge, the tag command for `v0.1.0`, Q-B6plan-6 (a)). It never commits, pushes, tags or merges.
  - `CHANGELOG.md`:
    - line 1 `# Changelog`;
    - a sentence stating semver and that before 1.0 a breaking change comes with a migration (spec §15);
    - `## Unreleased`, holding the v0.1.0 notes as bullets by area: gates; tools; schemas and migrations; init, doctor and upgrade; the plugin (skill, prompt blocks, playbook, hooks); programs and streams; profiles.
    - No ids of this repository's records, no person's handle, nothing from any other project.

**Input-domain dimensions:**
- Version argument: `0.1.0`, `1.0.0`, `0.1`, `0.1.0.1`, `v0.1.0`, `01.0.0`, `0.1.0-rc1` (refused: v0.1 releases plain triples), empty; equal to current; lower; higher in each position.
- Sites: all agree; one differs; a JSON pattern matching twice; matching nowhere; a file missing; a managed block missing (refused, naming `init`); CRLF in a JSON file (bytes outside the version preserved).
- `CHANGELOG.md`: missing; no `Unreleased`; `Unreleased` empty; `Unreleased` as the last section; two `Unreleased` headings.
- Tree: clean; an untracked file; on `base_branch`; detached HEAD.
- `--date`: valid; `2026-02-30`; absent.
- A second run with the same version (refused: equal to current).

- [ ] **Step 1: Write the failing tests** (`tests/test_release.py`; each builds a temp repository holding the sites at version `0.0.0`, on branch `release-test`):
  ```python
  def test_bumps_every_site_and_nothing_else():
      assert code == 0 and changed_files(repo) == SITE_PATHS | {"CHANGELOG.md"}
      assert all(site_version(repo, s) == "0.1.0" for s in RELEASE_SITES)
  def test_bytes_outside_versions_unchanged():
      assert only_version_changed(repo)
  def test_disagreeing_sites_refused():
      assert code == 1 and ".claude-plugin/marketplace.json" in err and unchanged(repo)
  def test_not_greater_refused():              # subTests: 0.0.0; 0.0.1 -> 0.0.0
      assert code == 1
  def test_on_base_branch_refused():
      assert code == 1 and "main" in err
  def test_empty_unreleased_refused():
      assert code == 1 and "Unreleased" in err
  def test_changelog_rolled():
      assert "## Unreleased\n\n## 0.1.0 - 2026-12-01\n" in read(repo, "CHANGELOG.md")
  def test_never_commits_or_tags():
      assert head_before == head_after and tags(repo) == []
  def test_run_all_and_doctor_agree_after_bump():   # this repository cloned into a temp dir, script run, then run_all and doctor
      assert run_all_code == 0 and doctor_code == 0
  ```
- [ ] **Step 2: Run the test command; expect FAIL.**
- [ ] **Step 3: Implement** `scripts/release.py` and write `CHANGELOG.md`.
- [ ] **Step 4: Run the test command on both interpreters and `python3 -m gates run_all`; expect PASS.**
- [ ] **Step 5: Commit** `feat(release): release script and CHANGELOG`, then checkpoint.

### Task 6R.3: release v0.1.0 (session controller; process task)

**Files:**
- Modify (through the script only): the `RELEASE_SITES` files and `CHANGELOG.md`
- Records: the ledger's `MERGED` line with `final=yes`; a prose `Tag:` line

**Owner answers applied:** protected `main`; Q-M1 (this repository: `merge.mode: controller`); Q-15 (a); Q-B6plan-6 (a); controller rulings 6R.

- [ ] **Step 1:** On `<program>/release/main`, with a clean tree, run `python3 scripts/release.py 0.1.0` as its own command. Then run the test command on both interpreters and `python3 -m gates run_all`; expect PASS. Commit `release: v0.1.0`, push, and checkpoint. The checkpoint line carries the real `tests=` and `gates=` values, since this step runs both.
- [ ] **Step 2: Block 6R end.**
  - Final review (`final_reviewer`, `tier3`) and final verifier (`final_verifier`, at the tier `models.top_tier_fallback` names unless `tier4` is set) over the whole stream diff.
  - Open the PR to `main` (`gh pr create`). CI must be green on all four cells (Task 2b.3).
  - The owner approves in chat, naming the PR and its head sha. Then run `gh pr merge <n> --merge --match-head-commit <sha>` as its own command, and read the merge back (`gh pr view <n> --json number,headRefOid,mergeCommit,mergedAt,mergedBy`).
- [ ] **Step 3:** Run `git fetch origin`. Then run `git worktree add --detach <a mktemp -d path> <merge commit>`; no agent merges or commits while the base branch is checked out (block 3's Bash hook). In that worktree, run the test command on both interpreters, `python3 -m gates run_all --base <merge commit>^1` and `doctor`; expect PASS. Then `git worktree remove` it.
- [ ] **Step 4:** Create the tag locally, annotated, on the merge commit (`git tag -a v0.1.0 -m "strict-delivery 0.1.0" <merge commit>`; Q-B6plan-6 (a): no other tag). Do not push. Report the PR, the merge commit, the tag object and the exact push command to the session.
- [ ] **Step 5:** Only on the owner's word, quoted, run `git push origin v0.1.0` as its own command. Then run `git ls-remote --tags origin`, which must name the tag object.
- [ ] **Step 6:** As the first commit of this plan's cleanup branch (Q-Pplan-9 (a)), write:
  - the `MERGED` line with `final=yes`;
  - `Tag: <name> object=<sha> commit=<merge sha> pushed=<yes|no> words=<the owner's words verbatim>`, one line per tag, a prose line and not a `ledger/1` keyword.
  - The cleanup PR follows Q-Pplan-9 (a).

### Block 6 gaps and divergences

- Gap: spec §12's strict pre-commit cell reads "run_all + gate suite on every supported runtime". No task in the plan outline or in any detailed section seen so far runs a target project's gates on every supported runtime. Task 6R.1 tests `run_all`'s gate set per profile only. The program plan should name an owner for this cell.
- Overlap, deliberate: spec §14's "Every gate has a red case" sits under "Init end-to-end", which is block 4's. Task 6R.1 also gives every `run_all` gate a red case per profile, because §14 "Profiles" asks for exactly the profile's gates, which only red cases prove. Block 4's tests stay its own.

---

## Streams before the programs block

Owner decision 2026-10-31: two streams run beside stream A (block 1 in order, then block 2) before the programs tooling exists. The session controller coordinates them by hand. Design §1 states the aim these rules serve here: "Every file and every piece of work has exactly one owner within an effort." Design §6 states the core rule: "When stream A needs a change in a file stream B owns, A never edits it." Until `gate_streams` lands (programs block, P2), a person or agent enforces both, using the checks below. Nothing is left to memory.

- **Streams.**
  - **A**: blocks 1a-1d, block 2, then the programs block. A runs in the main checkout.
  - **B**: the prose of block 3 (section "Stream B" below). B starts once its section is approved.
  - **C**: init's stack command detection (block 4) and `gate_cites` (block 5) (section "Stream C" below). C starts after block 1a merges into `main`.
- **File ownership.** The three path lists are disjoint. A is the residual owner: every path a block-1 or block-2 task creates or modifies belongs to A, and so does every path the table does not list.

  | Stream | Owns (exact paths; a trailing `/` means every path under that directory) |
  |---|---|
  | B | `skills/strict-delivery/SKILL.md`; `skills/strict-delivery/prompts/controller.md`, `implementer.md`, `implementer_transcription.md`, `task_reviewer.md`, `final_reviewer.md`, `final_verifier.md`, `exception_reviewer.md`, `audit_reviewer.md`, `audit_verifier.md`, `investigator.md`, and, on A's request in programs Task P4.3, `program_controller.md` and `stream_controller.md` (owner Q-Pplan-6 (a)) (these files only, each directly in the prompts directory; the directory itself is not B's); `playbook/rules.md`, `playbook/roles.md`, `playbook/decisions.md`, `playbook/sessions.md`, `playbook/streams.md`, `playbook/review.md`; `tests/prose_check.py`, `tests/test_prompt_blocks.py`, `tests/test_playbook.py`, `tests/test_skill.py`; `.strict-delivery/state/plans/2026-10-31-strict-delivery-framework-b/` |
  | C | `gates/lib/detect.py`, `gates/lib/cites.py`, `gates/lib/slug_table.py`, `gates/lib/case_table.py`, `gates/gate_cites.py`; `tests/test_detect.py`, `tests/test_cites_lib.py`, `tests/test_gate_cites.py`; `.strict-delivery/state/plans/2026-10-31-strict-delivery-framework-c/` |
  | A | every path of the block-1 file lists (Tasks 1a.1-1d.2), every path block 2 and the programs block create, `.strict-delivery/state/plans/2026-10-31-strict-delivery-framework/`, and every path not listed for B or C |

  When a stream's last block merges into `main`, every path in its row passes to A, the residual owner (owner answer DS-3). Until then the row stands.

  Owner answer Q-Pplan-6 (a) (2026-11-02): stream B writes the `program_controller` and `stream_controller` prompt blocks and their `tests/prose_check.py` rows on A's request in programs Task P4.3; if B's last block has merged first, the paths are A's (DS-3) and A writes them.
- **Shared files.** Five files are touched by more than one stream's work, and A owns all five:
  - `gates/__main__.py` (`COMMANDS` and the `check` dispatcher);
  - `gates/producers.py`;
  - `tests/helpers.py`;
  - `.gitignore`;
  - `docs/strict-delivery/INDEX.md`. This file is generated and git-ignored (spec §5), so nobody edits it. `python3 -m gates index` writes it (Task 1c.3).

  Two more paths have owners outside the table. The plan file and both specs belong to the session controller and the owner; no stream edits them. Decision and finding records (`.strict-delivery/state/decisions/`, `.strict-delivery/state/findings/`) are global records, and only the session controller writes them. This mirrors design §12, under which the program controller "is the only writer of global records within the program". Before `findings new` exists (Task 1d.2), a finding is a ledger row in the stream that raised it.
- **Requests (by hand until `gate_streams`).** A non-owner never edits another stream's file, shared files included. It writes the need in its report under `## Requests` (file, what and why, the spec or plan section that requires it) and stops at a step boundary if it is blocked.
  - The session controller records the request. It appends the same line to the requester's ledger and to the owner stream's ledger: `Request: <id> from=<stream> to=<stream> files=<paths> need=<text> status=open`. The id comes from `ids.mint(cfg["ids"]["request"], ...)` (Task 1a.3) once block 1a has merged.
  - The owner stream implements the request in its next task, or in a task added for it, and the controller sets `status=done` with the commit sha.
  - If the owner stream disputes the request, the dispute becomes an owner question of class `request-dispute` (spec §7.1). The ruling is the decision the request line cites.
  - Known requests are C to A: register `cites` with the `check` dispatcher in `gates/__main__.py` (Task C2.2), and, only if block 2 has merged into `main` before block C2, add `cites` to `run_all`'s gate list (stream rules, "Cross-stream order"). Any change C needs in `tests/helpers.py` is also a request. C keeps extra fixture code in its own test modules instead.
- **Branches and worktrees.** Design §4.1 does not fit before the programs tooling. Its stream branch `<program>/<stream>/main` presumes `<program>/integration`, a program folder and a program controller, and none of these exists yet. Owner answer DS-1: the streams follow this plan's own rule instead, "each on its own branch".
  - Block branches are `block/sb1` and `block/sb2` (stream B) and `block/sc1` and `block/sc2` (stream C), beside A's `block/b1a` ... `block/b1d`. Each is created from the tip of `main` when its block starts.
  - Each worktree sits outside the main checkout: `../strict-delivery-worktrees/<stream>/<branch leaf>` (for example `../strict-delivery-worktrees/b/sb1`). Design §4.1 explains why a nested worktree is avoided: it "shows there as an untracked folder and leaves it unclean". A sibling directory needs no `.gitignore` edit, and `.gitignore` belongs to A.
  - A keeps the main checkout. A stream's agents never `cd` into another stream's worktree.
- **Briefs and reports.** Per-stream dispatch artifacts live in the main checkout under `.superpowers/sdd/2026-10-31-strict-delivery-framework-<stream>/` (git-ignored), and dispatches name them by absolute path. A worktree does not share the main checkout's ignored files.
- **Merging each block.** Each B and C block merges exactly as A's blocks do (Process for this plan, "Blocks"):
  1. a final review (top-tier reviewer role, as A);
  2. the top-tier final verifier;
  3. the block branch pushed, a pull request to `main`, and the owner's approval in chat naming the PR and its head sha;
  4. `gh pr merge <n> --merge --match-head-commit <sha>` (owner directive 2026-11-01, Q-15 (a)), read back from the host;
  5. the post-merge gate run on `main` updated from the remote;
  6. the merge ledgered (from programs Task P1.2 as the `MERGED` line) as the next branch's first commit, and the checkpoint.

  Approvals are given in chat and ledgered verbatim in that stream's ledger, with the PR number, head sha and merge commit read back from the host; they are not decision records (owner answer Q-15 (a), 2026-11-01).

  The session controller merges into `main` one block at a time. Before a stream's block merges, its branch is brought up to date with `main` (next item) and the full commit gate is re-run on that branch head.
- **Keeping up with `main`, and interface changes.** C consumes A's interfaces, listed under each C task's Consumes.
  - Those interfaces are frozen once merged (Task 1a.1: "Do not change this code in later tasks"). A change to one is a plan change: the owner rules on it, and the controller lists the affected C tasks.
  - When `main` gains a commit that touches a path C or B consumes, or before any block merge, the stream brings its open block branch up to date. Owner answer DS-2: it merges `main` into the block branch, run in the stream's worktree as its own command, with no owner grant. This mirrors the sync rule for main into an integration branch, spec §8.
  - A stream never rebases a block branch (DS-2): a rebase would orphan reviewed shas that review reports and `<sha>:<path>` evidence cite.
  - After the update the stream re-runs the full test command on both interpreters and every enabled gate. It then appends `UPDATE <block> from=main@<sha> head=<sha> tests=<passed>/<total> gates=<PASS|n/a>` to its ledger. A conflict, or a red result caused by A's change, stops the stream with status BLOCKED and a message to the controller. The stream never edits A's file to fix it.
- **Checkpoints per stream.** Design §12: "Each stream owns its own plan workspace".
  - Stream B checkpoints in `.strict-delivery/state/plans/2026-10-31-strict-delivery-framework-b/` and stream C in `.strict-delivery/state/plans/2026-10-31-strict-delivery-framework-c/`. Each holds that stream's `ledger.md` and `handoff.md`.
  - Both use the formats of "Process for this plan": the `CHECKPOINT` line, handoff front matter `schema: handoff/1` with the spec §9 fields, and the resume line. The `block` field is `sb1`, `sb2`, `sc1` or `sc2`, and the branch is the block branch.
  - The checkpoint commit is on the block branch, and that worktree is clean after it. Other worktrees may be dirty (spec §9: "other streams' worktrees may be dirty").
  - Continuation is as in "Process for this plan": one block per agent context, a fresh controller per block from the stream's handoff and ledger.
- **Commit gate, every stream.** The commit gate is the same as A's at the same time: the test command on both interpreters, plus every gate enabled on `main` at the branch's last update from `main`, with a clean tree. `run_all` replaces the list when block 2 lands. A gate C adds is enabled for every stream once it is merged into `main` and the stream has updated from `main`.
- **Cross-stream order.** Three pieces of work depend on another stream's files. Each is sequenced so that no stream edits a file it does not own and no gate runs against files that are not there yet:
  - **`cites` in `run_all`.** `run_all` and its gate list are A's (block 2). `cites` joins that list only when both block C2 has merged into `main` and block 2 (which brings `run_all`) has merged into `main`.
    - If C2 merges first, block 2's detailed section lists `cites` in `run_all` from the start: `gate_cites` is then on `main` and its paths are A's (DS-3).
    - If block 2 merges first, Task C2.2 Step 6 raises a request to A to add `cites` to `run_all`. Until A's commit is on `main`, every stream's commit gate runs `python3 -m gates check cites` beside `run_all`.
  - **`gate_dispatch` and the prompt files.** Block 2's `gate_dispatch` compares a dispatch's `## Strict block` with `skills/strict-delivery/prompts/<role>.md`, which are B1's files.
    - Its tests always build fixture prompt files in temp directories and never read B's paths.
    - The block-2 task that lands `gate_dispatch` starts only after block B1 has merged into `main` and A has updated from `main`, so the gate checks real prompt files from the commit it lands in (spec §16: "Each gate is enabled on this repository as soon as it lands").
    - If block 2 reaches that task first, A runs its other block-2 tasks first and ledgers the wait; if none is left, A stops with status BLOCKED until B1 merges.
  - **`FIXED_RULES` and `playbook/rules.md`.** `decisions.validate` refuses an `overrides` naming a fixed rule, from the constant `FIXED_RULES` in A's code (block 2, the `decision/2` task, owner answer F-2). `test_fixed_rules_match_decisions_constant` in `tests/test_playbook.py` keeps it equal to the `fixed: yes` rows of `playbook/rules.md` (Task B2.1). Whoever lands second writes that test:
    - If the `decision/2` task is on `main` before block B2 merges, stream B writes the test on `block/sb2`: in Task B2.1 when it is already there when B2.1 starts, else in a commit after B2's update from `main` and before B2's final review. If the `decision/2` task reaches `main` after B2's final review and before B2's merge, B2 updates from `main` again, adds the test, and its final review and verifier run again before the merge grant.
    - If B2 merges first, `tests/test_playbook.py` is A's (DS-3), and A's `decision/2` task adds the test.
- **Cross-stream checks the controller runs by hand before each block merge.** Each must print nothing:
  - Every changed path is owned by the merging stream: `git diff --name-only main...block/<branch>` filtered against the stream's row in the table above.
  - Nothing outside the stream's rows changed: `git diff --name-only main...block/sb<n> | grep -v -E '^(skills/strict-delivery/(SKILL\.md|prompts/(controller|implementer|implementer_transcription|task_reviewer|final_reviewer|final_verifier|exception_reviewer|audit_reviewer|audit_verifier|investigator|program_controller|stream_controller)\.md)|playbook/(rules|roles|decisions|sessions|streams|review)\.md|tests/(prose_check|test_prompt_blocks|test_playbook|test_skill)\.py|\.strict-delivery/state/plans/2026-10-31-strict-delivery-framework-b/.*)$'`. Stream C uses the same check with its own rows.

---

## Stream B: plugin prose (branches `block/sb1`, then `block/sb2`)

Stream B writes the prose of spec §17 block 3: the role prompt blocks, the base playbook and the skill. It writes no gate code. Its tests are standard-library text checks over its own files, except two drift tests that each import one constant of A's code: `test_owner_only_matches_config_defaults` (Task B2.3, `gates.lib.config.DEFAULTS`) and, when the stream rules' "Cross-stream order" gives it to B, `test_fixed_rules_match_decisions_constant` (Task B2.1, `gates.lib.decisions.FIXED_RULES`). B depends on no other interface of A. Global Constraints, the Process for this plan, and the stream rules above all apply.

**Sources.** Spec §3 (layout and precedence), §7 (decisions), §8 (base playbook), §10 (roles and dispatch grammar), §12 (profiles), §13 and §13a, and design §4-§6 and §10-§12. The template for shape is the user-level `strict-delivery` skill and its eight prompt files (one-line intro, labelled paragraphs). B generalises them; it never copies them. B's files are public, and Task B1.1's forbidden-string check enforces the exclusions of spec §2 by test.

**Consumed later by:**
- `gate_dispatch` (block 2, stream A). Spec §10: "`## Strict block` (the role's prompt block, byte for byte)". It reads `skills/strict-delivery/prompts/<role>.md` and its first-line and heading rules (Task B1.1 Produces). It lands only after block B1 merges (stream rules, "Cross-stream order").
- Programs block P4 (Task P4.3). Owner answer Q-Pplan-6 (a): A requests the two prompt files and their `LABELS` rows from B, which writes them in its own style and format test; once B's last block (B2) has merged, the paths are A's (DS-3) and P4 writes them itself.
- Block 3 code (later, run as a program):
  - `.claude-plugin/plugin.json` packages `skills/` and `playbook/`.
  - The SessionStart hook prints "the instruction to invoke the strict-delivery skill" (skill `name` from Task B2.3) and lists active overrides (spec §4: "active rule overrides") from answered `rule-override` decisions. It refuses nothing. An override of a `fixed: yes` rule is refused when it is written, by `decisions.validate` (block 2, stream A) against `FIXED_RULES`, which a test keeps equal to `playbook/rules.md`'s `fixed` column (Task B2.1).
- Block 4 code (later):
  - The CLAUDE.md managed block points at `playbook/` (spec §8: "The CLAUDE.md managed block points at it").
  - Framework roles' prompt files and minimum tiers are fixed in the framework (`dispatch.ROLES`/`MIN_TIERS`), the same in every profile; config `roles` adds only project roles (spec §10 as edited by SE-B4-3; owner answer Q-B4plan-6 (a)). Task B2.2 `playbook/roles.md` is the prose source.

### Block B1: prompt blocks (branch `block/sb1`)

#### Task B1.1: prompt-block format, forbidden strings, worker blocks

**Files:**
- Create: `tests/prose_check.py` (helpers; not a test module), `skills/strict-delivery/prompts/implementer.md`, `skills/strict-delivery/prompts/implementer_transcription.md`, `skills/strict-delivery/prompts/investigator.md`
- Test: `tests/test_prompt_blocks.py`

**Owner answers applied:** PC1, PC3 (Process for this plan); DB-1 (one file per role, stem = role id), DB-3 (the forbidden list below, model names and the superpowers default save path included), DB-4 (template intro sentence and label style, generalised).

**Interfaces:**
- Consumes: none (standard library only).
- Produces:
  - `tests/prose_check.py`:
    - `SPEC_ROLES: tuple` = `("program_controller", "stream_controller", "controller", "implementer", "implementer_transcription", "task_reviewer", "final_reviewer", "final_verifier", "exception_reviewer", "audit_reviewer", "audit_verifier", "investigator")`. These are the spec §10 roles, in order.
    - `B_ROLES` = `SPEC_ROLES[2:]`; `PROGRAM_ROLES` = `SPEC_ROLES[:2]` (programs block P4, stream A).
    - `PROMPTS_DIR = "skills/strict-delivery/prompts"`.
    - `DISPATCH_HEADINGS: tuple` = `("## Role", "## Brief", "## Findings", "## Claims", "## Budget: tokens=<n> minutes=<n>", "## Model", "## Report", "## Strict block", "## Task")` (spec §10, in order).
    - `STATUS_LINE = "status: DONE|DONE_WITH_FINDINGS|NEEDS_DECISION|BLOCKED|DENIED"` (spec §10).
    - `FORBIDDEN: tuple` of `(name, compiled regex)` pairs (case-insensitive unless stated). The patterns are:
      - `lap-timer` (`lap[-_ ]?timer`; owner Q-B11-1);
      - `old-decision-number` (`\bDEC-\d{1,4}\b`, which does not match the id form `DEC-20261031-k3f9`);
      - `spec-clause` (`\bD\d{1,3}\b`, case-sensitive);
      - `row-id` (`\b[A-Z]\d+-[A-Z]+-\d+\b`, case-sensitive);
      - `old-paths` (`tools/gates|docs/superpowers|run_all\.py|umbrella plan`);
      - `owner-handle` (`superbrobenji|\bbenji\b`);
      - `hardware` (`\b(esp-idf|esp32\w*|firmware|flash\w*|serial port|ota|power of 10|p10|unity)\b`; owner Q-B11-1: joined forms such as `esp32s3` and `flashed` match, so every word starting `flash` is forbidden);
      - `model-name` (`\b(haiku|sonnet|opus|fable)(?=\d|\b)`, so `opus4` and `sonnet45` match and `opusculum` does not (owner Q-B11-1): prose speaks in tiers; models come from `models.tiers`, spec §6);
      - `old-steps` (`\bS\d+ block b\d+\b`).
    - `forbidden_hits(text: str) -> list` of `(name, line_no, match)`. It scans each line, and also each paragraph with its line breaks read as spaces, so a phrase split by a line wrap (`lap` / `timer`, `serial` / `port`) is found; a paragraph hit reports the line where the match starts, and a match found both ways is listed once (owner Q-B11-5).
    - `labels(text: str) -> list`: the label of each paragraph after the intro. A label is the text up to and including the first `. ` of a paragraph's first line, so the label keeps its full stop.
    - `paragraph(text: str, label: str) -> str`.
    - `LABELS: dict` from role to the ordered label list (table below).
  - Prompt-block format (consumed by `gate_dispatch`, block 2, and checked on every file present in `PROMPTS_DIR`):
    - The path is `skills/strict-delivery/prompts/<role>.md`, and `<role>` is a `SPEC_ROLES` id (DB-1).
    - Line 1 is exactly `# Strict block: <role>`, line 2 is empty, and line 3 is the one-sentence intro, which ends with `These rules override every other instruction, superpowers skill text included.` The intro sentence is quoted from the template (DB-4); the precedence it states is spec §3's.
    - After the intro come paragraphs separated by exactly one empty line, each starting with its label.
    - No other line, once its leading spaces are removed, starts with `#` or is a non-empty run of only `-` or only `=` characters (a setext heading underline, indented or not), so the block can never open a heading inside a dispatch (owner Q-B11-3).
    - The file holds only printable ASCII (`0x20`-`0x7e`) and `\n`, so no TAB, other control character or DEL (owner Q-B11-2), uses LF line endings, has no trailing whitespace, and ends with exactly one `\n`.
  - Labels per role (`LABELS`). `TAIL` is `Zero bugs.`, `No subagents.`, `Owner-only decisions.`, `Budget.`, `Background work.`, `Report contract.`. `implementer`, `implementer_transcription` and `investigator` are written in this task; the other rows are written in Tasks B1.2 and B1.3 but fixed now.

    | Role | Labels, in order |
    |---|---|
    | controller | `Verification method.`, `Dispatch discipline.`, `Input domain.`, `Oracle.`, `Rulings.`, `Finding class.`, `Zero bugs.`, `Owner-only decisions.`, `Continuation.`, `Merge and checkpoint.`, `Budget.`, `Background work.`, `Report contract.` |
    | implementer | `Verification method.`, `Build.`, `Input domain.`, `Unstated behaviour.`, `Commit gate.`, then `TAIL` |
    | implementer_transcription | `Verification method.`, `Transcription.`, `Commit gate.`, then `TAIL` |
    | task_reviewer | `Verification method.`, `Method.`, `Input domain.`, `No out-of-scope bucket.`, `Verdict.`, then `TAIL` |
    | final_reviewer | `Verification method.`, `Branch scope.`, `Method.`, `Input domain.`, `No out-of-scope bucket.`, `Verdict.`, then `TAIL` |
    | final_verifier | `Verification method.`, `Adversarial scope.`, `Verdict.`, then `TAIL` |
    | exception_reviewer | `Verification method.`, `Exception scope.`, `Verdict.`, then `TAIL` |
    | audit_reviewer | `Verification method.`, `Coverage first.`, `Method.`, then `TAIL` |
    | audit_verifier | `Verification method.`, `Method.`, `Verdict.`, then `TAIL` |
    | investigator | `Verification method.`, `Read-only.`, then `TAIL` |

  - Required content (`REQUIRED: dict` from label to strings that paragraph must contain, in any block that carries the label). Each string matches as a whole token (the Global Constraints whole-token rule, applied by `whole_token(s: str, text: str) -> bool` in `tests/prose_check.py`): `indirect` does not satisfy `directly`, `unkilled` does not satisfy `killed` (owner Q-B11-4):

    | Label | Must contain |
    |---|---|
    | `Verification method.` | `directly`, `by contradiction`, `Record both commands` (spec §8: "verify directly and by contradiction, record both commands") |
    | `Owner-only decisions.` | `decision_classes.owner_only`, `NEEDS_DECISION`, `at least two options` |
    | `Report contract.` | `STATUS_LINE` |
    | `Budget.` | `80 %` |
    | `Background work.` | `reaps` or `killed` |
    | `Commit gate.` | `python3 -m gates run_all` |
    | `Input domain.` | `input-domain table` (PC1) |
    | `Unstated behaviour.` | `NEEDS_DECISION`, `mutant` (PC3) |
    | `No out-of-scope bucket.` | `class-narrowing question for the owner`, `missing input-domain table is a finding` (PC4) |
    | `Oracle.` | `production path`, `independent expected value` (PC2) |
    | `Finding class.` | `class: <dimension>: <members>` (PC5) |
    | `Continuation.` | `handoff`, `BLOCKED: budget`, `Nothing continues from inherited memory` |
    | `Dispatch discipline.` | each `DISPATCH_HEADINGS` entry in backticks, in order, and `fork` |
    | `Read-only.` | `no tracked file` |

**Input-domain dimensions:**
- File set: an extra file in `PROMPTS_DIR` whose stem is not a role; a role file missing; a directory named `<role>.md`; a symlink.
- First line: wrong role, extra space, `##`, BOM.
- Line endings: CRLF, CR.
- Final newline: none, two.
- Trailing whitespace; a non-ASCII character such as an en dash or a curly quote; TAB, NUL, ESC, DEL (owner Q-B11-2).
- A line starting with `#` after line 1, inside a paragraph or alone; `   # x` (indented); `---`, `===` and `  ---` under a line (owner Q-B11-3); an empty line is not an underline.
- Labels: missing, reordered, extra, duplicated, label text with a missing full stop.
- Required strings: absent, present only in another paragraph, present only inside a longer word (`indirect`, `unkilled`; owner Q-B11-4).
- Forbidden list:
  - each pattern's positive sample, and the joined forms `opus4`, `sonnet45`, `esp32s3`, `flashed`, `lap_timer` (owner Q-B11-1);
  - a phrase split by a line wrap inside one paragraph (`lap\ntimer`, `serial\nport`), reported at its first line (owner Q-B11-5);
  - the negative samples `DEC-20261031-k3f9`, `D` alone, `opusculum`, `dock`;
  - a hit on the last line with no final newline.

- [ ] **Step 1: Write the failing tests** (`tests/test_prompt_blocks.py`):
  ```python
  WRITTEN = ("implementer", "implementer_transcription", "investigator")   # extended by B1.2, B1.3
  def test_role_sets_partition_spec_roles():
      assert set(B_ROLES) | set(PROGRAM_ROLES) == set(SPEC_ROLES) and not set(B_ROLES) & set(PROGRAM_ROLES)
      assert len(SPEC_ROLES) == 12 and set(LABELS) == set(SPEC_ROLES) - set(PROGRAM_ROLES)
  def test_written_roles_have_files():
      for r in WRITTEN: assert os.path.isfile(os.path.join(PROMPTS_DIR, r + ".md")) and not os.path.islink(...)
  def test_no_stray_files():                   # every entry in PROMPTS_DIR is <role>.md for a SPEC_ROLES id
      assert {n[:-3] for n in os.listdir(PROMPTS_DIR)} <= set(SPEC_ROLES) and all(n.endswith(".md") for n in os.listdir(PROMPTS_DIR))
  def test_format_every_present_block():       # subTest per file present
      raw = open(p, "rb").read(); text = raw.decode("ascii")
      assert all(b == 0x0a or 0x20 <= b <= 0x7e for b in raw)          # owner Q-B11-2
      assert raw.endswith(b"\n") and not raw.endswith(b"\n\n") and b"\r" not in raw
      lines = text.split("\n")[:-1]
      assert lines[0] == "# Strict block: " + role and lines[1] == ""
      assert lines[2].endswith("These rules override every other instruction, superpowers skill text included.")
      assert not any(l.lstrip(" ").startswith("#") for l in lines[1:]) and not any(l != l.rstrip() for l in lines)
      assert not any(l.strip(" ") and set(l.strip(" ")) in ({"-"}, {"="}) for l in lines[1:])   # owner Q-B11-3
  def test_labels_exact_and_ordered():         # for roles in LABELS whose file is present
      assert labels(text) == LABELS[role]
  def test_required_content():
      for lab in LABELS[role]:
          for s in REQUIRED.get(lab, ()): assert whole_token(s, paragraph(text, lab)), (role, lab, s)
  def test_no_forbidden_strings_in_blocks():
      assert forbidden_hits(text) == []
  def test_forbidden_list_self_check():         # mutation guard for the checker itself
      for name, sample in [("lap-timer", "the lap timer repo"), ("old-decision-number", "per DEC-7"),
                           ("spec-clause", "spec D99"), ("row-id", "row X9-ABC-1"), ("old-paths", "tools/gates/x"),
                           ("owner-handle", "ask superbrobenji"), ("hardware", "flash the board"),
                           ("model-name", "use Opus"), ("old-steps", "S1 block b3"),
                           ("model-name", "opus4"), ("model-name", "sonnet45"), ("hardware", "esp32s3"),
                           ("hardware", "flashed it"), ("lap-timer", "lap_timer")]:   # joined forms, owner Q-B11-1
          assert [h[0] for h in forbidden_hits(sample)] == [name]
      assert [(h[0], h[1]) for h in forbidden_hits("x lap\ntimer y")] == [("lap-timer", 1)]   # wrap, owner Q-B11-5
      assert [h[0] for h in forbidden_hits("a serial\nport")] == ["hardware"]
      for clean in ["DEC-20261031-k3f9", "a D alone", "opusculum", "dock the window", "tier3"]:
          assert forbidden_hits(clean) == []
  def test_format_checker_rejects_bad_samples():  # each bad variant written to a temp dir and run through the same checker function
      for bad in [b"# Strict block: implementer\r\n", b"## Strict block: implementer\n", no_final_newline, crlf, en_dash, inner_heading, swapped_labels,
                tab_line, nul_byte, indented_heading, setext_dashes, indented_setext, required_inside_word]:
          assert block_problems(bad, "implementer") != []
  ```
  (`block_problems(raw: bytes, role: str) -> list` sits in `tests/prose_check.py` and returns a list of problem strings. `test_format_every_present_block` and `test_labels_exact_and_ordered` assert `block_problems(raw, role) == []`, so the self-check and the real check run the same code.)
- [ ] **Step 2: Run the test command; expect FAIL** (`ModuleNotFoundError: tests.prose_check`, then missing files).
- [ ] **Step 3: Write `tests/prose_check.py` and the three blocks.** Each block is generic and names no project, model or person:
  - `implementer`: test first through the production path, the PC1 table rows, PC3, one mutant per changed production condition, and the commit gate `python3 -m gates run_all` plus `commands.test`.
  - `implementer_transcription`: the brief carries complete code; transcribe it, run the gates, and stop NEEDS_DECISION on any gap.
  - `investigator`: read-only, answers one question with file:line evidence.
- [ ] **Step 4: Run the test command on both interpreters and every enabled gate; expect PASS.**
- [ ] **Step 5: Commit** `docs(prompts): prompt-block format check and worker blocks`, then checkpoint in the stream-B ledger.

#### Task B1.2: review and verification blocks

**Files:**
- Create: `skills/strict-delivery/prompts/task_reviewer.md`, `final_reviewer.md`, `final_verifier.md`, `exception_reviewer.md`
- Modify: `tests/test_prompt_blocks.py` (extend `WRITTEN`)

**Owner answers applied:** PC4; DB-5 (`exception_reviewer` argues against one proposed exception); DB-2 (the top tier, `tier4`, is `final_verifier` and `exception_reviewer`).

**Interfaces:**
- Consumes: Task B1.1 `prose_check`.
- Produces: the four blocks, each passing `block_problems`, with these contents:
  - `task_reviewer` and `final_reviewer` re-run every claim and gate themselves (spec §8: "Reviewers execute every claim and re-run every gate themselves"). Their `No out-of-scope bucket.` paragraph carries PC4.
  - The `final_verifier` block states the top tier ("the top tier stays only for final verifier and exception reviewer", design §4) by tier name, never by model.
  - `exception_reviewer` (DB-5): its `Exception scope.` paragraph says it argues against one proposed exception to a rule, before the owner rules. The exception is a draft decision of class `rule-override`, or a deviation a project playbook allows. It reads only the proposal and its evidence.
  - The `final_verifier` and `exception_reviewer` blocks name their tier as `tier4` (DB-2), never a model.

**Input-domain dimensions:** as Task B1.1, for the four new files; the `Exception scope.` paragraph with each of its three phrases missing. A test also asserts that the `final_reviewer` and `task_reviewer` `Verdict.` paragraphs differ, so the files are not copies of each other.

- [ ] **Step 1: Extend the tests:**
  ```python
  WRITTEN = (..., "task_reviewer", "final_reviewer", "final_verifier", "exception_reviewer")
  def test_reviewer_blocks_differ_in_scope():
      assert paragraph(read("task_reviewer"), "Verdict.") != paragraph(read("final_reviewer"), "Verdict.")
      assert "whole branch" in paragraph(read("final_reviewer"), "Branch scope.")
  def test_reviewers_rerun_gates():
      for r in ("task_reviewer", "final_reviewer", "final_verifier"): assert "python3 -m gates run_all" in read(r)
  def test_exception_reviewer_scope():          # DB-5
      p = paragraph(read("exception_reviewer"), "Exception scope.")
      for s in ("one proposed exception", "`rule-override`", "only the proposal and its evidence"): assert s in p
  def test_top_tier_blocks_name_tier4():        # DB-2
      for r in ("final_verifier", "exception_reviewer"): assert "tier4" in read(r)
  ```
- [ ] **Step 2: Run; expect FAIL** (files missing).
- [ ] **Step 3: Write the four blocks.**
- [ ] **Step 4: Run on both interpreters and every enabled gate; expect PASS.**
- [ ] **Step 5: Commit** `docs(prompts): review, verifier and exception blocks`, then checkpoint.

#### Task B1.3: controller and audit blocks

**Files:**
- Create: `skills/strict-delivery/prompts/controller.md`, `audit_reviewer.md`, `audit_verifier.md`
- Modify: `tests/test_prompt_blocks.py`

**Owner answers applied:** PC1, PC2, PC5. Continuation (Process for this plan; design §4.4).

**Interfaces:**
- Consumes: Task B1.1.
- Produces:
  - The controller block. Its `Dispatch discipline.` paragraph names the dispatch grammar exactly (spec §10, `DISPATCH_HEADINGS` in order), refuses a fork dispatch, and keeps model choice inside `models.tiers` and `top_tier_roles` (spec §8: "Dispatch only inside the role/model map; the top tier only for `top_tier_roles`"). Its `Rulings.` paragraph bounds rulings by `rulings.max_per_block` and ledgers each as `Ruling: what -- why -- cost if wrong -- spec cite` (spec §7.1). Continuation and the fix-loop tiers follow spec §10: "Fix loop rounds 1-3 resume the implementer, rounds 4-5 a fresh agent one tier up, then an owner question".
  - The audit blocks. Both state spec §8's "the owner rules on triage before any plan" and name the owner-only slug `triage`. The `audit_reviewer` `Coverage first.` paragraph has the reviewer write its coverage list to its progress file before reviewing (the template's paragraph, generalised; DB-4). The `audit_verifier` `Method.` paragraph re-runs every reproducer and extends the reviewer's coverage list.
  - `test_all_b_roles_written`: `WRITTEN`, listed role by role, equals `B_ROLES`.

**Input-domain dimensions:**
- As Task B1.1.
- `Dispatch discipline.`: one heading missing, two swapped, `## Budget` without its `tokens=<n> minutes=<n>` form.
- The fix-loop sentence: rounds stated other than 1-3 and 4-5.
- Each key phrase of the controller and audit tests below: absent, or present only in another paragraph.

- [ ] **Step 1: Extend the tests:**
  ```python
  WRITTEN = ("implementer", "implementer_transcription", "investigator", "task_reviewer", "final_reviewer",
             "final_verifier", "exception_reviewer", "controller", "audit_reviewer", "audit_verifier")
  def test_all_b_roles_written():
      assert sorted(WRITTEN) == sorted(B_ROLES)
  def test_controller_dispatch_grammar_in_order():
      p = paragraph(read("controller"), "Dispatch discipline.")
      pos = [p.index("`" + h + "`") for h in DISPATCH_HEADINGS]
      assert pos == sorted(pos) and "fork" in p
  def test_controller_fix_loop():
      assert "rounds 1-3" in read("controller") and "rounds 4-5" in read("controller")
  def test_controller_ruling_format():
      p = paragraph(read("controller"), "Rulings.")
      assert "Ruling: what -- why -- cost if wrong -- spec cite" in p and "`rulings.max_per_block`" in p   # spec §7.1
  def test_controller_model_choice():           # spec §8 "the top tier only for `top_tier_roles`"; spec §6 `models.tiers`
      p = paragraph(read("controller"), "Dispatch discipline.")
      assert "`models.tiers`" in p and "`top_tier_roles`" in p
  def test_audit_blocks_triage_before_plan():   # spec §8 "the owner rules on triage before any plan"
      for r in ("audit_reviewer", "audit_verifier"):
          assert "before any plan" in read(r) and "`triage`" in read(r), r
  def test_audit_coverage_and_reproducers():
      assert "coverage list" in paragraph(read("audit_reviewer"), "Coverage first.")
      m = paragraph(read("audit_verifier"), "Method.")
      assert "reproducer" in m and "coverage list" in m
  ```
- [ ] **Step 2: Run; expect FAIL.**
- [ ] **Step 3: Write the three blocks.**
- [ ] **Step 4: Run on both interpreters and every enabled gate; expect PASS.**
- [ ] **Step 5: Commit** `docs(prompts): controller and audit blocks`, then checkpoint. **Block B1 end:** final review, verifier, then the pull-request flow (stream rules, "Merging each block"), checkpoint, continuation (stream rules above).

### Block B2: base playbook and skill (branch `block/sb2`)

#### Task B2.1: `playbook/rules.md`, the `SD-R<n>` rules

**Files:**
- Create: `playbook/rules.md`
- Test: `tests/test_playbook.py`

**Owner answers applied:** DB-6 (`SD-R1`-`SD-R17` in spec §8 order, `SD-R18` bypass block fixed, `SD-R19` stack-neutral production path), DB-7 (profiles and `enforced by` derived from spec §12), DB-8 (plain-text `source`), DB-9 (overrides by the optional decision field `overrides`, `decision/2`); F-2 (the refusal of a fixed-rule override is `decisions.validate`'s, against `FIXED_RULES`; a test here keeps that constant equal to the `fixed` column).

**Interfaces:**
- Consumes: Task B1.1 `prose_check` (`forbidden_hits`); `gates.lib.decisions.FIXED_RULES` (stream A, block 2) for one test, when the stream rules' "Cross-stream order" gives that test to B.
- Produces: `playbook/rules.md`. Line 1 is `# Base playbook: rules`. One paragraph follows: the fixed and override rule of spec §8. Per DB-9 it names the override form: a decision of class `rule-override` carrying the optional field `overrides: SD-R<n>` (decision schema `decision/2`, stream A, block 2; spec edits E1-E3), and a `fixed: yes` rule is never overridden. Then comes one markdown table with the header row exactly `| id | rule | why | enforced by | profiles | fixed | source |`, one row per rule:
  - `id` is `SD-R1` ... `SD-R<n>`, consecutive, with no gaps.
  - `enforced by` is one gate name from spec §3's list, or `hook`, or `judgment`.
  - `profiles` is a comma-separated, non-empty subset of `light, standard, strict`, in that order.
  - `fixed` is `yes` or `no`.
  - `source` is plain text `spec §<n>` (DB-8), never a path cite.

  The block-3 SessionStart hook lists active overrides (spec §4) and refuses nothing. An override of a `fixed: yes` rule is refused when it is written: `decisions.validate` (stream A, block 2, with `decision/2`) refuses an `overrides` in its constant `FIXED_RULES`, and `test_fixed_rules_match_decisions_constant` keeps that constant equal to this table's `fixed: yes` rows.
  - Rows (DB-6): `SD-R1`-`SD-R17` are spec §8's seventeen bullets in order. `SD-R18` is the bypass block (spec §4 PreToolUse Bash; spec §8 names it as fixed), enforced by `hook`, all profiles. `SD-R19` is the production-path rule: whether a test drives the real code path stays reviewer judgment, worded stack-neutral (spec §13a). It is enforced by `judgment`.
  - `fixed: yes` exactly for owner-only classes (`SD-R3`), merge grants (`SD-R12`) and the bypass block (`SD-R18`). Spec §8: "Rules marked `fixed` (owner-only classes, merge grants, the bypass block) cannot be overridden."
  - `profiles` and `enforced by` (DB-7). A rule takes the profiles whose spec §12 column says yes (or a cap or `per finding`) on the row that applies to it; a rule no §12 row applies to takes all three. `enforced by` is the gate spec §9, §10 or §13a names for it, the hook for the bypass block, else `judgment`. The drafter's derivation, which the owner checks as one table at B2.1's review:

    | id | spec key | §12 row | profiles | enforced by |
    |---|---|---|---|---|
    | SD-R1 | register row | register row per change | light, standard, strict | gate_register |
    | SD-R2 | by contradiction | claims register | standard, strict | gate_claims |
    | SD-R3 | Owner-only | decision log + owner-only gate | light, standard, strict | gate_decisions |
    | SD-R4 | Report before plan | none | light, standard, strict | judgment |

    `SD-R4` also carries spec §8's plan-in-full rule and the stream breakdown (owner answer Q-PL-1 (a)): its rule text states both, and its `enforced by` reads `program create (programs); judgment` (cross-block request from A, Programs block cross-block notes "Stream B (Q-PL-1 (a))"; review F-QPL-5). The row above is the pre-request text; B updates it when the request arrives.
    | SD-R5 | Zero bugs | none | light, standard, strict | judgment |
    | SD-R6 | deleted test | none | light, standard, strict | judgment |
    | SD-R7 | epic | none | light, standard, strict | judgment |
    | SD-R8 | process defect | none | light, standard, strict | judgment |
    | SD-R9 | re-run every gate | none | light, standard, strict | judgment |
    | SD-R10 | mutation transcript | review package + mutation transcript | standard, strict | gate_evidence |
    | SD-R11 | One block per agent context | block size cap | standard, strict | gate_checkpoint |
    | SD-R12 | owner grant | none | light, standard, strict | judgment |
    | SD-R13 | cleanup | none | light, standard, strict | gate_cleanup |
    | SD-R14 | background jobs | none | light, standard, strict | judgment |
    | SD-R15 | set -eu | none | light, standard, strict | judgment |
    | SD-R16 | decisions | decision log + owner-only gate | light, standard, strict | judgment |
    | SD-R17 | role/model map | dispatch grammar + model tiers | standard, strict | gate_dispatch |
    | SD-R18 | bypass | bypass block | light, standard, strict | hook |
    | SD-R19 | production-path | none | light, standard, strict | judgment |

    Spec §12's "top-tier final verifier" row (strict only) maps to no spec §8 bullet; it is config (`top_tier_roles`), not a rule row.

**Input-domain dimensions:**
- Header: a cell renamed, reordered, extra or missing.
- Ids: a gap, a duplicate, `SD-R0`, `SD-R01`, lowercase.
- `enforced by`: a gate name not in spec §3, empty.
- `profiles`: empty, unknown name, wrong order, duplicate.
- `fixed`: other than `yes` or `no`; the fixed set larger or smaller than the three; `FIXED_RULES` larger or smaller than the table's fixed set.
- `profiles` of `SD-R1`, `SD-R2`, `SD-R3`, `SD-R11`, `SD-R17`, `SD-R18` other than the table above.
- The intro paragraph without `overrides: SD-R<n>`, `rule-override` or `decision/2`.
- A row whose spec key phrase is missing.
- `source`: a path or anchor, empty.
- A second table; pipes inside a cell.
- Forbidden strings.

- [ ] **Step 1: Write the failing tests** (`tests/test_playbook.py`):
  ```python
  HEADER = "| id | rule | why | enforced by | profiles | fixed | source |"
  GATES = {"gate_schema", "gate_register", "gate_claims", "gate_decisions", "gate_dispatch", "gate_streams", "gate_context",
           "gate_cites", "gate_drift", "gate_index", "gate_checkpoint", "gate_cleanup", "gate_evidence", "run_all", "hook", "judgment"}
  SPEC8_KEYS = {1: "register row", 2: "by contradiction", 3: "Owner-only", 4: "Report before plan", 5: "Zero bugs",
                6: "deleted test", 7: "epic", 8: "process defect", 9: "re-run every gate", 10: "mutation transcript",
                11: "One block per agent context", 12: "owner grant", 13: "cleanup", 14: "background jobs",
                15: "set -eu", 16: "decisions", 17: "role/model map", 18: "bypass", 19: "production-path"}
  def test_header_and_ids():
      rows = table_rows(read("playbook/rules.md"))          # helper in prose_check: rows of the one table
      assert first_table_header(text) == HEADER and [r["id"] for r in rows] == ["SD-R%d" % i for i in range(1, len(rows) + 1)]
  def test_every_spec8_rule_present():
      for i, key in SPEC8_KEYS.items(): assert key.lower() in rows[i - 1]["rule"].lower(), i
  def test_profiles_from_spec12():               # DB-7: the rows whose spec §12 row is named in the owner answer
      p = {r["id"]: r["profiles"] for r in rows}
      for i in ("SD-R1", "SD-R3", "SD-R18"): assert p[i] == "light, standard, strict"
      for i in ("SD-R2", "SD-R11", "SD-R17"): assert p[i] == "standard, strict"
  def test_override_form_named():                 # DB-9
      intro = text.split(HEADER)[0]
      assert "`overrides: SD-R<n>`" in intro and "`rule-override`" in intro and "decision/2" in intro
  def test_fixed_set_exact():
      assert {r["id"] for r in rows if r["fixed"] == "yes"} == {"SD-R3", "SD-R12", "SD-R18"}
      assert all(r["fixed"] in ("yes", "no") for r in rows)
  def test_fixed_rules_match_decisions_constant():   # F-2; who writes it: stream rules, "Cross-stream order"
      from gates.lib.decisions import FIXED_RULES
      assert sorted(FIXED_RULES) == sorted(r["id"] for r in rows if r["fixed"] == "yes")
  def test_columns_valid():
      for r in rows:
          assert r["enforced by"] in GATES
          ps = r["profiles"].split(", "); assert ps and ps == [p for p in ("light", "standard", "strict") if p in ps]
          assert re.fullmatch(r"spec §\d+[a-z]?", r["source"])
  def test_table_parser_rejects_bad_samples():   # header reordered, SD-R gap, SD-R01, two tables
      for bad in BAD_SAMPLES: assert rules_problems(bad) != []
  def test_no_forbidden_strings_in_playbook():
      assert forbidden_hits(read("playbook/rules.md")) == []
  ```
- [ ] **Step 2: Run; expect FAIL.**
- [ ] **Step 3: Write `playbook/rules.md`** (and `table_rows`, `first_table_header`, `rules_problems` in `tests/prose_check.py`).
- [ ] **Step 4: Run on both interpreters and every enabled gate; expect PASS.**
- [ ] **Step 5: Commit** `docs(playbook): base rules SD-R1..SD-R<n>`, then checkpoint.

#### Task B2.2: the other playbook files

**Files:**
- Create: `playbook/roles.md`, `playbook/decisions.md`, `playbook/sessions.md`, `playbook/streams.md`, `playbook/review.md`
- Modify: `tests/test_playbook.py`, `tests/prose_check.py` (adds `section`)

**Owner answers applied:** DB-2 (minimum tier per role, the table below).

**Interfaces:**
- Consumes: Tasks B1.1-B1.3 (prompt files), B2.1.
- Produces (spec §8's list; each file's line 1 is `# Base playbook: <stem>`):
  - `tests/prose_check.py` gains `section(text: str, heading: str) -> str`: the lines after the one line equal to `## <heading>`, up to the next line starting with `## ` or the end. It raises `AssertionError` naming the heading when that line is absent or occurs more than once. Task B2.3 uses it too.
  - `decisions.md`, `sessions.md`, `streams.md` and `review.md` carry exactly the `## ` headings of `PLAYBOOK_SECTIONS` below, in order, and each section contains its key phrases (the test code is the table).
  - `roles.md`: one table with header `| role | prompt block | minimum tier | needs brief | finding states |`, one row per `SPEC_ROLES` id. `prompt block` is `skills/strict-delivery/prompts/<role>.md`, and `minimum tier` follows DB-2:

    | Tier | Roles |
    |---|---|
    | tier1 | `implementer_transcription` |
    | tier2 | `implementer` |
    | tier3 | `controller`, `program_controller`, `stream_controller`, `task_reviewer`, `final_reviewer`, `audit_reviewer`, `audit_verifier`, `investigator` |
    | tier4 | `final_verifier`, `exception_reviewer` |

    The table covers spec §10: "Each role names its prompt block, minimum tier, budget cap, whether it needs a brief, and which finding states it may take". The budget cap is config `budgets` (no default in the spec), so the table names the key, not a number.
  - `decisions.md`: spec §7 in operating terms, covering `ask` / `decide` / `find` / `withdraw`, the human-only answer rule, search before asking, and `landed_in` (spec §7.2: "a decision's `landed_in` is never a spec").
  - `sessions.md`: session kinds, start order, blocks, checkpoints, handoffs and continuation (spec §9, design §4.4, §10), and the planning steps for agents: plan in full before code, the stream breakdown plan (`breakdown/1`) as the last planning step, streams run as they unblock (spec §8 as edited for owner answer Q-PL-1 (a); cross-block request from A, Programs block cross-block notes "Stream B (Q-PL-1 (a))"; if this task is already done when the request arrives, B adds the section in a follow-up commit).
  - `streams.md`: design §4-§6 and §10-§12 in operating terms.
  - `review.md`: task and final review, the verifier, the fix loop and the process-defect stop (spec §8, §10).

**Input-domain dimensions:**
- `roles.md`: a role missing, a role extra, a prompt path to a file that does not exist (B roles only; `PROGRAM_ROLES` paths may be absent until P4), a tier outside `tier1`-`tier4`, any role at a tier other than DB-2's.
- `top_tier_roles` agreement: the rows at `tier4` are exactly `final_verifier` and `exception_reviewer` (design §4).
- Each file: line 1, forbidden strings.
- `PLAYBOOK_SECTIONS`: a heading missing, reordered, duplicated or extra; each key phrase absent, or present only in another section.
- `section`: the heading absent, the heading twice, the last section (no following `## `).

- [ ] **Step 1: Extend the tests:**
  ```python
  def test_roles_table_covers_spec_roles():
      rows = table_rows(read("playbook/roles.md"))
      assert [r["role"] for r in rows] == list(SPEC_ROLES)
      for r in rows:
          assert r["prompt block"] == "skills/strict-delivery/prompts/%s.md" % r["role"] and r["minimum tier"] in ("tier1", "tier2", "tier3", "tier4")
          if r["role"] in B_ROLES: assert os.path.isfile(r["prompt block"])
      assert {r["role"]: r["minimum tier"] for r in rows} == TIERS     # DB-2, all twelve
  TIERS = {"implementer_transcription": "tier1", "implementer": "tier2",
           "controller": "tier3", "program_controller": "tier3", "stream_controller": "tier3", "task_reviewer": "tier3",
           "final_reviewer": "tier3", "audit_reviewer": "tier3", "audit_verifier": "tier3", "investigator": "tier3",
           "final_verifier": "tier4", "exception_reviewer": "tier4"}
  def test_playbook_files_first_line_and_clean():
      for stem in ("rules", "roles", "decisions", "sessions", "streams", "review"):
          t = read("playbook/%s.md" % stem); assert t.split("\n", 1)[0] == "# Base playbook: " + stem and forbidden_hits(t) == []
  def test_decisions_playbook_human_only():
      assert "decisions decide" in read("playbook/decisions.md") and "human" in read("playbook/decisions.md")
  PLAYBOOK_SECTIONS = {   # file stem -> [(heading, key phrases)]; each phrase is quoted from the source cited on its line
      "decisions": [("Asking", ["`decisions ask`", "decisions find", "search before asking"]),              # spec §7.4
                    ("Answering", ["`decisions decide`", "`decisions withdraw`", "human"]),                  # spec §7.1
                    ("Lasting decisions", ["`landed_in`", "never a spec"])],                                 # spec §7.2, §7.4
      "sessions": [("Session kinds", ["`program`", "`program-controller`", "`sync`"]),                       # design §10
                   ("Start order", ["`in-force.md`", "`python3 -m gates context"]),                          # design §10, spec §9
                   ("Blocks and checkpoints", ["`block.max_tasks`", "`CHECKPOINT`"]),                        # spec §8, §9
                   ("Handoffs and continuation", ["handoff", "80 %", "Nothing continues from inherited memory"])],  # design §4.4
      "streams": [("Programs and streams", ["program_controller", "stream_controller", "disjoint set of files"]),  # spec §11
                  ("Cross-stream requests", ["never edits", "request"]),                                     # design §6
                  ("Syncs", ["`sync`", "integration branch"]),                                               # design §10
                  ("Status page", ["status page"])],                                                         # design §11
      "review": [("Task review", ["re-run every gate"]),                                                     # spec §8
                 ("Final review", ["whole branch"]),                                                   # Task B1.2
                 ("Verifier", ["`final_verifier`", "tier4"]),                                                # DB-2
                 ("Fix loop", ["rounds 1-3", "rounds 4-5", "owner question"]),                               # spec §10
                 ("Process-defect stop", ["process defect", "stop fixing"])],                                # spec §8
  }
  def test_playbook_sections_and_key_phrases():
      for stem, secs in PLAYBOOK_SECTIONS.items():
          t = read("playbook/%s.md" % stem)
          assert [l[3:] for l in t.split("\n") if l.startswith("## ")] == [h for h, _ in secs], stem
          for h, phrases in secs:
              body = section(t, h)
              for s in phrases: assert s.lower() in body.lower(), (stem, h, s)
  def test_section_helper_edges():              # absent and repeated headings fail; the last section runs to the end
      t = "# x\n\n## A\na1\n## B\nb1\n"
      assert section(t, "A") == "a1\n" and section(t, "B") == "b1\n"
      for text, heading in ((t, "C"), (t + "## A\n", "A")):
          try: section(text, heading)
          except AssertionError: continue
          raise AssertionError((text, heading))
  ```
- [ ] **Step 2: Run; expect FAIL.**
- [ ] **Step 3: Write the five files.**
- [ ] **Step 4: Run on both interpreters and every enabled gate; expect PASS.**
- [ ] **Step 5: Commit** `docs(playbook): roles, decisions, sessions, streams, review`, then checkpoint.

#### Task B2.3: the skill `SKILL.md`

**Files:**
- Create: `skills/strict-delivery/SKILL.md`
- Test: `tests/test_skill.py`

**Owner answers applied:** spec §3 precedence; spec §7.4 "Skill rule: search before asking."

**Interfaces:**
- Consumes: Tasks B1.1-B2.2.
- Produces: `skills/strict-delivery/SKILL.md`.
  - Front matter: line 1 `---`, then `name: strict-delivery`, then one `description:` line, then `---`.
  - Then `# Strict delivery` and the `## ` headings exactly, in order: `When it applies`, `Precedence`, `Roles and tiers`, `Decision classes`, `Verification method`, `Pipeline and gates`, `Continuation`, `Document locations`, `Judgment, not gated`.
  - `Precedence` lists spec §3's five layers in order.
  - `Roles and tiers` points at `playbook/roles.md` and names every `SPEC_ROLES` id.
  - `Decision classes` names `decision_classes.owner_only` and every default slug of spec §7.1.
  - `Verification method` states spec §8's "verify directly and by contradiction, record both commands".
  - `Pipeline and gates` names `python3 -m gates run_all` and spec §8's "Merge only on all-green under an owner grant".
  - `Continuation` states spec §8's continuation rule: a checkpoint or 80 % of budget writes a `handoff`, and "Nothing continues from inherited memory".
  - `Judgment, not gated` points at the `judgment` rows of `playbook/rules.md`.
  - `Document locations` names `docs/strict-delivery/specs/`, `docs/strict-delivery/plans/` and `docs/strict-delivery/reviews/`. Spec §3: "The skill and the CLAUDE.md managed block name the document locations (section 5)", and those locations override superpowers' default save paths. The skill states the override without spelling the superpowers path, so the forbidden list holds (owner answer DB-3).
  - The block-3 SessionStart hook consumes `name`.

**Input-domain dimensions:**
- Front matter: missing, `name` other than `strict-delivery`, two `description` lines.
- Headings: missing, reordered, extra `## `.
- Precedence: layers reordered or missing.
- A role id missing; a default owner-only slug missing.
- `SKILL_PHRASES`: each phrase absent, or present only in another section.
- Forbidden strings.

- [ ] **Step 1: Write the failing tests** (`tests/test_skill.py`):
  ```python
  HEADINGS = ["When it applies", "Precedence", "Roles and tiers", "Decision classes", "Verification method",
              "Pipeline and gates", "Continuation", "Document locations", "Judgment, not gated"]
  OWNER_ONLY = ["triage", "spec-direction", "scope", "merge-grant", "model-policy", "issue-close", "finding-class",
                "rule-override", "program-create", "stream-ownership", "stream-merge", "request-dispute", "program-close"]
  def test_front_matter():
      lines = read(SKILL).split("\n"); assert lines[0] == "---" and lines[1] == "name: strict-delivery" and lines[2].startswith("description: ") and lines[3] == "---"
  def test_headings_exact():
      assert [l[3:] for l in read(SKILL).split("\n") if l.startswith("## ")] == HEADINGS
  def test_precedence_order():
      p = section(read(SKILL), "Precedence")
      keys = ["CLAUDE.md", "skill and prompt blocks", "project playbook", "base playbook", "superpowers"]
      assert [p.index(k) for k in keys] == sorted(p.index(k) for k in keys)
  def test_roles_and_classes_named():
      for r in SPEC_ROLES: assert "`%s`" % r in section(read(SKILL), "Roles and tiers")
      for s in OWNER_ONLY: assert "`%s`" % s in section(read(SKILL), "Decision classes")
  def test_search_before_asking():
      assert "search before asking" in read(SKILL).lower()
  SKILL_PHRASES = {   # heading -> key phrases (case-insensitive), each from the source cited on its line
      "Verification method": ["directly", "by contradiction", "record both commands"],                 # spec §8
      "Pipeline and gates": ["`python3 -m gates run_all`", "all-green", "owner grant"],                 # spec §8
      "Continuation": ["handoff", "80 %", "Nothing continues from inherited memory"],                   # spec §8
      "Document locations": ["`docs/strict-delivery/specs/`", "`docs/strict-delivery/plans/`",
                             "`docs/strict-delivery/reviews/`", "override", "superpowers"],             # spec §3; paths from spec §5 layout
      "Judgment, not gated": ["judgment", "playbook/rules.md"],                                         # spec §8 rules.md line
  }
  def test_skill_section_phrases():
      for h, phrases in SKILL_PHRASES.items():
          body = section(read(SKILL), h).lower()
          for s in phrases: assert s.lower() in body, (h, s)
  def test_no_forbidden_strings_in_skill():
      assert forbidden_hits(read(SKILL)) == []
  ```
  (`OWNER_ONLY` repeats Task 1a.2's `DEFAULTS["decision_classes"]["owner_only"]` literally, so the test does not import `gates`. A second test, `test_owner_only_matches_config_defaults`, imports `gates.lib.config.DEFAULTS` and asserts equality once block 1a is on `main`, which it is before B2 starts. It guards against drift.)
- [ ] **Step 2: Run; expect FAIL.**
- [ ] **Step 3: Write `SKILL.md`.**
- [ ] **Step 4: Run on both interpreters and every enabled gate; expect PASS.**
- [ ] **Step 5: Commit** `docs(skill): strict-delivery skill`, then checkpoint. **Block B2 end:** final review, verifier, then the pull-request flow (stream rules, "Merging each block"), checkpoint. Stream B is then done: its paths pass to A (DS-3).

---

## Stream C: stack detection and `gate_cites` (branches `block/sc1`, then `block/sc2`)

Stream C builds two pieces of later blocks that depend only on block 1a:
- init's stack command detection (spec §17 block 4). Spec §4: "Detection invents nothing and only proposes; the owner confirms, edits or leaves out each command." Spec §18: "init's detection only offers the project's existing commands."
- `gate_cites` (spec §17 block 5). Spec §9: "`gate_cites`: every `path:line` and `path#anchor` cite in tracked docs resolves at HEAD." Owner answer DC-8 amends that to the tree being committed (spec edit E5); C builds to the amended text. The gate reads the working tree; owner answers F-3 and F-r3-1 make the working tree the tree being committed under the conditions of spec edits E5 and E10 (Task C2.2). Spec §7.4: "its anchor is checked by `gate_cites`".

C starts after block 1a merges into `main`. Global Constraints, the Process for this plan, and the stream rules above all apply. Tests build synthetic fixtures in temp directories and use `tests/helpers.py` (stream A) unchanged.

**Consumed later by:**
- Block 4 `init` calls `detect.detect(root)` and shows each `Proposal` with its `source` for the owner to confirm, edit or leave out. It writes only what the owner confirms into `commands`.
- Block 4's fixture repositories (node, rust, go, python, C with make, empty, monorepo) assert init's proposals against Task C1.2's table.
- `run_all` (block 2) runs `check cites` where the profile enables it (block 4 profiles). When `cites` joins `run_all` is fixed in the stream rules, "Cross-stream order".
- `doctor` (block 4).

### Block C1: stack command detection (branch `block/sc1`)

#### Task C1.1: the detection model, `package.json` and Makefiles

**Files:**
- Create: `gates/lib/detect.py`
- Test: `tests/test_detect.py`

**Owner answers applied:** spec §4 step 1, spec §18; DC-1 (the seven-row source table of Task C1.2), DC-2 (`test_one` never proposed), DC-3 (`root` only), DC-4 (always `npm run <name>`).

**Interfaces:**
- Consumes: `result.GateError` (Task 1a.2).
- Produces (`gates/lib/detect.py`):
  - `SLOTS: tuple` = `("test", "test_one", "lint", "build")`, from spec §4: "offer them for `test`, `test_one`, `lint` and `build`".
  - `@dataclass(frozen=True) Proposal(slot: str, command: str, source: str)`. `slot` is in `SLOTS`. `command` is the shell string offered for `commands.<slot>` (spec §6: "each a shell string or list"; detection offers a string). `source` names the file and the key or line the command came from, for example `package.json scripts.test` or `Makefile:12 test`.
  - `@dataclass(frozen=True) Problem(source: str, reason: str)`: a candidate source that could not be read. It is reported for init to show, never raised.
  - `@dataclass(frozen=True) Detection(proposals: tuple, problems: tuple)`.
  - `detect(root: str) -> Detection`. It reads only regular files directly in `root` (DC-3). It never runs a command, never writes, and never needs git.
    - If `root` is not a directory, it raises `GateError("<root>: not a directory")`.
    - Order: source order (`SOURCES`, Task C1.2's table), then slot order within a source. Duplicates across sources are kept, since the owner chooses.
    - `test_one` is never proposed; init always asks for it (DC-2).
  - `package.json` (DC-4: always `npm run`, whatever lockfile is present):
    - The file must be a regular file (`os.lstat`; a symlink gives `Problem("package.json", "symlink; not read")`).
    - It is decoded as `utf-8-sig`, and it must parse with `json.loads` (with `object_pairs_hook` refusing duplicate keys) into an object.
    - `scripts`, when present, is an object.
    - For each name in `("test", "lint", "build")` with a `str` value that is not empty and not only whitespace (`str.isspace()`; owner Q-C11-2), the result is `Proposal(name, "npm run " + name, "package.json scripts." + name)`.
    - Any other failure gives one `Problem("package.json", <reason>)` and no proposals from that file.
  - Makefile:
    - Of `GNUmakefile`, `makefile` and `Makefile`, in the order GNU make looks for them, only the first name that exists (by `os.lstat`) is a candidate, since GNU make reads that one and never a later one. Checked with GNU Make 3.81: a symlinked `GNUmakefile` is followed and `Makefile` is ignored; a directory or a dangling symlink named `GNUmakefile` stops make with an error.
      - If that entry is a regular file, it is read.
      - If it is a symlink, the result is `Problem("<name>", "symlink; not read")`, as for every source (Task C1.2). Any other kind (directory, FIFO) gives `Problem("<name>", "not a regular file")`.
      - In both problem cases no later name is read, so nothing is proposed that `make` would not run.
    - A rule line does not start with `\t` (that is a recipe line, or a "commands commence before first target" error). Its leading spaces, and any tabs after a first space, are skipped, as GNU make skips them. The rest does not start with `#` or `.`, and it matches `^([A-Za-z0-9_.-]+(?:[ \t]+[A-Za-z0-9_.-]+)*)[ \t]*::?(?![:=])`.
      - The lookahead refuses `:=`, `::=` and `:::=` at the colon: GNU make 4.x reads these as variable assignments, and GNU Make 3.81 fails on them (rc 2).
      - The target group admits only `[A-Za-z0-9_.-]` and blanks, so a line with `=`, `?=`, `+=` or `!=` before its first colon never matches. These are assignments too.
      - Checked with GNU Make 3.81, `make -n <target>` on a one-rule Makefile, recipe `\t@echo ran`:
        - rc 0, so proposed: `test:`, `test::`, `build test:` (both targets), `  test:` (leading spaces), ` \ttest:` (a space, then a tab).
        - Proposed as well, `test: dep` and `test : x`: with the prerequisite file present (`dep`, `x`) make gives rc 0 and runs the recipe; without it, rc 2 with "No rule to make target `dep', needed by `test'" (and the same for `x`), which names `test` as a rule. A target with no rule gives "No rule to make target `lint'" with no "needed by".
        - rc 2, so not proposed: `test := x`, `test ?= x`, `test += x`, `test != x`, `test=x`, `test:=x` ("No rule to make target `test'"); `test ::= x` ("No rule to make target `='"); `test::=x` ("No rule to make target `=x'"); `test :::= x` ("missing target pattern"); `\ttest:` as the first line or after an assignment ("commands commence before first target"); `\ttest:` after a rule (a recipe line); `# test:` and `  # test:`; `  test := x`.
        - Not proposed although make runs them, since detection reads literal target names only: `.PHONY: test` (rc 0, "Nothing to be done"), `$(T):` with `T = test`, `%:` and `test.o:` (implicit rules).
    - A line ending in `\` is joined with the next line, as GNU make joins them: the backslash, the newline and the next line's leading whitespace become one space. The joined text is one logical line, numbered by its first physical line. So `x \` followed by `test:` is the rule line `x test:` at line 1 (`make test` runs that target), while a recipe line `\t@echo a \` followed by `test:` stays a recipe line (`make test` finds no rule).
    - Lines between `define` and `endef` are skipped.
    - Each target named exactly `test`, `lint` or `build` gives `Proposal(name, "make " + name, "<file>:<line> " + name)`, the first definition only.
    - A file that is not UTF-8 gives a `Problem`.

**Input-domain dimensions:**
- `root`: missing, a file, a symlink to a directory (accepted, read through), unreadable.
- `package.json` file kind: absent, directory, symlink, FIFO, unreadable.
- `package.json` content:
  - empty, BOM, not UTF-8, invalid JSON;
  - top level a list, a string or `null`;
  - `scripts` absent, a list or `null`;
  - a script value non-str, empty str or whitespace only;
  - key case (`Test`), extra keys (`start`, `test:unit`), duplicate key.
- Makefile file names: each of the three; several present; lowercase-only on a case-insensitive filesystem; the first existing name a symlink (to a regular file, dangling), a directory or a FIFO, with a regular `Makefile` after it (one `Problem` for the first name; nothing read from `Makefile`).
- Rule lines:
  - `test:`, `test: dep`, `test::`, `build test:`;
  - `.PHONY: test`, `test := x`, `test ?= x`, `test += x`, `test != x`, `test ::= x`, `test :::= x`, `test::=x`, `test=x`, `test : x`;
  - leading spaces `  test:` (a rule), a space then a tab ` \ttest:` (a rule), `  test := x` (not a rule), `  # test:` (not a rule);
  - a recipe line `\ttest:` (after a rule; first in the file), `# test:`;
  - `$(T):`, `%:`, `test.o:`;
  - a rule line continued by `\` onto `test:` (a rule, numbered line 1); a recipe line continued by `\` onto `test:` (not a rule);
  - `define`/`endef`;
  - CRLF line ends, no final newline, a duplicate definition.
- Order: several sources and slots at once.
- Side effects: the tree is unchanged (a byte and mtime snapshot); no subprocess (patched `subprocess.run` and `os.system` assert not called).

- [ ] **Step 1: Write the failing tests** (`tests/test_detect.py`):
  ```python
  def test_empty_dir_proposes_nothing():
      assert detect(tmp) == Detection((), ())
  def test_root_not_a_directory():
      with self.assertRaises(GateError): detect(os.path.join(tmp, "nope"))
  def test_package_json_scripts():
      write("package.json", '{"scripts": {"test": "jest", "lint": "eslint .", "build": "tsc", "start": "node x"}}')
      assert detect(tmp).proposals == (Proposal("test", "npm run test", "package.json scripts.test"),
                                       Proposal("lint", "npm run lint", "package.json scripts.lint"),
                                       Proposal("build", "npm run build", "package.json scripts.build"))
  def test_package_json_bad_shapes_are_problems():   # subTests: "", "{", "[]", '{"scripts": []}', b"\xff", '{"a":1,"a":2}'
      d = detect(tmp); assert d.proposals == () and [p.source for p in d.problems] == ["package.json"]
  def test_script_value_not_usable_is_skipped():     # subTests: 1, "", "  ", None
      assert all(p.slot != "test" for p in detect(tmp).proposals)
  def test_package_json_symlink_refused():
      os.symlink(outside, os.path.join(tmp, "package.json"))
      assert detect(tmp).problems == (Problem("package.json", "symlink; not read"),)
  def test_makefile_rules():
      write("Makefile", "VAR := test\n.PHONY: test\nbuild test: dep\n\t@echo\nlint:: x\n  check:\n# lint:\n")
      assert [(p.slot, p.command, p.source) for p in detect(tmp).proposals] == [
          ("test", "make test", "Makefile:3 test"), ("lint", "make lint", "Makefile:5 lint"), ("build", "make build", "Makefile:3 build")]
  def test_makefile_variable_and_recipe_lines_are_not_rules():
      # subTests (each the whole Makefile; GNU Make 3.81 `make -n test` exits 2 on every one):
      #   "test=x\n", "test:=x\n", "test := x\n", "test ?= x\n", "test += x\n", "test != x\n",
      #   "test ::= x\n", "test::=x\n", "test :::= x\n", "  test := x\n", "  # test:\n", "# test:\n",
      #   "\ttest:\n", "x = 1\n\ttest:\n", "all:\n\ttest:\n", "all:\n\t@echo a \\\ntest:\n", "define D\ntest:\nendef\n"
      assert detect(tmp).proposals == ()
  def test_makefile_rule_after_leading_blanks():        # subTests: "  test:\n\t@echo ran\n", " \ttest:\n\t@echo ran\n" (3.81: rc 0, `ran`)
      assert [(p.slot, p.command, p.source) for p in detect(tmp).proposals] == [("test", "make test", "Makefile:1 test")]
  def test_makefile_continued_rule_line_joins():      # GNU make: `make test` runs this target
      write("Makefile", "x \\\ntest:\n\t@echo ran\n")
      assert [(p.slot, p.command, p.source) for p in detect(tmp).proposals] == [("test", "make test", "Makefile:1 test")]
  def test_first_existing_makefile_name_not_regular():  # subTests: GNUmakefile a symlink (to a file; dangling), a directory, a FIFO; a regular Makefile with "test:" after it
      d = detect(tmp); assert d.proposals == () and [p.source for p in d.problems] == ["GNUmakefile"]
  def test_gnu_make_file_precedence():                # GNUmakefile and Makefile both present
      assert {p.source.split(":")[0] for p in detect(tmp).proposals} == {"GNUmakefile"}
  def test_test_one_never_proposed():                 # every source of C1.1 and C1.2 present
      assert all(p.slot != "test_one" for p in detect(tmp).proposals)
  def test_detect_has_no_side_effects():
      before = snapshot(tmp)
      with mock.patch("subprocess.run") as run, mock.patch("os.system") as system: detect(tmp)
      assert snapshot(tmp) == before and not run.called and not system.called
  ```
- [ ] **Step 2: Run the test command; expect FAIL** (`ModuleNotFoundError: gates.lib.detect`).
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run on both interpreters and every enabled gate; expect PASS.**
- [ ] **Step 5: Commit** `feat(lib): stack command detection, package.json and Makefile`, then checkpoint in the stream-C ledger.

#### Task C1.2: toolchain sources and the source order

**Files:**
- Modify: `gates/lib/detect.py`, `tests/test_detect.py`

**Owner answers applied:** DC-1 (the seven-row table below; lint only from a project file that names it), DC-3.

**Interfaces:**
- Consumes: Task C1.1.
- Produces: `SOURCES: tuple` in this order, with these proposals (each source file a regular file directly in `root`; a symlink is a `Problem`; row 2 follows Task C1.1's first-existing-name rule):

  | # | Source | Condition | Proposals (`slot`: `command`; `source`) |
  |---|---|---|---|
  | 1 | `package.json` | Task C1.1 | Task C1.1 |
  | 2 | Makefile | Task C1.1 | Task C1.1 |
  | 3 | `Cargo.toml` | file present | `test`: `cargo test`; `build`: `cargo build`; source `Cargo.toml` |
  | 4 | `go.mod` | file present | `test`: `go test ./...`; `build`: `go build ./...`; source `go.mod` |
  | 5 | `mvnw` | file present (`mvnw.cmd` alone is not: Windows is out of v0.1, spec §1) | `test`: `./mvnw test`; `build`: `./mvnw package`; source `mvnw` |
  | 6 | `gradlew` | file present (`gradlew.bat` alone is not) | `test`: `./gradlew test`; `build`: `./gradlew build`; source `gradlew` |
  | 7 | `pyproject.toml` | a table header line `[tool.pytest.ini_options]` (test) or `[tool.ruff]` / `[tool.ruff.<sub>]` (lint), matched outside `"""` and `'''` multi-line strings, leading whitespace allowed, and after the `]` only trailing whitespace or a `#` comment (TOML allows both); the first matching header of each slot only, so `[tool.ruff]` and a later `[tool.ruff.lint]` give one lint proposal, sourced at the first | `test`: `python3 -m pytest`, source `pyproject.toml:<line> tool.pytest.ini_options`; `lint`: `ruff check .`, source `pyproject.toml:<line> tool.ruff` |

  No lint command is proposed from a toolchain alone (no `cargo clippy` or `go vet`): only a project file that names lint (a `lint` script or target, `[tool.ruff]`) gives one. Within each row, proposals follow `SLOTS` order.

**Input-domain dimensions:**
- Each source: absent, directory, symlink, empty file.
- `mvnw.cmd` or `gradlew.bat` without the POSIX wrapper.
- `pyproject.toml`:
  - the header with leading spaces (matched), with trailing whitespace or a trailing comment `[tool.ruff]  # lint` (matched), followed by other text `[tool.ruff] x` (not matched; not valid TOML), quoted (`["tool".pytest.ini_options]`: not matched, outside DC-1's table);
  - `[tool.ruff]` and then `[tool.ruff.lint]` in one file: one lint proposal, sourced at the first header;
  - inside a `"""` string, inside a `'''` string;
  - `[tool.pytest]` without `.ini_options` (not matched);
  - `[[tool.ruff]]` array table (not matched);
  - not UTF-8.
- All seven sources together: the full order.
- A monorepo with a sub-directory `package.json` only: nothing proposed (DC-3).

- [ ] **Step 1: Write the failing tests:**
  ```python
  def test_toolchain_sources():                         # subTests per row 3-6
      write(name, ""); assert [(p.slot, p.command, p.source) for p in detect(tmp).proposals] == EXPECTED[name]
  def test_windows_wrappers_alone_not_proposed():       # mvnw.cmd, gradlew.bat
      assert detect(tmp).proposals == ()
  def test_pyproject_headers():
      write("pyproject.toml", '[project]\nname = "x"\n  [tool.pytest.ini_options]\n[tool.ruff.lint]\n')
      assert [(p.slot, p.command, p.source) for p in detect(tmp).proposals] == [
          ("test", "python3 -m pytest", "pyproject.toml:3 tool.pytest.ini_options"), ("lint", "ruff check .", "pyproject.toml:4 tool.ruff")]
  def test_pyproject_trailing_comment_and_repeated_header():
      write("pyproject.toml", '[tool.ruff]  # lint\n[tool.ruff.lint]\n[tool.pytest.ini_options] \t\n')
      assert [(p.slot, p.command, p.source) for p in detect(tmp).proposals] == [
          ("test", "python3 -m pytest", "pyproject.toml:3 tool.pytest.ini_options"), ("lint", "ruff check .", "pyproject.toml:1 tool.ruff")]
      write("pyproject.toml", '[tool.ruff] x\n'); assert detect(tmp).proposals == ()
  def test_pyproject_header_inside_string_ignored():    # '"""\n[tool.pytest.ini_options]\n"""\n' and the ''' form
      assert detect(tmp).proposals == ()
  def test_full_source_order():                         # all seven present
      assert [p.source.split(" ")[0].split(":")[0] for p in detect(tmp).proposals] == ORDERED_SOURCES
  def test_monorepo_subdir_not_read():                  # packages/a/package.json only
      assert detect(tmp) == Detection((), ())
  ```
- [ ] **Step 2: Run; expect FAIL.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run on both interpreters and every enabled gate; expect PASS.**
- [ ] **Step 5: Commit** `feat(lib): toolchain detection sources and order`, then checkpoint. **Block C1 end:** final review, verifier, then the pull-request flow (stream rules, "Merging each block"), checkpoint, continuation.

### Block C2: `gate_cites` (branch `block/sc2`)

#### Task C2.1: the cite library

**Files:**
- Create: `gates/lib/cites.py`
- Create: `gates/lib/slug_table.py` (generated once, never edited by hand; owned by stream C, see the ownership table)
- Create: `gates/lib/case_table.py` (generated once, never edited by hand; owned by stream C, see the ownership table)
- Test: `tests/test_cites_lib.py`

**Owner answers applied:** spec §9, spec §7.4; DC-5 (backtick spans and inline link targets, placeholders excluded), DC-7 (GitHub ATX slug, `-1`, `-2` for repeats), Q-r5-1 (b) (`slugify` uses a frozen table, not `unicodedata`), Q-r6-1 (b) (`slugify` lowercases with a frozen case table, not `str.lower()`).

**Interfaces:**
- Consumes: the standard library (`bisect`), `gates/lib/slug_table.py` and `gates/lib/case_table.py` (this task creates both). Pure functions. None of the three modules imports `unicodedata`, and none calls `str.lower()` or another `str` case method.
- Produces (`gates/lib/slug_table.py`): `STRIP_RANGES: tuple`, a tuple of `(start, end)` pairs of integers, inclusive at both ends, sorted by `start`, non-overlapping and not touching (736 pairs, 977,500 code points, all within 0..0x10FFFF). They are exactly the code points that the regex of github-slugger 2.0.0 removes (the package file `regex.js`), generated once as Step 3 says. The file starts with a comment that says how it was generated and that it must not be edited by hand.
- Produces (`gates/lib/case_table.py`; owner answer Q-r6-1 (b)), generated once from the Unicode Character Database 13.0.0 (`https://www.unicode.org/Public/13.0.0/ucd/`) as Step 3 says. Unicode 13.0.0 is the version github-slugger 2.0.0 built its regex from (its source uses the npm package `@unicode/unicode-13.0.0`), so both tables state one Unicode version:
  - `LOWER: dict`, from `int` code point to its lowercase `str`, sorted by key: the simple lowercase of `UnicodeData.txt` (field 13), replaced by the unconditional lowercase of `SpecialCasing.txt` where that file has one. Only code points whose lowercase differs from themselves are keys (1,393). One value has two code points: U+0130 maps to `"i\u0307"`. U+03A3 maps to `"σ"`; `lowercase` applies the Final_Sigma rule for it in code. The conditional (language and context) entries of `SpecialCasing.txt` are not in the table.
  - `CASED_RANGES: tuple` (141 pairs, 4,286 code points) and `CASE_IGNORABLE_RANGES: tuple` (410 pairs, 2,413 code points), the `Cased` and `Case_Ignorable` properties of `DerivedCoreProperties.txt`, in the shape of `STRIP_RANGES` (inclusive `(start, end)` integer pairs, sorted, non-overlapping and not touching).
  - The file is ASCII (non-ASCII values are written as `\u` escapes) and starts with a comment that names the Unicode version and the three source files, and says it must not be edited by hand.
  - A sibling file, not more names in `slug_table.py`: each generated file then has one source and one generator, and `slug_table.py` stays byte-identical to the rev-6 output, so its pinned digests (`TABLE_SHA256` and the file SHA-256 of Step 3) stay valid.
- Produces (`gates/lib/cites.py`):
  - `@dataclass(frozen=True) Cite(doc: str, line: int, token: str, path: str, start: Optional[int], end: Optional[int], anchor: Optional[str])`. `doc` is the repo-relative doc path, `line` is 1-based, and `path` is the repo-relative target after resolution. Exactly one of `start` and `anchor` is set. `token` is the cite's source text: for the backtick form the code span with its backticks (`` `gates/x.py:9` ``); for the link form the destination as written, without the title and without the `<` and `>` of an angle-bracket destination, and before `%XX` decoding (``[s](b.md#nope)`` gives ``b.md#nope``). It is what `gate_cites` prints after the line number (Task C2.2).
  - `extract(doc: str, text: str) -> list` (DC-5):
    - Lines inside fenced code blocks are skipped. A fence is a line whose first non-space character, after at most three spaces, starts a run of three or more backticks or tildes; the block closes on the same character with a run at least as long.
    - **Code spans.** On each line outside fences, code spans are found as CommonMark finds them, within the line: a run of n backticks opens a span, the next run of exactly n backticks on the same line closes it, and a run with no such closer is literal text. Code spans take precedence over links, as in CommonMark: text inside any code span (of single or multiple backticks) is never scanned for the link form, so ``[t](b.md#c)`` and `[t](b.md#c "T")` give no link cite. A code span that CommonMark would continue onto the next line of a paragraph is not recognised (the scan is line-based, as the link form is), so its backtick run counts as literal text.
    - **Backtick form.** A code span of single backticks with no whitespace inside, fully matching `(?P<path>[^\s:#<>`]+?)(?::(?P<start>[0-9]+)(?:-(?P<end>[0-9]+))?|#(?P<anchor>[^\s#]*))`, whose `path` contains `/` or `.`, does not contain `://`, and is not 7-40 lowercase hex. The path is repo-relative.
    - **Link form.** An inline markdown link `[text](destination)` or `[text](destination title)`, on one line, that is not an image (`![`). The destination is parsed as CommonMark parses a link destination, and only the destination is the cite:
      - After `](` and any spaces or tabs, a destination that starts with `<` runs to the first `>`. The text between them is the destination, spaces included (`[t](<a b.md#c>)` gives `a b.md#c`). It must hold no `<`, or the link is not a cite.
      - Any other destination is the longest run of characters that are not whitespace or ASCII control characters, with balanced parentheses. It ends before the first whitespace, or before a `)` that has no open `(` in the run (``[t](a(b).md#c)`` gives ``a(b).md#c``).
      - After the destination come optional spaces or tabs, then an optional title, then optional spaces or tabs, then `)`. A title is `"..."`, `'...'` or `(...)`, with whitespace before it. It is ignored: `[t](b.md#c "T")`, `[t](b.md#c 'T')` and `[t](b.md#c (T))` each give ``b.md#c``. Anything else before the `)`, such as an unclosed title or a second word, means the text is not a link and gives no cite.
      - A destination that holds no `#`, or starts with a URL scheme (`[A-Za-z][A-Za-z0-9+.-]*:`), is not a cite.
      - The destination splits at its first `#` into a path part and an anchor. The path part is relative to `doc`'s directory, `%XX`-decoded, and normalised. An empty path part means `doc` itself.
      - Backslash escapes are not decoded. A token that holds `\` stays a `Cite`, and `problem` fails it (the path is not tracked, or no heading has that anchor).
      - A link whose destination or title spans lines is not a cite.
    - A token whose resolved path leaves the repository (`..` past the root), or starts with `/`, is still a `Cite`, and `problem` fails it.
  - `lowercase(text: str) -> str` (owner answer Q-r6-1 (b)): the Unicode 13.0.0 default lowercase conversion (full case mapping, independent of locale), read only from `case_table.py`. Each character becomes `LOWER.get(ord(ch), ch)`, except U+03A3 (`Σ`), which follows the Final_Sigma rule: it becomes `ς` (U+03C2) when, skipping case-ignorable characters, the nearest character before it is cased and the nearest character after it is not cased or there is none; otherwise `σ` (U+03C3). "Cased" and "case-ignorable" are lookups in `CASED_RANGES` and `CASE_IGNORABLE_RANGES` with `bisect.bisect_right`, as in step 2 below; a character in both counts as case-ignorable while skipping, as CPython's `str.lower()` and ICU do. So `Σ` is not mapped to `σ` always: the rule is applied, because github-slugger's `toLowerCase` applies it on Node 24.18.1 (`ΟΔΟΣ` gives `οδος`, `ΟΣΟ` gives `οσο`, `Σ` alone gives `σ`), and the table gives the same for every fixture of this task except the known limit below.
  - `slugify(heading: str) -> str` (DC-7, the GitHub rule; owner answers Q-r5-1 (b), Q-r6-1 (b)). This is github-slugger 2.0.0's `slug(value)`: `value.toLowerCase().replace(regex, '').replace(/ /g, '-')`. Standard library only, no `unicodedata`, no `str.lower()`:
    1. Lowercase the whole heading with `lowercase`, before any deletion, as github-slugger lowercases before its regex (so a character that step 2 deletes still counts as a neighbour for Final_Sigma: `Α²Σ` gives `ασ`, `ΑΣ²` gives `ας`, as on Node 24.18.1). github-slugger uses JavaScript's `String.prototype.toLowerCase`, the same conversion at its runtime's Unicode version; `lowercase` fixes the version at 13.0.0. There is no strip: `slugify(" a ")` is `"-a-"`.
    2. Delete each character whose code point lies in a range of `STRIP_RANGES`. The lookup is `bisect.bisect_right` on the tuple of range starts: take the last range whose `start` is at most the code point, and the character is deleted when the code point is at most that range's `end`. Every other character stays. The table holds what github-slugger's regex removes: `Other_Number`, the `Ps`, `Pe`, `Pi`, `Pf` and `Po` punctuation, `Dash_Punctuation` except `-`, every Symbol except the Alphabetic ones, `Control`, `Private_Use`, `Format`, every Separator except the space, and every code point unassigned in Unicode 13.0.0. A space, `-`, a letter, mark, `Nd`, `Nl` or `Pc` of Unicode 13.0.0, the 130 Alphabetic `So` code points (U+24B6-U+24E9, U+1F130-U+1F149, U+1F150-U+1F169, U+1F170-U+1F189) and a lone surrogate are not in it, so they stay.
    3. Turn each space into `-`.
    - So combining marks stay (`"Cafe\u0301 nfd"` gives `"cafe\u0301-nfd"`, `"\u0939\u093f\u0928\u094d\u0926\u0940"` stays whole), `Pc` stays (`"a\u203fb"` gives `"a\u203fb"`), `Other_Number` goes (`"x\u00b2 term"` gives `"x-term"`, `"\u00bd"` gives `""`), and a tab or no-break space goes (`"a\u00a0b"` gives `"ab"`).
    - Why a table: a category lookup follows the interpreter's Unicode version. Python 3.12 (Unicode 15.0.0) would keep 5,048 letters, marks and digits assigned after Unicode 13.0.0, and 3.13 (15.1.0) 5,670, which github-slugger removes as unassigned. The table removes the dependence: the delete step reads no interpreter data, so each code point gets the same verdict on every Python.
    - Checked by running the table against github-slugger's regex in Node (24.18.1) on every code point: 0 mismatches, and the regex uses no `\p{...}` escape and no `i` flag, so a Node's own Unicode version does not change its verdict.
    - Why a case table (owner answer Q-r6-1 (b)): `str.lower()` follows the interpreter's Unicode version, and so does Node's `toLowerCase`. Measured by script on Python 3.9.6 (Unicode 13.0.0), 3.12.14 (15.0.0), 3.13.18 (15.1.0) and Node 24.18.1 (Unicode 17.0): `str.lower()` differs between 3.9 and 3.13 for 40 single code points (all assigned after 13.0.0) and, over the strings `X+"\u03a3"`, `"a"+X+"\u03a3"` and `"a\u03a3"+X` for every code point `X`, for 650 strings (the final `\u03c2` or `\u03c3`; 3.12 equals 3.13). `lowercase` reads no interpreter data, so it gives one result on every Python 3.9+: over every code point alone and in those three strings it equals 3.9.6's `str.lower()` (both Unicode 13.0.0) with 0 differences, and its output is identical on 3.9.6 and 3.13.18 (`test_lowercase_is_the_same_on_every_interpreter`). The strip verdict of every single code point is unchanged by the switch (`VERDICT_SHA256` is the same value as with `str.lower()`).
    - Known limit (accepted with Q-r6-1 (b)): where a case mapping or a Cased/Case_Ignorable property changed after Unicode 13.0.0, the anchor can differ from the one GitHub's current Node gives. Measured against github-slugger 2.0.0 on Node 24.18.1 (Unicode 17.0), the known members are:
      - U+A7CB and U+A7DC (capital letters added in Unicode 16.0): Node lowers them to U+0264 `\u0264` and U+019B `\u019b`, which its regex keeps; the table has no mapping for them (unassigned in 13.0.0), so `slugify` keeps the capital and step 2 removes it (`""`). These are the only single code points whose slug differs from Node 24.18.1.
      - the Final_Sigma context: a `\u03a3` next to a code point whose Cased or Case_Ignorable property is newer than Unicode 13.0.0. Over the three string sets above, 1,060 strings differ from Node 24.18.1. Example: `"\U00010570\u03a3"` gives `\u03c3` (U+10570 is unassigned in 13.0.0, so not cased; step 2 then removes it), and Node 24.18.1 gives `\u03c2`. Both letters are kept, so only the slug text differs, and only for a heading with a capital sigma next to such a code point.
      - Node 24.18.1 is the only Node checked; a later Node can add members. A cite to such a heading uses the anchor `slugify` gives, which may not be the one GitHub's page shows.
  - `anchors(text: str) -> frozenset`. ATX headings (`#` to `######`, then a space) outside fences are taken in document order. Closing `#`s and the surrounding spaces are stripped, and each text is slugified. The result is `frozenset(number_repeats(<the slugs in order>))`.
  - `number_repeats(slugs: list) -> list` numbers repeats as github-slugger's `BananaSlug.slug` numbers them. With a map `occurrences` that starts empty, for each slug `s`: `result = s`; while `result` is in `occurrences`, add 1 to `occurrences[s]` and set `result = s + "-" + str(occurrences[s])`; then set `occurrences[result] = 0`, and `result` is the anchor. Headings `a`, `a-1`, `a` give `a`, `a-1`, `a-2`. Headings `a`, `a`, `a-1` give `a`, `a-1`, `a-1-1`.
  - `problem(cite: Cite, tracked: frozenset, read: Callable[[str], Optional[str]]) -> str`. It returns `""` when the cite resolves, else the reason:
    - `<path>: not a tracked file`;
    - `<path>: outside the repository`;
    - `<path>: line <n> is past the end (<k> lines)`;
    - `<path>: line numbers start at 1 and have no leading zero`;
    - `<path>: range end <e> is before start <s>`;
    - `<path>: no heading with anchor #<a>`;
    - `<path>: anchor on a non-markdown file`;
    - `<path>: empty anchor`;
    - `<path>: not UTF-8`;
    - `<path>: tracked but missing from the working tree` (`read` returned `None`).

    The line count is the number of `\n`-separated lines, where a final line without `\n` counts and a trailing `\n` adds none. "Markdown" means the path ends in `.md`.

**Input-domain dimensions:**
- Token forms:
  - backtick, link, a bare `path:3` in prose (not a cite), a double-backtick span, a span with a space;
  - the placeholder `path#anchor` (no `/` or `.`: not a cite), `<path>:<line>`, `abc1234:docs/x.md` (`<sha>:<path>`: not a cite);
  - `https://x/y#z`, `mailto:a@b`, an image link, a reference-style link `[a][b]` (not a cite).
- Link destinations and titles:
  - a title `"T"`, `'T'` or `(T)` after the destination (the cite is the destination only);
  - an angle-bracket destination `<a b.md#c>` (spaces kept), and one holding `<` (not a cite);
  - balanced parentheses in the destination ``a(b).md#c``;
  - a link inside a code span: `` `[t](b.md#c "T")` ``, ``` ``[t](b.md#c)`` ``` (no cite; code spans take precedence); a lone backtick before a link on the same line, `` `x [t](b.md#c) `` (the backtick is literal: a link cite);
  - `token`: a backtick cite keeps its backticks; a link cite is its destination as written (no title, no angle brackets, not `%XX`-decoded);
  - an unclosed title `[t](b.md#c "T)`, a second word `[t](b.md#c x)` (not links, no cite);
  - a destination holding `\` (a `Cite`, failed by `problem`);
  - a destination or title split across two lines (not a cite).
- Path forms:
  - `./a.md`, `../a.md` in a link from a nested doc, `..` past the root, `/abs.md`, `a//b.md`, a trailing `/`;
  - unicode, `%20`, `a b.md` (a space: no backtick cite).
- Line forms: `:0`, `:01`, `:1`, the last line, past the last line, `:3-1`, `:1-1`, `:2-9` past the end.
- File ends: a file ending without `\n`, an empty file, CRLF.
- Anchor forms: uppercase in the cite (`#Task`; not matched, slugs are lowercase), unicode heading, duplicate headings (`#x-1`), a heading with backticks or punctuation, a heading inside a fence, setext headings (not anchors; DC-7), `#` alone, an anchor on `.py`, `.MD`.
- Heading text (`slugify`, `anchors`; expected values from github-slugger 2.0.0):
  - a combining mark (NFD `Cafe\u0301`, Devanagari `हिन्दी`), an `Other_Number` (`²`, `½`), a non-`_` connector (`‿`), a circled letter (`Ⓐ`), a letter number (`Ⅻ`), final sigma (`ΟΔΟΣ`), an emoji, a tab, a no-break space, leading and trailing spaces;
  - a heading equal to an earlier numbered slug (`a`, `a-1`, `a`; `a`, `a`, `a-1`);
  - every code point 0..0x10FFFF, surrogates included, one at a time: the same result on every interpreter (a digest test); the first and last code point of each table range and the code point on each side of it (the digest covers them); a lone surrogate (kept); the 130 Alphabetic `So` code points (kept); U+A7CB and U+A7DC (removed; the known limit, Q-r6-1 (b));
  - lowercasing (`lowercase`, Q-r6-1 (b)): `Σ` word-final at the end (`ΟΔΟΣ`), word-final before a space (`ΟΔΟΣ ΚΑΙ`), medial (`ΟΣΟ`), alone (`Σ`), after a case-ignorable character (`Α'Σ`), next to a character step 2 deletes (`Α²Σ`, `ΑΣ²`), next to a code point unassigned in 13.0.0 (`\U00010570Σ`, the known limit); the Turkish dotted `İ` (U+0130, two code points `i\u0307`); every code point alone and in `X+"Σ"`, `"a"+X+"Σ"`, `"a"+"Σ"+X`, the same on every interpreter (a digest test) and equal to `str.lower()` where the interpreter's Unicode is 13.0.0;
  - `STRIP_RANGES`: its shape (a tuple of integer pairs, sorted, non-overlapping and not touching, within range) and its SHA-256;
  - `LOWER`, `CASED_RANGES`, `CASE_IGNORABLE_RANGES`: their shape and their SHA-256; no `str` case method in `cites.py` or `case_table.py`;
  - every case of github-slugger's `test/fixtures.json`.
- Fences: backticks, tildes, a longer closing fence, an unclosed fence (runs to the end of the file), an indented fence of four spaces (not a fence).
- `read` returning `None` (the file was deleted from the working tree): `<path>: tracked but missing from the working tree`.

- [ ] **Step 1: Write the failing tests** (`tests/test_cites_lib.py`):
  ```python
  def test_backtick_line_and_anchor_forms():
      cs = extract("docs/a.md", "see `gates/x.py:3` and `docs/b.md#intro` and `path#anchor` and `abc1234:docs/b.md`\n")
      assert [(c.path, c.start, c.anchor) for c in cs] == [("gates/x.py", 3, None), ("docs/b.md", None, "intro")]
  def test_link_relative_to_doc():
      cs = extract("docs/specs/a.md", "[x](../plans/p.md#task-1) [y](#local) [z](https://h/p#q) ![i](img.png#a)\n")
      assert [(c.path, c.anchor) for c in cs] == [("docs/plans/p.md", "task-1"), ("docs/specs/a.md", "local")]
  def test_link_title_and_angle_destination():         # the cite is the destination only; the title is ignored
      cs = extract("d/a.md", '[t](b.md#c "T") [t](b.md#c \'T\') [t](b.md#c (T)) [t](<x y.md#z>) [t](p(1).md#q)\n')
      assert [(c.path, c.anchor) for c in cs] == [("d/b.md", "c")] * 3 + [("d/x y.md", "z"), ("d/p(1).md", "q")]
  def test_link_forms_that_are_not_cites():             # subTests: unclosed title, second word, `<` inside <...>, split lines
      for text in ('[t](b.md#c "T)\n', '[t](b.md#c x)\n', '[t](<b<.md#c>)\n', '[t](b.md#c\n"T")\n', '[t](<b.md#c\n>)\n'):
          assert extract("d/a.md", text) == []
  def test_link_inside_code_span_not_a_cite():          # CommonMark: code spans take precedence over links
      for text in ('`[t](b.md#c "T")`\n', '``[t](b.md#c)``\n', '``[t](b.md#c "T")``\n', 'x ```[t](b.md#c)```\n'):
          assert extract("d/a.md", text) == []
      assert [(c.path, c.anchor) for c in extract("d/a.md", "`x [t](b.md#c)\n")] == [("d/b.md", "c")]   # lone backtick is literal
  def test_cite_token_text():                           # backtick form keeps its backticks; link form is the destination as written
      cs = extract("d/a.md", '`gates/x.py:9` [s](b.md#nope "T") [u](<x%20y.md#z>)\n')
      assert [c.token for c in cs] == ["`gates/x.py:9`", "b.md#nope", "x%20y.md#z"] and cs[2].path == "d/x y.md"
  def test_link_backslash_fails_closed():
      (c,) = extract("d/a.md", "[t](b\\_c.md#x)\n")
      assert c.path == "d/b\\_c.md" and "not a tracked file" in problem(c, frozenset({"d/b_c.md"}), r)
  def test_fenced_lines_skipped():
      assert extract("a.md", "```\n`x/y.py:1`\n```\n~~~~\n`x/y.py:2`\n~~~~\n") == []
  def test_slugify_github_rule():
      assert slugify("Task 1a.2: result contract, config loader, git helpers") == "task-1a2-result-contract-config-loader-git-helpers"
      assert slugify("`gate_cites` and Ünïcode") == "gate_cites-and-ünïcode"
      for heading, slug in [("Cafe\u0301 nfd", "cafe\u0301-nfd"), ("\u0939\u093f\u0928\u094d\u0926\u0940", "\u0939\u093f\u0928\u094d\u0926\u0940"),
                            ("x\u00b2 term", "x-term"), ("\u00bd", ""), ("a\u203fb", "a\u203fb"), ("\u24b6 circled", "\u24d0-circled"),
                            ("\u216b roman", "\u217b-roman"), ("\u039f\u0394\u039f\u03a3", "\u03bf\u03b4\u03bf\u03c2"),
                            ("\U0001f604 emoji", "-emoji"), ("a\tb", "ab"), ("a\u00a0b", "ab"), (" a ", "-a-")]:
          with self.subTest(heading=heading):
              assert slugify(heading) == slug
  # github-slugger 2.0.0, test/fixtures.json: cases 0-42, 45 (Connector_Punctuation), 55 (Line_Separator) and 68
  # (Paragraph_Separator), in file order, with their expected slugs. Its test runs them through one slugger, so the
  # numbering carries over from case to case; number_repeats does the same.
  SLUGGER_FIXTURES = [('alpha', 'alpha'), ('alpha', 'alpha-1'), ('bravoCharlieDelta', 'bravocharliedelta'), ('__proto__', '__proto__'),
      ('__proto__', '__proto__-1'), ('hasOwnProperty', 'hasownproperty'), ('echo', 'echo'), ('echo', 'echo-1'), ('echo 1', 'echo-1-1'),
      ('echo-1', 'echo-1-2'), ('echo', 'echo-2'), ('foxtrot-1', 'foxtrot-1'), ('foxtrot', 'foxtrot'), ('foxtrot', 'foxtrot-2'),
      ('heading with a - dash', 'heading-with-a---dash'), ('heading with an _ underscore', 'heading-with-an-_-underscore'),
      ('heading with a period.txt', 'heading-with-a-periodtxt'),
      ('exchange.bind_headers(exchange, routing [, bindCallback])', 'exchangebind_headersexchange-routing--bindcallback'), (' ', '-'), (' a', '-a'),
      ('a ', 'a-'), (' a ', '-a-'), ('-a-', '-a--1'), ('apostrophe\u2019s should be trimmed', 'apostrophes-should-be-trimmed'), ('golf', 'golf'),
      ('golf', 'golf-1'), ('golf', 'golf-2'), ('I \u2665 unicode', 'i--unicode'), ('dash-dash', 'dash-dash'), ('en\u2013dash', 'endash'),
      ('em\u2013dash', 'emdash'), ('\U0001f604 unicode emoji', '-unicode-emoji'), ('\U0001f604-\U0001f604 unicode emoji', '--unicode-emoji'),
      ('\U0001f604_\U0001f604 unicode emoji', '_-unicode-emoji'), ('\U0001f604 - an emoji', '---an-emoji'),
      (':smile: - a gemoji', 'smile---a-gemoji'), ('\u041f\u0440\u0438\u0432\u0435\u0442', '\u043f\u0440\u0438\u0432\u0435\u0442'),
      ('\u041f\u0440\u043e\u0444\u0438\u043b\u0438 \u043f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u0442\u0435\u043b\u0435\u0439', '\u043f\u0440\u043e\u0444\u0438\u043b\u0438-\u043f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u0442\u0435\u043b\u0435\u0439'),
      ('\u041f\u0440\u0438\u0432\u0435\u0442 non-latin \u4f60\u597d', '\u043f\u0440\u0438\u0432\u0435\u0442-non-latin-\u4f60\u597d'),
      (':ok: No underscore', 'ok-no-underscore'), (':ok_hand: Single', 'ok_hand-single'),
      (':ok_hand::hatched_chick: Two in a row with no spaces', 'ok_handhatched_chick-two-in-a-row-with-no-spaces'),
      (':ok_hand: :hatched_chick: Two in a row', 'ok_hand-hatched_chick-two-in-a-row'),
      ('a_ \u203f \u2040 \u2054 \ufe33 \ufe34 \ufe4d \ufe4e \ufe4f \uff3fb', 'a_-\u203f-\u2040-\u2054-\ufe33-\ufe34-\ufe4d-\ufe4e-\ufe4f-\uff3fb'),
      ('a\u2028b', 'ab'), ('a\u2029b', 'ab-1')]
  def test_github_slugger_fixtures():
      assert number_repeats([slugify(i) for i, _ in SLUGGER_FIXTURES]) == [e for _, e in SLUGGER_FIXTURES]
  import ast, hashlib, pathlib, unicodedata             # at the top of the module, with `from gates.lib import case_table, cites, slug_table`
  TABLE_SHA256 = "1af71c6876ad0341fc2550fb347218e790e26b6e05022c29818bd530e975e0ad"      # sha256 of repr(STRIP_RANGES)
  VERDICT_SHA256 = "1e74d3aead4367260822a28fefe88aae7e8d1f8f08ac4cb68cdb852995200bfd"    # see test_strip_verdict_is_the_same_on_every_interpreter
  def test_slug_table_shape():
      t = slug_table.STRIP_RANGES
      assert isinstance(t, tuple) and all(isinstance(p, tuple) and len(p) == 2 for p in t)
      assert len(t) == 736 and sum(e - s + 1 for s, e in t) == 977500
      assert all(type(s) is int and type(e) is int and 0 <= s <= e <= 0x10FFFF for s, e in t)
      assert all(t[i][1] + 1 < t[i + 1][0] for i in range(len(t) - 1))     # sorted, non-overlapping, not touching
  def test_slug_table_is_not_hand_edited():
      assert hashlib.sha256(repr(slug_table.STRIP_RANGES).encode()).hexdigest() == TABLE_SHA256
  def test_slugify_does_not_use_unicodedata():
      for mod in (cites, slug_table, case_table):
          text = pathlib.Path(mod.__file__).read_text(encoding="utf-8")
          names = {a.name.split(".")[0] for n in ast.walk(ast.parse(text)) if isinstance(n, ast.Import) for a in n.names}
          names |= {n.module.split(".")[0] for n in ast.walk(ast.parse(text)) if isinstance(n, ast.ImportFrom) and n.module}
          assert "unicodedata" not in names and "unicodedata" not in text      # nor __import__("unicodedata")
  def test_strip_verdict_is_the_same_on_every_interpreter():
      # By construction slugify reads no interpreter data. The digest was computed once on 3.9.6, 3.12.14 and 3.13.18 and was
      # equal on all three; the test passes on an interpreter only if it gives the same result for every code point.
      rows = "\n".join("%X:%s" % (cp, cites.slugify(chr(cp)).encode("utf-8", "surrogatepass").hex()) for cp in range(0x110000))
      assert hashlib.sha256(rows.encode()).hexdigest() == VERDICT_SHA256
  CASE_TABLE_SHA256 = "ed4381372f893a5f8ae953f095f52bbe8f11f76d5e9346bd1cec11bec09a15ff"  # see test_case_table_is_not_hand_edited
  LOWER_SHA256 = "f364d1ca036a14eafd06621641360296cb23686fdac2d27d811a2c71518b7a13"       # see test_lowercase_is_the_same_on_every_interpreter
  def test_case_table_shape():
      low = case_table.LOWER
      assert type(low) is dict and len(low) == 1393 and list(low) == sorted(low)
      assert all(type(k) is int and 0 <= k <= 0x10FFFF and type(v) is str and v and v != chr(k) for k, v in low.items())
      assert [k for k, v in low.items() if len(v) != 1] == [0x130] and low[0x130] == "i\u0307" and low[0x3A3] == "\u03c3"
      for t, n, total in ((case_table.CASED_RANGES, 141, 4286), (case_table.CASE_IGNORABLE_RANGES, 410, 2413)):
          assert isinstance(t, tuple) and len(t) == n and sum(e - s + 1 for s, e in t) == total
          assert all(type(p) is tuple and len(p) == 2 and type(p[0]) is int and type(p[1]) is int and 0 <= p[0] <= p[1] <= 0x10FFFF for p in t)
          assert all(t[i][1] + 1 < t[i + 1][0] for i in range(len(t) - 1))     # sorted, non-overlapping, not touching
  def test_case_table_is_not_hand_edited():
      lower = tuple((k, tuple(ord(c) for c in v)) for k, v in sorted(case_table.LOWER.items()))     # code points, not repr(str)
      canon = repr((lower, case_table.CASED_RANGES, case_table.CASE_IGNORABLE_RANGES))
      assert hashlib.sha256(canon.encode()).hexdigest() == CASE_TABLE_SHA256
  def test_slugify_does_not_use_str_lower():
      for mod in (cites, case_table):
          tree = ast.parse(pathlib.Path(mod.__file__).read_text(encoding="utf-8"))
          methods = ("lower", "casefold", "upper", "swapcase", "title", "capitalize")
          assert [n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute) and n.attr in methods] == [], mod.__name__
  def test_slugify_case_table_cases():
      # Expected values: the frozen Unicode 13.0.0 case table. github-slugger 2.0.0 on Node 24.18.1 (Unicode 17.0) gives the same
      # for every row except the last three, the known limit of Task C2.1: there they give "\u03c2", "\u0264" and "\u019b".
      for heading, slug in [("\u039f\u0394\u039f\u03a3", "\u03bf\u03b4\u03bf\u03c2"),
                            ("\u039f\u0394\u039f\u03a3 \u039a\u0391\u0399", "\u03bf\u03b4\u03bf\u03c2-\u03ba\u03b1\u03b9"),
                            ("\u039f\u03a3\u039f", "\u03bf\u03c3\u03bf"), ("\u03a3", "\u03c3"), ("\u0391'\u03a3", "\u03b1\u03c2"),
                            ("\u0391\u00b2\u03a3", "\u03b1\u03c3"), ("\u0391\u03a3\u00b2", "\u03b1\u03c2"),
                            ("\u0130", "i\u0307"), ("\u0130stanbul", "i\u0307stanbul"),
                            ("\U00010570\u03a3", "\u03c3"), ("\ua7cb", ""), ("\ua7dc", "")]:
          assert slugify(heading) == slug, heading
  def test_lowercase_is_the_same_on_every_interpreter():
      # lowercase() of every code point X alone and in X+"\u03a3", "a"+X+"\u03a3", "a\u03a3"+X (surrogates skipped). The digest was computed once
      # on 3.9.6 and 3.13.18 and was equal. Where the interpreter's Unicode is 13.0.0 (Python 3.9), str.lower() follows the same
      # version, so each result must also equal str.lower(): a check of the generated table against CPython's own tables.
      same_version = unicodedata.unidata_version == "13.0.0"
      rows = []
      for cp in range(0x110000):
          if 0xD800 <= cp <= 0xDFFF:
              continue
          x = chr(cp)
          for s in (x, x + "\u03a3", "a" + x + "\u03a3", "a\u03a3" + x):
              low = cites.lowercase(s)
              assert not same_version or low == s.lower(), hex(cp)
              rows.append(low)
      assert hashlib.sha256("\n".join(rows).encode("utf-8")).hexdigest() == LOWER_SHA256
  def test_repeat_numbering_skips_taken_slugs():
      assert number_repeats(["a", "a-1", "a"]) == ["a", "a-1", "a-2"]
      assert number_repeats(["a", "a", "a-1"]) == ["a", "a-1", "a-1-1"]
      assert anchors("# a\n# a-1\n# a\n") == frozenset({"a", "a-1", "a-2"})
  def test_duplicate_headings_numbered():
      assert anchors("# A\n## A\n### A\n") == frozenset({"a", "a-1", "a-2"})
  def test_line_bounds():                               # file text "1\n2\n3" (3 lines) and "1\n2\n3\n" (3 lines)
      assert problem(cite(start=3), T, r) == "" and "past the end (3 lines)" in problem(cite(start=4), T, r)
      assert "no leading zero" in problem(cite_from("`a/b.py:01`"), T, r) and "start at 1" in problem(cite_from("`a/b.py:0`"), T, r)
      assert "before start" in problem(cite_from("`a/b.py:3-1`"), T, r)
  def test_target_kinds():                              # untracked, outside repo, non-md anchor, empty anchor, read -> None
      assert "not a tracked file" in problem(cite_from("`x/untracked.md#a`"), T, r)
      assert "outside the repository" in problem(extract("a.md", "[x](../../out.md#a)\n")[0], T, r)
      assert "non-markdown" in problem(cite_from("`a/b.py#x`"), T, r) and "empty anchor" in problem(cite_from("`a/c.md#`"), T, r)
      assert "tracked but missing from the working tree" in problem(cite_from("`a/b.py:1`"), T, lambda p: None)
  ```
- [ ] **Step 2: Run; expect FAIL.**
- [ ] **Step 3: Implement.** Generate `gates/lib/slug_table.py` first, once, and do not edit it afterwards. In an empty scratch directory run `npm pack github-slugger@2.0.0` and unpack the tarball (the file needed is its `regex.js`). Save the script below outside that directory as `genpy.mjs` and run `node genpy.mjs <unpacked>/package/regex.js gates/lib/slug_table.py` from the worktree. The script reads `regex.js` as text, rebuilds its regex and tests every code point. Expected output: `ranges 736`, a file of 136 lines whose `repr(STRIP_RANGES)` has SHA-256 `1af71c6876ad0341fc2550fb347218e790e26b6e05022c29818bd530e975e0ad` (the value `TABLE_SHA256` pins) and whose bytes have SHA-256 `7683c6fb964373892708bce79c2ba155e95eff2e9ac171cdd073d391101b92d1`. A different digest means stop and report; never repair the table by hand. Then write `lowercase`, `slugify`, `number_repeats` and the rest in `gates/lib/cites.py`, once both tables are generated (the case table's commands follow the script below).
  ```js
// Usage: node genpy.mjs <path to github-slugger 2.0.0's regex.js> <output slug_table.py>
import fs from 'node:fs'
const [, , regexFile, outFile] = process.argv
const m = fs.readFileSync(regexFile, 'utf8').match(/export const regex = \/(.*)\/g\s*$/m)
const strip = new RegExp(m[1], 'g')
const pairs = []
let start = -1
for (let cp = 0; cp <= 0x110000; cp++) {
  let removed = false
  if (cp <= 0x10FFFF) {
    strip.lastIndex = 0
    removed = (cp >= 0xD800 && cp <= 0xDFFF ? String.fromCharCode(cp) : String.fromCodePoint(cp)).replace(strip, '') === ''
  }
  if (removed && start < 0) start = cp
  if (!removed && start >= 0) { pairs.push([start, cp - 1]); start = -1 }
}
const lines = []
let cur = '   '
for (const [a, b] of pairs) {
  const item = ` (${a}, ${b}),`
  if (cur.length + item.length > 100) { lines.push(cur); cur = '   ' }
  cur += item
}
lines.push(cur)
const header = [
  '# GENERATED FILE. DO NOT EDIT BY HAND.',
  '# Source: the published regex of github-slugger 2.0.0 (the package file regex.js). Node evaluated it',
  '# once on every code point 0..0x10FFFF (a surrogate code point as the lone UTF-16 unit). This table',
  '# holds each range of code points the regex removes, as inclusive (start, end) integer pairs.',
  '# gates/lib/cites.py slugify() deletes a character that lies in these ranges.',
  '# To change it, regenerate it from that source (plan Task C2.1, Step 3). tests/test_cites_lib.py',
  '# pins its SHA-256.',
  '',
  'STRIP_RANGES = ('
].join('\n')
fs.writeFileSync(outFile, header + '\n' + lines.join('\n') + '\n)\n')
console.log('ranges', pairs.length)
  ```
  Then generate `gates/lib/case_table.py` the same way, once, and do not edit it afterwards (owner answer Q-r6-1 (b)). In an empty scratch directory download the three Unicode 13.0.0 files: `curl -fsSLO https://www.unicode.org/Public/13.0.0/ucd/UnicodeData.txt`, and the same for `SpecialCasing.txt` and `DerivedCoreProperties.txt`. Their SHA-256 must be `bdbffbbfc8ad4d3a6d01b5891510458f3d36f7170422af4ea2bed3211a73e8bb` (`UnicodeData.txt`), `6424312f1dc39b22e0ff9c0ffb13dfad424d9b03e6a6dc6bca941f6bf5ef1ffd` (`SpecialCasing.txt`) and `a5d45f59b39deaab3c72ce8c1a2e212a5e086dff11b1f9d5bb0e352642e82248` (`DerivedCoreProperties.txt`). The version check is those digests together with the download path `/Public/13.0.0/ucd/`; in addition, the first line of `SpecialCasing.txt` is `# SpecialCasing-13.0.0.txt` and that of `DerivedCoreProperties.txt` is `# DerivedCoreProperties-13.0.0.txt`. `UnicodeData.txt` has no header line (its first line is `0000;<control>;Cc;0;BN;;;;;N;NULL;;;;`); its SHA-256 identifies it. Save the script below outside that directory as `gencase.py` and run `python3 -I gencase.py <scratch dir> gates/lib/case_table.py` from the worktree. The script parses the three files as text and imports nothing but `sys`. Expected output: `lower 1393 cased 141 case_ignorable 410`, an ASCII file of 367 lines whose canonical form (as `test_case_table_is_not_hand_edited` computes it) has SHA-256 `ed4381372f893a5f8ae953f095f52bbe8f11f76d5e9346bd1cec11bec09a15ff` (the value `CASE_TABLE_SHA256` pins) and whose bytes have SHA-256 `7e8f6dd03b85d3153ee3380e9f740ffd1daae10684b8a6295c202091dd1fa18f`. Regenerate once more with `python3.13 -I gencase.py <scratch dir> <scratch dir>/case_table.py` and compare the two files with `cmp`: they must be identical (the table equals a regeneration, on both interpreters). A different digest or a `cmp` difference means stop and report; never repair the table by hand.
  ```python
# Usage: python3 -I gencase.py <directory holding the three Unicode 13.0.0 UCD files> <output case_table.py>
import sys

ucd, out = sys.argv[1], sys.argv[2]


def rows(name):
    with open(ucd + "/" + name, encoding="utf-8") as f:
        for line in f:
            line = line.split("#", 1)[0].strip()
            if line:
                yield [field.strip() for field in line.split(";")]


lower = {}
for r in rows("UnicodeData.txt"):
    if r[13]:
        lower[int(r[0], 16)] = chr(int(r[13], 16))
for r in rows("SpecialCasing.txt"):                    # code; lower; title; upper; [condition_list;]
    if len(r) == 5 or (len(r) == 6 and r[4] == ""):    # unconditional entries only; Final_Sigma is in slugify's code
        cp, low = int(r[0], 16), "".join(chr(int(x, 16)) for x in r[1].split())
        if low != chr(cp):
            lower[cp] = low
        else:
            lower.pop(cp, None)


def ranges(prop):
    cps = set()
    for r in rows("DerivedCoreProperties.txt"):
        if r[1] == prop:
            a, _, b = r[0].partition("..")
            cps.update(range(int(a, 16), int(b or a, 16) + 1))
    pairs = []
    for cp in sorted(cps):
        if pairs and pairs[-1][1] + 1 == cp:
            pairs[-1][1] = cp
        else:
            pairs.append([cp, cp])
    return [tuple(p) for p in pairs]


def wrap(items):
    lines, cur = [], "   "
    for item in items:
        if len(cur) + len(item) > 100:
            lines.append(cur)
            cur = "   "
        cur += item
    lines.append(cur)
    return "\n".join(lines)


cased, ignorable = ranges("Cased"), ranges("Case_Ignorable")
text = "\n".join([
    "# GENERATED FILE. DO NOT EDIT BY HAND.",
    "# Source: the Unicode Character Database 13.0.0 (https://www.unicode.org/Public/13.0.0/ucd/):",
    "# LOWER from UnicodeData.txt (simple lowercase) overridden by the unconditional entries of",
    "# SpecialCasing.txt (full lowercase); CASED_RANGES and CASE_IGNORABLE_RANGES from the Cased and",
    "# Case_Ignorable properties of DerivedCoreProperties.txt, as inclusive (start, end) integer pairs.",
    "# gates/lib/cites.py slugify() lowercases with these tables (U+03A3 by the Final_Sigma rule).",
    "# To change it, regenerate it from that source (plan Task C2.1, Step 3). tests/test_cites_lib.py",
    "# pins its SHA-256.",
    "",
    "LOWER = {",
    wrap(" %d: %s," % (cp, ascii(lower[cp])) for cp in sorted(lower)),
    "}",
    "",
    "CASED_RANGES = (",
    wrap(" (%d, %d)," % p for p in cased),
    ")",
    "",
    "CASE_IGNORABLE_RANGES = (",
    wrap(" (%d, %d)," % p for p in ignorable),
    ")",
    "",
])
with open(out, "w", encoding="ascii", newline="\n") as f:
    f.write(text)
print("lower", len(lower), "cased", len(cased), "case_ignorable", len(ignorable))
  ```
- [ ] **Step 4: Run on both interpreters (3.9 and 3.13) and every enabled gate; expect PASS.** Then run the mutants, each against the finished task, and expect the named tests to fail on both interpreters (fix reverted, then restored):
  - M1 delete the first pair of `STRIP_RANGES`: `test_slug_table_shape`, `test_slug_table_is_not_hand_edited`, `test_strip_verdict_is_the_same_on_every_interpreter`.
  - M2 swap the first two pairs: the same three tests and `test_github_slugger_fixtures`.
  - M3 change the last pair's end to `1114112`: `test_slug_table_shape`, `test_slug_table_is_not_hand_edited`.
  - M4 `bisect_left` in place of `bisect_right`, or `cp < end` in place of `cp <= end`: `test_github_slugger_fixtures`, `test_strip_verdict_is_the_same_on_every_interpreter`.
  - M5 `slugify` keeps every code point (the lookup returns `False`): the same two tests.
  - M6 `slugify` without lowering (`lowercase` returns its input): the same two tests and `test_slugify_github_rule`, `test_slugify_case_table_cases`, `test_lowercase_is_the_same_on_every_interpreter`.
  - M7 `import unicodedata` added to `cites.py`: `test_slugify_does_not_use_unicodedata`.
  - M8 `lowercase` returns `text.lower()`: `test_slugify_does_not_use_str_lower` on both interpreters, and on 3.13 also `test_slugify_case_table_cases` and `test_lowercase_is_the_same_on_every_interpreter`.
  - M9 `Σ` always becomes `σ` (no Final_Sigma): `test_slugify_github_rule`, `test_slugify_case_table_cases`, `test_lowercase_is_the_same_on_every_interpreter`.
  - M10 Final_Sigma without skipping case-ignorable characters: `test_slugify_case_table_cases`, `test_lowercase_is_the_same_on_every_interpreter`.
  - M11 delete the `LOWER` entry of U+0130: `test_case_table_shape`, `test_case_table_is_not_hand_edited`, `test_slugify_case_table_cases`, `test_lowercase_is_the_same_on_every_interpreter`, `test_strip_verdict_is_the_same_on_every_interpreter`.
  - M12 change the first pair of `CASE_IGNORABLE_RANGES` to `(39, 40)`: `test_case_table_shape`, `test_case_table_is_not_hand_edited`, `test_lowercase_is_the_same_on_every_interpreter`.
- [ ] **Step 5: Commit** `feat(lib): cite extraction, anchors and resolution`, then checkpoint. The commit includes `gates/lib/slug_table.py` and `gates/lib/case_table.py`.

#### Task C2.2: `gate_cites`; request `check cites`; enable

**Files:**
- Create: `gates/gate_cites.py`
- Test: `tests/test_gate_cites.py`
- Request to stream A: register `cites` in the `check` dispatcher of `gates/__main__.py` (Task 1b.1's mechanism). Only if block 2 has merged into `main` first: a second request, to add `cites` to `run_all`'s gate list (stream rules, "Cross-stream order").

**Owner answers applied:** spec §9 (as amended by DC-8), §7.4, §13, §16 ("Each gate is enabled on this repository as soon as it lands"); DC-6 (every tracked `*.md`), DC-8 (cites resolve in the tree being committed), F-3 and F-r3-1 (the gate reads the working tree; the clean-tree refusal of E10 makes it the tree being committed).

**Interfaces:**
- Consumes:
  - `result.Result`, `run_gate`, `gate_args` and `GateError`;
  - `config.load`;
  - `gitinfo.tracked_files`;
  - `store.Store` (Task 1a.3; decision records, `landed_in`);
  - Task C2.1.
- Produces: `gates/gate_cites.py` with `PRODUCES = ()`, `check(args: list) -> Result` (gate `cites`) and `main(argv: Optional[list] = None) -> int` (`run_gate("cites", check, argv)`). Argument: `--root`.
  - Docs (DC-6): every path in `tracked_files(root)` ending `.md`, sorted. `tracked_files` keeps regular files only (gitinfo's `_REGULAR`, modes 100644 and 100755). So a tracked symlink `.md` is not a doc and is not scanned, and a cite whose target is a tracked symlink fails with `<path>: not a tracked file`.
  - Tree read (DC-8, owner answer F-3). Each doc and each target is read from the working tree, never at `HEAD`. The gate does not compare the working tree with the index. The equality of the working tree and the tree being committed comes from outside the gate:
    - from block 2, the git pre-commit hook refuses a commit while any tracked file has unstaged changes (plan "Later blocks", Block 2; spec edits E9, E10), for a commit it runs on: the hook installed and not bypassed;
    - from block 3, the Claude Code PreToolUse Bash gated commit refuses the same before any gate runs, for every agent commit, since the hook also refuses a `git commit` inside a compound command, or with a `GIT_INDEX_FILE` override (spec edits E10, E14; owner answers Q-r4-1 (a), Q-r4-2 (a)), and the bypass block refuses an agent's `--no-verify`;
    - in CI, the checkout is the pushed commit itself;
    - before block 2, the by-hand commit gate requires a clean tree (Process for this plan).

    A human's `--no-verify` and a repository without the git hooks are outside these conditions; there the gate reads the working tree as it is.

    So a doc and the target it cites can land in the same commit and pass that commit's own gate.
  - Categories. Each prints one `PASS cites.<cat>` when nothing in it failed, so a tree with no docs prints four `PASS` lines and is never empty:
    - `doc`: `FAIL cites.doc.<doc>: tracked but missing from the working tree` or `...: not UTF-8`.
    - `line`: `FAIL cites.line.<doc>:<n>: <token>: <problem>`.
    - `anchor`: `FAIL cites.anchor.<doc>:<n>: <token>: <problem>`.
    - `landed`: for each decision record whose `landed_in` holds a cite with `#`, the anchor is checked in its target: `FAIL cites.landed.<id>: <cite>: <problem>`. Spec §7.4: "its anchor is checked by `gate_cites`". The file part stays `gate_decisions`' check (Task 1c.1).
  - Failures: a missing config gives `FAIL cites.input` naming `/strict-delivery:init` (Review Focus 5). A `Store.load` `GateError` gives `FAIL cites.input`.
  - Line ids and reasons are escaped once, by `Result.render`, which applies `safe_text` to each text line. The gate does not escape them again.

**Input-domain dimensions:**
- argv: `--root` missing, not a repo, no config; `--json` first or later; unknown flag.
- Docs:
  - none tracked;
  - a tracked `.md` deleted in the working tree;
  - an untracked `.md` holding a broken cite (ignored);
  - a tracked `.MD`, which is not scanned (DC-6: `*.md` only);
  - not UTF-8.
- Each category's pass and fail.
- Decision records:
  - none;
  - `landed_in` absent or without an anchor;
  - an anchor present and missing;
  - a target untracked;
  - a record that does not load.
- Ordering: lines sorted by doc, then line.
- Tree read (DC-8, F-3; the gate reads the working tree):
  - a doc and its cited target both new and staged, with no commit: pass;
  - a target tracked in the index but deleted in the working tree: fail, `<path>: tracked but missing from the working tree`. The block-2 pre-commit hook refuses that commit anyway, since the deletion is an unstaged change;
  - a target with 3 lines staged and 9 in the working tree, cited at line 9: the gate passes, because it reads the working tree. The hook refuses the commit, and that refusal is tested in A's block-2 hook task, not here.
- Symlinks: a tracked symlink `.md` (not a doc, not scanned); a cite whose target is a tracked symlink (fail, `not a tracked file`); an untracked symlink `.md` (ignored).
- This repository's own docs: `python3 -m gates check cites` exits 0. The drafter's scan (rev 8, at 4aa05c9) simulated the splice: E1-E16 applied to the spec and plan, and the stream B and C sections inserted into the plan before "## Later blocks". A script following Task C2.1's `extract` rules (fences, code spans, backtick form, link form) over every tracked `*.md` of that tree found no cite, so the gate has nothing to fail there. The placeholder `path#anchor` is excluded by DC-5, and Task C2.1's examples are written as double-backtick spans or as code spans holding a space, which are not cites. A later edit that adds a cite-shaped example to a tracked doc must follow the same rule.

- [ ] **Step 1: Write the failing tests** (`tests/test_gate_cites.py`; `out, code = run(root, *args)` calls `gate_cites.main`):
  ```python
  def test_empty_repo_passes_every_category():
      for c in ["doc", "line", "anchor", "landed"]: assert "PASS cites." + c in out
      assert code == 0
  def test_broken_line_cite_fails():                 # docs/a.md line 2: `gates/x.py:9`, x.py has 3 lines
      assert "FAIL cites.line.docs/a.md:2: `gates/x.py:9`: gates/x.py: line 9 is past the end (3 lines)" in out and code == 1
  def test_broken_anchor_fails():                    # [s](b.md#nope) in docs/a.md line 1; docs/b.md tracked, holding "# b"
      assert "FAIL cites.anchor.docs/a.md:1: b.md#nope: docs/b.md: no heading with anchor #nope" in out and code == 1
  def test_untracked_doc_ignored():
      assert "PASS cites.line" in out and "PASS cites.anchor" in out
  def test_tracked_doc_deleted_in_worktree():
      assert "FAIL cites.doc.docs/a.md: tracked but missing from the working tree" in out
  def test_landed_in_anchor_checked():               # answered lasting decision, landed_in [".strict-delivery/playbooks/p.md#missing"]
      assert "FAIL cites.landed." + DEC_ID in out
  def test_missing_config_names_init():
      assert out.startswith("FAIL cites.input:") and "/strict-delivery:init" in out
  def test_doc_and_target_added_together_pass():     # DC-8: both written and staged, no commit yet; HEAD has neither
      assert "PASS cites.line" in out and code == 0
  def test_target_deleted_in_worktree_fails():       # gates/x.py tracked, then removed from the working tree only
      assert "gates/x.py: tracked but missing from the working tree" in out and code == 1
  def test_tracked_symlink_doc_not_scanned():        # docs/l.md tracked as a symlink (mode 120000) to notes.txt, which holds `gates/x.py:9`
      assert "PASS cites.line" in out and "docs/l.md" not in out and code == 0
  def test_cite_to_tracked_symlink_fails():          # docs/a.md cites `docs/l.md#x`; docs/l.md is a tracked symlink
      assert "docs/l.md: not a tracked file" in out and code == 1
  def test_this_repository_passes():                 # run on the checkout itself
      assert code == 0
  def test_json_output_shape():
      assert json.loads(out)
  ```
- [ ] **Step 2: Run; expect FAIL.**
- [ ] **Step 3: Implement `gates/gate_cites.py`.** Raise the request to stream A for the `check cites` registration.
- [ ] **Step 4: Run on both interpreters and every enabled gate; expect PASS.**
- [ ] **Step 5: Commit** `feat(gates): gate_cites`, then checkpoint.
- [ ] **Step 6: Enable** (after stream A's registration commit is on `main` and C has updated from `main`). Run `python3 -m gates check cites`; expect every line `PASS` and exit 0. From then on, every stream's commit gate includes `check cites`. If block 2 has merged into `main` by then, raise the second request to A, to add `cites` to `run_all`'s gate list; until A's commit is on `main`, every stream's commit gate runs `check cites` beside `run_all` (stream rules, "Cross-stream order"). **Block C2 end:** final review, verifier, then the pull-request flow (stream rules, "Merging each block"), checkpoint. Stream C is then done: its paths pass to A (DS-3).

---

## Later blocks (outline; each gets its own detailed plan section, input-domain dimensions and owner batch before it starts, split into sub-blocks of at most 3 tasks)

- **Block 2.** Planned in full in section "Block 2 (sub-blocks 2a, 2b, 2c)" above (owner answers 2026-11-01, "Block 2" below).
- **Programs block.** Planned in full in section "Programs block (sub-blocks P1, P2, P3, P4)" above (owner answers 2026-11-02, "Programs block" below).
- **Block 3.** Planned in full in section "Block 3: plugin packaging and Claude Code hooks (program streams `runtime`, `bash`, `tools`, `package`)" above (owner answers 2026-11-02, "Blocks 3-6" below).
- **Block 4.** Planned in full in section "Block 4 (streams `cfg4`, `rules4`, `init4`; sub-blocks 4a-4e)" above (owner answers 2026-11-02, "Blocks 3-6" below).
- **Block 5.** Planned in full in section "Block 5: context, docs and drift tooling (streams `context` and `docs`; sub-blocks 5a, 5b, 5c)" above (owner answers 2026-11-02, "Blocks 3-6" below).
- **Block 6.** Planned in full in section "Block 6 (streams `evidence`, `checkpoint`, `release`; sub-blocks 6E, 6K, 6R)" above (owner answers 2026-11-02, "Blocks 3-6" below).

---

## Owner answers (2026-10-31)

The owner answered the first batch on 2026-10-31. Each answer below is written into the tasks it affects. Every answer except OQ-2 is also edited into the main spec.

- OQ-1 (b): only `schema`, `framework_version` and `profile` are required in config; every key with a default may be omitted; keys whose reader has not landed are optional in `config/1` and become required in a later version with a migration (Tasks 1a.2, 1b.1; spec §6).
- OQ-2 (a): `ids` configures only the four prefixes (Tasks 1a.2, 1a.3).
- OQ-3 (b): an id's date must be a valid calendar date (Task 1a.3; spec §7.2).
- OQ-4 (c): new config key `base_branch`, default `main`; gates default `--base` to it and check against the merge base with it (Tasks 1a.2, 1a.3, 1c.1, 1c.2; spec §6, §7.2).
- OQ-5 (a): block 1 allows deleting a resolved finding only when an answered `merge-grant` names its `resolved_by` plan (Tasks 1b.3, 1c.2; spec §7.2).
- OQ-6 (c): `closed -> merged` is kept; only the cleanup step (programs block) may set `merged`; until then `merged` is unreachable and `closed` is final (Tasks 1a.3, 1b.3, 1c.2, 1d.2; spec §7.2).
- OQ-7 (b): a withdrawal writes `withdrawn {at, by, reason}` (Tasks 1b.2, 1d.1; spec §7.1, Appendix A).
- OQ-8 (a): merge grants carry structured `plan`, `program` and `stream` fields (Tasks 1b.2, 1d.1; spec §7.1, Appendix A).
- OQ-9 (a)+(i): `landed_in` allow-list `paths.playbooks`, `CLAUDE.md`, `paths.architecture`; block 1 checks the file only, and anchors come with `gate_cites` (Tasks 1b.2, 1c.1; spec §7.4).
- OQ-10 (a): config key `decisions.scan`, default globs `docs/**`, `CLAUDE.md`, `.strict-delivery/playbooks/**`, with the state directories excluded (Tasks 1a.2, 1c.1; spec §6, §7.1).
- OQ-11 (a)+(i): `asked_at` and `answered_at.at` are checked for shape only; `decide` refuses when `git config user.email` is unset (Tasks 1b.2, 1d.1; spec §7.1).
- OQ-12 (b): an optional `rule` field, written at `decide`, is the rule summary in `in-force.md` (Tasks 1b.2, 1c.3, 1d.1; spec §7.1, §7.4, Appendix A).
- OQ-13 (b): `overview/1` has only the sections block 1 can fill; the rest come in `overview/2` with a later migration (Task 1c.3; spec Appendix A).
- OQ-14 (a): `gate_schema` always checks config, a stated exception to the producer rule (Task 1b.1; spec Appendix A).
- OQ-15 (b): evidence may be a commit sha, a `<sha>:<path>`, or a plain tracked path outside the per-effort paths (Tasks 1b.3, 1d.2; spec §5).
- OQ-16 (a): unknown keys are refused in every schema (Tasks 1a.2, 1b.1 and every schema; spec Appendix A).
- OQ-17 (a): `gate_schema` skips an absent generated file (Tasks 1b.1, 1c.3; spec Appendix A).
- OQ-18 (b): the review-report scan stays in `gate_register`, keyed on the `review-report` schema line (Task 1c.2; spec §7.2).
- Second batch (owner, 2026-10-31, on the plan review): Q-plan-1 (a) `decision_classes.owner_only` merges as a union (Task 1a.2; spec §6); Q-plan-2 (a) the `closed -> merged` exception is in spec §7.2; Q-plan-3 (a) OQ-3, 5, 9, 11, 13 and 18 each have a spec sentence; Q-plan-4 (a) `pin.transcript` is `<sha>:<path>` only, type `sha-path` (Task 1b.3); Q-plan-5 (a) every plain path under `paths.findings` is refused as evidence (Task 1b.3; spec §5); Q-plan-6 (b) every block-1 test step carries its assertions as code. The drafter's calls I1-I9 are accepted and marked "(owner-approved call)" where the plan states them; I8 also makes spec §7.4 read "one table row per lasting decision".
- Third batch (owner, 2026-10-31, on the second plan review): Q-rev2-1 (a) `models.tiers.tier4` has no default; a project that uses top-tier roles sets it (Task 1a.2; spec §6); Q-rev2-2 (a) `landed_errors` matches the id as a whole token (Task 1b.2); Q-rev2-3 (b) `pin.transcript` sits under `<paths.plan_state>/<owner.plan>/mutations/` when the owner kind is `plan`, else under any plan's `mutations/` (Task 1b.3); the YAML subset has no floats, so `drift.estimate_factor` becomes `drift.estimate_factor_pct`, an integer percent, default 150 (Task 1a.2; spec §6, §9; programs design).
- Fourth batch (owner, 2026-10-31, on the seventh review): Q-decisions-1 (b) open and answered superseders count toward `fork.<id>`, withdrawn ones are ignored; a decision counts as superseded only once its superseder is answered; `ask` refuses a second superseder while an open or answered one exists (Tasks 1b.2, 1d.1; spec §7.1).
- Controller rulings on the third review (spec settles each): R-rev3-1 finding `owner` keys are declared in `finding.yml` with `required_when`/`absent_when` on `kind`, not hand-coded (spec §7.2); R-rev3-2 `ask` candidates are the union of per-topic, per-glob and per-word `find` hits (spec §7.4: `find` "on the new question's topics, paths and keywords"); test git calls are isolated from global and system config; line ids stated for `decisions.open-ref`/`scan` and `register.*`.

### Streams B and C (2026-10-31, 2026-11-01)


The owner answered every item of the first B/C batch with option (a) (ledger line of 2026-10-31, "Owner answers 2026-10-31 streams B/C"). Each answer is written into the tasks it names above.

- **DS-1** Block branches `block/sb1`, `block/sb2`, `block/sc1`, `block/sc2`, each from `main` and merging into `main`; worktrees at `../strict-delivery-worktrees/<stream>/<leaf>` (stream rules, "Branches and worktrees").
- **DS-2** A stream's open block branch follows `main` by a merge of `main` into it, as its own command, with no grant; never a rebase (stream rules, "Keeping up with `main`").
- **DS-3** When a stream's last block merges, its paths pass to A; P4 then adds its two roles to `tests/prose_check.py` itself (stream rules, "File ownership"; Stream B, "Consumed later by"; Tasks B2.3, C2.2 block ends).
- **DB-1** One prompt file per spec §10 role, stem equal to the role id (Task B1.1).
- **DB-2** Minimum tiers (model policy): tier1 `implementer_transcription`; tier2 `implementer`; tier3 `controller`, `program_controller`, `stream_controller`, `task_reviewer`, `final_reviewer`, `audit_reviewer`, `audit_verifier`, `investigator`; tier4 `final_verifier`, `exception_reviewer` (Tasks B1.2, B2.2).
- **DB-3** The forbidden list of Task B1.1, model names and the superpowers default save path included (Tasks B1.1, B2.3).
- **DB-4** The template's intro sentence and label style, generalised (Task B1.1).
- **DB-5** `exception_reviewer` argues against one proposed exception to a rule (a draft `rule-override` decision or a deviation a project playbook allows), reading only the proposal and its evidence (Task B1.2).
- **DB-6** `SD-R1`-`SD-R17` in spec §8 order; `SD-R18` the bypass block, fixed; `SD-R19` the stack-neutral production-path judgment rule (Task B2.1).
- **DB-7** `profiles` and `enforced by` derived from spec §12 and the gates spec §9, §10 and §13a name, else `judgment`; the derived table goes to the owner as one table at B2.1's review (Task B2.1).
- **DB-8** A plain-text `source` column, never a path cite (Task B2.1).
- **DB-9** An optional `overrides` field (pattern `SD-R[1-9][0-9]*`, class `rule-override` only) in `decision/2`, with a migration, before block 3's SessionStart reads it. Spec and plan edits E1-E3, E6, E7; the schema task is stream A's (Task B2.1 names the form).
- **DC-1** The seven-row source table (Tasks C1.1, C1.2).
- **DC-2** `test_one` is never proposed (Task C1.1).
- **DC-3** Detection reads `root` only (Tasks C1.1, C1.2).
- **DC-4** Always `npm run <name>` (Task C1.1).
- **DC-5** Cites are backtick spans and inline link targets outside fences; placeholders excluded (Tasks C2.1, C2.2).
- **DC-6** Every tracked `*.md` (Task C2.2).
- **DC-7** GitHub's slug for ATX headings, `-1`, `-2` for repeats (Task C2.1).
- **DC-8** Cites resolve in the tree being committed, not at `HEAD`. The gate reads the working tree of tracked files, and F-3 and F-r3-1 make that the tree being committed under the conditions of E5 and E10. Spec §9 edit E5 (Stream C intro, Task C2.2).

Second batch (owner, 2026-10-31, on the streams review; ledger line "Owner answers 2026-10-31 streams review"):

- **F-1 (a)** A change that is exactly a registered schema migration of the base row is not an immutability change; `base_errors` migrates the base row before comparing (block 2, stream A). Spec §7.2 edit E8; plan edit E6.
- **F-2 (a)** `decisions.validate` refuses an `overrides` naming a fixed rule; the fixed set is the constant `FIXED_RULES` in A's code, checked against the `fixed` column of `playbook/rules.md` by a stream-B test (Task B2.1; stream rules, "Cross-stream order"; plan edits E6, E7; spec edit E1).
- **F-3 (c)** The block-2 pre-commit hook refuses a commit while tracked files have unstaged changes, so the working tree is the tree being committed for every gate. E5 keeps the working tree (Task C2.2; plan edit E9; spec edit E10).

Third batch (owner, 2026-10-31, on review 3; ledger line "Owner answer 2026-10-31 F-r3-1 (a)"):

- **F-r3-1 (a)** Block 3's Claude Code commit hook (PreToolUse Bash, the gated commit) also refuses a commit while tracked files have unstaged changes. E5 and E10 state where the guarantee holds: agent commits through the Claude Code hook; commits outside Claude when the git hooks are installed and not bypassed; CI checks the commit itself. Plan edit E14 names the hook check and its test. F-r3-2 is plan edits E15 and E16; F-r3-3 is E6 and the stream rules' "Cross-stream order"; F-r3-4 is Tasks B1.3, B2.2 and B2.3.
- Fourth batch (owner, 2026-11-01): **Q-r4-1 (a)** Block 3's Claude Code commit hook refuses `git commit` inside a compound command (a commit runs as its own command); **Q-r4-2 (a)** it also refuses an agent `git commit` with a `GIT_INDEX_FILE` override (gates still inherit `GIT_INDEX_FILE` inside git's own hooks, Q-1a2r-5). Spec edits E5, E10; plan edit E14; Task C2.2.
- Fifth batch (owner, 2026-11-01): **Q-r5-1 (b)** `slugify` uses a frozen table, not `unicodedata`: `gates/lib/slug_table.py` (owned by stream C) holds the code-point ranges that github-slugger 2.0.0's regex removes, generated once from that package's `regex.js`, and `slugify` looks them up with `bisect`. Task C2.1 and the stream rules' ownership table.
- Sixth batch (owner, 2026-11-01): **Q-r6-1 (b)** `slugify` lowercases with a frozen case table, not `str.lower()`: `gates/lib/case_table.py` (owned by stream C) holds the Unicode 13.0.0 lowercase mappings and the `Cased` and `Case_Ignorable` ranges, generated once from the Unicode Character Database 13.0.0 in the same Step 3 as the strip table, and `lowercase` applies the Final_Sigma rule from those ranges, so every Python 3.9+ gives the same anchor. Accepted cost: where a case mapping changed after Unicode 13.0.0 the anchor can differ from GitHub's current Node; Task C2.1 names the known members (U+A7CB, U+A7DC, the Final_Sigma context). Task C2.1 and the stream rules' ownership table.

F-4 to F-7 needed no ruling: F-4 is plan edits E11-E13; F-5 is Task C1.1; F-6 is Tasks C1.1, C1.2 and C2.2; F-7 is the stream rules' "Cross-stream order" and Task C2.2.

Decision needed: none. The answers settle every item of the batch. Two details are left, by the plan's own process, to the detailed section and owner batch of the block that owns them, not to streams B or C: which `decisions` command writes `overrides` (stream A, block 2), and the owner's check of DB-7's derived table (B2.1's review).

The spec and plan edits E1-E16 named above are applied in the commit that added the stream B and C sections; each now stands in its file:

| Edit | Where | File |
|---|---|---|
| E1 | (DB-9, F-2). Spec §7.1, end of "Row fields" | `2026-10-31-strict-delivery-framework-design.md` |
| E2 | (DB-9). Spec §8, override rule | `2026-10-31-strict-delivery-framework-design.md` |
| E3 | (DB-9). Spec Appendix A, decision schema sentence | `2026-10-31-strict-delivery-framework-design.md` |
| E4 | (DB-9). Spec §17, block 2 (keeps the spec's block list in line with E6) | `2026-10-31-strict-delivery-framework-design.md` |
| E5 | (DC-8, F-3, F-r3-1). Spec §9, `gate_cites` | `2026-10-31-strict-delivery-framework-design.md` |
| E6 | (DB-9, F-1, F-2). Plan "Later blocks", Block 2: the `decision/2` migration task | `2026-10-31-strict-delivery-framework.md` |
| E7 | (DB-9, F-2). Plan "Later blocks", Block 3: the reader of the field | `2026-10-31-strict-delivery-framework.md` |
| E8 | (F-1). Spec §7.2, the immutability rule | `2026-10-31-strict-delivery-framework-design.md` |
| E9 | (F-3). Plan "Later blocks", Block 2: the pre-commit hook rule | `2026-10-31-strict-delivery-framework.md` |
| E10 | (F-3, F-r3-1). Spec §13, the clean-tree refusal | `2026-10-31-strict-delivery-framework-design.md` |
| E11 | (F-4). Plan "Later blocks", Block 3: what stream B delivers | `2026-10-31-strict-delivery-framework.md` |
| E12 | (F-4). Plan "Later blocks", Block 4: what stream C delivers to `init` | `2026-10-31-strict-delivery-framework.md` |
| E13 | (F-4). Plan "Later blocks", Block 5: `gate_cites` | `2026-10-31-strict-delivery-framework.md` |
| E14 | (F-r3-1). Plan "Later blocks", Block 3: the clean-tree refusal in the gated commit | `2026-10-31-strict-delivery-framework.md` |
| E15 | (F-r3-2). Plan Global Constraints, the spec §7.2 quote | `2026-10-31-strict-delivery-framework.md` |
| E16 | (F-r3-2). Plan Task 1a.3, `base_errors`: the exceptions of spec §7.2 | `2026-10-31-strict-delivery-framework.md` |

### Block 2 (2026-11-01)

The detailed Block 2 section above was reviewed three times until clean. Owner answers, all option (a) as written in the review batch: Q-B2plan-2, Q-B2plan-4 (a blob id per cite), Q-B2plan-5, Q-B2plan-6 (Task 2c.1 runs), Q-B2plan-7, Q-B2plan-8, Q-B2plan-11, Q-B2plan-12, Q-B2plan-13, Q-B2plan-16 (roles `plan_writer` and `plan_reviewer`, prompt prose by stream B on request), Q-B2plan-17, Q-B2plan-18, Q-B2plan-19, Q-B2plan-20, Q-B2plan-22, Q-B2plan-23, Q-B2plan-24.

- Q-B2plan-21 (model policy): the top tier defaults to the `tier3` model for now, because of high parallelism; it stays configurable so a project can set a higher, costlier `tier4`. Read as: `tier4` unset by default, `models.top_tier_fallback` defaulting to `tier3`, so `final_verifier` and `exception_reviewer` run at `tier3` unless `tier4` is set. This amends Q-B2plan-17 (a) for the unset case only (Task 2c.3 states it); the rule that one model may not name two tiers stands. This repository: `tier4` unset, `top_tier_roles: [final_verifier, exception_reviewer]`.
- Agent tree (owner, 2026-11-01): Q-H1 keep `program_controller`; Q-H2 per-role child caps `limits.max_children.<role>`; Q-H3 a sub-controller may dispatch a sub-controller when the stream controller judges it better; Q-H4 a worker's dispatch is refused; Q-H5 (a) depth-aware tree. Measured Claude Code limits are in the Block 2 section's opening facts. The spec edits these need land with the programs block's detailed section.
- Init (block 4) offers the subagent depth and concurrency limits and writes them into the project's `.claude/settings.json`; this repository sets depth 5 and concurrency 30.

### Programs block (2026-11-02)

The detailed Programs block section above was reviewed seven times until clean. The owner signed it off on 2026-11-02 ("recommended for all"): Q-Pplan-1, Q-Pplan-2, Q-Pplan-4, Q-Pplan-5, Q-Pplan-6, Q-Pplan-8, Q-Pplan-9, Q-Pplan-11, Q-Pplan-12 and Q-Pplan-14, all option (a):

- **Q-Pplan-1 (a)** every ledger line whose first token is `CHECKPOINT`, `Ruling`, `Request`, `UPDATE` or `MERGED` matches its form exactly; other lines are free prose; Task P1.3's migration rewrites this repository's nonconforming keyword lines, keeping their text (Tasks P1.2, P1.3).
- **Q-Pplan-2 (a)** `gate_checkpoint` declares no kinds while stream B or C is live; the `handoff` and `ledger` producer declaration is the scheduled one-line commit after the last of them merges (Task P1.3).
- **Q-Pplan-4 (a)** request transitions `open -> accepted | disputed | withdrawn`, `accepted -> done | withdrawn`, `disputed -> accepted | withdrawn` with a `request-dispute` decision; `done` and `withdrawn` final; no request file deleted while the program is live (Tasks P2.1, P2.2).
- **Q-Pplan-5 (a)** a sync merges `main` into each stream branch behind it, never a rebase (Tasks P2.3, P4.3).
- **Q-Pplan-6 (a)** stream B writes the `program_controller` and `stream_controller` prompt blocks and their `prose_check.py` rows on A's request; A writes them only once B's paths are A's (DS-3) (Task P4.3; stream rules ownership table).
- **Q-Pplan-8 (a)** the session reads a blocked agent's question from the handoff committed at the tip of the stream branch (Task P4.1).
- **Q-Pplan-9 (a)** the cleanup is a follow-up pull request per finished plan (`cleanup/<plan>`), made by hand; `merged` stays unreachable and `closed` final in v0.1. This moves out of the programs block the step OQ-6 (c) placed in it ("only the cleanup step (programs block) may set `merged`") (Tasks P3.2, P3.3).
- **Q-Pplan-11 (a)** the session keeps a dedicated integration worktree at `<worktrees>/<program>/integration`, created with `git worktree add -b`, and never switches the main checkout (Tasks P2.2, P4.1).
- **Q-Pplan-12 (a)** global records written on the integration branch reach `main` by one records pull request at program close (`<program>/records`) (Tasks P2.1, P2.3).
- **Q-Pplan-14 (a)** `merge.mode` is folded into Block 2's `config/2` (Task 2c.2); Task P3.1 only reads it.
- Controller rulings that replaced questions: Q-Pplan-7 (live programs from local `<p>/integration` branches) and Q-Pplan-10 (`estimate` and `used` as integers); Q-Pplan-3 and Q-Pplan-13 are settled by Q-15 (a).

Owner answers and directives on the agent tree and the pull-request flow (2026-11-01, 2026-11-02), each written into the section above and into the specs:

- **Q-H1..Q-H5** as recorded in "Block 2 (2026-11-01)": keep `program_controller`; per-role child caps `limits.max_children.<role>`; a sub-controller may dispatch a sub-controller; a worker's dispatch is refused; (a) the depth-aware tree, the session acting as program controller by default.
- **Protected main (directive, 2026-11-01):** nothing merges or pushes to `main` directly, in this repository and every target repository; work branches are pushed at checkpoints; a finished stream opens its own pull request to `main`.
- **Q-M1:** the PR merge mode is a per-project setting, `merge.mode`: `host` (the owner merges on the host) or `controller` (the owner approves in chat and the controller runs `gh pr merge`); this repository uses `controller`.
- **Q-M4 (a):** each finished stream opens its own PR to `main`; the integration branch holds only program records and combined testing and never merges into `main`.
- **Q-15 (a) (2026-11-01):** merge approvals are not decision records, from block 1c on. In `controller` mode the owner approves in chat naming the PR and its head sha and the controller runs `gh pr merge <n> --merge --match-head-commit <sha>`; in `host` mode the owner's host merge is the approval. The plan's ledger `MERGED` line records the PR, head sha, merge commit, `merged_by`, time, `final` and the approval (the owner's words verbatim with the PR and sha they named, or `host`).
- **Q-16 (a):** block 3's hook refuses any agent Edit or Write under `paths.decisions`; only the `decisions` tool writes there, and it refuses answers from agents.
- **Owner steps:** set this repository's host merge methods to merge commits only before block P3 (branch protection with pull requests required and admins enforced is already on).

Spec edits SE-1..SE-19, applied to both specs with this section (the edit ids the section above cites):

| Edit | Answer | Where | Change |
|---|---|---|---|
| SE-1 | Q-H5 (a) | Programs design §4 table (levels 1, 1a, 2, 3+) | The session acts as program controller by default; `stream_controller` at level 1, sub-controllers at 2, workers at 3; a separate `program_controller` (level 1, streams at 2) only when the configured depth allows. Programs design §4 currently: "1a \| program_controller \| agent dispatched by the program session". |
| SE-2 | Q-H5 (a) | Programs design §4 "Dispatch" bullet; main spec §10 "Lifecycle" | Now: "only the program session dispatches a program_controller; only a program_controller dispatches a stream_controller" (both specs). Becomes: the session or a `program_controller` dispatches a `stream_controller`; only the session dispatches a `program_controller`. |
| SE-3 | Q-H3 | Main spec §10 "Lifecycle"; programs design §4.1 | Now: "stream controllers and their sub-controllers dispatch the workers". Add: a sub-controller may dispatch a sub-controller when the stream agent judges it better, within the depth limit. |
| SE-4 | Q-H4 | Main spec §10 (dispatch grammar paragraph) | Add: `gate_dispatch` refuses any dispatch whose dispatcher is a worker role. |
| SE-5 | Q-H2 | Main spec §6 | The `limits` key (`max_children.<role>`, `max_depth`, `max_concurrent`), as block 2 Task 2c.2 already lists; not repeated here. |
| SE-6 | measured facts | Programs design §4.2; main spec §4 (init) | Now: "two levels probed; every level carries the dispatch tool". Becomes the measured facts (depth: Agent tool at levels 1-2 by default, 1-N with `CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH=N`; concurrency: launches past 20 refused by default, raised by `CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS`). Main spec §4: `init` writes both into the project `.claude/settings.json` `env` block. |
| SE-7 | Q-H5 (a) | Programs design §4.2, §4.3, §4.4, §5 step 2, §10 session kinds, §11; main spec §7.2 and programs design §8.1 (id minting), §6 (request writer) | Every "program controller" duty reads "the program controller (the session by default, Q-H5)". §4.4 "At every level from 1a down" and §4.2 "refreshes itself ... only at a sync" add that a session acting as program controller does not refresh and stays lean by re-reading the status pages (its existing §4.4 rule). §5 step 2 "The program session dispatches the program controller" becomes conditional on depth. |
| SE-8 | Q-Pplan answers and rulings | Appendix A ledger row (Q-15 (a): the `MERGED` line); main spec §6 and §17 block 2 (Q-Pplan-14, only under (a)); programs design §6 (Q-Pplan-4: request transitions); programs design §10 and main spec §8 (Q-Pplan-5); Appendix A ledger row (Q-Pplan-1); main spec §5 and §7.2 (Q-Pplan-9) | One sentence each, stating the answer. |
| SE-9 | schema vocabulary | Main spec Appendix A, "Where the line sits" | Add that a schema's `files` glob may hold `/`-separated segments and that a front-matter kind's schema checks the front matter only (Task P1.1). |
| SE-10 | owner directive (protected base) | Main spec §8 merge rule; §11 bullet on merges; §13 | Now (§8): "Merge only on all-green under an owner grant; the merge runs as its own command. The owner grants merges into a program's integration branch and into main." Becomes: the base branch is protected; nothing is pushed or merged to it directly; every change reaches it by a pull request merged by merge commit on the owner's approval (Q-15 (a): in chat, with the controller's `gh pr merge --match-head-commit`, or by the owner's own merge on the host), recorded as a `MERGED` ledger line; work branches are pushed at checkpoints. §13: the git pre-push hook refuses a push to the base branch, and block 3's Bash hook refuses an agent's push or merge to it. |
| SE-11 | Q-M4 (a) | Programs design §5 steps 2 and 4; §4 table (program_controller and stream_controller "Never" cells); §7.2 program folder row; main spec §11 | Now (§5.4): "Each completed block merges into the integration branch on the owner's grant ... The integration branch merges to main at milestones the program plan names, and at close". Now (§5.2): "Each stream branch starts from the integration branch." Becomes: stream branches start from the base branch; blocks accumulate on the stream branch; a finished stream opens its own PR to the base branch; the integration branch holds only program records and combined testing and never merges into the base branch. The §4 "Never" cells change from merging into integration to opening, not merging, the stream PR. |
| SE-12 | Q-M4 (a) | Programs design §12 `gate_streams` and `gate_drift`; main spec §9 `gate_drift` | Now (§12): "The base for `base..HEAD` is the integration branch, or the stream branch named as `stacked_on`"; "a stream branch behind `<program>/integration`, or an integration branch behind main, fails until a sync". Becomes: the base is the base branch (or `stacked_on`); a stream branch behind the base branch, or an integration branch behind it, fails until a sync; a merge of integration into a stream branch fails. |
| SE-13 | Q-M1 | Main spec §6; §4 (init asks; `doctor` reports) | New key `merge.mode` (`host` \| `controller`, default `host`) in `config/2` (owner answer Q-Pplan-14 (a)): who presses merge on an approved PR. |
| SE-14 | Q-M4 (a), the merge-method ruling, Q-15 (a) | Main spec §7.2 deletion proof and no-delete paragraph; programs design §8.1 | Now (§7.2): the cleanup may delete a resolved finding "only when that plan's merge grant is answered and its merge commit exists on the target branch"; "Until `gate_cleanup` lands ..., `gate_register` lets a branch delete a resolved finding only when an answered `merge-grant` names its `resolved_by` plan". Becomes: only when the plan's ledger records its final PR merge (`MERGED ... final=yes`) and that merge commit is on the target branch's first-parent history with the recorded head as its second parent; the cleanup is its own PR (Q-Pplan-9). |
| SE-15 | owner directive | Main spec §4 (init) | `init` offers to configure host branch protection on the base branch (PR required, merge-commit method); `doctor` reports it. |
| SE-17 | owner directive, review 3 F-Pp3-5, review 4 F-Pp4-4 | Main spec §4 (CI and the PreToolUse Bash list); programs design §11 | §4: CI also runs, on pull requests at the head sha, `check streams --branch` and, for cleanup heads, `check cleanup`; the Bash list gains the refusals of an agent's push or merge to the base branch, a commit or merge while it is checked out, and `gh pr merge` without `--merge` and `--match-head-commit`, or in `host` mode, plus any agent merge through `gh api` (the REST pull-request merge endpoint, GraphQL `mergePullRequest`) and any agent `git push` to the base branch in any refspec form (review 5 F-Pp5-3). §11: status `merged` means the stream's PR has merged into the base branch. |
| SE-18 | Q-15 (a) | Main spec §7.1 (grants: "Grants use class `merge-grant` and name the plan; a grant inside a program also names the program and the stream, as the fields `plan`, `program` and `stream`"), §7.2 (above), §8 (merge rule), Appendix A (decision schema sentence on grant fields); programs design §5 step 4 ("on the owner's grant (a merge grant names program, stream and plan)"), §4.1 ("The owner grants only merges into the integration branch and into main"), §8.1 | A PR merge approval is not a decision record: in `controller` mode the owner approves in chat naming the PR and its head sha, in `host` mode the owner's host merge is the approval, and the plan's ledger `MERGED` line records who, when, PR, head and merge commit. `merge-grant` stays an owner-only class for approvals that are not PR merges, if any remain; the decision schema keeps `plan`, `program` and `stream` for records already written (none in this repository use them for a PR). |
| SE-19 | Q-16 (a) | Main spec §4 (PreToolUse Edit/Write: "records nothing, blocks nothing"); §7.1 ("A hand edit of a record cannot be told apart from a tool write; it is valid when the schema holds") | The Edit/Write hook refuses any agent Edit or Write under `paths.decisions`; only the `decisions` tool writes decision records, and it refuses answers and withdrawals from agents. A human's hand edit remains valid when the schema holds. |
| SE-16 | Q-M4 (a), Q-Pplan-12 | Programs design §10 sync; §7.1 / §12 global-record writer | The sync's steps under Q-M4 (a) (merge main into integration, update stream branches from main, combined testing on integration); how global records written on integration reach the base branch (Q-Pplan-12). |

### Blocks 3-6 (2026-11-02)

The detailed sections for blocks 3, 4, 5 and 6 above were reviewed until clean. The owner answered their batches on 2026-11-02 ("recommended for all"); each answer is written into the tasks above, which state only the chosen option:

- **Q-B3plan-1 (a)** the Claude Code Bash hook always runs its own refusals, and runs `githook`'s gates itself only when `githooks status` reports the git hook missing, foreign or stale; otherwise git's hook runs them during the commit or push (Tasks 3b.2, 3b.3; spec edit SE-B3-6).
- **Q-B3plan-3 (a)** while the base branch is checked out, an agent may run exactly `git pull --ff-only` (optionally naming the base branch's remote and the base branch) and `git merge --ff-only <remote>/<base>`, `<remote>` being `branch.<base>.remote`; every other local base update is refused (Task 3b.3; SE-B3-2).
- **Q-B3plan-5 (a)** `plugin.json` depends on `{"name": "superpowers", "marketplace": "claude-plugins-official"}`, allowed in `marketplace.json`'s `allowCrossMarketplaceDependenciesOn` (Task 3d.1).
- **Q-B3plan-6 (b)** the Bash hook refuses `decisions decide` and `decisions withdraw` from every subagent (a call with `agent_id`) and allows the main session, which records the owner's exact words (Task 3b.2; SE-B3-2, SE-B3-7).
- **SE-B3-5** approved by the owner on 2026-11-02 (Q-SE-1 (a)): each `hooks.json` entry is one POSIX sh line, `cd "${CLAUDE_PLUGIN_ROOT}" && exec python3 -m gates hook <Event>` (ruling (3a), Task 3a.2).
- **Q-B4plan-1 (a)** `init` creates `.claude/settings.json` when absent and never rewrites an existing one: equal values pass, anything else is a conflict naming the JSON members to add by hand (Task 4d.1).
- **Q-B4plan-2 (a)** with a GitHub `origin` that `gh` cannot read, `doctor.protection` fails `cannot read <slug>: <reason>`; with no GitHub remote it is not checked (Task 4d.3; spec §4 edit).
- **Q-B4plan-3 (a)** when the base branch has any protection, `init` changes nothing on the host and reports each wanted setting that is missing; it sets protection only on an unprotected branch and changes merge methods only when they differ (Task 4d.2).
- **Q-B4plan-4 (a)** a profile has `defaults` (set directly; init's default) and `policy` (changed only under `overrides`); `limits.*` may also be overridden; the authorising decision is answered, in force and of the new default owner-only class `profile-override`; all three profiles default `top_tier_roles` to `[final_verifier, exception_reviewer]` (Tasks 4a.2, 4a.3, 4b.1; SE-B4-2).
- **Q-B4plan-5 (a)** the migration rewrites exact repo-relative occurrences of moved paths at path boundaries in tracked UTF-8 text files, and lists every other mention of a moved file's base name as a note (Task 4d.2).
- **Q-B4plan-6 (a)** framework role defaults stay code constants (`dispatch.ROLES`, `MIN_TIERS`), the same in every profile; config `roles` only adds project roles (prompt, minimum tier); budget caps live in `budgets`; the brief and finding-state fields are not read in v0.1 (Tasks 4a.3, 4b.2; SE-B4-3).
- **Q-B4plan-7 (a)** this repository keeps its own matrix workflow; its adoption runs `upgrade --ci no`, and `doctor.extras` names the workflow as a project workflow (Task 4e.2; SE-B4-7).
- **SE-B4-6** approved by the owner on 2026-11-02 (Q-SE-2 (a)): the protection `init` offers requires pull requests for everyone including administrators (`enforce_admins: true`), and `doctor` checks it (Tasks 4d.2, 4d.3).
- **Q-B5plan-2 (a)** `gate_drift` checks the host only with `--host`, which then requires a working `gh` and fails `drift.host` otherwise; the sync passes `--host` where the remote is GitHub (Tasks 5c.1, 5c.2; S5-4).
- **Q-B5plan-3 (a)** stream branches are kept until the program closes; a `merged` or `closed` status row whose branch is gone fails `drift.merged` (Task 5c.1).
- **Q-B5plan-4 (a)** the context reads of a role that neither dispatches nor commits are printed, not gated (Task 5a.3; S5-1's last sentence).
- **Q-B5plan-5 (b)** `receipt` is not a produced kind: `gate_schema` never reads receipts, and `gate_context` validates the receipt file it reads and fails closed on a bad one (Tasks 5a.2, 5a.3; S5-8).
- **Q-B6plan-1 (a)** under standard `gate_evidence` checks the pinned findings a branch adds or changes against the merge base with `base_branch`; under strict, every pinned finding in the tree (Tasks 6E.2, 6R.1; SE6-4).
- **Q-B6plan-2 (d)** `gate_checkpoint` counts a block's tasks both from its ledger's `CHECKPOINT` lines and from its plan's task headings, failing when either is over `block.max_tasks` (Tasks 6K.1, 6K.2; SE6-5).
- **Q-B6plan-3 (a)** `escape_cost` is folded into Block 2's `config/2` (Task 2c.2); Task 6E.3 only reads it.
- **Q-B6plan-4 (b)** the review package's `PIN-COMMAND` and the transcript's three commands must equal each other; the re-run uses the command rendered from the current config (Tasks 6E.1, 6E.2).
- **Q-B6plan-5 (a)** the last `CHECKPOINT` line must read `gates=PASS` with `passed == total` (Tasks 6K.1, 6K.2; SE6-7).
- **Q-B6plan-6 (a)** the release creates the tag `v0.1.0` only (Tasks 6R.2, 6R.3).

Answers on earlier blocks, given with the same batch:

- **F-docs-11 (c)** the former Task 1c.0 is its own sub-block, 1c0, as Task 1c0.1 (docs review 2, F-docs2-3), with its own pull request (branch `block/b1c`); block 1c keeps Tasks 1c.1-1c.3 on branch `block/b1c1`.
- **Q-C2fin-1 (a)** Task 1c0.1 also registers `cites` -> `gates.gate_cites` in the `check` dispatcher with a lazy import (stream C's request R-20261102-bn3p), so stream C can enable `check cites` before its block end.
- **Q-B1v-2 (a)** the `top_tier_roles` setting decides which roles may use the top tier: the programs design reads "the roles in `top_tier_roles`, by default the final verifier and the exception reviewer".
- **Q-Pplan-14 (a)** with **Q-B6plan-3 (a)**: Task 2c.2's `config/2` carries `merge` (`mode` `host` | `controller`, default `host`) and the optional `escape_cost`.

Spec edits applied with this section (each as its draft states it, for the chosen options only): SE-B3-1..SE-B3-7; SE-B4-1..SE-B4-7 and the Q-B4plan-2 (a) edit of spec §4's `doctor` protection line (the Q-B4plan-1 (b) edit does not apply); S5-1..S5-8 (S5-4 and S5-8 as answered); SE6-1..SE6-7 (SE6-5 under Q-B6plan-2 (d), SE6-7 under Q-B6plan-5 (a)); and the Q-B1v-2 (a) wording in the programs design. The main spec's §7.2 deletion proof by the plan's final `MERGED` line starts with the programs block, where `MERGED` lines begin (docs review F-docs-15).

Owner directive given later the same day:

- **Q-PL-1 (a) (2026-11-02)** everything in a spec and its plan is planned in full before code; no outline-only block may start implementation. The last planning step is a parallelism and stream breakdown plan (`<paths.plan_state>/<plan>/breakdown.yml`, kind `breakdown/1`: streams with owned paths, tasks per stream, dependency edges task -> task, unblock conditions, parallel groups within the concurrency limit, the assumed concurrency and depth), and streams run as they unblock. Written into main spec section 8, section 5 and Appendix A, programs design section 5 step 1 and section 7.2, Task P2.2 (`program create` refuses a plan with an outline-only block or no valid breakdown; `breakdown.py`, `schemas/breakdown.yml`), and a cross-block request to stream B for `playbook/sessions.md` (Task B2.2).
