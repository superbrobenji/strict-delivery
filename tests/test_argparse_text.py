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
    'run_all': 'usage: run_all [-h] [--root ROOT]\n               [--base BASE]\n',
    'check schema': 'usage: schema [-h] [--root ROOT]\n',
    'check cites': 'usage: cites [-h] [--root ROOT]\n',
    'check claims': 'usage: claims [-h] [--root ROOT]\n              [--base BASE]\n',
    'check decisions': 'usage: decisions [-h] [--root ROOT]\n                 [--base BASE]\n',
    'check register': 'usage: register [-h] [--root ROOT]\n                [--base BASE]\n',
    'check dispatch': 'usage: dispatch [-h] [--root ROOT]\n                [--prompts PROMPTS]\n                [--input INPUT]\n',
    'index': 'usage: index [-h] [--root ROOT]\n',
    'decisions ask': 'usage: decisions ask [-h]\n                     [--root ROOT]\n                     --class CLS\n                     --question\n                     QUESTION --option\n                     OPTION\n                     [--topic TOPIC]\n                     [--applies-to APPLIES_TO]\n                     --effect EFFECT\n                     [--supersedes SUPERSEDES]\n                     --by BY\n                     [--plan PLAN]\n                     [--program PROGRAM]\n                     [--stream STREAM]\n                     [--overrides OVERRIDES]\n                     [--recommend RECOMMEND]\n                     [--source SOURCE]\n',
    'decisions decide': 'usage: decisions decide [-h]\n                        [--root ROOT]\n                        --answer\n                        ANSWER\n                        [--rule RULE]\n                        [--landed-in LANDED_IN]\n                        ID\n',
    'decisions withdraw': 'usage: decisions withdraw [-h]\n                          [--root ROOT]\n                          --reason\n                          REASON\n                          ID\n',
    'decisions batch': 'usage: decisions batch [-h]\n                       [--root ROOT]\n                       [--since SINCE]\n                       [--answered]\n                       [--source SOURCE]\n                       [--date DATE]\n',
    'decisions find': 'usage: decisions find [-h]\n                      [--root ROOT]\n                      [--path PATH]\n                      [--topic TOPIC]\n                      [--all]\n                      [TERM ...]\n',
    'findings': 'usage: findings [-h] {new,move} ...\n',
    'findings new': 'usage: findings new [-h] --source\n                    SOURCE --severity\n                    SEVERITY\n                    --owner-kind\n                    OWNER_KIND --by BY\n                    --class CLASS_\n                    [--plan PLAN]\n                    [--task TASK]\n                    [--number NUMBER]\n                    [--parent PARENT]\n                    [--root ROOT]\n                    [--review-round REVIEW_ROUND]\n                    [--caused-by-change CAUSED_BY_CHANGE]\n                    [--dimension DIMENSION]\n                    [--cite CITE]\n',
    'findings move': 'usage: findings move [-h] --to TO --by\n                     BY\n                     [--ruling RULING]\n                     [--pin-test PIN_TEST]\n                     [--pin-transcript PIN_TRANSCRIPT]\n                     [--resolved-by RESOLVED_BY]\n                     [--root ROOT]\n                     [--evidence EVIDENCE]\n                     id\n',
    'claims': 'usage: claims [-h] {add,verify} ...\n',
    'claims add': 'usage: claims add [-h]\n                  [--document DOCUMENT]\n                  [--text TEXT]\n                  [--cite CITE]\n                  [--direct DIRECT]\n                  [--contradiction CONTRADICTION]\n                  [--by BY]\n                  [--root ROOT]\n',
    'claims verify': 'usage: claims verify [-h] [--by BY]\n                     [--root ROOT]\n                     [ID ...]\n',
}
USAGE_80 = {
    'run_all': 'usage: run_all [-h] [--root ROOT] [--base BASE]\n',
    'check schema': 'usage: schema [-h] [--root ROOT]\n',
    'check cites': 'usage: cites [-h] [--root ROOT]\n',
    'check claims': 'usage: claims [-h] [--root ROOT] [--base BASE]\n',
    'check decisions': 'usage: decisions [-h] [--root ROOT] [--base BASE]\n',
    'check register': 'usage: register [-h] [--root ROOT] [--base BASE]\n',
    'check dispatch': 'usage: dispatch [-h] [--root ROOT] [--prompts PROMPTS] [--input INPUT]\n',
    'index': 'usage: index [-h] [--root ROOT]\n',
    'decisions ask': 'usage: decisions ask [-h] [--root ROOT] --class CLS --question QUESTION\n                     --option OPTION [--topic TOPIC] [--applies-to APPLIES_TO]\n                     --effect EFFECT [--supersedes SUPERSEDES] --by BY\n                     [--plan PLAN] [--program PROGRAM] [--stream STREAM]\n                     [--overrides OVERRIDES] [--recommend RECOMMEND]\n                     [--source SOURCE]\n',
    'decisions decide': 'usage: decisions decide [-h] [--root ROOT] --answer ANSWER [--rule RULE]\n                        [--landed-in LANDED_IN]\n                        ID\n',
    'decisions withdraw': 'usage: decisions withdraw [-h] [--root ROOT] --reason REASON ID\n',
    'decisions batch': 'usage: decisions batch [-h] [--root ROOT] [--since SINCE] [--answered]\n                       [--source SOURCE] [--date DATE]\n',
    'decisions find': 'usage: decisions find [-h] [--root ROOT] [--path PATH] [--topic TOPIC] [--all]\n                      [TERM ...]\n',
    'findings': 'usage: findings [-h] {new,move} ...\n',
    'findings new': 'usage: findings new [-h] --source SOURCE --severity SEVERITY --owner-kind\n                    OWNER_KIND --by BY --class CLASS_ [--plan PLAN]\n                    [--task TASK] [--number NUMBER] [--parent PARENT]\n                    [--root ROOT] [--review-round REVIEW_ROUND]\n                    [--caused-by-change CAUSED_BY_CHANGE]\n                    [--dimension DIMENSION] [--cite CITE]\n',
    'findings move': 'usage: findings move [-h] --to TO --by BY [--ruling RULING]\n                     [--pin-test PIN_TEST] [--pin-transcript PIN_TRANSCRIPT]\n                     [--resolved-by RESOLVED_BY] [--root ROOT]\n                     [--evidence EVIDENCE]\n                     id\n',
    'claims': 'usage: claims [-h] {add,verify} ...\n',
    'claims add': 'usage: claims add [-h] [--document DOCUMENT] [--text TEXT] [--cite CITE]\n                  [--direct DIRECT] [--contradiction CONTRADICTION] [--by BY]\n                  [--root ROOT]\n',
    'claims verify': 'usage: claims verify [-h] [--by BY] [--root ROOT] [ID ...]\n',
}
USAGE_200 = {
    'run_all': 'usage: run_all [-h] [--root ROOT] [--base BASE]\n',
    'check schema': 'usage: schema [-h] [--root ROOT]\n',
    'check cites': 'usage: cites [-h] [--root ROOT]\n',
    'check claims': 'usage: claims [-h] [--root ROOT] [--base BASE]\n',
    'check decisions': 'usage: decisions [-h] [--root ROOT] [--base BASE]\n',
    'check register': 'usage: register [-h] [--root ROOT] [--base BASE]\n',
    'check dispatch': 'usage: dispatch [-h] [--root ROOT] [--prompts PROMPTS] [--input INPUT]\n',
    'index': 'usage: index [-h] [--root ROOT]\n',
    'decisions ask': 'usage: decisions ask [-h] [--root ROOT] --class CLS --question QUESTION --option OPTION [--topic TOPIC] [--applies-to APPLIES_TO] --effect EFFECT [--supersedes SUPERSEDES] --by BY [--plan PLAN]\n                     [--program PROGRAM] [--stream STREAM] [--overrides OVERRIDES] [--recommend RECOMMEND] [--source SOURCE]\n',
    'decisions decide': 'usage: decisions decide [-h] [--root ROOT] --answer ANSWER [--rule RULE] [--landed-in LANDED_IN] ID\n',
    'decisions withdraw': 'usage: decisions withdraw [-h] [--root ROOT] --reason REASON ID\n',
    'decisions batch': 'usage: decisions batch [-h] [--root ROOT] [--since SINCE] [--answered] [--source SOURCE] [--date DATE]\n',
    'decisions find': 'usage: decisions find [-h] [--root ROOT] [--path PATH] [--topic TOPIC] [--all] [TERM ...]\n',
    'findings': 'usage: findings [-h] {new,move} ...\n',
    'findings new': 'usage: findings new [-h] --source SOURCE --severity SEVERITY --owner-kind OWNER_KIND --by BY --class CLASS_ [--plan PLAN] [--task TASK] [--number NUMBER] [--parent PARENT] [--root ROOT]\n                    [--review-round REVIEW_ROUND] [--caused-by-change CAUSED_BY_CHANGE] [--dimension DIMENSION] [--cite CITE]\n',
    'findings move': 'usage: findings move [-h] --to TO --by BY [--ruling RULING] [--pin-test PIN_TEST] [--pin-transcript PIN_TRANSCRIPT] [--resolved-by RESOLVED_BY] [--root ROOT] [--evidence EVIDENCE] id\n',
    'claims': 'usage: claims [-h] {add,verify} ...\n',
    'claims add': 'usage: claims add [-h] [--document DOCUMENT] [--text TEXT] [--cite CITE] [--direct DIRECT] [--contradiction CONTRADICTION] [--by BY] [--root ROOT]\n',
    'claims verify': 'usage: claims verify [-h] [--by BY] [--root ROOT] [ID ...]\n',
}
USAGE_20 = {
    'run_all': 'usage: run_all\n       [-h]\n       [--root ROOT]\n       [--base BASE]\n',
    'check schema': 'usage: schema [-h]\n              [--root ROOT]\n',
    'check cites': 'usage: cites [-h]\n             [--root ROOT]\n',
    'check claims': 'usage: claims [-h]\n              [--root ROOT]\n              [--base BASE]\n',
    'check decisions': 'usage: decisions\n       [-h]\n       [--root ROOT]\n       [--base BASE]\n',
    'check register': 'usage: register\n       [-h]\n       [--root ROOT]\n       [--base BASE]\n',
    'check dispatch': 'usage: dispatch\n       [-h]\n       [--root ROOT]\n       [--prompts PROMPTS]\n       [--input INPUT]\n',
    'index': 'usage: index [-h]\n             [--root ROOT]\n',
    'decisions ask': 'usage: decisions ask\n       [-h]\n       [--root ROOT]\n       --class CLS\n       --question\n       QUESTION\n       --option\n       OPTION\n       [--topic TOPIC]\n       [--applies-to APPLIES_TO]\n       --effect\n       EFFECT\n       [--supersedes SUPERSEDES]\n       --by BY\n       [--plan PLAN]\n       [--program PROGRAM]\n       [--stream STREAM]\n       [--overrides OVERRIDES]\n       [--recommend RECOMMEND]\n       [--source SOURCE]\n',
    'decisions decide': 'usage: decisions decide\n       [-h]\n       [--root ROOT]\n       --answer\n       ANSWER\n       [--rule RULE]\n       [--landed-in LANDED_IN]\n       ID\n',
    'decisions withdraw': 'usage: decisions withdraw\n       [-h]\n       [--root ROOT]\n       --reason\n       REASON\n       ID\n',
    'decisions batch': 'usage: decisions batch\n       [-h]\n       [--root ROOT]\n       [--since SINCE]\n       [--answered]\n       [--source SOURCE]\n       [--date DATE]\n',
    'decisions find': 'usage: decisions find\n       [-h]\n       [--root ROOT]\n       [--path PATH]\n       [--topic TOPIC]\n       [--all]\n       [TERM ...]\n',
    'findings': 'usage: findings\n       [-h]\n       {new,move}\n       ...\n',
    'findings new': 'usage: findings new\n       [-h]\n       --source\n       SOURCE\n       --severity\n       SEVERITY\n       --owner-kind\n       OWNER_KIND\n       --by BY\n       --class\n       CLASS_\n       [--plan PLAN]\n       [--task TASK]\n       [--number NUMBER]\n       [--parent PARENT]\n       [--root ROOT]\n       [--review-round REVIEW_ROUND]\n       [--caused-by-change CAUSED_BY_CHANGE]\n       [--dimension DIMENSION]\n       [--cite CITE]\n',
    'findings move': 'usage: findings move\n       [-h] --to\n       TO --by BY\n       [--ruling RULING]\n       [--pin-test PIN_TEST]\n       [--pin-transcript PIN_TRANSCRIPT]\n       [--resolved-by RESOLVED_BY]\n       [--root ROOT]\n       [--evidence EVIDENCE]\n       id\n',
    'claims': 'usage: claims [-h]\n              {add,verify}\n              ...\n',
    'claims add': 'usage: claims add\n       [-h]\n       [--document DOCUMENT]\n       [--text TEXT]\n       [--cite CITE]\n       [--direct DIRECT]\n       [--contradiction CONTRADICTION]\n       [--by BY]\n       [--root ROOT]\n',
    'claims verify': 'usage: claims verify\n       [-h]\n       [--by BY]\n       [--root ROOT]\n       [ID ...]\n',
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
    (22, 'findings new'): 'usage: findings new\n       [-h] --source\n       SOURCE\n       --severity\n       SEVERITY\n       --owner-kind\n       OWNER_KIND\n       --by BY\n       --class\n       CLASS_\n       [--plan PLAN]\n       [--task TASK]\n       [--number NUMBER]\n       [--parent PARENT]\n       [--root ROOT]\n       [--review-round REVIEW_ROUND]\n       [--caused-by-change CAUSED_BY_CHANGE]\n       [--dimension DIMENSION]\n       [--cite CITE]\n',
    (27, 'decisions ask'): 'usage: decisions ask\n       [-h] [--root ROOT]\n       --class CLS\n       --question\n       QUESTION --option\n       OPTION\n       [--topic TOPIC]\n       [--applies-to APPLIES_TO]\n       --effect EFFECT\n       [--supersedes SUPERSEDES]\n       --by BY\n       [--plan PLAN]\n       [--program PROGRAM]\n       [--stream STREAM]\n       [--overrides OVERRIDES]\n       [--recommend RECOMMEND]\n       [--source SOURCE]\n',
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
    def __init__(self, key, words, valid, errkey=None, positional_extras=True, root=True, gate=None):
        self.key, self.words, self.valid = key, words, valid
        self.errkey = errkey or key  # the parser whose error() reports an unrecognized argument
        # `run_all` reports like a gate (a FAIL line on stdout, exit 1) though it is no `check` subcommand
        self.gate = gate or (words[1] if words[0] == "check" else None)
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
    P("check dispatch", ["check", "dispatch"], ["--input", "d.json"]),
    P("run_all", ["run_all"], [], gate="run_all"),
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

    def test_negative_number_digits_assigned_after_unicode_13(self):  # F-2, E7, R2-4 (M11 revised): all 16 parsers
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
                                  input_fail(p, root_fail(p))))
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

    def refused(self, error, call):
        """``call()`` raises exactly ``error`` (rule E10: a named ParserRefused subclass) with the E10 message tail."""
        with self.assertRaises(error) as cm:
            call()
        self.assertIs(type(cm.exception), error)
        self.assertTrue(str(cm.exception).endswith(" (refused: F1 rule E10)"), str(cm.exception))
        return str(cm.exception)

    def test_invalid_type_value(self):  # M2 (row A6: `type=` is refused, so no converter message is reachable)
        def number(s):
            raise ValueError(s)

        self.refused(result.ArgumentOptionRefused, lambda: _GateParser(prog="p").add_argument("--n", type=number))
        self.refused(result.ArgumentOptionRefused, lambda: _GateParser(prog="p").add_argument("--n", type=str))

    def test_invalid_type_value_converter_without_name(self):  # M2: refused (A6), named by its keyword
        class Conv:
            def __call__(self, s):
                raise ValueError(s)

        m = self.refused(result.ArgumentOptionRefused, lambda: _GateParser(prog="p").add_argument("--n", type=Conv()))
        self.assertIn("type", m)
        self.assertNotIn("\u2c2f", m)  # no argv text reaches a refusal: it is raised at the build call

    def test_invalid_type_value_type_error(self):  # M2: refused (A6)
        self.refused(result.ArgumentOptionRefused, lambda: _GateParser(prog="p").add_argument("--n", type=int))

    def test_argument_type_error_message_passes_through(self):  # refused (A6)
        def number(s):
            raise argparse.ArgumentTypeError("not a number")

        self.refused(result.ArgumentOptionRefused, lambda: _GateParser(prog="p").add_argument("--n", type=number))

    def test_invalid_choice_non_str_values(self):  # refused (A6: `type=` and `choices=`)
        self.refused(result.ArgumentOptionRefused,
                     lambda: _GateParser(prog="p").add_argument("--n", type=int, choices=(1, 2)))
        self.refused(result.ArgumentOptionRefused, lambda: _GateParser(prog="p").add_argument("--n", choices=("a",)))

    def test_type_not_callable(self):  # refused (A6)
        self.refused(result.ArgumentOptionRefused, lambda: _GateParser(prog="p").add_argument("--n", type=int))

    def raising_once(self, const):
        """An admitted parser whose `_Once` option `--x` raises ``ArgumentError(action, const)`` when it runs: the
        action class stays the exact `_Once` (row A3), only its call is patched for the test."""
        p = _GateParser(prog="p")
        p.add_argument("--x", action=result._Once)

        def call(self, parser, namespace, values, option_string=None):
            raise argparse.ArgumentError(self, const)

        return p, mock.patch.object(result._Once, "__call__", call)

    def test_ignored_explicit_argument_rewrite_only_for_argparse_text(self):  # E2: the message is rebuilt from its literal
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
            p, patch = self.raising_once(const)
            with self.subTest(const), patch:
                self.assertEqual(self.parse(p, ["--x", "v"])[0], "invalid arguments: " + want)

    def test_ignored_explicit_argument_rewrite_with_a_template_tail(self):  # E2: a template with text after %r
        # a translated template may end after the value; the head and the tail both have to match, and the value is
        # the text between them (hand-written: U+2C2F is not printable in Unicode 13.0.0, so R escapes it)
        head = "ignored explicit argument "
        for const, want in (
            (head + "'\u2c2f'!", "argument --x: ignored explicit argument '\\u2c2f'!"),
            (head + "'\u2c2f'?", "argument --x: ignored explicit argument '\u2c2f'?"),  # other tail: untouched
            (head + "'\u2c2f'", "argument --x: ignored explicit argument '\u2c2f'"),  # no tail: untouched
        ):
            p, patch = self.raising_once(const)
            with self.subTest(const), patch, mock.patch.object(result, "_IGNORED", head + "%r!"):
                self.assertEqual(self.parse(p, ["--x", "v"])[0], "invalid arguments: " + want)

    def test_leading_double_dash_scope(self):  # E5 needs a positional before the subparsers action: refused (A5)
        p = _GateParser(prog="p")
        p.add_argument("name")
        self.refused(result.PositionalRefused, lambda: p.add_subparsers(dest="sub"))

    def test_short_flag_without_long_alias(self):  # C4 keeps firing first (E8); `-q/--quiet` is now refused too (A2)
        p = _GateParser(prog="p")
        with self.assertRaises(result.ShortFlagWithoutLongAlias):  # refused, so E3 never meets a flag it cannot route
            p.add_argument("-q", action="store_true")
        self.refused(result.OptionStringRefused, lambda: p.add_argument("-q", "--quiet", action="store_true"))

    def test_single_dash_option_with_argument_untouched(self):  # a single-dash value option is refused (A2, M6)
        for strings in (("-x", "--xx"), ("--xx", "-x"), ("-x",)):
            with self.subTest(strings):
                self.refused(result.OptionStringRefused, lambda: _GateParser(prog="p").add_argument(*strings))

    def test_single_dash_flag_with_long_alias(self):  # E3 now reaches `-h` only (A2): the -q/-v/-x parser is refused
        for strings in (("-q", "--quiet"), ("--quiet", "-q"), ("-v", "--verbose"), ("-x", "--ex")):
            with self.subTest(strings):
                self.refused(result.OptionStringRefused,
                             lambda: _GateParser(prog="p").add_argument(*strings, action="store_true"))
        # E3 over the one admitted single-dash flag, `-h/--help` of add_help=True (hand-written from E3)
        p = _GateParser(prog="p")
        p.add_argument("--quiet", action="store_true")
        for arg, want in (("-ha", "'a'"), ("-hqa", "'qa'"), ("-h=", "''"), ("-hⰯ", "'\\u2c2f'")):
            with self.subTest(arg):
                self.assertEqual(self.parse(p, [arg])[0],
                                 "invalid arguments: argument -h/--help: ignored explicit argument " + want)

    def test_single_dash_flag_without_long_alias_is_refused(self):  # C4 (was: ..._keeps_interpreter_handling for `-x`)
        with self.assertRaises(result.ShortFlagWithoutLongAlias):
            _GateParser(prog="p").add_argument("-x", action="store_true")
        self.refused(result.OptionStringRefused,
                     lambda: _GateParser(prog="p").add_argument("-x", "--ex", dest="x", action="store_true"))

    def test_ambiguous_option_is_found_when_scanned(self):  # decision 1: 3.9.6's order on every interpreter
        def parser():
            p = _GateParser(prog="p")
            p.add_argument("--root")
            p.add_argument("--rule")
            return p

        want = "invalid arguments: ambiguous option: --r=a could match --root, --rule"
        self.assertEqual(self.parse(parser(), ["--root", "--r=a"])[0], want)
        self.assertEqual(self.parse(parser(), ["--r=a", "--root"])[0], want)

    def test_invalid_choice_non_str_value_uses_repr(self):  # refused (A6: `type=`, `choices=`)
        self.refused(result.ArgumentOptionRefused, lambda: _GateParser(prog="p").add_argument("--n", type=repr))

    def test_usage_formatter_indent(self):  # E4: text_width is the width less the indent; literals from native 3.9.6
        # (plain argparse.ArgumentParser on /usr/bin/python3 3.9.6, COLUMNS=30, measured 2026-11-17: scratch measure.py)
        with mock.patch.dict(os.environ, {"COLUMNS": "30"}):
            p = _GateParser(prog="p")
            for name in ("alpha", "beta", "gamma"):
                p.add_argument("--" + name, metavar=name[0].upper())
            want = {0: "usage: p [-h] [--alpha A]\n         [--beta B]\n         [--gamma G]\n\n",
                    4: "usage: p [-h]\n         [--alpha A]\n         [--beta B]\n         [--gamma G]\n\n",
                    10: "usage: p [-h]\n         [--alpha A]\n         [--beta B]\n         [--gamma G]\n\n"}
            for indent, text in want.items():
                f = p._get_formatter()
                f._current_indent = indent
                with self.subTest(indent):
                    self.assertEqual(f._format_usage(None, p._actions, p._mutually_exclusive_groups, "usage: "), text)

    def test_formatter_class_default_and_explicit(self):  # E4; an explicit formatter_class is refused (A1)
        self.assertEqual(_GateParser(prog="p").formatter_class.__name__, "_UsageFormatter")
        for value in (argparse.RawTextHelpFormatter, argparse.HelpFormatter, _GateParser(prog="p").formatter_class):
            with self.subTest(value.__name__):
                self.refused(result.ParserOptionRefused, lambda: _GateParser(prog="p", formatter_class=value))
        # the registered TypeError (formatter_class as a sixth positional) is refused by name too
        self.refused(result.ParserOptionRefused,
                     lambda: _GateParser("p", None, None, None, [], argparse.HelpFormatter))

    def test_usage_special_forms(self):  # E4: no arguments and a custom usage are refused (A1)
        self.refused(result.ParserOptionRefused, lambda: _GateParser(prog="p", add_help=False))
        self.refused(result.ParserOptionRefused, lambda: _GateParser(prog="p", usage="%(prog)s custom"))

    def test_usage_positionals_only_and_groups(self):  # E4 over the admitted shapes; literals from native 3.9.6 argparse
        # (plain argparse.ArgumentParser, /usr/bin/python3 3.9.6, COLUMNS=20/30, measured 2026-11-17: scratch measure.py)
        with mock.patch.dict(os.environ, {"COLUMNS": "20"}):
            p = _GateParser(prog="p")
            p.add_argument("a" * 14, nargs="*")
            self.assertEqual(p.format_usage(), "usage: p [-h]\n         [aaaaaaaaaaaaaa ...]\n")
        with mock.patch.dict(os.environ, {"COLUMNS": "30"}):
            q = _GateParser(prog="q")
            q.add_argument("--alpha", metavar="A", required=True)
            q.add_argument("--beta", metavar="B")
            q.add_argument("gamma", nargs="*", metavar="G")
            self.assertEqual(q.format_usage(), "usage: q [-h] --alpha A\n         [--beta B]\n         [G ...]\n")
        # the old shapes are refused: two positionals (A5), a group (A8)
        r = _GateParser(prog="r")
        r.add_argument("a")
        self.refused(result.PositionalRefused, lambda: r.add_argument("b"))
        self.assertRaises(result.GroupRefused, _GateParser(prog="q").add_mutually_exclusive_group, required=True)

    def test_choices_in_declared_order(self):  # E2: `choices=` is refused (A6); the subparser names keep E2 (M1)
        self.refused(result.ArgumentOptionRefused, lambda: _GateParser(prog="p").add_argument("x", choices=["b", "a"]))
        p = _GateParser(prog="p")
        subs = p.add_subparsers(dest="sub")
        for name in ("b", "c", "a"):
            subs.add_parser(name)
        self.assertEqual(self.parse(p, ["Ⱟ"])[0],
                         "invalid arguments: argument sub: invalid choice: '\\u2c2f' (choose from 'b', 'c', 'a')")

    def test_repr_str_subclass(self):  # T9: a str subclass in a choices list is refused (A6), and as a subparser name (A7)
        class Liar(str):
            def __repr__(self):
                return "LIE-REPR"

            def __str__(self):
                return "LIE-STR"

        self.refused(result.ArgumentOptionRefused,
                     lambda: _GateParser(prog="p").add_argument("x", choices=[Liar("ab")]))
        self.refused(result.SubparsersRefused,
                     lambda: _GateParser(prog="p").add_subparsers(dest="sub").add_parser(Liar("ab")))

    def test_skeleton_base_exception_group(self):  # K3, KA3: through an admitted `_Once` whose call raises
        class Boom(BaseException):
            pass

        excs = [Boom("b")]
        group = getattr(builtins, "BaseExceptionGroup", None)  # absent on 3.9: only the plain subclass is run there
        if group is not None:
            excs.append(group("g", [KeyboardInterrupt()]))
        for exc in excs:
            p = _GateParser(prog="p")
            p.add_argument("--x", action=result._Once)

            def call(self, parser, namespace, values, option_string=None, exc=exc):
                raise exc

            with self.subTest(type(exc).__name__), contextlib.redirect_stderr(io.StringIO()), \
                    mock.patch.object(result._Once, "__call__", call):
                with self.assertRaises(type(exc)) as cm:
                    p.parse_args(["--x", "v"])
                self.assertIs(cm.exception, exc)
        self.assertEqual(group is None, sys.version_info < (3, 11))

    def test_equals_after_one_dash_is_no_abbreviation(self):  # F-1, E6: 3.9.6 never prefix-matches the text before `=`
        p = _GateParser(prog="p")
        p.add_argument("--abc", action="store_true")
        for arg in ("-=x", "-=", "-ab=x", "-a=x", "-ab==", "-abc=x"):
            with self.subTest(arg):
                m = "unrecognized arguments: " + arg
                self.assertEqual(self.parse(p, [arg]), ("invalid arguments: " + m, "usage: p [-h] [--abc]\np: error: " + m + "\n"))
        # single-dash option strings are refused (A2), so `-a`, `-abc`, `-` cannot be defined
        for strings in (("-a",), ("-abc", "--abc"), ("-abc",), ("-",)):
            with self.subTest(strings):
                self.assertRaises(result.ParserRefused, _GateParser(prog="p").add_argument, *strings)
        # with a space it is a positional text, as everywhere (the one positional, nargs `*`)
        p = _GateParser(prog="p")
        p.add_argument("x", nargs="*")
        self.assertEqual(p.parse_args(["-= x"]).x, ["-= x"])

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
        subs = p.add_subparsers(dest="sub")
        sub = subs.add_parser("s")
        for owner in (p, p._optionals, p._positionals, sub, sub._optionals, sub._positionals):
            self.assertIs(owner._negative_number_matcher, result._NEGATIVE_NUMBER)

    def test_negative_number_options_defined_with_new_digits(self):  # F-2, E7: such an option is refused (A2)
        for digit in ("\U0001e4f0", "٣", "5"):
            with self.subTest(hex(ord(digit))):
                self.assertRaises(result.ParserRefused, _GateParser(prog="p").add_argument, "-" + digit, "--digit",
                                  action="store_true")
        p = _GateParser(prog="p")  # so no parser has a negative-number-like option: `-1` is the positional's text
        p.add_argument("x", nargs="*")
        p.add_argument("--three", action="store_true")
        self.assertEqual(p._has_negative_number_optionals, [])
        self.assertEqual(p.parse_args(["-1", "-٣"]).x, ["-1", "-٣"])
        self.assertEqual(self.parse(p, ["-\U0001e4f0"])[0], "invalid arguments: unrecognized arguments: -\U0001e4f0")
        self.assertRaises(result.GroupRefused, p.add_argument_group)
        self.assertRaises(result.ParserRefused, p.add_argument, "-\U0001e4f0", "--digit", action="store_true")
        self.assertEqual(p._has_negative_number_optionals, [])

