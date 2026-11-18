"""More rows of the Task P2.3 input-domain table for gates/gate_streams.py (part d; the row ids are in the comments).
Same fixtures as tests/test_gate_streams.py (a hand-written program on ``<program>/integration``, ``helpers.make_repo``
repositories whose git config sets colour and a short abbreviation); expected values are written from the table."""
import os
import subprocess
import unittest

from gates.lib import gitinfo, yamlsub
from tests import test_gate_streams as base
from tests.helpers import commit_all, git
from tests.test_gate_streams import (BD, INT, NAME, PG, PLAN_A, PROGDIR, PROGRAM_PLAN, REC, SA, SB, W, bd_of, status_page, streams_row)
from tests.test_programs_lib import MERGED_HEAD, PS, ckpt, ledger, mline, row, stream


class RowsE(base.Fx):
    layout, merge_line, prog = base.Windows.layout, base.Windows.merge_line, base.Windows.prog

    def stream(self, files, name=SA):
        self.branch(name)
        return self.commit(files)

    def lines(self, out):
        return [l for l in out.splitlines() if l]

    # ---- the status page and the requests (ST3, ST6, ST7, RQ7)
    def test_status_digits_and_page_problems(self):  # ST3 (V1), ST7 (Q16 (a))
        for n in (4300, 4301):
            self.program(status=status_page().replace("| 5 | 0 |", "| 5 | %s |" % ("9" * n), 1))
            out = self.run_gate()[0]
            self.assertNotIn("streams.input", out, n)                                       # never `streams.input: ValueError: ...`
            self.assertNotIn("ValueError", out, n)
            self.assertEqual(out.count("streams.status."), 1, n)
            git(self.root, "branch", "-D", INT)
        for label, status in (("first line wrong", b"not a status page\n"), ("absent", None),
                              ("not UTF-8", b"<!-- schema: status/1 -->\n\xff\xfe\n")):
            self.program(status="x\n")
            git(self.root, "checkout", "-q", INT)
            if status is None:
                git(self.root, "rm", "-q", PROGDIR + "/status.md")
            else:
                with open(os.path.join(self.root, *(PROGDIR + "/status.md").split("/")), "wb") as fh:
                    fh.write(status)
            commit_all(self.root, label)
            git(self.root, "checkout", "-q", "main")
            out, code = self.run_gate()
            self.assertEqual(code, 1, label)
            self.assertTrue("FAIL streams.status.%s: " % NAME in out or "FAIL streams.input: " in out, (label, out))
            git(self.root, "branch", "-D", INT)

    def test_status_page_in_the_tree_being_committed_on_integration(self):  # ST6 (D-Q11 (b))
        self.program()
        git(self.root, "checkout", "-q", INT)
        self.put(PROGDIR + "/status.md", "not a status page\n")
        self.assertIn("FAIL streams.status.%s: " % NAME, self.run_gate()[0])

    def test_breakdown_read_from_the_integration_tip(self):  # RQ7 (also PF19: test_map_breakdown_missing)
        self.program()
        self.branch(SA)
        self.commit({PS + "/program-plan/breakdown.yml": "garbage: [\n"})
        out = self.run_gate()[0]
        self.assertIn("PASS streams.map." + NAME, out)                                       # the working-tree copy is never read
        self.assertIn("FAIL streams.owned.%s/program-plan/breakdown.yml" % PS, out)

    # ---- ownership and test files (OW10, OW20, OW21, OW25, OW28, OW29, OW31, OU8, TF8-TF13, TF16)
    def test_spec_directory_entry_case_and_group_merge(self):  # OW10, OW20, OW21, OW25
        a = stream("a", ["a-owned.py", "tests/test_a.py", "adir/"], merge_order=1)
        b = stream("b", ["b-owned.py", "tests/test_b.py"], merge_order=2)
        self.program(streams=row(a, b), bd=bd_of(a, b))
        self.branch(SA)
        self.commit({"docs/strict-delivery/specs/x.md": "s\n", "adirx/y.py": "x\n", "adir/sub/x.py": "x\n"})
        git(self.root, "update-index", "--add", "--cacheinfo", "100644,%s,B-OWNED.PY" % git(self.root, "rev-parse", "HEAD:a-owned.py"))
        git(self.root, "commit", "-q", "-m", "case variant recorded in the index only")
        out = self.run_gate()[0]
        self.assertIn("FAIL streams.owned.docs/strict-delivery/specs/x.md:", out)          # OW10: the specs are never exempt
        self.assertIn("FAIL streams.owned.B-OWNED.PY: owned by stream b", out)             # OW20: compared by path_key (case)
        self.assertIn("FAIL streams.owned.adirx/y.py:", out)                               # `adir/` does not cover `adirx/y.py`
        self.assertNotIn("streams.owned.adir/sub/x.py", out)                               # OW21: the directory entry covers the subtree

    def test_group_merged_into_the_stream(self):  # OW25: the merge and the group's commits are each judged as the stream's
        self.program()
        git(self.root, "checkout", "-q", "-b", NAME + "/a/g1", "main")
        self.commit({"a-owned.py": "g\n"})
        self.branch(SA, "main")
        self.commit({"tests/test_a.py": "own\n"})
        git(self.root, "merge", "-q", "--no-ff", "-m", "group", NAME + "/a/g1")
        self.assertIn("PASS streams.owned\n", self.run_gate()[0])
        self.commit({"b-owned.py": "x\n"})
        self.assertIn("FAIL streams.owned.b-owned.py", self.run_gate()[0])

    def test_ownership_refusals_surface_as_lines(self):  # OW28, OW29, OW31, OU8
        a = stream("a", ["a-owned.py", "tests/test_a.py", PS + "/b-plan/"], merge_order=1)
        b = stream("b", ["b-owned.py", "tests/test_b.py"], merge_order=2)
        self.program(streams=row(a, b), bd=bd_of(a, b))
        self.assertIn("FAIL streams.map.%s: " % NAME, self.run_gate()[0])                  # OW28
        git(self.root, "branch", "-D", INT)
        self.program()
        out = self.run_gate("--branch", "other")[0]                                         # OW29: no `streams.owned` off a program branch
        self.assertNotIn("streams.owned", out)
        git(self.root, "checkout", "-q", INT)                                              # OW31: streams.yml unparsable
        self.commit({PROGDIR + "/streams.yml": "garbage: [\n"})
        git(self.root, "checkout", "-q", "main")
        self.branch(SA)
        out, code = self.run_gate()
        self.assertEqual(code, 1)
        self.assertEqual(len(self.lines(out)), 1)
        self.assertTrue(out.startswith("FAIL streams.input: "), out)
        self.assertIn("streams.yml", out)
        self.assertEqual(self.run_gate("--branch", NAME + "/b/main/x")[0].split(":")[0], "FAIL streams.branch")   # OU8: parse_branch ValueError

    def test_test_file_rows(self):  # TF9, TF10, TF11, TF12, TF13
        streams, bd, names = self.layout(a_owns=[W("tests/test_w.py", None, "merged:a/a2")],
                                         b_owns=[W("tests/test_w.py", "merged:a/a1"), W("tests/test_late.py", "merged:a/a2")])
        _, _, line = self.merge_line(1, "a1")
        self.program(merged=MERGED_HEAD + line + "\n", streams=streams, bd=bd, status=status_page(names))
        self.branch(SA)
        self.commit({"tests/test_w.py": "x\n"})                                              # TF9: two open windows cover the test file
        self.assertIn("FAIL streams.owned.tests/test_w.py: stream a and stream b are both open for it", self.run_gate()[0])
        self.commit({"tests/test_late.py": "x\n"})                                           # TF13: the owner's window is not open yet
        self.assertIn("FAIL streams.owned.tests/test_late.py:", self.run_gate()[0])
        git(self.root, "checkout", "-q", "main")
        git(self.root, "branch", "-D", SA, INT)
        self.program()
        self.branch(SA)
        os.remove(os.path.join(self.root, "tests", "test_b.py"))                             # TF11: deleting another stream's test file
        commit_all(self.root, "delete")
        self.assertIn("PASS streams.owned\n", self.run_gate()[0])
        git(self.root, "checkout", "-q", "main")
        git(self.root, "branch", "-D", SA)
        self.branch(SA)
        git(self.root, "mv", "tests/test_b.py", "b_module.py")                               # TF10: the rename to a non-test path
        commit_all(self.root, "rename")
        out = self.run_gate()[0]
        self.assertIn("FAIL streams.owned.b_module.py:", out)
        self.assertNotIn("streams.owned.tests/test_b.py", out)
        git(self.root, "checkout", "-q", INT)                                                # TF12: stream and group branches only
        self.commit({"tests/test_b.py": "y\n"})
        self.assertIn("FAIL streams.owned.tests/test_b.py:", self.run_gate()[0])
        self.branch(REC, "main")
        self.commit({"tests/test_b.py": "y\n"})
        self.assertIn("FAIL streams.owned.tests/test_b.py:", self.run_gate()[0])

    def test_test_file_owned_by_residual_and_unicode(self):  # TF8 (Q18 (a)), TF16 (V2)
        streams, bd, names = self.layout(a_owns=[], b_owns=[], residual=True)
        self.program(streams=streams, bd=bd, status=status_page(names))
        self.branch(SA)
        self.commit({"tests/test_gap.py": "x\n"})                                            # the owner by the gap is residual: another stream
        self.assertIn("PASS streams.owned\n", self.run_gate()[0])
        self.commit({"tests/helpers.py": "x\n", "tests/test_Ⱞ.py": "x\n"})
        out = self.run_gate()[0]
        self.assertIn("FAIL streams.owned.tests/helpers.py:", out)                          # a non-test path of the residual stream
        self.assertNotIn("streams.owned.tests/test_Ⱞ.py", out)                         # TF16: the same verdict on both interpreters


