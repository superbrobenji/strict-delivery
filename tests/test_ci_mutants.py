"""Tests of Task CI3 (input-domain table task-CI3-domain.md: rows T1-T14 and K1-K3; T15 is the PR's own CI run).

Every test calls ``tests.ci_mutants.main`` (or runs ``python -m tests.ci_mutants``) on a fixture git repository built
under a temporary directory: a base commit on ``main`` and a head commit on ``feature`` that adds, changes or removes
mutant tables. The test runs the runner would start are replaced by a recorded fake (``Fake``) except in
``RealRunTest``, which runs the real ``unittest`` of this interpreter on a tiny fixture. Expected values are written by
hand from the table; T6 is a generated cross product (stream-common "Pair matrix" rule)."""
import ast
import collections
import contextlib
import hashlib
import io
import itertools
import os
import pathlib
import random
import re
import stat
import subprocess
import sys
import threading
import time
import tokenize
import types
import unittest
from unittest import mock

from tests import ci_mutants
from tests import test_self_adoption as sa
from tests.helpers import GitIsolatedTestCase, commit_all, git, make_repo

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY39 = "/fake/python3.9"
PY313 = "/fake/python3.13"
PYTHONS = ["--python", "3.9=" + PY39, "--python", "3.13=" + PY313]
TABLE = ".strict-delivery/mutants/CI9.py"
PASS = (0, "..\n----------------------------------------------------------------------\nRan 3 tests in 0.1s\n\nOK\n", False)
FAIL = (1, "F..\n----------------------------------------------------------------------\nRan 3 tests in 0.1s\n\n"
           "FAILED (failures=1)\n", False)
HANG = (-9, "", True)
LINE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*): (KILLED|SURVIVED|SPLIT|NOT_APPLIED|TIMEOUT|ERROR)(.*)$", re.M)

BASE_FILES = {
    ".gitignore": "__pycache__/\n",
    "docs/readme.txt": "docs\n",
    "src/__init__.py": "",
    "src/a.py": "def add(a, b):\n    return a + b\n\n\nVERSION = 1\n",
    "src/b.py": "X = 'one'\nY = 'two'\n",
    "tests/__init__.py": "",
    "tests/test_a.py": "import unittest\n\nfrom src.a import add\n\n\nclass T(unittest.TestCase):\n"
                       "    def test_add(self):\n        self.assertEqual(add(1, 2), 3)\n",
    "tests/test_b.py": "import unittest\n\nfrom src import b\n\n\nclass T(unittest.TestCase):\n"
                       "    def test_x(self):\n        self.assertEqual(b.X, 'one')\n",
    "tests/test_c.py": "import unittest\n\n\nclass T(unittest.TestCase):\n    def test_c(self):\n        self.assertTrue(True)\n",
    "tests/ci_mutants.py": "# fixture runner\n",
    "tests/test_ci_mutants.py": "# fixture tests\n",
    ".github/workflows/strict-delivery.yml": "name: fixture\n",
}


def table(m, kill, extra=""):
    """The text of a table file: two literal assignments (a repr of a dict of tuples is a valid literal)."""
    return "M = %r\nKILL = %r\n%s" % (m, kill, extra)


SIMPLE_M = {"i1": ("src/a.py", "a + b", "a - b"), "i2": ("src/b.py", "'two'", "'three'")}
SIMPLE_KILL = {"i1": ("tests.test_a",), "i2": ("tests.test_b",)}
SIMPLE = table(SIMPLE_M, SIMPLE_KILL)


def lines_of(out):
    """{id: rest of the line} for every id line of the output."""
    got = {}
    for m in LINE.finditer(out):
        assert m.group(1) not in got, "duplicate id line " + m.group(1)
        got[m.group(1)] = (m.group(2), m.group(3))
    return got


def verdicts(out):
    return {k: v[0] for k, v in lines_of(out).items()}


class Fake:
    """The recorded stand-in for the test run: ``policy(py, mods, mutated)`` answers; every call is kept with the bytes of
    the watched files at that moment (so a test sees what the runner had written when it ran the modules)."""

    def __init__(self, root, policy=None, watch=("src/a.py", "src/b.py")):
        self.root = root
        self.watch = list(watch)
        self.policy = policy or (lambda py, mods, mutated: PASS)
        self.pristine = self.snapshot()
        self.calls = []

    def snapshot(self):
        snap = {}
        for rel in self.watch:
            with open(os.path.join(self.root, rel), "rb") as fh:
                snap[rel] = fh.read()
        return snap

    def __call__(self, py, mods, root, timeout):
        snap = self.snapshot()
        mutated = snap != self.pristine
        self.calls.append((py, tuple(mods), snap, timeout))
        return self.policy(py, tuple(mods), mutated)

    def mutated_calls(self):
        return [c for c in self.calls if c[2] != self.pristine]

    def baseline_calls(self):
        return [c for c in self.calls if c[2] == self.pristine]


class Fx(GitIsolatedTestCase):
    """A fixture repository: ``main`` holds BASE_FILES, ``feature`` adds the tables of ``repo()``."""

    def repo(self, tables=None, files=None, base_extra=None, head_extra=None):
        if getattr(self, "root", None) is not None:  # a second repository in one test gets a fresh work directory
            self.work = os.path.join(self.tmp, "work%d" % next(COUNTER))
            os.mkdir(self.work)
        root = make_repo(self.work)
        self.root = root
        for rel, text in dict(BASE_FILES, **(base_extra or {})).items():
            self.put(rel, text)
        git(root, "add", "-A")
        commit_all(root, "base")
        git(root, "checkout", "-q", "-b", "feature")
        for rel, text in (tables if tables is not None else {TABLE: SIMPLE}).items():
            self.put(rel, text)
        for rel, text in (head_extra or {}).items():
            self.put(rel, text)
        self.head = commit_all(root, "head")
        return root

    def put(self, rel, text):
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path) or self.root, exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(text if isinstance(text, bytes) else text.encode("utf-8"))

    def read(self, rel):
        with open(os.path.join(self.root, rel), "rb") as fh:
            return fh.read()

    def status(self):
        return git(self.root, "status", "--porcelain", "--untracked-files=all")

    def argv(self, cmd="run", part=1, parts=1, base="main", head=None, extra=()):
        out = [cmd, "--base", base, "--head", head or self.head, "--parts", str(parts)]
        if cmd in ("run", "split"):
            out += ["--part", str(part)]
        if cmd == "run":
            out += PYTHONS
        return out + list(extra)

    def call(self, argv, execute=None, env=None):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = ci_mutants.main(argv, root=self.root, execute=execute, env=env if env is not None else {})
        return code, out.getvalue(), err.getvalue()

    def go(self, fake=None, **kw):
        fake = fake or Fake(self.root)
        code, out, err = self.call(self.argv(**kw), execute=fake)
        return code, out, err, fake

    def only_error(self, name, needle, text, files=None, kill=None, m=None):
        """A table ``text`` is refused as ERROR naming the table, with ``needle`` in the message; nothing ran."""
        self.repo({TABLE: text}, head_extra=files)
        fake = Fake(self.root)
        code, out, err = self.call(self.argv(), execute=fake)
        self.assertEqual(code, 1, (name, out, err))
        errs = [ln for ln in out.splitlines() if ln.startswith("ERROR")]
        self.assertTrue(errs, (name, out))
        self.assertTrue(any(TABLE in ln and needle in ln for ln in errs), (name, needle, errs))
        self.assertEqual(fake.calls, [], name)  # nothing is run, nothing mutated
        self.assertEqual(self.status(), "", name)
        return errs


# ---- T1: where a table lives --------------------------------------------------------------------------------------
class LocationTest(Fx):
    def test_convention_path_is_recorded(self):  # T1
        self.assertEqual(ci_mutants.TABLE_DIR, ".strict-delivery/mutants")
        self.assertIn(".strict-delivery/mutants/<task-id>.py", ci_mutants.__doc__)

    def test_only_files_under_the_convention_are_tables(self):  # T1
        other = table({"zz": ("src/a.py", "a + b", "a - b")}, {"zz": ("tests.test_a",)})
        self.repo({TABLE: SIMPLE, "docs/CI9.py": other, "mutants/CI9.py": other, ".strict-delivery/CI9.py": other,
                   ".strict-delivery/state/CI9.py": other, "tests/table.py": other})
        code, out, err, fake = self.go()
        self.assertEqual((code, sorted(verdicts(out))), (0, ["i1", "i2"]), out)  # "zz" of the other files never ran

    def test_a_file_under_the_directory_that_is_no_table_is_refused(self):  # T1
        for name in ("README.md", "sub/x.py", "has space.py", "OTHER.PY", ".hidden.py", "a;b.py", "x.py.bak"):
            with self.subTest(name):
                self.repo({TABLE: SIMPLE, ".strict-delivery/mutants/" + name: SIMPLE.replace("i1", "j1").replace("i2", "j2")})
                fake = Fake(self.root)
                code, out, err = self.call(self.argv(), execute=fake)
                self.assertEqual(code, 1, out)
                self.assertRegex(out, r"(?m)^ERROR table \.strict-delivery/mutants/.*not a table file name")
                self.assertEqual(fake.calls, [])


# ---- T2: syntax ---------------------------------------------------------------------------------------------------
class SyntaxTest(Fx):
    def test_plain_literal_table_runs_and_is_never_executed(self):  # T2
        self.repo({TABLE: SIMPLE})
        code, out, err, fake = self.go()
        self.assertEqual((code, verdicts(out)), (0, {"i1": "SURVIVED", "i2": "SURVIVED"}), out)

    def test_nonliteral_content_is_refused_without_executing_it(self):  # T2
        marker = os.path.join(self.work, "..", "executed-marker")
        marker = os.path.normpath(marker)
        bodies = {
            "import": "import os\n" + SIMPLE,
            "from-import": "from os import path\n" + SIMPLE,
            "call": SIMPLE + "open(%r, 'w').close()\n" % marker,
            "call-in-value": "M = {'i1': ('src/a.py', 'a', open(%r, 'w').close())}\nKILL = {'i1': ('tests.test_a',)}\n" % marker,
            "name": "X = 'a + b'\nM = {'i1': ('src/a.py', X, 'a - b')}\nKILL = {'i1': ('tests.test_a',)}\n",
            "comprehension": "M = {k: ('src/a.py', 'a + b', 'a - b') for k in ['i1']}\nKILL = {'i1': ('tests.test_a',)}\n",
            "set-comp": "M = {'i1': ('src/a.py', 'a + b', 'a - b')}\nKILL = {x for x in 'a'}\n",
            "binop": "M = {'i1': ('src/a.py', 'a ' + '+ b', 'a - b')}\nKILL = {'i1': ('tests.test_a',)}\n",
            "fstring": "M = {'i1': ('src/a.py', f'a + b', 'a - b')}\nKILL = {'i1': ('tests.test_a',)}\n",
            "extra-statement": SIMPLE + "N = 1\n",
            "def": SIMPLE + "def main():\n    pass\n",
            "main-call": SIMPLE + "import sys\nsys.exit(0)\n",
            "docstring": '"""doc"""\n' + SIMPLE,
            "annotated": "M: dict = {}\nKILL = {}\n",
            "augmented": SIMPLE + "M += {}\n",
            "assigned-twice": SIMPLE + "M = {}\n",
            "no-KILL": "M = {}\n",
            "no-M": "KILL = {}\n",
            "tuple-target": "M, KILL = {}, {}\n",
            "chained": "M = KILL = {}\n",
            "empty-file": "",
        }
        for label, body in bodies.items():
            with self.subTest(label):
                self.only_error(label, "literal", body)
                self.assertFalse(os.path.exists(marker), label)  # the call never ran

    def test_syntax_error_nul_and_non_utf8_are_refused(self):  # T2
        self.only_error("syntax", "syntax", "M = {\n")
        self.only_error("nul", "syntax", "M = {}\x00\nKILL = {}\n")
        self.only_error("bom-latin1", "UTF-8", b"M = {'a': ('src/a.py', '\xe9', 'b')}\nKILL = {}\n")
        self.only_error("deep", "syntax", "M = " + "[" * 20000 + "]" * 20000 + "\nKILL = {}\n")

    def test_table_that_is_a_symlink_directory_or_too_large_is_refused(self):  # T2, T5 shape of the table file
        self.repo({TABLE: SIMPLE})
        git(self.root, "checkout", "-q", "-b", "link")
        os.rename(os.path.join(self.root, TABLE), os.path.join(self.root, "docs/real.py"))
        os.symlink("../../docs/real.py", os.path.join(self.root, TABLE))
        head = commit_all(self.root, "link table")
        fake = Fake(self.root)
        code, out, err = self.call(self.argv(head=head), execute=fake)
        self.assertEqual(code, 1, out)
        self.assertRegex(out, r"(?m)^ERROR table %s: .*not a regular file" % re.escape(TABLE))
        self.assertEqual(fake.calls, [])
        self.only_error("big", "too large", table(SIMPLE_M, SIMPLE_KILL, "# " + "x" * (1 << 20) + "\n"))


# ---- T3: shape ----------------------------------------------------------------------------------------------------
class ShapeTest(Fx):
    def case(self, label, m, kill, needle, ident):
        errs = self.only_error(label, needle, table(m, kill))
        self.assertTrue(any(ident in ln for ln in errs), (label, errs))

    def test_every_shape_error_names_table_and_id(self):  # T3
        ok = ("src/a.py", "a + b", "a - b")
        k = ("tests.test_a",)
        cases = [
            ("id-not-str", {1: ok}, {1: k}, "not a str", "1"),
            ("id-bytes", {b"i1": ok}, {b"i1": k}, "not a str", "i1"),
            ("id-bad-chars", {"i 1": ok}, {"i 1": k}, "id", "i 1"),
            ("id-colon", {"a: KILLED": ok}, {"a: KILLED": k}, "id", "a: KILLED"),
            ("id-newline", {"a\nb": ok}, {"a\nb": k}, "id", "a"),
            ("id-empty", {"": ok}, {"": k}, "id", "''"),
            ("id-too-long", {"a" * 65: ok}, {"a" * 65: k}, "id", "aaaa"),
            ("value-list", {"i1": list(ok)}, {"i1": k}, "3-tuple", "i1"),
            ("value-2-tuple", {"i1": ok[:2]}, {"i1": k}, "3-tuple", "i1"),
            ("value-4-tuple", {"i1": ok + ("x",)}, {"i1": k}, "3-tuple", "i1"),
            ("value-str", {"i1": "src/a.py"}, {"i1": k}, "3-tuple", "i1"),
            ("value-bytes-element", {"i1": ("src/a.py", b"a + b", "a - b")}, {"i1": k}, "3-tuple of str", "i1"),
            ("value-int-element", {"i1": ("src/a.py", "a + b", 1)}, {"i1": k}, "3-tuple of str", "i1"),
            ("old-equals-new", {"i1": ("src/a.py", "a + b", "a + b")}, {"i1": k}, "old equals new", "i1"),
            ("empty-old", {"i1": ("src/a.py", "", "x")}, {"i1": k}, "empty old", "i1"),
            ("unencodable", {"i1": ("src/a.py", "a + b", "\ud800")}, {"i1": k}, "UTF-8", "i1"),
            ("no-killing-module", {"i1": ok}, {}, "no killing module", "i1"),
            ("empty-killing-modules", {"i1": ok}, {"i1": ()}, "no killing module", "i1"),
            ("kill-not-tuple", {"i1": ok}, {"i1": "tests.test_a"}, "tuple of str", "i1"),
            ("kill-list", {"i1": ok}, {"i1": ["tests.test_a"]}, "tuple of str", "i1"),
            ("kill-for-unknown-id", {"i1": ok}, {"i1": k, "ghost": k}, "not in M", "ghost"),
            ("M-not-dict", [("i1", ok)], {"i1": k}, "dict", "M"),
            ("KILL-not-dict", {"i1": ok}, [("i1", k)], "dict", "KILL"),
        ]
        for case in cases:
            with self.subTest(case[0]):
                self.case(*case)

    def test_duplicate_key_inside_one_literal(self):  # T3
        self.only_error("dup-key", "duplicate", "M = {'i1': ('src/a.py', 'a', 'b'), 'i1': ('src/a.py', 'c', 'd')}\n"
                        "KILL = {'i1': ('tests.test_a',)}\n")
        self.only_error("dup-kill", "duplicate", "M = {'i1': ('src/a.py', 'a + b', 'a - b')}\n"
                        "KILL = {'i1': ('tests.test_a',), 'i1': ('tests.test_b',)}\n")

    def test_duplicate_id_across_two_tables_names_both(self):  # T3
        self.repo({TABLE: SIMPLE, ".strict-delivery/mutants/CI8.py": SIMPLE})
        fake = Fake(self.root)
        code, out, err = self.call(self.argv(), execute=fake)
        self.assertEqual(code, 1, out)
        for tab, other in ((TABLE, "CI8.py"), (".strict-delivery/mutants/CI8.py", "CI9.py")):
            self.assertRegex(out, r"(?m)^ERROR table %s id i1: duplicate id, also in .*%s" % (re.escape(tab), other))
        self.assertEqual(fake.calls, [])

    def test_the_same_id_in_an_unchanged_table_is_not_a_duplicate(self):  # T3: only changed tables are read
        self.repo({TABLE: SIMPLE}, base_extra={".strict-delivery/mutants/CI1.py": SIMPLE})
        code, out, err, fake = self.go()
        self.assertEqual((code, sorted(verdicts(out))), (0, ["i1", "i2"]), out)

    def test_one_bad_id_stops_the_other_ids_too(self):  # T3: nothing runs while any table is refused
        m = dict(SIMPLE_M, bad=("src/a.py", "x", "x"))
        self.only_error("one-bad", "old equals new", table(m, dict(SIMPLE_KILL, bad=("tests.test_a",))))


# ---- T4: killing modules ------------------------------------------------------------------------------------------
class ModuleTest(Fx):
    def run_with(self, modules):
        self.repo({TABLE: table({"i1": ("src/a.py", "a + b", "a - b")}, {"i1": modules})})
        fake = Fake(self.root)
        code, out, err = self.call(self.argv(), execute=fake)
        return code, out, fake

    def test_existing_modules_run(self):  # T4
        code, out, fake = self.run_with(("tests.test_a", "tests.test_c"))
        self.assertEqual((code, verdicts(out)), (0, {"i1": "SURVIVED"}), out)
        self.assertTrue(any(c[1] == ("tests.test_a", "tests.test_c") and c[2] != fake.pristine for c in fake.calls))

    def test_every_other_module_text_is_refused_and_never_reaches_unittest(self):  # T4
        bad = ["tests.test_missing", "gates.lib.config", "tests.helpers", "tests.sub.test_a", "tests", "tests.", "test_a",
               "tests/test_a.py", "tests.test_a.T", "-k", "--x", "-v", "tests.test_a;x", "tests.test_a x", "tests.test_a\n",
               "tests.test_a -k t", "$(x)", "`x`", "tests.test_\u0665", "tests.test_a\x00", "", "tests.test_*", "tests.test-a",
               ".tests.test_a", "tests..test_a", "tests.test_a.py"]
        for text in bad:
            with self.subTest(text):
                code, out, fake = self.run_with((text,))
                self.assertEqual(code, 1, out)
                self.assertRegex(out, r"(?m)^ERROR table %s id i1: .*killing module" % re.escape(TABLE))
                self.assertEqual(fake.calls, [])  # never started, so never passed to unittest as an option

    def test_a_good_module_beside_a_bad_one_refuses_the_id(self):  # T4
        code, out, fake = self.run_with(("tests.test_a", "--failfast"))
        self.assertEqual(code, 1, out)
        self.assertEqual(fake.calls, [])

    def test_a_module_that_is_a_symlink_or_untracked_is_refused(self):  # T4
        self.repo({TABLE: table({"i1": ("src/a.py", "a + b", "a - b")}, {"i1": ("tests.test_new",)})},
                  head_extra={})
        self.put("tests/test_new.py", "import unittest\n")  # on disk, untracked
        fake = Fake(self.root)
        code, out, err = self.call(self.argv(), execute=fake)
        self.assertEqual(code, 1, out)
        self.assertEqual(fake.calls, [])
        git(self.root, "checkout", "-q", "-b", "sym")
        os.rename(os.path.join(self.root, "tests/test_new.py"), os.path.join(self.root, "tests/test_new.moved"))
        os.symlink("test_a.py", os.path.join(self.root, "tests/test_new.py"))
        head = commit_all(self.root, "symlinked module")
        code, out, err = self.call(self.argv(head=head), execute=fake)
        self.assertEqual(code, 1, out)
        self.assertRegex(out, r"killing module")
        self.assertEqual(fake.calls, [])


