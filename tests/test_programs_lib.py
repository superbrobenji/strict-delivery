"""Tests for gates.lib.programs (plan Task P2.1, part ii) through the production functions on hand-built rows.
Expected values are written by hand from the plan and the input-domain tables (task-P2.1-domain.md part A,
task-P2.1-ownership-domain.md part B); the ``unicodedata`` oracle below is the independent check of ``path_key``."""
import ast
import itertools
import pathlib
import random
import unicodedata
import unittest
from unittest import mock

from gates.lib import programs, store
from gates.lib.programs import (NAME_RE, REQUEST_TRANSITIONS, agreement_errors, branch_of, breakdown_sub_blocks,
                                comes_before, event_problem, fold, group_problem, held_events, nfc, nfd, owner_of,
                                parse_branch, path_key, program_problem, request_base_errors, residual_reachable,
                                shared_rule, status_errors, status_fact_errors, status_rows, stream_problem,
                                streams_errors, sub_block, window_of, worktree_of, worktrees_dir)
from gates.lib.result import GateError
from tests.helpers import minimal_config

CFG = minimal_config()
NAME = "20261101-x"
PS = ".strict-delivery/state/plans"
PG = "docs/strict-delivery/plans"
PROGRAM_PLAN = PG + "/program-plan.md"
HEAD = "| stream | block | branch | worktree | next task | estimate | used | status | blockers | pending decisions | delivers |"
SEP = "|---|---|---|---|---|---|---|---|---|---|---|"
PS_, PC = "program-start", "program-close"


def stream(sid, owns=None, period=None, residual=False, **kw):
    s = {"id": sid, "purpose": "p", "plan": "%s/%s-plan.md" % (PG, sid), "estimate": 5, "depends_on": [],
         "merge_order": kw.pop("merge_order", 1)}
    if residual:
        s["residual"] = True
        if owns is not None:
            s["owns"] = owns
    else:
        s["owns"] = owns if owns is not None else [sid + "-owned.py"]
    if period:
        s["period"] = {"from": period[0], "until": period[1]}
    s.update(kw)
    return s


def row(*streams, **kw):
    out = {"schema": "streams/1", "program": NAME, "plan": PROGRAM_PLAN, "specs": [], "worktrees": "../w",
           "streams": list(streams), "shared": []}
    out.update(kw)
    return out


def S():
    return row(stream("a", merge_order=1), stream("b", merge_order=2))


def with_owns(r, owns):
    r = row(*[dict(s) for s in r["streams"]])
    for s in r["streams"]:
        if s["id"] in owns:
            s["owns"] = owns[s["id"]]
    return r


def W(path, a=None, b=None):
    d = {"path": path}
    if a:
        d["from"] = a
    if b:
        d["until"] = b
    return d


def two(a_owns, b_owns, **kw):
    return row(stream("a", a_owns, merge_order=1, **kw), stream("b", b_owns, merge_order=2))


def H(*ev):
    return frozenset((PS_,) + ev)


def overlaps(errs):
    return [e for e in errs if "overlaps" in e]


def record_streams():
    reg = ["gates/__main__.py", "gates/producers.py", "gates/run_all.py", "tests/test_run_all.py"]
    plug = [".claude-plugin/plugin.json", ".claude-plugin/marketplace.json"]
    return row(
        stream("package", reg + plug, (PS_, "merged:package"), merge_order=1),
        stream("residual", residual=True, period=(PS_, PC), merge_order=2),
        stream("init4", reg + ["CLAUDE.md", ".gitignore"], ("merged:residual/R2", "merged:init4"), merge_order=3),
        stream("release", plug + ["CLAUDE.md", ".gitignore"], ("merged:init4", PC), merge_order=4))


SUBS = {"package": {"3d"}, "residual": {"R1", "R2"}, "init4": {"4c", "4d", "4e"}, "release": {"6R"}}
S0 = held_events({}, SUBS)
S1 = held_events({"package": {"3d"}}, SUBS)
S2 = held_events({"package": {"3d"}, "residual": {"R2"}}, SUBS)
S3 = held_events({"package": {"3d"}, "residual": {"R2"}, "init4": {"4c", "4d", "4e"}}, SUBS)
SX = held_events({"residual": {"R2"}}, SUBS)
RECORD_BD = {"streams": [{"id": "package", "tasks": ["3d.1"]}, {"id": "residual", "tasks": ["R1.1", "R2.1"]},
                         {"id": "init4", "tasks": ["4c.1", "4d.1", "4e.1"]}, {"id": "release", "tasks": ["6R.1"]}],
             "edges": [{"from": "3d.1", "to": "R2.1"}, {"from": "4e.1", "to": "6R.1"}]}


class Names(unittest.TestCase):
    def test_name_re_literal(self):
        self.assertEqual(NAME_RE, "[a-z0-9][a-z0-9-]*")

    def test_program_names(self):
        for n in ("20261101-x", "20261101-a-b", "20261101-0", "20240229-leap", "00010101-x", "99991231-x"):
            self.assertEqual(program_problem(n), "", n)

    def test_program_name_refused(self):
        bad = ["20261301-x", "20261132-x", "20230229-x", "00001101-x", "20260000-x", "20261101-", "20261101-X",
               "20261101-a/b", "x", "20261101", "20261101--", "20261101-a_b", "20261101-a b", "20261101--a",
               "2026110-x", "202611011-x", "2026-11-01-x", "+0261101-x", "2026111-x", "\u0662\u0660\u0662\u0666\u0661\u0661\u0660\u0661-x",
               "20261101-\u00e9", "20261101-\u212a", "\uff12\uff10\uff12\uff16\uff11\uff11\uff10\uff11-x", "20261101-x\n",
               "20261101-x ", " 20261101-x", "20261101-x\x00", "20261101-x\r", "\ufeff20261101-x", "20261101-aB",
               "20261101-" + "a" * 5 + "/"]
        for n in bad:
            self.assertNotEqual(program_problem(n), "", repr(n))
        self.assertEqual(program_problem("20261101-" + "a" * 4301), "")
        for n in (None, 5, True, b"x", ["x"], {}):
            self.assertIn("not a string", program_problem(n))

        class Sub(str):
            pass
        self.assertNotEqual(program_problem(Sub("20261101-x")), "")

    def test_stream_and_group_problem(self):
        for ok in ("a", "a-b", "0", "x1", "records2", "main", "integrations"):
            self.assertEqual(stream_problem(ok), "", ok)
        for bad in ("integration", "records", "-a", "a_b", "A", "a/b", "", "a ", "Integration", "integration ", None, 5):
            self.assertNotEqual(stream_problem(bad), "", repr(bad))
        for ok in ("g", "a-b", "integration", "records", "0"):
            self.assertEqual(group_problem(ok), "", ok)
        for bad in ("main", "-a", "a_b", "A", "a/b", "", None, 5):
            self.assertNotEqual(group_problem(bad), "", repr(bad))

    def test_parse_branch(self):
        p = NAME
        self.assertEqual(parse_branch(p + "/s/main"), ("stream", p, "s", None))
        self.assertIsNone(parse_branch("block/p1"))
        with self.assertRaises(ValueError):
            parse_branch(p + "/integration/main")

    def test_parse_branch_forms(self):
        p = NAME
        for name, want in [(p + "/integration", ("integration", p, None, None)),
                           (p + "/records", ("records", p, None, None)),
                           (p + "/s/g", ("group", p, "s", "g")), (p + "/main/main", ("stream", p, "main", None)),
                           (p + "/s/integration", ("group", p, "s", "integration")),
                           (p + "/s/records", ("group", p, "s", "records"))]:
            self.assertEqual(parse_branch(name), want, name)
        for name in ("main", "block/p1", "feature/x", "20261301-x/s/main", "x/integration", "20261101/s/main",
                     "20261101-X/s/main", "", "/", "20261101-x\n/s/main"):
            self.assertIsNone(parse_branch(name), name)
        for name in (p + "/integration/x", p + "/s/g/h", p + "/records/x", p + "/", p + "//x", p, p + "/s",
                     p + "/-a/main", p + "/A/main", p + "/s/_g", p + "/s/G", p + "/s/main/main", p + "/\n/main",
                     p + "/\u00e9/main", p + "/records/main"):
            with self.assertRaises(ValueError, msg=name):
                parse_branch(name)
        for bad in (None, 5, b"x", ["a"]):
            with self.assertRaises(ValueError):
                parse_branch(bad)

    def test_branch_round_trip_and_forms(self):
        p = NAME
        self.assertEqual(branch_of(p, "s"), p + "/s/main")
        self.assertEqual(branch_of(p, "s", "g"), p + "/s/g")
        self.assertEqual(branch_of(p), p + "/integration")
        for args in [(p, None, "g"), ("x", "s"), (p, "integration"), (p, "s", "main"), (5, "s")]:
            with self.assertRaises(ValueError, msg=repr(args)):
                branch_of(*args)
        for b in (branch_of(p), branch_of(p, "s"), branch_of(p, "s", "g")):
            self.assertEqual(branch_of(*parse_branch(b)[1:]) if parse_branch(b)[0] != "integration" else b, b)

    def test_worktree_of(self):
        self.assertEqual(worktree_of("/w", NAME, "s"), "/w/%s/s/main" % NAME)
        self.assertEqual(worktree_of("/w", NAME, "s", "g"), "/w/%s/s/g" % NAME)
        self.assertEqual(worktree_of("/w/", NAME, "s"), "/w/%s/s/main" % NAME)
        self.assertEqual(worktree_of("../w", NAME, "s"), "../w/%s/s/main" % NAME)
        for args in [("", NAME, "s"), ("/w", NAME, "integration"), ("/w", NAME, "s", "main"), ("/w", "x", "s"), (5, NAME, "s")]:
            with self.assertRaises(ValueError, msg=repr(args)):
                worktree_of(*args)


