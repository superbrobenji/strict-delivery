"""Shell scanner for the Bash hook (standard library only).

``scan(text)`` says whether ``text`` is a plain command (``Scan.plain``) and, if so, which words the program gets
(``argv``), which leading ``NAME=value`` assignments come before it and, for the one allowed compound form
``cd <dir> && <simple command>``, which directory. The accepted grammar is closed (owner answer 2026-11-16: restrict
the input and fail closed, on the union of bash and zsh default semantics); text it does not derive is not plain:

- an optional prefix ``cd <dir> &&`` (``cd`` unquoted) whose ``<dir>`` starts with ``/`` and has no ``.`` or ``..``
  segment;
- leading assignments, each to a name in ``_ALLOW``;
- an optional program word: unquoted, unescaped, of ``[A-Za-z0-9_./-]`` only, not starting with ``-``, and not a
  reserved word or precommand modifier of bash or zsh;
- argument words. Unquoted, a word holds only the characters of ``_U``; quoted, anything but NUL (and, in double
  quotes, an unescaped ``$`` or backtick). Two neighbouring ``[0-9A-Za-z_-]`` characters of a word must be neighbours
  in the text too, so quoting, an escape or a line join never splits a token that ``token_in`` looks for;
- no construct the shell would expand (glob, brace, tilde, ``=``, ``$``), so ``argv`` is what the shell would run.

Everything else is not plain, and ``reason`` names the construct at the smallest text position; at the same position a
specific construct wins over a catch-all (``command word``, then ``character``, ``assignment``, ``quoting``).
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
_U = _NAME_REST | frozenset("-./:@+,%^=~{}#")  # the characters a word may hold unquoted
_PROGRAM = _NAME_REST | frozenset("./-")  # the characters of the program word
_GLOB = frozenset("*?[")
# Leading assignments allowed: the five that Task 3b.2 refuses by their own ids, and three that change no program or path.
_ALLOW = frozenset(("GIT_INDEX_FILE", "GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_OBJECT_DIRECTORY", "LANG",
                    "LC_ALL", "TZ"))
_OPS = frozenset(("&&", "||", ";;", "|&", "&>", "<<", "<>", "<&", ">>", ">&", ">|", "&>>", "<<<", "<<-", ";", "|", "&",
                  "<", ">", "(", ")"))
_OP_REASON = {";": "operator ;", ";;": "operator ;", "&&": "operator &&", "||": "operator ||", "|": "operator |",
              "|&": "operator |", "&": "operator &", "(": "grouping", ")": "grouping", "\n": "operator newline"}
_UNBALANCED = "unbalanced quote"
# Ranks of the reasons at one text position: a specific construct, then the program word, then the other catch-alls.
_SPECIFIC = 0
_PROGRAM_RANK = 1
_CATCH_ALL = 2
# Keywords of bash and zsh (the union, fail closed) that change what the command word means.
_COMMAND_RESERVED = frozenset(("case", "coproc", "do", "done", "elif", "else", "esac", "fi", "for", "function", "if",
                               "in", "select", "then", "time", "until", "while", "repeat", "foreach", "end",
                               "nocorrect", "noglob", "declare", "export", "float", "integer", "local", "readonly",
                               "typeset", "-", "builtin", "command", "exec"))
_RUN = re.compile("[^ \t\n\\\\'\"|&;<>()$`]+")  # a run of ordinary word characters
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
    operators. Also returns ``(pos, rank, reason)`` constructs found on the way."""
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
        found.append((nul, _SPECIFIC, "nul character"))
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
                found.append((i, _SPECIFIC, _UNBALANCED))
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
                found.append((i, _SPECIFIC, _UNBALANCED))
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
                    found.append((j, _SPECIFIC, "substitution" if text[j + 1:j + 2] == "(" else "expansion"))
                elif ch == "`":
                    found.append((j, _SPECIFIC, "substitution"))
                state["cur"].append((ch, True, j))
                j += 1
            if j >= n:
                found.append((i, _SPECIFIC, _UNBALANCED))
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
                found.append((i, _SPECIFIC, "substitution"))
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
                found.append((i, _SPECIFIC, "substitution" if nxt == "(" else "expansion"))
                state["cur"].append((c, False, i))
                i += 1
            elif c == "`":
                found.append((i, _SPECIFIC, "substitution"))
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


def _digits_assign(chars):
    """True when the word starts with unquoted digits and then an unquoted ``=`` or ``+=`` (zsh: a positional-parameter
    assignment, which bash does not take as one)."""
    k = 0
    while k < len(chars) and not chars[k][1] and chars[k][0] in "0123456789":
        k += 1
    if k == 0:
        return False
    if k < len(chars) and not chars[k][1] and chars[k][0] == "+":
        k += 1
    return k < len(chars) and not chars[k][1] and chars[k][0] == "="


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


