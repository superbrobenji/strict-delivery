"""Stack command detection: the project's existing commands, offered as proposals (standard library only).

Detection invents nothing and only proposes (spec section 4). It reads only regular files
directly in ``root``, never runs a command, never writes and never needs git.
"""
from __future__ import annotations

import json
import os
import re
import stat
from dataclasses import dataclass
from typing import Optional

from gates.lib.result import GateError

SLOTS = ("test", "test_one", "lint", "build")

# Slots detection proposes: test_one is never proposed; init always asks for it.
_PROPOSED = ("test", "lint", "build")
_MAKEFILE_NAMES = ("GNUmakefile", "makefile", "Makefile")  # the order GNU make looks for them

# The Makefile reader is a whitelist (owner Q-C11rr-3); see _makefile_proposals.
_ASSIGNMENT = re.compile(r"^([A-Za-z_][A-Za-z0-9_.-]*)[ \t]*(?:=|:=|\?=|\+=)")
_FIRST_WORD = re.compile(r"[^:=?+!\s]*")
# Targets have no `/`, so no two spellings name one file (`test`, `./test`; owner Q-C11r4-0).
_RULE = re.compile(r"^((?:[A-Za-z0-9_.-]+[ \t]+)*[A-Za-z0-9_.-]+)[ \t]*(::?)")
# Owner Q-C11r4-0 (a), each refused wherever it appears in the file:
# a Unicode Cc character other than TAB (a CR is part of the line end only directly before LF);
_CONTROL = re.compile("[\x00-\x08\x0a-\x1f\x7f-\x9f]")
# a call to one of these make functions in `$(...)` or `${...}` form (also after `$$`: fail-closed);
_CALL = re.compile(r"\$[({](?:eval|error|shell|file|call|value|info|warning)(?![A-Za-z0-9_-])")
# an assignment to a variable make reads back as command-line switches.
_SWITCH_VARIABLES = frozenset(("MAKEFLAGS", "MFLAGS"))
# A line whose first word, or any target, is one of these is a directive line, not a rule or an assignment
# (controller ruling R2 under owner Q-C11rr-3). The first word ends at a blank, `:`, `=`, `?`, `+` or `!`.
_DIRECTIVES = frozenset(("export", "unexport", "override", "private", "vpath", "include", "-include", "sinclude",
                         "undefine", "define", "endef", "ifdef", "ifndef", "ifeq", "ifneq", "else", "endif"))

_R_BACKSLASH = "line ends in a backslash"
_R_RECIPE = "recipe line before the first rule"
_R_ASSIGNMENT = "assignment after the colon"
_R_SEMICOLON = "';' after the colon"
_R_COLON_BACKSLASH = "backslash after the colon"
_R_DIRECTIVE = "directive line"
_R_SECOND_COLON = "second ':' after the colon"
_R_MIXED_COLONS = "target defined with both ':' and '::'"
_R_OTHER = "not a blank, comment, assignment, rule or recipe line"
_R_CONTROL = "control character"
_R_CALL = "make function call"
_R_SWITCHES = "assignment to MAKEFLAGS or MFLAGS"


@dataclass(frozen=True)
class Proposal:
    slot: str
    command: str
    source: str


@dataclass(frozen=True)
class Problem:
    source: str
    reason: str


@dataclass(frozen=True)
class Detection:
    proposals: tuple
    problems: tuple


class _Unreadable(Exception):
    """A candidate source that cannot be read; the message is the Problem reason."""


def _read_regular(path: str) -> bytes:
    """The bytes of the regular file at ``path`` (already seen as one by lstat), or _Unreadable.

    Opened non-blocking and without following a symlink, then re-checked with fstat, so a path
    swapped to a FIFO or a symlink after the lstat cannot block the read or be followed. The
    descriptor is closed on every exit path."""
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0))
    except OSError as e:
        raise _Unreadable(e.strerror or type(e).__name__) from None
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise _Unreadable("not a regular file")
        chunks = []
        while True:
            chunk = os.read(fd, 1 << 16)
            if not chunk:
                return b"".join(chunks)
            chunks.append(chunk)
    except OSError as e:
        raise _Unreadable(e.strerror or type(e).__name__) from None
    finally:
        os.close(fd)


def _fetch(root: str, name: str) -> Optional[bytes]:
    """None when ``name`` is absent in ``root``; the file bytes when it is a regular file;
    _Unreadable for a symlink, another kind, or a read failure."""
    path = os.path.join(root, name)
    try:
        mode = os.lstat(path).st_mode
    except FileNotFoundError:
        return None
    except OSError as e:
        raise _Unreadable(e.strerror or type(e).__name__) from None
    if stat.S_ISLNK(mode):
        raise _Unreadable("symlink; not read")
    if not stat.S_ISREG(mode):
        raise _Unreadable("not a regular file")
    return _read_regular(path)


class _DuplicateKey(ValueError):
    pass


def _no_duplicates(pairs: list) -> dict:
    keys = [k for k, _ in pairs]
    if len(set(keys)) != len(keys):
        raise _DuplicateKey()
    return dict(pairs)


class _BadConstant(ValueError):
    pass


def _refuse_constant(_name: str) -> None:
    raise _BadConstant()


class _Number:
    """A JSON number. Never converted, so the verdict does not depend on the interpreter's integer limit."""


def _number(_text: str) -> _Number:
    return _Number()


