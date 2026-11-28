"""Tests of Task 4d.1: ``gates/tools/init.py`` (questions, plan, apply). Expected values are written by hand."""
import ast
import contextlib
import copy
import io
import json
import os
import shutil
import socket
import stat
import subprocess
import sys
import unittest
from unittest import mock

from gates.lib import config, managed, plugin, templates, yamlsub
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
                try:
                    with open(p, "rb") as fh:
                        out.append((p, st.st_mode, fh.read()))
                except PermissionError:
                    out.append((p, st.st_mode, "unreadable"))
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

    def test_no_flag_skips_owner_word(self):  # AP11: the owner's word is the command file's rule; init has no such flag
        self.put_answers()
        before = snapshot(self.root)
        for flag in ("--yes", "-y", "--force", "--no-confirm", "--confirm", "--non-interactive", "--assume-yes"):
            code, out, _ = self.run_init("apply", "--root", self.root, "--answers", self.ans, flag)
            self.assertEqual((code, out), (2, ""), flag)
            self.assertEqual(snapshot(self.root), before, flag)

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
        self.assertEqual(self.run_init("plan", "--root", self.root, *a, "--json")[0], 0)  # 4d.2 IN-P8: plan has --json
        self.assertEqual(self.run_init("apply", "--root", self.root, *a, "--json")[0], 0)  # 4d.2 IN-H7: so has apply
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
        self.assertEqual(sorted(os.listdir(os.path.join(self.root, base))), ["config.yml", "context.yml", "playbooks", "state"])
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
                         ["apply:.strict-delivery/config.yml", "apply:CLAUDE.md", "apply:.gitignore",
                          "apply:.github/workflows/strict-delivery.yml", "apply:.claude/settings.json",
                          "apply:.strict-delivery/context.yml", "hook:pre-commit", "hook:pre-push"])
        self.assertLess(flat.index("apply:.gitignore"), flat.index("apply:.github/workflows/strict-delivery.yml"))
        self.assertLess(flat.index("mkdir:.strict-delivery/state"), flat.index("apply:CLAUDE.md"))

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


class S(str):
    pass


def touch(path, data=b"x"):
    with open(path, "wb") as fh:
        fh.write(data)


def umask():
    old = os.umask(0)
    os.umask(old)
    return old


