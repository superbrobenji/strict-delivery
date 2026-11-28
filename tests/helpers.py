"""Shared test helpers: fixture repositories built with plain git, isolated from the user's git config."""
import atexit
import contextlib
import copy
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from typing import Optional
from unittest import mock

from gates.lib.yamlsub import emit

_IDENTITY = {
    "GIT_AUTHOR_NAME": "Fixture Author",
    "GIT_AUTHOR_EMAIL": "author@example.invalid",
    "GIT_AUTHOR_DATE": "2026-01-01T00:00:00+0000",
    "GIT_COMMITTER_NAME": "Fixture Committer",
    "GIT_COMMITTER_EMAIL": "committer@example.invalid",
    "GIT_COMMITTER_DATE": "2026-01-01T00:00:00+0000",
}


def watched(fn, secs=10):
    """``("ok", value)`` or ``("err", exception)`` of ``fn()`` run in a daemon thread; a call that has not returned
    after ``secs`` seconds (a blocked open of a FIFO) raises AssertionError, so the test fails by name, never by a hang."""
    res = []

    def go():
        try:
            res.append(("ok", fn()))
        except BaseException as e:  # noqa: BLE001 - handed to the test
            res.append(("err", e))
    t = threading.Thread(target=go, daemon=True)
    t.start()
    t.join(secs)
    if t.is_alive():
        raise AssertionError("the call did not return within %d s (a FIFO was opened by name?)" % secs)
    return res[0]


def within(fn, secs=10):
    """``fn()`` run under ``watched``: its value is returned and its exception re-raised, so the call reads as a plain
    call (inside ``assertRaises``); a hang raises AssertionError."""
    kind, val = watched(fn, secs)
    if kind == "err":
        raise val
    return val


# The two texts a library function raises for a root that is not a top level (measured 2026-11-02).
TOP = "git rev-parse --show-toplevel: root must be the repository top level"
E128 = "git rev-parse --show-toplevel failed (exit 128)"


@contextlib.contextmanager
def int_limit(value):
    """Run the body with ``sys.set_int_max_str_digits(value)`` (restored after); ``None`` leaves the limit as it is."""
    if value is None:
        yield
        return
    old = sys.get_int_max_str_digits()
    sys.set_int_max_str_digits(value)
    try:
        yield
    finally:
        sys.set_int_max_str_digits(old)


# The int string-conversion limit settings every digit-count row runs under: the default, 640 (the lowest CPython 3.11+
# accepts) and 0 (unlimited). Interpreters before 3.11 have no such limit, so only the default exists there.
INT_LIMITS = (None, 640, 0) if hasattr(sys, "set_int_max_str_digits") else (None,)


def minimal_config() -> dict:
    return {"schema": "config/2", "framework_version": "0.0.0", "profile": "strict"}


def _exact(fn: str, name: str, value, typ) -> None:
    """Row E (owner Q-RS4-1 (A), 2026-11-26): exact types are accepted, subclasses (and every other type) are refused with
    a named TypeError before the function writes, runs git or calls a build."""
    if type(value) is not typ:
        raise TypeError("%s: %s must be exactly %s, not %s" % (fn, name, typ.__name__, type(value).__name__))


def _key_ok(key) -> bool:
    return type(key) in (str, int, bool, type(None)) or (type(key) is tuple and all(_key_ok(k) for k in key))


