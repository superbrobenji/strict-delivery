"""Tests of Task 4d.1: ``gates/tools/init.py`` (questions, plan, apply). Expected values are written by hand."""
import ast
import contextlib
import copy
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import unittest
from unittest import mock

from gates.lib import config, managed, plugin, yamlsub
from gates.lib.result import GateError
from gates.tools import githooks, init
from tests import helpers
from tests.helpers import GitIsolatedTestCase, git

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_D = "CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH"
ENV_C = "CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS"
DEL = object()
SETTINGS_ORIGINAL = '{"env": {"CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH": "2"}}\n'


def answers(**over):
    base = {"schema": "init-answers/1", "profile": "standard",
            "models": {"tiers": {"tier1": "haiku", "tier2": "sonnet", "tier3": "opus"}},
            "commands": {"test": "python3 -m unittest", "test_one": "python3 -m unittest {id}", "lint": "ruff check .",
                         "build": "make"},
            "git_hooks": True, "ci": False, "merge_mode": "host", "subagents": {"depth": 5, "concurrent": 30},
            "protect_base": False, "base_branch": "main"}
    for k, v in over.items():
        if v is DEL:
            base.pop(k, None)
        else:
            base[k] = v
    return base


def snapshot(root):
    out = []
    for d, dirs, files in os.walk(root):
        dirs.sort()
        for n in sorted(dirs + files):
            p = os.path.join(d, n)
            st = os.lstat(p)
            if stat.S_ISLNK(st.st_mode):
                out.append((p, "link", os.readlink(p)))
            elif stat.S_ISREG(st.st_mode):
                with open(p, "rb") as fh:
                    out.append((p, st.st_mode, fh.read()))
            else:
                out.append((p, st.st_mode, None))
    return out


