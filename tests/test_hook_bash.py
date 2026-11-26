"""Tests of the PreToolUse Bash hook (Task 3b.2, Producer 10 and the plan's Step 1 tests), run through the production entry
(``python3 -m gates hook PreToolUse``, ``tests.hookrun.run_hook``) on real repositories and linked worktrees. The expected
values are written by hand from the task-3b.2 input-domain table (row ids in the comments)."""
import json
import os
import shutil
import subprocess
import time
import unittest

from gates.lib import session
from gates.lib.yamlsub import emit
from gates.tools import githooks
from tests import hookrun
from tests.helpers import GitIsolatedTestCase, commit_all, git, make_repo, minimal_config

FW = hookrun.FW
ASK = "ask-id"


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def user_line(text):
    return json.dumps({"type": "user", "message": {"role": "user", "content": text}})


class HookCase(GitIsolatedTestCase):
    """``R`` is a strict-profile repository on branch ``feat`` whose ``commands.test`` appends to a marker file."""

    def setUp(self):
        super().setUp()
        self.R = os.path.join(self.work, "R")
        os.mkdir(self.R)
        self.marker = os.path.join(self.tmp, "marker")
        cfg = dict(minimal_config())
        cfg["commands"] = {"test": "echo ran >> %s" % self.marker}
        make_repo(self.R, cfg)
        write(os.path.join(self.R, "a.txt"), "one\n")
        commit_all(self.R, "a")
        git(self.R, "checkout", "-q", "-b", "feat")
        self.plugin = os.path.join(self.tmp, "plugin")
        os.mkdir(self.plugin)
        self.env = {"CLAUDE_PLUGIN_DATA": self.plugin, "PATH": os.environ["PATH"], "HOME": os.path.join(self.tmp, "home"),
                    "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null"}
        self.nproj = 0

    def gates_ran(self):
        return os.path.exists(self.marker)

    def B(self, command, cwd=None, agent=None, env=None, tool_input=None):
        cwd = cwd or self.R
        fields = {"tool_input": tool_input if tool_input is not None else {"command": command, "description": "d"}}
        if agent:
            fields.update(agent)
        return hookrun.run_hook("PreToolUse", hookrun.payload("PreToolUse", cwd, **fields),
                                env if env is not None else self.env, FW)

    def passes(self, r, msg=""):
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""), msg)

    def refused(self, r, *ids, absent=()):
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertEqual(r.stdout, "")
        for ident in ids:
            self.assertIn("FAIL hook.bash.%s" % ident, r.stderr)
        for ident in absent:
            self.assertNotIn("FAIL hook.bash.%s" % ident, r.stderr)

    def worktree(self, name, *args):
        path = os.path.join(self.work, name)
        git(self.R, "worktree", "add", "-q", *(list(args) + [path]))
        return path

    def agent(self, worktree, record=True, prompt=None, state=True):
        """The payload fields of subagent ``a1`` bound to ``worktree`` (a dispatch record of its first prompt; every
        call has its own prompt, so one call's record never binds another's agent)."""
        self.nproj += 1
        prompt = prompt or "brief %d" % self.nproj
        d = os.path.join(self.tmp, "proj%d" % self.nproj)
        os.makedirs(os.path.join(d, "sess-1", "subagents"))
        main_t = os.path.join(d, "sess-1.jsonl")
        write(main_t, user_line("MAIN prompt") + "\n")
        write(os.path.join(d, "sess-1", "subagents", "agent-a1.jsonl"), user_line(prompt) + "\n")
        if record and state:
            with session.locked(self.env, "sess-1") as st:
                session.add_dispatch(st, session.prompt_sha(prompt), "implementer", 1, "session", worktree, "feat")
        return {"agent_id": "a1", "agent_type": "implementer", "transcript_path": main_t}

    def dirty(self, root=None):
        write(os.path.join(root or self.R, "a.txt"), "changed\n")

    def failing_git_env(self, case_body, name="fakegit"):
        """``env`` with a fake ``git`` first on PATH: ``case_body`` is the body of a shell ``case "$*" in ... esac``
        (the arguments joined); every call it does not match runs the real git."""
        real = shutil.which("git", path=self.env["PATH"])
        fake = os.path.join(self.tmp, name)
        os.mkdir(fake)
        write(os.path.join(fake, "git"), '#!/bin/sh\ncase "$*" in\n%s\nesac\nexec "%s" "$@"\n' % (case_body, real))
        os.chmod(os.path.join(fake, "git"), 0o755)
        return dict(self.env, PATH=fake + os.pathsep + self.env["PATH"])


class CommitTest(HookCase):
    def test_add_and_commit_refused_no_gate_run(self):   # CS1, CR12
        for sep in ("&&", ";", "||", "|", "&", "\n"):
            with self.subTest(sep=repr(sep)):
                self.refused(self.B("git add x %s git commit -m m" % sep), "compound")
                self.refused(self.B("git commit -m m %s true" % sep), "compound")
        self.assertFalse(self.gates_ran())

    def test_each_wrapper_refused(self):   # CS2, CP2
        for command in ("(git commit -m m)", "{ git commit -m m; }", "echo $(git commit -m m)", "sh -c 'git commit -m m'",
                        "bash -c \"git commit -m m\"", "eval git commit -m m", "nohup git commit -m m",
                        "xargs git commit", "echo git commit", "grep \"git commit\" docs", "time git commit -m m",
                        "command git commit -m m"):
            with self.subTest(command=command):
                r = self.B(command)
                self.refused(r)
                self.assertRegex(r.stderr, r"FAIL hook\.bash\.(compound|not-git)")
        self.assertFalse(self.gates_ran())

    def test_index_override_refused(self):   # CE1, CE2
        for command in ("GIT_INDEX_FILE=x git commit -m m", "env GIT_INDEX_FILE=x git commit -m m",
                        "env -i GIT_INDEX_FILE=x git commit -m m"):
            with self.subTest(command=command):
                self.refused(self.B(command), "index")
        self.assertFalse(self.gates_ran())

    def test_git_dir_assignments_refused(self):   # CE3, TR32
        for command in ("GIT_DIR=x git commit -m m", "GIT_WORK_TREE=x git commit -m m", "env GIT_DIR=x git commit -m m",
                        "GIT_COMMON_DIR= git commit -m m", "GIT_OBJECT_DIRECTORY=x git commit -m m"):
            with self.subTest(command=command):
                self.refused(self.B(command), "target")

    def test_inherited_git_env_refused(self):   # CE7, PB13, PB14
        for name in ("GIT_INDEX_FILE", "GIT_DIR", "GIT_WORK_TREE"):
            for value in ("/nowhere", ""):
                with self.subTest(name=name, value=value):
                    env = dict(self.env)
                    env[name] = value
                    r = self.B("git commit -m m", env=env)
                    self.refused(r, "target")
                    self.assertIn(name, r.stderr)
                    self.assertFalse(self.gates_ran())
        env = dict(self.env, GIT_INDEX_FILE="a", GIT_DIR="b", GIT_WORK_TREE="c")
        self.assertEqual(self.B("git commit -m m", env=env).stderr.count("the hook inherited"), 3)

    def test_inherited_env_non_commit_passes(self):   # CE8
        self.passes(self.B("ls", env=dict(self.env, GIT_INDEX_FILE="/nowhere")))

    def test_quoted_separator_reaches_clean_tree_check(self):   # CS3
        self.dirty()
        r = self.B('git commit -m "a && b"')
        self.refused(r, "unstaged", absent=("compound",))
        self.assertFalse(self.gates_ran())

    def test_lone_commit_on_clean_tree_runs_gates(self):   # CR1, CR16
        self.passes(self.B("git commit -m m"))
        self.assertTrue(self.gates_ran())
        with open(self.marker, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "ran\n")

    def test_staged_then_changed_refused_before_gates(self):   # CU1
        git(self.R, "add", "a.txt")
        self.dirty()
        r = self.B("git commit -m m")
        self.refused(r, "unstaged")
        self.assertIn("a.txt: tracked file has unstaged changes; stage it or stash it, so the gates read the tree being "
                      "committed", r.stderr)
        self.assertFalse(self.gates_ran())

    def test_commit_a_with_unstaged_change_refused(self):   # CU2
        self.dirty()
        self.refused(self.B("git commit -a -m m"), "unstaged")
        self.assertFalse(self.gates_ran())

    def test_unstaged_deletion_refused(self):   # CU3
        os.rename(os.path.join(self.R, "a.txt"), os.path.join(self.tmp, "a.moved"))
        r = self.B("git commit -m m")
        self.refused(r, "unstaged")
        self.assertIn("a.txt", r.stderr)
        self.assertFalse(self.gates_ran())

    def test_untracked_file_not_listed(self):   # CU7
        write(os.path.join(self.R, "new.txt"), "x\n")
        self.passes(self.B("git commit -m m"))

    def test_unusual_names_one_line_each(self):   # HR6, CU10
        write(os.path.join(self.R, "sp ace.txt"), "1\n")
        write(os.path.join(self.R, "nl\nname.txt"), "1\n")
        write(os.path.join(self.R, "é.txt"), "1\n")
        commit_all(self.R, "names")
        for name in ("sp ace.txt", "nl\nname.txt", "é.txt"):
            write(os.path.join(self.R, name), "2\n")
        r = self.B("git commit -m m")
        self.refused(r, "unstaged")
        self.assertEqual(r.stderr.count("FAIL hook.bash.unstaged"), 3)
        self.assertIn("nl\\nname.txt", r.stderr)
        self.assertIn("sp ace.txt", r.stderr)

    def test_bypass_forms(self):   # CN1-CN3, CN17, TX1-TX36 (the plan's table)
        cases = (("git commit --no-verify -m m", True), ("git commit --no-veri -m m", True),
                 ("git commit --no-verbose -m m", True), ("git commit -n -m m", True), ("git commit -an", True),
                 ("git commit -nm x", True), ("git commit -mn", False), ("git commit -m -n", False),
                 ("git push -n", False), ("git -c core.hooksPath=/dev/null commit -m m", True),
                 ("git config core.HooksPath x", True), ("GIT_CONFIG_COUNT=1 git status", True),
                 ("GIT_CONFIG_GLOBAL=x git status", True), ("HOME=/tmp git commit -m m", True),
                 ("export HOME=x", True), ("env -u HOME git commit -m m", True), ("XDG_CONFIG_HOME=x ls", True),
                 ("git commit -m 'use --no-verify'", True), ("echo ok", False), ("git status --no-pager", False),
                 ("cd; echo $HOME", False))
        for command, expected in cases:
            with self.subTest(command=command):
                r = self.B(command)
                self.assertEqual("hook.bash.bypass" in r.stderr, expected, r.stderr)
                if expected:
                    self.assertEqual(r.returncode, 2)

    def test_alias_resolved(self):   # EW6, CN12, CR1
        git(self.R, "config", "alias.ci", "commit")
        self.refused(self.B("git ci --no-verify -m m"), "bypass.no-verify")
        self.refused(self.B("git ci -n -m m"), "bypass.n-flag")
        self.dirty()
        self.refused(self.B("git ci -m m"), "unstaged")
        git(self.R, "config", "alias.x", "!git commit")
        self.refused(self.B("git x -m m"), absent=("bypass",))

    def test_alias_in_compound_without_commit_word(self):   # EW8
        git(self.R, "config", "alias.ci", "commit")
        self.refused(self.B("ls && git ci -m m"), "compound")

    def test_healthy_git_hooks_skip_double_run(self):   # CR2
        self.assertEqual(githooks.install(self.R, FW), [])
        git(self.R, "status", "-s")
        self.passes(self.B("git commit -m m"))
        self.assertFalse(self.gates_ran())

    def test_gates_hooks_missing_runs_gates(self):   # CR3
        self.passes(self.B("git commit -m m"))
        self.assertTrue(self.gates_ran())

    def test_gates_strict_test_failure_kept(self):   # CR8
        cfg = dict(minimal_config())
        cfg["commands"] = {"test": "exit 3"}
        write(os.path.join(self.R, ".strict-delivery", "config.yml"), emit(cfg))
        commit_all(self.R, "failing test command")
        r = self.B("git commit -m m")
        self.refused(r, "gates")
        self.assertIn("commands.test exited 3", r.stderr)

    def test_config_error_refuses_commit_only(self):   # CC1, CC2, PB11
        write(os.path.join(self.R, ".strict-delivery", "config.yml"), "schema: [\n")
        r = self.B("git commit -m m")
        self.refused(r, "config")
        self.assertIn("no commit runs until the config loads", r.stderr)
        for command in ("ls", "git status", "git log"):
            self.passes(self.B(command), command)

    def test_config_error_text_refusals_apply(self):   # CC3, PB26
        write(os.path.join(self.R, ".strict-delivery", "config.yml"), "schema: [\n")
        self.refused(self.B("git commit --no-verify -m m"), "bypass.no-verify", "config")
        self.refused(self.B("HOME=x ls"), "bypass.home")

    def test_no_config_is_silent(self):   # PB12
        os.rename(os.path.join(self.R, ".strict-delivery", "config.yml"), os.path.join(self.tmp, "config.moved"))
        self.passes(self.B("git commit --no-verify -m m"))

    def test_all_profiles(self):   # PB10
        for profile in ("light", "standard", "strict"):
            with self.subTest(profile=profile):
                cfg = dict(minimal_config())
                cfg["profile"] = profile
                write(os.path.join(self.R, ".strict-delivery", "config.yml"), emit(cfg))
                commit_all(self.R, "profile " + profile)
                self.refused(self.B("git commit --no-verify -m m"), "bypass.no-verify")


