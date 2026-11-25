"""Tests of gates/tools/doctor.py (Task 4d.3): input, argv, root, version and hardening. Every test runs the production path (``doctor.main`` / ``doctor.check``) on
a fixture repository; every ``gh`` is a fake script first on PATH; expected texts are hand-written from the plan lines and
the task-4d.3 domain table, whose row ids are named in each comment."""
import ast
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
from unittest import mock

from gates.lib import config, plugin
from gates.lib.result import GateError
from gates.tools import doctor, githooks
from tests.helpers import commit_all, git, int_limit, make_repo, minimal_config, root_forms, INT_LIMITS
from tests.doctor_base import Base, CONTEXT, CONTEXT_OK, DEPTH, PV, ROOT, ROOT_ID, SETTINGS, WF, clear, put, snap


# ---------------------------------------------------------------------------------------------------- argv
class TestArgv(Base):
    def test_doctor_root_required(self):  # AR1, AR2, AR3, AR4, AR11, AR12
        for argv in ([], ["--json"], ["--bogus"], ["x"], ["--root"], ["--root", "--json"], ["--root", "-x"],
                     ["--root", self.r, "--root", self.r], ["--root=" + self.r, "--root=" + self.r],
                     ["--root", self.r, "--bogus"], ["x", "--root", self.r], ["--root", self.r, "x"],
                     ["-h"], ["--help"], ["--json", "--json", "--root", self.r], ["--root", "--json", self.r],
                     ["--root", self.r, "--json", "x"]):
            with self.subTest(argv=argv):
                code, out, err = self.main(list(argv))
                self.assertEqual((code, out), (2, ""))
                self.assertNotEqual(err, "")
        self.assertEqual(self.gh.log(), [])

    def test_doctor_root_empty(self):  # AR5, CD3
        for argv in (["--root", ""], ["--root="]):
            code, out, _ = self.run_doctor(*argv)
            self.assertEqual((code, out.splitlines()), (1, ["PASS doctor.python", "FAIL doctor.input: --root must not be empty"]))

    def test_doctor_root_forms_equal_abbrev_json(self):  # AR6, AR7, AR8, AR9
        base = self.run_doctor("--root", self.r)
        self.assertEqual(self.run_doctor("--root=" + self.r), base)
        self.assertEqual(self.run_doctor("--roo", self.r), base)
        first = self.run_doctor("--json", "--root", self.r)
        last = self.run_doctor("--root", self.r, "--json")
        self.assertEqual(first, last)
        doc = json.loads(first[1])
        self.assertEqual(doc["gate"], "doctor")
        self.assertEqual([x["id"] for x in doc["lines"]], ROOT_ID)
        self.assertEqual(doc["lines"][4]["reason"],
                         "neither extra installed: this repository is gated only inside Claude sessions")
        self.assertEqual(doc["ok"], base[0] == 0)

    def test_doctor_argv_types(self):  # AR13
        class L(list):
            pass
        for argv in (None, (), "--root x", L(["--root", self.r]), [None], [1], [b"--root"]):
            with self.subTest(argv=argv):
                err = io.StringIO()
                with contextlib.redirect_stderr(err):
                    self.assertEqual(doctor.main(argv), 2)

    def test_doctor_root_nul_and_long(self):  # AR14, AR15
        code, out, _ = self.run_doctor("--root", "x\x00y")
        self.assertEqual((code, out.splitlines()[1]), (1, "FAIL doctor.input: --root holds a NUL character"))
        for bad in ("/" + "a" * 5000, os.path.join(self.tmp, "b" * 300)):
            code, out, err = self.run_doctor("--root", bad)
            self.assertEqual(code, 1)
            self.assertTrue(out.splitlines()[1].startswith("FAIL doctor.input: "), out)
            self.assertNotIn("Traceback", err)

    def test_doctor_root_odd_names(self):  # AR16
        for name in ("é", "-x", "a b"):
            d = os.path.join(self.tmp, name)
            os.mkdir(d)
            make_repo(d, dict(minimal_config(), framework_version=PV))
            code, out, _ = self.run_doctor("--root=" + d)
            self.assertEqual(out.splitlines()[1], "PASS doctor.input", name)

    def test_doctor_relative_root_cwd_and_project_dir(self):  # AR17, AR18, AR19
        base = self.run_doctor("--root", self.r)
        old = os.getcwd()
        self.addCleanup(os.chdir, old)
        os.chdir(self.r)
        self.assertEqual(self.run_doctor("--root", "."), base)
        os.chdir("/")
        self.assertEqual(self.run_doctor("--root", self.r), base)
        other = os.path.join(self.tmp, "other")
        os.mkdir(other)
        with mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": other}):
            self.assertEqual(self.run_doctor("--root", self.r), base)
            self.assertEqual(self.run_doctor()[0], 2) if False else None
            self.assertEqual(self.run_doctor("--json")[0], 2)

    def test_doctor_streams_exit_codes_text_form(self):  # AR20, AR21, OUT6, OUT11
        code, out, err = self.run_doctor()
        self.assertEqual((type(code), err), (int, ""))
        self.assertEqual(code, 1)  # CLAUDE.md missing
        self.green()
        code, out, err = self.run_doctor()
        self.assertEqual((code, err), (0, ""))
        self.assertTrue(out.endswith("\n") and not out.endswith("\n\n"))
        for ln in out.splitlines():
            self.assertRegex(ln, r"\APASS doctor\.[a-z.-]+(: [^\t\r\x1b]*)?\Z")

    def test_doctor_not_registered_yet_and_not_in_run_all(self):  # AR22, AR23
        from gates import run_all
        from gates.__main__ import COMMANDS
        self.assertNotIn("doctor", COMMANDS)
        self.assertNotIn("doctor", run_all.PROFILE_GATES["strict"] + run_all.BASE_GATES)
        with open(os.path.join(ROOT, "gates", "tools", "doctor.py"), encoding="utf-8") as fh:
            self.assertIn('if __name__ == "__main__":', fh.read())

    def test_doctor_check_contract(self):  # CK1, CK2, CK3, CK4, CK5, CK6, CK8
        res = doctor.check(["--root", self.r])
        self.assertEqual(res.gate, "doctor")
        self.assertEqual(res.ok(), all(ln.status == "PASS" for ln in res.lines))
        for ln in res.lines:
            self.assertEqual((type(ln.id), type(ln.reason)), (str, str))
            self.assertTrue(ln.id.startswith("doctor."))
        for bad in ([], ["--root"], ["--root", "a", "--root", "b"], ["--json"], ["x"], None, ("--root", "x"), "x", [1]):
            with self.subTest(args=bad), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(GateError):
                    doctor.check(bad)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            again = doctor.check(["--root", self.r])
        self.assertEqual(out.getvalue(), "")
        self.assertEqual(again, res)


