"""UserPromptSubmit handler (Task 3a.2, plan P:3485): one reminder line on ``standard`` and ``strict``, nothing on
``light``; a config error or an unreadable skill name is a FAIL line. It refuses nothing and keeps no state."""
from __future__ import annotations

from gates.hooks.session_start import DOCTOR, skill_name
from gates.lib.hookio import HookContext, Outcome


def handle(ctx: HookContext) -> Outcome:
    if ctx.cfg is None:
        return Outcome(text=["FAIL hook.prompt-submit.config: %s%s" % (ctx.cfg_error or "the config is unavailable", DOCTOR)])
    profile = ctx.cfg["profile"]
    if profile == "light":
        return Outcome()
    name, reason = skill_name(ctx.framework_dir)
    if name is None:
        return Outcome(text=["FAIL hook.prompt-submit.skill: " + reason])
    return Outcome(text=["strict-delivery (%s): follow the %s skill; decisions are asked, never assumed" % (profile, name)])
