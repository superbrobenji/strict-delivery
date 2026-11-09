"""Cites in tracked docs (spec 9, 7.4): extraction, GitHub heading anchors and resolution, standard library only.

Pure functions. Lowercasing and the strip step of ``slugify`` read only the frozen tables ``case_table`` and
``slug_table``, so every Python 3.9+ gives one result. Lines are split on the line-feed character only.
"""
from __future__ import annotations

import bisect
import posixpath
import re
from dataclasses import dataclass
from typing import Callable, Iterator, List, Optional, Tuple

from gates.lib.case_table import CASE_IGNORABLE_RANGES, CASED_RANGES, LOWER
from gates.lib.slug_table import STRIP_RANGES

_SIGMA = 0x3A3
_SMALL_SIGMA = chr(0x3C3)
_FINAL_SIGMA = chr(0x3C2)

_STRIP_STARTS = tuple(s for s, _ in STRIP_RANGES)
_CASED_STARTS = tuple(s for s, _ in CASED_RANGES)
_IGNORABLE_STARTS = tuple(s for s, _ in CASE_IGNORABLE_RANGES)
_STARTS = {id(STRIP_RANGES): _STRIP_STARTS, id(CASED_RANGES): _CASED_STARTS, id(CASE_IGNORABLE_RANGES): _IGNORABLE_STARTS}


def _in_ranges(cp: int, ranges: tuple) -> bool:
    """True when cp lies in one of the inclusive (start, end) ranges: the last range starting at or before cp."""
    i = bisect.bisect_right(_STARTS[id(ranges)], cp) - 1
    return i >= 0 and cp <= ranges[i][1]


def lowercase(text: str) -> str:
    """Unicode 13.0.0 default lowercase (full mapping, no locale), from case_table only; U+03A3 by Final_Sigma."""
    out = []
    for i, ch in enumerate(text):
        cp = ord(ch)
        if cp != _SIGMA:
            out.append(LOWER.get(cp, ch))
            continue
        j = i - 1
        while j >= 0 and _in_ranges(ord(text[j]), CASE_IGNORABLE_RANGES):
            j -= 1
        k = i + 1
        while k < len(text) and _in_ranges(ord(text[k]), CASE_IGNORABLE_RANGES):
            k += 1
        before = j >= 0 and _in_ranges(ord(text[j]), CASED_RANGES)
        after = k < len(text) and _in_ranges(ord(text[k]), CASED_RANGES)
        out.append(_FINAL_SIGMA if before and not after else _SMALL_SIGMA)
    return "".join(out)


def slugify(heading: str) -> str:
    """github-slugger 2.0.0 ``slug(value)``: lowercase, delete the strip table's code points, spaces to ``-``."""
    out = []
    for ch in lowercase(heading):
        if _in_ranges(ord(ch), STRIP_RANGES):
            continue
        out.append("-" if ch == " " else ch)
    return "".join(out)


def number_repeats(slugs: list) -> list:
    """Number repeated slugs as BananaSlug.slug does: ``s``, ``s-1``, ``s-2``, skipping slugs already taken."""
    occurrences: dict = {}
    result = []
    for s in slugs:
        r = s
        while r in occurrences:
            occurrences[s] += 1
            r = s + "-" + str(occurrences[s])
        occurrences[r] = 0
        result.append(r)
    return result


@dataclass(frozen=True)
class Cite:
    doc: str
    line: int
    token: str
    path: str
    start: Optional[int]
    end: Optional[int]
    anchor: Optional[str]


_FENCE = re.compile(r"( {0,3})(`{3,}|~{3,})(.*)")
_BACKTICK_CITE = re.compile(r"(?P<path>[^\s:#<>`]+?)(?::(?P<start>[0-9]+)(?:-(?P<end>[0-9]+))?|#(?P<anchor>[^\s#]*))")
_HEX = re.compile(r"[0-9a-f]{7,40}")
_SCHEME = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*:")
_PERCENT = re.compile(r"%([0-9A-Fa-f]{2})")
_ATX = re.compile(r"(#{1,6}) (.*)")
_CLOSING = re.compile(r"[ \t]+#+\Z")


