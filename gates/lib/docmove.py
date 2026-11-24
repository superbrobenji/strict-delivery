"""The superpowers document migration of ``init`` (Task 4d.2): plan the ``git mv`` moves, rewrite the references,
apply both. Standard library only.

``plan_moves`` and ``rewrites`` only read; ``apply_moves`` runs ``git mv`` (through ``gitinfo._run``) and writes the
changed texts, and never runs ``git add``, ``git commit`` or a rollback. Paths, boundaries and base names are compared
by code point (never ``lower``, ``isalnum`` or any other Unicode-table call), so the verdict is the same on every
interpreter. This file and its tests are the exempt sites of the old-path literal (spec section 4 requires it).
"""
from __future__ import annotations

import bisect
import errno
import os
import posixpath
import stat
from typing import List

from gates.lib import gitinfo, managed, print_table
from gates.lib.result import GateError

SOURCES = ("docs/superpowers/specs/", "docs/superpowers/plans/")
_OLD = "docs/superpowers"
_KEYS = ("specs", "plans")
_CLASS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._/-")
_PATH_MSG = "path: must be a relative path inside the root"
_STATE_MSG = "%s: a state record names a moved path (%s); resolve it by hand before the migration"


def _need_root(root: object) -> None:
    if type(root) is not str or root == "":
        raise GateError("root must be a string")


def _cfg_text(cfg: object, key: str) -> str:
    if type(cfg) is not dict or type(cfg.get("paths")) is not dict or key not in cfg["paths"]:
        raise GateError("cfg: paths.%s is missing" % key)
    value = cfg["paths"][key]
    if type(value) is not str or value == "":
        raise GateError("cfg: paths.%s must be a non-empty string" % key)
    if (not print_table.is_printable(value) or value.startswith("/") or ".." in value.split("/")
            or value == "." or posixpath.normpath(value) != value):
        raise GateError("cfg: paths.%s must be a normalised repo-relative path" % key)
    return value


def _pair_list(moves: object) -> list:
    if type(moves) is not list:
        raise GateError("moves: must be a list")
    seen_src: set = set()
    seen_dst: set = set()
    for i, item in enumerate(moves):
        if (type(item) is not tuple or len(item) != 2 or type(item[0]) is not str or type(item[1]) is not str
                or item[0] == "" or item[1] == ""):
            raise GateError("moves: item %d must be a (src, dst) pair of non-empty strings" % i)
        src, dst = item
        for p in item:
            if (p.startswith("/") or p.endswith("/") or "\n" in p or "\0" in p
                    or any(s in ("", ".", "..") for s in p.split("/"))):
                raise GateError("moves: item %d holds a path that is not a normalised repo-relative path" % i)
        if src == dst or src in seen_src or dst in seen_dst:
            raise GateError("moves: item %d repeats a path or moves a file onto itself" % i)
        seen_src.add(src)
        seen_dst.add(dst)
    return moves


def _listing(root: str, args: List[str]) -> bytes:
    return gitinfo._run(root, "ls-files", ["ls-files", "-z"] + args + ["--"] + list(SOURCES), literal=True).stdout


