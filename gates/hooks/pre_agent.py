"""PreToolUse handler for the Agent tool (Task 3c.2, plan P:3897-3970): runs ``gate_dispatch`` for one dispatch with the
dispatcher, the live counts and ``program_live`` the hook measured, binds the child's worktree (ruling (3c)), and records
the dispatch in the session store so a later dispatch from that child finds its depth and worktree.

The hook holds the session lock for the whole call. It refuses with exit 2 (the entry renders ``Outcome.deny``); a pass
prints only the ``PASS dispatch.in-force.*`` lines as context. Every hook-originated FAIL line ends with its way out
(Ruling R2, spec section 4); the gate's own lines pass through verbatim. Standard library only."""
from __future__ import annotations

import json
import os
import tempfile
from typing import Optional

from gates import gate_dispatch
from gates.lib import dispatch, gitinfo, programs, session, transcript, worktrees
from gates.lib.hookio import HookContext, Outcome
from gates.lib.result import GateError, run_check, safe_text

WAY_OUT = "; the human can disable the plugin with /plugin until a fix merges, and !-prefixed commands still run"
_IN_FORCE = "PASS dispatch.in-force."
_PREFIX = "worktree: "


def _record(ctx: HookContext, state: Optional[dict]) -> Optional[tuple]:
    """``(role, depth, worktree, branch)`` of the record for the subagent this hook fires in (found by the SHA of the
    first prompt of its own transcript, M3), else ``None``: no store, no readable prompt, no record, an ambiguous one."""
    if type(state) is not dict or ctx.agent_id is None:
        return None
    prompt = transcript.first_prompt(transcript.own_transcript(ctx))
    if prompt is None:
        return None
    try:
        sha = session.prompt_sha(prompt)
    except (TypeError, UnicodeEncodeError):
        return None
    return session.lookup(state, sha)


def dispatcher(ctx: HookContext, state: Optional[dict]) -> Optional[dict]:
    """The dispatcher the gate input names (``id``, ``depth``, ``live_children``, ``live_total``), or ``None`` when
    the store is unavailable (``state`` ``None``) or the agent's record is missing or ambiguous. The counts are built
    from ``len`` so each is a plain ``int``."""
    if type(state) is not dict:
        return None
    if ctx.agent_id is None:
        who, role, depth = "session", "session", 0
    else:
        found = _record(ctx, state)
        if found is None:
            return None
        who, role, depth = ctx.agent_id, found[0], found[1]
    return {"id": role, "depth": depth, "live_children": session.live_children(state, who),
            "live_total": session.live_total(state)}


def _program_live(ctx: HookContext) -> Optional[bool]:
    try:
        return bool(programs.live_programs(ctx.root, ctx.cfg))
    except GateError:
        return None


def _role(prompt: str) -> Optional[str]:
    try:
        return dispatch.role_of(dispatch.parse(prompt)[0]["Role"])
    except (ValueError, KeyError):
        return None


def _task_lines(prompt: str) -> tuple:
    """``(matching, malformed)``: the lines of the ``## Task`` body (split on LF only) that read ``worktree: /...``,
    and those that start ``worktree:`` but do not (Q2)."""
    body = dispatch.parse(prompt)[0].get("Task")
    if body is None:
        return [], []
    match, bad = [], []
    for line in body.split("\n"):
        if line.startswith(_PREFIX + "/"):
            match.append(line[len(_PREFIX):])
        elif line.startswith("worktree:"):
            bad.append(line)
    return match, bad


def _in_group(ctx: HookContext, dispatcher_: Optional[dict], state: Optional[dict], branch: Optional[str]) -> bool:
    """Whether ``branch`` is a group branch ``<p>/<s>/<g>`` of the stream the dispatcher's record is bound to, read
    from the record's own ``branch`` field, never from the worktree now (F-B3p-20; CD7, CD8)."""
    if dispatcher_ is None or ctx.agent_id is None or not branch:
        return False
    found = _record(ctx, state)
    if found is None or not found[3]:
        return False
    try:
        mine, theirs = programs.parse_branch(found[3]), programs.parse_branch(branch)
    except ValueError:
        return False
    return (mine is not None and theirs is not None and mine[0] == "stream" and theirs[0] == "group"
            and mine[1] == theirs[1] and mine[2] == theirs[2])


def _bind(ctx: HookContext, text: str, dispatcher_: Optional[dict], state: Optional[dict]) -> tuple:
    shown = safe_text(text)
    refused = ["hook.agent.worktree: %s is not the top level of a worktree of this repository" % shown]
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return "", None, refused
    if "\0" in text:                       # before realpath: 3.9 returns a string for it, 3.13 raises (CD14)
        return "", None, refused
    real = os.path.realpath(text)
    if not worktrees.same_repository(ctx.root, real):
        return "", None, refused
    try:
        branch = worktrees.bound_branch(real)
    except GateError:
        return "", None, refused
    tops, notes = worktrees.allowed(ctx, ctx.root, ctx.cfg, state)
    if real in tops or _in_group(ctx, dispatcher_, state, branch):
        return real, branch or "", []
    fails = ["hook.agent.worktree: %s is not one of the dispatcher's worktrees" % shown]
    return "", None, fails + ["hook.agent.worktree: %s" % safe_text(n) for n in notes]


