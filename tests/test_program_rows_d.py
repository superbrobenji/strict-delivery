"""Task P2.2 part d: the rows of task-P2.2-domain.md that parts a-c left without a test (row ids in the comments): RT6,
RN7, RN14, RN18, CR22, SL9, PG6 (every subcommand), ST11 (a 4 MB page) and PE20 (a 20 MB text). Expected values are
written by hand; every git fixture is a ``make_repo`` repository or a clone of one."""
import builtins
import errno
import os
import stat
import sys
import tempfile
import time
import unittest
from unittest import mock

from gates.lib import breakdown, ids
from gates.tools import program_cli
from tests.helpers import commit_all, git, write_record
from tests.test_program_cli import DEC, NAME, PG, Fx, load_yaml, run
from tests.test_program_merged import PLAN_REC, RecFx, merged_line
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


def only_in(fn_name, real, fake):
    """A stand-in for ``real`` that acts as ``fake`` when the caller is the function ``fn_name`` of program_cli and as
    ``real`` for every other caller (so the rest of the run is the production path)."""
    def wrapper(*a, **k):
        f = sys._getframe(1)
        if f.f_code.co_name == fn_name and f.f_globals.get("__name__") == program_cli.__name__:
            return fake(*a, **k)
        return real(*a, **k)
    return wrapper


def raising(exc):
    def fake(*a, **k):
        raise exc
    return fake


class WriteBranches(AfterC):
    """The OSError branches of ``program_cli._replace`` (status, sync-log, request set) and ``_new_file`` (request
    new, create): each is a named refusal, exit 1, and leaves no temporary or partial file (PG12)."""

    def leftovers(self):
        return sorted(f for d, _, fs in os.walk(self.folder()) for f in fs if f.startswith(".program."))

    def status(self):
        return self.cli("status", "a", "--used", "1")

    def refused_with(self, patches, needle):
        with open(self.page(), "rb") as fh:
            before = fh.read()
        with patches:
            code, out, err = self.status()
        self.assertEqual((code, out), (1, ""), err)
        self.assertIn(needle, err)
        self.assertEqual(self.leftovers(), [])
        with open(self.page(), "rb") as fh:
            self.assertEqual(fh.read(), before)

    def test_replace_lstat_fails(self):  # PG12: the file vanishes or cannot be read between the load and the rewrite
        eacces = PermissionError(errno.EACCES, "Permission denied")
        self.refused_with(mock.patch.object(os, "lstat", only_in("_replace", os.lstat, raising(eacces))),
                          "status.md: cannot read (Permission denied)")

    def test_replace_refuses_a_non_regular_file(self):  # PG12
        as_dir = lambda p: os.lstat(os.path.dirname(p))
        self.refused_with(mock.patch.object(os, "lstat", only_in("_replace", os.lstat, as_dir)),
                          "status.md: not a regular file")

    def test_replace_mkstemp_fails(self):  # PG12
        eacces = PermissionError(errno.EACCES, "Permission denied")
        self.refused_with(mock.patch.object(tempfile, "mkstemp", only_in("_replace", tempfile.mkstemp, raising(eacces))),
                          "status.md: cannot write (Permission denied)")

    def test_replace_fails_after_the_temp_file_exists(self):  # PG12: the temp file is removed on every failure path
        eacces = PermissionError(errno.EACCES, "Permission denied")
        self.refused_with(mock.patch.object(os, "replace", only_in("_replace", os.replace, raising(eacces))),
                          "status.md: cannot write (Permission denied)")
        nospace = OSError(errno.ENOSPC, "No space left on device")
        self.refused_with(mock.patch.object(os, "fsync", only_in("_replace", os.fsync, raising(nospace))),
                          "status.md: cannot write (No space left on device)")

    def test_replace_keeps_the_mode_and_syncs(self):  # PG12
        os.chmod(self.page(), 0o640)
        calls = []
        real = os.fsync
        with mock.patch.object(os, "fsync", only_in("_replace", real, lambda fd: calls.append(fd) or real(fd))):
            self.assertEqual(self.status()[0], 0)
        self.assertEqual(stat.S_IMODE(os.stat(self.page()).st_mode), 0o640)
        self.assertEqual(len(calls), 1)

    def test_new_file_exists(self):  # PG12: a file that appeared after the mint is never overwritten
        real = ids.mint
        made = []

        def mint(*a, **k):
            rid = real(*a, **k)
            path = os.path.join(self.folder(), "requests", rid + ".yml")
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("other\n")
            made.append(path)
            return rid

        with mock.patch.object(ids, "mint", mint):
            code, out, err = self.cli("request new", *REQ)
        self.assertEqual((code, out), (1, ""), err)
        self.assertIn(".yml: already exists", err)
        with open(made[0], encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "other\n")

    def test_new_file_create_and_write_fail(self):  # PG12
        eacces = PermissionError(errno.EACCES, "Permission denied")
        with mock.patch.object(builtins, "open", only_in("_new_file", builtins.open, raising(eacces))):
            code, out, err = self.cli("request new", *REQ)
        self.assertEqual((code, out), (1, ""), err)
        self.assertIn(".yml: cannot create (Permission denied)", err)
        nospace = OSError(errno.ENOSPC, "No space left on device")
        with mock.patch.object(os, "fsync", only_in("_new_file", os.fsync, raising(nospace))):
            code, out, err = self.cli("request new", *REQ)
        self.assertEqual((code, out), (1, ""), err)
        self.assertIn(".yml: cannot write (No space left on device)", err)
        reqs = os.path.join(self.folder(), "requests")
        self.assertEqual(os.listdir(reqs) if os.path.isdir(reqs) else [], [])      # no partial file
        calls = []
        real = os.fsync
        with mock.patch.object(os, "fsync", only_in("_new_file", real, lambda fd: calls.append(fd) or real(fd))):
            self.assertEqual(self.cli("request new", *REQ)[0], 0)
        self.assertEqual(len(calls), 1)

    def test_request_new_by_stream_ids_that_are_not_text(self):  # RN9: a stream id that is not a str is no stream
        path = os.path.join(self.folder(), "streams.yml")
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        self.assertEqual(text.count("- id: b\n"), 1, text)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text.replace("- id: b\n", "- id: [b]\n"))
        code, out, err = self.cli("request new", *REQ[:2], "--to", "a", *REQ[4:])
        self.assertNotIn("Traceback", err)
        self.assertEqual(code, 1, err)


