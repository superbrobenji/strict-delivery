# strict-delivery framework Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build block 1 of the strict-delivery framework (spec §17.1): the gate library, the strict YAML subset, sharded decision and finding registers, `gate_register`, `gate_decisions`, and the decisions/findings tools. Blocks 2-6 are outlined at the end.

**Architecture:** A standard-library Python package `gates/` at the repository root, run as `python3 -m gates <command>`. `gates/lib/` holds pure modules (YAML subset, result contract, config, git, sharded store, decision and finding schemas); gates and tools are thin CLIs over them. Every gate reads a target tree given by `--root` (default: the repository root) and that tree's `.strict-delivery/config.yml`.

**Tech Stack:** Python 3.9+ standard library only (`unittest`, `argparse`, `subprocess`, `fnmatch`, `dataclasses`); git.

**Spec:** `docs/strict-delivery/specs/2026-10-31-strict-delivery-framework-design.md`

## Global Constraints

- Python 3.9 or newer, standard library only. No PyYAML, no third-party test runner: tests are `unittest`.
- State and config use the strict YAML subset (spec §6); every other YAML feature is refused with a line number.
- Language- and project-agnostic: no hardcoded model names, paths, owner handle or test filename patterns in gate code. Everything comes from config with the defaults in spec §5 and §6.
- Registers ship empty. No lap-timer decisions, findings, claims, DEC numbers, `LEGACY_PACKAGES`, D34 text or lap-timer state as fixtures. The repository is public; tests use synthetic fixtures built in temp directories.
- Gate contract (spec §13): `check(args) -> Result`; prints `PASS id` / `FAIL id: reason`; `--json`; exit 0 only when at least one line exists and every line passes; missing input fails as `<gate>.input`, an empty run as `<gate>.empty`; `--root` points at another tree.
- Ids: decisions `DEC-NNNN`, findings `F-NNNN`, width 4 (config `ids`). Shard size 50: `DEC-0137` lives in `resolved/DEC-0101-0150.yml`.
- Only the owner handle (`owner.handle` in config) answers or withdraws a decision.
- Every commit carries `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Test command, every task, on both interpreters (strict profile): `python3 -m unittest discover -s tests -t . -v` (system 3.9.6) and `python3.13 -m unittest discover -s tests -t . -v` (Homebrew `python@3.13`, installed before Task 1a.1). Both must pass before every commit.

## Process for this plan

- Bootstrap (spec §16): no gates exist when block 1a starts. Judgment rules apply by hand and the first report says so. `gate_decisions` and `gate_register` are enabled on this repository in Task 1b.3; from then every checkpoint runs them.
- Spec §17 block 1 has eight tasks; the block cap is 3 (strict profile). The plan splits it into sub-blocks **1a** (Tasks 1a.1-1a.3), **1b** (1b.1-1b.3) and **1c** (1c.1-1c.2), each on its own branch (`block/b1a`, `block/b1b`, `block/b1c`), each ending with final review + top-tier verifier + an owner merge grant, then `/clear`.
- Checkpoint after every task: append one line to `.strict-delivery/state/plans/2026-10-31-strict-delivery-framework/ledger.md`:
  `CHECKPOINT <block> <task> head=<short sha> tests=<passed>/<total> gates=<PASS|n/a> next=<task id>`
  and rewrite `handoff.md` beside it with the resume prompt:
  `Resume strict-delivery plan docs/strict-delivery/plans/2026-10-31-strict-delivery-framework.md at <next task>; branch <branch>; head <sha>; open questions: <ids or none>.`
  Tree clean after the checkpoint commit.
- Owner answers recorded 2026-10-31 (before the decision log exists): split of block 1 approved; the plan's design choices for fields the spec leaves open approved (`asked_at`/`answered_at.at` are commit shas, `withdraw` is owner-only, `schema: 1` wrappers, optional finding `parent`, `check <gate>` command form, `decisions.scan` defaults, LICENSE holder); Python 3.13 installed locally; execution subagent-driven.
- Process changes adopted by the owner 2026-10-31 after the Task 1a.1 convergence stop (applied to this plan's briefs and dispatches now, and written into this repository's own prompt blocks in block 3; the shared user-level skill is not changed):
  - PC1: every task whose Produces list takes an argument or reads a file carries an input-domain table in its brief. The table has one row per parameter or filesystem call and dimension, and each row gives values, the expected verdict and a test name. Dimensions include argument type (subclasses, bool as int), path kind, character class, the character after each indicator, each output position, and the resources held on each error path. A missing table blocks dispatch.
  - PC2: briefs state the oracle as the production path plus an independent expected value (for a parser: `load` of a file written by `emit`, and a fuzz generator that builds each document with its expected value).
  - PC3: an implementer lists every behaviour the brief does not state, and every knowing divergence, and stops NEEDS_DECISION. In a fix round it first lists the invariants the replaced code held and tests each. It writes one mutant per changed production condition or call.
  - PC4: reviewers have no out-of-scope bucket for this task's own code. A class that seems to exclude a failing whitelist input is a class-narrowing question for the owner. A missing input-domain table is a finding.
  - PC5: the ledger writes each finding's class by input dimension (`class: <dimension>: <members>`), and fix and re-review dispatches quote it verbatim.
- Owner questions are batched (owner, 2026-10-31). Before each task's dispatch, the controller drafts the input-domain table and lists every row whose verdict the spec, plan and earlier rulings do not settle. These go to the owner as one batch, with options and costs, and dispatch waits for the answers. Questions raised mid-task are collected and asked together at the next stop: a review verdict or the block end. They are never asked one at a time. The strict profile and full v0.1 scope stay (owner, 2026-10-31).
- Roles (spec §10): implementer sonnet; task reviewer and final reviewer opus; final verifier and exception reviewer the top tier only.

## Review Focus

1. Hand-written YAML values that other parsers coerce (`yes`, `no`, `on`, `2026-10-31`, `1.0`, `0.1.0`, `007`) must come back as strings, and the emitter must quote them so parse(emit(x)) == x. Test in Task 1a.1: `test_ambiguous_plain_scalars_are_strings`.
2. CRLF line endings and a UTF-8 BOM in a hand-edited file are accepted; invalid UTF-8 fails naming the file. Test in Task 1a.1: `test_crlf_and_bom_accepted`, `test_invalid_utf8_names_file`.
3. Two branches each `ask` a new decision, both get `DEC-0005`, and the merge has two `DEC-0005` records. The gate fails `decisions.duplicate.DEC-0005` and says to renumber the newer one. Test in Task 1b.1: `test_duplicate_across_open_files_and_shard`.
4. The owner hand-fixes a typo in an answered decision. The immutability check fails and names `supersedes` as the remedy. Test in Task 1b.2: `test_edited_resolved_row_fails_with_remedy`.
5. A gate run outside a git repository, or in one without `.strict-delivery/config.yml`, fails `<gate>.input` with a message naming `/strict-delivery:init`, never a traceback. Test in Task 1a.2: `test_missing_config_names_init`.

---

## Block 1a: library foundations

### Task 1a.1: strict YAML subset parser and emitter

**Files:**
- Create: `gates/__init__.py` (empty), `gates/lib/__init__.py` (empty), `gates/lib/yamlsub.py`, `LICENSE` (MIT, `Copyright (c) 2026 Benjamin Swanepoel`; the public repository has none yet)
- Test: `tests/__init__.py` (empty), `tests/test_yamlsub.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `class YamlError(Exception)` with attributes `line: int` (1-based) and `reason: str`; `str(e) == f"line {line}: {reason}"`.
  - `parse(text: str) -> object` returning `dict` (insertion-ordered, `str` keys), `list`, `str`, `int`, `bool` or `None`. An empty or comment-only document returns `None`.
  - `load(path: str, shown: str) -> object`: reads bytes, strips one leading UTF-8 BOM, decodes UTF-8 (failure raises `YamlError(0, f"{shown}: not valid UTF-8")`), normalises `\r\n` to `\n`, and calls `parse`. Every `YamlError` from it carries `shown` in the reason prefix.
  - `emit(value: object) -> str`: canonical text ending in one `\n`.
  - `class EmitError(ValueError)` for values `emit` cannot write (floats, empty dict, non-str keys, other types).

