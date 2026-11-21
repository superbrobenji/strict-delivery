"""Tests of gates/lib/evidence.py and of gates/schemas/mutation-transcript.yml and review-report.yml (plan Task 6E.1; the rows
SC, TL, PT, TE, RL, PE, SP, RP, RN, K and Y of the input-domain table task-6E.1-domain.md, settled by its "Controller
decisions" D-1-Q1 to D-1-Q13). Every expected value is written out here by hand from the plan and the decisions, never
read back from ``evidence``. The production path is a file committed in a temp repository, read back with
``gitinfo.show`` and parsed, against schemas loaded from ``gates/schemas`` with ``load_schema``. Neither kind is declared
before Rq-6-2 lands, so the schemas are used directly here."""
import contextlib
import copy
import io
import os
import random
import shlex
import sys
import tempfile
import types
import unittest
from unittest import mock

from gates import __main__ as gates_main
from gates.lib import config, evidence, gitinfo, ids, print_table, schema
from gates.lib.evidence import package_entries, parse_transcript, render_pin, run_pin, split_cite, transcript_errors
from gates.lib.result import GateError
from gates.lib.schema import files_of, load_schema, validate_markdown
from tests.helpers import INT_LIMITS, GitIsolatedTestCase, commit_all, int_limit, make_repo, minimal_config

TS_YML = os.path.join(schema.SCHEMAS_DIR, "mutation-transcript.yml")
RR_YML = os.path.join(schema.SCHEMAS_DIR, "review-report.yml")
EVIDENCE_PY = os.path.join(os.path.dirname(os.path.abspath(evidence.__file__)), "evidence.py")

TAG_T = "<!-- schema: mutation-transcript/1 -->"
TAG_R = "<!-- schema: review-report/1 -->"
F = "F-20261031-zzzz"
F2 = "F-20261101-abcd"
DEC = "DEC-20261031-zzzz"
D = "runtests -k t"
SHA = "abcdef0"
TP = ".strict-delivery/state/plans/p/mutations/a.md"
OK_RUNS = [(1, "fix", 0), (2, "mutant", 1), (3, "fix", 0)]
U_NEW = "\U0001f6dd"  # Cn in Unicode 13 (3.9), So in 15.1 (3.13)
U_LOW = "Ꟁ"  # lower() is itself on 3.9, U+A7C1 on 3.13
U_LOW2 = "ꟁ"
U_ANY = "ࡰ"

_CFG: dict = {}


def cfg() -> dict:
    """``config.load`` of a fixture repository whose config is ``minimal_config()`` (built once, copied per call)."""
    if not _CFG:
        with tempfile.TemporaryDirectory() as d:
            make_repo(d, minimal_config())
            _CFG.update(config.load(d))
    return copy.deepcopy(_CFG)


def run_line(n, phase, code, cmd=D) -> str:
    return "RUN %s %s exit=%s command=%s" % (n, phase, code, cmd)


def T(*body, tag=TAG_T) -> str:
    """A transcript text: the tag line, the given lines, a final newline."""
    return "\n".join([tag] + list(body)) + "\n"


def good(finding=F, test="t", mutant="revert", runs=OK_RUNS, cmd=D, extra=()) -> str:
    body = ["FINDING " + finding, "TEST " + test, "MUTANT " + mutant]
    body += [run_line(n, p, c, cmd) for n, p, c in runs]
    body += list(extra)
    return T(*body)


def R(*body, tag=TAG_R) -> str:
    return "\n".join([tag] + list(body)) + "\n"


def group(fid=F, test="t", cmd=D, sha=SHA, path=TP) -> list:
    return ["PIN %s transcript=%s:%s" % (fid, sha, path), "PIN-TEST %s %s" % (fid, test), "PIN-COMMAND %s %s" % (fid, cmd)]


def parsed_of(**kw) -> dict:
    return parse_transcript(good(**kw))


def errs(text_or_parsed=None, finding=F, test="t", cmd=D, **kw) -> list:
    p = parse_transcript(text_or_parsed) if type(text_or_parsed) is str else text_or_parsed
    return transcript_errors(p, finding, test, cmd, cfg())


class S(str):
    pass


class L(list):
    pass


class Dd(dict):
    pass


def write_bytes(root, rel, data: bytes):
    p = os.path.join(root, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "wb") as fh:
        fh.write(data)


class SchemaCase(unittest.TestCase):
    def ts(self):
        return load_schema(TS_YML)

    def rr(self):
        return load_schema(RR_YML)

    def tl(self, text):
        return validate_markdown(self.ts(), text)

    def rl(self, text):
        return validate_markdown(self.rr(), text)


# ---------------------------------------------------------------- SC, RL1, RL2: the schema files
class SchemaFiles(GitIsolatedTestCase):
    def test_transcript_schema_loads(self):  # SC1
        s = load_schema(TS_YML)
        self.assertEqual((s.kind, s.version, s.format), ("mutation-transcript", 1, "markdown"))
        self.assertEqual(s.first_line, TAG_T)
        # owner answer 2026-11-22 (a), legacy pre-schema transcripts (Task 6E.1-x, row X11): exactly the owner's entry
        self.assertEqual(s.files, [{"dir": "plan_state", "glob": "*/mutations/*",
                                    "exclude": ["2026-10-31-strict-delivery-framework-b/mutations/*"]}])
        self.assertEqual(sorted(s.rules), ["FINDING", "MUTANT", "RUN", "TEST"])
        self.assertIsNone(s.table)
        self.assertIsNone(s.headings)

    def test_report_schema_loads(self):  # RL1
        s = load_schema(RR_YML)
        self.assertEqual((s.kind, s.version, s.format), ("review-report", 1, "markdown"))
        self.assertEqual(s.first_line, TAG_R)
        self.assertEqual(s.files, [{"dir": "reviews", "glob": "*/*.md"}])
        self.assertEqual(sorted(s.rules), ["PIN", "PIN-COMMAND", "PIN-TEST"])

    def test_run_pattern_is_the_decided_one(self):  # D-1-Q1: narrower than plan :5694
        pat = load_schema(TS_YML).rules["RUN"][0]
        self.assertEqual(pat, "RUN [123] (?:fix|mutant) exit=(?:0|-?[1-9][0-9]{0,2}) command=.+")

    def test_every_schema_file_loads(self):  # SC2
        names = sorted(n for n in os.listdir(schema.SCHEMAS_DIR) if n.endswith(".yml"))
        self.assertEqual(len(names), 18)
        self.assertIn("mutation-transcript.yml", names)
        self.assertIn("review-report.yml", names)
        for n in names:
            with self.subTest(n):
                self.assertEqual(load_schema(os.path.join(schema.SCHEMAS_DIR, n)).kind, n[:-4])
        loaded, problems = schema.scan_dir()
        self.assertEqual(problems, [])
        self.assertIn("mutation-transcript", loaded)
        self.assertIn("review-report", loaded)

    def test_known_kinds_hold_both(self):  # SC3
        self.assertIn("mutation-transcript", schema.KNOWN_KINDS)
        self.assertIn("review-report", schema.KNOWN_KINDS)

    def _tree(self, paths, dirs=()):
        root = make_repo(self.work, minimal_config())
        for p in paths:
            write_bytes(root, p, b"x\n")
        for d in dirs:
            os.makedirs(os.path.join(root, d))
        return root, config.load(root)

    def test_transcript_files_listed(self):  # SC4, SC7
        ps = ".strict-delivery/state/plans"
        root, c = self._tree([ps + "/p/mutations/a.md", ps + "/p/mutations/.gitkeep", ps + "/p/mutations/noext",
                              ps + "/q/mutations/z.txt", ps + "/mutations/top.md", ps + "/p/other.md"])
        self.assertEqual(files_of(load_schema(TS_YML), root, c),
                         [ps + "/p/mutations/.gitkeep", ps + "/p/mutations/a.md", ps + "/p/mutations/noext",
                          ps + "/q/mutations/z.txt"])

    def test_nested_transcript_not_listed(self):  # SC5
        ps = ".strict-delivery/state/plans"
        root, c = self._tree([ps + "/p/mutations/sub/deep.md"])
        self.assertNotIn(ps + "/p/mutations/sub/deep.md", files_of(load_schema(TS_YML), root, c))

    def test_nested_directory_entry_listed_and_refused(self):  # SC6 (D-1-Q12 (a): behaviour as written, recorded)
        ps = ".strict-delivery/state/plans"
        root, c = self._tree([], dirs=[ps + "/p/mutations/sub"])
        entries = schema.entries_of(load_schema(TS_YML), root, c)
        self.assertEqual(entries, [(ps + "/p/mutations/sub", True)])

    def test_transcript_schema_used_directly(self):  # SC8
        self.assertFalse(hasattr(evidence, "PRODUCES"))
        self.assertEqual(validate_markdown(load_schema(TS_YML), good()), [])

    # ---- Task 6E.1-x, owner answer 2026-11-22 (a), legacy pre-schema transcripts: rows X12, X13, X14
    LEGACY = "2026-10-31-strict-delivery-framework-b"
    PS = ".strict-delivery/state/plans"

    def _gate(self, root):
        """``python3 -m gates check schema --root`` through ``gates.__main__.main`` with the transcript kind produced."""
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), \
                mock.patch.object(schema, "produced_kinds", return_value={"mutation-transcript"}):
            code = gates_main.main(["check", "schema", "--root", root])
        self.assertEqual(err.getvalue(), "")
        return code, out.getvalue().splitlines()

    def test_legacy_folder_transcript_not_checked(self):  # X12
        root, _ = self._tree([self.PS + "/" + self.LEGACY + "/mutations/x.txt"])
        self.assertEqual(self._gate(root), (0, ["PASS schema.kinds", "PASS schema.config", "PASS schema.mutation-transcript"]))

    def test_transcript_elsewhere_still_checked(self):  # X13
        root, _ = self._tree([self.PS + "/other-plan/mutations/x.txt", self.PS + "/" + self.LEGACY + "/mutations/x.txt",
                              self.PS + "/" + self.LEGACY + "-b/mutations/x.txt",
                              self.PS + "/2026-10-31-strict-delivery-framework/mutations/x.txt"])
        code, lines = self._gate(root)
        first = "first line: expected '%s'" % TAG_T
        self.assertEqual(code, 1)
        self.assertEqual(lines[2:], ["FAIL schema.mutation-transcript.%s/%s: %s" % (self.PS, rel, first) for rel in (
            self.LEGACY + "-b/mutations/x.txt", "2026-10-31-strict-delivery-framework/mutations/x.txt",
            "other-plan/mutations/x.txt")])  # path order: "-" sorts before "/"

    def test_real_repository_legacy_transcripts_not_listed(self):  # X14
        repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        legacy = os.path.join(repo, *self.PS.split("/"), self.LEGACY, "mutations")
        on_disk = sorted(os.listdir(legacy))
        self.assertEqual(len(on_disk), 42)
        listed = files_of(load_schema(TS_YML), repo, config.load(repo))
        self.assertEqual([p for p in listed if "/" + self.LEGACY + "/" in p], [])
        for n in on_disk:
            self.assertNotIn(self.PS + "/" + self.LEGACY + "/mutations/" + n, listed)

    def test_report_files_listed(self):  # RL2
        rv = "docs/strict-delivery/reviews"
        root, c = self._tree([rv + "/p/r.md", rv + "/p/r.txt", rv + "/top.md", rv + "/p/deeper/r.md"])
        self.assertEqual(files_of(load_schema(RR_YML), root, c), [rv + "/p/r.md"])