class More(Base):
    """Fixtures and helpers of the rows added by the continuation."""

    def repo(self, name, commit=True, flags=()):
        p = os.path.join(self.tmp, name)
        os.makedirs(p)
        git(p, "init", "-q", "-b", "main", *flags)
        if commit:
            self.write_in(p, "r.txt", "x\n")
            helpers.commit_all(p, "c")
        return p

    def write_in(self, root, rel, text):
        p = os.path.join(root, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(text)
        return p

    def make_fw(self, name="fw", version="0.0.0", repository="https://github.com/o/r", under=None):
        fw = os.path.join(under or self.tmp, name)
        os.makedirs(os.path.join(fw, ".claude-plugin"))
        shutil.copytree(os.path.join(REPO, "profiles"), os.path.join(fw, "profiles"))
        body = {"name": "x", "version": version}
        if repository is not None:
            body["repository"] = repository
        with open(os.path.join(fw, ".claude-plugin", "plugin.json"), "w", encoding="utf-8") as fh:
            json.dump(body, fh)
        return fw

    def init_config(self, **extra):
        rec = {"schema": "config/2", "framework_version": "0.0.0", "profile": "standard",
               "commands": answers()["commands"]}
        rec.update(extra)
        helpers.write_record(self.root, ".strict-delivery/config.yml", rec)

    def raw(self, text, sub="plan", root=None):
        data = text if isinstance(text, bytes) else text.encode("utf-8")
        with open(self.ans, "wb") as fh:
            fh.write(data)
        return self.run_init(sub, "--root", root or self.root, "--answers", self.ans)

    def refused(self, a, prefix, sub="plan"):
        self.put_answers(a)
        code, out, _ = self.run_init(sub, "--root", self.root, "--answers", self.ans)
        self.assertEqual(code, 1, (prefix, out))
        self.assertIn("FAIL init.answers: " + prefix, out)
        return out

    def accepted(self, a):
        self.put_answers(a)
        code, out, err = self.run_init("plan", "--root", self.root, "--answers", self.ans)
        self.assertEqual(code, 0, (a, out, err))
        return out

    def raw_with(self, **lines):
        """The default answers with the given keys replaced by raw YAML text."""
        a = answers()
        for k in lines:
            a.pop(k)
        return yamlsub.emit(a) + "".join("%s: %s\n" % kv for kv in lines.items())


class TestMainRows(More):
    def test_argv_types(self):  # AV1
        for bad in (None, ["plan", None], ["plan", b"x"], [S("plan")], "plan", (), {}, ["plan", 5]):
            err = io.StringIO()
            with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(init.main(bad), 2)
            self.assertEqual((err.getvalue(), out.getvalue()), ("init: argv must be a list of str\n", ""))

    def test_root_value_forms(self):  # AV7
        self.put_answers()
        a = ("--answers", self.ans)
        code, out, _ = self.run_init("plan", "--root", "", *a)
        self.assertEqual(code, 1)
        self.assertTrue(out.startswith("FAIL init.input: "), out)
        for argv in (("plan", "--root"), ("plan", *a, "--root"), ("questions", "--root", "--json"),
                     ("plan", "--root", "-x", *a)):
            self.assertEqual(self.run_init(*argv)[0], 2, argv)

    def test_answers_twice_and_empty(self):  # AV11
        self.put_answers()
        self.assertEqual(self.run_init("plan", "--root", self.root, "--answers", self.ans, "--answers", self.ans)[0], 2)
        code, out, _ = self.run_init("plan", "--root", self.root, "--answers", "")
        self.assertEqual(code, 1)
        self.assertTrue(out.startswith("FAIL init.answers: "), out)

    def test_option_abbreviation_and_order(self):  # AV13, AV14, AV12
        self.put_answers()
        for argv in (("plan", "--roo", self.root, "--ans", self.ans), ("plan", "--r", self.root, "--answers", self.ans)):
            self.assertEqual(self.run_init(*argv)[0], 0, argv)
        for argv in (("plan", "-r", self.root, "--answers", self.ans),
                     ("plan", "--bogus", "--root", self.root, "--answers", self.ans),
                     ("plan", "--root", self.root, "--answers", self.ans, "--"), ("plan", "--", "--root", self.root),
                     ("--root", self.root, "plan"), ("questions", "apply", "--root", self.root),
                     ("plan", "--root=%s" % self.root, "--answers", self.ans, "--extra")):
            self.assertEqual(self.run_init(*argv)[0], 2, argv)
        one = self.run_init("questions", "--root", self.root, "--json")
        self.assertEqual(self.run_init("questions", "--root", self.root, "--json", "--json"), one)

    def test_exit_codes_streams_types(self):  # AV16, AV17, AV18
        self.put_answers()
        cases = (((("plan", "--root", self.root, "--answers", self.ans), 0, True, False)),
                 (("plan", "--root", self.root + "-none", "--answers", self.ans), 1, True, False),
                 (("plan",), 2, False, True), (("bogus",), 2, False, True))
        for argv, want, has_out, has_err in cases:
            code, out, err = self.run_init(*argv)
            self.assertIs(type(code), int)
            self.assertEqual((code, bool(out), bool(err)), (want, has_out, has_err), argv)
        code, out, _ = self.run_init("plan", "--root", self.root + "-none", "--answers", self.ans)
        self.assertTrue(out.startswith("FAIL init.input: "))

    def test_argv_nul_and_surrogates(self):  # AV20, AV21
        self.put_answers()
        code, out, _ = self.run_init("plan", "--root", self.root + "\x00x", "--answers", self.ans)
        self.assertEqual(code, 1)
        self.assertTrue(out.startswith("FAIL init.input: "))
        self.assertNotIn("\x00", out)
        self.assertIn("\\x00", out)
        code, out, _ = self.run_init("plan", "--root", self.root, "--answers", self.ans + "\x00")
        self.assertEqual(code, 1)
        self.assertIn("FAIL init.answers: ", out)
        code, out, _ = self.run_init("plan", "--root", self.root + "\udcff", "--answers", self.ans)
        self.assertEqual(code, 1)
        self.assertTrue(out.startswith("FAIL init.input: "))
        code, out, _ = self.run_init("plan", "--root", os.path.join(self.tmp, "x\x1by"), "--answers", self.ans)
        self.assertEqual(code, 1)
        self.assertNotIn("\x1b", out)
        self.assertIn("x\\x1by", out)
        self.assertNotIn("\\\\x1b", out)

    def test_git_env_cleared(self):  # AV22
        other = self.repo("other")
        self.put_answers()
        env = {"GIT_DIR": os.path.join(other, ".git"), "GIT_WORK_TREE": other,
               "GIT_COMMON_DIR": os.path.join(other, ".git")}
        with mock.patch.dict(os.environ, env):
            code, out, _ = self.run_init("plan", "--root", self.root, "--answers", self.ans)
        self.assertEqual(code, 0, out)

    def test_argv_digit_paths(self):  # VR3
        self.put_answers()
        for n in (4300, 4301):
            self.assertEqual(self.run_init("plan", "--root", "9" * n, "--answers", self.ans)[0], 1)
            code, out, _ = self.run_init("plan", "--root", self.root, "--answers", "9" * n)
            self.assertEqual(code, 1)
            self.assertIn("FAIL init.answers: ", out)

    def test_usage_text_same_on_both(self):  # VR8
        self.put_answers()
        code, out, err = self.run_init("plan", "--bogus", "--root", self.root, "--answers", self.ans)
        self.assertEqual((code, out), (2, ""))
        self.assertEqual(err, "usage: init plan [-h] [--root ROOT] [--answers ANSWERS] [--json]\n"
                              "init plan: error: unrecognized arguments: --bogus\n")  # --json: 4d.2 IN-P8

    def test_module_form_does_work(self):  # PR4
        self.put_answers()
        r = subprocess.run([sys.executable, "-m", "gates.tools.init", "plan", "--root", self.root, "--answers", self.ans],
                           cwd=REPO, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=dict(os.environ))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(b"+++ b/.strict-delivery/config.yml", r.stdout)

    def test_import_both_interpreters(self):  # PR5
        with open(os.path.join(REPO, "gates", "tools", "init.py"), encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        self.assertTrue(any(isinstance(n, ast.ImportFrom) and n.module == "__future__" for n in tree.body))
        self.assertEqual([n for n in ast.walk(tree) if type(n).__name__ in ("Match", "TryStar")], [])


class TestRootRows(More):
    def test_root_forms_accepted(self):  # RT1, RT21, RT11, RT22
        self.put_answers()
        link = os.path.join(self.tmp, "lnk")
        os.symlink(self.root, link)
        nested = os.path.join(self.root, "inner")
        os.mkdir(nested)
        git(nested, "init", "-q", "-b", "main")
        for r in (self.root, self.root + "/", link, link + "/", nested):
            self.assertEqual(self.run_init("plan", "--root", r, "--answers", self.ans)[0], 0, r)
        for name in ("a b", "l\nf", "é", "x" * 200):
            p = self.repo(name, commit=False)
            before = snapshot(p)
            code, out, _ = self.run_init("plan", "--root", p, "--answers", self.ans)
            self.assertEqual(code, 0, name)
            self.assertEqual(snapshot(p), before)
        unborn = self.repo("unborn", commit=False)
        code, out, _ = self.run_init("apply", "--root", unborn, "--answers", self.ans)
        self.assertEqual(code, 0, out)
        self.assertIn("?? CLAUDE.md\n", out)

    def test_root_relative_forms(self):  # RT21
        self.put_answers()
        sub = os.path.join(self.root, "sub")
        os.mkdir(sub)
        old = os.getcwd()
        self.addCleanup(os.chdir, old)
        os.chdir(self.root)
        self.assertEqual(self.run_init("plan", "--root", ".", "--answers", self.ans)[0], 0)
        os.chdir(sub)
        code, out, _ = self.run_init("plan", "--root", ".", "--answers", self.ans)
        self.assertEqual(code, 1)
        self.assertIn("not the repository top level", out)
        os.chdir(os.path.join(plugin.framework_dir(), "tests"))
        code, out, _ = self.run_init("plan", "--root", ".", "--answers", self.ans)
        self.assertIn("is the framework's own directory", out)

    def test_root_case_variant(self):  # RT10, RT20
        os.mkdir(os.path.join(self.tmp, "CaseProbe"))
        if not os.path.exists(os.path.join(self.tmp, "caseprobe")):
            self.skipTest("file system is case-sensitive")
        self.put_answers()
        code, out, _ = self.run_init("plan", "--root", os.path.join(self.tmp, "REPO"), "--answers", self.ans)
        self.assertEqual(code, 1)
        self.assertTrue(out.startswith("FAIL init.input: "), out)

    def test_root_more_refusals(self):  # RT2, RT3, RT16
        sub = os.path.join(self.root, "sub")
        os.mkdir(sub)
        lsub = os.path.join(self.tmp, "lsub")
        os.symlink(sub, lsub)
        plainfile = os.path.join(self.tmp, "plainfile")
        touch(plainfile)
        self.put_answers()
        for r in (sub + "/", lsub, plainfile, os.path.join(self.root, ".git")):
            code, out, _ = self.run_init("plan", "--root", r, "--answers", self.ans)
            self.assertEqual(code, 1, r)
            self.assertTrue(out.startswith("FAIL init.input: "), out)
        l1 = os.path.join(self.tmp, "c1")
        l2 = os.path.join(self.tmp, "c2")
        os.symlink(os.path.join(plugin.framework_dir(), "tests"), l1)
        os.symlink(l1, l2)
        code, out, _ = self.run_init("plan", "--root", l2, "--answers", self.ans)
        self.assertEqual(code, 1)
        self.assertIn("is the framework's own directory", out)

    def test_root_unreadable(self):  # RT12
        d = self.repo("noperm", commit=False)
        os.chmod(d, 0)
        self.addCleanup(os.chmod, d, 0o755)
        self.put_answers()
        code, out, _ = self.run_init("plan", "--root", d, "--answers", self.ans)
        self.assertEqual(code, 1)
        self.assertTrue(out.startswith("FAIL init.input: "), out)

    def test_framework_variants(self):  # RT13, RT15, RT17, RT18, RT19
        fw = self.make_fw("fw")
        git(fw, "init", "-q", "-b", "main")
        nested = os.path.join(fw, "scratch")
        os.mkdir(nested)
        git(nested, "init", "-q", "-b", "main")
        fwlink = os.path.join(self.tmp, "fwlink")
        os.symlink(fw, fwlink)
        self.put_answers()
        for fwret, bad in ((fw, fw), (fw, nested), (fw, os.path.join(fw, ".git")), (fwlink, fw), (fwlink, fwlink),
                           (fw, fwlink)):
            with mock.patch.object(plugin, "framework_dir", return_value=fwret):
                code, out, _ = self.run_init("plan", "--root", bad, "--answers", self.ans)
            self.assertEqual(code, 1, bad)
            self.assertIn("is the framework's own directory", out)
        for name in ("fw-other", "fwx", "fw2"):
            sibling = self.repo(name, commit=False)
            with mock.patch.object(plugin, "framework_dir", return_value=fw):
                self.assertEqual(self.run_init("plan", "--root", sibling, "--answers", self.ans)[0], 0, name)
        vendored = self.make_fw("fw", under=os.path.join(self.root, "vendor"))
        before = snapshot(vendored)
        with mock.patch.object(plugin, "framework_dir", return_value=vendored):
            self.assertEqual(self.run_init("apply", "--root", self.root, "--answers", self.ans)[0], 0)
        self.assertEqual(snapshot(vendored), before)

    def test_submodule_no_note(self):  # RT7, HK11, FS11
        src = self.repo("subsrc")
        git(self.root, "-c", "protocol.file.allow=always", "submodule", "add", "-q", src, "mod")
        mod = os.path.join(self.root, "mod")
        self.put_answers()
        code, out, _ = self.run_init("plan", "--root", mod, "--answers", self.ans)
        self.assertEqual(code, 0, out)
        self.assertNotIn("shared by every worktree", out)
        self.assertEqual(self.run_init("apply", "--root", mod, "--answers", self.ans)[0], 0)
        self.assertTrue(os.path.exists(os.path.join(self.root, ".git", "modules", "mod", "hooks", "pre-commit")))
        gd = os.path.join(self.tmp, "gd")
        sg = os.path.join(self.tmp, "sg")
        git(self.tmp, "init", "-q", "-b", "main", "--separate-git-dir", gd, sg)
        code, out, _ = self.run_init("plan", "--root", sg, "--answers", self.ans)
        self.assertEqual(code, 0, out)
        self.assertNotIn("shared by every worktree", out)

    def test_apply_installs_hooks_in_common_dir(self):  # RT8, HK10
        wt = os.path.join(self.tmp, "wt")
        git(self.root, "worktree", "add", "-q", wt, "-b", "other")
        code, out, _ = self.cmd("apply", root=wt)
        self.assertEqual(code, 0, out)
        note = "note: hooks go to %s, shared by every worktree of this repository\n" % os.path.join(self.root, ".git", "hooks")
        self.assertIn(note, out)
        self.assertLess(out.index(note), out.index("?? "))
        self.assertTrue(all(l.status == "PASS" for l in githooks.status(self.root, githooks.framework_dir()).lines))

    def test_unborn_and_nul_questions(self):  # RT22
        unborn = self.repo("unb", commit=False)
        self.assertEqual(self.run_init("questions", "--root", unborn)[0], 0)


class TestQuestionRows(More):
    def test_questions_detect_error(self):  # QS5
        with mock.patch.object(init.detect, "detect", side_effect=GateError("boom")):
            code, out, _ = self.run_init("questions", "--root", self.root)
        self.assertEqual((code, out), (1, "FAIL init.input: boom\n"))

    def test_questions_profiles(self):  # QS6, FS9
        q = init.questions(self.root)
        self.assertEqual([p["name"] for p in q["profiles"]], ["light", "standard", "strict"])
        self.assertTrue(all(set(p) == {"name", "defaults", "policy"} for p in q["profiles"]))
        std = q["profiles"][1]
        self.assertEqual(std["defaults"], {"top_tier_roles": ["final_verifier", "exception_reviewer"]})
        self.assertEqual(std["policy"], {"block": {"max_tasks": 5}})
        fw = os.path.join(self.tmp, "fw2")
        os.mkdir(fw)
        with mock.patch.object(plugin, "framework_dir", return_value=fw):
            code, out, _ = self.run_init("questions", "--root", self.root)
        self.assertEqual(code, 1)
        self.assertTrue(out.startswith("FAIL init.input: profiles/light.yml: "), out)

    def test_questions_models_are_defaults(self):  # QS7
        q = init.questions(self.root)
        q["models"]["tier1"] = "x"
        self.assertEqual(init.questions(self.root)["models"], {"tier1": "haiku", "tier2": "sonnet", "tier3": "opus"})
        self.assertEqual(config.DEFAULTS["models"]["tiers"]["tier1"], "haiku")

    def test_questions_subagents_current(self):  # QS9, QS10, QS11, ST19
        for text in (None, "{}", '{"env": {}}', '{"env": {"OTHER": "1"}}'):
            if text is not None:
                self.write(".claude/settings.json", text)
            self.assertEqual(init.questions(self.root)["subagents"], {"current": None}, text)
        for env, want in (({ENV_D: "5", ENV_C: "30", "OTHER": "x"}, {ENV_D: "5", ENV_C: "30"}), ({ENV_C: "30"}, {ENV_C: "30"})):
            self.write(".claude/settings.json", json.dumps({"env": env}))
            self.assertEqual(init.questions(self.root)["subagents"], {"current": want})
        self.write(".claude/settings.json", json.dumps({"env": {ENV_D: 5}}))
        q = init.questions(self.root)
        self.assertEqual((q["subagents"], q["problems"]), ({"current": None}, [
            {"source": ".claude/settings.json", "reason": "env.%s: is not a string" % ENV_D}]))
        self.write(".claude/settings.json", json.dumps({"env": {ENV_D: "abc"}}))
        q = init.questions(self.root)
        self.assertEqual(q["problems"], [{"source": ".claude/settings.json",
                                          "reason": "env.%s: is not a decimal string" % ENV_D}])
        p = os.path.join(self.root, ".claude", "settings.json")
        for setup, reason in ((lambda: os.symlink(os.path.join(self.root, "README.md"), p), "is a symlink"),
                              (lambda: os.mkdir(p), "exists and is not a regular file"),
                              (lambda: os.mkfifo(p), "exists and is not a regular file"),
                              (lambda: touch(p, b"\xff\xfe"), "is not valid UTF-8"),
                              (lambda: touch(p, b'{"env": []}'), "env is not an object"),
                              (lambda: touch(p, b"[]"), "top level is not an object")):
            os.unlink(p) if os.path.lexists(p) and not os.path.isdir(p) or os.path.islink(p) else None
            if os.path.isdir(p) and not os.path.islink(p):
                os.rmdir(p)
            setup()
            q = helpers.within(lambda: init.questions(self.root))
            self.assertEqual((q["subagents"], q["problems"]), ({"current": None},
                                                               [{"source": ".claude/settings.json", "reason": reason}]))

    def test_questions_docs_and_shape(self):  # QS12, QS16, FS14
        self.write("docs/superpowers/specs/a.md", "x\n")
        self.write("docs/superpowers/plans/b.md", "y\n")
        helpers.commit_all(self.root, "docs")
        base = init.questions(self.root)
        self.assertEqual(base["superpowers_docs"], [["docs/superpowers/plans/b.md", "docs/strict-delivery/plans/b.md"],
                                                    ["docs/superpowers/specs/a.md", "docs/strict-delivery/specs/a.md"]])  # Q15
        self.init_config()
        q = init.questions(self.root)
        self.assertIs(q["initialised"], True)
        self.assertEqual(set(q), set(base))
        self.assertEqual({k: v for k, v in q.items() if k != "initialised"},
                         {k: v for k, v in base.items() if k != "initialised"})

    def test_questions_text_form_and_determinism(self):  # QS18, QS19, QS2
        self.write("package.json", '{"scripts": {"test": "jest", "lint": "eslint ."}}')
        self.write("Makefile", "build:\n\techo b\n")
        first = self.run_init("questions", "--root", self.root)
        self.assertEqual(first, self.run_init("questions", "--root", self.root))
        q = init.questions(self.root)
        self.assertEqual([p["slot"] for p in q["proposals"]] != sorted(p["slot"] for p in q["proposals"]), True)
        for p in q["proposals"]:
            for k in ("slot", "command", "source"):
                self.assertIn(p[k], first[1])
        lines = first[1].split("\n")
        self.assertEqual([l.split(":", 1)[0] for l in lines[:-1]], list(q))
        self.assertEqual(lines[-1], "")
        self.assertEqual(init.questions(self.root), q)

    def test_questions_json_ascii(self):  # QS17, VR4
        self.write("package.json", '{"scripts": {"test": "echo \\u00e9 \\ua7c0"}}')
        code, out, _ = self.run_init("questions", "--root", self.root, "--json")
        self.assertEqual(code, 0)
        self.assertTrue(out.isascii())
        self.assertEqual(json.loads(out), init.questions(self.root))
        self.assertTrue(out.endswith("}\n") and not out.endswith("\n\n"))

    def test_questions_direct_call_types(self):  # QS20
        for bad in (None, b"x", S(self.root), ""):
            with self.assertRaises(GateError):
                init.questions(bad)
        q = init.questions(self.root)
        self.assertIs(type(q), dict)
        self.assertEqual(len(q), 10)
        json.dumps(q)

    def test_detect_source_states(self):  # FS12
        os.symlink(os.path.join(self.root, "README.md"), os.path.join(self.root, "package.json"))
        os.mkfifo(os.path.join(self.root, "Cargo.toml"))
        os.mkdir(os.path.join(self.root, "go.mod"))
        self.write("pyproject.toml", "\xff", mode="w")
        code, out, _ = helpers.within(lambda: self.run_init("questions", "--root", self.root, "--json"))
        self.assertEqual(code, 0, out)
        json.loads(out)


class TestAnswersFile(More):
    def failraw(self, data, text):
        code, out, _ = self.raw(data)
        self.assertEqual(code, 1, out)
        self.assertIn("FAIL init.answers: " + text, out)

    def test_answers_special_files(self):  # AF3, AF4, AF5, AF6
        fifo = os.path.join(self.tmp, "fifo.yml")
        os.mkfifo(fifo)
        code, out, _ = helpers.within(lambda: self.run_init("plan", "--root", self.root, "--answers", fifo))
        self.assertEqual(code, 1)
        self.assertIn("not a regular file", out)
        self.put_answers()
        link = os.path.join(self.tmp, "l.yml")
        os.symlink(self.ans, link)
        self.assertEqual(self.run_init("plan", "--root", self.root, "--answers", link)[0], 0)
        dang = os.path.join(self.tmp, "d.yml")
        os.symlink(os.path.join(self.tmp, "none.yml"), dang)
        self.assertIn("No such file or directory", self.run_init("plan", "--root", self.root, "--answers", dang)[1])
        la, lb = os.path.join(self.tmp, "la"), os.path.join(self.tmp, "lb")
        os.symlink(lb, la)
        os.symlink(la, lb)
        self.assertIn("Too many levels of symbolic links", self.run_init("plan", "--root", self.root, "--answers", la)[1])
        self.assertIn("not a regular file", self.run_init("plan", "--root", self.root, "--answers",
                                                          os.path.join(self.tmp, "work"))[1])
        os.chmod(self.ans, 0)
        self.addCleanup(os.chmod, self.ans, 0o644)
        self.assertIn("cannot read file (Permission denied)", self.run_init("plan", "--root", self.root, "--answers", self.ans)[1])
        os.chmod(self.ans, 0o644)
        for data in (b"\xff\xfe", b"a: \x80\n", "a: 1\n".encode("utf-16"), b"a: \xc0\xaf\n"):
            self.failraw(data, "%s: not valid UTF-8" % self.ans)

    def test_answers_bom_and_endings(self):  # AF7, AF8
        good = yamlsub.emit(answers())
        self.assertEqual(self.raw(b"\xef\xbb\xbf" + good.encode())[0], 0)
        self.failraw(b"\xef\xbb\xbf\xef\xbb\xbf" + good.encode(), "schema: expected init-answers/1, got (missing)")
        self.failraw(good.encode() + b"\xef\xbb\xbf", "%s: " % self.ans)
        self.assertEqual(self.raw(good.replace("\n", "\r\n"))[0], 0)
        self.failraw(b"a: 1\rb: 2\n", "%s: control character not allowed (line 1)" % self.ans)
        self.failraw(good.replace("\n", "\r\n", 3) + "x: 1\r", "%s: control character not allowed" % self.ans)

    def test_answers_not_a_mapping(self):  # AF9
        for t in (b"", b"  \n", b"# c\n", b"- a\n", b"x\n", b"5\n", b"null\n"):
            self.failraw(t, "top level: must be a mapping")

    def test_answers_yaml_features_refused(self):  # AF10, AF11
        p = self.ans + ": "
        for data, text in ((b"a: &x 1\n", "anchors are not supported (line 1)"),
                           (b"a: *x\n", "aliases are not supported (line 1)"),
                           (b"a: !t 1\n", "tags are not supported (line 1)"),
                           (b"a: {b: c}\n", "flow mappings are not supported (line 1)"),
                           (b"a:\n\tb: 1\n", "tab in indentation (line 2)"),
                           (b"---\na: 1\n", "document markers are not supported (line 1)"),
                           (b"...\n", "document markers are not supported (line 1)"),
                           (b"<<: x\n", "merge keys are not supported (line 1)"),
                           (b"a: >\n  b\n", "folded scalars are not supported (line 1)"),
                           (b"a: \x00\n", "control character not allowed (line 1)"),
                           (b'a: "\\ud800"\n', "surrogate \\\\u escape is not supported (line 1)"),
                           (b"ci: true\nci: false\n", "duplicate key 'ci' (line 2)"),
                           (b"a:\n  b: 1\n  b: 2\n", "duplicate key 'b' (line 3)")):
            self.failraw(data, p + text)
        self.failraw(b"a: [x]\n", "schema: expected init-answers/1, got (missing)")

    def test_answers_large_inputs(self):  # AF12
        a = answers()
        a["commands"]["test"] = "x" * 100000
        self.assertEqual(self.accepted(a) != "", True)
        big = yamlsub.emit(answers()) + ("# " + "c" * 78 + "\n") * 130000
        self.assertEqual(self.raw(big)[0], 0)
        deep = "".join("%sa%d:\n" % ("  " * i, i) for i in range(51)) + "  " * 51 + "x: 1\n"
        self.failraw(deep, "%s: " % self.ans)

    def test_answers_path_forms(self):  # AF13, AF14, AF15, AF16
        self.put_answers()
        old = os.getcwd()
        self.addCleanup(os.chdir, old)
        os.chdir(self.tmp)
        self.assertEqual(self.run_init("plan", "--root", self.root, "--answers", "answers.yml")[0], 0)
        code, out, _ = self.run_init("plan", "--root", self.root, "--answers", "~/a.yml")
        self.assertEqual(code, 1)
        self.assertIn("No such file or directory", out)
        odd = os.path.join(self.tmp, "a b\né.yml")
        with open(odd, "w", encoding="utf-8") as fh:
            fh.write(yamlsub.emit(answers()))
        self.assertEqual(self.run_init("plan", "--root", self.root, "--answers", odd)[0], 0)
        inside = os.path.join(self.root, "answers.yml")
        with open(inside, "w", encoding="utf-8") as fh:
            fh.write(yamlsub.emit(answers()))
        before = snapshot(self.root)
        self.assertEqual(self.run_init("plan", "--root", self.root, "--answers", inside)[0], 0)
        self.assertEqual(snapshot(self.root), before)
        code, out, _ = self.run_init("apply", "--root", self.root, "--answers", inside)
        self.assertEqual(code, 0)
        self.assertIn("?? answers.yml\n", out)
        got = init.load_answers(self.ans)
        self.assertIs(type(got), dict)
        self.assertEqual(got, answers())
        self.assertEqual(init.load_answers(self.ans), got)

    def test_apply_rereads_answers(self):  # AF15, AP1
        self.assertEqual(self.cmd("plan")[0], 0)
        os.symlink(os.path.join(self.root, "README.md"), os.path.join(self.root, "CLAUDE.md"))
        before = snapshot(self.root)
        code, out, _ = self.cmd("apply", commands={"test": "other"})
        self.assertEqual(code, 1)
        self.assertIn("CLAUDE.md: is a symlink", out)
        self.assertEqual(snapshot(self.root), before)
        os.unlink(os.path.join(self.root, "CLAUDE.md"))
        self.assertEqual(self.cmd("apply", commands={"test": "other"})[0], 0)
        self.assertIn("  test: other\n", self.read(".strict-delivery/config.yml"))


class TestAnswerValues(More):
    def test_schema_tag(self):  # AK1
        for v in ("init-answers/2", "init-answers/0", "profile/1", "init-answers/01", "init-answers", 5, None):
            self.refused(answers(schema=v), "schema: ")
        self.refused(answers(schema="init-answers/2"), "schema: expected init-answers/1, got init-answers/2; run /strict-delivery:upgrade")
        self.refused(answers(schema=DEL), "schema: expected init-answers/1, got (missing)")

    def test_unknown_keys(self):  # AK3
        for k in ("Profile", "é"):
            code, out, _ = self.raw(yamlsub.emit(answers()) + "%s: x\n" % k)
            self.assertEqual(code, 1)
            self.assertIn("FAIL init.answers: %s: unknown key" % k, out)
        self.refused(answers(commands={"deploy": "x"}), "commands.deploy: unknown key")
        self.refused(answers(subagents={"x": 5}), "subagents.x: unknown key")
        self.refused(answers(models={"tiers": {"tier1": "a"}, "top_tier_fallback": "x"}),
                     "models.top_tier_fallback: unknown key")

    def test_profile_values(self):  # AK4
        for p in ("light", "standard", "strict"):
            self.accepted(answers(profile=p))
        for p in ("Standard", "STRICT", " standard", "standard ", "standard\n", "", "custom", 5, True):
            self.refused(answers(profile=p), "profile: must be one of light, standard, strict")
        self.refused(answers(profile=None), "profile: must not be null")
        self.refused(answers(profile=["standard"]), "profile: ")

    def test_models_shape_and_values(self):  # AK5, AK6
        self.refused(answers(models="x"), "models: must be a mapping")
        self.refused(answers(models=None), "models: must not be null")
        self.refused(answers(models={"other": {"a": "b"}}), "models.tiers: required key is missing")
        self.refused(answers(models={"tiers": "x"}), "models.tiers: must be a non-empty mapping")
        for k in ("tier0", "tier5", "Tier1", "tier1 ", "top_tier_fallback"):
            self.refused(answers(models={"tiers": {k: "x"}}), "models.tiers.%s: unknown key" % k)
        for v in ("", " ", 5, True, "a\nb", "a\x00b", "a\ua7c0b"):
            self.refused(answers(models={"tiers": {"tier1": v}}), "models.tiers.tier1: must be one line of printable characters")
        for t in ({"tier1": "haiku"}, {"tier4": "claude-x 1"}, {"tier1": "a", "tier2": "b", "tier3": "c", "tier4": "d"}):
            self.accepted(answers(models={"tiers": t}))

    def test_commands_shape_and_types(self):  # AK7, AK8, AK9
        self.accepted(answers(commands={"lint": "x"}))
        for v in ("", 5, True, ["a"], {"a": "b"}):
            self.refused(answers(commands={"test": v}), "commands.test: ")
        self.refused(answers(commands={"test": None}), "commands.test: must not be null")
        for v in (" ", "   ", "a\nb", "a\rb", "a\x00b", "a\tb", "a\x1bb", "a\x7fb", "a\x85b", "a\u2028b", "a\u2029b",
                  "a\n", "a\ua7c0b", "a\U0001F6DDb"):
            self.refused(answers(commands={"test": v}), "commands.test: must be one line of printable characters")
        self.failraw_block()

    def failraw_block(self):
        text = yamlsub.emit(answers(commands=DEL)) + "commands:\n  test: |\n    a\n    b\n"
        code, out, _ = self.raw(text)
        self.assertEqual(code, 1)
        self.assertIn("FAIL init.answers: commands.test: must be one line of printable characters", out)

    def test_command_texts_round_trip(self):  # AK10, CF12
        for cmd in ("python3 -m unittest -q", "pytest -k 'a and b'", "make test # c", 'echo "a: b"', "  lead", "trail  ",
                    "cmd \\", "é text", "{id}", "{id}{id}", "x" * 100000):
            plan = init.plan_init(self.root, answers(commands={"test": cmd}))
            self.assertEqual(yamlsub.parse(plan.writes[0].text)["commands"]["test"], cmd)

    def test_booleans(self):  # AK12
        for k in ("git_hooks", "ci", "protect_base"):
            for bad in ("yes", "True", "TRUE", "1", "0", '"true"', "~", "[true]"):
                code, out, _ = self.raw(self.raw_with(**{k: bad}))
                self.assertEqual(code, 1, (k, bad))
                self.assertIn("FAIL init.answers: %s: " % k, out)
        self.accepted(answers(protect_base=True))
        self.accepted(answers(protect_base=False))

    def test_merge_mode(self):  # AK13
        for m in ("host", "controller"):
            self.accepted(answers(merge_mode=m))
        for m in ("Host", "HOST", "controller ", "squash", "", 5):
            self.refused(answers(merge_mode=m), "merge_mode: must be one of host, controller")
        self.refused(answers(merge_mode=None), "merge_mode: must not be null")

    def test_subagent_integers(self):  # AK14, AK15, AK16, VR1, VR2
        for v in ("05", "+5", "0x5", "1_0", "5.0", '"5"', "true", "[5]"):
            code, out, _ = self.raw(self.raw_with(subagents="\n  depth: " + v))
            self.assertEqual(code, 1, v)
            self.assertIn("FAIL init.answers: ", out)
        code, out, _ = self.raw(self.raw_with(subagents="\n  depth: ~"))
        self.assertIn("subagents.depth: must not be null", out)
        for v in (0, -1):
            self.refused(answers(subagents={"depth": v}), "subagents.depth: must be at least 1")
        for a in ({"depth": 1}, {"concurrent": 30}, {"depth": 5, "concurrent": 30}):
            self.accepted(answers(subagents=a))
        self.assertEqual(self.raw(self.raw_with(subagents=""))[0], 0)
        for lim in helpers.INT_LIMITS:
            with helpers.int_limit(lim):
                self.accepted(answers(subagents={"depth": 10 ** 599}))
                for n in (601, 1000):
                    code, out, _ = self.raw(self.raw_with(subagents="\n  depth: " + "9" * n))
                    self.assertEqual(code, 1)
                    if n == 601 or lim != 640:  # a 641..1000 digit numeral is "integer too large" under limit 640
                        self.assertIn("FAIL init.answers: subagents.depth: must be an integer of at most 600 digits", out)
                    else:
                        self.assertIn("FAIL init.answers: ", out)
                for n in (1001, 4300, 4301):
                    code, out, _ = self.raw(self.raw_with(subagents="\n  depth: " + "9" * n))
                    self.assertEqual(code, 1)
                    self.assertIn("%s: integer too large (line " % self.ans, out)
                    with self.assertRaises(GateError):
                        init.plan_init(self.root, answers(subagents={"depth": 10 ** (n - 1)}))

    def test_base_branch(self):  # AK17
        for b in ("main", "develop", "release/1.0", "a_b-c.d", "HEAD", "1" * 40, "refs/heads/x"):
            self.accepted(answers(base_branch=b))
        for b in ("a b", "a\nb", "a\x00b", "-x", "^x", "a..b", "a//b", "a/", "/a", "a.lock", "1" * 41, "é"):
            self.refused(answers(base_branch=b), "base_branch: must be a branch name")
        for b in ("", 5):
            self.refused(answers(base_branch=b), "base_branch: ")
        self.refused(answers(base_branch=None), "base_branch: must not be null")

    def test_migrate_and_key_order(self):  # AK18, AK20
        for v in (True, False):
            a = answers()
            a["migrate"] = v
            self.refused(a, "migrate: no superpowers documents are tracked")
        keys = list(answers())
        text = "".join(yamlsub.emit({k: answers()[k]}) for k in reversed(keys))
        code, out, _ = self.raw(text)
        self.assertEqual(code, 0)
        self.assertEqual(out, self.run_init("plan", "--root", self.root, "--answers", self.put_answers())[1])

    def test_plan_init_answers_types(self):  # AK22
        class D(dict):
            pass
        for bad in (answers(profile=S("standard")), answers(ci=1), answers(subagents={"depth": True}),
                    answers(commands=None), answers(models={}), answers(profile=DEL), D(answers()), ["x"], None,
                    answers(subagents={"depth": 10 ** 4299}), answers(subagents={"depth": 10 ** 4300})):
            for lim in helpers.INT_LIMITS:
                with helpers.int_limit(lim), self.assertRaises(GateError):
                    init.plan_init(self.root, bad)
        a = answers()
        a["extra"] = 1
        with self.assertRaises(GateError):
            init.plan_init(self.root, a)
        for bad in (S(self.root), b"x"):
            with self.assertRaises(GateError):
                init.plan_init(bad, answers())

    def test_load_answers_deterministic(self):  # AK23
        self.put_answers()
        self.assertEqual(init.load_answers(self.ans), init.load_answers(self.ans))

    def test_unicode_version_rows(self):  # VR4, VR5
        import unicodedata
        with mock.patch.object(unicodedata, "category", side_effect=AssertionError("no unicodedata")):
            self.accepted(answers())
            self.refused(answers(commands={"test": "a\ua7c0b"}), "commands.test: must be one line of printable characters")
            self.refused(answers(base_branch="a\ua7c0"), "base_branch: ")


class TestConfigRows(More):
    def test_config_facts(self):  # CF2, CF3, CF4, CF11, CF16, CF18
        fw = self.make_fw("fw", version="12.0.7")
        os.makedirs(os.path.join(self.root, ".strict-delivery", "state"))
        for profile in ("light", "standard", "strict"):
            plan = init.plan_init(self.root, answers(profile=profile))
            data = yamlsub.parse(plan.writes[0].text)
            self.assertEqual(data["schema"], "config/2")
            self.assertEqual(config.CONFIG_TAG, "config/2")
            self.assertEqual(data["profile"], profile)
            self.assertTrue(set(data) <= {"schema", "framework_version", "profile", "commands", "models", "base_branch",
                                          "merge"})
        with mock.patch.object(plugin, "framework_dir", return_value=fw):
            self.assertEqual(self.cmd("apply", profile="strict")[0], 0)
        self.assertEqual(yamlsub.load(os.path.join(self.root, ".strict-delivery", "config.yml"), "c")["framework_version"], "12.0.7")
        self.assertEqual(config.load(self.root)["profile"], "strict")
        p = os.path.join(self.root, ".strict-delivery", "config.yml")
        with open(p, "rb") as fh:
            raw = fh.read()
        self.assertEqual((b"\r" in raw, raw.endswith(b"\n"), raw.endswith(b"\n\n"), raw[:3] == b"\xef\xbb\xbf"),
                         (False, True, False, False))
        self.assertEqual(os.stat(p).st_mode & 0o777, 0o666 & ~umask())

    def test_config_commands_and_models(self):  # CF5, CF6, CF7, CF8, CF9, CF10
        plan = init.plan_init(self.root, answers(commands={}))
        self.assertNotIn("commands", plan.writes[0].text)
        plan = init.plan_init(self.root, answers(models={"tiers": {"tier3": "opus", "tier1": "haiku", "tier2": "sonnet"}}))
        self.assertNotIn("models", plan.writes[0].text)
        plan = init.plan_init(self.root, answers(models={"tiers": {"tier1": "h"}}))
        self.assertIn("models:\n  tiers:\n    tier1: h\n", plan.writes[0].text)
        plan = init.plan_init(self.root, answers(models={"tiers": {"tier4": "z", "tier1": "haiku"}}))
        self.assertIn("models:\n  tiers:\n    tier1: haiku\n    tier4: z\n", plan.writes[0].text)
        plan = init.plan_init(self.root, answers(base_branch="main"))
        self.assertNotIn("base_branch", plan.writes[0].text)
        for m in ("host", "controller"):
            text = init.plan_init(self.root, answers(merge_mode=m)).writes[0].text
            self.assertTrue(text.endswith("merge:\n  mode: %s\n" % m), text)
        text = init.plan_init(self.root, answers(commands={"build": "b", "test": "t"})).writes[0].text
        self.assertIn("commands:\n  test: t\n  build: b\n", text)
        self.assertNotIn("lint", text)

    def test_config_emit_errors_mapped(self):  # CF19
        for bad in (answers(models={"tiers": {"tier1": "a\ud800"}}),):
            with self.assertRaises(GateError):
                init.plan_init(self.root, bad)

    def test_invalid_config_states(self):  # CF14, FS2
        p = os.path.join(self.root, ".strict-delivery", "config.yml")
        os.makedirs(os.path.dirname(p))
        states = []

        def put(data):
            def f():
                with open(p, "wb") as fh:
                    fh.write(data)
            return f

        def dirn():
            os.mkdir(p)

        def fifo():
            os.mkfifo(p)

        def dangling():
            os.symlink(os.path.join(self.tmp, "nope"), p)

        def noperm():
            put(b"schema: config/2\n")()
            os.chmod(p, 0)
            self.addCleanup(os.chmod, p, 0o644)
        for setup in (put(b"a: [\n"), put(b"schema: config/1\n"), put(b"\xff\xfe"), put(b""), put(b"\xef\xbb\xbf"), dirn, fifo,
                      dangling, noperm, put(b"schema: config/2\nframework_version: 0.0.0\nprofile: standard\nzzz: 1\n"),
                      put(b"schema: config/2\nframework_version: 0.0.0\nprofile: nope\n")):
            if os.path.lexists(p):
                if os.path.isdir(p) and not os.path.islink(p):
                    os.rmdir(p)
                else:
                    os.chmod(p, 0o644) if os.path.isfile(p) else None
                    os.unlink(p)
            setup()
            before = snapshot(self.root)
            for sub in ("plan", "apply", "questions"):
                if sub == "questions":
                    code, out, _ = helpers.within(lambda: self.run_init(sub, "--root", self.root))
                else:
                    code, out, _ = helpers.within(lambda: self.cmd(sub))
                self.assertEqual(code, 1, (setup, sub, out))
                self.assertTrue(out.startswith("FAIL init.config: "), out)
                self.assertTrue(out.endswith("; run /strict-delivery:doctor and /strict-delivery:upgrade\n"), out)
            self.assertEqual(snapshot(self.root), before)

    def test_config_parent_and_valid_symlink(self):  # CF17, CF15, QS14
        for setup in (lambda p: touch(p), lambda p: os.symlink(self.tmp, p),
                      lambda p: os.symlink(os.path.join(self.tmp, "none"), p)):
            p = os.path.join(self.root, ".strict-delivery")
            if os.path.lexists(p):
                os.unlink(p)
            setup(p)
            code, out, _ = self.cmd("plan")
            self.assertEqual(code, 1)
            self.assertIn("FAIL init.conflict: .strict-delivery/config.yml: parent .strict-delivery is not a directory", out)
        os.unlink(os.path.join(self.root, ".strict-delivery"))
        real = os.path.join(self.tmp, "cfg.yml")
        helpers.write_record(self.tmp, "cfg.yml", {"schema": "config/2", "framework_version": "0.0.0", "profile": "standard",
                                                   "commands": answers()["commands"]})
        os.mkdir(os.path.join(self.root, ".strict-delivery"))
        os.symlink(real, os.path.join(self.root, ".strict-delivery", "config.yml"))
        self.assertIs(init.questions(self.root)["initialised"], True)
        code, out, _ = self.cmd("apply")
        self.assertEqual(code, 0, out)
        self.assertTrue(os.path.islink(os.path.join(self.root, ".strict-delivery", "config.yml")))

    def test_version_numerals_verbatim(self):  # VR1 (c), VR2 (c)
        for n in (4300, 4301):
            fw = self.make_fw("fw%d" % n, version="9" * n + ".0.0")
            for lim in helpers.INT_LIMITS:
                with helpers.int_limit(lim), mock.patch.object(plugin, "framework_dir", return_value=fw):
                    code, out, _ = self.cmd("plan")
                self.assertEqual(code, 0, out[:200])
                self.assertIn("+framework_version: " + "9" * n + ".0.0\n", out)


class TestStateDirs(More):
    def test_dirs_existing_and_modes(self):  # DR2, DR4, DR9 prep, DR10, DR11
        d = os.path.join(self.root, ".strict-delivery", "state", "decisions")
        os.makedirs(d)
        self.write(".strict-delivery/state/decisions/keep.md", "k")
        code, out, _ = self.cmd("plan")
        self.assertNotIn("mkdir .strict-delivery/state/decisions/", out)
        lines = [l for l in out.split("\n") if l.startswith("mkdir ")]
        self.assertEqual(lines, ["mkdir .strict-delivery/state/findings/", "mkdir .strict-delivery/state/claims/",
                                 "mkdir .strict-delivery/state/plans/", "mkdir .strict-delivery/state/programs/",
                                 "mkdir .strict-delivery/playbooks/"])
        self.assertEqual(self.cmd("apply")[0], 0)
        self.assertEqual(self.read(".strict-delivery/state/decisions/keep.md"), "k")
        for rel in (".strict-delivery/state/claims", ".strict-delivery/playbooks"):
            self.assertEqual(os.stat(os.path.join(self.root, rel)).st_mode & 0o777, 0o777 & ~umask())
        self.assertEqual(self.cmd("plan")[1], "no changes\n")

    def test_dir_fifo_and_parent_file(self):  # DR5, DR7
        os.makedirs(os.path.join(self.root, ".strict-delivery", "state"))
        os.mkfifo(os.path.join(self.root, ".strict-delivery", "state", "claims"))
        code, out, _ = helpers.within(lambda: self.cmd("plan"))
        self.assertEqual(code, 1)
        self.assertIn("FAIL init.conflict: .strict-delivery/state/claims: exists and is not a directory", out)
        os.unlink(os.path.join(self.root, ".strict-delivery", "state", "claims"))
        os.rmdir(os.path.join(self.root, ".strict-delivery", "state"))
        self.write(".strict-delivery/state", "f")
        code, out, _ = self.cmd("plan")
        self.assertIn(".strict-delivery/state: exists and is not a directory", out)

    def test_dir_symlink_variants(self):  # DR6
        base = os.path.join(self.root, ".strict-delivery", "state")
        os.makedirs(base)
        for target in (os.path.join(self.root, "README.md"), os.path.join(self.tmp, "none"), self.tmp):
            link = os.path.join(base, "findings")
            if os.path.lexists(link):
                os.unlink(link)
            os.symlink(target, link)
            code, out, _ = self.cmd("plan")
            self.assertEqual(code, 1)
            self.assertIn(".strict-delivery/state/findings: is a symlink", out)
        os.unlink(os.path.join(base, "findings"))
        os.rmdir(base)
        os.symlink(self.tmp, base)
        code, out, _ = self.cmd("plan")
        self.assertIn(".strict-delivery/state: is a symlink", out)

    def test_equal_configured_paths_refused_by_templates(self):  # DR8
        self.init_config(paths={"decisions": "records/dec", "findings": "records/dec"})
        before = snapshot(self.root)
        code, out, _ = self.cmd("apply")
        self.assertEqual(code, 1)
        self.assertTrue(out.startswith("FAIL init.input: two ignore lines are equal: "), out)
        self.assertEqual(snapshot(self.root), before)

    def test_dirs_use_configured_paths(self):  # DR8, PL7
        self.init_config(paths={"decisions": "records/dec", "claims": "records/dec/claims"})
        code, out, _ = self.cmd("apply")
        self.assertEqual(code, 0, out)
        self.assertTrue(os.path.isdir(os.path.join(self.root, "records", "dec", "claims")))
        self.assertFalse(os.path.exists(os.path.join(self.root, ".strict-delivery", "state", "decisions")))
        self.assertTrue(os.path.isdir(os.path.join(self.root, ".strict-delivery", "state", "plans")))

    def test_mkdirs_permission_failure(self):  # DR9, AP4 (a)
        self.init_config()
        os.chmod(os.path.join(self.root, ".strict-delivery"), 0o555)
        self.addCleanup(os.chmod, os.path.join(self.root, ".strict-delivery"), 0o755)
        code, out, _ = self.cmd("apply")
        self.assertEqual(code, 1)
        self.assertIn("FAIL init.write: .strict-delivery/state: cannot create (Permission denied)\nwritten: \n", out)
        self.assertEqual([n for n in os.listdir(os.path.join(self.root, ".strict-delivery")) if n.startswith(".sd")], [])


class TestBlocks(More):
    def test_blocks_text_states(self):  # BK2, BK3
        for body in ("a\n", "a", "", "\n\n", "a\r\nb\r\n", "a\rb"):
            with open(os.path.join(self.root, "CLAUDE.md"), "wb") as fh:
                fh.write(body.encode("utf-8"))
            code, out, _ = self.cmd("apply", git_hooks=False)
            self.assertEqual(code, 0, out)
            with open(os.path.join(self.root, "CLAUDE.md"), "rb") as fh:
                new = fh.read().decode("utf-8")
            joined = body if body.endswith("\n") or body == "" else body + "\n"
            self.assertTrue(new.startswith(joined), repr(body))
            self.assertTrue(new[len(joined):].startswith("<!-- strict-delivery:begin"), repr(body))
        self.write("CLAUDE.md", "﻿<!-- strict-delivery:begin schema=claude-block/1 version=0.0.0 -->\nx\n"
                                "<!-- strict-delivery:end -->\n")
        code, out, _ = self.cmd("plan")
        self.assertEqual(code, 1)
        self.assertIn("CLAUDE.md: managed block malformed", out)

    def test_blocks_malformed_variants(self):  # BK6
        self.assertEqual(self.cmd("apply", git_hooks=False)[0], 0)
        good = self.read("CLAUDE.md")
        begin = good.split("\n")[0]
        end = "<!-- strict-delivery:end -->"
        for bad in (good + "\n" + begin + "\n", good.replace(end, ""), end + "\n" + good.replace(end, ""),
                    good.replace("claude-block/1", "gitignore-block/1"), " " + good, good.replace(end, end + " "),
                    good.replace("version=0.0.0", "version=1.2"), good.replace("-->\n", "-->\r\n", 1)):
            self.write("CLAUDE.md", bad)
            with open(os.path.join(self.root, "CLAUDE.md"), "wb") as fh:
                fh.write(bad.encode("utf-8"))
            before = snapshot(self.root)
            code, out, _ = self.cmd("apply", git_hooks=False)
            self.assertEqual(code, 1, bad)
            self.assertEqual(out.count("CLAUDE.md: managed block malformed"), 1, out)
            self.assertEqual(snapshot(self.root), before)

    def test_blocks_markers_and_bodies(self):  # BK1, BK9, BK12
        from gates.lib import schema, templates
        self.assertEqual(self.cmd("apply")[0], 0)
        c = self.read("CLAUDE.md")
        self.assertTrue(c.startswith("<!-- strict-delivery:begin schema=claude-block/1 version=0.0.0 -->\n"))
        self.assertTrue(c.endswith("<!-- strict-delivery:end -->\n"))
        self.assertIn(templates.claude_block_body(config.DEFAULTS), c)
        g = self.read(".gitignore")
        self.assertTrue(g.startswith("# strict-delivery:begin schema=gitignore-block/1 version=0.0.0\n"))
        self.assertIn(templates.gitignore_block_body(config.DEFAULTS), g)
        for kind, text in (("claude-block", c), ("gitignore-block", g)):
            sch = schema.load_schema(os.path.join(REPO, "gates", "schemas", kind + ".yml"))
            self.assertEqual(schema.validate_managed_block(sch, text), [])

    def test_block_paths_fixed_and_errors(self):  # BK10, BK11, PL5
        seen = []
        real = managed.plan

        def spy(root, writes, version):
            seen.extend((w.path, w.kind) for w in writes)
            return real(root, writes, version)
        with mock.patch.object(managed, "plan", spy):
            self.cmd("plan")
        self.assertIn(("CLAUDE.md", "claude-block"), seen)
        self.assertIn((".gitignore", "gitignore-block"), seen)
        from gates.lib import templates, migrations, schema
        before = snapshot(self.root)
        for target, name, exc in ((templates, "gitignore_block_body", GateError("boom")),
                                  (templates, "claude_block_body", GateError("boom")),
                                  (plugin, "version", GateError("boom")),
                                  (migrations, "current_version", schema.SchemaError("boom")),
                                  (schema, "load_schema", schema.SchemaError("boom"))):
            with mock.patch.object(target, name, side_effect=exc):
                code, out, _ = self.cmd("plan")
            self.assertEqual((code, out), (1, "FAIL init.input: boom\n"), name)
        with mock.patch.object(plugin, "repository_slug", side_effect=GateError("boom")):
            code, out, _ = self.cmd("plan", ci=True)
        self.assertEqual((code, out), (1, "FAIL init.input: boom\n"))
        self.assertEqual(snapshot(self.root), before)

    def test_blocks_non_utf8_and_unreadable(self):  # BK8
        p = self.write("CLAUDE.md", b"\xff", mode="wb")
        code, out, _ = self.cmd("plan")
        self.assertEqual(code, 1)
        self.assertIn("FAIL init.conflict: CLAUDE.md: exists and is not framework-managed", out)
        os.chmod(p, 0)
        self.addCleanup(os.chmod, p, 0o644)
        code, out, _ = self.cmd("plan")
        self.assertEqual((code, out), (1, "FAIL init.input: CLAUDE.md: cannot read (Permission denied)\n"))

    def test_blocks_file_kinds(self):  # BK7
        os.mkdir(os.path.join(self.root, "CLAUDE.md"))
        os.mkfifo(os.path.join(self.root, ".gitignore"))
        code, out, _ = helpers.within(lambda: self.cmd("plan"))
        self.assertEqual(code, 1)
        self.assertIn("CLAUDE.md: exists and is not framework-managed", out)
        self.assertIn(".gitignore: exists and is not framework-managed", out)

    def test_gitignore_plain_duplicates_kept(self):  # BK13
        self.write(".gitignore", "docs/strict-delivery/INDEX.md\n")
        code, out, _ = self.cmd("plan")
        self.assertEqual(code, 0)
        self.assertNotIn("note:", out)
        self.cmd("apply")
        self.assertTrue(self.read(".gitignore").startswith("docs/strict-delivery/INDEX.md\n"))

    def test_blocks_template_paths(self):  # BK9 (changed paths)
        self.init_config(paths={"index": "docs/other/INDEX.md"})
        self.cmd("apply")
        self.assertIn("docs/other/INDEX.md", self.read(".gitignore"))
        self.assertNotIn("docs/strict-delivery/INDEX.md", self.read(".gitignore"))


class TestCiRows(More):
    def fw_checkout(self, version="0.0.0"):
        fw = self.make_fw("fwc", version=version)
        git(fw, "init", "-q", "-b", "main")
        helpers.commit_all(fw, "c")
        return fw

    def ci_run(self, fw, sub="plan"):
        with mock.patch.object(plugin, "framework_dir", return_value=fw):
            return self.cmd(sub, ci=True)

    def test_ci_pin_states(self):  # CI5, CI6, CI7, CI8
        want = "FAIL init.answers: ci: no release tag and no framework commit to pin; answer ci: false until v0.1.0\n"
        outer = self.repo("outer")
        inner = self.make_fw("fwsub", under=outer)
        self.assertEqual(self.ci_run(inner)[1:2], (want,))
        unborn = self.make_fw("unb")
        git(unborn, "init", "-q", "-b", "main")
        self.assertEqual(self.ci_run(unborn)[1], want)
        sha256 = self.make_fw("s256")
        if git(sha256, "init", "-q", "-b", "main", "--object-format=sha256", check=False) == "" and os.path.isdir(os.path.join(sha256, ".git")):
            helpers.commit_all(sha256, "c")
            code, out, _ = self.ci_run(sha256)
            self.assertEqual(code, 1)
            self.assertIn("FAIL init.answers: ci: ", out)
        tagged = self.make_fw("tagged", version="0.1.0")
        with mock.patch.object(init.gitinfo, "head_sha", side_effect=init.GitNotFound("no git")):
            self.assertEqual(self.ci_run(tagged)[0], 0)
        fw = self.fw_checkout()
        sha1 = git(fw, "rev-parse", "HEAD")
        code, out, _ = self.ci_run(fw)
        self.assertEqual(code, 0)
        self.assertIn("git fetch --depth 1 https://github.com/o/r " + sha1, out)
        self.write_in(fw, "n.txt", "n")
        sha2 = helpers.commit_all(fw, "again")
        self.assertEqual(self.ci_run(fw, "apply")[0], 0)
        text = self.read(".github/workflows/strict-delivery.yml")
        self.assertIn(sha2, text)
        self.assertNotIn(sha1, text)

    def test_ci_workflow_states(self):  # CI9, CI10, CI11, CI14, CI15
        wf = ".github/workflows/strict-delivery.yml"
        fw = self.make_fw("f1", version="0.1.0")
        with mock.patch.object(plugin, "framework_dir", return_value=fw):
            self.assertEqual(self.cmd("apply", ci=True)[0], 0)
            self.assertEqual(self.cmd("plan", ci=True)[1], "no changes\n")
        self.assertTrue(os.path.isdir(os.path.join(self.root, ".github", "workflows")))
        fw2 = self.make_fw("f2", version="0.2.0")
        with mock.patch.object(plugin, "framework_dir", return_value=fw2):
            code, out, _ = self.cmd("plan", ci=True)
        self.assertEqual(code, 0)
        self.assertIn("note: %s: present at version v0.1.0; run /strict-delivery:upgrade" % wf, out)
        before = self.read(wf)
        with mock.patch.object(plugin, "framework_dir", return_value=fw2):
            self.cmd("apply", ci=True)
        self.assertEqual(self.read(wf), before)

    def test_ci_path_states(self):  # CI11
        wf = os.path.join(self.root, ".github", "workflows", "strict-delivery.yml")
        for setup, text in ((lambda: os.mkdir(wf), "%s: exists and is not framework-managed"),
                            (lambda: os.symlink(os.path.join(self.root, "README.md"), wf), "%s: is a symlink"),
                            (lambda: os.symlink(os.path.join(self.tmp, "no"), wf), "%s: is a symlink"),
                            (lambda: os.mkfifo(wf), "%s: exists and is not framework-managed")):
            os.makedirs(os.path.dirname(wf), exist_ok=True)
            if os.path.lexists(wf):
                os.rmdir(wf) if os.path.isdir(wf) and not os.path.islink(wf) else os.unlink(wf)
            setup()
            code, out, _ = helpers.within(lambda: self.cmd("plan", ci=True))
            self.assertEqual(code, 1)
            self.assertIn(text % ".github/workflows/strict-delivery.yml", out)
        os.unlink(wf)
        os.rmdir(os.path.dirname(wf))
        os.rmdir(os.path.dirname(os.path.dirname(wf)))
        self.write(".github", "f")
        code, out, _ = self.cmd("plan", ci=True)
        self.assertIn("parent .github is not a directory", out)

    def test_ci_repository_slug(self):  # CI13, CI14
        fw = self.make_fw("norepo", version="0.1.0", repository=None)
        with mock.patch.object(plugin, "framework_dir", return_value=fw):
            self.assertEqual(self.cmd("plan")[0], 0)
            code, out, _ = self.cmd("plan", ci=True)
        self.assertEqual(code, 1)
        self.assertTrue(out.startswith("FAIL init.input: "), out)
        fw = self.make_fw("withrepo", version="0.1.0")
        with mock.patch.object(plugin, "framework_dir", return_value=fw):
            self.assertIn("https://github.com/o/r v0.1.0", self.cmd("plan", ci=True)[1])

    def test_plugin_manifest_states(self):  # FS8
        before = snapshot(self.root)
        base = {"name": "x", "version": "0.1.0", "repository": "https://github.com/o/r"}
        cases = (b"", b"\xff", b"not json", b'{"version": "0.1.0", "version": "0.1.0"}', b'{"version": NaN}',
                 b'{"version": 1' + b"0" * 4300 + b"}", b"[]", b'{"name": "x"}', b'{"version": "1.0"}',
                 json.dumps(dict(base, repository="nope")).encode())
        for i, data in enumerate(cases):
            fw = os.path.join(self.tmp, "m%d" % i)
            os.makedirs(os.path.join(fw, ".claude-plugin"))
            with open(os.path.join(fw, ".claude-plugin", "plugin.json"), "wb") as fh:
                fh.write(data)
            with mock.patch.object(plugin, "framework_dir", return_value=fw):
                code, out, _ = self.cmd("plan", ci=True)
            self.assertEqual(code, 1, data)
            self.assertTrue(out.startswith("FAIL init.input: "), (data, out))
        for setup in (lambda p: os.mkdir(p), lambda p: None):
            fw = os.path.join(self.tmp, "mm%d" % id(setup))
            os.makedirs(os.path.join(fw, ".claude-plugin"))
            setup(os.path.join(fw, ".claude-plugin", "plugin.json"))
            with mock.patch.object(plugin, "framework_dir", return_value=fw):
                self.assertEqual(self.cmd("plan")[0], 1)
        self.assertEqual(snapshot(self.root), before)


class TestHookRows(More):
    def hooks_dir(self):
        return os.path.join(self.root, ".git", "hooks")

    def test_hooks_hookspath_values(self):  # HK5
        for value in ("/abs/elsewhere", "rel/path", ""):
            git(self.root, "config", "core.hooksPath", value)
            code, out, _ = self.cmd("plan")
            self.assertEqual(code, 1)
            self.assertIn("FAIL init.conflict: core.hooksPath is set (%s); unset it to install the hooks" % value, out)
        git(self.root, "config", "--unset", "core.hooksPath")
        env = {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "core.hooksPath", "GIT_CONFIG_VALUE_0": "viaenv"}
        with mock.patch.dict(os.environ, env):
            code, out, _ = self.cmd("plan")
        self.assertEqual(code, 1)
        self.assertIn("core.hooksPath is set (viaenv)", out)

    def test_hooks_false_touches_nothing(self):  # HK2
        os.makedirs(self.hooks_dir(), exist_ok=True)
        self.write_in(self.root, ".git/hooks/pre-commit", "#!/bin/sh\necho mine\n")
        git(self.root, "config", "core.hooksPath", "elsewhere")
        before = snapshot(self.root)
        code, out, _ = self.cmd("plan", git_hooks=False)
        self.assertEqual(code, 0)
        self.assertNotIn("hook ", out)
        self.assertEqual(self.cmd("apply", git_hooks=False)[0], 0)
        self.assertEqual(self.read(".git/hooks/pre-commit"), "#!/bin/sh\necho mine\n")

    def test_hooks_foreign_kinds(self):  # HK4
        os.makedirs(self.hooks_dir(), exist_ok=True)
        for name, setup in (("pre-commit", lambda p: os.mkdir(p)), ("pre-push", lambda p: os.symlink(self.tmp, p))):
            setup(os.path.join(self.hooks_dir(), name))
        code, out, _ = self.cmd("plan")
        self.assertEqual(code, 1)
        self.assertIn("FAIL init.conflict: githooks.pre-commit: foreign", out)
        self.assertIn("FAIL init.conflict: githooks.pre-push: foreign", out)

    def test_hooks_framework_path_and_modes(self):  # HK3, HK1, AP12, HK7, ID3
        fw = self.make_fw("otherfw", version="0.3.0")
        with mock.patch.object(plugin, "framework_dir", return_value=fw):
            self.assertEqual(self.cmd("apply")[0], 0)
        real = os.path.realpath(REPO)
        for name in githooks.NAMES:
            p = os.path.join(self.hooks_dir(), name)
            with open(p, encoding="utf-8") as fh:
                text = fh.read()
            self.assertIn(real, text)
            self.assertNotIn(fw, text)
            self.assertEqual(os.stat(p).st_mode & 0o777, 0o755)
        with open(os.path.join(self.hooks_dir(), "pre-commit"), "rb") as fh:
            data = fh.read()
        with mock.patch.object(plugin, "framework_dir", return_value=fw):
            self.assertEqual(self.cmd("apply")[0], 0)
        with open(os.path.join(self.hooks_dir(), "pre-commit"), "rb") as fh:
            self.assertEqual(fh.read(), data)

    def test_hooks_stale_shim(self):  # HK6
        os.makedirs(self.hooks_dir(), exist_ok=True)
        stale = githooks.shim("pre-commit", "/other/fw")
        p = os.path.join(self.hooks_dir(), "pre-commit")
        with open(p, "wb") as fh:
            fh.write(stale)
        os.chmod(p, 0o644)
        code, out, _ = self.cmd("plan")
        self.assertEqual(code, 0)
        self.assertIn("note: %s: present and stale; run /strict-delivery:upgrade" % p, out)
        self.assertEqual(out.count("hook "), 1)
        self.cmd("apply")
        with open(p, "rb") as fh:
            self.assertEqual(fh.read(), stale)
        self.assertTrue(os.path.exists(os.path.join(self.hooks_dir(), "pre-push")))

    def test_hooks_dir_states(self):  # HK8, HK12, AP4 (c)
        tpl = self.repo("tpl", commit=False, flags=("--template=",))
        self.assertFalse(os.path.exists(os.path.join(tpl, ".git", "hooks")))
        self.put_answers()
        self.assertEqual(self.run_init("apply", "--root", tpl, "--answers", self.ans)[0], 0)
        self.assertTrue(os.path.exists(os.path.join(tpl, ".git", "hooks", "pre-commit")))
        target = os.path.join(self.tmp, "hook-link-target")
        os.makedirs(target)
        # CD17 (run 11): a hooks directory that is a link, to a directory or dangling, is a conflict
        for name, setup in (("hf", lambda p: touch(p)), ("hd", lambda p: os.symlink(os.path.join(self.tmp, "none"), p)),
                            ("hl", lambda p: os.symlink(target, p))):
            r = self.repo(name, commit=False, flags=("--template=",))
            h = os.path.join(r, ".git", "hooks")
            setup(h)
            code, out, _ = self.run_init("plan", "--root", r, "--answers", self.ans)
            self.assertEqual(code, 1, out)
            self.assertIn("FAIL init.conflict: %s: exists and is not a directory" % h, out)
            before = snapshot(r)
            self.assertEqual(self.run_init("apply", "--root", r, "--answers", self.ans)[0], 1)
            self.assertEqual(snapshot(r), before, name)
            self.assertEqual(os.listdir(target), [], name)
        ro = self.repo("ro", commit=False)
        os.chmod(os.path.join(ro, ".git", "hooks"), 0o555)
        self.addCleanup(os.chmod, os.path.join(ro, ".git", "hooks"), 0o755)
        code, out, _ = self.run_init("apply", "--root", ro, "--answers", self.ans)
        self.assertEqual(code, 1)
        self.assertIn("FAIL init.write: %s: cannot write (Permission denied)\nwritten: " % os.path.join(ro, ".git", "hooks", "pre-commit"), out)
        self.assertTrue(os.path.exists(os.path.join(ro, "CLAUDE.md")))
        self.assertEqual([n for n in os.listdir(os.path.join(ro, ".git", "hooks")) if n.startswith(".sd")], [])

    def test_hooks_bad_framework_path(self):  # HK9
        before = snapshot(self.root)
        for bad in ("rel/path", "/a\nb"):
            with mock.patch.object(githooks, "framework_dir", return_value=bad):
                code, out, _ = self.cmd("apply")
            self.assertEqual(code, 1, bad)
            self.assertTrue(out.startswith("FAIL init.input: "), out)
            self.assertEqual(snapshot(self.root), before)

    def test_plan_prints_hooks(self):  # HK14
        code, out, _ = self.cmd("plan")
        self.assertIn("hook %s\nhook %s\n" % (os.path.join(self.hooks_dir(), "pre-commit"),
                                              os.path.join(self.hooks_dir(), "pre-push")), out)


class TestSettingsRows(More):
    def sp(self):
        return os.path.join(self.root, ".claude", "settings.json")

    def test_settings_one_key_and_none(self):  # ST2, ST3, ST20
        self.assertEqual(self.cmd("apply", subagents={"depth": 5}, git_hooks=False)[0], 0)
        self.assertEqual(json.loads(self.read(".claude/settings.json")), {"env": {ENV_D: "5"}})
        plan = init.plan_init(self.root, answers(subagents={"concurrent": 30}))
        self.assertEqual(plan.settings[0], "conflict")
        plan = init.plan_init(self.root, answers(subagents={}))
        self.assertIsNone(plan.settings)
        self.assertIsNone(init.plan_init(self.root, answers(subagents={"depth": 5})).settings)

    def test_settings_empty_no_change(self):  # ST3
        os.makedirs(os.path.join(self.root, ".claude"))
        code, out, _ = self.raw(self.raw_with(subagents=""), "apply")
        self.assertEqual(code, 0, out)
        self.assertFalse(os.path.exists(self.sp()))

    def test_settings_plan_field(self):  # ST20, ST1, ST21
        fresh = init.plan_init(self.root, answers())
        text = '{\n  "env": {\n    "%s": "30",\n    "%s": "5"\n  }\n}\n' % (ENV_C, ENV_D)
        self.assertEqual(fresh.settings, ("create", text))
        self.assertIn((".claude/settings.json", text), [(w.path, w.text) for w in fresh.writes])
        self.write(".claude/settings.json", "{}")
        plan = init.plan_init(self.root, answers())
        self.assertEqual(plan.settings, ("conflict", '.claude/settings.json: add "env"."%s": "30"; '
                                                     '.claude/settings.json: add "env"."%s": "5"' % (ENV_C, ENV_D)))
        self.assertEqual(plan.writes, [])
        self.assertEqual(len([c for c in plan.conflicts if c.startswith(".claude")]), 2)
        os.unlink(self.sp())
        self.cmd("apply")
        with open(self.sp(), "rb") as fh:
            raw = fh.read()
        self.assertEqual((raw.isascii(), b"\r" in raw, raw.endswith(b"\n\n")), (True, False, False))
        self.assertEqual(os.stat(self.sp()).st_mode & 0o777, 0o666 & ~umask())

    def test_settings_value_types_and_names(self):  # ST6, ST7, ST8
        for v in (5, 5.0, "05", " 5", "5 ", True, None, ["5"], {"a": 1}):
            self.write(".claude/settings.json", json.dumps({"env": {ENV_D: v, ENV_C: "30"}}))
            code, out, _ = self.cmd("plan")
            self.assertEqual(code, 1, v)
            self.assertIn('set "env"."%s" to "5"' % ENV_D, out)
            self.assertNotIn(ENV_C, out)
        self.write(".claude/settings.json", json.dumps({"env": {ENV_D.lower(): "5", ENV_D + " ": "5", ENV_C: "30"}}))
        code, out, _ = self.cmd("plan")
        self.assertIn('add "env"."%s": "5"' % ENV_D, out)
        self.write(".claude/settings.json", json.dumps({"top": 1}))
        self.assertEqual(self.cmd("plan")[1].count('add "env"'), 2)

    def test_settings_bad_files(self):  # ST9, ST12, ST14, ST15, ST16, ST17, VR7
        for text in ("{", '{"a":1,}', "[1,]", "{'a': 1}", "// x\n{}", "{} x", "", "  \n", '{"a": "\x00"}'):
            self.write(".claude/settings.json", text)
            code, out, _ = self.cmd("plan")
            self.assertEqual(code, 1, text)
            self.assertIn("FAIL init.conflict: .claude/settings.json: is not valid JSON\n", out)
        for data, want in ((b"\xef\xbb\xbf{}", "is not valid JSON"), (b"\xff\xfe", "is not valid UTF-8"),
                           ("{}".encode("utf-16"), "is not valid UTF-8")):
            self.write(".claude/settings.json", data, mode="wb")
            self.assertIn(".claude/settings.json: " + want, self.cmd("plan")[1])
        os.unlink(self.sp())
        os.mkdir(self.sp())
        self.assertIn(".claude/settings.json: exists and is not a regular file", self.cmd("plan")[1])
        os.rmdir(self.sp())
        os.mkfifo(self.sp())
        self.assertIn(".claude/settings.json: exists and is not a regular file",
                      helpers.within(lambda: self.cmd("plan"))[1])
        os.unlink(self.sp())
        os.symlink(os.path.join(self.tmp, "none"), self.sp())
        self.assertIn(".claude/settings.json: is a symlink", self.cmd("plan")[1])
        os.unlink(self.sp())
        self.write(".claude/settings.json", "{}")
        os.chmod(self.sp(), 0)
        self.addCleanup(os.chmod, self.sp(), 0o644)
        self.assertEqual(self.cmd("plan")[1], "FAIL init.input: .claude/settings.json: cannot read (Permission denied)\n")
        os.chmod(self.sp(), 0o644)
        os.unlink(self.sp())
        os.rmdir(os.path.dirname(self.sp()))
        self.write(".claude", "f")
        self.assertIn(".claude/settings.json: parent .claude is not a directory", self.cmd("plan")[1])
        os.unlink(os.path.join(self.root, ".claude"))
        os.symlink(self.tmp, os.path.join(self.root, ".claude"))
        self.assertIn("parent .claude is not a directory", self.cmd("plan")[1])
        os.unlink(os.path.join(self.root, ".claude"))
        self.write(".claude/settings.local.json", "{not json")
        local = snapshot(os.path.join(self.root, ".claude"))
        self.cmd("apply")
        self.assertEqual(self.read(".claude/settings.local.json"), "{not json")

    def test_settings_numerals_and_large(self):  # ST13, ST18, VR1 (b), VR2 (b)
        for lim in helpers.INT_LIMITS:
            with helpers.int_limit(lim):
                self.write(".claude/settings.json", '{"a": %s}' % ("1" * 4300))
                self.assertIn(' add "env"', self.cmd("plan")[1])
                self.write(".claude/settings.json", '{"a": %s}' % ("1" * 4301))
                self.assertIn(".claude/settings.json: an integer of more than 4300 digits is not allowed", self.cmd("plan")[1])
        self.write(".claude/settings.json", json.dumps({"pad": "x" * 10_000_000, "env": {ENV_D: "5", ENV_C: "30"}}))
        code, out, _ = self.cmd("plan", git_hooks=False)
        self.assertEqual(code, 0)
        self.assertNotIn("settings.json", out)

    def test_settings_dups_inside_env(self):  # ST10
        self.write(".claude/settings.json", '{"env": {"A": "1", "A": "2"}}')
        self.assertIn("duplicate key", self.cmd("plan")[1])
        for c in ("Infinity", "-Infinity"):
            self.write(".claude/settings.json", '{"a": %s}' % c)
            self.assertEqual(self.cmd("plan")[0], 1)


class TestPlanApplyRows(More):
    def test_initplan_fields(self):  # PL1, AP14
        import dataclasses
        plan = init.plan_init(self.root, answers())
        self.assertEqual([f.name for f in dataclasses.fields(plan)], ["writes", "conflicts", "settings", "moves",
                                                                     "host_calls", "notes", "host_error"])  # Q12
        self.assertEqual((plan.moves, plan.host_calls, plan.host_error), ([], [], None))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            plan.writes = []
        n = len(plan.writes)
        plan.writes.append(1)
        self.assertEqual(len(init.plan_init(self.root, answers()).writes), n)
        self.assertTrue(all(type(x) is str for x in plan.notes + plan.conflicts))

    def test_plan_pure_and_deterministic(self):  # PL2, ID4
        idx = git(self.root, "ls-files", "-s")
        before = snapshot(self.root)
        first = self.cmd("plan")
        self.assertEqual(first, self.cmd("plan"))
        self.assertEqual(snapshot(self.root), before)
        self.assertEqual(git(self.root, "ls-files", "-s"), idx)

    def test_all_conflicts_listed_in_order(self):  # PL3, PL4, PO2
        os.symlink(os.path.join(self.root, "README.md"), os.path.join(self.root, "CLAUDE.md"))
        self.write(".github/workflows/strict-delivery.yml", "name: mine\n")
        self.write(".claude/settings.json", SETTINGS_ORIGINAL)
        self.write(".strict-delivery/state/claims", "f")
        os.makedirs(self.hooks_path(), exist_ok=True)
        self.write(".git/hooks/pre-push", "#!/bin/sh\n")
        code, out, _ = self.cmd("plan", ci=True)
        self.assertEqual(code, 1)
        self.assertNotIn("--- a/", out)
        lines = out.split("\n")[:-1]
        self.assertTrue(all(l.startswith("FAIL init.conflict: ") for l in lines), out)
        keys = [".strict-delivery/state/claims:", "CLAUDE.md: is a symlink", ".github/workflows/strict-delivery.yml:",
                '.claude/settings.json: set "env"', "githooks.pre-push: foreign"]
        pos = [out.index(k) for k in keys]
        self.assertEqual(pos, sorted(pos), out)
        plan = init.plan_init(self.root, answers(ci=True))
        self.assertEqual((plan.writes, len(plan.conflicts) >= 5), ([], True))

    def hooks_path(self):
        return os.path.join(self.root, ".git", "hooks")

    def test_plan_order_and_diffs(self):  # PL6, PO3, PO11, DR10
        code, out, _ = self.cmd("plan", ci=True)
        self.assertEqual(code, 0)
        marks = ["--- a/.strict-delivery/config.yml\n+++ b/.strict-delivery/config.yml\n", "mkdir .strict-delivery/state/\n",
                 "--- a/CLAUDE.md\n+++ b/CLAUDE.md\n", "--- a/.gitignore\n+++ b/.gitignore\n",
                 "--- a/.github/workflows/strict-delivery.yml\n+++ b/.github/workflows/strict-delivery.yml\n",
                 "--- a/.claude/settings.json\n+++ b/.claude/settings.json\n",
                 "--- a/.strict-delivery/context.yml\n+++ b/.strict-delivery/context.yml\n", "\nhook /"]
        pos = [out.index(m) for m in marks]
        self.assertEqual(pos, sorted(pos), out)
        self.assertIn("@@ -0,0 +1,10 @@\n+schema: config/2\n", out)
        self.assertEqual(out.count("mkdir .strict-delivery/state/\n"), 1)

    def test_plan_diff_splits_on_lf_only(self):  # PO4, PO5, PO8, PO9, VR9
        self.write("CLAUDE.md", "p\x0bq\x1cr\x85s t\ru\nline é\nlast")
        code, out, _ = self.cmd("plan")
        self.assertEqual(code, 0)
        lines = out.split("\n")
        hit = [l for l in lines if l.startswith(" p")]
        self.assertEqual(len(hit), 1, out)
        self.assertTrue(hit[0].endswith("u"), hit)
        for esc in ("\\x0b", "\\x1c", "\\x85", "\\u2028", "\\r"):
            self.assertIn(esc, hit[0])
        self.assertIn(" line é", lines)
        i = lines.index(" line é")
        self.assertEqual(lines[i + 1:i + 3], ["-last", "+last"])
        self.assertNotIn("No newline", out)

    def test_plan_notes_after_actions(self):  # PO7
        wt = os.path.join(self.tmp, "wt2")
        git(self.root, "worktree", "add", "-q", wt, "-b", "o2")
        code, out, _ = self.cmd("plan", root=wt)
        self.assertEqual(code, 0)
        lines = out.split("\n")[:-1]
        self.assertTrue(lines[-1].startswith("note: hooks go to "))
        self.assertTrue(all(not l.startswith("note:") for l in lines[:-1]))

    def test_apply_prints_status_exactly(self):  # AP6, AP9, AP12
        code, out, _ = self.cmd("apply", ci=True)
        self.assertEqual(code, 0, out)
        self.assertEqual(out, "?? .claude/settings.json\n?? .github/workflows/strict-delivery.yml\n?? .gitignore\n"
                              "?? .strict-delivery/config.yml\n?? .strict-delivery/context.yml\n?? CLAUDE.md\n")
        code, out, _ = self.cmd("apply", ci=True)
        self.assertEqual(code, 0)
        self.assertEqual(out, "no changes\n?? .claude/settings.json\n?? .github/workflows/strict-delivery.yml\n"
                              "?? .gitignore\n?? .strict-delivery/config.yml\n?? .strict-delivery/context.yml\n"
                              "?? CLAUDE.md\n")
        for rel in (".strict-delivery/config.yml", "CLAUDE.md", ".gitignore", ".claude/settings.json"):
            self.assertEqual(os.stat(os.path.join(self.root, rel)).st_mode & 0o777, 0o666 & ~umask(), rel)

    def test_apply_status_call_form(self):  # AP6, CD10
        real = init.gitinfo._run
        calls = []

        def run(root, label, *a, **kw):
            if label == "status --porcelain":
                calls.append((a, kw))
            return real(root, label, *a, **kw)
        with mock.patch.object(init.gitinfo, "_run", run):
            self.assertEqual(self.cmd("apply")[0], 0)
        (args, kw), = calls
        self.assertEqual(args[0], ["status", "--porcelain=v1", "--untracked-files=all", "--ignored=no", "--no-renames",
                                   "--ignore-submodules=none"])
        self.assertEqual(kw["extra_env"], {"GIT_OPTIONAL_LOCKS": "0"})
        self.assertEqual(kw["opts"], init.gitinfo.FSMONITOR_OFF)

    def test_apply_status_failure(self):  # AP10
        real = init.gitinfo._run

        def run(root, label, *a, **kw):
            if label == "status --porcelain":
                raise GateError("boom")
            return real(root, label, *a, **kw)
        with mock.patch.object(init.gitinfo, "_run", run):
            code, out, _ = self.cmd("apply")
        self.assertEqual((code, out), (1, "FAIL init.status: boom\n"))
        self.assertTrue(os.path.exists(os.path.join(self.root, "CLAUDE.md")))

    def test_apply_failure_modes(self):  # AP4 (d), (e)
        with mock.patch.object(os, "write", side_effect=OSError(28, "No space left on device")):
            code, out, _ = self.cmd("apply")
        self.assertEqual(code, 1)
        self.assertIn("FAIL init.write: ", out)
        self.assertEqual([n for d, _, fs in os.walk(self.root) for n in fs if n.startswith(".sd-")], [])
        with mock.patch.object(os, "replace", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.cmd("apply")
        self.assertEqual([n for d, _, fs in os.walk(self.root) for n in fs if n.startswith(".sd-")], [])

    def test_apply_after_partial_run_completes(self):  # IN4, AP5
        real = managed.apply

        def boom(root, actions):
            if any(a[0] == "CLAUDE.md" for a in actions):
                raise managed.ManagedError("CLAUDE.md: cannot write (Permission denied)")
            return real(root, actions)
        with mock.patch.object(managed, "apply", boom):
            self.assertEqual(self.cmd("apply")[0], 1)
        cfg = self.read(".strict-delivery/config.yml")
        m = os.stat(os.path.join(self.root, ".strict-delivery", "config.yml")).st_mtime_ns
        self.assertIs(init.questions(self.root)["initialised"], True)
        self.assertEqual(self.cmd("apply")[0], 0)
        self.assertEqual(self.read(".strict-delivery/config.yml"), cfg)
        self.assertEqual(os.stat(os.path.join(self.root, ".strict-delivery", "config.yml")).st_mtime_ns, m)
        self.assertTrue(os.path.exists(os.path.join(self.root, "CLAUDE.md")))

    def test_apply_never_stages(self):  # AP7
        head = git(self.root, "rev-parse", "HEAD")
        idx = git(self.root, "ls-files", "-s")
        refs = git(self.root, "for-each-ref")
        self.cmd("apply", ci=True)
        self.assertEqual((git(self.root, "rev-parse", "HEAD"), git(self.root, "ls-files", "-s"),
                          git(self.root, "for-each-ref")), (head, idx, refs))
        self.assertEqual(git(self.root, "diff", "--cached", "--name-only"), "")

    def test_questions_write_nothing_linked(self):  # QS1
        wt = os.path.join(self.tmp, "wt3")
        git(self.root, "worktree", "add", "-q", wt, "-b", "o3")
        fresh = self.repo("fresh", commit=False)
        for r in (wt, fresh):
            before = snapshot(r)
            self.assertEqual(self.run_init("questions", "--root", r)[0], 0)
            self.assertEqual(snapshot(r), before)

    def test_questions_git_calls_read_only(self):  # QS1 (m11)
        seen = []
        real = init.gitinfo._run

        def run(root, label, args, *a, **kw):
            seen.append((label, args))
            return real(root, label, args, *a, **kw)
        with mock.patch.object(init.gitinfo, "_run", run):
            init.questions(self.root)
        self.assertTrue(all(args[0] in ("rev-parse", "ls-files", "config") for _, args in seen), seen)

    def test_unicode_numeric_in_source(self):  # VR10, VR11
        with open(os.path.join(REPO, "gates", "tools", "init.py"), encoding="utf-8") as fh:
            src = fh.read()
        for bad in ("isdigit", "isdecimal", "isalnum", "isnumeric", "casefold", "unicodedata", "except*"):
            self.assertNotIn(bad, src)


HELP_BODY = {
    "plan": "usage: init plan [-h] [--root ROOT] [--answers ANSWERS] [--json]\n\noptional arguments:\n"
            "  -h, --help         show this help message and exit\n  --root ROOT\n  --answers ANSWERS\n  --json\n",
    "apply": "usage: init apply [-h] [--root ROOT] [--answers ANSWERS] [--json]\n\noptional arguments:\n"
             "  -h, --help         show this help message and exit\n  --root ROOT\n  --answers ANSWERS\n  --json\n",
    "questions": "usage: init questions [-h] [--root ROOT] [--answers ANSWERS] [--json]\n\noptional arguments:\n"
                 "  -h, --help         show this help message and exit\n  --root ROOT\n  --answers ANSWERS\n  --json\n",
}
STATE_KEYS = ("decisions", "findings", "claims", "plan_state", "programs", "playbooks")
TOP = "top level is not an object"
ENV_NOT_OBJ = "env is not an object"


class TestReview1(More):
    """Round 1 of the 4d.1 review: findings F-20261124-x78m azfq 4vka i5nc 9vua 6b3i rda6 zs4z 4xja."""

    # --- R1-1 (x78m): ST11 -------------------------------------------------------------------------------------
    def test_settings_shape_conflicts(self):  # ST11
        for text, want in (("[]", TOP), ('"x"', TOP), ("5", TOP), ("null", TOP), ("true", TOP),
                           ('{"env": null}', ENV_NOT_OBJ), ('{"env": []}', ENV_NOT_OBJ),
                           ('{"env": "x"}', ENV_NOT_OBJ), ('{"env": 5}', ENV_NOT_OBJ)):
            self.write(".claude/settings.json", text)
            before = snapshot(self.root)
            for sub in ("plan", "apply"):
                code, out, _ = self.cmd(sub, git_hooks=False)
                self.assertEqual((code, out), (1, "FAIL init.conflict: .claude/settings.json: %s\n" % want),
                                 (sub, text))
            self.assertEqual(snapshot(self.root), before, text)

    # --- R1-2 (azfq) and R1-3 (4vka): QS11/ST19 through questions ----------------------------------------------
    def test_questions_settings_unusable_states(self):  # QS11, ST19
        src = ".claude/settings.json"
        cases = (
            (b"{", "is not valid JSON"),
            (b'{"env": {}, "env": {}}', "duplicate key 'env'"),
            (b'{"a": NaN}', "the constant NaN is not allowed"),
            (b"\xef\xbb\xbf{}", "is not valid JSON"),
            (b'{"a": %s}' % (b"1" * 4301), "an integer of more than 4300 digits is not allowed"),
        )
        p = os.path.join(self.root, ".claude", "settings.json")
        for lim in helpers.INT_LIMITS:
            with helpers.int_limit(lim):
                for data, reason in cases:
                    self.write(".claude/settings.json", data, "wb")
                    q = init.questions(self.root)
                    self.assertEqual((q["subagents"], q["problems"]),
                                     ({"current": None}, [{"source": src, "reason": reason}]), (lim, data[:20]))
        self.write(".claude/settings.json", b"{}", "wb")
        os.chmod(p, 0)
        self.addCleanup(os.chmod, p, 0o644)
        q = init.questions(self.root)
        self.assertEqual((q["subagents"], q["problems"]),
                         ({"current": None}, [{"source": src, "reason": "cannot read (Permission denied)"}]))
        os.chmod(p, 0o644)
        self.write(".claude/settings.json", json.dumps({"env": {ENV_D: "5"}}))
        q = init.questions(self.root)
        self.assertEqual((q["subagents"], q["problems"]), ({"current": {ENV_D: "5"}}, []))

    def test_questions_detect_reasons_repeat_no_path(self):  # R1-3 class: detect problems
        p = os.path.join(self.root, "package.json")
        self.write("package.json", b'{"scripts": {}}', "wb")
        os.chmod(p, 0)
        self.addCleanup(os.chmod, p, 0o644)
        q = init.questions(self.root)
        self.assertEqual(q["problems"], [{"source": "package.json", "reason": "Permission denied"}])

    # --- R1-4 (i5nc): one line per conflict --------------------------------------------------------------------
    def test_conflicts_listed_once(self):  # PL3, PO2
        os.symlink(self.tmp, os.path.join(self.root, ".strict-delivery"))
        want = [".strict-delivery/config.yml: parent .strict-delivery is not a directory", ".strict-delivery: is a symlink",
                ".strict-delivery/context.yml: parent .strict-delivery is not a directory"]
        self.assertEqual(init.plan_init(self.root, answers()).conflicts, want)
        code, out, _ = self.cmd("plan")
        self.assertEqual((code, out), (1, "".join("FAIL init.conflict: %s\n" % c for c in want)))

    def test_conflicts_listed_once_file_parent(self):  # PL3, PO2 (non-directory branch)
        self.write(".strict-delivery/state", "f")
        self.init_config()
        want = [".strict-delivery/state: exists and is not a directory"]
        self.assertEqual(init.plan_init(self.root, answers()).conflicts, want)
        code, out, _ = self.cmd("apply")
        self.assertEqual((code, out), (1, "FAIL init.conflict: .strict-delivery/state: exists and is not a directory\n"))

    def test_conflicts_two_distinct_children_kept(self):  # PL3: distinct conflicts are all kept
        self.init_config()
        os.makedirs(os.path.join(self.root, ".strict-delivery", "state"))
        self.write(".strict-delivery/state/decisions", "f")
        os.symlink(self.tmp, os.path.join(self.root, ".strict-delivery", "state", "claims"))
        self.assertEqual(init.plan_init(self.root, answers()).conflicts,
                         [".strict-delivery/state/decisions: exists and is not a directory",
                          ".strict-delivery/state/claims: is a symlink"])

    # --- R1-5 (9vua): init.write names the path ---------------------------------------------------------------
    def test_mkdir_failure_names_path(self):  # AP4 (a)
        self.init_config()
        os.chmod(os.path.join(self.root, ".strict-delivery"), 0o555)
        self.addCleanup(os.chmod, os.path.join(self.root, ".strict-delivery"), 0o755)
        code, out, _ = self.cmd("apply")
        self.assertEqual((code, out), (1, "FAIL init.write: .strict-delivery/state: cannot create (Permission denied)\n"
                                          "written: \n"))

    def test_hooks_dir_create_failure_names_path(self):  # AP4 (c)
        r = self.repo("nohooks", commit=False, flags=("--template=",))
        self.put_answers()
        hooks = os.path.join(r, ".git", "hooks")
        os.chmod(os.path.join(r, ".git"), 0o555)
        self.addCleanup(os.chmod, os.path.join(r, ".git"), 0o755)
        code, out, _ = self.run_init("apply", "--root", r, "--answers", self.ans)
        self.assertEqual(code, 1)
        self.assertIn("FAIL init.write: %s: cannot create (Permission denied)\nwritten: " % hooks, out)

    def test_hook_write_failure_names_path(self):  # AP4 (c), HK12
        hook = os.path.join(self.root, ".git", "hooks", "pre-commit")
        os.makedirs(os.path.dirname(hook), exist_ok=True)
        os.chmod(os.path.dirname(hook), 0o555)
        self.addCleanup(os.chmod, os.path.dirname(hook), 0o755)
        code, out, _ = self.cmd("apply")
        self.assertEqual(code, 1)
        self.assertIn("FAIL init.write: %s: cannot write (Permission denied)\nwritten: " % hook, out)
        os.chmod(os.path.dirname(hook), 0o755)
        for err, reason in ((OSError(28, "No space left on device"), "No space left on device"), (OSError("boom"), "OSError")):
            with mock.patch.object(githooks, "_write", side_effect=err):
                code, out, _ = self.cmd("apply")
            self.assertEqual(code, 1)
            self.assertIn("FAIL init.write: %s: cannot write (%s)\nwritten: " % (hook, reason), out)

    # --- R1-6 (6b3i): written: lists every file written ---------------------------------------------------------
    def test_written_lists_files_of_a_failed_group(self):  # AP4 (b), CD18
        real = managed._write

        def fail_gitignore(root, path, text):
            if path == ".gitignore":
                raise OSError(13, "Permission denied")
            return real(root, path, text)
        with mock.patch.object(managed, "_write", fail_gitignore):
            code, out, _ = self.cmd("apply")
        self.assertEqual(code, 1)
        dirs = ", ".join(".strict-delivery/%s/" % d for d in ("state", "state/decisions", "state/findings", "state/claims",
                                                              "state/plans", "state/programs", "playbooks"))
        self.assertEqual(out, "FAIL init.write: .gitignore: cannot write (Permission denied)\n"
                              "written: .strict-delivery/config.yml, %s, CLAUDE.md\n" % dirs)
        self.assertTrue(os.path.exists(os.path.join(self.root, "CLAUDE.md")))

    # --- R1-7 (rda6): notes after no changes -------------------------------------------------------------------
    def stale_block(self):
        self.assertEqual(self.cmd("apply")[0], 0)
        text = self.read("CLAUDE.md")
        version = plugin.version(plugin.framework_dir())
        self.assertIn(version, text)
        self.write("CLAUDE.md", text.replace(version, "90.0.0"))
        return "note: CLAUDE.md: present at version 90.0.0; run /strict-delivery:upgrade\n"

    def test_plan_no_changes_then_notes(self):  # PO6, PO7, D-Q5 (a)
        note = self.stale_block()
        before = snapshot(self.root)
        self.assertEqual(self.cmd("plan"), (0, "no changes\n" + note, ""))
        self.assertEqual(snapshot(self.root), before)

    def test_apply_no_changes_then_notes(self):  # PO6, PO7, D-Q5 (a)
        note = self.stale_block()
        before = snapshot(self.root)
        code, out, _ = self.cmd("apply")
        self.assertEqual(code, 0)
        self.assertTrue(out.startswith("no changes\n" + note + "?? "), out)
        self.assertEqual(out.count("note:"), 1)
        self.assertEqual(snapshot(self.root), before)

    def test_second_run_prints_exactly_no_changes(self):  # PO6, IN3: no note, nothing else
        self.assertEqual(self.cmd("apply")[0], 0)
        self.assertEqual(self.cmd("plan"), (0, "no changes\n", ""))

    # --- R1-8 (zs4z): VR8 --help text ---------------------------------------------------------------------------
    def test_help_text_same_on_both(self):  # VR8
        for sub, want in HELP_BODY.items():
            code, out, err = self.run_init(sub, "--help")
            # "options:" on 3.10+, "optional arguments:" on 3.9: _GateParser's, family-wide (tests/test_argparse_text.py)
            text = err.replace("\noptions:\n", "\noptional arguments:\n")
            self.assertEqual((code, out, text), (2, "", want), sub)

    # --- R1-9 (4xja): H7 outside the root, and the other Amendment H cells --------------------------------------
    def test_every_configured_path_outside_the_root_refused(self):  # H7: all 14 cfg["paths"] keys (the six state dirs and the rest)
        keys = tuple(config.DEFAULTS["paths"])
        self.assertEqual(len(keys), 14)
        for key in keys:
            for value in ("../escape", "/abs/escape", "a/../../escape", "a//b"):
                self.init_config(paths={key: value})
                before = snapshot(self.root)
                for sub in ("plan", "apply"):
                    code, out, _ = self.cmd(sub)
                    self.assertEqual(code, 1, (key, value, sub))
                    self.assertTrue(out.startswith("FAIL init.config: "), (key, value, out))
                    self.assertIn("paths.%s" % key, out)
                self.assertEqual(snapshot(self.root), before, (key, value))
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "escape")))

    def test_block_files_each_kind(self):  # H1-H3: CLAUDE.md and .gitignore, a link, a directory, a FIFO
        for name in ("CLAUDE.md", ".gitignore"):
            p = os.path.join(self.root, name)
            for setup, want in ((lambda: os.symlink(os.path.join(self.root, "README.md"), p), "is a symlink"),
                                (lambda: os.mkdir(p), "exists and is not framework-managed"),
                                (lambda: os.mkfifo(p), "exists and is not framework-managed")):
                setup()
                before = snapshot(self.root)
                for sub in ("plan", "apply"):
                    code, out, _ = helpers.within(lambda: self.cmd(sub))
                    self.assertEqual((code, out), (1, "FAIL init.conflict: %s: %s\n" % (name, want)), (name, sub))
                self.assertEqual(snapshot(self.root), before)
                os.rmdir(p) if os.path.isdir(p) and not os.path.islink(p) else os.unlink(p)

    def test_ci_parents_are_links(self):  # H4: .github and .github/workflows as links
        for parent in (".github", ".github/workflows"):
            os.makedirs(os.path.join(self.root, ".github"), exist_ok=True)
            p = os.path.join(self.root, parent)
            if parent == ".github":
                os.rmdir(p)
            else:
                os.makedirs(os.path.join(self.root, ".github"), exist_ok=True)
            os.symlink(self.tmp, p)
            code, out, _ = self.cmd("plan", ci=True)
            self.assertEqual(code, 1, parent)
            self.assertIn("FAIL init.conflict: .github/workflows/strict-delivery.yml: parent %s is not a directory\n" % parent, out)
            os.unlink(p)
            if parent == ".github/workflows":
                os.rmdir(os.path.join(self.root, ".github"))
        self.assertEqual(os.listdir(self.tmp).count("strict-delivery.yml"), 0)

    def test_answers_through_a_linked_parent(self):  # H4: the answers path is the owner's argument, read as given
        real_dir = os.path.join(self.tmp, "real-answers")
        os.mkdir(real_dir)
        self.put_answers()
        os.rename(self.ans, os.path.join(real_dir, "a.yml"))
        os.symlink(real_dir, os.path.join(self.tmp, "linked"))
        self.assertEqual(self.run_init("plan", "--root", self.root, "--answers",
                                       os.path.join(self.tmp, "linked", "a.yml"))[0], 0)

    def test_unusual_characters_in_a_configured_path(self):  # H6
        self.init_config(paths={"decisions": "rec é/ü x"})
        code, out, _ = self.cmd("apply")
        self.assertEqual(code, 0, out)
        self.assertTrue(os.path.isdir(os.path.join(self.root, "rec é", "ü x")))

    def test_state_dir_each_key_symlink_fifo_parent(self):  # H1, H3, H4 for each of the six paths
        for key in STATE_KEYS:
            parent = "rec_%s" % key
            self.init_config(paths={key: parent + "/leaf"})
            target = os.path.join(self.root, parent)
            for label, setup, want in (
                    ("link", lambda: (os.makedirs(target), os.symlink(self.tmp, os.path.join(target, "leaf"))),
                     "%s/leaf: is a symlink" % parent),
                    ("fifo", lambda: (os.makedirs(target), os.mkfifo(os.path.join(target, "leaf"))),
                     "%s/leaf: exists and is not a directory" % parent),
                    ("parentlink", lambda: os.symlink(self.tmp, target), "%s: is a symlink" % parent),
                    ("parentfile", lambda: self.write(parent, "f"), "%s: exists and is not a directory" % parent)):
                if os.path.lexists(target):
                    if os.path.isdir(target) and not os.path.islink(target):
                        shutil.rmtree(target)
                    else:
                        os.unlink(target)
                setup()
                before = snapshot(self.root)
                for sub in ("plan", "apply"):
                    code, out, _ = helpers.within(lambda: self.cmd(sub))
                    self.assertEqual(code, 1, (key, label, sub))
                    self.assertIn("FAIL init.conflict: %s\n" % want, out, (key, label))
                self.assertEqual(snapshot(self.root), before, (key, label))
                self.assertNotIn("leaf", os.listdir(self.tmp))

    def test_state_dir_pairs_equal_or_nested(self):  # H5, DR8: every pair of the six keys
        for i, a in enumerate(STATE_KEYS):
            for b in STATE_KEYS[i + 1:]:
                self.init_config(paths={a: "rec/x", b: "rec/x"})
                code, out, _ = self.cmd("plan")
                if (a, b) == ("decisions", "findings"):  # 4c.2: the two gitignore lines would be equal
                    self.assertEqual(code, 1, (a, b, out))
                    self.assertTrue(out.startswith("FAIL init.input: two ignore lines are equal: "), (a, b, out))
                else:  # DR8: created once, no conflict
                    self.assertEqual(code, 0, (a, b, out))
                    self.assertEqual(out.count("mkdir rec/x/\n"), 1, (a, b, out))
                self.init_config(paths={a: "rec/x", b: "rec/x/y"})
                code, out, _ = self.cmd("plan")
                self.assertEqual(code, 0, (a, b, out))
                self.assertEqual(out.count("mkdir rec/x/y/\n"), 1, (a, b, out))

    def test_hooks_dir_fifo_is_a_conflict(self):  # H3 (hooks directory)
        r = self.repo("hfifo", commit=False, flags=("--template=",))
        h = os.path.join(r, ".git", "hooks")
        os.mkfifo(h)
        self.put_answers()
        before = snapshot(r)
        code, out, _ = helpers.within(lambda: self.run_init("plan", "--root", r, "--answers", self.ans))
        self.assertEqual(code, 1)
        self.assertIn("FAIL init.conflict: %s: exists and is not a directory\n" % h, out)
        self.assertEqual(helpers.within(lambda: self.run_init("apply", "--root", r, "--answers", self.ans))[0], 1)
        self.assertEqual(snapshot(r), before)

    def test_hook_files_fifo_dir_symlink_each(self):  # H1-H3 (each of the two hook files)
        os.makedirs(os.path.join(self.root, ".git", "hooks"), exist_ok=True)
        for name in ("pre-commit", "pre-push"):
            p = os.path.join(self.root, ".git", "hooks", name)
            for setup in (lambda: os.mkfifo(p), lambda: os.mkdir(p), lambda: os.symlink(self.tmp, p)):
                setup()
                code, out, _ = helpers.within(lambda: self.cmd("plan"))
                self.assertEqual((code, out), (1, "FAIL init.conflict: githooks.%s: foreign\n" % name))
                os.rmdir(p) if os.path.isdir(p) and not os.path.islink(p) else os.unlink(p)

    def test_state_dir_swapped_to_link_after_plan(self):  # H4: a parent turns into a link between plan and write
        outside = os.path.join(self.tmp, "outside")
        os.mkdir(outside)
        real = managed.apply

        def swap(root, actions):
            res = real(root, actions)
            state = os.path.join(root, ".strict-delivery", "state")
            if not os.path.lexists(state) and any(a[0] == ".strict-delivery/config.yml" for a in actions):
                os.symlink(outside, state)
            return res
        with mock.patch.object(managed, "apply", swap):
            code, out, _ = self.cmd("apply")
        self.assertEqual(code, 1)
        self.assertIn("FAIL init.write: .strict-delivery/state: is a symlink\n", out)
        self.assertEqual(os.listdir(outside), [])

    def test_hooks_dir_swapped_to_link_after_plan(self):  # H4: the hooks directory turns into a link
        outside = os.path.join(self.tmp, "outside-hooks")
        os.mkdir(outside)
        hooks = os.path.join(self.root, ".git", "hooks")
        real = managed.apply

        def swap(root, actions):
            res = real(root, actions)
            if any(a[0] == "CLAUDE.md" for a in actions) and os.path.isdir(hooks) and not os.path.islink(hooks):
                os.rename(hooks, hooks + ".old")
                os.symlink(outside, hooks)
            return res
        with mock.patch.object(managed, "apply", swap):
            code, out, _ = self.cmd("apply")
        self.assertEqual(code, 1)
        self.assertIn("FAIL init.write: %s: exists and is not a directory\n" % hooks, out)
        self.assertEqual(os.listdir(outside), [])


