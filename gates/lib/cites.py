"""Cites in tracked docs (spec 9, 7.4): extraction, GitHub heading anchors and resolution, standard library only.

Pure functions. Lowercasing and the strip step of ``slugify`` read only the frozen tables ``case_table`` and
``slug_table``, so every Python 3.9+ gives one result. Lines are split on the line-feed character only.
"""
from __future__ import annotations

import bisect
import posixpath
import re
import weakref
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
    following: List[Optional[int]] = [None] * len(runs)     # index of the next run of the same length, one pass (F-V1)
    last: dict = {}
    for k in range(len(runs) - 1, -1, -1):
        following[k] = last.get(runs[k][1])
        last[runs[k][1]] = k
    spans = []
    i = 0
    while i < len(runs):
        j = following[i]
        if j is not None:
            spans.append((runs[i][0], runs[j][0] + runs[j][1], runs[i][1]))
            i = j
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


_BRACKET = re.compile(r"[\[\]]")
_BLANKS = re.compile(r"[ \t]*")
_BREAK = re.compile(r"[\x00- \x7f]")
_UNESCAPED = re.compile(r"(?<!\\)(?:\\\\)*([()\"'])")   # a ( ) " or ' after an even run of backslashes


def _openers(masked: str, closes: List[int]) -> List[Optional[int]]:
    """For each ``]`` index in closes (ascending): the ``[`` that balances it (brackets counted, escapes not decoded);
    failing that, the nearest ``[`` before it; None when there is no ``[`` before it. One pass over the brackets
    (F-V1): with level(i) the count of ``[`` minus the count of ``]`` in masked[:i], the balancing ``[`` is the last
    i before close with level(i) == level(close) - 1, the first place a backward bracket count reaches 0."""
    result: List[Optional[int]] = []
    last_at: dict = {}
    last_open = None
    level = 0
    q = 0
    for m in _BRACKET.finditer(masked):
        i = m.start()
        if q < len(closes) and closes[q] == i:
            j = last_at.get(level - 1)
            result.append(j if j is not None else last_open)
            q += 1
        last_at[level] = i
        if masked[i] == "[":
            level += 1
            last_open = i
        else:
            level -= 1
    return result


def _destinations(line: str, starts: List[int]) -> List[Optional[Tuple[int, int]]]:
    """For each start (ascending, the index just after a ``](``), parse ``destination [title] )`` from it:
    (begin, end) of the destination in line, or None. Per-line tables make each parse O(1) amortised (F-V1).

    A backslash keeps the next character out of the parenthesis depth of a bare destination and from closing a
    title. A destination or title never starts right after a backslash (it follows ``(``, a space, a tab or a
    quote), so whether a character there is escaped is a property of the line alone: it is escaped when the run of
    backslashes right before it is odd."""
    n = len(line)
    blank_end: dict = {}

    def skip(p: int) -> int:
        e = blank_end.get(p)
        if e is None:
            e = blank_end[p] = _BLANKS.match(line, p).end()
        return e

    closers: dict = {")": [], "\"": [], "'": []}
    parens: List[int] = []
    for m in _UNESCAPED.finditer(line):
        p = m.start(1)
        if line[p] != "(":
            closers[line[p]].append(p)
        if line[p] in "()":
            parens.append(p)
    breaks = [m.start() for m in _BREAK.finditer(line)]
    gts = [m.start() for m in re.finditer(">", line)]
    lts = [m.start() for m in re.finditer("<", line)]
    begins = [skip(p) for p in starts]
    # Bare destination: it runs to the first break character or to the first unescaped ")" at depth 0, that is the
    # first ")" at or after begin whose depth before it (count of "(" minus ")" before it) equals the depth at begin.
    depth_before = []
    depth = 0
    for p in parens:
        depth_before.append(depth)
        depth += 1 if line[p] == "(" else -1
    first_close: dict = {}
    drop: dict = {}
    order = sorted(range(len(begins)), key=lambda t: begins[t], reverse=True)
    k = len(parens)
    for t in order:
        b = begins[t]
        while k > 0 and parens[k - 1] >= b:
            k -= 1
            if line[parens[k]] == ")":
                first_close[depth_before[k]] = parens[k]
        drop[b] = first_close.get(depth_before[k] if k < len(parens) else depth)
    result: List[Optional[Tuple[int, int]]] = []
    for b in begins:
        result.append(None)
        if b < n and line[b] == "<":
            g = bisect.bisect_left(gts, b + 1)
            if g == len(gts):
                continue
            close = gts[g]
            j = bisect.bisect_left(lts, b + 1)
            if j < len(lts) and lts[j] < close:
                continue
            begin, end, pos = b + 1, close, close + 1
        else:
            j = bisect.bisect_left(breaks, b)
            stop = breaks[j] if j < len(breaks) else n
            d = drop[b]
            begin, end = b, d if d is not None and d < stop else stop
            pos = end
        after = skip(pos)
        if after < n and line[after] == ")":
            result[-1] = (begin, end)
            continue
        if after == pos or after >= n or line[after] not in "\"'(":
            continue
        listed = closers[")" if line[after] == "(" else line[after]]
        j = bisect.bisect_left(listed, after + 1)
        if j == len(listed):
            continue
        pos = skip(listed[j] + 1)
        if pos < n and line[pos] == ")":
            result[-1] = (begin, end)
    return result


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
        closes = [m.start() for m in re.finditer(r"\]\(", masked_line)]
        links = []
        for close, opener in zip(closes, _openers(masked_line, closes)):
            if opener is None or (opener > 0 and masked_line[opener - 1] == "!" and masked_line[opener - 2:opener - 1] != "\\"):
                continue
            links.append(close)
        hashes = [m.start() for m in re.finditer("#", line)] if links else []
        for close, parsed in zip(links, _destinations(line, [c + 2 for c in links])):
            if parsed is None:
                continue
            begin, end = parsed
            # No slice of line before the destination is known to be a cite: destinations of many links can overlap.
            h = bisect.bisect_left(hashes, begin)
            if h == len(hashes) or hashes[h] >= end or _SCHEME.match(line, begin, end):
                continue
            dest = line[begin:end]
            resolved = _resolve(doc, dest)
            if resolved is None:
                continue
            found.append((close, Cite(doc, number, dest, resolved[0], None, None, resolved[1])))
        found.sort(key=lambda t: t[0])
        cites.extend(c for _, c in found)
    return cites


