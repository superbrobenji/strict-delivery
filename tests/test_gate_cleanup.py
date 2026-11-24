"""Tests of gates/gate_cleanup.py (Task P3.3; rows AV, MG, PM, GN, OW, OP, LD, OUT, RG, EN, V of the P3.3 input-domain table;
binding decisions D-Q1 to D-Q8 of its end, and the P3.2 decisions it inherits). Every run goes through the production path:
``gates.__main__.main(["check", "cleanup", ...])`` in process and ``sys.executable -m gates check cleanup ...`` in a
subprocess. Every repository is a ``make_repo`` fixture with its own ``main``, ``merge.mode: controller`` and a git config
that sets ``color.ui=always``, ``color.diff=always`` and ``core.abbrev=7`` (tests/test_cleanup_lib.py ``Cx``, whose
scenario builder this module reuses). Expected values are written by hand; shas come from the fixture's own git."""
import ast
import builtins
import contextlib
import importlib
import inspect
import io
import json
import os
import subprocess
import sys
import unittest
from unittest import mock

from gates import __main__ as gates_main
from gates import gate_cleanup, producers, run_all
from gates.lib import checkpoints, config, gitinfo
from gates.lib.yamlsub import emit
from tests.helpers import (INT_LIMITS, E128, TOP, GitIsolatedTestCase, commit_all, git, int_limit, make_repo,
                           minimal_config, root_forms, write_record)
from tests.test_cleanup_lib import (CL, FD, LEDGER, LEDGER_HEAD, NAME, PG, PROGRAMS, PS, REV, SPECS, Cx, mline)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEC = ".strict-delivery/state/decisions"
PLAYBOOK = ".strict-delivery/playbooks/x.md"
SPEC = SPECS + "/s.md"
CLAIM = CL + "/docs--strict-delivery--specs--s.yml"
FIDP = FD + "/F-20261031-k3f9.yml"
OPENF = "F-20261031-r8s9"
D3 = "DEC-20261031-p6q7"
GROUPS = ("merge", "gone", "owner", "open", "landed")
CLEAN = "".join("PASS cleanup.%s\n" % g for g in GROUPS)
NOPLAN = "FAIL cleanup.merge: plan p has no final merge on the base branch\n"
STILL = ": still tracked; remove it with git rm\n"
# the seven per-effort paths of plan p written by hand (P3.2 PE1): plan, handoff, ledger, review, spec, claim, closed finding
PSET = sorted([PG + "/p.md", PS + "/p/handoff.md", LEDGER, REV + "/p/r.md", SPEC, CLAIM, FIDP])


def did(c):
    return "DEC-20261101-" + c * 4


def fid(c):
    return "F-20261101-" + c * 4


