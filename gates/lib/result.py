"""Gate result contract: PASS/FAIL lines, the run wrapper, argument parsing, repo root (standard library only)."""
from __future__ import annotations

import argparse
import builtins
import json
import os
import sys
from dataclasses import dataclass, field
from typing import Optional

from gates.lib.yamlsub import MAX_DEPTH  # owner Q-R6R-2 (b): the renderer's nesting cap is the plan's MAX_DEPTH


class GateError(Exception):
    """A problem with a gate's input or environment; the message is the FAIL reason."""


class GitNotFound(GateError):
    """git is not on PATH (no repository hint can help)."""


@dataclass
class Line:
    status: str
    id: str
    reason: str = ""


def safe_text(s: object) -> str:
    """``s`` as one line: a backslash becomes ``\\\\`` and every non-printable character is escaped
    (``\\n``, ``\\xNN``, ``\\uNNNN``, ``\\UNNNNNNNN``), so the output is unambiguous."""
    text = _exact(s) if issubclass(type(s), str) else _exact(str(s))  # type(), never __class__ (Q-1C0R5-1 (a))
    out = []
    for c in text:
        if c == "\\":
            out.append("\\\\")
        elif c.isprintable():
            out.append(c)
        elif c == "\n":
            out.append("\\n")
        elif c == "\r":
            out.append("\\r")
        elif c == "\t":
            out.append("\\t")
        elif ord(c) <= 0xFF:
            out.append("\\x%02x" % ord(c))
        elif ord(c) <= 0xFFFF:
            out.append("\\u%04x" % ord(c))
        else:
            out.append("\\U%08x" % ord(c))
    return "".join(out)


@dataclass
class Result:
    gate: str
    lines: list = field(default_factory=list)

    def ok(self) -> bool:
        return bool(self.lines) and all(ln.status == "PASS" for ln in self.lines)

    def fail(self, id: str, reason: str) -> None:
        self.lines.append(Line("FAIL", id, reason))

    def passed(self, id: str) -> None:
        self.lines.append(Line("PASS", id))

    def render(self, as_json: bool) -> str:
        if as_json:
            return json.dumps({
                "gate": self.gate,
                "ok": self.ok(),
                "lines": [{"status": ln.status, "id": ln.id, "reason": str(ln.reason)} for ln in self.lines],
            }) + "\n"
        out = []
        for ln in self.lines:
            if ln.status == "PASS":
                out.append("PASS %s\n" % safe_text(ln.id))
            else:
                out.append("FAIL %s: %s\n" % (safe_text(ln.id), safe_text(ln.reason)))
        return "".join(out)


class _GateParser(argparse.ArgumentParser):
    """Help and usage errors go to stderr and become GateError, never SystemExit."""

    def print_help(self, file=None) -> None:
        super().print_help(sys.stderr if file is None else file)

    def exit(self, status: int = 0, message: Optional[str] = None):
        if message:
            sys.stderr.write(message)
        if status == 0:
            raise GateError("help requested; no gate was run")
        raise GateError("invalid arguments (exit status %d)" % status)

    def error(self, message: str):
        self.print_usage(sys.stderr)
        sys.stderr.write("%s: error: %s\n" % (self.prog, message))
        raise GateError("invalid arguments: %s" % message)


class _Once(argparse.Action):
    """Store the value; a second occurrence (in full, with ``=`` or abbreviated) is an argument error."""

    def __call__(self, parser, namespace, values, option_string=None):
        if getattr(namespace, self.dest, None) is not None:
            parser.error("%s given more than once" % self.option_strings[0])
        setattr(namespace, self.dest, values)


def gate_args(prog: str) -> argparse.ArgumentParser:
    p = _GateParser(prog=prog, add_help=True)
    p.add_argument("--root", default=None, action=_Once, help="the tree to check (default: the repository root)")
    return p


def _exact(s: str) -> str:
    """The characters of ``s`` (a ``str`` or a subclass) as an exact ``str``; no method of a subclass runs
    (owner Q-1C0FIN2-R1 (a)), so a later ``%s``, ``+``, ``str()`` or json step cannot reach one."""
    return str.__str__(s)


_TYPE_NAME = type.__dict__["__name__"]


def _type_name(x: object) -> str:
    """The name of ``x``'s type as an exact ``str``, read past a metaclass that overrides ``__name__``."""
    return _exact(_TYPE_NAME.__get__(type(x)))


def _raw(x: object) -> str:
    """``x`` as text without Python's repr escaping, so that ``Result.render`` escapes it exactly once."""
    return _raw_on(x, ())


