"""Gate result contract: PASS/FAIL lines, the run wrapper, argument parsing, repo root (standard library only)."""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from typing import Optional


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
    text = s if isinstance(s, str) else str(s)
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


def _raw(x: object) -> str:
    """``x`` as text without Python's repr escaping, so that ``Result.render`` escapes it exactly once."""
    return _raw_on(x, ())


def _raw_on(x: object, path: tuple) -> str:
    """``_raw`` with the ids of the containers on the current path: one that contains itself renders as
    ``{...}`` or ``[...]``, as ``repr`` does (owner Q-1c0-3)."""
    if isinstance(x, str):
        return x
    if isinstance(x, dict):
        if id(x) in path:
            return "{...}"
        inner = path + (id(x),)
        return "{" + ", ".join(_raw_on(k, inner) + ": " + _raw_on(v, inner) for k, v in x.items()) + "}"
    if isinstance(x, (list, tuple)):
        if id(x) in path:
            return "[...]"
        inner = path + (id(x),)
        return "[" + ", ".join(_raw_on(i, inner) for i in x) + "]"
    return str(x)


def _exc_text(e: BaseException) -> str:
    """``str(e)`` with the repr that KeyError and OSError-with-filename apply to their text undone."""
    if isinstance(e, KeyError) and len(e.args) == 1:
        return _raw(e.args[0])
    if isinstance(e, OSError) and e.filename is not None:
        head = "[Errno %s] " % e.errno if e.errno is not None else ""
        out = head + (e.strerror or type(e).__name__) + ": " + _raw(e.filename)
        if e.filename2 is not None:
            out += " -> " + _raw(e.filename2)
        return out
    return str(e)


def run_check(name: str, check, args: list) -> Result:
    """Run ``check(args)``; anything but a non-empty Result becomes a FAIL line."""
    try:
        result = check(args)
    except GateError as e:
        return _input_fail(name, _raw(e.args[0] if len(e.args) == 1 else list(e.args)) if e.args else "")
    except SystemExit as e:
        return _input_fail(name, "exit requested (%s)" % ("'%s'" % e.code if isinstance(e.code, str) else _raw(e.code),))
    except Exception as e:
        return _input_fail(name, "%s: %s" % (type(e).__name__, _exc_text(e)))
    if not isinstance(result, Result):
        return _input_fail(name, "the check returned %s, not a Result" % type(result).__name__)
    if not result.lines:
        out = Result(name, [])
        out.fail(name + ".empty", "the gate produced no lines")
        return out
    return result


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