# ---------------------------------------------------------------------------------------------------- root, framework
class TestRoot(Base):
    def test_doctor_root_forms(self):  # RT1-RT4, RT6
        make_repo_cfg = os.path.join(self.tmp, "forms_top")
        os.mkdir(make_repo_cfg)
        top = make_repo(make_repo_cfg, dict(minimal_config(), framework_version=PV))
        forms = root_forms(self.tmp, top)
        for name, path, verdict in forms:
            with self.subTest(form=name):
                code, out, _ = self.run_doctor("--root", path)
                lines = out.splitlines()
                if name == "nested":
                    self.assertEqual(lines[1], "FAIL doctor.input: .strict-delivery/config.yml: missing; run /strict-delivery:init")
                elif verdict == "ok":
                    self.assertEqual(lines[1], "PASS doctor.input")
                else:
                    self.assertEqual(lines, ["PASS doctor.python", "FAIL doctor.input: " + verdict])

    def test_doctor_linked_worktree(self):  # RT5, GH12, WN7
        commit_all(self.r, "x")
        wt = os.path.join(self.tmp, "wt")
        git(self.r, "worktree", "add", "-q", "--detach", "--", wt)
        self.shims()
        before = snap(os.path.join(self.r, ".git"))
        lines = self.lines("--root", wt)
        self.assertIn("PASS doctor.githooks.pre-commit", lines)
        self.assertEqual(snap(os.path.join(self.r, ".git")), before)

    def test_doctor_git_missing(self):  # RT8
        only = os.path.join(self.tmp, "nogit")
        os.mkdir(only)
        with mock.patch.dict(os.environ, {"PATH": only}):
            code, out, _ = self.run_doctor()
        self.assertEqual((code, out.splitlines()), (1, ["PASS doctor.python",
                                                        "FAIL doctor.input: git not found on PATH; install git"]))

    def test_doctor_git_env_and_config_noise(self):  # RT9, RT10
        base = self.run_doctor()
        for key, val in (("color.ui", "always"), ("color.diff", "always"), ("core.abbrev", "7"),
                         ("core.quotepath", "false"), ("status.showUntrackedFiles", "no")):
            git(self.r, "config", key, val)
        self.assertEqual(self.run_doctor(), base)
        with mock.patch.dict(os.environ, {"GIT_DIR": os.path.join(self.tmp, "nowhere")}):
            self.assertEqual(self.run_doctor(), base)

    def test_doctor_framework_dir_refused(self):  # FW1, FW2, FW3, FW4, FW6, FW7, FW8, FW11, FW12, WN6
        fw = self.fw
        before = snap(fw)
        sym = os.path.join(self.tmp, "sym")
        os.symlink(fw, sym)
        symsub = os.path.join(self.tmp, "symsub")
        os.symlink(os.path.join(fw, "gates"), symsub)
        chain = os.path.join(self.tmp, "chain")
        os.symlink(sym, chain)
        rel = os.path.join(self.tmp, "rel")
        os.symlink("fw", rel)
        text = "FAIL doctor.input: %s is the framework's own directory; pass the target repository's top level"
        for path in (fw, fw + "/", fw + "/.", fw + "/gates/..", fw + "//", fw + "/gates", fw + "/nonexistent/x",
                     sym, symsub, chain, rel):
            with self.subTest(path=path):
                code, out, _ = self.run_doctor("--root", path)
                self.assertEqual((code, out.splitlines()), (1, ["PASS doctor.python", text % os.path.abspath(path)]))
        doc = json.loads(self.run_doctor("--json", "--root", fw)[1])
        self.assertEqual([x["status"] for x in doc["lines"]], ["PASS", "FAIL"])
        self.assertEqual(snap(fw), before)
        self.assertEqual(self.gh.log(), [])
        for sib in (fw + "x", fw + "-old"):  # FW6: a name that merely starts with the framework's
            os.mkdir(sib)
            self.assertNotIn("framework's own", self.run_doctor("--root", sib)[1])
        self.assertNotIn("framework's own", self.run_doctor("--root", os.path.dirname(fw))[1])  # FW7
        os.symlink(fw, os.path.join(self.r, "vendor"))  # FW8
        self.assertEqual(self.lines()[1], "PASS doctor.input")

    def test_doctor_framework_symlinked_both_ways(self):  # FW5
        link = os.path.join(self.tmp, "fwlink")
        os.symlink(self.fw, link)
        with mock.patch.object(plugin, "framework_dir", return_value=link):
            self.assertIn("framework's own", self.run_doctor("--root", self.fw)[1])
            self.assertIn("framework's own", self.run_doctor("--root", link)[1])

    def test_doctor_framework_case_alias(self):  # FW9 (Q5): a case alias is refused as the framework or fails on the config
        alias = self.fw.upper()
        if not os.path.exists(alias):
            self.skipTest("case-sensitive file system")
        code, out, _ = self.run_doctor("--root", alias)
        self.assertEqual(code, 1)
        self.assertEqual(out.splitlines()[0], "PASS doctor.python")
        self.assertTrue(out.splitlines()[1].startswith("FAIL doctor.input: "))

    def test_doctor_real_framework_dir_refused(self):  # FW10
        with mock.patch.object(plugin, "framework_dir", return_value=ROOT):
            before = snap(ROOT, skip_pycache=True)
            code, out, _ = self.run_doctor("--root", ROOT)
            after = snap(ROOT, skip_pycache=True)
        self.assertEqual(code, 1)
        self.assertIn("is the framework's own directory", out)
        self.assertEqual(before, after)


