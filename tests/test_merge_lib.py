"""Tests of gates/lib/merge.py: ``merged_errors`` (Task P2.1 part i; specified under Task P3.1; rows MG1-MG36 of the part
A table; decisions D-A17, D-A18, D-A23). Every repository is a ``make_repo`` fixture whose config comes from
``minimal_config()`` and whose git config sets ``color.ui=always``, ``color.diff=always`` and ``core.abbrev=7``."""
import ast
import os
import unittest
from unittest import mock

from gates.lib import config, gitinfo
from gates.lib.merge import MODES, agent_may_merge, merged_errors
from gates.lib.result import GateError, GitNotFound
from tests.helpers import INT_LIMITS, GitIsolatedTestCase, commit_all, git, int_limit, make_repo, minimal_config

PS = ".strict-delivery/state/plans"
P_LEDGER = PS + "/p/ledger.md"
Q_LEDGER = PS + "/q/ledger.md"
ABSENT40 = "89abcdef0123456789abcdef0123456789abcdef"
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class _Sub(str):
    pass


def ids(errors):
    return [suffix for suffix, _ in errors]


class MergeCase(GitIsolatedTestCase):
    def setUp(self):
        super().setUp()
        self.root = self.new_repo(self.work, "controller")
        self.cfg = config.load(self.root)
        self.host_cfg = dict(self.cfg, merge={"mode": "host"})
        self.A = git(self.root, "rev-parse", "HEAD")

    def new_repo(self, path, mode):
        os.makedirs(path, exist_ok=True)
        cfg = minimal_config()
        if mode is not None:
            cfg["merge"] = {"mode": mode}
        root = make_repo(path, cfg)
        for k, v in (("color.ui", "always"), ("color.diff", "always"), ("core.abbrev", "7")):
            git(root, "config", k, v)
        return root

    def put(self, rel, text="x\n", root=None):
        path = os.path.join(root or self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)

    def pr(self, name, files, how="no-ff", root=None, base="main"):
        """A branch off ``base`` with one commit that writes ``files`` (a dict), merged into ``base`` the way ``how``
        says; returns ``(head of the branch, HEAD of base after the merge)``."""
        r = root or self.root
        git(r, "checkout", "-q", "-b", name, base)
        for rel, text in files.items():
            self.put(rel, text, r)
        head = commit_all(r, "work " + name)
        git(r, "checkout", "-q", base)
        if how == "no-ff":
            git(r, "merge", "-q", "--no-ff", "-m", "Merge " + name, name)
        elif how == "ff":
            git(r, "merge", "-q", "--ff-only", name)
        elif how == "squash":
            git(r, "merge", "-q", "--squash", name)
            git(r, "commit", "-q", "-m", "squash " + name)
        return head, git(r, "rev-parse", "HEAD")

    def line(self, head, merge_sha, **over):
        d = {"pr": 7, "head": head, "merge": merge_sha, "merged_by": "owner", "at": "2026-11-18T10:00:00Z",
             "final": "no", "stream": "a", "block": "3d", "approval": "chat", "approval_pr": 7, "approval_head": head,
             "words": "merge it"}
        d.update(over)
        return d

    def good(self):
        head, m = self.pr("f", {P_LEDGER: "ledger\n", "code.py": "x = 1\n"})
        return head, m, self.line(head, m)


