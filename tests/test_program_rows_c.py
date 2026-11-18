"""Task P2.2 part c: the rows of the input-domain table task-P2.2-domain.md that parts a and b left without a test, for
``program create`` and the argv/root forms (row ids in the comments). Expected values are written by hand from the plan
lines and the table; every git fixture is a ``make_repo`` repository."""
import os
from unittest import mock

from gates.lib import programs
from tests.helpers import E128, TOP, commit_all, git, minimal_config, root_forms, write_record
from tests.test_program_merged import merged_line
from tests.test_program_cli import (DEC, NAME, PG, PLAN, PS, Fx, breakdown_row, load_yaml, run, stream, streams_row)


def tree(root):
    """Every directory and file below ``root`` (the ``.git`` entry excepted), as sorted relative paths."""
    out = []
    for d, dirs, files in os.walk(root):
        dirs[:] = [x for x in dirs if x != ".git"]
        rel = os.path.relpath(d, root)
        out.append(rel + "/")
        out.extend(os.path.join(rel, f) for f in files if f != ".git")
    return sorted(out)


class CreateC(Fx):
    def refused(self, *needles, **kw):
        before = tree(self.iw)
        code, out, err = self.create(**kw)
        self.assertEqual((code, out), (1, ""), err)
        self.assertNotIn("Traceback", err)
        for n in needles:
            self.assertIn(n, err)
        self.assertEqual(tree(self.iw), before)           # CR19: nothing, not even an empty directory
        return err

    def test_status_cells_from_streams_file(self):  # CR5
        for purpose in ("", "a|b", "a\nb", "café", "a\\b", " a", "a "):
            with self.subTest(purpose):
                self.set_streams(streams_row(stream("a", ["a/"], purpose=purpose), stream("b", ["b/"], merge_order=2)))
                self.refused("purpose")
        self.set_streams(streams_row(stream("a", ["a/"], estimate=0), stream("b", ["b/"], merge_order=2,
                                                                              estimate=10 ** 599)))
        code, out, err = self.create()
        self.assertEqual((code, err), (0, ""))
        rows = programs.status_rows(open(os.path.join(self.folder(), "status.md"), encoding="utf-8").read())
        self.assertEqual([r["estimate"] for r in rows], ["0", "1" + "0" * 599])

    def test_create_passes_plans_to_breakdown_errors(self):  # CR10, D-Q2: a stream plan outside paths.plans is refused
        for plan in ("elsewhere/x.md", PG + "/x-a", "/abs/x.md", PG + "/../x.md"):
            with self.subTest(plan):
                self.set_streams(streams_row(stream("a", ["a/"], plan=plan), stream("b", ["b/"], merge_order=2)))
                self.refused()

    def test_create_invalid_names(self):  # CR11, PG6
        for name in ("PROG", "x", "20261301-x", "20261101-", "20261101-X", "20261101-a/b", "20261101-../x", "",
                     "20261101-" + "x" * 4301, "20261101-x\n", "20261101-café", " 20261101-x"):
            with self.subTest(name[:30]):
                before = tree(self.iw)
                code, out, err = run("program", "create", name, "--streams", self.sf, "--decision", DEC, "--plan", PLAN,
                                     "--root", self.iw)
                self.assertEqual((code, out), (1, ""))
                if len(name) < 100:                      # a 4301 character slug is a valid name (P2.1): the branch rule
                    self.assertIn("program name", err)
                self.assertNotIn("Traceback", err)
                self.assertEqual(tree(self.iw), before)

    def test_create_reads_decisions_from_root(self):  # CR14
        other = "DEC-20261105-aaaa"
        self.decision(other, root=self.work)                      # only in the main checkout's working tree
        self.refused("program-create", decision=other)
        self.decision(other, root=self.iw)                        # in the integration worktree, untracked: read
        self.assertEqual(self.create(decision=other)[0], 0)

    def test_create_streams_file_kinds(self):  # CR15
        sf = self.sf
        for name, data in (("yaml error", b"a: [\n"), ("empty", b""), ("list", b"- a\n"), ("not utf-8", b"\xff\xfe\x00"),
                           ("scalar", b"x\n")):
            with self.subTest(name):
                with open(sf, "wb") as fh:
                    fh.write(data)
                self.refused("streams file")
        os.unlink(sf)
        self.refused("streams file", "cannot read")                # missing
        os.mkdir(sf)
        self.refused("not a regular file")                         # a directory

    def test_create_streams_file_with_bom_or_crlf(self):  # CR15: yamlsub refuses a CR and a BOM; the refusal names the file
        with open(self.sf, "rb") as fh:
            data = fh.read()
        for name, new in (("crlf", data.replace(b"\n", b"\r\n")), ("bom", b"\xef\xbb\xbf" + data)):
            with self.subTest(name):
                with open(self.sf, "wb") as fh:
                    fh.write(new)
                self.refused()                                  # CR names the file; a BOM spoils the first key

    def test_create_refusal_leaves_no_trace(self):  # CR19: each stage S1-S8, the branch rule and the worktree rule
        self.refused(decision="DEC-20261105-zzzz")                             # S7
        self.refused(plan="nope")                                              # S1
        self.refused(root=self.work)                                           # branch rule
        self.set_streams(streams_row(stream("a", ["a/"]), stream("b", ["a/"], merge_order=2)))
        self.refused()                                                         # S8
        self.set_streams(streams_row())
        write_record(self.iw, "%s/%s/breakdown.yml" % (PS, PLAN), breakdown_row(max_concurrent=99))
        self.refused("max_concurrent")                                         # S3
        write_record(self.iw, "%s/%s/breakdown.yml" % (PS, PLAN), breakdown_row(plan="other"))
        self.refused()                                                         # S2
        write_record(self.iw, "%s/%s/breakdown.yml" % (PS, PLAN), breakdown_row())
        os.makedirs(os.path.join(self.iw, ".strict-delivery/state/programs", NAME))
        self.refused("already exists")                                         # S6: the folder is there, listed above

    def test_create_during_merge_in_progress(self):  # CR21: not checked; the files are written
        gitdir = git(self.iw, "rev-parse", "--absolute-git-dir")
        with open(os.path.join(gitdir, "MERGE_HEAD"), "w", encoding="utf-8") as fh:
            fh.write(git(self.iw, "rev-parse", "HEAD") + "\n")
        with open(os.path.join(self.iw, "dirty.txt"), "w", encoding="utf-8") as fh:
            fh.write("x\n")
        code, out, err = self.create()
        self.assertEqual((code, err), (0, ""))
        self.assertTrue(os.path.isfile(os.path.join(self.folder(), "merged.md")))

    def test_create_in_hook_environment(self):  # CR23, PG13
        idx = os.path.join(self.tmp, "index-copy")
        with open(git(self.iw, "rev-parse", "--absolute-git-dir") + "/index", "rb") as src, open(idx, "wb") as dst:
            dst.write(src.read())
        with mock.patch.dict(os.environ, {"GIT_INDEX_FILE": idx}):
            code, out, err = self.create()
        self.assertEqual((code, err), (0, ""))

    def test_create_git_states(self):  # CR22: a base branch that does not exist locally is a refusal
        cfg = dict(minimal_config(), base_branch="trunk")
        write_record(self.iw, ".strict-delivery/config.yml", cfg)
        self.refused("ls-tree")

    def test_create_in_shallow_clone(self):  # CR22: reads local objects only
        clone = os.path.join(self.tmp, "c", "sh")
        os.makedirs(os.path.dirname(clone))
        git(self.tmp, "clone", "-q", "--depth", "1", "file://" + self.work, clone)
        git(clone, "config", "user.email", "f@example.invalid")
        git(clone, "config", "user.name", "F")
        iw = os.path.join(self.tmp, "c", "w", NAME, "integration")
        git(clone, "worktree", "add", "-q", "-b", NAME + "/integration", iw, "origin/main")
        code, out, err = self.create(root=iw)
        self.assertEqual((code, err), (0, ""))

    def test_breakdown_limit_types(self):  # CL6
        for field in ("max_concurrent", "max_depth"):
            for v in (0, True, "2", 1.5, None, -1, 10 ** 999):
                with self.subTest(field, v=repr(v)[:20]):
                    path = write_record(self.iw, "%s/%s/breakdown.yml" % (PS, PLAN),
                                        breakdown_row(**{field: 7 if v == 1.5 else v}))
                    if v == 1.5:                                  # the emitter has no float: edit the text
                        with open(path, encoding="utf-8") as fh:
                            text = fh.read()
                        with open(path, "w", encoding="utf-8") as fh:
                            fh.write(text.replace("%s: 7" % field, "%s: 1.5" % field))
                    self.refused(field if v != 10 ** 999 else "")

    def test_create_duplicate_owns_items(self):  # CA5: a duplicate item is a set member once
        self.set_streams(streams_row(stream("a", ["a/", "a/"]), stream("b", ["b/"], merge_order=2)))
        code, out, err = self.create()
        self.assertEqual(code, 0, err)

    def test_create_done_not_compared(self):  # CA15
        with open(os.path.join(self.iw, PG, PLAN + ".md"), "a", encoding="utf-8") as fh:
            fh.write("\n## Block C1: third\n\n### Task C1.1: z\n")
        write_record(self.iw, "%s/%s/breakdown.yml" % (PS, PLAN), breakdown_row(done=["C1.1"]))
        code, out, err = self.create()                              # the streams file has no done: nothing to disagree with
        self.assertEqual((code, err), (0, ""))

    def test_create_reads_each_input_once(self):  # CP6
        seen = []
        real = programs._fs_text

        def spy(root, rel, *a):
            seen.append(rel)
            return real(root, rel, *a)

        with mock.patch.object(programs, "_fs_text", spy):
            self.assertEqual(self.create()[0], 0)
        self.assertEqual([r for r in seen if r.endswith(PLAN + ".md")], ["%s/%s.md" % (PG, PLAN)])

    def test_worktrees_forms_through_streams_errors(self):  # RT5
        for w in ("w", "../../w", "/abs/w", "./../w", "../w/", "..//w", "../w/../v", "..", ".", "", "../w\n", "../w" * 1500):
            with self.subTest(w[:20]):
                row = streams_row()
                row["worktrees"] = w
                self.set_streams(row)
                self.refused()

    def test_root_forms(self):  # RT8
        for name, path, verdict in root_forms(self.tmp, self.work):
            if verdict == "ok":
                continue
            with self.subTest(name):
                code, out, err = self.create(root=path)
                self.assertEqual((code, out), (1, ""))
                self.assertIn(TOP if verdict == TOP else E128, err)

    def test_later_subcommands_root_rule(self):  # RT9, PG3, PG6: the branch rule applies to every subcommand
        for sub in (("status", NAME, "a", "--used", "1"), ("request", "new", NAME, "--from", "a", "--to", "b", "--file",
                                                           "b/x", "--interface", "s.md:1", "--need", "x", "--by", "a"),
                    ("request", "set", NAME, "R-20261101-aaaa", "--status", "accepted", "--by", "a"),
                    ("sync-log", NAME, "--main", "1" * 40, "--merged-main", "no", "--tests", "PASS"),
                    ("merged", NAME, "--line", merged_line(1, "1" * 40, "2" * 40, "a", "A1"))):
            with self.subTest(sub[0] + sub[1][:4]):
                code, out, err = run("program", *sub, "--root", self.work)
                self.assertEqual((code, out), (1, ""))
                self.assertIn("integration", err)

    def test_subcommand_forms(self):  # PG3
        for argv in ((), ("CREATE", NAME), ("nope",), ("request",), ("request", "nope", NAME), ("create",),
                     ("create", NAME, "extra"), ("status", NAME)):
            with self.subTest(argv):
                code, out, err = run("program", *argv)
                self.assertEqual((code, out), (2, ""))
                self.assertNotIn("Traceback", err)
        code, out, err = run("program", "create", "--help")
        self.assertIn(code, (0, 2))
        self.assertNotIn("Traceback", err)

    def test_refusal_lines_are_safe_text(self):  # PG11
        write_record(self.iw, "%s/%s/breakdown.yml" % (PS, PLAN), breakdown_row(max_concurrent=99, max_depth=99))
        code, out, err = self.create()
        lines = err.splitlines()
        self.assertEqual(code, 1)
        self.assertGreaterEqual(len(lines), 2)                    # one line per reason
        self.assertTrue(all(l.startswith("program create: ") for l in lines), err)
        code, out, err = run("program", "create", "20261101-x\x1b[31m\x07", "--streams", self.sf, "--decision", DEC,
                             "--plan", PLAN, "--root", self.iw)
        self.assertEqual(code, 1)
        self.assertTrue(all(ord(c) >= 0x20 or c == "\n" for c in err), repr(err))

    def test_create_under_colour_and_abbrev_config(self):  # PG14: create reads git under hostile git config
        for k, v in (("color.ui", "always"), ("color.diff", "always"), ("core.abbrev", "7")):
            git(self.work, "config", k, v)
        code, out, err = self.create()
        self.assertEqual((code, out, err), (0, "push %s/integration\n" % NAME, ""))
        self.assertEqual(self.read("sync-log.md"), "<!-- schema: sync-log/1 -->\n")
        self.assertEqual(load_yaml(os.path.join(self.folder(), "streams.yml")), streams_row())


