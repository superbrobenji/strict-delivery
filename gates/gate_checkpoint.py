"""Gate ``checkpoint``: the basic checkpoint check (spec 9; plan Task P1.3; decisions D-Q1 to D-Q26 of its table).

One line per id, in this order: ``handoff``, ``ledger``, ``agree``, ``head``, ``clean``, ``pushed``, ``reads``,
``worktrees``, ``merges`` (Task P3.1: every ``MERGED`` line of the ledger passes ``merge.merged_errors``; it prints
only when the handoff and the ledger passed), then Task 6K.2's ``cap``, ``records``, ``base``, ``files``, ``last``
(decisions D-6K2-Q1 to Q9: ``records``, ``base`` and ``files`` print when the handoff passed; ``cap`` and ``last`` also
need a readable ledger text, so a red last checkpoint fails both ``ledger`` and ``last``). ``--plan SLUG`` names the workspace
``<paths.plan_state>/<SLUG>/``. A line prints only when its inputs exist (D-Q2): ``ledger``, ``agree``, ``head``,
``reads`` and ``worktrees`` need a handoff that passed ``checkpoint.handoff``; ``agree`` also needs ``checkpoint.ledger``
to pass; ``clean`` and ``pushed`` always print. Several reasons for one id are joined with ``"; "`` (D-Q15), so every
id prints at most once. Git is read from local refs only (no network). The gate declares no kind (``PRODUCES = ()``,
D-Q23: stream B's workspace is live), so ``check schema`` does not check the handoff and the ledger of other plans.
"""
from __future__ import annotations

import errno
import os
import re
import stat
import sys

from gates.lib import checkpoints, config, gitinfo, merge, schema, worktrees
from gates.lib.result import GateError, Line, Result, _Once, gate_args, repo_root, run_gate
from gates.lib import tipread
from gates.lib.store import Store

PRODUCES: tuple = ()

_SLUG = re.compile(r"[a-z0-9][a-z0-9-]*")
_MISSING = (errno.ENOENT, errno.ENOTDIR, errno.ENAMETOOLONG)


def _args(args: list):
    p = gate_args("checkpoint")
    p.add_argument("--plan", default=None, action=_Once, help="the plan slug (required)")
    return p.parse_args(args)


def _root(ns) -> str:
    root = ns.root if ns.root is not None else repo_root()
    try:
        gitinfo.toplevel(root)
    except gitinfo.GitNotFound:
        raise
    except GateError as e:
        raise GateError("%s; run /strict-delivery:init" % e) from None
    return root


def _read_bytes(root: str, rel: str) -> tuple:
    """``(data, problem)`` for the file ``rel`` (``/``-joined) below ``root``: every component is looked at with
    ``lstat`` and none is followed (D-Q21); a directory component must be a real directory, the last a regular file.
    ``data`` is ``None`` with a ``problem`` text (D-Q16, D-Q22) when it cannot be read; nothing is opened before
    ``lstat`` has said regular file, so a FIFO is never opened."""
    parts = rel.split("/")
    path = root
    for i, part in enumerate(parts):
        path = os.path.join(path, part)
        shown = "/".join(parts[:i + 1])
        try:
            mode = os.lstat(path).st_mode
        except OSError as e:
            if e.errno in _MISSING:
                return None, "%s: missing" % rel
            return None, "%s: cannot read (%s)" % (rel, e.strerror or type(e).__name__)
        if i < len(parts) - 1:
            if stat.S_ISLNK(mode):
                return None, "%s: is a symlink; directories must be real directories" % shown
            if not stat.S_ISDIR(mode):
                return None, "%s: not a directory" % shown
        elif not stat.S_ISREG(mode):
            return None, "%s: is not a regular file (a directory, symlink or other entry is never followed)" % rel
    try:
        with open(path, "rb") as fh:
            return fh.read(), ""
    except OSError as e:
        return None, "%s: cannot read (%s)" % (rel, e.strerror or type(e).__name__)


def _read_text(root: str, rel: str) -> tuple:
    data, problem = _read_bytes(root, rel)
    if data is None:
        return None, problem
    try:
        return data.decode("utf-8"), ""
    except UnicodeDecodeError:
        return None, "%s: not valid UTF-8" % rel


def _add(res: Result, id_: str, reasons: list, note: str = "") -> None:
    """One line for ``id_``: FAIL with the reasons joined by ``"; "``, else PASS (with ``note`` as its reason)."""
    if reasons:
        res.fail(id_, "; ".join(reasons))
    elif note:
        res.lines.append(Line("PASS", id_, note))
    else:
        res.passed(id_)


