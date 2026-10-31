"""Strict YAML subset: parser and canonical emitter (standard library only).

Accepted: block mappings and sequences, flow sequences of scalars, plain,
single- and double-quoted scalars, and the block scalars ``|`` and ``|-``.
Everything else (anchors, aliases, tags, merge keys, flow mappings, folded
scalars, document markers, duplicate keys, tab indentation) is refused with a
``YamlError`` carrying the 1-based line.
"""
from __future__ import annotations

import re

MAX_DEPTH = 50
MAX_INT_CHARS = 1000
_INT = re.compile(r"-?(0|[1-9][0-9]*)\Z")
_BAD_CHARS = re.compile("[\x00-\x08\x0b-\x1f\x7f\ud800-\udfff]")
_HEX = set("0123456789abcdefABCDEF")
_PLAIN_BAD_START = {
    "&": "anchors are not supported",
    "*": "aliases are not supported",
    "!": "tags are not supported",
    "{": "flow mappings are not supported",
    ">": "folded scalars are not supported",
}
_PLAIN_GENERIC_BAD = "%@`,]}"
_EMIT_QUOTE_FIRST = "&*!>{}[]%@`|'\"#,?:"
_RESERVED = ("true", "false", "null", "~", "<<", "---", "...")


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
    if c in _PLAIN_GENERIC_BAD or (c == "?" and (len(text) == 1 or text[1] == " ")):
        raise YamlError(lineno, f"plain scalar may not start with {c!r}")
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
    if rest.strip() == "":
        return
    if rest[0] in " \t" and rest.lstrip().startswith("#"):
        return
    raise YamlError(lineno, f"unexpected text after {what}")


def _cut_comment(text: str) -> str:
    """Cut a plain scalar at the first whitespace-preceded '#'."""
    for i, c in enumerate(text):
        if c == "#" and i > 0 and text[i - 1] in " \t":
            return text[:i]
    return text


def _plain(text: str, lineno: int, flow: bool = False) -> object:
    """Validate and resolve a plain scalar (comment already removed)."""
    text = text.strip()
    if not text:
        raise YamlError(lineno, "empty scalar")
    _check_start(text, lineno)
    if ": " in text or text.endswith(":"):
        raise YamlError(lineno, "':' followed by a space is not allowed in a plain scalar")
    if flow and any(c in "[{}" for c in text):
        raise YamlError(lineno, "nested flow collections are not supported")
    return _resolve(text, lineno)


def _flow(s: str, lineno: int) -> list:
    """Parse a flow sequence of scalars; s starts with '['."""
    i = 1
    n = len(s)
    out = []

    def skip(j):
        while j < n and s[j] in " \t":
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
            if s[i] in "\"'":
                v, i = _quoted(s, i, lineno)
            else:
                j = i
                while j < n and s[j] not in ",]":
                    j += 1
                if j >= n:
                    raise YamlError(lineno, "unterminated flow sequence")
                chunk = s[i:j]
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


def _is_item(content: str) -> bool:
    return content == "-" or content.startswith("- ")


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
            if raw.strip() == "" or raw.strip().startswith("#"):
                i += 1
                continue
            ind = len(raw) - len(raw.lstrip(" "))
            if raw[ind] == "\t":
                raise YamlError(i + 1, "tab in indentation")
            content = raw[ind:].rstrip()
            if ind == 0 and (content in ("---", "...") or content.startswith(("--- ", "... "))):
                raise YamlError(i + 1, "document markers are not supported")
            return i, i + 1, ind, content
        return None

    def detect_key(self, content: str, lineno: int):
        """Return (key, rest-after-colon) if content is 'key: ...', else None."""
        c = content[0]
        if c in "\"'":
            key, end = _quoted(content, 0, lineno)
            j = end
            while j < len(content) and content[j] in " \t":
                j += 1
            if j < len(content) and content[j] == ":" and (j + 1 == len(content) or content[j + 1] == " "):
                return key, content[j + 1:]
            return None
        if c == "[":
            return None
        if c == "|":
            return None
        _check_start(content, lineno)
        for j, ch in enumerate(content):
            if ch == "#" and j > 0 and content[j - 1] in " \t":
                return None
            if ch == ":" and (j + 1 == len(content) or content[j + 1] == " "):
                key = content[:j].rstrip()
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
            if _is_item(content):
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
        _, _, ind, content = p
        if ind > parent_indent:
            return self.block(ind, False)
        if seq_at_parent and ind == parent_indent and _is_item(content):
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
            if _is_item(content):
                raise YamlError(lineno, "unexpected sequence item in a mapping")
            kv = self.detect_key(content, lineno)
            if kv is None:
                raise YamlError(lineno, "expected 'key: value'")
            key, rest = kv
            if key in result:
                raise YamlError(lineno, f"duplicate key {key!r}")
            self.pos = idx + 1
            rest = rest.strip()
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
            if not _is_item(content):
                break
            after = content[1:]
            rest = after.lstrip(" ")
            col = indent + 1 + (len(after) - len(rest))
            if rest == "" or rest.startswith("#"):
                self.pos = idx + 1
                result.append(self.nested(indent, lineno, False))
            elif _is_item(rest) or self.detect_key(rest, lineno) is not None:
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
        m = re.match(r"\|(-?)(?:[ \t]+#.*)?[ \t]*\Z", header)
        if not m:
            raise YamlError(lineno, "unsupported block scalar header (only '|' and '|-')")
        strip = m.group(1) == "-"
        start = self.pos
        min_ind = max(parent_indent + 1, 1)
        ci = None
        end = start
        body = []
        while end < len(self.lines):
            raw = self.lines[end]
            if raw.strip() == "":
                if ci is not None and len(raw) > ci:
                    if "\t" in raw:
                        raise YamlError(end + 1, "tab in indentation")
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


