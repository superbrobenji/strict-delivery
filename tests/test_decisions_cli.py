"""Tests of gates/tools/decisions_cli.py through ``main(argv)`` on real fixture repositories (Task 1d.1 input-domain
table rows A-I; block 1d decisions D-1..D-18). Expected ids, fields, lines and exit codes are written by hand from the
plan and the spec; records are read back with ``Store.load``."""
import ast
import contextlib
import io
import os
import random
import stat
import subprocess
import sys
import unittest
from unittest import mock

from gates import __main__ as gates_main
from gates import gate_decisions, gate_schema, producers
from gates.lib import config, decisions, ids, schema
from gates.lib.store import Store
from gates.tools import decisions_cli
from tests.helpers import E128, TOP, GitIsolatedTestCase, commit_all, git, make_repo, minimal_config, write_record

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEC = ".strict-delivery/state/decisions"
FIN = ".strict-delivery/state/findings"
SHA = "a1b2c3d"
OPTS = [{"label": "yes", "cost": "none"}, {"label": "no", "cost": "rework"}]
DA, DB, DC, DD = "DEC-20261031-a2b3", "DEC-20261031-c4d5", "DEC-20261031-e6f7", "DEC-20261031-g8h9"
DE, DF, DG = "DEC-20261031-j2k3", "DEC-20261031-m4n5", "DEC-20261031-p6q7"
MISSING = "DEC-20261031-z9z9"
FA = "F-20261031-a2b3"
EMAIL_MSG = "set git config user.email; the answer records it"


def dtag():  # Q-2a1-3: the tag comes from the schema
    return "decision/%d" % decisions._schema().version


def ftag():
    s = schema.load_schema(os.path.join(schema.SCHEMAS_DIR, "finding.yml"))
    return "%s/%d" % (s.kind, s.version)


def dec(id_, status="answered", **over):
    r = {"schema": dtag(), "id": id_, "status": status, "class": "scope", "question": "Keep X?", "options": OPTS,
         "asked_at": SHA, "asked_by": "agent", "topics": [], "applies_to": [], "checked_against": [],
         "effect": "one-off"}
    if status == "answered":
        r.update(answer="Yes", answered_at={"at": SHA, "by": "who@example.invalid"})
    if status == "withdrawn":
        r["withdrawn"] = {"at": SHA, "by": "who@example.invalid", "reason": "asked twice"}
    r.update(over)
    return {k: v for k, v in r.items() if v is not None}


def fnd(id_):
    return {"schema": ftag(), "id": id_, "status": "open", "source": "review", "severity": "HIGH", "class": "bug",
            "siblings": [], "cites": [], "repro": None, "owner": {"kind": "plan", "plan": "p", "task": "1a.2"},
            "pin": None, "ruling": None, "evidence": [], "history": [{"status": "open", "sha": SHA, "by": "agent"}]}


def ask_argv(cls="scope", question="Keep the prefix rule?", options=("yes::none", "no::rework"), effect="one-off",
             by="controller", extra=()):
    argv = ["ask", "--class", cls, "--question", question]
    for o in options:
        argv += ["--option", o]
    return argv + ["--effect", effect, "--by", by] + list(extra)


class Base(GitIsolatedTestCase):
    def setUp(self):
        super().setUp()
        self.root = make_repo(self.work)

    def cfg(self):
        return config.load(self.root)

    def put(self, *rows, commit=False):
        for r in rows:
            write_record(self.root, "%s/%s.yml" % (DEC, r["id"]), r)
        if commit:
            commit_all(self.root, "records")

    def cli(self, *args, root=True):
        argv = list(args) + (["--root", self.root] if root else [])
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = decisions_cli.main(argv)
        return code, out.getvalue(), err.getvalue()

    def recs(self):
        return {r.id: r.row for r in Store(self.root, "decision", self.cfg()).load()}

    def rec(self, id_):
        return self.recs()[id_]

    def snap(self):
        out = {}
        for d, dirs, files in os.walk(self.root):
            dirs[:] = [x for x in dirs if x != ".git"]
            for f in files:
                p = os.path.join(d, f)
                with open(p, "rb") as fh:
                    out[os.path.relpath(p, self.root)] = fh.read()
        return out

    def refused(self, args, needle, root=True):
        before = self.snap()
        code, out, err = self.cli(*args, root=root)
        self.assertEqual((code, out), (1, ""), err)
        self.assertTrue(err.startswith("decisions %s: " % args[0]), err)
        self.assertEqual(err.count("\n"), 1, err)
        self.assertIn(needle, err)
        self.assertEqual(self.snap(), before)
        return err

    def usage(self, args):
        before = self.snap()
        code, out, err = self.cli(*args)
        self.assertEqual((code, out), (2, ""), err)
        self.assertIn("usage:", err)
        self.assertEqual(self.snap(), before)
        return err

    def ask(self, *args, **kw):
        code, out, err = self.cli(*ask_argv(*args, **kw))
        self.assertEqual((code, err), (0, ""), err)
        return out.splitlines()[-1], out


# ---------------------------------------------------------------- plan Step 1 tests

