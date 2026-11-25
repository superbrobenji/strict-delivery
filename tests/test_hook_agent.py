"""Tests of the Agent PreToolUse hook and SubagentStop (Task 3c.2; rows of task-3c.2-domain.md named in each test).

Production path: ``python3 -m gates hook <Event>`` through ``tests.hookrun.run_hook`` with the real gate and the real
``skills/strict-delivery/prompts/``; pure tests patch ``gates.hooks.pre_agent.gate_dispatch.check`` (CD2) to observe the
gate input. Expected values are written by hand from the plan and the table, never read back from the code."""
import json
import os
import re
import threading
import unittest
from unittest import mock

from gates.hooks import pre_agent, subagent_stop
from gates.lib import config, dispatch, hookio, session
from gates.lib.hookio import HookContext, Outcome
from gates.lib.result import Result
from tests.helpers import GitIsolatedTestCase, commit_all, git, make_repo, minimal_config, write_record
from tests.hookrun import FW, payload, run_hook
from tests.test_dispatch_lib import NAME, add_program
from tests.test_worktrees import HEADER, PROGRAMS, status_row

MODELS = {2: "sonnet", 3: "opus"}
WAY = "; the human can disable the plugin with /plugin until a fix merges, and !-prefixed commands still run"
PROMPTS = os.path.join(FW, "skills", "strict-delivery", "prompts")


def real_prompt(role, model="sonnet", brief="b", task="t"):
    with open(os.path.join(PROMPTS, role + ".md"), "rb") as fh:
        block = fh.read().decode("utf-8")
    return ("## Role\n%s\n\n## Brief\n%s\n\n## Findings\n\n## Claims\n\n## Budget: tokens=1000 minutes=10\n\n"
            "## Model\n%s\n\n## Report\nr\n\n## Strict block\n\n%s\n## Task\n%s\n" % (role, brief, model, block, task))


def user_line(text):
    return json.dumps({"type": "user", "message": {"role": "user", "content": text}})


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def real(p):
    return os.path.realpath(p)


def tin(prompt, **extra):
    d = {"prompt": prompt, "subagent_type": "general-purpose", "model": "sonnet", "description": "d"}
    d.update(extra)
    return d


class Base(GitIsolatedTestCase):
    def setUp(self):
        super().setUp()
        self.R = real(make_repo(self.work))
        self.pd = os.path.join(self.tmp, "pd")
        os.makedirs(self.pd)
        self.env = {"PATH": os.environ["PATH"], "HOME": os.environ.get("HOME", "/"), "GIT_CONFIG_NOSYSTEM": "1",
                    "GIT_CONFIG_GLOBAL": "/dev/null", "LC_ALL": "C", "CLAUDE_PLUGIN_DATA": self.pd}
        self.main_t = os.path.join(self.tmp, "main.jsonl")
        write(self.main_t, user_line("MAIN") + "\n")

    def set_config(self, **extra):
        write_record(self.R, ".strict-delivery/config.yml", dict(minimal_config(), **extra))
        commit_all(self.R, "config")

    def hk(self, tool_input, agent_id=None, env=None, **fields):
        f = dict(tool_name="Agent", tool_input=tool_input, session_id="s1")
        if agent_id:
            f.update(agent_id=agent_id, agent_type="general-purpose", transcript_path=self.main_t)
        f.update(fields)
        return run_hook("PreToolUse", payload("PreToolUse", self.R, **f), env or self.env, FW)

    def sub(self, agent_id, prompt):
        write(os.path.join(self.tmp, "s1", "subagents", "agent-%s.jsonl" % agent_id), user_line(prompt) + "\n")

    def recs(self, sid="s1"):
        with session.locked(self.env, sid) as st:
            return [dict(e) for e in st["dispatches"]]

    def seed(self, *entries):
        with session.locked(self.env, "s1") as st:
            for e in entries:
                session.add_dispatch(st, *e)

    def stop(self, path, sid="s1", **f):
        return run_hook("SubagentStop", payload("SubagentStop", self.R, session_id=sid, agent_transcript_path=path, **f),
                        self.env, FW)

    def add_wt(self, name, *args):
        path = os.path.join(self.work, name)
        git(self.R, "worktree", "add", *(list(args) + [path]))
        return real(path)

    def hand(self, **kw):
        base = dict(event="PreToolUse", tool_name="Agent", tool_input={}, session_id="s1", agent_id=None,
                    transcript_path=self.main_t, cwd=self.R, root=self.R, cfg=config.load(self.R), cfg_error=None,
                    framework_dir=FW, env={"CLAUDE_PLUGIN_DATA": self.pd}, raw={})
        base.update(kw)
        return HookContext(**base)

    def seen(self, ctx, **over):
        """Run ``pre_agent.handle`` with a spy gate; return (outcome, calls)."""
        calls = []

        def check(args):
            i = args.index("--input")
            with open(args[i + 1], encoding="utf-8") as fh:
                calls.append((list(args), json.load(fh)))
            r = Result("dispatch")
            r.passed("dispatch.input")
            return r
        with mock.patch("gates.hooks.pre_agent.gate_dispatch.check", check):
            return pre_agent.handle(ctx), calls

    def program(self, streams=("s1", "s2")):
        """A live program; stream worktree for s1 on <p>/s1/main listed on the status page; integration worktree."""
        add_program(self.R, streams=streams)
        self.stream_wt = os.path.join(self.work, "stream1")
        git(self.R, "checkout", "-q", NAME + "/integration")
        write(os.path.join(self.R, PROGRAMS, NAME, "status.md"),
              "# status\n\n" + HEADER + status_row("s1", self.stream_wt).replace("20261101-prog", NAME))
        commit_all(self.R, "status")
        git(self.R, "checkout", "-q", "main")
        git(self.R, "worktree", "add", "-q", "-b", NAME + "/s1/main", self.stream_wt, "main")
        self.stream_wt = real(self.stream_wt)


class SessionContext(Base):
    def test_session_dispatch_context(self):   # DS1 HN1 HP1
        out, calls = self.seen(self.hand(tool_input=tin("P")))
        self.assertEqual((out.deny, out.context), ([], []))
        self.assertEqual(calls[0][1], {"prompt": "P", "subagent_type": "general-purpose", "model": "sonnet",
                                       "dispatcher": {"id": "session", "depth": 0, "live_children": 0, "live_total": 0},
                                       "program_live": False})
        self.assertEqual(calls[0][0][:2], ["--root", self.R])   # HR12
        self.assertEqual(calls[0][0][2], "--input")
        self.assertEqual(len(calls[0][0]), 4)

    def test_gate_input_key_set(self):   # HG1 HG2 HG6 HG11 HT4
        out, calls = self.seen(self.hand(tool_input={"prompt": "P", "description": "d", "run_in_background": True,
                                                     "isolation": "worktree", "name": "n", "x": {"y": 1}}))
        self.assertEqual(sorted(calls[0][1]), ["dispatcher", "program_live", "prompt"])
        for v in calls[0][1]["dispatcher"].values():
            self.assertIs(type(v) if not isinstance(v, str) else int, int)

    def test_dispatcher_counts_by_parent(self):   # DS2 HN4
        self.seed(*[("%064d" % i, "controller", 1, "session", "", "") for i in range(2)],
                  ("%064d" % 9, "implementer", 2, "a9", "", ""))
        out, calls = self.seen(self.hand(tool_input=tin("P")))
        self.assertEqual(calls[0][1]["dispatcher"], {"id": "session", "depth": 0, "live_children": 2, "live_total": 3})

    def test_store_down_omits_dispatcher(self):   # DS3
        env = dict(self.env)
        del env["CLAUDE_PLUGIN_DATA"]
        out, calls = self.seen(self.hand(tool_input=tin("P"), env=env))
        self.assertEqual(len(out.deny), 1)
        self.assertTrue(out.deny[0].startswith("FAIL hook.agent.session: CLAUDE_PLUGIN_DATA is not set"))
        self.assertNotIn("dispatcher", calls[0][1])

    def test_gate_input_program_live(self):   # HG8 HP2 HP3 HP4
        self.program()
        out, calls = self.seen(self.hand(tool_input=tin("P")))
        self.assertIs(calls[0][1]["program_live"], True)
        with mock.patch("gates.lib.programs.live_programs", side_effect=__import__("gates.lib.result",
                                                                                 fromlist=["GateError"]).GateError("x")):
            out, calls = self.seen(self.hand(tool_input=tin("P2")))
        self.assertNotIn("program_live", calls[0][1])

    def test_gate_input_prompt_roundtrip(self):   # HG10
        for text in ("café \U0001fae0", "a\r\nb\nc", "nul\u0000x", "x" * 4194304):
            with self.subTest(n=len(text)):
                out, calls = self.seen(self.hand(tool_input=tin(text)))
                self.assertEqual(calls[0][1]["prompt"], text)

    def test_wrong_type_forwarded_not_coerced(self):   # HG4
        for v in (None, 5, []):
            with self.subTest(v=v):
                out, calls = self.seen(self.hand(tool_input=tin("P", subagent_type=v, model=v)))
                self.assertEqual((calls[0][1]["subagent_type"], calls[0][1]["model"]), (v, v))

    def test_input_file_removed_on_every_path(self):   # HG9 HX2
        seen_dirs = []

        def check(args):
            seen_dirs.append(os.path.dirname(args[args.index("--input") + 1]))
            raise RuntimeError("boom")
        with mock.patch("gates.hooks.pre_agent.gate_dispatch.check", check):
            out = pre_agent.handle(self.hand(tool_input=tin("P")))
        self.assertTrue(out.deny[0].startswith("FAIL dispatch.input: RuntimeError: boom"))
        self.assertFalse(os.path.exists(seen_dirs[0]))
        out, calls = self.seen(self.hand(tool_input=tin("P")))
        self.assertEqual(out.deny, [])

    def test_gate_raising_denied(self):   # HR5 HR6
        for exc in (RuntimeError("r"), SystemExit(0)):
            with self.subTest(exc=exc), mock.patch("gates.hooks.pre_agent.gate_dispatch.check", side_effect=exc):
                out = pre_agent.handle(self.hand(tool_input=tin("P")))
                self.assertEqual(len(out.deny), 1)
                self.assertTrue(out.deny[0].startswith("FAIL dispatch.input: "))
        with mock.patch("gates.hooks.pre_agent.gate_dispatch.check", return_value=None):
            self.assertTrue(pre_agent.handle(self.hand(tool_input=tin("P"))).deny[0].startswith("FAIL dispatch.input: "))

    def test_baseexception_from_gate_fails_closed(self):   # HR7
        with mock.patch("gates.hooks.pre_agent.gate_dispatch.check", side_effect=KeyboardInterrupt()):
            with self.assertRaises(KeyboardInterrupt):
                pre_agent.handle(self.hand(tool_input=tin("P")))
        self.assertEqual(self.recs(), [])

    def test_in_force_lines_passed_as_context(self):   # HR3 HR4
        def check(args):
            r = Result("dispatch")
            r.passed("dispatch.input")
            r.passed("dispatch.in-force.DEC-20261101-k3f9")
            r.passed("dispatch.in-force.DEC-20261101-aaaa")
            return r
        with mock.patch("gates.hooks.pre_agent.gate_dispatch.check", check):
            out = pre_agent.handle(self.hand(tool_input=tin(real_prompt("implementer"))))
        self.assertEqual(out.context, ["PASS dispatch.in-force.DEC-20261101-k3f9",
                                       "PASS dispatch.in-force.DEC-20261101-aaaa"])
        self.assertEqual(out.deny, [])

        def bad(args):
            r = check(args)
            r.fail("dispatch.model", "m")
            return r
        with mock.patch("gates.hooks.pre_agent.gate_dispatch.check", bad):
            out = pre_agent.handle(self.hand(tool_input=tin("P")))
        self.assertEqual(out.deny, ["FAIL dispatch.model: m"])      # only FAIL lines; context dropped (HR4)
        self.assertEqual(out.context, [])


