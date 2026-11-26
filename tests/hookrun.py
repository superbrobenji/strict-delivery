"""Test helper: run one hook through the production entry and build measured-shape inputs (Task 3a.2, rows K1, K2).

``bash`` and ``tools`` import this module and never edit it. Values are synthetic; the key names are the ones measured
on Claude Code 2.1.330 (runtime-M1-M10)."""
import json
import os
import subprocess
import sys

FW = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_COMMON_TOOL = ("cwd", "effort", "hook_event_name", "permission_mode", "prompt_id", "scratchpad_dir", "session_id",
                "tool_input", "tool_name", "tool_use_id", "transcript_path")


def _has_hook_command() -> bool:
    from gates import __main__ as entry
    return "hook" in entry.COMMANDS


def argv_for(event: str) -> list:
    if _has_hook_command():
        return [sys.executable, "-m", "gates", "hook", event]
    return [sys.executable, "-c", "import sys, gates.hook; sys.exit(gates.hook.main(sys.argv[1:]))", event]


def run_hook(event: str, payload, env: dict, cwd: str, timeout=None) -> "subprocess.CompletedProcess":
    """Run the hook for ``event`` with ``payload`` (a dict, dumped as JSON, or bytes, sent as they are) on stdin, in the
    environment ``env`` (exactly, nothing inherited) and the process directory ``cwd`` (the framework checkout).
    The result holds ``stdout`` and ``stderr`` as text. ``timeout`` (seconds, default none): a hook still running then is
    killed and ``subprocess.TimeoutExpired`` is raised (a test bounding a call that may block, F-20261126-d2cx)."""
    data = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
    p = subprocess.run(argv_for(event), input=data, env=env, cwd=cwd, check=False, timeout=timeout,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return subprocess.CompletedProcess(p.args, p.returncode, p.stdout.decode("utf-8"), p.stderr.decode("utf-8"))


def payload(event: str, root: str, **fields) -> dict:
    """A main-session input of ``event`` with exactly the measured keys; ``fields`` override or add."""
    base = {"cwd": root, "hook_event_name": event, "scratchpad_dir": os.path.join(root, ".scratch"),
            "session_id": "sess-1", "transcript_path": os.path.join(root, "sess-1.jsonl")}
    if event in ("PreToolUse", "PostToolUse"):
        base.update({"effort": "high", "permission_mode": "default", "prompt_id": "p-1", "tool_use_id": "tu-1",
                     "tool_name": "Bash", "tool_input": {"command": "true", "description": "d"}})
        if event == "PostToolUse":
            base.update({"duration_ms": 5, "tool_response": {}})
    elif event == "SessionStart":
        base.update({"model": "m", "source": "startup"})
    elif event == "UserPromptSubmit":
        base.update({"permission_mode": "default", "prompt": "hello", "prompt_id": "p-1"})
    elif event == "SubagentStop":
        base.update({"agent_id": "a-1", "agent_transcript_path": os.path.join(root, "agent-a-1.jsonl"),
                     "agent_type": "general-purpose", "background_tasks": [], "effort": "high",
                     "last_assistant_message": "done", "permission_mode": "default", "prompt_id": "p-1",
                     "session_crons": [], "stop_hook_active": False})
    else:
        raise ValueError("unknown event")
    base.update(fields)
    return base