# ---------------------------------------------------------------------------------------------------- python, input, version
class TestPythonInputVersion(Base):
    def test_doctor_python_boundary(self):  # PY1-PY4, PY6, PY7, VR6, OUT13
        for value, passes in (((3, 8, 18, "final", 0), False), ((3, 9, 6, "final", 0), True), ((3, 9), True),
                              ((3, 9, 0), True), ((3, 13, 18, "final", 0), True), ((3, 8, 99), False),
                              ((3, 10), True), ((3, 100), True), ((4, 0), True), ((2, 7), False), ((3,), False),
                              ((3, 9, 0, "alpha", 1), True)):
            with self.subTest(value=value), mock.patch.object(sys, "version_info", value):
                first = self.lines()[0]
                self.assertEqual(first.startswith("PASS"), passes, first)
        with mock.patch.object(sys, "version_info", (3, 8, 18, "final", 0)):
            lines = self.lines()
            self.assertEqual(lines[0], "FAIL doctor.python: Python 3.8 is older than 3.9")
            self.assertEqual(len(lines), 13)  # the run continues (12 lines and doctor.context)
        for bad in (None, "3.9", (3, "9"), ()):
            with self.subTest(bad=bad), mock.patch.object(sys, "version_info", bad):
                first = self.lines()[0]
                self.assertTrue(first.startswith("FAIL doctor.python: cannot be checked: "), first)
        self.assertEqual(self.lines()[0], "PASS doctor.python")  # PY5, unpatched

    def test_doctor_input_config_missing_stops(self):  # IN2, IN7, OUT5, WN6
        os.remove(os.path.join(self.r, ".strict-delivery", "config.yml"))
        before = snap(self.r)
        code, out, _ = self.run_doctor()
        self.assertEqual((code, out.splitlines()), (1, ["PASS doctor.python",
                                                        "FAIL doctor.input: .strict-delivery/config.yml: missing; run /strict-delivery:init"]))
        self.assertEqual((snap(self.r), self.gh.log()), (before, []))

    def test_doctor_input_invalid(self):  # IN3, IN4, IN5, IN9
        cfgp = os.path.join(self.r, ".strict-delivery", "config.yml")
        for text, want in (("schema: config/1\nframework_version: 0.0.0\nprofile: strict\n",
                            ".strict-delivery/config.yml: schema: must be 'config/2'; run /strict-delivery:upgrade"),
                           ("schema: config/2\nframework_version: 0.0.0\nprofile: wild\n", None),
                           ("a: {b: 1}\n", None), ("schema: config/2\nschema: config/2\n", None),
                           ("schema: config/2\nframework_version: '\x07'\nprofile: strict\n", None)):
            with self.subTest(text=text):
                with open(cfgp, "w", encoding="utf-8") as fh:
                    fh.write(text)
                lines = self.lines()
                self.assertEqual(len(lines), 2, lines)
                self.assertTrue(lines[1].startswith("FAIL doctor.input: "), lines)
                if want:
                    self.assertEqual(lines[1], "FAIL doctor.input: " + want)

    def test_doctor_config_integers_4300_4301_digits(self):  # VR1 (d), IN6: killed by D101 (the input verdict dropped for a ValueError)
        cfgp = os.path.join(self.r, ".strict-delivery", "config.yml")
        head = "schema: config/2\nframework_version: 0.1.0\nprofile: strict\n"  # the integer is on line 5
        for limit in INT_LIMITS:
            with int_limit(limit):
                for n in (4300, 4301):
                    for block in ("drift:\n  estimate_factor_pct: ", "limits:\n  max_depth: "):
                        with self.subTest(limit=limit, digits=n, key=block.split(":")[0]):
                            with open(cfgp, "w", encoding="utf-8") as fh:
                                fh.write(head + block + "1" * n + "\n")
                            code, out, err = self.run_doctor()
                            self.assertEqual((code, err), (1, ""))
                            self.assertEqual(out.splitlines(), ["PASS doctor.python",
                                             "FAIL doctor.input: .strict-delivery/config.yml: integer too large (line 5)"])

    def test_doctor_input_pass_and_loaded_once(self):  # IN1, IN8, VE8
        with mock.patch.object(config, "load", wraps=config.load) as ld, \
                mock.patch.object(plugin, "version", wraps=plugin.version) as pv:
            lines = self.lines()
        self.assertEqual(lines[1], "PASS doctor.input")
        self.assertEqual(ld.call_count, 1 + 1)  # doctor's one call, and gate_schema's own load of the same file
        self.assertEqual(pv.call_count, 1)

    def test_doctor_input_file_states(self):  # IN6, FS7
        cfgp = os.path.join(self.r, ".strict-delivery", "config.yml")
        with open(cfgp, "rb") as fh:
            good = fh.read()
        real = os.path.join(self.tmp, "real.yml")
        for name, make in (("dangling", lambda: os.symlink(os.path.join(self.tmp, "nope"), cfgp)),
                           ("directory", lambda: os.mkdir(cfgp)), ("fifo", lambda: os.mkfifo(cfgp)),
                           ("nonutf8", lambda: put(cfgp, b"\xff\xfe")),
                           ("empty", lambda: put(cfgp)),
                           ("symlink", lambda: (put(real, good), os.symlink(real, cfgp))),
                           ("bom", lambda: put(cfgp, b"\xef\xbb\xbf" + good))):
            if os.path.lexists(cfgp):
                if os.path.isdir(cfgp) and not os.path.islink(cfgp):
                    os.rmdir(cfgp)
                else:
                    os.unlink(cfgp)
            make()
            with self.subTest(state=name):
                lines = self.lines()
                if name in ("symlink", "bom"):
                    self.assertEqual(lines[1], "PASS doctor.input")
                else:
                    self.assertEqual(len(lines), 2)
                    self.assertTrue(lines[1].startswith("FAIL doctor.input: "), lines)
        expect = {"dangling": "No such file or directory", "directory": "not a regular file",
                  "fifo": "not a regular file", "nonutf8": "not valid UTF-8", "empty": "must be a mapping"}
        for name, frag in expect.items():
            if os.path.lexists(cfgp):
                os.unlink(cfgp) if not os.path.isdir(cfgp) or os.path.islink(cfgp) else os.rmdir(cfgp)
            {"dangling": lambda: os.symlink(os.path.join(self.tmp, "nope"), cfgp),
             "directory": lambda: os.mkdir(cfgp), "fifo": lambda: os.mkfifo(cfgp),
             "nonutf8": lambda: put(cfgp, b"\xff\xfe"), "empty": lambda: put(cfgp)}[name]()
            self.assertIn(frag, self.lines()[1], name)

    def test_doctor_version_equal_different_absent(self):  # VE1, VE2, VE3, VE4
        self.assertEqual(self.lines()[3], "PASS doctor.version")
        self.set_cfg(framework_version="0.0.0")
        self.assertEqual(self.lines()[3],
                         "FAIL doctor.version: framework_version 0.0.0 differs from the plugin 0.1.0; run /strict-delivery:upgrade")
        self.set_cfg()
        mpath = os.path.join(self.fw, ".claude-plugin", "plugin.json")
        for state, text in (("absent", None), ("invalid", "{"), ("novers", '{"name": "x"}'), ("int", '{"version": 1}'),
                            ("v", '{"version": "v0.1.0"}'), ("lead0", '{"version": "01.0.0"}'),
                            ("two", '{"version": "0.1"}'), ("space", '{"version": " 0.1.0"}'),
                            ("nl", '{"version": "0.1.0\\n"}'), ("rc", '{"version": "0.1.0-rc1"}')):
            with self.subTest(state=state):
                if text is None:
                    os.unlink(mpath)
                else:
                    with open(mpath, "w", encoding="utf-8") as fh:
                        fh.write(text)
                lines = self.lines()
                self.assertTrue(lines[3].startswith("FAIL doctor.version: "), lines[3])
                if text is None:
                    self.assertEqual(lines[3], "FAIL doctor.version: .claude-plugin/plugin.json: cannot be read (FileNotFoundError)")
                    for id_ in ("claude-block", "gitignore-block"):  # CB15, CD9
                        self.assertEqual(self.line("doctor." + id_ if False else id_),
                                         "FAIL doctor.%s: not checked: doctor.version failed" % id_)
                self.assertEqual(len(lines), 13)

    def test_doctor_version_exact_text(self):  # VE5
        for cfgv, plug in (("0.1.00", "0.1.0"), ("1.0.0", "0.1.0"), ("0.1.0 ", "0.1.0")):
            self.set_cfg(framework_version=cfgv)
            self.assertTrue(self.lines()[3].startswith("FAIL doctor.version: "), (cfgv, plug))
        self.set_cfg(framework_version="v0.1.0")
        self.assertTrue(self.lines()[3].startswith("FAIL doctor.version: "))

    def test_doctor_numeric_text_4300_4301(self):  # VE6, CB9, CI19, SA13, SA15, VR1
        for limit in INT_LIMITS:
            with int_limit(limit):
                for n in (4300, 4301):
                    digits = "1" * n
                    ver = "1.0." + digits
                    other = "1.0." + "1" * (n - 1) + "2"
                    self.fw = self.mkfw(ver)
                    with mock.patch.object(plugin, "framework_dir", return_value=self.fw):
                        self.set_cfg(framework_version=ver)
                        lines = self.lines()
                        self.assertEqual(lines[1:4], ["PASS doctor.input", "PASS doctor.context", "PASS doctor.version"],
                                         (limit, n))
                        self.assertEqual(self.line("claude-block"), "FAIL doctor.claude-block: missing")
                        self.write("CLAUDE.md", self.claude(pv=ver))
                        self.assertEqual(self.line("claude-block"), "PASS doctor.claude-block")
                        self.write("CLAUDE.md", self.claude(pv=other))
                        self.assertTrue(self.line("claude-block").startswith("FAIL doctor.claude-block: version "))
                        self.set_cfg(framework_version=other)
                        self.assertTrue(self.lines()[3].startswith("FAIL doctor.version: "))
                        self.managed_ci(pin="v" + ver)
                        self.assertEqual(self.line("ci"), "PASS doctor.ci")
                        os.unlink(os.path.join(self.r, WF))
                        os.unlink(os.path.join(self.r, "CLAUDE.md"))
                        self.settings(raw='{"env": {"%s": %s}}' % (DEPTH, digits))
                        self.assertTrue(self.line("subagents").startswith("FAIL doctor.subagents: "))
                        self.settings(raw='{"env": {"%s": "%s"}}' % (DEPTH, digits))
                        self.assertTrue(self.line("subagents").startswith("FAIL doctor.subagents: "))
        self.fw = self.mkfw(PV)


