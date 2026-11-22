"""Tests of gates/lib/cleanup.py (Task P3.2; rows PL, FM, PE, PR, CD, V of the P3.2 input-domain table; decisions D-Q6 to
D-Q13). Every repository is a ``make_repo`` fixture with its own ``main``, ``merge.mode: controller`` and a git config
that sets ``color.ui=always``, ``color.diff=always`` and ``core.abbrev=7``. Merges are real ``--no-ff`` merges; the
expected values are written by hand."""
import ast
import os
import re
import time
import unittest

from gates.lib import cleanup, config, gitinfo
from gates.lib.cleanup import cited_decisions, final_merge, plan_effort, plan_ledger, program_effort
from gates.lib.result import GateError
from gates.lib.yamlsub import emit
from tests.helpers import (INT_LIMITS, TOP, GitIsolatedTestCase, check_root_forms, commit_all, git, int_limit,
                           make_repo, minimal_config, root_forms)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PS = ".strict-delivery/state/plans"
PG = "docs/strict-delivery/plans"
SPECS = "docs/strict-delivery/specs"
REV = "docs/strict-delivery/reviews"
CL = ".strict-delivery/state/claims"
FD = ".strict-delivery/state/findings"
PROGRAMS = ".strict-delivery/state/programs"
LEDGER = PS + "/p/ledger.md"
LEDGER_HEAD = "<!-- schema: ledger/1 -->\n"
NAME = "20261101-x"
D1 = "DEC-20261031-k3f9"
D2 = "DEC-20261031-m4n5"
ABSENT40 = "89abcdef0123456789abcdef0123456789abcdef"


class _Sub(str):
    pass


def mline(head, merge, final="yes", pr=12, approval="chat", extra=""):
    if approval == "host":
        return ("MERGED pr=%d head=%s merge=%s merged_by=u at=2026-11-02T06:23:42Z final=%s%s approval=host"
                % (pr, head, merge, final, extra))
    return ("MERGED pr=%d head=%s merge=%s merged_by=u at=2026-11-02T06:23:42Z final=%s%s approval=chat pr=%d head=%s "
            "words=approve PR %d" % (pr, head, merge, final, extra, pr, head, pr))