SH = [{"path": "reg.md", "rule": "append-rows"}, {"path": "own.md", "rule": "own-row"}]


class RowsF(base.Fx):
    """Plan-file hunks (PF13-PF20), shared files (SH11-SH19, OW4, TF5, IN19), line ids (OU2), environment (EN6, EN7)."""
    layout, merge_line = base.Windows.layout, base.Windows.merge_line

    def stream(self, files, name=SA):
        self.branch(name)
        return self.commit(files)

    def shared_program(self, extra=None, **kw):
        self.commit(dict({"reg.md": "| h |\n| r1 |\n", "own.md": "| a | 1 |\n| b | 2 |\n", "gates.py": "x = 1\n"}, **(extra or {})))
        self.program(streams=streams_row(shared=SH + [{"path": "gates.py", "rule": "append-rows"}, {"path": "tests/test_x.py", "rule": "append-rows"}]), **kw)

    # ---- plan-file hunks
    def test_plan_hunk_rows(self):  # PF13, PF14, PF15, PF16, PF17, PF20, EN6
        own = PLAN_A.replace("body one", "body one edited")
        out_of_task = PLAN_A.replace("foreign body", "foreign edited")
        self.commit({PG + "/b-plan.md": "# b\n", ".gitattributes": "*.md diff=custom\n"})
        for k, v in (("diff.context", "5"), ("diff.algorithm", "patience"), ("diff.interHunkContext", "3"),
                     ("diff.indentHeuristic", "false"), ("diff.custom.textconv", "false"), ("diff.external", "false"),
                     ("core.hooksPath", os.path.join(self.tmp, "no-hooks"))):                # PF13, EN6
            git(self.root, "config", k, v)
        self.program()
        self.branch(SA)
        self.commit({PG + "/a-plan.md": own})
        self.assertIn("PASS streams.owned\n", self.run_gate()[0])                           # PF13: the same hunks as the plain fixture
        self.commit({PG + "/a-plan.md": out_of_task})
        self.assertIn("FAIL streams.owned.%s/a-plan.md: plan hunk at line 17" % PG, self.run_gate()[0])
        git(self.root, "checkout", "-q", "-B", SA, "main")
        self.commit({PG + "/b-plan.md": "# b edited\n", PG + "/program-plan.md": PROGRAM_PLAN_EDIT, PG + "/a-plan.md": own})
        out = self.run_gate()[0]
        self.assertIn("FAIL streams.owned.%s/b-plan.md:" % PG, out)                         # PF14: another stream's plan file
        self.assertIn("FAIL streams.owned.%s/program-plan.md:" % PG, out)                   # PF15: the program's plan file
        self.assertNotIn("streams.owned.%s/a-plan.md" % PG, out)
        self.commit({PG + "/a-plan.md": own.replace("body two", "body two edited"), "tests/test_b.py": "y\n"})
        self.assertNotIn("a-plan.md", self.run_gate()[0])                                   # PF20: both exemptions together
        git(self.root, "checkout", "-q", "main")                                            # PF17: the tree being committed
        git(self.root, "checkout", "-q", "-b", NAME + "/a/g2", "main")
        self.put(PG + "/a-plan.md", own)
        self.assertIn("PASS streams.owned\n", self.run_gate()[0])
        self.put(PG + "/a-plan.md", out_of_task)
        self.assertIn("FAIL streams.owned.%s/a-plan.md: plan hunk at line 17" % PG, self.run_gate()[0])
        git(self.root, "checkout", "--", PG + "/a-plan.md")
        git(self.root, "checkout", "-q", "-b", NAME + "/a/g1", "main")                      # PF16: a group merged into the stream
        self.commit({PG + "/a-plan.md": out_of_task})
        self.branch(NAME + "/a/g3", "main")
        git(self.root, "merge", "-q", "--no-ff", "-m", "group", NAME + "/a/g1")
        self.assertIn("FAIL streams.owned.%s/a-plan.md: plan hunk at line 17" % PG, self.run_gate()[0])

    def test_plan_task_not_in_breakdown_fails(self):  # PF18
        bd = dict(BD, streams=[dict(BD["streams"][0], tasks=["a1.1"]), BD["streams"][1]])
        self.program(bd=bd)
        self.stream({PG + "/a-plan.md": PLAN_A.replace("body two", "body two edited")})
        self.assertIn("FAIL streams.owned.%s/a-plan.md: plan hunk at line" % PG, self.run_gate()[0])

    # ---- shared files
    def test_shared_row_grammar(self):  # SH11, SH12, SH19, OW4, TF5
        self.shared_program(extra={"tests/test_x.py": "| t |\n"})
        self.branch(SA)
        reg, own = "| h |\n| r1 |\n", "| a | 1 |\n| b | 2 |\n"
        for label, files, want in (
                ("a separator row is a row", {"reg.md": reg + "|---|\n"}, ""),
                ("a leading space is no row", {"reg.md": reg + " | r2 |\n"}, "FAIL streams.shared.reg.md: append-rows"),
                ("CRLF rewrites the base", {"reg.md": "| h |\r\n| r1 |\r\n| r2 |\r\n"}, "FAIL streams.shared.reg.md:"),
                ("first cell is stripped", {"own.md": own + "|  a  | 7 |\n"}, ""),
                ("first cell is case-sensitive", {"own.md": own + "| A | 7 |\n"}, "FAIL streams.shared.own.md:"),
                ("first cell is exact", {"own.md": own + "| ab | 7 |\n"}, "FAIL streams.shared.own.md:"),
                ("an empty first cell is foreign", {"own.md": own + "|  | 7 |\n"}, "FAIL streams.shared.own.md:"),
                ("a non-ASCII first cell is foreign", {"own.md": own + "| é | 7 |\n"}, "FAIL streams.shared.own.md:"),
                ("a non-table file never passes (append-rows)", {"gates.py": "x = 1\ny = 2\n"}, "FAIL streams.shared.gates.py: append-rows"),
                ("a shared test file", {"tests/test_x.py": "| t |\nnote\n"}, "FAIL streams.shared.tests/test_x.py:")):
            self.commit({"reg.md": reg, "own.md": own, "gates.py": "x = 1\n", "tests/test_x.py": "| t |\n"})
            git(self.root, "reset", "-q", "--hard", "HEAD")
            base_head = git(self.root, "rev-parse", "HEAD")
            self.commit(files)
            out = self.run_gate()[0]
            if want:
                self.assertIn(want, out, label)
                self.assertNotIn("streams.owned.%s" % list(files)[0], out, label)           # OW4: a shared path is not an ownership failure
            else:
                self.assertIn("PASS streams.shared", out, label)
            git(self.root, "reset", "-q", "--hard", base_head)

    def test_shared_per_commit_rename_and_other_branches(self):  # SH13, SH14, SH15, IN19, SH16, SH19
        self.shared_program()
        self.branch(SA)
        self.commit({"reg.md": "| h |\n| r1 |\n| r2 |\n"})
        self.assertIn("PASS streams.shared", self.run_gate()[0])
        self.commit({"reg.md": "| h |\n| r1 |\n| r2x |\n"})                                # SH14: against each commit's parent
        out = self.run_gate()[0]
        self.assertIn("FAIL streams.shared.reg.md: append-rows", out)
        git(self.root, "checkout", "-q", "-B", SA, "main")
        self.commit({"reg.md": "| h |\n| r1 |\n| r2 |\nnote\n"}, "append a non-row")
        self.assertIn("append-rows: 'note' is not a table row", self.run_gate()[0])                  # SH19: the rule and the first offending line
        git(self.root, "checkout", "-q", "-B", SA, "main")
        git(self.root, "mv", "reg.md", "reg2.md")                                           # SH15: both sides of a rename
        commit_all(self.root, "rename")
        self.assertIn("FAIL streams.shared.reg.md:", self.run_gate()[0])
        git(self.root, "checkout", "-q", INT)                                               # SH13, IN19: an unowned path on integration
        self.commit({"reg.md": "| h |\n| r1 |\n| r2 |\n"})
        out = self.run_gate()[0]
        self.assertIn("FAIL streams.owned.reg.md:", out)
        self.assertNotIn("streams.shared", out)

    def test_shared_path_also_owned_fails_map(self):  # SH16
        a = stream("a", ["a-owned.py", "tests/test_a.py", "reg.md"], merge_order=1)
        b = stream("b", ["b-owned.py", "tests/test_b.py"], merge_order=2)
        self.program(streams=row(a, b, shared=SH[:1]), bd=bd_of(a, b))
        self.assertIn("FAIL streams.map.%s: " % NAME, self.run_gate()[0])

    def test_shared_many_rows(self):  # SH18
        n = 50000
        rows = "".join("| r%d |\n" % i for i in range(n))
        self.shared_program(extra={"reg.md": "| h |\n" + rows})
        self.branch(SA)
        self.commit({"reg.md": "| h |\n" + rows + "".join("| s%d |\n" % i for i in range(n))})
        self.assertIn("PASS streams.shared", self.run_gate()[0])
        self.commit({"reg.md": "| h |\n" + rows.replace("| r7 |", "| r7x |") + "| s |\n"})
        self.assertIn("FAIL streams.shared.reg.md: append-rows", self.run_gate()[0])

    # ---- line ids and environment
    def test_pass_lines_green_run(self):  # OU2
        self.program()
        want = ["streams.map." + NAME, "streams.status." + NAME, "streams.request", "streams.owned", "streams.integration", "streams.shared"]
        for branch, ids in ((SA, want), (NAME + "/a/g1", want), (REC, want[:5]), (INT, want[:4])):
            git(self.root, "checkout", "-q", "-B", branch, INT if branch == INT else "main")
            out, code = self.run_gate()
            self.assertEqual((self.ids(out), code), (ids, 0), branch)
            self.assertFalse([l for l in out.splitlines() if not l.startswith("PASS ")], branch)

    def test_streams_with_worktree_config_extension(self):  # EN7
        self.program()
        self.stream({"b-owned.py": "x\n"})
        first = self.run_gate()
        git(self.root, "config", "extensions.worktreeConfig", "true")
        git(self.root, "config", "--worktree", "core.abbrev", "9")
        self.assertEqual(self.run_gate(), first)

    # ---- program files read at the integration tip (MP21, MP24)
    def test_program_plan_read_at_the_tip_and_odd_streams_values(self):  # MP21 (Q16), MP24 (V1, V2)
        self.program()
        self.branch(SA)
        self.commit({PG + "/program-plan.md": "# changed\n"})                                  # the working copy is never read
        self.assertIn("PASS streams.map." + NAME, self.run_gate()[0])
        git(self.root, "checkout", "-q", INT)
        git(self.root, "rm", "-q", PG + "/program-plan.md")
        git(self.root, "commit", "-q", "-m", "no program plan")
        out = self.run_gate()[0]
        self.assertIn("FAIL streams.map.%s: " % NAME, out)
        self.assertNotIn("streams.input", out)
        git(self.root, "checkout", "-q", "main")
        git(self.root, "branch", "-D", INT)
        s = streams_row()
        s["streams"][0]["purpose"] = "ࡰ\U0001fae8"
        s["streams"][1]["estimate"] = "9" * 4301
        self.program(streams=s)
        out = self.run_gate("--branch", "other")[0]
        self.assertTrue(self.lines_of(out))
        self.assertNotIn("ValueError", out)
        self.assertNotIn("Exceeds", out)

    def lines_of(self, out):
        return [l for l in out.splitlines() if l]

    def test_merged_lines_in_any_order_and_stream_without_tasks(self):  # ME16, ME14
        layout = {"a_owns": [W("w1.py", None, "merged:a/a1"), W("w2.py", None, "merged:a/a2")],
                  "b_owns": [W("w1.py", "merged:a/a1"), W("w2.py", "merged:a/a2")]}
        streams, bd, names = self.layout(**layout)
        _, _, l1 = self.merge_line(1, "a1")
        _, _, l2 = self.merge_line(2, "a2", branch="pr2")
        for order in ((l1, l2), (l2, l1)):                                                   # the events are the same set
            self.program(merged=MERGED_HEAD + "".join(l + "\n" for l in order), streams=streams, bd=bd, status=status_page(names))
            self.branch(SB)
            self.commit({"w1.py": "x\n", "w2.py": "x\n"})
            out = self.run_gate()[0]
            self.assertIn("PASS streams.owned\n", out)
            self.assertNotIn("FAIL", out)
            git(self.root, "checkout", "-q", "main")
            git(self.root, "branch", "-D", SB, INT)
        a_owns = [W("w1.py", None, "merged:b")]                                              # ME14: a stream with no tasks never has merged:b
        b_owns = [W("w1.py", "merged:b")]
        streams, bd, names = self.layout(a_owns=a_owns, b_owns=b_owns)
        bd["streams"][1]["tasks"] = []
        self.program(merged=MERGED_HEAD + l1.replace("stream=a block=a1", "stream=b block=1a") + "\n", streams=streams, bd=bd,
                     status=status_page(names))
        self.branch(SB)
        self.commit({"w1.py": "x\n"})
        out = self.run_gate()[0]
        self.assertIn("FAIL streams.owned.w1.py:", out)                                      # the window never opens
        self.assertIn("FAIL streams.map.%s: " % NAME, out)                                   # and the line itself is refused
        self.assertEqual(self.run_gate("--branch", "other")[0].count("PASS streams.map"), 0)

    def test_shared_path_inside_an_owned_directory_fails_map(self):  # SH17
        a = stream("a", ["a-owned.py", "tests/test_a.py", "docs/"], merge_order=1)
        b = stream("b", ["b-owned.py", "tests/test_b.py"], merge_order=2)
        self.program(streams=row(a, b, shared=[{"path": "docs/reg.md", "rule": "append-rows"}]), bd=bd_of(a, b))
        self.assertIn("FAIL streams.map.%s: " % NAME, self.run_gate()[0])


PROGRAM_PLAN_EDIT = PROGRAM_PLAN.replace("## Block a1: x", "## Block a1: y")


if __name__ == "__main__":
    unittest.main()
