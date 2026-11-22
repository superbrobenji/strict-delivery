"""Dispatch rules for ``gate_dispatch`` (spec section 10, plan Task 2c.3): roles, tiers, dispatchers, depth and limits,
the prompt grammar, the strict block and the small re-review conditions 1-5 (standard library only).

Narrow promise of ``small_errors`` (module contract): it checks spec section 10's small re-review conditions 1-5 only as
far as a gate can: round, ancestry, diff size, excluded paths and finding severities. It does not check that no owner
question is open or that the previous review found no fix-caused defect: the controller's line carries both
(``questions=none``, ``prev-fix-defects=0``) and a small re-reviewer escalates when either is false (owner Q-RD-12 (a)).

No ``str.lower``, ``isdigit``, ``isprintable`` or ``strip`` of non-ASCII text decides a verdict, and no ``int()`` reads
text of unbounded length, so the verdicts are the same on every supported interpreter (table rows V1, V2)."""
from __future__ import annotations

import fnmatch
import os
import re
import stat
from typing import Mapping, Optional

from gates.lib import gitinfo
from gates.lib.result import GateError, safe_text

HEADINGS: tuple = ("## Role", "## Brief", "## Findings", "## Claims", "## Budget: tokens=<n> minutes=<n>", "## Model",
                   "## Report", "## Strict block", "## Task")
_NAMES = ("Role", "Brief", "Findings", "Claims", "Budget", "Model", "Report", "Strict block", "Task")
_BUDGET = re.compile(r"## Budget: tokens=[1-9][0-9]* minutes=[1-9][0-9]*")

ROLES: tuple = ("program_controller", "stream_controller", "controller", "implementer", "implementer_transcription",
                "task_reviewer", "final_reviewer", "final_verifier", "exception_reviewer", "audit_reviewer",
                "audit_verifier", "investigator", "plan_writer", "plan_reviewer", "drafter")
CONTROLLER_ROLES: tuple = ("program_controller", "stream_controller", "controller")
MIN_TIERS: dict = {"implementer_transcription": 1, "implementer": 2, "controller": 3, "program_controller": 3,
                   "stream_controller": 3, "task_reviewer": 2, "final_reviewer": 3, "audit_reviewer": 3,
                   "audit_verifier": 3, "investigator": 3, "final_verifier": 4, "exception_reviewer": 4,
                   "plan_writer": 3, "plan_reviewer": 3, "drafter": 2}
SMALL_ROLES: tuple = ("task_reviewer",)
DEFAULT_TOP_TIER_ROLES: tuple = ("final_verifier", "exception_reviewer")  # spec section 6; config does not default it
DEFAULT_TOP_TIER_FALLBACK = "tier3"
TIER_NAMES: tuple = ("tier1", "tier2", "tier3", "tier4")

# Measured Claude Code facts (coordinator, 2026-11-01; plan P:1289): with CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH unset the
# Agent tool exists at levels 1-2 (level 3 is a leaf), set to 5 it exists at levels 1-5, so the depth is N + 1; with
# CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS unset a launch past 20 is refused, not queued, set to 30 twenty-five ran at once.
CLAUDE_DEFAULT_DEPTH = 3
CLAUDE_DEFAULT_CONCURRENT = 20
ENV_DEPTH = "CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH"
ENV_CONCURRENT = "CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS"
# One cap on every decimal text this PR converts with int() and every integer it prints: 600 digits, below 640 (the
# lowest PYTHONINTMAXSTRDIGITS CPython 3.11+ accepts, sys.int_info.str_digits_check_threshold) with room for the ``+ 1``
# sums, so int() and %d never raise under any setting and 3.9 and 3.13 print the same bytes (Decision D15, narrowed).
MAX_DIGITS = 600

LEVELS_BELOW: dict = {"program_controller": 2, "stream_controller": 1, "controller": 1}


# The dispatchers a worker role (a framework worker or a project role, Q-H4) accepts, by program_live.
WORKER_DISPATCHERS: dict = {True: ("stream_controller", "controller"), False: ("session", "controller")}


