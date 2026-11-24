"""Tests of gates.lib.worktrees (Task 3a.2 input-domain rows W1-W10). Real git repositories and linked worktrees
(``tests.helpers``); expected values are written by hand from the plan (P:3488-3489, rulings (3b), (3c)) and the table."""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from gates.lib import programs, session, worktrees
from gates.lib.hookio import HookContext
from gates.lib.result import GateError
from tests.helpers import GitIsolatedTestCase, commit_all, git, make_repo

PROMPT = "worker brief: do the task"
HEADER = ("| stream | block | branch | worktree | next task | estimate | used | status | blockers | pending decisions "
          "| delivers |\n|---|---|---|---|---|---|---|---|---|---|---|\n")
PROG = "20261101-prog"
PROGRAMS = ".strict-delivery/state/programs"
CFG = {"paths": {"programs": PROGRAMS}}


def status_row(stream, wt):
    return "| %s | 3 | 20261101-prog/%s/main | %s | t1 | 1 | 0 | running | - | - | - |\n" % (stream, stream, wt)


def hand_ctx(cwd, agent_id=None, transcript_path=None, session_id="s1", root=None):
    return HookContext(event="PreToolUse", tool_name="Bash", tool_input={}, session_id=session_id, agent_id=agent_id,
                       transcript_path=transcript_path, cwd=cwd, root=root or cwd, cfg=CFG, cfg_error=None,
                       framework_dir="/", env={}, raw={})


def user_line(text):
    return json.dumps({"type": "user", "message": {"role": "user", "content": text}})


def new_state(*entries):
    st = {"schema": session.SCHEMA, "session": "s1", "dispatches": [], "surfaced": []}
    for e in entries:
        session.add_dispatch(st, *e)
    return st


def real(p):
    return os.path.realpath(p)


class Fixture(GitIsolatedTestCase):
    def setUp(self):
        super().setUp()
        self.main = os.path.join(self.work, "main")
        os.mkdir(self.main)
        make_repo(self.main)

    def add_wt(self, name, *args):
        path = os.path.join(self.work, name)
        git(self.main, "worktree", "add", *(list(args) + [path]))
        return path

    def sub_ctx(self, prompt=PROMPT, write_sub=True):
        self.sub_count = getattr(self, "sub_count", 0) + 1
        d = os.path.join(self.tmp, "proj%d" % self.sub_count)
        os.makedirs(os.path.join(d, "s1", "subagents"), exist_ok=True)
        main_t = os.path.join(d, "s1.jsonl")
        with open(main_t, "w", encoding="utf-8") as fh:
            fh.write(user_line("MAIN session prompt") + "\n")
        if write_sub:
            with open(os.path.join(d, "s1", "subagents", "agent-a1.jsonl"), "w", encoding="utf-8") as fh:
                fh.write(user_line(prompt) + "\n")
        return hand_ctx(self.main, agent_id="a1", transcript_path=main_t)