DIGITS_SHA256_39 = "a277bbc39852a47c72cac71ac7f70d50ee2bfbb4cbbf42d9a11ee54f240fcdbe"  # the 650 digits of Unicode 13.0.0 (3.9.6), see test

# SHA-256 of "".join(repr(chr(c)) + "\n" for c in range(0x110000)) in UTF-8, measured on /usr/bin/python3 3.9.6.
REPR_SHA256_39 = "7860d79119580a12183b4b8b15522d4fcdbfbed4155a7f59496bad6c65a96510"


class TestFrozenRepr(unittest.TestCase):
    """E1 through the invalid-choice message of an admitted subparsers action whose one name is ``ab`` (``choices=`` is
    refused, row A6): ``invalid choice: <R> (choose from 'ab')``."""

    def r_of(self, parser, action, value):
        try:
            parser._check_value(action, value)
        except argparse.ArgumentError as e:
            msg = e.message
        else:
            raise AssertionError("no error")
        head, tail = "invalid choice: ", " (choose from 'ab')"
        self.assertTrue(msg.startswith(head) and msg.endswith(tail), msg)
        return msg[len(head):len(msg) - len(tail)]

    def test_frozen_repr_every_code_point(self):  # T8
        p = _GateParser(prog="p")
        action = p.add_subparsers(dest="sub")
        action.add_parser("ab")
        self.assertRaises(result.ArgumentOptionRefused, p.add_argument, "--x", choices=())
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


