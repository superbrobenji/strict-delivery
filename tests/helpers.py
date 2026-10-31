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


class GitIsolatedTestCase(unittest.TestCase):
    """Base class of every test that runs git: no system or global git config, a private HOME,
    no inherited GIT_DIR, GIT_WORK_TREE or GIT_INDEX_FILE, and a temp directory as self.tmp."""

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
        for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "CLAUDE_PROJECT_DIR"):
            os.environ.pop(name, None)
