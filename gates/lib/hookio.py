"""Hook input and output contract (Task 3a.2): the event names, the tool groups, the context a handler receives and the
outcome it returns, the strict input parser, the root and config lookup, and the output renderer (standard library
only)."""
from __future__ import annotations

import json
import math
import os
import types
from dataclasses import dataclass, field
from typing import Mapping, Optional

from gates.lib import config, gitinfo, session
from gates.lib.result import GateError, GitNotFound, safe_text

EVENTS = ("SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "SubagentStop")

# Measured tool names (M8, Claude Code 2.1.330: no ``Task``); ``MultiEdit`` is kept for versions that have it.
TOOL_GROUPS = {"Agent": "agent", "Bash": "bash", "Edit": "edit", "Write": "edit", "MultiEdit": "edit",
               "NotebookEdit": "edit", "Read": "read"}

_TOOL_EVENTS = ("PreToolUse", "PostToolUse")
MAX_DIGITS = 4300   # one verdict on every interpreter: 3.9 has no int digit limit, 3.11+ has 4300 by default


@dataclass
class HookContext:
    event: str
    tool_name: Optional[str]
    tool_input: dict
    session_id: str
    agent_id: Optional[str]
    transcript_path: Optional[str]
    cwd: str
    root: str
    cfg: Optional[dict]
    cfg_error: Optional[str]
    framework_dir: str
    env: Mapping[str, str]
    raw: dict


@dataclass
class Outcome:
    deny: list = field(default_factory=list)
    context: list = field(default_factory=list)
    text: list = field(default_factory=list)


class InputError(GateError):
    """A refused input; the message is already escaped (one line), so the entry does not escape it again."""


def _bad(reason: str) -> InputError:
    return InputError("hook.input: " + reason)


def _pairs(pairs: list) -> dict:
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError("duplicate key '%s'" % key)
        out[key] = value
    return out


def _constant(name: str) -> None:
    raise ValueError("constant '%s' is not allowed" % name)


def _integer(text: str) -> int:
    if len(text.lstrip("-")) > MAX_DIGITS:
        raise ValueError("integer longer than %d digits" % MAX_DIGITS)
    return int(text)


def _float(text: str) -> float:
    value = float(text)
    if not math.isfinite(value):
        raise ValueError("number is not finite")
    return value


def _id_ok(value: object) -> bool:
    return type(value) is str and session.SESSION_ID.match(value) is not None


def parse(event: str, data: bytes) -> dict:
    """The input object of ``event`` from the stdin bytes; every departure is ``GateError("hook.input: ...")``."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise _bad("input is not valid UTF-8") from None
    try:
        raw = json.loads(text, object_pairs_hook=_pairs, parse_constant=_constant, parse_int=_integer,
                         parse_float=_float)
    except (ValueError, RecursionError) as e:
        raise _bad("input is not valid JSON: " + safe_text(e)) from None
    if type(raw) is not dict:
        raise _bad("input must be a JSON object")
    name = raw.get("hook_event_name")
    if type(name) is not str or name != event:
        raise _bad("hook_event_name must be the event named on the command line")
    if not _id_ok(raw.get("session_id")):
        raise _bad("session_id must be 1 to 128 letters, digits, '_' or '-'")
    cwd = raw.get("cwd")
    if type(cwd) is not str or not os.path.isabs(cwd) or "\0" in cwd:
        raise _bad("cwd must be an absolute path")
    try:
        cwd.encode("utf-8")
    except UnicodeEncodeError:
        raise _bad("cwd must be an absolute path") from None
    if event in _TOOL_EVENTS:
        if type(raw.get("tool_name")) is not str:
            raise _bad("tool_name must be a string")
        if type(raw.get("tool_input")) is not dict:
            raise _bad("tool_input must be an object")
    if "agent_id" in raw and not _id_ok(raw["agent_id"]):
        raise _bad("agent_id must be 1 to 128 letters, digits, '_' or '-'")
    tp = raw.get("transcript_path")
    if tp is not None and type(tp) is not str:
        raise _bad("transcript_path must be a string or null")
    return raw


def context(event: str, raw: dict, env: Mapping[str, str], framework_dir: str) -> Optional[HookContext]:
    """The handler's context, or ``None`` (a silent no-op) when ``cwd`` is not in a git work tree or its top level
    holds no ``.strict-delivery/config.yml``."""
    try:
        root = gitinfo.toplevel(raw["cwd"])
    except GitNotFound:
        raise
    except GateError:
        return None
    if not os.path.lexists(os.path.join(root, config.CONFIG_PATH)):
        return None
    cfg, cfg_error = None, None
    try:
        cfg = config.load(root)
    except GateError as e:
        cfg_error = safe_text(e)
    tool = event in _TOOL_EVENTS
    return HookContext(
        event=event,
        tool_name=raw["tool_name"] if tool else None,
        tool_input=raw["tool_input"] if tool else {},
        session_id=raw["session_id"],
        agent_id=raw.get("agent_id"),
        transcript_path=raw.get("transcript_path"),
        cwd=raw["cwd"],
        root=root,
        cfg=cfg,
        cfg_error=cfg_error,
        framework_dir=framework_dir,
        env=types.MappingProxyType(dict(env)),
        raw=raw)


def render(event: str, outcome: Outcome) -> tuple:
    """``(stdout, stderr, code)`` for ``outcome`` on ``event``."""
    if event == "PreToolUse":
        if outcome.deny:
            return ("", "\n".join(outcome.deny) + "\n", 2)
        if outcome.context:
            body = {"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                           "additionalContext": "\n".join(outcome.context)}}
            return (json.dumps(body) + "\n", "", 0)
        return ("", "", 0)
    if event in ("SessionStart", "UserPromptSubmit") and outcome.text:
        return ("\n".join(outcome.text) + "\n", "", 0)
    return ("", "", 0)
