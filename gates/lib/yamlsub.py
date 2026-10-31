"""Strict YAML subset: parser and canonical emitter (standard library only).

Accepted: block mappings and sequences, flow sequences of scalars, plain,
single- and double-quoted scalars, and the block scalars ``|`` and ``|-``.
Everything else (anchors, aliases, tags, merge keys, flow mappings, folded
scalars, document markers, duplicate keys, tab indentation) is refused with a
``YamlError`` carrying the 1-based line.
"""
from __future__ import annotations

import os
import re
import stat

MAX_DEPTH = 50
MAX_INT_CHARS = 1000
_INT = re.compile(r"-?(0|[1-9][0-9]*)\Z")
_BAD_CHARS = re.compile("[\x00-\x08\x0b-\x1f\x7f\ud800-\udfff]")
_WS = " \t"  # YAML whitespace: space and tab only, never Unicode whitespace
_HEX = set("0123456789abcdefABCDEF")
_PLAIN_BAD_START = {
    "&": "anchors are not supported",
    "*": "aliases are not supported",
    "!": "tags are not supported",
    "{": "flow mappings are not supported",
    ">": "folded scalars are not supported",
}
_PLAIN_GENERIC_BAD = "%@`,]}"


class YamlError(Exception):
    """A document the strict subset refuses; ``line`` is 1-based (0 = whole file)."""

    def __init__(self, line: int, reason: str) -> None:
        super().__init__(f"line {line}: {reason}")
        self.line = line
        self.reason = reason


class EmitError(ValueError):
    """A value ``emit`` cannot write."""


# ---------------------------------------------------------------- parsing

def _check_start(text: str, lineno: int) -> None:
    """Refuse plain scalars/keys that start with an indicator character."""
    c = text[0]
    if c in _PLAIN_BAD_START:
        raise YamlError(lineno, _PLAIN_BAD_START[c])
    if c in _PLAIN_GENERIC_BAD or (c == "?" and (len(text) == 1 or text[1] in _WS)):
        raise YamlError(lineno, f"plain scalar may not start with {c!r}")
    if text.startswith("-\t"):
        raise YamlError(lineno, "tab used as a separator after '-'")
    if text == "-" or text.startswith("- "):
        raise YamlError(lineno, "plain scalar may not start with '- '")


def _resolve(text: str, lineno: int) -> object:
    """Resolve a plain scalar to bool, None, int or str."""
    if text == "true":
        return True
    if text == "false":
        return False
    if text in ("null", "~"):
        return None
    if _INT.match(text):
        if len(text) > MAX_INT_CHARS:
            raise YamlError(lineno, "integer too large")
        try:
            return int(text)
        except ValueError:
            raise YamlError(lineno, "integer too large") from None
    return text


def _quoted(s: str, pos: int, lineno: int) -> tuple:
    """Parse a quoted scalar starting at s[pos]; return (value, position after it)."""
    q = s[pos]
    i = pos + 1
    out = []
    while i < len(s):
        c = s[i]
        if q == "'":
            if c == "'":
                if s[i + 1:i + 2] == "'":
                    out.append("'")
                    i += 2
                    continue
                return "".join(out), i + 1
            out.append(c)
            i += 1
            continue
        if c == '"':
            return "".join(out), i + 1
        if c != "\\":
            out.append(c)
            i += 1
            continue
        e = s[i + 1:i + 2]
        if e in ("\\", '"'):
            out.append(e)
            i += 2
        elif e == "n":
            out.append("\n")
            i += 2
        elif e == "t":
            out.append("\t")
            i += 2
        elif e == "u":
            h = s[i + 2:i + 6]
            if len(h) != 4 or not set(h) <= _HEX:
                raise YamlError(lineno, "invalid \\u escape")
            n = int(h, 16)
            if 0xD800 <= n <= 0xDFFF:
                raise YamlError(lineno, "surrogate \\u escape is not supported")
            out.append(chr(n))
            i += 6
        else:
            raise YamlError(lineno, f"unsupported escape '\\{e}'")
    raise YamlError(lineno, "unterminated quoted scalar")


