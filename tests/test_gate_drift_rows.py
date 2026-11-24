"""Task 5c.2 (rows of the table task-5c.2-domain.md: S, B, L, H): ``gates/gate_drift.py`` through ``gate_drift.main(argv)``
on real git fixture repositories: the status page, the program-level lines and the stream lines. Split from
tests/test_gate_drift.py as tests/test_gate_streams_rows.py is from tests/test_gate_streams.py; same conventions."""
import ast
import builtins
import inspect
import json
import os
import subprocess
import sys
import unittest
from unittest import mock

from gates import __main__ as entry, gate_drift, run_all
from gates.lib import drift as dlib
from gates.lib.result import GateError, Result
from tests.drift_fx import (P, P2, PD, RID, Fx, handoff_text, mkrow, page, request_text, snapshot, streams_text)
from tests.helpers import E128, TOP, INT_LIMITS, GitIsolatedTestCase, commit_all, git, int_limit, make_repo, minimal_config, \
    root_forms, write_record

REAL_HOST = dlib.host_errors
BASE = "PASS drift.base"
CHECKS = ("branch", "behind", "merged", "handoff", "pending", "blockers")


def ok(p):
    """The nine PASS lines of a program with nothing failed, in the order of decision D-5c2-Q6."""
    return ["PASS drift.status." + p, "PASS drift.integration." + p] + ["PASS drift.%s.%s" % (c, p) for c in CHECKS]


class Runner:
    """A stand-in for ``subprocess.run`` that ``drift.host_errors`` takes as its ``runner``."""

    def __init__(self, result=None, raises=None):
        self.result, self.raises, self.calls = result, raises, []

    def __call__(self, argv, **kw):
        self.calls.append((argv, kw))
        if self.raises is not None:
            raise self.raises
        return self.result


def done(stdout="[]", code=0, stderr=""):
    return subprocess.CompletedProcess(["gh"], code, stdout, stderr)


def host_with(runner):
    return lambda root, cfg, prog: REAL_HOST(root, cfg, prog, runner=runner)


class Gate(Fx):
    def g(self, *argv):
        out, _err, code = self.run_main(gate_drift.main, ["--root", self.root] + list(argv))
        return out, code

    def lines(self, *argv):
        return self.g(*argv)[0].splitlines()

    def two(self):
        self.insync(P)
        self.insync(P2)

    def one_input_fail(self, out, fragment=""):
        ls = out.splitlines()
        self.assertEqual(len(ls), 1, out)
        self.assertTrue(ls[0].startswith("FAIL drift.input: "), out)
        self.assertIn(fragment, ls[0])