class StackedC(Fx):
    """Three streams, ``c`` stacked on ``a``; ``a`` has the sub-blocks A1 and A2 (CA18, CA19)."""

    def setUp(self):
        super().setUp()
        self.write_main(PG + "/%s.md" % PLAN, "".join("## Block %s: x\n\n### Task %s.1: x\n\n" % (b, b)
                                                      for b in ("A1", "A2", "B1", "C1")))
        commit_all(self.work, "plan 4")
        git(self.iw, "merge", "-q", "main")
        self.set_streams(streams_row(stream("a", ["a/"]), stream("b", ["b/"], merge_order=2),
                                     stream("c", ["c/"], merge_order=3, stacked_on="a")))

    def bd(self, *edges):
        sts = [{"id": "a", "paths": ["a/"], "tasks": ["A1.1", "A2.1"], "unblock": "at program start"},
               {"id": "b", "paths": ["b/"], "tasks": ["B1.1"], "unblock": "at program start"},
               {"id": "c", "paths": ["c/"], "tasks": ["C1.1"], "unblock": "at program start"}]
        write_record(self.iw, "%s/%s/breakdown.yml" % (PS, PLAN), breakdown_row(
            max_concurrent=3, streams=sts, edges=[{"from": f, "to": t} for f, t in edges],
            groups=[{"id": "g1", "tasks": ["A1.1", "A2.1"]}, {"id": "g2", "tasks": ["B1.1"]}, {"id": "g3", "tasks": ["C1.1"]}]))

    def test_create_stacked_order_transitive(self):  # CA18: a -> b -> c orders merged:c/C1 after merged:a
        self.bd(("A1.1", "B1.1"), ("A2.1", "B1.1"), ("B1.1", "C1.1"))
        code, out, err = self.create()
        self.assertEqual((code, err), (0, ""))

    def test_create_stacked_needs_all_parent_subblocks(self):  # CA19: one sub-block of a is not merged:a
        self.bd(("A1.1", "C1.1"))
        code, out, err = self.create()
        self.assertEqual((code, out), (1, ""))
        self.assertIn("stacked_on", err)
        self.assertFalse(os.path.exists(self.folder()))
        self.bd(("A1.1", "C1.1"), ("A2.1", "C1.1"))
        self.assertEqual(self.create()[0], 0)