class Base(GitIsolatedTestCase):
    def setUp(self):
        super().setUp()
        self.root = os.path.join(self.tmp, "repo")
        os.mkdir(self.root)
        git(self.root, "init", "-q", "-b", "main")
        git(self.root, "config", "user.email", "f@example.invalid")
        git(self.root, "config", "user.name", "F")
        git(self.root, "config", "commit.gpgsign", "false")
        self.write("README.md", "hello\n")
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", "first")
        self.ans = os.path.join(self.tmp, "answers.yml")

    def write(self, rel, text, mode="w"):
        p = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, mode, **({} if "b" in mode else {"encoding": "utf-8"})) as fh:
            fh.write(text)
        return p

    def read(self, rel):
        with open(os.path.join(self.root, rel), encoding="utf-8") as fh:
            return fh.read()

    def put_answers(self, a=None, **over):
        data = a if a is not None else answers(**over)
        with open(self.ans, "w", encoding="utf-8") as fh:
            fh.write(yamlsub.emit(data))
        return self.ans

    def run_init(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = init.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def cmd(self, sub, root=None, **over):
        self.put_answers(**over)
        return self.run_init(sub, "--root", root or self.root, "--answers", self.ans)

    def fw_with_version(self, version):
        fw = os.path.join(self.tmp, "fw")
        os.makedirs(os.path.join(fw, ".claude-plugin"), exist_ok=True)
        with open(os.path.join(fw, ".claude-plugin", "plugin.json"), "w", encoding="utf-8") as fh:
            json.dump({"name": "x", "version": version, "repository": "https://github.com/o/r"}, fh)
        return fw


class TestStep1(Base):
    def test_questions_lists_detect_proposals_in_order(self):  # QS2
        self.write("package.json", '{"scripts": {"test": "jest", "lint": "eslint ."}}')
        self.write("Makefile", "build:\n\techo b\n")
        q = init.questions(self.root)
        from gates.lib import detect
        want = [{"slot": p.slot, "command": p.command, "source": p.source} for p in detect.detect(self.root).proposals]
        self.assertTrue(want)
        self.assertEqual(q["proposals"], want)
        self.assertEqual(set(q), {"proposals", "problems", "ask_test_one", "profiles", "default_profile", "models",
                                  "defaults", "subagents", "superpowers_docs", "initialised"})

    def test_questions_never_proposes_test_one(self):  # QS3
        self.write("package.json", '{"scripts": {"test:one": "x", "test": "jest"}}')
        q = init.questions(self.root)
        self.assertIs(q["ask_test_one"], True)
        self.assertTrue(all(p["slot"] != "test_one" for p in q["proposals"]))

    def test_extras_defaults(self):  # QS8
        q = init.questions(self.root)
        self.assertEqual(q["defaults"], {"git_hooks": True, "ci": False, "merge_mode": "host", "protect_base": True})
        self.assertEqual(q["default_profile"], "standard")
        self.assertEqual(q["models"], {"tier1": "haiku", "tier2": "sonnet", "tier3": "opus"})
        self.assertEqual(q["superpowers_docs"], [])
        self.assertIs(q["initialised"], False)
        self.assertEqual(q["subagents"], {"current": None})
        self.assertEqual([p["name"] for p in q["profiles"]], ["light", "standard", "strict"])

    def test_questions_writes_nothing_and_json(self):  # QS1, QS17
        before = snapshot(self.root)
        code, out, _ = self.run_init("questions", "--root", self.root, "--json")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["default_profile"], "standard")
        self.assertTrue(out.endswith("}\n"))
        code, out, _ = self.run_init("questions", "--root", self.root)
        self.assertEqual(code, 0)
        self.assertIn("default_profile: ", out)
        self.assertEqual(snapshot(self.root), before)

    def test_plan_writes_nothing(self):  # PO1, PL2
        before = snapshot(self.root)
        code, out, _ = self.cmd("plan")
        self.assertEqual(code, 0)
        self.assertEqual(snapshot(self.root), before)
        self.assertIn("--- a/.strict-delivery/config.yml", out)
        self.assertIn("+++ b/CLAUDE.md", out)
        self.assertIn("mkdir .strict-delivery/state/decisions/", out)

    def test_apply_writes_config_blocks_and_hooks(self):  # AP8, HK1, BK1
        code, out, _ = self.cmd("apply", merge_mode="controller")
        self.assertEqual(code, 0, out)
        self.assertEqual(config.load(self.root)["merge"]["mode"], "controller")
        block = managed.find_block(self.read("CLAUDE.md"), managed.HTML)
        self.assertEqual(block.kind, "claude-block")
        self.assertEqual(managed.find_block(self.read(".gitignore"), managed.HASH).kind, "gitignore-block")
        self.assertTrue(all(l.status == "PASS" for l in githooks.status(self.root, githooks.framework_dir()).lines))
        for name in githooks.NAMES:
            self.assertEqual(os.stat(os.path.join(self.root, ".git", "hooks", name)).st_mode & 0o777, 0o755)
        self.assertIn("?? CLAUDE.md", out)
        self.assertIn("?? .strict-delivery/config.yml", out)
        self.assertNotIn(".strict-delivery/state", out)

    def test_conflict_writes_nothing(self):  # CI9, AP2, PL3, PL4
        self.write(".github/workflows/strict-delivery.yml", "name: mine\n")
        before = snapshot(self.root)
        for sub in ("plan", "apply"):
            code, out, _ = self.cmd(sub, ci=True)
            self.assertEqual(code, 1)
            self.assertIn(".github/workflows/strict-delivery.yml: exists and is not framework-managed", out)
            self.assertEqual(snapshot(self.root), before)

    def test_settings_created_with_env(self):  # ST1
        self.cmd("apply")
        self.assertEqual(self.read(".claude/settings.json"),
                         '{\n  "env": {\n    "CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS": "30",\n'
                         '    "CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH": "5"\n  }\n}\n')
        self.assertEqual(json.loads(self.read(".claude/settings.json")), {"env": {ENV_D: "5", ENV_C: "30"}})

    def test_existing_settings_never_rewritten(self):  # ST5
        self.write(".claude/settings.json", SETTINGS_ORIGINAL)
        before = snapshot(self.root)
        code, out, _ = self.cmd("apply")
        self.assertEqual(code, 1)
        self.assertIn('.claude/settings.json: set "env"."%s" to "5"' % ENV_D, out)
        self.assertIn('.claude/settings.json: add "env"."%s": "30"' % ENV_C, out)
        self.assertEqual(self.read(".claude/settings.json"), SETTINGS_ORIGINAL)
        self.assertEqual(snapshot(self.root), before)

    def test_second_apply_is_noop(self):  # IN3, PO6, ID1
        self.assertEqual(self.cmd("apply")[0], 0)
        before = snapshot(self.root)
        code, out, _ = self.cmd("plan")
        self.assertEqual((code, out), (0, "no changes\n"))
        code, out, _ = self.cmd("apply")
        self.assertEqual(code, 0)
        self.assertTrue(out.startswith("no changes\n"))
        self.assertEqual(snapshot(self.root), before)

    def test_never_commits(self):  # AP7
        before = git(self.root, "rev-list", "--count", "HEAD")
        self.cmd("apply")
        self.assertEqual(git(self.root, "rev-list", "--count", "HEAD"), before)
        self.assertEqual(git(self.root, "diff", "--cached", "--name-only"), "")

    def test_written_config_passes_gate_schema(self):  # CF13
        from gates import gate_schema
        self.cmd("apply")
        res = gate_schema.check(["--root", self.root])
        self.assertIn(("PASS", "schema.config"), [(l.status, l.id) for l in res.lines])
        self.assertEqual([l for l in res.lines if l.status == "FAIL"], [])

    def test_root_required(self):  # AV4
        self.put_answers()
        for sub in ("questions", "plan", "apply"):
            self.assertEqual(self.run_init(sub, "--answers", self.ans)[0], 2)
        self.assertEqual(self.run_init("apply", "--answers", self.ans)[0], 2)

    def test_framework_dir_refused_as_root(self):  # RT14-RT16
        fw = plugin.framework_dir()
        before = snapshot(os.path.join(fw, "profiles"))
        link = os.path.join(self.tmp, "link")
        os.symlink(os.path.join(fw, "tests"), link)
        for r in (fw, fw + "/", os.path.join(fw, "tests"), link):
            code, out, _ = self.cmd("plan", root=r)
            self.assertEqual(code, 1, r)
            self.assertIn("is the framework's own directory; pass the target repository's top level", out)
        self.assertEqual(snapshot(os.path.join(fw, "profiles")), before)

    def test_linked_worktree_hooks_note(self):  # RT5, RT6
        wt = os.path.join(self.tmp, "wt")
        git(self.root, "worktree", "add", "-q", wt, "-b", "other")
        code, out, _ = self.cmd("plan", root=wt)
        self.assertEqual(code, 0, out)
        self.assertIn("note: hooks go to %s, shared by every worktree of this repository"
                      % os.path.join(self.root, ".git", "hooks"), out)
        self.assertEqual(self.cmd("apply", root=wt)[0], 0)
        self.assertTrue(os.path.exists(os.path.join(wt, ".strict-delivery", "config.yml")))
        self.assertTrue(os.path.exists(os.path.join(self.root, ".git", "hooks", "pre-commit")))
        self.assertFalse(os.path.exists(os.path.join(self.root, ".strict-delivery")))
        code, out, _ = self.cmd("plan", root=self.root, git_hooks=False)
        self.assertNotIn("shared by every worktree", out)


