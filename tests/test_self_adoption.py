"""Tests of Task 2b.3 (self-adoption: the CI workflow, the config keys, the hooks, `run_all` as the commit gate;
input-domain table task-2b.3-domain.md: rows G (config), H (hooks and copies), K3 here; the workflow rows W and the
PC1 rows K1 and K2 are added with the workflow, in the second commit of the task).

The tests read this checkout's real config and run the real ``python3 -m gates run_all``, ``githooks install`` and
``git commit`` in disposable clones under a temporary directory (a clone is of this checkout's working files: its
tracked and untracked files are copied over the clone and committed there, so a test run before this task's commit
reads the files under test). Nothing here installs a hook in this checkout's own hooks directory. Expected values are
written by hand from the plan (P:1806-1865) and the table."""
import contextlib
import io
import os
import shutil
import subprocess
import sys
import unittest

from gates import __main__ as gates_main
from gates.lib import config, yamlsub
from gates.tools import githooks
from tests.helpers import GitIsolatedTestCase, commit_all, git, make_repo

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = ".strict-delivery/config.yml"
BASE = "b7afa88"  # Task 2b.2's reviewed head: the config at the base holds exactly three keys
COMMANDS_TEST = "python3 -m unittest discover -s tests -t . && python3.13 -m unittest discover -s tests -t ."
NESTED = "SD_SELF_ADOPTION_NESTED"  # set in the suite run inside a clone: the clone tests do not recurse
UNSTAGED = "tracked file has unstaged changes; stage it or stash it, so the gates read the tree being committed"
SHALLOW = "FAIL %s.input: git merge-base failed (exit 1)\n"