def _raw_on(x: object, path: tuple) -> str:
    """``_raw`` with the ids of the containers on the current path: one that contains itself renders as
    ``{...}`` or ``[...]``, as ``repr`` does (owner Q-1c0-3). Owner Q-1C0FIN2-1 (b), in repr's shape (pin R8): a
    set renders as ``{`` + its items sorted by their rendered text + ``}`` (``set()`` when empty), a frozenset as
    ``frozenset(`` + that + ``)`` (``frozenset()``), so the order does not depend on the hash seed. Bytes render
    as ``b'`` + the bytes decoded as Latin-1 + ``'`` (owner Q-F80W-3 (a)), so safe_text escapes each byte once.
    Every kind is read from ``type(x)``, never from ``x.__class__``, so an object cannot claim a kind (Q-1C0R5-1 (a))."""
    t = type(x)
    if issubclass(t, str):
        return _exact(x)
    if issubclass(t, bytes):
        return "b'" + bytes.decode(x, "latin-1") + "'"
    if not issubclass(t, (set, frozenset, dict, list, tuple)):
        return _leaf_text(x)
    if id(x) in path:
        return "[...]" if issubclass(t, (list, tuple)) else "{...}"
    if len(path) >= MAX_DEPTH:  # owner Q-R6R-2 (b): a fixed nesting cap, the same on every interpreter
        raise RecursionError("nesting deeper than %d" % MAX_DEPTH)
    inner = path + (id(x),)
    if issubclass(t, (set, frozenset)):
        items = sorted(_items_text([i for i in x], inner))
        body = "{" + ", ".join(items) + "}" if items else ""
        if issubclass(t, frozenset):
            return "frozenset(" + body + ")"
        return body or "set()"
    if issubclass(t, dict):
        texts = _items_text([o for k, v in x.items() for o in (k, v)], inner)
        return "{" + ", ".join(texts[n] + ": " + texts[n + 1] for n in range(0, len(texts), 2)) + "}"
    return "[" + ", ".join(_items_text([i for i in x], inner)) + "]"


def _items_text(items: list, path: tuple) -> list:
    """Each item rendered under its own guard (owner Q-R6R-1 (b)): an item that raises an Exception renders as that
    exception's type name. Every item is rendered before anything propagates, so what propagates does not depend on
    the order of the items (a set's order depends on the hash seed): a non-Exception BaseException first, else a
    RecursionError, which collapses the whole value to the type name, as nesting past the cap does (owner Q-R6R-2
    (b), Q-1C0V1R-3 (b)(i)). Of several non-Exception BaseExceptions, the one of highest rank (``_rank``)
    propagates; of one rank, the first collected (owner Q-R7R-0 (a), Q-R8-1 (a), Q-R8R-0 (a))."""
    out, stop = [], None
    for i in items:
        try:
            out.append(_raw_on(i, path))
        except RecursionError as e:
            stop = e if stop is None else stop
        except Exception as e:
            out.append(_type_name(e))
        except BaseException as e:
            if stop is None or issubclass(type(stop), Exception) or _rank(e) < _rank(stop):
                stop = e
    if stop is not None:
        raise stop
    return out


_MRO = type.__dict__["__mro__"]
_BUILTIN_CLASSES = frozenset(id(v) for v in vars(builtins).values() if issubclass(type(v), type))
# Owner Q-R8R-0 (a), Q-R9R-1 (c): the rank order; an entry the interpreter lacks (BaseExceptionGroup before 3.11)
# is skipped, so the remaining ranks keep their order.
_RANK_ORDER = ("KeyboardInterrupt", "SystemExit", "GeneratorExit", "BaseExceptionGroup")
_RANKS = {id(vars(builtins)[n]): r for r, n in enumerate(_RANK_ORDER) if n in vars(builtins)}
_OTHER = len(_RANK_ORDER)


def _rank(x: object) -> int:
    """The rank of ``x``'s type (smaller propagates first): the first built-in class in its real ``__mro__``,
    read through the ``type`` descriptor, so nothing the object or its metaclass defines is consulted (owner
    Q-R8R-0 (a), Q-R9R-1 (c), Q-R6-3 (a)): KeyboardInterrupt, SystemExit, GeneratorExit, BaseExceptionGroup, any
    other. Classes are compared by identity, so no name, ``__module__``, ``__qualname__`` or ``__eq__`` is read."""
    for c in _MRO.__get__(type(x)):
        if id(c) in _BUILTIN_CLASSES:
            return _RANKS.get(id(c), _OTHER)
    return _OTHER  # not reached: a type an ``except BaseException`` arm catches has BaseException in its __mro__