class TestMain(Base):
    def test_argv_and_usage(self):  # AV1-AV3
        for bad in ((), "plan", ["plan", 5], {}):
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                self.assertEqual(init.main(bad), 2)
            self.assertEqual(err.getvalue(), "init: argv must be a list of str\n")
        for argv in ([], ["Plan"], ["doctor"], ["plan "], ["--root", self.root], ["-h"]):
            self.assertEqual(self.run_init(*argv)[0], 2, argv)

    def test_option_forms(self):  # AV8-AV11, AV14, AV15, D-Q6
        self.put_answers()
        a = ("--answers", self.ans)
        self.assertEqual(self.run_init("plan", "--root", self.root, "--root", self.root, *a)[0], 2)
        self.assertEqual(self.run_init("plan", "--root", self.root)[0], 2)
        self.assertEqual(self.run_init("questions", "--root", self.root, *a)[0], 2)
        self.assertEqual(self.run_init("plan", "--root", self.root, *a, "--json")[0], 2)
        self.assertEqual(self.run_init("apply", "--root", self.root, *a, "--json")[0], 2)
        self.assertEqual(self.run_init("plan", "extra", "--root", self.root, *a)[0], 2)
        self.assertEqual(self.run_init("plan", "--root=" + self.root, *a)[0], 0)
        code, out, err = self.run_init("plan", "--help")
        self.assertEqual((code, out), (2, ""))

    def test_root_never_defaulted(self):  # AV5
        self.put_answers()
        with mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": self.root}):
            old = os.getcwd()
            os.chdir(self.root)
            try:
                self.assertEqual(self.run_init("plan", "--answers", self.ans)[0], 2)
            finally:
                os.chdir(old)

    def test_root_refusals(self):  # RT2-RT4
        sub = os.path.join(self.root, "sub")
        os.mkdir(sub)
        plain = os.path.join(self.tmp, "plain")
        os.mkdir(plain)
        bare = os.path.join(self.tmp, "bare")
        git(self.tmp, "init", "-q", "--bare", bare)
        self.put_answers()
        for r in (sub, plain, os.path.join(self.tmp, "missing"), bare, ""):
            code, out, _ = self.run_init("plan", "--root", r, "--answers", self.ans)
            self.assertEqual(code, 1, r)
            self.assertTrue(out.startswith("FAIL init.input: "), out)
        self.assertEqual(os.listdir(plain), [])

    def test_root_symlink_ok(self):  # RT9
        link = os.path.join(self.tmp, "lnk")
        os.symlink(self.root, link)
        self.assertEqual(self.cmd("apply", root=link)[0], 0)
        self.assertTrue(os.path.exists(os.path.join(self.root, "CLAUDE.md")))

    def test_check_order(self):  # AV19
        code, out, _ = self.run_init("plan", "--root", plugin.framework_dir(), "--answers", "/no/such")
        self.assertIn("is the framework's own directory", out)

    def test_questions_settings(self):  # QS9-QS11
        self.write(".claude/settings.json", json.dumps({"env": {ENV_D: "5", "OTHER": "x"}}))
        self.assertEqual(init.questions(self.root)["subagents"], {"current": {ENV_D: "5"}})
        self.write(".claude/settings.json", "{")
        q = init.questions(self.root)
        self.assertEqual(q["subagents"], {"current": None})
        self.assertEqual(q["problems"], [{"source": ".claude/settings.json", "reason": "is not valid JSON"}])

    def test_questions_problem_not_fatal(self):  # QS4
        self.write("package.json", "{not json")
        code, out, _ = self.run_init("questions", "--root", self.root, "--json")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["problems"][0]["source"], "package.json")