def _handoff(root: str, cfg: dict, slug: str) -> tuple:
    """``(row, reasons)``: the parsed handoff and what is wrong with it (``row`` is ``None`` when nothing parsed)."""
    rel = "%s/%s/handoff.md" % (cfg["paths"]["plan_state"], slug)
    text, problem = _read_text(root, rel)
    if text is None:
        return None, [problem]
    sch = schema.load_schema(os.path.join(schema.SCHEMAS_DIR, "handoff.yml"))
    reasons = list(schema.validate_front_matter(sch, text, cfg))
    try:
        row = checkpoints.parse_handoff(text)
    except ValueError as e:
        return None, reasons or [str(e)]
    reasons += checkpoints.handoff_errors(row, cfg)
    try:
        named = checkpoints.plan_slug(row.get("plan"))
    except ValueError:
        named = slug  # handoff_errors has named the plan problem
    if named != slug:
        reasons.append("plan: names %s, not %s" % (named, slug))
    return row, reasons


def _same_commit(root: str, a: str, b: str) -> tuple:
    """``(same, reason)``: both name a commit and each is an ancestor of the other (D-Q9)."""
    for v in (a, b):
        if not gitinfo.commit_exists(root, v):
            return False, "%s is not a commit" % v
    return gitinfo.is_ancestor(root, a, b) and gitinfo.is_ancestor(root, b, a), ""


def _ledger(root: str, cfg: dict, row: dict) -> tuple:
    """``(lines, reasons, text)``: the conforming ``CHECKPOINT`` lines, what is wrong with the ledger the handoff names,
    and its text (``None`` when it could not be read)."""
    text, problem = _read_text(root, row["ledger"])
    if text is None:
        return [], [problem], None
    reasons = []
    plan_text = None
    try:
        if not gitinfo.commit_exists(root, row["head"]):
            reasons.append("plan text: handoff head %s is not a commit" % row["head"])
        else:
            plan_text = tipread.show_file(root, row["head"], row["plan"])
            if plan_text is None:
                reasons.append("plan text: %s is absent at %s" % (row["plan"], row["head"]))
    except GateError as e:
        reasons.append("plan text: %s" % e)
    reasons += checkpoints.ledger_errors(text, cfg, plan_text=plan_text)
    lines = checkpoints.checkpoint_lines(text)
    if not lines:
        reasons.append("no conforming CHECKPOINT line")
    else:
        last = lines[-1]
        if not (last["total"] >= 1 and last["passed"] == last["total"] and last["gates"] == "PASS"):
            reasons.append("line %d: last CHECKPOINT is not green (tests=%d/%d gates=%s)"
                           % (last["line"], last["passed"], last["total"], last["gates"]))
    return lines, reasons, text


def _merges(root: str, cfg: dict, plan: str, text: str) -> list:
    """``<suffix>: <reason>`` for every ``MERGED`` line of the ledger text that fails ``merge.merged_errors`` (Task P3.1,
    decision D-Q2). A ``ValueError`` (a non-slug plan, a line the grammar should have refused) is one reason, its text."""
    reasons = []
    try:
        for line in checkpoints.merged_lines(text):
            reasons += ["%s: %s" % e for e in merge.merged_errors(root, cfg, plan, line)]
    except ValueError as e:
        reasons.append(str(e))
    return reasons


def _cap(root: str, cfg: dict, row: dict, lines: list, text: str) -> list:
    """``checkpoint.cap`` (Task 6K.2, D-6K2-Q5, Q6): ``cap_errors`` for the plan read from the working tree. A plan that
    cannot be read, a duplicate task heading, a bad cap value or a handoff block outside ``[0-9A-Za-z]+`` is one reason
    on this line, so the other lines stay."""
    plan_text, problem = _read_text(root, row["plan"])
    if plan_text is None:
        return [problem]
    try:
        try:
            rulings = checkpoints.ledger_rulings(text, row["block"])
        except ValueError:
            rulings = 0  # only a block outside [0-9A-Za-z]+ raises; cap_errors names it first
        return checkpoints.cap_errors(row, lines, plan_text, cfg, rulings)
    except (GateError, ValueError) as e:
        return [str(e)]