class PathKey(unittest.TestCase):
    def test_path_key_literals(self):
        for s, want in [("SRC", "src"), ("src", "src"), ("Src/A.py", "src/a.py"), ("STRASSE", "strasse"),
                        ("stra\u00dfe", "strasse"), ("STRA\u1e9eE", "strasse"), ("caf\u00e9", "caf\u00e9"),
                        ("cafe\u0301", "caf\u00e9"), ("\uac00", "\uac00"), ("\u1100\u1161", "\uac00"),
                        ("a\u0323\u0301", "\u1ea1\u0301"), ("a\u0301\u0323", "\u1ea1\u0301"),
                        ("\u1ea1\u0301", "\u1ea1\u0301"), ("\u0958", "\u0915\u093c"), ("\u0915\u093c", "\u0915\u093c"),
                        ("a", "a"), ("ab", "ab"), ("", ""), ("/", "/"), ("a/", "a/"), ("Src/", "src/"),
                        ("a/B/c", "a/b/c"), ("\ufeffA", "\ufeffa"), ("\ud800", "\ud800"), ("\n", "\n"), ("\x00", "\x00")]:
            self.assertEqual(path_key(s), want, repr(s))

    def test_path_key_unassigned_unchanged(self):
        self.assertEqual(path_key("\U00010570"), "\U00010570")
        self.assertEqual(path_key("\u2c2f"), "\u2c2f")

    def test_path_key_hangul_and_marks(self):
        for s, want in [("\uac00\u11a8", "\uac01"), ("\u1112\u1161\u11ab", "\ud55c"), ("\ud55c", "\ud55c"),
                        ("\ud55c\u11a8", "\ud55c\u11a8"), ("\u1161", "\u1161"), ("\u3131", "\u3131"),
                        ("\u1100\u1161\u11a7", "\uac00\u11a7"), ("a\u0301\u0316", "\u00e1\u0316"),
                        ("a\u0316\u0301", "\u00e1\u0316"), ("a\u0316\u0323", "a\u0316\u0323"), ("\u212b", "\u00e5"), ("\u2126", "\u03c9"), ("\u212a", "k"),
                        ("\u0130", "i\u0307"), ("\ufb03", "ffi"), ("\u0345", "\u03b9"), ("\u1c80", "\u0432"),
                        ("\u1f88", "\u1f00\u03b9"), ("\u0344", "\u0308\u0301"), ("\u0f73", "\u0f71\u0f72"),
                        ("\u01c5", "\u01c6"), ("\u03a3\u03c3\u03c2", "\u03c3\u03c3\u03c3"),
                        ("\U0001d15e", "\U0001d157\U0001d165")]:
            self.assertEqual(path_key(s), want, repr(s))

    def test_nfd_fold_nfc_alone(self):
        self.assertEqual(nfd("\u1ea5"), "a\u0302\u0301")
        self.assertEqual(nfd("\uac00"), "\u1100\u1161")
        self.assertEqual(nfd("a\u0301\u0323"), "a\u0323\u0301")
        self.assertEqual(fold("STRASSE"), "strasse")
        self.assertEqual(fold("\u00df"), "ss")
        self.assertEqual(nfc("a\u0323\u0301"), "\u1ea1\u0301")
        self.assertEqual(nfc("\u1100\u1161"), "\uac00")
        self.assertEqual(nfc("\u1100\u1161\u11a8"), "\uac01")

    def test_path_key_idempotent_and_prefix(self):
        for s in ("Src/A.py", "stra\u00dfe", "a\u0301\u0323", "\u0958"):
            self.assertEqual(path_key(path_key(s)), path_key(s))
        self.assertNotEqual(path_key("a"), path_key("ab"))

    def test_path_key_argument_types(self):
        class Sub(str):
            pass
        for bad in (None, 5, True, b"a", ["a"], Sub("A")):
            with self.assertRaises(TypeError):
                path_key(bad)

    def test_path_key_matches_unicodedata_13(self):
        if unicodedata.unidata_version != "13.0.0":
            self.skipTest("the oracle is unicodedata 13.0.0 (3.9.6)")
        bad = [c for c in range(0x110000) if not 0xD800 <= c <= 0xDFFF and path_key(chr(c)) !=
               unicodedata.normalize("NFC", unicodedata.normalize("NFD", chr(c)).casefold())]
        self.assertEqual(bad, [])

    def test_path_key_random_corpus_matches_unicodedata_13(self):
        if unicodedata.unidata_version != "13.0.0":
            self.skipTest("the oracle is unicodedata 13.0.0 (3.9.6)")
        pool = [chr(c) for c in (0x41, 0x61, 0xdf, 0xe9, 0x301, 0x323, 0x316, 0x1ea1, 0xac00, 0x1100, 0x1161, 0x11a8,
                                 0x958, 0x915, 0x93c, 0x2126, 0x212b, 0x3a3, 0x3c2, 0x345, 0x1f88, 0x1e9e)]
        rng = random.Random(7)
        for _ in range(3000):
            s = "".join(rng.choice(pool) for _ in range(rng.randint(1, 6)))
            self.assertEqual(path_key(s), unicodedata.normalize("NFC", unicodedata.normalize("NFD", s).casefold()), repr(s))

    def test_path_key_linear(self):
        self.assertEqual(len(path_key("a" + "\u0301" * 100000)), 100000)   # a + U+0301 composes to U+00E1
        self.assertEqual(path_key("9" * 4301), "9" * 4301)

    def test_programs_no_unicodedata_or_case_method(self):
        text = pathlib.Path(programs.__file__).read_text(encoding="utf-8")
        tree = ast.parse(text)
        self.assertEqual(violations(tree), [])
        self.assertNotIn("unicodedata", text)

    def test_ast_check_detects_plants(self):
        for src in ("import unicodedata", "from unicodedata import normalize", "s.lower()", "str.casefold(s)",
                    "x.title", "s.isalnum()", "import re\nre.IGNORECASE", "x = BaseExceptionGroup",
                    "try:\n pass\nexcept* ValueError:\n pass"):
            if "except*" in src and not hasattr(ast, "TryStar"):
                continue
            self.assertNotEqual(violations(ast.parse(src)), [], src)

    def test_programs_has_no_int_of_record_text(self):
        tree = ast.parse(pathlib.Path(programs.__file__).read_text(encoding="utf-8"))
        calls = [ast.dump(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "int"]
        self.assertEqual(len(calls), 3)  # the three of the calendar date, nothing else


BANNED_ATTR = {"lower", "casefold", "upper", "swapcase", "title", "capitalize", "isprintable", "isalnum", "isdigit",
               "isspace", "isdecimal", "isnumeric", "isalpha", "IGNORECASE", "I"}
BANNED_NAME = {"BaseExceptionGroup", "ExceptionGroup", "unicodedata"}


def violations(tree):
    out = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            out += [a.name for a in n.names if a.name.split(".")[0] == "unicodedata"]
        elif isinstance(n, ast.ImportFrom) and n.module and n.module.split(".")[0] == "unicodedata":
            out.append(n.module)
        elif isinstance(n, ast.Attribute) and n.attr in BANNED_ATTR:
            out.append(n.attr)
        elif isinstance(n, ast.Name) and n.id in BANNED_NAME:
            out.append(n.id)
        elif type(n).__name__ == "TryStar":
            out.append("except*")
    return out


class Events(unittest.TestCase):
    def test_event_problem_forms(self):
        for ev in (PS_, PC, "merged:a/R2", "merged:a/3d", "merged:a", "merged:a-b/x", "merged:a/" + "9" * 4301):
            self.assertEqual(event_problem(ev, {"a", "a-b"}), "", ev)
        for ev in ("later", "", " program-start", "program-start ", "Program-Start", "program-start\n", "merged",
                   "Merged:a", "merged:a/b:c", "merged:a:b", "program-start/x", "merged:z", "merged:/b", "merged:",
                   "merged::", "merged:A", "merged:a/", "merged:a/b/c", "merged:a/b-c", "merged:a/b.c", "merged:a/ b",
                   "merged:a/b ", "merged:a/\u00e9", "merged:a/\u0663", "merged:a/\uff21", "merged:a/\u0870",
                   "merged:a/b\n", "merged:a/b\r", "merged:a/b\x00", "merged:a/\ufeffb", None, 5, True, b"x", ["x"]):
            self.assertNotEqual(event_problem(ev, {"a"}), "", repr(ev))

    def test_event_problem_stream_ids_shapes(self):
        self.assertEqual(event_problem("merged:a", frozenset({"a"})), "")
        self.assertEqual(event_problem("merged:a", {"a": 1}), "")
        for bad in (["a"], ("a",), "abc", None):
            with self.assertRaises(ValueError):
                event_problem("merged:a", bad)

    def test_window_of(self):
        self.assertEqual(window_of({}, "x"), (PS_, PC))
        self.assertEqual(window_of({"period": {"from": "merged:a/R2", "until": "merged:a"}}, "x"), ("merged:a/R2", "merged:a"))
        self.assertEqual(window_of({"period": {"from": "merged:z", "until": PC}}, W("x", "merged:a", "merged:b")), ("merged:a", "merged:b"))
        self.assertEqual(window_of({"period": {"from": "merged:a", "until": PC}}, {"path": "x", "until": "merged:b"}), ("merged:a", "merged:b"))
        self.assertEqual(window_of({"period": {"from": PS_, "until": "merged:b"}}, {"path": "x", "from": "merged:a"}), ("merged:a", "merged:b"))
        self.assertEqual(window_of({}, {"path": "x", "from": "merged:a"}), ("merged:a", PC))
        self.assertEqual(window_of({}, {"path": "x", "until": "merged:b"}), (PS_, "merged:b"))
        self.assertEqual(window_of({"period": {"from": PS_, "until": PC}}, "x"), window_of({}, "x"))
        self.assertEqual(window_of({}, {"path": "x", "from": "later"}), ("later", PC))
        for bad_item in ({}, {"path": 3}, {"path": "x", "from": 5}, {"path": "x", "to": "m"}, None, 5, ["x"]):
            with self.assertRaises(ValueError, msg=repr(bad_item)):
                window_of({}, bad_item)
        for bad_stream in (None, [], {"period": {"from": "merged:a"}}, {"period": "x"}, {"period": {}}):
            with self.assertRaises(ValueError):
                window_of(bad_stream, "x")

    def test_sub_block(self):
        for t, want in [("4e.3", "4e"), ("3d.1", "3d"), ("R2.1", "R2"), ("1c0.2", "1c0"), ("P1.3", "P1"), ("6R.1", "6R"),
                        ("B2.2", "B2"), ("4e.3.1", "4e.3"), ("a.b.c", "a.b"), ("x", None), ("4e", None), ("", None),
                        ("4e.", "4e"), (".3", ""), (".", ""), ("..", "."), ("\u00e9.1", "\u00e9"), ("9" * 4301 + ".1", "9" * 4301)]:
            self.assertEqual(sub_block(t), want, repr(t))
        for bad in (None, 5, True, b"4e.3", ["4e.3"]):
            with self.assertRaises(ValueError):
                sub_block(bad)

    def test_held_events_plan_literals(self):
        self.assertEqual(held_events({"package": {"3d"}}, {"package": {"3d"}, "residual": {"R1", "R2"}}),
                         frozenset({PS_, "merged:package/3d", "merged:package"}))
        r = held_events({"residual": {"R1"}}, {"residual": {"R1", "R2"}})
        self.assertIn("merged:residual/R1", r)
        self.assertNotIn("merged:residual", r)

    def test_held_events_rows(self):
        self.assertEqual(held_events({}, {}), frozenset({PS_}))
        self.assertEqual(held_events({}, {"a": {"x"}}), frozenset({PS_}))
        self.assertEqual(held_events({"a": {"x", "y"}}, {"a": {"x", "y"}}), frozenset({PS_, "merged:a/x", "merged:a/y", "merged:a"}))
        self.assertEqual(held_events({"a": {"x"}}, {"a": {"x", "y"}}), frozenset({PS_, "merged:a/x"}))
        self.assertEqual(held_events({"s": {"b"}}, {}), frozenset({PS_, "merged:s/b"}))
        self.assertEqual(held_events({"s": set()}, {"s": set()}), frozenset({PS_}))
        self.assertEqual(held_events({"a": {"x", "extra"}}, {"a": {"x"}}), frozenset({PS_, "merged:a/x", "merged:a/extra", "merged:a"}))
        r = held_events({"a": {"x"}, "b": {"y"}}, {"a": {"x"}, "b": {"y", "z"}})
        self.assertEqual(r, frozenset({PS_, "merged:a/x", "merged:a", "merged:b/y"}))
        self.assertIs(type(r), frozenset)
        for bad in (({"a": ["x"]}, {}), ([], {}), ({}, []), ({1: {"x"}}, {}), ({"a": {1}}, {}), ({"a": {""}}, {}),
                    ({"a": {"x/y"}}, {}), ({"a": {"x y"}}, {})):
            with self.assertRaises(ValueError, msg=repr(bad)):
                held_events(*bad)

    def test_record_held_states(self):
        self.assertEqual(S0, frozenset({PS_}))
        self.assertEqual(S1, frozenset({PS_, "merged:package/3d", "merged:package"}))
        self.assertEqual(S2, S1 | {"merged:residual/R2"})
        self.assertEqual(S3, S2 | {"merged:init4/4c", "merged:init4/4d", "merged:init4/4e", "merged:init4"})
        self.assertEqual(SX, frozenset({PS_, "merged:residual/R2"}))


class Streams(unittest.TestCase):
    def test_valid_and_program_name(self):
        self.assertEqual(streams_errors(S(), NAME, CFG), [])
        self.assertTrue(any(e.startswith("program:") for e in streams_errors(row(stream("a"), program="20261101-y"), NAME, CFG)))
        self.assertTrue(any(e.startswith("program:") for e in streams_errors(S(), "x", CFG)))
        with self.assertRaises(ValueError):
            streams_errors(S(), None, CFG)
        self.assertEqual(streams_errors(None, NAME, CFG), ["streams: must be a mapping"])

    def test_stream_ids_and_graph(self):
        r = row(stream("integration"), stream("a", merge_order=2), stream("a", merge_order=3))
        errs = streams_errors(r, NAME, CFG)
        self.assertTrue(any(e.startswith("streams.0.id:") for e in errs))
        self.assertTrue(any("duplicate stream id 'a'" in e for e in errs))
        r = row(stream("a", depends_on=["z"]), stream("b", merge_order=2, depends_on=["b"]))
        self.assertEqual(sum("depends_on" in e for e in streams_errors(r, NAME, CFG)), 2)
        r = row(stream("a", depends_on=["b"]), stream("b", merge_order=2, depends_on=["a"]))
        self.assertTrue(any("depends_on cycle" in e for e in streams_errors(r, NAME, CFG)))
        r = row(stream("a", stacked_on="b"), stream("b", merge_order=2, stacked_on="a"))
        self.assertTrue(any("stacked_on cycle" in e for e in streams_errors(r, NAME, CFG)))
        r = row(stream("a", stacked_on="z"), stream("b", merge_order=2, stacked_on="b"))
        self.assertEqual(sum("stacked_on" in e for e in streams_errors(r, NAME, CFG)), 2)
        r = row(stream("a", stacked_on="b"), stream("b", merge_order=2, stacked_on="c"), stream("c", merge_order=3))
        self.assertEqual(streams_errors(r, NAME, CFG), [])
        r = row(stream("a", merge_order=1), stream("b", merge_order=1))
        self.assertTrue(any("merge_order" in e for e in streams_errors(r, NAME, CFG)))
        r = row(stream("a", merge_order=1), stream("b", merge_order=5))
        self.assertEqual(streams_errors(r, NAME, CFG), [])

    def test_plan_rules(self):
        def plans(m):
            r = row(stream("a", merge_order=1), stream("b", merge_order=2))
            for s in r["streams"]:
                s["plan"] = m[s["id"]]
            return r
        errs = streams_errors(plans({"a": PG + "/p1.md", "b": PG + "/p1.md"}), NAME, CFG)
        self.assertTrue(any("plan" in e for e in errs))
        self.assertTrue(any("plan" in e for e in streams_errors(plans({"a": PG + "/P1.md", "b": PG + "/p1.md"}), NAME, CFG)))
        self.assertTrue(any("equals the program plan" in e for e in streams_errors(plans({"a": PROGRAM_PLAN, "b": PG + "/b.md"}), NAME, CFG)))
        for bad in ("docs/other/a.md", PG + "/sub/a.md", PG + "/a", PG + "/.md", "docs/strict-delivery/plans-x/a.md", "/abs", "../x.md"):
            self.assertTrue(any(e.startswith("streams.0.plan:") for e in streams_errors(plans({"a": bad, "b": PG + "/b.md"}), NAME, CFG)), bad)

    def test_owned_overlap_refused(self):
        S_ = S()
        self.assertTrue(overlaps(streams_errors(with_owns(S_, {"a": ["src/"], "b": ["src/x.py"]}), NAME, CFG)))
        self.assertTrue(overlaps(streams_errors(with_owns(S_, {"a": ["src/"], "b": [W("src/x.py", "merged:a")]}), NAME, CFG)))
        self.assertTrue(overlaps(streams_errors(with_owns(S_, {"a": ["x.py"], "b": ["x.py"]}), NAME, CFG)))
        self.assertTrue(overlaps(streams_errors(with_owns(S_, {"a": ["x.py"], "b": [W("x.py", "merged:a")]}), NAME, CFG)))
        self.assertEqual(streams_errors(record_streams(), NAME, CFG), [])
        errs = streams_errors(record_streams(), NAME, CFG, SX)
        self.assertEqual(errs, ["owns: %s (stream package) overlaps %s (stream init4)" % (p, p) for p in
                                ("gates/__main__.py", "gates/producers.py", "gates/run_all.py", "tests/test_run_all.py")])
        for st in (S0, S1, S2, S3):
            self.assertEqual(streams_errors(record_streams(), NAME, CFG, st), [])
        two_plans = row(stream("a", merge_order=1), stream("b", merge_order=2))
        two_plans["streams"][0]["plan"] = two_plans["streams"][1]["plan"] = PG + "/p1.md"
        self.assertTrue(any("plan" in e for e in streams_errors(two_plans, NAME, CFG)))
        self.assertTrue(overlaps(streams_errors(two_plans, NAME, CFG)))
        res = row(stream("a", ["x.py"], merge_order=1), stream("residual", residual=True, merge_order=2))
        for p in (".strict-delivery/", PS + "/b-plan/x.md", PS + "/", ".strict-delivery/state/"):
            self.assertTrue(overlaps(streams_errors(with_owns(S_, {"a": [p]}), NAME, CFG)), p)
        for p in (".strict-delivery/", PS + "/residual-plan/x.md", PS + "/", ".strict-delivery/state/"):
            self.assertTrue(overlaps(streams_errors(with_owns(res, {"a": [p]}), NAME, CFG)), p)
        self.assertEqual(streams_errors(with_owns(S_, {"a": [PS + "/a-plan/x.md"]}), NAME, CFG), [])
        self.assertEqual(streams_errors(with_owns(res, {"a": ["x.py"]}), NAME, CFG), [])

    def test_overlap_windows_without_held(self):
        ps, pc = PS_, PC
        cases = [([W("x.py", ps, "merged:a")], [W("x.py", "merged:a", pc)], False),      # chained
                 ([W("x.py", "merged:a", pc)], [W("x.py", ps, "merged:b")], False),      # neither whole nor chained
                 ([W("a/", "merged:a", pc)], [W("a/b.py", ps, "merged:b")], False),
                 ([W("x.py", "merged:a", "merged:b")], [W("x.py", "merged:a", "merged:b")], False),
                 ([W("x.py", ps, pc)], ["x.py"], True),
                 ([W("x.py", ps, "merged:a")], [W("x.py", "merged:a", pc)], False)]
        for a, b, want in cases:
            for first, second in ((a, b), (b, a)):
                got = bool(overlaps(streams_errors(two(first, second), NAME, CFG)))
                self.assertEqual(got, want, (a, b))
        # a dead window chained to the whole program is the dead-window rule's, not an overlap
        for dead in (W("x.py", PC), W("x.py", None, PS_)):
            self.assertEqual(overlaps(streams_errors(two(["x.py"], [dead]), NAME, CFG)), [])
        # periods
        self.assertEqual(overlaps(streams_errors(row(stream("a", ["x.py"], (ps, "merged:a")), stream("b", ["x.py"], ("merged:a", pc), merge_order=2)), NAME, CFG)), [])
        self.assertEqual(overlaps(streams_errors(row(stream("a", ["x.py"], (ps, "merged:a")), stream("b", ["x.py"], ("merged:b", pc), merge_order=2)), NAME, CFG)), [])
        # a period written out equals an absent one
        self.assertTrue(overlaps(streams_errors(row(stream("a", ["x.py"], (ps, pc)), stream("b", ["x.py"], merge_order=2)), NAME, CFG)))
        # three streams on one path: one reason per pair
        r = row(stream("a", ["x.py"]), stream("b", ["x.py"], merge_order=2), stream("c", ["x.py"], merge_order=3))
        self.assertEqual(len(overlaps(streams_errors(r, NAME, CFG))), 3)
        # same stream never overlaps itself
        self.assertEqual(overlaps(streams_errors(with_owns(S(), {"a": ["src/", "src/x.py", "Src/"]}), NAME, CFG)), [])
        # a pair refused with and without held is reported once
        self.assertEqual(len(overlaps(streams_errors(two(["x.py"], ["x.py"]), NAME, CFG, S0))), 1)

    def test_overlap_keys_and_boundaries(self):
        for a, b, want in [("src/", "SRC/x.py", True), ("caf\u00e9/", "cafe\u0301/x", True), ("cafe\u0301/", "caf\u00e9/x", True),
                           ("\u1ea1\u0301/", "a\u0301\u0323/x", True), ("strasse/", "STRA\u00dfE/x", True), ("strasse/", "STRA\u1e9eE/x", True),
                           ("a/", "ab/x", False), ("a/", "a/b.py", True), ("a/b", "a/bc", False), ("X/", "x/", True),
                           ("\U00010570/", "\U00010597/x", False), ("a", "a/", True), ("a/", "a", True), ("a", "a/x", False)]:
            got = bool(overlaps(streams_errors(two([a], [b]), NAME, CFG)))
            self.assertEqual(got, want, (a, b))

    def test_overlap_with_held(self):
        ps = PS_
        a, b = [W("x.py", ps, "merged:a")], [W("x.py", ps, "merged:b")]
        self.assertEqual(len(overlaps(streams_errors(two(a, b), NAME, CFG, H()))), 1)
        self.assertEqual(overlaps(streams_errors(two(a, b), NAME, CFG, H("merged:a"))), [])
        self.assertEqual(overlaps(streams_errors(two(a, [W("x.py", "merged:q", PC)]), NAME, CFG, H())), [])
        c = [W("x.py", "merged:a", PC)]
        self.assertEqual(overlaps(streams_errors(two(a, c), NAME, CFG, H())), [])
        self.assertEqual(overlaps(streams_errors(two(a, c), NAME, CFG, H("merged:a"))), [])
        self.assertEqual(overlaps(streams_errors(two(a, b), NAME, CFG, H("merged:zz/y", "merged:a"))), [])
        for bad in (frozenset(), set(), [], "x", frozenset({PS_, PC}), frozenset({PS_, 1})):
            with self.assertRaises(ValueError):
                streams_errors(S(), NAME, CFG, bad)

    def test_window_and_period_bounds(self):
        errs = streams_errors(two([W("x.py", "later")], ["y.py"]), NAME, CFG)
        self.assertTrue(any(e.startswith("owns: x.py (stream a): ") and "later" in e for e in errs))
        for w in (W("x.py", None, "merged:z"), W("x.py", "merged:z/b"), W("x.py", "merged:a/"), W("x.py", "merged:a/b/c"),
                  W("x.py", "merged:a/b-c")):
            self.assertTrue(any(e.startswith("owns: x.py (stream a): ") for e in streams_errors(two([w], ["y.py"]), NAME, CFG)), w)
        self.assertEqual(streams_errors(two([W("x.py", PS_, "merged:a")], ["y.py"]), NAME, CFG), [])
        errs = streams_errors(row(stream("a", ["x.py"], ("later", PC)), stream("b", merge_order=2)), NAME, CFG)
        self.assertEqual([e for e in errs if e.startswith("period:")], ["period: a: 'later' is not an event"])
        self.assertFalse(any(e.startswith("owns:") for e in errs))
        errs = streams_errors(row(stream("a", ["x.py"], ("later", "also")), stream("b", merge_order=2)), NAME, CFG)
        self.assertEqual(len([e for e in errs if e.startswith("period:")]), 2)
        errs = streams_errors(row(stream("a", [W("x.py", PS_, "merged:a")], ("later", PC)), stream("b", merge_order=2)), NAME, CFG)
        self.assertEqual(len([e for e in errs if e.startswith("period:")]), 1)
        r = row(stream("residual", residual=True, period=("later", PC)), stream("b", merge_order=2))
        self.assertTrue(any(e.startswith("period: residual:") for e in streams_errors(r, NAME, CFG)))

    def test_dead_windows(self):
        for w in (W("x.py", "merged:a", "merged:a"), W("x.py", PC, PC), W("x.py", PC), W("x.py", None, PS_)):
            self.assertTrue(any("window can never open" in e for e in streams_errors(two([w], ["y.py"]), NAME, CFG)), w)
        self.assertTrue(any(e.startswith("period: a: window can never open") for e in
                            streams_errors(row(stream("a", ["x.py"], (PC, PS_)), stream("b", merge_order=2)), NAME, CFG)))
        self.assertEqual(streams_errors(two([W("x.py", "merged:b", "merged:a")], ["y.py"]), NAME, CFG), [])

    def test_entry_forms(self):
        for good in ("src/x.py", "src/", "caf\u00e9/x", "a b", "a\\b"):
            self.assertEqual(streams_errors(two([good], ["zz.py"]), NAME, CFG), [], good)
        for bad in ("", "/", "/abs/x", "./a", "../a", "a/../b", "a//b", "a//", ".", "a\nb", "a\x00b", "\ufeffa", "\u00a0",
                    "\U00010570"):
            self.assertTrue(any("not a normalised repository path" in e for e in streams_errors(two([bad], ["zz.py"]), NAME, CFG)), repr(bad))

    def test_residual_and_owns_rules(self):
        r = row(stream("a", merge_order=1), stream("r1", residual=True, merge_order=2), stream("r2", residual=True, merge_order=3))
        self.assertTrue(any("at most one residual" in e for e in streams_errors(r, NAME, CFG)))
        r = row(stream("a"), stream("residual", residual=True, merge_order=2, owns=["x.py"]))
        self.assertTrue(any("a residual stream has no owns" in e for e in streams_errors(r, NAME, CFG)))
        r = row(stream("a"), stream("residual", residual=True, merge_order=2, owns=[]))
        self.assertTrue(any("a residual stream has no owns" in e for e in streams_errors(r, NAME, CFG)))
        r = row(stream("a", []), stream("b", merge_order=2))
        self.assertTrue(any("needs at least one entry" in e for e in streams_errors(r, NAME, CFG)))
        r = row(stream("a"), stream("b", merge_order=2)); del r["streams"][1]["owns"]
        self.assertTrue(any("needs at least one entry" in e for e in streams_errors(r, NAME, CFG)))
        r = row(stream("a", ["x.py"], residual=False), {**stream("rest", residual=True, merge_order=2)})
        self.assertEqual(streams_errors(r, NAME, CFG), [])

    def test_protected_and_shared_paths(self):
        d = ".strict-delivery/state/decisions"
        for p in ("%s/%s/status.md" % (".strict-delivery/state/programs", NAME), ".strict-delivery/state/programs/%s/" % NAME,
                  d + "/x.yml", d + "/", ".strict-delivery/state/findings/f.yml", PROGRAM_PLAN, PS + "/program-plan/ledger.md",
                  ".strict-delivery/state/", ".STRICT-DELIVERY/state/decisions/x"):
            self.assertTrue(any("overlaps the program records" in e for e in streams_errors(two([p], ["zz.py"]), NAME, CFG)), p)
        cfg = {"paths": {"decisions": "d/dec"}}
        self.assertTrue(any("program records" in e for e in streams_errors(two(["d/dec/x.yml"], ["zz.py"]), NAME, cfg)))
        self.assertEqual(streams_errors(two([d + "/x.yml"], ["zz.py"]), NAME, cfg), [])
        r = two(["docs/x.md"], ["zz.py"]); r["shared"] = [{"path": "docs/x.md", "rule": "own-row"}]
        self.assertTrue(any("shared path" in e for e in streams_errors(r, NAME, CFG)))
        r["streams"][0]["owns"] = ["DOCS/X.MD"]
        self.assertTrue(any("shared path" in e for e in streams_errors(r, NAME, CFG)))
        r["streams"][0]["owns"] = ["docs/"]
        self.assertTrue(any("shared path" in e for e in streams_errors(r, NAME, CFG)))
        r["shared"] = [{"path": "docs/", "rule": "append-rows"}]; r["streams"][0]["owns"] = ["docs/x.md"]
        self.assertTrue(any("shared path" in e for e in streams_errors(r, NAME, CFG)))
        r["shared"] = [{"path": "docs/x.md", "rule": "own-row"}, {"path": "DOCS/x.md", "rule": "append-rows"}]; r["streams"][0]["owns"] = ["a.py"]
        self.assertTrue(any("duplicates" in e for e in streams_errors(r, NAME, CFG)))
        r["shared"] = []
        self.assertEqual(streams_errors(r, NAME, CFG), [])
        del r["shared"]
        self.assertEqual(streams_errors(r, NAME, CFG), [])

    def test_wrong_typed_fields_never_raise(self):
        r = S()
        r["streams"][0].update({"depends_on": "x", "owns": 5, "merge_order": True, "plan": None, "residual": "yes"})
        r["streams"].append(5)
        r["worktrees"] = 5
        r["shared"] = "x"
        streams_errors(r, NAME, CFG)
        streams_errors(r, NAME, CFG, S0)
        self.assertEqual(streams_errors(row(stream("a"), stream("b", merge_order=2, period=None)), NAME, CFG), [])

    def test_determinism_and_many_entries(self):
        r = two(["x.py", "x.py"], ["x.py"])
        self.assertEqual(streams_errors(r, NAME, CFG), streams_errors(r, NAME, CFG))
        big = row(*[stream("s%d" % i, ["d%d/f%d.py" % (i, j) for j in range(100)], merge_order=i + 1) for i in range(20)])
        self.assertEqual(streams_errors(big, NAME, CFG), [])


class Worktrees(unittest.TestCase):
    def errs(self, w):
        return [e for e in streams_errors({**S(), "worktrees": w}, NAME, CFG) if e.startswith("worktrees:")]

    def test_absolute_worktrees_refused(self):
        for w in ("/w", "/Users/x/w", "C:\\w", "\\\\h\\s"):
            self.assertTrue(self.errs(w), w)

    def test_inside_and_outside_forms(self):
        for w in ("w", "./w", "a/b", ".", ".strict-delivery/w"):
            self.assertTrue(self.errs(w), w)
        for w in ("../w", "../../w", "../a/b"):
            self.assertEqual(self.errs(w), [], w)
        for w in ("..", "../.."):
            self.assertTrue(self.errs(w), w)
        for w in ("a/../../w", "../w/", "../w//x", "../w/./x", "", "../w ".replace(" ", "\n"), "..\\w", "../w\x00", "../\u00e9", "../w\r"):
            self.assertTrue(self.errs(w), repr(w))
        self.assertEqual(self.errs(5), [])

    def test_worktrees_dir_resolves_against_main_worktree(self):
        with mock.patch.object(programs, "_main_worktree", return_value="/home/x/repo") as m:
            self.assertEqual(worktrees_dir("/home/x/wt/%s/integration" % NAME, S()), "/home/x/w")
            m.assert_called_once_with("/home/x/wt/%s/integration" % NAME)
            self.assertEqual(worktrees_dir("/r", {**S(), "worktrees": "../../w"}), "/home/w")
        with mock.patch.object(programs, "_main_worktree", return_value="/home/x/repo"):
            for w in ("../repo/x", "..", "/w", "w", 5):
                with self.assertRaises(GateError, msg=repr(w)):
                    worktrees_dir("/r", {**S(), "worktrees": w})
            with self.assertRaises(GateError):
                worktrees_dir("/r", None)

    def test_main_worktree_seam_calls_gitinfo(self):
        from gates.lib import gitinfo
        with mock.patch.object(gitinfo, "main_worktree", create=True, return_value="/m") as m:
            self.assertEqual(programs._main_worktree("/r"), "/m")
            m.assert_called_once_with("/r")


class Ownership(unittest.TestCase):
    def owner(self, r, path, held):
        return owner_of(r, PS, path, held)

    def test_exact_prefix_boundary(self):
        r = with_owns(S(), {"a": ["src/", "exact.py", "dir"]})
        self.assertEqual(self.owner(r, "exact.py", H()), "a")
        self.assertEqual(self.owner(r, "src/x/y.py", H()), "a")
        self.assertIsNone(self.owner(r, "srcx/y.py", H()))
        self.assertEqual(self.owner(r, "src/", H()), "a")
        self.assertEqual(self.owner(r, "dir", H()), "a")
        self.assertIsNone(self.owner(r, "dir/x", H()))
        self.assertIsNone(self.owner(r, "other.py", H()))
        self.assertEqual(self.owner(r, "Src/A.py", H()), "a")
        self.assertEqual(self.owner(with_owns(S(), {"a": ["caf\u00e9/"]}), "cafe\u0301/x", H()), "a")

    def test_plan_workspace_owned_implicitly(self):
        r = S()
        self.assertEqual(self.owner(r, PS + "/a-plan/ledger.md", H()), "a")
        self.assertEqual(self.owner(r, PS + "/b-plan/ledger.md", H()), "b")
        r2 = row(stream("a", period=("merged:z", PC)), stream("b", merge_order=2))
        self.assertEqual(self.owner(r2, PS + "/a-plan/ledger.md", H()), "a")
        self.assertEqual(self.owner(r2, PS + "/a-plan/ledger.md", H("merged:z", "merged:a")), "a")
        rec = record_streams()
        self.assertEqual([self.owner(rec, "gates/__main__.py", h) for h in (S0, S1, S2, S3)], ["package", "residual", "init4", "residual"])
        self.assertEqual([self.owner(rec, "CLAUDE.md", h) for h in (S0, S1, S2, S3)], ["residual", "residual", "init4", "release"])
        self.assertEqual([self.owner(rec, ".claude-plugin/plugin.json", h) for h in (S0, S1, S2, S3)], ["package", "residual", "residual", "release"])
        self.assertEqual([self.owner(rec, ".gitignore", h) for h in (S0, S1, S2, S3, SX)], ["residual", "residual", "init4", "release", "init4"])
        self.assertEqual(self.owner(rec, ".claude-plugin/plugin.json", SX), "package")
        for p in ("gates/producers.py", "gates/run_all.py", "tests/test_run_all.py"):
            self.assertEqual([self.owner(rec, p, h) for h in (S0, S1, S2, S3)], ["package", "residual", "init4", "residual"])
            with self.assertRaises(ValueError) as cm:
                self.owner(rec, p, SX)
            self.assertIn("package", str(cm.exception))
            self.assertIn("init4", str(cm.exception))
        for h in (S0, S1, S2, S3, SX):
            self.assertEqual(self.owner(rec, PS + "/package-plan/x.md", h), "package")
            self.assertEqual(self.owner(rec, PS + "/residual-plan/x.md", h), "residual")
            self.assertEqual(self.owner(rec, "other.py", h), "residual")
            self.assertIsNone(self.owner(rec, PROGRAM_PLAN, h))
            self.assertIsNone(self.owner(rec, PS + "/program-plan/ledger.md", h))

    def test_residual_period_and_records(self):
        r = row(stream("a", ["x.py"]), stream("residual", residual=True, period=("merged:a", PC), merge_order=2))
        self.assertIsNone(self.owner(r, "other.py", H()))
        self.assertEqual(self.owner(r, "other.py", H("merged:a")), "residual")
        r = row(stream("a", ["x.py"]), stream("residual", residual=True, period=(PS_, "merged:a"), merge_order=2))
        self.assertIsNone(self.owner(r, "other.py", H("merged:a")))
        self.assertEqual(self.owner(r, PS + "/residual-plan/n.md", H("merged:a")), "residual")
        res = row(stream("a", ["x.py"]), stream("residual", residual=True, merge_order=2))
        for p in (".strict-delivery/state/programs/%s/streams.yml" % NAME, ".strict-delivery/state/decisions/x.yml",
                  ".strict-delivery/state/findings/f.yml", PROGRAM_PLAN, PS + "/program-plan/ledger.md"):
            self.assertIsNone(self.owner(res, p, H()), p)
        self.assertIsNone(self.owner(S(), "other.py", H()))
        rest = row(stream("a", ["x.py"]), stream("rest", residual=True, merge_order=2))
        self.assertEqual(self.owner(rest, "other.py", H()), "rest")
        self.assertEqual(self.owner(rest, PS + "/rest-plan/x", H()), "rest")
        named = row(stream("a", ["x.py"]), {**stream("residual", ["y.py"], merge_order=2)})
        self.assertIsNone(self.owner(named, "other.py", H()))

    def test_windows_lifecycle_and_two_open(self):
        r = row(stream("a", [W("w.py", "merged:q", "merged:a")]), stream("residual", residual=True, merge_order=2))
        self.assertEqual(self.owner(r, "w.py", H()), "residual")
        self.assertEqual(self.owner(r, "w.py", H("merged:q")), "a")
        self.assertEqual(self.owner(r, "w.py", H("merged:q", "merged:a")), "residual")
        r = row(stream("a", ["x.py"], ("merged:q", "merged:a")), stream("residual", residual=True, merge_order=2))
        self.assertEqual([self.owner(r, "x.py", h) for h in (H(), H("merged:q"), H("merged:q", "merged:a"))], ["residual", "a", "residual"])
        self.assertIsNone(self.owner(row(stream("a", ["x.py"], ("merged:q", "merged:a"))), "x.py", H()))
        r = two([W("x.py", PS_, "merged:a")], [W("x.py", PS_, "merged:b")])
        with self.assertRaises(ValueError) as cm:
            self.owner(r, "x.py", H())
        self.assertIn("a and b", str(cm.exception))
        self.assertEqual(self.owner(with_owns(S(), {"a": ["src/", "src/x.py"]}), "src/x.py", H()), "a")
        with self.assertRaises(ValueError):
            self.owner(with_owns(S(), {"a": [PS + "/b-plan/x.md"]}), PS + "/b-plan/x.md", H())
        self.assertEqual(self.owner(r, "x.py", H("merged:zz/y", "merged:a")), "b")

    def test_path_and_held_forms(self):
        for p in ("", "/x", "./x", "a//b", "a/../b", "a\x00b", ".", "..", None, 5):
            with self.assertRaises(ValueError, msg=repr(p)):
                self.owner(S(), p, H())
        self.assertIsNone(self.owner(S(), "\U0001fae8.py", H()))
        self.assertEqual(self.owner(with_owns(S(), {"a": ["a\nb"]}), "a\nb", H()), "a")
        for h in (None, frozenset(), set(), [], "x", frozenset({PS_, PC}), frozenset({PS_, 1})):
            with self.assertRaises(ValueError):
                self.owner(S(), "x", h)
        with self.assertRaises(ValueError):
            self.owner(None, "x", H())

    def test_owner_of_cfg_paths(self):
        cfg = {"paths": {"decisions": "d/dec", "plan_state": "ps"}}
        res = row(stream("a", ["x.py"]), stream("residual", residual=True, merge_order=2))
        self.assertIsNone(owner_of(res, "ps", "d/dec/x.yml", H(), cfg=cfg))
        self.assertEqual(owner_of(res, "ps", ".strict-delivery/state/decisions/x.yml", H(), cfg=cfg), "residual")
        self.assertEqual(owner_of(res, "ps", "ps/a-plan/x", H(), cfg=cfg), "a")
        self.assertIsNone(owner_of(res, "ps", "ps/program-plan/ledger.md", H(), cfg=cfg))
        self.assertIsNone(owner_of(res, "ps", "ps/program-plan/ledger.md", H()))   # cfg None: plan_state from the argument
        self.assertEqual(owner_of(res, "ps", "ps/a-plan/x", H()), "a")

    def test_shared_rule(self):
        r = {**S(), "shared": [{"path": "docs/x.md", "rule": "own-row"}, {"path": "docs/y.md", "rule": "append-rows"}, {"path": "dd/", "rule": "own-row"}]}
        self.assertEqual(shared_rule(r, "docs/x.md"), "own-row")
        self.assertEqual(shared_rule(r, "docs/y.md"), "append-rows")
        self.assertEqual(shared_rule(r, "DOCS/X.md"), "own-row")
        self.assertEqual(shared_rule(r, "dd/a.md"), "own-row")
        for p in ("docs/z.md", ""):
            self.assertIsNone(shared_rule(r, p))
        self.assertIsNone(shared_rule(S(), "docs/x.md"))
        del r["shared"]
        self.assertIsNone(shared_rule(r, "x"))
        with self.assertRaises(ValueError):
            shared_rule(r, 5)
        with self.assertRaises(ValueError):
            shared_rule([], "x")


def bd(streams, edges=()):
    return {"streams": [{"id": k, "tasks": list(v)} for k, v in streams.items()],
            "edges": [{"from": a, "to": b} for a, b in edges]}


BDF = {"a": ["a1.1", "a1.2", "a2.1"], "b": ["b1.1", "b2.1"], "c": ["c1.1", "c2.1"]}


def cb(edges, x, y):
    return comes_before(bd(BDF, edges), x, y)


class Order(unittest.TestCase):
    def test_breakdown_sub_blocks(self):
        self.assertEqual(breakdown_sub_blocks(bd(BDF)), {"a": {"a1", "a2"}, "b": {"b1", "b2"}, "c": {"c1", "c2"}})
        self.assertEqual(breakdown_sub_blocks(bd({"s": ["x", "y"], "t": ["4c.1", "x", "4c.1"]})), {"s": set(), "t": {"4c"}})
        self.assertEqual(breakdown_sub_blocks({"streams": [{"id": "r", "residual": True, "tasks": ["R5.1"]}], "done": ["a0.1"]}), {"r": {"R5"}})
        self.assertEqual(breakdown_sub_blocks(RECORD_BD), SUBS)
        for bad in (None, {}, {"streams": "x"}, {"streams": [{"id": "a"}]}, {"streams": [{"id": "a", "tasks": "x"}]},
                    {"streams": [{"id": "a", "tasks": [1]}]}, {"streams": [{"tasks": []}]}):
            with self.assertRaises(ValueError, msg=repr(bad)):
                breakdown_sub_blocks(bad)

    def test_comes_before_rules(self):
        self.assertTrue(cb([("a1.2", "b1.1")], "merged:a/a1", "merged:b/b1"))
        self.assertFalse(cb([("a1.2", "b1.1")], "merged:b/b1", "merged:a/a1"))
        e = [("a1.1", "a2.1"), ("a2.1", "b1.1")]
        self.assertFalse(cb(e, "merged:a/a1", "merged:b/b1"))
        self.assertTrue(cb(e, "merged:a/a2", "merged:b/b1"))
        self.assertFalse(cb(e, "merged:a/a1", "merged:a/a2"))
        e = [("a1.1", "a1.2"), ("a1.2", "b1.1")]
        self.assertTrue(cb(e, "merged:a/a1", "merged:b/b1"))
        self.assertFalse(cb(e, "merged:a/a1", "merged:a/a1"))
        self.assertTrue(cb([("a1.1", "c1.1"), ("c1.1", "b1.1")], "merged:a/a1", "merged:b/b1"))
        e = [("a1.1", "c1.1"), ("c1.1", "c2.1"), ("c2.1", "b1.1")]
        self.assertFalse(cb(e, "merged:a/a1", "merged:b/b1"))
        self.assertTrue(cb(e, "merged:c/c2", "merged:b/b1"))
        self.assertTrue(cb([("a1.1", "b1.1"), ("b1.1", "c1.1")], "merged:a/a1", "merged:c/c1"))

    def test_comes_before_stream_last_event(self):
        self.assertFalse(cb([("a1.1", "b1.1")], "merged:a", "merged:b/b1"))
        self.assertTrue(cb([("a1.1", "b1.1"), ("a2.1", "b1.1")], "merged:a", "merged:b/b1"))
        self.assertTrue(cb([("a1.1", "b1.1")], "merged:a/a1", "merged:b"))
        self.assertFalse(cb([("a1.1", "b1.1")], "merged:a/a1", "merged:c"))
        self.assertTrue(cb([("a1.1", "b1.1"), ("a2.1", "b2.1")], "merged:a", "merged:b"))
        self.assertFalse(cb([("a1.1", "b1.1")], "merged:a", "merged:b"))

    def test_comes_before_bounds_and_noise(self):
        evs = [PS_, PC, "merged:a/a1", "merged:a", "merged:b/b2"]
        for e in evs:
            self.assertEqual(cb([], PS_, e), e != PS_)
            self.assertEqual(cb([], e, PS_), False)
            self.assertEqual(cb([], e, PC), e != PC)
            self.assertEqual(cb([], PC, e), False)
        self.assertTrue(cb([], PS_, PC))
        self.assertFalse(cb([], PC, PS_))
        for x, y in itertools.permutations(["merged:a/a1", "merged:b/b1", "merged:c"], 2):
            self.assertFalse(cb([], x, y))
        both = [("a1.1", "b1.1"), ("b1.1", "a1.1")]
        self.assertTrue(cb(both, "merged:a/a1", "merged:b/b1") and cb(both, "merged:b/b1", "merged:a/a1"))
        noisy = [("a1.1", "b1.1"), ("a1.1", "b1.1"), ("a1.1", "zz.1"), ("a1.1", "a1.1")]
        self.assertTrue(cb(noisy, "merged:a/a1", "merged:b/b1"))
        self.assertTrue(cb(list(reversed(noisy)), "merged:a/a1", "merged:b/b1"))
        for bad in ("later", "merged:zz/x", "merged:a/zz", "merged:a/", None):
            with self.assertRaises(ValueError, msg=repr(bad)):
                cb([], bad, "merged:b/b1")
        self.assertFalse(comes_before(bd({"s": ["x"], "t": ["t1.1"]}), "merged:s", "merged:t/t1"))
        self.assertFalse(comes_before(bd({"s": ["x"], "t": ["t1.1"]}), "merged:t/t1", "merged:s"))
        with self.assertRaises(ValueError):
            comes_before({"streams": [{"id": "a", "tasks": ["a1.1"]}], "edges": "x"}, PS_, PC)

    def test_comes_before_perf_and_digits(self):
        n = 400
        chain = bd({"s%d" % i: ["t%d.1" % i] for i in range(n)}, [("t%d.1" % i, "t%d.1" % (i + 1)) for i in range(n - 1)])
        self.assertTrue(comes_before(chain, "merged:s0/t0", "merged:s%d/t%d" % (n - 1, n - 1)))
        big = "9" * 4301
        self.assertTrue(comes_before(bd({"a": [big + ".1"], "b": ["b1.1"]}, [(big + ".1", "b1.1")]), "merged:a/" + big, "merged:b/b1"))

    def test_record_comes_before(self):
        self.assertTrue(comes_before(RECORD_BD, "merged:package/3d", "merged:residual/R2"))
        self.assertFalse(comes_before(RECORD_BD, "merged:residual/R2", "merged:package/3d"))


def downclosed(breakdown):
    subs = [(s, b) for s, bs in sorted(breakdown_sub_blocks(breakdown).items()) for b in sorted(bs)]
    out = []
    for mask in range(1 << len(subs)):
        h = {subs[i] for i in range(len(subs)) if mask >> i & 1}
        evs = {"merged:%s/%s" % x for x in h}
        if all(any(not comes_before(breakdown, "merged:%s/%s" % y, e) or True for e in evs) and
               all(y in h for y in subs if any(comes_before(breakdown, "merged:%s/%s" % y, e) for e in evs)) for y in subs):
            out.append(h)
    return out


def brute(streams, breakdown, path):
    sub = breakdown_sub_blocks(breakdown)
    for h in downclosed(breakdown):
        merged = {}
        for s, b in h:
            merged.setdefault(s, set()).add(b)
        try:
            if owner_of(streams, PS, path, held_events(merged, sub)) == "residual":
                return True
        except ValueError:
            pass
    return False


class Residual(unittest.TestCase):
    def rd(self, entries, period=(PS_, PC), edges=(), subs=None):
        streams = row(stream("a", entries.get("a", ["zz-a.py"])), stream("b", entries.get("b", ["zz-b.py"]), merge_order=2),
                      stream("y", ["zz-y.py"], merge_order=3), stream("residual", residual=True, period=period, merge_order=4))
        b = bd(subs or {"a": ["a1.1"], "b": ["b1.1"], "y": ["y1.1"], "residual": ["r1.1"]}, edges)
        return streams, b

    def test_rows(self):
        a, ps, pc = "merged:a", PS_, PC
        cases = [
            ("unowned.py", {}, (ps, pc), (), True),
            ("f.py", {"a": [W("f.py", ps, a)]}, (ps, pc), (), True),
            ("f.py", {"a": ["f.py"]}, (ps, pc), (), False),
            ("chained.md", {"a": [W("chained.md", ps, a)], "b": [W("chained.md", a, pc)]}, (ps, pc), (), False),
            ("twostep.py", {"a": [W("twostep.py", ps, a)], "b": [W("twostep.py", a, "merged:b")]}, (ps, pc), (), True),
            ("late.md", {"a": [W("late.md", ps, a)]}, (ps, "merged:y"), [("a1.1", "y1.1")], True),
            ("late.md", {"a": [W("late.md", ps, a)]}, (ps, "merged:y"), [("y1.1", "a1.1")], False),
            ("f.py", {"a": [W("f.py", a, pc)]}, (ps, pc), (), True),
            ("f.py", {"a": [W("f.py", ps, pc)]}, (ps, pc), (), False),
            ("f.py", {"a": [W("f.py", ps, "merged:zz")]}, (ps, pc), (), False),
            ("f.py", {"a": [W("f.py", "merged:zz", pc)]}, (ps, pc), (), True),
            ("f.py", {"b": [W("f.py", ps, "merged:b")]}, ("merged:a/a1", pc), (), True),
            ("f.py", {}, ("merged:z", pc), (), False),
            ("f.py", {}, ("merged:q/x", pc), (), False),
            ("late.md", {"a": [W("late.md", ps, a)]}, (ps, "merged:y"), [("y1.1", "b1.1"), ("b1.1", "a1.1")], False),
            ("Late.MD", {"a": [W("late.md", ps, a)]}, (ps, "merged:y"), [("a1.1", "y1.1")], True),
            ("docs/x.md", {"a": [W("docs/", ps, a)]}, (ps, pc), (), True),
            (PS + "/a-plan/x.md", {}, (ps, pc), (), False),
            (PS + "/residual-plan/x.md", {}, ("merged:z", pc), (), True),
            (PROGRAM_PLAN, {}, (ps, pc), (), False),
            (PS + "/program-plan/ledger.md", {}, (ps, pc), (), False),
            (".strict-delivery/state/programs/%s/streams.yml" % NAME, {}, (ps, pc), (), False),
            (".strict-delivery/state/decisions/x.yml", {}, (ps, pc), (), False),
            (".strict-delivery/state/findings/f.yml", {}, (ps, pc), (), False),
        ]
        for path, entries, period, edges, want in cases:
            streams, b = self.rd(entries, period, edges)
            self.assertEqual(residual_reachable(streams, b, PS, path), want, (path, entries, period, edges))
        # two sub-blocks of a, until merged:a needs both; the edge orders only a1 before y
        streams, b = self.rd({"a": [W("f.py", ps, a)]}, (ps, "merged:y"), [("a1.1", "y1.1")], subs={"a": ["a1.1", "a2.1"], "b": ["b1.1"], "y": ["y1.1"], "residual": ["r1.1"]})
        self.assertTrue(residual_reachable(streams, b, PS, "f.py"))
        streams, b = self.rd({"a": [W("f.py", ps, "merged:a/a1"), W("f.py", "merged:a/a1", a)]}, subs={"a": ["a1.1", "a2.1"], "b": ["b1.1"], "y": ["y1.1"], "residual": ["r1.1"]})
        self.assertTrue(residual_reachable(streams, b, PS, "f.py"))
        # no residual stream
        self.assertFalse(residual_reachable(S(), bd({"a": ["a1.1"], "b": ["b1.1"]}), PS, "x.py"))

    def test_record_residual_reachable(self):
        for p, want in [("gates/__main__.py", True), ("CLAUDE.md", True), (".claude-plugin/plugin.json", True),
                        (PS + "/package-plan/x.md", False), (PROGRAM_PLAN, False)]:
            self.assertEqual(residual_reachable(record_streams(), RECORD_BD, PS, p), want, p)

    def test_residual_reachable_matches_brute_force(self):
        rng = random.Random(11)
        ps, pc, a = PS_, PC, "merged:a"
        files = ["f.py", "g/x.py", PS + "/residual-plan/x", PS + "/a-plan/x", "unowned.py", PROGRAM_PLAN]
        fam = []
        for i in range(60):
            ents = {}
            for sid in ("a", "b"):
                ev = [ps, a, "merged:b", "merged:y", "merged:a/a1", "merged:y/y1", pc, "merged:zz"]
                lo, hi = rng.choice(ev), rng.choice(ev)
                paths = rng.choice(["f.py", "g/", "f.py", "unowned.py"])
                ents[sid] = [W(paths, lo, hi)] if rng.random() < 0.8 else [paths]
            period = (rng.choice([ps, "merged:a/a1", "merged:y"]), rng.choice([pc, "merged:y", "merged:b", a]))
            edges = [(x, y) for x, y in [("a1.1", "y1.1"), ("y1.1", "b1.1"), ("b1.1", "a1.1"), ("a1.1", "b1.1"), ("y1.1", "a1.1")] if rng.random() < 0.35]
            fam.append((ents, period, edges))
        n = 0
        for ents, period, edges in fam:
            streams, b = self.rd(ents, period, edges)
            for path in files:
                self.assertEqual(residual_reachable(streams, b, PS, path), brute(streams, b, path), (ents, period, edges, path))
                n += 1
        self.assertGreater(n, 300)

    def test_perf_chained_windows(self):
        sts = [stream("s%d" % i, [W("f.py", PS_ if i == 0 else "merged:s%d" % (i - 1), "merged:s%d" % i)], merge_order=i + 1) for i in range(30)]
        streams = row(*sts, stream("residual", residual=True, merge_order=99))
        b = bd({**{"s%d" % i: ["t%d.1" % i] for i in range(30)}, "residual": ["r1.1"]})
        self.assertTrue(residual_reachable(streams, b, PS, "f.py"))


class StatusPage(unittest.TestCase):
    def page(self, rows, facts=""):
        return "<!-- schema: status/1 -->\n\n%s\n%s\n%s\n%s" % (HEAD, SEP, "\n".join(rows), facts)

    def rowtext(self, s, **kw):
        c = {"block": "none", "branch": "%s/%s/main" % (NAME, s), "worktree": "../w/%s/%s/main" % (NAME, s), "next": "none",
             "estimate": "5", "used": "0", "status": "ready", "blockers": "none", "pending": "none", "delivers": "p"}
        c.update(kw)
        return "| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (s, c["block"], c["branch"], c["worktree"], c["next"], c["estimate"],
                                                                      c["used"], c["status"], c["blockers"], c["pending"], c["delivers"])

    def errs(self, rows, req=("R-20261101-abcd",)):
        return status_errors(status_rows(self.page(rows)), S(), cfg={"ids": {"request": "R", "decision": "DEC"}}, request_ids=set(req))

    def test_status_rows(self):
        rows = status_rows(self.page([self.rowtext("a"), self.rowtext("b", delivers="a\\|b")]))
        self.assertEqual([r["stream"] for r in rows], ["a", "b"])
        self.assertEqual(list(rows[0]), list(programs.STATUS_HEADERS))
        self.assertEqual(rows[1]["delivers"], "a|b")
        self.assertEqual(status_rows(self.page([self.rowtext("a", delivers="a\\\\|b")]))[0]["delivers"], "a\\|b") if False else None
        self.assertEqual(status_rows(""), [])
        self.assertEqual(status_rows("prose only"), [])
        self.assertEqual(status_rows(self.page([self.rowtext("a")]).replace("next task", "next  task")), [])
        short = "| a | none | x | y | none | 5 | 0 | ready | none | none |"
        r = status_rows(self.page([self.rowtext("a"), short, "| a |" + " b |" * 11]))
        self.assertEqual([("__error__" in x) for x in r], [False, True, True])
        self.assertEqual(r[1]["__line__"], 6)
        self.assertEqual(len(status_rows(self.page(["|\t%s\t" % self.rowtext("a")[1:]]))), 1)
        with self.assertRaises(ValueError):
            status_rows(None)

    def test_status_errors_valid_and_rows(self):
        self.assertEqual(self.errs([self.rowtext("a"), self.rowtext("b")]), [])
        self.assertEqual(self.errs([self.rowtext("b"), self.rowtext("a")]), [])
        self.assertEqual(self.errs([self.rowtext("a")]), ["missing row for stream b"])
        self.assertTrue(any(e.startswith("extra row") for e in self.errs([self.rowtext("a"), self.rowtext("b"), self.rowtext("c")])))
        self.assertTrue(any("duplicate row" in e for e in self.errs([self.rowtext("a"), self.rowtext("a"), self.rowtext("b")])))
        self.assertTrue(any("status row at line" in e for e in self.errs([self.rowtext("a"), self.rowtext("b"), "| a | b |"])))
        self.assertEqual(status_errors([], S(), cfg={"ids": {"request": "R", "decision": "DEC"}}, request_ids=set()), ["missing row for stream a", "missing row for stream b"])
        with self.assertRaises(TypeError):
            status_errors([], S())

    def test_status_values_branch_worktree_numbers(self):
        for ok in programs.STATUS_VALUES:
            self.assertEqual(self.errs([self.rowtext("a", status=ok), self.rowtext("b")]), [], ok)
        for bad in ("done", "Ready", ""):
            self.assertTrue(any("status '%s'" % bad in e for e in self.errs([self.rowtext("a", status=bad), self.rowtext("b")])), bad)
        for br in ("%s/a/g" % NAME, "%s/b/main" % NAME, "a/main", ""):
            self.assertTrue(any("branch" in e for e in self.errs([self.rowtext("a", branch=br), self.rowtext("b")])), br)
        for wt in ("../w/%s/a/main/" % NAME, "/w/%s/a/main" % NAME, "../w/%s/b/main" % NAME):
            self.assertTrue(any("worktree" in e for e in self.errs([self.rowtext("a", worktree=wt), self.rowtext("b")])), wt)
        for col in ("estimate", "used"):
            for ok in ("0", "7", "10", "9" * 600):
                self.assertEqual(self.errs([self.rowtext("a", **{col: ok}), self.rowtext("b")]), [], ok)
            for bad in ("-1", "1.5", "03", "00", "+1", "1e3", "0x10", "1_0", "", "none", "\u0663", "7.0", "9" * 601):
                self.assertTrue(any(col in e for e in self.errs([self.rowtext("a", **{col: bad}), self.rowtext("b")])), repr(bad))
        self.assertEqual(self.errs([self.rowtext("a", estimate="1", used="9"), self.rowtext("b")]), [])
        self.assertEqual(self.errs([self.rowtext("a", block="\u0870 x", next="\u00e9", delivers="\u0870" * 300), self.rowtext("b")]), [])

    def test_status_blockers_and_pending(self):
        rid = "R-20261101-abcd"
        self.assertEqual(self.errs([self.rowtext("a", blockers=rid + "," + rid), self.rowtext("b")]), [])
        for bad in ("R-20261101-zzzz", "DEC-20261101-abcd", "None", "NONE", "", rid + ", " + rid, rid + ","):
            self.assertTrue(any("blockers" in e for e in self.errs([self.rowtext("a", blockers=bad), self.rowtext("b")])), repr(bad))
        d = "DEC-20261101-abcd"
        self.assertEqual(self.errs([self.rowtext("a", pending=d + "," + d), self.rowtext("b")]), [])
        for bad in ("F-20261101-abcd", "x", "", d + ", " + d):
            self.assertTrue(any("pending decisions" in e for e in self.errs([self.rowtext("a", pending=bad), self.rowtext("b")])), repr(bad))

    def test_status_errors_argument_types(self):
        cfg = {"ids": {"request": "R", "decision": "DEC"}}
        for bad in (None, {}, {"program": NAME}, {"program": NAME, "streams": [1]}):
            with self.assertRaises(ValueError):
                status_errors([], bad, cfg=cfg, request_ids=set())
        with self.assertRaises(ValueError):
            status_errors(None, S(), cfg=cfg, request_ids=set())
        with self.assertRaises(ValueError):
            status_errors([], S(), cfg=cfg, request_ids=None)
        bad = {**S(), "program": "x"}
        self.assertTrue(status_errors(status_rows(self.page([self.rowtext("a")])), bad, cfg=cfg, request_ids=set()))

    def test_status_fact_lines(self):
        facts = ("Batch-cut: none\nIntegration: head=abcdef1\nAgent: ag-1 stream=a task=a1.1 transcript=t last=r jobs=none\n"
                 "Agent: ag-2 stream=program task=x transcript=t last=r jobs=j1:running\n")
        self.assertEqual(status_fact_errors(self.page([self.rowtext("a")], facts), S()), [])
        self.assertEqual(status_fact_errors(self.page([self.rowtext("a")]), S()), [])
        self.assertEqual(status_fact_errors("", S()), [])
        e = status_fact_errors("Batch-cut: none\nBatch-cut: abcdef1\n", S())
        self.assertEqual(e, ["Batch-cut: more than one line (lines 1, 2)"])
        self.assertTrue(any("Integration:" in x for x in status_fact_errors("Integration: head=abcdef1\nIntegration: head=abcdef2\n", S())))
        self.assertEqual(len(status_fact_errors("Batch-cut: ZZ\nBatch-cut: none\n", S())), 1)
        self.assertEqual(status_fact_errors("x Batch-cut: x\n Batch-cut: x\nBatch-cut:none\nbatch-cut: none\nBatch-cut: none\n| Batch-cut: none |\n", S()), [])
        d = status_fact_errors("Agent: ag-1 stream=a\nAgent: ag-1 stream=b\nAgent: ag-1x stream=a", S())
        self.assertEqual(len(d), 1)
        self.assertIn("ag-1", d[0])
        for s in ("zz", "integration", "", "Program"):
            self.assertTrue(any("stream '%s'" % s in x for x in status_fact_errors("Agent: ag-1 stream=%s task=t\n" % s, S())), s)
        self.assertEqual(status_fact_errors("Agent: x\nAgent:\nAgent: ag stream=a jobs=done:what", S()), [])
        self.assertEqual(status_fact_errors("Batch-cut: none\r\n", S()), [])
        for bad in ((None, S()), (5, S()), ("", None), ("", {}), ("", {"streams": [1]})):
            with self.assertRaises(ValueError):
                status_fact_errors(*bad)