class HookRuns(Base):
    def test_gate_pass_allows_and_records(self):   # HR1 HA1 HA10 HA11 HR14 HX5
        p = self.hk(tin(real_prompt("implementer")))
        self.assertEqual((p.returncode, p.stdout, p.stderr), (0, "", ""))
        sha = session.prompt_sha(real_prompt("implementer"))
        self.assertEqual(self.recs(), [{"sha": sha, "role": "implementer", "depth": 1, "parent": "session",
                                        "worktree": self.R, "branch": "main"}])
        path = os.path.join(self.pd, "sessions", "s1.yml")
        self.assertEqual(oct(os.stat(path).st_mode & 0o777), "0o600")
        self.assertEqual(session.state_errors(self.recs and {"schema": session.SCHEMA, "session": "s1",
                                                              "dispatches": self.recs(), "surfaced": []}, "s1"), [])

    def test_every_fail_line_denied(self):   # HR2 HG3 HT5 HA4 HN10
        p = self.hk({"prompt": real_prompt("implementer"), "subagent_type": "general-purpose"})
        self.assertEqual(p.returncode, 2)
        self.assertEqual(p.stdout, "")
        self.assertEqual(p.stderr.split("\n")[:-1], [
            "FAIL dispatch.model: the dispatch call passes no model",
            "FAIL dispatch.tier: not checked: dispatch.model failed",
            "FAIL dispatch.top-tier: not checked: dispatch.tier failed"])
        self.assertEqual(self.recs(), [])

    def test_model_mismatch_denied(self):   # HT6
        p = self.hk(tin(real_prompt("implementer"), model="opus"))
        self.assertEqual(p.returncode, 2)
        self.assertIn("FAIL dispatch.model: the dispatch's model 'opus' is not the one line of ## Model", p.stderr)

    def test_fork_denied_when_required(self):   # HG5
        for st in ("fork", "Fork", "FORK"):
            p = self.hk(tin(real_prompt("implementer"), subagent_type=st))
            self.assertEqual(p.returncode, 2, st)
            self.assertIn("FAIL dispatch.fork: subagent_type is fork", p.stderr)
        self.assertEqual(self.recs(), [])

    def test_unknown_dispatcher_omitted_fails_input(self):   # DS7 HG7 HA7
        p = self.hk(tin(real_prompt("implementer")), agent_id="a1")
        self.assertEqual(p.returncode, 2)
        self.assertEqual(p.stderr, "FAIL dispatch.input: input: dispatcher must be an object\n")
        self.assertEqual(self.recs(), [])

    def test_no_store_refuses_gated_dispatch(self):   # HS2 HS7
        for patch in ({"CLAUDE_PLUGIN_DATA": None}, {"CLAUDE_PLUGIN_DATA": "rel"}, {"CLAUDE_PLUGIN_DATA": ""}):
            env = dict(self.env)
            for k, v in patch.items():
                if v is None:
                    del env[k]
                else:
                    env[k] = v
            p = self.hk(tin(real_prompt("implementer")), env=env)
            self.assertEqual(p.returncode, 2, patch)
            lines = p.stderr.split("\n")
            self.assertEqual(lines[0], "FAIL dispatch.input: input: dispatcher must be an object")
            self.assertTrue(lines[1].startswith("FAIL hook.agent.session: "), lines)
            self.assertTrue(lines[1].endswith(WAY))

    def test_light_without_program_not_gated(self):   # HC2 HA6 HA5 HS3
        self.set_config(profile="light")
        p = self.hk({"prompt": "not a valid prompt", "model": "sonnet"})
        self.assertEqual((p.returncode, p.stdout, p.stderr), (0, "", ""))
        rec = self.recs()
        self.assertEqual([(r["role"], r["depth"], r["parent"]) for r in rec], [("unknown", 1, "session")])
        p = self.hk({"prompt": "other"}, agent_id="a1")        # unknown dispatcher, not required: nothing recorded
        self.assertEqual((p.returncode, p.stdout, p.stderr), (0, "", ""))
        self.assertEqual(len(self.recs()), 1)
        env = dict(self.env)
        del env["CLAUDE_PLUGIN_DATA"]
        p = self.hk({"prompt": "x"}, env=env)
        self.assertEqual((p.returncode, p.stdout, p.stderr), (0, "", ""))

    def test_light_with_live_program_gated(self):   # HC3
        self.set_config(profile="light")
        self.program()
        p = self.hk({"prompt": "not a valid prompt", "model": "sonnet"})
        self.assertEqual(p.returncode, 2)
        self.assertIn("FAIL dispatch.grammar", p.stderr)

    def test_standard_and_strict_gated(self):   # HC4
        for prof in ("standard", "strict"):
            self.set_config(profile=prof)
            self.assertEqual(self.hk({"prompt": "bad", "model": "sonnet"}).returncode, 2)

    def test_config_error_denies(self):   # HC1
        write(os.path.join(self.R, ".strict-delivery", "config.yml"), "not: [valid\n")
        p = self.hk(tin(real_prompt("implementer")))
        self.assertEqual(p.returncode, 2)
        lines = p.stderr.split("\n")[:-1]
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].startswith("FAIL hook.agent.config: "))
        self.assertTrue(lines[0].endswith(WAY))
        self.assertEqual(self.recs(), [])

    def test_prompt_absent_or_not_str(self):   # HT1 HT7 HG12
        want = ("FAIL hook.agent.prompt: the Agent call has no usable prompt (a str that encodes as UTF-8)" + WAY + "\n")
        for ti in ({}, {"prompt": None}, {"prompt": 5}, {"prompt": []}, {"prompt": True},
                   {"prompt": "x\ud800y"}):
            for profile in ("light", "strict"):
                with self.subTest(ti=ti, profile=profile):
                    self.set_config(profile=profile)
                    p = self.hk(ti)
                    self.assertEqual((p.returncode, p.stdout, p.stderr), (2, "", want))

    def test_fork_when_not_required_is_recorded(self):   # HT3 HN12
        self.set_config(profile="light")
        p = self.hk(tin("fork prompt", subagent_type="fork"))
        self.assertEqual(p.returncode, 0)
        self.assertEqual(len(self.recs()), 1)

    def test_depth_chain_and_records(self):   # HA2 HD3 HD4 HD8 DS4 DS5
        p1 = real_prompt("controller", "opus")
        self.assertEqual(self.hk(tin(p1, model="opus")).returncode, 0)
        self.sub("a1", p1)
        p2 = real_prompt("controller", "opus", brief="two")
        p = self.hk(tin(p2, model="opus"), agent_id="a1")
        self.assertEqual((p.returncode, p.stderr), (0, ""))
        self.assertEqual([(r["role"], r["depth"], r["parent"]) for r in self.recs()],
                         [("controller", 1, "session"), ("controller", 2, "a1")])
        self.sub("a2", p2)
        p3 = real_prompt("controller", "opus", brief="three")
        p = self.hk(tin(p3, model="opus"), agent_id="a2")
        self.assertEqual(p.returncode, 2)
        self.assertEqual(p.stderr, "FAIL dispatch.depth: dispatcher depth 2 + 1 + 1 level(s) below controller exceeds max_depth 3\n")
        p4 = real_prompt("implementer")
        p = self.hk(tin(p4), agent_id="a2")
        self.assertEqual((p.returncode, p.stderr), (0, ""))
        self.assertEqual([(r["role"], r["depth"], r["parent"]) for r in self.recs()][-1], ("implementer", 3, "a2"))

    def test_worker_dispatch_refused(self):   # DS6
        pw = real_prompt("implementer")
        self.seed((session.prompt_sha(pw), "implementer", 3, "session", self.R, "main"))
        self.sub("a1", pw)
        p = self.hk(tin(real_prompt("implementer", brief="x")), agent_id="a1")
        self.assertEqual(p.returncode, 2)
        self.assertIn("FAIL dispatch.dispatcher: implementer is a worker role, and a worker dispatches no agent", p.stderr)

    def test_unknown_role_record_fails_input(self):   # DS8
        pw = "some light prompt"
        self.seed((session.prompt_sha(pw), "unknown", 1, "session", self.R, "main"))
        self.sub("a1", pw)
        p = self.hk(tin(real_prompt("implementer")), agent_id="a1")
        self.assertEqual(p.stderr, "FAIL dispatch.input: input: dispatcher.id must be 'session' or a role id\n")

    def test_ambiguous_record_omitted(self):   # DS9 DS10 DS11
        sha = session.prompt_sha("PP")
        base = (sha, "controller", 2, "session", self.R, "main")
        variants = {"depth": (sha, "controller", 3, "session", self.R, "main"),
                    "worktree": (sha, "controller", 2, "session", "/other", "main"),
                    "branch": (sha, "controller", 2, "session", self.R, "feature"),
                    "role": (sha, "implementer", 2, "session", self.R, "main")}
        self.sub("a1", "PP")
        ctx = self.hand(agent_id="a1")
        for name, other in variants.items():
            with self.subTest(name):
                st = {"dispatches": []}
                session.add_dispatch(st, *base)
                session.add_dispatch(st, *other)
                self.assertIsNone(pre_agent.dispatcher(ctx, st))
        st = {"dispatches": []}
        session.add_dispatch(st, *base)
        session.add_dispatch(st, *base)
        self.assertEqual(pre_agent.dispatcher(ctx, st), {"id": "controller", "depth": 2, "live_children": 0,
                                                         "live_total": 2})

    def test_dispatcher_transcript_shapes(self):   # DS12 DS13 DS14 DS16 DS22
        sha = session.prompt_sha("AB")
        st = {"dispatches": []}
        session.add_dispatch(st, sha, "controller", 2, "session", self.R, "main")
        path = os.path.join(self.tmp, "s1", "subagents", "agent-a1.jsonl")
        ctx = self.hand(agent_id="a1")
        found = {"id": "controller", "depth": 2, "live_children": 0, "live_total": 1}
        self.assertIsNone(pre_agent.dispatcher(ctx, st))   # missing
        os.makedirs(path)
        self.assertIsNone(pre_agent.dispatcher(ctx, st))   # directory
        os.rmdir(path)
        rows = [("not json", "not json\n", None), ("not object", "[1]\n", None), ("blank first", "\n" + user_line("AB") + "\n", None),
                ("nan", '{"type":"user","message":{"content":NaN}}\n', None),
                ("dup", '{"type":"user","type":"user"}\n', None),
                ("blocks", json.dumps({"type": "user", "message": {"content": [{"type": "text", "text": "A"},
                                                                               {"type": "text", "text": "B"}]}}) + "\n", found),
                ("text+image", json.dumps({"type": "user", "message": {"content": [{"type": "text", "text": "AB"},
                                                                                   {"type": "image"}]}}) + "\n", found),
                ("no text", json.dumps({"type": "user", "message": {"content": [{"type": "image"}]}}) + "\n", None),
                ("surrogate", json.dumps({"type": "user", "message": {"content": "A\ud800"}}) + "\n", None)]
        for name, text, want in rows:
            with self.subTest(name):
                write(path, text)
                self.assertEqual(pre_agent.dispatcher(ctx, st), want)
        with open(path, "wb") as fh:
            fh.write(b"\xff\xfe\n")
        self.assertIsNone(pre_agent.dispatcher(ctx, st))   # not UTF-8

    def test_dispatcher_sha_is_byte_exact(self):   # DS17
        st = {"dispatches": []}
        session.add_dispatch(st, session.prompt_sha("P\n"), "controller", 2, "session", self.R, "main")
        for name, text in (("space", "P\n "), ("crlf", "P\r\n"), ("nonl", "P")):
            with self.subTest(name):
                self.sub("a1", text)
                self.assertIsNone(pre_agent.dispatcher(self.hand(agent_id="a1"), st))
        self.sub("a1", "P\n")
        self.assertIsNotNone(pre_agent.dispatcher(self.hand(agent_id="a1"), st))

    def test_dispatcher_own_transcript_refused(self):   # DS18 DS19 DS20
        st = {"dispatches": []}
        session.add_dispatch(st, session.prompt_sha("MAIN"), "controller", 2, "session", self.R, "main")
        session.add_dispatch(st, session.prompt_sha("P"), "controller", 2, "session", self.R, "main")
        for tp in (None, "", "rel/a.jsonl"):
            self.sub("a1", "P")
            self.assertIsNone(pre_agent.dispatcher(self.hand(agent_id="a1", transcript_path=tp), st), tp)
        write(os.path.join(self.tmp, "other", "subagents", "agent-a3.jsonl"), user_line("P") + "\n")
        self.assertIsNone(pre_agent.dispatcher(self.hand(agent_id="a3"), st))     # DS19: session id differs
        self.assertIsNone(pre_agent.dispatcher(self.hand(agent_id="a9"), st))     # DS20: main prompt never read

    def test_counts_follow_stop(self):   # HN6 SS7 SS18 SS20
        pa, pb = real_prompt("controller", "opus"), real_prompt("controller", "opus", brief="b2")
        self.set_config(profile="strict", limits={"max_concurrent": 2})
        for p in (pa, pb):
            self.assertEqual(self.hk(tin(p, model="opus")).returncode, 0)
        pc = real_prompt("controller", "opus", brief="b3")
        p = self.hk(tin(pc, model="opus"))
        self.assertEqual(p.returncode, 2)
        self.assertIn("FAIL dispatch.concurrency: 2 running + 1 exceeds max_concurrent 2", p.stderr)
        tp = os.path.join(self.tmp, "agent-pa.jsonl")
        write(tp, user_line(pa) + "\n")
        s = self.stop(tp)
        self.assertEqual((s.returncode, s.stdout, s.stderr), (0, "", ""))
        self.assertEqual(len(self.recs()), 1)
        self.assertEqual(self.hk(tin(pc, model="opus")).returncode, 0)

    def test_unmatched_stop_changes_nothing(self):   # HN7 SS6 SS12 SS14
        self.seed(("%064d" % 1, "controller", 1, "session", "", ""))
        before = self.recs()
        tp = os.path.join(self.tmp, "agent-x.jsonl")
        write(tp, user_line("never recorded") + "\n")
        self.assertEqual(self.stop(tp).returncode, 0)
        self.assertEqual(self.recs(), before)
        self.seed((session.prompt_sha("rec"), "controller", 1, "session", "", ""))
        write(tp, user_line("rec") + "\n")
        self.assertEqual(self.stop(tp, sid="s2").returncode, 0)     # SS14: other session
        self.assertEqual(len(self.recs()), 2)
        self.assertEqual(self.recs("s2"), [])

    def test_stop_removes_one_of_duplicates(self):   # SS8 SS9 SS19
        sha = session.prompt_sha("AB")
        self.seed(*[(sha, "controller", 1, "session", "", "") for _ in range(2)])
        tp = os.path.join(self.tmp, "t.jsonl")
        write(tp, json.dumps({"type": "user", "message": {"content": [{"type": "text", "text": "A"},
                                                                      {"type": "text", "text": "B"}]}}) + "\n")
        for want in (1, 0, 0):
            self.assertEqual(self.stop(tp, agent_id="zz").returncode, 0)
            self.assertEqual(len(self.recs()), want)

    def test_stop_unreadable_and_refused_paths(self):   # SS1-SS5 SS10 SS17
        self.seed(("%064d" % 1, "controller", 1, "session", "", ""))
        before = self.recs()
        d = os.path.join(self.tmp, "adir")
        os.makedirs(d)
        fifo = os.path.join(self.tmp, "fifo")
        os.mkfifo(fifo)
        bad = os.path.join(self.tmp, "bad.jsonl")
        with open(bad, "wb") as fh:
            fh.write(b"\xff\n")
        for path in (None, 5, [], {}, True, "", "rel.jsonl", "/x\u0000y", os.path.join(self.tmp, "absent"), d, fifo, bad):
            with self.subTest(path=path):
                p = run_hook("SubagentStop", payload("SubagentStop", self.R, agent_transcript_path=path, agent_type=""),
                             self.env, FW)
                self.assertEqual((p.returncode, p.stdout, p.stderr), (0, "", ""))
                self.assertEqual(self.recs(), before)
        pa = run_hook("SubagentStop", {k: v for k, v in payload("SubagentStop", self.R).items()
                                       if k != "agent_transcript_path"}, self.env, FW)
        self.assertEqual((pa.returncode, pa.stdout, pa.stderr), (0, "", ""))

    def test_stop_handle_always_empty_outcome(self):   # SS17 SS13
        ctx = self.hand(event="SubagentStop", raw={"agent_transcript_path": "/nope"})
        o = subagent_stop.handle(ctx)
        self.assertEqual((type(o), o.deny, o.context, o.text), (Outcome, [], [], []))
        tp = os.path.join(self.tmp, "t.jsonl")
        write(tp, user_line("rec") + "\n")
        self.seed((session.prompt_sha("rec"), "controller", 1, "session", "", ""))
        with mock.patch("gates.lib.session._write", side_effect=session.SessionUnavailable("disk")):
            o = subagent_stop.handle(self.hand(event="SubagentStop", raw={"agent_transcript_path": tp}))
        self.assertEqual((o.deny, o.context, o.text), ([], [], []))
        self.assertEqual(len(self.recs()), 1)

    def test_session_start_resets_counts(self):   # HN8
        self.seed(("%064d" % 1, "controller", 1, "session", "", ""))
        p = run_hook("SessionStart", payload("SessionStart", self.R, session_id="s1", source="startup"), self.env, FW)
        self.assertEqual(p.returncode, 0)
        self.assertEqual(self.recs(), [])

    def test_parallel_dispatches_both_counted(self):   # HQ1 HQ2
        results = []
        ps = [real_prompt("controller", "opus", brief="par%d" % i) for i in range(2)]

        def go(p):
            results.append(self.hk(tin(p, model="opus")))
        ts = [threading.Thread(target=go, args=(p,)) for p in ps]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        self.assertEqual([r.returncode for r in results], [0, 0])
        self.assertEqual(len(self.recs()), 2)
        self.set_config(profile="strict", limits={"max_concurrent": 3})   # 2 live + 1 allowed, then at the cap
        results.clear()
        ps = [real_prompt("controller", "opus", brief="cap%d" % i) for i in range(2)]
        ts = [threading.Thread(target=go, args=(p,)) for p in ps]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        self.assertEqual(sorted(r.returncode for r in results), [0, 2])
        self.assertIn("FAIL dispatch.concurrency: 3 running + 1 exceeds max_concurrent 3",
                      [r for r in results if r.returncode == 2][0].stderr)
        self.assertEqual(len(self.recs()), 3)

    def test_lock_released_on_error_paths(self):   # HX1
        with mock.patch("gates.hooks.pre_agent.gate_dispatch.check", side_effect=KeyboardInterrupt()):
            with self.assertRaises(KeyboardInterrupt):
                pre_agent.handle(self.hand(tool_input=tin("P")))
        self.assertEqual(self.hk(tin(real_prompt("implementer"))).returncode, 0)

    def test_write_failure_on_exit(self):   # HS6 (Q5)
        with mock.patch("gates.lib.session._write", side_effect=session.SessionUnavailable("disk full")):
            out, _ = self.seen(self.hand(tool_input=tin("P")))
        self.assertEqual(out.deny, ["FAIL hook.agent.session: disk full" + WAY])

    def test_corrupt_store_refuses_gated_dispatch(self):   # HS4
        write(os.path.join(self.pd, "sessions", "s1.yml"), "schema: [\n")
        p = self.hk(tin(real_prompt("implementer")))
        self.assertEqual(p.returncode, 2)
        self.assertTrue(p.stderr.startswith("FAIL dispatch.input: input: dispatcher must be an object\n"))
        self.assertIn("FAIL hook.agent.session: the session state file", p.stderr)