class CommandShapeTest(HookCase):
    def test_command_absent_and_not_str(self):   # PB1, PB2
        for tool_input in ({}, {"description": "d"}, {"command": None}, {"command": 1}, {"command": True},
                           {"command": []}, {"command": {}}, {"command": ["git", "commit"]}, {"command": 1.5}):
            with self.subTest(tool_input=tool_input):
                r = self.B("", tool_input=tool_input)
                self.refused(r, "input")

    def test_empty_and_whitespace_pass(self):   # PB3, PB4
        for command in ("", "   ", "\t", "\n\n"):
            with self.subTest(command=repr(command)):
                self.passes(self.B(command))

    def test_description_not_scanned(self):   # TX48, PB9
        self.passes(self.B("ls", tool_input={"command": "ls", "description": "git commit --no-verify; decide"}))

    def test_very_long(self):   # PB5
        self.passes(self.B("a " * 100000))
        self.passes(self.B("git commit -m " + "x" * 1000000))
        self.assertTrue(self.gates_ran())

    def test_pass_prints_nothing(self):   # PB17
        for command in ("ls", "git status", "git log"):
            self.passes(self.B(command), command)

    def test_nul_and_non_ascii(self):   # PB6, PB7
        self.refused(self.B("git commit -m \u0000"), "compound")
        self.passes(self.B("ls\u0000"))
        self.refused(self.B("git commit -m é"), "compound")

    def test_refusal_order(self):   # PB15, PB16
        r = self.B("git commit --no-verify -m m && true")
        self.assertEqual(r.returncode, 2)
        lines = r.stderr.splitlines()
        self.assertEqual(len(lines), 2)
        self.assertTrue(lines[0].startswith("FAIL hook.bash.bypass.no-verify"))
        self.assertTrue(lines[1].startswith("FAIL hook.bash.compound: git commit runs as its own command (operator &&)"))
        self.assertTrue(r.stderr.endswith("\n"))

    def test_other_tools_not_routed(self):   # PB22
        p = hookrun.payload("PreToolUse", self.R, tool_name="Read", tool_input={"file_path": "x"})
        r = hookrun.run_hook("PreToolUse", p, self.env, FW)
        self.assertNotIn("hook.bash", r.stderr)

    def test_git_missing(self):   # PB20
        # Decision (controller) PB20: hookio.context re-raises GitNotFound (3a.2) before any handler runs, so with no
        # git on PATH every Bash call, `ls` included, is refused by the 3a.2 line; the table verdict `ls: PASS` was
        # corrected (hooks stream controller 2, 2026-11-25). No divergence remains.
        env = dict(self.env, PATH=self.tmp)
        for command in ("git commit -m m", "ls"):
            r = self.B(command, env=env)
            self.assertEqual(r.returncode, 2)
            self.assertIn("FAIL hook.PreToolUse: git not found on PATH", r.stderr)

    def test_hook_writes_nothing_in_repo(self):   # PB24
        before = git(self.R, "status", "--porcelain", "--untracked-files=all")
        self.B("git commit -m m")
        self.assertEqual(git(self.R, "status", "--porcelain", "--untracked-files=all"), before)


class DecideTest(HookCase):
    FORMS = ("python3 -m gates decisions decide X --by owner", "python3 -I -m gates decisions withdraw X",
             "cd x; python3 -m gates decisions decide", "sh -c 'python3 -m gates decisions decide'",
             "python3 -c \"from gates.tools import decisions_cli; decisions_cli.main(['decide'])\"")

    def test_decide_and_withdraw_refused_from_subagents(self):   # TX38
        agent = self.agent(self.R)
        for command in self.FORMS:
            with self.subTest(command=command):
                r = self.B(command, agent=agent)
                self.refused(r, "decide")
                self.assertIn("(spec §7.1)", r.stderr)

    def test_decide_main_session_allowed(self):   # TX39
        for command in self.FORMS:
            with self.subTest(command=command):
                self.assertNotIn("hook.bash.decide", self.B(command).stderr)

    def test_ask_and_reads_allowed(self):   # TX40, TX41
        agent = self.agent(self.R)
        for command in ("python3 -m gates decisions ask X", "python3 -m gates decisions list", "grep decide notes.md",
                        "echo withdraw", "git status -m decide"):
            with self.subTest(command=command):
                self.assertNotIn("hook.bash.decide", self.B(command, agent=agent).stderr)