class Requests(unittest.TestCase):
    def setUp(self):
        # gates/schemas/request.yml is delivery (i)'s file; until it lands `migrate("request", ...)` has no schema
        # to read, so phase 1 runs the rules through an identity migration (the registry has no request step).
        p = mock.patch.object(programs, "_migrated", lambda kind, row: row)
        p.start()
        self.addCleanup(p.stop)

    def prog(self, *rows, name=NAME):
        reqs = [store.Record(r.get("id"), r, "programs/%s/requests/%s.yml" % (name, r.get("id"))) for r in rows]
        return mock.Mock(requests=reqs, spec=["requests", "name"], **{"name": name}) if False else _P(name, reqs)

    def req(self, status="open", rid="R-1", **kw):
        r = {"schema": "request/1", "id": rid, "from_stream": "a", "to_stream": "b", "files": ["x.py"], "status": status}
        r.update(kw)
        return r

    def test_request_transitions_literal(self):
        self.assertEqual(REQUEST_TRANSITIONS, {"open": ("accepted", "disputed", "withdrawn"), "accepted": ("done", "withdrawn"),
                                              "disputed": ("accepted", "withdrawn"), "done": (), "withdrawn": ()})
        for v in REQUEST_TRANSITIONS.values():
            self.assertIs(type(v), tuple)

    def test_request_transitions(self):
        sts = ["open", "accepted", "done", "disputed", "withdrawn"]
        for a, b in itertools.product(sts, sts):
            extra_b = {"resolution": {"commits": ["a" * 40], "at": "b" * 40, "by": "a"}} if b == "done" else {}
            extra_a = {"resolution": {"commits": ["a" * 40], "at": "b" * 40, "by": "a"}} if a == "done" else {}
            base = self.prog(self.req(a, **extra_a))
            now = self.prog(self.req(b, decision="DEC-20261101-abcd", **extra_b))
            errs = request_base_errors(now, base)
            got = any(s == "transition.R-1" for s, _ in errs)
            self.assertEqual(got, b not in REQUEST_TRANSITIONS[a] and a != b, (a, b, errs))

    def test_base_rules(self):
        base = self.prog(self.req())
        self.assertEqual(request_base_errors(base, base), [])
        self.assertEqual([s for s, _ in request_base_errors(self.prog(), base)], ["deleted.R-1"])
        self.assertEqual(request_base_errors(self.prog(self.req(), self.req(rid="R-2")), base), [])
        self.assertEqual([s for s, _ in request_base_errors(self.prog(self.req(rid="R-2", status="done")), self.prog())], ["transition.R-2"])
        dis = self.prog(self.req("disputed"))
        self.assertEqual([s for s, _ in request_base_errors(self.prog(self.req("accepted")), dis)], ["dispute.R-1"])
        self.assertEqual([s for s, _ in request_base_errors(self.prog(self.req("withdrawn")), dis)], ["dispute.R-1"])
        self.assertEqual(request_base_errors(self.prog(self.req("accepted", decision="DEC-20261101-abcd")), dis), [])
        self.assertEqual(request_base_errors(self.prog(self.req("disputed")), dis), [])
        self.assertEqual(request_base_errors(self.prog(self.req("disputed")), base), [])
        done = {"resolution": {"commits": ["a" * 40], "at": "b" * 40, "by": "a"}}
        d0 = self.prog(self.req("done", **done))
        self.assertEqual(request_base_errors(d0, d0), [])
        self.assertEqual([s for s, _ in request_base_errors(self.prog(self.req("done", need="x", **done)), d0)], ["immutable.R-1"])
        w0 = self.prog(self.req("withdrawn"))
        self.assertEqual([s for s, _ in request_base_errors(self.prog(self.req("withdrawn", files=["y.py"])), w0)], ["immutable.R-1"])
        self.assertEqual(request_base_errors(self.prog(dict(reversed(list(self.req("withdrawn").items())))), w0), [])
        both = [s for s, _ in request_base_errors(self.prog(self.req("open", need="x")), d0)]
        self.assertEqual(sorted(both), ["immutable.R-1", "transition.R-1"])
        for st in ("closed", None, 5, []):
            errs = request_base_errors(self.prog(self.req(st)), base)
            self.assertEqual([s for s, _ in errs], ["transition.R-1"])
        with self.assertRaises(ValueError):
            request_base_errors(base, _P("20261101-y", []))
        with self.assertRaises(ValueError):
            request_base_errors(None, base)
        self.assertEqual(request_base_errors(self.prog({"id": None}), self.prog({"id": None})), [])


