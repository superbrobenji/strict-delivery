"""Tests for the schema migration registry (gates.lib.migrations, Task 2a.1). Expected rows are written out
literally, never computed by ``migrate``; the input is compared with a deep copy taken before the call. The
schema tags here are literal because a tag or a version is these tests' subject (Global Constraints "Test
fixtures": migration tests are exempt)."""
import copy
import os
import tempfile
import unittest
from unittest import mock

from gates.lib import migrations, schema
from gates.lib.decisions import validate
from gates.lib.config import DEFAULTS
from gates.lib.migrations import MIGRATIONS, current_version, migrate

A = "DEC-20261031-k3f9"
OPT = {"label": "yes", "cost": "none"}
OPT2 = {"label": "no", "cost": "some"}
ROW_V1 = {"schema": "decision/1", "id": A, "status": "open", "class": "scope", "question": "Keep X?",
          "options": [OPT, OPT2], "asked_at": "a1b2c3d", "asked_by": "agent", "topics": ["ids"],
          "applies_to": ["src/*"], "checked_against": [], "effect": "lasting"}
ANSWERED_V1 = {**ROW_V1, "status": "answered", "answer": "Yes", "answered_at": {"at": "b2c3d4e", "by": "w@x.invalid"},
               "rule": "Keep X.", "landed_in": ["CLAUDE.md"]}
WITHDRAWN_V1 = {**ROW_V1, "status": "withdrawn", "withdrawn": {"at": "a1b2c3d", "by": "w@x.invalid", "reason": "r"}}


class S(str):
    pass


class D(dict):
    pass


class RegistryTests(unittest.TestCase):
    def test_registered_steps(self):  # R1; spec 15 "every migration is tested from an old fixture"
        self.assertEqual(set(MIGRATIONS), {("decision", 1)})

    def test_current_version_reads_schema_file(self):  # V1
        self.assertEqual(current_version("decision"), 2)
        self.assertEqual(current_version("finding"), 1)
        self.assertEqual(current_version("config"), 1)

    def test_current_version_follows_the_schemas_dir(self):  # V1: read from the file, never a literal
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(schema.SCHEMAS_DIR, "decision.yml"), encoding="utf-8") as fh:
                text = fh.read()
            with open(os.path.join(d, "decision.yml"), "w", encoding="utf-8") as fh:
                fh.write(text.replace("version: 2\n", "version: 7\n", 1))
            with mock.patch.object(schema, "SCHEMAS_DIR", d):
                self.assertEqual(current_version("decision"), 7)

    def test_missing_or_broken_schema_file_raises(self):  # V2
        with self.assertRaises(schema.SchemaError):
            current_version("claim")  # no claim.yml before Task 2a.2
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "decision.yml"), "w", encoding="utf-8") as fh:
                fh.write("kind: decision\nversion: 0\nformat: yaml\n")
            with mock.patch.object(schema, "SCHEMAS_DIR", d):
                with self.assertRaises(schema.SchemaError) as cm:
                    current_version("decision")
                self.assertIn("version: must be a positive integer", str(cm.exception))
                with self.assertRaises(schema.SchemaError):
                    migrate("decision", {**ROW_V1})  # passes through migrate too

    def test_unknown_kind_raises_without_opening_a_file(self):  # V3
        for kind in ("widget", "../schemas/decision", "Decision", "", 1, None, S("decision"), "decision "):
            with self.subTest(repr(kind)):
                with mock.patch.object(schema, "load_schema", side_effect=AssertionError("file read")):
                    with self.assertRaises(schema.SchemaError) as cm:
                        current_version(kind)
                self.assertEqual(str(cm.exception), "%s: not a known schema kind" % (kind,))