# ---------------------------------------------------------------- TL: transcript lines
class TranscriptLines(SchemaCase):
    def test_transcript_lines_conform(self):  # TL1
        self.assertEqual(self.tl(good()), [])
        self.assertEqual(self.tl(T("FINDING " + F, "TEST t", "MUTANT revert", run_line(1, "fix", 0))), [])

    def test_finding_line_shape(self):  # TL2
        bad = ["FINDING f-20261031-zzzz", "FINDING F-20261031-zzz0", "FINDING F-20261031-zzzz ", "FINDING F-20261031-zzzz\r",
               "FINDING F-20261031-zzzz x", "FINDING", "FINDING ", "FINDING: " + F, "FINDING F-2026103-zzzz",
               "FINDING F-20261031-zzzzz", "FINDING 1-20261031-zzzz", "FINDING F-20261031-zzzl", "FINDING -20261031-zzzz",
               "FINDING F-20261031-zzz", "FINDING F-20261031-zz"]
        for line in bad:
            with self.subTest(line):
                self.assertEqual(len(self.tl(T(line))), 1)
        for line in ["FINDING F-20261331-zzzz", "FINDING DEC-20261031-zzzz", "FINDING " + F]:
            with self.subTest(line):
                self.assertEqual(self.tl(T(line)), [])  # the date and the prefix are transcript_errors' (TE3)

    def test_test_line_nonempty(self):  # TL3
        for line in ["TEST", "TEST "]:
            with self.subTest(line):
                self.assertEqual(len(self.tl(T(line))), 1)
        for line in ["TEST  ", "TEST t "]:
            with self.subTest(line):
                self.assertEqual(self.tl(T(line)), [])
        self.assertEqual(parse_transcript(T("TEST  "))["test"], [" "])
        self.assertEqual(parse_transcript(T("TEST t "))["test"], ["t "])

    def test_transcript_text_edge_characters(self):  # TL4, PT9
        for ch in ["\t", "\r", "\0", " ", "\x85", "\x0b", "\x0c", "\xe9", "\ud800"]:
            with self.subTest(repr(ch)):
                text = T("TEST t" + ch, "MUTANT m" + ch, run_line(1, "fix", 0, "c" + ch))
                self.assertEqual(self.tl(text), [])
                p = parse_transcript(text)
                self.assertEqual(p["test"], ["t" + ch])
                self.assertEqual(p["mutant"], ["m" + ch])
                self.assertEqual(p["runs"], [{"n": 1, "phase": "fix", "exit": 0, "command": "c" + ch}])

    def test_mutant_line(self):  # TL5
        self.assertEqual(self.tl(T("MUTANT " + U_NEW)), [])
        self.assertEqual(self.tl(T(" free " + U_NEW)), [])
        self.assertEqual(len(self.tl(T("MUTANT"))), 1)
        self.assertEqual(len(self.tl(T("MUTANT "))), 1)

    def test_run_number_phase_shape(self):  # TL6
        for line in ["RUN 4 fix exit=0 command=x", "RUN 0 fix exit=0 command=x", "RUN 12 fix exit=0 command=x",
                     "RUN 1 Fix exit=0 command=x", "RUN 1 fixx exit=0 command=x", "RUN 1  fix exit=0 command=x"]:
            with self.subTest(line):
                self.assertEqual(len(self.tl(T(line))), 1)

    def test_pc1_long_run_number(self):  # K1b: the number is one character, never converted from long text
        for limit in INT_LIMITS:
            with int_limit(limit):
                for n in (4300, 4301, 641):
                    with self.subTest(limit=limit, n=n):
                        text = T("RUN %s fix exit=0 command=x" % ("1" * n))
                        self.assertEqual(len(self.tl(text)), 1)
                        with self.assertRaises(ValueError):
                            parse_transcript(text)

    def test_run_phase_is_not_schema(self):  # TL7
        self.assertEqual(self.tl(T("RUN 1 mutant exit=1 command=x")), [])

    def test_run_exit_text(self):  # TL8, D-1-Q1
        bad = ["exit=", "exit=+1", "exit=--1", "exit=1.0", "exit=١", "exit=１", "exit=-0", "exit=007",
               "exit=0000", "exit=1000", "exit=-1000", "exit=00", "exit=-", "exit=0x1", "exit= 1", "exit=1 "]
        for f in bad:
            with self.subTest(f):
                self.assertEqual(len(self.tl(T("RUN 1 fix %s command=x" % f))), 1)
        good_exits = {"0": 0, "1": 1, "9": 9, "10": 10, "255": 255, "-11": -11, "-1": -1, "999": 999, "-999": -999,
                      "126": 126, "256": 256}
        for f, v in good_exits.items():
            with self.subTest(f):
                text = T("RUN 1 fix exit=%s command=x" % f)
                self.assertEqual(self.tl(text), [])
                self.assertEqual(parse_transcript(text)["runs"][0]["exit"], v)

    def test_run_command_field(self):  # TL9
        for line in ["RUN 1 fix exit=0 command=", "RUN 1 fix exit=0", "RUN 1 fix exit=0 command", "RUN 1 fix exit=0 cmd=x"]:
            with self.subTest(line):
                self.assertEqual(len(self.tl(T(line))), 1)
        for cmd, want in [(" ", " "), ("a command=b", "a command=b"), ("x ", "x "), ("a  b", "a  b")]:
            with self.subTest(cmd):
                text = T("RUN 1 fix exit=0 command=" + cmd)
                self.assertEqual(self.tl(text), [])
                self.assertEqual(parse_transcript(text)["runs"][0]["command"], want)

    def test_run_spacing(self):  # TL10
        self.assertEqual(len(self.tl(T("RUN 1 fix  exit=0 command=x"))), 1)
        self.assertEqual(self.tl(T("RUN\t1 fix exit=0 command=x")), [])  # free text: the token is "RUN\t1"

    def test_keyword_forms(self):  # TL11
        self.assertEqual(len(self.tl(T("RUN: 1 fix exit=0 command=x"))), 1)
        for line in [" RUN 4 fix", "note RUN 4", "run 4", "FINDINGS x", " FINDING bad", "Test x", "mutant x"]:
            with self.subTest(line):
                self.assertEqual(self.tl(T(line)), [])
                self.assertEqual(parse_transcript(T(line))["runs"], [])
        # free text whose first token merely starts with a keyword is never read as that keyword
        for line in ["FINDINGS " + F, "TESTS t", "MUTANTS m", "RUNNING 1 fix exit=0 command=x", "RUN\t1 fix exit=0 command=x",
                     "TEST\tt", "MUTANT\tm", "FINDING\t" + F, "RUNS 1 fix exit=0 command=x"]:
            with self.subTest(line):
                self.assertEqual(parse_transcript(T(line)), {"finding": [], "test": [], "mutant": [], "runs": []})

    def test_output_line_colliding_with_keyword(self):  # TL12, D-1-Q9 (a)
        for line in ["RUN  tests/a.js", "TEST: 3 passed", "FINDING:", "MUTANT: x", "RUN"]:
            with self.subTest(line):
                self.assertEqual(len(self.tl(T(line))), 1)
                with self.assertRaises(ValueError):
                    parse_transcript(T(line))
        self.assertEqual(self.tl(T(" RUN  tests/a.js")), [])  # indented by one space: free text

    def test_keyword_order(self):  # TL13, D-1-Q10 (a)
        text = T(run_line(1, "fix", 0), "FINDING " + F, run_line(2, "mutant", 1), "TEST t", "MUTANT m", run_line(3, "fix", 0))
        self.assertEqual(self.tl(text), [])
        self.assertEqual(transcript_errors(parse_transcript(text), F, "t", D, cfg()), [])

    def test_transcript_line_ends(self):  # TL14, D-1-Q3 (a)
        body = good()
        self.assertEqual(self.tl(body), [])
        self.assertEqual(self.tl(body.rstrip("\n")), [])
        self.assertEqual(self.tl(body + "\n"), [])
        for name, text in [("crlf", body.replace("\n", "\r\n")), ("cr", body.replace("\n", "\r"))]:
            with self.subTest(name):
                self.assertEqual(self.tl(text), ["first line: expected '%s'" % TAG_T])
                with self.assertRaises(ValueError):
                    parse_transcript(text)
        mixed = body.replace("TEST t\n", "TEST t\r\n")
        self.assertEqual(self.tl(mixed), [])
        self.assertEqual(parse_transcript(mixed)["test"], ["t\r"])

    def test_transcript_first_line(self):  # TL15
        want = ["first line: expected '%s'" % TAG_T]
        for name, text in [("empty", ""), ("no tag", "FINDING " + F + "\n"), ("tag line 2", "x\n" + TAG_T + "\n"),
                           ("trailing space", TAG_T + " \n"), ("bom", "﻿" + TAG_T + "\n"),
                           ("report tag", TAG_R + "\n"), ("v2", "<!-- schema: mutation-transcript/2 -->\n")]:
            with self.subTest(name):
                self.assertEqual(self.tl(text), want)
                with self.assertRaises(ValueError) as cm:
                    parse_transcript(text)
                self.assertIn(want[0], str(cm.exception))
        for text in [TAG_T, TAG_T + "\n"]:
            with self.subTest(text):
                self.assertEqual(self.tl(text), [])
                self.assertEqual(parse_transcript(text), {"finding": [], "test": [], "mutant": [], "runs": []})

    def test_transcript_many_lines(self):  # TL16
        self.assertEqual(parse_transcript(T(*[" free %d" % i for i in range(100000)]))["runs"], [])
        e = self.tl(T(*["RUN 9 fix" for _ in range(100000)]))
        self.assertEqual(len(e), 100000)


