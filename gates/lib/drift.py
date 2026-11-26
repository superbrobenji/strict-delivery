"""Drift facts: the status rows and handoffs of a program against git (Task 5c.1; plan block 5c, rulings R5c-2, R5c-3,
R5c-5, owner answers SE-12, Q-Pplan-8 (a), Q-Pplan-12 (a), Q-B5plan-3 (a); controller decisions D-5c-Q1 .. D-5c-Q33).

Every function is read-only. A check returns a list of ``(suffix, reason)``; a malformed argument is a ``ValueError``
(``programs`` style) and a git-facing argument or a repository failure a ``GateError``. A branch tip is read as
``refs/heads/<name>`` (a tag of the same name never stands in for it); the base branch is read once per call.
The numerals of a status row follow ``programs._NUMBER`` (at most 600 digits) and are compared as exact integers, so the
verdicts are the same on every interpreter."""
from __future__ import annotations

import json
import os
import re
import subprocess
from typing import Optional

from gates.lib import checkpoints, gitinfo, programs
from gates.lib.result import GateError, GitNotFound, _exact, safe_text

_HEADS = "refs/heads/"
_HEX40 = re.compile(r"[0-9a-f]{40}")
_HEX7_40 = re.compile(r"[0-9a-f]{7,40}")
_SLUG = re.compile(r"[a-z0-9][a-z0-9-]*")
_LIVE = ("running", "blocked", "checkpoint")
_ENDED = ("merged", "closed")
_MAX_DIGITS = 600
_GH_TIMEOUT = 30
_GH_STATES = ("OPEN", "CLOSED", "MERGED")


def _shown(x: object) -> str:
    """The raw text of ``x``, cut after the last whole character whose escaped form (``safe_text``) still fits in 80
    characters of output. It is NOT escaped here: every reason and every GateError text leaves through ``Result.render``
    or ``drift_cli._why``, which escape it exactly once (spec section 13: "each id and reason escaped exactly once, by
    ``Result.render`` (``safe_text``)"), so no raw non-printable character can leave by any path."""
    text = _exact(x) if issubclass(type(x), str) else _exact(str(x))
    out, width = [], 0
    for c in text:
        width += len(safe_text(c))
        if width > 80:
            break
        out.append(c)
    return "".join(out)


# ---------------------------------------------------------------- git readers

def _base_name(cfg: object) -> str:
    name = cfg.get("base_branch") if type(cfg) is dict else None
    if type(name) is not str or name == "":
        raise GateError("cfg: base_branch must be a non-empty string")
    return name


def _plan_state(cfg: object) -> str:
    paths = cfg.get("paths") if type(cfg) is dict else None
    d = paths.get("plan_state") if type(paths) is dict else None
    if type(d) is not str or d == "":
        raise GateError("cfg: paths.plan_state must be a non-empty string")
    return d


def _tip(root: str, name: str) -> str:
    """The full id of the tip of the local branch ``name``; a GateError when there is no such branch."""
    if name not in gitinfo.local_branches(root):
        raise GateError("no local branch %s" % _shown(name))
    ids = gitinfo.first_parent(root, _HEADS + name)
    if not ids:
        raise GateError("git rev-list gave no commit for %s" % _shown(name))
    return ids[0]


def _need_sha(value: object, name: str) -> str:
    if type(value) is not str or _HEX40.fullmatch(value) is None:
        raise GateError("%s must be 40 lowercase hex digits" % name)
    return value


def decisions_at(root: str, cfg: dict, ref: str) -> list:
    """The decision records under ``paths.decisions`` at ``ref`` (the plan's ``ls_tree`` + ``show`` + ``yamlsub.parse``
    is ``checkpoints.records_at``; decision D-5c-Q26): a file that does not parse is a GateError naming it."""
    return checkpoints.records_at(root, cfg, ref, "decision")


