"""Tool ``context``: print the reads a session must make, one line per chunk (spec 9; plan Task 5a.1; task domain
table 5a.1 with its binding controller decisions).

Standard library only. ``python3 -m gates.tools.context_cli <kind> [--role R] [--plan S] [--program P]
[--stream S] [--brief PATH] [--handoff PATH] [--root R]``. Lines: ``read <absolute path> lines <a>-<b> blob <40-hex
blob id> -- <why>``, ``unresolved <path>: needs {<placeholder>}``, ``missing <absolute path> -- <why>``. Exit 0 when
every entry resolved and none is missing, 1 when any is unresolved or missing, 2 on a usage or load error (stdout empty,
one stderr line ``context: <reason>``). The blob id is ``gitinfo.blob_ids``'s; a path it cannot take (a git-ignored
file, a file outside the repository, a symlink) is exit 2 naming the path (decision D-Q1 (a), an interim that fails
closed). The tool declares no produced kind.
"""
from __future__ import annotations

import os
import posixpath
import stat
import sys
from typing import List, Optional

from gates.lib import config, context, dispatch, gitinfo
from gates.lib.result import GateError, _Once, gate_args, repo_root, safe_text


def _parser():
    p = gate_args("context")
    p.add_argument("kind", metavar="KIND")
    for flag in ("--role", "--plan", "--program", "--stream", "--brief", "--handoff"):
        p.add_argument(flag, default=None, action=_Once)
    return p


def _handoff_arg(value: str) -> str:
    """``--handoff``: a normalised repo-relative path, no placeholder, nothing absolute (decision D-Q5 (A))."""
    if value == "" or value.startswith("/") or "{" in value or "}" in value or "\0" in value \
            or ".." in value.split("/") or posixpath.normpath(value) != value or value == ".":
        raise ValueError("--handoff: must be a normalised repo-relative path without placeholders")
    return value


def _is_file(path: str) -> bool:
    try:
        return stat.S_ISREG(os.stat(path).st_mode) and os.access(path, os.R_OK)
    except (OSError, ValueError):
        return False


def _lines(root: str, cfg: dict, ctx: dict, kind: str, ns, vals: dict) -> tuple:
    """``(lines, code)``: every output line and the exit code, built before anything is printed."""
    top = os.path.realpath(gitinfo.toplevel(root))
    extras: list = []
    handoff = None
    hrel = None
    if ns.handoff is not None:
        hrel = _handoff_arg(ns.handoff)
    elif kind in context.HANDOFFS:
        hrel = context.resolve(context.HANDOFFS[kind], vals, cfg)
    if hrel is not None:
        joined = os.path.join(top, hrel)
        try:
            link = stat.S_ISLNK(os.lstat(joined).st_mode)  # the path as given, before any realpath (R1-1, PD15)
        except (OSError, ValueError):
            link = False
        if link:
            raise GateError("%s: the handoff is a symbolic link; it is read as a regular file only" % joined)
        handoff = context.absolute(root, hrel)
        if not handoff.startswith(top.rstrip("/") + "/"):
            raise GateError("%s: the handoff is outside this repository's tree" % handoff)
    handoff_missing = None
    if handoff is not None:
        try:
            regular = stat.S_ISREG(os.lstat(handoff).st_mode)
        except (OSError, ValueError):
            regular = False
        if regular:
            extras = context.handoff_reads(handoff, cfg)
        else:
            handoff_missing = handoff
    out, code, blobs, missing = [], 0, {}, set()
    for entry, resolved in context.required(ctx, kind, ns.role, vals, extras, cfg):
        if resolved is None:
            out.append("unresolved %s: needs {%s}" % (entry["path"], context.needs(entry["path"], vals)))
            code = 1
            continue
        abs_path = context.absolute(root, resolved)
        if not _is_file(abs_path):
            out.append("missing %s -- %s" % (abs_path, entry["why"]))
            missing.add(abs_path)
            code = 1
            continue
        try:
            link = stat.S_ISLNK(os.lstat(os.path.join(top, resolved)).st_mode)
        except (OSError, ValueError):
            link = False
        if link:
            raise GateError("%s: is a symbolic link; no blob id can be taken (gitinfo.blob_ids refuses it)" % abs_path)
        if not abs_path.startswith(top.rstrip("/") + "/"):
            raise GateError("%s: outside this repository's tree; no blob id can be taken (gitinfo.blob_ids takes "
                            "repository paths only)" % abs_path)
        rel = abs_path[len(top.rstrip("/")) + 1:]
        if rel not in blobs:
            try:
                blobs[rel] = gitinfo.blob_ids(root, [rel])[rel]
            except GateError as e:
                raise GateError("%s: no blob id can be taken (%s)" % (abs_path, e)) from None
        for a, b in context.split(abs_path, entry.get("lines"), cfg):
            out.append("read %s lines %d-%d blob %s -- %s" % (abs_path, a, b, blobs[rel], entry["why"]))
    if handoff_missing is not None and handoff_missing not in missing:
        out.append("missing %s -- handoff of %s" % (handoff_missing, kind))
        code = 1
    return out, code


def _run(ns) -> int:
    root = ns.root if ns.root is not None else repo_root()
    if root == "":
        raise GateError("--root: must not be empty")
    kind, _ = context.kind_of(ns.kind)
    if ns.role is not None and ns.role not in dispatch.ROLES:
        raise ValueError("--role: unknown role %s; the roles are %s" % (safe_text(ns.role), ", ".join(dispatch.ROLES)))
    cfg = config.load(root)
    ctx = context.load(root, cfg)
    vals = context.values_for(root, cfg, ns.kind, ns.plan, ns.program, ns.stream, ns.brief)
    lines, code = _lines(root, cfg, ctx, kind, ns, vals)
    text = "".join(line + "\n" for line in lines)
    try:
        text.encode(sys.stdout.encoding or "utf-8")
    except (UnicodeEncodeError, LookupError):
        raise GateError("a path cannot be encoded for the output") from None
    sys.stdout.write(text)
    return code


def main(argv: Optional[List[str]] = None) -> int:
    """``python3 -m gates.tools.context_cli <kind> ...``: 0, 1 (an unresolved or missing read) or 2 (error)."""
    if argv is None:
        args = list(sys.argv[1:])
    elif type(argv) is list and all(type(a) is str for a in argv):
        args = list(argv)
    else:
        sys.stderr.write("context: argv must be a list of str\n")
        return 2
    try:
        ns = _parser().parse_args(args)
    except GateError:
        return 2  # the parser has written the usage or help to stderr
    try:
        return _run(ns)
    except (GateError, ValueError) as e:
        sys.stderr.write("context: %s\n" % safe_text(e))
        return 2


if __name__ == "__main__":
    sys.exit(main())