class PlanTests(Base):
    def test_ask_writes_open_record_with_candidates(self):  # an answered record shares topic "ids"; D1, D15, E11
        self.put(dec(DA, topics=["ids"], question="Old question"))
        new, out = self.ask(extra=["--topic", "ids"])
        self.assertIn("candidate " + DA + ": ", out)
        r = self.rec(new)
        self.assertEqual((r["status"], r["checked_against"], r["asked_by"]), ("open", [DA], "controller"))
        self.assertEqual(out, "candidate %s: Old question\n%s\n" % (DA, new))

    def test_ask_one_option_writes_nothing(self):  # C1
        self.refused(ask_argv(options=("yes::none",)), "options")

    def test_ask_id_format_and_date(self):  # E1, E5
        new, _ = self.ask()
        self.assertEqual(ids.id_problem(new, "DEC"), "")
        self.assertEqual(new.split("-")[1], ids.utc_today().strftime("%Y%m%d"))
        head = git(self.root, "rev-parse", "HEAD")
        self.assertEqual(self.rec(new), {
            "schema": dtag(), "id": new, "status": "open", "class": "scope", "question": "Keep the prefix rule?",
            "options": [{"label": "yes", "cost": "none"}, {"label": "no", "cost": "rework"}], "asked_at": head,
            "asked_by": "controller", "topics": [], "applies_to": [], "checked_against": [], "effect": "one-off"})

    def test_decide_records_git_email(self):  # F6
        self.put(dec(DA, "open"))
        code, out, err = self.cli("decide", DA, "--answer", "Yes, keep it")
        self.assertEqual((code, out, err), (0, DA + "\n", ""))
        r = self.rec(DA)
        head = git(self.root, "rev-parse", "HEAD")
        self.assertEqual((r["status"], r["answer"], r["answered_at"]),
                         ("answered", "Yes, keep it", {"at": head, "by": "fixture@example.invalid"}))
        self.assertNotIn("landed_in", r)

    def test_decide_without_email_refused(self):  # OQ-11; B10: unset, empty, whitespace-only
        self.put(dec(DA, "open"))
        before = self.rec(DA)
        for value in (None, "", "   "):
            with self.subTest(value=value):
                if value is None:
                    git(self.root, "config", "--unset", "user.email", check=False)
                else:
                    git(self.root, "config", "user.email", value)
                self.refused(["decide", DA, "--answer", "Yes"], EMAIL_MSG)
                self.assertEqual(self.rec(DA), before)

    def test_ask_grant_fields(self):  # OQ-8; C7, C8
        self.refused(ask_argv(cls="merge-grant"), "plan")
        self.refused(ask_argv(cls="triage", extra=["--plan", "p"]), "plan: must be absent unless class is merge-grant")
        grant, _ = self.ask(cls="merge-grant", extra=["--plan", "2026-10-31-strict-delivery-framework"])
        self.assertEqual(self.rec(grant)["plan"], "2026-10-31-strict-delivery-framework")
        self.assertNotIn("program", self.rec(grant))

    def test_decide_writes_rule(self):  # OQ-12; F7
        self.put(dec(DA, "open"))
        self.assertEqual(self.cli("decide", DA, "--answer", "Yes", "--rule", "one-line rule")[0], 0)
        self.assertEqual(self.rec(DA)["rule"], "one-line rule")

    def test_decide_lasting_without_landed_in_refused(self):  # A10, F8
        self.put(dec(DA, "open", effect="lasting"))
        self.refused(["decide", DA, "--answer", "Yes"], "landed_in")
        self.assertEqual(self.rec(DA)["status"], "open")

    def test_decide_landed_in_spec_refused(self):  # F8
        self.put(dec(DA, "open", effect="lasting"))
        os.makedirs(os.path.join(self.root, "docs/strict-delivery/specs"))
        with open(os.path.join(self.root, "docs/strict-delivery/specs/s.md"), "w") as fh:
            fh.write(DA + "\n")
        commit_all(self.root, "spec")
        self.refused(["decide", DA, "--answer", "Yes", "--landed-in", "docs/strict-delivery/specs/s.md"], "is a spec")

    def test_decide_answered_record_refused(self):  # F3
        self.put(dec(DA))
        before = self.snap()
        self.refused(["decide", DA, "--answer", "Again"], DA + " is not open")
        self.assertEqual(self.snap(), before)

    def test_withdraw_shape(self):  # OQ-7; F10
        self.put(dec(DA, "open"))
        code, out, err = self.cli("withdraw", DA, "--reason", "dup")
        self.assertEqual((code, out, err), (0, DA + "\n", ""))
        r = self.rec(DA)
        head = git(self.root, "rev-parse", "HEAD")
        self.assertEqual((r["status"], r["withdrawn"]),
                         ("withdrawn", {"at": head, "by": "fixture@example.invalid", "reason": "dup"}))
        self.assertNotIn("answer", r)

    def test_withdraw_without_email_refused(self):  # I3; B10
        self.put(dec(DA, "open"))
        for value in (None, "", " \t "):
            with self.subTest(value=value):
                if value is None:
                    git(self.root, "config", "--unset", "user.email", check=False)
                else:
                    git(self.root, "config", "user.email", value)
                self.refused(["withdraw", DA, "--reason", "dup"], EMAIL_MSG)
                self.assertEqual(self.rec(DA)["status"], "open")

    def test_find_in_force_default_and_all(self):  # G1: a superseded and a withdrawn record match the term
        self.put(dec(DA, effect="lasting", landed_in=["CLAUDE.md"], question="Widget rule?"),
                 dec(DB, effect="lasting", landed_in=["CLAUDE.md"], supersedes=DA, question="Gizmo rule?"),
                 dec(DC, "withdrawn", question="Widget again?"))
        code, out, _ = self.cli("find", "widget")
        self.assertEqual((code, out), (0, "%s [] Gizmo rule? -> Yes\n" % DB))
        code, out, _ = self.cli("find", "widget", "--all")
        self.assertEqual(out, "%s [] Widget rule? -> Yes\n%s [] Widget again? -> (withdrawn)\n" % (DA, DC))

    def test_gates_pass_after_ask_and_decide(self):
        new, _ = self.ask(extra=["--topic", "ids"])
        self.assertEqual(self.cli("decide", new, "--answer", "Yes")[0], 0)
        self.assertTrue(gate_decisions.check(["--root", self.root]).ok())
        self.assertTrue(gate_schema.check(["--root", self.root]).ok())


# ---------------------------------------------------------------- A: argv and dispatch

