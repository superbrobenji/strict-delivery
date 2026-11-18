"""Tests of gates/gate_streams.py through ``gates.__main__.main`` in process and ``python3 -m gates`` in a subprocess
(Task P2.3 input-domain table: the row ids are in the comments). The program fixture is written by hand (decision D-Q23),
the fixture repository's git config sets ``color.ui=always``, ``color.diff=always`` and ``core.abbrev=7`` (plan P:2855).
Expected ids and reason fragments are written from the plan lines P:2829-2841 and the table, never read from the gate."""
import contextlib
import io
import os
import subprocess
import sys
import unittest

from gates import __main__ as entry
from gates.lib import config, gitinfo, yamlsub
from tests.helpers import GitIsolatedTestCase, commit_all, git, make_repo, minimal_config
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

    def program(self, merged=MERGED_HEAD, streams=None, bd=BD, status=None, requests=None, base="main"):
        """The program on ``<p>/integration`` cut from ``base``; HEAD is left on ``main``."""
        git(self.root, "checkout", "-q", "-b", INT, base)
        d = PROGDIR + "/"
        self.put(d + "streams.yml", yamlsub.emit(streams or streams_row()))
        self.put(d + "status.md", status or status_page())
        self.put(d + "sync-log.md", "<!-- schema: sync-log/1 -->\n")
        self.put(d + "merged.md", merged)
        for rid, r in (requests or {}).items():
            self.put("%s/requests/%s.yml" % (d, rid), yamlsub.emit(r))
        if bd is not None:
            self.put(PS + "/program-plan/breakdown.yml", yamlsub.emit(bd))
        commit_all(self.root, "program")
        git(self.root, "checkout", "-q", "main")

    def branch(self, name, at="main"):
        git(self.root, "checkout", "-q", "-b", name, at)

    def pr(self, branch, sid, lines=(), files=None):
        """A branch off main holding stream ``sid``'s ledger, merged into main with ``--no-ff``: ``(head, merge)``."""
        git(self.root, "checkout", "-q", "-b", branch, "main")
        self.put("%s/%s-plan/ledger.md" % (PS, sid), ledger(*lines))
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
        for bad in ("", "a..b", "a b", "a~b", "a@{b", "a.lock", "a/", "/a", "x\ny"):
            with self.subTest(bad=bad):
                out, code = self.run_gate("--branch", bad)
                self.assertTrue(out.startswith("FAIL streams.input:"), out)
                self.assertEqual(code, 1)
        self.assertEqual(self.run_gate("--branch=feature/x")[0], "PASS streams.none\n")
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

    def test_group_merge_after_combined_testing_passes(self):  # IG4, owner answer Q-A11-1 (c)
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

    def test_merge_of_main_exempt_combined_merge_owned_paths(self):  # IN5, IN6, IN7
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


if __name__ == "__main__":
    unittest.main()
