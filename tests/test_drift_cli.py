"""Task 5c.2: ``gates/tools/drift_cli.py`` (``python3 -m gates drift report``) through ``drift_cli.main(argv)`` on real git
fixture repositories (table task-5c.2-domain.md: the R and V rows are in each test's comment). Expected text is typed by hand."""
import builtins
import os
import sys
import unittest
from unittest import mock

from gates import __main__ as entry
from gates.tools import drift_cli
from tests.drift_fx import P, P2, PD, Fx, mkrow, page, snapshot, streams_text
from tests.helpers import INT_LIMITS, GitIsolatedTestCase, git, int_limit, minimal_config, root_forms, write_record

OVER = "over a used=16 estimate=10 limit=150%\n"


class Cli(Fx):
    def rep(self, *argv):
        return self.run_main(drift_cli.main, ["report", "--root", self.root] + list(argv))

    def over(self, p=P, rows=None, sids=("a",)):
        self.prog(p, sids, rows=rows if rows is not None else [mkrow(p, "a", used="16")])

    def config(self, pct):
        """The config with ``drift.estimate_factor_pct`` of ``pct`` (an int or a digit string), in the work tree only."""
        text = "schema: config/2\nframework_version: 0.0.0\nprofile: strict\ndrift:\n  estimate_factor_pct: %s\n" % pct
        with open(os.path.join(self.root, ".strict-delivery", "config.yml"), "w", encoding="utf-8") as fh:
            fh.write(text)


