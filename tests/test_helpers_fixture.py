"""Tests of Task CI2 (test-suite speed): the per-process template behind ``tests.helpers.make_repo`` (input-domain table
task-CI2-domain.md rows F1-F10, K1-K3, H1-H7) and the optional-locks default of ``helpers.git`` with the ``.git`` mtime
and index oracles (rows L1, L2).

Expected values are built here with raw ``git`` commands (an oracle independent of ``helpers``): the same commands the
slow path ran before this task, never a second call of the code under test."""
import ast
import collections
import contextlib
import hashlib
import importlib
import inspect
import os
import random
import re
import stat
import subprocess
import sys
import tempfile
import threading
import types
import unittest
from unittest import mock

from tests import helpers
from tests.helpers import GitIsolatedTestCase, git, make_repo, minimal_config

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MINIMAL_TEXT = "schema: config/2\nframework_version: 0.0.0\nprofile: strict\n"
# The second committed file of every fixture, as main's make_repo writes it (14b518a, tests/helpers.py: the line
# `write_record(tmp, ".strict-delivery/context.yml", {"schema": "context/1"})  # the gate_context producer makes this file
# required (Rq-5-2)` before `commit_all`; docstring "with the config and a minimal context.yml committed"): written here as
# raw bytes, an oracle independent of ``helpers.emit``.
CONTEXT_TEXT = "schema: context/1\n"
RAW_ENV = {
    "GIT_AUTHOR_NAME": "Fixture Author", "GIT_AUTHOR_EMAIL": "author@example.invalid",
    "GIT_AUTHOR_DATE": "2026-01-01T00:00:00+0000", "GIT_COMMITTER_NAME": "Fixture Committer",
    "GIT_COMMITTER_EMAIL": "committer@example.invalid", "GIT_COMMITTER_DATE": "2026-01-01T00:00:00+0000",
    "LC_ALL": "C",
}


def raw(root, *args, optional_locks=True):
    """Plain git, no helper: returns (returncode, stdout, stderr text)."""
    env = dict(os.environ)
    env.update(RAW_ENV)
    if not optional_locks:
        env["GIT_OPTIONAL_LOCKS"] = "0"
    p = subprocess.run(["git", "-C", root] + list(args), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return p.returncode, p.stdout.decode("utf-8", "replace").strip(), p.stderr.decode("utf-8", "replace")


def rawok(root, *args):
    rc, out, err = raw(root, *args)
    if rc != 0:
        raise AssertionError("raw git %s failed: %s" % (" ".join(args), err))
    return out


def slow_build(root, text=MINIMAL_TEXT):
    """What ``make_repo`` built before the template: init, five config lines, the config file and main's minimal
    context file, add, commit."""
    rawok(root, "init", "-q", "-b", "main")
    for k, v in (("user.email", "fixture@example.invalid"), ("user.name", "Fixture"), ("commit.gpgsign", "false"),
                 ("maintenance.auto", "false"), ("gc.auto", "0")):
        rawok(root, "config", k, v)
    path = os.path.join(root, ".strict-delivery", "config.yml")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)
    with open(os.path.join(root, ".strict-delivery", "context.yml"), "w", encoding="utf-8", newline="") as fh:
        fh.write(CONTEXT_TEXT)
    rawok(root, "add", "-A")
    rawok(root, "commit", "-q", "--allow-empty", "-m", "fixture")
    return root


def facts(root):
    """Everything the equivalence rows compare: head, branch, tracked paths with blob ids, local config, status, fsck,
    the bytes of the tracked files."""
    tracked = rawok(root, "ls-tree", "-r", "-z", "HEAD")
    paths = [ln.split("\t", 1)[1] for ln in tracked.split("\0") if ln]
    data = {}
    for rel in paths:
        with open(os.path.join(root, rel), "rb") as fh:
            data[rel] = fh.read()
    cfg = rawok(root, "config", "--local", "--list")
    rc, fsck, ferr = raw(root, "fsck", "--strict")
    return {
        "head": rawok(root, "rev-parse", "HEAD"), "branch": rawok(root, "symbolic-ref", "HEAD"),
        "tracked": tracked, "bytes": data, "config": cfg,
        "status": rawok(root, "status", "--porcelain", "--untracked-files=all"),
        "fsck": (rc, fsck, ferr), "log": rawok(root, "log", "--format=%H %an <%ae> %cn <%ce> %at %ct %s"),
    }


def tree_state(top):
    """Relative path -> (kind, mode, sha256 of bytes or link target) of every entry under ``top`` (mtimes excluded)."""
    out = {}
    for d, dirs, files in os.walk(top):
        for n in dirs + files:
            p = os.path.join(d, n)
            st = os.lstat(p)
            if stat.S_ISLNK(st.st_mode):
                body = os.readlink(p)
            elif stat.S_ISREG(st.st_mode):
                with open(p, "rb") as fh:
                    body = hashlib.sha256(fh.read()).hexdigest()
            else:
                body = None
            out[os.path.relpath(p, top)] = (stat.S_IFMT(st.st_mode), stat.S_IMODE(st.st_mode), body)
    return out


def index_state(root):
    path = os.path.join(root, ".git", "index")
    with open(path, "rb") as fh:
        return fh.read(), os.stat(path).st_mtime_ns


class Base(GitIsolatedTestCase):
    @staticmethod
    def write(d, rel, data):
        p = os.path.join(d, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as fh:
            fh.write(data)

    def fresh(self, name):
        d = self.inside(os.path.join(self.tmp, name))  # checked before it is created: a name like ".." fails the test
        os.mkdir(d)
        return d

    def inside(self, path):
        """SAFETY (rows D2, D3, E4; F-20261126-djav): returns ``path`` unchanged when its real path equals or lies below
        the real path of this test's own directory (``self.tmp``, which holds every ``self.sandbox()`` box), else fails the
        test with a message that starts ``inside:`` before any guard or write sees the path. ``path`` is exactly ``str``
        (anything else is a ``TypeError``, before any filesystem call) and absolute (a relative path depends on the
        working directory). Only ``realpath`` is called, which looks at links and never opens, creates or writes the
        path. The comparison is case-folded, as ``helpers._overlaps`` compares (chosen: the pair-matrix test hands the
        guards the case-folded spelling of a path of its sandbox, which must reach the guard; on a case-insensitive file
        system that spelling is the same directory, on a case-sensitive one it names nothing that exists). It is not a
        lock: a component swapped for a link after the check is seen by the next call only, which is why the call
        stands in the argument of the guard call itself."""
        if type(path) is not str:
            raise TypeError("inside: path must be exactly str, not %s" % type(path).__name__)
        if "\0" in path:  # not every interpreter's realpath refuses it: one named verdict on both
            self.fail("inside: %r holds a NUL" % (path,))
        try:
            os.fsencode(path)
        except UnicodeEncodeError:  # a lone surrogate no file system name can hold
            self.fail("inside: %r cannot be encoded as a file system name" % (path,))
        if not os.path.isabs(path):
            self.fail("inside: %r is not an absolute path" % (path,))
        real, home = os.path.realpath(path), os.path.realpath(self.tmp)  # lstat and readlink only; never raises here
        folded, top = real.casefold(), home.casefold().rstrip(os.sep)  # only the real path "/" ends in a separator
        if folded != top and not folded.startswith(top + os.sep):
            self.fail("inside: %r is not inside this test's directory %r" % (path, home))
        return path

    def sandbox(self):
        """SAFETY (a test of a refusal guard must never reach a real shared directory if the guard fails): from here
        to the end of the test, the template and history roots are made fresh, inside a private ``box`` under this
        test's own temporary directory (``tempfile.tempdir`` is ``box``, the registries are empty, nothing is
        registered with the real ``atexit``; the roots are removed by this test's cleanup). The roots, their parent
        (``box``) and every path built from them lie inside ``self.tmp``; so a guard that fails writes there only.
        Returns ``box``."""
        box = os.path.realpath(tempfile.mkdtemp(prefix="box-", dir=self.tmp))
        exits = []
        for p in (mock.patch.object(tempfile, "tempdir", box), mock.patch.object(helpers, "_TEMPLATE_ROOT", []),
                  mock.patch.object(helpers, "_HISTORY_ROOT", []), mock.patch.object(helpers, "_TEMPLATES", {}),
                  mock.patch.object(helpers, "_HISTORIES", {}),
                  mock.patch.object(helpers, "atexit", types.SimpleNamespace(register=exits.append))):
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(lambda: [fn() for fn in exits])  # runs before the patches stop and before self.tmp is removed
        return box

    def no_copy(self):
        """Patch that fails the test if the fast path (a copy of the template) is taken."""
        return mock.patch.object(helpers.shutil, "copytree", side_effect=AssertionError("fast path taken"))

    def stat_dirty_repo(self, name="dirty"):
        """A fixture repository whose tracked file is stat-dirty with equal content: a plain ``git status`` refreshes
        and rewrites ``.git/index`` (as the PR-5c flake showed), a status under GIT_OPTIONAL_LOCKS=0 does not."""
        root = make_repo(self.fresh(name))
        os.utime(os.path.join(root, ".strict-delivery", "config.yml"), (1, 1))
        return root


class EquivalenceTest(Base):
    def test_f1_default_equals_slow_build(self):  # F1
        fast = make_repo(self.fresh("fast"))
        slow = slow_build(self.fresh("slow"))
        self.assertEqual(facts(fast), facts(slow))
        f = facts(fast)
        self.assertEqual(f["branch"], "refs/heads/main")
        self.assertEqual(f["status"], "")
        self.assertEqual(f["fsck"][0], 0, f["fsck"])
        self.assertEqual(f["bytes"], {".strict-delivery/config.yml": MINIMAL_TEXT.encode(),
                                      ".strict-delivery/context.yml": CONTEXT_TEXT.encode()})
        for want in ("user.email=fixture@example.invalid", "user.name=Fixture", "commit.gpgsign=false",
                     "maintenance.auto=false", "gc.auto=0", "core.bare=false"):
            self.assertIn(want, f["config"].splitlines())
        self.assertEqual(tree_state(os.path.join(fast, ".git", "hooks")), tree_state(os.path.join(slow, ".git", "hooks")))

    def test_f2_config_variants(self):  # F2
        minimal = minimal_config()
        other = {"schema": "config/2", "framework_version": "1.2.3", "profile": "light", "base_branch": "trunk"}
        reordered = {"profile": "strict", "schema": "config/2", "framework_version": "0.0.0"}
        same_again = {"schema": "config/2", "framework_version": "0.0.0", "profile": "strict"}
        texts = {}
        before = len(helpers._TEMPLATES)
        for label, cfg in (("minimal", minimal), ("other", other), ("same", same_again), ("reordered", reordered),
                           ("none", None)):
            with self.subTest(label):
                text = helpers.emit(cfg if cfg is not None else minimal_config())
                texts[label] = text
                fast = make_repo(self.fresh("f-" + label), cfg)
                slow = slow_build(self.fresh("s-" + label), text)
                self.assertEqual(facts(fast), facts(slow))
        # one template per emitted text: minimal, same_again and none share one; other and reordered add one each
        self.assertEqual(texts["minimal"], texts["same"])
        self.assertEqual(texts["minimal"], texts["none"])
        self.assertNotEqual(texts["minimal"], texts["reordered"])  # emit keeps insertion order: a different text
        self.assertEqual(len({t for t in texts.values()}), 3)
        keys = [k for k in helpers._TEMPLATES if k[0] in texts.values()]
        self.assertEqual(len({helpers._TEMPLATES[k] for k in keys}), len(keys))  # no two keys share a directory
        self.assertNotEqual(facts(make_repo(self.fresh("x1"), other))["head"],
                            facts(make_repo(self.fresh("x2"), minimal))["head"])

    def test_f3_existing_files_and_dot_git(self):  # F3
        for label, prep in (("files", lambda d: self.write(d, "a.txt", b"a\n")),
                            ("nested", lambda d: self.write(d, "sub/deeper/b.txt", b"b\n")),
                            ("config-path", lambda d: self.write(d, ".strict-delivery/other.txt", b"o\n")),
                            ("dot-git", lambda d: rawok(d, "init", "-q", "-b", "main")),
                            ("empty-subdir", lambda d: os.mkdir(os.path.join(d, "emptydir")))):
            with self.subTest(label):
                a, b = self.fresh("a-" + label), self.fresh("b-" + label)
                prep(a)
                prep(b)
                with self.no_copy():
                    make_repo(a)
                slow_build(b)
                self.assertEqual(facts(a), facts(b))

    def test_f4_environment_takes_the_slow_path(self):  # F4
        tdir = self.fresh("gittemplate")
        self.write(tdir, "marker.txt", b"from the template dir\n")
        self.write(self.tmp, "gcfg", b"[core]\n\tautocrlf = true\n")
        gcfg = os.path.join(self.tmp, "gcfg")
        slow_cases = (("GIT_TEMPLATE_DIR", tdir), ("GIT_CONFIG_GLOBAL", gcfg), ("GIT_CONFIG_COUNT", "0"),
                      ("GIT_CONFIG_NOSYSTEM", "0"), ("GIT_DEFAULT_HASH", "sha1"), ("GIT_EXEC_PATH", "/nonexistent"),
                      ("GIT_CONFIG_KEY_0", "a.b"), ("GIT_CONFIG_PARAMETERS", "'a.b=c'"))
        for name, value in slow_cases:
            with self.subTest(name):
                with mock.patch.dict(os.environ, {name: value}):
                    if name == "GIT_EXEC_PATH":
                        continue  # a bad exec path breaks git itself: only the decision is checked below
                    a = self.fresh("a-" + name)
                    with self.no_copy():
                        make_repo(a)
                    b = self.fresh("b-" + name)
                    slow_build(b)
                    self.assertEqual(facts(a), facts(b))
                    self.assertEqual(os.path.exists(os.path.join(a, ".git", "marker.txt")), name == "GIT_TEMPLATE_DIR")
        with mock.patch.dict(os.environ, {"GIT_EXEC_PATH": "/nonexistent"}):
            self.assertFalse(helpers._fast_path_ok(self.fresh("execpath"), helpers._template_root()))
        with mock.patch.dict(os.environ):  # GIT_CONFIG_NOSYSTEM unset
            os.environ.pop("GIT_CONFIG_NOSYSTEM")
            with self.no_copy():
                make_repo(self.fresh("nosys"))
        # any other GIT_* name is part of the key: a template built under that environment, equal to a slow build in it
        for name, value in (("GIT_SOMETHING_ELSE", "1"), ("GIT_OPTIONAL_LOCKS", "1"), ("GIT_EDITOR", "ci2-editor")):
            with self.subTest(name), mock.patch.dict(os.environ, {name: value}):
                before = len(helpers._TEMPLATES)
                a = make_repo(self.fresh("k-" + name))
                self.assertEqual(len(helpers._TEMPLATES), before + 1)
                self.assertEqual(facts(a), facts(slow_build(self.fresh("ks-" + name))))
        with mock.patch.dict(os.environ):  # HOME other than the isolated one: the global file is /dev/null
            os.environ["HOME"] = self.tmp
            a = make_repo(self.fresh("home2"))
            self.assertEqual(facts(a), facts(slow_build(self.fresh("home2-slow"))))

    def test_f4_path_is_part_of_the_template_key(self):  # F4 (a test-set PATH)
        make_repo(self.fresh("p0"))
        keys = len(helpers._TEMPLATES)
        shim = self.fresh("shimbin")
        with mock.patch.dict(os.environ, {"PATH": shim + os.pathsep + os.environ["PATH"]}):
            a = make_repo(self.fresh("p1"))
        self.assertEqual(len(helpers._TEMPLATES), keys + 1)
        self.assertEqual(facts(a), facts(slow_build(self.fresh("p1-slow"))))


class IsolationTest(Base):
    def expected(self):
        return facts(slow_build(self.fresh("expected")))

    def test_f5_mutating_a_copy_leaves_the_template_and_others(self):  # F5
        first = make_repo(self.fresh("first"))
        tpl_dirs = [helpers._TEMPLATES[k] for k in helpers._TEMPLATES]
        before = [tree_state(t) for t in tpl_dirs]
        for p, _, files in os.walk(first):  # no hard links, no symlinks, no alternates
            for n in files:
                st = os.lstat(os.path.join(p, n))
                self.assertFalse(stat.S_ISLNK(st.st_mode), os.path.join(p, n))
                self.assertEqual(st.st_nlink, 1, os.path.join(p, n))
        self.assertFalse(os.path.exists(os.path.join(first, ".git", "objects", "info", "alternates")))
        git(first, "checkout", "-q", "-b", "side")
        self.write(first, "new.txt", b"n\n")
        git(first, "add", "-A")
        git(first, "commit", "-q", "-m", "more")
        git(first, "config", "x.y", "z")
        self.write(first, ".git/hooks/pre-commit", b"#!/bin/sh\nexit 1\n")
        git(first, "gc", "-q")
        git(first, "tag", "t1")
        second = make_repo(self.fresh("second"))
        self.assertEqual(facts(second), self.expected())
        self.assertEqual([tree_state(t) for t in tpl_dirs], before)
        self.assertEqual(git(second, "branch", "--list"), "* main")
        self.assertNotIn("x.y", git(second, "config", "--local", "--list"))
        self.assertEqual(git(second, "tag", "--list"), "")

    def test_f8_same_size_edit_right_after_is_seen(self):  # F8
        for i in range(3):
            root = make_repo(self.fresh("r%d" % i))
            path = os.path.join(root, ".strict-delivery", "config.yml")
            st = os.stat(path)
            with open(path, "rb") as fh:
                data = fh.read()
            edited = data.replace(b"strict", b"stric!")
            self.assertEqual(len(edited), len(data))
            with open(path, "wb") as fh:
                fh.write(edited)
            os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns))  # same size and the recorded mtime: the worst case
            self.assertEqual(git(root, "status", "--porcelain"), "M .strict-delivery/config.yml")  # helpers.git strips
            self.assertEqual(git(root, "diff", "--stat").count("config.yml"), 1)

    def test_f9_maintenance_on_both_paths(self):  # F9
        fast = make_repo(self.fresh("fast"))
        busy = self.fresh("busy")
        self.write(busy, "f.txt", b"x\n")
        slow = make_repo(busy)
        for root in (fast, slow):
            self.assertEqual(git(root, "config", "--get", "maintenance.auto"), "false")
            self.assertEqual(git(root, "config", "--get", "gc.auto"), "0")