def _records(root: str, cfg: dict, row: dict) -> list:
    """``checkpoint.records`` (Task 6K.2, D-6K2-Q4): the worktree's registers for a plain plan; with a handoff ``program``
    the tip of the local branch ``<program>/integration`` (``refs/heads/`` only, so a tag or a remote-tracking ref never
    answers). An unreadable register raises ``GateError`` (``checkpoint.input``, plan :6071)."""
    program = row.get("program")
    if program is None:
        findings = Store(root, "finding", cfg).load()
        decisions = Store(root, "decision", cfg).load()
    else:
        branch = "%s/integration" % program
        if branch not in gitinfo.local_branches(root):
            return ["branch %s is missing locally; fetch it" % branch]
        ref = "refs/heads/" + branch
        findings = checkpoints.records_at(root, cfg, ref, "finding")
        decisions = checkpoints.records_at(root, cfg, ref, "decision")
    try:
        return checkpoints.record_errors(row, findings, decisions)
    except ValueError as e:
        return [str(e)]


def _base(root: str, row: dict) -> list:
    """``checkpoint.base`` (Task 6K.2): ``head`` and ``base`` are commits and ``base`` is an ancestor of (or equal to)
    ``head``; ``commit_exists`` comes before ``is_ancestor``, which raises for a revision that is not a commit."""
    base, head = row["base"], row["head"]
    try:
        if not gitinfo.commit_exists(root, head):
            return ["head %s is not a commit" % head]
        if not gitinfo.commit_exists(root, base):
            return ["%s is not a commit" % base]
        if not gitinfo.is_ancestor(root, base, head):
            return ["%s is not an ancestor of %s" % (base, head)]
    except GateError as e:
        return [str(e)]
    return []


def _files(root: str, row: dict) -> list:
    """``checkpoint.files`` (Task 6K.2, D-6K2-Q7, Q8): the plan, then each spec in the handoff's order, must be in
    ``gitinfo.tracked_files`` (the index; regular files)."""
    tracked = gitinfo.tracked_files(root)
    return ["%s: not tracked" % rel for rel in [row["plan"]] + list(row["spec"]) if rel not in tracked]


def _agree(root: str, row: dict, last: dict) -> list:
    reasons = []
    if last["block"] != row["block"]:
        reasons.append("block: ledger line %d has %s, handoff has %s" % (last["line"], last["block"], row["block"]))
    if last["next"] != row["next_task"]:
        reasons.append("next: ledger line %d has %s, handoff next_task is %s" % (last["line"], last["next"], row["next_task"]))
    try:
        same, why = _same_commit(root, last["head"], row["head"])
    except GateError as e:
        same, why = False, str(e)
    if not same:
        reasons.append("head: %s" % (why or "ledger line %d names %s, handoff names %s: not the same commit"
                                     % (last["line"], last["head"], row["head"])))
    if row["ledger_from"] != last["line"] + 1:
        reasons.append("ledger_from: %s is not %d (the line after the last CHECKPOINT line, %d)"
                       % (row["ledger_from"], last["line"] + 1, last["line"]))
    return reasons


def _head_sha(root: str) -> tuple:
    try:
        return gitinfo.head_sha(root), ""
    except GateError:
        return None, "HEAD has no commit"


def _head(root: str, row: dict) -> list:
    reasons = []
    branch = gitinfo.current_branch(root)
    if branch is None:
        reasons.append("HEAD is detached; the handoff names branch %s" % row["branch"])
    elif branch != row["branch"]:
        reasons.append("branch: the handoff names %s, HEAD is on %s" % (row["branch"], branch))
    sha, why = _head_sha(root)
    if sha is None:
        reasons.append(why)
    elif not gitinfo.commit_exists(root, row["head"]):
        reasons.append("head: %s is not a commit" % row["head"])
    elif not gitinfo.is_ancestor(root, row["head"], sha):
        reasons.append("head: %s is not an ancestor of HEAD %s" % (row["head"], sha))
    return reasons


def _pushed(root: str, cfg: dict) -> tuple:
    """``(reasons, note)`` for ``checkpoint.pushed``."""
    branch = gitinfo.current_branch(root)
    if branch is None:
        return ["HEAD is detached, no branch to push"], ""
    if branch == cfg["base_branch"]:
        return ["the current branch %s is the base branch; checkpoints are made on a work branch" % branch], ""
    sha, why = _head_sha(root)
    if sha is None:
        return [why], ""
    names = gitinfo.remotes(root)
    if not names:
        return [], "no remote configured"
    up = gitinfo.upstream_sha(root)
    if up is None:
        return ["branch %s has no upstream; run git push -u %s %s" % (branch, names[0], branch)], ""
    if up != sha:
        return ["the upstream %s is not HEAD %s; push the checkpoint commit" % (up, sha)], ""
    return [], ""


def _line_count(data: bytes) -> int:
    """D-Q22: the number of ``\\n`` bytes, plus one when the file is not empty and does not end in ``\\n``."""
    return data.count(b"\n") + (1 if data and not data.endswith(b"\n") else 0)


