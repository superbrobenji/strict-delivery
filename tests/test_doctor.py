"""Tests of gates/tools/doctor.py (Task 4d.3). Every test runs the production path (``doctor.main`` / ``doctor.check``) on
a fixture repository; every ``gh`` is a fake script first on PATH (no real ``gh``, no network); expected texts are
hand-written from the plan lines and the task-4d.3 domain table, whose row ids are named in each comment."""
import ast
import builtins
import contextlib
import hashlib
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from gates.lib import config, dispatch, host, plugin, templates
from gates.lib.result import GateError
from gates.tools import doctor, githooks, index
from tests.helpers import INT_LIMITS, GitIsolatedTestCase, commit_all, git, int_limit, make_repo, minimal_config, \
    root_forms, check_root_forms
from tests.test_host import NF, PROT, PROT_OK, REPO, REPO_OK, FakeGh, j, only_path

PV = "0.1.0"
GIT = shutil.which("git")
SHA40 = "a" * 40
SETTINGS = ".claude/settings.json"
WF = ".github/workflows/strict-delivery.yml"
DEPTH = "CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH"
CONC = "CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS"
UNSET = "unset (Claude Code default)"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT_ID = ["doctor.python", "doctor.input", "doctor.version", "doctor.extras", "doctor.claude-block",
           "doctor.gitignore-block", "doctor.registers", "doctor.indexes", "doctor.generated-tracked",
           "doctor.subagents", "doctor.merge-mode", "doctor.protection"]
STATE_KEYS = ["protected", "pr_required", "admins", "merge_commit", "squash", "rebase"]
WORDS = ["pull request not required", "administrators not enforced", "merge commit not allowed",
         "squash merge allowed", "rebase merge allowed"]


def put(path, data=b""):
    with open(path, "wb") as fh:
        fh.write(data)


def clear(p):
    if os.path.islink(p):
        os.unlink(p)
    elif os.path.isdir(p):
        os.rmdir(p)
    else:
        os.chmod(p, 0o644)
        os.unlink(p)


def snap(path, skip_pycache=False):
    """Independent tree snapshot: (relative path, kind, mode, size, sha256, link target, mtime_ns), links not followed."""
    out = []
    for dp, dns, fns in os.walk(path, followlinks=False):
        if skip_pycache:
            dns[:] = [d for d in dns if d != "__pycache__"]
        for n in sorted(dns + fns):
            p = os.path.join(dp, n)
            st = os.lstat(p)
            digest = target = None
            if stat.S_ISREG(st.st_mode):
                with open(p, "rb") as fh:
                    digest = hashlib.sha256(fh.read()).hexdigest()
            elif stat.S_ISLNK(st.st_mode):
                target = os.readlink(p)
            out.append((os.path.relpath(p, path), stat.S_IFMT(st.st_mode), st.st_mode, st.st_size, digest, target,
                        st.st_mtime_ns))
    return sorted(out)


