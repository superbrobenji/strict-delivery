"""Tests of gates/lib/schema.py; rows K1-K7, L1-L13, T1-T16, R1-R9, G1-G3, M1-M5, P1-P3, F1-F6 of the 1b.1 table."""
import builtins
import copy
import errno
import fnmatch
import os
import re
import tempfile
import unittest
import warnings
from unittest import mock

from gates.lib import config, schema, yamlsub
from gates.lib.result import GateError
from gates.lib.schema import KNOWN_KINDS, LayoutError, SchemaError, entries_of, files_of, load_schema, produced_kinds
from gates.lib.schema import schemas, validate, validate_front_matter
from gates.lib.schema import validate_markdown
from tests.helpers import INT_LIMITS, GitIsolatedTestCase, commit_all, int_limit, make_repo

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
THING = "thing/%d" % BASE["version"]  # the tag of every record checked against a schema built from BASE
MD_VERSION = 1  # the version of the markdown schema md() builds
H_VERSION = 1  # the version of the front-matter schema Dirs.fm() builds (kind h)
L_VERSION = 1  # the version of the markdown `lines` schema Dirs.ln() builds (kind l)
HTAG = "h/%d" % H_VERSION
LTAG = "<!-- schema: l/%d -->" % L_VERSION
PS = ".strict-delivery/state/plans"  # config.DEFAULTS paths.plan_state, written out by hand
STAND_IN = "CHECKPOINT [^ ]+ [^ ]+ head=[0-9a-f]{7,40}"  # the stand-in pattern of the table's notation W
GOOD_LINE = "CHECKPOINT a b head=abcdef0"


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
        d = {"kind": "in-force", "version": MD_VERSION, "format": "markdown", "files": [{"path": "config"}],
             "first_line": "<!-- schema: in-force/%d -->" % MD_VERSION}
        d.update(over)
        return load_schema(self.put("in-force.yml", d))

    def fm_data(self, **over):
        d = {"kind": "h", "version": H_VERSION, "format": "front-matter", "files": [{"path": "config"}],
             "fields": {"schema": {"type": "str"}, "plan": {"type": "str"}}}
        d.update(over)
        return d

    def fm(self, **over):
        return load_schema(self.put("h.yml", self.fm_data(**over)))

    def ln_data(self, lines, **over):
        d = {"kind": "l", "version": L_VERSION, "format": "markdown", "files": [{"path": "config"}],
             "first_line": LTAG, "lines": lines}
        d.update(over)
        return d

    def ln(self, lines, **over):
        return load_schema(self.put("l.yml", self.ln_data(lines, **over)))

    def stand_in(self, **over):
        return self.ln([{"word": "CHECKPOINT", "pattern": STAND_IN}], **over)


def rt(d):
    """The value yamlsub.load gives for a file written by emit (the production read path)."""
    return yamlsub.parse(yamlsub.emit(d))


class KnownKinds(unittest.TestCase):
    def test_K1_known_kinds_match_appendix(self):
        self.assertEqual(KNOWN_KINDS, ("config", "decision", "finding", "claim", "request", "streams", "context",
                                       "handoff", "ledger", "status", "sync-log", "merged-log", "breakdown", "overview", "in-force",
                                       "decision-index", "finding-index", "mutation-transcript", "review-report",
                                       "receipt", "claude-block", "gitignore-block"))

    def test_K1_generated_set_is_the_four(self):  # N3 data
        self.assertEqual(schema.GENERATED_KINDS, ("decision-index", "finding-index", "in-force", "overview"))


class SchemasDir(Dirs):
    def test_K6_default_dir_loads_and_stems_known(self):
        got = schemas()
        self.assertEqual(sorted(got), ["breakdown", "claim", "config", "decision", "decision-index", "finding", "finding-index",
                                       "handoff", "in-force", "ledger", "merged-log", "mutation-transcript", "overview",
                                       "request", "review-report", "status", "streams",
                                       "sync-log"])  # Task 1c.3: the four generated kinds; P1.2: handoff, ledger; P2.1 part i: the five program kinds; 6E.1: the two evidence kinds
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
        self.assertEqual(problems, [("claim", "%s: format: must be yaml, markdown or front-matter" % bad)])  # D-Q3

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
            self.assertEqual(m, "%s: format: must be yaml, markdown or front-matter" % p, val)  # D-Q3 (changed on purpose)
        d = dict(BASE)
        del d["format"]
        p, m = self.bad(d)
        self.assertEqual(m, "%s: format: must be yaml, markdown or front-matter" % p)

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
                     "id": {"id_kind": "decision"}, "one_of": {"of": [{"type": "str"}]}}.get(t, {})
            self.sch({"v": dict(type=t, **extra)})
        self.assertEqual(len(schema.TYPES), 14)  # Task P2.1 part i adds one_of (D-A1)
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
                self.assertEqual(validate(s, {"schema": THING, "v": value}, CFG),
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
        self.assertEqual(validate(s, {"schema": THING, "v": "FX-20261031-k3f9"}, cfg), [])  # prefix from cfg
        self.assertEqual(len(validate(s, {"schema": THING, "v": "F-20261031-k3f9"}, cfg)), 1)

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
            (5, [m]), ("", [m]), (".", [m]), ("docs/a.md#a#b", [m]), ("docs/a.md#sec#", [m]),
            # the anchor site (Task 1d2.1): U+0C5D and U+1FAE0 are not printable at Unicode 13.0.0, on every interpreter
            ("docs/a.md#xౝ", [m]), ("docs/a.md#x\U0001FAE0", [m])])

    def test_T13_sha_path(self):
        m = "must be <sha>:<normalised repo-relative path>"
        self.run_types({"type": "sha-path"}, [
            ("abc1234:docs/a.md", []), ("abc1234", [m]), ("abc123:docs/a.md", [m]), ("a" * 41 + ":a", [m]),
            ("ABC1234:a", [m]), ("abc1234:", [m]), ("abc1234:./a", [m]), ("abc1234:/a", [m]), ("abc1234:../a", [m]), (5, [m]),
            ("abc1234:a:b", []), ("abc1234:a#x", [m]), ("abc1234:a.md#sec", [m])])

    def test_T14_none(self):
        s = self.sch({"n": {"type": "str", "nullable": True, "required": False},
                      "z": {"type": "str", "required": False}})
        self.assertEqual(validate(s, {"schema": THING, "n": None}, CFG), [])
        self.assertEqual(validate(s, {"schema": THING, "z": None}, CFG), ["z: must not be null"])

    def test_T15_nested_depth(self):
        s = self.sch({"a": {"type": "list", "items": {"type": "map", "fields": {"b": {"type": "int"}}}},
                      "m": {"type": "any-map", "required": False}})
        self.assertEqual(validate(s, rt({"schema": THING, "a": [{"b": 1}, {"b": "x"}]}), CFG),
                         ["a.1.b: must be an integer"])
        deep = cur = {}
        for _ in range(1000):
            cur["k"] = {}
            cur = cur["k"]
        self.assertEqual(validate(s, {"schema": THING, "a": [], "m": deep}, CFG), [])
        self.assertEqual(validate(s, {"schema": THING, "a": [], "m": {"x": [1, {"y": 2}]}}, CFG), [])

    def test_T16_top_level_not_a_mapping(self):
        s = self.sch()
        for v in (None, [], "x"):
            self.assertEqual(validate(s, v, CFG), ["top level: must be a mapping"])