# ---- T5: the mutated path -----------------------------------------------------------------------------------------
class PathTest(Fx):
    def one(self, path, files=None, base_extra=None, setup=None):
        """Run one id that mutates ``path`` (old text 'a + b' is only in src/a.py, so a refused path never reaches it)."""
        self.repo({TABLE: table({"i1": (path, "a + b", "a - b")}, {"i1": ("tests.test_a",)})}, head_extra=files,
                  base_extra=base_extra)
        if setup:
            setup()
        fake = Fake(self.root)
        code, out, err = self.call(self.argv(), execute=fake)
        return code, out, fake

    def refused(self, path, needle="path", **kw):
        code, out, fake = self.one(path, **kw)
        self.assertEqual(code, 1, (path, out))
        self.assertRegex(out, r"(?m)^i1: ERROR .*%s" % needle)
        self.assertEqual(fake.mutated_calls(), [], path)
        self.assertEqual(self.status(), "", path)

    def test_tracked_regular_file_is_mutated(self):  # T5
        code, out, fake = self.one("src/a.py")
        self.assertEqual((code, verdicts(out)), (0, {"i1": "SURVIVED"}), out)
        self.assertEqual(len(fake.mutated_calls()), 2)  # one run per interpreter

    def test_absolute_dotdot_and_malformed_paths(self):  # T5
        for path in ("/etc/passwd", os.path.join(self.work, "x"), "../src/a.py", "src/../src/a.py", "src/./a.py", "./src/a.py",
                     "src//a.py", "src/a.py/", "", ".", "..", "src\\a.py", "~/a.py", "src/a.py\n", "src/a.py\x00",
                     "src/a.py ", " src/a.py", "src/a:b.py", "src/a*.py", "src/[a].py", "src/\u00e4.py", "src/\udcff.py",
                     "-src", ":(top)src/a.py", ".git/config", "a" * 5000):
            with self.subTest(path[:40]):
                self.refused(path)

    def test_directory_missing_and_untracked_paths(self):  # T5
        self.refused("src")
        self.refused("src/")
        self.refused("src/missing.py")
        self.refused("__pycache__/u.py", setup=lambda: self.put("__pycache__/u.py", "a + b\n"),  # ignored, so the tree is clean
                     needle="not a tracked regular file")

    def test_tracked_symlink_to_a_file(self):  # T5
        def link():
            os.symlink("a.py", os.path.join(self.root, "src/alias.py"))
        self.repo({TABLE: table({"i1": ("src/alias.py", "a + b", "a - b")}, {"i1": ("tests.test_a",)})})
        git(self.root, "checkout", "-q", "-b", "sym")
        link()
        head = commit_all(self.root, "alias")
        fake = Fake(self.root)
        code, out, err = self.call(self.argv(head=head), execute=fake)
        self.assertEqual(code, 1, out)
        self.assertRegex(out, r"(?m)^i1: ERROR .*symbolic link")
        self.assertEqual(self.read("src/a.py"), BASE_FILES["src/a.py"].encode())

    def test_path_through_a_tracked_symlink_directory(self):  # T5
        self.repo({TABLE: table({"i1": ("link/a.py", "a + b", "a - b")}, {"i1": ("tests.test_a",)})})
        git(self.root, "checkout", "-q", "-b", "sym")
        os.symlink("src", os.path.join(self.root, "link"))
        head = commit_all(self.root, "link dir")
        fake = Fake(self.root)
        code, out, err = self.call(self.argv(head=head), execute=fake)
        self.assertEqual(code, 1, out)
        self.assertRegex(out, r"(?m)^i1: ERROR ")
        self.assertEqual(fake.mutated_calls(), [])

    def hide(self, rel, names):
        """Make git ignore ``names`` and skip the worktree state of ``rel``, so a swapped path leaves a clean status."""
        with open(os.path.join(self.root, ".git", "info", "exclude"), "a", encoding="utf-8") as fh:
            fh.write("\n".join(names) + "\n")
        git(self.root, "update-index", "--skip-worktree", rel)

    def test_a_parent_swapped_for_a_symlink_after_the_commit(self):  # T5 hardening row
        def swap():
            os.rename(os.path.join(self.root, "src"), os.path.join(self.root, "srcreal"))
            os.symlink("srcreal", os.path.join(self.root, "src"))
            self.hide("src/a.py", ["srcreal", "/src"])
        self.repo({TABLE: table({"i1": ("src/a.py", "a + b", "a - b")}, {"i1": ("tests.test_a",)})})
        swap()
        # the swap leaves tracked src/__init__.py and src/b.py missing as seen by git: hide them as well
        for rel in ("src/__init__.py", "src/b.py"):
            git(self.root, "update-index", "--skip-worktree", rel)
        self.assertEqual(self.status(), "")
        fake = Fake(self.root, watch=["srcreal/a.py"])
        code, out, err = self.call(self.argv(), execute=fake)
        self.assertEqual(code, 1, out)
        self.assertRegex(out, r"(?m)^i1: ERROR .*symbolic link")
        self.assertEqual(fake.mutated_calls(), [])

    def test_a_tracked_file_swapped_for_a_fifo_or_directory(self):  # T5 hardening row
        for kind in ("fifo", "dir"):
            with self.subTest(kind):
                self.work_reset()
                self.repo({TABLE: table({"i1": ("src/a.py", "a + b", "a - b")}, {"i1": ("tests.test_a",)})})
                os.rename(os.path.join(self.root, "src/a.py"), os.path.join(self.root, "src/a.moved"))
                with open(os.path.join(self.root, ".git", "info", "exclude"), "a", encoding="utf-8") as fh:
                    fh.write("src/a.moved\n")
                if kind == "fifo":
                    os.mkfifo(os.path.join(self.root, "src/a.py"))
                else:
                    os.mkdir(os.path.join(self.root, "src/a.py"))
                    self.put("src/a.py/inner.txt", "x\n")
                    with open(os.path.join(self.root, ".git", "info", "exclude"), "a", encoding="utf-8") as fh:
                        fh.write("src/a.py/inner.txt\n")
                git(self.root, "update-index", "--skip-worktree", "src/a.py")
                self.assertEqual(self.status(), "")
                fake = Fake(self.root, watch=["src/b.py"])
                code, out, err = self.call(self.argv(), execute=fake)  # a FIFO is never opened (it would block)
                self.assertEqual(code, 1, out)
                self.assertRegex(out, r"(?m)^i1: ERROR .*not a regular file")
                self.assertEqual(fake.mutated_calls(), [])

    def work_reset(self):
        """A fresh work directory for a sub-test that builds a second repository."""
        self.work = os.path.join(self.tmp, "work%d" % next(COUNTER))
        os.mkdir(self.work)

    def test_non_utf8_contents_are_mutated_bytewise(self):  # T5: unusual contents
        body = b"head \xff\xfe a + b \x80 tail\n"
        self.repo({TABLE: table({"i1": ("src/raw.py", "a + b", "a - b")}, {"i1": ("tests.test_a",)})},
                  base_extra={"src/raw.py": body})
        fake = Fake(self.root, watch=["src/raw.py"])
        code, out, err = self.call(self.argv(), execute=fake)
        self.assertEqual((code, verdicts(out)), (0, {"i1": "SURVIVED"}), out)
        self.assertEqual(fake.mutated_calls()[0][2]["src/raw.py"], body.replace(b"a + b", b"a - b"))
        self.assertEqual(self.read("src/raw.py"), body)

    def test_a_tracked_file_below_two_and_three_directories_is_mutated_and_restored(self):  # T5: parent walk, success path
        body = b"head \xff\xfe a + b \x80 tail\n"
        for path in ("src/sub/deep.py", "src/sub/sub2/deeper.py"):
            with self.subTest(path):
                self.repo({TABLE: table({"i1": (path, "a + b", "a - b")}, {"i1": ("tests.test_a",)})}, base_extra={path: body})
                fake = Fake(self.root, watch=[path])
                code, out, err = self.call(self.argv(), execute=fake)
                self.assertEqual((code, verdicts(out)), (0, {"i1": "SURVIVED"}), out)
                self.assertEqual([c[2][path] for c in fake.mutated_calls()], [body.replace(b"a + b", b"a - b")] * 2)
                self.assertEqual(self.read(path), body)  # restored byte-exact
                self.assertEqual(self.status(), "")

    def test_a_tracked_file_with_a_second_hard_link_is_refused_at_the_check(self):  # T5 link count
        text = BASE_FILES["src/a.py"]
        self.repo({TABLE: table({"i1": ("src/a.py", "a + b", "a - b"), "i2": ("src/c.py", "a + b", "a - b"),
                                 "i3": ("src/b.py", "'two'", "'three'")},
                                {"i1": ("tests.test_a",), "i2": ("tests.test_a",), "i3": ("tests.test_b",)})},
                  base_extra={"src/c.py": text, "src/d.py": text})
        outside = os.path.join(self.tmp, "outside_alias.py")
        os.link(os.path.join(self.root, "src/a.py"), outside)  # a.py is also a file outside the root (i1): two links
        os.link(os.path.join(self.root, "src/c.py"), os.path.join(self.root, "src/d.link"))  # d.py is another tracked file
        os.rename(os.path.join(self.root, "src/d.link"), os.path.join(self.root, "src/d.py"))  # same inode as c.py (i2)
        self.assertEqual(self.status(), "")  # same bytes: git sees no change
        fake = Fake(self.root, watch=["src/a.py", "src/b.py", "src/c.py", "src/d.py"])
        code, out, err = self.call(self.argv(), execute=fake)
        self.assertEqual((code, verdicts(out)), (1, {"i1": "ERROR", "i2": "ERROR", "i3": "SURVIVED"}), out)
        self.assertRegex(lines_of(out)["i1"][1], r"^ \| path 'src/a\.py' has more than one hard link$")
        self.assertRegex(lines_of(out)["i2"][1], r"^ \| path 'src/c\.py' has more than one hard link$")
        for call in fake.mutated_calls():  # only i3 ever ran: no linked file was ever mutated
            for rel in ("src/a.py", "src/c.py", "src/d.py"):
                self.assertEqual(call[2][rel], fake.pristine[rel], rel)
        for path in (outside, os.path.join(self.root, "src/a.py"), os.path.join(self.root, "src/c.py"),
                     os.path.join(self.root, "src/d.py")):
            with open(path, "rb") as fh:
                self.assertEqual(fh.read(), text.encode())
            self.assertEqual(os.stat(path).st_nlink, 2, path)
        self.assertEqual(self.status(), "")

    def test_a_killing_module_with_a_second_hard_link_is_refused(self):  # T5 link count, T4
        self.repo({TABLE: table({"i1": ("src/a.py", "a + b", "a - b")}, {"i1": ("tests.test_a",)})})
        os.link(os.path.join(self.root, "tests/test_a.py"), os.path.join(self.tmp, "module_alias.py"))
        fake = Fake(self.root)
        code, out, err = self.call(self.argv(), execute=fake)
        self.assertEqual(code, 1, out)
        self.assertRegex(out, r"(?m)^ERROR table %s id i1: .*killing module" % re.escape(TABLE))
        self.assertEqual(fake.calls, [])


class SwapAfterCheckTest(Fx):
    """T5 hardening row "a parent component is a symlink or is swapped after the check", one test per member of the class:
    the O_NONBLOCK flag, the O_NOFOLLOW flag, the fstat regular-file check, the write-open before the run, the write-open
    of the restore, and the parent components. The path of the one id is checked as a tracked regular file; then it is
    swapped (after the check, hidden from ``git status``) at one of three moments: AFTER_CHECK (while the baseline runs, before
    the file is read), BEFORE_WRITE (after the read, before the mutated bytes are written: the hook is count_problem) and
    BEFORE_RESTORE (during the mutated run, before the restore writes the bytes back). Every swap target lives in this
    test's own temporary directory (self.tmp, a sibling of the repository), never in a shared directory.

    The depth cases: the target is a file below one, two or three directories, and the directory swapped by the ``parent``
    kinds (PARENT) is any one of its ancestors, so every level of the parent walk is hit. The link-count kinds: a hard link
    to a file outside the root and a hard link to another tracked file, swapped in at each open of the target."""

    OUTSIDE_BODY = b"OUTSIDE a + b\n"
    ALL = ("symlink-inside", "symlink-outside", "directory", "fifo", "fifo-with-reader", "parent-inside", "parent-outside")
    HARD = ("hardlink-outside", "hardlink-inside")
    MOMENTS = ("after-check", "before-write", "before-restore")
    SWAP_AT_CALL = {"after-check": 1, "before-restore": 3}  # the 1st execute call is a baseline run, the 3rd the mutated run
    DEEP = {"src/sub/deep.py": "VALUE = a + b\n", "src/sub/b.py": "SUB = 1\n",
            "src/sub/sub2/deeper.py": "VALUE = a + b\n", "src/sub/sub2/b.py": "SUB2 = 1\n"}
    DEPTHS = (("src/a.py", ("src",)),  # one parent
              ("src/sub/deep.py", ("src", "src/sub")),  # two parents
              ("src/sub/sub2/deeper.py", ("src", "src/sub", "src/sub/sub2")))  # three parents
    PAIRS = tuple((target, parent) for target, parents in DEPTHS for parent in parents)

    def setUp(self):
        super().setUp()
        self.fds = []
        self.addCleanup(lambda: [os.close(fd) for fd in self.fds])
        self.extra, self.visible = dict(self.DEEP), set()
        self.use("src/a.py", "src")

    def use(self, target, parent):
        """The target path of the one id, and the ancestor directory that the ``parent`` kinds swap."""
        self.TARGET, self.PARENT = target, parent
        self.SIBLING = os.path.dirname(target) + "/b.py"  # a tracked file beside the target

    def moved(self, rel, kind):
        """Where the tracked file ``rel`` is after the swap ``kind``: a swapped parent moves its whole directory."""
        if kind.startswith("parent") and (rel == self.PARENT or rel.startswith(self.PARENT + "/")):
            return self.PARENT + "real" + rel[len(self.PARENT):]
        return rel

    def prepare(self):
        self.repo({TABLE: table({"i1": (self.TARGET, "a + b", "a - b")}, {"i1": ("tests.test_a",)})}, base_extra=self.extra)
        self.contents = dict(BASE_FILES, **self.extra)
        self.outside = os.path.join(self.tmp, "outside%d" % next(COUNTER))
        # the parent kinds link the swapped directory to ``outside``: the rest of the target path exists there, so a
        # parent that was followed would open (and write) this file
        self.outside_file = os.path.join(self.outside, self.TARGET[len(self.PARENT) + 1:])
        os.makedirs(os.path.dirname(self.outside_file))
        with open(self.outside_file, "wb") as fh:
            fh.write(self.OUTSIDE_BODY)
        os.utime(self.outside_file, ns=(10 ** 18, 10 ** 18))  # an old mtime: any write to the file changes it
        self.outside_before = (self.OUTSIDE_BODY, os.stat(self.outside_file).st_mtime_ns)
        with open(os.path.join(self.root, ".git", "info", "exclude"), "a", encoding="utf-8") as fh:
            fh.write("%s.aside\n%sreal\n/%s\n" % (self.TARGET, self.PARENT, self.PARENT))
        for rel in git(self.root, "ls-files", "--", self.PARENT).split("\n"):
            if rel and rel not in self.visible:
                git(self.root, "update-index", "--skip-worktree", rel)
        self.assertEqual(self.status(), "")

    def swap(self, kind):
        path = os.path.join(self.root, self.TARGET)
        if kind.startswith("parent"):
            os.rename(os.path.join(self.root, self.PARENT), os.path.join(self.root, self.PARENT + "real"))
            os.symlink(os.path.basename(self.PARENT) + "real" if kind == "parent-inside" else self.outside,
                       os.path.join(self.root, self.PARENT))
            return
        if kind == "renamed-over":  # a regular file of the tree (link count 1) renamed over the path
            os.rename(os.path.join(self.root, "src/c.py"), path)
            return
        os.rename(path, path + ".aside")
        if kind == "symlink-inside":
            os.symlink("b.py", path)  # another tracked file of the repository
        elif kind == "symlink-outside":
            os.symlink(self.outside_file, path)
        elif kind == "hardlink-outside":
            os.link(self.outside_file, path)  # the same inode as a file outside the root
        elif kind == "hardlink-inside":
            os.link(os.path.join(self.root, self.SIBLING), path)  # the same inode as another tracked file
        elif kind == "directory":
            os.mkdir(path)
        else:
            os.mkfifo(path)
            if kind == "fifo-with-reader":  # a FIFO that a non-blocking write open can reach
                self.fds.append(os.open(path, os.O_RDONLY | os.O_NONBLOCK))

    def attempt(self, moment, kind):
        """One run through main() with the swap at ``moment``; (code, out, execute calls). A run that blocks (on a FIFO)
        fails the test after it is released."""
        self.prepare()
        lock, calls, result = threading.Lock(), [], {}

        def execute(py, mods, root, timeout):
            with lock:
                calls.append(py)
                if len(calls) == self.SWAP_AT_CALL.get(moment):
                    self.swap(kind)
            return PASS
        real_count = ci_mutants.count_problem

        def count_then_swap(data, old):
            if moment == "before-write":
                self.swap(kind)
            return real_count(data, old)

        def work():
            result["r"] = self.call(self.argv(), execute=execute)
        with mock.patch.object(ci_mutants, "count_problem", count_then_swap):
            thread = threading.Thread(target=work, daemon=True)
            thread.start()
            thread.join(30)
            if thread.is_alive():  # blocked in an open of the FIFO: release it, then fail
                path = os.path.join(self.root, self.TARGET)
                for _ in range(100):
                    for flag in (os.O_WRONLY, os.O_RDONLY):
                        try:
                            self.fds.append(os.open(path, flag | os.O_NONBLOCK))
                        except OSError:
                            pass
                    thread.join(0.1)
                    if not thread.is_alive():
                        break
                self.fail("the run blocked on %s swapped in at %s" % (kind, moment))
        code, out, err = result["r"]
        return code, out, calls

    def check(self, moment, kind):
        code, out, calls = self.attempt(moment, kind)
        self.assertEqual((code, verdicts(out)), (1, {"i1": "ERROR"}), (moment, kind, out))
        line = lines_of(out)["i1"][1]
        who = re.escape(self.TARGET)
        refused = r" \| path '%s' changed after the check" % who
        if moment == "after-check":
            self.assertRegex(line, "^" + refused, (moment, kind, line))
            self.assertEqual(len(calls), 2, (moment, kind))  # the baseline only: the id never ran
        elif moment == "before-write":
            self.assertRegex(line, refused + r".*the file %s was not restored" % who, (moment, kind, line))
            self.assertEqual(len(calls), 2, (moment, kind))
        else:
            self.assertRegex(line, r" \| the file %s was not restored: path '%s' changed after the check" % (who, who),
                             (moment, kind, line))
            self.assertEqual(len(calls), 4, (moment, kind))
        self.assertOutsideAndSiblingUntouched(moment, kind)
        if moment != "before-restore":  # the original file was never touched
            original = self.moved(self.TARGET, kind) if kind.startswith("parent") else self.TARGET + ".aside"
            self.assertEqual(self.read(original), self.contents[self.TARGET].encode(), (moment, kind))

    def assertOutsideAndSiblingUntouched(self, moment, kind):
        with open(self.outside_file, "rb") as fh:  # nothing was written outside the root, through any link
            body = fh.read()
        self.assertEqual((body, os.stat(self.outside_file).st_mtime_ns), self.outside_before, (moment, kind))
        self.assertEqual(self.read(self.moved(self.SIBLING, kind)), self.contents[self.SIBLING].encode(),
                         (moment, kind))  # nor to another tracked file

    def each(self, moments, kinds):
        for moment, kind in itertools.product(moments, kinds):
            with self.subTest(moment=moment, kind=kind):
                self.check(moment, kind)

    def check_time(self, kind):
        """The swap is done BEFORE the run, so the check itself sees it: refused at the check, nothing run or mutated."""
        self.prepare()
        self.swap(kind)
        calls = []

        def execute(py, mods, root, timeout):
            calls.append(py)
            return PASS
        code, out, err = self.call(self.argv(), execute=execute)
        self.assertEqual((code, verdicts(out)), (1, {"i1": "ERROR"}), (self.TARGET, kind, out))
        self.assertRegex(lines_of(out)["i1"][1], r"^ \| path '%s' has a parent that is a symbolic link$" % re.escape(self.TARGET),
                         (self.TARGET, kind))
        self.assertEqual(calls, [], (self.TARGET, kind))  # not even the baseline ran
        self.assertOutsideAndSiblingUntouched("before the check", kind)

    def test_o_nonblock_a_fifo_swapped_in_never_blocks_the_open(self):  # T5 swapped after the check: O_NONBLOCK
        self.each(self.MOMENTS, ("fifo", "fifo-with-reader"))

    def test_o_nofollow_a_symlink_swapped_in_is_never_followed(self):  # T5 swapped after the check: O_NOFOLLOW
        self.each(self.MOMENTS, ("symlink-inside", "symlink-outside"))

    def test_the_regular_file_check_on_the_opened_file(self):  # T5 swapped after the check: fstat S_ISREG
        self.each(("after-check",), ("directory", "fifo", "fifo-with-reader"))
        self.each(("before-write", "before-restore"), ("fifo", "fifo-with-reader"))

    def test_the_write_open_before_the_run_never_follows_a_swap(self):  # T5 swapped after the check: the mutated write
        self.each(("before-write",), self.ALL)

    def test_the_write_open_of_the_restore_never_follows_a_swap(self):  # T5 swapped after the check: the restore write
        self.each(("before-restore",), self.ALL)

    def test_a_parent_directory_swapped_for_a_symlink_is_never_followed(self):  # T5 swapped after the check: parents
        self.each(self.MOMENTS, ("parent-inside", "parent-outside"))

    def test_a_parent_at_every_depth_swapped_for_a_symlink_is_never_followed(self):  # T5 swapped after the check: depth 1-3
        for target, parent in self.PAIRS:
            self.use(target, parent)
            with self.subTest(target=target, parent=parent):
                self.each(self.MOMENTS, ("parent-inside", "parent-outside"))

    def test_a_parent_at_every_depth_that_is_a_symlink_at_the_check_is_refused(self):  # T5 parent is a symlink: depth 1-3
        for target, parent in self.PAIRS:
            self.use(target, parent)
            for kind in ("parent-inside", "parent-outside"):
                with self.subTest(target=target, parent=parent, kind=kind):
                    self.check_time(kind)

    def test_a_hard_link_swapped_in_at_every_open_of_the_target_is_never_written_through(self):  # T5 link count: swapped
        self.each(self.MOMENTS, self.HARD)  # after-check: the read open; before-write: the write open; before-restore: the restore

    def test_a_hard_link_to_a_file_outside_the_root_keeps_the_outside_bytes_when_the_write_open_is_refused(self):  # T5 link count
        self.check("before-write", "hardlink-outside")
        with open(self.outside_file, "rb") as fh:
            self.assertEqual(fh.read(), self.OUTSIDE_BODY)  # a write open that truncated first would leave it empty
        self.assertEqual(os.stat(self.outside_file).st_nlink, 2)  # the link is still there: nothing was removed or rewritten

    def test_a_truncate_that_fails_is_a_named_error_and_leaks_no_descriptor(self):  # T5, T10: the truncate moved out of the open
        def refuse(fd, length):
            raise OSError(30, "Read-only file system")
        self.repo({TABLE: SIMPLE})
        before = len(os.listdir("/dev/fd"))
        with mock.patch.object(os, "ftruncate", refuse):
            code, out, err, fake = self.go()
        self.assertEqual((code, verdicts(out)), (1, {"i1": "ERROR", "i2": "ERROR"}), out)
        self.assertRegex(lines_of(out)["i1"][1], r"^ \| path 'src/a\.py' changed after the check \(cannot be truncated: "
                         r"Read-only file system\); the file src/a\.py was not restored: path 'src/a\.py' changed after the check")
        self.assertRegex(lines_of(out)["i2"][1], r"not run: the file of i1 was not restored")
        self.assertEqual(fake.mutated_calls(), [])
        self.assertEqual(self.read("src/a.py"), BASE_FILES["src/a.py"].encode())
        self.assertEqual(len(os.listdir("/dev/fd")), before)  # the descriptor of each refused open was closed

    def test_a_regular_file_renamed_over_the_path_from_elsewhere_in_the_tree_is_an_error(self):  # T5 swapped, T10 tree clean
        self.extra["src/c.py"] = "C = a + b\n"  # a tracked regular file of the tree, link count 1
        self.visible.add("src/c.py")  # its disappearance must show in git status
        for moment in self.MOMENTS:
            with self.subTest(moment=moment):
                code, out, calls = self.attempt(moment, "renamed-over")
                self.assertEqual((code, verdicts(out)), (1, {"i1": "ERROR"}), (moment, out))
                self.assertRegex(lines_of(out)["i1"][1],
                                 r"^ \| the tree is not clean \(\d+ entries, first: .*\) after (the baseline|this id)$")
                self.assertEqual(self.status().split(), ["D", "src/c.py"], moment)  # the vanished source is the only change
                self.assertOutsideAndSiblingUntouched(moment, "renamed-over")  # and nothing written outside the root
                self.assertEqual(len(calls), {"after-check": 2, "before-write": 4, "before-restore": 4}[moment], moment)

    def test_a_restore_that_does_not_read_back_the_bytes_is_an_error_and_stops_the_job(self):  # T10 restore
        class Lying:
            """The file of the restore, whose write is replaced."""
            def __init__(self, fh, write):
                self.fh, self.lie = fh, write

            def write(self, data):
                return self.lie(data)

            def __getattr__(self, name):
                return getattr(self.fh, name)

            def __enter__(self):
                self.fh.__enter__()
                return self

            def __exit__(self, *exc):
                return self.fh.__exit__(*exc)

        def full_disk(data):
            raise OSError(28, "No space left on device")
        real = ci_mutants.open_target
        for label, lie, needle in (("dropped", lambda data: len(data), "the bytes read back differ"),
                                   ("failed", full_disk, "OSError: .*No space left")):
            with self.subTest(label):
                writes = []

                def patched(root, rel, write):
                    fh = real(root, rel, write)
                    if write:
                        writes.append(rel)
                        if len(writes) == 2:  # the second write open of the run is the restore of the first id
                            return Lying(fh, lie)
                    return fh
                self.repo({TABLE: SIMPLE})
                with mock.patch.object(ci_mutants, "open_target", patched):
                    code, out, err, fake = self.go()
                self.assertEqual((code, verdicts(out)), (1, {"i1": "ERROR", "i2": "ERROR"}), out)
                self.assertRegex(lines_of(out)["i1"][1], r"the file src/a\.py was not restored: " + needle)
                self.assertRegex(lines_of(out)["i2"][1], r"not run: the file of i1 was not restored")
                self.assertEqual(len(fake.mutated_calls()), 2)  # i1's two runs only: i2 never ran