class OrderFreeTest(Base):
    SCRIPT = ("import os, sys\n"
              "sys.path.insert(0, %r)\n"
              "from tests import helpers\n"
              "d = sys.argv[1]\n"
              "os.mkdir(d)\n"
              "helpers.make_repo(d)\n"
              "print(helpers._TEMPLATE_ROOT[0])\n"
              "print(helpers.git(d, 'rev-parse', 'HEAD'))\n")

    def run_script(self, name, wait=True):
        script = os.path.join(self.tmp, "script.py")
        if not os.path.exists(script):
            with open(script, "w", encoding="utf-8") as fh:
                fh.write(self.SCRIPT % REPO)
        env = dict(os.environ)
        return subprocess.Popen([sys.executable, script, os.path.join(self.tmp, name)], cwd=self.tmp, env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def test_f6_f7_two_processes_each_own_template_removed_at_exit(self):  # F6, F7
        want = facts(slow_build(self.fresh("expected")))["head"]
        procs = [self.run_script("p1"), self.run_script("p2")]
        outs = []
        for p in procs:
            out, err = p.communicate(timeout=300)
            self.assertEqual((p.returncode, err), (0, b""), err)
            outs.append(out.decode().splitlines())
        self.assertEqual([o[1] for o in outs], [want, want])
        self.assertNotEqual(outs[0][0], outs[1][0])  # a private directory per process
        for o in outs:
            self.assertFalse(os.path.exists(o[0]), o[0])  # F7: gone at exit
            self.assertFalse(o[0].startswith(REPO + os.sep))

    def test_f6_second_call_alone_equals_first(self):  # F6: the lazy template: any call may be the first
        a = make_repo(self.fresh("a"))
        b = make_repo(self.fresh("b"))
        self.assertEqual(facts(a), facts(b))


def history_build(root):
    """A history with a symlink, an executable, a nested file and two commits; the facts are its commit ids."""
    make_repo(root)
    os.makedirs(os.path.join(root, "d", "e"))
    for rel, data in (("a.txt", b"alpha\n"), ("d/e/f.txt", b"f\n"), ("run", b"#!/bin/sh\n")):
        with open(os.path.join(root, rel), "wb") as fh:
            fh.write(data)
    os.chmod(os.path.join(root, "run"), 0o755)
    os.symlink("a.txt", os.path.join(root, "ln"))
    one = helpers.commit_all(root, "one")
    return {"one": one, "two": helpers.commit_all(root, "two")}


class HistoryTemplateTest(Base):
    """Row F11 (per-module fixtures), the helper behind it: ``helpers.cached_history``; rows F5, F6, F8, H1, H5 for it."""

    def counting(self):
        calls = []

        def build(root):
            calls.append(root)
            return history_build(root)
        return calls, build

    def regular_files(self, top):
        """Path relative to ``top`` -> (inode, link count) of every regular file."""
        out = {}
        for d, dirs, files in os.walk(top):
            for n in files:
                st = os.lstat(os.path.join(d, n))
                if stat.S_ISREG(st.st_mode):
                    out[os.path.relpath(os.path.join(d, n), top)] = (st.st_ino, st.st_nlink)
        return out

    def test_f11_copy_equals_a_direct_build(self):  # F11: same facts, same repository as the builder run on its own
        calls, build = self.counting()
        dest, got = helpers.cached_history("k-equal", self.fresh("copy"), build)
        direct = self.fresh("direct")
        want = history_build(direct)
        self.assertEqual(got, want)
        self.assertEqual(facts(dest), facts(direct))
        got_tree, want_tree = tree_state(dest), tree_state(direct)
        self.assertEqual(got_tree.pop(".git/index")[:2], want_tree.pop(".git/index")[:2])  # the index holds stat data
        self.assertEqual(got_tree, want_tree)
        self.assertEqual(rawok(dest, "ls-files", "-s"), rawok(direct, "ls-files", "-s"))
        self.assertEqual(os.readlink(os.path.join(dest, "ln")), "a.txt")
        self.assertEqual(stat.S_IMODE(os.stat(os.path.join(dest, "run")).st_mode), 0o755)
        self.assertEqual(rawok(dest, "rev-list", "--count", "HEAD"), "3")

    def test_f11_builds_once_per_key(self):  # F11: the second and later callers copy
        calls, build = self.counting()
        a = helpers.cached_history("k-once", self.fresh("a"), build)
        b = helpers.cached_history("k-once", self.fresh("b"), build)
        self.assertEqual(len(calls), 1)
        self.assertEqual((a[1], facts(a[0])), (b[1], facts(b[0])))
        helpers.cached_history("k-once-other", self.fresh("c"), build)
        self.assertEqual(len(calls), 2)
        with mock.patch.dict(os.environ, {"GIT_FIXTURE_PROBE": "1"}):  # another GIT_* environment: another template
            helpers.cached_history("k-once", self.fresh("d"), build)
        self.assertEqual(len(calls), 3)
        with mock.patch.dict(os.environ, {"PATH": os.environ.get("PATH", "") + os.pathsep + self.tmp}):
            helpers.cached_history("k-once", self.fresh("e"), build)
        self.assertEqual(len(calls), 4)

    def test_f5_copies_share_nothing(self):  # F5: no hard links, alternates, symlinked object stores, shared inodes
        calls, build = self.counting()
        a, _ = helpers.cached_history("k-iso", self.fresh("a"), build)
        b, _ = helpers.cached_history("k-iso", self.fresh("b"), build)
        tree = {top: self.regular_files(top) for top in (calls[0], a, b)}
        for top in (a, b):
            self.assertTrue(tree[top])
            self.assertEqual({n for (_, n) in tree[top].values()}, {1}, top)  # no hard link to anything
            self.assertEqual(tree[top].keys(), tree[calls[0]].keys())
            self.assertFalse(os.path.lexists(os.path.join(top, ".git", "objects", "info", "alternates")))
            self.assertFalse(os.path.islink(os.path.join(top, ".git", "objects")))
            self.assertFalse(os.path.islink(os.path.join(top, ".git")))
        inodes = [{i for (i, _) in tree[top].values()} for top in (calls[0], a, b)]
        self.assertEqual(inodes[0] & inodes[1], set())
        self.assertEqual(inodes[0] & inodes[2], set())
        self.assertEqual(inodes[1] & inodes[2], set())

    def test_f5_mutating_a_copy_leaves_the_template_and_others(self):  # F5: commit, branch, config, hooks, gc
        calls, build = self.counting()
        a, _ = helpers.cached_history("k-mut", self.fresh("a"), build)
        b, _ = helpers.cached_history("k-mut", self.fresh("b"), build)
        built = calls[0]
        template_before, b_before = tree_state(built), tree_state(b)
        self.write(a, "new.txt", b"n\n")
        git(a, "add", "-A")
        git(a, "commit", "-q", "-m", "three")
        git(a, "branch", "side")
        git(a, "config", "k.v", "1")
        self.write(a, ".git/hooks/pre-commit", b"#!/bin/sh\nexit 0\n")
        rawok(a, "gc", "-q")
        self.assertEqual(tree_state(built), template_before)
        self.assertEqual(tree_state(b), b_before)
        c, _ = helpers.cached_history("k-mut", self.fresh("c"), build)
        self.assertEqual(facts(c), facts(b))
        self.assertEqual(len(calls), 1)

    def test_f11_facts_are_a_copy(self):  # a test that edits its facts cannot change the next caller's
        _, build = self.counting()
        _, one = helpers.cached_history("k-facts", self.fresh("a"), build)
        one["one"] = "changed"
        _, two = helpers.cached_history("k-facts", self.fresh("b"), build)
        self.assertNotEqual(two["one"], "changed")

    def test_f11_keeps_mtimes_and_a_same_size_edit_is_seen(self):  # F8 for a cached history
        calls, build = self.counting()
        a, _ = helpers.cached_history("k-mtime", self.fresh("a"), build)
        for rel in ("a.txt", "d/e/f.txt", ".git/index", ".git/HEAD"):
            self.assertEqual(os.stat(os.path.join(a, rel)).st_mtime_ns, os.stat(os.path.join(calls[0], rel)).st_mtime_ns, rel)
        path = os.path.join(a, "a.txt")
        stamp = os.stat(path).st_mtime_ns
        with open(path, "wb") as fh:
            fh.write(b"omega\n")  # same size as "alpha\n"
        os.utime(path, ns=(stamp, stamp))
        self.assertEqual(rawok(a, "status", "--porcelain"), "M a.txt")

    def test_h1_non_empty_or_symlinked_dest_builds_in_place(self):  # F3, H1: the fast path's own conditions
        calls, build = self.counting()
        busy = self.fresh("busy")
        self.write(busy, "pre.txt", b"p\n")
        with self.no_copy():
            helpers.cached_history("k-busy", busy, build)
        self.assertEqual(calls, [busy])
        real = self.fresh("real")
        link = os.path.join(self.tmp, "lnk")
        os.symlink(real, link)
        with self.no_copy():
            helpers.cached_history("k-link", link, build)
        self.assertEqual(calls, [busy, link])
        self.assertEqual(rawok(real, "rev-list", "--count", "HEAD"), "3")

    def test_h2_regular_file_and_missing_dest(self):  # H2: the build runs in place and fails as make_repo does
        calls, build = self.counting()
        plain = os.path.join(self.tmp, "plain")
        with open(plain, "w", encoding="utf-8") as fh:
            fh.write("x")
        for label, path in (("file", plain), ("missing", os.path.join(self.tmp, "nope"))):
            with self.subTest(label):
                rc, _, err = raw(path, "init", "-q", "-b", "main")
                self.assertNotEqual(rc, 0)
                with self.no_copy(), self.assertRaises(AssertionError) as cm:
                    helpers.cached_history("k-h2", path, build)
                self.assertEqual(str(cm.exception), "git init -q -b main failed: %s" % err)
        self.assertEqual(calls, [plain, os.path.join(self.tmp, "nope")])

    def test_h3_fifo_dest_is_never_opened(self):  # H3
        calls, build = self.counting()
        fifo = os.path.join(self.tmp, "fifo")
        os.mkfifo(fifo)
        rc, _, err = raw(fifo, "init", "-q", "-b", "main")
        self.assertNotEqual(rc, 0)
        kind, val = helpers.watched(lambda: helpers.cached_history("k-h3", fifo, build), 20)
        self.assertEqual(kind, "err")
        self.assertIsInstance(val, AssertionError)
        self.assertEqual(str(val), "git init -q -b main failed: %s" % err)
        self.assertEqual(calls, [fifo])
        self.assertTrue(stat.S_ISFIFO(os.lstat(fifo).st_mode))

    def test_h4_a_parent_of_dest_is_a_symlink(self):  # H4: the copy equals a direct build
        calls, build = self.counting()
        real = self.fresh("real")
        os.mkdir(os.path.join(real, "sub"))
        link = os.path.join(self.tmp, "parentlink")
        os.symlink(real, link)
        dest, got = helpers.cached_history("k-h4", os.path.join(link, "sub"), build)
        direct = self.fresh("direct")
        want = history_build(direct)
        self.assertEqual(got, want)
        self.assertEqual(facts(os.path.join(real, "sub")), facts(direct))
        self.assertFalse(os.path.islink(os.path.join(real, "sub")))

    def test_h6_unusual_names_in_an_existing_dest(self):  # H6 (F3): built in place, equal to a direct build
        calls, build = self.counting()
        names = ["sp ace.txt", "new\nline.txt", "éè.txt", "‮.txt", "-dash", "tab\t.txt"]
        a, b = self.fresh("a"), self.fresh("b")
        for d in (a, b):
            for n in names:
                with open(os.path.join(d, n), "wb") as fh:
                    fh.write(b"x\n")
        with self.no_copy():
            _, got = helpers.cached_history("k-h6", a, build)
        self.assertEqual((calls, got), ([a], history_build(b)))
        self.assertEqual(facts(a), facts(b))

    def test_h6_non_utf8_name_in_an_existing_dest(self):  # H6 (skipped where the file system refuses the name)
        calls, build = self.counting()
        a, b = self.fresh("a"), self.fresh("b")
        try:
            for d in (a, b):
                with open(os.path.join(os.fsencode(d), b"\xff\xfe.txt"), "wb") as fh:
                    fh.write(b"x\n")
        except OSError as e:
            self.skipTest("the file system refuses a non-UTF-8 name: %s" % e)
        with self.no_copy():
            helpers.cached_history("k-h6u", a, build)
        history_build(b)
        self.assertEqual(rawok(a, "rev-parse", "HEAD^{tree}"), rawok(b, "rev-parse", "HEAD^{tree}"))
        self.assertEqual(calls, [a])

    def test_k1_numeric_text_4300_and_4301_digits(self):  # K1: the text is never turned into an int
        for digits in (4300, 4301):
            for limit in helpers.INT_LIMITS:
                with self.subTest(digits=digits, limit=limit), helpers.int_limit(limit):
                    cfg = dict(minimal_config(), big="7" * digits)
                    dest, got = helpers.cached_history(("k-k1", digits, limit), self.fresh("f%d-%s" % (digits, limit)),
                                                       lambda root, cfg=cfg: (make_repo(root, cfg), {"n": 1})[1])
                    slow = slow_build(self.fresh("s%d-%s" % (digits, limit)), helpers.emit(cfg))
                    self.assertEqual(got, {"n": 1})
                    self.assertEqual(facts(dest), facts(slow))
                    self.assertIn(("7" * digits).encode(), facts(dest)["bytes"][".strict-delivery/config.yml"])

    def test_k2_unicode_code_point_whose_category_differs(self):  # K2: U+1FAE0 is unassigned in 3.9's Unicode, a symbol in 3.13's
        for ch in ("\U0001fae0", "é", " ", "ퟻ"):
            with self.subTest(code=hex(ord(ch))):
                cfg = dict(minimal_config(), note="a" + ch + "b")
                dest, _ = helpers.cached_history(("k-k2", ord(ch)), self.fresh("f%x" % ord(ch)),
                                                 lambda root, cfg=cfg: (make_repo(root, cfg), {})[1])
                self.assertEqual(facts(dest), facts(slow_build(self.fresh("s%x" % ord(ch)), helpers.emit(cfg))))

    def test_h5_history_and_template_directories_are_never_a_target(self):  # H5
        box = self.sandbox()  # the roots and their parent are private to this test (F-20261125-hqt5)
        calls, build = self.counting()
        helpers.cached_history("k-h5", self.fresh("warm"), build)
        for root in (helpers._TEMPLATE_ROOT[0], helpers._HISTORY_ROOT[0]):
            self.assertEqual(os.path.dirname(root), box)
            before = tree_state(box)
            for label, path in (("root", root), ("inside", os.path.join(root, "x")), ("parent", os.path.dirname(root)),
                                ("a built history", calls[0])):
                with self.subTest(root=root, label=label), self.assertRaises(ValueError) as cm:
                    helpers.cached_history("k-h5", self.inside(path), build)
                self.assertIn("overlaps the fixture template directory", str(cm.exception))
            self.assertEqual(tree_state(box), before)  # nothing written anywhere in the sandbox
        self.assertEqual(len(calls), 1)

    def test_h7_history_root_is_private_and_outside_the_checkout(self):  # H7
        helpers.cached_history("k-h7", self.fresh("warm"), self.counting()[1])
        root = helpers._HISTORY_ROOT[0]
        self.assertEqual(os.path.dirname(root), os.path.realpath(tempfile.gettempdir()))
        self.assertTrue(os.path.basename(root).startswith("sd-fixture-history-"))
        self.assertEqual(stat.S_IMODE(os.stat(root).st_mode), 0o700)
        for under in (REPO, self.tmp):
            self.assertFalse(root.startswith(under + os.sep), under)
        self.assertNotEqual(root, helpers._TEMPLATE_ROOT[0])

    def test_f6_f7_order_free_and_removed_at_exit(self):  # F6, F7: any call may be first, in any process
        script = os.path.join(self.tmp, "hscript.py")
        with open(script, "w", encoding="utf-8") as fh:
            fh.write("import os, sys\nsys.path.insert(0, %r)\nfrom tests import helpers\n"
                     "n = []\n"
                     "def build(root):\n    n.append(1)\n    helpers.make_repo(root)\n    return {'x': 1}\n"
                     "for name in sys.argv[1:]:\n    os.mkdir(name)\n    helpers.cached_history('k', name, build)\n"
                     "print(len(n))\nprint(helpers._HISTORY_ROOT[0])\nprint(helpers._TEMPLATE_ROOT[0])\n" % REPO)
        procs = [subprocess.Popen([sys.executable, script] + [os.path.join(self.tmp, "p%d%s" % (i, k)) for k in "ab"],
                                  cwd=self.tmp, stdout=subprocess.PIPE, stderr=subprocess.PIPE) for i in (1, 2)]
        roots = []
        for p in procs:
            out, err = p.communicate(timeout=300)
            self.assertEqual((p.returncode, err), (0, b""), err)
            lines = out.decode().splitlines()
            self.assertEqual(lines[0], "1")  # built once for two copies
            roots.append(lines[1])
            for r in lines[1:]:
                self.assertFalse(os.path.exists(r), r)
                self.assertFalse(r.startswith(REPO + os.sep))
        self.assertNotEqual(roots[0], roots[1])
        for i in (1, 2):
            self.assertEqual(facts(os.path.join(self.tmp, "p%da" % i)), facts(os.path.join(self.tmp, "p%db" % i)))

    def test_k3_no_exception_group_in_cached_history(self):  # K3 (PC1): the new helper names none
        with open(os.path.join(REPO, "tests", "helpers.py"), encoding="utf-8") as fh:
            self.assertNotIn("Exception" + "Group", fh.read())


class InterfaceTest(unittest.TestCase):
    SIGS = {
        "git": "(root: str, *args: str, env: Optional[dict] = None, check: bool = True) -> str",
        "make_repo": "(tmp: str, config: Optional[dict] = None) -> str",
        "commit_all": "(root: str, msg: str) -> str",
        "write_record": "(root: str, rel: str, row: dict) -> str",
        "minimal_config": "() -> dict",
        "GitIsolatedTestCase": "(methodName='runTest')",
        "root_forms": "(tmp: str, top: str) -> list",
        "check_root_forms": "(tc: unittest.case.TestCase, forms: list, calls: dict) -> None",
        "watched": "(fn, secs=10)",
        "within": "(fn, secs=10)",
        "int_limit": "(value)",
    }

    def test_f10_public_names_and_signatures(self):  # F10
        for name, want in self.SIGS.items():
            with self.subTest(name):
                self.assertEqual(str(inspect.signature(getattr(helpers, name))), want)
        self.assertEqual(helpers.TOP, "git rev-parse --show-toplevel: root must be the repository top level")
        self.assertEqual(helpers.E128, "git rev-parse --show-toplevel failed (exit 128)")
        self.assertEqual(helpers.CLEARED_ENV, (
            "GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES",
            "GIT_NAMESPACE", "GIT_CEILING_DIRECTORIES", "GIT_INDEX_FILE", "CLAUDE_PROJECT_DIR"))
        self.assertEqual(helpers._IDENTITY, {
            "GIT_AUTHOR_NAME": "Fixture Author", "GIT_AUTHOR_EMAIL": "author@example.invalid",
            "GIT_AUTHOR_DATE": "2026-01-01T00:00:00+0000", "GIT_COMMITTER_NAME": "Fixture Committer",
            "GIT_COMMITTER_EMAIL": "committer@example.invalid", "GIT_COMMITTER_DATE": "2026-01-01T00:00:00+0000"})
        self.assertEqual(helpers.INT_LIMITS, (None, 640, 0) if hasattr(sys, "set_int_max_str_digits") else (None,))

    def test_k3_no_exception_group_in_the_changed_files(self):  # K3
        word = "Exception" + "Group"
        for rel in ("tests/helpers.py", "tests/test_helpers_fixture.py"):
            with open(os.path.join(REPO, rel), encoding="utf-8") as fh:
                self.assertNotIn(word, fh.read(), rel)


class InputDomainTest(Base):
    def test_k1_numeric_text_4300_and_4301_digits(self):  # K1
        for digits in (4300, 4301):
            for limit in helpers.INT_LIMITS:
                with self.subTest(digits=digits, limit=limit), helpers.int_limit(limit):
                    cfg = dict(minimal_config(), big="7" * digits)
                    text = helpers.emit(cfg)
                    fast = make_repo(self.fresh("f%d-%s" % (digits, limit)), cfg)
                    slow = slow_build(self.fresh("s%d-%s" % (digits, limit)), text)
                    self.assertEqual(facts(fast), facts(slow))
                    self.assertIn(("7" * digits).encode(), facts(fast)["bytes"][".strict-delivery/config.yml"])

    def test_k2_unicode_code_point_whose_category_differs(self):  # K2
        # U+1FAE0 (melting face): unassigned (Cn) in the Unicode of Python 3.9, a symbol (So) in 3.13's
        for ch in ("\U0001fae0", "é", " ", "ퟻ"):
            with self.subTest(code=hex(ord(ch))):
                cfg = dict(minimal_config(), note="a" + ch + "b")
                fast = make_repo(self.fresh("f%x" % ord(ch)), cfg)
                slow = slow_build(self.fresh("s%x" % ord(ch)), helpers.emit(cfg))
                self.assertEqual(facts(fast), facts(slow))

    def test_h1_tmp_is_a_symlink(self):  # H1
        target = self.fresh("target")
        link = os.path.join(self.tmp, "link")
        os.symlink(target, link)
        with self.no_copy():
            self.assertEqual(make_repo(link), link)
        self.assertEqual(facts(target), facts(slow_build(self.fresh("slow"))))

    def test_h2_regular_file_and_missing(self):  # H2
        plain = os.path.join(self.tmp, "plain")
        with open(plain, "w", encoding="utf-8") as fh:
            fh.write("x")
        for label, path in (("file", plain), ("missing", os.path.join(self.tmp, "nope"))):
            with self.subTest(label):
                rc, _, err = raw(path, "init", "-q", "-b", "main")
                self.assertNotEqual(rc, 0)
                with self.assertRaises(AssertionError) as cm:
                    make_repo(path)
                self.assertEqual(str(cm.exception), "git init -q -b main failed: %s" % err)
                self.assertTrue(err)

    def test_h3_fifo_is_never_opened(self):  # H3
        fifo = os.path.join(self.tmp, "fifo")
        os.mkfifo(fifo)
        rc, _, err = raw(fifo, "init", "-q", "-b", "main")
        self.assertNotEqual(rc, 0)
        kind, val = helpers.watched(lambda: make_repo(fifo), 20)
        self.assertEqual(kind, "err")
        self.assertIsInstance(val, AssertionError)
        self.assertEqual(str(val), "git init -q -b main failed: %s" % err)
        self.assertTrue(stat.S_ISFIFO(os.lstat(fifo).st_mode))

    def test_h4_a_parent_is_a_symlink(self):  # H4
        real = self.fresh("real")
        os.mkdir(os.path.join(real, "sub"))
        link = os.path.join(self.tmp, "parentlink")
        os.symlink(real, link)
        make_repo(os.path.join(link, "sub"))
        self.assertEqual(facts(os.path.join(real, "sub")), facts(slow_build(self.fresh("slow"))))

    def test_h5_template_directory_is_never_a_target(self):  # H5
        box = self.sandbox()  # the root and its parent are private to this test (F-20261125-hqt5)
        make_repo(self.fresh("warm"))
        root = helpers._TEMPLATE_ROOT[0]
        self.assertEqual(os.path.dirname(root), box)
        tpl = next(iter(helpers._TEMPLATES.values()))
        before = tree_state(box)
        inner = os.path.join(tpl, "subdir")
        for label, path in (("root itself", root), ("template", tpl), (".git of the template", os.path.join(tpl, ".git")),
                            ("missing under it", inner), ("parent of the root", os.path.dirname(root))):
            with self.subTest(label), self.assertRaises(ValueError) as cm:
                make_repo(self.inside(path))
            self.assertIn("overlaps the fixture template directory", str(cm.exception))
        self.assertEqual(tree_state(box), before)  # nothing written anywhere in the sandbox
        self.assertFalse(os.path.exists(inner))

    def test_h6_unusual_names_in_an_existing_directory(self):  # H6
        names = ["sp ace.txt", "new\nline.txt", "éè.txt", "‮.txt", "-dash", "tab\t.txt"]
        a, b = self.fresh("a"), self.fresh("b")
        for d in (a, b):
            for n in names:
                with open(os.path.join(d, n), "wb") as fh:
                    fh.write(b"x\n")
        with self.no_copy():
            make_repo(a)
        slow_build(b)
        self.assertEqual(facts(a), facts(b))

    def test_h6_non_utf8_name(self):  # H6 (skipped where the file system refuses the name)
        a, b = self.fresh("a"), self.fresh("b")
        try:
            for d in (a, b):
                with open(os.path.join(os.fsencode(d), b"\xff\xfe.txt"), "wb") as fh:
                    fh.write(b"x\n")
        except OSError as e:
            self.skipTest("the file system refuses a non-UTF-8 name: %s" % e)
        with self.no_copy():
            make_repo(a)
        slow_build(b)
        self.assertEqual(rawok(a, "rev-parse", "HEAD^{tree}"), rawok(b, "rev-parse", "HEAD^{tree}"))

    def test_h8_another_file_system_takes_the_slow_path(self):  # F1 (init's core.* lines depend on the file system)
        make_repo(self.fresh("warm"))
        root = helpers._TEMPLATE_ROOT[0]
        real_stat = os.stat

        def stat(path, *a, **kw):
            st = real_stat(path, *a, **kw)
            if isinstance(path, str) and os.path.realpath(path) == root:
                fields = list(st)
                fields[2] = st.st_dev + 1
                return os.stat_result(fields)
            return st
        with mock.patch.object(helpers.os, "stat", side_effect=stat), self.no_copy():
            a = make_repo(self.fresh("other-fs"))
        self.assertEqual(facts(a), facts(slow_build(self.fresh("slow"))))

    def test_h7_template_lives_in_a_private_temp_directory(self):  # H7
        make_repo(self.fresh("warm"))
        root = helpers._TEMPLATE_ROOT[0]
        self.assertEqual(os.path.dirname(root), os.path.realpath(tempfile.gettempdir()))
        self.assertTrue(os.path.basename(root).startswith("sd-fixture-template-"))
        self.assertEqual(stat.S_IMODE(os.stat(root).st_mode), 0o700)
        for under in (REPO, self.tmp):
            self.assertFalse(root.startswith(under + os.sep), under)
        for tpl in helpers._TEMPLATES.values():
            self.assertTrue(tpl.startswith(root + os.sep))


GUARD_ARGS = {"make_repo": ("tmp", 0), "_make_repo_slow": ("tmp", 0), "cached_history": ("dest", 1)}  # name -> (keyword, position) of the path
OWN_FILE = "test_helpers_fixture.py"
DYNAMIC = ("getattr", "globals", "vars", "__dict__", "__getattribute__", "attrgetter")  # ways to reach a name given as a string


def _callee(node):
    return getattr(node, "attr", getattr(node, "id", ""))


def _dotted(node):
    """``a.b.c`` for a chain of attributes ending in a name, else ``None``."""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    return ".".join([node.id] + parts[::-1]) if isinstance(node, ast.Name) else None


def guard_units(tree):
    """``[(qualified name, scope node)]``: every function and method (at any class depth; a nested function or lambda
    belongs to the function that holds it), the module level, and the statements of every class body."""
    units = []

    def collect(node, prefix):
        for ch in ast.iter_child_nodes(node):
            if isinstance(ch, ast.ClassDef):
                collect(ch, prefix + ch.name + ".")
            elif isinstance(ch, (ast.FunctionDef, ast.AsyncFunctionDef)):
                units.append((prefix + ch.name, ch))
    collect(tree, "")
    defs = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
    units.append(("<module level>", ast.Module(body=[n for n in tree.body if not isinstance(n, defs)], type_ignores=[])))
    for cl in [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]:
        units.append((cl.name + ".<class body>", ast.Module(body=[n for n in cl.body if not isinstance(n, defs)], type_ignores=[])))
    return units


def _raises_area(node):
    """The ids of every node inside an ``assertRaises`` / ``assertRaisesRegex`` block or inside the arguments of such a call."""
    area = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.With) and any(isinstance(i.context_expr, ast.Call) and _callee(i.context_expr.func).startswith("assertRaises")
                                             for i in sub.items):
            for stmt in sub.body:
                area.update(id(n) for n in ast.walk(stmt))
        elif isinstance(sub, ast.Call) and _callee(sub.func).startswith("assertRaises"):
            for a in list(sub.args) + [k.value for k in sub.keywords]:
                area.update(id(n) for n in ast.walk(a))
    return area


