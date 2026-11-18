"""Tests of gates/gate_streams.py through ``gates.__main__.main`` in process and ``python3 -m gates`` in a subprocess
(Task P2.3 input-domain table: the row ids are in the comments). The program fixture is written by hand (decision D-Q23),
the fixture repository's git config sets ``color.ui=always``, ``color.diff=always`` and ``core.abbrev=7`` (plan P:2855).
Expected ids and reason fragments are written from the plan lines P:2829-2841 and the table, never read from the gate."""
import contextlib
import io
import os
import shutil
import subprocess
import sys
import unittest
from unittest import mock

from gates import __main__ as entry
from gates.lib import config, gitinfo, yamlsub
from tests.helpers import E128, GitIsolatedTestCase, commit_all, git, make_repo, minimal_config, root_forms
from tests.test_programs_lib import (BDX, MERGED_HEAD, NAME, PG, PS, SEP, STATUS_TEXT, ckpt, ledger, mline, row, stream)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROGDIR = ".strict-delivery/state/programs/" + NAME
INT, REC = NAME + "/integration", NAME + "/records"
SA, SB = NAME + "/a/main", NAME + "/b/main"
HEADER = "| stream | block | branch | worktree | next task | estimate | used | status | blockers | pending decisions | delivers |"
PLAN_A = ("# plan a\n\n## Global Constraints\n\nrules\n\n### Task a1.1: one\n\nbody one\n\n#### Task a2.1: two\n\nbody two\n\n"
          "### Task b9.9: foreign\n\nforeign body\n")
PROGRAM_PLAN = "# program\n\n## Block a1: x\n\n## Block a2: x\n\n## Block 1a: x\n\n## Block 1b: x\n"
BD = {"plan": "program-plan", "streams": [
    {"id": "a", "tasks": ["a1.1", "a2.1"], "paths": ["a-owned.py", "tests/test_a.py"]},
    {"id": "b", "tasks": ["1a.1", "1b.1"], "paths": ["b-owned.py", "tests/test_b.py"]}], "edges": []}


def streams_row(**kw):
    return row(stream("a", ["a-owned.py", "tests/test_a.py"], merge_order=1),
               stream("b", ["b-owned.py", "tests/test_b.py"], merge_order=2), **kw)


def status_page(streams=("a", "b")):
    rows = ["| %s | none | %s/%s/main | ../w/%s/%s/main | none | 5 | 0 | ready | none | none | p |" % (s, NAME, s, NAME, s)
            for s in streams]
    return "<!-- schema: status/1 -->\n\n%s\n%s\n%s\n" % (HEADER, "|---|---|---|---|---|---|---|---|---|---|---|", "\n".join(rows))


