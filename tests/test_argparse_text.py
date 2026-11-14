"""Task F1: argparse error text built from argv is the same on every interpreter (spec section 14).

Every expected value below is written by hand from the rules E1-E5 of the task's input-domain table
(.superpowers/sdd/2026-10-31-strict-delivery-framework/task-F1-domain.md), in the form /usr/bin/python3 (3.9.6,
Unicode 13.0.0) prints. The usage blocks (USAGE_40/80/200) are literals copied from a 3.9.6 run of the unmodified
parsers (measured 2026-11-10) and checked against E4; no expected value is computed by the code under test or read
from the other interpreter. The command-line rows run ``sys.executable -m gates`` in a subprocess with bytes argv and
compare stdout and stderr as bytes."""
import argparse
import ast
import builtins
import contextlib
import hashlib
import io
import os
import subprocess
import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest import mock

from gates.lib import result
from gates.lib.result import GateError, _GateParser

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# --- usage blocks: 3.9.6's wrapping (E4), measured on /usr/bin/python3 3.9.6 -------------------------------------
USAGE_40 = {
    'check schema': 'usage: schema [-h] [--root ROOT]\n',
    'check cites': 'usage: cites [-h] [--root ROOT]\n',
    'check claims': 'usage: claims [-h] [--root ROOT]\n              [--base BASE]\n',
    'check decisions': 'usage: decisions [-h] [--root ROOT]\n                 [--base BASE]\n',
    'check register': 'usage: register [-h] [--root ROOT]\n                [--base BASE]\n',
    'index': 'usage: index [-h] [--root ROOT]\n',
    'decisions ask': 'usage: decisions ask [-h]\n                     [--root ROOT]\n                     --class CLS\n                     --question\n                     QUESTION --option\n                     OPTION\n                     [--topic TOPIC]\n                     [--applies-to APPLIES_TO]\n                     --effect EFFECT\n                     [--supersedes SUPERSEDES]\n                     --by BY\n                     [--plan PLAN]\n                     [--program PROGRAM]\n                     [--stream STREAM]\n',
    'decisions decide': 'usage: decisions decide [-h]\n                        [--root ROOT]\n                        --answer\n                        ANSWER\n                        [--rule RULE]\n                        [--landed-in LANDED_IN]\n                        ID\n',
    'decisions withdraw': 'usage: decisions withdraw [-h]\n                          [--root ROOT]\n                          --reason\n                          REASON\n                          ID\n',
    'decisions batch': 'usage: decisions batch [-h]\n                       [--root ROOT]\n                       [--since SINCE]\n                       [--answered]\n                       [--source SOURCE]\n                       [--date DATE]\n',
    'decisions find': 'usage: decisions find [-h]\n                      [--root ROOT]\n                      [--path PATH]\n                      [--topic TOPIC]\n                      [--all]\n                      [TERM ...]\n',
    'findings': 'usage: findings [-h] {new,move} ...\n',
    'findings new': 'usage: findings new [-h] --source\n                    SOURCE --severity\n                    SEVERITY\n                    --owner-kind\n                    OWNER_KIND --by BY\n                    --class CLASS_\n                    [--plan PLAN]\n                    [--task TASK]\n                    [--number NUMBER]\n                    [--parent PARENT]\n                    [--root ROOT]\n                    [--cite CITE]\n',
    'findings move': 'usage: findings move [-h] --to TO --by\n                     BY\n                     [--ruling RULING]\n                     [--pin-test PIN_TEST]\n                     [--pin-transcript PIN_TRANSCRIPT]\n                     [--resolved-by RESOLVED_BY]\n                     [--root ROOT]\n                     [--evidence EVIDENCE]\n                     id\n',
}
USAGE_80 = {
    'check schema': 'usage: schema [-h] [--root ROOT]\n',
    'check cites': 'usage: cites [-h] [--root ROOT]\n',
    'check claims': 'usage: claims [-h] [--root ROOT] [--base BASE]\n',
    'check decisions': 'usage: decisions [-h] [--root ROOT] [--base BASE]\n',
    'check register': 'usage: register [-h] [--root ROOT] [--base BASE]\n',
    'index': 'usage: index [-h] [--root ROOT]\n',
    'decisions ask': 'usage: decisions ask [-h] [--root ROOT] --class CLS --question QUESTION\n                     --option OPTION [--topic TOPIC] [--applies-to APPLIES_TO]\n                     --effect EFFECT [--supersedes SUPERSEDES] --by BY\n                     [--plan PLAN] [--program PROGRAM] [--stream STREAM]\n',
    'decisions decide': 'usage: decisions decide [-h] [--root ROOT] --answer ANSWER [--rule RULE]\n                        [--landed-in LANDED_IN]\n                        ID\n',
    'decisions withdraw': 'usage: decisions withdraw [-h] [--root ROOT] --reason REASON ID\n',
    'decisions batch': 'usage: decisions batch [-h] [--root ROOT] [--since SINCE] [--answered]\n                       [--source SOURCE] [--date DATE]\n',
    'decisions find': 'usage: decisions find [-h] [--root ROOT] [--path PATH] [--topic TOPIC] [--all]\n                      [TERM ...]\n',
    'findings': 'usage: findings [-h] {new,move} ...\n',
    'findings new': 'usage: findings new [-h] --source SOURCE --severity SEVERITY --owner-kind\n                    OWNER_KIND --by BY --class CLASS_ [--plan PLAN]\n                    [--task TASK] [--number NUMBER] [--parent PARENT]\n                    [--root ROOT] [--cite CITE]\n',
    'findings move': 'usage: findings move [-h] --to TO --by BY [--ruling RULING]\n                     [--pin-test PIN_TEST] [--pin-transcript PIN_TRANSCRIPT]\n                     [--resolved-by RESOLVED_BY] [--root ROOT]\n                     [--evidence EVIDENCE]\n                     id\n',
}
USAGE_200 = {
    'check schema': 'usage: schema [-h] [--root ROOT]\n',
    'check cites': 'usage: cites [-h] [--root ROOT]\n',
    'check claims': 'usage: claims [-h] [--root ROOT] [--base BASE]\n',
    'check decisions': 'usage: decisions [-h] [--root ROOT] [--base BASE]\n',
    'check register': 'usage: register [-h] [--root ROOT] [--base BASE]\n',
    'index': 'usage: index [-h] [--root ROOT]\n',
    'decisions ask': 'usage: decisions ask [-h] [--root ROOT] --class CLS --question QUESTION --option OPTION [--topic TOPIC] [--applies-to APPLIES_TO] --effect EFFECT [--supersedes SUPERSEDES] --by BY [--plan PLAN]\n                     [--program PROGRAM] [--stream STREAM]\n',
    'decisions decide': 'usage: decisions decide [-h] [--root ROOT] --answer ANSWER [--rule RULE] [--landed-in LANDED_IN] ID\n',
    'decisions withdraw': 'usage: decisions withdraw [-h] [--root ROOT] --reason REASON ID\n',
    'decisions batch': 'usage: decisions batch [-h] [--root ROOT] [--since SINCE] [--answered] [--source SOURCE] [--date DATE]\n',
    'decisions find': 'usage: decisions find [-h] [--root ROOT] [--path PATH] [--topic TOPIC] [--all] [TERM ...]\n',
    'findings': 'usage: findings [-h] {new,move} ...\n',
    'findings new': 'usage: findings new [-h] --source SOURCE --severity SEVERITY --owner-kind OWNER_KIND --by BY --class CLASS_ [--plan PLAN] [--task TASK] [--number NUMBER] [--parent PARENT] [--root ROOT]\n                    [--cite CITE]\n',
    'findings move': 'usage: findings move [-h] --to TO --by BY [--ruling RULING] [--pin-test PIN_TEST] [--pin-transcript PIN_TRANSCRIPT] [--resolved-by RESOLVED_BY] [--root ROOT] [--evidence EVIDENCE] id\n',
}
USAGE_20 = {
    'check schema': 'usage: schema [-h]\n              [--root ROOT]\n',
    'check cites': 'usage: cites [-h]\n             [--root ROOT]\n',
    'check claims': 'usage: claims [-h]\n              [--root ROOT]\n              [--base BASE]\n',
    'check decisions': 'usage: decisions\n       [-h]\n       [--root ROOT]\n       [--base BASE]\n',
    'check register': 'usage: register\n       [-h]\n       [--root ROOT]\n       [--base BASE]\n',
    'index': 'usage: index [-h]\n             [--root ROOT]\n',
    'decisions ask': 'usage: decisions ask\n       [-h]\n       [--root ROOT]\n       --class CLS\n       --question\n       QUESTION\n       --option\n       OPTION\n       [--topic TOPIC]\n       [--applies-to APPLIES_TO]\n       --effect\n       EFFECT\n       [--supersedes SUPERSEDES]\n       --by BY\n       [--plan PLAN]\n       [--program PROGRAM]\n       [--stream STREAM]\n',
    'decisions decide': 'usage: decisions decide\n       [-h]\n       [--root ROOT]\n       --answer\n       ANSWER\n       [--rule RULE]\n       [--landed-in LANDED_IN]\n       ID\n',
    'decisions withdraw': 'usage: decisions withdraw\n       [-h]\n       [--root ROOT]\n       --reason\n       REASON\n       ID\n',
    'decisions batch': 'usage: decisions batch\n       [-h]\n       [--root ROOT]\n       [--since SINCE]\n       [--answered]\n       [--source SOURCE]\n       [--date DATE]\n',
    'decisions find': 'usage: decisions find\n       [-h]\n       [--root ROOT]\n       [--path PATH]\n       [--topic TOPIC]\n       [--all]\n       [TERM ...]\n',
    'findings': 'usage: findings\n       [-h]\n       {new,move}\n       ...\n',
    'findings new': 'usage: findings new\n       [-h]\n       --source\n       SOURCE\n       --severity\n       SEVERITY\n       --owner-kind\n       OWNER_KIND\n       --by BY\n       --class\n       CLASS_\n       [--plan PLAN]\n       [--task TASK]\n       [--number NUMBER]\n       [--parent PARENT]\n       [--root ROOT]\n       [--cite CITE]\n',
    'findings move': 'usage: findings move\n       [-h] --to\n       TO --by BY\n       [--ruling RULING]\n       [--pin-test PIN_TEST]\n       [--pin-transcript PIN_TRANSCRIPT]\n       [--resolved-by RESOLVED_BY]\n       [--root ROOT]\n       [--evidence EVIDENCE]\n       id\n',
}
# Widths at which a boundary of 3.9.6's wrapping decides (found by sweeping COLUMNS 8..130 over the 14 parsers;
# literals from the unmodified parsers on 3.9.6).
EDGE_USAGE = {
    (37, 'findings'): 'usage: findings [-h] {new,move} ...\n',
    (65, 'decisions withdraw'): 'usage: decisions withdraw [-h] [--root ROOT] --reason REASON ID\n',
    (91, 'decisions find'): 'usage: decisions find [-h] [--root ROOT] [--path PATH] [--topic TOPIC] [--all] [TERM ...]\n',
    (101, 'decisions decide'): 'usage: decisions decide [-h] [--root ROOT] --answer ANSWER [--rule RULE] [--landed-in LANDED_IN] ID\n',
    (18, 'index'): 'usage: index\n             [-h]\n             [--root ROOT]\n',
    (18, 'check cites'): 'usage: cites\n             [-h]\n             [--root ROOT]\n',
    (22, 'findings'): 'usage: findings [-h]\n                {new,move}\n                ...\n',
    (30, 'decisions find'): 'usage: decisions find [-h]\n                      [--root ROOT]\n                      [--path PATH]\n                      [--topic TOPIC]\n                      [--all]\n                      [TERM ...]\n',
    (18, 'findings move'): 'usage: findings move\n       [-h] --to\n       TO --by\n       BY\n       [--ruling RULING]\n       [--pin-test PIN_TEST]\n       [--pin-transcript PIN_TRANSCRIPT]\n       [--resolved-by RESOLVED_BY]\n       [--root ROOT]\n       [--evidence EVIDENCE]\n       id\n',
    (22, 'findings new'): 'usage: findings new\n       [-h] --source\n       SOURCE\n       --severity\n       SEVERITY\n       --owner-kind\n       OWNER_KIND\n       --by BY\n       --class\n       CLASS_\n       [--plan PLAN]\n       [--task TASK]\n       [--number NUMBER]\n       [--parent PARENT]\n       [--root ROOT]\n       [--cite CITE]\n',
    (27, 'decisions ask'): 'usage: decisions ask\n       [-h] [--root ROOT]\n       --class CLS\n       --question\n       QUESTION --option\n       OPTION\n       [--topic TOPIC]\n       [--applies-to APPLIES_TO]\n       --effect EFFECT\n       [--supersedes SUPERSEDES]\n       --by BY\n       [--plan PLAN]\n       [--program PROGRAM]\n       [--stream STREAM]\n',
    (27, 'decisions withdraw'): 'usage: decisions withdraw\n       [-h] [--root ROOT]\n       --reason REASON\n       ID\n',
    (34, 'check schema'): 'usage: schema [-h] [--root ROOT]\n',
}
USAGE = {"20": USAGE_20, "40": USAGE_40, "80": USAGE_80, "200": USAGE_200}