def unsandboxed_guard_tests(tests_dir):
    """Row S1 / H5 safety (F-20261125-hqt5, F-20261126-djav; stream-common :65), the class: ``{"file::Qualified.name"}`` of
    every refusal-guard test in a ``test_*.py`` file of ``tests_dir`` (row D1) that hands ``make_repo``, ``cached_history``
    or ``_make_repo_slow`` a path that is not positively the test's own (row D2, a closed grammar: everything not listed
    is reported, whatever it spells). Members: in ``test_helpers_fixture.py`` every function (method, helper, nested
    function, lambda), the module level and every class body that names a guarded function; in any other module only a
    guarded call inside an ``assertRaises`` / ``assertRaisesRegex`` block or passed to one (a plain caller that expects no
    refusal is outside the class). Accepted path forms: ``self.inside(..)`` (checks at run time that the real path lies
    inside the test's own directory); in ``test_helpers_fixture.py`` also ``self.tmp``, ``self.work``, ``self.fresh(..)``
    (it calls ``self.inside``) and ``self.sandbox()`` (a box below ``self.tmp``), ``Str(<accepted>)`` and ``None`` and
    an ``int`` (type-refusal tests); everywhere ``tempfile.mkdtemp(..)`` and ``tempfile.TemporaryDirectory(..)`` (a new
    directory), ``os.path.join(<accepted>, <relative literal without a ``..`` component>...)``, ``os.path.realpath``,
    ``os.path.abspath`` and ``os.fsencode`` of an accepted path, the result of ``make_repo`` of an accepted path, a
    conditional of two accepted paths, and a name whose every binding (assignment, tuple assignment, loop over literal
    tuples, ``with .. as``, the directory a ``cached_history`` build callback gets) is accepted. A guarded name used other
    than as a called name (an alias, a string beside ``getattr``/``globals``/``vars``/``__dict__``), a guarded function
    passed by value to anything but ``assertRaises``/``assertRaisesRegex`` (or ``self.refused(fn, text, *args)`` in the own
    file), starred arguments, and a rebinding of ``self.tmp`` or ``self.work`` are reported. It reports more than the
    name-list scan it replaces: that one accepted a ``self.sandbox()`` test with any path."""
    found = set()
    for name in sorted(os.listdir(tests_dir)):
        if not (name.startswith("test_") and name.endswith(".py")):
            continue
        with open(os.path.join(tests_dir, name), encoding="utf-8") as fh:
            text = fh.read()
        tree = ast.parse(text)
        own = name == OWN_FILE
        builders = set()  # names passed as the build callback of cached_history anywhere in the file
        for sub in ast.walk(tree):
            if isinstance(sub, ast.Call) and _callee(sub.func) == "cached_history":
                for b in list(sub.args[2:3]) + [k.value for k in sub.keywords if k.arg == "build"]:
                    if isinstance(b, ast.Name):
                        builders.add(b.id)
        for qual, node in guard_units(tree):
            if _guard_problems(node, text, own, qual in builders):
                found.add(name + "::" + qual)
    return found


def _guard_problems(node, text, own, is_builder):
    """The reasons (source texts) why ``node`` hands a guarded function a path that is not positively the test's own."""
    named = any(isinstance(s, (ast.Name, ast.Attribute)) and _callee(s) in GUARD_ARGS or isinstance(s, ast.Constant) and s.value in GUARD_ARGS
                for s in ast.walk(node))
    if not named:  # the unit names no guarded function: not a member
        return []
    area = _raises_area(node)
    scope = named and (own or any(isinstance(s, ast.Call) and _callee(s.func).startswith("assertRaises") for s in ast.walk(node)))
    binds, stored = {}, set()

    def bind(target, kind, value):
        for n in ast.walk(target):
            if isinstance(n, ast.Name):
                binds.setdefault(n.id, []).append((kind, target, value))
                stored.add(id(n))
    other = ("other", None, None)
    for sub in ast.walk(node):
        if isinstance(sub, ast.Assign):
            for t in sub.targets:
                bind(t, "assign", sub.value)
        elif isinstance(sub, ast.For):
            bind(sub.target, "for", sub.iter)
        elif isinstance(sub, ast.withitem) and sub.optional_vars is not None:
            bind(sub.optional_vars, "with", sub.context_expr)
        elif isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            a = sub.args
            for arg in a.posonlyargs + a.args + a.kwonlyargs + [x for x in (a.vararg, a.kwarg) if x]:
                binds.setdefault(arg.arg, []).append(("param", sub, arg))
            if not isinstance(sub, ast.Lambda):
                binds.setdefault(sub.name, []).append(other)
        elif isinstance(sub, ast.ClassDef):
            binds.setdefault(sub.name, []).append(other)
        elif isinstance(sub, ast.ExceptHandler) and sub.name:
            binds.setdefault(sub.name, []).append(other)
        elif isinstance(sub, (ast.Import, ast.ImportFrom)):
            for al in sub.names:
                binds.setdefault((al.asname or al.name).split(".")[0], []).append(other)
    for sub in ast.walk(node):  # every other way a name gets a value: augmented, walrus, comprehension, delete, match
        if isinstance(sub, ast.Name) and isinstance(sub.ctx, (ast.Store, ast.Del)) and id(sub) not in stored:
            binds.setdefault(sub.id, []).append(other)
    handed = set()  # build callbacks of cached_history: their first parameter is the helper's own directory
    if is_builder:  # a function (a module or class body has no name a callback could be passed by)
        handed.add(id(node))
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call) and _callee(sub.func) == "cached_history":
            for b in list(sub.args[2:3]) + [k.value for k in sub.keywords if k.arg == "build"]:
                if isinstance(b, ast.Lambda):
                    handed.add(id(b))
                elif isinstance(b, ast.Name):
                    handed.update(id(v) for kind, tgt, v in binds.get(b.id, []) if kind == "assign" and isinstance(v, ast.Lambda))
                    handed.update(id(i) for i in ast.walk(node) if isinstance(i, (ast.FunctionDef, ast.AsyncFunctionDef)) and i.name == b.id)

    def accepted(e, seen):
        if isinstance(e, ast.Name):
            if e.id in seen:
                return True
            bs = binds.get(e.id)
            # a parameter is the helper's directory only where the function that binds it holds the use
            return bool(bs) and all(binding_ok(e.id, b, seen | {e.id}) and (b[0] != "param" or id(e) in {id(n) for n in ast.walk(b[1])})
                                    for b in bs)
        if isinstance(e, ast.Attribute):
            return own and isinstance(e.value, ast.Name) and e.value.id == "self" and e.attr in ("tmp", "work")
        if isinstance(e, ast.Constant):
            return own and (e.value is None or (type(e.value) is int))
        if isinstance(e, ast.Call):
            f, d = e.func, _dotted(e.func)
            if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id == "self":
                return f.attr == "inside" or (own and f.attr in ("fresh", "sandbox"))
            if d in ("tempfile.mkdtemp", "tempfile.TemporaryDirectory"):
                return True
            if d == "os.path.join" and e.args and not e.keywords:
                return accepted(e.args[0], seen) and all(relative(a, seen) for a in e.args[1:])
            if d in ("os.path.realpath", "os.path.abspath", "os.fsencode") and len(e.args) == 1 and not e.keywords:
                return accepted(e.args[0], seen)
            if own and d == "Str" and len(e.args) == 1 and not e.keywords:
                return accepted(e.args[0], seen)
            if _callee(f) in ("make_repo", "_make_repo_slow"):
                return True  # its result is its path; that nested guarded call is a call of this unit, checked on its own
            return False
        if isinstance(e, ast.IfExp):
            return accepted(e.body, seen) and accepted(e.orelse, seen)
        return False

    def relative(a, seen):
        if isinstance(a, ast.Constant):
            return isinstance(a.value, str) and a.value[:1] not in ("", "/") and ".." not in a.value.split("/")
        if isinstance(a, ast.Name):
            bs = binds.get(a.id)
            return bool(bs) and a.id not in seen and all(
                (k == "assign" and relative(v, seen | {a.id})) or (k == "for" and isinstance(t, ast.Name) and isinstance(v, (ast.Tuple, ast.List))
                                                                   and all(relative(x, seen | {a.id}) for x in v.elts))
                for k, t, v in bs)
        return False

    def binding_ok(name, b, seen):
        kind, tgt, v = b
        if kind == "param":
            args = tgt.args.posonlyargs + tgt.args.args
            return id(tgt) in handed and bool(args) and args[0] is v
        if kind in ("assign", "with"):
            return accepted(v, seen) if isinstance(tgt, ast.Name) else positional(tgt, v, name, seen, False)
        if kind == "for":
            if isinstance(tgt, ast.Name):
                return isinstance(v, (ast.Tuple, ast.List)) and all(accepted(x, seen) for x in v.elts)
            return positional(tgt, v, name, seen, True)
        return False

    def positional(tgt, v, name, seen, loop):
        if not isinstance(tgt, ast.Tuple):
            return False
        pos = [i for i, t in enumerate(tgt.elts) if isinstance(t, ast.Name) and t.id == name]
        if len(pos) != 1:
            return False
        rows = (v.elts if isinstance(v, (ast.Tuple, ast.List)) else None) if loop else [v]
        if rows is None:
            return False
        return all(isinstance(r, (ast.Tuple, ast.List)) and len(r.elts) == len(tgt.elts) and not any(isinstance(x, ast.Starred) for x in r.elts)
                   and accepted(r.elts[pos[0]], seen) for r in rows)

    def guard_path(args, keywords, name):
        kw, idx = GUARD_ARGS[name]
        return args[idx] if len(args) > idx else next((k.value for k in keywords if k.arg == kw), None)

    bad, refs = [], set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            callee = _callee(sub.func)
            if callee in GUARD_ARGS and (own or id(sub) in area):
                arg = guard_path(sub.args, sub.keywords, callee)  # a starred argument or ``**kw`` is no accepted form: reported
                if not accepted(arg, frozenset()):  # no path argument at all (None) is no accepted form either
                    bad.append("a path that is not an accepted form")
            # a guarded function passed by value: its arguments are the ones after it (after the text for ``self.refused``)
            for i, a in enumerate(sub.args):
                if isinstance(a, (ast.Name, ast.Attribute)) and _callee(a) in GUARD_ARGS:
                    refs.add(id(a))
                    if not (own or id(sub) in area or callee.startswith("assertRaises")):
                        continue  # a plain caller outside the own file expects no refusal: not in the class (row D1 (b))
                    skip = 1 if callee.startswith("assertRaises") else 2 if own and callee == "refused" else None
                    if skip is None:
                        bad.append("%s passed to %s" % (_callee(a), callee))
                        continue
                    rest, kws = sub.args[i + skip:], sub.keywords
                    arg = guard_path(rest, kws, _callee(a))
                    if not accepted(arg, frozenset()):
                        bad.append("a path that is not an accepted form")
            if own and len(sub.args) > 1 and isinstance(sub.args[0], ast.Name) and sub.args[0].id == "self" \
                    and isinstance(sub.args[1], ast.Constant) and sub.args[1].value in ("tmp", "work"):
                bad.append("rebinds self.%s" % sub.args[1].value)  # setattr(self, "tmp", ..), patch.object(self, "tmp", ..)
        elif own and isinstance(sub, ast.Attribute) and isinstance(sub.ctx, ast.Store) and isinstance(sub.value, ast.Name) \
                and sub.value.id == "self" and sub.attr in ("tmp", "work"):
            bad.append("assigns self.%s" % sub.attr)
    calls = {id(s.func) for s in ast.walk(node) if isinstance(s, ast.Call)}
    if scope:
        dynamic = guard_string = False
        for sub in ast.walk(node):
            if isinstance(sub, (ast.Name, ast.Attribute)) and _callee(sub) in GUARD_ARGS and id(sub) not in calls and id(sub) not in refs:
                bad.append("%s named other than in a call" % _callee(sub))
            if isinstance(sub, (ast.Name, ast.Attribute)) and _callee(sub) in DYNAMIC:
                dynamic = True
            if isinstance(sub, ast.Constant) and sub.value in GUARD_ARGS:
                guard_string = True
        if dynamic and guard_string:
            bad.append("a guarded name as a string beside a dynamic lookup")
    return bad


class OverlapMatrixTest(Base):
    """Row H5, the pair matrix (F-20261125-zgnj, F-20261125-hqt5): {template root, history root} x {equal, below,
    above} x {exact, case-folded} for ``make_repo`` and ``cached_history``, all inside ``self.sandbox()``. Case-folded
    aliases are refused on a case-sensitive file system too (chosen: fail closed and simpler); on a case-insensitive
    one (macOS APFS) the alias really is the same directory (checked with ``samefile`` where it exists)."""
    MSG = "overlaps the fixture template directory"

    def cells(self):
        """The cross product, generated: ``(guard, root name, relation, spelling, path)``. ``below`` is an existing empty
        directory inside the root, ``above`` the parent of the root (the sandbox)."""
        roots = {"template": helpers._TEMPLATE_ROOT[0], "history": helpers._HISTORY_ROOT[0]}
        out = []
        for guard in ("make_repo", "cached_history"):
            for rname in sorted(roots):
                root = roots[rname]
                sub = os.path.join(root, "below")
                if not os.path.isdir(sub):
                    os.mkdir(sub)
                for rel, path in (("equal", root), ("below", sub), ("above", os.path.dirname(root))):
                    for spelling in ("exact", "folded"):
                        out.append((guard, rname, rel, spelling, path if spelling == "exact" else path.upper()))
        return out

    @staticmethod
    def refused(guard, rname, rel):
        """The invariant of a cell: ``cached_history`` refuses both roots; ``make_repo`` refuses the template root and
        every directory above it, and leaves the history root and what is below it alone (a history build runs there)."""
        return guard == "cached_history" or rname == "template" or rel == "above"

    def test_h5_pair_matrix(self):
        box = self.sandbox()
        make_repo(self.fresh("warm"))
        warm_calls = []
        helpers.cached_history("k-matrix", self.fresh("warm2"), lambda root: warm_calls.append(root) or {})
        cells = self.cells()
        self.assertEqual(len(cells), 2 * 2 * 3 * 2)
        self.assertEqual(len({c[:4] for c in cells}), 24)
        before = tree_state(box)
        for guard, rname, rel, spelling, path in cells:
            with self.subTest(guard=guard, root=rname, relation=rel, spelling=spelling):
                if spelling == "folded":
                    exact = next(c[4] for c in cells if c[:3] == (guard, rname, rel) and c[3] == "exact")
                    self.assertNotEqual(path, exact)  # a different spelling
                    if os.path.exists(path):  # case-insensitive file system: the alias is the same directory
                        self.assertTrue(os.path.samefile(path, exact))
                built = []
                if guard == "make_repo":
                    run = lambda: make_repo(self.inside(path))  # noqa: E731
                else:
                    run = lambda: helpers.cached_history("k-cell", self.inside(path), lambda root: built.append(root) or {})  # noqa: E731
                if self.refused(guard, rname, rel):
                    with self.assertRaises(ValueError) as cm:
                        run()
                    self.assertTrue(str(cm.exception).startswith(guard + ": "), str(cm.exception))
                    self.assertIn(self.MSG, str(cm.exception))
                else:  # not a target of the guard: nothing is written either (the slow path is stubbed)
                    with mock.patch.object(helpers, "_fast_path_ok", return_value=False), \
                            mock.patch.object(helpers, "_make_repo_slow", side_effect=lambda t, c: t) as slow:
                        self.assertEqual(run(), path)
                    self.assertEqual(slow.call_count, 1)
                self.assertEqual(built, [])
                self.assertEqual(tree_state(box), before)  # invariant of every cell: the sandbox is unchanged
        self.assertEqual(len(warm_calls), 1)  # only the warm-up built anything

    def test_h5_filesystem_root_contains_every_root(self):
        """``/`` lies above every root; a ``realpath`` that says ``/`` for a directory of the sandbox is refused (the
        directory itself is private, so a failing guard writes only there)."""
        box = self.sandbox()
        make_repo(self.fresh("warm"))
        helpers.cached_history("k-warm", self.fresh("warm2"), lambda root: {})  # both roots exist before the snapshot
        target = os.path.join(box, "claims-to-be-the-filesystem-root")
        os.mkdir(target)
        real_realpath = os.path.realpath

        def fake(path, *a, **kw):
            return "/" if path == target else real_realpath(path, *a, **kw)
        before = tree_state(box)
        with mock.patch.object(os.path, "realpath", side_effect=fake):
            for guard, run in (("make_repo", lambda: make_repo(target)),
                               ("cached_history", lambda: helpers.cached_history("k-slash", target, lambda r: {}))):
                with self.subTest(guard), self.assertRaises(ValueError) as cm:
                    run()
                self.assertIn("overlaps the fixture template directory", str(cm.exception))
        self.assertEqual(tree_state(box), before)

    def test_h5_sandbox_keeps_every_root_and_parent_private(self):
        box = self.sandbox()
        self.assertTrue(box.startswith(self.tmp + os.sep), box)
        self.assertEqual(os.path.realpath(tempfile.gettempdir()), box)
        make_repo(self.fresh("w1"))
        helpers.cached_history("k-priv", self.fresh("w2"), lambda root: {})
        for root in (helpers._TEMPLATE_ROOT[0], helpers._HISTORY_ROOT[0]):
            self.assertEqual(os.path.dirname(root), box)
            self.assertTrue(root.startswith(self.tmp + os.sep), root)
        self.assertIsInstance(helpers.atexit, types.SimpleNamespace)  # nothing is registered with the real atexit

    def test_h5_every_guard_test_is_sandboxed(self):  # the class: a test that hands a guard a path from a shared root
        self.assertEqual(unsandboxed_guard_tests(os.path.join(REPO, "tests")), set())

    def test_h5_every_guard_test_is_sandboxed_has_teeth(self):
        bad = ("class T:\n    def test_a(self):\n        root = helpers._TEMPLATE_ROOT[0]\n"
               "        make_repo(os.path.dirname(root))\n"
               "    def test_b(self):\n        for p in (tempfile.gettempdir(),):\n            helpers.cached_history('k', p, b)\n"
               "    def test_c(self):\n        make_repo(os.path.join(REPO, 'x'))\n")
        good = ("class T:\n    def test_a(self):\n        self.sandbox()\n        root = helpers._TEMPLATE_ROOT[0]\n"
                "        make_repo(self.inside(os.path.dirname(root)))\n"
                "    def test_b(self):\n        make_repo(self.fresh('x'))\n")
        own = "test_helpers_fixture.py"  # the file whose every function is a member of the class (row D1 (a))
        with tempfile.TemporaryDirectory(dir=self.tmp) as d, tempfile.TemporaryDirectory(dir=self.tmp) as g:
            self.write(d, own, bad.encode())
            self.write(g, own, good.encode())
            self.assertEqual(unsandboxed_guard_tests(d), {own + "::T.test_a", own + "::T.test_b", own + "::T.test_c"})
            self.assertEqual(unsandboxed_guard_tests(g), set())


