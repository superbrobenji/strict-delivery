"""Tests of ``python3 -m gates hook`` (Task 3a.2 rows A, F, J, K, PR1 and the input rows through ``hook.main``) and of
``hooks/hooks.json``. Every run goes through ``tests/hookrun.py``, the production entry. Expected lines are written by
hand from the plan and the table. Patched handler modules are fixtures in a temporary package on PYTHONPATH of the
subprocess (a ``sitecustomize`` that edits ``gates.hook.HANDLERS`` before the entry runs), never files in the tree."""
import contextlib
import hashlib
import io
import json
import os
import subprocess
import sys
import unittest
from unittest import mock

from gates import hook
from gates.lib import hookio
from tests import hookrun
from tests.hookrun import FW, payload, run_hook
from tests.helpers import GitIsolatedTestCase, git, make_repo

TAIL = "; the strict-delivery hook fails closed; the human can disable the plugin with /plugin, and !-prefixed commands still run"
USAGE = "FAIL hook.usage: python3 -m gates hook <Event>; events: SessionStart, UserPromptSubmit, PreToolUse, PostToolUse, SubagentStop\n"


def fc(event, reason):
    return "FAIL hook.%s: %s%s" % (event, reason, TAIL)


FIXTURE_MODULES = {
    "ok_context": "from gates.lib.hookio import Outcome\ndef handle(ctx):\n    return Outcome(context=['x'])\n",
    "ok_text": "from gates.lib.hookio import Outcome\ndef handle(ctx):\n    return Outcome(text=['t1', 't2'])\n",
    "ok_deny": "from gates.lib.hookio import Outcome\ndef handle(ctx):\n    return Outcome(deny=['FAIL a', 'FAIL b'], context=['c'])\n",
    "ok_empty": "from gates.lib.hookio import Outcome\ndef handle(ctx):\n    return Outcome()\n",
    "no_handle": "x = 1\n",
    "not_callable": "handle = 1\n",
    "raises_exception": "def handle(ctx):\n    raise Exception('boom')\n",
    "raises_gate": "from gates.lib.result import GateError\ndef handle(ctx):\n    raise GateError('gate says no')\n",
    "raises_kbd": "def handle(ctx):\n    raise KeyboardInterrupt()\n",
    "raises_exit0": "def handle(ctx):\n    raise SystemExit(0)\n",
    "raises_beg": ("import builtins\n"
                   "def handle(ctx):\n"
                   "    if hasattr(builtins, 'BaseExceptionGroup'):\n"
                   "        raise builtins.BaseExceptionGroup('g', [KeyboardInterrupt()])\n"
                   "    class Stand(BaseException):\n        pass\n"
                   "    raise Stand('g')\n"),
    "raises_eg": ("import builtins\n"
                  "def handle(ctx):\n"
                  "    if hasattr(builtins, 'ExceptionGroup'):\n"
                  "        raise builtins.ExceptionGroup('g', [ValueError('v')])\n"
                  "    raise ValueError('g')\n"),
    "returns_none": "def handle(ctx):\n    return None\n",
    "returns_dict": "def handle(ctx):\n    return {'deny': []}\n",
    "returns_subclass": "from gates.lib.hookio import Outcome\nclass Sub(Outcome):\n    pass\ndef handle(ctx):\n    return Sub()\n",
    "deny_nonstr": "from gates.lib.hookio import Outcome\ndef handle(ctx):\n    return Outcome(deny=[1])\n",
    "deny_tuple": "from gates.lib.hookio import Outcome\ndef handle(ctx):\n    return Outcome(deny=('FAIL a',))\n",
    "context_nonlist": "from gates.lib.hookio import Outcome\ndef handle(ctx):\n    return Outcome(context='x')\n",
    "weird_reason": "from gates.lib.result import GateError\ndef handle(ctx):\n    raise GateError('a\\nb\\x07\\U0001fae0\\u2c2f')\n",
    "show_root": "from gates.lib.hookio import Outcome\ndef handle(ctx):\n    return Outcome(context=[ctx.root], text=[ctx.root])\n",
    "show_fw": "from gates.lib.hookio import Outcome\ndef handle(ctx):\n    return Outcome(context=[ctx.framework_dir], text=[ctx.framework_dir])\n",
    "show_env": ("from gates.lib.hookio import Outcome\n"
                 "def handle(ctx):\n"
                 "    try:\n        ctx.env['ZZ'] = '1'\n        r = 'writable'\n"
                 "    except TypeError:\n        r = 'read-only'\n"
                 "    return Outcome(context=[r + ' ' + ctx.env.get('HOOK_ENV_PROBE', '-')])\n"),
}