# ---------------------------------------------------------------- PT: parse_transcript
class ParseTranscript(GitIsolatedTestCase):
    def test_parse_valid_literal(self):  # PT1
        text = T("FINDING " + F, "TEST t", "MUTANT revert", run_line(1, "fix", 0), " captured output", run_line(2, "mutant", 1),
                 run_line(3, "fix", 0), "tail text")
        p = parse_transcript(text)
        self.assertEqual(p, {"finding": [F], "test": ["t"], "mutant": ["revert"],
                             "runs": [{"n": 1, "phase": "fix", "exit": 0, "command": D},
                                      {"n": 2, "phase": "mutant", "exit": 1, "command": D},
                                      {"n": 3, "phase": "fix", "exit": 0, "command": D}]})
        for r in p["runs"]:
            self.assertIs(type(r["n"]), int)
            self.assertIs(type(r["exit"]), int)
            self.assertIs(type(r["phase"]), str)
            self.assertIs(type(r["command"]), str)

    def test_parse_runs_in_file_order(self):
        p = parse_transcript(good(runs=[(3, "fix", 0), (1, "fix", 0), (2, "mutant", 1)]))
        self.assertEqual([r["n"] for r in p["runs"]], [3, 1, 2])

    def test_parse_exit_ints(self):  # PT2
        for text, want in [("0", 0), ("1", 1), ("255", 255), ("-11", -11), ("999", 999)]:
            with self.subTest(text):
                self.assertEqual(parse_transcript(T("RUN 2 mutant exit=%s command=x" % text))["runs"][0]["exit"], want)
        for text in ["-0", "007"]:  # D-1-Q1: not canonical, refused
            with self.subTest(text):
                with self.assertRaises(ValueError):
                    parse_transcript(T("RUN 2 mutant exit=%s command=x" % text))

    def test_parse_repeated_and_missing_keywords(self):  # PT3, D-1-Q2
        p = parse_transcript(T("FINDING " + F, "FINDING " + F2, "TEST a", "TEST b", "MUTANT m1", "MUTANT m2"))
        self.assertEqual((p["finding"], p["test"], p["mutant"]), ([F, F2], ["a", "b"], ["m1", "m2"]))
        self.assertEqual(parse_transcript(T("TEST a")), {"finding": [], "test": ["a"], "mutant": [], "runs": []})

    def test_parse_schema_errors_raise(self):  # PT4
        with self.assertRaises(ValueError) as cm:
            parse_transcript("FINDING " + F + "\n")
        self.assertEqual(str(cm.exception), "first line: expected '%s'" % TAG_T)
        with self.assertRaises(ValueError) as cm:
            parse_transcript(T("RUN 1 fix exit= command=x"))
        self.assertIn("line 2: 'RUN' line does not match", str(cm.exception))
        with self.assertRaises(ValueError) as cm:
            parse_transcript(T("RUN 1 fix exit= command=x", " ok", "TEST", "RUN 4 fix exit=0 command=x"))
        msg = str(cm.exception)
        self.assertEqual(len(validate_markdown(load_schema(TS_YML), T("RUN 1 fix exit= command=x", " ok", "TEST",
                                                                       "RUN 4 fix exit=0 command=x"))), 3)
        for needle in ["line 2: 'RUN'", "line 4: 'TEST'", "line 5: 'RUN'"]:
            self.assertIn(needle, msg)
        self.assertLess(msg.index("line 2"), msg.index("line 4"))
        self.assertLess(msg.index("line 4"), msg.index("line 5"))

    def test_parse_text_not_str(self):  # PT5, Y6
        for v in [None, b"%s\n" % TAG_T.encode(), 5, True, []]:
            with self.subTest(repr(v)):
                with self.assertRaises(ValueError) as cm:
                    parse_transcript(v)
                self.assertEqual(str(cm.exception), "first line: text must be a string")

    def test_parse_text_str_subclass(self):  # PT6, Y6
        with self.assertRaises(ValueError) as cm:
            parse_transcript(S(good()))
        self.assertEqual(str(cm.exception), "first line: text must be a string")

    def _commit(self, rel, data: bytes):
        root = make_repo(self.work, minimal_config())
        write_bytes(root, rel, data)
        return root, commit_all(root, "t")

    def test_parse_via_show_roundtrip(self):  # PT7: the production path
        rel = ".strict-delivery/state/plans/p/mutations/a.md"
        text = good(test="t" + U_NEW + U_LOW, cmd="runtests " + U_NEW + U_LOW)
        root, sha = self._commit(rel, text.encode("utf-8"))
        back = gitinfo.show(root, sha, rel)
        self.assertEqual(back, text)
        self.assertEqual(parse_transcript(back),
                         {"finding": [F], "test": ["t\U0001f6ddꟀ"], "mutant": ["revert"],
                          "runs": [{"n": 1, "phase": "fix", "exit": 0, "command": "runtests \U0001f6ddꟀ"},
                                   {"n": 2, "phase": "mutant", "exit": 1, "command": "runtests \U0001f6ddꟀ"},
                                   {"n": 3, "phase": "fix", "exit": 0, "command": "runtests \U0001f6ddꟀ"}]})
        self.assertEqual(transcript_errors(parse_transcript(back), F, "t" + U_NEW + U_LOW, "runtests " + U_NEW + U_LOW,
                                           cfg()), [])

    def test_parse_via_show_crlf_and_bom_refused(self):  # PT7, D-1-Q3 (a)
        for name, data in [("crlf", good().replace("\n", "\r\n").encode()), ("bom", b"\xef\xbb\xbf" + good().encode())]:
            with self.subTest(name):
                with tempfile.TemporaryDirectory() as d:
                    root, sha = self._commit_in(d, data)
                    back = gitinfo.show(root, sha, "a.md")
                    with self.assertRaises(ValueError):
                        parse_transcript(back)

    def _commit_in(self, d, data):
        root = make_repo(d, minimal_config())
        write_bytes(root, "a.md", data)
        return root, commit_all(root, "t")

    def test_show_non_utf8_is_gate_error(self):  # PT8
        root, sha = self._commit("bad.bin", b"\xff\xfe\x00")
        with self.assertRaises(GateError) as cm:
            gitinfo.show(root, sha, "bad.bin")
        self.assertEqual(str(cm.exception), "bad.bin: not valid UTF-8")


