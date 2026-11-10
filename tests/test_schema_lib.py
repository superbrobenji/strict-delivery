"""Tests of gates/lib/schema.py; rows K1-K7, L1-L13, T1-T16, R1-R9, G1-G3, M1-M5, P1-P3, F1-F6 of the 1b.1 table."""
import copy
import fnmatch
import os
import re
import tempfile
import unittest
from unittest import mock

from gates.lib import config, schema, yamlsub
from gates.lib.result import GateError
from gates.lib.schema import KNOWN_KINDS, SchemaError, files_of, load_schema, produced_kinds, schemas, validate
from gates.lib.schema import validate_markdown
from tests.helpers import GitIsolatedTestCase, commit_all, make_repo

NOT_ALLOWED = ("%s, which is not allowed: inside [ ] use an optional leading ! then characters or ranges x-y "
               "(x <= y) of printable ASCII other than ! - [ \\ ] ^ & ~ |")


def _words(atoms: str, top: int) -> list:
    out, layer = [], [""]
    for _ in range(top):
        layer = [w + a for w in layer for a in atoms]
        out += layer
    return out


def _ref_match(name: str, pat: str) -> bool:
    """Pure-Python reference of fnmatchcase for a glob the schema accepts: * ? literals, an unclosed [ as a
    literal, and [!? characters or ranges x-y]."""
    toks, i, n = [], 0, len(pat)
    while i < n:
        c = pat[i]
        i += 1
        if c == "[":
            j = i + (pat[i:i + 1] == "!")
            j += pat[j:j + 1] == "]"
            j = pat.find("]", j)
            if j >= 0:
                body = pat[i:j]
                neg = body[:1] == "!"
                items, ranges, k = body[neg:], [], 0
                while k < len(items):
                    if items[k + 1:k + 2] == "-" and k + 2 < len(items):
                        ranges.append((items[k], items[k + 2]))
                        k += 3
                    else:
                        ranges.append((items[k], items[k]))
                        k += 1
                toks.append(("C", neg, ranges))
                i = j + 1
                continue
        toks.append(("*",) if c == "*" else ("?",) if c == "?" else ("L", c))

    def m(t: int, s: int) -> bool:
        if t == len(toks):
            return s == len(name)
        tok = toks[t]
        if tok[0] == "*":
            return any(m(t + 1, k) for k in range(s, len(name) + 1))
        if s == len(name):
            return False
        ch = name[s]
        if tok[0] == "C":
            ok = any(lo <= ch <= hi for lo, hi in tok[2]) != tok[1]
        else:
            ok = tok[0] == "?" or ch == tok[1]
        return ok and m(t + 1, s + 1)
    return m(0, 0)


CFG = copy.deepcopy(config.DEFAULTS)
BASE = {"kind": "thing", "version": 1, "format": "yaml", "files": [{"path": "config"}],
        "fields": {"schema": {"type": "str"}}}