COUNTER = itertools.count(1)


# ---- T6: pair matrix ----------------------------------------------------------------------------------------------
class PairMatrixTest(Fx):
    """The mutated path against every protected path and every relation, generated, not listed by hand."""

    PROTECTED = {  # kind -> the path it names in the fixture
        "table-itself": TABLE,
        "other-table": ".strict-delivery/mutants/CI8.py",
        "runner": "tests/ci_mutants.py",
        "splitter": "tests/ci_mutants.py",
        "workflow": ".github/workflows/strict-delivery.yml",
        "killing-module": "tests/test_a.py",
        "runner-tests": "tests/test_ci_mutants.py",
        "imported-test-module": "tests/test_lib.py",  # imported by the killing module tests/test_a.py (F-20261126-5nhg)
        "imported-transitively": "tests/test_deep.py",  # imported by tests/test_lib.py
        "imported-through-support": "tests/test_viahelper.py",  # imported by tests/support_fx.py, which test_a imports
        "tests-package": "tests/__init__.py",
    }
    ORACLE_FILES = {  # the import graph of the fixture: test_a -> test_lib -> test_deep; test_a -> support_fx -> test_viahelper
        "tests/test_a.py": "import unittest\n\nfrom src.a import add\nfrom tests import support_fx\nfrom tests import test_lib\n\n\n"
                           "class T(unittest.TestCase):\n    def test_add(self):\n        self.assertEqual(add(1, 2), 3)\n",
        "tests/test_lib.py": "from tests import test_deep\n\nVALUE = 1\n",
        "tests/test_deep.py": "VALUE = 2\n",
        "tests/support_fx.py": "from tests import test_viahelper\n\nVALUE = 3\n",
        "tests/test_viahelper.py": "VALUE = 4\n",
    }
    ORACLE_PATHS = ["tests/test_lib.py", "tests/test_deep.py", "tests/test_viahelper.py", "tests/__init__.py"]

    @staticmethod
    def relate(path, relation):
        if relation == "equal":
            return path
        if relation == "below":
            return path + "/x.py"
        if relation == "above":
            return os.path.dirname(path)
        if relation == "case-folded":
            return path.upper()
        raise AssertionError(relation)

    def cells(self, protected=None):
        for (kind, path), relation in itertools.product(sorted((protected or self.PROTECTED).items()),
                                                         ("equal", "below", "above", "case-folded")):
            yield "%s-%s" % (kind, relation), kind, relation, self.relate(path, relation)

    def test_generated_cross_product(self):  # T6
        m, kill, expect = {}, {}, {}
        for n, (label, kind, relation, path) in enumerate(self.cells()):
            ident = "p%02d" % n
            m[ident] = (path, "a + b", "a - b")
            kill[ident] = ("tests.test_a",)
            expect[ident] = (label, path)
        m["okA"] = ("src/a.py", "a + b", "a - b")  # other cells are allowed: an ordinary source file
        kill["okA"] = ("tests.test_a",)
        m["okB"] = ("tests/test_c.py", "assertTrue(True)", "assertTrue(False)")  # a test module that kills nothing here
        kill["okB"] = ("tests.test_a",)
        m["okC"] = ("tests/support_fx.py", "VALUE = 3", "VALUE = 5")  # a support module (not test*) a killer imports stays allowed
        kill["okC"] = ("tests.test_a",)
        self.repo({TABLE: table(m, kill), ".strict-delivery/mutants/CI8.py": table(
            {"o1": ("src/b.py", "'one'", "'uno'")}, {"o1": ("tests.test_b",)})}, base_extra=self.ORACLE_FILES)
        fake = Fake(self.root, watch=["src/a.py", "src/b.py", "tests/test_c.py", "tests/test_a.py", "tests/ci_mutants.py",
                                      ".github/workflows/strict-delivery.yml", TABLE, ".strict-delivery/mutants/CI8.py",
                                      "tests/support_fx.py"] + self.ORACLE_PATHS)
        code, out, err = self.call(self.argv(), execute=fake)
        got = verdicts(out)
        self.assertEqual(code, 1, out)
        for ident, (label, path) in expect.items():
            with self.subTest(label):
                self.assertEqual(got.get(ident), "ERROR", (label, path, lines_of(out).get(ident)))
                if label.endswith(("-equal", "-case-folded")) or label.startswith(("table-itself-below", "other-table-below",
                                                                                      "workflow-below", "workflow-above")):
                    self.assertIn("protected", lines_of(out)[ident][1], label)
        self.assertEqual(got["okA"], "SURVIVED", out)
        self.assertEqual(got["okB"], "SURVIVED", out)
        self.assertEqual(got["okC"], "SURVIVED", out)
        self.assertEqual(got["o1"], "SURVIVED", out)
        # the invariant of every refused cell: the protected file was never altered, at any run
        for call in fake.calls:
            for rel in ["tests/ci_mutants.py", ".github/workflows/strict-delivery.yml", TABLE,
                        ".strict-delivery/mutants/CI8.py", "tests/test_a.py"] + self.ORACLE_PATHS:
                self.assertEqual(call[2][rel], fake.pristine[rel], rel)
        self.assertEqual(self.status(), "")

    def test_the_protected_set_covers_every_killing_module_of_every_table(self):  # T6
        m = {"i1": ("tests/test_b.py", "assertEqual", "assertNotEqual"), "i2": ("src/a.py", "a + b", "a - b")}
        kill = {"i1": ("tests.test_a",), "i2": ("tests.test_b",)}  # i2's killing module is i1's mutated file
        self.repo({TABLE: table(m, kill)})
        code, out, err, fake = self.go()
        self.assertEqual(verdicts(out), {"i1": "ERROR", "i2": "SURVIVED"}, out)
        self.assertIn("protected", lines_of(out)["i1"][1])

    def cross_product_in_parts(self, parts, targets_first):
        """The same cross product on a run split in ``parts`` jobs: the ids that mutate a protected path (targets) are in
        one part, the ids that protect it (their table, their killing module) in another part, through main() per part."""
        first, second = ".strict-delivery/mutants/CI8.py", TABLE  # the sorted tables: ids of ``first`` come first
        target_table, other_table = (first, second) if targets_first else (second, first)
        paths = dict(self.PROTECTED, **{"table-itself": target_table, "other-table": other_table})
        m_t, k_t, expect = {}, {}, {}
        for n, (label, kind, relation, path) in enumerate(self.cells(paths)):
            m_t["t%02d" % n] = (path, "a + b", "a - b")
            k_t["t%02d" % n] = ("tests.test_b",)  # tests/test_a.py is no killing module of any target, only of the protectors
            expect["t%02d" % n] = (label, path)
        size = len(m_t) + 2
        controls = {"t%02d" % len(m_t): ("src/a.py", "a + b", "a - b"),  # allowed cells: an ordinary source file
                    "t%02d" % (len(m_t) + 1): ("tests/test_c.py", "assertTrue(True)", "assertTrue(False)")}  # no killer here
        m_t.update(controls)
        k_t.update({ident: ("tests.test_b",) for ident in controls})
        self.assertEqual(len(m_t), size)
        harmless = ("src/b.py", "'two'", "'three'")
        protectors = {"q%02d" % n: harmless for n in range(size)}  # their killing module tests.test_a is the protected path
        fillers = {"f%02d" % n: harmless for n in range(size)}
        table_first = m_t if targets_first else protectors
        table_second = dict(fillers if parts == 3 else {}, **(protectors if targets_first else m_t))
        kills = dict(k_t, **{ident: ("tests.test_a",) for ident in protectors}, **{ident: ("tests.test_b",) for ident in fillers})
        self.repo({first: table(table_first, {i: kills[i] for i in table_first}),
                   second: table(table_second, {i: kills[i] for i in table_second})}, base_extra=self.ORACLE_FILES)
        order = (["targets"] + ["fillers"] * (parts == 3) + ["protectors"]) if targets_first \
            else (["protectors"] + ["fillers"] * (parts == 3) + ["targets"])
        groups = {"targets": set(m_t), "protectors": set(protectors), "fillers": set(fillers)}
        protected_files = ["tests/test_a.py", "tests/ci_mutants.py", "tests/test_ci_mutants.py",
                           ".github/workflows/strict-delivery.yml", first, second] + self.ORACLE_PATHS
        watch =["src/a.py", "src/b.py", "tests/test_c.py"] + protected_files
        for k, name in enumerate(order, 1):
            fake = Fake(self.root, watch=watch)
            code, out, err = self.call(self.argv(part=k, parts=parts), execute=fake)
            got = verdicts(out)
            self.assertEqual(set(got), groups[name], (parts, k, name, out))  # the layout: this part holds exactly this group
            if name == "targets":
                self.assertEqual(code, 1, out)
                for ident, (label, path) in expect.items():
                    self.assertEqual(got[ident], "ERROR", (parts, label, path, lines_of(out)[ident]))
                    if label.endswith(("-equal", "-case-folded")):
                        self.assertIn("protected", lines_of(out)[ident][1], (parts, label))
                for ident in controls:
                    self.assertEqual(got[ident], "SURVIVED", (parts, ident, out))
            else:
                self.assertEqual((code, set(got.values())), (0, {"SURVIVED"}), (parts, k, name, out))
            for call in fake.calls:  # the invariant of every refused cell: no protected file was ever altered
                for rel in protected_files:
                    self.assertEqual(call[2][rel], fake.pristine[rel], (parts, k, rel))
            self.assertEqual(self.status(), "")

    def test_the_cross_product_holds_on_a_run_split_in_parts(self):  # T6, multi-part
        for parts, targets_first in itertools.product((2, 3), (True, False)):
            with self.subTest(parts=parts, targets_first=targets_first):
                self.cross_product_in_parts(parts, targets_first)


# ---- T7: replacement ----------------------------------------------------------------------------------------------
class ReplacementTest(Fx):
    def apply(self, body, old, new, rel="src/raw.py"):
        self.repo({TABLE: table({"i1": (rel, old, new)}, {"i1": ("tests.test_a",)})}, base_extra={rel: body})
        fake = Fake(self.root, watch=[rel])
        code, out, err = self.call(self.argv(), execute=fake)
        self.assertEqual(self.read(rel), body if isinstance(body, bytes) else body.encode("utf-8"))  # restored, byte for byte
        self.assertEqual(hashlib.sha256(self.read(rel)).hexdigest(),
                         hashlib.sha256(body if isinstance(body, bytes) else body.encode("utf-8")).hexdigest())
        self.assertEqual(self.status(), "")
        return code, out, fake

    def test_zero_one_and_many_matches(self):  # T7
        code, out, fake = self.apply("alpha beta\n", "gamma", "x")
        self.assertEqual((code, verdicts(out)), (0, {"i1": "NOT_APPLIED"}), out)
        self.assertIn("0 matches", out)
        self.assertEqual(fake.mutated_calls(), [])
        code, out, fake = self.apply("alpha beta\n", "beta", "gamma")
        self.assertEqual(verdicts(out), {"i1": "SURVIVED"}, out)
        self.assertEqual(fake.mutated_calls()[0][2]["src/raw.py"], b"alpha gamma\n")
        code, out, fake = self.apply("beta alpha beta\n", "beta", "x")
        self.assertEqual((code, verdicts(out)), (0, {"i1": "NOT_APPLIED"}), out)
        self.assertIn("2 or more matches", out)
        self.assertEqual(fake.mutated_calls(), [])

    def test_overlapping_occurrences_count(self):  # T7: str.count would say one
        code, out, fake = self.apply("xaaay\n", "aa", "b")
        self.assertEqual(verdicts(out), {"i1": "NOT_APPLIED"}, out)
        self.assertIn("2 or more matches", out)
        self.assertEqual(fake.mutated_calls(), [])
        code, out, fake = self.apply("xaay\n", "aa", "b")  # exactly once: applied
        self.assertEqual(verdicts(out), {"i1": "SURVIVED"}, out)
        self.assertEqual(fake.mutated_calls()[0][2]["src/raw.py"], b"xby\n")

    def test_old_text_spanning_a_line_break(self):  # T7
        code, out, fake = self.apply("one\ntwo\nthree\n", "one\ntwo", "ONE\nTWO")
        self.assertEqual(verdicts(out), {"i1": "SURVIVED"}, out)
        self.assertEqual(fake.mutated_calls()[0][2]["src/raw.py"], b"ONE\nTWO\nthree\n")

    def test_crlf_files_are_matched_and_written_bytewise(self):  # T7
        body = b"one\r\ntwo\r\nthree\r\n"
        code, out, fake = self.apply(body, "one\ntwo", "x")  # a bare LF does not match inside CRLF text: no translation
        self.assertEqual(verdicts(out), {"i1": "NOT_APPLIED"}, out)
        code, out, fake = self.apply(body, "one\r\ntwo", "ONE\r\nTWO")
        self.assertEqual(verdicts(out), {"i1": "SURVIVED"}, out)
        self.assertEqual(fake.mutated_calls()[0][2]["src/raw.py"], b"ONE\r\nTWO\r\nthree\r\n")  # the other CRLFs untouched
        code, out, fake = self.apply(body, "two", "2")
        self.assertEqual(fake.mutated_calls()[0][2]["src/raw.py"], b"one\r\n2\r\nthree\r\n")

    def test_replacement_that_contains_old_and_empty_new(self):  # T7
        code, out, fake = self.apply("k=1\n", "k=1", "k=1;k=1")
        self.assertEqual(fake.mutated_calls()[0][2]["src/raw.py"], b"k=1;k=1\n")
        code, out, fake = self.apply("a b c\n", " b", "")
        self.assertEqual(fake.mutated_calls()[0][2]["src/raw.py"], b"a c\n")
        code, out, fake = self.apply("a b c\n", "a b c\n", "")  # the whole file removed: the write opens truncate to 0 bytes
        self.assertEqual(fake.mutated_calls()[0][2]["src/raw.py"], b"")
        self.assertEqual(self.read("src/raw.py"), b"a b c\n")

    def test_numeric_text_of_4300_and_4301_digits(self):  # K1
        for digits in (4300, 4301):
            with self.subTest(digits):
                old, new = "7" * digits, "8" * digits
                code, out, fake = self.apply("x = %s\n" % old, old, new)
                self.assertEqual((code, verdicts(out)), (0, {"i1": "SURVIVED"}), out)
                self.assertEqual(fake.mutated_calls()[0][2]["src/raw.py"], ("x = %s\n" % new).encode())

    def test_code_point_with_version_dependent_category(self):  # K2: U+1E030 is unassigned in Unicode 13 (3.9), a letter in 15
        mark = "\U0001e030"
        body = "a%sb\n" % mark
        code, out, fake = self.apply(body, mark, "Z")
        self.assertEqual(verdicts(out), {"i1": "SURVIVED"}, out)
        self.assertEqual(fake.mutated_calls()[0][2]["src/raw.py"], b"aZb\n")
        code, out, fake = self.apply(body + body, mark, "Z")  # two matches on both interpreters, whatever str.isalpha says
        self.assertEqual(verdicts(out), {"i1": "NOT_APPLIED"}, out)