def _word_checks(tok, found):
    """Add to ``found`` every construct inside one word: a reserved or group word, a comment, a character outside
    ``_U``, an expansion, and a token split by quoting."""
    chars = tok[1]
    if not chars:  # the fast path (a run of [0-9A-Za-z_]) and an empty quoted word hold nothing to check
        return
    pos = tok[2]
    flat = tok[3]
    unquoted = not any(c[1] for c in chars)
    if unquoted and flat in ("!", "[[", "]]"):
        found.append((pos, _SPECIFIC, "reserved word"))
    if unquoted and flat in ("{", "}"):
        found.append((pos, _SPECIFIC, "grouping"))
    first = chars[0]
    if not first[1]:
        if first[0] == "#":
            found.append((pos, _SPECIFIC, "comment"))
        elif first[0] == "~" or first[0] == "=":  # tilde, and zsh EQUALS (`=git` is the path of git)
            found.append((first[2], _SPECIFIC, "expansion"))
        elif first[0] == "{" or first[0] == "}":
            found.append((first[2], _CATCH_ALL, "character"))
    prev = None
    for cur in chars:
        ch, quoted, p = cur
        if not quoted:
            if ch in _GLOB:
                found.append((p, _SPECIFIC, "expansion"))
            elif ch not in _U:
                found.append((p, _CATCH_ALL, "character"))
            elif ch == "~" and prev is not None and not prev[1] and (prev[0] == "=" or prev[0] == ":"):
                found.append((p, _SPECIFIC, "expansion"))
        if prev is not None and prev[0] in _TOKEN_CLASS and ch in _TOKEN_CLASS and p != prev[2] + 1:
            found.append((prev[2] + 1, _CATCH_ALL, "quoting"))
        prev = cur
    brace = _brace_pos(chars)
    if brace >= 0:
        found.append((brace, _SPECIFIC, "expansion"))
    head = _assign_head(chars)
    if head is not None:
        k = head[2]
        for m in range(k, len(chars)):
            if m == k or chars[m - 1][0] == ":":  # a quoted colon counts too in zsh
                if not chars[m][1] and chars[m][0] in "~=":  # tilde, and zsh EQUALS
                    found.append((chars[m][2], _SPECIFIC, "expansion"))


def _program_word(tok):
    """True when the word may be the program word: of ``_PROGRAM`` only, not starting with ``-``, and each character at
    the next text position (so nothing in it is quoted, escaped or line-joined: each of those takes a position)."""
    if tok[1] is None:
        return True
    chars = tok[1]
    if not chars or chars[0][0] == "-":
        return False
    at = tok[2]
    for ch, _quoted, p in chars:
        if ch not in _PROGRAM or p != at:
            return False
        at += 1
    return True


def _cd_target(target):
    """True when the cd form's directory is absolute with no ``.`` or ``..`` segment."""
    if target[:1] != "/":
        return False
    for seg in target.split("/"):
        if seg == "." or seg == "..":
            return False
    return True


def _check_str(value, name):
    if type(value) is not str:
        raise TypeError("%s must be str, not %s" % (name, type(value).__name__))


def scan(text: str) -> Scan:
    _check_str(text, "text")
    toks, found = _tokenize(text)
    for tok in toks:
        if tok[0] == "w":
            _word_checks(tok, found)
    # The one compound form: a first `&&` after exactly `cd <absolute dir>` with something after it.
    main = 0
    cd = None
    if (len(toks) > 3 and toks[0][0] == "w" and toks[1][0] == "w" and toks[2][0] == "op" and toks[2][1] == "&&"):
        target = toks[1][3]
        if toks[0][3] == "cd" and _unquoted(toks[0]) and _cd_target(target):
            main = 3
            cd = target
    # `<(` and `>(` also found a substitution at the same position, which comes first in `found` and so wins.
    for idx, tok in enumerate(toks):
        if tok[0] == "op" and not (idx == 2 and main == 3):
            found.append((tok[2], _SPECIFIC, _OP_REASON.get(tok[1], "redirection")))
    # Leading assignments (allowed names only; NAME+=value is an append, which the shell expands), then the program word.
    for tok in toks[main:]:
        if tok[0] != "w":
            break
        chars = _chars(tok)
        head = _assign_head(chars)
        if head is None:
            # A shell keyword as the command word starts a construct, and zsh takes `1=x` (digits for a name) as an
            # assignment too.
            if _digits_assign(chars):
                found.append((tok[2], _SPECIFIC, "expansion"))
            elif tok[3] in _COMMAND_RESERVED and _unquoted(tok):
                found.append((tok[2], _SPECIFIC, "reserved word"))
            if not _program_word(tok):
                found.append((tok[2], _PROGRAM_RANK, "command word"))
            break
        if head[1]:
            found.append((tok[2], _SPECIFIC, "expansion"))
        if head[0] not in _ALLOW:
            found.append((tok[2], _CATCH_ALL, "assignment"))
    words = tuple([t[3] if t[0] == "w" else t[1] for t in toks])
    if found:
        reason = min(found, key=lambda f: (f[0], f[1]))[2]
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