class Argv(Base):
    def test_A1_dispatcher(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            self.assertEqual(gates_main.main(["decisions"] + ask_argv() + ["--root", self.root]), 0)
        self.assertEqual(ids.id_problem(out.getvalue().strip(), "DEC"), "")
        self.assertIn("decisions", gates_main.COMMANDS)
        for argv in ([], ["frob"], ["-h"]):
            with self.subTest(argv=argv):
                err = io.StringIO()
                with contextlib.redirect_stderr(err):
                    self.assertEqual(decisions_cli.main(argv), 2)
                self.assertEqual(err.getvalue(), "usage: python3 -m gates decisions <sub> [args]\n"
                                                 "subcommands: ask, decide, find, withdraw\n")

    def test_A1_subprocess(self):
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        p = subprocess.run([sys.executable, "-m", "gates", "decisions", "find", "--root", self.root], cwd=REPO,
                           env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual((p.stdout, p.stderr, p.returncode), (b"", b"", 0))

    def test_A2_argv_none_reads_sys_argv(self):
        with mock.patch.object(sys, "argv", ["x", "find", "--root", self.root]):
            self.assertEqual(decisions_cli.main(None), 0)

    def test_A3_help(self):
        for sub in ("ask", "decide", "withdraw", "find"):
            for flag in ("-h", "--help"):
                with self.subTest(sub=sub, flag=flag):
                    self.usage([sub, flag])

    def test_A4_unknown_flag_and_extra_positional(self):
        self.put(dec(DA, "open"))
        self.usage(ask_argv(extra=["--bogus", "x"]))
        self.usage(["withdraw", DA, "extra", "--reason", "r"])
        self.usage(["decide", DA, "--answer", "a", "--bogus"])

    def test_A5_value_starting_with_dash(self):
        self.put(dec(DA, "open"))
        self.usage(ask_argv(question="-x"))
        self.usage(["decide", DA, "--answer", "--"])
        self.assertEqual(self.cli("withdraw", DA, "--reason", "-")[0], 0)  # "-" alone is text (probe, both)
        self.assertEqual(self.rec(DA)["withdrawn"]["reason"], "-")
        new, _ = self.ask(question="-1")
        self.assertEqual(self.rec(new)["question"], "-1")

    def test_A6_equals_form_passes_leading_dash(self):
        code, out, err = self.cli("ask", "--class", "scope", "--question=-x", "--option=a::b", "--option", "c::d",
                                  "--effect", "one-off", "--by", "w")
        self.assertEqual(code, 0, err)
        r = self.rec(out.strip())
        self.assertEqual((r["question"], r["options"][0]), ("-x", {"label": "a", "cost": "b"}))

    def test_A7_abbreviations(self):
        code, out, err = self.cli("ask", "--cl", "scope", "--quest", "q", "--opt=a::b", "--opt", "c::d", "--eff",
                                  "one-off", "--by", "w")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.rec(out.strip())["question"], "q")
        self.assertIn("ambiguous option", self.usage(ask_argv(extra=["--p", "x"])))

    def test_A8_single_value_flag_repeated(self):
        self.put(dec(DA, "open"))
        cases = {"--class": "scope", "--question": "q", "--effect": "one-off", "--supersedes": DA, "--by": "w",
                 "--plan": "p", "--program": "x", "--stream": "y", "--root": self.root}
        for flag, v in cases.items():
            for form in ([flag, v], [flag + "=" + v], [flag[:-1], v]):
                with self.subTest(flag=flag, form=form):
                    self.assertIn("given more than once", self.usage(ask_argv(extra=[flag, v] + form)))
        for argv in (["decide", DA, "--answer", "a", "--answer", "b"], ["decide", DA, "--answer", "a", "--rule", "r",
                     "--rule=s"], ["withdraw", DA, "--reason", "a", "--reas", "b"],
                     ["find", "--path", "a", "--path", "b"], ["find", "--topic", "a", "--topic=b"]):
            with self.subTest(argv=argv):
                self.assertIn("given more than once", self.usage(argv))

    def test_A9_duplicate_repeatable_values_refused(self):  # D-10
        self.refused(ask_argv(options=("yes::a", "yes::b")), "--option label: yes given twice")
        self.refused(ask_argv(extra=["--topic", "ids", "--topic", "ids"]), "--topic: ids given twice")
        self.refused(ask_argv(extra=["--applies-to", "a/*", "--applies-to", "a/*"]), "--applies-to: a/* given twice")
        self.put(dec(DA, "open", effect="lasting"))
        self.refused(["decide", DA, "--answer", "a", "--landed-in", "CLAUDE.md", "--landed-in", "CLAUDE.md"],
                     "--landed-in: CLAUDE.md given twice")

    def test_A10_required_flag_missing(self):
        full = ask_argv()
        for flag in ("--class", "--question", "--option", "--effect", "--by"):
            argv = []
            i = 0
            while i < len(full):
                if full[i] == flag:
                    i += 2
                    continue
                argv.append(full[i])
                i += 1
            with self.subTest(flag=flag):
                self.assertIn("required", self.usage(argv))
        self.usage(["decide", "--answer", "a"])
        self.usage(["decide", DA])
        self.usage(["withdraw", "--reason", "r"])
        self.usage(["withdraw", DA])

    def test_A11_empty_values_refused(self):
        self.put(dec(DA, "open"))
        cases = [(ask_argv(cls=""), "--class: must not be empty"),
                 (ask_argv(question=""), "--question: must not be empty"),
                 (ask_argv(by=""), "--by: must not be empty"),
                 (ask_argv(effect=""), "--effect: must be lasting or one-off"),
                 (ask_argv(options=("::", "a::b")), "--option label: must not be empty"),
                 (ask_argv(extra=["--topic", ""]), "--topic: must match"),
                 (ask_argv(extra=["--applies-to", ""]), "--applies-to: must not be empty"),
                 (ask_argv(extra=["--supersedes", ""]), "--supersedes: id does not match the form"),
                 (ask_argv(cls="merge-grant", extra=["--plan", ""]), "--plan: must match"),
                 (ask_argv(cls="merge-grant", extra=["--plan", "p", "--program", "", "--stream", "s"]),
                  "--program: must match"),
                 (["decide", DA, "--answer", ""], "--answer: must not be empty"),
                 (["decide", DA, "--answer", "a", "--rule", ""], "--rule: must not be empty"),
                 (["decide", DA, "--answer", "a", "--landed-in", ""], "--landed-in: must not be empty"),
                 (["decide", "", "--answer", "a"], "ID: id does not match the form"),
                 (["withdraw", DA, "--reason", ""], "--reason: must not be empty"),
                 (["find", ""], "TERM: must not be empty"), (["find", "--path", ""], "--path: must not be empty"),
                 (["find", "--topic", ""], "--topic: must match")]
        for argv, needle in cases:
            with self.subTest(argv=argv):
                self.refused(argv, needle)
        self.refused(["find", "--root", ""], TOP, root=False)

    def test_A12_find_without_terms(self):
        self.put(dec(DA, effect="lasting", landed_in=["CLAUDE.md"], topics=["ids"], applies_to=["gates/*.py"]),
                 dec(DB, effect="lasting", landed_in=["CLAUDE.md"]), dec(DC, "open", topics=["ids"]))
        self.assertEqual(self.cli("find")[1], "%s [ids] Keep X? -> Yes\n%s [] Keep X? -> Yes\n" % (DA, DB))
        self.assertEqual(self.cli("find", "--topic", "ids")[1], "%s [ids] Keep X? -> Yes\n" % DA)
        self.assertEqual(self.cli("find", "--path", "gates/x.py")[1], "%s [ids] Keep X? -> Yes\n" % DA)


# ---------------------------------------------------------------- B: root, config, git

class RootConfigGit(Base):
    def test_B1_root_from_cwd(self):
        cwd = os.getcwd()
        self.addCleanup(os.chdir, cwd)
        os.chdir(self.root)
        code, out, err = self.cli(*ask_argv(), root=False)
        self.assertEqual(code, 0, err)
        self.assertIn(out.strip(), self.recs())

    def test_B2_B3_B4_bad_roots(self):
        plain = os.path.join(self.tmp, "plain")
        os.mkdir(plain)
        sub = os.path.join(self.root, "sub")
        os.mkdir(sub)
        for path, needle in ((os.path.join(self.tmp, "nonexistent"), E128 + "; run /strict-delivery:init"),
                             (plain, E128 + "; run /strict-delivery:init"), (sub, TOP)):
            for argv in (ask_argv(), ["decide", DA, "--answer", "a"], ["withdraw", DA, "--reason", "r"], ["find"]):
                with self.subTest(path=path, sub=argv[0]):
                    self.refused(argv + ["--root", path], needle, root=False)

    def test_B5_B6_config_missing_or_invalid(self):
        git(self.root, "rm", "-q", "--cached", ".strict-delivery/config.yml")
        os.replace(os.path.join(self.root, ".strict-delivery/config.yml"), os.path.join(self.tmp, "cfg"))
        self.refused(ask_argv(), ".strict-delivery/config.yml: missing; run /strict-delivery:init")
        write_record(self.root, ".strict-delivery/config.yml", {**minimal_config(), "bogus": 1})
        self.refused(["find"], "unknown key 'bogus'")
        write_record(self.root, ".strict-delivery/config.yml", {**minimal_config(), "ids": {"decision": "dec"}})
        self.refused(ask_argv(), "ids.decision: must be a prefix of capital letters A-Z")

    def test_B7_custom_prefix(self):
        write_record(self.root, ".strict-delivery/config.yml", {**minimal_config(), "ids": {"decision": "ADR"}})
        new, _ = self.ask()
        self.assertEqual(ids.id_problem(new, "ADR"), "")
        self.refused(["decide", DA, "--answer", "a"], "ID: id does not match the form; expected ADR-")

    def test_B8_class_list(self):
        self.refused(ask_argv(cls="bogus"), "class: bogus is not in decision_classes.owner_only")
        write_record(self.root, ".strict-delivery/config.yml",
                     {**minimal_config(), "decision_classes": {"owner_only": ["house-rule"]}})
        new, _ = self.ask(cls="house-rule")
        self.assertEqual(self.rec(new)["class"], "house-rule")
        self.ask(cls="triage")  # a default class stays

    def test_B9_unborn_head(self):
        bare = os.path.join(self.tmp, "unborn")
        os.mkdir(bare)
        git(bare, "init", "-q", "-b", "main")
        git(bare, "config", "user.email", "fixture@example.invalid")
        write_record(bare, ".strict-delivery/config.yml", minimal_config())
        write_record(bare, "%s/%s.yml" % (DEC, DA), dec(DA, "open"))
        self.root = bare
        self.refused(ask_argv(), "git rev-parse HEAD failed (exit 128)")
        self.refused(["decide", DA, "--answer", "a"], "git rev-parse HEAD failed (exit 128)")
        self.refused(["withdraw", DA, "--reason", "r"], "git rev-parse HEAD failed (exit 128)")
        self.assertEqual(self.cli("find", "--all"), (0, "%s [] Keep X? -> (open)\n" % DA, ""))

    def test_B11_git_not_found(self):
        with mock.patch.dict(os.environ, {"PATH": self.tmp}):
            for argv in (ask_argv(), ["find"]):
                with self.subTest(sub=argv[0]):
                    self.refused(argv, "decisions %s: git not found on PATH; install git\n" % argv[0])

    def test_B12_caller_git_env_cleared(self):
        other = os.path.join(self.tmp, "other")
        os.mkdir(other)
        make_repo(other)
        with mock.patch.dict(os.environ, {"GIT_DIR": os.path.join(other, ".git"), "GIT_WORK_TREE": other}):
            new, _ = self.ask()
        self.assertIn(new, self.recs())
        self.assertFalse(os.path.exists(os.path.join(other, DEC)))


# ---------------------------------------------------------------- C: ask fields

class AskFields(Base):
    def test_C2_C3_C4_option_forms(self):
        for opt, needle in (("a", "expected LABEL::COST with exactly one ::"), ("a::b::c", "exactly one ::"),
                            ("a::::b", "exactly one ::"), ("a:::b", "exactly one ::"),
                            ("::b", "--option label: must not be empty"), ("a::", "--option cost: must not be empty"),
                            (" ::b", "--option label: must not start or end with a space"),
                            ("a:: b", "--option cost: must not start or end with a space"),
                            ("a\nb::c", "--option label: U+000A is not allowed")):
            with self.subTest(opt=opt):
                self.refused(ask_argv(options=(opt, "x::y")), needle)
        new, _ = self.ask(options=("a::b", "c::d", "e: f::g h"))
        self.assertEqual(self.rec(new)["options"],
                         [{"label": "a", "cost": "b"}, {"label": "c", "cost": "d"}, {"label": "e: f", "cost": "g h"}])

    def test_C6_effect(self):
        for v in ("Lasting", "other", "lasting "):
            with self.subTest(v=v):
                self.refused(ask_argv(effect=v), "--effect: must be lasting or one-off")
        new, _ = self.ask(effect="lasting")
        self.assertEqual(self.rec(new)["effect"], "lasting")

    def test_C9_C10_grant_field_values(self):
        g = ["--plan", "p"]
        for extra, needle in ((g + ["--program", "x"], "program: stream must be given too"),
                              (g + ["--stream", "y"], "stream: program must be given too"),
                              (["--program", "x", "--stream", "y"], "plan"),
                              (g + ["--program", "x", "--stream", "integration"], "'integration' is reserved"),
                              (g + ["--program", "X", "--stream", "y"], "--program: must match [a-z0-9][a-z0-9-]*"),
                              (g + ["--program", "x", "--stream", "y_z"], "--stream: must match"),
                              (["--plan", "a/b"], "--plan: must match [a-z0-9][a-z0-9._-]*"),
                              (["--plan", "a b"], "--plan: must match"), (["--plan", "-p"], "usage")):
            with self.subTest(extra=extra):
                if needle == "usage":
                    self.usage(ask_argv(cls="merge-grant", extra=extra))
                else:
                    self.refused(ask_argv(cls="merge-grant", extra=extra), needle)
        self.refused(ask_argv(extra=["--program", "x", "--stream", "y"]), "program: must be absent unless class is")
        new, _ = self.ask(cls="merge-grant", extra=["--plan", "p.v2_x-1", "--program", "x", "--stream", "y"])
        r = self.rec(new)
        self.assertEqual((r["plan"], r["program"], r["stream"]), ("p.v2_x-1", "x", "y"))

    def test_C11_to_C16_supersedes(self):
        self.put(dec(DA), dec(DB, "open"), dec(DC, "withdrawn"), dec(DD), dec(DE, "open", supersedes=DD),
                 dec(DF), dec(DG, "withdrawn", supersedes=DF))
        self.refused(ask_argv(extra=["--supersedes", MISSING]), "supersedes: %s has no record" % MISSING)
        for bad in ("DEC-1", FA, "x", "DEC-20261399-a2b3"):
            with self.subTest(bad=bad):
                self.refused(ask_argv(extra=["--supersedes", bad]), "--supersedes: id ")
        self.refused(ask_argv(extra=["--supersedes", DB]), "supersedes: %s is not answered" % DB)
        self.refused(ask_argv(extra=["--supersedes", DC]), "supersedes: %s is not answered" % DC)
        self.refused(ask_argv(extra=["--supersedes", DD]), "supersedes: %s is already superseded by %s" % (DD, DE))
        new, _ = self.ask(extra=["--supersedes", DF])  # C16: only a withdrawn superseder
        self.assertEqual(self.rec(new)["supersedes"], DF)
        new2, _ = self.ask(extra=["--supersedes", DA])
        self.assertEqual(self.rec(new2)["supersedes"], DA)
        self.refused(ask_argv(extra=["--supersedes", DA]), "already superseded by %s" % new2)  # an open one now
        self.assertTrue(gate_decisions.check(["--root", self.root]).ok())

    def test_C18_by(self):
        new, _ = self.ask(by="stream a controller")
        self.assertEqual(self.rec(new)["asked_by"], "stream a controller")
        self.refused(ask_argv(by="a\nb"), "--by: U+000A is not allowed")


# ---------------------------------------------------------------- D: candidates

class Candidates(Base):
    def cands(self, out):
        return [ln.split(" ")[1].rstrip(":") for ln in out.splitlines() if ln.startswith("candidate ")]

    def test_D1_topic(self):
        self.put(dec(DA, topics=["Ids"]), dec(DB, topics=["idsx"]), dec(DC, "open", topics=["ids"]))
        new, out = self.ask(question="Zzz?", extra=["--topic", "ids"])
        self.assertEqual(self.cands(out), [DA, DC])  # D13: an open record is a candidate too
        self.assertEqual(self.rec(new)["checked_against"], [DA, DC])

    def test_D2_to_D6_globs(self):
        self.put(dec(DA, applies_to=["gates/*.py"]), dec(DB, applies_to=["gates/lib/x.py"]),
                 dec(DC, applies_to=["docs/*"]), dec(DD, applies_to=["["]), dec(DE, applies_to=["gates/**"]), dec(DF, applies_to=["a[b]"]))
        cases = (("gates/*.py", [DA, DB, DE]), ("gates/lib/x.py", [DA, DB, DE]), ("gates/x", [DE]),
                 ("[", [DD]), ("docs/a", [DC]), ("zzz", []), ("a[b]", [DF]), ("ab", [DF]))
        for g, want in cases:
            with self.subTest(g=g):
                _, out = self.ask(question="Zzz?", extra=["--applies-to", g])
                self.assertEqual([c for c in self.cands(out) if c in (DA, DB, DC, DD, DE, DF)], want)

    def test_D7_glob_hit_replaced_by_current_topic_hit_not(self):  # D-11
        self.put(dec(DA, applies_to=["gates/*"], topics=["t"]), dec(DB, supersedes=DA))
        _, out = self.ask(question="Zzz?", extra=["--applies-to", "gates/x"])
        self.assertEqual(self.cands(out), [DB])
        _, out = self.ask(question="Zzz?", extra=["--topic", "t"])
        self.assertEqual(self.cands(out), [DA])

    def test_D8_fork_refused(self):
        self.put(dec(DA, applies_to=["gates/*"]), dec(DB, supersedes=DA), dec(DC, supersedes=DA))
        self.refused(ask_argv(question="Zzz?", extra=["--applies-to", "gates/x"]), "fork.%s" % DA)

    def test_D9_question_words(self):
        self.put(dec(DA, question="the prefix"), dec(DB, answer="RULE book"), dec(DC, question="ids are fine"),
                 dec(DD, question="abcde"), dec(DE, question="abc"))
        _, out = self.ask(question="Ids: the prefix-rule! ABCDE abc")
        self.assertEqual(self.cands(out), [DA, DB, DD])

    def test_D10_D11_non_ascii_question_refused_same_on_both(self):  # Q-D30C2-1 skeleton; D-3
        for q, cp in (("Rule Ⱟ here", "U+2C2F"), ("Rule ࡰ", "U+0870"), ("Rule \U00010570", "U+10570"),
                      ("Straße", "U+00DF"), ("ﬁle", "U+FB01")):
            with self.subTest(cp=cp):
                err = self.refused(ask_argv(question=q), "")
                self.assertEqual(err, "decisions ask: --question: %s is not allowed; the text must be printable "
                                      "ASCII (U+0020-U+007E), with line breaks (U+000A)\n" % cp)

    def test_D12_union_once_in_id_order(self):
        self.put(dec(DC, topics=["t"], applies_to=["a/*"], question="widget"), dec(DA, question="widget"))
        _, out = self.ask(question="widget?", extra=["--topic", "t", "--applies-to", "a/b"])
        self.assertEqual(self.cands(out), [DA, DC])

    def test_D14_no_candidates(self):
        self.put(dec(DA, question="xyz"))
        new, out = self.ask(question="Zzz?")
        self.assertEqual(out, new + "\n")
        self.assertEqual(self.rec(new)["checked_against"], [])

    def test_D16_malformed_register_refused(self):
        self.put(dec(DA, status="closed"))
        self.refused(ask_argv(), DEC + "/" + DA + ".yml: status")
        self.refused(["find"], DEC + "/" + DA + ".yml: status")  # G9: schema-invalid, loadable
        os.replace(os.path.join(self.root, DEC, DA + ".yml"), os.path.join(self.tmp, "x"))
        with open(os.path.join(self.root, DEC, "junk.txt"), "w") as fh:
            fh.write("x")
        self.refused(ask_argv(), "not a regular file named <id>.yml")
        os.replace(os.path.join(self.root, DEC, "junk.txt"), os.path.join(self.tmp, "y"))
        with open(os.path.join(self.root, DEC, DA + ".yml"), "w") as fh:
            fh.write("- a\n")
        self.refused(ask_argv(), "the top level must be a mapping")
        self.refused(["find"], "the top level must be a mapping")  # G9


# ---------------------------------------------------------------- E: mint, write, output

class MintWrite(Base):
    def test_E2_mint_collision_redraws(self):
        today = ids.utc_today().strftime("%Y%m%d")
        taken = "DEC-%s-a2b3" % today
        self.put(dec(taken))
        write_record(self.root, "%s/%s.yml" % (FIN, "F-%s-c4d5" % today), fnd("F-%s-c4d5" % today))

        class Seq(random.Random):
            def __init__(self, chars):
                super().__init__(0)
                self.chars = list(chars)

            def choice(self, seq):
                return self.chars.pop(0)

        with mock.patch.object(decisions_cli, "_rng", Seq("a2b3" + "e6f7")):
            new, _ = self.ask()
        self.assertEqual(new, "DEC-%s-e6f7" % today)
        self.assertIsInstance(decisions_cli._rng, random.SystemRandom)

    def test_E3_existing_includes_finding_ids(self):
        today = ids.utc_today().strftime("%Y%m%d")
        cfg = {**minimal_config(), "ids": {"decision": "DEC", "finding": "F"}}
        write_record(self.root, ".strict-delivery/config.yml", cfg)
        seen = {}

        def spy(prefix, existing, day, rng):
            seen["existing"] = set(existing)
            return "DEC-%s-k3f9" % today

        write_record(self.root, "%s/%s.yml" % (FIN, FA), fnd(FA))
        self.put(dec(DA))
        with mock.patch.object(decisions_cli.ids, "mint", spy):
            self.ask()
        self.assertEqual(seen["existing"], {DA, FA})

    def test_E4_no_free_id(self):
        today = ids.utc_today().strftime("%Y%m%d")
        self.put(dec("DEC-%s-a2b3" % today))
        with mock.patch.object(ids, "_SUFFIX_COUNT", 1):
            self.refused(ask_argv(), "no free id")

    def test_E7_register_directory_created(self):
        self.assertFalse(os.path.exists(os.path.join(self.root, DEC)))
        new, _ = self.ask()
        self.assertTrue(os.path.isfile(os.path.join(self.root, DEC, new + ".yml")))
        self.assertTrue(os.path.isfile(os.path.join(self.root, DEC, "index.yml")))  # regenerated

    def test_E8_register_symlink_or_file(self):
        os.makedirs(os.path.join(self.root, ".strict-delivery/state"), exist_ok=True)
        os.mkdir(os.path.join(self.tmp, "elsewhere"))
        os.symlink(os.path.join(self.tmp, "elsewhere"), os.path.join(self.root, DEC))
        self.refused(ask_argv(), "is a symlink; register paths must be real directories")
        os.replace(os.path.join(self.root, DEC), os.path.join(self.tmp, "moved-link"))
        with open(os.path.join(self.root, DEC), "w") as fh:
            fh.write("x")
        self.refused(ask_argv(), "is not a directory")

    def test_E9_F12_read_only_register(self):
        self.put(dec(DA, "open"))
        d = os.path.join(self.root, DEC)
        os.chmod(d, 0o555)
        self.addCleanup(os.chmod, d, 0o755)
        self.refused(ask_argv(), "cannot create (")
        self.refused(["decide", DA, "--answer", "a"], "cannot write (")
        self.refused(["withdraw", DA, "--reason", "r"], "cannot write (")
        self.assertEqual(sorted(os.listdir(d)), [DA + ".yml"])

    def test_E10_F13_regenerate_failure_after_write(self):
        self.put(dec(DA, "open"), dec(DB, "open"))
        os.mkdir(os.path.join(self.root, DEC, "index.yml"))
        code, out, err = self.cli(*ask_argv())
        new = out.splitlines()[-1]
        self.assertEqual(code, 1)
        self.assertEqual(err, "decisions ask: %s written; indexes not regenerated: %s/index.yml: is a directory; "
                              "run python3 -m gates index\n" % (new, DEC))
        self.assertEqual(self.rec(new)["status"], "open")
        code, out, err = self.cli("decide", DA, "--answer", "a")
        self.assertEqual((code, out), (1, DA + "\n"))
        self.assertTrue(err.startswith("decisions decide: %s written; indexes not regenerated: " % DA))
        self.assertEqual(self.rec(DA)["status"], "answered")
        code, out, err = self.cli("withdraw", DB, "--reason", "r")
        self.assertEqual((code, out), (1, DB + "\n"))
        self.assertEqual(self.rec(DB)["status"], "withdrawn")

    def test_E12_E13_candidate_line_escaping(self):  # D-8
        self.put(dec(DA, topics=["t"], question="first\nsecond"), dec(DB, topics=["t"], question="café\tx"))
        _, out = self.ask(extra=["--topic", "t"])
        self.assertEqual(out.splitlines()[:2], ["candidate %s: first\\nsecond" % DA, "candidate %s: café\\tx" % DB])

    def test_E6_validate_before_write(self):  # every validate error: nothing written (I2)
        self.refused(ask_argv(cls="merge-grant"), "plan")


# ---------------------------------------------------------------- F: decide and withdraw

class DecideWithdraw(Base):
    def test_F1_F2_missing_and_malformed_id(self):
        for sub, extra in (("decide", ["--answer", "a"]), ("withdraw", ["--reason", "r"])):
            with self.subTest(sub=sub):
                self.refused([sub, MISSING] + extra, MISSING + ": no such decision")
                for bad in ("DEC-1", "../x", FA, "DEC-20261031-a2bé"):
                    self.refused([sub, bad] + extra, "ID: id does not match the form")

    def test_F4_F5_withdrawn_or_malformed_status(self):
        self.put(dec(DA, "withdrawn"), {**dec(DB, "open"), "status": "closed"}, dec(DC))
        for rid in (DA, DB, DC):
            for sub, extra in (("decide", ["--answer", "a"]), ("withdraw", ["--reason", "r"])):
                with self.subTest(rid=rid, sub=sub):
                    self.refused([sub, rid] + extra, rid + " is not open")

    def test_F7_rule_forms(self):
        self.put(dec(DA, "open"))
        self.refused(["decide", DA, "--answer", "a", "--rule", "two\nlines"], "--rule: U+000A is not allowed")
        self.refused(["decide", DA, "--answer", "a", "--rule", "x\ry"], "--rule: U+000D")

    def test_F8_landed_in_forms(self):
        self.put(dec(DA, "open", effect="lasting"), dec(DB, "open"), commit=True)
        os.makedirs(os.path.join(self.root, ".strict-delivery/playbooks/sub"))
        os.makedirs(os.path.join(self.root, "docs"))
        files = {"CLAUDE.md": DA + "\n", ".strict-delivery/playbooks/p.md": "no id\n",
                 ".strict-delivery/playbooks/bad.md": None, "docs/other.md": DA + "\n"}
        for rel, text in files.items():
            with open(os.path.join(self.root, rel), "wb") as fh:
                fh.write(b"\xff" + DA.encode() if text is None else text.encode())
        os.symlink(os.path.join(self.root, ".strict-delivery/playbooks"), os.path.join(self.root, "lnk"))
        commit_all(self.root, "files")
        with open(os.path.join(self.root, ".strict-delivery/playbooks/new.md"), "w") as fh:
            fh.write(DA)
        cases = (("docs/other.md", "is not a playbook, CLAUDE.md or architecture.md"),
                 (".strict-delivery/playbooks/new.md", "is not a tracked regular file"),
                 (".strict-delivery/playbooks/p.md", "does not contain the decision id " + DA),
                 (".strict-delivery/playbooks/bad.md", "not valid UTF-8"),
                 ("../CLAUDE.md", "normalised repo-relative path"),
                 ("/CLAUDE.md", "normalised repo-relative path"),
                 ("CLAUDE.md#", "normalised repo-relative path"),
                 ("CLAUDE.mdé", "--landed-in: U+00E9 is not allowed"),
                 (" CLAUDE.md", "--landed-in: must not start or end with a space"))
        for cite, needle in cases:
            with self.subTest(cite=cite):
                self.refused(["decide", DA, "--answer", "a", "--landed-in", cite], needle)
        self.refused(["decide", DB, "--answer", "a", "--landed-in", "CLAUDE.md"], "landed_in")  # one-off
        code, out, err = self.cli("decide", DA, "--answer", "a", "--landed-in", "CLAUDE.md#Some heading",
                                  "--landed-in", "CLAUDE.md")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.rec(DA)["landed_in"], ["CLAUDE.md#Some heading", "CLAUDE.md"])

    def test_F8_symlinked_parent(self):
        self.put(dec(DA, "open", effect="lasting"))
        os.makedirs(os.path.join(self.root, "real"))
        with open(os.path.join(self.root, "real", "p.md"), "w") as fh:
            fh.write(DA)
        os.makedirs(os.path.join(self.root, ".strict-delivery"), exist_ok=True)
        os.symlink(os.path.join(self.root, "real"), os.path.join(self.root, ".strict-delivery/playbooks"))
        commit_all(self.root, "link")
        self.refused(["decide", DA, "--answer", "a", "--landed-in", ".strict-delivery/playbooks/p.md"],
                     "is not a tracked regular file")

    def test_F11_reason_multiline(self):
        self.put(dec(DA, "open"))
        self.assertEqual(self.cli("withdraw", DA, "--reason", "asked twice\nsee the other")[0], 0)
        self.assertEqual(self.rec(DA)["withdrawn"]["reason"], "asked twice\nsee the other")
        self.put(dec(DB, "open"))
        self.assertEqual(self.cli("decide", DB, "--answer", "line one\nline two")[0], 0)
        self.assertEqual(self.rec(DB)["answer"], "line one\nline two")

    def test_F14_check_order(self):  # D-16: status before email; email before text
        self.put(dec(DA), dec(DB, "open"))
        git(self.root, "config", "--unset", "user.email")
        self.refused(["decide", DA, "--answer", ""], DA + " is not open")
        self.refused(["decide", DB, "--answer", ""], EMAIL_MSG)
        self.refused(["withdraw", DB, "--reason", ""], EMAIL_MSG)

    def test_D7_new_row_validated_before_render(self):  # the updated row's own errors, not the index's file form
        self.put(dec(DA, "open", **{"class": "bogus"}))
        for argv in (["withdraw", DA, "--reason", "r"], ["decide", DA, "--answer", "a"]):
            with self.subTest(sub=argv[0]):
                err = self.refused(argv, "")
                self.assertEqual(err, "decisions %s: class: bogus is not in decision_classes.owner_only\n" % argv[0])

    def test_F15_record_file_symlink(self):
        os.makedirs(os.path.join(self.root, DEC))
        write_record(self.root, "x/" + DA + ".yml", dec(DA, "open"))
        os.symlink(os.path.join(self.root, "x", DA + ".yml"), os.path.join(self.root, DEC, DA + ".yml"))
        self.refused(["decide", DA, "--answer", "a"], "not a regular file named <id>.yml")

    def test_D16_email_non_ascii_refused(self):
        self.put(dec(DA, "open"))
        git(self.root, "config", "user.email", "café@example.invalid")
        self.refused(["decide", DA, "--answer", "a"], "user.email: U+00E9 is outside U+0020-U+007E")
        self.refused(["withdraw", DA, "--reason", "r"], "user.email: U+00E9 is outside U+0020-U+007E")

    def test_D7_render_refusal_before_decide_write(self):  # a bad other record blocks the write
        self.put(dec(DA, "open"), dec(DB, status="bogus"))
        self.refused(["decide", DA, "--answer", "a"], DB + ".yml: status")
        self.refused(["withdraw", DA, "--reason", "r"], DB + ".yml: status")

    def test_D15_bad_finding_record_blocks_ask(self):
        write_record(self.root, "%s/%s.yml" % (FIN, FA), {**fnd(FA), "severity": "BAD"})
        self.refused(ask_argv(), FA + ".yml: severity")


