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
import shutil
import subprocess
import sys
import types
import unicodedata
import unittest
from unittest import mock

from gates import __main__ as gates_main
from gates import run_all
from gates.lib import plugin
from gates.lib.result import GateError, Line, Result
from tests.test_plugin_manifest import NOT_FINITE, NOT_FINITE_BODIES, V2_ROWS
from tests.helpers import (E128, TOP, GitIsolatedTestCase, check_root_forms, commit_all, git, make_repo,
                           minimal_config, root_forms, write_record)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SIX = ("schema", "register", "decisions", "claims", "cites", "evidence")   # the gates of standard and strict
BASE_ONES = ("register", "decisions", "claims", "evidence")
CONFIG = ".strict-delivery/config.yml"
UNSET = object()
HAS_EG = hasattr(builtins, "ExceptionGroup")
PASS6 = "".join("PASS %s.ok\n" % g for g in SIX)
VERSION_PASS = "PASS run_all.version\n"   # Task 3d.1: the last line; config framework_version "0.0.0" = the plugin's
# the 32 lines the five real gates give on a valid strict fixture repository, written by hand (as in O4)
REAL_PASS = ("PASS schema.kinds\nPASS schema.config\nPASS schema.decision\nPASS schema.finding\nPASS schema.claim\n"
             "PASS schema.request\nPASS schema.streams\nPASS schema.context\nPASS schema.status\nPASS schema.sync-log\nPASS schema.merged-log\nPASS schema.breakdown\n"
             "PASS schema.overview\nPASS schema.in-force\nPASS schema.decision-index\nPASS schema.finding-index\nPASS schema.mutation-transcript\nPASS schema.review-report\n"
             "PASS register.schema\nPASS register.store\nPASS register.base\nPASS register.transition\n"
             "PASS register.evidence\nPASS register.epic\nPASS register.report\n"
             "PASS decisions.schema\nPASS decisions.store\nPASS decisions.base\nPASS decisions.landed\n"
             "PASS decisions.refs\nPASS decisions.open-ref\nPASS decisions.scan\n"
             "PASS claims.schema\nPASS claims.store\nPASS claims.document\nPASS claims.stale\nPASS claims.base\n"
             "PASS cites.doc\nPASS cites.line\nPASS cites.anchor\nPASS cites.landed\n"
             "PASS evidence.config\nPASS evidence.scope\n")
