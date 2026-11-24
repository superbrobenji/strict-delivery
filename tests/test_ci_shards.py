"""Tests of Task CI1 (input-domain table task-CI1-domain.md: rows S, M, H, R, W2 and W4 here; the other W rows are pins in
test_self_adoption). Every test calls ``tests.ci_shards.main`` on the real tests directory or on a fixture tree, or runs
``python -m tests.ci_shards``. Expected values are written by hand from the table; M1's oracle is stdlib discover."""
import contextlib
import io
import itertools
import os
import re
import subprocess
import sys
import tempfile
import unicodedata
import unittest

from tests import ci_shards
from tests import test_self_adoption as sa
from tests.helpers import within

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS = os.path.join(REPO, "tests")
PASSING = "import unittest\n\n\nclass T(unittest.TestCase):\n    def test_a(self):\n        self.assertTrue(True)\n"
COUNTER = itertools.count()


def real_modules():
    """The module names at the top of tests/, by a hand-written filter (M1's second oracle)."""
    return sorted(n[:-3] for n in os.listdir(TESTS) if re.fullmatch(r"test[A-Za-z0-9_]*\.py", n))


def sized(size):
    """A passing test module of exactly ``size`` bytes."""
    body = PASSING
    assert size >= len(body)
    return body + "#" * (size - len(body) - 1) + "\n"


class FixtureCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name
        self.new_root()

    def new_root(self):
        """A fresh empty fixture root under a package name not used before (modules are cached by name)."""
        self.package = "cishardsfx%d" % next(COUNTER)
        self.root = os.path.join(self.tmp, self.package)
        os.mkdir(self.root)
        self.addCleanup(self.forget, self.package)

    @staticmethod
    def forget(package):
        for name in [n for n in sys.modules if n == package or n.startswith(package + ".")]:
            del sys.modules[name]

    def tree(self, files, init=True):
        """Write ``files`` ({name: text}) under the fixture root; the package gets an __init__.py."""
        if init:
            self.write("__init__.py", "")
        for name, text in files.items():
            self.write(name, text)
        return self.root

    def write(self, rel, text):
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)

    def call(self, argv, root=None, run=None):
        """(exit code, stdout, stderr, recorded run calls) of main(); by default run() is recorded, not executed."""
        calls = []

        def record(package, parent, names):
            calls.append((package, parent, list(names)))
            return 0
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = ci_shards.main(argv, root=self.root if root is None else root, run=run or record)
        return code, out.getvalue(), err.getvalue(), calls

    def shard_of(self, count, index, root=None):
        code, out, err, calls = self.call(["--shards", str(count), "--index", str(index)], root)
        self.assertEqual((code, err), (0, ""), out)
        self.assertEqual(len(calls), 1)
        return calls[0][2], out

    def refused(self, argv, root=None, message=None):
        code, out, err, calls = self.call(argv, root)
        self.assertEqual((code, out, calls), (2, "", []), (argv, err))
        self.assertTrue(err.startswith("ci_shards: refused: "), err)
        self.assertEqual(err.count("\n"), 1, err)
        if message is not None:
            self.assertIn(message, err)
        return err


