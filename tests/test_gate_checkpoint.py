"""Tests of gates/gate_checkpoint.py (plan Task P1.3 Steps 1-4) through ``python3 -m gates check checkpoint``.

Row ids in comments refer to the P1.3 input-domain table (task-P1.3-domain.md) and its binding decisions D-Q1..D-Q26.
The handoff is written by ``yamlsub.emit`` from a hand-written row; expected lines, reasons and line counts are
written out by hand from the plan lines and the table, never read back from the code under test. Fixtures are
``make_repo`` repositories whose config pins ``color.ui=always``, ``color.diff=always``, ``core.abbrev=7`` (Global
Constraints :33) with a bare remote in the temp directory (no network). Rows MG1-MG15, DC4 and DC5 are the oracle of
Step 5 (the program controller's migration of this repository's workspace, D-Q26) and are not tested here."""
import ast
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
from gates.lib import gitinfo, yamlsub
from tests.helpers import (TOP, GitIsolatedTestCase, check_root_forms, commit_all, git, make_repo, minimal_config,
                           root_forms, write_record)

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
NINE = EIGHT + ["merges"]  # Task P3.1 (CM20): checkpoint.merges is the last line, after worktrees
ALL = "".join("PASS checkpoint.%s\n" % i for i in NINE)
ALL_EIGHT = "".join("PASS checkpoint.%s\n" % i for i in EIGHT)
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
        for rel, data in (files or {}).items():
            self.put(rel, data)
        self.c1 = commit_all(self.root, "code")
        self.h7 = self.c1[:7]
        self.base = git(self.root, "rev-list", "--max-parents=0", "HEAD")
        body = "\n".join(l.replace("{H}", self.h7) for l in (lines if lines is not None else ["Prose line.", CK]))
        self.put(LEDGER, ledger_text if ledger_text is not None else LH + body + "\n")
        self.row = {
            "schema": "handoff/1", "plan": PLAN, "spec": ["docs/strict-delivery/specs/s.md"], "branch": "block/p1",
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
        self.assertEqual(ids(out), ["handoff", "ledger", "agree", "head", "clean", "pushed", "reads", "worktrees", "merges"])

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
        self.assertEqual([l["id"] for l in d["lines"]], ["checkpoint." + i for i in NINE])
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
        self.assertTrue(set(got) <= set(EIGHT))

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
        self.assertEqual(ids(out), ["handoff", "ledger", "head", "clean", "pushed", "reads", "worktrees"])
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
        self.assertEqual(out, ALL_EIGHT + FAKE_MERGE_FAIL)  # P3.1: the fake merge sha is now checked against git
        nob = "MERGED pr=3 head=%s merge=%s merged_by=a at=2026-11-02T08:59:36Z final=no approval=host" % ("a" * 40, "b" * 40)
        self.put(LEDGER, LH + "Prose.\n" + CK.replace("{H}", self.h7) + "\n" + nob + "\n")
        commit_all(self.root, "l")
        self.push()
        self.assertEqual(self.chk()[0], ALL_EIGHT + FAKE_MERGE_FAIL)

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
        self.assertEqual(self.chk()[0], ALL_EIGHT + FAKE_MERGE_FAIL)

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
        self.assertEqual(ids(out), ["handoff", "ledger", "head", "clean", "pushed", "reads", "worktrees"])

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
        self.assertLessEqual(subs, {"symbolic-ref", "rev-parse", "remote", "status", "merge-base", "ls-tree", "cat-file", "config"})
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
        self.assertEqual(line_of(out, "worktrees"), "PASS checkpoint.worktrees")  # same-repository is Task 6K.2's

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
        self.assertEqual(line_of(out, "worktrees"), "FAIL checkpoint.worktrees: ../unb: HEAD has no commit")


class Output(Fx):
    def test_failure_keeps_line_order(self):  # OR4
        self.build()
        self.rewrite(head="0000000", resume=resume_text(PLAN, "P1.2", "block/p1", "0000000"))
        self.put("x.txt")
        out, _ = self.chk()
        self.assertEqual(ids(out), ["handoff", "ledger", "head", "clean", "pushed", "reads", "worktrees"])

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
        self.assertEqual(ids(bad_out), NINE)

    def test_merges_printed_last_after_worktrees(self):  # CM20
        head, m = self.pr_merge("w1", {NOTE: "x\n"})
        self.build(lines=["Prose.", CK, mline(7, head, m)])
        out, _ = self.chk()
        self.assertEqual(ids(out)[-2:], ["worktrees", "merges"])

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
        self.assertEqual(p.stdout.decode().split("\n")[-2], "FAIL checkpoint.merges: head.7: the second parent of %s is %s, "
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