class Status(Gate):
    def test_program_read_at_branch_not_tag(self):  # S1
        self.insync()
        git(self.root, "tag", P + "/integration", "main")   # a tag of the same name at a commit with no program files
        self.assertEqual(self.lines(), [BASE] + ok(P))

    def test_invalid_status_page_skips_rows(self):  # S3, H6
        self.sbranch(P, "a")
        good = mkrow(P, "a")
        cases = {
            "status": ([mkrow(P, "a", status="Running")], "status 'Running' is not one of ready"),
            "missing row": ([], "missing row for stream a"),
            "extra row": ([good, mkrow(P, "zz")], "extra row: stream 'zz' is not a stream of the program"),
            "duplicate row": ([good, good], "duplicate row for stream a"),
            "used": ([mkrow(P, "a", used="-1")], "used '-1'"),
            "blocker": ([mkrow(P, "a", blockers="R-20261101-zzzz")], "R-20261101-zzzz"),
            "pending": ([mkrow(P, "a", **{"pending decisions": "nope"})], "nope"),
            "branch cell": ([mkrow(P, "a", branch="other/a/main")], "branch"),
            "worktree cell": ([mkrow(P, "a", worktree="../elsewhere")], "worktree"),
        }
        for name, (rows, fragment) in cases.items():
            with self.subTest(case=name):
                self.prog(P, ("a",), rows=rows)
                with mock.patch("gates.gate_drift.drift.host_errors", side_effect=AssertionError("host skipped")):
                    out, code = self.g("--host")
                fails = [l for l in out.splitlines() if l.startswith("FAIL drift.status." + P + ": ")]
                self.assertEqual(len(fails), 1, out)
                self.assertIn(fragment, fails[0])
                for c in CHECKS + ("host",):
                    self.assertNotIn("drift.%s.%s" % (c, P), out)
                self.assertEqual(code, 1)
                git(self.root, "branch", "-q", "-D", P + "/integration")

    def test_two_problems_two_lines(self):  # S3: one line per text
        self.sbranch(P, "a")
        self.prog(P, ("a",), rows=[mkrow(P, "a", status="Running", used="-1")])
        fails = [l for l in self.lines() if l.startswith("FAIL drift.status.")]
        self.assertEqual(len(fails), 2)

    def test_invalid_status_page_keeps_integration(self):  # S4
        self.sbranch(P, "a")
        self.prog(P, ("a",), rows=[mkrow(P, "a", status="Running")])
        self.commit_on("main", {"m.txt": "m\n"})
        out, code = self.g()
        ls = out.splitlines()
        self.assertEqual(ls[0], BASE)
        self.assertTrue(ls[1].startswith("FAIL drift.status.%s: " % P), out)
        self.assertEqual(ls[2], "FAIL drift.integration.%s: integration is behind main; run a sync" % P)
        self.assertEqual(len(ls), 3)

    def test_invalid_page_does_not_hide_other_program(self):  # S5
        self.sbranch(P, "a")
        self.prog(P, ("a",), rows=[mkrow(P, "a", status="Running")])
        self.insync(P2)
        out, code = self.g()
        ls = out.splitlines()
        self.assertEqual(ls[0], BASE)
        self.assertEqual(len(ls), 1 + 2 + 8, out)
        self.assertTrue(ls[1].startswith("FAIL drift.status.%s: " % P))
        self.assertEqual(ls[2], "PASS drift.integration." + P)
        self.assertEqual(ls[3:], ok(P2))
        self.assertEqual(code, 1)

    def test_status_no_table(self):  # S6
        self.prog(P, ("a",), status_text="no table here\n")
        out, code = self.g()
        self.assertEqual(out.splitlines()[1], "FAIL drift.status.%s: missing row for stream a" % P)

    def test_streams_yml_does_not_load(self):  # S7
        self.insync(P)
        for text in ("[unclosed\n", "- a\n- b\n"):
            with self.subTest(text=text):
                self.prog(P2, ("a",), streams=text)
                out, code = self.g()
                self.one_input_fail(out, "streams.yml")
                self.assertEqual(code, 1)
                git(self.root, "branch", "-q", "-D", P2 + "/integration")

    def test_program_file_does_not_load(self):  # S8
        self.insync(P)
        rel = "%s/%s/" % (PD, P2)
        cases = {"status.md": None, "BOM": ("status.md", "﻿" + page([mkrow(P2, "a")])),
                 "stray request": ("requests/notes.txt", "x\n")}
        for name, edit in cases.items():
            with self.subTest(case=name):
                self.prog(P2, ("a",), requests={})
                git(self.root, "checkout", "-q", P2 + "/integration")
                if edit is None:
                    git(self.root, "rm", "-q", rel + "status.md")
                else:
                    self.put(rel + edit[0], edit[1])
                commit_all(self.root, "break")
                git(self.root, "checkout", "-q", "main")
                out, code = self.g()
                self.one_input_fail(out, "status.md" if edit is None or edit[0] == "status.md" else "notes.txt")
                self.assertEqual(code, 1)
                git(self.root, "branch", "-q", "-D", P2 + "/integration")
        with self.subTest(case="requests symlink"):
            self.prog(P2, ("a",))
            git(self.root, "checkout", "-q", P2 + "/integration")
            os.symlink("..", os.path.join(self.root, rel + "requests"))
            commit_all(self.root, "link")
            git(self.root, "checkout", "-q", "main")
            self.one_input_fail(self.g()[0], "requests")

    def test_streams_program_mismatch(self):  # S9
        self.sbranch(P, "a")
        self.prog(P, ("a",), streams=streams_text(P, ("a",), program=P2))
        fails = [l for l in self.lines() if l.startswith("FAIL drift.status.")]
        self.assertTrue(fails and all("%s/a/main" % P2 in l for l in fails), fails)

    def test_request_ids_passed(self):  # S10
        self.sbranch(P, "a")
        stat = {"open": "ok", "accepted": "ok", "disputed": "ok", "done": "bad", "withdrawn": "bad"}
        for n, (status, verdict) in enumerate(stat.items()):
            rid = "R-20261101-aa%s" % "abcde"[n] + "a"
            with self.subTest(status=status):
                self.prog(P, ("a",), rows=[mkrow(P, "a", blockers=rid)], requests={rid: request_text(rid, status)})
                out, code = self.g()
                if verdict == "ok":
                    self.assertIn("PASS drift.blockers." + P, out)
                    self.assertEqual(code, 0)
                else:
                    self.assertIn("FAIL drift.blockers.%s.a: request %s is %s, not open, accepted or disputed" % (P, rid, status), out)
                    self.assertNotIn("drift.status.%s:" % P, out)
                git(self.root, "branch", "-q", "-D", P + "/integration")
        # a request record whose id is not a str is left out of the ids a blockers cell may name
        self.prog(P, ("a",))
        real_load = gate_drift.programs.load_program

        def load(root, cfg, name, ref):
            prog = real_load(root, cfg, name, ref)
            prog.requests.append(type(request_stub)(7, {"id": 7, "status": "open"}, "x"))
            return prog
        request_stub = gate_drift.programs.store.Record(RID, {}, "x")
        with mock.patch("gates.gate_drift.programs.load_program", side_effect=load):
            self.assertEqual(self.lines(), [BASE] + ok(P))

    def test_status_read_at_tip_not_working_tree(self):  # S11, S12
        self.insync()
        want = self.g()[0]
        path = self.worktree("int", P + "/integration")
        self.put("%s/%s/status.md" % (PD, P), page([mkrow(P, "a", used="-1")]), root=path)
        self.assertEqual(self.g()[0], want)
        self.assertEqual(self.run_main(gate_drift.main, ["--root", path])[0], want)

    def test_many_streams(self):  # S13
        sids = ["s%02d" % n for n in range(1, 31)]
        rows = [mkrow(P, s, status="ready") for s in sids]
        rows[16] = mkrow(P, "s17", status="running")
        self.prog(P, sids, rows=rows)
        out, code = self.g()
        want = [BASE, "PASS drift.status." + P, "PASS drift.integration." + P,
                "FAIL drift.branch.%s.s17: no local branch %s/s17/main" % (P, P)]
        self.assertEqual(out.splitlines()[:4], want)
        self.assertEqual(len(out.splitlines()), 4 + 5)
        self.assertEqual(code, 1)

    def test_status_digit_limit_same_on_both(self):  # S14, V1a, V1b
        self.sbranch(P, "a")
        for limit in INT_LIMITS:
            for digits, valid in ((600, True), (601, False), (4300, False), (4301, False)):
                for key in ("used", "estimate"):
                    with self.subTest(limit=limit, digits=digits, key=key), int_limit(limit):
                        self.prog(P, ("a",), rows=[mkrow(P, "a", **{key: "9" * digits})])
                        out, code = self.g()
                        fails = [l for l in out.splitlines() if l.startswith("FAIL drift.status.")]
                        if valid:
                            self.assertEqual(fails, [])
                        else:
                            self.assertEqual(len(fails), 1)
                            self.assertIn("%s '%s' is not a non-negative decimal integer" % (key, "9" * digits), fails[0])
                        git(self.root, "branch", "-q", "-D", P + "/integration")

    def test_status_unicode_cells_same_on_both(self):  # S15, V2a, V2b
        self.sbranch(P, "a")
        for ch, shown in (("ࡰ", "\\u0870"), ("Ꟁ", "\\ua7c0"), ("\U0001e030", "\\U0001e030"), ("é", "é")):
            with self.subTest(ch=shown):
                self.prog(P, ("a",), rows=[mkrow(P, "a", delivers=ch, block=ch)])
                out, code = self.g()
                self.assertNotIn("drift.status.%s:" % P, out)
                line = [l for l in out.splitlines() if l.startswith("FAIL drift.handoff.%s.a: block: the status row says '" % P)]
                self.assertEqual(len(line), 1, out)
                self.assertTrue(line[0].endswith("', the handoff says '5c'"), line)
                self.assertNotIn(ch if shown != ch else "\0", line[0])   # an unprintable character never leaves raw
                self.assertIn(shown.lstrip("\\"), line[0])
                git(self.root, "branch", "-q", "-D", P + "/integration")


