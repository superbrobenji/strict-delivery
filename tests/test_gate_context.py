"""Task 5a.3: ``gates/gate_context.py`` and ``context.enforced`` (plan 5245-5309; domain table 5a.3 with its binding
controller decisions D-Q1 (b) (``enforced`` raises ``ValueError`` outside the three profiles), D-Q2 (a) (only
``PASS context.reads``), PD1-PD11). Expected values are written by hand: shas by git's blob rule, lines from the plan.
A comment ``# XX1`` names the domain-table row a test covers."""
import ast
import contextlib
import hashlib
import io
import json
import os
import socket
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

from gates import gate_context, gate_schema, producers, run_all
from gates.lib import config, context, dispatch, receipts, schema
from gates.lib.result import GateError, ParseEntryRefused, run_gate, safe_text
from gates.tools import context_cli
from tests.helpers import GitIsolatedTestCase, INT_LIMITS, commit_all, git, int_limit, make_repo, minimal_config, write_record

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
S = "3f2b8c1e-9d4a-4b7e-8f10-2a6c5d9e0b13"
HDR = "schema: receipt/1\nreads:\n"
KINDS_TEXT = "plan, program, program-controller, stream-block, sync, or stream-<id>-block"
SESSION_TEXT = "session: must be 1 to 128 characters, A-Z a-z 0-9 _ -, starting with a letter or a digit"
PLAN_HANDOFF = ".strict-delivery/state/plans/p/handoff.md"
ROOT_USAGE = "FAIL context.input: "
HANDOFF = ("---\nschema: handoff/1\nplan: p\nspec:\n  - s.md\nbranch: b\nhead: aaaaaaa\nbase: bbbbbbb\nledger: l.md\n"
           "resume: r\nblock: b\nnext_task: t\nfindings_in_flight: []\nopen_decisions: []\nrulings: 0\ngrant: null\n"
           "live_subagents: []\nrole: controller\nbudget:\n  tokens: 1\n  minutes: 1\nworktrees:\n  - path: w\n"
           "    branch: b\n    head: aaaaaaa\n    porcelain: \"\"\nskills:\n  - s\nledger_from: 2\nbatch_cut: null\n"
           "questions: []\n%s---\nbody\n")
ROLES = dispatch.ROLES


def SHA(b):
    return hashlib.sha1(b"blob %d\0" % len(b) + b).hexdigest()


def ROW(p, s):
    return "  - path: %s\n    sha: %s\n" % (p, s)


def source(path, mode="r"):
    """The text (or bytes, mode ``rb``) of a file; a repository-relative path is read from the working tree."""
    full = path if os.path.isabs(path) else os.path.join(REPO, path)
    with open(full, mode, **({"encoding": "utf-8"} if "b" not in mode else {})) as fh:
        return fh.read()


def E(p, **kw):
    d = {"path": p, "why": "w " + p}
    d.update(kw)
    return d


NEW = SHA(b"x\n")
OLD = SHA(b"old\n")