def _only_comment(rest: str, lineno: int, what: str) -> None:
    """Require that rest is blank or a comment preceded by whitespace."""
    if rest.strip(_WS) == "":
        return
    if rest[0] in _WS and rest.lstrip(_WS).startswith("#"):
        return
    raise YamlError(lineno, f"unexpected text after {what}")


def _cut_comment(text: str) -> str:
    """Cut a plain scalar at the first whitespace-preceded '#'."""
    for i, c in enumerate(text):
        if c == "#" and i > 0 and text[i - 1] in _WS:
            return text[:i]
    return text


def _plain(text: str, lineno: int, flow: bool = False) -> object:
    """Validate and resolve a plain scalar (comment already removed)."""
    text = text.strip(_WS)
    if not text:
        raise YamlError(lineno, "empty scalar")
    _check_start(text, lineno)
    if flow and text[0] in "#|":  # c-indicators: refused first in a flow item too (owner ruling D4)
        raise YamlError(lineno, f"plain scalar may not start with {text[0]!r}")
    if re.search(r":\t", text):
        raise YamlError(lineno, "tab used as a separator after ':'")
    if re.search(r":([ \t]|\Z)", text):
        raise YamlError(lineno, "':' followed by whitespace is not allowed in a plain scalar")
    if flow and any(c in "[{}" for c in text):
        raise YamlError(lineno, "nested flow collections are not supported")
    return _resolve(text, lineno)


def _flow(s: str, lineno: int) -> list:
    """Parse a flow sequence of scalars; s starts with '['."""
    i = 1
    n = len(s)
    out = []

    def skip(j):
        while j < n and s[j] in _WS:
            if s[j] == "\t":
                raise YamlError(lineno, "tab used as a separator in a flow sequence")
            j += 1
        return j

    i = skip(i)
    if i < n and s[i] == "]":
        i += 1
    else:
        while True:
            i = skip(i)
            if i >= n:
                raise YamlError(lineno, "unterminated flow sequence")
            if s[i] == "#" and s[i - 1] in _WS:  # ' #' starts a comment, which a flow line cannot hold
                raise YamlError(lineno, "comment inside a flow sequence")
            if s[i] in "\"'":
                v, i = _quoted(s, i, lineno)
            else:
                j = i
                while j < n and s[j] not in ",]":
                    j += 1
                if j >= n:
                    raise YamlError(lineno, "unterminated flow sequence")
                chunk = s[i:j]
                if chunk.endswith("\t"):
                    raise YamlError(lineno, "tab used as a separator in a flow sequence")
                if _cut_comment(chunk) != chunk:
                    raise YamlError(lineno, "comment inside a flow sequence")
                v = _plain(chunk, lineno, flow=True)
                i = j
            out.append(v)
            i = skip(i)
            if i >= n:
                raise YamlError(lineno, "unterminated flow sequence")
            if s[i] == ",":
                i += 1
                if skip(i) < n and s[skip(i)] == "]":
                    raise YamlError(lineno, "trailing comma in flow sequence")
                continue
            if s[i] == "]":
                i += 1
                break
            raise YamlError(lineno, "expected ',' or ']' in flow sequence")
    _only_comment(s[i:], lineno, "flow sequence")
    return out


def _is_item(content: str, lineno: int) -> bool:
    """True for a '- ' sequence item line; a tab after '-' is refused."""
    if content.startswith("-\t"):
        raise YamlError(lineno, "tab used as a separator after '-'")
    return content == "-" or content.startswith("- ")


def _colon_sep(content: str, j: int, lineno: int) -> bool:
    """True if the ':' at content[j] is a key separator; a tab after it is refused."""
    if j + 1 == len(content) or content[j + 1] == " ":
        return True
    if content[j + 1] == "\t":
        raise YamlError(lineno, "tab used as a separator after ':'")
    return False