class ProgramLines(Gate):
    def base_fx(self):
        self.insync()

    def test_base_pass_line(self):  # B2
        self.insync()
        self.assertEqual(self.lines()[0], BASE)   # no upstream
        bare = self.remote()
        self.assertEqual(self.lines()[0], BASE)   # upstream equal
        self.commit_on("main", {"ahead.txt": "a\n"})
        self.assertEqual(self.lines()[0], BASE)   # local ahead of the upstream
        git(self.root, "config", "branch.main.merge", "refs/heads/gone")
        self.assertEqual(self.lines()[0], BASE)   # upstream gone

    def test_base_upstream_ahead_fails(self):  # B3
        self.insync()
        bare = self.remote()
        self.advance_remote(bare)
        git(self.root, "fetch", "-q", "origin")
        want = ("FAIL drift.base: update main from the remote: git -C %s fetch origin, then git -C %s merge --ff-only origin/main"
                % (self.root, self.root))
        out, code = self.g()
        self.assertEqual(out.splitlines()[0], want)
        self.assertEqual(out.splitlines()[1:], ok(P))
        self.assertEqual(code, 1)
        path = self.worktree("int", P + "/integration")
        self.assertEqual(self.run_main(gate_drift.main, ["--root", path])[0], out)

    def test_base_is_local_only(self):  # B5
        self.insync()
        bare = self.remote()
        self.advance_remote(bare)   # not fetched: the remote-tracking ref has not moved
        with mock.patch("gates.gate_drift.drift.host_errors", return_value=[]):
            self.assertEqual(self.lines("--host")[0], BASE)
        self.assertEqual(self.lines()[0], BASE)

    def test_base_branch_absent(self):  # B6
        self.insync()
        cfg = minimal_config()
        cfg["base_branch"] = "release"
        write_record(self.root, ".strict-delivery/config.yml", cfg)
        out, code = self.g()
        self.one_input_fail(out, "no local branch")
        self.assertIn("release", out)

    def test_integration_passes(self):  # B7, B12
        self.insync()
        self.assertIn("PASS drift.integration." + P, self.lines())
        self.commit_on(P + "/integration", {"extra.txt": "e\n"})
        self.assertEqual(self.lines(), [BASE] + ok(P))

    def test_behind_main_fails_until_sync(self):  # B8, B11, B12
        self.insync()
        self.commit_on("main", {"m.txt": "m\n"})
        out, code = self.g()
        self.assertEqual(code, 1)
        self.assertIn("FAIL drift.integration.%s: integration is behind main; run a sync" % P, out.splitlines())
        self.assertIn("FAIL drift.behind.%s.a: behind main; run a sync" % P, out.splitlines())
        self.merge_main_into(P + "/integration", P + "/a/main")
        out, code = self.g()
        self.assertEqual((out.splitlines(), code), ([BASE] + ok(P), 0))

    def test_integration_diverged_fails(self):  # B9
        self.insync()
        self.commit_on("main", {"m.txt": "m\n"})
        self.commit_on(P + "/integration", {"i.txt": "i\n"})
        self.assertIn("FAIL drift.integration.%s: integration is behind main; run a sync" % P, self.lines())

    def test_program_level_suffix_is_input(self):  # B14: the suffix of a base or integration tuple is checked
        self.insync()
        for name, value in (("base_errors", [("integration." + P, "x")]), ("base_errors", [("basement", "x")]),
                            ("integration_errors", [("integration.zz", "x")]), ("integration_errors", [("base", "x")])):
            with self.subTest(name=name, value=value), mock.patch("gates.gate_drift.drift." + name, return_value=value):
                self.one_input_fail(self.g()[0], "a drift check gave suffix")
        with mock.patch("gates.gate_drift.drift.base_errors", return_value=[("base", "r1"), ("base", "r2")]):
            self.assertEqual(self.lines()[:2], ["FAIL drift.base: r1", "FAIL drift.base: r2"])
        with mock.patch("gates.gate_drift.drift.integration_errors", return_value=[("integration." + P, "r3")]):
            self.assertEqual(self.lines()[2], "FAIL drift.integration.%s: r3" % P)

    def test_integration_branch_absent(self):  # B10
        self.insync()
        git(self.root, "branch", "-q", "-D", P + "/integration")
        with mock.patch("gates.gate_drift.programs.live_programs", return_value=[P]):
            out, code = self.g()
        self.one_input_fail(out)
        self.assertEqual(code, 1)

    def test_base_branch_forms(self):  # B13
        self.insync()
        git(self.root, "branch", "release/1.0", "main")
        cfg = minimal_config()
        cfg["base_branch"] = "release/1.0"
        write_record(self.root, ".strict-delivery/config.yml", cfg)
        self.assertEqual(self.lines(), [BASE] + ok(P))
        write_record(self.root, ".strict-delivery/config.yml", minimal_config())   # the commit below must not carry it
        self.commit_on("release/1.0", {"r.txt": "r\n"})
        write_record(self.root, ".strict-delivery/config.yml", cfg)
        out = self.lines()
        self.assertIn("FAIL drift.integration.%s: integration is behind release/1.0; run a sync" % P, out)
        self.assertIn("FAIL drift.behind.%s.a: behind release/1.0; run a sync" % P, out)
        cfg["base_branch"] = "a@b"
        write_record(self.root, ".strict-delivery/config.yml", cfg)
        out, code = self.g()
        self.one_input_fail(out)
        self.assertEqual(code, 1)

    def test_gate_writes_nothing(self):  # L11
        self.insync()
        self.commit_on("main", {"m.txt": "m\n"})
        before = snapshot(self.root)
        self.assertEqual(self.g()[1], 1)
        self.assertEqual(self.g("--program", P)[1], 1)
        self.assertEqual(snapshot(self.root), before)

    def test_gate_prints_no_estimate_line(self):  # L12
        self.insync(used="99", estimate="10")
        out, code = self.g()
        self.assertEqual((out.splitlines(), code), ([BASE] + ok(P), 0))
        self.assertNotIn("estimate", out)
        self.assertNotIn("over", out)


