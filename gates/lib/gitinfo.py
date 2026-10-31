"""Read-only git queries for the gates (standard library only).

Every call passes an argument list (never a shell string), forces the C locale, clears ``GIT_DIR`` and
``GIT_WORK_TREE`` from the caller's environment, and puts ``--`` before any user path. Failure messages
name the git command and never the directory. A ref or sha that starts with ``-`` is never given to git.
"""
from __future__ import annotations

import os
import posixpath
import subprocess
from typing import List, Optional

from gates.lib.result import GateError, GitNotFound

_REGULAR = ("100644", "100755")


def _env() -> dict:
    env = dict(os.environ)
    env.pop("GIT_DIR", None)
    env.pop("GIT_WORK_TREE", None)
    # GIT_INDEX_FILE stays inherited on purpose: a pre-commit hook reads the index being committed.
    env["LC_ALL"] = "C"
    return env


def _run(root: str, name: str, args: List[str], ok: Optional[tuple] = (0,),
         literal: bool = False) -> "subprocess.CompletedProcess":
    """Run ``git -C root <args>``; with ``ok`` a tuple, any other exit status is a GateError naming ``name``."""
    argv = ["git"] + (["--literal-pathspecs"] if literal else []) + ["-C", root] + args
    try:
        p = subprocess.run(argv, env=_env(), stdin=subprocess.DEVNULL, check=False,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except FileNotFoundError:
        raise GitNotFound("git not found on PATH; install git") from None
    except (OSError, ValueError):
        raise GateError("git %s failed: unusable argument" % name) from None
    if ok is not None and p.returncode not in ok:
        raise GateError("git %s failed (exit %d)" % (name, p.returncode))
    return p


def _text(data: bytes, what: str) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        raise GateError("git %s gave output that is not valid UTF-8" % what) from None


def _check_ref(ref: str) -> None:
    if ref.startswith("-"):
        raise GateError("ref must not start with '-'")


def _ensure_repo(root: str) -> None:
    _run(root, "rev-parse --git-dir", ["rev-parse", "--git-dir"])


def _entries(stdout: bytes, what: str) -> list:
    """Parse ``-z`` ls-tree or ls-files --stage output into (mode, third field, path) triples.

    The third field is the object id for ls-tree (``mode type sha``) and the stage for ls-files."""
    out = []
    for raw in stdout.split(b"\0"):
        if not raw:
            continue
        head, _, path = raw.partition(b"\t")
        mode, _, third = head.split(b" ")
        out.append((mode.decode("ascii"), third.decode("ascii"), _text(path, what)))
    return out


def toplevel(root: str) -> str:
    p = _run(root, "rev-parse --show-toplevel", ["rev-parse", "--show-toplevel"])
    return _text(p.stdout, "rev-parse --show-toplevel").rstrip("\n")


def head_sha(root: str) -> str:
    p = _run(root, "rev-parse HEAD", ["rev-parse", "HEAD"])
    return _text(p.stdout, "rev-parse").strip()


def commit_exists(root: str, sha: str) -> bool:
    _ensure_repo(root)
    if sha.startswith("-"):
        return False
    p = _run(root, "cat-file -e", ["cat-file", "-e", sha + "^{commit}"], ok=None)
    if p.returncode != 0:
        return False
    if len(sha) < 40 and all(c in "0123456789abcdefABCDEF" for c in sha):
        ref = _run(root, "rev-parse --symbolic-full-name", ["rev-parse", "--symbolic-full-name", sha],
                   ok=None)  # exit 128 for an ambiguous bare prefix: not a ref
        if ref.returncode == 0 and ref.stdout.strip():
            return True  # git resolves the value as a ref (branch, tag): the prefix rule does not apply
        d = _run(root, "rev-parse --disambiguate", ["rev-parse", "--disambiguate=" + sha])
        return len(d.stdout.split()) <= 1  # a prefix naming several objects (any type) is ambiguous
    return True


def blob_exists(root: str, sha: str, path: str) -> bool:
    _ensure_repo(root)
    if sha.startswith("-"):
        return False
    p = _run(root, "ls-tree", ["ls-tree", "-z", "--full-tree", sha, "--", path], ok=None, literal=True)
    return any(mode in _REGULAR and name == path for mode, _, name in _entries(p.stdout, "ls-tree"))


def tracked_files(root: str) -> frozenset:
    top = toplevel(root)
    p = _run(top, "ls-files", ["ls-files", "-z", "--stage"])
    return frozenset(name for mode, _, name in _entries(p.stdout, "ls-files") if mode in _REGULAR)


def show(root: str, ref: str, path: str) -> Optional[str]:
    _check_ref(ref)
    p = _run(root, "ls-tree", ["ls-tree", "-z", "--full-tree", ref, "--", path], literal=True)
    raw = None
    for mode, sha, name in _entries(p.stdout, "ls-tree"):
        if mode in _REGULAR and name == path:
            raw = sha
    if raw is None:
        return None
    blob = _run(root, "cat-file blob", ["cat-file", "blob", raw])
    try:
        return blob.stdout.decode("utf-8")
    except UnicodeDecodeError:
        raise GateError("%s: not valid UTF-8" % path) from None


def ls_tree(root: str, ref: str, directory: str) -> list:
    _check_ref(ref)
    d = directory.rstrip("/")
    if ".." in d.split("/"):
        raise GateError("ls-tree: directory must not hold a '..' segment")
    args = ["ls-tree", "-z", "--full-tree", ref]
    if d:
        args += ["--", d + "/"]
    p = _run(root, "ls-tree", args, literal=True)
    return [name for mode, _, name in _entries(p.stdout, "ls-tree")
            if mode in _REGULAR and posixpath.dirname(name) == d]


def merge_base(root: str, a: str, b: str) -> str:
    _check_ref(a)
    _check_ref(b)
    p = _run(root, "merge-base", ["merge-base", a, b])
    return _text(p.stdout, "merge-base").strip()


def user_email(root: str) -> Optional[str]:
    p = _run(root, "config user.email", ["config", "user.email"], ok=(0, 1))
    value = _text(p.stdout, "config").strip()
    return value or None
