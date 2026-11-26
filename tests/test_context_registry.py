"""Task R2.1, registry request Rq-5-1 (``context`` and ``receipt`` rows): ``python3 -m gates context|receipt`` against the
module entry, the lazy import, PC1 skeleton values. Expected values are written by hand from the plan."""
import builtins
import os
import subprocess
import sys
import unittest
from unittest import mock

from tests.helpers import GitIsolatedTestCase, make_repo

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run(module_args, root):
    env = dict(os.environ, PYTHONPATH=REPO, PYTHONDONTWRITEBYTECODE="1", LC_ALL="C")
    p = subprocess.run([sys.executable, "-m"] + module_args, cwd=REPO, env=env, stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, timeout=120)
    return p.returncode, p.stdout, p.stderr


class ContextRegistry(GitIsolatedTestCase):
    def setUp(self):
        super().setUp()
        self.root = make_repo(self.work)

    def both(self, command, module, args):
        direct = run([module] + args, self.root)
        via = run(["gates", command] + args, self.root)
        self.assertEqual(via, direct)
        self.assertNotIn(b"Traceback", via[2])
        return via

    def test_reachable_same_as_module(self):  # D4
        code, out, err = self.both("context", "gates.tools.context_cli", ["plan", "--root", self.root])
        self.assertNotEqual((code, out, err), (2, b"", b"usage: python3 -m gates <command> [args]\n"))
        code, out, err = self.both("receipt", "gates.tools.receipt_cli", ["add", "--session", "s", "--path", "none.txt",
                                                                        "--root", self.root])
        self.assertEqual(code, 1)
        self.assertNotIn(b"usage: python3 -m gates", err)

    def test_lazy_import(self):  # D5
        mods = ("gates.gate_context", "gates.tools.context_cli", "gates.tools.receipt_cli")
        probe = "sys.stdout.write(','.join(str(m in sys.modules) for m in %r))\n" % (mods,)
        cases = (("import sys\nfrom gates import __main__ as m\n" + probe, "False,False,False"),
                 ("import sys\nfrom gates import __main__ as m\nm.main(['context', '--bogus'])\n" + probe, None),
                 ("import sys\nfrom gates import __main__ as m\nm.main(['receipt', '--bogus'])\n" + probe, None),
                 ("import sys\nfrom gates import __main__ as m\nm.main(['check', 'context', '--bogus'])\n" + probe, None))
        env = dict(os.environ, PYTHONPATH=REPO, PYTHONDONTWRITEBYTECODE="1")
        want = ("False,False,False", "False,True,False", "False,False,True", "True,False,False")
        for (src, _), expect in zip(cases, want):
            with self.subTest(expect=expect):
                p = subprocess.run([sys.executable, "-c", src], cwd=REPO, env=env, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, timeout=120)
                self.assertTrue(p.stdout.decode().endswith(expect), p.stdout + p.stderr)

    def test_unknown_command_usage(self):  # D6
        for name in ("Context", "receipts"):
            with self.subTest(name):
                code, out, err = run(["gates", name], self.root)
                self.assertEqual((code, out), (2, b""))
                self.assertEqual(err.decode(), "usage: python3 -m gates <command> [args]\ncommands: check, claims, "
                                 "context, continue, decisions, findings, githook, githooks, hook, index, loopstats, "
                                 "program, questions, receipt, run_all\n")

    def test_pc1_digits_pass_through(self):  # P1
        for n in (4300, 4301):
            digits = "9" * n
            with self.subTest(n=n, command="receipt"):
                code, out, err = self.both("receipt", "gates.tools.receipt_cli",
                                           ["add", "--session", digits, "--path", "none.txt", "--root", self.root])
                self.assertIn(code, (1, 2))
            with self.subTest(n=n, command="context"):
                self.both("context", "gates.tools.context_cli", ["plan", "--root", self.root, digits])

    def test_pc1_unicode_command_name(self):  # P2
        # U+1FAE8 is category Cn (unassigned) in 3.9's unicodedata (Unicode 13.0) and So in 3.13's (Unicode 15.1)
        for name in ("\U0001FAE8", "context\U0001FAE8"):
            with self.subTest(name=ascii(name)):
                code, out, err = run(["gates", name], self.root)
                self.assertEqual((code, out), (2, b""))
                self.assertTrue(err.decode().startswith("usage: python3 -m gates <command> [args]\ncommands: "), err)
                self.assertNotIn(b"Traceback", err)

    def test_base_exception_propagates(self):  # P3
        from gates.__main__ import COMMANDS
        from gates.tools import context_cli, receipt_cli

        class Boom(BaseException):
            pass
        boom = Boom("x")
        groups = []
        if sys.version_info >= (3, 11):
            groups.append(BaseExceptionGroup("g", [KeyboardInterrupt()]))  # noqa: F821
        else:
            self.assertFalse(hasattr(builtins, "BaseExceptionGroup"))
        for name, mod in (("context", context_cli), ("receipt", receipt_cli)):
            for exc in [boom] + groups:
                with self.subTest(command=name, exc=type(exc).__name__):
                    with mock.patch.object(mod, "main", side_effect=exc):
                        with self.assertRaises(BaseException) as cm:
                            COMMANDS[name](["x"])
                    self.assertIs(cm.exception, exc)


if __name__ == "__main__":
    unittest.main()