def merged_at(root: str, base: str, tip: str) -> Optional[str]:
    """The merge commit of R5c-5: a first-parent commit of ``base`` with exactly two parents, the second equal to ``tip``
    (newest such commit), else ``None``. Both arguments are full lowercase 40-hex ids (decision D-5c-Q10). One
    ``git rev-list --parents --first-parent`` read, with ``--no-replace-objects`` as ``gitinfo.first_parent``."""
    _need_sha(base, "base")
    _need_sha(tip, "tip")
    gitinfo._need_root(root)
    gitinfo._require_toplevel(root)
    p = gitinfo._run(root, "rev-list", ["rev-list", "--no-color", "--parents", "--first-parent", base + "^{commit}",
                                        "--"], opts=gitinfo._NO_REPLACE)
    for line in gitinfo._text(p.stdout, "rev-list").split("\n"):
        ids = line.split()
        if len(ids) == 3 and ids[2] == tip:
            return ids[0]
    return None


def _remote_of(root: str, branch: str) -> str:
    p = gitinfo._run(root, "config", ["config", "--get", "branch.%s.remote" % branch], ok=(0, 1))
    name = gitinfo._text(p.stdout, "config").strip() if p.returncode == 0 else ""
    return name if name else "<remote>"


def base_errors(root: str, cfg: dict) -> list:
    """``[("base", reason)]`` when the upstream of the local base branch is not an ancestor of it (a host merge reached
    the remote and a fetch brought it here), else ``[]``; local refs only, no network (review F-B5p-6, Rq-5-5,
    Q-B3plan-3 (a); decision D-5c-Q1). ``upstream_of`` is ``None``, equal, or behind: no failure."""
    bb = _base_name(cfg)
    tip = _tip(root, bb)
    up = gitinfo.upstream_of(root, bb)
    if up is None:
        return []
    try:
        if gitinfo.is_ancestor(root, up, tip):
            return []
    except GitNotFound:
        raise
    except GateError as e:
        return [("base", "the upstream of %s cannot be compared with it: %s" % (_shown(bb), _shown(str(e))))]
    remote = _remote_of(root, bb)
    if not _same_name_upstream(root, bb, remote):
        # plan :5446 states the command only for <remote>/<base_branch>; any other upstream gets a named refusal
        p = gitinfo._run(root, "rev-parse --abbrev-ref", ["rev-parse", "--abbrev-ref", bb + "@{upstream}"])
        return [("base", "update %s from its upstream %s: it is not %s/%s, so no update command is given"
                 % (_shown(bb), _shown(gitinfo._text(p.stdout, "rev-parse").strip()), _shown(remote), _shown(bb)))]
    try:
        path = _checkout_of(root, bb)
    except GitNotFound:
        raise
    except GateError as e:
        return [("base", "update %s from the remote: the worktrees cannot be listed: %s, so no update command is given"
                 % (_shown(bb), _shown(str(e))))]
    if path is not None:
        return [("base", "update %s from the remote: git -C %s fetch %s, then git -C %s merge --ff-only %s/%s"
                 % (_shown(bb), path, remote, path, remote, _shown(bb)))]
    return [("base", "update %s from the remote: no worktree has %s checked out, so no update command is given"
             % (_shown(bb), _shown(bb)))]


def _same_name_upstream(root: str, bb: str, remote: str) -> bool:
    """True when the upstream git resolves for ``bb`` is ``<remote>/<bb>``: ``branch.<bb>.remote`` is set and is not
    ``.``, and ``git rev-parse --symbolic-full-name <bb>@{upstream}`` (local refs only) prints exactly
    ``refs/remotes/<remote>/<bb>``. It is the resolved upstream that decides, not the ``git remote`` list or the
    ``branch.<bb>.merge`` value, so a legacy ``.git/remotes`` remote is accepted, and a several-valued merge, a fetch
    refspec into another namespace, a ``.git/branches`` remote and a merge naming another branch are not (plan :5446;
    F-20261124-urap, -9bes, -mev2)."""
    if remote == "<remote>" or remote == ".":
        return False
    p = gitinfo._run(root, "rev-parse --symbolic-full-name", ["rev-parse", "--symbolic-full-name", bb + "@{upstream}"])
    return gitinfo._text(p.stdout, "rev-parse").rstrip("\n") == "refs/remotes/%s/%s" % (remote, bb)