class TestAnswers(Base):
    def fail(self, a, text, **kw):
        self.put_answers(a)
        code, out, _ = self.run_init("plan", "--root", self.root, "--answers", self.ans)
        self.assertEqual(code, 1, out)
        self.assertIn("FAIL init.answers: " + text, out)

    def test_missing_directory_yaml_error(self):  # AF1, AF2, AF10
        for p in (os.path.join(self.tmp, "nope.yml"), self.tmp):
            code, out, _ = self.run_init("plan", "--root", self.root, "--answers", p)
            self.assertEqual(code, 1)
            self.assertIn("FAIL init.answers: ", out)
        with open(self.ans, "w") as fh:
            fh.write("a: &x 1\n")
        self.assertIn("anchors are not supported", self.run_init("plan", "--root", self.root, "--answers", self.ans)[1])

    def test_required_keys_and_unknown(self):  # AK2, AK3
        for key in ("profile", "models", "commands", "git_hooks", "ci", "merge_mode", "subagents", "protect_base",
                    "base_branch"):
            self.fail(answers(**{key: DEL}), "%s: required key is missing" % key)
        a = answers()
        a["zzz"] = 1
        self.fail(a, "zzz: unknown key")

    def test_values(self):  # AK4, AK8, AK9, AK13, AK14, AK17, AK18
        self.fail(answers(profile="Standard"), "profile: must be one of")
        self.fail(answers(merge_mode="Host"), "merge_mode: must be one of")
        for bad in (0, True, "5"):
            self.fail(answers(subagents={"depth": bad}), "subagents.depth: ")
        self.fail(answers(subagents={"depth": 10 ** 600}), "subagents.depth: must be an integer of at most 600 digits")
        c = answers()["commands"]
        c["test"] = "a\nb"
        self.fail(answers(commands=c), "commands.test: must be one line of printable characters")
        c["test"] = "   "
        self.fail(answers(commands=c), "commands.test: must be one line of printable characters")
        c["test"] = "xꟀ"
        self.fail(answers(commands=c), "commands.test: must be one line of printable characters")
        for bad in ("a b", "-x", "a..b", "a//b", "a/", "a.lock", "1" * 41 + "a"):
            self.fail(answers(base_branch=bad), "base_branch: ")
        a = answers()
        a["migrate"] = True
        self.fail(a, "migrate: no superpowers documents are tracked")
        self.fail(answers(models={"tiers": {"tier9": "x"}}), "models.tiers.tier9: unknown key")
        self.fail(answers(models={"other": {"a": "b"}}), "models.other: unknown key")

    def test_accepted_texts_kept(self):  # AK10, AK11, CF12
        cmds = {"test": "  pytest -k 'a and b' # c  ", "test_one": "run-one", "lint": "echo \"a: b\"", "build": "é {id}{id}"}
        self.assertEqual(self.cmd("apply", commands=cmds)[0], 0)
        self.assertEqual(config.load(self.root)["commands"], cmds)

    def test_null_maps_mean_empty(self):  # D-Q1
        with open(self.ans, "w", encoding="utf-8") as fh:
            fh.write(yamlsub.emit(answers(commands=DEL, subagents=DEL)) + "commands:\nsubagents:\n")
        self.assertEqual(init.load_answers(self.ans)["subagents"], {})
        code, out, _ = self.run_init("apply", "--root", self.root, "--answers", self.ans)
        self.assertEqual(code, 0, out)
        self.assertFalse(os.path.exists(os.path.join(self.root, ".claude")))
        self.assertNotIn("commands", self.read(".strict-delivery/config.yml"))

    def test_load_answers_types_and_plan_init_types(self):  # AF17, AK22, PL8
        for bad in (None, 5, b"x"):
            with self.assertRaises(GateError):
                init.load_answers(bad)
        for bad in (None, [], answers(ci=1), answers(profile=DEL), answers(subagents={"depth": 10 ** 4300})):
            with self.assertRaises(GateError):
                init.plan_init(self.root, bad)
        with self.assertRaises(GateError):
            init.plan_init(None, answers())

    def test_all_errors_listed(self):  # AK21
        self.fail(answers(profile="x", merge_mode="y"), "profile: ")
        out = self.run_init("plan", "--root", self.root, "--answers", self.ans)[1]
        self.assertIn("FAIL init.answers: merge_mode: ", out)