class Worktrees(Base):
    def line(self, path, role="implementer", extra=""):
        return real_prompt(role, "opus" if role == "controller" else "sonnet", task="t\nworktree: %s\n%s" % (path, extra))

    def wo(self, prompt, ctx=None, state=None):
        return pre_agent.worktree_of(ctx or self.hand(), prompt, None, state)

    def test_worktree_bound_at_dispatch(self):   # WT1 WT5 WT6 WT34
        self.assertEqual(self.wo(real_prompt("implementer")), (self.R, []))
        self.assertEqual(self.wo(self.line(self.R)), (self.R, []))
        self.program()
        self.assertEqual(self.wo(self.line(self.stream_wt)), (self.stream_wt, []))
        self.assertEqual(self.wo(self.line(self.R)), (self.R, []))
        p = self.hk(tin(self.line(self.stream_wt), model="sonnet"))   # session -> implementer on the status worktree
        self.assertEqual(p.stderr.count("hook.agent"), 0, p.stderr)
        dispatch_prompt = real_prompt("stream_controller", "opus", brief="program: %s\nstream: s1" % NAME,
                                      task="t\nworktree: %s" % self.stream_wt)
        p = self.hk(tin(dispatch_prompt, model="opus"))
        self.assertEqual((p.returncode, p.stderr), (0, ""))
        self.assertEqual(self.recs()[-1]["worktree"], self.stream_wt)
        self.assertEqual(self.recs()[-1]["branch"], NAME + "/s1/main")

    def test_worker_without_line_live(self):   # WT2 WT3 WT4
        self.program()
        want = (  "", ["hook.agent.worktree: a worker in a live program names its worktree"])
        self.assertEqual(self.wo(real_prompt("implementer")), want)
        for role in ("stream_controller", "controller", "program_controller"):
            self.assertEqual(self.wo(real_prompt(role, "opus")), ("", []), role)
        self.assertEqual(self.wo(real_prompt("implementer").replace("## Role\nimplementer", "## Role\nbogus")), want)
        p = self.hk(tin(real_prompt("implementer")))
        self.assertEqual(p.returncode, 2)
        self.assertIn("FAIL hook.agent.worktree: a worker in a live program names its worktree" + WAY, p.stderr)
        self.assertEqual(self.recs(), [])

    def test_worktree_not_allowed_refused(self):   # WT8 WT9
        sib = self.add_wt("sib", "-b", "feature")
        want = ("", ["hook.agent.worktree: %s is not one of the dispatcher's worktrees" % sib])
        self.assertEqual(self.wo(self.line(sib)), want)
        self.program()
        self.assertEqual(self.wo(self.line(sib)), want)

    def test_group_worktree_from_stream_bound(self):   # WT10 WT12 WT13 WT14 WT15 WT16
        self.program()
        grp = self.add_wt("grp", "-b", NAME + "/s1/g1")
        other = self.add_wt("oth", "-b", NAME + "/s2/g1")
        s2 = self.add_wt("s2main", "-b", NAME + "/s2/main")
        sib = self.add_wt("sibg", "-b", NAME + "/s1/g2")
        bad = {n: self.add_wt("b" + str(i), "-b", NAME + "/s1/" + n) for i, n in enumerate(("G9", "a_b", "-x"))}
        ok = {n: self.add_wt("o" + str(i), "-b", NAME + "/s1/" + n) for i, n in enumerate(("a-b", "0x"))}
        pp = real_prompt("implementer")
        self.sub("a1", "stream prompt")
        st = {"dispatches": []}
        session.add_dispatch(st, session.prompt_sha("stream prompt"), "stream_controller", 1, "session",
                             self.stream_wt, NAME + "/s1/main")
        ctx = self.hand(agent_id="a1")
        disp = {"id": "stream_controller"}
        wo = lambda w: pre_agent.worktree_of(ctx, self.line(w), disp, st)
        self.assertEqual(wo(grp), (grp, []))
        self.assertEqual(wo(self.stream_wt), (self.stream_wt, []))
        for n, w in ok.items():
            self.assertEqual(wo(w), (w, []), n)
        for name, w in [("other stream group", other), ("other stream main", s2), ("g2 sibling ok as group", None)] + list(bad.items()):
            if w is None:
                self.assertEqual(wo(sib), (sib, []))
                continue
            with self.subTest(name):
                self.assertEqual(wo(w)[0], "")
                self.assertTrue(wo(w)[1][0].startswith("hook.agent.worktree: "))
        # WT14: a dispatcher recorded on a group branch cannot bind a sibling group
        st2 = {"dispatches": []}
        session.add_dispatch(st2, session.prompt_sha("stream prompt"), "controller", 2, "session", grp, NAME + "/s1/g1")
        self.assertEqual(pre_agent.worktree_of(ctx, self.line(sib), disp, st2)[0], "")
        # WT15: the record's branch decides, not the worktree's branch now
        git(self.stream_wt, "checkout", "-q", "-b", "elsewhere")
        self.assertEqual(wo(grp), (grp, []))

    def test_two_lines_and_format(self):   # WT17 WT18 WT19 WT20 WT21
        two = "two worktree: lines in ## Task"
        want = ("", ["hook.agent.worktree: " + two])
        a = self.add_wt("a", "-b", "fa")
        self.assertEqual(self.wo(real_prompt("implementer", task="t\nworktree: %s\nworktree: %s" % (self.R, a))), want)
        self.assertEqual(self.wo(real_prompt("implementer", task="t\nworktree: %s\nworktree: %s" % (a, self.R))), want)
        fmt = ("", ["hook.agent.worktree: the line must read 'worktree: <absolute path>'"])
        for line in ("worktree: rel/wt", "worktree:/x", "worktree:  /x"):
            self.assertEqual(self.wo(real_prompt("implementer", task="t\n" + line)), fmt, line)
        for line in (" worktree: /x", "Worktree: /x"):
            self.assertEqual(self.wo(real_prompt("implementer", task="t\n" + line)), (self.R, []), line)
        self.assertEqual(self.wo(real_prompt("implementer", brief="worktree: /x\nworktree: /y")), (self.R, []))
        self.assertEqual(self.wo("no headings at all\nworktree: /x"), (self.R, []))
        self.assertEqual(self.wo(real_prompt("implementer", task="prose\nmore\nworktree: %s" % self.R)), (self.R, []))

    def test_missing_subdir_and_other_repository(self):   # WT22 WT23 WT24 WT28 WT29
        refused = lambda p: ("", ["hook.agent.worktree: %s is not the top level of a worktree of this repository"
                                  % pre_agent.safe_text(p)])
        other = os.path.join(self.tmp, "otherrepo")
        os.makedirs(other)
        make_repo(other)
        sub = os.path.join(self.R, "sub")
        os.makedirs(sub)
        for p in ("/nope", sub, other, "/", self.R + " ", self.R + "\r", "/tmp/x\0y", "/tmp/x\ud800y"):
            with self.subTest(p=p):
                got = self.wo(real_prompt("implementer", task="t\nworktree: " + p))
                self.assertEqual(got, refused(p))

    def test_symlinks_and_spellings(self):   # WT25 WT26 WT27 WT28
        self.program()
        link = os.path.join(self.tmp, "link")
        os.symlink(self.stream_wt, link)
        self.assertEqual(self.wo(self.line(link)), (self.stream_wt, []))
        for sp in (self.stream_wt + "/", self.stream_wt + "/.", os.path.join(self.stream_wt, "..", os.path.basename(self.stream_wt))):
            self.assertEqual(self.wo(self.line(sp)), (self.stream_wt, []), sp)
        sublink = os.path.join(self.tmp, "sublink")
        os.makedirs(os.path.join(self.stream_wt, "d"))
        os.symlink(os.path.join(self.stream_wt, "d"), sublink)
        dangling = os.path.join(self.tmp, "dangling")
        os.symlink(os.path.join(self.tmp, "nowhere"), dangling)
        filelink = os.path.join(self.tmp, "filelink")
        os.symlink(self.main_t, filelink)
        for l in (sublink, dangling, filelink):
            self.assertEqual(self.wo(self.line(l))[0], "", l)

    def test_detached_worktree_empty_branch(self):   # WT30
        d = self.add_wt("det", "--detach")
        self.program()
        # allow it through the status page
        git(self.R, "checkout", "-q", NAME + "/integration")
        write(os.path.join(self.R, PROGRAMS, NAME, "status.md"),
              "# status\n\n" + HEADER + status_row("s1", d).replace("20261101-prog", NAME))
        commit_all(self.R, "status2")
        git(self.R, "checkout", "-q", "main")
        pr = real_prompt("stream_controller", "opus", brief="program: %s\nstream: s1" % NAME,
                         task="t\nworktree: %s" % d)
        p = self.hk(tin(pr, model="opus"))
        self.assertEqual((p.returncode, p.stderr), (0, ""))
        self.assertEqual((self.recs()[-1]["worktree"], self.recs()[-1]["branch"]), (d, ""))

    def test_no_line_subagent_binds_only_what_it_holds(self):   # WT31 WT33 (Q3)
        w = self.add_wt("w1", "-b", "fw")
        self.sub("a1", "PP")
        st = {"dispatches": []}
        session.add_dispatch(st, session.prompt_sha("PP"), "controller", 2, "session", w, "fw")
        ctx = self.hand(agent_id="a1")
        self.assertEqual(pre_agent.worktree_of(ctx, real_prompt("implementer"), {"id": "controller"}, st), ("", []))
        self.assertEqual(pre_agent.worktree_of(ctx, self.line(w), {"id": "controller"}, st), (w, []))

    def test_unknown_dispatcher_with_line_refused(self):   # WT32
        self.sub("a1", "PP")
        got = pre_agent.worktree_of(self.hand(agent_id="a1"), self.line(self.R), None, {"dispatches": []})
        self.assertEqual(got[0], "")
        self.assertEqual(got[1][0], "hook.agent.worktree: %s is not one of the dispatcher's worktrees" % self.R)

    def test_allowed_fails_do_not_deny_a_valid_line(self):   # WT37 (Q4)
        self.program()
        git(self.R, "checkout", "-q", NAME + "/integration")
        with open(os.path.join(self.R, PROGRAMS, NAME, "status.md"), encoding="utf-8") as fh:
            txt = fh.read()
        write(os.path.join(self.R, PROGRAMS, NAME, "status.md"), txt + status_row("s2", "/gone/missing").replace("20261101-prog", NAME))
        commit_all(self.R, "stale")
        git(self.R, "checkout", "-q", "main")
        self.assertEqual(self.wo(self.line(self.stream_wt)), (self.stream_wt, []))
        sib = self.add_wt("sib2", "-b", "fz")
        got = self.wo(self.line(sib))
        self.assertEqual(got[0], "")
        self.assertGreater(len(got[1]), 1)

    def test_live_programs_raises_in_worktree_of(self):   # WT38
        from gates.lib.result import GateError
        with mock.patch("gates.lib.programs.live_programs", side_effect=GateError("x")):
            self.assertEqual(self.wo(real_prompt("implementer"))[0], "")
            self.assertEqual(self.wo(real_prompt("controller", "opus")), ("", []))

    def test_session_cwd_variants(self):   # WT35 WT36
        sub = os.path.join(self.R, "sub")
        os.makedirs(sub)
        ctx = self.hand(cwd=sub)
        self.assertEqual(self.wo(real_prompt("implementer"), ctx), (self.R, []))
        self.assertEqual(self.wo(self.line(sub), ctx)[0], "")
        wl = self.add_wt("lw", "-b", "fl")
        ctx = self.hand(cwd=wl, root=wl)
        self.assertEqual(self.wo(real_prompt("implementer"), ctx), (wl, []))
        self.assertEqual(self.wo(self.line(self.R), ctx)[0], "")

    def test_worktree_vanishes_before_record(self):   # WT40 HA12 HA8 HA9
        calls = []
        real_bb = pre_agent.worktrees.bound_branch

        def bb(p):
            calls.append(p)
            return real_bb(p)
        with mock.patch("gates.hooks.pre_agent.worktrees.bound_branch", bb):
            out, _ = self.seen(self.hand(tool_input=tin(real_prompt("implementer"))))
        self.assertEqual(calls.count(self.R), 1)     # HA8: read once at record time (plus the line-check path not used)
        with mock.patch("gates.hooks.pre_agent.worktrees.bound_branch", side_effect=pre_agent.GateError("gone")):
            with self.assertRaises(pre_agent.GateError):
                self.seen(self.hand(tool_input=tin(real_prompt("implementer", brief="v"))))
        self.assertEqual(len(self.recs()), 1)
        self.program()
        calls.clear()
        with mock.patch("gates.hooks.pre_agent.worktrees.bound_branch", bb):
            self.seen(self.hand(tool_input=tin(real_prompt("controller", "opus", brief="nobind"))))
        self.assertEqual(calls, [])
        self.assertEqual((self.recs()[-1]["worktree"], self.recs()[-1]["branch"]), ("", ""))

    def test_worktree_fails_join_deny(self):   # HR9 HR10 HR11
        sib = self.add_wt("sib3", "-b", "fy")
        p = self.hk(tin(self.line(sib)))
        self.assertEqual(p.returncode, 2)
        self.assertEqual(p.stderr, "FAIL hook.agent.worktree: %s is not one of the dispatcher's worktrees%s\n" % (sib, WAY))
        self.assertEqual(self.recs(), [])
        p = self.hk(tin(self.line(sib), model="opus"))     # gate FAIL first, then the worktree line
        lines = p.stderr.split("\n")[:-1]
        self.assertTrue(lines[0].startswith("FAIL dispatch.model"))
        self.assertTrue(lines[-1].startswith("FAIL hook.agent.worktree"))
        self.set_config(profile="light")
        p = self.hk({"prompt": self.line(sib)})
        self.assertEqual(p.returncode, 2)
        self.assertEqual(self.recs(), [])

    def hz_wo(self, text):
        return self.wo(self.line(text))

    def test_hardening_worktree_symlink(self):   # HZ1
        self.program()
        other = self.add_wt("unallowed", "-b", "fq")
        a, b, c = (os.path.join(self.tmp, n) for n in ("l1", "l2", "l3"))
        os.symlink(self.stream_wt, a)
        os.symlink(other, b)
        os.symlink(os.path.join(self.tmp, "gone"), c)
        self.assertEqual(self.hz_wo(a), (self.stream_wt, []))
        self.assertEqual(self.hz_wo(b)[0], "")
        self.assertTrue(self.hz_wo(b)[1][0].startswith("hook.agent.worktree: "))
        self.assertEqual(self.hz_wo(c)[0], "")
        self.assertTrue(self.hz_wo(c)[1][0].startswith("hook.agent.worktree: "))

    def test_hardening_worktree_kinds(self):   # HZ2
        self.program()
        d = os.path.join(self.stream_wt, "subdir")
        os.makedirs(d)
        for p in (self.main_t, d):
            got = self.hz_wo(p)
            self.assertEqual(got, ("", ["hook.agent.worktree: %s is not the top level of a worktree of this repository" % p]))

    def test_hardening_fifo_paths(self):   # HZ3
        fifo = os.path.join(self.tmp, "ff")
        os.mkfifo(fifo)
        for p in (fifo, "/dev/null"):
            self.assertEqual(self.hz_wo(p)[0], "")
            self.assertTrue(self.hz_wo(p)[1][0].startswith("hook.agent.worktree: "))
        st = {"dispatches": []}
        session.add_dispatch(st, session.prompt_sha("P"), "controller", 2, "session", self.R, "main")
        d = os.path.join(self.tmp, "s1", "subagents", "agent-a1.jsonl")
        for kind in ("fifo", "dir", "null"):
            if os.path.lexists(d):
                os.rmdir(d) if os.path.isdir(d) else os.remove(d)
            os.makedirs(os.path.dirname(d), exist_ok=True)
            if kind == "fifo":
                os.mkfifo(d)
            elif kind == "dir":
                os.makedirs(d)
            else:
                os.symlink("/dev/null", d)
            self.assertIsNone(pre_agent.dispatcher(self.hand(agent_id="a1"), st), kind)
        self.seed((session.prompt_sha("P"), "controller", 1, "session", "", ""))
        for path in (fifo, os.path.join(self.tmp, "s1"), "/dev/null"):
            p = self.stop(path)
            self.assertEqual((p.returncode, p.stdout, p.stderr), (0, "", ""))
            self.assertEqual(len(self.recs()), 1)

    def test_hardening_parent_symlink(self):   # HZ4
        self.program()
        parent = os.path.join(self.tmp, "parentlink")
        os.symlink(os.path.dirname(self.stream_wt), parent)
        via = os.path.join(parent, os.path.basename(self.stream_wt))
        self.assertEqual(self.hz_wo(via), (self.stream_wt, []))

    def test_hardening_nested_worktrees(self):   # HZ5
        self.program()
        inner = os.path.join(self.stream_wt, "nested")
        git(self.stream_wt, "worktree", "add", "-q", "-b", NAME + "/s1/gn", inner)
        inner = real(inner)
        self.sub("a1", "stream prompt")
        st = {"dispatches": []}
        session.add_dispatch(st, session.prompt_sha("stream prompt"), "stream_controller", 1, "session",
                             self.stream_wt, NAME + "/s1/main")
        ctx, disp = self.hand(agent_id="a1"), {"id": "stream_controller"}
        wo = lambda w: pre_agent.worktree_of(ctx, self.line(w), disp, st)
        self.assertEqual(wo(self.stream_wt), (self.stream_wt, []))
        self.assertEqual(wo(inner), (inner, []))
        self.assertEqual(wo(os.path.join(inner, "..")), (self.stream_wt, []))   # the parent is never the nested top
        st2 = {"dispatches": []}
        session.add_dispatch(st2, session.prompt_sha("stream prompt"), "controller", 2, "session", inner, NAME + "/s1/gn")
        self.assertEqual(pre_agent.worktree_of(ctx, self.line(self.stream_wt), disp, st2)[0], "")

    def test_hardening_unusual_names(self):   # HZ6
        for n in ("sp ace", "caf\u00e9"):
            w = self.add_wt(n, "-b", "u" + str(len(n)))
            self.assertEqual(self.wo(self.line(w), self.hand(), None)[0], "")   # not allowed for session, but resolved
            self.assertEqual(self.wo(self.line(w))[1][0], "hook.agent.worktree: %s is not one of the dispatcher's worktrees" % w)
        for bad in ("/x\0y", "/x\ud800y", self.R + " ", self.R + "\r"):
            self.assertTrue(self.hz_wo(bad)[1][0].endswith("is not the top level of a worktree of this repository"), bad)

    def test_hardening_outside_root(self):   # HZ7
        other = os.path.join(self.tmp, "orepo")
        os.makedirs(other)
        make_repo(other)
        nowhere = os.path.join(self.tmp, "norepo")
        os.makedirs(nowhere)
        for p in (other, "/", nowhere):
            self.assertEqual(self.hz_wo(p)[0], "")
            self.assertTrue(self.hz_wo(p)[1][0].startswith("hook.agent.worktree: "), p)


