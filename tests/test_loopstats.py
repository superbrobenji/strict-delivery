"""Tests for ``loopstats`` (Task 6E.3): ``gates.loopstats.main`` on fixture repositories for the CLI rows, the
library functions for the formula rows. Every expected value is written by hand from spec section 10, the plan's
research table and the input-domain table's GOLDEN, or computed by the independent enumeration ``brute_p`` below
(``itertools.product``, meet in the middle); none is read back from the code under test."""
import contextlib
import io
import itertools
import json
import math
import os
import random
import subprocess
import sys
import unittest
from fractions import Fraction

from gates import __main__ as gates_main
from gates.lib import config, migrations
from gates.lib.loopstats import (ev, geo_fit, report, rule_n, small_signals, trend, verdict)
from gates.lib.result import GateError
from gates.lib.store import Record
from gates import loopstats as cli
from tests.helpers import GitIsolatedTestCase, git, make_repo, minimal_config, write_record

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FDIR = ".strict-delivery/state/findings"
ALPHA32 = "23456789abcdefghijkmnpqrstuvwxyz"
SHA = "a1b2c3d"

GOLDEN = (
    "LOOPSTATS plan=p task=1x.1 rounds=4 X=4,5,3,5 W=8,10,6,10 N=34 S=52 narrowed=2\n"
    "RULE-T p=0.591 u=+0.15 q=1(boundary) R=unbounded E_next=8.500\n"
    "RULE-N nu=1.000 fired=yes\n"
    "EV unset: escape_cost not configured\n"
    "VERDICT ESCALATE (Rule N fired after a narrowing)\n"
    "Loopstats: 1x.1 r4: X=4,5,3,5 W=8,10,6,10 p=0.591 q=1(boundary) nu=1.000 -> ESCALATE\n")
GOLDEN_JSON = (
    '{"E_next": "8.500", "N": 34, "R": "unbounded", "S": 52, "W": [8, 10, 6, 10], "X": [4, 5, 3, 5], '
    '"ev": "unset: escape_cost not configured", '
    '"ledger": "Loopstats: 1x.1 r4: X=4,5,3,5 W=8,10,6,10 p=0.591 q=1(boundary) nu=1.000 -> ESCALATE", '
    '"narrowed": [2], "note": null, "nu": "1.000", "p": "0.591", "plan": "p", "q": "1(boundary)", '
    '"reason": "Rule N fired after a narrowing", "rounds": 4, "rule_n": true, "task": "1x.1", "u": "+0.15", '
    '"verdict": "ESCALATE"}\n')


def fmt3(f):
    return "%d.%03d" % divmod(round(f * 1000), 1000)


def brute_p(counts):
    """P(S' <= S) by enumerating the draws with itertools.product, each half of the N draws separately."""
    k = len(counts)
    n = sum(counts)
    s = sum(i * c for i, c in enumerate(counts))
    half = n // 2

    def dist(m):
        d = {}
        for t in itertools.product(range(k), repeat=m):
            d[sum(t)] = d.get(sum(t), 0) + 1
        return d
    a, b = dist(half), dist(n - half)
    good = sum(ca * cb for sa, ca in a.items() for sb, cb in b.items() if sa + sb <= s)
    return Fraction(good, k ** n)