class TestConfig(Base):
    def test_config_text(self):  # CF1-CF11
        self.cmd("apply")
        self.assertEqual(self.read(".strict-delivery/config.yml"),
                         "schema: config/2\nframework_version: 0.0.0\nprofile: standard\ncommands:\n"
                         "  test: python3 -m unittest\n  test_one: python3 -m unittest {id}\n  lint: ruff check .\n"
                         "  build: make\nmerge:\n  mode: host\n")

    def test_config_optional_keys(self):  # CF5-CF9
        self.cmd("apply", commands={"lint": "x", "test": "t"}, base_branch="develop",
                 models={"tiers": {"tier1": "h2"}}, profile="strict")
        cfg = config.load(self.root)
        text = self.read(".strict-delivery/config.yml")
        self.assertIn("commands:\n  test: t\n  lint: x\n", text)
        self.assertIn("models:\n  tiers:\n    tier1: h2\n", text)
        self.assertIn("base_branch: develop\n", text)
        self.assertEqual((cfg["profile"], cfg["models"]["tiers"]["tier1"], cfg["models"]["tiers"]["tier2"]),
                         ("strict", "h2", "sonnet"))

    def test_valid_config_never_rewritten(self):  # CF15, IN1
        helpers.write_record(self.root, ".strict-delivery/config.yml",
                             {"schema": "config/2", "framework_version": "0.0.0", "profile": "standard",
                              "commands": answers()["commands"]})
        orig = self.read(".strict-delivery/config.yml")
        code, out, _ = self.cmd("apply")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.read(".strict-delivery/config.yml"), orig)
        self.assertTrue(init.questions(self.root)["initialised"])
        self.assertTrue(os.path.isdir(os.path.join(self.root, ".strict-delivery/state/claims")))

    def test_initialised_answers_must_match_config(self):  # D-Q4 (b)
        helpers.write_record(self.root, ".strict-delivery/config.yml",
                             {"schema": "config/2", "framework_version": "0.0.0", "profile": "strict"})
        before = snapshot(self.root)
        code, out, _ = self.cmd("apply")
        self.assertEqual(code, 1)
        self.assertIn('FAIL init.answers: profile: differs from the config (answer "standard", config "strict")', out)
        self.assertIn("commands.test: differs", out)
        self.assertEqual(snapshot(self.root), before)

    def test_invalid_config_stops(self):  # CF14, QS15
        self.write(".strict-delivery/config.yml", "schema: config/1\n")
        before = snapshot(self.root)
        for argv in (("plan",), ("apply",)):
            code, out, _ = self.cmd(argv[0])
            self.assertEqual(code, 1)
            self.assertIn("FAIL init.config: ", out)
            self.assertIn("; run /strict-delivery:doctor and /strict-delivery:upgrade", out)
        code, out, _ = self.run_init("questions", "--root", self.root)
        self.assertEqual(code, 1)
        self.assertEqual(snapshot(self.root), before)


