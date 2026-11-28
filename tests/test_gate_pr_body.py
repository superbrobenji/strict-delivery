"""Tests of gates/gate_pr_body.py and gates/lib/prbody.py (Task L2.1a, process learnings C3).

Row ids in comments refer to the Task L2.1 input-domain table (A, H, S, E, T, O, R, V) and to the controller's rows
X (exact types), G (generated inputs) and PM (the generated path matrix). Every hand-typed test of the gate runs the
production path ``python3 -m gates.gate_pr_body`` in a fresh interpreter on a real fixture repository; the generated
tests G1 and G2 call ``gate_pr_body.main`` in the test's process (stdout captured), with the root and config reads
replaced (the root rows are A2). Expected lines are typed by hand; no expectation is computed by prbody."""
import contextlib
import errno
import io
import json
import os
import random
import subprocess
import sys
import unittest
from pathlib import PurePosixPath
from unittest import mock

from gates import __main__ as gates_main
from gates import gate_pr_body
from gates.lib import prbody, result
from gates.lib.prbody import MAX_BYTES
from gates.lib.result import GateError
from gates.run_all import BASE_GATES, PROFILE_GATES
from tests.helpers import E128, TOP, GitIsolatedTestCase, make_repo, root_forms, within

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PASS = "PASS pr-body.placeholders\n"
CONFIG_MISSING = "FAIL pr-body.input: .strict-delivery/config.yml: missing; run /strict-delivery:init\n"
FF = os.fsdecode(b"\xff")  # a name holding byte 0xff (U+DCFF after fsdecode)
CLEAN = b"## Summary\n\nAll values copied from the record.\n"
POISON = b"TODO {{x}}\n"


SKIP_FF = "APFS refuses non-UTF-8 names (EILSEQ)"


def ff_or_skip(test, directory):
    """Create a directory named with byte 0xff under ``directory`` and return its path; the test is skipped when the
    file system raises ``OSError`` with errno ``EILSEQ`` (APFS), and any other error fails."""
    path = os.path.join(directory, "probe" + FF)
    try:
        os.mkdir(path)
    except OSError as e:
        if e.errno == errno.EILSEQ:
            test.skipTest(SKIP_FF)
        raise
    return path