class _Parser:
    def __init__(self, text: str) -> None:
        self.lines = text.split("\n")
        self.pos = 0
        self.over = {}
        self.depth = 0

    def peek(self):
        """Next significant line as (idx, lineno, indent, content), or None."""
        i = self.pos
        while i < len(self.lines):
            if i in self.over:
                ind, content = self.over[i]
                return i, i + 1, ind, content
            raw = self.lines[i]
            if raw.strip(_WS) == "" or raw.strip(_WS).startswith("#"):
                i += 1
                continue
            ind = len(raw) - len(raw.lstrip(" "))
            if raw[ind] == "\t":
                raise YamlError(i + 1, "tab in indentation")
            content = raw[ind:].rstrip(_WS)
            if ind == 0 and (content in ("---", "...") or content.startswith(("--- ", "... "))):
                raise YamlError(i + 1, "document markers are not supported")
            return i, i + 1, ind, content
        return None

    def trail(self, idx: int) -> str:
        """The whitespace peek stripped from the end of line idx."""
        raw = self.lines[idx]
        return raw[len(raw.rstrip(_WS)):]

    def detect_key(self, content: str, lineno: int):
        """Return (key, rest-after-colon) if content is 'key: ...', else None."""
        c = content[0]
        if c in "\"'":
            key, end = _quoted(content, 0, lineno)
            j = end
            while j < len(content) and content[j] in _WS:
                j += 1
            if j < len(content) and content[j] == ":" and _colon_sep(content, j, lineno):
                return key, content[j + 1:]
            return None
        if c == "[":
            return None
        if c == "|":
            return None
        _check_start(content, lineno)
        for j, ch in enumerate(content):
            if ch == "#" and j > 0 and content[j - 1] in _WS:
                return None
            if ch == ":" and _colon_sep(content, j, lineno):
                key = content[:j].rstrip(_WS)
                if key == "":
                    raise YamlError(lineno, "empty key")
                if key == "<<":
                    raise YamlError(lineno, "merge keys are not supported")
                return key, content[j + 1:]
        return None

    def block(self, indent: int, allow_scalar: bool):
        """Parse the node whose first line is at exactly this indent."""
        idx, lineno, ind, content = self.peek()
        self.depth += 1
        if self.depth > MAX_DEPTH:
            raise YamlError(lineno, "nesting too deep")
        try:
            if _is_item(content, lineno):
                return self.seq(indent)
            if self.detect_key(content, lineno) is not None:
                return self.mapping(indent)
            if not allow_scalar:
                raise YamlError(lineno, "expected a mapping or a sequence")
            self.pos = idx + 1
            return self.scalar(content, lineno, -1)
        finally:
            self.depth -= 1

    def nested(self, parent_indent: int, lineno: int, seq_at_parent: bool):
        """Value on following lines for an empty 'key:' or '-'."""
        p = self.peek()
        if p is None:
            return None
        _, plineno, ind, content = p
        if ind > parent_indent:
            return self.block(ind, False)
        if seq_at_parent and ind == parent_indent and _is_item(content, plineno):
            self.depth += 1
            try:
                if self.depth > MAX_DEPTH:
                    raise YamlError(p[1], "nesting too deep")
                return self.seq(parent_indent)
            finally:
                self.depth -= 1
        return None

    def mapping(self, indent: int):
        result = {}
        while True:
            p = self.peek()
            if p is None:
                break
            idx, lineno, ind, content = p
            if ind < indent:
                break
            if ind > indent:
                raise YamlError(lineno, "inconsistent indentation")
            if _is_item(content, lineno):
                raise YamlError(lineno, "unexpected sequence item in a mapping")
            kv = self.detect_key(content, lineno)
            if kv is None:
                raise YamlError(lineno, "expected 'key: value'")
            key, rest = kv
            if key in result:
                raise YamlError(lineno, f"duplicate key {key!r}")
            self.pos = idx + 1
            lead = rest[:len(rest) - len(rest.lstrip(_WS))]
            if rest == "":  # nothing follows ':' (content is rstripped): the stripped tail is after ':'
                lead = self.trail(idx)
            if "\t" in lead:  # owner rulings D5, U1: whatever follows
                raise YamlError(lineno, "tab in the whitespace after ':'")
            rest = rest.strip(_WS)
            if rest == "" or rest.startswith("#"):
                result[key] = self.nested(indent, lineno, True)
            else:
                result[key] = self.scalar(rest, lineno, indent)
        return result

    def seq(self, indent: int):
        result = []
        while True:
            p = self.peek()
            if p is None:
                break
            idx, lineno, ind, content = p
            if ind < indent:
                break
            if ind > indent:
                raise YamlError(lineno, "inconsistent indentation")
            if not _is_item(content, lineno):
                break
            after = content[1:]
            rest = after.lstrip(" ")
            if rest.startswith("\t") or (rest == "" and "\t" in self.trail(idx)):  # D5, U1
                raise YamlError(lineno, "tab used as a separator after '-'")
            col = indent + 1 + (len(after) - len(rest))
            if rest == "" or rest.startswith("#"):
                self.pos = idx + 1
                result.append(self.nested(indent, lineno, False))
            elif _is_item(rest, lineno) or self.detect_key(rest, lineno) is not None:
                self.over[idx] = (col, rest)
                self.pos = idx
                result.append(self.block(col, False))
            else:
                self.pos = idx + 1
                result.append(self.scalar(rest, lineno, indent))
        return result

    def scalar(self, text: str, lineno: int, parent_indent: int):
        """Parse a value that starts on the current line (text is non-empty)."""
        c = text[0]
        if c in "\"'":
            v, end = _quoted(text, 0, lineno)
            _only_comment(text[end:], lineno, "quoted scalar")
            return v
        if c == "[":
            if self.depth + 1 > MAX_DEPTH:
                raise YamlError(lineno, "nesting too deep")
            return _flow(text, lineno)
        if c == "|":
            return self.block_scalar(text, lineno, parent_indent)
        return _plain(_cut_comment(text), lineno)

    def block_scalar(self, header: str, lineno: int, parent_indent: int) -> str:
        # header is rstripped by every caller (peek, mapping, seq), so no trailing-whitespace branch
        m = re.match(r"\|(-?)(?:[ \t]+#.*)?\Z", header)
        if not m:
            raise YamlError(lineno, "unsupported block scalar header (only '|' and '|-')")
        strip = m.group(1) == "-"
        start = self.pos
        min_ind = max(parent_indent + 1, 1)
        ci = None
        end = start
        body = []
        lead = []  # (lineno, length) of blank lines before the first content line
        while end < len(self.lines):
            raw = self.lines[end]
            if raw.strip(_WS) == "":
                if "\t" in raw:
                    raise YamlError(end + 1, "tab in indentation")
                if ci is None:
                    lead.append((end + 1, len(raw)))
                    body.append("")
                elif len(raw) > ci:
                    body.append(raw[ci:])
                else:
                    body.append("")
                end += 1
                continue
            ind = len(raw) - len(raw.lstrip(" "))
            if ci is None:
                if ind < min_ind:
                    break
                ci = ind
                for ln, length in lead:
                    if length > ci:
                        raise YamlError(ln, "blank line indented deeper than the block scalar content")
            elif ind < ci:
                break
            if raw[ind] == "\t":
                raise YamlError(end + 1, "tab in indentation")
            body.append(raw[ci:])
            end += 1
        self.pos = end
        while body and body[-1] == "":
            body.pop()
        if not body:
            return ""
        return "\n".join(body) + ("" if strip else "\n")