class AllowedSubagent(Fixture):
    def test_allowed_worktrees_for_subagent_and_session(self):   # W1, W3 (W4 in the next test)
        wt = self.add_wt("wt1", "-b", "feature")
        st = new_state((session.prompt_sha(PROMPT), "worker", 3, "session", wt, "feature"))
        with self.subTest("W1 subagent with a record"):
            self.assertEqual(worktrees.allowed(self.sub_ctx(), self.main, CFG, st), (frozenset({real(wt)}), []))
        with self.subTest("W1 the result types"):
            tops, fails = worktrees.allowed(self.sub_ctx(), self.main, CFG, st)
            self.assertIs(type(tops), frozenset)
            self.assertIs(type(fails), list)
        with self.subTest("W1 the main session's prompt is not the subagent's"):
            st2 = new_state((session.prompt_sha("MAIN session prompt"), "worker", 3, "session", wt, "feature"))
            tops, fails = worktrees.allowed(self.sub_ctx(), self.main, CFG, st2)
            self.assertEqual((tops, len(fails)), (frozenset(), 1))
        with self.subTest("W3 session, cwd the checkout"):
            self.assertEqual(worktrees.allowed(hand_ctx(self.main), self.main, CFG, st), (frozenset({real(self.main)}), []))
        with self.subTest("W3 session, cwd a subdirectory"):
            sub = os.path.join(self.main, "a", "b")
            os.makedirs(sub)
            self.assertEqual(worktrees.allowed(hand_ctx(sub), self.main, CFG, None), (frozenset({real(self.main)}), []))
        with self.subTest("W3 session, cwd a linked worktree"):
            self.assertEqual(worktrees.allowed(hand_ctx(wt), wt, CFG, st), (frozenset({real(wt)}), []))
        with self.subTest("W3 state None does not matter for the session"):
            self.assertEqual(worktrees.allowed(hand_ctx(self.main), self.main, CFG, None), (frozenset({real(self.main)}), []))

    def test_unbound_subagent_has_no_worktree(self):   # W2
        wt = self.add_wt("wt1", "-b", "feature")
        sha = session.prompt_sha(PROMPT)
        gone = os.path.join(self.work, "gone")
        prefix = "this agent has no bound worktree ("
        file_ctx = self.sub_ctx()
        rows = [
            ("no record", self.sub_ctx(), new_state(), "no single dispatch record matches its prompt"),
            ("other prompt only", self.sub_ctx(), new_state((session.prompt_sha("x"), "worker", 3, "session", wt, "f")),
             "no single dispatch record matches its prompt"),
            ("ambiguous record", self.sub_ctx(),
             new_state((sha, "worker", 3, "session", wt, "feature"), (sha, "worker", 3, "session", self.main, "main")),
             "no single dispatch record matches its prompt"),
            ("worktree empty", self.sub_ctx(), new_state((sha, "worker", 3, "session", "", "")),
             "its dispatch bound no worktree"),
            ("state None", self.sub_ctx(), None, "the session store is unavailable"),
            ("worktree missing on disk", self.sub_ctx(), new_state((sha, "worker", 3, "session", gone, "f")),
             "the bound worktree does not exist: " + gone),
            ("worktree a file", file_ctx, new_state((sha, "worker", 3, "session", file_ctx.transcript_path, "f")),
             "the bound worktree does not exist: " + file_ctx.transcript_path),
            ("worktree relative", self.sub_ctx(), new_state((sha, "worker", 3, "session", "wt1", "f")),
             "the bound worktree is not an absolute path: wt1"),
            ("first_prompt None (subagent transcript absent)", self.sub_ctx(write_sub=False),
             new_state((sha, "worker", 3, "session", wt, "feature")), "its transcript has no readable first prompt"),
            ("no transcript_path", hand_ctx(self.main, agent_id="a1", transcript_path=None),
             new_state((sha, "worker", 3, "session", wt, "feature")), "its transcript has no readable first prompt"),
        ]
        for name, c, st, reason in rows:
            with self.subTest(name):
                self.assertEqual(worktrees.allowed(c, self.main, CFG, st), (frozenset(), [prefix + reason + ")"]))

    def test_unbound_subagent_never_gets_the_cwd_top_level(self):   # W2 (the mutant m3 target, named apart)
        c = self.sub_ctx()
        tops, fails = worktrees.allowed(c, self.main, CFG, new_state())
        self.assertNotIn(real(self.main), tops)
        self.assertEqual(len(fails), 1)


