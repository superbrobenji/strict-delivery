"""SubagentStop handler (Task 3c.2, plan P:3922): ends the live dispatch record whose prompt SHA-256 equals that of the
first user entry of the stopped agent's transcript. It refuses nothing and prints nothing: every path returns an empty
``Outcome``; an unreadable transcript, no match or an unavailable store changes nothing. Only an absolute ``str`` path
is read (CD9). Standard library only."""
from __future__ import annotations

import os

from gates.lib import session, transcript
from gates.lib.hookio import HookContext, Outcome


def _sha(path: object):
    if type(path) is not str or path == "" or not os.path.isabs(path) or "\0" in path:
        return None
    try:
        path.encode("utf-8")
    except UnicodeEncodeError:
        return None
    prompt = transcript.first_prompt(path)
    if prompt is None:
        return None
    try:
        return session.prompt_sha(prompt)
    except (TypeError, UnicodeEncodeError):
        return None


def handle(ctx: HookContext) -> Outcome:
    sha = _sha(ctx.raw.get("agent_transcript_path"))
    if sha is None:
        return Outcome()
    try:
        with session.locked(ctx.env, ctx.session_id) as state:
            session.end_dispatch(state, sha)
    except session.SessionUnavailable:
        pass
    return Outcome()
