"""Task P2.2 part d: the rows of task-P2.2-domain.md that parts a-c left without a test (row ids in the comments): RT6,
RN7, RN14, RN18, CR22, SL9, PG6 (every subcommand), ST11 (a 4 MB page) and PE20 (a 20 MB text). Expected values are
written by hand; every git fixture is a ``make_repo`` repository or a clone of one."""
import os
import time
import unittest
from unittest import mock

from gates.lib import breakdown
from tests.helpers import git
from tests.test_program_cli import NAME, PG, Fx, load_yaml, run
from tests.test_program_merged import PLAN_REC, RecFx
from tests.test_program_rows_c import tree
from tests.test_program_rows_c2 import REQ, AfterC


class MainWorktreeBase(Fx):
    """RT6: the main worktree is the parent of the common git directory; a layout with no main worktree is refused."""

    def clone_iw(self, name, *clone_flags):
        dest = os.path.join(self.tmp, name)
        git(self.tmp, "clone", "-q", *clone_flags, "file://" + self.work, dest)
        git(dest, "config", "user.email", "f@example.invalid")
        git(dest, "config", "user.name", "F")
        return dest

    def test_main_worktree_base_forms(self):  # RT6
        # plain repository (RT1) and a linked main (this fixture's iw is a linked worktree): passes
        self.assertEqual(self.create()[0], 0)
        # a clone made with --separate-git-dir: the common dir is not named .git, the worktree rule has no base
        sep = os.path.join(self.tmp, "sep.git")
        dest = self.clone_iw("sepclone", "--separate-git-dir", sep)
        iw = os.path.join(self.tmp, "sw", NAME, "integration")
        git(dest, "worktree", "add", "-q", "-b", NAME + "/integration", iw, "origin/main")
        code, out, err = self.create(root=iw)
        self.assertEqual((code, out), (1, ""), err)
        self.assertIn("no main worktree", err)
        self.assertNotIn("Traceback", err)
        self.assertFalse(os.path.exists(os.path.join(iw, ".strict-delivery/state/programs", NAME)))
        # a bare repository with a worktree
        bare = os.path.join(self.tmp, "bare.git")
        git(self.tmp, "clone", "-q", "--bare", "file://" + self.work, bare)
        iw2 = os.path.join(self.tmp, "bw", NAME, "integration")
        git(bare, "worktree", "add", "-q", iw2, NAME + "/integration")
        code, out, err = self.create(root=iw2)
        self.assertEqual((code, out), (1, ""), err)
        self.assertIn("no main worktree", err)
        self.assertFalse(os.path.exists(os.path.join(iw2, ".strict-delivery/state/programs", NAME)))

    def test_main_worktree_base_ignores_git_dir_env(self):  # RT6: GIT_DIR is cleared by gitinfo._env
        with mock.patch.dict(os.environ, {"GIT_DIR": os.path.join(self.tmp, "nowhere")}):
            code, out, err = self.create()
        self.assertEqual((code, err), (0, ""))


def unborn(iw):
    """Make the branch of the worktree ``iw`` an unborn branch (HEAD names it, no commit)."""
    git(iw, "checkout", "-q", "--detach")
    git(iw, "branch", "-q", "-D", NAME + "/integration")
    git(iw, "symbolic-ref", "HEAD", "refs/heads/%s/integration" % NAME)


class UnbornHead(AfterC):
    """RN14, CR22, SL9: a worktree whose branch has no commit."""

    def orphan(self):
        unborn(self.iw)

    def test_request_raised_at_head(self):  # RN14: the sha is HEAD; an unborn HEAD is a refusal
        rid = self.new_request()
        self.assertEqual(load_yaml(self.request_file(rid))["raised_at"]["sha"], git(self.iw, "rev-parse", "HEAD"))
        self.commit_iw()
        self.orphan()
        before = tree(self.iw)
        code, out, err = self.cli("request new", *REQ)
        self.assertEqual((code, out), (1, ""), err)
        self.assertIn("rev-parse HEAD failed", err)
        self.assertEqual(tree(self.iw), before)

    def test_sync_unborn_head(self):  # SL9
        self.orphan()
        before = tree(self.iw)
        code, out, err = self.cli("sync-log", "--main", git(self.work, "rev-parse", "main"), "--merged-main", "no",
                                  "--tests", "PASS")
        self.assertEqual((code, out), (1, ""), err)
        self.assertIn("rev-parse HEAD failed", err)
        self.assertEqual(tree(self.iw), before)