# ---------------------------------------------------------------- G: find

class Find(Base):
    def test_G2_G3_G4_G5_G7(self):
        self.put(dec(DA, effect="lasting", landed_in=["CLAUDE.md"], topics=["ids", "zz-top"], applies_to=["gates/*"],
                     question="Prefix rule?", answer="Keep it"),
                 dec(DB, effect="lasting", landed_in=["CLAUDE.md"], question="Other?"))
        line = "%s [ids, zz-top] Prefix rule? -> Keep it\n" % DA
        self.assertEqual(self.cli("find", "PREFIX", "keep"), (0, line, ""))
        self.assertEqual(self.cli("find", "--path", "gates/x.py")[1], line)
        self.assertEqual(self.cli("find", "--path", "docs/x")[1], "")
        self.assertEqual(self.cli("find", "--topic", "ids")[1], line)
        self.assertEqual(self.cli("find", "nothing"), (0, "", ""))
        self.assertEqual(self.cli("find", "other")[1], "%s [] Other? -> Yes\n" % DB)

    def test_G6_G8_open_and_multiline(self):
        self.put(dec(DA, "open", question="a\nb"), dec(DB, answer="x\ny", question="q"))
        self.assertEqual(self.cli("find", "--all")[1], "%s [] a\\nb -> (open)\n%s [] q -> x\\ny\n" % (DA, DB))

    def test_G10_non_ascii_term_refused_same_on_both(self):  # Q-D30C2-1 skeleton; D-3
        for term, cp in (("Ⱟ", "U+2C2F"), ("x\U00010570", "U+10570")):
            with self.subTest(cp=cp):
                err = self.refused(["find", term], "")
                self.assertEqual(err, "decisions find: TERM: %s is not allowed; the text must be printable ASCII "
                                      "(U+0020-U+007E)\n" % cp)
        self.refused(["find", "--topic", "Ids"], "--topic: must match [a-z0-9][a-z0-9-]*")
        self.refused(["find", "--path", "/a"], "--path: must be repo-relative")
        self.refused(["find", "--path", "a/../b"], "--path: must not hold a .. segment")
        self.refused(["find", "--path", "a b"], "--path: U+0020 is not allowed")