def load(path: str, shown: str) -> object:
    """Read, decode and parse a file; every YamlError names ``shown``."""
    with open(path, "rb") as fh:
        data = fh.read()
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise YamlError(0, f"{shown}: not valid UTF-8") from None
    text = text.replace("\r\n", "\n")
    try:
        return parse(text)
    except YamlError as e:
        raise YamlError(e.line, f"{shown}: {e.reason}") from None


# ---------------------------------------------------------------- emitting

def _plain_ok(s: str) -> bool:
    """True if s written plain re-parses as the same str (conservative)."""
    if s == "" or s in _RESERVED or _INT.match(s):
        return False
    if not s.isprintable() or s != s.strip(" "):
        return False
    if s[0] in _EMIT_QUOTE_FIRST or s == "-" or s.startswith("- "):
        return False
    return ": " not in s and " #" not in s and not s.endswith(":") and not s.startswith(("--- ", "... "))


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


def _str_text(s: str) -> str:
    return s if _plain_ok(s) else _dq(s)


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


def _scalar_text(v: object) -> str:
    if v is None:
        return "null"
    if v is True:
        return "true"
    if v is False:
        return "false"
    if isinstance(v, int):
        try:
            text = str(v)
        except ValueError:
            raise EmitError("integer too large") from None
        if len(text) > MAX_INT_CHARS:
            raise EmitError("integer too large")
        return text
    if isinstance(v, str):
        _check_str(v)
        return _str_text(v)
    raise EmitError(f"cannot emit {type(v).__name__}")


def _value_lines(v: object, indent: int, depth: int):
    """Lines for a non-container or container value placed after 'key:' or '- '.

    Returns (inline_text or None, following_lines)."""
    if isinstance(v, dict):
        if not v:
            raise EmitError("empty mapping cannot be emitted")
        return None, _lines(v, indent, depth + 1)
    if isinstance(v, list):
        if not v:
            return "[]", []
        return None, _lines(v, indent, depth + 1)
    if isinstance(v, str):
        _check_str(v)
        bf = _block_form(v)
        if bf is not None:
            header, body = bf
            return header, [" " * indent + ln if ln else "" for ln in body]
    return _scalar_text(v), []


def _lines(v: object, indent: int, depth: int):
    """Lines for a container at the given indent."""
    if depth > MAX_DEPTH:
        raise EmitError("nesting too deep")
    pad = " " * indent
    out = []
    if isinstance(v, dict):
        for k, val in v.items():
            if not isinstance(k, str):
                raise EmitError("mapping keys must be str")
            _check_str(k)
            inline, rest = _value_lines(val, indent + 2, depth)
            out.append(pad + _str_text(k) + ":" + (" " + inline if inline is not None else ""))
            out.extend(rest)
        return out
    for item in v:
        inline, rest = _value_lines(item, indent + 2, depth)
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
        if isinstance(value, (dict, list)) and value:
            return "\n".join(_lines(value, 0, 1)) + "\n"
        inline, rest = _value_lines(value, 2, 1)
        if inline is None or rest:
            return "\n".join([inline] + rest) + "\n"
        return inline + "\n"
    except RecursionError:
        raise EmitError("nesting too deep") from None