def _leaf_text(x: object) -> str:
    """``str(x)``; if that raises, ``repr(x)``; if that raises too, the type name, as a missing ``strerror``
    falls back to it (V1r-1, owner Q-1C0V1R-1 (a): a reason is always produced)."""
    for text in (str, repr):
        try:
            return _exact(text(x))
        except Exception:
            pass
    return _type_name(x)


def _s(x: object) -> str:
    """``str(x)`` by its characters, as CPython's own ``%S`` formatting takes it."""
    return _exact(str(x))


def _args_text(e: BaseException) -> str:
    """``BaseException.__str__(e)`` with ``_raw`` in place of ``str`` and ``repr``: the arguments rendered once. The
    arguments are not a container's items (owner Q-R7-1 (a)): each renders unguarded, in order, and the first that
    raises collapses the reason to the type name (Q-1C0V1R-3 (b)(i))."""
    if len(e.args) == 1:
        return _raw(e.args[0])
    return "[" + ", ".join(_raw(a) for a in e.args) + "]" if e.args else ""


def _exc_text(e: BaseException) -> str:
    """``str(e)`` with the repr that the exception's ``__str__`` applies to its arguments undone (verifier V-1):
    KeyError; OSError with a filename, or in its ``[Errno <errno>] <strerror>`` form; SyntaxError's message;
    and every ``__str__`` whose text is the default one, the repr of the arguments. In each branch a class's own
    ``__str__`` text stands (``_own_str_or``, owner Q-F80W-4 (a), Q-1C0FIN3-1 (a))."""
    if issubclass(type(e), KeyError) and e.args:
        return _own_str_or(e, KeyError, _args_text)
    if issubclass(type(e), OSError) and e.filename is not None:
        return _own_str_or(e, OSError, _filename_text)
    if type(e).__str__ is BaseException.__str__:
        return _args_text(e)
    try:
        text = _s(e)
    except Exception:  # the own __str__ cannot render an argument: render the arguments themselves
        return _args_text(e)
    return _own_str_text(e, text)


def _filename_text(e: OSError) -> str:
    """An OSError with a filename: ``[Errno <errno>] <strerror>: <filename>[ -> <filename2>]``, each part once."""
    head = "[Errno %s] " % _raw(e.errno) if e.errno is not None else ""
    out = head + _raw(e.strerror or _type_name(e)) + ": " + _raw(e.filename)
    if e.filename2 is not None:
        out += " -> " + _raw(e.filename2)
    return out


def _gate_filename_text(e: OSError) -> Optional[str]:
    """A GateError that is an OSError with a filename: main d9798af's reason was ``str(e)``, CPython's
    ``[Errno %S] %S: %R[ -> %R]``, so that form with each part once, the head kept whatever errno and strerror are
    and a filename2 shown wherever CPython shows it (F-r13r-1, owner Q-ES-V1 (a)). The form is read off
    ``OSError.__str__(e)`` itself, so a filename2 that the attribute reads as None but CPython shows is kept; None if
    that text is not this form (the caller then renders the text as the generic branch does)."""
    text = _text_of(lambda: OSError.__str__(e))
    head = _text_of(lambda: "[Errno %s] %s: %s" % (_s(e.errno), _s(e.strerror), _exact(repr(e.filename))))
    if text is None or head is None or not text.startswith(head):
        return None
    out = "[Errno %s] %s: %s" % (_raw(e.errno), _raw(e.strerror), _raw(e.filename))
    if text == head:
        return out
    if text[len(head):] == _text_of(lambda: " -> " + _exact(repr(e.filename2))):
        return out + " -> " + _raw(e.filename2)
    return None


_DICT = type.__dict__["__dict__"]


def _own_str_or(e: BaseException, base: type, fallback) -> str:
    """``e``'s own ``__str__`` text, if the ``__str__`` its type's real ``__mro__`` resolves to is no built-in
    class's in that ``__mro__`` (``object``'s included, owner Q-R13R-1 (b); read through the ``type`` descriptors,
    so a metaclass changes nothing and a class without an own ``__str__`` renders as before, F-r11r-1 (b)), as an
    exact ``str`` reconciled by ``_own_str_text``; if it is ``base``'s, or that own ``__str__`` raises or returns a
    non-str, ``fallback(e)``, the branch's rendering of the arguments; if it is another built-in's, main d9798af's
    form: the one argument in the KeyError branch (F-r13r-2), the filename form in the KeyError and OSError branches
    (F-r12r-1), else that built-in's form with each part once (``_built_in_text``) (owner Q-F80W-4 (a), Q-1C0FIN3-1
    (a), Q-1C0FIN2-R1 (a), Q-ES-V1 (a))."""
    mro = _MRO.__get__(type(e))
    own = next(_DICT.__get__(c)["__str__"] for c in mro if "__str__" in _DICT.__get__(c))
    for c in mro:
        if id(c) in _BUILTIN_CLASSES and _DICT.__get__(c).get("__str__") is own:
            if base is KeyError and len(e.args) == 1:  # F-r13r-2: main's KeyError branch rendered the one argument
                return fallback(e)
            if base is not BaseException and c is not OSError and _main_filename_form(e):  # F-r12r-1
                return _filename_text(e)
            return fallback(e) if c is base else _built_in_text(e, c)
    try:
        text = _s(e)
    except Exception:  # the own __str__ cannot render an argument: render the arguments themselves
        return fallback(e)
    return _own_str_text(e, text)


