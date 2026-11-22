"""Task 5a.1: ``gates/tools/context_cli.py`` (plan 5109-5193; domain table 5a.1 with its binding controller
decisions D-Q1 (a) (a path ``gitinfo.blob_ids`` cannot take is exit 2), D-Q3, D-Q4, D-Q5). Expected values are written
by hand: blob ids from git's own rule (``sha1("blob <n>\\0" + bytes)``; the autocrlf literal is measured with git)."""
import contextlib
import hashlib
import io
import os
import re
import subprocess
import sys
import unittest

from gates.lib import migrations
from gates.tools import context_cli
from tests.helpers import GitIsolatedTestCase, git, make_repo, within, write_record

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CTX_TAG = "context/%d" % migrations.current_version("context")  # fixtures take the tag from the schema (plan P:32)
PLAN_PATH = ".strict-delivery/state/plans/p/handoff.md"
INFORCE = ".strict-delivery/state/decisions/in-force.md"
BLOB_RE = re.compile(r"blob [0-9a-f]{40} --")

HANDOFF = ("---\nschema: handoff/1\nplan: p\nspec:\n  - s.md\nbranch: b\nhead: aaaaaaa\nbase: bbbbbbb\nledger: l.md\n"
           "resume: r\nblock: b\nnext_task: t\nfindings_in_flight: []\nopen_decisions: []\nrulings: 0\ngrant: null\n"
           "live_subagents: []\nrole: controller\nbudget:\n  tokens: 1\n  minutes: 1\nworktrees:\n  - path: w\n"
           "    branch: b\n    head: aaaaaaa\n    porcelain: \"\"\nskills:\n  - s\nledger_from: 2\nbatch_cut: null\n"
           "questions: []\n%s---\nbody\n")


def blob_of(data):
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def E(p, **kw):
    d = {"path": p, "why": "w " + p}
    d.update(kw)
    return d


def fixed(argv):
    return list(argv)


