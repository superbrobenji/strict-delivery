"""Task 5c.2: ``gates/gate_drift.py`` through ``gate_drift.main(argv)`` on real git fixture repositories (table
task-5c.2-domain.md: the row ids A, S, B, L, H, V are in each test's comment). Expected lines are typed by hand; nothing is
read back from ``gate_drift``, ``drift`` or ``programs``. ``drift.stream_errors`` and ``drift.host_errors`` are patched only
where a row needs a failure the fixture cannot make (mapping rows L1, L4-L10, H rows); every other row runs the real path."""
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


class Arguments(Gate):
    def test_no_program_passes_one_line(self):  # A1, B4
        self.assertEqual(self.g(), ("PASS drift.none\n", 0))

    def test_in_sync_program_passes(self):  # A2, L2, L15, S2
        self.insync()
        out, code = self.g()
        self.assertEqual(out.splitlines(), [BASE] + ok(P))
        self.assertEqual(out, "\n".join([BASE] + ok(P)) + "\n")
        self.assertNotIn("FAIL", out)
        self.assertEqual(code, 0)

    def test_two_programs_sorted(self):  # A3, B1
        self.insync(P2)
        self.insync(P)
        out, code = self.g()
        self.assertEqual(out.splitlines(), [BASE] + ok(P) + ok(P2))
        self.assertEqual(out.count("drift.base"), 1)
        self.assertEqual(code, 0)

    def test_program_option_selects(self):  # A4
        self.two()
        self.assertEqual(self.lines("--program", P2), [BASE] + ok(P2))
        self.assertEqual(self.lines("--program=" + P), [BASE] + ok(P))

    def test_program_repeated(self):  # A5
        self.two()
        both = [BASE] + ok(P) + ok(P2)
        self.assertEqual(self.lines("--program", P2, "--program", P), both)
        self.assertEqual(self.lines("--program", P, "--program", P), [BASE] + ok(P))

    def test_unknown_program_input(self):  # A6
        self.insync()
        git(self.root, "branch", "20261103-z/integration", "main")   # a branch whose tip has no streams.yml
        for name in ("20261103-z", "20261104-w"):
            with self.subTest(name=name):
                out, code = self.g("--program", name)
                self.one_input_fail(out, name)
                self.assertEqual(code, 1)

    def test_program_option_malformed(self):  # A7
        self.insync()
        for name in ("", "A", "a/b", "20261301-x", P + " ", "20261101-X", "a" * 600, "é-x", "20261101-é"):
            with self.subTest(name=name[:20]):
                out, code = self.g("--program", name)
                self.one_input_fail(out, "program name: ")
                self.assertEqual(code, 1)
        out, code = self.g("--program", "-x")
        self.one_input_fail(out, "invalid arguments: argument --program: expected one argument")

    def test_program_mixed_live_and_not(self):  # A8
        self.insync()
        out, code = self.g("--program", P, "--program", "20261103-z")
        self.one_input_fail(out, "20261103-z")
        self.assertNotIn(P, out)
        self.assertEqual(code, 1)

    def test_host_flag_adds_host_lines(self):  # A9, H7, H9
        self.two()
        with mock.patch("gates.gate_drift.drift.host_errors", side_effect=AssertionError("no --host: gh must not run")) as m:
            out, code = self.g()
            self.assertEqual((out.splitlines(), code), ([BASE] + ok(P) + ok(P2), 0))
            m.assert_not_called()
        with mock.patch("gates.gate_drift.drift.host_errors", return_value=[]) as m:
            out, code = self.g("--host")
            self.assertEqual(out.splitlines(), [BASE] + ok(P) + ["PASS drift.host." + P] + ok(P2) + ["PASS drift.host." + P2])
            self.assertEqual(code, 0)
            self.assertEqual(m.call_count, 2)
        self.assertIs(inspect.signature(dlib.host_errors).parameters["runner"].default, subprocess.run)

    def test_host_flag_forms(self):  # A10
        self.insync()
        want = [BASE] + ok(P) + ["PASS drift.host." + P]
        with mock.patch("gates.gate_drift.drift.host_errors", return_value=[]):
            for argv in (["--host", "--host"], ["--hos"]):
                with self.subTest(argv=argv):
                    self.assertEqual(self.lines(*argv), want)
            out, code = self.g("--host=1")
            self.one_input_fail(out, "invalid arguments: argument --host: ignored explicit argument '1'")

    def test_json_only_as_first_argument(self):  # A11
        self.insync()
        out, _e, code = self.run_main(gate_drift.main, ["--json", "--root", self.root])
        got = json.loads(out)
        self.assertEqual(got["gate"], "drift")
        self.assertIs(got["ok"], True)
        self.assertEqual([(x["status"], x["id"]) for x in got["lines"]],
                         [("PASS", l[5:]) for l in [BASE] + ok(P)])
        out, _e, code = self.run_main(gate_drift.main, ["--root", self.root, "--json"])
        self.one_input_fail(out, "invalid arguments: unrecognized arguments: --json")
        self.assertEqual(code, 1)

    def test_root_forms(self):  # A12
        for name, path, verdict in root_forms(self.tmp, self.root):
            with self.subTest(form=name):
                out, _e, code = self.run_main(gate_drift.main, ["--root", path])
                if name == "nested":
                    self.assertEqual(out, "FAIL drift.input: .strict-delivery/config.yml: missing; run /strict-delivery:init\n")
                elif verdict == "ok":
                    self.assertEqual((out, code), ("PASS drift.none\n", 0))
                elif verdict == TOP:   # git finds the top level; the library refuses the root a step later
                    self.assertEqual((out, code), ("FAIL drift.input: %s\n" % TOP, 1))
                else:
                    self.assertEqual((out, code), ("FAIL drift.input: %s; run /strict-delivery:init\n" % verdict, 1))
        out, _e, code = self.run_main(gate_drift.main, ["--root", self.root, "--root", self.root])
        self.one_input_fail(out, "given more than once")

    def test_missing_config_input(self):  # A13
        bare = os.path.join(self.tmp, "bare")
        os.mkdir(bare)
        git(bare, "init", "-q", "-b", "main")
        out, _e, code = self.run_main(gate_drift.main, ["--root", bare])
        self.assertEqual(out, "FAIL drift.input: .strict-delivery/config.yml: missing; run /strict-delivery:init\n")
        cfg = minimal_config()
        cfg["drift"] = {"estimate_factor_pct": 0}
        write_record(self.root, ".strict-delivery/config.yml", cfg)
        out, code = self.g()
        self.one_input_fail(out, "drift.estimate_factor_pct: must be an integer of at least 1")
        cfg = minimal_config()
        cfg["base_branch"] = "a" * 41
        write_record(self.root, ".strict-delivery/config.yml", cfg)
        self.one_input_fail(self.g()[0])

    def test_argv_refusals(self):  # A14
        for argv, fragment in ((["--bogus"], "invalid arguments: unrecognized arguments: --bogus"),
                               (["report"], "invalid arguments: unrecognized arguments: report"),
                               (["-h"], "help requested; no gate was run")):
            with self.subTest(argv=argv):
                out, code = self.g(*argv)
                self.one_input_fail(out, fragment)
                self.assertEqual(code, 1)

    def test_claude_project_dir(self):  # A15
        self.insync()
        want = [BASE] + ok(P)
        with mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": self.root}):
            out, _e, code = self.run_main(gate_drift.main, [])
            self.assertEqual((out.splitlines(), code), (want, 0))
        with mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": os.path.join(self.tmp, "missing")}):
            out, _e, code = self.run_main(gate_drift.main, [])
            self.one_input_fail(out, "CLAUDE_PROJECT_DIR is not a directory")
            out, _e, code = self.run_main(gate_drift.main, ["--root", self.root])
            self.assertEqual(out.splitlines(), want)

    def test_produces_empty(self):  # A16
        self.assertEqual(gate_drift.PRODUCES, ())
        res = gate_drift.check(["--root", self.root])
        self.assertIsInstance(res, Result)
        self.assertEqual((res.gate, [(l.status, l.id) for l in res.lines]), ("drift", [("PASS", "drift.none")]))
        self.assertTrue(callable(gate_drift.main))

    def test_gate_drift_registered(self):  # A17
        if "drift" not in entry.GATES:
            self.skipTest("Rq-5-1 not on this branch")
        self.assertEqual(entry.GATES["drift"], "gates.gate_drift")
        self.insync()
        out, _e, code = self.run_main(entry.main, ["check", "drift", "--root", self.root])
        self.assertEqual((out.splitlines(), code), ([BASE] + ok(P), 0))

    def test_drift_not_in_run_all(self):  # A18
        for profile, names in run_all.PROFILE_GATES.items():
            with self.subTest(profile=profile):
                self.assertNotIn("drift", names)

    def test_shallow_clone(self):  # A19
        self.insync()
        clone = os.path.join(self.tmp, "clone")
        git(self.tmp, "clone", "-q", "--depth", "2", "--no-single-branch", "file://" + self.root, clone)
        git(clone, "branch", P + "/integration", "origin/%s/integration" % P)
        out, _e, code = self.run_main(gate_drift.main, ["--root", clone])
        self.assertEqual((out, code), ("FAIL drift.input: shallow clone; fetch the full history\n", 1))

    def test_current_branch_irrelevant(self):  # A20
        self.insync()
        want = self.g()[0]
        self.assertEqual(want.splitlines(), [BASE] + ok(P))
        for ref in ("--detach", P + "/a/main", P + "/integration"):
            with self.subTest(head=ref):
                git(self.root, "checkout", "-q", *(["--detach", "main"] if ref == "--detach" else [ref]))
                self.assertEqual(self.g()[0], want)
        git(self.root, "checkout", "-q", "main")

    def test_same_lines_from_every_worktree(self):  # A21, Q9
        self.insync()
        want = [BASE] + ok(P)
        outs = [self.g()[0]]
        for name, ref in (("int", P + "/integration"), ("str", P + "/a/main")):
            path = self.worktree(name, ref)
            outs.append(self.run_main(gate_drift.main, ["--root", path])[0])
        self.assertEqual(outs[0].splitlines(), want)
        self.assertEqual(outs[0], outs[1])
        self.assertEqual(outs[0], outs[2])

    def test_drift_with_git_index_file(self):  # A22
        self.insync()
        with mock.patch.dict(os.environ, {"GIT_INDEX_FILE": os.path.join(self.tmp, "other-index")}):
            self.assertEqual(self.lines(), [BASE] + ok(P))

    def test_main_reads_sys_argv(self):  # A23
        self.insync()
        with mock.patch.object(sys, "argv", ["drift", "--root", self.root, "--program", P]):
            out, _e, code = self.run_main(lambda a: gate_drift.main(), [])
        self.assertEqual((out.splitlines(), code), ([BASE] + ok(P), 0))