class TestSurvivors(More):
    """Round 2: a surviving mutant is a missing test. Each test names the mutant ids (ch/4d1-mutants-5-table.py) it kills."""

    def only_differs(self, expected_line, **cfg_extra):
        """An initialised repository (config as ``init_config`` plus ``cfg_extra``); plan and apply refuse with exactly
        ``expected_line``, writing nothing (D-Q4 (b))."""
        self.init_config(**cfg_extra)
        before = snapshot(self.root)
        for sub in ("plan", "apply"):
            code, out, _ = self.cmd(sub)
            self.assertEqual((code, out), (1, "FAIL init.answers: %s\n" % expected_line), sub)
            self.assertEqual(snapshot(self.root), before, sub)

    # --- D-Q4 (b): each of the five config keys, one test each (members of _config_differences) ------------------
    def test_initialised_merge_mode_must_match(self):  # D-Q4 (b); kills s-a14
        self.only_differs('merge_mode: differs from the config (answer "host", config "controller")',
                          merge={"mode": "controller"})

    def test_initialised_base_branch_must_match(self):  # D-Q4 (b); kills s-a15
        self.only_differs('base_branch: differs from the config (answer "main", config "develop")',
                          base_branch="develop")

    def test_initialised_tier_value_must_match(self):  # D-Q4 (b); kills s-a16
        self.only_differs('models.tiers.tier2: differs from the config (answer "sonnet", config "mine")',
                          models={"tiers": {"tier2": "mine"}})

    def test_initialised_tier_absent_from_config_differs(self):  # D-Q4 (b); kills s-a16
        self.init_config()
        a = answers(models={"tiers": {"tier1": "haiku", "tier2": "sonnet", "tier3": "opus", "tier4": "x"}})
        self.put_answers(a)
        code, out, _ = self.run_init("plan", "--root", self.root, "--answers", self.ans)
        self.assertEqual((code, out), (1, 'FAIL init.answers: models.tiers.tier4: differs from the config '
                                          '(answer "x", config null)\n'))

    def test_initialised_equal_answers_pass(self):  # D-Q4 (b) "equal values pass": the other branch of every key
        self.init_config(merge={"mode": "controller"}, base_branch="develop", models={"tiers": {"tier2": "mine"}})
        a = answers(merge_mode="controller", base_branch="develop",
                    models={"tiers": {"tier1": "haiku", "tier2": "mine", "tier3": "opus"}})
        self.put_answers(a)
        self.assertEqual(self.run_init("plan", "--root", self.root, "--answers", self.ans)[0], 0)

    # --- D-Q5 (a): a block present at this version with another body is left alone, with a note -----------------
    def test_block_same_version_other_body_is_a_note(self):  # D-Q5 (a); kills s-a18 (CLAUDE.md)
        self.assertEqual(self.cmd("apply")[0], 0)
        self.write("CLAUDE.md", self.read("CLAUDE.md").replace("- Plans:", "- My plans:"))
        before = snapshot(self.root)
        for sub in ("plan", "apply"):
            code, out, _ = self.cmd(sub)
            self.assertEqual(code, 0, sub)
            self.assertTrue(out.startswith("no changes\nnote: CLAUDE.md: present at version 0.0.0; "
                                           "run /strict-delivery:upgrade\n"), (sub, out))
            self.assertEqual(snapshot(self.root), before, sub)
        self.assertIn("- My plans:", self.read("CLAUDE.md"))

    def test_gitignore_block_same_version_other_body_is_a_note(self):  # D-Q5 (a); kills s-a18 (.gitignore)
        self.assertEqual(self.cmd("apply")[0], 0)
        self.write(".gitignore", self.read(".gitignore").replace("/in-force.md", "/mine.md"))
        before = snapshot(self.root)
        for sub in ("plan", "apply"):
            code, out, _ = self.cmd(sub)
            self.assertEqual(code, 0, sub)
            self.assertTrue(out.startswith("no changes\nnote: .gitignore: present at version 0.0.0; "
                                           "run /strict-delivery:upgrade\n"), (sub, out))
            self.assertEqual(snapshot(self.root), before, sub)

    # --- CD13: the direct-call argument checks -------------------------------------------------------------------
    def test_load_answers_path_type_message(self):  # AF17; kills s-a33
        import pathlib
        for bad in (None, 5, b"x", pathlib.Path(self.ans), S(self.ans)):
            with self.assertRaises(init.InitError) as cm:
                init.load_answers(bad)
            self.assertEqual((cm.exception.ident, cm.exception.reason), ("init.answers", "path: must be a string"),
                             repr(bad))

    def test_plan_init_schema_error_is_init_input(self):  # PL5 (SchemaError while loading init-answers.yml); kills s-a8
        from gates.lib import schema
        with mock.patch.object(schema, "load_schema", side_effect=schema.SchemaError("boom")):
            with self.assertRaises(init.InitError) as cm:
                init.plan_init(self.root, answers())
        self.assertEqual((cm.exception.ident, cm.exception.reason), ("init.input", "boom"))

    # --- AP4, CD18: a hook written before a later write fails stays and is listed ------------------------------------
    def test_written_lists_hook_written_before_failure(self):  # AP4, CD18; kills s-g2, s-x7
        hooks = os.path.join(self.root, ".git", "hooks")
        real = githooks._write

        def second_fails(path, text):
            if path.endswith("pre-push"):
                raise OSError(28, "No space left on device")
            return real(path, text)
        with mock.patch.object(githooks, "_write", second_fails):
            code, out, _ = self.cmd("apply")
        dirs = ", ".join(".strict-delivery/%s/" % d for d in ("state", "state/decisions", "state/findings", "state/claims",
                                                              "state/plans", "state/programs", "playbooks"))
        self.assertEqual(out, "FAIL init.write: %s: cannot write (No space left on device)\n"
                              "written: .strict-delivery/config.yml, %s, CLAUDE.md, .gitignore, .claude/settings.json, "
                              ".strict-delivery/context.yml, %s\n"
                              % (os.path.join(hooks, "pre-push"), dirs, os.path.join(hooks, "pre-commit")))
        self.assertEqual(code, 1)
        self.assertTrue(os.path.exists(os.path.join(hooks, "pre-commit")))
        self.assertFalse(os.path.exists(os.path.join(hooks, "pre-push")))