CLAIMS_ADD_HELP = (USAGE_80["claims add"] + "\noptional arguments:\n  -h, --help            show this help message and "
                   "exit\n  --document DOCUMENT\n  --text TEXT\n  --cite CITE\n  --direct DIRECT\n  --contradiction "
                   "CONTRADICTION\n  --by BY\n  --root ROOT\n")
CLAIMS_VERIFY_HELP = (USAGE_80["claims verify"] + "\npositional arguments:\n  ID\n\noptional arguments:\n  -h, --help"
                      "   show this help message and exit\n  --by BY\n  --root ROOT\n")


class TestClaimsText(CommandLineCase):
    """Task 2c.1 rows R3, M11, X4: the usage, help and error text of ``claims add`` and ``claims verify`` (and the new
    ``decisions ask`` usage, in the dicts above) is the 3.9.6 text on every interpreter, byte for byte. The ``claims``
    parsers are not in PARSERS (their flags are checked by the tool, so the generic rows' valid argv differ); the rows
    that name Unicode argv text, an abbreviated flag and an ambiguous flag are written here."""

    def test_help_text(self):  # R3
        for sub, want in (("add", CLAIMS_ADD_HELP), ("verify", CLAIMS_VERIFY_HELP)):
            with self.subTest(sub=sub):
                rc, out, err = run(["claims", sub, "--help"])
                # help goes to stderr, as the family's. The section title is "optional arguments:" on 3.9 and
                # "options:" on 3.10+ for every gate parser (`index --help` too: an unrelated finding, not frozen by
                # _GateParser, which freezes usage and error text only), so that one word is normalised.
                text = err.decode().replace("\noptions:\n", "\noptional arguments:\n")
                self.assertEqual((rc, out, text), (2, b"", want))

    def test_unrecognized_argument_text(self):  # X4: Unicode argv text in the message
        cases = []
        for t in TEXTS:
            want = (USAGE_80["claims"] + "claims: error: unrecognized arguments: --nonsuch " + t.raw + "\n")
            cases.append(("claims add --nonsuch %s" % t.name, ["claims", "add", "--nonsuch", t.argv()], "80",
                          (2, b"", want.encode("utf-8"))))
        self.expect_cases(cases)

    def test_abbreviated_and_ambiguous_flag_text(self):  # X4
        sub = USAGE_80["claims add"]
        cases = [("abbreviated, no value", ["claims", "add", "--doc"], "80",
                  (2, b"", (sub + "claims add: error: argument --document: expected one argument\n").encode())),
                 ("ambiguous", ["claims", "add", "--c=x"], "80",
                  (2, b"", (sub + "claims add: error: ambiguous option: --c=x could match --cite, "
                            "--contradiction\n").encode())),
                 ("no subcommand", ["claims"], "80",
                  (2, b"", (USAGE_80["claims"] + "claims: error: the following arguments are required: {add,verify}\n")
                   .encode())),
                 ("verify extra positional", ["claims", "verify", "a", "b", "--by", "w"], "80",
                  (2, b"", (USAGE_80["claims"] + "claims: error: unrecognized arguments: b\n").encode()))]
        for t in TEXTS[:5]:
            cases.append(("ambiguous --c=%s" % t.name, ["claims", "add", b"--c=" + t.argv()], "80",
                          (2, b"", (sub + "claims add: error: ambiguous option: --c=" + t.raw
                                    + " could match --cite, --contradiction\n").encode("utf-8"))))
        for cols in ("20", "40", "200"):
            cases.append(("usage wrap %s" % cols, ["claims", "add", "--doc"], cols,
                          (2, b"", (USAGE[cols]["claims add"]
                                    + "claims add: error: argument --document: expected one argument\n").encode())))
            cases.append(("verify usage wrap %s" % cols, ["claims", "verify", "--by"], cols,
                          (2, b"", (USAGE[cols]["claims verify"]
                                    + "claims verify: error: argument --by: expected one argument\n").encode())))
        self.expect_cases(cases)


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
            ("gates/gate_checkpoint.py", "gate_args"), ("gates/gate_cites.py", "gate_args"), ("gates/gate_claims.py", "gate_args"),
            ("gates/gate_cleanup.py", "gate_args"), ("gates/gate_context.py", "gate_args"),
            ("gates/gate_decisions.py", "gate_args"),
            ("gates/gate_dispatch.py", "gate_args"),  # Task 2c.3 (after F1): `--root`, `--prompts`, `--input`
            ("gates/gate_evidence.py", "gate_args"),  # Task 6E.2
            ("gates/gate_register.py", "gate_args"),
            ("gates/gate_schema.py", "gate_args"),
            ("gates/gate_streams.py", "gate_args"),
            # inside _GateParser itself (E10): the registry snapshot of a plain parser that never parses (its action
            # names are the base the allowlist compares with), and the two super() calls of the build hooks
            ("gates/lib/result.py", "ArgumentParser"), ("gates/lib/result.py", "_GateParser"),
            ("gates/lib/result.py", "add_parser"), ("gates/lib/result.py", "add_subparsers"),
            # run_all builds its parser through gate_args (Task 2b.1)
            ("gates/run_all.py", "gate_args"),
            ("gates/tools/claims_cli.py", "_GateParser"), ("gates/tools/claims_cli.py", "add_parser"),
            ("gates/tools/claims_cli.py", "add_parser"), ("gates/tools/claims_cli.py", "add_subparsers"),
            ("gates/tools/context_cli.py", "gate_args"),  # Task 5a.1: the context tool, built by gate_args
            ("gates/tools/continue_cli.py", "_GateParser"),  # P4.2: one parser, built by _parser
            ("gates/tools/decisions_cli.py", "gate_args"), ("gates/tools/doctor.py", "gate_args"), ("gates/tools/doctor.py", "gate_args"),
            ("gates/tools/findings_cli.py", "_GateParser"),
            ("gates/tools/findings_cli.py", "add_parser"), ("gates/tools/findings_cli.py", "add_parser"),
            ("gates/tools/findings_cli.py", "add_subparsers"), ("gates/tools/index.py", "gate_args"),
            ("gates/tools/program_cli.py", "_GateParser"),
            ("gates/tools/questions_cli.py", "_GateParser"),
            ("gates/tools/receipt_cli.py", "_GateParser"), ("gates/tools/receipt_cli.py", "add_parser"),
            ("gates/tools/receipt_cli.py", "add_subparsers")])  # P2.2: one parser per subcommand, built by _parser
        self.assertEqual(keywords, [])