def _main_filename_form(e: BaseException) -> bool:
    """Whether main d9798af's ``_exc_text`` gave ``e`` the filename form: an OSError with a filename, unless it is a
    KeyError with one argument (main's KeyError branch came first). In the KeyError and OSError branches a class
    with no own ``__str__`` keeps that form whichever built-in ``__str__`` it resolves to; a GateError's reason was
    ``str(e)``, so not there (F-r12r-1, owner Q-ES-V1 (a))."""
    t = type(e)
    return issubclass(t, OSError) and e.filename is not None and not (issubclass(t, KeyError) and len(e.args) == 1)


def _built_in_text(e: BaseException, c: type) -> str:
    """The text of built-in ``c``'s ``__str__`` for ``e`` with the arguments rendered once: KeyError's and
    BaseException's from the arguments, OSError's with a filename from its parts, as their own branches give them
    (for a GateError, CPython's form, ``_gate_filename_text``); any other's (SyntaxError's, OSError's without a
    filename, ...) as the generic branch of ``_exc_text`` does."""
    if c is KeyError or c is BaseException:
        return _args_text(e)
    if c is OSError and e.filename is not None:
        text = _gate_filename_text(e) if issubclass(type(e), GateError) else _filename_text(e)
        if text is not None:
            return text
    try:
        text = _s(e)
    except Exception:  # as the generic branch: render the arguments themselves
        return _args_text(e)
    return _own_str_text(e, text)


def _text_of(make) -> Optional[str]:
    """``make()`` as an exact ``str``, or None if it raises: a form whose text cannot be computed is not the form
    of ``str(e)``."""
    try:
        return _exact(make())
    except Exception:
        return None


def _own_str_text(e: BaseException, text: str) -> str:
    """``text`` (``str(e)`` from an own ``__str__``) with the arguments rendered once where it shows them. When
    it shows them and they cannot render, the error propagates to ``_reason_text``, as for a default ``__str__``
    (owner Q-1C0V1R-3 (b)(i)); a text that does not show them stands."""
    if text == _text_of(lambda: BaseException.__str__(e)):  # an own __str__ that fell back to the default
        return _args_text(e)
    if issubclass(type(e), KeyError) and text == _text_of(lambda: KeyError.__str__(e)):  # F-r11r-1 (a)
        return _args_text(e)
    if issubclass(type(e), OSError) and e.filename is not None and text == _text_of(lambda: OSError.__str__(e)):
        # F-r11r-1 (a): the built-in filename form, each part once; a GateError's reason was str(e) in main (F-r13r-1)
        once = _gate_filename_text(e) if issubclass(type(e), GateError) else _filename_text(e)
        if once is not None:
            return once
    if issubclass(type(e), OSError) and text == _text_of(lambda: "[Errno %s] %s" % (_s(e.errno), _s(e.strerror))):
        return "[Errno %s] %s" % (_raw(e.errno), _raw(e.strerror))
    msg = _text_of(lambda: _s(e.msg)) if issubclass(type(e), SyntaxError) and e.msg is not None else None
    if msg is not None and text.startswith(msg):
        return _raw(e.msg) + text[len(msg):]
    return text


def _exit_text(e: SystemExit) -> str:
    code = e.code
    return "'%s'" % _exact(code) if issubclass(type(code), str) else _raw(code)


def _reason_text(e: BaseException, text) -> str:
    """``text(e)`` as an exact ``str``; if the exception itself cannot be read (its ``args`` raise), its type name,
    the ``_leaf_text`` fallback, so run_check always returns a reason (owner Q-1C0V1R-1 (a))."""
    try:
        return _exact(text(e))
    except Exception:
        return _type_name(e)


