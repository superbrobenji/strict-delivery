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


if __name__ == "__main__":
    unittest.main()