SITE = ("import json, os, sys\n"
        "spec = os.environ.get('HOOKTEST_HANDLERS')\n"
        "if spec:\n"
        "    import gates.hook as h\n"
        "    for k, v in json.loads(spec).items():\n"
        "        e, g = k.split('|')\n"
        "        h.HANDLERS[(e, g or None)] = v\n"
        "if os.environ.get('HOOKTEST_BREAK'):\n"
        "    class Broken:\n"
        "        def write(self, s):\n            raise BrokenPipeError('closed')\n"
        "        def flush(self):\n            pass\n"
        "    sys.stdout = Broken()\n    sys.stderr = Broken()\n")


class EntryCase(GitIsolatedTestCase):
    """A fixture repository, a fixture handler package and a plugin-data directory per test."""

    def setUp(self):
        super().setUp()
        self.repo = os.path.join(self.work, "repo")
        os.makedirs(self.repo)
        make_repo(self.repo)
        self.fx = os.path.join(self.tmp, "fx")
        os.makedirs(os.path.join(self.fx, "fxh"))
        with open(os.path.join(self.fx, "sitecustomize.py"), "w", encoding="utf-8") as fh:
            fh.write(SITE)
        with open(os.path.join(self.fx, "fxh", "__init__.py"), "w", encoding="utf-8") as fh:
            fh.write("")
        for name, src in FIXTURE_MODULES.items():
            with open(os.path.join(self.fx, "fxh", name + ".py"), "w", encoding="utf-8") as fh:
                fh.write(src)
        self.data = os.path.join(self.tmp, "plugin-data")
        os.makedirs(self.data)

    def env(self, patch=None, **extra):
        e = {"PATH": os.environ["PATH"], "HOME": os.environ["HOME"], "GIT_CONFIG_NOSYSTEM": "1",
             "GIT_CONFIG_GLOBAL": "/dev/null", "LC_ALL": "C", "CLAUDE_PLUGIN_DATA": self.data}
        if patch:
            e["PYTHONPATH"] = self.fx + os.pathsep + FW
            e["HOOKTEST_HANDLERS"] = json.dumps({k: "fxh." + v for k, v in patch.items()})
        e.update(extra)
        return e

    def run_h(self, event, data=None, patch=None, cwd=FW, **extra):
        if data is None:
            data = payload(event, self.repo)
        return run_hook(event, data, self.env(patch, **extra), cwd)


def key(event, group=None):
    return "%s|%s" % (event, group or "")