def parse(text: str) -> object:
    """Parse a document; empty or comment-only input gives None."""
    m = _BAD_CHARS.search(text)
    if m:
        raise YamlError(text.count("\n", 0, m.start()) + 1, "control character not allowed")
    p = _Parser(text)
    first = p.peek()
    if first is None:
        return None
    value = p.block(first[2], True)
    rest = p.peek()
    if rest is not None:
        raise YamlError(rest[1], "unexpected content (inconsistent indentation or second node)")
    return value


def _file_text(data: bytes) -> str:
    """The text load() hands to parse: one leading BOM stripped, CRLF normalised."""
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    return data.decode("utf-8").replace("\r\n", "\n")


def _read_regular_file(path: object, shown: str) -> bytes:
    """The bytes of the regular file at ``path``; any problem is a YamlError naming ``shown``.

    Only ``str``, ``bytes`` and ``os.PathLike`` are paths: ``os.fspath`` refuses
    the rest, an ``int`` included (``open`` would read it as a descriptor), and
    any ``Exception`` from a PathLike's ``__fspath__`` is refused too
    (KeyboardInterrupt and SystemExit still escape).
    Anything but a regular file (directory, FIFO, device, socket) is refused
    before it is opened, and again on the descriptor opened non-blocking, so a
    path swapped to a FIFO between the two checks cannot block the read. The
    descriptor is closed on every exit path, refusals included.
    """
    def refuse(why: str) -> YamlError:
        return YamlError(0, f"{shown}: cannot read file ({why})")

    try:
        name = os.fspath(path)
    except Exception as e:  # not a path type, or a PathLike whose __fspath__ fails
        raise refuse(f"invalid path: {type(e).__name__}") from None
    try:
        if not stat.S_ISREG(os.stat(name).st_mode):
            raise refuse("not a regular file")
        fd = os.open(name, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0))
    except OSError as e:
        raise refuse(e.strerror or type(e).__name__) from None
    except ValueError as e:  # embedded NUL, unencodable name
        raise refuse(f"invalid path: {type(e).__name__}") from None
    try:
        try:  # fd is owned here and closed on every exit, before anything else can fail
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise refuse("not a regular file")
            chunks = []
            while True:
                chunk = os.read(fd, 1 << 16)
                if not chunk:
                    return b"".join(chunks)
                chunks.append(chunk)
        finally:
            os.close(fd)
    except OSError as e:
        raise refuse(e.strerror or type(e).__name__) from None


