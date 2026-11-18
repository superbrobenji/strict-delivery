"""Task P2.2 part b: ``program merged`` on real ``--no-ff`` merges (rows MG1-MG9, MG12; plan test :2806-2807), the plan's
RECORD_BREAKDOWN (the section 6 record's hand-overs: 8 paths, four of them with two owners), and the subprocess and
git-call oracles (PG9, PG13, PG14, RT11). Expected values are written by hand from the plan lines and the table
task-P2.2-domain.md; every git fixture is a ``helpers.make_repo`` repository (no local ``main`` of this repository)."""
import os
import subprocess
import sys
import unittest
from unittest import mock

from gates.lib import breakdown, gitinfo
from tests.helpers import GitIsolatedTestCase, commit_all, git, make_repo, write_record
from tests.test_program_cli import DEC, NAME, PG, PS, Fx, load_yaml, run

REG, PLUGIN, IGN, CLAUDE = "gates/reg.py", "plugin.json", ".gitignore", "CLAUDE.md"
PLAN_REC = "rec-plan"
BLOCKS = [("3d", ["3d.1"]), ("R1", ["R1.1"]), ("R2", ["R2.1"]), ("R3", ["R3.1"]), ("R4", ["R4.1"]), ("R5", ["R5.1"]),
          ("4c", ["4c.1"]), ("4d", ["4d.1"]), ("4e", ["4e.1"]), ("6R", ["6R.1"])]
PLAN_TEXT_REC = "".join("## Block %s: b\n\n### Task %s: t\n\n" % (b, t[0]) for b, t in BLOCKS)
PERIOD = {"from": "program-start", "until": "program-close"}


def _st(sid, owns, order, **kw):
    s = {"id": sid, "purpose": "does " + sid, "plan": "%s/x-%s.md" % (PG, sid), "owns": owns, "estimate": 3,
         "depends_on": [], "merge_order": order}
    s.update(kw)
    if s.get("residual"):
        del s["owns"]
    return s


def _bs(sid, tasks, paths=None, **kw):
    s = {"id": sid, "tasks": tasks, "unblock": "at program start"}
    if paths is not None:
        s["paths"] = paths
    s.update(kw)
    return s


# the section 6 record's hand-overs, written out: package -> residual -> init4 (registry), package -> residual ->
# release (plugin.json), init4 -> release (.gitignore, CLAUDE.md, chained through merged:init4); 8 paths, 4 with two owners
PKG_P = [PLUGIN, REG]
INIT_P = [IGN, CLAUDE, {"path": REG, "from": "merged:residual"}]
REL_P = [IGN, CLAUDE, {"path": PLUGIN, "from": "merged:residual"}]
RECORD_BREAKDOWN = {
    "schema": "breakdown/1", "plan": PLAN_REC, "max_concurrent": 2, "max_depth": 2, "done": [],
    "streams": [_bs("package", ["3d.1"], PKG_P, period={"from": "program-start", "until": "merged:package"}),
                _bs("residual", ["R1.1", "R2.1", "R3.1", "R4.1", "R5.1"], residual=True, period=PERIOD),
                _bs("init4", ["4c.1", "4d.1", "4e.1"], INIT_P, period={"from": "program-start", "until": "merged:init4"}),
                _bs("release", ["6R.1"], REL_P, period={"from": "merged:init4", "until": "program-close"})],
    "edges": [{"from": "3d.1", "to": t} for t in ("R1.1", "R2.1", "R3.1", "R4.1", "R5.1")],
    "groups": [{"id": "g", "tasks": ["3d.1", "4c.1"]}]}
RECORD_STREAMS = {
    "schema": "streams/1", "program": NAME, "plan": "%s/%s.md" % (PG, PLAN_REC), "specs": [], "worktrees": "../w",
    "streams": [_st("package", PKG_P, 1, period={"from": "program-start", "until": "merged:package"}),
                _st("residual", [], 2, residual=True, period=PERIOD),
                _st("init4", INIT_P, 3, period={"from": "program-start", "until": "merged:init4"}),
                _st("release", REL_P, 4, period={"from": "merged:init4", "until": "program-close"})],
    "shared": []}