# ---- T8, T9, T10: outcomes, baseline, restore ----------------------------------------------------------------------
def killed_by_mutation(py, mods, mutated):
    return FAIL if mutated else PASS


class OutcomeTest(Fx):
    def test_the_five_outcomes_one_line_each(self):  # T8
        self.repo({TABLE: table(
            {"kil": ("src/a.py", "a + b", "a - b"), "sur": ("src/a.py", "VERSION = 1", "VERSION = 2"),
             "spl": ("src/b.py", "'one'", "'uno'"), "tim": ("src/b.py", "'two'", "'zwei'"),
             "err": ("src/a.py", "def add", "def sum")},
            {"kil": ("tests.test_a",), "sur": ("tests.test_c",), "spl": ("tests.test_b",), "tim": ("tests.test_b",),
             "err": ("tests.test_a",)})})

        def policy(py, mods, mutated):
            snap = self.read("src/a.py"), self.read("src/b.py")
            if not mutated:
                return PASS
            if b"a - b" in snap[0]:
                return FAIL
            if b"uno" in snap[1]:
                return FAIL if py == PY39 else PASS
            if b"zwei" in snap[1]:
                return HANG if py == PY313 else PASS
            if b"def sum" in snap[0]:
                raise RuntimeError("the fake runner broke")
            return PASS
        code, out, err, fake = self.go(Fake(self.root, policy))
        got = lines_of(out)
        self.assertEqual({k: v[0] for k, v in got.items()},
                         {"kil": "KILLED", "sur": "SURVIVED", "spl": "SPLIT", "tim": "TIMEOUT", "err": "ERROR"}, out)
        self.assertEqual(code, 1, out)  # an ERROR line makes the job exit non-zero
        self.assertRegex(out, r"(?m)^kil: KILLED \| 3\.9 Ran 3 tests FAILED ; 3\.13 Ran 3 tests FAILED$")
        self.assertRegex(out, r"(?m)^sur: SURVIVED \| 3\.9 Ran 3 tests OK ; 3\.13 Ran 3 tests OK$")
        self.assertRegex(out, r"(?m)^spl: SPLIT \| 3\.9 Ran 3 tests FAILED ; 3\.13 Ran 3 tests OK$")
        self.assertRegex(out, r"(?m)^tim: TIMEOUT \| 3\.9 Ran 3 tests OK ; 3\.13 timed out$")
        self.assertRegex(out, r"(?m)^err: ERROR \| RuntimeError: the fake runner broke$")
        self.assertEqual(self.status(), "")
        self.assertEqual(self.read("src/a.py"), BASE_FILES["src/a.py"].encode())

    def test_exit_zero_when_no_line_is_an_error(self):  # T8: KILLED, SURVIVED, SPLIT, NOT_APPLIED, TIMEOUT leave the exit code to the summary
        self.repo({TABLE: table({"a1": ("src/a.py", "a + b", "a - b"), "a2": ("src/a.py", "nothere", "x"),
                                 "a3": ("src/b.py", "'two'", "'zwei'")},
                                {"a1": ("tests.test_a",), "a2": ("tests.test_a",), "a3": ("tests.test_b",)})})
        code, out, err, fake = self.go(Fake(self.root, lambda py, mods, mutated: HANG if mutated and mods == ("tests.test_b",)
                                             else killed_by_mutation(py, mods, mutated)))
        self.assertEqual(verdicts(out), {"a1": "KILLED", "a2": "NOT_APPLIED", "a3": "TIMEOUT"}, out)
        self.assertEqual(code, 0, out)

    def test_a_run_with_no_ran_line_or_zero_tests_is_not_a_pass(self):  # T8
        self.repo({TABLE: table({"i1": ("src/a.py", "a + b", "a - b")}, {"i1": ("tests.test_a",)})})
        for text in ("", "OK\n", "Ran 0 tests in 0.0s\n\nOK\n"):
            with self.subTest(text):
                def policy(py, mods, mutated, text=text):
                    return PASS if not mutated else (0, text, False)
                code, out, err, fake = self.go(Fake(self.root, policy))
                self.assertEqual(verdicts(out), {"i1": "KILLED"}, out)

    def test_the_nonzero_exit_with_an_ok_text_is_a_failure(self):  # T8
        self.repo({TABLE: table({"i1": ("src/a.py", "a + b", "a - b")}, {"i1": ("tests.test_a",)})})
        code, out, err, fake = self.go(Fake(self.root, lambda py, mods, mutated: PASS if not mutated else (1, PASS[1], False)))
        self.assertEqual(verdicts(out), {"i1": "KILLED"}, out)

    def test_both_interpreters_get_the_same_modules_and_the_timeout(self):  # T8
        self.repo()
        code, out, err, fake = self.go()
        mut = fake.mutated_calls()
        self.assertEqual(sorted({c[0] for c in mut}), sorted([PY39, PY313]))
        self.assertEqual({c[3] for c in fake.calls}, {ci_mutants.DEFAULT_TIMEOUT})
        code, out, err = self.call(self.argv(extra=["--timeout", "7"]), execute=(f := Fake(self.root)))
        self.assertEqual({c[3] for c in f.calls}, {7})

    # ---- T9
    def test_failing_baseline_is_an_error_for_every_id_of_that_module(self):  # T9 (a1 and a3 share the failing KILL tuple)
        self.repo({TABLE: table(
            {"a1": ("src/a.py", "a + b", "a - b"), "a2": ("src/a.py", "VERSION = 1", "VERSION = 2"),
             "a3": ("src/a.py", "return a", "return 0 + a"), "b1": ("src/b.py", "'two'", "'three'")},
            {"a1": ("tests.test_a",), "a2": ("tests.test_a", "tests.test_c"), "a3": ("tests.test_a",),
             "b1": ("tests.test_b",)})})

        def policy(py, mods, mutated):
            if not mutated and mods == ("tests.test_a",) and py == PY39:
                return FAIL
            return PASS
        code, out, err, fake = self.go(Fake(self.root, policy))
        # a2's tuple (test_a, test_c) is baselined as it is run (F-20261126-rw5k): it passes, so a2 runs
        self.assertEqual(verdicts(out), {"a1": "ERROR", "a2": "SURVIVED", "a3": "ERROR", "b1": "SURVIVED"}, out)
        for ident in ("a1", "a3"):
            self.assertIn("baseline", lines_of(out)[ident][1])
            self.assertIn("tests.test_a", lines_of(out)[ident][1])
            self.assertIn("3.9", lines_of(out)[ident][1])
        self.assertEqual(code, 1)
        self.assertEqual({c[1] for c in fake.mutated_calls()}, {("tests.test_b",), ("tests.test_a", "tests.test_c")})  # no mutation of an id with a bad baseline

    def test_passing_baseline_runs_each_kill_tuple_once_per_interpreter_before_any_mutation(self):  # T9 (the tuple, as it is run)
        self.repo({TABLE: table(
            {"a1": ("src/a.py", "a + b", "a - b"), "a2": ("src/a.py", "VERSION = 1", "VERSION = 2")},
            {"a1": ("tests.test_a", "tests.test_c"), "a2": ("tests.test_a",)})})
        code, out, err, fake = self.go()
        base = fake.baseline_calls()
        self.assertEqual(sorted((c[0], c[1]) for c in base),
                         sorted([(PY39, ("tests.test_a",)), (PY313, ("tests.test_a",)),
                                 (PY39, ("tests.test_a", "tests.test_c")), (PY313, ("tests.test_a", "tests.test_c"))]))
        first_mut = min(i for i, c in enumerate(fake.calls) if c[2] != fake.pristine)
        self.assertTrue(all(c[2] == fake.pristine for c in fake.calls[:first_mut]))
        self.assertEqual(len(base), 4)
        self.assertEqual(code, 0)

    def test_baseline_timeout_is_a_baseline_failure(self):  # T9
        self.repo()
        code, out, err, fake = self.go(Fake(self.root, lambda py, mods, mutated: HANG if not mutated else PASS))
        self.assertEqual(verdicts(out), {"i1": "ERROR", "i2": "ERROR"}, out)
        self.assertIn("baseline", lines_of(out)["i1"][1])
        self.assertEqual(fake.mutated_calls(), [])

    # ---- T10
    def test_file_is_restored_after_every_outcome_including_timeout_and_exception(self):  # T10
        for label, policy in (("killed", killed_by_mutation), ("timeout", lambda py, m, mu: HANG if mu else PASS),
                              ("raise", self.raiser)):
            with self.subTest(label):
                self.work_reset()
                self.repo()
                before = {rel: self.read(rel) for rel in ("src/a.py", "src/b.py")}
                seen = []

                def watch(py, mods, mutated, policy=policy):
                    seen.append({rel: self.read(rel) for rel in ("src/a.py", "src/b.py")})
                    return policy(py, mods, mutated)
                code, out, err, fake = self.go(Fake(self.root, watch))
                self.assertTrue(any(s != before for s in seen), label)  # the file really was mutated while it ran
                self.assertEqual({rel: self.read(rel) for rel in before}, before, label)
                self.assertEqual(self.status(), "", label)

    @staticmethod
    def raiser(py, mods, mutated):
        if mutated:
            raise OSError("boom")
        return PASS

    def work_reset(self):
        self.work = os.path.join(self.tmp, "work%d" % next(COUNTER))
        os.mkdir(self.work)

    def test_a_run_that_leaves_an_untracked_file_is_an_error_and_stops_the_job(self):  # T10
        self.repo({TABLE: table({"a1": ("src/a.py", "a + b", "a - b"), "a2": ("src/a.py", "VERSION = 1", "VERSION = 2"),
                                 "a3": ("src/b.py", "'two'", "'three'")},
                                {"a1": ("tests.test_a",), "a2": ("tests.test_a",), "a3": ("tests.test_b",)})})

        def policy(py, mods, mutated):
            if mutated:
                with open(os.path.join(self.root, "litter.txt"), "w") as fh:
                    fh.write("x")
            return PASS
        code, out, err, fake = self.go(Fake(self.root, policy))
        got = lines_of(out)
        self.assertEqual({k: v[0] for k, v in got.items()}, {"a1": "ERROR", "a2": "ERROR", "a3": "ERROR"}, out)
        self.assertIn("tree is not clean", got["a1"][1])
        self.assertIn("not run", got["a2"][1])
        self.assertIn("not run", got["a3"][1])
        self.assertEqual(code, 1)
        self.assertEqual(len(fake.mutated_calls()), 2)  # only a1's pair of runs; a2 and a3 never started
        self.assertEqual(self.read("src/a.py"), BASE_FILES["src/a.py"].encode())  # the mutated file is restored anyway

    def test_a_run_that_changes_another_tracked_file_is_an_error(self):  # T10
        def policy(py, mods, mutated):
            if mutated:
                self.put("docs/readme.txt", "changed\n")
            return PASS
        self.repo()
        code, out, err, fake = self.go(Fake(self.root, policy))
        self.assertEqual(verdicts(out), {"i1": "ERROR", "i2": "ERROR"}, out)
        self.assertIn("tree is not clean", lines_of(out)["i1"][1])
        self.assertEqual(code, 1)

    def test_a_dirty_tree_at_the_start_runs_nothing(self):  # T10
        self.repo()
        self.put("docs/readme.txt", "dirty\n")
        fake = Fake(self.root)
        code, out, err = self.call(self.argv(), execute=fake)
        self.assertEqual(code, 1, out)
        self.assertRegex(out, r"(?m)^ERROR tree: .*not clean")
        self.assertEqual(fake.calls, [])
        self.assertEqual(verdicts(out), {})

    def test_an_untracked_file_at_the_start_runs_nothing(self):  # T10: --untracked-files=all
        self.repo()
        self.put("deep/er/file.txt", "x\n")
        fake = Fake(self.root)
        code, out, err = self.call(self.argv(), execute=fake)
        self.assertEqual(code, 1, out)
        self.assertEqual(fake.calls, [])

    def test_a_baseline_that_dirties_the_tree_stops_before_any_mutation(self):  # T10
        self.repo()

        def policy(py, mods, mutated):
            self.put("litter.txt", "x")
            return PASS
        code, out, err, fake = self.go(Fake(self.root, policy))
        self.assertEqual(code, 1, out)
        self.assertEqual(verdicts(out), {"i1": "ERROR", "i2": "ERROR"}, out)
        self.assertEqual(fake.mutated_calls(), [])

    def test_the_head_must_be_the_checkout(self):  # T11 head
        self.repo()
        git(self.root, "checkout", "-q", "main")
        fake = Fake(self.root)
        code, out, err = self.call(self.argv(), execute=fake)
        self.assertEqual(code, 1, out)
        self.assertRegex(out, r"(?m)^ERROR head: ")
        self.assertEqual(fake.calls, [])


# ---- T11: change detection ----------------------------------------------------------------------------------------
class ChangeTest(Fx):
    def split_ids(self, **kw):
        code, out, err = self.call(self.argv("split", **kw))
        self.assertEqual(err, "")
        return code, out

    def ids(self, out):
        return sorted(ln.split()[1] for ln in out.splitlines() if ln.startswith("  "))

    def test_added_table_runs_all_its_ids(self):  # T11
        self.repo()
        code, out = self.split_ids()
        self.assertEqual((code, self.ids(out)), (0, ["i1", "i2"]), out)

    def test_modified_table_runs_all_its_ids(self):  # T11
        self.repo({}, base_extra={TABLE: SIMPLE})
        git(self.root, "checkout", "-q", "-b", "mod")
        self.put(TABLE, table(dict(SIMPLE_M, i3=("src/b.py", "'one'", "'1'")), dict(SIMPLE_KILL, i3=("tests.test_b",))))
        head = commit_all(self.root, "modify")
        code, out = self.split_ids(head=head)
        self.assertEqual((code, self.ids(out)), (0, ["i1", "i2", "i3"]), out)  # the unchanged ids run again too

    def test_renamed_table_runs_under_its_new_name(self):  # T11
        self.repo({}, base_extra={".strict-delivery/mutants/OLD.py": SIMPLE})
        git(self.root, "checkout", "-q", "-b", "ren")
        git(self.root, "mv", ".strict-delivery/mutants/OLD.py", ".strict-delivery/mutants/NEW.py")
        head = commit_all(self.root, "rename")
        code, out = self.split_ids(head=head)
        self.assertEqual((code, self.ids(out)), (0, ["i1", "i2"]), out)
        self.assertIn(".strict-delivery/mutants/NEW.py", out)
        self.assertNotIn("OLD.py", out)

    def test_deleted_table_runs_nothing(self):  # T11
        self.repo({}, base_extra={TABLE: SIMPLE})
        git(self.root, "checkout", "-q", "-b", "del")
        git(self.root, "rm", "-q", TABLE)
        head = commit_all(self.root, "delete")
        code, out = self.split_ids(head=head)
        self.assertEqual((code, self.ids(out)), (0, []), out)

    def test_no_table_changed_passes_with_an_explicit_line(self):  # T11
        self.repo({"docs/other.txt": "x\n"})
        fake = Fake(self.root)
        code, out, err = self.call(self.argv(), execute=fake)
        self.assertEqual((code, fake.calls), (0, []), out)
        self.assertIn("ci_mutants: no mutant tables changed", out)
        self.repo({}, base_extra={TABLE: SIMPLE}, head_extra={"docs/other.txt": "y\n"})  # an unchanged table does not run
        code, out, err = self.call(self.argv(), execute=Fake(self.root))
        self.assertIn("no mutant tables changed", out)

    def test_whitespace_only_change_still_runs(self):  # T11
        self.repo({}, base_extra={TABLE: SIMPLE})
        git(self.root, "checkout", "-q", "-b", "ws")
        self.put(TABLE, SIMPLE + "\n\n")
        head = commit_all(self.root, "whitespace")
        code, out = self.split_ids(head=head)
        self.assertEqual(self.ids(out), ["i1", "i2"], out)

    def test_missing_or_unrelated_base_fails_closed(self):  # T11
        self.repo()
        for base in ("nosuchbranch", "origin/main", "0" * 40):
            with self.subTest(base):
                fake = Fake(self.root)
                code, out, err = self.call(self.argv(base=base), execute=fake)
                self.assertEqual(code, 1, out)
                self.assertRegex(out, r"(?m)^ERROR base %s: " % re.escape(base))
                self.assertEqual(fake.calls, [])
        tree = subprocess.run(["git", "-C", self.root, "mktree"], input=b"", stdout=subprocess.PIPE, check=True).stdout.strip()
        orphan = git(self.root, "commit-tree", tree.decode(), "-m", "unrelated")
        git(self.root, "branch", "unrelated", orphan)
        fake = Fake(self.root)
        code, out, err = self.call(self.argv(base="unrelated"), execute=fake)
        self.assertEqual(code, 1, out)
        self.assertRegex(out, r"(?m)^ERROR base unrelated: .*history")
        self.assertEqual(fake.calls, [])

    def test_the_diff_is_against_the_merge_base_not_the_base_tip(self):  # T11
        self.repo({}, base_extra={TABLE: SIMPLE})
        git(self.root, "checkout", "-q", "main")
        self.put(".strict-delivery/mutants/LATER.py", SIMPLE.replace("i1", "m1").replace("i2", "m2"))
        commit_all(self.root, "main moves on")  # a table the PR did not touch
        git(self.root, "checkout", "-q", "feature")
        code, out = self.split_ids(head=git(self.root, "rev-parse", "HEAD"))
        self.assertEqual((code, self.ids(out)), (0, []), out)  # LATER.py is not in the PR's diff

    def test_option_like_refs_are_refused_before_git_runs(self):  # T11: never passed through to git as an option
        self.repo()
        for base in ("--output=x", "-x", "a b", "a;b", "", "a\nb", "a..b", "@{u}", "a:b"):
            with self.subTest(base):
                code, out, err = self.call(self.argv(base=base))
                self.assertEqual((code, out), (2, ""), err)
                self.assertTrue(err.startswith("ci_mutants: refused: --base "), err)