# ---------------------------------------------------------------- TE: transcript_errors
class TranscriptErrors(unittest.TestCase):
    def assertNames(self, errors, *needles):
        self.assertTrue(errors, "expected errors")
        for n in needles:
            self.assertTrue(any(n in e for e in errors), "no error names %r in %r" % (n, errors))

    def test_valid_transcript(self):
        self.assertEqual(errs(good()), [])

    def test_exactly_one_each(self):  # TE1
        self.assertEqual(errs(good()), [])
        base = ["FINDING " + F, "TEST t", "MUTANT m"] + [run_line(n, p, c) for n, p, c in OK_RUNS]
        for name, kw, lines in [("FINDING twice", "FINDING", ["FINDING " + F] + base),
                                ("MUTANT twice", "MUTANT", base + ["MUTANT m"]),
                                ("TEST twice", "TEST", base + ["TEST t"]),
                                ("TEST missing", "TEST", [b for b in base if b != "TEST t"]),
                                ("FINDING missing", "FINDING", base[1:]),
                                ("MUTANT missing", "MUTANT", [b for b in base if b != "MUTANT m"])]:
            with self.subTest(name):
                e = errs(T(*lines))
                self.assertEqual(len(e), 1, e)
                self.assertNames(e, kw)
        e = errs(T(*[run_line(n, p, c) for n, p, c in OK_RUNS]))
        self.assertEqual(len(e), 3)
        for kw in ["FINDING", "TEST", "MUTANT"]:
            self.assertNames(e, kw)

    def test_repeats_report_only_the_count(self):  # TE1: a repeated line is one error, not also a value comparison
        base = [run_line(n, p, c) for n, p, c in OK_RUNS]
        e = errs(T("FINDING " + F2, "FINDING " + F, "TEST t", "MUTANT m", *base))
        self.assertEqual(e, ["finding: expected exactly one FINDING line, got 2"])
        e = errs(T("FINDING " + F, "TEST x", "TEST t", "MUTANT m", *base))
        self.assertEqual(e, ["test: expected exactly one TEST line, got 2"])
        e = errs(T("FINDING " + F, "TEST t", "MUTANT m", "MUTANT n", *base))
        self.assertEqual(e, ["mutant: expected exactly one MUTANT line, got 2"])

    def test_error_messages_exact(self):  # TE2, TE4, TE8, TE9: whole texts, strings shown by safe_text (no quotes)
        self.assertEqual(errs(good(finding=F2), finding=F), ["finding: expected " + F + ", got " + F2])
        self.assertEqual(errs(good(test="u"), test="t"), ["test: expected t, got u"])
        runs = [(1, "fix", 0), (2, "mutant", 1), (3, "fix", 0)]
        lines = [run_line(n, p, c, D if n != 2 else "other") for n, p, c in runs]
        self.assertEqual(errs(T("FINDING " + F, "TEST t", "MUTANT m", *lines)),
                         ["RUN 2: command: expected " + D + ", got other"])
        e = errs(good(runs=[(1, "fix", 1), (2, "mutant", 0), (3, "fix", 2)]))
        self.assertEqual(e, ["RUN 1: exit 1: a run on the fixed code must exit 0",
                             "RUN 2: exit 0: the run with the mutant must fail, so it exits non-zero and neither 126 nor 127",
                             "RUN 3: exit 2: a run on the fixed code must exit 0"])

    def test_finding_problem_is_about_the_transcript_value(self):  # TE3: the transcript's own id is the one checked
        e = errs(good(finding=DEC), finding=F)
        self.assertEqual(len(e), 2)
        self.assertEqual(e[0], "finding: expected " + F + ", got " + DEC)
        self.assertEqual(e[1], "finding: " + ids.id_problem(DEC, "F"))

    def test_finding_equals(self):  # TE2
        self.assertEqual(errs(good(finding=F), finding=F), [])
        self.assertNames(errs(good(finding=F), finding=F2), "finding")
        self.assertNames(errs(good(finding=F), finding="f-20261031-zzzz"), "finding")

    def test_finding_prefix_checked(self):  # TE3
        e = errs(good(finding=DEC), finding=DEC)
        self.assertEqual(e, ["finding: " + ids.id_problem(DEC, "F")])
        self.assertIn("id does not match the form", e[0])
        e = errs(good(finding="F-20261331-zzzz"), finding="F-20261331-zzzz")
        self.assertEqual(len(e), 1)
        self.assertIn("id date 20261331 is not a valid calendar date", e[0])
        e = errs(parsed_of(finding=F), finding=F)
        self.assertEqual(e, [])
        p = parse_transcript(T("FINDING F-20261031-zzzz", "TEST t", "MUTANT m", *[run_line(n, ph, c) for n, ph, c in OK_RUNS]))
        p["finding"] = ["F-20261031-zzz0"]
        self.assertNames(transcript_errors(p, "F-20261031-zzz0", "t", D, cfg()), "finding")

    def test_finding_prefix_follows_cfg(self):  # TE3: the prefix is cfg["ids"]["finding"], not a literal
        c = cfg()
        c["ids"]["finding"] = "Q"
        e = transcript_errors(parsed_of(finding="Q-20261031-zzzz"), "Q-20261031-zzzz", "t", D, c)
        self.assertEqual(e, [])
        e = transcript_errors(parsed_of(finding=F), F, "t", D, c)
        self.assertEqual(len(e), 1)
        self.assertIn("finding", e[0])

    def test_test_equals_exact(self):  # TE4
        self.assertEqual(errs(good(test="t"), test="t"), [])
        for name, got, want in [("off", "u", "t"), ("trail space", "t ", "t"), ("trail cr", "t\r", "t"), ("case", "T", "t"),
                                ("lead space", " t", "t")]:
            with self.subTest(name):
                self.assertNames(errs(good(test=got), test=want), "test")

    def test_runs_count(self):  # TE5
        self.assertEqual(errs(good()), [])
        for name, runs in [("two", OK_RUNS[:2]), ("four", OK_RUNS + [(1, "fix", 0)]), ("zero", [])]:
            with self.subTest(name):
                self.assertNames(errs(good(runs=runs)), "RUN")
                self.assertNames(errs(good(runs=runs)), "RUN: expected exactly three lines, got %s" % len(runs))

    def test_run_numbers_in_order(self):  # TE6
        for name, runs in [("1,3,2", [(1, "fix", 0), (3, "mutant", 1), (2, "fix", 0)]),
                           ("2,1,3", [(2, "fix", 0), (1, "mutant", 1), (3, "fix", 0)]),
                           ("1,1,3", [(1, "fix", 0), (1, "mutant", 1), (3, "fix", 0)]),
                           ("1,2,2", [(1, "fix", 0), (2, "mutant", 1), (2, "fix", 0)])]:
            with self.subTest(name):
                self.assertNames(errs(good(runs=runs)), "RUN")

    def test_run_phases(self):  # TE7
        for name, runs in [("fix x3", [(1, "fix", 0), (2, "fix", 0), (3, "fix", 0)]),
                           ("mutant,fix,mutant", [(1, "mutant", 1), (2, "fix", 0), (3, "mutant", 1)]),
                           ("fix,mutant,mutant", [(1, "fix", 0), (2, "mutant", 1), (3, "mutant", 1)])]:
            with self.subTest(name):
                self.assertNames(errs(good(runs=runs)), "phase")

    def test_command_equals_exact(self):  # TE8
        self.assertEqual(errs(good(cmd=D), cmd=D), [])
        for i in range(3):
            lines = [run_line(n, p, c, D if n != i + 1 else D + "x") for n, p, c in OK_RUNS]
            with self.subTest(i):
                e = errs(T("FINDING " + F, "TEST t", "MUTANT m", *lines))
                self.assertEqual(len(e), 1)
                self.assertNames(e, "command", "RUN %d" % (i + 1))
        self.assertNames(errs(good(cmd=D + " "), cmd=D), "command")
        self.assertNames(errs(good(cmd=D), cmd=D + " "), "command")
        self.assertNames(errs(good(cmd="R"), cmd="r"), "command")

    def test_run1_exit(self):  # TE9
        for code, ok in [(0, True), (1, False), (126, False), (-1, False)]:
            with self.subTest(code):
                e = errs(good(runs=[(1, "fix", code), (2, "mutant", 1), (3, "fix", 0)]))
                self.assertEqual(e == [], ok, e)
                if not ok:
                    self.assertNames(e, "RUN 1", "exit")

    def test_run3_exit(self):  # TE10
        for code, ok in [(0, True), (1, False), (127, False)]:
            with self.subTest(code):
                e = errs(good(runs=[(1, "fix", 0), (2, "mutant", 1), (3, "fix", code)]))
                self.assertEqual(e == [], ok, e)
                if not ok:
                    self.assertNames(e, "RUN 3", "exit")

    def test_run2_exit_set(self):  # TE11: controller ruling, 126 and 127 are no failing test
        table = [(0, False), (1, True), (2, True), (126, False), (127, False), (-11, True), (255, True), (128, True),
                 (143, True), (256, True), (-126, True), (-127, True), (999, True), (-999, True), (-1, True)]
        for code, ok in table:
            with self.subTest(code):
                e = errs(good(runs=[(1, "fix", 0), (2, "mutant", code), (3, "fix", 0)]))
                self.assertEqual(e == [], ok, e)
                if not ok:
                    self.assertNames(e, "RUN 2", "exit")

    def test_pc1_long_exit(self):  # TE12, K1a: D-1-Q1 bounds the pattern, one verdict on both interpreters
        for limit in INT_LIMITS:
            with int_limit(limit):
                for digits in (4300, 4301, 641):
                    for sign in ("", "-"):
                        for n, ph in ((1, "fix"), (2, "mutant"), (3, "fix")):
                            with self.subTest(limit=limit, digits=digits, sign=sign, n=n):
                                lines = [run_line(k, p, c) for k, p, c in OK_RUNS]
                                lines[n - 1] = "RUN %d %s exit=%s%s command=%s" % (n, ph, sign, "9" * digits, D)
                                with self.assertRaises(ValueError) as cm:
                                    parse_transcript(T("FINDING " + F, "TEST t", "MUTANT m", *lines))
                                self.assertIn("RUN", str(cm.exception))
                                self.assertNotIn("9" * 10, str(cm.exception))

    def test_error_text_uses_safe_text(self):  # TE13, K2d
        for bad in [U_NEW, "\0", "\r", U_LOW, "\x1b"]:
            with self.subTest(repr(bad)):
                e = transcript_errors(parsed_of(test="t" + bad, cmd=D + bad), F, "u" + bad, D + "z", cfg())
                self.assertTrue(e)
                from gates.lib.result import safe_text
                joined = "\n".join(e)
                self.assertNotIn("\n" + bad, joined)
                self.assertIn(safe_text("t" + bad), joined)
                self.assertIn(safe_text("u" + bad), joined)
                self.assertIn(safe_text(D + bad), joined)
                self.assertEqual(len(joined.split("\n")), len(e))  # every message is one line
        e = errs(good(test="t" + U_NEW), test="u" + U_NEW)
        self.assertIn("t\\U0001f6dd", "\n".join(e))  # the frozen Unicode 13 table: unprintable on both interpreters

    def test_pc1_message_uses_frozen_table(self):  # K2d, K2e
        self.assertFalse(print_table.is_printable(U_NEW))
        e = errs(good(test="t" + U_NEW + U_LOW), test="x")
        # both code points are unassigned in the frozen Unicode 13 table, so both are escaped, on both interpreters
        self.assertEqual(e, ["test: expected x, got t\\U0001f6dd\\ua7c0"])

    def test_pc1_no_huge_int_format(self):  # K1e
        p = parsed_of()
        for limit in INT_LIMITS:
            with int_limit(limit):
                p["runs"][1]["exit"] = 0
                e = transcript_errors(p, F, "t", D, cfg())
                self.assertEqual(len(e), 1)
                self.assertIn("exit", e[0])
                p["runs"][1]["exit"] = 10 ** 5000
                with self.assertRaises(GateError) as cm:
                    transcript_errors(p, F, "t", D, cfg())
                self.assertLess(len(str(cm.exception)), 200)

    def test_errors_accumulate(self):  # TE14
        p = parse_transcript(good(finding=F2, runs=[(1, "fix", 0), (2, "mutant", 0), (3, "fix", 0), (3, "fix", 0)]))
        e = transcript_errors(p, F, "t", D, cfg())
        self.assertNames(e, "finding", "RUN")
        self.assertGreaterEqual(len(e), 3)
        self.assertNames(e, "RUN 2")

    def test_parsed_shape_guard(self):  # TE15, Y8, Y12
        for name, bad in [("empty", {}), ("no runs", {"finding": [F], "test": ["t"], "mutant": ["m"]}),
                          ("runs not list", dict(parsed_of(), runs=())), ("runs list subclass", dict(parsed_of(), runs=L(parsed_of()["runs"]))),
                          ("run missing exit", dict(parsed_of(), runs=[{"n": 1, "phase": "fix", "command": D}])),
                          ("non-dict", []), ("True", True), ("None", None), ("dict subclass", Dd(parsed_of())),
                          ("run not dict", dict(parsed_of(), runs=["x"])),
                          ("run is a list of the keys", dict(parsed_of(), runs=[["n", "phase", "exit", "command"]])),
                          ("run dict subclass", dict(parsed_of(), runs=[Dd(parsed_of()["runs"][0])])),
                          ("finding scalar", dict(parsed_of(), finding=F)), ("finding list subclass", dict(parsed_of(), finding=L([F]))),
                          ("test item not str", dict(parsed_of(), test=[1])), ("mutant item str subclass", dict(parsed_of(), mutant=[S("m")])),
                          ("extra run key", dict(parsed_of(), runs=[dict(r, extra=1) for r in parsed_of()["runs"]])),
                          ("n bool", dict(parsed_of(), runs=[dict(r, n=True) if r["n"] == 1 else r for r in parsed_of()["runs"]])),
                          ("exit bool", dict(parsed_of(), runs=[dict(r, exit=True) if r["n"] == 2 else r for r in parsed_of()["runs"]])),
                          ("exit str", dict(parsed_of(), runs=[dict(r, exit="1") if r["n"] == 2 else r for r in parsed_of()["runs"]])),
                          ("phase int", dict(parsed_of(), runs=[dict(r, phase=1) if r["n"] == 2 else r for r in parsed_of()["runs"]])),
                          ("command subclass", dict(parsed_of(), runs=[dict(r, command=S(D)) if r["n"] == 2 else r for r in parsed_of()["runs"]])),
                          ("exit out of range", dict(parsed_of(), runs=[dict(r, exit=1000) if r["n"] == 2 else r for r in parsed_of()["runs"]])),
                          ("n out of range", dict(parsed_of(), runs=[dict(r, n=-1000) if r["n"] == 1 else r for r in parsed_of()["runs"]]))]:
            with self.subTest(name):
                with self.assertRaises(GateError) as cm:
                    transcript_errors(bad, F, "t", D, cfg())
                self.assertIn("parsed", str(cm.exception))

    def test_cfg_shape_guard(self):  # TE16, Y10
        c = cfg()
        for name, bad in [("empty", {}), ("no ids", {k: v for k, v in c.items() if k != "ids"}),
                          ("ids no finding", dict(c, ids={})), ("ids not dict", dict(c, ids=[])),
                          ("finding not str", dict(c, ids=dict(c["ids"], finding=1))), ("None", None), ("True", True),
                          ("list", []), ("dict subclass", Dd(c)), ("ids dict subclass", dict(c, ids=Dd(c["ids"]))),
                          ("finding str subclass", dict(c, ids=dict(c["ids"], finding=S("F"))))]:
            with self.subTest(name):
                with self.assertRaises(GateError) as cm:
                    transcript_errors(parsed_of(), F, "t", D, bad)
                self.assertIn("cfg", str(cm.exception))

    def test_transcript_errors_arg_types(self):  # TE17, Y9
        for pname in ("finding_id", "test_id", "command"):
            for bad in [True, None, 5, S("x"), b"x"]:
                with self.subTest(pname, bad=repr(bad)):
                    args = {"finding_id": F, "test_id": "t", "command": D}
                    args[pname] = bad
                    with self.assertRaises(GateError) as cm:
                        transcript_errors(parsed_of(), args["finding_id"], args["test_id"], args["command"], cfg())
                    self.assertIn(pname, str(cm.exception))

    def test_parsed_is_not_modified(self):
        p = parsed_of()
        before = copy.deepcopy(p)
        errs(p)
        self.assertEqual(p, before)

    def test_pc1_unicode_test_id(self):  # K2a
        for ch in (U_NEW, U_LOW, U_ANY):
            with self.subTest(repr(ch)):
                t = "t" + ch
                self.assertEqual(errs(good(test=t), test=t), [])
                d, _ = render_pin({"commands": {"test_one": "runtests -k {id}"}}, t)
                self.assertEqual(d, "runtests -k " + shlex.quote(t))
                self.assertEqual(d, "runtests -k '%s'" % t)

    def test_pc1_unicode_command(self):  # K2b
        c = "runtests " + U_NEW + U_LOW + U_ANY
        self.assertEqual(errs(good(cmd=c), cmd=c), [])
        lines = [run_line(n, p, code, c) for n, p, code in OK_RUNS]
        lines[1] = run_line(2, "mutant", 1, "runtests " + U_NEW + U_LOW2 + U_ANY)
        e = errs(T("FINDING " + F, "TEST t", "MUTANT m", *lines), cmd=c)
        self.assertEqual(len(e), 1)
        self.assertIn("RUN 2", e[0])

    def test_pc1_unicode_free_text(self):  # K2c
        text = good(mutant="m" + U_NEW + U_LOW, extra=[" out " + U_NEW + U_LOW + U_ANY, "note " + U_NEW])
        self.assertEqual(errs(text), [])

    def test_pc1_long_digit_text(self):  # K1d
        for limit in INT_LIMITS:
            with int_limit(limit):
                big = "9" * 4301
                self.assertEqual(errs(good(test=big, cmd=big), test=big, cmd=big), [])
                self.assertEqual(errs(good(extra=[" " + big])), [])
                self.assertNames(errs(good(test=big), test=big[:-1]), "test")


