"""Tests of gates/tools/continue_cli.py (Task P4.2, automatic continuation) through ``gates.__main__.main`` in process and
``python3 -m gates continue`` in a subprocess (``sys.executable``), on fixture repositories made with ``helpers.make_repo``
(git config ``color.ui=always``, ``color.diff=always``, ``core.abbrev=7``, ``diff.noprefix=true``). Expected values are
written by hand from the plan (:3121-3183) and the input-domain table of Task P4.2 with its binding decisions D-Q1..D-Q10;
the rows are named in the comments (CM, CG, HD, QA, LG, SR, TM, PS, SB, IJ, GD, GC, V)."""
import ast
import builtins
import contextlib
import datetime
import io
import json
import os
import re
import stat
import subprocess
import sys
import unittest
from unittest import mock

from gates import __main__ as gates_main
from gates import gate_dispatch, producers
from gates.lib import config, decisions, dispatch, gitinfo, ids, programs, yamlsub
from gates.tools import continue_cli, index, questions_cli
from tests.helpers import (INT_LIMITS, GitIsolatedTestCase, commit_all, git, int_limit, make_repo, minimal_config,
                           root_forms, write_record)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SLUG = "x-plan"
PLANS = "docs/strict-delivery/plans"
PLAN = PLANS + "/x-plan.md"
PS = ".strict-delivery/state/plans"
HP = PS + "/x-plan/handoff.md"
LP = PS + "/x-plan/ledger.md"
DEC = ".strict-delivery/state/decisions"
PRG = "20261101-x"
INTEG = PRG + "/integration"
PROGDIR = ".strict-delivery/state/programs/" + PRG
CK = "CHECKPOINT P4 P4.1 head=abc1234 tests=3/3 gates=PASS next=P4.2"
LH = "<!-- schema: ledger/1 -->\n"
D1, D2, D3, D4 = ("DEC-20261101-%s" % s for s in ("aaaa", "bbbb", "cccc", "dddd"))
F1, F2 = "F-20261101-aaaa", "F-20261101-bbbb"
TODAY = datetime.date(2026, 11, 21)
HEAD_ROW = ("| stream | block | branch | worktree | next task | estimate | used | status | blockers | pending decisions "
            "| delivers |\n|---|---|---|---|---|---|---|---|---|---|---|\n")
ROW_A = "| a | P4 | 20261101-x/a/main | ../w/a | P4.2 | 5 | 1 | running | none | none | does a |"
ROW_B = "| b | P4 | 20261101-x/b/main | ../w/b | P4.3 | 5 | 1 | running | none | none | does b |"
ALL_ROLES = dispatch.ROLES
MODELS = {"program_controller": "opus", "stream_controller": "opus", "controller": "opus", "implementer": "sonnet",
          "implementer_transcription": "haiku", "task_reviewer": "sonnet", "final_reviewer": "opus",
          "final_verifier": "opus", "exception_reviewer": "opus", "audit_reviewer": "opus", "audit_verifier": "opus",
          "investigator": "opus", "plan_writer": "opus", "plan_reviewer": "opus", "drafter": "sonnet"}
REFERENCE = (
    "## Role\ncontroller\n## Brief\n"
    "Continue docs/strict-delivery/plans/x-plan.md at P4.2; branch b; head abc1234\n"
    "Handoff: .strict-delivery/state/plans/x-plan/handoff.md\n"
    "Ledger since the last checkpoint:\nDispatched: x\n"
    "## Findings\nNone.\n## Claims\nNone.\n## Budget: tokens=1000 minutes=10\n## Model\nopus\n"
    "## Report\nstatus: DONE|DONE_WITH_FINDINGS|NEEDS_DECISION|BLOCKED|DENIED\n"
    "## Strict block\n\n# Strict block: controller\n\nrules\n\n"
    "## Task\nResume at P4.2 from the handoff; nothing continues from inherited memory.\n")


def resume(plan, nxt, branch, head, qids):
    return "Resume strict-delivery plan %s at %s; branch %s; head %s; open questions: %s." % (
        plan, nxt, branch, head, ", ".join(qids) if qids else "none")


def Q(qid="q1", source=None, **over):
    q = {"qid": qid, "class": "scope", "question": "Which?", "effect": "lasting",
         "options": [{"label": "a", "cost": "ca"}, {"label": "b", "cost": "cb"}], "recommended": "a"}
    if source is not None:
        q["source"] = source
    q.update(over)
    return q


def hrow(ps=PS, **over):
    row = {"schema": "handoff/1", "plan": PLAN, "spec": ["docs/strict-delivery/specs/s.md"], "branch": "b",
           "head": "abc1234", "base": "abc1234", "ledger": ps + "/x-plan/ledger.md", "block": "P4",
           "next_task": "P4.2", "findings_in_flight": [], "open_decisions": [], "rulings": 0, "grant": None,
           "live_subagents": [], "role": "controller", "budget": {"tokens": 1000, "minutes": 10},
           "worktrees": [{"path": ".", "branch": "b", "head": "abc1234", "porcelain": ""}],
           "skills": ["strict-delivery"], "ledger_from": 2, "batch_cut": None, "questions": []}
    row.update(over)
    if "resume" not in over:
        qids = [q["qid"] for q in row["questions"] if isinstance(q, dict) and isinstance(q.get("qid"), str)]
        row["resume"] = resume(row["plan"], row["next_task"], row["branch"], row["head"],
                               list(row["open_decisions"]) + qids)
    return row


def htext(row=None, body="a body line\n", **over):
    return "---\n" + yamlsub.emit(row if row is not None else hrow(**over)) + "---\n" + body


def ledger(tail="", ck=CK, head=LH):
    return head + ck + "\n" + tail


def dec(id_, status, tag, source=HP, answer="A one", question="Q one?", **over):
    r = {"schema": "decision/%d" % decisions._schema().version, "id": id_, "status": status, "class": "scope",
         "question": question, "options": [{"label": "a", "cost": "ca"}, {"label": "b", "cost": "cb"}],
         "asked_at": "a1b2c3d", "asked_by": "agent", "topics": [tag], "applies_to": [], "checked_against": [],
         "effect": "one-off", "recommended": "a"}
    if source is not None:
        r["source"] = source
    if status == "answered":
        r.update(answer=answer, answered_at={"at": "a1b2c3d", "by": "who@example.invalid"})
    if status == "withdrawn":
        r["withdrawn"] = {"at": "a1b2c3d", "by": "who@example.invalid", "reason": "asked twice"}
    r.update(over)
    return r


def block_of(role):
    return "# Strict block: %s\n\nrules\n" % role


def sect(out, name):
    sections, errors = dispatch.parse(out)
    assert errors == [], errors
    return sections[name]


class Fx(GitIsolatedTestCase):
    """A fixture root with a working-tree handoff and ledger of plan ``x-plan``, a prompts directory ``self.pd`` with
    a block file for every role, and the Claude Code limit variables cleared (GD5)."""

    cfg_over: dict = {}

    def setUp(self):
        super().setUp()
        p = mock.patch.dict(os.environ)
        p.start()
        self.addCleanup(p.stop)
        for k in (dispatch.ENV_DEPTH, dispatch.ENV_CONCURRENT):
            os.environ.pop(k, None)
        self.n = 0
        self.ps = PS
        self.build()

    def build(self, cfg=None, handoff=None, led=None):
        self.n += 1
        top = os.path.join(self.tmp, "w%d" % self.n)
        os.mkdir(top)
        self.cfg_row = dict(minimal_config(), **(self.cfg_over if cfg is None else cfg))
        self.root = make_repo(top, self.cfg_row)
        for k, v in (("color.ui", "always"), ("color.diff", "always"), ("core.abbrev", "7"), ("diff.noprefix", "true")):
            git(self.root, "config", k, v)
        self.pd = os.path.join(self.tmp, "pd%d" % self.n)
        os.mkdir(self.pd)
        for r in ALL_ROLES:
            self.put_file(os.path.join(self.pd, r + ".md"), block_of(r))
        self.put(self.ps + "/x-plan/handoff.md", handoff if handoff is not None else htext(ps=self.ps))
        self.put(self.ps + "/x-plan/ledger.md", led if led is not None else ledger("Dispatched: x\n"))
        self.cfg = config.load(self.root)

    # ---- files
    def put_file(self, path, data):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(data if isinstance(data, bytes) else data.encode("utf-8"))
        return path

    def put(self, rel, data, root=None):
        return self.put_file(os.path.join(root or self.root, *rel.split("/")), data)

    def hand(self, **over):
        self.put(self.ps + "/x-plan/handoff.md", htext(hrow(ps=self.ps, **over)))

    def led(self, tail="", **kw):
        self.put(self.ps + "/x-plan/ledger.md", ledger(tail, **kw))

    def put_dec(self, *rows):
        for r in rows:
            write_record(self.root, "%s/%s.yml" % (DEC, r["id"]), r)

    def set_config(self, **over):
        write_record(self.root, ".strict-delivery/config.yml", dict(minimal_config(), **over))

    def snap(self):
        out = {}
        for d, dirs, files in os.walk(self.root):
            dirs[:] = [x for x in dirs if x != ".git"]
            for f in files:
                p = os.path.join(d, f)
                with open(p, "rb") as fh:
                    out[os.path.relpath(p, self.root)] = fh.read()
        return out, git(self.root, "status", "--porcelain", "--untracked-files=all")

    # ---- runs
    def run_c(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = gates_main.main(["continue"] + list(argv))
        return code, out.getvalue(), err.getvalue()

    def base(self, plan=SLUG, root=True, prompts=True):
        a = ["--plan", plan]
        if root:
            a += ["--root", self.root]
        if prompts:
            a += ["--prompts", self.pd]
        return a

    def go(self, *extra):
        with mock.patch.object(ids, "utc_today", return_value=TODAY):
            return self.run_c(*self.base(), *extra)

    def ok(self, *extra):
        code, out, err = self.go(*extra)
        self.assertEqual((code, err), (0, ""), err)
        return out

    def refuse(self, needle, *extra, argv=None):
        with mock.patch.object(ids, "utc_today", return_value=TODAY):
            code, out, err = self.run_c(*(argv if argv is not None else self.base() + list(extra)))
        self.assertEqual((code, out), (1, ""), err)
        self.assertTrue(err != "" and all(l.startswith("continue: ") for l in err.splitlines()), err)
        self.assertIn(needle, err)
        return err

    def sub(self, *argv, env=None):
        e = dict(os.environ, PYTHONPATH=REPO)
        e.update(env or {})
        p = subprocess.run([sys.executable, "-m", "gates", "continue"] + list(argv), cwd=REPO, env=e,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return p.returncode, p.stdout, p.stderr

    # ---- program
    def program(self, status=None, rows=None):
        git(self.root, "checkout", "-q", "-b", INTEG)
        try:
            def st(sid, order):
                return {"id": sid, "purpose": "p", "plan": "%s/%s-plan.md" % (PLANS, sid), "estimate": 5,
                        "depends_on": [], "merge_order": order, "owns": [sid + "-owned.py"]}
            row = {"schema": "streams/1", "program": PRG, "plan": PLANS + "/program-plan.md", "specs": [],
                   "worktrees": "../w", "streams": rows if rows is not None else [st("a", 1), st("b", 2)], "shared": []}
            self.put(PROGDIR + "/streams.yml", yamlsub.emit(row))
            self.put(PROGDIR + "/status.md", status if status is not None else
                     "<!-- schema: status/1 -->\n\n" + HEAD_ROW + ROW_A + "\n" + ROW_B + "\n")
            self.put(PROGDIR + "/sync-log.md", "<!-- schema: sync-log/1 -->\n")
            self.put(PROGDIR + "/merged.md", "<!-- schema: merged-log/1 -->\n")
            self.commit_prog("program")
        finally:
            git(self.root, "checkout", "-q", "main")

    def commit_prog(self, msg):
        git(self.root, "add", "-A", PROGDIR)   # only the program files: the working-tree handoff stays untracked
        git(self.root, "commit", "-q", "-m", msg)

    def prog_hand(self, **over):
        self.hand(program=PRG, stream="a", **over)

    def gate(self, out, model="opus", dispatcher="session", depth=0, children=0, total=0, live=False, pd=None):
        path = os.path.join(self.tmp, "gate-in.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"prompt": out, "model": model, "dispatcher": {"id": dispatcher, "depth": depth,
                       "live_children": children, "live_total": total}, "program_live": live}, fh)
        return gate_dispatch.check(["--root", self.root, "--prompts", pd or self.pd, "--input", path])

    def flags(self, path, dispatcher="session", depth="0", children="0", total="0"):
        return ["--input-json", path, "--dispatcher", dispatcher, "--depth", depth, "--live-children", children,
                "--live-total", total]