def _checkout_of(root: str, bb: str) -> Optional[str]:
    """The path of the first entry of ``git worktree list --porcelain -z`` (one read) whose branch is ``bb``, that git
    does not list as ``prunable`` and whose path is an existing directory (``os.path.isdir``, which follows symlinks:
    a locked entry with its directory gone, a path that is now a file or a FIFO are skipped); ``None`` when no entry is
    left (F-20261124-9v77). Needs git 2.36 (``-z``): an older git exits 129, a GateError. Path and branch are read from
    the ``worktree `` and ``branch `` fields, the flag from a field ``prunable`` (git 2.31 and later lists it)."""
    out = gitinfo._text(gitinfo._run(root, "worktree list", ["worktree", "list", "--porcelain", "-z"]).stdout,
                        "worktree list")
    entries: list = []
    for field in out.split("\0"):
        if field.startswith("worktree "):
            entries.append([field[len("worktree "):], None, False])
        elif field.startswith("branch ") and entries:
            ref = field[len("branch "):]
            entries[-1][1] = ref[len(_HEADS):] if ref.startswith(_HEADS) else ref
        elif (field == "prunable" or field.startswith("prunable ")) and entries:
            entries[-1][2] = True
    for path, branch, prunable in entries:
        if branch == bb and not prunable and os.path.isdir(path):
            return path
    return None


def integration_errors(root: str, cfg: dict, p: str) -> list:
    """``integration.<p>``: the tip of the local base branch is not an ancestor of ``<p>/integration`` (SE-12)."""
    why = programs.program_problem(p)
    if why:
        raise ValueError("program name: " + why)
    bb = _base_name(cfg)
    base = _tip(root, bb)
    tip = _tip(root, programs.branch_of(p))
    if gitinfo.is_ancestor(root, base, tip):
        return []
    return [("integration." + p, "integration is behind %s; run a sync" % _shown(bb))]


# ---------------------------------------------------------------- argument checks

def _need_args(cfg: object, prog: object, row: object, stream: object) -> None:
    if type(prog) is not programs.Program:
        raise ValueError("prog: must be a Program")
    if type(row) is not dict or set(row) != set(programs.STATUS_HEADERS) \
            or any(type(v) is not str for v in row.values()):
        raise ValueError("row: must be a status row of the eleven headers, every cell a string")
    if type(stream) is not dict or type(stream.get("id")) is not str:
        raise ValueError("stream: must be a streams.yml stream mapping with a string id")
    if row["stream"] != stream["id"]:
        raise ValueError("row and stream disagree: '%s' and '%s'" % (_shown(row["stream"]), _shown(stream["id"])))
    if row["status"] not in programs.STATUS_VALUES:
        raise ValueError("row: status '%s' is not one of %s" % (_shown(row["status"]), ", ".join(programs.STATUS_VALUES)))
    if "stacked_on" in stream and type(stream["stacked_on"]) is not str:
        raise ValueError("stream: stacked_on must be a string")
    streams = prog.streams.get("streams") if type(prog.streams) is dict else None
    if type(streams) is not list or any(type(s) is not dict for s in streams):
        raise ValueError("prog: streams must hold a list of stream mappings")
    seen = [stream["id"]]
    cur = stream
    while "stacked_on" in cur:
        nxt = cur["stacked_on"]
        if nxt in seen:
            raise ValueError("stream %s: stacked_on '%s' makes a cycle" % (_shown(stream["id"]), _shown(nxt)))
        found = [s for s in streams if s.get("id") == nxt]
        if not found:
            raise ValueError("stream %s: stacked_on '%s' is no stream of the program" % (_shown(stream["id"]), _shown(nxt)))
        seen.append(nxt)
        cur = found[0]
        if "stacked_on" in cur and type(cur["stacked_on"]) is not str:
            raise ValueError("stream: stacked_on must be a string")


def _slug(stream: dict) -> tuple:
    """``(slug, None)`` for the stream's plan, else ``(None, reason)``; a slug outside ``[a-z0-9][a-z0-9-]*`` is refused."""
    try:
        slug = checkpoints.plan_slug(stream.get("plan"))
    except ValueError as e:
        return None, str(e)
    if _SLUG.fullmatch(slug) is None:
        return None, "the plan name '%s' must match [a-z0-9][a-z0-9-]*" % _shown(slug)
    return slug, None


# ---------------------------------------------------------------- the per-stream checks