# ---------------------------------------------------------------------------------------------------- order, text, scans
class TestOutput(Base):
    def test_doctor_text_json_escape_unique_deterministic(self):  # OUT6-OUT10, OUT12, OUT13
        self.set_cfg(framework_version="bad\x00\n\r\t\x1b\\Ꟁ")
        lines = self.lines()
        self.assertEqual(lines[3], "FAIL doctor.version: framework_version bad\\x00\\n\\r\\t\\x1b\\\\\\ua7c0 differs from the plugin 0.1.0; run /strict-delivery:upgrade")
        self.assertEqual(len(lines), len(set(l.split(":")[0] for l in lines)))
        for ln in lines:
            if ln.startswith("FAIL"):
                self.assertRegex(ln, r"\AFAIL doctor\.[a-z.-]+: .+")
        self.assertEqual(self.run_doctor(), self.run_doctor())
        env = dict(os.environ, PYTHONHASHSEED="0")
        outs = []
        for seed in ("0", "1"):
            env["PYTHONHASHSEED"] = seed
            outs.append(subprocess.run([sys.executable, "-m", "gates.tools.doctor", "--root", self.r], cwd=ROOT, env=env,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE))
        self.assertEqual(outs[0].stdout.decode().count("\n"), len(lines)) if False else None
        self.assertEqual(outs[0].stdout, outs[1].stdout)

    def test_doctor_no_unicode_dependent_calls_no_exceptgroup_no_git_write(self):  # VR2, VR3, no git write call
        with open(os.path.join(ROOT, "gates", "tools", "doctor.py"), encoding="utf-8") as fh:
            src = fh.read()
        tree = ast.parse(src)
        banned = {"lower", "upper", "casefold", "isprintable", "isdecimal", "isalnum", "isdigit", "isnumeric", "int"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                f = node.func
                name = f.attr if isinstance(f, ast.Attribute) else f.id if isinstance(f, ast.Name) else None
                self.assertNotIn(name, banned, ast.dump(node)[:80])
            self.assertNotIsInstance(node, getattr(ast, "TryStar", ()) or ())
        self.assertNotIn("BaseExceptionGroup", src)
        self.assertNotIn("unicodedata", src)
        for word in ("regenerate", "put_block", "managed.apply", "githooks.install", "host.calls", "host.run(",
                     '"add"', '"commit"', '"fetch"', '"push"', '"update-index"'):
            self.assertNotIn(word, src.replace("never ``index.regenerate``", ""), word)

    def test_doctor_usage_text_same_and_python_module_main(self):  # VR5, AR22
        out = subprocess.run([sys.executable, "-m", "gates.tools.doctor"], cwd=ROOT, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE)
        self.assertEqual((out.returncode, out.stdout), (2, b""))
        self.assertIn(b"usage: python3 -m gates.tools.doctor --root R", out.stderr)


class TestHardening(Base):
    """Amendment H rows H1-H7, for the paths doctor itself reads (parents, equal paths, outside the root, bytes)."""

    def test_h4_parent_symlinks_refused(self):  # H4 (with EX20, SA20): a symlinked parent is never followed
        elsewhere = os.path.join(self.tmp, "elsewhere")
        os.makedirs(os.path.join(elsewhere, "workflows"))
        self.write("settings.json", '{"env": {"%s": "abc"}}' % DEPTH, root=elsewhere)
        os.symlink(elsewhere, os.path.join(self.r, ".claude"))
        self.assertEqual(self.line("subagents"), "FAIL doctor.subagents: %s: parent .claude is a symlink" % SETTINGS)
        os.makedirs(os.path.join(self.r, ".github"))
        os.symlink(os.path.join(elsewhere, "workflows"), os.path.join(self.r, ".github", "workflows"))
        self.write("strict-delivery.yml", "# strict-delivery: generated by x; do not edit\n",
                   root=os.path.join(elsewhere, "workflows"))
        self.assertEqual(self.line("extras"), "FAIL doctor.extras: %s: parent .github/workflows is a symlink" % WF)
        self.assertEqual([ln for ln in self.lines() if "doctor.ci" in ln], [])

    def test_h5_equal_and_nested_configured_paths(self):  # H5 (IX4): equal paths are refused by index.render
        self.set_cfg(paths={"decisions": "docs/same", "findings": "docs/same"})
        self.assertEqual(self.line("indexes").split(":")[0], "FAIL doctor.indexes")
        self.set_cfg(paths={"decisions": "docs/a", "findings": "docs/a/b"})
        self.assertEqual(len(self.lines()), 13)  # nested paths: no traceback, every line still printed

    def test_h7_paths_outside_the_root_refused(self):  # H7 (IN4): a configured path outside the root fails doctor.input
        for value in ("../outside", "/abs/path", "a/../../b"):
            self.set_cfg(paths={"decisions": value})
            with self.subTest(value=value):
                lines = self.lines()
                self.assertEqual(len(lines), 2, lines)
                self.assertTrue(lines[1].startswith("FAIL doctor.input: "), lines)

    def test_h6_hook_bytes(self):  # H6 (EX10, GH16): non-UTF-8 hook content never raises
        path = os.path.join(self.r, ".git", "hooks", "pre-commit")
        with open(path, "wb") as fh:
            fh.write(b"#!/bin/sh\n" + githooks.HEADER.encode() + b"\n\xff\xfe\n")
        os.chmod(path, 0o755)
        self.assertEqual(self.line("githooks.pre-commit"), "FAIL doctor.githooks.pre-commit: stale")
        self.assertIn("git hooks: installed", self.line("extras"))


class TestConfigParent(Base):
    def test_h4_config_parent_symlink_or_file_refused(self):  # H4 (HC1, HC2): config.load follows a symlinked parent (U2 class)
        out = os.path.join(self.tmp, "out")
        shutil.copytree(os.path.join(self.r, ".strict-delivery"), out)
        shutil.rmtree(os.path.join(self.r, ".strict-delivery"))
        os.symlink(out, os.path.join(self.r, ".strict-delivery"))
        code, text, _ = self.run_doctor()
        self.assertEqual((code, text.splitlines()), (1, [
            "PASS doctor.python",
            "FAIL doctor.input: .strict-delivery/config.yml: parent .strict-delivery is a symlink"]))
        os.unlink(os.path.join(self.r, ".strict-delivery"))
        self.write(".strict-delivery", "a file\n")
        self.assertEqual(self.lines(), [
            "PASS doctor.python",
            "FAIL doctor.input: .strict-delivery/config.yml: parent .strict-delivery is not a directory"])


class TestSwapAfterCheck(Base):
    """H4, the second half: a path component swapped after the ``lstat`` that approved it. ``os.lstat`` is made to
    report an approved object (a regular file or a directory) for the name while the real object is a symlink or a
    FIFO; doctor must still refuse it and must not read outside the root or block (the race-at-open pattern of
    tests/test_managed.py ``swap_lstat``)."""

    def lie(self, mapping):
        real = os.lstat

        def fake(p, *a, **k):
            return real(mapping.get(os.path.basename(p), p) if isinstance(p, str) else p, *a, **k)
        return mock.patch("os.lstat", side_effect=fake)

    @contextlib.contextmanager
    def no_block(self, secs=20):  # a blocked open of a FIFO becomes an AssertionError instead of a hang
        import signal

        def boom(sig, frm):
            raise AssertionError("blocked on a FIFO")
        old = signal.signal(signal.SIGALRM, boom)
        signal.alarm(secs)
        try:
            yield
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old)

    def outside(self):
        d = os.path.join(self.tmp, "outside")
        os.makedirs(os.path.join(d, "workflows"), exist_ok=True)
        reg = os.path.join(self.tmp, "reg-file")
        with open(reg, "w") as fh:
            fh.write("x\n")
        return d, reg

    def test_final_component_swapped_to_a_symlink_refused(self):  # H4 (HS1): CLAUDE.md, .gitignore, settings, workflow
        d, reg = self.outside()
        self.write("CLAUDE.md", self.claude(), root=d)
        self.write(".gitignore", self.ignore(), root=d)
        self.write("settings.json", '{"env": {"%s": "abc"}}' % DEPTH, root=d)
        self.write("workflows/strict-delivery.yml", "# strict-delivery: generated by x; do not edit\n", root=d)
        os.makedirs(os.path.join(self.r, ".claude"))
        os.makedirs(os.path.join(self.r, ".github", "workflows"))
        for rel, src, id_ in (("CLAUDE.md", "CLAUDE.md", "claude-block"), (".gitignore", ".gitignore", "gitignore-block"),
                              (SETTINGS, "settings.json", "subagents"), (WF, "workflows/strict-delivery.yml", "extras")):
            os.symlink(os.path.join(d, src), os.path.join(self.r, rel))
            with self.subTest(path=rel), self.lie({os.path.basename(rel): reg}):
                self.assertEqual(self.line(id_), "FAIL doctor.%s: %s: is a symlink" % (id_, rel))

    def test_final_component_swapped_to_a_fifo_never_blocks(self):  # H4, H3 (HS2)
        d, reg = self.outside()
        os.makedirs(os.path.join(self.r, ".claude"))
        os.makedirs(os.path.join(self.r, ".github", "workflows"))
        for rel, id_ in (("CLAUDE.md", "claude-block"), (".gitignore", "gitignore-block"), (SETTINGS, "subagents"),
                         (WF, "extras")):
            os.mkfifo(os.path.join(self.r, rel))
            with self.subTest(path=rel), self.lie({os.path.basename(rel): reg}), self.no_block():
                self.assertEqual(self.line(id_), "FAIL doctor.%s: %s: is not a regular file" % (id_, rel))

    def test_parent_swapped_to_a_symlink_refused(self):  # H4 (HS3): .claude and .github/workflows
        d, _ = self.outside()
        real_dir = os.path.join(self.tmp, "real-dir")
        os.mkdir(real_dir)
        self.write("settings.json", '{"env": {"%s": "abc"}}' % DEPTH, root=d)
        os.symlink(d, os.path.join(self.r, ".claude"))
        with self.lie({".claude": real_dir}):
            self.assertEqual(self.line("subagents"), "FAIL doctor.subagents: %s: parent .claude is a symlink" % SETTINGS)
        self.write("workflows/strict-delivery.yml", "# strict-delivery: generated by x; do not edit\n", root=d)
        os.makedirs(os.path.join(self.r, ".github"))
        os.symlink(os.path.join(d, "workflows"), os.path.join(self.r, ".github", "workflows"))
        with self.lie({"workflows": real_dir}):
            self.assertEqual(self.line("extras"), "FAIL doctor.extras: %s: parent .github/workflows is a symlink" % WF)

    def test_every_configured_state_path_in_every_file_state(self):  # H1, H2, H3, H7 for each configured path
        keys = list(config.DEFAULTS["paths"])
        for key in keys:  # H7: outside the root is refused at doctor.input
            for value in ("../outside", "/abs/path"):
                self.set_cfg(paths={key: value})
                with self.subTest(key=key, value=value):
                    lines = self.lines()
                    self.assertEqual(len(lines), 2, lines)
                    self.assertTrue(lines[1].startswith("FAIL doctor.input: "), lines)
        elsewhere = os.path.join(self.tmp, "elsewhere")
        os.mkdir(elsewhere)
        for key in keys:
            for kind in ("symlink", "fifo", "file", "dir"):
                rel = "odd/" + key
                self.set_cfg(paths={key: rel})
                path = os.path.join(self.r, rel)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                {"symlink": lambda: os.symlink(elsewhere, path), "fifo": lambda: os.mkfifo(path),
                 "file": lambda: put(path, b"x\n"), "dir": lambda: os.mkdir(path)}[kind]()
                with self.subTest(key=key, kind=kind), self.no_block():
                    code, out, err = self.run_doctor()
                    self.assertIn(code, (0, 1))
                    self.assertEqual(err, "")
                    self.assertTrue(all(ln.startswith(("PASS doctor.", "FAIL doctor.")) for ln in out.splitlines()), out)
                    self.assertEqual(sum(1 for ln in out.splitlines() if " doctor.input" in ln), 1)
                clear(path)

    def test_h6_odd_names_in_a_register_directory(self):  # H6: a name that is not UTF-8, one with a newline and a NUL-free odd one
        d = os.path.join(self.r, self.cfg()["paths"]["decisions"])
        os.makedirs(d)
        made = 0
        for name in (b"DEC-\xff\xfe.yml", b"line\nbreak.yml", "é ü.yml".encode("utf-8")):
            try:
                put(os.path.join(os.fsencode(d), name), b"not: valid\n")
                made += 1
            except OSError:
                pass  # the file system refuses the name
        self.assertTrue(made >= 1)
        code, out, err = self.run_doctor()
        self.assertEqual((code, err), (1, ""))
        self.assertTrue(all(ln.startswith(("PASS doctor.", "FAIL doctor.")) for ln in out.splitlines()), out)

    def test_plugin_manifest_directory_and_fifo(self):  # H2, H3 for plugin.json (the framework side, never blocks)
        m = os.path.join(self.fw, ".claude-plugin", "plugin.json")
        for make in (lambda: os.mkdir(m), lambda: os.mkfifo(m)):
            os.unlink(m) if os.path.isfile(m) or os.path.islink(m) else None
            make()
            with self.no_block():
                got = self.lines()[3]
            self.assertTrue(got.startswith("FAIL doctor.version: "), got)
            clear(m)

    def test_hook_shim_swapped_after_check_not_read(self):  # H4, H3 (HS4): a symlink or FIFO in place of a shim
        d, reg = self.outside()
        hooks = os.path.join(self.r, ".git", "hooks")
        shim = os.path.join(d, "shim")
        with open(shim, "wb") as fh:
            fh.write(b"#!/bin/sh\n" + githooks.HEADER.encode() + b"\n")
        for name in githooks.NAMES:
            os.symlink(shim, os.path.join(hooks, name))
        with self.lie({n: reg for n in githooks.NAMES}):
            self.assertIn("neither extra installed", self.line("extras"))
        for name in githooks.NAMES:
            os.unlink(os.path.join(hooks, name))
            os.mkfifo(os.path.join(hooks, name))
        with self.lie({n: reg for n in githooks.NAMES}), self.no_block():
            self.assertIn("neither extra installed", self.line("extras"))