class ArgvTest(EntryCase):
    def test_argv_usage(self):   # A1, A2, A3, A5: stdin is not read, argv not echoed
        cases = [[], ["X"], ["sessionstart"], ["Stop"], [""], ["PreToolUse", "x"], ["SessionStart", "--"],
                 ["X\U0001fae0"], ["PreToolUse", "PreToolUse"]]
        for argv in cases:
            with self.subTest(argv=argv):
                p = subprocess.run([sys.executable, "-m", "gates", "hook"] + argv, cwd=FW, env=self.env(), check=False,
                                   stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                self.assertEqual((p.returncode, p.stdout, p.stderr), (2, b"", USAGE.encode("utf-8")))

    def test_argv_usage_in_process(self):   # A1: stdin is not read
        class Boom:
            @property
            def buffer(self):
                raise AssertionError("stdin was read")
        err = io.StringIO()
        with mock.patch.object(sys, "stdin", Boom()), contextlib.redirect_stderr(err):
            self.assertEqual(hook.main([]), 2)
        self.assertEqual(err.getvalue(), USAGE)

    def test_each_event_routes(self):   # A4: every event reaches its handler and is rendered by its rules
        patch = {key("SessionStart"): "ok_text", key("UserPromptSubmit"): "ok_text", key("PreToolUse", "bash"): "ok_context",
                 key("PostToolUse", "read"): "ok_text", key("SubagentStop"): "ok_text"}
        expected = {"SessionStart": ("t1\nt2\n", "", 0), "UserPromptSubmit": ("t1\nt2\n", "", 0),
                    "PreToolUse": (json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": "x"}}) + "\n", "", 0),
                    "PostToolUse": ("", "", 0), "SubagentStop": ("", "", 0)}
        for event in hookio.EVENTS:
            with self.subTest(event=event):
                data = payload(event, self.repo)
                if event == "PostToolUse":
                    data["tool_name"] = "Read"
                p = self.run_h(event, data, patch)
                self.assertEqual((p.stdout, p.stderr, p.returncode), expected[event])


class SilentTest(EntryCase):
    def test_no_config_is_silent(self):   # R2, spec section 4
        bare = os.path.join(self.tmp, "bare")
        os.makedirs(bare)
        git(bare, "init", "-q", "-b", "main")
        for event in hookio.EVENTS:
            with self.subTest(event=event):
                p = self.run_h(event, payload(event, bare, tool_name="Bash", tool_input={"command": "git commit --no-verify"}))
                self.assertEqual((p.returncode, p.stdout, p.stderr), (0, "", ""))

    def test_outside_git_is_silent(self):   # R1, R8
        plain = os.path.join(self.tmp, "plain")
        os.makedirs(plain)
        for cwd in (plain, os.path.join(self.tmp, "missing"), os.path.join(self.repo, ".git")):
            for event in hookio.EVENTS:
                with self.subTest(cwd=cwd, event=event):
                    p = self.run_h(event, payload(event, cwd))
                    self.assertEqual((p.returncode, p.stdout, p.stderr), (0, "", ""))

    def test_unknown_tool_silent(self):   # F7
        for name in ("Task", "Glob", "ToolSearch", "SubagentHandback", "agent", "bash", ""):
            with self.subTest(tool=name):
                p = self.run_h("PreToolUse", payload("PreToolUse", self.repo, tool_name=name))
                self.assertEqual((p.returncode, p.stdout, p.stderr), (0, "", ""))

    def test_claude_project_dir_ignored(self):   # R6
        other = os.path.join(self.tmp, "other")
        os.makedirs(other)
        make_repo(other)
        patch = {key("PreToolUse", "bash"): "show_root"}
        p = self.run_h("PreToolUse", patch=patch, cwd=other, CLAUDE_PROJECT_DIR=other, PYTHONPATH=self.fx + os.pathsep + FW)
        self.assertEqual(p.returncode, 0)
        self.assertEqual(json.loads(p.stdout)["hookSpecificOutput"]["additionalContext"], self.repo)

    def test_inherited_git_env_ignored(self):   # R7
        other = os.path.join(self.tmp, "other")
        os.makedirs(other)
        make_repo(other)
        patch = {key("PreToolUse", "bash"): "show_root"}
        p = self.run_h("PreToolUse", patch=patch, GIT_DIR=os.path.join(other, ".git"), GIT_WORK_TREE=other,
                       GIT_INDEX_FILE=os.path.join(other, ".git", "index"))
        self.assertEqual(json.loads(p.stdout)["hookSpecificOutput"]["additionalContext"], self.repo)

    def test_subdirectory_root(self):   # R3 through the entry
        sub = os.path.join(self.repo, "a", "b")
        os.makedirs(sub)
        p = self.run_h("PreToolUse", payload("PreToolUse", sub), {key("PreToolUse", "bash"): "show_root"})
        self.assertEqual(json.loads(p.stdout)["hookSpecificOutput"]["additionalContext"], self.repo)

    def test_linked_worktree_root(self):   # R4 through the entry
        wt = os.path.join(self.tmp, "wt")
        git(self.repo, "worktree", "add", "-q", "-b", "other", wt)
        p = self.run_h("PreToolUse", payload("PreToolUse", wt), {key("PreToolUse", "bash"): "show_root"})
        self.assertEqual(json.loads(p.stdout)["hookSpecificOutput"]["additionalContext"], wt)

    def test_root_with_space(self):   # R9
        odd = os.path.join(self.tmp, "re po é")
        os.makedirs(odd)
        make_repo(odd)
        p = self.run_h("PreToolUse", payload("PreToolUse", odd), {key("PreToolUse", "bash"): "show_root"})
        self.assertEqual(json.loads(p.stdout)["hookSpecificOutput"]["additionalContext"], odd)

    def test_config_error_named(self):   # R5: not silent; the handler sees cfg_error
        cfg = os.path.join(self.repo, ".strict-delivery", "config.yml")
        os.remove(cfg)
        with open(cfg, "w", encoding="utf-8") as fh:
            fh.write("a: [\n")
        p = self.run_h("SessionStart", patch={key("SessionStart"): "ok_text"})
        self.assertEqual((p.stdout, p.returncode), ("t1\nt2\n", 0))   # the handler ran: the hook is not silent

    def test_framework_dir(self):   # R10
        p = self.run_h("SessionStart", patch={key("SessionStart"): "show_fw"})
        self.assertEqual(p.stdout, FW + "\n")

    def test_context_env_copy(self):   # R11
        p = self.run_h("PreToolUse", patch={key("PreToolUse", "bash"): "show_env"}, HOOK_ENV_PROBE="seen")
        self.assertEqual(json.loads(p.stdout)["hookSpecificOutput"]["additionalContext"], "read-only seen")


class InputTest(EntryCase):
    BAD = [b"", b"\xff{}", b"{", b"x", b"[]", b'{"hook_event_name": "PostToolUse"}']

    def test_malformed_input_fails_closed_for_pretooluse(self):   # I1-I11 through the entry
        for data in self.BAD:
            for event in hookio.EVENTS:
                with self.subTest(event=event, data=data):
                    p = self.run_h(event, data)
                    if event == "PreToolUse":
                        self.assertEqual((p.returncode, p.stdout), (2, ""))
                        self.assertEqual(len(p.stderr.splitlines()), 1)
                        self.assertTrue(p.stderr.startswith("FAIL hook.PreToolUse: hook.input: "), p.stderr)
                        self.assertTrue(p.stderr.endswith(TAIL + "\n"))
                    elif event in ("SessionStart", "UserPromptSubmit"):
                        self.assertEqual((p.returncode, p.stderr), (0, ""))
                        self.assertTrue(p.stdout.startswith("FAIL hook.%s: hook.input: " % event), p.stdout)
                        self.assertTrue(p.stdout.endswith(TAIL + "\n"))
                    else:
                        self.assertEqual((p.returncode, p.stdout, p.stderr), (0, "", ""))

    def test_exact_input_failure_line(self):
        p = self.run_h("PreToolUse", b"")
        self.assertEqual(p.stderr, fc("PreToolUse", "hook.input: input is not valid JSON: Expecting value: line 1 column 1 (char 0)") + "\n")

    def test_event_mismatch_refused(self):   # I8
        for fields in ({"hook_event_name": "SessionStart"}, {"hook_event_name": 1}, {"hook_event_name": "pretooluse"}):
            with self.subTest(fields=fields):
                p = self.run_h("PreToolUse", payload("PreToolUse", self.repo, **fields))
                self.assertEqual(p.returncode, 2)
                self.assertTrue(p.stderr.startswith("FAIL hook.PreToolUse: hook.input: "))
        data = payload("PreToolUse", self.repo)
        del data["hook_event_name"]
        self.assertEqual(self.run_h("PreToolUse", data).returncode, 2)

    def test_unicode_version_lines_identical(self):   # I17, V2: the FAIL line naming U+1FAE0 is the same everywhere
        data = (json.dumps(payload("PreToolUse", self.repo))[:-1] + ', "\U0001fae0": 1, "\U0001fae0": 2}').encode("utf-8")
        p = self.run_h("PreToolUse", data)
        self.assertEqual(p.stderr, fc("PreToolUse", "hook.input: input is not valid JSON: duplicate key '\\U0001fae0'") + "\n")

    def test_session_id_128_accepted_129_refused(self):   # I9 through the entry
        patch = {key("PreToolUse", "bash"): "ok_context"}
        self.assertEqual(self.run_h("PreToolUse", payload("PreToolUse", self.repo, session_id="a" * 128), patch).returncode, 0)
        self.assertEqual(self.run_h("PreToolUse", payload("PreToolUse", self.repo, session_id="a" * 129), patch).returncode, 2)

    def test_post_and_stop_never_print(self):   # F8, I19
        internal = payload("SubagentStop", self.repo, agent_type="", agent_transcript_path="/nonexistent/agent-x.jsonl")
        cases = [("PostToolUse", b"x", None), ("SubagentStop", b"x", None), ("SubagentStop", internal, None),
                 ("PostToolUse", payload("PostToolUse", self.repo, tool_name="Read"), {key("PostToolUse", "read"): "raises_exception"}),
                 ("SubagentStop", payload("SubagentStop", self.repo), {key("SubagentStop"): "raises_exit0"})]
        for event, data, patch in cases:
            with self.subTest(event=event, data=str(data)[:40]):
                p = self.run_h(event, data, patch)
                self.assertEqual((p.returncode, p.stdout, p.stderr), (0, "", ""))


class HandlerTest(EntryCase):
    def test_handlers_table(self):   # F1
        self.assertEqual(hook.HANDLERS, {
            ("SessionStart", None): "gates.hooks.session_start",
            ("UserPromptSubmit", None): "gates.hooks.prompt_submit",
            ("PreToolUse", "agent"): "gates.hooks.pre_agent",
            ("PreToolUse", "bash"): "gates.hooks.pre_bash",
            ("PreToolUse", "edit"): "gates.hooks.pre_edit",
            ("PostToolUse", "read"): "gates.hooks.post_read",
            ("SubagentStop", None): "gates.hooks.subagent_stop"})

    def test_missing_handler_fails_closed(self):   # F2, F3, F11
        real = {"pre_agent", "pre_bash", "pre_edit", "subagent_stop"}   # absent in this task (streams bash and tools)
        for group, tool in (("agent", "Agent"), ("bash", "Bash"), ("edit", "Edit"), ("edit", "MultiEdit")):
            with self.subTest(tool=tool):
                mod = hook.HANDLERS[("PreToolUse", group)]
                self.assertIn(mod.rsplit(".", 1)[1], real)
                if os.path.exists(os.path.join(FW, *mod.split(".")) + ".py"):
                    self.skipTest("handler module exists")   # a later stream added it
                p = self.run_h("PreToolUse", payload("PreToolUse", self.repo, tool_name=tool))
                self.assertEqual((p.returncode, p.stdout), (2, ""))
                self.assertEqual(p.stderr, fc("PreToolUse", "ModuleNotFoundError: No module named '%s'" % mod) + "\n")
        for name, reason in (("fxh.nonexistent", "ModuleNotFoundError: No module named 'fxh.nonexistent'"),):
            p = self.run_h("SessionStart", patch={key("SessionStart"): "nonexistent"})
            self.assertEqual((p.returncode, p.stderr), (0, ""))
            self.assertEqual(p.stdout, fc("SessionStart", reason) + "\n")
        for name, reason in (("no_handle", "handler module fxh.no_handle has no handle"),
                             ("not_callable", "handler fxh.not_callable.handle is not callable")):
            for event, group in (("PreToolUse", "bash"), ("SessionStart", None)):
                with self.subTest(module=name, event=event):
                    p = self.run_h(event, patch={key(event, group): name})
                    if event == "PreToolUse":
                        self.assertEqual((p.returncode, p.stdout, p.stderr), (2, "", fc(event, reason) + "\n"))
                    else:
                        self.assertEqual((p.returncode, p.stdout, p.stderr), (0, fc(event, reason) + "\n", ""))

    def test_raising_handler_fails_closed(self):   # F4, F5
        cases = [("raises_exception", "Exception: boom"), ("raises_gate", "gate says no"),
                 ("raises_kbd", "KeyboardInterrupt: "), ("raises_exit0", "SystemExit: 0"),
                 ("raises_beg", None), ("raises_eg", None)]
        for name, reason in cases:
            for event, group in (("PreToolUse", "bash"), ("SessionStart", None)):
                with self.subTest(module=name, event=event):
                    p = self.run_h(event, patch={key(event, group): name})
                    line = p.stderr if event == "PreToolUse" else p.stdout
                    self.assertEqual(p.returncode, 2 if event == "PreToolUse" else 0)
                    self.assertEqual(p.stdout if event == "PreToolUse" else p.stderr, "")
                    self.assertTrue(line.startswith("FAIL hook.%s: " % event) and line.endswith(TAIL + "\n"), line)
                    self.assertEqual(len(line.splitlines()), 1)
                    if reason is not None:
                        self.assertEqual(line, fc(event, reason) + "\n")

    def test_bad_outcome_fails_closed(self):   # F6
        for name in ("returns_none", "returns_dict", "returns_subclass", "deny_nonstr", "deny_tuple", "context_nonlist"):
            with self.subTest(module=name):
                p = self.run_h("PreToolUse", patch={key("PreToolUse", "bash"): name})
                self.assertEqual((p.returncode, p.stdout), (2, ""))
                self.assertEqual(p.stderr, fc("PreToolUse", "handler fxh.%s.handle returned a bad outcome" % name) + "\n")

    def test_pass_never_allows(self):   # O3 through the entry
        p = self.run_h("PreToolUse", patch={key("PreToolUse", "bash"): "ok_context"})
        self.assertEqual((p.returncode, p.stderr), (0, ""))
        self.assertEqual(json.loads(p.stdout), {"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": "x"}})
        self.assertEqual(p.stdout, '{"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": "x"}}\n')

    def test_deny_through_entry(self):   # O1 through the entry
        p = self.run_h("PreToolUse", patch={key("PreToolUse", "bash"): "ok_deny"})
        self.assertEqual((p.returncode, p.stdout, p.stderr), (2, "", "FAIL a\nFAIL b\n"))

    def test_fail_line_one_line(self):   # F9
        p = self.run_h("PreToolUse", patch={key("PreToolUse", "bash"): "weird_reason"})
        self.assertEqual(p.stderr, fc("PreToolUse", "a\\nb\\x07\\U0001fae0\\u2c2f") + "\n")

    def test_write_failure_exit(self):   # F10
        for event, group, mod, code in (("PreToolUse", "bash", "ok_context", 2), ("PreToolUse", "bash", "ok_deny", 2),
                                        ("PreToolUse", "bash", "raises_gate", 2), ("SessionStart", None, "ok_text", 0),
                                        ("UserPromptSubmit", None, "ok_text", 0)):
            with self.subTest(event=event, module=mod):
                p = self.run_h(event, patch={key(event, group): mod}, HOOKTEST_BREAK="1")
                self.assertEqual(p.returncode, code)

    def run_pipes(self, event, group, mod, break_out, break_err):
        """The production entry with fd 1 and/or fd 2 a real OS pipe whose read end is closed before the hook writes;
        the stream that is not broken is captured. Returns (returncode, stdout bytes or None, stderr bytes or None)."""
        ends = []
        fds = {}
        for name, broken in (("stdout", break_out), ("stderr", break_err)):
            if broken:
                r, w = os.pipe()
                os.close(r)
                ends.append(w)
                fds[name] = w
            else:
                fds[name] = subprocess.PIPE
        try:
            p = subprocess.run(hookrun.argv_for(event), input=json.dumps(payload(event, self.repo)).encode("utf-8"),
                               cwd=FW, check=False, env=self.env({key(event, group): mod}),
                               stdout=fds["stdout"], stderr=fds["stderr"])
        finally:
            for w in ends:
                os.close(w)
        return p.returncode, (None if break_out else p.stdout), (None if break_err else p.stderr)

    def test_real_broken_pipe_exit(self):   # F10 (b), (c), (d), V9: never 120, no noise on the other stream
        deny = b"FAIL a\nFAIL b\n"
        cases = [   # part, event, group, module, exit code, fd 1 broken, fd 2 broken, expected bytes of the stream kept
            ("b", "PreToolUse", "bash", "ok_context", 2, True, False, b""),
            ("b", "PreToolUse", "bash", "ok_deny", 2, True, False, deny),
            ("b", "SessionStart", None, "ok_text", 0, True, False, b""),
            ("b", "UserPromptSubmit", None, "ok_text", 0, True, False, b""),
            ("b", "SessionStart", None, "raises_gate", 0, True, False, b""),
            ("b", "UserPromptSubmit", None, "raises_gate", 0, True, False, b""),
            ("c", "PreToolUse", "bash", "raises_gate", 2, False, True, b""),
            ("d", "PreToolUse", "bash", "raises_gate", 2, True, True, None),
            ("d", "SessionStart", None, "ok_text", 0, True, True, None),
        ]
        for part, event, group, mod, code, bo, be, kept in cases:
            with self.subTest(part=part, event=event, module=mod):
                rc, out, err = self.run_pipes(event, group, mod, bo, be)
                self.assertEqual(rc, code)
                if kept is not None:
                    self.assertEqual(err if bo else out, kept)

    def test_usage_broken_stderr_exit(self):   # F10d (A1-A3 with fd 2 a real broken pipe, and closed at start)
        launcher = os.path.join(self.tmp, "closefd_usage.py")
        with open(launcher, "w", encoding="utf-8") as fh:
            fh.write("import os, sys\nos.close(2)\nos.execv(sys.executable, [sys.executable] + sys.argv[1:])\n")
        for args in ([], ["Bogus"], ["PreToolUse", "x"]):
            base = [sys.executable, "-m", "gates", "hook"] + args
            with self.subTest(args=args, how="real broken pipe"):
                r, w = os.pipe()
                os.close(r)
                try:
                    p = subprocess.run(base, cwd=FW, check=False, env=self.env(), stdin=subprocess.DEVNULL,
                                       stdout=subprocess.PIPE, stderr=w)
                finally:
                    os.close(w)
                self.assertEqual((p.returncode, p.stdout), (2, b""))
            with self.subTest(args=args, how="closed at start"):
                p = subprocess.run([sys.executable, launcher] + base[1:], cwd=FW, check=False, env=self.env(),
                                   stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                self.assertEqual((p.returncode, p.stdout), (2, b""))

    def test_closed_fd_exit(self):   # F10c, V9: the process starts with fd 1 (or fd 2) closed
        launcher = os.path.join(self.tmp, "closefd.py")
        with open(launcher, "w", encoding="utf-8") as fh:
            fh.write("import os, sys\nos.close(int(sys.argv[1]))\nos.execv(sys.executable, [sys.executable] + sys.argv[2:])\n")
        cases = [   # fd closed, event, group, module, exit code, expected bytes of the other stream (None: unchecked)
            (1, "PreToolUse", "bash", "ok_context", 2, b""),
            (1, "PreToolUse", "bash", "raises_gate", 2, None),
            (1, "SessionStart", None, "ok_text", 0, b""),
            (2, "PreToolUse", "bash", "ok_context", 0, None),
            (2, "PreToolUse", "bash", "raises_gate", 2, b""),
            (2, "SessionStart", None, "ok_text", 0, b"t1\nt2\n"),
        ]
        for fd, event, group, mod, code, other in cases:
            with self.subTest(fd=fd, event=event, module=mod):
                argv = [sys.executable, launcher, str(fd)] + hookrun.argv_for(event)[1:]
                p = subprocess.run(argv, cwd=FW, check=False, input=json.dumps(payload(event, self.repo)).encode("utf-8"),
                                   env=self.env({key(event, group): mod}), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                self.assertEqual(p.returncode, code)
                if other is not None:
                    self.assertEqual(p.stderr if fd == 1 else p.stdout, other)

    def test_tool_groups_route(self):   # F11, V5: MultiEdit routes like Edit
        patch = {key("PreToolUse", "edit"): "ok_context"}
        for tool in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
            with self.subTest(tool=tool):
                p = self.run_h("PreToolUse", payload("PreToolUse", self.repo, tool_name=tool), patch)
                self.assertEqual(p.returncode, 0)
                self.assertIn("additionalContext", p.stdout)


class PostReadTest(EntryCase):
    def snapshot(self, *roots):
        out = {}
        for top in roots:
            for d, dirs, files in os.walk(top):
                for n in sorted(files + dirs):
                    p = os.path.join(d, n)
                    out[p] = hashlib.sha256(open(p, "rb").read()).hexdigest() if os.path.isfile(p) else "dir"
        return out

    def test_post_read_writes_nothing(self):   # PR1
        bare = os.path.join(self.tmp, "bare")
        os.makedirs(bare)
        git(bare, "init", "-q", "-b", "main")
        for root in (self.repo, bare):
            for tool_input in ({"file_path": os.path.join(root, "x")}, {}, {"a": [1]}):
                with self.subTest(root=root, tool_input=tool_input):
                    before = self.snapshot(self.repo, bare, self.data)
                    p = self.run_h("PostToolUse", payload("PostToolUse", root, tool_name="Read", tool_input=tool_input))
                    self.assertEqual((p.returncode, p.stdout, p.stderr), (0, "", ""))
                    self.assertEqual(self.snapshot(self.repo, bare, self.data), before)
        from gates.hooks import post_read
        self.assertEqual(post_read.handle(None), hookio.Outcome())


class HookrunTest(unittest.TestCase):
    def test_hookrun_uses_production_entry(self):   # K1
        self.assertEqual(hookrun.argv_for("SessionStart"), [sys.executable, "-m", "gates", "hook", "SessionStart"])
        calls = []

        def fake(argv, **kw):
            calls.append((argv, kw))
            return subprocess.CompletedProcess(argv, 0, b"o", b"e")
        with mock.patch("tests.hookrun.subprocess.run", fake):
            p = run_hook("PreToolUse", {"a": 1}, {"E": "1"}, "/fw")
        argv, kw = calls[0]
        self.assertEqual(argv, [sys.executable, "-m", "gates", "hook", "PreToolUse"])
        self.assertEqual((kw["cwd"], kw["env"], kw["input"]), ("/fw", {"E": "1"}, b'{"a": 1}'))
        self.assertEqual((p.stdout, p.stderr, p.returncode), ("o", "e", 0))
        from gates import __main__ as entry
        with mock.patch.dict(entry.COMMANDS, clear=False):
            del entry.COMMANDS["hook"]
            self.assertEqual(hookrun.argv_for("SessionStart")[:2], [sys.executable, "-c"])
            self.assertEqual(hookrun.argv_for("SessionStart")[-1], "SessionStart")

    def test_hookrun_payload_shape(self):   # K2
        keys = {
            "PreToolUse": "cwd effort hook_event_name permission_mode prompt_id scratchpad_dir session_id tool_input tool_name tool_use_id transcript_path",
            "PostToolUse": "cwd duration_ms effort hook_event_name permission_mode prompt_id scratchpad_dir session_id tool_input tool_name tool_response tool_use_id transcript_path",
            "SessionStart": "cwd hook_event_name model scratchpad_dir session_id source transcript_path",
            "UserPromptSubmit": "cwd hook_event_name permission_mode prompt prompt_id scratchpad_dir session_id transcript_path",
            "SubagentStop": "agent_id agent_transcript_path agent_type background_tasks cwd effort hook_event_name last_assistant_message permission_mode prompt_id scratchpad_dir session_crons session_id stop_hook_active transcript_path",
        }
        for event, names in keys.items():
            with self.subTest(event=event):
                p = payload(event, "/r")
                self.assertEqual(sorted(p), sorted(names.split()))
                self.assertEqual((p["cwd"], p["hook_event_name"]), ("/r", event))
                hookio.parse(event, json.dumps(p).encode("utf-8"))
        sub = payload("PreToolUse", "/r", agent_id="a-1", agent_type="general-purpose", tool_name="Read")
        self.assertEqual((sub["agent_id"], sub["agent_type"], sub["tool_name"]), ("a-1", "general-purpose", "Read"))
        self.assertEqual(len(sub), len(payload("PreToolUse", "/r")) + 2)


# ---------------------------------------------------------------- hooks/hooks.json

def load_json():
    with open(os.path.join(FW, "hooks", "hooks.json"), encoding="utf-8") as fh:
        text = fh.read()
    return text, json.loads(text)


def handler_objects(data):
    """(event, matcher or None, handler object) for every handler object."""
    out = []
    for event, groups in data["hooks"].items():
        for g in groups:
            for h in g["hooks"]:
                out.append((event, g.get("matcher"), h))
    return out


EXPECTED_ENTRIES = [("SessionStart", None), ("UserPromptSubmit", None), ("PreToolUse", "Agent"), ("PreToolUse", "Bash"),
                    ("PreToolUse", "Edit|Write|MultiEdit|NotebookEdit"), ("PostToolUse", "Read"), ("SubagentStop", None)]


class HooksJsonTest(unittest.TestCase):
    def test_hooks_json_matches_handlers(self):   # J1-J4
        text, data = load_json()
        self.assertTrue(text.endswith("}\n") and not text.endswith("\n\n"))
        self.assertEqual(sorted(data), ["description", "hooks"])
        self.assertIs(type(data["description"]), str)
        objs = handler_objects(data)
        self.assertEqual([(e, m) for e, m, h in objs], EXPECTED_ENTRIES)
        self.assertEqual(sorted(data["hooks"]), sorted(hookio.EVENTS))
        for event, matcher, h in objs:
            self.assertEqual(h["type"], "command")
            self.assertEqual(h["command"], 'cd "${CLAUDE_PLUGIN_ROOT}" && exec python3 -m gates hook ' + event)
        for event, groups in data["hooks"].items():   # J3: no matcher key on the three matcher-less events
            for g in groups:
                self.assertEqual("matcher" in g, event in ("PreToolUse", "PostToolUse"))
                self.assertEqual(sorted(g), ["hooks", "matcher"] if "matcher" in g else ["hooks"])

    def test_every_handlers_key_present_once(self):   # J2
        _, data = load_json()
        per_event = {}
        for event, matcher, h in handler_objects(data):
            per_event.setdefault(event, []).append(matcher)
        keys = []
        for event, matchers in per_event.items():
            if event == "PreToolUse" or event == "PostToolUse":
                for m in matchers:
                    groups = {hookio.TOOL_GROUPS[t] for t in m.split("|")}
                    self.assertEqual(len(groups), 1, m)
                    keys.append((event, groups.pop()))
            else:
                self.assertEqual(matchers, [None])
                keys.append((event, None))
        self.assertEqual(sorted(keys, key=str), sorted(hook.HANDLERS, key=str))

    def test_pretooluse_entries_block_on_failure(self):   # J5
        _, data = load_json()
        for event, matcher, h in handler_objects(data):
            with self.subTest(event=event, matcher=matcher):
                if event == "PreToolUse":
                    self.assertEqual(h.get("onFailure"), "block")
                else:
                    self.assertNotIn("onFailure", h)

    def test_hooks_json_no_timeout(self):   # J6
        _, data = load_json()
        for event, matcher, h in handler_objects(data):
            self.assertNotIn("timeout", h)

    def test_matchers_route_to_handlers(self):   # J7, V5
        _, data = load_json()
        for event, matcher, h in handler_objects(data):
            if matcher is None:
                continue
            for tool in matcher.split("|"):
                with self.subTest(tool=tool):
                    group = hookio.TOOL_GROUPS[tool]
                    self.assertIn((event, group), hook.HANDLERS)
        self.assertNotIn("Task", json.dumps(data))


if __name__ == "__main__":
    unittest.main()
