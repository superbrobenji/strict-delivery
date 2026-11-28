"""Pull-request body checks (Task L2.1, process learnings C3): the bytes of one file, their encoding, and the
placeholders left in them. Standard library only; no Unicode table is read (a body is judged byte by byte for the
encoding rules and by ASCII whole-token rules for the markers, so the verdict is the same on every interpreter).

``read_raw`` makes one ``os.open`` and judges the bytes read through that one descriptor: a later change of the file,
or of a symlinked parent directory, is not seen (a narrow promise, stated limit)."""
import errno
import os
import re
import stat

from gates.lib.result import GateError

MAX_BYTES = 1048576
MARKERS = ("TBD", "TODO")
SLOTS = ("{{", "}}")
_TOKEN_CHARS = frozenset("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz_-")
_CONTROL = re.compile(b"[\\x00-\\x08\\x0b\\x0c\\x0e-\\x1f\\x7f]")
_BOM = b"\xef\xbb\xbf"


def _exact(name: str, value: object, kind: type) -> None:
    if type(value) is not kind:
        raise TypeError("%s must be an exact %s, got %s" % (name, kind.__name__, type(value).__name__))


def _open_reason(e: BaseException) -> str:
    code = getattr(e, "errno", None)
    if code in (errno.ENOENT, errno.ENOTDIR):
        return "missing"
    if code == errno.ELOOP:
        return "a symlink"
    return "unreadable"


def read_raw(path: str) -> bytes:
    """The bytes of the regular file at ``path`` (at most ``MAX_BYTES``), read through one descriptor opened without
    following a symlink and without blocking; a ``GateError`` with exactly one reason otherwise."""
    _exact("path", path, str)
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    except (OSError, ValueError) as e:  # ValueError: a NUL in the path
        raise GateError(_open_reason(e)) from None
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise GateError("not a regular file")
        chunks, size = [], 0
        while size <= MAX_BYTES:
            chunk = os.read(fd, MAX_BYTES + 1 - size)
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
    except OSError:
        raise GateError("unreadable") from None
    finally:
        os.close(fd)
    if size > MAX_BYTES:
        raise GateError("over %d bytes" % MAX_BYTES)
    return b"".join(chunks)


def _line(raw: bytes, index: int) -> int:
    """The 1-based line of the byte at ``index``: the LF bytes before it, plus one; no ``int()`` runs on file text."""
    return raw.count(b"\n", 0, index) + 1


def text_problems(raw: bytes) -> list:
    """``[(check, reason)]`` with at most one entry, the first of: not UTF-8, a byte order mark, a CR, a control
    character (TAB and LF are allowed), no text (only spaces, TABs and LFs)."""
    _exact("raw", raw, bytes)
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError:
        return [("encoding", "not UTF-8")]
    if raw.startswith(_BOM):
        return [("encoding", "starts with a byte order mark")]
    cr = raw.find(b"\r")
    if cr >= 0:
        return [("line-ending", "CR at line %d" % _line(raw, cr))]
    ctl = _CONTROL.search(raw)
    if ctl is not None:
        return [("encoding", "control character U+%04X at line %d" % (raw[ctl.start()], _line(raw, ctl.start())))]
    if not raw.strip(b" \t\n"):
        return [("empty", "no text")]
    return []


def _bounded(text: str, start: int, token: str) -> bool:
    """Whether the ``token`` found at ``start`` is a whole token: both neighbours are outside ``[0-9A-Za-z_-]``."""
    before = text[start - 1] if start > 0 else ""
    after = text[start + len(token)] if start + len(token) < len(text) else ""
    return before not in _TOKEN_CHARS and after not in _TOKEN_CHARS


def placeholder_hits(text: str) -> list:
    """``[(line, token)]`` in file order: each ``{{`` and ``}}`` of a left-to-right scan that does not overlap, and each
    whole-token ``TBD`` or ``TODO`` (case-sensitive), anywhere (code spans and fences included: fail closed)."""
    _exact("text", text, str)
    found = []
    for slot in SLOTS:
        i = text.find(slot)
        while i >= 0:
            found.append((i, slot))
            i = text.find(slot, i + len(slot))
    for marker in MARKERS:
        i = text.find(marker)
        while i >= 0:
            if _bounded(text, i, marker):
                found.append((i, marker))
            i = text.find(marker, i + 1)
    found.sort()
    return [(text.count("\n", 0, i) + 1, token) for i, token in found]