# B6: the values of the class "starts with a dash (or is a control)"; the last two are the table's controls
DASH_VALUES = ("-r", "-x", "-h", "--root", "--base", "--json", "--x=y", "-", "--", "-1", "^x")


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
        for g in SIX:
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
            fh.write(body.replace("@SUFFIX@", name[len("tests_"):]))   # a name that ends the module's own name
        importlib.invalidate_caches()
        self.addCleanup(lambda: sys.modules.pop(name, None))
        return name

    # ---- running
    def run_main(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = run_all.main(argv)
        return out.getvalue(), code

    def sub(self, argv, command=("run_all",), cwd=REPO, env=None):
        full = dict(os.environ, PYTHONPATH=REPO)
        full.update(env or {})
        p = subprocess.run([sys.executable, "-m", "gates"] + list(command) + list(argv), cwd=cwd,
                           env=full, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return p.stdout.decode("utf-8"), p.returncode

    def expect(self, argv, text, code, called=None):
        """``text`` is the gates' lines; the version line (Task 3d.1) follows them, except after a ``run_all.input``
        failure, which has no version line (plan Task 3d.1, missing config)."""
        out, got = self.run_main(argv)
        self.assertEqual(out, text if text.startswith("FAIL run_all.input:") else text + VERSION_PASS)
        self.assertEqual(got, code)
        if called is not None:
            self.assertEqual(self.called(), called)


class ConstantsTest(unittest.TestCase):
    def test_profile_gates_literal(self):  # K1
        want = {"light": ("schema", "register", "decisions"),
                "standard": ("schema", "register", "decisions", "claims", "cites", "evidence"),
                "strict": ("schema", "register", "decisions", "claims", "cites", "evidence")}
        self.assertIs(type(run_all.PROFILE_GATES), dict)
        self.assertEqual(run_all.PROFILE_GATES, want)
        self.assertEqual(set(run_all.PROFILE_GATES), {"light", "standard", "strict"})
        for k, v in run_all.PROFILE_GATES.items():
            self.assertIs(type(v), tuple, k)

    def test_base_gates_literal(self):  # K2
        self.assertIs(type(run_all.BASE_GATES), tuple)
        self.assertEqual(run_all.BASE_GATES, ("decisions", "register", "claims", "evidence"))

    def test_profile_gates_registered(self):  # K3
        names = {g for v in run_all.PROFILE_GATES.values() for g in v}
        self.assertEqual(names, set(SIX))
        for g in names:
            self.assertIn(g, gates_main.GATES)

    def test_excluded_gates_absent(self):  # K4
        names = {g for v in run_all.PROFILE_GATES.values() for g in v}
        for g in ("dispatch", "streams", "context", "drift", "checkpoint", "cleanup", "index", "run_all"):   # Rq-6-3: evidence joined
            self.assertNotIn(g, names)
        self.assertNotIn("run_all", gates_main.GATES)


class LazyEvidenceTest(unittest.TestCase):
    def loaded(self, body):
        src = "import sys\n" + body + "sys.stdout.write('LOADED=%s' % ('gates.gate_evidence' in sys.modules))\n"
        p = subprocess.run([sys.executable, "-c", src], cwd=REPO, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return p.stdout.decode()

    def test_gate_evidence_imported_lazily(self):  # R3 (Rq-6-1)
        self.assertTrue(self.loaded("import gates.__main__\n").endswith("LOADED=False"))
        self.assertTrue(self.loaded("import gates.run_all\n").endswith("LOADED=False"))
        self.assertTrue(self.loaded("from gates import __main__ as m\nm.main(['check', 'evidence', '--bogus'])\n")
                        .endswith("LOADED=True"))


class EvidenceProfileTest(RunAllCase):
    """Task R2.3, Rq-6-3: ``evidence`` joins standard, strict and BASE_GATES, never light (literals written by hand)."""

    def test_evidence_in_standard_strict_and_base(self):  # T1, T2
        self.assertEqual(run_all.PROFILE_GATES["light"], ("schema", "register", "decisions"))
        for profile in ("standard", "strict"):
            self.assertEqual(run_all.PROFILE_GATES[profile],
                             ("schema", "register", "decisions", "claims", "cites", "evidence"))
        self.assertEqual(run_all.BASE_GATES, ("decisions", "register", "claims", "evidence"))

    def test_light_profile_does_not_call_evidence(self):  # T3
        self.all_pass()
        root = self.fixture("light")
        self.expect(["--root", root], ok_lines("schema", "register", "decisions"), 0, ["schema", "register", "decisions"])
        self.assertNotIn("evidence", self.called())

    def test_standard_and_strict_call_evidence_last(self):  # T1 through the production path
        self.all_pass()
        for profile in ("standard", "strict"):
            with self.subTest(profile=profile):
                del self.seen[:]
                root = self.fixture(profile)
                self.expect(["--root", root], PASS6, 0, ["schema", "register", "decisions", "claims", "cites", "evidence"])

    def test_evidence_lines_on_a_real_fixture(self):  # R1 through run_all, real gates
        root = self.fixture("strict")
        out, code = self.run_main(["--root", root])
        self.assertEqual(code, 0)
        self.assertIn("PASS evidence.config\nPASS evidence.scope\n", out)
        light = self.fixture("light")
        out, code = self.run_main(["--root", light])
        self.assertNotIn("evidence.", out)


class ProfileTest(RunAllCase):
    def test_light_runs_profile_gates_in_order(self):  # P1
        self.all_pass()
        root = self.fixture("light")
        self.expect(["--root", root], ok_lines("schema", "register", "decisions"), 0,
                    ["schema", "register", "decisions"])

    def test_standard_runs_profile_gates_in_order(self):  # P2
        self.all_pass()
        root = self.fixture("standard")
        self.expect(["--root", root], PASS6, 0, list(SIX))

    def test_strict_runs_profile_gates_in_order(self):  # P3
        self.all_pass()
        root = self.fixture("strict")
        self.expect(["--root", root], PASS6, 0, list(SIX))

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
                    + ok_lines("cites", "evidence"), 1, ["schema", "register", "decisions", "cites", "evidence"])

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
                            + "FAIL run_all.missing.claims: %s\n" % reason + ok_lines("cites", "evidence"), 1,
                            ["schema", "register", "decisions", "cites", "evidence"])

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

    def test_import_odd_baseexception_propagates(self):  # F-1: import, a BaseException subclass of the module's own
        root = self.fixture()
        self.all_pass()
        name = self.file_module("class Odd(BaseException):\n    pass\nraise Odd()\n")
        self.put(gates_main.GATES, "claims", name)
        for call in (lambda: run_all.check(["--root", root]), lambda: self.run_main(["--root", root])):
            with self.assertRaises(BaseException) as cm:
                call()
            self.assertEqual(type(cm.exception).__name__, "Odd")

    def test_check_read_systemexit_is_missing(self):  # F-1 (round 2): SystemExit while reading module.check
        root = self.fixture()
        for exc in (SystemExit(3), SystemExit()):
            with self.subTest(args=exc.args):
                del self.seen[:]
                self.all_pass()

                def getattr_(name, exc=exc):
                    raise exc
                mod = self.fake("claims", __getattr__=getattr_)
                self.expect(["--root", root],
                            ok_lines("schema", "register", "decisions")
                            + "FAIL run_all.missing.claims: reading %s.check raised SystemExit\n" % mod.__name__
                            + ok_lines("cites", "evidence"), 1, ["schema", "register", "decisions", "cites", "evidence"])

    def test_check_read_baseexception_propagates(self):  # F-1: reading module.check
        root = self.fixture()

        class Odd(BaseException):
            pass
        for exc in (KeyboardInterrupt(), GeneratorExit(), Odd("o")):
            with self.subTest(exc=type(exc).__name__):
                self.all_pass()

                def getattr_(name, exc=exc):
                    raise exc
                self.fake("claims", __getattr__=getattr_)
                with self.assertRaises(type(exc)):
                    run_all.check(["--root", root])
                with self.assertRaises(type(exc)):
                    self.run_main(["--root", root])

    def test_module_not_found_name_other_than_the_gate_is_import_failure(self):  # F-2
        root = self.fixture()
        for label, modname, dep in (("parent package absent", "nopkg_xx_f2.gate_x", None),
                                    ("parent inside gates absent", "gates.nopkg_xx_f2.gate_x", None),
                                    ("prefix-named dependency", None, "tests_fakefile_dep_prefix"),
                                    ("suffix-named dependency", None, "@SUFFIX@")):
            with self.subTest(label):
                del self.seen[:]
                self.all_pass()
                if modname is None:
                    modname = self.file_module("import %s\n" % dep)
                self.put(gates_main.GATES, "claims", modname)
                self.expect(["--root", root],
                            ok_lines("schema", "register", "decisions")
                            + "FAIL run_all.missing.claims: import of %s raised ModuleNotFoundError\n" % modname
                            + ok_lines("cites", "evidence"), 1, ["schema", "register", "decisions", "cites", "evidence"])

    def test_module_not_found_without_a_module_name_is_import_failure(self):  # F-5: e.name None or not a module
        root = self.fixture()
        for label, body in (("name None", "raise ModuleNotFoundError('boom')\n"),
                            ("name empty", "raise ModuleNotFoundError('boom', name='')\n"),
                            ("name other", "raise ModuleNotFoundError('boom', name='some.other')\n")):
            with self.subTest(label):
                del self.seen[:]
                self.all_pass()
                modname = self.file_module(body)
                self.put(gates_main.GATES, "claims", modname)
                self.expect(["--root", root],
                            ok_lines("schema", "register", "decisions")
                            + "FAIL run_all.missing.claims: import of %s raised ModuleNotFoundError\n" % modname
                            + ok_lines("cites", "evidence"), 1, ["schema", "register", "decisions", "cites", "evidence"])

    def package_module(self, body, init=""):
        """A module ``<package>.gate_x`` as files on the scratch import path; its dotted name is returned."""
        self.file_module("")   # makes the scratch import directory
        pkg = "tests_fakepkg_%d" % next(self._n)
        os.mkdir(os.path.join(self._modir, pkg))
        with open(os.path.join(self._modir, pkg, "__init__.py"), "w", encoding="utf-8") as fh:
            fh.write(init)
        with open(os.path.join(self._modir, pkg, "gate_x.py"), "w", encoding="utf-8") as fh:
            fh.write(body)
        importlib.invalidate_caches()
        self.addCleanup(lambda: [sys.modules.pop(k, None) for k in (pkg, pkg + ".gate_x")])
        return pkg + ".gate_x"

    def test_self_named_module_not_found_in_existing_module(self):  # G2b
        root = self.fixture()
        own = "raise ModuleNotFoundError('own body', name=__name__)\n"
        halted = self.file_module("x = 1\n")
        halted_pkg = self.package_module("x = 1\n")
        cases = [   # (label, module name, what to do first, expected reason)
            ("(i) file absent", "tests_absent_gate_xx", None, "tests_absent_gate_xx.py missing"),
            ("(i) file absent, dotted", "gates.gate_nosuch_yy", None, "gates/gate_nosuch_yy.py missing"),
            ("(ii) own body raises, naming itself", self.file_module(own), "raise", "raised"),
            ("(ii) own body raises, dotted", self.package_module(own), "raise", "raised"),
            ("(iv) sys.modules None, file absent", "tests_none_gate_xx", "none", "tests_none_gate_xx.py missing"),
            ("(iv) sys.modules None, file present", halted, "none", "%s.py missing" % halted),
            ("(iv) sys.modules None, dotted file present", halted_pkg, "none",
             "%s.py missing" % halted_pkg.replace(".", "/")),
        ]
        for label, name, how, why in cases:
            with self.subTest(label):
                del self.seen[:]
                self.all_pass()
                if how == "none":
                    self.put(sys.modules, name, None)
                reason = "import of %s raised ModuleNotFoundError" % name if why == "raised" else why
                self.put(gates_main.GATES, "claims", name)
                self.expect(["--root", root],
                            ok_lines("schema", "register", "decisions")
                            + "FAIL run_all.missing.claims: %s\n" % reason + ok_lines("cites", "evidence"), 1,
                            ["schema", "register", "decisions", "cites", "evidence"])

    def spec_finder(self, name, second):
        """A meta_path finder: the first lookup of ``name`` raises ``ModuleNotFoundError(name=name)``; the second
        (``importlib.util.find_spec``'s) calls ``second()`` (which raises)."""
        calls = []

        class Finder:
            def find_spec(self, fullname, path=None, target=None):
                if fullname == name:
                    calls.append(1)
                    if len(calls) > 1:
                        second()
                    raise ModuleNotFoundError("finder", name=name)
                return None
        finder = Finder()
        sys.meta_path.insert(0, finder)
        self.addCleanup(sys.meta_path.remove, finder)
        return name

    def find_spec_triggers(self):
        """G2b (v): module names whose self-named ModuleNotFoundError is followed by an Exception from
        ``importlib.util.find_spec``. Returns ``(label, name, before)`` where ``before`` runs just before the run."""
        triggers = []
        parent = self.file_module("x = 1\n")
        triggers.append(("parent is a module, not a package", parent + ".x", lambda: None))
        none_parent = self.package_module(
            "import sys\nsys.modules[__name__.rpartition('.')[0]] = None\n"
            "raise ModuleNotFoundError('x', name=__name__)\n")
        triggers.append(("parent is None in sys.modules", none_parent, lambda: None))
        broken = self.package_module(
            "import os, sys\ndel sys.modules[__name__.rpartition('.')[0]]\n"
            "os.environ['TESTS_BROKEN_PARENT'] = '1'\nraise ModuleNotFoundError('x', name=__name__)\n",
            init="import os\nif os.environ.get('TESTS_BROKEN_PARENT'):\n    raise ValueError('broken parent')\n")
        triggers.append(("parent's re-import raises", broken, lambda: None))
        spec_none = "tests_specnone_%d" % next(self._n)

        class SpecNoneFinder:
            def find_spec(self, fullname, path=None, target=None):
                if fullname == spec_none:
                    mod = types.ModuleType(spec_none)
                    mod.__spec__ = None
                    sys.modules[spec_none] = mod
                    raise ModuleNotFoundError("finder", name=spec_none)
                return None
        finder = SpecNoneFinder()
        sys.meta_path.insert(0, finder)
        self.addCleanup(sys.meta_path.remove, finder)
        self.addCleanup(sys.modules.pop, spec_none, None)
        triggers.append(("sys.modules[name].__spec__ is None", spec_none, lambda: None))

        def second():
            raise RuntimeError("second lookup")
        raising = self.spec_finder("tests_finderraises_%d" % next(self._n), second)
        triggers.append(("a meta_path finder raises on the lookup", raising, lambda: None))
        return triggers

    def test_find_spec_raising_is_import_failure(self):  # G2b (v), CR-2
        root = self.fixture()
        for label, name, before in self.find_spec_triggers():
            with self.subTest(label):
                del self.seen[:]
                self.all_pass()
                self.put(gates_main.GATES, "claims", name)
                before()
                self.expect(["--root", root],
                            ok_lines("schema", "register", "decisions")
                            + "FAIL run_all.missing.claims: import of %s raised ModuleNotFoundError\n" % name
                            + ok_lines("cites", "evidence"), 1, ["schema", "register", "decisions", "cites", "evidence"])
                os.environ.pop("TESTS_BROKEN_PARENT", None)

    def test_find_spec_systemexit_is_import_failure(self):  # G2b (v), SystemExit as in G2 and G3
        root = self.fixture()
        for label, args in (("SystemExit(3)", (3,)), ("SystemExit()", ())):
            with self.subTest(label):
                del self.seen[:]
                self.all_pass()

                def second(args=args):
                    raise SystemExit(*args)
                name = self.spec_finder("tests_finderexit_%d" % next(self._n), second)
                self.put(gates_main.GATES, "claims", name)
                self.expect(["--root", root],
                            ok_lines("schema", "register", "decisions")
                            + "FAIL run_all.missing.claims: import of %s raised ModuleNotFoundError\n" % name
                            + ok_lines("cites", "evidence"), 1, ["schema", "register", "decisions", "cites", "evidence"])

    def assert_find_spec_baseexception_propagates(self, members):
        """G2b (v) x G12: a non-Exception BaseException raised inside ``find_spec`` propagates out of both entry
        points; stdout and stderr stay empty although the gates before it passed."""
        root = self.fixture()
        argv = ["--root", root]
        entries = (("run_all.main", lambda: run_all.main(argv)),
                   ("gates main", lambda: gates_main.main(["run_all"] + argv)))
        for exc_name, factory in members:
            for entry, call in entries:
                with self.subTest(exc=exc_name, entry=entry):
                    del self.seen[:]
                    self.all_pass()

                    def second(factory=factory):
                        raise factory()
                    name = self.spec_finder("tests_findernoexc_%d" % next(self._n), second)
                    self.put(gates_main.GATES, "claims", name)
                    out, err = io.StringIO(), io.StringIO()
                    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                        with self.assertRaises(BaseException) as cm:
                            call()
                    self.assertEqual(type(cm.exception).__name__, exc_name)
                    self.assertEqual((out.getvalue(), err.getvalue()), ("", ""))
                    self.assertEqual(self.called(), ["schema", "register", "decisions"])

    def test_find_spec_baseexception_propagates(self):  # G2b (v), G12
        class Odd(BaseException):
            pass
        self.assert_find_spec_baseexception_propagates([
            ("KeyboardInterrupt", KeyboardInterrupt), ("GeneratorExit", GeneratorExit), ("Odd", Odd)])

    @unittest.skipUnless(hasattr(builtins, "BaseExceptionGroup"), "BaseExceptionGroup present: False (Python < 3.11)")
    def test_find_spec_base_exception_group_propagates(self):  # G2b (v), G12
        self.assert_find_spec_baseexception_propagates([
            ("BaseExceptionGroup", lambda: BaseExceptionGroup("g", [KeyboardInterrupt()]))])

    def test_no_check_is_missing(self):  # G4
        self.all_pass()
        mod = self.fake("claims")
        root = self.fixture()
        self.expect(["--root", root],
                    ok_lines("schema", "register", "decisions")
                    + "FAIL run_all.missing.claims: %s has no check\n" % mod.__name__ + ok_lines("cites", "evidence"), 1,
                    ["schema", "register", "decisions", "cites", "evidence"])

    def test_check_attribute_read_raising_is_missing(self):  # G4 sibling: reading check raises
        self.all_pass()

        def getattr_(name):
            raise ValueError("no")
        mod = self.fake("claims", __getattr__=getattr_)
        root = self.fixture()
        self.expect(["--root", root],
                    ok_lines("schema", "register", "decisions")
                    + "FAIL run_all.missing.claims: reading %s.check raised ValueError\n" % mod.__name__
                    + ok_lines("cites", "evidence"), 1, ["schema", "register", "decisions", "cites", "evidence"])

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
                            + ok_lines("cites", "evidence"), 1, ["schema", "register", "decisions", "cites", "evidence"])

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
                            + ok_lines("cites", "evidence"), 1, ["schema", "register", "decisions", "cites", "evidence"])

    def test_gate_keyboardinterrupt_propagates(self):  # G7
        root = self.fixture()

        class Odd(BaseException):
            pass
        for exc in (KeyboardInterrupt(), GeneratorExit(), Odd("o")):
            with self.subTest(exc=type(exc).__name__):
                self.all_pass()

                def boom(args, exc=exc):
                    raise exc
                self.fake("decisions", boom)
                with self.assertRaises(type(exc)):
                    run_all.check(["--root", root])
                with self.assertRaises(type(exc)):
                    self.run_main(["--root", root])

    def assert_propagates_without_output(self, members):
        """G12: for each ``(name, factory, import_body)`` and each site (raised at import, raised reading ``check``,
        raised by ``check``) and each entry point, the exception propagates and stdout is exactly empty, although
        the gates before the raising one have passed."""
        root = self.fixture()
        argv = ["--root", root]
        entries = (("run_all.main", lambda: run_all.main(argv)),
                   ("gates main", lambda: gates_main.main(["run_all"] + argv)))
        for name, factory, import_body in members:
            for site in ("import", "read", "call"):
                for entry, call in entries:
                    with self.subTest(exc=name, site=site, entry=entry):
                        del self.seen[:]
                        self.all_pass()
                        if site == "import":
                            self.put(gates_main.GATES, "claims", self.file_module(import_body))
                        elif site == "read":
                            def getattr_(attr):
                                raise factory()
                            self.fake("claims", __getattr__=getattr_)
                        else:
                            def boom(args):
                                raise factory()
                            self.fake("claims", boom)
                        out, err = io.StringIO(), io.StringIO()
                        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                            with self.assertRaises(BaseException) as cm:
                                call()
                        self.assertEqual(type(cm.exception).__name__, name)
                        self.assertEqual(out.getvalue(), "")
                        self.assertEqual(err.getvalue(), "")   # G12 (2026-11-15): stderr as well as stdout
                        self.assertEqual(self.called(), ["schema", "register", "decisions"])

    def test_propagation_leaves_no_partial_output(self):  # G12
        class Odd(BaseException):
            pass
        self.assert_propagates_without_output([
            ("KeyboardInterrupt", KeyboardInterrupt, "raise KeyboardInterrupt()\n"),
            ("GeneratorExit", GeneratorExit, "raise GeneratorExit()\n"),
            ("Odd", Odd, "class Odd(BaseException):\n    pass\nraise Odd()\n")])

    @unittest.skipUnless(hasattr(builtins, "BaseExceptionGroup"), "BaseExceptionGroup present: False (Python < 3.11)")
    def test_propagation_leaves_no_partial_output_base_exception_group(self):  # G12
        self.assert_propagates_without_output([
            ("BaseExceptionGroup", lambda: BaseExceptionGroup("g", [KeyboardInterrupt()]),
             "raise BaseExceptionGroup('g', [KeyboardInterrupt()])\n")])

    def test_empty_result_fails(self):  # G8
        self.all_pass()
        self.fake("claims", lambda args: Result("claims", []))
        root = self.fixture()
        self.expect(["--root", root],
                    ok_lines("schema", "register", "decisions") + "FAIL claims.empty: the gate produced no lines\n"
                    + ok_lines("cites", "evidence"), 1, ["schema", "register", "decisions", "cites", "evidence"])

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
                            + ok_lines("cites", "evidence"), 1, ["schema", "register", "decisions", "cites", "evidence"])

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
                + "PASS cites.a\nPASS cites.b\nFAIL cites.c: z\nPASS evidence.ok\n")
        self.expect(["--root", root], want, 1, list(SIX))

    def test_each_gate_gets_fresh_args(self):  # G11
        root = self.fixture()
        for mutator in ("schema", "register", "decisions", "claims", "evidence"):
            with self.subTest(mutator=mutator):
                del self.seen[:]
                for g in SIX:
                    self.fake(g, self.recorder(g, mutate=(g == mutator)))
                self.run_main(["--root", root, "--base", "x"])
                got = dict(self.seen)
                for g in SIX:
                    want = ["--root=" + root] + (["--base=x"] if g in BASE_ONES else [])
                    self.assertEqual(got[g], want, g)


