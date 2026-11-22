"""Gate ``context``: a session's required reads against its read receipts (spec 9, 12; plan Task 5a.3; task domain
table 5a.3 with its binding controller decisions).

The narrow promise (owner answer Q-B5plan-4 (a), ruling R5a-4): the gate checks the reads of the session that makes a
dispatch or a commit through Claude Code. It does not check the reads of a role that neither dispatches nor commits
(reviewers, verifiers, investigators): for them the context list is printed, not gated. A receipt proves that the file
was opened at that content, not that it was read in full (the Read tool truncates long files, so a full read cannot
be told apart).

``--session KEY --kind KIND`` are required. The list is ``context.required`` over ``every``, the kind, the role and
the handoff's ``required_reads``; one line per id, in list order: ``context.unresolved.<path>`` (a placeholder has no
value), ``context.file.<path>`` (the resolved file is not a readable regular file now), ``context.read.<path>`` (no
receipt row of the session holds the file, or none at its current content). ``PASS context.reads`` when nothing
failed. An entry with ``lines`` passes on any current receipt of the file (owner answer Q-RD-7 (a)). Every input
problem is ``FAIL context.input`` (``check`` raises ``GateError``). The gate prints ``FAIL`` under every profile; the
refusal on ``strict`` is the caller's, through ``context.enforced``. ``PRODUCES = ("context",)``: ``check schema``
checks ``context.yml`` once ``gates.producers`` lists this module; receipts are never read by it (owner answer
Q-B5plan-5 (b)). The gate writes nothing and makes no git call of its own.
"""
from __future__ import annotations

import os
import posixpath
import stat
import sys

from gates.lib import config, context, dispatch, gitinfo, receipts
from gates.lib.result import GateError, Result, _Once, gate_args, repo_root, run_gate, safe_text

PRODUCES: tuple = ("context",)


def _args(args: list):
    p = gate_args("context")
    for flag, text in (("--session", "the session key (required)"), ("--kind", "the session kind (required)"),
                       ("--role", "the role"), ("--plan", "the plan slug"), ("--program", "the program name"),
                       ("--stream", "the stream id"), ("--brief", "the brief path"),
                       ("--handoff", "the handoff whose required_reads join the list")):
        p.add_argument(flag, default=None, action=_Once, help=text)
    return p.parse_args(args)


def _root(ns) -> str:
    root = ns.root if ns.root is not None else repo_root()
    if root == "":
        raise GateError("--root: must not be empty")
    try:
        gitinfo.toplevel(root)
    except gitinfo.GitNotFound:
        raise
    except GateError as e:
        raise GateError("%s; run /strict-delivery:init" % e) from None
    return root


def _handoff_rel(ns, kind: str, vals: dict, cfg: dict):
    """The repository-relative handoff: ``--handoff`` under the CLI's rules (D5a1-Q5 (A)), else the kind's default when
    its placeholders resolve, else ``None``."""
    if ns.handoff is not None:
        v = ns.handoff
        if v == "" or v.startswith("/") or "{" in v or "}" in v or "\0" in v or ".." in v.split("/") \
                or posixpath.normpath(v) != v or v == ".":
            raise GateError("--handoff: must be a normalised repo-relative path without placeholders")
        return v
    if kind in context.HANDOFFS:
        return context.resolve(context.HANDOFFS[kind], vals, cfg)
    return None


def _extras(root: str, cfg: dict, kind: str, vals: dict, ns) -> list:
    rel = _handoff_rel(ns, kind, vals, cfg)
    if rel is None:
        return []
    top = os.path.realpath(gitinfo.toplevel(root))
    joined = os.path.join(top, rel)
    try:
        link = stat.S_ISLNK(os.lstat(joined).st_mode)  # the path as given, before any realpath
    except (OSError, ValueError):
        link = False
    if link:
        raise GateError("%s: the handoff is a symbolic link; it is read as a regular file only" % joined)
    path = context.absolute(root, rel)
    if not path.startswith(top.rstrip("/") + "/"):
        raise GateError("%s: the handoff is outside this repository's tree" % path)
    return context.handoff_reads(path, cfg)


def check(args: list) -> Result:
    ns = _args(args)
    if ns.session is None:
        raise GateError("--session KEY is required")
    if ns.kind is None:
        raise GateError("--kind KIND is required")
    problem = receipts.session_problem(ns.session)
    if problem:
        raise GateError(problem)
    try:
        kind, _ = context.kind_of(ns.kind)
    except ValueError as e:
        raise GateError(str(e)) from None
    if ns.role is not None and ns.role not in dispatch.ROLES:
        raise GateError("--role: unknown role %s; the roles are %s" % (safe_text(ns.role), ", ".join(dispatch.ROLES)))
    root = _root(ns)
    cfg = config.load(root)
    ctx = context.load(root, cfg)
    try:
        vals = context.values_for(root, cfg, ns.kind, ns.plan, ns.program, ns.stream, ns.brief)
        extras = _extras(root, cfg, kind, vals, ns)
        needed = context.required(ctx, kind, ns.role, vals, extras, cfg)
    except ValueError as e:
        raise GateError(str(e)) from None
    by_path: dict = {}
    for row in receipts.load(root, cfg, ns.session):
        by_path.setdefault(row["path"], []).append(row["sha"])
    res = Result("context")
    seen: set = set()
    verdict: dict = {}
    for entry, resolved in needed:
        if resolved is None:
            fid = "context.unresolved." + entry["path"]
            reason = "needs {%s}" % context.needs(entry["path"], vals)
        else:
            path = context.absolute(root, resolved)
            if path not in verdict:
                try:
                    now = receipts.content_sha(path)
                except GateError:
                    verdict[path] = ("context.file." + path, "not a readable regular file now")
                else:
                    shas = by_path.get(path, [])
                    if now in shas:
                        verdict[path] = None
                    elif shas:
                        verdict[path] = ("context.read." + path, "read at %s, now %s: read it again" % (shas[-1], now))
                    else:
                        verdict[path] = ("context.read." + path, "not read in this session")
            if verdict[path] is None:
                continue
            fid, reason = verdict[path]
        if fid not in seen:
            seen.add(fid)
            res.fail(fid, reason)
    if not res.lines:
        res.passed("context.reads")
    return res


def main(argv=None) -> int:
    return run_gate("context", check, argv)


if __name__ == "__main__":
    sys.exit(main())