class Base(GitIsolatedTestCase):
    def setUp(self):
        super().setUp()
        self.root = make_repo(self.work)
        self.real = os.path.realpath(self.root)

    def put(self, rel, data=b"x\n"):
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(data)
        return path

    def ctx(self, row=None, **kw):
        row = {"schema": CTX_TAG, **kw} if row is None else row
        write_record(self.root, ".strict-delivery/context.yml", row)

    def run_cli(self, *argv, root=True):
        args = list(argv) + (["--root", self.root] if root else [])
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = context_cli.main(args)
        return code, out.getvalue(), err.getvalue()

    def sub(self, *argv, env=None, cwd=None):
        e = dict(os.environ, PYTHONPATH=REPO, PYTHONDONTWRITEBYTECODE="1", LC_ALL="C")
        e.update(env or {})
        p = subprocess.run([sys.executable, "-m", "gates.tools.context_cli"] + list(argv), cwd=cwd or self.tmp, env=e,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
        return p.returncode, p.stdout.decode("utf-8"), p.stderr.decode("utf-8")

    def abs(self, rel):
        return self.real + "/" + rel


class Output(Base):
    def test_prints_absolute_reads(self):  # C1
        data = b"one\ntwo\nthree\n"
        self.put(INFORCE, data)
        self.ctx(every=[{"path": "{paths.decisions}/in-force.md", "why": "decisions"}])
        code, out, err = self.run_cli("plan")
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(out.splitlines()[0], "read " + os.path.realpath(self.root + "/.strict-delivery/state/decisions/in-force.md")
                         + " lines 1-3 blob " + blob_of(data) + " -- decisions")
        self.assertEqual(len(out.splitlines()), 1)

    def test_blob_uses_staged_index_rule(self):  # C2
        git(self.root, "config", "core.autocrlf", "true")
        self.put("a.txt", b"a\r\nb\r\n")
        self.ctx(every=[E("a.txt")])
        code, out, _ = self.run_cli("plan")
        self.assertEqual(code, 0)
        self.assertIn(" blob 422c2b7ab3b3c668038da977e4e93a5fc623169c ", out)  # LF-normalised, not the raw c30dea8a...
        self.assertNotIn("c30dea8a3641ea99b125d04d599d843712292759", out)
        git(self.root, "config", "core.autocrlf", "false")
        code, out, _ = self.run_cli("plan")
        self.assertIn(" blob c30dea8a3641ea99b125d04d599d843712292759 ", out)
        git(self.root, "config", "core.autocrlf", "false")
        self.put(".gitattributes", b"*.txt text eol=lf\n")
        code, out, _ = self.run_cli("plan")
        self.assertIn(" blob 422c2b7ab3b3c668038da977e4e93a5fc623169c ", out)

    def test_blob_of_ignored_file(self):  # C3 / D-Q1 (a)
        self.put(".gitignore", b".strict-delivery/state/decisions/\n")
        self.put(INFORCE, b"x\n")
        self.ctx(every=[E("{paths.decisions}/in-force.md")])
        code, out, err = self.run_cli("plan")
        self.assertEqual((code, out), (2, ""))
        self.assertEqual(err.count("\n"), 1)
        self.assertTrue(err.startswith("context: " + self.abs(INFORCE) + ": no blob id can be taken"), err)

    def test_blob_of_outside_file(self):  # C4
        other = os.path.join(self.tmp, "other")
        os.makedirs(other)
        with open(os.path.join(other, "b.md"), "wb") as fh:
            fh.write(b"x\n")
        self.ctx(roles={"task_reviewer": [E("{brief}")]})
        code, out, err = self.run_cli("plan", "--role", "task_reviewer", "--brief", os.path.join(other, "b.md"))
        self.assertEqual((code, out), (2, ""))
        self.assertIn(os.path.join(other, "b.md") + ": outside this repository's tree", err)
        self.assertEqual(err.count("\n"), 1)

    def test_blob_of_symlink(self):  # C5
        self.put("real.md", b"x\n")
        os.symlink("real.md", os.path.join(self.root, "l.md"))
        self.ctx(every=[E("l.md")])
        code, out, err = self.run_cli("plan")
        self.assertEqual((code, out), (2, ""))
        self.assertIn(self.abs("real.md") + ": is a symbolic link", err)

    def test_blob_of_symlinked_directory_component(self):  # A7 through the CLI: the printed path is the real one
        self.put("other/a.md", b"x\n")
        os.symlink("other", os.path.join(self.root, "docs"))
        self.ctx(every=[E("docs/a.md")])
        code, out, _ = self.run_cli("plan")
        self.assertEqual((code, out.split(" ")[:2]), (0, ["read", self.abs("other/a.md")]))

    def test_cli_chunks_share_blob(self):  # C6
        data = b"x\n" * 4500
        self.put("big.md", data)
        self.ctx(every=[E("big.md")])
        code, out, _ = self.run_cli("plan")
        self.assertEqual(code, 0)
        want = ["read %s lines %s blob %s -- w big.md" % (self.abs("big.md"), r, blob_of(data))
                for r in ("1-2000", "2001-4000", "4001-4500")]
        self.assertEqual(out.splitlines(), want)

    def test_cli_lines_forms(self):  # C7
        self.put("a.md", b"x\n" * 12)
        self.ctx(every=[E("a.md", lines="3-9"), E("a.md", lines="3-end"), E("a.md")])
        _, out, _ = self.run_cli("plan")
        self.assertEqual([l.split(" ")[3] for l in out.splitlines()], ["3-9", "3-12", "1-12"])

    def test_unresolved_exit_1(self):  # C8
        self.ctx(kinds={"plan": [E("{paths.plan_state}/{plan}/handoff.md")]})
        code, out, _ = self.run_cli("plan")
        self.assertEqual(code, 1)
        self.assertEqual(out, "unresolved {paths.plan_state}/{plan}/handoff.md: needs {plan}\n")

    def test_unresolved_first_placeholder(self):  # C9
        self.ctx(kinds={"sync": [E("{integration}/{paths.programs}/{program}/status.md")]})
        _, out, _ = self.run_cli("sync")
        self.assertEqual(out, "unresolved {integration}/{paths.programs}/{program}/status.md: needs {integration}\n")

    def test_cli_missing_lines(self):  # C10
        os.makedirs(os.path.join(self.root, "d"))
        os.symlink("gone", os.path.join(self.root, "dangling"))
        os.mkfifo(os.path.join(self.root, "fifo"))
        self.ctx(every=[E("none.md"), E("d"), E("dangling"), E("fifo")])
        code, out, _ = within(lambda: self.run_cli("plan"))  # a hang fails by name (FR-1)
        self.assertEqual(code, 1)
        self.assertEqual(out.splitlines(), ["missing %s -- w %s" % (self.abs(a), w)
                                            for a, w in (("none.md", "none.md"), ("d", "d"), ("gone", "dangling"),
                                                         ("fifo", "fifo"))])
        if hasattr(os, "geteuid") and os.geteuid() != 0:
            self.put("locked.md", b"x\n")
            os.chmod(os.path.join(self.root, "locked.md"), 0)
            self.ctx(every=[E("locked.md")])
            self.assertEqual(self.run_cli("plan")[1], "missing %s -- w locked.md\n" % self.abs("locked.md"))

    def test_cli_mixed_exit_1(self):  # C11
        self.put("a.md", b"x\n")
        self.ctx(every=[E("a.md"), E("{plan}/u.md"), E("none.md")])
        code, out, _ = self.run_cli("plan")
        self.assertEqual(code, 1)
        self.assertEqual([l.split(" ")[0] for l in out.splitlines()], ["read", "unresolved", "missing"])

    def test_cli_empty_list_exit_0(self):  # C12
        self.ctx()
        self.assertEqual(self.run_cli("plan"), (0, "", ""))

    def test_cli_empty_file_exit_2(self):  # D-Q3 (A)
        self.put("e.md", b"")
        self.ctx(every=[E("e.md")])
        code, out, err = self.run_cli("plan")
        self.assertEqual((code, out), (2, ""))
        self.assertIn("past the end", err)

    def test_cli_range_past_end_exit_2(self):
        self.put("a.md", b"x\n" * 3)
        self.ctx(every=[E("a.md", lines="2-9")])
        code, out, err = self.run_cli("plan")
        self.assertEqual((code, out), (2, ""))
        self.assertIn("2-9", err)

    def test_roles_and_kind_selection(self):  # C28 / PD20
        self.put("a.md", b"x\n")
        self.ctx(roles={"task_reviewer": [E("a.md")], "implementer": [E("{brief}")]})
        self.assertEqual(self.run_cli("plan")[1], "")
        self.assertEqual(self.run_cli("plan", "--role", "task_reviewer")[1].split(" ")[0], "read")
        code, out, err = self.run_cli("plan", "--role", "nobody")
        self.assertEqual((code, out), (2, ""))
        self.assertIn("program_controller", err)
        self.assertEqual(self.run_cli("plan", "--role", "")[0], 2)
        self.assertEqual(self.run_cli("plan", "--role=task_reviewer")[0], 0)
        self.assertEqual(self.run_cli("plan", "--role", "implementer")[1], "unresolved {brief}: needs {brief}\n")

    def test_cli_relative_brief_joined_to_root_not_cwd(self):  # A3 through the CLI
        self.put("b.md", b"x\n")
        self.ctx(roles={"task_reviewer": [E("{brief}")]})
        code, out, _ = self.run_cli("plan", "--role", "task_reviewer", "--brief", "b.md")
        self.assertEqual((code, out.split(" ")[1]), (0, self.abs("b.md")))


class Handoff(Base):
    def setUp(self):
        super().setUp()
        self.put("docs/x.md", b"x\n" * 5)
        self.put("docs/y.md", b"y\n")

    def valid(self, reads=""):
        self.put(PLAN_PATH, (HANDOFF % reads).encode())

    def test_cli_handoff_extras_appended(self):  # C13
        self.valid("required_reads:\n  - path: docs/x.md\n    lines: 2-4\n    why: wx\n  - path: docs/y.md\n    why: wy\n")
        self.ctx(every=[E("docs/y.md")], roles={"task_reviewer": [E("docs/x.md", lines="1-1")]})
        code, out, _ = self.run_cli("plan", "--plan", "p", "--role", "task_reviewer")
        self.assertEqual(code, 0)
        got = [(l.split(" ")[1][len(self.real) + 1:], l.split(" ")[3], l.split(" -- ")[1]) for l in out.splitlines()]
        self.assertEqual(got, [("docs/y.md", "1-1", "w docs/y.md"), ("docs/x.md", "1-1", "w docs/x.md"),
                               ("docs/x.md", "2-4", "wx")])  # docs/y.md of the handoff is a duplicate of the kind entry

    def test_cli_missing_handoff_exit_codes(self):  # C14, C15, C16
        self.ctx()
        want = "missing %s -- handoff of plan\n" % self.abs(PLAN_PATH)
        with self.subTest("default resolved and absent"):
            self.assertEqual(self.run_cli("plan", "--plan", "p")[:2], (1, want))
        with self.subTest("--handoff absent"):
            self.assertEqual(self.run_cli("plan", "--handoff", "docs/none.md")[:2],
                             (1, "missing %s -- handoff of plan\n" % self.abs("docs/none.md")))
        with self.subTest("fails handoff/1"):
            self.put(PLAN_PATH, b"---\nschema: handoff/1\n---\n")
            code, out, err = self.run_cli("plan", "--plan", "p")
            self.assertEqual((code, out), (2, ""))
            self.assertTrue(err.startswith("context: "), err)
            self.assertEqual(err.count("\n"), 1)
            self.assertIn(PLAN_PATH, err)

    def test_missing_handoff_once_when_kind_names_it(self):  # C14
        self.ctx(kinds={"plan": [E("{paths.plan_state}/{plan}/handoff.md")]})
        code, out, _ = self.run_cli("plan", "--plan", "p")
        self.assertEqual((code, out), (1, "missing %s -- w {paths.plan_state}/{plan}/handoff.md\n" % self.abs(PLAN_PATH)))

    def test_cli_default_handoff_needs_plan(self):  # C17
        self.ctx()
        self.assertEqual(self.run_cli("plan"), (0, "", ""))

    def test_cli_no_default_handoff_for_program(self):  # C18
        self.valid("required_reads:\n  - path: docs/x.md\n    why: wx\n")
        self.ctx()
        for kind in ("program", "program-controller", "sync"):
            self.assertEqual(self.run_cli(kind, "--plan", "p"), (0, "", ""))
        code, out, _ = self.run_cli("sync", "--handoff", PLAN_PATH)
        self.assertEqual((code, len(out.splitlines())), (0, 1))

    def test_stream_block_has_default_handoff(self):
        self.valid("required_reads:\n  - path: docs/x.md\n    why: wx\n")
        self.ctx()
        code, out, _ = self.run_cli("stream-docs-block", "--plan", "p")
        self.assertEqual((code, len(out.splitlines())), (0, 1))

    def test_cli_handoff_path_forms(self):  # C19 / D-Q5 (A)
        self.ctx()
        for bad in ("/abs/h.md", "../h.md", "{plan}/h.md", "", "docs//x.md", "./h.md", "a/../b"):
            with self.subTest(bad=bad):
                code, out, err = self.run_cli("plan", "--handoff", bad)
                self.assertEqual((code, out), (2, ""))
                self.assertIn("--handoff", err)
        self.valid()
        self.assertEqual(self.run_cli("plan", "--handoff", PLAN_PATH), (0, "", ""))
        os.makedirs(os.path.join(self.root, "dir"))
        self.assertEqual(self.run_cli("plan", "--handoff", "dir")[0], 1)  # a directory is `missing`, as for the default


class HandoffFileStates(Base):
    """R1-1 (F-20261121-uwsk): every state of the handoff file, for `--handoff` and for the default, through
    `context_cli.main` and a subprocess. A symlink (the final component) is exit 2 naming it, never followed; a
    directory, a FIFO and an absent file are the `missing ... -- handoff of plan` line (exit 1); a regular file is
    read (the invariants of the replaced code)."""

    def setUp(self):
        super().setUp()
        self.ctx()
        self.outside = os.path.join(self.tmp, "out")
        os.makedirs(self.outside)
        with open(os.path.join(self.outside, "h.md"), "wb") as fh:
            fh.write(b"not a handoff\n")
        self.put("real/h.md", (HANDOFF % "").encode())

    def states(self):
        return [("symlink to a file inside the tree", lambda p: os.symlink("real/h.md", p), 2, "symbolic link"),
                ("symlink to a file outside the tree", lambda p: os.symlink(os.path.join(self.outside, "h.md"), p), 2,
                 "symbolic link"),
                ("dangling symlink", lambda p: os.symlink("gone.md", p), 2, "symbolic link"),
                ("directory", lambda p: os.mkdir(p), 1, None),
                ("fifo", lambda p: os.mkfifo(p), 1, None),
                ("absent", lambda p: None, 1, None)]

    def check(self, how, argv_extra, rel):
        p = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        for name, build, want_code, want_word in self.states():
            build(p)
            with self.subTest(name=name):
                got = within(lambda: how(*argv_extra))  # a FIFO that is opened by name fails by name, not by a hang (FR-1)
                self.assertEqual(got[0], want_code, got)
                if want_word:
                    self.assertEqual(got[1], "")
                    self.assertIn(want_word, got[2])
                    self.assertIn(p, got[2])
                    self.assertEqual(got[2].count("\n"), 1)
                else:
                    self.assertEqual(got[1], "missing %s -- handoff of plan\n" % self.abs(rel))
            if os.path.islink(p) or os.path.isfile(p):
                os.unlink(p)
            elif os.path.isdir(p):
                os.rmdir(p)
            else:
                try:
                    os.unlink(p)
                except OSError:
                    pass

    def test_explicit_handoff_states_in_process(self):  # C19 symlink value, PD15
        self.check(lambda *a: self.run_cli("plan", *a), ("--handoff", "lnk.md"), "lnk.md")

    def test_explicit_handoff_states_subprocess(self):
        self.check(lambda *a: self.sub("plan", *a, "--root", self.root), ("--handoff", "lnk.md"), "lnk.md")

    def test_default_handoff_states_in_process(self):
        self.check(lambda *a: self.run_cli("plan", *a), ("--plan", "p"), PLAN_PATH)

    def test_default_handoff_states_subprocess(self):
        self.check(lambda *a: self.sub("plan", *a, "--root", self.root), ("--plan", "p"), PLAN_PATH)

    def test_symlinked_directory_component_outside_refused(self):
        os.symlink(self.outside, os.path.join(self.root, "odir"))
        code, out, err = self.run_cli("plan", "--handoff", "odir/h.md")
        self.assertEqual((code, out), (2, ""))
        self.assertIn("outside this repository's tree", err)
        self.assertEqual(self.sub("plan", "--handoff", "odir/h.md", "--root", self.root)[0], 2)

    def test_symlinked_directory_component_inside_read(self):  # invariant: an in-tree directory link is read
        os.symlink("real", os.path.join(self.root, "rdir"))
        self.assertEqual(self.run_cli("plan", "--handoff", "rdir/h.md"), (0, "", ""))

    def test_regular_handoff_still_read(self):  # invariants: a regular handoff is parsed; a failing handoff/1 is exit 2
        self.assertEqual(self.run_cli("plan", "--handoff", "real/h.md"), (0, "", ""))
        self.put("real/bad.md", b"---\nschema: handoff/1\n---\n")
        self.assertEqual(self.run_cli("plan", "--handoff", "real/bad.md")[0], 2)


class Arguments(Base):
    def setUp(self):
        super().setUp()
        self.ctx()

    def test_cli_repeated_flag(self):  # C20, C21
        for flag in ("--role", "--plan", "--program", "--stream", "--brief", "--handoff", "--root"):
            with self.subTest(flag=flag):
                code, out, err = self.run_cli("plan", flag, "a", flag, "b", root=False)
                self.assertEqual((code, out), (2, ""))
                self.assertIn("%s given more than once" % flag, err)

    def test_cli_kind_missing(self):  # C22
        for argv in ([], ["--plan", "p"]):
            code, out, err = self.run_cli(*argv)
            self.assertEqual((code, out), (2, ""))
            self.assertIn("the following arguments are required: KIND", err)

    def test_cli_unknown_kind(self):  # C23
        for bad in ("nope", "Plan", "stream-A-block", "stream-a", ""):
            with self.subTest(bad=bad):
                code, out, err = self.run_cli(bad)
                self.assertEqual((code, out), (2, ""))
                self.assertIn("sync", err)
                self.assertIn("program-controller", err)

    def test_cli_stream_kind(self):  # C24
        self.put("docs/docs/a.md", b"x\n")
        self.ctx(every=[E("docs/{stream}/a.md")])
        code, out, _ = self.run_cli("stream-docs-block")
        self.assertEqual((code, out.split(" ")[1]), (0, self.abs("docs/docs/a.md")))
        code, out, err = self.run_cli("stream-docs-block", "--stream", "b")
        self.assertEqual((code, out), (2, ""))
        self.assertIn("disagrees", err)
        self.assertEqual(self.run_cli("stream-docs-block", "--stream", "docs")[0], 0)

    def test_cli_extra_positional(self):  # C25
        code, out, err = self.run_cli("plan", "extra")
        self.assertEqual((code, out), (2, ""))
        self.assertIn("unrecognized arguments: extra", err)

    def test_cli_json_not_accepted(self):  # C26
        for argv in (["--json", "plan"], ["plan", "--json"], ["plan", "--json", "x"], ["plan", "--json=1"]):
            code, out, err = self.run_cli(*argv)
            self.assertEqual((code, out), (2, ""))
            self.assertIn("--json", err)

    def test_cli_unknown_flag_and_abbrev(self):  # C27
        for argv in (["plan", "--p", "x"], ["plan", "-r", "x"], ["plan", "--nope"]):  # --p is ambiguous
            with self.subTest(argv=argv):
                self.assertEqual(self.run_cli(*argv)[:2], (2, ""))
        # an unambiguous abbreviation is argparse's, unchanged by this tool: the same run as the full flag
        self.assertEqual(self.run_cli("plan", "--pl", "p"), self.run_cli("plan", "--plan", "p"))

    def test_cli_root_forms(self):  # C29
        f = os.path.join(self.tmp, "afile")
        open(f, "w").close()
        for bad in (self.tmp, f, os.path.join(self.tmp, "missing"), os.path.join(self.root, ".strict-delivery"), ""):
            with self.subTest(bad=bad):
                code, out, err = self.run_cli("plan", "--root", bad, root=False)
                self.assertEqual((code, out), (2, ""))
                self.assertEqual(err.count("\n"), 1)
        old = os.getcwd()
        self.addCleanup(os.chdir, old)
        os.chdir(self.root)
        self.assertEqual(self.run_cli("plan", root=False), (0, "", ""))  # default: the repository root of the cwd
        self.assertEqual(self.run_cli("plan", "--root", ".", root=False), (0, "", ""))

    def test_cli_no_config(self):  # C30
        os.unlink(os.path.join(self.root, ".strict-delivery/config.yml"))
        code, out, err = self.run_cli("plan")
        self.assertEqual((code, out), (2, ""))
        self.assertIn("/strict-delivery:init", err)

    def test_cli_no_context_file(self):  # C31
        os.unlink(os.path.join(self.root, ".strict-delivery/context.yml"))
        code, out, err = self.run_cli("plan")
        self.assertEqual((code, out), (2, ""))
        self.assertIn("/strict-delivery:init", err)

    def test_cli_invalid_context_file(self):  # C32
        self.ctx({"schema": CTX_TAG, "extra": 1, "every": [E("../a")]})
        code, out, err = self.run_cli("plan")
        self.assertEqual((code, out), (2, ""))
        self.assertIn("extra: unknown key", err)
        self.assertIn("every.0.path", err)

    def test_cli_no_partial_stdout_on_error(self):  # C33
        self.put("a.md", b"x\n")
        self.put("e.md", b"")
        self.ctx(every=[E("a.md"), E("e.md")])
        code, out, err = self.run_cli("plan")
        self.assertEqual((code, out), (2, ""))
        self.assertTrue(err)

    def test_cli_stderr_one_line(self):  # C34
        self.put("e.md", b"")
        self.ctx(every=[E("e.md")])
        for argv in (["plan"], ["nope"], ["plan", "--plan", "a\nb"]):
            code, out, err = self.run_cli(*argv)
            self.assertEqual(code, 2)
            self.assertEqual(err.count("\n"), 1 if argv != ["nope"] else err.count("\n"))
            self.assertNotIn("Traceback", err)
        code, out, err = self.run_cli("plan", "--plan", "a\nb")
        self.assertTrue(err.startswith("context: "))
        self.assertEqual(err.count("\n"), 1)

    def test_cli_values_grammar(self):  # D-Q4
        for argv in (["--plan", "../../x"], ["--stream", "A"], ["--program", "x"], ["--brief", "a\nb"]):
            with self.subTest(argv=argv):
                code, out, err = self.run_cli("plan", *argv)
                self.assertEqual((code, out), (2, ""))
        self.assertEqual(self.run_cli("plan", "--plan", "")[0], 0)  # an empty string is no value

    def test_cli_program_values_resolved(self):
        code, out, err = self.run_cli("program", "--program", "20261101-x")
        self.assertEqual((code, out), (2, ""))  # no integration branch

    def test_cli_argv_types(self):  # C39 / PD1
        for bad in (("plan",), [1], ["plan", None]):
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                self.assertEqual(context_cli.main(bad), 2)
            self.assertEqual((out.getvalue(), err.getvalue()), ("", "context: argv must be a list of str\n"))

    def test_cli_argv_none_reads_sys_argv(self):  # C39
        old = sys.argv
        self.addCleanup(setattr, sys, "argv", old)
        sys.argv = ["context", "plan", "--root", self.root]
        self.assertEqual(context_cli.main(), 0)


class Process(Base):
    def test_cli_module_main_guard(self):  # C40
        self.put("a.md", b"x\n")
        self.ctx(every=[E("a.md")])
        code, out, err = self.sub("plan", "--root", self.root)
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(out, "read %s lines 1-1 blob %s -- w a.md\n" % (self.abs("a.md"), blob_of(b"x\n")))
        self.assertEqual(self.sub("nope", "--root", self.root)[0], 2)
        self.assertEqual(self.sub("plan", "--root", self.root, "none")[0], 2)
        self.ctx(every=[E("none.md")])
        self.assertEqual(self.sub("plan", "--root", self.root)[0], 1)

    def test_context_command_registered(self):  # C41
        from gates.__main__ import COMMANDS
        if "context" not in COMMANDS:
            self.skipTest("Rq-5-1 not on this branch")
        self.put("a.md", b"x\n")
        self.ctx(every=[E("a.md")])
        p = subprocess.run([sys.executable, "-m", "gates", "context", "plan", "--root", self.root], cwd=REPO,
                           env=dict(os.environ, PYTHONPATH=REPO, LC_ALL="C"), stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
        self.assertEqual((p.returncode, p.stdout.decode()), self.sub("plan", "--root", self.root)[:2])

    def test_context_cli_declares_no_kind(self):  # C42
        self.assertEqual(getattr(context_cli, "PRODUCES", ()), ())
        from gates import producers
        self.assertNotIn("gates.tools.context_cli", producers.PRODUCER_MODULES)

    def test_cli_subprocess_equals_in_process(self):  # C45
        self.put("a.md", b"x\n" * 3)
        self.ctx(every=[E("a.md", lines="2-end")], kinds={"plan": [E("{plan}/x")]})
        want = self.run_cli("plan")
        got = self.sub("plan", "--root", self.root)
        self.assertEqual(want, got)
        self.assertEqual(got[0], 1)

    def test_cli_leaves_index_alone(self):  # C46
        self.put("a.md", b"x\n")
        self.ctx(every=[E("a.md")])
        git(self.root, "add", "-A")
        copy = os.path.join(self.tmp, "idx")
        with open(os.path.join(self.root, ".git/index"), "rb") as fh, open(copy, "wb") as out:
            out.write(fh.read())
        self.put("b.md", b"y\n")
        self.ctx(every=[E("a.md"), E("b.md")])
        before = git(self.root, "ls-files", "--stage")
        with open(copy, "rb") as fh:
            copy_before = fh.read()
        code, out, _ = self.sub("plan", "--root", self.root, env={"GIT_INDEX_FILE": copy})
        self.assertEqual(code, 0)
        self.assertEqual(git(self.root, "ls-files", "--stage"), before)
        with open(copy, "rb") as fh:
            self.assertEqual(fh.read(), copy_before)
        self.assertIn(blob_of(b"y\n"), out)

    def test_cli_git_not_found(self):  # C47
        self.ctx()
        empty = os.path.join(self.tmp, "nogit")
        os.makedirs(empty)
        code, out, err = self.sub("plan", "--root", self.root, env={"PATH": empty})
        self.assertEqual((code, out), (2, ""))
        self.assertEqual(err.count("\n"), 1)
        self.assertTrue(err.startswith("context: "))

    def test_cli_git_color_abbrev(self):  # C48
        git(self.root, "config", "color.ui", "always")
        git(self.root, "config", "core.abbrev", "7")
        self.put("a.md", b"x\n")
        self.ctx(every=[E("a.md")])
        code, out, _ = self.run_cli("plan")
        self.assertEqual(code, 0)
        self.assertIn(" blob " + blob_of(b"x\n") + " ", out)
        self.assertNotIn("\x1b", out)

    def test_cli_blob_is_40_hex(self):  # C49
        self.put("a.md", b"x\n")
        self.ctx(every=[E("a.md")])
        self.assertRegex(self.run_cli("plan")[1].split(" lines ")[1].split(" ", 1)[1], r"^blob [0-9a-f]{40} -- ")

    def test_cli_idempotent_no_tree_change(self):  # C50
        self.put("a.md", b"x\n")
        self.ctx(every=[E("a.md")])
        before = git(self.root, "status", "--porcelain", "--untracked-files=all")
        first = self.run_cli("plan")
        self.assertEqual(self.run_cli("plan"), first)
        self.assertEqual(git(self.root, "status", "--porcelain", "--untracked-files=all"), before)

    def test_cli_unencodable_path(self):  # C37 / PD22
        self.put("café.md", b"x\n")
        self.ctx(every=[E("café.md")])
        out = io.TextIOWrapper(io.BytesIO(), encoding="ascii")
        err = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = context_cli.main(["plan", "--root", self.root])
        self.assertEqual(code, 2)
        self.assertEqual(err.getvalue(), "context: a path cannot be encoded for the output\n")
        out.flush()
        self.assertEqual(out.buffer.getvalue(), b"")

    def test_output_independent_of_hash_seed(self):  # VN8
        self.put("a.md", b"x\n")
        self.ctx(every=[E("a.md")], kinds={"plan": [E("{plan}/x")]}, roles={"task_reviewer": [E("none.md")]})
        got = {self.sub("plan", "--role", "task_reviewer", "--root", self.root, env={"PYTHONHASHSEED": s}) for s in "0 1 7".split()}
        self.assertEqual(len(got), 1)

    def test_cli_exit_codes(self):  # C38
        self.put("a.md", b"x\n")
        self.ctx(every=[E("a.md")])
        self.assertEqual(self.run_cli("plan")[0], 0)
        self.ctx(every=[E("none.md")])
        self.assertEqual(self.run_cli("plan")[0], 1)
        self.ctx(every=[E("{plan}/a")])
        self.assertEqual(self.run_cli("plan")[0], 1)
        self.assertEqual(self.run_cli("nope")[0], 2)

    def test_cli_stdout_only_three_forms(self):  # C35, C36
        self.put("sp ace.md", b"x\n")
        self.ctx(every=[E("sp ace.md"), E("none.md"), E("{plan}/u")])
        code, out, _ = self.run_cli("plan")
        self.assertTrue(out.endswith("\n"))
        forms = [l.split(" ")[0] for l in out.splitlines()]
        self.assertEqual(forms, ["read", "missing", "unresolved"])
        self.assertTrue(out.splitlines()[0].startswith("read " + self.abs("sp ace.md") + " lines 1-1 blob "))
        self.assertNotIn("\x1b", out)

    def test_git_calls_only_through_gitinfo(self):  # VN5
        with open(os.path.join(REPO, "gates/tools/context_cli.py"), encoding="utf-8") as fh:
            self.assertNotIn("subprocess", fh.read())

    def test_cli_argparse_same_on_both(self):  # VN7
        self.ctx()
        self.assertEqual(self.run_cli("plan", "--plan=--")[0], 2)  # `--` is not a name
        self.assertEqual(self.run_cli("plan", "--plan", "-5")[0], 2)
        self.assertEqual(self.run_cli("plan", "--plan", "5")[1].split(" ")[-3:], ["handoff", "of", "plan\n"])


if __name__ == "__main__":
    unittest.main()
