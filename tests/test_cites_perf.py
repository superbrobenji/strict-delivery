"""F-V1: every scan of the cite library and gate is linear (or n log n) in what it scans (task C2V1 rows P1a-P4, P6).

Each test runs the production call (cites.extract, cites.anchors, cites.problem or gate_cites.main) in a child process
of the interpreter under test, `python -m tests.test_cites_perf CASE`, with a timeout, so a quadratic scan fails
within TIMEOUT instead of running for minutes. Two checks per case: the call at the larger size stays under BOUND
seconds (21ad52d's code does not finish the smaller size within TIMEOUT, the fixed code takes at most BOUND / 10),
and the ratio of the best of three runs at 2n over the best at n stays under RATIO (a quadratic scan gives about 4).
Code spans (P3) can only be O(n^1.5) (the unmatched runs that each rescan the line have distinct lengths), so that
case steps the size by 4 and allows RATIO * 2 (linear gives 4, the old scan 8)."""
import json
import math
import os
import subprocess
import sys
import time
import unittest

from tests.helpers import GitIsolatedTestCase, git, make_repo, write_record

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOUND = 4.0          # seconds for one production call at the larger size
RATIO = 2.6
STEP = {"p3_spans": 4}
TIMEOUT = 20         # seconds for the whole child: startup, three runs at n and three at 2n


def _anchor_target(n):
    return "".join("# h%d\n" % i for i in range(n))