# =====================================================================================================================
# Fix round 2 (owner Q-G3-F1C-1 (a), Q-A2-1 (a)): the refusals of rule E8 (rows C1-C6), `--` as an explicit option value
# (rule E9, rows D1-D3), E7 over all 16 parsers (row M11). Every expected value is written by hand: the goldens of the
# command-line rows are 3.9.6's form (measured with the unmodified parsers, 2026-11-16, equal on 3.13 except `=--`, whose
# 3.13 value `--` is rule E9's form).
# =====================================================================================================================
ASK_OK = ["--class", "c", "--question", "q", "--option", "a::b", "--effect", "lasting", "--by", "b", "--recommend", "a"]
NONEXISTENT_ROOT = "/nonexistent-f1-root"
ROOT_FAIL = "git rev-parse --show-toplevel failed (exit 128); run /strict-delivery:init"  # a root that is no directory
RUN_ALL_ROOT_FAIL = "git rev-parse --show-toplevel failed (exit 128)"  # run_all and dispatch add no `; run /strict-delivery:init` hint (dispatch: Task 2c.3)


def root_fail(p):
    return RUN_ALL_ROOT_FAIL if p.key in ("run_all", "check dispatch") else ROOT_FAIL


ROOT_NOT_TOP ="git rev-parse --show-toplevel: root must be the repository top level"  # `--root=` (an empty root)


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


TESTED_VALUE_OPTIONS = 64  # by hand from the parsers' option lists: schema/cites/index 1 each, claims/decisions/register/run_all 2 each, dispatch 3,
# ask 15 (with --overrides, --recommend, --source), decide 4, withdraw 2, batch 4, find 3, findings 0, findings new 14, findings move 8