The grammar the tests pin:
- Block mappings `key: value`; keys are plain or quoted scalars and always `str`.
- Block sequences `- item`, at the parent key's indent or deeper. `- key: v` starts a mapping inside the item.
- Flow sequences of scalars only: `[a, "b c", 1]`, `[]`.
- Scalars: plain, `'single'` (`''` escapes a quote), `"double"` (escapes `\\ \" \n \t \uXXXX` only).
- Block scalars `|` and `|-` only.
- `true`/`false` are booleans, `null`/`~` and an empty value are `None`, `-?(0|[1-9][0-9]*)` is an int. Every other plain scalar is a `str`, including `yes`, `on`, `1.0`, `007` and dates.
- ` #` starts a comment outside quotes. A plain value may not start with `& * ! > { % @ \``.

Refused, each a `YamlError` with the line: anchors (`&`), aliases (`*`), tags (`!`), merge keys (`<<`), duplicate keys, a tab in indentation, flow mappings (`{`), `>` folded scalars, `---` or `...` lines, inconsistent indentation.

Canonical emit: 2-space indent; lists of mappings as `- key: v` with continuation keys indented 2 more; empty list as `[]`; strings quoted with double quotes only when a plain scalar would not re-parse as the same `str`; multi-line strings as `|` (ending `\n`) or `|-` (no trailing `\n`), otherwise double-quoted with escapes.

- [ ] **Step 1: Write the failing tests** in `tests/test_yamlsub.py`, class `TestParse` / `TestRefuse` / `TestEmit`:

```python
def test_mapping_sequence_and_scalars(self):
    text = "a: 1\nb: [x, \"y z\"]\nc:\n  - k: v\n    n: null\nd: |\n  line1\n  line2\n"
    self.assertEqual(parse(text), {"a": 1, "b": ["x", "y z"], "c": [{"k": "v", "n": None}], "d": "line1\nline2\n"})

def test_ambiguous_plain_scalars_are_strings(self):
    for s in ["yes", "no", "on", "off", "2026-10-31", "1.0", "0.1.0", "007", "True", "NULL"]:
        self.assertEqual(parse(f"k: {s}\n"), {"k": s}, s)
        self.assertEqual(parse(emit({"k": s})), {"k": s}, s)

def test_sequence_at_parent_indent(self):
    self.assertEqual(parse("a:\n- 1\n- 2\n"), {"a": [1, 2]})

def test_comments_and_empty_document(self):
    self.assertEqual(parse("# only\n\n"), None)
    self.assertEqual(parse("a: b # note\nc: 'd # not'\n"), {"a": "b", "c": "d # not"})

def test_crlf_and_bom_accepted(self):   # via load() on a temp file holding b"\xef\xbb\xbfa: 1\r\nb: 2\r\n"
    ...  # assert == {"a": 1, "b": 2}

def test_invalid_utf8_names_file(self):  # load(p, "state/x.yml") on b"a: \xff\n"
    ...  # assertRaises YamlError; "state/x.yml" in str(err) and "not valid UTF-8" in str(err)
```

`TestRefuse`: one test per refusal above, each asserting `YamlError` and the exact `line`. For example, `test_duplicate_key` parses `"a: 1\nb: 2\na: 3\n"` and expects line 3, with `"duplicate key 'a'"` in the reason. Another: `test_tab_indent` (`"a:\n\t- 1\n"` gives line 2).

`TestEmit`: `test_round_trip_corpus` covers a list of about 30 values (nested lists of mappings, strings with `: `, ` #`, leading `-`, quotes, unicode, `\t`, trailing newlines, empty strings, `[]`) and asserts `parse(emit(v)) == v` and `emit(parse(emit(v))) == emit(v)`. Also `test_emit_refuses_float_and_empty_dict`.

- [ ] **Step 2: Run tests, expect FAIL** with `ModuleNotFoundError: No module named 'gates.lib.yamlsub'`.
- [ ] **Step 3: Implement `gates/lib/yamlsub.py`.** Use a line-based recursive-descent parser: pre-split into `(lineno, indent, content)` tuples, skipping blank and comment-only lines except inside block scalars, then parse a node at an indent.
- [ ] **Step 4: Fuzz check.** Add `test_fuzz_never_crashes`: 2000 random documents from a seeded `random.Random(1)` over the grammar's tokens. `parse` either returns or raises `YamlError`, never any other exception, and every accepted value round-trips.
- [ ] **Step 5: Run tests, expect PASS** (all of `tests/test_yamlsub.py`).
- [ ] **Step 6: Commit** `feat(lib): strict YAML subset parser and emitter`, then checkpoint (ledger line + handoff).

### Task 1a.2: result contract, config loader, git helpers

**Files:**
- Create: `gates/lib/result.py`, `gates/lib/config.py`, `gates/lib/gitinfo.py`, `gates/__main__.py`
- Test: `tests/helpers.py`, `tests/test_result.py`, `tests/test_config.py`, `tests/test_gitinfo.py`

