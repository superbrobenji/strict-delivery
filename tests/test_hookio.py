"""Tests of gates.lib.hookio (Task 3a.2 input-domain rows F1b, I*, R*, O*). Expected values are written by hand from the
plan (P:3450-3460) and the table, never read back from the code."""
import dataclasses
import json
import os
import subprocess
import typing
import unittest
from typing import Mapping, Optional
from unittest import mock

from gates.lib import hookio
from gates.lib.result import GateError
from tests import hookrun
from tests.helpers import GitIsolatedTestCase, git, make_repo


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



# ---------------------------------------------------------------- parse (rows I1-I19)

def pl(event="PreToolUse", **fields):
    return hookrun.payload(event, "/work/r", **fields)


def enc(obj):
    return json.dumps(obj).encode("utf-8")


def without(obj, *keys):
    return {k: v for k, v in obj.items() if k not in keys}


def raw_with(obj, extra_text):
    """``obj`` as JSON bytes with ``extra_text`` (a raw ``"key": value`` fragment) added as the last member."""
    return (json.dumps(obj)[:-1] + ", " + extra_text + "}").encode("utf-8")


def raw_tool_input(obj, text):
    """``obj`` with its ``tool_input`` member replaced by the raw JSON text ``text``."""
    return (json.dumps(without(obj, "tool_input"))[:-1] + ', "tool_input": ' + text + "}").encode("utf-8")


def refusals():
    """(event, bytes) pairs, each refused by ``parse``."""
    base = pl()
    valid = enc(base)
    cases = [
        ("I1", "PreToolUse", b""),
        ("I2", "PreToolUse", b"\xff{}"),
        ("I2", "PreToolUse", b"\xed\xa0\x80"),
        ("I3", "PreToolUse", b"\xef\xbb\xbf" + valid),
        ("I4", "PreToolUse", b"{"),
        ("I4", "PreToolUse", b"x"),
        ("I4", "PreToolUse", valid + b" x"),
        ("I5", "PreToolUse", b"[]"),
        ("I5", "PreToolUse", b'"s"'),
        ("I5", "PreToolUse", b"1"),
        ("I5", "PreToolUse", b"null"),
        ("I6", "PreToolUse", raw_with(base, '"session_id": "z"')),
        ("I6", "PreToolUse", raw_tool_input(base, '{"a": 1, "a": 2}')),
        ("I6", "PreToolUse", raw_tool_input(base, '{"a": {"b": 1, "b": 2}}')),
        ("I6", "PreToolUse", raw_tool_input(base, '[{"a": 1, "a": 2}]')),
        ("I7", "PreToolUse", raw_with(base, '"z": NaN')),
        ("I7", "PreToolUse", raw_with(base, '"z": Infinity')),
        ("I7", "PreToolUse", raw_with(base, '"z": -Infinity')),
        ("I7", "PreToolUse", raw_tool_input(base, '{"x": [NaN]}')),
        ("I8", "PreToolUse", enc(without(base, "hook_event_name"))),
        ("I8", "PreToolUse", enc(pl(hook_event_name="SessionStart"))),
        ("I8", "PreToolUse", enc(pl(hook_event_name="pretooluse"))),
        ("I8", "PreToolUse", enc(pl(hook_event_name=1))),
        ("I9", "PreToolUse", enc(without(base, "session_id"))),
        ("I16", "PreToolUse", raw_with(base, '"n": ' + "1" * 4301)),
        ("I16", "PreToolUse", raw_with(base, '"n": -' + "1" * 4301)),
    ]
    for v in ("", "a b", "a/b", "a\n", "a" * 129, 1, None, ["a"]):
        cases.append(("I9", "PreToolUse", enc(pl(session_id=v))))
    for v in ("", "a/b", "./a", 1, None, "/a\u0000b", ["/a"]):
        cases.append(("I10", "PreToolUse", enc(pl(cwd=v))))
    cases.append(("I10", "PreToolUse", enc(without(base, "cwd"))))
    cases.append(("I10", "PreToolUse", raw_with(without(base, "cwd"), '"cwd": "\\ud800"')))
    for ev in ("PreToolUse", "PostToolUse"):
        p = pl(ev)
        cases += [("I11", ev, enc(without(p, "tool_name"))), ("I11", ev, enc(pl(ev, tool_name=1))),
                  ("I11", ev, enc(pl(ev, tool_name=None))), ("I11", ev, enc(without(p, "tool_input"))),
                  ("I11", ev, enc(pl(ev, tool_input=[]))), ("I11", ev, enc(pl(ev, tool_input="s"))),
                  ("I11", ev, enc(pl(ev, tool_input=None)))]
    for v in (None, "", "a b", "a/b", "..", "a" * 129, 1):
        cases.append(("I13", "PreToolUse", enc(pl(agent_id=v))))
    for v in (1, []):
        cases.append(("I14", "PreToolUse", enc(pl(transcript_path=v))))
    return cases