def git(root: str, *args: str, env: Optional[dict] = None, check: bool = True) -> str:
    """Run git in root with a fixed identity and date; return stripped stdout. ``GIT_OPTIONAL_LOCKS=0`` is the
    default, as in ``gates/lib/gitinfo.py``: a probe such as ``git status`` never rewrites ``.git/index`` (a test that
    compares the index across its own probe would see the probe's write); an explicit ``env`` entry wins.
    Row E1: ``root`` and every argument are exactly ``str``, ``env`` is ``None`` or exactly ``dict`` whose keys and values
    are exactly ``str``, ``check`` is exactly ``bool``."""
    _exact("git", "root", root, str)
    for i, a in enumerate(args):
        _exact("git", "argument %d" % i, a, str)
    if env is not None:
        _exact("git", "env", env, dict)
        for k, v in env.items():
            _exact("git", "env key", k, str)
            _exact("git", "env value", v, str)
    _exact("git", "check", check, bool)
    full_env = dict(os.environ)
    full_env.update(_IDENTITY)
    full_env["LC_ALL"] = "C"
    full_env["GIT_OPTIONAL_LOCKS"] = "0"
    if env:
        full_env.update(env)
    p = subprocess.run(["git", "-C", root] + list(args), env=full_env, check=False,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if check and p.returncode != 0:
        raise AssertionError("git %s failed: %s" % (" ".join(args), p.stderr.decode("utf-8", "replace")))
    return p.stdout.decode("utf-8").strip()


def _make_repo_slow(tmp: str, config: Optional[dict]) -> str:
    git(tmp, "init", "-q", "-b", "main")
    git(tmp, "config", "user.email", "fixture@example.invalid")
    git(tmp, "config", "user.name", "Fixture")
    git(tmp, "config", "commit.gpgsign", "false")
    git(tmp, "config", "maintenance.auto", "false")  # no detached auto-maintenance or auto-gc writing into .git while a test runs
    git(tmp, "config", "gc.auto", "0")
    write_record(tmp, ".strict-delivery/config.yml", config if config is not None else minimal_config())
    write_record(tmp, ".strict-delivery/context.yml", {"schema": "context/1"})  # the gate_context producer makes this file required (Rq-5-2)
    commit_all(tmp, "fixture")
    return tmp


# The git environment ``GitIsolatedTestCase`` gives every test: no system or global git config. A fixture is copied from
# a template only under it: both names set to these values, none of the names that move or reshape a repository
# (the CLEARED_ENV names, a template directory, a hash or ref format, GIT_EXEC_PATH, any other GIT_CONFIG_* name);
# every other GIT_* name is part of the template's key, so a template is always built under the environment it serves.
_ISOLATED_GIT_ENV = {"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null"}
_REPO_SHAPING = frozenset(("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_OBJECT_DIRECTORY",
                           "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_NAMESPACE", "GIT_CEILING_DIRECTORIES",
                           "GIT_INDEX_FILE", "GIT_TEMPLATE_DIR", "GIT_DEFAULT_HASH", "GIT_DEFAULT_REF_FORMAT",
                           "GIT_EXEC_PATH", "GIT_CONFIG", "GIT_CONFIG_COUNT", "GIT_CONFIG_PARAMETERS",
                           "GIT_CONFIG_SYSTEM"))
_TEMPLATE_LOCK = threading.Lock()
_TEMPLATES: dict = {}  # (emitted config text, PATH, umask, GIT_* environment) -> directory of the template repository
_TEMPLATE_ROOT: list = []  # [private temporary directory], created on first use, removed at process exit
_HISTORY_ROOT: list = []  # the same for ``cached_history`` (a build runs there, so ``make_repo`` inside it is not an overlap)


def _private_root(holder: list, prefix: str) -> str:
    """A private temporary directory made on first use and removed at process exit (git objects are read-only)."""
    if not holder:
        root = os.path.realpath(tempfile.mkdtemp(prefix=prefix))
        holder.append(root)

        def _remove() -> None:
            def _writable(fn, path, _exc):
                os.chmod(os.path.dirname(path), 0o700)
                os.chmod(path, 0o700)
                fn(path)
            shutil.rmtree(root, onerror=_writable)
        atexit.register(_remove)
    return holder[0]


def _template_root() -> str:
    return _private_root(_TEMPLATE_ROOT, "sd-fixture-template-")


def _overlaps(real: str, root: str) -> bool:
    """True when the real paths ``real`` and ``root`` are equal, or one lies inside the other, compared case-folded:
    on a case-insensitive file system ``/T/SD-FIXTURE`` is the same directory as ``/T/sd-fixture``, and ``realpath``
    does not fold case. A case-folded alias is refused on a case-sensitive file system too (fail closed; no such
    path is a legitimate fixture directory). The filesystem root contains every root."""
    real, root = real.casefold().rstrip(os.sep), root.casefold().rstrip(os.sep)
    return real == root or real.startswith(root + os.sep) or root.startswith(real + os.sep)


_UMASK_LOCK = threading.Lock()


def _umask() -> int:
    """The process umask (no read-only getter exists: set it to 0 and put it back at once, under a lock, so that two
    threads cannot interleave and leave the umask at 0)."""
    with _UMASK_LOCK:
        old = os.umask(0)
        os.umask(old)
    return old


def _fast_path_ok(tmp: str, root: str) -> bool:
    """True when ``tmp`` is a real (not symlinked), empty directory on the template's file system, outside the
    template root, under the isolated git environment."""
    names = {k for k in os.environ if k.startswith("GIT_")}
    if any(os.environ.get(k) != v for k, v in _ISOLATED_GIT_ENV.items()):
        return False
    if names & _REPO_SHAPING or any(k.startswith("GIT_CONFIG_KEY_") or k.startswith("GIT_CONFIG_VALUE_") for k in names):
        return False
    try:
        if os.path.islink(tmp) or not os.path.isdir(tmp) or os.listdir(tmp):
            return False
        return os.stat(tmp).st_dev == os.stat(root).st_dev
    except OSError:
        return False


def make_repo(tmp: str, config: Optional[dict] = None) -> str:
    """Make tmp a git repository whose first branch is main, with the config and a minimal context.yml committed; return tmp.
    ``maintenance.auto`` is ``false`` and ``gc.auto`` is ``0`` in every repository returned. An empty tmp under the
    isolated git environment is a copy of a per-process template (one per emitted config text, PATH, umask and GIT_* environment, built the slow
    way, private temporary directory, removed at exit); any other tmp gets ``git init`` and the commit.
    Row E2: ``tmp`` is exactly ``str``, ``config`` is ``None`` or exactly ``dict``."""
    _exact("make_repo", "tmp", tmp, str)
    if config is not None:
        _exact("make_repo", "config", config, dict)
    text = emit(config if config is not None else minimal_config())
    root = _template_root()
    if _overlaps(os.path.realpath(tmp), os.path.realpath(root)):
        raise ValueError("make_repo: %s overlaps the fixture template directory" % tmp)
    if not _fast_path_ok(tmp, root):
        return _make_repo_slow(tmp, config)
    key = (text, os.environ.get("PATH", ""), _umask(),
           tuple(sorted((k, v) for k, v in os.environ.items() if k.startswith("GIT_"))))
    with _TEMPLATE_LOCK:
        tpl = _TEMPLATES.get(key)
        if tpl is None:
            tpl = os.path.join(root, "t%d" % len(_TEMPLATES))
            os.mkdir(tpl)
            _make_repo_slow(tpl, config)
            _TEMPLATES[key] = tpl
    for name in os.listdir(tpl):
        shutil.copytree(os.path.join(tpl, name), os.path.join(tmp, name), symlinks=True)
    return tmp


_HISTORY_LOCK = threading.Lock()
_HISTORIES: dict = {}  # (key, PATH, umask, GIT_* environment) -> (directory of the built history, facts)


def cached_history(key, dest: str, build):
    """Row F11: a history built once per process and copied for every caller. ``build(root)`` is called on an empty
    directory (inside a private history root, apart from the template root) and builds the whole repository there, with ``make_repo``,
    ``commit_all`` and plain file writes, and returns *facts* (plain data without paths, such as commit ids); ``key`` names the
    content (the same key must mean the same ``build``). Returns ``(dest, facts)``: ``dest`` is a real copy of the
    built directory (``copytree``: no hard links, no alternates, no shared object store), the facts a deep copy.
    Under the same conditions as ``make_repo``'s fast path (an empty, real ``dest`` on the template's file system,
    the isolated git environment) the build runs once per key, PATH, umask and GIT_* environment; otherwise ``build(dest)``
    runs on ``dest`` itself. Use only for a test that never depends on fresh history (the commit dates are the fixed
    ``_IDENTITY`` ones; the copy keeps every mtime, the index included).
    Row E3: ``dest`` is exactly ``str``, ``build`` is callable, ``key`` is built of exact ``str``, ``int``, ``bool``,
    ``None`` and ``tuple`` only."""
    _exact("cached_history", "dest", dest, str)
    if not callable(build):
        raise TypeError("cached_history: build must be callable, not %s" % type(build).__name__)
    if not _key_ok(key):
        raise TypeError("cached_history: key must be built of exact str, int, bool, None and tuple, not %s" % type(key).__name__)
    root = _template_root()
    real = os.path.realpath(dest)
    for rroot in (os.path.realpath(root), os.path.realpath(_private_root(_HISTORY_ROOT, "sd-fixture-history-"))):
        if _overlaps(real, rroot):
            raise ValueError("cached_history: %s overlaps the fixture template directory" % dest)
    if not _fast_path_ok(dest, root):
        return dest, build(dest)
    full = (key, os.environ.get("PATH", ""), _umask(),
            tuple(sorted((k, v) for k, v in os.environ.items() if k.startswith("GIT_"))))
    with _HISTORY_LOCK:  # not _TEMPLATE_LOCK: a build calls make_repo
        hit = _HISTORIES.get(full)
        if hit is None:
            built = tempfile.mkdtemp(prefix="h", dir=_private_root(_HISTORY_ROOT, "sd-fixture-history-"))
            hit = (built, build(built))
            _HISTORIES[full] = hit
    for name in os.listdir(hit[0]):
        src, dst = os.path.join(hit[0], name), os.path.join(dest, name)
        if os.path.isdir(src) and not os.path.islink(src):
            shutil.copytree(src, dst, symlinks=True)
        else:
            shutil.copy2(src, dst, follow_symlinks=False)
    return dest, copy.deepcopy(hit[1])


def commit_all(root: str, msg: str) -> str:
    git(root, "add", "-A")
    git(root, "commit", "-q", "--allow-empty", "-m", msg)
    return git(root, "rev-parse", "HEAD")


def write_record(root: str, rel: str, row: dict) -> str:
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(emit(row))
    return path


# Every git name gitinfo._env clears, plus GIT_INDEX_FILE (production inherits it for the pre-commit hook;
# fixture git must not write a parent's index, and the tests that need it set it themselves) and
# CLAUDE_PROJECT_DIR (read by result.repo_root).
CLEARED_ENV = ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_OBJECT_DIRECTORY",
               "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_NAMESPACE", "GIT_CEILING_DIRECTORIES",
               "GIT_INDEX_FILE", "CLAUDE_PROJECT_DIR")


