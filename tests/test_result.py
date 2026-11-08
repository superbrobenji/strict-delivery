"""Tests for the gate result contract (gates.lib.result), the dispatcher and the producers registry."""
import collections
import contextlib
import io
import json
import os
import random
import subprocess
import sys
import types
import unittest
from unittest import mock

from gates import __main__ as gates_main
from gates import producers
from gates.lib import config, decisions, findings
from gates.lib.result import (GateError, GitNotFound, Line, Result, _raw, gate_args, repo_root, run_check,
                              run_gate, safe_text)
from gates.lib.store import Record, Store, store_errors
from tests.helpers import GitIsolatedTestCase, make_repo

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run(name, check, argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = run_gate(name, check, argv)
    return code, out.getvalue(), err.getvalue()


def one_pass(args):
    gate_args("x").parse_args(args)
    r = Result("x", [])
    r.passed("x.ok")
    return r


def result_with(reason, id="x.bad"):
    def check(args):
        r = Result("x", [])
        r.fail(id, reason)
        return r
    return check


class ResultApiTest(unittest.TestCase):
    def test_ok_needs_a_line_and_all_pass(self):  # X3
        r = Result("g", [])
        self.assertFalse(r.ok())
        r.passed("g.a")
        self.assertTrue(r.ok())
        r.fail("g.b", "no")
        self.assertFalse(r.ok())
        self.assertEqual(r.lines, [Line("PASS", "g.a", ""), Line("FAIL", "g.b", "no")])

    def test_render_text(self):
        r = Result("g", [])
        r.passed("g.a")
        r.fail("g.b", "why")
        self.assertEqual(r.render(False), "PASS g.a\nFAIL g.b: why\n")
        self.assertEqual(Result("g", []).render(False), "")

    def test_render_json_round_trips(self):  # X6
        r = Result("g", [])
        r.passed("g.a")
        r.fail("g.q", 'say "hi" é中\n\x00')
        data = json.loads(r.render(True))
        self.assertEqual(data, {"gate": "g", "ok": False, "lines": [
            {"status": "PASS", "id": "g.a", "reason": ""},
            {"status": "FAIL", "id": "g.q", "reason": 'say "hi" é中\n\x00'}]})
        self.assertEqual(len(r.render(True).splitlines()), 1)

    def test_render_json_shape_exact(self):  # X6, owner Q-1a2r-4
        r = Result("g", [])
        r.passed("g.a")
        r.fail("g.b", "why\\n")
        self.assertEqual(r.render(True),
                         '{"gate": "g", "ok": false, "lines": [{"status": "PASS", "id": "g.a", "reason": ""}, '
                         '{"status": "FAIL", "id": "g.b", "reason": "why\\\\n"}]}\n')
        self.assertEqual(list(json.loads(r.render(True))), ["gate", "ok", "lines"])
        self.assertEqual(list(json.loads(r.render(True))["lines"][0]), ["status", "id", "reason"])

    def test_render_json_reason_is_a_string(self):
        r = Result("g", [])
        r.fail("g.a", 1)
        r.fail("g.b", None)
        self.assertEqual([ln["reason"] for ln in json.loads(r.render(True))["lines"]], ["1", "None"])

    def test_render_json_ok_true(self):
        r = Result("g", [])
        r.passed("g.a")
        self.assertIs(json.loads(r.render(True))["ok"], True)


class SafeTextTest(unittest.TestCase):
    def test_escapes_every_non_printable(self):  # X4
        cases = [
            ("a\nb\r", "a\\nb\\r"),
            ("t\tt", "t\\tt"),
            ("\x00", "\\x00"),
            ("\x01\x1f", "\\x01\\x1f"),
            ("\x7f", "\\x7f"),
            ("\x85", "\\x85"),
            ("  ", "\\u2028\\u2029"),
            ("\ud800", "\\ud800"),
            ("\U000e0001", "\\U000e0001"),
            ("plain é中", "plain é中"),
            ("\\", "\\\\"),
            ("\\n", "\\\\n"),
        ]
        for raw, want in cases:
            with self.subTest(raw=raw):
                self.assertEqual(safe_text(raw), want)
                self.assertEqual(len(safe_text(raw).splitlines()), 1)

    def test_backslash_n_and_newline_differ(self):  # X4, owner Q-1a2r-4
        self.assertNotEqual(safe_text("a\\nb"), safe_text("a\nb"))
        self.assertEqual(safe_text("a\\nb"), "a\\\\nb")
        self.assertEqual(safe_text("a\nb"), "a\\nb")
        r = Result("g", [])
        r.fail("g\\x", "p\\q")
        self.assertEqual(r.render(False), "FAIL g\\\\x: p\\\\q\n")

    def test_non_str_goes_through_str(self):  # X5
        class Obj:
            def __str__(self):
                return "o\nb"
        self.assertEqual(safe_text(1), "1")
        self.assertEqual(safe_text(None), "None")
        self.assertEqual(safe_text(Obj()), "o\\nb")


class RunGateTest(unittest.TestCase):
    def test_argv_empty_runs_default(self):  # X1
        self.assertEqual(run("x", one_pass, []), (0, "PASS x.ok\n", ""))

    def test_json_first_gives_json(self):
        code, out, _ = run("x", one_pass, ["--json"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out), {"gate": "x", "ok": True, "lines": [
            {"status": "PASS", "id": "x.ok", "reason": ""}]})

    def test_json_only_as_first_arg(self):
        code, out, err = run("x", one_pass, ["--root", "r", "--json"])
        self.assertEqual(code, 1)
        self.assertTrue(out.startswith("FAIL x.input:"), out)
        self.assertEqual(len(out.splitlines()), 1)
        self.assertIn("--json", err)
        code, out, _ = run("x", one_pass, ["--json", "--json"])  # the first is JSON, the second is unknown
        self.assertEqual(code, 1)
        line = json.loads(out)["lines"][0]
        self.assertEqual((line["status"], line["id"]), ("FAIL", "x.input"))

    def test_json_first_still_passes_rest(self):
        seen = []

        def check(args):
            seen.append(args)
            return one_pass(args)
        run("x", check, ["--json", "--root", "r"])
        run("x", check, ["--root", "r"])
        self.assertEqual(seen, [["--root", "r"], ["--root", "r"]])

    def test_root_option_parsed(self):
        got = []

        def check(args):
            got.append(gate_args("x").parse_args(args).root)
            return one_pass([])
        run("x", check, ["--root", "somewhere"])
        run("x", check, [])
        self.assertEqual(got, ["somewhere", None])

    def test_repeated_root_is_input_fail(self):
        want = "FAIL x.input: invalid arguments: --root given more than once\n"
        for argv in (["--root", "a", "--root", "b"], ["--root=a", "--root", "b"], ["--ro", "a", "--roo=b"],
                     ["--root", "a", "--root", "a"], ["--root", "", "--root", "b"], ["--root=", "--root", "b"]):
            code, out, _ = run("x", one_pass, argv)
            self.assertEqual((code, out), (1, want), argv)
        self.assertEqual(run("x", one_pass, ["--root", "a"])[0], 0)

    def test_help_is_input_fail_and_goes_to_stderr(self):
        code, out, err = run("x", one_pass, ["--help"])
        self.assertEqual((code, out), (1, "FAIL x.input: help requested; no gate was run\n"))
        self.assertIn("usage: x", err)
        self.assertIn("--root", err)

    def test_unknown_flag_and_missing_value(self):
        for argv in (["--bogus"], ["--root"], ["stray"]):
            with self.subTest(argv=argv):
                code, out, err = run("x", one_pass, argv)
                self.assertEqual(code, 1)
                self.assertTrue(out.startswith("FAIL x.input: "), out)
                self.assertEqual(len(out.splitlines()), 1)
                self.assertIn("usage: x", err)

    def test_argv_none_reads_sys_argv(self):
        with mock.patch.object(sys, "argv", ["prog", "--json"]):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = run_gate("x", one_pass)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out.getvalue())["gate"], "x")

    def test_empty_result_fails_empty(self):  # X2, X3
        code, out, _ = run("x", lambda a: Result("x", []), [])
        self.assertEqual((code, out), (1, "FAIL x.empty: the gate produced no lines\n"))
        code, out, _ = run("x", lambda a: Result("x", []), ["--json"])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(out)["lines"], [
            {"status": "FAIL", "id": "x.empty", "reason": "the gate produced no lines"}])

    def test_exception_becomes_input_fail(self):
        def boom(args):
            raise ValueError("boom")
        code, out, _ = run("x", boom, [])
        self.assertEqual((code, out), (1, "FAIL x.input: ValueError: boom\n"))

    def test_gate_error_message_kept(self):
        def boom(args):
            raise GateError("no config here")
        self.assertEqual(run("x", boom, [])[:2], (1, "FAIL x.input: no config here\n"))

    def test_exception_with_newlines_is_one_line(self):
        def boom(args):
            raise RuntimeError("a\nb")
        out = run("x", boom, [])[1]
        self.assertEqual(out, "FAIL x.input: RuntimeError: a\\nb\n")

    def test_system_exit_becomes_input_fail(self):
        for code_in in (0, "x", 3, None):
            with self.subTest(code=code_in):
                def check(args, c=code_in):
                    raise SystemExit(c)
                code, out, _ = run("x", check, [])
                self.assertEqual(code, 1)
                self.assertTrue(out.startswith("FAIL x.input: "), out)
                self.assertEqual(len(out.splitlines()), 1)
        out = run("x", lambda a: (_ for _ in ()).throw(SystemExit("x")), [])[1]
        self.assertIn("'x'", out)
        out = run("x", lambda a: (_ for _ in ()).throw(SystemExit("a\nb")), [])[1]  # F-1a-fin-3: escaped once
        self.assertEqual(out, "FAIL x.input: exit requested ('a\\nb')\n")

    def test_exception_text_is_escaped_once(self):  # F-1a-rr-1
        def raiser(exc):
            def check(args):
                raise exc
            return check
        cases = [(KeyError("a\nb"), "KeyError: a\\nb"),
                 (FileNotFoundError(2, "No such file", "a\nb"), "FileNotFoundError: [Errno 2] No such file: a\\nb"),
                 (SystemExit(["a\nb"]), "exit requested ([a\\nb])"),
                 (SystemExit(("a\nb", "c")), "exit requested ([a\\nb, c])"),
                 (ValueError("a\nb"), "ValueError: a\\nb"),
                 (SystemExit("a\nb"), "exit requested ('a\\nb')")]
        for exc, want in cases:
            with self.subTest(exc=repr(exc)):
                out = run("x", raiser(exc), [])[1]
                self.assertEqual(out, "FAIL x.input: %s\n" % want)

    def test_keyboard_interrupt_propagates(self):
        def raising(args):
            raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            run_gate("x", raising, [])
        with self.assertRaises(KeyboardInterrupt):
            run_check("x", raising, [])

    def test_non_result_return_fails_closed(self):
        for value in (None, "PASS x", 0, [Line("PASS", "x.a")]):
            with self.subTest(value=value):
                code, out, _ = run("x", lambda a, v=value: v, [])
                self.assertEqual(code, 1)
                self.assertTrue(out.startswith("FAIL x.input: "), out)

    def test_exit_codes(self):  # X3
        def mixed(args):
            r = Result("x", [])
            r.passed("x.a")
            r.fail("x.b", "bad")
            return r
        code, out, _ = run("x", mixed, [])
        self.assertEqual((code, out), (1, "PASS x.a\nFAIL x.b: bad\n"))
        self.assertEqual(run("x", one_pass, [])[0], 0)

    def test_newline_in_reason_is_one_line(self):  # X4
        code, out, _ = run("x", result_with("a\nb\r"), [])
        self.assertEqual(out, "FAIL x.bad: a\\nb\\r\n")
        self.assertEqual(len(out.splitlines()), 1)
        out = run("x", result_with("p q\x00r\x7fs"), [])[1]
        self.assertEqual(out, "FAIL x.bad: p\\u2028q\\x00r\\x7fs\n")
        out = run("x", result_with("ok", id="x.\nid"), [])[1]
        self.assertEqual(out, "FAIL x.\\nid: ok\n")

    def test_non_str_reason(self):  # X5
        class Obj:
            def __str__(self):
                return "obj\nx"
        for reason, want in ((1, "1"), (None, "None"), (Obj(), "obj\\nx")):
            with self.subTest(reason=reason):
                out = run("x", result_with(reason), [])[1]
                self.assertEqual(out, "FAIL x.bad: %s\n" % want)

    def test_pass_line_id_is_escaped_too(self):
        def check(args):
            r = Result("x", [])
            r.passed("x.a\nb")
            return r
        self.assertEqual(run("x", check, [])[1], "PASS x.a\\nb\n")