# ---------------------------------------------------------------- H: open grammars, I: produces and resources

class Grammars(Base):
    def test_H7_H8_glob_and_topic_whitelists(self):
        for extra, needle in ((["--applies-to", "/a"], "--applies-to: must be repo-relative"),
                              (["--applies-to", "../a"], "--applies-to: must not hold a .. segment"),
                              (["--applies-to", "aé"], "--applies-to: U+00E9"),
                              (["--topic", "Ids"], "--topic: must match"), (["--topic", "-x"], "usage"),
                              (["--topic", "a_b"], "--topic: must match"), (["--topic", "é"], "--topic: must")):
            with self.subTest(extra=extra):
                if needle == "usage":
                    self.usage(ask_argv(extra=extra))
                else:
                    self.refused(ask_argv(extra=extra), needle)

    def test_H10_free_text_whitelist(self):
        self.put(dec(DA, "open"))
        for argv, needle in ((ask_argv(question="a\tb"), "--question: U+0009"),
                             (ask_argv(question="a\rb"), "--question: U+000D"),
                             (ask_argv(question="a\x7fb"), "--question: U+007F"),
                             (ask_argv(question=" a"), "--question: must not start or end"),
                             (ask_argv(question="a\n"), "--question: must not start or end"),
                             (ask_argv(cls="scöpe"), "--class: U+00F6"),
                             (ask_argv(by="wé"), "--by: U+00E9"),
                             (ask_argv(options=("a::b\u0085", "c::d")), "--option cost: U+0085"),
                             (["decide", DA, "--answer", "é"], "--answer: U+00E9"),
                             (["withdraw", DA, "--reason", "r\x00"], "--reason: U+0000")):
            with self.subTest(argv=argv):
                self.refused(argv, needle)
        new, _ = self.ask(question="Ids: a \"quoted\" # 'x' - [y] {z} & * ! | > % @ `\nline two")
        self.assertEqual(self.rec(new)["question"], "Ids: a \"quoted\" # 'x' - [y] {z} & * ! | > % @ `\nline two")

    def test_H12_numeric_text(self):  # Q-D30C2-1 skeleton: no int() of argv text
        for n in (4300, 4301):
            with self.subTest(n=n):
                new, _ = self.ask(question="9" * n)
                self.assertEqual(self.rec(new)["question"], "9" * n)
                self.assertEqual(self.cli("decide", new, "--answer", "9" * n), (0, new + "\n", ""))
                self.assertEqual(self.rec(new)["answer"], "9" * n)
                self.assertEqual(self.cli("find", "9" * n, "--all")[1],
                                 "%s [] %s -> %s\n" % (new, "9" * n, "9" * n))

    def test_H13_H14_no_unicode_data_no_int_no_exception_group(self):  # D-5, Q-D30C2-1 skeleton
        path = os.path.join(REPO, "gates", "tools", "decisions_cli.py")
        with open(path, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        banned_attr = {"lower", "upper", "casefold", "isalnum", "isalpha", "isdigit", "isdecimal", "isnumeric",
                       "isspace", "isprintable", "isidentifier", "islower", "isupper", "istitle", "title",
                       "swapcase", "capitalize", "strip", "lstrip", "rstrip", "splitlines"}
        found = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in banned_attr:
                found.append(node.attr)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "split" \
                    and not node.args:
                found.append("split()")  # split with no separator splits on Unicode whitespace
            if isinstance(node, ast.Name) and node.id in ("BaseExceptionGroup", "ExceptionGroup"):
                found.append(node.id)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "int":
                found.append("int()")
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                found.extend(a.name for a in node.names if a.name == "unicodedata")
                if isinstance(node, ast.ImportFrom) and node.module == "unicodedata":
                    found.append("unicodedata")
            if isinstance(node, ast.Constant) and type(node.value) is str:
                found.extend(e for e in ("\\d", "\\w", "\\s", "\\D", "\\W", "\\S", "\\b") if e in node.value)
        self.assertEqual(found, [])

    def test_I1_produces(self):
        self.assertEqual(decisions_cli.PRODUCES, ("decision",))
        self.assertIn("gates.tools.decisions_cli", producers.PRODUCER_MODULES)

    def test_I3_keyboard_interrupt_propagates(self):
        with mock.patch.object(decisions_cli.gitinfo, "head_sha", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.cli(*ask_argv())


if __name__ == "__main__":
    unittest.main()
