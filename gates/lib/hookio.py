"""Hook input and output contract (Task 3a.2): the event names, the tool groups, the context a handler receives and the
outcome it returns (standard library only)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Optional

EVENTS = ("SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "SubagentStop")

# Measured tool names (M8, Claude Code 2.1.330: no ``Task``); ``MultiEdit`` is kept for versions that have it.
TOOL_GROUPS = {"Agent": "agent", "Bash": "bash", "Edit": "edit", "Write": "edit", "MultiEdit": "edit",
               "NotebookEdit": "edit", "Read": "read"}


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