class Fx(GitIsolatedTestCase):
    def setUp(self):
        super().setUp()
        self.root = make_repo(self.work, minimal_config())
        for k, v in (("color.ui", "always"), ("color.diff", "always"), ("core.abbrev", "7")):
            git(self.root, "config", k, v)
        self.cfg = config.load(self.root)
        self.put(PG + "/a-plan.md", PLAN_A)
        self.put(PG + "/program-plan.md", PROGRAM_PLAN)
        self.put("a-owned.py", "a\n")
        self.put("b-owned.py", "b\n")
        self.put("tests/test_b.py", "b\n")
        self.put("tests/test_a.py", "a\n")
        self.put("tests/helpers.py", "h\n")
        commit_all(self.root, "base")

    # ---- fixture helpers
    def put(self, rel, text):
        path = os.path.join(self.root, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)

    def commit(self, files, msg="c"):
        for rel, text in files.items():
            self.put(rel, text)
        return commit_all(self.root, msg)

    progdir = PROGDIR
    ps = PS

    def program(self, merged=MERGED_HEAD, streams=None, bd=BD, status=None, requests=None, base="main", back="main"):
        """The program on ``<p>/integration`` cut from ``base``; HEAD is left on ``back`` (``main``)."""
        git(self.root, "checkout", "-q", "-b", INT, base)
        d = self.progdir + "/"
        self.put(d + "streams.yml", yamlsub.emit(streams or streams_row()))
        self.put(d + "status.md", status or status_page())
        self.put(d + "sync-log.md", "<!-- schema: sync-log/1 -->\n")
        self.put(d + "merged.md", merged)
        for rid, r in (requests or {}).items():
            self.put("%s/requests/%s.yml" % (d, rid), yamlsub.emit(r))
        if bd is not None:
            self.put(self.ps + "/program-plan/breakdown.yml", yamlsub.emit(bd))
        commit_all(self.root, "program")
        git(self.root, "checkout", "-q", back)

    def branch(self, name, at="main"):
        git(self.root, "checkout", "-q", "-b", name, at)

    def pr(self, branch, sid, lines=(), files=None):
        """A branch off main holding stream ``sid``'s ledger, merged into main with ``--no-ff``: ``(head, merge)``."""
        git(self.root, "checkout", "-q", "-b", branch, "main")
        self.put("%s/%s-plan/ledger.md" % (self.ps, sid), ledger(*lines))
        for rel, text in (files or {}).items():
            self.put(rel, text)
        head = commit_all(self.root, "work " + branch)
        git(self.root, "checkout", "-q", "main")
        git(self.root, "merge", "-q", "--no-ff", "-m", "Merge " + branch, branch)
        return head, git(self.root, "rev-parse", "HEAD")

    def run_gate(self, *argv, root=None):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = entry.main(["check", "streams", "--root", root or self.root] + list(argv))
        return buf.getvalue(), code

    def subprocess_gate(self, *argv, python=None):
        p = subprocess.run([python or sys.executable, "-m", "gates", "check", "streams", "--root", self.root] + list(argv),
                           cwd=REPO, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return p.stdout.decode("utf-8"), p.returncode

    def ids(self, out):
        return [l.split(":")[0].split(" ", 1)[1] for l in out.splitlines()]


class Basics(Fx):
    def test_no_live_program_passes_with_one_line(self):  # BR4, OU3
        out, code = self.run_gate()
        self.assertEqual((out.strip(), code), ("PASS streams.none", 0))
        self.assertEqual(self.subprocess_gate(), (out, 0))

    def test_detached_without_branch_is_input_fail(self):  # AV2, AV3 (D-Q3 (a))
        git(self.root, "checkout", "-q", "--detach")
        out, code = self.run_gate()
        self.assertTrue(out.startswith("FAIL streams.input:"), out)
        self.assertEqual((len(out.splitlines()), code), (1, 1))

    def test_branch_value_forms(self):  # AV6 (D-Q4 (b)); AV7, AV8
        for bad in ("", "a..b", "a b", "a~b", "a@{b", "a.lock", "a/", "/a", "x\ny", "-x", "@", "a//b", "a.", "a/.b", "a/b.lock/c", "a\\b", "a:b", "a^b", "a?b", "a*b", "a[b", "a\x7fb", "x" * 256):
            with self.subTest(bad=bad):
                out, code = self.run_gate("--branch", bad)
                self.assertTrue(out.startswith("FAIL streams.input:"), out)
                self.assertEqual(code, 1)
        self.assertEqual(self.run_gate("--branch=feature/x")[0], "PASS streams.none\n")
        self.assertEqual(self.run_gate("--branch", "x" * 255)[0], "PASS streams.none\n")
        self.assertEqual(self.run_gate("--branch", "a@b")[0], "PASS streams.none\n")
        self.assertEqual(self.run_gate("--base", "nosuch")[0], "PASS streams.none\n")   # ignored
        self.assertIn("more than once", self.run_gate("--branch", "a", "--branch", "b")[0])

    def test_registration_and_produces(self):  # AV13, AV14
        self.assertEqual(entry.GATES["streams"], "gates.gate_streams")
        from gates import gate_streams
        self.assertEqual(gate_streams.PRODUCES, ())

    def test_malformed_program_branch_fails_branch(self):  # BR7
        for name in (NAME + "/a", NAME + "/a/g/h", NAME + "/records/main", NAME + "/a/main/main"):
            with self.subTest(name=name):
                out, code = self.run_gate("--branch", name)
                self.assertTrue(out.startswith("FAIL streams.branch:"), out)
                self.assertEqual((len(out.splitlines()), code), (1, 1))
        self.assertEqual(self.run_gate("--branch", "20261301-x/a/main")[0], "PASS streams.none\n")  # not a program name

    def test_program_branch_without_integration_fails_input(self):  # BR5, IG8
        self.branch(SA)
        out, code = self.run_gate()
        self.assertTrue(out.startswith("FAIL streams.input:") and "integration" in out, out)
        self.assertEqual(code, 1)

    def test_shallow_clone_fails_input(self):  # D-Q5 (b)
        self.program()
        clone = os.path.join(self.tmp, "clone")
        git(self.tmp, "clone", "-q", "--depth", "1", "file://" + self.root, clone)
        git(clone, "checkout", "-q", "-b", INT, "origin/main")
        out, _ = self.run_gate("--branch", SA, root=clone)
        self.assertEqual(out.split(":")[0], "FAIL streams.input")


class Files(Fx):
    def test_valid_program_on_main(self):  # BR3, BR10, MP1, ST1, RQ6
        self.program()
        out, code = self.run_gate()
        self.assertEqual(out, "PASS streams.map.%s\nPASS streams.status.%s\nPASS streams.request\n" % (NAME, NAME))
        self.assertEqual(code, 0)

    def test_remote_only_integration_not_live(self):  # BR12
        self.program()
        git(self.root, "branch", "-m", INT, "other/x")
        self.assertEqual(self.run_gate()[0], "PASS streams.none\n")

    def test_status_errors_surface(self):  # ST2, ST5
        self.program(status=status_page(("a",)))
        out, code = self.run_gate()
        self.assertIn("FAIL streams.status.%s: missing row for stream b" % NAME, out)
        self.assertEqual(code, 1)

    def test_request_errors_surface(self):  # RQ2
        bad = {"schema": "request/1", "id": "R-20261101-abcd", "from_stream": "a", "to_stream": "a", "files": ["a-owned.py"],
               "interface": "docs/x.md#y", "need": "n", "status": "open", "raised_at": {"sha": "a" * 7, "by": "a"}}
        self.program(requests={"R-20261101-abcd": bad})
        out, _ = self.run_gate()
        self.assertIn("FAIL streams.request.from.R-20261101-abcd:", out)

    def test_map_streams_changed_without_breakdown(self):  # MP17, OW28 surface
        other = {"plan": "program-plan", "streams": [dict(BD["streams"][0], paths=["a-owned.py"]), BD["streams"][1]], "edges": []}
        self.program(bd=other)
        out, _ = self.run_gate()
        self.assertIn("FAIL streams.map.%s:" % NAME, out)

    def test_map_breakdown_missing(self):  # ME13 (Q16 (a))
        self.program(bd=None)
        out, _ = self.run_gate()
        self.assertIn("FAIL streams.map.%s:" % NAME, out)
        self.assertIn("breakdown.yml is missing", out)

    def test_map_unknown_stream_and_block_without_heading(self):  # MP2, MP3
        head, m = self.pr("p1", "a", [ckpt("a1", "a1.1", "a" * 7)])
        self.program(merged=MERGED_HEAD + mline(1, head, m, "zz", "a1") + "\n")
        out, _ = self.run_gate()
        self.assertIn("FAIL streams.map.%s:" % NAME, out)
        self.assertIn("unknown stream zz", out)

    def test_map_counted_rows(self):  # MP5-MP12 through one pull request that carries a1 and a2
        a7 = git(self.root, "rev-parse", "--short=7", "HEAD")
        head, m = self.pr("p1", "a", [ckpt("a1", "a1.1", a7), ckpt("a2", "a2.1", a7)])
        good = MERGED_HEAD + mline(1, head, m, "a", "a2") + "\n"
        self.program(merged=good)
        self.assertIn("PASS streams.map", self.run_gate()[0])
        git(self.root, "branch", "-D", INT)
        self.program(merged=MERGED_HEAD + mline(1, head, m, "a", "a1") + "\n")      # MP6: not the last newly carried
        self.assertIn("FAIL streams.map", self.run_gate()[0])
        git(self.root, "branch", "-D", INT)
        self.program(merged=MERGED_HEAD + mline(1, head, m, "b", "1a") + "\n")      # MP11: block of another stream
        self.assertIn("FAIL streams.map", self.run_gate()[0])

    def test_map_copy_rows(self):  # MP5 / ME20-ME22
        a7 = git(self.root, "rev-parse", "--short=7", "HEAD")
        head, m = self.pr("p1", "a", [ckpt("a1", "a1.1", a7), ckpt("a2", "a2.1", a7)])
        line = mline(1, head, m, "a", "a2")
        self.program(merged=MERGED_HEAD + line + "\n")
        self.assertIn("PASS streams.map", self.run_gate()[0])                        # ME22: main's ledger holds no such pr
        git(self.root, "checkout", "-q", "main")
        for text, want in ((line, "PASS"), (line.replace("merged_by=owner", "merged_by=other"), "FAIL")):
            self.commit({"%s/a-plan/ledger.md" % PS: ledger(ckpt("a1", "a1.1", a7), text)})
            out = self.run_gate()[0]
            self.assertIn("%s streams.map" % want, out)
            git(self.root, "reset", "-q", "--hard", "HEAD~1")


class Owned(Fx):
    def stream(self, files, name=SA, msg="c"):
        self.branch(name)
        return self.commit(files, msg)

    def setUp(self):
        super().setUp()
        self.program()

    def test_own_change_passes(self):  # OW1, BS1
        self.stream({"a-owned.py": "a2\n"})
        out, code = self.run_gate()
        self.assertIn("PASS streams.owned\n", out)
        self.assertEqual(code, 0)

    def test_other_streams_file_fails(self):  # OW2, OW30
        self.stream({"b-owned.py": "x\n"})
        out, code = self.run_gate()
        self.assertIn("FAIL streams.owned.b-owned.py: owned by stream b", out)
        self.assertEqual(code, 1)

    def test_unowned_path_names_stream_ownership(self):  # OW3
        self.stream({"new.txt": "x\n"})
        out, _ = self.run_gate()
        self.assertIn("FAIL streams.owned.new.txt:", out)
        self.assertIn("stream-ownership", out)

    def test_other_streams_test_file_passes_any_other_path_fails(self):  # TF1-TF4, TF14, TF6
        self.stream({"tests/test_b.py": "x\n"})
        out, code = self.run_gate()
        self.assertIn("PASS streams.owned", out)
        self.assertEqual(code, 0)
        self.commit({"tests/helpers.py": "x\n", "tests/test_unowned.py": "x\n", "b-owned.py": "x\n", "a-owned.py": "y\n"})
        out = self.run_gate()[0]
        for path in ("tests/helpers.py", "tests/test_unowned.py", "b-owned.py"):
            self.assertIn("FAIL streams.owned.%s:" % path, out)
        self.assertNotIn("streams.owned.a-owned.py", out)
        self.assertNotIn("streams.owned.tests/test_b.py", out)
        os.environ["PR_BODY"] = "other"
        try:
            self.assertEqual(self.run_gate()[0], out)
        finally:
            del os.environ["PR_BODY"]

    def test_test_file_glob_forms(self):  # TF7, TF15
        from gates import gate_streams
        for path, want in (("tests/test_x.py", True), ("tests/test_.py", False), ("tests/test_x.py.bak", False),
                           ("tests/test_x.PY", False), ("tests/Test_x.py", False), ("Tests/test_x.py", False),
                           ("tests/sub/test_x.py", False), ("tests/test_a/b.py", False), ("src/tests/test_x.py", False),
                           ("test_x.py", False), ("tests/__init__.py", False), ("tests/test_Ⱞ.py", True)):
            self.assertIs(gate_streams._is_test_file(path), want, path)

    def test_program_folder_and_records_fail(self):  # OW7-OW9
        self.stream({PROGDIR + "/status.md": "x\n", "docs/strict-delivery/plans/program-plan.md": "y\n",
                     ".strict-delivery/state/decisions/x.yml": "z\n", PROGDIR + "/requests/R-1.yml": "q\n"})
        out = self.run_gate()[0]
        for path in (PROGDIR + "/status.md", PG + "/program-plan.md", ".strict-delivery/state/decisions/x.yml"):
            self.assertIn("FAIL streams.owned.%s:" % path, out)
        self.assertIn("requests/R-1.yml", out)

    def test_own_and_foreign_plan_workspace(self):  # OW5, OW6
        self.stream({PS + "/a-plan/x.md": "x\n", PS + "/b-plan/x.md": "x\n"})
        out = self.run_gate()[0]
        self.assertNotIn("a-plan/x.md", out)
        self.assertIn("FAIL streams.owned.%s/b-plan/x.md:" % PS, out)

    def test_change_then_revert_still_fails(self):  # BS11
        self.stream({"b-owned.py": "x\n"})
        self.commit({"b-owned.py": "b\n"})
        self.assertIn("FAIL streams.owned.b-owned.py", self.run_gate()[0])

    def test_rename_and_deletion(self):  # OW11, OW12
        self.branch(SA)
        os.remove(os.path.join(self.root, "b-owned.py"))
        os.rename(os.path.join(self.root, "a-owned.py"), os.path.join(self.root, "b-owned.py"))
        commit_all(self.root, "rename")
        self.assertIn("FAIL streams.owned.b-owned.py", self.run_gate()[0])

    def test_untracked_not_judged_tree_judged(self):  # OW13, BS13, OW27
        self.branch(SA)
        self.put("untracked.py", "x\n")
        self.assertIn("PASS streams.owned", self.run_gate()[0])
        self.put("b-owned.py", "edited\n")
        self.assertIn("FAIL streams.owned.b-owned.py: owned by stream b (the tree being committed)", self.run_gate()[0])
        git(self.root, "checkout", "--", "b-owned.py")
        self.put("b-owned.py", "staged\n")
        git(self.root, "add", "b-owned.py")
        os.remove(os.path.join(self.root, "b-owned.py"))
        self.assertIn("FAIL streams.owned.b-owned.py", self.run_gate()[0])      # D-Q13: staged then deleted

    def test_group_branch_judged_as_stream(self):  # OW26, BR9
        self.stream({"b-owned.py": "x\n"}, name=NAME + "/a/g1")
        self.assertIn("FAIL streams.owned.b-owned.py", self.run_gate()[0])

    def test_unknown_stream_branch(self):  # BR8 (D-Q8 (a))
        self.stream({"a-owned.py": "x\n"}, name=NAME + "/zzz/main")
        out = self.run_gate()[0]
        self.assertTrue(out.startswith("FAIL streams.branch: stream zzz is not in streams.yml"), out)

    def test_main_advanced_not_judged(self):  # BS2
        self.branch(SA)
        git(self.root, "checkout", "-q", "main")
        self.commit({"b-owned.py": "main moved\n"})
        git(self.root, "checkout", "-q", SA)
        self.assertIn("PASS streams.owned", self.run_gate()[0])

    def test_main_merge_exempt_integration_merge_fails(self):  # OW23, IG1, IG3
        self.stream({"a-owned.py": "x\n"})
        git(self.root, "checkout", "-q", "main")
        self.commit({"b-owned.py": "main moved\n"})
        git(self.root, "checkout", "-q", SA)
        git(self.root, "merge", "-q", "--no-ff", "-m", "sync", "main")
        out, code = self.run_gate()
        self.assertIn("PASS streams.owned", out)
        self.assertIn("PASS streams.integration", out)
        self.assertEqual(code, 0)
        git(self.root, "checkout", "-q", INT)
        self.commit({PROGDIR + "/sync-log.md": "<!-- schema: sync-log/1 -->\nx\n"})
        git(self.root, "checkout", "-q", SA)
        git(self.root, "merge", "-q", "--no-ff", "-m", "bad", INT)
        out, code = self.run_gate()
        self.assertIn("FAIL streams.integration.", out)
        self.assertEqual(code, 1)

    def test_group_merge_after_combined_testing_passes(self):  # IG4, IG10 (operand order and the second filter: mutants #26-#29), owner answer Q-A11-1 (c)
        self.branch(NAME + "/a/g1")
        self.commit({"a-owned.py": "g\n"})
        git(self.root, "checkout", "-q", "-b", SA, "main")
        git(self.root, "merge", "-q", "--no-ff", "-m", "group", NAME + "/a/g1")
        git(self.root, "checkout", "-q", INT)
        git(self.root, "merge", "-q", "--no-ff", "-m", "combined", SA)
        git(self.root, "checkout", "-q", SA)
        out, code = self.run_gate()
        self.assertIn("PASS streams.integration", out)
        self.assertEqual(code, 0)

    def test_merge_of_integration_only_commit_fails(self):  # IG5, IG2 (group, records)
        for kind in (SA, NAME + "/a/g1", REC):
            git(self.root, "checkout", "-q", "-B", kind, "main")
            self.commit({PS + "/program-plan/x.md": "x\n"} if kind == REC else {"a-owned.py": kind + "\n"})
            git(self.root, "merge", "-q", "--no-ff", "-m", "bad", INT)
            self.assertIn("FAIL streams.integration.", self.run_gate()[0], kind)

    def test_shared_rules(self):  # SH1-SH8
        sh = [{"path": "reg.md", "rule": "append-rows"}, {"path": "own.md", "rule": "own-row"}]
        git(self.root, "branch", "-D", INT)
        git(self.root, "checkout", "-q", "main")
        self.commit({"reg.md": "| h |\n| r1 |\n", "own.md": "| a | 1 |\n| b | 2 |\n"})
        self.program(streams=streams_row(shared=sh))
        self.branch(SA)
        self.commit({"reg.md": "| h |\n| r1 |\n| r2 |\n", "own.md": "| a | 9 |\n| b | 2 |\n| a | 3 |\n"})
        out = self.run_gate()[0]
        self.assertIn("PASS streams.shared", out)
        for text, want in (("| h |\n| r1x |\n", "reg.md"), ("| h |\n| new |\n| r1 |\n", "reg.md"), ("| h |\n| r1 |\nnote\n", "reg.md")):
            self.commit({"reg.md": text})
            self.assertIn("FAIL streams.shared.%s:" % want, self.run_gate()[0], text)
            self.commit({"reg.md": "| h |\n| r1 |\n"})
        self.commit({"own.md": "| a | 1 |\n| b | 7 |\n"})
        self.assertIn("FAIL streams.shared.own.md:", self.run_gate()[0])

    def test_plan_file_exception(self):  # PF1-PF3, PF14, PF15
        own = PLAN_A.replace("body one", "body one edited")
        self.stream({PG + "/a-plan.md": own})
        self.assertIn("PASS streams.owned", self.run_gate()[0])
        self.commit({PG + "/a-plan.md": own.replace("body two", "body two edited")})
        self.assertIn("PASS streams.owned", self.run_gate()[0])
        self.commit({PG + "/a-plan.md": own.replace("foreign body", "foreign edited")})
        self.assertIn("FAIL streams.owned.%s/a-plan.md: plan hunk at line 17" % PG, self.run_gate()[0])
        self.commit({PG + "/a-plan.md": own.replace("rules", "rules edited")})
        self.assertIn("plan hunk at line 5 lies outside", self.run_gate()[0])


class Integration(Fx):
    def setUp(self):
        super().setUp()
        self.program()
        git(self.root, "checkout", "-q", INT)

    def test_program_records_pass_and_code_fails(self):  # IN1, IN2, IN15
        self.commit({PROGDIR + "/sync-log.md": "<!-- schema: sync-log/1 -->\nx\n", ".strict-delivery/state/findings/x.yml": "x\n",
                     PS + "/program-plan/ledger.md": "x\n"})
        self.assertIn("PASS streams.owned", self.run_gate()[0])
        self.commit({"src/x.py": "x\n", PS + "/a-plan/x": "x\n"})
        out, code = self.run_gate()
        self.assertIn("FAIL streams.owned.src/x.py:", out)
        self.assertIn("FAIL streams.owned.%s/a-plan/x:" % PS, out)
        self.assertEqual(code, 1)

    def test_tree_being_committed_integration(self):  # IN4
        self.put("src/x.py", "x\n")
        git(self.root, "add", "src/x.py")
        self.assertIn("FAIL streams.owned.src/x.py:", self.run_gate()[0])

    def test_merge_of_main_exempt_combined_merge_owned_paths(self):  # IN5, IN6, IN7, IN14 (the base of the integration range is base_branch)
        self.branch(SA, "main")
        self.commit({"a-owned.py": "x\n"})
        git(self.root, "checkout", "-q", INT)
        git(self.root, "merge", "-q", "--no-ff", "-m", "combined", SA)
        self.assertIn("PASS streams.owned", self.run_gate()[0])
        self.branch(SB, "main")
        self.commit({"tests/test_a.py": "y\n", "b-owned.py": "y\n"})
        git(self.root, "checkout", "-q", INT)
        git(self.root, "merge", "-q", "--no-ff", "-m", "combined b", SB)
        out = self.run_gate()[0]
        self.assertIn("FAIL streams.owned.tests/test_a.py:", out)
        self.assertNotIn("streams.owned.b-owned.py", out)
        git(self.root, "checkout", "-q", "main")
        self.commit({"src/main_moved.py": "main\n"})
        git(self.root, "checkout", "-q", INT)
        git(self.root, "merge", "-q", "--no-ff", "-m", "sync", "main")
        self.assertIn("FAIL streams.owned.tests/test_a.py:", self.run_gate()[0])      # the earlier merge is still judged

    def test_unknown_merge_fails(self):  # IN7
        self.branch("other/x", "main")
        self.commit({"z.txt": "z\n"})
        git(self.root, "checkout", "-q", INT)
        git(self.root, "merge", "-q", "--no-ff", "-m", "m", "other/x")
        self.assertIn("FAIL streams.owned.z.txt: no stream or group branch reaches the second parent", self.run_gate()[0])

    def test_merge_in_progress(self):  # IN10, IN11
        self.branch(SA, "main")
        self.commit({"a-owned.py": "x\n"})
        git(self.root, "checkout", "-q", INT)
        git(self.root, "merge", "-q", "--no-ff", "--no-commit", SA)
        self.assertIn("PASS streams.owned", self.run_gate()[0])
        self.put("b-owned.py", "x\n")
        self.assertIn("FAIL streams.owned.b-owned.py:", self.run_gate()[0])


class Records(Fx):
    def test_records_branch(self):  # RC1-RC6
        self.program()
        self.branch(REC)
        self.commit({".strict-delivery/state/decisions/d.yml": "x\n", PG + "/program-plan.md": "y\n",
                     PS + "/program-plan/ledger.md": "z\n"})
        self.assertIn("PASS streams.owned", self.run_gate()[0])
        self.commit({"src/x.py": "x\n", PROGDIR + "/status.md": "s\n", PS + "/a-plan/x": "x\n"})
        out = self.run_gate()[0]
        for p in ("src/x.py", PROGDIR + "/status.md", PS + "/a-plan/x"):
            self.assertIn("FAIL streams.owned.%s:" % p, out)


def W(path, a=None, b=None):
    d = {"path": path}
    if a:
        d["from"] = a
    if b:
        d["until"] = b
    return d


def bd_of(*ss):
    """The breakdown that agrees with the streams ``ss`` (same owns, tasks by stream id)."""
    tasks = {"a": ["a1.1", "a2.1"], "b": ["1a.1", "1b.1"], "r": ["R1.1"]}
    out = []
    for s in ss:
        e = {"id": s["id"], "tasks": tasks[s["id"]]}
        if s.get("residual"):
            e["residual"] = True
        else:
            e["paths"] = list(s["owns"])
        out.append(e)
    return {"plan": "program-plan", "streams": out, "edges": []}


class Windows(Fx):
    """Window rows: a owns ``w.py`` until ``merged:a/a1``, b owns it from ``merged:a/a1`` (chained)."""

    def layout(self, a_owns=None, b_owns=None, residual=False, **akw):
        a = stream("a", ["a-owned.py", "tests/test_a.py"] + (a_owns if a_owns is not None else [W("w1.py", None, "merged:a/a1")]),
                   merge_order=1, **akw)
        b = stream("b", ["b-owned.py", "tests/test_b.py"] + (b_owns if b_owns is not None else [W("w1.py", "merged:a/a1")]),
                   merge_order=2)
        ss = [a, b]
        if residual:
            ss.append(stream("r", residual=True, period=("program-start", "program-close"), merge_order=3))
        return row(*ss), bd_of(*ss), ("a", "b", "r") if residual else ("a", "b")

    def merge_line(self, n, block, sid="a", ckpts=None, branch=None, h7=None):
        """A pull request on main carrying ``block`` of stream ``sid``; returns ``(head, merge, line)``."""
        h7 = h7 or git(self.root, "rev-parse", "--short=7", "HEAD")
        tid = {"a1": "a1.1", "a2": "a2.1", "1a": "1a.1", "1b": "1b.1", "R1": "R1.1"}
        lines = [ckpt(b, tid[b], h7) for b in (ckpts or [block])]
        head, m = self.pr(branch or "pr%d" % n, sid, lines)
        return head, m, mline(n, head, m, sid, block)

    def prog(self, lines, residual=False, **kw):
        streams, bd, names = self.layout(residual=residual, **kw)
        self.program(merged=MERGED_HEAD + "".join(l + "\n" for l in lines), streams=streams, bd=bd, status=status_page(names))

    def test_two_open_windows_fail_naming_both(self):  # MP4, OW15
        streams, bd, names = self.layout(a_owns=[W("w1.py", None, "merged:a/a2")], b_owns=[W("w1.py", "merged:a/a1")])
        _, _, line = self.merge_line(1, "a1")
        self.program(merged=MERGED_HEAD + line + "\n", streams=streams, bd=bd, status=status_page(names))
        self.branch(SA)
        self.commit({"w1.py": "x\n"})
        out, code = self.run_gate()
        self.assertIn("FAIL streams.map.%s: " % NAME, out)
        self.assertIn("owns: w1.py (stream a) overlaps w1.py (stream b)", out)
        self.assertIn("FAIL streams.owned.w1.py: stream a and stream b are both open for it", out)
        self.assertEqual(code, 1)

    def test_window_gap_is_residuals(self):  # OW14, OW18
        _, _, line = self.merge_line(1, "a1")
        self.prog([line], residual=True, b_owns=[W("w1.py", "merged:b/1a")])
        self.branch(SA)
        self.commit({"w1.py": "x\n"})
        self.assertIn("FAIL streams.owned.w1.py: owned by stream r", self.run_gate()[0])
        self.branch(NAME + "/r/main")
        self.commit({"w1.py": "y\n"})
        out = self.run_gate()[0]
        self.assertIn("PASS streams.owned\n", out)
        self.commit({"b-owned.py": "y\n"})                     # a path in another stream's open window
        self.assertIn("FAIL streams.owned.b-owned.py: owned by stream b", self.run_gate()[0])

    def test_path_before_from_after_until(self):  # OW16, OW19 (own window passes)
        _, _, line = self.merge_line(1, "a1")
        self.prog([line], residual=True, b_owns=[W("w1.py", "merged:b/1a")])
        self.branch(SB)
        self.commit({"w1.py": "x\n"})
        self.assertIn("FAIL streams.owned.w1.py: owned by stream r", self.run_gate()[0])       # after a's until, before b's from
        self.branch(SA)
        self.commit({"w1.py": "y\n"})
        self.assertIn("FAIL streams.owned.w1.py: owned by stream r", self.run_gate()[0])       # a's own path after its until

    def test_event_ancestry_per_commit(self):  # OW17, ME4, ME17, ME18
        self.branch(SB)
        git(self.root, "checkout", "-q", "main")
        streams, bd, names = self.layout(a_owns=[W("w1.py", None, "merged:a/a1"), W("w2.py", None, "merged:a/a2")],
                                         b_owns=[W("w1.py", "merged:a/a1"), W("w2.py", "merged:a/a2")])
        _, m1, l1 = self.merge_line(1, "a1")
        h7 = git(self.root, "rev-parse", "--short=7", "HEAD")
        head2, m2 = self.pr("pr2", "a", [ckpt("a1", "a1.1", h7), ckpt("a2", "a2.1", h7)])
        l2 = mline(2, head2, m2, "a", "a2")
        self.program(merged=MERGED_HEAD + l1 + "\n" + l2 + "\n", streams=streams, bd=bd, status=status_page(names))
        git(self.root, "checkout", "-q", SB)
        c = {}
        c[1] = self.commit({"w1.py": "1\n"})
        git(self.root, "merge", "-q", "--no-ff", "-m", "sync1", m1)
        c[2] = self.commit({"w1.py": "2\n"})
        c[3] = self.commit({"w2.py": "3\n"})
        git(self.root, "merge", "-q", "--no-ff", "-m", "sync2", m2)
        c[4] = self.commit({"w2.py": "4\n"})
        out, code = self.run_gate()
        # the oracle: a commit fails for its path when the path's opening merge is not an ancestor of it
        want = {"w1.py": [c[i] for i in c if not self.is_anc(m1, c[i]) and i in (1, 2)],
                "w2.py": [c[i] for i in c if not self.is_anc(m2, c[i]) and i in (3, 4)]}
        self.assertEqual((want["w1.py"], want["w2.py"]), ([c[1]], [c[3]]))
        for path, bad in want.items():
            line = [l for l in out.splitlines() if l.startswith("FAIL streams.owned.%s:" % path)]
            self.assertEqual(len(line), 1, out)
            self.assertIn("(%s)" % bad[0][:7], line[0])
            for i in c:
                if c[i] not in bad and path[1] == str(1 if i in (1, 2) else 2):
                    self.assertNotIn(c[i][:7], line[0])
        self.assertEqual(code, 1)
        git(self.root, "checkout", "-q", "-b", "tip", c[4])
        self.assertTrue(self.is_anc(m2, "HEAD"))                                                 # ME18: HEAD holds both

    def is_anc(self, a, b):
        p = subprocess.run(["git", "-C", self.root, "merge-base", "--is-ancestor", a, b])
        return p.returncode == 0

    def test_streams_ignore_colour_and_abbrev_config(self):  # EN1, EN2
        _, _, line = self.merge_line(1, "a1")
        self.prog([line])
        self.branch(SA)
        self.commit({"b-owned.py": "x\n"})
        first = self.run_gate()
        for k, v in (("color.ui", "never"), ("color.diff", "never"), ("core.abbrev", "12"), ("color.branch", "always"),
                     ("diff.renames", "true"), ("log.showSignature", "true")):
            git(self.root, "config", k, v)
        self.assertEqual(self.run_gate(), first)
        self.assertEqual(first[1], 1)
        self.assertNotIn("\x1b", first[0])


class Stacked(Fx):
    """Stacked rows: ``a`` is stacked on ``b``; the parent branch ``SB`` holds ``b``'s work until ``merged:b`` holds."""

    merge_line = Windows.merge_line

    def stacked_program(self, lines=(), stacked=True):
        a = stream("a", ["a-owned.py", "tests/test_a.py"], merge_order=2, **({"stacked_on": "b"} if stacked else {}))
        b = stream("b", ["b-owned.py", "tests/test_b.py"], merge_order=1)
        bd = bd_of(a, b)
        bd["edges"] = [{"from": x, "to": y} for x in ("1a.1", "1b.1") for y in ("a1.1", "a2.1")]
        self.program(merged=MERGED_HEAD + "".join(l + "\n" for l in lines), streams=row(a, b), bd=bd, status=status_page(("a", "b")))

    def parent_and_child(self):
        self.branch(SB)
        self.commit({"b-owned.py": "b1\n"})
        self.commit({"b-owned.py": "b2\n"})
        self.branch(SA, SB)
        self.commit({"a-owned.py": "a1\n"})

    def b_merged_line(self):
        git(self.root, "checkout", "-q", "main")
        return self.merge_line(1, "1b", sid="b", ckpts=["1a", "1b"], branch="prb")

    def test_stacked_before_and_after(self):  # BS4, BS5, OW22
        self.parent_and_child()
        _, m, line = self.b_merged_line()
        self.stacked_program([line])
        git(self.root, "checkout", "-q", SA)
        out, code = self.run_gate()
        self.assertIn("PASS streams.owned\n", out)                  # BS4: base is SB, b's commits in the parent are not judged
        self.assertEqual(code, 0, out)
        git(self.root, "merge", "-q", "--no-ff", "-m", "sync", m)
        out, code = self.run_gate()                                  # BS5: merged:b holds, base is main, b's commits are judged
        self.assertIn("FAIL streams.owned.b-owned.py: owned by stream b", out)
        self.assertEqual(code, 1)

    def test_stacked_parent_branch_missing(self):  # BS6
        self.parent_and_child()
        self.stacked_program()
        git(self.root, "checkout", "-q", SA)
        git(self.root, "branch", "-D", SB)
        out, code = self.run_gate()
        self.assertTrue(out.startswith("FAIL streams.input:"), out)
        self.assertEqual(code, 1)

    def test_stacked_parent_merge_exempt(self):  # OW24, IG6
        for stacked, want in ((True, "PASS streams.owned\n"), (False, "FAIL streams.owned.b-owned.py")):
            with self.subTest(stacked=stacked):
                self.branch(SB)
                self.commit({"b-owned.py": "b1\n"})
                self.stacked_program(stacked=stacked)
                self.branch(SA)
                self.commit({"a-owned.py": "a1\n"})
                git(self.root, "merge", "-q", "--no-ff", "-m", "take parent", SB)
                out, _ = self.run_gate()
                self.assertIn(want, out)
                git(self.root, "checkout", "-q", "main")
                for b in (SA, SB, INT):
                    git(self.root, "branch", "-D", b)


class Carried(Windows):
    """Carried sets (ME2, ME5-ME8, ME10): b's windows open at ``merged:b/1a``, ``merged:b/1b`` and ``merged:b``."""

    def probe(self, ckpts, block, h7=None):
        """Merge one PR of stream b, cut a branch from main, change each window path as b; the failing paths."""
        layout = {"a_owns": [W("w1a.py", None, "merged:b/1a"), W("w1b.py", None, "merged:b/1b"), W("wall.py", None, "merged:b")],
                  "b_owns": [W("w1a.py", "merged:b/1a"), W("w1b.py", "merged:b/1b"), W("wall.py", "merged:b")]}
        streams, bd, names = self.layout(**layout)
        _, _, line = self.merge_line(1, block, sid="b", ckpts=ckpts, h7=h7)
        self.program(merged=MERGED_HEAD + line + "\n", streams=streams, bd=bd, status=status_page(names))
        self.branch(SB)
        self.commit({"w1a.py": "x\n", "w1b.py": "x\n", "wall.py": "x\n"})
        out = self.run_gate()[0]
        self.assertIn("PASS streams.map", out)
        return sorted(l.split(":")[0][len("FAIL streams.owned."):] for l in out.splitlines() if l.startswith("FAIL streams.owned."))

    def test_one_pr_carries_both_sub_blocks(self):  # ME2, ME5
        self.assertEqual(self.probe(["1a", "1b"], "1b"), [])

    def test_one_task_missing_checkpoint(self):  # ME7
        self.assertEqual(self.probe(["1b"], "1b"), ["w1a.py", "wall.py"])

    def test_block_named_is_carried(self):  # ME8
        self.assertEqual(self.probe(["1a"], "1b"), [])

    def test_checkpoint_head_not_ancestor_not_carried(self):  # ME6
        git(self.root, "checkout", "-q", "-b", "side", "main")
        side = self.commit({"side.txt": "s\n"})
        git(self.root, "checkout", "-q", "main")
        self.assertEqual(self.probe(["1a", "1b"], "1b", h7=side[:7]), ["w1a.py", "wall.py"])   # 1b is named (ME8), 1a is not carried

    def test_events_program_start_only(self):  # ME1
        streams, bd, names = self.layout(a_owns=[W("w1.py", None, "merged:b/1a")], b_owns=[W("w1.py", "merged:b/1a")])
        self.program(streams=streams, bd=bd, status=status_page(names))
        self.branch(SB)
        self.commit({"w1.py": "x\n"})
        self.assertIn("FAIL streams.owned.w1.py: owned by stream a", self.run_gate()[0])


class Rows(Fx):
    def stream(self, files, name=SA):
        self.branch(name)
        return self.commit(files)

    def test_branch_defaults_given_detached_differs(self):  # AV1, AV4, AV5, BR13, BR14
        self.program()
        self.stream({"b-owned.py": "x\n"})
        self.assertIn("FAIL streams.owned.b-owned.py", self.run_gate()[0])                  # AV1: current branch
        git(self.root, "tag", SA + "-tag")
        git(self.root, "checkout", "-q", "--detach")
        out, code = self.run_gate("--branch", SA)                                            # AV4/BR13
        self.assertIn("FAIL streams.owned.b-owned.py", out)
        self.assertEqual(code, 1)
        git(self.root, "checkout", "-q", "main")
        self.assertEqual(self.run_gate("--branch", SA)[0].count("FAIL streams.owned"), 0)    # AV5: HEAD (main) is judged
        git(self.root, "tag", "-f", SA, "HEAD")                                              # BR14: a tag of the branch's name
        git(self.root, "checkout", "-q", SA + "-tag")
        self.assertIn("FAIL streams.owned.b-owned.py", self.run_gate("--branch", SA)[0])

    def test_branch_kinds(self):  # BR1, BR2
        self.program()
        for name, kind in ((NAME + "/a/g1", "group"), (SA, "stream"), (INT, "integration"), (REC, "records")):
            git(self.root, "checkout", "-q", "-B", name, "main" if name != INT else INT)
            out = self.run_gate()[0]
            self.assertIn("PASS streams.owned\n", out, name)

    def test_main_json_and_exit_codes(self):  # AV12, AV16, OU5, OU6
        from gates import gate_streams
        self.program()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(gate_streams.main(["--root", self.root]), 0)
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(gate_streams.main(["--root", self.root, "--bogus"]), 1)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            entry.main(["check", "streams", "--json", "--root", self.root])
        out = buf.getvalue()
        self.assertEqual(out.count("\n"), 1)
        self.assertTrue(out.startswith('{"gate": "streams", "ok": true, "lines": ['), out)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            entry.main(["check", "streams", "--root", self.root, "--help"])
        self.assertTrue(out.getvalue().startswith("FAIL streams.input: help requested"), out.getvalue())

    def test_no_forbidden_names_in_new_code(self):  # AV15, V3
        for rel in ("gates/gate_streams.py", "gates/lib/gitinfo.py"):
            with open(os.path.join(REPO, *rel.split("/")), encoding="utf-8") as fh:
                text = fh.read()
            self.assertNotIn("ExceptionGroup", text, rel)
            self.assertNotIn("except*", text, rel)

    def test_status_edit_on_stream_branch_is_owned_fail(self):  # ST4
        self.program()
        self.stream({PROGDIR + "/status.md": "x\n"})
        out = self.run_gate()[0]
        self.assertIn("FAIL streams.owned.%s/status.md:" % PROGDIR, out)
        self.assertIn("PASS streams.status.%s" % NAME, out)

    def test_request_valid(self):  # RQ1
        from tests.test_programs_lib import RID, req_row
        self.program(requests={RID: req_row()})
        self.assertIn("PASS streams.request\n", self.run_gate()[0])

    def test_integration_rows(self):  # IN3, IN13, IN17, IN18, IG7, IG9
        self.program()
        git(self.root, "checkout", "-q", INT)
        self.commit({PS + "/a-plan/x.md": "x\n"})
        self.assertIn("FAIL streams.owned.%s/a-plan/x.md" % PS, self.run_gate()[0])                  # IN3
        git(self.root, "reset", "-q", "--hard", "HEAD~1")
        self.commit({"tests/test_b.py": "x\n"})
        self.assertIn("FAIL streams.owned.tests/test_b.py", self.run_gate()[0])                      # IN18
        git(self.root, "reset", "-q", "--hard", "HEAD~1")
        os.remove(os.path.join(self.root, "a-owned.py"))
        commit_all(self.root, "delete")
        self.assertIn("FAIL streams.owned.a-owned.py", self.run_gate()[0])                           # IN17
        git(self.root, "reset", "-q", "--hard", "HEAD~1")
        self.assertNotIn("streams.integration", self.run_gate()[0])                                  # IG9
        self.branch(SA, INT)
        self.commit({"a-owned.py": "ff\n"})
        git(self.root, "checkout", "-q", INT)
        git(self.root, "merge", "-q", "--ff-only", SA)                                              # IN13, IG7
        out = self.run_gate()[0]
        self.assertIn("FAIL streams.owned.a-owned.py: only program records may change", out)

    def test_no_ff_merge_second_parent_not_judged_as_program(self):  # IN6 decision (first-parent range)
        self.program()
        self.branch(SA, "main")
        self.commit({"a-owned.py": "1\n"})
        self.commit({"b-owned.py": "2\n"})                   # a second-parent commit that is another stream's
        git(self.root, "checkout", "-q", INT)
        git(self.root, "merge", "-q", "--no-ff", "-m", "combined", SA)
        out = self.run_gate()[0]
        self.assertIn("FAIL streams.owned.b-owned.py: a merge of stream a may change only paths it owns", out)
        self.assertNotIn("only program records", out)

    def test_records_rows(self):  # RC7 (the main merge, D-Q26), RC8, RC9, RC10
        self.program()
        self.branch(REC)
        self.commit({PG + "/program-plan.md": "p2\n"})
        self.put("src/t.py", "x\n")
        git(self.root, "add", "src/t.py")
        self.assertIn("FAIL streams.owned.src/t.py:", self.run_gate()[0])                            # RC10
        git(self.root, "reset", "-q", "--hard")
        git(self.root, "checkout", "-q", "main")
        self.commit({"src/main_moved.py": "x\n"})
        git(self.root, "checkout", "-q", REC)
        self.assertIn("PASS streams.owned\n", self.run_gate()[0])                                    # RC9: main's move is not judged
        git(self.root, "merge", "-q", "--no-ff", "-m", "sync", "main")
        self.assertIn("PASS streams.owned\n", self.run_gate()[0])                                    # D-Q26

    def test_shared_delete_and_own_row(self):  # SH9, SH10
        sh = [{"path": "reg.md", "rule": "append-rows"}, {"path": "own.md", "rule": "own-row"}]
        self.commit({"reg.md": "| h |\n| r1 |\n", "own.md": "| a | 1 |\n| b | 2 |\n"})
        self.program(streams=streams_row(shared=sh))
        self.branch(SA)
        os.remove(os.path.join(self.root, "reg.md"))
        commit_all(self.root, "delete")
        self.assertIn("FAIL streams.shared.reg.md:", self.run_gate()[0])
        self.commit({"reg.md": "| h |\n| r1 |\n", "own.md": "| a | 1 |\n| b | 2 |\n| a | 5 |\n"})
        self.assertNotIn("streams.shared.own.md", self.run_gate()[0])

    def test_plan_hunk_rows(self):  # PF4-PF12
        self.program()
        base = PLAN_A
        for edit, ok in ((lambda t: t.replace("body two", "body two\n\nmore two"), True),                 # nested section, innermost
                         (lambda t: t.replace("# plan a\n", "# plan a2\n"), False),                         # before the first heading
                         (lambda t: t.replace("### Task b9.9: foreign", "### Task a1.1: foreign"), False),   # the old header line is b9.9's
                         (lambda t: t + "\n### Task a1.2: new\n\nx\n", False),                              # a section of no task of a
                         (lambda t: t.replace("body one\n\n", ""), True),                                   # a deletion inside own section
                         (lambda t: t.replace("foreign body\n", ""), False)):
            self.stream({PG + "/a-plan.md": edit(base)}, name=SA)
            out = self.run_gate()[0]
            self.assertIn("PASS streams.owned\n" if ok else "FAIL streams.owned.%s/a-plan.md:" % PG, out, edit(base))
            git(self.root, "checkout", "-q", "main")
            git(self.root, "branch", "-D", SA)
        self.stream({"a-owned.py": "x\n"})
        os.remove(os.path.join(self.root, *(PG + "/a-plan.md").split("/")))
        commit_all(self.root, "rm plan")
        self.assertIn("plan file is created or deleted", self.run_gate()[0])

    def test_unborn_head(self):  # BS17 (D-Q25 (b) clean tree, (c) a tree with changes)
        self.program()
        git(self.root, "checkout", "-q", "--orphan", SA)
        git(self.root, "rm", "-rfq", "--cached", ".")
        with open(os.path.join(self.root, ".git", "info", "exclude"), "a", encoding="utf-8") as fh:
            fh.write("*\n")
        out, code = self.run_gate()
        self.assertIn("PASS streams.owned\n", out)
        self.assertEqual(code, 0)
        self.put("b-owned.py", "x\n")
        git(self.root, "add", "-f", "b-owned.py")
        out, code = self.run_gate()
        self.assertIn("FAIL streams.owned.<unborn>: the branch has no commit yet and the tree holds b-owned.py", out)
        self.assertEqual(code, 1)

    def test_leading_dash_branch_equals_form(self):  # AV6 (D-Q4 (b)): `--branch=-x` reaches the gate's own check
        out, code = self.run_gate("--branch=-x")
        self.assertEqual((out, code), ("FAIL streams.input: --branch: '-x' is not a branch name\n", 1))

    PLAN2 = ("# p\n\n### Task a1.1: one\n\nbody one\n\n#### Task b8.8: nested foreign\n\nnested body\n\n##### sub heading\n\nsub body\n\n"
             "### Notes\n\nnotes text\n\n### Task a2.1: two\n\nbody two\n\n## Appendix\n\ntail text\n")

    def test_plan_sections_nested_and_same_level(self):  # PF rows: innermost section decides; a section ends at a heading of its level
        self.commit({PG + "/a-plan.md": self.PLAN2})
        self.program()
        for old, new, ok in (("body one", "body one edited", True), ("nested body", "nested edited", False), ("sub body", "sub edited", False),
                             ("notes text", "notes edited", False), ("body two", "body two edited", True), ("tail text", "tail edited", False)):
            self.stream({PG + "/a-plan.md": self.PLAN2.replace(old, new)})
            out = self.run_gate()[0]
            self.assertIn("PASS streams.owned\n" if ok else "FAIL streams.owned.%s/a-plan.md:" % PG, out, old)
            git(self.root, "checkout", "-q", "main")
            git(self.root, "branch", "-D", SA)

    def test_plan_file_mode_change_has_no_hunks(self):  # PF: a change with no hunk is refused
        self.program()
        self.branch(SA)
        os.chmod(os.path.join(self.root, *(PG + "/a-plan.md").split("/")), 0o755)
        commit_all(self.root, "mode")
        self.assertIn("plan file hunks cannot be read", self.run_gate()[0])

    def test_request_base_of_integration_is_head(self):  # RQ3 / D-Q12: on integration the base is HEAD, not the branch's tip
        from tests.test_programs_lib import RID, req_row
        self.program(requests={RID: req_row()})
        git(self.root, "checkout", "-q", "-b", "work", INT)
        self.commit({PROGDIR + "/requests/%s.yml" % RID: yamlsub.emit(req_row(need="other"))})
        out = self.run_gate("--branch", INT)[0]
        self.assertIn("PASS streams.request\n", out)

    def test_request_base_is_head_when_branch_given_differs(self):  # RQ3 / D-Q12 (mutant #11): `--branch` names the integration branch but HEAD is elsewhere
        from tests.test_programs_lib import RID, req_row
        self.program(requests={RID: req_row(status="withdrawn")})
        git(self.root, "checkout", "-q", "-b", "work", INT)
        self.commit({PROGDIR + "/requests/%s.yml" % RID: yamlsub.emit(req_row(status="withdrawn", need="changed"))})
        # base HEAD (the work branch itself): the withdrawn request is unchanged against HEAD, so the request line passes;
        # base the integration ref would read "a withdrawn request does not change" (immutable)
        out = self.run_gate("--branch", INT)[0]
        self.assertIn("PASS streams.request\n", out)

    def test_odd_paths_and_many_failures(self):  # OU4, OU9, OU1
        self.program()
        files = {"sp ace.txt": "x\n", "uniࡰ.txt": "x\n", "-dash.txt": "x\n", "q'uote.txt": "x\n"}
        files.update(("many/f%03d.txt" % i, "x\n") for i in range(60))
        self.stream(files)
        out, code = self.run_gate()
        self.assertEqual(code, 1)
        self.assertEqual(sum(l.startswith("FAIL streams.owned.") for l in out.splitlines()), 64)
        self.assertIn("FAIL streams.owned.sp ace.txt:", out)
        ids = self.ids(out)
        self.assertEqual(len(ids), len(set(ids)))

    def test_deterministic_across_hash_seeds(self):  # OU7, V5
        self.program()
        self.stream({"b-owned.py": "x\n", "new.txt": "y\n"})
        outs = set()
        for seed in ("0", "1", "4242"):
            env = dict(os.environ, PYTHONHASHSEED=seed)
            p = subprocess.run([sys.executable, "-m", "gates", "check", "streams", "--root", self.root], cwd=REPO, env=env,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            outs.add((p.stdout, p.returncode))
        self.assertEqual(len(outs), 1)

    def test_subprocess_matches_in_process_for_every_line(self):  # streams.input/none/branch/map/status/request/owned/integration/shared
        sh = [{"path": "reg.md", "rule": "append-rows"}]
        bad = {"schema": "request/1", "id": "R-20261101-abcd", "from_stream": "a", "to_stream": "a", "files": ["a-owned.py"],
               "interface": "docs/x.md#y", "need": "n", "status": "open", "raised_at": {"sha": "a" * 7, "by": "a"}}
        seen = set()

        def both(*argv):
            inproc = self.run_gate(*argv)
            self.assertEqual(self.subprocess_gate(*argv), inproc)
            seen.update(self.ids(inproc[0]))
            return inproc[0]

        self.assertEqual(both(), "PASS streams.none\n")
        self.assertIn("FAIL streams.input:", both("--branch", "a b"))
        self.assertIn("FAIL streams.branch:", both("--branch", NAME + "/a"))
        self.commit({"reg.md": "| h |\n| r1 |\n"})
        self.program(streams=streams_row(shared=sh), status=status_page(("a",)), requests={"R-20261101-abcd": bad})
        out = both()
        self.assertIn("FAIL streams.status.%s" % NAME, out)
        self.assertIn("FAIL streams.request.from.R-20261101-abcd", out)
        self.branch(SA)
        self.commit({"b-owned.py": "x\n", "reg.md": "| h |\nnote\n"})
        git(self.root, "merge", "-q", "--no-ff", "-m", "bad", INT)
        out = both()
        for want in ("FAIL streams.owned.b-owned.py", "FAIL streams.integration.", "FAIL streams.shared.reg.md", "streams.map.%s" % NAME):
            self.assertIn(want, out)
        self.assertEqual(len(seen & {"streams.input", "streams.none", "streams.branch"}), 3)


class Survivors(Fx):
    """Tests that kill the mutants #16-#81 of the part-b run that survived (Task P2.3 part c)."""

    def stream(self, files, name=SA):
        self.branch(name)
        return self.commit(files)

    def test_plan_edit_without_breakdown_names_it(self):  # PF-row / mutant #16: breakdown.yml unreadable
        self.program(bd=None)
        self.stream({PG + "/a-plan.md": PLAN_A.replace("body one", "body one edited")})
        self.assertIn("breakdown.yml cannot be read, so the task sections of stream a are unknown", self.run_gate()[0])

    def test_record_path_owned_by_a_stream_is_still_a_record(self):  # OW7 / IG / mutants #20, #32
        sync = ".strict-delivery/state/findings/x.yml"            # a global record
        self.program(streams=row(stream("a", ["a-owned.py", "tests/test_a.py", sync], merge_order=1),
                                 stream("b", ["b-owned.py", "tests/test_b.py"], merge_order=2)))
        self.stream({sync: "x\n"})
        self.assertIn("FAIL streams.owned.%s: a program record" % sync, self.run_gate()[0])      # mutant #20
        git(self.root, "checkout", "-q", INT)
        git(self.root, "merge", "-q", "--no-ff", "-m", "combined", SA)
        self.assertIn("FAIL streams.owned.%s: a merge of stream a may change only paths it owns" % sync, self.run_gate()[0])

    def test_octopus_merge_into_stream_branch_is_judged(self):  # IG11, mutant #22: every second parent must be on the base tip
        self.program()
        self.branch(SA)
        git(self.root, "branch", "feat", SA)
        git(self.root, "checkout", "-q", "main")
        self.commit({"m.txt": "m\n"})
        git(self.root, "checkout", "-q", "feat")
        self.commit({"a-owned.py": "f\n"})
        git(self.root, "checkout", "-q", SA)
        git(self.root, "merge", "-q", "--no-ff", "-m", "oct", "main", "feat")
        out = self.run_gate()[0]
        self.assertIn("FAIL streams.owned.m.txt:", out)

    def test_stream_merge_of_plain_branch_is_judged_by_paths(self):  # mutant #60: only integration merges are combined
        self.program()
        self.branch(SA)
        git(self.root, "checkout", "-q", "-b", "feat", "main")
        self.commit({"tests/test_b.py": "t\n"})                       # another stream's test file: allowed on a stream branch
        git(self.root, "checkout", "-q", SA)
        self.commit({"a-owned.py": "x\n"})
        git(self.root, "merge", "-q", "--no-ff", "-m", "m", "feat")
        self.assertIn("PASS streams.owned\n", self.run_gate()[0])

    def test_octopus_merge_on_integration_refused(self):  # IN12, mutant #30
        self.program()
        self.branch(SA)
        self.commit({"a-owned.py": "x\n"})
        self.branch(SB, "main")
        self.commit({"b-owned.py": "x\n"})
        git(self.root, "checkout", "-q", INT)
        git(self.root, "merge", "-q", "--no-ff", "-m", "oct", SA, SB)
        out = self.run_gate()[0]
        self.assertIn("an octopus merge on %s is refused" % INT, out)

    def test_combined_merge_reached_by_two_streams_fails(self):  # IN8, mutant #31
        self.program()
        self.branch(SA)
        self.commit({"a-owned.py": "x\n"})
        git(self.root, "branch", SB, SA)
        git(self.root, "checkout", "-q", INT)
        git(self.root, "merge", "-q", "--no-ff", "-m", "m", SA)
        self.assertIn("streams a and b both reach the second parent", self.run_gate()[0])

    def test_combined_merge_of_a_group_branch(self):  # IN9, mutant #33: a group branch counts as the stream's
        self.program()
        self.branch(NAME + "/a/g1")
        self.commit({"a-owned.py": "x\n"})
        git(self.root, "checkout", "-q", INT)
        git(self.root, "merge", "-q", "--no-ff", "-m", "m", NAME + "/a/g1")
        self.assertIn("PASS streams.owned\n", self.run_gate()[0])

    def test_malformed_program_branch_name_fails_closed_on_a_combined_merge(self):  # mutant #34 probe: pins the present behaviour
        self.program()
        self.branch(NAME + "/foo", "main")
        self.commit({"a-owned.py": "x\n"})
        git(self.root, "checkout", "-q", INT)
        git(self.root, "merge", "-q", "--no-ff", "-m", "m", NAME + "/foo")
        out, code = self.run_gate()
        self.assertTrue(out.startswith("FAIL streams.input: ValueError: branch '%s/foo'" % NAME), out)
        self.assertEqual(code, 1)

    def shared_fx(self, text):
        self.commit({"reg.md": text})
        self.program(streams=streams_row(shared=[{"path": "reg.md", "rule": "append-rows"}]))
        self.branch(SA)

    def test_shared_append_to_base_without_end(self):  # mutant #36
        self.shared_fx("| h |\n| r1 |")
        self.commit({"reg.md": "| h |\n| r1 |\n| r2 |\n"})
        self.assertIn("PASS streams.shared", self.run_gate()[0])
        self.commit({"reg.md": "| h |\n| r1 |\n| r2 |\n| r3 |"})
        self.assertIn("PASS streams.shared", self.run_gate()[0])

    def test_shared_appended_line_must_be_a_row(self):  # mutant #37
        self.shared_fx("| h |\n| r1 |\n")
        self.commit({"reg.md": "| h |\n| r1 |\nnote\n"})
        self.assertIn("FAIL streams.shared.reg.md: append-rows: 'note' is not a table row", self.run_gate()[0])

    def test_detached_and_shallow_messages(self):  # mutants #41, #42
        git(self.root, "checkout", "-q", "--detach")
        self.assertIn("HEAD is detached; pass --branch NAME", self.run_gate()[0])
        self.program()
        clone = os.path.join(self.tmp, "clone")
        git(self.tmp, "clone", "-q", "--depth", "1", "file://" + self.root, clone)
        git(clone, "checkout", "-q", "-b", INT, "origin/main")
        self.assertIn("shallow clone; fetch the full history", self.run_gate("--branch", SA, root=clone)[0])

    def test_staged_path_restored_in_work_tree_is_judged(self):  # mutant #45
        self.program()
        self.branch(SA)
        self.put("b-owned.py", "z\n")
        git(self.root, "add", "b-owned.py")
        self.put("b-owned.py", "b\n")                                   # the work tree equals HEAD; only the index differs
        out = self.run_gate()[0]
        self.assertIn("FAIL streams.owned.b-owned.py: owned by stream b (the tree being committed)", out)

    def test_no_shared_line_on_integration_or_records(self):  # mutant #57
        self.program()
        git(self.root, "checkout", "-q", INT)
        self.assertNotIn("streams.shared", self.run_gate()[0])
        self.branch(REC, "main")
        self.assertNotIn("streams.shared", self.run_gate()[0])

    def test_uncommitted_own_plan_edit_on_stream_branch_passes(self):  # mutant #61: the tree is diffed against HEAD
        self.program()
        self.branch(SA)
        self.put(PG + "/a-plan.md", PLAN_A.replace("body one", "body one edited"))
        self.assertIn("PASS streams.owned\n", self.run_gate()[0])

    def test_merged_record_first_line_and_finals_per_stream(self):  # mutants #50, #51
        head1, m1 = self.pr("p1", "a")
        head2, m2 = self.pr("p2", "b")
        l1 = mline(1, head1, m1, "a", "a2", final="yes")
        l2 = mline(2, head2, m2, "b", "1b", final="yes")
        self.program(merged=MERGED_HEAD + l1 + "\n" + l2 + "\n")
        out = self.run_gate()[0]
        self.assertNotIn("final=yes after a final line", out)         # a final line per stream (mutant #51: one in all)
        git(self.root, "branch", "-D", INT)
        self.program(merged="<!-- schema: merged-log/2 -->\n" + l1 + "\n")
        self.assertIn("merged.md: first line must be", self.run_gate()[0])    # mutant #50

    def test_one_final_line_per_stream_still_refused(self):  # sibling of #51
        head1, m1 = self.pr("p1", "a")
        head2, m2 = self.pr("p2", "a")
        self.program(merged=MERGED_HEAD + mline(1, head1, m1, "a", "a1", final="yes") + "\n"
                     + mline(2, head2, m2, "a", "a2", final="yes") + "\n")
        self.assertIn("final=yes after a final line of stream a", self.run_gate()[0])

    def test_base_ledger_records_a_pr_twice(self):  # ME23, mutant #54
        a7 = git(self.root, "rev-parse", "--short=7", "HEAD")
        head, m = self.pr("p1", "a", [ckpt("a1", "a1.1", a7)])
        line = mline(1, head, m, "a", "a1")
        self.program(merged=MERGED_HEAD + line + "\n")
        git(self.root, "checkout", "-q", "main")
        self.commit({"%s/a-plan/ledger.md" % PS: ledger(ckpt("a1", "a1.1", a7), line, line)})
        self.assertIn("pr 1: recorded twice in %s/a-plan/ledger.md at main" % PS, self.run_gate()[0])


NAME2 = "20261102-y"


class RowsD(Fx):
    """Task P2.3 part d: the rows of the table that parts a-c had not mapped (row ids in the comments)."""
    layout, merge_line, prog = Windows.layout, Windows.merge_line, Windows.prog

    def stream(self, files, name=SA):
        self.branch(name)
        return self.commit(files)

    def lines(self, out):
        return [l for l in out.splitlines() if l]

    # ---- arguments, roots, branches (AV9-AV11, BR6, BR11, BR15, BR16, EN4, EN5)
    def test_root_forms(self):  # AV9, EN5
        self.program()
        self.branch(SA)
        for name, path, verdict in root_forms(self.tmp, self.root):
            with self.subTest(form=name):
                out, code = self.run_gate(root=path)
                if verdict == "ok":
                    self.assertNotIn("show-toplevel", out)
                else:
                    self.assertEqual(code, 1)
                    self.assertEqual(len(self.lines(out)), 1)
                    self.assertTrue(out.startswith("FAIL streams.input: "), out)
                    if verdict == E128:
                        self.assertIn("; run /strict-delivery:init", out)
                    else:                       # a subdirectory of the top level (see the report: Decision needed, AV9 suffix)
                        self.assertIn("root must be the repository top level", out)

    def test_config_missing_and_custom_paths_and_base_branch(self):  # AV11
        bare = os.path.join(self.tmp, "noconfig")
        os.mkdir(bare)
        git(bare, "init", "-q", "-b", "main")
        out, code = self.run_gate(root=bare)
        self.assertEqual(code, 1)
        self.assertTrue(out.startswith("FAIL streams.input: "), out)
        self.assertIn(".strict-delivery/config.yml", out)
        self.assertIn("run /strict-delivery:init", out)
        cfg = dict(minimal_config(), base_branch="trunk", paths={"programs": "ops/progs", "plan_state": "ops/state"})
        self.put(".strict-delivery/config.yml", yamlsub.emit(cfg))
        commit_all(self.root, "custom config")
        git(self.root, "branch", "-m", "main", "trunk")
        self.progdir, self.ps = "ops/progs/" + NAME, "ops/state"
        self.program(base="trunk", back="trunk", bd=dict(BD))
        self.branch(SA, "trunk")
        self.commit({"a-owned.py": "x\n"})
        out, code = self.run_gate()
        self.assertEqual((self.ids(out), code, out.count("FAIL")), (["streams.map." + NAME, "streams.status." + NAME, "streams.request",
                                                                     "streams.owned", "streams.integration", "streams.shared"], 0, 0), out)
        self.commit({"b-owned.py": "x\n"})
        self.assertIn("FAIL streams.owned.b-owned.py: owned by stream b", self.run_gate()[0])
        self.assertEqual(git(self.root, "branch", "--list", "main"), "")              # a hard-coded base `main` would not exist here

    def test_integration_worktree_and_linked_roots(self):  # AV10, BR15, EN4
        self.program()
        wt = os.path.join(self.tmp, "wt-int")
        git(self.root, "worktree", "add", "-q", wt, INT)
        out, code = self.run_gate(root=wt)
        self.assertEqual((self.ids(out), code), (["streams.map." + NAME, "streams.status." + NAME, "streams.request", "streams.owned"], 0))
        wa =os.path.join(self.tmp, "wt-a")
        git(self.root, "worktree", "add", "-q", "-b", SA, wa, "main")
        with open(os.path.join(wa, "b-owned.py"), "w") as fh:
            fh.write("x\n")
        commit_all(wa, "b's file")
        self.assertIn("FAIL streams.owned.b-owned.py", self.run_gate(root=wa)[0])      # the linked worktree's own HEAD
        out, code = self.run_gate()                                                    # the main checkout is on main
        self.assertEqual((self.ids(out), code), (["streams.map." + NAME, "streams.status." + NAME, "streams.request"], 0))

    def test_integration_without_streams_yml(self):  # BR6
        git(self.root, "branch", INT, "main")
        out, code = self.run_gate()                                                    # on main: the program is not live
        self.assertEqual((out, code), ("PASS streams.none\n", 0))
        git(self.root, "checkout", "-q", "-b", SA, "main")
        out, code = self.run_gate()
        self.assertEqual(code, 1)
        self.assertEqual(len(self.lines(out)), 1)
        self.assertTrue(out.startswith("FAIL streams.input: "), out)
        self.assertIn("streams.yml", out)

    def program2(self):
        """A second live program ``20261102-y`` (hand written like ``program``), HEAD left on main."""
        git(self.root, "checkout", "-q", "-b", NAME2 + "/integration", "main")
        d = ".strict-delivery/state/programs/" + NAME2 + "/"
        self.put(d + "streams.yml", yamlsub.emit(streams_row(program=NAME2)) if False else yamlsub.emit(dict(streams_row(), program=NAME2)))
        self.put(d + "status.md", status_page().replace(NAME, NAME2))
        self.put(d + "sync-log.md", "<!-- schema: sync-log/1 -->\n")
        self.put(d + "merged.md", MERGED_HEAD)
        self.put(PS + "/program-plan/breakdown.yml", yamlsub.emit(BD))
        commit_all(self.root, "program 2")
        git(self.root, "checkout", "-q", "main")

    def test_two_live_programs_a_program_branch_checks_its_own_only(self):  # BR11 (D-Q9 (a) with (c)'s reading)
        self.program()
        self.program2()
        out, code = self.run_gate()                                                    # a non-program branch: every live program
        self.assertEqual((self.ids(out), code), (["streams.map." + NAME, "streams.status." + NAME, "streams.request",
                                                  "streams.map." + NAME2, "streams.status." + NAME2, "streams.request"], 0))
        self.branch(SA)
        out, code = self.run_gate()
        self.assertEqual((self.ids(out), code), (["streams.map." + NAME, "streams.status." + NAME, "streams.request", "streams.owned",
                                                  "streams.integration", "streams.shared"], 0))

    def test_branch_names_ascii_only(self):  # BR16 (V2)
        self.program()
        for bad in (NAME + "/" + "a" * 255 + "/main", NAME + "/é/main", NAME + "/A/main", NAME + "/ࡰ/main",
                    NAME + "/a/Ⱟ"):
            with self.subTest(branch=bad[:40]):
                out, code = self.run_gate("--branch", bad)
                self.assertEqual(code, 1)
                self.assertEqual(len(self.lines(out)), 1)
                self.assertTrue(out.startswith(("FAIL streams.branch: ", "FAIL streams.input: --branch: ")), out)   # 255 + prefix is no branch name

    # ---- the base and the judged commits (BS3, BS7-BS10, BS12, BS14-BS16, BS18)
    def test_side_commits_judged_individually(self):  # BS3, CP5
        self.program()
        git(self.root, "checkout", "-q", "-b", SB, "main")
        self.commit({"b-owned.py": "from b\n"})
        self.branch(SA, "main")
        self.commit({"a-owned.py": "own\n"})
        git(self.root, "merge", "-q", "--no-ff", "-s", "ours", "-m", "ours of b", SB)       # the tree equals the first parent's
        self.assertEqual(gitinfo.commit_paths(self.root, "HEAD"), [])
        out, code = self.run_gate()
        self.assertIn("FAIL streams.owned.b-owned.py: owned by stream b", out)
        self.assertEqual(code, 1)
        self.assertNotIn("a-owned.py", out)

    def test_base_branch_missing_locally(self):  # BS7 (D-Q5: the existing GateError route)
        self.program()
        self.branch(SA)
        git(self.root, "update-ref", "refs/remotes/origin/main", "main")
        git(self.root, "branch", "-q", "-m", "main", "elsewhere")
        out, code = self.run_gate()
        self.assertEqual(code, 1)
        self.assertEqual(len(self.lines(out)), 1)
        self.assertTrue(out.startswith("FAIL streams.input: "), out)

    def test_unrelated_histories(self):  # BS8
        self.program()
        git(self.root, "checkout", "-q", "--orphan", SA)
        self.put("a-owned.py", "x\n")
        commit_all(self.root, "orphan")
        out, code = self.run_gate()
        self.assertEqual(code, 1)
        self.assertEqual(len(self.lines(out)), 1)
        self.assertTrue(out.startswith("FAIL streams.input: "), out)
        self.assertIn("merge-base", out)

    def test_branch_at_base_tip_and_one_line_per_path_in_commit_order(self):  # BS10, BS12, BS14, BS15
        self.program()
        self.branch(SA)
        self.assertIn("PASS streams.owned\n", self.run_gate()[0])                         # BS10: no commit beyond the base
        self.commit({"b-owned.py": "1\n", "new1.txt": "1\n"})
        self.commit({"b-owned.py": "2\n"})
        self.commit({"b-owned.py": "3\n", "new0.txt": "1\n"})
        self.put("b-owned.py", "tree\n")                                                  # BS14: the tree being committed too
        out = self.run_gate()[0]
        fails = [l for l in out.splitlines() if l.startswith("FAIL streams.owned.")]
        self.assertEqual([l.split(":")[0] for l in fails],                                # BS15: the order of the first failure
                         ["FAIL streams.owned.b-owned.py", "FAIL streams.owned.new1.txt", "FAIL streams.owned.new0.txt"])
        self.assertEqual(out.count("streams.owned.b-owned.py"), 1)                         # BS12: one line, the reasons joined
        self.assertEqual(fails[0].count("; "), 3)                                          # three commits and the tree: four reasons

    def test_shallow_clone_never_judges_the_boundary(self):  # BS9 (D-Q5 (b))
        self.program()
        clone = os.path.join(self.tmp, "shallow")
        git(self.tmp, "clone", "-q", "--depth", "1", "--no-single-branch", "file://" + self.root, clone)
        git(clone, "branch", INT, "origin/" + INT)
        out, code = self.run_gate(root=clone, *("--branch", SA))
        self.assertEqual((out, code), ("FAIL streams.input: shallow clone; fetch the full history\n", 1))

    def test_large_range(self):  # BS16: the verdict does not depend on the number of commits
        self.program()
        self.branch(SA)
        head = git(self.root, "rev-parse", "HEAD")
        stream = [b"blob\nmark :1\ndata 2\nx\n\n"]
        for i in range(2000):
            stream.append(b"commit refs/heads/%s\ncommitter T <t@example.invalid> 0 +0000\ndata 1\nc\n" % SA.encode())
            if i == 0:
                stream.append(b"from " + head.encode() + b"\n")
            stream.append(b"M 100644 :1 a-owned.py\n\n" if i < 1999 else b"M 100644 :1 b-owned.py\n\n")
        subprocess.run(["git", "-C", self.root, "fast-import", "--quiet", "--force"], input=b"".join(stream), check=True,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=dict(os.environ))
        git(self.root, "reset", "-q", "--hard", SA)
        self.assertEqual(git(self.root, "rev-list", "--count", "main..HEAD"), "2000")
        out, code = self.run_gate()
        self.assertEqual(code, 1)
        self.assertEqual([l.split(":")[0] for l in out.splitlines() if l.startswith("FAIL")], ["FAIL streams.owned.b-owned.py"])

    def test_inside_pre_commit_hook_environment(self):  # BS18, EN3 (D-Q13: the tree being committed is the index in GIT_INDEX_FILE)
        self.program()
        self.branch(SA)
        alt = os.path.join(self.tmp, "alt-index")
        shutil.copy(os.path.join(self.root, ".git", "index"), alt)
        self.put("b-owned.py", "staged only in the alternate index\n")
        git(self.root, "add", "b-owned.py", env={"GIT_INDEX_FILE": alt})
        with open(os.path.join(self.root, ".git", "index"), "rb") as fh:
            real = fh.read()
        with mock.patch.dict(os.environ, {"GIT_INDEX_FILE": alt}):
            out = self.run_gate()[0]
        self.assertIn("FAIL streams.owned.b-owned.py", out)
        with open(os.path.join(self.root, ".git", "index"), "rb") as fh:
            self.assertEqual(fh.read(), real)                                              # no gate call wrote the real index

    # ---- the merged record and the ledgers (MP13-MP16, MP18-MP20, ME3, ME9, ME12, ME15, ME19, ME24)
    def test_ledger_rows(self):  # MP13, MP14, MP15, MP16, MP22 (the ledger path is <plan_state>/<plan slug>/ledger.md)
        self.program()
        bad = ledger("Ruling nonsense")
        self.branch(SA)                                                                    # MP15: a stream with no ledger yet
        self.assertIn("PASS streams.map." + NAME, self.run_gate()[0])
        self.commit({"%s/b-plan/ledger.md" % PS: bad})                                     # MP13: another stream's ledger, not read
        self.assertIn("PASS streams.map." + NAME, self.run_gate()[0])
        self.commit({"%s/a-plan/ledger.md" % PS: bad})                                     # MP14: the committing stream's own ledger
        self.assertIn("FAIL streams.map.%s: " % NAME, self.run_gate()[0])
        git(self.root, "checkout", "-q", INT)                                              # only on a stream or group branch
        self.put("%s/a-plan/ledger.md" % PS, bad)
        self.assertIn("PASS streams.map." + NAME, self.run_gate()[0])
        git(self.root, "checkout", "-q", "--", ".")
        git(self.root, "checkout", "-q", "main")
        a7 = git(self.root, "rev-parse", "--short=7", "HEAD")                              # MP16: a bad line in the ledger at a counted head
        head, m = self.pr("p1", "a", [ckpt("a1", "a1.1", a7), "Ruling nonsense"])
        git(self.root, "branch", "-D", INT)
        self.program(merged=MERGED_HEAD + mline(1, head, m, "a", "a1") + "\n")
        self.assertIn("FAIL streams.map.%s: " % NAME, self.run_gate()[0])

    def test_agreement_and_stacked_order_rows(self):  # MP18, MP19, MP20
        a = stream("a", ["a-owned.py", "tests/test_a.py"], merge_order=1, period=("program-start", "program-close"))
        b = stream("b", ["b-owned.py", "tests/test_b.py"], merge_order=2)
        self.program(streams=row(a, b), bd=bd_of(a, b))                                    # an explicit period equals an absent one
        self.assertIn("PASS streams.map." + NAME, self.run_gate()[0])
        git(self.root, "branch", "-D", INT)
        bd = bd_of(a, b)
        bd["streams"][0]["period"] = {"from": "program-start", "until": "merged:b"}
        self.program(streams=row(a, b), bd=bd)                                             # a bound that differs
        self.assertIn("period differs from the breakdown", self.run_gate()[0])
        git(self.root, "branch", "-D", INT)
        bd = bd_of(a, b)
        bd["plan"] = "other-plan"
        self.program(streams=row(a, b), bd=bd)                                             # the plan differs
        self.assertIn("FAIL streams.map.", self.run_gate()[0])
        git(self.root, "branch", "-D", INT)
        a2 = dict(a, stacked_on="b")
        self.program(streams=row(a2, b), bd=bd_of(a2, b))                                  # MP19: no edge orders a's blocks after merged:b
        self.assertIn("stacked_on: stream a sub-block", self.run_gate()[0])
        git(self.root, "branch", "-D", INT)
        b2 = dict(b, merge_order=1)                                                        # MP20: reasons of streams_errors surface
        self.program(streams=row(a, b2), bd=bd_of(a, b2))
        self.assertIn("FAIL streams.map.", self.run_gate()[0])

    def test_merged_lines_that_do_not_count_and_duplicates(self):  # ME3, ME15, ME19
        streams, bd, names = self.layout(a_owns=[W("w1.py", None, "merged:a/a1")], b_owns=[W("w1.py", "merged:a/a1")])
        head, m, line = self.merge_line(1, "a1")
        for label, bad_line in (("ME3: merge is not the merge of the head", mline(1, head, head, "a", "a1")),
                                ("ME19: merge not found locally", mline(1, head, "f" * 40, "a", "a1"))):
            self.program(merged=MERGED_HEAD + bad_line + "\n", streams=streams, bd=bd, status=status_page(names))
            self.branch(SB)
            self.commit({"w1.py": "x\n"})
            out = self.run_gate()[0]
            self.assertIn("FAIL streams.map.%s: " % NAME, out, label)                      # Q15 (a): a FAIL line, the line does not count
            self.assertIn("pr 1", out, label)
            self.assertIn("FAIL streams.owned.w1.py", out, label)                          # the window it would open stays closed
            git(self.root, "checkout", "-q", "main")
            git(self.root, "branch", "-D", SB, INT)
        self.program(merged=MERGED_HEAD + line + "\n", streams=streams, bd=bd, status=status_page(names))
        self.branch(SB)
        self.commit({"w1.py": "x\n"})
        self.assertIn("PASS streams.owned\n", self.run_gate()[0])                           # the good line opens it
        git(self.root, "checkout", "-q", "main")
        git(self.root, "branch", "-D", SB, INT)
        self.program(merged=MERGED_HEAD + line + "\n" + line + "\n", streams=streams, bd=bd, status=status_page(names))   # ME15
        self.assertIn("recorded twice", self.run_gate()[0])

    def test_one_pr_carries_both_sub_blocks_of_stream_a(self):  # ME9 (the sub-blocks a1 and a2 of one pull request)
        layout = {"a_owns": [W("w1.py", None, "merged:a/a1"), W("w2.py", None, "merged:a/a2"), W("wall.py", None, "merged:a")],
                  "b_owns": [W("w1.py", "merged:a/a1"), W("w2.py", "merged:a/a2"), W("wall.py", "merged:a")]}
        streams, bd, names = self.layout(**layout)
        _, _, line = self.merge_line(1, "a2", ckpts=["a1", "a2"])
        self.program(merged=MERGED_HEAD + line + "\n", streams=streams, bd=bd, status=status_page(names))
        self.branch(SB)
        self.commit({"w1.py": "x\n", "w2.py": "x\n", "wall.py": "x\n"})
        out = self.run_gate()[0]
        self.assertIn("PASS streams.map", out)
        self.assertEqual([l for l in out.splitlines() if l.startswith("FAIL")], [])          # merged:a/a1, merged:a/a2 and merged:a hold

    def test_ledger_at_head_missing_and_digits(self):  # ME12 (Q16 (a)), ME24 (V1)
        git(self.root, "checkout", "-q", "-b", "p1", "main")
        self.put("x.txt", "x\n")
        head = commit_all(self.root, "no ledger here")
        git(self.root, "checkout", "-q", "main")
        git(self.root, "merge", "-q", "--no-ff", "-m", "Merge p1", "p1")
        merge = git(self.root, "rev-parse", "HEAD")
        self.program(merged=MERGED_HEAD + mline(1, head, merge, "a", "a1") + "\n")
        out = self.run_gate()[0]
        self.assertIn("FAIL streams.map.%s: " % NAME, out)
        self.assertEqual(len([l for l in out.splitlines() if l.startswith("FAIL")]), 1)
        for pr in ("9" * 600, "9" * 601, "9" * 4301):                                      # the same verdict kind on both interpreters
            git(self.root, "branch", "-D", INT)
            self.program(merged=MERGED_HEAD + mline(pr, head, merge, "a", "a1") + "\n")
            out = self.run_gate()[0]
            self.assertIn("FAIL streams.map.%s: " % NAME, out)
            self.assertNotIn("streams.input", out)                                          # never a traceback-shaped ValueError line
            self.assertNotIn("ValueError", out)


if __name__ == "__main__":
    unittest.main()