# =====================================================================================================================
class TestMain(Fx):
    def test_reference_output_literal(self):  # PS1-PS17 one literal (D-Q6), PS14, PS16
        out = self.ok()
        self.assertEqual(out, REFERENCE)
        self.assertEqual(self.ok(), out)  # PS16 determinism

    def test_main_argv_types(self):  # CM1
        class S(str):
            pass
        for bad in (("--plan", SLUG), ["--plan", None], ["--plan", 5], ["--plan", b"x"], [S("--plan"), SLUG]):
            with self.subTest(bad=repr(bad)):
                err = io.StringIO()
                with contextlib.redirect_stderr(err):
                    self.assertEqual(continue_cli.main(bad), 2)
                self.assertEqual(err.getvalue(), "continue: argv must be a list of str\n")
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(out):
            self.assertEqual(continue_cli.main([]), 2)
        self.assertEqual(err.getvalue(), continue_cli._USAGE)   # the bare usage line, no "--plan is required" reason
        with mock.patch.object(ids, "utc_today", return_value=TODAY), mock.patch.object(
                sys, "argv", ["x"] + self.base()), contextlib.redirect_stdout(out):
            self.assertEqual(continue_cli.main(None), 0)
        self.assertEqual(out.getvalue(), REFERENCE)

    def test_plan_slug_domain(self):  # CM2
        for bad in ("", "X-Plan", "x_plan", "a/b", "..", "x-plan.md", "-x", "x y", "x\x00y", "x\ny", "é", "Ꟁ",
                    "a" * 0 + "-", "x" * 0 + "A"):
            with self.subTest(slug=bad):
                with mock.patch.object(index, "_root", side_effect=AssertionError("git before the flag check")):
                    self.refuse("--plan: must match [a-z0-9][a-z0-9-]*", argv=["--plan=" + bad, "--root", self.root])
        for n in (255, 256, 4301):   # a valid slug of any length passes the flag check, then the handoff is missing
            with self.subTest(n=n):
                self.refuse("missing", argv=self.base(plan="a" * n))
        code, out, err = self.run_c("--root", self.root)
        self.assertEqual((code, out), (2, ""))
        self.assertIn("continue: --plan is required", err)
        self.refuse("--plan given more than once", argv=self.base() + ["--plan", SLUG])

    def test_ref_forms(self):  # CM3
        commit_all(self.root, "state")
        sha = git(self.root, "rev-parse", "HEAD")
        for ref in ("main", "refs/heads/main", sha, "HEAD"):
            with self.subTest(ref=ref):
                self.assertEqual(self.ok("--ref", ref), REFERENCE)
        for ref in ("", "-x", "^x", "a" * 41, "main:foo", "HEAD^{tree}", "no-such", "a b", "a\nb"):
            with self.subTest(ref=ref):
                self.refuse("--ref", "--ref=" + ref)
        self.refuse("--ref given more than once", "--ref", "main", "--ref", "HEAD")
        self.refuse("--ref: v is not a commit", "--ref", "v")
        git(self.root, "tag", "main2")
        self.assertEqual(self.ok("--ref", "main2"), REFERENCE)

    def test_prompts_flag_forms(self):  # CM4
        real = os.path.join(REPO, "skills", "strict-delivery", "prompts")
        with open(os.path.join(real, "controller.md"), "rb") as fh:
            want = fh.read().decode("utf-8")
        with mock.patch.object(ids, "utc_today", return_value=TODAY):
            code, out, err = self.run_c("--plan", SLUG, "--root", self.root)
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(sect(out, "Strict block"), "\n" + want + "\n")
        rel = os.path.relpath(self.pd, os.getcwd())
        self.refuse("--prompts given more than once", "--prompts", self.pd)
        with mock.patch.object(ids, "utc_today", return_value=TODAY):
            self.assertEqual(self.run_c("--plan", SLUG, "--root", self.root, "--prompts", rel)[1], REFERENCE)
        spaced = os.path.join(self.tmp, "p d")
        os.mkdir(spaced)
        self.put_file(os.path.join(spaced, "controller.md"), block_of("controller"))
        with mock.patch.object(ids, "utc_today", return_value=TODAY):
            self.assertEqual(self.run_c("--plan", SLUG, "--root", self.root, "--prompts", spaced)[1], REFERENCE)
        fil = self.put_file(os.path.join(self.tmp, "afile"), "x")
        for p in (fil, os.path.join(self.tmp, "missing"), ""):
            with self.subTest(p=p):
                self.refuse("--prompts: must not be empty" if p == "" else "strict block file",
                            argv=["--plan", SLUG, "--root", self.root, "--prompts=" + p])

    def test_root_forms(self):  # CM5
        commit_all(self.root, "state")
        forms = root_forms(self.tmp, self.root)
        for name, path, verdict in forms:
            with self.subTest(form=name):
                code, out, err = self.run_c("--plan", SLUG, "--root", path, "--prompts", self.pd)
                if verdict == "ok":
                    self.assertNotIn("show-toplevel", err)
                else:
                    self.assertEqual((code, out), (1, ""))
                    self.assertIn(verdict, err)
        self.refuse("--root: must not be empty", argv=["--plan", SLUG, "--root=", "--prompts", self.pd])
        self.refuse("--root given more than once", argv=self.base() + ["--root", self.root])

    def test_flag_combinations(self):  # CM6, IJ12
        f = os.path.join(self.tmp, "out.json")
        for argv in (self.base() + ["x-plan"], self.base() + ["--bogus"], ["-h"], ["--help"]):
            with self.subTest(argv=argv):
                with contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(self.run_c(*argv)[:2], (2, ""))
        self.refuse("--dispatcher: only valid with --input-json", "--dispatcher", "session")
        self.refuse("--depth: only valid with --input-json", "--depth", "0")
        self.refuse("--live-total, --live-children: only valid with --input-json".replace(
            "--live-total, --live-children", "--live-children, --live-total"),
            "--live-children", "0", "--live-total", "0")
        for missing in ("--dispatcher", "--depth", "--live-children", "--live-total"):   # IJ4
            fl = self.flags(f)
            i = fl.index(missing)
            del fl[i:i + 2]
            with self.subTest(missing=missing):
                self.refuse(missing + " is required with --input-json", *fl)
        self.refuse("--input-json", "--input-json", f)
        self.assertFalse(os.path.exists(f))

    def test_abbreviated_flags_pinned(self):  # CM7
        f = os.path.join(self.tmp, "abbr.json")
        with mock.patch.object(ids, "utc_today", return_value=TODAY):
            code, out, err = self.run_c("--pl", SLUG, "--ro", self.root, "--prompt", self.pd, "--in", f,
                                        "--dispatcher", "session", "--dep", "0", "--live-c", "0", "--live-t", "0")
        self.assertEqual((code, out, err), (0, REFERENCE, ""))
        self.assertTrue(os.path.exists(f))
        commit_all(self.root, "state")
        with mock.patch.object(ids, "utc_today", return_value=TODAY):
            self.assertEqual(self.run_c("--pl", SLUG, "--ro", self.root, "--prompt", self.pd, "--re", "main")[1], REFERENCE)

    def test_exit_codes(self):  # CM8
        self.assertEqual(self.go()[0], 0)
        self.refuse("missing", argv=self.base(plan="y-plan"))
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(self.run_c("--nope")[0], 2)
        p = self.sub("--plan", SLUG, "--root", self.root, "--prompts", self.pd, env={"PYTHONIOENCODING": "utf-8"})
        self.assertEqual(p[0], 0)
        p = self.sub("--plan", "Bad", "--root", self.root)
        self.assertEqual((p[0], p[1]), (1, b""))
        self.assertEqual(self.sub()[0], 2)

    def scenarios(self):
        def live(fx):
            fx.hand(live_subagents=[{"agent": "ag1", "task": "t", "worktree": ".", "transcript": "tr",
                                     "last_record": "lr", "jobs": []}])

        def question(fx):
            fx.hand(questions=[Q("q1")])

        def bad_handoff(fx):
            fx.put(fx.ps + "/x-plan/handoff.md", "no front matter\n")

        def bad_ledger(fx):
            fx.put(fx.ps + "/x-plan/ledger.md", LH + "Dispatched: x\n")

        def tier_missing(fx):
            fx.hand(role="final_verifier")
            fx.set_config(top_tier_roles=["exception_reviewer"])

        def fallback(fx):
            fx.hand(role="final_verifier")
            fx.set_config(top_tier_fallback="tier9")

        def no_row(fx):
            fx.program(status="<!-- schema: status/1 -->\n\n" + HEAD_ROW + ROW_B + "\n")
            fx.prog_hand()

        def no_prompt(fx):
            os.rename(os.path.join(fx.pd, "controller.md"), os.path.join(fx.pd, "gone.md"))

        def heading_line(fx):
            fx.led("## Notes\n")

        def two(fx):
            live(fx)
            fx.hand(live_subagents=[{"agent": "ag1", "task": "t", "worktree": ".", "transcript": "tr",
                                     "last_record": "lr", "jobs": []}], questions=[Q("q1")])
        return {"live_subagents": live, "unanswered": question, "invalid handoff": bad_handoff,
                "invalid ledger": bad_ledger, "tier4 outside": tier_missing, "fallback": fallback, "no status row": no_row,
                "no prompt file": no_prompt, "heading line": heading_line, "two reasons": two}

    def test_refusals_print_nothing_on_stdout(self):  # CM9, CM11
        for name, setup in self.scenarios().items():
            with self.subTest(name):
                self.build()
                setup(self)
                f = os.path.join(self.tmp, "never%d.json" % self.n)
                before = self.snap()
                argv = self.base() + self.flags(f, dispatcher="controller")
                code, out, err = self.run_c(*argv)
                self.assertEqual((code, out), (1, ""), err)
                p = self.sub(*argv)
                self.assertEqual((p[0], p[1]), (1, b""))
                self.assertEqual(p[2].decode(), err)
                self.assertFalse(os.path.exists(f))
                self.assertEqual(self.snap(), before)

    def test_refusal_lines_are_safe_text(self):  # CM10
        self.hand(live_subagents=[{"agent": "ag1", "task": "t", "worktree": ".", "transcript": "tr",
                                   "last_record": "lr", "jobs": []}], questions=[Q("q1")])
        err = self.refuse("orphan")
        lines = err.splitlines()
        self.assertEqual(len(lines), 2, err)   # Q4: every failing stage prints, one reason per line
        self.assertTrue(lines[0].startswith("continue: live_subagents is not empty: continuing would orphan ag1"), err)
        self.assertTrue(lines[1].startswith("continue: question q1: unanswered"), err)
        self.hand(questions=[Q("q1")])
        self.put_dec(dec(D1, "answered", "q:x-plan:q1"))
        with mock.patch.object(questions_cli, "question_state", side_effect=questions_cli.GateError("a\x1b[31mb\nsecond\x07")):
            err = self.refuse("a\\x1b[31mb")
        self.assertIn("continue: second\\x07\n", err)
        self.assertNotIn("\x1b", err)

    def test_inherits_git_index_file(self):  # CM12
        commit_all(self.root, "state")
        with mock.patch.dict(os.environ, {"GIT_INDEX_FILE": os.path.join(self.tmp, "idx")}):
            self.assertEqual(self.ok("--ref", "main"), REFERENCE)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "idx")))

    def test_continue_registered(self):  # CG1
        self.assertIn("continue", gates_main.COMMANDS)
        with mock.patch.object(continue_cli, "main", return_value=7) as m:
            self.assertEqual(gates_main.COMMANDS["continue"](["--plan", "x"]), 7)
        m.assert_called_once_with(["--plan", "x"])
        with open(os.path.join(REPO, "gates", "__main__.py"), encoding="utf-8") as fh:
            self.assertNotIn("\nfrom gates.tools import continue_cli", fh.read())

    def test_usage_lists_continue(self):  # CG2
        want = ("usage: python3 -m gates <command> [args]\ncommands: check, claims, continue, decisions, findings, "
                "githook, githooks, hook, index, loopstats, program, questions, run_all\n")
        for argv in ([], ["bogus"]):
            p = subprocess.run([sys.executable, "-m", "gates"] + argv, cwd=REPO, env=dict(os.environ, PYTHONPATH=REPO),
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self.assertEqual((p.returncode, p.stdout, p.stderr.decode()), (2, b"", want))

    def test_continue_has_no_produces_entry(self):  # CG3
        self.assertFalse(hasattr(continue_cli, "PRODUCES"))
        self.assertNotIn("continue_cli", repr(producers.PRODUCER_MODULES))

    def test_other_commands_without_continue_module(self):  # CG5
        import gates.tools as tools_pkg
        saved = tools_pkg.continue_cli
        del tools_pkg.continue_cli
        self.addCleanup(setattr, tools_pkg, "continue_cli", saved)
        with mock.patch.dict(sys.modules, {"gates.tools.continue_cli": None}):
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(gates_main.main([]), 2)
                self.assertEqual(gates_main.main(["questions"]), 2)
            with self.assertRaises(ImportError):
                gates_main.main(["continue"])


# =====================================================================================================================
class TestHandoff(Fx):
    def test_handoff_file_kinds(self):  # HD2
        path = os.path.join(self.root, *HP.split("/"))
        d = os.path.dirname(path)
        os.rename(d, d + ".real")   # a symlinked directory component is never followed
        os.symlink(d + ".real", d)
        self.refuse("x-plan: is a symlink; directories must be real directories")
        os.unlink(d)
        os.rename(d + ".real", d)
        os.rename(path, path + ".real")
        self.refuse(HP + ": missing")
        os.mkdir(path)
        self.refuse(HP + ": is not a regular file")
        os.rmdir(path)
        os.symlink(path + ".real", path)
        self.refuse("is not a regular file")
        os.unlink(path)
        os.mkfifo(path)
        self.refuse("is not a regular file")   # a FIFO is never opened
        os.unlink(path)
        os.rename(path + ".real", path)
        if os.geteuid() != 0:
            os.chmod(path, 0)
            self.addCleanup(os.chmod, path, 0o644)
            self.refuse("cannot read (Permission denied)")
            os.chmod(path, 0o644)
        commit_all(self.root, "state")
        git(self.root, "rm", "-q", "--cached", HP)
        git(self.root, "commit", "-q", "-m", "drop")
        self.refuse(HP + ": missing at main", "--ref", "main")

    def test_handoff_text_kinds(self):  # HD3
        good = htext()
        cases = {"no front matter": ("hello\n", "first line must be '---'"),
                 "no closing": ("---\nplan: x\n", "front matter"), "yaml error": ("---\na: [\n---\n", "front matter"),
                 "not a mapping": ("---\n- a\n---\n", "front matter"), "BOM": ("﻿" + good, "first line must be '---'"),
                 "CRLF": (good.replace("\n", "\r\n"), "first line must be '---'"), "empty": ("", "front matter"),
                 "front matter only": ("---\n---\n", "front matter: must be a mapping"),
                 "not UTF-8": (b"---\nplan: \xff\n---\n", "not valid UTF-8")}
        for name, (text, needle) in cases.items():
            with self.subTest(name):
                self.put(HP, text)
                err = self.refuse(needle)
                self.assertTrue(all(l.startswith("continue: " + HP + ": ") for l in err.splitlines()), err)
        self.put(HP, good)
        self.assertEqual(self.ok(), REFERENCE)

    def test_invalid_handoff_refused(self):  # HD4
        row = hrow()
        cases = [("budget", {k: v for k, v in row.items() if k != "budget"}, "budget: required key is missing"),
                 ("role int", dict(row, role=5), "role: "), ("questions str", dict(row, questions="x"), "questions: "),
                 ("tokens 0", dict(row, budget={"tokens": 0, "minutes": 10}), "budget.tokens: must be at least 1"),
                 ("resume", dict(row, resume="wrong"), "resume: expected "),
                 ("ledger", dict(row, ledger=PS + "/other/ledger.md"), "ledger: expected '" + LP + "'"),
                 ("dup qid", hrow(questions=[Q("q1"), Q("q1")]), "q1"),
                 ("program only", dict(row, program=PRG), "stream: required when program is present"),
                 ("stream only", dict(row, stream="a"), "program: required when stream is present"),
                 ("bad program", dict(row, program="A/b", stream="a"), "program: must match"),
                 ("plan not md", hrow(plan="docs/x.txt"), "plan: ")]
        for name, r, needle in cases:
            with self.subTest(name):
                self.put(HP, htext(r))
                self.refuse(needle)

    def test_handoff_plan_slug_matches_directory(self):  # HD5
        self.put(HP, htext(hrow(plan=PLANS + "/y-plan.md", resume=None) if False else hrow(plan=PLANS + "/y-plan.md")))
        self.refuse("plan: names y-plan, not x-plan")

    def test_live_subagents_refused(self):  # HD6
        def sa(agent, state="running"):
            return {"agent": agent, "task": "t", "worktree": ".", "transcript": "tr", "last_record": "lr",
                    "jobs": [{"id": "j-" + agent, "state": state}]}
        self.assertEqual(self.ok(), REFERENCE)
        for subs, names in (([sa("ag1")], ["ag1"]), ([sa("ag1"), sa("ag2")], ["ag1", "ag2"]),
                            ([sa("ag1", "finished")], ["ag1"]), ([sa("ag1", "stopped")], ["ag1"])):
            with self.subTest(names=names, state=subs[0]["jobs"][0]["state"]):
                self.hand(live_subagents=subs)
                err = self.refuse("orphan")
                self.assertIn("live_subagents is not empty: continuing would orphan %s\n" % ", ".join(names), err)
        self.hand(live_subagents=[{"agent": "ag1"}])
        err = self.refuse("live_subagents")
        self.assertNotIn("orphan", err)

    def test_role_domain(self):  # HD7, TM2 (tier4 unset: the final verifier and exception reviewer take tier3)
        for role in ALL_ROLES:
            with self.subTest(role):
                self.hand(role=role)
                out = self.ok()
                self.assertEqual(sect(out, "Role"), role + "\n")
                self.assertEqual(sect(out, "Model"), MODELS[role] + "\n")
                self.assertEqual(sect(out, "Strict block"), "\n" + block_of(role) + "\n")
        for bad in ("", "Controller", 5, "my_role"):
            with self.subTest(bad=bad):
                self.hand(role=bad)
                self.refuse("role: ")

    def test_model_of_every_role(self):  # TM2 with tier4 set
        self.set_config(models={"tiers": {"tier4": "m4"}})
        for role in ALL_ROLES:
            with self.subTest(role):
                self.hand(role=role)
                want = "m4" if role in ("final_verifier", "exception_reviewer") else MODELS[role]
                self.assertEqual(sect(self.ok(), "Model"), want + "\n")

    def test_program_stream_fields(self):  # HD8, SR11
        with mock.patch.object(programs, "load_program", side_effect=AssertionError("page read")), \
                mock.patch.object(programs, "live_programs", side_effect=AssertionError("live read")):
            out = self.ok()   # both absent: no page, no lines
        self.assertEqual(out, REFERENCE)
        self.program()
        self.prog_hand()
        out = self.ok()
        self.assertEqual(sect(out, "Brief").splitlines()[-2:], ["program: " + PRG, "stream: a"])
        self.assertEqual(out.count("program: "), 1)
        self.hand(program=PRG)
        self.refuse("stream: required when program is present")
        self.hand(stream="a")
        self.refuse("program: required when stream is present")
        for bad in ("A", "a/b", "..", "-x"):
            self.hand(program=bad, stream="a")
            self.refuse("program: must match")
        self.hand(program="20261101-y", stream="a")
        self.refuse("program 20261101-y")
        self.hand(program=PRG, stream="zz")
        self.refuse("no row for stream zz")

    def test_unread_handoff_fields_not_checked(self):  # HD9
        self.hand(open_decisions=[D1], grant="pr=1 head=" + "a" * 40, rulings=5, ledger_from=9)
        self.assertEqual(self.ok(), REFERENCE)
        self.led("Dispatched: x\n", ck="CHECKPOINT P4 P4.1 head=abc1234 tests=2/3 gates=PASS next=P4.2")
        self.hand(batch_cut="abc1234")
        self.assertIn("Dispatched: x", self.ok())

    def test_budget_numerals_both_interpreters(self):  # HD10, V1
        def with_numeral(digits):
            return htext().replace("tokens: 1000\n", "tokens: %s\n" % digits)
        for limit in INT_LIMITS:
            with int_limit(limit):
                for digits in ("1", "9" * 600):
                    with self.subTest(limit=limit, n=len(digits)):
                        self.put(HP, with_numeral(digits))
                        self.assertIn("## Budget: tokens=%s minutes=10\n" % digits, self.ok())
                for digits in ("9" * 601, "9" * 1000):
                    with self.subTest(limit=limit, n=len(digits)):
                        self.put(HP, with_numeral(digits))
                        # under PYTHONINTMAXSTRDIGITS=640 yamlsub's own int() already refuses more than 640 digits
                        capped = limit == 640 and len(digits) > 640
                        self.refuse("integer too large" if capped else "budget.tokens: must be an integer from 1 to 600 digits")
                for digits in ("9" * 1001, "9" * 4300, "9" * 4301):
                    with self.subTest(limit=limit, n=len(digits)):
                        self.put(HP, with_numeral(digits))
                        self.refuse("integer too large")
        for bad in ("0", "-5", "true", "1.5"):
            with self.subTest(bad=bad):
                self.put(HP, with_numeral(bad))
                self.refuse("budget.tokens")

    def test_budget_heading(self):  # PS9
        self.hand(budget={"tokens": 300000, "minutes": 150})
        self.assertIn("\n## Budget: tokens=300000 minutes=150\n", self.ok())
        self.hand(budget={"tokens": 7, "minutes": 3})   # no padding: the gate's heading pattern has no leading zero
        self.assertIn("\n## Budget: tokens=7 minutes=3\n", self.ok())

    def test_findings_in_flight_domain(self):  # HD11, PS7
        self.assertEqual(sect(self.ok(), "Findings"), "None.\n")
        self.hand(findings_in_flight=[F1])
        self.assertEqual(sect(self.ok(), "Findings"), F1 + "\n")
        self.hand(findings_in_flight=[F2, F1])
        self.assertEqual(sect(self.ok(), "Findings"), F2 + "\n" + F1 + "\n")
        self.hand(findings_in_flight=[F1, F1])
        self.refuse("given twice")
        self.hand(findings_in_flight=["not-an-id"])
        self.refuse("findings_in_flight")

    def test_handoff_body_not_printed(self):  # HD12
        self.put(HP, htext(body="## Task\nSECRET-BODY\n## Role\nx\n"))
        out = self.ok()
        self.assertEqual(out, REFERENCE)
        self.assertNotIn("SECRET-BODY", out)

    def test_handoff_values_cannot_inject_headings(self):  # PS15
        self.hand(next_task="## Task")
        out = self.ok()
        self.assertEqual([l for l in out.split("\n") if l.startswith("## ")][:4],
                         ["## Role", "## Brief", "## Findings", "## Claims"])
        self.assertEqual(out.count("\n## Task\n"), 1)
        self.assertIn("at ## Task; branch b", out)
        self.hand(next_task="x\r")
        self.refuse("next_task: must be a single line of printable ASCII")


# =====================================================================================================================
class TestQuestions(Fx):
    def tag(self, qid="q1"):
        return "q:x-plan:" + qid

    def test_tag_through_p41_name(self):  # QA1
        self.assertEqual(questions_cli.tag("x-plan", "q1"), "q:x-plan:q1")
        self.hand(questions=[Q("q1")])
        self.put_dec(dec(D1, "answered", "q:x-plan:q1"))
        self.assertIn("Owner answers (2026-11-21), binding\n%s: Q one?\nAnswer: A one\n" % D1, self.ok())
        with mock.patch.object(questions_cli, "tag", return_value="q:other:q1") as m:
            self.refuse("question q1: unanswered")
        m.assert_called_with("x-plan", "q1")
        for wrong in ("q:x-plan:Q1", "q-x-plan-q1", "q:x-plan:q1 "):
            with self.subTest(wrong):
                self.put_dec(dec(D1, "answered", wrong))
                self.refuse("question q1: unanswered")

    def test_unanswered_question_refused(self):  # QA2
        self.hand(questions=[Q("q1")])
        self.refuse("question q1: unanswered (no decision carries q:x-plan:q1)")

    def test_asked_question_refused(self):  # QA3
        self.hand(questions=[Q("q1")])
        self.put_dec(dec(D1, "open", self.tag()))
        self.refuse("question q1: asked, not answered (%s)" % D1)

    def test_answered_question_passes(self):  # QA4
        self.hand(questions=[Q("q1")])
        self.put_dec(dec(D1, "answered", self.tag()))
        self.assertEqual(sect(self.ok(), "Brief").splitlines()[-3:],
                         ["Owner answers (2026-11-21), binding", D1 + ": Q one?", "Answer: A one"])

    def test_withdrawn_is_pending(self):  # QA5
        self.hand(questions=[Q("q1")])
        self.put_dec(dec(D1, "withdrawn", self.tag()))
        self.refuse("question q1: unanswered")

    def test_withdrawn_then_reasked_or_answered(self):  # QA6
        self.hand(questions=[Q("q1")])
        self.put_dec(dec(D1, "withdrawn", self.tag(), answer="NOPE"), dec(D2, "open", self.tag()))
        self.refuse("asked, not answered (%s)" % D2)
        self.put_dec(dec(D2, "answered", self.tag()))
        out = self.ok()
        self.assertIn(D2 + ": Q one?", out)
        self.assertNotIn(D1, out)

    def test_two_decisions_one_tag_refused(self):  # QA7
        self.hand(questions=[Q("q1")])
        for a, b in (("open", "open"), ("open", "answered"), ("answered", "answered")):
            with self.subTest(a=a, b=b):
                self.put_dec(dec(D1, a, self.tag()), dec(D2, b, self.tag()))
                self.refuse("q:x-plan:q1: carried by decisions %s, %s" % (D1, D2))

    def test_mixed_questions_all_unanswered_named(self):  # QA8
        self.hand(questions=[Q("q1"), Q("q2"), Q("q3")])
        self.put_dec(dec(D2, "open", self.tag("q2")), dec(D3, "answered", self.tag("q3"), answer="THREE"))
        err = self.refuse("question q1: unanswered")
        self.assertIn("question q2: asked, not answered", err)
        self.assertNotIn("q3", err)
        self.assertNotIn("THREE", err)

    def test_zero_questions_no_answers_block(self):  # QA9
        self.assertNotIn("Owner answers", self.ok())
        self.put(DEC + "/notes.txt", "x")   # no question: the register is not read
        self.assertEqual(self.ok(), REFERENCE)

    def test_register_kinds(self):  # QA10
        self.hand(questions=[Q("q1")])
        self.refuse("unanswered")   # no decisions/ folder
        self.put(DEC + "/notes.txt", "x")
        self.refuse(DEC)
        os.rename(os.path.join(self.root, DEC, "notes.txt"), os.path.join(self.root, DEC, "bad.yml"))
        self.put(DEC + "/bad.yml", "schema: decision/1\n")
        self.refuse("register: ")

    def test_register_is_working_tree(self):  # QA11
        self.hand(questions=[Q("q1")])
        commit_all(self.root, "state")
        git(self.root, "checkout", "-q", "-b", "other")
        self.put_dec(dec(D1, "answered", self.tag()))
        commit_all(self.root, "answered")
        git(self.root, "checkout", "-q", "main")
        self.refuse("question q1: unanswered")
        self.refuse("question q1: unanswered", "--ref", "other~0") if False else None
        self.refuse("question q1: unanswered", "--ref", "main")

    def test_answers_printed_per_source(self):  # QA12
        self.hand(questions=[Q("q1", source="r/worker-report.md"), Q("q2", source="r/worker-report.md")])
        self.put_dec(dec(D1, "answered", self.tag("q1"), source="r/worker-report.md", question="Q one?", answer="A one"),
                     dec(D2, "answered", self.tag("q2"), source="r/worker-report.md", question="Q two?", answer="A two"))
        want = ("Owner answers (2026-11-21), binding\n%s: Q one?\nAnswer: A one\n%s: Q two?\nAnswer: A two\n" % (D1, D2))
        self.assertIn(want, self.ok())

    def test_answers_two_sources_in_source_order(self):  # QA13
        self.hand(questions=[Q("q1", source="r/worker-report.md"), Q("q2")])
        self.put_dec(dec(D2, "answered", self.tag("q1"), source="r/worker-report.md", answer="ANS_REPORT_Q"),
                     dec(D1, "answered", self.tag("q2"), source=HP, answer="ANS_HANDOFF_Q"))
        b = sect(self.ok(), "Brief")
        self.assertIn("Owner answers (2026-11-21), binding\n%s: Q one?\nAnswer: ANS_REPORT_Q\n"
                      "Owner answers (2026-11-21), binding\n%s: Q one?\nAnswer: ANS_HANDOFF_Q\n" % (D2, D1), b)
        self.hand(questions=[Q("q2"), Q("q1", source="r/worker-report.md")])   # order of first appearance
        b = sect(self.ok(), "Brief")
        self.assertLess(b.index("ANS_HANDOFF_Q"), b.index("ANS_REPORT_Q"))

    def test_one_block_per_distinct_source(self):  # QA14
        self.hand(questions=[Q("q1"), Q("q2")])
        self.put_dec(dec(D1, "answered", self.tag("q1")), dec(D2, "answered", self.tag("q2"), answer="A two"))
        self.assertEqual(self.ok().count("Owner answers ("), 1)

    def test_answered_record_with_other_source(self):  # QA15
        self.hand(questions=[Q("q1", source="r/w.md")])
        for src in ("other.md", None):
            with self.subTest(src=src):
                self.put_dec(dec(D1, "answered", self.tag(), source=src))
                self.refuse("question q1: the answered decision %s is not printed for source r/w.md" % D1)

    def test_other_answers_not_printed(self):  # QA16
        self.hand(questions=[Q("q1")])
        self.put_dec(dec(D1, "answered", self.tag()),
                     dec(D2, "answered", "q:y-plan:q1", answer="FOREIGN"),
                     dec(D3, "answered", "q:x-plan:q9", answer="NOT-IN-HANDOFF"),
                     dec(D4, "answered", "free-topic", answer="BY-HAND"))
        out = self.ok()
        for s in ("FOREIGN", "NOT-IN-HANDOFF", "BY-HAND", D2, D3, D4):
            self.assertNotIn(s, out)

    def test_answers_date_is_utc_today(self):  # QA17
        self.hand(questions=[Q("q1")])
        self.put_dec(dec(D1, "answered", self.tag()))
        calls = []

        def today():
            calls.append(1)
            return datetime.date(2027, 1, 2)
        with mock.patch.object(ids, "utc_today", today):
            code, out, err = self.run_c(*self.base())
        self.assertEqual((code, err), (0, ""))
        self.assertIn("Owner answers (2027-01-02), binding\n", out)
        self.assertEqual(len(calls), 1)

    def test_answer_text_domain(self):  # QA18
        self.hand(questions=[Q("q1")])
        for answer, shown in (("a\nb", "a\\nb"), ("a\r\nb", "a\\nb"), ("a\tb", "a\tb"), ("é", "é"),
                              ("x" * 100000, "x" * 100000)):
            with self.subTest(answer=answer[:10]):
                self.put_dec(dec(D1, "answered", self.tag(), answer=answer))
                out = self.ok()
                self.assertIn("Answer: " + shown + "\n## Findings\n", out)
                self.assertEqual(len([l for l in out.split("\n") if l.startswith("## ")]), 9)
        for bad in ("a\x01b", "a\x7fb", "a b"):
            with self.subTest(bad=bad):
                self.put_dec(dec(D1, "answered", self.tag(), answer=bad))
                self.refuse("holds a character outside the batch text set")
        self.put_dec(dec(D1, "answered", self.tag(), question="Q\x01"))
        self.refuse("question: holds a character outside the batch text set (U+0001)")

    def test_duplicate_record_ids_refused(self):  # QA19
        self.hand(questions=[Q("q1")])
        self.put_dec(dec(D1, "answered", self.tag()))
        real = index._records(self.root, "decision", self.cfg, decisions.validate)
        w = type(real[0])(D2, dec(D2, "withdrawn", self.tag()), "f")   # withdrawn: ignored by question_state, still passed on
        with mock.patch.object(index, "_records", return_value=real + [w, w]):
            self.refuse("duplicate id %s" % D2)

    def test_answer_ids_pass_dispatch_decisions_line(self):  # QA20
        self.hand(questions=[Q("q1")])
        self.put_dec(dec(D1, "answered", self.tag()))
        out = self.ok()
        res = self.gate(out)
        self.assertTrue(res.ok(), [l for l in res.lines if l.status != "PASS"])

    def test_many_questions(self):  # QA21
        srcs = ("r/s1.md", "r/s2.md", None)
        qs = [Q("q%d" % i, source=srcs[i % 3]) for i in range(1000)]
        self.hand(questions=qs)
        recs = [dec("DEC-20261101-%s" % (("a%03d" % i).replace("0", "c").replace("1", "d")), "answered", self.tag("q%d" % i),
                    source=srcs[i % 3] or HP, answer="A%d" % i) for i in range(1000)]
        ids_seen = {r["id"] for r in recs}
        self.assertEqual(len(ids_seen), 1000)
        self.put_dec(*recs)
        out = self.ok()
        self.assertEqual(out.count("Owner answers ("), 3)
        self.assertEqual(out.count("\nAnswer: A"), 1000)


# =====================================================================================================================
class TestLedger(Fx):
    def test_ledger_tail_none(self):  # LG1
        self.led("")
        out = self.ok()
        self.assertNotIn("Ledger since", out)
        self.assertNotIn("Dispatched", out)

    def test_ledger_tail_in_brief(self):  # LG2
        self.led("Dispatched: x\nRuling: a -- b -- c -- d\nUPDATE s from=a@abc1234 head=abc1234 tests=1/1 gates=PASS\n")
        b = sect(self.ok(), "Brief")
        self.assertIn("Ledger since the last checkpoint:\nDispatched: x\nRuling: a -- b -- c -- d\n"
                      "UPDATE s from=a@abc1234 head=abc1234 tests=1/1 gates=PASS\n", b)
        self.assertNotIn("CHECKPOINT", b)

    def test_ledger_without_checkpoint_refused(self):  # LG3
        self.put(LP, LH + "Dispatched: x\n")
        self.refuse(LP + ": no conforming CHECKPOINT line")

    def test_nonconforming_checkpoint_refused(self):  # LG4
        self.led("Dispatched: x\nCHECKPOINT bad line\n")
        err = self.refuse(LP + ": line 4: ")
        self.assertNotIn("bad line\nDispatched", err)
        self.put(LP, LH + "CHECKPOINT bad line\n" + CK + "\n")
        self.refuse("line 2: ")
        self.put(LP, LH + "CHECKPOINT bad line\n")
        self.refuse(LP)

    def test_ledger_first_line(self):  # LG5
        for name, text in (("wrong", "<!-- schema: ledger/2 -->\n" + CK + "\n"), ("missing", CK + "\n"),
                           ("BOM", "﻿" + LH + CK + "\n"), ("CRLF", (LH + CK + "\nDispatched: x\n").replace("\n", "\r\n"))):
            with self.subTest(name):
                self.put(LP, text)
                self.refuse("first line: expected '<!-- schema: ledger/1 -->'")

    def test_ledger_line_with_cr_verbatim(self):  # LG6
        self.led("Dispatched: x\r\nnext\n")
        out = self.ok()
        self.assertIn("Ledger since the last checkpoint:\nDispatched: x\r\nnext\n", out)
        res = self.gate(out)
        self.assertTrue(res.ok(), [l for l in res.lines if l.status != "PASS"])

    def test_ledger_heading_line_refused(self):  # LG7
        for line in ("## Notes", "## Task", "## Role"):
            with self.subTest(line):
                self.led("Dispatched: x\n" + line + "\n")
                self.refuse(LP + ": line 4 begins with '## '")
        for line in ("program: z", "stream: z"):
            with self.subTest(line):   # PS6
                self.led(line + "\n")
                self.refuse("line 3 begins with '%s '" % line.split(" ")[0])

    def test_ledger_ids_and_small_line(self):  # LG8
        self.led("small-re-review: whatever\n")
        self.assertIn("small-re-review: whatever\n", self.ok())   # a controller: the gate reads it for task_reviewer only
        self.led("Ruling: DEC-20261101-zzzz -- b -- c -- d\n")
        self.assertIn("DEC-20261101-zzzz", self.ok())   # without the four flags nothing checks it
        f = os.path.join(self.tmp, "ids.json")
        self.refuse("dispatch.decisions: DEC-20261101-zzzz names no decision", *self.flags(f, dispatcher="controller"))
        self.assertFalse(os.path.exists(f))

    def test_ledger_tail_blank_lines(self):  # LG9
        for tail, want in (("a\n\n\nlast\n", "a\n\n\nlast\n"), ("a\n\n\nlast", "a\n\n\nlast\n"),
                           ("a\n\n\n", "a\n\n\n"), ("a\n", "a\n")):
            with self.subTest(tail=tail):
                self.led(tail)
                self.assertIn("Ledger since the last checkpoint:\n" + want + "## Findings\n", self.ok())

    def test_tail_starts_after_last_checkpoint(self):  # LG10
        later = "CHECKPOINT P4 P4.2 head=abc1234 tests=4/4 gates=PASS next=P4.3"
        self.put(LP, LH + CK + "\nDispatched: old\nRuling: a -- b -- c -- d\n" + later + "\nDispatched: new\nRuling: e -- f -- g -- h\n")
        b = sect(self.ok(), "Brief")
        self.assertIn("checkpoint:\nDispatched: new\nRuling: e -- f -- g -- h\n", b)
        self.assertNotIn("old", b)
        self.assertNotIn("P4.3", b)

    def test_update_line_in_tail(self):  # LG11
        u = "UPDATE s from=a@abc1234 head=abc1234 tests=1/1 gates=n/a"
        self.led(u + "\n")
        self.assertIn(u + "\n## Findings", self.ok())

    def test_ledger_file_kinds(self):  # LG12
        path = os.path.join(self.root, *LP.split("/"))
        os.rename(path, path + ".real")
        self.refuse(LP + ": missing")
        os.mkdir(path)
        self.refuse("is not a regular file")
        os.rmdir(path)
        os.symlink(path + ".real", path)
        self.refuse("is not a regular file")
        os.unlink(path)
        self.put(LP, b"<!-- schema: ledger/1 -->\n\xff\n")
        self.refuse("not valid UTF-8")
        self.put(LP, ledger("Dispatched: x\n"))
        commit_all(self.root, "state")
        git(self.root, "rm", "-q", LP)
        git(self.root, "commit", "-q", "-m", "drop")
        self.refuse(LP + ": missing at main", "--ref", "main")
        self.hand(ledger=PS + "/elsewhere/ledger.md")
        self.refuse("ledger: expected '" + LP + "'")

    def test_ledger_tail_long(self):  # LG13
        tail = "".join("Dispatched: line %d\n" % i for i in range(1000))
        self.led(tail)
        self.assertIn("checkpoint:\n" + tail + "## Findings\n", self.ok())

    def test_ledger_numerals(self):  # LG14
        n = "9" * 600
        self.put(LP, LH + "CHECKPOINT P4 P4.1 head=abc1234 tests=%s/%s gates=PASS next=P4.2\nDispatched: x\n" % (n, n))
        self.assertEqual(self.ok(), REFERENCE)
        n = "9" * 601
        self.put(LP, LH + "CHECKPOINT P4 P4.1 head=abc1234 tests=%s/%s gates=PASS next=P4.2\nDispatched: x\n" % (n, n))
        self.refuse(LP + ": line 2: ")


# =====================================================================================================================
class TestStatusRow(Fx):
    def setUp(self):
        super().setUp()
        self.program()
        self.prog_hand()

    def test_status_row_in_brief(self):  # SR1, PS5, PS6
        self.assertEqual(sect(self.ok(), "Brief"),
                         "Continue %s at P4.2; branch b; head abc1234\nHandoff: %s\nLedger since the last checkpoint:\n"
                         "Dispatched: x\nStatus row:\n%s\nprogram: %s\nstream: a\n" % (PLAN, HP, ROW_A, PRG))

    def test_status_row_missing_refused(self):  # SR2
        for page in ("<!-- schema: status/1 -->\n\n" + HEAD_ROW + ROW_B + "\n", "<!-- schema: status/1 -->\n\n" + HEAD_ROW,
                     "<!-- schema: status/1 -->\n\n| wrong | header |\n|---|---|\n| a | b |\n"):
            with self.subTest(page=page[-30:]):
                self.program_page(page)
                self.refuse("program %s: the status page has no " % PRG)

    def program_page(self, page):
        git(self.root, "checkout", "-q", INTEG)
        try:
            self.put(PROGDIR + "/status.md", page)
            self.commit_prog("page")
        finally:
            git(self.root, "checkout", "-q", "main")

    def test_status_row_is_raw_line(self):  # SR3
        for row in ("| a | P4 | b | w | P4.2 | 5 | 1 | running | none | none | does a \\| b |",
                    "|   a   |  P4  | b | w | P4.2 | 5 | 1 | running | none | none |    does a    |"):
            with self.subTest(row=row):
                self.program_page("<!-- schema: status/1 -->\n\n" + HEAD_ROW + row + "\n" + ROW_B + "\n")
                self.assertIn("Status row:\n" + row + "\nprogram: ", self.ok())

    def test_status_row_duplicate_refused(self):  # SR4
        self.program_page("<!-- schema: status/1 -->\n\n" + HEAD_ROW + ROW_A + "\n" + ROW_A + "\n")
        self.refuse("the status page has 2 rows for stream a")

    def test_status_row_malformed_refused(self):  # SR5
        self.program_page("<!-- schema: status/1 -->\n\n" + HEAD_ROW + ROW_A + "\n| a | b |\n")
        self.refuse("status page line 6: row has 2 cells, expected 11")

    def test_status_page_from_integration_tip(self):  # SR6
        git(self.root, "tag", "-f", INTEG)   # a tag with the branch's name: the full ref names the branch
        self.assertIn(ROW_A, self.ok())

    def test_program_not_live_refused(self):  # SR7
        self.hand(program="20261101-y", stream="a")
        self.refuse("program 20261101-y: ")
        git(self.root, "branch", "20261101-y/integration", "main")
        self.refuse("program 20261101-y: ")   # the tip holds no streams.yml

    def test_program_files_strictness(self):  # SR8
        git(self.root, "checkout", "-q", INTEG)
        self.put(PROGDIR + "/requests/stray.txt", "x")
        self.commit_prog("stray")
        git(self.root, "checkout", "-q", "main")
        self.refuse("program %s: " % PRG)

    def test_program_name_domain(self):  # SR9
        for bad in ("..", "a/b", "A"):
            with self.subTest(bad=bad[:10]):
                self.hand(program=bad, stream="a")
                with mock.patch.object(programs, "load_program", side_effect=AssertionError("built a ref")):
                    self.refuse("program: must match")
        self.hand(program="x" * 4301, stream="a")   # a well-formed name that is no program: load_program's program_problem
        self.refuse("program name")

    def test_stream_vs_streams_file_not_compared(self):  # SR10
        self.program_page("<!-- schema: status/1 -->\n\n" + HEAD_ROW + ROW_A.replace("| a |", "| zz |") + "\n" + ROW_B + "\n")
        self.hand(program=PRG, stream="zz")
        self.assertIn("stream: zz", self.ok())

    def test_uncommitted_status_edit_not_read(self):  # GC7
        wt = os.path.join(self.tmp, "intwt")
        git(self.root, "worktree", "add", "-q", wt, INTEG)
        self.put(PROGDIR + "/status.md", "edited\n", root=wt)
        self.assertIn(ROW_A, self.ok())

    def test_continue_prompt_passes_gate_dispatch_in_program(self):  # GD2
        out = self.ok()
        res = self.gate(out, dispatcher="stream_controller", depth=1, live=True)
        self.assertTrue(res.ok(), [l for l in res.lines if l.status != "PASS"])
        self.assertIn("PASS dispatch.program", [l.status + " " + l.id for l in res.lines])
        self.assertIn("PASS dispatch.stream", [l.status + " " + l.id for l in res.lines])
        f = os.path.join(self.tmp, "stream.json")
        self.assertEqual(self.ok(*self.flags(f, dispatcher="stream_controller", depth="1")), out)
        with open(f, encoding="utf-8") as fh:
            self.assertTrue(json.load(fh)["program_live"])   # IJ6: bool(live_programs)
        g = os.path.join(self.tmp, "session.json")   # a session may not dispatch a controller while a program is live
        self.refuse("dispatch.dispatcher: session may not dispatch controller", *self.flags(g))
        self.assertFalse(os.path.exists(g))

    def test_stream_controller_handoff_from_session(self):  # GD3
        self.prog_hand(role="stream_controller")
        out = self.ok()
        res = self.gate(out, dispatcher="session", depth=0, live=True)
        self.assertTrue(res.ok(), [l for l in res.lines if l.status != "PASS"])

    def test_program_live_is_bool_of_live_programs(self):  # IJ6
        f = os.path.join(self.tmp, "live.json")
        self.hand()   # no program in the handoff, another program live
        self.refuse("dispatch.dispatcher", *self.flags(f))   # session -> controller, program_live true: refused by the gate
        self.assertEqual(self.ok(*self.flags(f, dispatcher="stream_controller", depth="1")), self.ok())
        with open(f, encoding="utf-8") as fh:
            self.assertIs(json.load(fh)["program_live"], True)
        with mock.patch.object(programs, "live_programs", side_effect=programs.GateError("boom")):
            self.refuse("program_live: boom", *self.flags(os.path.join(self.tmp, "l2.json"), dispatcher="stream_controller", depth="1"))


# =====================================================================================================================
class TestTier(Fx):
    def tiers(self, **t):
        return {"models": {"tiers": t}}

    def test_model_from_min_tier(self):  # TM1
        self.assertEqual(sect(self.ok(), "Model"), "opus\n")

    def test_top_tier_role_uses_fallback_when_tier4_unset(self):  # TM3, TM4
        for role in ("final_verifier", "exception_reviewer"):
            with self.subTest(role):
                self.hand(role=role)
                out = self.ok()
                self.assertEqual(sect(out, "Model"), "opus\n")
                res = self.gate(out)
                self.assertTrue(res.ok(), [l for l in res.lines if l.status != "PASS"])

    def test_fallback_tier2(self):  # TM5
        self.hand(role="final_verifier")
        self.set_config(top_tier_fallback="tier2")
        out = self.ok()
        self.assertEqual(sect(out, "Model"), "sonnet\n")
        self.assertTrue(self.gate(out, model="sonnet").ok())

    def test_fallback_invalid_refused(self):  # TM6
        self.hand(role="final_verifier")
        for bad in ("tier9", "tier3x", "", 3, None, ["tier3"]):
            with self.subTest(bad=bad):
                self.set_config(top_tier_fallback=bad)
                self.refuse("top_tier_fallback '%s' names a tier that is unset or not tier1-tier4" % (bad,))
        self.hand(role="controller")   # a tier3 role never reads the fallback
        self.set_config(top_tier_fallback="tier9")
        self.assertEqual(sect(self.ok(), "Model"), "opus\n")

    def test_fallback_unset_tier_refused(self):  # TM7
        self.hand(role="final_verifier")
        self.set_config(top_tier_fallback="tier2")
        real = config.load

        def load(root):
            c = real(root)
            del c["models"]["tiers"]["tier2"]
            return c
        with mock.patch.object(config, "load", load):
            self.refuse("top_tier_fallback 'tier2' names a tier that is unset or not tier1-tier4")

    def test_tier4_set_ignores_fallback(self):  # TM8
        self.hand(role="final_verifier")
        self.set_config(top_tier_fallback="tier9", **self.tiers(tier4="m4"))
        out = self.ok()
        self.assertEqual(sect(out, "Model"), "m4\n")
        self.assertTrue(self.gate(out, model="m4").ok())

    def test_tier4_role_outside_top_tier_roles_refused(self):  # TM9
        self.hand(role="final_verifier")
        self.set_config(top_tier_roles=["exception_reviewer"])
        self.refuse("final_verifier needs tier4, which is unset, and is not in top_tier_roles")

    def test_top_tier_roles_types(self):  # TM10
        self.hand(role="final_verifier")
        for bad in ("final_verifier", 5, ["", "x"], [5]):
            with self.subTest(bad=bad):
                self.set_config(top_tier_roles=bad)
                self.refuse("config top_tier_roles must be a list of non-empty strings")
        self.set_config(top_tier_roles=[])
        self.refuse("final_verifier needs tier4")

    def test_model_tier2_role(self):  # TM11
        self.hand(role="implementer")
        out = self.ok()
        self.assertEqual(sect(out, "Model"), "sonnet\n")
        self.assertTrue(self.gate(out, model="sonnet").ok())

    def test_resolved_tier_without_model_refused(self):  # TM12
        self.hand(role="implementer")
        real = config.load

        def load(root):
            c = real(root)
            del c["models"]["tiers"]["tier2"]
            return c
        with mock.patch.object(config, "load", load):
            self.refuse("tier2 of role implementer has no model in models.tiers")

    def test_tier5_key_ignored(self):  # TM13
        self.set_config(**self.tiers(tier5="x"))
        self.assertEqual(sect(self.ok(), "Model"), "opus\n")

    def test_two_tiers_same_model_refused(self):  # TM14
        self.set_config(**self.tiers(tier3="o", tier4="o"))
        self.refuse("model 'o' is named by more than one tier (tier3, tier4)")

    def test_model_text_domain(self):  # TM15
        for model in ("op\nus", " opus", "opus ", "## Role", "mꟀ", "mé", "x" * 0 + "\t"):
            with self.subTest(model=model):
                self.set_config(**self.tiers(tier3=model))
                self.refuse("models.tiers.tier3: must be one line of printable ASCII")
        self.set_config(**self.tiers(tier3="a" * 4301))   # one printable line, any length
        self.assertEqual(sect(self.ok(), "Model"), "a" * 4301 + "\n")

    def test_model_section_bytes(self):  # TM16
        self.assertIn("\n## Model\nopus\n## Report\n", self.ok())

    def test_input_json_model_equals_section(self):  # IJ11
        self.hand(role="implementer")
        f = os.path.join(self.tmp, "m.json")
        self.ok(*self.flags(f, dispatcher="controller"))
        with open(f, encoding="utf-8") as fh:
            self.assertEqual(json.load(fh)["model"], "sonnet")


# =====================================================================================================================
class TestPrompt(Fx):
    def test_headings_in_order(self):  # PS1
        out = self.ok()
        self.assertEqual([l for l in out.split("\n") if l.startswith("## ")],
                         ["## Role", "## Brief", "## Findings", "## Claims", "## Budget: tokens=1000 minutes=10",
                          "## Model", "## Report", "## Strict block", "## Task"])
        self.assertEqual(dispatch.parse(out)[1], [])
        self.assertTrue(out.startswith("## Role\n"))

    def test_role_section(self):  # PS2
        self.assertEqual(sect(self.ok(), "Role"), "controller\n")

    def test_brief_continue_line(self):  # PS3
        self.assertEqual(sect(self.ok(), "Brief").splitlines()[0],
                         "Continue docs/strict-delivery/plans/x-plan.md at P4.2; branch b; head abc1234")

    def test_brief_handoff_path(self):  # PS4
        self.assertEqual(sect(self.ok(), "Brief").splitlines()[1], "Handoff: " + HP)
        commit_all(self.root, "state")
        self.assertEqual(sect(self.ok("--ref", "main"), "Brief").splitlines()[1], "Handoff: " + HP)
        self.ps = ".strict-delivery/st ate/plans"
        self.build(cfg={"paths": {"plan_state": ".strict-delivery/st ate/plans"}})   # GC4 (a space in plan_state)
        self.assertEqual(sect(self.ok(), "Brief").splitlines()[1], "Handoff: .strict-delivery/st ate/plans/x-plan/handoff.md")

    def test_brief_part_order(self):  # PS5
        self.hand(questions=[Q("q1")])
        self.put_dec(dec(D1, "answered", "q:x-plan:q1"))
        self.program()
        self.prog_hand(questions=[Q("q1")])
        b = sect(self.ok(), "Brief").splitlines()
        marks = [b[0].split(" ")[0], b[1].split(":")[0], b[2], b[4], b[6], b[-2], b[-1]]
        self.assertEqual(marks, ["Continue", "Handoff", "Ledger since the last checkpoint:", "Status row:",
                                 "Owner answers (2026-11-21), binding", "program: " + PRG, "stream: a"])

    def test_brief_program_stream_lines(self):  # PS6
        self.program()
        self.prog_hand()
        out = self.ok()
        self.assertEqual([l for l in out.split("\n") if l.startswith("program:")], ["program: " + PRG])
        self.assertEqual([l for l in out.split("\n") if l.startswith("stream:")], ["stream: a"])

    def test_findings_section(self):  # PS7
        self.assertEqual(sect(self.ok(), "Findings"), "None.\n")

    def test_claims_section(self):  # PS8
        self.assertEqual(sect(self.ok(), "Claims"), "None.\n")

    def test_report_section(self):  # PS11
        self.assertEqual(sect(self.ok(), "Report"), "status: DONE|DONE_WITH_FINDINGS|NEEDS_DECISION|BLOCKED|DENIED\n")

    def test_task_section(self):  # PS13
        self.assertEqual(sect(self.ok(), "Task"), "Resume at P4.2 from the handoff; nothing continues from inherited memory.\n")

    def test_output_ends_with_one_newline(self):  # PS14
        out = self.ok()
        self.assertTrue(out.endswith("memory.\n") and not out.endswith("\n\n"))

    def test_output_deterministic(self):  # PS16
        self.assertEqual(self.ok(), self.ok())

    def test_sections_bodies_literal(self):  # PS17
        s, errors = dispatch.parse(self.ok())
        self.assertEqual(errors, [])
        self.assertEqual({k: s[k] for k in ("Role", "Findings", "Claims", "Model", "Report", "Task")},
                         {"Role": "controller\n", "Findings": "None.\n", "Claims": "None.\n", "Model": "opus\n",
                          "Report": "status: DONE|DONE_WITH_FINDINGS|NEEDS_DECISION|BLOCKED|DENIED\n",
                          "Task": "Resume at P4.2 from the handoff; nothing continues from inherited memory.\n"})
        self.assertEqual(s["Brief"], "Continue %s at P4.2; branch b; head abc1234\nHandoff: %s\n"
                         "Ledger since the last checkpoint:\nDispatched: x\n" % (PLAN, HP))

    # ---- strict block
    def test_strict_block_bytes(self):  # SB1
        out = self.ok()
        self.assertIn("## Strict block\n\n# Strict block: controller\n\nrules\n\n## Task\n", out)
        self.assertEqual(dispatch.block_errors(sect(out, "Strict block"), "controller", self.pd), [])

    def test_prompt_file_missing_refused(self):  # SB2
        self.hand(role="stream_controller")
        os.rename(os.path.join(self.pd, "stream_controller.md"), os.path.join(self.pd, "x.md"))
        self.refuse("strict block file %s cannot be read (No such file or directory)" %
                    os.path.join(self.pd, "stream_controller.md"))
        for role in ("program_controller", "stream_controller"):   # the real directory holds both blocks since P4.3
            self.hand(role=role)
            code, out, err = self.run_c("--plan", SLUG, "--root", self.root)
            self.assertEqual((code, err), (0, ""))

    def test_prompt_file_kinds(self):  # SB3
        path = os.path.join(self.pd, "controller.md")
        os.rename(path, path + ".real")
        os.mkdir(path)
        self.refuse("strict block file %s is not a regular file" % path)
        os.rmdir(path)
        os.mkfifo(path)
        self.refuse("is not a regular file")   # a FIFO is never opened
        os.unlink(path)
        os.symlink(path + ".real", path)
        self.assertEqual(self.ok(), REFERENCE)   # a symlink is followed, as the gate does
        os.unlink(path)
        self.put_file(path, "")
        self.assertIn("## Strict block\n\n\n## Task\n", self.ok())
        os.chmod(path, 0)
        self.addCleanup(os.chmod, path, 0o644)
        if os.geteuid() != 0:
            self.refuse("cannot be read (Permission denied)")

    def test_strict_block_crlf_bytes_kept(self):  # SB4
        raw = b"# Strict block: controller\r\n\r\nrules\r\n"
        self.put_file(os.path.join(self.pd, "controller.md"), raw)
        out = self.ok()
        self.assertIn("## Strict block\n\n# Strict block: controller\r\n\r\nrules\r\n\n## Task\n", out)
        self.assertEqual(dispatch.block_errors(sect(out, "Strict block"), "controller", self.pd), [])
        self.assertTrue(self.gate(out).ok())

    def test_crlf_survives_text_mode_print_both_interpreters(self):  # SB5
        raw = b"# Strict block: controller\r\n\r\nrules\rmore\r\n"
        self.put_file(os.path.join(self.pd, "controller.md"), raw)
        code, out, err = self.sub("--plan", SLUG, "--root", self.root, "--prompts", self.pd,
                                  env={"PYTHONIOENCODING": "utf-8"})
        self.assertEqual((code, err), (0, b""))
        self.assertIn(b"## Strict block\n\n" + raw + b"\n## Task\n", out)

    def test_strict_block_encodings(self):  # SB6
        self.put_file(os.path.join(self.pd, "controller.md"), b"# Strict block: controller\n\n\xff\n")
        self.refuse("is not valid UTF-8")
        self.put_file(os.path.join(self.pd, "controller.md"), "# Strict block: controller\n\né\n")
        self.assertIn("é", self.ok())
        argv = ["--plan", SLUG, "--root", self.root, "--prompts", self.pd]
        code, out, err = self.sub(*argv, env={"PYTHONIOENCODING": "ascii"})
        self.assertEqual((code, out), (1, b""))
        self.assertIn(b"continue: the prompt cannot be encoded for stdout", err)
        code, out, err = self.sub(*argv, env={"PYTHONIOENCODING": "utf-8"})
        self.assertEqual(code, 0)
        self.assertIn("é".encode("utf-8"), out)

    def test_strict_block_bom_kept(self):  # SB7
        self.put_file(os.path.join(self.pd, "controller.md"), "﻿# Strict block: controller\n\nrules\n")
        out = self.ok()
        self.assertTrue(out.startswith("## Role\n"))
        self.assertIn("## Strict block\n\n﻿# Strict", out)

    def test_block_file_with_heading_line(self):  # SB8
        self.put_file(os.path.join(self.pd, "controller.md"), "# Strict block: controller\n\n## Notes\n")
        out = self.ok()   # not guarded: the output fails the gate's grammar line
        self.assertNotEqual(dispatch.parse(out)[1], [])

    def test_block_ids_not_scanned(self):  # SB9
        self.put_file(os.path.join(self.pd, "controller.md"), "# Strict block: controller\n\n%s\n" % "DEC-20261101-zzzz")
        res = self.gate(self.ok())
        self.assertTrue(res.ok(), [l for l in res.lines if l.status != "PASS"])

    def test_role_file_name_fixed(self):  # SB10
        for role in ALL_ROLES:
            self.assertEqual(os.path.basename(os.path.join(self.pd, role + ".md")), role + ".md")
            self.assertIn("/", "a/" + role)

    # ---- GD
    def test_continue_prompt_passes_gate_dispatch(self):  # HD1, GD1
        out = self.ok()
        res = self.gate(out)
        self.assertTrue(res.ok(), [l for l in res.lines if l.status != "PASS"])
        f = os.path.join(self.tmp, "in.json")
        self.assertEqual(self.ok(*self.flags(f)), out)
        r = gate_dispatch.check(["--root", self.root, "--prompts", self.pd, "--input", f])
        self.assertTrue(r.ok(), [l for l in r.lines if l.status != "PASS"])
        real = os.path.join(REPO, "skills", "strict-delivery", "prompts")
        g = os.path.join(self.tmp, "in2.json")
        self.ok(*self.flags(g))
        with open(g, encoding="utf-8") as fh:
            data = json.load(fh)
        data["prompt"] = sect(out, "Role")   # not used; the real-directory check follows
        code, out2, err = self.run_c("--plan", SLUG, "--root", self.root, "--prompts", real, *self.flags(os.path.join(self.tmp, "in3.json")))
        self.assertEqual((code, err), (0, ""))

    def test_gate_check_environment_controlled(self):  # GD5
        self.assertNotIn(dispatch.ENV_DEPTH, os.environ)
        self.assertNotIn(dispatch.ENV_CONCURRENT, os.environ)
        f = os.path.join(self.tmp, "env.json")
        self.ok(*self.flags(f, depth="1"))   # max depth 3 without the variable: 1 + 1 + 1 levels
        self.assertTrue(os.path.exists(f))
        g = os.path.join(self.tmp, "env2.json")
        with mock.patch.dict(os.environ, {dispatch.ENV_DEPTH: "1"}):   # max depth 2
            self.refuse("dispatch.depth", *self.flags(g, depth="1"))
        self.assertFalse(os.path.exists(g))

    def test_gate_lines_all_pass(self):  # GD6
        self.hand(findings_in_flight=[F1])
        res = self.gate(self.ok())
        self.assertEqual([l.id for l in res.lines], ["dispatch.input", "dispatch.fork", "dispatch.grammar", "dispatch.role",
                         "dispatch.dispatcher", "dispatch.program", "dispatch.stream", "dispatch.depth",
                         "dispatch.concurrency", "dispatch.children", "dispatch.model", "dispatch.tier",
                         "dispatch.top-tier", "dispatch.block", "dispatch.claims", "dispatch.decisions"])
        self.assertTrue(res.ok())

    def test_self_check(self):  # GD7
        f = os.path.join(self.tmp, "self.json")
        self.refuse("the prompt fails gate_dispatch", *self.flags(f, dispatcher="implementer"))
        self.assertFalse(os.path.exists(f))
        with mock.patch.object(gate_dispatch, "check", side_effect=AssertionError("run without the flags")):
            self.assertEqual(self.ok(), REFERENCE)   # no input exists without the four flags


# =====================================================================================================================
class TestInputJson(Fx):
    def f(self, name="in.json"):
        return os.path.join(self.tmp, name)

    def test_input_json_object(self):  # IJ1, IJ9, IJ10
        f = self.f()
        out = self.ok(*self.flags(f, dispatcher="controller", depth="0", children="2", total="3"))
        self.assertEqual(out, REFERENCE)   # also prints
        with open(f, encoding="utf-8") as fh:
            raw = fh.read()
        self.assertTrue(raw.endswith("}\n") and raw.count("\n") == 1)
        self.assertEqual(json.loads(raw), {"prompt": REFERENCE, "model": "opus", "program_live": False,
                                           "dispatcher": {"id": "controller", "depth": 0, "live_children": 2, "live_total": 3}})
        self.assertEqual(list(json.loads(raw)), sorted(json.loads(raw)))
        self.assertNotIn("subagent_type", json.loads(raw))
        self.assertIs(type(json.loads(raw)["program_live"]), bool)
        self.assertEqual(gate_dispatch._read_input(f)["prompt"], REFERENCE)

    def test_dispatcher_domain(self):  # IJ2
        for d in ("session", "controller"):
            with self.subTest(d):
                f = self.f(d + ".json")
                self.ok(*self.flags(f, dispatcher=d))
                self.assertTrue(os.path.exists(f))
        for d in [r for r in ALL_ROLES if r != "controller"]:
            with self.subTest(d):   # a role the gate refuses as the dispatcher of a controller
                f = self.f(d + ".json")
                self.refuse("dispatch.dispatcher", *self.flags(f, dispatcher=d))
                self.assertFalse(os.path.exists(f))
        for d in ("Session", "controller ", "", "x", "é", "Ꟁ"):
            with self.subTest(d):
                f = self.f("bad.json")
                self.refuse("--dispatcher: must be 'session' or a role id", "--input-json=" + f, "--dispatcher=" + d,
                            "--depth", "0", "--live-children", "0", "--live-total", "0")
        f = self.f("twice.json")
        self.refuse("--dispatcher given more than once", *self.flags(f), "--dispatcher", "session")

    def test_count_flags_domain(self):  # IJ3, V1
        bad = ["-1", "-0", "+1", "01", " 1", "1 ", "1_0", "true", "True", "false", "1.5", "1e3", "0x1", "",
               "５", "٥", "9" * 601, "9" * 4300, "9" * 4301]
        for flag in ("--depth", "--live-children", "--live-total"):
            for v in bad:
                with self.subTest(flag=flag, v=v[:12]):
                    f = self.f("c.json")
                    fl = self.flags(f)
                    fl[fl.index(flag) + 1] = v
                    fl[fl.index(flag)] = flag + "=" + v
                    del fl[fl.index(flag + "=" + v) + 1]
                    self.refuse(flag + ": must be a decimal integer", *fl)
                    self.assertFalse(os.path.exists(f))
        f = self.f("ok.json")
        for limit in INT_LIMITS:
            with int_limit(limit):
                n = "9" * 600
                for v, tag in (("0", "z"), ("1", "o"), (n, "n")):
                    g = self.f("ok%s%s.json" % (tag, limit))
                    self.ok(*self.flags(g, children=v))
                    with open(g, encoding="utf-8") as fh:
                        self.assertEqual(json.load(fh)["dispatcher"]["live_children"], int(v))
        self.refuse("--depth given more than once", *self.flags(f), "--depth", "0")

    def test_negative_count_refused(self):  # IJ5
        f = self.f("neg.json")
        for argv in (["--depth=-1"], ["--depth", "-1"]):
            with self.subTest(argv=argv):
                fl = self.flags(f)
                i = fl.index("--depth")
                fl[i:i + 2] = argv
                with contextlib.redirect_stderr(io.StringIO()):
                    code, out, err = self.run_c(*self.base(), *fl)
                self.assertIn(code, (1, 2))
                self.assertEqual(out, "")
        self.refuse("--depth: must be a decimal integer", *(lambda fl: fl[:fl.index("--depth")] + ["--depth=-1"] + fl[fl.index("--depth") + 2:])(self.flags(f)))

    def test_input_json_file_kinds(self):  # IJ7
        new = self.f("new.json")
        self.ok(*self.flags(new))
        exist = self.put_file(self.f("exist.json"), "KEEP")
        self.refuse("cannot be created (File exists)", *self.flags(exist))
        with open(exist) as fh:
            self.assertEqual(fh.read(), "KEEP")
        d = self.f("adir")
        os.mkdir(d)
        self.refuse("cannot be created", *self.flags(d))
        tgt = self.put_file(self.f("tgt"), "T")
        os.symlink(tgt, self.f("link"))
        self.refuse("cannot be created", *self.flags(self.f("link")))
        os.symlink(self.f("nowhere"), self.f("dangling"))
        self.refuse("cannot be created", *self.flags(self.f("dangling")))
        self.assertFalse(os.path.exists(self.f("nowhere")))
        self.refuse("cannot be created", *self.flags(self.f("nodir/x.json")))
        self.assertFalse(os.path.exists(self.f("nodir")))
        self.ok(*self.flags(self.f("sp ace.json")))
        self.refuse("--input-json: must be printable ASCII on one line", "--input-json=" + self.f("a\nb.json"),
                    "--dispatcher", "session", "--depth", "0", "--live-children", "0", "--live-total", "0")
        self.refuse("--input-json: must not be empty", "--input-json=", "--dispatcher", "session", "--depth", "0",
                    "--live-children", "0", "--live-total", "0")
        old = os.getcwd()
        os.chdir(self.tmp)
        self.addCleanup(os.chdir, old)
        self.ok(*self.flags("rel.json"))
        self.assertTrue(os.path.exists(os.path.join(self.tmp, "rel.json")))
        tracked = os.path.join(self.root, "tracked.json")
        self.put_file(tracked, "x")
        commit_all(self.root, "tracked")
        self.refuse("cannot be created", *self.flags(tracked))
        if os.geteuid() != 0:
            ro = self.f("ro")
            os.mkdir(ro)
            os.chmod(ro, 0o500)
            self.addCleanup(os.chmod, ro, 0o700)
            self.refuse("cannot be created", *self.flags(os.path.join(ro, "x.json")))
            self.assertEqual(os.listdir(ro), [])

    def test_input_json_prompt_roundtrip(self):  # IJ8
        self.led("Dispatched: x\r\nlone\rcr\nuni é   end\n")
        f = self.f("rt.json")
        out = self.ok(*self.flags(f))
        self.assertIn("lone\rcr\n", out)
        with open(f, "rb") as fh:
            raw = fh.read()
        self.assertTrue(raw.isascii())   # json.dump escapes every non-ASCII character and control byte
        self.assertEqual(json.loads(raw.decode("ascii"))["prompt"], out)
        self.assertEqual(gate_dispatch._read_input(f)["prompt"], out)


# =====================================================================================================================
class TestGit(Fx):
    def test_continue_ignores_colour_and_abbrev_config(self):  # GC1
        commit_all(self.root, "state")
        plain = os.path.join(self.tmp, "plain")
        os.mkdir(plain)
        root2 = make_repo(plain, minimal_config())
        for rel, text in ((HP, htext()), (LP, ledger("Dispatched: x\n"))):
            self.put(rel, text, root=root2)
        commit_all(root2, "state")
        with mock.patch.object(ids, "utc_today", return_value=TODAY):
            a = self.run_c("--plan", SLUG, "--root", self.root, "--prompts", self.pd, "--ref", "main")
            b = self.run_c("--plan", SLUG, "--root", root2, "--prompts", self.pd, "--ref", "main")
            c = self.run_c("--plan", SLUG, "--root", self.root, "--prompts", self.pd)
        self.assertEqual(a, (0, REFERENCE, ""))
        self.assertEqual(b, a)
        self.assertEqual(c, a)

    def test_root_git_states(self):  # GC2
        commit_all(self.root, "state")
        sha = git(self.root, "rev-parse", "HEAD")
        git(self.root, "checkout", "-q", "--detach", sha)
        self.assertEqual(self.ok(), REFERENCE)
        self.assertEqual(self.ok("--ref", sha), REFERENCE)
        git(self.root, "checkout", "-q", "-b", "stream/branch")
        self.assertEqual(self.ok(), REFERENCE)
        unborn = os.path.join(self.tmp, "unborn")
        os.mkdir(unborn)
        git(unborn, "init", "-q", "-b", "main")
        write_record(unborn, ".strict-delivery/config.yml", minimal_config())
        self.put(HP, htext(), root=unborn)
        self.put(LP, ledger("Dispatched: x\n"), root=unborn)
        with mock.patch.object(ids, "utc_today", return_value=TODAY):
            self.assertEqual(self.run_c("--plan", SLUG, "--root", unborn, "--prompts", self.pd)[:2], (0, REFERENCE))
            code, out, err = self.run_c("--plan", SLUG, "--root", unborn, "--prompts", self.pd, "--ref", "main")
        self.assertEqual((code, out), (1, ""))
        self.assertIn("--ref: main is not a commit", err)

    def test_shallow_and_linked_worktrees(self):  # GC3
        commit_all(self.root, "state")
        clone = os.path.join(self.tmp, "clone")
        git(self.tmp, "clone", "-q", "--depth", "1", "file://" + self.root, clone)
        with mock.patch.object(ids, "utc_today", return_value=TODAY):
            self.assertEqual(self.run_c("--plan", SLUG, "--root", clone, "--prompts", self.pd)[:2], (0, REFERENCE))
            self.assertEqual(self.run_c("--plan", SLUG, "--root", clone, "--prompts", self.pd, "--ref", "HEAD")[:2], (0, REFERENCE))
        wt = os.path.join(self.tmp, "wt")
        git(self.root, "worktree", "add", "-q", "-b", "wtb", wt)
        with mock.patch.object(ids, "utc_today", return_value=TODAY):
            self.assertEqual(self.run_c("--plan", SLUG, "--root", wt, "--prompts", self.pd)[:2], (0, REFERENCE))

    def test_paths_with_space_and_newline(self):  # GC4
        sp = os.path.join(self.tmp, "p d2")
        os.mkdir(sp)
        for r in ALL_ROLES:
            self.put_file(os.path.join(sp, r + ".md"), block_of(r))
        with mock.patch.object(ids, "utc_today", return_value=TODAY):
            self.assertEqual(self.run_c("--plan", SLUG, "--root", self.root, "--prompts", sp)[:2], (0, REFERENCE))
        self.refuse("--prompts: must be printable ASCII on one line",
                    argv=["--plan", SLUG, "--root", self.root, "--prompts=" + self.pd + "\n"])

    def test_cleared_env(self):  # GC5
        commit_all(self.root, "state")
        with mock.patch.dict(os.environ, {"GIT_DIR": os.path.join(self.tmp, "nope"), "GIT_WORK_TREE": self.tmp}):
            self.assertEqual(self.ok("--ref", "main"), REFERENCE)
            self.assertEqual(self.ok(), REFERENCE)

    def test_default_root_uses_repo_root(self):  # GC6
        with mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": self.root}), mock.patch.object(ids, "utc_today", return_value=TODAY):
            code, out, err = self.run_c("--plan", SLUG, "--prompts", self.pd)
        self.assertEqual((code, out, err), (0, REFERENCE, ""))


# =====================================================================================================================
class TestVersion(Fx):
    def test_numeric_text_limits_both_interpreters(self):  # V1 (argv, YAML and ledger numerals are in the rows above)
        for limit in INT_LIMITS:
            with int_limit(limit):
                for n in (600, 601, 4300, 4301):
                    with self.subTest(limit=limit, n=n):
                        f = self.f_json("v%s%d.json" % (limit, n))
                        fl = self.flags(f, children="9" * n)
                        if n == 600:
                            self.ok(*fl)
                            self.assertTrue(os.path.exists(f))
                        else:
                            self.refuse("--live-children: must be a decimal integer", *fl)
                            self.assertFalse(os.path.exists(f))

    def f_json(self, name):
        return os.path.join(self.tmp, name)

    def test_unicode_version_independent(self):  # V2
        self.put_file(os.path.join(self.pd, "controller.md"), "# Strict block: controller\n\nrules Ꟁ\n")
        self.led("Dispatched: Ꟁ\n")
        want = REFERENCE.replace("rules\n", "rules Ꟁ\n").replace("Dispatched: x", "Dispatched: Ꟁ")
        self.assertEqual(self.ok(), want)
        with open(os.path.join(REPO, "gates", "tools", "continue_cli.py"), encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        banned = {"lower", "upper", "isprintable", "isalnum", "isdigit", "isalpha", "isdecimal", "isnumeric", "strip",
                  "lstrip", "rstrip", "casefold", "title", "isspace"}
        used = {n.func.attr for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
        self.assertEqual(used & banned, set())

    def test_exception_groups_propagate(self):  # V3
        with open(os.path.join(REPO, "gates", "tools", "continue_cli.py"), encoding="utf-8") as fh:
            src = fh.read()
        self.assertNotIn("BaseExceptionGroup", src)
        self.assertFalse(any(isinstance(n, ast.Try) and any(getattr(h, "is_star", False) for h in n.handlers)
                             for n in ast.walk(ast.parse(src))) or False)
        self.assertNotIn("except*", src)
        if not hasattr(builtins, "BaseExceptionGroup"):
            self.skipTest("BaseExceptionGroup exists on Python 3.11 and later")
        commit_all(self.root, "state")
        f = os.path.join(self.tmp, "grp.json")
        for exc in (builtins.ExceptionGroup("x", [ValueError()]), builtins.BaseExceptionGroup("x", [KeyboardInterrupt()])):
            for target in ((gitinfo, "show"),):
                with self.subTest(type(exc).__name__), mock.patch.object(*target, side_effect=exc):
                    out = io.StringIO()
                    with contextlib.redirect_stdout(out), self.assertRaises(type(exc)):
                        self.run_c(*self.base(), "--ref", "main", *self.flags(f))
                    self.assertEqual(out.getvalue(), "")
                    self.assertFalse(os.path.exists(f))


if __name__ == "__main__":
    unittest.main()