class ShardCountTest(FixtureCase):
    def test_workflow_value_on_real_tree(self):  # S1
        names = real_modules()
        got = []
        for k in range(1, 6):
            code, out, err, calls = self.call(["--shards", "5", "--index", str(k)], TESTS)
            self.assertEqual((code, err), (0, ""))
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0][0:2], ("tests", REPO))
            self.assertTrue(calls[0][2])
            got.append(calls[0][2])
        self.assertEqual(sorted(m for shard in got for m in shard), names)

    def test_default_root_is_the_tests_directory(self):  # S1: the CLI has no path; main() without root reads tests/
        calls = []
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = ci_shards.main(["--shards", "1", "--index", "1"], run=lambda p, parent, names: calls.append(names) or 0)
        self.assertEqual((code, calls), (0, [real_modules()]))

    def test_partition_for_every_count_up_to_ten(self):  # S2
        names = real_modules()
        for n in range(1, 11):
            shards = []
            for k in range(1, n + 1):
                code, out, err, calls = self.call(["--shards", str(n), "--index", str(k)], TESTS)
                self.assertEqual((code, err), (0, ""), (n, k))
                shards.append(calls[0][2])
            flat = [m for s in shards for m in s]
            self.assertTrue(all(shards), (n, shards))  # none empty
            self.assertEqual(len(flat), len(set(flat)), n)  # pairwise disjoint
            self.assertEqual(sorted(flat), names, n)  # union is the whole set

    def test_bad_shard_counts(self):  # S3: Arabic-indic digit five has str.isdigit() true and int() accepts it
        bad = ["0", "-1", "+5", " 5", "5 ", "5\n", "5.0", "0x5", "٥", "", "05", "1000000", "5_0", "--index"]
        for text in bad:
            self.refused(["--shards", text, "--index", "1"], TESTS, "--shards needs a whole number from 1 to 999999")
        self.assertEqual("٥".isdigit(), True)

    def test_more_shards_than_modules(self):  # S4
        self.tree({"test_a.py": PASSING, "test_b.py": PASSING, "test_c.py": PASSING})
        self.refused(["--shards", "4", "--index", "1"], message="--shards 4 asks for more shards than the 3 test modules")
        for k in (1, 2, 3):
            shard, _ = self.shard_of(3, k)
            self.assertEqual(len(shard), 1)  # the boundary: one module per shard, none empty
        code, out, err, calls = self.call(["--shards", "3", "--index", "3"])
        self.assertEqual(code, 0)

    def test_numeric_text_of_4300_and_4301_digits(self):  # S5: both interpreters; int() of that text is never reached
        errs = {}
        for digits in (4300, 4301):
            text = "9" * digits
            errs[digits] = (self.refused(["--shards", text, "--index", "1"], TESTS),
                            self.refused(["--shards", "5", "--index", text], TESTS))
        shown = "'" + "9" * 80 + "...'"
        want_n = ("ci_shards: refused: --shards needs a whole number from 1 to 999999 (ASCII digits, no sign, no leading "
                  "zero), got %s\n" % shown)
        want_k = want_n.replace("--shards needs", "--index needs")
        for digits in (4300, 4301):
            self.assertEqual(errs[digits], (want_n, want_k))
        text = "9" * 4301
        for k in ("1", text):
            self.assertEqual(self.call(["--shards", text, "--index", k], TESTS)[0], 2)

    def test_shard_index(self):  # S6
        self.tree({"test_a.py": PASSING, "test_b.py": PASSING, "test_c.py": PASSING})
        for k in (1, 2, 3):
            self.assertEqual(self.call(["--shards", "3", "--index", str(k)])[0], 0)
        for text in ("0", "4", "-1", "x", "1.0", "١", "", "+1", " 1"):
            self.refused(["--shards", "3", "--index", text], message="--index")
        self.refused(["--shards", "3"], message="--index is required")
        self.refused(["--shards", "3", "--index"], message="--index needs a value")
        self.refused(["--index", "1"], message="--shards is required")
        self.refused(["--shards", "3", "--index", "4"], message="--index 4 is past --shards 3")

    def test_arguments(self):  # S7, H5, H7: no path option exists
        self.tree({"test_a.py": PASSING, "test_b.py": PASSING})
        base = ["--shards", "2", "--index", "1"]
        for argv in (["--bogus"], base + ["--bogus", "x"], base + ["--root", self.root], ["--root", self.root] + base,
                     base + ["--shards", "2"], base + ["--index", "1"], base + ["extra"], ["extra"] + base,
                     ["--shards=2", "--index=1"], ["--shards", "--index", "1"], [], ["--SHARDS", "2", "--index", "1"],
                     ["--shard", "2", "--index", "1"], ["-h"], ["--help"]):
            self.refused(argv)
        self.refused(base + ["--root", self.root], message="unknown argument '--root'")
        self.refused(base + ["--shards", "2"], message="--shards given twice")
        self.assertEqual(self.call(base)[0], 0)
        self.assertEqual(self.call(["--index", "1", "--shards", "2"])[0], 0)


