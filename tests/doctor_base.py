"""Shared fixtures of the doctor tests (Task 4d.3): ``Base`` and its helpers, split out of tests/test_doctor.py."""
import contextlib
import hashlib
import io
import json
import os
import shutil
import stat
from unittest import mock

from gates.lib import config, plugin, templates
from gates.tools import doctor, githooks
from tests.helpers import git, make_repo, minimal_config, GitIsolatedTestCase
from tests.test_host import FakeGh

PV = "0.1.0"
GIT = shutil.which("git")
SHA40 = "a" * 40
SETTINGS = ".claude/settings.json"
WF = ".github/workflows/strict-delivery.yml"
DEPTH = "CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH"
CONC = "CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS"
UNSET = "unset (Claude Code default)"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTEXT = ".strict-delivery/context.yml"
CONTEXT_OK = b"schema: context/1\n"  # hand-written valid context/1 row (plan :5102; gates/schemas/context.yml)
ROOT_ID = ["doctor.python", "doctor.input", "doctor.context", "doctor.version", "doctor.extras", "doctor.claude-block",
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
        put(os.path.join(self.r, CONTEXT), CONTEXT_OK)  # an initialised repository holds a valid context.yml (Amendment C)

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
