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

    def test_equals_after_one_dash(self):  # F-1, E6: `-=<text>` is an unknown option on every interpreter (3.9.6's form)
        req = "the following arguments are required: {new,move}"
        cases = []
        for p in PARSERS:
            for arg in ["-=", "-=a", "-==", "-=-", "-=--", "-=h", "-=--root"]:
                cases.append((p, arg, [arg.encode()], arg, arg))
            for t in TEXTS:
                cases.append((p, "-=" + t.name, [b"-=" + t.argv()], "-=" + t.raw, "-=" + t.rawf))
            if p.positional_extras:  # with a space it is a positional text, which the parsers with only extras report
                for arg in ["-= x", "-=a b"]:
                    cases.append((p, arg, [arg.encode()], arg, arg))
        out = []
        for p, label, tail, raw, rawf in cases:
            if p.valid is None:  # `findings`: the unknown option is dropped, the subcommand is missing; a text with a space is its value
                if " " in raw:
                    m = "argument {new,move}: invalid choice: %s (choose from 'new', 'move')" % ("'" + raw + "'")
                    want = golden(p, "findings", m, m)
                else:
                    want = golden(p, "findings", req, req)
                argv = p.words + tail
            else:
                m = "unrecognized arguments: "
                want = golden(p, p.errkey, m + raw, m + rawf)
                argv = p.words + p.valid + tail
            out.append(("%s %s" % (p.key, label), argv, "80", want))
        self.expect_cases(out)

    def test_equals_after_one_dash_after_subcommand_and_double_dash_control(self):  # F-1: position and the `--=` control
        n = BY_KEY["findings new"]
        m = "unrecognized arguments: -=a"
        cases = [("findings new <valid> -=a", n.words + NEW + ["-=a"], "80", golden(n, "findings", m, m))]
        d = BY_KEY["decisions decide"]
        # `--=a` is a prefix of every long option on both interpreters: ambiguous in the order argparse lists them
        m = "ambiguous option: --=a could match --help, --root, --answer, --rule, --landed-in"
        cases.append(("decisions decide --=a", d.words + ["--=a"], "80", golden(d, "decisions decide", m, m)))
        self.expect_cases(cases)

    def test_negative_number_digits_assigned_after_unicode_13(self):  # F-2, E7, R2-4 (M11 revised): all 14 parsers
        # `-<digit>` of Unicode 14-15 is no number, so it is an unknown option: as the value of `--root` it leaves the
        # option with no argument (a number would be the root); as a text where a positional is wanted it is no positional
        req = "the following arguments are required: {new,move}"
        f, fi = BY_KEY["findings"], BY_KEY["decisions find"]
        digits = ["\U00011f50", "\U00011f59", "\U00016ac0", "\U00016ac9", "\U0001e4f0", "\U0001e4f9"]
        missing = {"decisions decide": "ID", "decisions withdraw": "ID", "findings move": "id"}  # the positional of each
        cases = []
        for d in digits:
            for label, arg in (("-D", "-" + d), ("-.D", "-." + d), ("-1D", "-1" + d), ("-D.5", "-" + d + ".5"),
                               ("-DD", "-" + d + d)):
                u = "unrecognized arguments: " + arg
                cases.append(("findings %s U+%04X" % (label, ord(d)), ["findings", arg], "80", golden(f, "findings", req, req)))
                cases.append(("decisions find %s U+%04X" % (label, ord(d)), ["decisions", "find", arg], "80",
                              golden(fi, "decisions find", u, u)))
                for p in PARSERS:
                    if p.root:
                        m = "argument --root: expected one argument"
                        cases.append(("%s --root %s U+%04X" % (p.key, label, ord(d)),
                                      p.words + valid_ok(p) + ["--root", arg], "80", golden(p, p.key, m, m)))
                    if p.key in missing:  # the text is not the positional: the root is a directory that does not exist
                        m = "the following arguments are required: " + missing[p.key]
                        cases.append(("%s %s U+%04X" % (p.key, label, ord(d)),
                                      p.words + [arg] + p.valid[1:] + ["--root", NONEXISTENT_ROOT], "80", golden(p, p.key, m, m)))
        # controls: a digit that Unicode 13 has (and ASCII) makes a negative number, so a positional text
        for arg in ("-5", "-1.5", "-.5", "-\u0663", "-\u0663.\u0664"):
            m = "argument {new,move}: invalid choice: %s (choose from 'new', 'move')" % ("'" + arg + "'")
            cases.append(("findings control %s" % arg, ["findings", arg], "80", golden(f, "findings", m, m)))
        for arg in ("-5", "-1.5", "-.5", "-\u0663"):  # and the value of `--root`: a directory that does not exist
            for p in PARSERS:
                if p.root:
                    cases.append(("%s --root control %s" % (p.key, arg), p.words + valid_ok(p) + ["--root", arg], "80",
                                  input_fail(p, ROOT_FAIL)))
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

    def test_short_flag_without_long_alias(self):  # C4 (was: E3 needs a long alias, else the interpreter's own rule)
        p = _GateParser(prog="p")
        with self.assertRaises(result.ShortFlagWithoutLongAlias):  # refused, so E3 never meets a flag it cannot route
            p.add_argument("-q", action="store_true")
        p.add_argument("-q", "--quiet", action="store_true")  # the admitted equivalent
        self.assertTrue(p.parse_args(["-q"]).quiet)
        self.assertEqual(self.parse(p, ["-qa"])[0], "invalid arguments: argument -q/--quiet: ignored explicit argument 'a'")

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
        p.add_argument("-x", "--ex", dest="x", action="store_true")  # a single-dash flag needs a long alias (C4)
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

    def test_single_dash_flag_without_long_alias_is_refused(self):  # C4 (was: ..._keeps_interpreter_handling for `-x`)
        with self.assertRaises(result.ShortFlagWithoutLongAlias):
            _GateParser(prog="p").add_argument("-x", action="store_true")
        for arg in ("-x", "-xx"):  # the admitted `-x/--ex` is routed by E3 like `-q`
            with self.subTest(arg):
                ns = self.quiet_parser().parse_args([arg])
                self.assertEqual((ns.quiet, ns.verbose, ns.x), (False, False, True))
        self.assertEqual(self.parse(self.quiet_parser(), ["-xa"])[0],
                         "invalid arguments: argument -x/--ex: ignored explicit argument 'a'")

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


    def test_equals_after_one_dash_is_no_abbreviation(self):  # F-1, E6: 3.9.6 never prefix-matches the text before `=`
        def parser(*options):
            p = _GateParser(prog="p")
            for o in options:
                p.add_argument(o, "-" + o, action="store_true")  # `-abc/--abc`: a single-dash flag needs a long alias (C4)
            return p

        for arg in ("-=x", "-=", "-ab=x", "-a=x", "-ab=="):
            with self.subTest(arg):
                m = "unrecognized arguments: " + arg
                self.assertEqual(self.parse(parser("-abc"), [arg]), ("invalid arguments: " + m, "usage: p [-h] [-abc]\np: error: " + m + "\n"))
        # an option that is the first two characters keeps its argument, and `-abc` is not matched as well
        p = _GateParser(prog="p")
        p.add_argument("-a")
        p.add_argument("-abc", "--abc", action="store_true")
        ns = p.parse_args(["-ab=x"])
        self.assertEqual((ns.a, ns.abc), ("b=x", False))
        # the abbreviation without an `=`, and an option named in full before the `=`, are matched as before
        p = _GateParser(prog="p")
        p.add_argument("-abc", "--abc", action="store_true")
        self.assertTrue(p.parse_args(["-ab"]).abc)
        p = _GateParser(prog="p")
        p.add_argument("-abc")
        self.assertEqual(p.parse_args(["-abc=v"]).abc, "v")
        p = _GateParser(prog="p")  # an option string of one character is matched exactly
        p.add_argument("-", action="store_true", dest="d")
        self.assertTrue(p.parse_args(["-"]).d)
        # with a space it is a positional text, as everywhere
        p = _GateParser(prog="p")
        p.add_argument("x", nargs="?")
        self.assertEqual(p.parse_args(["-= x"]).x, "-= x")

    def test_negative_number_matcher_is_unicode_13(self):  # F-2, E7: the digits of Unicode 13.0.0, on every interpreter
        m = result._NEGATIVE_NUMBER
        digits = [c for c in range(0x110000) if m.match("-" + chr(c))]
        self.assertEqual(len(digits), 650)
        self.assertEqual(hashlib.sha256(",".join(map(str, digits)).encode()).hexdigest(), DIGITS_SHA256_39)
        for text, want in (("-5", True), ("-1.5", True), ("-.5", True), ("-٣", True), ("-", False), ("-.", False),
                           ("-1.", False), ("-5\n", True), ("-.5\n", True), ("-5\n\n", False), ("5", False), ("--5", False), ("-\U0001e4f0", False), ("-1.\U00011f50", False)):
            self.assertEqual(bool(m.match(text)), want, text)
        if sys.version_info < (3, 10):  # on 3.9.6 it is exactly what `\d` means
            import re
            self.assertEqual(digits, [c for c in range(0x110000) if re.match(r"\d", chr(c))])

    def test_negative_number_matcher_installed_everywhere(self):  # F-2, E7: the parser, its groups and its subparsers
        p = _GateParser(prog="p")
        subs = p.add_subparsers()
        sub = subs.add_parser("s")
        for owner in (p, p._optionals, p._positionals, p.add_argument_group(), p.add_mutually_exclusive_group(), sub,
                      sub._optionals, sub.add_argument_group()):
            self.assertIs(owner._negative_number_matcher, result._NEGATIVE_NUMBER)

    def test_negative_number_options_defined_with_new_digits(self):  # F-2, E7: `_has_negative_number_optionals`
        for where in ("parser", "group"):
            with self.subTest(where):
                p = _GateParser(prog="p")
                p.add_argument("x", nargs="?")
                (p if where == "parser" else p.add_argument_group()).add_argument("-\U0001e4f0", "--digit", action="store_true")
                self.assertEqual(p._has_negative_number_optionals, [])
                self.assertEqual(p.parse_args(["-1"]).x, "-1")
        p = _GateParser(prog="p")  # control: an option that is a number of Unicode 13 turns `-5` into an unknown option
        p.add_argument("x", nargs="?")
        p.add_argument("-٣", "--three", action="store_true")
        self.assertEqual(p._has_negative_number_optionals, [True])
        m = "unrecognized arguments: -5"
        self.assertEqual(self.parse(p, ["-5"]), ("invalid arguments: " + m, "usage: p [-h] [-٣] [x]\np: error: " + m + "\n"))