def _lines(text: str) -> Iterator[Tuple[int, str, bool]]:
    """(1-based number, line, in_fence) for each line. Lines split on LF only; one trailing CR is dropped."""
    fence = None
    for number, raw in enumerate(text.split("\n"), 1):
        line = raw[:-1] if raw.endswith("\r") else raw
        m = _FENCE.fullmatch(line)
        if fence is None:
            if m and not (m.group(2)[0] == "`" and "`" in m.group(3)):
                fence = (m.group(2)[0], len(m.group(2)))
                yield number, line, True
            else:
                yield number, line, False
        else:
            yield number, line, True
            if m and m.group(2)[0] == fence[0] and len(m.group(2)) >= fence[1]:
                fence = None


def _spans(line: str) -> List[Tuple[int, int, int]]:
    """Code spans as CommonMark finds them within the line: (start of opener, end of closer, run length)."""
    runs = [(m.start(), m.end() - m.start()) for m in re.finditer(r"`+", line)]
    spans = []
    i = 0
    while i < len(runs):
        for j in range(i + 1, len(runs)):
            if runs[j][1] == runs[i][1]:
                spans.append((runs[i][0], runs[j][0] + runs[j][1], runs[i][1]))
                i = j
                break
        i += 1
    return spans


def _decode_percent(part: str) -> str:
    """Decode %XX as UTF-8 bytes; a malformed escape or bytes that are not UTF-8 leave the part as written."""
    if "%" not in part:
        return part
    if re.search(r"%(?![0-9A-Fa-f]{2})", part):
        return part
    pieces = []
    last = 0
    for m in _PERCENT.finditer(part):
        pieces.append(part[last:m.start()].encode("utf-8", "surrogatepass"))
        pieces.append(bytes([int(m.group(1), 16)]))
        last = m.end()
    pieces.append(part[last:].encode("utf-8", "surrogatepass"))
    try:
        return b"".join(pieces).decode("utf-8")
    except UnicodeDecodeError:
        return part


def _destination(line: str, pos: int) -> Optional[Tuple[str, int]]:
    """Parse ``destination [title] )`` from pos (just after ``](``): (destination, index after ``)``) or None."""
    n = len(line)
    while pos < n and line[pos] in " \t":
        pos += 1
    if pos < n and line[pos] == "<":
        close = line.find(">", pos + 1)
        if close < 0:
            return None
        dest = line[pos + 1:close]
        if "<" in dest:
            return None
        pos = close + 1
    else:
        depth = 0
        begin = pos
        while pos < n:
            c = line[pos]
            if c <= " " or c == "\x7f":
                break
            if c == "\\" and pos + 1 < n and line[pos + 1] > " " and line[pos + 1] != "\x7f":
                pos += 2                            # a backslash is literal; it keeps the next character out of the depth count
                continue
            if c == "(":
                depth += 1
            elif c == ")":
                if depth == 0:
                    break
                depth -= 1
            pos += 1
        dest = line[begin:pos]
    gap = pos
    while pos < n and line[pos] in " \t":
        pos += 1
    gap = pos - gap
    if pos < n and line[pos] == ")":
        return dest, pos + 1
    if gap == 0 or pos >= n or line[pos] not in "\"'(":
        return None
    closer = ")" if line[pos] == "(" else line[pos]
    end = pos + 1
    while end < n and line[end] != closer:
        end += 2 if line[end] == "\\" else 1       # a backslash is literal; it keeps the next character from closing
    if end >= n:
        return None
    pos = end + 1
    while pos < n and line[pos] in " \t":
        pos += 1
    if pos < n and line[pos] == ")":
        return dest, pos + 1
    return None


def _link_opener(masked: str, close: int) -> Optional[int]:
    """Index of the ``[`` that balances the ``]`` at close (brackets counted, escapes not decoded); failing that,
    the nearest ``[`` before it. None when there is no ``[``."""
    depth = 1
    for i in range(close - 1, -1, -1):
        if masked[i] == "]":
            depth += 1
        elif masked[i] == "[":
            depth -= 1
            if depth == 0:
                return i
    return masked.rfind("[", 0, close) if "[" in masked[:close] else None


def _resolve(doc: str, dest: str) -> Optional[Tuple[str, str]]:
    """(path, anchor) of a link destination, or None when it is not a cite."""
    if "#" not in dest or _SCHEME.match(dest):
        return None
    part, anchor = dest.split("#", 1)
    if part == "":
        return doc, anchor
    part = _decode_percent(part)
    base = posixpath.dirname(doc)    # posixpath.join keeps a path that starts with "/" as it is
    return posixpath.normpath(posixpath.join(base, part) if base else part), anchor


_SHORT_DIGITS = 640


