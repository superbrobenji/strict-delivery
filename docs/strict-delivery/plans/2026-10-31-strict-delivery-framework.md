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

## Streams before the programs block

Owner decision 2026-10-31: two streams run beside stream A (block 1 in order, then block 2) before the programs tooling exists. The session controller coordinates them by hand. Design §1 states the aim these rules serve here: "Every file and every piece of work has exactly one owner within an effort." Design §6 states the core rule: "When stream A needs a change in a file stream B owns, A never edits it." Until `gate_streams` lands (programs block, P2), a person or agent enforces both, using the checks below. Nothing is left to memory.

- **Streams.**
  - **A**: blocks 1a-1d, block 2, then the programs block. A runs in the main checkout.
  - **B**: the prose of block 3 (section "Stream B" below). B starts once its section is approved.
  - **C**: init's stack command detection (block 4) and `gate_cites` (block 5) (section "Stream C" below). C starts after block 1a merges into `main`.
- **File ownership.** The three path lists are disjoint. A is the residual owner: every path a block-1 or block-2 task creates or modifies belongs to A, and so does every path the table does not list.

  | Stream | Owns (exact paths; a trailing `/` means every path under that directory) |
  |---|---|
  | B | `skills/strict-delivery/SKILL.md`; `skills/strict-delivery/prompts/controller.md`, `implementer.md`, `implementer_transcription.md`, `task_reviewer.md`, `final_reviewer.md`, `final_verifier.md`, `exception_reviewer.md`, `audit_reviewer.md`, `audit_verifier.md`, `investigator.md` (these ten files only, each directly in the prompts directory; the directory itself is not B's); `playbook/rules.md`, `playbook/roles.md`, `playbook/decisions.md`, `playbook/sessions.md`, `playbook/streams.md`, `playbook/review.md`; `tests/prose_check.py`, `tests/test_prompt_blocks.py`, `tests/test_playbook.py`, `tests/test_skill.py`; `.strict-delivery/state/plans/2026-10-31-strict-delivery-framework-b/` |
  | C | `gates/lib/detect.py`, `gates/lib/cites.py`, `gates/lib/slug_table.py`, `gates/lib/case_table.py`, `gates/gate_cites.py`; `tests/test_detect.py`, `tests/test_cites_lib.py`, `tests/test_gate_cites.py`; `.strict-delivery/state/plans/2026-10-31-strict-delivery-framework-c/` |
  | A | every path of the block-1 file lists (Tasks 1a.1-1d.2), every path block 2 and the programs block create, `skills/strict-delivery/prompts/program_controller.md` and `stream_controller.md` (programs block P4), `.strict-delivery/state/plans/2026-10-31-strict-delivery-framework/`, and every path not listed for B or C |

  When a stream's last block merges into `main`, every path in its row passes to A, the residual owner (owner answer DS-3). Until then the row stands.

  The programs-block outline gives the `program_controller` and `stream_controller` prompt blocks to P4. They stay with A, and B's format test (Task B1.1) applies to them when they land.
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
  3. an owner merge grant for that block;
  4. the merge into `main` as its own command;
  5. the post-merge gate run on `main`;
  6. the checkpoint.

  Grants before Task 1d.1 lands are given in chat and ledgered verbatim in that stream's ledger. After it lands, the session controller records each grant with `decisions ask --class merge-grant --plan 2026-10-31-strict-delivery-framework`, and the human answers it. `program` and `stream` stay absent, since spec §7.1 allows them only together and there is no program. The grant's question text names the stream and the block branch.

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
  - Nothing outside the stream's rows changed: `git diff --name-only main...block/sb<n> | grep -v -E '^(skills/strict-delivery/(SKILL\.md|prompts/(controller|implementer|implementer_transcription|task_reviewer|final_reviewer|final_verifier|exception_reviewer|audit_reviewer|audit_verifier|investigator)\.md)|playbook/(rules|roles|decisions|sessions|streams|review)\.md|tests/(prose_check|test_prompt_blocks|test_playbook|test_skill)\.py|\.strict-delivery/state/plans/2026-10-31-strict-delivery-framework-b/.*)$'`. Stream C uses the same check with its own rows.

---

## Stream B: plugin prose (branches `block/sb1`, then `block/sb2`)

Stream B writes the prose of spec §17 block 3: the role prompt blocks, the base playbook and the skill. It writes no gate code. Its tests are standard-library text checks over its own files, except two drift tests that each import one constant of A's code: `test_owner_only_matches_config_defaults` (Task B2.3, `gates.lib.config.DEFAULTS`) and, when the stream rules' "Cross-stream order" gives it to B, `test_fixed_rules_match_decisions_constant` (Task B2.1, `gates.lib.decisions.FIXED_RULES`). B depends on no other interface of A. Global Constraints, the Process for this plan, and the stream rules above all apply.

**Sources.** Spec §3 (layout and precedence), §7 (decisions), §8 (base playbook), §10 (roles and dispatch grammar), §12 (profiles), §13 and §13a, and design §4-§6 and §10-§12. The template for shape is the user-level `strict-delivery` skill and its eight prompt files (one-line intro, labelled paragraphs). B generalises them; it never copies them. B's files are public, and Task B1.1's forbidden-string check enforces the exclusions of spec §2 by test.

**Consumed later by:**
- `gate_dispatch` (block 2, stream A). Spec §10: "`## Strict block` (the role's prompt block, byte for byte)". It reads `skills/strict-delivery/prompts/<role>.md` and its first-line and heading rules (Task B1.1 Produces). It lands only after block B1 merges (stream rules, "Cross-stream order").
- Programs block P4 (stream A). Its two new prompt files must pass B's format test, with labels of their own in `LABELS`. Owner answer DS-3: once B's last block (B2) has merged, `tests/prose_check.py` is A's and P4 adds the two rows itself; while B is still live, P4 raises a request to B (stream rules above).
- Block 3 code (later, run as a program):
  - `.claude-plugin/plugin.json` packages `skills/` and `playbook/`.
  - The SessionStart hook prints "the instruction to invoke the strict-delivery skill" (skill `name` from Task B2.3) and lists active overrides (spec §4: "active rule overrides") from answered `rule-override` decisions. It refuses nothing. An override of a `fixed: yes` rule is refused when it is written, by `decisions.validate` (block 2, stream A) against `FIXED_RULES`, which a test keeps equal to `playbook/rules.md`'s `fixed` column (Task B2.1).
- Block 4 code (later):
  - The CLAUDE.md managed block points at `playbook/` (spec §8: "The CLAUDE.md managed block points at it").
  - The profiles' `roles` defaults name each role's prompt file and minimum tier (Task B2.2 `playbook/roles.md` is the prose source).

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
- [ ] **Step 5: Commit** `docs(prompts): controller and audit blocks`, then checkpoint. **Block B1 end:** final review, verifier, merge grant, merge into `main`, checkpoint, continuation (stream rules above).

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
  - `sessions.md`: session kinds, start order, blocks, checkpoints, handoffs and continuation (spec §9, design §4.4, §10).
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
- [ ] **Step 5: Commit** `docs(skill): strict-delivery skill`, then checkpoint. **Block B2 end:** final review, verifier, merge grant, merge into `main`, checkpoint. Stream B is then done: its paths pass to A (DS-3).

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
      - In both problem cases no later name is read, so nothing is proposed from a file `make` would not read.
    - What a Makefile proposal promises (owner Q-C11r4-0 (a)): only that it names a literal target of a plain rule in a file whose every line is one of the allowed forms below. It does not promise that `make` will run that rule; init shows the source line and the owner confirms.
    - The file is read line by line (physical lines; a CR directly before the newline is part of the line end) as a fail-closed whitelist (owner Q-C11rr-3). Before the forms below, each line is refused, in this order (owner Q-C11r4-0 (a)), when it holds:
      - a control character, Unicode category Cc (U+0000-U+001F, U+007F-U+009F) other than TAB, NUL included; a CR anywhere but directly before the newline (also a CR at the end of a file with no final newline) counts as one (reason `control character`; F-C11r4-4);
      - a line ending in `\` (reason `line ends in a backslash`);
      - a call to `eval`, `error`, `shell`, `file`, `call`, `value`, `info` or `warning` in `$(...)` or `${...}` form: `$(` or `${`, the name, then any character other than an ASCII letter, ASCII digit, `_` or `-` (so `$(eval.x)` and `$(evalé x)` are refused; controller ruling D-C11r4r-1 (a) under owner Q-C11r4-0), or the end of the line. This applies to every line, comment and recipe lines included, and `$$(shell x)` is refused as well (reason `make function call`; F-C11r4-2).
    Every line must then be one of:
      1. blank or whitespace-only;
      2. a comment: optional blanks, then `#`;
      3. a simple assignment, not starting with `\t`: `NAME op value`, with NAME `[A-Za-z_][A-Za-z0-9_.-]*` and `op` one of `=`, `:=`, `?=`, `+=` (blanks around `op` optional); an assignment to `MAKEFLAGS` or `MFLAGS` (exact names, any operator, any value) is refused (reason `assignment to MAKEFLAGS or MFLAGS`; owner Q-C11r4-0 (a), F-C11r4-3);
      4. a rule, not starting with `\t`: one or more literal targets (each `[A-Za-z0-9_.-]+`, so no `$`, `%`, `=` or `/`; `./test:` is refused, since make reads `test` and `./test` as one target; owner Q-C11r4-0 (a), F-C11r4-1), then `:` or `::`, then text that holds no `=`, no `;`, no `\` and no second `:`; a `#` ends the text, and what follows it is a comment. A target must not appear under both `:` and `::` in the file. Leading blanks of forms 3 and 4 are skipped; a first character `\t` makes the line a recipe line. A line is a directive line, and refused, when its first word (after leading blanks, up to a blank, `:`, `=`, `?`, `+` or `!`) is a directive word (`export`, `unexport`, `override`, `private`, `vpath`, `include`, `-include`, `sinclude`, `undefine`, `define`, `endef`, `ifdef`, `ifndef`, `ifeq`, `ifneq`, `else`, `endif`), whatever follows (`include:`, `ifdef ::`, `export =x` included), or when a directive word is any of its targets (`test export:`); this applies to forms 3 and 4 alike (controller ruling R2 under owner Q-C11rr-3);
      5. a recipe line: starts with `\t`, and only once a rule line has appeared since the last assignment (blank and comment lines between keep that context). Its text is not examined.
    - Any other line, and any line ending in `\`, gives no proposals from that Makefile and exactly one `Problem("<name>", "unsupported line <n>: <reason>")`, where `<n>` is the first such line (1-based) and `<name>` the Makefile name as listed. The reason is fixed text and never quotes the file. Refused, with examples: `define`/`endef`; `ifeq`/`ifneq`/`ifdef`/`ifndef`/`else`/`endif`; `include`/`-include`/`sinclude`; `export`/`unexport`/`override`/`private`/`vpath`/`undefine`, also alone or as a target (`include:`, `test export:`); a target-specific variable (`test: X = 1`, `test: X != 1`); `;` after the colon (`test: ; echo`); a second `:` after the colon (`test ::: x`, `test: a:b`); a target under both `:` and `::` (the Problem names the second line); a backslash (`x \` then `test:`; `test: a\;b`); a tab-led line before the first rule or after an assignment; `$(T):`, `%:`; a `/` in a target (`./test:`, `out/x.o:`); `test != x`, `test ::= x`; a control character (`\0`, a form feed, a lone CR); `MAKEFLAGS = -q`, `MFLAGS += -t`; `X := $(error x)`, `# $(shell x)`, `\t@echo ${info x}`; any text that is none of the five forms. Nothing is guessed: a Makefile that uses a construct outside the whitelist is not read at all, and init asks the owner for the commands.
    - Checked with GNU Make 3.81, `make -n <target>` in a scratch directory, recipe `\t@echo ran`:
      - rc 0, so proposed: `test:`, `test::`, `build test:` (both targets), `  test:` (leading spaces), ` \ttest:` (a space, then a tab).
      - `test: dep` and `test : x` are proposed as well: without the prerequisite file make gives rc 2 with "No rule to make target `dep', needed by `test'", which names `test` as a rule. A target with no rule gives "No rule to make target `lint'" with no "needed by". This stands (owner Q-C11r4-3 (a)): the rule exists, and a prerequisite that make cannot build is not a reason to withhold the proposal.
      - `test := x` and `test: X = 1` define no target: rc 2 "No rule to make target `test'".
      - `.PHONY: test` is accepted as a rule line but proposes nothing (its target is `.PHONY`); make runs it (rc 0, "Nothing to be done").
    - Each target named exactly `test`, `lint` or `build` gives `Proposal(name, "make " + name, "<file>:<line> " + name)`, the first definition only.
    - A file that is not UTF-8 gives a `Problem`.
    - Out of scope (owner Q-C11r4-0 (a), F-C11r4-5): repository state. Detection reads only the source files; it does not check whether an entry named like a slot (a `test/` folder or a `test` file in `root` or in a `VPATH` directory) would make `make test` report "up to date" instead of running the rule.

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
- Makefile lines (the whitelist; owner Q-C11rr-3):
  - blank and whitespace-only lines; comments (`# test:`, `  # test:`);
  - simple assignments with each operator (`=`, `:=`, `?=`, `+=`), with and without blanks around it, also leading blanks (`test := x`: not a rule);
  - rules: `test:`, `test: dep`, `test::`, `build test:`, `test : x`, leading spaces `  test:`, a space then a tab ` \ttest:`, a trailing `#` comment, `.PHONY: test` (accepted, proposes nothing), literal targets with `.`, `-`, `_` and digits, `/` after the colon (`test: src/a.c`);
  - recipe lines: after a rule (also past blank and comment lines), not before the first rule, not after an assignment;
  - refused with one `Problem`, the first such line named: `define`/`endef`; `ifeq`/`ifneq`/`ifdef`/`ifndef`/`else`/`endif`; `include`/`-include`/`sinclude`; `export`/`unexport`/`override`/`private`/`vpath`/`undefine` as first word or as a target, also alone (`include:`, `include :`); target-specific variables; `;`, `\` or a second `:` after the colon (`test ::: x`, `test: a:b`); a target under both `:` and `::` (the Problem names the second line; controller ruling R3 under owner Q-C11rr-3); any line ending in `\`; a tab-led line before the first rule; `$` or `%` in a target; `test != x`, `test ::= x`; unmatched text, a BOM, a form feed;
  - refused under owner Q-C11r4-0 (a), on any line: every Cc character other than TAB (NUL, form feed, U+0085), a CR not directly before the newline; a `/` in a target (`./test:`, `./test::` after `test:`, `out/x.o:`); an assignment to `MAKEFLAGS` or `MFLAGS` with each operator; a call to each of `eval`, `error`, `shell`, `file`, `call`, `value`, `info`, `warning` in `$(...)` and `${...}` form in an assignment value of each flavour, after the colon, in a recipe and in a comment, nested, after `$$`; accepted neighbours (U+0020, U+007E, U+00A0, U+00AD in a comment; `makeflags`, `MAKEFLAGSX`, `MAKEFLAGS:` as a target; `$(CC)`, `$(SHELL)`, `$(evaluate x)`, `$( shell x)`, `$(filter a,b)`);
  - repository state (a `test/` folder or `test` file in `root`): out of scope, the proposal stands (owner Q-C11r4-0 (a));
  - CRLF line ends, no final newline, a duplicate definition, physical line numbers.
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
  def test_makefile_assignments_are_not_rules():
      # subTests (each the whole Makefile): "test=x\n", "test:=x\n", "test := x\n", "test ?= x\n", "test += x\n",
      #   "  test := x\n", "  # test:\n", "# test:\n", ".PHONY: test\n"
      assert detect(tmp).proposals == () and detect(tmp).problems == ()
  def test_makefile_rule_after_leading_blanks():        # subTests: "  test:\n\t@echo ran\n", " \ttest:\n\t@echo ran\n" (3.81: rc 0, `ran`)
      assert [(p.slot, p.command, p.source) for p in detect(tmp).proposals] == [("test", "make test", "Makefile:1 test")]
  def test_makefile_unsupported_line_is_one_problem():  # subTests: "define D\ntest:\nendef\n", "ifdef X\n", "include x.mk\n",
      # "export test:\n", "test: X = 1\n", "test: ; echo\n", "x \\\ntest:\n", "\ttest:\n", "$(T):\n", "test != x\n", "foo\n"
      d = detect(tmp)
      assert d.proposals == () and d.problems == (Problem("Makefile", "unsupported line 1: <reason>"),)
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

**Owner answers applied:** DC-1 (the seven-row table below; lint only from a project file that names it), DC-3; Q-C12-1 to Q-C12-5 (2026-11-01, all option (a)):
- Q-C12-1: any `"""` or `'''` anywhere in `pyproject.toml` gives one `Problem("pyproject.toml", "unsupported line <n>: multi-line string")` (n the first such line) and no proposals from that file; no TOML lexing.
- Q-C12-2: "file present" for rows 3-6 means the file is opened through `_fetch` (an unreadable file is a `Problem`), content not examined; `mvnw` and `gradlew` must have an execute bit (`st_mode & 0o111`), else `Problem("<name>", "not executable")`. The plan test `test_toolchain_sources` therefore `chmod`s the wrappers.
- Q-C12-3: a row 3-7 source counts only under its exact spelling in `os.listdir(root)`; a case variant is nothing.
- Q-C12-4: Task C1.1's Makefile name match compares ASCII case only (fixes K1, a KELVIN SIGN name): an entry with a non-ASCII character never matches a probe; when `lstat` finds the probe but no listing entry matches exactly or by ASCII case, the result is `Problem("<probe>", "name not ASCII")` and no later name is read.
- Q-C12-5: `[tool.ruff.format]` (a sub-table whose first key is `format`) gives no lint proposal; `[tool.ruff]` or any other `[tool.ruff.<sub>]` still does.
- Controller row S1: `SOURCES` is the tuple of the seven labels (`"Makefile"` stands for row 2); `detect` reads through one private label -> reader table whose keys a test checks against `SOURCES`.
- Controller ruling (reason text not fixed by the owner): a UTF-8 byte order mark at the start of `pyproject.toml` gives `Problem("pyproject.toml", "unsupported line 1: byte order mark")` and no proposals.

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
- [ ] **Step 5: Commit** `feat(lib): toolchain detection sources and order`, then checkpoint. **Block C1 end:** final review, verifier, merge grant, merge into `main`, checkpoint, continuation.

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
- [ ] **Step 6: Enable** (after stream A's registration commit is on `main` and C has updated from `main`). Run `python3 -m gates check cites`; expect every line `PASS` and exit 0. From then on, every stream's commit gate includes `check cites`. If block 2 has merged into `main` by then, raise the second request to A, to add `cites` to `run_all`'s gate list; until A's commit is on `main`, every stream's commit gate runs `check cites` beside `run_all` (stream rules, "Cross-stream order"). **Block C2 end:** final review, verifier, merge grant, merge into `main`, checkpoint. Stream C is then done: its paths pass to A (DS-3).

---

## Later blocks (outline; each gets its own detailed plan section, input-domain dimensions and owner batch before it starts, split into sub-blocks of at most 3 tasks)

- **Block 2.** `gate_claims` with the claim schema (`claims/<doc-slug>.yml`, direct and contradiction commands, staleness from the cited paths), the no-delete rule extended to claim files, and claim ids `C-<YYYYMMDD>-<xxxx>`; `gate_dispatch` (spec §10 grammar, a fork refused, the tool's model equal to `## Model` and at least the role's minimum tier from `models.tiers`, the top tier only for `top_tier_roles`); `run_all` running the gates the profile enables (a missing or raising gate fails); the git hook shims (one-line POSIX sh exec of `python3 -m gates`) and their installer, where the pre-commit hook refuses a commit while any tracked file has unstaged changes, so the working tree every gate reads is the tree being committed (owner answer 2026-10-31); self-adoption: this repository answers yes to both extras, runs `run_all` in pre-commit, and gets its CI workflow (Python 3.9 and 3.13 on ubuntu and macOS). The decision schema `decision/2` (stream A; owner answers DB-9, F-1, F-2): `gates/schemas/decision.yml` gains the optional `overrides` (`str`); `decisions.validate` refuses a value that does not fully match `SD-R[1-9][0-9]*`, any class other than `rule-override`, and a value in `FIXED_RULES`, a constant in `gates/lib/decisions.py` equal to `("SD-R3", "SD-R12", "SD-R18")` that `test_fixed_rules_match_decisions_constant` in `tests/test_playbook.py` keeps equal to the `fixed: yes` rows of `playbook/rules.md`, with one writer in each landing order (stream rules, "Cross-stream order"): if this task is on `main` before block B2 merges, stream B writes the test on `block/sb2` while `tests/test_playbook.py` is B's file; if B2 merges first, `tests/test_playbook.py` is A's file (owner answer DS-3) and this task adds the test; a schema-migration registry in `gates/lib/` (spec §3 layout, "schema migrations") holds the entry from `decision/1` to `decision/2`, tested from a `decision/1` fixture; `base_errors` (Task 1a.3) migrates each base row with the registered migrations up to the current schema version before comparing, so a record that differs from its base row only by a registered migration is not an immutability change (spec §7.2), with tests that a migrated answered record passes and that any other change to it still fails `immutable.<id>`; this repository's decision records are migrated in the same commit, so `check schema` and `check decisions` stay green; block 4's `upgrade` runs migrations from the same registry, and `base_errors` accepts the records it migrates in the same way. Which `decisions` command writes `overrides` is settled in block 2's detailed section and owner batch. From here the commit gate is `run_all` plus the suite on both interpreters.
- **Programs block** (after block 2, so this repository can run blocks 3-6 as a program; design §16, spec §17). Order: (P1) the handoff and ledger schemas and a basic `gate_checkpoint` (handoff front matter per its schema, the block's own worktree clean while other streams' worktrees may be dirty, the continuation handoff present, the ledger's `CHECKPOINT` line); (P2) the streams, request and status schemas, request records `R-<YYYYMMDD>-<xxxx>` minted only by the program controller, the status page with header exactly `stream | block | branch | worktree | next task | estimate | used | status | blockers | pending decisions | delivers`, and `gate_streams` (ownership disjoint, every changed path owned or a shared file under `append-rows` or `own-row`, status rows, request records; branch and id rules of design §4.1 and spec §11); (P3) `gate_cleanup` for plain plans and programs (per-effort files gone after a merge or close; every lasting decision they produced lands outside them; resolved findings deleted only under design §8.1's deletion proof); (P4) the program_controller and stream_controller prompt blocks (tier3), automatic continuation (the continue prompt rendered from handoff, ledger and status page), the upward-question path (handoff question plus `SendMessage` to the parent; answers as decision records), and `gate_dispatch` extended for the two roles and their dispatchers. `gate_streams` and `gate_dispatch` run wherever a program is live, whatever the profile.
- **Block 3.** Plugin: `.claude-plugin/plugin.json` and `marketplace.json`; the skill `SKILL.md`, the role prompt blocks (PC1-PC5 written into this repository's blocks) and the base playbook (spec §8 rules as `SD-R<n>`), all delivered by stream B (Tasks B1.1-B2.3), which block 3 packages and does not plan again; the Claude Code hooks as `python3 -m gates hook <event>` (SessionStart, UserPromptSubmit, PreToolUse Agent, Bash and Edit/Write, PostToolUse Read), with the Bash branch blocking hook bypasses, refusing `decisions decide` and `decisions withdraw` from any agent (spec §4, §7.1), and, in its gated commit, refusing a `git commit` while any tracked file has unstaged changes, before any gate runs (spec §13, owner answer 2026-10-31), and refusing a Bash command that runs `git commit` inside a compound command, or with a `GIT_INDEX_FILE` override, so a commit runs as its own command (spec §13, owner answers 2026-11-01); tests: `git add x && git commit` refused with no gate run; `git commit` joined by each of `;`, `||`, `|`, `&` and a newline refused; `git commit` inside `( )`, `{ ...; }`, `$( )`, backticks, `sh -c`/`bash -c` and `eval` refused; `GIT_INDEX_FILE=x git commit` and `env GIT_INDEX_FILE=x git commit` refused; `git commit -m "a && b"` (separator inside quotes) not compound, so the clean-tree check decides; a lone `git commit` on a clean tree lets the gates run, tested through the Bash branch's production entry `python3 -m gates hook` on a temporary repository: a tracked file staged and then changed again makes `git commit` refused with no gate run, `git commit -a` with an unstaged tracked change is refused the same way, a deleted tracked file not yet staged is refused, and a clean tree lets the gates run, and the Edit/Write branch surfacing in-force decisions whose `applies_to` matches, once per session; SessionStart lists active overrides (spec §4) from answered `rule-override` decisions' `overrides` field (`decision/2`, block 2); it refuses nothing, since `decisions.validate` already refuses an override of a fixed rule when it is written (block 2).
- **Block 4.** `init` (stack command detection that only proposes, by calling `detect.detect`, which stream C delivers in Tasks C1.1-C1.2 and block 4 does not plan again, an answers file for non-interactive runs, the two extras' questions, the no-overwrite rule, the managed CLAUDE.md and `.gitignore` blocks with their claude-block and gitignore-block schemas, migration of existing `docs/superpowers/` specs and plans with `git mv` and reference rewrite), `doctor`, `upgrade` with tested schema migrations (including this repository's plain `.gitignore` lines becoming the managed block), templates, the CI workflow template pinned to a tag, profiles `light`, `standard` and `strict`, and the fixture repositories (node, rust, go, python, C with make, empty, monorepo).
- **Block 5.** Context, docs and drift tooling in full: `context.yml` and its schema, read receipts and the receipt schema, `gate_context`, `gate_cites` (delivered by stream C in Tasks C2.1-C2.2; block 5 does not plan it again), `gate_drift` (status-page and handoff facts against git, a stream behind integration or integration behind main, blocks past `drift.estimate_factor_pct` percent of their estimate), and `gate_index` (the indexes and `INDEX.md` regenerate without error; a tracked generated file fails).
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