class Host(Gate):
    def run_host(self, runner, *argv):
        with mock.patch("gates.gate_drift.drift.host_errors", side_effect=host_with(runner)):
            return self.g("--host", *argv)

    def test_host_gh_missing_fails(self):  # H1
        self.insync()
        out, code = self.run_host(Runner(raises=FileNotFoundError()))
        self.assertEqual(out.splitlines(), [BASE] + ok(P) + ["FAIL drift.host.%s: gh is not installed or not on PATH" % P])
        self.assertEqual(code, 1)

    def test_host_gh_failures_fail(self):  # H2
        self.insync()
        cases = ((Runner(done("", 1, "boom\nmore")), "gh exited 1: boom"),
                 (Runner(done("", 4, "auth required")), "gh exited 4: auth required"),
                 (Runner(raises=subprocess.TimeoutExpired("gh", 30)), "gh timed out after 30 seconds"),
                 (Runner(done("not json")), "gh output is not the expected JSON list"))
        for runner, fragment in cases:
            with self.subTest(fragment=fragment):
                out, code = self.run_host(runner)
                last = out.splitlines()[-1]
                self.assertTrue(last.startswith("FAIL drift.host.%s: " % P) and fragment in last, out)
                self.assertNotIn("PASS drift.host", out)
                self.assertEqual(code, 1)

    def test_host_per_stream_line(self):  # H3
        self.insync()
        merged = json.dumps([{"number": 3, "state": "MERGED", "headRefOid": "a" * 40, "mergeCommit": {"oid": "b" * 40}}])
        out, code = self.run_host(Runner(done(merged)))
        self.assertEqual(out.splitlines()[-1], "FAIL drift.host.%s.a: a PR of %s/a/main is MERGED while the status is running" % (P, P))
        self.assertNotIn("PASS drift.host", out)
        git(self.root, "branch", "-q", "-D", P + "/integration")
        git(self.root, "merge", "-q", "--no-ff", "-m", "merge a", P + "/a/main")
        sha = self.rev("HEAD")
        self.prog(P, ("a",), rows=[mkrow(P, "a", status="merged")])
        out, code = self.run_host(Runner(done("[]")))
        self.assertEqual(out.splitlines()[-1], "FAIL drift.host.%s.a: no PR of %s/a/main is MERGED with the merge commit %s found on main"
                         % (P, P, sha))

    def test_host_unknown_suffix_is_input(self):  # H10: a suffix host_errors never gives is a named input failure
        self.insync()
        for suffix in ("branch.a", "host.zz", "host.", "hostx", ""):
            with self.subTest(suffix=suffix), mock.patch("gates.gate_drift.drift.host_errors", return_value=[(suffix, "x")]):
                self.one_input_fail(self.g("--host")[0], "host_errors gave suffix")
        with mock.patch("gates.gate_drift.drift.host_errors", return_value=[("host", "why"), ("host.a", "because")]):
            self.assertEqual(self.lines("--host")[-2:], ["FAIL drift.host.%s: why" % P, "FAIL drift.host.%s.a: because" % P])

    def test_host_pass_line(self):  # H4
        self.insync()
        runner = Runner(done("[]"))
        out, code = self.run_host(runner)
        self.assertEqual((out.splitlines(), code), ([BASE] + ok(P) + ["PASS drift.host." + P], 0))
        self.assertEqual(runner.calls[0][0][:3], ["gh", "pr", "list"])

    def test_host_two_programs(self):  # H5
        self.two()
        out, code = self.run_host(Runner(raises=FileNotFoundError()))
        self.assertEqual([l for l in out.splitlines() if "drift.host" in l],
                         ["FAIL drift.host.%s: gh is not installed or not on PATH" % p for p in (P, P2)])

    def test_host_skipped_for_invalid_page(self):  # H6 with another program judged
        self.sbranch(P, "a")
        self.prog(P, ("a",), rows=[mkrow(P, "a", status="Running")])
        self.insync(P2)
        runner = Runner(done("[]"))
        out, code = self.run_host(runner)
        self.assertNotIn("drift.host." + P + ":", out)
        self.assertNotIn("PASS drift.host." + P + "\n", out)
        self.assertIn("PASS drift.host." + P2, out)
        self.assertEqual(len(runner.calls), 1)

    def test_version_4300_digits_same_on_both(self):  # V1a, V1b
        self.insync()
        for digits in (600, 601, 4300, 4301):
            with self.subTest(digits=digits):
                prs = '[{"number": %s, "state": "OPEN", "headRefOid": "%s", "mergeCommit": null}]' % ("9" * digits, "a" * 40)
                out, code = self.run_host(Runner(done(prs)))
                last = out.splitlines()[-1]
                if digits <= 600:
                    self.assertEqual(last, "PASS drift.host." + P)
                else:
                    self.assertTrue(last.startswith("FAIL drift.host.%s: gh output is not the expected JSON list" % P), last)


