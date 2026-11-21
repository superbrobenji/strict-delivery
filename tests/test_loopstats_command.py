"""``python3 -m gates loopstats`` against ``python3 -m gates.loopstats`` (registry request Rq-6-1): the same return
code, stdout and stderr on the golden fixture, on every refusal row and on the PC1 skeleton values; and the lazy import."""
import os
import subprocess
import sys

from tests import test_loopstats as tl

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LONG = "9" * 4301


def run(module_args, cwd=ROOT):
    p = subprocess.run([sys.executable, "-m"] + module_args, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return p.returncode, p.stdout, p.stderr


class TestLoopstatsCommand(tl.Fixture):
    def both(self, args):
        direct = run(["gates.loopstats"] + args)
        via = run(["gates", "loopstats"] + args)
        self.assertEqual(via, direct)
        return via

    def test_golden_same_streams(self):  # L1
        self.golden_fixture()
        code, out, err = self.both(self.base("--narrowed", "2"))
        self.assertEqual((code, out.decode(), err), (0, tl.GOLDEN, b""))

    def test_refusals_same_as_module(self):  # L2
        for name, args in (("bogus", ["--bogus"]), ("no args", []), ("help", ["--help"])):
            with self.subTest(name):
                code, out, err = self.both(args)
                self.assertEqual((code, out), (1, b""))
                lines = err.decode().splitlines()
                self.assertEqual(len(lines), 1, err)
                self.assertTrue(lines[0].startswith("loopstats: "), err)

    def test_lazy_import(self):  # L4
        src = ("import sys\nfrom gates import __main__ as m\nm.main(['check', 'schema'])\n"
               "sys.stdout.write('LOADED=%s' % ('gates.loopstats' in sys.modules))\n")
        p = subprocess.run([sys.executable, "-c", src], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertTrue(p.stdout.decode().endswith("LOADED=False"), p.stdout + p.stderr)
        src = ("import sys\nfrom gates import __main__ as m\nm.main(['loopstats', '--bogus'])\n"
               "sys.stdout.write('LOADED=%s' % ('gates.loopstats' in sys.modules))\n")
        p = subprocess.run([sys.executable, "-c", src], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertTrue(p.stdout.decode().endswith("LOADED=True"), p.stdout + p.stderr)

    def test_pc1_values_same_as_module(self):  # K
        self.golden_fixture()
        rows = (("4300 digits", self.base(rounds="9" * 4300)), ("4301 digits", self.base(rounds=LONG)),
                ("narrowed 4301", self.base("--narrowed", LONG)), ("U+1FAE8 task", self.base(task="1x.\U0001FAE8")))
        for name, args in rows:
            with self.subTest(name):
                code, out, err = self.both(args)
                self.assertNotIn(b"Traceback", err)
                self.assertNotIn(b"ExceptionGroup", err)
                self.assertIn(code, (0, 1))