class SubGate(GitIsolatedTestCase):
    """A fixture repository, a body file path, and the gate run in a fresh interpreter."""

    def setUp(self):
        super().setUp()
        self.root = make_repo(self.work)
        self.body = os.path.join(self.tmp, "body.md")

    def run_full(self, *argv, cwd=REPO):
        """``(exit code, stdout, stderr)`` of the production path; a hang is killed after 60 s (TimeoutExpired)."""
        p = subprocess.run([sys.executable, "-m", "gates.gate_pr_body"] + list(argv), cwd=cwd, timeout=60,
                           env=dict(os.environ, PYTHONPATH=REPO), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return p.returncode, p.stdout.decode("utf-8"), p.stderr.decode("utf-8")

    def run_args(self, *argv, cwd=REPO):
        code, out, _err = self.run_full(*argv, cwd=cwd)
        return code, out

    def run_gate(self, *args, body=None):
        argv = ["--root", self.root] + (["--body-file", body or self.body] if body is not False else []) + list(args)
        return self.run_args(*argv)

    def put(self, data):
        with open(self.body, "wb") as fh:
            fh.write(data if isinstance(data, bytes) else data.encode("utf-8"))


class PrBodyGateTest(SubGate):
    def test_clean_body_passes(self):
        self.put("## Summary\n\nFull suite: 6449 OK on both interpreters.\n")
        self.assertEqual(self.run_gate(), (0, PASS))

    def test_arguments(self):  # A1
        self.assertEqual(self.run_gate(body=False), (1, "FAIL pr-body.input: --body-file is required\n"))
        self.assertEqual(self.run_gate(body="-"), (1, "FAIL pr-body.input: --body-file -: standard input is not read\n"))
        self.assertEqual(self.run_args("--root", self.root, "--body-file="), (1, "FAIL pr-body.input: --body-file: empty\n"))
        self.put("ok\n")
        self.assertEqual(self.run_args("--root", self.root, "--body-file", self.body, "--body-file", self.body),
                         (1, "FAIL pr-body.input: invalid arguments: --body-file given more than once\n"))
        self.assertEqual(self.run_args("--root", self.root, "--body-file", self.body, "--body-file=" + self.body)[0], 1)
        self.assertEqual(self.run_args("--root", self.root, "--body-file", self.body, "extra"),
                         (1, "FAIL pr-body.input: invalid arguments: unrecognized arguments: extra\n"))

    def test_root_forms(self):  # A2
        self.put("ok\n")
        top = {"top": "ok", "top/": "ok", "link": "ok", "link/": "ok", "worktree": "ok"}
        verdicts = {"sub": TOP, "sub/": TOP, "link-to-sub": TOP}
        for name, path, verdict in root_forms(self.tmp, self.root):
            with self.subTest(form=name):
                code, out = self.run_args("--root", path, "--body-file", self.body)
                if name in top:
                    self.assertEqual((code, out), (0, PASS))
                elif name == "nested":  # a repository with no config
                    self.assertEqual((code, out), (1, CONFIG_MISSING))
                elif name in verdicts:  # git finds the top level; the config load refuses the root a step later
                    self.assertEqual((code, out), (1, "FAIL pr-body.input: %s\n" % verdicts[name]))
                else:
                    self.assertEqual(verdict, E128)
                    self.assertEqual((code, out), (1, "FAIL pr-body.input: %s; run /strict-delivery:init\n" % E128))
        # a plain directory and a path outside any repository fail with the init hint; a repository without config
        plain = os.path.join(self.tmp, "plain-dir")
        os.mkdir(plain)
        self.assertEqual(self.run_args("--root", plain, "--body-file", self.body),
                         (1, "FAIL pr-body.input: %s; run /strict-delivery:init\n" % E128))
        bare_repo = os.path.join(self.tmp, "noconfig")
        os.mkdir(bare_repo)
        subprocess.run(["git", "-C", bare_repo, "init", "-q", "-b", "main"], check=True)
        self.assertEqual(self.run_args("--root", bare_repo, "--body-file", self.body), (1, CONFIG_MISSING))

    def test_root_default(self):  # A2: no --root
        self.put("ok\n")
        self.assertEqual(self.run_args("--body-file", self.body, cwd=self.root), (0, PASS))
        with mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": self.root}):
            self.assertEqual(self.run_args("--body-file", self.body, cwd=self.tmp), (0, PASS))

    def test_json_and_help(self):  # A3
        self.put("ok\n")
        code, out = self.run_args("--json", "--root", self.root, "--body-file", self.body)
        self.assertEqual((code, json.loads(out)), (0, {"gate": "pr-body", "ok": True, "lines": [
            {"status": "PASS", "id": "pr-body.placeholders", "reason": ""}]}))
        self.put("{{a}}\n")
        code, out = self.run_args("--json", "--root", self.root, "--body-file", self.body)
        self.assertEqual((code, json.loads(out)), (1, {"gate": "pr-body", "ok": False, "lines": [
            {"status": "FAIL", "id": "pr-body.placeholder.1", "reason": "{{, }}"}]}))
        self.assertEqual(self.run_args("--help"), (1, "FAIL pr-body.input: help requested; no gate was run\n"))
        self.assertEqual(self.run_args("-h"), (1, "FAIL pr-body.input: help requested; no gate was run\n"))
        code, out, err = self.run_full("--help")  # the usage goes to stderr: the program name and each option's help
        self.assertIn("usage: pr-body [-h] [--root ROOT] [--body-file BODY_FILE]", err)
        self.assertIn("--body-file BODY_FILE\n                        the file holding the pull request body", err)
        self.assertEqual(self.run_args("--root", self.root, "--body-file", self.body, "--json"),
                         (1, "FAIL pr-body.input: invalid arguments: unrecognized arguments: --json\n"))

    def test_slots(self):  # T1, O1
        for body, want in (("Full suite: {{full_suite}}\n", "FAIL pr-body.placeholder.1: {{, }}\n"),
                           ("a {{ b\n", "FAIL pr-body.placeholder.1: {{\n"), ("a }} b\n", "FAIL pr-body.placeholder.1: }}\n"),
                           ("{{{x}}}\n", "FAIL pr-body.placeholder.1: {{, }}\n"),
                           ("`{{x}}`\n", "FAIL pr-body.placeholder.1: {{, }}\n"),
                           ("```\n{{x}}\n```\n", "FAIL pr-body.placeholder.2: {{, }}\n"),
                           ("a }}{{ b\n", "FAIL pr-body.placeholder.1: }}, {{\n")):
            with self.subTest(body=body):
                self.put(body)
                self.assertEqual(self.run_gate(), (1, want))
        for body in ("a { { b\n", "a { b } c\n", "a {\n{ b\n", "a }\n} b\n"):
            with self.subTest(body=body):
                self.put(body)
                self.assertEqual(self.run_gate(), (0, PASS))

    def test_markers_whole_tokens(self):  # T2
        for body, n in (("TBD\n", 1), ("x TODO\n", 1), ("TODO: y\n", 1), ("(TBD)\n", 1), ("XTODO\n", 0), ("TODOs\n", 0),
                        ("todo\n", 0), ("TODO_x\n", 0), ("TODO-x\n", 0), ("x-TBD\n", 0), ("9TBD\n", 0), ("TBDTODO\n", 0),
                        ("a TBD, TODO.\n", 2), ("Tbd\n", 0), ("TBD", 1), ("x TODO", 1), ("TBD x", 1), ("TBD\nx", 1)):
            with self.subTest(body=body):
                self.put(body)
                code, out = self.run_gate()
                if n == 0:
                    self.assertEqual((code, out), (0, PASS))
                elif n == 2:
                    self.assertEqual((code, out), (1, "FAIL pr-body.placeholder.1: TBD, TODO\n"))
                else:
                    self.assertEqual(code, 1)
                    self.assertEqual(out.count("FAIL pr-body.placeholder.1: "), 1)
                    self.assertIn(out, ("FAIL pr-body.placeholder.1: TBD\n", "FAIL pr-body.placeholder.1: TODO\n"))
        self.put("TBD\n")
        self.assertEqual(self.run_gate(), (1, "FAIL pr-body.placeholder.1: TBD\n"))
        self.put("x TODO\n")
        self.assertEqual(self.run_gate(), (1, "FAIL pr-body.placeholder.1: TODO\n"))

    def test_hit_lines_ordered_and_unique(self):  # T3
        self.put("x\nTODO {{a}}\nTBD\n")
        self.assertEqual(self.run_gate(), (1, "FAIL pr-body.placeholder.2: TODO, {{, }}\n"
                                              "FAIL pr-body.placeholder.3: TBD\n"))
        self.put("TBD\nok\n{{a}}\n")
        self.assertEqual(self.run_gate(), (1, "FAIL pr-body.placeholder.1: TBD\nFAIL pr-body.placeholder.3: {{, }}\n"))
        self.put("\nTODO\n")  # a LF in the first byte counts
        self.assertEqual(self.run_gate(), (1, "FAIL pr-body.placeholder.2: TODO\n"))
        self.put("}} TODO {{ TBD\n")
        self.assertEqual(self.run_gate(), (1, "FAIL pr-body.placeholder.1: }}, TODO, {{, TBD\n"))

    def test_path_kinds(self):  # H1
        self.put("ok\n")
        os.symlink(self.body, os.path.join(self.tmp, "link"))
        os.symlink(os.path.join(self.tmp, "nowhere"), os.path.join(self.tmp, "dangling"))
        os.mkfifo(os.path.join(self.tmp, "fifo"))
        for path, reason in ((os.path.join(self.tmp, "missing"), "missing"), (self.tmp, "not a regular file"),
                             (os.path.join(self.tmp, "link"), "a symlink"), (os.path.join(self.tmp, "dangling"), "a symlink"),
                             (os.path.join(self.tmp, "fifo"), "not a regular file"), ("/dev/null", "not a regular file"),
                             (self.body + "/x", "missing")):
            with self.subTest(path=path):
                code, out = within(lambda: self.run_gate(body=path))
                self.assertEqual((code, out), (1, "FAIL pr-body.input: --body-file %s: %s\n" % (path, reason)))
        self.assertEqual(self.run_gate(body=self.body), (0, PASS))

    def test_unreadable(self):  # H1
        if os.geteuid() == 0:
            self.skipTest("the effective uid is 0: mode 000 does not refuse")
        self.put("ok\n")
        os.chmod(self.body, 0)
        self.assertEqual(self.run_gate(), (1, "FAIL pr-body.input: --body-file %s: unreadable\n" % self.body))

    def test_parent_symlink_and_limit(self):  # H2
        real = os.path.join(self.tmp, "real")
        os.mkdir(real)
        with open(os.path.join(real, "b.md"), "wb") as fh:
            fh.write(b"ok\n")
        os.symlink(real, os.path.join(self.tmp, "parent"))
        self.assertEqual(self.run_gate(body=os.path.join(self.tmp, "parent", "b.md")), (0, PASS))
        # stated limit: only the last component is opened with O_NOFOLLOW; the bytes judged are those of the one
        # descriptor (see PM1 for the swap between the open and the read)
        with open(os.path.join(real, "b.md"), "wb") as fh:
            fh.write(b"TODO\n")
        self.assertEqual(self.run_gate(body=os.path.join(self.tmp, "parent", "b.md")),
                         (1, "FAIL pr-body.placeholder.1: TODO\n"))

    def test_path_equal_to_root(self):  # H3
        self.assertEqual(self.run_gate(body=self.root), (1, "FAIL pr-body.input: --body-file %s: not a regular file\n" % self.root))
        inside = os.path.join(self.root, ".git", "pr-body.md")
        with open(inside, "wb") as fh:
            fh.write(b"ok\n")
        self.assertEqual(self.run_gate(body=inside), (0, PASS))
        in_tree = os.path.join(self.root, "body.md")
        with open(in_tree, "wb") as fh:
            fh.write(b"ok\n")
        self.assertEqual(self.run_gate(body=in_tree), (0, PASS))

    def test_outside_root_and_relative(self):  # H4
        outside = os.path.join(self.tmp, "scratch")
        os.mkdir(outside)
        with open(os.path.join(outside, "b.md"), "wb") as fh:
            fh.write(b"ok\n")
        self.assertEqual(self.run_gate(body=os.path.join(outside, "b.md")), (0, PASS))
        self.assertEqual(self.run_args("--root", self.root, "--body-file", "b.md", cwd=outside), (0, PASS))
        self.assertEqual(self.run_args("--root", self.root, "--body-file", "nope.md", cwd=outside),
                         (1, "FAIL pr-body.input: --body-file nope.md: missing\n"))

    def test_non_utf8_name(self):  # H5
        directory = os.path.join(self.tmp, "ffdir")
        os.mkdir(directory)
        path = os.path.join(directory, "b" + FF + ".md")
        shown = os.path.join(directory, "b\\udcff.md")  # safe_text writes the surrogate once: \udcff
        try:
            with open(os.fsencode(path), "wb") as fh:
                fh.write(b"ok\n")
        except OSError as e:
            if e.errno == errno.EILSEQ:  # only that errno skips; every other error fails
                self.skipTest(SKIP_FF)
            raise
        self.assertEqual(self.run_gate(body=path), (0, PASS))
        os.mkfifo(os.fsencode(path) + b"2")
        self.assertEqual(within(lambda: self.run_gate(body=path + "2")),
                         (1, "FAIL pr-body.input: --body-file %s2: not a regular file\n" % shown))
        self.assertEqual(self.run_gate(body=path + "3"), (1, "FAIL pr-body.input: --body-file %s3: missing\n" % shown))

    def test_size_cap(self):  # S1
        self.put(b"a" * MAX_BYTES)
        self.assertEqual(self.run_gate(), (0, PASS))
        self.put(b"a" * (MAX_BYTES + 1))
        self.assertEqual(self.run_gate(), (1, "FAIL pr-body.input: --body-file %s: over 1048576 bytes\n" % self.body))
        self.put(b"TODO\n" + b"a" * (MAX_BYTES - 5))  # exactly the cap, a hit on line 1
        self.assertEqual(self.run_gate(), (1, "FAIL pr-body.placeholder.1: TODO\n"))

    def test_encoding(self):  # E1
        for raw, reason in ((b"\xff\n", "not UTF-8"), (b"\xef\xbb\xbfx\n", "starts with a byte order mark"),
                            (b"a\n\x00\n", "control character U+0000 at line 2"),
                            (b"\x1b\n", "control character U+001B at line 1"),
                            (b"\x7f\n", "control character U+007F at line 1"),
                            (b"a\n\nb\x08\n", "control character U+0008 at line 3"),
                            (b"\x0b\n", "control character U+000B at line 1"), (b"\x0c\n", "control character U+000C at line 1"),
                            (b"\x0e\n", "control character U+000E at line 1"), (b"\x1f\n", "control character U+001F at line 1"),
                            (b"a\xc3\n", "not UTF-8"), (b"\xef\xbb\n", "not UTF-8"),
                            (b"\n\x00\n", "control character U+0000 at line 2"),
                            (b"\n\n\n\x1f", "control character U+001F at line 4")):
            with self.subTest(raw=raw):
                self.put(raw)
                self.assertEqual(self.run_gate(), (1, "FAIL pr-body.%s: %s\n" % (
                    "encoding", reason)))
        for raw in (b"a\tb\n", "café   \u0085\n".encode("utf-8"), b"a\tb ~\n"):
            with self.subTest(raw=raw):
                self.put(raw)
                self.assertEqual(self.run_gate(), (0, PASS))

    def test_line_endings(self):  # E2
        self.put(b"a\r\nb\n")
        self.assertEqual(self.run_gate(), (1, "FAIL pr-body.line-ending: CR at line 1\n"))
        self.put(b"a\nb\rc\n")
        self.assertEqual(self.run_gate(), (1, "FAIL pr-body.line-ending: CR at line 2\n"))
        self.put(b"no final newline")
        self.assertEqual(self.run_gate(), (0, PASS))
        self.put(b"\rx\n")  # a CR in the first byte
        self.assertEqual(self.run_gate(), (1, "FAIL pr-body.line-ending: CR at line 1\n"))
        self.put(b"\n\n\rx\n")
        self.assertEqual(self.run_gate(), (1, "FAIL pr-body.line-ending: CR at line 3\n"))
        self.put(b"\x00 a\r\n")  # the CR is reported before the control character
        self.assertEqual(self.run_gate(), (1, "FAIL pr-body.line-ending: CR at line 1\n"))
        self.put(b"\xff\r\n")  # not UTF-8 first
        self.assertEqual(self.run_gate(), (1, "FAIL pr-body.encoding: not UTF-8\n"))

    def test_empty(self):  # E3
        for raw in (b"", b"\n", b"  \t\n\n", b" ", b"\t"):
            with self.subTest(raw=raw):
                self.put(raw)
                self.assertEqual(self.run_gate(), (1, "FAIL pr-body.empty: no text\n"))
        self.put(b"\n\n.\n")
        self.assertEqual(self.run_gate(), (0, PASS))

    def test_digit_runs(self):  # V1, both interpreters
        self.put("9" * 4300 + "\n" + "9" * 4301 + "\n")
        self.assertEqual(self.run_gate(), (0, PASS))
        self.put("x\n" * 4999 + "TODO\n")
        self.assertEqual(self.run_gate(), (1, "FAIL pr-body.placeholder.5000: TODO\n"))

    def test_version_dependent_code_points_pass(self):  # V2
        self.put("Ⱟ ࡰ \U0001fae8\n")
        self.assertEqual(self.run_gate(), (0, PASS))

    def test_sources_name_no_unicode_tables(self):  # V3
        for rel in ("gates/lib/prbody.py", "gates/gate_pr_body.py"):
            with open(os.path.join(REPO, rel), encoding="utf-8") as fh:
                src = fh.read()
            for word in ("unicodedata", "isprintable", "BaseExceptionGroup", "splitlines", ".lower(", "isalnum", ".upper("):
                with self.subTest(file=rel, word=word):
                    self.assertNotIn(word, src)

    def test_registered_in_no_run_all_list(self):  # R1
        if "pr-body" not in gates_main.GATES:
            self.skipTest("Rq-L2-1 not on this branch")
        self.assertEqual(gates_main.GATES["pr-body"], "gates.gate_pr_body")
        self.assertNotIn("pr-body", BASE_GATES)
        for profile, gates in PROFILE_GATES.items():
            with self.subTest(profile=profile):
                self.assertNotIn("pr-body", gates)

    def test_main_module_runs_as_script(self):  # O1: the module's own entry point
        self.put("ok\n")
        self.assertEqual(self.run_gate(), (0, PASS))


class ExactTypesTest(GitIsolatedTestCase):
    """X1-X4: exact types, refused with a named error before any work."""

    def test_exact_types(self):
        class S(str):
            pass

        class B(bytes):
            pass

        with mock.patch("os.open", side_effect=AssertionError("os.open must not run")):
            for bad, name in ((S("x"), "S"), (b"x", "bytes"), (PurePosixPath("x"), "PurePosixPath"), (None, "NoneType")):
                with self.subTest(fn="read_raw", value=name):
                    with self.assertRaises(TypeError) as cm:
                        prbody.read_raw(bad)
                    self.assertEqual(str(cm.exception), "path must be an exact str, got %s" % name)
        for bad, name in ((B(b"x"), "B"), (bytearray(b"x"), "bytearray"), (memoryview(b"x"), "memoryview"),
                          ("x", "str"), (None, "NoneType")):
            with self.subTest(fn="text_problems", value=name):
                with self.assertRaises(TypeError) as cm:
                    prbody.text_problems(bad)
                self.assertEqual(str(cm.exception), "raw must be an exact bytes, got %s" % name)
        for bad, name in ((S("x"), "S"), (b"x", "bytes"), (None, "NoneType")):
            with self.subTest(fn="placeholder_hits", value=name):
                with self.assertRaises(TypeError) as cm:
                    prbody.placeholder_hits(bad)
                self.assertEqual(str(cm.exception), "text must be an exact str, got %s" % name)
        self.assertEqual(prbody.text_problems(b"x\n"), [])
        self.assertEqual(prbody.placeholder_hits("x\n"), [])

        class L(list):
            pass

        for bad, name in (((), "tuple"), (L(), "L"), (["--root", S("x")], "S"), ([b"--root"], "bytes"), (None, "NoneType")):
            with self.subTest(fn="check", value=name):
                with mock.patch("os.open", side_effect=AssertionError("os.open must not run")):
                    with self.assertRaises(result.ParseEntryRefused) as cm:
                        gate_pr_body.check(bad)
                self.assertIn("a list of str is required", str(cm.exception))
        for bad, name in (((), "tuple"), (L(), "L"), (["--root", S("x")], "list"), ([b"--root"], "list")):
            with self.subTest(fn="main", value=name):
                with self.assertRaises(TypeError) as cm:
                    gate_pr_body.main(bad)
                self.assertEqual(str(cm.exception), "argv must be None or an exact list of exact str, got %s" % name)
        with mock.patch.object(sys, "argv", ["x", "--help"]), contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(gate_pr_body.main(None), 1)
        self.assertEqual(out.getvalue(), "FAIL pr-body.input: help requested; no gate was run\n")
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(gate_pr_body.main(["--help"]), 1)
        self.assertEqual(out.getvalue(), "FAIL pr-body.input: help requested; no gate was run\n")

    def test_short_reads_are_joined_and_sized(self):  # S1 at the library: the file arrives in pieces
        body = os.path.join(self.tmp, "b.md")
        real_read = os.read
        asked = []

        def short(fd, n):
            asked.append(n)
            return real_read(fd, min(n, 65536))

        for size in (MAX_BYTES, MAX_BYTES + 1, MAX_BYTES + 70000):
            with open(body, "wb") as fh:
                fh.write(b"a" * size)
            del asked[:]
            with mock.patch("os.read", short):
                if size == MAX_BYTES:
                    self.assertEqual(prbody.read_raw(body), b"a" * size)
                else:
                    with self.assertRaises(GateError) as cm:
                        prbody.read_raw(body)
                    self.assertEqual(str(cm.exception), "over 1048576 bytes")
            self.assertEqual((asked[0], max(asked)), (MAX_BYTES + 1, MAX_BYTES + 1), size)

    def test_read_error_after_the_open_is_unreadable_and_closes(self):  # H1: an OSError from os.read
        body = os.path.join(self.tmp, "b.md")
        with open(body, "wb") as fh:
            fh.write(b"ok\n")
        real_close, closed = os.close, []

        def close(fd):
            closed.append(fd)
            real_close(fd)

        with mock.patch("os.read", side_effect=OSError(errno.EIO, "boom")), mock.patch("os.close", close):
            with self.assertRaises(GateError) as cm:
                prbody.read_raw(body)
        self.assertEqual(str(cm.exception), "unreadable")
        self.assertEqual(len(closed), 1)

    def test_read_raw_reasons_through_the_library(self):  # H1 at the library: one reason each
        for path, reason in (("", "missing"), ("/dev/null", "not a regular file"), ("a\x00b", "unreadable")):
            with self.subTest(path=path):
                with self.assertRaises(GateError) as cm:
                    prbody.read_raw(path)
                self.assertEqual(str(cm.exception), reason)


# ---- G1, G2: seeded generated inputs, a hand-written reference, the gate through main() in this process ----

TOKCHARS = set("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz_-")


def ref_lines(text):
    """The reference: the gate's expected output for a text with at least one visible character, written from the
    sentence 'non-overlapping {{ and }} left to right; whole tokens bounded by non-[0-9A-Za-z_-] or the ends'."""
    hits, line, i, n = [], 1, 0, len(text)
    while i < n:
        c = text[i]
        if c == "\n":
            line += 1
            i += 1
            continue
        if text[i:i + 2] in ("{{", "}}"):
            hits.append((line, text[i:i + 2]))
            i += 2
            continue
        for w in ("TBD", "TODO"):
            if text[i:i + len(w)] == w:
                left = text[i - 1] if i else " "
                right = text[i + len(w)] if i + len(w) < n else " "
                if left not in TOKCHARS and right not in TOKCHARS:
                    hits.append((line, w))
        i += 1
    if not hits:
        return "PASS pr-body.placeholders\n"
    out, order = {}, []
    for line, tok in hits:
        if line not in out:
            out[line] = []
            order.append(line)
        out[line].append(tok)
    return "".join("FAIL pr-body.placeholder.%d: %s\n" % (n_, ", ".join(out[n_])) for n_ in order)


def ref_problem(raw):
    """The reference of the encoding order: not UTF-8, byte order mark, CR, control character, no text."""
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError:
        return "FAIL pr-body.encoding: not UTF-8\n"
    if raw[:3] == bytes([0xEF, 0xBB, 0xBF]):
        return "FAIL pr-body.encoding: starts with a byte order mark\n"
    for i, v in enumerate(raw):
        if v == 13:
            return "FAIL pr-body.line-ending: CR at line %d\n" % (1 + sum(1 for u in raw[:i] if u == 10))
    for i, v in enumerate(raw):
        if v < 32 and v not in (9, 10) or v == 127:
            return "FAIL pr-body.encoding: control character U+%04X at line %d\n" % (v, 1 + sum(1 for u in raw[:i] if u == 10))
    if all(v in (32, 9, 10) for v in raw):
        return "FAIL pr-body.empty: no text\n"
    return None


class GeneratedTest(GitIsolatedTestCase):
    SEED = 20261126
    COUNT = 2400

    def setUp(self):
        super().setUp()
        self.body = os.path.join(self.tmp, "body.md")
        patches = (mock.patch.object(gate_pr_body.gitinfo, "toplevel", return_value="/x"),
                   mock.patch.object(gate_pr_body.config, "load", return_value={}))
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def gate(self, raw):
        with open(self.body, "wb") as fh:
            fh.write(raw)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = gate_pr_body.main(["--root", "/x", "--body-file", self.body])
        return code, buf.getvalue()

    def test_generated_bodies_match_reference(self):  # G1: seed 20261126, 2400 bodies
        rng = random.Random(self.SEED)
        pieces = ["{", "}", "T", "B", "D", "O", "x", "_", "-", " ", "\n", "TBD", "TODO", "{{", "}}"]
        seen = set()
        for _ in range(self.COUNT):
            text = "".join(rng.choice(pieces) for _ in range(rng.randint(0, 24)))
            if all(c in " \n" for c in text):
                text += "x"
            want = ref_lines(text)
            code, out = self.gate(text.encode("utf-8"))
            if (code, out) != (0 if want.startswith("PASS") else 1, want):
                self.fail("body %r: got %r, want %r" % (text, (code, out), want))
            seen.add(want.split(":")[0].split(" ")[0])
        self.assertEqual(seen, {"PASS", "FAIL"})  # both verdicts occurred

    def test_generated_bytes_match_reference(self):  # G2: seed 20261126, 2400 byte strings of length 0-64
        rng = random.Random(self.SEED + 1)
        small = [0, 1, 8, 9, 10, 11, 12, 13, 14, 31, 32, 65, 84, 126, 127, 0xC3, 0xA9, 0xEF, 0xBB, 0xBF, 0xFF, 0x80]
        kinds = set()
        for n in range(self.COUNT):
            length = rng.randint(0, 64)
            if n % 2:
                raw = bytes(rng.randrange(256) for _ in range(length))
            else:
                raw = bytes(rng.choice(small) for _ in range(length))
            want = ref_problem(raw)
            code, out = self.gate(raw)
            if want is None:
                if code == 1 and not out.startswith("FAIL pr-body.placeholder."):
                    self.fail("bytes %r: got %r, want no encoding problem" % (raw, out))
                kinds.add("none")
            else:
                if (code, out) != (1, want):
                    self.fail("bytes %r: got %r, want %r" % (raw, (code, out), want))
                kinds.add(want.split(":")[0])
        self.assertEqual(kinds, {"none", "FAIL pr-body.encoding", "FAIL pr-body.line-ending", "FAIL pr-body.empty"})


# ---- PM1: the generated path matrix of read_raw ----

PM1_SOURCE_VERDICT = {  # typed by hand: the source (the body file itself)
    "absent": "missing", "file": "read", "dir": "not a regular file", "symlink_file_in": "a symlink",
    "symlink_file_out": "a symlink", "fifo": "not a regular file", "ff": "read"}
PM1_HOLDER_VERDICT = {  # typed by hand: the holder and each parent above it; only the last component is not followed
    "absent": "missing", "file": "missing", "dir": "read", "symlink_dir_in": "read", "symlink_dir_out": "read",
    "symlink_file_in": "missing", "symlink_file_out": "missing", "fifo": "missing", "ff": "read"}
PM1_ROLES = ("p1", "p2", "holder", "source")
PM1_SWAPS = ("file", "symlink", "dir")


def pm1_cells():
    """Every cell of the matrix: (role, state, moment, swap, verdict); moment ``open`` has swap ``None``."""
    cells = []
    for role in PM1_ROLES:
        table = PM1_SOURCE_VERDICT if role == "source" else PM1_HOLDER_VERDICT
        for state, verdict in table.items():
            cells.append((role, state, "open", None, verdict))
            for swap in PM1_SWAPS:
                cells.append((role, state, "between", swap, verdict))
    return cells


def make_rest(base, names):
    """The real entries below ``base``: directories, the last name a regular file holding CLEAN."""
    cur = base
    for i, name in enumerate(names):
        cur = os.path.join(cur, name)
        if i == len(names) - 1:
            with open(cur, "wb") as fh:
                fh.write(CLEAN)
        else:
            os.mkdir(cur)


def build_pm1(cell, outside, role, state):
    """Build the chain ``cell/use/p1/p2/holder/body.md`` with ``state`` at the entry of ``role``. Returns
    ``(path, entry, rest, created)``: the path to read, the entry of the role, the names below it, and whether the
    state could be built (macOS refuses a name holding byte 0xff)."""
    names = ["p1", "p2", "holder", "body.md"]
    k = PM1_ROLES.index(role)
    cur = os.path.join(cell, "use")
    os.mkdir(cur)
    for name in names[:k]:
        cur = os.path.join(cur, name)
        os.mkdir(cur)
    entry_name = names[k] + (FF if state == "ff" else "")
    entry = os.path.join(cur, entry_name)
    rest = names[k + 1:]
    path = os.path.join(entry, *rest) if rest else entry
    is_source = role == "source"
    target_dir = {"in": os.path.join(cell, "good"), "out": os.path.join(outside, os.path.basename(cell) + "-good")}
    if state == "absent":
        return path, entry, rest, True
    try:
        if state == "ff" and is_source:
            with open(os.fsencode(entry), "wb") as fh:
                fh.write(CLEAN)
        elif state in ("dir", "ff"):
            os.mkdir(entry)
            if not is_source:
                make_rest(entry, rest)
        elif state == "file":
            with open(entry, "wb") as fh:
                fh.write(CLEAN)
    except OSError as e:
        if state == "ff" and e.errno == errno.EILSEQ:  # APFS refuses a name holding byte 0xff; every other error fails
            return path, entry, rest, False
        raise
    if state == "fifo":
        os.mkfifo(entry)
    elif state.startswith("symlink_file"):
        where = target_dir[state.rsplit("_", 1)[1]]
        os.mkdir(where)
        with open(os.path.join(where, "t.md"), "wb") as fh:
            fh.write(CLEAN)
        os.symlink(os.path.join(where, "t.md"), entry)
    elif state.startswith("symlink_dir"):
        where = target_dir[state.rsplit("_", 1)[1]]
        os.mkdir(where)
        make_rest(where, rest)
        os.symlink(where, entry)
    return path, entry, rest, True


def swap_entry(entry, rest, kind, poison_root):
    """Replace ``entry`` by another file, a symlink or a directory (the original is renamed aside, never removed)."""
    os.rename(entry, entry + ".moved")
    if kind == "file":
        with open(entry, "wb") as fh:
            fh.write(POISON)
        return
    where = os.path.join(poison_root, "poison%d" % len(os.listdir(poison_root)))
    os.mkdir(where)
    if rest:
        cur = where
        for i, name in enumerate(rest):
            cur = os.path.join(cur, name)
            if i == len(rest) - 1:
                with open(cur, "wb") as fh:
                    fh.write(POISON)
            else:
                os.mkdir(cur)
    if kind == "symlink":
        os.symlink(where, entry)
    else:
        os.rename(where, entry)


class PathMatrixTest(GitIsolatedTestCase):
    def test_generated_path_matrix_read_raw(self):  # PM1
        outside = os.path.join(self.tmp, "second")
        os.mkdir(outside)
        cells = pm1_cells()
        random.Random(20261126).shuffle(cells)
        self.assertEqual(len(cells), (7 + 3 * 9) * 4)  # the source and three directory roles, 1 + 3 moments
        real_open = os.open
        for n, (role, state, moment, swap, verdict) in enumerate(cells):
            cell = os.path.join(self.tmp, "cell%d" % n)
            os.mkdir(cell)
            with self.subTest(role=role, state=state, moment=moment, swap=swap):
                path, entry, rest, created = build_pm1(cell, outside, role, state)
                want = verdict
                if not created:
                    self.skipTest(SKIP_FF)
                swaps = []

                def hooked(p, flags, *a, **k):
                    fd = real_open(p, flags, *a, **k)
                    if p == path and not swaps:
                        swaps.append(1)
                        swap_entry(entry, rest, swap, outside)
                    return fd

                with mock.patch("os.open", hooked if moment == "between" else real_open):
                    try:
                        got = within(lambda: prbody.read_raw(path))
                        outcome = "read" if got == CLEAN else "WRONG BYTES %r" % got
                    except GateError as e:
                        outcome = str(e)
                self.assertEqual(outcome, want)
                if moment == "between" and want == "read":
                    self.assertEqual(swaps, [1])  # the swap happened after the successful open


class ReadRawSwapTest(GitIsolatedTestCase):
    def test_swapped_file_is_never_judged(self):  # H2, PM1 between the open and the read, through the gate's own function
        body = os.path.join(self.tmp, "b.md")
        with open(body, "wb") as fh:
            fh.write(CLEAN)
        real_open = os.open

        def hooked(p, flags, *a, **k):
            fd = real_open(p, flags, *a, **k)
            if p == body:
                with open(body + ".new", "wb") as fh:
                    fh.write(POISON)
                os.rename(body + ".new", body)
            return fd

        with mock.patch("os.open", hooked):
            self.assertEqual(prbody.read_raw(body), CLEAN)
        self.assertEqual(prbody.read_raw(body), POISON)


if __name__ == "__main__":
    unittest.main()
