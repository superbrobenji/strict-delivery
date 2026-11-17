"""Tests of ``python3 -m gates check dispatch`` (plan Task 2c.3; rows I1-I14, Q1-Q3, M1-M8, S5, S13-S15, B8, V1-V3 of
task-2c.3-domain.md) through ``gates.__main__.main`` on fixture repositories and fixture prompt directories in temp
directories. Prompt files are never read from this repository's own prompts (stream rules); expected lines are written
out literally."""
import builtins
import contextlib
import io
import json
import os
import unittest
from unittest import mock

from gates import __main__ as gates_main
from gates.lib import claims as claims_lib, config, dispatch, migrations
from tests.helpers import (INT_LIMITS, GitIsolatedTestCase, commit_all, git, int_limit, make_repo, minimal_config,
                           write_record)

ENV_D, ENV_C = "CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH", "CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS"
ALL_PASS = ["PASS dispatch.input", "PASS dispatch.fork", "PASS dispatch.grammar", "PASS dispatch.role",
            "PASS dispatch.dispatcher", "PASS dispatch.depth", "PASS dispatch.concurrency", "PASS dispatch.children",
            "PASS dispatch.model", "PASS dispatch.tier", "PASS dispatch.top-tier", "PASS dispatch.block",
            "PASS dispatch.claims", "PASS dispatch.decisions"]
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
                                           "PASS dispatch.role", "PASS dispatch.dispatcher", "PASS dispatch.depth",
                                           "PASS dispatch.concurrency", "PASS dispatch.children", "PASS dispatch.model",
                                           "FAIL dispatch.tier: top_tier_fallback '%s' names a tier that is unset or "
                                           "not tier1-tier4" % shown,
                                           "FAIL dispatch.top-tier: not checked: dispatch.tier failed",
                                           "PASS dispatch.block", "PASS dispatch.claims", "PASS dispatch.decisions"])
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
                    self.assertEqual(len(out.splitlines()), 14, out)
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
                              "PASS dispatch.dispatcher", "FAIL dispatch.depth: dispatcher depth %s + 1 + 0 "
                              "level(s) below implementer exceeds max_depth 3" % ("9" * 600), "PASS dispatch.concurrency",
                              "PASS dispatch.children", "PASS dispatch.model", "PASS dispatch.tier",
                              "PASS dispatch.top-tier", "PASS dispatch.block", "PASS dispatch.claims",
                              "PASS dispatch.decisions"],
                    "live_children": ALL_PASS,
                    "live_total": ["PASS dispatch.input", "PASS dispatch.fork", "PASS dispatch.grammar",
                                   "PASS dispatch.role", "PASS dispatch.dispatcher", "PASS dispatch.depth",
                                   "FAIL dispatch.concurrency: %s running + 1 exceeds max_concurrent 20" % ("9" * 600),
                                   "PASS dispatch.children", "PASS dispatch.model", "PASS dispatch.tier",
                                   "PASS dispatch.top-tier", "PASS dispatch.block", "PASS dispatch.claims",
                                   "PASS dispatch.decisions"]}[field])
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


if __name__ == "__main__":
    unittest.main()
