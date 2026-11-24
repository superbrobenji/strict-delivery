"""The GitHub host side of ``init`` (Task 4d.2): which repository ``origin`` names, what the base branch's protection
is (read with ``gh``), and which ``gh`` calls would set the wanted protection. Standard library only.

``github_remote`` and ``read_state`` read only (``read_state`` runs two ``gh api`` reads); ``calls`` and ``missing``
are pure; ``run`` executes one argv that ``calls`` returned. No call goes through a shell, the remote URL is never put
in a message (it can hold a token), and nothing here compares text with a Unicode-table method.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from typing import List, Optional

from gates.lib import gitinfo
from gates.lib.result import GateError

TIMEOUT = 60  # seconds a ``gh`` call may run before it is killed
MAX_DIGITS = 600  # a numeral of the JSON that is longer is refused, never given to int() (P1.2 D-Q26)
PROTECTION_BODY = {"required_status_checks": None, "enforce_admins": True,
                   "required_pull_request_reviews": {"required_approving_review_count": 0}, "restrictions": None}
_KEYS = ("protected", "pr_required", "admins", "merge_commit", "squash", "rebase")
_REMOTE = (re.compile(r"https://github\.com/([A-Za-z0-9-]+)/([A-Za-z0-9._-]+?)(\.git)?"),
           re.compile(r"git@github\.com:([A-Za-z0-9-]+)/([A-Za-z0-9._-]+?)(\.git)?"))
_SLUG = re.compile(r"([A-Za-z0-9-]+)/([A-Za-z0-9._-]+)")
_NOT_FOUND = re.compile(r"gh: .* \(HTTP 404\)")
_BRANCH = re.compile(r"[A-Za-z0-9._/-]+")
_BRANCH_MSG = "branch: must hold only A-Z a-z 0-9 . _ / - with no empty, . or .. segment and no leading -"


class HostError(GateError):
    """``gh`` could not be run, answered an error, or answered something that is not what was asked."""


def _need_root(root: object) -> None:
    if type(root) is not str or root == "":
        raise GateError("root must be a string")


def _slug_ok(name: str) -> bool:
    return name not in (".", "..") and not name.endswith(".git")


def _check_slug(slug: object) -> str:
    m = _SLUG.fullmatch(slug) if type(slug) is str else None
    if m is None or not _slug_ok(m.group(2)):
        raise GateError("slug: must be owner/name")
    return slug


def _check_branch(branch: object) -> str:
    if (type(branch) is not str or _BRANCH.fullmatch(branch) is None or branch.startswith("-")
            or any(s in ("", ".", "..") for s in branch.split("/"))):
        raise GateError(_BRANCH_MSG)
    return branch


def _check_state(state: object) -> dict:
    if type(state) is not dict:
        raise GateError("state: must be a dict")
    for key in _KEYS:
        if key not in state:
            raise GateError("state: %s is missing" % key)
        if type(state[key]) is not bool:
            raise GateError("state: %s must be a bool" % key)
    if len(state) != len(_KEYS):
        raise GateError("state: holds a key other than %s" % ", ".join(_KEYS))
    return state


def github_remote(root: str) -> Optional[str]:
    """The ``owner/name`` of the ``origin`` remote when it is ``https://github.com/o/n(.git)`` or
    ``git@github.com:o/n(.git)``; ``None`` for every other remote, no ``origin``, several URLs or an unusable URL."""
    _need_root(root)
    gitinfo._require_toplevel(root)
    p = gitinfo._run(root, "remote get-url", ["remote", "get-url", "--all", "--", "origin"], ok=(0, 2))
    if p.returncode != 0:
        return None
    try:
        text = gitinfo._text(p.stdout, "remote get-url")
    except GateError:
        return None
    url = text[:-1] if text.endswith("\n") else text
    for pattern in _REMOTE:
        m = pattern.fullmatch(url)
        if m is not None and _slug_ok(m.group(2)):
            return "%s/%s" % (m.group(1), m.group(2))
    return None


# ---------------------------------------------------------------- running gh

def _env() -> dict:
    env = dict(os.environ)
    for name in ("GH_REPO", "GH_DEBUG", "DEBUG"):
        env.pop(name, None)
    env.update({"GH_HOST": "github.com", "GH_PROMPT_DISABLED": "1", "NO_COLOR": "1", "GH_NO_UPDATE_NOTIFIER": "1"})
    return env


def _first_line(data: bytes) -> str:
    for line in data.decode("utf-8", "replace").split("\n"):
        line = line.strip(" \t\r")
        if line != "":
            line = "".join("?" if (c < " " or c == "\x7f") else c for c in line)
            return line[:200]
    return "(no message)"


def _exec(root: str, argv: list, body: Optional[str]) -> "subprocess.CompletedProcess":
    cmd = " ".join(argv)
    env = _env()
    kwargs: dict = {"input": body.encode("utf-8")} if body is not None else {"stdin": subprocess.DEVNULL}
    try:
        return subprocess.run(argv, cwd=root, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              timeout=TIMEOUT, check=False, **kwargs)
    except subprocess.TimeoutExpired:
        raise HostError("%s: timed out after %d seconds" % (cmd, TIMEOUT)) from None
    except OSError as e:
        if isinstance(e, FileNotFoundError) and shutil.which(argv[0], path=env.get("PATH", "")) is None:
            raise HostError("%s: gh not found on PATH" % cmd) from None
        raise HostError("%s: cannot run gh: %s" % (cmd, e.strerror)) from None


def _failed(cmd: str, p: "subprocess.CompletedProcess") -> HostError:
    status = ("terminated by signal %d" % -p.returncode) if p.returncode < 0 else "exit %d" % p.returncode
    return HostError("%s: %s (%s)" % (cmd, _first_line(p.stderr), status))


class _Refused(Exception):
    pass


class _IntText(str):
    """An integer of the body kept as its text: no ``int()`` runs, so the interpreter's digit limit changes nothing."""


