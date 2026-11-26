"""Tests of gates/gate_checkpoint.py (plan Task P1.3 Steps 1-4) through ``python3 -m gates check checkpoint``.

Row ids in comments refer to the P1.3 input-domain table (task-P1.3-domain.md) and its binding decisions D-Q1..D-Q26.
The handoff is written by ``yamlsub.emit`` from a hand-written row; expected lines, reasons and line counts are
written out by hand from the plan lines and the table, never read back from the code under test. Fixtures are
``make_repo`` repositories whose config pins ``color.ui=always``, ``color.diff=always``, ``core.abbrev=7`` (Global
Constraints :33) with a bare remote in the temp directory (no network). Rows MG1-MG15, DC4 and DC5 are the oracle of
Step 5 (the program controller's migration of this repository's workspace, D-Q26) and are not tested here."""
import ast
import builtins
import contextlib
import io
import json
import os
import re
import subprocess
import sys
import unittest
from unittest import mock

from gates import __main__ as gates_main
from gates import gate_checkpoint, producers
from gates.lib import checkpoints, gitinfo, yamlsub
from tests.helpers import (INT_LIMITS, TOP, GitIsolatedTestCase, check_root_forms, commit_all, git, int_limit, make_repo, minimal_config,
                           root_forms, write_record)
from tests.tipkinds import BAD_KINDS, refusal, set_entry

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PYS = ("/usr/bin/python3", "/opt/homebrew/bin/python3.13")
SLUG = "2026-10-31-x"
PLAN = "docs/strict-delivery/plans/%s.md" % SLUG
PS = ".strict-delivery/state/plans"
LEDGER = "%s/%s/ledger.md" % (PS, SLUG)
HANDOFF = "%s/%s/handoff.md" % (PS, SLUG)
LH = "<!-- schema: ledger/1 -->\n"
CK = "CHECKPOINT P1 P1.1 head={H} tests=5/5 gates=PASS next=P1.2"
EIGHT = ["handoff", "ledger", "agree", "head", "clean", "pushed", "reads", "worktrees"]
NINE = EIGHT + ["merges"]  # Task P3.1 (CM20): checkpoint.merges follows worktrees
NEW = ["cap", "records", "base", "files", "last"]  # Task 6K.2: the five lines after merges
ALL14 = NINE + NEW  # plan :6076, :6095
ALL = "".join("PASS checkpoint.%s\n" % i for i in ALL14)
ALL_EIGHT = "".join("PASS checkpoint.%s\n" % i for i in EIGHT)
NEW_PASS = "".join("PASS checkpoint.%s\n" % i for i in NEW)
SPEC = "docs/strict-delivery/specs/s.md"
# the fixtures whose ledger holds a MERGED line for a made-up merge sha ("b" * 40, pr 3, host mode): the line is now
# checked against git, so the gate's last line fails with the merge rule only (Task P3.1)
FAKE_MERGE_FAIL = ("FAIL checkpoint.merges: merge.3: %s is not a commit in this repository; update main from the remote\n"
                   % ("b" * 40))


def require_both_pys(tc):
    """CI runs each interpreter in its own matrix cell, so a same-on-both test skips where one is absent."""
    for py in PYS:
        if not os.path.exists(py):
            tc.skipTest("interpreter not present: " + py)


def ids(out):
    return re.findall(r"^(?:PASS|FAIL) checkpoint\.([a-z]+)", out, re.M)


def line_of(out, id_):
    for ln in out.split("\n"):
        if ln.startswith(("PASS checkpoint.%s" % id_, "FAIL checkpoint.%s:" % id_)):
            return ln
    return None