class ModuleSetTest(FixtureCase):
    def test_module_set_equals_stdlib_discover(self):  # M1: the oracles are discover itself and a listdir filter
        import unittest as ut
        found = set()

        def walk(suite):
            for item in suite:
                if isinstance(item, ut.TestSuite):
                    walk(item)
                elif type(item).__module__ == "unittest.loader":  # an import failure: the module name is the test name
                    found.add(item._testMethodName.split(".")[-1])
                else:
                    found.add(type(item).__module__.split(".")[-1])
        walk(ut.TestLoader().discover(TESTS, top_level_dir=REPO))
        names = real_modules()
        self.assertEqual(sorted(found), names)
        for n in range(1, 8):
            flat = [m for k in range(1, n + 1) for m in self.call(["--shards", str(n), "--index", str(k)], TESTS)[3][0][2]]
            self.assertEqual(sorted(flat), names)  # each module in exactly one shard
        self.assertIn("test_ci_shards", names)
        self.assertNotIn("ci_shards", names)  # the runner itself, helpers and the like are not test modules

    def test_new_module_gets_the_size_weight(self):  # M2: 1700 bytes per second, at least 1
        self.tree({"test_zzz_new.py": sized(1700 * 7 + 5), "test_zzz_tiny.py": PASSING, "test_hookio.py": PASSING})
        shard, out = self.shard_of(1, 1)
        self.assertEqual(shard, ["test_hookio", "test_zzz_new", "test_zzz_tiny"])
        self.assertEqual(out.splitlines()[0], "ci_shards: shard 1 of 1: 3 modules, weight %d" % (7 + 1 + 1))

    def test_table_entry_without_a_file_is_ignored(self):  # M3
        self.tree({"test_hookio.py": PASSING, "test_yamlsub.py": PASSING})
        shard, out = self.shard_of(1, 1)
        self.assertEqual(shard, ["test_hookio", "test_yamlsub"])
        self.assertEqual(out.splitlines()[0], "ci_shards: shard 1 of 1: 2 modules, weight 5")  # 1 + 4 seconds, by table

    def test_test_file_inside_a_package(self):  # M4
        cases = {"fixtures/test_a.py": "fixtures/__init__.py", "fixtures/deep/more/test_b.py": "fixtures/deep/more/__init__.py"}
        cases["pkg/test.py"] = "pkg/__init__.py"  # matches test*.py as well
        for rel, init in cases.items():
            with self.subTest(rel):
                self.new_root()
                self.tree({"test_ok.py": PASSING})
                self.write("fixtures/__init__.py", "")
                self.write("fixtures/deep/__init__.py", "")
                self.write(init, "")
                self.write(rel, PASSING)
                self.refused(["--shards", "1", "--index", "1"], message="'%s' sits inside a package" % rel)

    def test_directories_discover_does_not_enter(self):  # M4: no __init__.py, so discover loads nothing there; they are not refused
        self.tree({"test_ok.py": PASSING})
        self.write("data/test_c.py", PASSING)
        self.write("fixtures/__init__.py", "")
        self.write("fixtures/data.txt", "x")
        self.write("__pycache__/test_ok.cpython-39.pyc", "x")
        shard, _ = self.shard_of(1, 1)
        self.assertEqual(shard, ["test_ok"])

    def test_package_that_is_a_symlink(self):  # M4, H4: discover follows a symlinked package
        self.tree({"test_ok.py": PASSING})
        real = os.path.join(self.tmp, "elsewhere")
        os.makedirs(real)
        for name in ("__init__.py", "test_far.py"):
            with open(os.path.join(real, name), "w") as fh:
                fh.write("")
        os.symlink(real, os.path.join(self.root, "linked"))
        self.refused(["--shards", "1", "--index", "1"], message="is a symbolic link")

    def test_names_that_are_not_ascii_test_modules(self):  # M5
        for name in ("test-x.py", "testé.py", "test x.py", "test.x.py", "test٥.py"):
            with self.subTest(name):
                self.new_root()
                self.tree({"test_ok.py": PASSING})
                self.write(name, PASSING)
                self.refused(["--shards", "1", "--index", "1"], message="is not named test[A-Za-z0-9_]*.py in ASCII")

    def test_names_that_are_test_modules(self):  # M5: the boundary, accepted (discover loads these too)
        self.tree({"test.py": PASSING, "test9.py": PASSING, "testX_y.py": PASSING, "test_ok.py": PASSING,
                   "helpers.py": PASSING, "tests.py": PASSING, "ci_shards.py": PASSING, "test_x.pyc": "", "Test_y.py": PASSING})
        shard, _ = self.shard_of(1, 1)
        self.assertEqual(shard, ["test", "test9", "testX_y", "test_ok", "tests"])

    def test_code_point_whose_category_differs_by_unicode_version(self):  # M6 (PC1): U+1E030, new in Unicode 15.0
        c = chr(0x1E030)
        newer = sys.version_info >= (3, 12)  # 3.9 has Unicode 13.0 (Cn, not an identifier), 3.13 has 15.1 (Lm, an identifier)
        self.assertEqual(unicodedata.category(c), "Lm" if newer else "Cn")
        self.assertEqual(("test" + c).isidentifier(), newer)
        name = "test" + c + ".py"
        try:
            self.tree({"test_ok.py": PASSING})
            self.write(name, PASSING)
        except OSError as err:  # pragma: no cover
            self.skipTest("this filesystem refuses the name: %s" % err)
        self.refused(["--shards", "1", "--index", "1"], message="is not named test[A-Za-z0-9_]*.py in ASCII")

    def test_split_is_pinned_and_independent_of_creation_order(self):  # M7: weights from the table, worked by hand
        # 265 gate_streams, 226 gate_streams_rows, 148 gitinfo, 110 githooks, 103 index, 1 hookio: s1=265; s2=226+103;
        # s3=148+110+1 (hookio goes to the lighter of 265 and 258)
        names = ["test_gate_streams", "test_gate_streams_rows", "test_gitinfo", "test_githooks", "test_index", "test_hookio"]
        for order in (names, list(reversed(names))):
            self.new_root()
            self.tree({n + ".py": PASSING for n in order})
            want = [["test_gate_streams"], ["test_gate_streams_rows", "test_index"],
                    ["test_githooks", "test_gitinfo", "test_hookio"]]
            self.assertEqual([self.shard_of(3, k)[0] for k in (1, 2, 3)], want)
            self.assertEqual(self.shard_of(3, 3)[1].splitlines()[:4],
                             ["ci_shards: shard 3 of 3: 3 modules, weight 259", "  %s.test_githooks" % self.package,
                              "  %s.test_gitinfo" % self.package, "  %s.test_hookio" % self.package])

    def test_equal_weights_break_by_name(self):  # M7: four modules of weight 1 (table 0 s), two shards
        self.tree({n + ".py": PASSING for n in ("test_migrations", "test_batch", "test_breakdown_d", "test_breakdown")})
        self.assertEqual([self.shard_of(2, k)[0] for k in (1, 2)],
                         [["test_batch", "test_breakdown_d"], ["test_breakdown", "test_migrations"]])

    def test_real_tree_split_is_the_hand_computed_greedy_split(self):  # M7 on the real tree, N=2: the two heavy modules apart
        a, b = (self.shard_of(2, k, TESTS)[0] for k in (1, 2))
        self.assertIn("test_gate_streams", a)  # 265 s, the heaviest module of the table, opens shard 1
        self.assertIn("test_gate_streams_rows", b)  # 226 s goes to the empty shard
        self.assertIn("test_self_adoption", b)  # 185 s goes to the lighter shard (226 against 265)


