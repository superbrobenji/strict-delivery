"""Tests for gates.gate_index through its production entry point, main(), on real git fixture repositories.

Task 5b.2 input-domain table (records/task-5b.2-domain.md): row ids A, E, V, T, I, O, C and the PC1 rows V1-V3 are named
in the comments. Expected lines are typed literally; git facts are built with real git commands."""
import builtins
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from gates import __main__ as gates_main
from gates import gate_index, run_all
from gates.lib import config, gitinfo, schema, yamlsub
from gates.lib.result import GateError
from gates.tools import index
from tests.helpers import E128, TOP, GitIsolatedTestCase, commit_all, git, make_repo, minimal_config, root_forms, \
    write_record
from tests.test_index import DA, FA, dec, fnd, lasting

DEC = ".strict-delivery/state/decisions"
FIN = ".strict-delivery/state/findings"
G1 = DEC + "/index.yml"
G2 = FIN + "/index.yml"
G3 = DEC + "/in-force.md"
G4 = "docs/strict-delivery/INDEX.md"
ALL = [G1, G2, G3, G4]
PNAME = "20261101-x"
INIT = "/strict-delivery:init"
OVERVIEW_HEADS = "[## Architecture, ## Specs and plans, ## Live programs, ## Open findings, ## In-force decisions]"


def put(root, rel, text, mode="w"):
    path = os.path.join(root, *rel.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, mode, **({} if "b" in mode else {"encoding": "utf-8", "newline": ""})) as fh:
        fh.write(text)
    return path


def snapshot(root):
    """Independent listing: (relative path, size, mtime_ns) of every file and directory, .git included."""
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for name in sorted(filenames) + list(dirnames):
            p = os.path.join(dirpath, name)
            st = os.lstat(p)
            out.append((os.path.relpath(p, root), st.st_size, st.st_mtime_ns))
    return sorted(out)


