"""PreToolUse Bash handler (Task 3b.2): the text refusals, the git-write target check and the refusals of a git commit.

It reads only ``tool_input["command"]``, prints nothing, writes nothing in the repository (the session store is the only
write, entered once for a subagent), and builds a ``bashpolicy.Policy`` first for the hook's own root, then for the target
root that ``bashpolicy.target_root`` returns (decision CD2). Standard library only."""
from __future__ import annotations

import os
from typing import Optional

from gates.lib import config, gitinfo, session, shellscan, transcript, worktrees
from gates.lib.bashpolicy import (GIT_WRITES, INHERITED_GIT_ENV, Policy, commit_refusals, effective_words, git_call,
                                  is_git_write, target_root, text_refusals)
from gates.lib.hookio import HookContext, Outcome
from gates.lib.result import GateError, Result, safe_text
from gates.tools import githooks

_WAY = "run it with the ! prefix if you must, or ask the owner"


def _state_access(ctx: HookContext):
    """The zero-argument callable of ``Policy.state_access``: ``(tops, fails, record)`` of the caller. The session store is
    entered only for a subagent (the main session's ``allowed`` ignores the state)."""
    def access() -> tuple:
        if ctx.agent_id is None:
            tops, fails = worktrees.allowed(ctx, ctx.root, ctx.cfg, None)
            return tops, fails, None
        try:
            with session.locked(ctx.env, ctx.session_id) as state:
                tops, fails = worktrees.allowed(ctx, ctx.root, ctx.cfg, state)
                prompt = transcript.first_prompt(transcript.own_transcript(ctx))
                record = session.lookup(state, session.prompt_sha(prompt)) if prompt is not None else None
        except session.SessionUnavailable as e:
            tops, fails = worktrees.allowed(ctx, ctx.root, ctx.cfg, None)
            return tops, fails + [safe_text(e)], None
        return tops, fails, record
    return access


def _policy(ctx: HookContext, root: str, aliases: dict) -> Policy:
    if root == ctx.root:
        cfg, err = ctx.cfg, ctx.cfg_error
    else:
        cfg, err = None, None
        try:
            cfg = config.load(root)
        except GateError as e:
            err = safe_text(e)
    base = cfg["base_branch"] if cfg is not None else config.DEFAULTS["base_branch"]
    return Policy(root=root, cfg=cfg, cfg_error=err, env=ctx.env, aliases=aliases, branch=gitinfo.current_branch(root),
                  base=base, agent_key=ctx.agent_id if ctx.agent_id is not None else "session", cwd=ctx.cwd,
                  state_access=_state_access(ctx))


def _run_gates(ctx: HookContext):
    def run(root: str) -> Result:
        try:
            status = githooks.status_result(root, ctx.framework_dir)
            healthy = not any(ln.status == "FAIL" and ln.id == "githooks.pre-commit" for ln in status.lines)
        except GateError:
            healthy = False
        if healthy:
            return Result("hook.bash.gates", [])
        return githooks.pre_commit_result(root)
    return run


def _named_top(ctx: HookContext, named: Optional[str]) -> Optional[str]:
    """The git top level of the directory ``named`` (joined to ``cwd``), or ``None`` when it does not resolve."""
    if not named:
        return None
    try:
        return gitinfo.toplevel(os.path.realpath(os.path.join(ctx.cwd, named)))
    except GateError:
        return None


def _views(command: str) -> tuple:
    """The raw text and the space-joined quote-removed words (ruling R1: every text check reads both)."""
    return command, " ".join(shellscan.scan(command).words)


def _has(views: tuple, word: str, casefold: bool = False) -> bool:
    return any(shellscan.token_in(v, word, casefold) for v in views)


def _write_words(views: tuple, aliases: dict) -> bool:
    """Whether the text names a git write: a ``GIT_WRITES`` token, or an alias that resolves to a write or a write option
    (table GW11: "the subcommand is alias-resolved before the membership test", plain or not)."""
    if any(_has(views, w) for w in GIT_WRITES):
        return True
    for name in aliases:
        if _has(views, name, True):
            call = git_call(shellscan.scan("git " + name), aliases)
            if call is not None and call.sub is not None and is_git_write(call.sub, call.args):
                return True
    return False


def _git_lines(ctx: HookContext, command: str) -> list:
    scan = shellscan.scan(command)
    views = _views(command)
    aliases = dict(gitinfo.aliases(ctx.root))
    p0 = _policy(ctx, ctx.root, aliases)
    call = git_call(scan, aliases) if scan.plain else None
    named = None
    if call is not None:
        named = call.argv_C if call.argv_C is not None else scan.cd
    top = _named_top(ctx, named)
    if top is not None and top != ctx.root:
        aliases = {**aliases, **dict(gitinfo.aliases(top))}
        call = git_call(scan, aliases)
        p0 = _policy(ctx, ctx.root, aliases)
    words = effective_words(command, aliases)
    is_commit = "commit" in words
    if scan.plain:
        is_write = call is not None and call.sub is not None and is_git_write(call.sub, call.args)
    else:
        is_write = _has(views, "git", True) and _write_words(views, aliases)
    if not (is_commit or is_write):
        return []
    run = _run_gates(ctx)
    if not scan.plain:
        if is_commit:
            return commit_refusals(command, p0, run)
        if any(_has(views, w) for w in ("-C", "--git-dir", "--work-tree", "cd")):
            return ["FAIL hook.bash.target: a git write names its worktree only as one plain command "
                    "(git -C <dir> ... or cd <dir> && git ...); %s" % _WAY]
        return target_root(scan, None, p0)[1]
    if is_write and not is_commit:
        lines = [ln for ln in call.lines if not ln.startswith("FAIL hook.bash.not-git")] if call is not None else []
        for name in INHERITED_GIT_ENV:
            if name in ctx.env:
                lines.append("FAIL hook.bash.target: the hook inherited %s; %s" % (name, _WAY))
        root, fails = target_root(scan, call.argv_C if call is not None else None, p0)
        return lines + fails
    root, fails = target_root(scan, call.argv_C if call is not None else None, p0)
    if root is None:
        return fails + commit_refusals(command, p0, run, stop=True)
    return commit_refusals(command, _policy(ctx, root, aliases), run)


def handle(ctx: HookContext) -> Outcome:
    command = ctx.tool_input.get("command")
    if type(command) is not str:
        return Outcome(deny=["FAIL hook.bash.input: command must be a string; %s" % _WAY])
    deny = text_refusals(command, ctx.agent_id)
    try:
        deny += _git_lines(ctx, command)
    except GateError as e:
        # D3-1: the policy or the aliases cannot be read, so any git word may be a write: a command holding a `git`
        # token (raw or quote-removed) is refused; a command with no `git` token passes (spec §4 "fail closed")
        if _has(_views(command), "git", True):
            deny.append("FAIL hook.bash.git: %s; %s" % (safe_text(e), _WAY))
    return Outcome(deny=deny)