class BaseTest(RunAllCase):
    def test_base_forwarded_only_to_base_gates(self):  # B1
        self.all_pass()
        root = self.fixture()
        self.run_main(["--root", root, "--base", "x"])
        got = self.args_of()
        for g in BASE_ONES:
            self.assertEqual(got[g], ["--root=" + root, "--base=x"], g)
        self.assertEqual(got["schema"], ["--root=" + root])
        self.assertEqual(got["cites"], ["--root=" + root])

    def test_no_base_not_forwarded(self):  # B2
        self.all_pass()
        root = self.fixture()
        self.run_main(["--root", root])
        self.assertEqual(self.args_of(), {g: ["--root=" + root] for g in SIX})

    def test_base_forwarded_exactly(self):  # B3
        self.all_pass()
        root = self.fixture()
        for argv, value in ((["--base", ""], ""), (["--base", " x "], " x "), (["--base=-x"], "-x"),
                            (["--base", "main~1"], "main~1"), (["--base", "\U0001f6dd"], "\U0001f6dd"),
                            (["--base", "a=b"], "a=b"), (["--base=a=b"], "a=b")):
            with self.subTest(value=value):
                del self.seen[:]
                self.run_main(["--root", root] + argv)
                got = self.args_of()
                for g in BASE_ONES:
                    self.assertEqual(got[g], ["--root=" + root, "--base=" + value], g)
                    self.assertIs(type(got[g][1]), str)
                self.assertEqual(got["schema"], ["--root=" + root])
                self.assertEqual(got["cites"], ["--root=" + root])

    def test_absent_base_ref_real_gates(self):  # B4
        root = self.fixture()
        want = ""
        for g in SIX:
            alone, _ = self.sub(["--root", root] + (["--base", "nosuchref"] if g in BASE_ONES else []),
                                command=("check", g))
            want += alone
        out, code = self.run_main(["--root", root, "--base", "nosuchref"])
        self.assertEqual(out.splitlines(), want.splitlines() + ["PASS run_all.version"])
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

    def chdir_to_parent_with_repo_named(self, value):
        """A valid strict fixture repository whose directory is named ``value``, in a fresh parent; the cwd becomes
        the parent (restored after the test). Returns the parent."""
        parent = os.path.join(self.tmp, "parent%d" % next(self._dirs))
        os.mkdir(parent)
        repo = os.path.join(parent, value)
        os.mkdir(repo)
        make_repo(repo, dict(minimal_config(), profile="strict"))
        cwd = os.getcwd()
        self.addCleanup(os.chdir, cwd)
        os.chdir(parent)
        return parent

    def alone_in_process(self, gate, argv, env=None):
        """``python3 -m gates check <gate> <argv>`` through ``gates.__main__.main`` (the same entry, no new process)."""
        buf = io.StringIO()
        with mock.patch.dict(os.environ, env or {}), contextlib.redirect_stdout(buf):
            rc = gates_main.main(["check", gate] + list(argv))
        return buf.getvalue(), rc

    def test_gate_args_double_dash_is_text(self):  # B6, member `--`: stored as the text `--` on every interpreter
        from gates.lib import result
        self.assertEqual(result.gate_args("probe").parse_args(["--root=--"]).root, "--")

    def test_dash_leading_root_forwarded_as_one_token(self):  # B6, --root
        for value in DASH_VALUES:
            with self.subTest(value=value):
                parent = self.chdir_to_parent_with_repo_named(value)
                for how in ("given", "env"):
                    with self.subTest(how=how):
                        if how == "given":
                            argv, env = ["--root=" + value], {}
                        else:
                            argv, env = [], {"CLAUDE_PROJECT_DIR": value}
                        with mock.patch.dict(os.environ, env):
                            out, code = self.run_main(argv)
                        alone = ""
                        for g in SIX:
                            text, rc = self.alone_in_process(g, argv, env)
                            self.assertEqual(rc, 0, g)
                            alone += text
                        self.assertEqual(alone, REAL_PASS)
                        # one real `python3 -m gates check` process, the path the sub-gate's argv really takes
                        text, rc = self.sub(argv, command=("check", "schema"), cwd=parent, env=env)
                        self.assertEqual((text, rc), (alone.split("PASS register.")[0], 0))
                        self.assertEqual(out, alone + VERSION_PASS)
                        self.assertEqual(code, 0)
                        self.assertNotIn("expected one argument", out)

    def test_dash_leading_base_forwarded_as_one_token(self):  # B6, --base
        root = self.fixture()
        schema = "".join(ln + "\n" for ln in REAL_PASS.splitlines() if ln.startswith("PASS schema."))
        cites = "".join(ln + "\n" for ln in REAL_PASS.splitlines() if ln.startswith("PASS cites."))
        for value in DASH_VALUES:
            with self.subTest(value=value):
                why = "ref must not start with '%s'" % ("^" if value.startswith("^") else "-")   # spec 13, spec:648
                want = (schema + "".join("FAIL %s.input: %s\n" % (g, why) for g in ("register", "decisions", "claims"))
                        + cites + "FAIL evidence.input: %s\n" % why)
                out, code = self.run_main(["--root", root, "--base=" + value])
                self.assertEqual(out, want + VERSION_PASS)
                self.assertEqual(code, 1)
                self.assertNotIn("expected one argument", out)
                alone = ""
                for g in SIX:
                    text, rc = self.alone_in_process(
                        g, ["--root", root] + (["--base=" + value] if g in BASE_ONES else []))
                    alone += text
                self.assertEqual(out, alone + VERSION_PASS)
                text, rc = self.sub(["--root", root, "--base=" + value], command=("check", "decisions"))
                self.assertEqual((text, rc), ("FAIL decisions.input: %s\n" % why, 1))



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
                lines.append({"status": "PASS", "id": "evidence.ok", "reason": ""})
                lines.append({"status": "PASS", "id": "run_all.version", "reason": ""})
                self.assertEqual(json.loads(out), {"gate": "run_all", "ok": False, "lines": lines})
                self.assertTrue(out.endswith("}\n"))
                self.assertEqual(out.count("\n"), 1)
                self.assertEqual(code, 1)
                self.assertEqual(self.called(), list(SIX))

    def test_json_first_text_literal(self):  # A1, byte form
        self.all_pass()
        root = self.fixture("light")
        out, code = self.run_main(["--json", "--root", root])
        self.assertEqual(out, '{"gate": "run_all", "ok": true, "lines": [{"status": "PASS", "id": "schema.ok", '
                              '"reason": ""}, {"status": "PASS", "id": "register.ok", "reason": ""}, '
                              '{"status": "PASS", "id": "decisions.ok", "reason": ""}, '
                              '{"status": "PASS", "id": "run_all.version", "reason": ""}]}\n')
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
            self.expect([], PASS6, 0, list(SIX))
        self.assertEqual(self.args_of(), {g: ["--root=" + root] for g in SIX})
        del self.seen[:]
        cwd = os.getcwd()
        self.addCleanup(os.chdir, cwd)
        os.chdir(root)
        for env in (None, ""):
            with self.subTest(env=env):
                del self.seen[:]
                os.environ.pop("CLAUDE_PROJECT_DIR", None)
                with mock.patch.dict(os.environ, {} if env is None else {"CLAUDE_PROJECT_DIR": env}):
                    self.expect([], PASS6, 0, list(SIX))
                self.assertEqual(self.args_of(), {g: ["--root=" + root] for g in SIX})
        del self.seen[:]
        with mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": os.path.join(root, "nodir")}):
            self.expect([], input_fail("CLAUDE_PROJECT_DIR is not a directory"), 1, [])

    def test_default_root_forwarded_as_repo_root_gives_it(self):  # F-3: never normalised by run_all
        from gates.lib import result
        self.all_pass()
        root = self.fixture()
        link = os.path.join(self.tmp, "link")
        os.symlink(root, link)
        cwd = os.getcwd()
        self.addCleanup(os.chdir, cwd)
        os.chdir(os.path.dirname(root))
        for label, env, _ in (("real", root, True), ("symlink", link, True), ("trailing slash", root + "/", True),
                               ("symlink trailing slash", link + "/", True),
                               ("relative", os.path.basename(root), True)):
            with self.subTest(label):
                del self.seen[:]
                with mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": env}):
                    self.assertEqual(result.repo_root(), env)
                    out, code = self.run_main([])
                self.assertEqual((out, code), (PASS6 + VERSION_PASS, 0))
                self.assertEqual(self.args_of(), {g: ["--root=" + env] for g in SIX})
        del self.seen[:]
        os.chdir(root)
        with mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": "."}):
            self.expect([], PASS6, 0, list(SIX))
            self.assertEqual(self.args_of(), {g: ["--root=."] for g in SIX})
        del self.seen[:]
        with mock.patch.dict(os.environ, {}):
            os.environ.pop("CLAUDE_PROJECT_DIR", None)
            self.expect([], PASS6, 0, list(SIX))
            self.assertEqual(self.args_of(), {g: ["--root=" + result.repo_root()] for g in SIX})

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
                    self.assertEqual(out, PASS6 + VERSION_PASS)
                    self.assertEqual(code, 0)
                    self.assertEqual(self.args_of(), {g: ["--root=" + path] for g in SIX})
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
        self.assertEqual(out.getvalue(), PASS6 + VERSION_PASS)

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
        self.assertEqual(len(out.splitlines()), 44)   # the 43 real-gate lines (six more kinds, P2.2; the context kind, Rq-5-2; the two evidence kinds, Rq-6-2; the two evidence lines, Rq-6-3) and the version line


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
        tag = minimal_config()["schema"]
        head = 'schema: %s\nframework_version: "0"\nprofile: strict\n' % tag
        cases = [('schema: "%s\nframework_version: "0\nprofile: strict\n' % tag,
                  "unterminated quoted scalar (line 1)"),
                 (head + "commands:\n\tx: 1\n", "tab in indentation (line 5)"),
                 ("schema: %s\nschema: %s\nframework_version: \"0\"\nprofile: strict\n" % (tag, tag),
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
                 ({k: v for k, v in minimal_config().items() if k != "profile"},
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
                                      "PASS claims.ok\nPASS c.a\nPASS evidence.ok\n", 0, list(SIX))

    def test_any_fail_exit_1_no_short_circuit(self):  # O2
        root = self.fixture()
        for bad in ("schema", "decisions", "cites"):
            with self.subTest(bad=bad):
                del self.seen[:]
                self.all_pass(**{bad: [Line("FAIL", bad + ".bad", "nope")]})
                want = "".join(("FAIL %s.bad: nope\n" % g) if g == bad else "PASS %s.ok\n" % g for g in SIX)
                self.expect(["--root", root], want, 1, list(SIX))

    def test_real_gates_pass_on_fixture_repo(self):  # O4
        root = self.fixture()
        out, code = self.run_main(["--root", root, "--base", "HEAD"])
        want = ("PASS schema.kinds\nPASS schema.config\nPASS schema.decision\nPASS schema.finding\nPASS schema.claim\n"
                "PASS schema.request\nPASS schema.streams\nPASS schema.context\nPASS schema.status\nPASS schema.sync-log\n"
                "PASS schema.merged-log\nPASS schema.breakdown\n"
                "PASS schema.overview\nPASS schema.in-force\nPASS schema.decision-index\n"
                "PASS schema.finding-index\nPASS schema.mutation-transcript\nPASS schema.review-report\n"
                "PASS register.schema\nPASS register.store\nPASS register.base\nPASS register.transition\n"
                "PASS register.evidence\nPASS register.epic\nPASS register.report\n"
                "PASS decisions.schema\nPASS decisions.store\nPASS decisions.base\nPASS decisions.landed\n"
                "PASS decisions.refs\nPASS decisions.open-ref\nPASS decisions.scan\n"
                "PASS claims.schema\nPASS claims.store\nPASS claims.document\nPASS claims.stale\n"
                "PASS claims.base\n"
                "PASS cites.doc\nPASS cites.line\nPASS cites.anchor\nPASS cites.landed\n"
             "PASS evidence.config\nPASS evidence.scope\n")
        self.assertEqual(out, want + VERSION_PASS)
        self.assertEqual(code, 0)


class VersionLineTest(RunAllCase):
    """Task 3d.1 rows A1-A8 and the version rows of S: ``run_all.version`` is the last line, compares the target's
    ``framework_version`` with the installed plugin's version, and fails closed on a bad manifest."""
    MISMATCH = ("FAIL run_all.version: framework_version 0.1.0 does not match the plugin version 0.0.0; "
                "run /strict-delivery:upgrade\n")
    PM = ".claude-plugin/plugin.json"

    def plugin_dir(self, body, name="fw"):
        """A framework directory whose plugin.json is ``body`` (bytes, or an object dumped as JSON; None: no file);
        ``plugin.framework_dir`` is patched to it for the rest of the test."""
        d = os.path.join(self.tmp, name + str(next(self._dirs)))
        os.makedirs(os.path.join(d, ".claude-plugin"))
        if body is not None:
            data = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
            with open(os.path.join(d, ".claude-plugin", "plugin.json"), "wb") as fh:
                fh.write(data)
        patcher = mock.patch.object(plugin, "framework_dir", return_value=d)
        patcher.start()
        self.addCleanup(patcher.stop)
        return d

    def test_version_line_passes_when_equal(self):  # A1; Q-B2plan-24 (a)
        self.all_pass()
        for profile, gates in (("light", ("schema", "register", "decisions")), ("standard", SIX), ("strict", SIX)):
            with self.subTest(profile=profile):
                root = self.fixture(profile)
                out, code = self.run_main(["--root", root])
                self.assertEqual(out, ok_lines(*gates) + "PASS run_all.version\n")
                self.assertEqual(code, 0)
                self.assertEqual(out.splitlines()[-1], "PASS run_all.version")
                out, code = self.run_main(["--root", root, "--base", "HEAD"])
                self.assertEqual((out, code), (ok_lines(*gates) + "PASS run_all.version\n", 0))

    def test_version_line_last_after_a_failed_or_missing_gate(self):  # A2
        root = self.fixture()
        self.all_pass(schema=[Line("FAIL", "schema.bad", "nope")])
        self.put(gates_main.GATES, "claims", UNSET)
        out, code = self.run_main(["--root", root])
        self.assertEqual(out, "FAIL schema.bad: nope\nPASS register.ok\nPASS decisions.ok\n"
                              "FAIL run_all.missing.claims: not registered in gates.__main__.GATES\n"
                              "PASS cites.ok\nPASS evidence.ok\nPASS run_all.version\n")
        self.assertEqual(code, 1)

    def test_version_mismatch_names_upgrade(self):  # A3
        self.all_pass()
        root = self.fixture(config=dict(minimal_config(), framework_version="0.1.0"))
        out, code = self.run_main(["--root", root])
        self.assertEqual(out, PASS6 + self.MISMATCH)
        self.assertEqual(code, 1)
        self.assertIn("/strict-delivery:upgrade", out)

    def test_version_mismatch_is_exact_string_comparison(self):  # A3 siblings
        self.all_pass()
        for fv in ("0.0.1", "1.0.0", "0.0", "v0.0.0", "0.0.0 ", "00.0.0", "a\nb"):
            with self.subTest(framework_version=fv):
                root = self.fixture(config=dict(minimal_config(), framework_version=fv))
                out, code = self.run_main(["--root", root])
                shown = fv.replace("\n", "\\n")
                self.assertEqual(out, PASS6 + "FAIL run_all.version: framework_version %s does not match the plugin "
                                              "version 0.0.0; run /strict-delivery:upgrade\n" % shown)
                self.assertEqual(code, 1)

    def test_bad_manifest_fails_closed(self):  # A4: each M and V row, through a patched framework_dir
        self.all_pass()
        root = self.fixture()
        pm = self.PM
        good = {"name": "strict-delivery", "version": "0.0.0"}
        rows = [
            ("M1 absent", None, "cannot be read (FileNotFoundError)"),
            ("M2 not utf-8", b'{"version": "\xff"}', "is not valid UTF-8"),
            ("M2 bom", b"\xef\xbb\xbf" + json.dumps(good).encode(), "is not valid JSON"),
            ("M2 empty", b"", "is not valid JSON"),
            ("M3 invalid", b'{"version": ', "is not valid JSON"),
            ("M3 list", b'["0.0.0"]', "the top level must be an object"),
            ("M3 string", b'"0.0.0"', "the top level must be an object"),
            ("M3 null", b"null", "the top level must be an object"),
            ("M3 number", b"0", "the top level must be an object"),
            ("M3 duplicate", b'{"version": "0.0.0", "version": "0.0.0"}', "duplicate key 'version'"),
            ("M3 nested duplicate", b'{"version": "0.0.0", "x": {"a": 1, "a": 2}}', "duplicate key 'a'"),
            ("M4 NaN", b'{"version": "0.0.0", "x": NaN}', "the constant NaN is not allowed"),
            ("M4 Infinity", b'{"version": "0.0.0", "x": Infinity}', "the constant Infinity is not allowed"),
            ("M4 -Infinity", b'{"version": "0.0.0", "x": -Infinity}', "the constant -Infinity is not allowed"),
            ("M5 nesting", b"[" * 100000, "nesting is too deep"),
            ("S1 long int", b'{"version": "0.0.0", "x": ' + b"1" * 4301 + b"}",
             "an integer of more than 4300 digits is not allowed"),
            ("V1 absent", b'{"name": "x"}', "version is missing"),
            ("V1 empty", b'{"version": ""}', "version  is not of the form X.Y.Z"),
            ("V1 int", b'{"version": 0}', "version must be a string, got 0"),
            ("V1 true", b'{"version": true}', "version must be a string, got True"),
            ("V1 null", b'{"version": null}', "version must be a string, got None"),
            ("V1 list", b'{"version": ["0.0.0"]}', "version must be a string, got [0.0.0]"),
            ("S2 unicode 14", b'{"version": "0.0.0\\ud83e\\udee0"}',
             "version 0.0.0\\U0001fae0 is not of the form X.Y.Z"),
        ]
        # F-3d1-R1-2: every V2 row of the plugin tests (one list), the M4 non-finite bodies (decision P4)
        for v in V2_ROWS:
            shown = v.replace("\\", "\\\\").replace("\n", "\\n").replace("\x00", "\\x00")   # as safe_text renders it
            rows.append(("V2 %r" % v, json.dumps({"version": v}).encode("ascii"),
                         "version %s is not of the form X.Y.Z" % shown))
        for body in NOT_FINITE_BODIES:
            rows.append(("M4 %r" % body, body, NOT_FINITE))
        for label, body, why in rows:
            with self.subTest(label):
                self.plugin_dir(body)
                out, code = self.run_main(["--root", root])
                self.assertEqual(out, PASS6 + "FAIL run_all.version: %s: %s\n" % (pm, why))
                self.assertEqual(code, 1)
        with self.subTest("M1 .claude-plugin absent"):
            d = os.path.join(self.tmp, "fwnodir")
            os.mkdir(d)
            with mock.patch.object(plugin, "framework_dir", return_value=d):
                self.assertEqual(self.run_main(["--root", root]),
                                 (PASS6 + "FAIL run_all.version: %s: cannot be read (FileNotFoundError)\n" % pm, 1))
        with self.subTest("M1 directory at the path"):
            d = self.plugin_dir(None)
            os.mkdir(os.path.join(d, ".claude-plugin", "plugin.json"))
            self.assertEqual(self.run_main(["--root", root]),
                             (PASS6 + "FAIL run_all.version: %s: is not a regular file\n" % pm, 1))

    def test_bad_manifest_as_subprocess_has_no_traceback(self):  # A4
        root = self.fixture()
        copy = os.path.join(self.tmp, "copy")
        shutil.copytree(os.path.join(REPO, "gates"), os.path.join(copy, "gates"),
                        ignore=shutil.ignore_patterns("__pycache__"))
        os.makedirs(os.path.join(copy, ".claude-plugin"))
        with open(os.path.join(copy, ".claude-plugin", "plugin.json"), "wb") as fh:
            fh.write(b"[" * 100000)
        env = dict(os.environ, PYTHONPATH="", PYTHONDONTWRITEBYTECODE="1")
        p = subprocess.run([sys.executable, "-m", "gates", "run_all", "--root", root], cwd=copy, env=env,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual(p.stderr, b"")
        self.assertEqual(p.returncode, 1)
        self.assertEqual(p.stdout.decode().splitlines()[-1],
                         "FAIL run_all.version: .claude-plugin/plugin.json: nesting is too deep")

    def test_root_is_another_tree_than_the_plugin(self):  # A5
        self.all_pass()
        self.plugin_dir({"version": "0.1.0"})
        equal = self.fixture(config=dict(minimal_config(), framework_version="0.1.0"))
        self.assertEqual(self.run_main(["--root", equal]), (PASS6 + VERSION_PASS, 0))
        other = self.fixture()   # framework_version 0.0.0 against the installed 0.1.0
        want = ("FAIL run_all.version: framework_version 0.0.0 does not match the plugin version 0.1.0; "
                "run /strict-delivery:upgrade\n")
        self.assertEqual(self.run_main(["--root", other]), (PASS6 + want, 1))
        self.assertNotEqual(os.path.realpath(plugin.framework_dir()), os.path.realpath(other))

    def test_missing_config_has_no_version_line(self):  # A6
        self.all_pass()
        d = os.path.join(self.tmp, "noconf2")
        os.mkdir(d)
        git(d, "init", "-q", "-b", "main")
        commit_all(d, "empty")
        out, code = self.run_main(["--root", d])
        self.assertEqual(out, input_fail(".strict-delivery/config.yml: missing; run /strict-delivery:init"))
        self.assertNotIn("run_all.version", out)
        self.assertEqual((code, self.seen), (1, []))
        self.plugin_dir(b"not json")      # a bad manifest does not add a line either
        out, code = self.run_main(["--root", d])
        self.assertEqual(out, input_fail(".strict-delivery/config.yml: missing; run /strict-delivery:init"))

    def test_json_output_ends_with_the_version_line(self):  # A7
        self.all_pass()
        root = self.fixture()
        out, code = self.run_main(["--json", "--root", root])
        doc = json.loads(out)
        self.assertEqual(code, 0)
        self.assertTrue(doc["ok"])
        self.assertEqual(doc["lines"][-1], {"status": "PASS", "id": "run_all.version", "reason": ""})
        self.assertEqual(len(doc["lines"]), 7)   # Rq-6-3: the evidence line
        bad = self.fixture(config=dict(minimal_config(), framework_version="0.1.0"))
        out, code = self.run_main(["--json", "--root", bad])
        doc = json.loads(out)
        self.assertEqual(code, 1)
        self.assertFalse(doc["ok"])
        self.assertEqual(doc["lines"][-1], {
            "status": "FAIL", "id": "run_all.version",
            "reason": "framework_version 0.1.0 does not match the plugin version 0.0.0; run /strict-delivery:upgrade"})

    def test_real_repo_passes_with_the_version_line_last(self):  # A8
        # only the version line is pinned: the other gates' verdicts on the real tree depend on its git state (a copy
        # with no local main, as test_self_adoption runs the suite, fails a base gate), not on this task
        out, code = self.sub([])
        self.assertEqual(out.splitlines()[-1], "PASS run_all.version")
        self.assertNotIn("run_all.version:", out)
        # F-1: the exit code agrees with the lines (not asserted to be 0: see the comment above)
        self.assertEqual(code, 1 if any(ln.startswith("FAIL ") for ln in out.splitlines()) else 0)

    def test_r4_r5_repository_rows_through_run_all(self):  # R4, R5: run_all reads the version only, never repository
        self.all_pass()
        root = self.fixture()
        for repo in ("https://github.com/o/..", "https://github.com/-o/n", "https://github.com/o-/n",
                     "https://github.com/o/n", "not a url"):
            with self.subTest(repository=repo):
                self.plugin_dir({"version": "0.0.0", "repository": repo})
                self.assertEqual(self.run_main(["--root", root]), (PASS6 + VERSION_PASS, 0))
                for fn in (plugin.repository_url, plugin.repository_slug):
                    if repo in ("https://github.com/o/n",):
                        self.assertIn("o", fn(plugin.framework_dir()))
                    else:
                        with self.assertRaises(GateError):
                            fn(plugin.framework_dir())

    def test_version_line_when_a_non_exception_baseexception_is_raised_by_the_plugin(self):  # S3
        class Odd(BaseException):
            pass
        self.all_pass()
        root = self.fixture()
        with mock.patch.object(plugin, "framework_dir", side_effect=Odd()):
            with self.assertRaises(Odd):
                self.run_main(["--root", root])

    def test_gate_error_text_goes_through_safe_text(self):  # rendering, never a raw control character
        self.all_pass()
        root = self.fixture()
        self.plugin_dir(b'{"version": "0.0.0\\u0007\\\\"}')
        out, code = self.run_main(["--root", root])
        self.assertEqual(out, PASS6 + "FAIL run_all.version: .claude-plugin/plugin.json: version 0.0.0\\x07\\\\ is "
                                      "not of the form X.Y.Z\n")


class Pc1Test(RunAllCase):
    """PC1 skeleton rows S1-S7 (owner Q-D30C2-1 (A+)); each runs on both interpreters."""

    def test_pc1_long_number_base(self):  # S1
        root = self.fixture()
        schema_ok = ("PASS schema.kinds\nPASS schema.config\nPASS schema.decision\nPASS schema.finding\nPASS schema.claim\n"
                     "PASS schema.request\nPASS schema.streams\nPASS schema.context\nPASS schema.status\nPASS schema.sync-log\n"
                     "PASS schema.merged-log\nPASS schema.breakdown\n"
                     "PASS schema.overview\nPASS schema.in-force\nPASS schema.decision-index\n"
                     "PASS schema.finding-index\nPASS schema.mutation-transcript\nPASS schema.review-report\n")
        cites_ok = "PASS cites.doc\nPASS cites.line\nPASS cites.anchor\nPASS cites.landed\n"
        why = "ref must not hold more than 40 hex digits in a row"
        want = (schema_ok + "FAIL register.input: %s\nFAIL decisions.input: %s\nFAIL claims.input: %s\n"
                % (why, why, why) + cites_ok + "FAIL evidence.input: %s\n" % why)   # expect() appends the version line
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
                            fh.write("schema: %s\nframework_version: %s\nprofile: %s\n"
                                     % (minimal_config()["schema"], fv, prof))
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
                            # a quoted number is a non-empty string: config.load accepts it (see the report); it is
                            # not the plugin's version, so the version line is the mismatch
                            out, code = self.run_main(["--root", root])
                            self.assertEqual(out, PASS6 + "FAIL run_all.version: framework_version %s does not match "
                                                  "the plugin version 0.0.0; run /strict-delivery:upgrade\n"
                                                  % ("7" * n))
                            self.assertEqual((code, self.called()), (1, list(SIX)))

    def test_pc1_long_number_sub_gate_line(self):  # S4
        root = self.fixture()
        for n in (4300, 4301):
            with self.subTest(digits=n):
                digits = "7" * n
                self.all_pass(claims=[Line("FAIL", "c." + digits, "r" + digits)])
                out, code = self.run_main(["--root", root])
                self.assertEqual(out, ok_lines("schema", "register", "decisions")
                                 + "FAIL c.%s: r%s\n" % (digits, digits) + ok_lines("cites", "evidence") + VERSION_PASS)
                self.assertEqual(code, 1)

    def test_pc1_long_number_int_id_kept_as_the_gate_alone_renders_it(self):  # S4, int id
        from gates.lib import result
        root = self.fixture()
        for digits in (4300, 4301, 4302):   # F-4: the 3.11+ str() limit is 4300 digits
            with self.subTest(digits=digits):
                line = Line("PASS", 10 ** (digits - 1))   # an int with exactly `digits` digits
                self.all_pass(claims=[line])
                out, code = self.run_main(["--root", root])
                alone = result.run_check("claims", lambda a: Result("claims", [line]), []).render(False)
                self.assertEqual(out, ok_lines("schema", "register", "decisions") + alone + ok_lines("cites", "evidence")
                                 + VERSION_PASS)
                self.assertEqual(code, 0)
                if digits == 4300:   # renderable on both interpreters: the same digits
                    self.assertEqual(alone, "PASS 1" + "0" * 4299 + "\n")

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
                              "PASS cites.ok\nPASS evidence.ok\nPASS run_all.version\n" % (esc, esc, "--base=" + esc))
        self.assertEqual(code, 1)
        out, code = self.run_main(["--root", root])
        self.assertEqual(out, "FAIL schema.%s: r%s\nPASS register.ok\nFAIL decisions.echo: %s\nPASS claims.ok\n"
                              "PASS cites.ok\nPASS evidence.ok\nPASS run_all.version\n" % (esc, esc, "--root=" + root.replace(ch, esc)))
        out, code = self.run_main(["--json", "--root", root, "--base", ch])
        got = json.loads(out)["lines"]
        self.assertEqual((got[0]["id"], got[0]["reason"]), ("schema." + ch, "r" + ch))
        self.assertEqual(got[2]["reason"], "--base=" + ch)

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
                    + "FAIL claims.input: ExceptionGroup: g (1 sub-exception)\n" + ok_lines("cites", "evidence"), 1,
                    ["schema", "register", "decisions", "cites", "evidence"])


class LiveProgramTest(RunAllCase):  # Task P2.3: RA1-RA4, RA9, RA11 (the live program is a branch <p>/integration holding streams.yml)
    NAME = "20261101-x"

    def live(self, root):
        git(root, "checkout", "-q", "-b", self.NAME + "/integration")
        write_record(root, ".strict-delivery/state/programs/%s/streams.yml" % self.NAME, {"schema": "streams/1"})
        commit_all(root, "program")
        git(root, "checkout", "-q", "main")

    def test_live_program_gates_literal(self):  # RA4
        self.assertEqual(run_all.LIVE_PROGRAM_GATES, ("streams",))
        self.assertIs(type(run_all.LIVE_PROGRAM_GATES), tuple)

    def test_streams_not_run_without_program(self):  # RA1
        for profile in ("light", "standard", "strict"):
            self.all_pass()
            self.fake("streams", self.recorder("streams"))
            self.seen.clear()
            run_all.check(["--root", self.fixture(profile)])
            self.assertNotIn("streams", self.called())

    def test_streams_runs_when_program_live_on_light(self):  # RA2, RA3, RA9, RA11
        for profile in ("light", "standard", "strict"):
            self.all_pass()
            self.fake("streams", self.recorder("streams"))
            self.seen.clear()
            root = self.fixture(profile)
            self.live(root)
            res = run_all.check(["--root", root])
            self.assertEqual(self.called()[-1], "streams")
            self.assertEqual(self.called().count("streams"), 1)
            self.assertEqual(self.args_of()["streams"], ["--root=" + root])
            self.assertEqual([l.id for l in res.lines][-2:], ["streams.ok", "run_all.version"])

    def test_streams_runs_on_program_branch_without_integration(self):  # RA5
        self.all_pass()
        self.fake("streams", self.recorder("streams"))
        root = self.fixture("light")
        git(root, "checkout", "-q", "-b", self.NAME + "/a/main")
        run_all.check(["--root", root])
        self.assertIn("streams", self.called())

    def test_live_check_failure_is_a_line_and_profile_gates_run(self):  # RA7, D-Q22 (b)
        self.all_pass()
        root = self.fixture("light")
        with mock.patch.object(run_all.programs, "live_programs", side_effect=GateError("boom")):
            res = run_all.check(["--root", root])
        self.assertEqual([(l.status, l.id) for l in res.lines if l.id.startswith("run_all.streams")],
                         [("FAIL", "run_all.streams")])
        self.assertEqual(self.called(), ["schema", "register", "decisions"])
        self.assertEqual([l.id for l in res.lines if l.id.startswith("streams")], [])     # mutant #89: a failed check is not live

    def test_streams_runs_on_a_malformed_program_branch(self):  # RA5 sibling, mutant #87: a bad shape counts as a program branch
        self.all_pass()
        self.fake("streams", self.recorder("streams"))
        root = self.fixture("light")
        git(root, "checkout", "-q", "-b", self.NAME + "/foo")
        run_all.check(["--root", root])
        self.assertIn("streams", self.called())

    def test_detached_head_with_live_program_is_red(self):  # RA6 (D-Q22 (a)): streams is appended and answers streams.input
        self.all_pass()
        root = self.fixture("light")
        self.live(root)
        git(root, "checkout", "-q", "--detach")
        res = run_all.check(["--root", root])
        self.assertIn(("FAIL", "streams.input"), [(l.status, l.id) for l in res.lines])
        self.assertIn("HEAD is detached; pass --branch NAME", [l.reason for l in res.lines if l.id == "streams.input"])

    def test_base_is_not_passed_to_streams(self):  # RA8 (D-Q6 (a))
        self.all_pass()
        self.fake("streams", self.recorder("streams"))
        root = self.fixture("light")
        self.live(root)
        run_all.check(["--root", root, "--base", "main"])
        self.assertEqual(self.args_of()["streams"], ["--root=" + root])

    def test_streams_module_missing_is_a_line(self):  # RA10
        self.all_pass()
        root = self.fixture("light")
        self.live(root)
        with mock.patch.dict(gates_main.GATES, {"streams": "gates.gate_streams_absent"}):
            res = run_all.check(["--root", root])
        self.assertIn(("FAIL", "run_all.missing.streams", "gates/gate_streams_absent.py missing"),
                      [(l.status, l.id, l.reason) for l in res.lines])

    def test_live_check_is_one_ref_listing_with_many_branches(self):  # RA13
        self.all_pass()
        self.fake("streams", self.recorder("streams"))
        root = self.fixture("light")
        self.live(root)
        subprocess.run(["git", "-C", root, "update-ref", "--stdin"], check=True,
                       input="".join("create refs/heads/b%d HEAD\n" % i for i in range(500)).encode())
        calls = []
        real = subprocess.run

        def spy(argv, *a, **kw):
            calls.append(list(argv))
            return real(argv, *a, **kw)
        with mock.patch.object(run_all.gitinfo.subprocess, "run", spy):
            run_all.check(["--root", root])
        self.assertEqual(len([c for c in calls if "for-each-ref" in c]), 1)
        self.assertIn("streams", self.called())


if __name__ == "__main__":
    unittest.main()