class TargetTest(HookCase):
    def test_subagent_commits_in_bound_worktree(self):   # TR2, TR3, CS5
        W = self.worktree("W", "-b", "wb")
        agent = self.agent(W)
        for command in ("git -C %s commit -m m" % W, "cd %s && git commit -m m" % W):
            with self.subTest(command=command):
                self.assertNotIn("hook.bash.target", self.B(command, agent=agent).stderr)
        self.assertNotIn("hook.bash.target", self.B("git commit -m m", cwd=W, agent=agent).stderr)

    def test_subagent_plain_write_in_main_checkout_refused(self):   # TR1
        W = self.worktree("W", "-b", "wb")
        r = self.B("git commit -m m", agent=self.agent(W))
        self.refused(r, "target")
        self.assertIn("%s is not a worktree this caller may write in (allowed: %s)" % (self.R, W), r.stderr)

    def test_refused_target_commit_stops_before_config_unstaged_gates(self):   # M43: the refused target's policy is not the target's
        W = self.worktree("W", "-b", "wb")
        agent = self.agent(W)
        self.dirty()   # the main checkout (the refused target) has an unstaged path
        r = self.B("git commit -m m", agent=agent)
        self.refused(r, "target", absent=("unstaged", "config", "gates"))
        write(os.path.join(self.R, ".strict-delivery", "config.yml"), "schema: [\n")   # and a config that does not load
        r = self.B("git commit -m m", agent=agent)
        self.refused(r, "target", absent=("unstaged", "config", "gates"))
        self.assertFalse(self.gates_ran())

    def test_other_worktree_and_other_repo_refused(self):   # TR4, TR21, HR7
        W = self.worktree("W", "-b", "wb")
        W2 = self.worktree("W2", "-b", "wb2")
        X = os.path.join(self.work, "X")
        os.mkdir(X)
        make_repo(X)
        agent = self.agent(W)
        for command in ("git -C %s commit -m m" % W2, "git -C %s commit -m m" % X, "git -C / commit -m m",
                        "git -C %s commit -m m" % self.tmp):
            with self.subTest(command=command):
                self.refused(self.B(command, agent=agent), "target")

    def test_unbound_subagent_refused_every_write(self):   # TR6-TR10
        W = self.worktree("W", "-b", "wb")
        for label, agent, env in (("no record", self.agent(W, record=False), None),
                                  ("plugin data unset", self.agent(W), {k: v for k, v in self.env.items()
                                                                       if k != "CLAUDE_PLUGIN_DATA"})):
            for command in ("git commit -m m", "git -C %s commit -m m" % W, "git reset --hard", "git tag x"):
                with self.subTest(label=label, command=command):
                    r = self.B(command, cwd=W, agent=agent, env=env)
                    self.refused(r, "target")
                    self.assertIn("this agent has no bound worktree (", r.stderr)
        agent = self.agent(W)
        write(agent["transcript_path"], "")
        self.refused(self.B("git commit -m m", cwd=W, agent=dict(agent, transcript_path=None)), "target")

    def test_session_commit_in_cwd_and_sibling_refused(self):   # TR11, TR12
        W = self.worktree("W", "-b", "wb")
        os.mkdir(os.path.join(self.R, "sub"))
        self.assertNotIn("hook.bash.target", self.B("git commit -m m", cwd=os.path.join(self.R, "sub")).stderr)
        self.refused(self.B("git -C %s commit -m m" % W), "target")

    def test_c_relative_joined_to_cwd(self):   # TR16
        W = self.worktree("W", "-b", "wb")
        agent = self.agent(W)
        os.mkdir(os.path.join(self.work, "d"))
        self.assertNotIn("hook.bash.target", self.B("git -C ../W commit -m m", cwd=os.path.join(self.work, "d"),
                                                    agent=agent).stderr)

    def test_hardening_symlink_target(self):   # HR1, TR17, TR18
        W = self.worktree("W", "-b", "wb")
        W2 = self.worktree("W2", "-b", "wb2")
        good, bad, dangling = (os.path.join(self.tmp, n) for n in ("good", "bad", "dangling"))
        os.symlink(W, good)
        os.symlink(W2, bad)
        os.symlink(os.path.join(self.tmp, "gone"), dangling)
        agent = self.agent(W)
        self.assertNotIn("hook.bash.target", self.B("git -C %s commit -m m" % good, agent=agent).stderr)
        self.refused(self.B("git -C %s commit -m m" % bad, agent=agent), "target")
        self.refused(self.B("git -C %s commit -m m" % dangling, agent=agent), "target")

    def test_hardening_target_kinds(self):   # HR2, TR23, TR22
        W = self.worktree("W", "-b", "wb")
        os.mkdir(os.path.join(W, "sub"))
        agent = self.agent(W)
        self.assertNotIn("hook.bash.target", self.B("git -C %s/sub commit -m m" % W, agent=agent).stderr)
        self.refused(self.B("git -C %s/.git commit -m m" % W, agent=agent), "target")   # a regular file
        self.refused(self.B("git -C %s/missing commit -m m" % W, agent=agent), "target")
        self.refused(self.B("git -C '' commit -m m", agent=agent), "target")

    def test_hardening_fifo(self):   # HR3
        W = self.worktree("W", "-b", "wb")
        fifo = os.path.join(self.tmp, "fifo")
        os.mkfifo(fifo)
        agent = self.agent(W)
        for command in ("git -C %s commit -m m" % fifo, "git -C /dev/null commit -m m"):
            start = time.time()
            self.refused(self.B(command, agent=agent), "target")
            self.assertLess(time.time() - start, 5, command)   # HR3: returns within 5 s
        os.rename(os.path.join(self.R, ".strict-delivery", "config.yml"), os.path.join(self.tmp, "config.moved"))
        os.mkfifo(os.path.join(self.R, ".strict-delivery", "config.yml"))
        start = time.time()
        r = self.B("git commit -m m")
        self.assertLess(time.time() - start, 5)
        self.refused(r, "config", absent=("unstaged", "gates"))   # HR3: the config.load verdict (cfg_error) refuses the commit
        self.assertIn("FAIL hook.bash.config: .strict-delivery/config.yml: cannot read file (not a regular file); ",
                      r.stderr)
        self.assertFalse(self.gates_ran())

    def test_hardening_parent_symlink(self):   # HR4
        W = self.worktree("W", "-b", "wb")
        link = os.path.join(self.tmp, "parentlink")
        os.symlink(self.work, link)
        agent = self.agent(W)
        self.assertNotIn("hook.bash.target", self.B("git -C %s/W commit -m m" % link, agent=agent).stderr)

    def test_hardening_swap_after_check_is_stated_limit(self):   # HR4
        W = self.worktree("W", "-b", "wb")
        link = os.path.join(self.tmp, "swap")
        os.symlink(W, link)
        agent = self.agent(W)
        first = self.B("git -C %s commit -m m" % link, agent=agent)
        os.symlink(self.R, link + ".new")
        os.replace(link + ".new", link)
        second = self.B("git -C %s commit -m m" % link, agent=agent)
        self.assertNotIn("hook.bash.target", first.stderr)   # the verdict follows the state at check time
        self.refused(second, "target")

    def test_hardening_nested_worktree(self):   # HR5
        nested = os.path.join(self.R, "nested")
        git(self.R, "worktree", "add", "-q", "-b", "nb", nested)
        agent = self.agent(nested)
        self.assertNotIn("hook.bash.target", self.B("git -C %s commit -m m" % nested, cwd=nested, agent=agent).stderr)
        self.assertNotIn("hook.bash.target", self.B("git -C %s commit -m m" % self.R, cwd=self.R,
                                                    agent=self.agent(self.R)).stderr)

    def test_non_write_no_target_check(self):   # TR24
        W = self.worktree("W", "-b", "wb")
        agent = self.agent(W)
        for command in ("git -C %s status" % self.R, "git log", "git branch", "git branch -a", "git diff"):
            with self.subTest(command=command):
                self.assertNotIn("hook.bash.target", self.B(command, agent=agent).stderr)

    def test_each_write_gets_target_check(self):   # GW1
        W = self.worktree("W", "-b", "wb")
        agent = self.agent(W)
        for sub in ("push", "merge x", "pull", "rebase x", "cherry-pick x", "revert x", "am x", "reset --hard", "update-ref x y",
                    "tag x", "stash", "worktree list", "branch -D x", "checkout -b x", "switch -c x"):
            with self.subTest(sub=sub):
                self.refused(self.B("git %s" % sub, agent=agent), "target")

    def test_two_c_and_c_with_cd_refused(self):   # TR19, TR20
        W = self.worktree("W", "-b", "wb")
        agent = self.agent(W)
        self.refused(self.B("git -C %s -C %s commit -m m" % (W, W), agent=agent), "target", "global-option.-C")
        self.refused(self.B("cd %s && git -C %s commit -m m" % (W, W), agent=agent), "target")

    def test_unstaged_check_reads_named_worktree(self):   # CU14
        W = self.worktree("W", "-b", "wb")
        agent = self.agent(W)
        self.dirty(W)
        self.refused(self.B("git -C %s commit -m m" % W, agent=agent), "unstaged")
        git(W, "checkout", "--", "a.txt")
        self.dirty(self.R)
        self.assertNotIn("hook.bash.unstaged", self.B("git -C %s commit -m m" % W, agent=agent).stderr)

    def test_global_options_refused(self):   # CG1, CG2, CG5
        for command, expected in (("git --no-pager commit -m m", False), ("git -P commit -m m", False),
                                  ("git --git-dir=x commit -m m", True), ("git --work-tree=x commit -m m", True),
                                  ("git -c a=b commit -m m", True), ("git --bare commit -m m", True)):
            with self.subTest(command=command):
                self.assertEqual("hook.bash.global-option" in self.B(command).stderr, expected)