**Interfaces:**
- Consumes: `yamlsub.load`, `YamlError`.
- Produces:
  - `result.py`: `@dataclass Line(status: str, id: str, reason: str = "")`, `@dataclass Result(gate: str, lines: list)` with `ok()`, `fail(id, reason)`, `passed(id)`, `render(as_json: bool) -> str`; `class GateError(Exception)`; `gate_args(prog: str) -> argparse.ArgumentParser` (adds `--root`, help to stderr); `run_check(name, check, args) -> Result` and `run_gate(name, check, argv=None) -> int` behave as lap-timer's (`--json` only as argv[0]; SystemExit, exceptions and an empty Result become FAIL lines; help is `<name>.input: help requested; no gate was run`); `repo_root() -> str` (`CLAUDE_PROJECT_DIR`, else `git rev-parse --show-toplevel`, else `GateError`); `safe_text(s: str) -> str` escapes non-printables in line ids.
  - `config.py`: `CONFIG_PATH = ".strict-delivery/config.yml"`; `DEFAULTS: dict` holding spec §5 paths (`paths.state = ".strict-delivery/state"`, `paths.reports = ["docs/strict-delivery/reviews"]`, `paths.plans = ".strict-delivery/state/plans"`, `paths.specs = "docs/strict-delivery/specs"`, `paths.docs_plans = "docs/strict-delivery/plans"`, `paths.index = "docs/strict-delivery/INDEX.md"`), `ids = {decision: {prefix: "DEC", width: 4}, finding: {prefix: "F", width: 4}, claim: {prefix: "C", width: 4}}`, `state.shard_size = 50`, `decision_classes.owner_only = ["triage", "spec-direction", "scope", "merge-grant", "model-policy", "issue-close", "finding-class", "rule-override"]`, `decisions.scan = ["docs/*", "CLAUDE.md", ".strict-delivery/state/plans/*"]`; `load(root: str) -> dict` (a deep merge of the file over `DEFAULTS`; requires `framework_version` (str), `profile` in `light|standard|strict`, non-empty `owner.handle`, `state.shard_size` a positive int; a missing file raises `GateError(".strict-delivery/config.yml: missing; run /strict-delivery:init")`; a YAML error raises `GateError` with the file and line).
  - `gitinfo.py` (ported from lap-timer `tools/gates/lib/gitinfo.py`, C locale, messages naming the command, never the directory): `head_sha(root) -> str`, `commit_exists(root, sha) -> bool`, `tracked_files(root) -> frozenset` (index entries with mode 100644/100755 only), `show(root, ref, path) -> Optional[str]` (`None` when the path is absent at `ref`).
  - `__main__.py`: `COMMANDS: dict[str, Callable[[list], int]]`; `main(argv) -> int` dispatches `argv[0]` and returns 2 with usage on stderr for an unknown command. Block 1 registers `check` (`check <gate> [args]`), `decisions`, `findings` and `index` as the later tasks land.
  - `tests/helpers.py`: `make_repo(tmp: str, config: Optional[dict] = None) -> str` (git init, writes `emit(config or minimal_config())` to `.strict-delivery/config.yml`, commits with a fixed author and date); `minimal_config() -> dict` (`framework_version: "0.0.0"`, `profile: strict`, `owner: {handle: owner-x}`); `commit_all(root, msg) -> str` returns the sha.

- [ ] **Step 1: Write the failing tests.**
  - `test_result.py`: `test_empty_result_fails_empty`; `test_exception_becomes_input_fail`; `test_json_only_as_first_arg`; `test_newline_in_reason_is_one_line`.
  - `test_config.py`: `test_defaults_merged` (minimal config gives `cfg["state"]["shard_size"] == 50` and `cfg["paths"]["state"] == ".strict-delivery/state"`); `test_missing_config_names_init` (`GateError` whose message contains `/strict-delivery:init`); `test_bad_profile`; `test_empty_owner_handle`; `test_yaml_error_names_file_and_line`.
  - `test_gitinfo.py`: `test_head_and_commit_exists`; `test_untracked_file_not_in_tracked`; `test_show_absent_path_is_none`; `test_not_a_repo_is_gate_error`.
- [ ] **Step 2: Run, expect FAIL** (modules missing).
- [ ] **Step 3: Implement the three modules and `__main__.py`.**
- [ ] **Step 4: Run, expect PASS** for the whole suite.
- [ ] **Step 5: Commit** `feat(lib): gate result contract, config loader, git helpers`, then checkpoint.

### Task 1a.3: sharded record store

**Files:**
- Create: `gates/lib/store.py`
- Test: `tests/test_store.py`