class HardeningTest(FixtureCase):
    def test_symlink_module(self):  # H1
        self.tree({"test_ok.py": PASSING, "real.txt": PASSING})
        os.symlink(os.path.join(self.root, "real.txt"), os.path.join(self.root, "test_x.py"))
        self.refused(["--shards", "1", "--index", "1"], message="'test_x.py' is not a regular file")

    def test_directory_module(self):  # H2
        self.tree({"test_ok.py": PASSING})
        os.mkdir(os.path.join(self.root, "test_x.py"))
        self.refused(["--shards", "1", "--index", "1"], message="'test_x.py' is not a regular file")

    def test_fifo_module_is_never_opened(self):  # H3: an open() of a FIFO with no writer blocks, so a hang fails by name
        self.tree({"test_ok.py": PASSING})
        os.mkfifo(os.path.join(self.root, "test_x.py"))
        err = within(lambda: self.refused(["--shards", "1", "--index", "1"], message="'test_x.py' is not a regular file"))
        self.assertTrue(err)

    def test_root_is_a_symlink(self):  # H4
        self.tree({"test_ok.py": PASSING})
        link = os.path.join(self.tmp, "linkroot")
        os.symlink(self.root, link)
        self.refused(["--shards", "1", "--index", "1"], link, "is a symbolic link")
        self.refused(["--shards", "1", "--index", "1"], link + os.sep, "is a symbolic link")  # a trailing slash does not hide it
        self.refused(["--shards", "1", "--index", "1"], os.path.join(self.tmp, "missing"), "is not a directory")
        self.assertEqual(self.call(["--shards", "1", "--index", "1"], self.root)[0], 0)

    def test_root_name_that_cannot_be_a_package(self):  # the modules are imported as <root name>.<module>: refuse what is no such name
        for name in ("bad-name", "pké", "1abc", "a b"):
            root = os.path.join(self.tmp, name)
            os.mkdir(root)
            self.refused(["--shards", "1", "--index", "1"], root, "is not an ASCII package name")

    def test_undecodable_file_name(self):  # H6
        name = b"test_\xff.py"
        try:
            self.tree({"test_ok.py": PASSING})
            with open(os.path.join(os.fsencode(self.root), name), "wb"):
                pass
        except OSError as err:
            self.skipTest("this filesystem refuses an undecodable name (macOS APFS does): %s" % err)
        self.refused(["--shards", "1", "--index", "1"], message="is not named test[A-Za-z0-9_]*.py in ASCII")