class MigrateTests(unittest.TestCase):
    def test_decision_1_migrates_to_2(self):  # M1
        row = {**ROW_V1}
        self.assertEqual(migrate("decision", row), {**ROW_V1, "schema": "decision/2"})
        self.assertEqual(ROW_V1["schema"], "decision/1")
        self.assertEqual(row["schema"], "decision/1")

    def test_every_status_from_an_old_fixture(self):  # R2
        expected = {
            "open": {"schema": "decision/2", "id": A, "status": "open", "class": "scope", "question": "Keep X?",
                     "options": [{"label": "yes", "cost": "none"}, {"label": "no", "cost": "some"}],
                     "asked_at": "a1b2c3d", "asked_by": "agent", "topics": ["ids"], "applies_to": ["src/*"],
                     "checked_against": [], "effect": "lasting"},
        }
        expected["answered"] = {**expected["open"], "status": "answered", "answer": "Yes",
                                "answered_at": {"at": "b2c3d4e", "by": "w@x.invalid"}, "rule": "Keep X.",
                                "landed_in": ["CLAUDE.md"]}
        expected["withdrawn"] = {**expected["open"], "status": "withdrawn",
                                 "withdrawn": {"at": "a1b2c3d", "by": "w@x.invalid", "reason": "r"}}
        for name, row in (("open", ROW_V1), ("answered", ANSWERED_V1), ("withdrawn", WITHDRAWN_V1)):
            with self.subTest(name):
                before = copy.deepcopy(row)
                got = migrate("decision", row)
                self.assertEqual(got, expected[name])
                self.assertIsNot(got, row)
                self.assertEqual(row, before)
                self.assertEqual(list(got), list(row))  # key order kept: only the tag's value changes

    def test_result_shares_no_nested_value(self):  # R3
        row = copy.deepcopy(ANSWERED_V1)
        before = copy.deepcopy(row)
        got = migrate("decision", row)
        got["options"][0]["label"] = "changed"
        got["options"].append({"label": "x", "cost": "y"})
        got["answered_at"]["by"] = "changed"
        got["topics"].append("t")
        self.assertEqual(row, before)

    def test_unmigratable_rows_unchanged(self):  # M2-M5
        rows = ([], "x", None, 1, D(ROW_V1), {}, {"id": A}, {**ROW_V1, "schema": "decision/01"},
                {**ROW_V1, "schema": "decision/1 "}, {**ROW_V1, "schema": "Decision/1"},
                {**ROW_V1, "schema": "decision"}, {**ROW_V1, "schema": 1}, {**ROW_V1, "schema": None},
                {**ROW_V1, "schema": S("decision/1")}, {"schema": "finding/1"}, {"schema": "decision/0"},
                {**ROW_V1, "schema": "decision/2"}, {"schema": "decision/9"})
        for row in rows:
            with self.subTest(repr(row)[:60]):
                before = copy.deepcopy(row)
                self.assertIs(migrate("decision", row), row)
                self.assertEqual(row, before)

    def test_gap_in_the_registry_leaves_the_row(self):  # M6
        with mock.patch.object(migrations, "current_version", return_value=3):
            row = {**ROW_V1}
            self.assertIs(migrate("decision", row), row)
            self.assertEqual(row["schema"], "decision/1")

    def test_steps_apply_in_order(self):  # M7
        calls = []

        def step2(row):
            calls.append(row["schema"])
            return {**row, "schema": "decision/3", "seen": list(calls)}

        def step1(row):
            calls.append(row["schema"])
            return {**row, "schema": "decision/2"}

        with mock.patch.object(migrations, "current_version", return_value=3), \
                mock.patch.dict(MIGRATIONS, {("decision", 1): step1, ("decision", 2): step2}):
            got = migrate("decision", {**ROW_V1})
            self.assertEqual(got, {**ROW_V1, "schema": "decision/3", "seen": ["decision/1", "decision/2"]})
            self.assertEqual(calls, ["decision/1", "decision/2"])
            calls.clear()
            got2 = migrate("decision", {**ROW_V1, "schema": "decision/2"})
            self.assertEqual(got2["schema"], "decision/3")
            self.assertEqual(calls, ["decision/2"])

    def test_migrate_never_validates(self):  # M8
        bad = {"schema": "decision/1", "id": "x", "status": "done", "zzz": [1, {"a": None}]}
        self.assertEqual(migrate("decision", bad), {"schema": "decision/2", "id": "x", "status": "done",
                                                    "zzz": [1, {"a": None}]})

    def test_row_checks_come_first(self):  # M9
        with mock.patch.object(schema, "load_schema", side_effect=AssertionError("file read")):
            for row in ([], None, "decision/1"):
                self.assertIs(migrate("widget", row), row)
            for row in ({"schema": "finding/1"}, {}, {"schema": "decision/2 "}):
                self.assertIs(migrate("decision", row), row)
        with self.assertRaises(schema.SchemaError):
            migrate("widget", {"schema": "widget/1"})

    def test_bad_kind_with_a_mapping_raises(self):  # M10
        for kind in (1, None, "decision ", S("decision"), "widget"):
            for row in ({**ROW_V1}, {"schema": "finding/1"}, {}):
                with self.subTest(kind=repr(kind), row=repr(row)[:30]):
                    with self.assertRaises(schema.SchemaError):
                        migrate(kind, row)

    def test_migrated_row_without_new_fields_valid(self):  # RC10, SC8; design 5
        cfg = copy.deepcopy(DEFAULTS)
        for row in (ROW_V1, ANSWERED_V1, WITHDRAWN_V1):
            with self.subTest(row["status"]):
                got = migrate("decision", copy.deepcopy(row))
                self.assertNotIn("recommended", got)
                self.assertNotIn("source", got)
                self.assertNotIn("overrides", got)
                self.assertEqual(validate(got, cfg), [])


if __name__ == "__main__":
    unittest.main()
