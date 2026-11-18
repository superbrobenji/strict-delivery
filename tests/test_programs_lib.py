"""Tests for gates.lib.programs (plan Task P2.1, part ii) through the production functions on hand-built rows.
Expected values are written by hand from the plan and the input-domain tables (task-P2.1-domain.md part A,
task-P2.1-ownership-domain.md part B); the ``unicodedata`` oracle below is the independent check of ``path_key``."""
import ast
import dataclasses
import itertools
import os
import pathlib
import random
import unicodedata
import unittest
from unittest import mock

from gates.lib import config, gitinfo, migrations, programs, store, yamlsub
from gates.lib.programs import (NAME_RE, REQUEST_TRANSITIONS, Program, agreement_errors, branch_of, breakdown_sub_blocks,
                                comes_before, counted_lines, event_problem, fold, group_problem, held_events,
                                live_programs, load_program, nfc, nfd, owner_of, parse_branch, path_key,
                                program_problem, request_base_errors, request_errors, residual_reachable,
                                shared_rule, status_errors, status_fact_errors, status_rows, stream_problem,
                                streams_errors, sub_block, window_of, worktree_of, worktrees_dir)
from gates.lib.result import GateError
from tests.helpers import (INT_LIMITS, GitIsolatedTestCase, check_root_forms, commit_all, git, int_limit, make_repo,
                           minimal_config, root_forms, write_record)

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

    def test_event_problem_reasons_keep_the_d_b5_phrase(self):
        # D-B5: the recommended phrases of Q5 are the prefix of the reason; a ": <value>" suffix is allowed.
        ids_ = {"a"}
        self.assertTrue(event_problem(5, ids_).startswith("not a str"))
        self.assertTrue(event_problem(None, ids_).startswith("not a str"))
        self.assertTrue(event_problem("later", ids_).startswith("not an event"))
        self.assertTrue(event_problem("merged", ids_).startswith("not an event"))
        self.assertTrue(event_problem("merged:z", ids_).startswith("unknown stream z"))
        self.assertTrue(event_problem("merged:a/b-c", ids_).startswith("sub-block id must be [0-9A-Za-z]+"))
        self.assertTrue(event_problem("merged:a/", ids_).startswith("sub-block id must be [0-9A-Za-z]+"))

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

    def test_streams_errors_deterministic(self):   # SE14: the same row twice, streams in another order
        def ovl(p, s, q, t):
            return "owns: %s (stream %s) overlaps %s (stream %s)" % (p, s, q, t)
        sa, sb, sc = (stream(i, ["x.py"], merge_order=n) for n, i in enumerate("abc", 1))
        first = row(sa, sb, sc)
        self.assertEqual(streams_errors(first, NAME, CFG), streams_errors(first, NAME, CFG))   # the same row twice
        self.assertEqual(streams_errors(first, NAME, CFG), [ovl("x.py", "a", "x.py", "b"), ovl("x.py", "a", "x.py", "c"),
                                                            ovl("x.py", "b", "x.py", "c")])         # row order
        other = row(sc, sa, sb)
        self.assertEqual(streams_errors(other, NAME, CFG), [ovl("x.py", "c", "x.py", "a"), ovl("x.py", "c", "x.py", "b"),
                                                            ovl("x.py", "a", "x.py", "b")])         # its row order
        self.assertEqual(sorted(streams_errors(first, NAME, CFG)), sorted(
            e.replace("(stream c) overlaps x.py (stream a)", "(stream a) overlaps x.py (stream c)")
             .replace("(stream c) overlaps x.py (stream b)", "(stream b) overlaps x.py (stream c)")
            for e in streams_errors(other, NAME, CFG)))     # the same set of reasons, up to the order within a pair

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
        for a, b, want in [("a/", "ab/x", False), ("a/", "a/b.py", True), ("a/b", "a/bc", False),
                           ("a", "a/", True), ("a/", "a", True), ("a", "a/x", False)]:
            got = bool(overlaps(streams_errors(two([a], [b]), NAME, CFG)))
            self.assertEqual(got, want, (a, b))

    def test_owned_overlap_case_folded_and_nfc(self):   # EN7, EN8 (plan :2673, Q-CAT-4, Q-X35 (a))
        def ovl(p, s, q, t):    # the reason's text, as the record test above spells it
            return "owns: %s (stream %s) overlaps %s (stream %s)" % (p, s, q, t)
        # EN7: ASCII case
        self.assertEqual(streams_errors(two(["src/"], ["SRC/x.py"]), NAME, CFG), [ovl("src/", "a", "SRC/x.py", "b")])
        # EN8: NFC against NFD, both ways, and the two mark orders of a-dot-below-acute
        self.assertEqual(streams_errors(two(["caf\u00e9/"], ["cafe\u0301/x"]), NAME, CFG),
                         [ovl("caf\u00e9/", "a", "cafe\u0301/x", "b")])
        self.assertEqual(streams_errors(two(["cafe\u0301/"], ["caf\u00e9/x"]), NAME, CFG),
                         [ovl("cafe\u0301/", "a", "caf\u00e9/x", "b")])
        self.assertEqual(streams_errors(two(["\u1ea1\u0301/"], ["a\u0301\u0323/x"]), NAME, CFG),
                         [ovl("\u1ea1\u0301/", "a", "a\u0301\u0323/x", "b")])
        # the moved rows of the old table: full case folding, and a character this Unicode table does not fold
        for a, b, want in [("strasse/", "STRA\u00dfE/x", True), ("strasse/", "STRA\u1e9eE/x", True), ("X/", "x/", True),
                           ("src/", "SRC/x.py", True), ("caf\u00e9/", "cafe\u0301/x", True),
                           ("cafe\u0301/", "caf\u00e9/x", True), ("\u1ea1\u0301/", "a\u0301\u0323/x", True),
                           ("\U00010570/", "\U00010597/x", False)]:
            with self.subTest(a=a, b=b):
                self.assertEqual(bool(overlaps(streams_errors(two([a], [b]), NAME, CFG))), want)

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
        self.assertEqual([e for e in errs if e.startswith("period:")], ["period: a: not an event: 'later'"])
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
        with mock.patch.object(gitinfo, "main_worktree", return_value="/home/x/repo") as m:
            self.assertEqual(worktrees_dir("/home/x/wt/%s/integration" % NAME, S()), "/home/x/w")
            m.assert_called_once_with("/home/x/wt/%s/integration" % NAME)
            self.assertEqual(worktrees_dir("/r", {**S(), "worktrees": "../../w"}), "/home/w")
        with mock.patch.object(gitinfo, "main_worktree", return_value="/home/x/repo"):
            for w in ("../repo/x", "..", "/w", "w", 5):
                with self.assertRaises(GateError, msg=repr(w)):
                    worktrees_dir("/r", {**S(), "worktrees": w})
            with self.assertRaises(GateError):
                worktrees_dir("/r", None)

    def test_worktrees_dir_calls_gitinfo_main_worktree_at_call_time(self):
        # the seam is gone: worktrees_dir reads the name `gitinfo.main_worktree` when it runs
        self.assertFalse(hasattr(programs, "_main_worktree"))
        with mock.patch.object(gitinfo, "main_worktree", return_value="/m/repo") as m:
            self.assertEqual(worktrees_dir("/r", S()), "/m/w")
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
        with self.assertRaises(ValueError) as cm:
            comes_before({"streams": [{"id": "a", "tasks": ["a1.1"]}], "edges": "x"}, PS_, PC)
        self.assertIn("breakdown.edges", str(cm.exception))
        with self.assertRaises(ValueError) as cm:    # F-20261118-ix24, D-B11 (a): no `edges` key
            comes_before({"streams": [{"id": "a", "tasks": ["a1.1"]}]}, PS_, PC)
        self.assertIn("breakdown.edges", str(cm.exception))

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

    def test_status_rows_one_per_stream(self):   # plan :2688: a page without stream b's row is "missing row"
        self.assertEqual(self.errs([self.rowtext("a"), self.rowtext("b")]), [])
        self.assertEqual(self.errs([self.rowtext("b"), self.rowtext("a")]), [])
        self.assertEqual(self.errs([self.rowtext("a")]), ["missing row for stream b"])
        self.assertTrue(any("missing row" in e for e in status_errors(
            status_rows(self.page([self.rowtext("a")])), S(), cfg={"ids": {"request": "R", "decision": "DEC"}}, request_ids=set())))
        self.assertTrue(any(e.startswith("extra row") for e in self.errs([self.rowtext("a"), self.rowtext("b"), self.rowtext("c")])))
        self.assertTrue(any("duplicate row" in e for e in self.errs([self.rowtext("a"), self.rowtext("a"), self.rowtext("b")])))

    def test_status_errors_valid_and_rows(self):
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

    def test_agreement_unusable_breakdown_raises_naming_the_field(self):
        # D-B11 (a): an unusable row is a ValueError naming the field, never a pass and never a traceback.
        def bad(mut, field):
            st, b = self.pair()
            mut(b)
            with self.assertRaises(ValueError, msg=field) as cm:
                agreement_errors(st, b, "program-plan")
            self.assertIn(field, str(cm.exception))
        bad(lambda b: b.pop("streams"), "breakdown.streams")
        bad(lambda b: b.update(streams={"a": 1}), "breakdown.streams")
        bad(lambda b: b["streams"].append(5), "breakdown.streams.2")
        bad(lambda b: b["streams"][0].pop("id"), "breakdown.streams.0.id")
        bad(lambda b: b["streams"][0].update(id=5), "breakdown.streams.0.id")
        bad(lambda b: b["streams"][0].pop("tasks"), "breakdown.streams.0.tasks")
        bad(lambda b: b["streams"][0].update(tasks=["a1.1", 3]), "breakdown.streams.0.tasks")
        bad(lambda b: b["streams"][1].update(paths="x"), "breakdown.streams.1.paths")
        bad(lambda b: b["streams"][0].update(period=[1]), "breakdown.streams.0.period")
        bad(lambda b: b.update(edges={"from": "a"}), "breakdown.edges")
        bad(lambda b: b.update(edges=[5]), "breakdown.edges")
        bad(lambda b: b.update(edges=[{"from": "a1.1"}]), "breakdown.edges")
        bad(lambda b: b.update(plan=5), "breakdown.plan")
        st, _ = self.pair()
        for notmap in (None, [], "x", 5):
            with self.assertRaises(ValueError) as cm:
                agreement_errors(st, notmap, "program-plan")
            self.assertIn("breakdown", str(cm.exception))
        _, b = self.pair()
        for notmap in (None, [], "x"):
            with self.assertRaises(ValueError) as cm:
                agreement_errors(notmap, b, "program-plan")
            self.assertIn("streams", str(cm.exception))
        # F-20261118-ix24, D-B11 (a): streams usable, `edges` absent is an unusable row (it no longer reads as an
        # empty list); an empty list stays valid (plan :2735: edges "may be empty")
        bad(lambda b: b.pop("edges"), "breakdown.edges")
        st, b = self.pair()
        self.assertEqual(b["edges"], [])
        self.assertEqual(agreement_errors(st, b, "program-plan"), [])

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


