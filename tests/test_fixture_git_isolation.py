"""Tests of the fixture git configuration (Task L2.1a, process learnings B5): ``helpers.fixture_gitconfig``, the
``GIT_CONFIG_GLOBAL`` of ``GitIsolatedTestCase``, the two local keys of ``make_repo``, and the scan of every
repository creation in ``tests/*.py``.

Row ids in comments: B1-B6, M1 (the transport child), V4 of the Task L2.1 input-domain table; X5, FG1-FG4, G3, PM2 of
the controller's rows. Every path a test here creates or passes lies under the test's own ``mkdtemp`` sandbox
(``self.tmp``); a call that is meant to be refused before any write runs with ``os.open`` replaced by a function that
fails the test, so a failed guard writes nothing anywhere (FG4)."""
import ast
import errno
import importlib
import itertools
import json
import os
import random
import stat
import subprocess
import types
import unittest
from pathlib import PurePosixPath
from unittest import mock

from tests import helpers
from tests.helpers import (CLEARED_ENV, GITCONFIG_TEXT, FixtureGitConfigRefused, GitIsolatedTestCase, commit_all,
                           fixture_gitconfig, git, make_repo, within)

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
FF = os.fsdecode(b"\xff")
SKIP_FF = "APFS refuses non-UTF-8 names (EILSEQ)"
MAINT = {"maintenance", "gc"}
EXPECTED_TEXT = "[maintenance]\n\tauto = false\n[gc]\n\tauto = 0\n"
# Every class that creates a repository and is not (yet) a GitIsolatedTestCase, with the request that fixes it.
EXEMPT = {("tests/test_drift_lib.py", "MergedAt"): "Rq-L2-2"}
IDENTITY = {"GIT_AUTHOR_NAME": "A", "GIT_AUTHOR_EMAIL": "a@example.invalid", "GIT_COMMITTER_NAME": "A",
            "GIT_COMMITTER_EMAIL": "a@example.invalid"}


def creation_calls(tests_dir):
    """``(rel, line, class, function)`` of every ``git(<root>, "init"|"clone", ...)`` and
    ``subprocess.*(["git", "init"|"clone", ...])`` call in ``tests/*.py`` (``ast``; class and function are the
    innermost enclosing names, ``None`` at module level)."""
    out = []
    for fn in sorted(os.listdir(tests_dir)):
        if not fn.endswith(".py"):
            continue
        with open(os.path.join(tests_dir, fn), encoding="utf-8") as fh:
            tree = ast.parse(fh.read())

        def walk(node, cls, func):
            for child in ast.iter_child_nodes(node):
                c, f = cls, func
                if isinstance(child, ast.ClassDef):
                    c = child.name
                elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    f = child.name
                elif isinstance(child, ast.Call) and is_creation(child):
                    out.append(("tests/" + fn, child.lineno, cls, func))
                walk(child, c, f)

        walk(tree, None, None)
    return out


def is_creation(call):
    f = call.func
    if isinstance(f, ast.Name) and f.id == "git":
        return len(call.args) >= 2 and isinstance(call.args[1], ast.Constant) and call.args[1].value in ("init", "clone")
    if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id == "subprocess":
        if call.args and isinstance(call.args[0], ast.List):
            el = call.args[0].elts
            return (len(el) >= 2 and isinstance(el[0], ast.Constant) and el[0].value == "git"
                    and isinstance(el[1], ast.Constant) and el[1].value in ("init", "clone"))
    return False


def source_sets_up_fixture(src):
    """Whether the module source has a ``setUpModule`` that calls ``fixture_gitconfig`` (what Rq-L2-2 makes
    ``tests/test_drift_lib.py`` do): every test of that module then runs under the fixture global config."""
    for node in ast.parse(src).body:
        if isinstance(node, ast.FunctionDef) and node.name == "setUpModule":
            for call in ast.walk(node):
                if isinstance(call, ast.Call):
                    f = call.func
                    if (isinstance(f, ast.Name) and f.id == "fixture_gitconfig") or (
                            isinstance(f, ast.Attribute) and f.attr == "fixture_gitconfig"):
                        return True
    return False


