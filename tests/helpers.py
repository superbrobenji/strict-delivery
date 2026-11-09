"""Shared test helpers: fixture repositories built with plain git, isolated from the user's git config."""
import os
import subprocess
import tempfile
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


# The two texts a library function raises for a root that is not a top level (measured 2026-11-02).
TOP = "git rev-parse --show-toplevel: root must be the repository top level"
E128 = "git rev-parse --show-toplevel failed (exit 128)"


def minimal_config() -> dict:
    return {"schema": "config/1", "framework_version": "0.0.0", "profile": "strict"}


def git(root: str, *args: str, env: Optional[dict] = None, check: bool = True) -> str:
    """Run git in root with a fixed identity and date; return stripped stdout."""
    full_env = dict(os.environ)
    full_env.update(_IDENTITY)
    full_env["LC_ALL"] = "C"
    if env:
        full_env.update(env)
    p = subprocess.run(["git", "-C", root] + list(args), env=full_env, check=False,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if check and p.returncode != 0:
        raise AssertionError("git %s failed: %s" % (" ".join(args), p.stderr.decode("utf-8", "replace")))
    return p.stdout.decode("utf-8").strip()


def make_repo(tmp: str, config: Optional[dict] = None) -> str:
    """Make tmp a git repository whose first branch is main, with the config committed; return tmp."""
    git(tmp, "init", "-q", "-b", "main")
    git(tmp, "config", "user.email", "fixture@example.invalid")
    git(tmp, "config", "user.name", "Fixture")
    git(tmp, "config", "commit.gpgsign", "false")
    write_record(tmp, ".strict-delivery/config.yml", config if config is not None else minimal_config())
    commit_all(tmp, "fixture")
    return tmp


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
    git(top, "worktree", "add", "-q", "--detach", wt)
    bare = os.path.join(base, "bare.git")
    git(base, "init", "-q", "--bare", bare)
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