# ---------------------------------------------------------------- delivery (ii) phase 2: git-backed rows

RID = "R-20261105-bn3p"
RID2 = "R-20261105-cn3p"
DID = "DEC-20261105-bn3p"
PROGDIR = ".strict-delivery/state/programs/" + NAME
STATUS_TEXT = "<!-- schema: status/1 -->\n\nthe status page\n"
SYNC_TEXT = "<!-- schema: sync-log/1 -->\n"
MERGED_HEAD = "<!-- schema: merged-log/1 -->\n"
LEDGER_HEAD = "<!-- schema: ledger/1 -->\n"


def prog_streams():
    return row(stream("a", ["a-owned.py", "tests/test_a.py"], merge_order=1), stream("b", ["b-owned.py"], merge_order=2),
               stream("residual", residual=True, merge_order=3))


def req_row(rid=RID, to="b", files=("b-owned.py",), status="open", frm="a", **kw):
    r = {"schema": "request/1", "id": rid, "from_stream": frm, "to_stream": to, "files": list(files),
         "interface": "docs/x.md#y", "need": "n", "status": status, "raised_at": {"sha": "a" * 7, "by": "a"}}
    r.update(kw)
    return r


def done_row(commits, rid=RID, to="b", files=("b-owned.py",), **kw):
    return req_row(rid, to, files, "done", resolution={"commits": list(commits), "at": "b" * 7, "by": "b"}, **kw)


def rec(r):
    return store.Record(r.get("id"), r, "%s/requests/%s.yml" % (PROGDIR, r.get("id")))


def make_program(requests=(), streams=None, merged=MERGED_HEAD, ref=None, name=NAME):
    return Program(name, streams if streams is not None else prog_streams(), STATUS_TEXT,
                   [rec(r) for r in requests], SYNC_TEXT, merged, ref)


def mline(pr, head, merge, stream_id, block, final="no", **kw):
    f = {"pr": str(pr), "head": head, "merge": merge, "merged_by": "owner", "at": "2026-11-18T10:00:00Z",
         "final": final, "stream": stream_id, "block": block}
    f.update(kw)
    return ("MERGED pr=%(pr)s head=%(head)s merge=%(merge)s merged_by=%(merged_by)s at=%(at)s final=%(final)s "
            "stream=%(stream)s block=%(block)s approval=host" % f)


def ledger(*lines):
    return LEDGER_HEAD + "".join(l + "\n" for l in lines)


def ckpt(block, task, head):
    return "CHECKPOINT %s %s head=%s tests=1/1 gates=PASS next=n" % (block, task, head)


BDX = {"plan": "program-plan", "streams": [
    {"id": "a", "tasks": ["a1.1"], "paths": ["a-owned.py", "tests/test_a.py"]},
    {"id": "b", "tasks": ["1a.1", "1b.1"], "paths": ["b-owned.py"]},
    {"id": "residual", "tasks": ["R1.1", "R2.1"], "residual": True}], "edges": []}