def seed_ctl(case, role, depth, prompt, parent="session", wt=None, branch="main"):
    case.seed((session.prompt_sha(prompt), role, depth, parent, case.R if wt is None else wt, branch))


class More(Base):
    def env_with(self, **kw):
        e = dict(self.env)
        e.update(kw)
        return e

    def chain(self, role, depth, tag="P0"):
        """A recorded dispatcher agent ``a1`` of ``role`` at ``depth`` (its prompt is ``tag``)."""
        seed_ctl(self, role, depth, tag)
        self.sub("a1", tag)

    # ---- transcript edges
    def test_dispatcher_transcript_max_bytes(self):   # DS15
        st = {"dispatches": []}
        probe = len(user_line("").encode("utf-8")) + 1
        path = os.path.join(self.tmp, "s1", "subagents", "agent-a1.jsonl")
        for total, found in ((4194304, True), (4194305, False)):
            text = "A" * (total - probe)
            st = {"dispatches": []}
            session.add_dispatch(st, session.prompt_sha(text), "controller", 2, "session", self.R, "main")
            write(path, user_line(text) + "\n")
            self.assertEqual(os.path.getsize(path), total)
            self.assertEqual(pre_agent.dispatcher(self.hand(agent_id="a1"), st) is not None, found, total)

    def test_fork_dispatcher_unknown(self):   # DS21
        write(os.path.join(self.tmp, "s1", "subagents", "agent-a1.jsonl"), user_line("<fork-boilerplate> do x") + "\n")
        p = self.hk(tin(real_prompt("implementer")), agent_id="a1", agent_type="fork")
        self.assertEqual((p.returncode, p.stderr), (2, "FAIL dispatch.input: input: dispatcher must be an object\n"))
        self.set_config(profile="light")
        p = self.hk({"prompt": "x"}, agent_id="a1", agent_type="fork")
        self.assertEqual((p.returncode, p.stderr), (0, ""))
        self.assertEqual(self.recs(), [])

    def test_depth_digit_edge(self):   # DS23 V1(c) V1(f)
        for digits, want in ((600, "FAIL dispatch.depth: dispatcher depth 1%s + 1 + 0 level(s) below implementer exceeds max_depth 3" % ("0" * 599)),
                             (601, "FAIL dispatch.input: ")):
            self.set_config(profile="strict")
            pd = "P-%d" % digits
            seed_ctl(self, "controller", 10 ** (digits - 1), pd)
            self.sub("a%d" % digits, pd)
            p = self.hk(tin(real_prompt("implementer", brief="d%d" % digits)), agent_id="a%d" % digits)
            self.assertEqual(p.returncode, 2)
            self.assertIn(want, p.stderr, digits)
        seed_ctl(self, "controller", 10 ** 999, "P-1000")     # (f) the store takes 1000 characters
        with self.assertRaises(session.SessionUnavailable):
            seed_ctl(self, "controller", 10 ** 1000, "P-1001")

    def test_session_file_digit_edge(self):   # V1(f)
        seed_ctl(self, "controller", 10 ** 999, "Q")
        self.assertEqual(self.recs()[-1]["depth"], 10 ** 999)

    def test_transcript_digit_edge(self):   # V1(b)
        st = {"dispatches": []}
        session.add_dispatch(st, session.prompt_sha("AB"), "controller", 2, "session", self.R, "main")
        path = os.path.join(self.tmp, "s1", "subagents", "agent-a1.jsonl")
        for n, found in ((4300, True), (4301, False)):
            write(path, '{"type":"assistant","n":%s}\n' % ("1" * n) + user_line("AB") + "\n")
            self.assertEqual(pre_agent.dispatcher(self.hand(agent_id="a1"), st) is not None, found, n)

    def test_tool_input_digit_limit(self):   # HT9 V1(a)
        for n, code in ((4300, 0), (4301, 2)):
            pl = payload("PreToolUse", self.R, tool_name="Agent", session_id="s1",
                         tool_input=dict(tin(real_prompt("implementer", brief="n%d" % n)), big="@@BIG@@"))
            data = json.dumps(pl).replace('"@@BIG@@"', "1" * n).encode("utf-8")
            p = run_hook("PreToolUse", data, self.env, FW)
            self.assertEqual(p.returncode, code, p.stderr)
            if code:
                self.assertIn("hook.input: input is not valid JSON: integer longer than 4300 digits", p.stderr)

    def test_limits_digit_edge(self):   # HN13 V1(e)
        self.set_config(limits={"max_concurrent": 10 ** 599})
        self.assertEqual(self.hk(tin(real_prompt("implementer"))).returncode, 0)
        self.set_config(limits={"max_concurrent": 10 ** 600})
        p = self.hk(tin(real_prompt("implementer", brief="x")))
        self.assertEqual(p.returncode, 2)
        self.assertTrue(p.stderr.startswith("FAIL hook.agent.config: "))

    # ---- required and the gate
    def test_required_true_when_live_programs_raises(self):   # HC5
        from gates.lib.result import GateError
        self.set_config(profile="light")
        with mock.patch("gates.lib.programs.live_programs", side_effect=GateError("x")):
            out, calls = self.seen(self.hand(tool_input=tin("P")))
        self.assertEqual(len(calls), 1)
        self.assertNotIn("program_live", calls[0][1])

    def test_exception_group_from_gate_denied(self):   # HR8 V3
        import builtins
        cls = getattr(builtins, "ExceptionGroup", None)
        exc = cls("g", [ValueError("v")]) if cls else type("ExceptionGroup", (Exception,), {})("g")
        with mock.patch("gates.hooks.pre_agent.gate_dispatch.check", side_effect=exc):
            out = pre_agent.handle(self.hand(tool_input=tin("P")))
        self.assertEqual(len(out.deny), 1)
        self.assertTrue(out.deny[0].startswith("FAIL dispatch.input: ExceptionGroup: "), out.deny)

    def test_baseexception_group_from_gate_propagates(self):   # HR7 V3
        import builtins
        cls = getattr(builtins, "BaseExceptionGroup", None)
        exc = cls("g", [KeyboardInterrupt()]) if cls else type("Stand", (BaseException,), {})("g")
        with mock.patch("gates.hooks.pre_agent.gate_dispatch.check", side_effect=exc):
            with self.assertRaises(BaseException):
                pre_agent.handle(self.hand(tool_input=tin("P")))
        self.assertEqual(self.recs(), [])

    def test_program_live_claim_checked_by_gate(self):   # HP5
        with mock.patch.object(pre_agent, "_program_live", return_value=True):
            out = pre_agent.handle(self.hand(tool_input=tin(real_prompt("implementer"))))
        self.assertTrue(any("program_live is true in the input, but false in git" in ln for ln in out.deny), out.deny)

    # ---- depth
    def test_depth_session_and_stream(self):   # HD1 HD2
        self.program()
        ps = real_prompt("stream_controller", "opus", brief="program: %s\nstream: s1" % NAME)
        p = self.hk(tin(ps, model="opus"))
        self.assertEqual((p.returncode, p.stderr), (0, ""))
        self.assertEqual(self.recs()[-1]["depth"], 1)
        self.sub("a1", ps)
        pc = real_prompt("controller", "opus", brief="program: %s\nstream: s1" % NAME)
        p = self.hk(tin(pc, model="opus"), agent_id="a1")
        self.assertEqual((p.returncode, p.stderr), (0, ""))
        self.assertEqual(self.recs()[-1]["depth"], 2)

    def test_depth_limit_six_env(self):   # HD5
        env = self.env_with(CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH="5")
        cases = [("controller", 2, "controller", 0), ("controller", 4, "controller", 0), ("controller", 5, "controller", 2),
                 ("controller", 5, "implementer", 0), ("controller", 6, "implementer", 2)]
        for i, (drole, depth, child, code) in enumerate(cases):
            tag = "D%d" % i
            seed_ctl(self, drole, depth, tag)
            self.sub("a%d" % i, tag)
            model = "opus" if child == "controller" else "sonnet"
            p = self.hk(tin(real_prompt(child, model, brief="c%d" % i), model=model), agent_id="a%d" % i, env=env)
            self.assertEqual(p.returncode, code, (depth, child, p.stderr))
            if code:
                self.assertIn("FAIL dispatch.depth", p.stderr)

    def test_depth_config_min(self):   # HD6
        self.set_config(limits={"max_depth": 2})
        self.chain("controller", 1)
        p = self.hk(tin(real_prompt("controller", "opus"), model="opus"), agent_id="a1",
                    env=self.env_with(CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH="5"))
        self.assertEqual(p.returncode, 2)
        self.assertIn("FAIL dispatch.depth: dispatcher depth 1 + 1 + 1 level(s) below controller exceeds max_depth 2", p.stderr)

    def test_depth_env_value_edge(self):   # HD7 V1(d)
        name = "CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH"
        good = {"1": 0, "9" * 600: 0}
        bad = ["0", "05", "+5", " 5", "5.0", "-1", "", "9" * 601, "9" * 4300, "9" * 4301]
        for i, (v, code) in enumerate(list(good.items()) + [(b, 2) for b in bad]):
            p = self.hk(tin(real_prompt("implementer", brief="e%d" % i)), env=self.env_with(**{name: v}))
            self.assertEqual(p.returncode, code, (v[:10], p.stderr[:200]))
            if code:
                self.assertIn("FAIL dispatch.input: input: %s must be a decimal integer of at least 1" % name, p.stderr)

    def test_stream_dispatch_without_program_denied(self):   # HD9
        self.chain("stream_controller", 1)
        p = self.hk(tin(real_prompt("controller", "opus"), model="opus"), agent_id="a1")
        self.assertEqual(p.returncode, 2)
        self.assertIn("FAIL dispatch.dispatcher: stream_controller may not dispatch controller (program_live false; "
                      "allowed: session, controller)", p.stderr)

    # ---- counts
    def test_child_cap_at_limit(self):   # HN2 HN3
        self.set_config(limits={"max_children": {"controller": 2}})
        self.chain("controller", 1)
        self.seed(("%064d" % 1, "implementer", 2, "a1", "", ""))
        p = self.hk(tin(real_prompt("implementer", brief="1")), agent_id="a1")
        self.assertEqual(p.returncode, 0, p.stderr)       # 1 live child + 1 = 2 <= 2: the new one is recorded
        p = self.hk(tin(real_prompt("implementer", brief="2")), agent_id="a1")
        self.assertEqual(p.returncode, 2)
        self.assertIn("FAIL dispatch.children: 2 running children + 1 exceeds limits.max_children.controller 2", p.stderr)
        self.seed(*[("%064d" % (10 + i), "controller", 1, "session", "", "") for i in range(5)])   # HN3: no key session
        self.assertEqual(self.hk(tin(real_prompt("implementer", brief="3"))).returncode, 0)

    def test_concurrency_at_limit(self):   # HN5
        self.set_config(limits={"max_concurrent": 3})
        self.seed(*[("%064d" % i, "controller", 1, "session", "", "") for i in range(2)])
        self.assertEqual(self.hk(tin(real_prompt("implementer", brief="a"))).returncode, 0)
        p = self.hk(tin(real_prompt("implementer", brief="b")))
        self.assertEqual(p.returncode, 2)
        self.assertIn("FAIL dispatch.concurrency: 3 running + 1 exceeds max_concurrent 3", p.stderr)

    def test_session_start_keeps_on_clear_and_compact(self):   # HN9
        for src, kept in (("clear", 1), ("compact", 1), (None, 0), ("weird", 0)):
            self.seed(("%064d" % 1, "controller", 1, "session", "", ""))
            pl = payload("SessionStart", self.R, session_id="s1")
            if src is None:
                del pl["source"]
            else:
                pl["source"] = src
            p = run_hook("SessionStart", pl, self.env, FW)
            self.assertEqual(p.returncode, 0)
            self.assertEqual(len(self.recs()), kept, src)
            with session.locked(self.env, "s1") as st:
                st["dispatches"] = []

    # ---- parallel and the lock
    def run_threads(self, prompts, **kw):
        res = []
        ts = [threading.Thread(target=lambda p=p: res.append(self.hk(tin(p), **kw))) for p in prompts]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        return res

    def test_parallel_children_cap(self):   # HQ3
        self.set_config(limits={"max_children": {"session": 1}})
        res = self.run_threads([real_prompt("implementer", brief="q%d" % i) for i in range(2)])
        self.assertEqual(sorted(r.returncode for r in res), [0, 2])
        self.assertEqual(len(self.recs()), 1)

    def test_parallel_eight_no_lost_update(self):   # HQ4
        res = self.run_threads([real_prompt("implementer", brief="e%d" % (i % 4)) for i in range(8)])
        self.assertEqual([r.returncode for r in res], [0] * 8)
        self.assertEqual(len(self.recs()), 8)

    def test_stop_and_dispatch_race(self):   # HQ6
        pa = real_prompt("controller", "opus", brief="old")
        seed_ctl(self, "controller", 1, pa)
        tp = os.path.join(self.tmp, "agent-old.jsonl")
        write(tp, user_line(pa) + "\n")
        out = []
        t1 = threading.Thread(target=lambda: out.append(self.stop(tp)))
        t2 = threading.Thread(target=lambda: out.append(self.hk(tin(real_prompt("implementer", brief="new")))))
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        self.assertEqual([o.returncode for o in out], [0, 0])
        self.assertEqual([r["role"] for r in self.recs()], ["implementer"])

    def test_lock_timeout_refuses_gated_dispatch(self):   # HS5 HQ5
        import fcntl
        self.seed(("%064d" % 1, "controller", 1, "session", "", ""))
        fd = os.open(os.path.join(self.pd, "sessions", "s1.lock"), os.O_RDWR | os.O_CREAT, 0o600)
        self.addCleanup(os.close, fd)
        fcntl.flock(fd, fcntl.LOCK_EX)
        real_locked = session.locked
        with mock.patch("gates.hooks.pre_agent.session.locked", lambda env, sid: real_locked(env, sid, timeout_s=1)):
            out = pre_agent.handle(self.hand(tool_input=tin(real_prompt("implementer"))))
        self.assertEqual(out.deny[0], "FAIL dispatch.input: input: dispatcher must be an object")
        self.assertIn("held by another process", out.deny[1])
        self.assertTrue(out.deny[1].startswith("FAIL hook.agent.session: "))
        fcntl.flock(fd, fcntl.LOCK_UN)
        self.assertEqual(len(self.recs()), 1)

    def test_lock_held_whole_call(self):   # HS8
        calls = []
        real_locked = session.locked

        def counting(env, sid):
            calls.append(1)
            return real_locked(env, sid)
        with mock.patch("gates.hooks.pre_agent.session.locked", counting):
            self.seen(self.hand(tool_input=tin("P")))
        self.assertEqual(len(calls), 1)

    def test_session_id_128(self):   # HS9
        for n, code in ((1, 0), (128, 0), (129, 2)):
            sid = "a" * n
            p = self.hk(tin(real_prompt("implementer", brief="s%d" % n)), session_id=sid)
            self.assertEqual(p.returncode, code, p.stderr)
        self.assertEqual(len(self.recs("a" * 128)), 1)

    # ---- SubagentStop edges
    def test_stop_store_unavailable(self):   # SS12
        tp = os.path.join(self.tmp, "t.jsonl")
        write(tp, user_line("rec") + "\n")
        env = dict(self.env)
        del env["CLAUDE_PLUGIN_DATA"]
        p = run_hook("SubagentStop", payload("SubagentStop", self.R, agent_transcript_path=tp), env, FW)
        self.assertEqual((p.returncode, p.stdout, p.stderr), (0, "", ""))
        write(os.path.join(self.pd, "sessions", "s1.yml"), "schema: [\n")
        p = self.stop(tp)
        self.assertEqual((p.returncode, p.stdout, p.stderr), (0, "", ""))
        with open(os.path.join(self.pd, "sessions", "s1.yml"), encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "schema: [\n")

    def test_stop_relative_path_never_read(self):   # SS3 (CD9): a relative path that resolves from the hook's own directory
        rec = os.path.join(self.tmp, "rel.jsonl")
        write(rec, user_line("rec") + "\n")
        self.seed((session.prompt_sha("rec"), "controller", 1, "session", "", ""))
        rel = os.path.relpath(rec, FW)
        self.assertFalse(os.path.isabs(rel))
        p = self.stop(rel)
        self.assertEqual((p.returncode, p.stdout, p.stderr), (0, "", ""))
        self.assertEqual(len(self.recs()), 1)
        self.assertEqual(self.stop(rec).returncode, 0)
        self.assertEqual(len(self.recs()), 0)

    def test_stop_unreadable_does_not_end_empty_prompt_record(self):   # SS4 (kills a None-prompt-as-empty mutant)
        self.seed((session.prompt_sha(""), "unknown", 1, "session", "", ""))
        p = self.stop(os.path.join(self.tmp, "absent.jsonl"))
        self.assertEqual((p.returncode, p.stdout, p.stderr), (0, "", ""))
        self.assertEqual(len(self.recs()), 1)

    def test_stop_baseexception_exit_zero(self):   # V3
        import io
        from gates import hook
        tp = os.path.join(self.tmp, "t.jsonl")
        write(tp, user_line("rec") + "\n")
        data = json.dumps(payload("SubagentStop", self.R, agent_transcript_path=tp)).encode("utf-8")

        class In:
            buffer = io.BytesIO(data)
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, {"CLAUDE_PLUGIN_DATA": self.pd}), mock.patch("sys.stdin", In), \
                mock.patch("sys.stdout", out), mock.patch("sys.stderr", err), \
                mock.patch("gates.hooks.subagent_stop.session.locked", side_effect=KeyboardInterrupt()):
            code = hook.main(["SubagentStop"])
        self.assertEqual((code, out.getvalue(), err.getvalue()), (0, "", ""))

    def test_stop_outside_config_repo_silent(self):   # SS15
        self.seed((session.prompt_sha("rec"), "controller", 1, "session", "", ""))
        tp = os.path.join(self.tmp, "t.jsonl")
        write(tp, user_line("rec") + "\n")
        nogit = os.path.join(self.tmp, "nogit")
        os.makedirs(nogit)
        p = run_hook("SubagentStop", payload("SubagentStop", nogit, agent_transcript_path=tp), self.env, FW)
        self.assertEqual((p.returncode, p.stdout, p.stderr), (0, "", ""))
        self.assertEqual(len(self.recs()), 1)

    def test_missing_optional_keys_accepted(self):   # V7
        pl = payload("PreToolUse", self.R, tool_name="Agent", session_id="s1", tool_input=tin(real_prompt("implementer")))
        for k in ("effort", "permission_mode", "prompt_id", "scratchpad_dir", "tool_use_id"):
            del pl[k]
        p = run_hook("PreToolUse", pl, self.env, FW)
        self.assertEqual((p.returncode, p.stderr), (0, ""))

    # ---- worktrees
    def test_worktree_integration_worktree_bound(self):   # WT7
        self.program()
        w = os.path.join(self.work, "intwt")
        git(self.R, "worktree", "add", "-q", w, NAME + "/integration")
        w = real(w)
        got = pre_agent.worktree_of(self.hand(), real_prompt("controller", "opus", task="t\nworktree: %s" % w), None, None)
        self.assertEqual(got, (w, []))

    def test_old_git_refuses(self):   # WT39 V5
        import shutil
        fake = os.path.join(self.tmp, "fakebin")
        os.makedirs(fake)
        script = os.path.join(fake, "git")
        write(script, '#!/bin/sh\ncase "$*" in *"worktree list"*|*--path-format*) exit 129;; esac\nexec %s "$@"\n' % shutil.which("git"))
        os.chmod(script, 0o755)
        env = self.env_with(PATH=fake + os.pathsep + self.env["PATH"])
        p = self.hk(tin(real_prompt("implementer", task="t\nworktree: %s" % self.R)), env=env)
        self.assertEqual(p.returncode, 2)
        self.assertIn("FAIL hook.agent.worktree: %s is not the top level of a worktree of this repository" % self.R, p.stderr)
        p = self.hk(tin(real_prompt("implementer", brief="n")), env=env)
        self.assertEqual(p.returncode, 2)
        self.assertTrue(p.stderr.startswith("FAIL hook.PreToolUse: "), p.stderr)
        self.assertEqual(self.recs(), [])

    def test_unicode_version_prompt_and_deny_identical(self):   # V2
        brief = "b \U0001fae0 Ⱟ"
        pr = real_prompt("implementer", brief=brief)
        p = self.hk(tin(pr))
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(self.recs()[-1]["sha"], __import__("hashlib").sha256(pr.encode("utf-8")).hexdigest())
        p = self.hk(tin(real_prompt("implementer", task="t\nworktree: /x\U0001fae0")))
        self.assertEqual(p.stderr, "FAIL hook.agent.worktree: /x\\U0001fae0 is not the top level of a worktree of this "
                                   "repository" + WAY + "\n")
        p = self.hk(tin(real_prompt("implementer"), subagent_type="FⰯ"))
        self.assertEqual(p.returncode, 0, p.stderr)       # only ASCII lower: not the fork spelling

    def test_unicode_version_session_file_identical(self):   # V2
        self.seed(("%064d" % 1, "controller", 1, "session", "/w\U0001fae0Ⱟ", "b\U0001fae0"))
        path = os.path.join(self.pd, "sessions", "s1.yml")
        with open(path, "rb") as fh:
            first = fh.read()
        self.assertEqual(self.recs()[0]["worktree"], "/w\U0001fae0Ⱟ")
        with session.locked(self.env, "s1"):
            pass
        with open(path, "rb") as fh:
            self.assertEqual(fh.read(), first)


