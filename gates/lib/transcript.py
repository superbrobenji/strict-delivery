"""Claude Code transcripts as the hooks read them (standard library only).

``first_prompt`` reads the text of the first user entry of a JSONL transcript; ``own_transcript`` names the
transcript of the agent a hook fires in (measured M3: inside a subagent ``transcript_path`` is the MAIN transcript, and the
subagent's own is ``<dirname(transcript_path)>/<session_id>/subagents/agent-<agent_id>.jsonl``). Every doubt gives
``None`` (fail closed), never a guess.
"""
from __future__ import annotations

import json
import os
import stat
from typing import Optional

from gates.lib import session

DEFAULT_MAX_BYTES = 4194304
MAX_DIGITS = 4300          # one verdict on every interpreter: 3.9 has no int digit limit, 3.13 stops above 4300
_CHUNK = 65536


class _Refused(Exception):
    """A transcript line that is not usable (internal)."""


def _pairs(items: list) -> dict:
    out: dict = {}
    for key, value in items:
        if key in out:
            raise _Refused("duplicate key")
        out[key] = value
    return out


def _constant(name: str) -> None:
    raise _Refused("constant " + name)


def _integer(text: str) -> int:
    if len(text.lstrip("-")) > MAX_DIGITS:
        raise _Refused("integer too long")
    return int(text)


def _parse(line: bytes) -> dict:
    try:
        obj = json.loads(line.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=_constant,
                         parse_int=_integer)
    except (UnicodeDecodeError, ValueError, RecursionError, _Refused):
        raise _Refused("not a JSON object line") from None
    if type(obj) is not dict:
        raise _Refused("not an object")
    return obj


def _text_of(entry: dict) -> Optional[str]:
    message = entry.get("message")
    if type(message) is not dict:
        return None
    content = message.get("content")
    if type(content) is str:
        text: Optional[str] = content
    elif type(content) is list:
        parts = [b["text"] for b in content
                 if type(b) is dict and b.get("type") == "text" and type(b.get("text")) is str]
        text = "".join(parts) if parts else None
    else:
        return None
    if text is not None:
        try:
            text.encode("utf-8")      # a lone surrogate cannot be hashed (session.prompt_sha); refuse it here
        except UnicodeEncodeError:
            return None
    return text


def _open_regular(path: object) -> Optional[int]:
    """A descriptor of the regular file ``path`` (symlinks followed), else ``None``; never blocks on a FIFO."""
    if type(path) is not str or path == "":
        return None
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    except (OSError, ValueError):
        return None
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            os.close(fd)
            return None
    except OSError:
        os.close(fd)
        return None
    return fd


def first_prompt(path: str, max_bytes: int = DEFAULT_MAX_BYTES) -> Optional[str]:
    """The text of the first ``type: user`` entry of the JSONL transcript ``path``: a ``str`` content, or the
    ``text`` blocks of a list content joined with ``""``. ``None`` for a path that is not a regular file (a symlink to
    one is followed), no user entry, a malformed line before it (not UTF-8, blank, not a JSON object, a duplicate
    key, ``NaN``/``Infinity``, an integer of more than 4300 digits), a user entry with no text, or an entry that does not
    end within the first ``max_bytes`` bytes (the line end counts). ``ValueError`` for a ``max_bytes`` that is not an
    ``int`` (``bool`` included) or is negative."""
    if type(max_bytes) is not int or max_bytes < 0:
        raise ValueError("max_bytes must be a non-negative int")
    fd = _open_regular(path)
    if fd is None:
        return None
    try:
        data = b""
        while len(data) < max_bytes:
            chunk = os.read(fd, min(_CHUNK, max_bytes - len(data)))
            if not chunk:
                break
            data += chunk
        end = len(data) < max_bytes or os.read(fd, 1) == b""   # the peek only tells whether the file ends here
    except OSError:
        return None
    finally:
        os.close(fd)
    lines = data.split(b"\n")
    if not end:
        lines = lines[:-1]            # the last line may continue beyond max_bytes: it never counts
    elif lines and lines[-1] == b"":
        lines = lines[:-1]            # the data ended with a line end
    for line in lines:
        try:
            entry = _parse(line)
        except _Refused:
            return None
        if entry.get("type") == "user":
            return _text_of(entry)
    return None


def own_transcript(ctx) -> Optional[str]:
    """The transcript of the agent the hook fires in, ``<dirname(transcript_path)>/<session_id>/subagents/
    agent-<agent_id>.jsonl`` (M3); ``None`` when ``agent_id`` is absent, or when ``transcript_path`` is not an absolute
    ``str`` or an id does not match ``session.SESSION_ID``. The path is returned whether or not the file exists."""
    agent_id = ctx.agent_id
    if agent_id is None:
        return None
    path, sid = ctx.transcript_path, ctx.session_id
    if type(path) is not str or path == "" or not os.path.isabs(path):
        return None
    for ident in (agent_id, sid):
        if type(ident) is not str or not session.SESSION_ID.match(ident):
            return None
    return os.path.join(os.path.dirname(path), sid, "subagents", "agent-%s.jsonl" % agent_id)
