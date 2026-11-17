"""Tests for the decision schema and rules (gates.lib.decisions) through the production call paths: rows are
written with ``write_record`` and read back with ``yamlsub.load``; ``landed_errors`` runs on real git
repositories. Expected error lists are written out literally, never derived from the code under test."""
import ast
import copy
import os
import unicodedata
import unittest

from unittest import mock

from gates.lib import config, decisions, gitinfo, migrations, schema, yamlsub
from gates.lib.decisions import (FIXED_RULES, KNOWN_RULES, current, find, in_force, is_resolved, landed_errors,
                                 ref_errors, superseded_ids, validate)
from gates.lib.migrations import migrate
from gates.lib.result import GateError, Result, run_check
from gates.lib.store import Record
from tests.helpers import GitIsolatedTestCase, commit_all, make_repo, write_record
from tests.test_fold_table import FORTY, FORTY_TARGET_313

# The tag of every record built here comes from the schema it is checked against, never a literal (Global
# Constraints "Test fixtures"; Q-2a1-3 (a), Q-RCp-3 (a)). Literal tags below are old-version refusal tests or
# wrong or malformed tags, which are exempt.
TAG = "decision/%d" % migrations.current_version("decision")
A = "DEC-20261031-k3f9"
B = "DEC-20261031-m4n5"
C = "DEC-20261031-p6q7"
D = "DEC-20261031-r8s9"
OPT = {"label": "yes", "cost": "none"}
OPT2 = {"label": "no", "cost": "some"}
W = {"at": "a1b2c3d", "by": "who@example.invalid", "reason": "asked twice"}
AT = {"at": "b2c3d4e", "by": "who@example.invalid"}
SPEC_ERR = ("landed_in: docs/strict-delivery/specs/x.md is a spec; specs are cleaned, land the rule in a "
            "playbook, CLAUDE.md or architecture.md")
OPEN = {"schema": TAG, "id": A, "status": "open", "class": "scope", "question": "Keep X?",
        "options": [OPT, OPT2], "asked_at": "a1b2c3d", "asked_by": "agent", "topics": ["ids"],
        "applies_to": ["src/*"], "checked_against": [], "effect": "lasting"}
ANSWERED = {**OPEN, "status": "answered", "answer": "Yes", "answered_at": AT, "rule": "Keep X.",
            "landed_in": ["CLAUDE.md"]}
WITHDRAWN = {**OPEN, "status": "withdrawn", "withdrawn": W}
GRANT = {**OPEN, "class": "merge-grant", "plan": "p"}
OVERRIDE = {**OPEN, "class": "rule-override", "overrides": "SD-R2"}
OPEN2 = {**OPEN, "options": [{"label": "a", "cost": "x"}, {"label": "b", "cost": "y"}]}
MODEL2 = {**OPEN2, "class": "model-policy"}
OPTIONAL_FIELDS = ("overrides", "recommended", "source")

# gates/schemas/decision.yml at version 1 (main 13ca17e), byte for byte: Task 2a.1 keeps every field (S2).
DECISION_1_HEAD = """kind: decision
version: 1
format: yaml
files:
  - dir: decisions
    glob: "*.yml"
    exclude:
      - index.yml
fields:
  schema:
    type: str
  id:
    type: id
    id_kind: decision
  status:
    type: enum
    values:
      - open
      - answered
      - withdrawn
  class:
    type: str
  question:
    type: str
  options:
    type: list
    min: 2
    items:
      type: map
      fields:
        label:
          type: str
        cost:
          type: str
  asked_at:
    type: sha
  asked_by:
    type: str
  topics:
    type: list
    items:
      type: str
  applies_to:
    type: list
    items:
      type: glob
  checked_against:
    type: list
    items:
      type: id
      id_kind: decision
  effect:
    type: enum
    values:
      - lasting
      - one-off
  supersedes:
    type: id
    id_kind: decision
    required: false
  answer:
    type: str
    required_when:
      - status:
          - answered
    absent_when:
      - status:
          - open
          - withdrawn
  answered_at:
    type: map
    required_when:
      - status:
          - answered
    absent_when:
      - status:
          - open
          - withdrawn
    fields:
      at:
        type: sha
      by:
        type: str
  rule:
    type: str
    required: false
    absent_when:
      - status:
          - open
          - withdrawn
  withdrawn:
    type: map
    required_when:
      - status:
          - withdrawn
    absent_when:
      - status:
          - open
          - answered
    fields:
      at:
        type: sha
      by:
        type: str
      reason:
        type: str
  plan:
    type: str
    required_when:
      - class:
          - merge-grant
  program:
    type: str
    required: false
  stream:
    type: str
    required: false
  landed_in:
    type: list
    min: 1
    items:
      type: cite
    required_when:
      - status:
          - answered
        effect:
          - lasting
    absent_when:
      - effect:
          - one-off
      - status:
          - open
      - status:
          - withdrawn
"""
NEW_FIELDS = """  overrides:
    type: str
    required: false
  recommended:
    type: str
    required: false
  source:
    type: str
    required: false
"""


def drop(row, *keys):
    return {k: v for k, v in row.items() if k not in keys}


def cfg_default():
    return copy.deepcopy(config.DEFAULTS)


class RowTestCase(GitIsolatedTestCase):
    def setUp(self):
        super().setUp()
        self.cfg = cfg_default()

    def rt(self, row):
        """The row as the gates see it: written by write_record, read back by yamlsub.load."""
        write_record(self.work, "r.yml", row)
        return yamlsub.load(os.path.join(self.work, "r.yml"), "r.yml")

    def v(self, row):
        return validate(self.rt(row), self.cfg)


class SchemaFileTests(RowTestCase):
    def test_schema_file_loads_and_declares_files(self):  # S1, S2, S4, S5
        s = schema.load_schema(os.path.join(schema.SCHEMAS_DIR, "decision.yml"))
        self.assertEqual((s.kind, s.version, s.format), ("decision", 2, "yaml"))
        self.assertEqual(s.files, [{"dir": "decisions", "glob": "*.yml", "exclude": ["index.yml"]}])
        self.assertEqual(s.fields["schema"], {"type": "str"})
        for key in ("overrides", "recommended", "source"):  # S3, S5, S6 (Task 2a.1)
            with self.subTest(key):
                self.assertEqual(s.fields[key], {"type": "str", "required": False})

    def test_version_1_fields_unchanged(self):  # S2 (Task 2a.1): every decision/1 field spec is as it was
        with open(os.path.join(schema.SCHEMAS_DIR, "decision.yml"), encoding="utf-8") as fh:
            text = fh.read()
        self.assertTrue(text.startswith(DECISION_1_HEAD.replace("version: 1\n", "version: 2\n")), text[:200])
        tail = text[len(DECISION_1_HEAD):]
        self.assertEqual(tail, NEW_FIELDS)

    def test_files_of_register_dir(self):  # S3
        make_repo(self.work)
        d = ".strict-delivery/state/decisions/"
        for name in (A + ".yml", "index.yml", "in-force.md", ".x.yml"):
            write_record(self.work, d + name, {"k": "v"})
        s = schema.load_schema(os.path.join(schema.SCHEMAS_DIR, "decision.yml"))
        self.assertEqual(schema.files_of(s, self.work, self.cfg), [d + ".x.yml", d + A + ".yml"])

    def test_valid_open_and_answered_rows(self):
        for name, row in (("open", OPEN), ("answered", ANSWERED), ("withdrawn", WITHDRAWN), ("grant", GRANT)):
            with self.subTest(name):
                self.assertEqual(self.v(row), [])

    def test_unknown_key_and_schema_tag(self):  # S6, S7; T4 (malformed tags are exempt literals)
        self.assertEqual(self.v({**OPEN, "zzz": "SD-R1"}), ["zzz: unknown key"])
        self.assertEqual(validate({**OPEN, "schema": "finding/1", "class": "style", "plan": "a/b"}, self.cfg),
                         ["schema: expected decision/2, got finding/1"])
        self.assertEqual(validate(drop({**GRANT, "class": "style"}, "schema"), self.cfg),
                         ["schema: expected decision/2, got (missing)"])

    def test_decision_1_tag_names_upgrade(self):  # T1 (old-version refusal: exempt literal)
        self.assertEqual(validate({**OPEN, "schema": "decision/1"}, self.cfg),
                         ["schema: expected decision/2, got decision/1; run /strict-delivery:upgrade"])
        # only the tag error: the class, grant and new-field rules do not run on an old row
        bad = {**OPEN, "schema": "decision/1", "class": "style", "plan": "a/b", "overrides": "SD-R3",
               "recommended": "zz", "source": ""}
        self.assertEqual(validate(bad, self.cfg),
                         ["schema: expected decision/2, got decision/1; run /strict-delivery:upgrade"])

    def test_current_tag_valid(self):  # T2
        self.assertEqual(OPEN["schema"], "decision/2")
        self.assertEqual(self.v(OPEN), [])

    def test_newer_tag_names_upgrade(self):  # T3 (exempt literal)
        bad = {**OPEN, "schema": "decision/3", "class": "style"}
        self.assertEqual(validate(bad, self.cfg),
                         ["schema: expected decision/2, got decision/3; run /strict-delivery:upgrade"])

    def test_malformed_tags_only_the_tag_error(self):  # T4 (exempt literals)
        class S(str):
            pass
        for got, shown in (("decision/2 ", "decision/2 "), (2, "2"), (None, "None"), (S("decision/2"), "decision/2"),
                           ("Decision/2", "Decision/2"), ("decision/02", "decision/02")):
            with self.subTest(repr(got)):
                row = {**OPEN, "schema": got, "class": "style", "overrides": "SD-R3", "source": ""}
                self.assertEqual(validate(row, self.cfg), ["schema: expected decision/2, got %s" % shown])

    def test_expected_tag_follows_the_schema_file(self):  # T5: never a literal
        with open(os.path.join(schema.SCHEMAS_DIR, "decision.yml"), encoding="utf-8") as fh:
            text = fh.read().replace("version: 2\n", "version: 3\n", 1)
        path = os.path.join(self.work, "decision.yml")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        with mock.patch.object(schema, "SCHEMAS_DIR", self.work), \
                mock.patch.object(decisions, "_loaded", [schema.load_schema(path)]):
            self.assertEqual(validate({**OPEN, "schema": "decision/3"}, self.cfg), [])
            self.assertEqual(validate({**OPEN, "schema": "decision/3", "class": "style"}, self.cfg),
                             ["class: style is not in decision_classes.owner_only"])
            self.assertEqual(validate({**OPEN, "schema": "decision/2", "class": "style"}, self.cfg),
                             ["schema: expected decision/3, got decision/2; run /strict-delivery:upgrade"])

    def test_top_level_not_a_mapping(self):  # T17
        for v in ([], None, "x", 1):
            with self.subTest(repr(v)):
                self.assertEqual(validate(v, self.cfg), ["top level: must be a mapping"])