class GatesAndWritesTest(HookCase):
    def test_gates_only_pre_commit_status(self):   # CR6
        self.assertEqual(githooks.install(self.R, FW), [])
        write(os.path.join(self.R, ".git", "hooks", "pre-push"), "foreign\n")   # only pre-push is not current
        self.passes(self.B("git commit -m m"))
        self.assertFalse(self.gates_ran())

    def test_gates_hooks_foreign_and_stale(self):   # CR4, CR5
        self.assertEqual(githooks.install(self.R, FW), [])
        write(os.path.join(self.R, ".git", "hooks", "pre-commit"), "foreign\n")
        self.passes(self.B("git commit -m m"))
        self.assertTrue(self.gates_ran())

    def test_non_plain_write_names_no_other_worktree(self):   # TR26 (decision Q3)
        W = self.worktree("W", "-b", "wb")
        r = self.B("ls && git -C %s reset --hard" % W)
        self.refused(r, "target")
        self.assertIn("names its worktree only as one plain command", r.stderr)
        self.passes(self.B("ls && git status"))
        self.assertNotIn("hook.bash.target", self.B("ls; git tag x").stderr)   # the target is cwd's top level

    def test_other_write_refusals_of_global_options_and_env(self):   # Q3
        for command in ("GIT_DIR=x git reset --hard", "git --git-dir=x reset --hard", "git -c a=b tag t"):
            with self.subTest(command=command):
                self.assertRegex(self.B(command).stderr, r"FAIL hook\.bash\.(target|global-option)")

    def test_handler_wired(self):   # PB21
        r = self.B("true")
        self.passes(r)


STATUS_HEADER = ("| stream | block | branch | worktree | next task | estimate | used | status | blockers | pending decisions "
                 "| delivers |\n|---|---|---|---|---|---|---|---|---|---|---|\n")
PROG = "20261101-prog"
PROGRAMS = ".strict-delivery/state/programs"
UNSTAGED_TAIL = "tracked file has unstaged changes; stage it or stash it, so the gates read the tree being committed"


def status_row(stream, wt):
    return "| %s | 3 | %s/%s/main | %s | t1 | 1 | 0 | running | - | - | - |\n" % (stream, PROG, stream, wt)


class ProgramTest(HookCase):
    """``LIVE`` of the table: ``R`` plus a live program (the branch ``<p>/integration`` holds ``streams.yml`` and the
    status page naming ``SW``; ``IW`` is the worktree on that branch; ``UW`` is a worktree the page does not name)."""

    def make_program(self, rows=None):
        self.IW, self.SW, self.UW = (os.path.join(self.work, n) for n in ("IW", "SW", "UW"))
        git(self.R, "worktree", "add", "-q", "-b", PROG + "/integration", self.IW, "main")
        write(os.path.join(self.IW, PROGRAMS, PROG, "streams.yml"), "schema: streams/1\n")
        self.status(STATUS_HEADER + (rows if rows is not None else status_row("s1", self.SW)))
        git(self.R, "worktree", "add", "-q", "-b", PROG + "/s1/main", self.SW, "main")
        git(self.R, "worktree", "add", "-q", "-b", "other", self.UW, "main")

    def status(self, text):
        write(os.path.join(self.IW, PROGRAMS, PROG, "status.md"), "# status\n\n" + text)
        commit_all(self.IW, "status")

    def test_program_session_writes_in_program_worktrees_only(self):   # TR13, TR14, PB23
        self.make_program()
        self.passes(self.B("git -C %s merge main" % self.SW))
        self.passes(self.B("git -C %s merge main" % self.IW))
        self.passes(self.B("git merge main"))
        self.dirty(self.IW)
        r = self.B("git -C %s commit -m m" % self.IW)
        self.refused(r, "unstaged", absent=("target",))
        r = self.B("git -C %s merge main" % self.UW)
        self.refused(r, "target")
        self.assertIn("FAIL hook.bash.target: %s is not a worktree this caller may write in (allowed: %s, %s, %s)"
                      % (self.UW, self.IW, self.R, self.SW), r.stderr)
        self.refused(self.B("git -C %s commit -m m" % self.UW), "target")
        W = self.worktree("W", "-b", "wb")
        self.refused(self.B("git -C %s merge main" % self.SW, agent=self.agent(W)), "target")   # a subagent gets its own only

    def test_program_session_bad_status_cell(self):   # TR15
        missing = os.path.join(self.work, "never-made")
        for label, cell, text in (("missing path", missing, "does not exist"),
                                  ("relative path", "rel/path", "is not an absolute path")):
            with self.subTest(label):
                self.make_program(rows=status_row("s1", cell))
                r = self.B("git -C %s merge main" % self.SW)
                self.refused(r, "target")
                self.assertIn("FAIL hook.bash.target: program %s: status worktree %s %s" % (PROG, cell, text), r.stderr)
                self.passes(self.B("git -C %s merge main" % self.IW))   # the integration worktree stays allowed
                for path in (self.IW, self.SW, self.UW):
                    git(self.R, "worktree", "remove", "--force", path)
                git(self.R, "branch", "-D", PROG + "/integration", PROG + "/s1/main", "other")
        with self.subTest("no status page at the tip"):
            self.make_program()
            git(self.IW, "rm", "-q", os.path.join(PROGRAMS, PROG, "status.md"))
            commit_all(self.IW, "drop status")
            r = self.B("git -C %s merge main" % self.SW)
            self.refused(r, "target")
            self.assertIn("is not a file at the tip of %s/integration" % PROG, r.stderr)

    def test_live_programs_raising(self):   # TR15 (live_programs raising: git for-each-ref fails)
        self.make_program()
        env = self.failing_git_env('*for-each-ref*) echo "fatal: injected" >&2; exit 128;;')
        r = self.B("git -C %s merge main" % self.SW, env=env)
        self.refused(r, "target")
        self.assertIn("FAIL hook.bash.target: live programs cannot be read (git for-each-ref failed (exit 128))\n", r.stderr)
        self.assertIn("%s is not a worktree this caller may write in (allowed: %s)" % (self.SW, self.R), r.stderr)

    def test_old_git_fails_closed_bash(self):   # V5 (the session form: worktree_list needs git 2.36)
        self.make_program()
        fake = os.path.join(self.tmp, "fakegit")
        os.mkdir(fake)
        real = subprocess.run(["which", "git"], env=self.env, stdout=subprocess.PIPE, check=True).stdout.decode().strip()
        write(os.path.join(fake, "git"), '#!/bin/sh\ncase "$*" in *"worktree list"*) echo "error: unknown option" >&2; exit 129;; '
                                         'esac\nexec "%s" "$@"\n' % real)
        os.chmod(os.path.join(fake, "git"), 0o755)
        env = dict(self.env, PATH=fake + os.pathsep + self.env["PATH"])
        r = self.B("git -C %s merge main" % self.SW, env=env)
        self.refused(r, "target")
        self.assertIn("worktrees cannot be listed", r.stderr)
        self.passes(self.B("git merge main", env=env, cwd=self.R))   # cwd's own top level stays allowed


