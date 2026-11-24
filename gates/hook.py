"""``python3 -m gates hook <Event>``: read one hook input from stdin, route it to its handler module, print the result.

The hook fails closed: any exception (parse error, missing or raising handler, a bad handler result) refuses on
PreToolUse (exit 2), prints the failure line on SessionStart and UserPromptSubmit, and prints nothing on PostToolUse and
SubagentStop (they refuse nothing). Standard library only."""
from __future__ import annotations

import importlib
import os
import sys
from typing import List, Optional

from gates.lib import hookio
from gates.lib.result import GateError, _type_name, safe_text

HANDLERS = {
    ("SessionStart", None): "gates.hooks.session_start",
    ("UserPromptSubmit", None): "gates.hooks.prompt_submit",
    ("PreToolUse", "agent"): "gates.hooks.pre_agent",
    ("PreToolUse", "bash"): "gates.hooks.pre_bash",
    ("PreToolUse", "edit"): "gates.hooks.pre_edit",
    ("PostToolUse", "read"): "gates.hooks.post_read",
    ("SubagentStop", None): "gates.hooks.subagent_stop",
}

USAGE = "FAIL hook.usage: python3 -m gates hook <Event>; events: " + ", ".join(hookio.EVENTS)
_TAIL = "; the strict-delivery hook fails closed; the human can disable the plugin with /plugin, and !-prefixed commands still run"


def framework_dir() -> str:
    """The directory holding the ``gates`` package of this process."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _reason(e: BaseException) -> str:
    """The raw reason text of ``e`` (escaped once, by ``fail_line``)."""
    try:
        text = str(e)
    except Exception:
        text = "unprintable"
    return text if isinstance(e, GateError) else "%s: %s" % (_type_name(e), text)


def fail_line(event: str, reason: str, escaped: bool = False) -> str:
    return "FAIL hook.%s: %s%s" % (event, reason if escaped else safe_text(reason), _TAIL)


def _outcome_ok(o: object) -> bool:
    if type(o) is not hookio.Outcome:
        return False
    for name in ("deny", "context", "text"):
        lines = getattr(o, name)
        if type(lines) is not list or any(type(x) is not str for x in lines):
            return False
    return True


def _handle(event: str, data: bytes) -> tuple:
    raw = hookio.parse(event, data)
    group = None
    if event in ("PreToolUse", "PostToolUse"):
        group = hookio.TOOL_GROUPS.get(raw["tool_name"])
        if group is None:
            return ("", "", 0)
    key = (event, group)
    if key not in HANDLERS:
        return ("", "", 0)
    ctx = hookio.context(event, raw, os.environ, framework_dir())
    if ctx is None:
        return ("", "", 0)
    module = importlib.import_module(HANDLERS[key])
    try:
        handle = module.handle
    except AttributeError:
        raise GateError("handler module %s has no handle" % HANDLERS[key]) from None
    if not callable(handle):
        raise GateError("handler %s.handle is not callable" % HANDLERS[key])
    outcome = handle(ctx)
    if not _outcome_ok(outcome):
        raise GateError("handler %s.handle returned a bad outcome" % HANDLERS[key])
    return hookio.render(event, outcome)


def _write(stream: object, text: str) -> None:
    if text:
        stream.write(text)
        stream.flush()


def _silence(stream: object) -> None:
    """Point the file descriptor under ``stream``, whose write or flush just failed, at the null device: the text left
    in its buffer is then flushed there at interpreter shutdown, and that flush cannot fail a second time (a failed
    shutdown flush gives exit status 120 and an ``Exception ignored`` message on the other stream)."""
    try:
        fd = stream.fileno()
        null = os.open(os.devnull, os.O_WRONLY)
        try:
            os.dup2(null, fd)
        finally:
            os.close(null)
    except BaseException:
        pass


def main(argv: List[str]) -> int:
    if type(argv) is not list or len(argv) != 1 or type(argv[0]) is not str or argv[0] not in hookio.EVENTS:
        sys.stderr.write(USAGE + "\n")
        return 2
    event = argv[0]
    try:
        data = sys.stdin.buffer.read()
        stdout, stderr, code = _handle(event, data)
    except BaseException as e:   # SystemExit(0) and KeyboardInterrupt from a handler must not allow
        line = fail_line(event, _reason(e), isinstance(e, hookio.InputError))
        if event == "PreToolUse":
            stdout, stderr, code = "", line + "\n", 2
        elif event in ("SessionStart", "UserPromptSubmit"):
            stdout, stderr, code = line + "\n", "", 0
        else:
            stdout, stderr, code = "", "", 0
    stream = None
    try:
        stream = sys.stdout
        _write(stream, stdout)
        stream = sys.stderr
        _write(stream, stderr)
    except BaseException:
        _silence(stream)
        return 2 if event == "PreToolUse" else 0
    return code