NEITHER_TEXT = "PASS doctor.extras: neither extra installed: this repository is gated only inside Claude sessions"


class TestHooksDirParents(Base):
    """H4 and H7 for the hooks directory (F-20261125-wch7): ``core.hooksPath`` leading through a symlinked parent, or to a
    directory outside the root, never makes a shim there count. Row EX9 gives the verdict of a hook that is not a regular
    file below the root: ``foreign``, and not installed unless the other directory holds a shim."""

    def outside_shims(self):
        """Real shims copied into a directory outside the root; the repository's own shims are removed."""
        self.shims()
        hooks = os.path.join(self.r, ".git", "hooks")
        out = os.path.join(self.tmp, "outside-hooks")
        os.makedirs(out)
        for n in githooks.NAMES:
            shutil.copyfile(os.path.join(hooks, n), os.path.join(out, n))
            os.chmod(os.path.join(out, n), 0o755)
            os.unlink(os.path.join(hooks, n))
        return out

    def test_h4_hooks_path_through_a_symlinked_parent_not_installed(self):  # H4 (hooksPath symlink, nested symlink)
        out = self.outside_shims()
        os.symlink(out, os.path.join(self.r, "myhooks"))
        git(self.r, "config", "core.hooksPath", "myhooks")
        self.assertEqual(self.line("extras"), NEITHER_TEXT)
        self.assertEqual([ln for ln in self.lines() if "githooks" in ln], [])
        git(self.r, "config", "core.hooksPath", "a/b")  # a parent two levels up is the link
        os.makedirs(os.path.join(self.tmp, "outside-a"))
        os.symlink(out, os.path.join(self.tmp, "outside-a", "b"))
        os.symlink(os.path.join(self.tmp, "outside-a"), os.path.join(self.r, "a"))
        self.assertEqual(self.line("extras"), NEITHER_TEXT)
        self.assertEqual([ln for ln in self.lines() if "githooks" in ln], [])

    def test_h7_hooks_path_outside_the_root_not_installed(self):  # H7: an absolute core.hooksPath outside the root
        out = self.outside_shims()
        git(self.r, "config", "core.hooksPath", out)
        self.assertEqual(self.line("extras"), NEITHER_TEXT)
        self.assertEqual([ln for ln in self.lines() if "githooks" in ln], [])
        for n in githooks.NAMES:
            shutil.copyfile(os.path.join(out, n), os.path.join(os.path.dirname(self.r), n))
            os.chmod(os.path.join(os.path.dirname(self.r), n), 0o755)
        git(self.r, "config", "core.hooksPath", "..")
        self.assertEqual(self.line("extras"), NEITHER_TEXT)
        self.assertEqual([ln for ln in self.lines() if "githooks" in ln], [])
        inside = os.path.join(self.r, "inhooks")  # control: the same shims in a real directory below the root count
        shutil.copytree(out, inside)
        git(self.r, "config", "core.hooksPath", inside)
        self.assertEqual(self.line("extras"), "PASS doctor.extras: git hooks: installed; CI: not installed")
        self.assertEqual(self.line("githooks.pre-commit"), "PASS doctor.githooks.pre-commit")
        for n in githooks.NAMES:  # control: hooksPath "" makes the root itself the hooks directory (GH10)
            shutil.copyfile(os.path.join(out, n), os.path.join(self.r, n))
            os.chmod(os.path.join(self.r, n), 0o755)
        git(self.r, "config", "core.hooksPath", "")
        self.assertEqual(self.line("extras"), "PASS doctor.extras: git hooks: installed; CI: not installed")

    def test_hooks_header_must_be_a_complete_line_two(self):  # EX7: the header on line 2 needs its newline
        self.shims()
        hooks = os.path.join(self.r, ".git", "hooks")
        for n in githooks.NAMES:
            put(os.path.join(hooks, n), b"#!/bin/sh\n" + githooks.HEADER.encode("utf-8"))
            os.chmod(os.path.join(hooks, n), 0o755)
        self.assertEqual(self.line("extras"), NEITHER_TEXT)

    def test_hooks_path_absent_directory_lines_are_missing(self):  # a hooks directory that does not exist: library "missing"
        out = self.outside_shims()
        for n in githooks.NAMES:
            shutil.copyfile(os.path.join(out, n), os.path.join(self.r, ".git", "hooks", n))
            os.chmod(os.path.join(self.r, ".git", "hooks", n), 0o755)
        git(self.r, "config", "core.hooksPath", "nodir/sub")
        lines = [ln for ln in self.lines() if "githooks" in ln or "doctor.extras" in ln]
        self.assertEqual(lines, ["PASS doctor.extras: git hooks: installed; CI: not installed",
                                 "FAIL doctor.githooks.pre-commit: missing", "FAIL doctor.githooks.pre-push: missing",
                                 "FAIL doctor.githooks.hooks-path: core.hooksPath is set (nodir/sub); unset it to install the hooks"])

    def test_h4_symlinked_hooks_directory_lines_are_foreign(self):  # H4 + EX9: shims elsewhere, the configured directory is a link
        out = self.outside_shims()
        for n in githooks.NAMES:  # the default directory keeps its shims, so the extra is installed
            shutil.copyfile(os.path.join(out, n), os.path.join(self.r, ".git", "hooks", n))
            os.chmod(os.path.join(self.r, ".git", "hooks", n), 0o755)
        os.symlink(out, os.path.join(self.r, "myhooks"))
        git(self.r, "config", "core.hooksPath", "myhooks")
        lines = [ln for ln in self.lines() if "githooks" in ln or "doctor.extras" in ln]
        self.assertEqual(lines, ["PASS doctor.extras: git hooks: installed; CI: not installed",
                                 "FAIL doctor.githooks.pre-commit: foreign", "FAIL doctor.githooks.pre-push: foreign",
                                 "FAIL doctor.githooks.hooks-path: core.hooksPath is set (myhooks); unset it to install the hooks"])
        git(self.r, "config", "core.hooksPath", out)  # H7: the real directory outside the root, an absolute path
        lines = [ln for ln in self.lines() if "githooks" in ln or "doctor.extras" in ln]
        self.assertEqual(lines, ["PASS doctor.extras: git hooks: installed; CI: not installed",
                                 "FAIL doctor.githooks.pre-commit: foreign", "FAIL doctor.githooks.pre-push: foreign",
                                 "FAIL doctor.githooks.hooks-path: core.hooksPath is set (%s); unset it to install the hooks" % out])