def _strip_closing(content: str) -> str:
    """content without a closing sequence: the trailing run of ``#`` and the spaces or tabs before it, when that run
    has at least one space or tab before it (the regex ``[ \\t]+#+\\Z``, without its backtracking over the run)."""
    head = content.rstrip("#")
    if len(head) < len(content) and head[-1:] in (" ", "\t"):
        return head.rstrip(" \t")
    return content


def anchors(text: str) -> frozenset:
    """The heading anchors of the ATX headings outside fences, repeats numbered."""
    slugs = []
    for _, line, in_fence in _lines(text):
        if in_fence:
            continue
        m = _ATX.fullmatch(line)
        if not m:
            continue
        slugs.append(slugify(_strip_closing(m.group(2).strip(" \t"))))
    return frozenset(number_repeats(slugs))


def _line_count(text: str) -> int:
    return text.count("\n") + (1 if text and not text.endswith("\n") else 0)


def _not_utf8(text: str) -> bool:
    return re.search("[\udc80-\udcff]", text) is not None


_FACTS: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()


def _fact(read: Callable, text: str, compute: Callable[[str], object]) -> object:
    """compute(text), computed once per target text while the reader that returned it lives, so K cites to one
    target cost O(K + T), not O(K x T) (F-V1). A reader that cannot be weakly referenced gets no cache."""
    try:
        per_read = _FACTS.get(read)
        if per_read is None:
            per_read = _FACTS[read] = {}
    except TypeError:
        return compute(text)
    key = (compute, text)
    if key not in per_read:
        per_read[key] = compute(text)
    return per_read[key]


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
    if _fact(read, text, _not_utf8):
        return "%s: not UTF-8" % p
    if cite.anchor is not None:
        if not p.endswith(".md"):
            return "%s: anchor on a non-markdown file" % p
        if cite.anchor == "":
            return "%s: empty anchor" % p
        if cite.anchor not in _fact(read, text, anchors):
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
    count = _fact(read, text, _line_count)
    if cite.start > count:
        return "%s: line %s is past the end (%d lines)" % (p, start_text, count)
    if cite.end is not None and cite.end > count:
        return "%s: line %s is past the end (%d lines)" % (p, end_text, count)
    return ""