class FieldTypeTests(RowTestCase):
    def check(self, key, value, expected, base=None):
        with self.subTest("%s=%r" % (key, value)):
            self.assertEqual(validate({**(base or OPEN), key: value}, self.cfg), expected)

    def test_id(self):  # T1
        self.check("id", A, [])
        self.check("id", "F-20261031-k3f9", ["id: id does not match the form; expected DEC-<YYYYMMDD>-<xxxx>: "
                                              "a valid calendar date and four characters from "
                                              "23456789abcdefghijkmnpqrstuvwxyz"])
        self.check("id", "DEC-20261031-K3F9", ["id: id does not match the form; expected DEC-<YYYYMMDD>-<xxxx>: "
                                                "a valid calendar date and four characters from "
                                                "23456789abcdefghijkmnpqrstuvwxyz"])
        self.check("id", "DEC-20261332-k3f9", ["id: id date 20261332 is not a valid calendar date; expected "
                                                "DEC-<YYYYMMDD>-<xxxx>: a valid calendar date and four "
                                                "characters from 23456789abcdefghijkmnpqrstuvwxyz"])
        self.assertEqual(len(validate({**OPEN, "id": 1}, self.cfg)), 1)
        self.cfg["ids"]["decision"] = "ADR"
        self.check("id", "ADR-20261031-k3f9", [])
        self.assertEqual(len(validate(OPEN, self.cfg)), 1)  # the DEC- id is now refused

    def test_status(self):  # T2
        for bad in ("Open", "closed", 1):
            with self.subTest(repr(bad)):
                errs = validate({**OPEN, "status": bad}, self.cfg)
                self.assertEqual(errs, ["status: must be one of open, answered, withdrawn"])
        self.assertEqual(validate(drop(OPEN, "status"), self.cfg), ["status: required key is missing"])

    def test_non_empty_strings(self):  # T3
        for key in ("class", "question", "asked_by"):
            for bad in ("", 1, None, ["x"]):
                with self.subTest("%s=%r" % (key, bad)):
                    errs = validate({**OPEN, key: bad}, self.cfg)
                    self.assertTrue(errs and errs[0].startswith(key + ":"), errs)
                    self.assertEqual([e for e in errs if "owner_only" in e], [])  # C5

    def test_topics_and_applies_to(self):  # T4, T5
        for key in ("topics", "applies_to"):
            self.check(key, [], [])
            self.check(key, ["x/**"], [])
            self.check(key, [""], [key + ".0: must be a non-empty " + ("string" if key == "topics" else "glob")])
            self.check(key, [1], [key + ".0: must be a non-empty " + ("string" if key == "topics" else "glob")])
            self.check(key, "x", [key + ": must be a list"])

    def test_checked_against(self):  # T6
        self.check("checked_against", [], [])
        self.check("checked_against", [B], [])
        self.check("checked_against", [A], [])  # its own id: no rule names it
        self.assertEqual(len(validate({**OPEN, "checked_against": ["F-20261031-k3f9"]}, self.cfg)), 1)
        self.assertEqual(len(validate({**OPEN, "checked_against": ["x"]}, self.cfg)), 1)

    def test_effect(self):  # T7
        self.check("effect", "one-off", [])
        self.check("effect", "one_off", ["effect: must be one of lasting, one-off"])
        self.assertEqual(validate(drop(OPEN, "effect"), self.cfg), ["effect: required key is missing"])

    def test_supersedes(self):  # T8
        self.assertEqual(validate(OPEN, self.cfg), [])
        self.check("supersedes", B, [])
        self.check("supersedes", A, [])  # self: ref_errors' business
        self.check("supersedes", None, ["supersedes: must not be null"])
        self.assertEqual(len(validate({**OPEN, "supersedes": "F-20261031-k3f9"}, self.cfg)), 1)

    def test_answer_and_rule_text(self):  # T9
        for bad in ("", 1):
            self.check("answer", bad, ["answer: must be a non-empty string"], ANSWERED)
            self.check("rule", bad, ["rule: must be a non-empty string"], ANSWERED)
        self.check("rule", "a\nb", [], ANSWERED)
        self.check("rule", "a | b", [], ANSWERED)

    def test_answered_at_sub_fields(self):  # T10
        base = ANSWERED
        self.check("answered_at", drop(AT, "by"), ["answered_at.by: required key is missing"], base)
        self.check("answered_at", {**AT, "x": 1}, ["answered_at.x: unknown key"], base)
        self.check("answered_at", {**AT, "by": ""}, ["answered_at.by: must be a non-empty string"], base)
        self.check("answered_at", {**AT, "by": "not an email"}, [], base)
        self.check("answered_at", ["x"], ["answered_at: must be a mapping"], base)

    def test_withdrawn_sub_fields(self):  # T11
        base = WITHDRAWN
        self.check("withdrawn", drop(W, "reason"), ["withdrawn.reason: required key is missing"], base)
        self.check("withdrawn", {**W, "by": ""}, ["withdrawn.by: must be a non-empty string"], base)
        self.check("withdrawn", {**W, "x": 1}, ["withdrawn.x: unknown key"], base)
        self.check("withdrawn", {**W, "at": "ABC1234"}, ["withdrawn.at: must be 7 to 40 lowercase hex digits"], base)

    def test_options_count_and_items(self):  # T12, T13
        for n, ok in ((0, False), (1, False), (2, True), (3, True)):
            with self.subTest(n):
                errs = validate({**OPEN, "options": [OPT] * n}, self.cfg)
                self.assertEqual(errs, [] if ok else ["options: must hold at least 2 items"])
        self.check("options", "x", ["options: must be a list"])
        self.check("options", [OPT, {**OPT2, "label": ""}], ["options.1.label: must be a non-empty string"])
        self.check("options", [OPT, {**OPT2, "cost": ""}], ["options.1.cost: must be a non-empty string"])
        self.check("options", [OPT, drop(OPT2, "cost")], ["options.1.cost: required key is missing"])
        self.check("options", [{**OPT, "x": 1}, OPT2], ["options.0.x: unknown key"])
        self.check("options", [OPT, "a str"], ["options.1: must be a mapping"])

    def test_one_option_refused_for_every_class(self):  # T14
        for c in cfg_default()["decision_classes"]["owner_only"]:
            with self.subTest(c):
                base = {**OPEN, "class": c, "options": [OPT]}
                if c == "merge-grant":
                    base["plan"] = "p"
                self.assertEqual(validate(base, self.cfg), ["options: must hold at least 2 items"])

    def test_landed_in_items(self):  # T15
        msg = "must be a normalised repo-relative path with an optional non-empty #anchor"
        for cite in ("CLAUDE.md", "CLAUDE.md#x"):
            self.check("landed_in", [cite], [], ANSWERED)
        for cite in ("CLAUDE.md#", "/abs.md", "a/../b.md", "./a.md", 1):
            self.check("landed_in", [cite], ["landed_in.0: " + msg], ANSWERED)
        self.check("landed_in", [], ["landed_in: must hold at least 1 items"], ANSWERED)

    def test_sha_shape_only(self):  # T16, OQ-11
        for key_path in ("asked_at", "answered_at", "withdrawn"):
            for sha, ok in (("a" * 7, True), ("a" * 40, True), ("a" * 6, False), ("a" * 41, False),
                            ("A" * 7, False), ("g" * 7, False)):
                with self.subTest("%s %r" % (key_path, sha)):
                    if key_path == "asked_at":
                        row = {**ANSWERED, "asked_at": sha}
                    elif key_path == "answered_at":
                        row = {**ANSWERED, "answered_at": {**AT, "at": sha}}
                    else:
                        row = {**WITHDRAWN, "withdrawn": {**W, "at": sha}}
                    errs = validate(row, self.cfg)
                    self.assertEqual(errs == [], ok, errs)
                    self.assertEqual(self.v(row) == [], ok)


class StatusMatrixTests(RowTestCase):
    FIELDS = {"answer": "Yes", "answered_at": AT, "rule": "r", "landed_in": ["CLAUDE.md"], "withdrawn": W}

    def test_open_with_each_field(self):  # M1, M2
        self.assertEqual(self.v(OPEN), [])
        for f, val in self.FIELDS.items():
            with self.subTest(f):
                self.assertEqual(validate({**OPEN, f: val}, self.cfg), [f + ": must be absent (absent_when matches)"])
        errs = validate({**OPEN, **self.FIELDS}, self.cfg)
        self.assertEqual(sorted(errs), sorted(f + ": must be absent (absent_when matches)" for f in self.FIELDS))

    def test_answered_cells(self):  # M3, M4, M5
        self.assertEqual(validate(drop(ANSWERED, "answer"), self.cfg),
                         ["answer: required key is missing (required_when matches)"])
        self.assertEqual(validate(drop(ANSWERED, "answered_at"), self.cfg),
                         ["answered_at: required key is missing (required_when matches)"])
        self.assertEqual(validate(drop(ANSWERED, "rule"), self.cfg), [])
        self.assertEqual(validate({**ANSWERED, "withdrawn": W}, self.cfg),
                         ["withdrawn: must be absent (absent_when matches)"])

    def test_withdrawn_cells(self):  # M6, M7
        for f in ("answer", "answered_at", "rule", "landed_in"):
            with self.subTest(f):
                self.assertEqual(validate({**WITHDRAWN, f: self.FIELDS[f]}, self.cfg),
                                 [f + ": must be absent (absent_when matches)"])
        self.assertEqual(validate(drop(WITHDRAWN, "withdrawn"), self.cfg),
                         ["withdrawn: required key is missing (required_when matches)"])
        self.assertEqual(validate({**WITHDRAWN, "answer": "x"}, self.cfg) != [], True)
        self.assertEqual(validate({**OPEN, "withdrawn": W}, self.cfg) != [], True)

    def test_invalid_or_missing_status_with_answer_fields(self):  # M8
        self.assertEqual(validate({**ANSWERED, "status": "Answered"}, self.cfg),
                         ["status: must be one of open, answered, withdrawn"])
        self.assertEqual(validate(drop(ANSWERED, "status"), self.cfg), ["status: required key is missing"])