def _package_json(root: str) -> tuple:
    """(proposals, problems) from package.json."""
    try:
        data = _fetch(root, "package.json")
    except _Unreadable as e:
        return (), (Problem("package.json", str(e)),)
    if data is None:
        return (), ()

    def bad(reason: str) -> tuple:
        return (), (Problem("package.json", reason),)

    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return bad("not valid UTF-8")
    try:
        doc = json.loads(text, object_pairs_hook=_no_duplicates, parse_constant=_refuse_constant,
                         parse_int=_number, parse_float=_number)
    except _DuplicateKey:
        return bad("duplicate key")
    except (ValueError, RecursionError):
        return bad("not valid JSON")
    if not isinstance(doc, dict):
        return bad("top level is not an object")
    scripts = doc.get("scripts", {})
    if not isinstance(scripts, dict):
        return bad("scripts is not an object")
    out = []
    for name in _PROPOSED:
        value = scripts.get(name)
        if isinstance(value, str) and value != "" and not value.isspace():
            out.append(Proposal(name, "npm run " + name, "package.json scripts." + name))
    return tuple(out), ()


def _makefile_proposals(name: str, text: str) -> tuple:
    """(proposals, problems) from a Makefile read as a whitelist (owner Q-C11rr-3).

    Each physical line must be one of: blank; a comment; a simple assignment; a rule with literal
    targets; a recipe line after a rule. The first other line gives no proposals and one Problem.
    A target named test, lint or build gives its slot, the first definition only."""
    first = {}
    colons = {}  # target -> ":" or "::", for the first rule line that named it
    in_recipe = False  # a rule line was read and no assignment since
    lines = text.split("\n")
    for lineno, raw in enumerate(lines, 1):
        # A CR is part of the line end only before a LF; the last piece has no LF after it.
        line = raw[:-1] if raw.endswith("\r") and lineno < len(lines) else raw

        def unsupported(reason: str) -> tuple:
            return (), (Problem(name, "unsupported line %d: %s" % (lineno, reason)),)

        if _CONTROL.search(line):
            return unsupported(_R_CONTROL)
        if line.endswith("\\"):
            return unsupported(_R_BACKSLASH)
        if _CALL.search(line):
            return unsupported(_R_CALL)
        if not line.strip(" \t"):
            continue
        if line.startswith("\t"):
            if not in_recipe:
                return unsupported(_R_RECIPE)
            continue
        body = line.lstrip(" \t")
        if body.startswith("#"):
            continue
        if _FIRST_WORD.match(body).group() in _DIRECTIVES:
            return unsupported(_R_DIRECTIVE)
        assignment = _ASSIGNMENT.match(body)
        if assignment:
            if assignment.group(1) in _SWITCH_VARIABLES:
                return unsupported(_R_SWITCHES)
            in_recipe = False
            continue
        m = _RULE.match(body)
        if not m:
            return unsupported(_R_OTHER)
        targets = m.group(1).split()
        if _DIRECTIVES.intersection(targets):
            return unsupported(_R_DIRECTIVE)
        after = body[m.end():].split("#", 1)[0]
        if "\\" in after:
            return unsupported(_R_COLON_BACKSLASH)
        if ";" in after:
            return unsupported(_R_SEMICOLON)
        if "=" in after:
            return unsupported(_R_ASSIGNMENT)
        if ":" in after:
            return unsupported(_R_SECOND_COLON)
        kind = m.group(2)
        if any(colons.setdefault(t, kind) != kind for t in targets):
            return unsupported(_R_MIXED_COLONS)
        in_recipe = True
        for target in targets:
            first.setdefault(target, lineno)
    return tuple(Proposal(slot, "make " + slot, "%s:%d %s" % (name, first[slot], slot))
                 for slot in _PROPOSED if slot in first), ()


def _makefile(root: str, listing: list) -> tuple:
    """(proposals, problems) from the first Makefile name that exists, as GNU make picks it."""
    for probe in _MAKEFILE_NAMES:
        try:
            os.lstat(os.path.join(root, probe))
        except FileNotFoundError:
            continue
        except OSError:
            pass  # exists but cannot be examined: _fetch reports it below under this name
        # On a case-insensitive filesystem the probe can match an entry spelled differently.
        exact = [e for e in listing if e == probe]
        folded = [e for e in listing if e.lower() == probe.lower()]
        name = exact[0] if exact else (folded[0] if folded else probe)
        try:
            data = _fetch(root, name)
        except _Unreadable as e:
            return (), (Problem(name, str(e)),)
        if data is None:  # vanished since the probe
            return (), (Problem(name, "No such file or directory"),)
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            return (), (Problem(name, "not valid UTF-8"),)
        return _makefile_proposals(name, text)
    return (), ()


def detect(root: str) -> Detection:
    """The commands ``root`` already has for test, lint and build, and the sources that could not be read.

    Order: source order (package.json, then the Makefile), then slot order within a source."""
    if type(root) is not str:
        raise GateError("root must be a str, not %s" % type(root).__name__)
    if not os.path.isdir(root):
        raise GateError("%s: not a directory" % root)
    try:
        listing = os.listdir(root)
        if not os.access(root, os.X_OK):  # readable but not searchable: no file inside can be examined
            raise PermissionError(13, os.strerror(13))
    except OSError as e:
        raise GateError("%s: cannot read (%s)" % (root, e.strerror or type(e).__name__)) from None
    proposals = []
    problems = []
    for read in (lambda: _package_json(root), lambda: _makefile(root, listing)):
        found, bad = read()
        proposals.extend(found)
        problems.extend(bad)
    return Detection(tuple(proposals), tuple(problems))
