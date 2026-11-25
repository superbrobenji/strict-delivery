"""Tests of gates/tools/questions_cli.py (Task P4.1, the upward-question path) through ``gates.__main__.main`` in process
and ``python3 -m gates questions`` in a subprocess, on fixture repositories made with ``helpers.make_repo``. Expected lines,
tags and record fields are written by hand from the plan (:3087-3092) and the input-domain table of Task P4.1 (rows are
named in the comments); records are read back with ``Store.load``. Binding decisions D-Q1..D-Q9 of stream a14 apply."""
import ast
import builtins
import contextlib
import io
import os
import re
import subprocess
import sys
import unittest
from unittest import mock

from gates import __main__ as gates_main
from gates import producers
from gates.lib import config, decisions, gitinfo, yamlsub
from gates.lib.result import GateError
from gates.lib import store, tipread
from gates.lib.store import Store
from gates.tools import decisions_cli, questions_cli
from tests.helpers import (INT_LIMITS, GitIsolatedTestCase, check_root_forms, commit_all, git, int_limit, make_repo,
                           minimal_config, root_forms, write_record)
from tests.tipkinds import BAD_KINDS, refusal, set_entry

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P = "20261101-x"
INTEG = P + "/integration"
PLANS = "docs/strict-delivery/plans"
PS = ".strict-delivery/state/plans"
DEC = ".strict-delivery/state/decisions"
HA = PS + "/a-plan/handoff.md"
HB = PS + "/b-plan/handoff.md"
D1, D2, D3, D4, D5, D6 = ("DEC-20261031-%s" % s for s in ("a1a1", "b2b2", "c3c3", "d4d4", "e5e5", "f6f6"))
SRC_RE = re.compile(r"asked a-plan:q[0-9]+ -> DEC-[0-9]{8}-[0-9a-z]{4}\n")


def Q(qid="q1", cls="scope", question="Which?", effect="lasting", options=(("a", "ca"), ("b", "cb")), recommended="a",
      source=None, **over):
    q = {"qid": qid, "class": cls, "question": question, "effect": effect,
         "options": [{"label": l, "cost": c} for l, c in options]}
    if recommended is not None:
        q["recommended"] = recommended
    if source is not None:
        q["source"] = source
    q.update(over)
    return {k: v for k, v in q.items() if v is not None}


def dec(id_, status="open", topics=(), **over):
    r = {"schema": "decision/%d" % decisions._schema().version, "id": id_, "status": status, "class": "scope",
         "question": "Earlier thing?", "options": [{"label": "a", "cost": "ca"}, {"label": "b", "cost": "cb"}],
         "asked_at": "a1b2c3d", "asked_by": "agent", "topics": list(topics), "applies_to": [], "checked_against": [],
         "effect": "one-off", "recommended": "a"}
    if status == "answered":
        r.update(answer="SECRET-ANSWER", answered_at={"at": "a1b2c3d", "by": "who@example.invalid"})
    if status == "withdrawn":
        r["withdrawn"] = {"at": "a1b2c3d", "by": "who@example.invalid", "reason": "asked twice"}
    r.update(over)
    return r


def resume(plan, nxt, branch, head, qids):
    return "Resume strict-delivery plan %s at %s; branch %s; head %s; open questions: %s." % (
        plan, nxt, branch, head, ", ".join(qids) if qids else "none")