class ParseTest(unittest.TestCase):
    def test_parse_refuses(self):   # I1-I11, I13, I14, I16
        for row, event, data in refusals():
            with self.subTest(row=row, data=data[:60]):
                with self.assertRaises(GateError) as cm:
                    hookio.parse(event, data)
                self.assertTrue(str(cm.exception).startswith("hook.input: "), str(cm.exception))

    def test_parse_refusal_texts(self):   # exact reasons written by hand (V4: json text per interpreter)
        table = [
            (b"", "hook.input: input is not valid JSON: Expecting value: line 1 column 1 (char 0)"),
            (b"x", "hook.input: input is not valid JSON: Expecting value: line 1 column 1 (char 0)"),
            (b"{", "hook.input: input is not valid JSON: Expecting property name enclosed in double quotes: line 1 column 2 (char 1)"),
            (b"{} x", "hook.input: input is not valid JSON: Extra data: line 1 column 4 (char 3)"),
            (b"\xff{}", "hook.input: input is not valid UTF-8"),
            (b"[]", "hook.input: input must be a JSON object"),
            (b"\xef\xbb\xbf{}", "hook.input: input is not valid JSON: Unexpected UTF-8 BOM (decode using utf-8-sig): line 1 column 1 (char 0)"),
            (raw_with(pl(), '"a": 1, "a": 2'), "hook.input: input is not valid JSON: duplicate key 'a'"),
            (raw_with(pl(), '"z": NaN'), "hook.input: input is not valid JSON: constant 'NaN' is not allowed"),
        ]
        for data, text in table:
            with self.subTest(data=data[:40]):
                with self.assertRaises(GateError) as cm:
                    hookio.parse("PreToolUse", data)
                self.assertEqual(str(cm.exception), text)

    def test_parse_accepts(self):   # accepted values of I9, I10, I13, I14
        for fields in ({"session_id": "a" * 128}, {"session_id": "A_b-9"}, {"cwd": "/"}, {"cwd": "/a b/é"},
                       {"agent_id": "a-1"}, {"agent_id": "a" * 128}, {"transcript_path": None}, {"transcript_path": "rel/x"},
                       {"agent_type": ""}):
            with self.subTest(fields=fields):
                raw = hookio.parse("PreToolUse", enc(pl(**fields)))
                for k, v in fields.items():
                    self.assertEqual(raw[k], v)
        absent = hookio.parse("PreToolUse", enc(without(pl(), "transcript_path")))
        self.assertNotIn("transcript_path", absent)
        self.assertNotIn("agent_id", absent)

    def test_parse_digit_limit(self):   # I16, V1: 4300 accepted, 4301 refused on both interpreters
        raw = hookio.parse("PreToolUse", raw_with(pl(), '"n": ' + "1" * 4300))
        self.assertEqual(raw["n"], int("1" * 4300))
        for text in ("1" * 4301, "-" + "1" * 4301):
            with self.subTest(len=len(text)):
                with self.assertRaises(GateError) as cm:
                    hookio.parse("PreToolUse", raw_with(pl(), '"n": ' + text))
                self.assertEqual(str(cm.exception),
                                 "hook.input: input is not valid JSON: integer longer than 4300 digits")

    def test_parse_overflow_floats_refused(self):   # I7, V8: an overflowing literal is refused like NaN, same text
        literals = ("1e400", "-1e400", "1E400", "1e+400", "1" + "0" * 400 + ".0", "-1" + "0" * 400 + ".0")
        for lit in literals:
            for where, make in (("top", lambda t: raw_with(pl(), '"z": ' + t)),
                                ("tool_input", lambda t: raw_tool_input(pl(), '{"x": ' + t + '}')),
                                ("list", lambda t: raw_tool_input(pl(), '{"x": [1, ' + t + ']}'))):
                with self.subTest(lit=lit[:12], where=where):
                    with self.assertRaises(GateError) as cm:
                        hookio.parse("PreToolUse", make(lit))
                    self.assertEqual(str(cm.exception), "hook.input: input is not valid JSON: number is not finite")

    def test_parse_finite_floats(self):   # I7b, V8: accepted, the value Python's float gives
        table = [("1e308", 1e308), ("-1e308", -1e308), ("1.7976931348623157e308", 1.7976931348623157e308),
                 ("1e-400", 0.0), ("-0.0", -0.0), ("0.5", 0.5),
                 ("0." + "0" * 4299 + "1", 0.0), ("0." + "0" * 4300 + "1", 0.0)]   # 4300 and 4301 digits after the point
        for text, value in table:
            with self.subTest(len=len(text), text=text[:12]):
                raw = hookio.parse("PreToolUse", raw_with(pl(), '"z": ' + text))
                self.assertEqual(str(raw["z"]), str(value))

    def test_parse_extra_fields_kept(self):   # I12, I15
        p = pl("SessionStart", tool_name="Bash", brand_new_key={"x": 1})
        raw = hookio.parse("SessionStart", enc(p))
        self.assertEqual(raw, p)
        raw = hookio.parse("PreToolUse", enc(pl(zz=[1, 2])))
        self.assertEqual(raw["zz"], [1, 2])

    def test_parse_measured_shapes(self):   # I13b, I18, I19, V6
        shapes = [("PreToolUse", {}), ("PreToolUse", {"agent_id": "a-1", "agent_type": "general-purpose"}),
                  ("PostToolUse", {}), ("SessionStart", {}), ("UserPromptSubmit", {}), ("SubagentStop", {})]
        for event, fields in shapes:
            with self.subTest(event=event, fields=fields):
                p = pl(event, **fields)
                self.assertEqual(hookio.parse(event, enc(p)), p)
        for v in ("", "general-purpose", "fork", 1):   # I13b: agent_type never validated
            with self.subTest(agent_type=v):
                self.assertEqual(hookio.parse("PreToolUse", enc(pl(agent_id="a-1", agent_type=v)))["agent_type"], v)
        absent = pl(agent_id="a-1")
        self.assertNotIn("agent_type", hookio.parse("PreToolUse", enc(absent)))
        internal = pl("SubagentStop", agent_type="", agent_transcript_path="/nonexistent/agent-x.jsonl")   # I19
        self.assertEqual(hookio.parse("SubagentStop", enc(internal)), internal)
        for event in hookio.EVENTS:   # V6: optional keys of newer versions may be missing
            for key in ("effort", "prompt_id", "scratchpad_dir", "permission_mode"):
                with self.subTest(event=event, missing=key):
                    p = without(pl(event), key)
                    self.assertEqual(hookio.parse(event, enc(p)), p)

    def test_unicode_version_lines_identical(self):   # I17, V2
        for name in ("\U0001fae0", "Ⱟ"):
            with self.subTest(name=name):
                self.assertEqual(hookio.parse("PreToolUse", enc(pl(tool_name=name)))["tool_name"], name)
        data = raw_with(pl(), '"\U0001fae0": 1, "\U0001fae0": 2')
        with self.assertRaises(GateError) as cm:
            hookio.parse("PreToolUse", data)
        self.assertEqual(str(cm.exception), "hook.input: input is not valid JSON: duplicate key '\\U0001fae0'")