def read_text(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def listing(path):
    """Every entry of a directory with its size and mode, so a change to any file shows."""
    out = []
    for name in sorted(os.listdir(path)):
        st = os.lstat(os.path.join(path, name))
        out.append((name, st.st_size, st.st_mode, st.st_mtime_ns))
    return out


def real_hooks_dir():
    """The shared hooks directory of this checkout (read only here)."""
    out = subprocess.run(["git", "-C", REPO, "rev-parse", "--git-common-dir"], stdout=subprocess.PIPE, check=True)
    common = out.stdout.decode("utf-8").strip()
    if not os.path.isabs(common):
        common = os.path.join(REPO, common)
    return os.path.join(os.path.realpath(common), "hooks")


class ConfigTest(GitIsolatedTestCase):
    def load_raw(self):
        return yamlsub.load(os.path.join(REPO, CONFIG), CONFIG)

    def test_config_commands_test(self):  # G1, G4
        self.assertEqual(self.load_raw()["commands"], {"test": COMMANDS_TEST})
        cfg = config.load(REPO)  # G4: the loader accepts the file
        self.assertEqual(cfg["commands"], {"test": COMMANDS_TEST})
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = gates_main.main(["check", "schema", "--root", REPO])
        self.assertEqual(code, 0, out.getvalue())
        self.assertNotIn("FAIL", out.getvalue())

    def test_config_top_tier(self):  # G2
        raw = self.load_raw()
        self.assertEqual(raw["top_tier_roles"], ["final_verifier", "exception_reviewer"])
        self.assertEqual(config.load(REPO)["top_tier_roles"], ["final_verifier", "exception_reviewer"])
        self.assertNotIn("tier4", config.load(REPO)["models"]["tiers"])
        self.assertNotIn("tier4", raw.get("models", {}).get("tiers", {}))
        self.assertNotIn("top_tier_fallback", raw)

    def test_config_only_two_keys_added(self):  # G3
        p = subprocess.run(["git", "-C", REPO, "show", "%s:%s" % (BASE, CONFIG)], stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE)
        self.assertEqual(p.returncode, 0, p.stderr.decode("utf-8", "replace"))
        base_path = os.path.join(self.tmp, "base.yml")
        with open(base_path, "wb") as fh:
            fh.write(p.stdout)
        base = yamlsub.load(base_path, CONFIG)
        self.assertEqual(base, {"schema": "config/1", "framework_version": "0.0.0", "profile": "strict"})
        current = dict(self.load_raw())
        self.assertEqual(sorted(set(current) - set(base)), ["commands", "top_tier_roles"])
        for key in ("commands", "top_tier_roles"):
            del current[key]
        self.assertEqual(current, base)
        # append only: the base's three lines open the file unchanged, the two keys follow
        text = read_text(os.path.join(REPO, CONFIG))
        self.assertTrue(text.startswith(p.stdout.decode("utf-8")))


class CopyCase(GitIsolatedTestCase):
    """Disposable clones of this checkout, one real git run at a time."""

    def setUp(self):
        super().setUp()
        self.bin = os.path.join(self.tmp, "bin")
        os.mkdir(self.bin)
        os.symlink(sys.executable, os.path.join(self.bin, "python3"))  # the shim's python3 is this interpreter

    def env(self):
        e = dict(os.environ)
        e["LC_ALL"] = "C"
        e["PATH"] = self.bin + os.pathsep + e["PATH"]
        return e

    def run_proc(self, argv, cwd):
        p = subprocess.run(argv, cwd=cwd, env=self.env(), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT)
        return p.returncode, p.stdout.decode("utf-8", "replace")

    def clone_copy(self, name, main):
        """``git clone`` of this checkout, its working files copied over and committed, HEAD detached; ``main`` True
        gives a local ``main`` at HEAD, False leaves no local ``main``."""
        dst = os.path.join(self.tmp, name)
        git(self.tmp, "clone", "-q", REPO, dst)
        git(dst, "config", "user.email", "fixture@example.invalid")
        git(dst, "config", "user.name", "Fixture")
        git(dst, "config", "commit.gpgsign", "false")
        names = git(REPO, "ls-files", "-z", "--cached", "--others", "--exclude-standard").split("\0")
        gone = set(git(REPO, "ls-files", "-z", "--deleted").split("\0"))
        for rel in names:
            if rel == "" or rel in gone:
                continue
            src = os.path.join(REPO, rel)
            if not os.path.isfile(src):
                continue
            to = os.path.join(dst, rel)
            os.makedirs(os.path.dirname(to), exist_ok=True)
            shutil.copyfile(src, to)
            shutil.copymode(src, to)
        for rel in sorted(gone - {""}):
            git(dst, "rm", "-q", "--cached", "--ignore-unmatch", "--", rel)
            if os.path.exists(os.path.join(dst, rel)):
                os.unlink(os.path.join(dst, rel))
        commit_all(dst, "working files")
        git(dst, "checkout", "-q", "--detach")
        git(dst, "branch", "-D", "main", check=False)
        if main:
            git(dst, "branch", "main", "HEAD")
        return dst

    def has_local_main(self, root):
        return subprocess.run(["git", "-C", root, "rev-parse", "--verify", "-q", "refs/heads/main"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0

    def gates_run_all(self, root, *args):
        return self.run_proc([sys.executable, "-m", "gates", "run_all", "--root", root] + list(args), cwd=root)


class CopyTest(CopyCase):
    def test_hooks_in_a_disposable_clone(self):  # H1, H2, H3 (the automated form of plan Step 4)
        clone = self.clone_copy("hooks", main=True)
        path = os.path.join(clone, CONFIG)
        text = read_text(path)
        self.assertEqual(text.count(COMMANDS_TEST), 1)
        with open(path, "w", encoding="utf-8") as fh:  # H2: a fast command, so the suite does not recurse
            fh.write(text.replace(COMMANDS_TEST, "\"true\""))
        commit_all(clone, "fast commands.test")
        real = real_hooks_dir()
        before = listing(real)
        self.assertEqual(githooks.install(clone, REPO), [])
        self.assertEqual(listing(real), before)  # H3: this checkout's hooks directory is untouched
        for name in ("pre-commit", "pre-push"):
            self.assertTrue(os.path.isfile(os.path.join(clone, ".git", "hooks", name)))
        head = git(clone, "rev-parse", "HEAD")
        # the clean commit passes: run_all's lines, then the test command's
        with open(os.path.join(clone, "clean.txt"), "w", encoding="utf-8") as fh:
            fh.write("clean\n")
        git(clone, "add", "clean.txt")
        code, out = self.run_proc(["git", "commit", "-q", "-m", "clean"], cwd=clone)
        self.assertEqual(code, 0, out)
        lines = out.splitlines()
        self.assertTrue(lines and all(ln.startswith("PASS ") for ln in lines), out)
        self.assertIn("PASS schema.config", lines)
        self.assertIn("PASS cites.landed", lines)
        self.assertEqual(lines[-1], "PASS githook.test")
        self.assertNotEqual(git(clone, "rev-parse", "HEAD"), head)
        # a staged new file and an unstaged change to a tracked file: refused before any gate
        head = git(clone, "rev-parse", "HEAD")
        with open(os.path.join(clone, "staged.txt"), "w", encoding="utf-8") as fh:
            fh.write("staged\n")
        git(clone, "add", "staged.txt")
        with open(os.path.join(clone, "clean.txt"), "a", encoding="utf-8") as fh:
            fh.write("unstaged\n")
        code, out = self.run_proc(["git", "commit", "-q", "-m", "unstaged"], cwd=clone)
        self.assertEqual(code, 1, out)
        self.assertEqual(out, "FAIL githook.unstaged: clean.txt: %s\n" % UNSTAGED)
        self.assertEqual(git(clone, "rev-parse", "HEAD"), head)
        # staging the file lets the same commit through
        git(clone, "add", "clean.txt")
        code, out = self.run_proc(["git", "commit", "-q", "-m", "staged"], cwd=clone)
        self.assertEqual(code, 0, out)
        self.assertEqual(self.run_proc([sys.executable, "-m", "gates", "githooks", "status", "--root", clone],
                                       cwd=REPO),
                         (0, "PASS githooks.pre-commit\nPASS githooks.pre-push\n"))

    def test_shim_fails_closed_when_framework_lacks_githook(self):  # H4
        added = git(REPO, "log", "--diff-filter=A", "--format=%H", "--", "gates/tools/githooks.py").split()
        self.assertEqual(len(added), 1, added)  # Task 2b.2 added the module once
        old = os.path.join(self.tmp, "old")
        git(self.tmp, "clone", "-q", "--no-checkout", REPO, old)
        git(old, "checkout", "-q", "--detach", added[0] + "^")
        self.assertFalse(os.path.exists(os.path.join(old, "gates", "tools", "githooks.py")))
        root = make_repo(os.path.join(self.work), None)
        self.assertEqual(githooks.install(root, old), [])  # the shim names the old framework checkout
        head = git(root, "rev-parse", "HEAD")
        with open(os.path.join(root, "f.txt"), "w", encoding="utf-8") as fh:
            fh.write("x\n")
        git(root, "add", "f.txt")
        code, out = self.run_proc(["git", "commit", "-q", "-m", "x"], cwd=root)
        self.assertNotEqual(code, 0, out)  # refused, never passed silently
        self.assertEqual(git(root, "rev-parse", "HEAD"), head)
        self.assertIn("usage: python3 -m gates", out)

    def test_run_all_passes_on_a_copy_with_main(self):  # H5 (F-B2p-3)
        clone = self.clone_copy("copy", main=True)
        self.assertTrue(self.has_local_main(clone))
        code, out = self.gates_run_all(clone)
        self.assertEqual(code, 0, out)
        self.assertNotIn("FAIL", out)

    def test_suite_needs_no_local_main(self):  # H6 (F-B2p-3)
        if os.environ.get(NESTED):
            # inside the clone below: the clone really has no local main; the nested run does not recurse
            self.assertFalse(self.has_local_main(REPO))
            return
        clone = self.clone_copy("nomain", main=False)
        self.assertFalse(self.has_local_main(clone))
        env = self.env()
        env[NESTED] = "1"
        p = subprocess.run([sys.executable, "-m", "unittest", "tests.test_run_all", "tests.test_self_adoption"],
                           cwd=clone, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT)
        self.assertEqual(p.returncode, 0, p.stdout.decode("utf-8", "replace")[-3000:])

    def test_run_all_shallow_clone_fails_closed(self):  # H7
        full = self.clone_copy("full", main=True)
        commit_all(full, "ahead of main")  # HEAD one commit past main: a shallow history has no merge base
        deep = os.path.join(self.tmp, "deep")
        git(self.tmp, "clone", "-q", "--no-single-branch", "file://" + full, deep)
        code, out = self.gates_run_all(deep, "--base", "origin/main")
        self.assertEqual(code, 0, out)  # the control: a full clone passes
        shallow = os.path.join(self.tmp, "shallow")
        git(self.tmp, "clone", "-q", "--depth", "1", "--no-single-branch", "file://" + full, shallow)
        self.assertEqual(git(shallow, "rev-parse", "--is-shallow-repository"), "true")
        code, out = self.gates_run_all(shallow, "--base", "origin/main")
        self.assertEqual(code, 1, out)
        lines = out.splitlines(True)
        for gate in ("register", "decisions", "claims"):  # measured 2026-11-17: the three base gates, in this order
            self.assertIn(SHALLOW % gate, lines)
        self.assertEqual([ln for ln in lines if ln.startswith("FAIL")],
                         [SHALLOW % g for g in ("register", "decisions", "claims")])

    def test_no_exception_group_in_task_files(self):  # K3: the files of this task use no exception group
        word = "Exception" + "Group"
        for rel in (CONFIG, "tests/test_self_adoption.py"):
            self.assertNotIn(word, read_text(os.path.join(REPO, rel)), rel)


if __name__ == "__main__":
    unittest.main()