class SubagentBindingTest(HookCase):
    def test_subagent_bound_to_main_checkout(self):   # TR5
        agent = self.agent(self.R)
        self.dirty()
        for command in ("git commit -m m", "git -C %s commit -m m" % self.R):
            with self.subTest(command=command):
                self.refused(self.B(command, agent=agent), "unstaged", absent=("target",))

    def test_unbound_subagent_record_forms(self):   # TR7, TR8, TR9
        W = self.worktree("W", "-b", "wb")
        gone = self.worktree("gone", "-b", "gb")
        agents = (("empty worktree", self.agent(""), None),
                  ("gone worktree", self.agent(gone), None))
        git(self.R, "worktree", "remove", "--force", gone)
        notdir = os.path.join(self.tmp, "plugin-file")
        write(notdir, "x")
        agents += (("plugin data a regular file", self.agent(W), dict(self.env, CLAUDE_PLUGIN_DATA=notdir)),)
        for label, agent, env in agents:
            with self.subTest(label):
                r = self.B("git -C %s commit -m m" % W, agent=agent, env=env)
                self.refused(r, "target")
                self.assertIn("this agent has no bound worktree (", r.stderr)

    def test_relative_worktree_record_refused_by_store(self):   # TR9 (relative form: the store refuses it first)
        W = self.worktree("W", "-b", "wb")
        agent = self.agent(W)
        path = os.path.join(self.plugin, "sessions", "sess-1.yml")
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn(W, text)
        write(path, text.replace(W, "rel/wt"))
        r = self.B("git -C %s commit -m m" % W, agent=agent)
        self.refused(r, "target")
        self.assertIn("this agent has no bound worktree (the session store is unavailable)", r.stderr)
        self.assertIn('is unreadable (dispatches[0].worktree: must be an absolute path or ""); start a new session',
                      r.stderr)

    def test_session_commit_without_plugin_data(self):   # PO5
        self.dirty()
        env = {k: v for k, v in self.env.items() if k != "CLAUDE_PLUGIN_DATA"}
        self.refused(self.B("git commit -m m", env=env), "unstaged", absent=("target",))

    def test_agent_vs_session(self):   # PB23
        W = self.worktree("W", "-b", "wb")
        agent = self.agent(W)
        decide = "python3 -m gates decisions decide X --by owner"
        self.assertNotIn("hook.bash.decide", self.B(decide).stderr)
        self.refused(self.B(decide, agent=agent), "decide")
        self.dirty()
        self.refused(self.B("git commit -m m"), "unstaged", absent=("target",))
        self.refused(self.B("git commit -m m", agent=agent), "target")

    def test_decide_agent_kinds(self):   # TX46
        decide = "python3 -m gates decisions decide X"
        self.refused(self.B(decide, agent=self.agent(self.R)), "decide")
        for bad in ("", "a b", None, "../x"):
            with self.subTest(agent_id=bad):
                r = self.B(decide, agent={"agent_id": bad, "agent_type": "implementer"})
                self.assertEqual(r.returncode, 2)
                self.assertNotIn("hook.bash.decide", r.stderr)
                self.assertRegex(r.stderr, r"FAIL hook\.")

    def test_decide_needs_decision_word(self):   # TX41
        agent = self.agent(self.R)
        for command in ("grep decide notes.md", "echo withdraw", 'git commit -m "decide"'):
            with self.subTest(command=command):
                self.assertNotIn("hook.bash.decide", self.B(command, agent=agent).stderr)

    def test_read_only_members_still_writes(self):   # GW2
        W = self.worktree("W", "-b", "wb")
        agent = self.agent(W)
        for sub in ("tag -l", "stash list", "worktree list", "reset --help"):
            with self.subTest(sub=sub):
                self.refused(self.B("git %s" % sub, agent=agent), "target")
                self.assertNotIn("hook.bash.target", self.B("git %s" % sub, cwd=W, agent=agent).stderr)

    def test_c_value_shapes(self):   # TR27
        spaced, accent = (self.worktree(n, "-b", "b%d" % i) for i, n in enumerate(("W with space", "Wé")))
        dashed = os.path.join(self.R, "-x")
        git(self.R, "worktree", "add", "-q", "-b", "dash", dashed)
        for target, quoted in ((spaced, "'%s'" % spaced), (accent, "'%s'" % accent)):
            with self.subTest(target=target):
                self.dirty(target)
                self.refused(self.B("git -C %s commit -m m" % quoted, agent=self.agent(target)), "unstaged",
                             absent=("target",))
        self.dirty(dashed)
        self.refused(self.B("git -C -x commit -m m", agent=self.agent(dashed)), "unstaged", absent=("target",))
        self.refused(self.B('git -C "a\nb" commit -m m', agent=self.agent(spaced)), "target")

    def test_c_as_last_word(self):   # TR27 (-C with no value; the observed verdicts, REF(global-option.-C) for a commit text)
        self.refused(self.B("git commit -m m && git -C"), "compound")
        self.passes(self.B("git add x && git -C"))   # stated limit: no commit word, so no commit check applies
        self.passes(self.B("git -C"))   # no commit word, not a write: no check applies
        r = self.B("git commit -C")   # -C as the last word of a commit text is git's own commit option (reuse message)
        self.assertNotIn("hook.bash.target", r.stderr)


class CommitShapeTest(HookCase):
    def test_commit_redirect_refused(self):   # CS4
        for command in ("git commit -F - <<'EOF'", "git commit -m m 2>&1", "git commit -m m > out", "git commit -m m < in"):
            with self.subTest(command=command):
                r = self.B(command)
                self.refused(r, "compound")
                self.assertIn("(redirection)", r.stderr)
        self.assertFalse(self.gates_ran())

    def test_cd_forms_not_plain(self):   # TR25, CS6
        W = self.worktree("W", "-b", "wb")
        agent = self.agent(W)
        for command in ("cd %s; git commit -m m" % W, "cd %s || git commit -m m" % W, "cd && git commit -m m",
                        "cd - && git commit -m m", "cd %s && cd y && git commit -m m" % W, "cd $W && git commit -m m",
                        "cd %s && git add x && git commit -m m" % W, "cd %s && git commit -m m && git push" % W):
            with self.subTest(command=command):
                self.refused(self.B(command, agent=agent), "compound")

    def test_compound_reasons(self):   # CS7
        for command, reason in (("git commit -m $MSG", "expansion"), ('git commit -m "$MSG"', "expansion"),
                                ("git commit -m *", "expansion"), ("git commit -m {a,b}", "character"),
                                ("git commit -m é", "character"), ("git commit -m \x00", "nul character"),
                                ('git commit -m "x', "unbalanced quote"), ("git commit -m m # c", "comment")):
            with self.subTest(command=command):
                r = self.B(command)
                self.refused(r, "compound")
                self.assertIn("FAIL hook.bash.compound: git commit runs as its own command (%s);" % reason, r.stderr)

    def test_commit_plain_whitespace(self):   # CS9
        self.dirty()
        for command in ("git commit -m m\n", "git\tcommit -m m", "git commit \\\n-m m"):
            with self.subTest(command=command):
                self.refused(self.B(command), "unstaged", absent=("compound",))

    def test_wrappers(self):   # CP1
        self.dirty()
        for command in ("/usr/bin/git commit -m m", "./git commit -m m", "/opt/x/git commit -m m"):
            with self.subTest(command=command):
                self.refused(self.B(command), "unstaged", absent=("not-git", "compound"))

    def test_allowed_assignments(self):   # CP11, CE4
        self.dirty()
        for command in ("LANG=C git commit -m m", "TZ=UTC git commit -m m", "LC_ALL=C git commit -m m",
                        "LANG=C env git commit -m m"):
            with self.subTest(command=command):
                self.refused(self.B(command), "unstaged", absent=("not-git", "compound", "index", "target"))

    def test_quoted_program_refused(self):   # CP12
        for command in ("'git' commit -m m", '"git" commit -m m', "g\\it commit -m m"):
            with self.subTest(command=command):
                self.refused(self.B(command), "compound")

    def test_commit_other_assignment_refused(self):   # CE5, CE6
        for command in ("FOO=1 git commit -m m", "git_index_file=x git commit -m m", "Git_Dir=x git commit -m m"):
            with self.subTest(command=command):
                self.refused(self.B(command), "compound")

    def test_which_step_wins(self):   # CR19
        self.dirty()
        r = self.B('GIT_INDEX_FILE=x git commit -m "--no-verify"')
        self.assertEqual(r.returncode, 2)
        self.assertEqual([ln.split(":")[0] for ln in r.stderr.splitlines()],
                         ["FAIL hook.bash.bypass.no-verify", "FAIL hook.bash.index"])
        self.assertFalse(self.gates_ran())

    def test_command_non_ascii(self):   # PB7
        self.dirty()
        self.refused(self.B('git commit -m "é"'), "unstaged", absent=("compound",))
        self.refused(self.B('git commit -m "\U0001fae0"'), "unstaged", absent=("compound",))
        for command in ("git commit -m é", "git commit -m é", "git commit -m \U0001fae0"):
            with self.subTest(command=command):
                r = self.B(command)
                self.refused(r, "compound")
                self.assertIn("(character)", r.stderr)
                self.assertNotIn("\U0001fae0", r.stderr)

    def test_command_control_chars(self):   # PB8
        self.refused(self.B("git commit\r-m m"), "compound")
        self.refused(self.B("git\fcommit"), "compound")

    def test_deny_render(self):   # PB16
        r = self.B("git commit --no-verify -m m && true")
        self.assertEqual((r.returncode, r.stdout), (2, ""))
        self.assertEqual(r.stderr, "\n".join(r.stderr.splitlines()) + "\n")
        self.assertEqual(len(r.stderr.splitlines()), 2)

    def test_subdirectory_cwd(self):   # PB27
        os.mkdir(os.path.join(self.R, "sub"))
        self.dirty()
        r = self.B("git commit -m m", cwd=os.path.join(self.R, "sub"))
        self.refused(r, "unstaged")
        self.assertIn("FAIL hook.bash.unstaged: a.txt: " + UNSTAGED_TAIL, r.stderr)

    def test_handler_module_wired(self):   # PB21
        from gates import hook
        self.assertEqual(hook.HANDLERS[("PreToolUse", "bash")], "gates.hooks.pre_bash")
        from gates.hooks import pre_bash
        self.assertTrue(callable(pre_bash.handle))
        r = self.B("true")
        self.passes(r)
        self.assertNotIn("hook.PreToolUse", r.stderr)

    def test_git_error_refuses_commit(self):   # PB19
        with open(os.path.join(self.R, ".git", "config"), "ab") as fh:
            fh.write(b"[alias]\n\tbad = \xff\n")
        r = self.B("git commit -m m")
        self.refused(r, "git")
        self.assertFalse(self.gates_ran())
        self.passes(self.B("ls"))
        self.refused(self.B("git status"), "git")   # D3-1 narrows CD2's "other commands pass" to commands with no git token

    def test_raising_handler_stand_in(self):   # V3
        import builtins
        import io
        from unittest import mock
        from gates import hook

        class Stand(BaseException):
            pass
        raisers = [Stand("stand-in")]
        group = getattr(builtins, "BaseExceptionGroup", None)
        if group is not None:
            raisers.append(group("g", [KeyboardInterrupt()]))
        data = json.dumps(hookrun.payload("PreToolUse", self.R, tool_input={"command": "git commit -m m", "description": "d"}))
        for exc in raisers:
            with self.subTest(exc=type(exc).__name__):
                out, err = io.StringIO(), io.StringIO()
                stdin = mock.Mock()
                stdin.buffer = io.BytesIO(data.encode("utf-8"))
                with mock.patch.object(githooks, "pre_commit_result", side_effect=exc), \
                        mock.patch.dict(os.environ, {"CLAUDE_PLUGIN_DATA": self.plugin}), \
                        mock.patch("sys.stdin", stdin), mock.patch("sys.stdout", out), mock.patch("sys.stderr", err):
                    code = hook.main(["PreToolUse"])
                self.assertEqual((code, out.getvalue()), (2, ""))
                self.assertRegex(err.getvalue(), r"^FAIL hook\.PreToolUse: ")

    def test_digit_limit_hook_json(self):   # V1a, V1b
        for digits, ok in ((4300, True), (4301, False)):
            with self.subTest(digits=digits):
                body = json.dumps(hookrun.payload("PreToolUse", self.R, tool_input={"command": "ls", "description": "d",
                                                                                     "n": 0}))
                data = body.replace('"n": 0', '"n": ' + "1" * digits).encode("utf-8")
                r = hookrun.run_hook("PreToolUse", data, self.env, FW)
                if ok:
                    self.passes(r)
                else:
                    self.assertEqual(r.returncode, 2)
                    self.assertIn("4300 digits", r.stderr)
        text = json.dumps(hookrun.payload("PreToolUse", self.R, tool_input={"command": "ls", "description": "9" * 4301}))
        self.passes(hookrun.run_hook("PreToolUse", text.encode("utf-8"), self.env, FW))

    def test_transcript_digits_binding(self):   # V1f
        W = self.worktree("W", "-b", "wb")
        for digits, bound in ((4300, True), (4301, False)):
            with self.subTest(digits=digits):
                agent = self.agent(W)
                sub = os.path.join(os.path.dirname(agent["transcript_path"]), "sess-1", "subagents", "agent-a1.jsonl")
                with open(sub, encoding="utf-8") as fh:
                    first = fh.read()
                write(sub, json.dumps({"type": "x", "n": 0}).replace(": 0", ": " + "1" * digits) + "\n" + first)
                r = self.B("git -C %s commit -m m" % W, agent=agent)
                if bound:
                    self.assertNotIn("hook.bash.target", r.stderr)
                else:
                    self.refused(r, "target")
                    self.assertIn("this agent has no bound worktree (", r.stderr)

    def test_unicode_paths_identical_bytes(self):   # V2a
        name = "\U0001fae0.txt"
        write(os.path.join(self.R, name), "1\n")
        commit_all(self.R, "unicode")
        write(os.path.join(self.R, name), "2\n")
        r = self.B("git commit -m m")
        self.refused(r, "unstaged")
        self.assertIn("FAIL hook.bash.unstaged: \\U0001fae0.txt: " + UNSTAGED_TAIL, r.stderr)
        self.assertNotIn("\U0001fae0", r.stderr)
        W = self.worktree("W\U0001fae0", "-b", "wb")
        r = self.B("git commit -m m", agent=self.agent(W))   # cwd R is not the bound worktree
        self.refused(r, "target")
        self.assertNotIn("\U0001fae0", r.stderr)
        self.assertIn("W\\U0001fae0", r.stderr)