def production_parsers():
    """{key: parser} of the 16 parsers of row P1 exactly as the commands build them: ``parse_args`` is replaced by a
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

    # The routes E10 admits (row A8 refuses the group routes, A1/A9 the parents routes: test_old_routes_refused).
    ROUTES = ("parser", "subparser")

    def build(self, route, option_strings, **kw):
        """A parser to which ``add_argument(*option_strings, **kw)`` is applied by ``route`` (the call that must refuse)."""
        if route == "parser":
            p = _GateParser(prog="p")
            p.add_argument(*option_strings, **kw)
        elif route == "subparser":
            p = _GateParser(prog="p")
            p.add_subparsers(dest="sub").add_parser("s").add_argument(*option_strings, **kw)
        else:
            raise AssertionError(route)
        return p

    def test_old_routes_refused(self):  # A8, A1/A9: the six routes of round 2 that E10 refuses before add_argument
        def sub():
            return _GateParser(prog="p").add_subparsers(dest="sub").add_parser("s")

        for name, call, error in (
                ("group", lambda: _GateParser(prog="p").add_argument_group("g"), result.GroupRefused),
                ("exclusive group", lambda: _GateParser(prog="p").add_mutually_exclusive_group(), result.GroupRefused),
                ("subparser group", lambda: sub().add_argument_group("g"), result.GroupRefused),
                ("subparser exclusive group", lambda: sub().add_mutually_exclusive_group(), result.GroupRefused),
                ("parents plain", lambda: _GateParser(prog="p", parents=[argparse.ArgumentParser(add_help=False)]),
                 result.ParserOptionRefused),
                ("parents gate", lambda: _GateParser(prog="p", parents=[_GateParser(prog="q")]),
                 result.ParserOptionRefused),
                ("parents empty", lambda: _GateParser(prog="p", parents=[]), result.ParserOptionRefused)):
            with self.subTest(name):
                with self.assertRaises(error) as cm:
                    call()
                self.assertIs(type(cm.exception), error)

    def test_hierarchy(self):  # E8 and E10: one base, a named subclass per refused configuration
        for cls in (result.OptionStringHoldsEquals, result.AbbrevDisabled, result.NestedGroup,
                    result.ShortFlagWithoutLongAlias, result.ParserOptionRefused, result.OptionStringRefused,
                    result.ActionRefused, result.NargsRefused, result.PositionalRefused, result.ArgumentOptionRefused,
                    result.SubparsersRefused, result.GroupRefused, result.ParseEntryRefused):
            self.assertTrue(issubclass(cls, result.ParserRefused), cls)
            self.assertIsNot(cls, result.ParserRefused)
        self.assertTrue(issubclass(result.NestedGroup, result.GroupRefused))
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
        sub = p.add_subparsers(dest="sub").add_parser("s")
        for route_call in (lambda: p.add_argument("-a=b"), lambda: p.add_argument("--a=b"),
                           lambda: sub.add_argument("--x=")):
            with self.assertRaises(result.OptionStringHoldsEquals):
                route_call()
        self.assertEqual(sorted(p._option_string_actions), ["--help", "-h"])
        self.assertEqual(sorted(sub._option_string_actions), ["--help", "-h"])
        q = _GateParser(prog="p")
        with self.assertRaises(result.OptionStringHoldsEquals):
            q.add_argument("--a=b")
        q.add_argument("--ok")
        self.assertEqual(q.parse_args(["--ok", "v"]).ok, "v")

    def test_equals_controls_are_admitted(self):  # C1 control: `--a-b`, `--ab` admitted; `-a` now refused (A2)
        for route in self.ROUTES:
            for option_strings in (("--a-b",), ("--ab",)):
                with self.subTest(route=route, option=option_strings):
                    p = self.build(route, option_strings)
                    self.assertTrue(p._option_string_actions)
            for option_strings in (("-a",), ("-a", "--a-b")):
                with self.subTest(route=route, option=option_strings):
                    self.assertRaises(result.OptionStringRefused, self.build, route, option_strings)
        p = _GateParser(prog="p")
        p.add_argument("--a-b")
        self.assertEqual(p.parse_args(["--a-b", "v"]).a_b, "v")
        self.assertEqual(p.parse_args(["--a-b=v"]).a_b, "v")

    def test_refuse_allow_abbrev_false(self):  # C2 (R2-3 is a refused input)
        with self.assertRaises(result.AbbrevDisabled) as cm:
            _GateParser(prog="p", allow_abbrev=False)
        self.assertEqual(str(cm.exception), "allow_abbrev=False (refused: F1 rule E8)")
        with self.assertRaises(result.AbbrevDisabled):
            _GateParser(prog="p").add_subparsers(dest="sub").add_parser("x", allow_abbrev=False)
        # after the build: refused when parsing starts
        p = _GateParser(prog="p")
        p.add_argument("--root")
        p.allow_abbrev = False
        with self.assertRaises(result.AbbrevDisabled):
            p.parse_args(["--root", "a"])
        top = _GateParser(prog="p")
        sub = top.add_subparsers(dest="sub").add_parser("s")
        sub.allow_abbrev = False
        with self.assertRaises(result.AbbrevDisabled):
            top.parse_args(["s"])
        # controls
        for kw in ({}, {"allow_abbrev": True}):
            p = _GateParser(prog="p", **kw)
            p.add_argument("--root")
            self.assertEqual(p.parse_args(["--ro", "a"]).root, "a")
        # add_parser takes `prog` only (A7): an explicit allow_abbrev=True there is refused as a keyword
        self.assertRaises(result.SubparsersRefused, _GateParser(prog="p").add_subparsers(dest="sub").add_parser, "x",
                          allow_abbrev=True)

    def test_refuse_nested_group(self):  # C3 (R2-2), A8: no group can be made, so no group is ever nested
        owners = (("parser", lambda: _GateParser(prog="p")),
                  ("subparser", lambda: _GateParser(prog="p").add_subparsers(dest="sub").add_parser("s")))
        for where, make in owners:
            for outer in ("_optionals", "_positionals"):  # the two groups argparse makes itself
                for inner, call in (("argument group", lambda g: g.add_argument_group("h")),
                                    ("exclusive group", lambda g: g.add_mutually_exclusive_group())):
                    with self.subTest(where=where, outer=outer, inner=inner):
                        group = getattr(make(), outer)
                        self.assertRaises(result.GroupRefused, call, group)
        p = _GateParser(prog="p")
        q = argparse.ArgumentParser(prog="q", add_help=False)
        q.add_argument_group("h").add_argument("--x")
        with self.assertRaises(result.GroupRefused):
            p._optionals._add_container_actions(q)
        # a post-13.0 digit option in a group is therefore never defined (R2-2)
        with self.assertRaises(result.GroupRefused):
            p.add_argument_group("a").add_argument("-\U0001e4f0", "--digit")

    def test_one_level_of_groups_is_admitted(self):  # C3's control is now refused (A8), at the first level
        for where, make in (("parser", lambda: _GateParser(prog="p")),
                            ("subparser", lambda: _GateParser(prog="p").add_subparsers(dest="sub").add_parser("s"))):
            for kind, group in (("argument group", lambda p: p.add_argument_group("g")),
                                ("exclusive group", lambda p: p.add_mutually_exclusive_group())):
                with self.subTest(where=where, kind=kind):
                    p = make()
                    with self.assertRaises(result.GroupRefused) as cm:
                        group(p)
                    self.assertIs(type(cm.exception), result.GroupRefused)
                    self.assertEqual(len(p._action_groups), 2)
                    self.assertEqual(p._mutually_exclusive_groups, [])

        self.assertRaises(result.ParserRefused, _GateParser(prog="p").add_argument, "-\U0001e4f0", "--digit", action="store_true")

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
                        # E8 keeps firing where it fired (E10), before the action row A3, for every action kind:
                        # one class per value (measured 2026-11-17 on 3.9.6 and 3.13, scratch probe2.py: 80 of 80)
                        with self.assertRaises(result.ParserRefused) as cm:
                            self.build(route, option_strings, **kw)
                        self.assertIs(type(cm.exception), result.ShortFlagWithoutLongAlias)
                        self.assertEqual(str(cm.exception),
                                         "single-dash flag %s has no long alias (refused: F1 rule E8)" % shown)

    def test_short_flag_controls_are_admitted(self):  # C4's controls are refused now (A2, A3, A4); `--quiet` admitted
        for route in self.ROUTES:
            for option_strings, kw, error in (
                    (("-q", "--quiet"), {"action": "store_true"}, result.OptionStringRefused),
                    (("--quiet", "-q"), {"action": "store_true"}, result.OptionStringRefused),
                    (("-q", "-Q", "--quiet"), {"action": "store_true"}, result.OptionStringRefused),
                    (("-r",), {}, result.OptionStringRefused), (("-r", "--root"), {}, result.OptionStringRefused),
                    (("--x",), {"nargs": "?"}, result.NargsRefused),
                    (("--flag",), {"action": argparse.BooleanOptionalAction}, result.ActionRefused),
                    (("--verbose",), {"action": "count"}, result.ActionRefused)):
                with self.subTest(route=route, option=option_strings, kw=sorted(kw)):
                    with self.assertRaises(error) as cm:
                        self.build(route, option_strings, **kw)
                    self.assertIs(type(cm.exception), error)
            for option_strings, kw in ((("--quiet",), {"action": "store_true"}), (("--root",), {})):
                with self.subTest(route=route, option=option_strings):
                    self.build(route, option_strings, **kw)
        p = _GateParser(prog="p")
        p.add_argument("--quiet", action="store_true")
        self.assertTrue(p.parse_args(["--quiet"]).quiet)

    def test_refuse_short_flag_left_without_long_alias_by_conflict_resolution(self):  # `resolve` is refused (A1)
        with self.assertRaises(result.ParserOptionRefused):
            _GateParser(prog="p", conflict_handler="resolve")
        p = _GateParser(prog="p", conflict_handler="error")  # the explicit default is admitted, and a conflict is
        p.add_argument("--quiet", action="store_true")       # argparse's own error, as before
        self.assertRaises(argparse.ArgumentError, p.add_argument, "--quiet", action="store_true")

    def test_precedence_equals_before_flag(self):  # E8: `-a=b` as a flag holds both faults; the `=` is named
        with self.assertRaises(result.OptionStringHoldsEquals):
            _GateParser(prog="p").add_argument("-a=b", action="store_true")

    def test_refused_strings_are_not_argv_text(self):  # K2: the message shows the option string with 3.9.6's repr rules
        with self.assertRaises(result.ShortFlagWithoutLongAlias) as cm:
            _GateParser(prog="p").add_argument("-\U0001e4f0", action="store_true")
        self.assertEqual(str(cm.exception), "single-dash flag '-\\U0001e4f0' has no long alias (refused: F1 rule E8)")

    def test_the_15_parsers_are_admitted(self):  # C6
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


class Record:
    """Notes that an admitted `_Once` action ran (rows C5, A11: a refusal leaves argv unread, so no action runs). A
    custom Action class is refused (A3), so the record is a patch of `_Once.__call__` around each parse."""
    ran = []

    @staticmethod
    def patch():
        def call(self, parser, namespace, values, option_string=None):
            Record.ran.append(option_string)

        return mock.patch.object(result._Once, "__call__", call)


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
        p.add_argument("--rec", action=result._Once)
        p.add_argument("--quiet", action="store_true")
        p.add_argument("--root")
        return p

    def entries(self, p):
        yield "parse_args", lambda: p.parse_args(["--rec", "v"])
        yield "parse_args from sys.argv", lambda: p.parse_args()
        yield "parse_known_args", lambda: p.parse_known_args(["--rec", "v"])
        yield "parse_known_args from sys.argv", lambda: p.parse_known_args()
        yield "parse_intermixed_args", lambda: p.parse_intermixed_args(["--rec", "v"])
        yield "parse_known_intermixed_args", lambda: p.parse_known_intermixed_args(["--rec", "v"])

    def expect_refused(self, mutate, error, make=None):
        """``parse_args(list)`` raises the mutation's own named error; every other entry is refused too (by A10 or by
        the mutation's error, both named), and in no case is argv read or an action run."""
        for entry in [name for name, _ in self.entries(self.make())]:
            p = (make or self.make)()
            mutate(p)
            call = dict(self.entries(p))[entry]
            del Record.ran[:]
            with self.subTest(entry=entry), mock.patch.object(sys, "argv", Unread()), Record.patch():
                with self.assertRaises(error if entry == "parse_args" else result.ParserRefused) as cm:
                    call()
                if entry != "parse_args":
                    self.assertIn(type(cm.exception), (result.ParseEntryRefused, error))
                self.assertEqual(Record.ran, [])

    def test_parse_entries_refused(self):  # A10: every entry but parse_args(list of exact str) is refused unread
        class S(str):
            pass

        for name, call in (("parse_args()", lambda p: p.parse_args()), ("parse_args(None)", lambda p: p.parse_args(None)),
                           ("tuple", lambda p: p.parse_args(("--rec", "v"))),
                           ("str subclass", lambda p: p.parse_args([S("--rec"), "v"])),
                           ("namespace", lambda p: p.parse_args(["--rec", "v"], namespace=argparse.Namespace())),
                           ("parse_known_args", lambda p: p.parse_known_args(["--rec", "v"])),
                           ("parse_intermixed_args", lambda p: p.parse_intermixed_args(["--rec", "v"])),
                           ("parse_known_intermixed_args", lambda p: p.parse_known_intermixed_args(["--rec", "v"])),
                           ("set_defaults", lambda p: p.set_defaults(root="r"))):
            for where in ("parser", "subparser"):
                p = self.make()
                target = p.add_subparsers(dest="sub").add_parser("s") if where == "subparser" else p
                if where == "subparser":
                    target.add_argument("--rec", action=result._Once)
                del Record.ran[:]
                with self.subTest(name, where=where), mock.patch.object(sys, "argv", Unread()), Record.patch():
                    with self.assertRaises(result.ParseEntryRefused) as cm:
                        call(target)
                    self.assertIs(type(cm.exception), result.ParseEntryRefused)
                    self.assertEqual(Record.ran, [])
        p = self.make()  # a non-empty `_defaults` reached by assignment is refused when parsing starts
        p._defaults["root"] = "r"
        self.assertRaises(result.ParseEntryRefused, p.parse_args, ["--root", "a"])
        p = self.make()  # control
        with Record.patch():
            del Record.ran[:]
            self.assertEqual(p.parse_args(["--rec", "v"]).root, None)
            self.assertEqual(Record.ran, ["--rec"])

    def test_refusal_rechecked_when_parsing_starts(self):  # C5
        def equals_in_option_strings(p):
            p._actions[-1].option_strings.append("--k=v")

        def equals_key(p):
            p._option_string_actions["--k=v"] = p._actions[-1]

        def flag_alias_removed(p):  # the help flag's long alias taken away
            help_action = p._option_string_actions["-h"]
            help_action.option_strings.remove("--help")
            del p._option_string_actions["--help"]

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
                ("group made by another parser", group_of_another_parser, result.GroupRefused),
                ("exclusive group made by another parser", exclusive_group_of_another_parser, result.GroupRefused),
                ("equals in option_strings", equals_in_option_strings, result.OptionStringHoldsEquals),
                ("equals as a registered key", equals_key, result.OptionStringHoldsEquals),
                ("alias removed", flag_alias_removed, result.ShortFlagWithoutLongAlias),
                ("zero-argument flag only in the registry", flag_registered_only_in_the_registry,
                 result.ShortFlagWithoutLongAlias),
                ("allow_abbrev", abbrev, result.AbbrevDisabled),
                ("group not made by the parser", foreign_argument_group, result.GroupRefused),
                ("exclusive group of a group", nested_exclusive_group, result.GroupRefused),
                ("exclusive group not made by the parser", foreign_exclusive_group, result.GroupRefused)):
            with self.subTest(name):
                self.expect_refused(mutate, error)

    def test_allowlist_rechecked_when_parsing_starts(self):  # A11: one change after build per row A1-A8, parser and subparser
        def sub_of(p):
            return [a for a in p._actions if isinstance(a, argparse._SubParsersAction)][0]

        def last(p):
            return p._option_string_actions["--root"]

        changes = (
            ("A1 exit_on_error", lambda p: setattr(p, "exit_on_error", False), result.ParserOptionRefused),
            ("A1 prefix_chars", lambda p: setattr(p, "prefix_chars", "+-"), result.ParserOptionRefused),
            ("A1 description", lambda p: setattr(p, "description", "d"), result.ParserOptionRefused),
            ("A1 epilog", lambda p: setattr(p, "epilog", "e"), result.ParserOptionRefused),
            ("A1 usage", lambda p: setattr(p, "usage", "u"), result.ParserOptionRefused),
            ("A1 formatter_class", lambda p: setattr(p, "formatter_class", argparse.HelpFormatter),
             result.ParserOptionRefused),
            ("A1 fromfile_prefix_chars", lambda p: setattr(p, "fromfile_prefix_chars", "@"), result.ParserOptionRefused),
            ("A1 argument_default", lambda p: setattr(p, "argument_default", "x"), result.ParserOptionRefused),
            ("A1 conflict_handler", lambda p: setattr(p, "conflict_handler", "resolve"), result.ParserOptionRefused),
            ("A2 single-dash string", lambda p: last(p).option_strings.append("-r"), result.OptionStringRefused),
            ("A2 upper case key", lambda p: p._option_string_actions.__setitem__("--R", last(p)),
             result.OptionStringRefused),
            ("A3 action class swapped", lambda p: setattr(last(p), "__class__", argparse._StoreFalseAction),
             result.ActionRefused),
            ("A3 registry entry", lambda p: p.register("action", "mine", argparse._StoreAction), result.ActionRefused),
            ("A4 nargs", lambda p: setattr(last(p), "nargs", "+"), result.NargsRefused),
            ("A5 second positional", lambda p: p._actions.append(argparse._StoreAction([], "y")), result.PositionalRefused),
            ("A6 type", lambda p: setattr(last(p), "type", int), result.ArgumentOptionRefused),
            ("A6 choices", lambda p: setattr(last(p), "choices", ["a"]), result.ArgumentOptionRefused),
            ("A6 default", lambda p: setattr(last(p), "default", "d"), result.ArgumentOptionRefused),
            ("A6 metavar", lambda p: setattr(last(p), "metavar", "o p"), result.ArgumentOptionRefused),
            ("A7 parser_class", lambda p: setattr(sub_of(p), "_parser_class", argparse.ArgumentParser),
             result.SubparsersRefused),
            ("A7 choice replaced (N1)", lambda p: sub_of(p).choices.__setitem__("s", argparse.ArgumentParser(prog="s")),
             result.SubparsersRefused),
            ("A7 dest None (M4)", lambda p: setattr(sub_of(p), "dest", None), result.SubparsersRefused),
            ("A7 required not a bool", lambda p: setattr(sub_of(p), "required", 1), result.SubparsersRefused),
            ("A7 option string on the subparsers action", lambda p: sub_of(p).option_strings.append("--x"),
             result.SubparsersRefused),
            ("A7 prog prefix", lambda p: setattr(sub_of(p), "_prog_prefix", "P"), result.SubparsersRefused),
            ("A7 choice name", lambda p: sub_of(p).choices.__setitem__("X", _GateParser(prog="x")),
             result.SubparsersRefused),
            ("A8 group appended", lambda p: p._action_groups.append(argparse._ArgumentGroup(p)), result.GroupRefused),
            ("A8 exclusive group appended", lambda p: p._mutually_exclusive_groups.append(
                argparse._MutuallyExclusiveGroup(p)), result.GroupRefused),
        )

        def make():
            p = _GateParser(prog="p")
            p.add_argument("--rec", action=result._Once)
            p.add_argument("--root")
            p.add_subparsers(dest="sub").add_parser("s").add_argument("--root")
            return p

        for name, change, error in changes:
            for where in ("parser", "subparser"):
                if where == "subparser" and name.startswith(("A5", "A7")):
                    continue  # a subparser holds no subparsers action, and its own positional count is A5's parser row
                p = make()
                target = sub_of(p).choices["s"] if where == "subparser" else p
                if name.startswith("A7"):
                    change(p)
                else:
                    change(target)
                del Record.ran[:]
                with self.subTest(name, where=where), mock.patch.object(sys, "argv", Unread()), Record.patch():
                    with self.assertRaises(error) as cm:
                        p.parse_args(["--rec", "v", "s"])
                    # a group appended after build keeps E8's NestedGroup (a GroupRefused), as it fired before E10
                    self.assertIn(type(cm.exception), (error, result.NestedGroup) if name.startswith("A8") else (error,))
                    self.assertEqual(Record.ran, [])

    def test_state_changes_refused_when_parsing_starts(self):  # A1, A2, A3, A11: changes no build hook sees
        def root(p):
            return p._option_string_actions["--root"]

        def drop_help(p):
            h = p._option_string_actions["-h"]
            p._actions.remove(h)
            p._optionals._group_actions.remove(h)
            del p._option_string_actions["-h"], p._option_string_actions["--help"]

        class Sub(_GateParser):
            pass

        class D(dict):
            pass

        for name, change in (
                ("allow_abbrev not a bool", lambda p: setattr(p, "allow_abbrev", 0)),
                ("help strings reordered", lambda p: setattr(p._option_string_actions["-h"], "option_strings",
                                                             ["--help", "-h"])),
                ("help action removed", drop_help),
                ("option string not registered", lambda p: root(p).option_strings.append("--zz")),
                ("registries a dict subclass", lambda p: setattr(p, "_registries", D(p._registries))),
                ("registry entry replaced", lambda p: p.register("action", "count", argparse._StoreAction))):
            p = _GateParser(prog="p")
            p.add_argument("--root")
            change(p)
            with self.subTest(name), mock.patch.object(sys, "argv", Unread()):
                self.assertRaises(result.ParserRefused, p.parse_args, ["--root", "a"])
        p = Sub(prog="p")  # a subclass of _GateParser is not the parser E10 admits
        p.add_argument("--root")
        self.assertRaises(result.ParserRefused, p.parse_args, ["--root", "a"])

    def test_refused_add_subparsers_leaves_the_parser_unchanged(self):  # A7: refused before argparse sees the call
        for kw in ({"dest": "S"}, {"dest": "s", "metavar": "{a,B}"}, {"dest": "s", "required": 1}):
            with self.subTest(sorted(kw)):
                p = _GateParser(prog="p")
                self.assertRaises(result.SubparsersRefused, p.add_subparsers, **kw)
                self.assertIsNone(p._subparsers)
                p.add_subparsers(dest="sub").add_parser("s")  # so the one admitted call still builds
                self.assertEqual(p.parse_args(["s"]).sub, "s")

    def test_each_state_check_names_its_change(self):  # A1-A8, A11 (fix round 5): exact class and text per check
        """One change after build per parse-start check; each is named by that check's own text (E10's shapes; the
        two E8 group texts keep their E8 tail), before any action runs and with argv unread."""
        e10, e8 = " (refused: F1 rule E10)", " (refused: F1 rule E8)"

        class Raised(Exception):
            pass

        class Evil(str):  # an option string whose methods raise: the check must not call one
            def __contains__(self, x):
                raise Raised()

            def __getitem__(self, key):
                raise Raised()

            def __len__(self):
                raise Raised()

            def __eq__(self, other):
                raise Raised()

            def __hash__(self):
                raise Raised()

        def sub_of(p):
            return [a for a in p._actions if isinstance(a, argparse._SubParsersAction)][0]

        def root(p):
            return p._option_string_actions["--root"]

        def foreign_optionals(p):  # the two-group shape kept, the second group not made by the parser
            g = argparse._ArgumentGroup(p)
            p._action_groups[1] = g
            p._optionals = g

        for name, change, error, text in (
                ("required not a bool", lambda p: setattr(root(p), "required", 1), result.ArgumentOptionRefused,
                 "keyword required=1" + e10),
                ("store_true nargs", lambda p: setattr(p._option_string_actions["--quiet"], "nargs", "?"),
                 result.NargsRefused, "nargs '?'" + e10),
                ("subparsers metavar", lambda p: setattr(sub_of(p), "metavar", "X"), result.SubparsersRefused,
                 "subparsers metavar 'X'" + e10),
                ("subparsers help", lambda p: setattr(sub_of(p), "help", "h"), result.SubparsersRefused,
                 "subparsers help or nargs" + e10),
                ("subparsers choices a copy", lambda p: setattr(sub_of(p), "choices", dict(sub_of(p).choices)),
                 result.SubparsersRefused, "subparsers choices" + e10),
                ("a subparser under two names", lambda p: sub_of(p).choices.__setitem__("t", sub_of(p).choices["s"]),
                 result.SubparsersRefused, "subparser name 't' is an alias" + e10),
                ("prog", lambda p: setattr(p, "prog", "P"), result.ParserOptionRefused, "prog='P'" + e10),
                ("add_help", lambda p: setattr(p, "add_help", False), result.ParserOptionRefused,
                 "attribute add_help=False" + e10),
                ("registered key of a refused shape", lambda p: p._option_string_actions.__setitem__("--R", root(p)),
                 result.OptionStringRefused, "registered option string '--R'" + e10),
                ("registered key of an action not in the parser",
                 lambda p: p._option_string_actions.__setitem__("--zz", argparse._StoreAction(["--zz"], "zz")),
                 result.OptionStringRefused, "registered option string '--zz' without its action" + e10),
                ("registered key its action does not list", lambda p: p._option_string_actions.__setitem__("--yy", root(p)),
                 result.OptionStringRefused, "registered option string '--yy' without its action" + e10),
                ("option_strings a tuple", lambda p: setattr(root(p), "option_strings", ("--root",)),
                 result.OptionStringRefused, "option_strings of an action" + e10),
                ("option string a str subclass", lambda p: root(p).option_strings.append(Evil("--r")),
                 result.OptionStringRefused, "option_strings of an action" + e10),
                ("registry kind", lambda p: p._registries.__setitem__("other", {}), result.ActionRefused,
                 "registry 'other'" + e10),
                ("registry key a str subclass", lambda p: p.register("action", StrSub("mine"), argparse._StoreAction),
                 result.ActionRefused, "registry entry 'mine'" + e10),
                ("registry entry removed", lambda p: p._registries["action"].__delitem__("count"), result.ActionRefused,
                 "registry entries" + e10),
                ("type registry entry replaced", lambda p: p._registries["type"].__setitem__(None, str),
                 result.ActionRefused, "registry entry for type None" + e10),
                ("optionals group not made by the parser", foreign_optionals, result.NestedGroup,
                 "an argument group this parser did not make" + e8),
                ("exclusive group not made by the parser",
                 lambda p: p._mutually_exclusive_groups.append(argparse._MutuallyExclusiveGroup(p)), result.NestedGroup,
                 "an exclusive group this parser did not make" + e8),
                ("a third group made by the parser", lambda p: p._action_groups.append(result._GateArgumentGroup(p)),
                 result.GroupRefused, "an argument group beyond the two argparse makes" + e10),
                ("an exclusive group made by the parser",
                 lambda p: p._mutually_exclusive_groups.append(result._GateExclusiveGroup(p)), result.GroupRefused,
                 "a mutually exclusive group" + e10)):
            p = _GateParser(prog="p")
            p.add_argument("--rec", action=result._Once)
            p.add_argument("--root")
            p.add_argument("--quiet", action="store_true")
            p.add_subparsers(dest="sub").add_parser("s")
            change(p)
            del Record.ran[:]
            with self.subTest(name), mock.patch.object(sys, "argv", Unread()), Record.patch():
                with self.assertRaises(result.ParserRefused) as cm:
                    p.parse_args(["--rec", "v", "s"])
                self.assertIs(type(cm.exception), error)
                self.assertEqual(str(cm.exception), text)
                self.assertEqual(Record.ran, [])

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
                                     result.GroupRefused)):
            with self.subTest(name):
                p = make()
                mutate(p)
                del Record.ran[:]
                with self.assertRaises(error), Record.patch():
                    p.parse_args(["--rec", "v", "s"])
                self.assertEqual(Record.ran, [])

    def test_refusal_at_build_leaves_no_action_to_run(self):  # C5 control: an admitted parser runs its action
        p = self.make()
        del Record.ran[:]
        with Record.patch():
            p.parse_args(["--rec", "v"])
        self.assertEqual(Record.ran, ["--rec"])

    def test_parse_start_check_ends_on_a_parser_that_is_its_own_subparser(self):  # C5, A7: the walk ends, refused
        p = self.make()
        subs = p.add_subparsers(dest="sub")
        subs.add_parser("s")
        subs.choices["again"] = p  # a cycle: a subparser that holds a subparsers action (two levels, A7)
        del Record.ran[:]
        with Record.patch(), self.assertRaises(result.SubparsersRefused):
            p.parse_args(["--rec", "v", "s"])
        self.assertEqual(Record.ran, [])