class Fx(GitIsolatedTestCase):
    """``main`` with the program ``P`` (streams a, b) committed on ``P/integration``, HEAD on it; the git config sets
    ``color.ui=always``, ``color.diff=always``, ``core.abbrev=7`` (GC1)."""

    def setUp(self):
        super().setUp()
        self.root = make_repo(self.work, self.config())
        for k, v in (("color.ui", "always"), ("color.diff", "always"), ("core.abbrev", "7"), ("diff.noprefix", "true")):
            git(self.root, "config", k, v)
        self.sha = git(self.root, "rev-parse", "HEAD")
        git(self.root, "checkout", "-q", "-b", INTEG)
        self.streams()
        for s in ("a", "b"):
            git(self.root, "branch", "%s/%s/main" % (P, s), "main")
        self.cfg = config.load(self.root)
        self.hand("a", [])
        self.hand("b", [])

    def config(self):
        return minimal_config()

    def put(self, rel, data, root=None):
        path = os.path.join(root or self.root, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(data if isinstance(data, bytes) else data.encode("utf-8"))
        return path

    def streams(self, rows=None, program=P, commit=True):
        def st(sid, order):
            return {"id": sid, "purpose": "p", "plan": "%s/%s-plan.md" % (PLANS, sid), "estimate": 5, "depends_on": [],
                    "merge_order": order, "owns": [sid + "-owned.py"]}
        row = {"schema": "streams/1", "program": program, "plan": PLANS + "/program-plan.md", "specs": [],
               "worktrees": "../w", "streams": rows if rows is not None else [st("a", 1), st("b", 2)], "shared": []}
        base = ".strict-delivery/state/programs/" + program
        self.put(base + "/streams.yml", yamlsub.emit(row))
        self.put(base + "/status.md", "<!-- schema: status/1 -->\n\nthe status page\n")
        self.put(base + "/sync-log.md", "<!-- schema: sync-log/1 -->\n")
        self.put(base + "/merged.md", "<!-- schema: merged-log/1 -->\n")
        if commit:
            commit_all(self.root, "program")

    def handoff_text(self, sid, questions, slug=None, **over):
        plan = slug or "%s-plan" % sid
        h7 = self.sha[:7]
        qids = [q["qid"] for q in questions if isinstance(q, dict) and isinstance(q.get("qid"), str)]
        branch = "%s/%s/main" % (P, sid)
        row = {"schema": "handoff/1", "plan": "%s/%s.md" % (PLANS, plan), "spec": ["docs/strict-delivery/specs/s.md"],
               "branch": branch, "head": h7, "base": h7, "ledger": "%s/%s/ledger.md" % (PS, plan),
               "resume": resume("%s/%s.md" % (PLANS, plan), "P4.1", branch, h7, qids), "block": "P4",
               "next_task": "P4.1", "findings_in_flight": [], "open_decisions": [], "rulings": 0, "grant": None,
               "live_subagents": [], "role": "controller", "budget": {"tokens": 300000, "minutes": 150},
               "worktrees": [{"path": ".", "branch": branch, "head": h7, "porcelain": ""}],
               "skills": ["strict-delivery"], "ledger_from": 4, "batch_cut": None, "questions": questions,
               "program": P, "stream": sid}
        row.update(over)
        return "---\n" + yamlsub.emit(row) + "---\nbody\n"

    def hand(self, sid, questions, dirslug=None, text=None, remove=False, **over):
        """Commit the handoff of ``sid`` (in the directory ``dirslug``, default its plan) on its branch."""
        git(self.root, "checkout", "-q", "%s/%s/main" % (P, sid))
        try:
            rel = "%s/%s/handoff.md" % (PS, dirslug or "%s-plan" % sid)
            if remove:
                git(self.root, "rm", "-q", "-f", rel)
            else:
                self.put(rel, text if text is not None else self.handoff_text(sid, questions, **over))
            commit_all(self.root, "handoff " + sid)
        finally:
            git(self.root, "checkout", "-q", INTEG)

    def run_q(self, *args, mod=None):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = gates_main.main(["questions"] + list(args))
        return code, out.getvalue(), err.getvalue()

    def lst(self, *extra):
        return self.run_q("list", "--program", P, "--root", self.root, *extra)

    def ask(self, *extra, by="boss"):
        return self.run_q("ask", "--program", P, "--by", by, "--root", self.root, *extra)

    def recs(self):
        return {r.id: r.row for r in Store(self.root, "decision", self.cfg).load()}

    def put_dec(self, *rows):
        for r in rows:
            write_record(self.root, "%s/%s.yml" % (DEC, r["id"]), r)

    def snap(self):
        out = {}
        for d, dirs, files in os.walk(self.root):
            dirs[:] = [x for x in dirs if x != ".git"]
            for f in files:
                p = os.path.join(d, f)
                with open(p, "rb") as fh:
                    out[os.path.relpath(p, self.root)] = fh.read()
        return out, git(self.root, "status", "--porcelain", "--untracked-files=all")

    def fails(self, code_out_err, needle, sub="list", out=""):
        code, o, e = code_out_err
        self.assertEqual((code, o), (1, out), e)
        self.assertTrue(all(l.startswith("questions %s: " % sub) for l in e.splitlines()), e)
        self.assertIn(needle, e)
        return e


# ---------------------------------------------------------------- Producer 1: main(argv)

class MainForms(Fx):
    def test_main_argv_types(self):  # QM1
        buf = io.StringIO()
        for bad in (("list",), ["list", None], ["list", 5], ["list", b"x"], 5, "list"):
            with self.subTest(argv=bad), contextlib.redirect_stderr(buf):
                self.assertEqual(questions_cli.main(bad), 2)
        self.assertEqual(buf.getvalue(), "questions: argv must be a list of str\n" * 6)

        class S(str):
            pass
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(questions_cli.main([S("list")]), 2)  # a str subclass is not a str
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(questions_cli.main([]), 2)
        self.assertTrue(err.getvalue().startswith("usage: python3 -m gates questions"), err.getvalue())
        out = io.StringIO()
        with mock.patch.object(sys, "argv", ["x", "list", "--program", P, "--root", self.root]), \
                contextlib.redirect_stdout(out):
            self.assertEqual(questions_cli.main(None), 0)
        self.assertEqual(out.getvalue(), "")

    def test_subcommand_forms(self):  # QM2
        for argv in ([], ["batch"], ["LIST"], ["list "], ["--help"], ["-h"], ["list", "--help"], ["ask", "-h"]):
            with self.subTest(argv=argv):
                code, out, err = self.run_q(*argv)
                self.assertEqual((code, out), (2, ""))
                self.assertIn("usage:", err)
        self.assertEqual(self.lst()[0], 0)
        self.assertEqual(self.run_q("ask", "--program", P, "--by", "b", "--root", self.root)[0], 0)

    def test_source_flag_combinations(self):  # QM3
        r = ["--root", self.root]
        cases = [(["--root", self.root], "one of --program or --plan is required"),
                 (["--program", P, "--plan", "a-plan", "--ref", "main"] + r, "--program and --plan are exclusive"),
                 (["--plan", "a-plan"] + r, "--ref is required with --plan"),
                 (["--ref", "main"] + r, "--ref is only valid with --plan"),
                 (["--program", P, "--ref", "main"] + r, "--ref is only valid with --plan"),
                 (["--program", P, "--program", P] + r, "--program given more than once"),
                 (["--plan", "a-plan", "--plan", "a-plan", "--ref", "main"] + r, "--plan given more than once"),
                 (["--plan", "a-plan", "--ref", "main", "--ref", "main"] + r, "--ref given more than once")]
        for args, needle in cases:
            with self.subTest(args=args), mock.patch.object(tipread, "show_file") as show, \
                    mock.patch.object(gitinfo, "local_branches") as lb:
                self.fails(self.run_q("list", *args), needle)
                self.assertFalse(show.called or lb.called)
        self.fails(self.run_q("ask", "--program", P, "--by", "b", "--by", "c", *r), "--by given more than once", "ask")

    def test_ask_by_domain(self):  # QM4, AM9
        self.fails(self.ask(by="\u00e9"), "--by: U+00E9 is not allowed", "ask")  # refused with nothing pending too
        self.hand("a", [Q()])
        self.fails(self.run_q("ask", "--program", P, "--root", self.root), "--by is required", "ask")
        self.assertEqual(self.run_q("list", "--program", P, "--by", "x", "--root", self.root)[0], 2)
        for by, needle in (("", "--by: must not be empty"), (" a", "--by: must not start or end"),
                           ("a ", "--by: must not start or end"), ("é", "--by: U+00E9 is not allowed"),
                           ("a\nb", "--by: U+000A is not allowed"), ("Ꟁ", "--by: U+A7C0 is not allowed")):
            with self.subTest(by=by):
                before = self.snap()
                self.fails(self.ask(by=by), needle, "ask")
                self.assertEqual(self.snap(), before)
        for by in ("a b", "-w"):
            with self.subTest(by=by):
                code, out, err = self.run_q("ask", "--program", P, "--by=" + by, "--root", self.root)
                self.assertEqual((code, err), (0, ""))
                (rid,) = [r for r in self.recs() if r in out]
                self.assertEqual(self.recs()[rid]["asked_by"], by)
                self.put_dec(dict(self.recs()[rid], status="withdrawn", withdrawn={"at": "a1b2c3d", "by": "w@e.invalid", "reason": "r"}))

    def test_root_forms(self):  # QM5
        git(self.root, "checkout", "-q", "main")
        forms = root_forms(self.tmp, self.root)
        git(self.root, "checkout", "-q", INTEG)
        for name, path, verdict in forms:
            with self.subTest(form=name):
                code, out, err = self.run_q("list", "--program", P, "--root", path)
                if verdict == "ok":
                    self.assertNotIn("repository top level", err)
                    self.assertNotIn("exit 128", err)
                else:
                    self.assertEqual((code, out), (1, ""))
                    self.assertIn(verdict, err)
        self.fails(self.run_q("list", "--program", P, "--root", ""), "--root: must not be empty")
        self.fails(self.run_q("list", "--program", P, "--root", self.root, "--root", self.root), "--root given more than once")
        self.assertEqual(self.run_q("list", "--program", P, "--root", self.root + "/")[0], 0)

    def test_exit_codes(self):  # QM6
        self.assertEqual(self.lst(), (0, "", ""))
        self.assertEqual(self.ask(), (0, "", ""))
        self.assertEqual(self.run_q("list", "--bogus")[0], 2)
        self.assertEqual(self.run_q("list", "--root", self.root)[0], 1)
        self.hand("a", [Q()])
        self.assertEqual(self.lst()[0], 0)

    def test_refusal_lines_are_safe_text(self):  # QM7
        self.hand("a", [], remove=True)
        git(self.root, "branch", "-D", "%s/b/main" % P)
        code, out, err = self.lst()
        self.assertEqual((code, out), (1, ""))
        self.assertEqual(len(err.splitlines()), 2, err)
        self.assertTrue(all(l.startswith("questions list: ") for l in err.splitlines()))
        code, out, err = self.run_q("list", "--plan", "a-plan", "--ref", "bad\x1b[31mref", "--root", self.root)
        self.assertEqual((code, out), (1, ""))
        self.assertEqual(err, "questions list: --ref: bad\\x1b[31mref is not a commit\n")

    def test_never_commits(self):  # QM8
        self.hand("a", [Q()])
        head = git(self.root, "rev-parse", "HEAD")
        idx = os.path.join(self.tmp, "stray-index")
        with mock.patch.dict(os.environ, {"GIT_INDEX_FILE": idx}):
            self.assertEqual(self.ask()[0], 0)
        self.assertEqual(git(self.root, "rev-parse", "HEAD"), head)
        self.assertFalse(os.path.exists(idx))
        self.assertEqual(git(self.root, "status", "--porcelain", "--untracked-files=all", "--", ".strict-delivery/state/decisions")[:2], "??")

    def test_abbreviated_flags_pinned(self):  # QM10
        self.hand("a", [Q()])
        full = self.lst()
        for args in (["--prog", P, "--roo", self.root], ["--program", P, "--r", self.root]):
            with self.subTest(args=args):
                code, out, err = self.run_q("list", *args)
                self.assertEqual((code, out), (0, full[1]), err) if code == 0 else self.assertEqual((code, out), (2, ""))

    def test_subprocess_matches_in_process(self):  # PC2
        self.hand("a", [Q(), Q("q2")])
        self.put_dec(dec(D2, topics=["q:a-plan:q2"]))
        want = self.lst()
        p = subprocess.run([sys.executable, "-m", "gates", "questions", "list", "--program", P, "--root", self.root],
                           cwd=REPO, env=dict(os.environ, PYTHONPATH=REPO), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual((p.returncode, p.stdout, p.stderr), (want[0], want[1].encode(), want[2].encode()))
        self.assertEqual(want[1], "pending a-plan:q1 a: Which?\nasked a-plan:q2 -> %s\n" % D2)
        p = subprocess.run([sys.executable, "-m", "gates", "questions", "ask", "--program", P, "--by", "boss", "--root",
                            self.root], cwd=REPO, env=dict(os.environ, PYTHONPATH=REPO), stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE)
        self.assertEqual((p.returncode, p.stderr), (0, b""))
        self.assertRegex(p.stdout.decode(), r"\Aasked a-plan:q1 -> DEC-[0-9]{8}-[0-9a-z]{4}\n\Z")


# ---------------------------------------------------------------- Producer 2: registration

class Registration(unittest.TestCase):
    def test_questions_registered(self):  # QR1
        self.assertIn("questions", gates_main.COMMANDS)
        with mock.patch.object(questions_cli, "main", return_value=7) as m:
            self.assertEqual(gates_main.COMMANDS["questions"](["list"]), 7)
        m.assert_called_once_with(["list"])
        with open(os.path.join(REPO, "gates", "__main__.py"), encoding="utf-8") as fh:
            self.assertNotIn("\nfrom gates.tools import questions_cli", fh.read())  # imported inside the function

    def test_usage_lists_questions(self):  # QR2
        want = ("usage: python3 -m gates <command> [args]\ncommands: check, claims, continue, decisions, findings, githook, "
                "githooks, hook, index, loopstats, program, questions, run_all\n")
        p = subprocess.run([sys.executable, "-m", "gates", "bogus"], cwd=REPO, env=dict(os.environ, PYTHONPATH=REPO),
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual((p.returncode, p.stdout, p.stderr.decode()), (2, b"", want))

    def test_questions_has_no_produces_entry(self):  # QR3
        self.assertFalse(hasattr(questions_cli, "PRODUCES"))
        self.assertNotIn("gates.tools.questions_cli", producers.PRODUCER_MODULES)


# ---------------------------------------------------------------- Producer 3: --program sources

class ProgramSources(Fx):
    def test_list_marks_pending_asked_answered(self):  # SP1, LS1, TG3-TG5
        self.hand("a", [Q("q1"), Q("q2", question="Second?"), Q("q3", question="Third?")])
        self.hand("b", [])
        self.put_dec(dec(D2, "open", ["q:a-plan:q2"]), dec(D3, "answered", ["q:a-plan:q3"]))
        self.assertEqual(self.lst(), (0, "pending a-plan:q1 a: Which?\nasked a-plan:q2 -> %s\nanswered a-plan:q3 -> %s\n" % (D2, D3), ""))

    def test_two_streams_same_qid(self):  # SP2
        self.hand("a", [Q("q1")])
        self.hand("b", [Q("q1", question="Other?")])
        self.assertEqual(self.lst(), (0, "pending a-plan:q1 a: Which?\npending b-plan:q1 b: Other?\n", ""))
        self.put_dec(dec(D2, "open", ["q:b-plan:q1"]))
        self.assertEqual(self.lst()[1], "pending a-plan:q1 a: Which?\nasked b-plan:q1 -> %s\n" % D2)

    def test_missing_stream_branch_is_error(self):  # SP3, AS15
        self.hand("a", [Q()])
        git(self.root, "branch", "-D", "%s/b/main" % P)
        e = self.fails(self.lst(), "stream b: branch %s/b/main does not exist" % P)
        self.assertEqual(e.count("\n"), 1)
        before = self.snap()
        self.fails(self.ask(), "stream b: branch %s/b/main does not exist" % P, "ask")
        self.assertEqual(self.snap(), before)

    def test_missing_handoff_is_error(self):  # SP4
        self.hand("a", [Q()])
        want = "stream b: %s: missing at %s/b/main" % (HB, P)
        self.hand("b", [], remove=True)
        self.fails(self.lst(), want)  # no file on b
        git(self.root, "checkout", "-q", "%s/b/main" % P)
        self.put(HB + "/x", "x\n")           # a directory
        commit_all(self.root, "dir")
        # 5b.3 F6 (owner Q-RC9-1 (a)): a non-regular handoff entry is refused by name, no longer read as "missing at"
        refused = "stream b: %s: refs/heads/%s/b/main:%s: cannot be read as a UTF-8 regular file (not a regular file)" % (HB, P, HB)
        self.fails(self.lst(), refused)
        git(self.root, "rm", "-q", "-r", "-f", HB)
        os.makedirs(os.path.dirname(os.path.join(self.root, *HB.split("/"))), exist_ok=True)
        os.symlink("elsewhere", os.path.join(self.root, *HB.split("/")))  # a symlink
        commit_all(self.root, "link")
        git(self.root, "checkout", "-q", INTEG)
        self.fails(self.lst(), refused)

    def test_uncommitted_question_not_read(self):  # SP5 (Q-Pplan-8 (a))
        self.hand("a", [Q("q1")])
        wt = os.path.join(self.tmp, "wt-a")
        git(self.root, "worktree", "add", "-q", wt, "%s/a/main" % P)
        self.put(HA, self.handoff_text("a", [Q("q1"), Q("q9")]), root=wt)
        code, out, err = self.lst()
        self.assertEqual((code, out, err), (0, "pending a-plan:q1 a: Which?\n", ""))
        self.assertNotIn("q9", out)

    def test_invalid_handoff_is_error(self):  # SP6
        good = self.handoff_text("a", [Q()])
        bad = {"no front matter": "hello\n", "no closing": "---\nschema: handoff/1\n", "yaml error": "---\na: [\n---\n",
               "bom": "﻿" + good, "crlf": good.replace("\n", "\r\n"), "not a mapping": "---\n- a\n---\n",
               "bad effect": self.handoff_text("a", [Q(effect="forever")]),
               "one option": self.handoff_text("a", [Q(options=(("a", "ca"),))]),
               "class typo": self.handoff_text("a", [Q(cls="triaj")]),
               "recommended missing": self.handoff_text("a", [Q(recommended=None)]),
               "duplicate qid": self.handoff_text("a", [Q(), Q()]),
               "model-policy with recommended": self.handoff_text("a", [Q(cls="model-policy")]),
               "not utf-8": b"---\nschema: \xff\n---\n"}
        self.hand("b", [Q("q7")])
        for name, text in bad.items():
            with self.subTest(name):
                self.hand("a", [], text=text)
                e = self.fails(self.lst(), "stream a: " + HA)
                self.assertNotIn("q7", e)
                self.assertEqual(self.ask(), (1, "", e.replace("questions list", "questions ask")))
        self.assertEqual(self.recs(), {})

    def test_handoff_plan_slug_matches_directory(self):  # SP7
        self.hand("a", [Q()], slug="b-plan")
        self.fails(self.lst(), "stream a: %s: plan: names b-plan, not a-plan" % HA)

    def test_handoff_program_and_stream_fields(self):  # D-Q3
        self.hand("a", [Q()], program="20261101-y")
        self.fails(self.lst(), "stream a: %s: program: names 20261101-y, not %s" % (HA, P))
        self.hand("a", [Q()], stream="b")
        self.fails(self.lst(), "stream a: %s: stream: names b, not a" % HA)
        text = self.handoff_text("a", [Q()])
        text = "\n".join(l for l in text.split("\n") if not l.startswith(("program:", "stream:")))
        self.hand("a", [Q()], text=text)  # absent: accepted
        self.assertEqual(self.lst()[0], 0)

    def test_program_name_domain(self):  # SP8
        for name in ("x", "20261301-x", "20261101-X", "20261101-a/b", "", "a" * 4301, "a\nb", "é", "20261101-x ",
                     "20261101-x퟿"):
            with self.subTest(name=name), mock.patch.object(gitinfo, "local_branches") as lb:
                self.fails(self.run_q("list", "--program", name, "--root", self.root), "--program: ")
                self.assertFalse(lb.called)
        self.fails(self.run_q("list", "--program", "20261102-y", "--root", self.root),
                   "--program: 20261102-y is not a live program")
        git(self.root, "branch", "20261103-z/integration", "main")
        self.fails(self.run_q("list", "--program", "20261103-z", "--root", self.root),
                   "--program: 20261103-z is not a live program")

    def test_streams_rows_domain(self):  # SP9, SP10
        def st(sid, plan, order=1):
            return {"id": sid, "purpose": "p", "plan": plan, "estimate": 5, "depends_on": [], "merge_order": order,
                    "owns": [sid + ".py"]}
        ok = "%s/a-plan.md" % PLANS
        cases = [([{"id": "a", "purpose": "p", "estimate": 5, "owns": ["a"], "merge_order": 1}], "stream a: plan: "),
                 ([st("a", "docs/other/a-plan.md")], "stream a: plan: must be %s/<name>.md" % PLANS),
                 ([st("a", PLANS + "/sub/a.md")], "stream a: plan: must be"),
                 ([st("a", PLANS + "/a-plan.txt")], "stream a: plan: must be"),
                 ([st("records", ok)], "stream records: id: "),
                 ([st("integration", ok)], "stream integration: id: "),
                 ([st("A", ok)], "stream A: id: "),
                 ([st("a", ok), st("b", ok, 2)], "stream b: plan: the same plan as stream a")]
        for slug in ("A-plan", "a plan", "a.plan", "a_plan", "a:plan", "a#plan"):
            cases.append(([st("a", "%s/%s.md" % (PLANS, slug))], "stream a: plan slug %s must match" % slug))
        for rows, needle in cases:
            with self.subTest(needle=needle):
                self.streams(rows)
                e = self.fails(self.lst(), needle)
                self.assertNotIn("Traceback", e)

    def test_slug_charset(self):  # SP10 (a plan slug that is not [a-z0-9][a-z0-9-]*)
        self.streams([{"id": "a", "purpose": "p", "plan": PLANS + "/Ꟁ-plan.md", "estimate": 5, "depends_on": [],
                       "merge_order": 1, "owns": ["a.py"]}])
        self.fails(self.lst(), "stream a: plan slug ")

    def test_plan_state_from_config(self):  # SP11, GC4
        for ps in ("state/p", "state/p q"):
            with self.subTest(plan_state=ps):
                cfg = dict(minimal_config(), paths={"plan_state": ps})
                git(self.root, "checkout", "-q", "main")
                write_record(self.root, ".strict-delivery/config.yml", cfg)
                git(self.root, "commit", "-q", "-a", "-m", "cfg " + ps)
                git(self.root, "checkout", "-q", INTEG)
                git(self.root, "merge", "-q", "--no-edit", "main")
                git(self.root, "checkout", "-q", "%s/a/main" % P)
                git(self.root, "merge", "-q", "--no-edit", "main")
                self.put("%s/a-plan/handoff.md" % ps, self.handoff_text("a", [Q()]).replace(PS, ps))
                commit_all(self.root, "handoff")
                git(self.root, "checkout", "-q", "%s/b/main" % P)
                git(self.root, "merge", "-q", "--no-edit", "main")
                self.put("%s/b-plan/handoff.md" % ps, self.handoff_text("b", []).replace(PS, ps))
                commit_all(self.root, "handoff")
                git(self.root, "checkout", "-q", INTEG)
                self.assertEqual(self.lst(), (0, "pending a-plan:q1 a: Which?\n", ""))

    def test_reads_current_tip_each_run(self):  # SP12
        self.hand("a", [Q("q1")])
        self.assertEqual(self.lst()[1], "pending a-plan:q1 a: Which?\n")
        self.hand("a", [Q("q1", question="Changed?")])
        self.assertEqual(self.lst()[1], "pending a-plan:q1 a: Changed?\n")
        self.hand("a", [], remove=True)
        self.fails(self.lst(), "stream a: %s: missing at %s/a/main" % (HA, P))

    def test_root_git_states(self):  # SP13, GC2
        self.hand("a", [Q()])
        git(self.root, "checkout", "-q", "--detach")
        self.assertEqual(self.lst()[1], "pending a-plan:q1 a: Which?\n")
        fresh = os.path.join(self.tmp, "fresh")
        os.mkdir(fresh)
        git(fresh, "init", "-q", "-b", "main")
        git(fresh, "config", "user.email", "f@example.invalid")
        write_record(fresh, ".strict-delivery/config.yml", minimal_config())
        code, out, err = self.run_q("list", "--program", P, "--root", fresh)
        self.assertEqual((code, out), (1, ""))
        code, out, err = self.run_q("list", "--plan", "a-plan", "--ref", "HEAD", "--root", fresh)  # GC3
        self.assertEqual((code, out), (1, ""))
        self.assertEqual(self.run_q("ask", "--plan", "a-plan", "--ref", "HEAD", "--by", "b", "--root", fresh)[:2], (1, ""))
        self.assertFalse(os.path.exists(os.path.join(fresh, DEC)))

    def test_branch_read_through_full_ref_name(self):  # SP14
        self.hand("a", [Q("q1")])
        git(self.root, "checkout", "-q", "-b", "other", "main")
        self.put(HA, self.handoff_text("a", [Q("q9")]))
        other = commit_all(self.root, "other")
        git(self.root, "checkout", "-q", INTEG)
        git(self.root, "tag", "%s/a/main" % P, other)
        self.assertEqual(self.lst()[1], "pending a-plan:q1 a: Which?\n")

    def test_cleared_env(self):  # GC7
        self.hand("a", [Q()])
        with mock.patch.dict(os.environ, {"GIT_DIR": os.path.join(self.tmp, "nowhere"), "GIT_WORK_TREE": self.tmp}):
            self.assertEqual(self.lst()[1], "pending a-plan:q1 a: Which?\n")

    def test_questions_ignores_colour_and_abbrev_config(self):  # GC1
        self.hand("a", [Q("q1"), Q("q2")])
        self.put_dec(dec(D2, "open", ["q:a-plan:q2"]))
        self.assertEqual(self.lst(), (0, "pending a-plan:q1 a: Which?\nasked a-plan:q2 -> %s\n" % D2, ""))
        code, out, err = self.ask()
        self.assertRegex(out, r"\Aasked a-plan:q1 -> DEC-[0-9]{8}-[0-9a-z]{4}\n\Z")
        self.assertEqual((code, err), (0, ""))


# ---------------------------------------------------------------- Producer 4: --plan --ref sources

class PlanSources(Fx):
    def plan(self, verb, ref, slug="a-plan", *extra):
        return self.run_q(verb, "--plan=" + slug, "--ref=" + ref, "--root", self.root, *extra)

    def test_plan_ref_reads_one_handoff(self):  # SR1, SR7
        self.hand("a", [Q("q1")])
        want = (0, "pending a-plan:q1 a-plan: Which?\n", "")
        sha = git(self.root, "rev-parse", "%s/a/main" % P)
        for ref in ("refs/heads/%s/a/main" % P, sha, "%s/a/main" % P):
            with self.subTest(ref=ref):
                self.assertEqual(self.plan("list", ref), want)

    def test_ref_forms(self):  # SR2
        self.hand("a", [Q()])
        self.fails(self.plan("list", ""), "--ref: must not be empty")
        for ref in ("", "-x", "^x", "a" * 41, "main:foo", "HEAD^{tree}", "a..b", "nope", "a\nb"):
            with self.subTest(ref=ref):
                code, out, err = self.plan("list", ref)
                self.assertEqual((code, out), (1, ""), err)
                self.assertTrue(err.startswith("questions list: --ref: "), err)
        git(self.root, "tag", "-a", "-m", "t", "v1", "%s/a/main" % P)
        self.assertEqual(self.plan("list", "v1")[0], 0)

    def test_plan_slug_charset(self):  # SR3
        self.hand("a", [Q()])
        for slug in ("", "A", "a/b", "a b", "a:b", "..", "a\nb", "é", "-a", "Ꟁ"):
            with self.subTest(slug=slug[:12]), mock.patch.object(tipread, "show_file") as show:
                self.fails(self.plan("list", "main", slug), "--plan: must match [a-z0-9][a-z0-9-]*")
                self.assertFalse(show.called)

    def test_plan_ref_missing(self):  # SR4
        self.hand("a", [Q()])
        self.fails(self.plan("list", "main"), "%s/a-plan/handoff.md: missing at main" % PS)
        self.fails(self.plan("list", "no-such"), "--ref: no-such is not a commit")

    def test_tip_handoff_entry_kinds(self):  # 5b.3 F6: a non-regular handoff at the ref is an errors line, never "missing at"
        rel = PS + "/a-plan/handoff.md"
        branch = "refs/heads/%s/a/main" % P
        text = self.handoff_text("a", [Q("q1")])
        for kind in ("regular", "executable"):
            with self.subTest(kind):
                set_entry(self.root, branch, rel, kind, text)
                self.assertEqual(self.plan("list", "%s/a/main" % P), (0, "pending a-plan:q1 a-plan: Which?\n", ""))
        with self.subTest("absent"):
            set_entry(self.root, branch, rel, "absent")
            self.fails(self.plan("list", "%s/a/main" % P), "plan a-plan: %s: missing at %s/a/main" % (rel, P))
        for kind, mode in BAD_KINDS:
            with self.subTest(kind):
                set_entry(self.root, branch, rel, kind, text)
                e = self.fails(self.plan("list", "%s/a/main" % P), "plan a-plan: %s: %s" % (rel, refusal("%s/a/main" % P, rel)))
                self.assertNotIn("missing at", e)
                e = self.fails(self.lst(), "stream a: %s: %s" % (rel, refusal(branch, rel)))
                self.assertNotIn("pending", e)

    def test_plan_ref_slug_mismatch(self):  # SR5
        self.hand("a", [Q()], slug="b-plan")
        self.fails(self.plan("list", "%s/a/main" % P), "plan: names b-plan, not a-plan")

    def test_plan_mode_tags(self):  # SR6
        self.hand("a", [Q("q1")])
        git(self.root, "checkout", "-q", "main")
        code, out, err = self.plan("ask", "%s/a/main" % P, "a-plan", "--by", "boss")
        self.assertEqual((code, err), (0, ""))
        (rid,) = self.recs()
        self.assertEqual(out, "asked a-plan:q1 -> %s\n" % rid)
        row = self.recs()[rid]
        self.assertEqual(row["topics"], ["q:a-plan:q1"])
        self.assertTrue(not any(k in row for k in ("plan", "program", "stream")))
        self.assertEqual(self.plan("list", "%s/a/main" % P)[1], "asked a-plan:q1 -> %s\n" % rid)  # LS2: slug label


# ---------------------------------------------------------------- Producer 5: the question fields

class QuestionFields(Fx):
    def bad_handoff(self, q, needle):
        self.hand("a", [q] if isinstance(q, dict) else q)
        before = self.snap()
        self.fails(self.lst(), needle)
        self.fails(self.ask(), needle, "ask")
        self.assertEqual(self.snap(), before)

    def test_qid_domain(self):  # HQ1
        for qid in ("Q1", "-q", "", "q 1", "q:1", "q_1", "q\n1", "é"):
            with self.subTest(qid=qid):
                self.bad_handoff(Q(qid=qid), "questions.0.qid: must be a string matching [a-z0-9][a-z0-9-]*")
        self.bad_handoff(Q(qid="q" * 4301), "questions.0.qid: the tag q:a-plan:qqq")
        self.hand("a", [Q(qid="q" * 119)])  # a tag of exactly 128 characters
        self.assertEqual(self.lst()[0], 0)
        self.hand("a", [Q(qid="q" * 120)])
        self.fails(self.lst(), "questions.0.qid: the tag q:a-plan:" + "q" * 10)
        self.assertEqual(questions_cli.MAX_TAG_CHARS, 128)

    def test_duplicate_qid(self):  # HQ2
        self.bad_handoff([Q(), Q()], "questions.1.qid: q1 given twice")

    def test_class_domain(self):  # HQ3
        self.bad_handoff(Q(cls="nonsense"), "questions.0.class: nonsense is not an owner-only class")
        self.hand("a", [Q(qid="q%d" % i, cls=c, recommended=None if c == "model-policy" else "a")
                        for i, c in enumerate(("scope", "model-policy", "triage"))])
        self.assertEqual(self.lst()[0], 0)

    def test_question_text_domain(self):  # HQ4, AM3, AM12
        for text in ("a\nb", "a\r\nb", "café", "a\x00b", "Ꟁ"):
            with self.subTest(text=text):
                self.bad_handoff(Q(question=text), "questions.0.question: must be a single line of printable ASCII")
        for text in ("Use a::b?", "-x", "--x", "x" * 100000):
            with self.subTest(text=text[:8]):
                self.hand("a", [Q(question=text)])
                self.assertEqual(self.lst()[1], "pending a-plan:q1 a: %s\n" % text)  # LS4: raw
        self.hand("a", [Q(question="--x")])
        self.assertEqual(self.ask()[0], 0)
        (row,) = self.recs().values()
        self.assertEqual(row["question"], "--x")
        for rid in list(self.recs()):
            self.put_dec(dict(self.recs()[rid], status="withdrawn", withdrawn={"at": "a1b2c3d", "by": "w@e.invalid", "reason": "r"}))
        self.hand("a", [Q(question=" lead")])  # passes handoff_errors, refused by decisions ask (D-Q9)
        code, out, err = self.ask()
        self.assertEqual((code, out), (1, ""))
        self.assertIn("questions ask: a-plan:q1: decisions ask: --question: must not start or end with a space", err)

    def test_effect_domain(self):  # HQ5, AM5
        for eff in ("Lasting", "", None):
            with self.subTest(effect=eff):
                self.bad_handoff(Q(effect=eff), "questions.0.effect")
        for eff in ("lasting", "one-off"):
            self.hand("a", [Q(effect=eff)])
            self.assertEqual(self.ask()[0], 0)
            rid = [r for r, row in self.recs().items() if row["status"] == "open"][0]
            self.assertEqual(self.recs()[rid]["effect"], eff)
            self.put_dec(dict(self.recs()[rid], status="withdrawn", withdrawn={"at": "a1b2c3d", "by": "w@e.invalid", "reason": "r"}))

    def test_option_domain(self):  # HQ6, AM4
        self.bad_handoff(Q(options=(("a", "ca"),)), "options")
        self.bad_handoff(Q(options=()), "options")
        self.hand("a", [Q(options=(("-a", "ca"), ("b", "cb")), recommended="-a")])
        self.assertEqual(self.ask()[0], 0)
        (row,) = self.recs().values()
        self.assertEqual((row["options"], row["recommended"]), ([{"label": "-a", "cost": "ca"}, {"label": "b", "cost": "cb"}], "-a"))

    def test_ask_option_with_double_colon(self):  # AM4, AS5
        for opts in ((("a::x", "ca"), ("b", "cb")), (("a:", "b"), ("c", "d")), 
                     ((" a", "ca"), ("b", "cb")), (("a", "ca"), ("a", "cb"), ("b", "cc"))):
            with self.subTest(opts=opts):
                self.hand("a", [Q(options=opts, recommended=opts[-1][0])])
                code, out, err = self.ask()
                self.assertEqual((code, out), (1, ""))
                self.assertIn("questions ask: a-plan:q1: decisions ask: --option", err)
        self.assertEqual(self.recs(), {})

    def test_option_order_preserved(self):  # HQ7
        self.hand("a", [Q(options=(("b", "cb"), ("a", "ca"), ("c", "cc")), recommended="c")])
        self.assertEqual(self.ask()[0], 0)
        (row,) = self.recs().values()
        self.assertEqual([o["label"] for o in row["options"]], ["b", "a", "c"])

    def test_recommend_domain(self):  # HQ8, AM8
        for rec in ("zzz", "", None, 5):
            with self.subTest(rec=rec):
                self.bad_handoff(Q(recommended=rec), "recommended")
        self.bad_handoff(Q(options=(("a", "x"), ("a", "y"))), "questions.q1.recommended: a is not the label of exactly one option")
        self.bad_handoff(Q(cls="model-policy", recommended="a"), "questions.q1.recommended: class model-policy carries no")
        self.hand("a", [Q(cls="model-policy", recommended=None)])
        self.assertEqual(self.ask()[0], 0)
        (row,) = self.recs().values()
        self.assertNotIn("recommended", row)
        self.assertEqual(row["class"], "model-policy")

    def test_source_domain(self):  # HQ9, AM7
        self.hand("a", [Q(source="r/worker-report.md")])
        self.assertEqual(self.ask()[0], 0)
        (rid,) = self.recs()
        self.assertEqual(self.recs()[rid]["source"], "r/worker-report.md")
        self.put_dec(dict(self.recs()[rid], status="withdrawn", withdrawn={"at": "a1b2c3d", "by": "w@e.invalid", "reason": "r"}))
        self.bad_handoff(Q(source=""), "questions.q1.source: must be a non-empty single line")
        for src in ("r/a b.md", "r/a.md#x", "r/*.md", "/abs", "../x", "r//x"):
            with self.subTest(src=src):
                self.hand("a", [Q(source=src)])
                code, out, err = self.ask()
                self.assertEqual((code, out), (1, ""))
                self.assertIn("questions ask: a-plan:q1: decisions ask: --source", err)

    def test_zero_questions(self):  # HQ10, AS1
        self.hand("a", [])
        self.hand("b", [])
        before = self.snap()
        self.assertEqual(self.lst(), (0, "", ""))
        self.assertEqual(self.ask(), (0, "", ""))
        self.assertEqual(self.snap(), before)

    def test_many_questions_run(self):  # HQ11
        self.hand("a", [Q("q%d" % i, question="Q %d?" % i) for i in range(1000)])
        out = self.lst()[1].splitlines()
        self.assertEqual(out[0], "pending a-plan:q0 a: Q 0?")
        self.assertEqual((len(out), out[-1]), (1000, "pending a-plan:q999 a: Q 999?"))

    def test_many_questions_ask_run(self):  # HQ11: 40 pending questions through ask, one by one (the register is re-read per question, so cost is quadratic: 200 took 223 s on 3.9 and 326 s on 3.13, hence 40; decision P4.1 D-Q7, controller under owner delegation 2026-11-09, F-20261121-dt8k)
        self.hand("a", [Q("q%d" % i) for i in range(40)])
        code, out, err = self.ask()
        self.assertEqual((code, err, len(out.splitlines())), (0, "", 40))
        self.assertEqual([l.split()[1] for l in out.splitlines()], ["a-plan:q%d" % i for i in range(40)])
        self.assertEqual(len(self.recs()), 40)

    def test_questions_wrong_type(self):  # HQ12
        for v in ('"x"', "{a: 1}", "null"):
            with self.subTest(v=v):
                text = self.handoff_text("a", []).replace("questions: []", "questions: " + v)
                self.hand("a", [], text=text)
                self.fails(self.lst(), "stream a: " + HA)
        text = "\n".join(l for l in self.handoff_text("a", []).split("\n") if not l.startswith("questions"))
        self.hand("a", [], text=text)
        self.fails(self.lst(), "stream a: " + HA)

    def test_numeric_text_limits_both_interpreters(self):  # V1
        for digits in (1001, 4300, 4301):
            for lim in INT_LIMITS:
                with self.subTest(digits=digits, limit=lim), int_limit(lim):
                    self.hand("a", [Q()], rulings=yamlsub.parse("0") or 0)
                    text = self.handoff_text("a", [Q()]).replace("rulings: 0", "rulings: " + "9" * digits)
                    self.hand("a", [], text=text)
                    self.fails(self.lst(), "stream a: " + HA)
        text = self.handoff_text("a", [Q()]).replace("rulings: 0", "rulings: " + "9" * 599)
        self.hand("a", [], text=text)
        self.assertEqual(self.lst()[0], 0)

    def test_unicode_version_independent(self):  # V2
        with open(os.path.join(REPO, "gates", "tools", "questions_cli.py"), encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        banned = {"lower", "upper", "casefold", "isprintable", "isalnum", "isdigit", "isalpha", "isidentifier",
                  "isnumeric", "isdecimal", "isspace"}
        called = {n.func.attr for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
        self.assertEqual(called & banned, set())
        self.bad_handoff(Q(question="Ꟁ"), "questions.0.question: must be a single line of printable ASCII")
        self.bad_handoff(Q(options=(("Ꟁ", "c"), ("b", "c")), recommended="b"), "options.0.label")

    def test_exception_groups_propagate(self):  # V3
        with open(os.path.join(REPO, "gates", "tools", "questions_cli.py"), encoding="utf-8") as fh:
            src = fh.read()
        self.assertNotIn("except*", src)
        self.assertNotIn("ExceptionGroup", src)
        if not hasattr(builtins, "BaseExceptionGroup"):
            self.skipTest("BaseExceptionGroup does not exist before Python 3.11")
        self.hand("a", [Q()])
        grp = getattr(builtins, "ExceptionGroup")("x", [ValueError()])
        with mock.patch.object(tipread, "show_file", side_effect=grp), self.assertRaises(getattr(builtins, "ExceptionGroup")):
            self.lst()
        self.hand("a", [Q(), Q("q2")])
        bgrp = getattr(builtins, "BaseExceptionGroup")("x", [KeyboardInterrupt()])
        with mock.patch.object(decisions_cli, "main", side_effect=bgrp), \
                self.assertRaises(getattr(builtins, "BaseExceptionGroup")):
            self.ask()
        self.assertEqual(self.recs(), {})


# ---------------------------------------------------------------- Producer 6: tags and the register

class Tags(Fx):
    def setUp(self):
        super().setUp()
        self.hand("a", [Q("q1")])

    def test_tag_text(self):  # TG1
        self.assertEqual(questions_cli.tag("a-plan", "q1"), "q:a-plan:q1")
        for bad in (("A", "q"), ("a", "Q"), ("a:b", "q"), ("a", "q:1"), ("", "q"), (5, "q"), ("a", None), ("a", "q" * 130)):
            with self.subTest(bad=bad[:1]), self.assertRaises(ValueError):
                questions_cli.tag(*bad)
        self.assertEqual(len(questions_cli.tag("a-plan", "q" * 119)), 128)

    def test_tag_unambiguous(self):  # TG13, M17
        self.assertNotEqual(questions_cli.tag("a", "b-c"), questions_cli.tag("a-b", "c"))
        self.assertEqual(questions_cli.tag("a", "b-c"), "q:a:b-c")

    def test_withdrawn_is_ignored(self):  # TG6
        self.put_dec(dec(D2, "withdrawn", ["q:a-plan:q1"]))
        self.assertEqual(self.lst()[1], "pending a-plan:q1 a: Which?\n")

    def test_withdrawn_then_reasked(self):  # TG7
        self.put_dec(dec(D2, "withdrawn", ["q:a-plan:q1"]), dec(D3, "open", ["q:a-plan:q1"]))
        out = self.lst()[1]
        self.assertEqual(out, "asked a-plan:q1 -> %s\n" % D3)
        self.assertNotIn(D2, out)

    def test_withdrawn_then_answered(self):  # TG8, TG10
        self.put_dec(dec(D2, "withdrawn", ["q:a-plan:q1"]), dec(D3, "answered", ["q:a-plan:q1"]))
        self.assertEqual(self.lst()[1], "answered a-plan:q1 -> %s\n" % D3)

    def test_withdrawn_does_not_count_as_duplicate(self):
        self.put_dec(dec(D2, "withdrawn", ["q:a-plan:q1"]), dec(D3, "withdrawn", ["q:a-plan:q1"]), dec(D4, "open", ["q:a-plan:q1"]))
        self.assertEqual(self.lst()[0], 0)

    def test_two_decisions_one_tag_is_error(self):  # TG9
        for sts in (("open", "open"), ("open", "answered"), ("answered", "answered")):
            with self.subTest(sts=sts):
                self.put_dec(dec(D4, sts[0], ["q:a-plan:q1"]), dec(D5, sts[1], ["q:a-plan:q1"]))
                code, out, err = self.lst()
                self.assertEqual((code, out), (1, ""))
                self.assertIn(D4, err)
                self.assertIn(D5, err)
                self.assertEqual(self.ask()[:2], (1, ""))
        self.assertEqual(len(self.recs()), 2)

    def test_three_decisions_one_tag(self):  # TG11
        self.put_dec(dec(D6, "open", ["q:a-plan:q1"]), dec(D4, "open", ["q:a-plan:q1"]), dec(D5, "answered", ["q:a-plan:q1"]))
        e = self.fails(self.lst(), "q:a-plan:q1: carried by decisions %s, %s, %s" % (D4, D5, D6))
        self.assertEqual(e.count("\n"), 1)

    def test_tag_exact_equality(self):  # TG12
        for t in ("Q:A-PLAN:Q1", "q:a-plan:q1 ", "q:a-plan:q10", "q:a-plan", "q:a-plan:q1:x", "q-a-plan-q1", "q:a-plan:q"):
            self.put_dec(dec(D2, "open", [t]))
            self.assertEqual(self.lst()[1], "pending a-plan:q1 a: Which?\n", t)

    def test_decision_topics_types(self):  # TG14, TG15, TG18
        for name, row in (("nested", dec(D2, topics=[["q"]])), ("int", dec(D2, topics=[5])), 
                          ("status", dec(D2, status="closed")), ("no status", {k: v for k, v in dec(D2).items() if k != "status"})):
            with self.subTest(name):
                self.put_dec(row)
                code, out, err = self.lst()
                self.assertEqual((code, out), (1, ""))
                self.assertIn("%s/%s.yml" % (DEC, D2), err)
        # decisions.validate accepts a string `topics` (unrelated finding U6); such a record is not this tag
        self.put_dec(dec(D2, topics="q:a-plan:q1"))
        self.assertEqual(self.lst()[1], "pending a-plan:q1 a: Which?\n")
        self.put(DEC + "/DEC-20261031-x1x1.yml", "- a\n")
        os.remove(os.path.join(self.root, DEC, D2 + ".yml"))
        code, out, err = self.lst()
        self.assertEqual((code, out), (1, ""))
        self.assertIn("DEC-20261031-x1x1.yml", err)

    def test_decision_status_domain(self):
        self.put_dec(dec(D2, status="closed", topics=["q:a-plan:q1"]))
        self.assertEqual(self.lst()[0], 1)

    def test_bad_record_refused(self):
        self.put(DEC + "/junk.txt", "not a record\n")
        self.assertEqual(self.lst()[0], 1)

    def test_records_from_root_working_tree_only(self):  # TG16
        git(self.root, "checkout", "-q", "main")
        self.put_dec(dec(D2, "open", ["q:a-plan:q1"]))
        commit_all(self.root, "record on main")
        git(self.root, "checkout", "-q", INTEG)
        self.assertFalse(os.path.exists(os.path.join(self.root, DEC, D2 + ".yml")))
        self.assertEqual(self.lst()[1], "pending a-plan:q1 a: Which?\n")

    def test_no_decisions_dir(self):  # TG17
        self.assertFalse(os.path.exists(os.path.join(self.root, DEC)))
        self.assertEqual(self.lst()[1], "pending a-plan:q1 a: Which?\n")

    def test_answered_line_has_id_only(self):  # TG19
        self.put_dec(dec(D2, "answered", ["q:a-plan:q1"]))
        self.assertEqual(self.lst()[1], "answered a-plan:q1 -> %s\n" % D2)
        self.assertNotIn("SECRET-ANSWER", self.lst()[1])


class QuestionState(unittest.TestCase):
    """``question_state`` (the lookup ``list`` and ``ask`` call; Task P4.2 imports it), called directly."""

    def recs(self, *rows):
        return [store.Record(r["id"], r, "f/%s.yml" % r["id"]) for r in rows]

    def test_states(self):  # TG3-TG8
        t = "q:a-plan:q1"
        self.assertEqual(questions_cli.question_state([], t), ("pending", None))
        self.assertEqual(questions_cli.question_state(self.recs(dec(D2, "open", [t])), t), ("asked", D2))
        self.assertEqual(questions_cli.question_state(self.recs(dec(D2, "answered", [t])), t), ("answered", D2))
        self.assertEqual(questions_cli.question_state(self.recs(dec(D2, "withdrawn", [t])), t), ("pending", None))
        self.assertEqual(questions_cli.question_state(self.recs(dec(D2, "withdrawn", [t]), dec(D3, "open", [t])), t), ("asked", D3))
        self.assertEqual(questions_cli.question_state(self.recs(dec(D2, "withdrawn", [t]), dec(D3, "answered", [t])), t), ("answered", D3))
        self.assertEqual(questions_cli.question_state(self.recs(dec(D2, "open", ["q:a-plan:q10", "other"])), t), ("pending", None))

    def test_two_carriers_raise_naming_both(self):  # TG9, TG11
        t = "q:a-plan:q1"
        with self.assertRaises(GateError) as cm:
            questions_cli.question_state(self.recs(dec(D5, "open", [t]), dec(D4, "answered", [t])), t)
        self.assertEqual(str(cm.exception), "q:a-plan:q1: carried by decisions %s, %s" % (D4, D5))
        with self.assertRaises(GateError) as cm:
            questions_cli.question_state(self.recs(dec(D6, "open", [t]), dec(D4, "open", [t]), dec(D5, "open", [t])), t)
        self.assertEqual(str(cm.exception), "q:a-plan:q1: carried by decisions %s, %s, %s" % (D4, D5, D6))


# ---------------------------------------------------------------- Producer 7: list output

class ListOutput(Fx):
    def test_list_writes_nothing(self):  # LS3, M14
        self.hand("a", [Q("q1"), Q("q2")])
        self.put_dec(dec(D2, "open", ["q:a-plan:q2"]))
        before = self.snap()
        self.lst()
        self.assertEqual(self.snap(), before)

    def test_questions_prints_no_batch(self):  # LS5
        self.hand("a", [Q("q1")])
        for line in self.lst()[1].splitlines():
            self.assertRegex(line, r"^(pending [a-z0-9-]+:[a-z0-9-]+ [a-z0-9-]+: .*|(asked|answered) [a-z0-9-]+:[a-z0-9-]+ -> DEC-.*)$")

    def test_list_deterministic(self):  # LS6
        self.hand("a", [Q("q2"), Q("q1")])
        self.hand("b", [Q("q1")])
        first = self.lst()
        self.assertEqual(first, self.lst())
        self.assertEqual(first[1].splitlines()[:2], ["pending a-plan:q2 a: Which?", "pending a-plan:q1 a: Which?"])

    def test_list_after_ask(self):  # LS7
        self.hand("a", [Q("q1"), Q("q2")])
        code, out, err = self.ask()
        ids = [l.split()[-1] for l in out.splitlines()]
        self.assertEqual(self.lst()[1], "asked a-plan:q1 -> %s\nasked a-plan:q2 -> %s\n" % tuple(ids))

    def test_list_partial_failure(self):  # LS8, M13
        self.hand("a", [Q("q1")])
        self.hand("b", [], text="garbage\n")
        code, out, err = self.lst()
        self.assertEqual((code, out), (1, ""))
        self.assertIn("stream b: " + HB, err)

    def test_list_and_ask_call_question_state(self):  # the lookup is one function (controller addition)
        self.hand("a", [Q("q1")])
        with mock.patch.object(questions_cli, "question_state", return_value=("answered", D2)) as qs:
            self.assertEqual(self.lst(), (0, "answered a-plan:q1 -> %s\n" % D2, ""))
            self.assertEqual(self.ask(), (0, "", ""))
        self.assertEqual([c.args[1] for c in qs.call_args_list], ["q:a-plan:q1"] * 2)
        self.assertEqual(self.recs(), {})

    def test_list_stream_or_plan_field(self):  # LS2
        self.hand("b", [Q("q1")])
        self.assertEqual(self.lst()[1], "pending b-plan:q1 b: Which?\n")


# ---------------------------------------------------------------- Producers 8, 9: ask

class AskTests(Fx):
    def fake(self, rc=0, out="DEC-20261101-aaaa\n", err=""):
        calls = []

        def main(argv):
            calls.append(list(argv))
            sys.stdout.write(out)
            sys.stderr.write(err)
            return rc
        return calls, mock.patch.object(decisions_cli, "main", side_effect=main)

    def test_ask_argv_exact(self):  # AM1, AM6, AM2, AM5
        self.hand("a", [Q("q1", source="r/worker-report.md"), Q("q2", cls="model-policy", recommended=None)])
        calls, p = self.fake()
        with p:
            self.assertEqual(self.run_q("ask", "--program", P, "--by=-boss", "--root", self.root)[0], 0)
        self.assertEqual(calls[0], ["ask", "--class=scope", "--question=Which?", "--option=a::ca", "--option=b::cb",
                                    "--effect=lasting", "--topic=q:a-plan:q1", "--source=r/worker-report.md",
                                    "--recommend=a", "--by=-boss", "--root=" + self.root])
        self.assertEqual(calls[1], ["ask", "--class=model-policy", "--question=Which?", "--option=a::ca",
                                    "--option=b::cb", "--effect=lasting", "--topic=q:a-plan:q2", "--source=" + HA,
                                    "--by=-boss", "--root=" + self.root])

    def test_ask_writes_one_decision_per_pending_question(self):  # AM10, AS2, AS11, TG-plan test
        self.hand("a", [Q("q1"), Q("q2")])
        head = git(self.root, "rev-parse", "HEAD")
        code, out, err = self.ask()
        self.assertEqual((code, err), (0, ""))
        lines = out.splitlines()
        self.assertEqual(len(lines), 2)
        for l, qid in zip(lines, ("q1", "q2")):
            self.assertRegex(l + "\n", r"\Aasked a-plan:%s -> DEC-[0-9]{8}-[0-9a-z]{4}\n\Z" % qid)
        new = [l.split()[-1] for l in lines]
        recs = self.recs()
        self.assertEqual(sorted(recs), sorted(new))
        row = recs[new[0]]
        self.assertEqual((row["topics"], row["status"], row["recommended"], row["source"]),
                         (["q:a-plan:q1"], "open", "a", HA))
        self.assertEqual((row["asked_at"], row["asked_by"], row["applies_to"], row["checked_against"]),
                         (head, "boss", [], []))
        self.assertTrue(not any(k in row for k in ("plan", "program", "stream")))
        self.assertEqual(recs[new[1]]["topics"], [["q:a-plan:q2"][0]])

    def test_ask_uses_question_source_when_given(self):  # plan :3107-3108 (AM7, HQ9)
        self.hand("a", [Q("q1", source="r/worker-report.md"), Q("q2")])
        code, out, err = self.ask()
        self.assertEqual((code, err), (0, ""))
        new_src, new_plain = [l.split()[-1] for l in out.splitlines()]
        self.assertEqual(self.recs()[new_src]["source"], "r/worker-report.md")
        self.assertEqual(self.recs()[new_plain]["source"], HA)

    def test_ask_twice_asks_nothing_new(self):  # AS3
        self.hand("a", [Q("q1")])
        self.assertEqual(self.ask()[0], 0)
        before = self.recs()
        self.assertEqual(self.ask(), (0, "", ""))
        self.assertEqual(self.recs(), before)

    def test_ask_only_pending(self):  # AS4
        self.hand("a", [Q("q1"), Q("q2"), Q("q3")])
        self.put_dec(dec(D2, "open", ["q:a-plan:q2"]), dec(D3, "answered", ["q:a-plan:q3"]))
        code, out, err = self.ask()
        self.assertEqual(code, 0)
        self.assertEqual([l.split()[1] for l in out.splitlines()], ["a-plan:q1"])
        self.assertEqual(len(self.recs()), 3)

    def test_ask_failure_stops_after_reporting(self):  # AS5, AS6, AS7, AS8
        self.hand("a", [Q("q1"), Q("q2", cls="merge-grant"), Q("q3")])
        code, out, err = self.ask()
        self.assertEqual(code, 1)
        self.assertRegex(out, r"\Aasked a-plan:q1 -> DEC-[0-9]{8}-[0-9a-z]{4}\n\Z")
        self.assertIn("questions ask: a-plan:q2: decisions ask: ", err)
        self.assertNotIn("q3", err + out)
        self.assertEqual(len(self.recs()), 1)  # q1's record stays, q3 not asked
        for rid in list(self.recs()):
            self.put_dec(dict(self.recs()[rid], status="withdrawn", withdrawn={"at": "a1b2c3d", "by": "w@e.invalid", "reason": "r"}))
        self.hand("a", [Q("q2", cls="merge-grant"), Q("q3")])
        self.assertEqual(self.ask()[:2], (1, ""))
        calls, p = self.fake(rc=2, out="", err="usage: x\n")
        self.hand("a", [Q("q1")])
        with p:
            code, out, err = self.ask()
        self.assertEqual((code, out, err), (1, "", "questions ask: a-plan:q1: usage: x\n"))

    def test_ask_record_written_but_index_failed(self):  # AS9
        self.hand("a", [Q("q1"), Q("q2")])
        with mock.patch("gates.tools.index.regenerate", side_effect=GateError("boom")):
            code, out, err = self.ask()
        self.assertEqual(code, 1)
        (rid,) = self.recs()
        self.assertEqual(out, "asked a-plan:q1 -> %s\n" % rid)
        self.assertIn("questions ask: a-plan:q1: ", err)
        self.assertIn("indexes not regenerated", err)

    def test_ask_id_taken_from_output(self):  # AS10, D-Q7
        self.hand("a", [Q("q1")])
        calls, p = self.fake(out="candidate DEC-20260101-zzzz: Older?\nDEC-20261101-aaaa\n")
        with p:
            self.assertEqual(self.ask(), (0, "asked a-plan:q1 -> DEC-20261101-aaaa\n", ""))
        for out in ("", "nonsense\n", "DEC-20261301-aaaa\n"):
            calls, p = self.fake(out=out)
            with p:
                code, o, e = self.ask()
            self.assertEqual((code, o), (1, ""), out)
            self.assertIn("questions ask: a-plan:q1: ", e)

    def test_ask_nonzero_exit_stops(self):  # AS8
        self.hand("a", [Q("q1"), Q("q2")])
        calls, p = self.fake(rc=1, out="DEC-20261101-aaaa\n", err="decisions ask: written; indexes not regenerated (x)\n")
        with p:
            code, out, err = self.ask()
        self.assertEqual((code, out), (1, "asked a-plan:q1 -> DEC-20261101-aaaa\n"))
        self.assertEqual(len(calls), 1)
        self.assertEqual(err, "questions ask: a-plan:q1: decisions ask: written; indexes not regenerated (x)\n")

    def test_ask_rechecks_tag_before_each_call(self):  # AS12
        self.hand("a", [Q("q1"), Q("q2")])
        real = decisions_cli.main
        n = []

        def main(argv):
            rc = real(argv)
            if not n:
                n.append(1)
                self.put_dec(dec(D2, "open", ["q:a-plan:q2"]))
            return rc
        with mock.patch.object(decisions_cli, "main", side_effect=main):
            code, out, err = self.ask()
        self.assertEqual((code, len(out.splitlines())), (0, 1))
        self.assertEqual(len([r for r in self.recs().values() if "q:a-plan:q2" in r["topics"]]), 1)

    def test_ask_writes_under_root(self):  # AS13, M15
        self.hand("a", [Q("q1")])
        repo_before = git(REPO, "status", "--porcelain", "--untracked-files=all")
        self.assertEqual(self.ask()[0], 0)
        self.assertEqual(len(self.recs()), 1)
        self.assertEqual(git(REPO, "status", "--porcelain", "--untracked-files=all"), repo_before)
        self.assertTrue(git(self.root, "status", "--porcelain", "--untracked-files=all").startswith("?? "))

    def test_ask_leaves_files_for_commit(self):  # AM13, AM11
        self.hand("a", [Q("q1")])
        self.put_dec(dec(D2, "answered", ["other"], question="Which thing?"))
        head = git(self.root, "rev-parse", "HEAD")
        code, out, err = self.ask()
        self.assertEqual(code, 0)
        self.assertNotIn("candidate", out)
        self.assertEqual(git(self.root, "rev-parse", "HEAD"), head)
        status = git(self.root, "status", "--porcelain", "--untracked-files=all")
        self.assertIn(out.split()[-1], status)

    def test_ask_records_print_in_batch(self):  # AS14
        self.hand("a", [Q("q1")])
        self.ask()
        out, buf = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(buf):
            self.assertEqual(gates_main.main(["decisions", "batch", "--root", self.root]), 0)
        self.assertIn("### source: " + HA, out.getvalue())
        self.assertIn("Which?", out.getvalue())

    def test_ask_branch_rule(self):  # D-Q4 (x)
        self.hand("a", [Q("q1")])
        git(self.root, "checkout", "-q", "main")
        self.fails(self.ask(), "must run on %s (HEAD is main)" % INTEG, "ask")
        git(self.root, "checkout", "-q", "--detach")
        self.fails(self.ask(), "must run on %s (HEAD is detached)" % INTEG, "ask")
        self.assertEqual(self.recs(), {})
        self.assertEqual(self.run_q("ask", "--plan", "a-plan", "--ref", "%s/a/main" % P, "--by", "b", "--root", self.root)[0], 0)

    def test_ask_refusal_leaves_tree_unchanged(self):  # AS16
        self.hand("a", [Q("q1")])
        self.hand("b", [], text="garbage\n")
        before = self.snap()
        self.assertEqual(self.ask()[0], 1)
        self.assertEqual(self.snap(), before)


if __name__ == "__main__":
    unittest.main()