DIGITS_SHA256_39 = "a277bbc39852a47c72cac71ac7f70d50ee2bfbb4cbbf42d9a11ee54f240fcdbe"  # the 650 digits of Unicode 13.0.0 (3.9.6), see test

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


# =====================================================================================================================
# Fix round 2 (owner Q-G3-F1C-1 (a), Q-A2-1 (a)): the refusals of rule E8 (rows C1-C6), `--` as an explicit option value
# (rule E9, rows D1-D3), E7 over all 14 parsers (row M11). Every expected value is written by hand: the goldens of the
# command-line rows are 3.9.6's form (measured with the unmodified parsers, 2026-11-16, equal on 3.13 except `=--`, whose
# 3.13 value `--` is rule E9's form).
# =====================================================================================================================
ASK_OK = ["--class", "c", "--question", "q", "--option", "a::b", "--effect", "lasting", "--by", "b"]
NONEXISTENT_ROOT = "/nonexistent-f1-root"
ROOT_FAIL = "git rev-parse --show-toplevel failed (exit 128); run /strict-delivery:init"  # a root that is no directory
ROOT_NOT_TOP = "git rev-parse --show-toplevel: root must be the repository top level"  # `--root=` (an empty root)


def valid_ok(p):
    """The arguments that satisfy parser ``p`` for a command line that must get as far as the root (`ask` needs a
    lasting effect and a LABEL::COST option for that)."""
    return ASK_OK if p.key == "decisions ask" else p.valid


