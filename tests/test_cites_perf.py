"""F-V1: every scan of the cite library and gate is linear (or n log n) in what it scans (task C2V1 rows P1a-P4, P6).

Each test runs the production call (cites.extract, cites.anchors, cites.problem or gate_cites.main) in a child process
of the interpreter under test, `python -m tests.test_cites_perf CASE`. Every check counts CPU time or work, never wall
time, so other load on the machine does not change the outcome (F-R1):
- time: one call at size n uses under BOUND CPU seconds (time.process_time). The fixed code takes at most BOUND / 10;
  21ad52d's P1a, P1b, P1d "(", P2 and P4 scans run past CPU_CAP, where RLIMIT_CPU kills the child (SIGXCPU).
- work: one call at size n // WORK_DIV, run under sys.settrace and sys.setprofile, executes at most LINES_PER_CHAR
  Python lines and passes at most SCAN_PER_CHAR characters of str receivers to C str methods (len(s) for each call
  s.m(...)), per character of input. Both counts are deterministic. The fixed code stays under 21 lines and 5
  characters; 21ad52d's P1c angle scan (str.find from every "<": quadratic inside C, which the time check cannot
  separate at a usable size) passes about n characters per character, its P3 span scan (O(n^1.5)) runs about 77 lines
  per character at the work size.
TIMEOUT is a wall-clock backstop for a child that hangs; the CPU cap ends a slow child long before it."""
import json
import math
import os
import signal
import subprocess
import sys
import time
import unittest

from tests.helpers import GitIsolatedTestCase, git, make_repo, write_record

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOUND = 3.0          # CPU seconds for one production call at size n
CPU_CAP = 15         # CPU seconds for the whole child (RLIMIT_CPU): 5 * BOUND
TIMEOUT = 120        # wall seconds for the whole child: a backstop only
WORK_DIV = 16        # the work counts run at size n // WORK_DIV
LINES_PER_CHAR = 32  # Python line events per input character
SCAN_PER_CHAR = 16   # str-method receiver characters per input character


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


def _work(f):
    """(Python line events, characters of the str receivers of C method calls) during f()."""
    count = [0, 0]

    def local(frame, event, arg):
        if event == "line":
            count[0] += 1
        return local

    def call(frame, event, arg):
        return local

    def profile(frame, event, arg):
        if event == "c_call" and isinstance(getattr(arg, "__self__", None), str):
            count[1] += len(arg.__self__)

    sys.settrace(call)
    sys.setprofile(profile)
    try:
        f()
    finally:
        sys.settrace(None)
        sys.setprofile(None)
    return count


def _cap_cpu():
    try:
        import resource
    except ImportError:                          # no RLIMIT_CPU (Windows): TIMEOUT is the only limit
        return
    hard = resource.getrlimit(resource.RLIMIT_CPU)[1]
    resource.setrlimit(resource.RLIMIT_CPU, (CPU_CAP, hard))


def _child(argv):
    _cap_cpu()
    if argv[0] == "gate":                        # gate ROOT: one gate_cites.main run, CPU-timed
        import contextlib
        import io
        from gates import gate_cites
        buf = io.StringIO()
        t = time.process_time()
        with contextlib.redirect_stdout(buf):
            code = gate_cites.main(["--root", argv[1]])
        print(json.dumps({"seconds": time.process_time() - t, "code": code, "out": buf.getvalue()}))
        return
    case, n = argv[0], int(argv[1])
    f, size = _lib_case(case, n)
    t = time.process_time()
    out = f()
    t = time.process_time() - t
    fw, wsize = _lib_case(case, n // WORK_DIV)
    lines, scan = _work(fw)
    print(json.dumps({"size": size, "cpu": t, "out": repr(out)[:200], "items": len(out),
                      "wsize": wsize, "lines": lines, "scan": scan}))


def _run(test, args):
    try:
        p = subprocess.run([sys.executable, "-m", "tests.test_cites_perf"] + list(args), cwd=ROOT, timeout=TIMEOUT,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
    except subprocess.TimeoutExpired:
        test.fail("%s: still running after %d wall s" % (" ".join(args), TIMEOUT))
    xcpu = -getattr(signal, "SIGXCPU", 0)
    test.assertEqual(p.returncode, 0, "%s: exit %d%s\n%s" % (
        " ".join(args), p.returncode, " (SIGXCPU: over %d CPU s, super-linear scan)" % CPU_CAP
        if xcpu and p.returncode == xcpu else "", p.stderr.decode("utf-8", "replace")[-2000:]))
    return json.loads(p.stdout.decode("utf-8"))


NONE = ("[]", 0)                        # the first 12 characters of the repr of the larger result, and its length


class LinearScanTest(unittest.TestCase):
    """Rows P1a-P1d (extract), P2 (anchors), P3 (code spans), P4 (problem): one test per row."""

    def check(self, cases):
        for case, n, expected in cases:
            with self.subTest(case=case):
                r = _run(self, [case, str(n)])
                self.assertLess(r["cpu"], BOUND, "%s: %.3f CPU s at %d" % (case, r["cpu"], r["size"]))
                self.assertLessEqual(r["lines"], LINES_PER_CHAR * r["wsize"],
                                     "%s: %d line events at %d" % (case, r["lines"], r["wsize"]))
                self.assertLessEqual(r["scan"], SCAN_PER_CHAR * r["wsize"],
                                     "%s: %d str characters scanned at %d" % (case, r["scan"], r["wsize"]))
                self.assertEqual((r["out"][:12], r["items"]), expected)

    def test_p1a_opener_search(self):
        self.check([("p1a_close_only", 50000, NONE), ("p1a_unbalanced", 33334, NONE), ("p1a_link", 33334, NONE),
                    ("p1a_deep", 25000, NONE)])

    def test_p1b_bare_destination(self):
        self.check([("p1b_open", 25000, NONE), ("p1b_tail", 33334, NONE), ("p1b_gap", 33334, NONE),
                    ("p1b_no_hash", 25000, NONE)])

    def test_p1c_angle_destination(self):
        # 21ad52d's angle scan is quadratic in C (find, slice): its CPU time is only about 10x the fixed code's at
        # 1.6 M characters, so the str scan count, not the time check, is what fails it
        self.check([("p1c_angle", 50000, NONE), ("p1c_angle_far", 50000, NONE)])

    def test_p1d_title(self):
        # Only the "(" title was quadratic at 21ad52d; a quote title stops at the next quote of its kind, and each
        # later quote title opens with one, so those two cases are regression guards that 21ad52d also passes.
        self.check([("p1d_paren", 16667, NONE), ("p1d_double", 16667, NONE), ("p1d_single", 16667, NONE)])

    def test_p2_closing_sequence(self):
        one = ("['a---------", 1)
        self.check([("p2_spaces", 100000, one), ("p2_tabs", 50000, one), ("p2_hash", 100000, one)])

    def test_p3_code_spans(self):
        self.check([("p3_spans", 50000, NONE)])

    def test_p4_problem_once_per_target(self):
        self.check([("p4_anchor", 8000, ("['', '', '',", 4000)), ("p4_line", 40000, ("['', '', '',", 4000))])

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