class AllowedSession(Fixture):
    def make_program(self, with_status=""):
        """A live program <p>: branch <p>/integration holding streams.yml and status.md, checked out in a worktree."""
        self.int_wt = os.path.join(self.work, "int")
        self.status_wt = os.path.join(self.work, "stream1")
        git(self.main, "checkout", "-q", "-b", PROG + "/integration")
        d = os.path.join(self.main, PROGRAMS, PROG)
        os.makedirs(d)
        with open(os.path.join(d, "streams.yml"), "w", encoding="utf-8") as fh:
            fh.write("schema: streams/1\n")
        self.write_status(self.main, status_row("s1", self.status_wt) if with_status == "" else with_status)
        git(self.main, "checkout", "-q", "main")
        git(self.main, "worktree", "add", self.int_wt, PROG + "/integration")
        git(self.main, "worktree", "add", "-b", PROG + "/s1/main", self.status_wt, "main")

    def write_status(self, where, rows):
        path = os.path.join(where, PROGRAMS, PROG, "status.md")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("# status\n\n" + HEADER + rows)
        commit_all(where, "status")

    def test_session_with_live_program(self):   # W4
        self.make_program()
        want = frozenset({real(self.main), real(self.status_wt), real(self.int_wt)})
        self.assertEqual(worktrees.allowed(hand_ctx(self.main), self.main, CFG, None), (want, []))
        with self.subTest("cwd a subdirectory of the main checkout"):
            sub = os.path.join(self.main, "x")
            os.mkdir(sub)
            self.assertEqual(worktrees.allowed(hand_ctx(sub), self.main, CFG, None), (want, []))
        with self.subTest("cwd the integration worktree: its own top level and the stream's, not the main checkout"):
            tops, fails = worktrees.allowed(hand_ctx(self.int_wt), self.int_wt, CFG, None)
            self.assertEqual((tops, fails), (frozenset({real(self.int_wt), real(self.status_wt)}), []))

    def test_subagent_with_live_program_gets_only_its_own(self):   # W1 with a live program
        self.make_program()
        wt = self.add_wt("wt1", "-b", "feature")
        st = new_state((session.prompt_sha(PROMPT), "worker", 3, "session", wt, "feature"))
        self.assertEqual(worktrees.allowed(self.sub_ctx(), self.main, CFG, st), (frozenset({real(wt)}), []))

    def test_allowed_status_cells(self):   # W5
        gone = os.path.join(self.work, "never-made")
        plain = os.path.join(self.work, "plain-dir")
        os.mkdir(plain)
        other = os.path.join(self.work, "other-repo")
        os.mkdir(other)
        make_repo(other)
        self.make_program()
        base = frozenset({real(self.main), real(self.int_wt)})
        both = base | {real(self.status_wt)}
        rows = [
            ("missing path", status_row("s1", gone), base, 1),
            ("relative path", status_row("s1", "stream1"), base, 1),
            ("relative dot path", status_row("s1", "./stream1"), base, 1),
            ("empty cell", status_row("s1", ""), base, 0),
            ("dash cell", status_row("s1", "-"), base, 0),
            ("__error__ row", "| s1 | only | three |\n", base, 1),
            ("existing directory that is no worktree", status_row("s1", plain), base, 1),
            ("worktree of another repository", status_row("s1", other), base, 1),
            ("a subdirectory of a worktree", status_row("s1", self.main + "/.strict-delivery"), base, 1),
            ("good and missing", status_row("s1", self.status_wt) + status_row("s2", gone), both, 1),
            ("good, empty, dash", status_row("s1", self.status_wt) + status_row("s2", "") + status_row("s3", "-"), both, 0),
        ]
        for name, text, tops, nfails in rows:
            with self.subTest(name):
                self.write_status(self.int_wt, text)
                got_tops, got_fails = worktrees.allowed(hand_ctx(self.main), self.main, CFG, None)
                self.assertEqual(got_tops, tops)
                self.assertEqual(len(got_fails), nfails, got_fails)
                for f in got_fails:
                    self.assertIn(PROG, f)
                    self.assertNotIn("\n", f)

    def fake_git(self, refused):
        """A directory holding a `git` that exits 129 `error: unknown option` when `refused` is an argument, else runs
        the real git (an old git without that option)."""
        real_git = shutil.which("git")
        d = os.path.join(self.tmp, "fakebin%s" % refused.strip("-").replace("=", "_"))
        os.mkdir(d)
        path = os.path.join(d, "git")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write('#!/bin/sh\nfor a in "$@"; do\n  if [ "$a" = "%s" ]; then echo "error: unknown option" >&2; exit 129; fi\n'
                     'done\nexec "%s" "$@"\n' % (refused, real_git))
        os.chmod(path, 0o755)
        return d

    def test_old_git_fails_closed(self):   # V7 (F-20261124-5gfw)
        self.make_program()
        full = frozenset({real(self.main), real(self.status_wt), real(self.int_wt)})
        self.assertEqual(worktrees.allowed(hand_ctx(self.main), self.main, CFG, None), (full, []))
        old = self.fake_git("--porcelain")
        with mock.patch.dict(os.environ, {"PATH": old + os.pathsep + os.environ["PATH"]}):
            with self.subTest("worktree list --porcelain -z (git 2.36)"):
                with self.assertRaises(GateError) as cm:
                    worktrees.worktree_list(self.main)
                self.assertIn("worktree list", str(cm.exception))
                self.assertIn("129", str(cm.exception))
                with self.assertRaises(GateError):
                    worktrees.bound_branch(self.main)
                tops, fails = worktrees.allowed(hand_ctx(self.main), self.main, CFG, None)
                self.assertEqual(tops, frozenset({real(self.main)}))
                self.assertEqual(len(fails), 1)
                self.assertIn("worktrees cannot be listed", fails[0])
            with self.subTest("the other call still works"):
                self.assertIs(worktrees.same_repository(self.main, self.main), True)
        new = self.fake_git("--path-format=absolute")
        with mock.patch.dict(os.environ, {"PATH": new + os.pathsep + os.environ["PATH"]}):
            with self.subTest("rev-parse --path-format=absolute (git 2.31)"):
                self.assertIs(worktrees.same_repository(self.main, self.main), False)
                self.assertIs(worktrees.same_repository(self.main, self.status_wt), False)
            with self.subTest("allowed never widens"):
                tops, fails = worktrees.allowed(hand_ctx(self.main), self.main, CFG, None)
                self.assertLessEqual(tops, full)
                self.assertIn(real(self.main), tops)
            with self.subTest("the other call still works"):
                self.assertEqual(len(worktrees.worktree_list(self.main)), 3)

    def test_missing_status_page_adds_a_fail(self):   # a live program whose tip holds no status.md: narrower set, one fail
        self.make_program()
        git(self.int_wt, "rm", "-q", os.path.join(PROGRAMS, PROG, "status.md"))
        commit_all(self.int_wt, "drop status")
        tops, fails = worktrees.allowed(hand_ctx(self.main), self.main, CFG, None)
        self.assertEqual(tops, frozenset({real(self.main), real(self.int_wt)}))
        self.assertEqual(len(fails), 1)
        self.assertIn(PROG, fails[0])

    def test_status_page_header_shapes(self):   # W5b
        self.make_program()
        base = frozenset({real(self.main), real(self.int_wt)})
        cells = HEADER.split("\n")[0].split("|")[1:-1]
        sep = HEADER.split("\n")[1] + "\n"
        row = status_row("s1", self.status_wt)
        page = os.path.join(self.int_wt, PROGRAMS, PROG, "status.md")

        def write_page(text):
            with open(page, "w", encoding="utf-8") as fh:
                fh.write(text)
            commit_all(self.int_wt, "page")
        bad = [
            ("no header", "# status\n\n" + row),
            ("renamed cell", "| " + " | ".join(["worktre" if c.strip() == "worktree" else c.strip() for c in cells]) + " |\n" + sep + row),
            ("10 cells", "| " + " | ".join(c.strip() for c in cells[:10]) + " |\n" + sep + row),
            ("12 cells", "| " + " | ".join([c.strip() for c in cells] + ["extra"]) + " |\n" + sep + row),
            ("no separator", HEADER.split("\n")[0] + "\n" + row),
            ("malformed separator", HEADER.split("\n")[0] + "\n| x |\n" + row),
        ]
        for name, text in bad:
            with self.subTest(name):
                write_page(text)
                tops, fails = worktrees.allowed(hand_ctx(self.main), self.main, CFG, None)
                self.assertEqual(tops, base)
                self.assertEqual(fails, ["program %s: %s has no status table" % (PROG, "%s/%s/status.md" % (PROGRAMS, PROG))])
        with self.subTest("right header and separator, zero rows"):
            write_page("# status\n\n" + HEADER)
            self.assertEqual(worktrees.allowed(hand_ctx(self.main), self.main, CFG, None), (base, []))

    def test_status_page_is_read_at_the_integration_tip(self):   # ruling (3b): not the main checkout's file
        self.make_program()
        stale = os.path.join(self.main, PROGRAMS, PROG)
        os.makedirs(stale, exist_ok=True)
        with open(os.path.join(stale, "status.md"), "w", encoding="utf-8") as fh:
            fh.write("# stale\n\n" + HEADER + status_row("s1", os.path.join(self.work, "never-made")))
        tops, fails = worktrees.allowed(hand_ctx(self.main), self.main, CFG, None)   # a work-tree file, not committed
        self.assertEqual((tops, fails), (frozenset({real(self.main), real(self.status_wt), real(self.int_wt)}), []))

    def test_unreadable_status_page_adds_a_fail(self):   # W5c-u: gitinfo.show fails with a git error
        self.make_program()
        base = frozenset({real(self.main), real(self.int_wt)})
        bad = os.path.join(self.tmp, "fakebin-status")   # a git that fails only the call naming the status page
        os.mkdir(bad)
        with open(os.path.join(bad, "git"), "w", encoding="utf-8") as fh:
            fh.write('#!/bin/sh\nfor a in "$@"; do\n  case "$a" in *status.md) echo "fatal: broken" >&2; exit 128;; esac\n'
                     'done\nexec "%s" "$@"\n' % shutil.which("git"))
        os.chmod(os.path.join(bad, "git"), 0o755)
        with mock.patch.dict(os.environ, {"PATH": bad + os.pathsep + os.environ["PATH"]}):
            tops, fails = worktrees.allowed(hand_ctx(self.main), self.main, CFG, None)
        self.assertEqual(tops, base)
        self.assertEqual(len(fails), 1, fails)
        self.assertTrue(fails[0].startswith("program %s: status page unreadable (" % PROG), fails[0])
        self.assertNotIn("\n", fails[0])

    def test_allowed_programs_error(self):   # W6
        for name, cfg in (("no paths.programs", {"paths": {}}), ("cfg not a dict", None), ("empty programs dir", {"paths": {"programs": ""}})):
            with self.subTest(name):
                tops, fails = worktrees.allowed(hand_ctx(self.main), self.main, cfg, None)
                self.assertEqual(tops, frozenset({real(self.main)}))
                self.assertEqual(len(fails), 1)
                self.assertNotIn("\n", fails[0])

    def test_session_cwd_outside_git(self):   # not stated for the session: no top level, no tops, one fail
        plain = os.path.join(self.work, "plain")
        os.mkdir(plain)
        tops, fails = worktrees.allowed(hand_ctx(plain), self.main, CFG, None)
        self.assertEqual((tops, len(fails)), (frozenset(), 1))
        missing = os.path.join(self.work, "nowhere")
        tops, fails = worktrees.allowed(hand_ctx(missing), self.main, CFG, None)
        self.assertEqual((tops, len(fails)), (frozenset(), 1))