CONTEXT_YML = """schema: context/1
every:
  - path: "{paths.decisions}/in-force.md"
    why: the decisions in force; every session reads them before acting (spec section 7.4)
kinds:
  plan:
    - path: "{paths.plan_state}/{plan}/handoff.md"
      why: where the plan stands and what to do next (handoff/1)
    - path: "{paths.plan_state}/{plan}/ledger.md"
      why: the plan's ledger, read from the handoff's ledger_from
    - path: "{paths.plans}/{plan}.md"
      why: the plan itself
  stream-block:
    - path: "{paths.plan_state}/{plan}/handoff.md"
      why: where the stream plan stands and what to do next (handoff/1)
    - path: "{paths.plan_state}/{plan}/ledger.md"
      why: the stream plan's ledger, read from the handoff's ledger_from
    - path: "{paths.plans}/{plan}.md"
      why: the stream plan itself
    - path: "{integration}/{paths.programs}/{program}/status.md"
      why: the program's status page (programs design section 10)
  program:
    - path: "{integration}/{paths.programs}/{program}/status.md"
      why: the program's status page (programs design section 10)
  program-controller:
    - path: "{integration}/{paths.programs}/{program}/status.md"
      why: the program's status page (programs design section 10)
    - path: "{integration}/{paths.programs}/{program}/streams.yml"
      why: the streams, their ownership and windows
  sync:
    - path: "{integration}/{paths.programs}/{program}/status.md"
      why: the program's status page (programs design section 10)
    - path: "{integration}/{paths.programs}/{program}/streams.yml"
      why: the streams, their ownership and windows
roles:
  task_reviewer:
    - path: "{brief}"
      why: the dispatch brief this agent works from
  final_reviewer:
    - path: "{brief}"
      why: the dispatch brief this agent works from
  final_verifier:
    - path: "{brief}"
      why: the dispatch brief this agent works from
  exception_reviewer:
    - path: "{brief}"
      why: the dispatch brief this agent works from
"""
CTX = ".strict-delivery/context.yml"


class TestContextYml(More):
    """Amendment C (plan :5102, owner answer Q-RC13-1): init writes the default .strict-delivery/context.yml. The
    expected text is hand-written above: origin/main's entries except the four ``playbook/review.md`` entries."""

    def ctx_path(self):
        return os.path.join(self.root, CTX)

    # --- the template pin -------------------------------------------------------------------------------------
    def test_template_is_the_expected_text(self):  # Q-RC13-1 (Note C-3)
        from gates.lib import templates
        with open(os.path.join(REPO, "templates", "context.yml"), "rb") as fh:
            self.assertEqual(fh.read().decode("utf-8"), CONTEXT_YML)
        self.assertEqual(templates.render("context.yml", {}), CONTEXT_YML)
        self.assertNotIn("playbook/review.md", CONTEXT_YML)
        self.assertEqual(CONTEXT_YML.count("{brief}"), 4)

    # --- CX1: a fresh repository -------------------------------------------------------------------------------
    def test_cx1_plan_lists_an_add(self):  # CX1; kills s-x1, s-x4
        before = snapshot(self.root)
        plan = init.plan_init(self.root, answers())
        adds = [w for w in plan.writes if w.path == CTX]
        self.assertEqual([(w.kind, w.text) for w in adds], [("file", CONTEXT_YML)])
        code, out, _ = self.cmd("plan")
        self.assertEqual(code, 0)
        self.assertIn("--- a/%s\n+++ b/%s\n@@ -0,0 +1,%d @@\n" % (CTX, CTX, CONTEXT_YML.count("\n")), out)
        self.assertIn("".join("+%s\n" % l for l in CONTEXT_YML.split("\n")[:-1]), out)
        self.assertEqual(snapshot(self.root), before)

    def test_cx1_apply_writes_the_default(self):  # CX1; kills s-x1, s-x4, s-x6
        code, out, _ = self.cmd("apply")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.read(CTX), CONTEXT_YML)
        self.assertIn("?? %s\n" % CTX, out)
        self.assertEqual(os.lstat(self.ctx_path()).st_mode & 0o777, 0o666 & ~umask())

    def test_cx1_written_file_passes_check_schema(self):  # CX1: check schema, kind context
        # ``context`` is in no producer list yet (it joins with block 5, plan :5102), so ``check schema`` does not look
        # at the kind on this head; the test makes it produced, as it will be, and shows the gate then looks.
        from gates import gate_schema
        from gates.lib import schema
        with mock.patch.object(schema, "produced_kinds", return_value=schema.produced_kinds() | {"context"}):
            self.assertEqual(self.cmd("apply")[0], 0)
            os.unlink(self.ctx_path())  # the fixture's own file: the gate must then name it missing
            missing = gate_schema.check(["--root", self.root])
            self.assertIn(("FAIL", "schema.context." + CTX), [(l.status, l.id) for l in missing.lines])
            self.assertEqual(self.cmd("apply")[0], 0)
            res = gate_schema.check(["--root", self.root])
        self.assertIn(("PASS", "schema.context"), [(l.status, l.id) for l in res.lines])
        self.assertEqual([l for l in res.lines if l.status == "FAIL"], [])

    def test_cx1_configured_path_is_used(self):  # CX1 with paths.context set (config.py:30 key); kills s-x5
        self.init_config(paths={"context": "ctx/context.yml"})
        code, out, _ = self.cmd("apply")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.read("ctx/context.yml"), CONTEXT_YML)
        self.assertFalse(os.path.exists(self.ctx_path()))

    # --- CX2: present ------------------------------------------------------------------------------------------
    def test_cx2_present_and_equal_is_no_change(self):  # CX2 equal; kills s-x2
        self.assertEqual(self.cmd("apply")[0], 0)
        before = snapshot(self.root)
        self.assertEqual(self.cmd("plan")[:2], (0, "no changes\n"))
        code, out, _ = self.cmd("apply")
        self.assertEqual(code, 0)
        self.assertTrue(out.startswith("no changes\n"), out)  # apply then prints the git status
        self.assertEqual(snapshot(self.root), before)
        self.assertEqual(self.read(CTX), CONTEXT_YML)

    def test_cx2_present_and_different_is_left_alone(self):  # CX2 different (no-overwrite rule); kills s-x2
        mine = "schema: context/1\nevery: []\n"
        self.write(CTX, mine)
        plan = init.plan_init(self.root, answers())
        self.assertEqual((plan.conflicts, [w.path for w in plan.writes if w.path == CTX]), ([], []))
        code, out, _ = self.cmd("plan")
        self.assertEqual(code, 0)
        self.assertNotIn(CTX, out)
        code, out, _ = self.cmd("apply")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.read(CTX), mine)
        self.assertTrue(os.path.exists(os.path.join(self.root, "CLAUDE.md")))  # the other pieces are still written
        self.assertEqual(self.cmd("plan")[:2], (0, "no changes\n"))

    def conflict(self, setup, text, sub_list=("plan", "apply")):
        setup()
        before = snapshot(self.root)
        for sub in sub_list:
            code, out, _ = helpers.within(lambda: self.cmd(sub))
            self.assertEqual(code, 1, (sub, out))
            self.assertIn("FAIL init.conflict: %s: %s\n" % (CTX, text), out)
            self.assertEqual(snapshot(self.root), before, sub)
        self.assertFalse(os.path.exists(os.path.join(self.root, "CLAUDE.md")))

    def test_cx2_malformed_non_utf8_is_a_conflict(self):  # CX2 malformed; H6; kills s-x3
        self.conflict(lambda: self.write(CTX, b"schema: context/1\n\xff\xfe", mode="wb"),
                      "exists and is not framework-managed")

    def test_cx2_symlink_is_a_conflict(self):  # CX2 symlink, H1; kills s-x3
        def setup():
            os.makedirs(os.path.dirname(self.ctx_path()))
            os.symlink(os.path.join(self.root, "README.md"), self.ctx_path())
        self.conflict(setup, "is a symlink")

    def test_cx2_dangling_symlink_is_a_conflict(self):  # CX2 symlink (dangling), H1; kills s-x3
        def setup():
            os.makedirs(os.path.dirname(self.ctx_path()))
            os.symlink(os.path.join(self.tmp, "nowhere"), self.ctx_path())
        self.conflict(setup, "is a symlink")

    def test_cx2_directory_is_a_conflict(self):  # CX2 directory, H2; kills s-x3
        self.conflict(lambda: os.makedirs(self.ctx_path()), "exists and is not framework-managed")

    def test_cx2_fifo_is_a_conflict(self):  # CX2 FIFO, H3; kills s-x3
        def setup():
            os.makedirs(os.path.dirname(self.ctx_path()))
            os.mkfifo(self.ctx_path())
        self.conflict(setup, "exists and is not framework-managed")

    def test_cx2_parent_link_is_a_conflict(self):  # H4: .strict-delivery is a symlink to a directory
        outside = os.path.join(self.tmp, "outside")
        os.mkdir(outside)
        os.symlink(outside, os.path.join(self.root, ".strict-delivery"))
        before = snapshot(self.root)
        for sub in ("plan", "apply"):
            code, out, _ = self.cmd(sub)
            self.assertEqual(code, 1, sub)
            self.assertIn("FAIL init.conflict: %s: parent .strict-delivery is not a directory\n" % CTX, out)
            self.assertEqual(snapshot(self.root), before, sub)
        self.assertEqual(os.listdir(outside), [])

    def test_cx2_unreadable_is_init_input(self):  # H6: mode 0 (as BK8 for CLAUDE.md)
        p = self.write(CTX, "x: y\n")
        os.chmod(p, 0)
        self.addCleanup(os.chmod, p, 0o644)
        code, out, _ = self.cmd("plan")
        self.assertEqual((code, out), (1, "FAIL init.input: %s: cannot read (Permission denied)\n" % CTX))

    def test_cx_write_failure_names_the_path(self):  # AP4: the context write fails after the others; kills s-x6
        real = managed._write

        def fail_ctx(root, path, text):
            if path == CTX:
                raise OSError(28, "No space left on device")
            return real(root, path, text)
        with mock.patch.object(managed, "_write", fail_ctx):
            code, out, _ = self.cmd("apply", git_hooks=False)
        self.assertEqual(code, 1)
        self.assertIn("FAIL init.write: %s: cannot write (No space left on device)\nwritten: " % CTX, out)
        self.assertIn("CLAUDE.md, .gitignore, .claude/settings.json\n", out)


SAME = "%s: two writes name the same path"
PARENT = "%s: parent %s is not a directory"
INSIDE = "%s: inside the state directory %s"