class Base(GitIsolatedTestCase):
    def setUp(self):
        super().setUp()
        self.fx = make_repo(self.work)
        self.real = os.path.realpath(self.fx)
        self.put("docs/x.md", b"x\n")
        self.ctx(kinds={"plan": [E("docs/x.md")]})
        self.rd = self.fx + "/.strict-delivery/receipts"
        self.A = self.real + "/docs/x.md"

    def put(self, rel, data=b"x\n"):
        path = os.path.join(self.fx, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(data)
        return path

    def ctx(self, **kw):
        write_record(self.fx, ".strict-delivery/context.yml", {"schema": "context/1", **kw})

    def profile(self, p):
        write_record(self.fx, ".strict-delivery/config.yml", dict(minimal_config(), profile=p))

    def receipt(self, text, session=S):
        os.makedirs(self.rd, exist_ok=True)
        data = text if type(text) is bytes else text.encode("utf-8")
        with open(self.rd + "/" + session + ".yml", "wb") as fh:
            fh.write(data)

    def rows(self, *pairs, session=S):
        self.receipt(HDR + "".join(ROW(p, s) for p, s in pairs), session)

    def read_a(self):
        self.rows((self.A, NEW))

    def args(self, *extra, kind="plan"):
        return ["--session", S, "--kind", kind, "--root", self.fx] + list(extra)

    def run_g(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = gate_context.main(argv)
        return out.getvalue(), code

    def go(self, *extra, kind="plan"):
        return self.run_g(self.args(*extra, kind=kind))

    def sub(self, argv, env=None, cwd=None, mod="gates.gate_context"):
        e = dict(os.environ, PYTHONPATH=REPO, PYTHONDONTWRITEBYTECODE="1", LC_ALL="C")
        e.update(env or {})
        p = subprocess.run([sys.executable, "-m", mod] + list(argv), cwd=cwd or self.tmp, env=e,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
        return p.stdout.decode("utf-8"), p.returncode

    def fail_a(self, why="not read in this session"):
        return "FAIL context.read.%s: %s\n" % (self.A, why)

    def one_input(self, argv, reason=None, prefix=None):
        out, code = self.run_g(argv)
        self.assertEqual(code, 1)
        self.assertEqual(out.count("\n"), 1, out)
        self.assertTrue(out.startswith(ROOT_USAGE), out)
        if reason is not None:
            self.assertEqual(out, ROOT_USAGE + reason + "\n")
        if prefix is not None:
            self.assertTrue(out.startswith(ROOT_USAGE + prefix), out)
        return out


# ------------------------------------------------------------------------------------------ context.enforced

class Enforced(Base):
    CFG = {"profile": "strict", "paths": {}}

    def test_enforced_only_on_strict(self):  # EN1 EN2 EN3
        got = [context.enforced({**self.CFG, "profile": p}) for p in ("light", "standard", "strict")]
        self.assertEqual(got, [False, False, True])
        self.assertTrue(all(type(g) is bool for g in got))

    def test_enforced_follows_loaded_profile(self):  # EN4
        got = []
        for p in ("light", "standard", "strict"):
            self.profile(p)
            got.append(context.enforced(config.load(self.fx)))
        self.assertEqual(got, [False, False, True])

    def test_config_refuses_other_profiles(self):  # EN5
        for bad in ("Strict", "STRICT", " strict", "strict\n", "", 3, True, ["strict"], None):
            with self.subTest(profile=bad):
                write_record(self.fx, ".strict-delivery/config.yml", dict(minimal_config(), profile=bad))
                with self.assertRaises(GateError) as cm:
                    config.load(self.fx)
                self.assertIn("profile: must be one of light, standard, strict", str(cm.exception))

    def test_enforced_missing_profile(self):  # EN6 (D-Q1 b)
        for cfg in ({}, {"paths": {}}):
            with self.subTest(cfg=cfg), self.assertRaises(ValueError):
                context.enforced(cfg)

    def test_enforced_ill_typed_profile(self):  # EN7 (D-Q1 b)
        class Sub(str):
            pass

        for bad in (None, 3, True, ["strict"], {"strict": 1}, b"strict", "", "Strict", "strict ", "strict\0", Sub("strict")):
            with self.subTest(profile=bad), self.assertRaises(ValueError):
                context.enforced({"profile": bad})

    def test_enforced_non_dict_cfg(self):  # EN8 (D-Q1 b)
        class D(dict):
            pass

        for bad in (None, [], "strict", D(profile="strict")):
            with self.subTest(cfg=bad), self.assertRaises(ValueError):
                context.enforced(bad)

    def test_enforced_reads_only_profile(self):  # EN9
        self.assertIs(context.enforced({"profile": "light", "context": {"enforced": True}, "enforced": True}), False)

    def test_enforced_pure(self):  # EN10
        cfg = {"profile": "strict", "paths": {"a": "b"}}
        before = json.dumps(cfg, sort_keys=True)
        boom = mock.Mock(side_effect=AssertionError("io"))
        with mock.patch("builtins.open", boom), mock.patch("os.stat", boom), mock.patch("subprocess.run", boom):
            self.assertIs(context.enforced(cfg), True)
        self.assertEqual(json.dumps(cfg, sort_keys=True), before)

    def test_context_module_names_additive(self):  # EN11
        names = sorted(n for n in dir(context) if not n.startswith("_") and callable(getattr(context, n))
                       and getattr(getattr(context, n), "__module__", "") == "gates.lib.context")
        self.assertEqual(names, sorted([
            "absolute", "context_errors", "enforced", "handoff_reads", "kind_of", "load", "needs", "parse_lines",
            "required", "resolve", "split", "values_for"]))


# ------------------------------------------------------------------------------------------ producer

class Producer(Base):
    def test_gate_context_produces_context(self):  # PR1
        self.assertEqual(gate_context.PRODUCES, ("context",))
        self.assertIs(type(gate_context.PRODUCES), tuple)
        self.assertTrue(all(type(x) is str for x in gate_context.PRODUCES))

    def test_producer_registry_unchanged_before_rq_5_2(self):  # PR2
        self.assertEqual(producers.PRODUCER_MODULES, (
            "gates.tools.index", "gates.tools.decisions_cli", "gates.tools.findings_cli", "gates.tools.claims_cli",
            "gates.gate_checkpoint", "gates.tools.program_cli"))

    def schema_out(self, root, modules=None):
        out = io.StringIO()
        patch = mock.patch("gates.producers.PRODUCER_MODULES", modules) if modules is not None else contextlib.nullcontext()
        with patch, contextlib.redirect_stdout(out):
            code = run_gate("schema", gate_schema.check, ["--root", root])
        return out.getvalue(), code

    def test_check_schema_unchanged_before_registration(self):  # PR3
        out, code = self.schema_out(REPO)
        self.assertEqual(code, 0, out)
        self.assertEqual(out.count("\n"), 15)
        self.assertNotIn("schema.context", out)

    def test_repository_passes_with_context_declared(self):  # PR4
        out, code = self.schema_out(REPO, producers.PRODUCER_MODULES + ("gates.gate_context",))
        self.assertEqual(code, 0, out)
        lines = out.splitlines()
        self.assertEqual(len(lines), 16)
        self.assertEqual(lines.index("PASS schema.context"), lines.index("PASS schema.streams") + 1)
        self.assertEqual(lines[lines.index("PASS schema.context") + 1], "PASS schema.status")

    def test_producer_makes_context_yml_required(self):  # PR5 PR6
        os.remove(self.fx + "/.strict-delivery/context.yml")  # test's own fixture file
        out, code = self.schema_out(self.fx)
        self.assertEqual(code, 0, out)
        self.assertNotIn("schema.context", out)  # PR6: before the patch
        out, code = self.schema_out(self.fx, producers.PRODUCER_MODULES + ("gates.gate_context",))
        self.assertIn("FAIL schema.context..strict-delivery/context.yml: missing\n", out)
        self.assertEqual(code, 1)

    def test_producer_valid_context_file_passes(self):  # PR7
        write_record(self.fx, ".strict-delivery/context.yml", {"schema": "context/1"})
        out, code = self.schema_out(self.fx, producers.PRODUCER_MODULES + ("gates.gate_context",))
        self.assertIn("PASS schema.context\n", out)
        self.assertEqual(code, 0, out)

    def test_producer_invalid_context_file_fails(self):  # PR8
        for row in ({"schema": "context/1", "bogus": 1}, {"schema": "context/1", "every": "x"}, {"schema": "context/9"}):
            with self.subTest(row=row):
                write_record(self.fx, ".strict-delivery/context.yml", row)
                out, code = self.schema_out(self.fx, producers.PRODUCER_MODULES + ("gates.gate_context",))
                self.assertEqual(code, 1)
                self.assertIn("FAIL schema.context..strict-delivery/context.yml: ", out)

    def test_check_schema_does_not_run_context_errors(self):  # PR9
        write_record(self.fx, ".strict-delivery/context.yml", {"schema": "context/1", "every": [
            {"path": "../x", "why": "w"}, {"path": "a.md", "why": "w"}, {"path": "a.md", "why": "w2"}]})
        out, code = self.schema_out(self.fx, producers.PRODUCER_MODULES + ("gates.gate_context",))
        self.assertIn("PASS schema.context\n", out)
        self.assertEqual(code, 0)
        self.assertEqual(self.go()[0].startswith(ROOT_USAGE + ".strict-delivery/context.yml: "), True)

    def test_import_has_no_side_effect(self):  # PR10
        script = os.path.join(self.tmp, "imp.py")
        with open(script, "w") as fh:
            fh.write("import os, sys\nbefore = (os.getcwd(), dict(os.environ), list(sys.argv))\n"
                     "import gates.gate_context\nprint(before == (os.getcwd(), dict(os.environ), list(sys.argv)))\n")
        p = subprocess.run([sys.executable, script], cwd=self.tmp, env=dict(os.environ, PYTHONPATH=REPO,
                           PYTHONDONTWRITEBYTECODE="1"), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual((p.stdout, p.stderr, p.returncode), (b"True\n", b"", 0))
        with mock.patch("gates.producers.PRODUCER_MODULES", ("gates.gate_context",)):
            self.assertIn("context", schema.produced_kinds())

    def test_receipts_not_declared(self):  # PR11
        with mock.patch("gates.producers.PRODUCER_MODULES", producers.PRODUCER_MODULES + ("gates.gate_context",)):
            self.assertNotIn("receipt", schema.produced_kinds())
        out, _ = self.schema_out(self.fx, producers.PRODUCER_MODULES + ("gates.gate_context",))
        self.assertNotIn("schema.receipt", out)

    def run_all_out(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = run_all.main(["--root", self.fx])
        return out.getvalue(), code

    def test_truncated_receipt_unchecked_by_schema_input_fail_in_gate(self):  # PR12 RC16
        self.receipt(HDR + "  - path: /x\n    sha: abc")
        out, code = self.schema_out(self.fx)
        self.assertEqual(code, 0, out)
        self.assertNotIn("receipt", out)
        out, code = self.run_all_out()
        self.assertNotIn("receipts", out)
        self.assertNotIn("FAIL run_all", out)
        out, code = self.go()
        self.assertEqual(code, 1)
        self.assertEqual(out, ROOT_USAGE + ".strict-delivery/receipts/%s.yml: reads.0.sha: must be 7 to 40 lowercase hex digits; "
                         "delete it to start the session's receipts again\n" % S)

    def test_symlinked_receipts_dir_unchecked_by_schema_input_fail_in_gate(self):  # PR13 RC22
        real = os.path.join(self.tmp, "realrec")
        os.mkdir(real)
        with open(real + "/" + S + ".yml", "w") as fh:
            fh.write(HDR + ROW(self.A, NEW))
        os.symlink(real, self.rd)
        out, code = self.schema_out(self.fx)
        self.assertEqual(code, 0, out)
        out, code = self.run_all_out()
        self.assertNotIn("receipts", out)
        out, code = self.go()
        self.assertEqual((out, code), (ROOT_USAGE + ".strict-delivery/receipts: is a symlink; directories must be real "
                                       "directories\n", 1))

    def test_context_in_no_run_all_list(self):  # PR14 PF5
        for gates in run_all.PROFILE_GATES.values():
            self.assertNotIn("context", gates)
        out, _ = self.run_all_out()
        self.assertNotIn("context.", out)


# ------------------------------------------------------------------------------------------ arguments

class Args(Base):
    def test_all_read_passes(self):  # AR1
        self.read_a()
        self.assertEqual(self.go(), ("PASS context.reads\n", 0))

    def test_missing_required_flags_fail_input(self):  # AR2 AR3 AR4
        self.one_input(["--kind", "plan", "--root", self.fx], "--session KEY is required")
        self.one_input(["--session", S, "--root", self.fx], "--kind KIND is required")
        self.one_input(["--root", self.fx], "--session KEY is required")

    def test_empty_flags_fail_input(self):  # AR5 AR6
        self.one_input(["--session", "", "--kind", "plan", "--root", self.fx], SESSION_TEXT)
        self.one_input(["--session=", "--kind", "plan", "--root", self.fx], SESSION_TEXT)
        self.one_input(["--session", S, "--kind", "", "--root", self.fx], "unknown kind ; the kinds are " + KINDS_TEXT)

    def test_repeated_flags_fail_input(self):  # AR7 M33
        for flag, v in (("--session", S), ("--kind", "plan"), ("--role", "drafter"), ("--plan", "p"), ("--program", "p"),
                        ("--stream", "s"), ("--brief", "b"), ("--handoff", "h.md"), ("--root", self.fx)):
            for second in (v, "other"):
                with self.subTest(flag=flag, second=second):
                    argv = self.args() + [flag, v, flag, second]
                    out = self.one_input(argv, "invalid arguments: %s given more than once" % flag)
                    self.assertNotIn("PASS", out)

    def test_session_key_class(self):  # AR8 AR9
        keys = ["../x", "a/b", "a\\b", ".", "..", "-a", "_a", "a b", "A\n", "a\0b", "a" * 128, "a" * 129, "é", "K",
                "9" * 4300, "9" * 4301]
        for key in keys:
            with self.subTest(key=key[:20]):
                out, code = self.run_g(["--session=" + key, "--kind", "plan", "--root", self.fx])
                problem = receipts.session_problem(key)
                if key == "a" * 128:
                    self.assertEqual(problem, "")
                    self.assertEqual(out, self.fail_a())
                else:
                    self.assertEqual(problem, SESSION_TEXT)
                    self.assertEqual((out, code), (ROOT_USAGE + SESSION_TEXT + "\n", 1))
                    if len(key) > 5:
                        self.assertNotIn(key, out)
        self.assertFalse(os.path.exists(self.rd))

    def test_session_uses_session_problem(self):  # AR9 M7
        with mock.patch("gates.lib.receipts.session_problem", return_value="session: patched") as m:
            out, code = self.go()
        self.assertEqual(out, ROOT_USAGE + "session: patched\n")
        m.assert_called()

    def test_dash_values(self):  # AR10
        self.one_input(["--session", "-x", "--kind", "plan", "--root", self.fx],
                       "invalid arguments: argument --session: expected one argument")
        self.one_input(["--session", "--kind", "plan", "--root", self.fx],
                       "invalid arguments: argument --session: expected one argument")
        self.one_input(["--session=-x", "--kind", "plan", "--root", self.fx], SESSION_TEXT)

    def test_unknown_kind_fails_input(self):  # AR11
        for k in ("nope", "Plan", "PLAN", "plan ", " plan", "stream-A-block", "stream-a", "stream--block", "stream-docs",
                  "a" * 4301, "a\0b"):
            with self.subTest(kind=k[:12]):
                self.one_input(["--session", S, "--kind", k, "--root", self.fx],
                               safe_text("unknown kind %s; the kinds are %s" % (safe_text(k), KINDS_TEXT)))

    def test_known_kinds_accepted(self):  # AR12
        self.ctx(kinds={"stream-block": [E("{stream}/x.md")], "plan": [E("docs/x.md")]})
        self.read_a()
        for kind in ("plan", "program", "program-controller", "stream-block", "sync"):
            with self.subTest(kind=kind):
                out, code = self.go(kind=kind)
                self.assertNotIn("context.input", out)
        self.assertEqual(self.go(kind="stream-docs-block"), ("PASS context.reads\n", 0))  # {stream} = docs

    def test_unknown_role_fails_input(self):  # AR13 PD11 M34
        # R1-4: the value is escaped once, by Result.render (spec section 13); the rendered forms are written by hand
        # from the safe_text rules: a backslash doubles, a newline is a backslash and n, NUL is backslash x00.
        for r, shown in (("nobody", "nobody"), ("Task_Reviewer", "Task_Reviewer"), ("TASK_REVIEWER", "TASK_REVIEWER"),
                         ("", ""), (" drafter", " drafter"), ("drafter\n", "drafter\\n"), ("x" * 4301, "x" * 4301),
                         ("a\\b", "a\\\\b"), ("a\0b", "a\\x00b"), ("a\x1bb", "a\\x1bb"), ("a\tb", "a\\tb")):
            with self.subTest(role=r[:10]):
                self.one_input(self.args("--role", r),
                               "--role: unknown role %s; the roles are %s" % (shown, ", ".join(ROLES)))

    def test_each_role_selects_its_list(self):  # AR14
        self.ctx(roles={"drafter": [E("docs/x.md")]})
        self.assertEqual(len(ROLES), 15)
        for r in ROLES:
            with self.subTest(role=r):
                out, code = self.go("--role", r)
                self.assertNotIn("context.input", out)
        self.assertEqual(self.go("--role", "drafter"), (self.fail_a(), 1))
        self.assertEqual(self.go(), ("PASS context.reads\n", 0))
        self.assertEqual(self.go("--role", "investigator")[1], 0)  # a role with no list adds nothing

    def test_json_first_position(self):  # AR15
        self.read_a()
        out, code = self.run_g(["--json"] + self.args())
        self.assertEqual((out, code), ('{"gate": "context", "ok": true, "lines": [{"status": "PASS", "id": "context.reads", '
                                       '"reason": ""}]}\n', 0))

    def test_json_later_is_unrecognized(self):  # AR16 M32
        self.one_input(["--session", S, "--json", "--kind", "plan", "--root", self.fx],
                       "invalid arguments: unrecognized arguments: --json")
        self.one_input(self.args("--json"), "invalid arguments: unrecognized arguments: --json")

    def test_json_failing_lines(self):  # AR17
        out, code = self.run_g(["--json"] + self.args())
        self.assertEqual(code, 1)
        d = json.loads(out)
        self.assertEqual(d, {"gate": "context", "ok": False, "lines": [
            {"status": "FAIL", "id": "context.read." + self.A, "reason": "not read in this session"}]})

    def test_root_not_a_repo(self):  # AR18
        plain = os.path.join(self.tmp, "plain")
        os.mkdir(plain)
        afile = os.path.join(self.tmp, "afile")
        open(afile, "w").close()
        link = os.path.join(self.tmp, "plink")
        os.symlink(plain, link)
        for root in (plain, os.path.join(self.tmp, "missing"), afile, link):
            with self.subTest(root=os.path.basename(root)):
                out, code = self.run_g(["--session", S, "--kind", "plan", "--root", root])
                self.assertEqual(code, 1)
                self.assertEqual(out.count("\n"), 1)
                self.assertTrue(out.startswith(ROOT_USAGE) and out.endswith("; run /strict-delivery:init\n"), out)

    def test_git_missing_has_no_init_hint(self):  # AR18 R1-1; spec section 13, Q-1a2r-6
        plain = os.path.join(self.tmp, "plain")
        os.mkdir(plain)
        nogit = {"PATH": os.path.join(self.tmp, "no-such-dir")}
        argv = ["--session", S, "--kind", "plan", "--root", self.fx]
        self.assertEqual(self.sub(argv, env=nogit), ("FAIL context.input: git not found on PATH; install git\n", 1))
        # contrast: git present and the root is not a repository -> the init hint
        out, code = self.sub(["--session", S, "--kind", "plan", "--root", plain])
        self.assertEqual(code, 1)
        self.assertTrue(out.startswith(ROOT_USAGE) and out.endswith("; run /strict-delivery:init\n"), out)
        self.assertNotIn("git not found", out)

    def test_root_forms(self):  # AR19
        self.read_a()
        link = os.path.join(self.tmp, "rlink")
        os.symlink(self.fx, link)
        self.assertEqual(self.run_g(["--session", S, "--kind", "plan", "--root", link]), ("PASS context.reads\n", 0))
        old = os.getcwd()
        self.addCleanup(os.chdir, old)
        os.chdir(self.tmp)
        self.assertEqual(self.run_g(["--session", S, "--kind", "plan", "--root", "work"]), ("PASS context.reads\n", 0))
        out, code = self.run_g(["--session", S, "--kind", "plan", "--root", self.fx + "/docs"])
        self.assertEqual((out, code), (ROOT_USAGE + "git rev-parse --show-toplevel: root must be the repository top level\n", 1))
        self.one_input(["--session", S, "--kind", "plan", "--root", ""], "--root: must not be empty")

    def test_root_default_forms(self):  # AR20
        self.read_a()
        old = os.getcwd()
        self.addCleanup(os.chdir, old)
        os.chdir(self.fx)
        argv = ["--session", S, "--kind", "plan"]
        self.assertEqual(self.run_g(argv), ("PASS context.reads\n", 0))
        with mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": self.fx}):
            self.assertEqual(self.run_g(argv), ("PASS context.reads\n", 0))
        with mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": os.path.join(self.tmp, "nodir")}):
            self.one_input(argv, "CLAUDE_PROJECT_DIR is not a directory")
        with mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": ""}):
            self.assertEqual(self.run_g(argv), ("PASS context.reads\n", 0))
        plain = os.path.join(self.tmp, "plain")
        os.mkdir(plain)
        os.chdir(plain)
        out = self.one_input(argv)
        self.assertTrue(out.endswith("; run /strict-delivery:init\n"), out)

    def test_flag_forms_and_help(self):  # AR21 VN5
        self.read_a()
        self.one_input(self.args("--bogus"), "invalid arguments: unrecognized arguments: --bogus")
        self.one_input(self.args("plan"), "invalid arguments: unrecognized arguments: plan")
        self.assertEqual(self.run_g(["--sess", S, "--ki", "plan", "--root", self.fx]), ("PASS context.reads\n", 0))
        self.assertEqual(self.run_g(["--session=" + S, "--kind", "plan", "--root", self.fx]), ("PASS context.reads\n", 0))
        self.one_input(self.args("--ro", "x"), "invalid arguments: ambiguous option: --ro could match --root, --role")
        self.one_input(["-h"], "help requested; no gate was run")
        self.one_input(["--session"], "invalid arguments: argument --session: expected one argument")

    def test_argv_types(self):  # AR22
        self.read_a()
        self.assertEqual(self.run_g(tuple(self.args())), ("PASS context.reads\n", 0))
        old = sys.argv
        self.addCleanup(setattr, sys, "argv", old)
        sys.argv = ["x"] + self.args()
        self.assertEqual(self.run_g(None), ("PASS context.reads\n", 0))
        for bad in (["--session", 3], [b"--session"]):
            with self.subTest(bad=bad):
                out, code = self.run_g(bad)
                self.assertEqual(code, 1)
                self.assertTrue(out.startswith(ROOT_USAGE + "ParseEntryRefused: parse_args with an object of type list"), out)
        for bad in ("x", None, tuple(self.args())):
            with self.subTest(check=bad), self.assertRaises(ParseEntryRefused):
                gate_context.check(bad)

    def test_very_long_values(self):  # AR23
        self.ctx(kinds={"program": [E("{plan}/x.md")]}, roles={"drafter": [E("{brief}")]})
        for plan in ("a" * 4301, "9" * 4301):
            with self.subTest(plan=plan[:3]):
                out, code = self.go("--plan", plan, kind="program")
                self.assertTrue(out.startswith("FAIL context.file." + self.real + "/" + plan[:5]), out[:80])
                self.assertEqual(code, 1)
        brief_msg = "--brief: must be one line of printable text of at most 4096 characters"
        self.one_input(self.args("--role", "drafter", "--brief", "b" * 4097, kind="program"), brief_msg)
        out, code = self.go("--role", "drafter", "--brief", "b" * 4096, kind="program")
        self.assertNotIn("context.input", out)
        self.one_input(self.args("--handoff", "h" * 5000))
        self.one_input(self.args("--program", "a" * 4301))
        self.assertNotIn("context.input", self.go("--stream", "a" * 4301)[0])  # a valid name, only a placeholder text

    def test_root_unencodable_or_nul(self):  # AR24 VN4
        for root in ("/tmp/x\udc80", self.fx + "\0"):
            with self.subTest(root=repr(root)[-8:]):
                out, code = self.run_g(["--session", S, "--kind", "plan", "--root", root])
                self.assertEqual(code, 1)
                self.assertEqual(out.count("\n"), 1)
                self.assertTrue(out.startswith(ROOT_USAGE + "git rev-parse --show-toplevel"), out)
                self.assertTrue(out.endswith("; run /strict-delivery:init\n"), out)

    def test_stream_flag_disagrees_with_kind(self):  # AR25
        self.ctx(kinds={"stream-block": [E("docs/x.md")]})
        self.read_a()
        self.assertEqual(self.go("--stream", "docs", kind="stream-docs-block"), ("PASS context.reads\n", 0))
        self.one_input(self.args("--stream", "other", kind="stream-docs-block"),
                       "--stream other disagrees with the kind stream-docs-block")

    def test_flag_set_is_the_planned_one(self):  # AR26
        self.read_a()
        argv = ["--root", self.fx, "--session", S, "--kind", "plan", "--role", "drafter", "--plan", "p", "--program", "",
                "--stream", "", "--brief", "", "--handoff", ""]
        out, _ = self.run_g(argv)
        self.assertNotIn("invalid arguments", out)
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            gate_context.main(["-h"])
        for flag in ("--root", "--session", "--kind", "--role", "--plan", "--program", "--stream", "--brief", "--handoff"):
            self.assertIn(flag, err.getvalue())
        listed = {w.strip("[],") for w in err.getvalue().split() if w.strip("[],").startswith("--")}
        self.assertEqual(listed - {"--help"}, {"--root", "--session", "--kind", "--role", "--plan", "--program", "--stream",
                                               "--brief", "--handoff"})


# ------------------------------------------------------------------------------------------ input stage

class Inputs(Base):
    def test_missing_config_fails_input(self):  # IN1
        fresh = os.path.join(self.tmp, "fresh")
        os.mkdir(fresh)
        git(fresh, "init", "-q", "-b", "main")
        git(fresh, "config", "user.email", "f@example.invalid")
        git(fresh, "config", "user.name", "F")
        open(fresh + "/f", "w").close()
        git(fresh, "add", "-A")
        git(fresh, "commit", "-q", "-m", "c")
        self.one_input(["--session", S, "--kind", "plan", "--root", fresh],
                       ".strict-delivery/config.yml: missing; run /strict-delivery:init")

    def test_invalid_config_fails_input(self):  # IN2
        write_record(self.fx, ".strict-delivery/config.yml", dict(minimal_config(), bogus=1))
        self.one_input(self.args(), prefix="")
        write_record(self.fx, ".strict-delivery/config.yml", dict(minimal_config(), profile="Strict"))
        self.one_input(self.args(), prefix="")
        os.remove(self.fx + "/.strict-delivery/config.yml")
        os.mkdir(self.fx + "/.strict-delivery/config.yml")
        self.one_input(self.args(), prefix="")

    def test_missing_context_file_names_init(self):  # IN3
        os.remove(self.fx + "/.strict-delivery/context.yml")
        out, code = self.go()
        self.assertEqual((out, code), (ROOT_USAGE + ".strict-delivery/context.yml: missing; run /strict-delivery:init\n", 1))
        self.assertTrue(out.startswith("FAIL context.input:") and "/strict-delivery:init" in out)

    def test_context_file_states(self):  # IN4
        path = self.fx + "/.strict-delivery/context.yml"
        valid = "schema: context/1\n"
        other = os.path.join(self.tmp, "other.yml")
        with open(other, "w") as fh:
            fh.write(valid)

        def dir_():
            os.mkdir(path)

        def symlink():
            os.symlink(other, path)

        def dangling():
            os.symlink(os.path.join(self.tmp, "nowhere"), path)

        def fifo():
            os.mkfifo(path)

        def raw(data):
            def f():
                with open(path, "wb") as fh:
                    fh.write(data)
            return f

        def unreadable():
            raw(valid.encode())()
            os.chmod(path, 0)

        cases = [("dir", dir_), ("dangling", dangling), ("fifo", fifo), ("empty", raw(b"")),
                 ("badutf8", raw(b"\xff\xfe")), ("badyaml", raw(b"a: [\n")), ("v2", raw(b"schema: context/2\n"))]
        if os.geteuid() != 0:
            cases.append(("unreadable", unreadable))
        for name, make in cases:
            with self.subTest(case=name):
                if os.path.lexists(path):
                    if os.path.isdir(path) and not os.path.islink(path):
                        os.rmdir(path)
                    else:
                        os.chmod(path, 0o600) if not os.path.islink(path) else None
                        os.remove(path)
                make()
                out, code = self.go()
                self.assertEqual(code, 1)
                self.assertTrue(out.startswith(ROOT_USAGE + ".strict-delivery/context.yml"), out)
                self.assertEqual(out.count("\n"), 1)
        for name, data in (("bom", b"\xef\xbb\xbf" + valid.encode()), ("crlf", valid.replace("\n", "\r\n").encode())):
            with self.subTest(case=name):
                os.remove(path)
                raw(data)()
                self.assertEqual(self.go(), ("PASS context.reads\n", 0))

    def test_context_errors_fail_input(self):  # IN5
        rows = [{"every": [E("../x")]}, {"every": [E("{nope}/x")]}, {"every": [E("a.md"), E("a.md")]},
                {"every": [E("a.md", lines="0-3")]}, {"every": [E("a.md", lines="5-2")]},
                {"every": [E("a.md", lines="1-" + "9" * 601)]}, {"roles": {"nobody": [E("a.md")]}}, {"roles": {"drafter": "x"}}]
        for row in rows:
            with self.subTest(row=str(row)[:40]):
                self.ctx(**row)
                out = self.one_input(self.args(), prefix=".strict-delivery/context.yml: ")
                self.assertNotIn("PASS", out)

    def make_program(self, name="20261101-x"):
        commit_all(self.fx, "context")
        git(self.fx, "checkout", "-q", "-b", name + "/integration")
        base = ".strict-delivery/state/programs/" + name + "/"
        write_record(self.fx, base + "streams.yml", {"schema": "streams/1", "program": name, "plan": "p", "specs": [],
                                                      "worktrees": "../w", "streams": [], "shared": []})
        for f in ("status.md", "sync-log.md", "merged.md"):
            self.put(base + f, b"x\n")
        git(self.fx, "add", "-A")
        git(self.fx, "commit", "-q", "-m", "program")
        git(self.fx, "checkout", "-q", "main")

    def test_program_values(self):  # IN6
        self.ctx(kinds={"program": [E("{integration}/a/{program}.md")]})
        self.one_input(self.args("--program", "20261101-x", kind="program"), prefix="")  # no integration branch
        self.make_program()
        integration = os.path.realpath(os.path.join(self.fx, "..", "w")) + "/20261101-x/integration"
        top = os.path.realpath(self.fx)
        self.put("../w/20261101-x/integration/a/20261101-x.md")
        out, code = self.go("--program", "20261101-x", kind="program")
        self.assertEqual((out, code), ("FAIL context.read.%s/a/20261101-x.md: not read in this session\n" % integration, 1))
        for bad in ("A", "a" * 4301, "nobranch-y"):
            with self.subTest(program=bad[:6]):
                out = self.one_input(self.args("--program", bad, kind="program"))
                self.assertNotIn("ValueError", out)
        self.assertEqual(self.go("--program", "", kind="program")[0],
                         "FAIL context.unresolved.{integration}/a/{program}.md: needs {integration}\n")
        self.assertTrue(top)

    def test_value_refusals(self):  # IN7
        for v in ("../../x", "A", "a_b"):
            self.one_input(self.args("--plan", v), "--plan: must match [a-z0-9][a-z0-9-]*")
        for v in ("a\nb", "a\0b", "aⰯb"):
            self.one_input(self.args("--brief", v), "--brief: must be one line of printable text of at most 4096 characters")
        self.ctx(kinds={"plan": [E("{plan}/x.md")]})
        self.assertEqual(self.go("--plan", "")[0], "FAIL context.unresolved.{plan}/x.md: needs {plan}\n")

    def good_handoff(self, extra=""):
        self.put(PLAN_HANDOFF, (HANDOFF % extra).encode())

    def test_bad_handoff_fails_input(self):  # IN8 IN9
        self.put("docs/none/keep", b"")
        self.one_input(self.args("--handoff", "docs/none.md"), self.real + "/docs/none.md: missing")
        os.mkdir(self.fx + "/hd")
        self.one_input(self.args("--handoff", "hd"), self.real + "/hd: not a regular file")
        os.mkfifo(self.fx + "/hf")
        self.one_input(self.args("--handoff", "hf"), self.real + "/hf: not a regular file")
        os.symlink(self.fx + "/docs/x.md", self.fx + "/hl.md")
        self.one_input(self.args("--handoff", "hl.md"), prefix=self.real + "/hl.md: the handoff is a symbolic link")
        self.put("bad1.md", b"---\nschema: handoff/1\n---\n")
        self.one_input(self.args("--handoff", "bad1.md"), prefix=self.real + "/bad1.md: plan: required key is missing")
        self.put("bad2.md", (HANDOFF % "required_reads:\n  - path: ../x\n    why: w\n").encode())
        self.one_input(self.args("--handoff", "bad2.md"),
                       self.real + "/bad2.md: required_reads.0.path: path '../x' must not hold '..'")
        self.put("bad3.md", b"\xff\xfe")
        self.one_input(self.args("--handoff", "bad3.md"), prefix=self.real + "/bad3.md: ")
        self.put("bad4.md", b"no front matter\n")
        self.one_input(self.args("--handoff", "bad4.md"), prefix=self.real + "/bad4.md: front matter: first line must be '---'")
        # IN9: the default handoff resolves and its file is absent
        self.one_input(self.args("--plan", "p"), "%s/%s: missing" % (self.real, PLAN_HANDOFF))

    def test_default_handoff_absent_fails_input(self):  # IN9 contrast with the CLI
        out, code = self.go("--plan", "p")
        self.assertEqual((out, code), (ROOT_USAGE + "%s/%s: missing\n" % (self.real, PLAN_HANDOFF), 1))
        err, o = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(o), contextlib.redirect_stderr(err):
            c = context_cli.main(["plan", "--plan", "p", "--root", self.fx])
        self.assertEqual(c, 1)
        self.assertIn("missing %s/%s -- handoff of plan\n" % (self.real, PLAN_HANDOFF), o.getvalue())

    def test_default_handoff_unresolved_no_failure(self):  # IN10 M24
        self.ctx(kinds={"plan": [E("{plan}/x.md")]})
        self.assertEqual(self.go(), ("FAIL context.unresolved.{plan}/x.md: needs {plan}\n", 1))

    def test_no_default_handoff_for_program_kinds(self):  # IN11
        self.good_handoff("required_reads:\n  - path: docs/x.md\n    why: w\n")
        self.ctx()
        for kind in ("program", "program-controller", "sync"):
            with self.subTest(kind=kind):
                self.assertEqual(self.go("--plan", "p", kind=kind), ("PASS context.reads\n", 0))
        self.put("h.md", (HANDOFF % "required_reads:\n  - path: docs/x.md\n    why: w\n").encode())
        self.assertEqual(self.go("--handoff", "h.md", kind="program"), (self.fail_a(), 1))

    def test_bad_handoff_cli_exit_2_gate_exit_1(self):  # IN12
        self.put("bad.md", b"---\nschema: handoff/1\n---\n")
        out, code = self.go("--handoff", "bad.md")
        err, o = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(o), contextlib.redirect_stderr(err):
            c = context_cli.main(["plan", "--handoff", "bad.md", "--root", self.fx])
        self.assertEqual((c, o.getvalue()), (2, ""))
        self.assertEqual(err.getvalue(), "context: " + out[len(ROOT_USAGE):])
        self.assertEqual(code, 1)

    def test_handoff_path_forms_match_cli(self):  # IN13 PD7 M26
        self.put("docs/h.md", (HANDOFF % "").encode())
        outside = os.path.join(self.tmp, "outside.md")
        with open(outside, "w") as fh:
            fh.write(HANDOFF % "")
        os.symlink(self.fx + "/docs/h.md", self.fx + "/docs/ln.md")
        outdir = os.path.join(self.tmp, "outdir")
        os.mkdir(outdir)
        with open(outdir + "/h.md", "w") as fh:
            fh.write(HANDOFF % "")
        os.symlink(outdir, self.fx + "/outlink")
        forms = ["docs/h.md", self.fx + "/docs/h.md", "../x", "{plan}", "", ".", "docs//h.md", "docs/h\0.md", "docs/ln.md",
                 outside, "docs/../docs/h.md", "outlink/h.md"]
        for f in forms:
            with self.subTest(form=repr(f)):
                gate_out, gate_code = self.go("--handoff", f)
                err, o = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(o), contextlib.redirect_stderr(err):
                    c = context_cli.main(["plan", "--handoff", f, "--root", self.fx]) if "\0" not in f else 2
                gate_refused = gate_out.startswith(ROOT_USAGE)
                self.assertEqual(gate_refused, c == 2, (gate_out, c, err.getvalue()))
                self.assertEqual(gate_code, 1 if gate_refused or "FAIL" in gate_out else 0)
        rule = ROOT_USAGE + "--handoff: must be a normalised repo-relative path without placeholders\n"
        for f in ("../x", "/abs", "{plan}", "", ".", "docs//h.md", "docs/h\0.md"):
            self.assertEqual(self.go("--handoff", f), (rule, 1), f)
        self.assertEqual(self.go("--handoff", "outlink/h.md"),
                         (ROOT_USAGE + "%s/h.md: the handoff is outside this repository's tree\n" % outdir, 1))
        self.assertEqual(self.go("--handoff", "docs/h.md")[1], 1)  # docs/x.md not read; the handoff itself is fine
        self.assertNotIn("context.input", self.go("--handoff", "docs/h.md")[0])

    def test_handoff_in_sibling_with_common_name_prefix_is_outside(self):  # IN13 PD7 R1-2
        """``<tmp>/work-evil`` beside ``<tmp>/work``: the name has the tree's name as a prefix, and is outside it."""
        evil = os.path.join(self.tmp, "work-evil")
        os.makedirs(evil + "/sub")
        for rel in ("h.md", "sub/h.md"):
            with open(os.path.join(evil, rel), "w") as fh:
                fh.write(HANDOFF % "required_reads:\n  - path: docs/x.md\n    why: w\n")
        os.symlink(evil, self.fx + "/outlink")  # a symlinked directory inside the tree
        os.makedirs(self.fx + "/docs/deep")
        os.symlink(evil + "/sub", self.fx + "/docs/deep/lnk")  # a nested one
        os.makedirs(self.fx + "/.strict-delivery/state/plans")
        os.symlink(evil, self.fx + "/.strict-delivery/state/plans/p")  # the default handoff's directory
        outside = "FAIL context.input: %s: the handoff is outside this repository's tree\n"
        self.assertEqual(self.go("--handoff", "outlink/h.md"), (outside % (evil + "/h.md"), 1))
        self.assertEqual(self.go("--handoff", "outlink/sub/h.md"), (outside % (evil + "/sub/h.md"), 1))
        self.assertEqual(self.go("--handoff", "docs/deep/lnk/h.md"), (outside % (evil + "/sub/h.md"), 1))
        with open(evil + "/handoff.md", "w") as fh:
            fh.write(HANDOFF % "")
        self.assertEqual(self.go("--plan", "p"), (outside % (evil + "/handoff.md"), 1))
        # contrast: the same layout inside the tree is accepted (docs/x.md is unread: a read line, not an input line)
        self.put("in/h.md", (HANDOFF % "required_reads:\n  - path: docs/x.md\n    why: w\n").encode())
        self.assertEqual(self.go("--handoff", "in/h.md"), (self.fail_a(), 1))

    def test_handoff_path_grammar_one_value_per_form(self):  # IN13 PD7 R1-3
        rule = ROOT_USAGE + "--handoff: must be a normalised repo-relative path without placeholders\n"
        for name, v in (("lone open brace", "a{b.md"), ("lone close brace", "a}b.md"), ("NUL", "a\0b.md"),
                        ("dot-dot component", "x/../y.md"), ("dot-dot first", "../x.md"), ("leading slash", "/abs.md"),
                        ("non-normalised", "docs//h.md"), ("dot component", "docs/./h.md"), ("dot", "."),
                        ("empty", ""), ("trailing slash", "docs/")):
            with self.subTest(form=name):
                self.assertEqual(self.go("--handoff", v), (rule, 1))

    def test_handoff_resolved_against_root(self):  # IN14 M25
        self.put("docs/h.md", (HANDOFF % "required_reads:\n  - path: docs/x.md\n    why: w\n").encode())
        old = os.getcwd()
        self.addCleanup(os.chdir, old)
        os.chdir(self.tmp)
        self.assertEqual(self.go("--handoff", "docs/h.md"), (self.fail_a(), 1))

    def test_one_input_line_in_fixed_order(self):  # IN15 PD2
        self.one_input(["--session", "../x", "--kind", "nope", "--root", "/nonexistent"], SESSION_TEXT)

    def test_input_failure_is_one_line_code_1(self):  # IN16 M28
        before = sorted(os.listdir(self.fx))
        for argv in (["--root", self.fx], self.args("--role", "zz"), self.args("--plan", "A"), self.args("--handoff", "no")):
            out = self.one_input(argv)
            self.assertNotIn("PASS", out)
        self.assertEqual(sorted(os.listdir(self.fx)), before)
        self.assertFalse(os.path.exists(self.rd))

    def test_value_errors_have_clean_reason(self):  # IN17 M27 PD1
        for argv in (self.args("--plan", "A"), self.args("--role", "zz"), self.args(kind="zz"), self.args("--brief", "a\nb"),
                     self.args("--stream", "q", kind="stream-docs-block")):
            out = self.one_input(argv)
            self.assertNotIn("ValueError", out)

    def test_check_raises_gateerror_main_prints_input(self):  # IN18 PD8
        for argv in (["--root", self.fx], self.args("--role", "zz"), self.args("--plan", "A"), self.args(kind="zz")):
            with self.subTest(argv=argv[-2:]):
                with self.assertRaises(GateError) as cm:
                    gate_context.check(argv)
                self.assertEqual(self.run_g(argv), (ROOT_USAGE + str(cm.exception) + "\n", 1))
        self.read_a()
        res = gate_context.check(self.args())
        self.assertEqual([(l.status, l.id) for l in res.lines], [("PASS", "context.reads")])


# ------------------------------------------------------------------------------------------ receipts and files

class Receipts(Base):
    def test_missing_read_fails_naming_path(self):  # RC1
        self.assertEqual(self.go(), (self.fail_a(), 1))
        self.assertFalse(os.path.exists(self.rd))

    def test_other_session_receipts_do_not_count(self):  # RC2
        self.rows((self.A, NEW), session="other")
        self.assertEqual(self.go(), (self.fail_a(), 1))

    def test_one_matching_row_passes(self):  # RC3
        self.read_a()
        self.assertEqual(self.go(), ("PASS context.reads\n", 0))

    def test_matching_row_among_others(self):  # RC4
        self.rows(("/other/a", NEW), (self.A, NEW), ("/other/b", OLD))
        self.assertEqual(self.go(), ("PASS context.reads\n", 0))

    def test_reread_after_change_passes(self):  # RC5 M11
        self.rows((self.A, OLD), (self.A, NEW))
        self.assertEqual(self.go(), ("PASS context.reads\n", 0))

    def test_any_matching_row_even_if_not_newest(self):  # RC6 M11
        self.rows((self.A, NEW), (self.A, OLD))
        self.assertEqual(self.go(), ("PASS context.reads\n", 0))

    def test_stale_read_fails_with_both_shas(self):  # RC7
        self.rows((self.A, OLD))
        self.assertEqual(self.go(), (self.fail_a("read at %s, now %s: read it again" % (OLD, NEW)), 1))

    def test_stale_names_newest_row_sha(self):  # RC8 M15
        old2 = SHA(b"older\n")
        self.rows((self.A, OLD), (self.A, old2))
        self.assertEqual(self.go()[0], self.fail_a("read at %s, now %s: read it again" % (old2, NEW)))

    def test_same_content_other_path_does_not_count(self):  # RC9
        self.put("docs/b.md", b"x\n")
        self.rows((self.real + "/docs/b.md", NEW))
        self.assertEqual(self.go(), (self.fail_a(), 1))

    def test_symlink_path_matches_real_path_receipt(self):  # RC10 M13
        os.symlink(self.fx + "/docs/x.md", self.fx + "/docs/ln.md")
        self.ctx(kinds={"plan": [E("docs/ln.md")]})
        cfg = config.load(self.fx)
        receipts.record(self.fx, cfg, S, self.fx + "/docs/ln.md")
        with open(self.rd + "/" + S + ".yml", "rb") as fh:
            self.assertEqual(fh.read().decode(), HDR + ROW(self.A, NEW))
        self.assertEqual(self.go(), ("PASS context.reads\n", 0))

    def test_row_with_symlink_spelling_does_not_match(self):  # RC11
        os.symlink(self.fx + "/docs/x.md", self.fx + "/docs/ln.md")
        self.ctx(kinds={"plan": [E("docs/ln.md")]})
        self.rows((self.real + "/docs/ln.md", NEW))
        self.assertEqual(self.go(), (self.fail_a(), 1))

    def test_symlinked_directory_component(self):  # RC12
        os.symlink(self.fx + "/docs", self.fx + "/link")
        self.ctx(kinds={"plan": [E("link/x.md")]})
        self.assertEqual(self.go(), (self.fail_a(), 1))
        self.read_a()
        self.assertEqual(self.go(), ("PASS context.reads\n", 0))

    def test_nonnormal_row_paths_do_not_match(self):  # RC13
        for p in ("docs/x.md", self.real + "/docs/./x.md", self.real + "/docs/../docs/x.md"):
            with self.subTest(path=p):
                self.rows((p, NEW))
                self.assertEqual(self.go(), (self.fail_a(), 1))

    def test_case_spelling_follows_realpath(self):  # RC14
        self.put("docs/Case.md", b"c\n")
        if os.path.exists(self.fx + "/docs/cASE.md"):
            self.ctx(kinds={"plan": [E("docs/case.MD")]})
            want = "FAIL context.read.%s/docs/case.MD: " % self.real
            self.rows((self.real + "/docs/Case.md", SHA(b"c\n")))
            self.assertEqual(self.go(), (want + "not read in this session\n", 1))
            self.rows((self.real + "/docs/case.MD", SHA(b"c\n")))
            self.assertEqual(self.go(), ("PASS context.reads\n", 0))
        else:
            self.skipTest("the temp volume is case-sensitive: two spellings name two files there")

    def test_corrupt_receipt_fails_input(self):  # RC15
        remedy = "; delete it to start the session's receipts again\n"
        sha = "a" * 40
        cases = [(b"- a\n- b\n", None), (b"\xff\xfe", ".strict-delivery/receipts/%s.yml: not valid UTF-8" % S),
                 ("schema: receipt/2\nreads: []\n".encode(), None),
                 (("schema: receipt/1\nreads:\n  - path: /x\n    sha: %s\n    extra: 1\n" % sha).encode(), None),
                 (HDR.encode() + ROW("/x", "A" * 40).encode(), None), (HDR.encode() + ROW("/x", "abcdef0").encode(), None),
                 (HDR.encode() + ROW("/x", "12345678901234567890").encode(), None)]
        for data, exact in cases:
            with self.subTest(data=data[:30]):
                self.receipt(data)
                out, code = self.go()
                self.assertEqual(code, 1)
                self.assertTrue(out.startswith(ROOT_USAGE + ".strict-delivery/receipts/%s.yml: " % S), out)
                self.assertTrue(out.endswith(remedy), out)
                self.assertEqual(out.count("\n"), 1)
                if exact:
                    self.assertEqual(out, ROOT_USAGE + exact + remedy)

    def test_truncated_receipt_fails_input(self):  # RC16
        self.receipt(HDR + "  - path: /x\n    sha: abc")
        self.assertIn("reads.0.sha: must be 7 to 40 lowercase hex digits", self.go()[0])
        self.receipt(HDR + ROW("/x", "a" * 40).rstrip("\n"))
        self.assertIn("the last line is cut (no final newline)", self.go()[0])

    def test_header_only_receipt_fails_input(self):  # RC17
        self.receipt(HDR)
        self.assertEqual(self.go(), (ROOT_USAGE + ".strict-delivery/receipts/%s.yml: reads: must not be null; delete it to "
                                     "start the session's receipts again\n" % S, 1))

    def test_zero_byte_receipt_fails_input(self):  # RC18
        self.receipt(b"")
        self.assertEqual(self.go(), (ROOT_USAGE + ".strict-delivery/receipts/%s.yml: top level: must be a mapping; delete it "
                                     "to start the session's receipts again\n" % S, 1))

    def test_empty_reads_list_is_no_rows(self):  # RC19
        self.receipt("schema: receipt/1\nreads: []\n")
        self.assertEqual(self.go(), (self.fail_a(), 1))

    def test_receipt_bom_and_crlf_accepted(self):  # RC20
        text = HDR + ROW(self.A, NEW)
        self.receipt(b"\xef\xbb\xbf" + text.encode())
        self.assertEqual(self.go(), ("PASS context.reads\n", 0))
        self.receipt(text.replace("\n", "\r\n").encode())
        self.assertEqual(self.go(), ("PASS context.reads\n", 0))

    def test_symlinked_receipt_file_fails_input(self):  # RC21
        os.makedirs(self.rd)
        with open(self.rd + "/other.yml", "w") as fh:
            fh.write(HDR + ROW(self.A, NEW))
        for target in (self.rd + "/other.yml", self.rd + "/nowhere.yml"):
            with self.subTest(target=os.path.basename(target)):
                if os.path.lexists(self.rd + "/" + S + ".yml"):
                    os.remove(self.rd + "/" + S + ".yml")
                os.symlink(target, self.rd + "/" + S + ".yml")
                self.assertEqual(self.go(), (ROOT_USAGE + ".strict-delivery/receipts/%s.yml: is a symlink; receipt files must "
                                             "be regular files; delete it to start the session's receipts again\n" % S, 1))

    def test_symlinked_receipts_dir_fails_input(self):  # RC22 (also PR13)
        real = os.path.join(self.tmp, "rr")
        os.mkdir(real)
        os.symlink(real, self.rd)
        self.assertEqual(self.go(), (ROOT_USAGE + ".strict-delivery/receipts: is a symlink; directories must be real "
                                                  "directories\n", 1))

    def test_other_receipt_file_states_fail_input(self):  # RC23
        os.makedirs(self.rd)
        f = self.rd + "/" + S + ".yml"
        os.mkdir(f)
        out = self.one_input(self.args(), prefix=".strict-delivery/receipts/%s.yml: is not a regular file" % S)
        os.rmdir(f)
        os.mkfifo(f)
        self.one_input(self.args(), prefix=".strict-delivery/receipts/%s.yml: is not a regular file" % S)
        os.remove(f)
        if os.geteuid() != 0:
            with open(f, "w") as fh:
                fh.write(HDR + ROW(self.A, NEW))
            os.chmod(f, 0)
            self.one_input(self.args(), prefix=".strict-delivery/receipts/%s.yml: cannot read file (Permission denied)" % S)
            os.chmod(f, 0o600)
        os.remove(f)
        os.rmdir(self.rd)
        open(self.rd, "w").close()
        self.one_input(self.args(), prefix=".strict-delivery/receipts: ")
        os.remove(self.rd)
        os.rename(self.fx + "/.strict-delivery", self.fx + "/sd")
        open(self.fx + "/.strict-delivery", "w").close()
        self.one_input(self.args())
        self.assertTrue(out)

    def test_large_receipt_file_linear(self):  # RC24 M9
        entries = [E("docs/f%d.md" % i) for i in range(50)] + [E("docs/f0.md", lines="1-1")]  # 50 files, 51 entries
        for i in range(50):
            self.put("docs/f%d.md" % i, b"x\n")
        self.ctx(kinds={"plan": entries})
        body = "".join(ROW("/n/%d" % i, NEW) for i in range(5000))
        body += "".join(ROW(self.real + "/docs/f%d.md" % i, NEW) for i in range(50))
        self.receipt(HDR + body)
        with mock.patch("gates.lib.receipts.load", wraps=receipts.load) as ld, \
                mock.patch("gates.lib.receipts.content_sha", wraps=receipts.content_sha) as cs:
            t = time.time()
            self.assertEqual(self.go(), ("PASS context.reads\n", 0))
        self.assertEqual(ld.call_count, 1)
        self.assertEqual(cs.call_count, 50)
        self.assertLess(time.time() - t, 20)

    def test_awkward_paths_round_trip_and_match(self):  # RC25 LN2
        cases = [("sp ace", "sp ace"), ("é", "é"), ("q\"uote", "q\"uote"), ("-lead", "-lead"), ("trail ", "trail "),
                 ("new\nline", "new\\nline"), ("esc\x1b[31m", "esc\\x1b[31m"), ("back\\slash", "back\\\\slash"),
                 ("uⰯ", "u\\u2c2f"), ("uࡰ", "u\\u0870"), ("u\U0001fae8", "u\\U0001fae8"),
                 ("sep ", "sep\\u2028"), ("bom﻿", "bom\\ufeff"), ("cr\rx", "cr\\rx")]
        cfg = config.load(self.fx)
        for name, shown in cases:
            with self.subTest(name=name):
                d = self.real + "/awk/" + name
                os.makedirs(d, exist_ok=True)
                with open(d + "/f.md", "wb") as fh:
                    fh.write(b"x\n")
                link = self.fx + "/awk/ln"
                if os.path.lexists(link):
                    os.remove(link)
                os.symlink(d, link)
                self.ctx(kinds={"plan": [E("awk/ln/f.md")]})
                self.assertEqual(self.go(), ("FAIL context.read.%s/awk/%s/f.md: not read in this session\n"
                                             % (self.real, shown), 1))
                receipts.record(self.fx, cfg, S, d + "/f.md")
                self.assertEqual(self.go(), ("PASS context.reads\n", 0))
                os.remove(self.rd + "/" + S + ".yml")
        self.ctx(kinds={"plan": [E("awk/ln/f.md")]})
        os.remove(self.fx + "/awk/ln")
        d = self.real + "/awk/json\nid"
        os.makedirs(d)
        with open(d + "/f.md", "wb") as fh:
            fh.write(b"x\n")
        os.symlink(d, self.fx + "/awk/ln")
        d2 = json.loads(self.run_g(["--json"] + self.args())[0])
        self.assertEqual(d2["lines"][0]["id"], "context.read.%s/awk/json\nid/f.md" % self.real)

    def test_gate_writes_nothing(self):  # RC26 M38
        def snap():
            out = {}
            for base, dirs, files in os.walk(self.fx):
                dirs[:] = [d for d in dirs if d != ".git"]
                for n in dirs + files:
                    p = os.path.join(base, n)
                    out[p] = os.lstat(p).st_mtime_ns
            return out, git(self.fx, "status", "--porcelain", "--untracked-files=all")

        before = snap()
        self.go()
        self.assertEqual(snap(), before)
        self.assertFalse(os.path.exists(self.rd))
        self.read_a()
        before = snap()
        self.go()
        self.assertEqual(snap(), before)

    def test_gate_uses_receipts_load_and_content_sha(self):  # RC27
        with mock.patch("gates.lib.receipts.load", return_value=[{"path": self.A, "sha": "b" * 40}]) as ld, \
                mock.patch("gates.lib.receipts.content_sha", return_value="b" * 40) as cs:
            self.assertEqual(self.go(), ("PASS context.reads\n", 0))
        self.assertEqual(ld.call_count, 1)
        cs.assert_called_once_with(self.A)

    def test_sha_compare_is_exact(self):  # RC28 M12
        for i in range(40):
            near = NEW[:i] + ("0" if NEW[i] != "0" else "1") + NEW[i + 1:]
            self.rows((self.A, near))
            out, code = self.go()
            self.assertEqual((out, code), (self.fail_a("read at %s, now %s: read it again" % (near, NEW)), 1))
            if i > 3:
                break
        self.rows((self.A, NEW[:7] + "0" * 33))
        self.assertEqual(self.go()[1], 1)


class Files(Base):
    def test_deleted_after_read_fails_file(self):  # RF2 RF3
        self.read_a()
        os.remove(self.fx + "/docs/x.md")
        want = "FAIL context.file.%s: not a readable regular file now\n" % self.A
        self.assertEqual(self.go(), (want, 1))
        os.remove(self.rd + "/" + S + ".yml")
        self.assertEqual(self.go(), (want, 1))  # RF3: never read, never existed

    def test_directory_fails_file(self):  # RF4 M17
        os.remove(self.fx + "/docs/x.md")
        os.mkdir(self.fx + "/docs/x.md")
        self.rows((self.A, NEW))
        self.assertEqual(self.go(), ("FAIL context.file.%s: not a readable regular file now\n" % self.A, 1))

    def test_unreadable_fails_file(self):  # RF5
        if os.geteuid() == 0:
            self.skipTest("root reads any file")
        self.read_a()
        os.chmod(self.fx + "/docs/x.md", 0)
        self.addCleanup(os.chmod, self.fx + "/docs/x.md", 0o600)
        want = ("FAIL context.file.%s: not a readable regular file now\n" % self.A, 1)
        self.assertEqual(self.go(), want)
        os.chmod(self.fx + "/docs/x.md", 0o600)
        os.chmod(self.fx + "/docs", 0)
        self.addCleanup(os.chmod, self.fx + "/docs", 0o755)
        self.assertEqual(self.go(), want)

    def test_fifo_fails_file_without_blocking(self):  # RF6 M18
        os.remove(self.fx + "/docs/x.md")
        os.mkfifo(self.fx + "/docs/x.md")
        out, code = self.sub(self.args(), cwd=self.tmp)  # a hang would raise subprocess.TimeoutExpired (60 s)
        self.assertEqual((out, code), ("FAIL context.file.%s: not a readable regular file now\n" % self.A, 1))

    def test_dangling_symlink_fails_file(self):  # RF7 RF9 VN6 M19
        os.remove(self.fx + "/docs/x.md")
        os.symlink(self.fx + "/nowhere", self.fx + "/docs/x.md")
        out, code = self.go()
        self.assertEqual((out, code), ("FAIL context.file.%s/nowhere: not a readable regular file now\n" % self.real, 1))
        os.remove(self.fx + "/docs/x.md")
        os.symlink(self.fx + "/l2", self.fx + "/docs/x.md")
        os.symlink(self.fx + "/docs/x.md", self.fx + "/l2")
        out, code = self.go()
        self.assertEqual(code, 1)
        self.assertTrue(out.startswith("FAIL context.file." + self.real + "/"), out)
        self.assertTrue(out.endswith(": not a readable regular file now\n"), out)
        self.assertEqual(out.count("\n"), 1)

    def test_symlink_to_file_resolves(self):  # RF8
        os.symlink(self.fx + "/docs/x.md", self.fx + "/docs/ln.md")
        self.ctx(kinds={"plan": [E("docs/ln.md")]})
        self.assertEqual(self.go(), (self.fail_a(), 1))

    def test_device_and_socket_fail_file(self):  # RF10
        self.ctx(roles={"drafter": [E("{brief}")]})
        self.assertEqual(self.go("--role", "drafter", "--brief", "/dev/null"),
                         ("FAIL context.file./dev/null: not a readable regular file now\n", 1))
        sdir = tempfile.mkdtemp(dir="/tmp")
        self.addCleanup(os.rmdir, sdir)
        path = sdir + "/s"
        s = socket.socket(socket.AF_UNIX)
        self.addCleanup(s.close)
        s.bind(path)
        self.addCleanup(os.remove, path)
        out, code = self.go("--role", "drafter", "--brief", path)
        self.assertEqual(code, 1)
        self.assertTrue(out.startswith("FAIL context.file."), out)

    def test_file_as_directory_fails_file(self):  # RF11
        self.ctx(kinds={"plan": [E("docs/x.md/y.md")]})
        out, code = self.go()
        self.assertEqual((out, code), ("FAIL context.file.%s/y.md: not a readable regular file now\n" % self.A, 1))

    def test_overlong_path_fails_file(self):  # RF12
        for rel in ("docs/" + "a" * 300, "/".join(["d" * 200] * 6) + "/f.md"):
            with self.subTest(n=len(rel)):
                self.ctx(kinds={"plan": [E(rel)]})
                out, code = self.go()
                self.assertEqual(code, 1)
                self.assertTrue(out.startswith("FAIL context.file." + self.real + "/"), out[:60])
                self.assertEqual(out.count("\n"), 1)

    def test_empty_required_file(self):  # RF13
        self.put("docs/x.md", b"")
        self.rows((self.A, "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391"))
        self.assertEqual(self.go(), ("PASS context.reads\n", 0))

    def test_large_required_file(self):  # RF14
        data = b"0123456789abcdef" * (3 * 1024 * 1024 // 16)
        self.put("docs/x.md", data)
        self.rows((self.A, SHA(data)))
        self.assertEqual(self.go(), ("PASS context.reads\n", 0))
        self.put("docs/x.md", data[:-1] + b"X")
        self.assertEqual(self.go(), (self.fail_a("read at %s, now %s: read it again" % (SHA(data), SHA(data[:-1] + b"X"))), 1))

    def test_nul_not_reachable_through_the_gate(self):  # RF16
        self.ctx(roles={"drafter": [E("{brief}")]})
        self.one_input(self.args("--role", "drafter", "--brief", "a\0b"),
                       "--brief: must be one line of printable text of at most 4096 characters")
        with self.assertRaises(GateError):
            context.absolute(self.fx, "a\0b")

    def test_file_outside_tree_is_gated(self):  # RF17
        outside = os.path.join(self.tmp, "outside.md")
        with open(outside, "wb") as fh:
            fh.write(b"x\n")
        self.ctx(roles={"drafter": [E("{brief}")]})
        self.assertEqual(self.go("--role", "drafter", "--brief", outside),
                         ("FAIL context.read.%s: not read in this session\n" % outside, 1))
        self.rows((outside, NEW))
        self.assertEqual(self.go("--role", "drafter", "--brief", outside), ("PASS context.reads\n", 0))

    def test_ignored_file_is_gated(self):  # RF18
        rel = ".strict-delivery/state/decisions/in-force.md"
        self.put(".gitignore", b".strict-delivery/state/decisions/in-force.md\n")
        self.put(rel, b"x\n")
        self.ctx(every=[E(rel)])
        self.assertEqual(git(self.fx, "check-ignore", rel), rel)
        want = self.real + "/" + rel
        self.assertEqual(self.go(), ("FAIL context.read.%s: not read in this session\n" % want, 1))
        self.rows((want, NEW))
        self.assertEqual(self.go(), ("PASS context.reads\n", 0))

    def test_file_vanishing_midway_is_file_line(self):  # RF19 PD3 M16
        self.read_a()
        with mock.patch("gates.lib.receipts.content_sha", side_effect=GateError("gone")):
            self.assertEqual(self.go(), ("FAIL context.file.%s: not a readable regular file now\n" % self.A, 1))


# ------------------------------------------------------------------------------------------ lists

class Lists(Base):
    def test_empty_list_passes(self):  # LS1 M30
        self.ctx()
        self.assertEqual(self.go(), ("PASS context.reads\n", 0))
        self.assertFalse(os.path.exists(self.rd))

    def test_every_only(self):  # LS2
        self.ctx(every=[E("docs/x.md")])
        self.assertEqual(self.go(kind="program"), (self.fail_a(), 1))

    def test_kind_without_list_passes(self):  # LS3
        self.assertEqual(self.go(kind="program"), ("PASS context.reads\n", 0))
        self.assertEqual(self.go(), (self.fail_a(), 1))

    def test_role_list_selected_by_role(self):  # LS4
        self.ctx(roles={"task_reviewer": [E("docs/x.md")]})
        self.assertEqual(self.go("--role", "task_reviewer"), (self.fail_a(), 1))
        self.assertEqual(self.go(), ("PASS context.reads\n", 0))

    def test_kind_and_role_overlap(self):  # LS5
        self.put("docs/y.md", b"y\n")
        self.ctx(every=[E("docs/x.md")], kinds={"plan": [E("docs/x.md"), E("docs/y.md")]},
                 roles={"drafter": [E("docs/y.md"), E("docs/x.md", lines="1-1")]})
        out, code = self.go("--role", "drafter")
        self.assertEqual(out, self.fail_a() + "FAIL context.read.%s/docs/y.md: not read in this session\n" % self.real)

    def test_line_order_is_required_order(self):  # LS6 PD6
        for n in "abcd":
            self.put("docs/%s.md" % n)
        self.put("h.md", (HANDOFF % "required_reads:\n  - path: docs/d.md\n    why: w\n").encode())
        self.ctx(every=[E("docs/a.md")], kinds={"plan": [E("docs/b.md")]}, roles={"drafter": [E("docs/c.md")]})
        out, _ = self.go("--role", "drafter", "--handoff", "h.md")
        self.assertEqual(out, "".join("FAIL context.read.%s/docs/%s.md: not read in this session\n" % (self.real, n)
                                      for n in "abcd"))

    def test_one_line_per_id(self):  # LS7 LS21 PD5 M21
        os.symlink(self.fx + "/docs/x.md", self.fx + "/docs/ln.md")
        self.ctx(kinds={"plan": [E("docs/x.md"), E("docs/ln.md"), E("docs/x.md", lines="1-1"), E("docs/x.md", lines="2-2")]})
        self.assertEqual(self.go(), (self.fail_a(), 1))

    def test_unresolved_placeholder_fails(self):  # LS8
        self.ctx(kinds={"plan": [E("{paths.plan_state}/{plan}/handoff.md")]})
        out, code = self.go()
        self.assertEqual((out, code), ("FAIL context.unresolved.{paths.plan_state}/{plan}/handoff.md: needs {plan}\n", 1))

    def test_unresolved_with_receipt_still_fails(self):  # LS9
        self.ctx(kinds={"plan": [E("{plan}/x.md")]})
        self.read_a()
        self.assertEqual(self.go(), ("FAIL context.unresolved.{plan}/x.md: needs {plan}\n", 1))

    def test_unresolved_entries_share_a_line(self):  # LS10 M21
        self.ctx(kinds={"plan": [E("{plan}/x.md", lines="1-2"), E("{plan}/x.md", lines="3-4")]})
        self.assertEqual(self.go(), ("FAIL context.unresolved.{plan}/x.md: needs {plan}\n", 1))

    def test_unresolved_names_first_placeholder(self):  # LS11 M22
        self.ctx(kinds={"plan": [E("{integration}/{paths.programs}/{program}/status.md")]})
        self.assertEqual(self.go()[0], "FAIL context.unresolved.{integration}/{paths.programs}/{program}/status.md: "
                                       "needs {integration}\n")

    def test_brief_entries(self):  # LS12
        self.ctx(roles={"task_reviewer": [E("{brief}")]})
        self.put("docs/b.md", b"b\n")
        outside = os.path.join(self.tmp, "o.md")
        open(outside, "w").close()
        g = lambda *a: self.go("--role", "task_reviewer", *a)
        self.assertEqual(g("--brief", "docs/b.md")[0], "FAIL context.read.%s/docs/b.md: not read in this session\n" % self.real)
        self.assertEqual(g("--brief", outside)[0], "FAIL context.read.%s: not read in this session\n" % outside)
        self.assertEqual(g("--brief", "docs/none.md")[0], "FAIL context.file.%s/docs/none.md: not a readable regular file now\n"
                         % self.real)
        for extra in (("--brief", ""), ()):
            self.assertEqual(g(*extra)[0], "FAIL context.unresolved.{brief}: needs {brief}\n")

    def test_handoff_without_extras(self):  # LS13
        self.put("h.md", (HANDOFF % "").encode())
        self.assertEqual(self.go("--handoff", "h.md"), (self.fail_a(), 1))
        self.ctx(kinds={"plan": [E("{paths.plan_state}/p/handoff.md")]})
        self.assertEqual(self.go("--handoff", "h.md")[0].count("\n"), 1)  # the handoff itself only when the list names it

    def extras(self, text="required_reads:\n  - path: docs/x.md\n    why: w\n"):
        self.ctx()
        self.put("h.md", (HANDOFF % text).encode())

    def test_handoff_extras_read(self):  # LS14
        self.extras()
        self.read_a()
        self.assertEqual(self.go("--handoff", "h.md"), ("PASS context.reads\n", 0))

    def test_handoff_extras_gated(self):  # LS15 M23
        self.extras()
        self.assertEqual(self.go("--handoff", "h.md"), (self.fail_a(), 1))

    def test_handoff_extras_stale(self):  # LS16
        self.extras()
        self.rows((self.A, OLD))
        self.assertEqual(self.go("--handoff", "h.md")[0], self.fail_a("read at %s, now %s: read it again" % (OLD, NEW)))

    def test_handoff_extra_duplicating_kind_entry(self):  # LS17
        self.extras()
        self.ctx(kinds={"plan": [E("docs/x.md")]})
        self.assertEqual(self.go("--handoff", "h.md"), (self.fail_a(), 1))

    def test_handoff_extras_placeholders(self):  # LS18
        self.extras("required_reads:\n  - path: \"{paths.plan_state}/{plan}/ledger.md\"\n    why: w\n")
        self.assertEqual(self.go("--handoff", "h.md")[0], "FAIL context.unresolved.{paths.plan_state}/{plan}/ledger.md: "
                                                          "needs {plan}\n")
        out = self.go("--handoff", "h.md", "--plan", "p")[0]
        self.assertEqual(out, "FAIL context.read.%s/.strict-delivery/state/plans/p/ledger.md: " % self.real
                         + "not a readable regular file now\n".replace("not a readable regular file now", "not read in this session")
                         if os.path.exists(self.fx + "/.strict-delivery/state/plans/p/ledger.md") else
                         "FAIL context.file.%s/.strict-delivery/state/plans/p/ledger.md: not a readable regular file now\n" % self.real)

    def test_range_entry_any_current_receipt(self):  # LS19 LN5 D-Q2 (a)
        self.put("docs/x.md", b"".join(b"line %d\n" % i for i in range(1000)))
        data = source(self.fx + "/docs/x.md", "rb")
        self.ctx(kinds={"plan": [E("docs/x.md", lines="3-9")]})
        cfg = config.load(self.fx)
        for what in ("whole", "head", "offset500"):
            with self.subTest(what=what):
                receipts.record(self.fx, cfg, S, self.fx + "/docs/x.md")  # record takes no range
                out, code = self.go()
                self.assertEqual((out.strip(), code), ("PASS context.reads", 0))
                self.assertEqual(out, "PASS context.reads\n")
        self.rows((self.A, OLD))
        self.assertEqual(self.go(), (self.fail_a("read at %s, now %s: read it again" % (OLD, SHA(data))), 1))

    def test_lines_past_end_not_checked_by_gate(self):  # LS20 M20
        self.put("docs/x.md", b"a\n" * 10)
        self.ctx(kinds={"plan": [E("docs/x.md", lines="500-600")]})
        self.rows((self.A, SHA(b"a\n" * 10)))
        self.assertEqual(self.go(), ("PASS context.reads\n", 0))
        with mock.patch("gates.lib.context.split", side_effect=AssertionError("split called")):
            self.assertEqual(self.go(), ("PASS context.reads\n", 0))

    def test_required_path_may_be_a_receipt_file(self):  # LS22
        rel = ".strict-delivery/receipts/%s.yml" % S
        self.ctx(kinds={"plan": [E(rel)]})
        self.rows((self.real + "/" + rel, "0" * 40))
        out, code = self.go()
        self.assertEqual(code, 1)
        self.assertTrue(out.startswith("FAIL context.read.%s/%s: read at %s, now " % (self.real, rel, "0" * 40)), out)

    def test_mixed_outcomes_in_order(self):  # LS23
        for n in ("never", "stale", "fine"):
            self.put("docs/%s.md" % n, (n + "\n").encode())
        self.ctx(kinds={"plan": [E("{plan}/u.md"), E("docs/gone.md"), E("docs/never.md"), E("docs/stale.md"),
                                 E("docs/fine.md")]})
        self.rows((self.real + "/docs/stale.md", OLD), (self.real + "/docs/fine.md", SHA(b"fine\n")))
        r = self.real
        self.assertEqual(self.go(), (
            "FAIL context.unresolved.{plan}/u.md: needs {plan}\n"
            "FAIL context.file.%s/docs/gone.md: not a readable regular file now\n"
            "FAIL context.read.%s/docs/never.md: not read in this session\n"
            "FAIL context.read.%s/docs/stale.md: read at %s, now %s: read it again\n" % (r, r, r, OLD, SHA(b"stale\n")), 1))

    def test_only_the_planned_line_forms(self):  # LN1 LN4
        self.read_a()
        self.assertEqual(self.go()[0], "PASS context.reads\n")
        self.rows((self.A, OLD))
        out, _ = self.go()
        self.assertNotIn("PASS", out)
        self.assertNotIn("context.reads", out)

    def test_unresolved_id_is_path_as_written(self):  # LN3
        self.ctx(kinds={"plan": [E("{integration}/{paths.programs}/x.md")]})
        self.assertTrue(self.go()[0].startswith("FAIL context.unresolved.{integration}/{paths.programs}/x.md: "))

    def test_pass_only_when_nothing_failed(self):  # LN4 M29
        self.put("docs/y.md")
        self.ctx(kinds={"plan": [E("docs/x.md"), E("docs/y.md")]})
        self.read_a()
        out, code = self.go()
        self.assertEqual(code, 1)
        self.assertEqual(out.count("PASS"), 0)
        self.assertEqual(out.count("\n"), 1)

    def test_exit_codes(self):  # LN6
        self.read_a()
        self.assertEqual(self.go()[1], 0)
        os.remove(self.rd + "/" + S + ".yml")
        self.assertEqual(self.go()[1], 1)
        self.assertEqual(self.run_g(["--root", self.fx])[1], 1)
        with mock.patch("gates.lib.receipts.load", side_effect=KeyboardInterrupt), self.assertRaises(KeyboardInterrupt):
            self.go()

    def test_stdout_once_stderr_empty(self):  # LN7
        class Counting(io.StringIO):
            writes = 0

            def write(self, s):
                Counting.writes += 1
                return super().write(s)

        out, err = Counting(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            gate_context.main(self.args())
        self.assertEqual((Counting.writes, err.getvalue()), (1, ""))
        self.assertNotIn("\x1b", out.getvalue())

    def test_idempotent(self):  # LN10
        a = self.go()
        self.assertEqual(self.go(), a)
        self.read_a()
        b = self.go()
        self.assertEqual(self.go(), b)
        self.put("docs/x.md", b"changed\n")
        c = self.go()
        self.assertEqual(self.go(), c)
        self.assertNotEqual(b, c)

    def test_git_config_noise_has_no_effect(self):  # LN11
        src = source("gates/gate_context.py")
        self.assertNotIn("subprocess", src)
        self.assertNotIn('"git"', src)
        self.read_a()
        want = self.go()
        for k, v in (("color.ui", "always"), ("color.diff", "always"), ("core.abbrev", "7")):
            git(self.fx, "config", k, v)
        shutil_copy = os.path.join(self.tmp, "index-copy")
        with open(self.fx + "/.git/index", "rb") as fh, open(shutil_copy, "wb") as out:
            out.write(fh.read())
        with mock.patch.dict(os.environ, {"GIT_INDEX_FILE": shutil_copy}):
            self.assertEqual(self.go(), want)

    def test_non_ascii_path_in_subprocess(self):  # LN12
        os.makedirs(self.fx + "/é", exist_ok=True)
        self.put("é/f.md")
        self.ctx(kinds={"plan": [E("é/f.md")]})
        out, code = self.sub(self.args())
        self.assertEqual((out, code), ("FAIL context.read.%s/é/f.md: not read in this session\n" % self.real, 1))

    def test_many_entries(self):  # LN13
        self.ctx(kinds={"plan": [E("docs/n%d.md" % i) for i in range(200)]})
        t = time.time()
        out, code = self.go()
        self.assertEqual(code, 1)
        self.assertEqual(out, "".join("FAIL context.file.%s/docs/n%d.md: not a readable regular file now\n" % (self.real, i)
                                      for i in range(200)))
        self.assertLess(time.time() - t, 10)

    def test_module_docstring_states_narrow_promise(self):  # LN14 PD9
        doc = gate_context.__doc__
        for phrase in ("neither dispatches nor commits", "printed, not gated", "not that it was read in full",
                       "makes a dispatch or a commit through Claude Code"):
            self.assertIn(phrase, " ".join(doc.split()))


# ------------------------------------------------------------------------------------------ profiles, modules, versions

class Profiles(Base):
    def test_same_result_every_profile(self):  # PF1 PF4
        cases = {}
        for name in ("allread", "missing", "stale", "unresolved", "file", "input"):
            self.ctx(kinds={"plan": [E("docs/x.md")]})
            argv = self.args()
            if os.path.lexists(self.fx + "/docs/x.md") is False:
                self.put("docs/x.md")
            if os.path.lexists(self.rd + "/" + S + ".yml"):
                os.remove(self.rd + "/" + S + ".yml")
            if name == "allread":
                self.read_a()
            elif name == "stale":
                self.rows((self.A, OLD))
            elif name == "unresolved":
                self.ctx(kinds={"plan": [E("{plan}/x.md")]})
            elif name == "file":
                os.remove(self.fx + "/docs/x.md")
            elif name == "input":
                argv = ["--root", self.fx]
            results = []
            for p in ("light", "standard", "strict"):
                self.profile(p)
                results.append((self.run_g(argv), self.run_g(["--json"] + argv)))
            self.assertEqual(results[0], results[1], name)
            self.assertEqual(results[1], results[2], name)
            cases[name] = results[0][0]
        self.assertEqual(sorted(c[1] for c in cases.values()), [0, 1, 1, 1, 1, 1])

    def test_gate_does_not_read_profile(self):  # PF2 M10
        tree = ast.parse(source("gates/gate_context.py"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant):
                self.assertNotEqual(node.value, "profile")
            if isinstance(node, ast.Attribute):
                self.assertNotEqual(node.attr, "enforced")
            if isinstance(node, ast.Name):
                self.assertNotEqual(node.id, "enforced")


class Modules(Base):
    def test_module_form_equals_in_process(self):  # RG1
        for prep in (lambda: None, self.read_a):
            prep()
            self.assertEqual(self.sub(self.args(), cwd=self.tmp), self.go())

    def test_gate_context_registered(self):  # RG3
        from gates.__main__ import GATES
        if "context" not in GATES:
            self.skipTest("Rq-5-1 not on this branch")
        self.assertEqual(GATES["context"], "gates.gate_context")
        self.read_a()
        p = subprocess.run([sys.executable, "-m", "gates", "check", "context"] + self.args(), cwd=REPO,
                           env=dict(os.environ, PYTHONPATH=REPO, LC_ALL="C"), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual((p.stdout.decode(), p.returncode), self.go())

    def test_gate_context_declared_producer(self):  # RG4
        if "gates.gate_context" not in producers.PRODUCER_MODULES:
            self.skipTest("Rq-5-2 not on this branch")
        self.assertIn("context", schema.produced_kinds())
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            run_gate("schema", gate_schema.check, ["--root", REPO])
        self.assertIn("PASS schema.context\n", out.getvalue())

    def test_hook_call_shape(self):  # RG7
        self.read_a()
        for extra in ([], ["--role", "drafter"], ["--role", "drafter", "--plan", ""], ["--program", ""], ["--brief", ""]):
            res = gate_context.check(["--root", self.fx, "--session", S, "--kind", "plan"] + extra)
            self.assertEqual([(l.status, l.id) for l in res.lines], [("PASS", "context.reads")])
        self.put("h.md", (HANDOFF % "").encode())
        gate_context.check(self.args("--handoff", "h.md"))

    def test_digit_limits_same_on_both(self):  # VN1
        for limit in INT_LIMITS:
            with self.subTest(limit=limit), int_limit(limit):
                for n in (4300, 4301):
                    out, code = self.run_g(["--session", "9" * n, "--kind", "plan", "--root", self.fx])
                    self.assertEqual((out, code), (ROOT_USAGE + SESSION_TEXT + "\n", 1))
                self.ctx(kinds={"program": [E("{plan}/x.md")]}, roles={"drafter": [E("{brief}")]})
                for n in (4300, 4301):
                    out, code = self.go("--plan", "9" * n, kind="program")
                    self.assertTrue(out.startswith("FAIL context.file."), out[:50])
                    self.one_input(self.args("--role", "drafter", "--brief", "9" * n, "--plan", "p", kind="program"),
                                   "--brief: must be one line of printable text of at most 4096 characters")
        self.ctx(kinds={"plan": [E("docs/x.md", lines="1-" + "9" * 4301)]})
        self.assertTrue(self.go()[0].startswith(ROOT_USAGE + ".strict-delivery/context.yml: "))

    def test_unicode_version_independent(self):  # VN2
        for v in ("aⰯb", "aࡰb", "a\U0001fae8b"):
            self.one_input(self.args("--plan", v), "--plan: must match [a-z0-9][a-z0-9-]*")
            self.one_input(["--session", v, "--kind", "plan", "--root", self.fx], SESSION_TEXT)
        self.one_input(self.args("--plan", "K"), "--plan: must match [a-z0-9][a-z0-9-]*")
        self.ctx(roles={"drafter": [E("{brief}")]})
        for v in ("aKb",):
            self.assertNotIn("context.input", self.go("--role", "drafter", "--brief", v)[0])
        for v in ("aⰯb", "aࡰb", "a\U0001fae8b"):
            self.one_input(self.args("--role", "drafter", "--brief", v))
        src = source("gates/gate_context.py")
        for word in (".lower(", "casefold", "isprintable", "unicodedata", "isalnum", "IGNORECASE"):
            self.assertNotIn(word, src)
        self.rows((self.real + "/docs/é.md", NEW))  # NFC vs NFD never equal: exact string compare
        self.put("docs/é.md")
        self.ctx(kinds={"plan": [E("docs/é.md")]})
        self.assertEqual(self.go(), ("PASS context.reads\n", 0))
        self.rows((self.real + "/docs/é.md", NEW))
        self.assertEqual(self.go()[1], 1)

    def test_exception_groups_not_referenced(self):  # VN3
        src = source("gates/gate_context.py")
        csrc = source("gates/lib/context.py")
        for s in (src, csrc):
            self.assertNotIn("ExceptionGroup", s)
            self.assertNotIn("except*", s)
        if not hasattr(__builtins__ if isinstance(__builtins__, dict) else __builtins__, "ExceptionGroup") \
                and sys.version_info < (3, 11):
            self.skipTest("ExceptionGroup does not exist before Python 3.11")
        group = ExceptionGroup("x", [ValueError()])  # noqa: F821
        for target in ("gates.lib.receipts.load", "gates.lib.context.load", "gates.lib.receipts.content_sha"):
            with self.subTest(target=target), mock.patch(target, side_effect=group):
                self.read_a()
                out, code = self.go()
                self.assertTrue(out.startswith("FAIL context.input: ExceptionGroup: ") or "context.file" in out, out)
        with mock.patch("gates.lib.receipts.load", side_effect=BaseExceptionGroup("x", [KeyboardInterrupt()])):  # noqa: F821
            with self.assertRaises(BaseException):
                self.go()

    def test_nul_and_surrogates_refused_same_text(self):  # VN4
        self.one_input(["--session", "a\0b", "--kind", "plan", "--root", self.fx], SESSION_TEXT)
        self.one_input(["--session", "a\udc80", "--kind", "plan", "--root", self.fx], SESSION_TEXT)
        self.ctx(roles={"drafter": [E("{brief}")]})
        self.one_input(self.args("--role", "drafter", "--brief", "a\0b"))
        self.one_input(self.args("--handoff", "a\0b"))
        for root in (self.fx + "\0", "/x\udc80"):
            out = self.one_input(["--session", S, "--kind", "plan", "--root", root])
            self.assertIn("git rev-parse --show-toplevel", out)

    def test_output_independent_of_hash_seed(self):  # VN9
        for n in "abcdef":
            self.put("docs/%s.md" % n)
        self.ctx(every=[E("docs/%s.md" % n) for n in "fcaebd"])
        outs = {self.sub(self.args(), env={"PYTHONHASHSEED": s}) for s in ("0", "1", "2")}
        self.assertEqual(len(outs), 1)
        self.assertEqual(outs.pop()[0].count("\n"), 6)

    def test_module_imports_on_both(self):  # VN10
        src = source("gates/gate_context.py")
        self.assertIn("from __future__ import annotations", src)
        tree = ast.parse(src)
        self.assertFalse([n for n in ast.walk(tree) if type(n).__name__ in ("Match", "TryStar")])


if __name__ == "__main__":
    unittest.main()