def module_sets_up_fixture(rel):
    with open(os.path.join(os.path.dirname(TESTS_DIR), rel), encoding="utf-8") as fh:
        return source_sets_up_fixture(fh.read())


def covered(rel, cls, load=importlib.import_module, sets_up=module_sets_up_fixture):
    """Whether a repository creation in class ``cls`` of the module ``rel`` runs under the fixture git config: the
    class is a ``GitIsolatedTestCase``, or its module's ``setUpModule`` calls ``fixture_gitconfig``."""
    if sets_up(rel):
        return True
    mod = load(rel[:-3].replace("/", "."))
    c = getattr(mod, cls, None) if cls is not None else None
    return isinstance(c, type) and issubclass(c, GitIsolatedTestCase)


def trace_children(tmp, name, run):
    """The argv lists of every ``child_start`` event of the git commands ``run(extra_env)`` starts; the trace is
    asserted live (a ``start`` event exists)."""
    trace = os.path.join(tmp, "trace-%s.jsonl" % name)
    with mock.patch.dict(os.environ, {"GIT_TRACE2_EVENT": trace}):
        run({"GIT_TRACE2_EVENT": trace})
    with open(trace, encoding="utf-8") as fh:
        events = [json.loads(line) for line in fh.read().split("\n") if line.strip()]
    assert any(e.get("event") == "start" for e in events), "the trace is not live"
    return events, [e.get("argv", []) for e in events if e.get("event") == "child_start"]


def has_maintenance(children):
    return any(MAINT & set(argv) for argv in children)


def snapshot(top):
    """Every entry under ``top`` by relative path: regular files with their bytes, links with their text, never
    followed and never opened (a FIFO is not read)."""
    out = {}
    for dirpath, dirnames, filenames in os.walk(top, followlinks=False):
        for name in dirnames + filenames:
            p = os.path.join(dirpath, name)
            mode = os.lstat(p).st_mode
            rel = os.path.relpath(p, top)
            if stat.S_ISLNK(mode):
                out[rel] = ("l", os.readlink(p))
            elif stat.S_ISREG(mode):
                with open(p, "rb") as fh:
                    out[rel] = ("f", fh.read())
            elif stat.S_ISDIR(mode):
                out[rel] = ("d",)
            else:
                out[rel] = ("o", stat.S_IFMT(mode))
    return out