**Interfaces:**
- Consumes: `yamlsub.load/emit`, `config.load`, `result.GateError`.
- Produces:
  - `@dataclass(frozen=True) IdScheme(prefix: str, width: int)` with `pattern` (`re.compile(rf"{prefix}-[0-9]{{{width}}}")`), `number(id: str) -> int` (raises `ValueError` on no fullmatch), `format(n: int) -> str`.
  - `shard_name(scheme: IdScheme, n: int, size: int) -> str`: `start = (n - 1) // size * size + 1`, `f"{prefix}-{start:0{w}d}-{start + size - 1:0{w}d}.yml"`. `shard_name(DEC4, 137, 50) == "DEC-0101-0150.yml"`, `shard_name(DEC4, 50, 50) == "DEC-0001-0050.yml"`.
  - `@dataclass(frozen=True) Record(id: str, row: dict, location: str, file: str)`, where `location` is `"open"` or `"resolved"` and `file` is repo-relative.
  - `SCHEMA = 1`. Every state file is a top-level mapping carrying `schema: 1` (spec §15): an open file is `{schema, record: <row>}`, a shard is `{schema, records: [<row>, ...]}`. A different or missing `schema` is a `GateError` naming the file. Migrations arrive with `upgrade` in block 4.
  - `class Store` with `__init__(self, root: str, kind: str, cfg: dict)` (kind `"decisions"` or `"findings"`; directory `<paths.state>/<kind>`, scheme from `ids.decision` or `ids.finding`); `load() -> list[Record]` (each `open/*.yml` file holds one row, each `resolved/*.yml` file a list of rows; a missing kind directory is an empty store; an unparsable file or a wrong top-level type is a `GateError` naming the file); `next_id(records) -> str` (max + 1, `DEC-0001` when empty); `write_open(row: dict) -> str` (writes `open/<id>.yml`, returns the path); `resolve(id: str, row: dict) -> str` (removes `open/<id>.yml`, inserts `row` into its shard sorted by number, writes the shard canonically, returns the shard path).
  - `invariant_errors(records: list, scheme: IdScheme, size: int, is_resolved: Callable[[dict], bool]) -> list[tuple[str, str]]` returning `(line-id suffix, reason)` pairs. Suffixes and their conditions: `duplicate.<id>` (an id more than once across `open/` and `resolved/`; the reason lists every file and says "renumber the newer record"); `gap.<id>` (an id missing below the max); `name.<file>` (an open file name that is not its row id, or a shard row outside the shard's range); `location.<id>` (a resolved row in `open/` or an open row in `resolved/`); `order.<file>` (shard rows not sorted); `id.<file>` (a row id that does not fullmatch the scheme; the row is printed as `entry-<i>`).
  - `immutability_errors(root: str, store: Store, base: str) -> list[tuple[str, str]]`: for every resolved row present in the shard at `base` (`gitinfo.show`), the current row must equal it. Suffix `immutable.<id>`; reason `resolved rows are immutable; record the change as a new decision with supersedes: <id>` for decisions, and `...as a new finding` for findings.

- [ ] **Step 1: Write the failing tests:** `test_schema_key_required`; `test_shard_name_boundaries` (n = 1, 50, 51, 137, 9999); `test_load_open_and_resolved`; `test_resolve_out_of_order_lands_in_range_sorted` (resolve 3, then 1, into `DEC-0001-0050.yml`; rows read `[1, 3]`; the file is canonical `emit` output); `test_partial_shard_with_open_ids_ok`; `test_duplicate_across_open_files_and_shard` (Review Focus 3); `test_gap_detected`; `test_open_file_name_mismatch`; `test_row_in_wrong_shard`; `test_resolved_row_in_open`; `test_unsorted_shard`; `test_malformed_id_prints_entry_index`; `test_immutability_detects_edit_and_allows_new_rows`.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement `gates/lib/store.py`.**
- [ ] **Step 4: Run, expect PASS** for the whole suite.
- [ ] **Step 5: Commit** `feat(lib): sharded record store with invariants`, then checkpoint. **Block 1a end:** final reviewer (opus) and top-tier verifier on `block/b1a`; ask the owner for a merge grant (in chat; the decision log does not exist yet; ledger the grant); merge as its own command; checkpoint; stop for `/clear`.

---

## Block 1b: schemas and gates

### Task 1b.1: decision schema and queries

**Files:**
- Create: `gates/lib/decisions.py`
- Test: `tests/test_decisions_lib.py`

**Interfaces:**
- Consumes: `store.Store`, `Record`, `IdScheme`, `config.load`.
- Produces:
  - `DECISION_KEYS = ["id", "class", "question", "options", "asked_at", "asked_by", "topics", "applies_to", "checked_against", "effect"]` (required); `OPTIONAL_KEYS = ["supersedes", "answer", "answered_at", "landed_in", "withdrawn"]`.
  - Field rules (spec §7.1). `class` is in `cfg.decision_classes.owner_only`. `options` is a list of `{label, cost}` with non-empty strings and at least 2 entries, except class `merge-grant`, whose question matches `grant:<plan>( .*)?` and which may carry one option. `asked_at` and `answered_at.at` are 7-40 hex commit shas. `asked_by` is a non-empty string. `topics` is a list of strings. `applies_to` is a list of path globs. `checked_against` is a list of ids in the scheme. `effect` is `lasting` or `one-off`. `supersedes` is an id or absent. `answer` and `answered_at{at, by}` are both set or both absent, and `answered_at.by == cfg.owner.handle`. `landed_in` is a non-empty list of repo-relative paths (optionally `#anchor`), required when answered and `effect: lasting`, absent otherwise. `withdrawn{at, by, reason}` has `by` equal to the owner handle and excludes `answer`.
  - `validate(row: dict, cfg: dict) -> list[str]`, each error `"<field>: <problem>"`; errors from the owner check start with `OWNER_ERROR = "owner: only the owner"`.
  - `is_resolved(row) -> bool` (answered or withdrawn); `is_open(row) -> bool`.
  - `superseded_ids(records) -> set[str]`; `in_force(records) -> list[Record]` (answered, `effect: lasting`, not superseded, not withdrawn, class not `merge-grant`); `current(records, id) -> str` (follows `supersedes` chains forward to the newest id).
  - `find(records, terms: list[str], path: Optional[str], topic: Optional[str], include_all: bool) -> list[Record]`: case-insensitive term match over question, answer and topics; `path` matched with `fnmatch` against `applies_to`; superseded hits are replaced by `current(...)`; in force only unless `include_all`.

- [ ] **Step 1: Write the failing tests:** `test_valid_open_and_answered_rows`; `test_non_owner_answer_is_owner_error`; `test_one_option_refused_except_grant`; `test_lasting_answer_needs_landed_in`; `test_one_off_must_not_have_landed_in`; `test_withdrawn_by_owner_is_resolved`; `test_unknown_class_uses_config_list` (a config adding `hardware` accepts it); `test_in_force_excludes_superseded_grants_one_off`; `test_find_follows_supersedes_chain` (DEC-0001 superseded by 0003, superseded by 0007, so `find` returns 0007 only); `test_find_by_path_glob_and_topic`.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement `gates/lib/decisions.py`.**
- [ ] **Step 4: Run, expect PASS.**
- [ ] **Step 5: Commit** `feat(lib): decision schema, in-force and find`, then checkpoint.

### Task 1b.2: gate_decisions

**Files:**
- Create: `gates/gate_decisions.py`; Modify: `gates/__main__.py` (register `check decisions`)
- Test: `tests/test_gate_decisions.py`

**Interfaces:**
- Consumes: `decisions.*`, `store.*`, `gitinfo.*`, `result.*`, `config.load`.
- Produces: `check(args: list) -> Result` (gate name `decisions`) and `main(argv=None) -> int`. Arguments: `--root`, `--base REF` (default `HEAD`; immutability baseline), `--scan PATH...` (extra files). Line-id categories, each printing one `PASS decisions.<cat>` when nothing in it failed or was skipped: `schema`, `owner`, `store` (invariant errors as `decisions.store.<suffix>`), `immutable`, `landed` (each `landed_in` path is a tracked file at `--root` that contains the decision id), `refs` (`supersedes` names an existing resolved, answered row; `checked_against` ids exist), `open-ref` (no tracked file matching `decisions.scan`, plus `--scan`, and outside `<paths.state>/decisions/` contains the id of an open decision; the reason is `<file>:<line> references unanswered <id>; the owner answers it first`), `scan` (an unreadable scan path fails here and withholds the `open-ref` PASS).

- [ ] **Step 1: Write the failing tests.** Each builds a repo with `helpers.make_repo` and writes records through `Store`. Tests: `test_empty_registers_pass_every_category_except_skipped`; `test_non_owner_answer_fails_owner`; `test_edited_resolved_row_fails_with_remedy` (Review Focus 4: commit an answered row, edit its `answer`, run with `--base HEAD`, expect `FAIL decisions.immutable.DEC-0001` with `supersedes` in the reason); `test_lasting_landed_in_must_cite_id`; `test_supersedes_open_row_fails_refs`; `test_open_ref_in_docs_fails`; `test_open_ref_in_untracked_file_ignored`; `test_answered_ref_passes`; `test_missing_config_is_input_fail`; `test_json_output_shape`.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement `gates/gate_decisions.py`.** Port the skip and category logic from lap-timer `tools/gates/gate_decisions.py`; the owner handle comes from the target root's config, never from the code checkout.
- [ ] **Step 4: Run, expect PASS.**
- [ ] **Step 5: Commit** `feat(gates): gate_decisions`, then checkpoint.

### Task 1b.3: finding schema, gate_register, self-adoption of both gates

**Files:**
- Create: `gates/lib/findings.py`, `gates/gate_register.py`, `.strict-delivery/config.yml`, `.strict-delivery/state/decisions/open/.gitkeep`, `.strict-delivery/state/findings/open/.gitkeep`; Modify: `gates/__main__.py` (register `check register`)
- Test: `tests/test_findings_lib.py`, `tests/test_gate_register.py`

**Interfaces:**
- Consumes: `store.*`, `decisions.is_resolved/validate`, `gitinfo.*`, `result.*`.
- Produces:
  - `findings.py`. `STATES = ["open", "planned", "in-progress", "fixed-unpinned", "pinned", "deferred", "closed", "merged"]`; `RESOLVED_STATES = {"closed", "merged"}`; `TRANSITIONS` is lap-timer's table verbatim (`tools/gates/lib/registers.py` `FINDING_TRANSITIONS`); `SEVERITIES = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]`. Keys: `id, source, severity, class, siblings, cites, repro, owner, state, pin, ruling, evidence, history`, plus optional `parent` (an epic's id). `owner` is `{kind: plan, plan, task} | {kind: issue, number} | {kind: roadmap, plan}`. `pin` is null or `{test, transcript}`: `test` is an opaque non-empty string with no pattern (spec §13a), and `transcript` is a tracked file under `<paths.plans>/<plan>/mutations/`, or `<sha>:<path>` naming one at a commit. `history` entries are `{state, sha, by}`; the last entry's state equals `state`; `merged` only `by: postmerge`. `validate(row, cfg) -> list[str]`, `transition_errors(row) -> list[str]`, `evidence_errors(row, root, cfg, decision_records, tracked) -> list[str]` (lap-timer rules minus `PIN_TEST`: deferred needs `ruling` naming a resolved, owner-answered decision; closed needs evidence; pinned needs a pin and a report path. Evidence and pin paths may be a tracked file at HEAD or `<sha>:<path>`, where the sha names a commit and `git cat-file -e <sha>:<path>` succeeds, so pruned plan workspaces stay valid evidence after merge (spec §5 lean tree)), `epic_errors(records) -> list[tuple[str, str]]` (a `parent` must exist; a parent in `closed` or `merged` with a child not resolved fails), `is_resolved(row) -> bool`.
  - `gate_register.py`: `check(args)` (gate name `register`) with `--root` and `--base`. Categories: `schema`, `owner`, `store`, `immutable`, `transition`, `evidence`, `epic`, `report`, `marker`. Registered-report scanning is ported from lap-timer `gate_register.registered_reports`/`report_ids`; directories come from `cfg.paths.reports`, a missing directory is no reports (not a FAIL), and ids are matched with the finding scheme.
  - This repository's `.strict-delivery/config.yml`: `framework_version: "0.0.0"`, `profile: strict`, `owner: {handle: superbrobenji}`; every other key defaults.

