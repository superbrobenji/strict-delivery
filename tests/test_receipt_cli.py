"""Task 5a.2: ``gates/tools/receipt_cli.py`` (plan 5211, 5243; domain table 5a.2 with its binding decisions: D-Q3 (no
subcommand is exit 2), PD7 (a refusal is exit 1, a usage error exit 2), PD13 (stdout is ``yamlsub.emit(row)``), PD14).
Expected values are written by hand."""
import contextlib
import hashlib
import io
import os
import subprocess
import sys
import unittest
from unittest import mock

from gates.lib import yamlsub
from gates.tools import receipt_cli
from tests.helpers import GitIsolatedTestCase, make_repo

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SID = "3f2b8c1e-9d4a-4b7e-8f10-2a6c5d9e0b13"
HDR = "schema: receipt/1\nreads:\n"


def blob(data):
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


class Base(GitIsolatedTestCase):
    def setUp(self):
        super().setUp()
        self.root = make_repo(self.work)
        self.real = os.path.realpath(self.root)
        self.rdir = self.root + "/.strict-delivery/receipts"
        self.rf = self.rdir + "/" + SID + ".yml"

    def put(self, rel, data=b"x\n"):
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(data)
        return path

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = receipt_cli.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def add(self, *extra, session=SID, path="a.txt"):
        return self.run_cli("add", "--session", session, "--path", path, "--root", self.root, *extra)

    def env(self, **extra):
        e = dict(os.environ, PYTHONPATH=REPO, PYTHONDONTWRITEBYTECODE="1", LC_ALL="C")
        e.update(extra)
        return e

    def sub(self, *argv, cwd=None, env=None, module="gates.tools.receipt_cli"):
        p = subprocess.run([sys.executable, "-m", module] + list(argv), cwd=cwd or self.tmp,
                           env=env or self.env(), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return p.returncode, p.stdout.decode("utf-8"), p.stderr.decode("utf-8")

    def rows(self):
        with open(self.rf, "rb") as fh:
            return fh.read().decode()


class Add(Base):
    def test_receipt_add_prints_row_exit_0(self):  # CL1, CL27
        self.put("a.txt", b"hello\n")
        sha = blob(b"hello\n")
        self.assertEqual(self.add(), (0, "path: %s/a.txt\nsha: %s\n" % (self.real, sha), ""))
        self.assertEqual(self.rows(), HDR + "  - path: %s/a.txt\n    sha: %s\n" % (self.real, sha))
        self.put("b.txt", b"b")
        self.assertEqual(self.add(path="b.txt")[1], "path: %s/b.txt\nsha: %s\n" % (self.real, blob(b"b")))
        self.assertEqual(self.rows().count("  - path:"), 2)

    def test_receipt_add_default_root(self):  # CL2
        self.put("a.txt", b"a")
        want = (0, "path: %s/a.txt\nsha: %s\n" % (self.real, blob(b"a")), "")
        self.assertEqual(self.sub("add", "--session", SID, "--path", "a.txt", cwd=self.root), want)
        os.unlink(self.rf)
        self.assertEqual(self.sub("add", "--session", SID, "--path", "a.txt", cwd=self.tmp,
                                  env=self.env(CLAUDE_PROJECT_DIR=self.root)), want)
        code, out, err = self.sub("add", "--session", SID, "--path", "a.txt", cwd=self.tmp)
        self.assertEqual((code, out), (1, ""))
        self.assertTrue(err.startswith("receipt add: ") and err.endswith("\n") and err.count("\n") == 1, err)
        self.assertIn("/strict-delivery:init", err)

    def test_receipt_add_root_forms(self):  # CL3
        self.put("a.txt", b"a")
        self.assertEqual(self.add()[0], 0)
        os.mkdir(self.root + "/sub")
        plain = os.path.join(self.tmp, "plain")
        os.mkdir(plain)
        for root in (self.root + "/missing", self.root + "/a.txt", plain, self.root + "/sub"):
            with self.subTest(root=root):
                code, out, err = self.run_cli("add", "--session", SID, "--path", "a.txt", "--root", root)
                self.assertEqual((code, out), (1, ""))
                self.assertTrue(err.startswith("receipt add: ") and err.count("\n") == 1, err)
        self.assertEqual(self.run_cli("add", "--session", SID, "--path", "a.txt", "--root", ""),
                         (1, "", "receipt add: --root: must not be empty\n"))
        self.assertEqual(self.run_cli("add", "--session", SID, "--path", "a.txt", "--root", self.root, "--root", self.root),
                         (1, "", "receipt add: --root given more than once\n"))
        old = os.getcwd()
        self.addCleanup(os.chdir, old)
        os.chdir(self.tmp)
        self.assertEqual(self.run_cli("add", "--session", SID, "--path", "a.txt", "--root", "work")[0], 0)

    def test_receipt_add_missing_flags(self):  # CL4, CL5, CL6
        self.assertEqual(self.run_cli("add", "--path", "a.txt", "--root", self.root),
                         (1, "", "receipt add: --session is required\n"))
        self.assertEqual(self.run_cli("add", "--session", SID, "--root", self.root),
                         (1, "", "receipt add: --path is required\n"))
        self.assertEqual(self.run_cli("add"), (1, "", "receipt add: --session is required\n"))

    def test_receipt_add_repeated_flags(self):  # CL7
        self.put("a.txt")
        for argv, flag in ((["--session", SID, "--session", "t", "--path", "a.txt"], "--session"),
                           (["--session", SID, "--path", "a.txt", "--path", "b"], "--path"),
                           (["--session", SID, "--path", "a.txt", "--root", self.root, "--root", self.root], "--root")):
            with self.subTest(flag=flag):
                code, out, err = self.run_cli("add", *argv)
                self.assertEqual(out, "")
                self.assertIn(code, (1, 2))
                self.assertIn("%s given more than once" % flag, err)
                self.assertEqual(err.count("\n") >= 1, True)
        self.assertFalse(os.path.lexists(self.rdir))

    def test_receipt_add_bad_session(self):  # CL8
        self.put("a.txt")
        for s in ("", "../x", "a/b", "a" * 129, "A\n"):
            with self.subTest(s=s):
                code, out, err = self.add(session=s)
                self.assertEqual((code, out), (1, ""))
                self.assertEqual(err, "receipt add: session: must be 1 to 128 characters, A-Z a-z 0-9 _ -, starting "
                                      "with a letter or a digit\n")
        self.assertFalse(os.path.lexists(self.rdir))

    def test_receipt_add_path_refusals(self):  # CL9, CL20
        os.mkdir(self.root + "/dir")
        os.mkfifo(self.root + "/f")
        self.put("u")
        os.chmod(self.root + "/u", 0)
        self.addCleanup(os.chmod, self.root + "/u", 0o600)
        cases = ["nope", "dir", "f", "a\0b"]
        if os.geteuid() != 0:
            cases.append("u")
        for p in cases:
            with self.subTest(p=p):
                code, out, err = self.add(path=p)
                self.assertEqual((code, out), (1, ""))
                self.assertTrue(err.startswith("receipt add: ") and err.count("\n") == 1, err)
        self.assertFalse(os.path.lexists(self.rdir))
        self.put("a.txt")
        target = os.path.join(self.tmp, "t")
        os.mkdir(target)
        os.symlink(target, self.rdir)
        code, out, err = self.add()
        self.assertEqual((code, out), (1, ""))
        self.assertIn("is a symlink", err)
        self.assertEqual(os.listdir(target), [])
        self.assertTrue(os.path.islink(self.rdir))

    def test_receipt_add_stdout_is_emit_of_row(self):  # CL10
        for i, n in enumerate(("plain.md", "a: b#c 'd\".md", "x\ny", "x\n\ny", " lead", "é中", "x y", "x\ry")):
            with self.subTest(n=n):
                self.put(n, b"v%d" % i)
                code, out, err = self.add(path=n, session="s%d" % i)
                self.assertEqual((code, err), (0, ""))
                self.assertEqual(yamlsub.parse(out), {"path": self.real + "/" + n, "sha": blob(b"v%d" % i)})
                self.assertTrue(out.startswith("path: ") and out.endswith("\n"))

    def test_receipt_add_stderr_one_line(self):  # CL11
        for p in ("no\nsuch\x1b[31mé", "é中-missing"):
            with self.subTest(p=p):
                code, out, err = self.add(path=p)
                self.assertEqual((code, out), (1, ""))
                self.assertTrue(err.startswith("receipt add: ") and err.endswith("\n"), err)
                self.assertEqual(err.count("\n"), 1)
                self.assertNotIn("\x1b", err)
                self.assertNotIn("Traceback", err)

    def test_receipt_add_exit_codes(self):  # CL12, CL16
        self.put("a.txt")
        self.assertEqual(self.add()[0], 0)
        self.assertEqual(self.add(path="nope")[0], 1)
        for argv in ([], ["remove"], ["Add"], ["ADD"], ["-h"], ["add", "-h"], ["add", "--bogus", "1"],
                     ["add", "x", "--session", SID, "--path", "a.txt"], ["--json", "add", "--session", SID, "--path", "a"],
                     ["add", "--session"]):
            with self.subTest(argv=argv):
                code, out, err = self.run_cli(*argv)
                self.assertEqual((code, out), (2, ""))
                self.assertNotEqual(err, "")

    def test_receipt_add_flag_forms(self):  # CL13, CL17, CL19
        self.put("a.txt", b"a")
        want = "path: %s/a.txt\nsha: %s\n" % (self.real, blob(b"a"))
        self.assertEqual(self.run_cli("add", "--session=" + SID, "--path=a.txt", "--root=" + self.root), (0, want, ""))
        self.assertEqual(self.run_cli("add", "--ses", SID, "--pa", "a.txt", "--ro", self.root), (0, want, ""))

    def test_receipt_add_dash_values(self):  # CL14
        self.put("-x", b"d")
        self.put("sub/-5", b"n")
        for v in ("-x", "--x", "--"):
            with self.subTest(v=v):
                code, out, err = self.run_cli("add", "--session", SID, "--path", v, "--root", self.root)
                self.assertEqual((code, out), (2, ""))
        self.assertEqual(self.run_cli("add", "--session", SID, "--path=-x", "--root", self.root)[0], 0)
        self.assertEqual(self.run_cli("add", "--session", SID, "--path", "./-x", "--root", self.root)[0], 0)

    def test_receipt_main_argv_types(self):  # CL15
        for argv in (("add",), ["add", 3], "add"):
            with self.subTest(argv=argv):
                out, err = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    code = receipt_cli.main(argv)
                self.assertEqual((code, out.getvalue(), err.getvalue()), (2, "", "receipt: argv must be a list of str\n"))
        self.put("a.txt")
        old = sys.argv
        self.addCleanup(setattr, sys, "argv", old)
        sys.argv = ["receipt", "add", "--session", SID, "--path", "a.txt", "--root", self.root]
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(receipt_cli.main(), 0)
        self.assertTrue(out.getvalue().startswith("path: "))

    def test_receipt_help_exit_2(self):  # CL18, VN5
        for argv in (["-h"], ["add", "-h"], ["--help"]):
            code, out, err = self.run_cli(*argv)
            self.assertEqual((code, out), (2, ""))
            self.assertIn("usage:", err)

    def test_receipt_cli_module_main_guard(self):  # CL21
        self.put("a.txt", b"a")
        code, out, err = self.sub("add", "--session", SID, "--path", "a.txt", "--root", self.root)
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(out, "path: %s/a.txt\nsha: %s\n" % (self.real, blob(b"a")))
        self.assertEqual(self.sub()[0], 2)
        self.assertEqual(self.sub("add", "--session", SID)[0:2], (1, ""))

    def test_cli_subprocess_equals_in_process(self):  # CL21
        self.put("a.txt", b"a")
        for argv in (["add", "--session", SID, "--path", "a.txt", "--root", self.root],
                     ["add", "--session", SID, "--path", "nope", "--root", self.root],
                     ["add", "--session", "../x", "--path", "a.txt", "--root", self.root],
                     ["add", "--session", SID]):
            with self.subTest(argv=argv):
                want = self.run_cli(*argv)
                self.assertEqual(self.sub(*argv), want)

    def test_receipt_command_registered(self):  # CL22
        from gates.__main__ import COMMANDS
        if "receipt" not in COMMANDS:
            self.skipTest("Rq-5-1 not on this branch")
        self.put("a.txt")
        argv = ["add", "--session", "t", "--path", "a.txt", "--root", self.root]
        p = subprocess.run([sys.executable, "-m", "gates", "receipt"] + argv, cwd=REPO, env=self.env(),
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual((p.returncode, p.stdout.decode()), self.sub(*argv)[:2])

    def test_receipt_add_unaffected_by_git_config(self):  # CL25
        self.put("a.txt", b"a")
        env = self.env(GIT_INDEX_FILE=os.path.join(self.tmp, "idx"), GIT_CONFIG_COUNT="2", GIT_CONFIG_KEY_0="color.ui",
                       GIT_CONFIG_VALUE_0="always", GIT_CONFIG_KEY_1="core.abbrev", GIT_CONFIG_VALUE_1="7")
        code, out, err = self.sub("add", "--session", SID, "--path", "a.txt", "--root", self.root, env=env)
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(out, "path: %s/a.txt\nsha: %s\n" % (self.real, blob(b"a")))

    def test_receipt_cli_catches_only_gateerror(self):  # CL28
        self.put("a.txt")
        with mock.patch.object(receipt_cli.receipts, "record", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                self.add()

    def test_receipt_add_unencodable_stdout(self):  # CL29
        n = "\U0001fae8.md"
        self.put(n, b"u")
        code, out, err = self.sub("add", "--session", SID, "--path", n, "--root", self.root,
                                  env=self.env(PYTHONIOENCODING="ascii"))
        self.assertEqual((code, out), (1, ""))
        self.assertEqual(err, "receipt add: a path cannot be encoded for the output\n")


if __name__ == "__main__":
    unittest.main()