def _lib_case(case, n):
    """(callable, size label) for the library cases: the input of size n built outside the timed call."""
    from gates.lib import cites
    if case == "p1a_close_only":
        s = "](" * n
    elif case == "p1a_link":
        s = "[](" * n
    elif case == "p1a_deep":
        s = "[" + "](((" * n
    elif case == "p1a_unbalanced":
        s = "]" * n + "](" * n
    elif case == "p1b_open":
        s = "[]((" * n
    elif case == "p1b_tail":
        s = "[](" * n + "(" * n
    elif case == "p1c_angle":
        s = "[](<" * n
    elif case == "p1c_angle_far":                # every angle destination runs to the one ">" at the end
        s = "[](<" * n + ">"
    elif case == "p1d_paren":
        s = "[](x (" * n
    elif case == "p1d_double":
        s = "[](x \"" * n
    elif case == "p1d_single":
        s = "[](x '" * n
    elif case == "p1b_gap":
        s = "[](" * n + " " * n + "x"
    elif case == "p1b_no_hash":                  # n destinations that parse, each about 2n long, none a cite
        s = "[](a" * n + ")" * n
    elif case == "p3_spans":
        k = math.isqrt(4 * n)                    # k unmatched runs of distinct lengths 2..k+1 (about 2n characters)
        s = "x".join("`" * (2 + i) for i in range(k)) + "x" + "`a`x" * n
    elif case in ("p2_spaces", "p2_tabs", "p2_hash"):
        mid = {"p2_spaces": " " * n + "x", "p2_tabs": "\t " * n + "x", "p2_hash": " " * n + "#x"}[case]
        s = "# a" + mid + "\n"
        return (lambda: sorted(cites.anchors(s))), len(s)
    elif case == "p4_anchor":
        target = _anchor_target(n)
        cs = [cites.Cite("d.md", 1, "t.md#h%d" % i, "t.md", None, None, "h%d" % i) for i in range(n // 2)]
        tracked = frozenset({"t.md"})
        read = {"t.md": target}.get
        return (lambda: [cites.problem(c, tracked, read) for c in cs]), len(target) + len(cs)
    elif case == "p4_line":
        target = "x\n" * (n * 100)
        cs = [cites.Cite("d.md", 1, "`t.py:%d`" % (i + 1), "t.py", i + 1, None, None) for i in range(n // 10)]
        tracked = frozenset({"t.py"})
        read = {"t.py": target}.get
        return (lambda: [cites.problem(c, tracked, read) for c in cs]), len(target) + len(cs)
    else:
        raise SystemExit("unknown case %s" % case)
    return (lambda: cites.extract("d.md", s + "\n")), len(s)


def _best(f, runs=3):
    best = None
    out = None
    for _ in range(runs):
        t = time.perf_counter()
        out = f()
        t = time.perf_counter() - t
        best = t if best is None else min(best, t)
    return best, out


def _child(argv):
    if argv[0] == "gate":                        # gate ROOT: one gate_cites.main run, timed
        import contextlib
        import io
        from gates import gate_cites
        buf = io.StringIO()
        t = time.perf_counter()
        with contextlib.redirect_stdout(buf):
            code = gate_cites.main(["--root", argv[1]])
        print(json.dumps({"seconds": time.perf_counter() - t, "code": code, "out": buf.getvalue()}))
        return
    case, n = argv[0], int(argv[1])
    f1, size1 = _lib_case(case, n)
    t1, out1 = _best(f1)
    f2, size2 = _lib_case(case, STEP.get(case, 2) * n)
    t2, out2 = _best(f2)
    print(json.dumps({"n": [size1, t1], "2n": [size2, t2], "out": repr(out2)[:200], "items": len(out2)}))


def _run(test, args):
    try:
        p = subprocess.run([sys.executable, "-m", "tests.test_cites_perf"] + list(args), cwd=ROOT, timeout=TIMEOUT,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
    except subprocess.TimeoutExpired:
        test.fail("%s: still running after %d s (super-linear scan)" % (" ".join(args), TIMEOUT))
    test.assertEqual(p.returncode, 0, p.stderr.decode("utf-8", "replace")[-2000:])
    return json.loads(p.stdout.decode("utf-8"))


NONE = ("[]", 0)                        # the first 12 characters of the repr of the larger result, and its length


class LinearScanTest(unittest.TestCase):
    """Rows P1a-P1d (extract), P2 (anchors), P3 (code spans), P4 (problem): one test per row."""

    def check(self, cases):
        for case, n, expected in cases:
            with self.subTest(case=case):
                r = _run(self, [case, str(n)])
                (s1, t1), (s2, t2) = r["n"], r["2n"]
                self.assertLess(t2, BOUND, "%s: %.3f s at %d" % (case, t2, s2))
                limit = RATIO * 2 if case in STEP else RATIO
                self.assertLess(t2 / max(t1, 1e-9), limit, "%s: %.4f s at %d, %.4f s at %d" % (case, t1, s1, t2, s2))
                self.assertEqual((r["out"][:12], r["items"]), expected)

    def test_p1a_opener_search(self):
        self.check([("p1a_close_only", 50000, NONE), ("p1a_unbalanced", 33334, NONE), ("p1a_link", 33334, NONE),
                    ("p1a_deep", 25000, NONE)])

    def test_p1b_bare_destination(self):
        self.check([("p1b_open", 25000, NONE), ("p1b_tail", 33334, NONE), ("p1b_gap", 33334, NONE),
                    ("p1b_no_hash", 25000, NONE)])

    def test_p1c_angle_destination(self):
        # 21ad52d's angle scan is quadratic in C (find, slice): at these sizes its ratio is 3.3-3.6, not over BOUND
        self.check([("p1c_angle", 100000, NONE), ("p1c_angle_far", 100000, NONE)])

    def test_p1d_title(self):
        # Only the "(" title was quadratic at 21ad52d; a quote title stops at the next quote of its kind, and each
        # later quote title opens with one, so those two cases are regression guards that 21ad52d also passes.
        self.check([("p1d_paren", 16667, NONE), ("p1d_double", 16667, NONE), ("p1d_single", 16667, NONE)])

    def test_p2_closing_sequence(self):
        one = ("['a---------", 1)
        self.check([("p2_spaces", 100000, one), ("p2_tabs", 50000, one), ("p2_hash", 100000, one)])

    def test_p3_code_spans(self):
        self.check([("p3_spans", 25000, NONE)])

    def test_p4_problem_once_per_target(self):
        self.check([("p4_anchor", 4000, ("['', '', '',", 4000)), ("p4_line", 20000, ("['', '', '',", 4000))])

class GateLinearScanTest(GitIsolatedTestCase):
    """Row P1 through gate_cites.main on a real repository (24 KB and 100 KB lines), and row P4's landed_in and anchor
    cites through the gate."""

    PASS4 = "".join("PASS cites.%s\n" % c for c in ("doc", "line", "anchor", "landed"))

    def gate(self, root):
        git(root, "add", "-A")
        r = _run(self, ["gate", root])
        self.assertLess(r["seconds"], BOUND, "%.3f s" % r["seconds"])
        return r["code"], r["out"]

    def put(self, root, rel, text):
        path = os.path.join(root, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)

    def test_long_link_lines(self):  # P1: 21ad52d takes 21 s at 24 KB on 3.9
        for name, line in (("24k", "[](" * 8000), ("100k", "[](" * 33334), ("close-100k", "](" * 50000),
                           ("deep-100k", "[" + "](((" * 25000)):
            with self.subTest(name=name):
                root = os.path.join(self.work, name)
                os.mkdir(root)
                make_repo(root)
                self.put(root, "big.md", line + "\n")
                self.assertEqual(self.gate(root), (0, self.PASS4))

    def test_many_cites_to_one_target(self):  # P4 through the gate: anchor cites and landed_in entries
        root = make_repo(self.work)
        self.put(root, "t.md", _anchor_target(4000))
        self.put(root, "d.md", "".join("[x](t.md#h%d)\n" % i for i in range(2000)))
        entries = ["t.md#h%d" % i for i in range(2000)]
        write_record(root, ".strict-delivery/state/decisions/DEC-20261031-k3f9.yml",
                     {"schema": "decision/1", "id": "DEC-20261031-k3f9", "status": "answered", "landed_in": entries})
        self.assertEqual(self.gate(root), (0, self.PASS4))


if __name__ == "__main__":
    _child(sys.argv[1:])