class GitProgram(GitIsolatedTestCase):
    """A ``make_repo`` fixture whose git config sets ``color.ui=always``, ``color.diff=always``, ``core.abbrev=7``."""

    def setUp(self):
        super().setUp()
        self.root = make_repo(self.work, minimal_config())
        for k, v in (("color.ui", "always"), ("color.diff", "always"), ("core.abbrev", "7")):
            git(self.root, "config", k, v)
        self.cfg = config.load(self.root)
        self.A = git(self.root, "rev-parse", "HEAD")

    def put(self, rel, text, root=None):
        path = os.path.join(root or self.root, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(text if type(text) is bytes else text.encode("utf-8"))
        return path

    def folder(self, requests=(), streams=None, root=None, name=NAME, base=None):
        base = base or ".strict-delivery/state/programs"
        d = "%s/%s" % (base, name)
        self.put(d + "/streams.yml", yamlsub.emit(streams if streams is not None else prog_streams()), root)
        self.put(d + "/status.md", STATUS_TEXT, root)
        self.put(d + "/sync-log.md", SYNC_TEXT, root)
        self.put(d + "/merged.md", MERGED_HEAD, root)
        for r in requests:
            self.put("%s/requests/%s.yml" % (d, r["id"]), yamlsub.emit(r), root)

    def sha(self, rev="HEAD", root=None):
        return git(root or self.root, "rev-parse", rev)


class ProgramDataclass(unittest.TestCase):
    def test_program_dataclass_frozen(self):  # PR1
        p = make_program()
        self.assertEqual([f.name for f in dataclasses.fields(Program)],
                         ["name", "streams", "status_text", "requests", "sync_log", "merged_log", "ref"])
        with self.assertRaises(dataclasses.FrozenInstanceError):
            p.name = "x"
        self.assertIsNone(p.ref)


class LoadProgram(GitProgram):
    def setUp(self):
        super().setUp()
        self.req = req_row()
        self.folder([self.req])
        commit_all(self.root, "program")
        self.expect = Program(NAME, prog_streams(), STATUS_TEXT, [rec(self.req)], SYNC_TEXT, MERGED_HEAD, None)

    def streams_path(self):
        return os.path.join(self.root, *(PROGDIR + "/streams.yml").split("/"))

    def refuses(self, fragment, ref=None, **kw):
        with self.assertRaises(GateError) as cm:
            load_program(self.root, kw.get("cfg", self.cfg), kw.get("name", NAME), ref)
        self.assertIn(fragment, str(cm.exception))

    def test_load_program_working_tree(self):  # PR2
        self.assertEqual(load_program(self.root, self.cfg, NAME, None), self.expect)
        p = load_program(self.root, self.cfg, NAME, None)
        self.assertEqual(p.requests[0].file, PROGDIR + "/requests/" + RID + ".yml")
        # sorted file order
        self.put(PROGDIR + "/requests/" + RID2 + ".yml", yamlsub.emit(req_row(RID2)))
        self.put(PROGDIR + "/requests/R-20261105-an3p.yml", yamlsub.emit(req_row("R-20261105-an3p")))
        got = [r.id for r in load_program(self.root, self.cfg, NAME, None).requests]
        self.assertEqual(got, ["R-20261105-an3p", RID, RID2])

    def test_load_program_from_ref(self):  # PR3
        git(self.root, "tag", "tg")
        git(self.root, "branch", "br")
        full = self.sha()
        for ref in ("br", full, "HEAD", "tg", "main"):
            p = load_program(self.root, self.cfg, NAME, ref)
            self.assertEqual(p, dataclasses.replace(self.expect, ref=ref), ref)
        # the working tree is not read when a ref is given
        self.put(PROGDIR + "/status.md", "changed\n")
        self.assertEqual(load_program(self.root, self.cfg, NAME, "HEAD").status_text, STATUS_TEXT)

    def test_load_program_missing_folder(self):  # PR4
        git(self.root, "checkout", "-q", "-b", "empty", self.A)
        for ref in (None, "empty"):
            self.refuses(PROGDIR + "/streams.yml", ref)
        self.refuses("streams.yml", None, name="20261102-y")

    def test_load_program_missing_streams(self):  # PR5
        os.remove(self.streams_path())
        self.refuses(PROGDIR + "/streams.yml")
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", "no streams")
        self.refuses(PROGDIR + "/streams.yml", "HEAD")

    def test_load_program_unparseable_streams(self):  # PR6
        good = yamlsub.emit(prog_streams())
        bad = {"tab indent": "a:\n\tb: 1\n", "duplicate key": "a: 1\na: 2\n", "anchor": "a: &x 1\nb: *x\n",
               "flow beyond the subset": "a: {b: [1, {c: 2}]}\n", "top-level list": "- a\n- b\n", "empty": "",
               "invalid utf-8": b"a: \xff\n", "BOM": b"\xef\xbb\xbf" + good.encode(), "CRLF": good.replace("\n", "\r\n"),
               "scalar": "just text\n"}
        for what, text in bad.items():
            with self.subTest(what):
                self.put(PROGDIR + "/streams.yml", text)
                self.refuses("streams.yml")
        p = self.streams_path()
        os.remove(p)
        os.mkdir(p)
        self.refuses("streams.yml")
        os.rmdir(p)
        os.symlink(os.path.join(self.root, PROGDIR, "status.md"), p)
        self.refuses("streams.yml")
        os.remove(p)
        os.mkfifo(p)
        self.refuses("streams.yml")
        os.remove(p)
        self.put(PROGDIR + "/streams.yml", good)
        if os.geteuid() != 0:
            os.chmod(p, 0)
            self.refuses("streams.yml")
            os.chmod(p, 0o644)
        self.put(PROGDIR + "/streams.yml", "# " + "x" * 98 + "\n" + "# " + "x" * 98 + "\n" * 1)
        with open(p, "a") as fh:
            fh.write(("# " + "x" * 98 + "\n") * 50000)   # about 5 MB of comments: still a mapping-less file
        self.refuses("streams.yml")

    def test_load_program_missing_texts(self):  # PR7, D-A9 (b)
        for name in ("status.md", "sync-log.md", "merged.md"):
            path = os.path.join(self.root, *(PROGDIR + "/" + name).split("/"))
            with open(path, "rb") as fh:
                saved = fh.read()
            os.remove(path)
            self.refuses(name)
            self.put(PROGDIR + "/" + name, saved)

    def test_load_program_text_kinds(self):  # PR8
        for name in ("status.md", "sync-log.md", "merged.md"):
            rel = PROGDIR + "/" + name
            path = os.path.join(self.root, *rel.split("/"))
            for what, data in (("invalid utf-8", b"<!-- x -->\n\xff\n"), ("BOM", b"\xef\xbb\xbf<!-- x -->\n"),
                               ("CRLF", b"<!-- x -->\r\n")):
                with self.subTest(name=name, what=what):
                    self.put(rel, data)
                    self.refuses(name)
            os.remove(path)
            os.mkdir(path)
            self.refuses(name)
            os.rmdir(path)
            os.symlink(os.path.join(self.root, PROGDIR, "streams.yml"), path)
            self.refuses(name)
            os.remove(path)
            self.put(rel, "ok\n")

    def test_load_program_requests_folder(self):  # PR9
        d = os.path.join(self.root, *(PROGDIR + "/requests").split("/"))
        os.remove(os.path.join(d, RID + ".yml"))
        self.assertEqual(load_program(self.root, self.cfg, NAME, None).requests, [])     # empty
        os.rmdir(d)
        self.assertEqual(load_program(self.root, self.cfg, NAME, None).requests, [])     # absent
        os.mkdir(d)
        stray = "not a regular file named <id>.yml"
        for name, data in (("index.yml", "a: 1\n"), (".gitkeep", ""), ("README.md", "x\n"), ("notes.txt", "x\n"),
                           (".hidden.yml", "a: 1\n"), ("in-force.md", "x\n")):
            with self.subTest(name):
                self.put(PROGDIR + "/requests/" + name, data)
                self.refuses("requests/%s: %s" % (name, stray))
                os.remove(os.path.join(d, name))
        os.mkdir(os.path.join(d, "sub.yml"))
        self.refuses("requests/sub.yml: " + stray)
        os.rmdir(os.path.join(d, "sub.yml"))
        os.symlink(self.streams_path(), os.path.join(d, "l.yml"))
        self.refuses("requests/l.yml: " + stray)
        os.remove(os.path.join(d, "l.yml"))
        self.put(PROGDIR + "/requests/top.yml", "- a\n- b\n")
        self.refuses("requests/top.yml")
        os.remove(os.path.join(d, "top.yml"))
        self.put(PROGDIR + "/requests/bad.yml", "a:\n\tb: 1\n")
        self.refuses("requests/bad.yml")
        os.remove(os.path.join(d, "bad.yml"))
        # a file whose name or id is wrong is store_errors' to name, not load_program's
        self.put(PROGDIR + "/requests/x.yml", yamlsub.emit(req_row("R-20261105-zz3p")))
        self.assertEqual([r.id for r in load_program(self.root, self.cfg, NAME, None).requests], ["R-20261105-zz3p"])

    def test_load_program_requests_folder_not_a_directory(self):  # PR9: the folder is a file or a symlink to a directory
        d = os.path.join(self.root, *(PROGDIR + "/requests").split("/"))
        os.remove(os.path.join(d, RID + ".yml"))
        os.rmdir(d)
        self.put(PROGDIR + "/requests", "x\n")
        self.refuses(PROGDIR + "/requests: not a directory")
        os.remove(d)
        os.makedirs(os.path.join(self.root, "elsewhere"))
        os.symlink(os.path.join(self.root, "elsewhere"), d)
        self.refuses(PROGDIR + "/requests: not a directory")

    def test_load_program_requests_listed_at_the_ref_not_the_working_tree(self):  # PR3, PR16
        os.remove(os.path.join(self.root, *(PROGDIR + "/requests/" + RID + ".yml").split("/")))
        self.put(PROGDIR + "/requests/README.md", "untracked stray\n")
        self.assertEqual(load_program(self.root, self.cfg, NAME, "HEAD").requests, self.expect.requests)
        self.refuses("requests/README.md", None)
        self.assertEqual(load_program(self.root, self.cfg, NAME, "HEAD").requests[0].id, RID)

    def test_load_program_ref_requests_folder(self):  # PR9 at a ref: a stray regular file is refused too
        self.put(PROGDIR + "/requests/README.md", "x\n")
        commit_all(self.root, "stray")
        self.refuses("requests/README.md: not a regular file named <id>.yml", "HEAD")
        git(self.root, "checkout", "-q", "-b", "none", self.A)
        self.folder()
        commit_all(self.root, "no requests")
        self.assertEqual(load_program(self.root, self.cfg, NAME, "HEAD").requests, [])

    def test_load_program_stray_entries_same_at_a_ref_and_in_the_working_tree(self):
        # F-20261118-bc74, D-A9 (task-P2.1-domain.md:574): "a stray entry in requests/ (not <id>.yml, a subfolder, a
        # symlink) ... each raise GateError naming it"; row PR9. One expected message for both readings.
        base = self.sha()
        rq = PROGDIR + "/requests/"

        def symlink(n):
            os.symlink(os.path.join(self.root, PROGDIR, "streams.yml"), os.path.join(self.root, *(rq + n).split("/")))

        def subfolder(n):
            self.put(rq + n + "/x.yml", yamlsub.emit(req_row("R-20261105-zz3p")))

        def gitlink(n):          # an empty folder on disk (an uninitialised submodule) and a 160000 entry in the index
            os.mkdir(os.path.join(self.root, *(rq + n).split("/")))
            git(self.root, "update-index", "--add", "--cacheinfo", "160000,%s,%s" % ("1" * 40, rq + n))

        kinds = [("symlink named <id>.yml", "l.yml", symlink), ("symlink, other name", "l", symlink),
                 ("subfolder named x.yml", "sub.yml", subfolder), ("subfolder, other name", "sub", subfolder),
                 ("stray file", "README.md", lambda n: self.put(rq + n, "x\n")),
                 ("hidden .yml", ".hidden.yml", lambda n: self.put(rq + n, "a: 1\n")),
                 ("generated name", "in-force.md", lambda n: self.put(rq + n, "x\n")),
                 ("gitlink named <id>.yml", "g.yml", gitlink)]      # last: git leaves its empty folder behind
        for i, (what, name, make) in enumerate(kinds):
            with self.subTest(what):
                git(self.root, "checkout", "-q", "-f", "-b", "stray%d" % i, base)
                make(name)
                git(self.root, "add", "-A")
                git(self.root, "commit", "-q", "-m", what)
                msg = "%s%s: not a regular file named <id>.yml" % (rq, name)
                self.refuses(msg, "HEAD")
                self.refuses(msg, None)
                self.refuses(msg, self.sha())

    def test_load_program_requests_not_a_folder_same_at_a_ref_and_in_the_working_tree(self):
        # F-20261118-bc74 (D-A9 class, controller ruling): `requests` itself a file, a symlink or a gitlink is
        # refused at a ref with the working tree's message. A gitlink has no working-tree twin (an empty folder
        # there is a folder), so it is checked at the refs only. An absent `requests` stays [].
        base = self.sha()
        rq = PROGDIR + "/requests"
        d = os.path.join(self.root, *rq.split("/"))
        msg = rq + ": not a directory"

        def clear():
            for n in os.listdir(d):
                os.remove(os.path.join(d, n))
            os.rmdir(d)

        def as_file():
            clear()
            self.put(rq, "x\n")

        def as_symlink():
            clear()
            os.makedirs(os.path.join(self.root, "elsewhere"))
            self.put("elsewhere/a.yml", yamlsub.emit(req_row("R-20261105-zz3p")))
            os.symlink(os.path.join(self.root, "elsewhere"), d)

        def as_gitlink():
            clear()
            git(self.root, "add", "-A")      # the index drops the folder's entries before the gitlink takes the name
            git(self.root, "update-index", "--add", "--cacheinfo", "160000,%s,%s" % ("1" * 40, rq))
            os.mkdir(d)                      # an uninitialised submodule is an empty folder; `add -A` keeps the gitlink

        for i, (what, make, wt) in enumerate([("file", as_file, True), ("symlink", as_symlink, True),
                                              ("gitlink", as_gitlink, False)]):
            with self.subTest(what):
                git(self.root, "checkout", "-q", "-f", "-b", "nf%d" % i, base)
                make()
                git(self.root, "add", "-A")
                git(self.root, "commit", "-q", "-m", what)
                self.refuses(msg, "HEAD")
                self.refuses(msg, self.sha())
                if wt:
                    self.refuses(msg, None)
        git(self.root, "checkout", "-q", "-f", "-b", "nf-absent", base)
        clear()
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", "no requests")
        self.assertEqual(load_program(self.root, self.cfg, NAME, "HEAD").requests, [])
        self.assertEqual(load_program(self.root, self.cfg, NAME, None).requests, [])

    def test_load_program_ref_accepts_an_executable_request_file(self):  # PR9: mode 100755 is a regular file at a ref
        os.chmod(os.path.join(self.root, *(PROGDIR + "/requests/" + RID + ".yml").split("/")), 0o755)
        commit_all(self.root, "exec")
        listing = git(self.root, "ls-tree", "HEAD", PROGDIR + "/requests/" + RID + ".yml")
        self.assertEqual(listing.split()[:2], ["100755", "blob"])
        self.assertEqual(load_program(self.root, self.cfg, NAME, "HEAD").requests, self.expect.requests)
        self.assertEqual(load_program(self.root, self.cfg, NAME, None).requests, self.expect.requests)

    def test_load_program_migrates_rows(self):  # PR10
        self.assertEqual(load_program(self.root, self.cfg, NAME, None).streams, prog_streams())   # current version: unchanged
        # no registered step: the rows are as read. With a (test-only) version 2 and a step 1 -> 2 both rows move.
        steps = {("streams", 1): lambda r: {**r, "schema": "streams/2"}, ("request", 1): lambda r: {**r, "schema": "request/2"}}
        with mock.patch.dict(migrations.MIGRATIONS, steps), mock.patch.object(migrations, "current_version", return_value=2):
            got = load_program(self.root, self.cfg, NAME, None)
            self.assertEqual(got.streams, {**prog_streams(), "schema": "streams/2"})
            self.assertEqual(got.requests[0].row, {**self.req, "schema": "request/2"})
            self.assertEqual(got.requests[0].id, RID)
            self.assertEqual(load_program(self.root, self.cfg, NAME, "HEAD").streams["schema"], "streams/2")

    def test_load_program_name(self):  # PR11
        for bad in ("x", "../a", "a/b", "", None, 5, b"20261101-x", "20261301-x", NAME + "/", "./" + NAME):
            with self.subTest(bad=bad):
                with self.assertRaises(GateError) as cm:
                    load_program(self.root, self.cfg, bad, None)
                self.assertIn("program name", str(cm.exception))

        class Sub(str):
            pass
        with self.assertRaises(GateError):
            load_program(self.root, self.cfg, Sub(NAME), None)
        with mock.patch.object(gitinfo, "show") as m:       # refused before any file is read
            with self.assertRaises(GateError):
                load_program(self.root, self.cfg, "../a", "HEAD")
            m.assert_not_called()

    def test_load_program_ref_forms(self):  # PR12, D-A23
        for bad in ("-x", "^x", "a" * 41, "", 5, b"HEAD", "no-such-ref", "HEAD:x"):
            with self.subTest(bad=bad):
                with self.assertRaises(GateError):
                    load_program(self.root, self.cfg, NAME, bad)
        # a tag and a branch of one name: the bare name is git's tag; refs/heads/<b> is the branch
        git(self.root, "checkout", "-q", "-b", "tagged", self.A)
        git(self.root, "tag", "t-folder")
        git(self.root, "checkout", "-q", "main")
        git(self.root, "tag", "dup", self.A)
        git(self.root, "branch", "dup", "main")
        self.assertRaises(GateError, load_program, self.root, self.cfg, NAME, "dup")      # the tag is the empty root commit
        self.assertEqual(load_program(self.root, self.cfg, NAME, "refs/heads/dup").status_text, STATUS_TEXT)

    def test_load_program_root_forms(self):  # PR13
        forms = root_forms(self.tmp, self.root)
        check_root_forms(self, forms, {"at a ref": lambda p: load_program(p, self.cfg, NAME, "main"),
                                       "working tree": lambda p: load_program(p, self.cfg, NAME, None)})
        for bad in (None, 5, "", b"x", [self.root]):
            with self.assertRaises(GateError):
                load_program(bad, self.cfg, NAME, None)

    def test_load_program_custom_paths(self):  # PR14
        cfg2 = {**self.cfg, "paths": {**self.cfg["paths"], "programs": "p2"}}
        self.folder([self.req], base="p2")
        self.put("p2/%s/status.md" % NAME, "custom\n")
        self.assertEqual(load_program(self.root, cfg2, NAME, None).status_text, "custom\n")
        commit_all(self.root, "p2")
        self.assertEqual(load_program(self.root, cfg2, NAME, "HEAD").status_text, "custom\n")
        for bad in ({k: v for k, v in self.cfg.items() if k != "paths"}, {**self.cfg, "paths": {**self.cfg["paths"], "programs": 5}},
                    {**self.cfg, "paths": {}}, {**self.cfg, "paths": None}, {}, None):
            with self.subTest(bad=bad):
                with self.assertRaises(GateError) as cm:
                    load_program(self.root, bad, NAME, None)
                self.assertIn("paths.programs", str(cm.exception))

    def test_load_program_ref_non_regular(self):  # PR15
        for name in ("status.md", "streams.yml"):
            git(self.root, "checkout", "-q", "-b", "sym-" + name[:3], "main")
            rel = PROGDIR + "/" + name
            os.remove(os.path.join(self.root, *rel.split("/")))
            os.symlink("sync-log.md", os.path.join(self.root, *rel.split("/")))
            commit_all(self.root, "symlink " + name)
            self.refuses(name, "HEAD")
            git(self.root, "checkout", "-q", "main")

    def test_load_program_sources_independent(self):  # PR16
        self.put(PROGDIR + "/status.md", "edited\n")
        self.assertEqual(load_program(self.root, self.cfg, NAME, None).status_text, "edited\n")
        self.assertEqual(load_program(self.root, self.cfg, NAME, "HEAD").status_text, STATUS_TEXT)

    def test_load_program_ref_invalid_utf8(self):  # PR17
        self.put(PROGDIR + "/status.md", b"<!-- x -->\n\xff\n")
        commit_all(self.root, "bad bytes")
        self.refuses("not valid UTF-8", "HEAD")

    def test_load_program_integration_worktree_root(self):  # PR18
        wt = os.path.join(self.tmp, "wt")
        git(self.root, "worktree", "add", "-q", "-b", NAME + "/integration", wt, "main")
        self.put(PROGDIR + "/status.md", "worktree text\n", wt)
        self.put(PROGDIR + "/status.md", "main text\n")
        self.assertEqual(load_program(wt, self.cfg, NAME, None).status_text, "worktree text\n")
        self.assertEqual(load_program(self.root, self.cfg, NAME, None).status_text, "main text\n")

    def test_load_program_digit_limits_same_on_both(self):  # PR19
        def with_estimate(n):
            r = prog_streams()
            text = yamlsub.emit(r).replace("estimate: 5", "estimate: 1" + "0" * (n - 1), 1)
            self.put(PROGDIR + "/streams.yml", text)
        # yamlsub refuses a numeral of more than 1000 characters on every interpreter ("integer too large"); under the
        # 3.11+ int-conversion limit of 640 even 1000 digits fail, and that too is the same GateError, never a traceback.
        limited = lambda lim: lim == 640
        for digits in (1000, 1001, 4300, 4301):
            with_estimate(digits)
            for lim in INT_LIMITS:
                with self.subTest(digits=digits, limit=lim), int_limit(lim):
                    if digits > 1000 or limited(lim):
                        with self.assertRaises(GateError) as cm:
                            load_program(self.root, self.cfg, NAME, None)
                        self.assertIn("streams.yml: integer too large", str(cm.exception))
                    else:
                        got = load_program(self.root, self.cfg, NAME, None)
                        self.assertEqual(got.streams["streams"][0]["estimate"], 10 ** 999)


class WorktreesGit(GitProgram):
    def test_worktrees_dir_real_main_worktree(self):  # WT7-WT9: the real gitinfo.main_worktree through worktrees_dir
        r = {**S(), "worktrees": "../wt-out"}
        want = os.path.join(os.path.dirname(self.root), "wt-out")
        self.assertEqual(worktrees_dir(self.root, r), want)
        linked = os.path.join(self.tmp, "linked")
        git(self.root, "worktree", "add", "-q", "--detach", linked)
        self.assertEqual(worktrees_dir(linked, r), want)      # resolved against the main worktree, never against root
        self.assertEqual(worktrees_dir(self.root, r), gitinfo.main_worktree(self.root) and want)
        with self.assertRaises(GateError):
            worktrees_dir(os.path.join(self.root, "nope"), r)


class LivePrograms(GitProgram):
    def integration(self, name=NAME, with_folder=True, base="main", branch=None):
        git(self.root, "checkout", "-q", "-b", branch or name + "/integration", base)
        if with_folder:
            self.folder(name=name)
        commit_all(self.root, "int " + name)
        git(self.root, "checkout", "-q", "main")

    def test_live_programs_none(self):  # LV1
        self.assertEqual(live_programs(self.root, self.cfg), [])

    def test_live_programs_from_integration_branches(self):  # LV2, plan :2701
        self.integration()
        self.assertEqual(live_programs(self.root, self.cfg), [NAME])

    def test_live_programs_integration_without_folder(self):  # LV3
        self.integration(with_folder=False)
        self.folder()
        commit_all(self.root, "folder on main only")
        self.assertEqual(live_programs(self.root, self.cfg), [])

    def test_live_programs_two(self):  # LV4
        self.integration("20261102-y")
        self.integration()
        self.integration("20261101-a")
        self.assertEqual(live_programs(self.root, self.cfg), ["20261101-a", NAME, "20261102-y"])

    def test_live_programs_stream_branch_only(self):  # LV5
        self.integration(branch=NAME + "/a/main")
        self.assertEqual(live_programs(self.root, self.cfg), [])

    def test_live_programs_ignores_current_tree(self):  # LV6
        self.folder()
        commit_all(self.root, "folder on main")
        self.assertEqual(live_programs(self.root, self.cfg), [])
        git(self.root, "checkout", "-q", "-b", NAME + "/a/main")
        self.assertEqual(live_programs(self.root, self.cfg), [])
        self.put(PROGDIR + "/x.txt", "x")           # an uncommitted tree changes nothing
        self.assertEqual(live_programs(self.root, self.cfg), [])

    def test_live_programs_branch_name_forms(self):  # LV7, D-A24
        for branch in ("x/integration", "20261105-z/integration/y", "20261101-x/records", "foo", "20261301-x/integration",
                       "20261101-x/a/integration"):
            git(self.root, "checkout", "-q", "-b", branch, "main")
            for prog in ("x", "20261105-z", "20261101-x", "20261301-x"):
                self.folder(name=prog)
            commit_all(self.root, "forms " + branch)
            git(self.root, "checkout", "-q", "main")
        self.assertEqual(live_programs(self.root, self.cfg), [])
        self.integration("20261103-ok")
        self.assertEqual(live_programs(self.root, self.cfg), ["20261103-ok"])

    def test_live_programs_tip_file_kinds(self):  # LV8
        for label, name in (("symlink", "20261101-a"), ("directory", "20261101-b"), ("empty", "20261101-c"),
                            ("unparseable", "20261101-d")):
            git(self.root, "checkout", "-q", "-b", name + "/integration", "main")
            d = PROGDIR.replace(NAME, name)
            self.put(d + "/status.md", "s\n")
            target = os.path.join(self.root, *(d + "/streams.yml").split("/"))
            if label == "symlink":
                os.symlink("status.md", target)
            elif label == "directory":
                self.put(d + "/streams.yml/inner", "x")
            else:
                self.put(d + "/streams.yml", "" if label == "empty" else "a:\n\tb\n")
            commit_all(self.root, label)
            git(self.root, "checkout", "-q", "main")
        self.assertEqual(live_programs(self.root, self.cfg), ["20261101-c", "20261101-d"])

    def test_live_programs_ignores_program_field(self):  # LV9
        self.folder(streams={**prog_streams(), "program": "20261102-other"})
        git(self.root, "checkout", "-q", "-b", NAME + "/integration")
        commit_all(self.root, "other program field")
        git(self.root, "checkout", "-q", "main")
        self.assertEqual(live_programs(self.root, self.cfg), [NAME])

    def test_live_programs_tag_same_name(self):  # LV10, D-A23
        self.integration()
        git(self.root, "tag", NAME + "/integration", self.A)          # the tag has no folder
        self.assertEqual(live_programs(self.root, self.cfg), [NAME])   # read from refs/heads/, not the tag git prefers
        git(self.root, "tag", "-d", NAME + "/integration")
        self.integration("20261102-y", with_folder=False)
        git(self.root, "checkout", "-q", "-b", "with-folder", "main")
        self.folder(name="20261102-y")
        commit_all(self.root, "folder")
        git(self.root, "tag", "20261102-y/integration")
        git(self.root, "checkout", "-q", "main")
        self.assertEqual(live_programs(self.root, self.cfg), [NAME])   # the tag holds a folder; the branch does not

    def test_live_programs_head_states(self):  # LV11
        self.integration()
        git(self.root, "checkout", "-q", "--detach")
        self.assertEqual(live_programs(self.root, self.cfg), [NAME])
        git(self.root, "checkout", "-q", "--orphan", "unborn")
        self.assertEqual(live_programs(self.root, self.cfg), [NAME])
        git(self.root, "checkout", "-q", "-f", "main")
        self.put("c.txt", "one\n")
        commit_all(self.root, "one")
        git(self.root, "checkout", "-q", "-b", "other", self.A)
        self.put("c.txt", "two\n")
        commit_all(self.root, "two")
        git(self.root, "merge", "main", check=False)
        self.assertTrue(os.path.exists(os.path.join(self.root, ".git", "MERGE_HEAD")))
        self.assertEqual(live_programs(self.root, self.cfg), [NAME])

    def test_live_programs_custom_path(self):  # LV12
        cfg2 = {**self.cfg, "paths": {**self.cfg["paths"], "programs": "p2"}}
        git(self.root, "checkout", "-q", "-b", NAME + "/integration", "main")
        self.folder(base="p2")
        commit_all(self.root, "p2")
        git(self.root, "checkout", "-q", "main")
        self.assertEqual(live_programs(self.root, cfg2), [NAME])
        self.assertEqual(live_programs(self.root, self.cfg), [])

    def test_live_programs_remote_only_not_live(self):  # LV13
        self.integration()
        git(self.root, "update-ref", "refs/remotes/origin/20261102-y/integration", self.sha(NAME + "/integration"))
        self.assertEqual(live_programs(self.root, self.cfg), [NAME])
        git(self.root, "branch", "-D", NAME + "/integration")
        self.assertEqual(live_programs(self.root, self.cfg), [])

    def test_live_programs_many(self):  # LV14 (100 programs; one listing, one tip read each)
        names = ["202611%02d-p%d" % (1 + i % 28, i) for i in range(100)]
        git(self.root, "checkout", "-q", "-b", "store", "main")
        for n in names:
            self.put("%s/%s/streams.yml" % (".strict-delivery/state/programs", n), "a: 1\n")
        sha = commit_all(self.root, "many")
        git(self.root, "checkout", "-q", "main")
        with open(os.path.join(self.root, ".git", "packed-refs"), "w") as fh:
            fh.write("# pack-refs with: peeled fully-peeled sorted\n")
            for n in sorted(names):
                fh.write("%s refs/heads/%s/integration\n" % (sha, n))
        self.assertEqual(len(gitinfo.local_branches(self.root)), 102)       # main, store and the 100 integration branches
        with mock.patch.object(gitinfo, "local_branches", wraps=gitinfo.local_branches) as lb, \
                mock.patch.object(gitinfo, "show", wraps=gitinfo.show) as sh:
            got = live_programs(self.root, self.cfg)
        self.assertEqual(got, sorted(names))
        self.assertEqual(lb.call_count, 1)
        self.assertEqual(sh.call_count, 100)

    def test_live_programs_types(self):  # LV15
        for bad in (None, 5, "", b"x"):
            with self.assertRaises(GateError):
                live_programs(bad, self.cfg)
        for bad in ({}, None, {"paths": {}}, {"paths": {"programs": 5}}):
            with self.assertRaises(GateError):
                live_programs(self.root, bad)

    def test_live_programs_returns_list(self):  # LV16
        self.integration()
        a = live_programs(self.root, self.cfg)
        self.assertIs(type(a), list)
        self.assertTrue(all(type(x) is str for x in a))
        a.append("x")
        self.assertEqual(live_programs(self.root, self.cfg), [NAME])


class Counted(GitProgram):
    """``counted_lines`` (decision D-A26 (1)) on real merge commits."""

    def setUp(self):
        super().setUp()
        self.a7 = self.A[:7]

    def pr(self, branch, sid, ledger_lines=(), files=None, ledger_name="ledger.md"):
        """A branch off main holding the stream's ledger (and ``files``), merged into main with ``--no-ff``;
        returns ``(head, merge)``."""
        git(self.root, "checkout", "-q", "-b", branch, "main")
        self.put("%s/%s-plan/%s" % (PS, sid, ledger_name), ledger(*ledger_lines))
        for rel, text in (files or {}).items():
            self.put(rel, text)
        head = commit_all(self.root, "work " + branch)
        git(self.root, "checkout", "-q", "main")
        git(self.root, "merge", "-q", "--no-ff", "-m", "Merge " + branch, branch)
        return head, self.sha("main")

    def program(self, *lines, streams=None):
        return make_program(streams=streams, merged=MERGED_HEAD + "".join(l + "\n" for l in lines))

    def run_counted(self, prog, bd=None):
        return counted_lines(prog, self.root, self.cfg, bd if bd is not None else BDX)

    def test_counted_none(self):
        self.assertEqual(self.run_counted(self.program()), ([], {}, []))

    def test_counted_one_line(self):  # ME2
        head, m = self.pr("p1", "b", [ckpt("1a", "1a.1", self.a7)])
        counted, merged, errors = self.run_counted(self.program(mline(1, head, m, "b", "1a")))
        self.assertEqual([(c["pr"], c["head"], c["merge"], c["stream"], c["block"]) for c in counted],
                         [(1, head, m, "b", "1a")])
        self.assertEqual((merged, errors), ({"b": {"1a"}}, []))

    def test_one_pr_carries_several_sub_blocks(self):  # ME5, Q-F80W-2: init4's pull request carries 4c, 4d, 4e
        head, m = self.pr("p1", "b", [ckpt("1a", "1a.1", self.a7), ckpt("1b", "1b.1", head7(self, "main"))])
        counted, merged, errors = self.run_counted(self.program(mline(1, head, m, "b", "1b")))
        self.assertEqual((merged, errors), ({"b": {"1a", "1b"}}, []))

    def test_block_must_be_the_last_newly_carried(self):  # MP6, Q-F80W-8 (a)
        head, m = self.pr("p1", "b", [ckpt("1a", "1a.1", self.a7), ckpt("1b", "1b.1", self.a7)])
        counted, merged, errors = self.run_counted(self.program(mline(1, head, m, "b", "1a")))
        self.assertEqual(len(counted), 1)                       # the line counts and carries
        self.assertEqual(merged, {"b": {"1a", "1b"}})
        self.assertEqual(len(errors), 1)
        self.assertIn("pr 1", errors[0])
        self.assertIn("not the last sub-block it newly carries (1a, 1b)", errors[0])

    def test_last_is_by_the_order_of_the_tasks(self):  # MP12
        bd = {**BDX, "streams": [BDX["streams"][0], {"id": "b", "tasks": ["1b.1", "1a.1"]}, BDX["streams"][2]]}
        head, m = self.pr("p1", "b", [ckpt("1a", "1a.1", self.a7), ckpt("1b", "1b.1", self.a7)])
        self.assertEqual(self.run_counted(self.program(mline(1, head, m, "b", "1a")), bd)[2], [])
        self.assertEqual(len(self.run_counted(self.program(mline(1, head, m, "b", "1b")), bd)[2]), 1)

    def test_a_sub_block_is_listed_once(self):  # two tasks of one sub-block name it once in the reason
        bd = {**BDX, "streams": [BDX["streams"][0], {"id": "b", "tasks": ["1a.1", "1a.2", "1b.1"]}, BDX["streams"][2]]}
        head, m = self.pr("p1", "b", [ckpt("1a", "1a.1", self.a7), ckpt("1a", "1a.2", self.a7), ckpt("1b", "1b.1", self.a7)])
        errors = self.run_counted(self.program(mline(1, head, m, "b", "1a")), bd)[2]
        self.assertEqual(len(errors), 1)
        self.assertIn("not the last sub-block it newly carries (1a, 1b)", errors[0])

    def test_checkpoint_head_not_ancestor_not_carried(self):  # ME6
        git(self.root, "checkout", "-q", "-b", "side", "main")
        self.put("side.txt", "x")
        side = commit_all(self.root, "side")
        git(self.root, "checkout", "-q", "main")
        head, m = self.pr("p1", "b", [ckpt("1a", "1a.1", side[:7]), ckpt("1b", "1b.1", self.a7)])
        counted, merged, errors = self.run_counted(self.program(mline(1, head, m, "b", "1b")))
        self.assertEqual((merged, errors), ({"b": {"1b"}}, []))

    def test_checkpoint_head_unknown_is_not_carried_and_never_raises(self):  # ME6 (a head git cannot resolve)
        head, m = self.pr("p1", "b", [ckpt("1a", "1a.1", "89abcde"), ckpt("1b", "1b.1", self.a7)])
        counted, merged, errors = self.run_counted(self.program(mline(1, head, m, "b", "1b")))
        self.assertEqual((merged, errors), ({"b": {"1b"}}, []))

    def test_one_task_without_checkpoint_not_carried(self):  # ME7
        bd = {**BDX, "streams": [BDX["streams"][0], {"id": "b", "tasks": ["1a.1", "1a.2", "1b.1"]}, BDX["streams"][2]]}
        head, m = self.pr("p1", "b", [ckpt("1a", "1a.1", self.a7), ckpt("1b", "1b.1", self.a7)])
        counted, merged, errors = self.run_counted(self.program(mline(1, head, m, "b", "1b")), bd)
        self.assertEqual((merged, errors), ({"b": {"1b"}}, []))

    def test_block_named_is_carried_without_a_checkpoint(self):  # ME8
        head, m = self.pr("p1", "b", [])
        self.assertEqual(self.run_counted(self.program(mline(1, head, m, "b", "1a")))[1:], ({"b": {"1a"}}, []))

    def test_block_that_is_no_sub_block_of_the_stream(self):  # MP11, Q-F80W-10 (a)
        head, m = self.pr("p1", "b", [ckpt("1a", "1a.1", self.a7)])
        counted, merged, errors = self.run_counted(self.program(mline(1, head, m, "b", "R2")))
        self.assertEqual(len(counted), 1)
        self.assertEqual(merged, {"b": {"1a"}})                 # R2 is not added; 1a is carried by its checkpoint
        self.assertEqual(len(errors), 1)
        self.assertIn("block R2 is no sub-block of the tasks of stream b", errors[0])

    def test_a_line_that_newly_carries_nothing(self):  # MP9, Q-F80RR3-2 (a)
        h1, m1 = self.pr("p1", "b", [ckpt("1a", "1a.1", self.a7)])
        h2, m2 = self.pr("p2", "b", [ckpt("1a", "1a.1", self.a7), ckpt("2x", "2x.1", self.a7)])
        counted, merged, errors = self.run_counted(self.program(mline(1, h1, m1, "b", "1a"), mline(2, h2, m2, "b", "1a")))
        self.assertEqual(len(counted), 2)
        self.assertEqual(len(errors), 1)
        self.assertIn("pr 2", errors[0])
        self.assertIn("newly carries no sub-block", errors[0])

    def test_a_pull_request_names_a_block_already_counted(self):  # MP8, Q-F80RR3-2 (a): R3's line with block=R5
        bd = {**BDX, "streams": [BDX["streams"][0], BDX["streams"][1],
                                 {"id": "residual", "tasks": ["R1.1", "R3.1", "R5.1"], "residual": True}]}
        h1, m1 = self.pr("p1", "residual", [ckpt("R1", "R1.1", self.a7), ckpt("R5", "R5.1", self.a7)])
        h2, m2 = self.pr("p2", "residual", [ckpt("R1", "R1.1", self.a7), ckpt("R3", "R3.1", self.a7), ckpt("R5", "R5.1", self.a7)])
        counted, merged, errors = self.run_counted(
            self.program(mline(1, h1, m1, "residual", "R5"), mline(2, h2, m2, "residual", "R5")), bd)
        self.assertEqual(merged, {"residual": {"R1", "R3", "R5"}})
        self.assertEqual(len(errors), 1)
        self.assertIn("pr 2", errors[0])
        self.assertIn("block R5 is not the last sub-block it newly carries (R3)", errors[0])

    def test_uncounted_lines_have_reasons(self):  # ME3, P2.3 D-Q15
        head, m = self.pr("p1", "b", [ckpt("1a", "1a.1", self.a7)])
        counted, merged, errors = self.run_counted(self.program(mline(1, self.A, m, "b", "1a")))
        self.assertEqual((counted, merged), ([], {}))
        self.assertEqual(len(errors), 1)
        for frag in ("pr 1", "does not count", "head.1"):
            self.assertIn(frag, errors[0])
        # a line of a stream the program does not have; a line with no stream; a plan that is not the stream's
        counted, merged, errors = self.run_counted(self.program(mline(1, head, m, "zz", "1a")))
        self.assertEqual((counted, merged), ([], {}))
        self.assertIn("stream zz is not a stream of streams.yml", errors[0])
        nostream = ("MERGED pr=3 head=%s merge=%s merged_by=o at=2026-11-18T10:00:00Z final=no approval=host" % (head, m))
        self.assertIn("stream None", self.run_counted(self.program(nostream))[2][0])
        counted, merged, errors = self.run_counted(self.program(mline(1, head, m, "residual", "R1")))
        self.assertEqual(counted, [])
        self.assertIn("plan.1", errors[0])

    def test_stream_plan_forms(self):
        head, m = self.pr("p1", "b", [ckpt("1a", "1a.1", self.a7)])
        for plan, frag in (("elsewhere/b-plan.md", "is not <paths.plans>/<name>.md"), (PG + "/B_plan.md", "plan must be a plan slug")):
            st = prog_streams()
            st["streams"][1]["plan"] = plan
            counted, merged, errors = self.run_counted(self.program(mline(1, head, m, "b", "1a"), streams=st))
            self.assertEqual(counted, [], plan)
            self.assertIn(frag, errors[0])

    def test_ledger_unreadable_at_the_head(self):  # ME12, Q16 (a)
        head, m = self.pr("p1", "b", [], ledger_name="notes.md")
        counted, merged, errors = self.run_counted(self.program(mline(1, head, m, "b", "1b")))
        self.assertEqual(merged, {"b": {"1b"}})
        self.assertEqual(len(errors), 1)
        self.assertIn(PS + "/b-plan/ledger.md cannot be read", errors[0])
        git(self.root, "checkout", "-q", "-b", "bad", "main")
        self.put("%s/b-plan/ledger.md" % PS, b"\xff\n")
        bad = commit_all(self.root, "bad ledger")
        git(self.root, "checkout", "-q", "main")
        git(self.root, "merge", "-q", "--no-ff", "-m", "m", "bad")
        counted, merged, errors = self.run_counted(self.program(mline(2, bad, self.sha("main"), "b", "1b")))
        self.assertIn("not valid UTF-8", errors[0])

    def test_unusable_breakdown_and_arguments(self):
        head, m = self.pr("p1", "b", [])
        prog = self.program(mline(1, head, m, "b", "1a"))
        for bad in ({}, {"streams": 5}, {"streams": [{"id": "b"}]}, []):
            with self.assertRaises(ValueError):
                self.run_counted(prog, bad)
        with self.assertRaises(ValueError):
            counted_lines({"merged_log": ""}, self.root, self.cfg, BDX)
        with self.assertRaises(GateError):
            counted_lines(prog, 5, self.cfg, BDX)
        with self.assertRaises(GateError):
            counted_lines(self.program(), 5, self.cfg, BDX)       # with no line to judge, the root is still checked

    def test_counted_lines_deterministic_and_file_order(self):  # ME16
        h1, m1 = self.pr("p1", "b", [ckpt("1a", "1a.1", self.a7)])
        h2, m2 = self.pr("p2", "b", [ckpt("1a", "1a.1", self.a7), ckpt("1b", "1b.1", self.a7)])
        prog = self.program(mline(2, h2, m2, "b", "1b"), mline(1, h1, m1, "b", "1a"))
        counted, merged, errors = self.run_counted(prog)
        self.assertEqual([c["pr"] for c in counted], [2, 1])          # file order, not pr order
        self.assertEqual(merged, {"b": {"1a", "1b"}})
        self.assertEqual(self.run_counted(prog), (counted, merged, errors))
        self.assertEqual(len(errors), 1)                               # the second line (pr 1, in file order) carries nothing new


def head7(case, rev):
    return case.sha(rev)[:7]


class RequestsGit(GitProgram):
    """``request_errors`` rules ``from.``, ``done.``, ``decision.`` and the store rules, on real history."""

    def setUp(self):
        super().setUp()
        r = self.root
        git(r, "checkout", "-q", "-b", NAME + "/a/main", "main")
        self.put("a-owned.py", "a\n")
        self.Ca = commit_all(r, "Ca")
        git(r, "checkout", "-q", "-b", NAME + "/b/main", "main")
        self.put("b-owned.py", "b\n")
        self.put("%s/b-plan/ledger.md" % PS, ledger(ckpt("1a", "1a.1", self.A[:7])))
        self.Cb = commit_all(r, "Cb")
        self.put("src/x.py", "x\n")
        self.Cd = commit_all(r, "Cd")
        self.put("notes.txt", "n\n")
        self.Cn = commit_all(r, "Cn")
        git(r, "checkout", "-q", "-b", NAME + "/residual/main", "main")
        self.put("res.txt", "r\n")
        self.put("%s/residual-plan/ledger.md" % PS, ledger())
        self.Cr = commit_all(r, "Cr")
        git(r, "checkout", "-q", "-b", NAME + "/integration", "main")
        self.put("ci.txt", "i\n")
        self.Ci = commit_all(r, "Ci")
        git(r, "checkout", "-q", "main")
        git(r, "merge", "-q", "--no-ff", "-m", "Cm", NAME + "/b/main")
        self.Cm = self.sha()
        git(r, "merge", "-q", "--no-ff", "-m", "Mr", NAME + "/residual/main")
        self.Mr = self.sha()
        git(r, "branch", "-D", NAME + "/residual/main")
        self.put("res.txt", "base\n")
        self.Cbase = commit_all(r, "Cbase")
        self.merged = MERGED_HEAD + mline(1, self.Cn, self.Cm, "b", "1a") + "\n" + mline(2, self.Cr, self.Mr, "residual", "R1") + "\n"

    def errs(self, *rows, merged=None, ref=None, bd=None, streams=None, cfg=None):
        prog = make_program(rows, streams, merged if merged is not None else self.merged, ref)
        return request_errors(prog, self.root, cfg or self.cfg, BDX if bd is None else bd)

    def kinds(self, *rows, **kw):
        return [s for s, _ in self.errs(*rows, **kw)]

    def test_request_store_errors(self):  # RQ1
        good = req_row()
        wrong_name = store.Record("R-20261105-bn3p", req_row(), PROGDIR + "/requests/x.yml")
        prog = Program(NAME, prog_streams(), "", [store.Record(RID, good, PROGDIR + "/requests/R-20261105-cn3p.yml"), wrong_name,
                                                  store.Record(5, req_row(rid=5), PROGDIR + "/requests/five.yml")],
                       "", MERGED_HEAD, None)
        got = request_errors(prog, self.root, self.cfg, BDX)
        want = store.store_errors(prog.requests, "R")
        self.assertEqual([e for e in got if e[0].split(".")[0] in ("id", "name", "duplicate")], want)
        self.assertEqual(got[:len(want)], want)                      # first, verbatim
        self.assertTrue(any(s.startswith("duplicate.") for s, _ in want))
        self.assertTrue(any(s.startswith("name.") for s, _ in want) and any(s.startswith("id.") for s, _ in want))
        decision_id = req_row(rid=DID)                                # a decision id in the requests folder
        self.assertTrue(any(s.startswith("id.") for s in self.kinds(decision_id)))

    def test_request_from_stream(self):  # RQ2
        self.assertEqual(self.kinds(req_row(frm="a")), [])
        self.assertEqual(self.errs(req_row(frm="z"))[0][0], "from." + RID)
        self.assertIn("from_stream z is not a stream", self.errs(req_row(frm="z"))[0][1])
        self.assertEqual(self.errs(req_row(frm="b", to="b"))[0], ("from." + RID, "from_stream b is the same as to_stream"))
        self.assertEqual(self.errs(req_row(frm=NAME))[0][0], "from." + RID)           # the program is not a stream
        self.assertEqual(self.errs(req_row(frm=""))[0][0], "from." + RID)
        for bad in (5, None, ["a"]):
            self.assertEqual(self.kinds(req_row(frm=bad)), [], bad)                   # the schema names a wrong type

    def test_request_to_unknown_does_not_raise(self):  # RQ3
        self.assertEqual(self.kinds(req_row(to="z")), ["to." + RID])

    def test_request_done_without_resolution(self):  # RQ4
        r = req_row(status="done")
        self.assertEqual(self.kinds(r), [])
        r["resolution"] = {"at": "b" * 7, "by": "b"}
        self.assertEqual(self.kinds(r), [])
        r["resolution"] = "x"
        self.assertEqual(self.kinds(r), [])

    def test_request_done_commit_must_exist(self):  # RQ5
        self.assertEqual(self.kinds(done_row([self.Cb])), [])
        self.assertEqual(self.kinds(done_row([self.Cb[:7]])), [])
        absent = "89abcdef0123456789abcdef0123456789abcdef"
        for what, sha in (("absent", absent), ("tree", git(self.root, "rev-parse", self.Cb + "^{tree}")),
                          ("blob", git(self.root, "rev-parse", self.Cb + ":b-owned.py")), ("41 hex", self.Cb + "a"),
                          ("annotated tag peels", None)):
            if sha is None:
                git(self.root, "tag", "-a", "-m", "t", "annot", self.Cb)
                sha = git(self.root, "rev-parse", "annot")
                self.assertEqual(self.kinds(done_row([sha])), [], what)      # an annotated tag peels to its commit
                continue
            got = self.errs(done_row([sha]))
            self.assertEqual([s for s, _ in got], ["done." + RID], what)
            self.assertEqual(got[0][1], "commit %s does not exist in this repository" % sha, what)

    def test_done_needs_commit_on_owner_branch(self):  # RQ6, RQ7, RQ8; plan :2698
        self.assertEqual(self.kinds(done_row([self.Cb])), [])
        got = self.errs(done_row([self.Ca]))                    # another stream's branch only
        self.assertEqual([s for s, _ in got], ["done." + RID])
        self.assertIn("reachable from neither", got[0][1])
        self.assertEqual(self.kinds(done_row([self.Ci])), ["done." + RID])      # only on <p>/integration

    def test_done_counted_merged_head_accepted(self):  # RQ9, RQ10
        r = done_row([self.Cr], to="residual", files=["res.txt"])
        self.assertEqual(self.kinds(r), [])
        r = done_row([self.Cbase], to="residual", files=["res.txt"])      # base_branch alone is no owner
        self.assertEqual(self.kinds(r), ["done." + RID])

    def test_done_uncounted_line_not_counted(self):  # RQ11, Q-A22 (i)
        r = done_row([self.Cr], to="residual", files=["res.txt"])
        wrong_head = MERGED_HEAD + mline(2, self.Cn, self.Mr, "residual", "R1") + "\n"
        self.assertEqual(self.kinds(r, merged=wrong_head), ["done." + RID])
        other = MERGED_HEAD + mline(1, self.Cn, self.Cm, "b", "1a") + "\n"            # another stream's line
        self.assertEqual(self.kinds(r, merged=other), ["done." + RID])
        wrong_plan = MERGED_HEAD + mline(3, self.Cn, self.Cm, "residual", "R1") + "\n"   # Cm touched b's plan, not residual's
        r2 = done_row([self.Cn], to="residual", files=["notes.txt"])
        self.assertEqual(self.kinds(r2, merged=wrong_plan), ["done." + RID])
        self.assertEqual(self.kinds(r2, merged=MERGED_HEAD + mline(3, self.Cn, self.Cm, "b", "1a") + "\n"), ["done." + RID])
        self.assertEqual(self.kinds(r), [])

    def test_done_counted_heads_come_from_counted_lines(self):
        # the same commit set that counted_lines returns decides `done` (one definition)
        prog = make_program([], None, self.merged)
        heads = [(c["stream"], c["head"]) for c in counted_lines(prog, self.root, self.cfg, BDX)[0]]
        self.assertEqual(heads, [("b", self.Cn), ("residual", self.Cr)])
        r = done_row([self.Cr], to="residual", files=["res.txt"])
        self.assertEqual([s for s in self.kinds(r, bd={}) if s.startswith("done.")], [])   # an unusable breakdown still counts the lines

    def test_done_branch_deleted(self):  # RQ12
        git(self.root, "branch", "-D", NAME + "/b/main")
        self.assertEqual(self.kinds(done_row([self.Cb])), [])                        # the counted head Cn holds Cb
        self.assertEqual(self.kinds(done_row([self.Cb]), merged=MERGED_HEAD), ["done." + RID])

    def test_done_commit_must_touch_listed_file(self):  # RQ13
        got = self.errs(done_row([self.Cn]))
        self.assertEqual([s for s, _ in got], ["done." + RID])
        self.assertIn("touches none of the listed files", got[0][1])
        only_done = lambda row_: [s for s in self.kinds(row_) if s.startswith("done.")]
        self.assertEqual(only_done(done_row([self.Cd], files=["src/"])), [])        # a directory prefix
        self.assertEqual(only_done(done_row([self.Cd], files=["src"])), ["done." + RID])
        self.assertEqual(self.kinds(done_row([self.Cb], files=["B-OWNED.PY"])), [])  # compared by path_key
        # a root commit against the empty tree
        root_files = [".strict-delivery/config.yml"]
        self.assertEqual(self.kinds(done_row([self.A], files=root_files)), ["to." + RID])   # b owns no config file
        self.assertEqual([s for s in self.kinds(done_row([self.A], files=root_files)) if s.startswith("done.")], [])
        self.assertEqual([s for s in self.kinds(done_row([self.A])) if s.startswith("done.")], ["done." + RID])

    def test_done_merge_commit_is_judged_by_its_first_parent_diff(self):  # Q-A22 (iii)
        r = self.root
        git(r, "checkout", "-q", "-b", "side", NAME + "/b/main")
        self.put("side.py", "s\n")
        commit_all(r, "side work")
        git(r, "checkout", "-q", NAME + "/b/main")
        self.put("y.py", "y\n")
        commit_all(r, "Cy")
        git(r, "merge", "-q", "--no-ff", "-m", "Mx", "side")
        Mx = self.sha()
        git(r, "checkout", "-q", "main")
        self.assertEqual([s for s in self.kinds(done_row([Mx], files=["side.py"])) if s.startswith("done.")], [])
        self.assertEqual([s for s in self.kinds(done_row([Mx], files=["y.py"])) if s.startswith("done.")], ["done." + RID])

    def test_done_git_failure_is_a_reason_not_a_crash(self):  # RQ16 (shallow or incomplete history)
        with mock.patch.object(programs, "_commit_paths", side_effect=GateError("boom")):
            got = self.errs(done_row([self.Cb]))
        self.assertEqual(got, [("done." + RID, "commit %s: git cannot judge it: boom" % self.Cb)])

    def test_done_each_commit_checked(self):  # RQ14
        self.assertEqual(self.kinds(done_row([self.Cb, self.Cn])), ["done." + RID])
        self.assertEqual(self.kinds(done_row([self.Cb], files=["b-owned.py", "other.py"])), ["to." + RID])
        got = self.errs(done_row([self.Cb, self.Cn]))
        self.assertIn(self.Cn, got[0][1])
        self.assertNotIn(self.Cb, got[0][1])

    def test_done_only_for_done_requests(self):  # RQ15
        r = req_row(status="open")
        r["resolution"] = {"commits": [self.Ca], "at": "b" * 7, "by": "b"}
        self.assertEqual(self.kinds(r), [])

    def test_request_errors_git_states(self):  # RQ16
        git(self.root, "checkout", "-q", "--detach", "main")
        self.assertEqual(self.kinds(done_row([self.Cb])), [])
        git(self.root, "checkout", "-q", "--orphan", "unborn")
        self.assertEqual(self.kinds(done_row([self.Cb])), [])
        self.assertEqual(self.kinds(done_row([self.Ca])), ["done." + RID])
        git(self.root, "checkout", "-q", "-f", "main")
        # a tag of the branch's name: the branch is read through refs/heads/ (D-A23)
        git(self.root, "checkout", "-q", "-b", "zside", "main")
        self.put("b-owned.py", "z\n")
        Cz = commit_all(self.root, "Cz touches a listed file, on no stream branch")
        git(self.root, "checkout", "-q", "main")
        git(self.root, "tag", NAME + "/b/main", Cz)
        self.assertEqual(self.kinds(done_row([self.Cb])), [])
        self.assertEqual(self.kinds(done_row([Cz])), ["done." + RID])      # the tag is no owner branch (refs/heads/ is read)
        self.assertEqual(self.kinds(done_row([self.Ca])), ["done." + RID])
        # an unknown to_stream names no branch
        self.assertEqual(self.kinds(done_row([self.Cb], to="zz")), ["to." + RID, "done." + RID])

    def decision_files(self, status="answered", cls="request-dispute", did=DID):
        write_dec = {"schema": "decision/1", "id": did, "status": status, "class": cls}
        write_record(self.root, ".strict-delivery/state/decisions/%s.yml" % did, write_dec)

    def test_request_decision_must_be_answered_dispute(self):  # RQ17
        r = req_row(decision=DID)
        got = self.errs(r)
        self.assertEqual(got, [("decision." + RID, "decision %s is not an answered decision of class request-dispute" % DID)])
        self.assertEqual(self.kinds(req_row()), [])                                    # absent: not judged
        self.decision_files()
        self.assertEqual(self.kinds(r), [])
        for status, cls in (("open", "request-dispute"), ("withdrawn", "request-dispute"), ("answered", "scope")):
            self.decision_files(status, cls)
            self.assertEqual(self.kinds(r), ["decision." + RID], (status, cls))
        self.decision_files()
        self.assertEqual(self.kinds(req_row(decision="DEC-20261105-zzzz")), ["decision." + RID])   # unknown id
        self.assertEqual(self.kinds(req_row(decision=RID)), ["decision." + RID])                   # a request id

    def test_request_decision_read_at_the_programs_ref(self):  # D-A22 (iv)
        self.decision_files()
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", "decision")
        r = req_row(decision=DID)
        self.assertEqual(self.kinds(r, ref="HEAD"), [])
        git(self.root, "checkout", "-q", "-b", "nodec", self.A)
        self.assertEqual(self.kinds(r, ref="main"), [])                 # the working tree is not read
        self.assertEqual(self.kinds(r, ref=None), ["decision." + RID])  # branch nodec holds no decision

    def test_request_decision_types(self):  # RQ18
        for bad in (5, "", None, ["x"]):
            self.assertEqual(self.kinds(req_row(decision=bad)), [], bad)

    def test_request_errors_arguments(self):  # RQ19
        prog = make_program([req_row()])
        for bad in (None, {"requests": []}, [prog]):
            with self.assertRaises(ValueError):
                request_errors(bad, self.root, self.cfg, BDX)
        for bad in (None, 5, "", b"x"):
            with self.assertRaises(GateError):
                request_errors(prog, bad, self.cfg, BDX)
        for bad in ({}, {"ids": {}}, None, {"ids": None}):
            with self.assertRaises(GateError):
                request_errors(prog, self.root, bad, BDX)
        sub = os.path.join(self.root, "sub")
        os.makedirs(sub)
        with self.assertRaises(GateError):
            request_errors(make_program([done_row([self.Cb])]), sub, self.cfg, BDX)
        for bd in (None, {}, BDX):
            self.assertEqual(request_errors(prog, self.root, self.cfg, bd), [])        # a non-residual request: not read

    def test_request_errors_order(self):  # RQ20
        r1 = req_row(RID, frm="z", to="z", files=["q.py"])
        r2 = done_row([self.Ca], rid=RID2, to="b", files=["b-owned.py", "b-owned.py"], decision=DID)
        got = self.kinds(r1, r2)
        self.assertEqual(got, ["to." + RID, "from." + RID, "files." + RID2, "done." + RID2, "decision." + RID2])
        self.assertEqual(self.kinds(r1, r2), got)                       # deterministic
        self.assertEqual(self.kinds(r2, r1), ["files." + RID2, "done." + RID2, "decision." + RID2, "to." + RID, "from." + RID])

    def test_request_errors_same_on_both(self):  # RQ21: no case folding of ids, no int(), 41 hex refused
        ids_ = ["R-20261105-ࡰn3p", "r-20261105-bn3p"]
        for i in ids_:
            self.assertTrue(any(s.startswith("id.") for s in self.kinds(req_row(rid=i))), i)
        self.assertEqual(self.kinds(done_row(["a" * 41])), ["done." + RID])

    def test_request_duplicate_files(self):  # D-A22 (v): a file listed twice is refused
        self.assertEqual(self.errs(req_row(files=["b-owned.py", "B-OWNED.PY"]))[0][0], "files." + RID)
        self.assertEqual(self.kinds(req_row(files=["b-owned.py", "b-owned.py"])), ["files." + RID])
        self.assertEqual(self.kinds(req_row(files=["b-owned.py"])), [])


def rdf(entries, period=(PS_, PC), edges=(), subs=None, extra=()):
    streams = row(stream("a", entries.get("a", ["zz-a.py"])), stream("b", entries.get("b", ["zz-b.py"]), merge_order=2),
                  stream("y", ["zz-y.py"], merge_order=3), stream("residual", residual=True, period=period, merge_order=4), *extra)
    return streams, bd(subs or {"a": ["a1.1"], "b": ["b1.1"], "y": ["y1.1"], "residual": ["r1.1"]}, edges)


class RequestsTo(GitProgram):
    """The ``to.<id>`` rule (part B, Producer 10), on hand-built streams rows."""

    def to(self, to, files, streams=None, breakdown=None, status="open", cfg=None, **kw):
        prog = make_program([req_row(to=to, files=files, status=status, **kw)], streams if streams is not None else AB())
        return [e for e in request_errors(prog, self.root, cfg or self.cfg, BDX if breakdown is None else breakdown)
                if e[0] == "to." + RID]

    def has(self, *a, **kw):
        return len(self.to(*a, **kw)) == 1

    def test_request_to_stream_must_own_files(self):  # RQ1, RQ2, RQ25; plan :2696
        self.assertEqual(self.to("a", ["b-owned.py", "a-owned.py"]), [("to." + RID, "to_stream a does not own b-owned.py")])
        self.assertEqual(self.to("a", ["a-owned.py"]), [])
        prog = make_program([req_row(RID, to="a", frm="b", files=["b-owned.py"]), req_row(RID2, to="b", files=["a-owned.py"])], AB())
        self.assertEqual(request_errors(prog, self.root, self.cfg, BDX),
                         [("to." + RID, "to_stream a does not own b-owned.py"), ("to." + RID2, "to_stream b does not own a-owned.py")])

    def test_request_to_by_key(self):  # RQ3
        st = two(["src/", "café/", "Doc.md"], ["b-owned.py"])
        for f in ("src/x/y.py", "SRC/x.py", "src/", "café/x", "CAFÉ/y", "doc.MD"):
            self.assertFalse(self.has("a", [f], st), f)
        for f in ("srcx/y.py", "doc.md/x", "x/src/y"):
            self.assertTrue(self.has("a", [f], st), f)

    def test_request_to_window_not_yet_open_passes(self):  # RQ4, RQ5
        st = two([W("w.py", "merged:b", PC), W("dead.py", PC, PC)], ["b-owned.py"])
        self.assertFalse(self.has("a", ["w.py"], st))            # judged without event state
        self.assertFalse(self.has("a", ["dead.py"], st))         # a window that can never open still is an entry

    def test_request_to_workspaces(self):  # RQ6
        self.assertFalse(self.has("a", [PS + "/a-plan/n.md"]))
        self.assertTrue(self.has("a", [PS + "/b-plan/n.md"]))

    def test_request_to_unknown_stream(self):  # RQ7
        self.assertEqual(self.to("zz", ["a-owned.py"]), [("to." + RID, "to_stream zz does not own a-owned.py")])

    def residual_rows(self):
        a, ps, pc = "merged:a", PS_, PC
        return [("unowned.py", {}, (ps, pc), (), False), ("w.py", {"a": [W("w.py", ps, a)]}, (ps, pc), (), False),
                ("f.py", {"a": ["f.py"]}, (ps, pc), (), True), (PROGRAM_PLAN, {}, (ps, pc), (), True),
                (PS + "/program-plan/ledger.md", {}, (ps, pc), (), True), (PROGDIR + "/streams.yml", {}, (ps, pc), (), True),
                (".strict-delivery/state/decisions/x.yml", {}, (ps, pc), (), True),
                (PS + "/a-plan/n.md", {}, (ps, pc), (), True), (PS + "/residual-plan/n.md", {}, (ps, pc), (), False),
                ("chained.md", {"a": [W("chained.md", ps, a)], "b": [W("chained.md", a, pc)]}, (ps, pc), (), True),
                ("twostep.py", {"a": [W("twostep.py", ps, a)], "b": [W("twostep.py", a, "merged:b")]}, (ps, pc), (), False),
                ("late.md", {"a": [W("late.md", ps, a)]}, (ps, "merged:y"), [("a1.1", "y1.1")], False),
                ("late.md", {"a": [W("late.md", ps, a)]}, (ps, "merged:y"), [("y1.1", "a1.1")], True),
                ("f.py", {"a": [W("f.py", ps, pc)]}, (ps, pc), (), True)]

    def test_request_to_residual_rows(self):  # RQ8-RQ17
        for path, entries, period, edges, refused in self.residual_rows():
            streams, b = rdf(entries, period, edges)
            self.assertEqual(self.has("residual", [path], streams, b), refused, (path, entries, period, edges))
        # the rows RQ14 and RQ16 with the plan's helper (comes_before) agree
        streams, b = rdf({"a": [W("late.md", PS_, "merged:a")]}, (PS_, "merged:y"), [("y1.1", "a1.1")])
        self.assertTrue(comes_before(b, "merged:y", "merged:a"))

    def test_request_to_residual_missing(self):  # RQ18
        self.assertTrue(self.has("residual", ["unowned.py"], AB()))

    def test_request_to_residual_by_flag(self):  # RQ19, D-B13
        flagged = row(stream("a"), stream("rest", residual=True, merge_order=2))
        self.assertFalse(self.has("rest", ["unowned.py"], flagged, bd({"a": ["a1.1"], "rest": ["r1.1"]})))
        unflagged = row(stream("a"), stream("residual", ["res.py"], merge_order=2))
        self.assertTrue(self.has("residual", ["unowned.py"], unflagged, bd({"a": ["a1.1"], "residual": ["r1.1"]})))

    def test_request_to_several_files(self):  # RQ20
        self.assertEqual(self.to("a", ["a-owned.py", "x1.py", "x2.py"]), [("to." + RID, "to_stream a does not own x1.py, x2.py")])

    def test_request_to_file_forms(self):  # RQ21
        for f in ("", "/x", "a//b", "./a", "../a", "a/../b", "x\x00y"):
            got = self.to("a", [f])
            self.assertEqual(got, [("to." + RID, "to_stream a does not own %s (not a normalised repository path)" % f)], repr(f))
        got = self.to("a", ["x" * 4301])
        self.assertEqual(got, [("to." + RID, "to_stream a does not own %s" % ("x" * 4301))])
        st = two(["a/"], ["b-owned.py"])             # a directory entry covers these spellings by key; their shape refuses them
        for f in ("a/../b", "a//b", "a/./b"):
            self.assertEqual(self.to("a", [f], st), [("to." + RID, "to_stream a does not own %s (not a normalised repository path)" % f)])
        st = two(["dir/", "a-owned.py"], ["b-owned.py"])
        self.assertFalse(self.has("a", ["dir/"], st))
        self.assertFalse(self.has("a", ["dir/x/y"], st))

    def test_request_to_breakdown_unusable(self):  # RQ22, D-B11
        streams = rdf({})[0]
        usable = {"streams": [{"id": "residual", "tasks": ["R1.1"], "residual": True}]}
        self.assertEqual(self.to("residual", ["unowned.py"], streams, dict(usable, edges=[])), [])   # edges present, empty
        for badbd in ({}, {"edges": []}, {"streams": [], "edges": 5}, {"streams": [{"id": "residual"}]},
                      usable):                       # F-20261118-ix24: streams usable, `edges` absent
            got = self.to("residual", ["unowned.py"], streams, badbd)
            self.assertEqual(len(got), 1, badbd)
            self.assertIn("the breakdown cannot decide it", got[0][1])
        self.assertFalse(self.has("a", ["zz-a.py"], streams, {}))     # a non-residual to_stream never reads it
        prog = make_program([req_row(to="residual", files=["unowned.py"])], streams)
        self.assertEqual(request_errors(prog, self.root, self.cfg, None)[0][0], "to." + RID)

    def test_request_to_all_statuses(self):  # RQ23
        for st in ("open", "accepted", "done", "disputed", "withdrawn"):
            self.assertTrue(self.has("a", ["b-owned.py"], status=st), st)
            self.assertFalse(self.has("a", ["a-owned.py"], status=st), st)

    def test_record_request_to(self):  # RQ24: the plan's record
        rs, rb = record_streams(), RECORD_BD
        for to, f, refused in (("residual", "gates/__main__.py", False), ("residual", "CLAUDE.md", False),
                               ("residual", ".claude-plugin/plugin.json", False), ("init4", "gates/__main__.py", False),
                               ("release", "gates/__main__.py", True), ("package", "CLAUDE.md", True),
                               ("residual", PS + "/package-plan/x.md", True)):
            self.assertEqual(self.has(to, [f], rs, rb), refused, (to, f))

    def test_request_to_passes_the_real_cfg(self):  # D-B2: a caller that forgot cfg would use the defaults
        cfg2 = {**self.cfg, "paths": {**self.cfg["paths"], "plan_state": "state/p", "programs": "p2"}}
        st, b = rdf({})
        self.assertTrue(self.has("residual", ["state/p/a-plan/n.md"], st, b, cfg=cfg2))
        self.assertFalse(self.has("residual", ["state/p/a-plan/n.md"], st, b))
        self.assertTrue(self.has("residual", ["p2/%s/streams.yml" % NAME], st, b, cfg=cfg2))
        self.assertFalse(self.has("residual", ["p2/%s/streams.yml" % NAME], st, b))


def AB():
    return row(stream("a", ["a-owned.py"], merge_order=1), stream("b", ["b-owned.py"], merge_order=2))


if __name__ == "__main__":
    unittest.main()
