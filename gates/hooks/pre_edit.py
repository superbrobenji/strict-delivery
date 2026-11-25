"""PreToolUse handler of the Edit, Write, MultiEdit and NotebookEdit tools (Task 3c.1, plan P:3853-3896).

It refuses any Edit or Write whose target path has the segments of ``paths.decisions`` as a contiguous run, case folded
through the frozen Unicode 13.0.0 table (``programs.fold``), over the lexical path, the real path of the normalised path
and the real path of the raw path (the controller rulings (3c) and Q1 (c)); only ``python3 -m gates decisions`` writes
there (owner answer Q-16 (a)). Otherwise it surfaces, once per session, every in-force decision whose ``applies_to`` glob
matches the repo-relative path of a target inside the repository root, and it blocks nothing else (spec section 4).

Stated limits: a hard link to a record and a write by the Bash tool are not detected here; the verdict is fixed when the
hook runs (a path component replaced between this hook and the tool's own action is not detectable); the configured
decisions path of an unloadable config is unknown, so the default is refused then. Standard library only."""
from __future__ import annotations

import fnmatch
import os
import posixpath

from gates.lib import config, decisions, print_table, programs, schema, session
from gates.lib.hookio import HookContext, Outcome
from gates.lib.result import GateError, safe_text
from gates.lib.store import Store

MAX_PATH_BYTES = 4096
_PATH_FIELD = {"Edit": "file_path", "Write": "file_path", "MultiEdit": "file_path", "NotebookEdit": "notebook_path"}
_INPUT_TAIL = ("; the Edit and Write tools need a non-empty string path in the tool's own field (file_path; "
               "notebook_path for NotebookEdit); the human can disable the plugin with /plugin until a fix merges, and "
               "!-prefixed commands still run")
_DENY = ("FAIL hook.edit.decisions: %s: decision records are written only by python3 -m gates decisions "
         "(owner answer Q-16 (a)); answers and withdrawals come from the human")


def _bad(reason: str) -> GateError:
    return GateError("hook.edit.input: " + reason)


def _clean(text: str) -> bool:
    """``text`` has no NUL and encodes to UTF-8 (no lone surrogate); ``os.path.realpath`` raises on both on 3.13 only."""
    if "\0" in text:
        return False
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def raw_target(ctx: HookContext) -> str:
    """The tool's own path field, joined to ``cwd`` when relative, not normalised (the OS resolves ``..`` after a
    symlink physically, so the raw spelling is one of the forms checked)."""
    tool = ctx.tool_name
    field = _PATH_FIELD.get(tool) if type(tool) is str else None
    if field is None:
        raise _bad("tool_name %s is not an edit tool" % safe_text(tool))
    if field not in ctx.tool_input:
        raise _bad("tool_input.%s is missing" % field)
    value = ctx.tool_input[field]
    if type(value) is not str:
        raise _bad("tool_input.%s must be a string" % field)
    if value == "":
        raise _bad("tool_input.%s is empty" % field)
    if not _clean(value):
        raise _bad("tool_input.%s holds a NUL or a lone surrogate" % field)
    if len(value.encode("utf-8")) > MAX_PATH_BYTES:
        raise _bad("tool_input.%s is longer than %d bytes" % (field, MAX_PATH_BYTES))
    return value if os.path.isabs(value) else os.path.join(ctx.cwd, value)


def target(ctx: HookContext) -> str:
    """The normalised absolute target of the call (plan P:3864)."""
    return posixpath.normpath(raw_target(ctx))


def _rel_problem(decisions_rel: object) -> str:
    if type(decisions_rel) is not str or decisions_rel == "":
        return "decisions_rel must be a non-empty string"
    if (not print_table.is_printable(decisions_rel) or decisions_rel.startswith("/")
            or ".." in decisions_rel.split("/") or decisions_rel == "." or posixpath.normpath(decisions_rel) != decisions_rel):
        return "decisions_rel must be a normalised repo-relative path of printable characters"
    return ""


def _segments(path: str) -> list:
    return [programs.fold(s) for s in path.split("/") if s != ""]


def _has_run(path: str, run: list) -> bool:
    segs = _segments(path)
    n = len(run)
    return any(segs[i:i + n] == run for i in range(len(segs) - n + 1))