def fid(i):
    return "F-20261031-%s%s%s%s" % (ALPHA32[i // 32768 % 32], ALPHA32[i // 1024 % 32], ALPHA32[i // 32 % 32],
                                    ALPHA32[i % 32])


def frow(i, rnd, sev="MEDIUM", dim=None, caused=True, plan="p", task="1x.1", **over):
    """A valid finding row owned by ``plan``/``task`` with the Rule N and T fields (any may be dropped via over)."""
    row = {"schema": "finding/%d" % migrations.current_version("finding"), "id": fid(i), "status": "open", "source": "review", "severity": sev,
           "class": "bug", "siblings": [], "cites": [{"file": "src/x.py", "lines": "1-2", "sha": SHA}],
           "repro": None, "owner": {"kind": "plan", "plan": plan, "task": task}, "pin": None, "ruling": None,
           "evidence": [], "history": [{"status": "open", "sha": SHA, "by": "agent"}],
           "review_round": rnd, "caused_by_change": caused, "dimension": dim if dim is not None else "d%d" % i}
    row.update(over)
    return {k: v for k, v in row.items() if v is not _DROP}


_DROP = object()


def rec(row):
    return Record(row.get("id"), row, "x/%s.yml" % row.get("id"))


def series(*per_round, sev="MEDIUM"):
    """Records: ``per_round[i]`` findings in review i + 1, each with its own dimension."""
    rows, n = [], 0
    for rnd, count in enumerate(per_round, start=1):
        for _ in range(count):
            rows.append(rec(frow(n, rnd, sev)))
            n += 1
    return rows


class Fixture(GitIsolatedTestCase):
    def setUp(self):
        super().setUp()
        self.root = make_repo(self.work, minimal_config())
        self.cfg = config.load(self.root)

    def put(self, row):
        write_record(self.root, "%s/%s.yml" % (FDIR, row["id"]), row)

    def put_series(self, *per_round, sev="MEDIUM"):
        for r in series(*per_round, sev=sev):
            self.put(r.row)

    def run_main(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(argv)
        return code, out.getvalue(), err.getvalue()

    def base(self, *extra, plan="p", task="1x.1", rounds="4"):
        return ["--plan", plan, "--task", task, "--rounds", rounds, "--root", self.root] + list(extra)

    def refused(self, argv, needle):
        code, out, err = self.run_main(argv)
        self.assertEqual((code, out), (1, ""), err)
        lines = [ln for ln in err.splitlines() if ln.startswith("loopstats: ")]
        self.assertEqual(len(lines), 1, err)
        self.assertEqual(err.splitlines()[-1], lines[0])
        self.assertIn(needle, err)
        self.assertNotIn("Traceback", err)
        return err

    def golden_fixture(self):
        self.put_series(4, 5, 3, 5)


class TestCli(Fixture):
    def test_cli_output_golden(self):  # O1, O2, E1
        self.golden_fixture()
        code, out, err = self.run_main(self.base("--narrowed", "2"))
        self.assertEqual((code, out, err), (0, GOLDEN, ""))

    def test_cli_output_mixed(self):  # O2: review 1 CRITICAL HIGH MEDIUM LOW, review 2 one LOW, review 3 two LOW
        n = 0
        for rnd, sevs in ((1, ["CRITICAL", "HIGH", "MEDIUM", "LOW"]), (2, ["LOW"]), (3, ["LOW", "LOW"])):
            for s in sevs:
                self.put(frow(n, rnd, s))
                n += 1
        code, out, err = self.run_main(self.base(rounds="3"))
        self.assertEqual(code, 0, err)
        self.assertIn("X=4,1,2 W=15,1,2 N=18 S=5 narrowed=none", out)
        self.assertIn("VERDICT LOW_PLATEAU (only LOW findings in the last 2 reviews)", out)
        self.assertNotIn("NOTE", out)

    def test_cli_rule_t_non_boundary(self):  # S4 (review-1 F1): the RULE-T line of a fit with q != 1/2
        self.put_series(6, 3, 1)  # all MEDIUM: W = 12,6,2, N = 20, S = 10
        q, _a, big_r, e_next = TestFormulas.closed_fit([12, 6, 2])
        u = (10 - 20 * 1.0) / math.sqrt(20 * 8 / 12.0)
        want = "RULE-T p=%s u=%+.2f q=%.3f R=%.3f E_next=%.3f" % (fmt3(brute_p([12, 6, 2])), u, q, big_r, e_next)
        code, out, err = self.run_main(self.base(rounds="3"))
        self.assertEqual((code, err), (0, ""))
        self.assertIn(want + "\n", out)
        self.assertIn("q=0.434 R=1.784 E_next=1.009\n", out)

    def test_cli_half_to_even(self):  # D9 (review-1 F3): values whose x1000 ends exactly in .5
        for i in range(8):  # q = 1/16 exactly: W = 16,1, N = 17, S = 1, m(q) = q/(1+q) = 1/17; 62.5 -> 62
            self.put(frow(i, 1))
        self.put(frow(8, 2, "LOW"))
        code, out, err = self.run_main(self.base(rounds="2"))
        self.assertEqual((code, err), (0, ""))
        self.assertIn(" q=0.062 ", out)
        self.assertIn("q=0.062 nu=1.000 ->", out)

    def test_cli_half_to_even_rounds_up(self):  # D9: 3/16 = 0.1875: 187.5 -> 188 (even)
        self.put(frow(0, 1, dim="a"))
        for i in range(1, 14):
            self.put(frow(i, 2, dim="a"))
        for i, d in enumerate("cde", start=14):
            self.put(frow(i, 2, dim=d))
        code, out, err = self.run_main(self.base(rounds="2"))
        self.assertEqual((code, err), (0, ""))
        self.assertIn("X=1,16 ", out)
        self.assertIn("RULE-N nu=0.188 fired=no\n", out)
        self.assertIn(" nu=0.188 -> ", out)

    def test_cli_note_line(self):  # O3
        note = "NOTE CRITICAL or HIGH findings caused by the change are fixed whatever the verdict\n"
        for sev, want in (("CRITICAL", True), ("HIGH", True), ("MEDIUM", False), ("LOW", False)):
            with self.subTest(sev=sev):
                self.put(frow(0, 1, sev))
                code, out, err = self.run_main(self.base(rounds="1"))
                self.assertEqual(code, 0, err)
                self.assertEqual(note in out, want)
                if want:  # the NOTE sits between VERDICT and the ledger line
                    lines = out.splitlines(True)
                    self.assertEqual((lines[-2], lines[-3].startswith("VERDICT")), (note, True))
        self.put(frow(1, 1, "HIGH", caused=False))  # only a change-caused finding counts
        self.put(frow(0, 1, "MEDIUM"))
        self.assertNotIn("NOTE", self.run_main(self.base(rounds="1"))[1])

    def test_cli_json_position(self):  # A5, D4
        self.golden_fixture()
        core = ["--plan", "p", "--task", "1x.1", "--rounds", "4", "--narrowed", "2", "--root", self.root]
        for name, argv in (("first", ["--json"] + core), ("last", core + ["--json"]),
                           ("between", core[:4] + ["--json"] + core[4:])):
            with self.subTest(name):
                self.assertEqual(self.run_main(argv), (0, GOLDEN_JSON, ""))

    def test_cli_argv_by_hand(self):  # D1-D4 argv rules without argparse (fix round 2)
        self.golden_fixture()
        root = ["--root", self.root]
        core = ["--plan", "p", "--task", "1x.1", "--rounds", "4"]
        refusals = (  # (argv, text the one stderr line must hold)
            (core + root + ["--rou", "4"], "--rou"),                    # an abbreviation of --rounds
            (["--plan", "p", "--task", "1x.1", "--roun", "4"] + root, "--roun"),
            (core + root + ["--help"], "--help"),
            (core + root + ["-h"], "-h"),
            (core + root + ["--"], "unknown argument --"),
            (core + root + ["stray"], "stray"),
            (core + root + ["--bogus=1"], "--bogus=1"),
            (["--plan", "p", "--task", "1x.1", "--root", self.root, "--rounds"], "--rounds: value missing"),
            (["--plan"], "--plan: value missing"),
            (["--narrowed"] + core + root, "--narrowed"),                # takes "--plan" as its value
            (["--task", "--json", "--plan", "p", "--rounds", "4"] + root, "--task"),   # a value starting with --
            (["--task=--json", "--plan", "p", "--rounds", "4"] + root, "--task"),
            (core + root + ["--root", self.root], "--root given more than once"),
            (core + root + ["--plan=q"], "--plan given more than once"),
            (core + root + ["--json", "--json"], "--json given more than once"),
            (core + root + ["--json=1"], "--json"),
            (core + root + ["--narrowed", "-2"], "--narrowed"),
            (["--task", "-x", "--plan", "p", "--rounds", "4"] + root, "--task"),
        )
        for argv, needle in refusals:
            with self.subTest(argv=argv):
                self.refused(argv, needle)
        eq = ["--plan=p", "--task=1x.1", "--rounds=4", "--narrowed=2", "--root=" + self.root]
        self.assertEqual(self.run_main(eq), (0, GOLDEN, ""))
        self.assertEqual(self.run_main(core + root + ["--narrowed", "2"]), (0, GOLDEN, ""))
        self.assertFalse(hasattr(cli, "argparse"))

    def test_cli_plan_arg(self):  # A1
        self.golden_fixture()
        for bad in ("", "a/b", "..", "A", "-a", "a_b", "é"):
            with self.subTest(plan=bad):
                self.refused(self.base(plan=bad), "--plan")
        self.refused(["--task", "1x.1", "--rounds", "4", "--root", self.root], "--plan")
        for good in ("p", "2026-plan"):
            with self.subTest(plan=good):
                self.assertEqual(self.run_main(self.base(plan=good))[0], 0)

    def test_cli_task_arg(self):  # A2
        self.refused(["--plan", "p", "--rounds", "4", "--root", self.root], "--task")
        self.refused(self.base(task=""), "--task")
        for good in ("1x.1", "nothing"):
            with self.subTest(task=good):
                code, out, err = self.run_main(self.base(task=good))
                self.assertEqual((code, err), (0, ""))
                self.assertIn("task=%s " % good, out)

    def test_cli_rounds_arg(self):  # A3, D1
        self.refused(["--plan", "p", "--task", "1x.1", "--root", self.root], "--rounds")
        for bad in ("0", "-1", "x", "3.0", " 3", "+3", "1_0", "٣", "100", "", "03", "3\n"):
            with self.subTest(rounds=bad):
                self.refused(self.base(rounds=bad), "--rounds")
        self.refused(self.base() + ["--rounds", "3"], "--rounds")
        for good in ("1", "99"):
            with self.subTest(rounds=good):
                code, out, err = self.run_main(self.base(rounds=good))
                self.assertEqual((code, err), (0, ""), err)
                self.assertIn("rounds=%s " % good, out)

    def test_cli_narrowed_arg(self):  # A4, D3, W1
        self.golden_fixture()
        for bad in (["0"], ["4"], ["5"], ["x"], ["2", "2"], ["-1"], [" 2"]):
            with self.subTest(narrowed=bad):
                argv = self.base()
                for r in bad:
                    argv += ["--narrowed", r]
                self.refused(argv, "--narrowed")
        self.refused(self.base("--narrowed", "1", rounds="1"), "--narrowed")
        for given, want in ((["1", "2"], "1,2"), (["2", "1"], "1,2"), (["3"], "3"), ([], "none")):
            with self.subTest(narrowed=given):
                argv = self.base()
                for r in given:
                    argv += ["--narrowed", r]
                code, out, err = self.run_main(argv)
                self.assertEqual(code, 0, err)
                self.assertIn(" narrowed=%s\n" % want, out)

    def test_cli_root_refused(self):  # A6, D10
        self.golden_fixture()
        argv = ["--plan", "p", "--task", "1x.1", "--rounds", "4"]
        sub = os.path.join(self.root, "sub")
        os.mkdir(sub)
        plain = os.path.join(self.tmp, "plain")
        os.mkdir(plain)
        bare_repo = os.path.join(self.tmp, "norepo")
        os.mkdir(bare_repo)
        git(bare_repo, "init", "-q", "-b", "main")
        for name, root in (("missing", os.path.join(self.tmp, "nope")), ("file", os.path.join(self.root, ".git", "HEAD")),
                           ("plain", plain), ("subdir", sub), ("no config", bare_repo)):
            with self.subTest(name):
                self.refused(argv + ["--root", root], "")
        write_record(self.root, ".strict-delivery/config.yml", dict(minimal_config(), escape_cost={
            "CRITICAL": 1, "HIGH": 1, "MEDIUM": 1, "LOW": 1}))
        self.refused(argv + ["--root", self.root], "escape_cost")

    def test_cli_default_root(self):  # D10: --root defaults to result.repo_root()
        from unittest import mock
        self.golden_fixture()
        with mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": self.root}):
            code, out, err = self.run_main(["--plan", "p", "--task", "1x.1", "--rounds", "4", "--narrowed", "2"])
        self.assertEqual((code, out, err), (0, GOLDEN, ""))

    def test_cli_unknown_flag(self):  # A7
        self.golden_fixture()
        for extra in (["--bogus"], ["extra"], ["--help"], ["--ro", "x"], ["--json=1"]):
            with self.subTest(extra=extra):
                self.refused(self.base(*extra), "")

    def test_cli_refuses_unclassified_finding(self):  # controller ruling 6E
        self.golden_fixture()
        bad = frow(900, 1, review_round=_DROP)
        self.put(bad)
        err = self.refused(self.base(), "review_round")
        self.assertIn(bad["id"], err)

    def test_cli_invalid_record(self):  # D5 through the store
        self.golden_fixture()
        bad = frow(900, 1, severity="BAD")
        self.put(bad)
        self.assertIn(bad["id"], self.refused(self.base(), "severity"))

    def test_escape_cost_shape_refused(self):
        # E2: under config/2 config.load refuses a malformed escape_cost with its own message; a well-formed one is
        # refused by loopstats itself (fail closed) until the registered follow-up "6E.3 escape_cost read after
        # config/2" reads it. Every shape exits 1 with one stderr line.
        self.golden_fixture()
        full = {"CRITICAL": 1, "HIGH": 1, "MEDIUM": 1, "LOW": 1}
        cfg = ".strict-delivery/config.yml"
        lead = "loopstats: " + cfg + ": "
        closed = "loopstats: escape_cost is set, but reading it needs config/2, which is not available yet"
        low = lead + "escape_cost.LOW: must be an integer of at least 0"
        digits_cap = lead + "escape_cost.LOW: must be an integer of at most 600 digits"
        shapes = {
            "valid": (full, closed),
            "missing LOW": ({k: 1 for k in ("CRITICAL", "HIGH", "MEDIUM")}, lead + "escape_cost.LOW: required key is missing"),
            "INFO": (dict(full, INFO=1), lead + "unknown key 'escape_cost.INFO'"),
            "negative": (dict(full, LOW=-1), low), "bool": (dict(full, LOW=True), low),
            "string": (dict(full, LOW="2"), low), "zeros": ({k: 0 for k in full}, closed),
            "U+1FAE8 key": (dict(full, **{"\U0001FAE8": 1}), lead + "unknown key 'escape_cost.\\U0001fae8'"),
        }
        # PC1: emit refuses an integer over yamlsub.MAX_INT_CHARS, so the digit rows are written as text; the parser's
        # own cap refuses them before config.load's 600-digit cap and before int()'s 4300-digit text limit matter.
        yaml_cap = lead + "integer too large (line 8)"
        big = {"4300 digits": ("9" * 4300, yaml_cap), "4301 digits": ("9" * 4301, yaml_cap),
               "1001 digits": ("9" * 1001, yaml_cap), "1000 digits": ("9" * 1000, digits_cap),
               "601 digits": ("9" * 601, digits_cap)}
        for name, (shape, line) in shapes.items():
            with self.subTest(name):
                write_record(self.root, cfg, dict(minimal_config(), escape_cost=shape))
                err = self.refused(self.base(), "escape_cost")
                self.assertEqual(err.splitlines()[-1], line)
        for name, (text, line) in big.items():
            with self.subTest(name):
                path = write_record(self.root, cfg, dict(minimal_config(), escape_cost=full))
                with open(path, encoding="utf-8") as fh:
                    body = fh.read()
                self.assertEqual(body.count("LOW: 1\n"), 1)
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(body.replace("LOW: 1\n", "LOW: " + text + "\n"))
                err = self.refused(self.base(), "")
                self.assertEqual(err.splitlines()[-1], line)

    def test_module_main_golden(self):  # A9
        self.golden_fixture()
        p = subprocess.run([sys.executable, "-m", "gates.loopstats"] + self.base("--narrowed", "2"), cwd=ROOT,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual((p.returncode, p.stdout.decode(), p.stderr.decode()), (0, GOLDEN, ""))

    def test_loopstats_command_registered(self):  # A10
        self.golden_fixture()
        p = subprocess.run([sys.executable, "-m", "gates", "loopstats"] + self.base("--narrowed", "2"), cwd=ROOT,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual((p.returncode, p.stdout.decode()), (0, GOLDEN))

    def test_pc1_long_numbers(self):  # K1
        self.golden_fixture()
        for digits in (4300, 4301):
            with self.subTest(argv=digits):
                self.refused(self.base(rounds="9" * digits), "--rounds")
                self.refused(self.base("--narrowed", "9" * digits), "--narrowed")
        path = os.path.join(self.root, FDIR, fid(0) + ".yml")
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("review_round: 1\n", text)
        msgs = []
        for digits in (4300, 4301):
            with self.subTest(row=digits):
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(text.replace("review_round: 1\n", "review_round: %s\n" % ("9" * digits)))
                code, out, err = self.run_main(self.base())
                self.assertEqual((code, out), (1, ""))
                self.assertTrue(err.startswith("loopstats: ") and "Traceback" not in err, err)
                msgs.append(err.replace(str(digits), "N"))
        self.assertEqual(msgs[0].count("\n"), 1)

    def test_pc1_unicode_task(self):  # K2
        task = "1x.\U0001F6DD"
        for i, rnd in enumerate((1, 1)):
            self.put(frow(i, rnd, task=task))
        code, out, err = self.run_main(self.base(task=task, rounds="1"))
        self.assertEqual((code, err), (0, ""))
        self.assertIn("task=1x.\\U0001f6dd rounds=1 ", out)
        self.assertTrue(out.endswith("-> CONTINUE\n"))
        self.assertIn("Loopstats: 1x.\\U0001f6dd r1:", out)


class TestRows(Fixture):
    def rep(self, rows, rounds=4, narrowed=(), plan="p", task="1x.1"):
        return report(rows, plan, task, rounds, list(narrowed), self.cfg)

    def refuses(self, rows, needle, rid, **kw):
        with self.assertRaises(GateError) as cm:
            self.rep(rows, **kw)
        self.assertIn(needle, str(cm.exception))
        self.assertIn(rid, str(cm.exception))

    def test_rows_excluded(self):  # R1
        base = series(2, 1)
        issue = {"kind": "issue", "number": 7}
        rows = base + [
            rec(frow(10, 1, plan="other")), rec(frow(11, 2, task="2x.1")),
            rec(frow(12, 1, owner=issue, review_round=_DROP, caused_by_change=_DROP, dimension=_DROP)),
            rec(frow(13, 1, owner={"kind": "roadmap", "plan": "p"}))]
        r = self.rep(rows, rounds=2)
        self.assertEqual((r["X"], r["W"], r["N"]), ([2, 1], [4, 2], 6))
        self.assertEqual(r["nu"], Fraction(1))

    def test_rows_info(self):  # R2
        rows = series(1, 1) + [rec(frow(10, 1, "INFO"))]
        self.assertEqual(self.rep(rows, rounds=2)["X"], [1, 1])
        for field in ("review_round", "caused_by_change"):
            with self.subTest(field):
                self.refuses(series(1, 1) + [rec(frow(10, 1, "INFO", **{field: _DROP}))], field, fid(10), rounds=2)

    def test_rows_caused_by_change(self):  # R3
        rows = series(1, 1) + [rec(frow(10, 1, caused=False, dimension=_DROP)), rec(frow(11, 2, caused=False))]
        self.assertEqual(self.rep(rows, rounds=2)["X"], [1, 1])
        self.refuses(series(1) + [rec(frow(10, 1, caused_by_change=_DROP))], "caused_by_change", fid(10), rounds=2)

    def test_rows_review_round(self):  # R4
        self.refuses(series(1) + [rec(frow(10, 1, review_round=_DROP))], "review_round", fid(10), rounds=2)
        self.refuses(series(1) + [rec(frow(10, 3))], "review_round", fid(10), rounds=2)
        self.refuses(series(1) + [rec(frow(10, 3, "INFO"))], "review_round", fid(10), rounds=2)
        self.assertEqual(self.rep(series(1, 1) + [rec(frow(10, 2))], rounds=2)["X"], [1, 2])
        self.assertEqual(self.rep([rec(frow(10, 1))], rounds=1)["X"], [1])

    def test_rows_invalid(self):  # R5
        self.refuses([rec(frow(10, 1, severity="BAD"))], "severity", fid(10), rounds=2)
        self.refuses([rec(frow(10, 1, task="2x.1", severity="BAD"))], "severity", fid(10), rounds=2)
        self.refuses([Record(fid(11), 5, "x.yml")], "finding", fid(11), rounds=2)
        self.refuses([Record(fid(12), {"id": fid(12)}, "x.yml")], "schema", fid(12), rounds=2)

    def test_rows_dimension(self):  # R6
        self.refuses([rec(frow(10, 1, dimension=_DROP))], "dimension", fid(10), rounds=1)
        self.refuses([rec(frow(10, 1, "LOW", dimension=_DROP))], "dimension", fid(10), rounds=1)
        rows = [rec(frow(10, 1, dimension=_DROP, caused=False)), rec(frow(11, 1, "INFO", dimension=_DROP)),
                rec(frow(12, 1))]
        self.assertEqual(self.rep(rows, rounds=1)["X"], [1])

    def test_rows_status_ignored(self):  # R9
        closed = frow(11, 1, status="closed", resolved_by="p",
                      history=[{"status": "open", "sha": SHA, "by": "a"}, {"status": "closed", "sha": SHA, "by": "a"}])
        rows = [rec(frow(10, 1)), rec(closed)]
        self.assertEqual(self.rep(rows, rounds=1)["X"], [2])

    def test_report_refusals(self):  # R7
        for rounds in (0, -1, 100, True, "3", None):
            with self.subTest(rounds=rounds), self.assertRaises(GateError):
                self.rep([], rounds=rounds)
        for narrowed in ([0], [4], [5], [True], ["2"], [2, 5]):
            with self.subTest(narrowed=narrowed), self.assertRaises(GateError):
                self.rep(series(1, 1, 1, 1), narrowed=narrowed)
        with self.assertRaises(GateError):
            self.rep([], rounds=1, narrowed=[1])
        self.assertEqual(self.rep(series(1, 1, 1, 1), narrowed=[3, 1, 3])["narrowed"], [1, 3])

    def test_escape_cost_deferred(self):  # R8, D7
        full = {"CRITICAL": 1, "HIGH": 1, "MEDIUM": 1, "LOW": 1}
        for value in (full, None, {}, "x"):
            cfg = dict(self.cfg, escape_cost=value)
            for fn in (report, small_signals):
                with self.subTest(fn=fn.__name__, value=value), self.assertRaises(GateError) as cm:
                    fn(series(1, 1), "p", "1x.1", 2, [], cfg)
                self.assertIn("escape_cost", str(cm.exception))
                self.assertIn("config/2", str(cm.exception))
        self.assertNotIn("escape_cost", self.cfg)
        self.assertIsNone(small_signals(series(8, 4, 2, 1), "p", "1x.1", 4, [], self.cfg)["ev_below_one"])

    def test_small_signals_p_exactly_alpha(self):  # S9 (review-1 F4): p == 1/10 at k = 10, one LOW in review 1
        rows = [rec(frow(0, 1, "LOW"))]
        self.assertEqual(self.rep(rows, rounds=10)["p"], Fraction(1, 10))
        self.assertEqual(small_signals(rows, "p", "1x.1", 10, [], self.cfg),
                         {"rule_n": False, "converging": True, "ev_below_one": None})

    def test_novelty(self):  # N1, N2, N3
        def dims(*rounds):
            rows, n = [], 0
            for rnd, ds in enumerate(rounds, start=1):
                for d in ds:
                    rows.append(rec(frow(n, rnd, dim=d)))
                    n += 1
            return rows
        r = self.rep(dims("ab", "cd"), rounds=2)
        self.assertEqual((r["nu"], r["rule_n"]), (Fraction(1), True))
        r = self.rep(dims("ab", "ac"), rounds=2)
        self.assertEqual((r["nu"], r["rule_n"]), (Fraction(1, 2), True))
        r = self.rep(dims("ab", "ab"), rounds=2)
        self.assertEqual((r["nu"], r["rule_n"]), (Fraction(0), False))
        r = self.rep(dims("ab", "a"), rounds=2)  # half new but X_k < X_(k-1) would need nu: here 0 new
        self.assertEqual((r["nu"], r["rule_n"]), (Fraction(0), False))
        r = self.rep(dims("abc", "ad"), rounds=2)  # one of two new, but X_2 < X_1
        self.assertEqual((r["nu"], r["rule_n"]), (Fraction(1, 2), False))
        # N2: "z" is first seen on an uncounted finding of round 1: still new in round 2
        rows = dims("a", "z") + [rec(frow(10, 1, caused=False, dim="z")), rec(frow(11, 1, "INFO", dim="y")),
                                 rec(frow(12, 2, dim="y"))]
        r = self.rep(rows, rounds=2)
        self.assertEqual((r["X"], r["nu"]), ([1, 2], Fraction(1)))
        # N3
        r = self.rep(dims("a", "ab", ""), rounds=3)
        self.assertEqual((r["X"], r["nu"], r["rule_n"]), ([1, 2, 0], None, False))

    def test_weighted_tally(self):  # S7
        for sev, w in (("CRITICAL", 8), ("HIGH", 4), ("MEDIUM", 2), ("LOW", 1)):
            with self.subTest(sev):
                r = self.rep([rec(frow(0, 1, sev))], rounds=1)
                self.assertEqual((r["X"], r["W"], r["N"], r["S"], r["p"]), ([1], [w], w, 0, 1))
        rows = [rec(frow(i, rnd, s)) for i, (rnd, s) in enumerate(
            [(1, "CRITICAL"), (1, "HIGH"), (1, "MEDIUM"), (1, "LOW"), (2, "LOW"), (3, "LOW"), (3, "LOW")])]
        r = self.rep(rows, rounds=3)
        self.assertEqual((r["X"], r["W"], r["N"], r["S"]), ([4, 1, 2], [15, 1, 2], 18, 5))
        self.assertEqual(r["p"], brute_p([15, 1, 2]))
        self.assertEqual(r["severities"], {"CRITICAL": 1, "HIGH": 1, "MEDIUM": 1, "LOW": 4})
        # the same X = (1, 1) with different severities gives different p (hand computed from Binomial(9, 1/2))
        early = self.rep([rec(frow(0, 1, "CRITICAL")), rec(frow(1, 2, "LOW"))], rounds=2)
        late = self.rep([rec(frow(0, 1, "LOW")), rec(frow(1, 2, "CRITICAL"))], rounds=2)
        self.assertEqual((early["X"], late["X"]), ([1, 1], [1, 1]))
        self.assertEqual((early["W"], late["W"]), ([8, 1], [1, 8]))
        self.assertEqual((early["p"], late["p"]), (Fraction(10, 512), Fraction(511, 512)))

    def test_low_run(self):  # S8: through report, rows built per scenario
        def run(rounds, spec, dims=None):
            rows = [rec(frow(i, rnd, s, dim=(dims[i] if dims else None))) for i, (rnd, s) in enumerate(spec)]
            return self.rep(rows, rounds=rounds)
        r = run(2, [(1, "LOW"), (2, "LOW")])
        self.assertEqual((r["verdict"], r["low_run"]), ("LOW_PLATEAU", 2))
        r = run(6, [(i, "LOW") for i in range(1, 7)])  # k = 6 and Rule N firing (every dimension new, X flat)
        self.assertEqual((r["verdict"], r["rule_n"], r["low_run"]), ("LOW_PLATEAU", True, 6))
        r = run(1, [(1, "LOW")])
        self.assertEqual((r["verdict"], r["low_run"]), ("CONTINUE", 1))
        r = run(2, [(1, "MEDIUM"), (1, "MEDIUM"), (2, "LOW")], dims=["a", "b", "a"])
        self.assertEqual((r["verdict"], r["low_run"]), ("CONTINUE", 1))
        r = run(3, [(3, "LOW")])  # two empty reviews, then LOW-only: L = 3
        self.assertEqual((r["verdict"], r["low_run"]), ("LOW_PLATEAU", 3))
        r = run(3, [(1, "LOW"), (2, "LOW")])  # empty review k after LOW-only reviews: CLEAN, whatever L
        self.assertEqual((r["verdict"], r["low_run"]), ("CLEAN", 3))
        r = run(3, [(1, "LOW"), (2, "LOW"), (3, "MEDIUM")])
        self.assertEqual((r["verdict"] != "LOW_PLATEAU", r["low_run"]), (True, 0))
        r = run(3, [(1, "MEDIUM"), (2, "LOW"), (3, "LOW")])  # LOW-only after a MEDIUM review: run of two
        self.assertEqual((r["verdict"], r["low_run"]), ("LOW_PLATEAU", 2))

    def test_small_signals(self):  # S11/E1
        r8421 = series(8, 4, 2, 1)
        r4535 = series(4, 5, 3, 5)
        a = small_signals(r8421, "p", "1x.1", 4, [], self.cfg)
        self.assertEqual(a, {"rule_n": False, "converging": True, "ev_below_one": None})
        b = small_signals(r4535, "p", "1x.1", 4, [], self.cfg)
        self.assertEqual(b, {"rule_n": True, "converging": False, "ev_below_one": None})
        self.assertIsNone(small_signals(series(4, 5), "p", "1x.1", 2, [], self.cfg)["converging"])
        self.assertIs(small_signals(series(4, 5, 3), "p", "1x.1", 3, [], self.cfg)["converging"], False)
        self.assertIs(small_signals(series(6, 3, 1), "p", "1x.1", 3, [], self.cfg)["converging"], True)
        with self.assertRaises(GateError):
            small_signals(r8421, "p", "1x.1", 4, [4], self.cfg)


class TestFormulas(unittest.TestCase):
    RESEARCH = {(4, 5, 3, 5): "0.585", (8, 4, 2, 1): "0.005", (4, 5, 3): "0.431", (6, 2, 0): "0.007",
                (3, 3, 3): "0.580", (6, 3, 1): "0.040", (4, 5): "0.746"}

    def test_trend_p_matches_research_and_brute_force(self):  # S3
        for counts, want in self.RESEARCH.items():
            with self.subTest(counts=counts):
                p = trend(list(counts))["p"]
                self.assertEqual(fmt3(p), want)
                self.assertEqual(p, brute_p(counts))
        # exact values (the research table's "117/200" and "1/200" are 3-place roundings, not these fractions)
        self.assertEqual(trend([4, 5])["p"], Fraction(191, 256))
        self.assertEqual(trend([6, 2, 0])["p"], Fraction(5, 729))
        self.assertEqual(trend([4, 5, 3])["p"], Fraction(228826, 531441))
        self.assertEqual(fmt3(trend([8, 10, 6, 10])["p"]), "0.591")  # the golden's W

    def test_trend_p_random_vectors(self):  # the sliding-window convolution against enumeration
        rng = random.Random(61)
        for _ in range(40):
            k = rng.randint(2, 5)
            counts = [rng.randint(0, 3) for _ in range(k)]
            while sum(counts) > 12 or (k ** sum(counts) > 300000):
                counts = [rng.randint(0, 2) for _ in range(k)]
            with self.subTest(counts=counts):
                self.assertEqual(trend(counts)["p"], brute_p(counts))

    def test_series_k(self):  # S1, S2
        t = trend([3])
        self.assertEqual((t["N"], t["S"], t["p"], t["u"]), (3, 0, 1, None))
        self.assertIsNone(geo_fit([3]))
        self.assertEqual(verdict([3], Fraction(1), 0, [6], 0), ("CONTINUE", "insufficient data"))
        t = trend([0, 0, 0])
        self.assertEqual((t["N"], t["S"], t["p"], t["u"]), (0, 0, 1, None))
        self.assertIsNone(geo_fit([0, 0, 0]))
        g = geo_fit([5, 0, 0])
        self.assertEqual((g["q"], g["R"], g["E_next"], g["boundary"]), (0, 0, 0, False))
        self.assertEqual(verdict([2, 1, 1, 1, 1], 0, 0, [4, 2, 2, 2, 2], 0), ("ESCALATE", "same dimensions recur"))
        self.assertEqual(verdict([1] * 6, 0, 0, [2] * 6, 0), ("ESCALATE", "fix rounds exhausted"))
        self.assertEqual(verdict([1] * 5 + [0], 0, 0, [2] * 5 + [0], 0)[0], "CLEAN")
        self.assertEqual(verdict([1, 2, 3, 4, 5, 6], 1, 0, [2, 4, 6, 8, 10, 12], 0),
                         ("ESCALATE", "fix rounds exhausted"))  # step 2 comes before Rule N

    def test_u_value(self):  # u by hand: (S - N(k-1)/2) / sqrt(N(k^2-1)/12)
        t = trend([8, 10, 6, 10])
        self.assertAlmostEqual(t["u"], 1 / (42.5 ** 0.5), places=12)
        self.assertEqual((t["N"], t["S"]), (34, 52))
        self.assertAlmostEqual(trend([8, 4, 2, 1])["u"], (11 - 15 * 1.5) / (15 * 15 / 12.0) ** 0.5, places=12)
        self.assertIsNone(trend([0, 0])["u"])

    @staticmethod
    def closed_fit(counts):
        """The k = 3 fit from the quadratic (2-r)q^2 + (1-r)q - r = 0, r = S/N (spec section 10), in floats:
        (q, a, R, E_next)."""
        n, s = sum(counts), counts[1] + 2 * counts[2]
        r = s / n
        q = (-(1 - r) + math.sqrt((1 - r) ** 2 + 4 * (2 - r) * r)) / (2 * (2 - r))
        a = n / (1 - q ** 3)
        return q, a, a * q ** 3, a * (1 - q) * q ** 3

    def test_geo_fit_non_boundary_values(self):  # S4 (review-1 F1)
        for counts in ([12, 6, 2], [4, 5, 3], [6, 2, 0]):
            q, a, big_r, e_next = self.closed_fit(counts)
            with self.subTest(counts=counts):
                g = geo_fit(counts)
                self.assertFalse(g["boundary"])
                for name, got, want in (("q", g["q"], q), ("a", g["a"], a), ("R", g["R"], big_r),
                                        ("E_next", g["E_next"], e_next)):
                    self.assertAlmostEqual(float(got), want, places=9, msg=name)
                    self.assertEqual(fmt3(got), "%.3f" % want, name)
        self.assertEqual(fmt3(geo_fit([12, 6, 2])["E_next"]), "1.009")  # the reviewer's value

    def test_geo_fit_stops_after_64_steps(self):  # S4 (review-1 F2): q has denominator 2**64 and brackets S/N
        for counts in ([12, 6, 2], [4, 5, 3], [6, 2, 0], [9, 5, 2, 1]):
            k, n, s = len(counts), sum(counts), sum(i * c for i, c in enumerate(counts))
            target = Fraction(s, n)
            q = geo_fit(counts)["q"]
            d = Fraction(1, 2 ** 64)

            def m(x):
                return sum(j * x ** j for j in range(k)) / sum(x ** j for j in range(k))
            with self.subTest(counts=counts):
                self.assertEqual(q.denominator, 2 ** 64)
                self.assertTrue(m(q - d) < target < m(q + d))

    def test_geo_fit_research_rows(self):  # S4
        g = geo_fit([8, 4, 2, 1])
        self.assertEqual((g["q"], g["E_next"], g["R"], g["boundary"]), (Fraction(1, 2), Fraction(1, 2), 1, False))
        self.assertEqual(fmt3(geo_fit([4, 5, 3])["q"]), "0.882")
        self.assertEqual(fmt3(geo_fit([6, 2, 0])["q"]), "0.220")
        g = geo_fit([4, 5, 3, 5])
        self.assertTrue(g["boundary"] and g["R"] is None)
        self.assertEqual((g["E_next"], g["q"]), (Fraction(17, 4), 1))
        self.assertEqual(geo_fit([5, 0, 0])["q"], 0)
        self.assertIsNone(geo_fit([5]))

    def test_boundary_iff_u_nonnegative(self):  # S5
        rng = random.Random(6)
        for _ in range(400):
            k = rng.randint(2, 6)
            counts = [rng.randint(0, 6) for _ in range(k)]
            if sum(counts) == 0:
                counts[0] = 1
            with self.subTest(counts=counts):
                self.assertEqual(geo_fit(counts)["boundary"], trend(counts)["u"] >= 0)

    def test_rule_n_conditions(self):  # Rule N's four conditions, one false at a time
        self.assertTrue(rule_n([3, 3], Fraction(1, 2)))
        self.assertFalse(rule_n([3], Fraction(1)))            # k >= 2
        self.assertFalse(rule_n([3, 0], None))                # X_k > 0
        self.assertFalse(rule_n([0, 0], Fraction(1)))         # X_k > 0 (X_k >= X_(k-1) holds here)
        self.assertFalse(rule_n([3, 3], Fraction(49, 100)))   # novelty >= 1/2
        self.assertFalse(rule_n([3, 2], Fraction(1)))         # X_k >= X_(k-1)

    def test_makefile_walkthrough(self):  # S10
        self.assertEqual(verdict([4, 5], 1, 0, [8, 10], 0)[0], "STOP_NARROW")
        self.assertEqual(verdict([4, 5, 3], 1, 1, [8, 10, 6], 0)[0], "ESCALATE")
        self.assertEqual(verdict([4, 5, 3, 5], 1, 1, [8, 10, 6, 10], 0)[0], "ESCALATE")

    def test_decision_table_rows(self):  # S6, S9, W1: every branch of the ladder
        F = Fraction
        rows = [
            # step 1
            (([3, 0], 0, 0, [6, 0], 1), ("CLEAN", "no counted finding in the last review")),
            (([1, 0], 0, 0, [1, 0], 2), ("CLEAN", "no counted finding in the last review")),
            (([3, 2, 0], 0, 0, [6, 4, 0], 0), ("CLEAN", "no counted finding in the last review")),
            (([2, 1, 1], 0, 0, [4, 1, 1], 2), ("LOW_PLATEAU", "only LOW findings in the last 2 reviews")),
            (([1] * 6, 1, 1, [1] * 6, 6), ("LOW_PLATEAU", "only LOW findings in the last 2 reviews")),
            (([4, 5], 1, 0, [1, 1], 2), ("LOW_PLATEAU", "only LOW findings in the last 2 reviews")),  # beats Rule N
            (([2, 1], 0, 0, [4, 1], 1), ("CONTINUE", "insufficient data")),
            (([2, 0, 0, 1], 0, 0, [4, 0, 0, 1], 3), ("LOW_PLATEAU", "only LOW findings in the last 2 reviews")),
            # step 2
            (([1] * 6, 0, 0, [2] * 6, 0), ("ESCALATE", "fix rounds exhausted")),
            # step 3
            (([4, 5], 1, 0, [8, 10], 0), ("STOP_NARROW", "Rule N fired: new dimensions keep arriving")),
            (([4, 5], 1, 1, [8, 10], 0), ("ESCALATE", "Rule N fired after a narrowing")),
            (([4, 5], 1, 2, [8, 10], 0), ("ESCALATE", "Rule N fired after a narrowing")),
            (([3, 3, 3], F(1, 2), 0, [6, 6, 6], 0), ("STOP_NARROW", "Rule N fired: new dimensions keep arriving")),
            # step 4
            (([4, 2], 0, 0, [8, 4], 0), ("CONTINUE", "insufficient data")),
            # step 5
            (([8, 4, 2, 1], F(1, 4), 0, [16, 8, 4, 2], 0), ("CONTINUE", "converging")),
            # step 6
            (([3, 3, 3], F(1, 4), 0, [6, 6, 6], 0), ("ESCALATE", "same dimensions recur")),
            (([5, 4, 3], F(1, 2), 0, [10, 8, 6], 0), ("STOP_NARROW", "not converging; new dimensions")),
            (([5, 4, 3], F(1, 2), 1, [10, 8, 6], 0), ("ESCALATE", "not converging after a narrowing")),
            (([5, 4, 3], F(1, 4), 0, [10, 8, 6], 0), ("ESCALATE", "same dimensions recur")),
            (([4, 5, 3, 5], F(1, 4), 0, [8, 10, 6, 10], 0), ("ESCALATE", "same dimensions recur")),  # boundary fit
            # rising and flat shapes
            (([1, 2, 4], 0, 0, [2, 4, 8], 0), ("ESCALATE", "same dimensions recur")),
        ]
        for args, want in rows:
            with self.subTest(args=args):
                self.assertEqual(verdict(*args), want)

    def test_ev_verdict(self):  # S11
        cost1 = {"CRITICAL": 1, "HIGH": 1, "MEDIUM": 1, "LOW": 1}
        r = ev([16, 8, 4, 2], {"MEDIUM": 15}, cost1)
        self.assertEqual((r["value"], r["verdict"]), (Fraction(1, 2), "stop"))
        r = ev([8, 10, 6, 10], {"MEDIUM": 17}, cost1)  # boundary fit: E_next = N/k = 34/4; value 17/4
        self.assertEqual((r["value"], r["verdict"]), (Fraction(17, 4), "continue"))
        self.assertIsNone(ev([8, 10], {"MEDIUM": 9}, None))
        self.assertIsNone(ev([8], {"MEDIUM": 4}, cost1))        # no fit (k < 2)
        self.assertIsNone(ev([0, 0], {}, cost1))                # no fit (N = 0)
        zero = {k: 0 for k in cost1}
        r = ev([8, 10, 6, 10], {"MEDIUM": 17}, zero)
        self.assertEqual((r["value"], r["verdict"]), (0, "stop"))
        mixed = {"CRITICAL": 4, "HIGH": 1, "MEDIUM": 0, "LOW": 2}   # boundary fit: E_next = 34/4
        r = ev([8, 10, 6, 10], {"CRITICAL": 2, "LOW": 3}, mixed)    # N = 34: 17/2 * (2*4 + 3*2)/34
        self.assertEqual(r["value"], Fraction(17, 2) * Fraction(14, 34))
        self.assertEqual(ev([8, 10, 6, 10], {"MEDIUM": 17}, {k: 2 for k in cost1})["value"], Fraction(17, 2))
        self.assertEqual(ev([8, 10, 6, 10], {"MEDIUM": 17}, {k: Fraction(4, 17) for k in cost1})["verdict"], "stop")


if __name__ == "__main__":
    unittest.main()
