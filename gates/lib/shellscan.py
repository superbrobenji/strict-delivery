"""Shell scanner for the Bash hook (standard library only).

``scan(text)`` says whether ``text`` is exactly one simple shell command whose words bash would pass to the program
unchanged (``Scan.plain``), and if so which words (``argv``), leading ``NAME=value`` assignments and, for the one
allowed compound form ``cd <dir> && <simple command>``, which directory. Everything else is not plain, and
``reason`` names the first construct (by text position) that made it so. The scanner is fail-closed: a construct
bash would expand (glob, brace, tilde, ``$``) is not plain, so ``argv`` is always what bash would run.
``token_in(text, word, casefold)`` finds ``word`` as a whole token (``[0-9A-Za-z_-]`` on neither side).

Only explicit ASCII character sets are used (no ``str.isspace``, ``isalnum``, ``lower``, ``casefold``), so the
verdicts do not depend on the interpreter's Unicode database; numbers are text and never converted.
"""
from __future__ import annotations

import dataclasses
import re
from typing import Optional

_NAME_START = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz_")
_NAME_REST = _NAME_START | frozenset("0123456789")
_TOKEN_CLASS = _NAME_REST | frozenset("-")
_OPS = frozenset(("&&", "||", ";;", "|&", "&>", "<<", "<>", "<&", ">>", ">&", ">|", "&>>", "<<<", "<<-", ";", "|", "&",
                  "<", ">", "(", ")"))
_OP_REASON = {";": "operator ;", ";;": "operator ;", "&&": "operator &&", "||": "operator ||", "|": "operator |",
              "|&": "operator |", "&": "operator &", "(": "grouping", ")": "grouping", "\n": "operator newline"}
_UNBALANCED = "unbalanced quote"
_RUN = re.compile("[^ \t\n\\\\'\"|&;<>()$`]+")  # a run of ordinary word characters
_SIMPLE = re.compile("[0-9A-Za-z_]+\\Z")  # a word with nothing special in it
_WHOLE = re.compile("[0-9A-Za-z_]+(?![^ \t\n])")  # a plain word that ends at whitespace or the end
_LOWER = {c: c + 32 for c in range(65, 91)}  # A-Z to a-z only: lengths and boundaries never shift


@dataclasses.dataclass(frozen=True)
class Scan:
    plain: bool
    cd: Optional[str]
    assignments: tuple
    argv: tuple
    reason: str
    words: tuple


def _flat(chars):
    return "".join(c[0] for c in chars)


def _chars(tok):
    """The ``(char, quoted, pos)`` list of a word token (built on demand for the plain-word fast path)."""
    if tok[1] is None:
        return [(ch, False, tok[2] + k) for k, ch in enumerate(tok[3])]
    return tok[1]


def _unquoted(tok):
    return tok[1] is None or not any(c[1] for c in tok[1])


def _tokenize(text):
    """Split ``text`` into ``("w", chars, pos, text)`` words (chars are ``(char, quoted, pos)``) and ``("op", op, pos)``
    operators. Also returns ``(pos, reason)`` constructs found on the way."""
    n = len(text)
    end = len(text.rstrip("\n"))
    toks = []
    found = []
    state = {"cur": [], "open": False, "pos": 0}

    def flush():
        if state["open"]:
            toks.append(("w", state["cur"], state["pos"], "".join([c[0] for c in state["cur"]])))
            state["cur"] = []
            state["open"] = False

    def begin(i):
        if not state["open"]:
            state["open"] = True
            state["pos"] = i

    nul = text.find("\x00")
    if nul >= 0:
        found.append((nul, "nul character"))
    i = 0
    while i < n:
        c = text[i]
        if c == " " or c == "\t":
            flush()
            i += 1
        elif c == "\n":
            flush()
            if i >= end:
                break
            toks.append(("op", "\n", i))
            i += 1
        elif c == "\\":
            if i + 1 >= n:
                found.append((i, _UNBALANCED))
                i += 1
            elif text[i + 1] == "\n":
                i += 2
            else:
                begin(i)
                state["cur"].append((text[i + 1], True, i + 1))
                i += 2
        elif c == "'":
            begin(i)
            j = text.find("'", i + 1)
            stop = n if j < 0 else j
            if j < 0:
                found.append((i, _UNBALANCED))
            for k in range(i + 1, stop):
                state["cur"].append((text[k], True, k))
            i = n if j < 0 else j + 1
        elif c == '"':
            begin(i)
            j = i + 1
            while j < n and text[j] != '"':
                ch = text[j]
                if ch == "\\" and j + 1 < n and text[j + 1] in '"\\$`\n':
                    if text[j + 1] != "\n":
                        state["cur"].append((text[j + 1], True, j + 1))
                    j += 2
                    continue
                if ch == "$":
                    found.append((j, "substitution" if text[j + 1:j + 2] == "(" else "expansion"))
                elif ch == "`":
                    found.append((j, "substitution"))
                state["cur"].append((ch, True, j))
                j += 1
            if j >= n:
                found.append((i, _UNBALANCED))
                i = n
            else:
                i = j + 1
        elif c == "|" or c == "&" or c == ";" or c == "<" or c == ">" or c == "(" or c == ")":
            flush()
            for size in (3, 2, 1):
                op = text[i:i + size]
                if op in _OPS:
                    break
            if (op == "<" or op == ">") and text[i + 1:i + 2] == "(":
                found.append((i, "substitution"))
            toks.append(("op", op, i))
            i += len(op)
        else:
            whole = None if state["open"] else _WHOLE.match(text, i)
            if whole is not None:
                toks.append(("w", None, i, whole.group()))
                i = whole.end()
                continue
            begin(i)
            if c == "$":
                nxt = text[i + 1:i + 2]
                found.append((i, "substitution" if nxt == "(" else "expansion"))
                state["cur"].append((c, False, i))
                i += 1
            elif c == "`":
                found.append((i, "substitution"))
                state["cur"].append((c, False, i))
                i += 1
            else:
                stop = _RUN.match(text, i).end()
                state["cur"].extend([(text[k], False, k) for k in range(i, stop)])
                i = stop
    flush()
    return toks, found