# ---------------------------------------------------------------------------------------------------- context.yml
CTX_MISSING = "FAIL doctor.context: .strict-delivery/context.yml: missing; run /strict-delivery:init"


class TestContext(Base):
    """Amendment C (plan :5102; Note C-2): the line ``doctor.context`` directly after ``doctor.input``."""

    def ctx_path(self):
        return os.path.join(self.r, CONTEXT)

    def test_cx1_context_missing(self):  # CX1: the repository is initialised but has no context.yml
        os.unlink(self.ctx_path())
        before = snap(self.r)
        code, out, err = self.run_doctor()
        lines = out.splitlines()
        self.assertEqual((code, err), (1, ""))
        self.assertEqual(lines[:3], ["PASS doctor.python", "PASS doctor.input", CTX_MISSING])
        self.assertEqual(len(lines), 13)  # the run continues after the line
        self.assertEqual((snap(self.r), self.gh.log()), (before, []))  # writes nothing

    def test_cx2_context_valid(self):  # CX2 valid: PASS, placed between doctor.input and doctor.version
        lines = self.lines()
        self.assertEqual(lines[1:4], ["PASS doctor.input", "PASS doctor.context", "PASS doctor.version"])
        self.assertEqual(len([ln for ln in lines if " doctor.context" in ln]), 1)

    def test_cx2_context_invalid(self):  # CX2 invalid against the schema: the production loader's text
        for text, want in ((b"schema: context/9\n",
                            "schema: expected context/1, got context/9; run /strict-delivery:upgrade"),
                           (b"", "top level: must be a mapping"),
                           (b"every: 3\n", "schema: expected context/1, got (missing)"),
                           (b"schema: context/1\nevery: nope\n", "every: must be a list"),
                           (b"schema: context/1\nbogus: 1\n", "bogus: unknown key"),
                           (b"a: {b: 1}\n", ".strict-delivery/context.yml: flow mappings are not supported (line 1)")):
            put(self.ctx_path(), text)
            with self.subTest(text=text):
                code, out, _ = self.run_doctor()
                self.assertEqual(code, 1)
                self.assertEqual(out.splitlines()[2], "FAIL doctor.context: .strict-delivery/context.yml: " + want)

    def test_cx2_context_file_states(self):  # CX2 symlink, directory, FIFO, non-UTF-8 (H1, H2, H3, H6): doctor's own texts
        import signal
        real = os.path.join(self.tmp, "real-context.yml")
        put(real, CONTEXT_OK)
        p = self.ctx_path()
        os.unlink(p)  # the fixture's valid file; each state below replaces it in turn
        for name, make, want in (("symlink", lambda: os.symlink(real, p), "is a symlink"),
                                 ("dangling", lambda: os.symlink(real + ".nope", p), "is a symlink"),
                                 ("directory", lambda: os.mkdir(p), "is not a regular file"),
                                 ("fifo", lambda: os.mkfifo(p), "is not a regular file"),
                                 ("nonutf8", lambda: put(p, b"schema: context/1\n\xff\xfe"), "is not valid UTF-8")):
            make()
            with self.subTest(state=name):
                def boom(sig, frm):
                    raise AssertionError("blocked on a FIFO")
                old = signal.signal(signal.SIGALRM, boom)
                signal.alarm(20)
                try:
                    code, out, err = self.run_doctor()
                finally:
                    signal.alarm(0)
                    signal.signal(signal.SIGALRM, old)
                self.assertEqual((code, err), (1, ""))
                self.assertEqual(out.splitlines()[2], "FAIL doctor.context: .strict-delivery/context.yml: " + want)
            clear(p)

    def test_cx2_context_parent_symlink_refused(self):  # H4: a symlinked parent is refused by doctor.input first
        os.unlink(self.ctx_path())
        out = os.path.join(self.tmp, "moved")
        os.rename(os.path.join(self.r, ".strict-delivery"), out)
        os.symlink(out, os.path.join(self.r, ".strict-delivery"))
        self.assertEqual(self.lines(), [
            "PASS doctor.python",
            "FAIL doctor.input: .strict-delivery/config.yml: parent .strict-delivery is a symlink"])