def input_fail(p, text):
    """What a gate or a tool prints when it refuses after the arguments parsed: ``check`` the FAIL line on stdout, a tool
    ``<prog>: <text>`` on stderr, both with exit status 1 and nothing else."""
    if p.gate:
        return 1, ("FAIL %s.input: %s\n" % (p.gate, text)).encode("utf-8"), b""
    return 1, b"", ("%s: %s\n" % (p.key, text)).encode("utf-8")


class Captured(GateError):
    pass


TESTED_VALUE_OPTIONS = 53  # by hand from the parsers' option lists: schema/cites/index 1 each, claims/decisions/register 2 each,
# ask 12, decide 4, withdraw 2, batch 4, find 3, findings 0, findings new 11, findings move 8


def production_parsers():
    """{key: parser} of the 14 parsers of row P1 exactly as the commands build them: ``parse_args`` is replaced by a
    spy that records the parser and stops, so the command's own construction code runs and nothing else. ``findings new``
    and ``findings move`` are the subparsers of the ``findings`` parser."""
    from gates.__main__ import main
    found = {}
    for p in PARSERS:
        if p.key in ("findings new", "findings move"):
            continue
        seen = []

        def spy(self, args=None, namespace=None):
            seen.append(self)
            raise Captured("captured")

        with mock.patch.object(_GateParser, "parse_args", spy), contextlib.redirect_stderr(io.StringIO()), \
                contextlib.redirect_stdout(io.StringIO()):
            main(p.words + ["x"])
        found[p.key] = seen[0]
    subs = [a for a in found["findings"]._actions if isinstance(a, argparse._SubParsersAction)][0]
    found["findings new"], found["findings move"] = subs.choices["new"], subs.choices["move"]
    return found