# ---------------------------------------------------------------- context (rows R1-R11)

def raw_for(cwd, event="PreToolUse", **fields):
    return hookio.parse(event, enc(hookrun.payload(event, cwd, **fields)))


class ContextTest(GitIsolatedTestCase):
    def new_repo(self, name):
        path = os.path.join(self.tmp, name)
        os.makedirs(path)
        return make_repo(path)

    def ctx(self, cwd, event="PreToolUse", env=None, fw="/fw", **fields):
        return hookio.context(event, raw_for(cwd, event, **fields), os.environ if env is None else env, fw)

    def test_outside_git_is_silent(self):   # R1, R8
        bare = os.path.join(self.tmp, "bare.git")
        subprocess.run(["git", "init", "-q", "--bare", bare], check=True)
        repo = self.new_repo("r")
        plain = os.path.join(self.tmp, "plain")
        os.makedirs(plain)
        for cwd in (plain, os.path.join(self.tmp, "missing"), os.path.join(repo, ".git"), bare):
            for event in hookio.EVENTS:
                with self.subTest(cwd=cwd, event=event):
                    self.assertIsNone(self.ctx(cwd, event))

    def test_no_config_is_silent(self):   # R2
        git(self.work, "init", "-q", "-b", "main")
        self.assertIsNone(self.ctx(self.work))

    def test_subdirectory_root(self):   # R3
        repo = make_repo(self.work)
        os.makedirs(os.path.join(repo, "a", "b"))
        for cwd in (os.path.join(repo, "a", "b"), repo):
            with self.subTest(cwd=cwd):
                c = self.ctx(cwd)
                self.assertEqual(c.root, repo)
                self.assertEqual(c.cwd, cwd)

    def test_linked_worktree_root(self):   # R4
        repo = make_repo(self.work)
        wt = os.path.join(self.tmp, "wt")
        git(repo, "worktree", "add", "-q", "-b", "other", wt)
        c = self.ctx(wt)
        self.assertEqual(c.root, wt)
        self.assertEqual(c.cfg["profile"], "strict")

    def test_config_error_named(self):   # R5
        repo = make_repo(self.work)
        cfg = os.path.join(repo, ".strict-delivery", "config.yml")
        os.remove(cfg)
        with open(cfg, "w", encoding="utf-8") as fh:
            fh.write("a: [\n")
        c = self.ctx(repo)
        self.assertIsNone(c.cfg)
        self.assertEqual(c.root, repo)
        self.assertTrue(c.cfg_error and "config.yml" in c.cfg_error, c.cfg_error)
        os.remove(cfg)
        os.mkdir(cfg)
        self.assertEqual(self.ctx(repo).cfg_error, ".strict-delivery/config.yml: cannot read file (not a regular file)")
        os.rmdir(cfg)
        os.symlink("/nonexistent/zz", cfg)
        c = self.ctx(repo)
        self.assertIsNone(c.cfg)
        self.assertEqual(c.cfg_error, ".strict-delivery/config.yml: cannot read file (No such file or directory)")
        good = self.new_repo("good")
        self.assertIsNone(self.ctx(good).cfg_error)
        self.assertEqual(self.ctx(good).cfg["profile"], "strict")

    def test_inherited_git_env_ignored(self):   # R7
        a = self.new_repo("a")
        b = self.new_repo("b")
        env = dict(os.environ, GIT_DIR=os.path.join(b, ".git"), GIT_WORK_TREE=b, GIT_INDEX_FILE=os.path.join(b, ".git", "index"))
        self.assertEqual(self.ctx(a, env=env).root, a)
        with mock.patch.dict(os.environ, env):
            self.assertEqual(self.ctx(a).root, a)

    def test_root_with_space(self):   # R9
        repo = self.new_repo("re po é")
        self.assertEqual(self.ctx(repo).root, repo)

    def test_context_env_copy(self):   # R11
        repo = make_repo(self.work)
        env = {"A": "1"}
        c = self.ctx(repo, env=env)
        env["A"] = "2"
        self.assertEqual(c.env["A"], "1")
        with self.assertRaises(TypeError):
            c.env["B"] = "x"

    def test_context_fields(self):   # shape of the context for each kind of event
        repo = make_repo(self.work)
        c = self.ctx(repo, tool_input={"command": "x"}, agent_id="a-1", tool_name="Bash", fw="/fwdir")
        self.assertEqual((c.event, c.tool_name, c.tool_input, c.session_id, c.agent_id, c.framework_dir),
                         ("PreToolUse", "Bash", {"command": "x"}, "sess-1", "a-1", "/fwdir"))
        self.assertEqual(c.transcript_path, os.path.join(repo, "sess-1.jsonl"))
        self.assertIsNone(c.cfg_error)
        s = self.ctx(repo, "SessionStart", tool_name="Bash")
        self.assertEqual((s.tool_name, s.tool_input, s.agent_id), (None, {}, None))
        self.assertEqual(s.raw["tool_name"], "Bash")