class GuardScanTest(Base):
    """Rows D1, D2 (F-20261126-djav): the S1 scan ``unsandboxed_guard_tests`` over planted files in a scratch tests
    directory (the production scan, never an extracted helper). Membership (D1): every function of
    tests/test_helpers_fixture.py that names a guarded function; in any other module only a guarded call inside an
    ``assertRaises`` / ``assertRaisesRegex`` block or passed to one (a plain caller is outside the class). The closed
    grammar (D2): a path argument is accepted only in the forms listed in ``unsandboxed_guard_tests``'s docstring."""
    OWN = "test_helpers_fixture.py"
    OTHER = "test_other.py"
    SPELLINGS = (  # the seven reviewer spellings of a shared root, TMPDIR in its three forms: (label, expression)
        ("dirname-of-self-tmp", "os.path.dirname(self.tmp)"),
        ("slash", '"/"'),
        ("tempfile-tempdir", "tempfile.tempdir"),
        ("environ-subscript", 'os.environ["TMPDIR"]'),
        ("environ-get", 'os.environ.get("TMPDIR")'),
        ("os-getenv", 'os.getenv("TMPDIR")'),
        ("getcwd", "os.getcwd()"),
        ("dirname-of-file", "os.path.dirname(__file__)"),
        ("helper-method-return", "self.shared_dir()"),
        ("module-function-return", "shared_dir()"),
    )

    def scan(self, **files):
        """The set the real scan reports for a scratch directory holding ``files`` (name -> source text)."""
        d = tempfile.mkdtemp(dir=self.tmp)
        for name, src in files.items():
            self.write(d, name, src.encode("utf-8"))
        return unsandboxed_guard_tests(d)

    @staticmethod
    def guard_test(call):
        return "class T(Base):\n    def test_x(self):\n        with self.assertRaises(ValueError):\n            %s\n" % call

    def test_each_listed_spelling_is_reported_for_both_guards_in_and_outside_the_own_file(self):
        for label, expr in self.SPELLINGS:
            for call in ("make_repo(%s)", "helpers.cached_history('k', %s, build)", "_make_repo_slow(%s, {})",
                         "make_repo(tmp=%s)"):
                src = self.guard_test(call % expr)
                with self.subTest(label=label, call=call):
                    self.assertEqual(self.scan(**{self.OWN: src}), {self.OWN + "::T.test_x"})
                    self.assertEqual(self.scan(**{self.OTHER: src}), {self.OTHER + "::T.test_x"})

    def test_a_spelling_reaches_the_scan_through_a_name_or_a_conditional(self):
        for label, expr in self.SPELLINGS:
            for body in ("        p = %s\n        with self.assertRaises(ValueError):\n            make_repo(p)\n",
                         "        p = self.tmp if self.x else %s\n        with self.assertRaises(ValueError):\n            make_repo(p)\n",
                         "        for p in (self.tmp, %s):\n            with self.assertRaises(ValueError):\n                make_repo(p)\n"):
                src = "class T(Base):\n    def test_x(self):\n" + body % expr
                with self.subTest(label=label, body=body[:30]):
                    self.assertEqual(self.scan(**{self.OWN: src}), {self.OWN + "::T.test_x"})

    def reported(self, expr):
        """``expr`` as the path of a guarded call in a refusal-guard test is reported, in the own file and in another one."""
        src = self.guard_test("make_repo(%s)" % expr)
        self.assertEqual(self.scan(**{self.OWN: src}), {self.OWN + "::T.test_x"})
        self.assertEqual(self.scan(**{self.OTHER: src}), {self.OTHER + "::T.test_x"})

    def test_spelling_dirname_of_self_tmp(self):
        self.reported("os.path.dirname(self.tmp)")

    def test_spelling_slash(self):
        self.reported('"/"')

    def test_spelling_tempfile_tempdir(self):
        self.reported("tempfile.tempdir")

    def test_spelling_environ_subscript_tmpdir(self):
        self.reported('os.environ["TMPDIR"]')

    def test_spelling_environ_get_tmpdir(self):
        self.reported('os.environ.get("TMPDIR")')

    def test_spelling_getenv_tmpdir(self):
        self.reported('os.getenv("TMPDIR")')

    def test_spelling_getcwd(self):
        self.reported("os.getcwd()")

    def test_spelling_dirname_of_file(self):
        self.reported("os.path.dirname(__file__)")

    def test_spelling_helper_method_return_value(self):
        src = ("class T(Base):\n    def shared(self):\n        return os.path.dirname(self.tmp)\n"
               "    def test_x(self):\n        with self.assertRaises(ValueError):\n            make_repo(self.shared())\n")
        self.assertEqual(self.scan(**{self.OWN: src}), {self.OWN + "::T.test_x"})
        self.assertEqual(self.scan(**{self.OTHER: src}), {self.OTHER + "::T.test_x"})

    def test_the_wrapped_form_is_accepted_and_nothing_else_of_these_spellings(self):
        for label, expr in self.SPELLINGS:
            src = self.guard_test("make_repo(self.inside(%s))" % expr)
            with self.subTest(label=label):
                self.assertEqual(self.scan(**{self.OWN: src}), set())
                self.assertEqual(self.scan(**{self.OTHER: src}), set())

    def test_aliasing_a_guarded_name_or_reaching_it_through_a_string_is_reported(self):
        cases = (
            "mr = make_repo\n        with self.assertRaises(ValueError):\n            mr(self.tmp)",
            "mr = helpers.make_repo\n        with self.assertRaises(ValueError):\n            mr(self.tmp)",
            "with self.assertRaises(ValueError):\n            getattr(helpers, 'make_repo')(self.tmp)",
            "with self.assertRaises(ValueError):\n            getattr(helpers, \"make_\" \"repo\")(self.tmp)",
            "with self.assertRaises(ValueError):\n            helpers.__dict__['make_repo'](self.tmp)",
            "with self.assertRaises(ValueError):\n            globals()['cached_history']('k', self.tmp, b)",
            "with self.assertRaises(ValueError):\n            vars(helpers)['_make_repo_slow'](self.tmp, {})",
            "fn = (make_repo,)[0]\n        with self.assertRaises(ValueError):\n            fn(self.tmp)",
            "with self.assertRaises(ValueError):\n            helpers.__getattribute__('make_repo')(self.tmp)",
            "with self.assertRaises(ValueError):\n            operator.attrgetter('make_repo')(helpers)(self.tmp)",
        )
        for body in cases:
            src = "class T(Base):\n    def test_x(self):\n        " + body + "\n"
            with self.subTest(body=body.split("\n")[0]):
                self.assertEqual(self.scan(**{self.OWN: src}), {self.OWN + "::T.test_x"})
                self.assertEqual(self.scan(**{self.OTHER: src}), {self.OTHER + "::T.test_x"})

    def test_membership_a_guard_test_in_another_module_is_in_a_plain_caller_is_out(self):
        shared = "os.path.dirname(self.tmp)"
        member_forms = (
            self.guard_test("make_repo(%s)" % shared),
            "class T(Base):\n    def test_x(self):\n        self.assertRaises(ValueError, make_repo, %s)\n" % shared,
            "class T(Base):\n    def test_x(self):\n        self.assertRaisesRegex(ValueError, 'x', helpers.cached_history, 'k', %s, b)\n" % shared,
            "class T(Base):\n    def test_x(self):\n        self.assertRaises(ValueError, lambda: make_repo(%s))\n" % shared,
            "class T(Base):\n    def test_x(self):\n        with self.subTest(), self.assertRaisesRegex(ValueError, 'x'):\n            make_repo(%s)\n" % shared,
            "class T(Base):\n    def test_x(self):\n        self.assertRaises(ValueError, msg=make_repo(%s))\n" % shared,
        )
        for src in member_forms:
            with self.subTest(src=src.split("\n")[2]):
                self.assertEqual(self.scan(**{self.OTHER: src}), {self.OTHER + "::T.test_x"})
        plain = ("class T(Base):\n    def test_x(self):\n        make_repo(%s)\n"
                 "        with self.assertRaises(KeyError):\n            {}['k']\n" % shared)
        with_helper = "class T(Base):\n    def new(self):\n        return make_repo(%s)\n" % shared
        self.assertEqual(self.scan(**{self.OTHER: plain, "test_third.py": with_helper}), set())
        self.assertEqual(self.scan(**{self.OWN: plain}), {self.OWN + "::T.test_x"})  # the own file: every function is in

    def test_membership_every_function_kind_of_the_own_file_is_scanned(self):
        bad = 'make_repo("/")'
        kinds = {
            "method": ("class T(Base):\n    def test_a(self):\n        %s\n" % bad, "T.test_a"),
            "helper method": ("class T(Base):\n    def build_it(self):\n        return %s\n" % bad, "T.build_it"),
            "module function": ("def helper_fn():\n    %s\n" % bad, "helper_fn"),
            "module level": ("%s\n" % bad, "<module level>"),
            "class body": ("class T(Base):\n    made = %s\n" % bad, "T.<class body>"),
            "nested function": ("class T(Base):\n    def test_n(self):\n        def inner():\n            %s\n        inner()\n" % bad,
                                "T.test_n"),
            "nested class": ("class T(Base):\n    class U:\n        def test_u(self):\n            %s\n" % bad, "T.U.test_u"),
            "nested class body": ("class T(Base):\n    class U:\n        made = %s\n" % bad, "U.<class body>"),
            "lambda": ("class T(Base):\n    def test_l(self):\n        f = lambda: %s\n        f()\n" % bad, "T.test_l"),
            "async function": ("class T(Base):\n    async def test_s(self):\n        %s\n" % bad, "T.test_s"),
        }
        for kind, (src, key) in kinds.items():
            with self.subTest(kind=kind):
                self.assertEqual(self.scan(**{self.OWN: src}), {self.OWN + "::" + key})
        good = {kind: src.replace(bad, "make_repo(self.inside('/x'))") for kind, (src, key) in kinds.items()}
        for kind, src in good.items():
            with self.subTest(kind=kind, wrapped=True):
                self.assertEqual(self.scan(**{self.OWN: src}), set())

    def test_the_accepted_forms_of_the_grammar_and_their_look_alikes(self):
        head = "class T(Base):\n    def test_x(self):\n"
        accepted = (
            "self.tmp", "self.work", "self.fresh('a')", "self.fresh(name)", "self.sandbox()", "self.inside(x)",
            "tempfile.mkdtemp(dir=self.tmp)", "os.path.join(self.tmp, 'a', 'b')", "os.path.join(self.sandbox(), 'a')",
            "os.path.realpath(self.tmp)", "os.path.abspath(self.fresh('a'))", "self.tmp if x else self.work",
            "make_repo(self.fresh('a'))", "Str(self.tmp)", "os.fsencode(self.tmp)", "None", "3",
            "os.path.join(self.inside(p), 'a')", "_make_repo_slow(self.fresh('a'), {})", "os.path.join(self.fresh('a'), 'b', 'c')",
        )
        for expr in accepted:
            with self.subTest(accepted=expr):
                self.assertEqual(self.scan(**{self.OWN: head + "        with self.assertRaises(TypeError):\n            make_repo(%s)\n" % expr}),
                                 set())
        refused = (
            "os.path.join(self.tmp, '..')", "os.path.join(self.tmp, '../x')", "os.path.join(self.tmp, 'a/../..')",
            "os.path.join(self.tmp, '/etc')", "os.path.join(self.tmp, name)", "os.path.join(self.tmp, 'a' + x)",
            "os.path.join('/', 'a')", "os.path.join(x, 'a')", "'a'", "''", "x", "self.root", "self.tmp.upper()",
            "self.tmp + '/..'", "os.path.dirname(self.fresh('a'))", "os.path.normpath(self.tmp)", "str(self.tmp)",
            "tmp_of(self)", "[self.tmp][0]", "self.tmp[:-1]", "f'{self.tmp}/..'", "make_repo(os.getcwd())",
            "other.tmp", "other.inside(x)", "True", "self.tmp if x else '/'", "'/' if x else self.tmp", "os.path.join(self.tmp, '')",
            "os.path.join(self.tmp, 3)", "os.path.join(self.tmp, 'a', x=1)", "os.path.realpath(self.tmp, strict=True)",
            "os.path.realpath(self.tmp, '/')", "Str(self.tmp, '/')", "Str(x=self.tmp)", "os.path.join()", "os.path.join(**kw)",
            "mkdtemp(dir=self.tmp)", "other.mkdtemp()", "Str('/')", "os.fsencode('/')", "4.5", "b'/'", "self.fresh",
        )
        for expr in refused:
            with self.subTest(refused=expr):
                self.assertEqual(self.scan(**{self.OWN: head + "        with self.assertRaises(TypeError):\n            make_repo(%s)\n" % expr}),
                                 {self.OWN + "::T.test_x"})

    def test_a_name_is_accepted_only_when_every_binding_is_and_loops_need_literal_elements(self):
        head = "class T(Base):\n    def test_x(self):\n"
        ok = (
            "        p = self.fresh('a')\n        make_repo(p)\n",
            "        p = self.fresh('a')\n        q = os.path.join(p, 'b')\n        make_repo(q)\n",
            "        for p in (self.tmp, self.work):\n            make_repo(p)\n",
            "        for p, c in ((self.tmp, 1), (self.work, 2)):\n            make_repo(p)\n",
            "        with tempfile.TemporaryDirectory(dir=self.tmp) as d:\n            make_repo(d)\n",
            "        n = 'sub'\n        make_repo(os.path.join(self.tmp, n))\n",
            "        for n in ('a', 'b'):\n            make_repo(os.path.join(self.tmp, n))\n",
            "        helpers.cached_history('k', self.tmp, lambda root: make_repo(root))\n",
            "        f = lambda root: make_repo(root)\n        helpers.cached_history('k', self.tmp, f)\n",
            "        p = self.fresh('a')\n        p = os.path.join(p, 'b')\n        make_repo(p)\n",
            "        p, q = self.tmp, self.work\n        make_repo(p)\n",
            "        helpers.cached_history('k', self.tmp, build=lambda root: make_repo(root))\n",
            "        def build(root):\n            make_repo(root)\n        helpers.cached_history('k', self.tmp, build)\n",
        )
        bad = (
            "        p = self.fresh('a')\n        p = '/'\n        make_repo(p)\n",
            "        p = self.fresh('a')\n        p += '/..'\n        make_repo(p)\n",
            "        p = self.fresh('a')\n        (p := '/')\n        make_repo(p)\n",
            "        p = self.fresh('a')\n        del p\n        make_repo(p)\n",
            "        p = self.fresh('a')\n        with open('x') as p:\n            make_repo(p)\n",
            "        p = self.fresh('a')\n        try:\n            pass\n        except OSError as p:\n            make_repo(p)\n",
            "        p = self.fresh('a')\n        import os as p\n        make_repo(p)\n",
            "        for p in (self.tmp, '/'):\n            make_repo(p)\n",
            "        for p in roots():\n            make_repo(p)\n",
            "        for p in [x for x in ('/',)]:\n            make_repo(p)\n",
            "        for p, c in ((self.tmp, 1), ('/', 2)):\n            make_repo(p)\n",
            "        for p, c in rows:\n            make_repo(p)\n",
            "        for p, c in ((self.tmp,),):\n            make_repo(p)\n",
            "        for p, c in ((self.tmp, *r),):\n            make_repo(p)\n",
            "        for p, p in ((self.tmp, self.work),):\n            make_repo(p)\n",
            "        n = 'a'\n        n = n\n        make_repo(os.path.join(self.tmp, n))\n",
            "        for n in names:\n            make_repo(os.path.join(self.tmp, n))\n",
            "        for n, m in (('a', 'b'),):\n            make_repo(os.path.join(self.tmp, n))\n",
            "        f = lambda root: 0\n        helpers.cached_history('k', self.tmp, f)\n        make_repo(root)\n",
            "        for c, p in ((1, self.tmp),):\n            make_repo(p)\n            p = '/'\n",
            "        p, q = '/', self.tmp\n        make_repo(p)\n",
            "        n = '..'\n        make_repo(os.path.join(self.tmp, n))\n",
            "        for n in ('a', '..'):\n            make_repo(os.path.join(self.tmp, n))\n",
            "        helpers.cached_history('k', self.tmp, lambda root: 0)\n        make_repo(root)\n",
            "        def build(root):\n            make_repo(root)\n        other(build)\n",
            "        def build(root, extra):\n            make_repo(extra)\n        helpers.cached_history('k', self.tmp, build)\n",
            "        self.tmp = '/'\n        make_repo(self.tmp)\n",
            "        self.work = os.getcwd()\n        make_repo(self.work)\n",
            "        make_repo(*args)\n",
            "        make_repo(**kw)\n",
            "        make_repo()\n",
        )
        for body in ok:
            with self.subTest(ok=body):
                self.assertEqual(self.scan(**{self.OWN: head + body}), set())
        for body in bad:
            with self.subTest(bad=body):
                self.assertEqual(self.scan(**{self.OWN: head + body}), {self.OWN + "::T.test_x"})

    def test_a_guard_passed_by_value_maps_its_arguments_to_the_guards_parameters(self):
        head = "class T(Base):\n    def test_x(self):\n"
        cases = (  # (statement, reported)
            ("self.refused(make_repo, 'make_repo: tmp must be exactly str', Str(self.fresh('a')))", False),
            ("self.refused(make_repo, 'make_repo: tmp must be exactly str', '/')", True),
            ("self.refused(make_repo, 'x', self.fresh('a'), 1)", False),
            ("self.refused(make_repo, 'x', self.fresh('a'), os.getcwd())", False),  # the config is no path
            ("self.refused(helpers.cached_history, 'x', 'k', Str(self.tmp), build)", False),
            ("self.refused(helpers.cached_history, 'x', 'k', '/', build)", True),
            ("self.refused(helpers.cached_history, 'x', 'k', dest='/', build=build)", True),
            ("self.refused(helpers.cached_history, 'x', '/', self.tmp, build)", False),  # the key is no path
            ("self.refused(make_repo, 'x')", True),
            ("self.refused(make_repo)", True),
            ("self.refused(*args)", False),
            ("self.refused(make_repo, 'x', *rest)", True),
            ("self.assertRaises(TypeError, make_repo, self.tmp)", False),
            ("self.assertRaises(TypeError, make_repo, '/')", True),
            ("self.assertRaisesRegex(TypeError, 'x', make_repo, '/')", True),
            ("self.assertRaises(TypeError, make_repo)", True),
            ("self.other(make_repo, self.tmp)", True),  # any other consumer of the function itself
            ("fns = [make_repo]", True),
            ("x = helpers.cached_history", True),
        )
        for stmt, reported in cases:
            with self.subTest(stmt=stmt):
                self.assertEqual(self.scan(**{self.OWN: head + "        " + stmt + "\n"}),
                                 {self.OWN + "::T.test_x"} if reported else set())
        outside = "class T(Base):\n    def test_x(self):\n        self.refused(make_repo, 'x', self.tmp)\n"
        self.assertEqual(self.scan(**{self.OTHER: outside}), set())  # `refused` is the convention of the own file only
        other = ("class T(Base):\n    def test_x(self):\n        with self.assertRaises(ValueError):\n"
                 "            self.refused(make_repo, 'x', self.tmp)\n")
        self.assertEqual(self.scan(**{self.OTHER: other}), {self.OTHER + "::T.test_x"})
        wrapped = other.replace("self.tmp", "self.inside(p)")  # `refused` is unknown outside the own file: even a wrapped path is reported
        self.assertEqual(self.scan(**{self.OTHER: wrapped}), {self.OTHER + "::T.test_x"})

    def test_the_own_file_forms_are_not_accepted_in_other_modules_and_inside_is(self):
        for expr in ("self.tmp", "self.work", "self.fresh('a')", "self.sandbox()", "Str(self.tmp)"):
            with self.subTest(expr=expr):
                self.assertEqual(self.scan(**{self.OTHER: self.guard_test("make_repo(%s)" % expr)}),
                                 {self.OTHER + "::T.test_x"})
        for expr in ("self.inside(p)", "tempfile.mkdtemp()", "os.path.join(self.inside(p), 'a')", "os.fsencode(self.inside(p))"):
            with self.subTest(expr=expr):
                self.assertEqual(self.scan(**{self.OTHER: self.guard_test("make_repo(%s)" % expr)}), set())

    def test_the_build_callback_of_a_module_function_is_the_helpers_directory(self):
        src = ("def builder(root):\n    make_repo(root)\n\ndef other(root):\n    make_repo(root)\n\n"
               "class T(Base):\n    def test_x(self):\n        helpers.cached_history('k', self.tmp, builder)\n")
        self.assertEqual(self.scan(**{self.OWN: src}), {self.OWN + "::other"})
        self.assertEqual(self.scan(**{self.OWN: src.replace("builder)", "builder, 0)")}), {self.OWN + "::other"})
        src2 = src.replace("self.tmp, builder)", "self.tmp, build=builder)")
        self.assertEqual(self.scan(**{self.OWN: src2}), {self.OWN + "::other"})
        self.assertEqual(self.scan(**{self.OWN: src.replace("helpers.cached_history", "helpers.unrelated")}),
                         {self.OWN + "::builder", self.OWN + "::other"})

    def test_self_tmp_is_never_assigned_in_a_scanned_function(self):
        for stmt in ("self.tmp = '/'", "self.work = '/'", "self.tmp, self.x = '/', 1", "setattr(self, 'tmp', '/')",
                     "mock.patch.object(self, 'tmp', '/').start()"):
            src = "class T(Base):\n    def test_x(self):\n        %s\n        make_repo(self.tmp)\n" % stmt
            with self.subTest(stmt=stmt):
                self.assertEqual(self.scan(**{self.OWN: src}), {self.OWN + "::T.test_x"})

    def test_a_plain_caller_in_another_module_that_sets_self_work_is_outside_the_class(self):
        """The shape of ``tests/test_index.py`` ``Base.build``: it sets ``self.work`` and builds a history, expecting no refusal."""
        src = ("class Base(T):\n    def build(self):\n        self.work = os.path.join(self.tmp, 'w1')\n        setattr(self, 'tmp', 1)\n"
               "        cached_history('k', self.work, make)\n        make_repo(self.work)\n")
        self.assertEqual(self.scan(**{self.OTHER: src}), set())
        self.assertEqual(self.scan(**{self.OWN: src}), {self.OWN + "::Base.build"})

    def test_only_test_python_files_are_read(self):
        bad = self.guard_test("make_repo('/')")
        self.assertEqual(self.scan(**{"test_notes.txt": "def (", "helpers_x.py": bad, "testing.py": bad, "conftest.py": bad,
                                      "test_ok.py": "x = 1\n"}), set())
        self.assertEqual(self.scan(**{"test_a.py": bad}), {"test_a.py::T.test_x"})

    def test_a_string_alone_or_a_dynamic_lookup_alone_is_not_reported(self):
        head = "class T(Base):\n    def test_x(self):\n"
        for body in ("        names = ['make_repo']\n        make_repo(self.fresh('a'))\n",
                     "        x = getattr(self, 'y')\n        make_repo(self.fresh('a'))\n"):
            with self.subTest(body=body):
                self.assertEqual(self.scan(**{self.OWN: head + body}), set())

    def test_a_guarded_name_stored_to_is_reported(self):
        for stmt in ("make_repo = self.stub", "helpers.make_repo = self.stub", "cached_history, x = self.a, 1"):
            with self.subTest(stmt=stmt):
                self.assertEqual(self.scan(**{self.OWN: "class T(Base):\n    def test_x(self):\n        %s\n" % stmt}),
                                 {self.OWN + "::T.test_x"})

    def test_the_old_teeth_cases_are_still_reported_and_a_sandboxed_root_needs_the_wrapped_form(self):
        old_bad = ("class T(Base):\n    def test_a(self):\n        root = helpers._TEMPLATE_ROOT[0]\n"
                   "        make_repo(os.path.dirname(root))\n"
                   "    def test_b(self):\n        for p in (tempfile.gettempdir(),):\n            helpers.cached_history('k', p, b)\n"
                   "    def test_c(self):\n        make_repo(os.path.join(REPO, 'x'))\n"
                   "    def test_d(self):\n        self.sandbox()\n        root = helpers._TEMPLATE_ROOT[0]\n"
                   "        make_repo(os.path.dirname(root))\n")
        self.assertEqual(self.scan(**{self.OWN: old_bad}), {self.OWN + "::T.test_" + n for n in "abcd"})
        wrapped = old_bad.replace("make_repo(os.path.dirname(root))", "make_repo(self.inside(os.path.dirname(root)))")
        self.assertEqual(self.scan(**{self.OWN: wrapped}), {self.OWN + "::T.test_" + n for n in "bc"})

    def test_the_scan_over_the_real_tests_directory_reports_nothing_and_fresh_is_the_checked_form(self):
        self.assertEqual(unsandboxed_guard_tests(os.path.join(REPO, "tests")), set())
        src = inspect.getsource(Base.fresh)
        self.assertIn("self.inside(os.path.join(self.tmp, name))", src)  # `self.fresh(..)` is accepted because of this line
        # each name is chosen so that `os.mkdir` could not create anything if the check were gone: an existing directory
        # (EEXIST) or a missing parent (ENOENT), so a weakened `inside` writes nothing here
        for bad in ("..", "../x/y", "a/../..", "/etc", "a" + os.sep + ".." + os.sep + ".."):
            with self.subTest(name=bad):
                before = tree_state(self.tmp)
                with self.assertRaises(AssertionError) as cm:
                    self.fresh(bad)
                self.assertTrue(str(cm.exception).startswith("inside: "), str(cm.exception))
                self.assertEqual(tree_state(self.tmp), before)