class OutcomeTest(FixtureCase):
    def run_shard(self, count, index):
        code, out, err, calls = self.call(["--shards", str(count), "--index", str(index)], run=ci_shards.run_modules)
        self.assertEqual(calls, [])
        return code, out, err

    def test_pass_with_a_skip_exits_zero(self):  # R1
        self.tree({"test_a.py": PASSING + "\n    @unittest.skip('why')\n    def test_skipped(self):\n        pass\n"})
        code, out, err = self.run_shard(1, 1)
        self.assertEqual((code, err), (0, ""))
        pkg = re.escape(self.package)  # verbosity 2 names each test; 3.13 adds the method name inside the parentheses
        self.assertRegex(out, r"(?m)^test_a \(%s\.test_a\.T(\.test_a)?\) \.\.\. ok$" % pkg)
        self.assertRegex(out, r"(?m)^test_skipped \(%s\.test_a\.T(\.test_skipped)?\) \.\.\. skipped 'why'$" % pkg)
        self.assertIn("Ran 2 tests", out)
        self.assertIn("OK (skipped=1)", out)

    def test_failure_error_and_import_error_exit_one(self):  # R2
        bodies = {"failing": "import unittest\n\n\nclass T(unittest.TestCase):\n    def test_a(self):\n        self.fail('no')\n",
                  "erroring": "import unittest\n\n\nclass T(unittest.TestCase):\n    def test_a(self):\n        1 / 0\n",
                  "import_error": "import a_module_that_does_not_exist_cishards\n",
                  "raises_on_import": "raise RuntimeError('boom')\n",
                  "syntax_error": "def broken(:\n"}
        for label, body in bodies.items():
            with self.subTest(label):
                self.new_root()
                self.tree({"test_good.py": PASSING, "test_bad.py": body})
                code, out, err = self.run_shard(1, 1)
                self.assertEqual(code, 1, (out, err))
                self.assertRegex(out, r"(?m)^test_a \(.*test_good\.T(\.test_a)?\) \.\.\. ok$")  # the good module still ran
                if label in ("raises_on_import", "syntax_error"):  # not an ImportError: the loader raises, the runner reports
                    self.assertIn("ci_shards: module test_bad did not load:", err)

    def test_zero_tests_exit_one(self):  # R3
        self.tree({"test_none.py": "import unittest\n\n\nclass Helper:\n    pass\n"})
        code, out, err = self.run_shard(1, 1)
        self.assertEqual(code, 1, out)
        self.assertIn("Ran 0 tests", out)  # 3.12 and later add a line "NO TESTS RAN" after it
        self.assertEqual(err, "ci_shards: no test ran in this shard\n")

    def test_only_the_chosen_shard_runs(self):  # R1: shard 2 of 3 runs its module alone
        self.tree({"test_a.py": PASSING.replace("test_a", "test_in_a"), "test_b.py": PASSING.replace("test_a", "test_in_b"),
                   "test_c.py": PASSING.replace("test_a", "test_in_c")})
        order = [self.shard_of(3, k)[0][0] for k in (1, 2, 3)]
        self.assertEqual(order, ["test_a", "test_b", "test_c"])  # equal weights: by name
        code, out, err = self.run_shard(3, 2)
        self.assertEqual((code, err), (0, ""))
        self.assertIn("test_in_b", out)
        self.assertNotIn("test_in_a", out)
        self.assertNotIn("test_in_c", out)
        self.assertIn("Ran 1 test", out)

    def test_parent_is_not_left_on_sys_path(self):  # the fixture's parent is added only for the run
        self.tree({"test_a.py": PASSING})
        before = list(sys.path)
        self.run_shard(1, 1)
        self.assertEqual(sys.path, before)

    def test_no_exception_group_in_the_new_files(self):  # R4 (PC1): the exception-group classes are absent on 3.9
        word = "Exception" + "Group"
        for rel in ("tests/ci_shards.py", "tests/test_ci_shards.py"):
            with open(os.path.join(REPO, rel), encoding="utf-8") as fh:
                self.assertNotIn(word, fh.read(), rel)