class IdRegisters(AfterC):
    def spy_seen(self):
        seen = []
        real = program_cli.ids.mint

        def spy(fmt, existing, today, rng):
            seen.append(set(existing))
            return real(fmt, existing, today, rng)

        with mock.patch.object(program_cli.ids, "mint", spy):
            self.new_request()
        return seen[0]

    def test_request_ids_include_findings_and_claims(self):  # RN11: every register's ids are given to the mint
        write_record(self.iw, ".strict-delivery/state/findings/F-20261118-aaaa.yml",
                     {"schema": "finding/1", "id": "F-20261118-aaaa"})
        write_record(self.iw, ".strict-delivery/state/claims/c.yml",
                     {"schema": "claims/1", "claims": [{"id": "CLAIM-1"}, {"id": ["not", "text"]}, {"id": 7}]})
        seen = self.spy_seen()
        self.assertLessEqual({DEC, "F-20261118-aaaa", "CLAIM-1"}, seen)

    def test_request_ids_skip_ids_that_are_not_text(self):  # RN11: a register entry whose id is no str is skipped
        write_record(self.iw, ".strict-delivery/state/findings/F-20261118-bbbb.yml",
                     {"schema": "finding/1", "id": ["not", "text"]})
        self.assertIn(DEC, self.spy_seen())


class NoProgramFolder(Fx):
    """RN13 and its class: every subcommand but create on a program that was never created."""

    def test_no_streams_file(self):  # RN13
        rel = ".strict-delivery/state/programs/%s/streams.yml: missing" % NAME
        sha = "a" * 40
        line = ("MERGED pr=1 head=%s merge=%s merged_by=u at=2026-11-01T10:00:00Z final=no stream=a block=A1 approval=host"
                % (sha, sha))
        for sub, argv in (("status", ("a", "--used", "1")), ("request new", REQ),
                          ("request set", ("R-20261101-aaaa", "--status", "accepted", "--by", "b")),
                          ("sync-log", ("--main", sha, "--merged-main", "no", "--tests", "PASS")),
                          ("merged", ("--line", line))):
            with self.subTest(sub):
                code, out, err = run("program", *sub.split(" "), NAME, *argv, "--root", self.iw)
                self.assertEqual((code, out), (1, ""), err)
                self.assertEqual(err, "program %s: %s\n" % (sub, rel))
        self.assertFalse(os.path.exists(os.path.join(self.iw, ".strict-delivery/state/programs", NAME)))


class ColourSet(AfterC):
    """PG14 for request set --commit and sync-log: git colour and abbreviation settings change nothing."""

    def setUp(self):
        super().setUp()
        for k, v in (("color.ui", "always"), ("color.diff", "always"), ("core.abbrev", "7")):
            git(self.work, "config", k, v)

    def test_request_set_commit_and_sync_log(self):  # PG14
        rid = self.new_request()
        self.assertEqual(self.cli("request set", rid, "--status", "accepted", "--by", "b")[0], 0)
        git(self.work, "checkout", "-q", "-b", NAME + "/b/main", "main")
        self.write_main("b/x.py", "x = 1\n")
        sha = commit_all(self.work, "b work")
        git(self.work, "checkout", "-q", "main")
        code, out, err = self.cli("request set", rid, "--status", "done", "--by", "b", "--commit", sha)
        self.assertEqual((code, out, err), (0, "push %s/integration\n" % NAME, ""))
        self.assertEqual(len(sha), 40)
        self.assertEqual(load_yaml(self.request_file(rid))["resolution"]["commits"], [sha])
        self.assertEqual(load_yaml(self.request_file(rid))["resolution"]["at"], git(self.iw, "rev-parse", "HEAD"))
        main = git(self.work, "rev-parse", "main")
        code, out, err = self.cli("sync-log", "--main", main, "--merged-main", "no", "--tests", "PASS")
        self.assertEqual((code, out, err), (0, "push %s/integration\n" % NAME, ""))
        with open(os.path.join(self.folder(), "sync-log.md"), encoding="utf-8") as fh:
            last = fh.read().splitlines()[-1]
        self.assertEqual(last, "SYNC integration=%s main=%s merged-main=no updated=none combined=none tests=PASS questions=none"
                         % (git(self.iw, "rev-parse", "HEAD"), main))
        self.assertEqual(len(git(self.iw, "rev-parse", "HEAD")), 40)


class ColourMerged(RecFx):
    def test_merged_under_colour_config(self):  # PG14
        for k, v in (("color.ui", "always"), ("color.diff", "always"), ("core.abbrev", "7")):
            git(self.work, "config", k, v)
        head, m = self.pr("release", [("6R", "6R.1")])
        line = merged_line(1, head, m, "release", "6R")
        code, out, err = self.merged(line)
        self.assertEqual((code, out, err), (0, "push %s/integration\n" % NAME, ""))
        self.assertEqual(self.log().splitlines(), ["<!-- schema: merged-log/1 -->", line])


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