class ConfigTest(HookCase):
    def put_config(self, text):
        write(os.path.join(self.R, ".strict-delivery", "config.yml"), text)

    def test_config_error_kinds(self):   # CC4, V1e
        good = dict(minimal_config())
        digits = "schema: config/2\nframework_version: 0.0.0\nprofile: strict\nbogus: "
        for label, text in (("schema", emit(dict(good, schema="config/1"))), ("unknown key", emit(dict(good, bogus=1))),
                            ("missing key", emit({"schema": "config/2", "profile": "strict"})),
                            ("profile", emit(dict(good, profile="weird"))), ("empty", ""),
                            ("4300 digits", digits + "1" * 4300 + "\n"), ("4301 digits", digits + "1" * 4301 + "\n")):
            with self.subTest(label):
                self.put_config(text)
                r = self.B("git commit -m m")
                self.refused(r, "config")
                self.assertIn("no commit runs until the config loads", r.stderr)
                if "digits" in label:
                    self.assertIn("integer too large", r.stderr)
                self.assertEqual(len(r.stderr.splitlines()), 1)
                self.passes(self.B("ls"))
        self.assertFalse(self.gates_ran())
        path = os.path.join(self.R, ".strict-delivery", "config.yml")
        moved = os.path.join(self.tmp, "config-moved.yml")
        os.rename(path, moved)
        os.mkdir(path)   # a directory at the path
        r = self.B("git commit -m m")
        self.refused(r, "config")
        self.assertIn("no commit runs until the config loads", r.stderr)
        self.assertEqual(len(r.stderr.splitlines()), 1)
        os.rename(path, os.path.join(self.tmp, "config-dir"))
        os.symlink("config.yml", path)   # a symlink loop
        r = self.B("git commit -m m")
        self.refused(r, "config")
        self.assertIn("no commit runs until the config loads", r.stderr)
        self.assertEqual(len(r.stderr.splitlines()), 1)
        self.assertFalse(self.gates_ran())

    def test_config_error_before_unstaged(self):   # CC8
        self.put_config("schema: [\n")
        r = self.B("git commit -m m")
        self.refused(r, "config", absent=("unstaged",))   # the config file itself is an unstaged change
        self.assertFalse(self.gates_ran())

    def test_target_config_used(self):   # CC6, CC7
        W = self.worktree("W", "-b", "wb")
        agent = self.agent(W)
        self.dirty(W)
        self.put_config("schema: [\n")   # cwd's root broken, the target fine
        r = self.B("git -C %s commit -m m" % W, agent=agent)
        self.refused(r, "unstaged", absent=("config",))
        git(self.R, "checkout", "--", ".strict-delivery/config.yml")
        write(os.path.join(W, ".strict-delivery", "config.yml"), "schema: [\n")   # cwd fine, the target broken
        r = self.B("git -C %s commit -m m" % W, agent=agent)
        self.refused(r, "config", absent=("unstaged",))
        self.assertIn("no commit runs until the config loads", r.stderr)

    def test_gates_commands_test_strict_only(self):   # CR9
        for profile in ("standard", "light"):
            with self.subTest(profile=profile):
                cfg = dict(minimal_config())
                cfg["profile"] = profile
                cfg["commands"] = {"test": "echo ran >> %s" % self.marker}
                write(os.path.join(self.R, ".strict-delivery", "config.yml"), emit(cfg))
                commit_all(self.R, "profile " + profile)
                self.passes(self.B("git commit -m m"))
                self.assertFalse(self.gates_ran())