class TestPieces(Base):
    def test_state_dirs(self):  # DR1-DR3
        self.cmd("apply")
        base = ".strict-delivery"
        for d in ("state/decisions", "state/findings", "state/claims", "state/plans", "state/programs", "playbooks"):
            p = os.path.join(self.root, base, d)
            self.assertEqual(os.listdir(p), [], d)
        self.assertEqual(sorted(os.listdir(os.path.join(self.root, base))), ["config.yml", "playbooks", "state"])
        self.assertFalse(os.path.exists(os.path.join(self.root, base, "receipts")))

    def test_dir_conflicts(self):  # DR5, DR6
        self.write(".strict-delivery/state/decisions", "file")
        code, out, _ = self.cmd("apply")
        self.assertEqual(code, 1)
        self.assertIn("init.conflict: .strict-delivery/state/decisions: exists and is not a directory", out)
        self.assertFalse(os.path.exists(os.path.join(self.root, "CLAUDE.md")))

    def test_dir_symlink_conflict(self):
        os.makedirs(os.path.join(self.root, ".strict-delivery", "state"))
        os.symlink(self.tmp, os.path.join(self.root, ".strict-delivery", "state", "claims"))
        code, out, _ = self.cmd("plan")
        self.assertEqual(code, 1)
        self.assertIn(".strict-delivery/state/claims: is a symlink", out)

    def test_blocks_keep_text(self):  # BK2, BK4, BK5, BK6
        self.write("CLAUDE.md", "my text")
        self.write(".gitignore", "node_modules\n")
        self.cmd("apply")
        c = self.read("CLAUDE.md")
        self.assertTrue(c.startswith("my text\n"))
        self.assertTrue(self.read(".gitignore").startswith("node_modules\n"))
        self.assertEqual(self.cmd("plan")[1], "no changes\n")
        self.write("CLAUDE.md", c.replace("version=0.0.0", "version=0.0.1"))
        code, out, _ = self.cmd("plan")
        self.assertEqual(code, 0)
        self.assertIn("note: CLAUDE.md: present at version 0.0.1; run /strict-delivery:upgrade", out)
        self.write("CLAUDE.md", c + c[c.index("<!-- strict-delivery:begin"):])
        code, out, _ = self.cmd("plan")
        self.assertEqual(code, 1)
        self.assertIn("CLAUDE.md: managed block malformed", out)

    def test_block_file_states(self):  # BK7
        os.symlink(os.path.join(self.root, "README.md"), os.path.join(self.root, "CLAUDE.md"))
        code, out, _ = self.cmd("plan")
        self.assertEqual(code, 1)
        self.assertIn("CLAUDE.md: is a symlink", out)

    def test_ci_tag_pin_and_refusal(self):  # CI2, CI4, CI12
        fw = self.fw_with_version("0.1.0")
        with mock.patch.object(plugin, "framework_dir", return_value=fw):
            self.assertEqual(self.cmd("apply", ci=True)[0], 0)
        text = self.read(".github/workflows/strict-delivery.yml")
        self.assertIn("git fetch --depth 1 https://github.com/o/r v0.1.0", text)
        self.assertTrue(managed.is_generated(text))
        self.assertIn("framework_version: 0.1.0", self.read(".strict-delivery/config.yml"))

    def test_ci_refused_without_pin(self):
        fw = self.fw_with_version("0.0.0")
        before = snapshot(self.root)
        with mock.patch.object(plugin, "framework_dir", return_value=fw):
            code, out, _ = self.cmd("plan", ci=True)
        self.assertEqual(code, 1)
        self.assertIn("FAIL init.answers: ci: no release tag and no framework commit to pin; answer ci: false "
                      "until v0.1.0", out)
        self.assertEqual(snapshot(self.root), before)

    def test_ci_sha_pin(self):  # CI3
        sha = git(plugin.framework_dir(), "rev-parse", "HEAD")
        self.assertEqual(self.cmd("apply", ci=True)[0], 0)
        self.assertIn(sha, self.read(".github/workflows/strict-delivery.yml"))

    def test_ci_false_touches_nothing(self):  # CI1
        self.write(".github/workflows/strict-delivery.yml", "name: mine\n")
        self.assertEqual(self.cmd("apply")[0], 0)
        self.assertEqual(self.read(".github/workflows/strict-delivery.yml"), "name: mine\n")

    def test_hooks_conflicts_and_off(self):  # HK2, HK4, HK5
        hooks = os.path.join(self.root, ".git", "hooks")
        os.makedirs(hooks, exist_ok=True)
        with open(os.path.join(hooks, "pre-commit"), "w") as fh:
            fh.write("#!/bin/sh\necho mine\n")
        code, out, _ = self.cmd("apply")
        self.assertEqual(code, 1)
        self.assertIn("FAIL init.conflict: githooks.pre-commit: foreign", out)
        self.assertFalse(os.path.exists(os.path.join(self.root, "CLAUDE.md")))
        self.assertEqual(self.cmd("apply", git_hooks=False)[0], 0)
        os.unlink(os.path.join(hooks, "pre-commit"))
        git(self.root, "config", "core.hooksPath", "elsewhere")
        code, out, _ = self.cmd("plan")
        self.assertEqual(code, 1)
        self.assertIn("core.hooksPath is set (elsewhere); unset it to install the hooks", out)

    def test_settings_states(self):  # ST4, ST9-ST14
        good = {"env": {ENV_D: "5", ENV_C: "30", "X": "1"}, "other": 1}
        self.write(".claude/settings.json", json.dumps(good))
        self.assertEqual(self.cmd("plan", git_hooks=False)[0], 0)
        for text, want in (("{", "is not valid JSON"), ("[]", "top level is not an object"),
                           ('{"env": []}', "env is not an object"), ('{"env": {}, "env": {}}', "duplicate key"),
                           ('{"a": NaN}', "the constant NaN is not allowed"),
                           ('{"a": %s}' % ("1" * 4301), "an integer of more than 4300 digits is not allowed"),
                           ('{"env": {"%s": 5, "%s": "30"}}' % (ENV_D, ENV_C), 'set "env"."%s" to "5"' % ENV_D)):
            self.write(".claude/settings.json", text)
            code, out, _ = self.cmd("plan")
            self.assertEqual(code, 1, text)
            self.assertIn(".claude/settings.json: ", out)
            self.assertIn(want, out)
        self.write(".claude/settings.json", '{"a": %s}' % ("1" * 4300))
        self.assertIn(" add ", self.cmd("plan")[1])
        target = os.path.join(self.root, ".claude", "settings.json")
        os.unlink(target)
        os.symlink(os.path.join(self.root, "README.md"), target)
        self.assertIn(".claude/settings.json: is a symlink", self.cmd("plan")[1])

    def test_apply_order_and_modes(self):  # AP3, HK13, AP12
        calls = []
        real_apply = managed.apply
        real_mkdir = os.mkdir
        real_write = githooks._write

        def rec_apply(root, actions):
            calls.append(("apply", [a[0] for a in actions]))
            return real_apply(root, actions)

        def rec_mkdir(p, *a):
            calls.append(("mkdir", os.path.relpath(p, self.root)))
            return real_mkdir(p, *a)

        def rec_hook(p, d):
            calls.append(("hook", os.path.basename(p)))
            return real_write(p, d)
        with mock.patch.object(managed, "apply", rec_apply), mock.patch.object(os, "mkdir", rec_mkdir), \
                mock.patch.object(githooks, "_write", rec_hook):
            self.assertEqual(self.cmd("apply", ci=True)[0], 0)
        kinds = [c[0] + ":" + (c[1] if isinstance(c[1], str) else ",".join(c[1])) for c in calls]
        flat = [k for k in kinds if not k.startswith("mkdir:.git")]
        self.assertEqual([k for k in flat if not k.startswith("mkdir:")],
                         ["apply:.strict-delivery/config.yml", "apply:CLAUDE.md,.gitignore",
                          "apply:.github/workflows/strict-delivery.yml", "apply:.claude/settings.json",
                          "hook:pre-commit", "hook:pre-push"])
        self.assertLess(flat.index("apply:CLAUDE.md,.gitignore"), flat.index("apply:.github/workflows/strict-delivery.yml"))
        self.assertLess(flat.index("mkdir:.strict-delivery/state"), flat.index("apply:CLAUDE.md,.gitignore"))

    def test_failure_part_way(self):  # AP4 (b), AP5
        real = managed.apply

        def boom(root, actions):
            if any(a[0] == "CLAUDE.md" for a in actions):
                raise managed.ManagedError("CLAUDE.md: cannot write (Permission denied); written before it: x")
            return real(root, actions)
        with mock.patch.object(managed, "apply", boom):
            code, out, _ = self.cmd("apply")
        self.assertEqual(code, 1)
        self.assertIn("FAIL init.write: CLAUDE.md: cannot write", out)
        self.assertIn("written: .strict-delivery/config.yml, .strict-delivery/state/", out)
        self.assertTrue(os.path.exists(os.path.join(self.root, ".strict-delivery/config.yml")))
        self.assertEqual([n for n in os.listdir(os.path.join(self.root, ".strict-delivery")) if n.startswith(".sd")], [])
        self.assertEqual(self.cmd("apply")[0], 0)  # the rest completes
        self.assertTrue(os.path.exists(os.path.join(self.root, "CLAUDE.md")))

    def test_plan_escapes_and_splits_on_lf(self):  # PO4, PO8
        self.write("CLAUDE.md", "a\rb\x1b[0m c")
        code, out, _ = self.cmd("plan")
        self.assertEqual(code, 0)
        self.assertNotIn("\x1b", out)
        self.assertNotIn(" ", out)
        self.assertIn("\\x1b", out)

    def test_hooks_idempotent_mtime(self):  # ID2, HK7
        self.cmd("apply")
        p = os.path.join(self.root, ".git", "hooks", "pre-commit")
        m = os.stat(p).st_mtime_ns
        self.cmd("apply")
        self.assertEqual(os.stat(p).st_mtime_ns, m)