# ---- T12: split ---------------------------------------------------------------------------------------------------
class SplitTest(Fx):
    def test_function_properties(self):  # T12
        for parts in range(1, 9):
            for n in list(range(0, 30)) + [101, 500]:
                items = [("t%d" % (i % 3), "id%04d" % i) for i in range(n)]
                got = ci_mutants.split(items, parts)
                self.assertEqual(len(got), parts)
                flat = [x for part in got for x in part]
                self.assertEqual(sorted(flat), sorted(items), (parts, n))  # union is the set
                self.assertEqual(len(flat), len(set(flat)), (parts, n))  # no id twice
                sizes = [len(p) for p in got]
                self.assertLessEqual(max(sizes) - min(sizes), 1, (parts, n, sizes))
                self.assertEqual(sizes, sorted(sizes, reverse=True))  # the larger parts come first

    def test_deterministic_from_the_sorted_ids_only(self):  # T12
        items = [("CI9.py", "b"), ("CI9.py", "a"), ("CI1.py", "z"), ("CI1.py", "a"), ("CI5.py", "m")]
        want = ci_mutants.split(sorted(items), 2)
        self.assertEqual(ci_mutants.split(items, 2), want)
        self.assertEqual(ci_mutants.split(list(reversed(items)), 2), want)
        self.assertEqual(want, [[("CI1.py", "a"), ("CI1.py", "z"), ("CI5.py", "m")], [("CI9.py", "a"), ("CI9.py", "b")]])

    def test_zero_fewer_equal_and_many_through_main(self):  # T12
        for n, parts in ((0, 3), (1, 3), (2, 3), (3, 3), (4, 3), (11, 4)):
            with self.subTest((n, parts)):
                ids = ["m%02d" % i for i in range(n)]
                m = {i: ("src/a.py", "a + b", "a - b") for i in ids}
                self.repo({TABLE: table(m, {i: ("tests.test_a",) for i in ids})}) if n else self.repo({TABLE: table({}, {})})
                seen = []
                for k in range(1, parts + 1):
                    code, out, err = self.call(self.argv("split", part=k, parts=parts))
                    self.assertEqual((code, err), (0, ""), out)
                    seen.append([ln.split()[1] for ln in out.splitlines() if ln.startswith("  ")])
                self.assertEqual(sorted(x for s in seen for x in s), ids)
                sizes = [len(s) for s in seen]
                self.assertLessEqual(max(sizes) - min(sizes), 1, sizes)
                self.work_reset()

    def work_reset(self):
        self.work = os.path.join(self.tmp, "work%d" % next(COUNTER))
        os.mkdir(self.work)

    def test_an_empty_part_passes_and_says_so(self):  # T12
        self.repo()
        code, out, err, fake = self.go(parts=4, part=4)  # two ids, four parts: part 4 has none
        self.assertEqual((code, fake.calls), (0, []), out)
        self.assertIn("ci_mutants: part 4 of 4 has no mutants", out)

    def test_run_takes_its_own_slice(self):  # T12
        self.repo()
        code, out, err, fake = self.go(parts=2, part=2)
        self.assertEqual(verdicts(out), {"i2": "SURVIVED"}, out)
        self.assertEqual({c[1] for c in fake.calls}, {("tests.test_b",)})  # only its modules, baseline included

    def test_refused_arguments_exit_two(self):  # T12 like ci_shards
        self.repo()
        bad_numbers = ["0", "-1", "+5", " 5", "5 ", "5\n", "5.0", "0x5", "\u0665", "", "05", "1000000", "5_0", "--part"]
        for text in bad_numbers:
            for option in ("--parts", "--part"):
                argv = self.argv("split", extra=[])
                argv[argv.index(option) + 1] = text
                code, out, err = self.call(argv)
                self.assertEqual((code, out), (2, ""), (option, text, err))
                self.assertIn("ci_mutants: refused: %s needs a whole number from 1 to 999999" % option, err)
        for text in ("9" * 4300, "9" * 4301):  # K1: numeric text is never turned into an int
            argv = self.argv("split")
            argv[argv.index("--parts") + 1] = text
            code, out, err = self.call(argv)
            self.assertEqual((code, out), (2, ""))
        code, out, err = self.call(self.argv("split", part=3, parts=2))
        self.assertEqual((code, out), (2, ""))
        self.assertIn("--part 3 is past --parts 2", err)
        for argv, needle in (([], "usage"), (["nosuch"], "unknown command"), (["split", "--parts", "1", "--part", "1"], "--base is required"),
                             (["split", "--base", "main", "--base", "main"], "given twice"),
                             (["split", "--bogus", "1"], "unknown argument"), (["split", "--base"], "needs a value"),
                             (["run", "--base", "main", "--head", "x" * 40, "--parts", "1", "--part", "1"], "--head needs"),
                             (["summary", "--base", "main", "--head", "a" * 40, "--parts", "1", "--part", "1"], "unknown argument")):
            code, out, err = self.call(argv)
            self.assertEqual((code, out), (2, ""), argv)
            self.assertIn(needle, err, argv)
            self.assertEqual(err.count("\n"), 1, err)

    def test_run_arguments_python_and_timeout(self):  # T12
        self.repo()
        base = ["run", "--base", "main", "--head", self.head, "--parts", "1", "--part", "1"]
        for extra, needle in (([], "--python"), (["--python", "3.9=" + PY39], "two --python"),
                              (["--python", "3.9=" + PY39, "--python", "3.9=" + PY313], "twice"),
                              (["--python", "3.9=relative/py", "--python", "3.13=" + PY313], "absolute"),
                              (["--python", "3.9", "--python", "3.13=" + PY313], "LABEL=PATH"),
                              (["--python", "=" + PY39, "--python", "3.13=" + PY313], "LABEL=PATH"),
                              (["--python", "a b=" + PY39, "--python", "3.13=" + PY313], "LABEL=PATH"),
                              (PYTHONS + ["--timeout", "0"], "--timeout needs"), (PYTHONS + ["--timeout", "1e3"], "--timeout needs")):
            code, out, err = self.call(base + extra)
            self.assertEqual((code, out), (2, ""), extra)
            self.assertIn(needle, err, extra)

    def test_the_command_line_entry_point(self):  # T12: python -m tests.ci_mutants, refusal exits 2
        p = subprocess.run([sys.executable, "-m", "tests.ci_mutants", "split", "--parts", "0"], cwd=REPO,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
        self.assertEqual((p.returncode, p.stdout), (2, ""))
        self.assertIn("ci_mutants: refused: --parts needs a whole number", p.stderr)


# ---- T13: summary -------------------------------------------------------------------------------------------------
class SummaryTest(Fx):
    IDS = ["s%d" % i for i in range(1, 7)]

    def setup_repo(self):
        m = {i: ("src/a.py", "a + b", "a - b") for i in self.IDS}
        self.repo({TABLE: table(m, {i: ("tests.test_a",) for i in self.IDS})})

    def lines(self, ids, verdict="KILLED"):
        return "\n".join("%s: %s | 3.9 Ran 3 tests FAILED ; 3.13 Ran 3 tests FAILED" % (i, verdict) for i in ids)

    def env(self, results, lines):
        env = {}
        for k, (res, text) in enumerate(zip(results, lines), 1):
            if res is not None:
                env["MUTANT_RESULT_%d" % k] = res
            if text is not None:
                env["MUTANT_LINES_%d" % k] = text
        return env

    def summary(self, results, lines, parts=2):
        return self.call(self.argv("summary", parts=parts), env=self.env(results, lines))

    def split_lines(self, verdicts_by_id=None):
        """The lines the two parts would print, with the verdict of ``verdicts_by_id`` for the ids named in it."""
        verdicts_by_id = verdicts_by_id or {}
        parts = ci_mutants.split([(TABLE, i) for i in self.IDS], 2)
        out = []
        for part in parts:
            out.append("\n".join("%s: %s | 3.9 Ran 3 tests FAILED ; 3.13 Ran 3 tests FAILED" % (i, verdicts_by_id.get(i, "KILLED"))
                                 for _, i in part))
        return out

    def test_all_killed_and_survived_passes_and_lists_survivors(self):  # T13
        self.setup_repo()
        a, b = self.split_lines({"s2": "SURVIVED", "s5": "SPLIT"})
        code, out, err = self.summary(["success", "success"], [a, b])
        self.assertEqual(code, 0, out)
        self.assertRegex(out, r"(?m)^survivor: s2 ")
        self.assertRegex(out, r"(?m)^split: s5 ")
        self.assertIn("6 mutants: KILLED 4, SURVIVED 1, SPLIT 1", out)

    def test_each_failing_verdict_fails(self):  # T13
        self.setup_repo()
        for verdict in ("NOT_APPLIED", "TIMEOUT", "ERROR"):
            with self.subTest(verdict):
                a, b = self.split_lines({"s3": verdict})
                code, out, err = self.summary(["success", "success"], [a, b])
                self.assertEqual(code, 1, out)
                self.assertRegex(out, r"(?m)^FAIL s3: %s" % verdict)

    def test_non_success_jobs_fail(self):  # T13
        self.setup_repo()
        a, b = self.split_lines()
        for result in ("failure", "cancelled", "skipped", "", "SUCCESS", "success ", "neutral"):
            with self.subTest(result):
                code, out, err = self.summary(["success", result], [a, b])
                self.assertEqual(code, 1, out)
                self.assertRegex(out, r"(?m)^FAIL job 2: result %s" % re.escape(repr(result)))
        code, out, err = self.summary(["success", None], [a, b])  # a job that never reported at all
        self.assertEqual(code, 1, out)
        self.assertRegex(out, r"(?m)^FAIL job 2: no result")

    def test_a_crashed_job_with_no_lines_fails_on_both_counts(self):  # T13
        self.setup_repo()
        a, b = self.split_lines()
        code, out, err = self.summary(["success", "failure"], [a, None])
        self.assertEqual(code, 1, out)
        self.assertRegex(out, r"(?m)^FAIL job 2: result 'failure'")
        self.assertRegex(out, r"(?m)^FAIL s4: no line")

    def test_missing_duplicated_and_unknown_lines_fail(self):  # T13
        self.setup_repo()
        a, b = self.split_lines()
        missing = "\n".join(a.splitlines()[:-1])
        code, out, err = self.summary(["success", "success"], [missing, b])
        self.assertEqual(code, 1, out)
        self.assertRegex(out, r"(?m)^FAIL s3: no line")
        code, out, err = self.summary(["success", "success"], [a + "\n" + b.splitlines()[0], b])  # across jobs
        self.assertEqual(code, 1, out)
        self.assertRegex(out, r"(?m)^FAIL s4: 2 lines")
        code, out, err = self.summary(["success", "success"], [a + "\n" + a.splitlines()[0], b])  # inside one job
        self.assertEqual(code, 1, out)
        self.assertRegex(out, r"(?m)^FAIL s1: 2 lines")
        code, out, err = self.summary(["success", "success"], [a + "\nghost: KILLED | x", b])
        self.assertEqual(code, 1, out)
        self.assertRegex(out, r"(?m)^FAIL ghost: unknown id")

    def test_an_unreadable_line_fails(self):  # T13
        self.setup_repo()
        a, b = self.split_lines()
        for junk in ("s1 KILLED", "s1: MAYBE | x", "s1:KILLED", ": KILLED", "::error::x", "killed: s1"):
            with self.subTest(junk):
                code, out, err = self.summary(["success", "success"], [a + "\n" + junk, b])
                self.assertEqual(code, 1, out)
                self.assertRegex(out, r"(?m)^FAIL job 1: unreadable line")
        code, out, err = self.summary(["success", "success"], [a + "\n\n", b])  # blank lines are not lines
        self.assertEqual(code, 0, out)

    def test_no_tables_changed_passes(self):  # T13, T11
        self.repo({"docs/x.txt": "x\n"})
        code, out, err = self.summary(["success", "success"], ["", ""])
        self.assertEqual(code, 0, out)
        self.assertIn("ci_mutants: no mutant tables changed", out)
        code, out, err = self.summary(["success", "skipped"], ["", ""])
        self.assertEqual(code, 1, out)
        code, out, err = self.summary(["success", "success"], ["s1: KILLED | x", ""])  # a line with no table
        self.assertEqual(code, 1, out)

    def test_a_refused_table_fails_the_summary(self):  # T13
        self.repo({TABLE: "M = {}\n"})
        code, out, err = self.summary(["success", "success"], ["", ""])
        self.assertEqual(code, 1, out)
        self.assertRegex(out, r"(?m)^ERROR table %s" % re.escape(TABLE))

    def test_lines_that_forge_workflow_commands_are_not_echoed_as_commands(self):  # T13
        self.setup_repo()
        a, b = self.split_lines()
        code, out, err = self.summary(["success", "success"], [a + "\n::set-output name=x::y", b])
        self.assertEqual(code, 1, out)
        self.assertFalse([ln for ln in out.splitlines() if ln.startswith("::")], out)


# ---- GITHUB_OUTPUT ------------------------------------------------------------------------------------------------
class OutputFileTest(Fx):
    def test_lines_are_written_as_a_multiline_output(self):  # T13: the summary reads them back through the job output
        self.repo()
        path = os.path.join(self.tmp, "github_output")
        fake = Fake(self.root, killed_by_mutation)
        code, out, err = self.call(self.argv(), execute=fake, env={"GITHUB_OUTPUT": path})
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        m = re.fullmatch(r"lines<<(ci_mutants_[0-9a-f]{32})\n(.*)\n\1\n", text, re.S)
        self.assertIsNotNone(m, text)
        self.assertEqual(verdicts(m.group(2)), {"i1": "KILLED", "i2": "KILLED"})
        self.assertEqual(sorted(m.group(2).splitlines()), sorted(ln for ln in out.splitlines() if LINE.match(ln)))
        # the summary accepts exactly that text
        code, out2, err = self.call(self.argv("summary"), env={"MUTANT_RESULT_1": "success", "MUTANT_LINES_1": m.group(2)})
        self.assertEqual(code, 0, out2)

    def test_empty_part_writes_an_empty_output(self):  # T12
        self.repo()
        path = os.path.join(self.tmp, "github_output")
        code, out, err = self.call(self.argv(parts=4, part=4), execute=Fake(self.root), env={"GITHUB_OUTPUT": path})
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        self.assertRegex(text, r"\Alines<<ci_mutants_[0-9a-f]{32}\n\nci_mutants_[0-9a-f]{32}\n\Z")

    def test_an_unwritable_output_file_is_an_error(self):  # T10 fail closed
        self.repo()
        code, out, err = self.call(self.argv(), execute=Fake(self.root), env={"GITHUB_OUTPUT": os.path.join(self.tmp, "nodir", "x")})
        self.assertEqual(code, 1, out)
        self.assertRegex(out, r"(?m)^ERROR output: ")


# ---- the real runner on a real fixture ----------------------------------------------------------------------------
class RealRunTest(Fx):
    def test_real_unittest_runs_kill_survive_and_time_out(self):  # T8: no fake; this interpreter runs the fixture tests twice
        m = {"k1": ("src/a.py", "a + b", "a - b"), "s1": ("src/a.py", "VERSION = 1", "VERSION = 2"),
             "t1": ("src/a.py", "return a + b", "while True:\n        pass")}
        self.repo({TABLE: table(m, {i: ("tests.test_a",) for i in m})})
        argv = ["run", "--base", "main", "--head", self.head, "--parts", "1", "--part", "1",
                "--python", "A=" + sys.executable, "--python", "B=" + sys.executable, "--timeout", "3"]
        code, out, err = self.call(argv)
        self.assertEqual(verdicts(out), {"k1": "KILLED", "s1": "SURVIVED", "t1": "TIMEOUT"}, out + err)
        self.assertRegex(out, r"(?m)^k1: KILLED \| A Ran 1 test FAILED ; B Ran 1 test FAILED$")
        self.assertEqual(self.status(), "")
        self.assertEqual(self.read("src/a.py"), BASE_FILES["src/a.py"].encode())

    def test_a_missing_interpreter_is_an_error_not_a_pass(self):  # T8
        self.repo()
        argv = self.argv()
        code, out, err = self.call(argv)  # the real execute with /fake/python...: nothing can start
        self.assertEqual(code, 1, out)
        self.assertEqual(set(verdicts(out).values()), {"ERROR"}, out)
        self.assertEqual(self.status(), "")


# ---- T14: the workflow, as text ----------------------------------------------------------------------------------
JOBS = ("mutants-1", "mutants-2", "mutants-3", "mutants-4")
CHECKOUT = ("      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1  # v7.0.1\n"
            "        with:\n"
            "          ref: ${{ github.event.pull_request.head.sha }}\n"
            "          fetch-depth: 0\n")
SETUP = ("      - id: py%s\n"
         "        uses: actions/setup-python@6d4fd22b20465ccc0f7354476588e8df7c9ca0e0  # v7.1.0\n"
         "        with:\n"
         "          python-version: \"%s\"\n")


def mutants_job(k):
    return ("  mutants-%d:\n"
            "    if: github.event_name == 'pull_request'\n"
            "    runs-on: ubuntu-24.04\n"
            "    timeout-minutes: 120\n"
            "    outputs:\n"
            "      lines: ${{ steps.run.outputs.lines }}\n"
            "    steps:\n" % k + CHECKOUT + SETUP % ("39", "3.9") + SETUP % ("313", "3.13") +
            "      - id: run\n"
            "        env:\n"
            "          BASE_REF: ${{ github.base_ref }}\n"
            "          HEAD_SHA: ${{ github.event.pull_request.head.sha }}\n"
            "          PY39: ${{ steps.py39.outputs.python-path }}\n"
            "          PY313: ${{ steps.py313.outputs.python-path }}\n"
            "        run: python -m tests.ci_mutants run --base \"origin/$BASE_REF\" --head \"$HEAD_SHA\" --parts 4 --part %d "
            "--python \"3.9=$PY39\" --python \"3.13=$PY313\"\n" % k)


class WorkflowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = sa.read_text(os.path.join(REPO, sa.WORKFLOW))

    def job(self, name):
        return sa.job_text(self.text, name)

    def test_the_mutation_jobs_byte_for_byte(self):  # T14
        for k, name in enumerate(JOBS, 1):
            self.assertEqual(self.job(name), mutants_job(k), name)

    def test_the_summary_job(self):  # T14
        job = self.job("mutants-summary")
        lines = sa.code_lines(job)
        self.assertEqual(lines[:6], ["  mutants-summary:", "    needs: [mutants-1, mutants-2, mutants-3, mutants-4]",
                                     "    if: always() && github.event_name == 'pull_request'", "    runs-on: ubuntu-24.04",
                                     "    steps:", "      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1"])
        st = sa.steps(job)
        self.assertEqual(st[0]["ref"], "${{ github.event.pull_request.head.sha }}")
        self.assertEqual(st[0]["fetch-depth"], "0")
        self.assertEqual(st[1]["python-version"], '"3.13"')
        env = st[2]
        self.assertEqual(env["run"], 'python -m tests.ci_mutants summary --base "origin/$BASE_REF" --head "$HEAD_SHA" --parts 4')
        for k in range(1, 5):
            self.assertEqual(env["MUTANT_RESULT_%d" % k], "${{ needs.mutants-%d.result }}" % k)
            self.assertEqual(env["MUTANT_LINES_%d" % k], "${{ needs.mutants-%d.outputs.lines }}" % k)
        self.assertEqual(env["BASE_REF"], "${{ github.base_ref }}")
        self.assertEqual(env["HEAD_SHA"], "${{ github.event.pull_request.head.sha }}")
        self.assertEqual(len(sa.steps(job)), 3)

    def test_parts_agree_across_the_jobs_and_the_summary(self):  # T14
        for k, name in enumerate(JOBS, 1):
            run = [st["run"] for st in sa.steps(self.job(name)) if "run" in st]
            self.assertEqual(len(run), 1)
            self.assertIn("--parts 4 --part %d " % k, run[0])
        self.assertEqual(len(JOBS), 4)
        self.assertIn("--parts 4", self.job("mutants-summary"))
        self.assertEqual(self.text.count("tests.ci_mutants"), 5)

    def test_existing_jobs_are_byte_for_byte(self):  # T14
        self.assertEqual(self.job("gates"), sa.GATES_JOB)
        self.assertEqual(self.job("shard"), sa.SHARD_JOB)
        pr = self.job("pull-request")
        self.assertEqual(hashlib.sha256(pr.encode("utf-8")).hexdigest(), PULL_REQUEST_SHA256)

    def test_new_jobs_run_on_pull_request_only_with_pinned_actions(self):  # T14
        for name in JOBS + ("mutants-summary",):
            job = self.job(name)
            self.assertIn("    if: github.event_name == 'pull_request'" if name != "mutants-summary"
                          else "    if: always() && github.event_name == 'pull_request'", sa.code_lines(job))
            self.assertIn("    runs-on: ubuntu-24.04", sa.code_lines(job))
            self.assertNotIn("matrix", job)
            for value in sa.uses(job):
                self.assertRegex(value, r"[^@\s]+@[0-9a-f]{40}$")
            self.assertEqual({v.split("@")[0] for v in sa.uses(job)}, {"actions/checkout", "actions/setup-python"})
            self.assertEqual(sa.steps(job)[0]["ref"], "${{ github.event.pull_request.head.sha }}")
            self.assertEqual(sa.steps(job)[0]["fetch-depth"], "0")
            self.assertEqual([ln for ln in job.splitlines() if "${{" in ln and "run:" in ln], [])  # values reach the shell through env
        for name in JOBS:
            self.assertEqual([st["python-version"] for st in sa.steps(self.job(name)) if "python-version" in st],
                             ['"3.9"', '"3.13"'])
        for repo, (sha, tag) in sa.PINS.items():  # every use of an action in the file is one of the two pinned ones, with its tag comment
            self.assertEqual(self.text.count("uses: %s@%s  # %s\n" % (repo, sha, tag)), self.text.count("uses: %s@" % repo))
        # six before CI3; then checkout + two setup-python in each of four jobs, and checkout + setup-python in the summary
        self.assertEqual(len(sa.uses(self.text)), 6 + 4 * 3 + 2)

    def test_job_order_and_no_other_job(self):  # T14
        names = re.findall(r"(?m)^  ([a-z][a-z0-9-]*):$", self.text.split("\njobs:\n", 1)[1])
        self.assertEqual(names, ["shard", "gates", "pull-request"] + list(JOBS) + ["mutants-summary"])

    def test_no_exception_group_in_the_new_files(self):  # K3 (PC1): the exception-group classes are absent on 3.9
        word = "Exception" + "Group"
        for rel in ("tests/ci_mutants.py", "tests/test_ci_mutants.py", sa.WORKFLOW):
            self.assertNotIn(word, sa.read_text(os.path.join(REPO, rel)), rel)

    def test_runner_sources_read_numbers_as_text_only(self):  # K1: no int() of table text
        src = sa.read_text(os.path.join(REPO, "tests/ci_mutants.py"))
        self.assertEqual(len(re.findall(r"\bint\(", src)), 1)  # the one int() of a --parts/--part/--timeout value, after NUMBER


# ---- final review: F1 (oracle import closure), F2 (baseline set), F3/F4 (G1), F5 (docstrings) ------------------------
TEST_A_BODY = ("import unittest\n\nfrom src.a import add\n\n\nclass T(unittest.TestCase):\n"
               "    def test_add(self):\n        self.assertEqual(add(1, 2), 3)\n")


class ImportClosureTest(Fx):  # F-20261126-5nhg (T6: a mutant of the oracle is refused)
    FORMS = {  # how the killing module tests/test_a.py names tests/test_lib.py
        "from tests import x": "from tests import test_lib\n",
        "from tests.x import y": "from tests.test_lib import VALUE\n",
        "import tests.x": "import tests.test_lib\n",
        "import tests.x as y": "import tests.test_lib as lib\n",
        "from . import x": "from . import test_lib\n",
        "from .x import y": "from .test_lib import VALUE\n",
        "import_module literal": "import importlib\nimportlib.import_module('tests.test_lib')\n",
        "__import__ literal": "__import__('tests.test_lib')\n",
        "inside a function": "def f():\n    from tests import test_lib\n",
        "two names on one line": "from tests import test_c, test_lib\n",
    }

    def mutate(self, files, path="tests/test_lib.py", old="VALUE = 1", new="VALUE = 2"):
        base = dict({"tests/test_lib.py": "VALUE = 1\n"}, **files)
        self.repo({TABLE: table({"x1": (path, old, new)}, {"x1": ("tests.test_a",)})}, base_extra=base)
        code, out, err, fake = self.go()
        return code, lines_of(out).get("x1"), fake

    def test_each_form_of_import_protects_the_module(self):  # F1: one test per member of the class
        for label, line in self.FORMS.items():
            with self.subTest(label):
                code, line_of, fake = self.mutate({"tests/test_a.py": line + TEST_A_BODY})
                self.assertEqual((code, line_of[0]), (1, "ERROR"), (label, line_of))
                self.assertIn("is protected", line_of[1], label)
                self.assertEqual(fake.calls, [], label)  # nothing run, nothing mutated
                self.assertEqual(self.status(), "")

    def test_a_module_imported_through_a_support_module_or_a_chain_is_protected(self):  # F1: transitive
        chain = {"tests/test_a.py": "from tests import support_fx\n" + TEST_A_BODY, "tests/support_fx.py": "from tests import test_lib\n"}
        code, line_of, fake = self.mutate(chain)
        self.assertEqual((code, line_of[0]), (1, "ERROR"), line_of)
        longer = {"tests/test_a.py": "from tests import test_mid\n" + TEST_A_BODY, "tests/test_mid.py": "from tests import test_lib\n"}
        code, line_of, fake = self.mutate(longer)
        self.assertEqual((code, line_of[0]), (1, "ERROR"), line_of)

    def test_what_is_not_an_import_or_not_a_test_module_stays_allowed(self):  # F1: controls and the stated exceptions
        cases = {
            "imported by nothing": ({"tests/test_a.py": TEST_A_BODY}, "tests/test_lib.py"),
            "named in a comment": ({"tests/test_a.py": "# from tests import test_lib\n" + TEST_A_BODY}, "tests/test_lib.py"),
            "named in a string": ({"tests/test_a.py": "X = 'tests.test_lib'\n" + TEST_A_BODY}, "tests/test_lib.py"),
            "a name built at run time": ({"tests/test_a.py": "import importlib\nimportlib.import_module('tests.' + 'test_lib')\n"
                                          + TEST_A_BODY}, "tests/test_lib.py"),
            "a support module": ({"tests/test_a.py": "from tests import helpers\n" + TEST_A_BODY, "tests/helpers.py": "VALUE = 1\n"},
                                 "tests/helpers.py"),
            "ci_shards": ({"tests/test_a.py": "from tests import ci_shards\n" + TEST_A_BODY, "tests/ci_shards.py": "VALUE = 1\n"},
                          "tests/ci_shards.py"),
            "a fixture file": ({"tests/test_a.py": TEST_A_BODY, "tests/fixtures/f.py": "VALUE = 1\n"}, "tests/fixtures/f.py"),
            # F-20261126-7bbd: a module the closure never reaches may be unreadable; a name that is no file is no refusal
            "an unparsable module nothing imports": ({"tests/test_a.py": TEST_A_BODY, "tests/other.py": "def (:\n"},
                                                     "tests/test_lib.py"),
            "an imported name that is no file": ({"tests/test_a.py": "from tests import nothing_here\n" + TEST_A_BODY},
                                                 "tests/test_lib.py"),
            "a name that is no module name": ({"tests/test_a.py": "import importlib\nimportlib.import_module('tests.sub/support')\n"
                                               + TEST_A_BODY, "tests/sub/support.py": "from tests import test_lib\n"},
                                              "tests/test_lib.py"),
            "constants and calls that name no module": ({"tests/test_a.py": "import importlib\nimportlib.import_module(5)\n"
                                                         "__import__(b'tests.test_lib')\nimportlib.import_module()\n"
                                                         "importlib.import_module(None)\ndict()\n" + TEST_A_BODY}, "tests/test_lib.py"),
        }
        for label, (files, path) in cases.items():
            with self.subTest(label):
                code, line_of, fake = self.mutate(files, path=path)
                self.assertEqual((code, line_of[0]), (0, "SURVIVED"), (label, line_of))

    # F-20261126-7bbd (T6, H1): a tests module the closure reaches and cannot read and parse refuses the whole run.
    def refused(self, bad, files, prepare=None, label="", mode=None, why=r"\S"):
        """The run is refused as ``ERROR oracle <bad>: <why>``: exit 1, nothing run, nothing mutated, the tree clean. ``files``
        are committed; ``prepare()`` then changes the working tree and the change is committed too."""
        self.repo({TABLE: table({"x1": ("src/a.py", "a + b", "a - b")}, {"x1": ("tests.test_a",)})}, base_extra=files)
        if prepare:
            prepare()
            self.head = commit_all(self.root, "the module that cannot be read")
        if mode is not None:  # a file git is told not to look at (it cannot read it either)
            git(self.root, "update-index", "--skip-worktree", bad)
            os.chmod(os.path.join(self.root, bad), mode)
            self.addCleanup(os.chmod, os.path.join(self.root, bad), 0o644)
        fake = Fake(self.root)
        code, out, err = self.call(self.argv(), execute=fake)
        self.assertEqual(code, 1, (label, out, err))
        self.assertRegex(out, r"(?m)^ERROR oracle %s: %s" % (re.escape(bad), why), (label, out))
        self.assertEqual(fake.calls, [], label)  # not even the baseline ran
        self.assertEqual(self.status(), "", label)
        self.assertEqual(self.read("src/a.py"), BASE_FILES["src/a.py"].encode("utf-8"), label)  # nothing mutated
        return out

    # Where the module that cannot be read sits: imported by the killing module tests/test_a.py, or through a support module.
    # (A killing module that is a symbolic link, a directory or has two hard links is refused earlier, as a table error.)
    IMPORTED = {"direct": ({"tests/test_a.py": "from tests import support\n" + TEST_A_BODY}, "tests/support.py"),
                "transitive": ({"tests/test_a.py": "from tests import mid\n" + TEST_A_BODY, "tests/mid.py": "import tests.support\n"},
                               "tests/support.py")}

    def test_an_imported_module_that_is_a_symbolic_link_is_refused(self):  # F3: a link to a regular module (Python imports it)
        for label, (files, rel) in self.IMPORTED.items():
            with self.subTest(label):
                def link():
                    self.put("tests/real_module.py", "VALUE = 1\n")
                    os.symlink("real_module.py", os.path.join(self.root, rel))
                self.refused(rel, files, link, label, why="is not a regular file")

    def test_an_imported_module_that_is_a_directory_is_refused(self):  # F3 / H1
        for label, (files, rel) in self.IMPORTED.items():
            with self.subTest(label):
                def directory():
                    self.put(rel + "/x.txt", "x\n")
                self.refused(rel, files, directory, label, why="is not a regular file")

    def test_an_imported_module_that_is_a_fifo_is_refused_without_blocking(self):  # F3 / H1: nothing opens it
        for label, (files, rel) in self.IMPORTED.items():
            with self.subTest(label):
                def fifo():
                    with open(os.path.join(self.root, ".git", "info", "exclude"), "a", encoding="utf-8") as fh:
                        fh.write("/%s\n" % rel)  # git ignores it (it cannot be added)
                    os.mkfifo(os.path.join(self.root, rel))
                self.refused(rel, files, fifo, label, why="is not a regular file")

    def test_an_imported_module_larger_than_8_mib_is_refused_and_one_of_exactly_8_mib_is_read(self):  # F3: the size cap
        limit = 8 << 20
        head = "from tests import test_lib\n"

        def padded(size):
            return head + "#" + "x" * (size - len(head) - 1)
        for size, label in ((limit + 1, "8 MiB + 1 byte"),):
            with self.subTest(label):
                out = self.refused("tests/support.py", {"tests/test_a.py": "from tests import support\n" + TEST_A_BODY,
                                                        "tests/support.py": padded(size)}, label=label, why="is larger than 8 MiB")
        for size, label in ((limit, "exactly 8 MiB"),):
            with self.subTest(label):  # read and walked: its import is protected
                code, line_of, fake = self.mutate({"tests/test_a.py": "from tests import support\n" + TEST_A_BODY,
                                                   "tests/support.py": padded(size)})
                self.assertEqual((code, line_of[0]), (1, "ERROR"), (label, line_of))
                self.assertIn("is protected", line_of[1], label)

    def test_an_imported_module_that_cannot_be_parsed_is_refused(self):  # F3: unparsable source, per kind of text
        texts = {"a syntax error": b"def (:\n", "a NUL byte": b"VALUE = 1\x00\n", "bytes that are not UTF-8": b"VALUE = '\xff\xfe'\n",
                 "an unknown encoding": b"# coding: nonsense-9\nVALUE = 1\n", "a bad indent": b"if 1:\nx = 1\n",
                 "nested too deep": b"x = " + b"[" * 3000 + b"]" * 3000 + b"\n"}
        for what, text in texts.items():
            for label, (files, rel) in dict(self.IMPORTED, **{"the killing module": ({}, "tests/test_a.py")}).items():
                with self.subTest((what, label)):
                    body = text + b"\n" + (TEST_A_BODY.encode("utf-8") if rel == "tests/test_a.py" else b"")
                    self.refused(rel, dict(files, **{rel: body}), None, label, why="cannot be parsed")

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root reads a file whatever its mode")
    def test_an_imported_module_that_cannot_be_read_is_refused(self):  # F3: unreadable (mode 0), per position
        for label, (files, rel) in dict(self.IMPORTED, **{"the killing module": ({}, "tests/test_a.py")}).items():
            with self.subTest(label):
                self.refused(rel, dict(files, **({} if rel == "tests/test_a.py" else {rel: "VALUE = 1\n"})), None, label, 0,
                             why="cannot be read")

    def test_an_imported_module_with_two_hard_links_is_refused(self):  # F3 / H1: open_target refuses a second link
        for label, (files, rel) in self.IMPORTED.items():
            with self.subTest(label):
                def twin():
                    os.link(os.path.join(self.root, rel), os.path.join(self.root, rel + ".twin"))
                self.refused(rel, dict(files, **{rel: "VALUE = 1\n"}), twin, label, why="cannot be read as a regular file with one hard link")

    def test_an_imported_module_whose_status_or_content_cannot_be_read_is_refused(self):  # F3: an OS error, injected at the seam
        files = {"tests/test_a.py": "from tests import support\n" + TEST_A_BODY, "tests/support.py": "VALUE = 1\n"}
        real_lstat, real_open = os.lstat, ci_mutants.open_target

        def lstat(path, *args, **kw):  # the status of the module cannot be read (any error but "no such file")
            if str(path).endswith("tests/support.py"):
                raise PermissionError(13, "Permission denied")
            return real_lstat(path, *args, **kw)

        class ReadFails:
            def __init__(self, fh):
                self.fh = fh

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                self.fh.close()

            def fileno(self):
                return self.fh.fileno()

            def read(self, *args):
                raise OSError(5, "Input/output error")

        def open_target(root, rel, write):
            fh = real_open(root, rel, write)
            return ReadFails(fh) if rel == "tests/support.py" else fh
        with mock.patch.object(os, "lstat", lstat):
            self.refused("tests/support.py", files, why=r"cannot be read \(Permission denied\)")
        with mock.patch.object(ci_mutants, "open_target", open_target):
            self.refused("tests/support.py", files, why=r"cannot be read \(Input/output error\)")

    def test_a_module_reached_twice_is_read_once(self):  # F3: the closure keeps the modules it has read (a diamond)
        files = {"tests/test_a.py": "from tests import test_b2, test_c2\n" + TEST_A_BODY, "tests/test_b2.py": "from tests import test_lib\n",
                 "tests/test_c2.py": "from tests import test_lib\n"}
        self.repo({TABLE: table({"x1": ("tests/test_lib.py", "VALUE = 1", "VALUE = 2")}, {"x1": ("tests.test_a",)})},
                  base_extra=dict({"tests/test_lib.py": "VALUE = 1\n"}, **files))
        parsed, real_parse = [], ast.parse

        def counting(source, filename="<unknown>", *args, **kw):
            parsed.append(filename)
            return real_parse(source, filename, *args, **kw)
        with mock.patch.object(ast, "parse", counting):
            code, out, err = self.call(self.argv(), execute=Fake(self.root))
        self.assertEqual(code, 1, out)  # test_lib is protected
        for rel in ("tests/test_a.py", "tests/test_b2.py", "tests/test_c2.py", "tests/test_lib.py"):
            self.assertEqual(parsed.count(rel), 1, (rel, parsed))

    def test_the_tests_package_file_is_protected_once_it_has_content(self):  # F1: tests/__init__.py
        files = {"tests/__init__.py": "VALUE = 1\n"}
        code, line_of, fake = self.mutate(files, path="tests/__init__.py")
        self.assertEqual((code, line_of[0]), (1, "ERROR"), line_of)
        self.assertIn("is protected", line_of[1])

    def test_the_case_folded_path_of_an_imported_module_is_protected(self):  # F1
        files = {"tests/test_a.py": "from tests import test_lib\n" + TEST_A_BODY}
        code, line_of, fake = self.mutate(files, path="TESTS/TEST_LIB.PY")
        self.assertEqual((code, line_of[0]), (1, "ERROR"), line_of)
        self.assertIn("is protected", line_of[1])


class BaselineTupleTest(Fx):  # F-20261126-rw5k (T9: the named modules fail before any mutation)
    PAIR = ("tests.test_a", "tests.test_b")

    def pair_fails(self, py, mods, mutated):
        return FAIL if tuple(mods) == self.PAIR or tuple(mods) == self.PAIR[::-1] else PASS

    def test_an_id_whose_modules_fail_together_is_an_error_and_is_not_mutated(self):  # F2
        m = {"noop": ("src/a.py", "a + b", "a - b"), "ok": ("src/b.py", "'two'", "'three'")}
        kill = {"noop": self.PAIR, "ok": ("tests.test_b",)}
        self.repo({TABLE: table(m, kill)})
        fake = Fake(self.root, self.pair_fails)
        code, out, err = self.call(self.argv(), execute=fake)
        got = lines_of(out)
        self.assertEqual((code, got["noop"][0], got["ok"][0]), (1, "ERROR", "SURVIVED"), out)
        self.assertIn("baseline failed: tests.test_a tests.test_b failed on", got["noop"][1])
        self.assertEqual([c[1] for c in fake.mutated_calls()], [("tests.test_b",)] * 2)  # noop was never mutated

    def test_each_distinct_tuple_is_baselined_once_exactly_as_it_is_run(self):  # F2: same order, no union, no split
        m = {"a1": ("src/a.py", "a + b", "a - b"), "a2": ("src/b.py", "'two'", "'three'"), "a3": ("src/b.py", "'one'", "'uno'")}
        kill = {"a1": ("tests.test_b", "tests.test_a"), "a2": ("tests.test_b", "tests.test_a"), "a3": ("tests.test_c",)}
        self.repo({TABLE: table(m, kill)})
        fake = Fake(self.root, watch=["src/a.py", "src/b.py"])
        code, out, err = self.call(self.argv(), execute=fake)
        self.assertEqual(code, 0, out)
        baselines = sorted({c[1] for c in fake.baseline_calls()})
        self.assertEqual(baselines, [("tests.test_b", "tests.test_a"), ("tests.test_c",)])
        self.assertEqual(len(fake.baseline_calls()), 4)  # two tuples, two interpreters: a shared tuple runs once

    def test_a_failing_tuple_does_not_hide_a_passing_one(self):  # F2: the tuples are independent
        m = {"p1": ("src/a.py", "a + b", "a - b"), "p2": ("src/b.py", "'two'", "'three'")}
        kill = {"p1": self.PAIR, "p2": self.PAIR[::-1]}
        self.repo({TABLE: table(m, kill)})
        fake = Fake(self.root, lambda py, mods, mutated: FAIL if tuple(mods) == self.PAIR else PASS)
        code, out, err = self.call(self.argv(), execute=fake)
        self.assertEqual((code, verdicts(out)), (1, {"p1": "ERROR", "p2": "SURVIVED"}), out)


class JobEnvTest(Fx):  # F-20261126-zzcq (G1: a job index outside 1..parts) and F-20261126-y8hc (G1, generated)
    IDS = ["s%d" % i for i in range(1, 7)]
    LINE_TEXT = "%s: KILLED | 3.9 Ran 3 tests FAILED ; 3.13 Ran 3 tests FAILED"

    def setup_repo(self):
        m = {i: ("src/a.py", "a + b", "a - b") for i in self.IDS}
        self.repo({TABLE: table(m, {i: ("tests.test_a",) for i in self.IDS})})

    def valid_env(self, parts):
        env = {}
        blocks = ci_mutants.split([(TABLE, i) for i in self.IDS], parts)
        for k, block in enumerate(blocks, 1):
            env["MUTANT_RESULT_%d" % k] = "success"
            env["MUTANT_LINES_%d" % k] = "\n".join(self.LINE_TEXT % i for _, i in block)
        return env

    def summary(self, parts, env):
        return self.call(self.argv("summary", parts=parts), env=env)

    def test_the_valid_environment_passes(self):  # G1 control
        self.setup_repo()
        for parts in (1, 2, 3):
            code, out, err = self.summary(parts, self.valid_env(parts))
            self.assertEqual(code, 0, (parts, out))

    def test_a_job_index_outside_the_closed_grammar_fails_the_summary(self):  # F3: one subtest per member
        self.setup_repo()
        bad = {"k=0": "0", "k>parts": "3", "k far past parts": "99", "leading zero": "01", "double zero": "00",
               "non-ASCII digit": "٣", "full-width digit": "１", "empty": "", "sign": "+1", "negative": "-1",
               "space": " 1", "trailing newline": "1\n", "decimal point": "1.0", "text": "x"}
        for label, suffix in bad.items():
            for kind in ("RESULT", "LINES"):
                with self.subTest((label, kind)):
                    env = self.valid_env(2)
                    env["MUTANT_%s_%s" % (kind, suffix)] = "failure" if kind == "RESULT" else "g1: ERROR | y\nghost: TIMEOUT | z"
                    code, out, err = self.summary(2, env)
                    self.assertEqual(code, 1, (label, out))
                    self.assertRegex(out, r"(?m)^FAIL env 'MUTANT_%s_.*': job index .* is outside 1\.\.2$" % kind)
        env = self.valid_env(2)  # names that only look similar are not job names
        env.update({"MUTANT_X_9": "1", "XMUTANT_RESULT_9": "1", "mutant_result_9": "1", "MUTANT_RESULTS_9": "1"})
        self.assertEqual(self.summary(2, env)[0], 0)

    # Every character at which str.splitlines cuts a line besides "\n" (and the pair "\r\n"), and every whitespace-only
    # line that str.strip drops: none of them separates or blanks a line of the closed grammar, which cuts at "\n" only.
    SEPARATORS = ["\x85", " ", " ", "\x0b", "\x0c", "\x1c", "\x1d", "\x1e", "\r", "\r\n"]
    BLANKS = ["\xa0", "　", "\x1f", " ", "\t", " ", " ", " ", " ", "\x1f\x1f", " \t "]
    DETAIL_CHARS = ["\U0001fae0", "é", "\x7f", "\x01", "‮", "퟿"]  # U+1FAE0: assigned in Unicode 14 (3.13), not 13 (3.9)
    RAW_SEPARATORS = ["\x85"," ", " ", "\x0b", "\x0c", "\x1c", "\x1d", "\x1e", "\r"]
    RESULTS = ["success", "failure", "cancelled", "skipped", "", "Success", "success ", " success", "success\n", "\x85",
               "ok", " ", "null", "SUCCESS", "success\x00x", "‮success"]
    PATHS = ["g out", "g'out", "g\"out", "géout", "g\nout", "g;out", "g$(x)out", "-gout", "g\U0001fae0out"]  # names a file can have
    SURROGATES = ["\ud800", "\udbff", "\udfff", "g\ud800out", "\ud83d" + "\ude00", "x\udc00"]  # lone surrogates: os.fsencode raises
    ESCAPED = ["\udc80", "\udcff", "g\udcc3out", "\udcc3", "\udce9\udca9"]  # surrogate-escaped bytes: fsencode gives bytes that are no UTF-8

    def lines_case(self, rng, env, k, kind, char=None):
        """(label, env, 1) of one case of the lines grammar: the part's lines are the valid ones with ``char`` (a separator
        between the first two lines, a whitespace-only line after the first, or a character in the detail of the first). The
        grammar cuts lines at "\\n" only and allows one line or an empty line, so every such text is unreadable: exit 1."""
        first, second, *rest = env["MUTANT_LINES_%d" % k].split("\n")
        if kind == "separator-between":
            char = char if char is not None else rng.choice(self.SEPARATORS)
            first = first + char + second
            second = None
        elif kind == "blank-line-of-whitespace":
            char = char if char is not None else rng.choice(self.BLANKS)
            first = first + "\n" + char
        else:
            char = char if char is not None else rng.choice(self.DETAIL_CHARS)
            first = first + " " + char
        env["MUTANT_LINES_%d" % k] = "\n".join([first] + ([second] if second is not None else []) + rest)
        return "%s=%r" % (kind, char), env, 1

    def mutations(self, rng, parts):
        """(label, env, expected exit code) of one generated case, built from the valid environment by one change whose
        verdict the closed grammar fixes: a part's job result must be exactly ``success``, its lines must be exactly the
        part's ids, cut at "\\n" only (an empty line, exactly "", is allowed; any other text is no line of the grammar), each
        line printable ASCII, and every job-looking name must carry a canonical index 1..parts."""
        env = self.valid_env(parts)
        k = rng.randint(1, parts)
        kind = rng.choice(["none", "result", "result-missing", "lines-text", "lines-missing", "lines-empty", "blank-lines",
                           "separator-in-line", "extra-name", "duplicate-line", "unknown-id", "separator-between",
                           "blank-line-of-whitespace", "detail-char"])
        if kind in ("separator-between", "blank-line-of-whitespace", "detail-char"):
            return self.lines_case(rng, env, k, kind)
        if kind == "none":
            return kind, env, 0
        if kind == "result":
            text = rng.choice(self.RESULTS)
            env["MUTANT_RESULT_%d" % k] = text
            return "%s=%r" % (kind, text), env, 0 if text == "success" else 1
        if kind == "result-missing":
            del env["MUTANT_RESULT_%d" % k]
            return kind, env, 1
        if kind == "lines-text":
            text = "".join(rng.choice("\U0001fae0abcxyz: |\t\x7f\x01é퟿ \x85-_.") for _ in range(rng.randint(1, 40)))
            env["MUTANT_LINES_%d" % k] = text
            return "%s=%r" % (kind, text), env, 1
        if kind == "lines-missing":
            del env["MUTANT_LINES_%d" % k]
            return kind, env, 1
        if kind == "lines-empty":
            env["MUTANT_LINES_%d" % k] = ""
            return kind, env, 1
        if kind == "blank-lines":
            env["MUTANT_LINES_%d" % k] = "\n" * rng.randint(0, 3) + env["MUTANT_LINES_%d" % k].replace("\n", "\n" * rng.randint(1, 3)) + "\n\n"
            return kind, env, 0
        if kind == "separator-in-line":  # splitlines cuts the line: the second piece is no line of the grammar
            sep = rng.choice(self.SEPARATORS)
            env["MUTANT_LINES_%d" % k] = env["MUTANT_LINES_%d" % k] + sep + "tail"
            return "%s=%r" % (kind, sep), env, 1
        if kind == "extra-name":
            suffix = rng.choice(["0", str(parts + 1), "0%d" % k, "00", "٣", "", "1.0", "-1", " 1", "x"] + [str(parts + rng.randint(1, 50))])
            name = "MUTANT_%s_%s" % (rng.choice(["RESULT", "LINES"]), suffix)
            env[name] = rng.choice(["success", "x"])
            return "%s=%r" % (kind, name), env, 1
        if kind == "duplicate-line":
            first = env["MUTANT_LINES_%d" % k].splitlines()[0]
            env["MUTANT_LINES_%d" % k] += "\n" + first
            return kind, env, 1
        env["MUTANT_LINES_%d" % k] += "\nghost: KILLED | x"  # unknown-id
        return kind, env, 1

    def test_generated_environments_get_the_verdict_of_the_closed_grammar(self):  # G1: seeded generator, through main()
        seed = 20261126
        self.setup_repo()
        rng = random.Random(seed)
        for n in range(150):
            parts = rng.choice([1, 2, 3])
            label, env, want = self.mutations(rng, parts)
            code, out, err = self.summary(parts, env)
            self.assertEqual(code, want, "seed=%d case=%d parts=%d %s\n%s" % (seed, n, parts, label, out))
            self.assertEqual(err, "", "seed=%d case=%d" % (seed, n))

    def test_a_detail_of_every_printable_ascii_character_and_a_line_without_detail_are_accepted(self):  # F-20261126-5ssd control
        self.setup_repo()
        env = self.valid_env(1)
        printable = "".join(chr(c) for c in range(0x20, 0x7f))
        lines = env["MUTANT_LINES_1"].split("\n")
        lines[0] = "s1: KILLED | " + printable
        lines[1] = lines[1].split(" ")[0] + " KILLED"  # a line with no detail at all
        env["MUTANT_LINES_1"] = "\n".join(lines)
        code, out, err = self.summary(1, env)
        self.assertEqual(code, 0, out)

    def test_every_separator_and_whitespace_line_of_the_pool_is_refused(self):  # F-20261126-5ssd: one case per member, seeded
        seed = 20261127
        self.setup_repo()
        rng = random.Random(seed)
        self.assertEqual(self.RAW_SEPARATORS, self.SEPARATORS[:-1])  # the escapes above are the literal characters
        members = ([("separator-between", c) for c in self.SEPARATORS] + [("blank-line-of-whitespace", c) for c in self.BLANKS]
                   + [("detail-char", c) for c in self.DETAIL_CHARS] + [("separator-at-the-end", c) for c in self.SEPARATORS])
        for n, (kind, char) in enumerate(members):
            parts = rng.choice([1, 2, 3])
            env = self.valid_env(parts)
            k = rng.randint(1, parts)
            if kind == "separator-at-the-end":  # a valid last line followed by the separator only
                env["MUTANT_LINES_%d" % k] += char
                label = "%s=%r" % (kind, char)
            else:
                label, env, _ = self.lines_case(rng, env, k, kind, char)
            code, out, err = self.summary(parts, env)
            why = "seed=%d case=%d parts=%d k=%d %s\n%s" % (seed, n, parts, k, label, out)
            self.assertEqual(code, 1, why)
            self.assertRegex(out, r"(?m)^FAIL (job %d: unreadable line|s\d: no line)" % k, why)
            self.assertEqual(err, "", why)
        for n in range(20):  # the valid environment and the empty lines of "\n" stay accepted (control)
            parts = rng.choice([1, 2, 3])
            env = self.valid_env(parts)
            k = rng.randint(1, parts)
            env["MUTANT_LINES_%d" % k] = "\n" * rng.randint(1, 3) + env["MUTANT_LINES_%d" % k].replace("\n", "\n" * rng.randint(1, 3)) + "\n"
            self.assertEqual(self.summary(parts, env)[0], 0, "seed=%d control %d" % (seed, n))

    def bounded(self, fn, release, what):
        """``fn()`` run in a thread joined with a timeout. On timeout ``release()`` frees the thread (it is called until the
        thread ends), then the test fails: a blocked open is a failure, never a hang. An exception of ``fn`` is re-raised."""
        result = {}

        def work():
            try:
                result["r"] = fn()
            except BaseException as err:  # noqa: BLE001 - re-raised in the test thread
                result["e"] = err
        thread = threading.Thread(target=work, daemon=True)
        thread.start()
        thread.join(20)
        if thread.is_alive():
            for _ in range(100):
                release()
                thread.join(0.1)
                if not thread.is_alive():
                    break
            self.fail("the run blocked (%s)" % what)
        if "e" in result:
            raise result["e"]
        return result["r"]

    def test_generated_github_output_values_get_the_verdict_of_the_closed_grammar(self):  # G1, H1: seeded, through main()
        seed = 20261126
        self.repo()
        rng = random.Random(seed)
        kinds = ["missing", "empty", "relative", "directory", "fifo", "fifo-with-reader", "symlink", "dangling-symlink",
                 "new-file", "nested-new-file", "existing-file", "write-only-file", "nul", "lone-surrogate",
                 "surrogate-escaped", "escaped-utf8-alias", "long-name", "long-parent", "long-path", "no-file-name",
                 "symlinked-parent", "parent-swapped", "final-swapped", "file-as-parent", "fifo-as-parent"]
        umask = os.umask(0)
        os.umask(umask)
        self.assertEqual(os.path.realpath(self.tmp), self.tmp)  # no component above a sandbox is a symbolic link
        fds = []
        self.addCleanup(lambda: [os.close(fd) for fd in fds])
        for n in range(len(kinds) + 60):  # every kind once, then a seeded draw
            kind = kinds[n] if n < len(kinds) else rng.choice(kinds)
            box = os.path.join(self.tmp, "out%d" % n)  # the sandbox of the case: every path below it
            os.mkdir(box)
            name = rng.choice(self.PATHS)
            path = os.path.join(box, name)
            target = os.path.join(box, "target")
            with open(target, "wb") as fh:
                fh.write(b"KEEP\n")
            env, want, swap, none_made = {}, 1, None, False  # none_made: the case must leave nothing but ``target`` in the box
            if kind == "missing":
                want = 0
            elif kind == "empty":
                env["GITHUB_OUTPUT"] = ""
            elif kind == "relative":
                env["GITHUB_OUTPUT"] = rng.choice(["out.txt", "./out.txt", "a/b.txt", name, "../x"])
            elif kind == "nul":
                env["GITHUB_OUTPUT"] = path + "\0x"
            elif kind == "directory":
                os.mkdir(path)
                env["GITHUB_OUTPUT"] = path
            elif kind in ("fifo", "fifo-with-reader"):
                os.mkfifo(path)
                if kind == "fifo-with-reader":
                    fds.append(os.open(path, os.O_RDONLY | os.O_NONBLOCK))
                env["GITHUB_OUTPUT"] = path
            elif kind == "symlink":
                os.symlink(target, path)
                env["GITHUB_OUTPUT"] = path
            elif kind == "dangling-symlink":
                os.symlink(os.path.join(box, "nothing"), path)
                env["GITHUB_OUTPUT"] = path
            elif kind in ("lone-surrogate", "surrogate-escaped"):  # no valid UTF-8 path: a named refusal, not a traceback
                env["GITHUB_OUTPUT"] = box + "/" + rng.choice(self.SURROGATES if kind == "lone-surrogate" else self.ESCAPED)
                none_made = True
            elif kind == "escaped-utf8-alias":  # surrogate-escaped bytes that are valid UTF-8 spell a valid path: accepted
                env["GITHUB_OUTPUT"] = box + "/g\udcc3\udca9out"
                path = os.path.join(box, "géout")
                want = 0
            elif kind == "long-name":
                env["GITHUB_OUTPUT"] = box + "/" + "x" * rng.choice([256, 300, 1000, 5000])  # more than 255 bytes: ENAMETOOLONG
                none_made = True
            elif kind == "long-parent":
                env["GITHUB_OUTPUT"] = box + "/" + "y" * rng.choice([256, 4096]) + "/out"
                none_made = True
            elif kind == "long-path":  # every component is short; the whole path is longer than PATH_MAX and does not exist
                env["GITHUB_OUTPUT"] = box + "".join("/" + "d" * 100 for _ in range(rng.randint(11, 60))) + "/out"
                none_made = True
            elif kind == "no-file-name":  # a path that does not end in a file name
                env["GITHUB_OUTPUT"] = rng.choice([box + "/", box + "/out/", box + "//", box + "/out//", "/", "//", "///"])
                none_made = True
            elif kind in ("symlinked-parent", "parent-swapped"):
                real, elsewhere = os.path.join(box, "real"), os.path.join(box, "elsewhere")
                os.makedirs(os.path.join(real, "sub"))
                os.makedirs(os.path.join(elsewhere, "sub"))
                os.makedirs(os.path.join(elsewhere, "d2"))  # what the swapped link of the parent kind leads to
                if kind == "symlinked-parent":  # a symbolic link is a component of the parent chain at the check
                    link = rng.choice(["link", "a/link", "a/b/link"])
                    os.makedirs(os.path.dirname(os.path.join(box, link)) or box, exist_ok=True)
                    os.symlink(rng.choice([real, os.path.relpath(real, os.path.dirname(os.path.join(box, link)))]),
                               os.path.join(box, link))
                    env["GITHUB_OUTPUT"] = os.path.join(box, link, rng.choice(["", "sub/"]) + "out")
                else:  # a real directory at the check, swapped for a link after it (while the runner holds the path)
                    chain = os.path.join(box, "d1", "d2")
                    os.makedirs(chain)
                    env["GITHUB_OUTPUT"] = os.path.join(chain, "out")
                    held = rng.choice([os.path.join(box, "d1"), chain])

                    def swap(held=held):
                        os.rename(held, held + ".aside")
                        os.symlink(os.path.join(elsewhere, "sub") if held == chain else elsewhere, held)
            elif kind in ("file-as-parent", "fifo-as-parent"):  # a parent that is no directory: a regular file, or a FIFO
                holder = os.path.join(box, "holder")  # (a FIFO nobody has open: opening it without O_DIRECTORY blocks)
                if kind == "file-as-parent":
                    with open(holder, "wb") as fh:
                        fh.write(b"KEEP\n")
                else:
                    os.mkfifo(holder)
                env["GITHUB_OUTPUT"] = holder + "/out"
            elif kind == "final-swapped":  # the file does not exist at the check; a link is there when it is opened
                env["GITHUB_OUTPUT"] = path

                def swap():
                    os.symlink(target, path)
            else:
                if kind in ("existing-file", "write-only-file"):
                    with open(path, "wb") as fh:
                        fh.write(b"BEFORE\n")
                    if kind == "write-only-file":
                        os.chmod(path, 0o200)  # a file that can be appended to but not read
                if kind == "nested-new-file":
                    path = os.path.join(box, "d1", "d2", name)
                    os.makedirs(os.path.dirname(path))
                env["GITHUB_OUTPUT"] = path
                want = 0
            before = os.getcwd()
            os.chdir(box)  # a relative GITHUB_OUTPUT (and "../x") resolves inside this case's sandbox even if it is accepted
            fifo = {"fifo": path, "fifo-as-parent": os.path.join(box, "holder")}.get(kind)

            def release():  # a reader frees a blocked writer, a writer frees a blocked reader
                for flag in (os.O_RDONLY, os.O_WRONLY):
                    try:
                        fds.append(os.open(fifo, flag | os.O_NONBLOCK))
                    except OSError:
                        pass
            fired = []

            def hook(nbytes, real_hex=ci_mutants.secrets.token_hex):
                fired.append(1)
                swap()
                return real_hex(nbytes)
            try:
                with mock.patch.object(ci_mutants.secrets, "token_hex", hook) if swap else contextlib.nullcontext():
                    code, out, err = self.bounded(lambda: self.call(self.argv(), execute=Fake(self.root), env=env), release,
                                                  "seed=%d case=%d kind=%s: O_NONBLOCK is missing from the open of GITHUB_OUTPUT"
                                                  % (seed, n, kind))
            finally:
                os.chdir(before)
            why = "seed=%d case=%d kind=%s path=%r\n%s" % (seed, n, kind, env.get("GITHUB_OUTPUT"), out)
            self.assertEqual(code, want, why)
            self.assertEqual(err, "", why)
            self.assertEqual(bool(fired), swap is not None, why)  # the swap ran after the runner had checked the path
            if want:
                self.assertRegex(out, r"(?m)^ERROR output: ", why)
            if kind in ("lone-surrogate", "surrogate-escaped"):  # the same refusal on every platform, not an open that fails
                self.assertRegex(out, r"(?m)^ERROR output: GITHUB_OUTPUT must be valid UTF-8 text", why)
                self.assertTrue(out.isascii(), why)  # the name is shown escaped: a lone surrogate would break a real stdout
            if kind == "no-file-name":
                self.assertRegex(out, r"(?m)^ERROR output: GITHUB_OUTPUT must name a file", why)
            if kind in ("symlink", "dangling-symlink", "final-swapped"):
                with open(target, "rb") as fh:
                    self.assertEqual(fh.read(), b"KEEP\n", why)  # nothing written through the link
                self.assertFalse(os.path.exists(os.path.join(box, "nothing")), why)
            if none_made:
                self.assertEqual(sorted(os.listdir(box)), ["target"], why)
            if kind in ("symlinked-parent", "parent-swapped"):
                for top in (os.path.join(box, "real"), os.path.join(box, "elsewhere")):
                    self.assertFalse([f for _, _, files in os.walk(top) for f in files if f == "out"], why)  # nothing written through
            if kind in ("new-file", "nested-new-file", "escaped-utf8-alias"):  # a created file has the mode of open(..., 0o666)
                self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o666 & ~umask, why)
            if kind in ("new-file", "nested-new-file", "existing-file", "write-only-file", "escaped-utf8-alias"):
                os.chmod(path, 0o600)
                with open(path, "rb") as fh:
                    text = fh.read().decode("utf-8")
                self.assertTrue(text.startswith("BEFORE\n" if kind in ("existing-file", "write-only-file") else "lines<<ci_mutants_"), why)
                self.assertIn("i1: SURVIVED", text, why)
            if kind == "relative":
                self.assertEqual(self.status(), "", why)  # nothing was written below the repository root either
            self.assertEqual(self.status(), "", why)