class Txt:
    """One argv text with the hand-written forms E1/E2 give: ``raw`` is what a raw message prints on stderr (a lone
    surrogate leaves the backslashreplace stream as six ASCII characters), ``rawf`` the same through safe_text in the
    FAIL line, ``r`` and ``rx`` the E1 repr of the text and of ``"x" + text`` on stderr (``rf``, ``rxf``: in the FAIL
    line, where each backslash is doubled and nothing else changes)."""

    def __init__(self, name, arg, raw, rawf, r, rx):
        self.name, self.arg, self.raw, self.rawf, self.r, self.rx = name, arg, raw, rawf, r, rx
        self.rf = r.replace("\\", "\\\\")
        self.rxf = rx.replace("\\", "\\\\")

    def argv(self):
        return self.arg.encode("utf-8", "surrogateescape")


TEXTS = [
    Txt("ascii", "a", "a", "a", "'a'", "'xa'"),
    Txt("e-acute", "é", "é", "é", "'é'", "'xé'"),
    Txt("u2c2f", "Ⱟ", "Ⱟ", "\\u2c2f", "'\\u2c2f'", "'x\\u2c2f'"),
    Txt("u0c5d", "ౝ", "ౝ", "\\u0c5d", "'\\u0c5d'", "'x\\u0c5d'"),
    Txt("u1fae0", "\U0001fae0", "\U0001fae0", "\\U0001fae0", "'\\U0001fae0'", "'x\\U0001fae0'"),
    Txt("ctrl-1", "\x01", "\x01", "\\x01", "'\\x01'", "'x\\x01'"),
    Txt("tab", "\t", "\t", "\\t", "'\\t'", "'x\\t'"),
    Txt("lf", "\n", "\n", "\\n", "'\\n'", "'x\\n'"),
    Txt("lone-surrogate", "\udc80", "\\udc80", "\\udc80", "'\\udc80'", "'x\\udc80'"),
    Txt("apostrophe", "'", "'", "'", "\"'\"", "\"x'\""),
    Txt("dquote", '"', '"', '"', "'\"'", "'x\"'"),
    Txt("backslash", "\\", "\\", "\\\\", "'\\\\'", "'x\\\\'"),
    Txt("both-quotes", "a'\"b", "a'\"b", "a'\"b", "'a\\'\"b'", "'xa\\'\"b'"),
    Txt("apostrophe-in", "a'b", "a'b", "a'b", "\"a'b\"", "\"xa'b\""),
]