class CommandLineTest(unittest.TestCase):
    def cli(self, *argv):
        return subprocess.run([sys.executable, "-m", "tests.ci_shards"] + list(argv), cwd=REPO, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, universal_newlines=True)

    def test_refusal_exits_two(self):
        p = self.cli("--shards", "0", "--index", "1")
        self.assertEqual((p.returncode, p.stdout), (2, ""))
        self.assertIn("ci_shards: refused: --shards needs a whole number", p.stderr)
        p = self.cli("--shards", "100000", "--index", "1")  # reads the real tests/: more shards than modules
        self.assertEqual((p.returncode, p.stdout), (2, ""))
        self.assertIn("asks for more shards than the %d test modules" % len(real_modules()), p.stderr)

    def test_lightest_shard_of_the_real_tree_runs_and_passes(self):  # one real module through the real command line
        count = len(real_modules())
        p = self.cli("--shards", str(count), "--index", str(count))
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        lines = p.stdout.splitlines()
        self.assertRegex(lines[0], r"ci_shards: shard %d of %d: 1 modules, weight 1$" % (count, count))
        self.assertRegex(lines[1], r"^  tests\.test_[a-z_]+$")
        self.assertRegex(p.stdout, r"(?m)^Ran \d+ tests? in ")  # unittest's own summary, on stdout
        self.assertRegex(p.stdout, r"(?m)^OK")


class WorkflowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = sa.read_text(os.path.join(REPO, sa.WORKFLOW))
        cls.gates = sa.job_text(cls.text, "gates")
        cls.shard = sa.job_text(cls.text, "shard")

    def test_shard_matrix_is_the_run_lines_count(self):  # W4
        values = sa.flow_items(self.shard, "shard")
        self.assertEqual(values, [["1", "2", "3", "4", "5"]])
        runs = [st["run"] for st in sa.steps(self.shard) if "run" in st]
        self.assertEqual(runs, ["python -m tests.ci_shards --shards 5 --index ${{ matrix.shard }}"])
        count = int(re.search(r"--shards (\d+) ", runs[0]).group(1))
        self.assertEqual(values[0], [str(i) for i in range(1, count + 1)])
        self.assertEqual(sa.oses(self.shard), sa.oses(self.gates))
        self.assertEqual(sa.pythons(self.shard), sa.pythons(self.gates))
        self.assertEqual(sa.oses(self.shard), [["ubuntu-24.04", "macos-15"]])
        self.assertEqual(sa.pythons(self.shard), [['"3.9"', '"3.13"']])
        self.assertLessEqual(count, len(real_modules()))  # every shard of the workflow is non-empty

    def first_step_script(self):
        first = sa.steps(self.gates)[0]
        self.assertEqual(first["name"], "Require every shard")
        return sa.PullRequestJobTest.step_script(self.gates, first["name"])

    def test_gates_first_step_passes_only_on_success(self):  # W2: the step's shell text under bash, one run per value
        script = self.first_step_script()
        self.assertEqual(sa.steps(self.gates)[0]["SHARD_RESULT"], "${{ needs.shard.result }}")
        self.assertNotIn("${{", script)  # the value reaches the shell through env, never through the run text
        rc = {}
        for value in ("success", "failure", "cancelled", "skipped", "", "SUCCESS", "success ", "successful", "success\n",
                      "*", "$(true)"):
            p = subprocess.run(["bash", "-e", "-c", script], env={"SHARD_RESULT": value, "PATH": os.environ["PATH"]},
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
            rc[value] = p.returncode
            if value != "success":
                self.assertIn("result: %s" % value, p.stderr)
            else:
                self.assertEqual((p.stdout, p.stderr), ("", ""))
        self.assertEqual(rc.pop("success"), 0)
        self.assertEqual(set(rc.values()), {1}, rc)
        p = subprocess.run(["bash", "-e", "-c", script], env={"PATH": os.environ["PATH"]}, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE)  # the variable is not set at all
        self.assertEqual(p.returncode, 1)


if __name__ == "__main__":
    unittest.main()