def _behind(root: str, prog: programs.Program, stream: dict, bb: str, base: str, tip: str) -> list:
    names, extra = [], []
    if not gitinfo.is_ancestor(root, base, tip):
        names.append(bb)
    parent = stream.get("stacked_on")
    if parent is not None:
        pb = programs.branch_of(prog.name, parent)
        if pb not in gitinfo.local_branches(root):
            extra.append("the stacked_on branch %s is missing" % _shown(pb))
        elif not gitinfo.is_ancestor(root, _tip(root, pb), tip):
            names.append(pb)
    parts = []
    if names:
        parts.append("behind %s; run a sync" % " and ".join(_shown(n) for n in names))
    parts += extra
    return [("behind." + stream["id"], "; ".join(parts))] if parts else []


def _handoff_problems(root: str, cfg: dict, stream: dict, row: dict, branch: str, tip: str) -> list:
    slug, why = _slug(stream)
    if slug is None:
        return ["stream plan: " + why]
    path = "%s/%s/handoff.md" % (_plan_state(cfg), slug)
    try:
        text = gitinfo.show(root, _HEADS + branch, path)
        if text is None:
            return ["no handoff at %s on %s" % (_shown(path), _shown(branch))]
        h = checkpoints.parse_handoff(text)
    except ValueError as e:
        return [str(e)]
    except GitNotFound:
        raise
    except GateError as e:
        return ["%s: %s" % (_shown(path), _shown(str(e)))]
    out = list(checkpoints.handoff_errors(h, cfg))
    for f in ("branch", "head", "block", "next_task"):
        if type(h.get(f)) is not str:
            out.append("%s: must be a string" % f)
    if type(h.get("branch")) is str and h["branch"] != branch:
        out.append("branch %s is not %s" % (_shown(h["branch"]), _shown(branch)))
    head = h.get("head")
    if type(head) is str:
        if _HEX7_40.fullmatch(head) is None:
            out.append("head: must be 7 to 40 lowercase hex")
        else:
            try:
                if not gitinfo.is_ancestor(root, head, tip):
                    out.append("head %s is not an ancestor of the branch tip" % head)
            except GitNotFound:
                raise
            except GateError as e:
                out.append("head %s: %s" % (head, _shown(str(e))))
    for field, cell in (("block", "block"), ("next_task", "next task")):
        if type(h.get(field)) is str and h[field] != row[cell]:
            out.append("%s: the status row says '%s', the handoff says '%s'"
                       % (cell, _shown(row[cell]), _shown(h[field])))
    return out


def _elem(i: str) -> str:
    """A cell element as shown in a reason: quoted when it is empty or has a space around it."""
    return _shown(i) if i != "" and i == i.strip() else "'%s'" % _shown(i)


def _cell_ids(cell: str) -> list:
    if cell == "none":
        return []
    out = []
    for part in cell.split(","):
        if part not in out:
            out.append(part)
    return out


def _pending_problems(root: str, cfg: dict, prog: programs.Program, stream: dict, row: dict) -> list:
    recs = decisions_at(root, cfg, _HEADS + programs.branch_of(prog.name))
    by_id: dict = {}
    for r in recs:
        if type(r.id) is str and r.id not in by_id:
            by_id[r.id] = r
    out, listed = [], set()
    for i in _cell_ids(row["pending decisions"]):
        listed.add(i)
        r = by_id.get(i)
        if r is None:
            out.append("%s names no decision record" % _elem(i))
            continue
        st = r.row.get("status") if type(r.row) is dict else None
        if st != "open":
            out.append("%s is %s, not open" % (_shown(i), _shown(st) if type(st) is str else "without a status"))
    slug, _ = _slug(stream)
    if slug is not None:
        tag = re.compile("q:" + re.escape(slug) + ":[a-z0-9][a-z0-9-]*")
        for r in recs:
            if type(r.id) is not str or r.id in listed or type(r.row) is not dict or r.row.get("status") != "open":
                continue
            topics = r.row.get("topics")
            hit = [t for t in topics if type(t) is str and tag.fullmatch(t)] if type(topics) is list else []
            if hit:
                out.append("open decision %s (topic %s) is not listed in pending decisions" % (_shown(r.id), _shown(hit[0])))
    return out


def _blockers_problems(prog: programs.Program, row: dict) -> list:
    by_id: dict = {}
    for r in prog.requests:
        if type(r.id) is str and r.id not in by_id:
            by_id[r.id] = r
    out = []
    for i in _cell_ids(row["blockers"]):
        r = by_id.get(i)
        if r is None:
            out.append("%s names no request of this program" % _elem(i))
            continue
        st = r.row.get("status") if type(r.row) is dict else None
        if type(st) is not str or st not in ("open", "accepted", "disputed"):
            out.append("request %s is %s, not open, accepted or disputed" % (_shown(i), _shown(st) if type(st) is str else "without a status"))
    return out