class EffectTests(RowTestCase):
    def test_effect_against_landed_in(self):  # E1-E5
        self.assertEqual(validate(drop(ANSWERED, "landed_in"), self.cfg),
                         ["landed_in: required key is missing (required_when matches)"])
        self.assertEqual(validate({**ANSWERED, "effect": "one-off"}, self.cfg),
                         ["landed_in: must be absent (absent_when matches)"])
        self.assertEqual(validate(drop({**ANSWERED, "effect": "one-off"}, "landed_in"), self.cfg), [])
        self.assertEqual(validate(OPEN, self.cfg), [])
        self.assertEqual(validate(WITHDRAWN, self.cfg), [])
        self.assertEqual(validate(drop(ANSWERED, "effect"), self.cfg), ["effect: required key is missing"])


class ClassTests(RowTestCase):
    def test_default_classes_accepted(self):  # C1
        for c in cfg_default()["decision_classes"]["owner_only"]:
            with self.subTest(c):
                row = {**OPEN, "class": c}
                if c == "merge-grant":
                    row["plan"] = "p"
                self.assertEqual(validate(row, self.cfg), [])

    def test_config_added_class(self):  # C2
        hw = {**OPEN, "class": "hardware"}
        self.assertEqual(validate(hw, self.cfg), ["class: hardware is not in decision_classes.owner_only"])
        self.cfg["decision_classes"]["owner_only"].append("hardware")
        self.assertEqual(validate(hw, self.cfg), [])

    def test_config_added_class_through_config_load(self):  # C2 through config.load
        make_repo(self.work, {**{"schema": "config/1", "framework_version": "0", "profile": "strict"},
                              "decision_classes": {"owner_only": ["hardware"]}})
        self.assertEqual(validate({**OPEN, "class": "hardware"}, config.load(self.work)), [])

    def test_unknown_and_case(self):  # C3, C4
        for c in ("style", "Scope", "SCOPE", "scope "):
            with self.subTest(repr(c)):
                self.assertEqual(validate({**OPEN, "class": c}, self.cfg),
                                 ["class: %s is not in decision_classes.owner_only" % c])

    def test_class_not_a_string(self):  # C5
        for bad in (1, "", None):
            self.assertEqual(len(validate({**OPEN, "class": bad}, self.cfg)), 1)
        self.assertEqual(validate(drop(OPEN, "class"), self.cfg), ["class: required key is missing"])


class GrantTests(RowTestCase):
    def g(self, **kw):
        return validate({**GRANT, **kw}, self.cfg)

    def test_grant_field_combinations(self):  # G1-G4
        self.assertEqual(validate(drop(GRANT, "plan"), self.cfg),
                         ["plan: required key is missing (required_when matches)"])
        self.assertEqual(self.g(), [])
        self.assertEqual(self.g(program="prog"), ["program: stream must be given too; program and stream come "
                                                  "together or not at all"])
        self.assertEqual(self.g(stream="s1"), ["stream: program must be given too; program and stream come "
                                               "together or not at all"])
        self.assertEqual(self.g(program="prog", stream="s1"), [])

    def test_plan_shape(self):  # G5
        for plan, ok in (("a/b", False), ("a b", False), ("a\tb", False), ("a\nb", False), ("a b", False),
                         ("p-1.2", True)):
            with self.subTest(repr(plan)):
                self.assertEqual(self.g(plan=plan) == [], ok)
        self.assertEqual(self.g(plan="a/b"), ["plan: must not contain '/' or whitespace"])

    def test_program_stream_shape(self):  # G6
        for v, ok in (("s1", True), ("a-b", True), ("0x", True), ("S1", False), ("a/b", False), ("-a", False),
                      ("a_b", False), ("a.b", False), ("abc\n", False), ("", False)):
            for key, other in (("program", "stream"), ("stream", "program")):
                with self.subTest("%s %r" % (key, v)):
                    self.assertEqual(self.g(**{key: v, other: "ok"}) == [], ok)
        self.assertEqual(self.g(program="S1", stream="ok"), ["program: must match [a-z0-9][a-z0-9-]*"])

    def test_stream_integration(self):  # G7
        self.assertEqual(self.g(program="p", stream="integration"),
                         ["stream: 'integration' is reserved and cannot name a stream"])
        self.assertEqual(self.g(program="p", stream="main"), [])
        self.assertEqual(self.g(program="integration", stream="s"), [])

    def test_non_grant_with_grant_fields(self):  # G8
        for key in ("plan", "program", "stream"):
            with self.subTest(key):
                self.assertEqual(validate({**OPEN, key: "p"}, self.cfg),
                                 [key + ": must be absent unless class is merge-grant"])
        self.assertEqual(len(validate({**OPEN, "plan": "p", "program": "p", "stream": "s"}, self.cfg)), 3)

    def test_wrong_types_only_schema_error(self):  # G9
        self.assertEqual(self.g(plan=1), ["plan: must be a non-empty string"])
        self.assertEqual(self.g(program=["a"], stream="s"), ["program: must be a non-empty string"])

    def test_grant_fields_through_file(self):  # OQ-8 via write_record/load
        self.assertEqual(self.v({**GRANT, "program": "prog", "stream": "s1"}), [])
        self.assertEqual(self.v({**GRANT, "plan": "a/b"}), ["plan: must not contain '/' or whitespace"])


class S(str):
    pass


ONLY = "overrides: only class rule-override carries it"


def form(v):
    return "overrides: %s does not match SD-R[1-9][0-9]*" % v


def fixed(v):
    return "overrides: %s is a fixed rule and cannot be overridden" % v


def unknown(v):
    return "overrides: %s is not a base playbook rule" % v


def not_label(v):
    return "recommended: %s is not the label of exactly one option" % v


MODEL = "recommended: class model-policy carries no recommended option"
LINE = "source: must be a non-empty single line"


class RuleConstantTests(unittest.TestCase):
    def test_fixed_rules_literal(self):  # K1; F-2, literal owner value (F-B2p-4)
        self.assertIs(type(FIXED_RULES), tuple)
        self.assertEqual(FIXED_RULES, ("SD-R3", "SD-R12", "SD-R18"))

    def test_known_rules_literal(self):  # K2; DB-6, Q-B2plan-8 (a)
        self.assertIs(type(KNOWN_RULES), tuple)
        self.assertEqual(KNOWN_RULES, tuple("SD-R%d" % n for n in range(1, 20)))
        self.assertEqual(len(KNOWN_RULES), 19)

    def test_fixed_rules_are_known(self):  # K3
        self.assertTrue(set(FIXED_RULES) <= set(KNOWN_RULES))


class OverridesTests(RowTestCase):
    def test_well_formed_known_not_fixed(self):  # O1, O7
        for v in ("SD-R1", "SD-R2", "SD-R19"):
            with self.subTest(v):
                self.assertEqual(self.v({**OVERRIDE, "overrides": v}), [])
        self.assertEqual(self.v(drop(OVERRIDE, "overrides")), [])

    def test_overrides_form(self):  # O2: one error per cause, a malformed value names no rule
        for v in ("SD-R0", "SD-R01", "SD-R", "sd-r3", "SD-R3 ", " SD-R3", "SD-R3\n", "SD-R3a", "SD-R3\r",
                  "SD-R٣", "XSD-R3"):
            with self.subTest(repr(v)):
                self.assertEqual(validate({**OVERRIDE, "overrides": v}, self.cfg), [form(v)])

    def test_form_through_file(self):  # O2 via write_record/load
        for v in ("SD-R0", "sd-r3", "SD-R3a"):
            with self.subTest(v):
                self.assertEqual(self.v({**OVERRIDE, "overrides": v}), [form(v)])

    def test_rendered_reason_escaped_once(self):  # O3
        errs = validate({**OVERRIDE, "overrides": "SD-R3\n"}, self.cfg)
        self.assertEqual(errs, ["overrides: SD-R3\n does not match SD-R[1-9][0-9]*"])
        res = Result("x", [])
        res.fail("x.o", errs[0])
        self.assertEqual(res.render(False), "FAIL x.o: overrides: SD-R3\\n does not match SD-R[1-9][0-9]*\n")

    def test_overrides_fixed_rule_refused(self):  # O4; literal list, not the constant
        for r in ("SD-R3", "SD-R12", "SD-R18"):
            with self.subTest(r):
                self.assertEqual(self.v({**OVERRIDE, "overrides": r}), [fixed(r)])

    def test_overrides_unknown_rule_refused(self):  # O5; Q-B2plan-8 (a)
        for r in ("SD-R20", "SD-R100"):
            with self.subTest(r):
                self.assertEqual(self.v({**OVERRIDE, "overrides": r}), [unknown(r)])

    def test_not_an_exact_non_empty_str(self):  # O6: the schema's error only; nothing raises
        for v, err in ((1, "overrides: must be a non-empty string"), (None, "overrides: must not be null"),
                       ("", "overrides: must be a non-empty string"), (True, "overrides: must be a non-empty string"),
                       (S("SD-R3"), "overrides: must be a non-empty string"),
                       (["SD-R2"], "overrides: must be a non-empty string"),
                       ({"a": 1}, "overrides: must be a non-empty string")):
            with self.subTest(repr(v)):
                self.assertEqual(validate({**OVERRIDE, "overrides": v}, self.cfg), [err])

    def test_overrides_only_on_rule_override(self):  # O8
        self.assertIn(ONLY, validate({**OPEN, "overrides": "SD-R2"}, self.cfg))
        for c in cfg_default()["decision_classes"]["owner_only"]:
            if c == "rule-override":
                continue
            with self.subTest(c):
                row = {**OPEN, "class": c, "overrides": "SD-R2"}
                if c == "merge-grant":
                    row["plan"] = "p"
                self.assertEqual(self.v(row), [ONLY])
        self.cfg["decision_classes"]["owner_only"].append("hardware")
        self.assertEqual(validate({**OPEN, "class": "hardware", "overrides": "SD-R2"}, self.cfg), [ONLY])
        # exact class match (review 1 F1): near names of rule-override are other classes
        near = ("rule-override-x", "rule-overrides", "x-rule-override", "rule-overrid", "rule", "override")
        self.cfg["decision_classes"]["owner_only"].extend(near)
        for c in near:
            with self.subTest(near=c):
                self.assertEqual(validate({**OPEN, "class": c, "overrides": "SD-R2"}, self.cfg), [ONLY])
                self.assertEqual(validate({**OPEN, "class": c}, self.cfg), [])

    def test_class_and_value_both_wrong(self):  # O9
        self.assertEqual(validate({**OPEN, "overrides": "SD-R3"}, self.cfg), [ONLY, fixed("SD-R3")])
        self.assertEqual(validate({**OPEN, "overrides": "SD-R20"}, self.cfg), [ONLY, unknown("SD-R20")])
        self.assertEqual(validate({**OPEN, "overrides": "SD-R0"}, self.cfg), [ONLY, form("SD-R0")])
        self.assertEqual(validate({**OPEN, "overrides": 1}, self.cfg),
                         ["overrides: must be a non-empty string", ONLY])

    def test_class_missing_or_not_a_str(self):  # O10
        self.assertEqual(validate(drop(OVERRIDE, "class"), self.cfg), ["class: required key is missing"])
        self.assertEqual(validate({**OVERRIDE, "class": 1, "overrides": "SD-R3"}, self.cfg),
                         ["class: must be a non-empty string"])

    def test_every_status(self):  # O11
        for name, base in (("open", OPEN), ("answered", ANSWERED), ("withdrawn", WITHDRAWN)):
            with self.subTest(name):
                self.assertEqual(self.v({**base, "class": "rule-override", "overrides": "SD-R2"}), [])

    def test_grant_rules_unchanged(self):  # O12
        self.assertEqual(validate({**GRANT, "overrides": "SD-R2"}, self.cfg), [ONLY])
        self.assertEqual(validate({**GRANT, "plan": "a/b", "overrides": "SD-R2"}, self.cfg),
                         ["plan: must not contain '/' or whitespace", ONLY])
        self.assertEqual(validate({**OVERRIDE, "plan": "p"}, self.cfg),
                         ["plan: must be absent unless class is merge-grant"])


