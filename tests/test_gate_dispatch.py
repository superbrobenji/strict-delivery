"""Tests of ``python3 -m gates check dispatch`` (plan Task 2c.3; rows I1-I14, Q1-Q3, M1-M8, S5, S13-S15, B8, V1-V3 of
task-2c.3-domain.md) through ``gates.__main__.main`` on fixture repositories and fixture prompt directories in temp
directories. Prompt files are never read from this repository's own prompts (stream rules); expected lines are written
out literally."""
import builtins
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import unittest
from unittest import mock

from gates import __main__ as gates_main
from gates.lib import claims as claims_lib, config, dispatch, migrations, programs
from gates.lib.result import GateError
from tests.test_dispatch_lib import NAME, add_program
from tests.helpers import (INT_LIMITS, GitIsolatedTestCase, commit_all, git, int_limit, make_repo, minimal_config,
                           write_record)

ENV_D, ENV_C = "CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH", "CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS"
ALL_PASS = ["PASS dispatch.input", "PASS dispatch.fork", "PASS dispatch.grammar", "PASS dispatch.role",
            "PASS dispatch.dispatcher", "PASS dispatch.program", "PASS dispatch.stream", "PASS dispatch.depth", "PASS dispatch.concurrency", "PASS dispatch.children",
            "PASS dispatch.model", "PASS dispatch.tier", "PASS dispatch.top-tier", "PASS dispatch.block",
            "PASS dispatch.budget", "PASS dispatch.size", "PASS dispatch.claims", "PASS dispatch.decisions"]
MODELS = {1: "haiku", 2: "sonnet", 3: "opus", 4: "fable"}
CTAG = "claim/%d" % migrations.current_version("claim")
FTAG = "finding/%d" % migrations.current_version("finding")
SESSION = {"id": "session", "depth": 0, "live_children": 0, "live_total": 0}
LINE = "small-re-review: plan=p task=t round=2 fix=%s..%s narrowed=none questions=none prev-fix-defects=0"


def block(role):
    return "# Strict block: %s\n\nbody of %s\n" % (role, role)


def prompt(role, brief="b", findings="", claims="", model="sonnet", body=None, extra_heading=""):
    body = block(role) if body is None else body
    return ("## Role\n%s\n\n## Brief\n%s\n\n## Findings\n%s\n\n## Claims\n%s\n\n## Budget: tokens=1000 minutes=10\n\n"
            "## Model\n%s\n\n## Report\nr\n\n## Strict block\n\n%s\n## Task\nt\n%s" % (role, brief, findings, claims,
                                                                                  model, body, extra_heading))


def live_lines(out):
    return out.splitlines()


class GateCase(GitIsolatedTestCase):
    def setUp(self):
        super().setUp()
        self.root = make_repo(self.work)
        self.prompts = os.path.join(self.tmp, "prompts")
        os.mkdir(self.prompts)
        for r in dispatch.ROLES:
            with open(os.path.join(self.prompts, r + ".md"), "w", encoding="utf-8", newline="") as f:
                f.write(block(r))
        patcher = mock.patch.dict(os.environ)
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ.pop(ENV_D, None)
        os.environ.pop(ENV_C, None)
        self.n = 0

    def set_config(self, **extra):
        write_record(self.root, ".strict-delivery/config.yml", dict(minimal_config(), **extra))
        commit_all(self.root, "config")

    def write_input(self, data):
        self.n += 1
        path = os.path.join(self.tmp, "in%d.json" % self.n)
        with open(path, "wb") as f:
            f.write(data if isinstance(data, bytes) else json.dumps(data).encode("utf-8"))
        return path

    def base(self, role="implementer", **over):
        d = {"prompt": prompt(role, model=MODELS[dispatch.MIN_TIERS[role] if dispatch.MIN_TIERS[role] < 4 else 3]),
             "model": MODELS[dispatch.MIN_TIERS[role] if dispatch.MIN_TIERS[role] < 4 else 3],
             "dispatcher": dict(SESSION), "program_live": False}
        d.update(over)
        return d

    def run_gate(self, data, *extra, prompts=True):
        path = data if isinstance(data, str) else self.write_input(data)
        argv = ["check", "dispatch", "--root", self.root, "--input", path] + (["--prompts", self.prompts] if prompts else []) \
            + list(extra)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
            code = gates_main.main(argv)
        return buf.getvalue(), code

    def lines(self, data, *extra):
        out, code = self.run_gate(data, *extra)
        return out.splitlines(), code

    def only(self, data, name):
        """The one line of ``dispatch.<name>`` of a run."""
        out, _ = self.lines(data)
        got = [ln for ln in out if ln.split(":")[0].split(" ")[1] == "dispatch." + name]
        self.assertEqual(len(got), 1, out)
        return got[0]


