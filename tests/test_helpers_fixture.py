"""Tests of Task CI2 (test-suite speed): the per-process template behind ``tests.helpers.make_repo`` (input-domain table
task-CI2-domain.md rows F1-F10, K1-K3, H1-H7) and the optional-locks default of ``helpers.git`` with the ``.git`` mtime
and index oracles (rows L1, L2).

Expected values are built here with raw ``git`` commands (an oracle independent of ``helpers``): the same commands the
slow path ran before this task, never a second call of the code under test."""
import hashlib
import inspect
import os
import stat
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

from tests import helpers
from tests.helpers import GitIsolatedTestCase, git, make_repo, minimal_config

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MINIMAL_TEXT = "schema: config/2\nframework_version: 0.0.0\nprofile: strict\n"
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
    """What ``make_repo`` built before the template: init, five config lines, the config file, add, commit."""
    rawok(root, "init", "-q", "-b", "main")
    for k, v in (("user.email", "fixture@example.invalid"), ("user.name", "Fixture"), ("commit.gpgsign", "false"),
                 ("maintenance.auto", "false"), ("gc.auto", "0")):
        rawok(root, "config", k, v)
    path = os.path.join(root, ".strict-delivery", "config.yml")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)
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
        d = os.path.join(self.tmp, name)
        os.mkdir(d)
        return d

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
        self.assertEqual(f["bytes"], {".strict-delivery/config.yml": MINIMAL_TEXT.encode()})
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
        make_repo(self.fresh("warm"))
        root = helpers._TEMPLATE_ROOT[0]
        tpl = next(iter(helpers._TEMPLATES.values()))
        before = tree_state(root)
        inner = os.path.join(tpl, "subdir")
        for label, path in (("root itself", root), ("template", tpl), (".git of the template", os.path.join(tpl, ".git")),
                            ("missing under it", inner), ("parent of the root", os.path.dirname(root))):
            with self.subTest(label), self.assertRaises(ValueError) as cm:
                make_repo(path)
            self.assertIn("overlaps the fixture template directory", str(cm.exception))
        self.assertEqual(tree_state(root), before)
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
     12 tests/test_drift_lib.py: Arguments.test_stream_errors_writes_nothing (PR-5c; not on origin/main, the records
        stream owns it; the same measure as member 1 or 3, covered by their tests)
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

    def test_member_list_is_complete(self):  # the grep that produced the list: every file naming an oracle over .git
        found = set()
        for name in sorted(os.listdir(os.path.join(REPO, "tests"))):
            if not (name.startswith("test_") and name.endswith(".py")) or name == "test_helpers_fixture.py":
                continue
            with open(os.path.join(REPO, "tests", name), encoding="utf-8") as fh:
                text = fh.read()
            if "st_mtime" in text or "getmtime" in text or ".git/index" in text or '".git", "index"' in text:
                found.add(name)
        # every file the grep finds is either a member above or one of the listed non-members
        self.assertEqual(found - {"test_gate_index.py", "test_claims_lib.py", "test_gitinfo.py", "test_gate_context.py",
                                  "test_detect.py", "test_claims_cli.py", "test_context_cli.py", "test_githooks.py",
                                  "test_hookio.py", "test_program_merged.py", "test_drift_lib.py", "test_hook_entry.py",
                                  "test_gate_cleanup.py", "test_self_adoption.py", "test_gate_streams.py"}, set())