def plan_moves(root: str, cfg: dict) -> tuple:
    """``(moves, conflicts, notes)``: a move is ``(src, dst)`` for every tracked regular file under a source; a
    conflict is a text that makes ``init`` write nothing; a note is an untracked file left behind."""
    _need_root(root)
    targets = [_cfg_text(cfg, k) for k in _KEYS]
    tracked = gitinfo.tracked_files(root)
    top = gitinfo.toplevel(root)
    moves = []
    for src in sorted(tracked):
        for source, target in zip(SOURCES, targets):
            if src.startswith(source):
                moves.append((src, target + "/" + src[len(source):]))
    conflicts: list = []
    for mode, _, path in gitinfo._entries(_listing(top, ["--stage"]), "ls-files"):
        if mode == "120000":
            conflicts.append("%s: tracked symlink; not moved" % path)
        elif mode == "160000":
            conflicts.append("%s: tracked submodule; not moved" % path)
    for src, _ in moves:
        if not os.path.lexists(os.path.join(top, *src.split("/"))):
            conflicts.append("%s: tracked but missing; not moved" % src)
    overlap = False
    for key, target in zip(_KEYS, targets):
        for source in SOURCES:
            bare = source[:-1]
            if target == bare or target.startswith(source) or (bare + "/").startswith(target + "/"):
                conflicts.append("paths.%s: overlaps the superpowers source %s" % (key, source))
                overlap = True
    if targets[0] == targets[1]:
        conflicts.append("paths.specs: equals paths.plans")
    if not overlap:
        conflicts.extend(_target_conflicts(top, moves, tracked))
    notes = sorted("%s: untracked; not moved" % gitinfo._text(raw, "ls-files")
                   for raw in _listing(top, ["--others"]).split(b"\0") if raw)
    return moves, sorted(set(conflicts)), notes


def _target_conflicts(top: str, moves: list, tracked: frozenset) -> list:
    out: list = []
    dsts = [dst for _, dst in moves]
    for dst in dsts:
        try:
            managed._check_path(dst)
        except managed.ManagedError:
            out.append("%s: %s" % (dst, _PATH_MSG))
            continue
        try:
            state = managed._inspect(top, dst)
        except managed.ManagedError:  # a target that cannot be read (mode 000) still exists: a conflict, never opened
            if not os.path.lexists(os.path.join(top, *dst.split("/"))):
                raise
            out.append("%s: exists" % dst)
            continue
        if state[0] == "conflict" and (state[1].startswith("parent ") or state[1] == "is a symlink"):
            out.append("%s: %s" % (dst, state[1]))
        elif state[0] != "absent" or dst in tracked or os.path.lexists(os.path.join(top, *dst.split("/"))):
            out.append("%s: exists" % dst)
    ordered = sorted(dsts)
    for i, dst in enumerate(ordered):
        nxt = ordered[i + 1] if i + 1 < len(ordered) else None
        if nxt is not None and (nxt == dst or nxt.startswith(dst + "/")):
            out.append("%s: two moves name the same target" % dst)
    return out


# ---------------------------------------------------------------- rewrites