class MergedLineTests(MergeCase):
    def test_merged_line_checked_against_git(self):  # MG1, plan :2706
        head, m, line = self.good()
        self.assertEqual(merged_errors(self.root, self.cfg, "p", line), [])
        errs = merged_errors(self.root, self.cfg, "p", {**line, "head": self.A})
        self.assertEqual(ids(errs), ["head.7", "approval.7"])  # the chat approval still names the old head

    def test_merged_line_host_mode(self):  # MG2
        head, m, line = self.good()
        host = self.line(head, m, approval="host", approval_pr=None, approval_head=None, words=None)
        self.assertEqual(merged_errors(self.root, self.host_cfg, "p", host), [])

    def test_merged_head_must_be_second_parent(self):  # MG3
        head, m, line = self.good()
        errs = merged_errors(self.root, self.cfg, "p", {**line, "head": self.A, "approval_head": self.A})
        self.assertEqual(ids(errs), ["head.7"])
        reason = dict(errs)["head.7"]
        self.assertIn(head, reason)
        self.assertIn(self.A, reason)

    def test_squash_is_no_merge(self):  # MG4, plan :2714
        head, m = self.pr("sq", {P_LEDGER: "ledger\n"}, how="squash")
        errs = merged_errors(self.root, self.cfg, "p", self.line(head, m))
        self.assertEqual(ids(errs), ["merge.7"])
        self.assertIn("1 parent", dict(errs)["merge.7"])

    def test_merged_fast_forward_refused(self):  # MG5
        head, m = self.pr("ff", {P_LEDGER: "ledger\n"}, how="ff")
        self.assertEqual(head, m)
        self.assertEqual(ids(merged_errors(self.root, self.cfg, "p", self.line(head, m))), ["merge.7"])

    def test_merged_octopus_refused(self):  # MG6
        h1, _ = self.pr("o1", {P_LEDGER: "ledger\n"}, how="none")
        h2, _ = self.pr("o2", {"code.py": "x\n"}, how="none")
        git(self.root, "merge", "-q", "--no-ff", "-m", "octopus", "o1", "o2")
        m = git(self.root, "rev-parse", "HEAD")
        errs = merged_errors(self.root, self.cfg, "p", self.line(h1, m))
        self.assertEqual(ids(errs), ["merge.7"])
        self.assertIn("3 parent", dict(errs)["merge.7"])

    def test_merged_off_first_parent_line(self):  # MG7: the inner merge is reachable through a second parent only
        r = self.root
        git(r, "checkout", "-q", "-b", "side")
        self.put(P_LEDGER, "ledger\n")
        commit_all(r, "s1")
        git(r, "checkout", "-q", "main")
        self.put("m1.txt")
        m1 = commit_all(r, "m1")
        git(r, "checkout", "-q", "side")
        git(r, "merge", "-q", "--no-ff", "-m", "inner", "main")
        inner = git(r, "rev-parse", "HEAD")
        git(r, "checkout", "-q", "main")
        git(r, "merge", "-q", "--no-ff", "-m", "outer", "side")
        outer = git(r, "rev-parse", "HEAD")
        self.assertEqual(git(r, "rev-parse", inner + "^2"), m1)
        errs = merged_errors(r, self.cfg, "p", self.line(m1, inner))
        self.assertEqual(ids(errs), ["merge.7"])
        self.assertIn("first-parent history of main", dict(errs)["merge.7"])
        outer_head = git(r, "rev-parse", outer + "^2")
        self.assertEqual(merged_errors(r, self.cfg, "p", self.line(outer_head, outer)), [])  # the line on the first-parent line

    def test_merged_unknown_sha_says_update_from_remote(self):  # MG8
        head, m, line = self.good()
        errs = merged_errors(self.root, self.cfg, "p", {**line, "merge": ABSENT40})
        self.assertEqual(ids(errs), ["merge.7"])
        self.assertIn("%s is not a commit in this repository; update main from the remote" % ABSENT40, dict(errs)["merge.7"])

    def test_merged_not_on_base_branch(self):  # MG9: a real two-parent commit that main does not hold
        r = self.root
        git(r, "checkout", "-q", "-b", "t2", "main")
        git(r, "checkout", "-q", "-b", "side3", "main")
        self.put("s3.txt")
        h = commit_all(r, "s3")
        git(r, "checkout", "-q", "t2")
        git(r, "merge", "-q", "--no-ff", "-m", "unmerged merge", "side3")
        mg = git(r, "rev-parse", "HEAD")
        git(r, "checkout", "-q", "main")
        errs = merged_errors(r, self.cfg, "p", self.line(h, mg))
        self.assertEqual(ids(errs), ["merge.7"])
        self.assertIn("is not on the first-parent history of main", dict(errs)["merge.7"])

    def test_merged_non_commit_merge_sha(self):  # MG10
        head, m, line = self.good()
        tree = git(self.root, "rev-parse", m + "^{tree}")
        blob = git(self.root, "rev-parse", m + ":code.py")
        git(self.root, "tag", "-a", "-m", "t", "annotated", m)
        tag_object = git(self.root, "rev-parse", "annotated")
        self.assertNotEqual(tag_object, m)
        for bad in (tree, blob):
            with self.subTest(bad=bad[:7]):
                errs = merged_errors(self.root, self.cfg, "p", {**line, "merge": bad})
                self.assertEqual(ids(errs), ["merge.7"])
                self.assertIn("is not a commit in this repository", dict(errs)["merge.7"])
        errs = merged_errors(self.root, self.cfg, "p", {**line, "merge": tag_object})  # a tag object is not the commit
        self.assertEqual(ids(errs), ["merge.7"])
        self.assertIn("is not on the first-parent history of main", dict(errs)["merge.7"])

    def test_merged_git_errors_are_reasons_not_crashes(self):  # a GateError of the history read is a reason; git missing is not
        head, m, line = self.good()
        with mock.patch.object(gitinfo, "rev_list", side_effect=GateError("git rev-list failed (exit 128)")):
            errs = merged_errors(self.root, self.cfg, "p", line)
        self.assertEqual(ids(errs), ["merge.7"])
        self.assertIn("git cannot read the history of main", dict(errs)["merge.7"])
        self.assertIn("update main from the remote", dict(errs)["merge.7"])
        with mock.patch.object(gitinfo, "rev_list", side_effect=GitNotFound("git not found on PATH; install git")):
            with self.assertRaises(GitNotFound):
                merged_errors(self.root, self.cfg, "p", line)
        with mock.patch.object(gitinfo, "parents", side_effect=GateError("git rev-list --parents failed (exit 128)")):
            self.assertEqual(ids(merged_errors(self.root, self.cfg, "p", line)), ["merge.7"])

    def test_merged_base_branch_missing(self):  # MG11, D-A18
        head, m, line = self.good()
        errs = merged_errors(self.root, dict(self.cfg, base_branch="release"), "p", line)
        self.assertEqual(ids(errs), ["merge.7"])
        self.assertIn("release is not a local branch; update release from the remote", dict(errs)["merge.7"])
        bare = os.path.join(self.tmp, "origin.git")
        git(self.tmp, "init", "-q", "--bare", "-b", "main", bare)
        git(self.root, "remote", "add", "origin", bare)
        git(self.root, "push", "-q", "origin", "main")
        git(self.root, "fetch", "-q", "origin")
        git(self.root, "checkout", "-q", "-b", "work")
        git(self.root, "branch", "-q", "-D", "main")
        self.assertEqual(git(self.root, "rev-parse", "origin/main"), m)  # only the remote-tracking branch holds it
        errs = merged_errors(self.root, self.cfg, "p", line)
        self.assertEqual(ids(errs), ["merge.7"])
        self.assertIn("update main from the remote", dict(errs)["merge.7"])

    def test_merged_base_branch_forms(self):  # MG12, D-A23
        head, m, line = self.good()
        git(self.root, "tag", "main", self.A)  # a tag called like the base branch is never read
        self.assertEqual(merged_errors(self.root, self.cfg, "p", line), [])
        r2 = self.new_repo(os.path.join(self.tmp, "rel"), "controller")
        git(r2, "checkout", "-q", "-b", "release/1.x")
        h2, m2 = self.pr("g", {P_LEDGER: "l\n"}, root=r2, base="release/1.x")
        self.assertEqual(merged_errors(r2, dict(self.cfg, base_branch="release/1.x"), "p", self.line(h2, m2)), [])
        self.assertEqual(ids(merged_errors(r2, dict(self.cfg, base_branch="a" * 41), "p", self.line(h2, m2))), ["merge.7"])

    def test_merged_plan_touched_passes(self):  # MG13
        head, m, line = self.good()
        self.assertEqual(ids(merged_errors(self.root, self.cfg, "p", line)), [])

    def test_code_only_pr_fails_plan_check(self):  # MG14, plan :2710
        head, m = self.pr("code", {"code.py": "x\n"})
        errs = merged_errors(self.root, self.cfg, "p", self.line(head, m))
        self.assertEqual(ids(errs), ["plan.7"])

    def test_line_copied_from_another_plan_fails(self):  # MG15, MG16: review 5 F-Pp5-1, review 6 F-Pp6-1
        self.pr("first", {P_LEDGER: "ledger of p\n"})  # main now holds p's ledger
        head, m = self.pr("other", {Q_LEDGER: "ledger of q\n"})  # cut from that main, touches q's workspace only
        self.assertIn("p/ledger.md", git(self.root, "ls-tree", "-r", "--name-only", head))  # its head tree holds p's
        line = self.line(head, m)
        self.assertEqual(ids(merged_errors(self.root, self.cfg, "p", line)), ["plan.7"])
        self.assertEqual(merged_errors(self.root, self.cfg, "q", line), [])

    def test_merged_pr_touching_both_plans_counts_for_both(self):  # MG17
        head, m = self.pr("both", {P_LEDGER: "p\n", Q_LEDGER: "q\n"})
        line = self.line(head, m)
        self.assertEqual(merged_errors(self.root, self.cfg, "p", line), [])
        self.assertEqual(merged_errors(self.root, self.cfg, "q", line), [])

    def test_merged_plan_prefix_boundary(self):  # MG18
        cases = [({PS + "/p-extra/x.md": "x\n"}, False), ({PS + "/P/x.md": "x\n"}, False),
                 ({PS + "/p/a/b/c.md": "x\n"}, True), ({PS + "/p/ledger.md": "x\n"}, True), ({PS + "/p": "a file\n"}, False)]
        for i, (files, ok) in enumerate(cases):
            with self.subTest(files=list(files)):
                r = self.new_repo(os.path.join(self.tmp, "pb%d" % i), "controller")
                head, m = self.pr("b", files, root=r)
                got = merged_errors(r, self.cfg, "p", self.line(head, m))
                self.assertEqual(got, [] if ok else [("plan.7", dict(got).get("plan.7"))])
                self.assertEqual(ids(got), [] if ok else ["plan.7"])

    def test_merged_plan_uses_first_parent_diff(self):  # MG19
        r = self.root
        git(r, "checkout", "-q", "-b", "br", "main")
        self.put("code.py", "x\n")
        head = commit_all(r, "code only")
        git(r, "checkout", "-q", "main")
        self.put(P_LEDGER, "main side\n")
        commit_all(r, "main touches p")  # the first-parent side changed p/, the branch did not
        git(r, "merge", "-q", "--no-ff", "-m", "Merge br", "br")
        m = git(r, "rev-parse", "HEAD")
        self.assertEqual(ids(merged_errors(r, self.cfg, "p", self.line(head, m))), ["plan.7"])

    def test_merged_plan_rename_counts_both_sides(self):  # MG20
        self.put(P_LEDGER, "ledger\n")
        commit_all(self.root, "ledger on main")
        r = self.root
        git(r, "checkout", "-q", "-b", "mv", "main")
        os.makedirs(os.path.join(r, "moved"))
        git(r, "mv", P_LEDGER, "moved/ledger.md")
        head = commit_all(r, "move out")
        git(r, "checkout", "-q", "main")
        git(r, "merge", "-q", "--no-ff", "-m", "Merge mv", "mv")
        m = git(r, "rev-parse", "HEAD")
        self.assertEqual(merged_errors(r, self.cfg, "p", self.line(head, m)), [])

    def test_merged_plan_argument(self):  # MG21
        head, m, line = self.good()
        for bad in ("x/y", "", "p/", "..", "P", "p x", "-p", 5, None, _Sub("p"), b"p"):
            with self.subTest(plan=repr(bad)):
                with self.assertRaises(ValueError):
                    merged_errors(self.root, self.cfg, bad, line)
        self.assertEqual(merged_errors(self.root, self.cfg, "p", line), [])

    def test_merged_approval_must_match_mode(self):  # MG22
        head, m, line = self.good()
        errs = merged_errors(self.root, self.host_cfg, "p", line)  # chat in host mode
        self.assertEqual(ids(errs), ["approval.7"])
        host = {**line, "approval": "host"}
        self.assertEqual(merged_errors(self.root, self.host_cfg, "p", host), [])

    def test_merged_approval_controller_mode_needs_chat(self):  # MG23
        head, m, line = self.good()
        self.assertEqual(ids(merged_errors(self.root, self.cfg, "p", {**line, "approval": "host"})), ["approval.7"])

    def test_chat_approval_must_name_pr_and_head(self):  # MG24, plan :2712, review 5 F-Pp5-2
        head, m, line = self.good()
        for over in ({"approval_head": self.A}, {"approval_pr": 8}, {"approval_head": self.A, "approval_pr": 8}):
            with self.subTest(over=over):
                self.assertEqual(ids(merged_errors(self.root, self.cfg, "p", {**line, **over})), ["approval.7"])

    def test_merged_words_not_judged(self):  # MG25
        head, m, line = self.good()
        for words in ("", "x" * 5000, head, "café Ⱟ", None):
            self.assertEqual(merged_errors(self.root, self.cfg, "p", {**line, "words": words}), [], repr(words)[:20])

    def test_merged_approval_head_exact(self):  # MG26: no prefix matching
        head, m, line = self.good()
        self.assertEqual(ids(merged_errors(self.root, self.cfg, "p", {**line, "approval_head": head[:7]})), ["approval.7"])
        self.assertEqual(ids(merged_errors(self.root, self.cfg, "p", {**line, "approval_head": head.upper()})), ["approval.7"])

    def test_merged_mode_values(self):  # MG27
        head, m, line = self.good()
        host = {**line, "approval": "host"}
        self.assertEqual(merged_errors(self.root, dict(self.cfg, merge={"mode": "controller"}), "p", line), [])
        self.assertEqual(merged_errors(self.root, dict(self.cfg, merge={"mode": "host"}), "p", host), [])
        for bad in ("auto", "", None, "Host"):
            with self.assertRaises(GateError):
                merged_errors(self.root, dict(self.cfg, merge={"mode": bad}), "p", line)
        r2 = self.new_repo(os.path.join(self.tmp, "nomode"), None)  # the default is host
        self.assertEqual(config.load(r2)["merge"], {"mode": "host"})
        h2, m2 = self.pr("d", {P_LEDGER: "l\n"}, root=r2)
        self.assertEqual(merged_errors(r2, config.load(r2), "p", self.line(h2, m2, approval="host")), [])
        self.assertEqual(ids(merged_errors(r2, config.load(r2), "p", self.line(h2, m2))), ["approval.7"])

    def test_merged_multiple_failures_order(self):  # MG28: merge, head, plan, approval; a failing merge stops head and plan
        head, m = self.pr("code", {"code.py": "x\n"})
        line = self.line(self.A, m, approval="host")
        self.assertEqual(ids(merged_errors(self.root, self.cfg, "p", line)), ["head.7", "plan.7", "approval.7"])
        bad = {**line, "merge": ABSENT40}
        self.assertEqual(ids(merged_errors(self.root, self.cfg, "p", bad)), ["merge.7", "approval.7"])

    def test_merged_line_types(self):  # MG29
        head, m, line = self.good()
        for bad in (None, [], "x", 5):
            with self.assertRaises(ValueError):
                merged_errors(self.root, self.cfg, "p", bad)
        for key in ("pr", "head", "merge", "approval"):
            with self.subTest(missing=key):
                with self.assertRaises(ValueError):
                    merged_errors(self.root, self.cfg, "p", {k: v for k, v in line.items() if k != key})
        for key, values in (("pr", ("7", True, 0, -1, 7.0, None, 10 ** 600, 10 ** 4300)),
                            ("head", (head[:39], head.upper(), _Sub(head), None, 5, head + "0")),
                            ("merge", (m[:39], m.upper(), _Sub(m), None, 5)),
                            ("approval", ("auto", "", None, 5, _Sub("chat"))),
                            ("approval_pr", ("7", True, 0, None, 10 ** 4300)), ("approval_head", (None, 5, b"x"))):
            for value in values:
                with self.subTest(key=key, kind=type(value).__name__, bits=getattr(value, "bit_length", lambda: 0)()):
                    with self.assertRaises(ValueError) as cm:
                        merged_errors(self.root, self.cfg, "p", {**line, key: value})
                    self.assertLess(len(str(cm.exception)), 200)  # a 4301-digit pr is never written out
        for limit in INT_LIMITS:
            with int_limit(limit):
                big = {**line, "pr": 10 ** 599, "approval_pr": 10 ** 599}  # the largest accepted: 600 digits
                self.assertEqual(merged_errors(self.root, self.cfg, "p", big), [])
                errs = merged_errors(self.root, self.cfg, "p", {**big, "approval": "host"})
                self.assertEqual(ids(errs), ["approval." + "1" + "0" * 599])
        # a chat line of the host kind keeps approval_pr and approval_head unread
        self.assertEqual(merged_errors(self.root, self.host_cfg, "p", {k: v for k, v in {**line, "approval": "host"}.items()
                                                                       if not k.startswith("approval_")}), [])

    def test_merged_suffix_form(self):  # MG30
        head, m = self.pr("code", {"code.py": "x\n"})
        line = self.line(self.A, m, approval="host", pr=12345)
        errs = merged_errors(self.root, self.cfg, "p", line)
        self.assertEqual([s for s, _ in errs], ["head.12345", "plan.12345", "approval.12345"])
        self.assertTrue(all(type(s) is str and type(r) is str and r for s, r in errs))
        self.assertIs(type(errs), list)

    def test_merged_errors_git_states(self):  # MG31
        head, m, line = self.good()
        git(self.root, "checkout", "-q", "--detach")
        self.assertEqual(merged_errors(self.root, self.cfg, "p", line), [])  # detached HEAD
        git(self.root, "checkout", "-q", "main")
        git(self.root, "replace", m, self.A)  # a replace ref cannot change the verdict (D-A16)
        self.assertEqual(merged_errors(self.root, self.cfg, "p", line), [])
        fresh = os.path.join(self.tmp, "unborn")
        os.mkdir(fresh)
        git(fresh, "init", "-q", "-b", "main")
        self.assertEqual(ids(merged_errors(fresh, self.cfg, "p", line)), ["merge.7"])  # unborn: no local branch
        shallow = os.path.join(self.tmp, "shallow")
        git(self.tmp, "clone", "-q", "--depth", "1", "file://" + self.root, shallow)
        errs = merged_errors(shallow, self.cfg, "p", line)
        self.assertEqual(ids(errs), ["merge.7"])
        self.assertIn("update main from the remote", dict(errs)["merge.7"])

    def test_merged_errors_mid_merge(self):  # MG31
        head, m, line = self.good()
        r = self.root
        git(r, "checkout", "-q", "-b", "c1")
        self.put("f", "1\n")
        commit_all(r, "c1")
        git(r, "checkout", "-q", "main")
        self.put("f", "2\n")
        commit_all(r, "m2")
        git(r, "merge", "-q", "c1", check=False)
        self.assertTrue(os.path.exists(os.path.join(r, ".git", "MERGE_HEAD")))
        self.assertEqual(merged_errors(r, self.cfg, "p", line), [])

    def test_merged_after_base_advanced(self):  # MG32
        head, m, line = self.good()
        for i in range(3):
            self.put("later%d.txt" % i)
            commit_all(self.root, "later %d" % i)
        self.assertEqual(merged_errors(self.root, self.cfg, "p", line), [])

    def test_merged_reverse_merge_limit(self):  # MG33, D-A17 (Q-A17c): a stated limit, not a defect
        r = self.root
        git(r, "checkout", "-q", "-b", "topic", "main")
        self.put("code.py", "x\n")
        commit_all(r, "topic work")
        git(r, "checkout", "-q", "main")
        self.put(P_LEDGER, "ledger\n")
        old_main = commit_all(r, "main moves")
        git(r, "checkout", "-q", "topic")
        git(r, "merge", "-q", "--no-ff", "-m", "main into topic", "main")
        reverse = git(r, "rev-parse", "HEAD")
        git(r, "checkout", "-q", "main")
        git(r, "merge", "-q", "--ff-only", "topic")
        self.assertEqual(git(r, "rev-parse", reverse + "^2"), old_main)
        self.assertEqual(merged_errors(r, self.cfg, "p", self.line(old_main, reverse)), [])

    def test_merged_errors_root_and_cfg(self):  # MG34
        head, m, line = self.good()
        os.makedirs(os.path.join(self.root, "sub"))
        for bad in ("sub", os.path.join(self.root, "nosuch")):
            with self.assertRaises(GateError):
                merged_errors(bad, self.cfg, "p", line)
        for bad in (None, b".", 5, "", _Sub(self.root)):
            with self.assertRaises(GateError) as cm:
                merged_errors(bad, self.cfg, "p", line)
            self.assertEqual(str(cm.exception), "root must be a string")
        for key in ("base_branch", "merge", "paths"):
            with self.subTest(drop=key):
                with self.assertRaises(GateError) as cm:
                    merged_errors(self.root, {k: v for k, v in self.cfg.items() if k != key}, "p", line)
                self.assertIn("cfg: ", str(cm.exception))
        with self.assertRaises(GateError):
            merged_errors(self.root, dict(self.cfg, paths={}), "p", line)
        with self.assertRaises(GateError):
            merged_errors(self.root, dict(self.cfg, base_branch=""), "p", line)
        with self.assertRaises(GateError):
            merged_errors(self.root, None, "p", line)

    def test_merged_each_line_alone(self):  # MG36
        head, m, line = self.good()
        twin = {**line, "pr": 8, "approval_pr": 8}
        self.assertEqual(merged_errors(self.root, self.cfg, "p", line), [])
        self.assertEqual(merged_errors(self.root, self.cfg, "p", twin), [])