class TestReview2(More):
    """Fix round 3 (review 2): R2-1 (H5, ``paths.context`` against every other path init plans), R2-2 (H4 swaps of the
    context file), R2-3 (AP3 up-front recheck). Mutant ids: ch/4d1-mutants-6-table.py."""

    def overlap(self, ctx, expect, ci=False, **paths):
        """``plan`` and ``apply`` print exactly the one conflict ``expect`` and leave the tree as it was."""
        self.init_config(paths=dict(paths, context=ctx))
        before = snapshot(self.root)
        fw = self.make_fw("tagged", version="0.1.0")
        for sub in ("plan", "apply"):
            with mock.patch.object(plugin, "framework_dir", return_value=fw), \
                    mock.patch.object(init.gitinfo, "head_sha", side_effect=init.GitNotFound("no git")):
                code, out, _ = helpers.within(lambda: self.cmd(sub, ci=ci))
            self.assertEqual((code, out), (1, "FAIL init.conflict: %s\n" % expect), (ctx, sub))
            self.assertEqual(snapshot(self.root), before, (ctx, sub))

    # --- R2-1: equal to a state directory (STATE_KEYS), to the state parent, to an ancestor directory ------------
    # Decision (controller, owner delegation 2026-11-09): equal to or inside a state directory is one conflict line
    # ``<ctx>: inside the state directory <dir>``.
    def test_ctx_equals_state_decisions(self):  # H5; kills r-i1
        d = ".strict-delivery/state/decisions"
        self.overlap(d, INSIDE % (d, d))

    def test_ctx_equals_state_findings(self):  # H5; kills r-i1
        d = ".strict-delivery/state/findings"
        self.overlap(d, INSIDE % (d, d))

    def test_ctx_equals_state_claims(self):  # H5; kills r-i1
        d = ".strict-delivery/state/claims"
        self.overlap(d, INSIDE % (d, d))

    def test_ctx_equals_state_plans(self):  # H5; kills r-i1
        d = ".strict-delivery/state/plans"
        self.overlap(d, INSIDE % (d, d))

    def test_ctx_equals_state_programs(self):  # H5; kills r-i1
        d = ".strict-delivery/state/programs"
        self.overlap(d, INSIDE % (d, d))

    def test_ctx_equals_playbooks(self):  # H5; kills r-i1
        d = ".strict-delivery/playbooks"
        self.overlap(d, INSIDE % (d, d))

    def test_ctx_equals_state_parent(self):  # H5; kills r-i2
        d = ".strict-delivery/state"
        self.overlap(d, INSIDE % (d, d))

    def test_ctx_inside_state_decisions(self):  # H5; kills r-i1, r-i3
        d = ".strict-delivery/state/decisions"
        self.overlap(d + "/ctx.yml", INSIDE % (d + "/ctx.yml", d))

    def test_ctx_inside_state_findings(self):  # H5; kills r-i1, r-i3
        d = ".strict-delivery/state/findings"
        self.overlap(d + "/ctx.yml", INSIDE % (d + "/ctx.yml", d))

    def test_ctx_inside_state_claims(self):  # H5; kills r-i1, r-i3
        d = ".strict-delivery/state/claims"
        self.overlap(d + "/ctx.yml", INSIDE % (d + "/ctx.yml", d))

    def test_ctx_inside_state_plans(self):  # H5; kills r-i1, r-i3
        d = ".strict-delivery/state/plans"
        self.overlap(d + "/ctx.yml", INSIDE % (d + "/ctx.yml", d))

    def test_ctx_inside_state_programs(self):  # H5; kills r-i1, r-i3
        d = ".strict-delivery/state/programs"
        self.overlap(d + "/ctx.yml", INSIDE % (d + "/ctx.yml", d))

    def test_ctx_inside_playbooks(self):  # H5; kills r-i1, r-i3
        d = ".strict-delivery/playbooks"
        self.overlap(d + "/ctx.yml", INSIDE % (d + "/ctx.yml", d))

    def test_ctx_inside_state_parent(self):  # H5; kills r-i2, r-i3
        d = ".strict-delivery/state"
        self.overlap(d + "/ctx.yml", INSIDE % (d + "/ctx.yml", d))

    def test_ctx_deep_inside_state_dir(self):  # H5; kills r-i3 (two levels down)
        d = ".strict-delivery/state/claims"
        self.overlap(d + "/a/b.yml", INSIDE % (d + "/a/b.yml", d))

    def test_ctx_sibling_of_state_dir_name_passes(self):  # H5; kills r-i3 (a name that only shares the prefix)
        self.init_config(paths={"context": ".strict-delivery/state-x.yml"})
        self.assertEqual(self.cmd("plan")[0], 0)

    def test_ctx_equals_strict_delivery_dir(self):  # H5; kills r-o2
        d = ".strict-delivery"
        self.overlap(d, SAME % d)

    def test_ctx_equals_claude_dir(self):  # H5; kills r-o2
        self.overlap(".claude", SAME % ".claude")

    def test_ctx_equals_github_dir(self):  # H5; kills r-o2 (ci true)
        self.overlap(".github", SAME % ".github", ci=True)

    def test_ctx_equals_github_workflows_dir(self):  # H5; kills r-o2 (ci true)
        self.overlap(".github/workflows", SAME % ".github/workflows", ci=True)

    def test_ctx_equals_configured_state_dir(self):  # H5; kills r-i1 (a configured, not a default, directory)
        self.overlap("rec/dec", INSIDE % ("rec/dec", "rec/dec"), decisions="rec/dec")

    def test_ctx_inside_configured_state_dir(self):  # H5; kills r-i1 (a configured directory)
        self.overlap("rec/dec/c.yml", INSIDE % ("rec/dec/c.yml", "rec/dec"), decisions="rec/dec")

    def test_ctx_inside_configured_state_parent(self):  # H5; kills r-i2 (paths.state configured)
        self.overlap("st/c.yml", INSIDE % ("st/c.yml", "st"), state="st")

    # --- R2-1: equal to, or below, a planned file --------------------------------------------------------------
    def test_ctx_equals_claude_md(self):  # H5; kills r-o1, r-o9
        self.overlap("CLAUDE.md", SAME % "CLAUDE.md")

    def test_ctx_equals_claude_md_present(self):  # H5; kills r-o1, r-o9 (the file exists with the block: no write is planned)
        self.assertEqual(self.cmd("apply", git_hooks=False)[0], 0)
        self.init_config(paths={"context": "CLAUDE.md"})
        before = snapshot(self.root)
        for sub in ("plan", "apply"):
            code, out, _ = self.cmd(sub, git_hooks=False)
            self.assertEqual((code, out), (1, "FAIL init.conflict: %s\n" % (SAME % "CLAUDE.md")), sub)
            self.assertEqual(snapshot(self.root), before, sub)

    def test_ctx_below_claude_md(self):  # H5; kills r-o4
        self.overlap("CLAUDE.md/x.yml", PARENT % ("CLAUDE.md/x.yml", "CLAUDE.md"))

    def test_ctx_equals_gitignore(self):  # H5; kills r-o1, r-o9
        self.overlap(".gitignore", SAME % ".gitignore")

    def test_ctx_below_gitignore(self):  # H5; kills r-o4
        self.overlap(".gitignore/x.yml", PARENT % (".gitignore/x.yml", ".gitignore"))

    def test_ctx_equals_settings(self):  # H5; kills r-o1, r-o9
        self.overlap(".claude/settings.json", SAME % ".claude/settings.json")

    def test_ctx_below_settings(self):  # H5; kills r-o4
        self.overlap(".claude/settings.json/x.yml", PARENT % (".claude/settings.json/x.yml", ".claude/settings.json"))

    def test_ctx_equals_ci_workflow(self):  # H5; kills r-o1, r-o9 (ci true)
        p = ".github/workflows/strict-delivery.yml"
        self.overlap(p, SAME % p, ci=True)

    def test_ctx_below_ci_workflow(self):  # H5; kills r-o4 (ci true)
        p = ".github/workflows/strict-delivery.yml"
        self.overlap(p + "/x.yml", PARENT % (p + "/x.yml", p), ci=True)

    def test_ctx_equals_config(self):  # H5; kills r-o1, r-o9
        p = ".strict-delivery/config.yml"
        self.overlap(p, SAME % p)

    def test_ctx_below_config(self):  # H5; kills r-o4
        p = ".strict-delivery/config.yml"
        self.overlap(p + "/x.yml", PARENT % (p + "/x.yml", p))

    # --- R2-1: the reverse nesting, a state directory below paths.context -----------------------------------------
    def test_state_dir_below_ctx(self):  # H5; kills r-o2 (the ancestors of a state directory)
        self.overlap("rec", SAME % "rec", decisions="rec/dec")

    def test_state_dir_below_ctx_other_key(self):  # H5; kills r-o2 (a key other than the first)
        self.overlap("rec", SAME % "rec", playbooks="rec/pb")

    def test_state_dir_deep_below_ctx(self):  # H5; kills r-o2 (two levels below)
        self.overlap("rec/a", SAME % "rec/a", claims="rec/a/b/c")

    # --- R2-1: a ``paths.context`` that overlaps nothing is still accepted ----------------------------------------
    def test_ctx_unrelated_paths_pass(self):  # H5: the default and siblings of planned paths
        for ctx in (".strict-delivery/context.yml", ".strict-delivery/statex.yml", "ctx/context.yml",
                    ".github/ctx.yml", ".claude/ctx.yml"):
            self.init_config(paths={"context": ctx})
            code, out, _ = self.cmd("plan")
            self.assertEqual(code, 0, (ctx, out))

    # --- R2-2: H4 swap after plan; each member passes on the parent commit and is killed by r-s1 or r-s2 --------
    def swap_after(self, trigger_path, swap):
        """Run ``apply``; ``swap`` runs once, right after the write of ``trigger_path``."""
        real = managed.apply

        def wrapper(root, actions):
            res = real(root, actions)
            if any(a[0] == trigger_path for a in actions):
                swap(root)
            return res
        with mock.patch.object(managed, "apply", wrapper):
            return self.cmd("apply", git_hooks=False)

    def test_ctx_file_swapped_to_symlink_after_plan(self):  # H4, H1; kills r-s1
        outside = os.path.join(self.tmp, "outside.yml")
        code, out, _ = self.swap_after(".claude/settings.json", lambda r: os.symlink(outside, os.path.join(r, CTX)))
        self.assertEqual(code, 1)
        self.assertIn("FAIL init.write: apply refused: %s: is a symlink\n" % CTX, out)
        self.assertFalse(os.path.exists(outside))

    def test_ctx_file_swapped_to_directory_after_plan(self):  # H4, H2; kills r-s1
        code, out, _ = self.swap_after(".claude/settings.json", lambda r: os.mkdir(os.path.join(r, CTX)))
        self.assertEqual(code, 1)
        self.assertIn("FAIL init.write: apply refused: %s: exists and is not framework-managed\n" % CTX, out)
        self.assertEqual(os.listdir(os.path.join(self.root, CTX)), [])

    def test_ctx_file_swapped_to_fifo_after_plan(self):  # H4, H3; kills r-s1
        code, out, _ = self.swap_after(".claude/settings.json", lambda r: os.mkfifo(os.path.join(r, CTX)))
        self.assertEqual(code, 1)
        self.assertIn("FAIL init.write: apply refused: %s: exists and is not framework-managed\n" % CTX, out)
        self.assertTrue(stat.S_ISFIFO(os.lstat(os.path.join(self.root, CTX)).st_mode))

    def test_ctx_parent_swapped_to_symlink_after_plan(self):  # H4; kills r-s1
        outside = os.path.join(self.tmp, "outside-sd")
        os.mkdir(outside)

        def swap(r):
            os.rename(os.path.join(r, ".strict-delivery"), os.path.join(r, ".strict-delivery.old"))
            os.symlink(outside, os.path.join(r, ".strict-delivery"))
        code, out, _ = self.swap_after(".claude/settings.json", swap)
        self.assertEqual(code, 1)
        self.assertIn("FAIL init.write: apply refused: %s: parent .strict-delivery is not a directory\n" % CTX, out)
        self.assertEqual(os.listdir(outside), [])

    def test_state_dir_swapped_to_file_after_plan(self):  # H4 (the non-directory branch of the recheck); kills r-s2
        def swap(r):
            with open(os.path.join(r, ".strict-delivery", "state"), "w", encoding="utf-8") as fh:
                fh.write("x")
        code, out, _ = self.swap_after(".strict-delivery/config.yml", swap)
        self.assertEqual(code, 1)
        self.assertIn("FAIL init.write: .strict-delivery/state: exists and is not a directory\n", out)
        self.assertEqual(self.read(".strict-delivery/state"), "x")
        self.assertFalse(os.path.exists(os.path.join(self.root, "CLAUDE.md")))

    # --- R2-3: AP3, the group (CLAUDE.md, .gitignore) is checked before the first write, and again before each ----
    def swapped_after_build(self, name):
        outside = os.path.join(self.tmp, "outside.txt")
        real_build = init._build
        snap = []

        def build(root, answers):
            res = real_build(root, answers)
            os.symlink(outside, os.path.join(root, name))  # after the plan, before the first write
            snap.append(snapshot(root))
            return res
        with mock.patch.object(init, "_build", build):
            code, out, _ = self.cmd("apply")
        self.assertEqual((code, out), (1, "FAIL init.write: apply refused: %s: is a symlink\nwritten: \n" % name))
        self.assertEqual(snapshot(self.root), snap[0])
        self.assertFalse(os.path.exists(os.path.join(self.root, ".strict-delivery")))
        self.assertFalse(os.path.exists(outside))

    def test_gitignore_swapped_after_plan_nothing_is_written(self):  # AP3; red on the parent, kills r-a1
        self.swapped_after_build(".gitignore")
        self.assertFalse(os.path.exists(os.path.join(self.root, "CLAUDE.md")))

    def test_claude_md_swapped_after_plan_nothing_is_written(self):  # AP3; red on the parent, kills r-a1 (the other action)
        self.swapped_after_build("CLAUDE.md")
        self.assertFalse(os.path.exists(os.path.join(self.root, ".gitignore")))

    def test_gitignore_swapped_between_the_two_writes_is_refused(self):  # AP3; kills r-s1
        outside = os.path.join(self.tmp, "outside.txt")
        code, out, _ = self.swap_after("CLAUDE.md", lambda r: os.symlink(outside, os.path.join(r, ".gitignore")))
        self.assertEqual(code, 1)
        self.assertIn("FAIL init.write: apply refused: .gitignore: is a symlink\nwritten: ", out)
        self.assertTrue(out.rstrip("\n").endswith("CLAUDE.md"), out)
        self.assertFalse(os.path.exists(outside))


NOT_MANAGED = "%s: exists and is not framework-managed"
HOOKS_PATH = "core.hooksPath is set (%s); unset it to install the hooks"


class TestReview3(More):
    """Fix round 4 (review 3): R3-1 (F-20261125-ninr, the hook files init plans are planned files for H5), R3-2
    (F-20261125-4fji, the ``/`` boundary: a sibling name is accepted), R3-3 (F-20261125-5x5w, the H5 compare under
    one explicit ASCII map of ``A``-``Z`` to ``a``-``z``, Note H-1). Mutant ids: ch/4d1-mutants-7-table.py (t7-*)."""

    overlap = TestReview2.overlap

    def refused_at(self, root, ctx, lines, **paths):
        """``plan`` and ``apply`` on ``root`` print exactly the conflict ``lines`` and change nothing in ``root`` or in
        the main repository ``self.root`` (which holds the common git directory)."""
        rec = {"schema": "config/2", "framework_version": "0.0.0", "profile": "standard",
               "commands": answers()["commands"], "paths": dict(paths, context=ctx)}
        helpers.write_record(root, ".strict-delivery/config.yml", rec)
        before = (snapshot(root), snapshot(self.root))
        for sub in ("plan", "apply"):
            code, out, _ = self.cmd(sub, root=root)
            self.assertEqual((code, out), (1, "".join("FAIL init.conflict: %s\n" % l for l in lines)), (ctx, sub))
            self.assertEqual((snapshot(root), snapshot(self.root)), before, (ctx, sub))

    def accepted_ctx(self, ctx, ci=False):
        """``plan`` exits 0 and ``apply`` exits 0 and writes the default context file at ``ctx``."""
        self.init_config(paths={"context": ctx})
        fw = self.make_fw("tagged", version="0.1.0")
        for sub in ("plan", "apply"):
            with mock.patch.object(plugin, "framework_dir", return_value=fw), \
                    mock.patch.object(init.gitinfo, "head_sha", side_effect=init.GitNotFound("no git")):
                code, out, _ = helpers.within(lambda: self.cmd(sub, ci=ci))
            self.assertEqual(code, 0, (ctx, sub, out))
        self.assertEqual(self.read(ctx), CONTEXT_YML)

    def hide_hooks_dir(self):
        os.rename(os.path.join(self.root, ".git", "hooks"), os.path.join(self.root, ".git", "hooks.old"))

    # --- R3-1 (ninr): equal to, or below, a hook file init plans (default .git/hooks) ------------------------------
    def test_ctx_equals_pre_commit_hook(self):  # H5; red on the parent; kills t7-h1, t7-h2
        self.overlap(".git/hooks/pre-commit", SAME % ".git/hooks/pre-commit")

    def test_ctx_equals_pre_push_hook(self):  # H5; red on the parent; kills t7-h1, t7-h2
        self.overlap(".git/hooks/pre-push", SAME % ".git/hooks/pre-push")

    def test_ctx_below_pre_commit_hook(self):  # H5; red on the parent; kills t7-h1, t7-h4
        p = ".git/hooks/pre-commit"
        self.overlap(p + "/x", PARENT % (p + "/x", p))

    def test_ctx_below_pre_push_hook(self):  # H5; red on the parent; kills t7-h1, t7-h4
        p = ".git/hooks/pre-push"
        self.overlap(p + "/x", PARENT % (p + "/x", p))

    def test_ctx_equals_hook_hooks_dir_absent(self):  # H5; red on the parent; kills t7-h1, t7-h2
        self.hide_hooks_dir()
        self.overlap(".git/hooks/pre-commit", SAME % ".git/hooks/pre-commit")

    def test_ctx_below_hook_hooks_dir_absent(self):  # H5; red on the parent; kills t7-h1, t7-h4
        self.hide_hooks_dir()
        p = ".git/hooks/pre-push"
        self.overlap(p + "/x", PARENT % (p + "/x", p))

    def test_ctx_equals_absent_hooks_dir(self):  # H5 (the directory init creates); red on the parent; kills t7-h3
        self.hide_hooks_dir()
        self.overlap(".git/hooks", SAME % ".git/hooks")

    def test_ctx_equals_present_hooks_dir_keeps_existing_text(self):  # H5 pin (passes on the parent); kills t7-h5
        self.overlap(".git/hooks", NOT_MANAGED % ".git/hooks")

    def test_ctx_equals_git_dir_keeps_existing_text(self):  # H5 pin (passes on the parent); kills t7-h5
        self.overlap(".git", NOT_MANAGED % ".git")

    # --- R3-1: core.hooksPath (init installs no hook there: its conflict is the one line) --------------------------
    def test_ctx_equals_hook_in_hooks_path(self):  # H5 pin (passes on the parent)
        git(self.root, "config", "core.hooksPath", "hk")
        self.refused_at(self.root, "hk/pre-commit", [HOOKS_PATH % "hk"])

    def test_ctx_below_hook_in_hooks_path(self):  # H5 pin (passes on the parent)
        git(self.root, "config", "core.hooksPath", "hk")
        self.refused_at(self.root, "hk/pre-push/x", [HOOKS_PATH % "hk"])

    def test_ctx_equals_hooks_path_dir(self):  # H5 pin (passes on the parent); kills t7-h6
        git(self.root, "config", "core.hooksPath", "hk")
        self.refused_at(self.root, "hk", [HOOKS_PATH % "hk"])

    # --- R3-1: a linked worktree (hooks in the common git directory, outside its root) -----------------------------
    def test_ctx_hook_path_in_linked_worktree(self):  # H5 pin (passes on the parent): .git is a file there
        wt = os.path.join(self.tmp, "wt")
        git(self.root, "worktree", "add", "-q", "--detach", "--", wt)
        self.refused_at(wt, ".git/hooks/pre-commit", [PARENT % (".git/hooks/pre-commit", ".git")])

    # --- R3-1: a separate git directory inside the root (its hooks are below the root) ----------------------------
    def sep_repo(self):
        p = os.path.join(self.tmp, "sep")
        return self.repo("sep", flags=("--separate-git-dir", os.path.join(p, "gd")))

    def test_ctx_equals_hook_in_separate_git_dir(self):  # H5; red on the parent; kills t7-h1, t7-h2
        root = self.sep_repo()
        self.refused_at(root, "gd/hooks/pre-commit", [SAME % "gd/hooks/pre-commit"])

    def test_ctx_below_hook_in_separate_git_dir(self):  # H5; red on the parent; kills t7-h1, t7-h4
        root = self.sep_repo()
        self.refused_at(root, "gd/hooks/pre-push/x", [PARENT % ("gd/hooks/pre-push/x", "gd/hooks/pre-push")])

    # --- R3-2 (4fji): the ``/`` boundary; a name that only shares a planned file's prefix is accepted -------------
    def test_ctx_sibling_of_claude_md_passes(self):  # pin (passes on the parent); kills t7-b1
        self.accepted_ctx("CLAUDE.mdx")

    def test_ctx_sibling_of_gitignore_passes(self):  # pin (passes on the parent); kills t7-b1
        self.accepted_ctx(".gitignorex")

    def test_ctx_sibling_of_settings_passes(self):  # pin (passes on the parent); kills t7-b1
        self.accepted_ctx(".claude/settings.jsonx")

    def test_ctx_sibling_of_ci_workflow_passes(self):  # pin (passes on the parent); kills t7-b1 (ci true)
        self.accepted_ctx(".github/workflows/strict-delivery.ymlx", ci=True)

    def test_ctx_sibling_of_config_passes(self):  # pin (passes on the parent); kills t7-b1
        self.accepted_ctx(".strict-delivery/config.ymlx")

    def test_ctx_sibling_of_pre_commit_hook_passes(self):  # pin (passes on the parent); kills t7-b2
        self.accepted_ctx(".git/hooks/pre-commitx")

    def test_ctx_sibling_of_pre_push_hook_passes(self):  # pin (passes on the parent); kills t7-b2
        self.accepted_ctx(".git/hooks/pre-pushx")

    # --- R3-3 (5x5w, Note H-1): equal under the ASCII map to a planned file -----------------------------------------
    def test_ctx_folds_to_claude_md(self):  # H5; red on the parent; kills t7-f1, t7-f4
        self.overlap("claude.md", SAME % "claude.md")

    def test_ctx_folds_to_gitignore(self):  # H5; red on the parent; kills t7-f1, t7-f2
        self.overlap(".GITIGNORE", SAME % ".GITIGNORE")

    def test_ctx_folds_to_settings(self):  # H5; red on the parent; kills t7-f1, t7-f2
        self.overlap(".claude/Settings.json", SAME % ".claude/Settings.json")

    def test_ctx_folds_to_ci_workflow(self):  # H5; red on the parent; kills t7-f1, t7-f2 (ci true)
        p = ".github/workflows/STRICT-delivery.yml"
        self.overlap(p, SAME % p, ci=True)

    def test_ctx_folds_to_config(self):  # H5; red on the parent; kills t7-f1, t7-f2
        p = ".strict-delivery/Config.yml"
        self.overlap(p, SAME % p)

    def test_ctx_folds_to_pre_commit_hook(self):  # H5; red on the parent; kills t7-f1, t7-f8
        p = ".GIT/hooks/PRE-COMMIT"
        self.overlap(p, SAME % p)

    def test_ctx_folds_to_pre_push_hook(self):  # H5; red on the parent; kills t7-f1, t7-f8
        p = ".git/hooks/Pre-Push"
        self.overlap(p, SAME % p)

    def test_ctx_folds_to_ancestor_dir(self):  # H5; red on the parent; kills t7-f1, t7-f2
        self.overlap(".CLAUDE", SAME % ".CLAUDE")

    # --- R3-3: equal under the map to each state directory and to the state parent -----------------------------------
    def test_ctx_folds_to_state_decisions(self):  # H5; red on the parent; kills t7-f1, t7-f2
        self.overlap(".strict-delivery/state/DECISIONS",
                     INSIDE % (".strict-delivery/state/DECISIONS", ".strict-delivery/state/decisions"))

    def test_ctx_folds_to_state_findings(self):  # H5; red on the parent; kills t7-f1, t7-f2
        self.overlap(".strict-delivery/state/Findings",
                     INSIDE % (".strict-delivery/state/Findings", ".strict-delivery/state/findings"))

    def test_ctx_folds_to_state_claims(self):  # H5; red on the parent; kills t7-f1, t7-f2
        self.overlap(".strict-delivery/state/CLAIMS",
                     INSIDE % (".strict-delivery/state/CLAIMS", ".strict-delivery/state/claims"))

    def test_ctx_folds_to_state_plans(self):  # H5; red on the parent; kills t7-f1, t7-f2
        self.overlap(".strict-delivery/state/Plans",
                     INSIDE % (".strict-delivery/state/Plans", ".strict-delivery/state/plans"))

    def test_ctx_folds_to_state_programs(self):  # H5; red on the parent; kills t7-f1, t7-f2
        self.overlap(".strict-delivery/state/PROGRAMS",
                     INSIDE % (".strict-delivery/state/PROGRAMS", ".strict-delivery/state/programs"))

    def test_ctx_folds_to_playbooks(self):  # H5; red on the parent; kills t7-f1, t7-f2
        self.overlap(".strict-delivery/PLAYBOOKS", INSIDE % (".strict-delivery/PLAYBOOKS", ".strict-delivery/playbooks"))

    def test_ctx_folds_to_state_parent(self):  # H5; red on the parent; kills t7-f1, t7-f2
        self.overlap(".strict-delivery/STATE", INSIDE % (".strict-delivery/STATE", ".strict-delivery/state"))

    # --- R3-3: nested under the map; the configured side in upper case -----------------------------------------------
    def test_ctx_folds_below_claude_md(self):  # H5; red on the parent; kills t7-f1, t7-f7
        self.overlap("Claude.md/x.yml", PARENT % ("Claude.md/x.yml", "CLAUDE.md"))

    def test_ctx_folds_inside_state_dir(self):  # H5; red on the parent; kills t7-f1, t7-f2
        p = ".strict-delivery/STATE/decisions/c.yml"
        self.overlap(p, INSIDE % (p, ".strict-delivery/state/decisions"))

    def test_configured_state_dir_folds_to_ctx(self):  # H5; red on the parent; kills t7-f3, t7-f6
        self.overlap("rec/dec/c.yml", INSIDE % ("rec/dec/c.yml", "Rec/Dec"), decisions="Rec/Dec")

    def test_configured_state_dir_ancestor_folds_to_ctx(self):  # H5; red on the parent; kills t7-f3
        self.overlap("rec", SAME % "rec", decisions="Rec/Dec")

    def test_configured_state_parent_folds_to_ctx(self):  # H5; red on the parent; kills t7-f5
        self.overlap("rec", INSIDE % ("rec", "Rec"), state="Rec")

    def test_ctx_inside_two_state_dirs_equal_under_the_map(self):  # H5; the first configured spelling; kills t7-f13
        self.overlap("rec/x/c.yml", INSIDE % ("rec/x/c.yml", "Rec/X"), claims="Rec/X", plan_state="rec/x")

    # --- R3-3: the hook side in upper case (a separate git directory named GD inside the root) ----------------------
    def sep_repo_upper(self):
        p = os.path.join(self.tmp, "sepu")
        return self.repo("sepu", flags=("--separate-git-dir", os.path.join(p, "GD")))

    def test_ctx_folds_to_hook_in_upper_case_git_dir(self):  # H5; red on the parent; kills t7-f1, t7-f9
        root = self.sep_repo_upper()
        self.refused_at(root, "gd/hooks/pre-commit", [SAME % "gd/hooks/pre-commit"])

    def test_ctx_folds_below_hook_in_upper_case_git_dir(self):  # H5; red on the parent; kills t7-f9, t7-f11
        root = self.sep_repo_upper()
        self.refused_at(root, "gd/hooks/pre-push/x", [PARENT % ("gd/hooks/pre-push/x", "GD/hooks/pre-push")])

    def test_ctx_folds_to_absent_hooks_dir_in_upper_case_git_dir(self):  # H5; red on the parent; kills t7-f10
        root = self.sep_repo_upper()
        os.rename(os.path.join(root, "GD", "hooks"), os.path.join(root, "GD", "hooks.old"))
        self.refused_at(root, "gd/hooks", [SAME % "gd/hooks"])

    # --- R3-3: what the map leaves apart, and what never reaches it -------------------------------------------------
    def test_ctx_differing_after_fold_passes(self):  # control (passes on the parent); kills t7-f12
        self.accepted_ctx("Claude.mdx")

    def test_ctx_nfd_refused_before_the_compare(self):  # Note H-1: non-ASCII never reaches the compare; pin
        # an NFD-spelled context against an NFC state directory: managed refuses the non-ASCII context (init.input)
        self.init_config(paths={"decisions": "réc", "context": "réc/c.yml"})
        before = snapshot(self.root)
        for sub in ("plan", "apply"):
            code, out, _ = self.cmd(sub)
            self.assertEqual((code, out), (1, "FAIL init.input: path: must be a relative path inside the root\n"), sub)
            self.assertEqual(snapshot(self.root), before, sub)

    def test_ua7c0_path_refused_before_the_compare(self):  # PC1, VR4, VR5 (both interpreters); pin
        # U+A7C0 is not printable at Unicode 13 (print_table): config refuses it in every path the compare reads.
        for key in ("state",) + STATE_KEYS + ("context",):
            self.init_config(paths={key: "Ꟁ/c"})
            before = snapshot(self.root)
            for sub in ("plan", "apply"):
                code, out, _ = self.cmd(sub)
                self.assertEqual((code, out), (1, "FAIL init.config: .strict-delivery/config.yml: paths.%s: must be a "
                                                  "non-empty normalised repo-relative path of printable characters; "
                                                  "run /strict-delivery:doctor and /strict-delivery:upgrade\n" % key),
                                 (key, sub))
                self.assertEqual(snapshot(self.root), before, (key, sub))


# --- Fix round 5 (owner answer Q-RC14-1 (a)): the H5 pair matrix, written by hand ------------------------------------
# Rows: every configured key init reads as a path. Columns: every path init plans on the matrix layouts (the files,
# every directory it creates, the hooks directory and both hook files with the hooks missing, installed, or with no
# hooks directory, each state directory, paths.state, paths.context), each with its layout and the ci answer. The
# plan-side completeness check is test_matrix_columns_hold_every_planned_path.
# Part B (4d.2): rows index and receipts (U-1: they feed .gitignore) and specs and plans (the migration targets' keys).
# The migration targets themselves are planned paths only on an UNINITIALISED repository (Q13: neither the migration
# nor the host offer runs where the config exists), and there ``cfg`` is the defaults, so the targets are a single
# configuration, not a row: test_matrix_migration_targets_are_planned_paths is their completeness and cell test.
# Fix round 1 (RB-4): every key of config.DEFAULTS["paths"] is a row, 14 (architecture and reviews included: Q-RC14-1
# (a) "every member of each set"); test_matrix_rows_are_every_configured_path_key pins the set.
MATRIX_ROWS = ("context", "decisions", "findings", "claims", "plan_state", "programs", "playbooks", "state",
               "index", "receipts", "specs", "plans", "architecture", "reviews")