class TestDoubleDashValue(CommandLineCase):
    """Rule E9: `--` given as an option's value is the text `--` on every interpreter."""

    def test_double_dash_option_value(self):  # D1, K1
        cases = []
        for p in PARSERS:
            if not p.root:
                continue
            ok = valid_ok(p)
            cases.append(("%s --root=--" % p.key, p.words + ok + ["--root=--"], "80", input_fail(p, root_fail(p))))
            for tail in ("-", "---", "--x", "-- "):  # controls: not the text `--`
                cases.append(("%s --root=%s" % (p.key, tail), p.words + ok + ["--root=" + tail], "80", input_fail(p, root_fail(p))))
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

    def test_double_dash_short_option_value(self):  # D3: `-o/--opt` is refused (A2); `--opt=--` of an admitted `--opt`
        for strings in (("-o", "--opt"), ("-o",)):
            with self.subTest(strings), self.assertRaises(result.OptionStringRefused):
                _GateParser(prog="p").add_argument(*strings)
        for kw in ({"type": str}, {"choices": ["a", "--"]}):
            with self.subTest(sorted(kw)), self.assertRaises(result.ArgumentOptionRefused):
                _GateParser(prog="p").add_argument("--opt", **kw)

        def parser():
            p = _GateParser(prog="p")
            p.add_argument("--opt")
            return p

        def run(p, argv):
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                try:
                    return vars(p.parse_args(argv))
                except GateError as e:
                    return str(e)

        self.assertEqual(run(parser(), ["--opt=--"]), {"opt": "--"})
        for argv in (["--opt", "--"], ["--opt", "--", "x"]):  # the separate token is no value: 3.9.6's error
            with self.subTest(argv):
                self.assertEqual(run(parser(), argv), "invalid arguments: argument --opt: expected one argument")
        p = _GateParser(prog="p")
        p.add_argument("--app", action="append")
        p.add_argument("--once", action=result._Once)
        self.assertEqual(vars(p.parse_args(["--app=--", "--app=b", "--once=--"])), {"app": ["--", "b"], "once": "--"})
        q = _GateParser(prog="p")  # the one positional beside it still takes the separator as 3.9.6 does
        q.add_argument("x", nargs="*")
        q.add_argument("--opt")
        ns = q.parse_args(["--opt=--", "--", "--"])
        self.assertEqual((ns.opt, ns.x), ("--", ["--"]))





# =====================================================================================================================
# Fix round 3-4 (owner Q-G3-F1R3-1 (a)): rule E10, the allowlist (rows A1-A13, KA1-KA3). Every expected verdict is the
# named refusal of the row, written by hand from the table; the message tail is E10's ` (refused: F1 rule E10)` and the
# refused value is shown by E1's frozen repr (3.9.6's form, hand-written below).
# =====================================================================================================================
class StrSub(str):
    pass