def run_check(name: str, check, args: list) -> Result:
    """Run ``check(args)``; anything but a non-empty Result becomes a FAIL line. Every reason and id that leaves
    is an exact ``str`` (F-1c0fin2-1, owner Q-1C0FIN2-R2 (a))."""
    try:
        result = check(args)
    except GateError as e:
        return _input_fail(name, _reason_text(e, lambda x: _own_str_or(x, BaseException, _args_text)))
    except SystemExit as e:
        return _input_fail(name, "exit requested (%s)" % _reason_text(e, _exit_text))
    except Exception as e:
        return _input_fail(name, "%s: %s" % (_type_name(e), _reason_text(e, _exc_text)))
    try:  # one guard over all the work after the check returns (owner Q-1C0R5-1 (a)); a BaseException propagates
        if not issubclass(type(result), Result):
            return _input_fail(name, "the check returned %s, not a Result" % _type_name(result))
        return _own_result(name, result)
    except Exception as e:  # the type-name fallback, as _reason_text gives for an exception it cannot render
        return _input_fail(name, _type_name(e))


_STATUSES = ("PASS", "FAIL")  # spec §13: a gate prints PASS id or FAIL id: reason lines


def _own_result(name: str, result: Result) -> Result:
    """A new Result built from the one the check returned, which is never changed (F-fin2r-1). Its shape is checked
    first (owner Q-1C0FIN2-U2 (a)): the gate an exact ``str``, ``lines`` a list (plan: ``Result(gate: str, lines:
    list)``), each entry a Line whose status is the exact ``str`` PASS or FAIL. Any other shape fails
    ``<name>.input`` with a named reason, as a value that is not a Result does; an empty list fails ``<name>.empty``.
    The gate must be ``name`` (owner Q-1C0R5-2 (a)). Kinds are read from ``type()``, never ``__class__``, so an
    object that claims to be a list, a Line or a str is refused (owner Q-1C0R5-1 (a)); a class whose real ``__mro__``
    holds Result or Line is a subclass (owner Q-R6-3 (a)). An id and a reason render through ``_raw``, item by item
    as an exception argument does (owner Q-F80W-5 (b), Q-R6-2 (a))."""
    try:
        gate, lines = result.gate, result.lines
    except Exception:
        return _input_fail(name, "the check returned a Result that cannot be read")
    if type(gate) is not str:
        return _input_fail(name, "the check returned a Result whose gate is %s, not a str" % _type_name(gate))
    if gate != _exact(name):
        return _input_fail(name, "the check returned a Result for gate %s, not %s" % (gate, _exact(name)))
    if not issubclass(type(lines), list):
        return _input_fail(name, "the check returned a Result whose lines is %s, not a list" % _type_name(lines))
    out = []
    for n, ln in enumerate(list.copy(lines), 1):
        if not issubclass(type(ln), Line):
            return _input_fail(name, "line %d of the Result is %s, not a Line" % (n, _type_name(ln)))
        try:
            status, id_, reason = ln.status, ln.id, ln.reason
        except Exception:
            return _input_fail(name, "line %d of the Result cannot be read" % n)
        if type(status) is not str:
            return _input_fail(name, "line %d of the Result has a status of type %s, not str" % (n, _type_name(status)))
        if status not in _STATUSES:
            return _input_fail(name, "line %d of the Result has status %s, not PASS or FAIL" % (n, status))
        out.append(Line(status, _raw(id_), _raw(reason)))
    if not out:
        empty = Result(name, [])
        empty.fail(name + ".empty", "the gate produced no lines")
        return empty
    return Result(gate, out)


def _input_fail(name: str, reason: str) -> Result:
    out = Result(name, [])
    out.fail(name + ".input", reason)
    return out


def run_gate(name: str, check, argv: Optional[list] = None) -> int:
    """Run a gate: ``--json`` counts only as ``argv[0]``; print the lines; exit code 0 only when ok."""
    args = list(sys.argv[1:] if argv is None else argv)
    as_json = args[:1] == ["--json"]
    if as_json:
        args = args[1:]
    result = run_check(name, check, args)
    sys.stdout.write(result.render(as_json))
    return 0 if result.ok() else 1


def repo_root() -> str:
    """``CLAUDE_PROJECT_DIR`` when set and non-empty (it must be a directory), else the git toplevel."""
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env:
        if not os.path.isdir(env):
            raise GateError("CLAUDE_PROJECT_DIR is not a directory")
        return env
    from gates.lib import gitinfo
    try:
        return gitinfo.toplevel(".")
    except GitNotFound:
        raise
    except GateError as e:
        raise GateError("%s; run /strict-delivery:init" % e) from None