class Probe(object):
    """A stand-in test whose own directory is ``tmp``: ``inside`` is the real ``Base.inside`` bound to it, ``fail`` raises
    ``AssertionError`` as ``TestCase.fail`` does."""
    inside = Base.inside

    def __init__(self, tmp):
        self.tmp = tmp

    def fail(self, msg=None):
        raise AssertionError(msg)


class InsideTest(Base):
    """Rows D3 and E4 (F-20261126-djav): ``Base.inside(path)``, the run-time check behind the S1 scan. D3: a seeded,
    generated matrix of path role (the argument, a parent of it, the test's own directory as holder) x file state
    (absent, regular, directory, symlink to inside, symlink to outside, FIFO, non-UTF-8 name) x relation of the
    location (equal, below, above, sibling of the holder) x spelling (exact, case-folded) x moment (at the check;
    between check and use). The expected verdict of every cell is written by hand in ``expect``, from the row: the
    path is returned only when its real path equals or lies below the real path of the holder, else the test fails
    with a message that starts ``inside:``. E4: exact ``str`` accepted; a subclass, bytes, a PathLike, None refused."""
    STATES = ("absent", "regular", "directory", "symlink-inside", "symlink-outside", "fifo", "non-utf8")
    ROLES = ("argument", "parent", "holder")
    RELATIONS = ("equal", "below", "above", "sibling")
    SPELLINGS = ("exact", "folded")
    SEEDS = tuple(range(1, 9))
    # names: ASCII, accents, case folds that change length (ß, ﬁ, İ), a code point new in Unicode 14 and one whose category
    # differs between 3.9 and 3.13, a surrogate-escaped (non-UTF-8) name, and glob or pathspec magic (* ? [ ] ! : \ and
    # git's ``:(top)``, ``:!x``, ``:/``)
    POOL = ("a", "é", "ß", "ﬁ", "İ", "x y", "dot.d", "-dash", "\U0001fae0", "ퟻ", "Ꟁ", "n\nl", "t\tb", "g*lob", "q?", "[x]",
            "[!a]", ":(top)m", ":!ex", ":(glob)r", "b\\s", "{a,b}", "~tilde", "$HOME")

    @staticmethod
    def expect(role, relation, state, spelling, case_insensitive):
        """The row, by hand. ``relation`` is where the object (the argument, or the parent of the argument) lives
        relative to the holder. A symlink state decides the real path (its target); every other state leaves the real
        path equal to the lexical location. A holder is judged by its real path, so every path equal to or below the
        holder (spelled through the holder or through a link to it) is accepted and nothing else is. The comparison
        folds case: a case-folded spelling is the same directory on a case-insensitive file system (a link in it still
        resolves), and on a case-sensitive one it names nothing that exists, so it is judged by its lexical place."""
        if role == "holder":
            if spelling == "folded" and state.startswith("symlink") and not case_insensitive:
                return False  # the folded name of the holder's link is no link: its lexical place is not the holder's real path
            return relation in ("equal", "below")
        if state == "symlink-outside":
            real_outside = True
        elif state == "symlink-inside":
            real_outside = False
        else:
            real_outside = relation not in ("equal", "below")
        if spelling == "folded" and state.startswith("symlink") and not case_insensitive:
            real_outside = relation not in ("equal", "below")  # on a case-sensitive file system the folded name is no link
        return not real_outside

    @staticmethod
    def fold(path):
        """Upper-case the ASCII letters only (the upper case of other letters can be a different name: ß -> SS)."""
        return "".join(c.upper() if c.isascii() else c for c in path)

    def world(self, rng, seed):
        """A private world under this test's own directory: ``scratch`` holds ``holder`` (the probe's own directory),
        ``outside`` (a sibling) and a target directory in each. Names are drawn from the pool, each made unique by an
        index, so no two casefold equal."""
        names = rng.sample(self.POOL, 6)
        scratch = self.fresh("world-%d" % seed)
        w = {"scratch": scratch}
        for i, key in enumerate(("holder", "outside", "in-target", "out-target", "deep", "other")):
            w[key] = names[i] + "-%d" % i
        w["holder"], w["outside"] = os.path.join(scratch, w["holder"]), os.path.join(scratch, w["outside"])
        os.mkdir(w["holder"])
        os.mkdir(w["outside"])
        w["in-target"], w["out-target"] = os.path.join(w["holder"], w["in-target"]), os.path.join(w["outside"], w["out-target"])
        os.mkdir(w["in-target"])
        os.mkdir(w["out-target"])
        return w

    @staticmethod
    def make(path, state, w):
        """Create the object of ``state`` at ``path``; True when it exists as that state (a file system may refuse a
        non-UTF-8 name: then the cell is the absent one)."""
        if state == "absent":
            return True
        if state == "directory":
            os.mkdir(path)
        elif state == "regular":
            with open(path, "wb") as fh:
                fh.write(b"x")
        elif state == "symlink-inside":
            os.symlink(w["in-target"], path)
        elif state == "symlink-outside":
            os.symlink(w["out-target"], path)
        elif state == "fifo":
            os.mkfifo(path)
        elif state == "non-utf8":
            try:
                with open(path, "wb") as fh:
                    fh.write(b"x")
            except OSError:  # EILSEQ on APFS: the name cannot exist; the check still sees the name
                return False
        return True

    def cells(self, rng, w):
        """``(role, relation, state, spelling, path, holder_spelling)``: every cell of the cross product that exists
        (an object that is the holder or its parent directory has the state ``directory`` only)."""
        out = []
        holder, scratch = w["holder"], w["scratch"]
        loc = {"below": holder, "sibling": w["outside"]}
        n = 0
        for state in self.STATES:
            for relation in ("below", "sibling"):
                for role in ("argument", "parent"):
                    n += 1
                    depth = rng.randrange(0, 3)  # directories between the location and the object
                    where = loc[relation]
                    for k in range(depth):
                        where = os.path.join(where, "d%d-%d" % (n, k))
                        os.mkdir(where)
                    name = "%s-%d" % (rng.choice(self.POOL), n) if state != "non-utf8" else os.fsdecode(b"o%d-\xff\xfe" % n)
                    obj = os.path.join(where, name)
                    self.make(obj, state, w)
                    rest = [] if role == "argument" else ["child"] + ["r%d" % k for k in range(rng.randrange(0, 2))]
                    path = os.path.join(obj, *rest)
                    out.append((role, relation, state, "exact", path, holder))
                    out.append((role, relation, state, "folded", self.fold(path), holder))
        link = os.path.join(holder, "link-to-holder")
        os.symlink(holder, link)
        for spelling, p in (("exact", holder), ("folded", self.fold(holder))):
            out.append(("argument", "equal", "directory", spelling, p, holder))
            out.append(("argument", "above", "directory", spelling, scratch if spelling == "exact" else self.fold(scratch), holder))
        out.append(("argument", "equal", "symlink-inside", "exact", link, holder))  # a link to the holder is the holder
        # the holder as a role: the probe's own directory is spelled through a link, case-folded, absent, a file, a FIFO
        for hstate in self.STATES:
            hp = os.path.join(scratch, "h-%s" % hstate)
            if hstate == "symlink-inside":
                os.symlink(holder, hp)  # a link to a directory: its real path is the holder's
            elif hstate == "symlink-outside":
                os.symlink(w["out-target"], hp)
            elif hstate == "directory":
                os.mkdir(hp)
            elif hstate == "non-utf8":
                hp = os.path.join(scratch, os.fsdecode(b"h\xff"))
            else:
                self.make(hp, hstate, w)
            for relation, rel_path in (("equal", hp), ("below", os.path.join(hp, "x", "y")),
                                       ("above", scratch), ("sibling", os.path.join(scratch, "sibling-of-h"))):
                out.append(("holder", relation, hstate, "exact", rel_path, hp))
            out.append(("holder", "below", hstate, "folded", self.fold(os.path.join(hp, "x")), hp))
        return out

    def run_cell(self, cell, case_insensitive, seed):
        role, relation, state, spelling, path, holder = cell
        want = self.expect(role, relation, state, spelling, case_insensitive)
        label = "seed=%d role=%s relation=%s state=%s spelling=%s path=%r holder=%r" % (seed, role, relation, state, spelling, path, holder)
        probe = Probe(holder)
        with mock.patch("builtins.open", side_effect=AssertionError("inside opened a file: " + label)), \
                mock.patch.object(os, "open", side_effect=AssertionError("inside opened a file: " + label)), \
                mock.patch.object(os, "mkdir", side_effect=AssertionError("inside created: " + label)), \
                mock.patch.object(os, "makedirs", side_effect=AssertionError("inside created: " + label)), \
                mock.patch.object(os, "mkfifo", side_effect=AssertionError("inside created: " + label)), \
                mock.patch.object(os, "symlink", side_effect=AssertionError("inside created: " + label)), \
                mock.patch.object(os, "rename", side_effect=AssertionError("inside moved: " + label)), \
                mock.patch.object(os, "unlink", side_effect=AssertionError("inside removed: " + label)), \
                mock.patch.object(os, "rmdir", side_effect=AssertionError("inside removed: " + label)), \
                mock.patch.object(os, "utime", side_effect=AssertionError("inside wrote: " + label)), \
                mock.patch.object(os, "chmod", side_effect=AssertionError("inside wrote: " + label)):
            try:
                got = Probe.inside(probe, path)
            except AssertionError as err:
                self.assertFalse(want, "refused but expected accepted (%s): %s" % (label, err))
                self.assertTrue(str(err).startswith("inside: "), "message of the refusal (%s): %s" % (label, err))
            else:
                self.assertTrue(want, "accepted but expected refused (%s)" % label)
                self.assertIs(got, path, label)  # returned unchanged (the same object)
        return want, label

    def test_d3_generated_path_matrix(self):
        for seed in self.SEEDS:
            rng = random.Random(seed)
            w = self.world(rng, seed)
            ci = os.path.exists(self.fold(w["holder"])) and os.path.samefile(self.fold(w["holder"]), w["holder"])
            cells = self.cells(rng, w)
            seen = collections.Counter()
            before = tree_state(w["scratch"])
            for cell in cells:
                want, label = self.run_cell(cell, ci, seed)
                seen[(cell[0], want)] += 1
                self.assertEqual(tree_state(w["scratch"]), before, "the world changed: " + label)
            # every role has accepted and refused cells, and every file state appears at least once as an argument
            self.assertEqual(set(r for r, _ in seen), set(self.ROLES), "seed=%d" % seed)
            for role in self.ROLES:
                self.assertGreater(seen[(role, True)], 0, "seed=%d role=%s" % (seed, role))
                self.assertGreater(seen[(role, False)], 0, "seed=%d role=%s" % (seed, role))
            self.assertEqual({c[2] for c in cells if c[0] != "holder"}, set(self.STATES), "seed=%d" % seed)
            self.assertEqual({c[1] for c in cells}, set(self.RELATIONS), "seed=%d" % seed)
            self.assertEqual({c[3] for c in cells}, set(self.SPELLINGS), "seed=%d" % seed)
            # the cross product: role x state x relation x spelling of the generated (non-holder) cells is complete
            keys = {(c[0], c[2], c[1], c[3]) for c in cells if c[0] != "holder" and c[1] in ("below", "sibling")}
            self.assertEqual(len(keys), 2 * len(self.STATES) * 2 * 2, "seed=%d" % seed)

    def test_d3_the_draw_is_a_function_of_the_seed(self):
        def shape(seed, call):
            rng = random.Random(seed)
            w = self.world(rng, 700 + call)  # a fresh scratch directory for each call
            return [(c[0], c[1], c[2], c[3], os.path.relpath(c[4], w["scratch"] if c[3] == "exact" else self.fold(w["scratch"])))
                    for c in self.cells(rng, w)]
        self.assertEqual(shape(3, 1), shape(3, 2))
        self.assertNotEqual(shape(3, 3), shape(4, 4))

    def test_d3_a_swap_between_check_and_use_is_seen_by_the_next_check_only(self):
        """Moment: between check and use. ``inside`` is not a lock: the answer it gave stays what it was (it returned the
        path), a component swapped for a link to outside afterwards is refused by the NEXT call. So the wrapped form
        puts the call in the argument of the guard call (the window is one argument evaluation) and ``fresh`` checks
        before it creates."""
        for seed in self.SEEDS:
            rng = random.Random(seed)
            w = self.world(rng, 50 + seed)
            probe = Probe(w["holder"])
            for role in ("argument", "parent"):
                for depth in (0, 1, 2):
                    where = os.path.join(w["holder"], "s%s%d" % (role, depth))
                    os.mkdir(where)
                    swapped = where
                    path = os.path.join(where, *["sub%d" % k for k in range(depth)] + ["leaf"])
                    label = "seed=%d role=%s depth=%d path=%r" % (seed, role, depth, path)
                    self.assertIs(Probe.inside(probe, path), path, label)  # the check passes
                    os.rename(swapped, swapped + ".moved")  # the swap, after the check and before the use
                    os.symlink(w["out-target"], swapped)
                    self.assertEqual(path, os.path.join(swapped, *["sub%d" % k for k in range(depth)] + ["leaf"]), label)
                    with self.assertRaises(AssertionError, msg=label) as cm:  # the next check sees it
                        Probe.inside(probe, path)
                    self.assertTrue(str(cm.exception).startswith("inside: "), label)
                    self.assertIn(repr(path), str(cm.exception), label)

    def test_d3_refusals_write_nothing_and_name_the_path(self):
        w = self.world(random.Random(0), 99)
        probe = Probe(w["holder"])
        before = tree_state(self.tmp)
        for path in (w["scratch"], w["outside"], os.path.join(w["outside"], "x"), "/", os.path.dirname(self.tmp), os.getcwd(),
                     os.path.join(w["holder"], "..", "outside", "x"), "relative/path", "", ".", "~", "a" + os.sep,
                     os.path.join(w["holder"], "a\0b"), os.path.join(w["holder"], "\ud800"), "\0", w["holder"] + "\0"):
            with self.subTest(path=path[:60]), self.assertRaises(AssertionError) as cm:
                Probe.inside(probe, path)
            self.assertTrue(str(cm.exception).startswith("inside: "), str(cm.exception))
            self.assertIn(repr(path), str(cm.exception))
            self.assertEqual(tree_state(self.tmp), before)
        # a name too long to exist is still a place below the holder (it is the guard's and the file system's to refuse)
        for path in (w["holder"], w["holder"] + os.sep, os.path.join(w["holder"], "a", "..", "b"), os.path.join(w["holder"], "l" * 300),
                     os.path.join(w["holder"], "l" * 70000)):
            with self.subTest(accepted=path[:60]):
                self.assertIs(Probe.inside(probe, path), path)

    def test_d3_through_the_real_test_object_the_sandbox_box_and_self_tmp_are_inside(self):
        box = self.sandbox()
        for path in (self.tmp, self.work, box, os.path.join(box, "x"), self.fresh("a"), tempfile.mkdtemp(dir=self.tmp)):
            self.assertIs(self.inside(path), path)
        for path in (os.path.dirname(self.tmp), "/", self.tmp + "-other", REPO):  # "-other": a sibling that shares the prefix
            with self.assertRaises(AssertionError) as cm:
                self.inside(path)
            self.assertTrue(str(cm.exception).startswith("inside: "), str(cm.exception))
            self.assertIn(repr(path), str(cm.exception))

    def test_d3_a_holder_that_is_the_file_system_root_holds_every_absolute_path(self):
        probe = Probe("/")  # nothing is created or opened: the check only looks at links
        for path in ("/", "/x", "/x/y", "//x"):
            with self.subTest(path=path):
                self.assertIs(Probe.inside(probe, path), path)

    def test_e4_exact_types_only_and_before_any_filesystem_call(self):
        class S(str):
            pass

        class P:
            def __fspath__(self):
                return self.path
        good = os.path.join(self.tmp, "ok")
        pathlike = P()
        pathlike.path = good
        calls = []
        with contextlib.ExitStack() as stack:
            for mod, name in ((os.path, "realpath"), (os.path, "isabs"), (os.path, "exists"), (os, "lstat"), (os, "readlink"),
                              (os, "stat")):
                stack.enter_context(mock.patch.object(mod, name, side_effect=lambda *a, _n=name, **k: calls.append(_n)))
            for bad in (S(good), os.fsencode(good), pathlike, None, 3, [good], bytearray(good, "utf-8"), ("a",)):
                with self.subTest(type=type(bad).__name__), self.assertRaises(TypeError) as cm:
                    self.inside(bad)
                self.assertEqual(str(cm.exception), "inside: path must be exactly str, not %s" % type(bad).__name__)
        self.assertEqual(calls, [])  # no filesystem call before the type refusal
        self.assertEqual(self.inside(good), good)
        self.assertIs(type(self.inside(good)), str)