LEDGER1 = "<!-- schema: ledger/1 -->\n"


def merged_line(pr, head, merge, stream, block, final="no"):
    return ("MERGED pr=%d head=%s merge=%s merged_by=u at=2026-11-01T10:00:00Z final=%s stream=%s block=%s approval=host"
            % (pr, head, merge, final, stream, block))


class RecordBreakdown(unittest.TestCase):
    def test_record_breakdown_passes_with_eight_paths(self):  # BE1, plan test :2789
        n = sum(len(s.get("paths", [])) for s in RECORD_BREAKDOWN["streams"])
        self.assertEqual(n, 8)
        plans = {s: "x-" + s for s in ("package", "residual", "init4", "release")}
        self.assertEqual(breakdown.breakdown_errors(RECORD_BREAKDOWN), [])
        self.assertEqual(breakdown.breakdown_errors(RECORD_BREAKDOWN, plans=plans), [])
        self.assertEqual(breakdown.plan_errors(PLAN_TEXT_REC, RECORD_BREAKDOWN), [])

    def test_record_breakdown_unordered_hand_over_fails(self):  # BE14: the hand-over needs its edges
        bad = dict(RECORD_BREAKDOWN, edges=[])
        self.assertTrue(any(s == "paths" for s, _ in breakdown.breakdown_errors(bad)))


class RecFx(Fx):
    """A program created from RECORD_BREAKDOWN, committed on its integration branch."""

    def setUp(self):
        super().setUp()
        self.write_main("%s/%s.md" % (PG, PLAN_REC), PLAN_TEXT_REC)
        write_record(self.work, "%s/%s/breakdown.yml" % (PS, PLAN_REC), RECORD_BREAKDOWN)
        commit_all(self.work, "record")
        git(self.iw, "merge", "-q", "main")
        self.set_streams(RECORD_STREAMS)
        code, out, err = self.create(plan=PLAN_REC)
        self.assertEqual((code, err), (0, ""), err)
        self.commit_iw()
        self.pr_no = 0

    def pr(self, stream, tasks_blocks, extra=()):
        """A branch off main holding the stream's ledger with one CHECKPOINT per ``(block, task)``, merged into main with
        ``--no-ff``; returns ``(head, merge)``."""
        base = git(self.work, "rev-parse", "main")[:7]
        git(self.work, "checkout", "-q", "-b", "pr%d" % (self.pr_no + 1), "main")
        self.write_main("%s/x-%s/ledger.md" % (PS, stream), LEDGER1 + "".join(
            "CHECKPOINT %s %s head=%s tests=1/1 gates=PASS next=n\n" % (b, t, base) for b, t in tasks_blocks))
        head = commit_all(self.work, "work")
        git(self.work, "checkout", "-q", "main")
        git(self.work, "merge", "-q", "--no-ff", "-m", "Merge pr", "pr%d" % (self.pr_no + 1))
        self.pr_no += 1
        return head, git(self.work, "rev-parse", "main")

    def merged(self, line):
        return run("program", "merged", NAME, "--line", line, "--root", self.iw)

    def log(self):
        return self.read("merged.md")