def load(path: str, shown: str) -> object:
    """Read, decode and parse a file; every YamlError names ``shown``."""
    data = _read_regular_file(path, shown)
    try:
        text = _file_text(data)
    except UnicodeDecodeError:
        raise YamlError(0, f"{shown}: not valid UTF-8") from None
    try:
        return parse(text)
    except YamlError as e:
        raise YamlError(e.line, f"{shown}: {e.reason}") from None


# ---------------------------------------------------------------- emitting

def _reparses(text: str, expected: object) -> bool:
    """True if text, written to a file and read back by load(), parses to expected."""
    try:
        return parse(_file_text(text.encode("utf-8"))) == expected
    except (YamlError, UnicodeError):
        return False


def _plain_ok(s: str, pos: str) -> bool:
    """True if s written plain at pos ('key@start', 'key@col0', 'key@in', 'value', 'item', 'top') comes back as the same str.

    The decision runs the real parser (through load's byte path) on the plain
    form, so it cannot drift from either."""
    if s == "" or "\n" in s:
        return False
    if pos == "key@start":  # first line of the file: a BOM strip applies
        return _reparses(s + ": v", {s: "v"})
    if pos == "key@col0":  # later line at column 0: document-marker lines apply
        o = "j" if s == "k" else "k"
        return _reparses(o + ": 1\n" + s + ": v", {o: 1, s: "v"})
    if pos == "key@in":  # indented or after '- ': neither applies
        return _reparses("- " + s + ": v", [{s: "v"}])
    if pos == "value":
        return _reparses("k: " + s, {"k": s})
    if pos == "item":
        return _reparses("- " + s, [s])
    return _reparses(s, s)