class Gx(Cx):
    def setUp(self):
        super().setUp()
        git(self.root, "config", "diff.noprefix", "true")

    def run_in_process(self, argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = gates_main.main(["check", "cleanup"] + list(argv))
        return code, out.getvalue()

    def g(self, *argv, root=True):
        return self.run_in_process(list(argv) + (["--root", self.root] if root else []))

    def sub(self, argv, cwd=None):
        env = dict(os.environ, PYTHONPATH=REPO)
        p = subprocess.run([sys.executable, "-m", "gates", "check", "cleanup"] + list(argv), cwd=cwd or self.root,
                           env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return p.returncode, p.stdout.decode("utf-8")

    def scen(self, owned=False, **kw):
        extra = dict(kw.pop("extra", {}))
        if not owned:
            extra[FD + "/" + OPENF + ".yml"] = emit({"schema": "finding/1", "id": OPENF, "status": "open",
                                                     "owner": {"kind": "issue"}})
        return self.scenario(extra=extra, **kw)

    def cleanup_branch(self, s, keep=(), name=None):
        git(self.root, "checkout", "-q", "-b", "cleanup/" + (name or s["plan"]), "main")
        rm = [p for p in sorted(s["set"]) if p not in keep]
        if rm:
            git(self.root, "rm", "-q", "--", *rm)
        return commit_all(self.root, "cleanup")

    def finding(self, i, status="open", owner=None, **extra):
        row = {"schema": "finding/1", "id": i, "status": status}
        if owner is not None:
            row["owner"] = owner
        row.update(extra)
        self.put("%s/%s.yml" % (FD, i), emit(row))

    def decision(self, i, status="open", effect=None, cls="scope", **extra):
        row = {"schema": "decision/1", "id": i, "status": status, "class": cls}
        if effect is not None:
            row["effect"] = effect
        row.update(extra)
        self.put("%s/%s.yml" % (DEC, i), emit(row))

    def both(self, argv):
        """The in-process and the subprocess answer (equal), as ``(code, out)``."""
        a = self.run_in_process(argv)
        self.assertEqual(self.sub(argv), a)
        return a


class ArgvTests(Gx):
    def test_cleanup_produces_literal(self):  # AV1, RG6
        self.assertEqual(gate_cleanup.PRODUCES, ())
        self.assertEqual(producers.PRODUCER_MODULES, ("gates.tools.index", "gates.tools.decisions_cli",
                                                      "gates.tools.findings_cli", "gates.tools.claims_cli",
                                                      "gates.gate_checkpoint", "gates.tools.program_cli", "gates.gate_context"))

    def test_cleanup_main_shape(self):  # AV2
        self.assertIsNone(inspect.signature(gate_cleanup.main).parameters["argv"].default)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = gate_cleanup.main(["--plan", "p", "--root", self.root])
        self.assertEqual((code, out.getvalue()), (1, NOPLAN))
        self.assertEqual(gate_cleanup.check(["--plan", "p", "--root", self.root]).gate, "cleanup")

    def test_neither_plan_nor_program(self):  # AV3
        for argv in ([], ["--root", self.root]):
            code, out = self.g(*argv, root=False)
            self.assertEqual(code, 1)
            self.assertTrue(out.startswith("FAIL cleanup.input: exactly one of --plan SLUG or --program NAME"), out)

    def test_both_plan_and_program(self):  # AV4
        for argv in (["--plan", "fx", "--program", "20261101-x"], ["--plan", "fx", "--program", "20261101-x",
                                                                    "--decision", D3]):
            code, out = self.g(*argv)
            self.assertEqual((code, out.split(":")[0]), (1, "FAIL cleanup.input"), out)

    def test_unknown_plan_fails_merge_line(self):  # AV5
        self.assertEqual(self.g("--plan", "nosuch"), (1, "FAIL cleanup.merge: plan nosuch has no final merge on the base branch\n"))

    def test_program_close_needs_decision(self):  # AV6, plan test
        code, out = self.g("--program", NAME)
        self.assertTrue(out.startswith("FAIL cleanup.input:"), out)
        self.assertEqual(code, 1)

    def test_decision_refused_with_plan(self):  # AV7
        code, out = self.g("--plan", "fx", "--decision", D3)
        self.assertTrue(out.startswith("FAIL cleanup.input: --decision is refused with --plan"), out)

    def test_plan_slug_forms(self):  # AV8
        for good in ("fx", "0", "a-b"):
            with self.subTest(good=good):
                self.assertEqual(self.g("--plan", good), (1, "FAIL cleanup.merge: plan %s has no final merge on the base branch\n" % good))
        for bad in ("", "A", "a_b", "a b", "a/b", "..", "a\n", "café", "ࡰ", "Cleanup/fx"):
            with self.subTest(bad=bad):
                code, out = self.g("--plan", bad)
                self.assertEqual((code, out), (1, "FAIL cleanup.input: --plan must match [a-z0-9][a-z0-9-]*\n"))
        self.assertEqual(self.g("--plan=-x")[1], "FAIL cleanup.input: --plan must match [a-z0-9][a-z0-9-]*\n")
        code, out = self.g("--plan", "-x")
        self.assertTrue(out.startswith("FAIL cleanup.input:"), out)
        for n in (255, 256, 4301):  # never a traceback; the file system decides between a missing ledger and a read failure
            code, out = self.g("--plan", "a" * n)
            self.assertEqual(code, 1)
            self.assertIn(out.split(":")[0], ("FAIL cleanup.merge", "FAIL cleanup.input"), n)

    def test_program_name_as_plan_is_a_plan_slug(self):  # AV9
        self.assertEqual(self.g("--plan", NAME),
                         (1, "FAIL cleanup.merge: plan %s has no final merge on the base branch\n" % NAME))

    def test_program_name_forms(self):  # AV10
        code, out = self.g("--program", NAME, "--decision", D3)  # well formed: it goes on to the decision
        self.assertEqual((code, out), (1, "FAIL cleanup.merge: decision %s has no record\n" % D3))
        for bad in ("x", "20261301-x", "20261101-", "20261101-X", "20261101-a/b", "", "ࡰ", "9" * 4301):
            with self.subTest(bad=bad):
                code, out = self.g("--program", bad, "--decision", D3)
                self.assertEqual(code, 1)
                self.assertTrue(out.startswith("FAIL cleanup.input: --program: "), out)

    def test_decision_id_forms(self):  # AV11
        for bad in ("F-20261031-k3f9", "DEC-20261301-k3f9", "DEC-20261031-K3F9", "", "DEC-20261031-k3f9\n", "D1",
                    "DEC-20261031-k3f9\x00", "9" * 4301):
            with self.subTest(bad=bad):
                code, out = self.g("--program", NAME, "--decision", bad)
                self.assertEqual(code, 1)
                self.assertTrue(out.startswith("FAIL cleanup.input: --decision: "), out)
        code, out = self.g("--program", NAME, "--decision", "-x")
        self.assertTrue(out.startswith("FAIL cleanup.input:"), out)
        self.assertEqual(self.g("--program", NAME, "--decision", "DEC-20261031-zzzz")[1],
                         "FAIL cleanup.merge: decision DEC-20261031-zzzz has no record\n")

    def test_git_missing_has_no_init_hint(self):  # AV14: no repository hint can help when git itself is not found
        from gates.lib.result import GitNotFound
        with mock.patch.object(gitinfo, "toplevel", side_effect=GitNotFound("git is not on PATH")):
            self.assertEqual(self.g("--plan", "p"), (1, "FAIL cleanup.input: git is not on PATH\n"))
        with mock.patch.object(gitinfo, "toplevel", side_effect=gitinfo.GateError("not a git repository")):
            self.assertEqual(self.g("--plan", "p"), (1, "FAIL cleanup.input: not a git repository; run /strict-delivery:init\n"))

    def test_decision_id_uses_cfg_prefix(self):  # AV11 with ids.decision set: the configured prefix is the rule, not DEC
        write_record(self.root, ".strict-delivery/config.yml", dict(minimal_config(), merge={"mode": "controller"},
                                                                    ids={"decision": "ZZ"}))
        self.assertEqual(self.g("--program", NAME, "--decision", "ZZ-20261031-zzzz")[1],
                         "FAIL cleanup.merge: decision ZZ-20261031-zzzz has no record\n")
        self.assertTrue(self.g("--program", NAME, "--decision", "DEC-20261031-zzzz")[1].startswith("FAIL cleanup.input: --decision: "))

    def test_repeated_and_unknown_flags(self):  # AV12
        for argv in (["--root", self.root, "--root", self.root, "--plan", "a"], ["--plan", "a", "--plan", "b"],
                     ["--bogus"], ["-h"], ["--help"], ["--plan", "a", "--bogus"],
                     ["--program", "20261101-x", "--program", "20261101-y", "--decision", "DEC-20261031-k3f9"],
                     ["--program", "20261101-x", "--decision", "DEC-20261031-k3f9", "--decision", "DEC-20261031-m4n5"],
                     ["--p", "a"],    # AV12 (amended 2026-11-22): --p matches --plan and --program: ambiguous, refused
                     ["--x", "a"]):   # AV12: not a prefix of any flag
            with self.subTest(argv=argv):
                code, out = self.run_in_process(argv if "--root" in argv else argv + ["--root", self.root])
                self.assertEqual(code, 1)
                self.assertTrue(out.startswith("FAIL cleanup.input:"), out)
        for accepted in (["--plan=a"], ["--pl", "a"]):  # an abbreviation is the shared parser's own behaviour (E8)
            self.assertEqual(self.g(*accepted), (1, "FAIL cleanup.merge: plan a has no final merge on the base branch\n"))

    def test_ambiguous_abbreviation_refused(self):  # AV12 (amended): --p is a prefix of --plan and --program
        for argv in (["--p", "a"], ["--p=a"]):
            with self.subTest(argv=argv):
                code, out = self.g(*argv)
                self.assertEqual(code, 1)
                self.assertTrue(out.startswith("FAIL cleanup.input:"), out)
                self.assertEqual(out.count("\n"), 1, out)
        self.assertEqual(self.g("--pla", "a"), self.g("--plan", "a"))   # a unique prefix is --plan

    def test_json_flag_position(self):  # AV13, OUT9
        code, out = self.g("--json", "--plan", "p")
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(out), {"gate": "cleanup", "ok": False, "lines": [
            {"status": "FAIL", "id": "cleanup.merge", "reason": "plan p has no final merge on the base branch"}]})
        code, out = self.g("--plan", "p", "--json")
        self.assertTrue(out.startswith("FAIL cleanup.input:") and "unrecognized arguments: --json" in out, out)

    def test_root_forms(self):  # AV14
        for name, path, verdict in root_forms(self.tmp, self.root):
            with self.subTest(form=name):
                code, out = self.run_in_process(["--plan", "p", "--root", path])
                self.assertEqual(code, 1)
                if verdict == "ok":
                    self.assertNotIn(TOP, out)
                    self.assertNotIn(E128, out)
                elif verdict == TOP:  # git finds the top level; the library refuses the root a step later
                    self.assertEqual(out, "FAIL cleanup.input: %s\n" % TOP)
                else:
                    self.assertEqual(out, "FAIL cleanup.input: %s; run /strict-delivery:init\n" % verdict)
        self.assertTrue(self.run_in_process(["--plan", "p", "--root", ""])[1].startswith("FAIL cleanup.input:"))

    def test_claude_project_dir(self):  # OUT7, AV14 (absent --root)
        with mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": self.root}):
            self.assertEqual(self.run_in_process(["--plan", "p"]), (1, NOPLAN))
        with mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": os.path.join(self.root, ".strict-delivery", "config.yml")}):
            code, out = self.run_in_process(["--plan", "p"])
            self.assertEqual(code, 1)
            self.assertTrue(out.startswith("FAIL cleanup.input:"), out)

    def test_argv_checked_before_io(self):  # AV15
        calls = []
        real = gitinfo._run
        with mock.patch.object(gitinfo, "_run", side_effect=lambda *a, **k: calls.append(a) or real(*a, **k)), \
                mock.patch("os.lstat", side_effect=lambda *a, **k: calls.append(a) or (_ for _ in ()).throw(OSError("spy"))):
            for argv in ([], ["--plan", "a", "--program", NAME], ["--plan", "A"], ["--program", "x", "--decision", D3],
                         ["--program", NAME], ["--plan", "a", "--decision", D3]):
                code, out = self.run_in_process(argv + ["--root", self.root])
                self.assertEqual(code, 1, argv)
                self.assertTrue(out.startswith("FAIL cleanup.input:"), out)
        self.assertEqual(calls, [])

    def test_cleanup_config_errors(self):  # AV16
        cfg = minimal_config()
        for name, row in (("schema", dict(cfg, schema="config/9")), ("mode", dict(cfg, merge={"mode": "x"}))):
            with self.subTest(case=name):
                write_record(self.root, ".strict-delivery/config.yml", row)
                code, out = self.g("--plan", "p")
                self.assertEqual(code, 1)
                self.assertTrue(out.startswith("FAIL cleanup.input:"), out)
        os.unlink(os.path.join(self.root, ".strict-delivery", "config.yml"))
        self.assertTrue(self.g("--plan", "p")[1].startswith("FAIL cleanup.input:"))

    def test_cleanup_cli_matches_in_process(self):  # AV17, OUT8
        s = self.scen()
        self.cleanup_branch(s)
        for argv in (["--plan", "p"], ["--plan", "nosuch"], [], ["--plan", "A"], ["--program", NAME],
                     ["--plan", "p", "--decision", D3], ["--bogus"]):
            with self.subTest(argv=argv):
                self.both(argv + ["--root", self.root])
        self.assertEqual(self.both(["--plan", "p", "--root", self.root]), (0, CLEAN))


class MergeTests(Gx):
    def test_clean_after_final_merge_passes(self):  # MG1, GN1, OUT2, plan test
        s = self.scen()
        self.cleanup_branch(s)
        code, out = self.g("--plan", "p")
        for c in GROUPS:
            self.assertIn("PASS cleanup." + c, out)
        self.assertEqual((code, out), (0, CLEAN))
        self.assertFalse(os.path.exists(os.path.join(self.root, LEDGER)))  # MG5: read from before its deletion

    def test_no_final_merge_stops_after_merge_line(self):  # MG2, plan test
        self.scenario(final=False)  # a ledger of the header only
        for case, text in (("empty", None), ("checkpoint only", "CHECKPOINT at=2026-11-02T06:00:00Z head=%s" % self.A)):
            with self.subTest(case=case):
                if text:
                    self.set_ledger(text)
                code, out = self.g("--plan", "p")
                self.assertEqual((code, out), (1, NOPLAN))
                self.assertIn("FAIL cleanup.merge", out)
                self.assertNotIn("cleanup.gone", out)
        self.assertEqual(self.g("--plan", "never-existed")[1].count("\n"), 1)
        os.unlink(os.path.join(self.root, LEDGER))
        self.assertEqual(self.g("--plan", "p"), (1, NOPLAN))  # a plan with a handoff, no ledger

    def test_only_nonfinal_lines_fail(self):  # MG3
        s = self.scenario(final=False)
        self.set_ledger(mline(s["head"], s["merge"], final="no", pr=1), mline(s["head"], s["merge"], final="no", pr=2))
        self.assertEqual(self.g("--plan", "p"), (1, NOPLAN))

    def test_final_line_failing_merged_errors(self):  # MG4, MG12
        s = self.scenario(final=False)
        t = self.scenario(plan="q", tag="t", fid="F-20261031-n5n5", final=False)
        self.pr("sq", {PS + "/p/sq.md": "x\n"}, how="squash")
        squash = git(self.root, "rev-parse", "HEAD")
        cases = {"merge is not a merge commit": mline(s["head"], self.A), "head is not the second parent": mline(self.A, s["merge"]),
                 "host line under controller": mline(s["head"], s["merge"], approval="host"),
                 "squash merge": mline(squash, squash), "merge of another plan": mline(t["head"], t["merge"])}
        for name, line in cases.items():
            with self.subTest(case=name):
                self.set_ledger(line)
                code, out = self.g("--plan", "p")
                self.assertEqual((code, out), (1, NOPLAN))
                self.assertEqual(out.count("\n"), 1)

    def test_first_passing_final_line_is_at(self):  # MG11
        s = self.scenario(final=False)
        bad = mline(self.A, self.A, pr=1)
        good = mline(s["head"], s["merge"], pr=2)
        for lines in ((bad, good), (good, bad)):
            with self.subTest(lines=lines):
                self.set_ledger(*lines)
                self.assertEqual(self.g("--plan", "p")[1].splitlines()[0], "PASS cleanup.merge")

    def test_ledger_working_tree_precedence_through_gate(self):  # MG9
        s = self.scenario(final=False)
        path = os.path.join(self.root, *LEDGER.split("/"))
        self.put(LEDGER, LEDGER_HEAD + mline(s["head"], s["merge"]) + "\n")  # uncommitted real line: read
        self.assertEqual(self.g("--plan", "p")[1].splitlines()[0], "PASS cleanup.merge")
        self.put(LEDGER, LEDGER_HEAD + mline(s["head"], "e" * 40) + "\n")  # an invented merge sha: refused by git
        self.assertEqual(self.g("--plan", "p"), (1, NOPLAN))
        git(self.root, "checkout", "-q", "--", LEDGER)
        self.set_ledger(mline(s["head"], s["merge"]))
        os.unlink(path)  # deleted in the tree, present at HEAD: HEAD's text
        self.assertEqual(self.g("--plan", "p")[1].splitlines()[0], "PASS cleanup.merge")

    def test_merge_line_read_after_ledger_deleted(self):  # MG5
        s = self.scen()
        self.cleanup_branch(s)  # the second commit removes the ledger
        self.assertNotIn(LEDGER, git(self.root, "ls-files").split("\n"))
        self.assertFalse(os.path.exists(os.path.join(self.root, *LEDGER.split("/"))))
        first_parent = git(self.root, "rev-list", "--first-parent", "main").split("\n")  # oracle: the merge is on main
        self.assertIn(s["merge"], first_parent)
        self.assertIn("MERGED", git(self.root, "show", "main:" + LEDGER))  # the text before its deletion holds the line
        self.assertEqual(self.g("--plan", "p"), (0, CLEAN))
        self.assertEqual(self.both(["--plan", "p", "--root", self.root]), (0, CLEAN))

    def test_plan_step1_tests_exist(self):  # OUT12: the plan's Step 1 test names (plan 3045-3062), written by hand
        names = {"test_clean_after_final_merge_passes": MergeTests, "test_left_ledger_fails": GoneTests,
                 "test_no_final_merge_stops_after_merge_line": MergeTests,
                 "test_open_finding_still_owned_by_plan_fails": OwnerTests,
                 "test_cited_open_decision_fails": DecisionTests, "test_lasting_decision_unlanded_fails": DecisionTests,
                 "test_program_close_needs_decision": ArgvTests}
        for name, cls in names.items():
            with self.subTest(test=name):
                self.assertTrue(callable(getattr(cls, name, None)), "%s is not a method of %s" % (name, cls.__name__))
        sa = importlib.import_module("tests.test_self_adoption")  # the eighth: its plan assertion is in its body
        found = [c for c in vars(sa).values() if inspect.isclass(c) and hasattr(c, "test_workflow_runs_cleanup_for_cleanup_heads")]
        self.assertEqual(len(found), 1)
        self.assertIn('"gates check cleanup --plan"', inspect.getsource(found[0].test_workflow_runs_cleanup_for_cleanup_heads))

    def test_ledger_file_kinds(self):  # MG10
        s = self.scenario()
        path = os.path.join(self.root, *LEDGER.split("/"))
        text = open(path, encoding="utf-8").read()
        os.unlink(path)
        os.symlink("elsewhere", path)
        for kind in ("symlink", "directory", "fifo", "invalid utf-8"):
            with self.subTest(kind=kind):
                if kind != "symlink":
                    if os.path.islink(path):
                        os.unlink(path)
                    elif os.path.isdir(path):
                        os.rmdir(path)
                    elif os.path.exists(path):
                        os.unlink(path)
                    if kind == "directory":
                        os.mkdir(path)
                    elif kind == "fifo":
                        os.mkfifo(path)
                    else:
                        with open(path, "wb") as fh:
                            fh.write(b"\xff\xfe")
                code, out = self.g("--plan", "p")
                self.assertEqual(code, 1)
                self.assertTrue(out.startswith("FAIL cleanup.input: " + LEDGER), out)
        os.unlink(path)
        with open(path, "wb") as fh:  # CRLF: the final line carries a CR, fails the pattern and is skipped
            fh.write(text.replace("\n", "\r\n").encode("utf-8"))
        self.assertEqual(self.g("--plan", "p"), (1, NOPLAN))
        self.assertIn(s["merge"], text)

    def test_merge_fail_reason_names_plan(self):  # MG12
        out = self.g("--plan", "some-plan")[1]
        self.assertTrue(out.startswith("FAIL cleanup.merge:") and "some-plan" in out, out)

    def test_digit_limits(self):  # MG13, V1
        s = self.scenario(final=False)
        base = mline(s["head"], s["merge"])
        for setting in INT_LIMITS:
            for n in (600, 601, 4300, 4301):
                with self.subTest(setting=setting, digits=n), int_limit(setting):
                    self.set_ledger(base.replace("pr=12", "pr=" + "9" * n))
                    code, out = self.g("--plan", "p")
                    if n == 600:  # the ledger pattern admits 600 digits; the line then passes its checks
                        self.assertEqual(out.splitlines()[0], "PASS cleanup.merge")
                    else:  # skipped by the pattern before any int()
                        self.assertEqual((code, out), (1, NOPLAN))
        with open(os.path.join(REPO, "gates", "gate_cleanup.py"), encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        self.assertEqual([n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                          and n.func.id == "int"], [])

    def test_base_branch_forms(self):  # MG14, MG6
        s = self.scen()
        self.cleanup_branch(s)
        cfg = dict(minimal_config(), merge={"mode": "controller"}, base_branch="trunk")
        write_record(self.root, ".strict-delivery/config.yml", cfg)
        self.assertEqual(self.g("--plan", "p"), (1, NOPLAN))  # trunk is missing: fail closed
        git(self.root, "branch", "trunk", "main")
        self.assertEqual(self.g("--plan", "p")[1].splitlines()[0], "PASS cleanup.merge")
        git(self.root, "tag", "tagbase", "main")
        write_record(self.root, ".strict-delivery/config.yml", dict(cfg, base_branch="tagbase"))
        self.assertEqual(self.g("--plan", "p"), (1, NOPLAN))  # a tag is not a local branch

    def test_merge_line_needs_local_base_branch(self):  # MG6
        s = self.scen()
        self.cleanup_branch(s)
        tip = git(self.root, "rev-parse", "main")
        git(self.root, "branch", "-q", "-D", "main")
        self.assertEqual(self.g("--plan", "p"), (1, NOPLAN))
        git(self.root, "branch", "main", tip)
        self.assertEqual(self.g("--plan", "p"), (0, CLEAN))

    def test_shallow_clone_refused(self):  # MG7
        s = self.scen()
        self.cleanup_branch(s)
        dst = os.path.join(self.tmp, "shallow")
        git(self.tmp, "clone", "-q", "--depth", "1", "file://" + self.root, dst)
        self.assertEqual(self.run_in_process(["--plan", "p", "--root", dst]),
                         (1, "FAIL cleanup.input: shallow clone; fetch the full history\n"))

    def test_head_states(self):  # MG8, OUT11
        s = self.scen()
        head = self.cleanup_branch(s)
        git(self.root, "checkout", "-q", "--detach", head)
        self.assertEqual(self.g("--plan", "p"), (0, CLEAN))  # detached
        self.put("untracked.txt")  # a dirty tree is not judged
        self.assertEqual(self.g("--plan", "p"), (0, CLEAN))
        unborn = os.path.join(self.tmp, "unborn")
        os.mkdir(unborn)
        git(unborn, "init", "-q", "-b", "main")
        write_record(unborn, ".strict-delivery/config.yml", minimal_config())
        code, out = self.run_in_process(["--plan", "p", "--root", unborn])
        self.assertEqual(code, 1)
        self.assertTrue(out.startswith("FAIL cleanup.input:"), out)
        wt = os.path.join(self.tmp, "wt")  # a linked worktree gives the same verdict
        git(self.root, "worktree", "add", "-q", "--detach", wt, head)
        self.assertEqual(self.run_in_process(["--plan", "p", "--root", wt]), (0, CLEAN))
        self.assertEqual(self.g("--plan", "p"), (0, CLEAN))

    def test_cleanup_git_states(self):  # OUT11: paths with a space, a newline, a tab (GN8) and the states above
        self.test_head_states()


class GoneTests(Gx):
    def test_left_ledger_fails(self):  # GN2, plan test
        s = self.scen()
        self.cleanup_branch(s, keep=(LEDGER,))
        code, out = self.g("--plan", "p")
        self.assertIn("FAIL cleanup.gone." + LEDGER, out)
        self.assertEqual((code, out), (1, "PASS cleanup.merge\nFAIL cleanup.gone." + LEDGER + STILL +
                                       "PASS cleanup.owner\nPASS cleanup.open\nPASS cleanup.landed\n"))

    def test_left_files_fail_by_kind(self):  # GN3, GN11, OUT3
        s = self.scen(extra={PS + "/p/sub/deep.md": "x\n"})
        self.cleanup_branch(s, keep=PSET + [PS + "/p/sub/deep.md"])
        code, out = self.g("--plan", "p")
        want = sorted(PSET + [PS + "/p/sub/deep.md"])
        self.assertEqual((code, out), (1, "PASS cleanup.merge\n" + "".join("FAIL cleanup.gone." + p + STILL for p in want)
                                       + "PASS cleanup.owner\nPASS cleanup.open\nPASS cleanup.landed\n"))

    def test_shared_spec_kept_passes(self):  # GN4
        s = self.scen()
        self.scen(plan="q", tag="t", fid="F-20261031-n5n5", final=False, spec_also=[SPEC])
        self.cleanup_branch(s, keep=(SPEC, CLAIM))
        self.assertEqual(self.g("--plan", "p"), (0, CLEAN))
        git(self.root, "checkout", "-q", "main")
        git(self.root, "branch", "-q", "-D", "cleanup/p")
        self.cleanup_branch(s, keep=(CLAIM,))  # the spec is judged only when it is in the set: it is not
        self.assertEqual(self.g("--plan", "p"), (0, CLEAN))

    def test_files_added_after_final_merge(self):  # GN5
        s = self.scen()
        self.put(PS + "/p/late.md")
        commit_all(self.root, "late")
        self.cleanup_branch(s)
        self.assertTrue(os.path.exists(os.path.join(self.root, PS, "p", "late.md")))
        self.assertEqual(self.g("--plan", "p"), (0, CLEAN))  # the stated limit: the set is read at the final merge
        git(self.root, "checkout", "main", "--", LEDGER)  # a path of the set re-added is judged
        commit_all(self.root, "readd")
        self.assertEqual(self.g("--plan", "p")[1].splitlines()[1], "FAIL cleanup.gone." + LEDGER + STILL.strip("\n"))

    def test_gone_means_not_in_the_index(self):  # GN6
        s = self.scen()
        rm = sorted(s["set"])
        git(self.root, "checkout", "-q", "-b", "cleanup/p", "main")
        git(self.root, "rm", "-q", "--cached", "--", *rm)  # the files stay on disk
        self.assertTrue(os.path.exists(os.path.join(self.root, *PSET[0].split("/"))))
        self.assertEqual([p for p in rm if p in git(self.root, "ls-files").split("\n")], [])
        self.assertEqual(self.g("--plan", "p"), (0, CLEAN))
        git(self.root, "checkout", "-q", "-f", "-B", "v2", "main")
        git(self.root, "rm", "-q", "--", *rm)  # staged, not committed
        self.assertEqual(self.g("--plan", "p"), (0, CLEAN))
        git(self.root, "checkout", "-q", "-f", "-B", "v3", "main")
        git(self.root, "rm", "-q", "--", *[p for p in rm if p != SPEC])
        os.unlink(os.path.join(self.root, *SPEC.split("/")))  # removed from disk, still in the index
        self.assertEqual(git(self.root, "ls-files", "--", SPEC), SPEC)
        self.assertEqual(self.g("--plan", "p")[1].splitlines()[1], "FAIL cleanup.gone." + SPEC + STILL.strip("\n"))

    def test_symlink_at_set_path_reads_as_gone(self):  # GN7 (pins today: unrelated finding U2)
        s = self.scen()
        self.cleanup_branch(s, keep=(SPEC,))
        git(self.root, "rm", "-q", "--", SPEC)
        os.makedirs(os.path.join(self.root, *SPEC.split("/")[:-1]), exist_ok=True)
        os.symlink("elsewhere", os.path.join(self.root, *SPEC.split("/")))
        commit_all(self.root, "symlink")
        self.assertIn("120000", git(self.root, "ls-files", "--stage", "--", SPEC))
        self.assertEqual(self.g("--plan", "p"), (0, CLEAN))

    def test_gone_lines_escape_paths(self):  # GN8, V2
        names = ["café x.md", "sub/new\nline.md", "tab\there.md", 'q"uote.md', "aࡰb.md", "u2c2fⰯ.md",
                 "\U0001fae8.md"]
        s = self.scen(extra={PS + "/p/" + n: "x\n" for n in names})
        self.cleanup_branch(s, keep=[PS + "/p/" + n for n in names])
        code, out = self.g("--plan", "p")
        want = {"FAIL cleanup.gone." + PS + "/p/café x.md" + STILL,
                "FAIL cleanup.gone." + PS + "/p/sub/new\\nline.md" + STILL,
                "FAIL cleanup.gone." + PS + "/p/tab\\there.md" + STILL,
                'FAIL cleanup.gone.' + PS + '/p/q"uote.md' + STILL,
                "FAIL cleanup.gone." + PS + "/p/a\\u0870b.md" + STILL,
                "FAIL cleanup.gone." + PS + "/p/u2c2f\\u2c2f.md" + STILL,
                "FAIL cleanup.gone." + PS + "/p/\\U0001fae8.md" + STILL}
        got = set(l + "\n" for l in out.splitlines() if l.startswith("FAIL"))
        self.assertTrue(want <= got, sorted(want - got))
        self.assertEqual(len(out.splitlines()), 4 + len(names))
        self.assertEqual(code, 1)

    def test_cleanup_unicode_same_on_both(self):  # V2: no Unicode property or case method in the gate module
        with open(os.path.join(REPO, "gates", "gate_cleanup.py"), encoding="utf-8") as fh:
            text = fh.read()
        for word in (".lower(", ".upper(", "isalpha", "isprintable", "unicodedata", "casefold", "isalnum", ".isdigit("):
            self.assertNotIn(word, text)

    def test_gone_many_paths(self):  # GN9
        files = {"%s/p/m/f%03d.md" % (PS, i): "x\n" for i in range(300)}
        s = self.scen(extra=files)
        self.cleanup_branch(s, keep=list(files) + sorted(s["set"]))
        code, out = self.g("--plan", "p")
        lines = [l for l in out.splitlines() if l.startswith("FAIL cleanup.gone.")]
        self.assertEqual(lines, ["FAIL cleanup.gone." + p + STILL.strip("\n") for p in sorted(set(files) | set(PSET))])
        self.assertNotIn("PASS cleanup.gone", out)

    def test_plan_effort_errors_are_input_failures(self):  # GN10
        self.scen(spec_also=[SPECS + "/missing.md"])
        code, out = self.g("--plan", "p")
        self.assertEqual(code, 1)
        self.assertTrue(out.startswith("FAIL cleanup.input:") and "missing.md" in out, out)
        git(self.root, "checkout", "-q", "-b", "t-q", "main")  # a symlink in the plan's folder at the merge
        self.put(PS + "/q/handoff.md", "---\n" + emit({"schema": "handoff/1", "plan": "q", "spec": [SPEC]}) + "---\n")
        os.symlink("elsewhere", os.path.join(self.root, PS, "q", "link"))
        head = commit_all(self.root, "q")
        git(self.root, "checkout", "-q", "main")
        git(self.root, "merge", "-q", "--no-ff", "-m", "merge q", "t-q")
        self.set_ledger(mline(head, git(self.root, "rev-parse", "HEAD"), pr=3), plan="q")
        code, out = self.g("--plan", "q")
        self.assertEqual(code, 1)
        self.assertTrue(out.startswith("FAIL cleanup.input:") and "symlink" in out, out)

    def test_gone_minimal_plan(self):  # GN12
        git(self.root, "checkout", "-q", "-b", "t-m", "main")
        self.put(PG + "/m.md", "plan\n")
        self.put(PS + "/m/ledger.md", LEDGER_HEAD)
        head = commit_all(self.root, "m")
        git(self.root, "checkout", "-q", "main")
        git(self.root, "merge", "-q", "--no-ff", "-m", "merge m", "t-m")
        self.set_ledger(mline(head, git(self.root, "rev-parse", "HEAD")), plan="m")
        git(self.root, "checkout", "-q", "-b", "cleanup/m", "main")
        git(self.root, "rm", "-q", "--", PG + "/m.md", PS + "/m/ledger.md")
        commit_all(self.root, "cleanup")
        self.assertEqual(self.g("--plan", "m"), (0, CLEAN))


class OwnerTests(Gx):
    def clean(self, **kw):
        s = self.scen(**kw)
        self.cleanup_branch(s)
        return s

    def test_open_finding_still_owned_by_plan_fails(self):  # OW1, plan test
        s = self.scen(owned=True)
        self.cleanup_branch(s)
        code, out = self.g("--plan", "p")
        self.assertIn("FAIL cleanup.owner." + OPENF, out)
        self.assertEqual((code, out), (1, "PASS cleanup.merge\nPASS cleanup.gone\nFAIL cleanup.owner." + OPENF +
                                       ": finding " + OPENF + " of plan p is open; pass it to an issue or roadmap item\n"
                                       "PASS cleanup.open\nPASS cleanup.landed\n"))

    def test_finding_moved_to_issue_passes(self):  # OW2, OW10
        self.clean()
        self.assertEqual(self.g("--plan", "p"), (0, CLEAN))
        git(self.root, "rm", "-q", "--", FD + "/" + OPENF + ".yml")  # no matching finding at all
        self.assertEqual(self.g("--plan", "p"), (0, CLEAN))

    def test_owner_rule_matrix(self):  # OW3-OW7, OW9 (every row is an uncommitted working-tree file)
        self.clean()
        own = {"kind": "plan", "plan": "p", "task": "1"}
        want = []
        n = [0]

        def mk(status="open", owner=own, hit=False, **extra):
            n[0] += 1
            i = fid("abcdefghijkmnpqrstuvwxyz23456789"[n[0]])
            self.finding(i, status, owner, **extra)
            if hit:
                want.append((i, status))

        mk(owner={"kind": "roadmap", "plan": "p"})            # OW3
        for other in ("q", "p ", "P", "p/x", "p-b"):          # OW4
            mk(owner={"kind": "plan", "plan": other, "task": "1"})
        mk("closed", resolved_by="zz")                        # OW5
        mk("merged", resolved_by="zz")
        for st in ("planned", "in-progress", "fixed-unpinned", "pinned", "deferred", "open"):   # OW6
            mk(st, hit=True)
        for bad in ([], None, "p", {"kind": 5, "plan": "p"}, {"kind": "plan", "plan": 5}, {"kind": "plan", "plan": None},
                    {"kind": "plan", "plan": ["p"]}, {"kind": "plan"}):   # OW7
            mk(owner=bad)
        n[0] += 1
        i = fid("abcdefghijkmnpqrstuvwxyz23456789"[n[0]])     # a status that is missing
        self.put("%s/%s.yml" % (FD, i), emit({"schema": "finding/1", "id": i, "owner": own}))
        code, out = self.g("--plan", "p")
        self.assertEqual(code, 1)
        got = [l for l in out.splitlines() if "cleanup.owner" in l]
        self.assertEqual(got, ["FAIL cleanup.owner.%s: finding %s of plan p is %s; pass it to an issue or roadmap item"
                               % (i, i, st) for i, st in sorted(want)])

    def test_owner_unloadable_records(self):  # OW8
        self.clean()
        own = {"kind": "plan", "plan": "p", "task": "1"}
        for case in ("garbled", "dir", "no id", "int id"):
            with self.subTest(case=case):
                path = os.path.join(self.root, FD, "zz.yml")
                if case == "garbled":
                    self.put(FD + "/zz.yml", "a: [unclosed\n")
                elif case == "dir":
                    os.unlink(path)
                    os.mkdir(path)
                elif case == "no id":
                    os.rmdir(path)
                    self.put(FD + "/zz.yml", emit({"schema": "finding/1", "status": "open", "owner": own}))
                else:
                    self.put(FD + "/zz.yml", emit({"schema": "finding/1", "id": 5, "status": "open", "owner": own}))
                code, out = self.g("--plan", "p")
                self.assertEqual(code, 1)
                self.assertTrue(out.startswith("FAIL cleanup.input: " + FD + "/zz.yml"), out)
                self.assertEqual(out.count("\n"), 1, out)  # one line: the other groups are not shown

    def test_owner_uses_cfg_finding_prefix(self):  # OW12
        self.clean()
        write_record(self.root, ".strict-delivery/config.yml", dict(minimal_config(), merge={"mode": "controller"},
                                                                    ids={"finding": "X"}))
        self.finding("X-20261101-aaaa", "open", {"kind": "plan", "plan": "p", "task": "1"})
        self.assertEqual(self.g("--plan", "p")[1].splitlines()[2],
                         "FAIL cleanup.owner.X-20261101-aaaa: finding X-20261101-aaaa of plan p is open; pass it to an "
                         "issue or roadmap item")

    def test_owner_plan_compare_is_exact(self):  # OW4 (the matrix above holds the rows; this one pins the prefix case alone)
        self.clean()
        self.finding(fid("a"), "open", {"kind": "plan", "plan": "p-b", "task": "1"})
        self.assertEqual(self.g("--plan", "p"), (0, CLEAN))


class DecisionTests(Gx):
    def test_cited_open_decision_fails(self):  # OP1, plan test
        s = self.scen(extra={SPEC: "cites %s\n" % did("a")})
        self.cleanup_branch(s)
        self.decision(did("a"))
        code, out = self.g("--plan", "p")
        self.assertIn("FAIL cleanup.open." + did("a"), out)
        self.assertEqual((code, out), (1, "PASS cleanup.merge\nPASS cleanup.gone\nPASS cleanup.owner\nFAIL cleanup.open." +
                                       did("a") + ": decision " + did("a") + " is cited by the cleaned files and is still "
                                       "open\nPASS cleanup.landed\n"))

    def test_lasting_decision_unlanded_fails(self):  # LD1, plan test
        s = self.scen(extra={SPEC: "cites %s\n" % did("a")})
        self.cleanup_branch(s)
        self.put(PLAYBOOK, "no id here\n")
        self.decision(did("a"), "answered", "lasting", landed_in=[PLAYBOOK + "#x"])
        commit_all(self.root, "playbook")
        code, out = self.g("--plan", "p")
        self.assertIn("FAIL cleanup.landed." + did("a"), out)
        self.assertEqual(out.splitlines()[-1], "FAIL cleanup.landed.%s: landed_in: %s does not contain the decision id %s"
                         % (did("a"), PLAYBOOK, did("a")))
        self.put(PLAYBOOK, "the rule of %s\n" % did("a"))  # LD2: landed
        commit_all(self.root, "landed")
        self.assertEqual(self.g("--plan", "p"), (0, CLEAN))

    def test_decision_rule_matrix(self):  # OP2-OP7, OP10, LD1, LD4-LD8, OUT1, LD10
        a, b, c, e, f, g, h, i, j, k, m, n, p, q, r, s_, t, u, v, w = [did(x) for x in "abcefghijkmnpqrstuvw"]
        d = did("d")
        text = "cites %s\n" % " ".join([a, b, c, d, e, f, g, i, j, k, "(" + r + ")", "X" + q, q + "a", q + "-2", "(%s)" % m, n,
                                         s_])
        s = self.scen(extra={SPEC: text, LEDGER: LEDGER_HEAD + "cites %s\n" % t})
        self.put(PS + "/p/late.md", "cites %s\n" % u)  # only at HEAD, not at the merge: not counted
        commit_all(self.root, "late")
        self.cleanup_branch(s)
        self.put(PLAYBOOK, "rule of %s and %s\n" % (e, h))
        self.put(".strict-delivery/playbooks/y.md", "cites %s\n" % w)  # not in the set: not counted
        self.decision(a)                                                 # OP1 open
        self.decision(b, "answered", "one-off")                          # OP2
        self.decision(c, "withdrawn")                                    # OP3
        self.decision(e, "answered", "lasting", landed_in=[PLAYBOOK])    # LD2 landed
        self.decision(f, "answered", "lasting", cls="merge-grant", plan="p")  # LD7 grant class: not judged
        self.decision(g, "open")                                         # OP10: open, superseded by an answered h
        self.decision(h, "answered", "lasting", landed_in=[PLAYBOOK], supersedes=g)
        self.decision(i, "answered", "lasting", landed_in=[PLAYBOOK + "#x"])   # LD1 (i is not in the playbook)
        self.decision(j, "answered", "lasting")                          # LD4: no landed_in
        self.decision(k, "answered", "lasting", landed_in=[])            # LD4: empty
        self.decision(q, "open")                                         # OP5: only broken tokens cite it
        self.decision(r, "open")                                         # OP5: the parenthesised token is a citation
        self.decision(m, "answered", "lasting", landed_in=[PLAYBOOK])    # LD5: m superseded by p (cited m)
        self.decision(s_, "answered", "lasting", landed_in=[PLAYBOOK])   # LD6: s superseded by a one-off
        self.decision(t, "open")                                         # OP6: cited in the ledger at the merge
        self.decision(u, "open")                                         # cited only after the merge
        self.decision(v, "open")                                         # OP7: never cited; its own file names it
        self.decision(w, "open")
        self.decision(p, "answered", "lasting", landed_in=[PLAYBOOK + "#x"], supersedes=m)  # the superseder of m: unlanded
        self.decision(n, "answered", "one-off", supersedes=s_)
        commit_all(self.root, "records")
        code, out = self.g("--plan", "p")
        self.assertEqual(code, 1)
        fail = lambda id_, why: "FAIL cleanup.%s: %s\n" % (id_, why)
        grp = "decision %s is cited by the cleaned files and is still open"
        no_id = "landed_in: %s does not contain the decision id %s"
        absent = "landed_in: absent or empty; a lasting decision lands its rule outside the cleaned files"
        # the open group in sorted id order, then the landed group in sorted id order (the final id of a superseded one)
        want = ("PASS cleanup.merge\nPASS cleanup.gone\nPASS cleanup.owner\n"
                + "".join(fail("open." + x, grp % x) for x in sorted([a, g, r, t]))
                + "".join(fail("landed." + x, why) for x, why in sorted([
                    (i, no_id % (PLAYBOOK, i)), (j, absent), (k, absent), (p, no_id % (PLAYBOOK, p))])))
        self.assertEqual(out, want)

    def test_cited_decision_token_rules_through_gate(self):  # OP5 (the tokens of the matrix are checked there; here alone)
        s = self.scen(extra={SPEC: "%s %s %s\n" % ("X" + did("a"), did("a") + "a", did("a") + "-2")})
        self.cleanup_branch(s)
        self.decision(did("a"))
        self.assertEqual(self.g("--plan", "p"), (0, CLEAN))

    def test_cited_id_without_record(self):  # OP4
        s = self.scen(extra={SPEC: "cites %s\n" % did("a")})
        self.cleanup_branch(s)
        self.assertEqual(self.g("--plan", "p"), (0, CLEAN))

    def test_cited_one_off_not_judged(self):  # OP2
        s = self.scen(extra={SPEC: "cites %s\n" % did("a")})
        self.cleanup_branch(s)
        self.decision(did("a"), "answered", "one-off")
        self.assertEqual(self.g("--plan", "p"), (0, CLEAN))

    def test_decision_store_errors(self):  # OP8
        s = self.scen(extra={SPEC: "cites %s\n" % did("a")})
        self.cleanup_branch(s)
        self.put(DEC + "/bad.yml", "a: [unclosed\n")
        code, out = self.g("--plan", "p")
        self.assertEqual(code, 1)
        self.assertTrue(out.startswith("FAIL cleanup.input:"), out)

    def test_cited_uses_cfg_decision_prefix(self):  # OP9
        s = self.scen(extra={SPEC: "cites ZZ-20261101-aaaa and %s\n" % did("b")})
        self.cleanup_branch(s)
        write_record(self.root, ".strict-delivery/config.yml", dict(minimal_config(), merge={"mode": "controller"},
                                                                    ids={"decision": "ZZ"}))
        self.decision("ZZ-20261101-aaaa")
        self.decision(did("b"))
        out = self.g("--plan", "p")[1]
        self.assertIn("FAIL cleanup.open.ZZ-20261101-aaaa", out)
        self.assertNotIn(did("b"), out)

    def test_landed_cite_kinds_through_gate(self):  # LD3
        s = self.scen(extra={SPEC: "cites %s\n" % did("a")})
        self.cleanup_branch(s)
        self.put("docs/other.md", "x\n")
        commit_all(self.root, "other")
        cites = [SPEC + "#x", "README.md", "CLAUDE.md#x", "docs/other.md", PLAYBOOK + "#", ".strict-delivery/playbooks/nope.md",
                 5, "./x.md"]
        self.decision(did("a"), "answered", "lasting", landed_in=cites)
        out = self.g("--plan", "p")[1].splitlines()[-1]
        for part in ("landed_in: %s is a spec; specs are cleaned" % SPEC, "landed_in: README.md is not a playbook, CLAUDE.md or architecture.md",
                     "landed_in: CLAUDE.md is not a tracked regular file", "landed_in: docs/other.md is not a playbook",
                     "landed_in: %s# is not a normalised repo-relative path" % PLAYBOOK,
                     "landed_in: .strict-delivery/playbooks/nope.md is not a tracked regular file", "landed_in: 5 is not a string",
                     "landed_in: ./x.md is not a normalised"):
            self.assertIn(part, out)
        self.assertTrue(out.startswith("FAIL cleanup.landed." + did("a") + ": "), out)

    def test_superseded_by_one_off_and_fork(self):  # LD6
        s = self.scen(extra={SPEC: "cites %s\n" % did("a")})
        self.cleanup_branch(s)
        self.decision(did("a"), "answered", "lasting", landed_in=[PLAYBOOK])
        self.decision(did("b"), "answered", "lasting", supersedes=did("a"), landed_in=[PLAYBOOK])
        self.decision(did("c"), "answered", "lasting", supersedes=did("a"), landed_in=[PLAYBOOK])
        code, out = self.g("--plan", "p")
        self.assertEqual(code, 1)
        self.assertTrue(out.startswith("FAIL cleanup.input:") and "fork" in out, out)

    def test_one_off_superseded_by_a_fork_not_judged(self):  # OP2, LD6: a one-off is skipped before current() can see a fork
        s = self.scen(extra={SPEC: "cites %s\n" % did("a")})
        self.cleanup_branch(s)
        self.decision(did("a"), "answered", "one-off")
        self.decision(did("b"), "answered", "lasting", supersedes=did("a"), landed_in=[PLAYBOOK])
        self.decision(did("c"), "answered", "lasting", supersedes=did("a"), landed_in=[PLAYBOOK])
        self.assertEqual(self.g("--plan", "p"), (0, CLEAN))

    def test_first_record_of_a_cited_id_decides(self):  # OP4: two records of one id; the first in file-name order is read
        s = self.scen(extra={SPEC: "cites %s\n" % did("a")})
        self.cleanup_branch(s)
        self.put("%s/DEC-20261031-a000.yml" % DEC, emit({"schema": "decision/1", "id": did("a"), "status": "open",
                                                         "class": "scope"}))
        self.decision(did("a"), "answered", "lasting")  # DEC-20261101-aaaa.yml, no landed_in
        self.assertEqual(self.g("--plan", "p"), (1, "PASS cleanup.merge\nPASS cleanup.gone\nPASS cleanup.owner\n"
                                                    "FAIL cleanup.open." + did("a") + ": decision " + did("a") + " is cited "
                                                    "by the cleaned files and is still open\nPASS cleanup.landed\n"))

    def test_records_with_an_unhashable_id_are_skipped(self):  # OP8: an id that is a list is no id
        s = self.scen(extra={SPEC: "cites %s\n" % did("a")})
        self.cleanup_branch(s)
        self.put("%s/DEC-20261031-a000.yml" % DEC, emit({"schema": "decision/1", "id": ["x"], "status": "answered",
                                                         "class": "scope", "effect": "lasting"}))
        self.decision(did("a"), "answered", "one-off")
        self.assertEqual(self.g("--plan", "p"), (0, CLEAN))

    def test_withdrawn_cited_record_superseded_by_a_lasting_one_not_judged(self):  # OP3, LD6
        s = self.scen(extra={SPEC: "cites %s\n" % did("a")})
        self.cleanup_branch(s)
        self.decision(did("a"), "withdrawn", "lasting")
        self.decision(did("b"), "answered", "lasting", supersedes=did("a"))  # in force, no landed_in, but never cited
        self.assertEqual(self.g("--plan", "p"), (0, CLEAN))

    def test_landed_reasons_joined_with_semicolons(self):  # LD3
        s = self.scen(extra={SPEC: "cites %s\n" % did("a")})
        self.cleanup_branch(s)
        self.decision(did("a"), "answered", "lasting", landed_in=["README.md", "./x.md"])
        self.assertEqual(self.g("--plan", "p")[1].splitlines()[-1],
                         "FAIL cleanup.landed.%s: landed_in: README.md is not a playbook, CLAUDE.md or architecture.md; "
                         "landed_in: ./x.md is not a normalised repo-relative path with an optional non-empty #anchor" % did("a"))

    def test_landed_uses_one_tracked_set(self):  # LD9
        s = self.scen(extra={SPEC: "cites %s %s\n" % (did("a"), did("b"))})
        self.cleanup_branch(s)
        for c in "ab":
            self.decision(did(c), "answered", "lasting", landed_in=[PLAYBOOK])
        real = gitinfo.tracked_files
        with mock.patch.object(gitinfo, "tracked_files", side_effect=real) as spy:
            self.g("--plan", "p")
        self.assertEqual(spy.call_count, 1)

    def test_open_and_landed_are_disjoint(self):  # LD8, OUT3
        s = self.scen(extra={SPEC: "cites %s %s\n" % (did("a"), did("b"))}, owned=True)
        self.cleanup_branch(s, keep=(SPEC,))
        self.decision(did("a"))
        self.decision(did("b"), "answered", "lasting", landed_in=[PLAYBOOK])
        out = self.g("--plan", "p")[1]
        self.assertEqual([l.split(":")[0] for l in out.splitlines()],
                         ["PASS cleanup.merge", "FAIL cleanup.gone." + SPEC, "FAIL cleanup.owner." + OPENF,
                          "FAIL cleanup.open." + did("a"), "FAIL cleanup.landed." + did("b")])


class ProgramTests(Gx):
    def program(self, plans=("a-plan", "b-plan"), specs=(), program_plan=PG + "/program-plan.md"):
        streams = {"schema": "streams/1", "program": NAME, "plan": program_plan, "specs": list(specs),
                   "streams": [{"id": p[0], "plan": "%s/%s.md" % (PG, p)} for p in plans]}
        d = "%s/%s" % (PROGRAMS, NAME)
        git(self.root, "checkout", "-q", "-b", NAME + "/integration", "main")
        self.put(d + "/streams.yml", emit(streams))
        self.put(d + "/status.md", "<!-- schema: status/1 -->\n\nthe status page\n")
        self.put(d + "/sync-log.md", "<!-- schema: sync-log/1 -->\n")
        self.put(d + "/merged.md", "<!-- schema: merged-log/1 -->\n")
        commit_all(self.root, "program")
        git(self.root, "checkout", "-q", "main")

    def build(self, final_b=True, **kw):
        a = self.scen(plan="a-plan", tag="sa", fid="F-20261031-k3f9", **kw)
        b = self.scen(plan="b-plan", tag="sb", fid="F-20261031-n5n5", final=final_b, **kw)
        self.program()
        return a, b

    def close(self, status="answered", cls="program-close", program=NAME, i=D3, **extra):
        row = {"schema": "decision/1", "id": i, "status": status, "class": cls}
        if program is not None:
            row["program"] = program
        row.update(extra)
        self.put("%s/%s.yml" % (DEC, i), emit(row))

    def close_branch(self, a, b, keep=()):
        git(self.root, "checkout", "-q", "-b", "cleanup/" + NAME, "main")
        rm = [p for p in sorted(a["set"] | b["set"]) if p not in keep]
        git(self.root, "rm", "-q", "--", *rm)
        commit_all(self.root, "cleanup")

    def gp(self, *extra):
        return self.g("--program", NAME, "--decision", D3, *extra)

    def test_program_close_clean_passes(self):  # PM1
        a, b = self.build()
        self.close_branch(a, b)
        self.close()
        self.assertEqual(self.gp(), (0, CLEAN))
        self.assertEqual(self.both(["--program", NAME, "--decision", D3, "--root", self.root]), (0, CLEAN))

    def test_program_close_decision_forms(self):  # PM2, PM5
        a, b = self.build()
        self.close_branch(a, b)
        bad = {"open": dict(status="open"), "withdrawn": dict(status="withdrawn"), "scope": dict(cls="scope"),
               "program-create": dict(cls="program-create"), "other program": dict(program="20261102-y"),
               "no program": dict(program=None)}
        for name, kw in bad.items():
            with self.subTest(case=name):
                self.close(**kw)
                code, out = self.gp()
                self.assertEqual(code, 1)
                self.assertEqual(out.count("\n"), 1)
                self.assertTrue(out.startswith("FAIL cleanup.merge: decision %s " % D3), out)
        self.close()
        self.close(i="DEC-20261031-q7q7", supersedes=D3)  # D3 is superseded by another answered program-close decision
        code, out = self.gp()
        self.assertEqual((code, out), (1, "FAIL cleanup.merge: decision %s is superseded\n" % D3))
        self.assertEqual(self.g("--program", NAME, "--decision", "DEC-20261031-q7q7")[1].splitlines()[0], "PASS cleanup.merge")
        os.unlink(os.path.join(self.root, DEC, "DEC-20261031-q7q7.yml"))
        self.finding("F-20261031-k3f9", "closed")  # the id of a finding is no decision
        self.assertEqual(self.g("--program", NAME, "--decision", "F-20261031-k3f9")[1][:25], "FAIL cleanup.input: --dec")

    def test_program_close_open_fails(self):  # PM5
        a, b = self.build()
        self.close_branch(a, b)
        self.close(status="open")
        self.assertEqual(self.gp(), (1, "FAIL cleanup.merge: decision %s is not answered\n" % D3))

    def test_program_stream_not_merged_fails_merge(self):  # PM3
        a, b = self.build(final_b=False)
        self.close()
        code, out = self.gp()
        self.assertEqual((code, out), (1, "FAIL cleanup.merge: stream plan b-plan has no final merge; the program is not "
                                          "finished\n"))

    def test_program_stream_workspace_left(self):  # PM4
        a, b = self.build()
        self.close()
        self.close_branch(a, b, keep=(PS + "/b-plan/handoff.md",))
        code, out = self.gp()
        self.assertEqual((code, out), (1, "PASS cleanup.merge\nFAIL cleanup.gone." + PS + "/b-plan/handoff.md" + STILL +
                                       "PASS cleanup.owner\nPASS cleanup.open\nPASS cleanup.landed\n"))

    def test_program_files_broken(self):  # PM6
        a, b = self.build()
        self.close()
        self.close_branch(a, b)
        git(self.root, "checkout", "-q", NAME + "/integration")
        self.put("%s/%s/streams.yml" % (PROGRAMS, NAME), "a: [unclosed\n")
        commit_all(self.root, "broken")
        git(self.root, "checkout", "-q", "cleanup/" + NAME)
        code, out = self.gp()
        self.assertEqual(code, 1)
        self.assertTrue(out.startswith("FAIL cleanup.input:") and "streams.yml" in out, out)
        git(self.root, "branch", "-q", "-D", NAME + "/integration")
        code, out = self.gp()
        self.assertEqual(code, 1)
        self.assertTrue(out.startswith("FAIL cleanup.input:"), out)

    def test_program_folder_not_judged(self):  # PM7
        a, b = self.build()
        self.close()
        self.close_branch(a, b)
        self.put("%s/%s/streams.yml" % (PROGRAMS, NAME), "x\n")
        commit_all(self.root, "folder")
        self.assertEqual(self.gp(), (0, CLEAN))

    def test_program_plan_and_specs_must_be_gone(self):  # PM8
        self.scen(plan="a-plan", tag="sa", fid="F-20261031-k3f9")
        self.scen(plan="b-plan", tag="sb", fid="F-20261031-n5n5")
        self.program(specs=[SPECS + "/program-spec.md"])
        self.close()
        a = {"set": {p.replace("/p/", "/a-plan/").replace("/p.md", "/a-plan.md").replace("/s.md", "/sa.md") for p in PSET}}
        a["set"] = {PG + "/a-plan.md", PS + "/a-plan/handoff.md", PS + "/a-plan/ledger.md", REV + "/a-plan/r.md",
                    SPECS + "/sa.md", CL + "/docs--strict-delivery--specs--sa.yml", FD + "/F-20261031-k3f9.yml"}
        b = {"set": {PG + "/b-plan.md", PS + "/b-plan/handoff.md", PS + "/b-plan/ledger.md", REV + "/b-plan/r.md",
                     SPECS + "/sb.md", CL + "/docs--strict-delivery--specs--sb.yml", FD + "/F-20261031-n5n5.yml"}}
        self.close_branch(a, b)
        self.put(PG + "/program-plan.md", "program plan\n")
        self.put(SPECS + "/program-spec.md", "program spec\n")
        commit_all(self.root, "program files")
        code, out = self.gp()
        self.assertEqual((code, out), (1, "PASS cleanup.merge\nFAIL cleanup.gone." + PG + "/program-plan.md" + STILL +
                                       "FAIL cleanup.gone." + SPECS + "/program-spec.md" + STILL +
                                       "PASS cleanup.owner\nPASS cleanup.open\nPASS cleanup.landed\n"))

    def test_stream_plan_checked_as_plan(self):  # PM10
        a, b = self.build()
        self.cleanup_branch(a, name="a-plan")
        self.assertEqual(self.g("--plan", "a-plan"), (0, CLEAN))

    def test_program_citation_scan_points(self):  # PM9, LD11, OW11
        a = self.scen(plan="a-plan", tag="sa", fid="F-20261031-k3f9", extra={SPECS + "/sa.md": "cites %s\n" % did("a")})
        b = self.scen(plan="b-plan", tag="sb", fid="F-20261031-n5n5", extra={SPECS + "/sb.md": "cites %s\n" % did("b")})
        self.program()
        self.put(PG + "/program-plan.md", "cites %s\n" % did("c"))  # on the base branch until the cleanup
        commit_all(self.root, "program plan")
        self.close_branch(a, b, keep=())
        self.close()
        for c in "abc":
            self.decision(did(c))
        for slug, c in (("program-plan", "d"), ("a-plan", "e"), ("b-plan", "f"), (NAME, "g"), ("other", "h")):
            self.finding(fid(c), "open", {"kind": "plan", "plan": slug, "task": "1"})
        code, out = self.gp()
        self.assertEqual(code, 1)
        self.assertEqual([l.split(":")[0] for l in out.splitlines()],
                         ["PASS cleanup.merge", "FAIL cleanup.gone." + PG + "/program-plan.md"] +
                         ["FAIL cleanup.owner." + fid(c) for c in "def"] + ["FAIL cleanup.open." + did(c) for c in "abc"] +
                         ["PASS cleanup.landed"])

    def restream(self, **fields):
        """streams.yml on the integration branch with ``fields`` replaced (a key set to None is removed)."""
        git(self.root, "checkout", "-q", NAME + "/integration")
        streams = {"schema": "streams/1", "program": NAME, "plan": PG + "/program-plan.md", "specs": [],
                   "streams": [{"id": "a", "plan": PG + "/a-plan.md"}, {"id": "b", "plan": PG + "/b-plan.md"}]}
        streams.update(fields)
        self.put("%s/%s/streams.yml" % (PROGRAMS, NAME), emit({k: v for k, v in streams.items() if v is not None}))
        commit_all(self.root, "streams variant")
        git(self.root, "checkout", "-q", "cleanup/" + NAME)

    def test_program_streams_yml_shapes_refused(self):  # PM6: a malformed streams.yml is one cleanup.input line, never a crash
        a, b = self.build()
        self.close()
        self.close_branch(a, b)
        cases = (("streams not a list", dict(streams=5), "streams.yml: streams must be a list"),
                 ("streams absent", dict(streams=None), "streams.yml: streams must be a list"),
                 ("a row not a mapping", dict(streams=["x"]), "streams.yml: streams.0.plan must be a string"),
                 ("a row plan not a string", dict(streams=[{"id": "a", "plan": 5}]),
                  "streams.yml: streams.0.plan must be a string"),
                 ("a row plan not .md", dict(streams=[{"id": "a", "plan": PG + "/a-plan.txt"}]),
                  "streams.yml: streams.0.plan: " + PG + "/a-plan.txt is not " + PG + "/<name>.md"),
                 ("specs not a list", dict(specs=5), "streams.yml: specs must be a list"))
        for name, fields, text in cases:
            with self.subTest(case=name):
                self.restream(**fields)
                code, out = self.gp()
                self.assertEqual(code, 1)
                self.assertEqual(out.splitlines()[-1], "FAIL cleanup.input: " + text)

    def test_program_unmerged_streams_listed_sorted_and_once(self):  # PM3: duplicates dropped, slug order
        self.scen(plan="a-plan", tag="sa", fid="F-20261031-k3f9", final=False)
        self.scen(plan="b-plan", tag="sb", fid="F-20261031-n5n5", final=False)
        self.program(plans=("b-plan", "a-plan", "b-plan"))
        self.close()
        self.assertEqual(self.gp(), (1, "FAIL cleanup.merge: stream plan a-plan has no final merge; the program is not "
                                        "finished; stream plan b-plan has no final merge; the program is not finished\n"))

    def test_program_close_first_record_of_an_id_decides(self):  # PM2: two records of one id; the first in file-name order
        a, b = self.build()
        self.close_branch(a, b)
        self.close()  # DEC-20261031-p6q7.yml: answered
        self.put("%s/DEC-20261031-a000.yml" % DEC, emit({"schema": "decision/1", "id": D3, "status": "open",
                                                         "class": "program-close", "program": NAME}))
        self.assertEqual(self.gp(), (1, "FAIL cleanup.merge: decision %s is not answered\n" % D3))

    def test_program_shared_files_read_at_the_base_branch(self):  # PM9, MG14: removed at HEAD, cited on the base branch
        a = self.scen(plan="a-plan", tag="sa", fid="F-20261031-k3f9")
        b = self.scen(plan="b-plan", tag="sb", fid="F-20261031-n5n5")
        self.program()
        self.put(PG + "/program-plan.md", "cites %s\n" % did("c"))
        commit_all(self.root, "program plan")
        git(self.root, "branch", "trunk", "main")  # the base branch is trunk; main moves on without the program plan
        git(self.root, "rm", "-q", "--", PG + "/program-plan.md")
        commit_all(self.root, "main loses the plan")
        write_record(self.root, ".strict-delivery/config.yml", dict(minimal_config(), merge={"mode": "controller"},
                                                                    base_branch="trunk"))
        git(self.root, "checkout", "-q", "-b", "cleanup/" + NAME, "trunk")
        git(self.root, "rm", "-q", "--", *sorted((a["set"] | b["set"]) | {PG + "/program-plan.md"}))
        commit_all(self.root, "cleanup")
        self.close()
        self.decision(did("c"))
        self.assertEqual(self.gp(), (1, "PASS cleanup.merge\nPASS cleanup.gone\nPASS cleanup.owner\nFAIL cleanup.open." +
                                     did("c") + ": decision " + did("c") + " is cited by the cleaned files and is still "
                                     "open\nPASS cleanup.landed\n"))


class OutputTests(Gx):
    def test_cleanup_line_order(self):  # OUT1
        a, d = did("a"), did("b")
        s = self.scen(owned=True, extra={SPEC: "cites %s %s\n" % (a, d)})
        self.cleanup_branch(s, keep=(SPEC,))
        self.decision(a)
        self.put(PLAYBOOK, "x\n")
        self.decision(d, "answered", "lasting", landed_in=[PLAYBOOK])
        code, out = self.g("--plan", "p")
        self.assertEqual(code, 1)
        self.assertEqual([l.split(":")[0] for l in out.splitlines()],
                         ["PASS cleanup.merge", "FAIL cleanup.gone." + SPEC, "FAIL cleanup.owner." + OPENF,
                          "FAIL cleanup.open." + a, "FAIL cleanup.landed." + d])

    def test_pass_id_withheld_only_for_failing_group(self):  # OUT3
        s = self.scen()
        self.cleanup_branch(s, keep=(LEDGER,))
        out = self.g("--plan", "p")[1]
        self.assertNotIn("PASS cleanup.gone", out)
        for c in ("merge", "owner", "open", "landed"):
            self.assertIn("PASS cleanup." + c + "\n", out)

    def test_cleanup_exit_codes(self):  # OUT4
        s = self.scen()
        self.cleanup_branch(s)
        self.assertEqual(self.g("--plan", "p")[0], 0)
        self.assertEqual(self.g("--plan", "q")[0], 1)

    def test_cleanup_gate_writes_nothing(self):  # OUT5
        s = self.scen()
        self.cleanup_branch(s)
        before = git(self.root, "status", "--porcelain", "--untracked-files=all")
        refs = git(self.root, "for-each-ref")
        seen = []
        real = gitinfo._run
        with mock.patch.object(gitinfo, "_run", side_effect=lambda r, label, argv, *a, **k: seen.append(argv[0])
                               or real(r, label, argv, *a, **k)):
            self.assertEqual(self.g("--plan", "p"), (0, CLEAN))
        self.assertEqual(git(self.root, "status", "--porcelain", "--untracked-files=all"), before)
        self.assertEqual(git(self.root, "for-each-ref"), refs)
        self.assertTrue(seen)
        for forbidden in ("fetch", "push", "checkout", "rm", "branch", "commit", "merge", "add", "reset", "pull", "clone",
                          "tag", "update-ref", "config"):
            self.assertNotIn(forbidden, seen)

    def test_cleanup_in_hook_environment(self):  # OUT6
        s = self.scen()
        self.cleanup_branch(s)
        index = os.path.join(self.tmp, "index-copy")
        with open(os.path.join(self.root, ".git", "index"), "rb") as src, open(index, "wb") as dst:
            dst.write(src.read())
        with mock.patch.dict(os.environ, {"GIT_INDEX_FILE": index}):
            self.assertEqual(self.g("--plan", "p"), (0, CLEAN))

    def test_cleanup_gate_ignores_colour_and_abbrev_config(self):  # OUT10
        s = self.scen(owned=True)
        for k, v in (("color.ui", "always"), ("color.diff", "always"), ("core.abbrev", "7"), ("diff.noprefix", "true")):
            self.assertEqual(git(self.root, "config", k), v)
        self.cleanup_branch(s, keep=(LEDGER,))
        out = self.g("--plan", "p")[1]
        self.assertEqual([l.split(":")[0] for l in out.splitlines()],
                         ["PASS cleanup.merge", "FAIL cleanup.gone." + LEDGER, "FAIL cleanup.owner." + OPENF,
                          "PASS cleanup.open", "PASS cleanup.landed"])
        self.assertEqual(self.g("--plan", "nosuch"), (1, "FAIL cleanup.merge: plan nosuch has no final merge on the base branch\n"))

    def test_cleanup_digit_limits_same_on_both(self):  # V1 (the limit settings run in test_digit_limits)
        for setting in INT_LIMITS:
            with int_limit(setting):
                self.assertEqual(self.g("--plan", "p"), (1, NOPLAN))

    def test_cleanup_exception_groups(self):  # V3
        with open(os.path.join(REPO, "gates", "gate_cleanup.py"), encoding="utf-8") as fh:
            text = fh.read()
        for word in ("Exception" + "Group", "except" + "*"):
            self.assertNotIn(word, text)
        if not hasattr(builtins, "ExceptionGroup"):
            self.skipTest("ExceptionGroup exists on 3.11 and later only")
        boom = lambda *a, **k: (_ for _ in ()).throw(ExceptionGroup("g", [OSError("x")]))  # noqa: F821
        with mock.patch.object(gitinfo, "_run", side_effect=boom):
            code, out = self.g("--plan", "p")
        self.assertEqual(code, 1)
        self.assertTrue(out.startswith("FAIL cleanup.input:"), out)


class RegistryTests(Gx):
    def test_cleanup_registered(self):  # RG1
        self.assertEqual(gates_main.GATES["cleanup"], "gates.gate_cleanup")
        self.assertEqual(sorted(gates_main.GATES), ["checkpoint", "cites", "claims", "cleanup", "context", "decisions",
                                                    "dispatch", "evidence", "register", "schema", "streams"])

    def test_check_usage_lists_cleanup(self):  # RG2
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(gates_main.main(["check"]), 2)
        self.assertEqual(err.getvalue(), "usage: python3 -m gates check <gate> [args]\ngates: checkpoint, cites, claims, "
                                         "cleanup, context, decisions, dispatch, evidence, register, schema, streams\n")

    def test_run_all_never_runs_cleanup(self):  # RG3
        for names in list(run_all.PROFILE_GATES.values()) + [run_all.BASE_GATES, run_all.LIVE_PROGRAM_GATES]:
            self.assertNotIn("cleanup", names)

    def test_cleanup_module_import_is_lazy(self):  # RG5
        with mock.patch.dict(gates_main.GATES, {"cleanup": "gates.gate_nosuch"}):
            self.assertEqual(self.g("--plan", "p"), (1, "FAIL cleanup.input: gates/gate_nosuch.py missing\n"))
        importlib.import_module("gates.gate_cleanup")


class EnableTests(Gx):
    """Task P3.3 Step 5 as a fixture: a bare remote, two sub-block branches merged with ``--no-ff``, the MERGED lines as the
    first commit of ``cleanup/fx`` and the removal as its second."""

    def build(self, spec_text="spec\n"):
        self.remote = os.path.join(self.tmp, "remote.git")
        git(self.tmp, "init", "-q", "--bare", "-b", "main", self.remote)
        r = self.root
        git(r, "remote", "add", "origin", self.remote)
        spec, plan = SPECS + "/fx.md", PG + "/fx.md"
        ho = {"schema": "handoff/1", "plan": "fx", "spec": [spec]}
        self.put(plan, "plan\n")
        self.put(spec, spec_text)
        self.put(PS + "/fx/ledger.md", LEDGER_HEAD)
        self.put(PS + "/fx/handoff.md", "---\n" + emit(ho) + "---\nbody\n")
        commit_all(r, "plan fx")
        git(r, "push", "-q", "origin", "main")
        heads = []
        for n in (1, 2):
            git(r, "checkout", "-q", "-b", "block/fx-%d" % n, "main")
            self.put("%s/fx/notes%d.md" % (PS, n), "notes\n")
            heads.append(commit_all(r, "notes %d" % n))
            git(r, "checkout", "-q", "main")
            git(r, "merge", "-q", "--no-ff", "-m", "Merge block/fx-%d" % n, "block/fx-%d" % n)
        merges = [git(r, "rev-parse", "main^1"), git(r, "rev-parse", "main")]
        git(r, "push", "-q", "origin", "main")
        git(r, "checkout", "-q", "-b", "cleanup/fx", "main")
        self.put(PS + "/fx/ledger.md", LEDGER_HEAD + mline(heads[0], merges[0], final="no", pr=1) + "\n" +
                 mline(heads[1], merges[1], final="yes", pr=2) + "\n")
        commit_all(r, "ledger")
        return {"set": sorted([plan, spec, PS + "/fx/ledger.md", PS + "/fx/handoff.md", PS + "/fx/notes1.md",
                               PS + "/fx/notes2.md"]), "heads": heads, "merges": merges}

    def test_enable_fixture_builds(self):  # EN1-EN5
        e = self.build()
        for n in (0, 1):
            self.assertEqual(len(git(self.root, "show", "-s", "--format=%P", e["merges"][n]).split()), 2)
        self.assertEqual(git(self.root, "ls-remote", self.remote, "refs/heads/main").split()[0], git(self.root, "rev-parse", "main"))
        git(self.root, "rm", "-q", "--", *e["set"])
        commit_all(self.root, "remove")
        self.assertEqual(git(self.root, "ls-files", "--", PS + "/fx", PG + "/fx.md", SPECS + "/fx.md"), "")

    def test_enable_check_passes(self):  # EN6, EN11
        e = self.build()
        git(self.root, "rm", "-q", "--", *e["set"])
        commit_all(self.root, "remove")
        self.assertEqual(self.both(["--plan", "fx", "--root", self.root]), (0, CLEAN))

    def test_enable_fixture_negative_variants(self):  # EN7
        e = self.build("cites %s\n" % did("a"))
        base = git(self.root, "rev-parse", "HEAD")

        def variant(name, keep=()):
            git(self.root, "checkout", "-q", "-f", "-B", name, base)
            git(self.root, "rm", "-q", "--", *[p for p in e["set"] if p not in keep])

        variant("v1", keep=(PS + "/fx/notes2.md",))
        self.assertEqual(self.g("--plan", "fx")[1].splitlines()[:2],
                         ["PASS cleanup.merge", "FAIL cleanup.gone." + PS + "/fx/notes2.md" + STILL.strip("\n")])
        git(self.root, "checkout", "-q", "-f", "-B", "v2", base)
        self.put(PS + "/fx/ledger.md", LEDGER_HEAD + mline(e["heads"][0], e["merges"][0], final="no", pr=1) + "\n")
        self.assertEqual(self.g("--plan", "fx"), (1, "FAIL cleanup.merge: plan fx has no final merge on the base branch\n"))
        variant("v3", keep=(SPECS + "/fx.md",))
        self.assertEqual(self.g("--plan", "fx")[1].splitlines()[1], "FAIL cleanup.gone." + SPECS + "/fx.md" + STILL.strip("\n"))
        variant("v4")
        self.decision(did("a"))
        self.assertEqual(self.g("--plan", "fx")[1].splitlines()[3].split(":")[0], "FAIL cleanup.open." + did("a"))
        os.unlink(os.path.join(self.root, DEC, did("a") + ".yml"))
        self.finding(fid("b"), "open", {"kind": "plan", "plan": "fx", "task": "1"})
        self.assertEqual(self.g("--plan", "fx")[1].splitlines()[2].split(":")[0], "FAIL cleanup.owner." + fid("b"))

    def test_enable_ci_shaped_clone(self):  # EN8, MG6
        e = self.build()
        git(self.root, "rm", "-q", "--", *e["set"])
        commit_all(self.root, "remove")
        git(self.root, "push", "-q", "origin", "cleanup/fx")
        ci = os.path.join(self.tmp, "ci")
        git(self.tmp, "clone", "-q", self.remote, ci)
        git(ci, "checkout", "-q", "--detach", "origin/cleanup/fx")
        git(ci, "branch", "-q", "-D", "main")
        self.assertEqual(self.run_in_process(["--plan", "fx", "--root", ci]),
                         (1, "FAIL cleanup.merge: plan fx has no final merge on the base branch\n"))
        git(ci, "branch", "main", "origin/main")
        self.assertEqual(self.run_in_process(["--plan", "fx", "--root", ci]), (0, CLEAN))

    def test_cleanup_pr_with_only_first_commit_fails_gone(self):  # WF11
        e = self.build()
        code, out = self.g("--plan", "fx")
        self.assertEqual(code, 1)
        self.assertEqual([l for l in out.splitlines() if l.startswith("FAIL")],
                         ["FAIL cleanup.gone." + p + STILL.strip("\n") for p in e["set"]])


if __name__ == "__main__":
    unittest.main()