def _assign_head(chars):
    """``(name, plus, value_start)`` when the word starts with an unquoted ``NAME=`` or ``NAME+=``, else None."""
    if not chars or chars[0][1] or chars[0][0] not in _NAME_START:
        return None
    k = 1
    while k < len(chars) and not chars[k][1] and chars[k][0] in _NAME_REST:
        k += 1
    name = _flat(chars[:k])
    plus = k < len(chars) and not chars[k][1] and chars[k][0] == "+"
    if plus:
        k += 1
    if k < len(chars) and not chars[k][1] and chars[k][0] == "=":
        return name, plus, k + 1
    return None


def _brace_pos(chars):
    """Position of an unquoted ``{`` that has an unquoted ``,`` or ``..`` and then an unquoted ``}``, else -1."""
    opened = -1
    sep = False
    dot = False
    for ch, quoted, pos in chars:
        if quoted:
            dot = False
            continue
        if ch == "{":
            if opened < 0:
                opened = pos
        elif ch == "}":
            if opened >= 0 and sep:
                return opened
        elif opened >= 0 and ch == ",":
            sep = True
        if ch == ".":
            if dot and opened >= 0:
                sep = True
            dot = True
        else:
            dot = False
    return -1


def _word_reason(chars, pos, flat):
    """``(pos, reason)`` when the word is itself a reserved word, a group brace, a comment or bash would expand it."""
    if not chars:
        return None
    if _SIMPLE.match(flat):
        return None
    unquoted = not any(c[1] for c in chars)
    if unquoted and flat in ("!", "[[", "]]"):
        return pos, "reserved word"
    if unquoted and flat in ("{", "}"):
        return pos, "grouping"
    if not chars[0][1] and chars[0][0] == "#":
        return pos, "comment"
    for ch, quoted, p in chars:
        if not quoted and ch in "*?[":
            return p, "expansion"
    brace = _brace_pos(chars)
    if brace >= 0:
        return brace, "expansion"
    if not chars[0][1] and chars[0][0] == "~":
        return chars[0][2], "expansion"
    head = _assign_head(chars)
    if head is not None:
        k = head[2]
        for m in range(k, len(chars)):
            if m == k or (not chars[m - 1][1] and chars[m - 1][0] == ":"):
                if not chars[m][1] and chars[m][0] == "~":
                    return chars[m][2], "expansion"
    return None


def _check_str(value, name):
    if type(value) is not str:
        raise TypeError("%s must be str, not %s" % (name, type(value).__name__))


def scan(text: str) -> Scan:
    _check_str(text, "text")
    toks, found = _tokenize(text)
    for tok in toks:
        if tok[0] == "w":
            hit = _word_reason(tok[1], tok[2], tok[3])
            if hit is not None:
                found.append(hit)
    # The one compound form: a first `&&` after exactly `cd <word>` with something after it.
    main = 0
    cd = None
    if (len(toks) > 3 and toks[0][0] == "w" and toks[1][0] == "w" and toks[2][0] == "op" and toks[2][1] == "&&"):
        target = toks[1][3]
        if (toks[0][3] == "cd" and _unquoted(toks[0]) and target != ""
                and not target.startswith("-")):
            main = 3
            cd = target
    # `<(` and `>(` also found a substitution at the same position, which comes first in `found` and so wins.
    for idx, tok in enumerate(toks):
        if tok[0] == "op" and not (idx == 2 and main == 3):
            found.append((tok[2], _OP_REASON.get(tok[1], "redirection")))
    # A leading NAME+=value is an append assignment, which bash expands.
    for tok in toks[main:]:
        if tok[0] != "w":
            break
        head = _assign_head(_chars(tok))
        if head is None:
            break
        if head[1]:
            found.append((tok[2], "expansion"))
    words = tuple([t[3] if t[0] == "w" else t[1] for t in toks])
    if found:
        reason = min(found, key=lambda f: f[0])[1]
        return Scan(False, None, (), (), reason, words)
    assignments = []
    rest = toks[main:]
    k = 0
    while k < len(rest):
        head = _assign_head(_chars(rest[k]))
        if head is None:
            break
        assignments.append((head[0], _flat(_chars(rest[k])[head[2]:])))
        k += 1
    argv = tuple([t[3] for t in rest[k:]])
    return Scan(True, cd, tuple(assignments), argv, "", words)


def token_in(text: str, word: str, casefold: bool = False) -> bool:
    _check_str(text, "text")
    _check_str(word, "word")
    if word == "":
        return False
    if casefold:
        text = text.translate(_LOWER)
        word = word.translate(_LOWER)
    size = len(word)
    at = text.find(word)
    while at >= 0:
        before = text[at - 1] if at > 0 else ""
        after = text[at + size] if at + size < len(text) else ""
        if before not in _TOKEN_CLASS and after not in _TOKEN_CLASS:
            return True
        at = text.find(word, at + 1)
    return False