def _number(digits: str) -> int:
    """The value of a decimal digit run of any length. int() is called only on runs of at most 640 digits, the lowest
    int string-conversion limit CPython 3.11+ accepts, so no length and no PYTHONINTMAXSTRDIGITS setting raises."""
    if len(digits) <= _SHORT_DIGITS:
        return int(digits)
    low = len(digits) // 2
    return _number(digits[:-low]) * 10 ** low + _number(digits[-low:])


def extract(doc: str, text: str) -> list:
    """Every cite in text outside fenced code, in source order (line, then column)."""
    cites: List[Cite] = []
    for number, line, in_fence in _lines(text):
        if in_fence:
            continue
        spans = _spans(line)
        found = []
        masked = list(line)
        for s, e, run in spans:
            for k in range(s, e):
                masked[k] = " "
            content = line[s + run:e - run]
            if run != 1:
                continue
            m = _BACKTICK_CITE.fullmatch(content)
            if not m:
                continue
            path = m.group("path")
            if not ("/" in path or "." in path) or "://" in path or _HEX.fullmatch(path):
                continue
            tok = line[s:e]
            if m.group("anchor") is not None:
                c = Cite(doc, number, tok, path, None, None, m.group("anchor"))
            else:
                end = m.group("end")
                c = Cite(doc, number, tok, path, _number(m.group("start")), None if end is None else _number(end), None)
            found.append((s, c))
        masked_line = "".join(masked)
        for m in re.finditer(r"\]\(", masked_line):
            opener = _link_opener(masked_line, m.start())
            if opener is None or (opener > 0 and masked_line[opener - 1] == "!" and masked_line[opener - 2:opener - 1] != "\\"):
                continue
            parsed = _destination(line, m.end())
            if parsed is None:
                continue
            dest = parsed[0]
            resolved = _resolve(doc, dest)
            if resolved is None:
                continue
            found.append((m.start(),Cite(doc, number, dest, resolved[0], None, None, resolved[1])))
        found.sort(key=lambda t: t[0])
        cites.extend(c for _, c in found)
    return cites


def anchors(text: str) -> frozenset:
    """The heading anchors of the ATX headings outside fences, repeats numbered."""
    slugs = []
    for _, line, in_fence in _lines(text):
        if in_fence:
            continue
        m = _ATX.fullmatch(line)
        if not m:
            continue
        content = _CLOSING.sub("", m.group(2).strip(" \t"))
        slugs.append(slugify(content))
    return frozenset(number_repeats(slugs))


def _line_count(text: str) -> int:
    return text.count("\n") + (1 if text and not text.endswith("\n") else 0)


def _outside(path: str) -> bool:
    if path.startswith("/"):
        return True
    norm = posixpath.normpath(path)
    return norm == ".." or norm.startswith("../")


def problem(cite: Cite, tracked: frozenset, read: Callable[[str], Optional[str]]) -> str:
    """"" when the cite resolves, else the reason (the caller's read decodes with errors="surrogateescape")."""
    p = cite.path
    if _outside(p):
        return "%s: outside the repository" % p
    if p not in tracked:
        return "%s: not a tracked file" % p
    text = read(p)
    if text is None:
        return "%s: tracked but missing from the working tree" % p
    if re.search("[\udc80-\udcff]", text):
        return "%s: not UTF-8" % p
    if cite.anchor is not None:
        if not p.endswith(".md"):
            return "%s: anchor on a non-markdown file" % p
        if cite.anchor == "":
            return "%s: empty anchor" % p
        if cite.anchor not in anchors(text):
            return "%s: no heading with anchor #%s" % (p, cite.anchor)
        return ""
    m = _BACKTICK_CITE.fullmatch(cite.token[1:-1])
    texts = [m.group("start")] + ([m.group("end")] if m.group("end") is not None else []) if m else []
    if any(t.startswith("0") for t in texts):
        return "%s: line numbers start at 1 and have no leading zero" % p
    # Print the token's own digits (no leading zero here, so equal to str(int)); %d of a number over 4300 digits
    # raises on CPython 3.11+.
    start_text, end_text = (texts + [None])[:2] if texts else ("%d" % cite.start, None if cite.end is None else "%d" % cite.end)
    if cite.end is not None and cite.end < cite.start:
        return "%s: range end %s is before start %s" % (p, end_text, start_text)
    count = _line_count(text)
    if cite.start > count:
        return "%s: line %s is past the end (%d lines)" % (p, start_text, count)
    if cite.end is not None and cite.end > count:
        return "%s: line %s is past the end (%d lines)" % (p, end_text, count)
    return ""
