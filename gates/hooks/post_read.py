"""PostToolUse Read handler: registered, writes nothing until block 5 lands read receipts (controller ruling (3a))."""
from __future__ import annotations

from gates.lib.hookio import HookContext, Outcome


def handle(ctx: HookContext) -> Outcome:
    return Outcome()
