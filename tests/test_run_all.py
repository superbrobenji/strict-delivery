"""Tests of gates/run_all.py through check() / main() and ``python3 -m gates run_all`` (Task 2b.1 input-domain table:
rows K, P, G, B, A, C, O and the PC1 skeleton rows S). Fake gates enter only through ``gates.__main__.GATES`` entries
naming modules registered in ``sys.modules`` (or written to a scratch import path); real gates run on ``make_repo``
fixtures. Expected texts are written by hand from spec 12 and 13, the plan (P:1505-1516) and the table."""
import builtins
import contextlib
import importlib
import io
import itertools
import json
import os
import subprocess
import sys
import types
import unicodedata
import unittest
from unittest import mock

from gates import __main__ as gates_main
from gates import run_all
from gates.lib.result import GateError, Line, Result
from tests.helpers import (E128, TOP, GitIsolatedTestCase, check_root_forms, commit_all, git, make_repo,
                           minimal_config, root_forms, write_record)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIVE = ("schema", "register", "decisions", "claims", "cites")
BASE_ONES = ("register", "decisions", "claims")
CONFIG = ".strict-delivery/config.yml"
UNSET = object()
HAS_EG = hasattr(builtins, "ExceptionGroup")
PASS5 = "".join("PASS %s.ok\n" % g for g in FIVE)


def ok_lines(*gates):
    return "".join("PASS %s.ok\n" % g for g in gates)


def input_fail(reason):
    return "FAIL run_all.input: %s\n" % reason