class TreeStateTest(HookCase):
    def only_unstaged(self, r, *paths):
        self.refused(r, "unstaged")
        head = "FAIL hook.bash.unstaged: "
        listed = [ln[len(head):].split(": tracked file")[0] for ln in r.stderr.splitlines() if ln.startswith(head)]
        self.assertEqual(sorted(listed), sorted(paths))
        self.assertFalse(self.gates_ran())

    def two_files(self):
        write(os.path.join(self.R, "b.txt"), "1\n")
        write(os.path.join(self.R, "c.txt"), "1\n")
        commit_all(self.R, "bc")
        write(os.path.join(self.R, "b.txt"), "2\n")   # the sentinel: the one path that must be listed

    def test_staged_deletion_not_listed(self):   # CU4
        self.two_files()
        git(self.R, "rm", "-q", "c.txt")
        self.only_unstaged(self.B("git commit -m m"), "b.txt")

    def test_staged_rename_not_listed(self):   # CU5
        self.two_files()
        git(self.R, "mv", "c.txt", "d.txt")
        self.only_unstaged(self.B("git commit -m m"), "b.txt")

    def test_unstaged_rename(self):   # CU6
        os.rename(os.path.join(self.R, "a.txt"), os.path.join(self.R, "z.txt"))
        self.only_unstaged(self.B("git commit -m m"), "a.txt")

    def test_intent_to_add_listed(self):   # CU8
        write(os.path.join(self.R, "new.txt"), "x\n")
        git(self.R, "add", "-N", "new.txt")
        self.only_unstaged(self.B("git commit -m m"), "new.txt")

    def test_touch_not_listed(self):   # CU13
        self.two_files()
        os.utime(os.path.join(self.R, "c.txt"), (1, 1))
        self.only_unstaged(self.B("git commit -m m"), "b.txt")

    def test_unstaged_many_paths(self):   # CU11
        names = ["f%04d.txt" % n for n in range(1000)]
        for n in names:
            write(os.path.join(self.R, n), "1\n")
        commit_all(self.R, "many")
        for n in names:
            write(os.path.join(self.R, n), "2\n")
        r = self.B("git commit -m m")
        self.only_unstaged(r, *names)

    def test_submodule_changed_listed(self):   # CU9
        S = os.path.join(self.work, "S")
        os.mkdir(S)
        make_repo(S)
        git(self.R, "-c", "protocol.file.allow=always", "submodule", "add", "-q", S, "sub")
        commit_all(self.R, "submodule")
        write(os.path.join(self.R, "sub", "new.txt"), "x\n")   # only an untracked file inside the submodule
        self.only_unstaged(self.B("git commit -m m"), "sub")
        commit_all(os.path.join(self.R, "sub"), "inner")   # a new commit checked out in the submodule
        self.only_unstaged(self.B("git commit -m m"), "sub")

    def test_unmerged_listed(self):   # CU17
        git(self.R, "checkout", "-q", "-b", "other")
        write(os.path.join(self.R, "a.txt"), "other\n")
        commit_all(self.R, "other")
        git(self.R, "checkout", "-q", "feat")
        write(os.path.join(self.R, "a.txt"), "feat\n")
        commit_all(self.R, "feat")
        git(self.R, "merge", "other", check=False)
        r = self.B("git commit -m m")
        self.refused(r, "unstaged")
        self.assertIn("FAIL hook.bash.unstaged: a.txt: " + UNSTAGED_TAIL, r.stderr)   # git lists an unmerged path twice
        self.assertFalse(self.gates_ran())

    def test_unstaged_paths_raises(self):   # CU16 (git diff fails: a refusal on one gates line, not an exception)
        self.dirty()
        env = self.failing_git_env('*--ignore-submodules=none*) echo "fatal: injected" >&2; exit 128;;')
        r = self.B("git commit -m m", env=env)
        self.refused(r, "gates", absent=("unstaged",))
        self.assertEqual(r.stderr, "FAIL hook.bash.gates: git diff --name-only failed (exit 128)\n")
        self.assertFalse(self.gates_ran())

    def test_unborn_head(self):   # CU19
        U = os.path.join(self.work, "U")
        os.mkdir(U)
        git(U, "init", "-q", "-b", "main")
        cfg = dict(minimal_config())
        cfg["commands"] = {"test": "echo ran >> %s" % self.marker}
        write(os.path.join(U, ".strict-delivery", "config.yml"), emit(cfg))
        git(U, "add", ".strict-delivery/config.yml")
        r = self.B("git commit -m m", cwd=U)
        self.assertNotIn("hook.bash.unstaged", r.stderr)
        self.assertNotIn("FAIL hook.PreToolUse", r.stderr)
        # CU19 "unstaged_paths works on an unborn branch ... no raise": no `git diff` failure line and no unstaged line;
        # the gates then run on the unborn tree and their own lines (block 2: merge-base needs a commit) refuse, exit 2
        self.refused(r, "gates", absent=("unstaged", "git"))
        self.assertNotIn("git diff", r.stderr)
        self.assertEqual([ln.split(":")[0] for ln in r.stderr.splitlines()], ["FAIL hook.bash.gates"] * 3)
        self.assertIn("FAIL hook.bash.gates: register.input: git merge-base failed (exit 128)", r.stderr)


class GatesTest(HookCase):
    def test_gates_hooks_stale(self):   # CR5
        self.assertEqual(githooks.install(self.R, FW), [])
        path = os.path.join(self.R, ".git", "hooks", "pre-commit")
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("# edited\n")
        self.passes(self.B("git commit -m m"))
        self.assertTrue(self.gates_ran())

    def test_gates_run_all_failure_kept(self):   # CR7
        write(os.path.join(self.R, ".strict-delivery/state/decisions/DEC-20261031-k3f9.yml"), "schema: decision/999\n")
        git(self.R, "add", "-A")
        r = self.B("git commit -m m")
        self.refused(r, "gates")
        bad = ("FAIL hook.bash.gates: schema.decision..strict-delivery/state/decisions/DEC-20261031-k3f9.yml: schema: "
               "expected decision/2, got decision/999; run /strict-delivery:upgrade")
        self.assertEqual(r.stderr.splitlines().count(bad), 1)
        self.assertTrue(all(ln.startswith("FAIL hook.bash.gates: ") for ln in r.stderr.splitlines()))
        self.assertFalse(self.gates_ran())   # fail fast: commands.test not run

    def test_run_gates_raises(self):   # CR13 (GateError: the second git diff, the gates' own, fails)
        mark = os.path.join(self.tmp, "diff-seen")
        env = self.failing_git_env('*--ignore-submodules=none*) if [ -e "%s" ]; then echo "fatal: injected" >&2; exit 128; '
                                  'fi; : > "%s";;' % (mark, mark))
        r = self.B("git commit -m m", env=env)
        self.refused(r, "gates")
        self.assertEqual(r.stderr, "FAIL hook.bash.gates: git diff --name-only failed (exit 128)\n")
        self.assertTrue(os.path.exists(mark))   # the hook's own diff passed; the failing one was the gates'
        self.assertFalse(self.gates_ran())

    def test_gate_output_size(self):   # CR15
        cfg = dict(minimal_config())
        cfg["commands"] = {"test": "head -c 10485760 /dev/zero; head -c 1048576 /dev/zero >&2; echo ran >> %s" % self.marker}
        write(os.path.join(self.R, ".strict-delivery", "config.yml"), emit(cfg))
        commit_all(self.R, "big output")
        self.passes(self.B("git commit -m m"))   # 10 MiB of commands.test output is dropped, stdout stays empty
        self.assertTrue(self.gates_ran())
        write(os.path.join(self.R, ".strict-delivery/state/decisions/DEC-20261031-k3f9.yml"),
              "schema: decision/" + "9" * 1048576 + "\n")
        git(self.R, "add", "-A")
        r = self.B("git commit -m m")
        self.refused(r, "gates")
        self.assertTrue(all(ln.startswith("FAIL hook.bash.gates: ") for ln in r.stderr.splitlines()))

    def test_status_error_runs_gates(self):   # CR14
        notdir = os.path.join(self.tmp, "hooks-file")
        write(notdir, "x")
        git(self.R, "config", "core.hooksPath", notdir)
        self.passes(self.B("git commit -m m"))
        self.assertTrue(self.gates_ran())

    def test_flagged_file_gates_line(self):   # CU12
        git(self.R, "update-index", "--assume-unchanged", "a.txt")
        self.dirty()
        r = self.B("git commit -m m")
        self.refused(r, "gates")
        self.assertIn("FAIL hook.bash.gates: githook.flagged: a.txt: tracked file is flagged assume-unchanged or "
                      "skip-worktree", r.stderr)
        self.assertFalse(self.gates_ran())

    def test_gates_leave_tree_clean(self):   # PB25
        before = git(self.R, "status", "--porcelain", "--untracked-files=all")
        self.passes(self.B("git commit -m m"))
        self.assertTrue(self.gates_ran())
        self.assertEqual(git(self.R, "status", "--porcelain", "--untracked-files=all"), before)


CALLERS = ("session", "agent-R", "agent-W", "agent-nested")
CWDS = ("R", "nested")
TARGETS = ("R", "W", "nested", "nested/sub", "X", "/")


def cross_cells():
    """Every cell of the caller x target x cwd product (HR5, HR7, TR21, TR2-TR4, TR11, TR12): ``(caller, cwd, form, target)``
    with ``form`` in ``none`` (no named directory: the target is the cwd's top level), ``-C`` and ``cd`` (``cd <dir> &&``).
    The expected verdict is written by hand in ``cross_expected`` from the table sentences: a session may write in the top
    level of its cwd; a subagent only in its bound worktree; the top level of ``nested/sub`` is ``nested``; ``/`` has none."""
    cells = []
    for caller in CALLERS:
        for cwd in CWDS:
            cells.append((caller, cwd, "none", "cwd"))
            for form in ("-C", "cd"):
                for target in TARGETS:
                    cells.append((caller, cwd, form, target))
    return cells


def cross_expected(cell):
    """``(allowed, top)``: whether the cell's write is allowed, and the top level label the refusal names (``None`` for ``/``)."""
    caller, cwd, form, target = cell
    top = {"cwd": cwd, "R": "R", "W": "W", "nested": "nested", "nested/sub": "nested", "X": "X", "/": None}[target]
    allowed = {"session": cwd, "agent-R": "R", "agent-W": "W", "agent-nested": "nested"}[caller]
    return top == allowed, top