class CreateUnborn(Fx):
    def test_create_unborn_head(self):  # CR22: an unborn branch and a HEAD without a first commit
        unborn(self.iw)
        code, out, err = self.create()
        self.assertEqual(code, 1, err)
        self.assertIn("ls-tree failed", err)                            # the base branch has no tree to read
        self.assertFalse(os.path.exists(self.folder()))
        fresh = os.path.join(self.tmp, "fresh")
        os.mkdir(fresh)
        git(fresh, "init", "-q", "-b", NAME + "/integration")
        code, out, err = self.create(root=fresh)
        self.assertEqual((code, out), (1, ""), err)
        self.assertIn("config.yml: missing", err)


class NameForms(AfterC):
    BAD = ("x", "20261301-x", "20261101-", "20261101-X", "20261101-a/b", "", "a" * 4301, "20261101-x\0", "20261101-x\n",
           "20261101-é", "20261101-x y", "20261101-../x")

    def argv_of(self):
        line = "MERGED pr=1 head=%s merge=%s merged_by=u at=2026-11-01T10:00:00Z final=no stream=a block=A1 approval=host"
        return {"status": ("a", "--used", "1"), "request new": REQ,
                "request set": ("R-20261101-aaaa", "--status", "closed", "--by", "a"),
                "sync-log": ("--main", "a" * 40, "--merged-main", "no", "--tests", "PASS"),
                "merged": ("--line", line % ("a" * 40, "b" * 40))}

    def test_program_name_forms_refused(self):  # PG6: every subcommand but create (create: test_create_invalid_names)
        self.commit_iw()
        for sub, argv in self.argv_of().items():
            for name in self.BAD:
                with self.subTest(sub, name=name[:24]):
                    branch = name + "/integration"
                    made = False
                    if name and "\0" not in name and "\n" not in name and " " not in name and ".." not in name \
                            and name[0] != "/" and not name.endswith("/") and len(name) < 200 and name.isascii() \
                            and name.lower() != NAME:
                        git(self.iw, "checkout", "-q", "-B", branch)       # a branch of that exact name exists
                        made = True
                    before = tree(self.iw)
                    sub_argv = sub.split(" ")
                    code, out, err = run("program", *sub_argv, name, *argv, "--root", self.iw)
                    self.assertEqual((code, out), (1, ""), err)
                    self.assertNotIn("Traceback", err)
                    self.assertTrue(err.startswith("program %s: " % sub), err)
                    if sub == "status":
                        self.assertIn("program name", err)
                    self.assertEqual(tree(self.iw), before)
                    if made:
                        git(self.iw, "checkout", "-q", NAME + "/integration")
            # a valid name with no such branch: the branch rule
            code, out, err = run("program", *sub.split(" "), "20261102-y", *argv, "--root", self.iw)
            self.assertEqual((code, out), (1, ""), err)
            self.assertIn("program runs only on", err)


class RequestChecksBeforeIo(AfterC):
    def test_request_new_checks_before_io(self):  # RN18: every bad flag is refused before any git or file call
        def boom(*a, **k):
            raise AssertionError("io before the argv check")

        def argv(**over):
            flags = {"--from": ["a"], "--to": ["b"], "--file": ["b/x.py"], "--interface": ["spec.md:1"], "--need": ["x"],
                     "--by": ["a"]}
            flags.update(over)
            return [x for f, vs in flags.items() for v in vs for x in (f, v)]

        bad = [{"--from": [""]}, {"--from": [" a"]}, {"--from": ["a", "a"]}, {"--to": ["b\n"]}, {"--to": ["b", "b"]},
               {"--file": ["b/"]}, {"--file": ["/b"]}, {"--file": ["b/x.py", "b/x.py"]}, {"--file": ["b\\x"]},
               {"--interface": ["caf\u00e9"]}, {"--interface": ["a", "a"]}, {"--need": ["x\0"]}, {"--need": ["x", "y"]},
               {"--by": [" "]}, {"--by": ["a", "a"]}]
        with mock.patch("gates.lib.gitinfo._run", side_effect=boom), mock.patch("gates.lib.config.load", side_effect=boom), \
                mock.patch("gates.lib.programs.load_program", side_effect=boom), mock.patch("builtins.open", side_effect=boom):
            for over in bad:
                with self.subTest(over):
                    code, out, err = self.cli("request new", *argv(**over))
                    self.assertEqual((code, out), (1, ""), err)
                    self.assertNotIn("Traceback", err)
        self.assertFalse(os.path.exists(os.path.join(self.folder(), "requests")))