class UmaskTest(Base):
    """Row F4, process state not in the template key (F-20261125-ix2g): a copy equals the slow build made under the
    caller's umask, whichever umask built the template first; two umasks in both orders, for ``make_repo`` and
    ``cached_history``. The expected tree is built with raw git in this test."""

    def modes(self, top):
        return {rel: v[:2] for rel, v in tree_state(top).items()}

    def umask(self, value):
        old = os.umask(value)
        self.addCleanup(os.umask, old)

    @staticmethod
    def raw_history(root):
        slow_build(root)
        os.makedirs(os.path.join(root, "d", "e"))
        for rel, data in (("a.txt", b"alpha\n"), ("d/e/f.txt", b"f\n"), ("run", b"#!/bin/sh\n")):
            with open(os.path.join(root, rel), "wb") as fh:
                fh.write(data)
        os.chmod(os.path.join(root, "run"), 0o755)
        os.symlink("a.txt", os.path.join(root, "ln"))
        rawok(root, "add", "-A")
        rawok(root, "commit", "-q", "--allow-empty", "-m", "one")
        rawok(root, "commit", "-q", "--allow-empty", "-m", "two")

    def test_f4_umask_make_repo_both_orders(self):
        seen = {}
        for order in ((0o077, 0o022), (0o022, 0o077)):
            self.sandbox()  # a fresh template registry per order: the first caller's umask builds the template
            for um in order:
                with self.subTest(order=order, umask=oct(um)):
                    self.umask(um)
                    tag = "%o-%o" % (order[0], um)
                    fast = make_repo(self.fresh("f" + tag))
                    slow = slow_build(self.fresh("s" + tag))
                    self.assertEqual(self.modes(fast), self.modes(slow))
                    self.assertEqual(facts(fast), facts(slow))
                    seen[um] = self.modes(fast)[".git"]
        self.assertEqual(seen[0o077], (stat.S_IFDIR, 0o700))  # the two umasks really give different trees
        self.assertEqual(seen[0o022], (stat.S_IFDIR, 0o755))

    def test_f4_umask_cached_history_both_orders(self):
        for order in ((0o077, 0o022), (0o022, 0o077)):
            self.sandbox()
            for um in order:
                with self.subTest(order=order, umask=oct(um)):
                    self.umask(um)
                    tag = "%o-%o" % (order[0], um)
                    fast, _ = helpers.cached_history("k-umask", self.fresh("f" + tag), history_build)
                    slow = self.fresh("s" + tag)
                    self.raw_history(slow)
                    self.assertEqual(self.modes(fast), self.modes(slow))
                    self.assertEqual(rawok(fast, "rev-list", "--count", "HEAD"), "3")

    def test_f4_umask_is_part_of_both_keys(self):
        self.sandbox()
        self.umask(0o077)
        make_repo(self.fresh("a"))
        helpers.cached_history("k-key", self.fresh("b"), history_build)
        before = (len(helpers._TEMPLATES), len(helpers._HISTORIES))
        self.umask(0o022)
        make_repo(self.fresh("c"))
        helpers.cached_history("k-key", self.fresh("d"), history_build)
        self.assertGreater(len(helpers._TEMPLATES), before[0])
        self.assertEqual(len(helpers._HISTORIES), before[1] + 1)


class UmaskThreadTest(Base):
    """F-20261126-jth9, row F4 / process state: ``helpers._umask`` reads the umask by setting it to 0 and putting it back,
    so two threads interleaving would leave the process umask at 0 for good. It takes ``_UMASK_LOCK`` around the pair."""

    def test_umask_reads_from_threads_leave_the_umask_alone(self):
        old_interval = sys.getswitchinterval()
        self.addCleanup(sys.setswitchinterval, old_interval)
        sys.setswitchinterval(1e-6)
        before = os.umask(0o022)
        self.addCleanup(os.umask, before)
        for round_no in range(5):
            seen, barrier = [], threading.Barrier(6)

            def hammer():
                barrier.wait()
                got = {helpers._umask() for _ in range(3000)}
                seen.append(got)
            threads = [threading.Thread(target=hammer) for _ in range(6)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            self.assertEqual(os.umask(0o022), 0o022, "round %d: the process umask was left changed" % round_no)
            self.assertEqual(seen, [{0o022}] * 6, "round %d: a thread read a umask that was not the process's" % round_no)


def process_state_sites(text):
    """``{(function, kind): locked}``: every function of ``text`` that touches process state shared by all threads:
    ``os.umask``, ``os.chdir``, ``os.putenv``, ``os.unsetenv``, ``os.environ`` (read or written) or ``tempfile.tempdir``;
    ``locked`` is true when every such use lies inside a ``with <name ending in LOCK>:`` block."""
    kinds = {"umask", "chdir", "putenv", "unsetenv", "environ"}
    out = {}

    def walk(node, qual, locked):
        for ch in ast.iter_child_nodes(node):
            if isinstance(ch, ast.ClassDef):
                walk(ch, qual + ch.name + ".", locked)
            elif isinstance(ch, (ast.FunctionDef, ast.AsyncFunctionDef)):
                walk(ch, qual + ch.name + ".", False)
            else:
                here = locked or (isinstance(ch, ast.With) and any(
                    isinstance(i.context_expr, ast.Name) and i.context_expr.id.endswith("LOCK") for i in ch.items))
                if isinstance(ch, ast.Attribute) and isinstance(ch.value, ast.Name):
                    kind = None
                    if ch.value.id == "os" and ch.attr in kinds:
                        kind = "os." + ch.attr
                    elif ch.value.id == "tempfile" and ch.attr == "tempdir":
                        kind = "tempfile.tempdir"
                    if kind:
                        key = (qual[:-1], kind)
                        out[key] = out.get(key, True) and here
                walk(ch, qual, here)
    walk(ast.parse(text), "", False)
    return out


class ProcessStateTest(Base):
    """F-20261126-jth9, the class: process-state reads and writes in ``tests/helpers.py``. The one member is
    ``_umask`` (locked). Non-members: ``_fast_path_ok``, ``make_repo`` and ``cached_history`` only read ``os.environ``
    (nothing in helpers.py writes it from a thread); ``GitIsolatedTestCase.setUp`` patches and pops ``os.environ``
    once per test, on the thread that runs the test, restored by its cleanup."""
    EXPECTED = {
        ("_umask", "os.umask"): True,  # member
        ("_fast_path_ok", "os.environ"): False,  # non-member: reads
        ("make_repo", "os.environ"): False,  # non-member: reads
        ("cached_history", "os.environ"): False,  # non-member: reads
        ("GitIsolatedTestCase.setUp", "os.environ"): False,  # non-member: one thread per test, restored by cleanup
        ("git", "os.environ"): False,  # non-member: reads
    }

    def test_helpers_touches_process_state_only_where_listed(self):
        with open(os.path.join(REPO, "tests", "helpers.py"), encoding="utf-8") as fh:
            sites = process_state_sites(fh.read())
        self.assertEqual(sites, self.EXPECTED)

    def test_every_umask_chdir_putenv_use_is_locked(self):
        with open(os.path.join(REPO, "tests", "helpers.py"), encoding="utf-8") as fh:
            sites = process_state_sites(fh.read())
        for (fn, kind), locked in sorted(sites.items()):
            if kind != "os.environ":
                with self.subTest(fn=fn, kind=kind):
                    self.assertTrue(locked, "%s: %s is not inside a lock" % (fn, kind))

    def test_scan_teeth(self):
        text = ("import os, tempfile\nL = 1\ndef a():\n    os.umask(0)\ndef b():\n    with L_LOCK:\n        os.umask(0)\n"
                "def c():\n    os.chdir('x')\n    with M_LOCK:\n        os.chdir('y')\ndef d():\n    tempfile.tempdir = 1\n"
                "class K:\n    def m(self):\n        os.environ['A'] = '1'\n")
        self.assertEqual(process_state_sites(text), {("a", "os.umask"): False, ("b", "os.umask"): True,
                                                     ("c", "os.chdir"): False, ("d", "tempfile.tempdir"): False,
                                                     ("K.m", "os.environ"): False})


class HistorySymlinkTest(Base):
    """Rows F5/F11 (F-20261125-fiw5): symlinks inside a cached history are copied as symlinks, never followed. One test
    per member: a top-level symlink to a directory, a dangling symlink, a symlink to a directory below a directory. The
    expected tree is built with raw git in the test; the copy must equal it entry by entry."""

    def check(self, label, extra, links):
        """``extra(root)`` adds files and links to a repository; ``links`` is the hand-written ``{path: target}``."""
        def build(root):
            make_repo(root)
            extra(root)
            helpers.commit_all(root, "links")
            return {}
        dest, _ = helpers.cached_history("k-sym-" + label, self.fresh("copy-" + label), build)
        want = self.fresh("want-" + label)
        slow_build(want)
        extra(want)
        rawok(want, "add", "-A")
        rawok(want, "commit", "-q", "--allow-empty", "-m", "links")
        for rel, target in links.items():
            path = os.path.join(dest, rel)
            self.assertTrue(os.path.islink(path), rel)
            self.assertEqual(os.readlink(path), target)
            self.assertEqual(rawok(dest, "ls-files", "-s", "--", rel).split()[0], "120000")
        got_tree, want_tree = tree_state(dest), tree_state(want)
        self.assertEqual(got_tree.pop(".git/index")[:2], want_tree.pop(".git/index")[:2])
        self.assertEqual(got_tree, want_tree)
        self.assertEqual(rawok(dest, "ls-files", "-s"), rawok(want, "ls-files", "-s"))
        self.assertEqual(rawok(dest, "status", "--porcelain", "--untracked-files=all"), "")

    def test_top_level_symlink_to_a_directory(self):
        def extra(root):
            os.makedirs(os.path.join(root, "realdir"))
            with open(os.path.join(root, "realdir", "inner.txt"), "wb") as fh:
                fh.write(b"inner\n")
            os.symlink("realdir", os.path.join(root, "dirlink"))
        self.check("topdir", extra, {"dirlink": "realdir"})

    def test_dangling_symlink(self):
        def extra(root):
            os.symlink("no-such-target", os.path.join(root, "dangling"))
        self.check("dangling", extra, {"dangling": "no-such-target"})

    def test_nested_symlink_to_a_directory(self):
        def extra(root):
            os.makedirs(os.path.join(root, "a", "b"))
            with open(os.path.join(root, "a", "b", "f.txt"), "wb") as fh:
                fh.write(b"f\n")
            os.symlink("b", os.path.join(root, "a", "blink"))
            os.symlink("gone", os.path.join(root, "a", "b", "dangling"))
        self.check("nested", extra, {"a/blink": "b", "a/b/dangling": "gone"})


class OptionalLocksTest(Base):
    def test_l1_helpers_git_status_leaves_the_index_alone(self):  # L1
        root = self.stat_dirty_repo()
        before = index_state(root)
        for args in (("status", "--porcelain"), ("status", "--porcelain=v1", "--untracked-files=all"),
                     ("ls-files", "-s"), ("status",), ("log", "-1"), ("rev-parse", "HEAD")):
            with self.subTest(args):
                git(root, *args)
                self.assertEqual(index_state(root), before)

    def test_l1_teeth_a_plain_status_rewrites_the_index(self):  # L1: the fixture really is the flake's state
        root = self.stat_dirty_repo()
        before = index_state(root)
        self.assertEqual(raw(root, "status", "--porcelain")[0], 0)
        self.assertNotEqual(index_state(root)[0], before[0])

    def test_l1_explicit_env_wins(self):  # L1: a caller's env overrides the default
        root = self.stat_dirty_repo()
        before = index_state(root)
        git(root, "status", "--porcelain", env={"GIT_OPTIONAL_LOCKS": "1"})
        self.assertNotEqual(index_state(root)[0], before[0])

    def test_l1_identity_and_lc_all_unchanged(self):  # the other env entries keep their values
        root = make_repo(self.fresh("id"))
        self.assertEqual(git(root, "log", "-1", "--format=%an|%ae|%cn|%ce|%at"),
                         "Fixture Author|author@example.invalid|Fixture Committer|committer@example.invalid|"
                         "1767225600")


class Str(str):
    pass


class Dict(dict):
    pass


class ExactTypeTest(Base):
    """Rows E1-E3 (owner Q-RS4-1 (A), 2026-11-26): ``git``, ``make_repo`` and ``cached_history`` accept exact types only; a
    subclass or any other type raises a named ``TypeError`` before anything is written, git is run or a build is called.
    Per parameter: the exact types are accepted, a subclass is refused."""

    def untouched(self):
        """The patches under which a refusal must not reach git, a copy, the slow build, a template or a history."""
        box = self.sandbox()
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(mock.patch.object(helpers.subprocess, "run", side_effect=AssertionError("git was run")))
        stack.enter_context(mock.patch.object(helpers.shutil, "copytree", side_effect=AssertionError("a copy was made")))
        stack.enter_context(mock.patch.object(helpers, "_make_repo_slow", side_effect=AssertionError("a slow build")))
        return box, tree_state(box), tree_state(self.tmp)

    def refused(self, fn, text, *args, **kw):
        box, in_box, in_tmp = self.untouched()
        with self.assertRaises(TypeError) as cm:
            fn(*args, **kw)
        self.assertTrue(str(cm.exception).startswith(text), str(cm.exception))
        self.assertEqual((helpers._TEMPLATE_ROOT, helpers._HISTORY_ROOT, helpers._TEMPLATES, helpers._HISTORIES),
                         ([], [], {}, {}))
        self.assertEqual((tree_state(box), tree_state(self.tmp)), (in_box, in_tmp))

    # E1 git
    def test_e1_git_root(self):
        root = make_repo(self.fresh("r"))
        self.assertEqual(git(root, "rev-parse", "--is-inside-work-tree"), "true")  # exact str accepted
        for bad in (Str(root), os.fsencode(root), None, 3):
            with self.subTest(root=type(bad).__name__):
                self.refused(git, "git: root must be exactly str", bad, "status")

    def test_e1_git_args(self):
        root = make_repo(self.fresh("r"))
        self.assertEqual(git(root, "status", "--porcelain"), "")
        for bad in (Str("status"), b"status", 5, None):
            with self.subTest(arg=type(bad).__name__):
                self.refused(git, "git: argument 1 must be exactly str", root, "status", bad)

    def test_e1_git_env(self):
        root = make_repo(self.fresh("r"))
        self.assertEqual(git(root, "status", "--porcelain", env=None), "")
        self.assertEqual(git(root, "status", "--porcelain", env={"GIT_OPTIONAL_LOCKS": "1"}), "")
        for bad in (Dict(), os.environ, [], "A=1", collections.OrderedDict()):
            with self.subTest(env=type(bad).__name__):
                self.refused(git, "git: env must be exactly dict", root, "status", env=bad)

    def test_e1_git_env_contents(self):
        """F-20261128-jkth (row E1, "env: None or an exact dict whose keys and values are exact str"): one case per member
        of the class, each refused with a named TypeError before git runs (``refused`` fails the test if git is run).
        Only harmless names (no GIT_* name, no PATH or HOME) and only ``git --version`` in this test's own directory."""
        root = self.fresh("r")
        self.assertTrue(git(root, "--version", env={"CI2_X": "v", "CI2_Y": ""}).startswith("git version"))  # exact str accepted
        cases = (  # (member, env, the message the refusal starts with)
            ("key str subclass", {Str("CI2_X"): "v"}, "git: env key must be exactly str, not Str"),
            ("value str subclass", {"CI2_X": Str("v")}, "git: env value must be exactly str, not Str"),
            ("bytes value", {"CI2_X": b"v"}, "git: env value must be exactly str, not bytes"),
            ("bytes key", {b"CI2_X": "v"}, "git: env key must be exactly str, not bytes"),
            ("int key", {1: "v"}, "git: env key must be exactly str, not int"),
            ("int value", {"CI2_X": 1}, "git: env value must be exactly str, not int"),
            ("None value", {"CI2_X": None}, "git: env value must be exactly str, not NoneType"),
            ("a later entry", {"CI2_X": "v", "CI2_Y": 2}, "git: env value must be exactly str, not int"),
        )
        for member, env, text in cases:
            with self.subTest(member=member):
                self.refused(git, text, root, "--version", env=env)

    def test_e1_git_check(self):
        root = make_repo(self.fresh("r"))
        self.assertEqual(git(root, "status", "--porcelain", check=True), "")
        self.assertEqual(git(root, "rev-parse", "--verify", "nope", check=False), "")
        for bad in (1, 0, None, "yes"):
            with self.subTest(check=repr(bad)):
                self.refused(git, "git: check must be exactly bool", root, "status", check=bad)

    # E2 make_repo
    def test_e2_make_repo_tmp(self):
        make_repo(self.fresh("ok"))  # exact str accepted
        d = os.path.join(self.tmp, "bad")
        os.mkdir(d)
        for bad in (Str(d), os.fsencode(d), None, 3):
            with self.subTest(tmp=type(bad).__name__):
                self.refused(make_repo, "make_repo: tmp must be exactly str", bad)

    def test_e2_make_repo_config(self):
        make_repo(self.fresh("none"), None)
        make_repo(self.fresh("dict"), minimal_config())  # None and an exact dict accepted
        d = os.path.join(self.tmp, "bad")
        os.mkdir(d)
        for bad in (Dict(minimal_config()), collections.OrderedDict(minimal_config()), [], "x", 0):
            with self.subTest(config=type(bad).__name__):
                self.refused(make_repo, "make_repo: config must be exactly dict", d, bad)

    # E3 cached_history
    def test_e3_cached_history_dest(self):
        helpers.cached_history("k", self.fresh("ok"), lambda root: {})
        d = os.path.join(self.tmp, "bad")
        os.mkdir(d)
        built = []
        for bad in (Str(d), os.fsencode(d), None, 3):
            with self.subTest(dest=type(bad).__name__):
                self.refused(helpers.cached_history, "cached_history: dest must be exactly str", "k", bad,
                             lambda root: built.append(root))
        self.assertEqual(built, [])

    def test_e3_cached_history_build(self):
        d = os.path.join(self.tmp, "bad")
        os.mkdir(d)

        class Callable:
            def __call__(self, root):
                return {}
        helpers.cached_history("k-callable", self.fresh("ok"), Callable())  # any callable is accepted
        for bad in (None, "build", 3, [lambda root: {}]):
            with self.subTest(build=type(bad).__name__):
                self.refused(helpers.cached_history, "cached_history: build must be callable", "k", d, bad)

    def test_e3_cached_history_key(self):
        n = 0
        for good in ("k", 3, True, None, ("a", 1, (None, False)), ()):
            n += 1
            with self.subTest(key=repr(good)):
                helpers.cached_history(good, self.fresh("ok%d" % n), lambda root: {})
        d = os.path.join(self.tmp, "bad")
        os.mkdir(d)
        for bad in (Str("k"), 1.5, [1], {"a": 1}, ("a", Str("b")), ("a", ["b"]), b"k", frozenset()):
            with self.subTest(key=repr(bad)):
                self.refused(helpers.cached_history, "cached_history: key must be built of exact", bad, d,
                             lambda root: {})


class InheritedEnvTest(Base):
    """Rows G1 and G1a (owner Q-HK5-2 (a), 2026-11-26; F-20261128-bd56): F4's inherited environment, pinned by a seeded
    generated-input test over the whole class. The members (``members``): every name of the guard's set, written here by
    hand (``SHAPING``, an oracle independent of ``helpers._REPO_SHAPING``; ``test_g1a_...`` pins the two equal),
    GIT_CONFIG_KEY_n and GIT_CONFIG_VALUE_n for n = 0 and a generated n >= 1, PATH and HOME values (HOME also unset),
    GIT_CONFIG_GLOBAL empty, unset and with unusual characters, GIT_CONFIG_NOSYSTEM other than "1" and unset, other GIT_*
    names, and the K1 / K2 texts (names and values of 4300 and 4301 digits, the code point U+1FAE0). Seed ``s`` draws the
    member ``s`` mod the member count and, from the second round on, up to two more of other names, each with a
    generated value. Expected decision (row G1, written here, not read from helpers): never the fast path for a SHAPING
    name or a GIT_CONFIG_KEY_ / GIT_CONFIG_VALUE_ name (checked through ``_fast_path_ok`` alone: git never runs under
    them); otherwise the fast path exactly under the isolated pair (GIT_CONFIG_GLOBAL=/dev/null, GIT_CONFIG_NOSYSTEM=1),
    and the result equals a slow build made with raw git under the same environment. The seed, the drawn members and
    the environment are in every failure text."""
    SHAPING = ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES",
               "GIT_NAMESPACE", "GIT_CEILING_DIRECTORIES", "GIT_INDEX_FILE", "GIT_TEMPLATE_DIR", "GIT_DEFAULT_HASH",
               "GIT_DEFAULT_REF_FORMAT", "GIT_EXEC_PATH", "GIT_CONFIG", "GIT_CONFIG_COUNT", "GIT_CONFIG_PARAMETERS",
               "GIT_CONFIG_SYSTEM")
    ROUNDS = 2
    K2 = "\U0001fae0"  # unassigned in 3.9's Unicode, a symbol in 3.13's
    TEXTS = ("", "1", "a b", "n\nl", "t\tb", "=x=", "é", K2, "9" * 4300, "1" + "0" * 4300, "/")

    def members(self):
        """``{label: function(rng) -> {name: value, or None to unset}}``; every path a value names lies in this test's
        directory. The first word of a label is its name family: one draw never holds two members of one family."""
        odd = self.fresh("odd dir é " + self.K2 + " =x")
        self.write(odd, ".gitconfig", b"[core]\n\tautocrlf = true\n[init]\n\tdefaultBranch = other\n")
        cfg = os.path.join(odd, "global config é" + self.K2)
        self.write(odd, os.path.basename(cfg), b"[core]\n\tautocrlf = true\n")
        missing = os.path.join(self.tmp, "missing")
        texts = self.TEXTS + (odd,)
        number = lambda rng: rng.choice(("1", "7", str(rng.randint(2, 10 ** 9)), "9" * 4300, "1" + "0" * 4300))  # noqa: E731
        other = {"GIT_SOMETHING_ELSE": texts, "GIT_EDITOR": texts, "GIT_OPTIONAL_LOCKS": ("0", "1"),
                 "GIT_TERMINAL_PROMPT": ("0", "1")}
        out = {}
        for name in self.SHAPING:
            out[name] = lambda rng, name=name: {name: rng.choice(texts)}
        out.update({
            "GIT_CONFIG_KEY_0": lambda rng: {"GIT_CONFIG_KEY_0": rng.choice(("a.b", "core.autocrlf") + texts)},
            "GIT_CONFIG_KEY_n": lambda rng: {"GIT_CONFIG_KEY_" + number(rng): rng.choice(("a.b",) + texts)},
            "GIT_CONFIG_VALUE_0": lambda rng: {"GIT_CONFIG_VALUE_0": rng.choice(texts)},
            "GIT_CONFIG_VALUE_n": lambda rng: {"GIT_CONFIG_VALUE_" + number(rng): rng.choice(texts)},
            "PATH value": lambda rng: {"PATH": rng.choice((odd, missing, os.path.dirname(helpers.shutil.which("git"))))
                                       + os.pathsep + os.environ["PATH"]},
            "HOME value": lambda rng: {"HOME": rng.choice((odd, "", missing))},
            "HOME unset": lambda rng: {"HOME": None},
            "GIT_CONFIG_GLOBAL empty": lambda rng: {"GIT_CONFIG_GLOBAL": ""},
            "GIT_CONFIG_GLOBAL unset": lambda rng: {"GIT_CONFIG_GLOBAL": None},
            "GIT_CONFIG_GLOBAL unusual": lambda rng: {"GIT_CONFIG_GLOBAL": rng.choice((cfg, missing + " \n" + self.K2,
                                                                                         " /dev/null", "/dev/null "))},
            "GIT_CONFIG_NOSYSTEM other": lambda rng: {"GIT_CONFIG_NOSYSTEM": rng.choice(("0", "", "true", "yes"))},
            "GIT_CONFIG_NOSYSTEM unset": lambda rng: {"GIT_CONFIG_NOSYSTEM": None},
            "GIT_other name": lambda rng: (lambda n: {n: rng.choice(other[n])})(rng.choice(sorted(other))),
            "K1 GIT_CONFIG_KEY_ of 4301 digits": lambda rng: {"GIT_CONFIG_KEY_" + "1" + "0" * 4300: "a.b"},
            "K1 GIT_CONFIG_VALUE_ of 4300 digits": lambda rng: {"GIT_CONFIG_VALUE_" + "9" * 4300: "c"},
            "K1 GIT_ name of 4300 digits": lambda rng: {"GIT_" + "9" * 4300: rng.choice(("x", "9" * 4300))},
            "K1 GIT_ value of 4301 digits": lambda rng: {"GIT_CI2_K1": "1" + "0" * 4300},
            "K2 GIT_ value": lambda rng: {"GIT_CI2_K2": "a" + self.K2},
            "K2 GIT_DIR value": lambda rng: {"GIT_DIR": os.path.join(odd, self.K2)},
        })
        return out

    def draw(self, seed, members):
        """``(labels, environment)`` for ``seed``: a function of the seed (and of this test's directory) only."""
        rng = random.Random(seed)
        labels = sorted(members)
        chosen = [labels[seed % len(labels)]]
        if seed >= len(labels):
            for label in rng.sample(labels, rng.randint(0, 2)):
                if label.split()[0] not in {c.split()[0] for c in chosen}:
                    chosen.append(label)
        env = {}
        for label in chosen:
            env.update(members[label](rng))
        return chosen, env

    def expected_fast(self):
        """Row G1 by hand, on the environment as it now is: ``(moved, fast)``."""
        present = {k for k in os.environ if k.startswith("GIT_")}
        moved = any(k in self.SHAPING or k.startswith("GIT_CONFIG_KEY_") or k.startswith("GIT_CONFIG_VALUE_")
                    for k in present)
        isolated = os.environ.get("GIT_CONFIG_GLOBAL") == "/dev/null" and os.environ.get("GIT_CONFIG_NOSYSTEM") == "1"
        return moved, not moved and isolated

    def test_g1_generated_environments_equal_a_slow_build(self):
        members = self.members()
        seeds = range(self.ROUNDS * len(members))
        drawn, guarded, built, decisions = (collections.Counter() for _ in range(4))
        for seed in seeds:
            labels, env = self.draw(seed, members)
            where = "seed %d, members %r, environment %r" % (seed, labels, env)
            drawn.update(labels)
            with self.subTest(seed=seed), mock.patch.dict(os.environ, {k: v for k, v in env.items() if v is not None}):
                for k in [k for k, v in env.items() if v is None]:
                    os.environ.pop(k, None)
                moved, fast = self.expected_fast()
                decisions["fast" if fast else "slow"] += 1
                a = self.fresh("a%d" % seed)
                self.assertEqual(helpers._fast_path_ok(a, helpers._template_root()), fast, where)
                if moved:  # a name that moves or reshapes a repository: the decision is all, git is never run under it
                    guarded.update(labels)
                    continue
                built.update(labels)
                if fast:
                    with mock.patch.object(helpers.shutil, "copytree", wraps=helpers.shutil.copytree) as copied:
                        make_repo(a)
                    self.assertGreater(copied.call_count, 0, where)
                else:
                    with self.no_copy():
                        make_repo(a)
                b = self.fresh("b%d" % seed)
                slow_build(b)
                self.assertEqual(facts(a), facts(b), where)
        moving = [m for m in members if m in self.SHAPING or m.startswith(("GIT_CONFIG_KEY", "GIT_CONFIG_VALUE", "K1 GIT_CONFIG"))
                  or m == "K2 GIT_DIR value"]
        self.assertEqual(sorted(drawn), sorted(members))  # every member is drawn
        self.assertEqual(sorted(m for m in moving if guarded[m] == 0), [])  # each moving member reaches the decision
        self.assertEqual(sorted(m for m in members if m not in moving and built[m] == 0), [])  # each other one a build
        self.assertGreater(decisions["slow"], 0)
        self.assertGreater(decisions["fast"], 0)

    def test_g1_the_draw_is_a_function_of_the_seed(self):
        members = self.members()
        seeds = range(self.ROUNDS * len(members))
        self.assertEqual([self.draw(s, members) for s in seeds], [self.draw(s, members) for s in seeds])
        self.assertGreater(len({repr(self.draw(s, members)) for s in seeds}), len(members))

    def test_g1a_the_guard_set_is_the_hand_list(self):
        self.assertEqual(len(set(self.SHAPING)), 16)
        self.assertIs(type(helpers._REPO_SHAPING), frozenset)
        self.assertEqual(sorted(helpers._REPO_SHAPING), sorted(self.SHAPING))