class DocstringTest(unittest.TestCase):  # F-20261126-pwu6: the docs of the path rule name the link-count refusal
    def test_the_module_docstring_and_regular_problem_name_the_hard_link_refusal(self):  # F5
        doc = " ".join(ci_mutants.__doc__.split())
        rule = doc[doc.index("A path is relative"):doc.index("must occur exactly once")]
        self.assertIn("exactly one hard link", rule)
        self.assertIn("exactly one hard link", " ".join(ci_mutants._regular_problem.__doc__.split()))
        self.assertIn("exactly one hard link", " ".join(ci_mutants.open_target.__doc__.split()))  # already stated there

    def test_the_docs_state_the_baseline_per_kill_tuple(self):  # F-20261126-bfmx: each tuple as it is run, not each module
        doc = " ".join(ci_mutants.__doc__.split())
        self.assertIn("``run`` baselines each distinct KILL tuple of its part exactly as it is run (the same modules in the "
                      "same order, on both interpreters)", doc)
        stale = re.compile(r"(every|each|per|one)[ -](killing )?" + "mod" + "ule", re.I)  # (the word is split: this file is scanned)
        for rel in ("tests/ci_mutants.py", "tests/test_ci_mutants.py"):
            source = sa.read_text(os.path.join(REPO, rel))
            texts = [t.string for t in tokenize.generate_tokens(io.StringIO(source).readline) if t.type == tokenize.COMMENT]
            tree = ast.parse(source)
            texts += [ast.get_docstring(n) or "" for n in ast.walk(tree)
                      if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))]
            for text in texts:
                for sentence in re.split(r"(?<=[.;:])\s+", " ".join(text.split())):
                    if re.search("baselin", sentence, re.I):  # every sentence of a docstring or comment that names the baseline
                        self.assertIsNone(stale.search(sentence), (rel, sentence))

    def test_the_docs_state_the_grammar_of_the_job_lines_the_output_path_and_the_closure(self):  # F-20261126-5ssd, uvbz, 7bbd
        doc = " ".join(ci_mutants.__doc__.split())
        for needle in ("separated by \"\\n\" only", "printable ASCII", "valid UTF-8", "a symbolic link in any component",
                       "ERROR output:", "ERROR oracle", "larger than 8 MiB"):
            self.assertIn(needle, doc)