class RecommendedTests(RowTestCase):
    def test_absent(self):  # RC1
        self.cfg["decision_classes"]["owner_only"].append("hardware")
        for c in self.cfg["decision_classes"]["owner_only"]:
            for name, base in (("open", OPEN2), ("answered", ANSWERED), ("withdrawn", WITHDRAWN)):
                with self.subTest(c=c, status=name):
                    row = {**base, "class": c}
                    if c == "merge-grant":
                        row["plan"] = "p"
                    self.assertEqual(validate(row, self.cfg), [])

    def test_recommended_must_name_one_option(self):  # RC2, RC4; session-resume design 3.6
        self.assertEqual(self.v({**OPEN2, "recommended": "a"}), [])
        self.assertEqual(self.v({**OPEN2, "recommended": "b"}), [])
        for v in ("c", "A", "a ", " a", "x"):
            with self.subTest(repr(v)):
                self.assertEqual(self.v({**OPEN2, "recommended": v}), [not_label(v)])
        self.assertEqual(validate({**OPEN2, "recommended": ""}, self.cfg),
                         ["recommended: must be a non-empty string", not_label("")])

    def test_label_held_by_two_options(self):  # RC3
        row = {**OPEN2, "options": [{"label": "a", "cost": "x"}, {"label": "a", "cost": "y"}], "recommended": "a"}
        self.assertEqual(self.v(row), [not_label("a")])

    def test_not_an_exact_str(self):  # RC5: the schema's error only; nothing raises
        for v, err in ((1, "recommended: must be a non-empty string"), (True, "recommended: must be a non-empty string"),
                       (None, "recommended: must not be null"), (["a"], "recommended: must be a non-empty string"),
                       (S("a"), "recommended: must be a non-empty string")):
            with self.subTest(repr(v)):
                self.assertEqual(validate({**OPEN2, "recommended": v}, self.cfg), [err])

    def test_str_subclass_not_a_label(self):  # RC5 (review 2 R2-2): the label rule runs on an exact str only
        for v in (S("c"), S("A"), S("a "), S("x"), S("")):
            with self.subTest(repr(v)):
                self.assertEqual(validate({**OPEN2, "recommended": v}, self.cfg),
                                 ["recommended: must be a non-empty string"])
        self.assertEqual(validate({**MODEL2, "recommended": S("c")}, self.cfg),
                         ["recommended: must be a non-empty string", MODEL])  # schema errors first

    def test_recommended_refused_on_model_policy(self):  # RC6; L:415
        self.assertEqual(self.v({**MODEL2, "recommended": "a"}), [MODEL])
        self.assertEqual(validate({**MODEL2, "recommended": "c"}, self.cfg), [MODEL, not_label("c")])
        self.assertEqual(self.v(MODEL2), [])

    def test_config_added_class(self):  # RC7
        self.cfg["decision_classes"]["owner_only"].append("hardware")
        self.assertEqual(validate({**OPEN2, "class": "hardware", "recommended": "a"}, self.cfg), [])
        # exact class match (review 1 F1): near names of model-policy carry `recommended` like any other class
        near = ("model-policy-x", "x-model-policy", "model-polic", "model-policies", "model", "policy")
        self.cfg["decision_classes"]["owner_only"].extend(near)
        for c in near:
            with self.subTest(near=c):
                self.assertEqual(validate({**OPEN2, "class": c, "recommended": "a"}, self.cfg), [])
                self.assertEqual(validate({**OPEN2, "class": c, "recommended": "c"}, self.cfg), [not_label("c")])

    def test_label_compared_exactly(self):  # RC4 (review 1 F2): whitespace is part of the label, never stripped
        for v in (" ", "\t", " a ", "\ta", "a\t", "a\n"):
            with self.subTest(repr(v)):
                self.assertEqual(validate({**OPEN2, "recommended": v}, self.cfg), [not_label(v)])
        opts = [{"label": "a", "cost": "x"}, {"label": " a", "cost": "y"}]
        for v in ("a", " a"):
            with self.subTest(both=repr(v)):
                self.assertEqual(validate({**OPEN2, "options": opts, "recommended": v}, self.cfg), [])
        ws = [{"label": " ", "cost": "x"}, {"label": "b", "cost": "y"}]
        self.assertEqual(validate({**OPEN2, "options": ws, "recommended": " "}, self.cfg), [])

    def test_every_status(self):  # RC8
        for name, base in (("answered", ANSWERED), ("withdrawn", WITHDRAWN)):
            with self.subTest(name):
                self.assertEqual(self.v({**base, "options": OPEN2["options"], "recommended": "a"}), [])
                self.assertEqual(self.v({**base, "recommended": "yes"}), [])

    def test_options_malformed(self):  # RC9: fail closed, nothing raises
        cases = (
            ("a", ["options: must be a list", not_label("a")]),
            ([{"label": "a", "cost": "x"}, "a"], ["options.1: must be a mapping"]),
            (["a", "b"], ["options.0: must be a mapping", "options.1: must be a mapping", not_label("a")]),
            ([{"cost": "x"}, {"label": "b", "cost": "y"}], ["options.0.label: required key is missing",
                                                             not_label("a")]),
            ([{"label": 1, "cost": "x"}, {"label": "b", "cost": "y"}], ["options.0.label: must be a non-empty string",
                                                                         not_label("a")]),
            ([{"label": S("a"), "cost": "x"}, {"label": "b", "cost": "y"}],
             ["options.0.label: must be a non-empty string", not_label("a")]),
            ([{"label": ["a"], "cost": "x"}, {"label": "b", "cost": "y"}],
             ["options.0.label: must be a non-empty string", not_label("a")]),
            (None, ["options: must not be null", not_label("a")]),
        )
        for opts, expected in cases:
            with self.subTest(repr(opts)):
                self.assertEqual(validate({**OPEN2, "options": opts, "recommended": "a"}, self.cfg), expected)
        self.assertEqual(validate({**drop(OPEN2, "options"), "recommended": "a"}, self.cfg),
                         ["options: required key is missing", not_label("a")])

    def test_options_not_a_list(self):  # RC9 (review 2 R2-3): every non-list value; the label rule never iterates
        cases = (
            (1, ["options: must be a list"]), (0, ["options: must be a list"]), (1.5, ["options: must be a list"]),
            (True, ["options: must be a list"]), (None, ["options: must not be null"]),
            ({"recommended": "a"}, ["options: must be a list"]),
            ({"label": "a", "cost": "x"}, ["options: must be a list"]),
            ({}, ["options: must be a list"]), ("a", ["options: must be a list"]),
        )
        for opts, schema_errs in cases:
            with self.subTest(repr(opts)):
                self.assertEqual(validate({**OPEN2, "options": opts, "recommended": "a"}, self.cfg),
                                 schema_errs + [not_label("a")])

    def test_recommended_on_every_default_class(self):  # RC6/RC7 class dimension (review 2 R2-1); spec 7.1
        classes = cfg_default()["decision_classes"]["owner_only"]
        self.assertIn("model-policy", classes)
        for c in classes:
            for name, base in (("open", OPEN2), ("answered", {**ANSWERED, "options": OPEN2["options"]})):
                with self.subTest(c=c, status=name):
                    row = {**base, "class": c, "recommended": "a"}
                    if c == "merge-grant":
                        row["plan"] = "p"
                    self.assertEqual(validate(row, self.cfg), [MODEL] if c == "model-policy" else [])

    def test_migrated_row_without_new_fields_valid(self):  # RC10, SC8; design 5 (old fixture: exempt literal)
        row_v1 = {**drop(OPEN2, *OPTIONAL_FIELDS), "schema": "decision/1"}
        got = migrate("decision", row_v1)
        self.assertEqual(got, {**row_v1, "schema": "decision/2"})
        self.assertEqual(validate(got, self.cfg), [])

    def test_rendered_reason_escaped_once(self):  # RC11
        errs = validate({**OPEN2, "recommended": "a\nb"}, self.cfg)
        self.assertEqual(errs, [not_label("a\nb")])
        res = Result("x", [])
        res.fail("x.r", errs[0])
        self.assertEqual(res.render(False),
                         "FAIL x.r: recommended: a\\nb is not the label of exactly one option\n")


CHANGED_CP = "\U0001F6DC"  # PC1-U: Cn (unassigned) in Unicode 13.0 (Python 3.9), So in Unicode 15.1 (Python 3.13)


def unidata_major():
    return int(unicodedata.unidata_version.split(".")[0])


class TextDomainTests(RowTestCase):
    """PC1 skeleton rows (owner Q-D30C2-1 (A+)) for this task's text checks; the suite runs on 3.9 and 3.13."""

    def test_digit_runs_at_the_int_limit(self):  # PC1-D: validate never int()s text; 4300 and 4301 digits
        for n in (4300, 4301):
            with self.subTest(n=n):
                rid = "SD-R" + "1" * n
                self.assertEqual(validate({**OVERRIDE, "overrides": rid}, self.cfg),
                                 ["overrides: %s is not a base playbook rule" % rid])
                tag = "decision/" + "2" * n
                self.assertEqual(validate({**OPEN2, "schema": tag}, self.cfg),
                                 ["schema: expected %s, got %s; run /strict-delivery:upgrade" % (TAG, tag)])

    def test_code_point_whose_category_changed(self):  # PC1-U: the verdicts do not depend on the unidata version
        self.assertEqual(unicodedata.category(CHANGED_CP), "So" if unidata_major() >= 15 else "Cn")
        opts = [{"label": CHANGED_CP, "cost": "x"}, {"label": "b", "cost": "y"}]
        self.assertEqual(validate({**OPEN2, "options": opts, "recommended": CHANGED_CP}, self.cfg), [])
        self.assertEqual(validate({**OPEN2, "recommended": CHANGED_CP}, self.cfg), [not_label(CHANGED_CP)])
        self.assertEqual(validate({**OPEN2, "source": "r/%s.md" % CHANGED_CP, "question": CHANGED_CP}, self.cfg), [])
        for v in ("SD-R" + CHANGED_CP, "SD-R١", "SD-R２"):  # non-ASCII digits never match [0-9]
            with self.subTest(repr(v)):
                self.assertEqual(validate({**OVERRIDE, "overrides": v}, self.cfg),
                                 ["overrides: %s does not match SD-R[1-9][0-9]*" % v])