def under_decisions(path: str, decisions_rel: str, raw: object = None) -> bool:
    """``True`` when ``path`` (absolute and normalised) holds the case-folded segments of ``decisions_rel`` as a
    contiguous run in its lexical form, in ``os.path.realpath`` of itself, or in ``os.path.realpath`` of ``raw`` (the
    un-normalised spelling, when given). Anything else than a normalised absolute ``path`` or a config-class
    ``decisions_rel`` is a ``ValueError`` (fail closed)."""
    if type(path) is not str or not _clean(path) or not path.startswith("/") or posixpath.normpath(path) != path:
        raise ValueError("path must be a normalised absolute string without NUL or lone surrogate")
    problem = _rel_problem(decisions_rel)
    if problem:
        raise ValueError(problem)
    if raw is not None and (type(raw) is not str or not _clean(raw) or not raw.startswith("/")):
        raise ValueError("raw must be an absolute string without NUL or lone surrogate")
    run = _segments(decisions_rel)
    forms = [path, os.path.realpath(path)]
    if raw is not None:
        forms.append(os.path.realpath(raw))
    return any(_has_run(f, run) for f in forms)


def _inside(root: str, path: str) -> object:
    """The repo-relative path of ``path`` under ``root``, or ``None`` outside it."""
    if path == root:
        return "."
    prefix = root if root.endswith("/") else root + "/"
    return path[len(prefix):] if path.startswith(prefix) else None


def _first_line(value: object) -> str:
    return safe_text(value.split("\n")[0]) if type(value) is str else ""


def _why(e: BaseException) -> str:
    return safe_text(e) if isinstance(e, GateError) else safe_text("%s: %s" % (type(e).__name__, e))


def _line(i: str, row: dict) -> str:
    rule = row.get("rule")
    cites = row.get("landed_in")
    shown = [safe_text(c) for c in cites if type(c) is str] if type(cites) is list else []
    return "in-force %s: %s; landed_in %s" % (
        safe_text(i), _first_line(rule if type(rule) is str and rule != "" else row.get("question")),
        ", ".join(shown) if shown else "none")


def _glob_problem(row: dict) -> str:
    """The reason ``applies_to`` of ``row`` cannot be matched, or ``""`` (absent counts as no globs)."""
    globs = row.get("applies_to")
    if "applies_to" not in row:
        return ""
    if type(globs) is not list:
        return "applies_to: must be a list"
    for n, g in enumerate(globs):
        if type(g) is str and schema.bracket_problem(g):
            return "applies_to.%d: %s" % (n, schema.bracket_problem(g))
    return ""


def _matching(ctx: HookContext, rels: list) -> list:
    """``[(id, line)]``, sorted by id, of the in-force decisions matching a repo-relative path of ``rels``; a record
    whose ``applies_to`` is unusable gives ``(id, FAIL line)`` with the id ``None`` (never marked)."""
    out = []
    records = Store(ctx.root, "decision", ctx.cfg).load()
    rows = sorted(((r.id, r.row) for r in decisions.in_force(records) if type(r.id) is str and type(r.row) is dict),
                  key=lambda t: t[0])
    for i, row in rows:
        problem = _glob_problem(row)
        if problem:
            out.append((None, "FAIL hook.edit.decisions-load: %s: %s" % (safe_text(i), safe_text(problem))))
            continue
        globs = row.get("applies_to") or []
        if any(type(g) is str and fnmatch.fnmatchcase(rel, g) for g in globs for rel in rels):
            out.append((i, _line(i, row)))
    return out


def handle(ctx: HookContext) -> Outcome:
    try:
        raw = raw_target(ctx)
    except GateError as e:
        return Outcome(deny=["FAIL " + safe_text(e) + _INPUT_TAIL])
    path = posixpath.normpath(raw)
    decisions_rel = ctx.cfg["paths"]["decisions"] if ctx.cfg is not None else config.DEFAULTS["paths"]["decisions"]
    if under_decisions(path, decisions_rel, raw):
        return Outcome(deny=[_DENY % safe_text(path)])
    if ctx.cfg is None:
        return Outcome()
    rels = []
    for form in (path, os.path.realpath(path)):
        rel = _inside(ctx.root, form)
        if rel is not None and rel != "." and rel not in rels:
            rels.append(rel)
    if not rels:
        return Outcome()
    try:
        found = _matching(ctx, rels)
    except Exception as e:
        return Outcome(context=["FAIL hook.edit.decisions-load: " + _why(e)])
    ids = [i for i, _ in found if i is not None]
    surfaced = None
    if ids:
        try:
            surfaced = []
            with session.locked(ctx.env, ctx.session_id) as state:
                for i in ids:
                    if session.mark_surfaced(state, i):
                        surfaced.append(i)
        except session.SessionUnavailable:
            surfaced = None   # no memory: every match is surfaced (plan P:3868)
    return Outcome(context=[line for i, line in found if i is None or surfaced is None or i in surfaced])