# ---------------------------------------------------------------- RL, PE, SP
class ReportLines(SchemaCase):
    def test_pin_sha_bounds(self):  # RL3, K1c
        ok = ["a" * 7, "a" * 40, "0123456789abcdef0123456789abcdef01234567"]
        bad = ["a" * 6, "a" * 41, "ABCDEF0", "a" * 4300, "a" * 4301, "g" * 7, "١" * 7, "ａ" * 7]
        for sha in ok:
            with self.subTest(sha):
                self.assertEqual(self.rl(R("PIN %s transcript=%s:p" % (F, sha))), [])
        for sha in bad:
            with self.subTest(sha[:10], n=len(sha)):
                self.assertEqual(len(self.rl(R("PIN %s transcript=%s:p" % (F, sha)))), 1)
        for line in ["PIN %s transcript=%s:" % (F, SHA), "PIN %s transcript=%s" % (F, SHA), "PIN %s transcript=:p" % F,
                     "PIN %s transcript=%s p" % (F, SHA), "PIN %s transcript=" % F]:
            with self.subTest(line):
                self.assertEqual(len(self.rl(R(line))), 1)

    def test_pin_path_free(self):  # RL4
        for path in ["a:b", "a b", "a\r", "a ", "/abs", "../x", "a#b"]:
            with self.subTest(path):
                self.assertEqual(self.rl(R("PIN %s transcript=%s:%s" % (F, SHA, path))), [])

    def test_pin_id_shape(self):  # RL5
        for fid in [DEC, "F-20261331-zzzz"]:
            with self.subTest(fid):
                self.assertEqual(self.rl(R("PIN %s transcript=%s:p" % (fid, SHA))), [])
        for fid in ["F-20261031-zzz0", "f-20261031-zzzz", "F-20261031-zzzzz", "", "F-2026103-zzzz", "F-202610311-zzzz",
                    "F-20261031-zzz", "-20261031-zzzz", "1-20261031-zzzz"]:
            with self.subTest(fid):
                self.assertEqual(len(self.rl(R("PIN %s transcript=%s:p" % (fid, SHA)))), 1)
                self.assertEqual(len(self.rl(R("PIN-TEST %s t" % fid))), 1)
                self.assertEqual(len(self.rl(R("PIN-COMMAND %s c" % fid))), 1)
        for fid in [F, DEC, "AB-20261331-zzzz"]:
            with self.subTest(fid):
                self.assertEqual(self.rl(R("PIN-TEST %s t" % fid, "PIN-COMMAND %s c" % fid)), [])

    def test_pin_test_line(self):  # RL6
        self.assertEqual(self.rl(R("PIN-TEST %s adds totals" % F)), [])
        self.assertEqual(self.rl(R("PIN-TEST %s t%s" % (F, U_NEW))), [])
        self.assertEqual(self.rl(R("PIN-TEST %s  " % F)), [])  # id + two spaces: the test is " "
        for line in ["PIN-TEST " + F, "PIN-TEST %s " % F, "PIN-TEST", "PIN-TEST  x"]:
            with self.subTest(line):
                self.assertEqual(len(self.rl(R(line))), 1)

    def test_pin_command_line(self):  # RL7
        self.assertEqual(self.rl(R("PIN-COMMAND %s %s" % (F, D))), [])
        for line in ["PIN-COMMAND " + F, "PIN-COMMAND: %s %s" % (F, D), "PIN-COMMAND %s " % F]:
            with self.subTest(line):
                self.assertEqual(len(self.rl(R(line))), 1)

    def test_report_keyword_forms(self):  # RL8
        self.assertEqual(len(self.rl(R("PIN: %s transcript=%s:p" % (F, SHA)))), 1)
        for line in ["pin " + F, "PIN-TESTX %s x" % F, " PIN %s transcript=bad" % F, "see PIN bad", "PIN-COMMANDS x"]:
            with self.subTest(line):
                self.assertEqual(self.rl(R(line)), [])

    def test_report_first_line(self):  # RL9, D-1-Q3 (a)
        want = ["first line: expected '%s'" % TAG_R]
        for name, text in [("empty", ""), ("bom", "﻿" + TAG_R + "\n"), ("crlf", R("prose").replace("\n", "\r\n")),
                           ("transcript tag", TAG_T + "\n"), ("v2", "<!-- schema: review-report/2 -->\n")]:
            with self.subTest(name):
                self.assertEqual(self.rl(text), want)
        for text in [TAG_R, TAG_R + "\n", R("prose " + U_NEW)]:
            with self.subTest(text):
                self.assertEqual(self.rl(text), [])

    def test_report_without_pins_valid(self):  # RL10
        self.assertEqual(self.rl(R("prose")), [])