class Merged(RecFx):
    def test_valid_line_appended(self):  # MG1, plan test :2807
        head, m = self.pr("release", [("6R", "6R.1")])
        line = merged_line(1, head, m, "release", "6R")
        code, out, err = self.merged(line)
        self.assertEqual((code, out, err), (0, "push %s/integration\n" % NAME, ""))
        self.assertEqual(self.log().splitlines(), ["<!-- schema: merged-log/1 -->", line])
        self.assertIn("PASS schema.merged-log", run("check", "schema", "--root", self.iw)[1])

    def test_refusals_leave_the_record(self):  # MG5, MG6, MG7, MG17: plan test :2807
        head, m = self.pr("package", [("3d", "3d.1")])
        before = self.log()
        good = merged_line(1, head, m, "package", "3d")
        sq = git(self.work, "rev-parse", head + "^1")
        for name, line in (("head moved", good.replace(head, sq)), ("unknown merge", good.replace(m, "1" * 40)),
                           ("first parent not a merge", good.replace(m, head)),
                           ("approval chat", good.replace("approval=host", "approval=chat")),
                           ("code-only pull request", merged_line(1, head, m, "init4", "4c"))):
            with self.subTest(name):
                code, out, err = self.merged(line)
                self.assertEqual((code, out), (1, ""))
                self.assertTrue(err.startswith("program merged: "), err)
                self.assertEqual(self.log(), before)
        self.assertEqual(self.merged(good)[0], 0)
        again = self.merged(good)
        self.assertEqual(again[0], 1)
        self.assertIn("recorded twice", again[2])
        h2, m2 = self.pr("package", [("3d", "3d.1")])
        self.assertEqual(self.merged(merged_line(1, h2, m2, "package", "3d"))[0], 1)  # pr 1 again, another stream or not

    def test_final_per_stream(self):  # MG7, Q-F80RR3-1 (a)
        h1, m1 = self.pr("package", [("3d", "3d.1")])
        h2, m2 = self.pr("release", [("6R", "6R.1")])
        h3, m3 = self.pr("package", [("3d", "3d.1")])
        a, b = merged_line(1, h1, m1, "package", "3d", "yes"), merged_line(2, h2, m2, "release", "6R", "yes")
        self.assertEqual(self.merged(a)[0], 0)
        self.assertEqual(self.merged(b)[0], 0)                     # a final line of a second stream is appended
        before = self.log()
        code, out, err = self.merged(merged_line(3, h3, m3, "package", "3d", "yes"))
        self.assertEqual((code, out, self.log()), (1, "", before))
        self.assertIn("final=yes after a final line of stream package", err)
        self.assertEqual(self.log().splitlines()[-1], b)

    def test_merged_block_rules(self):  # MG8, Q-F80W-8 (a), Q-F80W-10 (a), Q-F80RR3-2 (a): INIT4_BLOCK_4D, INIT4_BLOCK_R2
        h, m = self.pr("init4", [("4c", "4c.1"), ("4d", "4d.1"), ("4e", "4e.1")])
        before = self.log()
        for name, block, why in (("INIT4_BLOCK_4D", "4d", "block 4d is not the last sub-block it newly carries (4c, 4d, 4e)"),
                                 ("INIT4_BLOCK_R2", "R2", "block R2 is no sub-block of the tasks of stream init4")):
            with self.subTest(name):
                code, out, err = self.merged(merged_line(1, h, m, "init4", block))
                self.assertEqual((code, out, self.log()), (1, "", before))
                self.assertIn(why, err)
        line = merged_line(1, h, m, "init4", "4e")
        self.assertEqual(self.merged(line)[0], 0)
        self.assertEqual(self.log().splitlines()[-1], line)

    def test_residual_pull_request_order(self):  # MG8: RESIDUAL_R1_R5_R3_R2_R4, RESIDUAL_R3_BLOCK_R5
        carried, lines = [], []
        for n, blk in enumerate(("R1", "R5", "R3", "R2", "R4"), 1):
            carried.append((blk, blk + ".1"))
            h, m = self.pr("residual", sorted(carried))
            lines.append((merged_line(n, h, m, "residual", blk), h, m, blk))
            if blk == "R3":
                before = self.log()
                bad = merged_line(n, h, m, "residual", "R5")          # RESIDUAL_R3_BLOCK_R5: R5 was carried by pr 2
                code, out, err = self.merged(bad)
                self.assertEqual((code, out, self.log()), (1, "", before))
                self.assertIn("block R5 is not the last sub-block it newly carries (R3)", err)
            self.assertEqual(self.merged(lines[-1][0])[0], 0, blk)
        self.assertEqual(self.log().splitlines()[1:], [l[0] for l in lines])
        self.assertEqual(self.log().splitlines()[-1], lines[-1][0])
        self.assertEqual(self.log().splitlines()[-1].split(" block=")[1].split(" ")[0], "R4")

    def test_line_that_newly_carries_nothing(self):  # MG8
        h1, m1 = self.pr("residual", [("R1", "R1.1")])
        h2, m2 = self.pr("residual", [("R1", "R1.1")])
        self.assertEqual(self.merged(merged_line(1, h1, m1, "residual", "R1"))[0], 0)
        code, out, err = self.merged(merged_line(2, h2, m2, "residual", "R1"))
        self.assertEqual((code, out), (1, ""))
        self.assertIn("newly carries no sub-block", err)

    def test_carried_sub_blocks(self):  # MG9
        git(self.work, "checkout", "-q", "-b", "side", "main")
        self.write_main("side.txt", "x")
        side = commit_all(self.work, "side")[:7]
        git(self.work, "checkout", "-q", "main")
        git(self.work, "checkout", "-q", "-b", "prA", "main")
        self.write_main("%s/x-init4/ledger.md" % PS, LEDGER1 + "".join(
            "CHECKPOINT %s %s head=%s tests=1/1 gates=PASS next=n\n" % (b, t, hd) for b, t, hd in (
                ("4c", "4c.1", side), ("4d", "4d.1", "89abcde"), ("4e", "4e.1", git(self.work, "rev-parse", "main")[:7]))))
        head = commit_all(self.work, "w")
        git(self.work, "checkout", "-q", "main")
        git(self.work, "merge", "-q", "--no-ff", "-m", "M", "prA")
        m = git(self.work, "rev-parse", "main")
        # 4c's checkpoint head is not an ancestor and 4d's is unknown: only 4e is carried, and block 4e passes
        self.assertEqual(self.merged(merged_line(1, head, m, "init4", "4e"))[0], 0)
        h2, m2 = self.pr("init4", [])                               # the ledger holds no checkpoint at all
        before = self.log()
        self.assertEqual(self.merged(merged_line(2, h2, m2, "init4", "4c"))[0], 0)  # the named block is carried anyway
        self.assertNotEqual(self.log(), before)

    def test_merged_needs_base_branch(self):  # MG12: merged_errors reads the local base branch
        h, m = self.pr("release", [("6R", "6R.1")])
        git(self.work, "branch", "-q", "-m", "main", "trunk")
        before = self.log()
        code, out, err = self.merged(merged_line(1, h, m, "release", "6R"))
        self.assertEqual((code, out, self.log()), (1, "", before))
        self.assertIn("update main from the remote", err)


