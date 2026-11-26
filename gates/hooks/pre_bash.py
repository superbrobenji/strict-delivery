"""PreToolUse Bash handler (Task 3b.2): the text refusals, the git-write target check and the refusals of a git commit.

It reads only ``tool_input["command"]``, prints nothing, writes nothing in the repository (the session store is the only
write, entered once for a subagent), and builds a ``bashpolicy.Policy`` first for the hook's own root, then for the target
root that ``bashpolicy.target_root`` returns (decision CD2). Standard library only."""
from __future__ import annotations

import os
from typing import Optional

from gates.lib import config, gitinfo, session, shellscan, transcript, worktrees
from gates.lib.bashpolicy import (INHERITED_GIT_ENV, Policy, c_option_in_text, commit_refusals, effective_words,
                                  expansion_c_option, git_call, is_git_write, shell_alias_texts, target_root, text_refusals,
                                  write_text_refusals)
from gates.lib.hookio import HookContext, Outcome
from gates.lib.result import GateError, Result, safe_text
from gates.tools import githooks

_WAY = "run it with the ! prefix if you must, or ask the owner"
_C_OPTION = "FAIL hook.bash.global-option.-c: git option -c before the subcommand is refused; %s" % _WAY  # bashpolicy.py:386's format


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


def _inherited_lines(ctx: HookContext) -> list:
    """Ruling R3-4 (F-20261126-xevm): a line for each of ``GIT_INDEX_FILE``, ``GIT_DIR`` and ``GIT_WORK_TREE`` the hook
    inherited (an inherited variable reaches the Bash tool too: the target of a write cannot be checked), on every branch
    that judges a git write."""
    return ["FAIL hook.bash.target: the hook inherited %s; %s" % (name, _WAY) for name in INHERITED_GIT_ENV if name in ctx.env]


def _c_option(scan, call, other_program: bool, command: str, aliases: dict) -> bool:
    """Ruling N1 (F-20261126-2z9y): whether ``git -c`` is in play. A plain git command: its global options (before the
    subcommand, after alias resolution) hold ``-c``, or a ``!`` body it reaches holds a whole token ``-c`` after ``git``. Any
    other text (not plain, or a program that is not git): a whole token ``-c`` after a ``git`` token, either view."""
    if scan.plain and not other_program:
        return call is not None and (any(ln.startswith("FAIL hook.bash.global-option.-c:") for ln in call.lines)
                                     or expansion_c_option(call)
                                     or any(c_option_in_text(t) for t in shell_alias_texts(call, aliases)))
    return c_option_in_text(command)


def _git_lines(ctx: HookContext, command: str) -> list:
    scan = shellscan.scan(command)
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
    # A plain command whose program is not git (`bash -c 'git -C X reset --hard'`, `zsh -c '...'`, `env -S '...'`) runs a
    # text this hook cannot parse: its git words are read as the text of a non-plain command is (ruling (3b) on text
    # checks: "a command that mentions `git` with ... is refused unless it is exactly one plain simple command whose
    # program is `git`"; decision Q3 for the target of a non-plain write).
    other_program = scan.plain and call is not None and any(ln.startswith("FAIL hook.bash.not-git") for ln in call.lines)
    rule = write_text_refusals(command, aliases, p0.agent_key)
    if rule:
        # RULE-A (Q-HK5-1 (a), T:690): a git write in text that is not one plain git command is refused for every actor,
        # with no target step; the lines in the order of CDP2: the U1 not-git line of a refused env wrapper, the inherited
        # GIT_* lines (ruling R3-4), the -c line (ruling N1), the compound write line
        env_lines = []
        if call is not None and call.env_refused:
            env_lines = [ln for ln in call.lines if ln.startswith("FAIL hook.bash.not-git")]
        c_line = [_C_OPTION] if _c_option(scan, call, other_program, command, aliases) else []
        return env_lines + _inherited_lines(ctx) + c_line + [ln for ln in rule if ln != _C_OPTION]
    lines = _judged(ctx, command, scan, aliases, p0, call)
    if _c_option(scan, call, other_program, command, aliases) and _C_OPTION not in lines:
        lines.append(_C_OPTION)   # N1: on every git command, after the lines it gets otherwise
    return lines


def _judged(ctx: HookContext, command: str, scan, aliases: dict, p0: Policy, call) -> list:
    """The lines of the commit and write judgment of ``command`` (``[]`` for a command that is neither). A text that is not
    one plain git command is judged here for ``commit`` only: its writes are RULE-A's (``write_text_refusals``)."""
    words = effective_words(command, aliases)
    is_commit = "commit" in words
    is_write = scan.plain and call is not None and call.sub is not None and is_git_write(call.sub, call.args)
    if not (is_commit or is_write):
        return []
    run = _run_gates(ctx)
    if not scan.plain:
        return commit_refusals(command, p0, run)
    if is_write and not is_commit:
        lines = [ln for ln in call.lines if not ln.startswith("FAIL hook.bash.not-git")] if call is not None else []
        lines += _inherited_lines(ctx)
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