SESSION_TAG = session.SCHEMA   # hook-session has no schema file (its reader session.state_errors checks it); Task 3a.1 ships it
STATE_OK = ("schema: " + SESSION_TAG + "\nsession: s1\ndispatches:\n  - sha: %s\n    role: controller\n    depth: 1\n"
            "    parent: session\n    worktree: /w\n    branch: b\nsurfaced: []\n")
SHA_A = "a" * 64


class Fix1(Base):
    """Review round 1 (findings wfhu kafz yas4 9xky i2xx vmks hkwy)."""

    def env_with(self, **kw):
        e = dict(self.env)
        e.update(kw)
        return e

    def counting(self, hijack=False):
        calls = []
        real_bb = pre_agent.worktrees.bound_branch

        def bb(p):
            calls.append(p)
            return "hijacked" if (hijack and len(calls) > 1) else real_bb(p)
        return calls, bb

    def main_run(self, tool_input, check):
        import io
        from gates import hook
        data = json.dumps(payload("PreToolUse", self.R, tool_name="Agent", session_id="s1", tool_input=tool_input)).encode()

        class In:
            buffer = io.BytesIO(data)
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, {"CLAUDE_PLUGIN_DATA": self.pd}), mock.patch("sys.stdin", In), \
                mock.patch("sys.stdout", out), mock.patch("sys.stderr", err), \
                mock.patch("gates.hooks.pre_agent.gate_dispatch.check", check):
            code = hook.main(["PreToolUse"])
        return code, out.getvalue(), err.getvalue()

    # ---- wfhu: bound_branch read once per dispatch (call sites: pre_agent._bind and pre_agent._decide)
    def test_branch_read_once(self):   # HA8, F-B3p-20: no line, line, group line
        calls, bb = self.counting()
        with mock.patch("gates.hooks.pre_agent.worktrees.bound_branch", bb):
            self.seen(self.hand(tool_input=tin(real_prompt("implementer"))))
            self.assertEqual(calls, [self.R])
            del calls[:]
            self.seen(self.hand(tool_input=tin(real_prompt("implementer", brief="l", task="t\nworktree: %s" % self.R))))
            self.assertEqual(calls, [self.R])
        self.assertEqual([r["branch"] for r in self.recs()], ["main", "main"])

    def test_branch_read_once_group_hijack(self):   # HA8: the recorded branch is the one the group rule judged
        self.program()
        grp = self.add_wt("grp", "-b", NAME + "/s1/g1")
        self.sub("a1", "stream prompt")
        self.seed((session.prompt_sha("stream prompt"), "stream_controller", 1, "session", self.stream_wt,
                   NAME + "/s1/main"))
        calls, bb = self.counting(hijack=True)
        with mock.patch("gates.hooks.pre_agent.worktrees.bound_branch", bb):
            out, _ = self.seen(self.hand(agent_id="a1", tool_input=tin(real_prompt("implementer", task="t\nworktree: %s" % grp))))
        self.assertEqual((out.deny, calls), ([], [grp]))
        self.assertEqual(self.recs()[-1]["branch"], NAME + "/s1/g1")

    # ---- kafz: group-rule refusals (WT13, WT16), one case per class member
    def test_group_branch_shapes(self):   # WT13 WT16
        self.program()
        okwt = self.add_wt("okg", "-b", NAME + "/s1/g1")
        self.sub("a1", "stream prompt")

        def verdict(w, rec_branch=NAME + "/s1/main"):
            st = {"dispatches": []}
            session.add_dispatch(st, session.prompt_sha("stream prompt"), "stream_controller", 1, "session",
                                 self.stream_wt, rec_branch)
            return pre_agent.worktree_of(self.hand(agent_id="a1"), real_prompt("implementer", task="t\nworktree: %s" % w),
                                         {"id": "stream_controller"}, st)
        self.assertEqual(verdict(okwt), (okwt, []))
        targets = {"four components": self.add_wt("w4", "-b", NAME + "/s1/a/b"),
                   "another program": self.add_wt("wq", "-b", "20261102-y/s1/g1"),
                   "records": self.add_wt("wr", "-b", NAME + "/records"),
                   "integration": self.add_wt_existing("wi", NAME + "/integration"),
                   "non-program branch": self.add_wt("wf", "-b", "feature2"),
                   "detached": self.add_wt("wd", "--detach")}
        for name, w in targets.items():
            with self.subTest(name):
                self.assertEqual(verdict(w), ("", ["hook.agent.worktree: %s is not one of the dispatcher's worktrees" % w]))
        with self.subTest("WT16 record of another program, target in this one"):
            self.assertEqual(verdict(okwt, "20261102-y/s1/main")[0], "")
        with self.subTest("WT16 program differs only"):
            other = self.add_wt("wq2", "-b", "20261102-y/s1/g2")
            self.assertEqual(verdict(other, "20261102-y/s1/main")[0], other)    # same program and stream: allowed
            self.assertEqual(verdict(other)[0], "")

    def add_wt_existing(self, name, branch):
        path = os.path.join(self.work, name)
        git(self.R, "worktree", "add", "-q", path, branch)
        return real(path)

    # ---- yas4: HT2
    def test_prompt_empty(self):   # HT2
        p = self.hk({"prompt": "", "model": "sonnet"})
        self.assertEqual(p.returncode, 2)
        self.assertIn("FAIL dispatch.grammar: missing heading ## Role", p.stderr)
        self.set_config(profile="light")
        p = self.hk({"prompt": "", "model": "sonnet"})
        self.assertEqual((p.returncode, p.stdout, p.stderr), (0, "", ""))
        self.assertEqual([(r["sha"], r["role"]) for r in self.recs()], [(session.prompt_sha(""), "unknown")])

    # ---- 9xky: the defensive deny
    def test_defensive_unknown_dispatcher_deny(self):
        out, calls = self.seen(self.hand(agent_id="a1", tool_input=tin("P")))
        self.assertEqual(out.deny, ["FAIL hook.agent.dispatcher: the dispatcher is unknown and the gate passed it" + WAY])
        self.assertEqual(self.recs(), [])
        self.set_config(profile="light")
        out, calls = pre_agent.handle(self.hand(agent_id="a1", tool_input=tin("P"), cfg=config.load(self.R))), None
        self.assertEqual((out.deny, self.recs()), ([], []))

    # ---- i2xx: the verdict follows the state at check time
    def test_hardening_swap_after_check_is_stated_limit(self):   # HZ4
        self.program()
        mk = lambda brief: real_prompt("stream_controller", "opus", brief="program: %s\nstream: s1\n%s" % (NAME, brief),
                                       task="t\nworktree: %s" % self.stream_wt)
        p = self.hk(tin(mk("one"), model="opus"))
        self.assertEqual((p.returncode, p.stderr), (0, ""))
        os.rename(self.stream_wt, self.stream_wt + "-moved")       # swapped after the check
        p = self.hk(tin(mk("two"), model="opus"))                # the same line is judged on the state now
        self.assertEqual(p.returncode, 2)
        self.assertIn("hook.agent.worktree: %s is not the top level of a worktree of this repository" % self.stream_wt,
                      p.stderr)
        self.assertEqual([r["worktree"] for r in self.recs()], [self.stream_wt])    # the first record kept its checked path

    # ---- vmks: DS23 exact line
    def test_depth_601_digits_exact_line(self):   # DS23 V1(c)
        import re
        seed_ctl(self, "controller", 10 ** 600, "P-601")
        self.sub("a601", "P-601")
        p = self.hk(tin(real_prompt("implementer", brief="d601")), agent_id="a601")
        self.assertEqual(p.returncode, 2)
        self.assertRegex(p.stderr, r"\AFAIL dispatch\.input: input: \S*dispatch\.json: not valid UTF-8 JSON "
                                   r"\(an integer of more than 600 digits\)\n\Z")

    # ---- hkwy: every value of the partly tested rows
    def test_fork_spellings_pass_the_gate(self):   # HG5
        for i, st in enumerate(("ｆｏｒｋ", " fork", "fork ")):
            p = self.hk(tin(real_prompt("implementer", brief="f%d" % i), subagent_type=st))
            self.assertEqual((p.returncode, p.stderr), (0, ""), st)

    def test_dispatcher_transcript_symlink_followed(self):   # DS13
        st = {"dispatches": []}
        session.add_dispatch(st, session.prompt_sha("AB"), "controller", 2, "session", self.R, "main")
        target = os.path.join(self.tmp, "real.jsonl")
        write(target, user_line("AB") + "\n")
        link = os.path.join(self.tmp, "s1", "subagents", "agent-a1.jsonl")
        os.makedirs(os.path.dirname(link))
        os.symlink(target, link)
        self.assertEqual(pre_agent.dispatcher(self.hand(agent_id="a1"), st)["id"], "controller")

    def test_config_directory_and_dangling_symlink(self):   # HC1
        cfg = os.path.join(self.R, ".strict-delivery", "config.yml")
        os.rename(cfg, cfg + ".bak")
        for kind in ("dir", "dangling"):
            if kind == "dir":
                os.mkdir(cfg)
            else:
                os.symlink(os.path.join(self.tmp, "nowhere"), cfg)
            p = self.hk(tin(real_prompt("implementer")))
            self.assertEqual(p.returncode, 2, kind)
            lines = p.stderr.split("\n")[:-1]
            self.assertEqual(len(lines), 1, lines)
            self.assertTrue(lines[0].startswith("FAIL hook.agent.config: ") and lines[0].endswith(WAY), lines)
            os.rename(cfg, cfg + "." + kind)

    def test_store_path_shapes(self):   # HS2 HS3 (corrected: a symlinked directory is accepted, 3a.1 L3)
        afile = os.path.join(self.tmp, "afile")
        write(afile, "x")
        link = os.path.join(self.tmp, "pdlink")
        os.symlink(self.pd, link)
        for val in (afile, "", "rel"):
            p = self.hk(tin(real_prompt("implementer")), env=self.env_with(CLAUDE_PLUGIN_DATA=val))
            self.assertEqual(p.returncode, 2, val)
            self.assertIn("FAIL dispatch.input: input: dispatcher must be an object\n", p.stderr)
            self.assertRegex(p.stderr, r"FAIL hook\.agent\.session: ")
        p = self.hk(tin(real_prompt("implementer", brief="file")), env=self.env_with(CLAUDE_PLUGIN_DATA=afile))
        self.assertRegex(p.stderr, r"FAIL hook\.agent\.session: the session directory .* is not usable")
        p = self.hk(tin(real_prompt("implementer", brief="link")), env=self.env_with(CLAUDE_PLUGIN_DATA=link))
        self.assertEqual((p.returncode, p.stderr), (0, ""))
        self.assertEqual(len(self.recs()), 1)
        self.set_config(profile="light")                          # HS3: not required: allow, nothing recorded
        for val in (afile, "", "rel"):
            p = self.hk({"prompt": "x"}, env=self.env_with(CLAUDE_PLUGIN_DATA=val))
            self.assertEqual((p.returncode, p.stdout, p.stderr), (0, "", ""), val)
        p = self.hk({"prompt": "y"}, env=self.env_with(CLAUDE_PLUGIN_DATA=link))
        self.assertEqual(len(self.recs()), 2)

    def test_corrupt_state_variants(self):   # HS4
        path = os.path.join(self.pd, "sessions", "s1.yml")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        variants = {"depth true": STATE_OK.replace("depth: 1", "depth: true") % SHA_A,
                    "depth 0": STATE_OK.replace("depth: 1", "depth: 0") % SHA_A,
                    "depth str": STATE_OK.replace("depth: 1", 'depth: "1"') % SHA_A,
                    "sha 63": STATE_OK % SHA_A[:63], "sha 65": STATE_OK % (SHA_A + "a"),
                    "other session": (STATE_OK % SHA_A).replace("session: s1", "session: s9"),
                    "unknown key": (STATE_OK % SHA_A) + "extra: 1\n"}
        for name, text in variants.items():
            for profile, deny in (("strict", True), ("light", False)):
                self.set_config(profile=profile)
                write(path, text)
                p = self.hk(tin(real_prompt("implementer", brief=name)) if deny else {"prompt": "x"})
                self.assertEqual(p.returncode, 2 if deny else 0, (name, p.stderr))
                if deny:
                    self.assertIn("FAIL hook.agent.session: the session state file", p.stderr)
                with open(path, encoding="utf-8") as fh:
                    self.assertEqual(fh.read(), text, name)             # never moved or rewritten
        os.rename(path, path + ".real")
        target_text = STATE_OK % SHA_A            # a valid state: only the symlink makes the file unreadable
        write(path + ".real", target_text)
        os.symlink(path + ".real", path)
        for profile, deny in (("strict", True), ("light", False)):     # HS4 symlink: both profiles, bytes unchanged
            self.set_config(profile=profile)
            p = self.hk(tin(real_prompt("implementer", brief="symlink")) if deny else {"prompt": "x"})
            self.assertEqual(p.returncode, 2 if deny else 0, (profile, p.stderr))
            if deny:
                self.assertIn("FAIL hook.agent.session: the session state file", p.stderr)
            self.assertTrue(os.path.islink(path), profile)
            self.assertEqual(os.readlink(path), path + ".real", profile)
            with open(path + ".real", encoding="utf-8") as fh:
                self.assertEqual(fh.read(), target_text, profile)      # never moved or rewritten

    def test_stop_lock_held(self):   # SS12 (the lock is held by another process: exit 0, nothing changed)
        import fcntl
        self.seed((session.prompt_sha("rec"), "controller", 1, "session", "", ""))
        tp = os.path.join(self.tmp, "t.jsonl")
        write(tp, user_line("rec") + "\n")
        fd = os.open(os.path.join(self.pd, "sessions", "s1.lock"), os.O_RDWR | os.O_CREAT, 0o600)
        self.addCleanup(os.close, fd)
        fcntl.flock(fd, fcntl.LOCK_EX)
        p = self.stop(tp)
        self.assertEqual((p.returncode, p.stdout, p.stderr), (0, "", ""))
        fcntl.flock(fd, fcntl.LOCK_UN)
        self.assertEqual(len(self.recs()), 1)

    def test_concurrency_default_and_env(self):   # HN5
        def fill(n):
            with session.locked(self.env, "s1") as st:
                st["dispatches"] = []
                for i in range(n):
                    session.add_dispatch(st, "%064d" % i, "controller", 1, "session", "", "")
        fill(19)
        self.assertEqual(self.hk(tin(real_prompt("implementer", brief="d19"))).returncode, 0)
        fill(20)
        p = self.hk(tin(real_prompt("implementer", brief="d20")))
        self.assertEqual(p.returncode, 2)
        self.assertIn("FAIL dispatch.concurrency: 20 running + 1 exceeds max_concurrent 20", p.stderr)
        env = self.env_with(CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS="21")
        self.assertEqual(self.hk(tin(real_prompt("implementer", brief="e20")), env=env).returncode, 0)
        fill(21)
        p = self.hk(tin(real_prompt("implementer", brief="e21")), env=env)
        self.assertIn("FAIL dispatch.concurrency: 21 running + 1 exceeds max_concurrent 21", p.stderr)

    def test_session_start_resume_and_fork_reset(self):   # HN8
        for src in ("resume", "fork"):
            self.seed(("%064d" % 1, "controller", 1, "session", "", ""))
            p = run_hook("SessionStart", payload("SessionStart", self.R, session_id="s1", source=src), self.env, FW)
            self.assertEqual(p.returncode, 0)
            self.assertEqual(self.recs(), [], src)

    def test_limits_digit_edge_all_keys(self):   # HN13 (corrected: 601 digits give hook.agent.config)
        for limits in ({"max_depth": 10 ** 599}, {"max_children": {"session": 10 ** 599}}):
            self.set_config(limits=limits)
            p = self.hk(tin(real_prompt("implementer", brief=str(sorted(limits)))))
            self.assertEqual((p.returncode, p.stderr), (0, ""), limits)
        for limits in ({"max_depth": 10 ** 600}, {"max_children": {"session": 10 ** 600}}, {"max_concurrent": 10 ** 600}):
            self.set_config(limits=limits)
            p = self.hk(tin(real_prompt("implementer", brief="x")))
            self.assertEqual(p.returncode, 2)
            self.assertTrue(p.stderr.startswith("FAIL hook.agent.config: "), p.stderr)

    def test_limits_digit_edge_role_keys(self):   # HN13 (F-20261124-dq53): max_children.<role> at 600 and 601 digits
        # the dispatcher's own role key (only `controller` may dispatch without a live program; the other controller
        # roles are covered below as keys with a session dispatcher): 600 digits load and the dispatch passes
        self.set_config(limits={"max_children": {"controller": 10 ** 599}})
        seed_ctl(self, "controller", 1, "P-ctl")
        self.sub("a1", "P-ctl")
        p = self.hk(tin(real_prompt("implementer", brief="d600")), agent_id="a1")
        self.assertEqual((p.returncode, p.stderr), (0, ""))
        for role in dispatch.ROLES + ("session",):                   # every key the gate accepts, 600 digits and 601 digits
            self.set_config(limits={"max_children": {role: 10 ** 599}})
            p = self.hk(tin(real_prompt("implementer", brief="s600-" + role)))
            self.assertEqual((p.returncode, p.stderr), (0, ""), role)
            self.set_config(limits={"max_children": {role: 10 ** 600}})
            p = self.hk(tin(real_prompt("implementer", brief="s601-" + role)))
            self.assertEqual(p.returncode, 2, role)
            self.assertTrue(p.stderr.startswith("FAIL hook.agent.config: "), (role, p.stderr))
        self.set_config(limits={"max_children": {"controller": 10 ** 600}})     # 601 digits with a controller dispatcher
        p = self.hk(tin(real_prompt("implementer", brief="d601")), agent_id="a1")
        self.assertEqual(p.returncode, 2)
        self.assertTrue(p.stderr.startswith("FAIL hook.agent.config: "), p.stderr)

    def test_gate_result_shapes_denied(self):   # HR5 HR6
        from gates.lib.result import GateError
        empty, other = Result("dispatch"), Result("other")
        other.passed("other.x")
        for what, want in ((GateError("cfg broke"), "FAIL dispatch.input: cfg broke"),
                           (empty, "FAIL dispatch.empty: the gate produced no lines"),
                           (other, "FAIL dispatch.input: the check returned a Result for gate other, not dispatch")):
            kw = {"side_effect": what} if isinstance(what, Exception) else {"return_value": what}
            with mock.patch("gates.hooks.pre_agent.gate_dispatch.check", **kw):
                out = pre_agent.handle(self.hand(tool_input=tin("P")))
            self.assertEqual(out.deny, [want])

    def test_context_as_stdout_json(self):   # HR3 HR14 through hook.main
        def check(args):
            r = Result("dispatch")
            r.passed("dispatch.input")
            r.passed("dispatch.in-force.DEC-20261101-k3f9")
            return r
        code, out, err = self.main_run(tin(real_prompt("implementer")), check)
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(out, json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext":
                                                                "PASS dispatch.in-force.DEC-20261101-k3f9"}}) + "\n")
        self.assertNotIn("permissionDecision", out)

    def test_baseexception_from_gate_is_exit_two_through_entry(self):   # HR7 V3
        import builtins
        cls = getattr(builtins, "BaseExceptionGroup", None)
        for exc in (KeyboardInterrupt(), cls("g", [KeyboardInterrupt()]) if cls else type("Stand", (BaseException,), {})("g")):
            code, out, err = self.main_run(tin(real_prompt("implementer")), mock.Mock(side_effect=exc))
            self.assertEqual((code, out), (2, ""))
            self.assertTrue(err.startswith("FAIL hook.PreToolUse: "), err)
        self.assertEqual(self.recs(), [])

    def test_unicode_role_and_session_file_bytes(self):   # V2
        pr = real_prompt("implementer").replace("## Role\nimplementer\n", "## Role\nimplementerⰯ\n", 1)
        p = self.hk(tin(pr))
        self.assertEqual(p.returncode, 2)
        self.assertIn("FAIL dispatch.role: ", p.stderr)
        self.seed(("%064d" % 1, "controller", 1, "session", "/w\U0001fae0Ⱟ", "b"))
        with open(os.path.join(self.pd, "sessions", "s1.yml"), "rb") as fh:
            self.assertIn(b"    worktree: /w\xf0\x9f\xab\xa0\xe2\xb0\xaf\n", fh.read())

    def test_stop_oversize_and_surrogate_first_entry(self):   # SS5 through subagent_stop
        self.seed((session.prompt_sha("A" * 4194400), "controller", 1, "session", "", ""),   # equals the oversize text's SHA:
                  (session.prompt_sha("A"), "controller", 1, "session", "", ""))              # only the size limit stops a match
        big = os.path.join(self.tmp, "big.jsonl")
        write(big, user_line("A" * 4194400) + "\n")
        sur = os.path.join(self.tmp, "sur.jsonl")
        write(sur, json.dumps({"type": "user", "message": {"content": "A\ud800"}}) + "\n")
        for path in (big, sur):
            p = self.stop(path)
            self.assertEqual((p.returncode, p.stdout, p.stderr), (0, "", ""))
            self.assertEqual(len(self.recs()), 2, path)
        small = os.path.join(self.tmp, "small.jsonl")                  # control: the seeded SHA matches a transcript within the limit
        write(small, user_line("A" * 4194000) + "\n")
        self.seed((session.prompt_sha("A" * 4194000), "controller", 1, "session", "", ""))
        self.assertEqual(self.stop(small).returncode, 0)
        self.assertEqual(len(self.recs()), 2)

    def test_write_failure_on_exit_every_profile(self):   # HS6 (Q5, F-20261124-vbkd): denied whatever `required`
        err = session.SessionUnavailable("disk full")
        want = ["FAIL hook.agent.session: disk full" + WAY]
        for name, profile, agent in (("gate required", "strict", None), ("not required, no program", "light", None),
                                     ("not required, unknown dispatcher", "light", "zz")):
            self.set_config(profile=profile)
            with mock.patch("gates.lib.session._write", side_effect=err):
                out, _ = self.seen(self.hand(cfg=config.load(self.R), agent_id=agent, tool_input=tin("P")))
            self.assertEqual(out.deny, want, name)
            self.assertEqual(self.recs(), [], name)            # nothing was recorded