class Cx(GitIsolatedTestCase):
    def setUp(self):
        super().setUp()
        self.root = self.new_repo(self.work)
        self.cfg = config.load(self.root)
        self.A = git(self.root, "rev-parse", "HEAD")

    def new_repo(self, path, mode="controller"):
        os.makedirs(path, exist_ok=True)
        cfg = minimal_config()
        cfg["merge"] = {"mode": mode}
        root = make_repo(path, cfg)
        for k, v in (("color.ui", "always"), ("color.diff", "always"), ("core.abbrev", "7")):
            git(root, "config", k, v)
        return root

    def put(self, rel, text="x\n", root=None):
        path = os.path.join(root or self.root, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(text if type(text) is bytes else text.encode("utf-8"))

    def pr(self, name, files, how="no-ff", base="main"):
        r = self.root
        git(r, "checkout", "-q", "-b", name, base)
        for rel, text in files.items():
            self.put(rel, text)
        head = commit_all(r, "work " + name)
        git(r, "checkout", "-q", base)
        if how == "no-ff":
            git(r, "merge", "-q", "--no-ff", "-m", "Merge " + name, name)
        elif how == "squash":
            git(r, "merge", "-q", "--squash", name)
            git(r, "commit", "-q", "-m", "squash " + name)
        elif how == "ff":
            git(r, "merge", "-q", "--ff-only", name)
        return head, git(r, "rev-parse", "HEAD")

    def set_ledger(self, *lines, plan="p"):
        self.put("%s/%s/ledger.md" % (PS, plan), LEDGER_HEAD + "".join(l + "\n" for l in lines))
        return commit_all(self.root, "ledger " + plan)

    def scenario(self, plan="p", tag="s", fid="F-20261031-k3f9", final=True, spec_also=(), extra=None):
        """One plan's whole effort merged by one pull request; returns a dict of the paths and shas."""
        spec = "%s/%s.md" % (SPECS, tag)
        kept = "docs/%s-kept.md" % tag
        claim = "%s/%s.yml" % (CL, spec[:-3].replace("/", "--"))
        kclaim = "%s/%s.yml" % (CL, kept[:-3].replace("/", "--"))
        other = "F-20261031-m4n5" if fid != "F-20261031-m4n5" else "F-20261031-p6q7"
        openf = "F-20261031-r8s9" if fid != "F-20261031-r8s9" else "F-20261031-t2u3"
        ho = {"schema": "handoff/1", "plan": plan, "spec": [spec] + list(spec_also)}
        crow = lambda doc: emit({"schema": "claim/1", "document": doc, "claims": []})
        frow = lambda i, st, by: emit({"schema": "finding/1", "id": i, "status": st, "resolved_by": by})
        files = {
            "%s/%s.md" % (PG, plan): "plan\n", "%s/%s/ledger.md" % (PS, plan): LEDGER_HEAD,
            "%s/%s/handoff.md" % (PS, plan): "---\n" + emit(ho) + "---\nbody\n",
            "%s/%s/r.md" % (REV, plan): "review\n", spec: "spec\n", kept: "kept\n",
            claim: crow(spec), kclaim: crow(kept),
            "%s/%s.yml" % (FD, fid): frow(fid, "closed", plan),
            "%s/%s.yml" % (FD, other): frow(other, "closed", "other"),
            "%s/%s.yml" % (FD, openf): emit({"schema": "finding/1", "id": openf, "status": "open",
                                             "owner": {"kind": "plan", "plan": plan, "task": "1"}}),
        }
        for k, v in (extra or {}).items():
            files[k] = v
        head, merge = self.pr("t-" + plan, files)
        if final:
            self.set_ledger(mline(head, merge), plan=plan)
        return {"head": head, "merge": merge, "spec": spec, "kept": kept, "claim": claim, "kclaim": kclaim,
                "fid": fid, "other": other, "openf": openf, "plan": plan,
                "set": {"%s/%s.md" % (PG, plan), "%s/%s/ledger.md" % (PS, plan), "%s/%s/handoff.md" % (PS, plan),
                        "%s/%s/r.md" % (REV, plan), spec, claim, "%s/%s.yml" % (FD, fid)}}


class LedgerTests(Cx):
    def test_plan_ledger_present(self):  # PL1
        s = self.scenario()
        self.assertEqual(plan_ledger(self.root, self.cfg, "p"), LEDGER_HEAD + mline(s["head"], s["merge"]) + "\n")

    def test_ledger_read_from_before_its_deletion(self):  # PL2, plan test
        s = self.scenario()
        git(self.root, "checkout", "-q", "-b", "cleanup/p")
        git(self.root, "rm", "-q", "-f", "--", LEDGER)
        commit_all(self.root, "cleanup")
        self.assertFalse(os.path.exists(os.path.join(self.root, LEDGER)))
        self.assertIn("MERGED pr=12", plan_ledger(self.root, self.cfg, "p"))

    def test_plan_ledger_never_existed(self):  # PL3
        self.assertIsNone(plan_ledger(self.root, self.cfg, "p"))

    def test_plan_ledger_working_tree_precedence(self):  # PL4, D-Q6 (a)
        self.set_ledger("committed")
        self.put(LEDGER, LEDGER_HEAD + "edited\n")
        self.assertEqual(plan_ledger(self.root, self.cfg, "p"), LEDGER_HEAD + "edited\n")  # uncommitted edit wins
        git(self.root, "checkout", "--", LEDGER)
        git(self.root, "rm", "-q", "-f", "--", LEDGER)  # staged deletion: file gone from the tree, present at HEAD
        self.assertEqual(plan_ledger(self.root, self.cfg, "p"), LEDGER_HEAD + "committed\n")
        git(self.root, "reset", "-q", "--hard")
        self.put("%s/q/ledger.md" % PS, "untracked\n")  # untracked, never in history
        self.assertEqual(plan_ledger(self.root, self.cfg, "q"), "untracked\n")
        # a symlink or a directory in the working tree is refused
        os.remove(os.path.join(self.root, LEDGER))
        os.symlink("elsewhere", os.path.join(self.root, LEDGER))
        with self.assertRaises(GateError) as cm:
            plan_ledger(self.root, self.cfg, "p")
        self.assertEqual(str(cm.exception), LEDGER + ": is not a regular file")

    def test_plan_ledger_plan_forms(self):  # PL5
        for bad in ("P", "a/b", "..", "a b", "", None, 5, _Sub("p"), "a" * 0 + "-x", "p\n", "p\0", "café", "a\nb"):
            with self.subTest(repr(bad)):
                with self.assertRaises(ValueError) as cm:
                    plan_ledger(self.root, self.cfg, bad)
                self.assertEqual(str(cm.exception), "plan_ledger: plan must be a plan slug of a-z, 0-9 and '-'")
        self.assertIsNone(plan_ledger(self.root, self.cfg, "a" * 255))

    def test_plan_ledger_cfg_forms(self):  # PL6
        for cfg, msg in (({}, "cfg: paths.plan_state is missing"), ({"paths": {}}, "cfg: paths.plan_state is missing"),
                         ({"paths": {"plan_state": 5}}, "cfg: paths.plan_state must be a non-empty string"),
                         ({"paths": {"plan_state": ""}}, "cfg: paths.plan_state must be a non-empty string")):
            with self.subTest(msg):
                with self.assertRaises(GateError) as cm:
                    plan_ledger(self.root, cfg, "p")
                self.assertEqual(str(cm.exception), msg)

    def test_plan_ledger_file_kinds(self):  # PL7
        self.put(LEDGER, b"\xff\xfe bad\n")
        with self.assertRaises(GateError) as cm:
            plan_ledger(self.root, self.cfg, "p")
        self.assertEqual(str(cm.exception), LEDGER + ": not valid UTF-8")
        self.put(LEDGER, "﻿" + LEDGER_HEAD.rstrip("\n") + "\r\n")
        self.assertEqual(plan_ledger(self.root, self.cfg, "p"), "﻿" + LEDGER_HEAD.rstrip("\n") + "\r\n")
        os.remove(os.path.join(self.root, LEDGER))
        os.makedirs(os.path.join(self.root, LEDGER))
        with self.assertRaises(GateError):
            plan_ledger(self.root, self.cfg, "p")

    def test_plan_ledger_root_forms(self):  # PL8
        check_root_forms(self, root_forms(self.tmp, self.root), {"plan_ledger": lambda r: plan_ledger(r, self.cfg, "p")})
        for bad in (None, "", _Sub(self.root)):
            with self.assertRaises(GateError) as cm:
                plan_ledger(bad, self.cfg, "p")
            self.assertEqual(str(cm.exception), "root must be a string")


class FinalMergeTests(Cx):
    def prep(self):
        head, merge = self.pr("t", {"%s/p/handoff.md" % PS: "h\n"})
        return head, merge

    def test_final_merge_no_merged_line(self):  # FM1
        self.set_ledger("CHECKPOINT 1a 1 head=abcdef1 tests=1/1 gates=PASS next=2")
        self.assertIsNone(final_merge(self.root, self.cfg, "p"))

    def test_plan_not_merged_until_final_line(self):  # FM2, FM4, plan test (D-Q7: pr is an int)
        head, merge = self.prep()
        self.set_ledger(mline(head, merge, "no", 11), mline(head, merge, "no", 13))
        self.assertIsNone(final_merge(self.root, self.cfg, "p"))
        self.set_ledger(mline(head, merge, "no", 11), mline(head, merge, "yes", 12))
        got = final_merge(self.root, self.cfg, "p")
        self.assertEqual(got["pr"], 12)
        self.assertIs(type(got["pr"]), int)
        self.assertEqual((got["head"], got["merge"], got["final"], got["approval"]), (head, merge, "yes", "chat"))

    def test_final_merge_line_failing_merged_errors(self):  # FM3
        head, merge = self.prep()
        other_head, other_merge = self.pr("o", {"%s/q/handoff.md" % PS: "h\n"})
        sq_head, sq = self.pr("sq", {"%s/p/x.md" % PS: "h\n"}, how="squash")
        cases = {
            "merge: not a commit": mline(head, ABSENT40),
            "merge: not a merge commit": mline(head, self.A),
            "merge: squash": mline(sq_head, sq),
            "head": mline(self.A, merge),
            "plan: merge of another plan": mline(other_head, other_merge),
            "approval: host line in controller mode": mline(head, merge, approval="host"),
            "approval: chat line naming another head": mline(head, merge).replace(
                "approval=chat pr=12 head=" + head, "approval=chat pr=12 head=" + self.A),
        }
        for name, line in cases.items():
            with self.subTest(name):
                self.set_ledger(line)
                self.assertIsNone(final_merge(self.root, self.cfg, "p"))
        self.set_ledger(mline(head, merge))
        self.assertIsNotNone(final_merge(self.root, self.cfg, "p"))

    def test_final_merge_after_ledger_deleted(self):  # FM5
        head, merge = self.prep()
        self.set_ledger(mline(head, merge))
        git(self.root, "checkout", "-q", "-b", "cleanup/p")
        git(self.root, "rm", "-q", "-f", "--", LEDGER)
        commit_all(self.root, "cleanup")
        self.assertEqual(final_merge(self.root, self.cfg, "p")["merge"], merge)

    def test_final_merge_never_existed(self):  # FM6
        self.assertIsNone(final_merge(self.root, self.cfg, "p"))

    def test_final_merge_two_final_lines(self):  # FM7, D-Q8 (a)
        head, merge = self.prep()
        bad = mline(head, ABSENT40, pr=5)
        good1, good2 = mline(head, merge, pr=6), mline(head, merge, pr=7)
        for lines, want in (((bad, good1), 6), ((good1, good2), 6), ((good2, good1), 7), ((good1, bad), 6),
                            ((bad, mline(head, ABSENT40, pr=8)), None)):
            with self.subTest(want=want):
                self.set_ledger(*lines)
                got = final_merge(self.root, self.cfg, "p")
                self.assertEqual(None if got is None else got["pr"], want)

    def test_final_merge_skips_nonconforming_lines(self):  # FM8
        head, merge = self.prep()
        self.set_ledger("MERGED PR-1c0 (#4): prose of the old shape",
                        "MERGED pr=1 head=7aeb5d4 merge=%s merged_by=u at=2026-11-02T06:23:42Z final=yes approval=host" % merge,
                        mline(head, merge))
        self.assertEqual(final_merge(self.root, self.cfg, "p")["pr"], 12)

    def test_final_merge_stream_line(self):  # FM9
        head, merge = self.prep()
        self.set_ledger(mline(head, merge, extra=" stream=a block=3"))
        got = final_merge(self.root, self.cfg, "p")
        self.assertEqual((got["stream"], got["block"]), ("a", "3"))

    def test_final_merge_base_branch_forms(self):  # FM10
        head, merge = self.prep()
        self.set_ledger(mline(head, merge))
        git(self.root, "branch", "trunk", "main")
        self.assertIsNotNone(final_merge(self.root, dict(self.cfg, base_branch="trunk"), "p"))
        self.assertIsNone(final_merge(self.root, dict(self.cfg, base_branch="nonesuch"), "p"))
        git(self.root, "branch", "-m", "main", "other")  # no local main
        self.assertIsNone(final_merge(self.root, self.cfg, "p"))
        self.assertIsNotNone(final_merge(self.root, dict(self.cfg, base_branch="other"), "p"))

    def test_final_merge_git_states(self):  # FM11
        head, merge = self.prep()
        sq_head, sq = self.pr("sq", {"%s/p/x.md" % PS: "h\n"}, how="squash")
        rb_head, rb = self.pr("rb", {"%s/p/y.md" % PS: "h\n"}, how="ff")
        for name, line in (("squash", mline(sq_head, sq)), ("fast-forward", mline(rb_head, rb))):
            with self.subTest(name):
                self.set_ledger(line)
                self.assertIsNone(final_merge(self.root, self.cfg, "p"))
        self.set_ledger(mline(head, merge))
        git(self.root, "checkout", "-q", "--detach", "HEAD")
        self.assertIsNotNone(final_merge(self.root, self.cfg, "p"))  # judged by base_branch, not HEAD
        git(self.root, "checkout", "-q", "main")
        shallow = os.path.join(self.tmp, "shallow")
        git(self.tmp, "clone", "-q", "--depth", "1", "file://" + self.root, shallow)
        self.assertIsNone(final_merge(shallow, config.load(shallow), "p"))  # the merge commit is cut off
        unborn = os.path.join(self.tmp, "unborn")
        os.mkdir(unborn)
        git(unborn, "init", "-q", "-b", "main")
        with self.assertRaises(GateError):
            final_merge(unborn, self.cfg, "p")

    def test_final_merge_argument_forms(self):  # FM12
        for bad in ("P", "a/b", "", None, 5, _Sub("p")):
            with self.assertRaises(ValueError):
                final_merge(self.root, self.cfg, bad)
        bad_cfg = {"base_branch": "main", "paths": self.cfg["paths"]}
        self.set_ledger("x")
        self.put(LEDGER, LEDGER_HEAD + mline(self.A, self.A) + "\n")
        for cfg in (bad_cfg, dict(self.cfg, merge={}), dict(self.cfg, merge={"mode": "x"})):
            with self.assertRaises(GateError):
                final_merge(self.root, cfg, "p")

    def test_final_merge_digit_limits(self):  # FM13, V1: 600 digits conform; 601, 4300, 4301 are skipped, no ValueError
        head, merge = self.prep()
        for limit in INT_LIMITS:
            with int_limit(limit):
                for digits, found in ((600, True), (601, False), (4300, False), (4301, False)):
                    with self.subTest(limit=limit, digits=digits):
                        n = int("9" * min(digits, 600))
                        text = mline(head, merge, pr=n) if digits == 600 else mline(head, merge).replace(
                            "pr=12", "pr=" + "9" * digits)
                        self.set_ledger(text)
                        got = final_merge(self.root, self.cfg, "p")
                        self.assertEqual(got is not None, found)

    def test_final_merge_line_whitespace(self):  # FM15
        head, merge = self.prep()
        for name, line in (("CR", mline(head, merge) + "\r"), ("trailing space after words ok", None),
                           ("tab", mline(head, merge).replace(" merged_by", "\tmerged_by"))):
            if line is None:
                continue
            with self.subTest(name):
                self.set_ledger(line)
                self.assertIsNone(final_merge(self.root, self.cfg, "p"))

    def test_git_reads_ignore_colour_and_abbrev_config(self):  # FM14: the fixture sets all three; a plain clone agrees
        head, merge = self.prep()
        self.set_ledger(mline(head, merge))
        plain = os.path.join(self.tmp, "plainclone")
        git(self.tmp, "clone", "-q", self.root, plain)
        for k in ("color.ui", "color.diff", "core.abbrev"):
            self.assertNotEqual(git(self.root, "config", k), "")
            self.assertEqual(git(plain, "config", "--get", k, check=False), "")
        self.assertEqual(final_merge(plain, config.load(plain), "p"), final_merge(self.root, self.cfg, "p"))


class PlanEffortTests(Cx):
    def test_plan_effort_lists_per_effort_paths(self):  # PE1, PE20 (the fixture sets colour and abbrev)
        s = self.scenario()
        self.assertEqual(set(plan_effort(self.root, self.cfg, "p", s["merge"])), s["set"])
        self.assertNotIn(s["kept"], s["set"])

    def test_plan_effort_plan_file_absent(self):  # PE2
        s = self.scenario(plan="p")
        git(self.root, "rm", "-q", "-f", "--", "%s/p.md" % PG)
        at = commit_all(self.root, "no plan file")
        self.assertEqual(set(plan_effort(self.root, self.cfg, "p", at)), s["set"] - {"%s/p.md" % PG})

    def test_plan_effort_handoff_absent(self):  # PE3
        s = self.scenario()
        git(self.root, "rm", "-q", "-f", "--", "%s/p/handoff.md" % PS)
        at = commit_all(self.root, "no handoff")
        want = s["set"] - {"%s/p/handoff.md" % PS, s["spec"], s["claim"]}
        self.assertEqual(set(plan_effort(self.root, self.cfg, "p", at)), want)

    def handoff(self, text):
        self.put("%s/p/handoff.md" % PS, text)
        return commit_all(self.root, "handoff")

    def test_plan_effort_handoff_spec_forms(self):  # PE4, D-Q11
        s = self.scenario()
        spec = s["spec"]
        fm = lambda spec_value: "---\n" + emit({"schema": "handoff/1", "plan": "p", "spec": spec_value}) + "---\n"
        ok = {"two specs": ([spec, s["kept"].replace("docs/", SPECS + "/")], None), "duplicate": ([spec, spec], None)}
        self.put(SPECS + "/second.md")
        commit_all(self.root, "second")
        at = self.handoff(fm([spec, SPECS + "/second.md"]))
        self.assertTrue({spec, SPECS + "/second.md"} <= set(plan_effort(self.root, self.cfg, "p", at)))
        at = self.handoff(fm([spec, spec]))
        got = plan_effort(self.root, self.cfg, "p", at)
        self.assertEqual(len(got), len(set(got)))
        bad = {"missing spec": "---\n" + emit({"schema": "handoff/1", "plan": "p"}) + "---\n",
               "str": fm("x"), "empty list": fm([]), "int item": fm([5]), "not under specs": fm(["docs/other.md"]),
               "absent at at": fm([SPECS + "/nope.md"]), "dotdot": fm([SPECS + "/../x.md"]), "absolute": fm(["/etc/x"]),
               "no closer": "---\nspec: []\n", "BOM": "﻿---\nspec: []\n---\n", "not a mapping": "---\n- a\n---\n"}
        for name, text in bad.items():
            with self.subTest(name):
                at = self.handoff(text)
                with self.assertRaises(GateError) as cm:
                    plan_effort(self.root, self.cfg, "p", at)
                self.assertIn("%s/p/handoff.md" % PS, str(cm.exception))
        del ok

    def test_shared_spec_kept(self):  # PE5, controller ruling "shared specs"
        s = self.scenario(plan="p", tag="shared")
        t = self.scenario(plan="q", tag="qonly", fid="F-20261031-yyyy".replace("y", "w"), spec_also=[s["spec"]])
        got = set(plan_effort(self.root, self.cfg, "p", s["merge"]))
        self.assertNotIn(s["spec"], got)
        self.assertNotIn(s["claim"], got)  # the claim follows its document
        self.assertIn("%s/p.md" % PG, got)
        got_q = set(plan_effort(self.root, self.cfg, "q", t["merge"]))
        self.assertIn(t["spec"], got_q)
        self.assertNotIn(s["spec"], got_q)

    def test_plan_effort_other_handoff_forms(self):  # PE6
        s = self.scenario()
        def other(text, branch_only=False):
            if branch_only:
                git(self.root, "checkout", "-q", "-b", "feat")
            self.put("%s/zz/handoff.md" % PS, text)
            commit_all(self.root, "other handoff")
            if branch_only:
                git(self.root, "checkout", "-q", "main")
        other("---\n" + emit({"schema": "handoff/1", "plan": "zz", "spec": ["docs/else.md"]}) + "---\n")
        self.assertIn(s["spec"], plan_effort(self.root, self.cfg, "p", s["merge"]))  # not naming it
        other("---\n" + emit({"schema": "handoff/1", "plan": "zz", "spec": ["docs/else.md", s["spec"]]}) + "---\n")
        self.assertNotIn(s["spec"], plan_effort(self.root, self.cfg, "p", s["merge"]))  # naming it among several
        other("garbage, not front matter\n")
        self.assertNotIn(s["spec"], plan_effort(self.root, self.cfg, "p", s["merge"]))  # unparsable: kept
        other("---\n" + emit({"schema": "handoff/1", "plan": "zz", "spec": "x"}) + "---\n")
        self.assertNotIn(s["spec"], plan_effort(self.root, self.cfg, "p", s["merge"]))  # a bad shape: kept
        other("---\n" + emit({"schema": "handoff/1", "plan": "zz", "spec": ["docs/else.md"]}) + "---\n")
        self.assertIn(s["spec"], plan_effort(self.root, self.cfg, "p", s["merge"]))  # the own handoff is not another
        git(self.root, "checkout", "-q", "-b", "feat")  # a handoff only on a branch is not read
        self.put("%s/yy/handoff.md" % PS, "---\n" + emit({"schema": "handoff/1", "spec": [s["spec"]]}) + "---\n")
        commit_all(self.root, "branch only")
        self.assertIn(s["spec"], plan_effort(self.root, self.cfg, "p", s["merge"]))

    def test_plan_effort_base_branch_missing(self):  # PE7
        s = self.scenario()
        for base in ("nonesuch", "tagbase"):  # a tag is not a local branch either
            git(self.root, "tag", "tagbase") if base == "tagbase" else None
            with self.assertRaises(GateError) as cm:
                plan_effort(self.root, dict(self.cfg, base_branch=base), "p", s["merge"])
            self.assertEqual(str(cm.exception), "%s is not a local branch; update %s from the remote" % (base, base))

    def test_plan_effort_enumerates_other_handoffs(self):  # PE8
        s = self.scenario()
        self.put("%s/empty-dir/note.md" % PS)  # a directory with no handoff
        self.put(PS + "/stray.md")  # a file directly in plan_state
        for i in range(12):
            self.put("%s/o%d/handoff.md" % (PS, i), "---\n" + emit({"schema": "handoff/1", "spec": ["docs/e%d.md" % i]}) + "---\n")
        commit_all(self.root, "others")
        self.assertIn(s["spec"], plan_effort(self.root, self.cfg, "p", s["merge"]))
        self.put("%s/o3/handoff.md" % PS, "---\n" + emit({"schema": "handoff/1", "spec": [s["spec"]]}) + "---\n")
        commit_all(self.root, "o3 names it")
        self.assertNotIn(s["spec"], plan_effort(self.root, self.cfg, "p", s["merge"]))

    def test_plan_effort_directory_contents(self):  # PE9
        s = self.scenario(extra={PS + "/p/mutations/F.txt": "m\n", PS + "/p/a/b/c.txt": "c\n",
                                 REV + "/p/sp aceé.md": "u\n", PS + "/p/new\nline.txt": "n\n"})
        got = set(plan_effort(self.root, self.cfg, "p", s["merge"]))
        self.assertTrue({PS + "/p/mutations/F.txt", PS + "/p/a/b/c.txt", REV + "/p/sp aceé.md",
                         PS + "/p/new\nline.txt"} <= got)
        os.symlink("ledger.md", os.path.join(self.root, PS, "p", "link"))
        at = commit_all(self.root, "symlink")
        with self.assertRaises(GateError) as cm:
            plan_effort(self.root, self.cfg, "p", at)
        self.assertIn(PS + "/p/link", str(cm.exception))

    def test_plan_effort_claims_follow_their_document(self):  # PE10
        s = self.scenario(extra={})
        self.put(CL + "/" + "docs--strict-delivery--plans--p.yml", emit({"schema": "claim/1", "document": "%s/p.md" % PG, "claims": []}))
        self.put(CL + "/gone.yml", emit({"schema": "claim/1", "document": "docs/deleted-already.md", "claims": []}))
        at = commit_all(self.root, "more claims")
        got = set(plan_effort(self.root, self.cfg, "p", at))
        self.assertIn(s["claim"], got)
        self.assertIn(CL + "/docs--strict-delivery--plans--p.yml", got)
        self.assertNotIn(s["kclaim"], got)
        self.assertNotIn(CL + "/gone.yml", got)

    def test_plan_effort_claim_file_kinds(self):  # PE11
        s = self.scenario()
        self.put(CL + "/odd.yml", emit({"schema": "claim/1", "document": 5, "claims": []}))
        self.put(CL + "/none.yml", emit({"schema": "claim/1", "claims": []}))
        at = commit_all(self.root, "odd claims")
        self.assertEqual(set(plan_effort(self.root, self.cfg, "p", at)), s["set"])
        self.put(CL + "/dup.yml", emit({"schema": "claim/1", "document": s["spec"], "claims": []}))
        at = commit_all(self.root, "a file whose name does not match its document")
        with self.assertRaises(GateError) as cm:
            plan_effort(self.root, self.cfg, "p", at)
        self.assertIn(CL + "/dup.yml", str(cm.exception))
        git(self.root, "rm", "-q", "-f", "--", CL + "/dup.yml")
        self.put(CL + "/broken.yml", "a: [unclosed\n")
        at = commit_all(self.root, "broken claim")
        with self.assertRaises(GateError) as cm:
            plan_effort(self.root, self.cfg, "p", at)
        self.assertIn("broken.yml", str(cm.exception))

    def test_plan_effort_findings(self):  # PE12
        s = self.scenario()
        got = set(plan_effort(self.root, self.cfg, "p", s["merge"]))
        self.assertIn("%s/%s.yml" % (FD, s["fid"]), got)
        self.assertNotIn("%s/%s.yml" % (FD, s["other"]), got)  # another plan's
        self.assertNotIn("%s/%s.yml" % (FD, s["openf"]), got)  # an open finding owned by the plan: the gate judges it

    def test_plan_effort_finding_shapes(self):  # PE13
        s = self.scenario()
        for name, row in (("status missing", {"resolved_by": "p"}), ("status None", {"status": None, "resolved_by": "p"}),
                          ("status padded", {"status": "closed ", "resolved_by": "p"}),
                          ("resolved_by padded", {"status": "closed", "resolved_by": "p "}),
                          ("resolved_by upper", {"status": "closed", "resolved_by": "P"}),
                          ("resolved_by missing", {"status": "closed"}), ("resolved_by int", {"status": "closed", "resolved_by": 5})):
            self.put("%s/F-20261031-bbbb.yml" % FD, emit(dict({"schema": "finding/1", "id": "F-20261031-bbbb"}, **row)))
            at = commit_all(self.root, name)
            self.assertNotIn("%s/F-20261031-bbbb.yml" % FD, plan_effort(self.root, self.cfg, "p", at), name)
        self.put("%s/F-20261031-bbbb.yml" % FD, emit({"schema": "finding/1", "id": "F-20261031-bbbb", "status": "merged",
                                                     "resolved_by": "p", "review_round": 2, "dimension": "x"}))
        at = commit_all(self.root, "merged with Q-ES fields")
        self.assertIn("%s/F-20261031-bbbb.yml" % FD, plan_effort(self.root, self.cfg, "p", at))
        self.put("%s/F-20261031-cccc.yml" % FD, "a: [unclosed\n")
        at = commit_all(self.root, "broken record")
        with self.assertRaises(GateError) as cm:
            plan_effort(self.root, self.cfg, "p", at)
        self.assertIn("F-20261031-cccc.yml", str(cm.exception))

    def test_plan_effort_at_forms(self):  # PE14
        s = self.scenario()
        git(self.root, "tag", "tg", s["merge"])
        for ok in (s["merge"], "tg", "HEAD", "main", "refs/heads/main"):
            with self.subTest(ok):
                self.assertTrue(set(plan_effort(self.root, self.cfg, "p", ok)) >= s["set"] - {LEDGER})
                self.assertIn("%s/p.md" % PG, plan_effort(self.root, self.cfg, "p", ok))
        blob = git(self.root, "rev-parse", "HEAD:" + "%s/p.md" % PG)
        for bad in (None, "", "-x", "a" * 41, 5, _Sub("HEAD"), "nosuchref", blob, git(self.root, "rev-parse", "HEAD^{tree}")):
            with self.subTest(repr(bad)):
                with self.assertRaises(GateError):
                    plan_effort(self.root, self.cfg, "p", bad)

    def test_plan_effort_plan_slug_prefix(self):  # PE15
        s = self.scenario(plan="p", tag="one")
        t = self.scenario(plan="p-b", tag="two", fid="F-20261031-m3m3".replace("3", "4"))
        got = set(plan_effort(self.root, self.cfg, "p", t["merge"]))
        self.assertEqual(got, s["set"])
        self.assertFalse(any("/p-b" in x for x in got))
        for bad in ("P", "a/b", "..", "a b", "", None, 5, _Sub("p"), "p\0", "p\n"):
            with self.assertRaises(ValueError):
                plan_effort(self.root, self.cfg, bad, t["merge"])

    def test_plan_effort_result_is_sorted_unique(self):  # PE16
        s = self.scenario()
        got = plan_effort(self.root, self.cfg, "p", s["merge"])
        self.assertIs(type(got), list)
        self.assertEqual(got, sorted(set(got)))
        self.assertTrue(all(type(x) is str and not x.startswith("/") for x in got))

    def test_plan_effort_as_of_at(self):  # PE17
        s = self.scenario()
        before = git(self.root, "rev-parse", s["merge"] + "^1")
        self.assertEqual(plan_effort(self.root, self.cfg, "p", before), [])  # nothing of the plan existed yet
        self.put("%s/p/late.md" % PS)
        commit_all(self.root, "late")
        self.assertNotIn("%s/p/late.md" % PS, plan_effort(self.root, self.cfg, "p", s["merge"]))
        self.assertIn("%s/p/late.md" % PS, plan_effort(self.root, self.cfg, "p", "HEAD"))

    def test_plan_effort_shallow(self):  # PE18
        s = self.scenario()
        self.put("later")
        commit_all(self.root, "later")
        shallow = os.path.join(self.tmp, "shallow")
        git(self.tmp, "clone", "-q", "--depth", "1", "file://" + self.root, shallow)
        with self.assertRaises(GateError):
            plan_effort(shallow, config.load(shallow), "p", s["merge"])

    def test_plan_effort_uses_cfg_paths(self):  # PE19
        s = self.scenario()
        moved = {"plans": "m/plans", "plan_state": "m/state", "reviews": "m/rev", "specs": "m/specs",
                 "claims": "m/claims", "findings": "m/findings"}
        files = {"m/plans/p.md": "x", "m/state/p/ledger.md": "x", "m/state/p/handoff.md":
                 "---\n" + emit({"schema": "handoff/1", "spec": ["m/specs/s.md"]}) + "---\n", "m/rev/p/r.md": "x",
                 "m/specs/s.md": "x", "m/claims/m--specs--s.yml": emit({"schema": "claim/1", "document": "m/specs/s.md", "claims": []}),
                 "m/findings/F-20261031-k3f9.yml": emit({"schema": "finding/1", "id": "F-20261031-k3f9", "status": "closed", "resolved_by": "p"})}
        for k, v in files.items():
            self.put(k, v)
        at = commit_all(self.root, "moved")
        cfg = dict(self.cfg, paths=dict(self.cfg["paths"], **moved))
        self.assertEqual(set(plan_effort(self.root, cfg, "p", at)), set(files))
        self.assertEqual(set(plan_effort(self.root, self.cfg, "p", s["merge"])), s["set"])

    def test_plan_effort_root_and_cfg_forms(self):
        s = self.scenario()
        for bad in (None, "", _Sub(self.root)):
            with self.assertRaises(GateError):
                plan_effort(bad, self.cfg, "p", s["merge"])
        for cfg in ({}, dict(self.cfg, paths={})):
            with self.assertRaises(GateError):
                plan_effort(self.root, cfg, "p", s["merge"])
        sub = os.path.join(self.root, "sub")
        os.mkdir(sub)
        with self.assertRaises(GateError) as cm:
            plan_effort(sub, self.cfg, "p", s["merge"])
        self.assertEqual(str(cm.exception), TOP)


class ProgramEffortTests(Cx):
    def program(self, plans=("a-plan", "b-plan"), specs=(), program_plan=PG + "/program-plan.md", branch=True, **over):
        streams = {"schema": "streams/1", "program": NAME, "plan": program_plan, "specs": list(specs),
                   "streams": [{"id": p[0], "plan": "%s/%s.md" % (PG, p)} for p in plans]}
        streams.update(over)
        d = "%s/%s" % (PROGRAMS, NAME)
        if branch:
            git(self.root, "checkout", "-q", "-b", NAME + "/integration", "main")
        self.put(d + "/streams.yml", emit(streams))
        self.put(d + "/status.md", "<!-- schema: status/1 -->\n\nthe status page\n")
        self.put(d + "/sync-log.md", "<!-- schema: sync-log/1 -->\n")
        self.put(d + "/merged.md", "<!-- schema: merged-log/1 -->\n")
        self.put(program_plan, "program plan\n")
        commit_all(self.root, "program")
        if branch:
            git(self.root, "checkout", "-q", "main")

    def two(self):
        a = self.scenario(plan="a-plan", tag="sa", fid="F-20261031-k3f9")
        b = self.scenario(plan="b-plan", tag="sb", fid="F-20261031-m4n5".replace("m4n5", "n5n5"))
        return a, b

    def test_program_effort_all_merged(self):  # PR1, PR4, PR10, PR8
        a, b = self.two()
        self.program(specs=[SPECS + "/program-spec.md"])
        git(self.root, "checkout", "-q", NAME + "/integration")
        self.put(SPECS + "/program-spec.md")
        commit_all(self.root, "spec")
        git(self.root, "checkout", "-q", "main")
        self.put(PS + "/a-plan/late.md")  # written after the final merge: read "at its final merge", it is not in the set
        commit_all(self.root, "late")
        want = sorted(a["set"] | b["set"] | {PG + "/program-plan.md", SPECS + "/program-spec.md"})
        for at in (None, a["merge"], "HEAD"):
            self.assertEqual(program_effort(self.root, self.cfg, NAME, at), want)
        self.assertFalse(any(p.startswith(PROGRAMS + "/") for p in want))

    def test_program_folder_not_in_program_effort(self):  # PR4, plan test (at is None)
        self.two()
        self.program()
        got = program_effort(self.root, self.cfg, NAME, None)
        self.assertFalse(any(p.startswith(PROGRAMS + "/") for p in got))
        self.assertIn(PG + "/program-plan.md", got)

    def test_program_effort_unmerged_stream(self):  # PR2
        self.scenario(plan="a-plan", tag="sa")
        self.scenario(plan="b-plan", tag="sb", fid="F-20261031-n5n5", final=False)
        self.program()
        with self.assertRaises(GateError) as cm:
            program_effort(self.root, self.cfg, NAME, None)
        self.assertEqual(str(cm.exception), "stream plan b-plan has no final merge; the program is not finished")

    def test_program_effort_stream_plan_absent(self):  # PR3
        a, b = self.two()
        git(self.root, "rm", "-q", "-f", "--", PG + "/b-plan.md")
        commit_all(self.root, "no stream plan file")
        self.program()
        got = program_effort(self.root, self.cfg, NAME, None)
        self.assertIn(PG + "/b-plan.md", got)  # the streams file names it; plan_effort adds nothing for it
        self.assertEqual(set(got) - {PG + "/b-plan.md", PG + "/program-plan.md"}, a["set"] | (b["set"] - {PG + "/b-plan.md"}))

    def test_program_effort_missing_integration_branch(self):  # PR5
        self.two()
        self.program(branch=False)
        with self.assertRaises(GateError):
            program_effort(self.root, self.cfg, NAME, None)

    def test_program_effort_broken_program_files(self):  # PR6
        self.two()
        self.program()
        git(self.root, "checkout", "-q", NAME + "/integration")
        git(self.root, "rm", "-q", "-f", "--", "%s/%s/status.md" % (PROGRAMS, NAME))
        commit_all(self.root, "no status")
        git(self.root, "checkout", "-q", "main")
        with self.assertRaises(GateError) as cm:
            program_effort(self.root, self.cfg, NAME, None)
        self.assertIn("status.md", str(cm.exception))

    def test_program_effort_program_name_forms(self):  # PR7
        for bad in ("20261101-X", "a/b", "", None, 5, _Sub(NAME), NAME + "\0"):
            with self.subTest(repr(bad)):
                with self.assertRaises(GateError):
                    program_effort(self.root, self.cfg, bad, None)

    def test_program_effort_at_forms(self):  # PR8
        self.two()
        self.program()
        for bad in ("", 5, "-x", b"x"):
            with self.assertRaises(GateError):
                program_effort(self.root, self.cfg, NAME, bad)

    def test_program_effort_streams_yml_shapes(self):  # PR9
        self.two()
        for name, over in (("plan not str", {"plan": 5}), ("spec outside specs", {"specs": ["docs/else.md"]}),
                           ("specs not list", {"specs": "x"}), ("plan not under plans", {"plan": "docs/x/program-plan.md"}),
                           ("plan nested", {"plan": PG + "/sub/p.md"}), ("plan not md", {"plan": PG + "/p.txt"}),
                           ("streams not list", {"streams": "x"}), ("stream plan dotdot", {"streams": [{"plan": PG + "/../x.md"}]}),
                           ("stream without plan", {"streams": [{"id": "a"}]})):
            with self.subTest(name):
                self.fresh_branch()
                self.program(**over)
                with self.assertRaises(GateError):
                    program_effort(self.root, self.cfg, NAME, None)
        self.fresh_branch()
        self.program(plans=("a-plan", "a-plan"))  # two streams, one plan: collapsed
        self.assertEqual(len([p for p in program_effort(self.root, self.cfg, NAME, None) if p == PG + "/a-plan.md"]), 1)

    def fresh_branch(self):
        if NAME + "/integration" in gitinfo.local_branches(self.root):
            git(self.root, "branch", "-q", "-D", NAME + "/integration")

    def test_program_effort_spec_shared_between_streams(self):  # PR11, D-Q11
        a = self.scenario(plan="a-plan", tag="shared")
        b = self.scenario(plan="b-plan", tag="sb", fid="F-20261031-n5n5", spec_also=[a["spec"]])
        self.program()
        got = program_effort(self.root, self.cfg, NAME, None)
        self.assertNotIn(a["spec"], got)  # each stream plan keeps it: the other's handoff is still at the base tip
        self.assertIn(b["spec"], got)

    def test_program_effort_program_specs_shared(self):  # PR12: the program's specs are taken as written
        a, b = self.two()
        self.program(specs=[a["spec"]])
        self.assertIn(a["spec"], program_effort(self.root, self.cfg, NAME, None))

    def test_program_effort_uses_stream_ledgers(self):  # PR10
        a, b = self.two()
        self.program()
        self.assertTrue(set(program_effort(self.root, self.cfg, NAME, None)) >= a["set"] | b["set"])
        d = "%s/%s/merged.md" % (PROGRAMS, NAME)
        self.assertFalse(os.path.exists(os.path.join(self.root, d)))  # merged.md is on the integration branch only


class CitedTests(Cx):
    def at(self, files):
        for k, v in files.items():
            self.put(k, v)
        return commit_all(self.root, "files")

    def test_cited_decisions_whole_token(self):  # CD1
        at = self.at({"docs/a.md": "we follow %s here\n" % D1})
        self.assertEqual(cited_decisions(self.root, ["docs/a.md"], at, "DEC"), [D1])

    def test_cited_decisions_in_code_blocks(self):  # CD2
        at = self.at({"docs/a.md": "`%s` and\n```\n%s\n```\n" % (D1, D2)})
        self.assertEqual(cited_decisions(self.root, ["docs/a.md"], at, "DEC"), [D1, D2])

    def test_cited_decisions_longer_tokens(self):  # CD3
        none = ["X" + D1, D1 + "a", D1 + "-2", D1 + "_x", "1" + D1, "-" + D1]
        at = self.at({"docs/a.md": "\n".join(none) + "\n"})
        self.assertEqual(cited_decisions(self.root, ["docs/a.md"], at, "DEC"), [])
        for ok in ("(%s)" % D1, D1 + ".", D1 + ":", D1 + "ࡰ", "ࡰ" + D1, D1 + "\U0001fae8", " " + D1 + "\t"):
            with self.subTest(repr(ok)):
                at = self.at({"docs/b.md": ok + "\n"})
                self.assertEqual(cited_decisions(self.root, ["docs/b.md"], at, "DEC"), [D1])
        at = self.at({"docs/c.md": "XF-20261031-k3f9 F-20261031-k3f9a F-20261031-k3f9\n"})
        self.assertEqual(cited_decisions(self.root, ["docs/c.md"], at, "F"), ["F-20261031-k3f9"])

    def test_cited_decisions_binary_file(self):  # CD4, D-Q13
        at = self.at({"docs/a.bin": b"\x00\x01 " + D1.encode() + b" \x00\n", "docs/bad.bin": b"\xff\xfe" + D1.encode()})
        self.assertEqual(cited_decisions(self.root, ["docs/a.bin"], at, "DEC"), [D1])  # NUL, valid UTF-8
        with self.assertRaises(GateError) as cm:
            cited_decisions(self.root, ["docs/bad.bin"], at, "DEC")
        self.assertEqual(str(cm.exception), "docs/bad.bin: not valid UTF-8")

    def test_cited_decisions_path_absent_at_at(self):  # CD5
        at = self.at({"docs/a.md": D1})
        self.assertEqual(cited_decisions(self.root, ["docs/a.md", "docs/missing.md"], at, "DEC"), [D1])

    def test_cited_decisions_unique_sorted(self):  # CD6
        at = self.at({"docs/a.md": "%s %s %s\n" % (D2, D1, D2), "docs/b.md": D1})
        self.assertEqual(cited_decisions(self.root, ["docs/a.md", "docs/b.md"], at, "DEC"), [D1, D2])

    def test_cited_decisions_id_shape(self):  # CD7
        text = "DEC-20261301-k3f9 DEC-20261031-0o1l DEC-20261031-K3F9 F-20261031-k3f9 DEC-20261031-\nk3f9 DEC-20260230-k3f9\n"
        at = self.at({"docs/a.md": text})
        self.assertEqual(cited_decisions(self.root, ["docs/a.md"], at, "DEC"), [])

    def test_cited_decisions_prefix_forms(self):  # CD8
        at = self.at({"docs/a.md": D1 + " DXC-20261031-k3f9 DEC-20261031-m4n5\n"})
        for bad in ("", None, 5, b"DEC"):
            with self.assertRaises(GateError):
                cited_decisions(self.root, ["docs/a.md"], at, bad)
        self.assertEqual(cited_decisions(self.root, ["docs/a.md"], at, "D.C"), [])  # a metacharacter never acts
        self.assertEqual(cited_decisions(self.root, ["docs/a.md"], at, "DEC|F"), [])
        self.assertEqual(cited_decisions(self.root, ["docs/a.md"], at, "dec"), [])

    def test_cited_decisions_paths_forms(self):  # CD9
        at = self.at({"docs/a.md": D1})
        self.assertEqual(cited_decisions(self.root, [], at, "DEC"), [])
        for bad in ("docs/a.md", ("docs/a.md",), None, [None], [5], [""], ["../x"], ["/abs"], ["docs//a.md"]):
            with self.subTest(repr(bad)):
                with self.assertRaises(GateError):
                    cited_decisions(self.root, bad, at, "DEC")
        with self.assertRaises(GateError) as cm:
            cited_decisions(self.root, "docs/a.md", at, "DEC")
        self.assertEqual(str(cm.exception), "paths must be a list of str")

    def test_cited_decisions_at_forms(self):  # CD10
        at = self.at({"docs/a.md": D1})
        for bad in (None, "", "-x", "a" * 41, 5, "nosuchref", git(self.root, "rev-parse", "HEAD^{tree}")):
            with self.subTest(repr(bad)):
                with self.assertRaises(GateError):
                    cited_decisions(self.root, ["docs/a.md"], bad, "DEC")

    def test_cited_decisions_linear_time(self):  # CD11
        big = ("x" * 1000 + "\n") * 5000 + "y" * 1000000 + "\n" + ("DEC-20261031-" * 1000) + " " + D1 + "\n"
        at = self.at({"docs/big.md": big})
        t0 = time.time()
        self.assertEqual(cited_decisions(self.root, ["docs/big.md"], at, "DEC"), [D1])
        self.assertLess(time.time() - t0, 5)

    def test_cited_decisions_line_ends_and_bom(self):  # CD12
        at = self.at({"docs/a.md": "﻿%s\r\n%s\r\n\t%s\t\n" % (D1, D2, D1)})
        self.assertEqual(cited_decisions(self.root, ["docs/a.md"], at, "DEC"), [D1, D2])

    def test_cited_decisions_reads_at_commit(self):  # CD13
        at = self.at({"docs/a.md": D1 + "\n"})
        self.at({"docs/a.md": D2 + "\n"})
        self.assertEqual(cited_decisions(self.root, ["docs/a.md"], at, "DEC"), [D1])
        self.assertEqual(cited_decisions(self.root, ["docs/a.md"], "HEAD", "DEC"), [D2])

    def test_cited_decisions_matches_a_reference_scanner(self):  # oracle 4: split on the class, compare tokens
        neighbours = ["", " ", "a", "Z", "9", "_", "-", ".", "(", "ࡰ", "\U0001fae8", "\n"]
        texts, expected = [], []
        for i, (l, r) in enumerate((l, r) for l in neighbours for r in neighbours):
            texts.append(l + D1 + r)
            ok = (l == "" or not re.fullmatch(r"[0-9A-Za-z_-]", l[-1])) and (r == "" or not re.fullmatch(r"[0-9A-Za-z_-]", r[0]))
            expected.append([D1] if ok else [])
        for text, want in zip(texts, expected):
            at = self.at({"docs/r.md": text})
            self.assertEqual(cited_decisions(self.root, ["docs/r.md"], at, "DEC"), want, repr(text))


class VersionTests(unittest.TestCase):
    def test_cleanup_no_int_call_and_no_exception_groups(self):  # V1, V3
        with open(os.path.join(REPO, "gates", "lib", "cleanup.py"), encoding="utf-8") as fh:
            source = fh.read()
        tree = ast.parse(source)
        self.assertNotIn("(?<!\\w", source)  # the boundary class is written out, never \w
        for node in ast.walk(tree):
            self.assertFalse(isinstance(node, ast.Call) and getattr(node.func, "id", "") == "int")
            self.assertFalse(isinstance(node, ast.Name) and node.id in ("ExceptionGroup", "BaseExceptionGroup"))
            self.assertFalse(isinstance(node, ast.Attribute) and node.attr in ("isalpha", "isalnum", "isprintable", "lower",
                                                                              "casefold", "upper", "isidentifier"))

    def test_cleanup_unicode_same_on_both(self):  # V2: sorting and equality only; U+0870 and U+2C2F are plain code points
        self.assertEqual(sorted(["Ⱟ", "ࡰ", "b", "B"]), ["B", "b", "ࡰ", "Ⱟ"])
        self.assertTrue(cleanup.is_slug("p") and not cleanup.is_slug("ࡰ"))


if __name__ == "__main__":
    unittest.main()