MATRIX_DEFAULT_CTX = ".strict-delivery/context.yml"
DOC_SPEC_DST = "docs/strict-delivery/specs/a.md"
DOC_PLAN_DST = "docs/strict-delivery/plans/x/p.md"
MATRIX_HOOKS = ".git/hooks"
MATRIX_CI = ".github/workflows/strict-delivery.yml"
MATRIX_COLUMNS = (
    (".strict-delivery/config.yml", "missing", False), ("CLAUDE.md", "missing", False),
    (".gitignore", "missing", False), (".claude/settings.json", "missing", False), (".claude", "missing", False),
    (".github/workflows/strict-delivery.yml", "missing", True), (".github/workflows", "missing", True),
    (".github", "missing", True),
    (".git/hooks/pre-commit", "missing", False), (".git/hooks/pre-push", "missing", False),
    (".git/hooks", "missing", False),
    (".git/hooks/pre-commit", "installed", False), (".git/hooks/pre-push", "installed", False),
    (".git/hooks", "installed", False),
    (".git/hooks/pre-commit", "nodir", False), (".git/hooks/pre-push", "nodir", False),
    (".git/hooks", "nodir", False),
    (".strict-delivery/state/decisions", "missing", False), (".strict-delivery/state/findings", "missing", False),
    (".strict-delivery/state/claims", "missing", False), (".strict-delivery/state/plans", "missing", False),
    (".strict-delivery/state/programs", "missing", False), (".strict-delivery/playbooks", "missing", False),
    (".strict-delivery/state", "missing", False), (".strict-delivery/context.yml", "missing", False),
    (".strict-delivery", "missing", False),
)
# The files a plan of each layout writes (besides paths.context and the CI workflow), and the directories it makes.
MATRIX_FILES = {
    "missing": ["CLAUDE.md", ".gitignore", ".claude/settings.json", ".git/hooks/pre-commit", ".git/hooks/pre-push"],
    "installed": ["CLAUDE.md", ".gitignore", ".claude/settings.json"],
    "nodir": ["CLAUDE.md", ".gitignore", ".claude/settings.json", ".git/hooks/pre-commit", ".git/hooks/pre-push"],
}
DOC_MOVES = [("docs/superpowers/plans/x/p.md", DOC_PLAN_DST), ("docs/superpowers/specs/a.md", DOC_SPEC_DST)]
MATRIX_DIRS = [".strict-delivery/state", ".strict-delivery/state/decisions", ".strict-delivery/state/findings",
               ".strict-delivery/state/claims", ".strict-delivery/state/plans", ".strict-delivery/state/programs",
               ".strict-delivery/playbooks"]
_MATRIX_UP = str.maketrans("abcdefghijklmnopqrstuvwxyz", "ABCDEFGHIJKLMNOPQRSTUVWXYZ")  # Note H-1's map, reversed
# (cells, distinct runs). By hand: a column has 2 + (its proper ancestors) relations, each exact and upper case. The 26
# columns hold 85 relations, so a row has 85 x 2 = 170 cells and the 14 rows 14 x 170 = 2380; a row has 110 distinct
# runs (the 4d.1 matrix: 880 / 8), so 14 x 110 = 1540. The review's independent generator (derived from the planned
# paths, ch/4d2-review-1b.md C4) counts (2380, 1540) for the 14 keys of config.DEFAULTS["paths"]; the fix report
# repeats the run on both interpreters.
MATRIX_COUNT = (2380, 1540)
_MATRIX_DOWN = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")
# U-1 oracle, by hand: the cells of the rows index and receipts (which feed .gitignore only) that Q-RC14-5 (a) refuses.
# A value is refused when it is a planned file, below a planned file, a directory init makes or keeps as a parent of a
# planned path, below a state directory or the state parent, the CI workflow path or its directories (ci answered),
# or the hooks directory when it does not exist (layout nodir).
U1_FILES = (".strict-delivery/config.yml", "CLAUDE.md", ".gitignore", ".claude/settings.json", MATRIX_DEFAULT_CTX,
            ".git/hooks/pre-commit", ".git/hooks/pre-push")
U1_DIRS = (".claude", ".strict-delivery", ".strict-delivery/state", ".strict-delivery/state/decisions",
           ".strict-delivery/state/findings", ".strict-delivery/state/claims", ".strict-delivery/state/plans",
           ".strict-delivery/state/programs", ".strict-delivery/playbooks")
U1_BELOW_DIRS = U1_DIRS[2:]  # a state directory or the state parent: a path below it is "inside the state directory"
U1_CI = (MATRIX_CI, ".github/workflows", ".github")


def u1_refused(value, layout, ci):
    v = value.translate(_MATRIX_DOWN)  # Note H-1: the compare is under the ASCII map
    files = [f.translate(_MATRIX_DOWN) for f in U1_FILES]
    if v in files or any(v.startswith(f + "/") for f in files):
        return True
    if v in U1_DIRS or any(v.startswith(d + "/") for d in U1_BELOW_DIRS):
        return True
    if ci and (v in U1_CI or v.startswith(MATRIX_CI + "/")):
        return True
    return v == ".git/hooks" and layout == "nodir"


def matrix_cells():
    """``{(row, value, layout, ci): [(column, relation, fold), ...]}``: rows x columns x (equal, below, above: each
    proper ancestor of the column) x (exact, upper case); cells that configure the same value share one run."""
    out = {}
    for row in MATRIX_ROWS:
        for col, layout, ci in MATRIX_COLUMNS:
            parts = col.split("/")
            rel = [("equal", col), ("below", col + "/x")]
            rel += [("above", "/".join(parts[:i])) for i in range(1, len(parts))]
            for relation, value in rel:
                for fold in ("exact", "upper"):
                    v = value if fold == "exact" else value.translate(_MATRIX_UP)
                    out.setdefault((row, v, layout, ci), []).append((col, relation, fold))
    return out


def named_paths(out):
    """The path each ``FAIL`` line of a refused plan names (``None`` for a line of another shape): the text before the
    first ``": "`` of a ``FAIL init.conflict`` line, or the directory of the ``two ignore lines are equal`` input error."""
    names = []
    ignore = "FAIL init.input: two ignore lines are equal: "
    for line in out.splitlines():
        if line.startswith("FAIL init.conflict: "):
            names.append(line[len("FAIL init.conflict: "):].split(": ", 1)[0])
        elif line.startswith(ignore) and line.endswith("/index.yml"):
            names.append(line[len(ignore):-len("/index.yml")])
        else:
            names.append(None)
    return names


def plan_moves_printed(out):
    """The ``move <src> -> <dst>`` lines of a plan, as ``(src, dst)`` pairs in print order."""
    return [tuple(line[5:].split(" -> ")) for line in out.splitlines() if line.startswith("move ")]


def plan_paths(out, root):
    """``(files, dirs)`` a plan prints: ``{path: content}`` of each ``+++ b/`` diff (every planned file is new on the
    matrix layouts, so its content is the ``+`` lines) and of each ``hook`` line (content None), and the ``mkdir``
    paths."""
    files, dirs, cur = {}, [], None
    for line in out.splitlines():
        if line.startswith("+++ b/"):
            cur = line[6:]
            files[cur] = ""
        elif cur is not None and line.startswith("+"):
            files[cur] += line[1:] + "\n"
        elif cur is not None and line.startswith("@@"):
            continue
        else:
            cur = None
            if line.startswith("mkdir "):
                dirs.append(line[6:-1])
            elif line.startswith("hook "):
                files[os.path.relpath(line[5:], root)] = None
    return files, dirs


class TestPairMatrix(More):
    """Fix round 5 (F-20261125-jmqe, -fqg3, -38fh, -5bb3; owner answer Q-RC14-1 (a)): every cell of the H5 pair matrix
    holds the invariant: plan exit 0 implies apply exit 0 with every planned file written with its planned content and
    every planned directory made; plan exit not 0 implies apply exit not 0 and a byte-identical tree. Mutant ids:
    ch/4d1-mutants-8-table.py (t8-*)."""

    def layouts(self):
        fw = self.make_fw("tagged", version="0.1.0")
        out = {}
        for layout in ("missing", "installed", "nodir"):
            t = os.path.join(self.tmp, "layout-" + layout)
            os.mkdir(t)
            helpers.make_repo(t, {"schema": "config/2", "framework_version": "0.0.0", "profile": "standard",
                                  "commands": answers()["commands"]})
            os.makedirs(os.path.join(t, MATRIX_HOOKS), exist_ok=True)
            if layout == "installed":
                for n in ("pre-commit", "pre-push"):
                    githooks._write(os.path.join(t, MATRIX_HOOKS, n), githooks.shim(n, githooks.framework_dir()))
            elif layout == "nodir":
                os.rename(os.path.join(t, MATRIX_HOOKS), os.path.join(t, ".git", "hooks.old"))
            out[layout] = t
        ans = {}
        for ci in (False, True):
            ans[ci] = os.path.join(self.tmp, "answers-%s.yml" % ci)
            with open(ans[ci], "w", encoding="utf-8") as fh:
                fh.write(yamlsub.emit(answers(ci=ci)))
        return fw, out, ans

    def matrix_main(self, fw, ans, sub, root, ci):
        with mock.patch.object(plugin, "framework_dir", return_value=fw), \
                mock.patch.object(init.gitinfo, "head_sha", side_effect=init.GitNotFound("no git")):
            return self.run_init(sub, "--root", root, "--answers", ans[ci])[:2]

    def test_matrix_columns_hold_every_planned_path(self):  # completeness: a planned path outside the columns fails
        fw, lay, ans = self.layouts()
        cols = set()
        for col, _layout, _ci in MATRIX_COLUMNS:
            parts = col.split("/")
            cols.update("/".join(parts[:i]) for i in range(1, len(parts) + 1))
        for layout, tmpl in sorted(lay.items()):
            for ci in (False, True):
                root = os.path.join(self.tmp, "c-%s-%s" % (layout, ci))
                shutil.copytree(tmpl, root, symlinks=True)
                code, out = self.matrix_main(fw, ans, "plan", root, ci)
                files, dirs = plan_paths(out, root)
                want = MATRIX_FILES[layout] + [MATRIX_DEFAULT_CTX] + ([MATRIX_CI] if ci else [])
                self.assertEqual((code, sorted(files), dirs), (0, sorted(want), MATRIX_DIRS), (layout, ci, out))
                self.assertEqual(plan_moves_printed(out), [], (layout, ci, out))  # an initialised repository: no moves
                for p in list(files) + dirs:
                    parts = p.split("/")
                    self.assertEqual(["/".join(parts[:i]) for i in range(1, len(parts) + 1)
                                      if "/".join(parts[:i]) not in cols], [], (layout, ci, p))

    def test_matrix_rows_are_every_configured_path_key(self):  # RB-4: the 14 keys of paths, written out by hand
        self.assertEqual(sorted(MATRIX_ROWS), sorted([
            "state", "decisions", "findings", "claims", "plan_state", "programs", "playbooks", "receipts", "context",
            "architecture", "index", "specs", "plans", "reviews"]))
        self.assertEqual(sorted(MATRIX_ROWS), sorted(config.DEFAULTS["paths"]))

    def test_pair_matrix(self):  # H5, every cell; the red cells on 118ccec are listed in ch/4d1-fix-5.md
        fw, lay, ans = self.layouts()
        cells = matrix_cells()
        self.assertEqual((sum(len(v) for v in cells.values()), len(cells)), MATRIX_COUNT)
        shim = {n: githooks.shim(n, githooks.framework_dir()) for n in ("pre-commit", "pre-push")}
        for i, ((row, value, layout, ci), labels) in enumerate(sorted(cells.items())):
            with self.subTest(row=row, value=value, layout=layout, ci=ci, cells=len(labels)):
                root = os.path.join(self.tmp, "m%d" % i)
                shutil.copytree(lay[layout], root, symlinks=True)
                helpers.write_record(root, ".strict-delivery/config.yml", {
                    "schema": "config/2", "framework_version": "0.0.0", "profile": "standard",
                    "commands": answers()["commands"], "paths": {row: value}})
                before = snapshot(root)
                pcode, pout = self.matrix_main(fw, ans, "plan", root, ci)
                acode, aout = self.matrix_main(fw, ans, "apply", root, ci)
                if row in ("index", "receipts"):  # U-1: the hand-written oracle of the refused cells (red on 9390daf)
                    self.assertEqual(pcode != 0, u1_refused(value, layout, ci), (pout, aout))
                if pcode != 0:
                    self.assertNotEqual(acode, 0, (pout, aout))
                    self.assertEqual(snapshot(root), before, aout)
                    named = named_paths(pout)  # RB-5: every line names a path, and one is this cell's value or column
                    want = {value.translate(_MATRIX_DOWN)} | {c.translate(_MATRIX_DOWN) for c, _r, _f in labels}
                    self.assertTrue(named and None not in named, pout)
                    self.assertTrue(any(n.translate(_MATRIX_DOWN) in want for n in named), (sorted(want), pout))
                    continue
                self.assertEqual(acode, 0, (pout, aout))
                files, dirs = plan_paths(pout, root)
                ctx = value if row == "context" else MATRIX_DEFAULT_CTX
                want = MATRIX_FILES[layout] + [ctx] + ([MATRIX_CI] if ci else [])
                self.assertEqual(sorted(files), sorted(want), pout)
                for p, text in files.items():
                    path = os.path.join(root, p)
                    self.assertFalse(os.path.islink(path), p)
                    with open(path, "rb") as fh:
                        got = fh.read()
                    self.assertEqual(got, shim[os.path.basename(p)] if text is None else text.encode("utf-8"), p)
                self.assertEqual(files[ctx], CONTEXT_YML)
                for d in dirs:
                    path = os.path.join(root, d)
                    self.assertTrue(os.path.isdir(path) and not os.path.islink(path), d)

    # --- the texts of the members the matrix found red on 118ccec (one test per shape) ------------------------------
    overlap = TestReview2.overlap

    def install_hooks(self, mode=0o755):
        for n in ("pre-commit", "pre-push"):
            p = os.path.join(self.root, MATRIX_HOOKS, n)
            githooks._write(p, githooks.shim(n, githooks.framework_dir()))
            os.chmod(p, mode)

    def test_ctx_equals_installed_pre_commit_hook(self):  # R4-1 (jmqe); red on 118ccec; kills t8-h1, t8-h2
        self.install_hooks()
        self.overlap(".git/hooks/pre-commit", SAME % ".git/hooks/pre-commit")

    def test_ctx_equals_installed_pre_push_hook(self):  # R4-1 (jmqe); red on 118ccec; kills t8-h1, t8-h2
        self.install_hooks()
        self.overlap(".git/hooks/pre-push", SAME % ".git/hooks/pre-push")

    def test_ctx_folds_to_installed_hook(self):  # R4-1 under the map; red on 118ccec; kills t8-h1
        self.install_hooks()
        self.overlap(".GIT/HOOKS/PRE-PUSH", SAME % ".GIT/HOOKS/PRE-PUSH")

    def test_ctx_equals_stale_hook(self):  # R4-1 sibling (a present hook, stale mode); red on 118ccec; kills t8-h1
        self.install_hooks(mode=0o644)
        self.overlap(".git/hooks/pre-commit", SAME % ".git/hooks/pre-commit")

    def test_ctx_equals_foreign_hook_keeps_existing_text(self):  # pin: a foreign hook is its own conflict, one line
        self.write(".git/hooks/pre-commit", "#!/bin/sh\necho mine\n")
        self.overlap(".git/hooks/pre-commit", "githooks.pre-commit: foreign")

    def test_ctx_below_installed_hook_keeps_existing_text(self):  # pin: managed's own text, one line (PO2)
        self.install_hooks()
        p = ".git/hooks/pre-commit"
        self.overlap(p + "/x", PARENT % (p + "/x", p))

    def test_state_equals_claude_md(self):  # R4-4 (5bb3); red on 118ccec; kills t8-s1, t8-s2
        self.overlap(MATRIX_DEFAULT_CTX, SAME % "CLAUDE.md", claims="CLAUDE.md")

    def test_state_below_gitignore(self):  # R4-4; red on 118ccec; kills t8-s1, t8-s3
        self.overlap(MATRIX_DEFAULT_CTX, PARENT % (".gitignore/x", ".gitignore"), decisions=".gitignore/x")

    def test_state_equals_settings(self):  # R4-4; red on 118ccec; kills t8-s1
        self.overlap(MATRIX_DEFAULT_CTX, SAME % ".claude/settings.json", playbooks=".claude/settings.json")

    def test_state_equals_ci_workflow(self):  # R4-4 (ci true); red on 118ccec; kills t8-s1
        self.overlap(MATRIX_DEFAULT_CTX, SAME % MATRIX_CI, ci=True, programs=MATRIX_CI)

    def test_state_folds_to_claude_md(self):  # R4-4 under the map; red on 118ccec; kills t8-s4
        self.overlap(MATRIX_DEFAULT_CTX, SAME % "claude.md", findings="claude.md")

    def test_state_equals_planned_hook(self):  # R4-4; red on 118ccec; kills t8-s5
        self.overlap(MATRIX_DEFAULT_CTX, SAME % ".git/hooks/pre-commit", plan_state=".git/hooks/pre-commit")

    def test_state_below_planned_hook_no_hooks_dir(self):  # R4-4; red on 118ccec; kills t8-s5, t8-s3
        self.hide_hooks_dir()
        p = ".git/hooks/pre-push"
        self.overlap(MATRIX_DEFAULT_CTX, PARENT % (p + "/x", p), claims=p + "/x")

    def test_state_folds_to_planned_hook(self):  # R4-4 under the map; red on 118ccec; kills t8-s5, t8-s4
        self.overlap(MATRIX_DEFAULT_CTX, SAME % ".GIT/HOOKS/PRE-PUSH", claims=".GIT/HOOKS/PRE-PUSH")

    def test_state_equals_installed_hook_keeps_existing_text(self):  # pin: _dir_plan's own text, one line
        self.install_hooks()
        p = ".git/hooks/pre-commit"
        self.overlap(MATRIX_DEFAULT_CTX, "%s: exists and is not a directory" % p, claims=p)

    def test_state_above_planned_file_passes(self):  # control (passes on 118ccec): a state directory holds a file
        self.init_config(paths={"claims": ".claude"})
        code, out = self.cmd("apply")[:2]
        self.assertEqual(code, 0, out)
        self.assertTrue(os.path.isfile(os.path.join(self.root, ".claude/settings.json")))

    hide_hooks_dir = TestReview3.hide_hooks_dir

    def ignore_pair(self, decisions, findings, line):
        self.init_config(paths={"decisions": decisions, "findings": findings})
        before = snapshot(self.root)
        for sub in ("plan", "apply"):
            code, out, _ = self.cmd(sub)
            self.assertEqual((code, out), (1, "FAIL init.input: two ignore lines are equal: %s\n" % line), sub)
            self.assertEqual(snapshot(self.root), before, sub)

    def test_decisions_folds_to_findings(self):  # R4-3 (38fh), decision U-3 (a); red on 118ccec; kills t8-u1
        self.ignore_pair(".strict-delivery/state/Findings", ".strict-delivery/state/findings",
                         ".strict-delivery/state/findings/index.yml")

    def test_findings_folds_to_decisions(self):  # R4-3; red on 118ccec; kills t8-u1, t8-u2
        self.ignore_pair("rec/dec", "REC/Dec", "REC/Dec/index.yml")

    def test_decisions_equals_findings_keeps_existing_text(self):  # pin: the exact pair (templates' own check)
        self.ignore_pair("rec/dec", "rec/dec", "rec/dec/index.yml")

    def test_decisions_nested_in_findings_under_the_map_passes(self):  # DR8 under the map: created once; control
        self.init_config(paths={"decisions": "REC/x", "findings": "rec/x/y"})
        code, out = self.cmd("apply")[:2]
        self.assertEqual(code, 0, out)
        self.assertTrue(os.path.isdir(os.path.join(self.root, "rec/x/y")))


# --- Task 4d.2 Part B: the migration and the branch-protection offer (Producer 8), the folded findings, U-1 ------------
SPEC_OLD = "docs/superpowers/specs/a.md"
PLAN_OLD = "docs/superpowers/plans/x/p.md"
SPEC_NEW = "docs/strict-delivery/specs/a.md"
PLAN_NEW = "docs/strict-delivery/plans/x/p.md"
G_REPO = "api repos/o/n"
G_PROT = "api repos/o/n/branches/main/protection"
G_PUT = "api -X PUT repos/o/n/branches/main/protection --input -"
G_PATCH = "api -X PATCH repos/o/n -F allow_merge_commit=true -F allow_squash_merge=false -F allow_rebase_merge=false"
G_NF = "gh: Branch not protected (HTTP 404)\n"
BODY = ('{"required_status_checks": null, "enforce_admins": true, "required_pull_request_reviews": '
        '{"required_approving_review_count": 0}, "restrictions": null}')


def repo_json(merge=True, squash=False, rebase=False):
    return json.dumps({"id": 1, "allow_merge_commit": merge, "allow_squash_merge": squash, "allow_rebase_merge": rebase})


def prot_json(admins=True, pr=True):
    body = {"enforce_admins": {"enabled": admins}}
    if pr:
        body["required_pull_request_reviews"] = {"required_approving_review_count": 0}
    return json.dumps(body)


def unprot(merge_only=True):
    flag = repo_json() if merge_only else repo_json(True, True, True)
    return {G_REPO: (flag, "", 0), G_PROT: ("", G_NF, 1), G_PUT: ("{}", "", 0), G_PATCH: ("{}", "", 0)}