class TestAllowlist(unittest.TestCase):
    def refused(self, error, call, *args, **kw):
        with self.assertRaises(error) as cm:
            call(*args, **kw)
        self.assertIs(type(cm.exception), error)
        self.assertTrue(str(cm.exception).endswith(" (refused: F1 rule E10)"), str(cm.exception))
        return str(cm.exception)

    def sub(self):
        return _GateParser(prog="p").add_subparsers(dest="sub")

    def test_parser_options_refused(self):  # A1, A9, M5
        plain = argparse.ArgumentParser(prog="q", add_help=False)
        for name, kw in (("add_help", {"add_help": False}), ("exit_on_error", {"exit_on_error": False}),
                         ("prefix_chars", {"prefix_chars": "+"}), ("prefix_chars", {"prefix_chars": "-+"}),
                         ("conflict_handler", {"conflict_handler": "resolve"}), ("parents", {"parents": []}),
                         ("parents", {"parents": [plain]}), ("parents", {"parents": [_GateParser(prog="q")]}),
                         ("formatter_class", {"formatter_class": argparse.HelpFormatter}),
                         ("formatter_class", {"formatter_class": _GateParser(prog="q").formatter_class}),
                         ("usage", {"usage": "u"}), ("description", {"description": "d"}), ("epilog", {"epilog": "e"}),
                         ("fromfile_prefix_chars", {"fromfile_prefix_chars": "@"}),
                         ("argument_default", {"argument_default": "x"}), ("add_help", {"add_help": 1}),
                         ("prog", {"prog": "P"}), ("prog", {"prog": "9x"}), ("prog", {"prog": "\xe9"}),
                         ("prog", {"prog": StrSub("p")}), ("prog", {"prog": None})):
            with self.subTest(name, value=repr(kw[name])[:30]):
                m = self.refused(result.ParserOptionRefused, _GateParser, **dict({"prog": "p"}, **kw))
                self.assertIn(name, m)
        self.refused(result.ParserOptionRefused, _GateParser, "p")  # any positional
        self.refused(result.ParserOptionRefused, _GateParser)  # prog is required: sys.argv is never read
        with mock.patch.object(sys, "argv", Unread()):
            self.refused(result.ParserOptionRefused, _GateParser)
        self.assertRaises(result.ParserRefused, self.sub().add_parser, "x", description="d")  # through add_parser
        self.assertRaises(result.AbbrevDisabled, _GateParser, prog="p", allow_abbrev=False)  # C2 keeps its name

    def test_parser_option_defaults_admitted(self):  # A1 controls: the explicit defaults
        p = _GateParser(prog="p", add_help=True, prefix_chars="-", allow_abbrev=True, exit_on_error=True,
                        conflict_handler="error")
        p.add_argument("--root")
        self.assertEqual(p.parse_args(["--ro", "a"]).root, "a")
        self.assertEqual(_GateParser(prog="decisions ask-2_x").prog, "decisions ask-2_x")

    def test_option_strings_refused(self):  # A2, M6
        for strings in (("-o",), ("-o", "--opt"), ("--opt", "-o"), ("-1", "--one"), ("-\U0001e4f0", "--d"),
                        ("--a\U0001e4f0",), ("--\xe9",), ("--A",), ("--a_b",), ("--9x",), ("---a",), ("--",),
                        ("--a-",), ("--a--b",), (StrSub("--a"),), ("-h",), ("--help",), ("-h", "--help")):
            for route in ("parser", "subparser"):
                target = _GateParser(prog="p") if route == "parser" else self.sub().add_parser("s")
                with self.subTest(strings=[s[:6] for s in strings], route=route):
                    if strings == ("-h", "--help") or strings in (("-h",), ("--help",)):
                        with self.assertRaises(result.ParserRefused):  # by hand: the help action only by add_help
                            target.add_argument(*strings, action="store_true" if len(strings) == 1 else None)
                        continue
                    self.refused(result.OptionStringRefused, target.add_argument, *strings)
        self.assertRaises(result.OptionStringHoldsEquals, _GateParser(prog="p").add_argument, "--a=b")  # C1 first

    def test_option_string_shapes_admitted(self):  # A2 controls
        p = _GateParser(prog="p")
        for strings in (("--a",), ("--a-b",), ("--a1",), ("--ab-c2-d",), ("--xx", "--yy")):
            p.add_argument(*strings)
        self.assertEqual(vars(p.parse_args(["--a=1", "--a-b", "2", "--yy", "3"]))["xx"], "3")

    def test_actions_refused(self):  # A3
        class Custom(argparse.Action):
            def __call__(self, parser, namespace, values, option_string=None):
                pass

        class OnceSub(result._Once):
            pass

        for name, kw in (("store_false", {"action": "store_false"}), ("store_const", {"action": "store_const", "const": 1}),
                         ("append_const", {"action": "append_const", "const": 1}), ("count", {"action": "count"}),
                         ("help", {"action": "help"}), ("version", {"action": "version", "version": "v"}),
                         ("extend", {"action": "extend"}), ("BooleanOptionalAction", {"action": argparse.BooleanOptionalAction}),
                         ("custom", {"action": Custom}), ("_Once subclass", {"action": OnceSub}),
                         ("str subclass", {"action": StrSub("store")})):
            with self.subTest(name):
                with self.assertRaises(result.ParserRefused) as cm:
                    _GateParser(prog="p").add_argument("--x", **kw)
                # `const`/`version` keywords may be named first (A6); the action itself otherwise
                self.assertIn(type(cm.exception), (result.ActionRefused, result.ArgumentOptionRefused))
                if name in ("store_false", "count", "help", "extend", "BooleanOptionalAction", "custom", "_Once subclass"):
                    self.assertIs(type(cm.exception), result.ActionRefused)
        # a name added with register(): an admitted class under a new name is refused when parsing starts (A3, A11);
        # an admitted name pointed at another class is refused at the add_argument call
        p = _GateParser(prog="p")
        p.register("action", "mine", argparse._StoreAction)
        p.add_argument("--x", action="mine")
        with mock.patch.object(sys, "argv", Unread()):
            self.refused(result.ActionRefused, p.parse_args, ["--x", "1"])
        q = _GateParser(prog="p")
        q.register("action", "store", argparse._StoreFalseAction)
        self.refused(result.ActionRefused, q.add_argument, "--x", action="store")

    def test_actions_admitted(self):  # A3 controls
        p = _GateParser(prog="p")
        p.add_argument("--a")
        p.add_argument("--b", action="store")
        p.add_argument("--c", action="store_true")
        p.add_argument("--d", action="append")
        p.add_argument("--e", action=result._Once)
        self.assertEqual(vars(p.parse_args(["--a", "1", "--b", "2", "--c", "--d", "3", "--d", "4", "--e", "5"])),
                         {"a": "1", "b": "2", "c": True, "d": ["3", "4"], "e": "5"})

    def test_nargs_refused(self):  # A4, M2
        for nargs in ("?", "+", 0, 1, 2, argparse.REMAINDER, argparse.PARSER, argparse.SUPPRESS, 10 ** 30, True):
            for where in ("option", "positional"):
                with self.subTest(nargs=repr(nargs)[:12], where=where):
                    self.refused(result.NargsRefused, _GateParser(prog="p").add_argument,
                                 "--x" if where == "option" else "x", nargs=nargs)
        self.refused(result.NargsRefused, _GateParser(prog="p").add_argument, "--x", nargs="*")  # `*` on an option

    def test_nargs_admitted(self):  # A4 controls
        p = _GateParser(prog="p")
        p.add_argument("--x")
        p.add_argument("terms", nargs="*")
        self.assertEqual(vars(p.parse_args(["a", "b", "--x", "c"])), {"x": "c", "terms": ["a", "b"]})
        q = _GateParser(prog="p")
        q.add_argument("id")
        self.assertEqual(q.parse_args(["v"]).id, "v")

    def test_second_positional_refused(self):  # A5, M1, M2
        for first, second in ((("x",), ("y",)), (("x",), ("y", "?")), (("x", "*"), ("y",)), (("x",), ("y", "*"))):
            p = _GateParser(prog="p")
            p.add_argument(first[0], **({"nargs": first[1]} if len(first) > 1 else {}))
            with self.subTest(first=first, second=second):
                self.refused(result.PositionalRefused, p.add_argument, second[0],
                             **({"nargs": second[1]} if len(second) > 1 else {}))
        p = _GateParser(prog="p")
        p.add_subparsers(dest="sub")
        self.refused(result.PositionalRefused, p.add_argument, "x")  # a positional after the subparsers action
        p = _GateParser(prog="p")
        p.add_argument("x")
        self.refused(result.PositionalRefused, p.add_subparsers, dest="sub")  # and the reverse
        for kw in ({"action": "append"}, {"action": result._Once}, {"action": "store_true"}):
            with self.subTest(kw=sorted(kw)):  # a positional is the plain store action (round 3 decision, kept)
                self.assertRaises(result.ParserRefused, _GateParser(prog="p").add_argument, "x", **kw)

    def test_one_positional_admitted(self):  # A5 controls
        for name in ("id", "terms", "a_b9"):
            p = _GateParser(prog="p")
            p.add_argument(name)
            self.assertEqual(getattr(p.parse_args(["v"]), name), "v")
        for name in ("A", "a-b", "9", "\xe9", StrSub("x")):
            with self.subTest(name=name):
                self.assertRaises(result.ParserRefused, _GateParser(prog="p").add_argument, name)

    def test_argument_keywords_refused(self):  # A6
        for name, args, kw in (("type", ("--x",), {"type": str}), ("choices", ("--x",), {"choices": ["a"]}),
                               ("const", ("--x",), {"const": "c"}), ("default", ("--x",), {"default": 0}),
                               ("default", ("--x",), {"default": ""}), ("default", ("--x",), {"default": []}),
                               ("required", ("x",), {"required": True}), ("required", ("--x",), {"required": 1}),
                               ("help", ("--x",), {"help": "100%"}), ("help", ("--x",), {"help": "\xe9"}),
                               ("help", ("--x",), {"help": "a\tb"}), ("metavar", ("--x",), {"metavar": "o p"}),
                               ("metavar", ("--x",), {"metavar": "[X]"}), ("metavar", ("--x",), {"metavar": "(X)"}),
                               ("metavar", ("--x",), {"metavar": ("A", "B")}), ("metavar", ("--x",), {"metavar": StrSub("X")}),
                               ("metavar", ("--x",), {"metavar": "x"}), ("dest", ("--x",), {"dest": "a-b"}),
                               ("dest", ("--x",), {"dest": "A"}), ("dest", ("--x",), {"dest": StrSub("a")})):
            with self.subTest(name, value=repr(kw[name])[:20]):
                m = self.refused(result.ArgumentOptionRefused, _GateParser(prog="p").add_argument, *args, **kw)
                self.assertIn(name, m)
        self.assertRaises(result.ParserRefused, _GateParser(prog="p").add_argument, "--x", action="version", version="v")

    def test_argument_keywords_admitted(self):  # A6 controls: the keywords of the 16 parsers
        p = _GateParser(prog="p")
        p.add_argument("--class", dest="cls", required=True, metavar="CLS", help="the class (a b-c, d.e)")
        p.add_argument("--root", default=None, help="h")
        p.add_argument("--all", action="store_true", required=False)
        self.assertEqual(vars(p.parse_args(["--class", "c"])), {"cls": "c", "root": None, "all": False})

    def test_subparsers_refused(self):  # A7, N1, M4
        for name, kw in (("no dest", {}), ("no dest, required (M4)", {"required": True}), ("title", {"dest": "s", "title": "t"}),
                         ("description", {"dest": "s", "description": "d"}), ("prog", {"dest": "s", "prog": "x"}),
                         ("help", {"dest": "s", "help": "h"}), ("action", {"dest": "s", "action": argparse._SubParsersAction}),
                         ("parser_class N1", {"dest": "s", "parser_class": argparse.ArgumentParser}),
                         ("parser_class gate", {"dest": "s", "parser_class": _GateParser}), ("dest shape", {"dest": "S"}),
                         ("dest str subclass", {"dest": StrSub("s")}), ("metavar shape", {"dest": "s", "metavar": "{a,B}"}),
                         ("metavar", {"dest": "s", "metavar": "X"}), ("required not bool", {"dest": "s", "required": 1})):
            with self.subTest(name):
                self.refused(result.SubparsersRefused, _GateParser(prog="p").add_subparsers, **kw)
        p = _GateParser(prog="p")
        p.add_subparsers(dest="sub")
        self.refused(result.SubparsersRefused, p.add_subparsers, dest="other")  # a second one
        s = self.sub().add_parser("s")
        self.refused(result.SubparsersRefused, s.add_subparsers, dest="deeper")  # two levels
        for name, args, kw in (("aliases", ("x",), {"aliases": ["y"]}), ("help", ("x",), {"help": "h"}),
                               ("name shape", ("X",), {}), ("name digit", ("x1",), {}), ("name U+2C2F", ("Ⱟ",), {}),
                               ("name str subclass", (StrSub("x"),), {}), ("prog shape", ("x",), {"prog": "X"})):
            with self.subTest(name):
                with self.assertRaises(result.ParserRefused) as cm:
                    self.sub().add_parser(*args, **kw)
                self.assertIn(type(cm.exception), (result.SubparsersRefused, result.ParserOptionRefused))
        subs = self.sub()
        subs.add_parser("x")
        self.refused(result.SubparsersRefused, subs.add_parser, "x")  # a name given twice (3.9 overwrites, 3.11+ raises)

    def test_findings_shape_admitted(self):  # A7 control: the `findings` shape
        p = _GateParser(prog="findings")
        subs = p.add_subparsers(dest="sub", metavar="{new,move}")
        subs.required = True
        subs.add_parser("new", prog="findings new").add_argument("--by", required=True)
        subs.add_parser("move", prog="findings move").add_argument("id")
        self.assertEqual(vars(p.parse_args(["new", "--by", "b"])), {"sub": "new", "by": "b"})
        self.assertEqual(vars(p.parse_args(["move", "i"])), {"sub": "move", "id": "i"})

    def test_groups_refused(self):  # A8 (C3's rows converted: see TestRefusals.test_refuse_nested_group)
        for target in (_GateParser(prog="p"), self.sub().add_parser("s")):
            for call in (target.add_argument_group, target.add_mutually_exclusive_group):
                with self.subTest(call.__name__):
                    self.refused(result.GroupRefused, call)
            self.refused(result.GroupRefused, target.add_argument_group, "t", "d")
            self.refused(result.GroupRefused, target.add_mutually_exclusive_group, required=True)
            self.assertEqual((len(target._action_groups), target._mutually_exclusive_groups), (2, []))

    def test_review_3_members_refused(self):  # A13: N1, M1-M6 with review 3's shapes
        self.refused(result.SubparsersRefused, _GateParser(prog="p").add_subparsers, dest="s",
                     parser_class=argparse.ArgumentParser)  # N1
        p = _GateParser(prog="p")
        p.add_argument("x")
        self.refused(result.PositionalRefused, p.add_argument, "y")  # M1
        p = _GateParser(prog="p")
        p.add_argument("x")
        self.refused(result.PositionalRefused, p.add_argument, "y", nargs="?")  # M2
        self.refused(result.NargsRefused, _GateParser(prog="p").add_argument, "y", nargs="?")  # M2, alone
        p = _GateParser(prog="p")
        p.add_argument("--opt")
        with mock.patch.object(sys, "argv", Unread()):  # M3, refused by its own name (E8/E10: the message names it)
            self.assertIn("parse_intermixed_args", self.refused(result.ParseEntryRefused, p.parse_intermixed_args, ["--", "a"]))
        self.refused(result.SubparsersRefused, _GateParser(prog="p").add_subparsers, required=True)  # M4
        self.refused(result.ParserOptionRefused, _GateParser, prog="p", exit_on_error=False)  # M5
        self.refused(result.OptionStringRefused, _GateParser(prog="p").add_argument, "-o", "--opt")  # M6

    def test_skeleton_digit_runs(self):  # KA1: no int() on configuration or argv text; same verdict on both
        d = "9" * 4301
        p = _GateParser(prog="p")
        p.add_argument("--a" + d)
        self.assertEqual(vars(p.parse_args(["--a" + d, d])), {"a" + d: d})
        self.assertIn("'--" + d + "'", self.refused(result.OptionStringRefused, _GateParser(prog="p").add_argument, "--" + d))
        self.refused(result.ArgumentOptionRefused, _GateParser(prog="p").add_argument, "--x", metavar=d)
        self.refused(result.ParserOptionRefused, _GateParser, prog=d)
        for n in (18, 4300, 4301):  # an int nargs of n+1 digits: 3.13 refuses str() of more than 4300 digits
            with self.subTest(digits=n + 1):
                self.refused(result.NargsRefused, _GateParser(prog="p").add_argument, "--x", nargs=10 ** n)
        f = BY_KEY["findings move"]  # argv: the digits as a positional of a production parser (subprocess, bytes)
        m = "the following arguments are required: --to, --by"
        self.assertEqual(run(["findings", "move", d]), golden(f, "findings move", m, m))

    def test_skeleton_category_differs(self):  # KA2: U+1E4F0 (Cn on 3.9.6, Nd on 3.13) and U+2C2F in the configuration
        for c, shown in (("\U0001e4f0", "\\U0001e4f0"), ("Ⱟ", "\\u2c2f")):
            for name, error, call in (
                    ("option string", result.OptionStringRefused, lambda: _GateParser(prog="p").add_argument("--a" + c)),
                    ("positional", result.ParserRefused, lambda: _GateParser(prog="p").add_argument("a" + c)),
                    ("dest", result.ArgumentOptionRefused, lambda: _GateParser(prog="p").add_argument("--a", dest="a" + c)),
                    ("metavar", result.ArgumentOptionRefused, lambda: _GateParser(prog="p").add_argument("--a", metavar="A" + c)),
                    ("prog", result.ParserOptionRefused, lambda: _GateParser(prog="p" + c)),
                    ("help", result.ArgumentOptionRefused, lambda: _GateParser(prog="p").add_argument("--a", help="h" + c)),
                    ("subparser name", result.SubparsersRefused, lambda: self.sub().add_parser("s" + c))):
                with self.subTest(name, c=hex(ord(c))):
                    with self.assertRaises(error) as cm:
                        call()
                    self.assertNotIn(c, str(cm.exception))  # shown by E1 (3.9.6's escape), the same bytes on both
                    if name != "positional":
                        self.assertIn(shown, str(cm.exception))

    def test_skeleton_base_exception_group(self):  # KA3
        class Boom(BaseException):
            pass

        group = getattr(builtins, "BaseExceptionGroup", None)  # absent on 3.9.6 (the test states it)
        self.assertEqual(group is None, sys.version_info < (3, 11))
        exc = group("g", [KeyboardInterrupt()]) if group is not None else Boom("b")

        class Stream(io.StringIO):
            def write(self, s):
                raise exc

        p = _GateParser(prog="p")
        p.add_argument("--root")
        for argv in (["--zz"], ["-h"]):
            with self.subTest(argv), mock.patch.object(sys, "stderr", Stream()), mock.patch.object(sys, "stdout", Stream()):
                with self.assertRaises(type(exc)) as cm:
                    p.parse_args(argv)
                self.assertIs(cm.exception, exc)

        class Evil(str):
            def __eq__(self, other):
                raise exc

            def __hash__(self):
                raise exc

            def __str__(self):
                raise exc

            def __len__(self):
                raise exc

            def __getitem__(self, key):
                raise exc

            def lstrip(self, *a):
                raise exc

            def startswith(self, *a):
                raise exc

            def replace(self, *a):
                raise exc

        # a keyword name that is a str subclass is refused by exact type (the interpreter itself compares keyword names
        # with the parameters at the call, so a raising __eq__ cannot be passed as a keyword name at all)
        self.assertRaises(result.ArgumentOptionRefused,
                          lambda: _GateParser(prog="p").add_argument("--a", **{StrSub("dest"): "x"}))
        for call in (lambda: _GateParser(prog="p").add_argument(Evil("--a")),
                     lambda: _GateParser(prog=Evil("p")),
                     lambda: _GateParser(prog="p").add_argument("--a", metavar=Evil("A"))):
            with self.assertRaises(result.ParserRefused):  # the check calls no method of the checked value
                call()

    def test_each_call_check_names_its_value(self):  # A1, A2, A4, A6, A10 at the call (fix round 5): exact class and text
        """Each build-time check names the value it refuses, at the call that brings it (E10). The expected texts are
        written from rule E10's message shapes (the refused keyword, value or option string through `_frozen_repr`)."""
        tail = " (refused: F1 rule E10)"

        def parser():
            return _GateParser(prog="p")

        for name, call, error, text in (
                ("a positional argument", lambda: _GateParser("p"), result.ParserOptionRefused, "positional argument 'p'"),
                ("a positional argument beside prog", lambda: _GateParser("p", prog="q"), result.ParserOptionRefused,
                 "positional argument 'p'"),
                ("required not a bool on a positional", lambda: parser().add_argument("x", required=1),
                 result.ArgumentOptionRefused, "keyword required=1"),
                ("an unknown keyword", lambda: parser().add_argument("--x", foo=1), result.ArgumentOptionRefused,
                 "keyword 'foo'"),
                ("deprecated (a keyword argparse 3.13 takes, 3.9 does not)",
                 lambda: parser().add_argument("--x", deprecated=True), result.ArgumentOptionRefused, "keyword 'deprecated'"),
                ("version on a store action", lambda: parser().add_argument("--x", version="v"),
                 result.ArgumentOptionRefused, "keyword version='v'"),
                ("nargs None given to store_true", lambda: parser().add_argument("--q", action="store_true", nargs=None),
                 result.NargsRefused, "nargs None given to store_true"),
                ("nargs ? given to store_true", lambda: parser().add_argument("--q", action="store_true", nargs="?"),
                 result.NargsRefused, "nargs '?' given to store_true"),
                ("dest given to a positional", lambda: parser().add_argument("x", dest="y"), result.ArgumentOptionRefused,
                 "keyword dest='y' given to a positional"),
                ("option_strings a tuple, added through _add_action",
                 lambda: parser()._add_action(argparse._StoreAction(("--a",), "a")), result.OptionStringRefused,
                 "option_strings of type tuple")):
            with self.subTest(name):
                with mock.patch.object(sys, "argv", Unread()):
                    self.assertEqual(self.refused(error, call), text + tail)
        p = parser()  # set_defaults through one of the two groups argparse makes: refused at the call, nothing stored
        self.assertEqual(self.refused(result.ParseEntryRefused, p._optionals.set_defaults, root="r"), "set_defaults" + tail)
        self.assertEqual(p._defaults, {})

    def test_int_nargs_never_reaches_argparse(self):  # A4 (fix round 5): an int nargs is refused before argparse reads it
        """argparse builds a list of an int nargs' length (a huge int hangs it), so the call is refused before
        argparse's ``add_argument`` runs; the control shows the spy is on the path an admitted call takes."""
        tail = " (refused: F1 rule E10)"
        entered = []
        real = argparse._ActionsContainer.add_argument

        def spy(container, *args, **kwargs):
            entered.append(args)
            return real(container, *args, **kwargs)

        for args, kw in ((("--x",), {}), (("x",), {}), (("--x",), {"action": "append"}), (("--x",), {"action": "store_true"}),
                         (("--x",), {"action": result._Once})):
            with self.subTest(args=args, action=kw.get("action")):
                del entered[:]
                p = _GateParser(prog="p")
                with mock.patch.object(argparse._ActionsContainer, "add_argument", spy):
                    self.assertEqual(self.refused(result.NargsRefused, p.add_argument, *args, nargs=2, **kw), "nargs 2" + tail)
                    self.assertEqual(entered, [])
                    p.add_argument("--y")  # control
                    self.assertEqual(entered, [("--y",)])


if __name__ == "__main__":
    unittest.main()