class FixtureGitConfigTest(GitIsolatedTestCase):
    def kinds(self):
        """``(name, run)`` for each way a fixture creates a repository; each run also commits (and pushes)."""
        def sub(*args):  # the environment is read at the call, so the trace variable of the run is in it
            subprocess.run(["git"] + list(args), env=dict(os.environ, LC_ALL="C", **IDENTITY), check=True, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE)

        def made(name):
            path = os.path.join(self.tmp, name)
            os.mkdir(path)
            return path

        def k_make_repo(_e):
            r = make_repo(made("k1"))
            commit_all(r, "c")

        def k_helper_init(_e):
            r = made("k2")
            git(r, "init", "-q", "-b", "main")
            git(r, "commit", "-q", "--allow-empty", "-m", "m")

        def k_subprocess_init(_e):
            r = made("k3")
            sub("init", "-q", "-b", "main", r)
            sub("-C", r, "commit", "-q", "--allow-empty", "-m", "m")

        def k_clone(_e):
            src = make_repo(made("k4src"))
            dst = os.path.join(self.tmp, "k4dst")
            git(self.tmp, "clone", "-q", "--", src, dst)
            git(dst, "commit", "-q", "--allow-empty", "-m", "m")

        def k_bare_push(_e):
            r = make_repo(made("k5"))
            bare = os.path.join(self.tmp, "k5.git")
            git(self.tmp, "init", "-q", "--bare", "--", bare)
            commit_all(r, "c")
            git(r, "push", "-q", bare, "main")

        def k_worktree(_e):
            r = make_repo(made("k6"))
            wt = os.path.join(self.tmp, "k6wt")
            git(r, "worktree", "add", "-q", "--detach", "--", wt)
            git(wt, "commit", "-q", "--allow-empty", "-m", "m")

        return [("make_repo", k_make_repo), ("helpers init", k_helper_init), ("subprocess init", k_subprocess_init),
                ("clone", k_clone), ("bare remote and push", k_bare_push), ("worktree add", k_worktree)]

    def test_global_fixture_file_holds_only_the_two_keys(self):  # B1, V4
        print("git version: %s" % subprocess.run(["git", "--version"], stdout=subprocess.PIPE).stdout.decode().strip())
        self.assertEqual(sorted(git(self.work, "config", "--global", "--list").split("\n")),
                         ["gc.auto=0", "maintenance.auto=false"])
        self.assertEqual(os.environ["GIT_CONFIG_GLOBAL"], os.path.join(self.tmp, "gitconfig"))
        with open(os.path.join(self.tmp, "gitconfig"), "rb") as fh:
            self.assertEqual(fh.read(), EXPECTED_TEXT.encode("utf-8"))
        self.assertEqual(os.environ["GIT_CONFIG_NOSYSTEM"], "1")
        self.assertEqual(os.environ["HOME"], os.path.join(self.tmp, "home"))
        for name in CLEARED_ENV:
            self.assertNotIn(name, os.environ)

    def test_make_repo_writes_the_keys_locally(self):  # B2
        r = make_repo(self.work)
        self.assertEqual(git(r, "config", "--local", "--get", "maintenance.auto"), "false")
        self.assertEqual(git(r, "config", "--local", "--get", "gc.auto"), "0")
        with open(os.path.join(r, ".git", "config"), encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("\tauto = false\n", text)
        self.assertIn("\tauto = 0\n", text)

    def test_no_maintenance_child_in_any_creation_kind(self):  # B3, M1
        for name, run in self.kinds():
            with self.subTest(kind=name):
                events, children = trace_children(self.tmp, name.replace(" ", "-"), run)
                self.assertFalse(has_maintenance(children), (name, children))
                if name == "bare remote and push":  # M1: the receive-pack child ran and started no maintenance
                    starts = [e.get("argv", [""])[0] for e in events if e.get("event") == "start"]
                    self.assertIn("git-receive-pack", starts)

    def test_constructed_env_on_make_repo_tree(self):  # B4
        r = make_repo(self.work)
        env = {"PATH": os.environ["PATH"], "HOME": os.environ["HOME"], "GIT_CONFIG_NOSYSTEM": "1",
               "GIT_CONFIG_GLOBAL": "/dev/null", "LC_ALL": "C"}
        env.update(IDENTITY)
        _events, children = trace_children(self.tmp, "b4", lambda e: subprocess.run(
            ["git", "-C", r, "commit", "-q", "--allow-empty", "-m", "m"], env=dict(env, **e), check=True))
        self.assertFalse(has_maintenance(children), children)

    def test_oracle_sees_maintenance_without_the_keys(self):  # B5m, M2
        bare_env = {"GIT_CONFIG_GLOBAL": "/dev/null"}
        r = os.path.join(self.tmp, "nokeys")
        os.mkdir(r)
        git(r, "init", "-q", "-b", "main", env=bare_env)
        _events, children = trace_children(self.tmp, "b5m", lambda e: git(
            r, "commit", "-q", "--allow-empty", "-m", "m", env=dict(bare_env, **e)))
        print("M2 children: %s" % [c for c in children if MAINT & set(c)])
        self.assertTrue(has_maintenance(children), children)

    def test_generated_inherited_env(self):  # G3
        rng = random.Random(20261126)
        letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        noise = {"GIT_ZZ" + "".join(rng.choice(letters) for _ in range(8)): "".join(rng.choice("ab/ .x") for _ in range(6))
                 for _ in range(60)}
        self.assertGreaterEqual(len(noise), 50)
        inherited = dict(noise)
        inherited.update({name: os.path.join(self.tmp, "nowhere") for name in CLEARED_ENV})
        inherited["GIT_CONFIG_GLOBAL"] = "/dev/null"

        class Probe(GitIsolatedTestCase):
            def runTest(self):
                pass

        probe = Probe()
        with mock.patch.dict(os.environ, inherited):
            probe.setUp()
            try:
                self.assertEqual(os.environ["GIT_CONFIG_GLOBAL"], os.path.join(probe.tmp, "gitconfig"))
                self.assertEqual(os.environ["GIT_CONFIG_NOSYSTEM"], "1")
                for name in CLEARED_ENV:
                    self.assertNotIn(name, os.environ)
                for name, value in noise.items():
                    self.assertEqual(os.environ[name], value)  # inherited, and not harmful

                def run(_e):
                    r = make_repo(probe.work)
                    commit_all(r, "c")

                _events, children = trace_children(probe.tmp, "g3", run)
                self.assertFalse(has_maintenance(children), children)
            finally:
                probe.doCleanups()

    def test_every_repository_creation_is_covered(self):  # B6, the whole class
        calls = creation_calls(TESTS_DIR)
        self.assertGreaterEqual(len(calls), 100)
        problems = []
        for rel, line, cls, func in calls:
            if rel == "tests/helpers.py" and func in ("make_repo", "root_forms"):
                continue
            if (rel, cls) in EXEMPT:
                continue
            if not covered(rel, cls):
                problems.append("%s:%d %s" % (rel, line, cls))
        self.assertEqual(problems, [])

    def test_exempt_entries_still_needed(self):  # B6: an EXEMPT entry whose class is now covered is stale
        for (rel, cls), request in EXEMPT.items():
            with self.subTest(rel=rel, cls=cls):
                self.assertTrue(any(r == rel and c == cls for r, _l, c, _f in creation_calls(TESTS_DIR)), request)
                self.assertFalse(covered(rel, cls), "%s is covered now: drop %s" % (cls, request))

    def test_covered_rule_by_examples(self):  # B6: the rule that decides a creation is covered, on typed cases
        class Plain(unittest.TestCase):
            pass

        class Isolated(GitIsolatedTestCase):
            pass

        fake = types.SimpleNamespace(Plain=Plain, Isolated=Isolated, notaclass=3)
        load = {"tests.x": fake}.__getitem__
        no, yes = (lambda rel: False), (lambda rel: True)
        self.assertTrue(covered("tests/x.py", "Isolated", load, no))
        self.assertFalse(covered("tests/x.py", "Plain", load, no))
        self.assertFalse(covered("tests/x.py", "notaclass", load, no))
        self.assertFalse(covered("tests/x.py", "nothere", load, no))
        self.assertFalse(covered("tests/x.py", None, load, no))
        self.assertTrue(covered("tests/x.py", "Plain", load, yes))
        src = "def setUpModule():\n    env = {'GIT_CONFIG_GLOBAL': fixture_gitconfig(home)}\n"
        self.assertTrue(source_sets_up_fixture(src))
        self.assertTrue(source_sets_up_fixture("def setUpModule():\n    helpers.fixture_gitconfig(home)\n"))
        self.assertFalse(source_sets_up_fixture("def setUpModule():\n    env = {'GIT_CONFIG_GLOBAL': '/dev/null'}\n"))
        self.assertFalse(source_sets_up_fixture("def other():\n    fixture_gitconfig(home)\n"))


class NoWrite(object):
    """Replace ``os.open`` by a function that fails the test: the call it wraps must write nothing."""

    def __enter__(self):
        self.patch = mock.patch("os.open", side_effect=AssertionError("os.open must not run"))
        self.patch.start()

    def __exit__(self, *exc):
        self.patch.stop()


class FixtureGitConfigFunctionTest(GitIsolatedTestCase):
    def home(self, name="home"):
        return os.path.join(self.tmp, "box", name)

    def setUp(self):
        super().setUp()
        os.mkdir(os.path.join(self.tmp, "box"))

    def test_fixture_gitconfig_exact_types(self):  # X5
        class S(str):
            pass

        with NoWrite():
            for bad, name in ((S(self.home()), "S"), (self.home().encode(), "bytes"), (PurePosixPath(self.home()), "PurePosixPath"),
                              (None, "NoneType")):
                with self.subTest(value=name):
                    with self.assertRaises(TypeError) as cm:
                        fixture_gitconfig(bad)
                    self.assertEqual(str(cm.exception), "home must be an exact str, got %s" % name)
        self.assertEqual(snapshot(os.path.join(self.tmp, "box")), {})
        got = fixture_gitconfig(self.home())
        self.assertEqual(got, os.path.join(self.tmp, "box", "gitconfig"))
        with open(got, "rb") as fh:
            self.assertEqual(fh.read(), EXPECTED_TEXT.encode("utf-8"))
        self.assertEqual(GITCONFIG_TEXT, EXPECTED_TEXT)
        self.assertEqual(stat.S_IMODE(os.stat(got).st_mode) & 0o077, 0)  # created 0o600: no group or other bits

    def test_fixture_gitconfig_refuses_existing_target(self):  # FG1
        box = os.path.join(self.tmp, "box")
        target = os.path.join(box, "gitconfig")
        original = os.path.join(self.tmp, "original")
        with open(original, "wb") as fh:
            fh.write(b"ORIGINAL\n")
        makers = {
            "regular file": lambda: open(target, "wb").close(),
            "symlink to a file": lambda: os.symlink(original, target),
            "dangling symlink": lambda: os.symlink(os.path.join(self.tmp, "nowhere"), target),
            "directory": lambda: os.mkdir(target),
            "fifo": lambda: os.mkfifo(target),
        }
        for name, make in makers.items():
            with self.subTest(existing=name):
                make()
                before = snapshot(self.tmp)
                with self.assertRaises(FixtureGitConfigRefused) as cm:
                    within(lambda: fixture_gitconfig(self.home()))
                self.assertTrue(str(cm.exception).startswith(target + ": "), str(cm.exception))
                self.assertEqual(snapshot(self.tmp), before)
                self.assertFalse(os.path.exists(os.path.join(self.tmp, "nowhere")))
                os.rename(target, os.path.join(self.tmp, "moved-" + name.replace(" ", "-")))

    def test_fixture_gitconfig_parent_forms(self):  # FG2
        real = os.path.join(self.tmp, "realdir")
        os.mkdir(real)
        os.symlink(real, os.path.join(self.tmp, "linkdir"))
        got = fixture_gitconfig(os.path.join(self.tmp, "linkdir", "home"))
        self.assertEqual(got, os.path.join(self.tmp, "linkdir", "gitconfig"))
        with open(os.path.join(real, "gitconfig"), "rb") as fh:  # the file lands in the link's target, in the sandbox
            self.assertEqual(fh.read(), EXPECTED_TEXT.encode("utf-8"))
        with NoWrite():
            for bad in ("/", "//", "", ".", "..", "home", "relative/home", "/a/..", "/a/.", self.tmp + "/..", self.tmp + "/box/.."):
                with self.subTest(home=bad):
                    with self.assertRaises(FixtureGitConfigRefused) as cm:
                        fixture_gitconfig(bad)
                    self.assertEqual(str(cm.exception), "home must be an absolute path with a name of its own: %s" % bad)
        self.assertEqual(os.path.dirname("/"), "/")  # the parent of / is /

    def test_fixture_gitconfig_trailing_slash(self):  # FG2: a trailing slash names the same home
        got = fixture_gitconfig(self.home() + "/")
        self.assertEqual(got, os.path.join(self.tmp, "box", "gitconfig"))
        self.assertEqual(os.listdir(os.path.join(self.tmp, "box")), ["gitconfig"])

    def test_fixture_gitconfig_names(self):  # FG3
        for name in ("a b", "café", "x" + FF):
            with self.subTest(parent=name):
                parent = os.path.join(self.tmp, name)
                try:
                    os.mkdir(parent)
                except OSError as e:
                    if name == "x" + FF and e.errno == errno.EILSEQ:  # only that errno skips; every other error fails
                        self.skipTest(SKIP_FF)
                    raise
                got = fixture_gitconfig(os.path.join(parent, "home"))
                self.assertEqual(got, os.path.join(parent, "gitconfig"))
                with open(os.fsencode(got), "rb") as fh:
                    self.assertEqual(fh.read(), EXPECTED_TEXT.encode("utf-8"))


# ---- PM2: the generated path matrix of fixture_gitconfig ----

PM2_ROLES = ("p1", "p2", "holder", "target")
PM2_DIR_VERDICT = {  # typed by hand: the holder and each parent above it
    "absent": "refused", "file": "refused", "dir": "written", "symlink_dir_in": "written", "symlink_dir_out": "written",
    "symlink_file_in": "refused", "symlink_file_out": "refused", "fifo": "refused", "ff": "written"}
PM2_TARGET_VERDICT = {  # typed by hand: the entry <holder>/gitconfig exists already (a neighbour named with 0xff does not matter)
    "absent": "written", "file": "refused", "dir": "refused", "symlink_file_in": "refused", "symlink_file_out": "refused",
    "dangling": "refused", "fifo": "refused", "ff": "written"}


def pm2_cells():
    """Every cell: (role, state, moment, verdict). The moment ``call`` has the state in place when the function is
    called; ``between`` swaps the role to the state just before the ``os.open`` (the verdict is the same)."""
    cells = []
    for role in PM2_ROLES:
        table = PM2_TARGET_VERDICT if role == "target" else PM2_DIR_VERDICT
        for state, verdict in table.items():
            cells.append((role, state, "call", verdict))
            cells.append((role, state, "between", verdict))
    return cells


def make_target_state(holder, state, original, nowhere, outside_file):
    """Create ``<holder>/gitconfig`` as ``state`` (never a hang, never a write through anything)."""
    target = os.path.join(holder, "gitconfig")
    if state == "file":
        with open(target, "wb") as fh:
            fh.write(b"ORIGINAL\n")
    elif state == "dir":
        os.mkdir(target)
    elif state == "symlink_file_in":
        os.symlink(original, target)
    elif state == "symlink_file_out":
        os.symlink(outside_file, target)
    elif state == "dangling":
        os.symlink(nowhere, target)
    elif state == "fifo":
        os.mkfifo(target)
    elif state == "ff":
        with open(os.fsencode(target) + b"\xff", "wb") as fh:
            fh.write(b"neighbour\n")


class PathMatrixFixtureTest(GitIsolatedTestCase):
    def setUp(self):
        super().setUp()
        self.count = itertools.count()

    def make_entry(self, cell, outside, entry, rest, state):
        """Create ``entry`` as ``state``, with the plain directories ``rest`` below it where the state is a directory.
        Returns the directory a written ``gitconfig`` lands in."""
        landing = os.path.join(entry, *rest)
        if state == "absent":
            return landing
        if state in ("dir", "ff"):
            os.mkdir(entry)
            inner = entry
            for name in rest:
                inner = os.path.join(inner, name)
                os.mkdir(inner)
        elif state == "file":
            with open(entry, "wb") as fh:
                fh.write(b"x")
        elif state == "fifo":
            os.mkfifo(entry)
        elif state.startswith("symlink_file"):
            os.symlink(self.original if state.endswith("_in") else self.outside_file, entry)
        elif state.startswith("symlink_dir"):
            where = os.path.join(cell if state.endswith("_in") else outside, "dir%d" % next(self.count))
            os.mkdir(where)
            inner = where
            for name in rest:
                inner = os.path.join(inner, name)
                os.mkdir(inner)
            os.symlink(where, entry)
            landing = inner
        return landing

    def build(self, cell, outside, role, state, moment):
        """Returns ``(home, target, box, inject)``: the ``home`` argument, the path ``fixture_gitconfig`` opens, a
        one-element list holding the directory a written file lands in, and ``inject`` (``None`` for the moment
        ``call``): the function that puts ``role`` into ``state`` just before the open. Under ``between`` the role
        is a plain directory until then."""
        names = ["p1", "p2", "holder"]
        use = os.path.join(cell, "use")
        os.mkdir(use)
        self.original = os.path.join(cell, "original")
        with open(self.original, "wb") as fh:
            fh.write(b"ORIGINAL\n")
        self.outside_file = os.path.join(outside, os.path.basename(cell) + "-file")
        with open(self.outside_file, "wb") as fh:
            fh.write(b"OUTSIDE\n")
        k = names.index(role) if role != "target" else len(names)
        cur = use
        for name in names[:k]:
            cur = os.path.join(cur, name)
            os.mkdir(cur)
        if role == "target":
            def inject():
                make_target_state(cur, state, self.original, os.path.join(cell, "nowhere"), self.outside_file)

            if moment == "call":
                inject()
                inject = None
            return os.path.join(cur, "home"), os.path.join(cur, "gitconfig"), [cur], inject
        entry = os.path.join(cur, names[k] + (FF if state == "ff" else ""))
        rest = names[k + 1:]
        home, target = os.path.join(entry, *rest, "home"), os.path.join(entry, *rest, "gitconfig")
        if moment == "call":
            return home, target, [self.make_entry(cell, outside, entry, rest, state)], None
        box = [self.make_entry(cell, outside, entry, rest, "dir")]

        def swap():
            os.rename(entry, entry + ".moved")
            box[0] = self.make_entry(cell, outside, entry, rest, state)

        return home, target, box, swap

    def test_generated_path_matrix_fixture_gitconfig(self):  # PM2
        outside = os.path.join(self.tmp, "second")
        os.mkdir(outside)
        cells = pm2_cells()
        random.Random(20261126).shuffle(cells)
        self.assertEqual(len(cells), (9 * 3 + 8) * 2)  # three directory roles of 9 states, the target of 8, two moments
        real_open = os.open
        for n, (role, state, moment, verdict) in enumerate(cells):
            cell = os.path.join(self.tmp, "cell%d" % n)
            os.mkdir(cell)
            with self.subTest(role=role, state=state, moment=moment):
                if state == "ff":  # APFS refuses the name (EILSEQ): skip; any other error fails
                    try:
                        os.mkdir(os.path.join(cell, "probe" + FF))
                    except OSError as e:
                        if e.errno == errno.EILSEQ:
                            self.skipTest(SKIP_FF)
                        raise
                home, target, box, inject = self.build(cell, outside, role, state, moment)
                injected = []

                def hooked(p, flags, *a, **k):
                    if inject is not None and p == target and not injected:
                        inject()
                        injected.append(snapshot(self.tmp))
                    return real_open(p, flags, *a, **k)

                before = snapshot(self.tmp)
                with mock.patch("os.open", hooked):
                    try:
                        got = within(lambda: fixture_gitconfig(home))
                        outcome = "written"
                    except FixtureGitConfigRefused:
                        outcome = "refused"
                self.assertEqual(outcome, verdict)
                if inject is not None:
                    self.assertEqual(len(injected), 1)  # the swap happened, before the open
                    before = injected[0]
                after = snapshot(self.tmp)
                if outcome == "refused":
                    self.assertEqual(after, before)  # nothing written, nothing changed
                else:
                    self.assertEqual(got, target)
                    with open(os.fsencode(os.path.join(box[0], "gitconfig")), "rb") as fh:
                        self.assertEqual(fh.read(), EXPECTED_TEXT.encode("utf-8"))
                    new = sorted(set(after) - set(before))
                    self.assertEqual(len(new), 1, new)
                    self.assertEqual(os.path.basename(os.fsencode(new[0])), b"gitconfig")
                    self.assertEqual({k: v for k, v in before.items() if k in after and after[k] != v}, {})


if __name__ == "__main__":
    unittest.main()