def _pairs(pairs: list) -> dict:
    out: dict = {}
    for key, value in pairs:
        if key in out:
            raise _Refused("duplicate key")
        out[key] = value
    return out


def _constant(name: str):
    raise _Refused("the constant %s is not allowed" % name)


def _integer(text: str) -> _IntText:
    if len(text.lstrip("-")) > MAX_DIGITS:
        raise _Refused("an integer of more than %d digits is not allowed" % MAX_DIGITS)
    return _IntText(text)


def _float(text: str) -> float:
    value = float(text)
    if value in (float("inf"), float("-inf")) or value != value:
        raise _Refused("a number that is not finite is not allowed")
    return value


def _json(cmd: str, p: "subprocess.CompletedProcess") -> dict:
    try:
        text = p.stdout.decode("utf-8")
        data = json.loads(text, object_pairs_hook=_pairs, parse_constant=_constant, parse_int=_integer,
                          parse_float=_float)
    except _Refused as e:
        raise HostError("%s: invalid JSON (%s)" % (cmd, e)) from None
    except (ValueError, RecursionError):
        raise HostError("%s: invalid JSON" % cmd) from None
    if type(data) is not dict:
        raise HostError("%s: not a JSON object" % cmd)
    return data


def _flag(cmd: str, data: dict, key: str) -> bool:
    if key not in data:
        raise HostError("%s: %s is missing" % (cmd, key))
    if type(data[key]) is not bool:
        raise HostError("%s: %s must be a bool" % (cmd, key))
    return data[key]