def _dispatchers() -> dict:
    workers = tuple(r for r in ROLES if r not in CONTROLLER_ROLES)
    live = {"program_controller": ("session",), "stream_controller": ("session", "program_controller"),
            "controller": ("stream_controller", "controller")}
    plain = {"program_controller": (), "stream_controller": (), "controller": ("session", "controller")}
    for w in workers:
        live[w] = WORKER_DISPATCHERS[True]
        plain[w] = WORKER_DISPATCHERS[False]
    return {True: live, False: plain}


DISPATCHERS: dict = _dispatchers()


_ROLE_ID = re.compile(r"[a-z][a-z0-9_]*")


class RoleCollision(ValueError):
    """A project role id that may not be used: a framework role id, or ``session``."""


def _roles_map(cfg: object) -> dict:
    if type(cfg) is not dict:
        raise ValueError("cfg must be a mapping")
    roles = cfg.get("roles", {})
    if type(roles) is not dict:
        raise ValueError("roles must be a mapping")
    for k in roles:
        if type(k) is not str or not _ROLE_ID.fullmatch(k):
            raise ValueError("roles: '%s' is not a role id [a-z][a-z0-9_]*" % safe_text(str(k)))
    return roles


def project_ids(cfg: dict) -> tuple:
    """The project role ids of ``cfg['roles']``, sorted by code point, collisions not checked (ValueError for a shape
    ``config.load`` cannot return)."""
    return tuple(sorted(_roles_map(cfg)))


def roles_of(cfg: dict) -> tuple:
    """``ROLES`` plus the project role ids in sorted order. An id equal to a framework role raises ``RoleCollision``
    (the first in sorted order); so does ``session``, the main session's dispatcher id. Project roles are workers: they
    are in no constant here."""
    ids = project_ids(cfg)
    for i in ids:
        if i in ROLES:
            raise RoleCollision("%s: a project role may not reuse a framework role id" % i)
        if i == "session":
            raise RoleCollision("session: a project role may not reuse the dispatcher id session")
    return ROLES + ids


def dispatchers_for(live: bool, role: str) -> tuple:
    """The dispatchers allowed for ``role``: the ``DISPATCHERS`` row of a framework role, the worker row of any other id
    (a project role); ``DISPATCHERS`` itself is never extended."""
    return DISPATCHERS[live][role] if role in DISPATCHERS[live] else WORKER_DISPATCHERS[live]


def depth_ok(role: str, dispatcher_depth: int, max_depth: int) -> bool:
    return dispatcher_depth + 1 + LEVELS_BELOW.get(role, 0) <= max_depth


# ---------------------------------------------------------------- limits

def _env_limit(env: Mapping, name: str) -> Optional[int]:
    if name not in env:
        return None
    v = env[name]
    if type(v) is not str or len(v) > MAX_DIGITS or not re.fullmatch(r"[1-9][0-9]*", v):
        raise ValueError("%s must be a decimal integer of at least 1 (digits 0-9 only, no sign, space or leading zero, "
                         "at most %d digits)" % (name, MAX_DIGITS))
    return int(v)


def limits_of(cfg: dict, env: Mapping) -> tuple:
    """``(max_depth, max_concurrent)``: the minimum of the config limit (when set) and the Claude Code value, which
    always counts, set or unset (F-B2p2-3: never fails open)."""
    d = _env_limit(env, ENV_DEPTH)
    c = _env_limit(env, ENV_CONCURRENT)
    depth = CLAUDE_DEFAULT_DEPTH if d is None else d + 1
    conc = CLAUDE_DEFAULT_CONCURRENT if c is None else c
    limits = cfg.get("limits") or {}
    if "max_depth" in limits:
        depth = min(depth, limits["max_depth"])
    if "max_concurrent" in limits:
        conc = min(conc, limits["max_concurrent"])
    return depth, conc


# ---------------------------------------------------------------- grammar