class PackageEntries(GitIsolatedTestCase):
    def test_package_entries_full(self):  # PE1
        self.assertEqual(package_entries(R(*group())), {F: {"transcript": SHA + ":" + TP, "test": "t", "command": D}})

    def test_report_without_pins_is_empty(self):  # PE2
        self.assertEqual(package_entries("<!-- schema: review-report/1 -->\nprose\n"), {})
        self.assertEqual(package_entries(TAG_R), {})

    def test_package_group_incomplete_raises(self):  # PE3
        g = group()
        for name, lines, missing in [("no test", [g[0], g[2]], "PIN-TEST"), ("no command", g[:2], "PIN-COMMAND")]:
            with self.subTest(name):
                with self.assertRaises(ValueError) as cm:
                    package_entries(R(*lines))
                self.assertIn(F, str(cm.exception))
                self.assertIn(missing, str(cm.exception))

    def test_package_orphan_lines_raise(self):  # PE4
        g = group()
        for name, lines, kw in [("test alone", [g[1]], "PIN"), ("command alone", [g[2]], "PIN"),
                                ("test+command", g[1:], "PIN"), ("no pin, but a full other group", group(F2) + [g[1]], "PIN")]:
            with self.subTest(name):
                with self.assertRaises(ValueError) as cm:
                    package_entries(R(*lines))
                self.assertIn(kw, str(cm.exception))

    def test_package_repeats_raise(self):  # PE5
        g = group()
        for name, extra in [("PIN", g[0]), ("PIN same", "PIN %s transcript=%s:%s" % (F, SHA, TP)),
                            ("PIN-TEST", g[1]), ("PIN-TEST other", "PIN-TEST %s u" % F),
                            ("PIN-COMMAND", g[2]), ("PIN-COMMAND other", "PIN-COMMAND %s other" % F)]:
            with self.subTest(name):
                with self.assertRaises(ValueError) as cm:
                    package_entries(R(*(g + [extra])))
                self.assertIn(F, str(cm.exception))

    def test_package_two_findings_interleaved(self):  # PE6
        a, b = group(F, "ta", "ca", "abcdef1", "pa"), group(F2, "tb", "cb", "abcdef2", "pb")
        text = R(a[0], b[0], b[1], a[1], b[2], "prose", a[2])
        self.assertEqual(package_entries(text), {F: {"transcript": "abcdef1:pa", "test": "ta", "command": "ca"},
                                                 F2: {"transcript": "abcdef2:pb", "test": "tb", "command": "cb"}})

    def test_package_transcript_text(self):  # PE7
        self.assertEqual(package_entries(R(*group(sha="abcdef0", path="a:b")))[F]["transcript"], "abcdef0:a:b")
        for name, line in [("6 hex", "PIN %s transcript=abcdef:p" % F), ("no path", "PIN %s transcript=%s:" % (F, SHA))]:
            with self.subTest(name):
                with self.assertRaises(ValueError):
                    package_entries(R(line, group()[1], group()[2]))

    def test_package_foreign_prefix(self):  # PE8, D-1-Q11 (a)
        self.assertEqual(list(package_entries(R(*group(DEC)))), [DEC])

    def test_package_text_not_stripped(self):  # PE9
        e = package_entries(R(group()[0], "PIN-TEST %s  x" % F, "PIN-COMMAND %s %s;'\"%s " % (F, D, U_NEW)))
        self.assertEqual(e[F]["test"], " x")
        self.assertEqual(e[F]["command"], "%s;'\"%s " % (D, U_NEW))

    def test_package_schema_errors_raise(self):  # PE10
        g = R(*group())
        for name, text in [("no first line", "\n".join(group()) + "\n"), ("crlf", g.replace("\n", "\r\n")),
                           ("bom", "﻿" + g), ("bad pin", R("PIN %s transcript=abc:p" % F))]:
            with self.subTest(name):
                with self.assertRaises(ValueError):
                    package_entries(text)

    def test_package_text_not_str(self):  # PE11, Y7
        for v in [None, b"", True, S(R()), 5]:
            with self.subTest(repr(v)):
                with self.assertRaises(ValueError) as cm:
                    package_entries(v)
                self.assertEqual(str(cm.exception), "first line: text must be a string")

    def test_package_prose_ignored(self):  # PE12
        self.assertEqual(package_entries(R(" PIN %s transcript=%s:p" % (F, SHA), "see PIN " + F, "pin x")), {})

    def test_package_large(self):  # PE13
        ids_ = ["F-20261031-%04d" % i for i in range(5000)]
        # 0-9 digits are not in the id alphabet, so use letters
        alpha = "23456789abcdefghijkmnpqrstuvwxyz"
        ids_ = ["F-20261031-%s%s%s%s" % (alpha[i // 32768 % 32], alpha[i // 1024 % 32], alpha[i // 32 % 32], alpha[i % 32])
                for i in range(5000)]
        lines = []
        for i in ids_:
            lines += group(i)
        e = package_entries(R(*lines))
        self.assertEqual(len(e), 5000)
        self.assertEqual(e[ids_[4999]], {"transcript": SHA + ":" + TP, "test": "t", "command": D})
        self.assertEqual(package_entries(R(*([" free"] * 100000))), {})

    def test_package_via_show_roundtrip(self):  # PE14
        root = make_repo(self.work, minimal_config())
        write_bytes(root, "docs/strict-delivery/reviews/p/r.md", R("prose", *group()).encode("utf-8"))
        sha = commit_all(root, "t")
        back = gitinfo.show(root, sha, "docs/strict-delivery/reviews/p/r.md")
        self.assertEqual(package_entries(back), {F: {"transcript": SHA + ":" + TP, "test": "t", "command": D}})


class SplitCite(unittest.TestCase):
    def test_split_cite_sha_bounds(self):  # SP1, K1c
        for n in (7, 40):
            self.assertEqual(split_cite("a" * n + ":p"), ("a" * n, "p"))
        for n in (6, 41, 4300, 4301):
            with self.subTest(n):
                for limit in INT_LIMITS:
                    with int_limit(limit):
                        self.assertIsNone(split_cite("a" * n + ":p"))
        self.assertEqual(split_cite("0123456789abcdef0123456789abcdef01234567:x"), ("0123456789abcdef0123456789abcdef01234567", "x"))

    def test_split_cite_alphabet(self):  # SP2
        for sha in ["ABCDEF0", "abcdefg", "١" * 7, "ａ" * 7, "abcdefé"]:
            with self.subTest(sha):
                self.assertIsNone(split_cite(sha + ":p"))

    def test_split_cite_separator(self):  # SP3
        for e in ["abcdef0", "abcdef0p", ":abcdef0", ":p", "abcdef0:", "", "abc def:p", "abcdef0\n:p", " abcdef0:p"]:
            with self.subTest(e):
                self.assertIsNone(split_cite(e))

    def test_split_cite_path_not_validated(self):  # SP4
        for path in ["a:b", "a#b", "/abs", "../x", "\n", " ", ":", "::", "a b"]:
            with self.subTest(repr(path)):
                self.assertEqual(split_cite("abcdef0:" + path), ("abcdef0", path))

    def test_split_cite_agrees_with_findings_split(self):  # SP5
        from gates.lib import findings
        rng = random.Random(6)
        alphabet = "abcdef0123:/xG A\n"
        for _ in range(200):
            n = rng.randint(0, 12)
            s = "".join(rng.choice(alphabet) for _ in range(n))
            if rng.random() < 0.5:
                s = "".join(rng.choice("abcdef0123456789") for _ in range(rng.choice([6, 7, 8, 40, 41]))) + ":" + s
            kind, tail = findings._split(s)
            got = split_cite(s)
            with self.subTest(repr(s)):
                if kind == "sha-path" and tail != "":
                    self.assertEqual(got, (s.partition(":")[0], tail))
                else:
                    self.assertIsNone(got)

    def test_split_cite_arg_types(self):  # SP6, Y11
        for v in [None, True, 5, b"abcdef0:p", S("abcdef0:p"), [], ("abcdef0", "p")]:
            with self.subTest(repr(v)):
                self.assertIsNone(split_cite(v))


# ---------------------------------------------------------------- RP: render_pin
def cfg_of(template):
    c = cfg()
    c["commands"] = {"test_one": template}
    return c


STR_T = "runtests -k {id}"
LST = ["runtests", "-k", "{id}"]
BAD_IDS_RP13 = ["a b", "it's", "a;rm x", "$(x)", "`x`", 'a"b', "a\\b", "*", "~", "a#b", "!", "%", "-x", "{id}", "a&b", "a|b",
                "a>b", "a<b", "(x)", "a\tb", " lead", "trail ", "\xe9", U_NEW, U_LOW, "١", "a=b", "a,b", "a:b", "a/b", "a@b"]


class RenderPin(unittest.TestCase):
    def test_render_string_quotes_id(self):  # RP1
        d, run = render_pin(cfg_of(STR_T), "adds totals")
        self.assertEqual((d, run), ("runtests -k 'adds totals'", "runtests -k 'adds totals'"))
        self.assertIs(type(run), str)
        self.assertEqual(render_pin(cfg_of(STR_T), "a;rm x")[0], "runtests -k 'a;rm x'")

    def test_render_string_every_id(self):  # RP2
        self.assertEqual(render_pin(cfg_of("a {id} b {id}"), "x y")[0], "a 'x y' b 'x y'")

    def test_render_refuses_bad_templates(self):  # RP3, RP6, RP7, Y3
        for name, tmpl in [("no id", "runtests"), ("list no id", ["runtests", "-k"]), ("empty", ""), ("empty list", []),
                           ("non-str element", [1]), ("None element", ["a", None]), ("int", 3), ("bool", True), ("None", None),
                           ("dict", {}), ("tuple", ("a", "{id}")), ("list holding bool", [True, "{id}"]),
                           ("elem str subclass only", [S("{id}")]), ("id in a non-str", ["a", 1, "{id}"]), ("float", 1.5),
                           ("bytes", b"x {id}"), ("nested list", [["{id}"]])]:
            with self.subTest(name):
                c = cfg()
                c["commands"] = {"test_one": tmpl}
                with self.assertRaises(GateError) as cm:
                    render_pin(c, "x")
                self.assertIn("commands.test_one", str(cm.exception))

    def test_render_list_has_no_shell(self):  # RP4
        d, run = render_pin(cfg_of(LST), "a b")
        self.assertEqual(run, ["runtests", "-k", "a b"])
        self.assertEqual(d, "runtests -k 'a b'")
        self.assertIs(type(run), list)

    def test_render_list_every_element(self):  # RP5
        d, run = render_pin(cfg_of(["x", "--only={id}", "{id}"]), "a b;c")
        self.assertEqual(run, ["x", "--only=a b;c", "a b;c"])
        self.assertEqual(d, "x '--only=a b;c' 'a b;c'")

    def test_render_template_subclasses(self):  # RP8, Y3
        for name, tmpl in [("str subclass", S("x {id}")), ("list subclass", L(["x", "{id}"])), ("dict subclass", Dd())]:
            with self.subTest(name):
                with self.assertRaises(GateError) as cm:
                    render_pin(cfg_of(tmpl), "x")
                self.assertIn("commands.test_one", str(cm.exception))

    def test_render_missing_keys(self):  # RP9, Y1
        c0 = cfg()
        for name, c in [("commands absent", {k: v for k, v in c0.items() if k != "commands"}), ("commands empty", dict(c0, commands={})),
                        ("test_one absent", dict(c0, commands={"test": "x"})), ("commands None", dict(c0, commands=None)),
                        ("commands list", dict(c0, commands=[])), ("commands str", dict(c0, commands="x")),
                        ("commands subclass", dict(c0, commands=Dd(test_one=STR_T))),
                        ("cfg None", None), ("cfg True", True), ("cfg list", []), ("cfg subclass", Dd(cfg_of(STR_T))),
                        ("empty cfg", {})]:
            with self.subTest(name):
                with self.assertRaises(GateError) as cm:
                    render_pin(c, "x")
                self.assertIn("commands.test_one", str(cm.exception))

    def test_render_id_spellings(self):  # RP10
        for t in ["{ID}", "{id }", "{ id}", "id", "{i d}", "{}"]:
            with self.subTest(t):
                with self.assertRaises(GateError):
                    render_pin(cfg_of("x " + t), "x")
        self.assertEqual(render_pin(cfg_of("x {{id}}"), "ab")[0], "x {ab}")
        self.assertEqual(render_pin(cfg_of("x {{id}}"), "a b")[0], "x {'a b'}")

    def test_render_no_reexpansion(self):  # RP11
        self.assertEqual(render_pin(cfg_of(STR_T), "{id}")[0], "runtests -k '{id}'")
        self.assertEqual(render_pin(cfg_of(STR_T), "a{id}b")[0], "runtests -k 'a{id}b'")
        self.assertEqual(render_pin(cfg_of(LST), "{id}")[1], ["runtests", "-k", "{id}"])

    def test_render_plain_id_unquoted(self):  # RP12
        self.assertEqual(render_pin(cfg_of(STR_T), "adds_totals_1")[0], "runtests -k adds_totals_1")
        self.assertEqual(render_pin(cfg_of(STR_T), "a/b.py::T.t-1@2%x+y=z:w,v")[0], "runtests -k a/b.py::T.t-1@2%x+y=z:w,v")

    def test_render_quotes_metacharacters(self):  # RP13 (display)
        for i in BAD_IDS_RP13:
            with self.subTest(repr(i)):
                self.assertEqual(render_pin(cfg_of(STR_T), i)[0], "runtests -k " + shlex.quote(i))
                self.assertEqual(shlex.split(render_pin(cfg_of(STR_T), i)[0]), ["runtests", "-k", i])
                self.assertEqual(shlex.split(render_pin(cfg_of(LST), i)[0]), ["runtests", "-k", i])
        self.assertEqual(render_pin(cfg_of(STR_T), "it's")[0], """runtests -k 'it'"'"'s'""")
        self.assertEqual(render_pin(cfg_of(STR_T), "$(x)")[0], "runtests -k '$(x)'")
        self.assertEqual(render_pin(cfg_of(STR_T), "-x")[0], "runtests -k -x")

    def test_render_non_ascii_id(self):  # RP14
        for i in ["\xe9", U_NEW, U_LOW, "١"]:
            with self.subTest(repr(i)):
                self.assertEqual(render_pin(cfg_of(STR_T), i)[0], "runtests -k '%s'" % i)

    def test_render_refuses_bad_ids(self):  # RP15, RP16, RP17, D-1-Q4
        for name, i in [("empty", ""), ("newline", "a\nb"), ("newline only", "\n"), ("trailing newline", "a\n"), ("cr", "a\rb"),
                        ("cr only", "\r"), ("crlf", "a\r\nb"), ("nul", "a\0b"), ("nul only", "\0"), ("surrogate", "a\ud800b"),
                        ("low surrogate", "\udfff")]:
            for tname, tmpl in [("str", STR_T), ("list", LST)]:
                with self.subTest(name, form=tname):
                    with self.assertRaises(GateError) as cm:
                        render_pin(cfg_of(tmpl), i)
                    self.assertIn("test_id", str(cm.exception))

    def test_render_edge_characters(self):  # RP17: accepted and quoted
        for name, i in [("tab", "a\tb"), ("del", "a\x7fb"), ("u2028", "a b"), ("nel", "a\x85b"), ("space only", " "),
                        ("lead", " a"), ("trail", "a "), ("vt", "a\x0bb"), ("esc", "\x1b[0m")]:
            with self.subTest(name):
                d, run = render_pin(cfg_of(STR_T), i)
                self.assertEqual(shlex.split(d), ["runtests", "-k", i])
                self.assertEqual(render_pin(cfg_of(LST), i)[1], ["runtests", "-k", i])

    def test_render_long_id(self):  # RP18, K1d
        for n in (4301, 100000):
            i = "9" * n
            for limit in INT_LIMITS:
                with int_limit(limit):
                    self.assertEqual(render_pin(cfg_of(STR_T), i)[0], "runtests -k " + i)
                    self.assertEqual(render_pin(cfg_of(LST), i)[1], ["runtests", "-k", i])

    def test_render_id_types(self):  # RP19, Y2
        for v in [None, True, 5, b"x", S("x"), ["x"]]:
            with self.subTest(repr(v)):
                with self.assertRaises(GateError) as cm:
                    render_pin(cfg_of(STR_T), v)
                self.assertIn("test_id", str(cm.exception))

    def test_render_list_element_edges(self):  # RP20, D-1-Q13 (a)
        self.assertEqual(render_pin(cfg_of([""]  + ["{id}"]), "x")[1], ["", "x"])
        self.assertEqual(render_pin(cfg_of(["{id}"]), "x")[1], ["x"])
        self.assertEqual(render_pin(cfg_of(["{id}", ""]), "x")[1], ["x", ""])
        self.assertEqual(render_pin(cfg_of(["", "{id}"]), "x")[0], "'' x")

    def test_render_nul_in_template_refused(self):  # unstated, narrowing: a template that exec could not run
        for tmpl in ["a\0 {id}", ["a\0", "{id}"], ["a", "{id}\0"], "a\ud800 {id}", ["\ud800", "{id}"], "a\udfff {id}",
                     ["{id}", "\udfff"], "a\udc80 {id}"]:
            with self.subTest(repr(tmpl)):
                with self.assertRaises(GateError) as cm:
                    render_pin(cfg_of(tmpl), "x")
                self.assertIn("commands.test_one", str(cm.exception))

    def test_render_does_not_mutate(self):  # RP21
        c = cfg_of(list(LST))
        before = copy.deepcopy(c)
        render_pin(c, "a b")
        self.assertEqual(c, before)
        self.assertEqual(c["commands"]["test_one"], LST)
        _, run = render_pin(c, "a b")
        run.append("z")
        self.assertEqual(c["commands"]["test_one"], LST)

    def test_render_pure(self):  # RP22
        c = cfg_of(STR_T)
        self.assertEqual(render_pin(c, "a b"), render_pin(c, "a b"))

    def test_render_returns_tuple_of_two(self):
        r = render_pin(cfg_of(STR_T), "x")
        self.assertIs(type(r), tuple)
        self.assertEqual(len(r), 2)


# ---------------------------------------------------------------- RN: run_pin
class RunPin(GitIsolatedTestCase):
    def setUp(self):
        super().setUp()
        self.root = make_repo(self.work, minimal_config())
        self.scripts = os.path.join(self.tmp, "scripts")
        os.mkdir(self.scripts)

    def script(self, name, body):
        p = os.path.join(self.scripts, name)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(body)
        return p

    def py(self, name, body):
        return [sys.executable, self.script(name, body)]

    def test_run_pin_exit_codes(self):  # RN1, RN2
        for code in (0, 1, 2, 3):
            with self.subTest("shell", code=code):
                self.assertEqual(run_pin(self.root, "exit %d" % code), code)
            with self.subTest("list", code=code):
                argv = self.py("e%d.py" % code, "import sys\nsys.exit(%d)\n" % code)
                self.assertEqual(run_pin(self.root, argv), code)

    def test_run_pin_missing_program(self):  # RN3
        self.assertEqual(run_pin(self.root, ["/no/such/prog"]), 127)
        self.assertEqual(run_pin(self.root, "no_such_prog_xyz_6e1"), 127)

    def test_run_pin_not_executable_forms_differ(self):  # RN4
        p = self.script("noexec.sh", "exit 0\n")
        os.chmod(p, 0o644)
        self.assertEqual(run_pin(self.root, [p]), 127)  # PermissionError is an OSError
        self.assertEqual(run_pin(self.root, shlex.quote(p)), 126)  # the shell's "found but not executable"

    def test_run_pin_signal_codes(self):  # RN5: no kill command; the child signals itself
        argv = self.py("term.py", "import signal\nsignal.raise_signal(signal.SIGTERM)\n")
        self.assertEqual(run_pin(self.root, argv), -15)
        self.assertEqual(run_pin(self.root, " ".join(shlex.quote(a) for a in argv)), -15)
        self.assertEqual(run_pin(self.root, " ".join(shlex.quote(a) for a in argv) + "; exit $?"), 143)

    def test_run_pin_shell_modulo(self):  # RN6
        self.assertEqual(run_pin(self.root, "exit 256"), 0)
        self.assertEqual(run_pin(self.root, "exit -1"), 255)

    def test_run_pin_cwd(self):  # RN7
        argv = self.py("cwd.py", "import os, sys\nsys.exit(0 if os.path.realpath(os.getcwd()) == os.environ['WANT'] else 1)\n")
        with mock.patch.dict(os.environ, {"WANT": os.path.realpath(self.root)}):
            self.assertEqual(run_pin(self.root, argv), 0)
            self.assertEqual(run_pin(self.root, " ".join(shlex.quote(a) for a in argv)), 0)
            self.assertEqual(run_pin(self.root, 'test "$(pwd -P)" = "$WANT"'), 0)
            other = os.path.join(self.tmp, "other")
            os.mkdir(other)
            self.assertEqual(run_pin(other, argv), 1)

    def test_run_pin_bad_cwd_is_127(self):  # RN8
        self.assertEqual(run_pin(os.path.join(self.tmp, "nonexistent"), "exit 0"), 127)
        self.assertEqual(run_pin(os.path.join(self.tmp, "nonexistent"), ["x"]), 127)
        f = os.path.join(self.tmp, "afile")
        write_bytes(self.tmp, "afile", b"x")
        self.assertEqual(run_pin(f, "exit 0"), 127)

    def test_run_pin_inherits_env(self):  # RN9
        argv = self.py("env.py", "import os, sys\nsys.exit(0 if os.environ.get('EV6E1') == 'yes' else 1)\n")
        self.assertEqual(run_pin(self.root, argv), 1)
        with mock.patch.dict(os.environ, {"EV6E1": "yes"}):
            self.assertEqual(run_pin(self.root, argv), 0)
            self.assertEqual(run_pin(self.root, '[ "$EV6E1" = yes ]'), 0)

    def test_run_pin_discards_output(self):  # RN10
        argv = self.py("out.py", "import sys\nsys.stdout.write('x' * 1048576)\nsys.stderr.write('y' * 1048576)\nsys.exit(4)\n")
        self.assertEqual(run_pin(self.root, argv), 4)

    def test_run_pin_stdin(self):  # RN11, D-1-Q6 (a)
        argv = self.py("in.py", "import sys\nsys.exit(0 if sys.stdin.read() == '' else 1)\n")
        self.assertEqual(run_pin(self.root, argv), 0)

    def test_run_pin_passes_exactly_these_arguments(self):  # RN12, RN11, RN10
        import subprocess
        calls = []

        def fake(*a, **kw):
            calls.append((a, kw))
            return types.SimpleNamespace(returncode=7)

        with mock.patch.object(evidence.subprocess, "run", fake):
            self.assertEqual(run_pin(self.root, "exit 0"), 7)
            self.assertEqual(run_pin(self.root, ["a", "b"]), 7)
        self.assertEqual(calls[0], (("exit 0",), {"cwd": self.root, "shell": True, "stdin": subprocess.DEVNULL,
                                                  "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}))
        self.assertEqual(calls[1], ((["a", "b"],), {"cwd": self.root, "shell": False, "stdin": subprocess.DEVNULL,
                                                    "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}))
        for _, kw in calls:
            self.assertNotIn("timeout", kw)
            self.assertNotIn("env", kw)

    def test_run_pin_forms_agree(self):  # RN13: the child observes its argv
        script = self.script("argv.py", "import os, sys\nsys.exit(0 if sys.argv[1:] == ['-k', os.environ['EXPECT_ID']] else 1)\n")
        for i in BAD_IDS_RP13 + ["adds totals_1", "a;touch SENT_6E1", "$(touch SENT_6E1)", "`touch SENT_6E1`", "x\ny"[:1]]:
            with self.subTest(repr(i)):
                with mock.patch.dict(os.environ, {"EXPECT_ID": i}):
                    tmpl_s = "%s %s -k {id}" % (shlex.quote(sys.executable), shlex.quote(script))
                    tmpl_l = [sys.executable, script, "-k", "{id}"]
                    _, run_s = render_pin(cfg_of(tmpl_s), i)
                    _, run_l = render_pin(cfg_of(tmpl_l), i)
                    self.assertEqual(run_pin(self.root, run_s), 0)
                    self.assertEqual(run_pin(self.root, run_l), 0)
        self.assertFalse(os.path.exists(os.path.join(self.root, "SENT_6E1")))

    def test_run_pin_list_no_shell(self):  # RN18
        argv = self.py("arg.py", "import sys\nsys.exit(0 if sys.argv[1] == 'a; touch SENT_6E1' else 1)\n") + ["a; touch SENT_6E1"]
        self.assertEqual(run_pin(self.root, argv), 0)
        self.assertFalse(os.path.exists(os.path.join(self.root, "SENT_6E1")))

    def test_run_pin_run_types(self):  # RN14, Y5, D-1-Q5 (a)
        for name, v in [("None", None), ("True", True), ("int", 3), ("bytes", b"exit 0"), ("tuple", ()), ("empty list", []),
                        ("empty str", ""), ("[None]", [None]), ("mixed", ["x", 1]), ("str subclass", S("exit 0")),
                        ("list subclass", L(["x"])), ("elem subclass", [S("x")]), ("dict", {}), ("nested", [["x"]])]:
            with self.subTest(name):
                with self.assertRaises(GateError) as cm:
                    run_pin(self.root, v)
                self.assertIn("run", str(cm.exception))

    def test_run_pin_root_types(self):  # RN15, Y4
        for name, v in [("None", None), ("True", True), ("int", 5), ("bytes", b"x"), ("str subclass", S(self.root)), ("list", [])]:
            with self.subTest(name):
                with self.assertRaises(GateError) as cm:
                    run_pin(v, "exit 0")
                self.assertIn("root", str(cm.exception))

    def test_run_pin_root_nul_and_surrogate(self):  # RN15, RN16, Y4, D-1-Q5 (a), F-20261121-74tv
        bad = ["a\0b", "\0", self.root + "\0", "a\ud800b", "\ud800", "a\udfffb", "\udc80", self.root + "\ud800"]
        with mock.patch.object(evidence.subprocess, "run", side_effect=AssertionError("called")):
            for root in bad:
                for run in ["exit 0", ["x"]]:
                    with self.subTest(root=repr(root), run=type(run).__name__):
                        with self.assertRaises(GateError) as cm:
                            run_pin(root, run)
                        self.assertTrue(str(cm.exception).startswith("root:"), str(cm.exception))
            with self.subTest("bad root before bad run"):
                with self.assertRaises(GateError) as cm:
                    run_pin("a\0", "exit 0\0")
                self.assertTrue(str(cm.exception).startswith("root:"))

    def test_run_pin_root_invariants_kept(self):  # what the replaced check held, still held
        self.assertEqual(run_pin(self.root, "exit 3"), 3)  # a good root still runs
        self.assertEqual(run_pin(self.root, ["/no/such/prog"]), 127)
        for root in ["", os.path.join(self.tmp, "nonexistent")]:  # an empty or missing root is 127, as it was
            for run in ["exit 0", ["x"]]:
                with self.subTest(root=root, run=type(run).__name__):
                    self.assertEqual(run_pin(root, run), 127)
        with self.assertRaises(GateError) as cm:  # the type check is first and still names root
            run_pin(None, "exit 0\0")
        self.assertTrue(str(cm.exception).startswith("root:"))
        with self.assertRaises(GateError) as cm:  # a good root with a bad run still names run
            run_pin(self.root, "exit 0\0")
        self.assertIn("run", str(cm.exception))

    def test_run_pin_non_oserror(self):  # RN16: refused before exec, as GateError naming run
        for v in ["exit 0\0", ["a\0"], ["a", "b\0"], "a\ud800", ["\ud800"], "a\udfff", ["\udfff"], "a\udc80"]:
            with self.subTest(repr(v)):
                with self.assertRaises(GateError) as cm:
                    run_pin(self.root, v)
                self.assertIn("run", str(cm.exception))

    def test_run_pin_types_checked_before_exec(self):  # a bad type never reaches subprocess
        with mock.patch.object(evidence.subprocess, "run", side_effect=AssertionError("called")):
            for v in [None, 3, [], ""]:
                with self.assertRaises(GateError):
                    run_pin(self.root, v)
            with self.assertRaises(GateError):
                run_pin(None, "exit 0")

    def test_run_pin_only_oserror_is_127(self):  # D-1-Q5: after the checks, only OSError maps
        with mock.patch.object(evidence.subprocess, "run", side_effect=OSError("x")):
            self.assertEqual(run_pin(self.root, "exit 0"), 127)
        with mock.patch.object(evidence.subprocess, "run", side_effect=RuntimeError("x")):
            with self.assertRaises(RuntimeError):
                run_pin(self.root, "exit 0")

    def test_run_pin_returns_int(self):  # RN17
        for run in ["exit 0", "exit 5", ["/no/such/prog"]]:
            r = run_pin(self.root, run)
            self.assertIs(type(r), int)

    def test_render_then_run(self):  # RN19
        script = self.script("t.py", "import sys\nsys.exit(0 if sys.argv[1:] == ['a b;c'] else 9)\n")
        d, run = render_pin(cfg_of("%s %s {id}" % (shlex.quote(sys.executable), shlex.quote(script))), "a b;c")
        self.assertEqual(run_pin(self.root, run), 0)
        self.assertTrue(d.endswith("'a b;c'"))


# ---------------------------------------------------------------- K3, hygiene
class SourceRules(unittest.TestCase):
    def test_pc1_no_exception_group(self):  # K3
        with open(EVIDENCE_PY, encoding="utf-8") as fh:
            src = fh.read()
        for tok in ("ExceptionGroup", "BaseExceptionGroup", "except*", "except *"):
            self.assertNotIn(tok, src)

    def test_no_splitlines_no_int_format(self):  # TL4, K1e: the source never splits on splitlines nor formats an int with %d
        with open(EVIDENCE_PY, encoding="utf-8") as fh:
            src = fh.read()
        self.assertNotIn("splitlines", src)
        self.assertNotIn("%d", src)

    def test_pc1_printable_is_frozen(self):  # K2e
        self.assertFalse(print_table.is_printable(U_NEW))
        e = errs(good(test="a" + U_NEW), test="b")
        self.assertIn("\\U0001f6dd", e[0])

    def test_module_has_no_produces(self):
        self.assertFalse(hasattr(evidence, "PRODUCES"))


# ---------------------------------------------------------------- the PC2 generator
class Generated(GitIsolatedTestCase):
    """200 seeded transcripts, each a known mutation of one field of a valid one, written into one temp repository,
    committed, read back with gitinfo.show and judged by transcript_errors. The verdict of each case is written by hand
    in MUTATIONS (the controller ruling and plan :5706-5712), never computed from the code under test."""

    OTHER_IDS = [F2, "F-20260101-abcd", "F-20261231-zzzz", "F-20250505-2345"]
    RUN2_OK = [1, 2, 3, 5, 100, 128, 137, 143, 255, 256, 999, -1, -6, -9, -11, -15, -64, -126, -127, -999]
    RUN2_BAD = [0, 126, 127]
    FIX_BAD = [1, 2, 126, 127, 255, -1, -11, 100]

    def case(self, rng):
        """(name, expect_ok, transcript text, test_id, command, finding_id)."""
        test, cmd, fid = "adds totals", "runtests -k 'adds totals'", F
        runs = [(1, "fix", 0), (2, "mutant", 1), (3, "fix", 0)]
        mutant, extra = "revert the fix", []
        ok = True
        kind = rng.choice(["control", "finding", "test", "command", "run1", "run2_ok", "run2_bad", "run3", "drop_run",
                           "dup_run", "swap_phases", "renumber", "mutant_text", "output", "foreign_prefix", "test_space"])
        text_test, text_cmd, text_fid = test, cmd, fid
        cmds = [cmd, cmd, cmd]
        if kind == "finding":
            text_fid, ok = rng.choice(self.OTHER_IDS), False
        elif kind == "foreign_prefix":
            text_fid, fid, ok = "DEC-20261031-zzzz", "DEC-20261031-zzzz", False
        elif kind == "test":
            text_test, ok = test + rng.choice(["x", "2", "é", U_NEW]), False
        elif kind == "test_space":
            text_test, ok = test + " ", False
        elif kind == "command":
            i = rng.randrange(3)
            cmds[i] = rng.choice([cmd + " ", cmd + "x", cmd[:-1], cmd.upper(), cmd.replace("runtests", "runtest")])
            ok = False
        elif kind == "run1":
            runs[0] = (1, "fix", rng.choice(self.FIX_BAD)); ok = False
        elif kind == "run2_ok":
            runs[1] = (2, "mutant", rng.choice(self.RUN2_OK))
        elif kind == "run2_bad":
            runs[1] = (2, "mutant", rng.choice(self.RUN2_BAD)); ok = False
        elif kind == "run3":
            runs[2] = (3, "fix", rng.choice(self.FIX_BAD)); ok = False
        elif kind == "drop_run":
            del runs[rng.randrange(3)]; ok = False
        elif kind == "dup_run":
            runs.insert(rng.randrange(4), (rng.choice([1, 2, 3]), rng.choice(["fix", "mutant"]), 0)); ok = False
        elif kind == "swap_phases":
            runs = [(1, "mutant", 1), (2, "fix", 0), (3, "fix", 0)] if rng.random() < 0.5 else [(1, "fix", 0), (2, "fix", 0), (3, "fix", 0)]
            ok = False
        elif kind == "renumber":
            runs = [(1, "fix", 0), (3, "mutant", 1), (2, "fix", 0)]; ok = False
        elif kind == "mutant_text":
            mutant = rng.choice(["x", "commands.mutate run", "manual revert " + U_NEW, "m\t "])
        elif kind == "output":
            extra = [" " + rng.choice(["ok 1", "FAILED", "RUN 9", "TEST: x", "é"]) for _ in range(rng.randint(1, 3))]
        body = ["FINDING " + text_fid, "TEST " + text_test, "MUTANT " + mutant]
        for k, (n, p, c) in enumerate(runs):
            body.append(run_line(n, p, c, cmds[min(k, 2)]))
            if extra and k == 0:
                body += extra
        return kind, ok, T(*body), test, cmd, fid

    def test_two_hundred_seeded_transcripts(self):
        rng = random.Random(6)
        cases = [self.case(rng) for _ in range(200)]
        self.assertEqual(len({c[0] for c in cases}), 16)  # every mutation kind is drawn
        root = make_repo(self.work, minimal_config())
        for i, c in enumerate(cases):
            write_bytes(root, ".strict-delivery/state/plans/p/mutations/%03d.md" % i, c[2].encode("utf-8"))
        sha = commit_all(root, "transcripts")
        c0 = cfg()
        for i, (kind, ok, _, test, cmd, fid) in enumerate(cases):
            text = gitinfo.show(root, sha, ".strict-delivery/state/plans/p/mutations/%03d.md" % i)
            with self.subTest(i=i, kind=kind):
                got = transcript_errors(parse_transcript(text), fid, test, cmd, c0)
                self.assertEqual(got == [], ok, got)


if __name__ == "__main__":
    unittest.main()
