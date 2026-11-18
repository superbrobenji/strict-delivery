"""Task P2.2 part b: more rows of the input-domain table task-P2.2-domain.md (row ids in the comments) for ``program
create`` (CR6-CR8, CR12-CR13, CR20, CL5, CL7, CA17-CA19, RT2, RT4, RT7, RT10) and ``program merged`` (MG2, MG3, MG13).
Expected values are written by hand from the plan lines and the table; every git fixture is a ``make_repo`` repository."""
import os
from unittest import mock

from gates.lib import dispatch
from tests.helpers import commit_all, git, minimal_config
from tests.test_program_cli import (DEC, NAME, PG, PLAN, PS, Fx, After, breakdown_row, run, stream, streams_row)
from tests.test_program_merged import merged_line


class CreateRows(Fx):
    def refused(self, *needles, **kw):
        code, out, err = self.create(**kw)
        self.assertEqual((code, out), (1, ""), err)
        for n in needles:
            self.assertIn(n, err)
        self.assertFalse(os.path.exists(self.folder()))
        return err

    def test_plan_file_kinds(self):  # CR6
        plan = os.path.join(self.iw, PG, PLAN + ".md")
        os.unlink(plan)
        self.assertIn(PG + "/" + PLAN + ".md", self.refused("is missing"))
        os.mkdir(plan)
        self.assertEqual(self.create()[0], 1)                      # a directory is no plan text
        os.rmdir(plan)
        os.symlink(os.path.join(self.iw, "streams-elsewhere"), plan)
        self.assertEqual(self.create()[0], 1)                      # a symlink is never followed to a plan
        os.unlink(plan)
        with open(plan, "wb") as fh:
            fh.write(b"\xff\xfe not utf-8")
        self.assertEqual(self.create()[0], 1)
        with open(plan, "w", encoding="utf-8") as fh:
            fh.write("")
        self.refused("outline.structure")                          # empty: read as text, then judged

    def test_breakdown_file_kinds(self):  # CR7
        bd = os.path.join(self.iw, PS, PLAN, "breakdown.yml")
        for name, make in (("missing", lambda: os.unlink(bd)), ("directory", lambda: (os.unlink(bd), os.mkdir(bd))),
                           ("yaml error", lambda: self.put(bd, "a: [\n"))):
            with self.subTest(name):
                if os.path.isdir(bd):
                    os.rmdir(bd)
                if not os.path.lexists(bd):
                    open(bd, "w").close()
                make()
                self.refused("breakdown")

    def put(self, path, text):
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)

    def test_plan_slug_forms(self):  # CR8
        for bad in ("", "A", "a_b", "a/b", "..", "a\n", "café", "x" * 4301):
            with self.subTest(repr(bad[:12])):
                code, out, err = self.create(plan=bad)
                self.assertEqual((code, out), (1, ""))
                self.assertFalse(os.path.exists(self.folder()))
        self.assertEqual(self.create(plan="-a")[0], 2)              # a value that starts with '-' is read as an option

    def test_create_twice_refused(self):  # CR12 (working tree), CR20
        self.assertEqual(self.create()[0], 0)
        code, out, err = self.create()
        self.assertEqual((code, out), (1, ""))
        self.assertIn("already exists in the working tree", err)
        self.commit_iw()
        self.assertIn("already exists", self.create()[2])           # committed at HEAD

    def test_folder_only_at_base_tip_refused(self):  # CR12: added to main after the branch was cut
        base = ".strict-delivery/state/programs/%s" % NAME
        self.write_main(base + "/streams.yml", "x: 1\n")
        commit_all(self.work, "program on main")
        err = self.refused("already exists at refs/heads/main")
        self.assertIn(base, err)

    def test_decision_forms(self):  # CR13
        self.decision("DEC-20261105-op3n", "open")
        self.decision("DEC-20261105-wd3n", "withdrawn")
        self.decision("DEC-20261105-sc3p", "answered", "scope")
        git(self.work, "add", "-A")
        for did in ("DEC-20261105-op3n", "DEC-20261105-wd3n", "DEC-20261105-sc3p", "DEC-20261105-zzzz", "DEC-1", ""):
            with self.subTest(did):
                code, out, err = self.create(decision=did)
                self.assertEqual((code, out), (1, ""))
                self.assertFalse(os.path.exists(self.folder()))
        self.assertEqual(self.create()[0], 0)

    def test_limit_environment_malformed(self):  # CL5: limits_of raises ValueError, create refuses, no traceback
        for val in ("0", "-1", "05", " 5", "5 ", "x", "", "9" * 601, "٥"):
            with self.subTest(repr(val[:8])):
                with mock.patch.dict(os.environ, {"CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH": val}):
                    code, out, err = self.create()
                self.assertEqual((code, out), (1, ""))
                self.assertTrue(err.startswith("program create: "), err)
                self.assertFalse(os.path.exists(self.folder()))

    def test_limit_tuple_order(self):  # CL7: limits_of returns (depth, concurrent); a swap is refused for depth only
        with mock.patch.object(dispatch, "limits_of", return_value=(1, 10)):
            err = self.refused("max_depth 2 is above the effective limit 1")
        self.assertNotIn("max_concurrent", err)
        with mock.patch.object(dispatch, "limits_of", return_value=(10, 1)):
            err = self.refused("max_concurrent 2 is above the effective limit 1")
        self.assertNotIn("max_depth", err)

    def test_stacked_order(self):  # CA17-CA19, plan test :2777
        row = streams_row(stream("a", ["a/"]), stream("b", ["b/"], merge_order=2, stacked_on="a"))
        self.set_streams(row)
        self.refused("stacked_on")                                  # no edge orders merged:b/B1 after merged:a
        edge = [{"from": "A1.1", "to": "B1.1"}]
        write = self.write_breakdown
        write(breakdown_row(edges=edge, groups=[{"id": "g", "tasks": ["A1.1"]}]))
        self.assertEqual(self.create()[0], 0)

    def write_breakdown(self, row):
        from tests.helpers import write_record
        write_record(self.iw, "%s/%s/breakdown.yml" % (PS, PLAN), row)

    def test_worktrees_wrong_type(self):  # RT10
        for bad in (5, ["../w"], None):
            with self.subTest(repr(bad)):
                row = streams_row()
                row["worktrees"] = bad
                self.set_streams(row)
                self.refused("worktrees")

    def test_refused_in_main_checkout_with_branch(self):  # RT2: no worktree; the branch checked out in the main checkout
        git(self.iw, "checkout", "-q", "--detach")
        git(self.work, "checkout", "-q", NAME + "/integration")
        code, out, err = self.create(root=self.work)
        self.assertEqual((code, out), (1, ""))
        self.assertIn("integration worktree", err)

    def test_root_spelled_through_a_symlink(self):  # RT7: compared after realpath
        link = os.path.join(self.tmp, "iwlink")
        os.symlink(self.iw, link)
        self.assertEqual(self.create(root=link)[0], 0)