def run_main(argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
        code = gates_main.main(argv)
    return buf.getvalue(), code


def resume_text(plan, nxt, branch, head, open_ids="none"):
    """The resume line spelled out from Process :57 (not by ``resume_line``)."""
    return "Resume strict-delivery plan %s at %s; branch %s; head %s; open questions: %s." % (plan, nxt, branch, head, open_ids)


class Fx(GitIsolatedTestCase):
    """A repository on branch ``block/p1`` with a plan, a ledger, a handoff, committed and pushed to a bare remote."""

    def setUp(self):
        super().setUp()
        self.root = make_repo(self.work, getattr(self, "CFG", None))
        for k, v in (("color.ui", "always"), ("color.diff", "always"), ("color.status", "always"), ("core.abbrev", "7"),
                     ("diff.noprefix", "true")):
            git(self.root, "config", k, v)
        self.bare = os.path.join(self.tmp, "origin.git")

    def put(self, rel, data="x\n", root=None):
        path = os.path.join(root or self.root, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(data if isinstance(data, bytes) else data.encode("utf-8"))
        return path

    def build(self, lines=None, row=None, push=True, plan_text="## Block P1: basic\n", files=None, remote=True,
              ledger_text=None, handoff_text=None):
        git(self.root, "checkout", "-q", "-b", "block/p1")
        self.put(PLAN, plan_text)
        self.put(SPEC, "spec\n")
        for rel, data in (files or {}).items():
            self.put(rel, data)
        self.c1 = commit_all(self.root, "code")
        self.h7 = self.c1[:7]
        self.base = git(self.root, "rev-list", "--max-parents=0", "HEAD")
        body = "\n".join(l.replace("{H}", self.h7) for l in (lines if lines is not None else ["Prose line.", CK]))
        self.put(LEDGER, ledger_text if ledger_text is not None else LH + body + "\n")
        self.row = {
            "schema": "handoff/1", "plan": PLAN, "spec": [SPEC], "branch": "block/p1",
            "head": self.h7, "base": self.base, "ledger": LEDGER, "resume": resume_text(PLAN, "P1.2", "block/p1", self.h7),
            "block": "P1", "next_task": "P1.2", "findings_in_flight": [], "open_decisions": [], "rulings": 0,
            "grant": None, "live_subagents": [], "role": "controller", "budget": {"tokens": 300000, "minutes": 150},
            "worktrees": [{"path": ".", "branch": "block/p1", "head": self.h7, "porcelain": ""}],
            "skills": ["strict-delivery"], "ledger_from": 4, "batch_cut": None, "questions": [],
        }
        self.row.update(row or {})
        self.put(HANDOFF, handoff_text if handoff_text is not None else "---\n" + yamlsub.emit(self.row) + "---\nbody\n")
        self.c2 = commit_all(self.root, "checkpoint")
        if remote:
            git(self.tmp, "init", "-q", "--bare", "-b", "main", self.bare)
            git(self.root, "remote", "add", "origin", self.bare)
            if push:
                git(self.root, "push", "-q", "-u", "origin", "block/p1")
        return self

    def rewrite(self, **over):
        """Rewrite the handoff with ``over`` changed and commit it (pushed unless ``push`` is False)."""
        self.row.update(over)
        self.put(HANDOFF, "---\n" + yamlsub.emit(self.row) + "---\nbody\n")
        commit_all(self.root, "handoff")

    def push(self):
        git(self.root, "push", "-q", "origin", "block/p1")

    def chk(self, *args, root=None, slug=SLUG):
        argv = ["check", "checkpoint", "--root", root or self.root] + (["--plan", slug] if slug is not None else []) + list(args)
        return run_main(argv)

    def lines(self, out):
        return out.split("\n")


class HappyPath(Fx):
    def test_valid_checkpoint_passes(self):  # HD1, LG1, AG1, HE1, CL1, PU3, OR1; plan :2559
        self.build()
        out, code = self.chk()
        for c in ["handoff", "ledger", "agree", "head", "clean"]:
            self.assertIn("PASS checkpoint." + c, out)
        self.assertEqual(out, ALL)
        self.assertEqual(code, 0)

    def test_line_order_with_new_lines(self):  # OR1; plan :2588
        self.build()
        out, _ = self.chk()
        self.assertEqual(ids(out), ALL14)

    def test_short_and_full_head_agree(self):  # AG1, AG4; plan :2574
        for ledger_head, handoff_head in (("{H}", None), ("FULL", None), ("{H}", "FULL"), ("FULL", "FULL"), ("12", "{H}")):
            with self.subTest(ledger=ledger_head, handoff=handoff_head):
                fx = type(self)("test_valid_checkpoint_passes")
                fx.setUp()
                try:
                    fx.build()
                    full = fx.c1
                    pick = lambda v: full if v == "FULL" else full[:12] if v == "12" else fx.h7
                    ck = "CHECKPOINT P1 P1.1 head=%s tests=5/5 gates=PASS next=P1.2" % pick(ledger_head)
                    fx.put(LEDGER, LH + "Prose line.\n" + ck + "\n")
                    if handoff_head:
                        fx.rewrite(head=pick(handoff_head), resume=resume_text(PLAN, "P1.2", "block/p1", pick(handoff_head)),
                                   worktrees=[{"path": ".", "branch": "block/p1", "head": fx.h7, "porcelain": ""}])
                    else:
                        commit_all(fx.root, "ledger")
                    fx.push()
                    out, code = fx.chk()
                    self.assertIn("PASS checkpoint.agree", out)
                    self.assertEqual(code, 0, out)
                finally:
                    fx.doCleanups()

    def test_head_ancestor_passes(self):  # HE2: the handoff head is the commit before the checkpoint commit
        self.build()
        self.assertEqual(git(self.root, "rev-parse", "HEAD~1"), self.c1)
        out, _ = self.chk()
        self.assertEqual(line_of(out, "head"), "PASS checkpoint.head")

    def test_agree_head_differs(self):  # AG4
        self.build()
        self.put("other.txt")
        c3 = commit_all(self.root, "other")
        self.put(LEDGER, LH + "Prose line.\nCHECKPOINT P1 P1.1 head=%s tests=5/5 gates=PASS next=P1.2\n" % c3[:7])
        commit_all(self.root, "ledger")
        self.push()
        out, _ = self.chk()
        self.assertTrue(line_of(out, "agree").startswith("FAIL checkpoint.agree: head: ledger line 3 names %s, handoff names %s" % (c3[:7], self.h7)), out)

    def test_agree_head_not_a_commit(self):  # AG5, HE4
        self.build()
        self.put(LEDGER, LH + "Prose line.\nCHECKPOINT P1 P1.1 head=0000000 tests=5/5 gates=PASS next=P1.2\n")
        commit_all(self.root, "ledger")
        self.push()
        out, _ = self.chk()
        self.assertEqual(line_of(out, "agree"), "FAIL checkpoint.agree: head: 0000000 is not a commit")
        self.rewrite(head="0000000", resume=resume_text(PLAN, "P1.2", "block/p1", "0000000"))
        self.push()
        out, _ = self.chk()
        self.assertEqual(line_of(out, "head"), "FAIL checkpoint.head: head: 0000000 is not a commit")
        self.assertIn("FAIL checkpoint.ledger: plan text: handoff head 0000000 is not a commit", out)


class Arguments(Fx):
    def test_missing_plan_argument_is_input_fail(self):  # AV1; plan :2572
        self.build()
        out, code = self.chk(slug=None)
        self.assertTrue(out.startswith("FAIL checkpoint.input:"), out)
        self.assertEqual(out, "FAIL checkpoint.input: --plan SLUG is required\n")
        self.assertEqual(code, 1)
        out, _ = run_main(["check", "checkpoint"])
        self.assertEqual(out.count("\n"), 1)

    def test_plan_slug_forms(self):  # AV2, V1
        self.build()
        bad = ["", "A", "-a", "a_b", "a.b", "a b", "a/b", "a/../b", "..", ".", "a\n", "é", "a" * 3 + "ࡰ"]
        for slug in bad:
            with self.subTest(slug=repr(slug)):
                out, code = run_main(["check", "checkpoint", "--root", self.root, "--plan=" + slug])
                self.assertEqual(out, "FAIL checkpoint.input: --plan must match [a-z0-9][a-z0-9-]*\n")
                self.assertEqual(code, 1)
        for slug in ("x", "0a", "a-b", "2026-10-31-y", "a" * 255, "a" * 256, "a" * 4301):
            with self.subTest(slug=slug[:12] + str(len(slug))):
                out, code = self.chk(slug=slug)
                self.assertTrue(out.startswith("FAIL checkpoint.handoff: %s/%s/handoff.md: missing\n" % (PS, slug)), out[:200])
                self.assertEqual(ids(out), ["handoff", "clean", "pushed"])
                self.assertEqual(code, 1)

    def test_plan_option_forms(self):  # AV3
        self.build()
        self.assertEqual(run_main(["check", "checkpoint", "--root", self.root, "--plan=" + SLUG])[0], ALL)
        self.assertEqual(run_main(["check", "checkpoint", "--root", self.root, "--pla", SLUG])[0], ALL)
        for argv, frag in ((["--plan"], "expected one argument"), (["--plan", "--root", self.root], "expected one argument"),
                           (["--plan", "-x"], "expected one argument"), (["--PLAN", "x"], "unrecognized arguments"),
                           (["-plan", "x"], "unrecognized arguments")):
            with self.subTest(argv=argv):
                out, code = run_main(["check", "checkpoint", "--root", self.root] + argv)
                self.assertTrue(out.startswith("FAIL checkpoint.input: invalid arguments"), out)
                self.assertIn(frag, out)
                self.assertEqual(code, 1)

    def test_repeated_plan_is_refused(self):  # AV4
        self.build()
        for argv in (["--plan", "a", "--plan", "b"], ["--plan", "a", "--plan", "a"], ["--pla", "a", "--plan", "b"]):
            with self.subTest(argv=argv):
                out, code = run_main(["check", "checkpoint", "--root", self.root] + argv)
                self.assertEqual(out, "FAIL checkpoint.input: invalid arguments: --plan given more than once\n")
        out, _ = run_main(["check", "checkpoint", "--root", self.root, "--root", self.root, "--plan", SLUG])
        self.assertEqual(out, "FAIL checkpoint.input: invalid arguments: --root given more than once\n")

    def test_json_position(self):  # AV5, OR6
        self.build()
        out, code = run_main(["check", "checkpoint", "--json", "--root", self.root, "--plan", SLUG])
        d = json.loads(out)
        self.assertEqual(d["gate"], "checkpoint")
        self.assertIs(d["ok"], True)
        self.assertEqual([l["id"] for l in d["lines"]], ["checkpoint." + i for i in ALL14])
        self.assertEqual(d["lines"][5], {"status": "PASS", "id": "checkpoint.pushed", "reason": ""})
        out, code = run_main(["check", "checkpoint", "--root", self.root, "--plan", SLUG, "--json"])
        self.assertEqual(out, "FAIL checkpoint.input: invalid arguments: unrecognized arguments: --json\n")
        self.assertEqual(code, 1)

    def test_root_forms(self):  # AV6
        self.build()
        forms = root_forms(self.tmp, self.root)
        for name, path, verdict in forms:
            with self.subTest(form=name):
                out, code = run_main(["check", "checkpoint", "--root", path, "--plan", SLUG])
                if name == "nested":  # a repository below the top level of another: a top level with no config
                    self.assertEqual(out, "FAIL checkpoint.input: .strict-delivery/config.yml: missing; run /strict-delivery:init\n")
                elif verdict == "ok":
                    self.assertFalse(out.startswith("FAIL checkpoint.input:"), out)
                else:
                    self.assertEqual(out.count("\n"), 1, out)
                    self.assertTrue(out.startswith("FAIL checkpoint.input: "), out)
                    self.assertIn(verdict, out)

    def test_config_missing_and_custom_paths(self):  # AV7
        fresh = os.path.join(self.tmp, "nocfg")
        os.mkdir(fresh)
        git(fresh, "init", "-q", "-b", "main")
        out, _ = run_main(["check", "checkpoint", "--root", fresh, "--plan", SLUG])
        self.assertEqual(out, "FAIL checkpoint.input: .strict-delivery/config.yml: missing; run /strict-delivery:init\n")
        self.build()
        write_record(self.root, ".strict-delivery/config.yml", dict(minimal_config(), base_branch="block/p1"))
        commit_all(self.root, "cfg")
        self.push()
        out, _ = self.chk()
        self.assertIn("FAIL checkpoint.pushed: the current branch block/p1 is the base branch", out)

    def test_claude_project_dir(self):  # AV6
        with mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": os.path.join(self.tmp, "nope")}):
            out, _ = run_main(["check", "checkpoint", "--plan", SLUG])
        self.assertEqual(out, "FAIL checkpoint.input: CLAUDE_PROJECT_DIR is not a directory\n")
        self.build()
        with mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": self.root}):
            out, _ = run_main(["check", "checkpoint", "--plan", SLUG])
        self.assertEqual(out, ALL)

    def test_help_is_not_run(self):  # AV8
        for flag in ("--help", "-h"):
            out, code = run_main(["check", "checkpoint", flag])
            self.assertEqual(out, "FAIL checkpoint.input: help requested; no gate was run\n")

    def test_unknown_arguments(self):  # AV9
        self.build()
        for extra in (["--base", "main"], ["x"], ["--"]):
            with self.subTest(extra=extra):
                out, code = self.chk(*extra)
                self.assertTrue(out.startswith("FAIL checkpoint.input: invalid arguments"), out)
                self.assertEqual(code, 1)

    def test_gate_registered(self):  # AV10
        self.assertEqual(gates_main.GATES["checkpoint"], "gates.gate_checkpoint")
        out = io.StringIO()
        with contextlib.redirect_stderr(out):
            self.assertEqual(gates_main.main(["check"]), 2)
        self.assertIn("gates: checkpoint, cites, claims, cleanup, decisions, dispatch, register, schema, streams\n", out.getvalue())

    def test_main_exit_codes(self):  # AV12
        self.build()
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(gate_checkpoint.main(["--root", self.root, "--plan", SLUG]), 0)
            self.assertEqual(gate_checkpoint.main(["--root", self.root, "--plan", "nope"]), 1)
            with mock.patch.object(sys, "argv", ["gate_checkpoint.py", "--root", self.root, "--plan", SLUG]):
                self.assertEqual(gate_checkpoint.main(), 0)

    def test_gate_checkpoint_imports_same_on_both(self):  # AV13
        require_both_pys(self)
        self.assertEqual(gate_checkpoint.PRODUCES, ())
        for py in PYS:
            p = subprocess.run([py, "-c", "import gates.gate_checkpoint as g; print(g.PRODUCES)"], cwd=REPO,
                               capture_output=True, text=True)
            self.assertEqual((p.returncode, p.stdout), (0, "()\n"), py)

    def test_line_ids_unique_and_known(self):  # AV14
        self.build()
        self.rewrite(next_task="P1.3", head="0000000")
        out, _ = self.chk()
        got = ids(out)
        self.assertEqual(len(got), len(set(got)))
        self.assertTrue(set(got) <= set(ALL14))

    def test_not_in_run_all(self):  # AV11
        from gates import run_all
        for names in run_all.PROFILE_GATES.values():
            self.assertNotIn("checkpoint", names)


class Files(Fx):
    def test_missing_handoff_fails(self):  # HD2, OR2; plan :2568
        self.build()
        os.remove(os.path.join(self.root, *HANDOFF.split("/")))
        commit_all(self.root, "rm")
        self.push()
        out, code = self.chk()
        self.assertIn("FAIL checkpoint.handoff", out)
        self.assertEqual(line_of(out, "handoff"), "FAIL checkpoint.handoff: %s: missing" % HANDOFF)
        self.assertEqual(ids(out), ["handoff", "clean", "pushed"])
        self.assertEqual(code, 1)

    def test_handoff_file_kinds(self):  # FL1
        self.build()
        path = os.path.join(self.root, *HANDOFF.split("/"))
        real = path + ".real"
        os.rename(path, real)
        os.mkdir(path)
        out, _ = self.chk()
        self.assertIn("FAIL checkpoint.handoff: %s: is not a regular file" % HANDOFF, out)
        os.rmdir(path)
        os.symlink(real, path)
        out, _ = self.chk()
        self.assertIn("FAIL checkpoint.handoff: %s: is not a regular file" % HANDOFF, out)
        os.unlink(path)
        os.symlink("nowhere", path)
        out, _ = self.chk()
        self.assertIn("FAIL checkpoint.handoff: %s: is not a regular file" % HANDOFF, out)
        os.unlink(path)
        os.mkfifo(path)
        out, _ = self.chk()  # never opened: this returns at once
        self.assertIn("FAIL checkpoint.handoff: %s: is not a regular file" % HANDOFF, out)
        os.unlink(path)
        os.rename(real, path)
        os.chmod(path, 0)
        out, _ = self.chk()
        if os.access(path, os.R_OK):
            self.skipTest("this user reads mode 000 files")
        self.assertIn("FAIL checkpoint.handoff: %s: cannot read (Permission denied)" % HANDOFF, out)
        os.chmod(path, 0o644)
        self.assertEqual(self.chk()[0].split("\n")[0], "PASS checkpoint.handoff")

    def test_handoff_encodings(self):  # FL2, D-Q14
        self.build()
        path = self.put(HANDOFF, b"")
        for name, data, frag in (("empty", b"", "front matter: first line must be '---'"),
                                 ("bom", b"\xef\xbb\xbf---\nschema: handoff/1\n---\n", "front matter: first line must be '---'"),
                                 ("crlf", b"---\r\nschema: handoff/1\r\n---\r\n", "front matter: first line must be '---'"),
                                 ("bad utf8", b"---\n\xff\xfe\n---\n", "%s: not valid UTF-8" % HANDOFF)):
            with self.subTest(name=name):
                self.put(HANDOFF, data)
                out, _ = self.chk()
                self.assertTrue(line_of(out, "handoff").startswith("FAIL checkpoint.handoff: "), out)
                self.assertIn(frag, line_of(out, "handoff"))

    def test_workspace_directory_kinds(self):  # FL3
        self.build()
        wdir = os.path.join(self.root, PS, SLUG)
        real = wdir + ".real"
        os.rename(wdir, real)
        out, _ = self.chk()
        self.assertEqual(line_of(out, "handoff"), "FAIL checkpoint.handoff: %s: missing" % HANDOFF)
        os.symlink(real, wdir)
        out, _ = self.chk()
        self.assertEqual(line_of(out, "handoff"), "FAIL checkpoint.handoff: %s/%s: is a symlink; directories must be real directories" % (PS, SLUG))
        os.unlink(wdir)
        with open(wdir, "w") as fh:
            fh.write("x")
        out, _ = self.chk()
        self.assertEqual(line_of(out, "handoff"), "FAIL checkpoint.handoff: %s/%s: not a directory" % (PS, SLUG))
        os.unlink(wdir)
        os.rename(real, wdir)
        pdir = os.path.join(self.root, PS)
        os.rename(pdir, pdir + ".real")
        os.symlink(pdir + ".real", pdir)
        out, _ = self.chk()
        self.assertIn("is a symlink; directories must be real directories", line_of(out, "handoff"))

    def test_handoff_schema_errors_reported(self):  # HD3
        self.build()
        for name, text, frag in (
                ("no front matter", "plain\n", "front matter: first line must be '---'"),
                ("no closer", "---\nschema: handoff/1\n", "front matter: no closing '---' line"),
                ("v2", "---\n" + yamlsub.emit(dict(self.row, schema="handoff/2")) + "---\n", "schema: expected handoff/1, got handoff/2; run /strict-delivery:upgrade"),
                ("unknown key", "---\n" + yamlsub.emit(dict(self.row, in_progress_outside_plan="x")) + "---\n", "in_progress_outside_plan: unknown key"),
                ("missing field", "---\n" + yamlsub.emit({k: v for k, v in self.row.items() if k != "ledger_from"}) + "---\n", "ledger_from: required key is missing")):
            with self.subTest(name=name):
                self.put(HANDOFF, text)
                out, _ = self.chk()
                self.assertTrue(line_of(out, "handoff").startswith("FAIL checkpoint.handoff: "), out)
                self.assertIn(frag, line_of(out, "handoff"))
                self.assertEqual(ids(out), ["handoff", "clean", "pushed"])

    def test_handoff_rules_surface_in_gate(self):  # HD4
        self.build()
        for over, frag in ((dict(resume="Resume wrongly."), "resume: expected '"), (dict(role="nobody"), "role: must be one of"),
                           (dict(ledger=".strict-delivery/state/plans/other/ledger.md"), "ledger: expected '%s'" % LEDGER),
                           (dict(grant="x"), "grant: must be null or 'pr=<n> head=<40 hex>'"),
                           (dict(plan="docs/x.md"), "plan: must be docs/strict-delivery/plans/<name>.md")):
            with self.subTest(over=sorted(over)):
                self.put(HANDOFF, "---\n" + yamlsub.emit(dict(self.row, **over)) + "---\n")
                out, _ = self.chk()
                self.assertIn(frag, line_of(out, "handoff"))

    def test_slug_must_equal_plan_slug(self):  # FL7, D-Q1
        self.build()
        other = "%s/%s/handoff.md" % (PS, "other-plan")
        self.put(other, "---\n" + yamlsub.emit(self.row) + "---\n")
        out, _ = self.chk(slug="other-plan")
        self.assertEqual(line_of(out, "handoff"), "FAIL checkpoint.handoff: plan: names %s, not other-plan" % SLUG)

    def test_handoff_errors_order_and_count(self):  # HD5, D-Q15
        self.build()
        self.put(HANDOFF, "---\n" + yamlsub.emit(dict(self.row, resume="bad", grant=5)) + "---\n")
        out, _ = self.chk()
        self.assertEqual(out.count("FAIL checkpoint.handoff:"), 1)
        reason = line_of(out, "handoff")
        self.assertIn("; ", reason)
        self.assertLess(reason.index("grant"), reason.index("resume: expected"))  # schema errors, then rules

    def test_all_digit_sha_needs_quotes(self):  # HD7
        self.build()
        text = "---\n" + yamlsub.emit(self.row) + "---\n"
        text = re.sub(r"(?m)^base: .*$", "base: 3094724", text)
        self.put(HANDOFF, text)
        out, _ = self.chk()
        self.assertIn("base: must be 7 to 40 lowercase hex digits", line_of(out, "handoff"))
        self.put(HANDOFF, re.sub(r"(?m)^base: .*$", 'base: "3094724"', text))
        out, _ = self.chk()
        self.assertNotIn("base:", line_of(out, "handoff"))

    def test_handoff_digit_limits_same_on_both(self):  # HD9, V1
        self.build()
        for n, ok in ((600, True), (1000, True), (1001, False)):
            self.put(HANDOFF, re.sub(r"(?m)^rulings: .*$", "rulings: " + "9" * n, "---\n" + yamlsub.emit(self.row) + "---\n"))
            out, _ = self.chk()
            if not ok:
                self.assertIn("integer too large", line_of(out, "handoff"))
            else:
                self.assertEqual(line_of(out, "handoff"), "PASS checkpoint.handoff")

    def test_real_handoff_roundtrip_through_emit(self):  # PC2
        self.build()
        from gates.lib import checkpoints
        text = open(os.path.join(self.root, *HANDOFF.split("/")), encoding="utf-8").read()
        self.assertEqual(checkpoints.parse_handoff(text), self.row)

    def test_ledger_file_kinds(self):  # FL4, LG2
        self.build()
        path = os.path.join(self.root, *LEDGER.split("/"))
        os.unlink(path)
        out, _ = self.chk()
        self.assertEqual(line_of(out, "ledger"), "FAIL checkpoint.ledger: %s: missing" % LEDGER)
        self.assertEqual(ids(out), ["handoff", "ledger", "head", "clean", "pushed", "reads", "worktrees"] + ["records", "base", "files"])
        os.mkdir(path)
        out, _ = self.chk()
        self.assertIn("is not a regular file", line_of(out, "ledger"))
        os.rmdir(path)
        for data, frag in ((b"\xff", "not valid UTF-8"), (b"", "first line: expected '<!-- schema: ledger/1 -->'"),
                           (b"\xef\xbb\xbf" + LH.encode() + b"x\n", "first line: expected"),
                           (LH.replace("\n", "\r\n").encode() + b"x\r\n", "first line: expected")):
            self.put(LEDGER, data)
            out, _ = self.chk()
            self.assertIn(frag, line_of(out, "ledger"))

    def test_ledger_path_must_match(self):  # FL5
        self.build()
        for bad in ("../../x.md", "/etc/passwd", ".strict-delivery/state/plans/other/ledger.md"):
            self.put(HANDOFF, "---\n" + yamlsub.emit(dict(self.row, ledger=bad)) + "---\n")
            out, _ = self.chk()
            self.assertIn("ledger: expected '%s'" % LEDGER, line_of(out, "handoff"))

    def test_plan_text_unreadable(self):  # FL6, D-Q3
        self.build()
        self.rewrite(head=self.base[:7], resume=resume_text(PLAN, "P1.2", "block/p1", self.base[:7]))  # the plan is not in that commit
        out, _ = self.chk()
        self.assertEqual(line_of(out, "ledger"), "FAIL checkpoint.ledger: plan text: %s is absent at %s" % (PLAN, self.base[:7]))

    def test_plan_text_head_entry_kinds(self):  # 5b.3 F14: a non-regular plan at the handoff head is a reason, never "is absent at"
        self.build()
        for kind, mode in BAD_KINDS:
            with self.subTest(kind):
                head = set_entry(self.root, "refs/heads/side", PLAN, kind, "## Block P1: basic\n")[:7]
                self.rewrite(head=head, resume=resume_text(PLAN, "P1.2", "block/p1", head))
                out, _ = self.chk()
                self.assertEqual(line_of(out, "ledger"), "FAIL checkpoint.ledger: plan text: %s" % refusal(head, PLAN))
        with self.subTest("regular"):
            head = set_entry(self.root, "refs/heads/side", PLAN, "regular", "## Block P1: basic\n")[:7]
            self.rewrite(head=head, resume=resume_text(PLAN, "P1.2", "block/p1", head))
            self.assertNotIn("plan text", line_of(self.chk()[0], "ledger"))

    def test_plan_text_read_at_checkpoint_head(self):  # LG6, D-Q3 (a)
        self.build(lines=["Prose.", CK, "MERGED pr=3 head=%s merge=%s merged_by=a at=2026-11-02T08:59:36Z final=no stream=a block=P2 approval=host" % ("a" * 40, "b" * 40)])
        out, _ = self.chk()
        self.assertIn("block P2 has no block heading", line_of(out, "ledger"))
        self.put(PLAN, "## Block P1: basic\n## Block P2: later\n")  # edited after head: not read
        commit_all(self.root, "plan edit")
        self.push()
        out, _ = self.chk()
        self.assertIn("block P2 has no block heading", line_of(out, "ledger"))

    def test_ledger_from_after_last_checkpoint(self):  # AG1, AG6, LG5; plan :2580
        self.build()
        out_ok, _ = self.chk()
        self.assertIn("PASS checkpoint.agree", out_ok)
        self.rewrite(ledger_from=3)
        out_earlier, _ = self.chk()
        self.assertIn("FAIL checkpoint.agree", out_earlier)

    def test_ledger_headingless_block_fails_ledger(self):  # LG5; plan :2581
        merged = "MERGED pr=3 head=%s merge=%s merged_by=a at=2026-11-02T08:59:36Z final=no stream=a block=1c approval=host" % ("a" * 40, "b" * 40)
        self.build(lines=["Prose.", CK, merged])
        out, _ = self.chk()
        self.assertIn("FAIL checkpoint.ledger", out)
        self.assertEqual(line_of(out, "ledger"), "FAIL checkpoint.ledger: line 4: block 1c has no block heading")
        self.assertNotIn("checkpoint.agree", out)

    def test_ledger_block_heading_from_plan(self):  # LG5
        merged = "MERGED pr=3 head=%s merge=%s merged_by=a at=2026-11-02T08:59:36Z final=no stream=a block=P1 approval=host" % ("a" * 40, "b" * 40)
        self.build(lines=["Prose.", CK, merged])
        out, _ = self.chk()
        self.assertEqual(out, ALL_EIGHT + FAKE_MERGE_FAIL + NEW_PASS)  # P3.1: the fake merge sha is now checked against git
        nob = "MERGED pr=3 head=%s merge=%s merged_by=a at=2026-11-02T08:59:36Z final=no approval=host" % ("a" * 40, "b" * 40)
        self.put(LEDGER, LH + "Prose.\n" + CK.replace("{H}", self.h7) + "\n" + nob + "\n")
        commit_all(self.root, "l")
        self.push()
        self.assertEqual(self.chk()[0], ALL_EIGHT + FAKE_MERGE_FAIL + NEW_PASS)

    def test_ledger_needs_a_checkpoint_line(self):  # LG3
        for lines in ([], ["prose only"], ["CHECKPOINT x"]):
            with self.subTest(lines=lines):
                fx = type(self)("test_ledger_needs_a_checkpoint_line")
                fx.setUp()
                try:
                    fx.build(lines=lines, row={"ledger_from": 2})
                    out, _ = fx.chk()
                    self.assertIn("no conforming CHECKPOINT line", line_of(out, "ledger"))
                    self.assertNotIn("checkpoint.agree", out)
                finally:
                    fx.doCleanups()
        fx = type(self)("test_ledger_needs_a_checkpoint_line")
        fx.setUp()
        try:
            fx.build(lines=["CHECKPOINT x"], row={"ledger_from": 2})
            out, _ = fx.chk()
            self.assertEqual(line_of(out, "ledger").count("line 2: 'CHECKPOINT' line does not match"), 1)
        finally:
            fx.doCleanups()

    def test_ledger_real_size(self):  # LG10: a ledger of the real one's size is read once and checked at once
        self.build(lines=["Prose line number %d with some words to make it long enough to resemble a real one" % i for i in range(700)] + [CK],
                   row={"ledger_from": 703})
        out, _ = self.chk()
        self.assertEqual(out, ALL)

    def test_ledger_errors_reported(self):  # LG4
        self.build(lines=["Ruling (x): a -- b -- c -- d", CK])
        out, _ = self.chk()
        self.assertTrue(line_of(out, "ledger").startswith("FAIL checkpoint.ledger: line 2: 'Ruling' line does not match "), out)

    def test_ledger_gate_passes_no_stream_ids(self):  # LG7
        merged = "MERGED pr=3 head=%s merge=%s merged_by=a at=2026-11-02T08:59:36Z final=no stream=zz block=P1 approval=host" % ("a" * 40, "b" * 40)
        self.build(lines=["Prose.", CK, merged])
        self.assertEqual(self.chk()[0], ALL_EIGHT + FAKE_MERGE_FAIL + NEW_PASS)

    def test_ledger_cross_line_rules_surface(self):  # LG8
        m = "MERGED pr=3 head=%s merge=%s merged_by=a at=%s final=%s approval=host" % ("a" * 40, "b" * 40, "%s", "%s")
        self.build(lines=["Prose.", CK, m % ("2026-11-02T08:59:36Z", "yes"), m % ("2026-13-02T08:59:36Z", "yes")])
        out, _ = self.chk()
        reason = line_of(out, "ledger")
        for frag in ("line 5: pr 3 recorded twice", "line 5: at 2026-13-02T08:59:36Z is not a valid UTC time", "line 5: final=yes after a final line"):
            self.assertIn(frag, reason)

    def test_open_and_closed_lines_are_prose(self):  # LG9, DC7
        self.build(lines=["Open: handoff/ledger producer declaration waits for B and C to merge", CK,
                          "Closed: handoff/ledger producer declared at abcdef1"])
        self.assertEqual(self.chk()[0], ALL)

    def test_last_checkpoint_green(self):  # LG11, D-Q4
        for tail, frag in (("tests=3/5 gates=PASS", "line 3: last CHECKPOINT is not green (tests=3/5 gates=PASS)"),
                           ("tests=5/5 gates=n/a", "line 3: last CHECKPOINT is not green (tests=5/5 gates=n/a)"),
                           ("tests=0/0 gates=PASS", "line 3: last CHECKPOINT is not green (tests=0/0 gates=PASS)")):
            with self.subTest(tail=tail):
                fx = type(self)("test_last_checkpoint_green")
                fx.setUp()
                try:
                    fx.build(lines=["Prose.", "CHECKPOINT P1 P1.1 head={H} " + tail + " next=P1.2"])
                    out, _ = fx.chk()
                    self.assertEqual(line_of(out, "ledger"), "FAIL checkpoint.ledger: " + frag)
                finally:
                    fx.doCleanups()
        self.build(lines=["Prose.", "CHECKPOINT P1 P1.0 head={H} tests=3/5 gates=n/a next=P1.1", CK], row={"ledger_from": 5})
        self.assertEqual(self.chk()[0], ALL)  # only the last line must be green

    def test_agree_block_differs(self):  # AG2
        for block in ("p1", "P", "P1x", "1a"):
            with self.subTest(block=block):
                fx = type(self)("test_agree_block_differs")
                fx.setUp()
                try:
                    fx.build(row={"block": block})
                    out, _ = fx.chk()
                    self.assertEqual(line_of(out, "agree"), "FAIL checkpoint.agree: block: ledger line 3 has P1, handoff has %s" % block)
                finally:
                    fx.doCleanups()

    def test_next_task_disagreement_fails(self):  # AG3; plan :2566
        self.build(row={"next_task": "P1.9", "resume": resume_text(PLAN, "P1.9", "block/p1", "{H}")})
        self.row["resume"] = resume_text(PLAN, "P1.9", "block/p1", self.h7)
        self.rewrite()
        out, _ = self.chk()
        self.assertIn("FAIL checkpoint.agree", out)
        self.assertEqual(line_of(out, "agree"), "FAIL checkpoint.agree: next: ledger line 3 has P1.2, handoff next_task is P1.9")

    def test_next_task_with_space_cannot_agree(self):  # AG3, D-Q5
        self.build()
        self.rewrite(next_task="P1.2 and more", resume=resume_text(PLAN, "P1.2 and more", "block/p1", self.h7))
        out, _ = self.chk()
        self.assertIn("FAIL checkpoint.agree: next: ", out)

    def test_ledger_from_rules(self):  # AG6
        self.build(lines=["Prose.", "CHECKPOINT P1 P1.0 head={H} tests=5/5 gates=PASS next=P1.1", "More prose.", CK, "Tail prose."])
        for value, ok in ((6, True), (3, False), (4, False), (5, False), (7, False), (2, False), (400, False)):
            with self.subTest(ledger_from=value):
                self.rewrite(ledger_from=value)
                out, _ = self.chk()
                if ok:
                    self.assertEqual(line_of(out, "agree"), "PASS checkpoint.agree")
                else:
                    self.assertEqual(line_of(out, "agree"), "FAIL checkpoint.agree: ledger_from: %d is not 6 (the line after the last CHECKPOINT line, 5)" % value)

    def test_agree_uses_last_checkpoint_line(self):  # AG7
        self.build(lines=["Prose.", CK.replace("P1.1", "P1.0").replace("next=P1.2", "next=other"), CK], row={"ledger_from": 5})
        self.assertEqual(line_of(self.chk()[0], "agree"), "PASS checkpoint.agree")
        self.put(LEDGER, LH + "Prose.\n" + CK.replace("{H}", self.h7) + "\n" + CK.replace("{H}", self.h7).replace("next=P1.2", "next=other") + "\n")
        commit_all(self.root, "l")
        self.push()
        self.rewrite(ledger_from=5)
        self.assertIn("FAIL checkpoint.agree: next:", self.chk()[0])

    def test_agree_ignores_nonconforming_checkpoint(self):  # AG9
        self.build(lines=["Prose.", CK, "CHECKPOINT bad line"])
        out, _ = self.chk()
        self.assertIn("FAIL checkpoint.ledger: line 4: 'CHECKPOINT' line does not match", out)

    def test_agree_not_printed_when_ledger_fails(self):  # AG11, D-Q2
        self.build(lines=["Prose.", CK, "CHECKPOINT bad line"])
        out, _ = self.chk()
        self.assertEqual(ids(out), ["handoff", "ledger", "head", "clean", "pushed", "reads", "worktrees"] + NEW)

    def test_agree_digit_limits_same_on_both(self):  # AG10, V1
        n = "9" * 600
        self.build(lines=["Prose.", "CHECKPOINT P1 P1.1 head={H} tests=%s/%s gates=PASS next=P1.2" % (n, n)])
        self.assertEqual(self.chk()[0], ALL)
        m = "9" * 601
        self.put(LEDGER, LH + "Prose.\nCHECKPOINT P1 P1.1 head=%s tests=%s/%s gates=PASS next=P1.2\n" % (self.h7, m, m))
        commit_all(self.root, "l")
        self.push()
        out, _ = self.chk()
        self.assertIn("'CHECKPOINT' line does not match", line_of(out, "ledger"))


class Branch(Fx):
    def test_detached_head_fails(self):  # HE8; plan :2570
        self.build()
        git(self.root, "checkout", "-q", "--detach")
        out, _ = self.chk()
        self.assertIn("FAIL checkpoint.head", out)
        self.assertIn("detached", line_of(out, "head"))
        self.assertEqual(line_of(out, "head"), "FAIL checkpoint.head: HEAD is detached; the handoff names branch block/p1")
        self.assertEqual(line_of(out, "pushed"), "FAIL checkpoint.pushed: HEAD is detached, no branch to push")  # PU8

    def test_branch_differs_fails(self):  # HE7
        self.build()
        git(self.root, "checkout", "-q", "-b", "block/p1x")
        out, _ = self.chk()
        self.assertEqual(line_of(out, "head"), "FAIL checkpoint.head: branch: the handoff names block/p1, HEAD is on block/p1x")

    def test_branch_equal_with_same_named_tag(self):  # HE9, D-Q6
        self.build()
        git(self.root, "tag", "block/p1")
        self.assertEqual(line_of(self.chk()[0], "head"), "PASS checkpoint.head")

    def test_linked_worktree_right_branch(self):  # HE6, PU15
        self.build()
        git(self.root, "checkout", "-q", "--detach")
        w = os.path.join(self.tmp, "lw")
        git(self.root, "worktree", "add", "-q", w, "block/p1")
        out, code = self.chk(root=w)
        self.assertEqual(out, ALL, out)

    def test_head_not_ancestor_fails(self):  # HE3, HE13
        self.build()
        git(self.root, "checkout", "-q", "-b", "side", self.base)
        self.put("s.txt")
        side = commit_all(self.root, "side")
        git(self.root, "checkout", "-q", "block/p1")
        self.rewrite(head=side[:7], resume=resume_text(PLAN, "P1.2", "block/p1", side[:7]))
        out, _ = self.chk()
        self.assertEqual(line_of(out, "head"), "FAIL checkpoint.head: head: %s is not an ancestor of HEAD %s" % (side[:7], git(self.root, "rev-parse", "HEAD")))

    def test_head_two_reasons(self):  # HE12, D-Q15
        self.build()
        git(self.root, "checkout", "-q", "-b", "side", self.base)
        self.put("s.txt")
        side = commit_all(self.root, "side")
        git(self.root, "checkout", "-q", "block/p1")
        self.rewrite(head=side[:7], resume=resume_text(PLAN, "P1.2", "block/p1", side[:7]))
        git(self.root, "checkout", "-q", "-b", "other")
        out, _ = self.chk()
        self.assertEqual(out.count("FAIL checkpoint.head:"), 1)
        self.assertEqual(line_of(out, "head"), "FAIL checkpoint.head: branch: the handoff names block/p1, HEAD is on other; head: "
                         "%s is not an ancestor of HEAD %s" % (side[:7], git(self.root, "rev-parse", "HEAD")))

    def test_head_ref_named_like_a_prefix(self):  # HE5, D-Q10 (a): git reads a ref name before a hex prefix; a stated limit
        self.build()
        git(self.root, "checkout", "-q", "-b", "side", self.base)
        self.put("s.txt")
        side = commit_all(self.root, "side")
        git(self.root, "checkout", "-q", "block/p1")
        git(self.root, "branch", self.h7, side)  # a branch named like the recorded head, pointing elsewhere
        out, _ = self.chk()
        self.assertEqual(subprocess.run(["git", "-C", self.root, "merge-base", "--is-ancestor", self.c1, "HEAD"]).returncode, 0)
        self.assertTrue(line_of(out, "head").startswith("FAIL checkpoint.head: head: %s is not an ancestor of HEAD" % self.h7), line_of(out, "head"))

    def test_long_branch_name(self):  # HE11 (the handoff holds printable ASCII, so a 200-character branch is a string)
        name = "b" * 200
        self.build()
        git(self.root, "checkout", "-q", "-b", name)
        out, _ = self.chk()
        self.assertEqual(line_of(out, "head"), "FAIL checkpoint.head: branch: the handoff names block/p1, HEAD is on %s" % name)

    def test_head_unborn(self):  # HE10, D-Q13
        fresh = os.path.join(self.tmp, "unborn")
        os.mkdir(fresh)
        write_record(fresh, ".strict-delivery/config.yml", minimal_config())
        git(fresh, "init", "-q", "-b", "block/p1")
        self.put(HANDOFF, "---\n" + yamlsub.emit({"schema": "handoff/1"}) + "---\n", root=fresh)
        out, _ = run_main(["check", "checkpoint", "--root", fresh, "--plan", SLUG])
        self.assertEqual(ids(out), ["handoff", "clean", "pushed"])
        self.assertEqual(line_of(out, "pushed"), "FAIL checkpoint.pushed: HEAD has no commit")
        self.assertTrue(line_of(out, "clean").startswith("FAIL checkpoint.clean: uncommitted paths: "))


class Clean(Fx):
    def test_untracked_file_fails_clean(self):  # CL2; plan :2564
        self.build()
        self.put("x.txt")
        out, code = self.chk()
        self.assertIn("FAIL checkpoint.clean: ", out)
        self.assertIn("x.txt", out)
        self.assertEqual(line_of(out, "clean"), "FAIL checkpoint.clean: uncommitted paths: x.txt")
        self.assertEqual(code, 1)

    def test_staged_and_unstaged_fail_clean(self):  # CL3
        self.build()
        self.put("s.txt")
        git(self.root, "add", "s.txt")
        self.put(PLAN, "changed\n")
        self.assertEqual(line_of(self.chk()[0], "clean"), "FAIL checkpoint.clean: uncommitted paths: %s, s.txt" % PLAN)

    def test_ignored_file_passes_clean(self):  # CL4
        self.build()
        self.put(".git/info/exclude", "*.log\n")
        self.put("x.log")
        self.assertEqual(line_of(self.chk()[0], "clean"), "PASS checkpoint.clean")

    def test_dirty_sibling_worktree_passes(self):  # CL5; plan :2562
        self.build()
        w = os.path.join(self.tmp, "w")
        git(self.root, "worktree", "add", "-q", "-b", "wb", w)
        self.put("x", root=w)
        out, _ = self.chk()
        self.assertIn("PASS checkpoint.clean", out)

    def test_clean_lists_every_path(self):  # CL6, D-Q18, OR7
        self.build()
        names = ["a b.txt", "nl\nx.txt", "café.txt"] + ["many/f%d" % i for i in range(200)]
        for n in names:
            self.put(n)
        out, _ = self.chk()
        reason = line_of(out, "clean")
        self.assertIn("a b.txt", reason)
        self.assertIn("nl\\nx.txt", reason)  # escaped once by Result.render
        self.assertIn("caf\u00e9.txt", reason)  # printable in the frozen table: raw
        for i in range(200):
            self.assertIn("many/f%d" % i, reason)

    def test_clean_inside_hook_uses_the_hook_index(self):  # CL7, DP10
        self.build()
        self.put("n.txt")
        alt = os.path.join(self.tmp, "alt-index")
        env = dict(os.environ, GIT_INDEX_FILE=alt)
        subprocess.run(["git", "-C", self.root, "read-tree", "HEAD"], env=env, check=True)
        subprocess.run(["git", "-C", self.root, "add", "n.txt"], env=env, check=True)
        with mock.patch.dict(os.environ, {"GIT_INDEX_FILE": alt}):
            out, _ = self.chk()
        self.assertEqual(line_of(out, "clean"), "FAIL checkpoint.clean: uncommitted paths: n.txt")

    def test_clean_covers_workspace_files(self):  # CL8, D-Q19
        self.build()
        self.put(LEDGER, LH + "changed\n")
        self.assertIn("FAIL checkpoint.clean: uncommitted paths: %s" % LEDGER, self.chk()[0])
        git(self.root, "checkout", "--", LEDGER)
        self.put(".git/info/exclude", "handoff.md\n")  # an ignored workspace file is a documented limit
        self.put(HANDOFF.replace("handoff.md", "handoff.md"), open(os.path.join(self.root, *HANDOFF.split("/"))).read())
        self.assertEqual(line_of(self.chk()[0], "clean"), "PASS checkpoint.clean")

    def test_clean_unmerged_fails(self):  # CL9
        self.build()
        self.put("f.txt", "base\n")
        commit_all(self.root, "f")
        git(self.root, "checkout", "-q", "-b", "side")
        self.put("f.txt", "side\n")
        commit_all(self.root, "side")
        git(self.root, "checkout", "-q", "block/p1")
        self.put("f.txt", "mine\n")
        commit_all(self.root, "mine")
        git(self.root, "merge", "side", check=False)
        self.assertEqual(line_of(self.chk()[0], "clean"), "FAIL checkpoint.clean: uncommitted paths: f.txt")

    def test_clean_git_failure_is_input_fail(self):  # CL10, OR9
        self.build()
        with mock.patch.object(gate_checkpoint.gitinfo, "dirty_paths", side_effect=gate_checkpoint.GateError("git status --porcelain failed (exit 128)")):
            out, code = self.chk()
        self.assertEqual(out, "FAIL checkpoint.input: git status --porcelain failed (exit 128)\n")
        self.assertEqual(code, 1)

    def test_clean_rename_listing(self):  # CL11, D-Q7
        self.build()
        git(self.root, "mv", PLAN, PLAN.replace("2026", "2027"))
        self.assertEqual(line_of(self.chk()[0], "clean"), "FAIL checkpoint.clean: uncommitted paths: %s, %s" % (PLAN, PLAN.replace("2026", "2027")))


class Pushed(Fx):
    def test_unpushed_checkpoint_fails(self):  # PU3, PU4; plan :2576
        self.build()
        pushed_out, _ = self.chk()
        self.put("later.txt")
        c = commit_all(self.root, "after the push")
        out, _ = self.chk()
        self.assertIn("FAIL checkpoint.pushed", out)
        self.assertIn("PASS checkpoint.pushed", pushed_out)
        self.assertEqual(line_of(out, "pushed"), "FAIL checkpoint.pushed: the upstream %s is not HEAD %s; push the checkpoint commit" % (self.c2, c))

    def test_no_remote_passes_pushed_with_reason(self):  # PU1; plan :2578
        self.build(remote=False)
        out, _ = self.chk()
        self.assertIn("PASS checkpoint.pushed", out)
        d = json.loads(run_main(["check", "checkpoint", "--json", "--root", self.root, "--plan", SLUG])[0])
        row = [l for l in d["lines"] if l["id"] == "checkpoint.pushed"][0]
        self.assertEqual(row, {"status": "PASS", "id": "checkpoint.pushed", "reason": "no remote configured"})

    def test_remote_without_upstream_fails(self):  # PU2
        self.build(push=False)
        out, _ = self.chk()
        self.assertEqual(line_of(out, "pushed"), "FAIL checkpoint.pushed: branch block/p1 has no upstream; run git push -u origin block/p1")

    def test_upstream_ahead_fails(self):  # PU5
        self.build()
        self.put("later.txt")
        c = commit_all(self.root, "later")
        self.push()
        git(self.root, "reset", "-q", "--hard", self.c2)
        self.assertEqual(line_of(self.chk()[0], "pushed"), "FAIL checkpoint.pushed: the upstream %s is not HEAD %s; push the checkpoint commit" % (c, self.c2))

    def test_upstream_diverged_fails(self):  # PU6
        self.build()
        self.put("later.txt")
        commit_all(self.root, "later")
        self.push()
        git(self.root, "reset", "-q", "--hard", self.c2)
        self.put("other.txt")
        commit_all(self.root, "other")
        self.assertIn("FAIL checkpoint.pushed: the upstream ", self.chk()[0])

    def test_checkpoint_on_base_branch_fails(self):  # PU7; plan :2590
        self.build()
        git(self.root, "checkout", "-q", "main")
        out, _ = self.chk()
        self.assertIn("FAIL checkpoint.pushed", out)
        self.assertEqual(line_of(out, "pushed"), "FAIL checkpoint.pushed: the current branch main is the base branch; checkpoints are made on a work branch")
        fresh = os.path.join(self.tmp, "norem")  # also with no remote at all
        os.mkdir(fresh)
        make_repo(fresh)
        out, _ = run_main(["check", "checkpoint", "--root", fresh, "--plan", SLUG])
        self.assertEqual(line_of(out, "pushed"), "FAIL checkpoint.pushed: the current branch main is the base branch; checkpoints are made on a work branch")

    def test_pushed_local_upstream(self):  # PU9
        self.build(remote=False)
        git(self.root, "branch", "--set-upstream-to=main")
        self.assertEqual(line_of(self.chk()[0], "pushed"), "PASS checkpoint.pushed")

    def test_pushed_upstream_under_another_name(self):  # PU10, D-Q11 stated limit
        self.build()
        git(self.root, "checkout", "-q", "-b", "newfeat", "origin/block/p1")
        self.row["branch"] = "newfeat"
        self.rewrite(branch="newfeat", resume=resume_text(PLAN, "P1.2", "newfeat", self.h7),
                     worktrees=[{"path": ".", "branch": "newfeat", "head": self.h7, "porcelain": ""}])
        git(self.root, "push", "-q", "origin", "newfeat:newfeat")  # no -u: the upstream stays origin/block/p1
        self.assertEqual(git(self.root, "rev-parse", "@{upstream}"), self.c2)
        self.assertEqual(git(self.root, "rev-parse", "origin/newfeat"), git(self.root, "rev-parse", "HEAD"))
        self.assertIn("FAIL checkpoint.pushed: the upstream", line_of(self.chk()[0], "pushed"))

    def test_pushed_upstream_gone(self):  # PU11
        self.build()
        git(self.root, "push", "-q", "origin", ":block/p1")
        git(self.root, "fetch", "-q", "--prune")
        self.assertIn("has no upstream", line_of(self.chk()[0], "pushed"))

    def test_pushed_two_remotes(self):  # PU12
        self.build()
        other = os.path.join(self.tmp, "fork.git")
        git(self.tmp, "init", "-q", "--bare", "-b", "main", other)
        git(self.root, "remote", "add", "fork", other)
        self.assertEqual(line_of(self.chk()[0], "pushed"), "PASS checkpoint.pushed")

    def test_pushed_remote_without_url(self):  # PU13, D-Q12
        self.build(remote=False)
        git(self.root, "config", "remote.x.fetch", "+refs/heads/*:refs/remotes/x/*")
        self.assertEqual(line_of(self.chk()[0], "pushed"), "FAIL checkpoint.pushed: branch block/p1 has no upstream; run git push -u x block/p1")

    def test_pushed_reads_local_refs_only(self):  # PU14
        self.build()
        calls = []
        real = subprocess.run

        def spy(argv, *a, **kw):
            calls.append(list(argv))
            return real(argv, *a, **kw)
        import shutil
        shutil.rmtree(self.bare)  # the remote is gone: the verdict comes from local refs
        with mock.patch.object(gitinfo.subprocess, "run", spy):
            out, _ = self.chk()
        self.assertEqual(line_of(out, "pushed"), "PASS checkpoint.pushed")
        subs = set()
        for argv in calls:
            i = argv.index("-C") + 2
            subs.add(argv[i])
        self.assertLessEqual(subs, {"symbolic-ref", "rev-parse", "remote", "status", "merge-base", "ls-tree", "cat-file", "config", "ls-files"})
        self.assertFalse(subs & {"fetch", "ls-remote", "push", "pull"})

    def test_pushed_uses_stale_local_ref(self):  # PU16
        self.build()
        clone = os.path.join(self.tmp, "clone")
        git(self.tmp, "clone", "-q", self.bare, clone)
        git(clone, "config", "user.email", "f@example.invalid")
        git(clone, "config", "user.name", "F")
        git(clone, "checkout", "-q", "block/p1")
        self.put("c.txt", root=clone)
        commit_all(clone, "c")
        git(clone, "push", "-q", "origin", "block/p1")
        self.assertEqual(line_of(self.chk()[0], "pushed"), "PASS checkpoint.pushed")


class Reads(Fx):
    def reads(self, entries, files=None):
        self.build(files=files)
        self.rewrite(required_reads=entries)
        self.push()
        return self.chk()[0]

    def test_reads_none(self):  # RD1, D-Q20
        self.build()
        self.assertEqual(line_of(self.chk()[0], "reads"), "PASS checkpoint.reads")
        self.rewrite(required_reads=[])
        self.push()
        self.assertEqual(line_of(self.chk()[0], "reads"), "PASS checkpoint.reads")

    def test_required_read_missing_fails(self):  # RD2; plan :2582
        out = self.reads([{"path": "docs/missing.md", "why": "w"}])
        self.assertIn("FAIL checkpoint.reads", out)
        self.assertIn("docs/missing.md", out)
        self.assertEqual(line_of(out, "reads"), "FAIL checkpoint.reads: docs/missing.md: missing")

    def test_required_read_path_kinds(self):  # RD2, D-Q21
        self.build(files={"docs/a.md": "a\nb\n"})
        os.symlink("a.md", os.path.join(self.root, "docs/lnk.md"))
        os.symlink("gone", os.path.join(self.root, "docs/dang.md"))
        os.mkdir(os.path.join(self.root, "docs/dir"))
        os.mkfifo(os.path.join(self.root, "docs/fifo"))
        os.symlink("docs", os.path.join(self.root, "linkdir"))
        self.put("docs/file", "x")
        entries = [{"path": p, "why": "w"} for p in ("docs/a.md", "docs/lnk.md", "docs/dang.md", "docs/dir", "docs/fifo",
                                                     "linkdir/a.md", "docs/file/x.md")]
        self.rewrite(required_reads=entries)
        out, _ = self.chk()
        reason = line_of(out, "reads")
        self.assertNotIn("docs/a.md:", reason)
        for frag in ("docs/lnk.md: is not a regular file", "docs/dang.md: is not a regular file", "docs/dir: is not a regular file",
                     "docs/fifo: is not a regular file", "linkdir: is a symlink; directories must be real directories",
                     "docs/file: not a directory"):
            self.assertIn(frag, reason)

    def test_reads_line_ranges(self):  # RD3
        self.build(files={"docs/a.md": "a\nb\n"})
        for lines, ok in (("1-3", False), ("1-2", True), ("2-end", True), ("3-end", False), ("1-end", True), ("2-2", True),
                          ("2-1", False), ("1-1", True), ("1-3", False)):
            with self.subTest(lines=lines):
                self.rewrite(required_reads=[{"path": "docs/a.md", "lines": lines, "why": "w"}])
                out, _ = self.chk()
                self.assertEqual(line_of(out, "reads").startswith("PASS"), ok, line_of(out, "reads"))

    def test_reads_line_count_definition(self):  # RD4, D-Q22 (hand-written counts: \n bytes, plus one for an unterminated last line)
        for data, count in ((b"", 0), (b"a", 1), (b"a\n", 1), (b"a\nb", 2), (b"a\nb\n", 2), (b"a\r\nb\r\n", 2),
                            (b"a\rb", 1), (b"a\x0bb\x0cc", 1), ("a b".encode(), 1), (b"\xff\xfe\n\xff", 2), (b"a\x00b\n", 1)):
            with self.subTest(data=data):
                self.assertEqual(gate_checkpoint._line_count(data), count)
                fx = type(self)("test_reads_none")
                fx.setUp()
                try:
                    fx.build(files={"docs/a.md": data})
                    fx.rewrite(required_reads=[{"path": "docs/a.md", "lines": "1-end", "why": "w"}])
                    self.assertEqual(line_of(fx.chk()[0], "reads").startswith("PASS"), count >= 1)
                    fx.rewrite(required_reads=[{"path": "docs/a.md", "lines": "1-%d" % max(count, 1), "why": "w"}])
                    self.assertEqual(line_of(fx.chk()[0], "reads").startswith("PASS"), count >= 1)
                finally:
                    fx.doCleanups()

    def test_reads_empty_file(self):  # RD5
        self.build(files={"docs/e.md": ""})
        self.rewrite(required_reads=[{"path": "docs/e.md", "why": "w"}])
        self.assertEqual(line_of(self.chk()[0], "reads"), "PASS checkpoint.reads")
        self.rewrite(required_reads=[{"path": "docs/e.md", "lines": "1-end", "why": "w"}])
        self.assertEqual(line_of(self.chk()[0], "reads"), "FAIL checkpoint.reads: docs/e.md: lines 1-end: the file has 0 lines")

    def test_reads_binary_and_large_files(self):  # RD6
        self.build(files={"docs/b.bin": b"\x00\xff\xfe\n" * 5, "docs/big.md": b"x\n" * 200000})
        self.rewrite(required_reads=[{"path": "docs/b.bin", "lines": "1-5", "why": "w"},
                                     {"path": "docs/big.md", "lines": "200000-200000", "why": "w"}])
        self.assertEqual(line_of(self.chk()[0], "reads"), "PASS checkpoint.reads")

    def test_unreadable_file_is_a_reason(self):  # "an unreadable file is a reason, never a skip"
        self.build(files={"docs/a.md": "a\n"})
        self.rewrite(required_reads=[{"path": "docs/a.md", "why": "w"}])
        self.push()
        os.chmod(os.path.join(self.root, "docs/a.md"), 0)
        if os.access(os.path.join(self.root, "docs/a.md"), os.R_OK):
            os.chmod(os.path.join(self.root, "docs/a.md"), 0o644)
            self.skipTest("this user reads mode 000 files")
        self.assertEqual(line_of(self.chk()[0], "reads"), "FAIL checkpoint.reads: docs/a.md: cannot read (Permission denied)")
        os.chmod(os.path.join(self.root, "docs/a.md"), 0o644)

    def test_reads_digit_limits_same_on_both(self):  # RD7, V1
        for text, count in (("9" * 600, 5),):
            data = b"x\n" * count
            row = {"path": "docs/a.md", "lines": "1-" + "9" * 600, "why": "w"}
            self.build(files={"docs/a.md": data})
            out = gate_checkpoint._reads(self.root, {"required_reads": [row]})
            self.assertEqual(out, ["docs/a.md: lines 1-%s: need start <= end <= 5 (the file's line count)" % ("9" * 600)])
            out = gate_checkpoint._reads(self.root, {"required_reads": [dict(row, lines="%s-end" % ("9" * 600))]})
            self.assertEqual(out, ["docs/a.md: lines %s-end: the file has 5 lines" % ("9" * 600)])

    def test_reads_not_printed_when_handoff_fails(self):  # RD9
        self.build()
        self.put(HANDOFF, "---\n" + yamlsub.emit(dict(self.row, required_reads=[{"path": "../x", "why": "w"}])) + "---\n")
        out, _ = self.chk()
        self.assertIn("required_reads.0.path: must be a normalised repo-relative path", line_of(out, "handoff"))
        self.assertNotIn("checkpoint.reads", out)

    def test_reads_every_bad_entry_reported(self):  # RD10, D-Q15
        out = self.reads([{"path": "docs/m1.md", "why": "w"}, {"path": "docs/m2.md", "why": "w"}])
        self.assertEqual(out.count("FAIL checkpoint.reads:"), 1)
        self.assertEqual(line_of(out, "reads"), "FAIL checkpoint.reads: docs/m1.md: missing; docs/m2.md: missing")

    def test_reads_untracked_file_passes(self):  # RD11
        self.build()
        self.put(".git/info/exclude", "scratch/\n")
        self.put("scratch/n.md", "a\n")
        self.rewrite(required_reads=[{"path": "scratch/n.md", "why": "w"}])
        self.push()
        self.assertEqual(line_of(self.chk()[0], "reads"), "PASS checkpoint.reads")

    def test_reads_under_symlinked_root(self):  # RD12
        self.build(files={"docs/a.md": "a\n"})
        self.rewrite(required_reads=[{"path": "docs/a.md", "lines": "1-1", "why": "w"}])
        link = os.path.join(self.tmp, "rootlink")
        os.symlink(self.root, link)
        self.assertEqual(line_of(self.chk(root=link)[0], "reads"), "PASS checkpoint.reads")


class Worktrees(Fx):
    def wt(self, *entries):
        base = {"path": ".", "branch": "block/p1", "head": self.h7, "porcelain": ""}
        self.rewrite(worktrees=[base] + list(entries))
        self.push()
        return self.chk()[0]

    def sib(self, name="../w", branch="wb"):
        path = os.path.normpath(os.path.join(self.root, name))
        git(self.root, "worktree", "add", "-q", "-b", branch, path)
        return path

    def test_worktree_head_ancestor_rule(self):  # WT1-WT3; plan :2584
        self.build()
        w = self.sib()
        w_head = git(w, "rev-parse", "HEAD")
        out_ancestor = self.wt({"path": "../w", "branch": "wb", "head": self.c1[:7], "porcelain": ""})
        self.assertIn("PASS checkpoint.worktrees", out_ancestor)
        out_equal = self.wt({"path": "../w", "branch": "wb", "head": w_head[:7], "porcelain": ""})
        self.assertIn("PASS checkpoint.worktrees", out_equal)
        self.put("n.txt", root=w)
        newer = commit_all(w, "newer")
        out_not_ancestor = self.wt({"path": "../w", "branch": "wb", "head": newer[:7], "porcelain": ""})
        self.assertIn("PASS checkpoint.worktrees", out_not_ancestor)  # the recorded head is HEAD itself
        git(w, "reset", "-q", "--hard", self.c1)
        out_not_ancestor = self.wt({"path": "../w", "branch": "wb", "head": newer[:7], "porcelain": ""})
        self.assertIn("FAIL checkpoint.worktrees", out_not_ancestor)
        self.assertEqual(line_of(out_not_ancestor, "worktrees"), "FAIL checkpoint.worktrees: ../w: head %s is not an ancestor of its HEAD %s" % (newer[:7], self.c1))

    def test_root_entry_porcelain_must_be_empty(self):  # WT9; plan :2586
        self.build()
        for porcelain, ok in (("", True), (" M a", False), ("?? x\n", False), ("\n", False), (" ", False)):
            with self.subTest(porcelain=porcelain):
                self.rewrite(worktrees=[{"path": ".", "branch": "block/p1", "head": self.h7, "porcelain": porcelain}])
                self.push()
                out, _ = self.chk()
                self.assertEqual(line_of(out, "worktrees").startswith("PASS"), ok, out)
                if not ok:
                    self.assertEqual(line_of(out, "worktrees"), "FAIL checkpoint.worktrees: .: porcelain: the root entry must be the empty string")

    def test_worktree_branch_differs(self):  # WT4
        self.build()
        self.sib()
        out = self.wt({"path": "../w", "branch": "feat", "head": self.c1[:7], "porcelain": ""})
        self.assertEqual(line_of(out, "worktrees"), "FAIL checkpoint.worktrees: ../w: branch: recorded feat, actual wb")
        out = self.wt({"path": "../w", "branch": None, "head": self.c1[:7], "porcelain": ""})
        self.assertEqual(line_of(out, "worktrees"), "FAIL checkpoint.worktrees: ../w: branch: recorded null (detached), actual wb")

    def test_worktree_null_branch_detached_passes(self):  # WT5
        self.build()
        w = os.path.join(self.tmp, "d")
        git(self.root, "worktree", "add", "-q", "--detach", w)
        out = self.wt({"path": "../d", "branch": None, "head": self.c1[:7], "porcelain": ""})
        self.assertEqual(line_of(out, "worktrees"), "PASS checkpoint.worktrees")
        out = self.wt({"path": "../d", "branch": "wb", "head": self.c1[:7], "porcelain": ""})
        self.assertEqual(line_of(out, "worktrees"), "FAIL checkpoint.worktrees: ../d: branch: recorded wb, actual null (detached)")

    def test_worktree_path_missing(self):  # WT6
        self.build()
        os.makedirs(os.path.join(self.tmp, "afile"), exist_ok=True)
        os.rmdir(os.path.join(self.tmp, "afile"))
        with open(os.path.join(self.tmp, "afile"), "w") as fh:
            fh.write("x")
        os.symlink("nowhere", os.path.join(self.tmp, "dangling"))
        for path, frag in (("../nope", "directory missing"), ("../afile", "not a directory"), ("../dangling", "not a directory")):
            with self.subTest(path=path):
                out = self.wt({"path": path, "branch": None, "head": self.c1[:7], "porcelain": ""})
                if path == "../dangling":
                    frag = "directory missing" if not os.path.lexists(os.path.join(self.tmp, "dangling")) else "not a directory"
                self.assertEqual(line_of(out, "worktrees"), "FAIL checkpoint.worktrees: %s: %s" % (path, frag))

    def test_worktree_directory_not_a_top_level(self):  # WT7
        self.build()
        os.mkdir(os.path.join(self.root, "sub"))
        out = self.wt({"path": "sub", "branch": None, "head": self.c1[:7], "porcelain": ""})
        self.assertEqual(line_of(out, "worktrees"), "FAIL checkpoint.worktrees: sub: not a git top level")
        os.mkdir(os.path.join(self.tmp, "plain"))
        out = self.wt({"path": "../plain", "branch": None, "head": self.c1[:7], "porcelain": ""})
        self.assertEqual(line_of(out, "worktrees"), "FAIL checkpoint.worktrees: ../plain: not a git top level (not a repository)")
        other = os.path.join(self.tmp, "otherrepo")
        os.mkdir(other)
        make_repo(other)
        out = self.wt({"path": "../otherrepo", "branch": "main", "head": git(other, "rev-parse", "HEAD")[:7], "porcelain": ""})
        # WT1 (Task 6K.2, U2): another repository's top level is no worktree of this repository, so this line used to PASS
        self.assertEqual(line_of(out, "worktrees"), "FAIL checkpoint.worktrees: ../otherrepo: not a worktree of this repository")

    def test_worktree_path_forms(self):  # WT8
        self.build()
        w = self.sib()
        os.symlink(w, os.path.join(self.tmp, "wlink"))
        for path in ("../w", "../wlink", "../../%s/w" % os.path.basename(self.tmp)):
            with self.subTest(path=path):
                out = self.wt({"path": path, "branch": "wb", "head": self.c1[:7], "porcelain": ""})
                self.assertEqual(line_of(out, "worktrees"), "PASS checkpoint.worktrees", out)

    def test_other_entry_porcelain_not_compared(self):  # WT10
        self.build()
        w = self.sib()
        self.put("dirty", root=w)
        for porcelain in ("?? dirty\n", "junk", ""):
            out = self.wt({"path": "../w", "branch": "wb", "head": self.c1[:7], "porcelain": porcelain})
            self.assertEqual(line_of(out, "worktrees"), "PASS checkpoint.worktrees")

    def test_worktree_head_not_a_commit(self):  # WT11
        self.build()
        self.sib()
        out = self.wt({"path": "../w", "branch": "wb", "head": "0000000", "porcelain": ""})
        self.assertEqual(line_of(out, "worktrees"), "FAIL checkpoint.worktrees: ../w: head 0000000 is not a commit there")

    def test_worktree_branch_with_same_named_tag(self):  # WT12
        self.build()
        self.sib()
        git(self.root, "tag", "wb")
        out = self.wt({"path": "../w", "branch": "wb", "head": self.c1[:7], "porcelain": ""})
        self.assertEqual(line_of(out, "worktrees"), "PASS checkpoint.worktrees")

    def test_root_entry_matches_handoff(self):  # WT13, D-Q17: checked like any other entry
        self.build()
        self.rewrite(worktrees=[{"path": ".", "branch": "block/p1", "head": self.base[:7], "porcelain": ""}])
        self.push()
        self.assertEqual(line_of(self.chk()[0], "worktrees"), "PASS checkpoint.worktrees")
        self.rewrite(worktrees=[{"path": ".", "branch": "other", "head": self.h7, "porcelain": ""}])
        self.push()
        self.assertEqual(line_of(self.chk()[0], "worktrees"), "FAIL checkpoint.worktrees: .: branch: recorded other, actual block/p1")

    def test_worktrees_many(self):  # WT15
        self.build()
        entries = []
        for i in range(20):
            self.sib("../m%d" % i, "mb%d" % i)
            entries.append({"path": "../m%d" % i, "branch": "mb%d" % i, "head": self.c1[:7], "porcelain": ""})
        self.assertEqual(line_of(self.wt(*entries), "worktrees"), "PASS checkpoint.worktrees")

    def test_worktrees_every_bad_entry_reported(self):  # WT17, D-Q15
        self.build()
        self.sib("../w1", "w1")
        self.sib("../w2", "w2")
        out = self.wt({"path": "../w1", "branch": "x", "head": self.c1[:7], "porcelain": ""},
                      {"path": "../w2", "branch": "y", "head": self.c1[:7], "porcelain": ""},
                      {"path": "../w3", "branch": "z", "head": self.c1[:7], "porcelain": ""})
        self.assertEqual(out.count("FAIL checkpoint.worktrees:"), 1)
        self.assertEqual(line_of(out, "worktrees"), "FAIL checkpoint.worktrees: ../w1: branch: recorded x, actual w1; "
                         "../w2: branch: recorded y, actual w2; ../w3: directory missing")

    def test_worktree_unborn_entry(self):  # WT18
        self.build()
        u = os.path.join(self.tmp, "unb")
        os.mkdir(u)
        git(u, "init", "-q", "-b", "main")
        out = self.wt({"path": "../unb", "branch": "main", "head": self.c1[:7], "porcelain": ""})
        # Task 6K.2 (row WT1, like U2): a separate repository, even an unborn one, is no worktree of this repository
        self.assertEqual(line_of(out, "worktrees"), "FAIL checkpoint.worktrees: ../unb: not a worktree of this repository")


class Output(Fx):
    def test_failure_keeps_line_order(self):  # OR4
        self.build()
        self.rewrite(head="0000000", resume=resume_text(PLAN, "P1.2", "block/p1", "0000000"))
        self.put("x.txt")
        out, _ = self.chk()
        self.assertEqual(ids(out), ["handoff", "ledger", "head", "clean", "pushed", "reads", "worktrees"] + NEW)

    def test_exit_codes(self):  # OR5
        self.build()
        self.assertEqual(self.chk()[1], 0)
        self.put("x")
        self.assertEqual(self.chk()[1], 1)
        from gates.lib.result import Result
        self.assertFalse(Result("checkpoint").ok())  # no line is never a pass
        with mock.patch.object(gate_checkpoint, "check", return_value=Result("checkpoint")), \
                contextlib.redirect_stdout(io.StringIO()) as buf:
            self.assertEqual(gate_checkpoint.main(["--root", self.root, "--plan", SLUG]), 1)
        self.assertEqual(buf.getvalue(), "FAIL checkpoint.empty: the gate produced no lines\n")

    def test_json_output(self):  # OR6
        self.build()
        self.put("a\nb.txt")
        d = json.loads(run_main(["check", "checkpoint", "--json", "--root", self.root, "--plan", SLUG])[0])
        self.assertIs(d["ok"], False)
        clean = [l for l in d["lines"] if l["id"] == "checkpoint.clean"][0]
        self.assertEqual(clean["reason"], "uncommitted paths: a\nb.txt")

    def test_output_escaping_same_on_both(self):  # OR7, V2
        require_both_pys(self)
        self.build()
        for n in ("uࡰ.txt", "e\U0001fae8.txt", "n b.txt", "t .txt", "c\u0085.txt", "back\\slash.txt"):
            self.put(n)
        outs = []
        for py in PYS:
            p = subprocess.run([py, "-m", "gates", "check", "checkpoint", "--root", self.root, "--plan", SLUG], cwd=REPO,
                               capture_output=True)
            outs.append(p.stdout)
        self.assertEqual(outs[0], outs[1])
        text = outs[0].decode("utf-8")
        for frag in ("u\\u0870.txt", "e\\U0001fae8.txt", "n\\xa0b.txt", "t\\u2028.txt", "c\\x85.txt", "back\\\\slash.txt"):
            self.assertIn(frag, text)

    def test_unexpected_exception_is_input_fail(self):  # OR9
        self.build()
        with mock.patch.object(gate_checkpoint.gitinfo, "dirty_paths", side_effect=RuntimeError("boom")):
            out, code = self.chk()
        self.assertEqual(out, "FAIL checkpoint.input: RuntimeError: boom\n")
        self.assertEqual(code, 1)

    def test_exception_groups(self):  # OR10, V3
        if not hasattr(__builtins__ if isinstance(__builtins__, dict) else __builtins__, "ExceptionGroup"):
            self.skipTest("ExceptionGroup does not exist on this interpreter (3.9)")
        import builtins
        self.build()
        eg = builtins.ExceptionGroup("x", [ValueError("v")])
        with mock.patch.object(gate_checkpoint.gitinfo, "dirty_paths", side_effect=eg):
            out, _ = self.chk()
        self.assertTrue(out.startswith("FAIL checkpoint.input: ExceptionGroup: "), out)
        beg = builtins.BaseExceptionGroup("x", [KeyboardInterrupt()])
        with mock.patch.object(gate_checkpoint.gitinfo, "dirty_paths", side_effect=beg):
            with self.assertRaises(builtins.BaseExceptionGroup):
                self.chk()

    def test_subprocess_run_same_on_both(self):  # OR11
        require_both_pys(self)
        self.build()
        self.put("x.txt")
        outs = []
        for py in PYS:
            p = subprocess.run([py, "-m", "gates", "check", "checkpoint", "--root", self.root, "--plan", SLUG], cwd=REPO,
                               capture_output=True)
            outs.append((p.returncode, p.stdout, p.stderr))
        self.assertEqual(outs[0], outs[1])
        self.assertEqual(outs[0][0], 1)
        want = ALL.replace("PASS checkpoint.clean\n", "FAIL checkpoint.clean: uncommitted paths: x.txt\n").encode()
        self.assertEqual(outs[0][1], want)
        self.assertEqual(run_main(["check", "checkpoint", "--root", self.root, "--plan", SLUG])[0].encode(), want)

    def test_unicode_version_independent(self):  # V2: a handoff branch with a non-ASCII name fails handoff_errors first
        self.build()
        self.put(HANDOFF, "---\n" + yamlsub.emit(dict(self.row, branch="bࡰ")) + "---\n")
        out, _ = self.chk()
        self.assertIn("branch: ", line_of(out, "handoff"))
        self.assertNotIn("checkpoint.head", out)


NOTE = "%s/%s/note.md" % (PS, SLUG)  # a path under the plan's workspace: a pull request of this plan touches one
PFX = "%s/%s/" % (PS, SLUG)


def mline(pr, head, merge, approval="chat", apr=None, ahead=None):
    """A ``MERGED`` ledger line spelled from the grammar of Task P1.2 (a chat line names its own pr and head)."""
    tail = ("approval=chat pr=%s head=%s words=merge it" % (pr if apr is None else apr, head if ahead is None else ahead)
            if approval == "chat" else "approval=host")
    return ("MERGED pr=%s head=%s merge=%s merged_by=owner at=2026-11-18T10:00:00Z final=no stream=a block=P1 %s"
            % (pr, head, merge, tail))


def no_parent(m):
    return "%s has no parents (a root commit, or the clone is shallow); update main from the remote" % m


class MergesFx(Fx):
    """Task P3.1: ``checkpoint.merges`` on a repository in controller mode whose ``main`` holds real pull request merges."""
    CFG = dict(minimal_config(), merge={"mode": "controller"})

    def pr_merge(self, name, files, how="no-ff"):
        """A branch off ``main`` writing ``files``, merged into ``main`` (call before ``build``); ``(head, main tip)``."""
        r = self.root
        git(r, "checkout", "-q", "-b", name, "main")
        for rel, text in files.items():
            self.put(rel, text)
        head = commit_all(r, "work " + name)
        git(r, "checkout", "-q", "main")
        if how == "no-ff":
            git(r, "merge", "-q", "--no-ff", "-m", "Merge " + name, name)
        elif how == "ff":
            git(r, "merge", "-q", "--ff-only", name)
        elif how == "squash":
            git(r, "merge", "-q", "--squash", name)
            git(r, "commit", "-q", "-m", "squash " + name)
        return head, git(r, "rev-parse", "HEAD")

    def reledger(self, lines):
        """Replace the ledger by the prose line, the checkpoint line and ``lines``; commit and push."""
        self.put(LEDGER, LH + "Prose line.\n" + CK.replace("{H}", self.h7) + "\n" + "".join(l + "\n" for l in lines))
        commit_all(self.root, "ledger")
        self.push()

    def merges(self, out):
        return line_of(out, "merges")


class Merges(MergesFx):
    def test_checkpoint_checks_merged_lines(self):  # CM1, CM2, CM20; plan :2943-2944
        head, m = self.pr_merge("w1", {NOTE: "x\n"})
        self.build()
        good_out, code = self.chk()
        self.assertEqual((good_out, code), (ALL, 0))  # no MERGED line: PASS
        self.reledger([mline(7, head, m)])
        good_out, code = self.chk()
        self.assertEqual((good_out, code), (ALL, 0))  # one good chat line in controller mode
        self.assertIn("PASS checkpoint.merges", good_out)
        self.reledger([mline(7, "c" * 40, m)])
        bad_out, code = self.chk()
        self.assertEqual(code, 1)
        self.assertEqual(self.merges(bad_out), "FAIL checkpoint.merges: head.7: the second parent of %s is %s, not the "
                         "recorded head %s" % (m, head, "c" * 40))
        self.assertEqual(ids(bad_out), ALL14)

    def test_merges_printed_last_after_worktrees(self):  # CM20
        head, m = self.pr_merge("w1", {NOTE: "x\n"})
        self.build(lines=["Prose.", CK, mline(7, head, m)])
        out, _ = self.chk()
        self.assertEqual(ids(out)[-7:-5], ["worktrees", "merges"])

    def test_merges_merge_not_a_commit(self):  # CM4
        head, m = self.pr_merge("w1", {NOTE: "x\n"})
        self.build(lines=["Prose.", CK, mline(7, head, "d" * 40)])
        out, _ = self.chk()
        self.assertEqual(self.merges(out), "FAIL checkpoint.merges: merge.7: %s is not a commit in this repository; "
                         "update main from the remote" % ("d" * 40))

    def test_merges_squash_refused(self):  # CM5 (a fast-forward too; the octopus merge is MG6 of test_merge_lib.py)
        for how in ("squash", "ff"):
            with self.subTest(how=how):
                fx = type(self)("test_merges_squash_refused")
                fx.setUp()
                try:
                    head, m = fx.pr_merge("w1", {NOTE: "x\n"}, how=how)
                    fx.build(lines=["Prose.", CK, mline(7, head, m)])
                    out, _ = fx.chk()
                    self.assertEqual(fx.merges(out), "FAIL checkpoint.merges: merge.7: %s has 1 parent(s), and a pull request "
                                     "merge commit has exactly two (a squash, a rebase or an octopus merge is refused)" % m)
                finally:
                    fx.doCleanups()

    def test_merges_shallow_clone(self):  # CM6: a commit with no parents, which is what a shallow clone shows (MG31)
        head, m = self.pr_merge("w1", {NOTE: "x\n"})
        self.build(lines=["Prose.", CK, mline(7, head, m)])
        root_commit = git(self.root, "rev-list", "--max-parents=0", "main")
        self.reledger([mline(7, head, root_commit)])
        out, _ = self.chk()
        self.assertEqual(self.merges(out), "FAIL checkpoint.merges: merge.7: " + no_parent(root_commit))

    def test_merges_off_first_parent(self):  # CM7
        r = self.root
        git(r, "checkout", "-q", "-b", "inner", "main")
        self.put(NOTE, "i\n")
        inner = commit_all(r, "inner")
        git(r, "checkout", "-q", "-b", "outer", "main")
        self.put("o.txt", "o\n")
        commit_all(r, "outer")
        git(r, "merge", "-q", "--no-ff", "-m", "inner into outer", "inner")
        m1 = git(r, "rev-parse", "HEAD")
        git(r, "checkout", "-q", "main")
        git(r, "merge", "-q", "--no-ff", "-m", "outer", "outer")
        self.build(lines=["Prose.", CK, mline(7, inner, m1)])
        out, _ = self.chk()
        self.assertEqual(self.merges(out), "FAIL checkpoint.merges: merge.7: %s is not on the first-parent history of "
                         "main; update main from the remote" % m1)

    def test_merges_base_branch_missing(self):  # CM8
        head, m = self.pr_merge("w1", {NOTE: "x\n"})
        self.build(lines=["Prose.", CK, mline(7, head, m)])
        git(self.root, "branch", "-m", "main", "trunk")
        out, _ = self.chk()
        self.assertEqual(self.merges(out), "FAIL checkpoint.merges: merge.7: main is not a local branch; update main "
                         "from the remote")

    def test_merges_head_mismatch(self):  # CM10
        head, m = self.pr_merge("w1", {NOTE: "x\n"})
        other = "e" * 40
        self.build(lines=["Prose.", CK, mline(7, other, m)])
        out, _ = self.chk()
        self.assertEqual(self.merges(out), "FAIL checkpoint.merges: head.7: the second parent of %s is %s, not the "
                         "recorded head %s" % (m, head, other))

    def test_merges_code_only_pr_fails(self):  # CM11: a code-only PR, and a merge that touched another plan's workspace
        for files in ({"code.py": "x = 1\n"}, {PS + "/other/ledger.md": "l\n"}):
            with self.subTest(files=list(files)):
                fx = type(self)("test_merges_code_only_pr_fails")
                fx.setUp()
                try:
                    head, m = fx.pr_merge("w1", files)
                    fx.build(lines=["Prose.", CK, mline(7, head, m)])
                    out, _ = fx.chk()
                    self.assertEqual(fx.merges(out), "FAIL checkpoint.merges: plan.7: the merge %s changes no path under "
                                     "%s: it is not a pull request of plan %s" % (m, PFX, SLUG))
                finally:
                    fx.doCleanups()

    def test_merges_approval_mode(self):  # CM12
        head, m = self.pr_merge("w1", {NOTE: "x\n"})
        self.build(lines=["Prose.", CK, mline(7, head, m, approval="host")])
        out, _ = self.chk()
        self.assertEqual(self.merges(out), "FAIL checkpoint.merges: approval.7: approval is host, and merge.mode "
                         "controller needs chat")
        for kw, what in (({"apr": 8}, "pr"), ({"ahead": "f" * 40}, "head"), ({"apr": 8, "ahead": "f" * 40}, "pr and head")):
            with self.subTest(what=what):
                self.reledger([mline(7, head, m, **kw)])
                out, _ = self.chk()
                self.assertEqual(self.merges(out), "FAIL checkpoint.merges: approval.7: the chat approval names another "
                                 "%s than the line's pr and head" % what)

    def test_merges_rule_order(self):  # CM13: head, plan, approval on one line; a failing merge shows merge and approval
        head, m = self.pr_merge("w1", {"code.py": "x\n"})
        other = "e" * 40
        self.build(lines=["Prose.", CK, mline(7, other, m, approval="host")])
        out, _ = self.chk()
        self.assertEqual(self.merges(out), "FAIL checkpoint.merges: head.7: the second parent of %s is %s, not the "
                         "recorded head %s; plan.7: the merge %s changes no path under %s: it is not a pull request of plan "
                         "%s; approval.7: approval is host, and merge.mode controller needs chat" % (m, head, other, m, PFX, SLUG))
        self.reledger([mline(7, other, "d" * 40, approval="host")])
        out, _ = self.chk()
        self.assertEqual(self.merges(out), "FAIL checkpoint.merges: merge.7: %s is not a commit in this repository; update "
                         "main from the remote; approval.7: approval is host, and merge.mode controller needs chat" % ("d" * 40))

    def test_merges_one_bad_of_three(self):  # CM14: ledger order; good lines add nothing
        h1, m1 = self.pr_merge("w1", {NOTE: "1\n"})
        h2, m2 = self.pr_merge("w2", {NOTE: "2\n"})
        h3, m3 = self.pr_merge("w3", {NOTE: "3\n"})
        bad = "a" * 40
        self.build(lines=["Prose.", CK, mline(7, h1, m1), mline(8, bad, m2), mline(9, h3, m3)])
        out, _ = self.chk()
        self.assertEqual(self.merges(out), "FAIL checkpoint.merges: head.8: the second parent of %s is %s, not the "
                         "recorded head %s" % (m2, h2, bad))

    def test_merges_one_line_per_id(self):  # CM21: many bad lines, one line, reasons joined with "; " in ledger order
        h1, m1 = self.pr_merge("w1", {NOTE: "1\n"})
        h2, m2 = self.pr_merge("w2", {NOTE: "2\n"})
        a, b = "a" * 40, "b" * 40
        self.build(lines=["Prose.", CK, mline(7, a, m1), mline(8, b, m2)])
        out, _ = self.chk()
        self.assertEqual(ids(out).count("merges"), 1)
        self.assertEqual(self.merges(out), "FAIL checkpoint.merges: head.7: the second parent of %s is %s, not the recorded "
                         "head %s; head.8: the second parent of %s is %s, not the recorded head %s" % (m1, h1, a, m2, h2, b))

    def test_merges_printed_only_with_ledger(self):  # CM19, D-Q2
        head, m = self.pr_merge("w1", {NOTE: "x\n"})
        self.build(lines=["Prose.", "CHECKPOINT P1 P1.1 head={H} tests=4/5 gates=PASS next=P1.2", mline(7, "c" * 40, m)])
        out, _ = self.chk()  # the last checkpoint is not green: checkpoint.ledger fails
        self.assertTrue(line_of(out, "ledger").startswith("FAIL checkpoint.ledger"))
        self.assertNotIn("checkpoint.merges", out)
        self.reledger([mline(7, head, m)])
        self.rewrite(plan="docs/strict-delivery/plans/other.md")  # the handoff fails: no ledger line, no merges line
        out, _ = self.chk()
        self.assertTrue(line_of(out, "handoff").startswith("FAIL checkpoint.handoff"))
        self.assertNotIn("checkpoint.merges", out)
        self.assertNotIn("checkpoint.ledger", out)

    def test_merges_crlf_line_not_checked(self):  # CM22: \r is outside the line grammar; the ledger rejects the line first
        head, m = self.pr_merge("w1", {NOTE: "x\n"})
        self.build(lines=["Prose.", CK, mline(7, "c" * 40, m) + "\r"])
        out, _ = self.chk()
        self.assertTrue(line_of(out, "ledger").startswith("FAIL checkpoint.ledger: line 4: 'MERGED' line does not match"),
                        out)
        self.assertNotIn("checkpoint.merges", out)

    def test_merges_unaffected_by_head_state(self):  # CM25: detached HEAD; the verdict reads refs and objects, never HEAD
        head, m = self.pr_merge("w1", {NOTE: "x\n"})
        self.build(lines=["Prose.", CK, mline(7, head, m)])
        git(self.root, "checkout", "-q", "--detach")
        out, _ = self.chk()
        self.assertEqual(self.merges(out), "PASS checkpoint.merges")

    def test_merges_git_config_independent(self):  # CM26: colour, abbreviation and prefix settings change nothing
        for k, v in (("color.ui", "always"), ("color.diff", "always"), ("core.abbrev", "7"), ("diff.noprefix", "true")):
            self.assertEqual(git(self.root, "config", "--get", k), v)
        head, m = self.pr_merge("w1", {NOTE: "x\n"})
        self.build(lines=["Prose.", CK, mline(7, head, m)])
        self.assertEqual(self.merges(self.chk()[0]), "PASS checkpoint.merges")

    def test_merges_valueerror_mapped(self):  # CM15, CM16: a ValueError is a merges line, never a traceback
        head, m = self.pr_merge("w1", {NOTE: "x\n"})
        self.build(lines=["Prose.", CK, mline(7, head, m)])
        text = "merged_errors: plan must be a plan slug of a-z, 0-9 and '-'"
        with mock.patch.object(gate_checkpoint.merge, "merged_errors", side_effect=ValueError(text)):
            out, code = self.chk()
        self.assertEqual((self.merges(out), code), ("FAIL checkpoint.merges: " + text, 1))
        bad = {"pr": 7, "merge": m, "approval": "host"}  # no head: merged_errors raises ValueError itself
        with mock.patch.object(gate_checkpoint.checkpoints, "merged_lines", return_value=[bad]):
            out, code = self.chk()
        self.assertEqual((self.merges(out), code), ("FAIL checkpoint.merges: merged_errors: line has no 'head'", 1))

    def test_merges_gateerror_is_input(self):  # CM17
        head, m = self.pr_merge("w1", {NOTE: "x\n"})
        self.build(lines=["Prose.", CK, mline(7, head, m)])
        with mock.patch.object(gate_checkpoint.merge, "merged_errors", side_effect=gate_checkpoint.GateError("cfg: broken")):
            out, code = self.chk()
        self.assertEqual((out, code), ("FAIL checkpoint.input: cfg: broken\n", 1))

    def test_merges_adds_no_git_call(self):  # MC-G1: the merges code calls merge.merged_errors and checkpoints.merged_lines only
        with open(os.path.join(REPO, "gates", "gate_checkpoint.py"), encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        fn = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_merges"]
        self.assertEqual(len(fn), 1)
        attrs = sorted({n.func.attr for n in ast.walk(fn[0]) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)})
        self.assertEqual(attrs, ["append", "merged_errors", "merged_lines"])
        names = {n.id for n in ast.walk(fn[0]) if isinstance(n, ast.Name)}
        self.assertFalse(names & {"gitinfo", "subprocess", "os"})

    def test_merges_subprocess_on_this_interpreter(self):  # PC2: python3 -m gates in a subprocess, sys.executable
        head, m = self.pr_merge("w1", {NOTE: "x\n"})
        self.build(lines=["Prose.", CK, mline(7, head, m)])
        run = lambda: subprocess.run([sys.executable, "-m", "gates", "check", "checkpoint", "--root", self.root, "--plan", SLUG],
                                     cwd=REPO, capture_output=True)
        p = run()
        self.assertEqual((p.returncode, p.stdout, p.stderr), (0, ALL.encode(), b""))
        self.reledger([mline(7, "c" * 40, m)])
        p = run()
        self.assertEqual(p.returncode, 1)
        self.assertEqual([l for l in p.stdout.decode().split("\n") if l.startswith("FAIL checkpoint.merges")][0], "FAIL checkpoint.merges: head.7: the second parent of %s is %s, "
                         "not the recorded head %s" % (m, head, "c" * 40))


class MergesHost(MergesFx):
    CFG = None  # minimal_config(): merge absent, the default host

    def test_merges_host_mode(self):  # CM3
        head, m = self.pr_merge("w1", {NOTE: "x\n"})
        self.build(lines=["Prose.", CK, mline(7, head, m, approval="host")])
        self.assertEqual(self.chk(), (ALL, 0))
        self.reledger([mline(7, head, m)])  # a chat line in host mode
        out, _ = self.chk()
        self.assertEqual(self.merges(out), "FAIL checkpoint.merges: approval.7: approval is chat, and merge.mode host needs host")

    def test_merges_pr_digit_cap(self):  # CM23: 600 digits are checked (the suffix prints whole), 601 fail the ledger
        head, m = self.pr_merge("w1", {NOTE: "x\n"})
        big = "9" * 600
        self.build(lines=["Prose.", CK, mline(big, head, "d" * 40, approval="host")])
        out, _ = self.chk()
        self.assertEqual(self.merges(out), "FAIL checkpoint.merges: merge.%s: %s is not a commit in this repository; update "
                         "main from the remote" % (big, "d" * 40))
        self.reledger([mline("9" * 601, head, m, approval="host")])
        out, _ = self.chk()
        self.assertTrue(line_of(out, "ledger").startswith("FAIL checkpoint.ledger"))
        self.assertNotIn("checkpoint.merges", out)


# ---------------------------------------------------------------------------------------------------------------------
# Task 6K.2: the five new lines (cap, records, base, files, last) and the same-repository rule of worktrees. Row ids refer
# to task-6K.2-domain.md (records/ of the program workspace) and its decisions D-6K2-Q1..Q9. Expected lines are written
# by hand from the plan (:6069-6089, :6092-6116) and that table, never read back from checkpoints.* or worktrees.*.
# ---------------------------------------------------------------------------------------------------------------------
F1 = "F-20261101-abcd"
D1 = "DEC-20261101-abcd"
D2 = "DEC-20261101-abce"
F2 = "F-20261101-abce"
FDIR = ".strict-delivery/state/findings"
DDIR = ".strict-delivery/state/decisions"
SPEC2 = "docs/strict-delivery/specs/s2.md"
CAP3 = minimal_config()  # profile strict presets block.max_tasks 3 (Task 4a.2); a file key block.max_tasks is refused


def ck(n, block="P1", tests="5/5", gates="PASS", nxt=None):
    """A CHECKPOINT line for task ``<block>.<n>`` (head is the placeholder the fixture replaces)."""
    return "CHECKPOINT %s %s.%d head={H} tests=%s gates=%s next=%s" % (block, block, n, tests, gates, nxt or "%s.%d" % (block, n + 1))


def plan_with(*ns, block="P1"):
    return "## Block %s: x\n" % block + "".join("### Task %s.%s: t\n" % (block, n) for n in ns)


class FullFx(Fx):
    """``Fx`` with the strict cap of 3 tasks, preset by the strict profile of the committed config (Task 4a.2; the
    cap was a file key before it, owner answer Q-RC6-1 (a)). A test that needs another cap sets ``profile="light"``
    (no preset) or an ``overrides`` entry."""
    CFG = CAP3

    def commit_push(self, msg="x"):
        commit_all(self.root, msg)
        self.push()

    def setcfg(self, **kw):
        write_record(self.root, ".strict-delivery/config.yml", dict(minimal_config(), **kw))
        self.commit_push("cfg")

    def reledger(self, lines, **kw):
        body = "\n".join(l.replace("{H}", self.h7) for l in lines)
        self.put(LEDGER, LH + body + "\n")
        self.commit_push("ledger")

    def replan(self, text):
        self.put(PLAN, text)
        self.commit_push("plan")

    def rec(self, directory, id_, status, root=None):
        self.put("%s/%s.yml" % (directory, id_), yamlsub.emit({"id": id_, "status": status}), root=root)

    def line(self, id_):
        return line_of(self.chk()[0], id_)


class NewLinesOrder(FullFx):
    def test_full_checkpoint_passes(self):  # GO1; plan :6094-6095
        self.build()
        out, code = self.chk()
        self.assertEqual(ids(out), ["handoff", "ledger", "agree", "head", "clean", "pushed", "reads", "worktrees", "merges",
                                    "cap", "records", "base", "files", "last"])
        self.assertEqual(out, ALL)
        self.assertEqual(code, 0)

    def test_line_ids_unique_and_known_with_new_lines(self):  # GO2
        self.build()
        self.rewrite(head="0000000", resume=resume_text(PLAN, "P1.2", "block/p1", "0000000"), base="0000000")
        out, _ = self.chk()
        got = ids(out)
        self.assertEqual(len(got), len(set(got)))
        self.assertTrue(set(got) <= set(ALL14))
        self.assertEqual(got, [i for i in ALL14 if i in got])  # a subsequence of the fixed order

    def test_handoff_missing_prints_no_dependent_lines(self):  # GO3; plan :6114-6115
        self.build()
        os.remove(os.path.join(self.root, *HANDOFF.split("/")))
        commit_all(self.root, "rm")
        self.push()
        out, code = self.chk()
        self.assertEqual(ids(out), ["handoff", "clean", "pushed"])
        self.assertNotIn("checkpoint.cap", out)
        self.assertIn("FAIL checkpoint.handoff", out)
        self.assertEqual(code, 1)
        self.rewrite(plan="docs/strict-delivery/plans/other.md")  # a handoff that fails its own rules
        out, _ = self.chk()
        self.assertTrue(line_of(out, "handoff").startswith("FAIL checkpoint.handoff"))
        for i in ("ledger", "agree", "head", "reads", "worktrees", "merges") + tuple(NEW):
            self.assertNotIn("checkpoint.%s" % i, out)

    def test_ledger_failure_new_lines_print_rule(self):  # GO4, D-6K2-Q2 (a)
        self.build(lines=["Prose only, no checkpoint line."], row={"ledger_from": 3})
        out, _ = self.chk()
        self.assertEqual(ids(out), ["handoff", "ledger", "head", "clean", "pushed", "reads", "worktrees"] + NEW)
        self.assertEqual(line_of(out, "last"), "FAIL checkpoint.last: no CHECKPOINT line")
        self.assertEqual(line_of(out, "cap"), "PASS checkpoint.cap")
        # an unreadable ledger file: records, base and files need only the handoff; cap and last need ledger text
        os.remove(os.path.join(self.root, *LEDGER.split("/")))
        commit_all(self.root, "rm ledger")
        self.push()
        out, _ = self.chk()
        self.assertEqual(ids(out), ["handoff", "ledger", "head", "clean", "pushed", "reads", "worktrees", "records", "base", "files"])
        self.assertNotIn("checkpoint.cap", out)
        self.assertNotIn("checkpoint.last", out)

    def test_new_lines_json_and_exit(self):  # GO6, section 13
        self.build()
        self.rewrite(base="0000000")
        self.push()
        out, code = run_main(["check", "checkpoint", "--json", "--root", self.root, "--plan", SLUG])
        d = json.loads(out)
        self.assertEqual([l["id"] for l in d["lines"]], ["checkpoint." + i for i in ALL14])
        self.assertIs(d["ok"], False)
        self.assertEqual(code, 1)
        base = [l for l in d["lines"] if l["id"] == "checkpoint.base"][0]
        self.assertEqual(base, {"status": "FAIL", "id": "checkpoint.base", "reason": "0000000 is not a commit"})
        out, code = self.chk()
        self.assertEqual(code, 1)
        self.assertEqual(line_of(out, "base"), "FAIL checkpoint.base: 0000000 is not a commit")

    def test_new_line_reasons_joined(self):  # GO8, D-Q15
        self.build(lines=["Prose.", ck(1), ck(2), ck(3), ck(4, nxt="P1.2")], row={"rulings": 5, "ledger_from": 7})
        self.replan(plan_with(1, 2, 3, 4))
        self.assertEqual(self.line("cap"), "FAIL checkpoint.cap: block: 4 tasks in ledger exceed block.max_tasks 3; "
                         "block: 4 tasks in plan exceed block.max_tasks 3; rulings: handoff says 5, ledger has 0")


class Cap(FullFx):
    def test_light_has_no_cap(self):  # CA1; plan :6100
        for n in (1, 4, 10):
            with self.subTest(tasks=n):
                fx = type(self)("test_light_has_no_cap")
                fx.CFG = dict(minimal_config(), profile="light")  # light presets no cap (strict presets 3)
                fx.setUp()
                try:
                    fx.build(lines=["Prose."] + [ck(i) for i in range(1, n + 1)], row={"ledger_from": n + 3})
                    fx.replan(plan_with(*range(1, n + 1)))
                    self.assertEqual(fx.line("cap"), "PASS checkpoint.cap")
                finally:
                    fx.doCleanups()

    def test_fourth_task_over_strict_cap_fails(self):  # CA2; plan :6098-6099 (the cap is written into the config, Q-RC6-1)
        self.build(lines=["Prose.", ck(1), ck(2), ck(3), ck(4)], row={"ledger_from": 7})
        self.replan(plan_with(1, 2, 3, 4))
        out, _ = self.chk()
        self.assertIn("FAIL checkpoint.cap: block: 4 tasks in ledger exceed block.max_tasks 3", out)
        self.assertEqual(line_of(out, "cap"), "FAIL checkpoint.cap: block: 4 tasks in ledger exceed block.max_tasks 3; "
                         "block: 4 tasks in plan exceed block.max_tasks 3")

    def test_cap_line_at_over_under(self):  # CA3
        self.build()
        for cap in (1, 3, 5):
            self.setcfg(profile="light", block={"max_tasks": cap})  # a profile that presets no cap: strict refuses a file key
            for n_led, n_plan, want in (
                    (cap, cap, "PASS checkpoint.cap"), (cap - 1, cap - 1, "PASS checkpoint.cap"),
                    (cap + 1, cap, "FAIL checkpoint.cap: block: %d tasks in ledger exceed block.max_tasks %d" % (cap + 1, cap)),
                    (cap, cap + 1, "FAIL checkpoint.cap: block: %d tasks in plan exceed block.max_tasks %d" % (cap + 1, cap))):
                with self.subTest(cap=cap, ledger=n_led, plan=n_plan):
                    self.reledger(["Prose."] + [ck(i) for i in range(1, n_led + 1)])
                    self.replan(plan_with(*range(1, n_plan + 1)))
                    self.assertEqual(self.line("cap"), want)

    def test_cap_profile_presets(self):  # CA4; plan :6081
        for profile, tasks, want in (("light", 10, "PASS checkpoint.cap"), ("standard", 6, "FAIL checkpoint.cap"),
                                     ("standard", 5, "PASS checkpoint.cap"), ("strict", 4, "FAIL checkpoint.cap"),
                                     ("strict", 3, "PASS checkpoint.cap")):
            with self.subTest(profile=profile, tasks=tasks):
                fx = type(self)("test_cap_profile_presets")
                fx.CFG = dict(minimal_config(), profile=profile)
                fx.setUp()
                try:
                    fx.build(lines=["Prose."] + [ck(i) for i in range(1, tasks + 1)], row={"ledger_from": tasks + 3})
                    fx.replan(plan_with(*range(1, tasks + 1)))
                    self.assertTrue(fx.line("cap").startswith(want))
                finally:
                    fx.doCleanups()

    def test_cap_overrides_entry(self):  # CA5: an overrides entry changing block.max_tasks raises the strict cap of 3 for the gate
        self.build()
        self.rec(DDIR, D1, "answered")  # the authorising decision of the override (gate_decisions checks it; this gate reads the config)
        self.setcfg(overrides={"block.max_tasks": {"value": 5, "decision": D1}})  # profile strict: the preset 3 is overridden to 5
        for n_led, n_plan, want in (
                (4, 4, "PASS checkpoint.cap"), (5, 5, "PASS checkpoint.cap"),
                (6, 5, "FAIL checkpoint.cap: block: 6 tasks in ledger exceed block.max_tasks 5"),
                (5, 6, "FAIL checkpoint.cap: block: 6 tasks in plan exceed block.max_tasks 5")):
            with self.subTest(ledger=n_led, plan=n_plan):
                self.reledger(["Prose."] + [ck(i) for i in range(1, n_led + 1)])
                self.replan(plan_with(*range(1, n_plan + 1)))
                self.assertEqual(self.line("cap"), want)

    def test_cap_file_key_refused_under_strict_preset(self):  # seam with 4a.2 (as test_checkpoints_lib's strict preset and refusal)
        self.build()
        self.setcfg(block={"max_tasks": 3})  # profile strict presets block.max_tasks 3: a file key is refused, even the same value
        self.assertEqual(self.chk(), ("FAIL checkpoint.input: .strict-delivery/config.yml: block.max_tasks: preset by profile strict; "
                                      "change it under overrides with the authorising decision\n", 1))

    def test_cap_bad_value_through_gate(self):  # CA6, CA7, D-6K2-Q6 (a)
        self.build()
        for value in (0, -1, True, "3", None, [3]):  # a float is not in the YAML subset, so no config holds one
            with self.subTest(max_tasks=repr(value)):
                self.setcfg(profile="light", block={"max_tasks": value})  # light presets no cap: a file value is read, then typed
                out, code = self.chk()
                self.assertEqual(out, "FAIL checkpoint.input: .strict-delivery/config.yml: block.max_tasks: must be an integer of at least 1\n")
                self.assertEqual(code, 1)
        for value in (0, True, "2"):
            with self.subTest(max_per_block=repr(value)):
                self.setcfg(rulings={"max_per_block": value})
                self.assertEqual(self.chk(), ("FAIL checkpoint.input: .strict-delivery/config.yml: rulings.max_per_block: "
                                              "must be an integer of at least 1\n", 1))
        self.setcfg(profile="light", block=5)
        self.assertEqual(self.chk(), ("FAIL checkpoint.input: .strict-delivery/config.yml: block: must be a mapping\n", 1))
        self.setcfg(rulings=[1])
        self.assertEqual(self.chk(), ("FAIL checkpoint.input: .strict-delivery/config.yml: rulings: must be a mapping\n", 1))

    def test_rulings_cap_through_gate(self):  # CA8
        r = "Ruling: a -- b -- c -- d"
        self.build(lines=["Prose.", ck(1), r, r], row={"rulings": 2, "ledger_from": 3})
        self.setcfg(rulings={"max_per_block": 2})
        self.assertEqual(self.line("cap"), "PASS checkpoint.cap")
        self.reledger(["Prose.", ck(1), r, r, r])
        self.rewrite(rulings=3)
        self.push()
        self.assertEqual(self.line("cap"), "FAIL checkpoint.cap: rulings: 3 Ruling lines in the ledger exceed rulings.max_per_block 2")

    def test_cap_rulings_agreement(self):  # CA9
        r = "Ruling: a -- b -- c -- d"
        self.build(lines=["Prose.", ck(1), r, r], row={"rulings": 0})
        for cfg in ({}, {"rulings": {"max_per_block": 5}}):
            self.setcfg(**cfg)
            self.assertEqual(self.line("cap"), "FAIL checkpoint.cap: rulings: handoff says 0, ledger has 2")
        self.rewrite(rulings=2)
        self.push()
        self.assertEqual(self.line("cap"), "PASS checkpoint.cap")

    def test_cap_plan_unreadable(self):  # CA10, D-6K2-Q5 (a)
        self.build()
        path = os.path.join(self.root, *PLAN.split("/"))
        os.remove(path)
        self.assertEqual(self.line("cap"), "FAIL checkpoint.cap: %s: missing" % PLAN)
        os.mkdir(path)
        self.assertEqual(self.line("cap"), "FAIL checkpoint.cap: %s: is not a regular file (a directory, symlink or other entry "
                         "is never followed)" % PLAN)
        os.rmdir(path)
        self.put(PLAN, b"\xff\xfe\x00")
        self.assertEqual(self.line("cap"), "FAIL checkpoint.cap: %s: not valid UTF-8" % PLAN)
        os.remove(path)
        os.symlink(os.path.join(self.root, SPEC), path)
        self.assertTrue(self.line("cap").startswith("FAIL checkpoint.cap: %s: is not a regular file" % PLAN))

    def test_cap_plan_duplicate_heading(self):  # CA11, D-6K2-Q6 (a)
        self.build()
        self.replan("## Block P1\n### Task P1.1: a\n#### Task P1.1: b\n")
        out, _ = self.chk()
        self.assertEqual(line_of(out, "cap"), "FAIL checkpoint.cap: plan_tasks: task P1.1 is listed twice")
        self.assertEqual(len(ids(out)), 14)
        # a condition before the colon is not a heading of the form; two of them are not a duplicate
        self.replan("## Block P1\n### Task P1.1 (only under x): a\n### Task P1.1 (only under y): b\n")
        self.assertEqual(self.line("cap"), "PASS checkpoint.cap")

    def test_cap_block_outside_letters_digits(self):  # CA12
        self.build()
        self.rewrite(block="P-1")
        self.push()
        out, _ = self.chk()
        self.assertEqual(line_of(out, "handoff"), "PASS checkpoint.handoff")
        self.assertEqual(line_of(out, "cap"), "FAIL checkpoint.cap: cap_errors: handoff block must be a string of ASCII letters and digits")
        for block in ("P 1", "Pࡰ"):
            self.rewrite(block=block)
            self.push()
            out, _ = self.chk()
            if line_of(out, "handoff") == "PASS checkpoint.handoff":
                self.assertEqual(line_of(out, "cap"), "FAIL checkpoint.cap: cap_errors: handoff block must be a string of "
                                 "ASCII letters and digits")
            else:
                self.assertIsNone(line_of(out, "cap"))

    def test_cap_ledger_real_size(self):  # CA13: only the handoff's block is counted in a long ledger
        others = ["CHECKPOINT P0 P0.%d head={H} tests=5/5 gates=PASS next=P0.%d" % (i, i + 1) for i in range(1, 1001)]
        self.build(lines=["Prose."] + others + [ck(1)], row={"ledger_from": 1004})
        self.replan(plan_with(1))
        out, _ = self.chk()
        self.assertEqual(line_of(out, "cap"), "PASS checkpoint.cap")

    def test_cap_rulings_counted_by_segment(self):  # CA14
        r = "Ruling: a -- b -- c -- d"
        lines = ["Prose.", r, ck(1, block="P0"), r, ck(1), r]  # the first ruling belongs to P0's segment, the last two to P1
        self.build(lines=lines, row={"rulings": 2, "ledger_from": 8})
        self.assertEqual(self.line("cap"), "PASS checkpoint.cap")
        self.rewrite(rulings=3)
        self.push()
        self.assertEqual(self.line("cap"), "FAIL checkpoint.cap: rulings: handoff says 3, ledger has 2")

    def test_cap_digit_limits_same_on_both(self):  # CA15, V1a; D-6K2-Q6 (a)
        for limit in INT_LIMITS:
            for digits, want in ((600, "FAIL checkpoint.cap: rulings: handoff says %s, ledger has 0" % ("9" * 600)),
                                 (601, "FAIL checkpoint.cap: cap_errors: handoff rulings must be an integer of 0 to 600 digits"),
                                 (1000, "FAIL checkpoint.cap: cap_errors: handoff rulings must be an integer of 0 to 600 digits")):
                with self.subTest(limit=limit, digits=digits), int_limit(limit):
                    fx = type(self)("test_cap_digit_limits_same_on_both")
                    fx.setUp()
                    try:
                        fx.build()
                        text = "---\n" + yamlsub.emit(fx.row).replace("rulings: 0\n", "rulings: %s\n" % ("9" * digits)) + "---\nbody\n"
                        fx.put(HANDOFF, text)
                        fx.commit_push()
                        if digits > (640 if limit == 640 else 1000):  # yamlsub refuses an integer beyond the limit in force
                            out, _ = fx.chk()
                            self.assertTrue(line_of(out, "handoff").startswith("FAIL checkpoint.handoff: front matter: line "), out[:300])
                            self.assertIsNone(line_of(out, "cap"))
                        else:
                            self.assertEqual(fx.line("cap"), want)
                    finally:
                        fx.doCleanups()
            for digits in (1001, 4300, 4301):  # V1a: refused by the front matter reader before the gate's own rules
                with self.subTest(limit=limit, digits=digits), int_limit(limit):
                    fx = type(self)("test_cap_digit_limits_same_on_both")
                    fx.setUp()
                    try:
                        fx.build()
                        fx.put(HANDOFF, "---\n" + yamlsub.emit(fx.row).replace("rulings: 0\n", "rulings: %s\n" % ("9" * digits)) + "---\nbody\n")
                        fx.commit_push()
                        out, _ = fx.chk()
                        self.assertTrue(line_of(out, "handoff").startswith("FAIL checkpoint.handoff: front matter: line "), out[:300])
                        self.assertIsNone(line_of(out, "cap"))
                    finally:
                        fx.doCleanups()

    def test_cap_config_value_digits(self):  # V1b: a 600-digit max_tasks is a valid integer that no count exceeds
        # The file key needs a profile that presets no cap (light); strict refuses it. Since Task 4a.3 config.load refuses
        # an integer of more than 600 digits (MAX_DIGITS) before the gate counts anything, so 1000 digits is an input line.
        light = yamlsub.emit(dict(minimal_config(), profile="light"))
        for limit in INT_LIMITS:
            with self.subTest(limit=limit), int_limit(limit):
                fx = type(self)("test_cap_config_value_digits")
                fx.setUp()
                try:
                    fx.build()
                    fx.put(".strict-delivery/config.yml", light + "block:\n  max_tasks: %s\n" % ("9" * 600))
                    fx.commit_push()
                    self.assertEqual(fx.line("cap"), "PASS checkpoint.cap")
                    fx.put(".strict-delivery/config.yml", light + "block:\n  max_tasks: %s\n" % ("9" * 1000))
                    fx.commit_push()
                    if limit == 640:  # yamlsub refuses an integer beyond the limit in force (1000 digits > 640)
                        self.assertTrue(fx.chk()[0].startswith("FAIL checkpoint.input: "))
                    else:
                        self.assertEqual(fx.chk(), ("FAIL checkpoint.input: .strict-delivery/config.yml: block.max_tasks: "
                                                    "must be an integer of at most 600 digits\n", 1))
                    fx.put(".strict-delivery/config.yml", light + "block:\n  max_tasks: %s\n" % ("9" * 1001))
                    fx.commit_push()
                    out, _ = fx.chk()
                    self.assertTrue(out.startswith("FAIL checkpoint.input: "), out[:300])
                    self.assertEqual(out.count("\n"), 1)
                finally:
                    fx.doCleanups()

    def test_cap_unicode_headings_not_counted(self):  # V2a: U+0870 and U+A7C1 changed category between Unicode 13 and 15
        self.build()
        self.setcfg(profile="light", block={"max_tasks": 1})  # light presets no cap: strict refuses a file value
        self.replan("## Block P1\n### Task P1.1: a\n### Task P1.ࡰ: b\n### Task P1.ꟁ: c\n")
        self.assertEqual(self.line("cap"), "PASS checkpoint.cap")


class Records(FullFx):
    def build_open(self, *ids_, **row):
        """``build`` whose handoff lists the open decisions ``ids_`` (and the resume line that names them)."""
        self.build(row=row)
        self.rewrite(open_decisions=list(ids_), resume=resume_text(PLAN, "P1.2", "block/p1", self.h7, ", ".join(ids_)))
        self.push()
        return self

    def prog(self, decisions=(), findings=(), raw=None):
        """Branch ``p/integration`` (cut from HEAD) holding the given decision and finding records; the handoff gets
        ``program: p``, ``stream: records``."""
        git(self.root, "checkout", "-q", "-b", "p/integration")
        for id_, status in decisions:
            self.rec(DDIR, id_, status)
        for id_, status in findings:
            self.rec(FDIR, id_, status)
        for rel, data in (raw or {}).items():
            self.put(rel, data)
        commit_all(self.root, "records")
        git(self.root, "checkout", "-q", "block/p1")
        self.rewrite(program="p", stream="records")
        self.push()

    def test_records_empty_passes(self):  # RC1
        self.build()
        self.assertEqual(self.line("records"), "PASS checkpoint.records")

    def test_records_unresolved_findings_pass(self):  # RC2
        for status in ("open", "planned", "in-progress", "fixed-unpinned", "pinned", "deferred"):
            with self.subTest(status=status):
                fx = type(self)("test_records_empty_passes")
                fx.setUp()
                try:
                    fx.build(row={"findings_in_flight": [F1]})
                    fx.rec(FDIR, F1, status)
                    fx.commit_push()
                    self.assertEqual(fx.line("records"), "PASS checkpoint.records")
                finally:
                    fx.doCleanups()

    def test_resolved_finding_in_flight_fails(self):  # RC3; plan :6102-6103
        for status in ("closed", "merged"):
            with self.subTest(status=status):
                fx = type(self)("test_records_empty_passes")
                fx.setUp()
                try:
                    fx.build(row={"findings_in_flight": [F1]})
                    fx.rec(FDIR, F1, status)
                    fx.commit_push()
                    out, _ = fx.chk()
                    self.assertIn("FAIL checkpoint.records", out)
                    self.assertIn(F1, out)
                    self.assertEqual(line_of(out, "records"), "FAIL checkpoint.records: findings_in_flight.%s: resolved (status %s)" % (F1, status))
                finally:
                    fx.doCleanups()

    def test_records_missing_finding(self):  # RC4
        self.build(row={"findings_in_flight": [F1]})
        self.assertEqual(self.line("records"), "FAIL checkpoint.records: findings_in_flight.%s: no finding record" % F1)

    def test_records_open_decisions(self):  # RC5
        self.build_open(D1)
        self.assertEqual(self.line("records"), "FAIL checkpoint.records: open_decisions.%s: no decision record" % D1)
        for status, want in (("open", "PASS checkpoint.records"),
                             ("answered", "FAIL checkpoint.records: open_decisions.%s: status answered, not open" % D1),
                             ("withdrawn", "FAIL checkpoint.records: open_decisions.%s: status withdrawn, not open" % D1)):
            with self.subTest(status=status):
                self.rec(DDIR, D1, status)
                self.commit_push()
                self.assertEqual(self.line("records"), want)

    def test_records_error_order(self):  # RC6, D-K-Q7
        self.build_open(D2, findings_in_flight=[F2, F1])
        self.rec(FDIR, F1, "closed")
        self.rec(DDIR, D2, "answered")
        self.commit_push()
        self.assertEqual(self.line("records"), "FAIL checkpoint.records: findings_in_flight.%s: no finding record; "
                         "findings_in_flight.%s: resolved (status closed); open_decisions.%s: status answered, not open" % (F2, F1, D2))

    def test_records_plain_plan_reads_worktree(self):  # RC7: a decision committed on another branch only is not found
        self.build_open(D1)
        git(self.root, "checkout", "-q", "-b", "other")
        self.rec(DDIR, D1, "open")
        commit_all(self.root, "d")
        git(self.root, "checkout", "-q", "block/p1")
        self.assertEqual(self.line("records"), "FAIL checkpoint.records: open_decisions.%s: no decision record" % D1)

    def test_program_records_read_from_integration(self):  # RC8; Q-Pplan-12 (a); plan :6104-6105
        self.build_open(D1)
        self.prog(decisions=[(D1, "open")])
        out, _ = self.chk()
        self.assertIn("PASS checkpoint.records", out)
        self.assertEqual(line_of(out, "records"), "PASS checkpoint.records")

    def test_program_record_only_in_worktree_fails(self):  # RC9
        self.build_open(D1)
        self.prog()
        self.rec(DDIR, D1, "open")
        self.commit_push()
        self.assertEqual(self.line("records"), "FAIL checkpoint.records: open_decisions.%s: no decision record" % D1)

    def test_program_without_local_integration_fails(self):  # RC10; plan :6106-6107; D-6K2-Q4 (a)
        self.build_open(D1)
        self.prog()
        want = "FAIL checkpoint.records: branch p/integration is missing locally; fetch it"
        git(self.root, "branch", "-q", "-m", "p/integration", "p/renamed")
        out, _ = self.chk()
        self.assertIn("FAIL checkpoint.records", out)
        self.assertIn("p/integration", out)
        self.assertEqual(line_of(out, "records"), want)
        # a remote-tracking ref or a tag of that spelling never answers
        sha = git(self.root, "rev-parse", "p/renamed")
        git(self.root, "update-ref", "refs/remotes/origin/p/integration", sha)
        self.assertEqual(self.line("records"), want)
        git(self.root, "tag", "p/integration", sha)
        self.assertEqual(self.line("records"), want)

    def test_program_decisions_directory_absent(self):  # RC11
        self.build()
        self.prog()
        self.assertEqual(self.line("records"), "PASS checkpoint.records")
        self.rewrite(open_decisions=[D1], resume=resume_text(PLAN, "P1.2", "block/p1", self.h7, D1))
        self.push()
        self.assertEqual(self.line("records"), "FAIL checkpoint.records: open_decisions.%s: no decision record" % D1)

    def test_program_value_forms(self):  # RC12: the handoff gate refuses the shapes first; records is then not printed
        self.build()
        for prog, stream in (("a-b", "records"), ("A", "records"), ("a/b", "records"), ("", "records"), ("ࡰ", "records"),
                             (None, "records"), ("p", None)):
            with self.subTest(program=prog, stream=stream):
                self.row.pop("program", None)
                self.row.pop("stream", None)
                if prog is not None:
                    self.row["program"] = prog
                if stream is not None:
                    self.row["stream"] = stream
                self.rewrite()
                self.push()
                out, _ = self.chk()
                ok = prog == "a-b"
                self.assertEqual(line_of(out, "handoff").startswith("PASS"), ok, out[:300])
                if not ok:
                    self.assertIsNone(line_of(out, "records"))

    def test_records_unreadable_register_is_input(self):  # RC13; plan :6071
        self.build()
        self.put("%s/bad.yml" % DDIR, "a: [\n")
        self.commit_push()
        out, code = self.chk()
        self.assertEqual(out, "FAIL checkpoint.input: %s/bad.yml: unterminated flow sequence (line 1)\n" % DDIR)
        self.assertEqual(code, 1)
        os.remove(os.path.join(self.root, DDIR, "bad.yml"))
        os.makedirs(os.path.join(self.root, FDIR, "sub"))
        self.put("%s/sub/x" % FDIR, "x")
        self.commit_push()
        out, _ = self.chk()
        self.assertEqual(out, "FAIL checkpoint.input: %s/sub: not a regular file named <id>.yml (only index.yml and in-force.md "
                         "are allowed besides records)\n" % FDIR)

    def test_program_unreadable_register_is_input(self):  # RC14
        for raw in ({"%s/bad.yml" % DDIR: "a: [\n"}, {"%s/sub/x.yml" % DDIR: "id: a\n"}, {"%s/notyml.txt" % DDIR: "x"}):
            with self.subTest(raw=sorted(raw)):
                fx = type(self)("test_records_empty_passes")
                fx.setUp()
                try:
                    fx.build()
                    fx.prog(raw=raw)
                    out, code = fx.chk()
                    self.assertTrue(out.startswith("FAIL checkpoint.input: "), out)
                    self.assertEqual(out.count("\n"), 1)
                    self.assertIn(".strict-delivery/state/decisions/", out)
                    self.assertEqual(code, 1)
                finally:
                    fx.doCleanups()

    def test_records_non_utf8_record(self):  # RC15
        self.build()
        self.put("%s/%s.yml" % (DDIR, D1), b"\xff\xfe\x00")
        self.commit_push()
        out, _ = self.chk()
        self.assertTrue(out.startswith("FAIL checkpoint.input: "), out)
        self.assertEqual(out.count("\n"), 1)
        self.assertIn("%s/%s.yml" % (DDIR, D1), out)

    def test_records_kind_mixup(self):  # RC16
        self.build_open(D1, findings_in_flight=[F1])
        self.rec(DDIR, F1, "open")  # a finding id sitting in the decisions register
        self.rec(FDIR, D1, "open")  # a decision id sitting in the findings register
        self.commit_push()
        self.assertEqual(self.line("records"), "FAIL checkpoint.records: findings_in_flight.%s: no finding record; "
                         "open_decisions.%s: no decision record" % (F1, D1))
        self.rewrite(findings_in_flight=[D1])  # the handoff gate refuses the wrong kind first
        self.push()
        out, _ = self.chk()
        self.assertTrue(line_of(out, "handoff").startswith("FAIL checkpoint.handoff"))
        self.assertIsNone(line_of(out, "records"))

    def test_records_each_kind_read_once(self):  # RC17
        self.build()
        self.prog()
        with mock.patch.object(checkpoints, "records_at", wraps=checkpoints.records_at) as spy:
            out, _ = self.chk()
        self.assertEqual(line_of(out, "records"), "PASS checkpoint.records")
        self.assertEqual(spy.call_count, 2)
        self.assertEqual(sorted(c.args[3] for c in spy.call_args_list), ["decision", "finding"])
        self.assertTrue(all(c.args[2] == "refs/heads/p/integration" for c in spy.call_args_list))

    def test_records_dirty_worktree_plain_vs_program(self):  # RC18
        self.build_open(D1)
        self.rec(DDIR, D1, "answered")
        self.commit_push()
        self.rec(DDIR, D1, "open")  # uncommitted change: a plain plan reads the worktree content
        out, _ = self.chk()
        self.assertEqual(line_of(out, "records"), "PASS checkpoint.records")
        self.assertTrue(line_of(out, "clean").startswith("FAIL checkpoint.clean: uncommitted paths: "))
        git(self.root, "checkout", "-q", "--", DDIR)
        self.prog(decisions=[(D1, "open")])  # the worktree holds the answered record, the integration branch the open one
        self.rec(DDIR, D1, "withdrawn")      # and a dirty change: a program plan never reads the worktree
        self.assertEqual(self.line("records"), "PASS checkpoint.records")


class Base(FullFx):
    def based(self, base, **row):
        self.rewrite(base=base, **row)
        self.push()
        return self.chk()[0]

    def test_base_ancestor_passes(self):  # BA1
        self.build()
        for base in (self.base, self.base[:7]):
            with self.subTest(base=base):
                self.assertEqual(line_of(self.based(base), "base"), "PASS checkpoint.base")

    def test_base_equal_to_head_passes(self):  # BA2
        self.build()
        for base in (self.h7, self.c1):
            self.assertEqual(line_of(self.based(base), "base"), "PASS checkpoint.base")

    def test_base_not_ancestor_fails(self):  # BA3; plan :6108-6109
        self.build()
        orphan = git(self.root, "commit-tree", "4b825dc642cb6eb9a060e54bf8d69288fbee4904", "-m", "orphan")
        out = self.based(orphan)
        self.assertIn("FAIL checkpoint.base", out)
        self.assertEqual(line_of(out, "base"), "FAIL checkpoint.base: %s is not an ancestor of %s" % (orphan, self.h7))
        git(self.root, "checkout", "-q", "-b", "ahead")
        self.put("ahead.txt")
        ahead = commit_all(self.root, "ahead")
        git(self.root, "checkout", "-q", "block/p1")
        self.assertEqual(line_of(self.based(ahead), "base"), "FAIL checkpoint.base: %s is not an ancestor of %s" % (ahead, self.h7))

    def test_base_not_a_commit_fails(self):  # BA4
        self.build()
        tree = git(self.root, "rev-parse", "HEAD^{tree}")
        blob = git(self.root, "rev-parse", "HEAD:" + PLAN)
        for base in ("0000000", tree, blob):
            with self.subTest(base=base):
                out = self.based(base)
                self.assertEqual(line_of(out, "base"), "FAIL checkpoint.base: %s is not a commit" % base)
                self.assertEqual(len(ids(out)), 14)  # no lone checkpoint.input line

    def test_base_short_and_full(self):  # BA5
        self.build()
        for base in (self.base[:7], self.base, self.base[:12]):
            self.assertEqual(line_of(self.based(base), "base"), "PASS checkpoint.base")

    def test_base_annotated_tag_object(self):  # BA6
        self.build()
        git(self.root, "tag", "-a", "-m", "m", "t1", self.base)
        tagobj = git(self.root, "rev-parse", "t1")
        self.assertNotEqual(tagobj, self.base)
        self.assertEqual(line_of(self.based(tagobj), "base"), "PASS checkpoint.base")

    def test_base_forms_refused_by_schema(self):  # BA7
        self.build()
        for base in ("main", self.base[:6], self.base.upper(), self.base + "0"):
            with self.subTest(base=base):
                out = self.based(base)
                self.assertTrue(line_of(out, "handoff").startswith("FAIL checkpoint.handoff"), out[:300])
                self.assertIsNone(line_of(out, "base"))

    def test_base_when_head_missing(self):  # BA8, D-6K2-Q5 (a)
        self.build()
        out = self.based(self.base, head="0000000", resume=resume_text(PLAN, "P1.2", "block/p1", "0000000"))
        self.assertEqual(line_of(out, "base"), "FAIL checkpoint.base: head 0000000 is not a commit")
        self.assertEqual(line_of(out, "head"), "FAIL checkpoint.head: head: 0000000 is not a commit")

    def test_base_ambiguous_prefix(self):  # BA9: a 7-hex prefix of two objects is not a commit (core.disambiguate=none)
        self.build()
        import hashlib
        seen = {}
        pair = None
        n = 0
        while pair is None:
            body = ("tree 4b825dc642cb6eb9a060e54bf8d69288fbee4904\nauthor a <a@x> %d +0000\ncommitter a <a@x> %d +0000\n\nm\n" % (n, n)).encode()
            sha = hashlib.sha1(b"commit %d\x00" % len(body) + body).hexdigest()
            if sha[:7] in seen:
                pair = (seen[sha[:7]], body, sha[:7])
            seen[sha[:7]] = body
            n += 1
        for i, body in enumerate(pair[:2]):
            path = os.path.join(self.tmp, "c%d.txt" % i)
            with open(path, "wb") as fh:
                fh.write(body)
            git(self.root, "hash-object", "-t", "commit", "-w", path)
        out = self.based(pair[2])
        self.assertEqual(line_of(out, "base"), "FAIL checkpoint.base: %s is not a commit" % pair[2])


class Files3(FullFx):
    def untrack(self, *rels):
        for rel in rels:
            git(self.root, "rm", "-q", "--cached", rel)
        git(self.root, "commit", "-q", "-m", "untrack")
        self.push()

    def test_files_tracked_passes(self):  # FI1
        self.build(files={SPEC2: "s2\n"}, row={"spec": [SPEC, SPEC2]})
        self.assertEqual(self.line("files"), "PASS checkpoint.files")
        self.assertEqual(git(self.root, "ls-files", "--", PLAN, SPEC, SPEC2).split("\n"), sorted([PLAN, SPEC, SPEC2]))

    def test_untracked_plan_fails(self):  # FI2
        self.build()
        self.untrack(PLAN)
        self.assertEqual(self.line("files"), "FAIL checkpoint.files: %s: not tracked" % PLAN)

    def test_untracked_spec_fails(self):  # FI3; plan :6110-6111
        self.build(row={"spec": [SPEC, "docs/strict-delivery/specs/never.md"]})
        self.put("docs/strict-delivery/specs/never.md")  # on disk, never added
        self.push()
        out, _ = self.chk()
        self.assertIn("FAIL checkpoint.files", out)
        self.assertEqual(line_of(out, "files"), "FAIL checkpoint.files: docs/strict-delivery/specs/never.md: not tracked")

    def test_spec_deleted(self):  # FI4, D-6K2-Q8 (a)
        self.build()
        git(self.root, "rm", "-q", SPEC)
        git(self.root, "commit", "-q", "-m", "rm")
        self.push()
        self.assertEqual(self.line("files"), "FAIL checkpoint.files: %s: not tracked" % SPEC)
        git(self.root, "revert", "--no-edit", "-n", "HEAD")
        git(self.root, "commit", "-q", "-m", "back")
        self.push()
        self.assertEqual(self.line("files"), "PASS checkpoint.files")
        git(self.root, "rm", "-q", "--cached", SPEC)
        git(self.root, "commit", "-q", "-m", "cached")
        self.push()
        self.assertEqual(self.line("files"), "FAIL checkpoint.files: %s: not tracked" % SPEC)
        git(self.root, "add", SPEC)
        git(self.root, "commit", "-q", "-m", "tracked again")
        self.push()
        os.remove(os.path.join(self.root, *SPEC.split("/")))  # disk only: the index still tracks it; clean reports it
        out, _ = self.chk()
        self.assertEqual(line_of(out, "files"), "PASS checkpoint.files")
        self.assertIn(SPEC, line_of(out, "clean"))

    def test_spec_renamed(self):  # FI5
        self.build()
        new = "docs/strict-delivery/specs/renamed.md"
        git(self.root, "mv", SPEC, new)
        git(self.root, "commit", "-q", "-m", "mv")
        self.push()
        self.assertEqual(self.line("files"), "FAIL checkpoint.files: %s: not tracked" % SPEC)
        self.rewrite(spec=[new])
        self.push()
        self.assertEqual(self.line("files"), "PASS checkpoint.files")

    def test_two_specs_one_missing(self):  # FI6
        self.build(files={SPEC2: "s2\n"}, row={"spec": [SPEC, SPEC2]})
        self.untrack(SPEC2)
        line = self.line("files")
        self.assertEqual(line, "FAIL checkpoint.files: %s: not tracked" % SPEC2)
        self.assertNotIn(SPEC + ":", line)

    def test_files_reasons_order(self):  # FI7, D-6K2-Q7 (a)
        self.build(files={SPEC2: "s2\n"}, row={"spec": [SPEC, SPEC2]})
        self.untrack(SPEC2, PLAN, SPEC)
        out, _ = self.chk()
        self.assertEqual(out.count("FAIL checkpoint.files"), 1)
        self.assertEqual(line_of(out, "files"), "FAIL checkpoint.files: %s: not tracked; %s: not tracked; %s: not tracked" % (PLAN, SPEC, SPEC2))

    def test_spec_directory_and_symlink(self):  # FI8
        self.build()
        self.rewrite(spec=["docs/strict-delivery/specs"])
        self.push()
        self.assertEqual(self.line("files"), "FAIL checkpoint.files: docs/strict-delivery/specs: not tracked")
        link = "docs/strict-delivery/specs/link.md"
        os.symlink("s.md", os.path.join(self.root, *link.split("/")))
        self.commit_push()
        self.rewrite(spec=[link])
        self.push()
        self.assertEqual(self.line("files"), "FAIL checkpoint.files: %s: not tracked" % link)

    def test_spec_staged_only(self):  # FI9
        self.build(row={"spec": [SPEC, "docs/strict-delivery/specs/n.md"]})
        self.put("docs/strict-delivery/specs/n.md")
        git(self.root, "add", "docs/strict-delivery/specs/n.md")
        out, _ = self.chk()
        self.assertEqual(line_of(out, "files"), "PASS checkpoint.files")
        self.assertTrue(line_of(out, "clean").startswith("FAIL checkpoint.clean: uncommitted paths: "))
        self.assertIn("n.md", line_of(out, "clean"))

    def test_spec_case_differs(self):  # FI10
        self.build(row={"spec": ["docs/strict-delivery/specs/S.md"]})
        self.assertEqual(self.line("files"), "FAIL checkpoint.files: docs/strict-delivery/specs/S.md: not tracked")

    def test_spec_non_ascii_refused_earlier(self):  # FI11
        self.build(row={"spec": ["docs/strict-delivery/specs/ünï.md"]})
        out, _ = self.chk()
        self.assertTrue(line_of(out, "handoff").startswith("FAIL checkpoint.handoff"), out[:300])
        self.assertIsNone(line_of(out, "files"))

    def test_spec_path_forms(self):  # FI12: a path that is not normalised is never reported as tracked
        self.build()
        for spec in ("./" + SPEC, "docs//strict-delivery/specs/s.md", "../x", "/" + SPEC, "docs/strict-delivery/specs/../specs/s.md"):
            with self.subTest(spec=spec):
                self.rewrite(spec=[spec])
                self.push()
                out, _ = self.chk()
                self.assertNotEqual(line_of(out, "files"), "PASS checkpoint.files")
                if line_of(out, "handoff") == "PASS checkpoint.handoff":
                    self.assertEqual(line_of(out, "files"), "FAIL checkpoint.files: %s: not tracked" % spec)

    def test_spec_duplicates(self):  # FI13
        self.build(row={"spec": [SPEC, SPEC]})
        out, _ = self.chk()
        self.assertTrue(line_of(out, "handoff").startswith("FAIL checkpoint.handoff"))
        self.assertIsNone(line_of(out, "files"))


class Last(FullFx):
    def last(self, *lines):
        self.build(lines=["Prose."] + list(lines), row={"ledger_from": len(lines) + 3})
        out, _ = self.chk()
        return out

    def test_last_green_passes(self):  # LA1
        self.assertEqual(line_of(self.last(ck(1)), "last"), "PASS checkpoint.last")

    def test_red_last_checkpoint_fails(self):  # LA2, D-6K2-Q1 (a); plan :6112-6113
        out = self.last(ck(1, tests="4/5"))
        self.assertIn("FAIL checkpoint.last", out)
        self.assertEqual(line_of(out, "last"), "FAIL checkpoint.last: last CHECKPOINT: tests 4/5")
        self.assertEqual(line_of(out, "ledger"), "FAIL checkpoint.ledger: line 3: last CHECKPOINT is not green (tests=4/5 gates=PASS)")
        self.assertNotIn("checkpoint.agree", out)
        self.assertNotIn("checkpoint.merges", out)

    def test_last_gates_not_pass(self):  # LA3
        out = self.last(ck(1, gates="n/a"))
        self.assertEqual(line_of(out, "last"), "FAIL checkpoint.last: last CHECKPOINT: gates=n/a")

    def test_last_both_red(self):  # LA4
        out = self.last(ck(1, tests="4/5", gates="n/a"))
        self.assertEqual(line_of(out, "last"), "FAIL checkpoint.last: last CHECKPOINT: gates=n/a; last CHECKPOINT: tests 4/5")

    def test_last_zero_of_zero(self):  # LA5, D-K-Q16: 0/0 fails the ledger and passes last
        out = self.last(ck(1, tests="0/0"))
        self.assertEqual(line_of(out, "last"), "PASS checkpoint.last")
        self.assertEqual(line_of(out, "ledger"), "FAIL checkpoint.ledger: line 3: last CHECKPOINT is not green (tests=0/0 gates=PASS)")

    def test_last_only_last_line(self):  # LA6
        out = self.last(ck(1, tests="4/5"), ck(2, nxt="P1.3"))
        self.assertEqual(line_of(out, "last"), "PASS checkpoint.last")

    def test_last_any_block(self):  # LA7: the block mismatch is agree's
        out = self.last(ck(1), ck(1, block="P2"))
        self.assertEqual(line_of(out, "last"), "PASS checkpoint.last")
        self.assertTrue(line_of(out, "agree").startswith("FAIL checkpoint.agree: block: ledger line 4 has P2, handoff has P1"))

    def test_last_no_checkpoint_line(self):  # LA8
        out = self.last()
        self.assertEqual(line_of(out, "last"), "FAIL checkpoint.last: no CHECKPOINT line")
        self.assertIn("no conforming CHECKPOINT line", line_of(out, "ledger"))

    def test_last_crlf_last_line(self):  # LA9: a CRLF line is not a CHECKPOINT line; the line before it is the last
        text = LH + "Prose.\n" + ck(1).replace("{H}", "0000000") + "\n" + ck(2, tests="1/5", gates="n/a").replace("{H}", "0000000") + "\r\n"
        self.build(ledger_text=text, row={"ledger_from": 5})
        out, _ = self.chk()
        self.assertEqual(line_of(out, "last"), "PASS checkpoint.last")
        self.assertTrue(line_of(out, "ledger").startswith("FAIL checkpoint.ledger"))

    def test_last_digit_limits_same_on_both(self):  # LA10, V1b
        for limit in INT_LIMITS:
            with self.subTest(limit=limit), int_limit(limit):
                n = "9" * 600
                m = "9" * 599 + "8"
                for tests, want in (("%s/%s" % (n, n), "PASS checkpoint.last"),
                                    ("%s/%s" % (m, n), "FAIL checkpoint.last: last CHECKPOINT: tests %s/%s" % (m, n)),
                                    ("%s/%s" % ("9" * 601, "9" * 601), "FAIL checkpoint.last: no CHECKPOINT line")):
                    fx = type(self)("test_last_green_passes")
                    fx.setUp()
                    try:
                        out = fx.last(ck(1, tests=tests))
                        self.assertEqual(line_of(out, "last"), want)
                    finally:
                        fx.doCleanups()


class WorktreesSameRepo(Fx):
    wt = Worktrees.wt
    sib = Worktrees.sib

    def foreign(self, name="otherrepo"):
        other = os.path.join(self.tmp, name)
        os.mkdir(other)
        make_repo(other)
        return other

    def test_worktree_of_another_repository_fails(self):  # WT1; rewrites the U2 test of test_worktree_directory_not_a_top_level
        self.build()
        other = self.foreign()
        head = git(other, "rev-parse", "HEAD")[:7]
        out = self.wt({"path": "../otherrepo", "branch": "main", "head": head, "porcelain": ""})
        self.assertIn("FAIL checkpoint.worktrees", out)
        self.assertIn("../otherrepo", out)
        self.assertEqual(line_of(out, "worktrees"), "FAIL checkpoint.worktrees: ../otherrepo: not a worktree of this repository")

    def test_linked_worktree_passes(self):  # WT2
        self.build()
        self.sib()
        out = self.wt({"path": "../w", "branch": "wb", "head": self.c1[:7], "porcelain": ""})
        self.assertEqual(line_of(out, "worktrees"), "PASS checkpoint.worktrees")

    def test_worktree_symlink_to_linked(self):  # WT4
        self.build()
        w = self.sib()
        os.symlink(w, os.path.join(self.tmp, "lnk"))
        out = self.wt({"path": "../lnk", "branch": "wb", "head": self.c1[:7], "porcelain": ""})
        self.assertEqual(line_of(out, "worktrees"), "PASS checkpoint.worktrees")

    def test_worktree_clone_fails(self):  # WT5
        self.build()
        clone = os.path.join(self.tmp, "clone")
        git(self.tmp, "clone", "-q", "-b", "block/p1", self.bare, clone)
        out = self.wt({"path": "../clone", "branch": "block/p1", "head": self.c1[:7], "porcelain": ""})
        self.assertEqual(line_of(out, "worktrees"), "FAIL checkpoint.worktrees: ../clone: not a worktree of this repository")

    def test_worktree_unborn_linked_entry(self):  # fix round 1, F-20261124-cqac: HEAD has no commit, same repository
        self.build()
        orph = os.path.join(self.tmp, "orph")
        git(self.root, "worktree", "add", "-q", "--orphan", "-b", "orph", orph)
        self.assertEqual(git(orph, "rev-parse", "--path-format=absolute", "--git-common-dir"),
                         git(self.root, "rev-parse", "--path-format=absolute", "--git-common-dir"))
        out = self.wt({"path": "../orph", "branch": "orph", "head": self.c1[:7], "porcelain": ""})
        self.assertEqual(line_of(out, "worktrees"), "FAIL checkpoint.worktrees: ../orph: HEAD has no commit")

    def test_worktree_kinds_keep_old_reasons(self):  # WT6
        self.build()
        os.mkdir(os.path.join(self.tmp, "plain"))
        bare = os.path.join(self.tmp, "b.git")
        git(self.tmp, "init", "-q", "--bare", bare)
        for path, want in (("../b.git", "not a git top level (not a repository)"), ("../plain", "not a git top level (not a repository)"),
                           ("../nope", "directory missing")):
            with self.subTest(path=path):
                out = self.wt({"path": path, "branch": None, "head": self.c1[:7], "porcelain": ""})
                self.assertEqual(line_of(out, "worktrees"), "FAIL checkpoint.worktrees: %s: %s" % (path, want))

    def test_worktree_foreign_repository_reason_first(self):  # WT8, D-6K2-Q9 (a): the reason replaces the head and branch checks
        self.build()
        self.foreign()
        out = self.wt({"path": "../otherrepo", "branch": "zzz", "head": "0000000", "porcelain": ""})
        self.assertEqual(line_of(out, "worktrees"), "FAIL checkpoint.worktrees: ../otherrepo: not a worktree of this repository")

    def test_worktree_same_repository_ignores_git_env(self):  # WT11
        self.build()
        other = self.foreign()
        self.sib()
        entries = ({"path": "../w", "branch": "wb", "head": self.c1[:7], "porcelain": ""},
                   {"path": "../otherrepo", "branch": "main", "head": git(other, "rev-parse", "HEAD")[:7], "porcelain": ""})
        self.rewrite(worktrees=[{"path": ".", "branch": "block/p1", "head": self.h7, "porcelain": ""}] + list(entries))
        self.push()
        env = {"GIT_DIR": os.path.join(self.tmp, "nowhere"), "GIT_COMMON_DIR": os.path.join(self.tmp, "nowhere2")}
        with mock.patch.dict(os.environ, env):
            out, _ = self.chk()
        self.assertEqual(line_of(out, "worktrees"), "FAIL checkpoint.worktrees: ../otherrepo: not a worktree of this repository")


class SourceAndGroups(FullFx):
    def test_gate_source_no_unbounded_int_format(self):  # V1c (fix round 1, F-20261124-iwe7)
        """Rule: an integer reaches output only through the ``%d`` strings of Tasks P1.3 and P3.1 (their operands are line
        numbers, test counts and file line counts, each bounded by ``checkpoint_lines`` or the file size). So the set of
        string constants holding ``%d`` must equal that hand-written set; no f-string and no ``.format`` call exists; and
        every ``str(...)`` call takes the caught exception ``e`` (never a count). A new formatted integer, in any function,
        fails; an unrelated edit does not."""
        with open(os.path.join(REPO, "gates", "gate_checkpoint.py"), encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        want = {
            "line %d: last CHECKPOINT is not green (tests=%d/%d gates=%s)",
            "block: ledger line %d has %s, handoff has %s",
            "next: ledger line %d has %s, handoff next_task is %s",
            "ledger line %d names %s, handoff names %s: not the same commit",
            "ledger_from: %s is not %d (the line after the last CHECKPOINT line, %d)",
            "%s: lines %s: the file has %d lines",
            "%s: lines %s: need start <= end <= %d (the file's line count)",
        }
        got = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and "%d" in node.value:
                got.add(node.value)
            self.assertNotIsInstance(node, ast.JoinedStr, "an f-string")
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Attribute) and node.func.attr == "format":
                    self.fail(".format at line %d" % node.lineno)
                if isinstance(node.func, ast.Name) and node.func.id in ("str", "repr", "format"):
                    ok = node.func.id == "str" and len(node.args) == 1 and isinstance(node.args[0], ast.Name) and node.args[0].id == "e"
                    self.assertTrue(ok, "%s(...) of something but an exception at line %d" % (node.func.id, node.lineno))
        self.assertEqual(got, want)

    def test_gate_source_has_no_unicode_table_calls(self):  # V2b
        with open(os.path.join(REPO, "gates", "gate_checkpoint.py"), encoding="utf-8") as fh:
            src = fh.read()
        for banned in (".lower()", ".isprintable", "unicodedata", ".splitlines", "\\w", "BaseException", "except:"):
            self.assertNotIn(banned, src, banned)

    def test_gate_unexpected_exception_is_input_not_a_reason(self):  # V3, both interpreters (fix round 1, F-20261124-iwe7)
        """An exception the new code does not name (here a ``RuntimeError``; an ``ExceptionGroup`` is the 3.11+ form) at
        any call it makes is not turned into a reason on ``cap``, ``base``, ``files``, ``last`` or ``worktrees``: ``run_check``
        prints the single line ``FAIL checkpoint.input: RuntimeError: boom``."""
        self.build()
        exc = [RuntimeError("boom")]

        def boom(*a, **k):
            raise exc[0]
        real = {"is_ancestor": gitinfo.is_ancestor, "commit_exists": gitinfo.commit_exists}

        def below_base(name):
            def side(*a, **k):
                f = sys._getframe(1)
                while f is not None and f.f_code.co_name != "_base":
                    f = f.f_back
                if f is None:
                    return real[name](*a, **k)
                raise exc[0]
            return side
        for target, side in (("gates.lib.gitinfo.tracked_files", boom), ("gates.lib.checkpoints.cap_errors", boom),
                             ("gates.lib.checkpoints.last_line_errors", boom), ("gates.lib.checkpoints.record_errors", boom),
                             ("gates.lib.worktrees.same_repository", boom),
                             ("gates.lib.gitinfo.is_ancestor", below_base("is_ancestor")),
                             ("gates.lib.gitinfo.commit_exists", below_base("commit_exists"))):
            with self.subTest(target=target), mock.patch(target, side_effect=side):
                out, code = self.chk()
                self.assertEqual((out, code), ("FAIL checkpoint.input: RuntimeError: boom\n", 1))
            # a BaseException that is not an Exception (the 3.9-safe stand-in of BaseExceptionGroup) leaves main unchanged
            exc[0] = KeyboardInterrupt()
            with self.subTest(target=target, kind="KeyboardInterrupt"), mock.patch(target, side_effect=side):
                with self.assertRaises(KeyboardInterrupt):
                    self.chk()
            exc[0] = RuntimeError("boom")

    def test_gate_exception_groups_propagate(self):  # V3 (fix round 1, F-20261124-iwe7)
        """A ``BaseExceptionGroup`` raised at any call the new code makes leaves ``main`` unchanged (``run_check`` catches
        ``Exception`` only). An ``ExceptionGroup`` is an ``Exception``: ``run_check`` turns it into the one line
        ``FAIL checkpoint.input: ...``, and it never becomes a reason on ``cap``, ``records``, ``base``, ``files`` or ``last``."""
        if not hasattr(builtins, "BaseExceptionGroup"):
            self.skipTest("no BaseExceptionGroup on this interpreter")
        self.build()
        real = {"is_ancestor": gitinfo.is_ancestor, "commit_exists": gitinfo.commit_exists}

        def raiser(make, only_in=None, name=None):
            def side(*a, **k):
                if only_in is not None:  # raise only below the named function; the other gate lines call these too
                    f = sys._getframe(1)
                    while f is not None and f.f_code.co_name != only_in:
                        f = f.f_back
                    if f is None:
                        return real[name](*a, **k)
                raise make()
            return side
        bgroup = lambda: builtins.BaseExceptionGroup("x", [KeyboardInterrupt()])
        egroup = lambda: builtins.ExceptionGroup("x", [ValueError("y")])
        targets = [("gates.lib.gitinfo.tracked_files", None, None), ("gates.lib.checkpoints.cap_errors", None, None),
                   ("gates.lib.checkpoints.last_line_errors", None, None), ("gates.lib.checkpoints.record_errors", None, None),
                   ("gates.lib.worktrees.same_repository", None, None),
                   ("gates.lib.gitinfo.is_ancestor", "_base", "is_ancestor"), ("gates.lib.gitinfo.commit_exists", "_base", "commit_exists")]
        for target, only_in, name in targets:
            with self.subTest(target=target, kind="BaseExceptionGroup"), mock.patch(target, side_effect=raiser(bgroup, only_in, name)):
                with self.assertRaises(builtins.BaseExceptionGroup):
                    self.chk()
            with self.subTest(target=target, kind="ExceptionGroup"), mock.patch(target, side_effect=raiser(egroup, only_in, name)):
                out, code = self.chk()
                self.assertTrue(out.startswith("FAIL checkpoint.input: "), out)
                self.assertEqual((out.count("\n"), code), (1, 1))
        # the program path: local_branches and records_at
        git(self.root, "branch", "p/integration")
        self.rewrite(program="p", stream="records")
        self.push()
        for target in ("gates.lib.gitinfo.local_branches", "gates.lib.checkpoints.records_at"):
            with self.subTest(target=target, kind="BaseExceptionGroup"), mock.patch(target, side_effect=raiser(bgroup)):
                with self.assertRaises(builtins.BaseExceptionGroup):
                    self.chk()
            with self.subTest(target=target, kind="ExceptionGroup"), mock.patch(target, side_effect=raiser(egroup)):
                out, _ = self.chk()
                self.assertTrue(out.startswith("FAIL checkpoint.input: ") and out.count("\n") == 1, out)


class Registration(unittest.TestCase):
    def test_checkpoint_produces_literal(self):  # DC1, D-Q23
        self.assertEqual(gate_checkpoint.PRODUCES, ())

    def test_checkpoint_produces_is_a_tuple_of_str(self):  # DC8
        self.assertIs(type(gate_checkpoint.PRODUCES), tuple)
        self.assertTrue(all(type(x) is str for x in gate_checkpoint.PRODUCES))

    def test_checkpoint_in_producer_modules(self):  # DC2, D-Q23
        self.assertEqual(producers.PRODUCER_MODULES[-2:], ("gates.gate_checkpoint", "gates.tools.program_cli"))  # P2.2 appends last
        self.assertEqual(producers.PRODUCER_MODULES[2], "gates.tools.findings_cli")

    def test_handoff_and_ledger_unproduced_not_checked(self):  # DC3
        out, code = run_main(["check", "schema", "--root", REPO])
        self.assertEqual(code, 0, out)
        self.assertNotIn("schema.handoff", out)
        self.assertNotIn("schema.ledger", out)
        self.assertEqual(out.count("\n"), out.count("PASS schema"))

    def test_run_all_unaffected_when_undeclared(self):  # DC6
        out, code = run_main(["run_all", "--base", "HEAD"])
        self.assertEqual(code, 0, out)
        self.assertNotIn("checkpoint", out)


if __name__ == "__main__":
    unittest.main()