class MergedRecordFile(RecFx):
    def test_merged_record_file_kinds(self):  # MG11
        h, m = self.pr("release", [("6R", "6R.1")])
        line = merged_line(1, h, m, "release", "6R")
        path = os.path.join(self.folder(), "merged.md")
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("no newline")
        self.assertEqual(self.merged(line)[0], 1)                   # a malformed earlier line is never repaired
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("<!-- schema: merged-log/1 -->")                # no final newline
        code, out, err = self.merged(line)
        self.assertEqual(code, 1)
        self.assertIn("does not end with a newline", err)
        os.unlink(path)
        self.assertEqual(self.merged(line)[0], 1)                   # absent: refused


class ProgramSubprocess(Fx):
    """The oracle: ``python3 -m gates program ...`` in a subprocess, launched with ``sys.executable`` (rows PG9, PG10)."""

    def sub(self, *argv):
        env = dict(os.environ)
        env.pop("GIT_DIR", None)
        top = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        p = subprocess.run([sys.executable, "-m", "gates", "program", *argv], cwd=top, env=env, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, check=False)
        return p.returncode, p.stdout.decode("utf-8"), p.stderr.decode("utf-8")

    def test_every_subcommand_through_python_m_gates(self):  # PG9, PG10: one row per subcommand
        code, out, err = self.sub("create", NAME, "--streams", self.sf, "--decision", DEC, "--plan", "prog-plan",
                                  "--root", self.iw)
        self.assertEqual((code, out, err), (0, "push %s/integration\n" % NAME, ""))
        self.commit_iw()
        code, out, err = self.sub("status", NAME, "a", "--used", "2", "--root", self.iw)
        self.assertEqual((code, out, err), (0, "push %s/integration\n" % NAME, ""))
        code, out, err = self.sub("request", "new", NAME, "--from", "a", "--to", "b", "--file", "b/x.py", "--interface",
                                  "spec.md:1", "--need", "x", "--by", "a", "--root", self.iw)
        self.assertEqual((code, err), (0, ""))
        lines = out.splitlines()
        self.assertEqual(lines[0], "push %s/integration" % NAME)
        rid = lines[-1]
        code, out, err = self.sub("request", "set", NAME, rid, "--status", "accepted", "--by", "b", "--root", self.iw)
        self.assertEqual((code, out, err), (0, "push %s/integration\n" % NAME, ""))
        main = git(self.work, "rev-parse", "main")
        code, out, err = self.sub("sync-log", NAME, "--main", main, "--merged-main", "no", "--tests", "PASS",
                                  "--root", self.iw)
        self.assertEqual((code, out, err), (0, "push %s/integration\n" % NAME, ""))
        code, out, err = self.sub("merged", NAME, "--line", "hello", "--root", self.iw)   # a refusal exits 1
        self.assertEqual((code, out), (1, ""))
        self.assertTrue(err.startswith("program merged: "), err)
        code, out, err = self.sub("bogus")                                                # a usage error exits 2
        self.assertEqual((code, out), (2, ""))
        self.assertIn("usage: python3 -m gates program", err)