class TestRefusals(unittest.TestCase):
    """Rule E8: a parser configuration `_GateParser` does not admit is refused, with a named error, where it is built."""

    ROUTES = ("parser", "group", "exclusive group", "subparser", "subparser group", "subparser exclusive group",
              "parents plain", "parents gate")

    def build(self, route, option_strings, **kw):
        """A parser to which ``add_argument(*option_strings, **kw)`` is applied by ``route`` (the call that must refuse)."""
        if route == "parser":
            p = _GateParser(prog="p")
            p.add_argument(*option_strings, **kw)
        elif route == "group":
            p = _GateParser(prog="p")
            p.add_argument_group("g").add_argument(*option_strings, **kw)
        elif route == "exclusive group":
            p = _GateParser(prog="p")
            p.add_mutually_exclusive_group().add_argument(*option_strings, **kw)
        elif route == "subparser":
            p = _GateParser(prog="p")
            p.add_subparsers().add_parser("s").add_argument(*option_strings, **kw)
        elif route == "subparser group":
            p = _GateParser(prog="p")
            p.add_subparsers().add_parser("s").add_argument_group("g").add_argument(*option_strings, **kw)
        elif route == "subparser exclusive group":
            p = _GateParser(prog="p")
            p.add_subparsers().add_parser("s").add_mutually_exclusive_group().add_argument(*option_strings, **kw)
        elif route == "parents plain":  # `_add_container_actions` adds through `_add_action`, not `add_argument`
            q = argparse.ArgumentParser(prog="q", add_help=False)
            q.add_argument(*option_strings, **kw)
            p = _GateParser(prog="p", parents=[q])
        elif route == "parents gate":  # refused where the parent is built
            q = _GateParser(prog="q", add_help=False)
            q.add_argument(*option_strings, **kw)
            p = _GateParser(prog="p", parents=[q])
        else:
            raise AssertionError(route)
        return p

    def test_hierarchy(self):  # E8: one base, four named subclasses
        for cls in (result.OptionStringHoldsEquals, result.AbbrevDisabled, result.NestedGroup,
                    result.ShortFlagWithoutLongAlias):
            self.assertTrue(issubclass(cls, result.ParserRefused), cls)
            self.assertIsNot(cls, result.ParserRefused)
        self.assertTrue(issubclass(result.ParserRefused, ValueError))
        self.assertFalse(issubclass(result.ParserRefused, GateError))  # a build error, never a gate verdict

    def test_refuse_option_string_with_equals(self):  # C1 (R2-1: its only configuration), K2 (U+1E4F0), K1 (4301 digits)
        values = [("-a=b",), ("-x=",), ("-=x",), ("--a=b",), ("--=",), ("--x=",), ("--ok", "-a=b"), ("-\U0001e4f0=",),
                  ("-" + "9" * 4300 + "=",)]
        shown = {("-\U0001e4f0=",): "'-\\U0001e4f0='", ("-" + "9" * 4300 + "=",): "'-" + "9" * 4300 + "='"}
        kinds = (("store", {}), ("store_true", {"action": "store_true"}), ("append", {"action": "append"}),
                 ("_Once", {"action": result._Once}))
        for route in self.ROUTES:
            for option_strings in values:
                offender = [o for o in option_strings if "=" in o][0]
                text = shown.get((offender,), "'%s'" % offender)
                for kind, kw in kinds:
                    with self.subTest(route=route, option=option_strings[0][:12], kind=kind):
                        with self.assertRaises(result.OptionStringHoldsEquals) as cm:
                            self.build(route, option_strings, **kw)
                        self.assertEqual(str(cm.exception), "option string %s holds '=' (refused: F1 rule E8)" % text)

    def test_option_string_with_equals_leaves_the_parser_unchanged(self):  # C1: refused before it is registered
        p = _GateParser(prog="p")
        for route_call in (lambda: p.add_argument("-a=b"), lambda: p.add_argument_group("g").add_argument("--a=b"),
                           lambda: p.add_mutually_exclusive_group().add_argument("--x=")):
            with self.assertRaises(result.OptionStringHoldsEquals):
                route_call()
        self.assertEqual(sorted(p._option_string_actions), ["--help", "-h"])
        p.add_argument("--ok")
        self.assertEqual(p.parse_args(["--ok", "v"]).ok, "v")

    def test_equals_controls_are_admitted(self):  # C1 control: `-a`, `--a-b`, `--ab`; and the 14 parsers (C6)
        for route in self.ROUTES:
            for option_strings in (("-a",), ("--a-b",), ("--ab",), ("-a", "--a-b")):
                with self.subTest(route=route, option=option_strings):
                    p = self.build(route, option_strings)
                    self.assertTrue(p._option_string_actions)
        p = _GateParser(prog="p")
        p.add_argument("-a", "--a-b")
        self.assertEqual(p.parse_args(["-a", "v"]).a_b, "v")
        self.assertEqual(p.parse_args(["--a-b=v"]).a_b, "v")

    def test_refuse_allow_abbrev_false(self):  # C2 (R2-3 is a refused input)
        with self.assertRaises(result.AbbrevDisabled) as cm:
            _GateParser(prog="p", allow_abbrev=False)
        self.assertEqual(str(cm.exception), "allow_abbrev=False (refused: F1 rule E8)")
        with self.assertRaises(result.AbbrevDisabled):
            _GateParser(prog="p").add_subparsers().add_parser("x", allow_abbrev=False)
        # after the build: refused when parsing starts, whichever the parse entry point
        p = _GateParser(prog="p")
        p.add_argument("--root")
        p.allow_abbrev = False
        with self.assertRaises(result.AbbrevDisabled):
            p.parse_args(["--root", "a"])
        top = _GateParser(prog="p")
        sub = top.add_subparsers().add_parser("s")
        sub.allow_abbrev = False
        with self.assertRaises(result.AbbrevDisabled):
            top.parse_args(["s"])
        # controls
        for kw in ({}, {"allow_abbrev": True}):
            p = _GateParser(prog="p", **kw)
            p.add_argument("--root")
            self.assertEqual(p.parse_args(["--ro", "a"]).root, "a")
        sub = _GateParser(prog="p").add_subparsers().add_parser("x", allow_abbrev=True)
        self.assertTrue(sub.allow_abbrev)

    def test_refuse_nested_group(self):  # C3 (R2-2 is a refused input)
        message = "a group inside a group (refused: F1 rule E8)"
        owners = (("parser", lambda: _GateParser(prog="p")),
                  ("subparser", lambda: _GateParser(prog="p").add_subparsers().add_parser("s")))
        for where, make in owners:
            for kind, outer in (("argument group", lambda p: p.add_argument_group("g")),
                                ("exclusive group", lambda p: p.add_mutually_exclusive_group())):
                for inner, call in (("argument group", lambda g: g.add_argument_group("h")),
                                    ("exclusive group", lambda g: g.add_mutually_exclusive_group())):
                    with self.subTest(where=where, outer=kind, inner=inner):
                        group = outer(make())
                        with self.assertRaises(result.NestedGroup) as cm:
                            call(group)
                        self.assertEqual(str(cm.exception), message)
        # the group and the parser are not nested at depth 3 either: depth 2 is refused, so no chain exists; the
        # parents route builds the parent's groups on the child and a group is never the target
        p = _GateParser(prog="p")
        g = p.add_argument_group("g")
        q = argparse.ArgumentParser(prog="q", add_help=False)
        q.add_argument_group("h").add_argument("--x")
        with self.assertRaises(result.NestedGroup):
            g._add_container_actions(q)
        # a post-13.0 digit option in a group nested in a group is therefore never defined (R2-2)
        with self.assertRaises(result.NestedGroup):
            p.add_argument_group("a").add_mutually_exclusive_group().add_argument("-\U0001e4f0", "--digit")

    def test_one_level_of_groups_is_admitted(self):  # C3 control: E7 still holds in a group of either kind
        for where, make in (("parser", lambda: _GateParser(prog="p")),
                            ("subparser", lambda: _GateParser(prog="p").add_subparsers().add_parser("s"))):
            for kind, group in (("argument group", lambda p: p.add_argument_group("g")),
                                ("exclusive group", lambda p: p.add_mutually_exclusive_group())):
                with self.subTest(where=where, kind=kind):
                    p = make()
                    p.add_argument("x", nargs="?")
                    group(p).add_argument("-\U0001e4f0", "--digit", action="store_true")
                    self.assertEqual(p._has_negative_number_optionals, [])
                    self.assertEqual(p.parse_known_args(["-1"])[0].x, "-1")
                    g = group(p)
                    self.assertIs(g._negative_number_matcher, result._NEGATIVE_NUMBER)

    def test_refuse_short_flag_without_long_alias(self):  # C4 (FR-1 is a refused input), K2 (U+1E4F0), K1 (4301 digits)
        class Z(argparse.Action):
            def __init__(self, option_strings, dest, **kw):
                super().__init__(option_strings, dest, nargs=0, **kw)

            def __call__(self, parser, namespace, values, option_string=None):
                pass

        kinds = (("store_true", {"action": "store_true"}), ("store_false", {"action": "store_false"}),
                 ("store_const", {"action": "store_const", "const": 1}),
                 ("append_const", {"action": "append_const", "const": 1}), ("count", {"action": "count"}),
                 ("help", {"action": "help"}), ("version", {"action": "version", "version": "v"}), ("custom", {"action": Z}))
        values = [(("-x",), "'-x'"), (("-1",), "'-1'"), (("-\U0001e4f0",), "'-\\U0001e4f0'"),
                  (("-x", "-y"), "'-x', '-y'"), (("-" + "9" * 4301,), "'-" + "9" * 4301 + "'")]
        for route in self.ROUTES:
            for option_strings, shown in values:
                for kind, kw in kinds:
                    with self.subTest(route=route, option=option_strings[0][:8], kind=kind):
                        with self.assertRaises(result.ShortFlagWithoutLongAlias) as cm:
                            self.build(route, option_strings, **kw)
                        self.assertEqual(str(cm.exception),
                                         "single-dash flag %s has no long alias (refused: F1 rule E8)" % shown)

    def test_short_flag_controls_are_admitted(self):  # C4 control
        for route in self.ROUTES:
            for option_strings, kw in ((("-q", "--quiet"), {"action": "store_true"}),
                                       (("--quiet", "-q"), {"action": "store_true"}),
                                       (("-q", "-Q", "--quiet"), {"action": "store_true"}),
                                       (("-r",), {}), (("-r", "--root"), {}), (("-x",), {"nargs": "?"}),
                                       (("--flag",), {"action": argparse.BooleanOptionalAction}),
                                       (("-v", "--verbose"), {"action": "count"})):
                with self.subTest(route=route, option=option_strings, kw=sorted(kw)):
                    self.build(route, option_strings, **kw)
        p = _GateParser(prog="p")  # `-h/--help` of every parser, and a flag with a long alias parses
        p.add_argument("-q", "--quiet", action="store_true")
        self.assertTrue(p.parse_args(["-q"]).quiet)

    def test_refuse_short_flag_left_without_long_alias_by_conflict_resolution(self):  # C4: `resolve` removes the alias
        p = _GateParser(prog="p", conflict_handler="resolve")
        p.add_argument("-q", "--quiet", action="store_true")
        with self.assertRaises(result.ShortFlagWithoutLongAlias) as cm:
            p.add_argument("--quiet", action="store_true")
        self.assertEqual(str(cm.exception), "single-dash flag '-q' has no long alias (refused: F1 rule E8)")
        p = _GateParser(prog="p", conflict_handler="resolve")  # the help flag's long alias taken away
        with self.assertRaises(result.ShortFlagWithoutLongAlias) as cm:
            p.add_argument("--help", action="store_true")
        self.assertEqual(str(cm.exception), "single-dash flag '-h' has no long alias (refused: F1 rule E8)")
        p = _GateParser(prog="p", conflict_handler="resolve")  # control: the whole option replaced is fine
        p.add_argument("-q", "--quiet", action="store_true")
        p.add_argument("-q", "--quiet", action="store_true")
        self.assertTrue(p.parse_args(["-q"]).quiet)

    def test_precedence_equals_before_flag(self):  # E8: `-a=b` as a flag holds both faults; the `=` is named
        with self.assertRaises(result.OptionStringHoldsEquals):
            _GateParser(prog="p").add_argument("-a=b", action="store_true")

    def test_refused_strings_are_not_argv_text(self):  # K2: the message shows the option string with 3.9.6's repr rules
        with self.assertRaises(result.ShortFlagWithoutLongAlias) as cm:
            _GateParser(prog="p").add_argument("-\U0001e4f0", action="store_true")
        self.assertEqual(str(cm.exception), "single-dash flag '-\\U0001e4f0' has no long alias (refused: F1 rule E8)")

    def test_the_14_parsers_are_admitted(self):  # C6
        from gates.__main__ import main
        parsers = production_parsers()
        self.assertEqual(sorted(parsers), sorted(p.key for p in PARSERS))
        for key, p in sorted(parsers.items()):
            with self.subTest(key):
                self.assertIs(p.allow_abbrev, True)
                self.assertEqual(sorted(o for a in p._actions for o in a.option_strings if o[1] != "-"), ["-h"])
                self.assertFalse([o for a in p._actions for o in a.option_strings if "=" in o])
                self.assertEqual(p._mutually_exclusive_groups, [])
                self.assertEqual(len(p._action_groups), 2)
        for p in PARSERS:  # each builds and parses through its command with no refusal (the help is a GateError)
            with self.subTest(p.key), contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(p.words + ["--help"]), p.rc())