class ModuleShape(unittest.TestCase):
    def source(self, rel):
        with open(os.path.join(REPO, rel), encoding="utf-8") as fh:
            return fh.read()

    def test_merge_module_shape(self):  # MG35, MD10: Task P3.1 adds MODES and agent_may_merge (edited on purpose)
        tree = ast.parse(self.source("gates/lib/merge.py"))
        public = []
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                public.append(node.name)
            elif isinstance(node, ast.Assign):
                public += [t.id for t in node.targets if isinstance(t, ast.Name)]
        self.assertEqual([n for n in public if not n.startswith("_")], ["MODES", "agent_may_merge", "merged_errors"])

    def test_merge_module_reads_no_unicode_property(self):  # V2
        tree = ast.parse(self.source("gates/lib/merge.py"))
        banned = {"lower", "upper", "casefold", "isprintable", "isspace", "isalnum", "isdigit", "isalpha", "isdecimal",
                  "isnumeric", "title", "capitalize", "swapcase"}
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = [a.name for a in node.names] + [getattr(node, "module", None) or ""]
                self.assertNotIn("unicodedata", " ".join(names))
            if isinstance(node, ast.Attribute):
                self.assertNotIn(node.attr, banned)
            if isinstance(node, ast.keyword):
                self.assertNotEqual(node.arg, "flags")
            if isinstance(node, ast.Attribute) and node.attr in ("IGNORECASE", "I"):
                self.fail("re.IGNORECASE")

    def test_part_i_no_exception_groups(self):  # V3: no except* and no ExceptionGroup name (3.9 has none)
        for rel in ("gates/lib/merge.py", "gates/lib/gitinfo.py"):
            tree = ast.parse(self.source(rel))
            for node in ast.walk(tree):
                self.assertNotEqual(type(node).__name__, "TryStar", rel)
                if isinstance(node, ast.Name):
                    self.assertNotIn(node.id, ("ExceptionGroup", "BaseExceptionGroup"), rel)