class GitIsolatedTestCase(unittest.TestCase):
    """Base class of every test that runs git: no system or global git config, a private HOME,
    none of the CLEARED_ENV names inherited, and a temp directory as self.tmp."""

    def setUp(self) -> None:
        super().setUp()
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.tmp = os.path.realpath(td.name)
        home = os.path.join(self.tmp, "home")
        os.mkdir(home)
        self.work = os.path.join(self.tmp, "work")
        os.mkdir(self.work)
        patcher = mock.patch.dict(os.environ, {
            "HOME": home,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": "/dev/null",
        })
        patcher.start()
        self.addCleanup(patcher.stop)
        for name in CLEARED_ENV:
            os.environ.pop(name, None)


def root_forms(tmp: str, top: str) -> list:
    """Every spelling of a root the domain table (T1-T12) names, built with real git and symlinks around the
    repository ``top`` (a ``make_repo`` tree with at least one commit). Returns ``(name, path, verdict)`` where the
    verdict is ``"ok"`` (the root check accepts it), ``TOP`` or ``E128`` (the text the check raises)."""
    base = os.path.join(tmp, "forms")
    os.mkdir(base)
    sub = os.path.join(top, "sub")
    os.makedirs(sub)
    with open(os.path.join(top, "file.txt"), "w", encoding="utf-8") as fh:
        fh.write("x\n")
    link = os.path.join(base, "link")
    os.symlink(top, link)
    linksub = os.path.join(base, "linksub")
    os.symlink(sub, linksub)
    plain = os.path.join(base, "plain")
    os.mkdir(plain)
    wt = os.path.join(base, "wt")
    git(top, "worktree", "add", "-q", "--detach", "--", wt)
    bare = os.path.join(base, "bare.git")
    git(base, "init", "-q", "--bare", "--", bare)
    nested = os.path.join(sub, "nested")
    os.mkdir(nested)
    git(nested, "init", "-q", "-b", "main")
    return [
        ("top", top, "ok"), ("top/", top + "/", "ok"), ("sub", sub, TOP), ("sub/", sub + "/", TOP),
        ("link", link, "ok"), ("link/", link + "/", "ok"), ("link-to-sub", linksub, TOP),
        ("missing", os.path.join(top, "missing"), E128), ("file", os.path.join(top, "file.txt"), E128),
        ("plain", plain, E128), ("worktree", wt, "ok"), ("bare", bare, E128),
        ("dot-git", os.path.join(top, ".git"), E128), ("nested", nested, "ok"),
    ]


def check_root_forms(tc: unittest.TestCase, forms: list, calls: dict) -> None:
    """For every call and every form: a refused form raises exactly its text (never naming the path); an accepted
    form never raises the root-check text."""
    from gates.lib.result import GateError
    for fname, fn in calls.items():
        for name, path, verdict in forms:
            with tc.subTest(fn=fname, form=name):
                msg = None
                try:
                    fn(path)
                except GateError as e:
                    msg = str(e)
                if verdict == "ok":
                    tc.assertNotIn(msg, (TOP, E128))
                else:
                    tc.assertEqual(msg, verdict)
                    tc.assertNotIn(path, msg)