class P:
    def __init__(self, key, words, valid, errkey=None, positional_extras=True, root=True):
        self.key, self.words, self.valid = key, words, valid
        self.errkey = errkey or key  # the parser whose error() reports an unrecognized argument
        self.gate = words[1] if words[0] == "check" else None
        self.prog = self.gate or key
        self.positional_extras = positional_extras
        self.root = root

    def rc(self):
        return 1 if self.gate else 2


def prog_of(key):
    return key.split()[1] if key.startswith("check ") else key


ASK = ["--class", "c", "--question", "q", "--option", "o", "--effect", "e", "--by", "b"]
NEW = ["--source", "s", "--severity", "v", "--owner-kind", "k", "--by", "b", "--class", "c"]
PARSERS = [
    P("check schema", ["check", "schema"], []),
    P("check cites", ["check", "cites"], []),
    P("check claims", ["check", "claims"], []),
    P("check decisions", ["check", "decisions"], []),
    P("check register", ["check", "register"], []),
    P("index", ["index"], []),
    P("decisions ask", ["decisions", "ask"], ASK),
    P("decisions decide", ["decisions", "decide"], ["ID1", "--answer", "a"]),
    P("decisions withdraw", ["decisions", "withdraw"], ["ID1", "--reason", "r"]),
    P("decisions batch", ["decisions", "batch"], []),
    P("decisions find", ["decisions", "find"], [], positional_extras=False),
    P("findings", ["findings"], None, root=False),
    P("findings new", ["findings", "new"], NEW, errkey="findings"),
    P("findings move", ["findings", "move"], ["id1", "--to", "t", "--by", "b"], errkey="findings"),
]
# Which usage block an error in the parser raised by a shape is printed with (the subparser's unrecognized
# arguments are reported by the top parser).
BY_KEY = {p.key: p for p in PARSERS}

ENV_BASE = {k: v for k, v in os.environ.items() if not k.startswith(("PYTHON", "COLUMNS", "LC_", "LANG"))}