class Conditions(Dirs):
    def test_R1_required_nullable(self):
        s = self.sch({"a": {"type": "str"}, "b": {"type": "str", "required": False}})
        self.assertEqual(validate(s, {"schema": THING}, CFG), ["a: required key is missing"])
        self.assertEqual(validate(s, {"schema": THING, "a": "x"}, CFG), [])
        self.assertEqual(validate(s, {"schema": THING, "a": "x", "b": None}, CFG), ["b: must not be null"])

    def cond(self):
        return self.sch({"status": {"type": "enum", "values": ["open", "answered", "x"]},
                         "answer": {"type": "str", "required_when": [{"status": ["answered"]}],
                                    "absent_when": [{"status": ["open"]}]}})

    def test_R2_required_when_top_level(self):
        s = self.cond()
        self.assertEqual(validate(s, {"schema": THING, "status": "answered"}, CFG),
                         ["answer: required key is missing (required_when matches)"])
        self.assertEqual(validate(s, {"schema": THING, "status": "answered", "answer": "y"}, CFG), [])
        self.assertEqual(validate(s, {"schema": THING, "status": "x"}, CFG), [])  # not matched: optional
        s2 = self.sch({"status": {"type": "str"}, "a": {"type": "str", "required": True,
                                                         "required_when": [{"status": ["z"]}]}})
        self.assertEqual(validate(s2, {"schema": THING, "status": "y"}, CFG), [])  # required: true is overridden

    def test_R3_absent_when_top_level(self):
        s = self.cond()
        self.assertEqual(validate(s, {"schema": THING, "status": "open", "answer": "x"}, CFG),
                         ["answer: must be absent (absent_when matches)"])
        self.assertEqual(validate(s, {"schema": THING, "status": "open", "answer": None}, CFG),
                         ["answer: must be absent (absent_when matches)"])
        self.assertEqual(validate(s, {"schema": THING, "status": "open"}, CFG), [])
        self.assertEqual(validate(s, {"schema": THING, "status": "x", "answer": "y"}, CFG), [])

    def nested(self):
        return self.sch({"o": {"type": "map", "fields": {
            "kind": {"type": "enum", "values": ["issue", "plan"]},
            "number": {"type": "int", "required": False, "required_when": [{"kind": ["issue"]}]},
            "plan": {"type": "str", "required": False, "absent_when": [{"kind": ["issue"]}]}}}})

    def test_R4_conditions_inside_nested_map(self):
        s = self.nested()
        v = lambda o: validate(s, {"schema": THING, "o": o}, CFG)
        self.assertEqual(v({"kind": "issue", "number": 3}), [])
        self.assertEqual(v({"kind": "issue"}), ["o.number: required key is missing (required_when matches)"])
        self.assertEqual(v({"kind": "issue", "number": 3, "plan": "p"}), ["o.plan: must be absent (absent_when matches)"])
        self.assertEqual(v({"kind": "plan", "plan": "p"}), [])

    def test_R5_condition_sibling_absent(self):
        s = self.cond()
        self.assertEqual(validate(s, {"schema": THING}, CFG), ["status: required key is missing"])
        self.assertEqual(validate(s, {"schema": THING, "answer": "y"}, CFG), ["status: required key is missing"])

    def test_R6_condition_sibling_of_other_type(self):
        s = self.sch({"status": {"type": "any-map", "required": False},
                      "a": {"type": "str", "required_when": [{"status": ["1"]}]},
                      "b": {"type": "str", "required_when": [{"status": [1]}]}})
        for status in (1, True, [1], {"x": 1}, None):
            errs = validate(s, {"schema": THING, "status": status}, CFG)
            self.assertNotIn("a: required key is missing (required_when matches)", errs, status)
        self.assertIn("b: required key is missing (required_when matches)",
                      validate(s, {"schema": THING, "status": 1}, CFG))
        self.assertNotIn("b: required key is missing (required_when matches)",
                         validate(s, {"schema": THING, "status": True}, CFG))
        s2 = self.sch({"status": {"type": "str", "required": False},
                       "a": {"type": "str", "required_when": [{"status": ["1"]}]}})
        self.assertEqual(validate(s2, {"schema": THING, "status": "1"}, CFG),
                         ["a: required key is missing (required_when matches)"])
        self.assertEqual(validate(s2, {"schema": THING, "status": 1}, CFG), ["status: must be a non-empty string"])

    def test_R7_several_conditions(self):
        s = self.sch({"status": {"type": "str"},
                      "a": {"type": "str", "required_when": [{"status": ["x"]}, {"status": ["y"]}]}})
        for st, n in (("x", 1), ("y", 1), ("z", 0)):
            self.assertEqual(len(validate(s, {"schema": THING, "status": st}, CFG)), n, st)
        s = self.sch({"status": {"type": "str"}, "a": {"type": "str", "required": False, "absent_when": [
            {"status": ["x"]}, {"status": ["y"]}]}})
        self.assertEqual(len(validate(s, {"schema": THING, "status": "y", "a": "q"}, CFG)), 1)
        self.assertEqual(len(validate(s, {"schema": THING, "status": "x", "a": "q"}, CFG)), 1)

    def test_R8_condition_with_several_siblings(self):
        s = self.sch({"a": {"type": "str"}, "b": {"type": "str"},
                      "c": {"type": "str", "required_when": [{"a": ["x"], "b": ["y"]}]}})
        self.assertEqual(validate(s, {"schema": THING, "a": "x", "b": "n"}, CFG), [])
        self.assertEqual(validate(s, {"schema": THING, "a": "n", "b": "y"}, CFG), [])
        self.assertEqual(validate(s, {"schema": THING, "a": "x", "b": "y"}, CFG),
                         ["c: required key is missing (required_when matches)"])

    def test_R9_both_rules_match(self):
        s = self.sch({"status": {"type": "str"}, "a": {"type": "str", "required_when": [{"status": ["x"]}],
                                                      "absent_when": [{"status": ["x"]}]}})
        self.assertEqual(validate(s, {"schema": THING, "status": "x", "a": "v"}, CFG),
                         ["a: must be absent (absent_when matches)"])
        self.assertEqual(validate(s, {"schema": THING, "status": "x"}, CFG),
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
        self.assertEqual(validate(s, {"schema": "decision/%d" % s.version, "v": 1}, CFG), [])

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
    TAG = "<!-- schema: in-force/%d -->" % MD_VERSION

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
        self.assertEqual(produced_kinds(), {"breakdown", "claim", "decision", "decision-index", "finding", "finding-index", "in-force", "merged-log",
                                           "overview", "request", "status", "streams", "sync-log"})  # Tasks 1c.3, 1d.1, 1d.2, 2c.1; P2.2: the program tool's six
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


EMPTY_SEG = "must not have an empty segment (no leading, trailing or doubled '/')"
DOT_SEG = "'.' and '..' segments are not allowed"
SPAN = "a [...] class may not hold '/'"
STAR2 = "'**' is not supported"


class NestedGlobLoad(Dirs):
    """Producer 1 of the P1.1 table (rows NG1-NG12): ``load_schema`` of a nested ``glob``."""

    def gs(self, g):
        return self.sch(files=[{"dir": "decisions", "glob": g}])

    def refused(self, g, text):
        p, m = self.bad(dict(BASE, files=[{"dir": "decisions", "glob": g}]))
        self.assertEqual(m, "%s: files.0.glob: %s" % (p, text), g)

    def test_nested_glob_valid_forms_load(self):  # NG1
        for g in ("*/handoff.md", "*/requests/*.yml", "*/a/b/c.md", "a*/[xy]*.md"):
            with self.subTest(glob=g):
                self.assertEqual(self.gs(g).files, [{"dir": "decisions", "glob": g}])

    def test_bad_glob_segments_refused(self):  # NG2, NG3, NG4, NG12 (the plan's name)
        for g in ("a//b", "//", "a///b", "/x", "x/", "/", "/x/"):
            with self.subTest(glob=g):
                self.refused(g, EMPTY_SEG)
        for g in ("./x", "../x", "x/./y", "x/../y", ".", "..", "x/.", "x/.."):
            with self.subTest(glob=g):
                self.refused(g, DOT_SEG)

    def test_one_segment_glob_unchanged(self):  # NG5
        for g in ("*.yml", "index.yml", "*", "?", "[a-c]*"):
            with self.subTest(glob=g):
                self.assertEqual(self.gs(g).files, [{"dir": "decisions", "glob": g}])

    def test_nested_glob_bracket_grammar_reused(self):  # NG6
        self.assertEqual(self.gs("[a-c]*/x.md").files[0]["glob"], "[a-c]*/x.md")
        self.assertEqual(self.gs("a[!b]/x.md").files[0]["glob"], "a[!b]/x.md")
        head = "must be a supported glob: the bracket expression [%s] holds "
        for g, body, why in (("[z-a]/x.md", "z-a", "the reversed range z-a"), ("[-a]/x", "-a", NOT_ALLOWED % "U+002D"),
                             ("x/[é]", "é", NOT_ALLOWED % "U+00E9")):
            with self.subTest(glob=g):
                self.refused(g, (head % body) + why)

    def test_nested_glob_bracket_across_slash(self):  # NG7 (D-Q1)
        for g in ("a[/]b", "[a/b]*", "a[!/]b", "a/b[/]c", "a[]/]b", "a[!]/]b", "a[x]/b[/]"):
            with self.subTest(glob=g):
                self.refused(g, SPAN)
        for g in ("a[x/y", "a]x/y", "[/y"):  # no class is closed: each [ or ] is a literal, as fnmatch reads it
            with self.subTest(glob=g):
                self.assertEqual(self.gs(g).files[0]["glob"], g)

    def test_nested_glob_double_star_refused(self):  # NG8 (D-Q2)
        for g in ("**/handoff.md", "a/**/b", "a**/x", "**", "x/**", "*/**.md"):
            with self.subTest(glob=g):
                self.refused(g, STAR2)

    def test_nested_glob_unicode_segment_same_on_both(self):  # NG9, V2
        for g in ("a b/x", "é/x", "ࡰ*/x", "a\\b/x", "\U0001fae8/Ⱟ*", "x/ౝ"):
            with self.subTest(glob=g):
                self.assertEqual(self.gs(g).files[0]["glob"], g)

    def test_nested_glob_exclude_list_checked(self):  # NG11
        ok = [{"dir": "d", "glob": "*/handoff.md", "exclude": ["x"]}]
        self.assertEqual(self.sch(files=ok).files, ok)
        ok2 = [{"dir": "d", "glob": "*/handoff.md", "exclude": ["a/handoff.md"]}]
        self.assertEqual(self.sch(files=ok2).files, ok2)
        for ex in ("x", [1], None):
            p, m = self.bad(dict(BASE, files=[{"dir": "d", "glob": "*/handoff.md", "exclude": ex}]))
            self.assertEqual(m, "%s: files.0.exclude: must be a list of strings" % p, ex)

    # ---- Task 6E.1-x, owner answer 2026-11-22 (a): rows X5, X7, X8, X9, X15, X16, X18 (load side)
    def ex(self, entry, glob="*/*/*"):
        files = [{"dir": "d", "glob": glob, "exclude": entry}]
        return dict(BASE, files=files)

    def ex_refused(self, entry, text, glob="*/*/*"):
        p, m = self.bad(self.ex(entry, glob))
        self.assertEqual(m, "%s: files.0.exclude: %s" % (p, text), entry)

    def test_exclude_path_entry_segment_count_must_match_glob(self):  # X5
        for entry, glob in (("p-b/*", "*/mutations/*"), ("*/*", "*/*/*"), ("a/b/c/d", "*/*/*"), ("a/b", "*"),
                            ("a/b/c", "*/*")):
            with self.subTest(entry=entry, glob=glob):
                self.ex_refused([entry], "exclude entry '%s': must have as many segments as the glob" % entry, glob)
        for entry, glob in (("a/b", "*/*"), ("a/b/c", "*/*/*"), ("*/*", "*/handoff.md")):
            with self.subTest(entry=entry, glob=glob):
                self.assertEqual(self.sch(files=[{"dir": "d", "glob": glob, "exclude": [entry]}]).files[0]["exclude"],
                                 [entry])

    def test_exclude_malformed_path_entries_refused(self):  # X7
        for e in ("/a/b", "a/b/", "a//b", "//", "/"):
            with self.subTest(entry=e):
                self.ex_refused([e], "exclude entry '%s': %s" % (e, EMPTY_SEG), "*/*/*" if e.count("/") > 1 else "*/*")
        for e in ("./a/b", "a/../b", "a/b/.", "a/./b"):
            with self.subTest(entry=e):
                self.ex_refused([e], "exclude entry '%s': %s" % (e, DOT_SEG))
        self.ex_refused(["a/**/b"], "exclude entry 'a/**/b': '**' is not supported")
        self.ex_refused(["a/[/]b"], "exclude entry 'a/[/]b': " + SPAN)
        head = "must be a supported glob: the bracket expression [%s] holds "
        self.ex_refused(["a/[z-a]"], "exclude entry 'a/[z-a]': " + (head % "z-a") + "the reversed range z-a", "*/*")
        self.ex_refused(["a/[é]"], "exclude entry 'a/[é]': " + (head % "é") + NOT_ALLOWED % "U+00E9", "*/*")
        self.ex_refused(["ok/ok", "a//b"], "exclude entry 'a//b': " + EMPTY_SEG, "*/*")  # the second entry, same key

    def test_exclude_unclosed_bracket_is_a_literal_as_in_the_glob(self):  # X7 (bracket_problem accepts a lone "[")
        for e in ("a/[b", "a/[]b"):
            with self.subTest(entry=e):
                self.assertEqual(self.sch(files=[{"dir": "d", "glob": "*/*", "exclude": [e]}]).files[0]["exclude"], [e])

    def test_exclude_type_refused(self):  # X8
        for ex in ("a", [1], [None], [True], ["a", 2], None, {"a": 1}, 5):
            with self.subTest(exclude=ex):
                self.ex_refused(ex, "must be a list of strings", "*/*")

    def test_exclude_empty_entry_refused(self):  # X9
        for ex in ([""], ["a", ""], ["a/b", ""]):
            with self.subTest(exclude=ex):
                self.ex_refused(ex, "an exclude entry must not be empty", "*/*")

    def test_exclude_plain_names_are_not_validated_as_patterns(self):  # X1, X2 (load side, D-X2)
        for e in ("index.yml", "*.yml", "[z-a]", "a b", "**", "é", "a\\b"):
            with self.subTest(entry=e):
                self.assertEqual(self.sch(files=[{"dir": "d", "glob": "*", "exclude": [e]}]).files[0]["exclude"], [e])

    def test_exclude_pc1_load_same_on_both(self):  # X15, X16
        for e in ("9" * 4300 + "/m/*", "9" * 4301 + "/m/*", "\U0001f6dd/m/*", "Ꟁ/ꟁ/ࡰ", "9" * 4301):
            with self.subTest(entry=e[:12] + str(len(e))):
                self.assertEqual(self.sch(files=[{"dir": "d", "glob": "*/*/*", "exclude": [e]}]).files[0]["exclude"], [e])

    def test_exclude_on_a_path_item_refused(self):  # X18
        for ex in (["a/b"], ["a"], []):
            with self.subTest(exclude=ex):
                p, m = self.bad(dict(BASE, files=[{"path": "config", "exclude": ex}]))
                self.assertEqual(m, "%s: files.0: a path item is exactly {path: <paths key>}" % p)

    def test_glob_refusal_names_the_item_index(self):  # NG12: the index is the item's position
        p, m = self.bad(dict(BASE, files=[{"path": "config"}, {"dir": "d", "glob": "a//b"}]))
        self.assertEqual(m, "%s: files.1.glob: %s" % (p, EMPTY_SEG))

    def test_glob_non_string_still_refused(self):  # NG10 (existing rule, kept)
        for g in ("", 1, None, ["a"]):
            p, m = self.bad(dict(BASE, files=[{"dir": "d", "glob": g}]))
            self.assertEqual(m, "%s: files.0.glob: a dir item needs a non-empty string dir and glob" % p, g)


EXPECTED_FILES = [  # written by hand from gates/schemas/*.yml, in sorted file order
    ("claim", [{"dir": "claims", "glob": "*.yml"}]),
    ("config", [{"path": "config"}]),
    ("decision", [{"dir": "decisions", "glob": "*.yml", "exclude": ["index.yml"]}]),
    ("decision-index", [{"dir": "decisions", "glob": "index.yml"}]),
    ("finding", [{"dir": "findings", "glob": "*.yml", "exclude": ["index.yml"]}]),
    ("finding-index", [{"dir": "findings", "glob": "index.yml"}]),
    ("in-force", [{"dir": "decisions", "glob": "in-force.md"}]),
    ("overview", [{"path": "index"}]),
]


class FrontMatterSchema(Dirs):
    """Producer 3 (rows FS1-FS7): ``load_schema`` of a front-matter schema."""

    def test_front_matter_schema_loads(self):  # FS1
        s = self.fm()
        self.assertEqual((s.format, s.kind, s.version), ("front-matter", "h", H_VERSION))
        self.assertEqual(s.fields, {"schema": {"type": "str"}, "plan": {"type": "str"}})
        self.assertEqual((s.first_line, s.table, s.headings, s.lines), (None, None, None, None))

    def test_front_matter_schema_field_rule(self):  # FS2
        want = "fields.schema: must be declared as a required, non-nullable str"
        for fields in ({"plan": {"type": "str"}}, {"schema": {"type": "str", "required": False}},
                       {"schema": {"type": "str", "nullable": True}}, {"schema": {"type": "text"}},
                       {"schema": {"type": "str", "required_when": [{"plan": ["x"]}]}, "plan": {"type": "str"}},
                       {"schema": {"type": "str", "required": False, "absent_when": [{"plan": ["x"]}]},
                        "plan": {"type": "str"}}):
            with self.subTest(fields=fields):
                p, m = self.bad(self.fm_data(fields=fields), name="h.yml")
                self.assertEqual(m, "%s: %s" % (p, want))

    def test_front_matter_schema_fields_checked(self):  # FS3
        d = self.fm_data()
        del d["fields"]
        p, m = self.bad(d, name="h.yml")
        self.assertEqual(m, "%s: fields: required key is missing" % p)
        p, m = self.bad(self.fm_data(fields=[]), name="h.yml")
        self.assertEqual(m, "%s: fields: must be a mapping of field names to specs" % p)
        p, m = self.bad(self.fm_data(fields={"schema": {"type": "str"}, "x": {"type": "nope"}}), name="h.yml")
        self.assertIn("%s: fields.x.type: must be one of " % p, m)

    def test_body_keys_by_format(self):  # FS4 (D-Q6)
        for key, val in (("first_line", "x"), ("table", ["a"]), ("headings", ["## A"]),
                         ("lines", [{"word": "A", "pattern": "A"}])):
            with self.subTest(key=key):
                p, m = self.bad(self.fm_data(**{key: val}), name="h.yml")
                self.assertEqual(m, "%s: %s: unknown key for a front-matter schema" % (p, key))
        p, m = self.bad(dict(BASE, lines=[{"word": "A", "pattern": "A"}]))
        self.assertEqual(m, "%s: lines: unknown key for a yaml schema" % p)
        p, m = self.bad(self.fm_data(kinds=[]), name="h.yml")
        self.assertEqual(m, "%s: kinds: unknown key for a front-matter schema" % p)
        md = {"kind": "thing", "version": 1, "format": "markdown", "files": [{"path": "config"}], "first_line": "x"}
        p, m = self.bad(dict(md, fields={"schema": {"type": "str"}}))
        self.assertEqual(m, "%s: fields: unknown key for a markdown schema" % p)

    def test_format_values(self):  # FS5
        self.assertEqual(self.sch().format, "yaml")
        self.assertEqual(self.md().format, "markdown")
        self.assertEqual(self.fm().format, "front-matter")
        for val in ("Front-Matter", "frontmatter", "front_matter", "json", "front-matter ", None, 5, ["front-matter"]):
            with self.subTest(format=val):
                p, m = self.bad(self.fm_data(format=val), name="h.yml")
                self.assertEqual(m, "%s: format: must be yaml, markdown or front-matter" % p)

    def test_formats_literal(self):  # FS6
        self.assertEqual(schema.FORMATS, ("yaml", "markdown", "front-matter"))

    def test_old_schemas_unchanged(self):  # FS7
        listed = sorted(os.listdir(schema.SCHEMAS_DIR))
        later = ["breakdown.yml", "handoff.yml", "ledger.yml", "merged-log.yml", "mutation-transcript.yml", "request.yml",
                 "review-report.yml", "status.yml", "streams.yml",
                 "sync-log.yml"]  # Task P1.2 adds two; Task P2.1 part i adds the five program schemas; Task 6E.1 the two evidence ones
        self.assertEqual(listed, sorted([k + ".yml" for k, _ in EXPECTED_FILES] + later))
        got = [name for name in listed if name not in later]  # the old vocabulary's files only
        loaded = [load_schema(os.path.join(schema.SCHEMAS_DIR, name)) for name in got]
        self.assertEqual({s.kind: s.files for s in loaded}, dict(EXPECTED_FILES))
        for s in loaded:
            self.assertEqual(s.lines, None)
            self.assertIn(s.format, ("yaml", "markdown"))


class LinesLoad(Dirs):
    """Producer 5 (rows LW1-LW13): ``load_schema`` of markdown ``lines``."""

    def refused(self, lines, key, text, **over):
        p, m = self.bad(self.ln_data(lines, **over), name="l.yml")
        self.assertEqual(m, "%s: %s: %s" % (p, key, text), lines)

    def test_lines_valid_forms(self):  # LW1
        one = [{"word": "CHECKPOINT", "pattern": STAND_IN}]
        two = one + [{"word": "Ruling", "pattern": "Ruling .*"}]
        self.assertEqual(self.ln(one).lines, one)
        self.assertEqual(self.ln(two).lines, two)
        self.assertEqual(self.ln(two, table=["a", "b"]).lines, two)
        self.assertEqual(self.ln(two, table=["a", "b"]).table, ["a", "b"])
        self.assertEqual(self.ln(two, headings=["## A"]).headings, ["## A"])
        self.assertEqual(self.ln(two).first_line, LTAG)
        self.assertEqual((self.ln(two).table, self.ln(two).headings), (None, None))

    def test_markdown_schema_without_lines_unchanged(self):  # LW2
        s = self.md()
        self.assertIsNone(s.lines)
        self.assertEqual(validate_markdown(s, s.first_line + "\nCHECKPOINT bad\nRuling x\n"), [])

    def test_lines_shape_refused(self):  # LW3 (D-Q9)
        for bad in ("x", {"word": "A", "pattern": "A"}, 5, None, True):
            with self.subTest(lines=bad):
                self.refused(bad, "lines", "must be a non-empty list")
        self.refused([], "lines", "must be a non-empty list")
        for item in ("A", 5, None, ["A"]):
            with self.subTest(item=item):
                self.refused([item], "lines.0", "must be a mapping")
        self.refused([{"word": "A", "pattern": "A", "x": 1}], "lines.0.x", "unknown key")
        self.refused([{"word": "A"}], "lines.0.pattern", "required key is missing")
        self.refused([{"pattern": "A"}], "lines.0.word", "required key is missing")
        self.refused([{"word": "A", "pattern": "A"}, {"pattern": "B"}], "lines.1.word", "required key is missing")
        for v in (1, None, True, ["A"]):
            with self.subTest(word=v):
                self.refused([{"word": v, "pattern": "A"}], "lines.0.word", "must be a string")
            with self.subTest(pattern=v):
                self.refused([{"word": "A", "pattern": v}], "lines.0.pattern", "must be a string")

    def test_lines_word_refused(self):  # LW4 (D-Q10)
        want = "must be printable ASCII with no whitespace"
        for w in ("", "A B", "A\tB", " A", "A ", "A\nB", "A B", "A\u0085B", "A　B", "A​B", "A᠎B",
                  "A\x00", "A\x7f", "é", "ࡰ", "\U0001fae8", "A B", "A\rB"):
            with self.subTest(word=w):
                self.refused([{"word": w, "pattern": "A"}], "lines.0.word", want)

    def test_lines_word_forms(self):  # LW5
        for w in ("CHECKPOINT", "Ruling", "A:B", "a", "x-y", "[x]", "*"):
            with self.subTest(word=w):
                self.assertEqual(self.ln([{"word": w, "pattern": "A"}]).lines[0]["word"], w)
        for w in ("Ruling:", ":", "A::"):
            with self.subTest(word=w):
                self.refused([{"word": w, "pattern": "A"}], "lines.0.word", "must not end with ':'")

    def test_lines_repeated_word_refused(self):  # LW6
        rep = "repeats the word of an earlier item"
        self.refused([{"word": "A", "pattern": "A"}, {"word": "A", "pattern": "A"}], "lines.1.word", rep)
        self.refused([{"word": "A", "pattern": "A"}, {"word": "A", "pattern": "B"}], "lines.1.word", rep)
        self.refused([{"word": "A", "pattern": "A"}, {"word": "B", "pattern": "B"}, {"word": "B", "pattern": "C"}],
                     "lines.2.word", rep)
        got = self.ln([{"word": "A", "pattern": "A"}, {"word": "a", "pattern": "a"}]).lines
        self.assertEqual([x["word"] for x in got], ["A", "a"])

    def test_invalid_regex_refused(self):  # LW7
        for pat in ("(", "[", "*a", "\\", "a{2,1}", "(?:", ")", "a)", "[b-a]", "\\1(a)", "a**", "a{1}{2}"):
            with self.subTest(pattern=pat):
                p, m = self.bad(self.ln_data([{"word": "X", "pattern": pat}]), name="l.yml")
                self.assertTrue(m.startswith("%s: lines.0.pattern: not a valid regular expression (" % p), m)

    def test_pattern_dialect_same_on_both(self):  # LW8, V4 (D-Q11): refused by the dialect, not by re.compile
        cases = (("a\\++", POSSESSIVE), ("a*+", POSSESSIVE), ("a++", POSSESSIVE), ("a?+", POSSESSIVE), ("a{2}+", POSSESSIVE),
                 ("(?>a)", GROUP_Q), ("a(?i)b", GROUP_Q), ("(?i:a)", GROUP_Q), ("(?P<n>x)", GROUP_Q),
                 ("(?P<a>x)(?P<a>y)", GROUP_Q), ("(?<n>x)", GROUP_Q), ("(?<=a)b", GROUP_Q), ("(?(1)a|b)", GROUP_Q),
                 ("(?#c)", GROUP_Q), ("(?", GROUP_Q), ("(a)*", QUANT), ("(a)+", QUANT), ("(a){2}", QUANT),
                 ("(?:a|b)+", QUANT), ("(a|aa)+b", QUANT), ("(?=a)*", QUANT), ("(a)*?", QUANT),
                 ("\\w", ESC), ("\\W", ESC), ("\\d", ESC), ("\\D", ESC), ("\\s", ESC), ("\\S", ESC), ("\\b", ESC),
                 ("\\B", ESC), ("[\\d]", ESC), ("a\\w+", ESC), ("é", ASCII), ("a\tb", ASCII), ("a\x7fb", ASCII),
                 ("a\nb", ASCII), ("ࡰ", ASCII), ("\U0001fae8", ASCII), ("a b", ASCII))
        for pat, text in cases:
            with self.subTest(pattern=pat):
                self.refused([{"word": "X", "pattern": pat}], "lines.0.pattern", text)
        for pat in (STAND_IN, "CHECKPOINT x", "Ruling.*", "[A-Za-z]+ [0-9]{2,4}", "(?:a|b)c", "a(?=b)b", "a(?!b)",
                    "(a|b)?c", "x\\.y", "x\\\\y", "^a$", "\\(?a", "\\)*", "[)*]x", "[^ ]+", "a{,3}", "a{2,3}?",
                    "[(?]", "(?:" * 20 + "a" + ")" * 20, "((((a))))", "[]a)*]", "[^]a)*]", "(a)" * 25, "(?:a)" * 25):  # "a\\++" is refused: the textual rule
            with self.subTest(accepted=pat):
                self.assertEqual(self.ln([{"word": "X", "pattern": pat}]).lines[0]["pattern"], pat)

    def test_pattern_compiled_with_ascii_flag(self):  # D-Q11: the compiled object carries re.ASCII
        s = self.ln([{"word": "X", "pattern": "X [^ ]+"}, {"word": "Y", "pattern": "Y"}])
        self.assertEqual(sorted(s.rules), ["X", "Y"])
        for word, (pattern, compiled) in s.rules.items():
            self.assertTrue(compiled.flags & re.ASCII, word)
            self.assertEqual(compiled.flags, re.compile("x", re.ASCII).flags, word)  # no IGNORECASE, DOTALL, MULTILINE
            self.assertEqual(compiled.pattern, pattern)
        self.assertEqual(s.rules["X"][0], "X [^ ]+")

    def test_pattern_variable_count_cap(self):  # F-20261118-ff4c: at most 24 variable quantifiers and alternations
        many = "more than 24 quantifiers and alternations"
        ok = ("a?" * 24, "a?|" * 12, "(?:a|a)" * 24, "a{2,3}" * 24, "a{2,}" * 24, "a{,3}" * 24, "a*?" * 12, "a??" * 12,
              "a{2}" * 100, "a{2}?" * 24, "a{2,3}?" * 12, "[?][*][+][|]" * 100, "\\?\\*\\+\\|" * 100, "(?:a)" * 100, "(?=a)" * 100,
              "(?!a)" * 100, "{x" * 100, "{}" * 100, "a" * 5000, "a+" * 12 + "b*" * 12, "a*?" * 6 + "a|" * 12)  # a lazy ? counts: "a*?" is 2
        for pat in ok:
            with self.subTest(loads=pat[:30], n=len(pat)):
                self.assertEqual(self.ln([{"word": "X", "pattern": pat}]).lines[0]["pattern"], pat)
        for pat in ("a?" * 25, "a?" * 25 + "a" * 25, "a?|" * 12 + "a?", "(?:a|a)" * 25, "a{2,3}" * 25, "a{2,}" * 25,
                    "a{,3}" * 25, "a*" * 25, "a+" * 25, "a|" * 25, "a*?" * 13, "a??" * 13, "a{2}?" * 25, "a{2,3}?" * 13, "a*?" * 12 + "b|", "(?:a|b)?" * 13,
                    "a?" * 24 + "b|c"):
            with self.subTest(refused=pat[:30], n=len(pat)):
                self.refused([{"word": "X", "pattern": pat}], "lines.0.pattern", many)

    def test_pattern_group_nesting_cap(self):  # LW9: no RecursionError can differ between interpreters
        deep = "(?:" * 21 + "a" + ")" * 21
        want = "groups nested more than 20 deep are not supported"
        self.refused([{"word": "X", "pattern": deep}], "lines.0.pattern", want)
        self.refused([{"word": "X", "pattern": "(?:" * 1000 + ")" * 1000}], "lines.0.pattern", want)
        self.refused([{"word": "X", "pattern": "(" * 1000 + ")" * 1000}], "lines.0.pattern", want)

    def test_pattern_other_exceptions_are_schema_errors(self):  # LW9 (D-Q11: every exception of re.compile)
        path = self.put("l.yml", self.ln_data([{"word": "X", "pattern": "a"}]))
        for exc in (RuntimeError("invalid SRE code"), OverflowError("x"), RecursionError("x"), ValueError("v"),
                    MemoryError(), Exception("e"), re.error("boom")):
            with self.subTest(exc=type(exc).__name__):
                with mock.patch.object(schema.re, "compile", side_effect=exc):
                    with self.assertRaises(SchemaError) as cm:
                        load_schema(path)
                name = "re.error: boom" if isinstance(exc, re.error) else type(exc).__name__  # 3.13 names the class PatternError
                self.assertEqual(str(cm.exception),
                                 "%s: lines.0.pattern: not a valid regular expression (%s)" % (path, name))
        for pat in ("a{4294967296}", "a{99999999999999999999}"):  # a real OverflowError on both interpreters
            with self.subTest(pattern=pat):
                p, m = self.bad(self.ln_data([{"word": "X", "pattern": pat}]), name="l.yml")
                self.assertEqual(m, "%s: lines.0.pattern: not a valid regular expression (OverflowError)" % p)

    def test_pattern_warnings_under_w_error(self):  # LW10: one verdict and one text whatever the warning filter
        for pat in ("[a--b]", "[[a]", "[a&&b]", "[a||b]", "[a~~b]"):
            texts = set()
            for mode in ("default", "ignore", "error", "always"):
                with warnings.catch_warnings():
                    warnings.simplefilter(mode)
                    p, m = self.bad(self.ln_data([{"word": "X", "pattern": pat}]), name="l.yml")
                    texts.add(m)
            with self.subTest(pattern=pat):
                self.assertEqual(len(texts), 1, texts)
                self.assertTrue(next(iter(texts)).startswith("%s: lines.0.pattern: not a valid regular expression (" % p))
        with warnings.catch_warnings():  # a clean pattern loads under -W error, and loading emits no warning
            warnings.simplefilter("error")
            self.assertEqual(self.stand_in().lines[0]["pattern"], STAND_IN)

    def test_pattern_size_and_cost(self):  # LW11 (D-Q9 empty; D-Q12 settled by the dialect)
        self.refused([{"word": "X", "pattern": ""}], "lines.0.pattern", "must not be empty")
        big = "a" * 100000
        self.assertEqual(self.ln([{"word": "X", "pattern": big}]).lines[0]["pattern"], big)
        self.refused([{"word": "X", "pattern": "(a|aa)+b"}], "lines.0.pattern", QUANT)

    def test_lines_pattern_roundtrip(self):  # LW12: written with yamlsub.emit, read back byte for byte
        for pat in ("a: b", "a #b", "x\\.y", "\"q\"", "'q'", "[ab]c", "{x", "&x", "!x", "a -- b", "x:y", "- a",
                    "a\\\\b", "% x", "@x", "`x", "|x", ">x", "x #", "# x", " lead", "trail "):
            with self.subTest(pattern=pat):
                got = self.ln([{"word": "X", "pattern": pat}]).lines[0]["pattern"]
                self.assertEqual(got, pat)

    def test_pattern_classes_at_load(self):  # LW13
        for pat in ("\\w", "\\d", "\\s", "\\S", "[^\\s]+"):
            with self.subTest(pattern=pat):
                self.refused([{"word": "X", "pattern": pat}], "lines.0.pattern", ESC)
        self.assertEqual(self.ln([{"word": "X", "pattern": "[^ ]+"}]).lines[0]["pattern"], "[^ ]+")


POSSESSIVE = "possessive quantifiers are not supported"
GROUP_Q = "'(?' is only supported as (?: (?= or (?!"
QUANT = "a quantified group is not supported (a ')' followed by '*', '+' or '{')"
ESC = "the escapes \\w \\W \\d \\D \\s \\S \\b \\B are not supported"
ASCII = "must be printable ASCII (U+0020-U+007E)"
SYMLINK = "is a symlink; directories must be real directories"
TOO_BIG = ["front matter: line 3: integer too large"]


class NestedFiles(GitIsolatedTestCase):
    """Producer 2 (rows NE1-NE17): ``entries_of`` / ``files_of`` with a nested glob."""

    def setUp(self):
        super().setUp()
        self.n = 0
        self.root = make_repo(self.work)
        self.cfg = config.load(self.root)

    def fresh(self):
        """Another fixture repository (a new directory, so no case needs files removed)."""
        self.n += 1
        d = os.path.join(self.tmp, "w%d" % self.n)
        os.mkdir(d)
        self.root = make_repo(d)
        return self.root

    def sch(self, glob=None, exclude=None, files=None):
        sd = os.path.join(self.tmp, "sd")
        os.makedirs(sd, exist_ok=True)
        if files is None:
            item = {"dir": "plan_state", "glob": glob}
            if exclude is not None:
                item["exclude"] = exclude
            files = [item]
        with open(os.path.join(sd, "thing.yml"), "w") as fh:
            fh.write(yamlsub.emit(dict(BASE, files=files)))
        return load_schema(os.path.join(sd, "thing.yml"))

    def touch(self, rel, text="a: 1\n"):
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            fh.write(text)

    def listing(self, glob, **kw):
        return files_of(self.sch(glob, **kw), self.root, self.cfg)

    def test_nested_glob_lists_files_in_subdirectories(self):  # NE1, plan Step 1
        self.touch(PS + "/b/handoff.md")
        self.touch(PS + "/a/handoff.md")
        self.assertEqual(self.listing("*/handoff.md"), [PS + "/a/handoff.md", PS + "/b/handoff.md"])
        self.assertEqual(entries_of(self.sch("*/handoff.md"), self.root, self.cfg),
                         [(PS + "/a/handoff.md", True), (PS + "/b/handoff.md", True)])

    def test_nested_glob_symlinked_directory_refused(self):  # plan Step 1, NE4
        self.touch(PS + "/a/handoff.md")
        os.makedirs(os.path.join(self.tmp, "elsewhere"))
        os.symlink(os.path.join(self.tmp, "elsewhere"), os.path.join(self.root, PS, "link"))
        with self.assertRaises(LayoutError) as cm:
            self.listing("*/handoff.md")
        self.assertEqual((cm.exception.rel, str(cm.exception)), (PS + "/link", SYMLINK))

    def test_nested_glob_file_in_middle_skipped(self):  # plan Step 1, NE4
        self.touch(PS + "/a/handoff.md")
        self.touch(PS + "/c", "plain file")
        self.assertEqual(self.listing("*/handoff.md"), [PS + "/a/handoff.md"])

    def test_nested_glob_sorted_by_full_path(self):  # NE2, NE15 order
        for name in ("a", "a-b", "a b"):
            self.touch(PS + "/" + name + "/handoff.md")
        self.assertEqual(self.listing("*/handoff.md"),
                         [PS + "/a b/handoff.md", PS + "/a-b/handoff.md", PS + "/a/handoff.md"])
        self.touch(PS + "/a/x/f.md")
        self.touch(PS + "/a-b/x/f.md")
        self.assertEqual(self.listing("*/x/f.md"), [PS + "/a-b/x/f.md", PS + "/a/x/f.md"])

    def test_nested_glob_directory_without_match_skipped(self):  # NE3
        self.touch(PS + "/a/handoff.md")
        self.touch(PS + "/c/notes.md")
        os.makedirs(os.path.join(self.root, PS, "d"))
        self.assertEqual(self.listing("*/handoff.md"), [PS + "/a/handoff.md"])

    def test_nested_glob_middle_entry_kinds(self):  # NE4
        s = self.sch("*/handoff.md")
        for kind in ("file", "symlink to dir", "symlink to file", "dangling symlink", "fifo", "directory"):
            with self.subTest(kind=kind):
                self.fresh()
                self.touch(PS + "/a/handoff.md")
                c = os.path.join(self.root, PS, "c")
                if kind == "file":
                    self.touch(PS + "/c", "x")
                elif kind == "symlink to dir":
                    os.makedirs(os.path.join(self.tmp, "t%d" % self.n))
                    os.symlink(os.path.join(self.tmp, "t%d" % self.n), c)
                elif kind == "symlink to file":
                    self.touch("real.md")
                    os.symlink(os.path.join(self.root, "real.md"), c)
                elif kind == "dangling symlink":
                    os.symlink("nowhere", c)
                elif kind == "fifo":
                    os.mkfifo(c)
                else:
                    self.touch(PS + "/c/handoff.md")
                if kind in ("symlink to dir", "symlink to file", "dangling symlink"):
                    with self.assertRaises(LayoutError) as cm:
                        files_of(s, self.root, self.cfg)
                    self.assertEqual((cm.exception.rel, str(cm.exception)), (PS + "/c", SYMLINK))
                elif kind == "directory":
                    self.assertEqual(files_of(s, self.root, self.cfg), [PS + "/a/handoff.md", PS + "/c/handoff.md"])
                else:
                    self.assertEqual(files_of(s, self.root, self.cfg), [PS + "/a/handoff.md"])

    def test_nested_glob_last_segment_kinds_listed(self):  # NE5
        self.touch("real.md")
        base = os.path.join(self.root, PS)
        self.touch(PS + "/a/handoff.md")
        os.makedirs(base + "/b")
        os.symlink(os.path.join(self.root, "real.md"), base + "/b/handoff.md")
        os.makedirs(base + "/c")
        os.symlink("nowhere", base + "/c/handoff.md")
        os.makedirs(base + "/d")
        os.mkfifo(base + "/d/handoff.md")
        os.makedirs(base + "/e/handoff.md")
        want = [PS + "/%s/handoff.md" % x for x in "abcde"]
        self.assertEqual(self.listing("*/handoff.md"), want)
        self.assertEqual({fg for _, fg in entries_of(self.sch("*/handoff.md"), self.root, self.cfg)}, {True})

    def test_nested_glob_depth(self):  # NE6
        for rel in ("f.md", "a/f.md", "a/b/f.md", "a/b/c/f.md"):
            self.touch(PS + "/" + rel)
        for glob, want in (("f.md", "f.md"), ("*/f.md", "a/f.md"), ("*/*/f.md", "a/b/f.md"),
                           ("*/*/*/f.md", "a/b/c/f.md")):
            with self.subTest(glob=glob):
                self.assertEqual(self.listing(glob), [PS + "/" + want])
        self.assertEqual(self.listing("*/*/*/*/f.md"), [])

    def test_nested_glob_missing_levels(self):  # NE7 (D-Q4)
        self.assertEqual(self.listing("*/handoff.md"), [])  # plan_state absent
        self.touch(PS + "/a/handoff.md")
        self.assertEqual(self.listing("c/handoff.md"), [])  # nothing named c
        real = os.lstat

        def vanishing(path, *a, **kw):
            if path.endswith(PS + "/a"):
                raise FileNotFoundError(errno.ENOENT, "No such file or directory", path)
            return real(path, *a, **kw)
        with mock.patch.object(schema.os, "lstat", side_effect=vanishing):
            with self.assertRaises(LayoutError) as cm:
                self.listing("*/handoff.md")
        self.assertEqual((cm.exception.rel, str(cm.exception)), (PS + "/a", "cannot read (No such file or directory)"))

    def test_nested_glob_dir_component_checks_unchanged(self):  # NE8
        self.touch(PS + "/a/handoff.md")
        s = self.sch("*/handoff.md")
        other = os.path.join(self.tmp, "other")
        os.rename(os.path.join(self.root, PS), other)
        os.symlink(other, os.path.join(self.root, PS))
        with self.assertRaises(LayoutError) as cm:
            files_of(s, self.root, self.cfg)
        self.assertEqual((cm.exception.rel, str(cm.exception)), (PS, SYMLINK))
        self.fresh()
        self.touch(".strict-delivery/state", "x")
        with self.assertRaises(LayoutError) as cm:
            self.listing("*/handoff.md")
        self.assertEqual((cm.exception.rel, str(cm.exception)), (".strict-delivery/state", "is not a directory"))

    def test_nested_glob_odd_names_same_on_both(self):  # NE9, V5
        names = [".h", "a b", "é", "ࡰ", "\U0001fae8", "Ⱟ", "ౝ"]
        for n in names:
            self.touch(PS + "/" + n + "/handoff.md")
        self.assertEqual(self.listing("*/handoff.md"), [PS + "/" + n + "/handoff.md" for n in sorted(names)])
        self.assertEqual(sorted(names), [".h", "a b", "é", "ࡰ", "ౝ", "Ⱟ", "\U0001fae8"])
        self.assertEqual(self.listing("ࡰ/handoff.md"), [PS + "/ࡰ/handoff.md"])
        self.assertEqual(self.listing("?/handoff.md"), [PS + "/" + n + "/handoff.md"
                                                         for n in ("é", "ࡰ", "ౝ", "Ⱟ", "\U0001fae8")])

    def test_nested_glob_segment_matching(self):  # NE10
        for n in ("a", "a1", "a2", "ab", "b", "c"):
            self.touch(PS + "/" + n + "/handoff.md")
        h = "/handoff.md"
        self.assertEqual(self.listing("a?/handoff.md"), [PS + "/" + n + h for n in ("a1", "a2", "ab")])
        self.assertEqual(self.listing("[ab]/handoff.md"), [PS + "/a" + h, PS + "/b" + h])
        self.assertEqual(self.listing("a/handoff.md"), [PS + "/a" + h])
        self.assertEqual(self.listing("[!ab]*/handoff.md"), [PS + "/c" + h])

    def test_nested_glob_exclude_last_segment_only(self):  # NE11
        self.touch(PS + "/a/handoff.md")
        self.touch(PS + "/b/handoff.md")
        self.assertEqual(self.listing("*/handoff.md", exclude=["handoff.md"]), [])
        both = [PS + "/a/handoff.md", PS + "/b/handoff.md"]
        self.assertEqual(self.listing("*/handoff.md", exclude=["a"]), both)
        # owner answer 2026-11-22 (a): an entry with "/" is a path pattern, so this one now excludes a/handoff.md
        self.assertEqual(self.listing("*/handoff.md", exclude=["a/handoff.md"]), [PS + "/b/handoff.md"])
        self.touch(PS + "/a/skip.md")
        self.assertEqual(self.listing("a/*.md", exclude=["skip.md"]), [PS + "/a/handoff.md"])

    # ---- Task 6E.1-x, owner answer 2026-11-22 (a), legacy pre-schema transcripts: rows X1-X4, X6, X10, X15, X16
    MG = "*/mutations/*"
    T = "/mutations/T.txt"

    def test_exclude_plain_name_is_literal_basename(self):  # X1
        self.touch(PS + "/a/index.yml")
        self.touch(PS + "/a/y.yml")
        self.touch(PS + "/b/index.yml")
        self.assertEqual(self.listing("*/*.yml", exclude=["index.yml"]), [PS + "/a/y.yml"])

    def test_exclude_plain_name_never_fnmatch(self):  # X2
        for n in ("x.yml", "*.yml", "y.yml"):
            self.touch(PS + "/a/" + n)
        self.assertEqual(self.listing("*/*.yml", exclude=["*.yml"]), [PS + "/a/x.yml", PS + "/a/y.yml"])
        self.assertEqual(self.listing("*/*.yml", exclude=["x.y?l"]), [PS + "/a/*.yml", PS + "/a/x.yml", PS + "/a/y.yml"])

    def test_exclude_path_pattern_matches(self):  # X3
        self.touch(PS + "/p-b" + self.T)
        self.assertEqual(self.listing(self.MG, exclude=["p-b/mutations/*"]), [])
        self.touch(PS + "/p-b/mutations/U.txt")
        self.touch(PS + "/p-b/other/V.txt")
        self.assertEqual(self.listing(self.MG, exclude=["p-b/mutations/T.txt"]), [PS + "/p-b/mutations/U.txt"])
        self.assertEqual(self.listing(self.MG, exclude=["p-?/mutations/T.t?t"]), [PS + "/p-b/mutations/U.txt"])
        self.assertEqual(self.listing(self.MG, exclude=["*/mutations/T*"]), [PS + "/p-b/mutations/U.txt"])

    def test_exclude_path_pattern_sibling_dirs_still_listed(self):  # X4
        for d in ("p", "p-b", "p-bb"):
            self.touch(PS + "/" + d + self.T)
        self.assertEqual(self.listing(self.MG, exclude=["p-b/mutations/*"]), [PS + "/p-bb" + self.T, PS + "/p" + self.T])

    def test_exclude_path_pattern_is_case_sensitive(self):  # X6
        self.touch(PS + "/p-b" + self.T)
        self.assertEqual(self.listing(self.MG, exclude=["P-B/mutations/*"]), [PS + "/p-b" + self.T])
        self.assertEqual(self.listing(self.MG, exclude=["p-b/MUTATIONS/*"]), [PS + "/p-b" + self.T])
        self.assertEqual(self.listing(self.MG, exclude=["p-b/mutations/t.TXT"]), [PS + "/p-b" + self.T])

    def test_exclude_mixed_entries_both_semantics(self):  # X10
        self.touch(PS + "/p-b" + self.T)
        self.touch(PS + "/p/mutations/index.yml")
        self.touch(PS + "/p" + self.T)
        self.assertEqual(self.listing(self.MG, exclude=["index.yml", "p-b/mutations/*"]), [PS + "/p" + self.T])
        self.assertEqual(self.listing(self.MG, exclude=["p-b/mutations/*"]),
                         [PS + "/p/mutations/T.txt", PS + "/p/mutations/index.yml"])

    def test_exclude_pattern_with_wrong_segment_count_matches_nothing(self):  # X5 (defence in depth, hand-built)
        self.touch(PS + "/p-b" + self.T)
        s = self.sch(self.MG, exclude=["p-b/mutations/*"])
        for bad in (["p-b/*"], ["p-b/mutations/*/x"], ["*/*"]):  # load refuses these; the listing must still not match
            with self.subTest(entry=bad):
                s.files[0]["exclude"] = bad
                self.assertEqual(files_of(s, self.root, self.cfg), [PS + "/p-b" + self.T])

    def test_exclude_pc1_long_numeric_segments(self):  # X15 (a file name is at most 255 bytes; the entry may be 4300+)
        for n in (4300, 4301):
            long_entry = "9" * n + "/mutations/*"
            self.assertEqual(self.sch(self.MG, exclude=[long_entry]).files[0]["exclude"], [long_entry])
        name = "9" * 250
        self.touch(PS + "/" + name + self.T)
        self.touch(PS + "/p" + self.T)
        self.assertEqual(self.listing(self.MG, exclude=[name + "/mutations/*"]), [PS + "/p" + self.T])
        self.assertEqual(self.listing(self.MG, exclude=["9" * 4301 + "/mutations/*"]),
                         [PS + "/" + name + self.T, PS + "/p" + self.T])

    def test_exclude_pc1_unicode_names_same_on_both(self):  # X16: U+1F6DD is Cn in Unicode 13 (3.9), So in 15 (3.13)
        names = ["\U0001f6dd", "Ꟁ", "ࡰ"]  # not "ꟁ" too: the fixture file system folds case, so it is the same directory
        for n in names:
            self.touch(PS + "/" + n + self.T)
        for n in names:
            with self.subTest(name=n):
                self.assertEqual(self.listing(self.MG, exclude=[n + "/mutations/*"]),
                                 [PS + "/" + m + self.T for m in sorted(names) if m != n])
        self.assertEqual(self.listing(self.MG, exclude=["?/mutations/*"]), [])

    def test_nested_glob_unreadable_directory(self):  # NE13 (D-Q4)
        if os.geteuid() == 0:
            self.skipTest("root reads every directory")
        self.touch(PS + "/c/handoff.md")
        self.touch(PS + "/a/handoff.md")
        s = self.sch("*/handoff.md")
        for rel in (PS + "/c", PS):
            with self.subTest(rel=rel):
                full = os.path.join(self.root, rel)
                os.chmod(full, 0)
                self.addCleanup(os.chmod, full, 0o755)
                with self.assertRaises(LayoutError) as cm:
                    files_of(s, self.root, self.cfg)
                self.assertEqual((cm.exception.rel, str(cm.exception)),
                                 (rel, "cannot read the directory (Permission denied)"))
                os.chmod(full, 0o755)

    def test_nested_glob_with_path_items(self):  # NE14
        self.touch(PS + "/a/handoff.md")
        self.touch(".strict-delivery/context.yml")
        s = self.sch(files=[{"path": "context"}, {"dir": "plan_state", "glob": "*/handoff.md"}])
        self.assertEqual(files_of(s, self.root, self.cfg), [".strict-delivery/context.yml", PS + "/a/handoff.md"])
        self.assertEqual(schema.expected_paths(s, self.cfg), [".strict-delivery/context.yml"])

    def test_nested_glob_real_repository(self):  # NE16
        repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        got = files_of(self.sch("*/handoff.md"), repo, config.load(repo))
        want = [PS + "/2026-10-31-strict-delivery-framework-b/handoff.md", PS + "/2026-10-31-strict-delivery-framework/handoff.md"]
        self.assertEqual([g for g in got if g in want], want)
        self.assertTrue(all(g.endswith("/handoff.md") and g.count("/") == PS.count("/") + 2 for g in got), got)
        self.assertEqual(got, sorted(got))

    def test_nested_glob_root_must_be_the_toplevel(self):  # NE15 with a nested glob
        sub = os.path.join(self.root, "sub")
        os.mkdir(sub)
        with self.assertRaises(GateError) as cm:
            files_of(self.sch("*/handoff.md"), sub, self.cfg)
        self.assertEqual(str(cm.exception), "git rev-parse --show-toplevel: root must be the repository top level")

    def test_nested_glob_unknown_dir_key(self):  # NE17
        s = self.sch(files=[{"dir": "stat", "glob": "*/handoff.md"}])
        with self.assertRaises(SchemaError) as cm:
            files_of(s, self.root, self.cfg)
        self.assertEqual(str(cm.exception), "%s: files: 'stat' is not a key of paths" % s.path)


class FrontMatterValidate(Dirs):
    """Producer 4 (rows FM1-FM16): ``validate_front_matter``."""

    def setUp(self):
        super().setUp()
        self.hs = self.fm()
        self.t = "---\nschema: %s\nplan: p\n---\n" % HTAG

    def v(self, text, schema_=None):
        return validate_front_matter(schema_ or self.hs, text, CFG)

    def test_front_matter_valid(self):  # FM1, plan Step 1
        self.assertEqual(self.v("---\nschema: h/1\nplan: p\n---\nbody\n".replace("h/1", HTAG)), [])
        self.assertEqual(self.v(self.t), [])
        self.assertEqual(self.v(self.t[:-1]), [])  # no newline after the closing line
        self.assertEqual(self.v("---\nschema: %s\nplan: p\n---" % HTAG), [])

    def test_front_matter_body_is_free_text(self):  # FM1
        for body in ("---\n", "...\n", "\t\n", "a\x00b\n", "a\rb\n", "﻿\n", "\u0085\n", "\ud800\n", "x: [\n",
                     "\x7f", " ", "-" * 100, "x" * 1000000):
            with self.subTest(body=body[:12]):
                self.assertEqual(self.v(self.t + body), [])

    def test_front_matter_first_line(self):  # FM2
        want = ["front matter: first line must be '---'"]
        rest = "schema: %s\nplan: p\n---\n" % HTAG
        for first in ("", "x", "", " ---", "---  ", "--- ", "----", "-- -", "---x", "﻿---", "---\r", "- --",
                      " ---"):
            with self.subTest(first=first):
                self.assertEqual(self.v(first + "\n" + rest), want)
        self.assertEqual(self.v(""), want)
        self.assertEqual(self.v("\n---\n" + rest), want)
        self.assertEqual(self.v(self.t.replace("\n", "\r\n")), want)

    def test_front_matter_missing_closer(self):  # FM3, plan Step 1
        want = ["front matter: no closing '---' line"]
        self.assertEqual(self.v("---\nschema: %s\n" % HTAG), want)
        for text in ("---\n", "---", "---\nschema: %s\nplan: p\n--- \n" % HTAG, "---\nplan: p\n----\n",
                     "---\nplan: p\n...\n", "---\nplan: p\n ---\n", "---\nplan: p\n---\r\n", "---\nplan: p\n\t---\n"):
            with self.subTest(text=text):
                self.assertEqual(self.v(text), want)

    def test_front_matter_closer_forms(self):  # FM3
        self.assertEqual(self.v("---\nschema: %s\nplan: p\n---" % HTAG), [])  # the closer at EOF with no newline
        self.assertEqual(self.v("---\nschema: %s\nplan: p\n---\n" % HTAG), [])

    def test_front_matter_first_closer_wins(self):  # FM4
        self.assertEqual(self.v(self.t + "more: 1\n---\nx\n---\n"), [])
        self.assertEqual(self.v("---\nschema: %s\nplan: |\n  x\n---\n" % HTAG), [])
        self.assertEqual(self.v("---\nschema: %s\nplan: |\n  x\n---\ny: 1\n---\n" % HTAG), [])

    def test_front_matter_empty_is_not_a_mapping(self):  # FM5, FM6, FM11
        want = ["front matter: must be a mapping"]
        for text in ("---\n---\n", "---\n# c\n---\n", "---\n\n---\n", "---\n- a\n---\n", "---\njust text\n---\n",
                     "---\n5\n---\n", "---\ntrue\n---\n", "---\nnull\n---\n", "---\n- a\n- b\n---\nschema: %s\n" % HTAG):
            with self.subTest(text=text):
                self.assertEqual(self.v(text), want)

    def test_front_matter_yaml_line_is_file_line(self):  # FM7, plan Step 1
        self.assertIn("front matter: line 4:", self.v("---\nschema: %s\nplan: p\nx: [\n---\n" % HTAG)[0])
        cases = (("---\nschema: %s\nplan: p\nx: [\n---\n" % HTAG, "front matter: line 4: unterminated flow sequence"),
                 ("---\nschema: [\nplan: p\n---\n", "front matter: line 2: unterminated flow sequence"),
                 ("---\na: 1\na: 2\n---\n", "front matter: line 3: duplicate key 'a'"),
                 ("---\nschema: %s\n...\nplan: p\n---\n" % HTAG, "front matter: line 3: document markers are not supported"),
                 ("---\nschema:\t%s\n---\n" % HTAG, "front matter: line 2: tab used as a separator after ':'"),
                 ("---\nschema: %s\nplan: p\nz: [\n---\nz: ]\n" % HTAG, "front matter: line 4: unterminated flow sequence"))
        for text, want in cases:
            with self.subTest(text=text):
                self.assertEqual(self.v(text), [want])

    def test_front_matter_control_characters(self):  # FM8
        want = ["front matter: line 2: control character not allowed"]
        for ch in ("\r", "\x00", "\x01", "\x7f", "\ud800", "\x1f", "\x0b"):
            with self.subTest(ch=ch):
                self.assertEqual(self.v("---\nschema: %s%s\nplan: p\n---\n" % (HTAG, ch)), want)

    def test_front_matter_integer_limits_same_on_both(self):  # FM9, V1
        for limit in INT_LIMITS:
            with int_limit(limit):
                self.assertEqual(self.v("---\nschema: %s\nplan: 5\n---\n" % HTAG), ["plan: must be a non-empty string"])
                self.assertEqual(self.v("---\nschema: %s\nplan: %s\n---\n" % (HTAG, "9" * 1000)),
                                 TOO_BIG if limit == 640 else ["plan: must be a non-empty string"])  # see U2 of the report
                for n in (1001, 4300, 4301):
                    with self.subTest(limit=limit, digits=n):
                        self.assertEqual(self.v("---\nschema: %s\nplan: %s\n---\n" % (HTAG, "9" * n)), TOO_BIG)

    def test_front_matter_schema_errors_unprefixed(self):  # FM10
        def t(body):
            return "---\n" + body + "---\n"
        self.assertEqual(self.v(t("schema: %s\nplan: p\nzzz: 1\n" % HTAG)), ["zzz: unknown key"])
        self.assertEqual(self.v(t("schema: %s\n" % HTAG)), ["plan: required key is missing"])
        self.assertEqual(self.v(t("schema: %s\nplan: 5\n" % HTAG)), ["plan: must be a non-empty string"])
        self.assertEqual(self.v(t("schema: %s\nplan: null\n" % HTAG)), ["plan: must not be null"])
        self.assertEqual(self.v(t("schema: h/2\nplan: p\n")),
                         ["schema: expected %s, got h/2; run /strict-delivery:upgrade" % HTAG])
        self.assertEqual(self.v(t("schema: x/1\nplan: p\n")), ["schema: expected %s, got x/1" % HTAG])
        self.assertEqual(self.v(t("plan: p\n")), ["schema: expected %s, got (missing)" % HTAG])
        long = self.v(t("schema: %s\nplan: p\n" % ("a" * 4301)))
        self.assertEqual(long, ["schema: expected %s, got %s" % (HTAG, "a" * 4301)])
        self.assertEqual(self.v(t("zzz: 1\nplan: p\nschema: %s\nyyy: 2\n" % HTAG)), ["zzz: unknown key", "yyy: unknown key"])

    def test_front_matter_yaml_subset_applies(self):  # FM12
        self.assertEqual(self.v("---\nschema: %s\nplan: a: b: c\n---\n" % HTAG),
                         ["front matter: line 3: ':' followed by whitespace is not allowed in a plain scalar"])
        for val in ('"x: y"', "|\n  text", "|-\n  text", "'q'", "a b", "a#b"):
            with self.subTest(value=val):
                self.assertEqual(self.v("---\nschema: %s\nplan: %s\n---\n" % (HTAG, val)), [])
        for val in ("[a, b]", "\n  - a\n  - b"):
            with self.subTest(value=val):
                self.assertEqual(self.v("---\nschema: %s\nplan: %s\n---\n" % (HTAG, val)),
                                 ["plan: must be a non-empty string"])
        self.assertEqual(self.v("---\nschema: %s\nplan: {a: b}\n---\n" % HTAG),
                         ["front matter: line 3: flow mappings are not supported"])

    def test_front_matter_numeric_sha_needs_quotes(self):  # FM13
        s = self.fm(fields={"schema": {"type": "str"}, "head": {"type": "sha"}})
        for head, want in (("1234567", ["head: must be 7 to 40 lowercase hex digits"]), ("0123456", []),
                           ("1234567e1", []), ('"1234567"', []), ("abcdef0", [])):
            with self.subTest(head=head):
                self.assertEqual(self.v("---\nschema: %s\nhead: %s\n---\n" % (HTAG, head), s), want)

    def test_front_matter_text_types(self):  # FM14 (D-Q8)
        class S(str):
            pass
        for text in (None, b"---\n", 5, S(self.t), [], True):
            with self.subTest(text=type(text).__name__):
                self.assertEqual(self.v(text), ["front matter: text must be a string"])

    def test_front_matter_split_on_newline_only(self):  # FM15
        for ch in (" ", "\u0085", " ", "\x0c"):
            with self.subTest(ch=ch):
                self.assertEqual(self.v("---\nschema: %s\nplan: a%sb\n---\n" % (HTAG, ch)),
                                 ["front matter: line 3: control character not allowed"] if ch == "\x0c" else [])
        self.assertEqual(self.v("---\nschema: %s \nplan: p\n---\n" % HTAG),
                         ["schema: expected %s, got %s " % (HTAG, HTAG)])

    def test_front_matter_large_input(self):  # FM16
        keys = "".join("k%d: 1\n" % i for i in range(100000))
        got = self.v("---\nschema: %s\nplan: p\n%s---\n" % (HTAG, keys))
        self.assertEqual(len(got), 100000)
        self.assertEqual((got[0], got[-1]), ("k0: unknown key", "k99999: unknown key"))

    def test_front_matter_returns_a_list_and_leaves_the_schema(self):
        got = self.v(self.t)
        self.assertIs(type(got), list)
        self.assertEqual(self.hs.fields, {"schema": {"type": "str"}, "plan": {"type": "str"}})


class LinesValidate(Dirs):
    """Producer 6 (rows LV1-LV17): ``validate_markdown`` with ``lines``."""

    def setUp(self):
        super().setUp()
        self.ls = self.stand_in()

    def v(self, *lines, schema_=None):
        return validate_markdown(schema_ or self.ls, "\n".join((LTAG,) + lines))

    def err(self, n, pat=STAND_IN, word="CHECKPOINT"):
        return "line %d: '%s' line does not match %s" % (n, word, pat)

    def test_lines_pattern_checked(self):  # LV1, plan Step 1
        self.assertEqual(validate_markdown(self.ls, LTAG + "\nCHECKPOINT bad\nprose CHECKPOINT x\n"),
                         ["line 2: 'CHECKPOINT' line does not match " + STAND_IN])

    def test_lines_conforming_line_passes(self):  # LV2
        self.assertEqual(self.v(GOOD_LINE, "prose", GOOD_LINE + "", ""), [])
        self.assertEqual(self.v("CHECKPOINT xࡰ y head=" + "a" * 40), [])

    def test_lines_word_with_colon(self):  # plan Step 1: "Ruling (x): y" is keyword-led
        rs = self.ln([{"word": "Ruling", "pattern": "Ruling: .*"}])
        self.assertEqual(validate_markdown(rs, LTAG + "\nRuling (x): y\n"),
                         ["line 2: 'Ruling' line does not match Ruling: .*"])
        self.assertEqual(validate_markdown(rs, LTAG + "\nRuling: y\n"), [])
        self.assertEqual(validate_markdown(rs, LTAG + "\nRuling y\n"), ["line 2: 'Ruling' line does not match Ruling: .*"])

    def test_lines_first_token_rule(self):  # LV3, LV4
        cases = (("CHECKPOINT", True), ("CHECKPOINT:", True), ("CHECKPOINT::", False), ("CHECKPOINT:x", False),
                 ("CHECKPOINT\tx", False), ("checkpoint x", False), ("CHECKPOINTS x", False), ("CHECKPOINT  x", True),
                 ("prose CHECKPOINT x", False), ("x CHECKPOINT", False), ("a: CHECKPOINT", False),
                 ("CHECKPOINT: a b head=abcdef0", True), ("CHECKPOINT a", True), ("Checkpoint a", False))
        for line, keyword_led in cases:
            with self.subTest(line=line):
                self.assertEqual(self.v(line), [self.err(2)] if keyword_led else [])

    def test_lines_token_rule_against_reference_oracle(self):  # the table's Oracle section
        def keyword_led(line):  # the plan's rule written independently: first token to the first space, one ':' off
            tok = line.split(" ", 1)[0]
            if tok.endswith(":"):
                tok = tok[:-1]
            return tok == "CHECKPOINT"
        words = ("CHECKPOINT", "CHECKPOINT:", "CHECKPOINT::", "checkpoint", "CHECKPOINTS", "CHECKPOINT\t", "CHECKPOINT:x",
                 "", "x", "Z:")
        sufs = ("", " x", ":x", "  x", " x y", "\tx", " CHECKPOINT", " " + GOOD_LINE[11:], "\r", " a b head=abcdef0")
        pres = ("", " ", "x ", "  ", "\t")
        lines = [p + w + s for p in pres for w in words for s in sufs]
        fm = re.compile(STAND_IN)
        want = ["line %d: 'CHECKPOINT' line does not match %s" % (i + 2, STAND_IN)
                for i, ln in enumerate(lines) if keyword_led(ln) and not fm.fullmatch(ln)]
        self.assertGreater(len(want), 8)
        self.assertGreater(len([ln for ln in lines if keyword_led(ln) and fm.fullmatch(ln)]), 0)
        self.assertEqual(self.v(*lines), want)

    def test_lines_leading_space_never_keyword(self):  # LV5
        self.assertEqual(self.v(" CHECKPOINT x", "  CHECKPOINT", "   ", "", " ", " CHECKPOINT"), [])

    def test_lines_first_line_not_checked(self):  # LV6
        self.assertEqual(validate_markdown(self.ls, LTAG), [])
        s = self.stand_in(first_line="CHECKPOINT ok")
        self.assertEqual(validate_markdown(s, "CHECKPOINT ok\nCHECKPOINT ok\n"), [self.err(2)])
        self.assertEqual(validate_markdown(s, "CHECKPOINT ok\n"), [])
        self.assertEqual(validate_markdown(self.ls, "CHECKPOINT bad\nCHECKPOINT bad\n"),
                         ["first line: expected '%s'" % LTAG])

    def test_lines_match_is_case_sensitive(self):  # F-20261118-qmmm: only re.ASCII, no IGNORECASE
        upper = self.ln([{"word": "CHECKPOINT", "pattern": "CHECKPOINT X"}])
        self.assertEqual(validate_markdown(upper, LTAG + "\nCHECKPOINT X\n"), [])
        self.assertEqual(validate_markdown(upper, LTAG + "\nCHECKPOINT x\n"), [self.err(2, "CHECKPOINT X")])
        lower = self.ln([{"word": "Ruling", "pattern": "Ruling: [a-z]+"}])
        self.assertEqual(validate_markdown(lower, LTAG + "\nRuling: abc\n"), [])
        self.assertEqual(validate_markdown(lower, LTAG + "\nRuling: ABC\nRuling: abC\n"),
                         [self.err(2, "Ruling: [a-z]+", "Ruling"), self.err(3, "Ruling: [a-z]+", "Ruling")])
        self.assertEqual(validate_markdown(lower, LTAG + "\nruling: abc\n"), [])  # the word is case sensitive too

    def test_lines_fullmatch_decides(self):  # LV7, LV8
        def s_(pat, word="CHECKPOINT"):
            return self.ln([{"word": word, "pattern": pat}])
        s = s_("CHECKPOINT x")
        self.assertEqual(validate_markdown(s, LTAG + "\nCHECKPOINT x\n"), [])
        self.assertEqual(validate_markdown(s, LTAG + "\nCHECKPOINT x y\n"), [self.err(2, "CHECKPOINT x")])
        self.assertEqual(validate_markdown(s, LTAG + "\nx CHECKPOINT x\n"), [])
        self.assertEqual(validate_markdown(s, LTAG + "\nCHECKPOINT xx\n"), [self.err(2, "CHECKPOINT x")])
        a = s_("^CHECKPOINT x$")
        self.assertEqual(validate_markdown(a, LTAG + "\nCHECKPOINT x\nCHECKPOINT x \n"), [self.err(3, "^CHECKPOINT x$")])
        d = s_("a$", "a")
        self.assertEqual(validate_markdown(d, LTAG + "\na\na \n"), [self.err(3, "a$", "a")])

    def test_lines_errors_in_order_with_line_numbers(self):  # LV9
        two = self.ln([{"word": "CHECKPOINT", "pattern": STAND_IN}, {"word": "Ruling", "pattern": "Ruling: .+"}])
        got = validate_markdown(two, "\n".join((LTAG, "CHECKPOINT bad", GOOD_LINE, "Ruling: ok", "prose", "Ruling",
                                                 "", "CHECKPOINT", "Ruling: x")))
        self.assertEqual(got, [self.err(2), self.err(6, "Ruling: .+", "Ruling"), self.err(8)])

    def test_lines_beside_table_and_headings(self):  # LV10
        t = self.stand_in(table=["id"])
        self.assertEqual(validate_markdown(t, "\n".join((LTAG, "| x |", "|---|", "CHECKPOINT bad"))),
                         ["table: header must be '| id |', got '| x |'", self.err(4)])
        self.assertEqual(validate_markdown(t, "\n".join((LTAG, "| id |", "|---|", "| CHECKPOINT x |", "CHECKPOINT bad"))),
                         [self.err(5)])
        h = self.stand_in(headings=["## One"])
        self.assertEqual(validate_markdown(h, "\n".join((LTAG, "## Two", "CHECKPOINT bad"))),
                         ["headings: expected [## One], got [## Two]", self.err(3)])
        self.assertEqual(validate_markdown(h, "\n".join((LTAG, "## One", GOOD_LINE))), [])
        self.assertEqual(validate_markdown(self.ls, LTAG + "\n| CHECKPOINT |\n"), [])

    def test_lines_fences_not_special(self):  # LV11
        self.assertEqual(self.v("```", "CHECKPOINT bad", "```", "> CHECKPOINT x", "- CHECKPOINT x", "* CHECKPOINT x"),
                         [self.err(3)])

    def test_lines_line_ends(self):  # LV12
        self.assertEqual(validate_markdown(self.ls, (LTAG + "\nCHECKPOINT bad\n").replace("\n", "\r\n")),
                         ["first line: expected '%s'" % LTAG])
        loose = self.ln([{"word": "CHECKPOINT", "pattern": "CHECKPOINT [^ ]+"}])
        self.assertEqual(self.v("CHECKPOINT x\r", schema_=loose), [])  # a stray CR stays in the line: [^ ] takes it
        ascii_only = self.ln([{"word": "CHECKPOINT", "pattern": "CHECKPOINT [!-~]+"}])
        self.assertEqual(self.v("CHECKPOINT x\r", schema_=ascii_only), [self.err(2, "CHECKPOINT [!-~]+")])
        self.assertEqual(self.v("CHECKPOINT a b", "CHECKPOINT a\u0085b", schema_=loose), [])
        self.assertEqual(self.v("CHECKPOINT bad CHECKPOINT bad"), [self.err(2)])
        self.assertEqual(self.v(*([""] * 1000 + ["CHECKPOINT bad"])), [self.err(1002)])
        self.assertEqual(validate_markdown(self.ls, LTAG + "\nCHECKPOINT bad"), [self.err(2)])  # no final newline

    def test_lines_unicode_class_verdict_same_on_both(self):  # LV13, V2
        loose = self.ln([{"word": "CHECKPOINT", "pattern": "CHECKPOINT [^ ]+ [^ ]+ head=[0-9a-f]{7,40}"}])
        for ch in ("ࡰ", "\U0001fae8", "Ⱟ", "ౝ", " ", "é", "٥"):
            with self.subTest(ch=ch):
                self.assertEqual(self.v("CHECKPOINT %s %s head=abcdef0" % (ch, ch), schema_=loose), [])
        digits = self.ln([{"word": "X", "pattern": "X [0-9]+"}])
        self.assertEqual(self.v("X 123", "X ٥", schema_=digits), [self.err(3, "X [0-9]+", "X")])  # [0-9] is ASCII
        self.assertEqual(self.v("X ࡰ", schema_=digits), [self.err(2, "X [0-9]+", "X")])

    def test_lines_long_line_same_on_both(self):  # LV14, V1
        digits = self.ln([{"word": "CHECKPOINT", "pattern": "CHECKPOINT [0-9]+"}])
        for limit in INT_LIMITS:
            with int_limit(limit):
                for n in (4300, 4301, 1000000):
                    with self.subTest(limit=limit, digits=n):
                        self.assertEqual(self.v("CHECKPOINT " + "9" * n, schema_=digits), [])
                        self.assertEqual(self.v("CHECKPOINT " + "9" * n + "x", schema_=digits),
                                         [self.err(2, "CHECKPOINT [0-9]+")])
                self.assertEqual(self.v("9" * 4301 + " x"), [])  # a numeric first token is just a token

    def test_lines_text_not_str(self):  # LV15
        for text in (None, b"%s\nCHECKPOINT bad" % LTAG.encode(), 5):
            self.assertEqual(validate_markdown(self.ls, text), ["first line: text must be a string"])

    def test_lines_many_lines(self):  # LV17
        got = self.v(*(["CHECKPOINT bad"] * 100000))
        self.assertEqual(len(got), 100000)
        self.assertEqual((got[0], got[-1]), (self.err(2), self.err(100001)))

    def test_lines_keyword_reasons_are_plain_text(self):
        got = self.v("CHECKPOINT ࡰ")
        self.assertEqual(got, [self.err(2)])


class OneOf(Dirs):
    """Task P2.1 part i, decision D-A1: the ``one_of`` union spec (``of: [spec, ...]``, pairwise distinct base types,
    the alternative picked by ``type(value)`` exactly, no trial and backtrack)."""

    OWNS = {"type": "one_of", "of": [{"type": "str"},
                                      {"type": "map", "fields": {"path": {"type": "str"},
                                                                 "from": {"type": "str", "required": False}}}]}

    def field(self, spec=None):
        return self.sch({"v": dict(spec or self.OWNS, required=False)})

    def check(self, s, value):
        return validate(s, {"schema": THING, "v": value}, CFG)

    def test_one_of_is_a_type(self):
        self.assertIn("one_of", schema.TYPES)
        self.assertEqual(len(schema.TYPES), 14)
        self.assertEqual(self.field().fields["v"]["type"], "one_of")

    def test_one_of_valid_alternatives(self):  # the owns item of streams.yml: a string or a window map
        s = self.field()
        for value in ("src/", {"path": "src/"}, {"path": "src/", "from": "merged:a"}):
            with self.subTest(value=repr(value)):
                self.assertEqual(self.check(s, value), [])

    def test_one_of_checks_the_matching_alternative_only(self):
        s = self.field()
        self.assertEqual(self.check(s, ""), ["v: must be a non-empty string"])
        self.assertEqual(self.check(s, {}), ["v.path: required key is missing"])
        self.assertEqual(self.check(s, {"path": "p", "x": 1}), ["v.x: unknown key"])
        self.assertEqual(self.check(s, {"path": 5}), ["v.path: must be a non-empty string"])

    def test_one_of_no_matching_alternative_names_the_allowed_types(self):
        s = self.field()
        class S(str):
            pass
        for value in (5, True, 1.5, ["a"], S("a"), b"x", ()):
            with self.subTest(value=repr(value)):
                self.assertEqual(self.check(s, value), ["v: must be a string or a mapping"])

    def test_one_of_base_types(self):
        alts = [{"type": "int", "min": 1}, {"type": "bool"}, {"type": "list", "items": {"type": "str"}},
                {"type": "enum", "values": ["a", "b"]}]
        s = self.field({"type": "one_of", "of": alts})
        self.assertEqual(self.check(s, 3), [])
        self.assertEqual(self.check(s, 0), ["v: must be at least 1"])
        self.assertEqual(self.check(s, True), [])  # a bool is the bool alternative, never the int one
        self.assertEqual(self.check(s, ["x"]), [])
        self.assertEqual(self.check(s, [5]), ["v.0: must be a non-empty string"])
        self.assertEqual(self.check(s, "a"), [])
        self.assertEqual(self.check(s, "c"), ["v: must be one of a, b"])
        self.assertEqual(self.check(s, {"x": 1}), ["v: must be an integer or true or false or a list or a string"])
        only_int = self.field({"type": "one_of", "of": [{"type": "int"}, {"type": "str"}]})
        self.assertEqual(self.check(only_int, False), ["v: must be an integer or a string"])

    def test_one_of_string_types_share_one_base_type(self):
        for t in ("text", "id", "sha", "glob", "cite", "sha-path"):
            extra = {"id": {"id_kind": "decision"}}.get(t, {})
            with self.subTest(t=t):
                p, m = self.bad(dict(BASE, fields={"schema": {"type": "str"}, "v": {
                    "type": "one_of", "of": [{"type": "str"}, dict(type=t, **extra)]}}))
                self.assertIn("same base type", m)

    def test_one_of_nullable_and_required_belong_to_the_union(self):
        s = self.sch({"v": dict(self.OWNS, nullable=True)})
        self.assertEqual(self.check(s, None), [])
        self.assertEqual(validate(s, {"schema": THING}, CFG), ["v: required key is missing"])
        s = self.field()
        self.assertEqual(self.check(s, None), ["v: must not be null"])

    def test_one_of_inside_a_list(self):  # streams.yml owns: list of (str or map)
        s = self.sch({"v": {"type": "list", "min": 1, "items": self.OWNS}})
        self.assertEqual(self.check(s, ["a/", {"path": "b/"}]), [])
        self.assertEqual(self.check(s, ["a/", 5]), ["v.1: must be a string or a mapping"])

    def test_one_of_load_refusals(self):
        def spec(**kw):
            return dict(BASE, fields={"schema": {"type": "str"}, "v": dict({"type": "one_of"}, **kw)})
        p, m = self.bad(spec())
        self.assertEqual(m, "%s: fields.v.of: required by type one_of" % p)
        for of in ([], "x", {"a": 1}, None, 5):
            with self.subTest(of=repr(of)):
                p, m = self.bad(spec(of=of))
                self.assertEqual(m, "%s: fields.v.of: must be a non-empty list of field specs" % p)
        p, m = self.bad(spec(of=["str"]))
        self.assertEqual(m, "%s: fields.v.of.0: a field spec must be a mapping" % p)
        p, m = self.bad(spec(of=[{"type": "str"}, {"type": "str"}]))
        self.assertEqual(m, "%s: fields.v.of.1: has the same base type (str) as alternative 0; the alternatives need "
                         "distinct base types" % p)
        p, m = self.bad(spec(of=[{"type": "map", "fields": {"a": {"type": "str"}}}, {"type": "any-map"}]))
        self.assertIn("same base type (map)", m)
        p, m = self.bad(spec(of=[{"type": "str"}, {"type": "enum", "values": ["a"]}]))
        self.assertIn("same base type (str)", m)
        p, m = self.bad(spec(of=[{"type": "int"}, {"type": "enum", "values": [1]}]))
        self.assertIn("same base type (int)", m)
        p, m = self.bad(spec(of=[{"type": "one_of", "of": [{"type": "str"}]}]))
        self.assertEqual(m, "%s: fields.v.of.0.type: a one_of alternative cannot itself be one_of" % p)
        p, m = self.bad(spec(of=[{"type": "str"}, {"type": "one_of", "of": [{"type": "int"}]}]))
        self.assertEqual(m, "%s: fields.v.of.1.type: a one_of alternative cannot itself be one_of" % p)
        p, m = self.bad(spec(of=[{"type": "nope"}]))
        self.assertIn("fields.v.of.0.type: must be one of", m)
        p, m = self.bad(spec(of=[{"type": "map"}]))
        self.assertEqual(m, "%s: fields.v.of.0.fields: required by type map" % p)
        for key, val in (("required", False), ("nullable", True), ("required_when", [{"schema": ["x"]}]),
                         ("absent_when", [{"schema": ["x"]}])):
            with self.subTest(key=key):
                p, m = self.bad(spec(of=[{"type": "str", key: val}]))
                self.assertEqual(m, "%s: fields.v.of.0.%s: not used inside one_of" % (p, key))

    def test_of_is_used_by_one_of_only(self):
        p, m = self.bad(dict(BASE, fields={"schema": {"type": "str"}, "v": {"type": "str", "of": [{"type": "str"}]}}))
        self.assertEqual(m, "%s: fields.v.of: not used by type str" % p)
        p, m = self.bad(dict(BASE, fields={"schema": {"type": "str"}, "v": {"type": "one_of", "of": [{"type": "str"}],
                                                                              "min": 1}}))
        self.assertEqual(m, "%s: fields.v.min: not used by type one_of" % p)

    def test_one_of_alternative_with_its_own_items_and_fields_is_checked(self):
        p, m = self.bad(dict(BASE, fields={"schema": {"type": "str"}, "v": {
            "type": "one_of", "of": [{"type": "list", "items": {"type": "str"}}, {"type": "str", "min": 1}]}}))
        self.assertEqual(m, "%s: fields.v.of.1.min: not used by type str" % p)

    def test_one_of_schema_field_cannot_be_the_tag(self):  # a yaml schema declares schema as a required str
        p, m = self.bad(dict(BASE, fields={"schema": {"type": "one_of", "of": [{"type": "str"}]}}))
        self.assertEqual(m, "%s: fields.schema: must be declared as a required, non-nullable str" % p)


class VersionRows(Dirs):
    """Skeleton rows V1-V5 of the P1.1 table that no producer row already covers."""

    def test_digit_limits_same_on_both(self):  # V1
        for limit in INT_LIMITS:
            with int_limit(limit):
                for n in (1000, 1001, 4300, 4301):
                    with self.subTest(limit=limit, digits=n):
                        s = self.sch(files=[{"dir": "decisions", "glob": "9" * n + "/x"}])
                        self.assertEqual(s.files[0]["glob"], "9" * n + "/x")
                hs = self.fm()
                text = "---\nschema: %s\nplan: %s\n---\n"
                self.assertEqual(validate_front_matter(hs, text % (HTAG, "9" * 1000), CFG),
                                 TOO_BIG if limit == 640 else ["plan: must be a non-empty string"])
                self.assertEqual(validate_front_matter(hs, text % (HTAG, "9" * 1001), CFG), TOO_BIG)

    def test_unicode_version_independent(self):  # V2
        hs = self.fm()
        for ch in ("ࡰ", "\U0001fae8", "Ⱟ", "ౝ"):
            with self.subTest(ch=ch):
                self.assertEqual(validate_front_matter(hs, "---\nschema: %s\nplan: a%sb\n---\n" % (HTAG, ch), CFG), [])
                p, m = self.bad(self.ln_data([{"word": "A" + ch, "pattern": "A"}]), name="l.yml")
                self.assertEqual(m, "%s: lines.0.word: must be printable ASCII with no whitespace" % p)
                p, m = self.bad(self.ln_data([{"word": "A", "pattern": "A" + ch}]), name="l.yml")
                self.assertEqual(m, "%s: lines.0.pattern: %s" % (p, ASCII))
                self.assertEqual(self.sch(files=[{"dir": "d", "glob": ch + "*/x"}]).files[0]["glob"], ch + "*/x")
                self.assertEqual(validate_markdown(self.stand_in(), LTAG + "\nCHECKPOINT %s %s head=abcdef0\n" % (ch, ch)), [])

    def test_exception_groups(self):  # V3 (the gate half is in tests/test_gate_schema.py)
        beg = getattr(builtins, "BaseExceptionGroup", None)
        eg = getattr(builtins, "ExceptionGroup", None)
        if beg is None:
            self.skipTest("BaseExceptionGroup is absent on this interpreter (3.9)")
        hs = self.fm()
        for exc in (beg("x", [KeyboardInterrupt()]), eg("x", [ValueError()])):
            with self.subTest(exc=type(exc).__name__):
                with mock.patch.object(yamlsub, "parse", side_effect=exc):
                    with self.assertRaises(beg) as cm:
                        validate_front_matter(hs, "---\nschema: %s\nplan: p\n---\n" % HTAG, CFG)
                self.assertIs(cm.exception, exc)


if __name__ == "__main__":
    unittest.main()
if __name__ == "__main__":
    unittest.main()