class StreamLines(Gate):
    def stream_lines(self, fn, sids=("a",), rows=None):
        self.prog(P, sids, rows=rows)
        with mock.patch("gates.gate_drift.drift.stream_errors", side_effect=fn):
            return self.g()

    def test_every_stream_failure_has_its_line(self):  # L1
        got = [(c + ".a", "reason " + c) for c in CHECKS]
        out, code = self.stream_lines(lambda *a: list(got))
        want = [BASE, "PASS drift.status." + P, "PASS drift.integration." + P]
        want += ["FAIL drift.%s.%s.a: reason %s" % (c, P, c) for c in CHECKS]
        self.assertEqual(out.splitlines(), want)
        self.assertEqual(code, 1)

    def test_failed_check_has_no_pass_line(self):  # L3
        self.prog(P, ("a", "b"))
        fn = lambda root, cfg, prog, row, st: [("behind.a", "why")] if st["id"] == "a" else []
        with mock.patch("gates.gate_drift.drift.stream_errors", side_effect=fn):
            out, code = self.g()
        self.assertEqual(out.splitlines(), [BASE, "PASS drift.status." + P, "PASS drift.integration." + P,
                                            "PASS drift.branch." + P, "FAIL drift.behind.%s.a: why" % P] +
                         ["PASS drift.%s.%s" % (c, P) for c in CHECKS[2:]])
        self.assertNotIn("PASS drift.behind", out)

    def test_one_line_per_tuple(self):  # L4
        out, code = self.stream_lines(lambda *a: [("handoff.a", "one"), ("handoff.a", "two"), ("handoff.a", "three")])
        self.assertEqual([l for l in out.splitlines() if "handoff" in l],
                         ["FAIL drift.handoff.%s.a: %s" % (P, w) for w in ("one", "two", "three")])

    def test_line_order(self):  # L5
        self.insync(P)
        self.insync(P2)
        git(self.root, "branch", "-q", "-D", P + "/integration")
        git(self.root, "branch", "-q", "-D", P2 + "/integration")
        self.prog(P, ("a", "b"))
        self.prog(P2, ("a", "b"))

        def fn(root, cfg, prog, row, st):
            if st["id"] == "b":
                return [("behind.b", "bb"), ("branch.b", "br")]
            return [("blockers.a", "ba")] if prog.name == P else []
        with mock.patch("gates.gate_drift.drift.stream_errors", side_effect=fn):
            out, code = self.g()
        want = [BASE,
                "PASS drift.status." + P, "PASS drift.integration." + P, "FAIL drift.branch.%s.b: br" % P,
                "FAIL drift.behind.%s.b: bb" % P, "PASS drift.merged." + P, "PASS drift.handoff." + P,
                "PASS drift.pending." + P, "FAIL drift.blockers.%s.a: ba" % P,
                "PASS drift.status." + P2, "PASS drift.integration." + P2, "FAIL drift.branch.%s.b: br" % P2,
                "FAIL drift.behind.%s.b: bb" % P2, "PASS drift.merged." + P2, "PASS drift.handoff." + P2,
                "PASS drift.pending." + P2, "PASS drift.blockers." + P2]
        self.assertEqual(out.splitlines(), want)

    def test_stream_order(self):  # L6
        self.prog(P, ("b", "a"), rows=[mkrow(P, "a"), mkrow(P, "b")])
        out, code = self.stream_lines(lambda root, cfg, prog, row, st: [("behind." + st["id"], "w")], ("b", "a"),
                                      rows=[mkrow(P, "a"), mkrow(P, "b")])
        self.assertEqual([l for l in out.splitlines() if "behind" in l], ["FAIL drift.behind.%s.a: w" % P, "FAIL drift.behind.%s.b: w" % P])

    def test_unknown_suffix_is_input(self):  # L7
        for suffix in ("base", "nodot", "", "branch", "branch.zz", "integration." + P, "host.a", "estimate.a"):
            with self.subTest(suffix=suffix):
                out, code = self.stream_lines(lambda *a: [(suffix, "x")])
                self.one_input_fail(out, "stream_errors gave suffix")
                self.assertEqual(code, 1)

    def test_stream_errors_valueerror_is_input(self):  # L8
        out, code = self.stream_lines(mock.Mock(side_effect=ValueError("row: bad")))
        self.assertEqual(out, "FAIL drift.input: ValueError: row: bad\n")

    def test_stream_errors_gateerror_is_input(self):  # L9
        out, code = self.stream_lines(mock.Mock(side_effect=GateError("repository broke")))
        self.assertEqual(out, "FAIL drift.input: repository broke\n")

    def test_reason_escaped_once(self):  # L10, V2b
        out, code = self.stream_lines(lambda *a: [("handoff.a", "block ࡰ a\\b")])
        self.assertIn("FAIL drift.handoff.%s.a: block \\u0870 a\\\\b\n" % P, out)

    def test_merged_stream_passes(self):  # L13
        self.sbranch(P, "a")
        git(self.root, "merge", "-q", "--no-ff", "-m", "merge a", P + "/a/main")
        self.prog(P, ("a",), rows=[mkrow(P, "a", status="merged")])
        self.assertEqual(self.lines(), [BASE] + ok(P))

    def test_stacked_behind_parent(self):  # L14
        self.sbranch(P, "a")
        self.sbranch(P, "b")
        self.prog(P, ("a", "b"), stacked={"b": "a"})
        out = self.lines()
        self.assertEqual([l for l in out if l.startswith("FAIL")], ["FAIL drift.behind.%s.b: behind %s/a/main; run a sync" % (P, P)])

    def test_real_failures_by_category(self):  # L1 on the real path: handoff, pending
        self.sbranch(P, "a", head="0" * 40)
        self.prog(P, ("a",), rows=[mkrow(P, "a", blockers=RID)], requests={RID: request_text(RID, "done")})
        out = self.lines()
        self.assertTrue(any(l.startswith("FAIL drift.handoff.%s.a: " % P) for l in out), out)
        self.assertIn("FAIL drift.blockers.%s.a: request %s is done, not open, accepted or disputed" % (P, RID), out)


if __name__ == "__main__":
    unittest.main()