class TranscriptCiteTest(unittest.TestCase):
    """F-20261126-i27y, F-20261128-uu6c (row C1): in every CI2 mutation transcript (``TRANSCRIPTS``, by hand; every
    transcript whose TEST line names this module is one of them), each ``path:line`` cite is listed in ``CITES`` and
    its line on this head holds the listed text; a line number in prose is refused (a cite is the only checked form).
    Rows K1/K2: a line number of more than six digits is reported, never passed to ``int()``; the patterns are ASCII."""
    MUTATIONS = os.path.join(REPO, ".strict-delivery", "state", "plans", "2026-10-31-strict-delivery-framework", "mutations")
    TRANSCRIPTS = ("F-20261125-hqt5.md", "F-20261125-765j.md", "F-20261125-ix2g.md", "F-20261125-fiw5.md",
                   "F-20261125-zgnj.md", "F-20261126-hk6k.md", "F-20261126-yga8.md", "F-20261126-jth9.md",
                   "F-20261126-eid2.md", "F-20261126-djav.md", "F-20261126-i27y.md")
    COPY_LINE = "if os.path.isdir(src) and not os.path.islink(src):"
    CITES = {"F-20261125-fiw5.md": [("tests/helpers.py", COPY_LINE)], "F-20261126-i27y.md": [("tests/helpers.py", COPY_LINE)]}

    def cites(self, text):
        return re.findall(r"\b((?:tests|gates)/[A-Za-z0-9_/.]+\.py):([0-9]+)\b", text, re.ASCII)

    def prose(self, text):
        return re.findall(r"\b(?:lines?|l\.)\s+(?:is\s+|was\s+|at\s+|number\s+|no\.\s+)?[0-9]+\b", text,
                          re.IGNORECASE | re.ASCII)

    def read(self, path):
        with open(path, encoding="utf-8") as fh:
            return fh.read()

    def problems(self, name, text, wanted):
        """Every problem of one transcript's ``text`` against its listed cites ``wanted`` ([(path, text at the line)])."""
        found = self.cites(text)
        if [c[0] for c in found] != [w[0] for w in wanted]:
            return ["%s: cites %r, listed %r" % (name, found, [w[0] for w in wanted])]
        out = []
        for (path, line), (_, want) in zip(found, wanted):
            if len(line) > 6:
                out.append("%s: %s: a line number of %d digits" % (name, path, len(line)))
                continue
            lines = self.read(os.path.join(REPO, path)).split("\n")
            n = int(line)
            if not 1 <= n <= len(lines) or want not in lines[n - 1]:
                out.append("%s: %s:%d does not hold %r" % (name, path, n, want))
        return out + ["%s: a line number in prose: %r" % (name, p) for p in self.prose(text)]

    def test_every_cite_in_the_ci2_transcripts_is_listed_and_points_at_its_line(self):
        self.assertEqual(set(self.CITES) - set(self.TRANSCRIPTS), set())
        for name in self.TRANSCRIPTS:
            with self.subTest(transcript=name):
                text = self.read(os.path.join(self.MUTATIONS, name))
                self.assertEqual(self.problems(name, text, self.CITES.get(name, [])), [])

    def test_every_transcript_of_this_module_is_listed(self):
        mine = [n for n in sorted(os.listdir(self.MUTATIONS))
                if re.search(r"^TEST tests\.test_helpers_fixture\.", self.read(os.path.join(self.MUTATIONS, n)),
                             re.MULTILINE)]
        self.assertEqual(sorted(set(mine) - set(self.TRANSCRIPTS)), [])
        self.assertEqual(len(set(self.TRANSCRIPTS)), len(self.TRANSCRIPTS))

    def test_scan_teeth(self):
        self.assertEqual(self.cites("x tests/helpers.py:218; y gates/lib/a.py:3 and tests/b.py 4"),
                         [("tests/helpers.py", "218"), ("gates/lib/a.py", "3")])
        self.assertEqual(self.prose("the line is 269 on this head; lines 3; Line 4; at line number 5; l. 6; 102 tests"),
                         ["line is 269", "lines 3", "Line 4", "line number 5", "l. 6"])
        copy = [("tests/helpers.py", self.COPY_LINE)]
        at = self.read(os.path.join(REPO, "tests", "helpers.py")).split("\n").index("        " + self.COPY_LINE) + 1
        self.assertEqual(self.problems("t", "tests/helpers.py:%d" % at, copy), [])
        for bad in (at + 1, at - 1, 0, 999999):  # moved by one line either way, before the first line, past the last
            with self.subTest(line=bad):
                self.assertEqual(self.problems("t", "tests/helpers.py:%d" % bad, copy),
                                 ["t: tests/helpers.py:%d does not hold %r" % (bad, self.COPY_LINE)])
        self.assertEqual(self.problems("t", "no cite", copy), ["t: cites [], listed ['tests/helpers.py']"])
        self.assertEqual(self.problems("t", "tests/helpers.py:%d, line %d" % (at, at), copy),
                         ["t: a line number in prose: 'line %d'" % at])

    def test_k1_long_line_numbers_are_reported_without_int(self):
        """Row K1: 4300 and 4301 digits (3.11+ refuse ``int()`` of more than 4300 digits) give the same report on 3.9."""
        for digits in (7, 4300, 4301):
            with self.subTest(digits=digits):
                text = "tests/helpers.py:" + "1" * digits
                self.assertEqual(self.problems("t", text, [("tests/helpers.py", self.COPY_LINE)]),
                                 ["t: tests/helpers.py: a line number of %d digits" % digits])

    def test_k2_code_points_new_since_3_9_do_not_change_a_word_boundary(self):
        """Row K2: U+1E030 is a letter (Lm) in Unicode 15 (3.13) and unassigned in 3.9's Unicode 13; next to a cite or a
        prose line number it gives the same matches on both (the patterns are ASCII)."""
        ch = "\U0001E030"
        self.assertEqual(self.cites(ch + "tests/helpers.py:274" + ch), [("tests/helpers.py", "274")])
        self.assertEqual(self.prose(ch + "line 5" + ch), ["line 5"])


class MemberOracleTest(Base):
    """Row L2: every oracle in tests/ that observes ``.git`` bytes, mtimes or the index across a probe, found by
    grep (mtime, st_mtime, getmtime, index, "writes nothing", snapshot); one test per member. A member is
    immune when the probe a test takes with ``helpers.git`` (status, ls-files, diff) leaves the member's
    measurement unchanged on a stat-dirty fixture; ``teeth`` shows the measurement does see a plain
    ``git status``'s rewrite (the oracle stays as strict as before), except for the content-level members.

    Members (file: test):
      1 test_gate_index.py: Writes.test_gate_writes_nothing (size and mtime of every entry, .git included)
      2 test_hook_entry.py: PostReadTest.test_post_read_writes_nothing (sha256 of every file, .git included)
      3 test_claims_lib.py: ArgvChunkTests.test_large_claim_file_gives_verdicts, test_invariants_hold_across_chunks,
        test_failure_in_a_later_chunk (index_state: bytes and mtime of .git/index)
      4 test_gitinfo.py: test_dirty_paths_does_not_write_the_index (DP12, index bytes)
      5 test_gitinfo.py: test_does_not_write_the_index (CP20, index bytes)
      6 test_gitinfo.py: test_changed_paths_index_settings (CP14, ``ls-files -s``)
      7 test_checkpoints_lib.py: test_records_at_writes_nothing (RA20, status and ``ls-files -s``)
      8 test_gate_context.py: Receipts.test_gate_writes_nothing (RC26, mtimes outside .git and status)
      9 test_gate_cleanup.py: test_cleanup_gate_writes_nothing (OUT5) and test_gate_evidence.py: test_gate_writes_nothing
        (C10): status text only
     10 test_gate_streams.py: test_inside_pre_commit_hook_environment (BS18, real index bytes after a gate run)
     11 test_self_adoption.py: listing() (size, mode, mtime of this checkout's hooks directory, H3)
     12 test_drift_lib.py: Arguments.test_stream_errors_writes_nothing and test_status_probe_writes_nothing (``probe()``:
        status with explicit optional locks off, HEAD, index st_mtime_ns)
     13 test_drift_cli.py: test_report_writes_nothing (drift_fx.snapshot: sha256 of every path, .git included)
     14 test_gate_drift_rows.py: test_gate_writes_nothing (the same snapshot)
     15-22 test_claims_lib.py StagedBlobIdTests: test_conversion_cases_match_git_add, test_f1_reproducer_crlf_in_index_is_fresh,
        test_lf_file_and_spaces_and_dash, test_non_regular_is_stale_and_never_staged (found by the search: it also goes
        through ``verdict``), test_tab_and_newline_paths, test_no_index_entry_yet,
        test_index_from_git_index_file_is_read_and_unchanged, test_temp_index_removed_on_every_exit (index bytes
        before and after the production call, ``index_bytes``/``verdict``)
     23 test_context_cli.py Process.test_cli_leaves_index_alone (C46: ``ls-files --stage`` and the GIT_INDEX_FILE copy)
     Members 15-23 are checked by running the real test itself on a stat-dirty fixture (``run_real``). The complete list,
     per test with the checked non-members and their reasons, is LISTED_TESTS; ``test_member_list_is_complete`` compares
     it per test (a test that names an oracle pattern itself or through a helper of its file), not per file.
     Member 8 is also pinned to its real test's source and teeth by test_member8_real_test_is_the_measured_one.
    ``git diff`` is not a status probe: it refreshes a stat-dirty index even under GIT_OPTIONAL_LOCKS=0 (measured, and
    noted at test_gitinfo.py CP14), so no member's setup may probe with ``diff`` between its two measurements.
    Not members (no .git in the measurement, grep-checked): test_detect snapshot (a plain directory), test_claims_cli
    snap, test_continue_cli snap, test_decisions_cli snap, test_questions_cli snap, test_findings_cli snapshot
    (all skip .git), test_claims_cli V-8 (the claim file's mtime)."""

    def immune(self, measure, teeth=True):
        root = self.stat_dirty_repo()
        before = measure(root)
        git(root, "status", "--porcelain")
        git(root, "status")
        git(root, "ls-files", "-s")
        self.assertEqual(measure(root), before)
        if teeth:
            self.assertEqual(raw(root, "status", "--porcelain")[0], 0)
            self.assertNotEqual(measure(root), before, "the measurement does not see a plain status's index rewrite")

    def test_member1_gate_index_snapshot(self):
        from tests import test_gate_index
        self.immune(test_gate_index.snapshot)

    def test_member2_hook_entry_snapshot(self):
        from tests import test_hook_entry
        self.immune(lambda root: test_hook_entry.PostReadTest.snapshot(None, root))

    def test_member3_claims_lib_index_state(self):
        from tests import test_claims_lib
        self.immune(lambda root: test_claims_lib.ArgvChunkTests.index_state(types.SimpleNamespace(root=root)))

    def test_member4_gitinfo_dirty_paths_index_bytes(self):
        self.immune(lambda root: index_state(root)[0])

    def test_member5_gitinfo_commit_paths_index_bytes(self):
        self.immune(lambda root: index_state(root)[0])

    def test_member6_gitinfo_ls_files_stage(self):
        self.immune(lambda root: raw(root, "ls-files", "-s")[1], teeth=False)

    def test_member7_checkpoints_status_and_ls_files(self):
        self.immune(lambda root: (raw(root, "status", "--porcelain", "--untracked-files=all", optional_locks=False)[1],
                                  raw(root, "ls-files", "-s")[1]), teeth=False)

    def test_member8_gate_context_mtimes_and_status(self):
        def snap(root):
            out = {}
            for base, dirs, files in os.walk(root):
                dirs[:] = [d for d in dirs if d != ".git"]
                for n in dirs + files:
                    p = os.path.join(base, n)
                    out[p] = os.lstat(p).st_mtime_ns
            return out, raw(root, "status", "--porcelain", "--untracked-files=all", optional_locks=False)[1]
        self.immune(snap, teeth=False)

    def test_member10_gate_streams_real_index_bytes(self):
        self.immune(lambda root: index_state(root)[0])

    def test_member11_self_adoption_hooks_listing(self):
        from tests import test_self_adoption
        self.immune(lambda root: test_self_adoption.listing(os.path.join(root, ".git", "hooks")), teeth=False)

    def test_member9_status_text_oracles(self):
        self.immune(lambda root: git(root, "status", "--porcelain", "--untracked-files=all"), teeth=False)

    def test_member12_drift_lib_probe(self):  # tests/test_drift_lib.py Arguments.test_stream_errors_writes_nothing
        from tests import test_drift_lib

        def measure(root):
            with mock.patch.dict(test_drift_lib.G, {"root": root}):
                return test_drift_lib.Arguments.probe()
        self.immune(measure)

    def test_member13_drift_cli_snapshot(self):  # tests/test_drift_cli.py test_report_writes_nothing (sha256, .git included)
        from tests import test_drift_cli
        self.immune(test_drift_cli.snapshot)

    def test_member14_gate_drift_rows_snapshot(self):  # tests/test_gate_drift_rows.py test_gate_writes_nothing (same)
        from tests import test_gate_drift_rows
        self.immune(test_gate_drift_rows.snapshot)

    def test_member8_real_test_is_the_measured_one(self):
        """Member 8 is measured above by a copy of the snapshot; this pins the real test to the same shape: the walk
        leaves out ``.git`` (so a probe's index rewrite cannot show in it) and the status goes through ``helpers.git``
        (optional locks off), and the copy sees a touched file, a new file and a changed status (teeth)."""
        import inspect as _inspect
        from tests import test_gate_context
        src = _inspect.getsource(test_gate_context.Receipts.test_gate_writes_nothing)
        self.assertIn('dirs[:] = [d for d in dirs if d != ".git"]', src)
        self.assertIn('os.lstat(p).st_mtime_ns', src)
        self.assertIn('git(self.fx, "status", "--porcelain", "--untracked-files=all")', src)
        self.assertIs(test_gate_context.git, git)
        root = self.stat_dirty_repo()

        def snap():
            out = {}
            for base, dirs, files in os.walk(root):
                dirs[:] = [d for d in dirs if d != ".git"]
                for n in dirs + files:
                    p = os.path.join(base, n)
                    out[p] = os.lstat(p).st_mtime_ns
            return out, git(root, "status", "--porcelain", "--untracked-files=all")
        before = snap()
        git(root, "status")
        git(root, "ls-files", "-s")
        self.assertEqual(snap(), before)
        cfg = os.path.join(root, ".strict-delivery", "config.yml")
        os.utime(cfg, (2, 2))
        self.assertNotEqual(snap(), before)
        os.utime(cfg, (1, 1))
        self.assertEqual(snap(), before)
        self.write(root, "new.txt", b"x")
        self.assertNotEqual(snap(), before)

    # Members 15-23 (F-20261125-765j): the real test is run on a fixture whose tracked files are all stat-dirty (so a
    # plain ``git status`` would rewrite ``.git/index``), unchanged, through its own oracle; one test per member.
    def run_real(self, module, cls, name):
        """Run ``module.cls.name`` itself (its own fixture, its own oracle, no assertion changed) with every tracked
        file of its repository made stat-dirty right after ``setUp``; the fixture is proven dirty (a plain status
        rewrites the index) before the test body runs. Fails unless that one test ran and passed."""
        parent = getattr(module, cls)

        class Dirty(parent):
            def setUp(self):
                super().setUp()
                dirty(self.root)
                before = index_state(self.root)[0]
                rc, _, _ = raw(self.root, "status", "--porcelain")  # plain: refreshes (the teeth of the fixture)
                assert rc == 0 and index_state(self.root)[0] != before, "the fixture is not stat-dirty"
                dirty(self.root)

        result = unittest.TestResult()
        Dirty(name).run(result)
        self.assertEqual(result.testsRun, 1)
        self.assertEqual((result.failures, result.errors, result.skipped), ([], [], []), result.failures + result.errors)

    def test_member15_claims_lib_conversion_cases(self):
        self.run_member(15)

    def test_member16_claims_lib_f1_reproducer(self):
        self.run_member(16)

    def test_member17_claims_lib_lf_spaces_dash(self):
        self.run_member(17)

    def test_member18_claims_lib_non_regular(self):
        self.run_member(18)

    def test_member19_claims_lib_tab_and_newline_paths(self):
        self.run_member(19)

    def test_member20_claims_lib_no_index_entry_yet(self):
        self.run_member(20)

    def test_member21_claims_lib_git_index_file(self):
        self.run_member(21)

    def test_member22_claims_lib_temp_index_removed(self):
        self.run_member(22)

    def test_member23_context_cli_leaves_index_alone(self):
        self.run_member(23)

    def run_member(self, number):
        """Members 15-23: the real test, by the table ``REAL_MEMBERS`` (module, class, test method)."""
        module, cls, name = REAL_MEMBERS[number]
        self.run_real(importlib.import_module("tests." + module), cls, name)

    # F-20261126-hk6k: ``run_real`` fails when the real test fails, errors or skips (teeth: a deliberately failing,
    # erroring and skipping parent test case, and each of the nine real tests replaced by such a body).
    class Probe(GitIsolatedTestCase):
        """A parent test case of the shape ``run_real`` runs: ``self.root`` is a repository of its own."""
        def setUp(self):
            super().setUp()
            self.root = make_repo(self.work)

    BODIES = {
        "failure": lambda self: self.fail("deliberate failure"),
        "error": lambda self: (_ for _ in ()).throw(RuntimeError("deliberate error")),
        "skip": lambda self: self.skipTest("deliberate skip"),
        "pass": lambda self: None,
    }

    def probe_module(self, mode):
        probe = type("Probe", (self.Probe,), {"test_body": self.BODIES[mode]})
        return types.SimpleNamespace(Probe=probe)

    def test_run_real_fails_when_the_real_test_fails_errors_or_skips(self):
        self.run_real(self.probe_module("pass"), "Probe", "test_body")  # a passing real test passes
        for mode in ("failure", "error", "skip"):
            with self.subTest(mode=mode), self.assertRaises(AssertionError):
                self.run_real(self.probe_module(mode), "Probe", "test_body")

    def test_each_of_members_15_23_fails_when_its_real_test_fails(self):
        self.assertEqual(sorted(REAL_MEMBERS), list(range(15, 24)))
        for number, (module, cls, name) in sorted(REAL_MEMBERS.items()):
            mod = importlib.import_module("tests." + module)
            for mode in ("failure", "error", "skip"):
                with self.subTest(member=number, mode=mode), mock.patch.object(getattr(mod, cls), name, self.BODIES[mode]):
                    with self.assertRaises(AssertionError):
                        self.run_member(number)

    def test_members_15_23_oracles_see_a_plain_status(self):
        """Teeth of 15-23: their oracles (``StagedBlobIdTests.index_bytes``, the ``ls-files --stage`` and copy bytes of
        member 23) do see the rewrite a plain status makes, so a green member means the probe-free run left it alone."""
        from tests import test_claims_lib
        root = self.stat_dirty_repo()
        case = types.SimpleNamespace(root=root)
        before = test_claims_lib.StagedBlobIdTests.index_bytes(case)
        git(root, "status", "--porcelain")
        self.assertEqual(test_claims_lib.StagedBlobIdTests.index_bytes(case), before)
        self.assertEqual(raw(root, "status", "--porcelain")[0], 0)
        self.assertNotEqual(test_claims_lib.StagedBlobIdTests.index_bytes(case), before)

    def test_member_list_is_complete(self):  # per test, not per file: an unlisted test of a listed file fails here
        self.assertEqual(unlisted_oracle_tests(os.path.join(REPO, "tests")), set())

    def test_member_list_is_exact_about_its_labels(self):  # every label is a member number or a checked non-member reason
        for key, label in LISTED_TESTS.items():
            with self.subTest(key):
                self.assertRegex(label, r"^(M\d+|N-(env|own-mtime|plain-dir|tree-without-git|exists|state-file))$")
        self.assertEqual(sorted({int(v[1:]) for v in LISTED_TESTS.values() if v.startswith("M")}), list(range(1, 24)))

    def test_oracle_closure_has_teeth_for_every_branch(self):
        """F-20261126-eid2: every branch of the call closure of ``oracle_tests`` (which functions a test reaches by name):
        a method calling a method of its class, a method calling a module-level function, a module-level test calling a
        module-level function or a method of any class, two links, a cycle; and what it must NOT follow (a method of
        another class), a helper nobody calls, a file that is not a test file and this file."""
        mtime = "'st_mtime'"
        body = (
            "def mod_helper():\n    return %(m)s\n"
            "def far():\n    return mod_helper()\n"
            "def loop_a():\n    loop_b()\n"
            "def loop_b():\n    loop_a()\n    return %(m)s\n"
            "def unused():\n    return %(m)s\n"
            "def test_module_calls_module():\n    mod_helper()\n"
            "def test_module_calls_method():\n    method_only()\n"
            "class Other:\n    def method_only(self):\n        return %(m)s\n"
            "    def other_class_only(self):\n        return %(m)s\n"
            "class T:\n"
            "    def same(self):\n        return %(m)s\n"
            "    def test_same_class(self):\n        self.same()\n"
            "    def test_module_level_helper(self):\n        mod_helper()\n"
            "    def test_two_links(self):\n        far()\n"
            "    def test_cycle(self):\n        loop_a()\n"
            "    def test_other_class_is_not_followed(self):\n        self.other_class_only()\n"
            "    def test_calls_nothing(self):\n        pass\n"
        ) % {"m": mtime}
        with tempfile.TemporaryDirectory(dir=self.tmp) as d:
            self.write(d, "test_closure.py", body.encode())
            self.write(d, "helper_closure.py", body.encode())  # not a test file
            self.write(d, "test_helpers_fixture.py", body.encode())  # this file is the oracle's own
            got = set(oracle_tests(d))
        want = {"test_closure.py::" + n for n in (
            "test_module_calls_module", "test_module_calls_method", "T.test_same_class", "T.test_module_level_helper",
            "T.test_two_links", "T.test_cycle")}
        self.assertEqual(got, want)

    def test_member_list_has_teeth(self):  # a new test that names a pattern is found, in a new file or a listed one
        for pattern in ORACLE_PATTERNS:
            body = "class T:\n    def helper(self):\n        return %r\n    def test_new(self):\n        self.helper()\n" % pattern
            with self.subTest(pattern=pattern), tempfile.TemporaryDirectory(dir=self.tmp) as d:
                self.write(d, "test_new_oracle.py", body.encode())
                self.write(d, "test_quiet.py", b"class T:\n    def test_q(self):\n        pass\n")
                # a listed file: its listed test is accepted, a new test next to it is found
                self.write(d, "test_gitinfo.py", (
                    "class DirtyPaths:\n    def test_dirty_paths_does_not_write_the_index(self):\n        x = %r\n"
                    "    def test_added_later(self):\n        x = %r\n" % (pattern, pattern)).encode())
                self.assertEqual(unlisted_oracle_tests(d), {"test_new_oracle.py::T.test_new",
                                                            "test_gitinfo.py::DirtyPaths.test_added_later"})
        with tempfile.TemporaryDirectory(dir=self.tmp) as d:  # the drift_fx snapshot is an oracle of ``.git`` bytes
            self.write(d, "test_drifty.py", b"from tests.drift_fx import snapshot\n\nclass T:\n    def test_d(self):\n"
                                            b"        snapshot('.')\n")
            self.write(d, "test_plain.py", b"class T:\n    def test_d(self):\n        snapshot('.')\n")
            self.assertEqual(unlisted_oracle_tests(d), {"test_drifty.py::T.test_d"})