def _dq(s: str) -> str:
    out = ['"']
    for c in s:
        if c == "\\":
            out.append("\\\\")
        elif c == '"':
            out.append('\\"')
        elif c == "\n":
            out.append("\\n")
        elif c == "\t":
            out.append("\\t")
        elif ord(c) < 0x20 or ord(c) == 0x7F or (not c.isprintable() and ord(c) <= 0xFFFF):
            out.append("\\u%04x" % ord(c))
        else:
            out.append(c)
    out.append('"')
    return "".join(out)


def _str_text(s: str, pos: str) -> str:
    return s if _plain_ok(s, pos) else _dq(s)


def _block_form(s: str):
    """Return (header, lines) if s can be written as '|' or '|-', else None."""
    if "\n" not in s or not all(c == "\n" or c.isprintable() for c in s):
        return None
    if s.endswith("\n"):
        body, header = s[:-1], "|"
    else:
        body, header = s, "|-"
    if body.endswith("\n"):
        return None
    lines = body.split("\n")
    if lines[0] == "" or lines[0].startswith(" ") or any(ln != ln.rstrip(" ") for ln in lines):
        return None
    return header, lines


def _check_str(s: str) -> None:
    if any(0xD800 <= ord(c) <= 0xDFFF for c in s):
        raise EmitError("string contains a lone surrogate")


def _scalar_text(v: object, pos: str) -> str:
    if v is None:
        return "null"
    if v is True:
        return "true"
    if v is False:
        return "false"
    if type(v) is int:
        try:
            text = str(v)
        except ValueError:
            raise EmitError("integer too large") from None
        if len(text) > MAX_INT_CHARS:
            raise EmitError("integer too large")
        return text
    if type(v) is str:
        _check_str(v)
        return _str_text(v, pos)
    raise EmitError(f"cannot emit {type(v).__name__}")


def _value_lines(v: object, indent: int, depth: int, pos: str):
    """Lines for a non-container or container value placed after 'key:' or '- '.

    Returns (inline_text or None, following_lines)."""
    if type(v) is dict:
        if not v:
            raise EmitError("empty mapping cannot be emitted")
        return None, _lines(v, indent, depth + 1)
    if type(v) is list:
        if not v:
            if depth + 1 > MAX_DEPTH:  # the parser counts a flow '[]' as one level
                raise EmitError("nesting too deep")
            return "[]", []
        return None, _lines(v, indent, depth + 1)
    if type(v) is str:
        _check_str(v)
        bf = _block_form(v)
        if bf is not None:
            header, body = bf
            return header, [" " * indent + ln if ln else "" for ln in body]
    return _scalar_text(v, pos), []


def _lines(v: object, indent: int, depth: int):
    """Lines for a container at the given indent."""
    if depth > MAX_DEPTH:
        raise EmitError("nesting too deep")
    pad = " " * indent
    out = []
    if type(v) is dict:
        def kpos(n):
            if indent > 0:
                return "key@in"
            return "key@start" if n == 0 else "key@col0"

        for n, (k, val) in enumerate(v.items()):
            if type(k) is not str:
                raise EmitError("mapping keys must be str")
            _check_str(k)
            inline, rest = _value_lines(val, indent + 2, depth, "value")
            out.append(pad + _str_text(k, kpos(n)) + ":" + (" " + inline if inline is not None else ""))
            out.extend(rest)
        return out
    for item in v:
        inline, rest = _value_lines(item, indent + 2, depth, "item")
        if inline is not None:
            out.append(pad + "- " + inline)
            out.extend(rest)
        else:
            rest[0] = pad + "- " + rest[0][indent + 2:]
            out.extend(rest)
    return out


def emit(value: object) -> str:
    """Canonical text for value, ending in one newline."""
    try:
        if type(value) in (dict, list) and value:
            return "\n".join(_lines(value, 0, 1)) + "\n"
        inline, rest = _value_lines(value, 2, 0, "top")
        if inline is None or rest:
            return "\n".join([inline] + rest) + "\n"
        return inline + "\n"
    except RecursionError:
        raise EmitError("nesting too deep") from None
