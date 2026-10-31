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
- Uniqueness (spec §7.2): "no id appears twice across the tree, and a pull request's ids are checked against the base branch too (config `base_branch`, section 6; deletions and immutability are checked against the merge base with it); a resolved record is immutable (a change is a new decision with `supersedes`), except that a finding's status moves from `closed` to `merged`, set only by the cleanup step (owner answer 2026-10-31); a decision's `landed_in` is never a spec."
- Whole-token match (used in Tasks 1b.2, 1c.1 and 1c.2): an id occurs in a text as a whole token when the character before it and the character after it are each either outside `[0-9A-Za-z_-]` or the start or end of the text. So with prefix `F`, `XF-20261031-k3f9` and `F-20261031-k3f9a` hold no finding id (owner-approved call, I6).
- Names (owner-approved call, I7): the `paths` key names, the schema-file vocabulary of Task 1b.1, and the file and function names in this plan are the plan's choice under design §17 ("File and function names inside `gates/`").
- Answers (spec §7.1): "there is no global owner setting. Answers and withdrawals come only from that human"; "Each answer records the git identity (`git config user.email`) as `answered_at.by`." No config key names an owner. The PreToolUse Bash refusal of `decisions decide` and `decisions withdraw` from agents lands in block 3; until then the controller never runs either command; the human runs them with the `!` prefix.
- Evidence (spec §5): cites of per-effort files use "the form `<sha>:<path>`, resolved with `git cat-file` (and required to name a commit in the repository), never a file at HEAD."
- Base branch (owner OQ-4): config `base_branch`, default `main`; gates default `--base` to it, check deletions and immutability against the merge base with it, and check id collisions against its tip.
- Unknown keys (owner OQ-16): every schema refuses keys it does not declare.
- Generated files (spec §5): "Ignored, never committed: generated files (state indexes, `in-force.md`, `INDEX.md`)".
- Gate contract (spec §13): "`check(args) -> Result`; prints `PASS id` or `FAIL id: reason` lines; `--json`; exits 0 only when at least one line exists and every line passes; a missing input fails (`<gate>.input`), an empty run fails (`<gate>.empty`); `--root` points at another tree."
- Registers ship empty. No lap-timer decisions, findings, claims, decision numbers or state as fixtures; the repository is public, so tests build synthetic fixtures in temp directories.
- Every commit carries `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Test command, every task, both interpreters (strict profile): `/usr/bin/python3 -m unittest discover -s tests -t . -v` (3.9.6) and `python3.13 -m unittest discover -s tests -t . -v` (Homebrew `/opt/homebrew/bin/python3.13`). Both pass before every commit, and the tree is clean after it.

## Process for this plan

- Bootstrap (spec §16): no gates existed when block 1a started; judgment rules apply by hand and the block-1a report says so. "Each gate is enabled on this repository as soon as it lands": `check schema` from Task 1b.1, `check decisions` from Task 1c.1, `check register` from Task 1c.2. From each enabling task on, the commit gate is the test command on both interpreters plus every enabled `python3 -m gates check <gate>` exiting 0, with a clean tree (`git status --porcelain --untracked-files=all` empty). `run_all` replaces this list in block 2.
- Blocks. Spec §17 block 1 is split under the strict cap of 3 tasks per block into sub-blocks **1a** (Tasks 1a.1-1a.3), **1b** (1b.1-1b.3), **1c** (1c.1-1c.3) and **1d** (1d.1-1d.2), each on its own branch (`block/b1a` ... `block/b1d`). Under the strict profile each block ends with a final review (opus), a top-tier final verifier and an owner merge grant, then the merge as its own command, then the checkpoint. Grants for 1a-1c are given in chat and ledgered verbatim (no decision tool exists yet). From block 1d's end, the controller records the grant with `decisions ask --class merge-grant`, and the human answers it with `! python3 -m gates decisions decide ...`.
- Continuation (spec §8, design §4.4) replaces stopping for `/clear`: at a checkpoint, at 80 % of its token or time budget, or at a usage-limit stop, the controller writes its handoff and returns `status: DONE` with `next:` (or `BLOCKED: budget`); its dispatcher at once dispatches a fresh controller with a continue prompt built from the handoff and ledger. One block per agent context stays. Nothing continues from inherited memory.
- Checkpoint after every task: append one line to `.strict-delivery/state/plans/2026-10-31-strict-delivery-framework/ledger.md`:
  `CHECKPOINT <block> <task> head=<short sha> tests=<passed>/<total> gates=<PASS|n/a> next=<task id>`
  and rewrite `handoff.md` beside it. Its front matter carries `schema: handoff/1` and the fields spec §9 lists for `gate_checkpoint` (plan, spec, branch, head, base, ledger, resume line, block, next task, findings in flight, open decisions, rulings, grant, live subagents). The resume line reads:
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
  - `config.load(root: str) -> dict`: deep merge of the file over `DEFAULTS` (a mapping merges key by key; `decision_classes.owner_only` merges as a union: the file's slugs are added to the default list, and a project cannot drop a default (owner Q-plan-1, spec §6); any other value replaces), then the key checks (OQ-1: only `schema`, `framework_version` and `profile` must be in the file; every key with a default may be omitted; OQ-16: a top-level key not in `CONFIG_KEYS` is refused with `GateError` naming it; `models`, `models.tiers` and `drift`, when present, are mappings; each `models.tiers` value present is a non-empty `str`, the four `ids` prefixes are distinct (controller ruling R-rev5-1), and `drift.estimate_factor_pct` is an `int` (not `bool`) of at least 1, else `GateError` naming the key). `CONFIG_KEYS` is the spec §6 key set plus `schema`: `schema`, `framework_version`, `profile`, `commands`, `paths`, `ids`, `models`, `roles`, `top_tier_roles`, `top_tier_fallback`, `decision_classes`, `block`, `rulings`, `dispatch`, `budgets`, `drift`, `overrides`, `base_branch`, `decisions`. Always: `framework_version` a `str`; `profile` one of `light`, `standard`, `strict`; each `paths` value a non-empty, normalised, repo-relative `str` (no leading `/`, no `..` segment); `schema` equal to `config/1`; `ids` exactly the four prefix keys; `base_branch` a non-empty `str`; `decisions.scan` a list of non-empty `str` globs; `decision_classes.owner_only` in the file a non-empty list of non-empty `str` (as the config schema's `min: 1`, Task 1b.1). No `owner` key is read. A missing file raises `GateError(".strict-delivery/config.yml: missing; run /strict-delivery:init")`; a `YamlError` raises `GateError` carrying the file and line; a top level that is not a mapping raises `GateError`.
  - `gitinfo.py` (C locale; messages name the git command, never the directory): `head_sha(root) -> str`; `commit_exists(root, sha) -> bool` (`git cat-file -e <sha>^{commit}`); `blob_exists(root, sha, path) -> bool` (`git cat-file -e <sha>:<path>`, true only for a blob); `tracked_files(root) -> frozenset` (index entries of mode 100644 or 100755 only); `show(root, ref, path) -> Optional[str]` (`None` when the path is absent at `ref`); `ls_tree(root, ref, directory) -> list` (repo-relative paths of regular files directly in `directory` at `ref`; empty when the directory is absent); `merge_base(root, a, b) -> str`; `user_email(root) -> Optional[str]` (`git config user.email`, `None` when unset or empty); every git failure other than these documented `None`/`False`/empty results raises `GateError`.
  - `producers.py`: `PRODUCER_MODULES: tuple` of dotted module names, empty here; each later gate or tool module defines `PRODUCES: tuple` of kind names and is appended to this tuple by its task (Appendix A "declares that kind in its `produces` list").
  - `__main__.py`: `COMMANDS: dict` mapping a command name to `Callable[[list], int]`; `main(argv: list) -> int` dispatches `argv[0]`, returns 2 with usage on stderr for an unknown or missing command. Block 1 registers `check` (`check <gate> [args]`), `decisions`, `findings` and `index` as later tasks land.
  - `tests/helpers.py`: `minimal_config() -> dict` (`schema: config/1`, `framework_version: "0.0.0"`, `profile: strict`; nothing else); `make_repo(tmp: str, config: Optional[dict] = None) -> str` (`git init -b main`, so the first branch is `main` whatever `init.defaultBranch` says; a fixed author and committer identity and date, `user.email` set to `fixture@example.invalid`; `GitIsolatedTestCase(unittest.TestCase)`, the base class of every test that runs git, patches `os.environ` for each test with `unittest.mock.patch.dict` (`HOME` = the test's temp directory, `GIT_CONFIG_NOSYSTEM=1`, `GIT_CONFIG_GLOBAL=/dev/null`), so production code, which inherits `os.environ`, sees an unset repo `user.email` as unset, writes `emit(config or minimal_config())` to `.strict-delivery/config.yml`, commits); `commit_all(root: str, msg: str) -> str` returns the new sha; `write_record(root: str, rel: str, row: dict) -> str` writes `emit(row)`.

**Input-domain dimensions:** `config.load`: required keys (each of `schema`, `framework_version`, `profile` missing), file kind (missing, directory, FIFO, symlink, unreadable), YAML failure, top-level type (`None`, list, scalar), each read key's type (str subclass, `bool` as `int`, `None`, empty), `profile` values (case, whitespace, unknown), each `paths` value (absolute, `..`, `./`, `//`, trailing `/`, empty, non-str), deep-merge shapes (mapping over scalar, scalar over mapping, list replacing list), unknown top-level keys (`owner`, a typo such as `profle`), `ids` values (extra key, missing key, lowercase prefix, empty, two kinds sharing one prefix: refused), `base_branch` (empty, non-str), `decisions.scan` (empty list, non-str item), `decision_classes.owner_only` (not a list, empty list: refused, non-str item, empty-str item, a new slug added to the defaults, a default slug restated, an attempt to drop a default by listing only `hardware`: the defaults stay), `models.tiers` (absent: defaults tier1-3 and no `tier4`; a project `tier4` kept; a tier value non-str or empty: refused; an extra tier name kept), `models`, `models.tiers` or `drift` not a mapping: refused; `drift.estimate_factor_pct` (absent: 150; 0, negative, `bool`, str `"1.5"`: refused). `repo_root`: `CLAUDE_PROJECT_DIR` unset, empty, non-directory; not a git repository. `gitinfo`: `root` kinds, ref forms (full sha, short sha, ambiguous short sha, branch, tag, nonexistent ref, a value starting with `-`), path forms (spaces, unicode, leading `-`, absent, directory, symlink, submodule), unset `user.email`. `run_gate` argv: `--json` first or later, `--help`, unknown flag, empty. `Result` text: newline, CR, control characters, non-str reason; check raising `Exception`, `SystemExit(0)`, `SystemExit("x")`, `KeyboardInterrupt`.

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
  - `store.py`: `@dataclass(frozen=True) Record(id: str, row: dict, file: str)` (`file` repo-relative). `class Store` with `__init__(self, root: str, kind: str, cfg: dict)` (`kind` is `"decision"` or `"finding"`; the directory is `cfg["paths"]["decisions"]` or `cfg["paths"]["findings"]`; the prefix from `cfg["ids"]`); `load() -> list` (every `*.yml` file directly in the directory except `index.yml`, as a `Record`; a missing directory is an empty store; a file that does not load, is not a regular file, or is not a top-level mapping raises `GateError` naming the file); `path_for(id: str) -> str`; `create(row: dict) -> str` (creates the register directory and its parents when absent, then writes `emit(row)` to `<id>.yml`; refuses an existing file with `GateError`); `replace(row: dict) -> str` (rewrites an existing file; refuses a missing one). The store never validates fields; the schema checker does.
  - `store_errors(records: list, prefix: str) -> list` of `(suffix, reason)` pairs: `id.<file>` (the row's `id` fails `id_problem`), `name.<file>` (file stem differs from the row's `id`), `duplicate.<id>` (one id in more than one file; the reason lists every file).
  - `base_errors(root: str, store: Store, base: str, is_resolved: Callable[[dict], bool], may_delete: Callable[[dict], bool]) -> list` of `(suffix, reason)` pairs, where `base` is the base branch ref (OQ-4: callers pass `--base`, default `cfg["base_branch"]`); deletions and immutability compare the working tree with `mb = merge_base(root, base, "HEAD")`, collisions with the tip of `base`: `deleted.<id>` (a record file at `mb` is absent now and `may_delete(row_at_base)` is false; reason `<file> exists on <base>; records on the base branch are never deleted`); `immutable.<id>` (a record resolved at `mb` differs now; reason for decisions `resolved records are immutable; record the change as a new decision with supersedes: <id>`, for findings `... as a new finding`; the one exception in spec §7.2, `closed -> merged` set only by the cleanup step, does not arise in block 1, where `merged` is unreachable (OQ-6), so a closed finding changed in any way fails here); `collision.<id>` (an id added since the merge base that also exists at `base` with different content; reason `id <id> already exists on <base>; mint a new id`). For decisions `may_delete` is always false; for findings it is supplied by Task 1b.3 (OQ-5).

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
  def test_empty_decisions_map_passes():      # decisions: {} and decision_classes: {}
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
  - `decisions.py`: `validate(row: dict, cfg: dict) -> list` (schema errors, plus `class: <x> is not in decision_classes.owner_only`, against the merged list of Task 1a.2; for class `merge-grant`: `plan` has no `/` and no whitespace (both rules owner-approved calls, I9), and `program` and `stream` are both present or both absent and each matches `[a-z0-9][a-z0-9-]*`, and `stream` is not `integration` (spec §11); for any other class `plan`, `program` and `stream` are absent); `landed_errors(row: dict, root: str, cfg: dict, tracked: frozenset) -> list` (each `landed_in` cite, anchor stripped, is a tracked file that contains the row's id as a whole token (Global Constraints, "Whole-token match"; owner Q-rev2-2), and is on the allow-list (OQ-9): under `cfg["paths"]["playbooks"]`, exactly `CLAUDE.md`, or exactly `cfg["paths"]["architecture"]`; any other place fails `landed_in: <cite> is not a playbook, CLAUDE.md or architecture.md`; the anchor is not checked here, `gate_cites` checks it in block 5; a cite under `cfg["paths"]["specs"]` always fails `landed_in: <cite> is a spec; specs are cleaned, land the rule in a playbook, CLAUDE.md or architecture.md`); `is_resolved(row) -> bool` (`status != "open"`); `superseded_ids(records: list) -> set` (ids named in `supersedes` by an answered record only); `ref_errors(records: list) -> list` of `(suffix, reason)`: `supersedes.<id>` (target missing, not answered, the row itself, or a cycle), `checked.<id>` (a `checked_against` id with no record); `current(records: list, id: str) -> str` (follows `supersedes` forward through answered records to the newest id); two open or answered records superseding one id is a `ref_errors` failure `fork.<id>`; a withdrawn superseder is ignored (owner Q-decisions-1 (b)); `in_force(records: list) -> list` (answered, `effect: lasting`, not superseded, class not `merge-grant`); `find(records: list, terms: list, path: Optional[str], topic: Optional[str], include_all: bool) -> list` (case-insensitive match of every term over question, answer and topics; `path` matched with `fnmatch.fnmatchcase` against each `applies_to` glob; superseded hits replaced by `current(...)`, without repeats; in force only unless `include_all`).

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
  def test_withdrawn_superseder_ignored():    # Q-decisions-1: B supersedes A, B withdrawn, C supersedes A
      assert ref_errors([A, B_withdrawn, C_open]) == [] and A["id"] not in superseded_ids([A, B_withdrawn, C_open])
      assert ("fork." + A["id"]) in [s for s, _ in ref_errors([A, B_open, C_open])]
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

**Owner answers applied:** OQ-5, OQ-6, OQ-15, OQ-16.

**Interfaces:**
- Consumes: `schema.*`, `ids.id_problem`, `decisions.is_resolved/validate`, `gitinfo.commit_exists/blob_exists/tracked_files`, `store.Record`.
- Produces:
  - `findings.py` constants: `STATUSES = ["open", "planned", "in-progress", "fixed-unpinned", "pinned", "deferred", "closed", "merged"]` (spec §7.2); `RESOLVED = {"closed", "merged"}`; `SEVERITIES = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]`; `TRANSITIONS = {"open": ["planned", "deferred", "closed"], "planned": ["in-progress", "open", "deferred"], "in-progress": ["fixed-unpinned", "pinned", "planned"], "fixed-unpinned": ["pinned"], "pinned": ["closed", "merged"], "deferred": ["open", "planned"], "closed": ["merged"], "merged": []}` (the table the owner approved with the earlier plan). OQ-6: only the cleanup step (programs block) may set `merged`; in block 1 `merged` is unreachable and `closed` is final, so `validate` refuses `status: merged` and any `merged` history entry with `status: merged is set only by the cleanup step`.
  - `gates/schemas/finding.yml` (`finding/1`, `files: [{dir: findings, glob: "*.yml", exclude: [index.yml]}]`). Fields: `id` (`id`, `id_kind: finding`), `status` (`enum` of `STATUSES`), `source` (`str`), `severity` (`enum` of `SEVERITIES`), `class` (`str`), `siblings` (`list` of `str`), `cites` (`list` of `map {file: str, lines: str, sha: sha}`), `repro` (`str`, `nullable`), `owner` (`map`, fields declared in the schema, never hand-coded (spec §7.2; controller ruling R-rev3-1): `kind` (`enum [plan, issue, roadmap]`), `plan` (`str`; `required_when: [{kind: [plan, roadmap]}]`, `absent_when: [{kind: [issue]}]`), `task` (`str`; `required_when: [{kind: [plan]}]`, `absent_when: [{kind: [issue, roadmap]}]`), `number` (`int`, `min: 1`; `required_when: [{kind: [issue]}]`, `absent_when: [{kind: [plan, roadmap]}]`); any other key gives `owner.<key>: unknown key` (OQ-16)), `pin` (`map {test: str, transcript: sha-path}`, `nullable`; owner Q-plan-4), `ruling` (`id`, `id_kind: decision`, `nullable`), `evidence` (`list` of `str`), `history` (`list`, `min: 1`, items `map {status: enum of STATUSES, sha: sha, by: str}`), `parent` (`id`, `id_kind: finding`, `required: false`), `resolved_by` (`str`; `required_when: [{status: [closed, merged]}]`, `absent_when: [{status: [open, planned, in-progress, fixed-unpinned, pinned, deferred]}]`; spec §7.2 "names the plan that resolved it (`resolved_by: <plan>`)"; a plan name has no `/` and no whitespace, an owner-approved call, I9).
  - `validate(row: dict, cfg: dict) -> list`; `transition_errors(row) -> list` (history starts at `open`; each step is in `TRANSITIONS`; the last history status equals `status`); `evidence_errors(row: dict, root: str, cfg: dict, decision_records: list, tracked: frozenset) -> list` (`deferred` needs `ruling` naming an answered decision; `closed` needs at least one evidence entry; `pinned` needs `pin` and a review-report entry in `evidence` under `cfg["paths"]["reviews"]`; `pin.test` is an opaque non-empty string, never matched against a pattern (spec §13a); `pin.transcript` is a `<sha>:<path>` only (owner Q-plan-4), with `commit_exists(sha)` and `blob_exists(sha, path)`, and its path under `<paths.plan_state>/<owner.plan>/mutations/` when the owner kind is `plan`, else under `<paths.plan_state>/*/mutations/` for any plan (owner Q-rev2-3); OQ-15: an evidence entry is a commit sha (`commit_exists`), a `<sha>:<path>` (`commit_exists(sha)` and `blob_exists(sha, path)`), or a plain path that `tracked` holds and that lies outside every per-effort path (`paths.specs`, `paths.plans`, `paths.plan_state`, `paths.reviews`, `paths.programs`, `paths.claims`) and outside `paths.findings`, open findings included (owner Q-plan-5, spec §5); per-effort files, review reports, transcripts and finding records are cited only as `<sha>:<path>`); `epic_errors(records: list) -> list` of `(suffix, reason)` (`parent.<id>`: the parent is missing, is the row itself, or forms a cycle; `epic.<id>`: a resolved parent with an unresolved child); `is_resolved(row) -> bool` (`status in RESOLVED`); `may_delete(row: dict, root: str, cfg: dict, decision_records: list) -> bool` (OQ-5: true only when the row is resolved and an answered decision of class `merge-grant` has `plan` equal to the row's `resolved_by`; the merge-commit check arrives with `gate_cleanup`).

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
  def test_epic_resolved_parent_with_open_child_fails():
      assert ("epic." + PARENT, ANY) in epic_errors(records)
  def test_may_delete():                      # OQ-5
      assert may_delete(CLOSED, root, cfg, [answered_grant(plan=CLOSED["resolved_by"])]) is True
      for d in [[], [open_grant], [withdrawn_grant], [answered_grant(plan="other")]]: assert may_delete(CLOSED, root, cfg, d) is False
      assert may_delete(FINDING, root, cfg, [answered_grant(plan="p")]) is False
  ```
- [ ] **Step 2: Run the test command; expect FAIL.**
- [ ] **Step 3: Implement `schemas/finding.yml` and `findings.py`.**
- [ ] **Step 4: Run the test command on both interpreters and `python3 -m gates check schema`; expect PASS.**
- [ ] **Step 5: Commit** `feat(lib): finding schema and rules; sha:path evidence`, then checkpoint. **Block 1b end:** as block 1a.

---

## Block 1c: gates and indexes (branch `block/b1c`)

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
- [ ] **Step 5: Commit** `feat(tools): decision and finding indexes, in-force.md, overview; generated files ignored`, then checkpoint. **Block 1c end:** as block 1a.

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
- [ ] **Step 5: Commit** `feat(tools): findings new and move`, then checkpoint. **Block 1d end:** final review, verifier; the controller records the grant with `python3 -m gates decisions ask --class merge-grant ...` `--plan 2026-10-31-strict-delivery-framework --effect one-off` (OQ-8), and the human answers it with `! python3 -m gates decisions decide <id> --answer ...`; merge; checkpoint; continuation.

---

## Later blocks (outline; each gets its own detailed plan section, input-domain dimensions and owner batch before it starts, split into sub-blocks of at most 3 tasks)

- **Block 2.** `gate_claims` with the claim schema (`claims/<doc-slug>.yml`, direct and contradiction commands, staleness from the cited paths), the no-delete rule extended to claim files, and claim ids `C-<YYYYMMDD>-<xxxx>`; `gate_dispatch` (spec §10 grammar, a fork refused, the tool's model equal to `## Model` and at least the role's minimum tier from `models.tiers`, the top tier only for `top_tier_roles`); `run_all` running the gates the profile enables (a missing or raising gate fails); the git hook shims (one-line POSIX sh exec of `python3 -m gates`) and their installer; self-adoption: this repository answers yes to both extras, runs `run_all` in pre-commit, and gets its CI workflow (Python 3.9 and 3.13 on ubuntu and macOS). From here the commit gate is `run_all` plus the suite on both interpreters.
- **Programs block** (after block 2, so this repository can run blocks 3-6 as a program; design §16, spec §17). Order: (P1) the handoff and ledger schemas and a basic `gate_checkpoint` (handoff front matter per its schema, the block's own worktree clean while other streams' worktrees may be dirty, the continuation handoff present, the ledger's `CHECKPOINT` line); (P2) the streams, request and status schemas, request records `R-<YYYYMMDD>-<xxxx>` minted only by the program controller, the status page with header exactly `stream | block | branch | worktree | next task | estimate | used | status | blockers | pending decisions | delivers`, and `gate_streams` (ownership disjoint, every changed path owned or a shared file under `append-rows` or `own-row`, status rows, request records; branch and id rules of design §4.1 and spec §11); (P3) `gate_cleanup` for plain plans and programs (per-effort files gone after a merge or close; every lasting decision they produced lands outside them; resolved findings deleted only under design §8.1's deletion proof); (P4) the program_controller and stream_controller prompt blocks (tier3), automatic continuation (the continue prompt rendered from handoff, ledger and status page), the upward-question path (handoff question plus `SendMessage` to the parent; answers as decision records), and `gate_dispatch` extended for the two roles and their dispatchers. `gate_streams` and `gate_dispatch` run wherever a program is live, whatever the profile.
- **Block 3.** Plugin: `.claude-plugin/plugin.json` and `marketplace.json`; the skill `SKILL.md`; the role prompt blocks (PC1-PC5 written into this repository's blocks); the base playbook (spec §8 rules as `SD-R<n>`); the Claude Code hooks as `python3 -m gates hook <event>` (SessionStart, UserPromptSubmit, PreToolUse Agent, Bash and Edit/Write, PostToolUse Read), with the Bash branch blocking hook bypasses and refusing `decisions decide` and `decisions withdraw` from any agent (spec §4, §7.1), and the Edit/Write branch surfacing in-force decisions whose `applies_to` matches, once per session.
- **Block 4.** `init` (stack command detection that only proposes, an answers file for non-interactive runs, the two extras' questions, the no-overwrite rule, the managed CLAUDE.md and `.gitignore` blocks with their claude-block and gitignore-block schemas, migration of existing `docs/superpowers/` specs and plans with `git mv` and reference rewrite), `doctor`, `upgrade` with tested schema migrations (including this repository's plain `.gitignore` lines becoming the managed block), templates, the CI workflow template pinned to a tag, profiles `light`, `standard` and `strict`, and the fixture repositories (node, rust, go, python, C with make, empty, monorepo).
- **Block 5.** Context, docs and drift tooling in full: `context.yml` and its schema, read receipts and the receipt schema, `gate_context`, `gate_cites`, `gate_drift` (status-page and handoff facts against git, a stream behind integration or integration behind main, blocks past `drift.estimate_factor_pct` percent of their estimate), and `gate_index` (the indexes and `INDEX.md` regenerate without error; a tracked generated file fails).
- **Block 6.** `gate_checkpoint` in full, `gate_evidence` (spec §13a: pin command re-run, transcript shape pass-fail-pass, with the mutation-transcript and review-report schemas), the profile end-to-end tests, the release script, `CHANGELOG.md`, and tag `v0.1.0`.

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
