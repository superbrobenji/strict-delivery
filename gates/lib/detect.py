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

_RULE = re.compile(r"^([A-Za-z0-9_.-]+(?:[ \t]+[A-Za-z0-9_.-]+)*)[ \t]*::?(?![:=])")
_DEFINE = re.compile(r"^(?:(?:override|export|private)[ \t]+)*define(?:[ \t]|$)")
_ENDEF = re.compile(r"^endef(?:[ \t]|$)")


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
        doc = json.loads(text, object_pairs_hook=_no_duplicates)
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


def _odd_backslashes(s: str) -> bool:
    """True if ``s`` ends in an odd number of backslashes (GNU make pairs them: ``\\\\`` is a literal)."""
    n = len(s) - len(s.rstrip("\\"))
    return n % 2 == 1


def _logical_lines(text: str) -> list:
    """(first physical line number, text) per logical line, split on ``\\n`` only.

    A CR before the newline is part of the line end. A line ending in a backslash is joined with
    the next: the backslash, the newline and the next line's leading blanks become one space; at
    the end of the file the backslash is dropped."""
    lines = [ln[:-1] if ln.endswith("\r") else ln for ln in text.split("\n")]
    out = []
    i = 0
    while i < len(lines):
        start = i + 1
        cur = lines[i]
        i += 1
        while _odd_backslashes(cur):
            if i < len(lines):
                cur = cur[:-1] + " " + lines[i].lstrip(" \t")
                i += 1
            else:
                cur = cur[:-1]
        out.append((start, cur))
    return out


def _rule_names(line: str) -> tuple:
    """The target names of a rule line, or ()."""
    if line.startswith("\t"):
        return ()
    if line.startswith(" "):
        line = line.lstrip(" \t")
    if line.startswith("#") or line.startswith("."):
        return ()
    m = _RULE.match(line)
    return tuple(m.group(1).split()) if m else ()


def _makefile_proposals(name: str, text: str) -> tuple:
    first = {}
    depth = 0
    for lineno, line in _logical_lines(text):
        body = line.lstrip(" \t")
        if depth:
            if _DEFINE.match(body):
                depth += 1
            elif _ENDEF.match(body):
                depth -= 1
            continue
        if not line.startswith("\t") and _DEFINE.match(body):
            depth = 1
            continue
        for target in _rule_names(line):
            first.setdefault(target, lineno)
    return tuple(Proposal(slot, "make " + slot, "%s:%d %s" % (name, first[slot], slot))
                 for slot in _PROPOSED if slot in first)


def _makefile(root: str, listing: list) -> tuple:
    """(proposals, problems) from the first Makefile name that exists, as GNU make reads it."""
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
        return _makefile_proposals(name, text), ()
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
    except OSError as e:
        raise GateError("%s: cannot read (%s)" % (root, e.strerror or type(e).__name__)) from None
    proposals = []
    problems = []
    for read in (lambda: _package_json(root), lambda: _makefile(root, listing)):
        found, bad = read()
        proposals.extend(found)
        problems.extend(bad)
    return Detection(tuple(proposals), tuple(problems))