def run(argv, cols="80"):
    """(returncode, stdout, stderr) of ``sys.executable -m gates <argv>``; argv is a list of bytes or str."""
    args = [a if isinstance(a, bytes) else a.encode("utf-8", "surrogateescape") for a in argv]
    env = dict(ENV_BASE, COLUMNS=cols, PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=REPO)
    p = subprocess.run([sys.executable, "-m", "gates"] + args, cwd=REPO, env=env,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return p.returncode, p.stdout, p.stderr


def run_many(cases):
    with ThreadPoolExecutor(max_workers=8) as ex:
        return list(ex.map(lambda c: run(c[1], c[2] if len(c) > 2 else "80"), cases))


def err_golden(errkey, msg, cols="80"):
    """The stderr bytes of an argument error in parser ``errkey``: its 3.9.6 usage, then ``<prog>: error: <msg>``."""
    return (USAGE[cols][errkey] + prog_of(errkey) + ": error: " + msg + "\n").encode("utf-8")


def golden(p, errkey, msg, msgf, cols="80"):
    """The (rc, stdout, stderr) a parser error must give (O1-O3): ``check`` prints the FAIL line (exit 1), a tool
    prints nothing on stdout (exit 2)."""
    out = ("FAIL %s.input: invalid arguments: %s\n" % (p.gate, msgf)).encode("utf-8") if p.gate else b""
    return p.rc(), out, err_golden(errkey, msg, cols)


class CommandLineCase(unittest.TestCase):
    def expect_cases(self, cases):
        """cases: (label, argv, cols, expected (rc, stdout, stderr)); each checked under its own subTest."""
        got = run_many([(c[0], c[1], c[2]) for c in cases])
        for c, g in zip(cases, got):
            with self.subTest(c[0]):
                if g != c[3]:  # a short message: a byte-for-byte diff of long outputs is slow
                    self.fail("got %r\nwant %r" % (tuple(x[:400] for x in (g[0:1] + g[1:])) if False else (g[0], g[1][:300], g[2][:400]),
                                                  (c[3][0], c[3][1][:300], c[3][2][:400])))


class TestEveryParser(CommandLineCase):
    def test_invalid_choice(self):  # M1, T1-T7, K2
        p = BY_KEY["findings"]
        cases = []
        for t in TEXTS:
            m = lambda r, f: golden(p, "findings", "argument {new,move}: invalid choice: %s (choose from 'new', 'move')" % r,
                                    "argument {new,move}: invalid choice: %s (choose from 'new', 'move')" % f)
            cases.append(("findings %s" % t.name, ["findings", t.argv()], "80", m(t.r, t.rf)))
            cases.append(("findings x%s" % t.name, ["findings", b"x" + t.argv()], "80", m(t.rx, t.rxf)))
        self.expect_cases(cases)

    def test_unrecognized(self):  # M3
        cases = []
        for p in PARSERS:
            if p.valid is None:
                continue  # `findings` alone: the required subcommand is reported first
            for t in TEXTS:
                shapes = [("--zz", b"--zz" + t.argv(), "--zz" + t.raw, "--zz" + t.rawf),
                          ("-", b"-" + t.argv(), "-" + t.raw, "-" + t.rawf)]
                if t.arg != "a":  # `--a` is an abbreviation of --all / --answered / --applies-to in some parsers
                    shapes.append(("--", b"--" + t.argv(), "--" + t.raw, "--" + t.rawf))
                if p.positional_extras and p.root:
                    shapes.append(("--root=x extra", None, "extra" + t.raw, "extra" + t.rawf))
                for label, arg, raw, rawf in shapes:
                    if arg is None:
                        argv = p.words + p.valid + ["--root=x", b"extra" + t.argv()]
                    else:
                        argv = p.words + p.valid + [arg]
                    m = "unrecognized arguments: "
                    cases.append(("%s %s %s" % (p.key, label, t.name), argv, "80",
                                  golden(p, p.errkey, m + raw, m + rawf)))
        self.expect_cases(cases)

    def test_ambiguous(self):  # M4
        rows = [("decisions decide", "--r=", "--root, --rule"), ("decisions ask", "--p=", "--plan, --program"),
                ("findings move", "--pin=", "--pin-test, --pin-transcript")]
        cases = []
        for key, opt, matches in rows:
            p = BY_KEY[key]
            for t in TEXTS:
                m = "ambiguous option: %s%s could match %s"
                cases.append(("%s %s%s" % (key, opt, t.name), p.words + [opt.encode() + t.argv()], "80",
                              golden(p, key, m % (opt, t.raw, matches), m % (opt, t.rawf, matches))))
        # the scan finds the ambiguity before any option is consumed (3.9.6's order)
        p = BY_KEY["decisions decide"]
        m = "ambiguous option: --r=a could match --root, --rule"
        cases.append(("ambiguous wins over an earlier missing value", p.words + ["--root", "--r=a"], "80",
                      golden(p, "decisions decide", m, m)))
        self.expect_cases(cases)

    def test_ignored_explicit_long(self):  # M5
        rows = [(p.key, "--help=", "-h/--help") for p in PARSERS]
        rows += [("decisions find", "--all=", "--all"), ("decisions batch", "--answered=", "--answered")]
        cases = []
        for key, opt, name in rows:
            p = BY_KEY[key]
            for t in TEXTS:
                m = "argument %s: ignored explicit argument %%s" % name
                cases.append(("%s %s%s" % (key, opt, t.name), p.words + [opt.encode() + t.argv()], "80",
                              golden(p, key, m % t.r, m % t.rf)))
            m = "argument %s: ignored explicit argument ''" % name
            cases.append(("%s %s(empty)" % (key, opt), p.words + [opt], "80", golden(p, key, m, m)))
        self.expect_cases(cases)

    def help_golden(self, p):
        """`-h` itself: the stdout and exit code every help-giving argument must reproduce."""
        return (p.rc(), ("FAIL %s.input: help requested; no gate was run\n" % p.gate).encode() if p.gate else b"")

    def test_single_dash_combination(self):  # M6, E3
        errors = [("-ha", "'a'"), ("-hha", "'a'"), ("-h a", "' a'"), ("-ha=b", "'a=b'"), ("-hh=a", "'=a'"),
                  ("-h=ha", "'a'"), ("-h=", "''"), ("-h-x", "'-x'"), ("-h-", "'-'"), ("-h==", "'='")]
        helps = ["-hh", "-hhh", "-h=h", "-h=hh"]
        cases = []
        for p in PARSERS:
            for arg, r in errors:
                m = "argument -h/--help: ignored explicit argument %s" % r
                cases.append(("%s %s" % (p.key, arg), p.words + [arg], "80", golden(p, p.key, m, m.replace("\\", "\\\\"))))
            for t in TEXTS:
                m = "argument -h/--help: ignored explicit argument %s" % t.r
                mf = "argument -h/--help: ignored explicit argument %s" % t.rf
                cases.append(("%s -h%s" % (p.key, t.name), p.words + [b"-h" + t.argv()], "80", golden(p, p.key, m, mf)))
            if p.root:
                m = "argument --root: expected one argument"
                cases.append(("%s --root -ha" % p.key, p.words + ["--root", "-ha"], "80", golden(p, p.key, m, m)))
                cases.append(("%s --root -h=" % p.key, p.words + ["--root", "-h="], "80", golden(p, p.key, m, m)))
            # an earlier error wins: the ignored argument is raised where argparse reaches the element
            m = "argument -h/--help: ignored explicit argument 'x'"
            cases.append(("%s --help=x -ha" % p.key, p.words + ["--help=x", "-ha"], "80", golden(p, p.key, m, m)))
        self.expect_cases(cases)
        # the combinations that are the help: the same stdout and exit code as `-h`, usage first on stderr
        for p in PARSERS:
            base = run(p.words + ["-h"])
            self.assertEqual(base[:2], self.help_golden(p), p.key)
            self.assertTrue(base[2].startswith(USAGE["80"][p.key].encode()), p.key)
            for arg in helps:
                with self.subTest("%s %s" % (p.key, arg)):
                    self.assertEqual(run(p.words + [arg]), base)

    def test_findings_double_dash(self):  # M7, E5
        p = BY_KEY["findings"]
        inv = "argument {new,move}: invalid choice: '--' (choose from 'new', 'move')"
        req = "the following arguments are required: {new,move}"
        cases = [
            ("findings -- new", ["findings", "--", "new"], "80", golden(p, "findings", inv, inv)),
            ("findings -- --", ["findings", "--", "--"], "80", golden(p, "findings", inv, inv)),
            ("findings -- move x", ["findings", "--", "move", "x"], "80", golden(p, "findings", inv, inv)),
            ("findings --zz -- new", ["findings", "--zz", "--", "new"], "80", golden(p, "findings", inv, inv)),
            ("findings --", ["findings", "--"], "80", golden(p, "findings", req, req)),
        ]
        # a `--` inside the subcommand's own arguments is not the subparser's value
        n = BY_KEY["findings new"]
        m = "the following arguments are required: --source, --severity, --owner-kind, --by, --class"
        cases.append(("findings new -- x", ["findings", "new", "--", "x"], "80", golden(n, "findings new", m, m)))
        # a `--` after the subcommand is the subcommand's own: both arguments are reported, the `--` too (3.9.6)
        u = "unrecognized arguments: -- x"
        cases.append(("findings new <valid> -- x", ["findings", "new"] + NEW + ["--", "x"], "80", golden(p, "findings", u, u)))
        cases.append(("findings move id1 <valid> -- x", ["findings", "move", "id1", "--to", "t", "--by", "b", "--", "x"],
                      "80", golden(p, "findings", u, u)))
        v = BY_KEY["findings move"]
        m = "the following arguments are required: --to, --by"
        cases.append(("findings move -- id1 --to t --by b", ["findings", "move", "--", "id1", "--to", "t", "--by", "b"],
                      "80", golden(v, "findings move", m, m)))
        self.expect_cases(cases)

    def test_messages_without_argv_text(self):  # M8, control
        cases = []
        for p in PARSERS:
            if p.root:
                m = "argument --root: expected one argument"
                cases.append(("%s --root" % p.key, p.words + p.valid + ["--root"], "80", golden(p, p.key, m, m)))
                m = "--root given more than once"
                cases.append(("%s --root a --root b" % p.key, p.words + p.valid + ["--root", "a", "--root", "b"], "80",
                              golden(p, p.key, m, m)))
        n = BY_KEY["findings new"]
        m = "the following arguments are required: --source, --severity, --owner-kind, --by, --class"
        cases.append(("findings new", n.words, "80", golden(n, "findings new", m, m)))
        v = BY_KEY["findings move"]
        m = "the following arguments are required: id, --to, --by"
        cases.append(("findings move", v.words, "80", golden(v, "findings move", m, m)))
        m = "the following arguments are required: {new,move}"
        cases.append(("findings", ["findings"], "80", golden(BY_KEY["findings"], "findings", m, m)))
        a = BY_KEY["decisions ask"]
        m = "the following arguments are required: --class, --question, --option, --effect, --by"
        cases.append(("decisions ask", a.words, "80", golden(a, "decisions ask", m, m)))
        self.expect_cases(cases)

    def test_usage_wrapping(self):  # M9, E4
        cases = []
        for cols in ("20", "40", "80", "200"):  # 20: the program name is longer than 3/4 of the width
            for p in PARSERS:
                m = "argument -h/--help: ignored explicit argument 'x'"
                cases.append(("%s COLUMNS=%s" % (p.key, cols), p.words + ["--help=x"], cols, golden(p, p.key, m, m, cols)))
        self.expect_cases(cases)

    def test_usage_wrapping_boundaries(self):  # M9, E4: the widths where each comparison of the algorithm decides
        cases = []
        for (cols, key), usage in sorted(EDGE_USAGE.items()):
            p = BY_KEY[key]
            m = "argument -h/--help: ignored explicit argument 'x'"
            want = golden(p, key, m, m)
            want = (want[0], want[1], usage.encode() + (prog_of(key) + ": error: " + m + "\n").encode())
            cases.append(("%s COLUMNS=%d" % (key, cols), p.words + ["--help=x"], str(cols), want))
        self.expect_cases(cases)

    def test_skeleton_digit_runs(self):  # K1
        for n in (4300, 4301):
            d = "9" * n
            p = BY_KEY["findings"]
            m = "argument {new,move}: invalid choice: '%s' (choose from 'new', 'move')" % d
            self.assertEqual(run(["findings", d]), golden(p, "findings", m, m), n)
            f = BY_KEY["decisions find"]
            m = "argument --all: ignored explicit argument '%s'" % d
            self.assertEqual(run(["decisions", "find", "--all=" + d]), golden(f, "decisions find", m, m), n)
            s = BY_KEY["check schema"]
            m = "unrecognized arguments: --zz" + d
            self.assertEqual(run(["check", "schema", "--zz" + d]), golden(s, "check schema", m, m), n)


class TestParserUnit(unittest.TestCase):
    """The parser class itself, where no gate parser has the shape (type=, choices=, a lying str subclass)."""

    def parse(self, parser, argv):
        err = io.StringIO()
        with mock.patch.dict(os.environ, {"COLUMNS": "80"}), contextlib.redirect_stderr(err):
            try:
                parser.parse_args(argv)
            except GateError as e:
                return str(e), err.getvalue()
        raise AssertionError("no GateError")

    def number_parser(self):
        def number(s):
            raise ValueError(s)

        p = _GateParser(prog="p")
        p.add_argument("--n", type=number)
        return p

    def test_invalid_type_value(self):  # M2, K1 (the converter with 4300 and 4301 digits)
        for t in TEXTS:
            with self.subTest(t.name):
                m = "argument --n: invalid number value: %s" % t.r
                self.assertEqual(self.parse(self.number_parser(), ["--n", t.arg]),
                                 ("invalid arguments: " + m, "usage: p [-h] [--n N]\np: error: " + m + "\n"))
        for n in (4300, 4301):
            m = "argument --n: invalid number value: '%s'" % ("9" * n)
            self.assertEqual(self.parse(self.number_parser(), ["--n", "9" * n])[0], "invalid arguments: " + m)

    def test_invalid_type_value_converter_without_name(self):  # M2: no __name__, the type's repr names it (3.9.6's rule)
        class Conv:
            def __repr__(self):
                return "Conv<1>"

            def __call__(self, s):
                raise ValueError(s)

        p = _GateParser(prog="p")
        p.add_argument("--n", type=Conv())
        self.assertEqual(self.parse(p, ["--n", "\u2c2f"])[0],
                         "invalid arguments: argument --n: invalid Conv<1> value: '\\u2c2f'")

    def test_invalid_type_value_type_error(self):  # M2: a TypeError from the converter is the same error
        def number(s):
            raise TypeError(s)

        p = _GateParser(prog="p")
        p.add_argument("--n", type=number)
        m = "argument --n: invalid number value: '\\u2c2f'"
        self.assertEqual(self.parse(p, ["--n", "Ⱟ"])[0], "invalid arguments: " + m)

    def test_argument_type_error_message_passes_through(self):  # control: not argv text
        def number(s):
            raise argparse.ArgumentTypeError("not a number")

        p = _GateParser(prog="p")
        p.add_argument("--n", type=number)
        self.assertEqual(self.parse(p, ["--n", "Ⱟ"])[0], "invalid arguments: argument --n: not a number")

    def test_invalid_choice_non_str_values(self):  # E2 on a converted value: 3.9.6's form, `repr` of the int
        p = _GateParser(prog="p")
        p.add_argument("--n", type=int, choices=(1, 2))
        self.assertEqual(self.parse(p, ["--n", "3"])[0], "invalid arguments: argument --n: invalid choice: 3 (choose from 1, 2)")

    def test_type_not_callable(self):  # not argv text: the message is argparse's own, with the type's repr
        p = _GateParser(prog="p")
        p.add_argument("--n", type=int)
        p.register("type", int, 5)
        self.assertEqual(self.parse(p, ["--n", "1"])[0], "invalid arguments: argument --n: 5 is not callable")

    def test_ignored_explicit_argument_rewrite_only_for_argparse_text(self):  # E2: the message is rebuilt from its literal
        class Raise(argparse.Action):
            def __call__(self, parser, namespace, values, option_string=None):
                raise argparse.ArgumentError(self, self.const)

        head = "ignored explicit argument "
        for const, want in (
            (head + "'\u2c2f'", "argument --x: ignored explicit argument '\\u2c2f'"),
            (head + "'\\u2c2f'", "argument --x: ignored explicit argument '\\u2c2f'"),
            (head + "not a literal", "argument --x: ignored explicit argument not a literal"),
            (head + "5", "argument --x: ignored explicit argument 5"),
            (head + "foo", "argument --x: ignored explicit argument foo"),
            (head + "0x10", "argument --x: ignored explicit argument 0x10"),
            (head + "b'a'", "argument --x: ignored explicit argument b'a'"),
            ("x" * len(head) + "'a'", "argument --x: " + "x" * len(head) + "'a'"),
            ("no " + head + "'a'", "argument --x: no ignored explicit argument 'a'"),
            (head + "'a'" + " tail", "argument --x: ignored explicit argument 'a' tail"),
            ("x" * len(head) + "'" + head + "'", "argument --x: " + "x" * len(head) + "'" + head + "'"),  # head not first
        ):
            p = _GateParser(prog="p")
            p.add_argument("--x", action=Raise, const=const, nargs=0)
            with self.subTest(const):
                self.assertEqual(self.parse(p, ["--x"])[0], "invalid arguments: " + want)

    def test_ignored_explicit_argument_rewrite_with_a_template_tail(self):  # E2: a template with text after %r
        # a translated template may end after the value; the head and the tail both have to match, and the value is
        # the text between them (hand-written: U+2C2F is not printable in Unicode 13.0.0, so R escapes it)
        class Raise(argparse.Action):
            def __call__(self, parser, namespace, values, option_string=None):
                raise argparse.ArgumentError(self, self.const)

        head = "ignored explicit argument "
        for const, want in (
            (head + "'\u2c2f'!", "argument --x: ignored explicit argument '\\u2c2f'!"),
            (head + "'\u2c2f'?", "argument --x: ignored explicit argument '\u2c2f'?"),  # other tail: untouched
            (head + "'\u2c2f'", "argument --x: ignored explicit argument '\u2c2f'"),  # no tail: untouched
        ):
            p = _GateParser(prog="p")
            p.add_argument("--x", action=Raise, const=const, nargs=0)
            with self.subTest(const), mock.patch.object(result, "_IGNORED", head + "%r!"):
                self.assertEqual(self.parse(p, ["--x"])[0], "invalid arguments: " + want)

    def test_leading_double_dash_scope(self):  # E5: only a `--` that reaches the subcommand action first is kept
        def parser():
            p = _GateParser(prog="p")
            p.add_argument("name")
            p.add_subparsers(dest="sub").add_parser("new")
            return p

        ns = parser().parse_args(["--", "n", "new"])
        self.assertEqual((ns.name, ns.sub), ("n", "new"))

    def test_short_flag_without_long_alias(self):  # E3 needs a long alias to route; without one the interpreter's own rule
        p = _GateParser(prog="p")
        p.add_argument("-q", action="store_true")
        self.assertTrue(p.parse_args(["-q"]).q)
        self.assertTrue(self.parse(p, ["-qa"])[0].startswith("invalid arguments: "))  # an error, not a crash

    def test_single_dash_option_with_argument_untouched(self):  # E3 is for a zero-argument option only
        p = _GateParser(prog="p")
        p.add_argument("-x", "--xx")
        self.assertEqual(p.parse_args(["-xfoo"]).xx, "foo")
        self.assertEqual(p.parse_args(["-x=foo"]).xx, "foo")
        # the value is everything after the option letter (3.9.6 and 3.13 alike): a repeated letter is part of it
        self.assertEqual(p.parse_args(["-xxfoo"]).xx, "xfoo")
        self.assertEqual(p.parse_args(["-xx=foo"]).xx, "x=foo")
        self.assertEqual(p.parse_args(["-x==a"]).xx, "=a")

    def quiet_parser(self):
        p = _GateParser(prog="p")
        p.add_argument("-q", "--quiet", action="store_true")
        p.add_argument("-v", "--verbose", action="store_true")
        p.add_argument("-x", action="store_true")
        return p

    def test_single_dash_flag_with_long_alias(self):  # E3 for any zero-argument single-dash option that has a long alias
        # hand-written from E3: the option's own letter is stripped (and one leading `=` first), nothing left is the
        # flag itself, anything else is an ignored explicit argument named with the option's own strings
        errors = [("-qa", "argument -q/--quiet: ignored explicit argument 'a'"),
                  ("-qqa", "argument -q/--quiet: ignored explicit argument 'a'"),
                  ("-q=a", "argument -q/--quiet: ignored explicit argument 'a'"),
                  ("-q=", "argument -q/--quiet: ignored explicit argument ''"),
                  ("-qv", "argument -q/--quiet: ignored explicit argument 'v'"),  # only q is stripped
                  ("-vq", "argument -v/--verbose: ignored explicit argument 'q'"),
                  ("-vqq", "argument -v/--verbose: ignored explicit argument 'qq'"),
                  ("-qⰯ","argument -q/--quiet: ignored explicit argument '\\u2c2f'")]
        for arg, want in errors:
            with self.subTest(arg):
                self.assertEqual(self.parse(self.quiet_parser(), [arg])[0], "invalid arguments: " + want)
        for arg in ("-q", "-qq", "-qqq", "-q=q"):
            with self.subTest(arg):
                ns = self.quiet_parser().parse_args([arg])
                self.assertEqual((ns.quiet, ns.verbose, ns.x), (True, False, False))
        ns = self.quiet_parser().parse_args(["-v", "-q", "-vv"])
        self.assertEqual((ns.quiet, ns.verbose), (True, True))

    def test_single_dash_flag_without_long_alias_keeps_interpreter_handling(self):  # E3 does not route `-x`
        for arg in ("-x", "-xx"):
            with self.subTest(arg):
                ns = self.quiet_parser().parse_args([arg])
                self.assertEqual((ns.quiet, ns.verbose, ns.x), (False, False, True))

    def test_ambiguous_option_is_found_when_scanned(self):  # decision 1: 3.9.6's order on every interpreter
        def parser():
            p = _GateParser(prog="p")
            p.add_argument("--root")
            p.add_argument("--rule")
            return p

        want = "invalid arguments: ambiguous option: --r=a could match --root, --rule"
        self.assertEqual(self.parse(parser(), ["--root", "--r=a"])[0], want)
        self.assertEqual(self.parse(parser(), ["--r=a", "--root"])[0], want)

    def test_invalid_choice_non_str_value_uses_repr(self):  # decision 3: 3.9.6 prints `repr` of a converted value
        class Thing:
            def __init__(self, text):
                self.text = text

            def __repr__(self):
                return "Thing<%s>" % self.text

            def __str__(self):
                return "STR-NOT-USED"

            def __eq__(self, other):
                return False

            __hash__ = None

        p = _GateParser(prog="p")
        p.add_argument("--n", type=Thing, choices=[Thing("c")])
        self.assertEqual(self.parse(p, ["--n", "v"])[0],
                         "invalid arguments: argument --n: invalid choice: Thing<v> (choose from Thing<c>)")

    def test_usage_formatter_indent(self):  # E4: text_width is the width less the indent; literals from native 3.9.6
        with mock.patch.dict(os.environ, {"COLUMNS": "30"}):
            p = _GateParser(prog="p", add_help=False)
            for name in ("alpha", "beta", "gamma"):
                p.add_argument("--" + name, metavar=name[0].upper())
            want = {0: "usage: p [--alpha A]\n         [--beta B]\n         [--gamma G]\n\n",
                    4: "usage: p [--alpha A]\n         [--beta B]\n         [--gamma G]\n\n",
                    10: "usage: p\n         [--alpha A]\n         [--beta B]\n         [--gamma G]\n\n"}
            for indent, text in want.items():
                f = p._get_formatter()
                f._current_indent = indent
                with self.subTest(indent):
                    self.assertEqual(f._format_usage(None, p._actions, p._mutually_exclusive_groups, "usage: "), text)

    def test_formatter_class_default_and_explicit(self):  # E4
        self.assertEqual(_GateParser(prog="p").formatter_class.__name__, "_UsageFormatter")
        self.assertIs(_GateParser(prog="p", formatter_class=argparse.RawTextHelpFormatter).formatter_class,
                      argparse.RawTextHelpFormatter)

    def test_usage_special_forms(self):  # E4: a parser with no arguments, and a custom usage text
        bare = _GateParser(prog="p", add_help=False)
        self.assertEqual(self.parse(bare, ["x"]), ("invalid arguments: unrecognized arguments: x",
                                                   "usage: p\np: error: unrecognized arguments: x\n"))
        custom = _GateParser(prog="p", usage="%(prog)s custom")
        self.assertEqual(self.parse(custom, ["x"]), ("invalid arguments: unrecognized arguments: x",
                                                     "usage: p custom\np: error: unrecognized arguments: x\n"))

    def test_usage_positionals_only_and_groups(self):  # E4: 3.9.6's lines (literals from 3.9.6 argparse, COLUMNS=20/30)
        with mock.patch.dict(os.environ, {"COLUMNS": "20"}):
            p = _GateParser(prog="p", add_help=False)
            p.add_argument("a" * 14)
            p.add_argument("b" * 14)
            self.assertEqual(p.format_usage(), "usage: p\n         aaaaaaaaaaaaaa\n         bbbbbbbbbbbbbb\n")
        with mock.patch.dict(os.environ, {"COLUMNS": "30"}):
            q = _GateParser(prog="q")
            g = q.add_mutually_exclusive_group(required=True)
            g.add_argument("--alpha", metavar="A")
            g.add_argument("--beta", metavar="B")
            q.add_argument("--gamma", nargs="*", metavar="G")
            self.assertEqual(q.format_usage(), "usage: q [-h]\n         (--alpha A | --beta B)\n         [--gamma [G ...]]\n")

    def test_choices_in_declared_order(self):  # E2
        p = _GateParser(prog="p")
        p.add_argument("x", choices=["b", "Ⱟ", "a'"])
        self.assertEqual(self.parse(p, ["z"])[0],
                         "invalid arguments: argument x: invalid choice: 'z' (choose from 'b', '\\u2c2f', \"a'\")")

    def test_repr_str_subclass(self):  # T9
        class Liar(str):
            def __repr__(self):
                return "LIE-REPR"

            def __str__(self):
                return "LIE-STR"

        p = _GateParser(prog="p")
        p.add_argument("x", type=Liar, choices=[Liar("ab"), Liar("Ⱟ")])
        self.assertEqual(self.parse(p, ["zz"])[0],
                         "invalid arguments: argument x: invalid choice: 'zz' (choose from 'ab', '\\u2c2f')")

    def test_skeleton_base_exception_group(self):  # K3
        class Boom(BaseException):
            pass

        class Raise(argparse.Action):
            def __call__(self, parser, namespace, values, option_string=None):
                raise self.const

        excs = [Boom("b")]
        group = getattr(builtins, "BaseExceptionGroup", None)  # absent on 3.9: only the plain subclass is run there
        if group is not None:
            excs.append(group("g", [KeyboardInterrupt()]))
        for exc in excs:
            p = _GateParser(prog="p")
            p.add_argument("--x", action=Raise, const=exc, nargs=0)
            with self.subTest(type(exc).__name__), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(type(exc)) as cm:
                    p.parse_args(["--x"])
                self.assertIs(cm.exception, exc)
        self.assertEqual(group is None, sys.version_info < (3, 11))


# SHA-256 of "".join(repr(chr(c)) + "\n" for c in range(0x110000)) in UTF-8, measured on /usr/bin/python3 3.9.6.
REPR_SHA256_39 = "7860d79119580a12183b4b8b15522d4fcdbfbed4155a7f59496bad6c65a96510"


class TestFrozenRepr(unittest.TestCase):
    """E1 through the parser's invalid-choice message with no choices: ``invalid choice: <R> (choose from )``."""

    def r_of(self, parser, action, value):
        try:
            parser._check_value(action, value)
        except argparse.ArgumentError as e:
            msg = e.message
        else:
            raise AssertionError("no error")
        head, tail = "invalid choice: ", " (choose from )"
        self.assertTrue(msg.startswith(head) and msg.endswith(tail), msg)
        return msg[len(head):len(msg) - len(tail)]

    def test_frozen_repr_every_code_point(self):  # T8
        p = _GateParser(prog="p")
        action = p.add_argument("x", choices=())
        from gates.lib import print_table
        h = hashlib.sha256()
        for c in range(0x110000):
            ch = chr(c)
            r = self.r_of(p, action, ch)
            h.update((r + "\n").encode("utf-8"))
            if sys.version_info < (3, 10) or print_table.is_printable(ch) == ch.isprintable():
                if r != repr(ch):
                    self.fail("U+%04X: %r != %r" % (c, r, repr(ch)))
        self.assertEqual(h.hexdigest(), REPR_SHA256_39)
        for s, want in (("'", "\"'\""), ('"', "'\"'"), ("\\", "'\\\\'"), ("a'\"b", "'a\\'\"b'"), ("a'b", "\"a'b\""),
                        ("", "''"), ("Ⱟ\U0001fae0\x01", "'\\u2c2f\\U0001fae0\\x01'")):
            self.assertEqual(self.r_of(p, action, s), want, s)


class TestParserSites(unittest.TestCase):
    def test_parser_sites_enumerated(self):  # P2, K1
        names = {"_GateParser", "gate_args", "ArgumentParser", "add_subparsers", "add_parser"}
        found = []
        keywords = []
        for dirpath, _, files in os.walk(os.path.join(REPO, "gates")):
            for f in sorted(files):
                if not f.endswith(".py"):
                    continue
                path = os.path.join(dirpath, f)
                with open(path, encoding="utf-8") as fh:
                    tree = ast.parse(fh.read())
                for node in ast.walk(tree):
                    if not isinstance(node, ast.Call):
                        continue
                    fn = node.func
                    name = fn.id if isinstance(fn, ast.Name) else fn.attr if isinstance(fn, ast.Attribute) else None
                    if name in names:
                        found.append((os.path.relpath(path, REPO).replace(os.sep, "/"), name))
                    for k in node.keywords:
                        if k.arg in ("type", "choices"):
                            keywords.append((os.path.relpath(path, REPO).replace(os.sep, "/"), k.arg))
        self.assertEqual(sorted(found), [
            ("gates/gate_cites.py", "gate_args"), ("gates/gate_claims.py", "gate_args"),
            ("gates/gate_decisions.py", "gate_args"), ("gates/gate_register.py", "gate_args"),
            ("gates/gate_schema.py", "gate_args"), ("gates/lib/result.py", "_GateParser"),
            ("gates/tools/decisions_cli.py", "gate_args"), ("gates/tools/findings_cli.py", "_GateParser"),
            ("gates/tools/findings_cli.py", "add_parser"), ("gates/tools/findings_cli.py", "add_parser"),
            ("gates/tools/findings_cli.py", "add_subparsers"), ("gates/tools/index.py", "gate_args")])
        self.assertEqual(keywords, [])


if __name__ == "__main__":
    unittest.main()