class _SubDict(dict):
    pass


class AgentMayMergeTests(GitIsolatedTestCase):
    """Task P3.1 producer 1: ``MODES`` and ``agent_may_merge`` (rows MD1-MD11, decision D-Q1 (b): an exception for a
    malformed cfg, the bool only for a valid one)."""

    def repo(self, name, mode):
        path = os.path.join(self.work, name)
        os.makedirs(path)
        cfg = minimal_config()
        if mode is not None:
            cfg["merge"] = {"mode": mode}
        return make_repo(path, cfg)

    def source(self, rel):
        with open(os.path.join(REPO, rel), encoding="utf-8") as fh:
            return fh.read()

    def test_modes_literal(self):  # MD1
        self.assertIs(type(MODES), tuple)
        self.assertEqual(MODES, ("host", "controller"))

    def test_modes_equal_config_modes(self):  # MD2
        for m in MODES:
            with self.subTest(mode=m):
                self.assertEqual(config.load(self.repo("r-" + m, m))["merge"]["mode"], m)
        with self.assertRaises(GateError):
            config.load(self.repo("r-auto", "auto"))
        tree = ast.parse(self.source("gates/lib/config.py"))
        literals = [tuple(e.value for e in n.elts) for n in ast.walk(tree)
                    if isinstance(n, ast.Tuple) and n.elts and all(isinstance(e, ast.Constant) for e in n.elts)]
        self.assertIn(("host", "controller"), literals)  # the validator's literal is the same set as MODES

    def test_merge_modes_single_literal(self):  # MD3
        tree = ast.parse(self.source("gates/lib/merge.py"))
        tuples = [tuple(e.value for e in n.elts) for n in ast.walk(tree)
                  if isinstance(n, ast.Tuple) and n.elts and all(isinstance(e, ast.Constant) for e in n.elts)]
        self.assertEqual(tuples.count(("host", "controller")), 1)
        self.assertNotIn("_MODES", [n.id for n in ast.walk(tree) if isinstance(n, ast.Name)])
        self.assertIn("MODES", [n.id for n in ast.walk(tree) if isinstance(n, ast.Name)])

    def test_default_mode_is_host(self):  # MD4, MD-plan :2940
        absent = config.load(self.repo("absent", None))
        host = config.load(self.repo("host", "host"))
        controller = config.load(self.repo("controller", "controller"))
        self.assertIs(agent_may_merge(absent), False)
        self.assertIs(agent_may_merge(host), False)
        self.assertIs(agent_may_merge(controller), True)

    def test_agent_may_merge_bare_dict(self):  # MD5
        self.assertIs(agent_may_merge({"merge": {"mode": "controller"}}), True)
        self.assertIs(agent_may_merge({"merge": {"mode": "host"}}), False)

    def test_agent_may_merge_exact_compare(self):  # MD6, D-Q1: a mode off the enum raises, never True
        for bad in ("Controller", "controller ", "CONTROLLER", "auto", "", "contrôller", "Ⱟ"):
            with self.subTest(mode=bad):
                with self.assertRaises(GateError):
                    agent_may_merge({"merge": {"mode": bad}})

    def test_agent_may_merge_mode_types(self):  # MD7
        class S(str):
            pass
        for bad in (None, 1, True, ["controller"], {"a": 1}, S("controller")):
            with self.subTest(mode=repr(bad)):
                with self.assertRaises(GateError):
                    agent_may_merge({"merge": {"mode": bad}})

    def test_agent_may_merge_cfg_shapes(self):  # MD8
        good = {"merge": {"mode": "controller"}}
        for bad in (None, [], "controller", {}, {"merge": None}, {"merge": "controller"}, {"merge": {}},
                    {"merge": []}, _SubDict(good), {"merge": _SubDict(mode="controller")}):
            with self.subTest(cfg=repr(bad)):
                with self.assertRaises(GateError):
                    agent_may_merge(bad)

    def test_agent_may_merge_pure(self):  # MD9
        import copy
        cfg = {"merge": {"mode": "controller"}, "other": [1, {"a": 2}]}
        before = copy.deepcopy(cfg)
        with mock.patch("builtins.open", side_effect=AssertionError("open")), \
                mock.patch("subprocess.run", side_effect=AssertionError("subprocess")), \
                mock.patch("subprocess.Popen", side_effect=AssertionError("popen")):
            self.assertIs(agent_may_merge(cfg), True)
        self.assertEqual(cfg, before)

    def test_p31_digit_limits_same_on_both(self):  # V1: P3.1 adds no int() of text in the three files it touches
        expect = {"gates/lib/merge.py": 0, "gates/tools/githooks.py": 0, "gates/gate_checkpoint.py": 2}
        for rel, count in expect.items():
            tree = ast.parse(self.source(rel))
            calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                     and n.func.id == "int"]
            self.assertEqual(len(calls), count, rel)  # gate_checkpoint's two are _reads, on validated line ranges

    def test_p31_no_exception_groups(self):  # V3
        for rel in ("gates/lib/merge.py", "gates/gate_checkpoint.py", "gates/tools/githooks.py"):
            for node in ast.walk(ast.parse(self.source(rel))):
                self.assertNotEqual(type(node).__name__, "TryStar", rel)
                if isinstance(node, ast.Name):
                    self.assertNotIn(node.id, ("ExceptionGroup", "BaseExceptionGroup"), rel)

    def test_p31_unicode_same_on_both(self):  # V2: no case or property method; U+0870 and U+2C2F are plain bytes
        for odd in ("ࡰ", "Ⱟ", "\U0001fae8"):
            with self.subTest(odd=odd):
                with self.assertRaises(GateError):
                    agent_may_merge({"merge": {"mode": odd}})
                self.assertIs(agent_may_merge({"merge": {"mode": "controller"}, "base_branch": "ma%sn" % odd}), True)


if __name__ == "__main__":
    unittest.main()