class GitCalls(Fx):
    """PG9, PG13, RT11: the git calls of every subcommand; none writes, pushes, fetches or switches branches."""

    BAD = {"push", "fetch", "remote", "checkout", "switch", "add", "commit", "merge", "reset", "stash", "pull"}

    def calls(self, fn):
        seen = []
        real = gitinfo._run

        def spy(root, name, args, *a, **kw):
            seen.append(list(args))
            return real(root, name, args, *a, **kw)
        with mock.patch("gates.lib.gitinfo._run", side_effect=spy):
            result = fn()
        return result, seen

    def test_no_write_git_calls_and_main_never_switched(self):  # PG9, PG13, RT11
        before = git(self.work, "rev-parse", "--abbrev-ref", "HEAD")
        (code, out, err), seen = self.calls(self.create)
        self.assertEqual(code, 0, err)
        self.commit_iw()
        (code, out, err), s2 = self.calls(lambda: run("program", "status", NAME, "a", "--used", "1", "--root", self.iw))
        self.assertEqual(code, 0, err)
        self.assertTrue(seen and s2)
        for args in seen + s2:
            self.assertFalse(self.BAD & set(args[:2]), args)
        self.assertEqual(git(self.work, "rev-parse", "--abbrev-ref", "HEAD"), before)

    def test_git_index_file_is_inherited_never_written(self):  # PG13
        index = os.path.join(self.tmp, "idx")
        with open(os.path.join(self.iw, ".git")) as fh:
            gitdir = fh.read().split("gitdir:")[1].strip()
        with open(os.path.join(gitdir, "index"), "rb") as fh, open(index, "wb") as out:
            out.write(fh.read())
        with open(index, "rb") as fh:
            before = fh.read()
        with mock.patch.dict(os.environ, {"GIT_INDEX_FILE": index}):
            code, out_, err = self.create()
        self.assertEqual(code, 0, err)
        with open(index, "rb") as fh:
            self.assertEqual(fh.read(), before)       # the tool never writes the index it inherits

if __name__ == "__main__":
    unittest.main()