class ResidualRequests(RecFx):
    """RN7: ``--to residual`` is judged by ``request_errors`` with the breakdown read from the working tree."""

    def req(self, path):
        return run("program", "request", "new", NAME, "--from", "release", "--to", "residual", "--file", path,
                   "--interface", "spec.md:1", "--need", "x", "--by", "release", "--root", self.iw)

    def test_request_new_to_residual(self):  # RN7
        before = tree(self.iw)
        for path in ("docs/free.md",                                     # no stream covers it
                     "gates/reg.py",                                     # covered by one stream in one window only
                     ".strict-delivery/state/plans/x-residual/n.md"):    # residual's own workspace
            with self.subTest(path):
                code, out, err = self.req(path)
                self.assertEqual(code, 0, err)
        for path in (".gitignore",                                       # two chained windows cover it for the whole program
                     "%s/%s.md" % (PG, PLAN_REC),                        # the program plan's file
                     ".strict-delivery/state/plans/%s/n.md" % PLAN_REC,  # its workspace
                     ".strict-delivery/state/plans/x-package/n.md"):     # another stream's implicit plan workspace
            with self.subTest(path):
                mark = tree(self.iw)
                code, out, err = self.req(path)
                self.assertEqual((code, out), (1, ""), err)
                self.assertNotIn("Traceback", err)
                self.assertIn("to_stream residual does not own " + path, err)
                self.assertEqual(tree(self.iw), mark)
        self.assertNotEqual(tree(self.iw), before)


class BigInputs(AfterC):
    def test_status_4mb_page(self):  # ST11, ST1, ST14: a 4 MB page: one row rewritten, every other byte kept
        with open(self.page(), encoding="utf-8") as fh:
            good = fh.read()
        big = good + ("x" * 1023 + "\n") * 4096
        with open(self.page(), "w", encoding="utf-8", newline="") as fh:
            fh.write(big)
        self.assertGreaterEqual(len(big), 4 * 1024 * 1024)
        code, out, err = self.cli("status", "a", "--used", "1")
        self.assertEqual(code, 0, err)
        with open(self.page(), encoding="utf-8", newline="") as fh:
            after = fh.read()
        self.assertTrue(after.endswith(big[len(good):]))                  # the 4 MB tail is kept byte for byte
        self.assertNotEqual(after, big)
        self.assertEqual(len(after.split("\n")), len(big.split("\n")))     # one row changed, no line added or lost


class PlanText20Mb(unittest.TestCase):
    def test_plan_errors_20mb_text(self):  # PE20: a 20 MB text is linear (built in a temp dir, never committed)
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "big.md")
            with open(path, "w", encoding="utf-8", newline="") as fh:
                fh.write("## Block B1:\n### Task B1.1: x\n")
                for _ in range(20 * 1024):
                    fh.write(("prose " * 200 + "\n") * 17)
            self.assertGreaterEqual(os.path.getsize(path), 20 * 1024 * 1024)
            with open(path, encoding="utf-8", newline="") as fh:
                text = fh.read()
        t0 = time.time()
        got = breakdown.plan_errors(text, {"streams": [], "done": []})
        self.assertLess(time.time() - t0, 60)
        self.assertEqual([s for s, _ in got if s.startswith("outline.") and not s.startswith(("outline.task", "outline.unplanned"))], [])


if __name__ == "__main__":
    unittest.main()