class Report(Cli):
    def test_report_lists_over_rows(self):  # R1
        self.over()
        self.assertEqual(self.rep(), (OVER, "", 0))

    def test_report_none(self):  # R2
        for used, estimate in (("15", "10"), ("0", "10"), ("0", "0")):
            with self.subTest(used=used, estimate=estimate):
                self.prog(P, ("a",), rows=[mkrow(P, "a", used=used, estimate=estimate)])
                self.assertEqual(self.rep(), ("none\n", "", 0))

    def test_report_one_line_per_over_row(self):  # R3
        rows = [mkrow(P, "b", used="20"), mkrow(P, "a", used="16"), mkrow(P, "c", used="11", estimate="1")]
        self.prog(P, ("a", "b", "c"), rows=rows)
        self.assertEqual(self.rep(), ("over b used=20 estimate=10 limit=150%\nover a used=16 estimate=10 limit=150%\n"
                                      "over c used=11 estimate=1 limit=150%\n", "", 0))

    def test_report_two_programs(self):  # R4
        self.over(P2)
        self.over(P)
        self.assertEqual(self.rep(), (OVER + OVER, "", 0))
        self.prog(P2, ("a",), rows=[mkrow(P2, "a", used="99")])
        self.assertEqual(self.rep()[0], OVER + "over a used=99 estimate=10 limit=150%\n")

    def test_report_program_option(self):  # R5
        self.over(P)
        self.prog(P2, ("a",), rows=[mkrow(P2, "a", used="99")])
        self.assertEqual(self.rep("--program", P), (OVER, "", 0))
        self.assertEqual(self.rep("--program", P2), ("over a used=99 estimate=10 limit=150%\n", "", 0))
        self.assertEqual(self.rep("--program", P2, "--program", P)[0], OVER + "over a used=99 estimate=10 limit=150%\n")
        self.assertEqual(self.rep("--program", P, "--program", P)[0], OVER)
        out, err, code = self.rep("--program", "20261103-z")
        self.assertEqual((out, err, code), ("", "drift: program 20261103-z is not live: no local branch 20261103-z/integration "
                                                "whose tip holds streams.yml\n", 1))
        for bad in ("A", "", P + " "):
            with self.subTest(program=bad):
                out, err, code = self.rep("--program", bad)
                self.assertEqual((out, code), ("", 1))
                self.assertTrue(err.startswith("drift: program name: ") and err.count("\n") == 1, err)
        out, err, code = self.rep("--program", P, "--program", "20261103-z")
        self.assertEqual((out, code), ("", 1))

    def test_report_no_program_is_none(self):  # R6
        self.assertEqual(self.rep(), ("none\n", "", 0))

    def test_report_pct_from_config(self):  # R7
        self.prog(P, ("a",), rows=[mkrow(P, "a", used="13")])
        self.assertEqual(self.rep(), ("none\n", "", 0))
        self.config(120)
        self.assertEqual(self.rep(), ("over a used=13 estimate=10 limit=120%\n", "", 0))

    def test_report_pct_too_large(self):  # R8, V1a, V1b
        self.over()
        for digits, text in ((601, "9" * 601), (601, "1" + "0" * 600), (1000, "9" * 1000)):
            with self.subTest(digits=digits, text=text[:3]):
                self.config(text)
                out, err, code = self.rep()
                self.assertEqual((out, code), ("", 1))
                self.assertTrue(err.startswith("drift: ") and "drift.estimate_factor_pct" in err, err)
                self.assertNotIn("Traceback", err)
        self.config("9" * 1001)
        out, err, code = self.rep()
        self.assertEqual((out, code), ("", 1))
        self.assertEqual(err, "drift: .strict-delivery/config.yml: integer too large (line 5)\n")

    def test_version_no_int_to_text_over_limit(self):  # V1c
        self.prog(P, ("a",), rows=[mkrow(P, "a", used="9" * 600, estimate="0")])
        self.config("9" * 600)
        self.assertEqual(self.rep(), ("over a used=%s estimate=0 limit=%s%%\n" % ("9" * 600, "9" * 600), "", 0))
        self.prog(P, ("a",), rows=[mkrow(P, "a", used="9" * 600, estimate="1")])
        self.config(10 ** 599)
        self.assertEqual(self.rep()[0], "over a used=%s estimate=1 limit=1%s%%\n" % ("9" * 600, "0" * 599))

    def test_report_program_does_not_load(self):  # R9
        self.over(P)
        for name, kw in (("streams.yml", {"streams": "[unclosed\n"}), ("status.md", None), ("request", {"files": {
                PD + "/%s/requests/notes.txt" % P2: "x\n"}})):
            with self.subTest(case=name):
                if kw is None:
                    self.prog(P2, ("a",))
                    git(self.root, "checkout", "-q", P2 + "/integration")
                    git(self.root, "rm", "-q", "%s/%s/status.md" % (PD, P2))
                    git(self.root, "commit", "-q", "-m", "rm")
                    git(self.root, "checkout", "-q", "main")
                else:
                    self.prog(P2, ("a",), **kw)
                out, err, code = self.rep()
                self.assertEqual((out, code), (OVER, 1))
                self.assertTrue(err.startswith("drift: ") and err.count("\n") == 1 and name.split("/")[-1].split(".")[0] in err, err)
                git(self.root, "branch", "-q", "-D", P2 + "/integration")
        self.prog(P2, ("a",), streams="[unclosed\n")
        git(self.root, "branch", "-q", "-D", P + "/integration")
        out, err, code = self.rep()
        self.assertEqual((out, code), ("", 1))

    def test_report_invalid_page_is_load_failure(self):  # R10, R13
        digits601 = "9" * 601
        for name, rows in (("-1", [mkrow(P, "a", used="-1")]), ("007", [mkrow(P, "a", used="007")]),
                           ("601", [mkrow(P, "a", used=digits601)]), ("missing", []), ("٣", [mkrow(P, "a", used="٣")]),
                           ("1_0", [mkrow(P, "a", estimate="1_0")])):
            with self.subTest(case=name):
                self.prog(P, ("a",), rows=rows)
                out, err, code = self.rep()
                self.assertEqual((out, code), ("", 1))
                self.assertTrue(err.startswith("drift: %s: " % P) and err.count("\n") == 1, err)
                self.assertNotIn("Traceback", err)
        self.prog(P, ("a",), rows=[mkrow(P, "a", used="9" * 600, estimate="9" * 600)])
        self.assertEqual(self.rep(), ("none\n", "", 0))

    def test_report_names_first_status_text(self):  # R10: the first text of the page, nothing else
        self.prog(P, ("a",), rows=[mkrow(P, "a", status="Running", used="-1")])
        self.assertEqual(self.rep(), ("", "drift: %s: stream a: status 'Running' is not one of ready, running, blocked, checkpoint, "
                                          "merged, closed\n" % P, 1))

    def test_report_status_text_escaped_once(self):  # R10, S15, V2a (F-20261124-hu7f): stderr text is escaped once
        for cell, shown in (("x\\y", "x\\\\y"), ("ࡰ", "\\u0870"), ("Ꟁ", "\\ua7c0"), ("\U0001e030", "\\U0001e030"),
                            ("x\\yࡰ", "x\\\\y\\u0870")):
            with self.subTest(cell=shown):
                self.prog(P, ("a",), rows=[mkrow(P, "a", status=cell, used="-1")])
                self.assertEqual(self.rep(), ("", "drift: %s: stream a: status '%s' is not one of ready, running, blocked, "
                                                  "checkpoint, merged, closed\n" % (P, shown), 1))

    def test_report_numeric_text_4300_4301_digits(self):  # V1a, V1b: refused before int(), same on both interpreters
        for limit in INT_LIMITS:
            for digits in (4300, 4301):
                for key in ("used", "estimate"):
                    with self.subTest(limit=limit, digits=digits, key=key), int_limit(limit):
                        self.prog(P, ("a",), rows=[mkrow(P, "a", **{key: "9" * digits})])
                        out, err, code = self.rep()
                        self.assertEqual((out, code), ("", 1))
                        self.assertEqual(err, "drift: %s: stream a: %s '%s' is not a non-negative decimal integer\n"
                                         % (P, key, "9" * digits))
                with self.subTest(limit=limit, digits=digits, key="pct"), int_limit(limit):
                    self.over()
                    self.config("9" * digits)
                    out, err, code = self.rep()
                    self.assertEqual((out, code), ("", 1))
                    self.assertEqual(err, "drift: .strict-delivery/config.yml: integer too large (line 5)\n")

    def test_report_ignores_status(self):  # R11
        self.prog(P, ("a", "b"), rows=[mkrow(P, "a", status="merged", used="99"), mkrow(P, "b", status="closed", used="99")])
        self.assertEqual(self.rep()[0], "over a used=99 estimate=10 limit=150%\nover b used=99 estimate=10 limit=150%\n")

    def test_report_is_per_row(self):  # R12
        self.prog(P, ("a", "b"), rows=[mkrow(P, "a", block="5c", estimate="100", used="120"),
                                       mkrow(P, "b", block="5c", estimate="10", used="16")])
        self.assertEqual(self.rep()[0], "over b used=16 estimate=10 limit=150%\n")

    def test_report_echoes_cell_text(self):  # R14
        self.prog(P, ("a",), rows=[mkrow(P, "a", used="9" * 600, estimate="1")])
        self.assertEqual(self.rep()[0], "over a used=%s estimate=1 limit=150%%\n" % ("9" * 600))

    def test_drift_usage_refusals(self):  # R15, R17
        for argv in ([], ["bogus"], ["report", "extra"], ["report", "--host"], ["report", "--json"], ["report", "-h"],
                     ["report", "--root"], ["report", "--root", self.root, "--root", self.root], ["--root", self.root]):
            with self.subTest(argv=argv):
                out, err, code = self.run_main(drift_cli.main, argv)
                self.assertEqual((out, code), ("", 2))
                self.assertNotEqual(err, "")
        out, err, code = self.run_main(drift_cli.main, ["report", "--root", self.root, "--root", self.root])
        self.assertIn("--root given more than once", err)

    def test_report_root_forms(self):  # R16
        self.over()
        for name, path, verdict in root_forms(self.tmp, self.root):
            with self.subTest(form=name):
                out, err, code = self.run_main(drift_cli.main, ["report", "--root", path])
                if name == "nested":
                    self.assertEqual((out, code), ("", 1))
                    self.assertEqual(err, "drift: .strict-delivery/config.yml: missing; run /strict-delivery:init\n")
                elif verdict == "ok":
                    self.assertEqual((out, err, code), (OVER, "", 0))
                else:
                    self.assertEqual((out, code), ("", 1))
                    self.assertTrue(err.startswith("drift: ") and verdict in err, err)

    def test_report_reads_integration_tip(self):  # R18, R19
        self.over()
        path = self.worktree("int", P + "/integration")
        self.put("%s/%s/status.md" % (PD, P), page([mkrow(P, "a", used="0")]), root=path)
        self.assertEqual(self.rep(), (OVER, "", 0))
        self.assertEqual(self.run_main(drift_cli.main, ["report", "--root", path]), (OVER, "", 0))
        git(self.root, "branch", "stream", "main")
        spath = self.worktree("str", "stream")
        self.assertEqual(self.run_main(drift_cli.main, ["report", "--root", spath]), (OVER, "", 0))

    def test_report_stdout_only(self):  # R20, R24
        self.prog(P, ("a", "b"), rows=[mkrow(P, "a", used="16"), mkrow(P, "b", used="17")])
        out, err, code = self.rep()
        self.assertEqual(err, "")
        self.assertTrue(out.endswith("\n") and "\n\n" not in out)
        self.assertNotIn("PASS", out + err)
        self.assertNotIn("FAIL", out + err)

    def test_drift_command_registered(self):  # R21
        if "drift" not in entry.COMMANDS:
            self.skipTest("Rq-5-1 not on this branch")
        self.over()
        self.assertEqual(self.run_main(entry.main, ["drift", "report", "--root", self.root]), (OVER, "", 0))

    def test_report_writes_nothing(self):  # R22
        self.over()
        before = snapshot(self.root)
        self.rep()
        self.rep("--program", P)
        self.assertEqual(snapshot(self.root), before)

    def test_report_exit_codes(self):  # R23
        self.over()
        self.assertEqual(self.rep()[2], 0)
        self.assertEqual(self.rep("--program", P2)[2], 1)
        self.assertEqual(self.run_main(drift_cli.main, ["report", "--bogus"])[2], 2)