class SourceTests(RowTestCase):
    def test_absent(self):  # SC1
        self.assertEqual(self.v(OPEN2), [])

    def test_source_single_line(self):  # SC2; Q-X27 (a)
        for v in ("r/a.md", "no/such/file.md", "a path/with spaces.md"):
            with self.subTest(v):
                self.assertEqual(self.v({**OPEN2, "source": v}), [])

    def test_empty(self):  # SC3
        self.assertEqual(validate({**OPEN2, "source": ""}, self.cfg),
                         ["source: must be a non-empty string", LINE])

    def test_line_breaks(self):  # SC4
        for v in ("a\nb", "a\rb", "a\r\nb", "a\n", "\n", "\r"):
            with self.subTest(repr(v)):
                self.assertEqual(validate({**OPEN2, "source": v}, self.cfg), [LINE])
        self.assertEqual(self.v({**OPEN2, "source": "a\nb"}), [LINE])

    def test_other_characters(self):  # SC5
        for v in ("a\tb", "a b", "a\x0bb", "a\x85b", "a b"):
            with self.subTest(repr(v)):
                self.assertEqual(validate({**OPEN2, "source": v}, self.cfg), [])
        for v in (" ", "\t", "  a  ", " \t ", "\x0b", "\x85", "　"):  # review 1 F2: whitespace-only is valid
            with self.subTest(ws=repr(v)):
                self.assertEqual(validate({**OPEN2, "source": v}, self.cfg), [])
        for v in (" ", "  a  "):  # and through a written record
            with self.subTest(file=repr(v)):
                self.assertEqual(self.v({**OPEN2, "source": v}), [])

    def test_not_an_exact_str(self):  # SC6
        for v, err in ((1, "source: must be a non-empty string"), (None, "source: must not be null"),
                       (["r/a.md"], "source: must be a non-empty string"),
                       (S("a\nb"), "source: must be a non-empty string")):
            with self.subTest(repr(v)):
                self.assertEqual(validate({**OPEN2, "source": v}, self.cfg), [err])

    def test_status_and_class(self):  # SC7
        for name, base in (("open", OPEN2), ("answered", ANSWERED), ("withdrawn", WITHDRAWN), ("model", MODEL2)):
            with self.subTest(name):
                self.assertEqual(self.v({**base, "source": "r/a.md"}), [])

    def test_all_three_fields_together(self):  # O1 + RC2 + SC2 on one row; every rule independent
        row = {**OPEN2, "class": "rule-override", "overrides": "SD-R2", "recommended": "a", "source": "r/a.md"}
        self.assertEqual(self.v(row), [])
        bad = {**row, "class": "model-policy", "overrides": "SD-R3", "recommended": "c", "source": "a\nb"}
        self.assertEqual(validate(bad, self.cfg), [ONLY, fixed("SD-R3"), MODEL, not_label("c"), LINE])