# ---- E0-E4: the interface of tests/ci_mutants.py (stream-common :63 exact types; Q-CI5-1 (A) interface names) ----------
class StrSub(str):
    pass


class ListSub(list):
    pass


class TupleSub(tuple):
    pass


class IntSub(int):
    pass


class DictSub(dict):
    pass


class BytesSub(bytes):
    pass


class BoolLike:
    """An object that is true and is not a bool."""

    def __bool__(self):
        return True


class FsPath:
    """An os.PathLike that is not a str."""

    def __init__(self, text):
        self.text = text

    def __fspath__(self):
        return self.text


# The names tests/ci_mutants.py leaves without a leading underscore: the four called from outside (E1-E4; the module's
# upper-case constants are not functions or classes), written by hand from the table row E0.
PUBLIC_NAMES = {"main", "split", "open_target", "count_problem"}
# The other 33 module-level functions and classes, written by hand from the finding F-20261126-qm9a: each is private.
INTERNAL_NAMES = ("Refused Stop show clean number parse git tracked_files tree_problem check_head changed_tables ident_text "
                  "regular_problem Row literal_assignments read_literals load_table gather run_unittest Result run_pair "
                  "protected_reason path_problem Unsafe restore one_row run_rows write_output say refusals command_split "
                  "command_run command_summary").split()
