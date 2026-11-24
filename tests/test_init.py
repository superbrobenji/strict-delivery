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
        self.assertEqual(err, "usage: init plan [-h] [--root ROOT] [--answers ANSWERS]\n"
                              "init plan: error: unrecognized arguments: --bogus\n")

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
        self.assertEqual(base["superpowers_docs"], [])
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
        self.assertIn("FAIL init.write: PermissionError: Permission denied\nwritten: \n", out)
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
        self.assertIn("FAIL init.write: PermissionError: Permission denied\nwritten: ", out)
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
                                                                     "host_calls", "notes"])
        self.assertEqual((plan.moves, plan.host_calls), ([], []))
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
                 "--- a/.claude/settings.json\n+++ b/.claude/settings.json\n", "\nhook /"]
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
                              "?? .strict-delivery/config.yml\n?? CLAUDE.md\n")
        code, out, _ = self.cmd("apply", ci=True)
        self.assertEqual(code, 0)
        self.assertEqual(out, "no changes\n?? .claude/settings.json\n?? .github/workflows/strict-delivery.yml\n"
                              "?? .gitignore\n?? .strict-delivery/config.yml\n?? CLAUDE.md\n")
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


if __name__ == "__main__":
    unittest.main()