def _worktree(ctx: HookContext, prompt: str, dispatcher: Optional[dict], state: Optional[dict]) -> tuple:
    """``(path, branch, fails)`` for the dispatch ``prompt``: ``path`` the ``realpath`` of the worktree bound to the child (or
    ``""`` for none) and ``fails`` the ``hook.agent.worktree: <reason>`` lines (no ``FAIL`` prefix, no way out).

    The ``worktree:`` line is the first ``## Task`` line reading ``worktree: /<path>``; it must be the top level of a
    worktree of this repository and one of the dispatcher's allowed worktrees (or a group worktree of its stream).
    With no line and no program live the main checkout is bound when the dispatcher may hold it, else nothing; with
    a program live a worker is refused and a controller binds nothing."""
    match, bad = _task_lines(prompt)
    if len(match) > 1:
        return "", None, ["hook.agent.worktree: two worktree: lines in ## Task"]
    if bad:
        return "", None, ["hook.agent.worktree: the line must read 'worktree: <absolute path>'"]
    if match:
        return _bind(ctx, match[0], dispatcher, state)
    live = _program_live(ctx)
    if live is None or live:
        role = _role(prompt)
        if role is None or role not in dispatch.CONTROLLER_ROLES:
            return "", None, ["hook.agent.worktree: a worker in a live program names its worktree"]
        return "", None, []
    main = os.path.realpath(ctx.root)
    tops, _ = worktrees.allowed(ctx, ctx.root, ctx.cfg, state)
    return (main, None, []) if main in tops else ("", None, [])


def worktree_of(ctx: HookContext, prompt: str, dispatcher: Optional[dict], state: Optional[dict]) -> tuple:
    """``(path, fails)`` of ``_worktree``: ``path`` the ``realpath`` of the worktree bound to the child (or ``""``)
    and ``fails`` the ``hook.agent.worktree: <reason>`` lines (no ``FAIL`` prefix, no way out)."""
    path, _, fails = _worktree(ctx, prompt, dispatcher, state)
    return path, fails


def _gate(ctx: HookContext, prompt: str, disp: Optional[dict], live: Optional[bool]) -> tuple:
    """``(fail_lines, context_lines)`` of the gate run for this dispatch."""
    data = {"prompt": prompt}
    for name in ("subagent_type", "model"):
        if name in ctx.tool_input:
            data[name] = ctx.tool_input[name]
    if disp is not None:
        data["dispatcher"] = disp
    if live is not None:
        data["program_live"] = live
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "dispatch.json")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(data))
        result = run_check("dispatch", gate_dispatch.check, ["--root", ctx.root, "--input", path])
    lines = [ln for ln in result.render(False).split("\n") if ln != ""]
    return [ln for ln in lines if ln.startswith("FAIL ")], [ln for ln in lines if ln.startswith(_IN_FORCE)]


def _decide(ctx: HookContext, prompt: str, required: bool, state: Optional[dict], store_error: Optional[str]) -> Outcome:
    disp = dispatcher(ctx, state)
    fails, context = [], []
    if required:
        fails, context = _gate(ctx, prompt, disp, _program_live(ctx))
    path, branch, wfails = _worktree(ctx, prompt, disp, state)
    deny = list(fails) + ["FAIL %s%s" % (f, WAY_OUT) for f in wfails]
    if store_error is not None and required:
        deny.append("FAIL hook.agent.session: %s%s" % (safe_text(store_error), WAY_OUT))
    if deny:
        return Outcome(deny=deny)
    if disp is None:
        if required:
            return Outcome(deny=["FAIL hook.agent.dispatcher: the dispatcher is unknown and the gate passed it%s" % WAY_OUT])
        return Outcome()                   # no gate applies and no count to base a record on (plan step 5)
    role = _role(prompt) or "unknown"
    if path and branch is None:            # no line: the main checkout is read here; with a line it was read in _bind
        branch = worktrees.bound_branch(path) or ""   # the branch is read once per dispatch, never again (F-B3p-20)
    branch = branch or ""
    session.add_dispatch(state, session.prompt_sha(prompt), role, disp["depth"] + 1, ctx.agent_id or "session", path,
                         branch)
    return Outcome(context=context)


def handle(ctx: HookContext) -> Outcome:
    if ctx.cfg_error is not None or ctx.cfg is None:
        return Outcome(deny=["FAIL hook.agent.config: %s; fix .strict-delivery/config.yml%s"
                             % (ctx.cfg_error, WAY_OUT)])
    prompt = ctx.tool_input.get("prompt")
    usable = type(prompt) is str
    if usable:
        try:
            prompt.encode("utf-8")
        except UnicodeEncodeError:
            usable = False
    if not usable:
        return Outcome(deny=["FAIL hook.agent.prompt: the Agent call has no usable prompt (a str that encodes as UTF-8)%s"
                             % WAY_OUT])
    required = dispatch.required(ctx.root, ctx.cfg)
    entered = done = False
    outcome = None
    try:
        with session.locked(ctx.env, ctx.session_id) as state:
            entered = True
            outcome = _decide(ctx, prompt, required, state, None)
            done = True
    except session.SessionUnavailable as e:
        if entered and not done:
            raise
        if done:                           # the write on lock exit failed: the count would be lost (Q5)
            return Outcome(deny=["FAIL hook.agent.session: %s%s" % (safe_text(e), WAY_OUT)])
        return _decide(ctx, prompt, required, None, str(e))
    return outcome