def stream_errors(root: str, cfg: dict, prog: programs.Program, row: dict, stream: dict) -> list:
    """The ``(suffix, reason)`` of one status row against git, in the order ``branch``, ``behind``, ``merged``,
    ``handoff``, ``pending``, ``blockers`` (decision D-5c-Q15). ``base`` is ``base_errors``'s, once per program."""
    _need_args(cfg, prog, row, stream)
    s, status = stream["id"], row["status"]
    bb = _base_name(cfg)
    base = _tip(root, bb)
    branch = programs.branch_of(prog.name, s)
    tip = _tip(root, branch) if branch in gitinfo.local_branches(root) else None
    out: list = []
    if tip is None and status in _LIVE:
        out.append(("branch." + s, "no local branch %s" % _shown(branch)))
    if tip is not None and status not in _ENDED:
        out += _behind(root, prog, stream, bb, base, tip)
    merge = merged_at(root, base, tip) if tip is not None else None
    if status in _ENDED:
        if tip is None:
            out.append(("merged." + s, "stream branches are kept until the program closes"))
        elif merge is None:
            out.append(("merged." + s, "%s has no merge commit on %s; if the PR merged on the host, update %s from the remote"
                        % (_shown(branch), _shown(bb), _shown(bb))))
    elif merge is not None:
        out.append(("merged." + s, "the stream has merged at %s; set status merged" % merge))
    if status in _LIVE and tip is not None:
        out += [("handoff." + s, why) for why in _handoff_problems(root, cfg, stream, row, branch, tip)]
    elif status == "ready" and (row["block"] != "none" or row["next task"] != "none"):
        out.append(("handoff." + s, "status ready needs block and next task to be none"))
    out += [("pending." + s, why) for why in _pending_problems(root, cfg, prog, stream, row)]
    out += [("blockers." + s, why) for why in _blockers_problems(prog, row)]
    return out


# ---------------------------------------------------------------- the estimate

def _numeral(row: dict, key: str) -> int:
    cell = row.get(key)
    if type(cell) is not str or programs._NUMBER.fullmatch(cell) is None:
        raise ValueError("row: %s must be a number of at most %d digits" % (key, _MAX_DIGITS))
    return int(cell)


def over_estimate(row: dict, pct: int) -> Optional[str]:
    """``None`` when ``used * 100 <= estimate * pct`` (exact integers), else ``over <s> used=<used> estimate=<estimate>
    limit=<pct>%`` (R5c-2: per status row; an estimate of 0 with used above 0 is over)."""
    if type(row) is not dict:
        raise ValueError("row: must be a dict")
    if type(pct) is not int or pct < 1 or pct >= 10 ** _MAX_DIGITS:
        raise ValueError("pct: must be an integer of 1 to %d digits" % _MAX_DIGITS)
    stream = row.get("stream")
    why = programs.stream_problem(stream)
    if why:
        raise ValueError("row: stream: " + why)
    used, estimate = _numeral(row, "used"), _numeral(row, "estimate")
    if used * 100 <= estimate * pct:
        return None
    return "over %s used=%s estimate=%s limit=%d%%" % (stream, row["used"], row["estimate"], pct)


# ---------------------------------------------------------------- the host

def _no_constant(name: str) -> object:
    raise ValueError("the constant %s is not allowed" % name)


def _int_digits(text: str) -> int:
    if len(text.lstrip("-")) > _MAX_DIGITS:
        raise ValueError("an integer of more than %d digits" % _MAX_DIGITS)
    return int(text)


def _no_duplicates(items: list) -> dict:
    out: dict = {}
    for k, v in items:
        if k in out:
            raise ValueError("duplicate key %s" % _shown(k))
        out[k] = v
    return out