def _reads(root: str, row: dict) -> list:
    reasons = []
    for entry in row.get("required_reads") or []:
        path = entry["path"]
        data, problem = _read_bytes(root, path)
        if data is None:
            reasons.append(problem)
            continue
        lines = entry.get("lines")
        if lines is None:
            continue
        count = _line_count(data)
        first, _, last = lines.partition("-")
        a = int(first)
        if last == "end":
            if not a <= count:
                reasons.append("%s: lines %s: the file has %d lines" % (path, lines, count))
        else:
            b = int(last)
            if not (a <= b <= count):
                reasons.append("%s: lines %s: need start <= end <= %d (the file's line count)" % (path, lines, count))
    return reasons


def _worktrees(root: str, row: dict) -> list:
    reasons = []
    for entry in row["worktrees"]:
        path = entry["path"]
        why = _worktree(root, entry)
        reasons += ["%s: %s" % (path, w) for w in why]
    return reasons


def _worktree(root: str, entry: dict) -> list:
    d = os.path.join(root, entry["path"])
    if not os.path.lexists(d):
        return ["directory missing"]
    if not os.path.isdir(d):
        return ["not a directory"]
    try:
        top = gitinfo.toplevel(d)
        same = os.path.samefile(d, top)
    except GateError:
        return ["not a git top level (not a repository)"]
    except OSError:
        return ["not a git top level"]
    if not same:
        return ["not a git top level"]
    if not worktrees.same_repository(root, d):  # Task 6K.2, D-6K2-Q9: a foreign repository's heads mean nothing here
        return ["not a worktree of this repository"]
    out = []
    try:
        sha = gitinfo.head_sha(d)
    except GateError:
        return ["HEAD has no commit"]
    try:
        if not gitinfo.commit_exists(d, entry["head"]):
            out.append("head %s is not a commit there" % entry["head"])
        elif not gitinfo.is_ancestor(d, entry["head"], sha):
            out.append("head %s is not an ancestor of its HEAD %s" % (entry["head"], sha))
        actual = gitinfo.current_branch(d)
    except GateError as e:
        return out + [str(e)]
    if actual != entry["branch"]:
        out.append("branch: recorded %s, actual %s" % (entry["branch"] if entry["branch"] is not None else "null (detached)",
                                                        actual if actual is not None else "null (detached)"))
    if entry["path"] == "." and entry["porcelain"] != "":
        out.append("porcelain: the root entry must be the empty string")
    return out


def check(args: list) -> Result:
    ns = _args(args)
    if ns.plan is None:
        raise GateError("--plan SLUG is required")
    if not _SLUG.fullmatch(ns.plan):
        raise GateError("--plan must match [a-z0-9][a-z0-9-]*")
    root = _root(ns)
    cfg = config.load(root)
    res = Result("checkpoint")
    row, reasons = _handoff(root, cfg, ns.plan)
    _add(res, "checkpoint.handoff", reasons)
    good = not reasons
    lines = []
    ledger_text = None  # set when the ledger passed: checkpoint.merges needs it
    text = None  # the ledger text when it could be read: checkpoint.cap and checkpoint.last need it
    if good:
        lines, ledger_reasons, text = _ledger(root, cfg, row)
        if not ledger_reasons:
            ledger_text = text
        _add(res, "checkpoint.ledger", ledger_reasons)
        if not ledger_reasons:
            _add(res, "checkpoint.agree", _agree(root, row, lines[-1]))
        _add(res, "checkpoint.head", _head(root, row))
    dirty = gitinfo.dirty_paths(root)
    _add(res, "checkpoint.clean", ["uncommitted paths: " + ", ".join(dirty)] if dirty else [])
    why, note = _pushed(root, cfg)
    _add(res, "checkpoint.pushed", why, note)
    if good:
        _add(res, "checkpoint.reads", _reads(root, row))
        _add(res, "checkpoint.worktrees", _worktrees(root, row))
    if ledger_text is not None:
        _add(res, "checkpoint.merges", _merges(root, cfg, ns.plan, ledger_text))
    if good:
        if text is not None:
            _add(res, "checkpoint.cap", _cap(root, cfg, row, lines, text))
        _add(res, "checkpoint.records", _records(root, cfg, row))
        _add(res, "checkpoint.base", _base(root, row))
        _add(res, "checkpoint.files", _files(root, row))
        if text is not None:
            _add(res, "checkpoint.last", checkpoints.last_line_errors(lines))
    return res


def main(argv=None) -> int:
    return run_gate("checkpoint", check, argv)


if __name__ == "__main__":
    sys.exit(main())