# ---------------------------------------------------------------- render (rows O1-O8)

def ctx_json(text):
    return json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": text}}) + "\n"


class RenderTest(unittest.TestCase):
    def test_render_table(self):   # O1, O2, O4-O8
        O = hookio.Outcome
        table = [
            ("PreToolUse", O(deny=["FAIL a", "FAIL b"]), ("", "FAIL a\nFAIL b\n", 2)),
            ("PreToolUse", O(deny=["FAIL a"], context=["c"], text=["t"]), ("", "FAIL a\n", 2)),
            ("PreToolUse", O(text=["t"]), ("", "", 0)),
            ("PreToolUse", O(), ("", "", 0)),
            ("SessionStart", O(text=["a", "b"]), ("a\nb\n", "", 0)),
            ("UserPromptSubmit", O(text=["a", "b"]), ("a\nb\n", "", 0)),
            ("SessionStart", O(), ("", "", 0)),
            ("UserPromptSubmit", O(), ("", "", 0)),
            ("SessionStart", O(deny=["FAIL a"], context=["c"]), ("", "", 0)),
            ("UserPromptSubmit", O(deny=["FAIL a"], context=["c"]), ("", "", 0)),
            ("PostToolUse", O(deny=["FAIL a"], context=["c"], text=["t"]), ("", "", 0)),
            ("SubagentStop", O(deny=["FAIL a"], context=["c"], text=["t"]), ("", "", 0)),
            ("PostToolUse", O(), ("", "", 0)),
            ("SubagentStop", O(), ("", "", 0)),
        ]
        for event, outcome, expected in table:
            with self.subTest(event=event, outcome=outcome):
                self.assertEqual(hookio.render(event, outcome), expected)

    def test_pass_never_allows(self):   # O3
        for lines, text in ((["x"], "x"), (["x", "y"], "x\ny")):
            with self.subTest(lines=lines):
                out, err, code = hookio.render("PreToolUse", hookio.Outcome(context=lines))
                self.assertEqual((out, err, code), (ctx_json(text), "", 0))
                self.assertEqual(json.loads(out), {"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                                                          "additionalContext": text}})
                self.assertNotIn("permissionDecision", out)

    def test_render_non_ascii_escaped(self):   # O8, V2
        out, err, code = hookio.render("PreToolUse", hookio.Outcome(context=["é\U0001fae0"]))
        self.assertEqual(out, '{"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": "\\u00e9\\ud83e\\udee0"}}\n')
        self.assertEqual((err, code), ("", 0))


if __name__ == "__main__":
    unittest.main()