def _gh_prs(text: str) -> list:
    """The ``gh pr list`` JSON as a list of PR mappings, the whole shape validated; ValueError otherwise."""
    data = json.loads(text, parse_constant=_no_constant, parse_int=_int_digits, object_pairs_hook=_no_duplicates)
    if type(data) is not list:
        raise ValueError("the output is not a JSON list")
    for pr in data:
        if type(pr) is not dict:
            raise ValueError("a list element is not an object")
        num = pr.get("number")
        if type(num) is not int:
            raise ValueError("number must be an integer")
        if pr.get("state") not in _GH_STATES or type(pr.get("state")) is not str:
            raise ValueError("state must be one of %s" % ", ".join(_GH_STATES))
        if type(pr.get("headRefOid")) is not str:
            raise ValueError("headRefOid must be a string")
        mc = pr.get("mergeCommit")
        if mc is not None and (type(mc) is not dict or type(mc.get("oid")) is not str):
            raise ValueError("mergeCommit must be null or an object with a string oid")
    return data


def _ask_gh(runner: object, root: str, base_branch: str, branch: str) -> list:
    argv = ["gh", "pr", "list", "--head", branch, "--base", base_branch, "--state", "all", "--json",
            "number,state,headRefOid,mergeCommit"]
    env = {k: v for k, v in os.environ.items() if k != "GH_REPO"}   # -R unset: GH_REPO would name another repository
    try:
        res = runner(argv, cwd=root, capture_output=True, text=True, timeout=_GH_TIMEOUT, env=env)  # type: ignore[operator]
    except subprocess.TimeoutExpired:
        raise GateError("gh timed out after %d seconds" % _GH_TIMEOUT) from None
    except FileNotFoundError:
        raise GateError("gh is not installed or not on PATH") from None
    except Exception as e:
        raise GateError("gh could not run: %s: %s" % (type(e).__name__, _shown(str(e)))) from None
    code, out, err = getattr(res, "returncode", None), getattr(res, "stdout", None), getattr(res, "stderr", None)
    if type(code) is not int:
        raise GateError("gh gave no exit status")
    if code != 0:
        first = err.split("\n", 1)[0] if type(err) is str else ""
        raise GateError("gh exited %d: %s" % (code, _shown(first)))
    if type(out) is not str:
        raise GateError("gh output is not text")
    try:
        return _gh_prs(out)
    except Exception as e:
        raise GateError("gh output is not the expected JSON list: %s" % _shown(str(e))) from None


def host_errors(root: str, cfg: dict, prog: programs.Program, runner: object = subprocess.run) -> list:
    """With ``--host`` (Q-B5plan-2 (a)): ``host.<s>`` per stream from ``gh pr list --head <branch> --base <base_branch>
    --state all --json ...`` (``-R`` unset, 30 s); any ``gh`` failure is exactly ``[("host", reason)]`` (fail closed, no
    partial pass; decision D-5c-Q31). A stream with no valid status row is ``host.<s>``."""
    if type(prog) is not programs.Program:
        raise ValueError("prog: must be a Program")
    if not callable(runner):
        raise ValueError("runner: must be callable")
    bb = _base_name(cfg)
    base = _tip(root, bb)
    streams = prog.streams.get("streams") if type(prog.streams) is dict else None
    if type(streams) is not list or any(type(s) is not dict or type(s.get("id")) is not str for s in streams):
        raise ValueError("prog: streams must hold a list of stream mappings")
    rows = {r["stream"]: r for r in programs.status_rows(prog.status_text) if "__error__" not in r}
    local = gitinfo.local_branches(root)
    out: list = []
    for st in streams:
        s = st["id"]
        row = rows.get(s)
        if row is None:
            out.append(("host." + s, "no status row to judge against the host"))
            continue
        branch = programs.branch_of(prog.name, s)
        try:
            prs = _ask_gh(runner, root, bb, branch)
        except GateError as e:
            return [("host", str(e))]
        merged = [pr for pr in prs if pr["state"] == "MERGED"]
        status = row["status"]
        if status == "merged":
            local_merge = merged_at(root, base, _tip(root, branch)) if branch in local else None
            if local_merge is None or not any(type(pr.get("mergeCommit")) is dict and pr["mergeCommit"]["oid"] == local_merge
                                              for pr in merged):
                out.append(("host." + s, "no PR of %s is MERGED with the merge commit %s found on %s" % (
                    _shown(branch), local_merge or "(none found locally)", _shown(bb))))
        elif status not in _ENDED and merged:
            out.append(("host." + s, "a PR of %s is MERGED while the status is %s" % (_shown(branch), _shown(status))))
    return out