class FinalReview(Base):
    """PR-tools final review (findings yxau r8kv): FR-1 and the plan-named tests of P:3939, P:3957 and P:3961."""

    def line(self, path, role="implementer", extra=""):
        return real_prompt(role, "opus" if role == "controller" else "sonnet", task="t\nworktree: %s\n%s" % (path, extra))

    def break_write(self, sid):
        """The store's temporary file name is a directory: the write on lock exit fails with ``SessionUnavailable``."""
        with session.locked(self.env, sid):
            pass
        os.makedirs(os.path.join(self.pd, "sessions", sid + ".yml.tmp"))
        with open(os.path.join(self.pd, "sessions", sid + ".yml"), "rb") as fh:
            return fh.read()

    def test_write_failure_on_exit_keeps_every_fail_line(self):   # HS6 (Q5 (a), plan P:3918, F-20261125-yxau)
        sib = self.add_wt("sibw", "-b", "fw")
        wt_line = "FAIL hook.agent.worktree: %s is not one of the dispatcher's worktrees%s" % (sib, WAY)
        gate = ["FAIL dispatch.model: the dispatch call passes no model",
                "FAIL dispatch.tier: not checked: dispatch.model failed",
                "FAIL dispatch.top-tier: not checked: dispatch.tier failed"]
        for n, (name, profile, agent, ti, keep) in enumerate((
                ("gate required, gate FAIL lines", "strict", None, {"prompt": real_prompt("implementer"),
                                                                    "subagent_type": "general-purpose"}, gate),
                ("gate required, worktree FAIL line", "strict", None, tin(self.line(sib)), [wt_line]),
                ("gate required, gate and worktree FAIL lines", "strict", None,
                 {"prompt": self.line(sib), "subagent_type": "general-purpose"}, gate + [wt_line]),
                ("not required, worktree FAIL line", "light", None, {"prompt": self.line(sib)}, [wt_line]),
                ("gate required, pass", "strict", None, tin(real_prompt("implementer")), []),
                ("not required, no program", "light", None, {"prompt": "x"}, []),
                ("not required, unknown dispatcher", "light", "zz", {"prompt": "x"}, []))):
            with self.subTest(name):
                self.set_config(profile=profile)
                sid = "w%d" % n
                before = self.break_write(sid)
                p = self.hk(ti, agent_id=agent, session_id=sid)
                self.assertEqual(p.returncode, 2, p.stderr)
                self.assertEqual(p.stdout, "")
                lines = p.stderr.split("\n")[:-1]
                self.assertEqual(lines[:-1], keep)                       # every computed FAIL line stays, in order
                self.assertRegex(lines[-1], r"^FAIL hook\.agent\.session: cannot write the session state file .*%s\.yml "
                                            r"\(.*\)%s$" % (sid, re.escape(WAY)))
                with open(os.path.join(self.pd, "sessions", sid + ".yml"), "rb") as fh:
                    self.assertEqual(fh.read(), before)                  # nothing was recorded

    def test_unavailable_inside_locked_body_is_reraised(self):   # fail closed: not re-run without a store (mutant R3)
        err = session.SessionUnavailable("inside the body")
        for profile in ("strict", "light"):
            with self.subTest(profile):
                self.set_config(profile=profile)
                with mock.patch("gates.hooks.pre_agent.session.add_dispatch", side_effect=err):
                    with self.assertRaises(session.SessionUnavailable) as cm:
                        self.seen(self.hand(cfg=config.load(self.R), tool_input=tin(real_prompt("implementer"))))
                self.assertIs(cm.exception, err)

    def test_nested_dispatcher_from_record(self):   # DS4 M1 M3, plan P:3939: what the gate receives
        seed_ctl(self, "stream_controller", 1, "P0")
        self.sub("a1", "P0")
        out, calls = self.seen(self.hand(agent_id="a1", tool_input=tin(real_prompt("implementer"))))
        self.assertEqual(out.deny, [])
        self.assertEqual(calls[0][1]["dispatcher"],
                         {"id": "stream_controller", "depth": 1, "live_children": 0, "live_total": 1})
        self.assertIs(calls[0][1]["program_live"], False)

    def test_controller_at_depth_two_cannot_open_a_level(self):   # DS5 HD3, plan P:3957 (Q-H5 (a), limit 3), entry
        seed_ctl(self, "controller", 2, "P0")
        self.sub("a1", "P0")
        p = self.hk(tin(real_prompt("controller", "opus", brief="below"), model="opus"), agent_id="a1")
        self.assertEqual(p.returncode, 2)
        self.assertIn("FAIL dispatch.depth", p.stderr)
        self.assertEqual(len(self.recs()), 1)                              # only the seeded record

    def test_stream_cannot_bind_another_streams_worktree(self):   # WT12, plan P:3961, entry
        self.program()
        own = self.add_wt("grp", "-b", NAME + "/s1/g1")
        other = self.add_wt("oth", "-b", NAME + "/s2/g1")
        s2main = self.add_wt("s2main", "-b", NAME + "/s2/main")
        seed_ctl(self, "stream_controller", 1, "stream prompt", wt=self.stream_wt, branch=NAME + "/s1/main")
        self.sub("a1", "stream prompt")
        p = self.hk(tin(self.line(own)), agent_id="a1")                    # control: its own group worktree binds
        self.assertEqual((p.returncode, p.stderr), (0, ""))
        for w in (other, s2main):
            with self.subTest(worktree=w):
                p = self.hk(tin(self.line(w, extra="n%s" % w)), agent_id="a1")
                self.assertEqual(p.returncode, 2)
                self.assertEqual(p.stderr, "FAIL hook.agent.worktree: %s is not one of the dispatcher's worktrees%s\n"
                                 % (w, WAY))
        self.assertEqual([r["worktree"] for r in self.recs()], [self.stream_wt, own])


if __name__ == "__main__":
    unittest.main()