class MainTest(unittest.TestCase):
    def test_no_command_and_unknown_command(self):  # X7
        for argv in ([], ["nope"], ["nope", "--json"]):
            with self.subTest(argv=argv):
                err = io.StringIO()
                with contextlib.redirect_stderr(err):
                    code = gates_main.main(argv)
                self.assertEqual(code, 2)
                self.assertIn("usage: python3 -m gates <command>", err.getvalue())

    def test_registered_command_gets_rest_and_returns_its_code(self):
        seen = []

        def cmd(args):
            seen.append(args)
            return 7
        with mock.patch.dict(gates_main.COMMANDS, {"t": cmd}):
            self.assertEqual(gates_main.main(["t", "a", "--b"]), 7)
            self.assertEqual(gates_main.main(["t"]), 7)
        self.assertEqual(seen, [["a", "--b"], []])

    def test_usage_lists_registered_commands(self):
        err = io.StringIO()
        with mock.patch.dict(gates_main.COMMANDS, {"zzcmd": lambda a: 0}):
            with contextlib.redirect_stderr(err):
                gates_main.main([])
        self.assertIn("zzcmd", err.getvalue())

    def test_module_entry_point(self):
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        p = subprocess.run([sys.executable, "-m", "gates", "nope"], cwd=REPO, env=env,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual(p.returncode, 2)
        self.assertEqual(p.stdout, b"")
        self.assertIn(b"usage: python3 -m gates", p.stderr)

    def test_producers_registry_empty_tuple(self):
        self.assertEqual(producers.PRODUCER_MODULES, ())


class RepoRootTest(GitIsolatedTestCase):
    def setUp(self):
        super().setUp()
        self.repo = make_repo(self.work)
        os.mkdir(os.path.join(self.repo, "sub"))
        self.plain = os.path.join(self.tmp, "plain")
        os.mkdir(self.plain)
        cwd = os.getcwd()
        self.addCleanup(os.chdir, cwd)

    def test_env_unset_uses_git_toplevel(self):  # R1, R2
        os.chdir(self.repo)
        self.assertEqual(repo_root(), self.repo)
        os.chdir(os.path.join(self.repo, "sub"))
        self.assertEqual(repo_root(), self.repo)

    def test_env_empty_uses_git_toplevel(self):
        os.chdir(self.repo)
        with mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": ""}):
            self.assertEqual(repo_root(), self.repo)

    def test_env_directory_returned_as_is(self):
        os.chdir(self.plain)
        odd = os.path.join(self.plain, ".", "")
        with mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": odd}):
            self.assertEqual(repo_root(), odd)

    def test_env_non_directory_or_missing_is_error(self):
        os.chdir(self.repo)
        afile = os.path.join(self.plain, "f")
        open(afile, "w").close()
        for value in (afile, os.path.join(self.plain, "missing")):
            with self.subTest(value=value), mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": value}):
                with self.assertRaises(GateError) as e:
                    repo_root()
                self.assertIn("CLAUDE_PROJECT_DIR", str(e.exception))

    def test_outside_a_repo_is_gate_error_without_directory(self):
        os.chdir(self.plain)
        with self.assertRaises(GateError) as e:
            repo_root()
        self.assertIn("git rev-parse --show-toplevel", str(e.exception))
        self.assertNotIn(self.plain, str(e.exception))
        self.assertIn("run /strict-delivery:init", str(e.exception))

    def test_git_missing_has_no_init_hint(self):  # R2, owner Q-1a2r-6
        os.chdir(self.plain)
        with mock.patch.dict(os.environ, {"PATH": os.path.join(self.plain, "nowhere")}):
            with self.assertRaises(GateError) as e:
                repo_root()
        self.assertEqual(str(e.exception), "git not found on PATH; install git")

        def check(args):
            repo_root()
            return one_pass([])
        with mock.patch.dict(os.environ, {"PATH": os.path.join(self.plain, "nowhere")}):
            code, out, err = run("x", check, [])
        self.assertEqual(code, 1)
        self.assertEqual(out, "FAIL x.input: git not found on PATH; install git\n")
        self.assertNotIn("init", out)

    def test_outside_a_repo_through_run_gate(self):
        os.chdir(self.plain)

        def check(args):
            repo_root()
            return one_pass([])
        code, out, err = run("x", check, [])
        self.assertEqual(code, 1)
        self.assertTrue(out.startswith("FAIL x.input: "), out)
        self.assertIn("/strict-delivery:init", out)
        self.assertEqual(len(out.splitlines()), 1)
        self.assertNotIn("Traceback", err)



def raise_gate(*args):
    def check(a):
        raise GateError(*args)
    return check


def rendered(check):
    return run_check("g", check, []).render(False)


class StrRaises:
    """An argument whose ``str`` raises and whose ``repr`` works (V1r-1)."""

    def __str__(self):
        raise RuntimeError("no str")

    def __repr__(self):
        return "SR"


class ReprRaises:
    """An argument whose ``repr`` raises and whose ``str`` works."""

    def __str__(self):
        return "RS"

    def __repr__(self):
        raise RuntimeError("no repr")


class BothRaise:
    """An argument that cannot render at all (U-V1-1)."""

    def __str__(self):
        raise RuntimeError("no str")

    __repr__ = __str__


class BrokenArgs(Exception):
    """An exception whose ``args`` cannot be read."""

    @property
    def args(self):
        raise RuntimeError("no args")


def escaping_or_rendered(exc):
    """``rendered`` for a check raising ``exc``; an exception escaping run_check becomes ``ESCAPED <type>``, so the
    assertion that reports it carries no unrenderable context."""
    def check(a):
        raise exc
    try:
        return rendered(check)
    except Exception as x:
        out = "ESCAPED %s" % type(x).__name__
    return out


class RawMapTest(unittest.TestCase):
    """Q-U2: a map item in a reason is escaped exactly once, by Result.render (task 1c0.1, R1-R16)."""

    def test_map_item_escaped_once(self):  # R10
        self.assertEqual(rendered(raise_gate({"k": "a\\b\nc"})), "FAIL g.input: {k: a\\\\b\\nc}\n")

    def test_map_item_json_escaped_once(self):  # R16
        out = run_check("g", raise_gate({"k": "a\\b\nc"}), []).render(True)
        self.assertEqual(json.loads(out)["lines"][0]["reason"], "{k: a\\b\nc}")
        self.assertEqual(out, '{"gate": "g", "ok": false, "lines": [{"status": "FAIL", "id": "g.input", '
                              '"reason": "{k: a\\\\b\\nc}"}]}\n')

    def test_nested_map_and_list_escaped_once(self):  # R2
        self.assertEqual(_raw({"a": ["x\\y", {"b": "\n"}]}), "{a: [x\\y, {b: \n}]}")
        self.assertEqual(_raw([{"a": "b"}]), "[{a: b}]")
        self.assertEqual(_raw({"a": {"b": "c"}}), "{a: {b: c}}")
        self.assertEqual(rendered(raise_gate({"a": ["x\\y", {"b": "\n"}]})),
                         "FAIL g.input: {a: [x\\\\y, {b: \\n}]}\n")

    def test_flat_dict_insertion_order(self):  # R1
        self.assertEqual(_raw({"k": "v"}), "{k: v}")
        self.assertEqual(_raw({"b": "2", "a": "1"}), "{b: 2, a: 1}")

    def test_character_classes_in_key_and_value(self):  # R3
        table = (("\\", "\\\\"), ("\n", "\\n"), ("\t", "\\t"), ('"', '"'), ("'", "'"), ("\x00", "\\x00"),
                 ("\x7f", "\\x7f"), ("\u00e9", "\u00e9"), ("\u2028", "\\u2028"))
        for ch, shown in table:
            with self.subTest(ch=ch):
                self.assertEqual(_raw({"k" + ch: "v" + ch}), "{k%s: v%s}" % (ch, ch))
                self.assertEqual(rendered(raise_gate({"k" + ch: "v" + ch})),
                                 "FAIL g.input: {k%s: v%s}\n" % (shown, shown))

    def test_empty_dict(self):  # R4
        self.assertEqual(_raw({}), "{}")
        self.assertEqual(_raw({"a": {}}), "{a: {}}")

    def test_dict_subclasses(self):  # R5
        self.assertEqual(_raw(collections.OrderedDict([("b", 1), ("a", 2)])), "{b: 1, a: 2}")

        class Loud(dict):
            def __str__(self):
                return "LOUD"
        self.assertEqual(_raw(Loud(k="v")), "{k: v}")

    def test_non_str_keys(self):  # R6
        self.assertEqual(_raw({1: "a"}), "{1: a}")
        self.assertEqual(_raw({None: "b"}), "{None: b}")
        self.assertEqual(_raw({True: "c"}), "{True: c}")
        self.assertEqual(_raw({(1, 2): "d"}), "{[1, 2]: d}")

    def test_plain_form_is_ambiguous_like_the_list_case(self):  # R7
        self.assertEqual(_raw({"a: b": "c"}), _raw({"a": "b: c"}))
        self.assertEqual(_raw({"1": "x"}), _raw({1: "x"}))
        self.assertEqual(_raw(["a, b"]), _raw(["a", "b"]))

    def test_other_containers_unchanged(self):  # R8
        mp = types.MappingProxyType({"a": 1})
        self.assertEqual(_raw(mp), str(mp))
        self.assertEqual(_raw({1}), "{1}")
        self.assertEqual(_raw(frozenset([2])), str(frozenset([2])))
        self.assertEqual(_raw(b"x"), "b'x'")

    def test_raw_self_containing_containers(self):  # R9, Q-1c0-3 (a)
        d = {}
        d["a"] = d
        lst = []
        lst.append(lst)
        self.assertEqual(_raw(d), "{a: {...}}")
        self.assertEqual(_raw(lst), "[[...]]")
        mixed = {}
        mixed["l"] = [mixed]
        self.assertEqual(_raw(mixed), "{l: [{...}]}")
        self.assertEqual(rendered(raise_gate(d)), "FAIL g.input: {a: {...}}\n")

    def test_shared_but_acyclic_container_is_rendered_in_full(self):  # R9: the guard is the current path only
        shared = {"k": "v"}
        self.assertEqual(_raw([shared, shared]), "[{k: v}, {k: v}]")
        self.assertEqual(_raw({"a": shared, "b": shared}), "{a: {k: v}, b: {k: v}}")

    def test_gate_error_arity(self):  # R11
        self.assertEqual(rendered(raise_gate("text")), "FAIL g.input: text\n")
        self.assertEqual(rendered(raise_gate()), "FAIL g.input: \n")
        self.assertEqual(rendered(raise_gate("a", "b")), "FAIL g.input: [a, b]\n")
        self.assertEqual(rendered(lambda a: (_ for _ in ()).throw(GitNotFound("x"))), "FAIL g.input: x\n")

    def test_multi_argument_gate_error_escaped_once(self):  # owner Q-1c0-5
        self.assertEqual(rendered(raise_gate("a\\b", {"k": "c\\d"}, "x\ny")),
                         "FAIL g.input: [a\\\\b, {k: c\\\\d}, x\\ny]\n")

    def test_unexpected_exception_reasons_escaped_once(self):  # owner Q-1c0-2 (a)
        def raising(exc):
            def check(a):
                raise exc
            return check
        cases = (
            (ValueError({"k": "a\\b"}), "FAIL g.input: ValueError: {k: a\\\\b}\n"),
            (ValueError("a\\b", "c"), "FAIL g.input: ValueError: [a\\\\b, c]\n"),
            (ValueError("a\\b", {"k": "x\ny"}), "FAIL g.input: ValueError: [a\\\\b, {k: x\\ny}]\n"),
            (KeyError("a\\b", "c"), "FAIL g.input: KeyError: [a\\\\b, c]\n"),
            (RuntimeError(), "FAIL g.input: RuntimeError: \n"),
            (RuntimeError("a\\b"), "FAIL g.input: RuntimeError: a\\\\b\n"),
            (OSError(2, "gone"), "FAIL g.input: FileNotFoundError: [Errno 2] gone\n"),
        )
        for exc, want in cases:
            with self.subTest(exc=repr(exc)):
                self.assertEqual(rendered(raising(exc)), want)

    def test_own_str_exception_reasons_escaped_once(self):  # verifier V-1: classes with their own C __str__
        def raising(exc):
            def check(a):
                raise exc
            return check
        cases = (
            (AttributeError("a\\b", "c"), "AttributeError: [a\\\\b, c]"),
            (AttributeError({"k": "a\\b"}), "AttributeError: {k: a\\\\b}"),
            (NameError("a\\b", "c"), "NameError: [a\\\\b, c]"),
            (UnboundLocalError(["a\\b"]), "UnboundLocalError: [a\\\\b]"),
            (OSError({"k": "a\\b"}), "OSError: {k: a\\\\b}"),
            (OSError(["a\\b"]), "OSError: [a\\\\b]"),
            (OSError("a\\b", 1, 2, 3, 4, 5), "OSError: [a\\\\b, 1, 2, 3, 4, 5]"),
            (OSError("a\\b", {"k": "c\\d"}), "OSError: [Errno a\\\\b] {k: c\\\\d}"),
            (OSError(2, {"k": "a\\b"}), "FileNotFoundError: [Errno 2] {k: a\\\\b}"),
            (OSError(None, "a\\b"), "OSError: [Errno None] a\\\\b"),
            (OSError(2, {"k": "a\\b"}, "f"), "FileNotFoundError: [Errno 2] {k: a\\\\b}: f"),
            (ImportError("a\\b", "c"), "ImportError: [a\\\\b, c]"),
            (ImportError({"k": "a\\b"}), "ImportError: {k: a\\\\b}"),
            (ImportError("a\\b"), "ImportError: a\\\\b"),
            (ModuleNotFoundError("a\\b", {"k": "c\\d"}), "ModuleNotFoundError: [a\\\\b, {k: c\\\\d}]"),
            (SyntaxError({"k": "a\\b"}), "SyntaxError: {k: a\\\\b}"),
            (SyntaxError({"k": "a\\b"}, ("f", 1, 2, "t")), "SyntaxError: {k: a\\\\b} (f, line 1)"),
            (SyntaxError("a\\b", 1, 2, 3, 4, 5), "SyntaxError: a\\\\b"),
            (IndentationError(["a\\b"]), "IndentationError: [a\\\\b]"),
            (TabError({"k": "a\\b"}), "TabError: {k: a\\\\b}"),
        )
        for exc, want in cases:
            with self.subTest(exc=repr(exc)):
                self.assertEqual(rendered(raising(exc)), "FAIL g.input: %s\n" % want)

    def test_every_builtin_exception_reason_escaped_once(self):  # verifier V-1: the class x arity sweep
        import builtins
        argsets = (({"k": "a\\b"},), ("a\\b", "c"), ("a\\b",), (["a\\b"],), ("a\\b", 1, 2, 3, 4, 5),
                   ("a\\b", {"k": "c\\d"}), (2, {"k": "a\\b"}), (2, "x", {"k": "a\\b"}), (2, {"k": "a\\b"}, "f"))
        swept = 0
        for name in sorted(dir(builtins)):
            cls = getattr(builtins, name)
            if not (isinstance(cls, type) and issubclass(cls, Exception)):
                continue
            for args in argsets:
                try:
                    exc = cls(*args)
                except Exception:
                    continue
                swept += 1

                def check(a, exc=exc):
                    raise exc
                with self.subTest(cls=name, args=repr(args)):
                    out = rendered(check)  # an exception escaping run_check fails the subtest as an error
                    self.assertTrue(out.startswith("FAIL g.input: %s: " % type(exc).__name__), out)
                    self.assertNotIn("\\\\\\\\", out)  # one backslash in gives two out; four is a second escape
                    self.assertNotIn("'", out)  # no repr quoting of a caller value
        self.assertGreater(swept, 400)

    def test_own_str_text_kept_when_the_arguments_cannot_render(self):  # V-1 fix: str(e) worked, so no new crash
        class Bad:
            def __str__(self):
                raise RuntimeError("no str")
            __repr__ = __str__

        class Own(Exception):
            def __str__(self):
                return "own a\\b"

        class OwnSyntax(SyntaxError):
            def __str__(self):
                return "own a\\b"
        for exc, want in ((Own(Bad()), "Own: own a\\\\b"), (Own(Bad(), "x"), "Own: own a\\\\b"),
                          (OwnSyntax(Bad()), "OwnSyntax: own a\\\\b")):
            with self.subTest(exc=type(exc).__name__, n=len(exc.args)):
                self.assertEqual(rendered(lambda a, exc=exc: (_ for _ in ()).throw(exc)), "FAIL g.input: %s\n" % want)

    def test_unrenderable_arguments_still_give_a_reason(self):  # V1r-1, U-V1-1, owner Q-1C0V1R-1 (a)
        cases = (
            (ValueError(StrRaises()), "ValueError: SR"),
            (ValueError(StrRaises(), 1), "ValueError: [SR, 1]"),  # b97db1f gave (SR, 1); escaped at ea8355b
            (ValueError(ReprRaises(), 1), "ValueError: [RS, 1]"),
            (ValueError(BothRaise()), "ValueError: BothRaise"),
            (ValueError(BothRaise(), "a\\b"), "ValueError: [BothRaise, a\\\\b]"),
            (ValueError({"k": BothRaise()}), "ValueError: {k: BothRaise}"),
            (ValueError([StrRaises(), [BothRaise()]]), "ValueError: [SR, [BothRaise]]"),
            (KeyError(StrRaises(), 1), "KeyError: [SR, 1]"),
            (KeyError(BothRaise()), "KeyError: BothRaise"),
            (OSError(2, "gone", StrRaises()), "FileNotFoundError: [Errno 2] gone: SR"),
            (OSError(2, BothRaise(), "f"), "FileNotFoundError: [Errno 2] BothRaise: f"),
            (OSError(2, "gone", "f", None, BothRaise()), "FileNotFoundError: [Errno 2] gone: f -> BothRaise"),
            (OSError(2, StrRaises()), "FileNotFoundError: [2, SR]"),
            (OSError(StrRaises()), "OSError: SR"),
            (OSError(ReprRaises(), 1, 2, 3, 4, 5), "OSError: [RS, 1, 2, 3, 4, 5]"),
            (OSError(ReprRaises(), ("f\\g", 1)), "OSError: [Errno RS] [f\\\\g, 1]"),  # default text unreadable
            (ImportError(StrRaises(), 1), "ImportError: [SR, 1]"),
            (ImportError(BothRaise()), "ImportError: BothRaise"),
            (SyntaxError(StrRaises()), "SyntaxError: SR"),
            (SyntaxError(BothRaise(), ("f", 1, 2, "t")), "SyntaxError: [BothRaise, [f, 1, 2, t]]"),
            (AttributeError(StrRaises()), "AttributeError: SR"),
            (NameError(BothRaise(), 1), "NameError: [BothRaise, 1]"),
            (GateError(StrRaises()), "SR"),
            (GateError(BothRaise(), "a\\b"), "[BothRaise, a\\\\b]"),
            (SystemExit(StrRaises()), "exit requested (SR)"),
            (SystemExit(BothRaise()), "exit requested (BothRaise)"),
            (BrokenArgs("x"), "BrokenArgs: BrokenArgs"),
        )
        for exc, want in cases:
            with self.subTest(exc=type(exc).__name__, n=len(exc.args) if type(exc) is not BrokenArgs else -1):
                self.assertEqual(escaping_or_rendered(exc), "FAIL g.input: %s\n" % want)

    def test_every_builtin_exception_gives_a_reason_for_unrenderable_arguments(self):  # V1r-1 sweep
        import builtins
        argsets = []
        for bad in (StrRaises(), ReprRaises(), BothRaise()):
            argsets += [(bad,), (bad, 1), ({"k": bad},), ([bad],), (2, bad), (2, "s", bad), (2, bad, "f"),
                        (2, "s", "f", None, bad), (bad, ("f", 1, 2, "t")), (bad, 1, 2, 3, 4, 5)]
        swept = 0
        for name in sorted(dir(builtins)):
            cls = getattr(builtins, name)
            if not (isinstance(cls, type) and issubclass(cls, Exception)):
                continue
            for args in argsets:
                try:
                    exc = cls(*args)
                except Exception:
                    continue
                swept += 1
                with self.subTest(cls=name, args=len(args)):
                    out = escaping_or_rendered(exc)
                    self.assertTrue(out.startswith("FAIL g.input: %s: " % type(exc).__name__), out)
        self.assertGreater(swept, 1000)

    def test_uniterable_container_collapses_to_the_type_name(self):  # V1r2-1, owner Q-1C0V1R-3 (b)(i)
        class IterDict(dict):
            def items(self):
                raise RuntimeError("no items")

        class IterList(list):
            def __iter__(self):
                raise RuntimeError("no iter")
        cases = (
            (ValueError(IterDict(k=1)), "ValueError: ValueError"),
            (ValueError("ok", IterList([1])), "ValueError: ValueError"),  # the renderable "ok" is dropped too
            (KeyError(IterList([1])), "KeyError: KeyError"),
            (OSError(2, "s", IterList([1])), "FileNotFoundError: FileNotFoundError"),
            (ImportError(IterDict(k="a\\b"), 1), "ImportError: ImportError"),  # own __str__ fell back to repr
            (AttributeError(IterDict(k="a\\b"), 1), "AttributeError: AttributeError"),  # own __str__ on 3.12+
            (OSError(2, IterList(["a\\b"])), "FileNotFoundError: FileNotFoundError"),  # the [Errno] form
            (SyntaxError(IterList(["a\\b"])), "SyntaxError: SyntaxError"),
            (SyntaxError(IterList(["a\\b"]), ("f", 1, 2, "t")), "SyntaxError: SyntaxError"),
            (GateError(IterDict(k=1)), "GateError"),
            (SystemExit(IterList([1])), "exit requested (SystemExit)"),
        )
        for exc, want in cases:
            with self.subTest(exc=type(exc).__name__):
                self.assertEqual(escaping_or_rendered(exc), "FAIL g.input: %s\n" % want)

    def test_nesting_past_the_recursion_limit_collapses_to_the_type_name(self):  # V1r2-1, Q-1C0V1R-3 (b)(i)
        deep = []
        for _ in range(sys.getrecursionlimit() + 100):
            deep = [deep]
        for exc, want in ((ValueError(deep), "ValueError: ValueError"), (KeyError(deep), "KeyError: KeyError"),
                          (GateError(deep), "GateError"), (SystemExit(deep), "exit requested (SystemExit)")):
            with self.subTest(exc=type(exc).__name__):
                self.assertEqual(escaping_or_rendered(exc), "FAIL g.input: %s\n" % want)

    def test_base_exception_from_rendering_propagates(self):  # owner Q-1C0V1R-2 (a)(i): as from the check itself
        class StrExit:
            def __str__(self):
                raise SystemExit("from str")
            __repr__ = __str__

        class StrKbd:
            def __str__(self):
                raise KeyboardInterrupt()
            __repr__ = __str__
        for exc in (ValueError(StrExit()), KeyError(StrExit()), OSError(2, "s", StrExit()), GateError(StrExit()),
                    ImportError(StrExit(), 1)):
            with self.subTest(exc=type(exc).__name__):
                with self.assertRaises(SystemExit) as cm:
                    rendered(lambda a, exc=exc: (_ for _ in ()).throw(exc))
                self.assertEqual(cm.exception.code, "from str")
        with self.assertRaises(KeyboardInterrupt):
            rendered(lambda a: (_ for _ in ()).throw(ValueError(StrKbd())))

    def test_other_exception_paths_with_a_map(self):  # R12
        def key_error(a):
            raise KeyError({"k": "\\"})

        def exit_(a):
            raise SystemExit({"k": "\\"})
        self.assertEqual(rendered(key_error), "FAIL g.input: KeyError: {k: \\\\}\n")
        self.assertEqual(rendered(exit_), "FAIL g.input: exit requested ({k: \\\\})\n")

    def test_generated_nesting_is_escaped_once(self):  # oracle: an independent recursive formatter
        leaves = ["a", "\\", "\n", "\t", '"', "'", "\x00", "\x7f", "\u00e9", "\u2028", "x\\y\nz"]
        rng = random.Random(20261102)

        def make(depth):
            kind = rng.randrange(3) if depth else 0
            if kind == 0:
                return rng.choice(leaves)
            if kind == 1:
                return [make(depth - 1) for _ in range(rng.randrange(3))]
            return {rng.choice(leaves) + str(i): make(depth - 1) for i in range(rng.randrange(3))}

        def fmt(v):
            if isinstance(v, dict):
                return "{" + ", ".join(fmt(k) + ": " + fmt(x) for k, x in v.items()) + "}"
            if isinstance(v, list):
                return "[" + ", ".join(fmt(x) for x in v) + "]"
            return v
        for n in range(200):
            v = make(3)
            with self.subTest(n=n):
                self.assertEqual(rendered(raise_gate(v)), "FAIL g.input: " + safe_text(fmt(v)) + "\n")


class ReasonSitesTest(GitIsolatedTestCase):
    """Q-1c0-2 (a): every reason that formats a caller value renders a map once (store.py:71 and :227, schema.py:350,
    findings.py:94, decisions.py:122)."""

    MAP = {"k": "a\\b"}

    def fail_line(self, reason):
        res = Result("x", [])
        res.fail("x.r", reason)
        return res.render(False)

    def test_reason_sites_render_map_once(self):
        root = make_repo(self.work)
        cfg = config.load(root)
        sites = {
            "store.path_for": lambda: run_check("x", lambda a: Store(root, "decision", cfg).path_for(self.MAP),
                                                [self.MAP]).render(False),
            "store.store_errors name": lambda: self.fail_line([r for s, r in store_errors([Record(self.MAP, {}, "d/c.yml")], "DEC")
                                                if s.startswith("name.")][0]),
            "schema.validate": lambda: self.fail_line(findings.validate({"schema": self.MAP}, cfg)[0]),
            "findings.transition_errors": lambda: self.fail_line(findings.transition_errors(
                {"status": self.MAP, "history": [{"status": "open"}]})[-1]),
            "decisions.landed_errors": lambda: self.fail_line(decisions.landed_errors(
                {"landed_in": [self.MAP]}, root, cfg, frozenset())[0]),
        }
        want = {
            "store.path_for": "FAIL x.input: cannot use id {k: a\\\\b}: id is not a string (dict); ",
            "store.store_errors name": "FAIL x.r: file name c.yml differs from the record id {k: a\\\\b}\n",
            "schema.validate": "FAIL x.r: schema: expected finding/1, got {k: a\\\\b}\n",
            "findings.transition_errors": "FAIL x.r: status: {k: a\\\\b} differs from the last history entry (open)\n",
            "decisions.landed_errors": "FAIL x.r: landed_in: {k: a\\\\b} is not a string\n",
        }
        for name, site in sites.items():
            with self.subTest(site=name):
                line = site()
                self.assertNotIn("\\\\\\\\", line)
                self.assertNotIn("{'", line)
                self.assertTrue(line.startswith(want[name]), line)


class SOk(str):
    """A str subclass with its own working ``__str__`` (F-1c0fin2-2)."""

    def __str__(self):
        return "OTHER"


class SBad(str):
    """A str subclass whose ``__str__``, ``__repr__``, ``__add__``, ``__radd__``, ``__mod__``, ``__eq__`` and
    ``__format__`` raise (F-1c0fin2-1): if any of them ran, the reason would not be its characters."""

    def _no(self, *a):
        raise RuntimeError("no")
    __str__ = __repr__ = __add__ = __radd__ = __mod__ = __eq__ = __format__ = _no
    __hash__ = str.__hash__


class SOdd(str):
    """A str subclass whose ``__str__`` returns an ``SBad``."""

    def __str__(self):
        return SBad("inner")


class IOdd(int):
    """An int subclass whose ``__str__`` returns an ``SBad`` (the text a ``__str__`` returns is its characters)."""

    def __str__(self):
        return SBad("7")


class FSub(float):
    def __str__(self):
        return "F"


class OwnStrBad(Exception):
    """An own ``__str__`` returning an ``SBad``."""

    def __str__(self):
        return SBad("own\\x")


class OwnStrOk(Exception):
    def __str__(self):
        return SOk("own\\x")


class _RaisingName(type):
    @property
    def __name__(cls):
        raise RuntimeError("no name")


class MetaNamed(Exception, metaclass=_RaisingName):
    """An exception whose class's ``__name__`` lookup raises."""


class SubNamed(Exception):
    pass


SubNamed.__name__ = SBad("Sub\\Named")  # a type name that is a str subclass


class LeafSubNamed:
    def __str__(self):
        raise RuntimeError("no str")
    __repr__ = __str__


LeafSubNamed.__name__ = SBad("Leaf\\Named")

C = "a\\b"
# (label, argument factory, text the argument renders as): owner Q-1C0FIN2-R1 (a), a str subclass is its characters
KINDS = [
    ("exact", lambda: C, C),
    ("SOk", lambda: SOk(C), C),
    ("SBad", lambda: SBad(C), C),
    ("SOdd", lambda: SOdd(C), C),
    ("IOdd", lambda: IOdd(7), "7"),
    ("FSub", lambda: FSub(1.5), "F"),
    ("list", lambda: [SBad(C), SOk(C)], "[a\\b, a\\b]"),
    ("dict", lambda: {SBad("k"): SOk("v"), IOdd(1): SBad("w")}, "{k: v, 7: w}"),
    ("BothRaise", BothRaise, "BothRaise"),
    ("LeafSubNamed", LeafSubNamed, "Leaf\\Named"),
]
STR_KINDS = ("exact", "SOk", "SBad", "SOdd")


def _forms(label, v):
    """(form label, exception factory taking the argument, the reason): every run_check branch."""
    se = "exit requested ('%s')" % v if label in STR_KINDS else "exit requested (%s)" % v
    # [2, ...]: CPython's own str(e) cannot run, so the arguments are shown (as the OSError(2, StrRaises()) pin)
    oss = "FileNotFoundError: [2, %s]" % v if label in ("SBad", "list", "dict", "BothRaise", "LeafSubNamed") else \
        "FileNotFoundError: [Errno 2] %s" % v
    return [
        ("GateError", GateError, v),
        ("SystemExit", SystemExit, se),
        ("KeyError", KeyError, "KeyError: " + v),
        ("ValueError", ValueError, "ValueError: " + v),
        ("ValueError2", lambda a: ValueError(a, 1), "ValueError: [%s, 1]" % v),
        ("OSError strerror", lambda a: OSError(2, a), oss),
        ("OSError filename", lambda a: OSError(2, "s", a), "FileNotFoundError: [Errno 2] s: " + v),
    ]


def both_modes(check):
    """(text line, json reason, the reason's type, the id's type) through run_gate and run_check; an escaping
    exception becomes ``ESCAPED <type>``."""
    try:
        text = run("g", check, [])[1]
        reason = json.loads(run("g", check, ["--json"])[1])["lines"][0]["reason"]
        ln = run_check("g", check, []).lines[0]
    except Exception as x:
        return "ESCAPED %s" % type(x).__name__
    return text, reason, type(ln.reason), type(ln.id)


def raising(make):
    def check(a):
        raise make()
    return check


class ExactReasonTest(unittest.TestCase):
    """F-1c0fin2-1, F-1c0fin2-2, owner Q-1C0FIN2-R1 (a) and Q-1C0FIN2-R2 (a): every reason and id that leaves
    run_check is an exact str, the same in text and --json, and no method of a str subclass runs."""

    def test_every_kind_in_every_branch_and_mode(self):  # F-1c0fin2-1, F-1c0fin2-2
        for label, make_arg, v in KINDS:
            for form, make_exc, want in _forms(label, v):
                with self.subTest(kind=label, form=form):
                    got = both_modes(raising(lambda: make_exc(make_arg())))
                    self.assertEqual(got, ("FAIL g.input: %s\n" % safe_text(want), want, str, str))

    def test_str_subclass_same_rule_in_both_modes(self):  # F-1c0fin2-2: its characters, never its __str__
        for n, make in enumerate((lambda: GateError(SOk(C)), lambda: ValueError(SOk(C)), lambda: KeyError(SOk(C)),
                                  lambda: SystemExit(SOk(C)), lambda: OSError(2, SOk(C)))):
            with self.subTest(n=n):
                got = both_modes(raising(make))
                self.assertNotIn("OTHER", "".join(got[:2]))
                self.assertEqual(got[0], "FAIL g.input: %s\n" % safe_text(got[1]))

    def test_own_str_returning_a_str_subclass(self):  # the text an own __str__ returns is its characters
        self.assertEqual(both_modes(raising(lambda: OwnStrBad("x"))),
                         ("FAIL g.input: OwnStrBad: own\\\\x\n", "OwnStrBad: own\\x", str, str))
        self.assertEqual(both_modes(raising(lambda: OwnStrOk("x"))),
                         ("FAIL g.input: OwnStrOk: own\\\\x\n", "OwnStrOk: own\\x", str, str))

    def test_type_names(self):  # a type name that is a str subclass, or whose lookup raises
        self.assertEqual(both_modes(raising(lambda: SubNamed("x"))),
                         ("FAIL g.input: Sub\\\\Named: x\n", "Sub\\Named: x", str, str))
        self.assertEqual(both_modes(raising(lambda: MetaNamed("x"))),
                         ("FAIL g.input: MetaNamed: x\n", "MetaNamed: x", str, str))
        self.assertEqual(both_modes(lambda a: SubNamed()),
                         ("FAIL g.input: the check returned Sub\\\\Named, not a Result\n",
                          "the check returned Sub\\Named, not a Result", str, str))

    def test_own_result_reasons_and_ids(self):  # owner Q-1C0FIN2-R2 (a); X5: a non-str value goes through str()
        reasons = [(C, C), (SOk(C), C), (SBad(C), C), (SOdd(C), C), (IOdd(7), "7"), (FSub(1.5), "F"),
                   ([C], "['a\\\\b']"), ({"k": "v"}, "{'k': 'v'}"), (BothRaise(), "BothRaise"),
                   (LeafSubNamed(), "Leaf\\Named"), (None, "None"), (1, "1")]
        for n, (value, want) in enumerate(reasons):
            with self.subTest(reason=n):
                self.assertEqual(both_modes(result_with(value)),
                                 ("FAIL x.bad: %s\n" % safe_text(want), want, str, str))
        for n, (value, want) in enumerate(((SBad("x.\\id"), "x.\\id"), (SOk("x.id"), "x.id"), (5, "5"),
                                           (BothRaise(), "BothRaise"))):
            with self.subTest(id=n):
                try:
                    text = run("g", result_with("r", id=value), [])[1]
                    out = json.loads(run("g", result_with("r", id=value), ["--json"])[1])["lines"][0]
                    ln = run_check("g", result_with("r", id=value), []).lines[0]
                    got = (text, out["id"], type(ln.id))
                except Exception as x:
                    got = "ESCAPED %s" % type(x).__name__
                self.assertEqual(got, ("FAIL %s: r\n" % safe_text(want), want, str))

    def test_sets_escaped_once_in_sorted_order(self):  # owner Q-1C0FIN2-1 (b): items sorted by their rendered text
        class SetSub(set):
            def __repr__(self):
                raise RuntimeError("no repr")
        cases = [({"b\\", "a\\"}, "{a\\, b\\}"), (frozenset({"z", "a\nb"}), "frozenset({a\nb, z})"),
                 (set(), "set()"), (frozenset(), "frozenset()"), ({SBad("y"), 2, "x"}, "{2, x, y}"),
                 ([frozenset({"q\\"})], "[frozenset({q\\})]"), ({"k": {"v\\"}}, "{k: {v\\}}"),
                 (SetSub({"s\\"}), "{s\\}"), ({frozenset({"b"}), "a"}, "{a, frozenset({b})}")]
        for n, (value, want) in enumerate(cases):
            with self.subTest(n=n):
                try:
                    got = (_raw(value), type(_raw(value)), rendered(raise_gate(value)),
                           rendered(raising(lambda: ValueError(value))))
                except Exception as x:
                    got = "ESCAPED %s" % type(x).__name__
                self.assertEqual(got, (want, str, "FAIL g.input: %s\n" % safe_text(want),
                                       "FAIL g.input: ValueError: %s\n" % safe_text(want)))

    def test_bytes_escaped_once(self):  # owner Q-1C0FIN2-1 (b), Q-F80W-3 (a): b' + Latin-1 + ', always '
        class BSub(bytes):
            def decode(self, *a):
                raise RuntimeError("no decode")
            __repr__ = __str__ = decode
        cases = [(b"a\\b", "b'a\\b'"), (b"it's", "b'it's'"), (b"'\"", "b''\"'"), (b"", "b''"),
                 (b"\x00\n\t\x7f\x80\xe9", "b'\x00\n\t\x7f\x80\xe9'"), ([b"a\\b"], "[b'a\\b']"),
                 (BSub(b"s\\"), "b's\\'")]
        for n, (value, want) in enumerate(cases):
            with self.subTest(n=n):
                try:
                    got = (_raw(value), type(_raw(value)), both_modes(raise_gate(value)),
                           both_modes(raising(lambda: KeyError(value))))
                except Exception as x:
                    got = "ESCAPED %s" % type(x).__name__
                self.assertEqual(got, (want, str, ("FAIL g.input: %s\n" % safe_text(want), want, str, str),
                                       ("FAIL g.input: KeyError: %s\n" % safe_text(want), "KeyError: " + want,
                                        str, str)))
        self.assertEqual(safe_text(_raw(b"\x00\n\\")), repr(b"\x00\n\\"))  # ASCII, no quote: repr's text

    def test_oserror_bytes_filename_escaped_once(self):  # owner Q-1C0FIN2-1 (b)
        for exc, want in ((OSError(2, "s", b"a\\b"), "FileNotFoundError: [Errno 2] s: b'a\\b'"),
                          (OSError(2, "s", "f", None, b"g\\h"), "FileNotFoundError: [Errno 2] s: f -> b'g\\h'"),
                          (OSError(2, b"e\\r"), "FileNotFoundError: [Errno 2] b'e\\r'")):
            with self.subTest(exc=want):
                self.assertEqual(both_modes(raising(lambda: exc)),
                                 ("FAIL g.input: %s\n" % safe_text(want), want, str, str))

    def test_set_order_does_not_depend_on_the_hash_seed(self):
        code = ("from gates.lib.result import _raw; "
                "print(_raw([{'q%d' % i for i in range(40)} | {frozenset({'b', 'a', 'c'}), b'x\\\\y'},"
                " frozenset('abcdefgh')]))")
        outs = set()
        for seed in ("0", "1", "12345"):
            env = dict(os.environ, PYTHONHASHSEED=seed, PYTHONDONTWRITEBYTECODE="1")
            outs.add(subprocess.run([sys.executable, "-c", code], cwd=REPO, env=env, capture_output=True,
                                    text=True, check=True).stdout)
        self.assertEqual(len(outs), 1, outs)


class ROLine(Line):
    """A Line whose attributes cannot be assigned once frozen (F-fin2r-1)."""

    def __setattr__(self, k, v):
        if getattr(self, "_frozen", False):
            raise AttributeError("read-only line")
        object.__setattr__(self, k, v)


def frozen_line(*a):
    ln = ROLine(*a)
    ln._frozen = True
    return ln


class UnreadLine(Line):
    """A Line whose ``reason`` cannot be read."""

    def __getattribute__(self, k):
        if k == "reason":
            raise RuntimeError("no reason")
        return object.__getattribute__(self, k)


class KbdLine(Line):
    def __getattribute__(self, k):
        if k == "reason":
            raise KeyboardInterrupt()
        return object.__getattribute__(self, k)


class UnreadResult(Result):
    def __getattribute__(self, k):
        if k == "lines":
            raise RuntimeError("no lines")
        return object.__getattribute__(self, k)


class OddList(list):
    def _no(self, *a):
        raise RuntimeError("no")
    __iter__ = __len__ = __bool__ = __getitem__ = _no


def returning(make):
    return lambda a: make()


def shape_of(make):
    """(text, json line, the json gate, the rendered lines' types) for a check returning ``make()``."""
    check = returning(make)
    try:
        text = run("g", check, [])[1]
        js = json.loads(run("g", check, ["--json"])[1])
        r = run_check("g", check, [])
    except Exception as x:
        return "ESCAPED %s" % type(x).__name__
    kinds = {(type(r.gate), type(ln.status), type(ln.id), type(ln.reason)) for ln in r.lines}
    return text, js["lines"], js["gate"], kinds, type(r) is Result and all(type(ln) is Line for ln in r.lines)


def refused(reason):
    return ("FAIL g.input: %s\n" % safe_text(reason), [{"status": "FAIL", "id": "g.input", "reason": reason}], "g",
            {(str, str, str, str)}, True)


class ResultShapeTest(unittest.TestCase):
    """F-fin2r-1 and owner Q-1C0FIN2-U2 (a): run_check checks the whole shape of a Result a check returns and fails
    it on ``<gate>.input`` (spec §13) with a named reason, never raising; it never changes the check's Result."""

    def test_line_whose_attributes_cannot_be_assigned(self):  # F-fin2r-1
        got = shape_of(lambda: Result("g", [frozen_line("FAIL", "g.x", SBad("a\\b"))]))
        self.assertEqual(got, ("FAIL g.x: a\\\\b\n", [{"status": "FAIL", "id": "g.x", "reason": "a\\b"}], "g",
                               {(str, str, str, str)}, True))

    def test_checks_result_is_not_changed(self):  # F-fin2r-1
        ln = Line("FAIL", SBad("g.\\x"), SBad("r"))
        shared = Result("g", [ln])
        lines = shared.lines
        self.assertEqual(run("g", returning(lambda: shared), [])[1], "FAIL g.\\\\x: r\n")
        self.assertEqual(run("g", returning(lambda: shared), ["--json"])[0], 1)
        self.assertIs(shared.lines, lines)
        self.assertIs(shared.lines[0], ln)
        self.assertEqual((type(ln.id), type(ln.reason)), (SBad, SBad))

    def test_well_formed_shapes_render(self):
        cases = [
            (lambda: Result("g", [Line("PASS", "g.a"), Line("FAIL", "g.b", "r")]),
             "PASS g.a\nFAIL g.b: r\n", [{"status": "PASS", "id": "g.a", "reason": ""},
                                         {"status": "FAIL", "id": "g.b", "reason": "r"}]),
            (lambda: Result("g", OddList([Line("PASS", "g.a")])), "PASS g.a\n",
             [{"status": "PASS", "id": "g.a", "reason": ""}]),
            (lambda: Result("g", [Line("PASS", "g.a", SBad("x"))]), "PASS g.a\n",
             [{"status": "PASS", "id": "g.a", "reason": "x"}]),
        ]
        for n, (make, text, lines) in enumerate(cases):
            with self.subTest(n=n):
                self.assertEqual(shape_of(make), (text, lines, "g", {(str, str, str, str)}, True))

    def test_gate_not_an_exact_str(self):
        for n, (gate, name) in enumerate(((SOk("g"), "SOk"), (SBad("g"), "SBad"), (1, "int"), (None, "NoneType"),
                                          (BothRaise(), "BothRaise"), (LeafSubNamed(), "Leaf\\Named"))):
            with self.subTest(n=n):
                self.assertEqual(shape_of(lambda: Result(gate, [Line("PASS", "g.a")])),
                                 refused("the check returned a Result whose gate is %s, not a str" % name))

    def test_lines_not_a_list(self):
        for n, (lines, name) in enumerate((((Line("PASS", "g.a"),), "tuple"), (None, "NoneType"),
                                           ("PASS", "str"), ({"a": 1}, "dict"),
                                           ((x for x in [Line("PASS", "g.a")]), "generator"))):
            with self.subTest(n=n):
                self.assertEqual(shape_of(lambda: Result("g", lines)),
                                 refused("the check returned a Result whose lines is %s, not a list" % name))

    def test_entry_not_a_line(self):
        for n, (entry, name) in enumerate((("x", "str"), (None, "NoneType"), (("PASS", "g.a"), "tuple"),
                                           ({"status": "PASS"}, "dict"), (BothRaise(), "BothRaise"))):
            with self.subTest(n=n):
                self.assertEqual(shape_of(lambda: Result("g", [Line("PASS", "g.a"), entry])),
                                 refused("line 2 of the Result is %s, not a Line" % name))

    def test_status_not_an_exact_str(self):
        for n, (status, name) in enumerate(((SOk("FAIL"), "SOk"), (SBad("PASS"), "SBad"), (1, "int"),
                                            (None, "NoneType"), (BothRaise(), "BothRaise"))):
            with self.subTest(n=n):
                self.assertEqual(shape_of(lambda: Result("g", [Line(status, "g.a", "r")])),
                                 refused("line 1 of the Result has a status of type %s, not str" % name))

    def test_status_outside_pass_and_fail(self):
        for n, status in enumerate(("pass", "OK", "", " PASS", "FAIL\n", "Fail", "a\\b")):
            with self.subTest(n=n):
                self.assertEqual(shape_of(lambda: Result("g", [Line(status, "g.a", "r")])),
                                 refused("line 1 of the Result has status %s, not PASS or FAIL" % status))

    def test_unreadable_result_and_line(self):
        self.assertEqual(shape_of(lambda: UnreadResult("g", [Line("PASS", "g.a")])),
                         refused("the check returned a Result that cannot be read"))
        self.assertEqual(shape_of(lambda: Result("g", [Line("PASS", "g.a"), UnreadLine("FAIL", "g.b", "r")])),
                         refused("line 2 of the Result cannot be read"))

    def test_base_exception_while_reading_propagates(self):  # owner Q-1C0V1R-2 (a)(i)
        with self.assertRaises(KeyboardInterrupt):
            run_check("g", returning(lambda: Result("g", [KbdLine("FAIL", "g.b", "r")])), [])

    def test_empty_and_not_a_result_unchanged(self):  # pins x.empty and "not a Result" keep their text
        self.assertEqual(shape_of(lambda: Result("g", [])),
                         ("FAIL g.empty: the gate produced no lines\n",
                          [{"status": "FAIL", "id": "g.empty", "reason": "the gate produced no lines"}], "g",
                          {(str, str, str, str)}, True))
        self.assertEqual(shape_of(lambda: None), refused("the check returned NoneType, not a Result"))


if __name__ == "__main__":
    unittest.main()