class CrossProductTest(HookCase):
    """R1-9: the caller x target x cwd product, every cell (owner rule 2026-11-24)."""

    def build(self):
        self.W = self.worktree("W", "-b", "wb")
        self.nested = os.path.join(self.R, "nested")
        git(self.R, "worktree", "add", "-q", "-b", "nb", self.nested)
        os.mkdir(os.path.join(self.nested, "sub"))
        self.X = os.path.join(self.work, "X")
        os.mkdir(self.X)
        make_repo(self.X)
        self.paths = {"R": self.R, "W": self.W, "nested": self.nested, "nested/sub": os.path.join(self.nested, "sub"),
                      "X": self.X, "/": "/"}
        self.callers = {"session": None, "agent-R": self.agent(self.R), "agent-W": self.agent(self.W),
                        "agent-nested": self.agent(self.nested)}

    def command(self, form, target):
        if form == "none":
            return "git tag x"
        return "git -C %s tag x" % self.paths[target] if form == "-C" else "cd %s && git tag x" % self.paths[target]

    def test_every_cell(self):   # HR5, HR7, TR21 (main session and subagent), TR2-TR4, TR11, TR12
        self.build()
        cells = cross_cells()
        self.assertEqual(len(cells), 4 * 2 * (1 + 2 * 6))
        counts = {True: 0, False: 0}
        for cell in cells:
            caller, cwd, form, target = cell
            allowed, top = cross_expected(cell)
            counts[allowed] += 1
            with self.subTest(cell=cell):
                r = self.B(self.command(form, target), cwd=self.paths[cwd], agent=self.callers[caller])
                if allowed:
                    self.passes(r)
                else:
                    self.refused(r, "target")
                    if top is None:
                        self.assertIn("FAIL hook.bash.target: / has no git top level; ", r.stderr)
                    else:
                        self.assertIn("FAIL hook.bash.target: %s is not a worktree this caller may write in (allowed: %s)"
                                      % (self.paths[top], self.paths[cross_expected_allowed(caller, cwd)]), r.stderr)
        self.assertEqual(counts, {True: 26, False: 78})   # the cells that pass are exactly the ones the table names


def cross_expected_allowed(caller, cwd):
    return {"session": cwd, "agent-R": "R", "agent-W": "W", "agent-nested": "nested"}[caller]


class QuoteSplitTest(HookCase):
    """R1-1 (ruling R1: every check reads the raw text and the quote-removed words) and R1-2 (alias resolution of a
    non-plain write): each refused as its unsplit form is, through the hook."""

    def setUp(self):
        super().setUp()
        self.W = self.worktree("W", "-b", "wb")
        self.agent_w = self.agent(self.W)   # a subagent bound to W, its cwd the main checkout R (not allowed)
        self.X = os.path.join(self.work, "X")
        os.mkdir(self.X)
        make_repo(self.X)

    def same(self, split, plain, **kw):
        a, b = self.B(split, **kw), self.B(plain, **kw)
        self.refused(b, "target")
        self.assertEqual((a.returncode, a.stdout, a.stderr), (b.returncode, b.stdout, b.stderr), split)
        return a

    def test_write_word_split(self):   # R1-1 member: _write_words
        for split, plain in (('git re""set --hard; ls', "git reset --hard; ls"), ("git t'a'g x; ls", "git tag x; ls"),
                             ('git wor""ktree list; ls', "git worktree list; ls")):
            with self.subTest(command=split):
                r = self.same(split, plain, agent=self.agent_w)
                self.assertIn("FAIL hook.bash.target: %s is not a worktree this caller may write in (allowed: %s)"
                              % (self.R, self.W), r.stderr)

    def test_git_word_split(self):   # R1-1 member: the git token
        self.same('gi""t reset --hard; ls', "git reset --hard; ls", agent=self.agent_w)
        self.same("'g'it reset --hard; ls", "git reset --hard; ls", agent=self.agent_w)

    def test_target_tokens_split(self):   # R1-1 members: the -C, --git-dir, --work-tree and cd tokens
        for split, plain in (('git -""C %s reset --hard; ls' % self.X, "git -C %s reset --hard; ls" % self.X),
                             ('git --git""-dir=%s reset --hard; ls' % self.X, "git --git-dir=%s reset --hard; ls" % self.X),
                             ('git --work""-tree=%s reset --hard; ls' % self.X, "git --work-tree=%s reset --hard; ls" % self.X),
                             ('c""d %s; git reset --hard' % self.X, "cd %s; git reset --hard" % self.X)):
            with self.subTest(command=split):
                r = self.same(split, plain)   # the main session: cwd R is allowed, the named directory decides
                self.assertIn("names its worktree only as one plain command", r.stderr)

    def test_alias_to_write_non_plain(self):   # R1-2 (GW11: alias resolved before the membership test, plain or not)
        git(self.R, "config", "alias.rs", "reset --hard")
        git(self.R, "config", "alias.rr", "rs")
        git(self.R, "config", "alias.st", "status")
        for plain, unsplit in (("git rs; ls", "git reset --hard; ls"), ("git RS; ls", "git reset --hard; ls"),
                               ("git rr; ls", "git reset --hard; ls"), ('git r""s; ls', "git reset --hard; ls"),
                               ("ls && git rs", "ls && git reset --hard")):
            with self.subTest(command=plain):
                self.same(plain, unsplit, agent=self.agent_w)
        self.passes(self.B("git st; ls", agent=self.agent_w))   # an alias of a read stays a pass
        self.passes(self.B("git st; ls"))

    def test_alias_to_write_option_non_plain(self):   # R1-2 (branch, checkout and switch write options through an alias)
        for name, value in (("bd", "branch -D"), ("cb", "checkout -b"), ("sc", "switch -c"), ("bf", "branch --force")):
            git(self.R, "config", "alias." + name, value)
        git(self.R, "config", "alias.bl", "branch --list")
        for name in ("bd", "cb", "sc", "bf"):
            with self.subTest(alias=name):
                r = self.B("git %s x; ls" % name, agent=self.agent_w)
                self.refused(r, "target")
                self.assertIn("%s is not a worktree this caller may write in (allowed: %s)" % (self.R, self.W), r.stderr)
        self.passes(self.B("git bl; ls", agent=self.agent_w))

    def test_alias_to_write_target_tokens_non_plain(self):   # R1-2 with R1-1: the -C refusal reads the alias form too
        git(self.R, "config", "alias.rs", "reset --hard")
        r = self.B("git -C %s rs; ls" % self.X)
        self.refused(r, "target")
        self.assertIn("names its worktree only as one plain command", r.stderr)


class ErrorPathTest(HookCase):
    """R1-4 (decision D3-1): when the policy or the aliases cannot be read, a command holding a ``git`` token (raw or
    quote-removed) is refused ``hook.bash.git`` with its way out; a command with no ``git`` token passes."""

    WAY = "; run it with the ! prefix if you must, or ask the owner\n"

    def bad_alias(self, root):
        with open(os.path.join(root, ".git", "config"), "ab") as fh:
            fh.write(b"[alias]\n\tbad = \xff\n")

    def git_refused(self, r):
        self.refused(r, "git")
        self.assertEqual(len(r.stderr.splitlines()), 1, r.stderr)
        self.assertTrue(r.stderr.startswith("FAIL hook.bash.git: "), r.stderr)
        self.assertTrue(r.stderr.endswith(self.WAY), r.stderr)

    def test_aliases_of_cwd_root_unreadable(self):   # :84 and the swallow at :131-133
        self.bad_alias(self.R)
        W = self.worktree("W", "-b", "wb")
        agent = self.agent(W)
        for command in ("git reset --hard", "git -C %s reset --hard" % W, "git status", "git log -1", "git tag x; ls",
                        "cd %s && git status" % W):
            with self.subTest(command=command):
                self.git_refused(self.B(command, agent=agent))
                self.git_refused(self.B(command))
        for command in ("ls", "echo hello", "echo digit gitx", "true; false", "rm -f nothing"):
            with self.subTest(command=command):
                self.passes(self.B(command, agent=agent))
                self.passes(self.B(command))

    def test_git_token_read_quote_removed(self):   # R1-1 member: the git and commit tokens of the fallback
        self.bad_alias(self.R)
        for command in ('gi""t status', "g'i't commit -m m", 'git com""mit -m m', 'gi""t com""mit -m m', "'git' log",
                        'gi""t reset --hard; ls', "GIT status", 'GI""T status'):   # the token is folded (CD4)
            with self.subTest(command=command):
                self.git_refused(self.B(command))
        for command in ('echo gi""tx', "echo digit gitx", 'echo "xgit"'):
            with self.subTest(command=command):
                self.passes(self.B(command))

    def test_aliases_of_target_root_unreadable(self):   # :92
        X = os.path.join(self.work, "X")
        os.mkdir(X)
        make_repo(X)
        self.bad_alias(X)
        for command in ("git -C %s status" % X, "git -C %s reset --hard" % X, "cd %s && git status" % X):
            with self.subTest(command=command):
                self.git_refused(self.B(command))

    def test_current_branch_unreadable(self):   # :50
        env = self.failing_git_env('*symbolic-ref*) echo "fatal: injected" >&2; exit 128;;')
        for command in ("git status", "git reset --hard", "git commit -m m"):
            with self.subTest(command=command):
                self.git_refused(self.B(command, env=env))
        self.passes(self.B("ls", env=env))
        self.passes(self.B("echo hello", env=env))

    def test_empty_git_subcommand(self):   # bashpolicy is_git_write("") GateError, caught in pre_bash
        for command in ("git ''", 'git "" status', "git '' reset --hard"):
            with self.subTest(command=command):
                self.git_refused(self.B(command))
        self.passes(self.B("echo ''"))

    def test_empty_alias_expansion_word(self):   # the same GateError reached through a non-plain alias
        git(self.R, "config", "alias.em", "''")
        self.git_refused(self.B("git em; ls"))

    def test_other_text_refusals_still_listed(self):   # the refusal list is kept ahead of the git line
        self.bad_alias(self.R)
        r = self.B("git status --no-verify")
        self.refused(r, "bypass.no-verify", "git")


if __name__ == "__main__":
    unittest.main()