class Record(argparse.Action):
    """An action that notes that it ran (rows C5: a refusal leaves argv unread, so no action runs)."""
    ran = []

    def __init__(self, option_strings, dest, **kw):
        super().__init__(option_strings, dest, nargs=0, **kw)

    def __call__(self, parser, namespace, values, option_string=None):
        Record.ran.append(option_string)


class Unread:
    """A ``sys.argv`` that fails the test when anything reads it."""

    def __getitem__(self, key):
        raise AssertionError("sys.argv was read")

    def __iter__(self):
        raise AssertionError("sys.argv was read")

    def __len__(self):
        raise AssertionError("sys.argv was read")


class TestRefusalAtParseStart(unittest.TestCase):
    """C5: a configuration that reaches the parser by a route the build hooks do not see is refused when parsing starts."""

    def make(self):
        p = _GateParser(prog="p")
        p.add_argument("--rec", action=Record)
        p.add_argument("-q", "--quiet", action="store_true")
        p.add_argument("--root")
        return p

    def entries(self, p):
        yield "parse_args", lambda: p.parse_args(["--rec"])
        yield "parse_args from sys.argv", lambda: p.parse_args()
        yield "parse_known_args", lambda: p.parse_known_args(["--rec"])
        yield "parse_known_args from sys.argv", lambda: p.parse_known_args()
        yield "parse_intermixed_args", lambda: p.parse_intermixed_args(["--rec"])
        yield "parse_known_intermixed_args", lambda: p.parse_known_intermixed_args(["--rec"])

    def expect_refused(self, mutate, error, make=None):
        for entry in [name for name, _ in self.entries(self.make())]:
            p = (make or self.make)()
            mutate(p)
            call = dict(self.entries(p))[entry]
            del Record.ran[:]
            with self.subTest(entry=entry), mock.patch.object(sys, "argv", Unread()):
                with self.assertRaises(error):
                    call()
                self.assertEqual(Record.ran, [])

    def test_refusal_rechecked_when_parsing_starts(self):  # C5
        def equals_in_option_strings(p):
            p._actions[-1].option_strings.append("--k=v")

        def equals_key(p):
            p._option_string_actions["--k=v"] = p._actions[-1]

        def flag_alias_removed(p):
            quiet = p._option_string_actions["-q"]
            quiet.option_strings.remove("--quiet")
            del p._option_string_actions["--quiet"]

        def flag_registered_only_in_the_registry(p):
            p._option_string_actions["-w"] = argparse._StoreTrueAction(["-w"], "w")  # not in the action list

        def abbrev(p):
            p.allow_abbrev = False

        def foreign_argument_group(p):
            p._action_groups.append(argparse._ArgumentGroup(p._optionals))

        def nested_exclusive_group(p):
            p._mutually_exclusive_groups.append(argparse._MutuallyExclusiveGroup(p._optionals))

        def foreign_exclusive_group(p):
            p._mutually_exclusive_groups.append(argparse._MutuallyExclusiveGroup(p))

        def flag_only_in_the_action_list(p):
            p._actions.append(argparse._StoreTrueAction(["-w"], "w"))  # not in the registry

        def group_of_another_parser(p):
            p._action_groups.append(result._GateArgumentGroup(_GateParser(prog="other")))

        def exclusive_group_of_another_parser(p):
            p._mutually_exclusive_groups.append(result._GateExclusiveGroup(_GateParser(prog="other")))

        for name, mutate, error in (
                ("zero-argument flag only in the action list", flag_only_in_the_action_list,
                 result.ShortFlagWithoutLongAlias),
                ("group made by another parser", group_of_another_parser, result.NestedGroup),
                ("exclusive group made by another parser", exclusive_group_of_another_parser, result.NestedGroup),
                ("equals in option_strings", equals_in_option_strings, result.OptionStringHoldsEquals),
                ("equals as a registered key", equals_key, result.OptionStringHoldsEquals),
                ("alias removed", flag_alias_removed, result.ShortFlagWithoutLongAlias),
                ("zero-argument flag only in the registry", flag_registered_only_in_the_registry,
                 result.ShortFlagWithoutLongAlias),
                ("allow_abbrev", abbrev, result.AbbrevDisabled),
                ("group not made by the parser", foreign_argument_group, result.NestedGroup),
                ("exclusive group of a group", nested_exclusive_group, result.NestedGroup),
                ("exclusive group not made by the parser", foreign_exclusive_group, result.NestedGroup)):
            with self.subTest(name):
                self.expect_refused(mutate, error)

    def test_refusal_rechecked_in_a_subparser_before_any_action_runs(self):  # C5: the top parser reads no argv first
        def make():
            p = self.make()
            p.add_subparsers(dest="sub").add_parser("s")
            return p

        def sub(p):
            return [a for a in p._actions if isinstance(a, argparse._SubParsersAction)][0].choices["s"]

        for name, mutate, error in (("allow_abbrev", lambda p: setattr(sub(p), "allow_abbrev", False), result.AbbrevDisabled),
                                    ("equals", lambda p: sub(p)._actions[0].option_strings.append("--a=b"),
                                     result.OptionStringHoldsEquals),  # the subparser's `-h/--help`
                                    ("group", lambda p: sub(p)._action_groups.append(argparse._ArgumentGroup(sub(p))),
                                     result.NestedGroup)):
            with self.subTest(name):
                p = make()
                mutate(p)
                del Record.ran[:]
                with self.assertRaises(error):
                    p.parse_args(["--rec", "s"])
                self.assertEqual(Record.ran, [])

    def test_refusal_at_build_leaves_no_action_to_run(self):  # C5 control: an admitted parser runs its action
        p = self.make()
        del Record.ran[:]
        p.parse_args(["--rec"])
        self.assertEqual(Record.ran, ["--rec"])

    def test_parse_start_check_ends_on_a_parser_that_is_its_own_subparser(self):  # C5: the walk of the subparsers
        p = self.make()
        subs = p.add_subparsers(dest="sub")
        subs.add_parser("s")
        subs.choices["again"] = p  # a cycle: without a record of the parsers seen the walk would never end
        del Record.ran[:]
        p.parse_args(["--rec"])
        self.assertEqual(Record.ran, ["--rec"])