class WorktreeList(Fixture):
    def test_worktree_list(self):   # W7
        det = self.add_wt("det", "--detach")
        spaced = self.add_wt("with space", "-b", "sp")
        nl = os.path.join(self.work, "a\nb")
        git(self.main, "worktree", "add", "-b", "nl", nl)
        slash = self.add_wt("slash", "-b", "p1/s1/main")
        locked = self.add_wt("locked", "-b", "lk")
        git(self.main, "worktree", "lock", locked)
        moved = self.add_wt("tomove", "-b", "pr")
        os.rename(moved, os.path.join(self.work, "moved-away"))   # git now sees a prunable worktree
        got = worktrees.worktree_list(self.main)
        self.assertEqual(got[0], (self.main, "main"))
        self.assertEqual(sorted(got[1:]), sorted([(det, None), (spaced, "sp"), (nl, "nl"), (slash, "p1/s1/main"),
                                                   (locked, "lk"), (moved, "pr")]))
        self.assertTrue(all(type(e) is tuple and len(e) == 2 for e in got))
        with self.subTest("the same list from a linked worktree"):
            self.assertEqual(sorted(worktrees.worktree_list(slash), key=lambda e: e[0]), sorted(got, key=lambda e: e[0]))
        with self.subTest("root a subdirectory"):
            os.mkdir(os.path.join(self.main, "sub"))
            self.assertEqual(sorted(worktrees.worktree_list(os.path.join(self.main, "sub"))), sorted(got))

    def test_worktree_list_bare_main(self):   # W7: a bare main entry is (path, None)
        bare = os.path.join(self.work, "bare.git")
        os.mkdir(bare)
        git(bare, "init", "-q", "--bare", "-b", "main")
        self.assertEqual(worktrees.worktree_list(bare), [(bare, None)])
        with self.subTest("a bare repository with a linked worktree"):
            git(self.main, "remote", "add", "o", bare)
            git(self.main, "push", "-q", "o", "main")
            linked = os.path.join(self.work, "from-bare")
            git(bare, "worktree", "add", linked, "main")
            self.assertEqual(sorted(worktrees.worktree_list(bare)), sorted([(bare, None), (linked, "main")]))

    def test_worktree_list_errors(self):   # not a repository, a missing path, a non-str root
        plain = os.path.join(self.work, "plain")
        os.mkdir(plain)
        for name, root in (("not a repository", plain), ("missing", os.path.join(self.work, "nowhere")), ("None", None),
                           ("int", 5), ("empty", "")):
            with self.subTest(name):
                with self.assertRaises(GateError):
                    worktrees.worktree_list(root)

    def test_worktree_list_env(self):   # W8
        other = os.path.join(self.work, "other")
        os.mkdir(other)
        make_repo(other)
        extra = os.path.join(self.work, "other-linked")
        git(other, "worktree", "add", "-b", "ob", extra)
        mine = self.add_wt("mine", "-b", "mb")
        want = sorted([(self.main, "main"), (mine, "mb")])
        env = {"GIT_DIR": os.path.join(other, ".git"), "GIT_WORK_TREE": other, "GIT_COMMON_DIR": os.path.join(other, ".git"),
               "GIT_NAMESPACE": "ns", "GIT_CEILING_DIRECTORIES": self.work, "LC_ALL": "de_DE.UTF-8"}
        seen = []
        real_run = subprocess.run

        def spy(*a, **k):
            seen.append(k.get("env"))
            return real_run(*a, **k)

        with mock.patch.dict(os.environ, env):
            with mock.patch.object(worktrees.subprocess, "run", side_effect=spy):
                got = worktrees.worktree_list(self.main)
        self.assertEqual(sorted(got), want)
        self.assertEqual(len(seen), 1)
        for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_OBJECT_DIRECTORY",
                     "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_NAMESPACE", "GIT_CEILING_DIRECTORIES"):
            self.assertNotIn(name, seen[0])
        self.assertEqual(seen[0]["LC_ALL"], "C")
        with self.subTest("LC_ALL unset"):
            seen.clear()
            with mock.patch.dict(os.environ):
                os.environ.pop("LC_ALL", None)
                with mock.patch.object(worktrees.subprocess, "run", side_effect=spy):
                    self.assertEqual(sorted(worktrees.worktree_list(self.main)), want)
            self.assertEqual(seen[0]["LC_ALL"], "C")
        with self.subTest("the argument list is the -z porcelain form"):
            seen_args = []
            def spy_args(argv, *a, **k):
                seen_args.append(argv)
                return real_run(argv, *a, **k)
            with mock.patch.object(worktrees.subprocess, "run", side_effect=spy_args):
                worktrees.worktree_list(self.main)
            self.assertEqual(seen_args[0][-4:], ["worktree", "list", "--porcelain", "-z"])