def read_state(root: str, slug: str, branch: str) -> dict:
    """``{protected, pr_required, admins, merge_commit, squash, rebase}`` of the branch and repository, read with two
    ``gh api`` calls (the repository first). A 404 on the protection call, read from ``gh``'s first stderr line, means
    unprotected; every other failure is a ``HostError`` naming the command."""
    _need_root(root)
    if not os.path.isdir(root):
        raise GateError("root: not a directory")
    _check_slug(slug)
    _check_branch(branch)
    argv = ["gh", "api", "repos/%s" % slug]
    cmd = " ".join(argv)
    p = _exec(root, argv, None)
    if p.returncode != 0:
        raise _failed(cmd, p)
    repo = _json(cmd, p)
    merge = (_flag(cmd, repo, "allow_merge_commit"), _flag(cmd, repo, "allow_squash_merge"),
             _flag(cmd, repo, "allow_rebase_merge"))
    argv = ["gh", "api", "repos/%s/branches/%s/protection" % (slug, branch)]
    cmd = " ".join(argv)
    p = _exec(root, argv, None)
    if p.returncode == 1 and _NOT_FOUND.fullmatch(p.stderr.decode("utf-8", "replace").split("\n")[0].rstrip("\r")):
        protected, pr, admins = False, False, False
    elif p.returncode != 0:
        raise _failed(cmd, p)
    else:
        prot = _json(cmd, p)
        if type(prot.get("enforce_admins")) is not dict:
            raise HostError("%s: enforce_admins must be an object" % cmd)
        admins = _flag(cmd, prot["enforce_admins"], "enabled")
        if "required_pull_request_reviews" in prot and type(prot["required_pull_request_reviews"]) is not dict:
            raise HostError("%s: required_pull_request_reviews must be an object" % cmd)
        protected, pr = True, "required_pull_request_reviews" in prot
    return dict(zip(_KEYS, (protected, pr, admins) + merge))


def body_text() -> str:
    """The exact text the protection PUT reads on stdin."""
    return json.dumps(PROTECTION_BODY)


def calls(state: dict, slug: str, branch: str) -> List[list]:
    """The ``gh`` argv lists that set the wanted protection: nothing for a protected branch (owner Q-4d2-9 (1)); for an
    unprotected one the PUT, then the PATCH when the merge methods are not merge-commit only."""
    _check_state(state)
    _check_slug(slug)
    _check_branch(branch)
    if state["protected"]:
        return []
    out = [["gh", "api", "-X", "PUT", "repos/%s/branches/%s/protection" % (slug, branch), "--input", "-"]]
    if (state["merge_commit"], state["squash"], state["rebase"]) != (True, False, False):
        out.append(["gh", "api", "-X", "PATCH", "repos/%s" % slug, "-F", "allow_merge_commit=true",
                    "-F", "allow_squash_merge=false", "-F", "allow_rebase_merge=false"])
    return out


def missing(state: dict) -> List[str]:
    """The text of each setting that is missing or differs, in a fixed order (shared with ``doctor``)."""
    _check_state(state)
    out = []
    if not state["pr_required"]:
        out.append("pull request not required")
    if not state["admins"]:
        out.append("administrators not enforced")
    if not state["merge_commit"]:
        out.append("merge commit not allowed")
    if state["squash"]:
        out.append("squash merge allowed")
    if state["rebase"]:
        out.append("rebase merge allowed")
    return out


def run(root: str, argv: list) -> str:
    """Run one ``gh api`` argv of ``calls`` in ``root`` (the PUT reads ``body_text()`` on stdin); its stdout, or a
    ``HostError`` naming the command."""
    _need_root(root)
    if not os.path.isdir(root):
        raise GateError("root: not a directory")
    if type(argv) is not list or len(argv) < 2 or any(type(a) is not str for a in argv) or argv[:2] != ["gh", "api"]:
        raise GateError("argv: must be a list of strings that starts with gh api")
    is_put = argv[2:4] == ["-X", "PUT"] and argv[-2:] == ["--input", "-"]
    p = _exec(root, argv, body_text() if is_put else None)
    if p.returncode != 0:
        raise _failed(" ".join(argv), p)
    return p.stdout.decode("utf-8", "replace")
