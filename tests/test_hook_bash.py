"""Tests of the PreToolUse Bash hook (Task 3b.2, Producer 10 and the plan's Step 1 tests), run through the production entry
(``python3 -m gates hook PreToolUse``, ``tests.hookrun.run_hook``) on real repositories and linked worktrees. The expected
values are written by hand from the task-3b.2 input-domain table (row ids in the comments)."""
import json
import os
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
        # hookio.context re-raises GitNotFound (3a.2): the handler is never reached, the hook fails closed for every
        # command; this differs from table row PB20 (ls: PASS) and is reported as a divergence.
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
        start = time.time()
        self.refused(self.B("git -C %s commit -m m" % fifo, agent=agent), "target")
        self.refused(self.B("git -C /dev/null commit -m m", agent=agent), "target")
        self.assertLess(time.time() - start, 30)
        os.rename(os.path.join(self.R, ".strict-delivery", "config.yml"), os.path.join(self.tmp, "config.moved"))
        os.mkfifo(os.path.join(self.R, ".strict-delivery", "config.yml"))
        start = time.time()
        r = self.B("git commit -m m")
        self.assertLess(time.time() - start, 30)
        self.assertIn(r.returncode, (0, 2))

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


if __name__ == "__main__":
    unittest.main()