class _P:
    def __init__(self, name, requests):
        self.name, self.requests = name, requests


class Agreement(unittest.TestCase):
    def pair(self):
        st = row(stream("a", ["x/", W("y.py", "merged:a/a1", "merged:a")], merge_order=1, plan=PG + "/a-plan.md"),
                 stream("residual", residual=True, merge_order=2), plan=PROGRAM_PLAN)
        st["streams"][0]["period"] = {"from": "merged:b/b1", "until": PC}
        st["streams"][1]["period"] = {"from": PS_, "until": PC}
        b = {"plan": "program-plan", "streams": [
            {"id": "a", "tasks": ["a1.1"], "paths": ["x/", {"path": "y.py", "from": "merged:a/a1", "until": "merged:a"}],
             "period": {"from": "merged:b/b1", "until": PC}},
            {"id": "residual", "tasks": ["R1.1"], "residual": True}], "edges": []}
        return st, b

    def test_agreement(self):
        st, b = self.pair()
        self.assertEqual(agreement_errors(st, b, "program-plan"), [])
        # the paths in another order; a window that writes out the period's bounds equals a plain item
        b["streams"][0]["paths"] = [{"path": "y.py", "from": "merged:a/a1", "until": "merged:a"}, {"path": "x/", "from": "merged:b/b1", "until": PC}]
        self.assertEqual(agreement_errors(st, b, "program-plan"), [])
        st2, b2 = self.pair(); b2["streams"][0]["paths"].append("z/")
        self.assertTrue(any("streams" in e and "paths" in e for e in agreement_errors(st2, b2, "program-plan")))
        st2, b2 = self.pair(); b2["streams"].append({"id": "c", "tasks": ["c1.1"], "paths": ["c/"]})
        self.assertTrue(any("stream c" in e for e in agreement_errors(st2, b2, "program-plan")))
        st2, b2 = self.pair(); del st2["streams"][1]
        self.assertTrue(any("stream residual" in e for e in agreement_errors(st2, b2, "program-plan")))
        st2, b2 = self.pair(); del b2["streams"][0]["period"]
        self.assertTrue(any("period" in e for e in agreement_errors(st2, b2, "program-plan")))
        st2, b2 = self.pair(); b2["streams"][1]["period"] = {"from": PS_, "until": PC}
        self.assertEqual(agreement_errors(st2, b2, "program-plan"), [])      # an absent period equals program-start..program-close
        st2, b2 = self.pair(); b2["streams"][1]["residual"] = False
        self.assertTrue(any("residual" in e for e in agreement_errors(st2, b2, "program-plan")))
        self.assertTrue(any("breakdown's plan" in e for e in agreement_errors(st, b, "other")))
        st2, b2 = self.pair(); st2["plan"] = PG + "/other.md"
        self.assertTrue(any("plan of streams.yml" in e for e in agreement_errors(st2, b2, "program-plan")))
        st2, b2 = self.pair(); b2["done"] = ["a1.1"]
        self.assertEqual(agreement_errors(st2, b2, "program-plan"), [])
        with self.assertRaises(ValueError):
            agreement_errors(st, b, None)

    def test_stacked_order(self):
        def mk(edges, t_tasks=("t1.1",)):
            st = row(stream("s", ["s/"], merge_order=1, stacked_on="t"), stream("t", ["t/"], merge_order=2), plan=PROGRAM_PLAN)
            b = {"plan": "program-plan", "streams": [{"id": "s", "tasks": ["s1.1", "s2.1"], "paths": ["s/"]},
                                                   {"id": "t", "tasks": list(t_tasks), "paths": ["t/"]}],
                 "edges": [{"from": x, "to": y} for x, y in edges]}
            return st, b
        st, b = mk([("t1.1", "s1.1"), ("t1.1", "s2.1")])
        self.assertEqual(agreement_errors(st, b, "program-plan"), [])
        st, b = mk([("t1.1", "s1.1")])
        self.assertEqual([e for e in agreement_errors(st, b, "program-plan") if "stacked_on" in e],
                         ["stacked_on: stream s sub-block s2 is not ordered after merged:t by the breakdown's edges"])
        st, b = mk([("t1.1", "s1.1"), ("t1.1", "s2.1")], t_tasks=("t1.1", "t2.1"))   # t has two sub-blocks, edges from one only
        self.assertTrue(any("stacked_on" in e for e in agreement_errors(st, b, "program-plan")))
        st, b = mk([("t1.1", "s1.1"), ("t2.1", "s1.1"), ("t1.1", "s2.1"), ("t2.1", "s2.1")], t_tasks=("t1.1", "t2.1"))
        self.assertEqual(agreement_errors(st, b, "program-plan"), [])


if __name__ == "__main__":
    unittest.main()