class Versions(Cli):
    def test_version_exception_group_in_report(self):  # V3b
        eg, beg = getattr(builtins, "ExceptionGroup", None), getattr(builtins, "BaseExceptionGroup", None)
        if eg is None or beg is None:
            self.skipTest("ExceptionGroup absent on 3.9")
        self.over()
        with mock.patch("gates.gate_drift.programs.load_program", side_effect=eg("g", [ValueError()])):
            self.assertEqual(self.rep(), ("", "drift: ExceptionGroup: g (1 sub-exception)\n", 1))
        with mock.patch("gates.gate_drift.programs.load_program", side_effect=beg("g", [KeyboardInterrupt()])):
            with self.assertRaises(beg):
                self.rep()

    def test_report_unexpected_exception_is_exit_1(self):  # Q20 (a): any Exception while judging one program
        self.over()
        with mock.patch("gates.gate_drift.programs.load_program", side_effect=ValueError("boom")):
            self.assertEqual(self.rep(), ("", "drift: ValueError: boom\n", 1))
        with mock.patch("gates.gate_drift.programs.load_program", side_effect=KeyboardInterrupt()):
            with self.assertRaises(KeyboardInterrupt):
                self.rep()
        with mock.patch("gates.gate_drift.programs.live_programs", side_effect=ValueError("sel")):
            self.assertEqual(self.rep(), ("", "drift: ValueError: sel\n", 1))

    def test_version_unicode_same_on_both(self):  # V2a: a handoff-free page with non-ASCII cells reports the same lines
        for ch in ("ࡰ", "Ꟁ", "\U0001e030", "é"):
            with self.subTest(ch=ch):
                self.prog(P, ("a",), rows=[mkrow(P, "a", used="16", delivers=ch, block=ch)])
                self.assertEqual(self.rep(), (OVER, "", 0))
        out, err, code = self.rep("--program", "é-x")
        self.assertEqual((out, code), ("", 1))


if __name__ == "__main__":
    unittest.main()