class Mig(More):
    """Producer 8 (rows IN-*, AM-F8): ``init.main`` on ``make_repo``-style fixtures, with a fake ``gh`` and a tracing
    ``git`` that are the test's own scripts in its own temp directory, first on PATH."""

    def setUp(self):
        super().setUp()
        self.ghdir = None
        self.gitdir = None
        self.real_git = shutil.which("git")

    def prepend_path(self, d):
        patcher = mock.patch.dict(os.environ, {"PATH": d + os.pathsep + os.environ["PATH"]})
        patcher.start()
        self.addCleanup(patcher.stop)

    def gh(self, rules):
        """A ``gh`` that logs ``$*`` and, for a write call, whether config, the old and the new path exist (cwd = root)."""
        d = self.ghdir = os.path.join(self.tmp, "ghbin")
        os.makedirs(d, exist_ok=True)
        lines = ["#!/bin/sh", "D='%s'" % d, 'echo "$*" >> "$D/argv.log"', 'case "$1 $2" in "api -X")',
                 "  if [ -f .strict-delivery/config.yml ]; then c=1; else c=0; fi",
                 "  if [ -e %s ]; then s=1; else s=0; fi" % SPEC_OLD,
                 "  if [ -e %s ]; then t=1; else t=0; fi" % SPEC_NEW,
                 '  echo "cfg=$c src=$s dst=$t" >> "$D/state.log";; esac',
                 'case "$*" in "api -X PUT"*) /bin/cat > "$D/body.txt";; esac', 'case "$*" in']
        for i, (key, (out, err, code)) in enumerate(rules.items()):
            for ext, data in (("out", out), ("err", err)):
                with open(os.path.join(d, "%s.%d" % (ext, i)), "w", encoding="utf-8") as fh:
                    fh.write(data)
            lines.append("'%s') /bin/cat \"$D/out.%d\"; /bin/cat \"$D/err.%d\" >&2; exit %d;;" % (key, i, i, code))
        lines += ["esac", "echo unexpected >&2", "exit 99"]
        with open(os.path.join(d, "gh"), "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
        os.chmod(os.path.join(d, "gh"), 0o755)
        self.prepend_path(d)

    def ghlog(self, name="argv.log"):
        if self.ghdir is None:
            return []
        try:
            with open(os.path.join(self.ghdir, name), encoding="utf-8") as fh:
                return fh.read().splitlines()
        except FileNotFoundError:
            return []

    def no_gh(self):
        """PATH holds ``git`` and nothing else: no ``gh`` can be found."""
        d = os.path.join(self.tmp, "gitonly")
        os.makedirs(d, exist_ok=True)
        os.symlink(self.real_git, os.path.join(d, "git"))
        patcher = mock.patch.dict(os.environ, {"PATH": d})
        patcher.start()
        self.addCleanup(patcher.stop)

    def trace_git(self, fail_on=None):
        """A ``git`` that logs ``$*`` and runs the real one; ``fail_on`` is a ``case`` pattern of ``$*`` that exits 1."""
        d = self.gitdir = os.path.join(self.tmp, "gitbin")
        os.makedirs(d, exist_ok=True)
        lines = ["#!/bin/sh", 'echo "$*" >> \'%s/git.log\'' % d]
        if fail_on:
            lines += ['case "$*" in', "%s) echo boom >&2; exit 1;;" % fail_on, "esac"]
        lines.append("exec '%s' \"$@\"" % self.real_git)
        with open(os.path.join(d, "git"), "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
        os.chmod(os.path.join(d, "git"), 0o755)
        self.prepend_path(d)

    def gitlog(self):
        with open(os.path.join(self.gitdir, "git.log"), encoding="utf-8") as fh:
            return fh.read().splitlines()

    def docs(self, spec="spec a\n", plan="plan p\n", **more):
        self.write(SPEC_OLD, spec)
        self.write(PLAN_OLD, plan)
        for rel, text in more.items():
            self.write(rel.replace("__", "/"), text)
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", "docs")

    def remote(self, url, name="origin"):
        git(self.root, "remote", "add", name, url)

    def mc(self, sub, migrate=None, protect=False, js=False, root=None, **over):
        a = answers(protect_base=protect, **over)
        if migrate is not None:
            a["migrate"] = migrate
        self.put_answers(a)
        return self.run_init(sub, "--root", root or self.root, "--answers", self.ans, *(["--json"] if js else []))

    def questions_json(self):
        code, out, _ = self.run_init("questions", "--root", self.root, "--json")
        self.assertEqual(code, 0, out)
        return json.loads(out)

    def tree(self, root):
        """The work tree (never ``.git``) as ``{relative path: (mode, bytes)}``."""
        return {os.path.relpath(p, root): (m, d) for p, m, d in snapshot(root)
                if os.path.relpath(p, root).split(os.sep)[0] != ".git"}

    # --- questions (IN-Q*) ---------------------------------------------------------------------------------------
    def test_in_q1_questions_no_docs(self):  # IN-Q1; red on 9390daf (the control); kills fb-1
        self.gh({})
        before = snapshot(self.root)
        self.assertEqual(self.questions_json()["superpowers_docs"], [])
        self.assertEqual(self.ghlog(), [])
        self.assertEqual(snapshot(self.root), before)
        self.docs()  # control: the same call lists the moves once documents are tracked
        self.assertEqual(self.questions_json()["superpowers_docs"], [[PLAN_OLD, PLAN_NEW], [SPEC_OLD, SPEC_NEW]])

    def test_in_q2_questions_pairs_sorted(self):  # IN-Q2, Q15; kills b-1
        self.docs()
        self.assertEqual(self.questions_json()["superpowers_docs"], [[PLAN_OLD, PLAN_NEW], [SPEC_OLD, SPEC_NEW]])

    def test_in_q3_questions_cfg_source(self):  # IN-Q3; kills b-2
        self.docs()
        q = self.questions_json()
        self.assertEqual((q["initialised"], q["superpowers_docs"][1]), (False, [SPEC_OLD, SPEC_NEW]))
        self.init_config(paths={"specs": "docs/s2"})
        q = self.questions_json()
        self.assertEqual((q["initialised"], q["superpowers_docs"]), (True, [[PLAN_OLD, PLAN_NEW], [SPEC_OLD, "docs/s2/a.md"]]))

    def test_in_q4_untracked_only(self):  # IN-Q4; red on 9390daf (the control)
        self.write(SPEC_OLD, "new\n")
        self.assertEqual(self.questions_json()["superpowers_docs"], [])
        git(self.root, "add", SPEC_OLD)  # control: the same file, once tracked, is listed
        self.assertEqual(self.questions_json()["superpowers_docs"], [[SPEC_OLD, SPEC_NEW]])

    def test_in_q5_non_utf8_tracked_path(self):  # IN-Q5 (CD23), H6
        blob = git(self.root, "hash-object", "-w", "README.md")
        cacheinfo = b"100644," + blob.encode() + b",docs/superpowers/specs/\xff.md"
        subprocess.run([os.fsencode(a) for a in ("git", "-C", self.root, "update-index", "--add", "--cacheinfo")]
                       + [cacheinfo], check=True)
        before = snapshot(self.root)
        for sub in ("questions", "plan", "apply"):  # apply: nothing is written before the refusal (RB-9)
            argv = [sub, "--root", self.root] + (["--answers", self.put_answers(migrate=True)] if sub != "questions" else [])
            code, out, _ = self.run_init(*argv)
            self.assertEqual((code, out), (1, "FAIL init.input: git ls-files gave output that is not valid UTF-8\n"), sub)
        self.assertEqual(snapshot(self.root), before)

    def test_in_q6_conflicting_docs_listed(self):  # IN-Q6 (CD3)
        self.write(SPEC_NEW, "exists\n")
        self.docs()
        self.assertEqual(self.questions_json()["superpowers_docs"], [[PLAN_OLD, PLAN_NEW], [SPEC_OLD, SPEC_NEW]])

    # --- the migrate answer (IN-L*) ------------------------------------------------------------------------------
    def test_in_l1_migrate_with_docs(self):  # IN-L1; kills fb-3
        self.docs()
        for value in (True, False):
            self.assertEqual(self.mc("plan", migrate=value)[0], 0, value)

    def test_in_l2_migrate_required(self):  # IN-L2; kills b-3
        self.docs()
        code, out, _ = self.mc("plan")
        self.assertEqual((code, out.startswith("FAIL init.answers: migrate: ")), (1, True), out)

    def test_in_l3_migrate_refused_without_docs(self):  # IN-L3 (also untracked only); kills fb-2
        for untracked in (False, True):
            if untracked:
                self.write(SPEC_OLD, "x\n")
            for value in (True, False):
                self.assertEqual(self.mc("plan", migrate=value)[:2],
                                 (1, "FAIL init.answers: migrate: no superpowers documents are tracked\n"), (untracked, value))

    def test_in_l5_protect_base_required(self):  # IN-L5; kills fb-4 (the schema's required key)
        a = answers()
        del a["protect_base"]
        self.put_answers(a)
        code, out, _ = self.run_init("plan", "--root", self.root, "--answers", self.ans)
        self.assertEqual((code, out.startswith("FAIL init.answers: protect_base: ")), (1, True), out)
        self.assertEqual(out.count("\n"), 1, out)

    # --- plan output (IN-P*) -------------------------------------------------------------------------------------
    def test_in_p1_plan_prints_moves(self):  # IN-P1; kills b-4
        self.docs()
        before, index = snapshot(self.root), git(self.root, "ls-files", "-s")
        code, out, _ = self.mc("plan", migrate=True)
        self.assertEqual(code, 0, out)
        self.assertIn("move %s -> %s\nmove %s -> %s\n" % (PLAN_OLD, PLAN_NEW, SPEC_OLD, SPEC_NEW), out)
        self.assertEqual((snapshot(self.root), git(self.root, "ls-files", "-s")), (before, index))

    def test_in_p2_plan_diffs(self):  # IN-P2; kills b-5
        self.docs(spec="see docs/superpowers/specs/a.md here\n", **{"README.md": "ref docs/superpowers/specs/a.md\r\nl2\r\n"})
        out = self.mc("plan", migrate=True)[1]
        self.assertIn("--- a/%s\n+++ b/%s\n@@ -1 +1 @@\n-see docs/superpowers/specs/a.md here\n"
                      "+see docs/strict-delivery/specs/a.md here\n" % (SPEC_OLD, SPEC_NEW), out)
        self.assertIn("--- a/README.md\n+++ b/README.md\n", out)
        self.assertIn("-ref docs/superpowers/specs/a.md\\r\n+ref docs/strict-delivery/specs/a.md\\r\n", out)

    def test_in_p3_plan_notes(self):  # IN-P3; kills b-6
        self.docs(**{"README.md": "see [a](a.md)\n"})
        self.write("docs/superpowers/specs/new.md", "n\n")
        out = self.mc("plan", migrate=True)[1]
        notes = ["note: README.md:1: mentions a.md; not rewritten\n",
                 "note: docs/superpowers/specs/new.md: untracked; not moved\n"]
        for n in notes:
            self.assertEqual(out.count(n), 1, out)
            self.assertGreater(out.index(n), out.rindex("move "))

    def test_in_p4_plan_host_calls_verbatim(self):  # IN-P4; kills b-7
        self.docs()
        self.remote("https://github.com/o/n.git")
        self.gh(unprot(merge_only=False))
        out = self.mc("plan", migrate=False, protect=True)[1]
        self.assertIn("call: gh api -X PUT repos/o/n/branches/main/protection --input -\nbody: %s\n"
                      "call: gh api -X PATCH repos/o/n -F allow_merge_commit=true -F allow_squash_merge=false "
                      "-F allow_rebase_merge=false\n" % BODY, out)
        self.assertEqual(self.ghlog(), [G_REPO, G_PROT])  # reads only: nothing ran

    def test_in_p5_plan_migrate_false_silent(self):  # IN-P5, IN-M1; red on 9390daf (the exit code)
        self.docs(spec="see docs/superpowers/specs/a.md\n")
        code, out, err = self.mc("plan", migrate=False)
        self.assertEqual((code, err), (0, ""), out)
        for text in ("move ", "docs/superpowers", "mentions", "untracked"):
            self.assertNotIn(text, out)
        # the whole output, by hand: the new-file diffs of the init writes, the directories and the hooks (nothing of
        # the documents), 10 + 23 + 7 + 6 + 47 body lines under the five hunk headers
        head = [line for line in out.splitlines() if not line.startswith(("+", " ")) or line.startswith("+++")]
        hooks = os.path.join(self.root, ".git", "hooks")
        self.assertEqual(head, [
            "--- a/.strict-delivery/config.yml", "+++ b/.strict-delivery/config.yml", "@@ -0,0 +1,10 @@",
            "mkdir .strict-delivery/state/", "mkdir .strict-delivery/state/decisions/",
            "mkdir .strict-delivery/state/findings/", "mkdir .strict-delivery/state/claims/",
            "mkdir .strict-delivery/state/plans/", "mkdir .strict-delivery/state/programs/",
            "mkdir .strict-delivery/playbooks/",
            "--- a/CLAUDE.md", "+++ b/CLAUDE.md", "@@ -0,0 +1,23 @@",
            "--- a/.gitignore", "+++ b/.gitignore", "@@ -0,0 +1,7 @@",
            "--- a/.claude/settings.json", "+++ b/.claude/settings.json", "@@ -0,0 +1,6 @@",
            "--- a/.strict-delivery/context.yml", "+++ b/.strict-delivery/context.yml", "@@ -0,0 +1,47 @@",
            "hook " + os.path.join(hooks, "pre-commit"), "hook " + os.path.join(hooks, "pre-push")])
        self.assertEqual(len(out.splitlines()), len(head) + 10 + 23 + 7 + 6 + 47, out)

    def test_in_p6_plan_conflict_exit_1(self):  # IN-P6; kills b-8
        self.write(SPEC_NEW, "exists\n")
        self.docs()
        before = snapshot(self.root)
        self.assertEqual(self.mc("plan", migrate=True)[:2], (1, "FAIL init.conflict: %s: exists\n" % SPEC_NEW))
        self.assertEqual(snapshot(self.root), before)

    def test_in_p7_plan_reads_host(self):  # IN-P7 (Q12): a plan reads, never writes
        self.remote("https://github.com/o/n.git")
        self.gh(unprot())
        before = snapshot(self.root)
        self.assertEqual(self.mc("plan", protect=True)[0], 0)
        self.assertEqual((self.ghlog(), snapshot(self.root)), ([G_REPO, G_PROT], before))

    def test_in_h8_plan_host_error(self):  # IN-H8 (Q12): FAIL init.protection, exit 1, nothing written
        self.remote("https://github.com/o/n.git")
        self.no_gh()
        before = snapshot(self.root)
        self.assertEqual(self.mc("plan", protect=True)[:2], (1, "FAIL init.protection: gh api repos/o/n: gh not found on PATH\n"))
        self.assertEqual(snapshot(self.root), before)

    def test_in_p8_plan_json(self):  # IN-P8 (CD23); kills b-9
        self.docs(**{"README.md": "see docs/superpowers/specs/a.md\n"})
        self.write("docs/superpowers/specs/new.md", "n\n")
        self.remote("https://github.com/o/n.git")
        self.gh(unprot())
        code, out, _ = self.mc("plan", migrate=True, protect=True, js=True)
        self.assertEqual(code, 0, out)
        d = json.loads(out)
        self.assertEqual(d["moves"], [[PLAN_OLD, PLAN_NEW], [SPEC_OLD, SPEC_NEW]])
        self.assertEqual([r["path"] for r in d["rewrites"]], ["README.md"])
        self.assertTrue(d["rewrites"][0]["diff"].startswith("--- a/README.md\n+++ b/README.md\n"))
        self.assertEqual(d["notes"], ["docs/superpowers/specs/new.md: untracked; not moved"])
        self.assertEqual(d["host_calls"], [["gh", "api", "-X", "PUT", "repos/o/n/branches/main/protection", "--input", "-"]])
        text = self.mc("plan", migrate=True, protect=True)[1]  # the same facts in the text form
        self.assertIn("note: " + d["notes"][0], text)
        self.assertIn(d["rewrites"][0]["diff"], text)
        self.assertTrue(all("move %s -> %s\n" % tuple(m) in text for m in d["moves"]))

    def test_in_p9_plan_odd_names(self):  # IN-P9; PM-S18, Q1
        names = ["a b.md", "it's.md", 'q"x.md']
        self.docs(**{"docs__superpowers__specs__" + n: "t\n" for n in names})
        out = self.mc("plan", migrate=True)[1]
        for n in names:
            self.assertEqual(out.splitlines().count("move docs/superpowers/specs/%s -> docs/strict-delivery/specs/%s" % (n, n)), 1, n)

    def test_in_p9_odd_names_refused(self):  # IN-P9: a name that cannot be shown or checked is a conflict, never raw
        self.docs(**{"docs__superpowers__specs__x\ny.md": "t\n", "docs__superpowers__specs__é.md": "t\n"})
        code, out, _ = self.mc("plan", migrate=True)
        text = "path: must be a relative path inside the root"
        self.assertEqual((code, out), (1, "FAIL init.conflict: docs/strict-delivery/specs/x\\ny.md: %s\n"
                                           "FAIL init.conflict: docs/strict-delivery/specs/é.md: %s\n" % (text, text)))

    # --- apply (IN-A*, IN-M*) ------------------------------------------------------------------------------------
    def test_in_a2_migration_only_on_word(self):  # IN-A2, IN-M1, AM-I1 (the plan's name)
        self.docs(spec="see docs/superpowers/specs/a.md\n")
        self.trace_git()
        before = self.tree(self.root)
        code, out, _ = self.mc("apply", migrate=False)
        self.assertEqual(code, 0, out)
        self.assertFalse(any("mv" in line.split() for line in self.gitlog()))
        self.assertEqual(self.read(SPEC_OLD), "see docs/superpowers/specs/a.md\n")
        self.assertEqual(self.tree(self.root)[SPEC_OLD], before[SPEC_OLD])

    def test_migration_only_on_word(self):  # the plan's test name: answers migrate false leaves the file
        self.docs()
        self.assertEqual(self.mc("apply", migrate=False)[0], 0)
        self.assertTrue(os.path.exists(os.path.join(self.root, SPEC_OLD)))
        self.assertFalse(os.path.exists(os.path.join(self.root, SPEC_NEW)))

    def test_in_a3_moves_staged_edits_not(self):  # IN-A3, IN-M2, IN-M3; kills b-11, b-35
        self.docs(spec="see docs/superpowers/specs/a.md\n", **{"README.md": "see docs/superpowers/specs/a.md\n"})
        code, out, _ = self.mc("apply", migrate=True)
        self.assertEqual(code, 0, out)
        status = git(self.root, "status", "--porcelain", "--untracked-files=no").splitlines()
        self.assertIn("R  %s -> %s" % (PLAN_OLD, PLAN_NEW), status)
        self.assertIn("RM %s -> %s" % (SPEC_OLD, SPEC_NEW), status)
        self.assertEqual(git(self.root, "diff", "--name-only").splitlines(), ["README.md", SPEC_NEW])  # unstaged edits
        self.assertEqual(git(self.root, "diff", "--cached", "--name-only", "--no-renames").splitlines(),
                         [PLAN_NEW, SPEC_NEW, PLAN_OLD, SPEC_OLD])
        self.assertEqual(self.read(SPEC_NEW), "see docs/strict-delivery/specs/a.md\n")
        self.assertEqual(self.read("README.md"), "see docs/strict-delivery/specs/a.md\n")

    def test_in_a4_no_host_call_when_false(self):  # IN-A4; kills b-12
        self.remote("https://github.com/o/n.git")
        self.gh(unprot())
        other = os.path.join(self.tmp, "a4-other")
        shutil.copytree(self.root, other, symlinks=True)  # an unwritten copy, for the apply without gh
        self.assertEqual(self.mc("apply", protect=False)[0], 0)
        self.assertEqual(self.ghlog(), [])
        self.no_gh()  # and a missing gh is no error, on plan and on apply
        self.assertEqual(self.mc("plan", protect=False, root=other)[0], 0)
        code, out, _ = self.mc("apply", protect=False, root=other)
        self.assertEqual(code, 0, out)
        self.assertNotIn("FAIL", out)
        self.assertTrue(os.path.isfile(os.path.join(other, ".strict-delivery/config.yml")))

    def test_in_a5_put_runs_with_body_on_stdin(self):  # IN-A5, IN-A1, IN-M3; kills b-13
        self.docs()
        self.remote("https://github.com/o/n.git")
        self.gh(unprot())
        code, out, _ = self.mc("apply", migrate=True, protect=True)
        self.assertEqual(code, 0, out)
        self.assertEqual(self.ghlog(), [G_REPO, G_PROT, G_PUT])
        self.assertEqual(self.ghlog("body.txt"), [BODY])
        self.assertEqual(self.ghlog("state.log"), ["cfg=1 src=0 dst=1"])  # the file writes and the moves came first

    def test_in_a6_patch_runs(self):  # IN-A6; kills b-13
        self.remote("https://github.com/o/n.git")
        self.gh(unprot(merge_only=False))
        self.assertEqual(self.mc("apply", protect=True)[0], 0)
        self.assertEqual(self.ghlog(), [G_REPO, G_PROT, G_PUT, G_PATCH])

    def test_in_a7_nothing_to_do(self):  # IN-A7: protected with everything, Q9 (no host call of any kind)
        self.remote("https://github.com/o/n.git")
        self.gh({G_REPO: (repo_json(), "", 0), G_PROT: (prot_json(), "", 0)})
        code, out, _ = self.mc("apply", protect=True)
        self.assertEqual((code, self.ghlog(), "protection of" in out), (0, [G_REPO, G_PROT], False))

    def test_in_a8_protected_missing_note(self):  # IN-A8, HC-C13 (Q9): a note each, no write
        self.remote("https://github.com/o/n.git")
        self.gh({G_REPO: (repo_json(True, True, False), "", 0), G_PROT: (prot_json(admins=False), "", 0)})
        code, out, _ = self.mc("apply", protect=True)
        self.assertEqual((code, self.ghlog()), (0, [G_REPO, G_PROT]))
        self.assertIn("note: protection of main on o/n: administrators not enforced\n"
                      "note: protection of main on o/n: squash merge allowed\n", out)

    def test_target_exists_conflict_and_nothing_moved(self):  # IN-A9 (the plan's name); kills b-8
        self.write(SPEC_NEW, "exists\n")
        self.docs()
        before = snapshot(self.root)
        self.assertEqual(self.mc("apply", migrate=True)[:2], (1, "FAIL init.conflict: %s: exists\n" % SPEC_NEW))
        self.assertEqual(snapshot(self.root), before)

    def test_in_a10_block_survives_rewrite(self):  # IN-A10 (Q16); kills b-35, b-11
        old = "x docs/superpowers/specs/a.md y\n"
        self.docs(**{"CLAUDE.md": old, ".gitignore": old})
        code, out, _ = self.mc("apply", migrate=True)
        self.assertEqual(code, 0, out)
        for path in ("CLAUDE.md", ".gitignore"):
            text = self.read(path)
            self.assertIn("x docs/strict-delivery/specs/a.md y\n", text, path)
        self.assertEqual(managed.find_block(self.read("CLAUDE.md"), managed._KIND_STYLE["claude-block"]).kind, "claude-block")
        self.assertEqual(managed.find_block(self.read(".gitignore"), managed._KIND_STYLE["gitignore-block"]).kind,
                         "gitignore-block")

    def test_in_a10_workflow_holding_a_reference(self):  # IN-A10 (RB-9): a generated workflow is rewritten, init only notes it
        fw = self.make_fw("tagged", version="0.1.0")
        text = templates.ci_workflow(copy.deepcopy(config.DEFAULTS), "v0.1.0", plugin.repository_slug(fw)) \
            + "# " + SPEC_OLD + "\n"
        self.assertEqual(text.count(SPEC_OLD), 1)
        self.docs(**{".github__workflows__strict-delivery.yml": text})
        with mock.patch.object(plugin, "framework_dir", return_value=fw), \
                mock.patch.object(init.gitinfo, "head_sha", side_effect=init.GitNotFound("no git")):
            code, out, _ = self.mc("apply", migrate=True, ci=True)
        self.assertEqual(code, 0, out)
        self.assertIn("note: %s: present at version v0.1.0; run /strict-delivery:upgrade\n" % MATRIX_CI, out)
        self.assertEqual(self.read(MATRIX_CI), text.replace(SPEC_OLD, SPEC_NEW))
        self.assertIn(" M %s\n" % MATRIX_CI, out)  # an unstaged edit, never staged by init

    def test_in_a11_second_run_noop(self):  # IN-A11, IN-A14, IN-R2 (Q13); kills b-17
        self.docs()
        self.remote("https://github.com/o/n.git")
        self.gh(unprot())
        self.assertEqual(self.mc("apply", migrate=True, protect=True)[0], 0)
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", "init")
        calls = self.ghlog()
        self.assertEqual(self.mc("plan", migrate=True)[:2],
                         (1, "FAIL init.answers: migrate: no superpowers documents are tracked\n"))
        before = snapshot(self.root)
        note = "note: initialised repository: document migration and branch protection are not offered\n"
        self.assertEqual(self.mc("plan", protect=True)[:2], (0, "no changes\n" + note))
        code, out, _ = self.mc("apply", protect=True)
        self.assertEqual((code, out.startswith("no changes\n" + note)), (0, True), out)
        self.assertEqual((snapshot(self.root), self.ghlog()), (before, calls))  # nothing written, no call
        self.assertEqual(self.mc("plan", protect=False)[:2], (0, "no changes\n"))  # no offer answered: no note

    def test_in_a12_migrate_failure_exit_1(self):  # IN-A12, AM-F8 (CD12, CD21); kills b-18
        self.docs()
        self.remote("https://github.com/o/n.git")
        self.gh(unprot())
        self.trace_git(fail_on='*" mv -- docs/superpowers/specs"*')
        code, out, _ = self.mc("apply", migrate=True, protect=True)
        self.assertEqual(code, 1, out)
        self.assertIn("FAIL init.migrate: git mv failed (exit 1): %s -> %s; moved before it: %s -> %s\n"
                      % (SPEC_OLD, SPEC_NEW, PLAN_OLD, PLAN_NEW), out)
        self.assertTrue(os.path.isfile(os.path.join(self.root, ".strict-delivery/config.yml")))  # the file writes stay
        self.assertEqual(self.ghlog(), [G_REPO, G_PROT])  # the host calls did not run after the failed migration

    def test_never_commits(self):  # IN-A13 (the plan's name): no commit, no push
        self.docs()
        self.remote("https://github.com/o/n.git")
        self.gh(unprot())
        refs = lambda: (git(self.root, "rev-list", "--count", "HEAD"), git(self.root, "for-each-ref"))  # noqa: E731
        before = refs()
        self.assertEqual(self.mc("apply", migrate=True, protect=True)[0], 0)
        self.assertEqual(refs(), before)

    def test_in_r1_linked_worktree_moves(self):  # IN-R1 (F-B4p-13)
        self.docs()
        wt = os.path.join(self.tmp, "wt")
        git(self.root, "worktree", "add", "-q", "-b", "wtb", wt)
        code, out, _ = self.mc("apply", migrate=True, root=wt)
        self.assertEqual(code, 0, out)
        self.assertIn("note: hooks go to ", out)
        self.assertEqual(git(wt, "diff", "--cached", "--name-only", "--no-renames").splitlines(),
                         [PLAN_NEW, SPEC_NEW, PLAN_OLD, SPEC_OLD])
        self.assertTrue(os.path.isfile(os.path.join(wt, SPEC_NEW)))

    # --- the remote (IN-N*) --------------------------------------------------------------------------------------
    NO_REMOTE = "note: no GitHub remote recognised; branch protection is not offered\n"

    def no_remote(self, url=None, name="origin"):
        if url is not None:
            self.remote(url, name)
        self.no_gh()
        code, out, err = self.mc("apply", protect=True)
        self.assertEqual(code, 0, out)
        self.assertIn(self.NO_REMOTE, out)
        return out + err

    def test_in_n1_no_remote_note(self):  # IN-N1 (also with gh missing); kills b-14, fb-13
        self.no_remote()
        self.gh({})
        self.assertEqual(self.mc("plan", protect=True)[0], 0)
        self.assertEqual(self.ghlog(), [])

    def test_in_n2_https_origin(self):  # IN-N2
        self.remote("https://github.com/o/n.git")
        self.gh({G_REPO: (repo_json(), "", 0), G_PROT: (prot_json(), "", 0)})
        self.assertEqual(self.mc("plan", protect=True)[0], 0)
        self.assertEqual(self.ghlog(), [G_REPO, G_PROT])

    def test_in_n3_ssh_origin(self):  # IN-N3
        self.remote("git@github.com:o/n.git")
        self.gh({G_REPO: (repo_json(), "", 0), G_PROT: (prot_json(), "", 0)})
        self.assertEqual(self.mc("plan", protect=True)[0], 0)
        self.assertEqual(self.ghlog(), [G_REPO, G_PROT])

    def test_in_n4_other_host(self):  # IN-N4
        self.no_remote("https://gitlab.com/o/n")

    def test_in_n5_other_remote_name_only(self):  # IN-N5
        self.no_remote("https://github.com/o/n", name="upstream")

    def test_in_n6_token_not_printed(self):  # IN-N6
        text = self.no_remote("https://u:tok@github.com/o/n")
        self.assertNotIn("tok", text)
        self.assertNotIn("github.com", text)

    def test_in_n7_ssh_scheme_url(self):  # IN-N7 (CD16)
        text = self.no_remote("ssh://git@github.com/o/n.git")
        self.assertNotIn("not GitHub", text)

    # --- host failures (IN-H*) -----------------------------------------------------------------------------------
    def host_fail(self, rules=None, js=False, migrate=None):
        self.remote("https://github.com/o/n.git")
        if rules is None:
            self.no_gh()
        else:
            self.gh(rules)
        return self.mc("apply", migrate=migrate, protect=True, js=js)

    def test_gh_missing_fails_closed(self):  # IN-H1 (the plan's name); kills b-15, b-19, fb-18
        code, out, _ = self.host_fail()
        self.assertEqual(code, 1, out)
        self.assertIn("FAIL init.protection: gh api repos/o/n: gh not found on PATH\n", out)
        self.assertTrue(os.path.isfile(os.path.join(self.root, ".strict-delivery/config.yml")))

    def test_in_h2_gh_fails(self):  # IN-H2
        self.remote("https://github.com/o/n.git")
        for status in (1, 4):
            with self.subTest(status=status):
                root = os.path.join(self.tmp, "h2-%d" % status)
                shutil.copytree(self.root, root, symlinks=True)
                self.gh({G_REPO: ("", "gh: not logged in\n", status)})
                code, out, _ = self.mc("apply", protect=True, root=root)
                self.assertEqual(code, 1, out)
                self.assertIn("FAIL init.protection: gh api repos/o/n: gh: not logged in (exit %d)\n" % status, out)
                self.assertTrue(os.path.isfile(os.path.join(root, ".strict-delivery/config.yml")))

    def test_in_h3_put_fails(self):  # IN-H3
        rules = unprot()
        rules[G_PUT] = ("", "gh: Forbidden (HTTP 403)\n", 1)
        code, out, _ = self.host_fail(rules)
        self.assertEqual(code, 1, out)
        self.assertIn("FAIL init.protection: gh %s: gh: Forbidden (HTTP 403) (exit 1)\n" % G_PUT, out)
        self.assertEqual(self.ghlog(), [G_REPO, G_PROT, G_PUT])
        self.assertTrue(os.path.isfile(os.path.join(self.root, "CLAUDE.md")))  # nothing is rolled back

    def test_in_h4_patch_fails_after_put(self):  # IN-H4 (Q9, Q13: the second run makes no call at all)
        rules = unprot(merge_only=False)
        rules[G_PATCH] = ("", "gh: Server Error (HTTP 500)\n", 1)
        code, out, _ = self.host_fail(rules)
        self.assertEqual((code, self.ghlog()), (1, [G_REPO, G_PROT, G_PUT, G_PATCH]))
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", "init")
        self.assertEqual(self.mc("apply", protect=True)[0], 0)
        self.assertEqual(len(self.ghlog()), 4)

    def test_in_h5_files_stay(self):  # IN-H5: the tree after the FAIL equals the tree of the same apply without protection
        self.docs()
        self.remote("https://github.com/o/n.git")
        other = os.path.join(self.tmp, "other")
        shutil.copytree(self.root, other, symlinks=True)
        self.no_gh()
        self.assertEqual(self.mc("apply", migrate=True, protect=True)[0], 1)
        self.assertEqual(self.mc("apply", migrate=True, protect=False, root=other)[0], 0)
        self.assertEqual(self.tree(self.root), self.tree(other))
        for name in ("pre-commit", "pre-push"):  # the hooks stay too (RB-9): the files and their modes are the same
            mine, theirs = (os.path.join(r, ".git", "hooks", name) for r in (self.root, other))
            with open(mine, "rb") as a, open(theirs, "rb") as b:
                self.assertEqual((a.read(), os.stat(mine).st_mode), (b.read(), os.stat(theirs).st_mode), name)

    def test_in_h6_output_order(self):  # IN-H6 (CD22): FAIL line, then the status listing
        code, out, _ = self.host_fail()
        self.assertEqual(code, 1)
        self.assertLess(out.index("FAIL init.protection"), out.index("?? .strict-delivery/"))

    def test_in_h7_json_form(self):  # IN-H7 (CD23)
        code, out, _ = self.host_fail(js=True)
        self.assertEqual(code, 1)
        self.assertIn({"id": "init.protection", "status": "FAIL", "reason": "gh api repos/o/n: gh not found on PATH"},
                      [json.loads(line) for line in out.splitlines() if line.startswith("{")])

    def test_in_q14_branch_refused_no_gh_call(self):  # Q14: a branch gh could misread is refused before any call; kills fb-5
        self.remote("https://github.com/o/n.git")
        self.gh(unprot())
        want = "FAIL init.answers: base_branch: must be a branch name of letters, digits, '.', '_', '-' and '/'\n"
        for branch in ("a?b", "a#b"):
            for sub in ("plan", "apply"):
                self.assertEqual(self.mc(sub, protect=True, base_branch=branch)[:2], (1, want), (branch, sub))
                self.assertEqual(self.ghlog(), [], (branch, sub))

    # --- the --json failure shapes (RB-8, D1): one object ``{"id", "status", "reason"}`` per FAIL line --------------------
    def non_utf8_path(self, root):
        blob = git(root, "hash-object", "-w", "README.md")
        cacheinfo = b"100644," + blob.encode() + b",docs/superpowers/specs/\xff.md"
        subprocess.run([os.fsencode(a) for a in ("git", "-C", root, "update-index", "--add", "--cacheinfo")] + [cacheinfo],
                       check=True)

    def test_json_failure_input_questions_plan_apply(self):  # init.input in all three subcommands; kills fb-26, fb-27
        self.non_utf8_path(self.root)
        before = snapshot(self.root)
        want = '{"id": "init.input", "status": "FAIL", "reason": "git ls-files gave output that is not valid UTF-8"}\n'
        for sub in ("questions", "plan", "apply"):
            argv = [sub, "--root", self.root, "--json"] + (["--answers", self.put_answers(migrate=True)] if sub != "questions" else [])
            self.assertEqual(self.run_init(*argv), (1, want, ""), sub)
        self.assertEqual(snapshot(self.root), before)

    def test_json_failure_questions_is_json_not_text(self):  # D1: questions --json failed as text before; pin both forms
        root = os.path.join(self.tmp, "nonrepo")
        os.mkdir(root)
        reason = "%s: git rev-parse --show-toplevel failed (exit 128)" % root
        self.assertEqual(self.run_init("questions", "--root", root, "--json"),
                         (1, json.dumps({"id": "init.input", "status": "FAIL", "reason": reason}) + "\n", ""))
        self.assertEqual(self.run_init("questions", "--root", root), (1, "FAIL init.input: %s\n" % reason, ""))

    def test_json_failure_framework_error_is_input(self):  # a GateError outside the build: init.input; kills fb-28
        for sub in ("questions", "plan"):
            argv = [sub, "--root", self.root, "--json"] + (["--answers", self.put_answers()] if sub == "plan" else [])
            with mock.patch.object(plugin, "framework_dir", side_effect=GateError("no framework here")):
                self.assertEqual(self.run_init(*argv), (1, '{"id": "init.input", "status": "FAIL", "reason": '
                                                          '"no framework here"}\n', ""), sub)

    def test_json_failure_answers_plan_apply(self):  # init.answers; kills fb-27
        self.docs()
        want = ('{"id": "init.answers", "status": "FAIL", "reason": "migrate: required key is missing '
                '(superpowers documents are tracked)"}\n')
        for sub in ("plan", "apply"):
            self.assertEqual(self.mc(sub, js=True), (1, want, ""), sub)

    def test_json_failure_conflict_plan_apply(self):  # init.conflict; kills fb-29
        self.write(SPEC_NEW, "exists\n")
        self.docs()
        before = snapshot(self.root)
        want = '{"id": "init.conflict", "status": "FAIL", "reason": "docs/strict-delivery/specs/a.md: exists"}\n'
        for sub in ("plan", "apply"):
            self.assertEqual(self.mc(sub, migrate=True, js=True), (1, want, ""), sub)
        self.assertEqual(snapshot(self.root), before)

    def test_json_failure_write_apply(self):  # init.write (the ``written:`` line stays text); kills fb-31
        self.init_config()
        os.chmod(os.path.join(self.root, ".strict-delivery"), 0o555)
        self.addCleanup(os.chmod, os.path.join(self.root, ".strict-delivery"), 0o755)
        self.assertEqual(self.mc("apply", js=True),
                         (1, '{"id": "init.write", "status": "FAIL", "reason": ".strict-delivery/state: cannot create '
                             '(Permission denied)"}\nwritten: \n', ""))

    def test_json_failure_migrate_apply(self):  # init.migrate (the status listing stays text); kills fb-32
        self.docs()
        self.trace_git(fail_on='*" mv -- docs/superpowers/specs"*')
        code, out, _ = self.mc("apply", migrate=True, js=True)
        want = ('{"id": "init.migrate", "status": "FAIL", "reason": "git mv failed (exit 1): docs/superpowers/specs/a.md '
                '-> docs/strict-delivery/specs/a.md; moved before it: docs/superpowers/plans/x/p.md -> '
                'docs/strict-delivery/plans/x/p.md"}\n')
        self.assertEqual((code, out), (1, want + "A  docs/strict-delivery/plans/x/p.md\nD  docs/superpowers/plans/x/p.md\n"
                                             "?? .claude/settings.json\n?? .gitignore\n?? .strict-delivery/config.yml\n"
                                             "?? .strict-delivery/context.yml\n?? CLAUDE.md\n"))

    def test_json_failure_status_apply(self):  # init.status after the writes (CD22); kills fb-40
        self.trace_git(fail_on='*"status --porcelain=v1 --untracked-files=all"*')
        self.assertEqual(self.mc("apply", js=True),
                         (1, '{"id": "init.status", "status": "FAIL", "reason": "git status --porcelain failed (exit 1)"}\n', ""))
        self.assertTrue(os.path.isfile(os.path.join(self.root, ".strict-delivery/config.yml")))  # the writes stay

    def test_json_failure_protection_plan(self):  # init.protection in plan --json (Q12, D2); kills fb-30
        self.remote("https://github.com/o/n.git")
        self.no_gh()
        self.assertEqual(self.mc("plan", protect=True, js=True),
                         (1, '{"id": "init.protection", "status": "FAIL", "reason": "gh api repos/o/n: gh not found on '
                             'PATH"}\n', ""))

    def test_plan_init_refuses_with_input_error_for_a_reader_failure(self):  # IN-Q5 at the API: InitError init.input; kills fb-39
        self.non_utf8_path(self.root)
        with self.assertRaises(init.InitError) as cm:
            init.plan_init(self.root, dict(answers(), migrate=True))
        self.assertEqual((cm.exception.ident, cm.exception.reason), ("init.input", "git ls-files gave output that is not valid UTF-8"))

    def test_no_host_read_while_the_plan_is_in_conflict(self):  # IN-P7 with IN-P6: ``and not conflicts``; kills fb-19
        self.write(SPEC_NEW, "exists\n")
        self.docs()
        self.remote("https://github.com/o/n.git")
        self.gh(unprot())
        before = snapshot(self.root)
        for sub in ("plan", "apply"):
            self.assertEqual(self.mc(sub, migrate=True, protect=True)[:2], (1, "FAIL init.conflict: %s: exists\n" % SPEC_NEW), sub)
        self.assertEqual((self.ghlog(), snapshot(self.root)), ([], before))

    # --- Q16: apply recomputes the moves after its writes; a change between the plan and the recompute is FAIL init.migrate
    def race_git(self, trigger, actions):
        """A ``git`` that, on its first call once ``trigger`` (a shell test) holds, runs ``actions`` and then the real git."""
        d = os.path.join(self.tmp, "racebin")
        os.makedirs(d, exist_ok=True)
        lines = ["#!/bin/sh", 'if %s && [ ! -f "%s/done" ]; then' % (trigger, d), "  : > '%s/done'" % d]
        lines += ["  " + a for a in actions] + ["fi", "exec '%s' \"$@\"" % self.real_git]
        with open(os.path.join(d, "git"), "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
        os.chmod(os.path.join(d, "git"), 0o755)
        self.prepend_path(d)

    def race_target(self):
        r = self.root
        return ['[ -f "%s/.strict-delivery/config.yml" ]' % r,
                ["mkdir -p '%s/docs/strict-delivery/specs'" % r, "echo x > '%s/docs/strict-delivery/specs/a.md'" % r]]

    def race_record(self):
        r, rec = self.root, ".strict-delivery/state/decisions/D-1.yml"
        return ['[ -d "%s/.strict-delivery/state/decisions" ]' % r,
                ["echo 'ref: docs/superpowers/specs/a.md' > '%s/%s'" % (r, rec), "'%s' -C '%s' add %s" % (self.real_git, r, rec)]]

    LISTING = ("?? .claude/settings.json\n?? .gitignore\n?? .strict-delivery/config.yml\n?? .strict-delivery/context.yml\n"
               "?? CLAUDE.md\n")

    def test_apply_recomputes_moves_after_writes_target(self):  # Q16: a target made after the plan; kills fb-37
        self.docs()
        self.race_git(*self.race_target())
        code, out, _ = self.mc("apply", migrate=True)
        self.assertEqual((code, out), (1, "FAIL init.migrate: %s: exists\n" % SPEC_NEW + self.LISTING
                                       + "?? docs/strict-delivery/specs/a.md\n"))
        self.assertTrue(os.path.isfile(os.path.join(self.root, SPEC_OLD)) and os.path.isfile(os.path.join(self.root, PLAN_OLD)))
        self.assertTrue(os.path.isfile(os.path.join(self.root, ".strict-delivery/config.yml")))  # the file writes stay

    def test_apply_recompute_state_record_conflict(self):  # a tracked state record made after the plan; kills fb-36
        self.docs()
        self.race_git(*self.race_record())
        code, out, _ = self.mc("apply", migrate=True)
        self.assertEqual((code, out), (1, "FAIL init.migrate: .strict-delivery/state/decisions/D-1.yml: a state record names "
                                          "a moved path (docs/superpowers/specs/a.md); resolve it by hand before the migration\n"
                                          "A  .strict-delivery/state/decisions/D-1.yml\n" + self.LISTING))
        self.assertTrue(os.path.isfile(os.path.join(self.root, SPEC_OLD)))

    def test_apply_recompute_reports_the_move_conflict_alone(self):  # a target and a record: the target only; kills fb-35
        self.docs()
        t_trigger, t_actions = self.race_target()
        _r_trigger, r_actions = self.race_record()
        self.race_git(t_trigger, t_actions + ["mkdir -p '%s/.strict-delivery/state/decisions'" % self.root] + r_actions)
        code, out, _ = self.mc("apply", migrate=True)
        self.assertEqual(out.splitlines()[0], "FAIL init.migrate: %s: exists" % SPEC_NEW, out)
        self.assertEqual(code, 1)

    # --- Version rows (both interpreters through the runner), Amendment H --------------------------------------------
    def test_vr1_numeral_in_rewritten_text(self):  # VR1 (b), (d): no int() on file text; line numbers are small ints
        digits = "1" * 4301
        for limit in helpers.INT_LIMITS:
            with self.subTest(limit=limit), helpers.int_limit(limit):
                root = os.path.join(self.tmp, "vr1-%s" % limit)
                shutil.copytree(self.root, root, symlinks=True)
                for rel, text in ((SPEC_OLD, "docs/superpowers/specs/a.md:%s\n" % digits), ("README.md", digits + "\n")):
                    p = os.path.join(root, rel)
                    os.makedirs(os.path.dirname(p), exist_ok=True)
                    with open(p, "w", encoding="utf-8") as fh:
                        fh.write(text)
                git(root, "add", "-A")
                git(root, "commit", "-q", "-m", "n%s" % limit)
                code, out, _ = self.mc("apply", migrate=True, root=root)
                self.assertEqual(code, 0, out[:200])
                with open(os.path.join(root, SPEC_NEW), encoding="utf-8") as fh:
                    self.assertEqual(fh.read(), "docs/strict-delivery/specs/a.md:%s\n" % digits)

    def test_vr1_numeral_gh_json_through_init(self):  # VR1 (a): 601 digits refused with HostError on both interpreters
        self.remote("https://github.com/o/n.git")
        for limit in helpers.INT_LIMITS:
            with self.subTest(limit=limit), helpers.int_limit(limit):
                big = '{"id": %s, "allow_merge_commit": true, "allow_squash_merge": false, "allow_rebase_merge": false}' % ("9" * 601)
                self.gh({G_REPO: (big, "", 0)})
                code, out, _ = self.mc("plan", protect=True)
                self.assertEqual(code, 1)
                self.assertIn("FAIL init.protection: gh api repos/o/n: invalid JSON (an integer of more than 600 digits is not allowed)",
                              out)

    def test_vr2_u2c2f_in_paths_refused(self):  # VR2 (4): print_table's pinned tables decide, on both interpreters; kills fb-6 (3.13)
        self.init_config(paths={"specs": "docs/Ⱟ"})
        before = snapshot(self.root)
        for sub in ("plan", "apply"):
            self.assertEqual(self.mc(sub)[:2], (1, "FAIL init.config: .strict-delivery/config.yml: paths.specs: must be a "
                                                   "non-empty normalised repo-relative path of printable characters; "
                                                   "run /strict-delivery:doctor and /strict-delivery:upgrade\n"), sub)
        self.assertEqual(snapshot(self.root), before)

    def test_matrix_migration_targets_are_planned_paths(self):  # Part B pair matrix, Q-RC14-1 (a): the migration targets
        self.docs()  # an uninitialised repository: ``cfg`` is the defaults, the one configuration the targets have
        code, out, _ = self.mc("plan", migrate=True)
        files, dirs = plan_paths(out, self.root)
        self.assertEqual((code, sorted(files), dirs, plan_moves_printed(out)), (0, sorted([
            ".strict-delivery/config.yml", "CLAUDE.md", ".gitignore", ".claude/settings.json", MATRIX_DEFAULT_CTX,
            ".git/hooks/pre-commit", ".git/hooks/pre-push"]), MATRIX_DIRS, DOC_MOVES), out)
        # the cross product, by hand: the 14 default keys against each target and its ancestors; the only relations are
        # that paths.specs and paths.plans lie above their own targets
        defaults = {"state": ".strict-delivery/state", "decisions": ".strict-delivery/state/decisions",
                    "findings": ".strict-delivery/state/findings", "claims": ".strict-delivery/state/claims",
                    "plan_state": ".strict-delivery/state/plans", "programs": ".strict-delivery/state/programs",
                    "playbooks": ".strict-delivery/playbooks", "receipts": ".strict-delivery/receipts",
                    "context": MATRIX_DEFAULT_CTX, "architecture": "docs/strict-delivery/architecture.md",
                    "index": "docs/strict-delivery/INDEX.md", "specs": "docs/strict-delivery/specs",
                    "plans": "docs/strict-delivery/plans", "reviews": "docs/strict-delivery/reviews"}
        found = []
        for key, value in sorted(defaults.items()):
            for _src, dst in DOC_MOVES:
                if value == dst or value.startswith(dst + "/"):
                    found.append((key, "equal-or-below", dst))
                elif dst.startswith(value + "/"):
                    found.append((key, "above", dst))
        self.assertEqual(found, [("plans", "above", DOC_PLAN_DST), ("specs", "above", DOC_SPEC_DST)])
        code, out, _ = self.mc("apply", migrate=True)  # the cell holds: plan 0, apply 0, every move made
        self.assertEqual(code, 0, out)
        for src, dst in DOC_MOVES:
            self.assertTrue(os.path.isfile(os.path.join(self.root, dst)) and not os.path.lexists(os.path.join(self.root, src)))

    def test_in_r2_initialised_no_migration(self):  # IN-R2 (Q13): the config exists, so nothing moves; kills b-17
        self.docs()
        self.init_config()
        code, out, _ = self.mc("apply", migrate=True)
        self.assertEqual(code, 0, out)
        self.assertIn("note: initialised repository: document migration and branch protection are not offered\n", out)
        self.assertTrue(os.path.isfile(os.path.join(self.root, SPEC_OLD)))  # the source stays, the target is not made
        self.assertFalse(os.path.lexists(os.path.join(self.root, SPEC_NEW)))

    def test_state_record_conflict_through_init(self):  # Q-CH10-1 (b) at the init level (RW-X1a); kills b-33, b-36
        self.docs(**{".strict-delivery__state__decisions__D-1.yml": "ref: docs/superpowers/specs/a.md\n"})
        before = snapshot(self.root)
        want = ("FAIL init.conflict: .strict-delivery/state/decisions/D-1.yml: a state record names a moved path "
                "(docs/superpowers/specs/a.md); resolve it by hand before the migration\n")
        for sub in ("plan", "apply"):
            self.assertEqual(self.mc(sub, migrate=True)[:2], (1, want), sub)
        self.assertEqual(snapshot(self.root), before)

    def test_h_rows_through_init(self):  # Amendment H, H1 H3 H4 H5 H7 at the init level; the rest cite table rows (report)
        self.docs()
        fifo_root = os.path.join(self.tmp, "fifo")
        shutil.copytree(self.root, fifo_root, symlinks=True)
        link = os.path.join(self.tmp, "outside.md")
        with open(link, "w", encoding="utf-8") as fh:
            fh.write("o\n")
        os.symlink(link, os.path.join(self.root, "docs/superpowers/specs/ln.md"))  # H1: a tracked symlink source
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", "ln")
        before = snapshot(self.root)
        self.assertEqual(self.mc("plan", migrate=True)[:2],
                         (1, "FAIL init.conflict: docs/superpowers/specs/ln.md: tracked symlink; not moved\n"))
        self.assertEqual(snapshot(self.root), before)
        tmp_fifo = os.path.join(fifo_root, "swap")  # H3: a tracked holder that became a FIFO is skipped, never opened
        os.mkfifo(tmp_fifo)
        os.replace(tmp_fifo, os.path.join(fifo_root, "README.md"))
        code, out, _ = helpers.within(lambda: self.mc("plan", migrate=True, root=fifo_root))
        self.assertEqual(code, 0, out)
        self.assertIn("note: README.md: not a regular file; not read\n", out)
        for value in ("../out", "/abs", "a/../b"):  # H7: a configured path outside the root is refused by the config
            self.init_config(paths={"specs": value})
            self.assertEqual(self.mc("plan", migrate=True)[0], 1, value)

    # --- RB-1 HIGH, RB-2 MEDIUM, RB-3 MEDIUM (Amendment H4, H2, H3 for the tracked sources): the init-level cells of
    # docmove's fix (``_source_state``); the expected lines are the D-Q3 (A) texts, written by hand --------------------
    def symlinked_parent(self, parent):
        """RB-1: ``parent`` (a directory of the committed tree) moves outside the root, a symlink to it takes its place."""
        self.docs()
        out = os.path.join(self.tmp, "outside-" + parent.replace("/", "_"))
        os.rename(os.path.join(self.root, parent), out)
        os.symlink(out, os.path.join(self.root, parent))
        outside, before = snapshot(out), snapshot(self.root)
        sources = [s for s in (PLAN_OLD, SPEC_OLD) if s.startswith(parent + "/")]  # the plan line sorts first
        if parent == "docs":  # the targets lie below ``docs`` too: their parent is the same fault (D-Q3 (A)), lines sort first
            sources = [PLAN_NEW, SPEC_NEW] + sources
        want = "".join("FAIL init.conflict: %s: parent %s is not a directory\n" % (s, parent) for s in sources)
        for sub in ("plan", "apply"):
            self.assertEqual(self.mc(sub, migrate=True)[:2], (1, want), (parent, sub))
        self.assertEqual((snapshot(out), snapshot(self.root)), (outside, before))

    def test_rb1_docs_symlink_to_outside(self):  # RB-1 HIGH, H4; kills the ``_source_state`` parent test (Part A)
        self.symlinked_parent("docs")

    def test_rb1_superpowers_symlink_to_outside(self):  # RB-1 HIGH, H4
        self.symlinked_parent("docs/superpowers")

    def test_rb1_specs_symlink_to_outside(self):  # RB-1 HIGH, H4
        self.symlinked_parent("docs/superpowers/specs")

    def test_rb1_plans_symlink_to_outside(self):  # RB-1 HIGH, H4
        self.symlinked_parent("docs/superpowers/plans")

    def special_source(self, kind):
        """A tracked source (``SPEC_OLD``) replaced in the work tree by a ``kind``; the plan and the apply refuse it."""
        self.docs()
        path = os.path.join(self.root, SPEC_OLD)
        os.unlink(path)
        if kind == "directory":
            os.mkdir(path)
        elif kind == "fifo":
            os.mkfifo(path)
        else:  # a socket: the whole path is too long for bind(2), so bind by its base name inside its directory
            here = os.getcwd()
            os.chdir(os.path.dirname(path))
            try:
                sock = socket.socket(socket.AF_UNIX)
                self.addCleanup(sock.close)
                sock.bind(os.path.basename(path))
            finally:
                os.chdir(here)
        before = snapshot(self.root)
        want = "FAIL init.conflict: %s: not a regular file; not moved\n" % SPEC_OLD
        for sub in ("plan", "apply"):
            self.assertEqual(helpers.within(lambda: self.mc(sub, migrate=True))[:2], (1, want), (kind, sub))
        self.assertEqual(snapshot(self.root), before)

    def test_rb2_source_replaced_by_a_directory(self):  # RB-2 MEDIUM, H2
        self.special_source("directory")

    def test_rb3_source_replaced_by_a_fifo(self):  # RB-3 MEDIUM, H3: no read blocks (``within``)
        self.special_source("fifo")

    def test_rb3_source_replaced_by_a_socket(self):  # RB-3 MEDIUM, H3
        self.special_source("socket")


class TestPartBFindings(More):
    """The folded findings of 4d.1's code: F-20261125-iu7y (one conflict line per fault), -m638 (the ``/`` boundary),
    and U-1 (``paths.index`` and ``paths.receipts``)."""

    overlap = TestReview2.overlap

    def make_fw(self, name="fw", **kw):  # ``overlap`` makes its fake framework per call: one per test is enough
        fws = self.__dict__.setdefault("fws", {})
        if name not in fws:
            fws[name] = More.make_fw(self, name, **kw)
        return fws[name]

    def test_iu7y_one_line_per_fault(self):  # R5-1; kills b-21r, b-22r, fb-10, fb-12; CLAUDE.md, .gitignore, settings, CI, a hook
        fw = self.make_fw("tagged", version="0.1.0")
        self.write("CLAUDE.md", "mine\n")
        self.write(".gitignore", "x\n")
        self.write(".claude/settings.json", json.dumps({"env": {ENV_C: "30", ENV_D: "5"}}, indent=2, sort_keys=True) + "\n")
        with mock.patch.object(plugin, "framework_dir", return_value=fw), \
                mock.patch.object(init.gitinfo, "head_sha", side_effect=init.GitNotFound("no git")):
            self.assertEqual(self.cmd("apply", ci=True)[0], 0)  # the CI workflow and the hooks now exist
        for key, path in (("claims", "CLAUDE.md"), ("playbooks", ".gitignore"), ("programs", ".claude/settings.json"),
                          ("findings", MATRIX_CI), ("decisions", ".git/hooks/pre-commit")):
            for value in (path, path + "/x"):
                with self.subTest(key=key, value=value):
                    self.overlap(MATRIX_DEFAULT_CTX, "%s: exists and is not a directory" % path, ci=True, **{key: value})

    def accepted_pair(self, root, ci=False):
        fw = self.make_fw("tagged", version="0.1.0")
        for sub in ("plan", "apply"):
            with mock.patch.object(plugin, "framework_dir", return_value=fw), \
                    mock.patch.object(init.gitinfo, "head_sha", side_effect=init.GitNotFound("no git")):
                self.put_answers(ci=ci)
                code, out, _ = self.run_init(sub, "--root", root, "--answers", self.ans)
            self.assertEqual(code, 0, (sub, out))

    def test_m638_slash_boundary(self):  # R5-3; kills b-23: a sibling name of a planned file is accepted by every key
        count = 0
        for path, ci in (("CLAUDE.mdx", False), (".gitignorex", False), (".claude/settings.jsonx", False),
                         (MATRIX_CI + "x", True), (".git/hooks/pre-commitx", False), (".git/hooks/pre-pushx", False)):
            for key in STATE_KEYS:
                with self.subTest(key=key, path=path):
                    root = os.path.join(self.tmp, "r%d" % count)
                    count += 1
                    shutil.copytree(self.root, root, symlinks=True)
                    helpers.write_record(root, ".strict-delivery/config.yml", {
                        "schema": "config/2", "framework_version": "0.0.0", "profile": "standard",
                        "commands": answers()["commands"], "paths": {key: path}})
                    self.accepted_pair(root, ci)

    def test_u1_index_and_receipts_pairs(self):  # U-1 (Q-RC14-5 (a)): the context's existing texts; red on the parent
        cases = [("CLAUDE.md", SAME % "CLAUDE.md"), ("CLAUDE.MD", SAME % "CLAUDE.MD"),
                 ("CLAUDE.md/x", PARENT % ("CLAUDE.md/x", "CLAUDE.md")), (".gitignore", SAME % ".gitignore"),
                 (".claude", SAME % ".claude"), (MATRIX_DEFAULT_CTX, SAME % MATRIX_DEFAULT_CTX),
                 (".strict-delivery", SAME % ".strict-delivery"),
                 (".strict-delivery/state/claims", INSIDE % (".strict-delivery/state/claims", ".strict-delivery/state/claims")),
                 (".strict-delivery/state/claims/x", INSIDE % (".strict-delivery/state/claims/x", ".strict-delivery/state/claims")),
                 (".strict-delivery/state", INSIDE % (".strict-delivery/state", ".strict-delivery/state")),
                 (".git/hooks/pre-commit", SAME % ".git/hooks/pre-commit"),
                 (".GIT/HOOKS/PRE-PUSH", SAME % ".GIT/HOOKS/PRE-PUSH")]
        for key in ("index", "receipts"):
            for value, expect in cases:
                with self.subTest(key=key, value=value):
                    self.overlap(MATRIX_DEFAULT_CTX, expect, **{key: value})

    # --- F-20261125-iu7y, the member review 1 found open: an existing paths.context file equal to or below a state key ---
    def ctx_file_under(self, key):
        """``plan`` and ``apply`` print one line (``_dir_plan``'s) for the existing context file as, or below, ``key``."""
        self.write(MATRIX_DEFAULT_CTX, CONTEXT_YML)
        for value in (MATRIX_DEFAULT_CTX, MATRIX_DEFAULT_CTX + "/x"):
            with self.subTest(key=key, value=value):
                self.overlap(MATRIX_DEFAULT_CTX, "%s: exists and is not a directory" % MATRIX_DEFAULT_CTX, **{key: value})

    def test_iu7y_context_file_under_decisions(self):  # red on 44528c0; kills fb-8, fb-9, b-22r
        self.ctx_file_under("decisions")

    def test_iu7y_context_file_under_findings(self):  # red on 44528c0; kills fb-8, fb-9, b-22r
        self.ctx_file_under("findings")

    def test_iu7y_context_file_under_claims(self):  # red on 44528c0; kills fb-8, fb-9, b-22r
        self.ctx_file_under("claims")

    def test_iu7y_context_file_under_plan_state(self):  # red on 44528c0; kills fb-8, fb-9, b-22r
        self.ctx_file_under("plan_state")

    def test_iu7y_context_file_under_programs(self):  # red on 44528c0; kills fb-8, fb-9, b-22r
        self.ctx_file_under("programs")

    def test_iu7y_context_file_under_playbooks(self):  # red on 44528c0; kills fb-8, fb-9, b-22r
        self.ctx_file_under("playbooks")

    def test_iu7y_state_below_the_hook_the_context_equals(self):  # the hook call's ``reported``; kills fb-11
        self.overlap(".git/hooks/pre-commit", SAME % ".git/hooks/pre-commit", claims=".git/hooks/pre-commit/x")

    def test_index_and_receipts_on_one_path_one_line(self):  # PO2 after the U-1 compares: two keys, one fault; kills fb-20
        self.overlap(MATRIX_DEFAULT_CTX, SAME % "CLAUDE.md", index="CLAUDE.md", receipts="CLAUDE.md")

    def test_u1_sibling_paths_accepted(self):  # U-1 control: a path that merely shares a prefix is not refused; kills fb-7
        for key in ("index", "receipts"):
            root = os.path.join(self.tmp, "u1-" + key)
            shutil.copytree(self.root, root, symlinks=True)
            helpers.write_record(root, ".strict-delivery/config.yml", {
                "schema": "config/2", "framework_version": "0.0.0", "profile": "standard",
                "commands": answers()["commands"], "paths": {key: "CLAUDE.mdx"}})
            self.accepted_pair(root)


class TestFix2b(Mig):
    """4d.2 fix round 2, init side (review 2b): R2B-1 (the conditions of ``_is_reported`` and ``_reported_names``),
    R2B-2 (``--json`` of ``init.config``), and OQ-4 (a source or a parent swapped between init's file writes and the
    recomputed ``plan_moves``). Expected lines are written by hand; the init-level path cells are in
    tests/test_init_path_matrix.py. Mutant ids: ch/4d2-fix2b-operand-mutants-table.py."""

    def make_fw(self, name="fw", **kw):  # ``faults`` makes its fake framework per call: one per test is enough
        fws = self.__dict__.setdefault("fws", {})
        if name not in fws:
            fws[name] = More.make_fw(self, name, **kw)
        return fws[name]

    def faults(self, expect, ci=False, **paths):
        """``plan`` and ``apply`` print exactly the lines ``expect`` (one ``FAIL init.conflict`` line each) and leave the
        tree as it was; ``paths`` are the configured ``paths`` of an initialised repository."""
        self.init_config(paths=paths)
        before = snapshot(self.root)
        fw = self.make_fw("tagged", version="0.1.0")
        for sub in ("plan", "apply"):
            with mock.patch.object(plugin, "framework_dir", return_value=fw), \
                    mock.patch.object(init.gitinfo, "head_sha", side_effect=init.GitNotFound("no git")):
                code, out, _ = helpers.within(lambda: self.mc(sub, ci=ci))
            self.assertEqual((code, out), (1, "".join("FAIL init.conflict: %s\n" % e for e in expect)), (paths, sub))
            self.assertEqual(snapshot(self.root), before, (paths, sub))

    # --- R2B-1: the conditions of ``_is_reported`` and ``_reported_names`` (a conflict is reported once, whatever the
    # case of its spelling; a string prefix is not a path prefix). Each case is independent of the file system's case
    # rule: no path of it exists in the repository, or it exists in exactly the spelling it is configured in -----------
    def test_r2b1_is_reported_folds_the_path_equal(self):  # kills: _is_reported fold of ``path`` in ``==``
        self.faults([SAME % "CLAUDE.md"], context="CLAUDE.MD", decisions="CLAUDE.md")

    def test_r2b1_is_reported_folds_the_path_below(self):  # kills: _is_reported fold of ``path`` in ``startswith``
        self.faults([SAME % "CLAUDE.md"], context="CLAUDE.MD/x", decisions="CLAUDE.md")

    def test_r2b1_reported_names_are_folded_equal(self):  # kills: _reported_names fold
        self.faults([SAME % "CLAUDE.MD"], context="CLAUDE.md", decisions="CLAUDE.MD")

    def test_r2b1_reported_names_are_folded_below(self):  # kills: _reported_names fold
        self.faults([SAME % "CLAUDE.MD"], context="CLAUDE.md/x", decisions="CLAUDE.MD")

    def test_r2b1_string_prefix_is_not_a_reported_path_state_site(self):  # kills: ``n + "/"`` (the state-overlap call)
        self.write("CLAUDE.m", "mine\n")  # claims: CLAUDE.m is a fault of its own; decisions: CLAUDE.md is another
        self.faults(["CLAUDE.m: exists and is not a directory", SAME % "CLAUDE.md"], claims="CLAUDE.m", decisions="CLAUDE.md")

    def test_r2b1_string_prefix_is_not_a_reported_path_context_site(self):  # kills: ``n + "/"`` (the context call)
        self.write("CLAUDE.m", "mine\n")
        self.faults(["CLAUDE.m: exists and is not a directory", SAME % "CLAUDE.md"], claims="CLAUDE.m", context="CLAUDE.md")

    def test_r2b1_a_path_below_any_one_reported_name_is_reported(self):  # kills: ``any`` -> ``all`` in _is_reported
        self.write("CLAUDE.m", "mine\n")
        self.write(".gitignore", "x\n")  # two faults of _dir_plan; playbooks lies below the second only
        self.faults(["CLAUDE.m: exists and is not a directory", ".gitignore: exists and is not a directory"],
                    claims="CLAUDE.m/x", playbooks=".gitignore/y")

    def test_r2b1_upper_case_state_value_with_an_existing_context_file(self):  # the review's reproducer, every key
        self.write(MATRIX_DEFAULT_CTX, CONTEXT_YML)
        upper = MATRIX_DEFAULT_CTX.upper()
        insensitive = os.path.exists(os.path.join(self.root, upper))  # the file system's own rule decides the one line
        for key in STATE_KEYS:
            for value in (upper, upper + "/X"):
                with self.subTest(key=key, value=value):
                    if insensitive:  # the state directory is the existing file: _dir_plan's line, and nothing else
                        one = "%s: exists and is not a directory" % upper
                    else:  # a new directory: the context file lies inside it
                        one = INSIDE % (MATRIX_DEFAULT_CTX, value)
                    self.faults([one], **{key: value})

    def test_r2b1_upper_case_hook_path_with_installed_hooks(self):  # an installed hook as a state value, upper case
        fw = self.make_fw("tagged", version="0.1.0")
        with mock.patch.object(plugin, "framework_dir", return_value=fw), \
                mock.patch.object(init.gitinfo, "head_sha", side_effect=init.GitNotFound("no git")):
            self.assertEqual(self.mc("apply")[0], 0)  # the hooks now exist
        upper = ".GIT/HOOKS/PRE-COMMIT"
        insensitive = os.path.exists(os.path.join(self.root, upper))
        self.faults([("%s: exists and is not a directory" if insensitive else SAME) % upper], claims=upper)

    # --- R2B-2: the ``--json`` shape of ``init.config`` (plan and apply reach it; ``questions`` does not) ---------------
    def test_json_failure_config_plan_apply(self):  # init.config; kills the ``ns.json`` argument of ``_fail`` for this id
        helpers.write_record(self.root, ".strict-delivery/config.yml", {
            "schema": "config/2", "profile": "standard", "commands": answers()["commands"]})  # no framework_version
        before = snapshot(self.root)
        want = ('{"id": "init.config", "status": "FAIL", "reason": ".strict-delivery/config.yml: framework_version: '
                'required key is missing; run /strict-delivery:doctor and /strict-delivery:upgrade"}\n')
        for sub in ("plan", "apply"):
            self.assertEqual(self.mc(sub, js=True), (1, want, ""), sub)
        self.assertEqual(snapshot(self.root), before)

    # --- OQ-4: a source or a parent swapped after init's file writes and before the recomputed ``plan_moves`` (Q16) ----
    def swapped_after_writes(self, swap):
        """``apply`` with ``swap()`` run before the second ``docmove.plan_moves`` call (the recompute after the writes)."""
        self.docs()
        real, calls = init.docmove.plan_moves, []

        def hooked(root, cfg):
            calls.append(1)
            if len(calls) == 2:
                swap()
            return real(root, cfg)
        with mock.patch.object(init.docmove, "plan_moves", hooked):
            code, out, _ = self.mc("apply", migrate=True)
        self.assertEqual(len(calls), 2)
        fails = [l for l in out.splitlines() if l.startswith("FAIL ")]
        self.assertTrue(os.path.isfile(os.path.join(self.root, ".strict-delivery/config.yml")))  # CD12: the writes stay
        for dst in (PLAN_NEW, SPEC_NEW):
            self.assertFalse(os.path.lexists(os.path.join(self.root, dst)), dst)  # nothing moved
        return code, fails

    def test_oq4_source_swapped_after_the_writes(self):  # init.py:865-869: the one migrate line, exit 1
        def swap():
            path = os.path.join(self.root, SPEC_OLD)
            os.unlink(path)
            os.mkdir(path)
        self.assertEqual(self.swapped_after_writes(swap),
                         (1, ["FAIL init.migrate: docs/superpowers/specs/a.md: not a regular file; not moved"]))

    def test_oq4_source_parent_swapped_after_the_writes(self):
        def swap():
            outside = os.path.join(self.tmp, "outside")
            os.rename(os.path.join(self.root, "docs/superpowers/specs"), outside)
            os.symlink(outside, os.path.join(self.root, "docs/superpowers/specs"))
        self.assertEqual(self.swapped_after_writes(swap), (1, [
            "FAIL init.migrate: docs/superpowers/specs/a.md: parent docs/superpowers/specs is not a directory"]))
        self.assertEqual(sorted(os.listdir(os.path.join(self.tmp, "outside"))), ["a.md"])  # never moved from

    def test_oq4_conflicts_are_joined_by_semicolons(self):  # every conflict of the recompute on the one line
        def swap():
            outside = os.path.join(self.tmp, "outside")
            os.rename(os.path.join(self.root, "docs"), outside)
            os.symlink(outside, os.path.join(self.root, "docs"))
        want = "FAIL init.migrate: " + "; ".join(
            "%s: parent docs is not a directory" % p for p in (PLAN_NEW, SPEC_NEW, PLAN_OLD, SPEC_OLD))
        self.assertEqual(self.swapped_after_writes(swap), (1, [want]))


if __name__ == "__main__":
    unittest.main()