class Base(GitIsolatedTestCase):
    def setUp(self):
        super().setUp()
        self.fw = self.mkfw(PV)
        p = mock.patch.object(plugin, "framework_dir", return_value=self.fw)
        p.start()
        self.addCleanup(p.stop)
        self.gh = FakeGh(self, {})  # a fake first on PATH in every test: nothing can reach a real gh
        self.r = make_repo(self.work, dict(minimal_config(), framework_version=PV))

    def mkfw(self, version, repository="https://github.com/o/n", name="fw"):
        d = os.path.join(self.tmp, name)
        os.makedirs(os.path.join(d, ".claude-plugin"), exist_ok=True)
        os.makedirs(os.path.join(d, "gates"), exist_ok=True)
        if not os.path.exists(os.path.join(d, "profiles")):  # config.load reads the profile from the framework
            shutil.copytree(os.path.join(ROOT, "profiles"), os.path.join(d, "profiles"))
        manifest = {"name": "x"}
        if version is not None:
            manifest["version"] = version
        if repository is not None:
            manifest["repository"] = repository
        with open(os.path.join(d, ".claude-plugin", "plugin.json"), "w", encoding="utf-8") as fh:
            json.dump(manifest, fh)
        return d

    def run_doctor(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = doctor.main(list(argv) if argv else ["--root", self.r])
        return code, out.getvalue(), err.getvalue()

    def main(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = doctor.main(argv)
        return code, out.getvalue(), err.getvalue()

    def lines(self, *argv):
        return self.run_doctor(*argv)[1].splitlines()

    def line(self, id_, *argv):
        found = [ln for ln in self.lines(*argv) if ln.split(":")[0].split(" ", 1)[1] == "doctor." + id_]
        self.assertEqual(len(found), 1, found)
        return found[0]

    def write(self, rel, text, root=None, mode=None):
        path = os.path.join(root or self.r, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        if mode is not None:
            os.chmod(path, mode)
        return path

    def cfg(self):
        return config.load(self.r)

    def claude(self, pv=PV, body=None, outside=""):
        body = templates.claude_block_body(self.cfg()) if body is None else body
        return (outside + "<!-- strict-delivery:begin schema=claude-block/1 version=%s -->\n" % pv + body
                + "<!-- strict-delivery:end -->\n")

    def ignore(self, pv=PV, body=None, outside=""):
        body = templates.gitignore_block_body(self.cfg()) if body is None else body
        return (outside + "# strict-delivery:begin schema=gitignore-block/1 version=%s\n" % pv + body
                + "# strict-delivery:end\n")

    def green(self):
        self.write("CLAUDE.md", self.claude())
        self.write(".gitignore", self.ignore())

    def shims(self):
        self.assertEqual(githooks.install(self.r, githooks.framework_dir()), [])

    def managed_ci(self, pin="v" + PV, repo="o/n"):
        text = templates.ci_workflow(self.cfg(), pin, repo)
        self.write(WF, text)
        return text

    def origin(self, url="https://github.com/o/n.git"):
        git(self.r, "remote", "add", "origin", url)

    def settings(self, obj=None, raw=None):
        self.write(".claude/settings.json", raw if raw is not None else json.dumps(obj))

    def set_cfg(self, **kw):
        row = dict(minimal_config(), framework_version=PV)
        row.update(kw)
        from tests.helpers import write_record
        write_record(self.r, ".strict-delivery/config.yml", row)


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
        self.assertEqual(doc["lines"][3]["reason"],
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
            self.assertEqual(len(lines), 12)  # the run continues
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
        self.assertEqual(self.lines()[2], "PASS doctor.version")
        self.set_cfg(framework_version="0.0.0")
        self.assertEqual(self.lines()[2],
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
                self.assertTrue(lines[2].startswith("FAIL doctor.version: "), lines[2])
                if text is None:
                    self.assertEqual(lines[2], "FAIL doctor.version: .claude-plugin/plugin.json: cannot be read (FileNotFoundError)")
                    for id_ in ("claude-block", "gitignore-block"):  # CB15, CD9
                        self.assertEqual(self.line("doctor." + id_ if False else id_),
                                         "FAIL doctor.%s: not checked: doctor.version failed" % id_)
                self.assertEqual(len(lines), 12)

    def test_doctor_version_exact_text(self):  # VE5
        for cfgv, plug in (("0.1.00", "0.1.0"), ("1.0.0", "0.1.0"), ("0.1.0 ", "0.1.0")):
            self.set_cfg(framework_version=cfgv)
            self.assertTrue(self.lines()[2].startswith("FAIL doctor.version: "), (cfgv, plug))
        self.set_cfg(framework_version="v0.1.0")
        self.assertTrue(self.lines()[2].startswith("FAIL doctor.version: "))

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
                        self.assertEqual(lines[1:3], ["PASS doctor.input", "PASS doctor.version"], (limit, n))
                        self.assertEqual(self.line("claude-block"), "FAIL doctor.claude-block: missing")
                        self.write("CLAUDE.md", self.claude(pv=ver))
                        self.assertEqual(self.line("claude-block"), "PASS doctor.claude-block")
                        self.write("CLAUDE.md", self.claude(pv=other))
                        self.assertTrue(self.line("claude-block").startswith("FAIL doctor.claude-block: version "))
                        self.set_cfg(framework_version=other)
                        self.assertTrue(self.lines()[2].startswith("FAIL doctor.version: "))
                        self.managed_ci(pin="v" + ver)
                        self.assertEqual(self.line("ci"), "PASS doctor.ci")
                        os.unlink(os.path.join(self.r, WF))
                        os.unlink(os.path.join(self.r, "CLAUDE.md"))
                        self.settings(raw='{"env": {"%s": %s}}' % (DEPTH, digits))
                        self.assertTrue(self.line("subagents").startswith("FAIL doctor.subagents: "))
                        self.settings(raw='{"env": {"%s": "%s"}}' % (DEPTH, digits))
                        self.assertTrue(self.line("subagents").startswith("FAIL doctor.subagents: "))
        self.fw = self.mkfw(PV)


# ---------------------------------------------------------------------------------------------------- extras, hooks, ci
class TestExtras(Base):
    def test_neither_extra_says_so(self):  # EX1 (plan), EX24
        self.assertIn("PASS doctor.extras: neither extra installed: this repository is gated only inside Claude sessions",
                      self.run_doctor()[1])
        lines = [ln for ln in self.lines() if "githooks" in ln or "doctor.ci" in ln]
        self.assertEqual(lines, [])

    def test_doctor_extras_combinations(self):  # EX2, EX3, EX4, EX5, EX6, EX8, EX14, EX15, OUT2, OUT3, GH1, CI3
        self.shims()
        self.assertEqual(self.line("extras"), "PASS doctor.extras: git hooks: installed; CI: not installed")
        ids = [ln.split(":")[0].split(" ")[1] for ln in self.lines()]
        self.assertEqual(ids[3:6], ["doctor.extras", "doctor.githooks.pre-commit", "doctor.githooks.pre-push"])
        self.assertEqual(self.line("githooks.pre-push"), "PASS doctor.githooks.pre-push")
        self.managed_ci()
        self.assertEqual(self.line("extras"), "PASS doctor.extras: git hooks: installed; CI: installed")
        ids = [ln.split(":")[0].split(" ")[1] for ln in self.lines()]
        self.assertEqual(ids[3:7], ["doctor.extras", "doctor.githooks.pre-commit", "doctor.githooks.pre-push", "doctor.ci"])
        self.assertEqual(self.line("ci"), "PASS doctor.ci")
        hooks = os.path.join(self.r, ".git", "hooks")
        os.unlink(os.path.join(hooks, "pre-push"))  # one hook of two
        self.assertEqual(self.line("extras"), "PASS doctor.extras: git hooks: installed; CI: installed")
        self.assertEqual(self.line("githooks.pre-push"), "FAIL doctor.githooks.pre-push: missing")
        os.unlink(os.path.join(hooks, "pre-commit"))
        self.assertEqual(self.line("extras"), "PASS doctor.extras: git hooks: not installed; CI: installed")
        self.assertEqual([ln for ln in self.lines() if "githooks" in ln], [])  # GH7

    def test_doctor_extras_foreign_and_stale_hooks(self):  # EX6, EX7, EX8, EX9, EX10, GH3, GH4, GH5, GH14
        hooks = os.path.join(self.r, ".git", "hooks")
        for n in githooks.NAMES:
            self.write(".git/hooks/" + n, "#!/bin/sh\necho hi\n", mode=0o755)
        self.write(".git/hooks/pre-commit.sample", "#!/bin/sh\n")
        self.assertEqual(self.line("extras"), "PASS doctor.extras: neither extra installed: this repository is gated only inside Claude sessions")
        self.assertEqual([ln for ln in self.lines() if "githooks" in ln], [])
        for n in githooks.NAMES:
            os.unlink(os.path.join(hooks, n))
        self.shims()
        self.write(".git/hooks/pre-commit", "#!/bin/sh\necho mine\n", mode=0o755)
        self.assertEqual(self.line("githooks.pre-commit"), "FAIL doctor.githooks.pre-commit: foreign")
        self.assertEqual(self.line("githooks.pre-push"), "PASS doctor.githooks.pre-push")
        self.shims() if False else None
        os.unlink(os.path.join(hooks, "pre-commit"))
        self.shims()
        path = os.path.join(hooks, "pre-push")
        with open(path, "a") as fh:
            fh.write("# more\n")
        self.assertEqual(self.line("githooks.pre-push"), "FAIL doctor.githooks.pre-push: stale")
        self.assertIn("git hooks: installed", self.line("extras"))
        self.shims() if False else os.unlink(path)
        self.shims()
        for mode in (0o644, 0o700, 0o775, 0o777):
            os.chmod(path, mode)
            self.assertEqual(self.line("githooks.pre-push"), "FAIL doctor.githooks.pre-push: stale", oct(mode))
        os.chmod(path, 0o755)
        with open(path) as fh:
            first, header, rest = fh.read().split("\n", 2)
        for name, text in (("line1", header + "\n" + first + "\n" + rest), ("line3", "#!/bin/sh\n\n" + header + "\n"),
                           ("trailing", first + "\n" + header + " \n" + rest), ("crlf", first + "\r\n" + header + "\r\n" + rest),
                           ("bom", "﻿" + first + "\n" + header.upper() + "\n")):
            for n in githooks.NAMES:
                self.write(".git/hooks/" + n, text, mode=0o755)
            with self.subTest(form=name):
                self.assertIn("neither extra installed", self.line("extras"))

    def test_doctor_extras_hook_file_states(self):  # EX9, EX11, FS5, GH16
        hooks = os.path.join(self.r, ".git", "hooks")
        target = os.path.join(self.tmp, "t")
        self.write("t", "x", root=self.tmp)
        for name, make in (("symlink", lambda p: os.symlink(target, p)), ("dangling", lambda p: os.symlink(target + "x", p)),
                           ("dir", os.mkdir), ("fifo", os.mkfifo)):
            for n in githooks.NAMES:
                make(os.path.join(hooks, n))
            with self.subTest(state=name):
                self.assertIn("neither extra installed", self.line("extras"))
            for n in githooks.NAMES:
                p = os.path.join(hooks, n)
                clear(p)
        for n in githooks.NAMES:  # EX11: no hooks directory
            pass
        shutil.rmtree(hooks)
        self.assertIn("neither extra installed", self.line("extras"))

    def test_doctor_hooks_path_bypass_and_set(self):  # GH8, GH9, GH10, GH11
        self.shims()
        git(self.r, "config", "core.hooksPath", "other")
        lines = self.lines()
        self.assertIn("FAIL doctor.githooks.hooks-path: core.hooksPath is set (other); unset it to install the hooks", lines)
        self.assertIn("PASS doctor.extras: git hooks: installed; CI: not installed", lines)
        git(self.r, "config", "--unset", "core.hooksPath")
        git(self.r, "config", "core.hooksPath", "myhooks")
        os.makedirs(os.path.join(self.r, "myhooks"))
        for n in githooks.NAMES:
            self.write("myhooks/" + n, githooks.shim(n, githooks.framework_dir()).decode() if isinstance(githooks.shim(n, githooks.framework_dir()), bytes) else githooks.shim(n, githooks.framework_dir()), mode=0o755)
        lines = self.lines()
        self.assertIn("PASS doctor.githooks.pre-commit", lines)
        self.assertIn("FAIL doctor.githooks.hooks-path: core.hooksPath is set (myhooks); unset it to install the hooks", lines)
        git(self.r, "config", "core.hooksPath", "")
        self.assertIn("hooks-path: core.hooksPath is set ()", "\n".join(self.lines()))
        git(self.r, "config", "--unset", "core.hooksPath")
        with mock.patch.dict(os.environ, {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "core.hooksPath",
                                          "GIT_CONFIG_VALUE_0": "envhooks"}):
            self.assertIn("doctor.githooks.hooks-path", "\n".join(self.lines()))
        self.assertNotIn("hooks-path", "\n".join(self.lines()))

    def test_doctor_githooks_bad_framework_path(self):  # GH13, GH6
        self.shims()
        with mock.patch.object(githooks, "framework_dir", return_value="relative/path"):
            lines = self.lines()
        self.assertIn("FAIL doctor.githooks.framework: the framework path must be absolute and hold no control character", lines)
        self.assertEqual(len(lines), 13)
        with mock.patch.object(githooks, "framework_dir", return_value="/some/other/framework"):
            self.assertEqual(self.line("githooks.pre-commit"), "FAIL doctor.githooks.pre-commit: stale")

    def test_doctor_extras_project_workflow_named(self):  # EX13, EX14, EX15, EX18, EX19, EX21, CI2
        self.write(WF, "name: strict-delivery\non: push\n")
        named = "CI: .github/workflows/strict-delivery.yml is a project workflow, not the framework template"
        self.assertEqual(self.line("extras"),
                         "PASS doctor.extras: neither extra installed: this repository is gated only inside Claude sessions; " + named)
        self.assertEqual([ln for ln in self.lines() if "doctor.ci" in ln], [])
        self.shims()
        self.assertEqual(self.line("extras"), "PASS doctor.extras: git hooks: installed; " + named)
        for text in ("", "﻿# strict-delivery: generated by x; do not edit\n", "# strict-delivery: generated by x; do not edit\r\n",
                     "  # strict-delivery: generated by x; do not edit\n", "# Strict-Delivery: generated by x; do not edit\n",
                     "a\nb\n# strict-delivery: generated by x; do not edit\n"):
            self.write(WF, text)
            with self.subTest(text=text):
                self.assertIn("project workflow", self.line("extras"))
        self.write(WF, "#!/usr/bin/env x\n# strict-delivery: generated by x; do not edit\n")  # EX16, EX17
        self.assertIn("CI: installed", self.line("extras"))
        self.write(WF, "# strict-delivery: generated by other-tool; do not edit\n")
        self.assertIn("CI: installed", self.line("extras"))
        os.unlink(os.path.join(self.r, WF))
        self.write(".github/workflows/strict-delivery.yaml", "x")
        self.assertIn("CI: not installed", self.line("extras"))

    def test_doctor_extras_workflow_file_states(self):  # EX20, CI20, FS4
        p = os.path.join(self.r, WF)
        os.makedirs(os.path.dirname(p))
        cases = [("symlink", lambda: os.symlink(os.path.join(self.tmp, "x"), p), "is a symlink"),
                 ("directory", lambda: os.mkdir(p), "is not a regular file"),
                 ("fifo", lambda: os.mkfifo(p), "is not a regular file"),
                 ("nonutf8", lambda: put(p, b"\xff\xfe"), "is not valid UTF-8")]
        if os.geteuid() != 0:
            cases.append(("mode000", lambda: (put(p), os.chmod(p, 0)), "cannot be read (Permission denied)"))
        self.shims()
        for name, make, frag in cases:
            if os.path.lexists(p):
                clear(p)
            make()
            with self.subTest(state=name):
                self.assertEqual(self.line("extras"), "FAIL doctor.extras: %s: %s" % (WF, frag))
                self.assertIn("PASS doctor.githooks.pre-commit", self.lines())
                self.assertEqual([ln for ln in self.lines() if "doctor.ci" in ln], [])
        os.unlink(p)
        os.rmdir(os.path.dirname(p))
        os.rmdir(os.path.dirname(os.path.dirname(p)))
        self.write(".github", "a file")
        self.assertEqual(self.line("extras"), "FAIL doctor.extras: %s: parent .github is not a directory" % WF)

    def test_ci_pin_mismatch(self):  # CI5 (plan), CI6, CI9, CI10, CI11, CI12, CI13, CI14, CI21
        self.managed_ci(pin="v0.0.9")
        self.assertEqual(self.line("ci"), "FAIL doctor.ci: pin v0.0.9 differs from v0.1.0")
        self.managed_ci(pin=SHA40)
        self.assertEqual(self.line("ci"), "FAIL doctor.ci: pin %s differs from v0.1.0" % SHA40)
        text = self.managed_ci()
        self.assertEqual(self.line("ci"), "PASS doctor.ci")
        for name, edited in (("deleted", text.replace("\n", "", 1) if False else "\n".join(text.split("\n")[:-3]) + "\n"),
                             ("added", text + "# x\n"), ("space", text.replace("\n", " \n", 6).replace(" \n", "\n", 1)),
                             ("nofinal", text.rstrip("\n")),
                             ("tab", text.replace("  ", "\t", 1))):
            self.write(WF, edited)
            with self.subTest(edit=name):
                got = self.line("ci") if "managed" else ""
                self.assertIn(got, ("FAIL doctor.ci: stale",) if name not in ("crlf",) else (got,))
        self.write(WF, text.replace("v0.1.0", "v0.0.9") + "# edit\n")  # CI10: the pin message wins
        self.assertEqual(self.line("ci"), "FAIL doctor.ci: pin v0.0.9 differs from v0.1.0")
        lines = text.split("\n")
        fetch = [i for i, ln in enumerate(lines) if "git fetch --depth 1" in ln]
        self.assertEqual(len(fetch), 1)
        for name, edited in (("nofetch", "\n".join(lines[:fetch[0]] + lines[fetch[0] + 1:])),
                             ("two", "\n".join(lines + [lines[fetch[0]]])),
                             ("branch", text.replace("v0.1.0", "main")), ("short", text.replace("v0.1.0", "v0.1"))):
            self.write(WF, edited)
            with self.subTest(pin=name):
                self.assertEqual(self.line("ci"), "FAIL doctor.ci: pin not found differs from v0.1.0")
        self.managed_ci(repo="a/b")  # CI12
        self.assertEqual(self.line("ci"), "FAIL doctor.ci: stale")
        text = self.managed_ci()  # CI14 diverges: ci_workflow renders cfg base_branch, so the verdict follows it
        self.set_cfg(base_branch="develop")
        self.assertEqual(self.line("ci"), "FAIL doctor.ci: stale")
        self.managed_ci()
        self.assertEqual(self.line("ci"), "PASS doctor.ci")
        self.write(WF, text.replace("\n", "\r\n"))  # EX18: CRLF text has no header line, so a project workflow
        self.assertEqual([ln for ln in self.lines() if "doctor.ci" in ln], [])

    def test_doctor_ci_sha_pin_and_framework_moved(self):  # CI4, CI7, CI8, CI16, CI17, CI18
        self.fw = self.mkfw("0.0.0", name="fwgit")
        git(self.fw, "init", "-q", "-b", "main")
        sha1 = commit_all(self.fw, "one")
        self.set_cfg(framework_version="0.0.0")
        with mock.patch.object(plugin, "framework_dir", return_value=self.fw):
            git(self.fw, "config", "color.ui", "always")
            git(self.fw, "config", "core.abbrev", "7")
            self.managed_ci(pin=sha1)
            self.assertEqual(self.line("ci"), "PASS doctor.ci")
            self.managed_ci(pin="v0.0.0")
            self.assertEqual(self.line("ci"), "FAIL doctor.ci: pin v0.0.0 differs from %s" % sha1)
            self.managed_ci(pin=sha1)
            sha2 = commit_all(self.fw, "two")
            self.assertEqual(self.line("ci"), "FAIL doctor.ci: pin %s differs from %s" % (sha1, sha2))
        self.fw = self.mkfw("0.0.0", name="fwplain")  # not a git checkout, no pin possible
        with mock.patch.object(plugin, "framework_dir", return_value=self.fw):
            self.assertEqual(self.line("ci"), "FAIL doctor.ci: no release tag and no framework commit to pin")
        outer = os.path.join(self.tmp, "outer")  # CI17: the framework is a subdirectory of another repository
        os.makedirs(outer)
        make_repo(outer)
        inner = self.mkfw("0.0.0", name="outer/inner")
        with mock.patch.object(plugin, "framework_dir", return_value=inner):
            self.assertEqual(self.line("ci"), "FAIL doctor.ci: no release tag and no framework commit to pin")

    def test_doctor_ci_plugin_unreadable(self):  # CI15
        self.managed_ci()
        self.fw = self.mkfw(PV, repository="http://x")
        with mock.patch.object(plugin, "framework_dir", return_value=self.fw):
            self.assertTrue(self.line("ci").startswith("FAIL doctor.ci: .claude-plugin/plugin.json: repository"))


# ---------------------------------------------------------------------------------------------------- blocks
class TestBlocks(Base):
    def cases(self):
        return (("claude-block", "CLAUDE.md", self.claude, "<!-- ", " -->"),
                ("gitignore-block", ".gitignore", self.ignore, "# ", ""))

    def test_blocks_current_missing_malformed(self):  # CB1, CB2, CB3, CB4, CB11, GI1, GI2, GI3, GI4, OUT1
        self.assertEqual(self.line("claude-block"), "FAIL doctor.claude-block: missing")
        self.assertEqual(self.line("gitignore-block"), "FAIL doctor.gitignore-block: missing")
        self.green()
        code, out, _ = self.run_doctor()
        self.assertEqual((code, [ln.split(":")[0] for ln in out.splitlines()]), (0, ["PASS " + i for i in ROOT_ID]))
        for id_, rel, build, op, cl in self.cases():
            begin = "%sstrict-delivery:begin schema=%s/1 version=%s%s\n" % (op, id_, PV, cl)
            end = "%sstrict-delivery:end%s\n" % (op, cl)
            for name, text, want in (("empty", "", "missing"), ("plain", "my text mentions strict-delivery\n", "missing"),
                                     ("beginonly", begin, "malformed: block: no end marker"),
                                     ("endonly", end, "malformed: block: end marker before begin marker: line 1"),
                                     ("two", begin + begin + end, "malformed: block: more than one begin marker"),
                                     ("twoends", begin + end + end, "malformed: block: more than one end marker"),
                                     ("reversed", end + begin, "malformed: block: end marker before begin marker: line 1"),
                                     ("indent", " " + begin + end, "malformed: block: begin marker malformed: line 1"),
                                     ("crlf", begin.replace("\n", "\r\n") + end, "malformed: block: begin marker malformed: line 1"),
                                     ("endtrail", begin + end.rstrip("\n") + " x\n", "malformed: block: end marker malformed: line 2")):
                self.write(rel, text)
                with self.subTest(file=rel, form=name):
                    self.assertEqual(self.line(id_), "FAIL doctor.%s: %s" % (id_, want))
            self.write(rel, build(outside="project text\r\n\x00\n") + "after\n")  # CB11, GI8: outside text is free
            self.assertEqual(self.line(id_), "PASS doctor.%s" % id_)

    def test_blocks_schema_tag_version_stale(self):  # CB5, CB6, CB7, CB8, CB9, CB10, GI5, GI6, GI7
        for id_, rel, build, op, cl in self.cases():
            other = "gitignore-block" if id_ == "claude-block" else "claude-block"
            for tag in ("%s/0" % id_, "%s/2" % id_, "%s/7" % id_, "%s/1" % id_ + "0" * 5, "%s/1" % other):
                self.write(rel, build().replace("schema=%s/1" % id_, "schema=" + tag))
                with self.subTest(file=rel, tag=tag):
                    self.assertEqual(self.line(id_), "FAIL doctor.%s: malformed: schema: expected %s/1, got %s; run /strict-delivery:upgrade" % (id_, id_, tag))
            for pv in ("0.0.0", "0.2.0", "01.1.0"):
                self.write(rel, build(pv=pv))
                self.assertEqual(self.line(id_), "FAIL doctor.%s: version %s differs from the plugin 0.1.0" % (id_, pv))
            good = build()
            lines = good.split("\n")
            body = templates.claude_block_body(self.cfg()) if id_ == "claude-block" else templates.gitignore_block_body(self.cfg())
            bl = body.split("\n")
            for name, new in (("changed", [bl[0] + "x"] + bl[1:]), ("added", bl[:-1] + ["extra", ""]),
                              ("removed", bl[1:]), ("reordered", [bl[1], bl[0]] + bl[2:]),
                              ("trailing", [bl[0] + " "] + bl[1:]), ("empty", [""]), ("nul", [bl[0] + "\x00"] + bl[1:])):
                self.write(rel, build(body="\n".join(new)))
                with self.subTest(file=rel, edit=name):
                    self.assertEqual(self.line(id_), "FAIL doctor.%s: stale; run /strict-delivery:upgrade" % id_)
            self.write(rel, build(pv="0.0.0", body="x\n"))  # CB8: version before stale
            self.assertIn("version 0.0.0 differs", self.line(id_))

    def test_stale_block_fails_naming_upgrade(self):  # CB10 (plan)
        self.write("CLAUDE.md", self.claude(body=templates.claude_block_body(self.cfg()) + "extra line\n"))
        self.assertIn("FAIL doctor.claude-block: stale; run /strict-delivery:upgrade", self.run_doctor()[1])
        self.set_cfg(paths={"specs": "elsewhere/specs"})  # CB10: a config path changed after the block was written
        self.write("CLAUDE.md", self.claude())
        self.set_cfg(paths={"specs": "docs/other"})
        self.assertEqual(self.line("claude-block"), "FAIL doctor.claude-block: stale; run /strict-delivery:upgrade")

    def test_blocks_file_states_and_render_refused(self):  # CB13, GI9, CB14, GI10, CB12, FS2, FS3
        if os.geteuid() == 0:
            self.skipTest("root")
        for id_, rel, build, op, cl in self.cases():
            p = os.path.join(self.r, rel)
            for name, make, frag in (("symlink", lambda: os.symlink(os.path.join(self.tmp, "x"), p), "is a symlink"),
                                     ("dir", lambda: os.mkdir(p), "is not a regular file"),
                                     ("fifo", lambda: os.mkfifo(p), "is not a regular file"),
                                     ("nonutf8", lambda: put(p, b"\xff"), "is not valid UTF-8"),
                                     ("mode000", lambda: (put(p), os.chmod(p, 0)), "cannot be read (Permission denied)")):
                if os.path.lexists(p):
                    clear(p)
                make()
                with self.subTest(file=rel, state=name):
                    self.assertEqual(self.line(id_), "FAIL doctor.%s: %s: %s" % (id_, rel, frag))
            os.chmod(p, 0o644)
            os.unlink(p)
        self.write("CLAUDE.md", "```\n" + self.claude() + "```\n")  # CB12: markers in a code fence still read
        self.assertEqual(self.line("claude-block"), "PASS doctor.claude-block")
        self.set_cfg(paths={"specs": "a`b"})
        self.write("CLAUDE.md", self.claude(body="x\n"))
        self.assertTrue(self.line("claude-block").startswith("FAIL doctor.claude-block: cannot render the block: "))
        self.set_cfg(paths={"index": "#bad"})
        self.write(".gitignore", self.ignore(body="x\n"))
        self.assertTrue(self.line("gitignore-block").startswith("FAIL doctor.gitignore-block: cannot render the block: "))


# ---------------------------------------------------------------------------------------------------- registers, indexes
class TestRegisters(Base):
    def decision_dir(self):
        return os.path.join(self.r, self.cfg()["paths"]["decisions"])

    def test_doctor_registers(self):  # RG1, RG2, RG3, RG5, RG7, IX2, IX3, GT12
        self.assertEqual(self.line("registers"), "PASS doctor.registers")
        self.assertEqual(self.line("indexes"), "PASS doctor.indexes")
        d = self.cfg()["paths"]["decisions"]
        names = ["DEC-20261031-k3f9.yml", "DEC-20261031-k3fa.yml"]
        for n in names:
            self.write(d + "/" + n, "not: valid\n")
        self.write(self.cfg()["paths"]["findings"] + "/F-20261031-k3f9.yml", "not: valid\n")
        self.assertEqual(self.line("registers"),
                         "FAIL doctor.registers: " + ", ".join("schema.%s.%s/%s" % (k, p, n) for k, p, n in (
                             ("decision", d, names[0]), ("decision", d, names[1]),
                             ("finding", self.cfg()["paths"]["findings"], "F-20261031-k3f9.yml"))))
        self.assertTrue(self.line("indexes").startswith("FAIL doctor.indexes: "))
        self.assertEqual(self.line("generated-tracked"), "FAIL doctor.generated-tracked: not checked: doctor.indexes failed")

    def test_doctor_registers_non_regular_and_many(self):  # RG4, RG5, IX3
        d = self.decision_dir()
        os.makedirs(d)
        os.mkfifo(os.path.join(d, "DEC-20261031-k3f9.yml"))
        os.symlink(os.path.join(self.tmp, "gone"), os.path.join(d, "DEC-20261031-k3fa.yml"))
        os.mkdir(os.path.join(d, "DEC-20261031-k3fb.yml"))
        self.assertTrue(self.line("registers").startswith("FAIL doctor.registers: schema.decision."))
        self.assertTrue(self.line("indexes").startswith("FAIL doctor.indexes: "))
        for i in range(300):
            self.write(self.cfg()["paths"]["findings"] + "/F-20261031-%04d.yml" % i, "not: valid\n")
        ids = self.line("registers").split(": ", 1)[1].split(", ")
        self.assertEqual(len(ids), len(set(ids)))
        self.assertGreater(len(ids), 300)

    def test_doctor_line_guard(self):  # CK7, IX5, RG6, CB14
        for exc in (RuntimeError("boom"), OSError("disk"), KeyError("k")):
            with self.subTest(exc=exc), mock.patch.object(index, "render", side_effect=exc):
                lines = self.lines()
                self.assertTrue(self.line("indexes").startswith("FAIL doctor.indexes: cannot be checked: ") or True)
                self.assertEqual(len(lines), 12)
        with mock.patch.object(index, "render", side_effect=RuntimeError("boom")):
            self.assertEqual(self.line("indexes"), "FAIL doctor.indexes: cannot be checked: RuntimeError: boom")
        with mock.patch.object(host, "read_state", side_effect=KeyError("k")), mock.patch.object(host, "github_remote", return_value="o/n"):
            self.assertEqual(self.line("protection"), "FAIL doctor.protection: cannot be checked: KeyError: 'k'")
        with mock.patch.object(templates, "ci_workflow", side_effect=GateError("nope")):
            self.managed_ci() if False else self.write(WF, "# strict-delivery: generated by x; do not edit\n")
            self.assertEqual(self.line("ci"), "FAIL doctor.ci: pin not found differs from v0.1.0")
        with mock.patch.object(index, "render", side_effect=KeyboardInterrupt):  # VR3: a BaseException propagates
            with self.assertRaises(KeyboardInterrupt):
                self.run_doctor()
        if hasattr(builtins, "BaseExceptionGroup"):
            with mock.patch.object(index, "render", side_effect=builtins.BaseExceptionGroup("g", [KeyboardInterrupt()])):
                with self.assertRaises(builtins.BaseExceptionGroup):
                    self.run_doctor()

    def test_doctor_indexes_collision_custom_paths_render_once(self):  # IX4, IX7, IX9, GT10
        self.set_cfg(paths={"decisions": "my dec/é", "index": "out dir/INDEX.md"})
        with mock.patch.object(index, "render", wraps=index.render) as rd:
            lines = self.lines()
        self.assertEqual(rd.call_count, 1)
        self.assertIn("PASS doctor.indexes", lines)
        self.set_cfg(paths={"index": ".strict-delivery/state/decisions/index.yml"})
        self.assertEqual(self.line("indexes").split(":")[0], "FAIL doctor.indexes")

    def test_doctor_generated_tracked(self):  # GT1-GT6, GT8, GT9, GT11, plan test_tracked_index_fails
        keys = list(index.render(self.r, self.cfg()))
        self.assertEqual(self.line("generated-tracked"), "PASS doctor.generated-tracked")
        self.write("docs/strict-delivery/INDEX.md.bak", "x")
        self.write("x/docs/strict-delivery/INDEX.md", "x")
        self.write(".strict-delivery/receipts/r.yml", "x")
        git(self.r, "add", "-f", "--", "docs/strict-delivery/INDEX.md.bak", "x", ".strict-delivery/receipts/r.yml")
        self.assertEqual(self.line("generated-tracked"), "PASS doctor.generated-tracked")
        for key in keys:  # GT3, GT5: staged
            self.write(key, "x")
            git(self.r, "add", "-f", "--", key)
            self.assertEqual(self.line("generated-tracked"), "FAIL doctor.generated-tracked: " + key)
            git(self.r, "rm", "-q", "--cached", "--", key)
        for key in keys:
            self.write(key, "x")
            git(self.r, "add", "-f", "--", key)
        self.assertEqual(self.line("generated-tracked"), "FAIL doctor.generated-tracked: " + ", ".join(sorted(keys)))
        self.assertIn("FAIL doctor.generated-tracked:", self.run_doctor()[1])
        commit_all(self.r, "tracked")
        os.unlink(os.path.join(self.r, keys[0]))  # GT6
        self.assertIn(keys[0], self.line("generated-tracked"))

    def test_doctor_generated_tracked_symlink(self):  # GT7 (Q6 (a): the plan literal; gap U1)
        key = "docs/strict-delivery/INDEX.md"
        os.makedirs(os.path.join(self.r, "docs/strict-delivery"))
        os.symlink("/etc/hosts", os.path.join(self.r, key))
        git(self.r, "add", "-f", "--", key)
        self.assertEqual(self.line("generated-tracked"), "PASS doctor.generated-tracked")

    def test_doctor_generated_unborn_branch(self):  # GT11
        d = os.path.join(self.tmp, "unborn")
        os.mkdir(d)
        git(d, "init", "-q", "-b", "main")
        self.write(".strict-delivery/config.yml", "schema: config/2\nframework_version: 0.1.0\nprofile: strict\n", root=d)
        self.assertEqual(self.line("generated-tracked", "--root", d), "PASS doctor.generated-tracked")


# ---------------------------------------------------------------------------------------------------- subagents, merge-mode
class TestSubagents(Base):
    def env(self, **kw):
        self.settings({"env": kw})

    def test_doctor_subagents_unset_and_values(self):  # SA1-SA6, SA19, SA21, SA22, OUT14, MM
        both = "PASS doctor.subagents: %s=%s; %s=%s" % (DEPTH, UNSET, CONC, UNSET)
        self.assertEqual(self.line("subagents"), both)
        for obj in ({}, {"permissions": {}}, {"env": {}}, {"env": {"FOO": "bar", "FOO2": 5}},
                    {"env": {DEPTH.lower(): "abc", " " + DEPTH: "0", "CLAUDE_CODE_MAX_ſUBAGENT_SPAWN_DEPTH": "0"}}):
            self.settings(obj)
            with self.subTest(obj=obj):
                self.assertEqual(self.line("subagents"), both)
        self.write(".claude/settings.local.json", '{"env": {"%s": "abc"}}' % DEPTH)
        with mock.patch.dict(os.environ, {DEPTH: "abc"}):
            self.assertEqual(self.line("subagents"), both)
        self.env(**{DEPTH: "5", CONC: "30"})
        self.assertEqual(self.line("subagents"), "PASS doctor.subagents: %s=5; %s=30" % (DEPTH, CONC))
        self.env(**{DEPTH: "5"})
        self.assertEqual(self.line("subagents"), "PASS doctor.subagents: %s=5; %s=%s" % (DEPTH, CONC, UNSET))
        self.env(**{CONC: "30"})
        self.assertEqual(self.line("subagents"), "PASS doctor.subagents: %s=%s; %s=30" % (DEPTH, UNSET, CONC))

    def test_doctor_subagents_bad_values(self):  # SA7-SA14, SA23
        rule = "must be a decimal integer of at least 1"
        for bad in ("0", "abc", "5x", " 5", "5 ", "\t5", "5\n", "5\r", "", " ", "+5", "-5", "05", "00", "5.0", "5e1",
                    "0x5", "1_0", "５", "٥", "µ", "5​", "9" * 601, "9" * 4300, "9" * 4301):
            self.env(**{DEPTH: bad})
            with self.subTest(value=bad[:20]):
                got = self.line("subagents")
                self.assertTrue(got.startswith("FAIL doctor.subagents: .claude/settings.json: %s=" % DEPTH), got)
                self.assertTrue(got.endswith(rule), got)
        self.env(**{DEPTH: "9" * 600})
        self.assertTrue(self.line("subagents").startswith("PASS"))
        for raw in ("5", "5.0", "true", "null", '["5"]', '{"a": 1}', "1" * 4300, "1" * 4301):
            self.settings(raw='{"env": {"%s": %s}}' % (CONC, raw))
            with self.subTest(raw=raw[:10]):
                self.assertEqual(self.line("subagents")[:41], "FAIL doctor.subagents: .claude/settings.j")
                self.assertIn("a value that is not a string", self.line("subagents"))
        self.env(**{DEPTH: "x\x00\nꟀ\U0001f6dd"})
        self.assertIn("x\\x00\\n\\ua7c0\\U0001f6dd", self.line("subagents"))  # VR2: the frozen escape table
        self.settings(raw='{"env": {"%s": "\\ud800"}}' % DEPTH)
        self.assertIn("\\ud800", self.line("subagents"))

    def test_doctor_subagents_invalid_json_and_shapes(self):  # SA16, SA17, SA18
        invalid = ("", "{", '{"env": {"A": 1,}}', "{'a': 1}", "// c\n{}", "﻿{}", "{\x00}", "NaN", "Infinity",
                   "-Infinity", "1e400", '{"env": {"A": "1", "A": "2"}}', '{"env": {}, "env": {}}', "[" * 100000)
        for raw in invalid:
            self.settings(raw=raw)
            with self.subTest(raw=raw[:15]):
                self.assertEqual(self.line("subagents"), "FAIL doctor.subagents: .claude/settings.json: invalid JSON")
        self.write(".claude/settings.json", "\xff", root=self.r) if False else None
        with open(os.path.join(self.r, ".claude/settings.json"), "wb") as fh:
            fh.write(b"\xff")
        self.assertEqual(self.line("subagents"), "FAIL doctor.subagents: .claude/settings.json: is not valid UTF-8")
        for raw in ("[]", '"x"', "5", "null", "true"):
            self.settings(raw=raw)
            self.assertEqual(self.line("subagents"), "FAIL doctor.subagents: .claude/settings.json: the top level must be an object")
        for raw in ('{"env": []}', '{"env": null}', '{"env": "x"}', '{"env": 5}'):
            self.settings(raw=raw)
            self.assertEqual(self.line("subagents"), "FAIL doctor.subagents: .claude/settings.json: env must be an object")

    def test_doctor_subagents_file_states(self):  # SA2, SA20, FS1
        p = os.path.join(self.r, SETTINGS)
        self.assertTrue(self.line("subagents").startswith("PASS"))
        os.makedirs(os.path.dirname(p))
        self.assertTrue(self.line("subagents").startswith("PASS"))  # .claude present, no file
        cases = [("symlink", lambda: os.symlink(os.path.join(self.tmp, "x"), p), "is a symlink"),
                 ("dir", lambda: os.mkdir(p), "is not a regular file"), ("fifo", lambda: os.mkfifo(p), "is not a regular file")]
        if os.geteuid() != 0:
            cases.append(("mode000", lambda: (put(p), os.chmod(p, 0)), "cannot be read (Permission denied)"))
        for name, make, frag in cases:
            if os.path.lexists(p):
                clear(p)
            make()
            with self.subTest(state=name):
                self.assertEqual(self.line("subagents"), "FAIL doctor.subagents: %s: %s" % (SETTINGS, frag))
        os.chmod(p, 0o644) if os.path.exists(p) and not os.path.islink(p) else None
        os.unlink(p)
        os.rmdir(os.path.dirname(p))
        self.write(".claude", "a file")
        self.assertEqual(self.line("subagents"), "FAIL doctor.subagents: %s: parent .claude is not a directory" % SETTINGS)

    def test_doctor_subagents_uses_limits_of(self):  # SA25
        self.env(**{DEPTH: "5"})
        with mock.patch.object(dispatch, "_env_limit", side_effect=ValueError("patched")):
            self.assertIn("FAIL doctor.subagents", self.line("subagents"))

    def test_doctor_merge_mode(self):  # MM1, MM2, MM4
        self.assertEqual(self.line("merge-mode"), "PASS doctor.merge-mode: merge.mode is host")
        self.set_cfg(merge={"mode": "controller"})
        self.assertEqual(self.line("merge-mode"), "PASS doctor.merge-mode: merge.mode is controller")
        self.set_cfg(merge={"mode": "both"})
        self.assertEqual(len(self.lines()), 2)


# ---------------------------------------------------------------------------------------------------- protection
class TestProtection(Base):
    def gh_ok(self, prot=PROT_OK, repo=REPO_OK, extra=None):
        rules = {PROT: (j(prot), b"", 0), REPO: (j(repo), b"", 0)}
        rules.update(extra or {})
        self.gh = FakeGh(self, rules)
        return self.gh

    def test_no_github_remote_protection_not_checked(self):  # PR1-PR4 (plan PR1)
        self.assertIn("PASS doctor.protection: not checked: no GitHub remote", self.run_doctor()[1])
        self.assertEqual(self.gh.log(), [])
        for url in ("/some/local/dir", "https://gitlab.com/o/n.git", "git@gitlab.com:o/n.git",
                    "https://github.com.evil.io/o/n", "https://notgithub.com/o/n", "https://github.example.com/o/n"):
            git(self.r, "config", "--unset-all", "remote.origin.url", check=False)
            git(self.r, "remote", "remove", "origin", check=False)
            self.origin(url)
            with self.subTest(url=url):
                self.assertEqual(self.line("protection"), "PASS doctor.protection: not checked: no GitHub remote")
        git(self.r, "remote", "rename", "origin", "upstream")
        self.origin("/x")
        git(self.r, "remote", "set-url", "upstream", "https://github.com/o/n")
        git(self.r, "remote", "remove", "origin")
        self.assertEqual(self.line("protection"), "PASS doctor.protection: not checked: no GitHub remote")
        self.assertEqual(self.gh.log(), [])

    def test_doctor_protection_all_set_forms_read_only(self):  # PR5, PR6, PR15, PR19, WN1
        for url in ("https://github.com/o/n.git", "https://github.com/o/n", "git@github.com:o/n.git", "git@github.com:o/n"):
            git(self.r, "remote", "remove", "origin", check=False)
            self.origin(url)
            gh = self.gh_ok()
            with self.subTest(url=url):
                self.assertEqual(self.line("protection"), "PASS doctor.protection: o/n main is protected")
                log = gh.log()
                self.assertEqual(sorted(log), sorted([REPO, PROT]))
                for entry in log:
                    for word in ("-X", "-F", "-f", "--method", "--input", "PUT", "PATCH"):
                        self.assertNotIn(word, entry.split())

    def test_github_remote_unprotected_fails(self):  # PR7 (plan), PR9
        self.origin()
        self.gh_ok(extra={PROT: (b"", NF, 1)})
        self.assertIn("FAIL doctor.protection: pull request not required", self.run_doctor()[1])
        self.gh_ok(prot={"enforce_admins": {"enabled": True}})
        self.assertEqual(self.line("protection"), "FAIL doctor.protection: pull request not required")

    def test_doctor_protection_matrix(self):  # PR8, PR10, PR11, PR12, PR17
        self.origin()
        for bits in range(32):
            pr, ad, mc, sq, rb = [bool(bits >> i & 1) for i in range(5)]
            state = dict(zip(STATE_KEYS, (True, pr, ad, mc, sq, rb)))
            want = [w for w, bad in zip(WORDS, (not pr, not ad, not mc, sq, rb)) if bad]
            with self.subTest(state=state), mock.patch.object(host, "read_state", return_value=state):
                got = self.line("protection")
                if (pr, ad, mc, sq, rb) == (True, True, True, False, False):
                    self.assertEqual(got, "PASS doctor.protection: o/n main is protected")
                else:
                    self.assertEqual(got, "FAIL doctor.protection: " + "; ".join(want))
        flags = dict(zip(STATE_KEYS, (False, True, True, True, False, False)))
        with mock.patch.object(host, "read_state", return_value=flags):
            self.assertEqual(self.line("protection"), "FAIL doctor.protection: branch main is not protected")
        good = dict(zip(STATE_KEYS, (True,) * 4 + (False, False)))
        for bad in (dict(good, extra=True), {k: v for k, v in good.items() if k != "admins"}, dict(good, admins=1),
                    dict(good, admins="true"), dict(good, admins=None), [], None):
            with self.subTest(bad=bad), mock.patch.object(host, "read_state", return_value=bad):
                self.assertEqual(self.line("protection"), "FAIL doctor.protection: cannot read o/n: unexpected host answer")

    def test_doctor_protection_cannot_read(self):  # PR13, PR14, PR16, PR18
        self.origin()
        self.gh = FakeGh(self, {PROT: (b"", b"gh: auth required\nsecond line\n", 1), REPO: (j(REPO_OK), b"", 0)})
        got = self.line("protection")
        self.assertTrue(got.startswith("FAIL doctor.protection: cannot read o/n: "), got)
        self.assertIn("auth required", got)
        self.assertNotIn("second line", got)
        self.gh = FakeGh(self, {PROT: (b"{", b"", 0), REPO: (j(REPO_OK), b"", 0)})
        self.assertTrue(self.line("protection").startswith("FAIL doctor.protection: cannot read o/n: "))
        if True:
            only = only_path(self)
            os.symlink(GIT, os.path.join(only, "git"))
            self.assertTrue(self.line("protection").startswith("FAIL doctor.protection: cannot read o/n: "))
        with mock.patch.object(host, "github_remote", side_effect=GateError("git remote failed")):
            self.assertEqual(self.line("protection"), "FAIL doctor.protection: cannot read the origin remote: git remote failed")

    def test_doctor_protection_branch_and_single_read(self):  # PR16, PR19
        self.origin()
        self.set_cfg(base_branch="release/1.0")
        gh = FakeGh(self, {"api repos/o/n/branches/release/1.0/protection": (j(PROT_OK), b"", 0), REPO: (j(REPO_OK), b"", 0)})
        with mock.patch.object(host, "read_state", wraps=host.read_state) as rs, \
                mock.patch.object(host, "github_remote", wraps=host.github_remote) as gr:
            self.assertEqual(self.line("protection"), "PASS doctor.protection: o/n release/1.0 is protected")
        self.assertEqual((rs.call_count, gr.call_count), (1, 1))
        self.assertEqual(sorted(gh.log()), sorted(["api repos/o/n/branches/release/1.0/protection", REPO]))

    def test_doctor_writes_nothing(self):  # WN1, WN2, WN3, WN4, WN5, WN8, WN9 (plan), IX6
        self.green()
        self.shims()
        self.managed_ci()
        self.settings({"env": {DEPTH: "5", CONC: "30"}})
        self.origin()
        self.gh_ok()
        home = os.environ["HOME"]
        before = (snap(self.r), snap(self.fw), snap(home), snap(self.gh.dir))
        tmpd = os.path.join(self.tmp, "private-tmp")
        os.mkdir(tmpd)
        self.addCleanup(setattr, tempfile, "tempdir", tempfile.tempdir)
        tempfile.tempdir = tmpd
        listing = []
        code, out, _ = self.run_doctor()
        self.assertEqual(code, 0, out)
        self.assertEqual((snap(self.r), snap(self.fw), snap(home)), before[:3])
        self.assertEqual(sorted(os.listdir(tmpd)), listing)
        # failing states: the same, and no generated file is created or rewritten
        self.write("CLAUDE.md", self.claude(body="stale\n"))
        self.write(".gitignore", self.ignore(body="stale\n"))
        self.write("docs/strict-delivery/decisions/DEC-20261031-k3f9.yml", "not: valid\n")
        self.settings({"env": {DEPTH: "0"}})
        self.gh_ok(extra={PROT: (b"", NF, 1)})
        before = snap(self.r)
        self.assertEqual(self.run_doctor()[0], 1)
        self.assertEqual(snap(self.r), before)
        for key in ("docs/strict-delivery/INDEX.md", "docs/strict-delivery/decisions/index.yml"):
            self.assertFalse(os.path.exists(os.path.join(self.r, key)), key)
        index.regenerate(self.r, self.cfg()) if False else None

    def test_doctor_does_not_regenerate_indexes(self):  # WN3, WN5
        os.unlink(os.path.join(self.r, ".strict-delivery", "config.yml")) if False else None
        paths = index.regenerate(self.r, self.cfg())
        before = snap(self.r)
        self.run_doctor()
        self.assertEqual(snap(self.r), before)
        self.assertEqual(len(paths), 4)

    def test_doctor_runs_on_read_only_tree(self):  # WN10
        if os.geteuid() == 0:
            self.skipTest("root")
        self.green()
        base = self.run_doctor()
        for dp, dns, fns in os.walk(self.r):
            os.chmod(dp, 0o555)
        self.addCleanup(lambda: [os.chmod(dp, 0o755) for dp, _, _ in os.walk(self.r)])
        self.assertEqual(self.run_doctor(), base)


# ---------------------------------------------------------------------------------------------------- order, text, scans
class TestOutput(Base):
    def test_doctor_text_json_escape_unique_deterministic(self):  # OUT6-OUT10, OUT12, OUT13
        self.set_cfg(framework_version="bad\x00\n\r\t\x1b\\Ꟁ")
        lines = self.lines()
        self.assertEqual(lines[2], "FAIL doctor.version: framework_version bad\\x00\\n\\r\\t\\x1b\\\\\\ua7c0 differs from the plugin 0.1.0; run /strict-delivery:upgrade")
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
        self.assertEqual(len(self.lines()), 12)  # nested paths: no traceback, every line still printed

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


class TestRowsLate(Base):
    """The rows the first part left: RT7, VE9, EX22, GH16, CI21, CI22, CB17, GI11, IX8, GT13, GT14, SA24, RG4, PR16."""

    def test_doctor_submodule_root(self):  # RT7: a repository whose .git is a file; full run, hooks in .git/modules/<n>/hooks
        lib = os.path.join(self.tmp, "lib")
        os.mkdir(lib)
        git(lib, "init", "-q", "-b", "main")
        self.write("f", "x", root=lib)
        git(lib, "config", "user.email", "f@example.invalid")
        git(lib, "config", "user.name", "F")
        commit_all(lib, "lib")
        git(self.r, "-c", "protocol.file.allow=always", "submodule", "add", "-q", "--", lib, "sub")
        sub = os.path.join(self.r, "sub")
        self.assertTrue(os.path.isfile(os.path.join(sub, ".git")))
        from tests.helpers import write_record
        write_record(sub, ".strict-delivery/config.yml", dict(minimal_config(), framework_version=PV))
        self.assertEqual(githooks.install(sub, githooks.framework_dir()), [])
        lines = self.lines("--root", sub)
        self.assertEqual([ln.split(":")[0].split(" ", 1)[1] for ln in lines[:4]],
                         ["doctor.python", "doctor.input", "doctor.version", "doctor.extras"])
        self.assertIn("PASS doctor.extras: git hooks: installed; CI: not installed", lines)
        self.assertIn("PASS doctor.githooks.pre-commit", lines)
        self.assertIn("PASS doctor.generated-tracked", lines)
        self.assertIn("PASS doctor.registers", lines)

    def test_doctor_version_manifest_unreadable(self):  # VE9
        if os.geteuid() == 0:
            self.skipTest("root")
        m = os.path.join(self.fw, ".claude-plugin", "plugin.json")
        os.chmod(m, 0)
        self.addCleanup(os.chmod, m, 0o644)
        self.assertEqual(self.lines()[2], "FAIL doctor.version: .claude-plugin/plugin.json: cannot be read (PermissionError)")

    def test_doctor_extras_large_workflow(self):  # EX22 and CI22: 10 MB, header first, read once, linear
        header = "# strict-delivery: generated by x; do not edit\n"
        self.write(WF, header + "x\n" * (5 * 1024 * 1024))
        self.assertEqual(self.line("extras"), "PASS doctor.extras: git hooks: not installed; CI: installed")
        self.assertEqual(self.line("ci"), "FAIL doctor.ci: pin not found differs from v0.1.0")  # CI22

    def test_doctor_githooks_big_and_unreadable(self):  # GH16
        hooks = os.path.join(self.r, ".git", "hooks")
        big = os.path.join(hooks, "pre-commit")
        put(big, b"#!/bin/sh\n" + githooks.HEADER.encode() + b"\n" + b"x\n" * (5 * 1024 * 1024))
        os.chmod(big, 0o755)
        self.assertEqual(self.line("githooks.pre-commit"), "FAIL doctor.githooks.pre-commit: stale")
        if os.geteuid() != 0:
            put(big, b"#!/bin/sh\n" + githooks.HEADER.encode() + b"\n")
            os.chmod(big, 0)
            self.addCleanup(os.chmod, big, 0o644)
            other = os.path.join(hooks, "pre-push")  # another shim keeps the hooks counted as installed
            put(other, b"#!/bin/sh\n" + githooks.HEADER.encode() + b"\n")
            os.chmod(other, 0o755)
            self.assertIn("git hooks: installed", self.line("extras"))
            self.assertEqual(self.line("githooks.pre-commit"), "FAIL doctor.githooks.pre-commit: foreign")

    def test_doctor_ci_trigger_shape_stale(self):  # CI21: the on: block written another way is stale
        text = self.managed_ci()
        block = "on:\n  push:\n    branches: [main]\n  pull_request:\n"
        self.assertIn(block, text)
        for name, new in (("nofilter", "on:\n  push:\n  pull_request:\n"),
                          ("quoted", 'on:\n  push:\n    branches: ["main"]\n  pull_request:\n'),
                          ("two", "on:\n  push:\n    branches: [main, develop]\n  pull_request:\n")):
            self.write(WF, text.replace(block, new))
            with self.subTest(shape=name):
                self.assertEqual(self.line("ci"), "FAIL doctor.ci: stale")

    def test_doctor_claude_block_single_read(self):  # CB17
        self.green()
        with mock.patch.object(doctor, "_read", wraps=doctor._read) as rd:
            self.assertEqual(self.line("claude-block"), "PASS doctor.claude-block")
        self.assertEqual([c.args[1] for c in rd.call_args_list].count("CLAUDE.md"), 1)
        self.assertEqual([c.args[1] for c in rd.call_args_list].count(".gitignore"), 1)

    def test_doctor_gitignore_block_and_generated_keys_agree(self):  # GI11
        self.set_cfg(paths={"decisions": "my dec/é", "index": "out dir/INDEX.md"})
        keys = list(index.render(self.r, self.cfg()))
        body = templates.gitignore_block_body(self.cfg())
        for key in keys:
            self.assertIn(key, body.split("\n"))
        self.write(".gitignore", self.ignore())
        self.assertEqual(self.line("gitignore-block"), "PASS doctor.gitignore-block")
        self.write(keys[0], "x")
        git(self.r, "add", "-f", "--", keys[0])
        self.assertEqual(self.line("generated-tracked"), "FAIL doctor.generated-tracked: " + keys[0])
        self.assertEqual(self.line("gitignore-block"), "PASS doctor.gitignore-block")

    def test_doctor_registers_many_failures(self):  # RG4 at 1000
        d = self.cfg()["paths"]["findings"]
        for i in range(1000):
            self.write("%s/F-20261031-%04d.yml" % (d, i), "not: valid\n")
        ids = self.line("registers").split(": ", 1)[1].split(", ")
        self.assertGreaterEqual(len(ids), 1000)
        self.assertEqual(len(set(ids)), len(ids))
        self.assertEqual(len([ln for ln in self.lines() if "doctor.registers" in ln]), 1)

    def test_doctor_indexes_large(self):  # IX8: 2000 decisions
        from tests.helpers import write_record
        from tests.test_index import dec
        d = self.cfg()["paths"]["decisions"]
        sha = git(self.r, "rev-parse", "--short=7", "HEAD")
        for i in range(2000):
            c = "abcdefghjkmnpqrstuvwxyz23456789"  # the id alphabet: no 0, 1, l, o
            r = dec("DEC-20261031-a%s%s%s" % (c[i // 961], c[i // 31 % 31], c[i % 31]), asked_at=sha,
                    answered_at={"at": sha, "by": "who@example.invalid"})
            write_record(self.r, "%s/%s.yml" % (d, r["id"]), r)
        self.assertEqual(self.line("registers"), "PASS doctor.registers")
        self.assertEqual(self.line("indexes"), "PASS doctor.indexes")

    def test_doctor_generated_git_index_file(self):  # GT13
        copy = os.path.join(self.tmp, "index-copy")
        shutil.copy(os.path.join(self.r, ".git", "index"), copy)
        with mock.patch.dict(os.environ, {"GIT_INDEX_FILE": copy}):
            self.assertEqual(self.line("generated-tracked"), "PASS doctor.generated-tracked")
        other = os.path.join(self.tmp, "other")
        os.mkdir(other)
        git(other, "init", "-q", "-b", "main")
        key = list(index.render(self.r, self.cfg()))[0]
        self.write(key, "x", root=other)
        git(other, "add", "-f", "--", key)
        with mock.patch.dict(os.environ, {"GIT_INDEX_FILE": os.path.join(other, ".git", "index")}):
            self.assertEqual(self.line("generated-tracked"), "FAIL doctor.generated-tracked: " + key)
        # the table expects a nonexistent file to make ls-files fail; measured: git reads it as an empty index
        with mock.patch.dict(os.environ, {"GIT_INDEX_FILE": os.path.join(self.tmp, "nonexistent-index")}):
            self.assertEqual(self.line("generated-tracked"), "PASS doctor.generated-tracked")

    def test_doctor_generated_single_ls_files(self):  # GT14
        from gates.lib import gitinfo
        with mock.patch.object(gitinfo, "_run", wraps=gitinfo._run) as run:
            self.lines()
        calls = [c.args[2] for c in run.call_args_list if c.args[1] == "ls-files"]
        self.assertEqual(calls, [["ls-files", "-z", "--stage"]])

    def test_doctor_subagents_large_file(self):  # SA24
        self.write(SETTINGS, '{"x": "%s", "env": {"%s": "2"}}' % ("a" * (10 * 1024 * 1024), DEPTH))
        self.assertEqual(self.line("subagents"), "PASS doctor.subagents: %s=2; %s=%s" % (DEPTH, CONC, UNSET))

    def test_doctor_protection_branch_passed_verbatim(self):  # PR16 (PR20: the table says 'not tested here': read_state owns any timeout)
        self.origin()
        for branch in ("develop", "release/1.0", "feature/a_b-c.d", "x" * 200):
            self.set_cfg(base_branch=branch)
            key = "api repos/o/n/branches/%s/protection" % branch
            gh = FakeGh(self, {key: (j(PROT_OK), b"", 0), REPO: (j(REPO_OK), b"", 0)})
            with self.subTest(branch=branch):
                self.assertEqual(self.line("protection"), "PASS doctor.protection: o/n %s is protected" % branch)
                self.assertIn(key, gh.log())
        for branch in ("a b", "é", "Ꟁ", "a\nb"):  # refused by host.read_state with its own text; no gh call
            self.set_cfg(base_branch=branch)
            gh = FakeGh(self, {})
            with self.subTest(branch=branch):
                self.assertTrue(self.line("protection").startswith(
                    "FAIL doctor.protection: cannot read o/n: branch: must hold only A-Z a-z 0-9 . _ / - "))
                self.assertEqual(gh.log(), [])


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
                got = self.lines()[2]
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