def parse(prompt: str) -> tuple:
    """``(sections, errors)``. Every line starting ``## `` is a heading, split on LF only (a CR or a BOM makes a line
    no match: Decision D7). The headings must be exactly ``HEADINGS``, in order, each once; text before ``## Role`` is
    an error. A section's body is the text between its heading line and the next heading line."""
    lines = prompt.split("\n")
    marks = [i for i, ln in enumerate(lines) if ln.startswith("## ")]
    errors = []
    if (marks and marks[0] > 0) or (not marks and prompt != ""):
        errors.append("text before the first heading (preamble)")
    found = [lines[i] for i in marks]
    names = []
    for ln in found:
        if ln.startswith("## Budget") and _BUDGET.fullmatch(ln):
            names.append("Budget")
        elif ln in HEADINGS[:4] + HEADINGS[5:]:
            names.append(ln[3:])
        else:
            names.append(None)
    want = list(_NAMES)
    for n, ln in zip(names, found):
        if n is None:
            what = "the budget heading is not '## Budget: tokens=<n> minutes=<n>' with n a positive decimal integer " \
                   "with no leading zero" if ln.startswith("## Budget") else "unexpected heading '%s'" % ln
            errors.append(what)
    seen: dict = {}
    for n in names:
        if n is not None:
            seen[n] = seen.get(n, 0) + 1
    for n in want:
        if seen.get(n, 0) == 0:
            errors.append("missing heading %s" % ("## " + n if n != "Budget" else HEADINGS[4]))
        elif seen[n] > 1:
            errors.append("duplicate heading %s" % ("## " + n if n != "Budget" else HEADINGS[4]))
    if not errors and names != want:
        errors.append("headings are not in the order %s" % ", ".join(HEADINGS))
    sections: dict = {}
    for k, i in enumerate(marks):
        n = names[k]
        if n is None or n in sections:
            continue
        end = marks[k + 1] if k + 1 < len(marks) else None
        body = "\n".join(lines[i + 1:end]) + ("\n" if end is not None else "")
        sections[n] = body
    return sections, errors


def role_of(body: str, roles: tuple = ROLES) -> str:
    """The first non-empty line of the ``## Role`` body, exactly a role id of ``roles`` (default the framework roles; a
    project passes ``roles_of(cfg)``); anything else is a ValueError."""
    for line in body.split("\n"):
        if line != "":
            if line in roles:
                return line
            raise ValueError("the first non-empty line of ## Role must be exactly one role id, not '%s'" % line)
    raise ValueError("## Role is empty")


def block_errors(body: str, role: str, prompts_dir: str) -> list:
    """The body must equal ``"\\n" + <prompts_dir>/<role>.md + "\\n"`` byte for byte."""
    path = os.path.join(prompts_dir, role + ".md")
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
    except OSError as e:
        return ["strict block file %s cannot be read (%s)" % (path, e.strerror or type(e).__name__)]
    try:
        want = "\n" + raw.decode("utf-8") + "\n"
    except UnicodeDecodeError:
        return ["strict block file %s is not valid UTF-8" % path]
    if body != want:
        return ["## Strict block is not the block %s byte for byte (blank line, the file, blank line)" % path]
    return []


def _project_prompt(role: str, cfg: dict) -> str:
    """The checked ``roles.<role>.prompt`` of a project role (ValueError otherwise): an exact non-empty ``str``, a
    normalised repository-relative path ending ``.md``, no backslash, space, control character or ``..``."""
    entry = _roles_map(cfg).get(role) if type(role) is str else None
    if type(entry) is not dict:
        raise ValueError("%s is no framework role and no project role" % safe_text(str(role)))
    pr = entry.get("prompt")
    parts = pr.split("/") if type(pr) is str else []
    if (type(pr) is not str or not pr.endswith(".md") or pr.startswith("/") or "\\" in pr or " " in pr
            or any(ord(c) < 32 or ord(c) == 127 for c in pr) or any(p in ("", ".", "..") for p in parts)
            or parts[-1] == ".md"):
        raise ValueError("roles.%s.prompt is not a normalised repository-relative .md path" % role)
    return pr


def prompt_path(role: str, cfg: dict, prompts_dir: str, root: str) -> str:
    """The framework prompt file of a framework role (unchanged); ``<root>/<roles.<role>.prompt>`` of a project role."""
    if role in ROLES:
        return os.path.join(prompts_dir, role + ".md")
    return os.path.join(root, _project_prompt(role, cfg))