class IndexCase(GitIsolatedTestCase):
    def setUp(self):
        super().setUp()
        self.root = make_repo(self.work)
        self.ignore(ALL)
        self.err = ""

    # ---- fixtures
    def ignore(self, lines):
        put(self.root, ".gitignore", "".join(x + "\n" for x in lines))
        git(self.root, "add", "--", ".gitignore")
        git(self.root, "commit", "-q", "-m", "ignore")

    def set_config(self, cfg):
        write_record(self.root, ".strict-delivery/config.yml", cfg)
        git(self.root, "add", "--", ".strict-delivery/config.yml")
        git(self.root, "commit", "-q", "-m", "config")

    def stage(self, rel, text="x\n"):
        put(self.root, rel, text)
        git(self.root, "add", "-f", "--", rel)

    def commit(self, msg="c"):
        git(self.root, "commit", "-q", "-m", msg)

    def run_gate(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = gate_index.main(list(args))
        self.err = err.getvalue()
        return out.getvalue(), code

    def run_root(self, *args):
        return self.run_gate("--root", self.root, *args)

    def lines(self, out=None):
        return (out if out is not None else self.run_root()[0]).splitlines()

    def patched(self, fn, *args):
        """Run the gate with render's result passed through ``fn`` (a dict -> anything)."""
        real = index.render

        def fake(root, cfg):
            return fn(real(root, cfg))
        with mock.patch.object(index, "render", fake):
            return self.run_root(*args)

    def with_text(self, rel, text):
        return self.patched(lambda d: {**d, rel: text})

    def fails(self, out, prefix):
        return [ln for ln in out.splitlines() if ln.startswith("FAIL " + prefix)]


PASS4 = ["PASS index.render", "PASS index.valid", "PASS index.tracked", "PASS index.ignored"]


class CleanAndArgs(IndexCase):
    def test_clean_repo_passes(self):  # A1, E1, V1, T1, I1, O1
        out, code = self.run_root()
        self.assertEqual(out.splitlines(), PASS4)
        self.assertEqual(code, 0)
        for c in ("render", "valid", "tracked", "ignored"):
            self.assertIn("PASS index." + c, out)

    def test_root_forms(self):  # A2
        forms = root_forms(self.tmp, self.root)
        for name, path, verdict in forms:
            with self.subTest(form=name):
                out, code = self.run_gate("--root", path)
                if verdict == "ok" and name != "nested":
                    self.assertEqual(out.splitlines(), PASS4)
                elif verdict == "ok":
                    self.assertNotIn("show-toplevel", out)
                else:
                    self.assertIn("FAIL index.input: " + verdict, out)
                    self.assertNotIn(path, out)
        self.assertEqual(self.run_gate("--root=" + self.root)[0].splitlines(), PASS4)
        self.assertEqual(self.run_gate("--ro", self.root)[0].splitlines(), PASS4)

    def test_root_not_a_repository(self):  # A3
        empty = os.path.join(self.tmp, "empty")
        os.mkdir(empty)
        afile = os.path.join(self.tmp, "afile")
        put(self.tmp, "afile", "x")
        for path in (empty, os.path.join(self.tmp, "missing"), afile):
            with self.subTest(path=path):
                out, code = self.run_gate("--root", path)
                self.assertEqual(out, "FAIL index.input: %s; run %s\n" % (E128, INIT))
                self.assertEqual(code, 1)

    def test_root_subdirectory_refused(self):  # A4
        sub = os.path.join(self.root, "sub")
        os.mkdir(sub)
        out, code = self.run_gate("--root", sub)
        self.assertEqual(out, "FAIL index.input: " + TOP + "\n")
        self.assertEqual(code, 1)

    def test_missing_config_names_init(self):  # A5
        other = os.path.join(self.tmp, "other")
        os.mkdir(other)
        git(other, "init", "-q", "-b", "main")
        out, code = self.run_gate("--root", other)
        self.assertTrue(out.startswith("FAIL index.input:"))
        self.assertIn(".strict-delivery/config.yml: missing; run /strict-delivery:init", out)
        self.assertEqual(len(out.splitlines()), 1)
        self.assertEqual(code, 1)

    def test_bad_config_is_input(self):  # A6
        for text in ("schema: config/2\nframework_version: 0.0.0\nprofile: strict\nbogus: 1\n",
                     "schema: config/2\nframework_version: 0.0.0\nprofile: x\n",
                     "schema: config/9\nframework_version: 0.0.0\nprofile: strict\n"):
            with self.subTest(text=text):
                put(self.root, ".strict-delivery/config.yml", text)
                out, code = self.run_root()
                self.assertEqual(len(out.splitlines()), 1)
                self.assertTrue(out.startswith("FAIL index.input: "))
                self.assertEqual(code, 1)

    def test_json_only_as_first_argument(self):  # A7, O9
        out, code = self.run_gate("--json", "--root", self.root)
        body = json.loads(out)
        self.assertEqual(body["gate"], "index")
        self.assertIs(body["ok"], True)
        self.assertEqual([x["id"] for x in body["lines"]], ["index.render", "index.valid", "index.tracked",
                                                            "index.ignored"])
        self.assertTrue(all(x["status"] == "PASS" and x["reason"] == "" for x in body["lines"]))
        self.assertEqual(code, 0)
        out, code = self.run_gate("--root", self.root, "--json")
        self.assertEqual(out, "FAIL index.input: invalid arguments: unrecognized arguments: --json\n")
        self.assertEqual(code, 1)

    def test_json_shape(self):  # O9
        self.stage(G4)
        body = json.loads(self.run_gate("--json", "--root", self.root)[0])
        self.assertIs(body["ok"], False)
        bad = [x for x in body["lines"] if x["status"] == "FAIL"]
        self.assertEqual(len(bad), 1)
        self.assertEqual(set(bad[0]), {"status", "id", "reason"})
        self.assertEqual(bad[0]["id"], "index.tracked." + G4)

    def test_argv_refusals(self):  # A8
        cases = [(["--root", self.root, "--root", self.root], "--root given more than once"),
                 (["--bogus"], "unrecognized arguments: --bogus"),
                 (["--root", self.root, "extra"], "unrecognized arguments: extra"),
                 (["--help"], "help requested; no gate was run"),
                 (["--root"], "expected one argument"),
                 (["--root", ""], "root must be the repository top level")]
        for argv, text in cases:
            with self.subTest(argv=argv):
                with contextlib.redirect_stderr(io.StringIO()):
                    out, code = self.run_gate(*argv)
                self.assertTrue(out.startswith("FAIL index.input:"), out)
                self.assertIn(text, out)
                self.assertEqual(len(out.splitlines()), 1)
                self.assertEqual(code, 1)

    def test_claude_project_dir(self):  # A9
        with mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": self.root}):
            self.assertEqual(self.run_gate()[0].splitlines(), PASS4)
        with mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": os.path.join(self.tmp, "missing")}):
            self.assertEqual(self.run_gate()[0], "FAIL index.input: CLAUDE_PROJECT_DIR is not a directory\n")
            self.assertEqual(self.run_root()[0].splitlines(), PASS4)

    def test_index_from_linked_worktree(self):  # A10, I12
        wt = os.path.join(self.tmp, "wt")
        git(self.root, "worktree", "add", "-q", "--detach", wt)
        self.assertEqual(self.run_gate("--root", wt)[0].splitlines(), PASS4)
        put(wt, G4, "x\n")
        git(wt, "add", "-f", "--", G4)
        wt_out = self.run_gate("--root", wt)[0]
        self.assertIn("FAIL index.tracked." + G4, wt_out)
        self.assertEqual(self.run_root()[0].splitlines(), PASS4)  # the main index is its own

    def test_main_reads_sys_argv(self):  # A11
        out = io.StringIO()
        with mock.patch.object(sys, "argv", ["gate_index", "--root", self.root]), contextlib.redirect_stdout(out):
            code = gate_index.main()
        self.assertEqual(out.getvalue().splitlines(), PASS4)
        self.assertEqual(code, 0)

    def test_produces_empty(self):  # A12
        self.assertEqual(gate_index.PRODUCES, ())
        res = gate_index.check(["--root", self.root])
        self.assertEqual(res.gate, "index")
        p = subprocess.run([sys.executable, "-m", "gates.gate_index", "--root", self.root], stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
        self.assertEqual(p.stdout.decode().splitlines(), PASS4)
        self.assertEqual(p.returncode, 0)

    def test_index_with_git_index_file(self):  # A14, T12
        idx = os.path.join(self.tmp, "tmp-index")
        git(self.root, "read-tree", "HEAD", env={"GIT_INDEX_FILE": idx})
        put(self.root, G4, "x\n")
        git(self.root, "add", "-f", "--", G4, env={"GIT_INDEX_FILE": idx})
        with mock.patch.dict(os.environ, {"GIT_INDEX_FILE": idx}):
            out = self.run_root()[0]
        self.assertEqual(self.fails(out, "index"), ["FAIL index.tracked.%s: generated; never commit it: "
                                                    "git rm --cached %s" % (G4, G4)])
        self.assertEqual(self.run_root()[0].splitlines(), PASS4)  # unset: the real index holds nothing
        git(self.root, "add", "-f", "--", G4)
        with mock.patch.dict(os.environ, {"GIT_INDEX_FILE": ".git/index"}):
            self.assertIn("FAIL index.tracked." + G4, self.run_root()[0])

    def test_cwd_does_not_matter(self):  # A15
        sub = os.path.join(self.root, "sub")
        os.mkdir(sub)
        old = os.getcwd()
        self.addCleanup(os.chdir, old)
        for cwd in (sub, self.tmp):
            os.chdir(cwd)
            self.assertEqual(self.run_root()[0].splitlines(), PASS4)
        os.chdir(sub)
        self.assertEqual(self.run_gate()[0].splitlines(), PASS4)  # no --root: the toplevel of the cwd

    def test_stderr_empty(self):  # O10
        self.run_root()
        self.assertEqual(self.err, "")
        self.stage(G4)
        self.run_root()
        self.assertEqual(self.err, "")

    def test_no_resources_left(self):  # O11
        names = ("mkstemp", "mkdtemp", "NamedTemporaryFile", "TemporaryDirectory")
        with contextlib.ExitStack() as st:
            mocks = [st.enter_context(mock.patch.object(tempfile, n)) for n in names]
            self.run_gate("--bogus")
            with mock.patch.object(index, "render", side_effect=RuntimeError("r")):
                self.run_root()
            self.run_root()
        for m in mocks:
            m.assert_not_called()

    def test_gate_is_idempotent(self):  # O12
        self.stage(G4)
        self.assertEqual(self.run_root(), self.run_root())

    def test_no_empty_run(self):  # O5
        self.assertNotIn("index.empty", self.run_root()[0])


class Render(IndexCase):
    def test_render_error_stops(self):  # E2
        put(self.root, DEC + "/DEC-20261031-k3f9.yml", "id: [unclosed\n")
        out, code = self.run_root()
        self.assertTrue(out.startswith("FAIL index.render:"), out)
        self.assertIn("unterminated flow sequence", out)
        for later in ("index.valid", "index.tracked", "index.ignored"):
            self.assertNotIn(later, out)
        self.assertEqual(len(out.splitlines()), 1)
        self.assertEqual(code, 1)

    def test_render_error_other_records(self):  # E2
        bad = dict(fnd(FA), bogus=1)
        write_record(self.root, "%s/%s.yml" % (FIN, FA), bad)
        out = self.run_root()[0]
        self.assertTrue(out.startswith("FAIL index.render:"), out)
        self.assertEqual(len(out.splitlines()), 1)

    def test_render_other_exception(self):  # E3
        for exc, text in ((RuntimeError("r"), "RuntimeError: r"), (ValueError("v"), "ValueError: v"),
                          (KeyError("k"), "KeyError: 'k'"), (RecursionError("deep"), "RecursionError: deep")):
            with self.subTest(exc=text), mock.patch.object(index, "render", side_effect=exc):
                out, code = self.run_root()
                self.assertEqual(out, "FAIL index.render: %s\n" % text)
                self.assertEqual(code, 1)

    def test_render_gateerror_text(self):  # E2 (plan: GateError text)
        with mock.patch.object(index, "render", side_effect=GateError("boom: text")):
            self.assertEqual(self.run_root()[0], "FAIL index.render: boom: text\n")

    def test_render_git_not_found(self):  # E4
        with mock.patch.object(index, "render", side_effect=gitinfo.GitNotFound("git not found on PATH; install git")):
            out = self.run_root()[0]
        self.assertEqual(out, "FAIL index.render: git not found on PATH; install git\n")

    def test_render_systemexit_and_keyboardinterrupt(self):  # E5
        with mock.patch.object(index, "render", side_effect=SystemExit(3)):
            self.assertEqual(self.run_root()[0], "FAIL index.input: exit requested (3)\n")
        with mock.patch.object(index, "render", side_effect=KeyboardInterrupt()):
            with self.assertRaises(KeyboardInterrupt):
                self.run_root()

    def test_render_shape_refused(self):  # E6, V8
        good = index.render(self.root, config.load(self.root))
        keys = list(good)
        bad = [("a list", [1]), ("None", None), ("three keys", {k: good[k] for k in keys[:3]}),
               ("five keys", dict(good, extra="x")), ("int key", {1: "x", **{k: good[k] for k in keys[1:]}}),
               ("bytes value", {**good, G2: b"x"}), ("None value", {**good, G1: None}), ("empty", {})]
        for name, value in bad:
            with self.subTest(shape=name), mock.patch.object(index, "render", return_value=value):
                out, code = self.run_root()
                self.assertTrue(out.startswith("FAIL index.render: render returned"), out)
                self.assertEqual(len(out.splitlines()), 1)
                self.assertEqual(code, 1)

    def test_render_path_collision(self):  # E7
        cfg = minimal_config()
        cfg["paths"] = {"index": G1}
        self.set_config(cfg)
        out = self.run_root()[0]
        self.assertTrue(out.startswith("FAIL index.render: two generated files would share a path ("), out)

    def test_paths_index_moved(self):  # E8
        cfg = minimal_config()
        cfg["paths"] = {"index": "out/OVERVIEW.md"}
        self.set_config(cfg)
        self.ignore([G1, G2, G3, "out/OVERVIEW.md"])
        self.assertEqual(self.run_root()[0].splitlines(), PASS4)
        self.stage("out/OVERVIEW.md")
        self.stage(G4)  # the default path is no longer generated: not judged
        self.assertEqual(self.fails(self.run_root()[0], "index"),
                         ["FAIL index.tracked.out/OVERVIEW.md: generated; never commit it: "
                          "git rm --cached out/OVERVIEW.md"])
        git(self.root, "rm", "-q", "--cached", "--", "out/OVERVIEW.md")
        self.ignore([G1, G2, G3])
        self.assertEqual(self.fails(self.run_root()[0], "index.ignored"),
                         ["FAIL index.ignored.out/OVERVIEW.md: add it to .gitignore (spec §5)"])

    def test_paths_index_odd_names(self):  # E9, I11, Q9
        for rel in ("docs/*.md", "a b/INDEX.md"):
            with self.subTest(rel=rel):
                cfg = minimal_config()
                cfg["paths"] = {"index": rel}
                self.set_config(cfg)
                self.ignore([G1, G2, G3, rel])
                self.assertEqual(self.run_root()[0].splitlines(), PASS4)
                self.ignore([G1, G2, G3])
                self.assertEqual(self.fails(self.run_root()[0], "index.ignored"),
                                 ["FAIL index.ignored.%s: add it to .gitignore (spec §5)" % rel])
                self.stage(rel)
                quoted = "'a b/INDEX.md'" if " " in rel else "'docs/*.md'"
                self.assertEqual(self.fails(self.run_root()[0], "index.tracked"),
                                 ["FAIL index.tracked.%s: generated; never commit it: git rm --cached %s"
                                  % (rel, quoted)])
                git(self.root, "rm", "-q", "--cached", "--", rel)

    def test_render_program_does_not_load(self):  # E10 [5b.1]
        git(self.root, "checkout", "-q", "-b", PNAME + "/integration")
        d = ".strict-delivery/state/programs/" + PNAME
        put(self.root, d + "/streams.yml", "a: [unclosed\n")
        put(self.root, d + "/status.md", "log\n")
        put(self.root, d + "/sync-log.md", "log\n")
        put(self.root, d + "/merged.md", "log\n")
        git(self.root, "add", "--", d)
        self.commit("program")
        git(self.root, "checkout", "-q", "main")
        out = self.run_root()[0]
        self.assertTrue(out.startswith("FAIL index.render:"), out)
        self.assertIn("streams.yml", out)
        self.assertEqual(len(out.splitlines()), 1)

    def test_empty_repository(self):  # E11
        self.assertEqual(self.run_root()[0].splitlines(), PASS4)
        bare = os.path.join(self.tmp, "nocommit")
        os.mkdir(bare)
        git(bare, "init", "-q", "-b", "main")
        write_record(bare, ".strict-delivery/config.yml", minimal_config())
        put(bare, ".gitignore", "".join(x + "\n" for x in ALL))
        out = self.run_gate("--root", bare)[0]
        self.assertEqual(out.splitlines(), PASS4)

    def test_render_store_errors(self):  # E12
        write_record(self.root, DEC + "/DEC-20261340-k3f9.yml", dec("DEC-20261340-k3f9"))
        out = self.run_root()[0]
        self.assertTrue(out.startswith("FAIL index.render:"), out)
        self.assertIn("DEC-20261340-k3f9", out)
        self.assertEqual(len(out.splitlines()), 1)

    def test_render_two_records_one_id(self):  # E12
        write_record(self.root, DEC + "/" + DA + ".yml", dec(DA))
        write_record(self.root, DEC + "/" + DA + "-2.yml", dec(DA))
        out = self.run_root()[0]
        self.assertTrue(out.startswith("FAIL index.render:"), out)

    def test_render_gets_loaded_config(self):  # E13, V15
        seen = {}
        real_load, real_render, real_validate = config.load, index.render, schema.validate

        def load(root):
            seen["cfg"] = real_load(root)
            return seen["cfg"]

        def render(root, cfg):
            seen["render"] = cfg
            return real_render(root, cfg)

        def validate(sch, value, cfg):
            seen["validate"] = cfg
            return real_validate(sch, value, cfg)
        with mock.patch.object(config, "load", load), mock.patch.object(index, "render", render), \
                mock.patch.object(schema, "validate", validate):
            self.assertEqual(self.run_root()[0].splitlines(), PASS4)
        self.assertIs(seen["render"], seen["cfg"])
        self.assertIs(seen["validate"], seen["cfg"])

    def test_render_called_once(self):  # E14
        real = index.render
        with mock.patch.object(index, "render", wraps=real) as m:
            self.run_root()
        self.assertEqual(m.call_count, 1)
        self.assertEqual(m.call_args[0][0], self.root)

    def test_render_large_input(self):  # E15
        write_record(self.root, DEC + "/" + DA + ".yml", lasting(DA, rule="x" * 1000000))
        self.assertEqual(self.run_root()[0].splitlines(), PASS4)

    def test_version_numbers(self):  # V1a V1b V1c: same text on both interpreters
        for digits, ok in ((1000, True), (4300, False), (4301, False)):
            with self.subTest(digits=digits):
                text = yamlsub.emit(fnd(FA, owner={"kind": "issue", "number": 3}))
                self.assertIn("number: 3\n", text)
                put(self.root, "%s/%s.yml" % (FIN, FA), text.replace("number: 3\n", "number: %s\n" % ("9" * digits)))
                out = self.run_root()[0]
                if ok:
                    self.assertEqual(out.splitlines(), PASS4)
                else:
                    self.assertTrue(out.startswith("FAIL index.render:"), out[:200])
                    self.assertIn("integer too large", out)

    def test_version_unicode_same_on_both(self):  # V2a, V2b: literal code points, no interpreter-derived value
        rule = "ࡰ Ꟁ \U0001e030 é"
        write_record(self.root, DEC + "/" + DA + ".yml", lasting(DA, rule=rule))
        self.assertEqual(self.run_root()[0].splitlines(), PASS4)

    def test_line_escaping_same_on_both(self):  # O8
        key = "docs/ࡰꟀ\U0001e030é.md"
        out = self.patched(lambda d: {G1: d[G1], G2: d[G2], G3: d[G3], key: d[G4]})[0]
        self.assertTrue(any(ln.startswith("FAIL index.ignored.docs/\\u0870\\ua7c0\\U0001e030é.md") for ln in
                            out.splitlines()), out)

    @unittest.skipUnless(hasattr(builtins, "ExceptionGroup"), "ExceptionGroup absent on 3.9")
    def test_version_exception_group_render(self):  # V3a
        eg = getattr(builtins, "ExceptionGroup")("g", [ValueError()])
        with mock.patch.object(index, "render", side_effect=eg):
            self.assertEqual(self.run_root()[0], "FAIL index.render: ExceptionGroup: g (1 sub-exception)\n")
        beg = getattr(builtins, "BaseExceptionGroup")("g", [KeyboardInterrupt()])
        with mock.patch.object(index, "render", side_effect=beg):
            with self.assertRaises(getattr(builtins, "BaseExceptionGroup")):
                self.run_root()


class Valid(IndexCase):
    def test_valid_markdown_first_line(self):  # V2
        want = {G3: "first line: expected '<!-- schema: in-force/1 -->'",
                G4: "first line: expected '<!-- schema: overview/2 -->'"}
        for rel, why in want.items():
            for name, text in (("wrong tag", "<!-- schema: x/9 -->\n"), ("empty", ""),
                               ("bom", "﻿<!-- schema: in-force/1 -->\n")):
                with self.subTest(path=rel, text=name):
                    out, code = self.with_text(rel, text)
                    self.assertIn("FAIL index.valid.%s: %s" % (rel, why), out)
                    self.assertNotIn("PASS index.valid", out)
                    self.assertEqual(code, 1)
        crlf = index.render(self.root, config.load(self.root))[G3].replace("\n", "\r\n")
        self.assertIn("FAIL index.valid." + G3 + ": first line: expected", self.with_text(G3, crlf)[0])

    def test_valid_overview_headings(self):  # V3 [5b.1]
        good = index.render(self.root, config.load(self.root))[G4]
        self.assertIn("## Open findings\n", good)
        dropped = good.replace("## Open findings\n", "")
        got = "[## Architecture, ## Specs and plans, ## Live programs, ## In-force decisions]"
        self.assertIn("FAIL index.valid.%s: headings: expected %s, got %s" % (G4, OVERVIEW_HEADS, got),
                      self.with_text(G4, dropped)[0])
        extra = good + "\n## x\n"
        self.assertIn("FAIL index.valid.%s: headings: expected %s" % (G4, OVERVIEW_HEADS),
                      self.with_text(G4, extra)[0])
        swapped = good.replace("## Architecture", "## TMP").replace("## Specs and plans", "## Architecture") \
            .replace("## TMP", "## Specs and plans")
        self.assertIn("FAIL index.valid.%s: headings: expected" % G4, self.with_text(G4, swapped)[0])

    def test_valid_in_force_table(self):  # V4
        head = "<!-- schema: in-force/1 -->\n"
        for name, text in (("header", head + "| id | topics |\n|---|---|\n"), ("no table", head),
                           ("no separator", head + "| id | topics | rule | landed_in |\n| a | b | c | d |\n")):
            with self.subTest(name=name):
                out = self.with_text(G3, text)[0]
                self.assertTrue(any(ln.startswith("FAIL index.valid.%s: table:" % G3) for ln in out.splitlines()), out)

    def test_valid_yaml_schema_errors(self):  # V5
        cases = [("schema: decision-index/9\ndecisions: []\n", "schema: expected decision-index/1, got"),
                 ("schema: decision-index/1\ndecisions: []\nextra: 1\n", "extra: unknown key"),
                 ("schema: decision-index/1\ndecisions: x\n", "decisions"),
                 ("schema: decision-index/1\ndecisions:\n  - id: DEC-20261031-k3f9\n    file: x.yml\n"
                  "    status: bogus\n    class: c\n    topics: []\n", "status")]
        for text, frag in cases:
            with self.subTest(text=text):
                out, code = self.with_text(G1, text)
                fails = self.fails(out, "index.valid." + G1 + ": ")
                self.assertTrue(fails and any(frag in ln for ln in fails), out)
                self.assertEqual(code, 1)

    def test_valid_yaml_parse_error(self):  # V6
        out = self.with_text(G2, "a: [unclosed\n")[0]
        self.assertEqual(len(self.fails(out, "index.valid." + G2 + ": ")), 1)
        self.assertIn("unterminated flow sequence (line 1)", out)
        self.assertNotIn("index.input", out)

    def test_valid_top_level_not_mapping(self):  # V7
        self.assertIn("FAIL index.valid.%s: top level: must be a mapping" % G1, self.with_text(G1, "- a\n")[0])

    def test_valid_one_failure_others_still_run(self):  # V9, O2, O3
        out = self.with_text(G4, "<!-- schema: overview/2 -->\n")[0].splitlines()
        self.assertEqual(out[0], "PASS index.render")
        self.assertTrue(out[1].startswith("FAIL index.valid." + G4))
        self.assertEqual(out[-2:], ["PASS index.tracked", "PASS index.ignored"])
        self.assertNotIn("PASS index.valid", out)

    def test_valid_one_line_per_error(self):  # V10
        text = "schema: decision-index/1\ndecisions: []\nextra: 1\nmore: 2\n"
        fails = self.fails(self.with_text(G1, text)[0], "index.valid." + G1 + ": ")
        self.assertEqual([ln.split(": ", 1)[1] for ln in fails], ["extra: unknown key", "more: unknown key"])

    def test_valid_schema_file_missing(self):  # V11
        empty = os.path.join(self.tmp, "noschemas")
        os.mkdir(empty)
        with mock.patch.object(schema, "SCHEMAS_DIR", empty):
            out, code = self.run_root()
        self.assertTrue(out.startswith("FAIL index.input: "), out)
        self.assertNotIn("SchemaError", out)  # the text of the schema problem, not the exception type
        self.assertEqual(len(out.splitlines()), 1)
        self.assertEqual(code, 1)

    def test_valid_old_overview_text(self):  # V12 [5b.1]
        out = self.with_text(G4, "<!-- schema: overview/1 -->\n## Architecture\n")[0]
        self.assertIn("FAIL index.valid.%s: first line: expected '<!-- schema: overview/2 -->'" % G4, out)

    def test_valid_ignores_disk_files(self):  # V13
        put(self.root, G4, "garbage\n")
        put(self.root, G1, "garbage: [\n")
        self.assertEqual(self.run_root()[0].splitlines(), PASS4)

    def test_valid_unicode_rule(self):  # V14
        write_record(self.root, DEC + "/" + DA + ".yml", lasting(DA, rule="ࡰ Ꟁ \U0001e030 é"))
        self.assertEqual(self.run_root()[0].splitlines(), PASS4)


class Tracked(IndexCase):
    def hint(self, rel):
        return "FAIL index.tracked.%s: generated; never commit it: git rm --cached %s" % (rel, rel)

    def test_tracked_generated_file_fails(self):  # T2, T15
        self.stage(G4)
        out, code = self.run_root()
        self.assertIn(self.hint(G4), out.splitlines())
        self.assertNotIn("PASS index.tracked", out)
        self.assertEqual(code, 1)
        self.assertIn("FAIL index.tracked.docs/strict-delivery/INDEX.md", out)
        self.assertEqual(git(self.root, "status", "--porcelain", "--", G4)[0], "A")

    def test_tracked_committed_each_path(self):  # T3
        for rel in ALL:
            with self.subTest(rel=rel):
                self.stage(rel)
                self.commit("add " + rel)
                out = self.run_root()[0]
                self.assertEqual(self.fails(out, "index"), [self.hint(rel)])
                git(self.root, "rm", "-q", "--cached", "--", rel)
                self.commit("rm " + rel)

    def test_tracked_all_four(self):  # T4, O3
        for rel in ALL:
            self.stage(rel)
        out = self.run_root()[0].splitlines()
        self.assertEqual(out, ["PASS index.render", "PASS index.valid"] + [self.hint(r) for r in ALL]
                         + ["PASS index.ignored"])

    def test_tracked_staged_deletion_passes(self):  # T5
        self.stage(G4)
        self.commit("add")
        git(self.root, "rm", "-q", "--cached", "--", G4)
        self.assertEqual(self.run_root()[0].splitlines(), PASS4)

    def test_tracked_intent_to_add_fails(self):  # T6
        put(self.root, G4, "x\n")
        git(self.root, "add", "-N", "-f", "--", G4)
        self.assertIn(self.hint(G4), self.run_root()[0].splitlines())

    def test_tracked_deleted_in_worktree_fails(self):  # T7
        self.stage(G4)
        self.commit("add")
        os.unlink(os.path.join(self.root, *G4.split("/")))
        self.assertIn(self.hint(G4), self.run_root()[0].splitlines())

    def test_tracked_executable_fails(self):  # T8
        self.stage(G4)
        git(self.root, "update-index", "--chmod=+x", "--", G4)
        self.assertEqual(git(self.root, "ls-files", "--stage", "--", G4).split()[0], "100755")
        self.assertIn(self.hint(G4), self.run_root()[0].splitlines())

    def test_tracked_unmerged_one_line(self):  # T9
        git(self.root, "checkout", "-q", "-b", "side")
        self.stage(G4, "side\n")
        self.commit("side")
        git(self.root, "checkout", "-q", "main")
        self.stage(G4, "main\n")
        self.commit("main")
        git(self.root, "merge", "-q", "side", check=False)
        self.assertEqual(len(git(self.root, "ls-files", "-u", "--", G4).splitlines()), 2)
        self.assertEqual(self.fails(self.run_root()[0], "index"), [self.hint(G4)])

    def test_tracked_symlink_or_gitlink(self):  # T10 / Q4: a stated limit (gitinfo.tracked_files is regular files only)
        os.makedirs(os.path.join(self.root, "docs", "strict-delivery"))
        os.symlink("elsewhere", os.path.join(self.root, *G4.split("/")))
        git(self.root, "add", "-f", "--", G4)
        self.assertEqual(git(self.root, "ls-files", "--stage", "--", G4).split()[0], "120000")
        self.assertEqual(self.run_root()[0].splitlines()[2], "PASS index.tracked")
        git(self.root, "rm", "-q", "--cached", "--", G4)
        sha = git(self.root, "rev-parse", "HEAD")
        git(self.root, "update-index", "--add", "--cacheinfo", "160000,%s,%s" % (sha, G3))
        self.assertEqual(git(self.root, "ls-files", "--stage", "--", G3).split()[0], "160000")
        self.assertEqual(self.run_root()[0].splitlines()[2], "PASS index.tracked")

    def test_tracked_case_variant(self):  # T11 / Q10: exact string comparison
        lower = "docs/strict-delivery/index.md"
        self.stage(lower)
        self.assertEqual(self.run_root()[0].splitlines()[2], "PASS index.tracked")

    def test_tracked_directory_at_path(self):  # T13
        self.stage(G4 + "/x", "x\n")
        self.assertEqual(self.run_root()[0].splitlines()[2], "PASS index.tracked")

    def test_tracked_skip_worktree(self):  # T14
        self.stage(G4)
        self.commit("add")
        git(self.root, "update-index", "--skip-worktree", "--", G4)
        os.unlink(os.path.join(self.root, *G4.split("/")))
        self.assertIn(self.hint(G4), self.run_root()[0].splitlines())

    def test_tracked_hint_text(self):  # T15
        for rel in ALL:
            self.stage(rel)
        for ln in self.fails(self.run_root()[0], "index.tracked."):
            rel = ln[len("FAIL index.tracked."):].split(": ")[0]
            self.assertEqual(ln, self.hint(rel))

    def test_untracked_unignored_file(self):  # T16
        self.ignore([G1, G2, G3])
        put(self.root, G4, "x\n")
        out = self.run_root()[0].splitlines()
        self.assertEqual(out[2], "PASS index.tracked")
        self.assertEqual(out[3], "FAIL index.ignored.%s: add it to .gitignore (spec §5)" % G4)

    def test_tracked_gateerror_is_a_line(self):  # Q3
        with mock.patch.object(gitinfo, "tracked_files", side_effect=GateError("boom")):
            out, code = self.run_root()
        self.assertEqual(out.splitlines(), ["PASS index.render", "PASS index.valid", "FAIL index.tracked: boom",
                                            "PASS index.ignored"])
        self.assertEqual(code, 1)

    def test_tracked_and_ignored_independent(self):  # I7
        self.stage(G4)  # GI names G4 and the file is tracked
        out = self.run_root()[0].splitlines()
        self.assertEqual(out, ["PASS index.render", "PASS index.valid", self.hint(G4), "PASS index.ignored"])

    def test_failed_check_has_no_pass_line(self):  # O2
        self.stage(G4)
        out = self.run_root()[0]
        self.assertNotIn("PASS index.tracked", out)
        for c in ("render", "valid", "ignored"):
            self.assertIn("PASS index." + c, out)

    def test_exit_code(self):  # O4
        self.assertEqual(self.run_root()[1], 0)
        self.stage(G4)
        self.assertEqual(self.run_root()[1], 1)


class Ignored(IndexCase):
    def bad(self, rel):
        return "FAIL index.ignored.%s: add it to .gitignore (spec §5)" % rel

    def test_ignored_none(self):  # I2, I13, I14
        os.unlink(os.path.join(self.root, ".gitignore"))
        git(self.root, "rm", "-q", "--cached", "--", ".gitignore")
        self.commit("no ignore")
        out = self.run_root()[0].splitlines()
        self.assertEqual(out, ["PASS index.render", "PASS index.valid", "PASS index.tracked"]
                         + [self.bad(r) for r in ALL])

    def test_unignored_generated_file_fails(self):  # I3
        self.ignore([G1, G2, G3])
        out, code = self.run_root()
        self.assertIn("FAIL index.ignored.", out)
        self.assertEqual(self.fails(out, "index.ignored"), [self.bad(G4)])
        self.assertNotIn("PASS index.ignored", out)
        self.assertEqual(code, 1)

    def test_ignored_negated_pattern_fails(self):  # I4
        self.ignore([G1, G2, "*.md", "!INDEX.md"])
        self.assertEqual(self.fails(self.run_root()[0], "index.ignored"), [self.bad(G4)])

    def test_ignored_dir_pattern_wins(self):  # I5
        self.ignore([G1, G2, G3, "docs/strict-delivery/", "!docs/strict-delivery/INDEX.md"])
        self.assertEqual(self.run_root()[0].splitlines(), PASS4)

    def test_ignored_by_each_source(self):  # I6, Q8
        self.ignore([G1, G2, G3])
        put(self.root, ".git/info/exclude", G4 + "\n")
        self.assertEqual(self.run_root()[0].splitlines(), PASS4)
        put(self.root, ".git/info/exclude", "# none\n")
        self.assertIn(self.bad(G4), self.run_root()[0])
        put(self.root, "docs/strict-delivery/.gitignore", "INDEX.md\n")
        self.assertEqual(self.run_root()[0].splitlines(), PASS4)
        os.unlink(os.path.join(self.root, "docs", "strict-delivery", ".gitignore"))
        glob = put(self.tmp, "globalconfig", "[core]\n\texcludesFile = %s\n" % put(self.tmp, "globalignore", G4 + "\n"))
        with mock.patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": glob}):
            self.assertEqual(self.run_root()[0].splitlines(), PASS4)
        self.assertIn(self.bad(G4), self.run_root()[0])

    def test_ignored_gateerror_is_a_line(self):  # I8, E9, Q3
        cfg = minimal_config()
        cfg["paths"] = {"index": ":x.md"}
        self.set_config(cfg)
        out = self.run_root()[0].splitlines()
        self.assertEqual(out[:3], ["PASS index.render", "PASS index.valid", "PASS index.tracked"])
        self.assertEqual(len(out), 4)
        self.assertTrue(out[3].startswith("FAIL index.ignored.:x.md: "), out)
        self.assertIn("must not start with ':'", out[3])

    def test_ignored_other_paths_still_judged(self):  # Q3
        cfg = minimal_config()
        cfg["paths"] = {"index": ":x.md"}
        self.set_config(cfg)
        self.ignore([G2])
        fails = self.fails(self.run_root()[0], "index.ignored.")
        self.assertEqual([f.split(": ")[0] for f in fails], ["FAIL index.ignored." + G1, "FAIL index.ignored." + G3,
                                                            "FAIL index.ignored.:x.md"])
        self.assertEqual(len(fails), 3)

    def test_ignored_symlinked_parent_is_a_line(self):  # I8
        os.makedirs(os.path.join(self.tmp, "elsewhere", "strict-delivery"))
        os.symlink(os.path.join(self.tmp, "elsewhere"), os.path.join(self.root, "docs"))
        out = self.run_root()[0]
        self.assertTrue(out.splitlines()[0].startswith(("PASS index.render", "FAIL index.render")), out)
        if out.startswith("PASS index.render"):
            self.assertEqual(len(self.fails(out, "index.ignored." + G4 + ": ")), 1)
            self.assertIn("exit 128", out)

    def test_ignored_parent_is_file(self):  # I9
        put(self.root, "docs", "i am a file\n")
        out = self.run_root()[0]
        if out.startswith("PASS index.render"):
            self.assertEqual(out.splitlines()[-1], "PASS index.ignored")
        else:
            self.assertTrue(out.startswith("FAIL index.render:"), out)

    def test_ignored_case_follows_core_ignorecase(self):  # I10
        self.ignore([G1, G2, G3, "docs/strict-delivery/index.md"])
        git(self.root, "config", "core.ignorecase", "true")
        self.assertEqual(self.run_root()[0].splitlines(), PASS4)
        git(self.root, "config", "core.ignorecase", "false")
        self.assertEqual(self.fails(self.run_root()[0], "index.ignored"), [self.bad(G4)])

    def test_ignored_line_order(self):  # I13
        self.ignore([])
        out = self.run_root()[0].splitlines()
        self.assertEqual(out[3:], [self.bad(r) for r in ALL])

    def test_ignored_shares_info_exclude(self):  # I12
        wt = os.path.join(self.tmp, "wt2")
        self.ignore([G1, G2, G3])
        git(self.root, "worktree", "add", "-q", "--detach", wt)
        self.assertIn(self.bad(G4), self.run_gate("--root", wt)[0])
        put(self.root, ".git/info/exclude", G4 + "\n")
        self.assertEqual(self.run_gate("--root", wt)[0].splitlines(), PASS4)


class Writes(IndexCase):
    def test_gate_writes_nothing(self):  # O6
        scenarios = [lambda: None, lambda: self.stage(G4), lambda: self.ignore([G1, G2, G3]),
                     lambda: put(self.root, DEC + "/DEC-20261031-k3f9.yml", "id: [unclosed\n")]
        for setup in scenarios:
            setup()
            before = snapshot(self.root)
            self.run_root()
            self.assertEqual(snapshot(self.root), before)

    def test_fixture_repo_starts_no_auto_maintenance(self):  # X1, X2 (F-20261124-v9q9)
        self.assertEqual(git(self.root, "config", "--get", "maintenance.auto"), "false")
        self.assertEqual(git(self.root, "config", "--get", "gc.auto"), "0")
        trace = os.path.join(self.tmp, "trace2.jsonl")
        git(self.root, "commit", "-q", "--allow-empty", "-m", "traced", env={"GIT_TRACE2_EVENT": trace})
        with open(trace, encoding="utf-8") as fh:
            events = [json.loads(line) for line in fh if line.strip()]
        self.assertTrue(any(e.get("event") == "start" for e in events))  # the trace is live
        for e in events:
            if e.get("event") == "child_start":
                self.assertFalse({"maintenance", "gc"} & set(e.get("argv", [])), e)

    def test_gate_creates_no_directory(self):  # O7
        self.run_root()
        self.assertFalse(os.path.exists(os.path.join(self.root, "docs")))
        self.assertFalse(os.path.exists(os.path.join(self.root, "docs", "strict-delivery")))


class Registries(unittest.TestCase):
    def test_cites_enabled(self):  # C1-C3
        self.assertEqual(gates_main.GATES["cites"], "gates.gate_cites")
        self.assertIn("cites", run_all.PROFILE_GATES["standard"])
        self.assertIn("cites", run_all.PROFILE_GATES["strict"])
        self.assertNotIn("cites", run_all.PROFILE_GATES["light"])

    @unittest.skipUnless("index" in run_all.PROFILE_GATES["standard"], "Rq-5-3 not on this branch")
    def test_index_in_standard_and_strict_only(self):  # C4
        self.assertIn("index", run_all.PROFILE_GATES["standard"])
        self.assertIn("index", run_all.PROFILE_GATES["strict"])
        self.assertNotIn("index", run_all.PROFILE_GATES["light"])

    def test_rq_5_3_skip_reason(self):  # C5
        fn = Registries.test_index_in_standard_and_strict_only
        if "index" in run_all.PROFILE_GATES["standard"]:
            self.assertFalse(getattr(fn, "__unittest_skip__", False))
            self.assertNotIn("index", run_all.PROFILE_GATES["light"])
        else:
            self.assertIs(fn.__unittest_skip__, True)
            self.assertEqual(fn.__unittest_skip_why__, "Rq-5-3 not on this branch")

    @unittest.skipUnless("index" in gates_main.GATES, "Rq-5-1 not on this branch")
    def test_gate_index_registered(self):  # A13, C7
        self.assertEqual(gates_main.GATES["index"], "gates.gate_index")


if __name__ == "__main__":
    unittest.main()
