"""Tests of gates.lib.hookio (Task 3a.2 input-domain rows F1b, I*, R*, O*). Expected values are written by hand from the
plan (P:3450-3460) and the table, never read back from the code."""
import dataclasses
import typing
import unittest
from typing import Mapping, Optional

from gates.lib import hookio


class A1NamesTest(unittest.TestCase):
    def test_events(self):
        self.assertEqual(hookio.EVENTS, ("SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "SubagentStop"))

    def test_tool_groups_table(self):   # F1b (M8: no Task)
        self.assertEqual(hookio.TOOL_GROUPS, {"Agent": "agent", "Bash": "bash", "Edit": "edit", "Write": "edit",
                                              "MultiEdit": "edit", "NotebookEdit": "edit", "Read": "read"})
        self.assertNotIn("Task", hookio.TOOL_GROUPS)

    def test_hook_context_fields(self):
        expected = [("event", str), ("tool_name", Optional[str]), ("tool_input", dict), ("session_id", str),
                    ("agent_id", Optional[str]), ("transcript_path", Optional[str]), ("cwd", str), ("root", str),
                    ("cfg", Optional[dict]), ("cfg_error", Optional[str]), ("framework_dir", str),
                    ("env", Mapping[str, str]), ("raw", dict)]
        self.assertTrue(dataclasses.is_dataclass(hookio.HookContext))
        hints = typing.get_type_hints(hookio.HookContext)
        self.assertEqual([(f.name, hints[f.name]) for f in dataclasses.fields(hookio.HookContext)], expected)

    def test_outcome_fields(self):
        self.assertTrue(dataclasses.is_dataclass(hookio.Outcome))
        hints = typing.get_type_hints(hookio.Outcome)
        self.assertEqual([(f.name, hints[f.name]) for f in dataclasses.fields(hookio.Outcome)],
                         [("deny", list), ("context", list), ("text", list)])

    def test_empty_outcome_has_independent_lists(self):
        a, b = hookio.Outcome(), hookio.Outcome()
        self.assertEqual((a.deny, a.context, a.text), ([], [], []))
        a.deny.append("x")
        self.assertEqual(b.deny, [])


if __name__ == "__main__":
    unittest.main()