# Private functions added after the rename by the final-review fixes (F-20261126-5nhg: the import closure of the oracle).
ADDED_PRIVATE = {"_import_closure", "_" + "parse_module"}  # (the second, F-20261126-7bbd, is built: PRIVATE_USES_HERE stays as it was)
PRIVATE_NAMES = {"_" + name for name in INTERNAL_NAMES} | ADDED_PRIVATE
# The private names of ci_mutants that this test module itself uses, each with the reason (E0: "nothing outside the module
# uses a private name" has this one exception, because the tests name the refusal class of E2-E4).
PRIVATE_USES_HERE = {"_Refused": "the named error of split, open_target and count_problem: a test pins the class, not a "
                                 "TypeError or ValueError raised by something else",
                     "_import_closure": "named as a string in ADDED_PRIVATE, the hand-written expected set of E0 (not called)",
                     "_regular_problem":"F5: a test pins the text of this function's docstring (the link-count clause); a "
                                         "docstring cannot be read through a public name"}


def private_uses(text, names, python=True):
    """The names of ``names`` (private names of ci_mutants) that ``text`` refers to: an attribute of a module, a name
    imported from it, a quoted name (patch.object, getattr), or, for text that is not Python, any whole word."""
    found = set(re.findall(r"ci_mutants\s*\.\s*(_(?!_)\w+)", text))  # (a dunder such as __doc__ is not a name of the module)
    if python and "ci_mutants" not in text:
        return found  # a file that never names the module cannot use its names (a name like _git may be its own)
    if python:
        for node in ast.walk(ast.parse(text)):
            if isinstance(node, ast.Attribute) and node.attr in names:
                found.add(node.attr)
            elif isinstance(node, ast.ImportFrom) and (node.module or "").endswith("ci_mutants"):
                found.update(a.name for a in node.names if a.name in names)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in names:
                found.add(node.value)
    else:
        found.update(n for n in names if re.search(r"(?<![A-Za-z0-9_])%s(?![A-Za-z0-9_])" % re.escape(n), text))
    return found


class InterfaceNamesTest(unittest.TestCase):  # E0
    def module_names(self):
        """(public, private, all) names of the module-level functions and classes, from an ast scan of the file."""
        tree = ast.parse(sa.read_text(os.path.join(REPO, "tests/ci_mutants.py")))
        names = [n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
        return ({n for n in names if not n.startswith("_")}, {n for n in names if n.startswith("_")}, names)

    def test_only_the_four_called_names_are_public(self):  # E0
        public, private, names = self.module_names()
        self.assertEqual(public, PUBLIC_NAMES)
        self.assertEqual(len(names), len(set(names)))  # no name defined twice
        self.assertEqual(len(INTERNAL_NAMES), 33)
        self.assertEqual(len(PRIVATE_NAMES), 35)

    def test_the_generated_private_list_equals_the_expected_set(self):  # E0
        self.assertEqual(self.module_names()[1], PRIVATE_NAMES)

    def test_the_imported_module_agrees_with_the_scan(self):  # E0: what a caller can see
        seen = {n for n, v in vars(ci_mutants).items() if (callable(v) and getattr(v, "__module__", None) == ci_mutants.__name__)
                and not n.startswith("_")}
        self.assertEqual(seen, PUBLIC_NAMES)
        for name in PRIVATE_NAMES:
            self.assertTrue(hasattr(ci_mutants, name), name)  # renamed, not removed
        for name in INTERNAL_NAMES:
            self.assertFalse(hasattr(ci_mutants, name), name)  # no old public name is left
        self.assertFalse(hasattr(ci_mutants, "import_closure"))

    def test_the_scanner_finds_each_form_of_use(self):  # E0: the contradiction of the scan below
        names = PRIVATE_NAMES
        n = "_" + "show"  # built, so that this file's own scan does not find it
        for text in ("from tests import ci_mutants\nci_mutants.%s(1)\n" % n, "from tests.ci_mutants import %s\n" % n,
                     "mock.patch.object(ci_mutants, '%s')\n" % n, "mock.patch('tests.ci_mutants.%s')\n" % n,
                     "import tests.ci_mutants as cm\ncm.%s\n" % n, "getattr(ci_mutants, '%s')\n" % n):
            self.assertEqual(private_uses(text, names), {n}, text)
        self.assertEqual(private_uses("python -m tests.ci_mutants.%s\n" % n, names, python=False), {n})
        self.assertEqual(private_uses("run: %s\n" % n, names, python=False), {n})
        for text in ("from tests import ci_mutants\nci_mutants.main([])\nci_mutants.split([], 1)\nci_mutants.TABLE_DIR\n",
                     "x = show(1)\n"):
            self.assertEqual(private_uses(text, names), set(), text)

    def test_no_file_outside_the_module_uses_a_private_name(self):  # E0: tests/*.py and .github/
        checked = []
        for name in sorted(os.listdir(os.path.join(REPO, "tests"))):
            rel = "tests/" + name
            if not name.endswith(".py") or rel in ("tests/ci_mutants.py", "tests/test_ci_mutants.py"):
                continue
            checked.append(rel)
            self.assertEqual(private_uses(sa.read_text(os.path.join(REPO, rel)), PRIVATE_NAMES), set(), rel)
        for top, _, files in os.walk(os.path.join(REPO, ".github")):
            for name in sorted(files):
                path = os.path.join(top, name)
                checked.append(os.path.relpath(path, REPO))
                self.assertEqual(private_uses(sa.read_text(path), PRIVATE_NAMES, python=False), set(), path)
        self.assertIn(sa.WORKFLOW, checked)
        self.assertIn("tests/test_self_adoption.py", checked)

    def test_this_test_module_uses_only_the_listed_private_names(self):  # E0
        got = private_uses(sa.read_text(os.path.abspath(__file__)), PRIVATE_NAMES)
        self.assertEqual(got, set(PRIVATE_USES_HERE))

    def test_the_refusal_class_is_a_value_error(self):  # E2-E4: the named error
        self.assertTrue(issubclass(ci_mutants._Refused, ValueError))


class MainTypesTest(Fx):  # E1
    PREFIX = "ci_mutants: refused: "

    def attempt(self, argv=None, **kw):
        fake = Fake(self.root)
        kw.setdefault("root", self.root)
        kw.setdefault("execute", fake)
        kw.setdefault("env", {})
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = ci_mutants.main(self.argv() if argv is None else argv, **kw)
        return code, out.getvalue(), err.getvalue(), fake

    def refused(self, label, needle, argv=None, **kw):
        code, out, err, fake = self.attempt(argv, **kw)
        self.assertEqual((code, out), (2, ""), (label, err))
        self.assertTrue(err.startswith(self.PREFIX + needle + " "), (label, err))
        self.assertEqual(len(err.splitlines()), 1, (label, err))
        self.assertEqual(fake.calls, [], label)  # nothing run
        self.assertEqual(self.status(), "", label)  # nothing mutated

    def passed_the_guards(self, label, argv=None, marker="unknown command ", **kw):
        """An unknown command is refused by the argument parser itself: the value went through every type guard."""
        code, out, err, fake = self.attempt(["frobnicate"] if argv is None else argv, **kw)
        self.assertEqual((code, out), (2, ""), (label, err))
        self.assertTrue(err.startswith(self.PREFIX + marker), (label, err))

    def test_argv(self):  # E1
        self.repo()
        code, out, err, fake = self.attempt()
        self.assertEqual((code, err), (0, ""), out)  # an exact list of exact str is accepted and runs
        self.assertEqual(len(fake.mutated_calls()), 4)
        self.passed_the_guards("empty list", argv=[], marker="usage: ")
        for label, argv in (("list subclass", ListSub(self.argv())), ("tuple", tuple(self.argv())),
                            ("str subclass element", [StrSub(self.argv()[0])] + self.argv()[1:]),
                            ("str subclass option", self.argv()[:1] + [StrSub("--base")] + self.argv()[2:]),
                            ("bytes element", self.argv()[:-1] + [b"x"]), ("int element", self.argv()[:-1] + [1]),
                            ("None element", self.argv()[:-1] + [None]), ("a str", "run"),
                            ("a generator", (a for a in self.argv()))):
            with self.subTest(label):
                self.refused(label, "argv must be", argv=argv)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):  # None is no list (attempt() reads None as "the default argv")
            self.assertEqual(ci_mutants.main(None, root=self.root, env={}), 2)
        self.assertTrue(err.getvalue().startswith(self.PREFIX + "argv must be "), err.getvalue())

    def test_root(self):  # E1
        self.repo()
        self.passed_the_guards("exact str", root=self.root)
        self.passed_the_guards("None", root=None)
        for label, root in (("str subclass", StrSub(self.root)), ("bytes", self.root.encode("utf-8")),
                            ("PathLike", FsPath(self.root)), ("pathlib", pathlib.Path(self.root)),
                            ("int", 3)):
            with self.subTest(label):
                self.refused(label, "root must be", root=root)

    def test_execute(self):  # E1
        self.repo()
        self.passed_the_guards("None", execute=None)
        self.passed_the_guards("a callable", execute=Fake(self.root))
        self.passed_the_guards("a lambda", execute=lambda *a: PASS)
        for label, execute in (("str", "run"), ("int", 1), ("a tuple", (1, 2)), ("a dict", {})):
            with self.subTest(label):
                self.refused(label, "execute must be", execute=execute)

    def test_env(self):  # E1
        self.repo()
        self.passed_the_guards("None", env=None)
        self.passed_the_guards("an empty dict", env={})
        self.passed_the_guards("an exact dict of str", env={"A": "b", "MUTANT_RESULT_1": "success"})
        self.passed_the_guards("os.environ itself", env=os.environ)
        self.passed_the_guards("a copy of os.environ is an exact dict", env=dict(os.environ))
        code, out, err, fake = self.attempt(self.argv("split"), env=os.environ)  # the real call path, nothing is written
        self.assertEqual((code, err), (0, ""), out)
        bad = (("dict subclass", DictSub()), ("dict subclass with items", DictSub(A="b")),
               ("a Mapping that is no dict", collections.UserDict()),
               ("a read-only mapping", types.MappingProxyType({})), ("a Mapping of os.environ", types.MappingProxyType(os.environ)),
               ("os.environ.copy() as a subclass", DictSub(os.environ)), ("str subclass key", {StrSub("A"): "b"}),
               ("str subclass value", {"A": StrSub("b")}), ("int key", {1: "b"}), ("int value", {"A": 1}),
               ("bytes value", {"A": b"b"}), ("None value", {"A": None}), ("a list of pairs", [("A", "b")]), ("a str", "A=b"))
        for label, env in bad:
            with self.subTest(label):
                self.refused(label, "env must be", env=env)
        for label, env in bad:  # the same on the split command: the refusal does not depend on the command
            with self.subTest("split " + label):
                self.refused("split " + label, "env must be", argv=self.argv("split"), env=env)

    def test_the_type_guards_run_before_the_arguments_are_read(self):  # E1: a bad command and a bad env: the type is named
        self.repo()
        code, out, err, fake = self.attempt(["frobnicate"], env=DictSub())
        self.assertEqual((code, out), (2, ""))
        self.assertTrue(err.startswith(self.PREFIX + "env must be "), err)


class SplitTypesTest(unittest.TestCase):  # E2
    KEYS = [("t1.py", "b"), ("t1.py", "a"), ("t2.py", "c")]

    def refused(self, label, needle, keys, parts):
        with self.assertRaises(ci_mutants._Refused, msg=label) as caught:
            ci_mutants.split(keys, parts)
        self.assertTrue(str(caught.exception).startswith(needle + " "), (label, str(caught.exception)))

    def test_keys(self):  # E2
        want = [[("t1.py", "a"), ("t1.py", "b")], [("t2.py", "c")]]
        self.assertEqual(ci_mutants.split(list(self.KEYS), 2), want)
        self.assertEqual(ci_mutants.split([], 3), [[], [], []])
        first = self.KEYS[:1]
        for label, keys in (("list subclass", ListSub(self.KEYS)), ("tuple", tuple(self.KEYS)), ("a set", set(self.KEYS)),
                            ("a generator", (k for k in self.KEYS)), ("None", None), ("a str", "ab"),
                            ("list item", first + [["t1.py", "a"]]), ("tuple subclass item", first + [TupleSub(("t1.py", "a"))]),
                            ("str subclass table", first + [(StrSub("t1.py"), "a")]),
                            ("str subclass id", first + [("t1.py", StrSub("a"))]),
                            ("1-tuple", first + [("t1.py",)]), ("3-tuple", first + [("t1.py", "a", "x")]),
                            ("empty tuple", first + [()]), ("int id", first + [("t1.py", 1)]),
                            ("bytes table", first + [(b"t1.py", "a")]), ("str item", first + ["ab"])):
            with self.subTest(label):
                self.refused(label, "keys must be", keys, 2)

    def test_keys_refused_before_any_work(self):  # E2: split builds nothing
        touched = []

        class Watched(ListSub):
            def __iter__(self):
                touched.append("iter")
                return ListSub.__iter__(self)
        self.refused("watched", "keys must be", Watched(self.KEYS), 2)
        self.assertEqual(touched, [])

    def test_parts(self):  # E2
        self.assertEqual(len(ci_mutants.split(list(self.KEYS), 1)), 1)
        self.assertEqual(len(ci_mutants.split(list(self.KEYS), 5)), 5)
        for label, parts in (("True", True), ("False", False), ("int subclass", IntSub(2)), ("0", 0), ("-1", -1),
                             ("float", 2.0), ("str", "2"), ("None", None), ("bytes", b"2"), ("a list", [2])):
            with self.subTest(label):
                self.refused(label, "parts must be", list(self.KEYS), parts)


class OpenTargetTypesTest(GitIsolatedTestCase):  # E3
    def setUp(self):
        super().setUp()
        self.box = os.path.join(self.tmp, "box")  # the sandbox: every path this class passes is below it
        os.mkdir(self.box)
        self.file = os.path.join(self.box, "f.bin")
        with open(self.file, "wb") as fh:
            fh.write(b"data\n")
        self.opens = []
        real_open = os.open

        def recording(*args, **kw):
            self.opens.append(args)
            return real_open(*args, **kw)
        self.patcher = mock.patch.object(os, "open", recording)

    def read(self):
        with open(self.file, "rb") as fh:
            return fh.read()

    def refused(self, label, needle, root, rel, write):
        self.patcher.start()
        try:
            with self.assertRaises(ci_mutants._Refused, msg=label) as caught:
                ci_mutants.open_target(root, rel, write)
        finally:
            self.patcher.stop()
        self.assertTrue(str(caught.exception).startswith(needle + " "), (label, str(caught.exception)))
        self.assertEqual(self.opens, [], label)  # opens nothing
        self.assertEqual(self.read(), b"data\n", label)  # and truncates nothing

    def test_exact_values_are_accepted(self):  # E3
        with ci_mutants.open_target(self.box, "f.bin", False) as fh:
            self.assertEqual(fh.read(), b"data\n")
        with ci_mutants.open_target(self.box, "f.bin", True) as fh:
            fh.write(b"new")
        self.assertEqual(self.read(), b"new")

    def test_root(self):  # E3
        for label, root in (("str subclass", StrSub(self.box)), ("bytes", self.box.encode("utf-8")),
                            ("PathLike", FsPath(self.box)), ("pathlib", pathlib.Path(self.box)), ("None", None)):
            for write in (False, True):
                with self.subTest((label, write)):
                    self.refused(label, "root must be", root, "f.bin", write)

    def test_rel(self):  # E3
        for label, rel in (("str subclass", StrSub("f.bin")), ("bytes", b"f.bin"), ("PathLike", FsPath("f.bin")),
                           ("pathlib", pathlib.PurePosixPath("f.bin")), ("None", None)):
            for write in (False, True):
                with self.subTest((label, write)):
                    self.refused(label, "rel must be", self.box, rel, write)

    def test_write(self):  # E3
        for label, write in (("int 1", 1), ("int 0", 0), ("bool-like", BoolLike()), ("None", None), ("str", "yes"),
                             ("a list", [True])):
            with self.subTest(label):
                self.refused(label, "write must be", self.box, "f.bin", write)


class CountProblemTypesTest(unittest.TestCase):  # E4: data and old are bytes (the file's bytes and the row's encoded old text)
    def refused(self, label, needle, data, old):
        with self.assertRaises(ci_mutants._Refused, msg=label) as caught:
            ci_mutants.count_problem(data, old)
        self.assertTrue(str(caught.exception).startswith(needle + " "), (label, str(caught.exception)))

    def test_exact_bytes_are_accepted(self):  # E4
        self.assertEqual(ci_mutants.count_problem(b"abc", b"b"), (1, ""))
        self.assertEqual(ci_mutants.count_problem(b"abc", b"x"), (-1, "0 matches"))
        self.assertEqual(ci_mutants.count_problem(b"aaa", b"aa"), (-1, "2 or more matches"))
        self.assertEqual(ci_mutants.count_problem(b"", b"a"), (-1, "0 matches"))

    def test_data(self):  # E4
        for label, data in (("str", "abc"), ("bytes subclass", BytesSub(b"abc")), ("bytearray", bytearray(b"abc")),
                            ("memoryview", memoryview(b"abc")), ("None", None), ("int", 1), ("a list", [b"abc"])):
            with self.subTest(label):
                self.refused(label, "data must be", data, b"b")

    def test_old(self):  # E4
        for label, old in (("str", "b"), ("bytes subclass", BytesSub(b"b")), ("bytearray", bytearray(b"b")),
                           ("memoryview", memoryview(b"b")), ("None", None), ("int", 98), ("a list", [b"b"])):
            with self.subTest(label):
                self.refused(label, "old must be", b"abc", old)


# the sha256 of the pull-request job's text on origin/main at 22b9cb2 (the job Task CI3 leaves unchanged)
PULL_REQUEST_SHA256 = "8cc5ff6b4ab4956c074304f2f823b894cf04a3ade424dffa991df6314dc62b56"


if __name__ == "__main__":
    unittest.main()
