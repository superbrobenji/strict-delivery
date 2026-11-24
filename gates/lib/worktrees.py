"""Worktree facts the hooks check a git write against (standard library only).

``allowed`` is the set of worktree top levels a caller may write in (ruling (3b) on commit targets); ``worktree_list``,
``bound_branch`` and ``same_repository`` read git with the environment ``gitinfo`` uses (``gitinfo.CLEARED_ENV``
removed, ``LC_ALL=C``). Every doubt narrows the answer and, for ``allowed``, adds a fail line (fail closed).
"""
from __future__ import annotations

import os
import subprocess
from typing import Optional

from gates.lib import gitinfo, programs, session, transcript
from gates.lib.result import GateError, GitNotFound, safe_text

_HEADS = "refs/heads/"


def _env() -> dict:
    env = dict(os.environ)
    for name in gitinfo.CLEARED_ENV:
        env.pop(name, None)
    env["LC_ALL"] = "C"
    return env


def _git(root: object, args: list) -> bytes:
    """``git -C root <args>`` stdout; ``GateError`` for a root that is not a non-empty ``str``, a git failure or no git."""
    if type(root) is not str or root == "":
        raise GateError("git %s: root must be a non-empty string" % args[0])
    try:
        p = subprocess.run(["git", "-C", root] + args, env=_env(), stdin=subprocess.DEVNULL, check=False,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except FileNotFoundError:
        raise GitNotFound("git not found on PATH; install git") from None
    except (OSError, ValueError):
        raise GateError("git %s failed: unusable argument" % args[0]) from None
    if p.returncode != 0:
        raise GateError("git %s failed (exit %d)" % (" ".join(args[:2]), p.returncode))
    return p.stdout


def _decode(data: bytes, what: str) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        raise GateError("git %s gave output that is not valid UTF-8" % what) from None


def worktree_list(root: str) -> list:
    """Needs git 2.36 (``worktree list -z``); an older git exits 129 and this raises ``GateError`` (fail closed).
    ``(path, branch_or_None)`` for every entry of ``git worktree list --porcelain -z``, main first, in git's order:
    ``refs/heads/`` stripped, ``None`` for a detached or bare entry; prunable and locked entries are included."""
    out = _decode(_git(root, ["worktree", "list", "--porcelain", "-z"]), "worktree list")
    entries: list = []
    for field in out.split("\0"):
        if field.startswith("worktree "):
            entries.append([field[len("worktree "):], None])
        elif field.startswith("branch ") and entries:
            ref = field[len("branch "):]
            entries[-1][1] = ref[len(_HEADS):] if ref.startswith(_HEADS) else ref
    return [(path, branch) for path, branch in entries]


def bound_branch(top: str) -> Optional[str]:
    """The branch checked out at the worktree top level ``top``, ``None`` when detached; ``GateError`` when ``top``
    is not the top level of a worktree (a subdirectory, a missing path, no repository)."""
    entries = worktree_list(top)
    want = os.path.realpath(top)
    for path, branch in entries:
        if os.path.realpath(path) == want:
            return branch
    raise GateError("%s is not the top level of a worktree" % safe_text(top))


def same_repository(a: str, b: str) -> bool:
    """Needs git 2.31 (``--path-format``); an older git fails the call and the answer is ``False``.
    Equal ``git rev-parse --path-format=absolute --git-common-dir`` for ``a`` and ``b``; ``False`` for anything
    that is not a path of a repository (missing, no repository, not a ``str``)."""
    try:
        common = [_decode(_git(p, ["rev-parse", "--path-format=absolute", "--git-common-dir"]), "rev-parse")
                  .rstrip("\n") for p in (a, b)]
    except GateError:
        return False
    return common[0] != "" and common[0] == common[1]


def _unbound(reason: str) -> tuple:
    return frozenset(), ["this agent has no bound worktree (%s)" % reason]


def _subagent(ctx, state: Optional[dict]) -> tuple:
    if type(state) is not dict:
        return _unbound("the session store is unavailable")
    prompt = transcript.first_prompt(transcript.own_transcript(ctx))
    if prompt is None:
        return _unbound("its transcript has no readable first prompt")
    found = session.lookup(state, session.prompt_sha(prompt))
    if found is None:
        return _unbound("no single dispatch record matches its prompt")
    wt = found[2]
    if wt == "":
        return _unbound("its dispatch bound no worktree")
    if type(wt) is not str or not os.path.isabs(wt):
        return _unbound("the bound worktree is not an absolute path: %s" % safe_text(wt))
    if not os.path.isdir(wt):
        return _unbound("the bound worktree does not exist: %s" % safe_text(wt))
    return frozenset({os.path.realpath(wt)}), []


def _has_status_table(text: str) -> bool:
    """Whether ``programs.status_rows`` found the status table in ``text`` (its first line starting with ``|`` whose
    cells are the eleven headers, then a separator line): it returns ``[]`` both for a page with no such table and for
    a table of zero rows, and only the second is a page that names no worktree."""
    lines = text.split("\n")
    for n, line in enumerate(lines):
        if line.startswith("|") and programs._cells(line) == list(programs.STATUS_HEADERS):
            nxt = lines[n + 1] if n + 1 < len(lines) else ""
            return nxt.startswith("|") and set(nxt) <= set("|-: ")
    return False


def _status_cells(root: str, cfg: dict, name: str, known: set, tops: set, fails: list) -> None:
    """Add the worktree cells of program ``name``'s status page (read at the tip of ``<name>/integration``) that
    name an existing worktree of this repository; every other cell adds a fail line, an empty or ``-`` one nothing."""
    page = "%s/%s/status.md" % (programs._programs_dir(cfg), name)
    try:
        text = gitinfo.show(root, _HEADS + name + "/integration", page)
    except GateError as e:
        fails.append("program %s: status page unreadable (%s)" % (name, safe_text(e)))
        return
    if text is None:
        fails.append("program %s: %s is not a file at the tip of %s/integration" % (name, safe_text(page), name))
        return
    if not _has_status_table(text):
        fails.append("program %s: %s has no status table" % (name, safe_text(page)))
        return
    for row in programs.status_rows(text):
        if "__error__" in row:
            fails.append("program %s: status page line %s: %s" % (name, safe_text(row.get("__line__")),
                                                                 safe_text(row["__error__"])))
            continue
        cell = row["worktree"]
        if cell in ("", "-"):
            continue
        who = "program %s: status worktree %s" % (name, safe_text(cell))
        if not os.path.isabs(cell):
            fails.append("%s is not an absolute path" % who)
            continue
        if not os.path.isdir(cell):
            fails.append("%s does not exist" % who)
            continue
        real = os.path.realpath(cell)
        if real not in known:
            fails.append("%s is not a worktree of this repository" % who)
            continue
        tops.add(real)


def _session(ctx, root: str, cfg: dict) -> tuple:
    fails: list = []
    try:
        tops = {os.path.realpath(gitinfo.toplevel(ctx.cwd))}
    except GateError as e:
        return frozenset(), ["the session's working directory has no git top level (%s)" % safe_text(e)]
    try:
        names = programs.live_programs(root, cfg)
    except GateError as e:
        return frozenset(tops), ["live programs cannot be read (%s)" % safe_text(e)]
    if not names:
        return frozenset(tops), fails
    try:
        listing = worktree_list(root)
    except GateError as e:
        return frozenset(tops), ["worktrees cannot be listed (%s)" % safe_text(e)]
    known = {os.path.realpath(path) for path, _ in listing if os.path.isdir(path)}
    for name in names:
        for path, branch in listing:
            if branch == name + "/integration" and os.path.isdir(path):
                tops.add(os.path.realpath(path))
        _status_cells(root, cfg, name, known, tops, fails)
    return frozenset(tops), fails


def allowed(ctx, root: str, cfg: dict, state: Optional[dict]) -> tuple:
    """``(tops, fails)``: the worktree top levels the caller may write in (``realpath``ed), and one line per reason
    the set is narrower than the plan's. A subagent: exactly the worktree recorded for its own dispatch prompt
    (``session.lookup`` on the SHA of the first prompt of its own transcript, M3); none, with the fail ``this agent
    has no bound worktree (<reason>)``, when the store, the record or the worktree is missing. The session: the top
    level of ``cwd``, plus, while a program is live, the worktree cells of each live program's status page that name
    a worktree of this repository and the worktree holding ``<program>/integration``."""
    if ctx.agent_id is not None:
        return _subagent(ctx, state)
    return _session(ctx, root, cfg)