def _read_text(root: str, path: str) -> tuple:
    """``("text", str)``, ``("skip", note)`` or ``("absent",)`` for a tracked holder; every component is looked at with
    ``lstat`` and never followed, and only a regular file is opened (never a FIFO)."""
    parts = path.split("/")
    cur = root
    for i, part in enumerate(parts):
        cur = os.path.join(cur, part)
        try:
            st = os.lstat(cur)
        except (FileNotFoundError, NotADirectoryError):
            return ("absent",)
        except OSError as e:
            raise GateError("%s: cannot read (%s)" % (path, e.strerror)) from None
        last = i == len(parts) - 1
        if (not last and not stat.S_ISDIR(st.st_mode)) or (last and not stat.S_ISREG(st.st_mode)):
            return ("skip", "%s: not a regular file; not read" % path)
    try:
        fd = os.open(cur, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    except OSError as e:
        if e.errno == errno.ELOOP:
            return ("skip", "%s: not a regular file; not read" % path)
        raise GateError("%s: cannot read (%s)" % (path, e.strerror)) from None
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return ("skip", "%s: not a regular file; not read" % path)
        chunks = []
        while True:
            chunk = os.read(fd, 1 << 20)
            if not chunk:
                break
            chunks.append(chunk)
    except OSError as e:
        raise GateError("%s: cannot read (%s)" % (path, e.strerror)) from None
    finally:
        os.close(fd)
    data = b"".join(chunks)
    if b"\0" in data:
        return ("skip", "%s: not UTF-8 text; not rewritten" % path)
    try:
        return ("text", data.decode("utf-8"))
    except UnicodeDecodeError:
        return ("skip", "%s: not UTF-8 text; not rewritten" % path)


def _candidates(moves: list) -> dict:
    cands = {src: dst for src, dst in moves}
    for source in SOURCES:
        found = set()
        for src, dst in moves:
            if src.startswith(source):
                rest = src[len(source):]
                if dst.endswith(rest):
                    found.add(dst[:len(dst) - len(rest)])
        if len(found) > 1:
            raise GateError("moves: the moves under %s name more than one target directory" % source)
        if found:
            cands[source] = found.pop()
    return cands


def _occurrences(text: str, needle: str) -> list:
    out = []
    i = text.find(needle)
    while i != -1:
        out.append(i)
        i = text.find(needle, i + len(needle))
    return out


def _replace(text: str, cands: dict) -> tuple:
    """One left-to-right pass over the original text: ``(new_text, spans)`` where a span is ``(start, end, old)``.
    A candidate counts only when the characters before and after it (read in the original) are outside the class
    or are the text's ends; at one position the longest valid candidate wins."""
    hits = []
    for needle in cands:
        for i in _occurrences(text, needle):
            hits.append((i, -len(needle), needle))
    hits.sort()
    spans = []
    pos = 0
    n = len(text)
    for start, neg, needle in hits:
        end = start - neg
        if start < pos:
            continue
        if (start > 0 and text[start - 1] in _CLASS) or (end < n and text[end] in _CLASS):
            continue
        spans.append((start, end, needle))
        pos = end
    out = []
    last = 0
    for start, end, needle in spans:
        out.append(text[last:start])
        out.append(cands[needle])
        last = end
    out.append(text[last:])
    return "".join(out), spans


def rewrites(root: str, moves: list, state_dirs: list) -> tuple:
    """``(changes, notes, conflicts)``: a change is ``(path, new_text)`` (a moved file at its new path); a note is
    ``path:line: mentions <name>; not rewritten`` or a skip note; a conflict is a tracked state record that names a
    moved path (owner Q-CH10-1 (b)); with any conflict ``changes`` is ``[]``."""
    _need_root(root)
    _pair_list(moves)
    if type(state_dirs) is not list or any(type(d) is not str or d == "" for d in state_dirs):
        raise GateError("state_dirs: must be a list of non-empty strings")
    if not moves:
        return [], [], []
    tracked = gitinfo.tracked_files(root)
    top = gitinfo.toplevel(root)
    cands = _candidates(moves)
    dst_of = dict(moves)
    names = sorted({src.rsplit("/", 1)[-1] for src, _ in moves})
    changes: list = []
    notes: list = []
    conflicts: list = []
    for holder in sorted(tracked):
        got = _read_text(top, holder)
        shown = dst_of.get(holder, holder)
        if got[0] == "absent":
            continue
        if got[0] == "skip":
            notes.append((shown, 0, 0, got[1].replace(holder, shown, 1)))
            continue
        text = got[1]
        new, spans = _replace(text, cands)
        if spans and any(holder.startswith(d + "/") for d in state_dirs):
            conflicts.append(_STATE_MSG % (holder, spans[0][2]))
            continue
        if new != text:
            changes.append((shown, new))
        starts = [s[0] for s in spans]
        ends = [s[1] for s in spans]
        newlines = [i for i, c in enumerate(text) if c == "\n"] if "\n" in text else []
        for needle, label in [(n, n) for n in names] + [(_OLD, _OLD)]:
            for i in _occurrences(text, needle):
                k = bisect.bisect_right(starts, i) - 1
                if k >= 0 and i < ends[k]:
                    continue
                line = bisect.bisect_left(newlines, i) + 1
                col = i - (newlines[line - 2] + 1 if line > 1 else 0)
                notes.append((shown, line, col, "%s:%d: mentions %s; not rewritten" % (shown, line, label)))
    if conflicts:
        return [], [n[3] for n in sorted(notes)], sorted(conflicts)
    return sorted(changes), [n[3] for n in sorted(notes)], []


# ---------------------------------------------------------------- apply

def _changes_list(changes: object, moves: list) -> list:
    if type(changes) is not list:
        raise GateError("changes: must be a list")
    srcs = {src for src, _ in moves}
    seen: set = set()
    for i, item in enumerate(changes):
        if type(item) is not tuple or len(item) != 2 or type(item[0]) is not str or type(item[1]) is not str:
            raise GateError("changes: item %d must be a (path, text) pair of strings" % i)
        path, text = item
        if (path == "" or path.startswith("/") or "\0" in path or any(s in ("", ".", "..") for s in path.split("/"))):
            raise GateError("changes: item %d path must be a relative path inside the root" % i)
        if path in seen:
            raise GateError("changes: two changes name the same path (%s)" % path)
        if path in srcs:
            raise GateError("changes: %s is the source of a move; name its new path" % path)
        seen.add(path)
        try:
            text.encode("utf-8")
        except UnicodeEncodeError:
            raise GateError("%s: text is not encodable as UTF-8" % path) from None
    return changes


def _preflight(top: str, moves: list) -> None:
    for src, dst in moves:
        if os.path.lexists(os.path.join(top, *dst.split("/"))):
            raise GateError("%s: exists; nothing was moved" % dst)
        cur = top
        for part in dst.split("/")[:-1]:
            cur = os.path.join(cur, part)
            try:
                st = os.lstat(cur)
            except FileNotFoundError:
                break
            if not stat.S_ISDIR(st.st_mode):
                raise GateError("%s: parent %s is not a directory; nothing was moved" % (dst, cur[len(top) + 1:]))


def _still_regular(top: str, path: str) -> None:
    cur = top
    parts = path.split("/")
    for i, part in enumerate(parts):
        cur = os.path.join(cur, part)
        try:
            st = os.lstat(cur)
        except FileNotFoundError:
            raise GateError("%s: missing" % path) from None
        except OSError as e:
            raise GateError("%s: cannot read (%s)" % (path, e.strerror)) from None
        want = stat.S_ISREG if i == len(parts) - 1 else stat.S_ISDIR
        if not want(st.st_mode):
            raise GateError("%s: not a regular file" % path)


def apply_moves(root: str, moves: list, changes: list) -> None:
    """Create the target parents, run ``git mv -- src dst`` per move, then write the changes. A failure raises
    ``GateError`` naming it and the work done before it, which stays (no rollback, no ``git add``, no commit)."""
    _need_root(root)
    moves = _pair_list(moves)
    changes = _changes_list(changes, moves)
    if not moves and not changes:
        return None
    gitinfo._require_toplevel(root)
    top = gitinfo.toplevel(root)
    _preflight(top, moves)
    done: list = []
    for src, dst in moves:
        cur = top
        for part in dst.split("/")[:-1]:
            cur = os.path.join(cur, part)
            if not os.path.lexists(cur):
                os.mkdir(cur)
        p = gitinfo._run(top, "mv", ["mv", "--", src, dst], ok=None, literal=True)
        if p.returncode != 0:
            before = "; moved before it: " + ", ".join("%s -> %s" % m for m in done) if done else ""
            raise GateError("git mv failed (exit %d): %s -> %s%s" % (p.returncode, src, dst, before))
        done.append((src, dst))
    written: list = []
    for path, text in changes:
        before = "; written before it: " + ", ".join(written) if written else ""
        try:
            _still_regular(top, path)
            managed._write(top, path, text)
        except GateError as e:
            raise GateError("%s%s" % (e, before)) from None
        except OSError as e:
            raise GateError("%s: cannot write (%s)%s" % (path, e.strerror, before)) from None
        written.append(path)
    return None