def project_block_errors(body: str, role: str, cfg: dict, root: str) -> list:
    """Like ``block_errors`` for a project role, reading ``<root>/<prompt>`` from the working tree: every component below
    ``root`` is ``lstat``ed (a symlink or non-directory component, a symlink or non-regular file is refused before any
    open), the file is opened with ``O_NOFOLLOW`` and ``O_NONBLOCK`` and ``fstat``ed, and a file larger than the body is
    refused without being read (Decision D8)."""
    try:
        rel = _project_prompt(role, cfg)
    except ValueError as e:
        return [str(e)]
    cur = root
    parts = rel.split("/")
    for i, part in enumerate(parts):
        cur = os.path.join(cur, part)
        try:
            mode = os.lstat(cur).st_mode
        except OSError as e:
            return ["strict block file %s cannot be read (%s)" % (rel, e.strerror or type(e).__name__)]
        if i < len(parts) - 1:
            if not stat.S_ISDIR(mode):
                return ["strict block file %s: the component '%s' is a symlink or not a directory" % (rel, part)]
        elif stat.S_ISLNK(mode):
            return ["strict block file %s is a symlink, never followed" % rel]
        elif not stat.S_ISREG(mode):
            return ["strict block file %s is not a regular file" % rel]
    try:
        fd = os.open(cur, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    except OSError as e:
        return ["strict block file %s cannot be read (%s)" % (rel, e.strerror or type(e).__name__)]
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            return ["strict block file %s is not a regular file" % rel]
        limit = len(body.encode("utf-8", "surrogatepass"))
        if st.st_size > limit:
            return ["## Strict block is not the block %s byte for byte (blank line, the file, blank line)" % rel]
        with os.fdopen(fd, "rb", closefd=False) as fh:
            raw = fh.read(limit + 1)
    except OSError as e:
        return ["strict block file %s cannot be read (%s)" % (rel, e.strerror or type(e).__name__)]
    finally:
        os.close(fd)
    try:
        want = "\n" + raw.decode("utf-8") + "\n"
    except UnicodeDecodeError:
        return ["strict block file %s is not valid UTF-8" % rel]
    if body != want:
        return ["## Strict block is not the block %s byte for byte (blank line, the file, blank line)" % rel]
    return []


def budget_numbers(prompt: str) -> Optional[tuple]:
    """The two digit texts ``(tokens, minutes)`` of the first valid ``## Budget`` heading line of ``prompt``, else None.
    The texts are never converted here: a caller compares by length first (no ``int()`` of unbounded text, row V1)."""
    for ln in prompt.split("\n"):
        if ln.startswith("## Budget") and _BUDGET.fullmatch(ln):
            tokens, minutes = ln[len("## Budget: "):].split(" ")
            return tokens[len("tokens="):], minutes[len("minutes="):]
    return None


def over_cap(text: str, cap: int) -> bool:
    """Whether the digit text ``text`` is greater than ``cap`` (``cap`` below ``10**MAX_DIGITS``): by length when the
    text has more than ``MAX_DIGITS`` digits, so no ``int()`` reads unbounded text."""
    return True if len(text) > MAX_DIGITS else int(text) > cap


def model_line(body: str) -> Optional[str]:
    """The one line of a ``## Model`` body (leading and trailing empty lines dropped), else None (Decision D8)."""
    lines = body.split("\n")
    while lines and lines[0] == "":
        lines.pop(0)
    while lines and lines[-1] == "":
        lines.pop()
    return lines[0] if len(lines) == 1 else None


# ---------------------------------------------------------------- tiers

def tier_of(model: str, cfg: dict) -> Optional[int]:
    """The number of the one tier ``cfg['models']['tiers']`` maps to ``model``; None when none does; a model named by
    two tiers is a ValueError. Keys other than tier1-tier4 name no tier."""
    tiers = cfg["models"]["tiers"]
    hit = [t for t in TIER_NAMES if t in tiers and tiers[t] == model]
    if len(hit) > 1:
        raise ValueError("model '%s' is named by more than one tier (%s)" % (model, ", ".join(hit)))
    return int(hit[0][4]) if hit else None


def min_tier_of(role: str, cfg: dict) -> int:
    """``min_tier(role, cfg)`` for a framework role (the table value and the tier4 fallback); the number of ``min_tier``
    of a project role's entry (no fallback). ValueError for any other id or a malformed entry."""
    if type(role) is not str or type(cfg) is not dict:
        raise ValueError("min_tier_of takes a role id (str) and a config (dict)")
    if role in ROLES:
        return min_tier(role, cfg)
    entry = _roles_map(cfg).get(role)
    if type(entry) is not dict:
        raise ValueError("%s is no framework role and no project role" % safe_text(role))
    tier = entry.get("min_tier")
    if type(tier) is not str or tier not in TIER_NAMES:
        raise ValueError("roles.%s.min_tier must be one of %s" % (role, ", ".join(TIER_NAMES)))
    return int(tier[4])


def small_tier(role: str, cfg: dict) -> int:
    return int(cfg["reviews"]["small"]["tier"][4])


def min_tier(role: str, cfg: dict) -> int:
    """The lowest tier number ``role`` may run at under ``cfg`` (ValueError names the cause). A role whose minimum is
    tier4 runs at the tier ``top_tier_fallback`` names while ``tier4`` is unset, when it is one of ``top_tier_roles``."""
    need = MIN_TIERS[role]
    tiers = cfg["models"]["tiers"]
    if need < 4 or "tier4" in tiers:
        return need
    roles = cfg.get("top_tier_roles", DEFAULT_TOP_TIER_ROLES)
    if role not in roles:
        raise ValueError("%s needs tier4, which is unset, and is not in top_tier_roles" % role)
    fb = cfg.get("top_tier_fallback", DEFAULT_TOP_TIER_FALLBACK)
    if fb not in TIER_NAMES or fb not in tiers:       # a non-str is never equal to a tier name, so it is refused here
        raise ValueError("top_tier_fallback '%s' names a tier that is unset or not tier1-tier4" % (fb,))
    return int(fb[4])


# ---------------------------------------------------------------- small re-review

SMALL_PREFIX = "small-re-review: "
_KEYS = ("plan", "task", "round", "fix", "narrowed", "questions", "prev-fix-defects")
_WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
_SHA = r"[0-9a-f]{7,40}"
# round and every narrowed id are [1-9][0-9]*; the length cap (MAX_DIGITS: no int() of longer text) is applied in small_line.
_PATTERNS = {"plan": _WORD, "task": _WORD, "round": re.compile(r"[1-9][0-9]*"),
             "fix": re.compile("(%s)\\.\\.(%s)" % (_SHA, _SHA)),
             "narrowed": re.compile(r"none|[1-9][0-9]*(,[1-9][0-9]*)*"),
             "questions": re.compile(r"none"), "prev-fix-defects": re.compile(r"0")}


def small_line(brief: str) -> Optional[dict]:
    """The one ``small-re-review: `` line of a Brief, parsed; None when there is none; ValueError naming the key for a
    malformed line or for two lines."""
    lines = [ln for ln in brief.split("\n") if ln.startswith(SMALL_PREFIX)]
    if not lines:
        return None
    if len(lines) > 1:
        raise ValueError("small-re-review: more than one line")
    toks = lines[0][len(SMALL_PREFIX):].split(" ")
    out: dict = {}
    for i, key in enumerate(_KEYS):
        if i >= len(toks) or not toks[i].startswith(key + "="):
            raise ValueError("small-re-review: key %s is missing or out of order" % key)
        m = _PATTERNS[key].fullmatch(toks[i][len(key) + 1:])
        if m is None:
            raise ValueError("small-re-review: key %s is malformed" % key)
        val = toks[i][len(key) + 1:]
        if key in ("round", "narrowed") and any(len(n) > MAX_DIGITS for n in val.split(",")):
            raise ValueError("small-re-review: key %s is malformed" % key)
        if key == "round":
            out[key] = int(val)
        elif key == "fix":
            out[key] = (m.group(1), m.group(2))
        elif key == "narrowed":
            out[key] = [] if val == "none" else val.split(",")
        elif key == "prev-fix-defects":
            out[key] = 0
        else:
            out[key] = val
    if len(toks) > len(_KEYS):
        raise ValueError("small-re-review: text after prev-fix-defects (a repeated or unknown key)")
    return out


def _numstat(root: str, a: str, b: str) -> list:
    """``[(added, deleted, path)]`` for ``a..b`` (``-`` for a binary file), by the pinned git invocation."""
    p = gitinfo._run(root, "diff --numstat", ["diff", "--no-color", "--numstat", "-z", "--no-renames", "--no-ext-diff",
                                              "--no-textconv", a + ".." + b, "--"])
    out = []
    for raw in gitinfo._text(p.stdout, "diff --numstat").split("\0"):
        if raw:
            added, deleted, path = raw.split("\t", 2)
            out.append((added, deleted, path))
    return out


def small_errors(line: dict, findings_ids: list, root: str, cfg: dict) -> list:
    """Reasons the small re-review conditions 1-5 do not hold (module docstring: the narrow promise)."""
    small = cfg["reviews"]["small"]
    out = []
    if not 1 <= line["round"] <= 4:
        out.append("round %d: only rounds 1-4 may be small; round 5 always runs at the minimum tier" % line["round"])
    if line["questions"] != "none":
        out.append("questions is not none")
    if line["prev-fix-defects"] != 0:
        out.append("prev-fix-defects is not 0")
    a, b = line["fix"]
    try:
        if not gitinfo.is_ancestor(root, a, b):
            out.append("fix: %s is not an ancestor of %s" % (a, b))
        else:
            rows = _numstat(root, a, b)
            if len(rows) > small["max_files"]:
                out.append("fix changes %d files, more than reviews.small.max_files %d" % (len(rows), small["max_files"]))
            total = 0
            for added, deleted, path in rows:
                if added == "-" or deleted == "-":
                    out.append("fix changes the binary file %s" % path)
                else:
                    total += int(added) + int(deleted)
            if total > small["max_lines"]:
                out.append("fix changes %d lines, more than reviews.small.max_lines %d" % (total, small["max_lines"]))
            for _a, _d, path in rows:
                for glob in small["exclude"]:
                    if fnmatch.fnmatchcase(path, glob):
                        out.append("fix changes %s, which matches reviews.small.exclude %s" % (path, glob))
                        break
    except GateError as e:
        out.append("fix: %s" % e)
    out += _severity_errors(findings_ids, root, cfg)
    return out


def _severity_errors(findings_ids: list, root: str, cfg: dict) -> list:
    if not findings_ids:
        return ["## Findings names no finding id"]
    from gates.lib import store
    try:
        records = store.Store(root, "finding", cfg).load()
    except GateError as e:
        return ["findings: %s" % e]
    out = []
    for fid in findings_ids:
        rows = [r.row for r in records if r.id == fid]
        if not rows:
            out.append("finding %s names no finding record" % fid)
        elif any(row.get("severity") not in ("LOW", "MEDIUM") for row in rows):
            out.append("finding %s is not LOW or MEDIUM" % fid)
    return out


# ---------------------------------------------------------------- live programs (plan Task P4.3)

PROGRAM_PREFIX = "program: "
STREAM_PREFIX = "stream: "
_QUOTE_MAX = 60


def _quote(v: str, limit: int = _QUOTE_MAX) -> str:
    """``v`` as one line of printable ASCII (``safe_text`` escapes; a non-ASCII character is escaped by code point, so
    the bytes do not depend on the interpreter's Unicode database), cut to ``limit`` characters."""
    cut = v[:limit] + ("..." if len(v) > limit else "")
    return "'%s'" % safe_text(cut).encode("ascii", "backslashreplace").decode("ascii")


def required(root: str, cfg: dict) -> bool:
    """True when the profile is ``standard`` or ``strict``, or any program is live (spec section 12: wherever a program
    is live, ``gate_dispatch`` runs, whatever the profile). It never fails open (D-Q1): a profile that is not exactly
    ``light``, or a repository ``live_programs`` cannot read, returns True; only a ``cfg`` that is not a dict or a
    ``root`` that is not a string raises ``ValueError``."""
    if type(cfg) is not dict:
        raise ValueError("cfg must be a dict")
    if type(root) is not str:
        raise ValueError("root must be a string")
    profile = cfg.get("profile")
    if type(profile) is not str or profile != "light":
        return True
    from gates.lib import programs      # lazy: programs imports checkpoints, which imports this module
    try:
        return bool(programs.live_programs(root, cfg))
    except GateError:
        return True


def _lines_of(brief: str, prefix: str) -> list:
    return [ln[len(prefix):] for ln in brief.split("\n") if ln.startswith(prefix)]


def _one_line(lines: list, prefix: str, kind: str, problem) -> tuple:
    """``(value or None, reason or "")`` for the one ``prefix`` line of a Brief."""
    key = prefix.rstrip(": ")
    if not lines:
        return None, "## Brief holds no line '%s<%s>' (at the start of the line)" % (prefix, kind)
    if len(lines) > 1:
        return None, "## Brief holds %d '%s' lines, not one" % (len(lines), prefix)
    v = lines[0]
    why = problem(v)
    if why:
        return None, "the '%s' line is not a %s name: %s" % (key, kind, _quote(v))
    return v, ""


def program_errors(sections: dict, role: str, root: str, cfg: dict, program_live: bool) -> list:
    """``[(suffix, reason)]`` for the lines ``dispatch.program`` and ``dispatch.stream`` (plan Task P4.3): the caller's
    ``program_live`` against ``live_programs``; for a ``program_controller`` or ``stream_controller`` the one
    ``program: <p>`` line of ``## Brief`` naming a live program; for a ``stream_controller`` the one ``stream: <s>``
    line naming a stream of that program's ``streams.yml`` on its integration branch. A ``GateError`` of
    ``live_programs`` escapes (D-Q3); one of ``load_program`` becomes a ``stream`` pair; a ``stream`` pair
    ``stream not checked`` follows a failed program line (D-Q4)."""
    if type(program_live) is not bool:
        raise ValueError("program_live must be a bool")
    if type(sections) is not dict:
        raise ValueError("sections must be a dict")
    if type(role) is not str:
        raise ValueError("role must be a string")
    if type(cfg) is not dict:
        raise ValueError("cfg must be a dict")
    if type(root) is not str:
        raise ValueError("root must be a string")
    brief = sections.get("Brief", "")
    if type(brief) is not str:
        raise ValueError("sections['Brief'] must be a string")
    from gates.lib import programs      # lazy: programs imports checkpoints, which imports this module
    live = programs.live_programs(root, cfg)
    out = []
    if program_live != bool(live):
        out.append(("program", "program_live is %s in the input, but %s in git (%d live program(s))"
                    % ("true" if program_live else "false", "false" if program_live else "true", len(live))))
    if role not in ("program_controller", "stream_controller"):
        return out
    prog, why = _one_line(_lines_of(brief, PROGRAM_PREFIX), PROGRAM_PREFIX, "program", programs.program_problem)
    if prog is not None and prog not in live:
        why = "the program %s is not live (no integration branch holds its streams.yml)" % _quote(prog)
        prog = None
    if prog is None:
        out.append(("program", why))
    if role != "stream_controller":
        return out
    if prog is None:
        out.append(("stream", "stream not checked: the program line failed"))
        return out
    sid, why = _one_line(_lines_of(brief, STREAM_PREFIX), STREAM_PREFIX, "stream", programs.stream_problem)
    if sid is None:
        out.append(("stream", why))
        return out
    try:
        program = programs.load_program(root, cfg, prog, "refs/heads/%s/integration" % prog)
    except GateError as e:
        out.append(("stream", "the program files of %s cannot be read: %s" % (prog, _quote(str(e), 240))))
        return out
    if programs._stream_row(program.streams, sid) is None:
        out.append(("stream", "the stream %s is not a stream of %s's streams.yml" % (_quote(sid), prog)))
    return out