class LandedTests(GitIsolatedTestCase):
    def setUp(self):
        super().setUp()
        self.cfg = cfg_default()
        make_repo(self.work)
        self.row = {**ANSWERED, "landed_in": ["CLAUDE.md"]}

    def put(self, rel, text):
        path = os.path.join(self.work, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(text if isinstance(text, bytes) else text.encode("utf-8"))

    def errs(self, *cites, row=None, tracked=None, commit=True):
        if commit:
            commit_all(self.work, "files")
        t = gitinfo.tracked_files(self.work) if tracked is None else tracked
        return landed_errors({**(row or self.row), "landed_in": list(cites)}, self.work, self.cfg, t)

    def test_allowed_places(self):  # L1
        places = [".strict-delivery/playbooks/x.md", ".strict-delivery/playbooks/sub/y.md", "CLAUDE.md",
                  "docs/strict-delivery/architecture.md"]
        for p in places:
            self.put(p, "see " + A + ".\n")
        for p in places:
            with self.subTest(p):
                self.assertEqual(self.errs(p), [])

    def test_anchor_stripped_not_checked(self):  # L2
        self.put("CLAUDE.md", A)
        self.assertEqual(self.errs("CLAUDE.md#no-such-anchor", "CLAUDE.md#x"), [])

    def test_not_on_allow_list(self):  # L3
        for p in ("README.md", "docs/CLAUDE.md", "claude.md", ".strict-delivery/playbooksX/a.md"):
            self.put(p, A)
        self.put(".strict-delivery/playbooks/d/x.md", A)
        for p in ("README.md", "docs/CLAUDE.md", "claude.md", ".strict-delivery/playbooksX/a.md",
                  ".strict-delivery/playbooks"):
            with self.subTest(p):
                self.assertEqual(self.errs(p), ["landed_in: %s is not a playbook, CLAUDE.md or architecture.md" % p])

    def test_config_moved_places(self):  # L4
        self.cfg["paths"]["playbooks"] = "rules"
        self.cfg["paths"]["architecture"] = "ARCH.md"
        for p in ("rules/a.md", "ARCH.md", "docs/strict-delivery/architecture.md"):
            self.put(p, A)
        self.assertEqual(self.errs("rules/a.md", "ARCH.md"), [])
        self.assertEqual(self.errs("docs/strict-delivery/architecture.md"),
                         ["landed_in: docs/strict-delivery/architecture.md is not a playbook, CLAUDE.md or "
                          "architecture.md"])

    def test_spec_refused(self):  # L5
        self.put("docs/strict-delivery/specs/x.md", A)
        self.assertEqual(self.errs("docs/strict-delivery/specs/x.md"), [SPEC_ERR])
        self.assertEqual(self.errs("docs/strict-delivery/specs/x.md#s"), [SPEC_ERR])
        self.assertEqual(self.errs("docs/strict-delivery/specs"),
                         ["landed_in: docs/strict-delivery/specs is a spec; specs are cleaned, land the rule in "
                          "a playbook, CLAUDE.md or architecture.md"])

    def test_spec_inside_allowed_place_still_spec(self):  # L6
        self.cfg["paths"]["specs"] = ".strict-delivery/playbooks/specs"
        self.put(".strict-delivery/playbooks/specs/x.md", A)
        self.assertEqual(self.errs(".strict-delivery/playbooks/specs/x.md"),
                         ["landed_in: .strict-delivery/playbooks/specs/x.md is a spec; specs are cleaned, land "
                          "the rule in a playbook, CLAUDE.md or architecture.md"])

    def test_untracked_and_non_regular(self):  # L7
        self.put("CLAUDE.md", A)
        self.assertEqual(self.errs("CLAUDE.md", commit=False),
                         ["landed_in: CLAUDE.md is not a tracked regular file"])
        self.put(".strict-delivery/playbooks/d/x.md", A)
        commit_all(self.work, "d")
        self.assertEqual(self.errs(".strict-delivery/playbooks/d"),
                         ["landed_in: .strict-delivery/playbooks/d is not a tracked regular file"])
        # tracked in the set but absent from the working tree
        self.assertEqual(self.errs("CLAUDE.md", tracked=frozenset({"CLAUDE.md"}) | gitinfo.tracked_files(self.work),
                                   commit=False) , [])
        self.assertEqual(self.errs(".strict-delivery/playbooks/gone.md", commit=False,
                                   tracked=frozenset({".strict-delivery/playbooks/gone.md"})),
                         ["landed_in: .strict-delivery/playbooks/gone.md cannot be read as a UTF-8 regular file "
                          "(No such file or directory)"])

    def test_tracked_symlink_not_a_regular_entry(self):  # L7
        self.put("x.md", A)
        os.symlink("x.md", os.path.join(self.work, "CLAUDE.md"))
        self.assertEqual(self.errs("CLAUDE.md"), ["landed_in: CLAUDE.md is not a tracked regular file"])

    def test_working_tree_symlink_and_symlinked_parent(self):  # L7
        self.put("CLAUDE.md", A)
        commit_all(self.work, "c")
        tracked = gitinfo.tracked_files(self.work)
        self.put("other.md", A)
        link = os.path.join(self.work, "tmp-link")
        os.symlink("other.md", link)
        os.replace(link, os.path.join(self.work, "CLAUDE.md"))
        self.assertEqual(self.errs("CLAUDE.md", tracked=tracked, commit=False),
                         ["landed_in: CLAUDE.md cannot be read as a UTF-8 regular file (not a regular file)"])
        os.makedirs(os.path.join(self.work, ".strict-delivery"), exist_ok=True)
        self.put("real/x.md", A)
        os.symlink("../real", os.path.join(self.work, ".strict-delivery", "playbooks"))
        errs = self.errs(".strict-delivery/playbooks/x.md", commit=False,
                         tracked=frozenset({".strict-delivery/playbooks/x.md"}))
        self.assertEqual(len(errs), 1)
        self.assertTrue(errs[0].startswith("landed_in: .strict-delivery/playbooks/x.md cannot be read"), errs)

    def test_lacking_the_id(self):  # L8
        self.put("CLAUDE.md", "nothing here\n")
        self.assertEqual(self.errs("CLAUDE.md"), ["landed_in: CLAUDE.md does not contain the decision id " + A])
        self.put("CLAUDE.md", "see " + B + "\n")
        self.assertEqual(self.errs("CLAUDE.md"), ["landed_in: CLAUDE.md does not contain the decision id " + A])

    def test_whole_token_match(self):  # L9
        cases = [("see %s." % A, True), ("[x](#%s)" % A, True), (A + "a", False), ("X" + A, False),
                 (A + "_x", False), ("-" + A, False), (A, True), ("x\n" + A, True), (A + "\nx", True),
                 (A + "-x", False), ("%s-" % A, False), ("'%s'" % A, True)]
        for text, ok in cases:
            with self.subTest(text):
                self.put("CLAUDE.md", text)
                self.assertEqual(self.errs("CLAUDE.md") == [], ok)

    def test_id_only_as_prefix_of_longer_token_fails(self):  # plan dimension
        self.put("CLAUDE.md", A + "z")
        self.assertEqual(len(self.errs("CLAUDE.md")), 1)

    def test_file_content_kinds(self):  # L10
        self.put("CLAUDE.md", b"\xff\xfe " + A.encode())
        errs = self.errs("CLAUDE.md")
        self.assertEqual(len(errs), 1)
        self.assertTrue(errs[0].startswith("landed_in: CLAUDE.md cannot be read as a UTF-8 regular file"), errs)
        self.put("CLAUDE.md", b"")
        self.assertEqual(self.errs("CLAUDE.md"), ["landed_in: CLAUDE.md does not contain the decision id " + A])
        self.put("CLAUDE.md", ("line\r\n%s\r\n" % A).encode())
        self.assertEqual(self.errs("CLAUDE.md"), [])

    def test_malformed_cites(self):  # L11
        self.put("CLAUDE.md", A)
        norm = "is not a normalised repo-relative path with an optional non-empty #anchor"
        for cite in ("/abs.md", "a/../CLAUDE.md", "./CLAUDE.md", "CLAUDE.md#", "CLAUDE.md#a#b"):
            with self.subTest(cite):
                self.assertEqual(self.errs(cite), ["landed_in: %s %s" % (cite, norm)])
        self.assertEqual(self.errs(1), ["landed_in: 1 is not a string"])
        self.assertEqual(self.errs(None), ["landed_in: None is not a string"])

    def test_several_and_duplicate_cites(self):  # L12
        self.put("CLAUDE.md", A)
        self.put("README.md", A)
        self.assertEqual(self.errs("CLAUDE.md", "README.md"),
                         ["landed_in: README.md is not a playbook, CLAUDE.md or architecture.md"])
        self.assertEqual(self.errs("CLAUDE.md", "CLAUDE.md#x"), [])

    def test_landed_in_absent_not_a_list_and_bad_id(self):  # L13
        self.put("CLAUDE.md", A)
        commit_all(self.work, "c")
        t = gitinfo.tracked_files(self.work)
        self.assertEqual(landed_errors(drop(self.row, "landed_in"), self.work, self.cfg, t), [])
        self.assertEqual(landed_errors({**self.row, "landed_in": "CLAUDE.md"}, self.work, self.cfg, t),
                         ["landed_in: must be a list of cites"])
        for bad in (1, None, ""):
            with self.subTest(repr(bad)):
                self.assertEqual(landed_errors({**self.row, "id": bad}, self.work, self.cfg, t),
                                 ["landed_in: CLAUDE.md cannot be checked: the row has no valid id to find in it"])
        self.assertEqual(landed_errors(drop(self.row, "id"), self.work, self.cfg, t),
                         ["landed_in: CLAUDE.md cannot be checked: the row has no valid id to find in it"])
        self.assertEqual(landed_errors([], self.work, self.cfg, t), [])

    def test_root_must_be_toplevel(self):  # L14, owner Q-1a-fin-1 (a)
        self.put("CLAUDE.md", "no id")
        self.put("sub/CLAUDE.md", A)
        commit_all(self.work, "c")
        t = gitinfo.tracked_files(self.work)
        row = {**self.row, "landed_in": ["CLAUDE.md"]}
        msg = "git rev-parse --show-toplevel: root must be the repository top level"
        with self.assertRaises(GateError) as cm:
            landed_errors(row, os.path.join(self.work, "sub"), self.cfg, t)
        self.assertEqual(str(cm.exception), msg)
        with self.assertRaises(GateError):  # refused before the row is looked at
            landed_errors(drop(row, "landed_in"), os.path.join(self.work, "sub"), self.cfg, t)
        self.assertEqual(landed_errors(row, self.work, self.cfg, t),
                         ["landed_in: CLAUDE.md does not contain the decision id " + A])
        link = os.path.join(self.tmp, "toplink")
        os.symlink(self.work, link)
        self.assertEqual(landed_errors(row, link, self.cfg, t),
                         ["landed_in: CLAUDE.md does not contain the decision id " + A])

    def test_landed_in_must_contain_id_with_validate(self):  # plan test, both functions on one row
        self.put("CLAUDE.md", "no id")
        self.assertEqual(validate(self.row, self.cfg), [])
        self.assertEqual(len(self.errs("CLAUDE.md")), 1)


def rec(row, name=None):
    return Record(row.get("id"), row, "d/%s.yml" % (name or row.get("id")))


def dec(id_, status="answered", **more):
    r = {"id": id_, "status": status, "class": "scope", "effect": "lasting", "question": "q", "answer": "a",
         "topics": [], "applies_to": []}
    r.update(more)
    return r


class RuleTests(unittest.TestCase):
    def suffixes(self, records):
        return sorted(s for s, _ in ref_errors(records))

    def test_is_resolved(self):  # R1
        self.assertFalse(is_resolved({"status": "open"}))
        for v in ("answered", "withdrawn", "Open", None, 1):
            with self.subTest(repr(v)):
                self.assertTrue(is_resolved({"status": v}))
        self.assertTrue(is_resolved({}))

    def test_superseded_ids_by_answered_only(self):  # R2
        for status, expect in (("open", set()), ("answered", {A}), ("withdrawn", set())):
            with self.subTest(status):
                self.assertEqual(superseded_ids([rec(dec(A)), rec(dec(B, status, supersedes=A))]), expect)

    def test_chain_of_three(self):  # R3
        recs = [rec(dec(A)), rec(dec(B, supersedes=A)), rec(dec(C, supersedes=B))]
        self.assertEqual(superseded_ids(recs), {A, B})
        self.assertEqual((current(recs, A), current(recs, B), current(recs, C)), (C, C, C))
        self.assertEqual(ref_errors(recs), [])
        recs[2] = rec(dec(C, "open", supersedes=B))
        self.assertEqual(superseded_ids(recs), {A})
        self.assertEqual(current(recs, A), B)

    def test_missing_target(self):  # R4
        self.assertEqual(ref_errors([rec(dec(B, supersedes=A))]),
                         [("supersedes." + B, "supersedes: %s has no record" % A)])

    def test_self(self):  # R5
        self.assertEqual(ref_errors([rec(dec(A, supersedes=A))]),
                         [("supersedes." + A, "supersedes: a decision cannot supersede itself")])
        self.assertEqual(superseded_ids([rec(dec(A, supersedes=A))]), set())

    def test_self_superseding_row_counts_nowhere(self):  # owner Q-1b2r-2 (a)
        selfie = rec(dec(A, supersedes=A))
        self.assertEqual(superseded_ids([selfie]), set())
        self.assertEqual([r.id for r in in_force([selfie])], [A])
        self.assertEqual(current([selfie], A), A)
        self.assertEqual([r.id for r in find([selfie], [], None, None, False)], [A])
        self.assertEqual(self.suffixes([selfie]), ["supersedes." + A])
        # with a second answered superseder there is no fork: the self reference is not a superseder
        both = [selfie, rec(dec(B, supersedes=A))]
        self.assertEqual(self.suffixes(both), ["supersedes." + A])
        self.assertEqual(current(both, A), B)

    def test_target_not_answered(self):  # R6
        for target in ("open", "withdrawn"):
            for sup in ("open", "answered"):
                with self.subTest("%s %s" % (target, sup)):
                    self.assertEqual(ref_errors([rec(dec(A, target)), rec(dec(B, sup, supersedes=A))]),
                                     [("supersedes." + B, "supersedes: %s is not answered" % A)])
        # Q-1b2-3: a withdrawn superseder is not checked for its target's status
        self.assertEqual(ref_errors([rec(dec(A, "open")), rec(dec(B, "withdrawn", supersedes=A))]), [])
        # ... but is checked for a missing target, itself and a cycle
        self.assertEqual(self.suffixes([rec(dec(B, "withdrawn", supersedes=A))]), ["supersedes." + B])
        self.assertEqual(self.suffixes([rec(dec(B, "withdrawn", supersedes=B))]), ["supersedes." + B])
        self.assertEqual(self.suffixes([rec(dec(A, "withdrawn", supersedes=B)),
                                        rec(dec(B, "withdrawn", supersedes=A))]),
                         ["supersedes." + A, "supersedes." + B])

    def test_cycles_terminate(self):  # R7
        two = [rec(dec(A, supersedes=B)), rec(dec(B, supersedes=A))]
        self.assertEqual(self.suffixes(two), ["supersedes." + A, "supersedes." + B])
        three = [rec(dec(A, supersedes=B)), rec(dec(B, "open", supersedes=C)), rec(dec(C, supersedes=A))]
        self.assertEqual(self.suffixes(three), ["supersedes." + A, "supersedes." + B, "supersedes." + C])
        self.assertEqual(current(two, A), B)  # A > B > A: stops at the first repeat, last id before it
        self.assertEqual(current(two, B), A)
        four = [rec(dec(A, supersedes=B)), rec(dec(B, supersedes=C)), rec(dec(C, supersedes=D)),
                rec(dec(D, supersedes=A))]
        self.assertEqual(current(four, A), B)  # A, D, C, B, then A repeats: the last id before the repeat
        # a tail leading into a cycle, from a row outside it: that row is not a member
        tail = [rec(dec(D, supersedes=A))] + two
        self.assertNotIn("supersedes." + D, self.suffixes(tail))

    def test_fork(self):  # R8
        for s1 in ("open", "answered"):
            for s2 in ("open", "answered"):
                with self.subTest("%s %s" % (s1, s2)):
                    recs = [rec(dec(A)), rec(dec(B, s1, supersedes=A)), rec(dec(C, s2, supersedes=A))]
                    self.assertEqual(self.suffixes(recs), ["fork." + A])

    def test_withdrawn_superseder_ignored(self):  # R9, Q-decisions-1
        a, bw, co = rec(dec(A)), rec(dec(B, "withdrawn", supersedes=A)), rec(dec(C, "open", supersedes=A))
        self.assertEqual(ref_errors([a, bw, co]), [])
        self.assertNotIn(A, superseded_ids([a, bw, co]))
        self.assertIn("fork." + A, [s for s, _ in ref_errors([a, rec(dec(B, "open", supersedes=A)), co])])
        self.assertEqual(ref_errors([a, bw, rec(dec(C, "withdrawn", supersedes=A))]), [])
        ca = rec(dec(C, supersedes=A))
        self.assertEqual(ref_errors([a, bw, ca]), [])
        self.assertEqual(superseded_ids([a, bw, ca]), {A})

    def test_checked_against(self):  # R10
        row = dec(A, checked_against=[B, C, D])
        self.assertEqual(ref_errors([rec(row), rec(dec(B, "withdrawn"))]),
                         [("checked." + A, "checked_against: no record for %s, %s" % (C, D))])
        self.assertEqual(ref_errors([rec(dec(A, checked_against=[])), rec(dec(B))]), [])
        self.assertEqual(ref_errors([rec(dec(A, checked_against=[B])), rec(dec(B))]), [])

    def test_current_unknown_and_unsuperseded(self):  # R11
        recs = [rec(dec(A)), rec(dec(B, "open", supersedes=A))]
        self.assertEqual(current(recs, "DEC-20261031-zzzz"), "DEC-20261031-zzzz")
        self.assertEqual(current(recs, A), A)
        self.assertEqual(current([rec(dec(A))], A), A)

    def test_current_fork_raises(self):  # R12
        recs = [rec(dec(A)), rec(dec(B, supersedes=A)), rec(dec(C, supersedes=A))]
        with self.assertRaises(GateError) as cm:
            current(recs, A)
        self.assertIn("fork." + A, str(cm.exception))
        self.assertEqual(self.suffixes(recs), ["fork." + A])

    def test_malformed_rows_never_raise(self):  # R13
        bad = [Record(None, {"status": "answered", "supersedes": A}, "d/x.yml"),
               rec(dec(B, supersedes=1)), rec({"id": C}), Record(D, "not a dict", "d/y.yml"),
               Record(5, dec(A), "d/z.yml"), rec(dec(A, checked_against="x"))]
        ref_errors(bad)
        superseded_ids(bad)
        in_force(bad)
        find(bad, [], None, None, False)
        find(bad, ["q"], "src/a", "t", True)
        self.assertEqual(current(bad, A), A)
        self.assertEqual(superseded_ids(bad), set())

    def test_in_force(self):  # I1-I6
        recs = [rec(dec(A)), rec(dec(B, "open")), rec(dec(C, "withdrawn")), rec(dec(D, effect="one-off")),
                rec(dec("DEC-20261031-e2f3", **{"class": "merge-grant"}))]
        self.assertEqual([r.id for r in in_force(recs)], [A])
        self.assertEqual(in_force([]), [])

    def test_in_force_excludes_superseded_only_by_answered(self):  # I3
        for status, gone in (("answered", True), ("open", False), ("withdrawn", False)):
            with self.subTest(status):
                got = [r.id for r in in_force([rec(dec(A)), rec(dec(B, status, supersedes=A))])]
                self.assertEqual(got, [B] if gone else [A])

    def test_in_force_keeps_input_order(self):  # I5
        recs = [rec(dec(C)), rec(dec(A)), rec(dec(B))]
        self.assertEqual([r.id for r in in_force(recs)], [C, A, B])

    def test_in_force_excludes_superseded_grants_one_off(self):  # plan test
        recs = [rec(dec(A)), rec(dec(B, supersedes=A)), rec(dec(C, effect="one-off")),
                rec(dec(D, **{"class": "merge-grant"}))]
        self.assertEqual([r.id for r in in_force(recs)], [B])


class FindTests(unittest.TestCase):
    def ids(self, recs, terms=(), path=None, topic=None, all_=False):
        return [r.id for r in find(recs, list(terms), path, topic, all_)]

    def test_terms_over_fields(self):  # N1
        recs = [rec(dec(A, question="alpha")), rec(dec(B, answer="alpha")), rec(dec(C, topics=["alpha"])),
                rec(dec(D, rule="alpha", **{"class": "scope"}))]
        self.assertEqual(self.ids(recs, ["alpha"]), [A, B, C])

    def test_every_term(self):  # N2
        recs = [rec(dec(A, question="alpha beta")), rec(dec(B, question="alpha", answer="beta")),
                rec(dec(C, question="alpha"))]
        self.assertEqual(self.ids(recs, ["alpha", "beta"]), [A, B])

    def test_case_unicode_literal(self):  # N3, N4
        recs = [rec(dec(A, question="Straße é a.c")), rec(dec(B, question="abc ( ["))]
        self.assertEqual(self.ids(recs, ["ALPHA"]), [])
        self.assertEqual(self.ids(recs, ["STRASSE"]), [A])
        self.assertEqual(self.ids(recs, ["É"]), [A])
        self.assertEqual(self.ids(recs, ["a.c"]), [A])
        self.assertEqual(self.ids(recs, ["("]), [B])
        self.assertEqual(self.ids(recs, ["[x]"]), [])

    def test_empty_terms(self):  # N5
        recs = [rec(dec(A)), rec(dec(B))]
        self.assertEqual(self.ids(recs, []), [A, B])
        self.assertEqual(self.ids(recs, [""]), [A, B])

    def test_path_glob(self):  # N6
        recs = [rec(dec(A, applies_to=["src/*"])), rec(dec(B, applies_to=["src/**/*.py"])),
                rec(dec(C, applies_to=[]))]
        self.assertEqual(self.ids(recs, path="src/a/b.py"), [A, B])
        self.assertEqual(self.ids(recs, path="src/a.py"), [A])
        self.assertEqual(self.ids(recs, path="SRC/a"), [])
        self.assertEqual(self.ids(recs, path=None), [A, B, C])

    def test_path_glob_outside_the_grammar_refused(self):  # F-1, U-2 folded into F-1 (D-31)
        recs = [rec(dec(A, applies_to=["src/*"])), rec(dec(B, applies_to=["src/*", 5, "", "src/[z-a].py"]))]
        with self.assertRaises(GateError) as cm:
            find(recs, [], "src/x.py", None, True)
        self.assertEqual(str(cm.exception), "%s: applies_to.3: must be a supported glob: the bracket expression "
                                            "[z-a] holds the reversed range z-a" % B)
        self.assertEqual(self.ids(recs, all_=True), [A, B])  # no --path: no glob is read
        recs[1] = rec(dec(B, applies_to=[5, "", "src/[a-c].py"]))
        self.assertEqual(self.ids(recs, path="src/b.py", all_=True), [A, B])
        self.assertEqual(self.ids(recs, path="", all_=True), [B])  # "" matches only the empty path, as before

    def test_find_by_path_glob_and_topic(self):  # plan test
        recs = [rec(dec(D, applies_to=["src/*"], topics=["ids"])), rec(dec(A, applies_to=["doc/*"], topics=["x"]))]
        self.assertEqual(self.ids(recs, path="src/a/b.py"), [D])
        self.assertEqual(self.ids(recs, topic="ids"), [D])

    def test_topic_exact_after_casefold(self):  # N7, Q-1b2-5
        recs = [rec(dec(A, topics=["ids"]))]
        self.assertEqual(self.ids(recs, topic="IDS"), [A])
        self.assertEqual(self.ids(recs, topic="id"), [])
        self.assertEqual(self.ids(recs, topic=None), [A])

    def test_follows_supersedes_chain(self):  # N8, plan test
        recs = [rec(dec(A, question="term")), rec(dec(B, supersedes=A, question="x")),
                rec(dec(C, supersedes=B, question="y"))]
        self.assertEqual(self.ids(recs, ["term"]), [C])

    def test_no_repeats_in_first_appearance_order(self):  # N9
        recs = [rec(dec(A, question="t")), rec(dec(B, question="t")), rec(dec(C, supersedes=A, question="t")),
                rec(dec(D, question="t"))]
        self.assertEqual(self.ids(recs, ["t"]), [C, B, D])  # A is replaced by C at A's place
        recs = [rec(dec(A, question="t")), rec(dec(B, question="t", supersedes=A)), rec(dec(C, supersedes=B))]
        self.assertEqual(self.ids(recs, ["t"]), [C])

    def test_in_force_only(self):  # N10
        recs = [rec(dec(A, "open")), rec(dec(B, "withdrawn")), rec(dec(C, effect="one-off")),
                rec(dec(D, **{"class": "merge-grant"})), rec(dec("DEC-20261031-e2f3", question="q"))]
        self.assertEqual(self.ids(recs, ["q"]), ["DEC-20261031-e2f3"])

    def test_superseded_by_non_lasting_current_drops_out(self):  # replace then filter
        recs = [rec(dec(A, question="t")), rec(dec(B, supersedes=A, effect="one-off"))]
        self.assertEqual(self.ids(recs, ["t"]), [])

    def test_every_kind_of_superseded_match_is_replaced(self):  # owner Q-1b2r-1 (b)
        kinds = {"one-off": dict(effect="one-off"), "grant": {"class": "merge-grant"},
                 "open": dict(status="open"), "withdrawn": dict(status="withdrawn")}
        for name, kw in kinds.items():
            with self.subTest(name):
                a = dec(A, question="t", **kw)
                # an open or withdrawn A is superseded by an answered B: the cross-status case
                recs = [rec(a), rec(dec(B, supersedes=A, question="x"))]
                self.assertEqual(self.ids(recs, ["t"]), [B])
                self.assertEqual(self.ids(recs, ["t"], all_=True), [A])
                # unsuperseded, the same match stays out (not in force)
                self.assertEqual(self.ids([rec(a)], ["t"]), [])
                # replaced by a ruling that is itself not in force: nothing
                recs = [rec(a), rec(dec(B, supersedes=A, question="x", effect="one-off"))]
                self.assertEqual(self.ids(recs, ["t"]), [])
        # a withdrawn superseder does not replace its target
        recs = [rec(dec(A, question="t", effect="one-off")), rec(dec(B, "withdrawn", supersedes=A))]
        self.assertEqual(self.ids(recs, ["t"]), [])
        # two matches replaced by one ruling: once
        recs = [rec(dec(A, question="t", effect="one-off")), rec(dec(C, question="t", status="open")),
                rec(dec(B, supersedes=A)), rec(dec(D, supersedes=C))]
        self.assertEqual(self.ids(recs, ["t"]), [B, D])
        recs = [rec(dec(A, question="t", effect="one-off")), rec(dec(B, supersedes=A, question="t"))]
        self.assertEqual(self.ids(recs, ["t"]), [B])

    def test_include_all(self):  # N11, Q-1b2-7
        recs = [rec(dec(A, "open")), rec(dec(B, "withdrawn")), rec(dec(C, effect="one-off")),
                rec(dec(D, **{"class": "merge-grant"})), rec(dec("DEC-20261031-e2f3")),
                rec(dec("DEC-20261031-g4h5", supersedes="DEC-20261031-e2f3"))]
        self.assertEqual(self.ids(recs, ["q"], all_=True), [r.id for r in recs])

    def test_filters_combine(self):  # N12
        recs = [rec(dec(A, question="alpha", applies_to=["src/*"], topics=["ids"]))]
        self.assertEqual(self.ids(recs, ["alpha"], "src/a", "ids"), [A])
        for args in ((["beta"], "src/a", "ids"), (["alpha"], "doc/a", "ids"), (["alpha"], "src/a", "x")):
            with self.subTest(args):
                self.assertEqual(self.ids(recs, args[0], args[1], args[2]), [])

    def test_missing_fields(self):  # N13
        r = rec({"id": A, "status": "answered", "effect": "lasting", "class": "scope"})
        self.assertEqual(self.ids([r], ["x"]), [])
        self.assertEqual(self.ids([r], []), [A])
        self.assertEqual(self.ids([r], [], "a/b"), [])
        self.assertEqual(self.ids([r], [], None, "t"), [])

    def test_fork_raises_in_find(self):  # Q-1b2-4
        recs = [rec(dec(A, question="t")), rec(dec(B, supersedes=A)), rec(dec(C, supersedes=A))]
        with self.assertRaises(GateError):
            find(recs, ["t"], None, None, False)



class LandedMapReasonTest(GitIsolatedTestCase):
    """Q-U2 / Q-1c0-2 (a): a map cite in landed_in is escaped exactly once (decisions.py:122; task 1c0.1, R13)."""

    def test_decision_reason_with_map_item_escaped_once(self):
        make_repo(self.work)
        errs = landed_errors({"id": A, "landed_in": [{"k": "a\\b"}]}, self.work, cfg_default(), frozenset())
        self.assertEqual(errs, ["landed_in: {k: a\\b} is not a string"])
        res = Result("x", [])
        res.fail("x.landed", errs[0])
        self.assertEqual(res.render(False), "FAIL x.landed: landed_in: {k: a\\\\b} is not a string\n")
        raised = run_check("x", lambda a: (_ for _ in ()).throw(GateError(errs[0])), []).render(False)
        self.assertEqual(raised, "FAIL x.input: landed_in: {k: a\\\\b} is not a string\n")
        self.assertNotIn("\\\\\\\\", res.render(False))


class FoldTests(unittest.TestCase):
    """Case folding through the frozen Unicode 13.0.0 table (Task U1 rows D1-D9, D11, K1, K3): expected match sets
    are written by hand and the production path is ``find`` on hand-built records. The 40 code points are unassigned
    at 13.0.0, so they fold to themselves on both interpreters (3.13's own ``casefold`` would fold them)."""

    def ids(self, recs, terms=(), topic=None):
        return [r.id for r in find(recs, list(terms), None, topic, False)]

    def test_fold_ascii_case(self):  # D1
        recs = [rec(dec(A, question="strasse", topics=["alpha"]))]
        self.assertEqual(self.ids(recs, ["STRASSE"]), [A])
        self.assertEqual(self.ids(recs, ["StRaSsE", "ALPHA"]), [A])
        self.assertEqual(self.ids(recs, topic="Alpha"), [A])
        self.assertEqual(self.ids(recs, topic="ALPHA"), [A])
        recs = [rec(dec(A, question="STRASSE", topics=["Alpha"]))]
        self.assertEqual(self.ids(recs, ["strasse", "alpha"]), [A])
        self.assertEqual(self.ids(recs, topic="alpha"), [A])
        self.assertEqual(self.ids(recs, ["strassen"]), [])
        self.assertEqual(self.ids(recs, topic="alph"), [])

    def test_fold_full_folding(self):  # D2
        sharp, kelvin, dot, sigma = "stra\u00dfe", "\u212a", "\u0130", "\u03a3\u0391\u03a3"
        cases = [("STRASSE", sharp), ("strasse", "STRA\u1e9eE"), ("strasse", "STRA\u00dfE"), ("STRASSE", "stra\u1e9ee"),
                 ("k", kelvin), (kelvin, "k"), (kelvin, "K"), ("i", dot), ("i\u0307", dot), (dot, "i\u0307"),
                 ("\u03c3\u03b1\u03c3", sigma), ("\u03c3\u03b1\u03c2", sigma), (sigma, "\u03c3\u03b1\u03c2"),
                 ("\u03c2", "\u03c3"), ("ffi", "\ufb03"), ("\ufb03", "FFI")]
        for term, text in cases:
            with self.subTest(term=term, text=text):
                self.assertEqual(self.ids([rec(dec(A, question=text))], [term]), [A])
                self.assertEqual(self.ids([rec(dec(A, answer=text))], [term]), [A])
                self.assertEqual(self.ids([rec(dec(A, topics=[text]))], [term]), [A])
        self.assertEqual(self.ids([rec(dec(A, topics=["\u03c3\u03b1\u03c2"]))], topic=sigma), [A])
        self.assertEqual(self.ids([rec(dec(A, topics=[dot]))], topic="i\u0307"), [A])
        self.assertEqual(self.ids([rec(dec(A, topics=[dot]))], topic="i"), [])
        for term, text in (("k", "l"), ("\u03c3", "\u03c4"), ("ss", "s"), ("i\u0307", "i")):
            with self.subTest(term=term, text=text):
                self.assertEqual(self.ids([rec(dec(A, question=text))], [term]), [])

    def test_fold_forty_topic(self):  # D3, K2
        for cp in FORTY:
            c, target = chr(cp), chr(FORTY_TARGET_313[cp])
            with self.subTest(hex(cp)):
                self.assertEqual(self.ids([rec(dec(A, topics=[target]))], topic=c), [])
                self.assertEqual(self.ids([rec(dec(A, topics=[c]))], topic=target), [])
                self.assertEqual(self.ids([rec(dec(A, topics=[c]))], topic=c), [A])
                self.assertEqual(self.ids([rec(dec(A, topics=[target]))], topic=target), [A])

    def test_fold_forty_term(self):  # D4, K2
        for cp in FORTY:
            c, target = chr(cp), chr(FORTY_TARGET_313[cp])
            with self.subTest(hex(cp)):
                self.assertEqual(self.ids([rec(dec(A, question="x" + target + "y"))], [c]), [])
                self.assertEqual(self.ids([rec(dec(A, question="x" + c + "y"))], [target]), [])
                self.assertEqual(self.ids([rec(dec(A, question="x" + c + "y"))], [c]), [A])
                self.assertEqual(self.ids([rec(dec(A, question="x" + target + "y"))], [target]), [A])

    def test_fold_forty_row_text(self):  # D5, K2
        for cp in FORTY:
            c, target = chr(cp), chr(FORTY_TARGET_313[cp])
            for field in ("question", "answer", "topics"):
                with self.subTest(hex(cp), field=field):
                    def row(s):
                        return [rec(dec(A, **{field: [s] if field == "topics" else s}))]
                    self.assertEqual(self.ids(row("a" + c + "b"), [target]), [])
                    self.assertEqual(self.ids(row("a" + c + "b"), [c]), [A])
                    self.assertEqual(self.ids(row("a" + c + "b"), ["a" + c + "b"]), [A])
                    self.assertEqual(self.ids(row("a" + c + "b"), ["a" + target + "b"]), [])

    def test_fold_surrogate(self):  # D6
        recs = [rec(dec(A, question="a\udc80", topics=["\udc80"]))]
        self.assertEqual(self.ids(recs, ["\udc80"]), [A])
        self.assertEqual(self.ids(recs, ["\udc81"]), [])
        self.assertEqual(self.ids(recs, topic="\udc80"), [A])
        self.assertEqual(self.ids(recs, topic="\udc81"), [])

    def test_fold_empty(self):  # D7
        self.assertEqual(self.ids([rec(dec(A, question="q"))], [""]), [A])
        self.assertEqual(self.ids([rec(dec(A, question=None, answer=None, topics=[]))], [""]), [])
        self.assertEqual(self.ids([rec(dec(A, topics=[""]))], topic=""), [A])
        self.assertEqual(self.ids([rec(dec(A, topics=["a"]))], topic=""), [])

    def test_fold_non_str(self):  # D8
        recs = [rec(dec(A, question=5, answer=None, topics=[["alpha"], 7, "alpha"]))]
        self.assertEqual(self.ids(recs, ["ALPHA"]), [A])
        self.assertEqual(self.ids(recs, topic="alpha"), [A])
        self.assertEqual(self.ids([rec(dec(A, question=5, answer=None, topics=[]))], ["5"]), [])
        for bad in (5, None, b"alpha", ["alpha"]):  # as a topic, None means no topic filter: not tested there
            with self.subTest(repr(bad)):
                with self.assertRaises(TypeError) as cm:
                    self.ids(recs, [bad])
                self.assertEqual(str(cm.exception), "_fold() argument must be str, not %s" % type(bad).__name__)
                if bad is not None:
                    with self.assertRaises(TypeError):
                        self.ids(recs, topic=bad)

    def test_fold_str_subclass(self):  # D9: the characters decide, never the subclass's own methods
        class Liar(str):
            def casefold(self):
                return "zzz"

            def __iter__(self):
                return iter("zz")

            def __eq__(self, other):
                return True

            def __hash__(self):
                return 1

        recs = [rec(dec(A, question="ab", topics=["ab"]))]
        self.assertEqual(self.ids(recs, [Liar("AB")]), [A])
        self.assertEqual(self.ids(recs, [Liar("zz")]), [])
        self.assertEqual(self.ids(recs, topic=Liar("AB")), [A])
        self.assertEqual(self.ids(recs, topic=Liar("zz")), [])
        # a row text that is a str subclass is skipped, as before (the exact-type test of _texts)
        self.assertEqual(self.ids([rec(dec(A, question=Liar("alpha"), answer=None))], ["alpha"]), [])

    def test_skeleton_digit_runs(self):  # K1: numeric text at and past the int() digit limit
        for n in (4300, 4301):
            d = "1" * n
            with self.subTest(n=n):
                self.assertEqual(self.ids([rec(dec(A, question=d, topics=[d]))], [d], topic=d), [A])
                self.assertEqual(self.ids([rec(dec(A, question=d + "2", topics=[d + "2"]))], [d], topic=d), [])

    def test_decisions_no_case_method(self):  # D11, G4
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gates", "lib",
                            "decisions.py")
        with open(path, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        methods = ("lower", "casefold", "upper", "swapcase", "title", "capitalize")
        self.assertEqual([n.lineno for n in ast.walk(tree) if isinstance(n, ast.Attribute) and n.attr in methods], [])
        mods = [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
        mods += [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
        self.assertNotIn("unicodedata", mods)

    def test_skeleton_no_handler(self):  # K3: nothing in the fold path catches an exception
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gates", "lib",
                            "decisions.py")
        with open(path, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        funcs = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
        for name in ("_fold", "_texts", "_matches"):
            self.assertIn(name, funcs)
            self.assertEqual([n for n in ast.walk(funcs[name]) if isinstance(n, (ast.Try, ast.ExceptHandler))], [],
                             name)


if __name__ == "__main__":
    unittest.main()