class Versions(Gate):
    def test_version_exception_group_in_drift(self):  # V3a
        eg, beg = getattr(builtins, "ExceptionGroup", None), getattr(builtins, "BaseExceptionGroup", None)
        if eg is None or beg is None:
            self.skipTest("ExceptionGroup absent on 3.9")
        self.insync()
        with mock.patch("gates.gate_drift.drift.stream_errors", side_effect=eg("g", [ValueError()])):
            self.assertEqual(self.g()[0], "FAIL drift.input: ExceptionGroup: g (1 sub-exception)\n")
        with mock.patch("gates.gate_drift.drift.host_errors", side_effect=eg("g", [ValueError()])):
            self.assertEqual(self.g("--host")[0], "FAIL drift.input: ExceptionGroup: g (1 sub-exception)\n")
        for target in ("stream_errors", "host_errors"):
            with self.subTest(target=target), mock.patch("gates.gate_drift.drift." + target,
                                                         side_effect=beg("g", [KeyboardInterrupt()])):
                with self.assertRaises(beg):
                    self.g("--host")

    def test_version_modules_import_on_39(self):  # V4
        for name in ("gates/gate_drift.py", "gates/tools/drift_cli.py"):
            path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), name)
            with open(path, encoding="utf-8") as fh:
                src = fh.read()
            with self.subTest(file=name):
                ast.parse(src, filename=name, feature_version=(3, 9))
                for word in (".lower(", "casefold", "isprintable", "isalnum", "unicodedata", "IGNORECASE", "removeprefix",
                             "except*", "match "):
                    self.assertNotIn(word, src)


if __name__ == "__main__":
    unittest.main()