REAL_MEMBERS = {
    15: ("test_claims_lib", "StagedBlobIdTests", "test_conversion_cases_match_git_add"),
    16: ("test_claims_lib", "StagedBlobIdTests", "test_f1_reproducer_crlf_in_index_is_fresh"),
    17: ("test_claims_lib", "StagedBlobIdTests", "test_lf_file_and_spaces_and_dash"),
    18: ("test_claims_lib", "StagedBlobIdTests", "test_non_regular_is_stale_and_never_staged"),
    19: ("test_claims_lib", "StagedBlobIdTests", "test_tab_and_newline_paths"),
    20: ("test_claims_lib", "StagedBlobIdTests", "test_no_index_entry_yet"),
    21: ("test_claims_lib", "StagedBlobIdTests", "test_index_from_git_index_file_is_read_and_unchanged"),
    22: ("test_claims_lib", "StagedBlobIdTests", "test_temp_index_removed_on_every_exit"),
    23: ("test_context_cli", "Process", "test_cli_leaves_index_alone"),
}

ORACLE_PATTERNS = ("st_mtime", "getmtime", ".git/index", '".git", "index"', "GIT_OPTIONAL_LOCKS", "writes_nothing")


def dirty(root):
    """Make every tracked file of ``root`` stat-dirty with equal content (mtime 1)."""
    for rel in rawok(root, "ls-files").splitlines():
        os.utime(os.path.join(root, rel), (1, 1))


def oracle_tests(tests_dir):
    """``{"file::Class.test": patterns}``: every test function of every ``test_*.py`` under ``tests_dir`` (this file
    excepted) whose own source, or the source of any function of the same file it calls by name (transitively, helpers
    of its class or of the module), names an oracle pattern (an mtime, ``.git/index``, ``GIT_OPTIONAL_LOCKS``, a
    "writes nothing" test) or, in a file importing ``tests.drift_fx``, calls its ``snapshot`` (a hash of ``.git``)."""
    out = {}
    for name in sorted(os.listdir(tests_dir)):
        if not (name.startswith("test_") and name.endswith(".py")) or name == "test_helpers_fixture.py":
            continue
        with open(os.path.join(tests_dir, name), encoding="utf-8") as fh:
            text = fh.read()
        lines = text.split("\n")
        defs = []

        def walk(node, prefix, cls):
            for ch in ast.iter_child_nodes(node):
                if isinstance(ch, ast.ClassDef):
                    walk(ch, prefix + ch.name + ".", ch.name)
                elif isinstance(ch, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    defs.append((prefix + ch.name, cls, ch))
                    walk(ch, prefix + ch.name + ".", cls)
        walk(ast.parse(text), "", None)
        by_simple = {}
        for q, c, n in defs:
            by_simple.setdefault(n.name, []).append((q, c))
        direct, calls = {}, {}
        for q, c, n in defs:
            seg = "\n".join(lines[n.lineno - 1:n.end_lineno])
            direct[q] = [p for p in ORACLE_PATTERNS if p in seg]
            calls[q] = set()
            for sub in ast.walk(n):
                if isinstance(sub, ast.Call):
                    calls[q].add(getattr(sub.func, "attr", getattr(sub.func, "id", "")))
            if "snapshot" in calls[q] and "tests.drift_fx" in text:
                direct[q].append("drift_fx.snapshot")
        for q, c, n in defs:
            if not n.name.startswith("test"):
                continue
            seen, todo, hit = set(), [q], set()
            while todo:
                cur = todo.pop()
                if cur in seen:
                    continue
                seen.add(cur)
                hit.update(direct[cur])
                for called in calls[cur]:
                    todo.extend(q2 for q2, c2 in by_simple.get(called, []) if c2 == c or c2 is None or c is None)
            if hit:
                out[name + "::" + q] = sorted(hit)
    return out


def unlisted_oracle_tests(tests_dir):
    return set(oracle_tests(tests_dir)) - set(LISTED_TESTS)


# Every test that names an oracle pattern, with its member number (M) or the reason it is a checked non-member:
# N-env: sets or copies ``.git/index`` as an input (``GIT_INDEX_FILE``), compares no index bytes or mtimes across a probe;
# N-own-mtime: the test sets the mtime itself; N-plain-dir: snapshot of a plain directory or of a tree without ``.git``;
# N-tree-without-git: a snapshot that skips ``.git``; N-exists: only the existence of a file in a repository of its own;
# N-state-file: compares the bytes, mtime and directory listing of a hook state file in the test's data directory (its
# snap() never reads ``.git``), so a probe's rewrite of the repository's index cannot change what it compares.
LISTED_TESTS = {
    "test_gate_index.py::Writes.test_gate_writes_nothing": "M1",
    "test_hook_entry.py::PostReadTest.test_post_read_writes_nothing": "M2",
    "test_claims_lib.py::ArgvChunkTests.test_failure_in_a_later_chunk": "M3",
    "test_claims_lib.py::ArgvChunkTests.test_invariants_hold_across_chunks": "M3",
    "test_claims_lib.py::ArgvChunkTests.test_large_claim_file_gives_verdicts": "M3",
    "test_gitinfo.py::DirtyPaths.test_dirty_paths_does_not_write_the_index": "M4",
    "test_gitinfo.py::P23dGitinfoTest.test_does_not_write_the_index": "M5",
    "test_gitinfo.py::ChangedPaths.test_changed_paths_index_settings": "M6",
    "test_checkpoints_lib.py::RecordsAt.test_records_at_writes_nothing": "M7",
    "test_gate_context.py::Receipts.test_gate_writes_nothing": "M8",
    "test_gate_cleanup.py::OutputTests.test_cleanup_gate_writes_nothing": "M9",
    "test_gate_evidence.py::InputFailures.test_gate_writes_nothing": "M9",
    "test_gate_streams.py::RowsD.test_inside_pre_commit_hook_environment": "M10",
    "test_self_adoption.py::CopyTest.test_hooks_in_a_disposable_clone": "M11",
    "test_drift_lib.py::Arguments.test_stream_errors_writes_nothing": "M12",
    "test_drift_lib.py::Arguments.test_status_probe_writes_nothing": "M12",
    "test_drift_cli.py::Report.test_report_writes_nothing": "M13",
    "test_gate_drift_rows.py::ProgramLines.test_gate_writes_nothing": "M14",
    "test_claims_lib.py::StagedBlobIdTests.test_conversion_cases_match_git_add": "M15",
    "test_claims_lib.py::StagedBlobIdTests.test_f1_reproducer_crlf_in_index_is_fresh": "M16",
    "test_claims_lib.py::StagedBlobIdTests.test_lf_file_and_spaces_and_dash": "M17",
    "test_claims_lib.py::StagedBlobIdTests.test_non_regular_is_stale_and_never_staged": "M18",
    "test_claims_lib.py::StagedBlobIdTests.test_tab_and_newline_paths": "M19",
    "test_claims_lib.py::StagedBlobIdTests.test_no_index_entry_yet": "M20",
    "test_claims_lib.py::StagedBlobIdTests.test_index_from_git_index_file_is_read_and_unchanged": "M21",
    "test_claims_lib.py::StagedBlobIdTests.test_temp_index_removed_on_every_exit": "M22",
    "test_context_cli.py::Process.test_cli_leaves_index_alone": "M23",
    "test_claims_lib.py::StagedBlobIdTests.test_racy_entry_is_rehashed": "N-own-mtime",
    "test_claims_lib.py::StagedBlobIdTests.test_repository_without_index_file": "N-exists",
    "test_claims_cli.py::VerifyTests.test_verify_idempotent": "N-own-mtime",
    "test_claims_cli.py::AddFlagTests.test_add_without_contradiction_writes_nothing": "N-tree-without-git",
    "test_decisions_cli.py::Batch.test_batch_writes_nothing": "N-tree-without-git",
    "test_decisions_cli.py::Overrides.test_ask_fixed_override_writes_nothing": "N-tree-without-git",
    "test_decisions_cli.py::PlanTests.test_ask_one_option_writes_nothing": "N-tree-without-git",
    "test_questions_cli.py::ListOutput.test_list_writes_nothing": "N-tree-without-git",
    "test_index.py::Overview2.test_regenerate_writes_nothing_on_refusal": "N-tree-without-git",
    "test_index.py::Overview2.test_render_writes_nothing_overview_2": "N-tree-without-git",
    "test_store.py::LoadTest.test_symlinked_register_path_refused_by_create_and_writes_nothing": "N-tree-without-git",
    "test_detect.py::OrderAndEffectTests.test_detect_has_no_side_effects": "N-plain-dir",
    "test_detect.py::OrderAndEffectTests.test_no_side_effects_on_problem_paths": "N-plain-dir",
    "test_detect.py::OrderTests.test_no_side_effects_on_problem_paths": "N-plain-dir",
    "test_detect.py::OrderTests.test_no_side_effects_with_every_source": "N-plain-dir",
    "test_drift_lib.py::MergedAt.test_merged_at_with_git_index_file": "N-env",
    "test_gate_cleanup.py::OutputTests.test_cleanup_in_hook_environment": "N-env",
    "test_gate_context.py::Lists.test_git_config_noise_has_no_effect": "N-env",
    "test_gate_index.py::CleanAndArgs.test_index_with_git_index_file": "N-env",
    "test_githooks.py::CommandsTestTest.test_commands_test_environment": "N-env",
    "test_githooks.py::FlaggedPathsTest.test_flagged_paths_git_failure": "N-env",
    "test_githooks.py::FlaggedPathsTest.test_flagged_paths_index_file": "N-env",
    "test_githooks.py::PreCommitTest.test_fsmonitor_hidden_change_refuses_commit": "N-env",
    "test_githooks.py::PreCommitTest.test_index_file_forms": "N-env",
    "test_githooks.py::PreCommitTest.test_relative_index_file_with_cd_shim": "N-env",
    "test_githooks.py::PreCommitTest.test_shim_under_each_posix_shell": "N-env",
    "test_githooks.py::UnstagedPathsTest.test_unstaged_paths_git_failure": "N-env",
    "test_githooks.py::UnstagedPathsTest.test_unstaged_paths_index_file": "N-env",
    "test_gitinfo.py::DirtyPaths.test_dirty_paths_call_form": "N-env",
    "test_gitinfo.py::DirtyPaths.test_dirty_paths_inherits_git_index_file": "N-env",
    "test_gitinfo.py::EnvAndFlagsTest.test_repository_env_names_cleared": "N-env",
    "test_gitinfo.py::LastTextTests.test_last_text_call_shape": "N-env",
    "test_gitinfo.py::P23dGitinfoTest.test_ignores_user_config_and_index_file": "N-env",
    "test_gitinfo.py::TrackedFilesTest.test_git_index_file_is_honoured": "N-env",
    "test_gitinfo.py::UpstreamOfTests.test_upstream_of_inherits_index_env": "N-env",
    "test_hook_entry.py::SilentTest.test_inherited_git_env_ignored": "N-env",
    "test_hookio.py::ContextTest.test_inherited_git_env_ignored": "N-env",
    "test_hook_edit.py::ReviewOneTest.test_no_match_leaves_store_unchanged": "N-state-file",
    # from main 3787493 (config 4a-4c): the snapshot of test_managed skips ``.git`` (``if ".git" in d.split(os.sep): continue``);
    # test_render_writes_nothing compares directory listings of a template directory, no repository
    "test_managed.py::ApplyTests.test_apply_precheck_writes_nothing": "N-tree-without-git",
    "test_managed.py::PlanTests.test_plan_writes_nothing": "N-tree-without-git",
    "test_templates.py::TestRender.test_render_writes_nothing": "N-plain-dir",
    # from main c2ba203 (CI3): SwapAfterCheckTest sets the mtime of its own outside file (os.utime) and compares only that file, never .git
    "test_ci_mutants.py::SwapAfterCheckTest.test_a_hard_link_swapped_in_at_every_open_of_the_target_is_never_written_through": "N-own-mtime",
    "test_ci_mutants.py::SwapAfterCheckTest.test_a_hard_link_to_a_file_outside_the_root_keeps_the_outside_bytes_when_the_write_open_is_refused": "N-own-mtime",
    "test_ci_mutants.py::SwapAfterCheckTest.test_a_parent_at_every_depth_swapped_for_a_symlink_is_never_followed": "N-own-mtime",
    "test_ci_mutants.py::SwapAfterCheckTest.test_a_parent_at_every_depth_that_is_a_symlink_at_the_check_is_refused": "N-own-mtime",
    "test_ci_mutants.py::SwapAfterCheckTest.test_a_parent_directory_swapped_for_a_symlink_is_never_followed": "N-own-mtime",
    "test_ci_mutants.py::SwapAfterCheckTest.test_a_regular_file_renamed_over_the_path_from_elsewhere_in_the_tree_is_an_error": "N-own-mtime",
    "test_ci_mutants.py::SwapAfterCheckTest.test_o_nofollow_a_symlink_swapped_in_is_never_followed": "N-own-mtime",
    "test_ci_mutants.py::SwapAfterCheckTest.test_o_nonblock_a_fifo_swapped_in_never_blocks_the_open": "N-own-mtime",
    "test_ci_mutants.py::SwapAfterCheckTest.test_the_regular_file_check_on_the_opened_file": "N-own-mtime",
    "test_ci_mutants.py::SwapAfterCheckTest.test_the_write_open_before_the_run_never_follows_a_swap": "N-own-mtime",
    "test_ci_mutants.py::SwapAfterCheckTest.test_the_write_open_of_the_restore_never_follows_a_swap": "N-own-mtime",
}