class InputTest(GateCase):
    def test_valid_dispatch_passes(self):                           # I14
        out, code = self.lines(self.base())
        self.assertEqual((out, code), (ALL_PASS, 0))

    def test_input_file_refused(self):                              # I1-I4
        d = self.base()
        link = os.path.join(self.tmp, "link.json")
        real = self.write_input(d)
        os.symlink(real, link)
        cases = {"missing": os.path.join(self.tmp, "nope.json"), "directory": self.tmp, "symlink": link,
                 "invalid json": self.write_input(b"{"), "not utf-8": self.write_input(b"\xff\xfe{}"),
                 "list": self.write_input([]), "string": self.write_input('"x"'), "empty": self.write_input(b""),
                 "duplicate keys": self.write_input(b'{"prompt": "a", "prompt": "b"}'),
                 "duplicate key in a valid input": self.write_input(
                     json.dumps(d)[:-1].encode("utf-8") + b', "program_live": false}'),
                 "NaN": self.write_input(b'{"prompt": "a", "dispatcher": NaN}'),
                 "Infinity": self.write_input(b'{"prompt": "a", "x": Infinity}'),
                 "unknown key": self.write_input(dict(d, extra=1)),
                 "unknown dispatcher key": self.write_input(dict(d, dispatcher=dict(SESSION, extra=1))),
                 "prompt absent": self.write_input({k: v for k, v in d.items() if k != "prompt"})}
        for v in (1, None, []):
            cases["prompt %r" % (v,)] = self.write_input(dict(d, prompt=v))
        for k in ("subagent_type", "model"):
            for v in (1, None):
                cases["%s %r" % (k, v)] = self.write_input(dict(d, **{k: v}))
        for name, path in cases.items():
            with self.subTest(name):
                out, code = self.run_gate(path)
                self.assertEqual(code, 1)
                self.assertEqual(len(out.splitlines()), 1, out)
                self.assertTrue(out.startswith("FAIL dispatch.input: "), out)
        out, _ = self.run_gate(cases["unknown key"])
        self.assertIn("extra", out)

    def test_absent_dispatcher_fails_input(self):                   # I5
        d = self.base()
        for name, value in (("absent", None), ("list", []), ("string", "session")):
            with self.subTest(name):
                data = {k: v for k, v in d.items() if k != "dispatcher"} if value is None else dict(d, dispatcher=value)
                out, code = self.run_gate(data)
                self.assertTrue(out.startswith("FAIL dispatch.input"), out)
                self.assertEqual(code, 1)
        for field in SESSION:
            with self.subTest(field):
                out, _ = self.run_gate(dict(d, dispatcher={k: v for k, v in SESSION.items() if k != field}))
                self.assertTrue(out.startswith("FAIL dispatch.input") and field in out, out)

    def test_input_values(self):                                    # I6-I9
        d = self.base()
        bad = [("id", "boss"), ("id", 1), ("depth", -1), ("depth", True), ("depth", 1.0), ("depth", "1"),
               ("live_children", -1), ("live_children", True), ("live_children", "0"), ("live_total", -1),
               ("live_total", True), ("live_total", "0")]
        for k, v in bad:
            with self.subTest(k=k, v=v):
                out, _ = self.run_gate(dict(d, dispatcher=dict(SESSION, **{k: v})))
                self.assertTrue(out.startswith("FAIL dispatch.input"), out)
        for v in (None, 1, "true", "absent"):
            with self.subTest(program_live=v):
                data = {k: x for k, x in d.items() if k != "program_live"} if v == "absent" else dict(d, program_live=v)
                self.assertTrue(self.run_gate(data)[0].startswith("FAIL dispatch.input"))

    def test_program_live_values(self):                             # I9
        self.assertIn("PASS dispatch.dispatcher", self.lines(self.base(program_live=False))[0])
        out, code = self.lines(self.base(program_live=True))        # a program is live: the session may not dispatch it
        self.assertIn("FAIL dispatch.dispatcher: session may not dispatch implementer (program_live true; allowed: "
                      "stream_controller, controller)", out)
        self.assertEqual(code, 1)

    def test_config_missing_fails_input(self):                      # I12
        os.unlink(os.path.join(self.root, ".strict-delivery", "config.yml"))
        out, code = self.run_gate(self.base())
        self.assertEqual((out, code), ("FAIL dispatch.input: .strict-delivery/config.yml: missing; run "
                                       "/strict-delivery:init\n", 1))

    def test_missing_input_argument(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = gates_main.main(["check", "dispatch", "--root", self.root])
        self.assertEqual((buf.getvalue(), code), ("FAIL dispatch.input: input: --input FILE is required\n", 1))

    def test_env_values_through_the_gate(self):                     # E4 through the gate
        for bad in ("0", "abc", "", " 5", "٥"):
            for name in (ENV_D, ENV_C):
                with self.subTest(name=name, bad=bad):
                    os.environ[name] = bad
                    out, _ = self.run_gate(self.base())
                    self.assertTrue(out.startswith("FAIL dispatch.input: ") and name in out and len(out.splitlines()) == 1)
                    os.environ.pop(name)


class RulesTest(GateCase):
    def test_worker_dispatcher_refused(self):                       # Q-H4, I6
        for w in dispatch.ROLES:
            if w in dispatch.CONTROLLER_ROLES:
                continue
            for live in (False, True):
                with self.subTest(worker=w, live=live):
                    got = self.only(self.base(program_live=live, dispatcher=dict(SESSION, id=w)), "dispatcher")
                    self.assertEqual(got, "FAIL dispatch.dispatcher: %s is a worker role, and a worker dispatches no "
                                          "agent" % w)

    def test_sub_controller_may_dispatch_sub_controller(self):      # Q-H3
        d = self.base("controller", dispatcher=dict(SESSION, id="controller", depth=1), program_live=True)
        self.assertEqual(self.only(d, "dispatcher"), "PASS dispatch.dispatcher")
        d = self.base("controller", dispatcher=dict(SESSION, id="stream_controller", depth=1), program_live=True)
        self.assertEqual(self.only(d, "dispatcher"), "PASS dispatch.dispatcher")
        self.assertTrue(self.only(self.base("program_controller", program_live=False), "dispatcher").startswith("FAIL"))

    def test_depth_limit(self):                                     # I7, P1 through the gate
        for role, level, ok in (("implementer", 2, True), ("implementer", 3, False), ("controller", 1, True),
                                ("controller", 2, False), ("program_controller", 0, True), ("program_controller", 1, False)):
            with self.subTest(role=role, level=level):
                live = role == "controller"
                d = self.base(role, program_live=live, dispatcher=dict(SESSION, id="controller" if level else "session",
                                                                        depth=level))
                if role == "program_controller":
                    d["program_live"] = True
                got = self.only(d, "depth")
                self.assertEqual(got.startswith("PASS"), ok, got)
        os.environ[ENV_D] = "5"                                     # limit 6 admits level 3
        self.assertEqual(self.only(self.base(dispatcher=dict(SESSION, id="controller", depth=3)), "depth"),
                         "PASS dispatch.depth")
        os.environ.pop(ENV_D)
        self.set_config(limits={"max_depth": 2})
        self.assertTrue(self.only(self.base(dispatcher=dict(SESSION, id="controller", depth=2)), "depth").startswith("FAIL"))

    def test_concurrency_limit(self):                               # I8
        self.assertEqual(self.only(self.base(dispatcher=dict(SESSION, live_total=19)), "concurrency"),
                         "PASS dispatch.concurrency")
        self.assertEqual(self.only(self.base(dispatcher=dict(SESSION, live_total=20)), "concurrency"),
                         "FAIL dispatch.concurrency: 20 running + 1 exceeds max_concurrent 20")
        os.environ[ENV_C] = "30"
        self.assertEqual(self.only(self.base(dispatcher=dict(SESSION, live_total=29)), "concurrency"),
                         "PASS dispatch.concurrency")
        self.set_config(limits={"max_concurrent": 5})
        self.assertTrue(self.only(self.base(dispatcher=dict(SESSION, live_total=5)), "concurrency").startswith("FAIL"))

    def test_child_cap(self):                                       # Q-H2, I8
        d = self.base(dispatcher=dict(SESSION, live_children=3))
        self.assertEqual(self.only(d, "children"), "PASS dispatch.children")            # uncapped
        self.set_config(limits={"max_children": {"session": 3}})
        self.assertEqual(self.only(d, "children"),
                         "FAIL dispatch.children: 3 running children + 1 exceeds limits.max_children.session 3")
        self.assertEqual(self.only(self.base(dispatcher=dict(SESSION, live_children=2)), "children"),
                         "PASS dispatch.children")
        self.set_config(limits={"max_children": {"controller": 1}})                     # another dispatcher's cap
        self.assertEqual(self.only(d, "children"), "PASS dispatch.children")

    def test_unknown_max_children_key_fails_input(self):            # I10, Q-2c2-1 (a)
        for key, ok in (("implementer", True), ("session", True), ("drafter", True), ("implementor", False)):
            with self.subTest(key):
                self.set_config(limits={"max_children": {key: 2}})
                out, _ = self.run_gate(self.base())
                self.assertEqual(out.startswith("FAIL dispatch.input"), not ok, out)
                if not ok:
                    self.assertIn("implementor", out)

    def test_fork_refused(self):                                    # I11
        for st, ok in (("fork", False), ("Fork", False), ("FORK", False), ("general-purpose", True), (None, True)):
            with self.subTest(st):
                d = self.base()
                if st is not None:
                    d["subagent_type"] = st
                self.assertEqual(self.only(d, "fork").startswith("PASS"), ok)
        self.assertEqual(self.only(self.base(subagent_type="fork"), "fork"), "FAIL dispatch.fork: subagent_type is fork")

    def test_dependent_lines_fail_closed(self):                     # I13
        out, code = self.lines(self.base(prompt="## Role\nimplementer\n"))
        self.assertEqual(code, 1)
        self.assertEqual(out[0], "PASS dispatch.input")
        self.assertTrue(any(ln.startswith("FAIL dispatch.grammar: missing heading ## Brief") for ln in out), out)
        self.assertIn("FAIL dispatch.model: not checked: dispatch.grammar failed", out)
        self.assertIn("FAIL dispatch.block: not checked: dispatch.grammar failed", out)
        out, _ = self.lines(self.base(prompt=prompt("implementor")))
        self.assertTrue(any(ln.startswith("FAIL dispatch.role: ") for ln in out))
        for name in ("dispatcher", "depth", "tier", "top-tier", "block"):
            self.assertTrue(any(ln.startswith("FAIL dispatch.%s: not checked: " % name) for ln in out), (name, out))
        self.assertEqual(len([ln for ln in out if ln.startswith(("PASS", "FAIL"))]), len(ALL_PASS))

    def test_prompts_never_read_from_root(self):                    # H9
        other = os.path.join(self.root, "skills", "strict-delivery", "prompts")
        os.makedirs(other)
        with open(os.path.join(other, "implementer.md"), "w", encoding="utf-8") as f:
            f.write("a different block\n")
        self.assertEqual(self.only(self.base(), "block"), "PASS dispatch.block")
        out, _ = self.run_gate(self.base(), prompts=False)       # the default: the installed package's own prompts
        self.assertIn("FAIL dispatch.block: ## Strict block is not the block", out)
        self.assertNotIn(other, out)
        decoy = os.path.join(self.tmp, "cwd", "skills", "strict-delivery", "prompts")      # nor under the cwd
        os.makedirs(decoy)
        with open(os.path.join(decoy, "implementer.md"), "w", encoding="utf-8", newline="") as f:
            f.write(block("implementer"))
        before = os.getcwd()
        os.chdir(os.path.join(self.tmp, "cwd"))
        self.addCleanup(os.chdir, before)
        out, _ = self.run_gate(self.base(), prompts=False)
        self.assertIn("FAIL dispatch.block: ## Strict block is not the block", out)

    def test_strict_block_variants(self):                           # H8 through the gate
        t = block("implementer")
        for name, body, ok in (("equal", t, True), ("trailing space", t.replace("body", "body "), False),
                               ("another role's", block("controller"), False)):
            with self.subTest(name):
                self.assertEqual(self.only(self.base(prompt=prompt("implementer", body=body)), "block").startswith("PASS"), ok)
        self.assertTrue(self.only(self.base(prompt=prompt("implementer").replace("\n\n## Task", "\n## Task")), "block")
                        .startswith("FAIL"))                       # missing final empty line
        self.assertTrue(self.only(self.base(prompt=prompt("implementer").replace("\n", "\r\n")), "block")
                        .startswith("FAIL"))                       # CRLF
        os.unlink(os.path.join(self.prompts, "implementer.md"))
        got = self.only(self.base(), "block")
        self.assertIn("implementer.md cannot be read", got)


class ModelTierTest(GateCase):
    def test_absent_tool_model_fails(self):                         # M1
        d = self.base()
        del d["model"]
        self.assertEqual(self.only(d, "model"), "FAIL dispatch.model: the dispatch call passes no model")
        self.assertEqual(self.only(d, "tier"), "FAIL dispatch.tier: not checked: dispatch.model failed")

    def test_model_variants(self):                                  # M1
        for name, model, body, ok in (("equal", "sonnet", "sonnet", True), ("different", "opus", "sonnet", False),
                                      ("case", "Sonnet", "sonnet", False), ("two lines", "sonnet", "sonnet\nsonnet", False),
                                      ("empty body", "sonnet", "", False), ("padded", "sonnet", "\nsonnet\n", True)):
            with self.subTest(name):
                d = self.base(prompt=prompt("implementer", model=body), model=model)
                self.assertEqual(self.only(d, "model").startswith("PASS"), ok)

    def test_tier_each_role(self):                                  # M3: each role at, above, below MIN_TIERS
        self.set_config(models={"tiers": {"tier1": "haiku", "tier2": "sonnet", "tier3": "opus", "tier4": "fable"}})
        for role, need in dispatch.MIN_TIERS.items():
            for tier in (1, 2, 3, 4):
                with self.subTest(role=role, tier=tier):
                    d = self.base(role, model=MODELS[tier], prompt=prompt(role, model=MODELS[tier]))
                    got = self.only(d, "tier")
                    self.assertEqual(got.startswith("PASS"), tier >= need, got)

    def test_tier_names(self):                                      # M2
        got = self.only(self.base(model="mystery", prompt=prompt("implementer", model="mystery")), "tier")
        self.assertEqual(got, "FAIL dispatch.tier: model 'mystery' is named by no tier")
        self.set_config(models={"tiers": {"tier2": "same", "tier3": "same"}})
        got = self.only(self.base(model="same", prompt=prompt("implementer", model="same")), "tier")
        self.assertTrue(got.startswith("FAIL dispatch.tier: model 'same' is named by more than one tier"), got)

    def test_top_tier_fallback(self):                               # M4, M8
        fv = lambda m: self.base("final_verifier", model=m, prompt=prompt("final_verifier", model=m))
        self.assertEqual(self.only(fv("opus"), "tier"), "PASS dispatch.tier")             # default fallback tier3
        self.assertTrue(self.only(fv("sonnet"), "tier").startswith("FAIL dispatch.tier"))
        self.set_config(top_tier_fallback="tier2")
        self.assertEqual(self.only(fv("sonnet"), "tier"), "PASS dispatch.tier")
        self.assertTrue(self.only(fv("haiku"), "tier").startswith("FAIL"))
        for bad in ("tier9", "tier4"):
            self.set_config(top_tier_fallback=bad)
            got = self.only(fv("opus"), "tier")
            self.assertTrue(got.startswith("FAIL dispatch.tier") and "top_tier_fallback" in got, got)
        self.set_config(top_tier_roles=["exception_reviewer"])
        self.assertTrue(self.only(fv("opus"), "tier").startswith("FAIL dispatch.tier: final_verifier needs tier4"))
        self.set_config(top_tier_roles="x")
        self.assertTrue(self.run_gate(fv("opus"))[0].startswith("FAIL dispatch.input"))

    def test_top_tier_fallback_value_types(self):                   # F-2c3-R1-3, P:2064
        """A top_tier_fallback that is not a str naming a set tier of tier1-tier3 fails dispatch.tier, and only for a
        dispatch of a top_tier_roles role whose minimum is tier4, tier4 being unset; every other dispatch passes."""
        cases = ((3, "3"), (None, "None"), (["tier3"], "['tier3']"), ("tier9", "tier9"), (True, "True"), ("", ""),
                 ("tier4", "tier4"), ({"a": 1}, "{'a': 1}"), ("Tier3", "Tier3"),
                 (["tier3", "tier2"], "['tier3', 'tier2']"))
        for bad, shown in cases:
            self.set_config(top_tier_fallback=bad)
            for role in ("final_verifier", "exception_reviewer"):
                with self.subTest(fallback=repr(bad), role=role):
                    d = self.base(role, model="opus", prompt=prompt(role, model="opus"))
                    out, code = self.lines(d)
                    self.assertEqual(code, 1)
                    self.assertEqual(out, ["PASS dispatch.input", "PASS dispatch.fork", "PASS dispatch.grammar",
                                           "PASS dispatch.role", "PASS dispatch.dispatcher", "PASS dispatch.program", "PASS dispatch.stream", "PASS dispatch.depth",
                                           "PASS dispatch.concurrency", "PASS dispatch.children", "PASS dispatch.model",
                                           "FAIL dispatch.tier: top_tier_fallback '%s' names a tier that is unset or "
                                           "not tier1-tier4" % shown,
                                           "FAIL dispatch.top-tier: not checked: dispatch.tier failed",
                                           "PASS dispatch.block", "PASS dispatch.budget", "PASS dispatch.size",
                                           "PASS dispatch.claims", "PASS dispatch.decisions"])
            for role in dispatch.ROLES:                              # every other role: unaffected, whole run passes
                if dispatch.MIN_TIERS[role] < 4 and role not in ("program_controller", "stream_controller"):
                    with self.subTest(fallback=repr(bad), role=role):
                        out, code = self.lines(self.base(role))
                        self.assertEqual((out, code), (ALL_PASS, 0))
        self.set_config(models={"tiers": {"tier1": "haiku", "tier2": "sonnet", "tier3": "opus", "tier4": "fable"}},
                        top_tier_fallback=3)                        # tier4 set: the fallback is never read
        d = self.base("final_verifier", model="fable", prompt=prompt("final_verifier", model="fable"))
        self.assertEqual(self.lines(d), (ALL_PASS, 0))
        self.set_config(top_tier_roles=["exception_reviewer"], top_tier_fallback=3)   # not a top_tier_roles role
        d = self.base("final_verifier", model="opus", prompt=prompt("final_verifier", model="opus"))
        self.assertEqual(self.only(d, "tier"),
                         "FAIL dispatch.tier: final_verifier needs tier4, which is unset, and is not in top_tier_roles")

    def test_top_tier_roles_bad_shapes_fail_input(self):            # F-2c3-R1-3: fail closed, for every role
        for bad in ("final_verifier", 3, [3], [""], None, [None], ["final_verifier", ""], {"final_verifier": 1}, True,
                    ["final_verifier", ["x"]]):
            self.set_config(top_tier_roles=bad)
            for role in ("implementer", "final_verifier", "controller"):
                with self.subTest(top_tier_roles=repr(bad), role=role):
                    out, code = self.run_gate(self.base(role))
                    self.assertEqual((out, code), ("FAIL dispatch.input: input: config top_tier_roles must be a list "
                                                   "of non-empty strings\n", 1))
        self.set_config(top_tier_roles=[])                          # an empty list is a list: no top tier role
        self.assertEqual(self.lines(self.base()), (ALL_PASS, 0))
        self.set_config(top_tier_roles=["final_verifier"])
        self.assertEqual(self.lines(self.base()), (ALL_PASS, 0))

    def test_top_tier_set(self):                                    # M5
        self.set_config(models={"tiers": {"tier1": "haiku", "tier2": "sonnet", "tier3": "opus", "tier4": "fable"}},
                        top_tier_fallback="tier2")
        fv = lambda m: self.base("final_verifier", model=m, prompt=prompt("final_verifier", model=m))
        self.assertEqual(self.only(fv("fable"), "tier"), "PASS dispatch.tier")
        self.assertTrue(self.only(fv("opus"), "tier").startswith("FAIL dispatch.tier"))

    def test_top_tier_only_for_top_tier_roles(self):                # M6, R2
        self.set_config(models={"tiers": {"tier1": "haiku", "tier2": "sonnet", "tier3": "opus", "tier4": "fable"}})
        ctl = lambda role, m: self.base(role, model=m, prompt=prompt(role, model=m))
        self.assertEqual(self.only(ctl("final_verifier", "fable"), "top-tier"), "PASS dispatch.top-tier")
        self.assertEqual(self.only(ctl("controller", "fable"), "top-tier"),
                         "FAIL dispatch.top-tier: tier4 is only for top_tier_roles, not controller")
        self.assertEqual(self.only(ctl("controller", "opus"), "top-tier"), "PASS dispatch.top-tier")
        self.set_config()
        self.assertEqual(self.only(ctl("controller", "opus"), "top-tier"), "PASS dispatch.top-tier")   # tier4 unset

    def test_top_tier_roles_default(self):                          # M7, D9
        self.set_config(models={"tiers": {"tier3": "opus", "tier4": "fable"}})
        self.assertEqual(self.only(self.base("exception_reviewer", model="fable",
                                              prompt=prompt("exception_reviewer", model="fable")), "top-tier"),
                         "PASS dispatch.top-tier")
        self.assertTrue(self.only(self.base("audit_reviewer", model="fable", prompt=prompt("audit_reviewer", model="fable")),
                                  "top-tier").startswith("FAIL"))

    def test_plan_writer_dispatch_from_session_passes(self):        # B8
        d = self.base("plan_writer", model="opus", prompt=prompt("plan_writer", model="opus"))
        self.assertEqual(self.lines(d), (ALL_PASS, 0))
        d = self.base("plan_writer", model="sonnet", prompt=prompt("plan_writer", model="sonnet"))
        self.assertTrue(self.only(d, "tier").startswith("FAIL"))
        for role in ("plan_reviewer",):
            d = self.base(role, model="opus", prompt=prompt(role, model="opus"))
            self.assertEqual(self.lines(d), (ALL_PASS, 0))

    def test_drafter_dispatch_at_tier2_passes(self):                # B8
        d = self.base("drafter", model="sonnet", prompt=prompt("drafter", model="sonnet"))
        out, code = self.lines(d)
        self.assertEqual((out, code), (ALL_PASS, 0))
        d = self.base("drafter", model="haiku", prompt=prompt("drafter", model="haiku"))
        out, code = self.lines(d)
        self.assertIn("FAIL dispatch.tier: tier1 is below the minimum tier2 of drafter", out)
        self.assertEqual(code, 1)

    def test_task_reviewer_minimum_is_tier2(self):                  # owner model-policy 2026-11-17: task reviewers on tier2
        self.assertEqual(dispatch.MIN_TIERS["task_reviewer"], 2)
        for model, want in (("haiku", "FAIL dispatch.tier: tier1 is below the minimum tier2 of task_reviewer"),
                            ("sonnet", "PASS dispatch.tier"), ("opus", "PASS dispatch.tier")):
            with self.subTest(model=model):
                d = self.base("task_reviewer", model=model, prompt=prompt("task_reviewer", model=model))
                self.assertEqual(self.only(d, "tier"), want)
        for role in ("final_reviewer", "final_verifier"):           # unchanged: the final roles keep their minimum
            self.assertEqual(dispatch.MIN_TIERS[role], {"final_reviewer": 3, "final_verifier": 4}[role])


class SmallGateTest(GateCase):
    def setUp(self):
        super().setUp()
        self.fid = "F-20261031-k3f9"
        write_record(self.root, ".strict-delivery/state/findings/%s.yml" % self.fid,
                     {"schema": FTAG, "id": self.fid, "severity": "LOW"})
        commit_all(self.root, "finding")
        self.a = git(self.root, "rev-parse", "HEAD")
        with open(os.path.join(self.root, "x.txt"), "w") as f:
            f.write("x\n")
        self.b = commit_all(self.root, "fix")
        # task_reviewer's minimum is tier2 (owner 2026-11-17), so the only tier a small re-review can save is tier1
        self.set_config(reviews={"small": {"tier": "tier1"}})

    def small(self, role="task_reviewer", model="haiku", line=None, findings=None, **over):
        line = LINE % (self.a[:12], self.b[:12]) if line is None else line
        findings = self.fid if findings is None else findings
        return self.base(role, model=model, prompt=prompt(role, model=model, brief="intro\n" + line + "\nend",
                                                          findings=findings), **over)

    def test_small_re_review_below_min_tier_passes(self):           # S13
        out, code = self.lines(self.small())
        self.assertEqual(code, 0, out)
        self.assertIn("PASS dispatch.tier", out)
        self.assertIn("PASS dispatch.small", out)
        self.assertEqual(out.index("PASS dispatch.small") - out.index("PASS dispatch.tier"), 1)   # plan order

    def test_small_re_review_failing_condition_refused(self):       # S14
        for name, kw in (("not a finding", {"findings": "F-20261031-zzzz"}), ("no ids", {"findings": ""}),
                         ("round 5", {"line": (LINE % (self.a[:12], self.b[:12])).replace("round=2", "round=5")})):
            with self.subTest(name):
                out, code = self.lines(self.small(**kw))
                self.assertEqual(code, 1)
                self.assertTrue(any(ln.startswith("FAIL dispatch.small: ") for ln in out), out)
                self.assertTrue(any(ln.startswith("FAIL dispatch.tier: tier1 is below") for ln in out), out)

    def test_small_tier_variants(self):                             # S13
        # a small tier at or above the minimum (tier2) is allowed and saves nothing: tier2 passes on its own
        for cfgtier, tier, ok in (("tier1", 1, True), ("tier1", 2, True), ("tier2", 1, False), ("tier2", 2, True),
                                  ("tier3", 1, False), ("tier3", 2, True), ("tier3", 3, True)):
            with self.subTest(cfgtier=cfgtier, tier=tier):
                self.set_config(reviews={"small": {"tier": cfgtier}})
                a = git(self.root, "rev-parse", "HEAD~1")
                b = git(self.root, "rev-parse", "HEAD")
                d = self.small(model=MODELS[tier], line=LINE % (self.a[:12], self.b[:12]))
                got = self.only(d, "tier")
                self.assertEqual(got.startswith("PASS"), ok, got)
                del a, b

    def test_small_line_at_min_tier(self):                          # S15, D11
        for line in ("small-re-review: plan=p", (LINE % (self.a[:12], self.b[:12])).replace("round=2", "round=5")):
            out, code = self.lines(self.small(model="opus", line=line))
            self.assertIn("PASS dispatch.tier", out)
            self.assertTrue(any(ln.startswith("FAIL dispatch.small") for ln in out), out)
            self.assertEqual(code, 1)

    def test_small_line_long_numbers(self):                         # F-2c3-R1-4, I1, I2, K1 (G1)
        ln = LINE % (self.a[:12], self.b[:12])
        for lim in INT_LIMITS:
            with int_limit(lim):
                self.small_line_long_numbers(ln, lim)

    def small_line_long_numbers(self, ln, lim):
        for n in (1, 9, 10, 11, 600):                               # narrowed ids of any length up to 600 digits pass
            with self.subTest(limit=lim, n=n, key="narrowed"):
                out, code = self.lines(self.small(line=ln.replace("narrowed=none", "narrowed=1,%s" % ("7" * n))))
                self.assertEqual(code, 0, out)
                self.assertIn("PASS dispatch.small", out)
                self.assertIn("PASS dispatch.tier", out)
        for n in (1, 9, 10, 11, 600):                               # a long round is parsed, then refused as a reason
            with self.subTest(limit=lim, n=n, key="round"):
                out, code = self.lines(self.small(line=ln.replace("round=2", "round=%s" % ("7" * n))))
                self.assertEqual(code, 1)
                self.assertIn("FAIL dispatch.small: round %s: only rounds 1-4 may be small; round 5 always runs at "
                              "the minimum tier" % ("7" * n), out)
                self.assertIn("FAIL dispatch.tier: tier1 is below the minimum tier2 of task_reviewer", out)
        for n in (601, 700, 4300, 4301):
            for key, text in (("round", ln.replace("round=2", "round=" + "7" * n)),
                              ("narrowed", ln.replace("narrowed=none", "narrowed=" + "7" * n)),
                              ("narrowed", ln.replace("narrowed=none", "narrowed=1," + "7" * n))):
                with self.subTest(limit=lim, n=n, key=key):
                    out, code = self.lines(self.small(line=text))
                    self.assertEqual(code, 1)
                    self.assertIn("FAIL dispatch.small: small-re-review: key %s is malformed" % key, out)
                    self.assertTrue(any(x.startswith("FAIL dispatch.tier") for x in out), out)
        for key, text in (("round", ln.replace("round=2", "round=٥")),
                          ("round", ln.replace("round=2", "round=５")),
                          ("narrowed", ln.replace("narrowed=none", "narrowed=٥"))):        # K2
            with self.subTest(limit=lim, key=key, shape="non-ASCII digit"):
                out, code = self.lines(self.small(line=text))
                self.assertEqual(code, 1)
                self.assertIn("FAIL dispatch.small: small-re-review: key %s is malformed" % key, out)

    def test_malformed_below_min_fails_both(self):                  # S3
        out, _ = self.lines(self.small(line="small-re-review: plan=p"))
        self.assertTrue(any(ln.startswith("FAIL dispatch.small: small-re-review: key task") for ln in out), out)
        self.assertTrue(any(ln.startswith("FAIL dispatch.tier") for ln in out))

    def test_small_line_ignored_on_other_roles(self):               # S5
        for role in ("final_reviewer", "implementer"):
            out, _ = self.lines(self.small(role=role, model="haiku"))
            self.assertFalse(any("dispatch.small" in ln for ln in out), out)
            self.assertTrue(any(ln.startswith("FAIL dispatch.tier") for ln in out))
        out, _ = self.lines(self.small(role="task_reviewer", model="haiku", line="no small line here"))
        self.assertFalse(any("dispatch.small" in ln for ln in out))
        self.assertTrue(any(ln.startswith("FAIL dispatch.tier") for ln in out))


class RegisterTest(GateCase):
    def decision(self, did, status="answered", **kw):
        row = {"id": did, "status": status, "class": "scope", "effect": "lasting", "question": "q", "answer": "a",
               "topics": [], "applies_to": []}
        row.update(kw)
        write_record(self.root, ".strict-delivery/state/decisions/%s.yml" % did, row)

    def test_decisions_line(self):                                  # Q2
        self.decision("DEC-20261031-k3f9")
        self.decision("DEC-20261031-m4n5", status="open")
        mk = lambda text: self.base(prompt=prompt("implementer", brief=text))
        self.assertEqual(self.only(mk("none"), "decisions"), "PASS dispatch.decisions")
        self.assertEqual(self.only(mk("see DEC-20261031-k3f9."), "decisions"), "PASS dispatch.decisions")
        self.assertEqual(self.only(mk("see DEC-20261031-m4n5"), "decisions"),
                         "FAIL dispatch.decisions: DEC-20261031-m4n5 is an open decision")
        self.assertEqual(self.only(mk("see DEC-20261031-zzzz"), "decisions"),
                         "FAIL dispatch.decisions: DEC-20261031-zzzz names no decision")
        self.assertEqual(self.only(mk("XDEC-20261031-zzzz DEC-20261031-zzzza"), "decisions"), "PASS dispatch.decisions")
        # the strict block is never read for ids
        d = self.base(prompt=prompt("implementer", body="# Strict block: implementer\n\nDEC-20261031-zzzz\n"))
        with open(os.path.join(self.prompts, "implementer.md"), "w") as f:
            f.write("# Strict block: implementer\n\nDEC-20261031-zzzz\n")
        self.assertEqual(self.only(d, "decisions"), "PASS dispatch.decisions")

    def test_in_force_lines(self):                                  # Q3
        self.decision("DEC-20261031-k3f9", applies_to=["gates/*.py"])
        self.decision("DEC-20261031-m4n5", applies_to=["docs/**"])
        self.decision("DEC-20261031-p6q7", applies_to=["gates/*.py"], supersedes="DEC-20261031-k3f9")
        self.decision("DEC-20261031-r8s9", applies_to=["gates/*.py"], status="open")
        d = self.base(prompt=prompt("implementer", brief="edit `gates/x.py`, then (src/y.txt)."))
        out, _ = self.lines(d)
        self.assertEqual([ln for ln in out if "in-force" in ln], ["PASS dispatch.in-force.DEC-20261031-p6q7"])
        d = self.base(prompt=prompt("implementer", brief="docs/a/b.md gates/z.py"))
        out, _ = self.lines(d)
        self.assertEqual([ln for ln in out if "in-force" in ln],
                         ["PASS dispatch.in-force.DEC-20261031-m4n5", "PASS dispatch.in-force.DEC-20261031-p6q7"])

    def claim_fixture(self):
        for rel, text in (("docs/a.md", "# A\n"), ("src/x.txt", "x\n")):
            p = os.path.join(self.root, rel)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w") as f:
                f.write(text)
        blob = git(self.root, "hash-object", "--", "src/x.txt")
        c = {"id": "C-20261031-k3f9", "text": "x holds", "cites": [{"path": "src/x.txt", "lines": "1", "blob": blob}],
             "direct": "grep -n x src/x.txt", "contradiction": "grep -c y src/x.txt", "by": "implementer"}
        write_record(self.root, ".strict-delivery/state/claims/docs--a.yml",
                     {"schema": CTAG, "document": "docs/a.md", "claims": [c]})
        commit_all(self.root, "claims")

    def test_claims_line(self):                                     # Q1
        self.claim_fixture()
        mk = lambda text: self.base(prompt=prompt("implementer", claims=text))
        self.assertEqual(self.only(mk(""), "claims"), "PASS dispatch.claims")
        self.assertEqual(self.only(mk("C-20261031-k3f9"), "claims"), "PASS dispatch.claims")
        self.assertEqual(self.only(mk("C-20261031-zzzz"), "claims"), "FAIL dispatch.claims: C-20261031-zzzz names no claim")
        with open(os.path.join(self.root, "src/x.txt"), "w") as f:
            f.write("changed\n")
        got = self.only(mk("C-20261031-k3f9"), "claims")
        self.assertTrue(got.startswith("FAIL dispatch.claims: C-20261031-k3f9 is stale: "), got)

    def test_exception_groups(self):                                # V3
        self.claim_fixture()
        d = self.base(prompt=prompt("implementer", claims="C-20261031-k3f9"))
        if not hasattr(builtins, "ExceptionGroup"):
            self.skipTest("ExceptionGroup is absent before Python 3.11")
        eg = ExceptionGroup("x", [ValueError()])           # noqa: F821
        with mock.patch.object(claims_lib, "load", side_effect=eg):
            out, code = self.run_gate(d)
        self.assertEqual((out, code), ("FAIL dispatch.input: ExceptionGroup: x (1 sub-exception)\n", 1))
        beg = BaseExceptionGroup("x", [KeyboardInterrupt()])   # noqa: F821
        with mock.patch.object(claims_lib, "load", side_effect=beg):
            with self.assertRaises(BaseExceptionGroup):         # noqa: F821
                self.run_gate(d)


class VersionTest(GateCase):
    def test_digit_limits_same_on_both(self):                       # V1, I3, I4, K1 (G2, G3)
        for lim in INT_LIMITS:
            with int_limit(lim):
                self.digit_limits_same_on_both(lim)

    def test_derived_max_depth_printed_in_full(self):               # I5 (G4): max_depth = env depth + 1 has 601 digits
        nines, ten = "9" * 600, "1" + "0" * 600
        want_depth = ("FAIL dispatch.depth: dispatcher depth %s + 1 + 1 level(s) below controller exceeds max_depth %s"
                      % (nines, ten))
        raw = json.dumps({"prompt": prompt("controller", model="sonnet"), "model": "sonnet", "program_live": False,
                          "dispatcher": {"id": "session", "depth": 0, "live_children": 0, "live_total": 0}})
        raw = raw.replace('"depth": 0', '"depth": ' + nines)
        outs = []
        for lim in INT_LIMITS:
            with int_limit(lim):
                os.environ[ENV_D] = nines
                with self.subTest(limit=lim):
                    out, code = self.run_gate(self.write_input(raw.encode()))
                    outs.append(out)
                    self.assertEqual(code, 1)
                    self.assertEqual(len(out.splitlines()), 18, out)
                    self.assertIn(want_depth, out.splitlines())
        self.assertEqual(len(set(outs)), 1)                          # the same bytes under every limit setting
        os.environ.pop(ENV_D)

    def test_non_ascii_digits_in_integers(self):                    # K2: no isdigit/isdecimal decides
        for lim in INT_LIMITS:
            with int_limit(lim):
                for text in ('"٥"', '"５"', '"\U0001FAE8"'):
                    with self.subTest(limit=lim, text=text):
                        d = json.dumps(self.base()).replace('"depth": 0', '"depth": ' + text)
                        out, code = self.run_gate(self.write_input(d.encode()))
                        self.assertEqual((out.count("\n"), code), (1, 1))
                        self.assertTrue(out.startswith("FAIL dispatch.input: input: dispatcher.depth must be"), out)
                for name in (ENV_D, ENV_C):
                    for val in ("٥", "５"):
                        os.environ[name] = val
                        with self.subTest(limit=lim, env=name, value=val):
                            out, code = self.run_gate(self.base())
                            self.assertEqual(code, 1)
                            self.assertTrue(out.startswith("FAIL dispatch.input: input: %s must be a decimal" % name), out)
                        os.environ.pop(name)

    def digit_limits_same_on_both(self, lim):
        """The whole output, not a prefix: the reason text is the gate's own on both interpreters (F-2c3-R1-5)."""
        def raw(field, text):
            disp = {"depth": "0", "live_children": "0", "live_total": "0"}
            disp[field] = text
            return ('{"prompt": %s, "model": "sonnet", "dispatcher": {"id": "session", "depth": %s, "live_children": %s, '
                    '"live_total": %s}, "program_live": false}' % (json.dumps(prompt("implementer")), disp["depth"],
                                                                   disp["live_children"], disp["live_total"])).encode()

        def refused(path):                      # the gate's own text, written here, with no interpreter wording in it
            return "FAIL dispatch.input: input: %s: not valid UTF-8 JSON (an integer of more than 600 digits)\n" % path

        for field in ("depth", "live_children", "live_total"):
            for text in ("9" * 601, "-" + "9" * 601, "1" + "0" * 699, "9" * 4300, "9" * 4301, "-" + "9" * 4301,
                         "1" + "0" * 4300, "9" * 4301 + "0" * 3):
                with self.subTest(limit=lim, field=field, digits=len(text.lstrip("-")), sign=text[0]):
                    path = self.write_input(raw(field, text))
                    self.assertEqual(self.run_gate(path), (refused(path), 1))
            with self.subTest(limit=lim, field=field, digits=600, sign="-"):  # parsed (the sign is no digit), then negative
                self.assertEqual(self.run_gate(self.write_input(raw(field, "-" + "9" * 600))),
                                 ("FAIL dispatch.input: input: dispatcher.%s must be an integer of at least 0\n" % field,
                                  1))
            with self.subTest(limit=lim, field=field, digits=600):       # 600 digits parse, then the line judges them
                out, code = self.lines(self.write_input(raw(field, "9" * 600)))
                self.assertEqual(out, {
                    "depth": ["PASS dispatch.input", "PASS dispatch.fork", "PASS dispatch.grammar", "PASS dispatch.role",
                              "PASS dispatch.dispatcher", "PASS dispatch.program", "PASS dispatch.stream", "FAIL dispatch.depth: dispatcher depth %s + 1 + 0 "
                              "level(s) below implementer exceeds max_depth 3" % ("9" * 600), "PASS dispatch.concurrency",
                              "PASS dispatch.children", "PASS dispatch.model", "PASS dispatch.tier",
                              "PASS dispatch.top-tier", "PASS dispatch.block", "PASS dispatch.budget",
                              "PASS dispatch.size", "PASS dispatch.claims", "PASS dispatch.decisions"],
                    "live_children": ALL_PASS,
                    "live_total": ["PASS dispatch.input", "PASS dispatch.fork", "PASS dispatch.grammar",
                                   "PASS dispatch.role", "PASS dispatch.dispatcher", "PASS dispatch.program", "PASS dispatch.stream", "PASS dispatch.depth",
                                   "FAIL dispatch.concurrency: %s running + 1 exceeds max_concurrent 20" % ("9" * 600),
                                   "PASS dispatch.children", "PASS dispatch.model", "PASS dispatch.tier",
                                   "PASS dispatch.top-tier", "PASS dispatch.block", "PASS dispatch.budget",
                                   "PASS dispatch.size", "PASS dispatch.claims", "PASS dispatch.decisions"]}[field])
                self.assertEqual(code, 0 if field == "live_children" else 1)
        for name, text in ((ENV_D, "depth"), (ENV_C, "concurrency")):
            for n in (601, 700, 4300, 4301, 5000):
                os.environ[name] = "9" * n
                with self.subTest(limit=lim, env=name, digits=n):
                    self.assertEqual(self.run_gate(self.base()), (
                        "FAIL dispatch.input: input: %s must be a decimal integer of at least 1 (digits 0-9 only, no sign, "
                        "space or leading zero, at most 600 digits)\n" % name, 1))
            os.environ[name] = "9" * 600
            with self.subTest(limit=lim, env=name, digits=600):          # accepted, min with the default
                self.assertEqual(self.lines(self.base()), (ALL_PASS, 0))
            os.environ.pop(name)
        big = prompt("implementer").replace("tokens=1000", "tokens=" + "1" * 4301)
        self.assertEqual(self.lines(self.base(prompt=big)), (ALL_PASS, 0))                 # budget by regex only

    def test_unicode_version_independent(self):                     # V2
        for cp in ("\U0001fae8", "ࡰ"):
            for field, data in (("id", self.base(dispatcher=dict(SESSION, id="a" + cp))),
                                ("role", self.base(prompt=prompt("implementer" + cp))),
                                ("model", self.base(model="sonnet" + cp)),
                                ("key", self.base(prompt=prompt("task_reviewer", brief="small-re-review: plan=p " + cp + "=1"),
                                                  model="haiku"))):
                with self.subTest(cp=hex(ord(cp[0])), field=field):
                    out, code = self.run_gate(data)
                    self.assertEqual(code, 1)
                    self.assertTrue(out.isascii(), out)           # escaped through result's frozen table
        out, _ = self.run_gate(self.base(prompt=prompt("implementerࡰ")))
        self.assertIn("FAIL dispatch.role: the first non-empty line of ## Role must be exactly one role id, not "
                      "'implementer\\u0870'", out)


REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BRIEF = "program: %s\nstream: a" % NAME
PROG_ORDER = ["PASS dispatch.dispatcher", "PASS dispatch.program", "PASS dispatch.stream"]


def ids(out):
    return [ln.split(":")[0].split(" ")[1] for ln in out]


class ProgramLinesTest(GateCase):
    """Task P4.3, rows GL1-GL21 of task-P4.3-domain.md with D-Q5 (a): the lines come right after dispatch.dispatcher."""

    def setUp(self):
        super().setUp()
        for key, val in (("color.ui", "always"), ("color.diff", "always"), ("core.abbrev", "7")):
            git(self.root, "config", key, val)

    def stream_dispatch(self, brief=BRIEF, live=True, **over):
        d = self.base("stream_controller", program_live=live, prompt=prompt("stream_controller", brief=brief,
                                                                           model=MODELS[3]))
        d.update(over)
        return d

    def test_session_dispatches_stream_controller_in_live_program(self):     # GL1, Q-H5 (a)
        add_program(self.root)
        out, code = self.lines(self.stream_dispatch())
        self.assertEqual(code, 0, out)
        self.assertEqual(out[4:7], PROG_ORDER)
        self.assertEqual(ids(out)[:8], ["dispatch.input", "dispatch.fork", "dispatch.grammar", "dispatch.role",
                                        "dispatch.dispatcher", "dispatch.program", "dispatch.stream", "dispatch.depth"])
        self.assertTrue(all(ln.startswith("PASS") for ln in out), out)

    def test_stream_controller_without_live_program_refused(self):           # GL2
        out, code = self.lines(self.stream_dispatch(live=False))
        self.assertEqual(code, 1)
        self.assertIn("FAIL dispatch.dispatcher: session may not dispatch stream_controller (program_live false; "
                      "allowed: none)", out)
        self.assertTrue(any(ln.startswith("FAIL dispatch.program: ") for ln in out), out)
        self.assertTrue(any(ln.startswith("FAIL dispatch.stream: ") for ln in out), out)

    def test_gate_claim_false_against_live_program_fails_program_line(self):  # GL3, GL4
        add_program(self.root)
        out, code = self.lines(self.base("implementer", program_live=False))
        self.assertEqual(code, 1)
        self.assertIn("PASS dispatch.dispatcher", out)
        got = [ln for ln in out if ln.startswith("FAIL dispatch.program")]
        self.assertEqual(got, ["FAIL dispatch.program: program_live is false in the input, but true in git "
                               "(1 live program(s))"])
        self.assertIn("PASS dispatch.stream", out)
        os.environ.pop(ENV_D, None)
        git(self.root, "branch", "-q", "-D", NAME + "/integration")
        d = self.base("controller", program_live=True, dispatcher=dict(SESSION, id="stream_controller", depth=1))
        out, code = self.lines(d)
        self.assertEqual(code, 1)
        self.assertIn("FAIL dispatch.program: program_live is true in the input, but false in git "
                      "(0 live program(s))", out)

    def test_session_dispatches_program_controller(self):                   # GL5
        add_program(self.root)
        out, code = self.lines(self.base("program_controller", program_live=True,
                                         prompt=prompt("program_controller", brief="program: " + NAME, model=MODELS[3])))
        self.assertEqual((out[4:8], code), (PROG_ORDER + ["PASS dispatch.depth"], 0), out)

    def test_program_roles_depth_matrix(self):                             # GL6
        add_program(self.root)
        for role in ("program_controller", "stream_controller"):
            brief = "program: " + NAME if role == "program_controller" else BRIEF
            for limit, env in ((3, None), (6, "5")):
                for depth in (0, 1):
                    want = {("program_controller", 3, 0): True, ("program_controller", 3, 1): False,
                            ("program_controller", 6, 0): True, ("program_controller", 6, 1): True,
                            ("stream_controller", 3, 0): True, ("stream_controller", 3, 1): True,
                            ("stream_controller", 6, 0): True, ("stream_controller", 6, 1): True}[(role, limit, depth)]
                    with self.subTest(role=role, limit=limit, depth=depth):
                        os.environ.pop(ENV_D, None)
                        if env:
                            os.environ[ENV_D] = env
                        # a depth-1 dispatcher of program_controller (the one controller the session may not be at depth 1)
                        disp = dict(SESSION, depth=depth)
                        out, _ = self.lines(self.base(role, program_live=True, dispatcher=disp,
                                                      prompt=prompt(role, brief=brief, model=MODELS[3])))
                        self.assertIn("PASS dispatch.dispatcher", out)
                        self.assertIn("PASS dispatch.program", out)
                        self.assertEqual(any(ln.startswith("PASS dispatch.depth") for ln in out), want, out)

    def test_program_controller_dispatches_stream_controller(self):         # GL7
        add_program(self.root)
        d = self.stream_dispatch(dispatcher=dict(SESSION, id="program_controller", depth=1))
        out, code = self.lines(d)
        self.assertEqual((out[4:8], code), (PROG_ORDER + ["PASS dispatch.depth"], 0), out)

    def test_stream_controller_cannot_dispatch_program_controller(self):    # GL8
        add_program(self.root)
        d = self.base("program_controller", program_live=True, dispatcher=dict(SESSION, id="stream_controller", depth=1),
                      prompt=prompt("program_controller", brief="program: " + NAME, model=MODELS[3]))
        self.assertTrue(self.only(d, "dispatcher").startswith("FAIL dispatch.dispatcher: stream_controller may not "))

    def test_worker_dispatcher_refused_with_program_lines(self):            # GL9
        add_program(self.root)
        for w in ("implementer", "task_reviewer"):
            for role in ("stream_controller", "program_controller"):
                with self.subTest(w=w, role=role):
                    out, code = self.lines(self.base(role, program_live=True, dispatcher=dict(SESSION, id=w),
                                                     prompt=prompt(role, brief=BRIEF, model=MODELS[3])))
                    self.assertIn("FAIL dispatch.dispatcher: %s is a worker role, and a worker dispatches no agent" % w, out)
                    self.assertTrue({"dispatch.program", "dispatch.stream"} <= set(ids(out)))
                    self.assertEqual(code, 1)

    def test_program_lines_not_checked_without_role(self):                  # GL10
        for brief_prompt in (prompt("implementer").replace("## Role\nimplementer\n\n", ""),
                             prompt("implementer").replace("## Role\nimplementer", "## Role\nboss")):
            out, code = self.lines(self.base(prompt=brief_prompt))
            self.assertEqual(code, 1)
            self.assertIn("FAIL dispatch.dispatcher: not checked: dispatch.role failed", out)
            self.assertIn("FAIL dispatch.program: not checked: dispatch.role failed", out)
            self.assertIn("FAIL dispatch.stream: not checked: dispatch.role failed", out)
            i = ids(out)
            self.assertEqual(i[i.index("dispatch.dispatcher"):i.index("dispatch.dispatcher") + 4],
                             ["dispatch.dispatcher", "dispatch.program", "dispatch.stream", "dispatch.depth"])

    def test_input_failure_prints_only_input_line(self):                    # GL11
        out, code = self.lines(self.base(program_live="yes"))
        self.assertEqual((len(out), code), (1, 1))
        self.assertTrue(out[0].startswith("FAIL dispatch.input: "))

    def test_program_line_joins_reasons(self):                              # GL12
        add_program(self.root)
        out, _ = self.lines(self.stream_dispatch(brief="nothing", live=False))
        got = [ln for ln in out if ln.startswith("FAIL dispatch.program: ")][0]
        parts = got[len("FAIL dispatch.program: "):].split("; ")
        self.assertEqual(len(parts), 2, got)
        self.assertTrue(parts[0].startswith("program_live is false in the input"))
        self.assertTrue(parts[1].startswith("## Brief holds no line 'program: <program>'"))

    def test_stream_line_fails_for_unknown_stream(self):                    # BL14 through the gate
        add_program(self.root)
        out, code = self.lines(self.stream_dispatch(brief="program: %s\nstream: nope" % NAME))
        self.assertEqual(code, 1)
        self.assertIn("PASS dispatch.program", out)
        self.assertTrue(any(ln.startswith("FAIL dispatch.stream: ") for ln in out))

    def test_stream_not_checked_after_program_failure(self):                # D-Q4 through the gate
        add_program(self.root)
        out, _ = self.lines(self.stream_dispatch(brief="program: 20261102-y\nstream: a"))
        self.assertIn("FAIL dispatch.stream: stream not checked: the program line failed", out)

    def test_program_lines_git_failure(self):                              # GL15, D-Q3: live_programs' GateError
        with mock.patch.object(programs, "live_programs", side_effect=GateError("refs are broken")):
            out, code = self.lines(self.base())
        self.assertEqual((out, code), (["FAIL dispatch.input: refs are broken"], 1))

    def test_program_roles_min_tier(self):                                  # GL17
        add_program(self.root)
        for role in ("program_controller", "stream_controller"):
            brief = "program: " + NAME if role == "program_controller" else BRIEF
            for model, ok in ((MODELS[3], True), (MODELS[2], False), (MODELS[1], False)):
                with self.subTest(role=role, model=model):
                    d = self.base(role, program_live=True, model=model, prompt=prompt(role, brief=brief, model=model))
                    self.assertEqual(self.only(d, "tier").startswith("PASS"), ok)

    def test_run_all_has_no_dispatch_line(self):                           # GL21
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
            gates_main.main(["run_all", "--root", self.root])
        self.assertNotIn("dispatch.", buf.getvalue())

    def test_gate_dispatch_subprocess(self):                               # GL18
        add_program(self.root)
        path = self.write_input(self.stream_dispatch())
        env = dict(os.environ, PYTHONPATH=REPO)
        p = subprocess.run([sys.executable, "-m", "gates", "check", "dispatch", "--root", self.root, "--input", path,
                            "--prompts", self.prompts], cwd=REPO, env=env, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE)
        inproc, code = self.lines(path)
        self.assertEqual((p.returncode, p.stdout.decode("utf-8").splitlines()), (code, inproc))
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertEqual(p.stdout.decode("utf-8").splitlines()[4:7], PROG_ORDER)

    def real(self, role):
        with open(os.path.join(REPO, "skills", "strict-delivery", "prompts", role + ".md"), encoding="utf-8",
                  newline="") as fh:
            return fh.read()

    def real_dispatch(self, role, **over):
        brief = "program: " + NAME if role == "program_controller" else BRIEF
        return self.base(role, program_live=True, prompt=prompt(role, brief=brief, model=MODELS[3],
                                                                body=self.real(role)), **over)

    def test_program_role_blocks_present_byte_equal_and_absent(self):      # GL16, plan P:3218
        add_program(self.root)
        real_dir = os.path.join(REPO, "skills", "strict-delivery", "prompts")
        for role in ("program_controller", "stream_controller"):
            d = self.real_dispatch(role)
            with self.subTest(role=role, case="present"):
                out, code = self.run_gate(d, "--prompts", real_dir, prompts=False)
                self.assertIn("PASS dispatch.block\n", out)
                self.assertEqual(code, 0, out)
            for name, body in (("one byte", self.real(role).replace("Zero bugs.", "Zero bug.", 1)
                                if role == "stream_controller" else self.real(role).replace("Sync.", "Sync", 1)),
                               ("trailing space", self.real(role).replace("\n\n", " \n\n", 1)),
                               ("CRLF", self.real(role).replace("\n", "\r\n")),
                               ("BOM", "﻿" + self.real(role))):
                with self.subTest(role=role, case=name):
                    bad = self.real_dispatch(role)
                    bad["prompt"] = prompt(role, brief="program: %s\nstream: a" % NAME, model=MODELS[3], body=body)
                    out, code = self.run_gate(bad, "--prompts", real_dir, prompts=False)
                    self.assertIn("FAIL dispatch.block: ## Strict block is not the block ", out)
            with self.subTest(role=role, case="absent"):
                empty = os.path.join(self.tmp, "emptyprompts")
                os.makedirs(empty, exist_ok=True)
                out, code = self.run_gate(d, "--prompts", empty, prompts=False)
                self.assertIn("FAIL dispatch.block: strict block file %s cannot be read (No such file or directory)"
                              % os.path.join(empty, role + ".md"), out)
                self.assertEqual(code, 1)

    def test_default_prompts_dir_serves_program_blocks(self):              # GL19, via the subprocess's own package
        add_program(self.root)
        os.makedirs(os.path.join(self.root, "skills", "strict-delivery", "prompts"))     # a decoy under --root
        for role in ("program_controller", "stream_controller"):
            path = self.write_input(self.real_dispatch(role))
            p = subprocess.run([sys.executable, "-m", "gates", "check", "dispatch", "--root", self.root, "--input", path],
                               cwd=REPO, env=dict(os.environ, PYTHONPATH=REPO), stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE)
            out = p.stdout.decode("utf-8")
            self.assertEqual(p.returncode, 0, out)
            self.assertIn("PASS dispatch.block\n", out)
            self.assertNotIn("FAIL", out)


class StepFiveTest(GitIsolatedTestCase):
    """Task P4.3 Step 5 (rows EN1-EN9, D-Q10 (a)): a repository carrying this checkout's real gates package and prompt
    blocks; ``program create``, then the commit of the program folder on the integration branch, then the gate."""

    def setUp(self):
        super().setUp()
        for name in (ENV_D, ENV_C):
            os.environ.pop(name, None)
        from tests import test_program_cli as pcli
        self.pcli = pcli
        self.fx = pcli.Fx("create")
        self.fx.tmp, self.fx.work = self.tmp, self.work
        self.fx.addCleanup = self.addCleanup
        pcli.make_repo(self.work)
        self.fx.write_main(pcli.PG + "/%s.md" % pcli.PLAN, pcli.PLAN_TEXT)
        pcli.write_record(self.work, "%s/%s/breakdown.yml" % (pcli.PS, pcli.PLAN), pcli.breakdown_row())
        self.fx.decision(pcli.DEC)
        for key, val in (("color.ui", "always"), ("color.diff", "always"), ("core.abbrev", "7")):
            git(self.work, "config", key, val)
        shutil.copytree(os.path.join(REPO, "gates"), os.path.join(self.work, "gates"),
                        ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copytree(os.path.join(REPO, "profiles"), os.path.join(self.work, "profiles"))  # Task 4a.2: config.load reads profiles/<p>.yml
        shutil.copytree(os.path.join(REPO, "skills", "strict-delivery", "prompts"),
                        os.path.join(self.work, "skills", "strict-delivery", "prompts"))
        commit_all(self.work, "plan")
        self.fx.iw = os.path.join(self.tmp, "w", NAME, "integration")
        git(self.work, "worktree", "add", "-q", "-b", NAME + "/integration", self.fx.iw, "main")
        self.fx.sf = os.path.join(self.tmp, "streams.yml")
        self.fx.set_streams(pcli.streams_row())
        self.n = 0

    def gate(self, role="stream_controller", brief=BRIEF, live=True, dispatcher=None, body=None):
        self.n += 1
        with open(os.path.join(self.work, "skills", "strict-delivery", "prompts", role + ".md"), encoding="utf-8",
                  newline="") as fh:
            real = fh.read()
        model = config.load(self.work)["models"]["tiers"]["tier3"]
        data = {"prompt": prompt(role, brief=brief, model=model, body=real if body is None else body), "model": model,
                "dispatcher": dispatcher or dict(SESSION), "program_live": live}
        path = os.path.join(self.tmp, "step5-%d.json" % self.n)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        p = subprocess.run([sys.executable, "-m", "gates", "check", "dispatch", "--root", self.work, "--input", path],
                           cwd=self.work, env=dict(os.environ, PYTHONPATH=""), stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE)
        return p.stdout.decode("utf-8").splitlines(), p.returncode

    def test_step5_enable(self):                                           # EN1-EN9
        code, out, err = self.fx.create()
        self.assertEqual((code, err, out), (0, "", "push %s/integration\n" % NAME))        # EN5
        before, bcode = self.gate()                                         # EN6: not committed yet: not live
        self.assertEqual(bcode, 1)
        self.assertTrue(any(ln.startswith("FAIL dispatch.program: ") for ln in before), before)
        self.fx.commit_iw()                                                 # D-Q10 (a)
        out, code = self.gate()                                             # EN8
        self.assertEqual(code, 0, out)
        self.assertTrue(out and all(ln.startswith("PASS ") for ln in out), out)
        for want in ("dispatch.dispatcher", "dispatch.program", "dispatch.stream", "dispatch.block", "dispatch.tier",
                     "dispatch.depth"):
            self.assertIn("PASS " + want, out)
        out, code = self.gate("program_controller", brief="program: " + NAME)
        self.assertEqual(code, 0, out)
        for name, kw, want in (                                             # EN9
                ("claim", dict(live=False), "FAIL dispatch.program: "),
                ("unknown stream", dict(brief="program: %s\nstream: nope" % NAME), "FAIL dispatch.stream: "),
                ("no program line", dict(brief="stream: a"), "FAIL dispatch.program: "),
                ("worker dispatcher", dict(dispatcher=dict(SESSION, id="implementer")), "FAIL dispatch.dispatcher: "),
                ("block byte", dict(body="x"), "FAIL dispatch.block: ")):
            with self.subTest(name):
                out, code = self.gate(**kw)
                self.assertEqual(code, 1, out)
                self.assertTrue(any(ln.startswith(want) for ln in out), out)
        git(self.work, "worktree", "remove", "--force", self.fx.iw)
        git(self.work, "branch", "-q", "-D", NAME + "/integration")
        out, code = self.gate()
        self.assertEqual(code, 1)
        self.assertTrue(any(ln.startswith("FAIL dispatch.program: ") for ln in out), out)


# ---------------------------------------------------------------- Task 4b.2: project roles, budget caps, prompt size cap
# Rows RO, MC, DR, MT, PP, BU, SZ, LN, CF, V of task-4b.2-domain.md; every expected line is written out by hand.

FRAMEWORK_IDS = ["program_controller", "stream_controller", "controller", "implementer", "implementer_transcription",
                 "task_reviewer", "final_reviewer", "final_verifier", "exception_reviewer", "audit_reviewer",
                 "audit_verifier", "investigator", "plan_writer", "plan_reviewer", "drafter"]
TIERS4 = {"tiers": {"tier1": "haiku", "tier2": "sonnet", "tier3": "opus", "tier4": "fable"}}
BUDGET_HEAD = "## Budget: tokens=1000 minutes=10"
BLOCK_ERR = "FAIL dispatch.block: ## Strict block is not the block p.md byte for byte (blank line, the file, blank line)"


def with_budget(text, tokens, minutes):
    assert BUDGET_HEAD in text
    return text.replace(BUDGET_HEAD, "## Budget: tokens=%s minutes=%s" % (tokens, minutes), 1)


class ProjectCase(GateCase):
    """``doc_writer`` (prompt ``p.md``, min_tier tier2) in the config and its prompt file in the working tree."""

    def setUp(self):
        super().setUp()
        self.write_prompt("p.md", block("doc_writer"))
        self.set_roles()

    def write_prompt(self, rel, text):
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(text if isinstance(text, bytes) else text.encode("utf-8"))
        return path

    def set_roles(self, roles=None, **extra):
        roles = {"doc_writer": {"prompt": "p.md", "min_tier": "tier2"}} if roles is None else roles
        self.set_config(roles=roles, **extra)

    def proj(self, role="doc_writer", model="sonnet", body=None, **over):
        d = {"prompt": prompt(role, model=model, body=body), "model": model, "dispatcher": dict(SESSION),
             "program_live": False}
        d.update(over)
        return d

    def run_json(self, data):
        argv = ["check", "dispatch", "--json", "--root", self.root, "--input", self.write_input(data),
                "--prompts", self.prompts]
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
            gates_main.main(argv)
        return json.loads(buf.getvalue())


class RolesTest(ProjectCase):
    def test_project_role_dispatch_passes(self):                    # DR2, PP3, LN1
        out, code = self.lines(self.proj())
        self.assertEqual((out, code), (ALL_PASS, 0))

    def test_project_role_collision_fails(self):                    # RO4, CF3, Q2
        for rid in FRAMEWORK_IDS:
            with self.subTest(rid):
                self.set_roles({rid: {"prompt": "p.md", "min_tier": "tier2"}})
                out, code = self.lines(self.base())
                self.assertEqual(code, 1)
                self.assertIn("FAIL dispatch.role: %s: a project role may not reuse a framework role id" % rid, out)
                self.assertIn("FAIL dispatch.dispatcher: not checked: dispatch.role failed", out)
                self.assertIn("FAIL dispatch.block: not checked: dispatch.role failed", out)
                self.assertIn("FAIL dispatch.budget: not checked: dispatch.role failed", out)
                self.assertNotIn("FAIL dispatch.input", "\n".join(out))

    def test_two_collisions_name_first_sorted(self):                # RO5, RO6
        e = {"prompt": "p.md", "min_tier": "tier2"}
        self.set_roles({"plan_writer": e, "doc_writer": e, "drafter": e})
        out, _ = self.lines(self.base())
        self.assertEqual(self.only(self.base(), "role"),
                         "FAIL dispatch.role: drafter: a project role may not reuse a framework role id")

    def test_project_role_named_session(self):                      # RO8, Q3
        self.set_roles({"session": {"prompt": "p.md", "min_tier": "tier2"}})
        self.assertEqual(self.only(self.base(), "role"),
                         "FAIL dispatch.role: session: a project role may not reuse the dispatcher id session")

    def test_collision_with_max_children_key(self):                 # MC9, BU21
        e = {"prompt": "p.md", "min_tier": "tier2"}
        self.set_roles({"plan_writer": e}, limits={"max_children": {"plan_writer": 2}},
                       budgets={"plan_writer": {"tokens": 5}})
        out, _ = self.run_gate(self.base())
        self.assertTrue(out.startswith("PASS dispatch.input\n"), out)
        self.assertIn("FAIL dispatch.role: plan_writer: a project role may not reuse a framework role id", out)

    def test_project_role_cannot_dispatch(self):                    # DR6, Q-H4, MC10
        both = {"doc_writer": {"prompt": "p.md", "min_tier": "tier2"}, "doc_two": {"prompt": "p.md", "min_tier": "tier2"}}
        self.set_roles(both)
        for child in ("implementer", "controller", "doc_two"):
            for live in (True, False):
                with self.subTest(child, live=live):
                    d = self.proj(child) if child == "doc_two" else self.base(child)
                    d["dispatcher"] = dict(SESSION, id="doc_writer")
                    d["program_live"] = live
                    out, _ = self.lines(d)
                    self.assertIn("FAIL dispatch.dispatcher: doc_writer is a worker role, and a worker dispatches no "
                                  "agent", out)
                    self.assertNotIn("FAIL dispatch.input", "\n".join(out))

    def test_project_role_takes_worker_row(self):                   # DR3, DR4, DR5
        passing = {(False, "session"), (False, "controller"), (True, "stream_controller"), (True, "controller")}
        for live in (True, False):
            for did in FRAMEWORK_IDS + ["session"]:
                with self.subTest(live=live, dispatcher=did):
                    got = self.only(self.proj(dispatcher=dict(SESSION, id=did), program_live=live), "dispatcher")
                    self.assertEqual(got.startswith("PASS"), (live, did) in passing, got)
        got = self.only(self.proj(program_live=True), "dispatcher")
        self.assertEqual(got, "FAIL dispatch.dispatcher: session may not dispatch doc_writer (program_live true; "
                              "allowed: stream_controller, controller)")

    def test_unknown_dispatcher_id_fails_input(self):               # DR7
        for did in ("boss", "implementor", "Doc_writer"):
            with self.subTest(did):
                out, code = self.run_gate(self.proj(dispatcher=dict(SESSION, id=did)))
                self.assertEqual((out.startswith("FAIL dispatch.input"), code), (True, 1))

    def test_project_role_depth_as_worker(self):                    # DR8
        c = dict(SESSION, id="controller")
        self.assertEqual(self.only(self.proj(dispatcher=dict(c, depth=2)), "depth"), "PASS dispatch.depth")
        self.assertEqual(self.only(self.proj(dispatcher=dict(c, depth=3)), "depth"),
                         "FAIL dispatch.depth: dispatcher depth 3 + 1 + 0 level(s) below doc_writer exceeds max_depth 3")

    def test_role_exact(self):                                      # DR9
        for text in ("doc_writer ", " doc_writer", "Doc_writer", "doc_writer extra"):
            with self.subTest(text):
                d = self.proj()
                d["prompt"] = d["prompt"].replace("## Role\ndoc_writer\n", "## Role\n%s\n" % text, 1)
                self.assertTrue(self.only(d, "role").startswith("FAIL dispatch.role: the first non-empty line"))
        d = self.proj()
        d["prompt"] = d["prompt"].replace("## Role\ndoc_writer\n", "## Role\ndoc_writer\nthen text\n", 1)
        self.assertEqual(self.only(d, "role"), "PASS dispatch.role")

    def test_no_roles_project_role_id_in_role_fails(self):          # DR1
        self.set_config()
        self.assertEqual(self.only(self.proj(), "role"), "FAIL dispatch.role: the first non-empty line of ## Role "
                                                         "must be exactly one role id, not 'doc_writer'")

    def test_constants_unchanged_after_project_dispatch(self):      # DR11, RO14
        before = (dispatch.ROLES, dispatch.CONTROLLER_ROLES, dict(dispatch.MIN_TIERS),
                  {k: dict(v) for k, v in dispatch.DISPATCHERS.items()})
        self.lines(self.proj())
        self.assertEqual(before, (dispatch.ROLES, dispatch.CONTROLLER_ROLES, dispatch.MIN_TIERS, dispatch.DISPATCHERS))
        self.assertNotIn("doc_writer", dispatch.DISPATCHERS[True])

    def test_small_line_ignored_for_project_role(self):             # DR12
        d = self.proj()
        d["prompt"] = d["prompt"].replace("## Brief\nb\n", "## Brief\n%s\n" % (LINE % ("a" * 7, "b" * 7)), 1)
        out, code = self.lines(d)
        self.assertEqual((out, code), (ALL_PASS, 0))

    def test_project_role_top_tier(self):                           # DR13, MT6
        self.set_roles(models=TIERS4, roles={"doc_writer": {"prompt": "p.md", "min_tier": "tier4"}})
        d = self.proj(model="fable")
        self.assertEqual(self.only(d, "top-tier"), "FAIL dispatch.top-tier: tier4 is only for top_tier_roles, not "
                                                   "doc_writer")
        self.assertEqual(self.only(d, "tier"), "PASS dispatch.tier")
        self.set_roles(models=TIERS4, roles={"doc_writer": {"prompt": "p.md", "min_tier": "tier4"}},
                       top_tier_roles=["doc_writer"])
        self.assertEqual(self.only(d, "top-tier"), "PASS dispatch.top-tier")

    def test_project_role_min_tier_below_equal_above(self):         # MT4
        self.set_roles(models=TIERS4)
        self.assertEqual(self.only(self.proj(model="haiku"), "tier"),
                         "FAIL dispatch.tier: tier1 is below the minimum tier2 of doc_writer")
        self.assertEqual(self.only(self.proj(model="sonnet"), "tier"), "PASS dispatch.tier")
        self.assertEqual(self.only(self.proj(model="opus"), "tier"), "PASS dispatch.tier")

    def test_project_role_tier4_unset_never_passes(self):           # MT5
        self.set_roles({"doc_writer": {"prompt": "p.md", "min_tier": "tier4"}}, top_tier_roles=["doc_writer"])
        self.assertEqual(self.only(self.proj(model="opus"), "tier"),
                         "FAIL dispatch.tier: tier3 is below the minimum tier4 of doc_writer")
        # Decision (controller, 2026-11-22), MT5 amended: dispatch.top-tier is PASS whenever the tier is known (3 != 4),
        # even after dispatch.tier failed, as for a framework role (plan :4414 "the order of every existing line is
        # unchanged").
        self.assertEqual(self.only(self.proj(model="opus"), "top-tier"), "PASS dispatch.top-tier")

    def test_project_role_model_and_fork_as_framework(self):        # DR14, DR16
        d = self.proj()
        del d["model"]
        self.assertEqual(self.only(d, "model"), "FAIL dispatch.model: the dispatch call passes no model")
        self.assertEqual(self.only(d, "tier"), "FAIL dispatch.tier: not checked: dispatch.model failed")
        self.assertEqual(self.only(self.proj(subagent_type="fork"), "fork"), "FAIL dispatch.fork: subagent_type is fork")

    def test_project_role_program_line_only_mismatch(self):         # DR15
        d = self.proj(dispatcher=dict(SESSION, id="controller"), program_live=True)
        out, _ = self.lines(d)
        self.assertIn("FAIL dispatch.program: program_live is true in the input, but false in git (0 live program(s))", out)
        self.assertIn("PASS dispatch.stream", out)

    def test_project_role_dispatcher_cap_line_independent(self):    # MC12
        self.set_roles(limits={"max_children": {"doc_writer": 1}})
        d = self.proj(dispatcher=dict(SESSION, id="doc_writer", live_children=1))
        out, _ = self.lines(d)
        self.assertIn("FAIL dispatch.dispatcher: doc_writer is a worker role, and a worker dispatches no agent", out)
        self.assertIn("FAIL dispatch.children: 1 running children + 1 exceeds limits.max_children.doc_writer 1", out)


class MaxChildrenKeyTest(ProjectCase):
    def test_project_role_is_a_max_children_key(self):             # MC3, MC4
        self.set_roles(limits={"max_children": {"doc_writer": 2}})
        out, _ = self.run_gate(self.proj())
        self.assertNotIn("FAIL dispatch.input", out)
        self.set_roles(limits={"max_children": {"implementor": 2}})
        out, code = self.run_gate(self.proj())
        self.assertEqual((out, code), ("FAIL dispatch.input: input: limits.max_children.implementor names no role\n", 1))

    def test_max_children_key_without_role_fails_input(self):      # MC5
        self.set_config(limits={"max_children": {"doc_writer": 2}})
        self.assertEqual(self.run_gate(self.proj()),
                         ("FAIL dispatch.input: input: limits.max_children.doc_writer names no role\n", 1))

    def test_max_children_key_variants_same_on_both(self):         # MC6, V2
        for key, shown in (("Doc_writer", "Doc_writer"), ("doc_writer ", "doc_writer "), ("Ꟁ", "\\ua7c0"),
                           ("\U0001fae8", "\\U0001fae8"), ("﻿doc", "\\ufeffdoc")):
            with self.subTest(repr(key)):
                self.set_roles(limits={"max_children": {key: 1}})
                self.assertEqual(self.run_gate(self.proj()),
                                 ("FAIL dispatch.input: input: limits.max_children.%s names no role\n" % shown, 1))

    def test_max_children_first_bad_key_named(self):               # MC7
        self.set_roles(limits={"max_children": {"doc_writer": 1, "implementor": 1, "zzz": 1}})
        self.assertEqual(self.run_gate(self.proj()),
                         ("FAIL dispatch.input: input: limits.max_children.implementor names no role\n", 1))

    def test_override_max_children_project_key(self):              # MC11, CF12: the real override route
        dec = "DEC-20261111-abcd"
        write_record(self.root, ".strict-delivery/state/decisions/%s.yml" % dec,
                     {"id": dec, "status": "answered", "class": "profile-override", "effect": "lasting",
                      "question": "q", "answer": "a", "topics": [], "applies_to": []})
        ovr = {"limits.max_children.doc_writer": {"value": 2, "decision": dec}}
        self.set_roles(overrides=ovr)                               # with the roles entry: the override reaches the gate
        self.assertEqual(config.load(self.root)["limits"]["max_children"], {"doc_writer": 2})
        self.assertEqual(self.lines(self.proj()), (ALL_PASS, 0))
        self.set_config(overrides=ovr)                              # without it: the key names no role
        self.assertEqual(self.run_gate(self.proj()),
                         ("FAIL dispatch.input: input: limits.max_children.doc_writer names no role\n", 1))

    def test_max_children_key_nul_newline_empty_injected(self):    # MC6, MC8, MC13: shapes the YAML writer cannot carry
        base = config.load(self.root)
        for key, shown in (("doc\x00writer", "doc\\x00writer"), ("doc_writer\n", "doc_writer\\n"),
                           ("\ndoc_writer", "\\ndoc_writer"), ("doc_writer\x00", "doc_writer\\x00")):
            with self.subTest(repr(key)):
                cfg = dict(base, limits={"max_children": {key: 1}})
                with mock.patch.object(config, "load", return_value=cfg):
                    self.assertEqual(self.run_gate(self.proj()),
                                     ("FAIL dispatch.input: input: limits.max_children.%s names no role\n" % shown, 1))
        with mock.patch.object(config, "load", return_value=dict(base, limits={"max_children": {}})):
            self.assertEqual(self.lines(self.proj()), (ALL_PASS, 0))        # MC8
        cfg = dict(base, limits={"max_children": {"doc_writer": 1}})          # MC13: a worker's cap is accepted, never read
        with mock.patch.object(config, "load", return_value=cfg):
            self.assertEqual(self.lines(self.proj()), (ALL_PASS, 0))

    def test_max_children_builtin_keys(self):                      # MC1, MC2
        for key in FRAMEWORK_IDS + ["session"]:
            with self.subTest(key):
                self.set_config(limits={"max_children": {key: 2}})
                self.assertNotIn("FAIL dispatch.input", self.run_gate(self.base())[0])


class ProjectPromptTest(ProjectCase):
    def blk(self, text):
        return self.proj(body=text)

    def test_prompt_path_not_from_prompts_dir(self):                # PP23
        with open(os.path.join(self.prompts, "doc_writer.md"), "w", encoding="utf-8", newline="") as f:
            f.write(block("doc_writer"))
        os.remove(os.path.join(self.root, "p.md"))
        self.assertEqual(self.only(self.proj(), "block"),
                         "FAIL dispatch.block: strict block file p.md cannot be read (No such file or directory)")

    def test_project_prompt_missing_fails_block(self):              # PP5, PP14
        for rel in ("p.md", "nodir/p.md"):
            with self.subTest(rel):
                self.set_roles({"doc_writer": {"prompt": rel, "min_tier": "tier2"}} )
                if rel == "p.md":
                    os.remove(os.path.join(self.root, "p.md"))
                self.assertEqual(self.only(self.proj(), "block"),
                                 "FAIL dispatch.block: strict block file %s cannot be read (No such file or directory)"
                                 % rel)

    def test_project_block_byte_variants(self):                     # PP4, PP25
        good = block("doc_writer")
        for name, body in (("one char", good.replace("body", "bodx")), ("trailing space", good + " "),
                           ("crlf", good.replace("\n", "\r\n")), ("bom", "﻿" + good),
                           ("framework block", block("implementer")), ("extra newline", good + "\n"),
                           ("empty", "")):
            with self.subTest(name):
                self.assertEqual(self.only(self.blk(body), "block"), BLOCK_ERR)
        self.write_prompt("p.md", "")
        self.assertEqual(self.only(self.blk(""), "block"), "PASS dispatch.block")
        self.write_prompt("p.md", good.rstrip("\n"))
        self.assertEqual(self.only(self.blk(good), "block"), BLOCK_ERR)
        self.write_prompt("p.md", good.replace("\n", "\r\n"))
        self.assertEqual(self.only(self.blk(good.replace("\n", "\r\n")), "block"), "PASS dispatch.block")
        self.assertEqual(self.only(self.blk(good), "block"), BLOCK_ERR)

    def test_project_prompt_symlink_fails_block(self):             # PP6-PP9
        os.rename(os.path.join(self.root, "p.md"), os.path.join(self.root, "real.md"))
        outside = os.path.join(self.tmp, "x.md")
        with open(outside, "w", encoding="utf-8", newline="") as f:
            f.write(block("doc_writer"))
        p = os.path.join(self.root, "p.md")
        for name, target in (("inside", "real.md"), ("outside", outside), ("dangling", "nothing.md"), ("loop", "p.md")):
            with self.subTest(name):
                os.symlink(target, p)
                try:
                    self.assertEqual(self.only(self.proj(), "block"),
                                     "FAIL dispatch.block: strict block file p.md is a symlink, never followed")
                finally:
                    os.unlink(p)

    def test_project_prompt_directory_fails_block(self):           # PP10
        os.remove(os.path.join(self.root, "p.md"))
        os.mkdir(os.path.join(self.root, "p.md"))
        self.assertEqual(self.only(self.proj(), "block"),
                         "FAIL dispatch.block: strict block file p.md is not a regular file")

    def test_project_prompt_fifo_fails_block_without_hanging(self):  # PP11, V4
        os.remove(os.path.join(self.root, "p.md"))
        os.mkfifo(os.path.join(self.root, "p.md"))
        path = self.write_input(self.proj())
        env = dict(os.environ, PYTHONPATH=REPO)
        p = subprocess.run([sys.executable, "-m", "gates", "check", "dispatch", "--root", self.root, "--input", path,
                            "--prompts", self.prompts], cwd=REPO, env=env, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, timeout=30)
        self.assertIn("FAIL dispatch.block: strict block file p.md is not a regular file",
                      p.stdout.decode("utf-8").splitlines())

    def test_project_prompt_socket_fails_block(self):              # PP12
        import socket
        os.remove(os.path.join(self.root, "p.md"))
        s = socket.socket(socket.AF_UNIX)
        self.addCleanup(s.close)
        try:
            s.bind(os.path.join(self.root, "p.md"))
        except OSError as e:
            self.skipTest("cannot bind a socket here: %s" % e)
        self.assertEqual(self.only(self.proj(), "block"),
                         "FAIL dispatch.block: strict block file p.md is not a regular file")

    def test_project_prompt_parent_component_refused(self):        # PP13, PP14
        os.mkdir(os.path.join(self.root, "realdir"))
        self.write_prompt("realdir/doc.md", block("doc_writer"))
        os.symlink("realdir", os.path.join(self.root, "playbooks"))
        self.set_roles({"doc_writer": {"prompt": "playbooks/doc.md", "min_tier": "tier2"}})
        self.assertEqual(self.only(self.proj(), "block"), "FAIL dispatch.block: strict block file playbooks/doc.md: "
                                                          "the component 'playbooks' is a symlink or not a directory")
        self.set_roles({"doc_writer": {"prompt": "p.md/b.md", "min_tier": "tier2"}})
        self.assertEqual(self.only(self.proj(), "block"), "FAIL dispatch.block: strict block file p.md/b.md: "
                                                          "the component 'p.md' is a symlink or not a directory")

    def test_project_prompt_unreadable(self):                      # PP15
        path = os.path.join(self.root, "p.md")
        os.chmod(path, 0)
        self.addCleanup(os.chmod, path, 0o644)
        try:
            open(path, "rb").close()
        except OSError:
            pass
        else:
            self.skipTest("the process reads a mode 0 file")
        self.assertEqual(self.only(self.proj(), "block"),
                         "FAIL dispatch.block: strict block file p.md cannot be read (Permission denied)")

    def test_project_prompt_not_utf8(self):                        # PP16
        self.write_prompt("p.md", b"\xff\xfe")
        self.assertEqual(self.only(self.proj(), "block"), "FAIL dispatch.block: strict block file p.md is not valid UTF-8")

    def test_project_prompt_huge_file_not_read(self):              # PP17
        path = self.write_prompt("p.md", b"")
        os.truncate(path, 2 * 1024 ** 3)
        with mock.patch.object(os, "fdopen", side_effect=AssertionError("read")):
            self.assertEqual(self.only(self.proj(), "block"), BLOCK_ERR)

    def test_project_prompt_swap_to_symlink_refused(self):         # PP18, V4
        os.rename(os.path.join(self.root, "p.md"), os.path.join(self.root, "real.md"))
        os.symlink("real.md", os.path.join(self.root, "p.md"))
        real = os.lstat
        regular = os.lstat(os.path.join(self.root, "real.md"))

        def lie(path, *a, **k):
            return regular if os.path.basename(path) == "p.md" else real(path, *a, **k)
        with mock.patch.object(os, "lstat", side_effect=lie):
            got = self.only(self.proj(), "block")
        self.assertTrue(got.startswith("FAIL dispatch.block: strict block file p.md cannot be read ("), got)

    def test_project_prompt_read_from_working_tree(self):          # PP19
        self.write_prompt("p.md", block("doc_writer") + "edited")
        self.assertEqual(self.only(self.proj(), "block"), BLOCK_ERR)
        self.write_prompt("p.md", "other")
        self.assertEqual(self.only(self.blk("other"), "block"), "PASS dispatch.block")
        git(self.root, "checkout", "--", "p.md")
        self.assertEqual(self.only(self.proj(), "block"), "PASS dispatch.block")

    def test_project_prompt_root_through_symlink(self):            # PP20
        link = os.path.join(self.tmp, "rootlink")
        os.symlink(self.root, link)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
            gates_main.main(["check", "dispatch", "--root", link, "--input", self.write_input(self.proj()),
                             "--prompts", self.prompts])
        self.assertIn("PASS dispatch.block", buf.getvalue().splitlines())

    def test_project_prompt_name_read_as_given(self):              # PP26
        self.write_prompt("é.md", block("doc_writer"))
        self.set_roles({"doc_writer": {"prompt": "é.md", "min_tier": "tier2"}})
        self.assertEqual(self.only(self.proj(), "block"), "PASS dispatch.block")

    def test_project_prompt_name_too_long(self):                   # PP27
        self.set_roles({"doc_writer": {"prompt": "a" * 300 + ".md", "min_tier": "tier2"}})
        self.assertEqual(self.only(self.proj(), "block"), "FAIL dispatch.block: strict block file %s.md cannot be read "
                                                          "(File name too long)" % ("a" * 300))

    def test_two_project_roles_one_prompt_file(self):              # PP24
        e = {"prompt": "p.md", "min_tier": "tier2"}
        self.set_roles({"a": e, "b": e})
        for r in ("a", "b"):
            self.assertEqual(self.only(self.proj(r, body=block("doc_writer")), "block"), "PASS dispatch.block")

    def test_prompt_path_refused_values_fail_block(self):          # PP21 through the gate (injected cfg)
        base = config.load(self.root)
        for bad in ("../p.md", "/etc/passwd", "a//b.md", "./p.md", "p.txt", "p.md "):
            with self.subTest(bad):
                cfg = dict(base, roles={"doc_writer": {"prompt": bad, "min_tier": "tier2"}})
                with mock.patch.object(config, "load", return_value=cfg):
                    got = self.only(self.proj(), "block")
                self.assertEqual(got, "FAIL dispatch.block: roles.doc_writer.prompt is not a normalised "
                                      "repository-relative .md path")


class BudgetTest(ProjectCase):
    def caps(self, role="implementer", **c):
        self.set_roles(budgets={role: c})

    def test_budget_cap_exceeded(self):                            # BU3
        self.caps(tokens=50000)
        for n, want in ((49999, "PASS dispatch.budget"), (50000, "PASS dispatch.budget"),
                        (50001, "FAIL dispatch.budget: tokens 50001 exceeds the cap 50000")):
            with self.subTest(n):
                d = self.base()
                d["prompt"] = with_budget(d["prompt"], n, 10)
                self.assertEqual(self.only(d, "budget"), want)

    def test_budget_minutes_boundary(self):                        # BU4
        self.caps(minutes=30)
        for n, want in ((29, "PASS dispatch.budget"), (30, "PASS dispatch.budget"),
                        (31, "FAIL dispatch.budget: minutes 31 exceeds the cap 30")):
            with self.subTest(n):
                d = self.base()
                d["prompt"] = with_budget(d["prompt"], 5, n)
                self.assertEqual(self.only(d, "budget"), want)

    def test_budget_both_exceed_one_line(self):                    # BU5, BU6, BU7
        self.caps(tokens=50000, minutes=30)
        for t, m, want in ((60000, 40, "FAIL dispatch.budget: tokens 60000 exceeds the cap 50000; minutes 40 exceeds "
                                       "the cap 30"),
                           (60000, 30, "FAIL dispatch.budget: tokens 60000 exceeds the cap 50000"),
                           (50000, 40, "FAIL dispatch.budget: minutes 40 exceeds the cap 30")):
            d = self.base()
            d["prompt"] = with_budget(d["prompt"], t, m)
            self.assertEqual(self.only(d, "budget"), want)
        self.caps(tokens=5)
        d = self.base()
        d["prompt"] = with_budget(d["prompt"], 5, "9" * 500)
        self.assertEqual(self.only(d, "budget"), "PASS dispatch.budget")

    def test_budget_cap_absent_and_other_role(self):               # BU1, BU2, BU10
        d = self.base()
        d["prompt"] = with_budget(d["prompt"], 99999999, 99999999)
        self.assertEqual(self.only(d, "budget"), "PASS dispatch.budget")
        self.caps("controller", tokens=1, minutes=1)
        self.assertEqual(self.only(d, "budget"), "PASS dispatch.budget")
        self.caps("controller", tokens=1)
        d["dispatcher"] = dict(SESSION, id="controller")
        self.assertEqual(self.only(d, "budget"), "PASS dispatch.budget")

    def test_budget_project_role_cap(self):                        # BU9
        self.caps("doc_writer", tokens=5)
        d = self.proj()
        self.assertEqual(self.only(d, "budget"), "FAIL dispatch.budget: tokens 1000 exceeds the cap 5")

    def test_budget_key_naming_no_role(self):                      # BU19, Q5
        for key in ("nosuch", "session"):
            with self.subTest(key):
                self.caps(key, tokens=5)
                self.assertEqual(self.run_gate(self.base()),
                                 ("FAIL dispatch.input: input: budgets.%s names no role\n" % key, 1))
        self.caps("doc_writer", tokens=5)
        self.assertNotIn("FAIL dispatch.input", self.run_gate(self.base())[0])
        self.set_config(budgets={"doc_writer": {"tokens": 5}})
        self.assertEqual(self.run_gate(self.base()), ("FAIL dispatch.input: input: budgets.doc_writer names no role\n", 1))

    def test_budget_line_not_checked(self):                        # BU11-BU13
        self.caps(tokens=5)
        d = self.base()
        d["prompt"] = d["prompt"].replace(BUDGET_HEAD, "## Budget: tokens=0 minutes=10")
        self.assertEqual(self.only(d, "budget"), "FAIL dispatch.budget: not checked: dispatch.grammar failed")
        d = self.base()
        d["prompt"] = d["prompt"].replace("## Role\nimplementer", "## Role\nnobody")
        self.assertEqual(self.only(d, "budget"), "FAIL dispatch.budget: not checked: dispatch.role failed")

    def test_budget_numbers_come_from_the_heading(self):           # BU14, BU12 duplicate
        self.caps(tokens=50000)
        d = self.base(prompt=prompt("implementer", brief="tokens=99999999 minutes=99999999 and Budget: tokens=99999999"))
        self.assertEqual(self.only(d, "budget"), "PASS dispatch.budget")
        d = self.base()
        d["prompt"] = d["prompt"].replace("## Model\n", BUDGET_HEAD.replace("1000", "99999") + "\n\n## Model\n", 1)
        self.assertEqual(self.only(d, "budget"), "PASS dispatch.budget")           # judges the first heading

    def test_budget_huge_numbers_same_on_both(self):               # BU15-BU18, V1
        for lim in INT_LIMITS:
            with int_limit(lim):
                self.caps(tokens=5)
                for digits, want in ((599, "tokens %s exceeds the cap 5" % ("9" * 599)),
                                     (600, "tokens %s exceeds the cap 5" % ("9" * 600)),
                                     (601, "tokens (a number of 601 digits) exceeds the cap 5"),
                                     (4300, "tokens (a number of 4300 digits) exceeds the cap 5"),
                                     (4301, "tokens (a number of 4301 digits) exceeds the cap 5")):
                    with self.subTest(limit=lim, digits=digits):
                        d = self.base()
                        d["prompt"] = with_budget(d["prompt"], "9" * digits, 10)
                        self.assertEqual(self.only(d, "budget"), "FAIL dispatch.budget: " + want)
                with self.subTest(limit=lim, case="no cap"):
                    self.set_roles()
                    d = self.base()
                    d["prompt"] = with_budget(d["prompt"], "9" * 4301, 10)
                    self.assertEqual(self.only(d, "budget"), "PASS dispatch.budget")
                with self.subTest(limit=lim, case="cap of 600 digits"):
                    self.caps(tokens=int("9" * 600))
                    d = self.base()
                    d["prompt"] = with_budget(d["prompt"], "9" * 600, 10)
                    self.assertEqual(self.only(d, "budget"), "PASS dispatch.budget")

    def test_budget_json_line(self):                               # BU22
        self.caps(tokens=50000)
        d = self.base()
        d["prompt"] = with_budget(d["prompt"], 50001, 10)
        got = self.run_json(d)
        self.assertFalse(got["ok"])
        self.assertIn({"status": "FAIL", "id": "dispatch.budget", "reason": "tokens 50001 exceeds the cap 50000"},
                      got["lines"])

    def test_budget_and_size_exit_codes_and_order(self):           # LN3-LN5
        self.set_roles(budgets={"implementer": {"tokens": 5}}, dispatch={"max_prompt_chars": 5})
        out, code = self.lines(self.base())
        ids = [ln.split(":")[0] for ln in out]
        self.assertEqual(ids[13:17], ["PASS dispatch.block", "FAIL dispatch.budget", "FAIL dispatch.size",
                                      "PASS dispatch.claims"])
        self.assertEqual(code, 1)
        self.set_roles(budgets={"implementer": {"tokens": 5000}}, dispatch={"max_prompt_chars": 100000})
        self.assertEqual(self.lines(self.base()), (ALL_PASS, 0))


class SizeTest(ProjectCase):
    def sized(self, role, total, unit="x"):
        """A prompt of exactly ``total`` characters whose Brief holds ``unit`` copies and then ``x`` padding."""
        d = self.base(role) if role in dispatch.ROLES else self.proj(role)
        empty = len(prompt(role, brief="", model=d["model"]))
        pad = unit * 50
        pad += "x" * (total - empty - len(pad))
        d["prompt"] = prompt(role, brief=pad, model=d["model"])
        self.assertEqual(len(d["prompt"]), total)
        return d

    def test_prompt_size_boundary(self):                           # SZ2, SZ11
        self.set_config(dispatch={"max_prompt_chars": 5000})
        for n, want in ((4999, "PASS dispatch.size"), (5000, "PASS dispatch.size"),
                        (5001, "FAIL dispatch.size: the prompt holds 5001 characters, more than "
                               "dispatch.max_prompt_chars 5000")):
            with self.subTest(n):
                self.assertEqual(self.only(self.sized("implementer", n), "size"), want)

    def test_prompt_size_counts_characters(self):                  # SZ3
        self.set_config(dispatch={"max_prompt_chars": 5000})
        for name, unit in (("e-acute", "é"), ("emoji", "\U0001f600"), ("combining", "é"),
                           ("surrogate", "\ud800"), ("crlf", "\r\n"), ("bom", "﻿"), ("nul", "\x00"), ("ff", "\f")):
            for n, want in ((5000, "PASS dispatch.size"), (5001, "FAIL dispatch.size: the prompt holds 5001 characters, "
                                                                  "more than dispatch.max_prompt_chars 5000")):
                with self.subTest(name, n=n):
                    self.assertEqual(self.only(self.sized("implementer", n, unit), "size"), want)

    def test_prompt_size_whole_prompt(self):                       # SZ4
        self.set_config(dispatch={"max_prompt_chars": 100})
        d = self.base()
        n = len(d["prompt"])
        self.assertEqual(self.only(d, "size"), "FAIL dispatch.size: the prompt holds %d characters, more than "
                                               "dispatch.max_prompt_chars 100" % n)
        self.set_config(dispatch={"max_prompt_chars": n})
        self.assertEqual(self.only(d, "size"), "PASS dispatch.size")
        self.assertEqual(self.only(dict(d, prompt=d["prompt"].replace("\n", "\r\n")), "size")[:9], "FAIL disp")

    def test_size_cap_one_huge_and_every_role(self):               # SZ5, SZ6, SZ8
        self.set_roles(dispatch={"max_prompt_chars": 1})
        for d in (self.base(), self.base("controller"), self.proj()):
            self.assertTrue(self.only(d, "size").startswith("FAIL dispatch.size: the prompt holds "), d)
        out, _ = self.lines(self.base(prompt=""))
        self.assertIn("PASS dispatch.size", out)
        self.assertTrue(any(ln.startswith("FAIL dispatch.grammar") for ln in out))
        self.set_roles(dispatch={"max_prompt_chars": int("9" * 599)})
        self.assertEqual(self.only(self.base(), "size"), "PASS dispatch.size")

    def test_size_independent_of_grammar(self):                    # SZ7
        self.set_config(dispatch={"max_prompt_chars": 5})
        out, _ = self.lines(self.base(prompt="x" * 10))
        self.assertIn("FAIL dispatch.size: the prompt holds 10 characters, more than dispatch.max_prompt_chars 5", out)
        self.assertTrue(any(ln.startswith("FAIL dispatch.grammar") for ln in out))

    def test_size_absent_and_long(self):                           # SZ1, SZ10
        d = self.base()
        d["prompt"] = prompt("implementer", brief="x" * 5000000)
        self.assertEqual(self.only(d, "size"), "PASS dispatch.size")

    def test_size_json_line(self):                                 # SZ12
        self.set_config(dispatch={"max_prompt_chars": 5})
        n = len(self.base()["prompt"])
        got = self.run_json(self.base())
        self.assertIn({"status": "FAIL", "id": "dispatch.size",
                       "reason": "the prompt holds %d characters, more than dispatch.max_prompt_chars 5" % n},
                      got["lines"])


class InputShapeTest(ProjectCase):
    def injected(self, **extra):
        cfg = dict(config.load(self.root), **extra)
        with mock.patch.object(config, "load", return_value=cfg):
            return self.run_gate(self.proj())

    def test_new_input_failures_are_one_line(self):                # LN6, BU20, SZ9, RO10
        shapes = [("budgets", {"implementer": {"tokens": v}}) for v in (0, -1, True, "5", 2.5, None, [5], 10 ** 600)]
        shapes += [("budgets", v) for v in (None, 5, [], {"implementer": 5}, {"implementer": {"other": 1}})]
        shapes += [("dispatch", v) for v in (None, 5, [], {"other": 1}, {"max_prompt_chars": 0},
                                             {"max_prompt_chars": True}, {"max_prompt_chars": "5"},
                                             {"max_prompt_chars": 2.5}, {"max_prompt_chars": 10 ** 600})]
        shapes += [("roles", v) for v in (None, 5, True, "x", [], {1: {}}, {"X": {}}, {"a b": {}}, {"x\n": {}})]
        for key, val in shapes:
            with self.subTest(key, val=repr(val)[:30]):
                out, code = self.injected(**{key: val})
                self.assertEqual(code, 1)
                self.assertEqual(len(out.splitlines()), 1, out)
                self.assertTrue(out.startswith("FAIL dispatch.input: "), out)

    def test_budget_empty_entry_is_no_cap(self):                   # BU8: an empty entry reaches only by injection
        base = config.load(self.root)
        for budgets in ({"implementer": {}}, {"doc_writer": {}}, {}):
            with self.subTest(repr(budgets)):
                with mock.patch.object(config, "load", return_value=dict(base, budgets=budgets)):
                    self.assertEqual(self.lines(self.base()), (ALL_PASS, 0))
                    self.assertEqual(self.lines(self.proj()), (ALL_PASS, 0))

    def test_bad_config_values_are_one_input_line(self):           # CF15
        for key, val in (("roles", 5), ("roles", {"x": {"prompt": "../p.md", "min_tier": "tier2"}}),
                         ("budgets", {"controller": {"tokens": 0}}), ("dispatch", {"max_prompt_chars": 0})):
            with self.subTest(key):
                self.set_config(**{key: val})
                out, code = self.run_gate(self.base())
                self.assertEqual(code, 1)
                self.assertEqual(len(out.splitlines()), 1)
                self.assertTrue(out.startswith("FAIL dispatch.input: .strict-delivery/config.yml: "), out)

    def test_no_roles_no_budgets_no_dispatch_output_unchanged(self):  # CF1, LN2
        self.set_config()
        self.assertEqual(self.lines(self.base()), (ALL_PASS, 0))

    def test_long_role_id_and_path(self):                          # CF5
        rid = "r" * 5000
        self.write_prompt("q.md", block(rid))
        self.set_roles({rid: {"prompt": "q.md", "min_tier": "tier2"}})
        self.assertEqual(self.lines(self.proj(rid, body=block(rid))), (ALL_PASS, 0))

    def test_exception_groups_not_swallowed(self):                 # V3
        if not hasattr(builtins, "BaseExceptionGroup"):
            self.skipTest("BaseExceptionGroup is absent on this interpreter")
        with mock.patch.object(config, "load", side_effect=builtins.ExceptionGroup("x", [ValueError()])):
            out, code = self.run_gate(self.proj())
        self.assertEqual(code, 1)
        self.assertTrue(out.startswith("FAIL dispatch.input: ExceptionGroup"), out)
        with mock.patch.object(config, "load", side_effect=builtins.BaseExceptionGroup("x", [KeyboardInterrupt()])):
            with self.assertRaises(builtins.BaseExceptionGroup):
                self.run_gate(self.proj())


if __name__ == "__main__":
    unittest.main()