class MergedLineForms(After):
    def test_merged_line_forms(self):  # MG2, MG3, MG13
        good = merged_line(7, "1" * 40, "2" * 40, "a", "A1")
        text = self.read("merged.md")
        for name, line in (("empty", ""), ("lowercase", good.replace("MERGED", "merged")), ("keyword alone", "MERGED"),
                           ("leading space", " " + good), ("trailing space", good + " "), ("trailing newline", good + "\n"),
                           ("carriage return", good + "\r"), ("note prefix", "Note: " + good),
                           ("only stream", good.replace(" block=A1", "")), ("only block", good.replace(" stream=a", "")),
                           ("4301 chars", good + "x" * 4301), ("non-ascii", good.replace("u at", "é at")),
                           ("pr 601 digits", good.replace("pr=7", "pr=" + "7" * 601)), ("pr zero", good.replace("pr=7", "pr=0"))):
            with self.subTest(name):
                code, out, err = self.cli("merged", "--line", line)
                self.assertEqual((code, out), (1, ""))
                self.assertTrue(err.startswith("program merged: "), err)
                self.assertEqual(self.read("merged.md"), text)
        self.assertEqual(self.cli("merged")[0], 1)                  # --line absent: refused, "--line is required"
        self.assertEqual(self.cli("merged", "--line", "")[0], 1)


class RequestDone(After):
    def test_done_commit_on_the_owners_branch(self):  # RS3, RS2: done needs --commit, and the commit lies on the owner's branch
        rid = self.new_request()
        self.assertEqual(self.cli("request set", rid, "--status", "accepted", "--by", "b")[0], 0)
        before = self.status_of(rid)
        self.assertEqual(self.cli("request set", rid, "--status", "done", "--by", "b")[0], 1)         # no --commit
        stray = git(self.iw, "rev-parse", "HEAD")
        code, out, err = self.cli("request set", rid, "--status", "done", "--by", "b", "--commit", stray)
        self.assertEqual((code, out, self.status_of(rid)), (1, "", before))                           # not on b's branch
        self.write_main("b/x.py", "x = 1\n")
        git(self.work, "checkout", "-q", "-b", NAME + "/b/main", "main")
        self.write_main("b/x.py", "x = 2\n")
        sha = commit_all(self.work, "b work")
        git(self.work, "checkout", "-q", "main")
        code, out, err = self.cli("request set", rid, "--status", "done", "--by", "b", "--commit", sha)
        self.assertEqual((code, out, err), (0, "push %s/integration\n" % NAME, ""))
        self.assertEqual(self.status_of(rid), "done")