class TestSource(unittest.TestCase):
    def test_init_source_has_no_exception_group(self):  # VR6, VR4, VR10
        with open(os.path.join(REPO, "gates", "tools", "init.py"), encoding="utf-8") as fh:
            src = fh.read()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            self.assertNotEqual(type(node).__name__, "TryStar")
            if isinstance(node, ast.Name):
                self.assertNotIn(node.id, ("BaseExceptionGroup", "ExceptionGroup"))
            if isinstance(node, ast.ExceptHandler):
                self.assertIsNotNone(node.type)
                self.assertNotEqual(getattr(node.type, "id", None), "BaseException")
            if isinstance(node, ast.Attribute):
                self.assertNotIn(node.attr, ("isprintable", "lower", "splitlines", "isdigit", "isalnum"))
        self.assertNotIn("\\d", src)

    def test_produces_and_not_registered(self):  # PR1-PR3
        self.assertEqual(init.PRODUCES, ("claude-block", "gitignore-block"))
        from gates.lib import schema
        for k in init.PRODUCES:
            self.assertIn(k, schema.KNOWN_KINDS)
            self.assertTrue(os.path.exists(os.path.join(REPO, "gates", "schemas", k + ".yml")))
        r = subprocess.run([sys.executable, "-m", "gates", "init", "plan"], cwd=REPO, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE)
        self.assertEqual(r.returncode, 2)

    def test_module_form_runs(self):  # PR4
        r = subprocess.run([sys.executable, "-m", "gates.tools.init", "plan"], cwd=REPO, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE)
        self.assertEqual(r.returncode, 2)
        self.assertIn(b"usage: python3 -m gates init", r.stderr)


if __name__ == "__main__":
    unittest.main()