class BoundBranchAndSameRepository(Fixture):
    def test_bound_branch(self):   # W9
        feat = self.add_wt("feat", "-b", "p1/s1/main")
        det = self.add_wt("det", "--detach")
        plain = os.path.join(self.work, "plain")
        os.mkdir(plain)
        sub = os.path.join(self.main, "sub")
        os.mkdir(sub)
        link = os.path.join(self.work, "link-to-feat")
        os.symlink(feat, link)
        self.assertEqual(worktrees.bound_branch(self.main), "main")
        self.assertEqual(worktrees.bound_branch(feat), "p1/s1/main")
        self.assertIsNone(worktrees.bound_branch(det))
        self.assertEqual(worktrees.bound_branch(link), "p1/s1/main")
        for name, path in (("a subdirectory", sub), ("not a repository", plain),
                           ("missing", os.path.join(self.work, "nowhere")), ("None", None), ("empty", "")):
            with self.subTest(name):
                with self.assertRaises(GateError):
                    worktrees.bound_branch(path)

    def test_bound_branch_follows_a_switch(self):   # the branch is the one checked out now
        git(self.main, "checkout", "-q", "-b", "later")
        self.assertEqual(worktrees.bound_branch(self.main), "later")
        git(self.main, "checkout", "-q", "--detach")
        self.assertIsNone(worktrees.bound_branch(self.main))

    def test_same_repository(self):   # W10
        linked = self.add_wt("linked", "-b", "b2")
        other = os.path.join(self.work, "other")
        os.mkdir(other)
        make_repo(other)
        plain = os.path.join(self.work, "plain")
        os.mkdir(plain)
        for name, a, b, expected in (
                ("main and linked", self.main, linked, True),
                ("linked and main", linked, self.main, True),
                ("same path", self.main, self.main, True),
                ("another repository", self.main, other, False),
                ("a non-repository path", self.main, plain, False),
                ("a non-repository first", plain, self.main, False),
                ("a missing path", self.main, os.path.join(self.work, "nowhere"), False),
                ("a missing first", os.path.join(self.work, "nowhere"), self.main, False),
                ("both missing", os.path.join(self.work, "n1"), os.path.join(self.work, "n1"), False),
                ("None", self.main, None, False),
                ("empty", "", self.main, False),
                ("int", 5, self.main, False)):
            with self.subTest(name):
                self.assertIs(worktrees.same_repository(a, b), expected)

    def test_same_repository_ignores_inherited_git_env(self):   # the call runs with the gitinfo environment
        other = os.path.join(self.work, "other")
        os.mkdir(other)
        make_repo(other)
        with mock.patch.dict(os.environ, {"GIT_DIR": os.path.join(other, ".git"), "GIT_COMMON_DIR": os.path.join(other, ".git")}):
            self.assertIs(worktrees.same_repository(self.main, other), False)
            self.assertIs(worktrees.same_repository(self.main, self.main), True)


if __name__ == "__main__":
    unittest.main()