class Dirs(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.tmp = os.path.realpath(td.name)
        self.sd = os.path.join(self.tmp, "schemas")
        os.mkdir(self.sd)

    def put(self, name, data, raw=False):
        path = os.path.join(self.sd, name)
        with open(path, "wb") as fh:
            fh.write(data if isinstance(data, bytes) else (data if raw else yamlsub.emit(data)).encode("utf-8"))
        return path

    def sch(self, fields=None, kind="thing", **over):
        d = copy.deepcopy(BASE)
        d["kind"] = kind
        if fields is not None:
            d["fields"] = dict(d["fields"], **fields)
        d.update(over)
        return load_schema(self.put(kind + ".yml", d))

    def bad(self, data, name="thing.yml", raw=False):
        path = self.put(name, data, raw)
        with self.assertRaises(SchemaError) as cm:
            load_schema(path)
        return path, str(cm.exception)

    def md(self, **over):
        d = {"kind": "in-force", "version": 1, "format": "markdown", "files": [{"path": "config"}],
             "first_line": "<!-- schema: in-force/1 -->"}
        d.update(over)
        return load_schema(self.put("in-force.yml", d))


def rt(d):
    """The value yamlsub.load gives for a file written by emit (the production read path)."""
    return yamlsub.parse(yamlsub.emit(d))


class KnownKinds(unittest.TestCase):
    def test_K1_known_kinds_match_appendix(self):
        self.assertEqual(KNOWN_KINDS, ("config", "decision", "finding", "claim", "request", "streams", "context",
                                       "handoff", "ledger", "status", "sync-log", "overview", "in-force",
                                       "decision-index", "finding-index", "mutation-transcript", "review-report",
                                       "receipt", "claude-block", "gitignore-block"))

    def test_K1_generated_set_is_the_four(self):  # N3 data
        self.assertEqual(schema.GENERATED_KINDS, ("decision-index", "finding-index", "in-force", "overview"))


class SchemasDir(Dirs):
    def test_K6_default_dir_loads_and_stems_known(self):
        got = schemas()
        self.assertEqual(sorted(got), ["claim", "config", "decision", "decision-index", "finding", "finding-index",
                                       "in-force", "overview"])  # Task 1c.3 adds the four generated kinds
        self.assertTrue(all(stem in KNOWN_KINDS for stem in got))

    def test_K6_fixture_dir_and_bad_file_raises_naming_it(self):
        self.put("decision.yml", dict(BASE, kind="decision"))
        self.assertEqual(sorted(schemas(self.sd)), ["decision"])
        path = self.put("claim.yml", dict(BASE, kind="claim", version=0))
        with self.assertRaises(SchemaError) as cm:
            schemas(self.sd)
        self.assertEqual(str(cm.exception), "%s: version: must be a positive integer" % path)

    def test_K2_unknown_stems_are_problems_not_schemas(self):
        self.put("widget.yml", dict(BASE, kind="widget"))
        self.put("Config.yml", dict(BASE, kind="Config"))
        self.put("decision.yml", dict(BASE, kind="decision"))
        loaded, problems = schema.scan_dir(self.sd)
        self.assertEqual(sorted(loaded), ["decision"])
        self.assertEqual(problems, [
            ("Config", "Config.yml: kind 'Config' is not in KNOWN_KINDS"),
            ("widget", "widget.yml: kind 'widget' is not in KNOWN_KINDS")])
        with self.assertRaises(SchemaError):
            schemas(self.sd)

    def test_K3_other_entries_are_problems(self):
        self.put("x.yaml", "a: 1\n", raw=True)
        self.put("README.md", "x", raw=True)
        os.mkdir(os.path.join(self.sd, "sub"))
        outside = os.path.join(self.tmp, "outside.yml")
        with open(outside, "w") as fh:
            fh.write(yamlsub.emit(dict(BASE, kind="config")))
        os.symlink(outside, os.path.join(self.sd, "config.yml"))
        os.mkfifo(os.path.join(self.sd, "x.yml"))
        loaded, problems = schema.scan_dir(self.sd)  # must not block on the FIFO
        self.assertEqual(loaded, {})
        self.assertEqual(sorted(problems), [
            ("README.md", "README.md: not a regular *.yml schema file"),
            ("config.yml", "config.yml: not a regular *.yml schema file"),
            ("sub", "sub: not a regular *.yml schema file"),
            ("x.yaml", "x.yaml: not a regular *.yml schema file"),
            ("x.yml", "x.yml: not a regular *.yml schema file")])

    def test_K5_one_bad_file_among_good(self):
        self.put("decision.yml", dict(BASE, kind="decision"))
        bad = self.put("claim.yml", dict(BASE, kind="claim", format="json"))
        loaded, problems = schema.scan_dir(self.sd)
        self.assertEqual(sorted(loaded), ["decision"])
        self.assertEqual(problems, [("claim", "%s: format: must be yaml or markdown" % bad)])

    def test_K3_missing_dir_is_empty_unreadable_dir_raises(self):
        self.assertEqual(schema.scan_dir(os.path.join(self.tmp, "nope")), ({}, []))
        afile = self.put("afile.yml", "x: 1\n", raw=True)
        with self.assertRaises(SchemaError) as cm:
            schema.scan_dir(afile)
        self.assertEqual(str(cm.exception), "%s: cannot read the schemas directory (Not a directory)" % afile)


class LoadSchema(Dirs):
    def test_L1_unreadable_files(self):
        p, m = self.bad("a: [b", raw=True)
        self.assertIn(p, m)
        self.assertIn("(line 1)", m)
        p = os.path.join(self.sd, "nope.yml")
        with self.assertRaises(SchemaError) as cm:
            load_schema(p)
        self.assertIn(p, str(cm.exception))
        os.mkdir(os.path.join(self.sd, "dir.yml"))
        with self.assertRaises(SchemaError) as cm:
            load_schema(os.path.join(self.sd, "dir.yml"))
        self.assertIn("not a regular file", str(cm.exception))
        p, m = self.bad(b"kind: \xff\n", name="thing.yml")
        self.assertIn("not valid UTF-8", m)
        for body in ("- a\n", ""):
            p, m = self.bad(body, raw=True)
            self.assertEqual(m, "%s: top level: must be a mapping" % p)

    def test_L2_kind(self):
        for val in ("other", None, 5, "thing "):
            d = dict(BASE, kind=val)
            p, m = self.bad(d)
            self.assertEqual(m, "%s: kind: must equal the file stem 'thing'" % p, val)
        d = dict(BASE)
        del d["kind"]
        p, m = self.bad(d)
        self.assertEqual(m, "%s: kind: must equal the file stem 'thing'" % p)
        self.assertEqual(self.sch(kind="thing").kind, "thing")

    def test_L3_version(self):
        for val in (0, -1, True, "1"):
            p, m = self.bad(dict(BASE, version=val))
            self.assertEqual(m, "%s: version: must be a positive integer" % p, val)
        d = dict(BASE)
        del d["version"]
        p, m = self.bad(d)
        self.assertEqual(m, "%s: version: must be a positive integer" % p)
        self.assertEqual(self.sch(version=2).version, 2)

    def test_L4_format(self):
        for val in ("json", "YAML", None):
            p, m = self.bad(dict(BASE, format=val))
            self.assertEqual(m, "%s: format: must be yaml or markdown" % p, val)
        d = dict(BASE)
        del d["format"]
        p, m = self.bad(d)
        self.assertEqual(m, "%s: format: must be yaml or markdown" % p)

    def test_L5_top_level_keys_by_format(self):
        p, m = self.bad(dict(BASE, first_line="x"))
        self.assertEqual(m, "%s: first_line: unknown key for a yaml schema" % p)
        p, m = self.bad(dict(BASE, kinds=[]))
        self.assertEqual(m, "%s: kinds: unknown key for a yaml schema" % p)
        d = dict(BASE)
        del d["fields"]
        p, m = self.bad(d)
        self.assertEqual(m, "%s: fields: required key is missing" % p)
        md = {"kind": "thing", "version": 1, "format": "markdown", "files": [{"path": "config"}], "first_line": "x"}
        self.assertEqual(load_schema(self.put("thing.yml", md)).first_line, "x")
        p, m = self.bad(dict(md, fields={"schema": {"type": "str"}}))
        self.assertEqual(m, "%s: fields: unknown key for a markdown schema" % p)
        d = dict(md)
        del d["first_line"]
        p, m = self.bad(d)
        self.assertEqual(m, "%s: first_line: required key is missing" % p)
        p, m = self.bad(dict(md, table=["a"], headings=["## A"]))
        self.assertEqual(m, "%s: headings: table and headings cannot both be given" % p)
        for key, val in (("first_line", ""), ("first_line", 5), ("table", []), ("table", ["a", ""]),
                         ("headings", ["A"]), ("headings", "## A")):
            p, m = self.bad(dict(md, **{key: val}))
            self.assertIn("%s: %s: " % (p, key), m, (key, val))
        self.assertEqual(load_schema(self.put("thing.yml", dict(md, table=["a", "b"]))).table, ["a", "b"])
        self.assertEqual(load_schema(self.put("thing.yml", dict(md, headings=["## A"]))).headings, ["## A"])

    def test_L6_files(self):
        ok = [{"path": "config"}, {"dir": "decisions", "glob": "*.yml", "exclude": ["index.yml"]},
              {"dir": "findings", "glob": "*.yml"}]
        self.assertEqual(self.sch(files=ok).files, ok)
        cases = [([], "files", "must be a non-empty list"), ("x", "files", "must be a non-empty list"),
                 (["x"], "files.0", "must be a mapping"),
                 ([{"path": "config", "dir": "d", "glob": "*"}], "files.0", "a path item is exactly {path: <paths key>}"),
                 ([{"path": ""}], "files.0", "a path item is exactly {path: <paths key>}"),
                 ([{"dir": "decisions"}], "files.0.glob", "a dir item needs a non-empty string dir and glob"),
                 ([{"glob": "*"}], "files.0.dir", "a dir item needs a non-empty string dir and glob"),
                 ([{"dir": "d", "glob": ""}], "files.0.glob", "a dir item needs a non-empty string dir and glob"),
                 ([{"dir": "d", "glob": "*[z-a]"}], "files.0.glob",
                  "must be a supported glob: the bracket expression [z-a] holds the reversed range z-a"),
                 ([{"dir": "d", "glob": "*", "other": 1}], "files.0.other", "unknown key"),
                 ([{"dir": "d", "glob": "*", "exclude": "a"}], "files.0.exclude", "must be a list of strings"),
                 ([{"dir": "d", "glob": "*", "exclude": [1]}], "files.0.exclude", "must be a list of strings")]
        for files, key, problem in cases:
            p, m = self.bad(dict(BASE, files=files))
            self.assertEqual(m, "%s: %s: %s" % (p, key, problem), files)
        d = dict(BASE)
        del d["files"]
        p, m = self.bad(d)
        self.assertEqual(m, "%s: files: required key is missing" % p)

    def test_L7_field_type(self):
        for t in schema.TYPES:
            extra = {"enum": {"values": ["a"]}, "list": {"items": {"type": "str"}}, "map": {"fields": {"x": {"type": "str"}}},
                     "id": {"id_kind": "decision"}}.get(t, {})
            self.sch({"v": dict(type=t, **extra)})
        self.assertEqual(len(schema.TYPES), 13)
        for t in ("string", "float", None, 5):
            p, m = self.bad(dict(BASE, fields={"schema": {"type": "str"}, "v": {"type": t}}))
            self.assertTrue(m.startswith("%s: fields.v.type: must be one of str, text" % p), m)
        p, m = self.bad(dict(BASE, fields={"schema": {"type": "str"}, "v": {"required": False}}))
        self.assertTrue(m.startswith("%s: fields.v.type: must be one of" % p))
        p, m = self.bad(dict(BASE, fields={"schema": {"type": "str"}, "v": "str"}))
        self.assertEqual(m, "%s: fields.v: a field spec must be a mapping" % p)
        p, m = self.bad(dict(BASE, fields=[]))
        self.assertEqual(m, "%s: fields: must be a mapping of field names to specs" % p)

    def test_L8_unknown_spec_key(self):
        p, m = self.bad(dict(BASE, fields={"schema": {"type": "str"}, "v": {"type": "str", "default": "x"}}))
        self.assertEqual(m, "%s: fields.v.default: unknown field-spec key" % p)
        self.sch({"v": {"type": "str", "required": False, "nullable": True}})

    def test_L9_key_not_applicable_to_type(self):
        cases = [({"type": "str", "values": ["a"]}, "values", "not used by type str"),
                 ({"type": "bool", "min": 1}, "min", "not used by type bool"),
                 ({"type": "list"}, "items", "required by type list"),
                 ({"type": "map"}, "fields", "required by type map"),
                 ({"type": "any-map", "fields": {"x": {"type": "str"}}}, "fields", "not used by type any-map"),
                 ({"type": "id"}, "id_kind", "required by type id"),
                 ({"type": "id", "id_kind": "widget"}, "id_kind", "must be one of decision, finding, claim, request"),
                 ({"type": "enum"}, "values", "required by type enum"),
                 ({"type": "enum", "values": []}, "values", None),
                 ({"type": "enum", "values": "a"}, "values", None),
                 ({"type": "str", "items": {"type": "str"}}, "items", "not used by type str"),
                 ({"type": "str", "id_kind": "decision"}, "id_kind", "not used by type str")]
        for spec, key, problem in cases:
            p, m = self.bad(dict(BASE, fields={"schema": {"type": "str"}, "v": spec}))
            self.assertTrue(m.startswith("%s: fields.v.%s: " % (p, key)), m)
            if problem:
                self.assertEqual(m, "%s: fields.v.%s: %s" % (p, key, problem))

    def test_L10_key_value_types(self):
        for key, val in (("required", 1), ("required", "yes"), ("nullable", 0), ("nullable", "no")):
            p, m = self.bad(dict(BASE, fields={"schema": {"type": "str"}, "v": {"type": "str", key: val}}))
            self.assertEqual(m, "%s: fields.v.%s: must be true or false" % (p, key), (key, val))
        for val in (True, -1, "1"):
            p, m = self.bad(dict(BASE, fields={"schema": {"type": "str"}, "v": {"type": "int", "min": val}}))
            self.assertEqual(m, "%s: fields.v.min: must be an integer of at least 0" % p, val)
        self.sch({"v": {"type": "int", "min": 0}})
        for vals in (["a", 1], [1, True], [[1]], [None]):
            p, m = self.bad(dict(BASE, fields={"schema": {"type": "str"}, "v": {"type": "enum", "values": vals}}))
            self.assertEqual(m, "%s: fields.v.values: must be a non-empty list of strings, or of integers, "
                                "or of booleans" % p, vals)
        self.sch({"v": {"type": "enum", "values": [1, 2]}})
        self.sch({"v": {"type": "enum", "values": [True]}})

    def test_L11_condition_lists(self):
        def f(**kw):
            return {"schema": {"type": "str"}, "status": {"type": "str"}, "a": dict(type="str", required=False, **kw)}
        for key in ("required_when", "absent_when"):
            self.sch({"status": {"type": "str"}, "a": {"type": "str", "required": False,
                                                       key: [{"status": ["x"]}]}})
            for conds, problem in (("x", "must be a list of conditions"),
                                   (["x"], "each condition must be a mapping"),
                                   ([{"zzz": ["x"]}], "condition names 'zzz', which this map does not declare")):
                p, m = self.bad(dict(BASE, fields=f(**{key: conds})))
                self.assertEqual(m, "%s: fields.a.%s: %s" % (p, key, problem), (key, conds))
            p, m = self.bad(dict(BASE, fields=f(**{key: [{"status": "x"}]})))
            self.assertEqual(m, "%s: fields.a.%s.status: must be a list of values" % (p, key))
            p, m = self.bad(dict(BASE, fields=f(**{key: [{"status": [[1]]}]})))
            self.assertEqual(m, "%s: fields.a.%s.status: must be a list of values" % (p, key))

    def test_L11_conditions_in_nested_map_name_nested_siblings(self):
        nested = {"type": "map", "fields": {"kind": {"type": "str"},
                                            "n": {"type": "int", "required_when": [{"kind": ["issue"]}]}}}
        self.sch({"o": nested})
        nested["fields"]["n"]["required_when"] = [{"schema": ["x"]}]  # a top-level key, not a sibling
        p, m = self.bad(dict(BASE, fields={"schema": {"type": "str"}, "o": nested}))
        self.assertEqual(m, "%s: fields.o.fields.n.required_when: condition names 'schema', "
                            "which this map does not declare" % p)
        item = {"type": "list", "items": {"type": "str", "required_when": [{"schema": ["x"]}]}}
        p, m = self.bad(dict(BASE, fields={"schema": {"type": "str"}, "l": item}))
        self.assertIn("fields.l.items.required_when: condition names 'schema'", m)

    def test_L12_absent_when_on_required_field(self):
        base = {"status": {"type": "str"}}
        for extra in ({}, {"required": True}):
            p, m = self.bad(dict(BASE, fields=dict({"schema": {"type": "str"}}, **base, a=dict(
                type="str", absent_when=[{"status": ["open"]}], **extra))))
            self.assertEqual(m, "%s: fields.a: absent_when on a required field can never be satisfied; "
                                "write required: false or a required_when" % p)
        self.sch(dict(base, a={"type": "str", "required": False, "absent_when": [{"status": ["open"]}]}))
        self.sch(dict(base, a={"type": "str", "absent_when": [{"status": ["open"]}],
                               "required_when": [{"status": ["done"]}]}))

    def test_L13_schema_field(self):
        d = dict(BASE, fields={"v": {"type": "str"}})
        p, m = self.bad(d)
        self.assertEqual(m, "%s: fields.schema: must be declared as a required, non-nullable str" % p)
        for spec in ({"type": "text"}, {"type": "str", "required": False}, {"type": "str", "nullable": True},
                     {"type": "str", "required_when": [{"schema": ["x"]}]}):
            p, m = self.bad(dict(BASE, fields={"schema": spec}))
            self.assertTrue(m.startswith("%s: fields.schema" % p), (spec, m))


class Types(Dirs):
    def run_types(self, spec, cases, **kw):
        s = self.sch({"v": dict(spec, required=False)}, **kw)
        for value, expected in cases:
            with self.subTest(spec=spec["type"], value=repr(value)):
                self.assertEqual(validate(s, {"schema": "thing/1", "v": value}, CFG),
                                 [e if e.startswith("v.") else "v: " + e for e in expected])

    def test_T1_str(self):
        class S(str):
            pass
        m = "must be a non-empty string"
        self.run_types({"type": "str"}, [("a", []), ("", [m]), (S("a"), [m]), (1, [m]), (None, ["must not be null"]),
                                         (True, [m]), (["a"], [m])])

    def test_T2_text(self):
        class S(str):
            pass
        m = "must be a string"
        self.run_types({"type": "text"}, [("", []), ("a\nb", []), (S("a"), [m]), (1, [m]), (None, ["must not be null"])])

    def test_T3_int_min(self):
        class I(int):
            pass
        m = "must be an integer"
        self.run_types({"type": "int", "min": 1}, [(0, ["must be at least 1"]), (1, []), (2, []), (True, [m]),
                                                    (False, [m]), (I(2), [m]), (1.0, [m]), ("1", [m]),
                                                    (None, ["must not be null"])])
        self.run_types({"type": "int"}, [(-5, []), (0, [])])

    def test_T4_bool(self):
        m = "must be true or false"
        self.run_types({"type": "bool"}, [(True, []), (False, []), (1, [m]), (0, [m]), ("true", [m]),
                                          (None, ["must not be null"])])

    def test_T5_enum(self):
        m = "must be one of a, b"
        self.run_types({"type": "enum", "values": ["a", "b"]}, [("a", []), ("b", []), ("c", [m]), (1, [m]), ("A", [m])])
        self.run_types({"type": "enum", "values": ["1"]}, [("1", []), (1, ["must be one of 1"]),
                                                           (True, ["must be one of 1"])])
        self.run_types({"type": "enum", "values": [1]}, [(1, []), (True, ["must be one of 1"]),
                                                         ("1", ["must be one of 1"])])

    def test_T6_list(self):
        items = {"type": "list", "items": {"type": "str"}}
        self.run_types(items, [([], []), (["a", "b"], []), (["a", "b", 3], ["v.2: must be a non-empty string"]),
                               (("a",), ["must be a list"]), ("a", ["must be a list"]),
                               (None, ["must not be null"]), (["", None], ["v.0: must be a non-empty string",
                                                                           "v.1: must not be null"])])
        self.run_types(dict(items, min=1), [([], ["must hold at least 1 items"]), (["a"], [])])

    def test_T7_map(self):
        spec = {"type": "map", "fields": {"a": {"type": "int"}, "b": {"type": "int", "required": False}}}
        self.run_types(spec, [({"a": 1}, []), ({"a": 1, "b": 2}, []), ({"a": 1, "c": 2}, ["v.c: unknown key"]),
                              ({}, ["v.a: required key is missing"]), ([], ["must be a mapping"]),
                              (None, ["must not be null"]), ({"a": True}, ["v.a: must be an integer"])])

    def test_T8_any_map(self):
        m = "must be a mapping"
        self.run_types({"type": "any-map"}, [({}, []), ({"x": [1]}, []), ([], [m]), ("x", [m]),
                                             (None, ["must not be null"])])

    def test_T9_id(self):
        class S(str):
            pass
        good = "DEC-20261031-k3f9"
        form = ("expected DEC-<YYYYMMDD>-<xxxx>: a valid calendar date and four characters from "
                "23456789abcdefghijkmnpqrstuvwxyz")
        self.run_types({"type": "id", "id_kind": "decision"}, [
            (good, []), ("F-20261031-k3f9", ["id does not match the form; " + form]),
            ("DEC-20261031-K3F9", ["id does not match the form; " + form]),
            (S(good), ["id is not a string (S); " + form]), (1, ["id is not a string (int); " + form]),
            ("DEC-20261331-k3f9", ["id date 20261331 is not a valid calendar date; " + form])])
        cfg = copy.deepcopy(CFG)
        cfg["ids"]["finding"] = "FX"
        s = self.sch({"v": {"type": "id", "id_kind": "finding"}})
        self.assertEqual(validate(s, {"schema": "thing/1", "v": "FX-20261031-k3f9"}, cfg), [])  # prefix from cfg
        self.assertEqual(len(validate(s, {"schema": "thing/1", "v": "F-20261031-k3f9"}, cfg)), 1)

    def test_T10_sha(self):
        m = "must be 7 to 40 lowercase hex digits"
        self.run_types({"type": "sha"}, [("abc1234", []), ("a" * 40, []), ("abc123", [m]), ("a" * 41, [m]),
                                         ("ABC1234", [m]), ("abc123g", [m]), (1234567, [m]), ("abc1234\n", [m])])

    def test_T11_glob(self):
        m = "must be a non-empty glob"
        self.run_types({"type": "glob"}, [("docs/**", []), ("", [m]), (5, [m])])

    def test_T11b_glob_bracket_grammar(self):  # F-1, U-2 folded into F-1 (D-31)
        ok = ["src/[a-c].py", "[!a-c]x", "a[b]", "[", "a[", "[]", "[!]", "x]", "]", "[ab0-9_.*?/]", "[a-a]",
              "[a-cx-z]", "[!a]", "a é \n[0-9]"]
        bad = [("src/[z-a].py", "z-a", "the reversed range z-a"), ("[b-a]", "b-a", "the reversed range b-a"),
               ("[!z-a]x", "!z-a", "the reversed range z-a"), ("[a-cz-b]", "a-cz-b", "the reversed range z-b"),
               ("ok/[a]/[b-a]", "b-a", "the reversed range b-a")]
        bad += [(g, body, NOT_ALLOWED % cp) for g, body, cp in (
            ("[--!]", "--!", "U+002D"), ("[[-!]", "[-!", "U+005B"), ("![--!]", "--!", "U+002D"),
            ("[a-]", "a-", "U+002D"), ("[-a]", "-a", "U+002D"), ("[^a]", "^a", "U+005E"), ("[a\\b]", "a\\b", "U+005C"),
            ("[a&&b]", "a&&b", "U+0026"), ("[a~~b]", "a~~b", "U+007E"), ("[a||b]", "a||b", "U+007C"),
            ("[]a]", "]a", "U+005D"), ("[!]a]", "!]a", "U+005D"), ("[a-c-e]", "a-c-e", "U+002D"),
            ("[a!]", "a!", "U+0021"), ("[é]", "é", "U+00E9"), ("[ ]", " ", "U+0020"), ("[a-é]", "a-é", "U+00E9"),
            ("[\x7f]", "\x7f", "U+007F"))]
        cases = [(g, []) for g in ok] + [(g, ["must be a supported glob: the bracket expression [%s] holds %s"
                                               % (body, tail)]) for g, body, tail in bad]
        self.run_types({"type": "glob"}, cases)
        for g, want in cases:
            with self.subTest(g=g):
                self.assertEqual(schema.bracket_problem(g), want[0] if want else "")

    def test_T11c_glob_differential(self):
        """For every pattern of the reviewer's space (lengths 1-5 over a z - [ ] !) and of lengths 1-4 over
        a z * ? [ ] ! -, a glob the schema accepts never raises in fnmatch and matches exactly as the pure-Python
        reference matcher of the grammar: so 3.9 and 3.13 agree on it. Every pattern fnmatch raises on is refused."""
        names = ["", "a", "z", "m", "-", "!", "[", "]", "az", "za", "a-", "[a]", "a]", "!a", "zz", "a-z", "]]", "*",
                 "?", "a*", "a?z"]
        pats = [p for atoms, top in (("az-[]!", 5), ("az*?[]!-", 4)) for p in _words(atoms, top)]
        accepted = 0
        for p in pats:
            problem = schema.bracket_problem(p)
            try:
                got = [fnmatch.fnmatchcase(n, p) for n in names]
            except re.error:
                self.assertNotEqual(problem, "", p)
                continue
            if problem == "":
                accepted += 1
                self.assertEqual(got, [_ref_match(n, p) for n in names], p)
        self.assertGreater(accepted, 1000)

    def test_T12_cite(self):
        m = "must be a normalised repo-relative path with an optional non-empty #anchor"
        self.run_types({"type": "cite"}, [
            ("docs/a.md", []), ("docs/a.md#sec", []), ("docs/a.md#", [m]), ("#sec", [m]), ("/abs.md", [m]),
            ("a/../b.md", [m]), ("./a.md", [m]), ("a//b.md", [m]), ("a/", [m]), ("../a.md", [m]), ("..", [m]), ("a\x01b", [m]), ("a.md#x\ny", [m]),
            (5, [m]), ("", [m]), (".", [m]), ("docs/a.md#a#b", [m]), ("docs/a.md#sec#", [m])])

    def test_T13_sha_path(self):
        m = "must be <sha>:<normalised repo-relative path>"
        self.run_types({"type": "sha-path"}, [
            ("abc1234:docs/a.md", []), ("abc1234", [m]), ("abc123:docs/a.md", [m]), ("a" * 41 + ":a", [m]),
            ("ABC1234:a", [m]), ("abc1234:", [m]), ("abc1234:./a", [m]), ("abc1234:/a", [m]), ("abc1234:../a", [m]), (5, [m]),
            ("abc1234:a:b", []), ("abc1234:a#x", [m]), ("abc1234:a.md#sec", [m])])

    def test_T14_none(self):
        s = self.sch({"n": {"type": "str", "nullable": True, "required": False},
                      "z": {"type": "str", "required": False}})
        self.assertEqual(validate(s, {"schema": "thing/1", "n": None}, CFG), [])
        self.assertEqual(validate(s, {"schema": "thing/1", "z": None}, CFG), ["z: must not be null"])

    def test_T15_nested_depth(self):
        s = self.sch({"a": {"type": "list", "items": {"type": "map", "fields": {"b": {"type": "int"}}}},
                      "m": {"type": "any-map", "required": False}})
        self.assertEqual(validate(s, rt({"schema": "thing/1", "a": [{"b": 1}, {"b": "x"}]}), CFG),
                         ["a.1.b: must be an integer"])
        deep = cur = {}
        for _ in range(1000):
            cur["k"] = {}
            cur = cur["k"]
        self.assertEqual(validate(s, {"schema": "thing/1", "a": [], "m": deep}, CFG), [])
        self.assertEqual(validate(s, {"schema": "thing/1", "a": [], "m": {"x": [1, {"y": 2}]}}, CFG), [])

    def test_T16_top_level_not_a_mapping(self):
        s = self.sch()
        for v in (None, [], "x"):
            self.assertEqual(validate(s, v, CFG), ["top level: must be a mapping"])


class Conditions(Dirs):
    def test_R1_required_nullable(self):
        s = self.sch({"a": {"type": "str"}, "b": {"type": "str", "required": False}})
        self.assertEqual(validate(s, {"schema": "thing/1"}, CFG), ["a: required key is missing"])
        self.assertEqual(validate(s, {"schema": "thing/1", "a": "x"}, CFG), [])
        self.assertEqual(validate(s, {"schema": "thing/1", "a": "x", "b": None}, CFG), ["b: must not be null"])

    def cond(self):
        return self.sch({"status": {"type": "enum", "values": ["open", "answered", "x"]},
                         "answer": {"type": "str", "required_when": [{"status": ["answered"]}],
                                    "absent_when": [{"status": ["open"]}]}})

    def test_R2_required_when_top_level(self):
        s = self.cond()
        self.assertEqual(validate(s, {"schema": "thing/1", "status": "answered"}, CFG),
                         ["answer: required key is missing (required_when matches)"])
        self.assertEqual(validate(s, {"schema": "thing/1", "status": "answered", "answer": "y"}, CFG), [])
        self.assertEqual(validate(s, {"schema": "thing/1", "status": "x"}, CFG), [])  # not matched: optional
        s2 = self.sch({"status": {"type": "str"}, "a": {"type": "str", "required": True,
                                                         "required_when": [{"status": ["z"]}]}})
        self.assertEqual(validate(s2, {"schema": "thing/1", "status": "y"}, CFG), [])  # required: true is overridden

    def test_R3_absent_when_top_level(self):
        s = self.cond()
        self.assertEqual(validate(s, {"schema": "thing/1", "status": "open", "answer": "x"}, CFG),
                         ["answer: must be absent (absent_when matches)"])
        self.assertEqual(validate(s, {"schema": "thing/1", "status": "open", "answer": None}, CFG),
                         ["answer: must be absent (absent_when matches)"])
        self.assertEqual(validate(s, {"schema": "thing/1", "status": "open"}, CFG), [])
        self.assertEqual(validate(s, {"schema": "thing/1", "status": "x", "answer": "y"}, CFG), [])

    def nested(self):
        return self.sch({"o": {"type": "map", "fields": {
            "kind": {"type": "enum", "values": ["issue", "plan"]},
            "number": {"type": "int", "required": False, "required_when": [{"kind": ["issue"]}]},
            "plan": {"type": "str", "required": False, "absent_when": [{"kind": ["issue"]}]}}}})

    def test_R4_conditions_inside_nested_map(self):
        s = self.nested()
        v = lambda o: validate(s, {"schema": "thing/1", "o": o}, CFG)
        self.assertEqual(v({"kind": "issue", "number": 3}), [])
        self.assertEqual(v({"kind": "issue"}), ["o.number: required key is missing (required_when matches)"])
        self.assertEqual(v({"kind": "issue", "number": 3, "plan": "p"}), ["o.plan: must be absent (absent_when matches)"])
        self.assertEqual(v({"kind": "plan", "plan": "p"}), [])

    def test_R5_condition_sibling_absent(self):
        s = self.cond()
        self.assertEqual(validate(s, {"schema": "thing/1"}, CFG), ["status: required key is missing"])
        self.assertEqual(validate(s, {"schema": "thing/1", "answer": "y"}, CFG), ["status: required key is missing"])

    def test_R6_condition_sibling_of_other_type(self):
        s = self.sch({"status": {"type": "any-map", "required": False},
                      "a": {"type": "str", "required_when": [{"status": ["1"]}]},
                      "b": {"type": "str", "required_when": [{"status": [1]}]}})
        for status in (1, True, [1], {"x": 1}, None):
            errs = validate(s, {"schema": "thing/1", "status": status}, CFG)
            self.assertNotIn("a: required key is missing (required_when matches)", errs, status)
        self.assertIn("b: required key is missing (required_when matches)",
                      validate(s, {"schema": "thing/1", "status": 1}, CFG))
        self.assertNotIn("b: required key is missing (required_when matches)",
                         validate(s, {"schema": "thing/1", "status": True}, CFG))
        s2 = self.sch({"status": {"type": "str", "required": False},
                       "a": {"type": "str", "required_when": [{"status": ["1"]}]}})
        self.assertEqual(validate(s2, {"schema": "thing/1", "status": "1"}, CFG),
                         ["a: required key is missing (required_when matches)"])
        self.assertEqual(validate(s2, {"schema": "thing/1", "status": 1}, CFG), ["status: must be a non-empty string"])

    def test_R7_several_conditions(self):
        s = self.sch({"status": {"type": "str"},
                      "a": {"type": "str", "required_when": [{"status": ["x"]}, {"status": ["y"]}]}})
        for st, n in (("x", 1), ("y", 1), ("z", 0)):
            self.assertEqual(len(validate(s, {"schema": "thing/1", "status": st}, CFG)), n, st)
        s = self.sch({"status": {"type": "str"}, "a": {"type": "str", "required": False, "absent_when": [
            {"status": ["x"]}, {"status": ["y"]}]}})
        self.assertEqual(len(validate(s, {"schema": "thing/1", "status": "y", "a": "q"}, CFG)), 1)
        self.assertEqual(len(validate(s, {"schema": "thing/1", "status": "x", "a": "q"}, CFG)), 1)

    def test_R8_condition_with_several_siblings(self):
        s = self.sch({"a": {"type": "str"}, "b": {"type": "str"},
                      "c": {"type": "str", "required_when": [{"a": ["x"], "b": ["y"]}]}})
        self.assertEqual(validate(s, {"schema": "thing/1", "a": "x", "b": "n"}, CFG), [])
        self.assertEqual(validate(s, {"schema": "thing/1", "a": "n", "b": "y"}, CFG), [])
        self.assertEqual(validate(s, {"schema": "thing/1", "a": "x", "b": "y"}, CFG),
                         ["c: required key is missing (required_when matches)"])

    def test_R9_both_rules_match(self):
        s = self.sch({"status": {"type": "str"}, "a": {"type": "str", "required_when": [{"status": ["x"]}],
                                                      "absent_when": [{"status": ["x"]}]}})
        self.assertEqual(validate(s, {"schema": "thing/1", "status": "x", "a": "v"}, CFG),
                         ["a: must be absent (absent_when matches)"])
        self.assertEqual(validate(s, {"schema": "thing/1", "status": "x"}, CFG),
                         ["a: required key is missing (required_when matches)"])


class Tag(Dirs):
    def dec(self):
        return self.sch({"v": {"type": "int", "required": False}}, kind="decision")

    def test_G1_version_differs_names_upgrade(self):
        s = self.dec()
        self.assertEqual(validate(s, {"schema": "decision/2"}, CFG),
                         ["schema: expected decision/1, got decision/2; run /strict-delivery:upgrade"])
        s2 = self.sch(kind="decision", version=2)
        self.assertEqual(validate(s2, {"schema": "decision/1"}, CFG),
                         ["schema: expected decision/2, got decision/1; run /strict-delivery:upgrade"])
        self.assertEqual(validate(s, {"schema": "decision/1", "v": 1}, CFG), [])

    def test_G2_wrong_kind_malformed_or_missing(self):
        s = self.dec()

        class S(str):
            pass
        for got, shown in (("finding/1", "finding/1"), ("decision/1 ", "decision/1 "), ("decision/01", "decision/01"),
                           ("decision/0", "decision/0"), ("decision", "decision"), (1, "1"), (None, "None"),
                           (S("decision/1"), "decision/1"), ("Decision/1", "Decision/1")):
            self.assertEqual(validate(s, {"schema": got}, CFG), ["schema: expected decision/1, got %s" % shown], got)
        self.assertEqual(validate(s, {"v": 1}, CFG), ["schema: expected decision/1, got (missing)"])

    def test_G3_only_the_tag_error_when_the_tag_is_wrong(self):
        s = self.dec()
        self.assertEqual(validate(s, {"schema": "decision/2", "zzz": 1, "v": "x"}, CFG),
                         ["schema: expected decision/1, got decision/2; run /strict-delivery:upgrade"])


class Markdown(Dirs):
    TAG = "<!-- schema: in-force/1 -->"

    def test_M1_first_line(self):
        s = self.md()
        self.assertEqual(validate_markdown(s, self.TAG + "\nbody\n"), [])
        self.assertEqual(validate_markdown(s, self.TAG), [])
        err = ["first line: expected '%s'" % self.TAG]
        for text in ("", "\n" + self.TAG, "﻿" + self.TAG + "\n", self.TAG + "\r\nbody", self.TAG + " \n",
                     "<!-- schema: in-force/2 -->\n", "<!-- schema: finding/1 -->\n", "x\n" + self.TAG):
            self.assertEqual(validate_markdown(s, text), err, repr(text))
        self.assertEqual(validate_markdown(s, None), ["first line: text must be a string"])

    def test_M2_table_header(self):
        s = self.md(table=["id", "status"])
        ok = self.TAG + "\n\n| id | status |\n|---|---|\n| a | b |\n"
        self.assertEqual(validate_markdown(s, ok), [])
        hdr = "table: header must be '| id | status |', got "
        self.assertEqual(validate_markdown(s, ok.replace("| id | status |", "| status | id |")), [hdr + "'| status | id |'"])
        self.assertEqual(validate_markdown(s, ok.replace("| id | status |", "| id | status | x |")),
                         [hdr + "'| id | status | x |'"])
        self.assertEqual(validate_markdown(s, ok.replace("| id | status |", "| id |")), [hdr + "'| id |'"])
        self.assertEqual(validate_markdown(s, ok.replace("| id | status |", "|  id  | status |")),
                         [hdr + "'|  id  | status |'"])
        self.assertEqual(validate_markdown(s, ok.replace("| id | status |", "|id|status|")), [hdr + "'|id|status|'"])
        self.assertEqual(validate_markdown(s, ok.replace("| id | status |", "| id | status | ")), [hdr + "'| id | status | '"])
        self.assertEqual(validate_markdown(s, self.TAG + "\nno table\n"),
                         ["table: missing; expected a header '| id | status |'"])
        sep = "table: the line after the header must be '|---|---|'"
        self.assertEqual(validate_markdown(s, ok.replace("|---|---|", "| --- | --- |")), [sep])
        self.assertEqual(validate_markdown(s, ok.replace("|---|---|", "|---|")), [sep])
        self.assertEqual(validate_markdown(s, self.TAG + "\n| id | status |"), [sep])
        self.assertEqual(validate_markdown(s, ok.replace("\n", "\r\n")), ["first line: expected '%s'" % self.TAG])

    def test_M3_first_table_wins(self):
        s = self.md(table=["a"])
        self.assertEqual(validate_markdown(s, self.TAG + "\n| a |\n|---|\n\nprose\n| b |\n|---|\n"), [])
        self.assertEqual(validate_markdown(s, self.TAG + "\nprose\n\n| a |\n|---|\n"), [])
        self.assertEqual(validate_markdown(s, self.TAG + "\n| b |\n|---|\n\n| a |\n|---|\n"),
                         ["table: header must be '| a |', got '| b |'"])
        self.assertEqual(validate_markdown(s, self.TAG + "\n | a |\n|---|\n"),
                         ["table: header must be '| a |', got '|---|'"])  # a leading space is not a table line
        self.assertEqual(validate_markdown(s, self.TAG + "\n | a |\n"), ["table: missing; expected a header '| a |'"])

    def test_M4_headings(self):
        s = self.md(headings=["## One", "## Two"])
        t = self.TAG + "\n\n## One\n\ntext\n\n## Two\n"
        self.assertEqual(validate_markdown(s, t), [])
        self.assertEqual(validate_markdown(s, t + "### Sub\n"), [])
        err = "headings: expected [## One, ## Two], got [%s]"
        self.assertEqual(validate_markdown(s, self.TAG + "\n## Two\n## One\n"), [err % "## Two, ## One"])
        self.assertEqual(validate_markdown(s, self.TAG + "\n## One\n"), [err % "## One"])
        self.assertEqual(validate_markdown(s, t + "## Three\n"), [err % "## One, ## Two, ## Three"])
        self.assertEqual(validate_markdown(s, self.TAG + "\n##One\n## One\n## Two \n"), [err % "## One, ## Two "])

    def test_M5_markdown_schema_without_table_or_headings_checks_first_line_only(self):
        s = self.md()
        self.assertEqual(validate_markdown(s, self.TAG + "\n| x |\n## y\n"), [])


class Producers(unittest.TestCase):
    def kinds(self, mods):
        with mock.patch("gates.producers.PRODUCER_MODULES", tuple("tests.fixtures." + m for m in mods)):
            return produced_kinds()

    def test_P1_union(self):
        self.assertEqual(produced_kinds(), {"decision", "decision-index", "finding", "finding-index", "in-force", "overview"})  # Tasks 1c.3, 1d.1, 1d.2
        self.assertEqual(self.kinds([]), set())
        self.assertEqual(self.kinds(["prod_claim"]), {"claim"})
        self.assertEqual(self.kinds(["prod_claim_decision", "prod_decision", "prod_empty"]), {"claim", "decision"})
        self.assertEqual(self.kinds(["prod_widget"]), {"widget"})

    def test_P2_import_failure_names_module(self):
        for mod, text in (("raising_producer", "RuntimeError: boom"), ("nonexistent", "ModuleNotFoundError")):
            with self.assertRaises(GateError) as cm:
                self.kinds([mod])
            self.assertIn("producer module tests.fixtures.%s cannot be imported (" % mod, str(cm.exception))
            self.assertIn(text, str(cm.exception))

    def test_P3_produces_value(self):
        for mod in ("prod_missing", "prod_list", "prod_str", "prod_badtuple"):
            with self.assertRaises(GateError) as cm:
                self.kinds([mod])
            self.assertEqual(str(cm.exception),
                             "producer module tests.fixtures.%s: PRODUCES must be a tuple of strings" % mod)


class Files(GitIsolatedTestCase):
    def setUp(self):
        super().setUp()
        self.root = make_repo(self.work)
        self.cfg = config.load(self.root)

    def sch(self, files):
        sd = os.path.join(self.tmp, "sd")
        os.makedirs(sd, exist_ok=True)
        d = dict(BASE, files=files)
        with open(os.path.join(sd, "thing.yml"), "w") as fh:
            fh.write(yamlsub.emit(d))
        return load_schema(os.path.join(sd, "thing.yml"))

    def touch(self, rel, text="a: 1\n"):
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            fh.write(text)

    def test_F1_path_items(self):
        self.assertEqual(files_of(self.sch([{"path": "config"}]), self.root, self.cfg), [".strict-delivery/config.yml"])
        self.assertEqual(files_of(self.sch([{"path": "context"}]), self.root, self.cfg), [])
        self.touch(".strict-delivery/context.yml")
        self.assertEqual(files_of(self.sch([{"path": "context"}]), self.root, self.cfg), [".strict-delivery/context.yml"])
        cfg = copy.deepcopy(self.cfg)
        cfg["paths"]["context"] = "elsewhere/c.yml"
        self.touch("elsewhere/c.yml")
        self.assertEqual(files_of(self.sch([{"path": "context"}]), self.root, cfg), ["elsewhere/c.yml"])
        self.assertEqual(schema.expected_paths(self.sch([{"path": "context"}, {"dir": "decisions", "glob": "*"}]), cfg),
                         ["elsewhere/c.yml"])
        s = self.sch([{"path": "stat"}])
        with self.assertRaises(SchemaError) as cm:
            files_of(s, self.root, self.cfg)
        self.assertEqual(str(cm.exception), "%s: files: 'stat' is not a key of paths" % s.path)
        s = self.sch([{"dir": "stat", "glob": "*"}])
        with self.assertRaises(SchemaError):
            files_of(s, self.root, self.cfg)

    def test_F2_dir_items(self):
        s = self.sch([{"dir": "decisions", "glob": "*.yml", "exclude": ["index.yml"]}])
        self.assertEqual(files_of(s, self.root, self.cfg), [])  # missing dir
        d = ".strict-delivery/state/decisions"
        os.makedirs(os.path.join(self.root, d))
        self.assertEqual(files_of(s, self.root, self.cfg), [])  # empty dir
        for n in ("b.yml", "a.yml", "index.yml", "X.YML", "c.txt"):
            self.touch(d + "/" + n)
        os.mkdir(os.path.join(self.root, d, "sub.yml"))
        self.touch(d + "/sub/deep.yml")
        self.assertEqual(files_of(s, self.root, self.cfg), [d + "/a.yml", d + "/b.yml", d + "/sub.yml"])
        self.assertEqual(schema.entries_of(s, self.root, self.cfg)[0], (d + "/a.yml", True))

    def test_F4_non_regular_matches_are_listed_and_symlinked_components_refused(self):
        s = self.sch([{"dir": "decisions", "glob": "*.yml"}])
        d = ".strict-delivery/state/decisions"
        self.touch(d + "/real.yml")
        os.symlink("real.yml", os.path.join(self.root, d, "link.yml"))
        os.symlink("nowhere", os.path.join(self.root, d, "dangling.yml"))
        os.mkfifo(os.path.join(self.root, d, "fifo.yml"))
        os.mkdir(os.path.join(self.root, d, "dir.yml"))
        self.assertEqual(files_of(s, self.root, self.cfg),
                         [d + "/" + n for n in ("dangling.yml", "dir.yml", "fifo.yml", "link.yml", "real.yml")])
        other = os.path.join(self.tmp, "other")
        os.makedirs(other)
        os.rename(os.path.join(self.root, ".strict-delivery/state/decisions"), os.path.join(other, "decisions"))
        os.symlink(os.path.join(other, "decisions"), os.path.join(self.root, d))
        with self.assertRaises(schema.LayoutError) as cm:
            files_of(s, self.root, self.cfg)
        self.assertEqual((cm.exception.rel, str(cm.exception)), (d, "is a symlink; directories must be real directories"))

    def test_F4_component_not_a_directory(self):
        s = self.sch([{"dir": "decisions", "glob": "*.yml"}])
        self.touch(".strict-delivery/state", "x")
        with self.assertRaises(schema.LayoutError) as cm:
            files_of(s, self.root, self.cfg)
        self.assertEqual((cm.exception.rel, str(cm.exception)), (".strict-delivery/state", "is not a directory"))

    def test_F5_symlinked_path_item_is_listed(self):
        s = self.sch([{"path": "context"}])
        self.touch("real.yml")
        os.symlink("../real.yml", os.path.join(self.root, ".strict-delivery/context.yml"))
        self.assertEqual(files_of(s, self.root, self.cfg), [".strict-delivery/context.yml"])

    def test_F6_root_must_be_the_toplevel(self):
        s = self.sch([{"path": "config"}])
        sub = os.path.join(self.root, "sub")
        os.mkdir(sub)
        with self.assertRaises(GateError) as cm:
            files_of(s, sub, self.cfg)
        self.assertEqual(str(cm.exception), "git rev-parse --show-toplevel: root must be the repository top level")
        with self.assertRaises(GateError):
            files_of(s, self.tmp, self.cfg)
        with self.assertRaises(GateError):
            files_of(self.sch([{"path": "stat"}]), sub, self.cfg)  # toplevel check comes before key resolution
        commit_all(self.root, "x")


if __name__ == "__main__":
    unittest.main()