- [ ] **Step 1: Write the failing tests.**
  - `test_findings_lib.py`: `test_valid_finding`; `test_missing_owner`; `test_pin_test_is_opaque` (`"npx jest -t 'adds totals'"` is accepted); `test_transcript_must_be_tracked_under_plans`; `test_evidence_sha_path_form` (a `<sha>:<path>` naming a file at a real commit passes after the file is deleted from HEAD; a bad sha, a missing path at that sha, or a malformed form fails); `test_illegal_transition`; `test_merged_only_by_postmerge`; `test_deferred_needs_answered_ruling`; `test_epic_closed_with_open_child_fails`.
  - `test_gate_register.py`: `test_empty_registers_pass`; `test_closed_finding_in_open_dir_fails_store_location`; `test_report_cites_unknown_finding`; `test_near_miss_marker_fails`; `test_missing_report_dir_is_fine`; `test_edited_resolved_finding_fails_immutable`.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement `findings.py` and `gate_register.py`.**
- [ ] **Step 4: Run, expect PASS** for the whole suite.
- [ ] **Step 5: Self-adopt.** Write this repository's config and empty state directories. Run `python3 -m gates check decisions` and `python3 -m gates check register` on this repository; expect every line `PASS` and exit 0.
- [ ] **Step 6: Commit** `feat(gates): finding schema, gate_register; enable both gates on this repository`, then checkpoint with `gates=PASS`. **Block 1b end:** as in block 1a.