class TestDoubleDashValue(CommandLineCase):
    """Rule E9: `--` given as an option's value is the text `--` on every interpreter."""

    def test_double_dash_option_value(self):  # D1, K1
        cases = []
        for p in PARSERS:
            if not p.root:
                continue
            ok = valid_ok(p)
            cases.append(("%s --root=--" % p.key, p.words + ok + ["--root=--"], "80", input_fail(p, ROOT_FAIL)))
            for tail in ("-", "---", "--x", "-- "):  # controls: not the text `--`
                cases.append(("%s --root=%s" % (p.key, tail), p.words + ok + ["--root=" + tail], "80", input_fail(p, ROOT_FAIL)))
            cases.append(("%s --root=" % p.key, p.words + ok + ["--root="], "80", input_fail(p, ROOT_NOT_TOP)))
            if p.gate in ("claims", "decisions", "register"):
                cases.append(("%s --base=--" % p.key, p.words + ok + ["--base=--"], "80",
                              input_fail(p, "ref must not start with '-'")))
            m = "--root given more than once"  # the stored `--` is a value like any other: a second occurrence is refused
            cases.append(("%s --root=-- --root=a" % p.key, p.words + ok + ["--root=--", "--root=a"], "80", golden(p, p.key, m, m)))
        for n in (4300, 4301):  # K1: a digit run as the value
            for key in ("index", "check schema", "decisions find"):
                p = BY_KEY[key]
                cases.append(("%s --root=<%d digits>" % (key, n), p.words + ["--root=" + "9" * n], "80", input_fail(p, ROOT_FAIL)))
        self.expect_cases(cases)

    def test_double_dash_option_value_stored_as_text(self):  # D1: every option that takes a value, every parser
        tested = 0
        for key, parser in sorted(production_parsers().items()):
            for action in parser._actions:
                action.required = False
            for action in list(parser._actions):
                if not action.option_strings or action.nargs is not None:
                    continue
                option = action.option_strings[0]
                with self.subTest(key=key, option=option), contextlib.redirect_stderr(io.StringIO()):
                    value = getattr(parser.parse_args([option + "=--"]), action.dest)
                    if isinstance(action, argparse._AppendAction):
                        self.assertEqual(value, ["--"])
                        self.assertIs(type(value[0]), str)
                    else:
                        self.assertEqual(value, "--")
                        self.assertIs(type(value), str)
                tested += 1
        self.assertEqual(tested, TESTED_VALUE_OPTIONS)

    def test_double_dash_separate_token(self):  # D2: unchanged on both (the interpreters agree: the error of 3.9.6)
        cases = []
        for p in PARSERS:
            if not p.root:
                continue
            ok = valid_ok(p)
            m = "argument --root: expected one argument"
            for tail in (["--root", "--"], ["--root", "--", "x"], ["--root", "--", "--"]):
                cases.append(("%s %s" % (p.key, " ".join(tail)), p.words + ok + tail, "80", golden(p, p.key, m, m)))
            if p.gate in ("claims", "decisions", "register"):
                m2 = "argument --base: expected one argument"
                cases.append(("%s --base --" % p.key, p.words + ok + ["--base", "--"], "80", golden(p, p.key, m2, m2)))
        a = BY_KEY["decisions ask"]
        m = "argument --option: expected one argument"
        cases.append(("decisions ask --option --", a.words + ["--class", "c", "--question", "q", "--option", "--",
                                                          "--effect", "lasting", "--by", "b"], "80", golden(a, a.key, m, m)))
        i = BY_KEY["index"]
        m = "unrecognized arguments: -- --"
        cases.append(("index -- --", ["index", "--", "--"], "80", golden(i, "index", m, m)))
        self.expect_cases(cases)

    def parse(self, key, argv):
        parser = production_parsers()[key]
        for action in parser._actions:
            action.required = False
        with contextlib.redirect_stderr(io.StringIO()):
            return vars(parser.parse_args(argv))

    def test_double_dash_as_separator_is_unchanged(self):  # D2, E5: `--` as a separator, for the positionals
        want = {("--", "--"): ["--"], ("x", "--", "--"): ["x", "--"], ("--", "x"): ["x"], ("--",): [], ("x", "--"): ["x"],
                ("--", "--", "--"): ["--", "--"], ("--", "--", "--root=a"): ["--", "--root=a"]}
        for argv, terms in want.items():
            with self.subTest(argv):
                ns = self.parse("decisions find", list(argv))
                self.assertEqual((ns["terms"], ns["root"]), (terms, None))
        ns = self.parse("decisions find", ["--root=--", "--", "--"])  # the explicit value and the separator side by side
        self.assertEqual((ns["terms"], ns["root"]), (["--"], "--"))
        ns = self.parse("decisions decide", ["ID", "--answer=--"])
        self.assertEqual((ns["id"], ns["answer"]), ("ID", "--"))

    def test_double_dash_short_option_value(self):  # D3: `-o--`, `-o=--`, `-o --` of an admitted `-o/--opt`
        def number(s):
            if s == "--":
                raise ValueError(s)
            return s

        def parser(**kw):
            p = _GateParser(prog="p")
            p.add_argument("-o", "--opt", **kw)
            return p

        def run(p, argv):
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                try:
                    return vars(p.parse_args(argv))
                except GateError as e:
                    return str(e)

        for argv in (["-o--"], ["-o=--"], ["--opt=--"]):
            with self.subTest(argv):
                self.assertEqual(run(parser(), argv), {"opt": "--"})
                self.assertEqual(run(parser(choices=["a", "--"]), argv), {"opt": "--"})
                self.assertEqual(run(parser(type=number), argv),
                                 "invalid arguments: argument -o/--opt: invalid number value: '--'")
                self.assertEqual(run(parser(choices=["a", "b"]), argv),
                                 "invalid arguments: argument -o/--opt: invalid choice: '--' (choose from 'a', 'b')")
        # the separate token is no value on either interpreter: 3.9.6's error
        for argv in (["-o", "--"], ["--opt", "--"], ["-o", "--", "x"], ["--opt", "--", "x"]):
            with self.subTest(argv):
                self.assertEqual(run(parser(), argv), "invalid arguments: argument -o/--opt: expected one argument")
        # the other arities: the text `--` is a value
        p = _GateParser(prog="p")
        p.add_argument("-o", "--opt", nargs="*")
        p.add_argument("-a", "--app", action="append")
        p.add_argument("-m", "--maybe", nargs="?", const="C")
        self.assertEqual(vars(p.parse_args(["-o--"]))["opt"], ["--"])
        self.assertEqual(vars(p.parse_args(["-a--", "--app=--", "-a=b"]))["app"], ["--", "--", "b"])
        self.assertEqual(vars(p.parse_args(["-m--"]))["maybe"], "--")
        self.assertEqual(vars(p.parse_args(["--maybe=--"]))["maybe"], "--")
        q = _GateParser(prog="p")  # a positional beside it still takes the separator as 3.9.6 does
        q.add_argument("x", nargs="*")
        q.add_argument("-o", "--opt")
        ns = q.parse_args(["-o--", "--", "--"])
        self.assertEqual((ns.opt, ns.x), ("--", ["--"]))




if __name__ == "__main__":
    unittest.main()