class RunAllCase(GitIsolatedTestCase):
    """Fixture helpers shared by every test: profile repositories, fake gates, recorders, run helpers."""

    _n = itertools.count()

    def setUp(self):
        super().setUp()
        self.seen = []        # (gate, args at entry) in call order
        self._dirs = itertools.count()

    # ---- fixtures
    def fixture(self, profile="strict", config=None):
        d = os.path.join(self.tmp, "repo%d" % next(self._dirs))
        os.mkdir(d)
        return make_repo(d, config if config is not None else dict(minimal_config(), profile=profile))

    # ---- patching of dict entries, restored after the test (only the keys touched, never a whole sys.modules)
    def put(self, d, key, value):
        old = d.get(key, UNSET)

        def restore():
            if old is UNSET:
                d.pop(key, None)
            else:
                d[key] = old
        self.addCleanup(restore)
        if value is UNSET:
            d.pop(key, None)
        else:
            d[key] = value

    def fake(self, gate, check=UNSET, **attrs):
        """Register a fake module for ``gate`` whose ``check`` is ``check`` (no attribute when UNSET)."""
        name = "tests_fake_gate_%s_%d" % (gate, next(self._n))
        mod = types.ModuleType(name)
        if check is not UNSET:
            mod.check = check
        for k, v in attrs.items():
            setattr(mod, k, v)
        self.put(gates_main.GATES, gate, name)
        self.put(sys.modules, name, mod)
        return mod

    def recorder(self, gate, lines=None, mutate=False):
        """A check that records the args it got and returns ``lines`` (default one PASS gate.ok line)."""
        def check(args):
            self.seen.append((gate, list(args)))
            if mutate:
                args.insert(0, "--junk")
                args.append("--junk2")
                del args[1:2]
            res = Result(gate)
            for ln in (lines if lines is not None else [Line("PASS", gate + ".ok")]):
                res.lines.append(ln)
            return res
        return check

    def all_pass(self, **lines):
        for g in FIVE:
            self.fake(g, self.recorder(g, lines.get(g)))

    def called(self):
        return [g for g, _ in self.seen]

    def args_of(self):
        return {g: a for g, a in self.seen}

    def file_module(self, body):
        """A module file on a scratch import path; its name is returned (unique, never imported before)."""
        if not hasattr(self, "_modir"):
            self._modir = os.path.join(self.tmp, "mods")
            os.mkdir(self._modir)
            sys.path.insert(0, self._modir)
            self.addCleanup(lambda: sys.path.remove(self._modir))
        name = "tests_fakefile_%d" % next(self._n)
        with open(os.path.join(self._modir, name + ".py"), "w", encoding="utf-8") as fh:
            fh.write(body)
        importlib.invalidate_caches()
        self.addCleanup(lambda: sys.modules.pop(name, None))
        return name

    # ---- running
    def run_main(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = run_all.main(argv)
        return out.getvalue(), code

    def sub(self, argv, command=("run_all",)):
        p = subprocess.run([sys.executable, "-m", "gates"] + list(command) + list(argv), cwd=REPO,
                           env=dict(os.environ), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return p.stdout.decode("utf-8"), p.returncode

    def expect(self, argv, text, code, called=None):
        out, got = self.run_main(argv)
        self.assertEqual(out, text)
        self.assertEqual(got, code)
        if called is not None:
            self.assertEqual(self.called(), called)


class ConstantsTest(unittest.TestCase):
    def test_profile_gates_literal(self):  # K1
        want = {"light": ("schema", "register", "decisions"),
                "standard": ("schema", "register", "decisions", "claims", "cites"),
                "strict": ("schema", "register", "decisions", "claims", "cites")}
        self.assertIs(type(run_all.PROFILE_GATES), dict)
        self.assertEqual(run_all.PROFILE_GATES, want)
        self.assertEqual(set(run_all.PROFILE_GATES), {"light", "standard", "strict"})
        for k, v in run_all.PROFILE_GATES.items():
            self.assertIs(type(v), tuple, k)

    def test_base_gates_literal(self):  # K2
        self.assertIs(type(run_all.BASE_GATES), tuple)
        self.assertEqual(run_all.BASE_GATES, ("decisions", "register", "claims"))

    def test_profile_gates_registered(self):  # K3
        names = {g for v in run_all.PROFILE_GATES.values() for g in v}
        self.assertEqual(names, set(FIVE))
        for g in names:
            self.assertIn(g, gates_main.GATES)

    def test_excluded_gates_absent(self):  # K4
        names = {g for v in run_all.PROFILE_GATES.values() for g in v}
        for g in ("dispatch", "streams", "context", "drift", "checkpoint", "cleanup", "index", "evidence",
                  "run_all"):
            self.assertNotIn(g, names)
        self.assertNotIn("run_all", gates_main.GATES)


class ProfileTest(RunAllCase):
    def test_light_runs_profile_gates_in_order(self):  # P1
        self.all_pass()
        root = self.fixture("light")
        self.expect(["--root", root], ok_lines("schema", "register", "decisions"), 0,
                    ["schema", "register", "decisions"])

    def test_standard_runs_profile_gates_in_order(self):  # P2
        self.all_pass()
        root = self.fixture("standard")
        self.expect(["--root", root], PASS5, 0, list(FIVE))

    def test_strict_runs_profile_gates_in_order(self):  # P3
        self.all_pass()
        root = self.fixture("strict")
        self.expect(["--root", root], PASS5, 0, list(FIVE))

    def test_bad_profile_is_input_fail(self):  # P4
        reason = ".strict-delivery/config.yml: profile: must be one of light, standard, strict"
        self.all_pass()
        for value in ("extreme", "Strict", "", ["strict"], 1):
            with self.subTest(value=value):
                del self.seen[:]
                root = self.fixture(config=dict(minimal_config(), profile=value))
                self.expect(["--root", root], input_fail(reason), 1, [])


class GateListTest(RunAllCase):
    def test_missing_gate_fails(self):  # G1
        self.all_pass()
        self.put(gates_main.GATES, "claims", UNSET)
        root = self.fixture()
        self.expect(["--root", root],
                    ok_lines("schema", "register", "decisions")
                    + "FAIL run_all.missing.claims: not registered in gates.__main__.GATES\n"
                    + ok_lines("cites"), 1, ["schema", "register", "decisions", "cites"])

    def test_import_failure_is_missing(self):  # G2
        root = self.fixture()
        cases = [
            ("own module absent", None, "gates/gate_nosuch_claims_xx.py missing"),
            ("dependency ModuleNotFoundError", "import tests_no_such_dependency_xx\n", "ModuleNotFoundError"),
            ("ImportError", "raise ImportError('x')\n", "ImportError"),
            ("ValueError", "raise ValueError('x')\n", "ValueError"),
            ("SyntaxError", "def (:\n", "SyntaxError"),
            ("SystemExit", "raise SystemExit(4)\n", "SystemExit"),
        ]
        for label, body, why in cases:
            with self.subTest(label):
                del self.seen[:]
                self.all_pass()
                if body is None:
                    self.put(gates_main.GATES, "claims", "gates.gate_nosuch_claims_xx")
                    reason = why
                else:
                    name = self.file_module(body)
                    self.put(gates_main.GATES, "claims", name)
                    reason = "import of %s raised %s" % (name, why)
                self.expect(["--root", root],
                            ok_lines("schema", "register", "decisions")
                            + "FAIL run_all.missing.claims: %s\n" % reason + ok_lines("cites"), 1,
                            ["schema", "register", "decisions", "cites"])

    def test_import_keyboardinterrupt_propagates(self):  # G3
        root = self.fixture()
        for exc in ("KeyboardInterrupt", "GeneratorExit"):
            with self.subTest(exc):
                self.all_pass()
                self.put(gates_main.GATES, "claims", self.file_module("raise %s()\n" % exc))
                with self.assertRaises(getattr(builtins, exc)):
                    run_all.check(["--root", root])
                with self.assertRaises(getattr(builtins, exc)):
                    self.run_main(["--root", root])

    def test_no_check_is_missing(self):  # G4
        self.all_pass()
        mod = self.fake("claims")
        root = self.fixture()
        self.expect(["--root", root],
                    ok_lines("schema", "register", "decisions")
                    + "FAIL run_all.missing.claims: %s has no check\n" % mod.__name__ + ok_lines("cites"), 1,
                    ["schema", "register", "decisions", "cites"])

    def test_check_attribute_read_raising_is_missing(self):  # G4 sibling: reading check raises
        self.all_pass()

        def getattr_(name):
            raise ValueError("no")
        mod = self.fake("claims", __getattr__=getattr_)
        root = self.fixture()
        self.expect(["--root", root],
                    ok_lines("schema", "register", "decisions")
                    + "FAIL run_all.missing.claims: reading %s.check raised ValueError\n" % mod.__name__
                    + ok_lines("cites"), 1, ["schema", "register", "decisions", "cites"])

    def test_uncallable_check_is_missing(self):  # G5
        root = self.fixture()
        for value, tname in ((1, "int"), (None, "NoneType"), ("x", "str")):
            with self.subTest(value=value):
                del self.seen[:]
                self.all_pass()
                mod = self.fake("claims", value)
                self.expect(["--root", root],
                            ok_lines("schema", "register", "decisions")
                            + "FAIL run_all.missing.claims: %s.check is not callable (%s)\n" % (mod.__name__, tname)
                            + ok_lines("cites"), 1, ["schema", "register", "decisions", "cites"])

    def test_raising_gate_fails(self):  # G6
        root = self.fixture()
        raises = [(GateError("bad"), "bad"), (ValueError("v"), "ValueError: v"),
                  (RecursionError("deep"), "RecursionError: deep"), (SystemExit(3), "exit requested (3)")]
        if HAS_EG:
            raises.append((ExceptionGroup("g", [ValueError()]), "ExceptionGroup: g (1 sub-exception)"))
        for exc, why in raises:
            with self.subTest(exc=type(exc).__name__):
                del self.seen[:]
                self.all_pass()

                def boom(args, exc=exc):
                    raise exc
                self.fake("claims", boom)
                self.expect(["--root", root],
                            ok_lines("schema", "register", "decisions") + "FAIL claims.input: %s\n" % why
                            + ok_lines("cites"), 1, ["schema", "register", "decisions", "cites"])

    def test_gate_keyboardinterrupt_propagates(self):  # G7
        root = self.fixture()

        class Odd(BaseException):
            pass
        for exc in (KeyboardInterrupt(), Odd("o")):
            with self.subTest(exc=type(exc).__name__):
                self.all_pass()

                def boom(args, exc=exc):
                    raise exc
                self.fake("decisions", boom)
                with self.assertRaises(type(exc)):
                    run_all.check(["--root", root])
                with self.assertRaises(type(exc)):
                    self.run_main(["--root", root])

    def test_empty_result_fails(self):  # G8
        self.all_pass()
        self.fake("claims", lambda args: Result("claims", []))
        root = self.fixture()
        self.expect(["--root", root],
                    ok_lines("schema", "register", "decisions") + "FAIL claims.empty: the gate produced no lines\n"
                    + ok_lines("cites"), 1, ["schema", "register", "decisions", "cites"])

    def test_non_result_fails(self):  # G9
        root = self.fixture()
        cases = [(None, "the check returned NoneType, not a Result"), (0, "the check returned int, not a Result"),
                 ({}, "the check returned dict, not a Result"),
                 (Result("schema", [Line("PASS", "x")]), "the check returned a Result for gate schema, not claims"),
                 (Result("claims", [Line("OK", "x")]), "line 1 of the Result has status OK, not PASS or FAIL")]
        for value, why in cases:
            with self.subTest(why=why):
                del self.seen[:]
                self.all_pass()
                self.fake("claims", lambda args, value=value: value)
                self.expect(["--root", root],
                            ok_lines("schema", "register", "decisions") + "FAIL claims.input: %s\n" % why
                            + ok_lines("cites"), 1, ["schema", "register", "decisions", "cites"])

    def test_lines_kept_verbatim_in_order(self):  # G10
        class Bad(str):
            def __str__(self):
                raise RuntimeError("no")

            def __repr__(self):
                raise RuntimeError("no")
        self.all_pass(
            schema=[Line("PASS", "p\\q"), Line("FAIL", "s.nl\nx", "why\ttab\\")],
            register=[Line("PASS", "r.lit\\n"), Line("FAIL", "r.two", "a\nb\\n")],
            decisions=[Line("FAIL", Bad("d.bad"), Bad("rea\\son")), Line("PASS", "d.after")],
            claims=[Line("PASS", 7), Line("FAIL", 9, 5)],
            cites=[Line("PASS", "cites.a"), Line("PASS", "cites.b"), Line("FAIL", "cites.c", "z")])
        root = self.fixture()
        want = (r"PASS p\\q" + "\n" + r"FAIL s.nl\nx: why\ttab\\" + "\n"
                + r"PASS r.lit\\n" + "\n" + r"FAIL r.two: a\nb\\n" + "\n"
                + r"FAIL d.bad: rea\\son" + "\n" + "PASS d.after\n"
                + "PASS 7\nFAIL 9: 5\n"
                + "PASS cites.a\nPASS cites.b\nFAIL cites.c: z\n")
        self.expect(["--root", root], want, 1, list(FIVE))

    def test_each_gate_gets_fresh_args(self):  # G11
        root = self.fixture()
        for mutator in ("schema", "register", "decisions", "claims"):
            with self.subTest(mutator=mutator):
                del self.seen[:]
                for g in FIVE:
                    self.fake(g, self.recorder(g, mutate=(g == mutator)))
                self.run_main(["--root", root, "--base", "x"])
                got = dict(self.seen)
                for g in FIVE:
                    want = ["--root", root] + (["--base", "x"] if g in BASE_ONES else [])
                    self.assertEqual(got[g], want, g)


class BaseTest(RunAllCase):
    def test_base_forwarded_only_to_base_gates(self):  # B1
        self.all_pass()
        root = self.fixture()
        self.run_main(["--root", root, "--base", "x"])
        got = self.args_of()
        for g in BASE_ONES:
            self.assertEqual(got[g], ["--root", root, "--base", "x"], g)
        self.assertEqual(got["schema"], ["--root", root])
        self.assertEqual(got["cites"], ["--root", root])

    def test_no_base_not_forwarded(self):  # B2
        self.all_pass()
        root = self.fixture()
        self.run_main(["--root", root])
        self.assertEqual(self.args_of(), {g: ["--root", root] for g in FIVE})

    def test_base_forwarded_exactly(self):  # B3
        self.all_pass()
        root = self.fixture()
        for argv, value in ((["--base", ""], ""), (["--base", " x "], " x "), (["--base=-x"], "-x"),
                            (["--base", "main~1"], "main~1"), (["--base", "\U0001f6dd"], "\U0001f6dd")):
            with self.subTest(value=value):
                del self.seen[:]
                self.run_main(["--root", root] + argv)
                got = self.args_of()
                for g in BASE_ONES:
                    self.assertEqual(got[g], ["--root", root, "--base", value], g)
                    self.assertIs(type(got[g][3]), str)
                self.assertEqual(got["schema"], ["--root", root])
                self.assertEqual(got["cites"], ["--root", root])

    def test_absent_base_ref_real_gates(self):  # B4
        root = self.fixture()
        want = ""
        for g in FIVE:
            alone, _ = self.sub(["--root", root] + (["--base", "nosuchref"] if g in BASE_ONES else []),
                                command=("check", g))
            want += alone
        out, code = self.run_main(["--root", root, "--base", "nosuchref"])
        self.assertEqual(out.splitlines(), want.splitlines())
        self.assertEqual(code, 1)
        for g in BASE_ONES:
            self.assertIn("FAIL %s.input: git merge-base failed (exit 128)\n" % g, out)
        self.assertEqual([ln for ln in out.splitlines() if ln.startswith("FAIL")],
                         ["FAIL %s.input: git merge-base failed (exit 128)" % g for g in BASE_ONES])

    def test_base_repeated_refused(self):  # B5
        self.all_pass()
        root = self.fixture()
        self.expect(["--root", root, "--base", "a", "--base", "b"],
                    input_fail("invalid arguments: --base given more than once"), 1, [])
        self.expect(["--root", root, "--base=a", "--base", "b"],
                    input_fail("invalid arguments: --base given more than once"), 1, [])


class ArgvTest(RunAllCase):
    def test_json_first(self):  # A1
        self.all_pass(claims=[Line("FAIL", "claims.x", "a\\b\nc")])
        root = self.fixture()
        for argv in (["--json", "--root", root], ["--json", "--root", root, "--base", "HEAD"]):
            with self.subTest(argv=argv):
                del self.seen[:]
                out, code = self.run_main(argv)
                lines = [{"status": "PASS", "id": g + ".ok", "reason": ""} for g in ("schema", "register", "decisions")]
                lines.append({"status": "FAIL", "id": "claims.x", "reason": "a\\b\nc"})
                lines.append({"status": "PASS", "id": "cites.ok", "reason": ""})
                self.assertEqual(json.loads(out), {"gate": "run_all", "ok": False, "lines": lines})
                self.assertTrue(out.endswith("}\n"))
                self.assertEqual(out.count("\n"), 1)
                self.assertEqual(code, 1)
                self.assertEqual(self.called(), list(FIVE))

    def test_json_first_text_literal(self):  # A1, byte form
        self.all_pass()
        root = self.fixture("light")
        out, code = self.run_main(["--json", "--root", root])
        self.assertEqual(out, '{"gate": "run_all", "ok": true, "lines": [{"status": "PASS", "id": "schema.ok", '
                              '"reason": ""}, {"status": "PASS", "id": "register.ok", "reason": ""}, '
                              '{"status": "PASS", "id": "decisions.ok", "reason": ""}]}\n')
        self.assertEqual(code, 0)

    def test_json_later_refused(self):  # A2
        self.all_pass()
        root = self.fixture()
        for argv in (["--base", "HEAD", "--json"], ["--root", root, "--json"]):
            with self.subTest(argv=argv):
                self.expect(argv if "--root" in argv else ["--root", root] + argv,
                            input_fail("invalid arguments: unrecognized arguments: --json"), 1, [])

    def test_root_default(self):  # A3
        self.all_pass()
        root = self.fixture()
        with mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": root}):
            self.expect([], PASS5, 0, list(FIVE))
        self.assertEqual(self.args_of(), {g: ["--root", root] for g in FIVE})
        del self.seen[:]
        cwd = os.getcwd()
        self.addCleanup(os.chdir, cwd)
        os.chdir(root)
        for env in (None, ""):
            with self.subTest(env=env):
                del self.seen[:]
                os.environ.pop("CLAUDE_PROJECT_DIR", None)
                with mock.patch.dict(os.environ, {} if env is None else {"CLAUDE_PROJECT_DIR": env}):
                    self.expect([], PASS5, 0, list(FIVE))
                self.assertEqual(self.args_of(), {g: ["--root", root] for g in FIVE})
        del self.seen[:]
        with mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": os.path.join(root, "nodir")}):
            self.expect([], input_fail("CLAUDE_PROJECT_DIR is not a directory"), 1, [])

    def test_root_repeated_refused(self):  # A4
        self.all_pass()
        for argv in (["--root", "a", "--root", "b"], ["--root=a", "--root", "b"]):
            with self.subTest(argv=argv):
                self.expect(argv, input_fail("invalid arguments: --root given more than once"), 1, [])

    def test_root_forms(self):  # A5
        self.all_pass()
        top = make_repo(self.work)
        forms = root_forms(self.tmp, top)
        nested = [p for n, p, v in forms if n == "nested"][0]
        write_record(nested, CONFIG, minimal_config())
        for name, path, verdict in forms:
            with self.subTest(form=name):
                del self.seen[:]
                out, code = self.run_main(["--root", path])
                if verdict == "ok":
                    self.assertEqual(out, PASS5)
                    self.assertEqual(code, 0)
                    self.assertEqual(self.args_of(), {g: ["--root", path] for g in FIVE})
                else:
                    self.assertEqual(out, input_fail(verdict))
                    self.assertEqual(code, 1)
                    self.assertEqual(self.seen, [])
                    self.assertNotIn(path, out)

    def test_empty_root_is_given_not_default(self):  # A5 sibling: "" is a value, not "missing"
        self.all_pass()
        root = self.fixture()
        with mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": root}):
            self.expect(["--root", ""], input_fail(TOP), 1, [])

    def test_root_without_value_refused(self):  # A6
        self.all_pass()
        self.expect(["--root"], input_fail("invalid arguments: argument --root: expected one argument"), 1, [])

    def test_unknown_flag_refused(self):  # A7
        self.all_pass()
        root = self.fixture()
        for extra in ("--nope", "-x", "foo"):
            with self.subTest(extra=extra):
                self.expect(["--root", root, extra],
                            input_fail("invalid arguments: unrecognized arguments: %s" % extra), 1, [])

    def test_help_runs_nothing(self):  # A8
        self.all_pass()
        for flag in ("--help", "-h"):
            with self.subTest(flag=flag):
                self.expect([flag], input_fail("help requested; no gate was run"), 1, [])

    def test_command_registered(self):  # A9
        self.assertNotIn("run_all", gates_main.GATES)
        self.assertIn("run_all", gates_main.COMMANDS)
        with mock.patch.object(run_all, "main", return_value=42) as m:
            self.assertEqual(gates_main.COMMANDS["run_all"](["--x", "y"]), 42)
            m.assert_called_once_with(["--x", "y"])
            self.assertEqual(gates_main.main(["run_all", "--z"]), 42)
        self.all_pass()
        root = self.fixture()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(gates_main.main(["run_all", "--root", root]), 0)
        self.assertEqual(out.getvalue(), PASS5)

    def test_module_run_end_to_end(self):  # A9
        root = self.fixture()
        for argv in (["--root", root, "--base", "HEAD"], ["--root", root, "--base", "nosuchref"],
                     ["--json", "--root", root], ["--root", root, "--json"], ["--help"], []):
            with self.subTest(argv=argv):
                with mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": root}):
                    want = self.run_main(argv)
                    got = self.sub(argv)
                self.assertEqual(got, want)
        out, code = self.sub(["--root", root, "--base", "HEAD"])
        self.assertEqual(code, 0)
        self.assertEqual(len(out.splitlines()), 31)


class ConfigTest(RunAllCase):
    def test_missing_config_is_input_fail(self):  # C1
        self.all_pass()
        d = os.path.join(self.tmp, "noconf")
        os.mkdir(d)
        git(d, "init", "-q", "-b", "main")
        commit_all(d, "empty")
        out, code = self.run_main(["--root", d])
        self.assertEqual(out, input_fail(".strict-delivery/config.yml: missing; run /strict-delivery:init"))
        self.assertTrue(out.startswith("FAIL run_all.input:"))
        self.assertIn("/strict-delivery:init", out)
        self.assertEqual(out.count("\n"), 1)
        self.assertEqual((code, self.seen), (1, []))

    def test_yaml_error_is_input_fail(self):  # C2
        self.all_pass()
        head = 'schema: config/1\nframework_version: "0"\nprofile: strict\n'
        cases = [('schema: "config/1\nframework_version: "0\nprofile: strict\n',
                  "unterminated quoted scalar (line 1)"),
                 (head + "commands:\n\tx: 1\n", "tab in indentation (line 5)"),
                 ("schema: config/1\nschema: config/1\nframework_version: \"0\"\nprofile: strict\n",
                  "duplicate key 'schema' (line 2)")]
        for text, why in cases:
            with self.subTest(why=why):
                root = self.fixture()
                with open(os.path.join(root, CONFIG), "w", encoding="utf-8") as fh:
                    fh.write(text)
                self.expect(["--root", root], input_fail(".strict-delivery/config.yml: " + why), 1, [])

    def test_invalid_config_is_input_fail(self):  # C3
        self.all_pass()
        cases = [(dict(minimal_config(), bogus=1), ".strict-delivery/config.yml: unknown key 'bogus'"),
                 ({"schema": "config/1", "framework_version": "0"},
                  ".strict-delivery/config.yml: profile: required key is missing")]
        for cfg, why in cases:
            with self.subTest(why=why):
                root = self.fixture(config=cfg)
                self.expect(["--root", root], input_fail(why), 1, [])


class OutputTest(RunAllCase):
    def test_all_pass_exit_0(self):  # O1
        self.all_pass(schema=[Line("PASS", "s.a"), Line("PASS", "s.b")], cites=[Line("PASS", "c.a")])
        root = self.fixture()
        self.expect(["--root", root], "PASS s.a\nPASS s.b\nPASS register.ok\nPASS decisions.ok\n"
                                      "PASS claims.ok\nPASS c.a\n", 0, list(FIVE))

    def test_any_fail_exit_1_no_short_circuit(self):  # O2
        root = self.fixture()
        for bad in ("schema", "decisions", "cites"):
            with self.subTest(bad=bad):
                del self.seen[:]
                self.all_pass(**{bad: [Line("FAIL", bad + ".bad", "nope")]})
                want = "".join(("FAIL %s.bad: nope\n" % g) if g == bad else "PASS %s.ok\n" % g for g in FIVE)
                self.expect(["--root", root], want, 1, list(FIVE))

    def test_version_line(self):  # O3  (Q-B2plan-24 (a): no version line in block 2)
        self.all_pass()
        root = self.fixture()
        out, code = self.run_main(["--root", root])
        self.assertNotIn("run_all.version", out)
        self.assertNotIn("run_all.", out)
        out, code = self.run_main(["--root", root, "--base", "HEAD"])
        self.assertNotIn("run_all.version", out)

    def test_real_gates_pass_on_fixture_repo(self):  # O4
        root = self.fixture()
        out, code = self.run_main(["--root", root, "--base", "HEAD"])
        want = ("PASS schema.kinds\nPASS schema.config\nPASS schema.decision\nPASS schema.finding\n"
                "PASS schema.overview\nPASS schema.in-force\nPASS schema.decision-index\n"
                "PASS schema.finding-index\n"
                "PASS register.schema\nPASS register.store\nPASS register.base\nPASS register.transition\n"
                "PASS register.evidence\nPASS register.epic\nPASS register.report\n"
                "PASS decisions.schema\nPASS decisions.store\nPASS decisions.base\nPASS decisions.landed\n"
                "PASS decisions.refs\nPASS decisions.open-ref\nPASS decisions.scan\n"
                "PASS claims.schema\nPASS claims.store\nPASS claims.document\nPASS claims.stale\n"
                "PASS claims.base\n"
                "PASS cites.doc\nPASS cites.line\nPASS cites.anchor\nPASS cites.landed\n")
        self.assertEqual(out, want)
        self.assertEqual(code, 0)


class Pc1Test(RunAllCase):
    """PC1 skeleton rows S1-S7 (owner Q-D30C2-1 (A+)); each runs on both interpreters."""

    def test_pc1_long_number_base(self):  # S1
        root = self.fixture()
        schema_ok = ("PASS schema.kinds\nPASS schema.config\nPASS schema.decision\nPASS schema.finding\n"
                     "PASS schema.overview\nPASS schema.in-force\nPASS schema.decision-index\n"
                     "PASS schema.finding-index\n")
        cites_ok = "PASS cites.doc\nPASS cites.line\nPASS cites.anchor\nPASS cites.landed\n"
        why = "ref must not hold more than 40 hex digits in a row"
        want = (schema_ok + "FAIL register.input: %s\nFAIL decisions.input: %s\nFAIL claims.input: %s\n"
                % (why, why, why) + cites_ok)
        for n in (4300, 4301):
            with self.subTest(digits=n):
                self.expect(["--root", root, "--base", "7" * n], want, 1)

    def test_pc1_long_number_root(self):  # S2
        self.all_pass()
        for n in (4300, 4301):
            with self.subTest(digits=n):
                out, code = self.run_main(["--root", "7" * n])
                self.assertEqual(out, input_fail(E128))
                self.assertEqual((code, self.seen), (1, []))

    def test_pc1_long_number_config(self):  # S3
        self.all_pass()
        for n in (4300, 4301):
            for key in ("profile", "framework_version"):
                for quote in ("", '"'):
                    with self.subTest(digits=n, key=key, quoted=bool(quote)):
                        del self.seen[:]
                        root = self.fixture()
                        num = quote + "7" * n + quote
                        fv, prof = ('"0"', num) if key == "profile" else (num, "strict")
                        with open(os.path.join(root, CONFIG), "w", encoding="utf-8") as fh:
                            fh.write("schema: config/1\nframework_version: %s\nprofile: %s\n" % (fv, prof))
                        if not quote:
                            line = 3 if key == "profile" else 2
                            self.expect(["--root", root],
                                        input_fail(".strict-delivery/config.yml: integer too large (line %d)" % line),
                                        1, [])
                        elif key == "profile":
                            self.expect(["--root", root], input_fail(
                                ".strict-delivery/config.yml: profile: must be one of light, standard, strict"),
                                1, [])
                        else:
                            # a quoted number is a non-empty string: config.load accepts it (see the report)
                            self.expect(["--root", root], PASS5, 0, list(FIVE))

    def test_pc1_long_number_sub_gate_line(self):  # S4
        root = self.fixture()
        for n in (4300, 4301):
            with self.subTest(digits=n):
                digits = "7" * n
                self.all_pass(claims=[Line("FAIL", "c." + digits, "r" + digits)])
                out, code = self.run_main(["--root", root])
                self.assertEqual(out, ok_lines("schema", "register", "decisions")
                                 + "FAIL c.%s: r%s\n" % (digits, digits) + ok_lines("cites"))
                self.assertEqual(code, 1)

    def test_pc1_long_number_int_id_kept_as_the_gate_alone_renders_it(self):  # S4, int id
        from gates.lib import result
        root = self.fixture()
        big = 10 ** 4300
        for n in (big, big * 10):
            with self.subTest(digits=len(str(n)) if sys.version_info < (3, 11) else "limit"):
                line = Line("PASS", n)
                self.all_pass(claims=[line])
                out, code = self.run_main(["--root", root])
                alone = result.run_check("claims", lambda a: Result("claims", [line]), []).render(False)
                self.assertEqual(out, ok_lines("schema", "register", "decisions") + alone + ok_lines("cites"))
                self.assertEqual(code, 0)

    def test_pc1_unicode_version(self):  # S5
        ch = "\U0001f6dd"
        cat = {"13.0.0": "Cn", "15.1.0": "So"}
        self.assertIn(unicodedata.unidata_version, cat)
        self.assertEqual(unicodedata.category(ch), cat[unicodedata.unidata_version])
        esc = "\\U0001f6dd"
        self.all_pass(schema=[Line("FAIL", "schema." + ch, "r" + ch)])
        self.fake("decisions", lambda args: Result("decisions", [Line("FAIL", "decisions.echo", args[-1])]))
        root = os.path.join(self.tmp, "root" + ch)
        os.mkdir(root)
        make_repo(root, minimal_config())
        out, code = self.run_main(["--root", root, "--base", ch])
        self.assertEqual(out, "FAIL schema.%s: r%s\nPASS register.ok\nFAIL decisions.echo: %s\nPASS claims.ok\n"
                              "PASS cites.ok\n" % (esc, esc, esc))
        self.assertEqual(code, 1)
        out, code = self.run_main(["--root", root])
        self.assertEqual(out, "FAIL schema.%s: r%s\nPASS register.ok\nFAIL decisions.echo: %s\nPASS claims.ok\n"
                              "PASS cites.ok\n" % (esc, esc, root.replace(ch, esc)))
        out, code = self.run_main(["--json", "--root", root, "--base", ch])
        got = json.loads(out)["lines"]
        self.assertEqual((got[0]["id"], got[0]["reason"]), ("schema." + ch, "r" + ch))
        self.assertEqual(got[2]["reason"], ch)

    @unittest.skipUnless(hasattr(builtins, "BaseExceptionGroup"), "BaseExceptionGroup present: False (Python < 3.11)")
    def test_pc1_base_exception_group_propagates(self):  # S6
        self.all_pass()

        def boom(args):
            raise BaseExceptionGroup("g", [KeyboardInterrupt()])
        self.fake("claims", boom)
        root = self.fixture()
        with self.assertRaises(BaseExceptionGroup):
            run_all.check(["--root", root])
        with self.assertRaises(BaseExceptionGroup):
            self.run_main(["--root", root])

    @unittest.skipUnless(HAS_EG, "ExceptionGroup present: False (Python < 3.11)")
    def test_pc1_exception_group_is_input(self):  # S7
        self.all_pass()

        def boom(args):
            raise ExceptionGroup("g", [ValueError()])
        self.fake("claims", boom)
        root = self.fixture()
        self.expect(["--root", root],
                    ok_lines("schema", "register", "decisions")
                    + "FAIL claims.input: ExceptionGroup: g (1 sub-exception)\n" + ok_lines("cites"), 1,
                    ["schema", "register", "decisions", "cites"])


if __name__ == "__main__":
    unittest.main()