---

## Block 1c: tools

### Task 1c.1: decisions ask, decide, withdraw, find

**Files:**
- Create: `gates/tools/__init__.py`, `gates/tools/decisions_cli.py`; Modify: `gates/__main__.py` (register `decisions`)
- Test: `tests/test_decisions_cli.py`

**Interfaces:**
- Consumes: `Store`, `decisions.*`, `gitinfo.head_sha`, `config.load`, and `index.regenerate` from Task 1c.2. Until then, 1c.1 calls a stub `regenerate(root, cfg) -> list[str]` defined in `gates/tools/index.py` that returns `[]`.
- Produces: `main(argv: list) -> int` for `python3 -m gates decisions <sub>`:
  - `ask --class C --question Q --option "LABEL::COST" (repeat) --topic T (repeat) --applies-to GLOB (repeat) --effect lasting|one-off [--supersedes ID] --by WHO [--root R]`. It runs `find` over the topics, paths and question words; prints `candidate <id>: <question>` lines; writes the open record with `checked_against` = those candidate ids, `asked_at` = HEAD sha and `asked_by` = WHO; validates before writing (exit 1 and nothing written on any error); prints the new id last.
  - `decide ID --answer TEXT [--landed-in CITE (repeat)] --by HANDLE`. Refused (exit 1) when HANDLE is not the owner handle, the id is not open, or validation fails. Otherwise it sets `answer` and `answered_at{at: HEAD, by}`, calls `Store.resolve`, then regenerates the indexes.
  - `withdraw ID --reason R --by HANDLE`: owner only, sets `withdrawn{at, by, reason}`, resolves, regenerates.
  - `find TERM... [--path P] [--topic T] [--all]`: prints `<id> [<topics>] <question> -> <answer>` lines; exit 0 even with no hits.

- [ ] **Step 1: Write the failing tests:** `test_ask_writes_open_record_with_candidates`; `test_ask_invalid_writes_nothing`; `test_decide_by_non_owner_refused`; `test_decide_moves_to_shard`; `test_decide_lasting_without_landed_in_refused`; `test_withdraw_owner_only`; `test_find_in_force_default_and_all`; `test_gate_decisions_passes_after_ask_and_decide` (an end-to-end run through the CLI followed by `gate_decisions.check`).
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement `decisions_cli.py`.**
- [ ] **Step 4: Run, expect PASS.**
- [ ] **Step 5: Commit** `feat(tools): decisions ask, decide, withdraw, find`, then checkpoint.

### Task 1c.2: findings new/move, indexes, in-force.md

**Files:**
- Create: `gates/tools/findings_cli.py`; Modify: `gates/tools/index.py` (replace the stub), `gates/__main__.py` (register `findings`, `index`)
- Test: `tests/test_findings_cli.py`, `tests/test_index.py`

**Interfaces:**
- Consumes: `Store`, `findings.*`, `decisions.in_force`, `yamlsub.emit`.
- Produces:
  - `findings_cli.main(argv) -> int`. `new --source S --severity SEV --class TEXT --owner-kind K (--plan P --task T | --number N) [--parent ID] [--cite FILE:LINES@SHA ...] --by WHO` writes an open record with history `[{open, HEAD, WHO}]`. `move ID --to STATE --by WHO [--evidence E ...] [--ruling DEC] [--pin-test T --pin-transcript PATH]` refuses illegal transitions, appends history and resolves into the shard when STATE is in `RESOLVED_STATES`.
  - `index.py`: `regenerate(root: str, cfg: dict) -> list[str]` writes `<state>/decisions/index.yml` (mapping id to `{file, status (open|answered|withdrawn|superseded), class, topics}`), `<state>/findings/index.yml` (id to `{file, state, severity, owner}`) and `<state>/decisions/in-force.md` (a header line `# In-force decisions (generated; do not edit)`, then one line per in-force decision: `- <id> [<topics>] <first line of answer> -- landed_in: <cites>`). It returns the paths written. `stale(root, cfg) -> list[str]` returns the generated files whose content differs from a fresh render. CLI `index [--check]`: `--check` exits 1 listing stale files and writes nothing. The generated files are git-ignored (spec §5 lean tree): this task adds them to this repository's `.gitignore`, and a test asserts that `regenerate` output is never tracked.

- [ ] **Step 1: Write the failing tests:** `test_new_and_move_through_lifecycle_to_closed_shard`; `test_move_illegal_transition_refused`; `test_move_deferred_needs_ruling`; `test_index_lists_every_record`; `test_in_force_md_excludes_superseded_and_grants`; `test_index_check_detects_stale`; `test_regenerate_is_idempotent` (two runs give byte-identical files); `test_gate_register_passes_after_cli_lifecycle`.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement both modules.**
- [ ] **Step 4: Run, expect PASS** for the whole suite. Run `python3 -m gates check decisions`, `python3 -m gates check register` and `python3 -m gates index --check` on this repository; expect all to pass.
- [ ] **Step 5: Commit** `feat(tools): findings new/move, indexes, in-force.md`, then checkpoint. **Block 1c end:** the final review package; the merge grant is now recorded with `decisions ask --class merge-grant --question grant:b1c` and answered by the owner.

---

## Later blocks (outline; each gets its own detailed plan section before it starts)

- **Block 2:** `gate_claims` (per-document `claims/<doc-slug>.yml`, direct and contra commands, staleness from cited paths at `verified_at`); `gate_dispatch` (spec §10 grammar, tier rank from `models.tiers`, `top_tier_roles`, fork refused); `run_all` driven by profile; git hook shims (one-line sh exec of `python3 -m gates`) and installer; the CI workflow for this repository (3.9 and 3.13, ubuntu and macOS); this repository runs `run_all` in pre-commit from here.
- **Block 3:** plugin packaging (`.claude-plugin/plugin.json`, `marketplace.json`); skill `SKILL.md`; role prompt blocks; base playbook (spec §8 rules as `SD-R<n>`); Claude Code hooks as `python3 -m gates hook <event>` (SessionStart, UserPromptSubmit, PreToolUse Agent/Bash/Edit-Write, PostToolUse Read), with the Bash branch also refusing `decisions decide` and `withdraw` from agents.
- **Block 4:** `init` (stack command detection that only proposes, answers file for non-interactive runs, the no-overwrite rule, migration of existing `docs/superpowers/` specs and plans with `git mv` and reference rewrite), `doctor`, `upgrade` with schema migrations, templates (CLAUDE.md managed block, CI workflow pinned to a tag), profiles `light/standard/strict.yml`, fixture repositories (node, rust, go, python, C/make, empty, monorepo).
- **Block 5:** `gate_context` and read receipts, `gate_cites`, `gate_drift`, `gate_index` (indexes regenerate without error; a tracked generated file fails), `gate_streams`.
- **Block 6:** `gate_checkpoint`, `gate_evidence` (spec §13a), profile end-to-end tests, release script, `CHANGELOG.md`, tag `v0.1.0`.

Each later block is split to at most 3 tasks per sub-block, as block 1 is.
