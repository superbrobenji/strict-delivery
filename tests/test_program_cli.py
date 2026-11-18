"""Tests for gates.tools.program_cli (plan Task P2.2) through ``gates.__main__.main`` in process and
``python3 -m gates program`` in a subprocess. Expected values are written by hand from the plan lines and the
input-domain table task-P2.2-domain.md (row ids in the comments); fixtures come from tests/helpers.py."""
import contextlib
import io
import os
import subprocess
import sys
import unittest
from unittest import mock

from gates import __main__ as gates_main
from gates import producers
from gates.lib import programs, yamlsub
from gates.tools import program_cli
from tests.helpers import GitIsolatedTestCase, commit_all, git, make_repo, write_record

NAME = "20261101-x"
PG = "docs/strict-delivery/plans"
PS = ".strict-delivery/state/plans"
PLAN = "prog-plan"
DEC = "DEC-20261105-bn3p"
HEAD_LINE = "| stream | block | branch | worktree | next task | estimate | used | status | blockers | pending decisions | delivers |"
PLAN_TEXT = ("## Block A1: first\n\n### Task A1.1: x\n\n## Block B1: second\n\n### Task B1.1: y\n")


def stream(sid, owns, **kw):
    s = {"id": sid, "purpose": "does " + sid, "plan": "%s/x-%s.md" % (PG, sid), "owns": owns, "estimate": 3,
         "depends_on": [], "merge_order": kw.pop("merge_order", 1)}
    s.update(kw)
    return s


def streams_row(*sts):
    return {"schema": "streams/1", "program": NAME, "plan": "%s/%s.md" % (PG, PLAN), "specs": [],
            "worktrees": "../w", "streams": list(sts) or [stream("a", ["a/"]), stream("b", ["b/"], merge_order=2)],
            "shared": []}


def breakdown_row(**kw):
    row = {"schema": "breakdown/1", "plan": PLAN, "max_concurrent": 2, "max_depth": 2, "done": [],
           "streams": [{"id": "a", "paths": ["a/"], "tasks": ["A1.1"], "unblock": "at program start"},
                       {"id": "b", "paths": ["b/"], "tasks": ["B1.1"], "unblock": "at program start"}],
           "edges": [], "groups": [{"id": "g", "tasks": ["A1.1", "B1.1"]}]}
    row.update(kw)
    return row


def load_yaml(path):
    with open(path, encoding="utf-8") as fh:
        return yamlsub.parse(fh.read())


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = gates_main.main(list(argv))
    return code, out.getvalue(), err.getvalue()


class Fx(GitIsolatedTestCase):
    """A repository on main holding the plan, the breakdown and an answered program-create decision, and the
    integration worktree ``<tmp>/w/<NAME>/integration`` made by the plan's one git command."""

    def setUp(self):
        super().setUp()
        make_repo(self.work)
        self.write_main(PG + "/%s.md" % PLAN, PLAN_TEXT)
        write_record(self.work, "%s/%s/breakdown.yml" % (PS, PLAN), breakdown_row())
        self.decision(DEC)
        commit_all(self.work, "plan")
        self.iw = os.path.join(self.tmp, "w", NAME, "integration")
        git(self.work, "worktree", "add", "-q", "-b", NAME + "/integration", self.iw, "main")
        self.sf = os.path.join(self.tmp, "streams.yml")
        self.set_streams(streams_row())

    def write_main(self, rel, text):
        path = os.path.join(self.work, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)

    def decision(self, did, status="answered", cls="program-create", root=None):
        write_record(root or self.work, ".strict-delivery/state/decisions/%s.yml" % did,
                     {"schema": "decision/1", "id": did, "status": status, "class": cls})

    def set_streams(self, row):
        with open(self.sf, "w", encoding="utf-8") as fh:
            fh.write(yamlsub.emit(row))

    def create(self, *extra, root=None, plan=PLAN, decision=DEC):
        return run("program", "create", NAME, "--streams", self.sf, "--decision", decision, "--plan", plan,
                   "--root", root or self.iw, *extra)

    def folder(self):
        return os.path.join(self.iw, ".strict-delivery/state/programs", NAME)

    def read(self, name):
        with open(os.path.join(self.folder(), name), encoding="utf-8") as fh:
            return fh.read()

    def commit_iw(self):
        return commit_all(self.iw, "program")


class Registration(unittest.TestCase):
    def test_program_produces_literal(self):  # PG1
        self.assertEqual(program_cli.PRODUCES, ("streams", "status", "sync-log", "request", "breakdown", "merged-log"))

    def test_program_registered(self):  # PG4, RG6, RG9
        self.assertIn("program", gates_main.COMMANDS)
        self.assertEqual(producers.PRODUCER_MODULES[-1], "gates.tools.program_cli")
        code, out, err = run("program")
        self.assertEqual((code, out), (2, ""))
        code, out, err = run("program", "bogus")
        self.assertEqual(code, 2)

    def test_main_argv_types(self):  # PG2
        for bad in ("x", ("create",), ["create", 5], [b"x"]):
            with self.subTest(repr(bad)):
                err = io.StringIO()
                with contextlib.redirect_stderr(err):
                    self.assertEqual(program_cli.main(bad), 2)
                self.assertEqual(err.getvalue(), "program: argv must be a list of str\n")


class Create(Fx):
    def test_create_writes_four_files_that_validate(self):  # CR1-CR4, RG8, Q-F80W-6 (b)
        code, out, err = self.create()
        self.assertEqual((code, err, out), (0, "", "push %s/integration\n" % NAME))
        self.assertEqual(sorted(os.listdir(self.folder())), ["merged.md", "status.md", "streams.yml", "sync-log.md"])
        self.assertEqual(self.read("merged.md").splitlines(), ["<!-- schema: merged-log/1 -->"])
        self.assertEqual(self.read("sync-log.md"), "<!-- schema: sync-log/1 -->\n")
        self.assertEqual(self.read("status.md").split("\n"), [
            "<!-- schema: status/1 -->", HEAD_LINE, "|---|---|---|---|---|---|---|---|---|---|---|",
            "| a | none | %s/a/main | ../w/%s/a/main | none | 3 | 0 | ready | none | none | does a |" % (NAME, NAME),
            "| b | none | %s/b/main | ../w/%s/b/main | none | 3 | 0 | ready | none | none | does b |" % (NAME, NAME),
            ""])
        self.assertEqual(load_yaml(os.path.join(self.folder(), "streams.yml")), streams_row())
        self.assertEqual(os.listdir(os.path.dirname(self.folder())), [NAME])
        code, out, err = run("check", "schema", "--root", self.iw)  # the fixture decision is a minimal row
        self.assertEqual([l for l in out.splitlines() if l.startswith("FAIL") and "programs" in l], [])
        self.assertIn("PASS schema.status", out)
        self.assertEqual(self.create()[0], 1)  # CR20: the folder exists now

    def test_create_through_python_m_gates(self):  # PC2: the subprocess path, both interpreters run this suite
        env = dict(os.environ)
        p = subprocess.run([sys.executable, "-m", "gates", "program", "create", NAME, "--streams", self.sf,
                            "--decision", DEC, "--plan", PLAN, "--root", self.iw], cwd=os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual((p.returncode, p.stdout, p.stderr), (0, b"push %s/integration\n" % NAME.encode(), b""))

    def refused(self, *needles, **kw):
        code, out, err = self.create(**kw)
        self.assertEqual((code, out), (1, ""))
        for n in needles:
            self.assertIn(n, err)
        self.assertFalse(os.path.exists(self.folder()))
        self.assertEqual(os.listdir(os.path.join(self.iw, ".strict-delivery/state")), ["decisions"] if False else
                         os.listdir(os.path.join(self.iw, ".strict-delivery/state")))
        return err

    def test_create_refuses_outline_only_plan(self):  # Q-PL-1 (a)
        self.write_main(PG + "/%s.md" % PLAN, "## Block A1: first\n\n- a bullet only\n")
        commit_all(self.work, "outline")
        git(self.iw, "merge", "-q", "main")
        self.refused("outline.block.A1")
        write = PLAN_TEXT + "\n## Later blocks\n\n- **X.** soon\n"
        self.write_main(PG + "/%s.md" % PLAN, write)
        commit_all(self.work, "later")
        git(self.iw, "merge", "-q", "main")
        self.refused("Planned in full")

    def test_create_refuses_missing_or_invalid_breakdown(self):  # CR7, CP3
        path = os.path.join(self.iw, PS, PLAN, "breakdown.yml")
        os.rename(path, path + ".bak")
        self.refused("breakdown.yml")
        os.rename(path + ".bak", path)
        for name, text in (("yaml error", "a: [\n"), ("not a map", "- x\n")):
            with self.subTest(name), open(path, "w", encoding="utf-8") as fh:
                fh.write(text)
            self.refused("breakdown")
        write_record(self.iw, "%s/%s/breakdown.yml" % (PS, PLAN), breakdown_row(plan="other"))
        self.refused("streams", "other")
        write_record(self.iw, "%s/%s/breakdown.yml" % (PS, PLAN), breakdown_row(max_depth=0))
        self.refused("breakdown/1", "max_depth")

    def test_create_refuses_breakdown_over_effective_limits(self):  # F-QPL-2, CL1-CL3
        env = {"CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH": "1", "CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS": "2"}
        with mock.patch.dict(os.environ, env):  # limits (depth 2, concurrent 2): equal passes
            self.assertEqual(self.create()[0], 0)
        os.rename(self.folder(), self.folder() + ".gone")
        for name, bd, needle in (("conc", breakdown_row(max_concurrent=3), "max_concurrent"),
                                 ("depth", breakdown_row(max_depth=3), "max_depth")):
            with self.subTest(name), mock.patch.dict(os.environ, env):
                write_record(self.iw, "%s/%s/breakdown.yml" % (PS, PLAN), bd)
                code, out, err = self.create()
                self.assertEqual(code, 1)
                self.assertIn(needle, err)
        with self.subTest("malformed env"), mock.patch.dict(os.environ, {"CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH": "x"}):
            self.assertEqual(self.create()[0], 1)

    def test_create_refuses_breakdown_disagreeing_with_streams(self):  # F-QPL-3, Q-F80W-9 (a)
        cases = {"extra path": streams_row(stream("a", ["a/", "a2/"]), stream("b", ["b/"], merge_order=2)),
                 "period": streams_row(stream("a", ["a/"], period={"from": "program-start", "until": "merged:b"}),
                                       stream("b", ["b/"], merge_order=2)),
                 "plan": dict(streams_row(), plan=PG + "/other.md")}
        for name, row in cases.items():
            with self.subTest(name):
                self.set_streams(row)
                code, out, err = self.create()
                self.assertEqual(code, 1)
                self.assertIn("streams", err)
                self.assertFalse(os.path.exists(self.folder()))
        a_then_b = streams_row(stream("a", ["a/"]), stream("b", ["b/"], merge_order=2, stacked_on="a"))
        self.set_streams(a_then_b)
        code, out, err = self.create()
        self.assertEqual(code, 1)
        self.assertIn("stacked_on", err)
        write_record(self.iw, "%s/%s/breakdown.yml" % (PS, PLAN), breakdown_row(edges=[{"from": "A1.1", "to": "B1.1"}],
                                                                                groups=[{"id": "g", "tasks": ["A1.1"]}]))
        self.assertEqual(self.create()[0], 0)  # the edge orders merged:b/B1 after merged:a

    def test_create_needs_answered_program_create(self):  # CR13
        self.decision("DEC-20261105-wd3p", "withdrawn", root=self.iw)
        self.decision("DEC-20261105-op3p", "open", root=self.iw)
        self.decision("DEC-20261105-sc3p", "answered", "scope", root=self.iw)
        for did in ("DEC-20261105-wd3p", "DEC-20261105-op3p", "DEC-20261105-sc3p", "DEC-20261105-zz39"):
            with self.subTest(did):
                self.refused("program-create", decision=did)

    def test_create_refuses_name_on_main(self):  # CR12
        base = ".strict-delivery/state/programs/%s" % NAME
        self.write_main(base + "/streams.yml", "schema: streams/1\n")
        commit_all(self.work, "name taken")
        self.refused("already exists")

    def test_refused_off_integration_branch(self):  # PG5
        want = "%s/integration" % NAME
        git(self.iw, "checkout", "-q", "-b", NAME + "/a/main")
        self.refused(want)
        git(self.iw, "checkout", "-q", "--detach")
        self.refused(want, "detached")
        git(self.iw, "checkout", "-q", NAME + "/integration")
        self.assertEqual(self.create(root=self.work)[0], 1)  # the main checkout is on main
        self.assertEqual(git(self.work, "rev-parse", "--abbrev-ref", "HEAD"), "main")  # RT11

    def test_create_refused_in_wrong_worktree(self):  # RT3
        other = os.path.join(self.tmp, "elsewhere")
        git(self.work, "worktree", "add", "-q", "-b", "other-x/integration", other, "main")
        git(other, "branch", "-m", NAME + "/integration2")
        git(other, "checkout", "-q", "-b", "20261102-y/integration")
        self.assertEqual(self.create(root=other)[0], 1)

    def test_create_flag_forms(self):  # CR17, CR18, PG16
        for argv in (["program", "create", NAME, "--decision", DEC, "--plan", PLAN, "--root", self.iw],
                     ["program", "create", NAME, "--streams", "", "--decision", DEC, "--plan", PLAN, "--root", self.iw],
                     ["program", "create", NAME, "--streams", self.sf, "--streams", self.sf, "--decision", DEC,
                      "--plan", PLAN, "--root", self.iw],
                     ["program", "create", NAME, "--streams", self.sf, "--decision", DEC, "--plan", "A_b", "--root", self.iw],
                     ["program", "create", "x", "--streams", self.sf, "--decision", DEC, "--plan", PLAN, "--root", self.iw]):
            with self.subTest(argv[3:6]):
                self.assertEqual(run(*argv)[0], 1)
                self.assertFalse(os.path.exists(self.folder()))

    def test_create_refuses_invalid_streams_file(self):  # CR15, CR16
        for name, row in (("overlap", streams_row(stream("a", ["a/"]), stream("b", ["a/b.py"], merge_order=2))),
                          ("worktrees", dict(streams_row(), worktrees="/abs"))):
            with self.subTest(name):
                self.set_streams(row)
                self.refused()
        os.unlink(self.sf)
        self.refused("streams file")

    def test_write_failure_leaves_nothing(self):  # PG12, Q11
        if os.geteuid() == 0:
            self.skipTest("root ignores directory modes")
        programs_dir = os.path.join(self.iw, ".strict-delivery/state")
        os.makedirs(os.path.join(programs_dir, "programs"))
        os.chmod(os.path.join(programs_dir, "programs"), 0o555)
        try:
            code, out, err = self.create()
        finally:
            os.chmod(os.path.join(programs_dir, "programs"), 0o755)
        self.assertEqual((code, out), (1, ""))
        self.assertEqual(os.listdir(os.path.join(programs_dir, "programs")), [])


class After(Fx):
    """Subcommands after a successful create (committed on the integration branch)."""

    def setUp(self):
        super().setUp()
        self.assertEqual(self.create()[0], 0)
        self.commit_iw()

    def cli(self, sub, *argv):
        return run("program", *sub.split(" "), NAME, *argv, "--root", self.iw)

    def clean(self):
        return git(self.iw, "status", "--porcelain", "--untracked-files=all")

    def test_status_rewrites_one_row(self):  # ST1, ST14
        before = self.read("status.md").split("\n")
        code, out, err = self.cli("status", "a", "--used", "3", "--status", "running")
        self.assertEqual((code, out, err), (0, "push %s/integration\n" % NAME, ""))
        after = self.read("status.md").split("\n")
        self.assertEqual(after[:3], before[:3])
        self.assertEqual(after[4:], before[4:])
        self.assertEqual(after[3], "| a | none | %s/a/main | ../w/%s/a/main | none | 3 | 3 | running | none | none | does a |"
                         % (NAME, NAME))
        self.assertEqual([r["used"] for r in programs.status_rows("\n".join(after))], ["3", "0"])

    def test_status_refusals(self):  # ST2-ST6
        text = self.read("status.md")
        for argv in (("zz", "--used", "1"), ("a",), ("a", "--status", "done"), ("a", "--used", "03"),
                     ("a", "--used", "-1"), ("a", "--used", "9" * 601), ("a", "--used", "1", "--used", "2"),
                     ("a", "--block", "x|y"), ("a", "--delivers", "café"), ("a", "--blockers", "R-20261105-aaaa"),
                     ("a", "--pending", "nope")):
            with self.subTest(argv):
                code, out, err = self.cli("status", *argv)
                self.assertEqual((code, out), (1, ""))
                self.assertEqual(self.read("status.md"), text)
        self.assertEqual(self.clean(), "")

    def test_request_new_mints_and_prints_id(self):  # RN1, RN3-RN5, RN12
        code, out, err = self.cli("request new", "--from", "a", "--to", "b", "--file", "b/x.py", "--interface",
                                  "spec.md:1", "--need", "x", "--by", "a")
        self.assertEqual((code, err), (0, ""))
        lines = out.splitlines()
        self.assertEqual(lines[0], "push %s/integration" % NAME)
        rid = lines[-1]
        self.assertRegex(rid, r"^R-[0-9]{8}-[0-9a-z]{4}$")
        rec = load_yaml(os.path.join(self.folder(), "requests", rid + ".yml"))
        self.assertEqual((rec["status"], rec["from_stream"], rec["to_stream"], rec["files"], rec["raised_at"]),
                         ("open", "a", "b", ["b/x.py"], {"sha": git(self.iw, "rev-parse", "HEAD"), "by": "a"}))
        self.assertIn("PASS schema.request", run("check", "schema", "--root", self.iw)[1])
        base = ("--from", "a", "--to", "b", "--file", "b/x.py", "--interface", "spec.md:1", "--need", "x", "--by", "a")
        for name, argv in (("to does not own", ("--from", "b", "--to", "a", "--file", "b/x.py", "--interface", "spec.md:1",
                                                "--need", "x", "--by", "b")),
                           ("from equals to", ("--from", "b", "--to", "b", "--file", "b/x.py", "--interface", "spec.md:1",
                                               "--need", "x", "--by", "b")),
                           ("no file", ("--from", "a", "--to", "b", "--interface", "spec.md:1", "--need", "x", "--by", "a")),
                           ("by unknown", base[:-1] + ("zz",)), ("flag twice", base + ("--need", "y")),
                           ("same file twice", base + ("--file", "b/x.py")), ("dot dot", base[:5] + ("../x",) + base[6:]),
                           ("non ascii", base[:-3] + ("café", "--by", "a"))):
            with self.subTest(name):
                self.assertEqual(self.cli("request new", *argv)[0], 1)
        self.assertEqual(len(os.listdir(os.path.join(self.folder(), "requests"))), 1)

    def test_request_new_collision_redraws(self):  # RN10
        class Rng:
            def __init__(self, seq):
                self.seq = list(seq)

            def choice(self, alphabet):
                return self.seq.pop(0)

        argv = ("--from", "a", "--to", "b", "--file", "b/x.py", "--interface", "spec.md:1", "--need", "x", "--by", "a")
        ids = []
        for _ in range(2):
            with mock.patch.object(program_cli, "_rng", Rng("aaaaaaaabbbb")):
                code, out, err = self.cli("request new", *argv)
            self.assertEqual(code, 0, err)
            ids.append(out.splitlines()[-1])
        self.assertEqual(len(set(ids)), 2)
        self.assertEqual(len(os.listdir(os.path.join(self.folder(), "requests"))), 2)

    def new_request(self):
        code, out, err = self.cli("request new", "--from", "a", "--to", "b", "--file", "b/x.py", "--interface",
                                  "spec.md:1", "--need", "x", "--by", "a")
        self.assertEqual(code, 0, err)
        return out.splitlines()[-1]

    def status_of(self, rid):
        return load_yaml(os.path.join(self.folder(), "requests", rid + ".yml"))["status"]

    def test_request_set_every_pair(self):  # RS1, RS2, RS5, RS13
        allowed = programs.REQUEST_TRANSITIONS
        states = ("open", "accepted", "done", "disputed", "withdrawn")
        for cur in states:
            for new in states:
                with self.subTest("%s->%s" % (cur, new)):
                    rid = self.new_request()
                    path = os.path.join(self.folder(), "requests", rid + ".yml")
                    row = load_yaml(path)
                    row["status"] = cur
                    if cur == "done":
                        row["resolution"] = {"commits": ["a" * 40], "at": "b" * 40, "by": "b"}
                    with open(path, "w", encoding="utf-8") as fh:
                        fh.write(yamlsub.emit(row))
                    extra = ("--commit", git(self.iw, "rev-parse", "HEAD")) if new == "done" else ()
                    extra += ("--decision", DEC) if cur == "disputed" else ()
                    code, out, err = self.cli("request set", rid, "--status", new, "--by", "b", *extra)
                    if new in allowed[cur] and new != "done":
                        if cur == "disputed":
                            self.assertEqual(code, 1)   # DEC is no answered request-dispute decision
                        else:
                            self.assertEqual((code, self.status_of(rid)), (0, new), err)
                    else:
                        self.assertEqual(code, 1)
                        self.assertEqual(self.status_of(rid), cur)

    def test_request_done_needs_commit(self):  # RS2, RS5, RS4
        rid = self.new_request()
        self.assertEqual(self.cli("request set", rid, "--status", "accepted", "--by", "b")[0], 0)
        self.assertEqual(self.cli("request set", rid, "--status", "done", "--by", "b")[0], 1)
        self.assertEqual(self.status_of(rid), "accepted")
        self.assertEqual(self.cli("request set", rid, "--status", "withdrawn", "--commit", "a" * 40, "--by", "b")[0], 1)
        self.assertEqual(self.cli("request set", rid, "--status", "withdrawn", "--decision", DEC, "--by", "b")[0], 1)

    def test_leaving_dispute_needs_decision(self):  # RS6
        d = self.new_request()
        self.assertEqual(self.cli("request set", d, "--status", "disputed", "--by", "b")[0], 0)
        self.assertEqual(self.cli("request set", d, "--status", "accepted", "--by", "b")[0], 1)
        self.assertEqual(self.status_of(d), "disputed")
        self.decision("DEC-20261105-rd3p", "answered", "request-dispute", root=self.iw)
        code, out, err = self.cli("request set", d, "--status", "accepted", "--decision", "DEC-20261105-rd3p", "--by", "b")
        self.assertEqual((code, self.status_of(d), err), (0, "accepted", ""))
        self.assertEqual(self.cli("request set", "R-20261105-zzzz", "--status", "accepted", "--by", "b")[0], 1)

    def test_sync_line_and_merged_record_appended(self):  # SL1-SL12
        head = git(self.iw, "rev-parse", "HEAD")
        main = git(self.work, "rev-parse", "main")
        code, out, err = self.cli("sync-log", "--main", main, "--merged-main", "yes", "--updated", "b", "--updated", "a",
                                  "--tests", "PASS")
        self.assertEqual((code, out, err), (0, "push %s/integration\n" % NAME, ""))
        self.assertEqual(self.read("sync-log.md").split("\n")[1:],
                         ["SYNC integration=%s main=%s merged-main=yes updated=a,b combined=none tests=PASS "
                          "questions=none" % (head, main), ""])
        text = self.read("sync-log.md")
        for name, argv in (("not a commit", ("--main", "1" * 40, "--merged-main", "no", "--tests", "PASS")),
                           ("short sha", ("--main", main[:7], "--merged-main", "no", "--tests", "PASS")),
                           ("merged-main", ("--main", main, "--merged-main", "YES", "--tests", "PASS")),
                           ("tests", ("--main", main, "--merged-main", "no", "--tests", "pass")),
                           ("unknown stream", ("--main", main, "--merged-main", "no", "--tests", "PASS", "--updated", "zz")),
                           ("duplicate", ("--main", main, "--merged-main", "no", "--tests", "PASS", "--combined", "a",
                                          "--combined", "a")),
                           ("unknown question", ("--main", main, "--merged-main", "no", "--tests", "PASS", "--question",
                                                 DEC.replace("bn3p", "zzzz"))),
                           ("missing", ("--merged-main", "no", "--tests", "PASS"))):
            with self.subTest(name):
                self.assertEqual(self.cli("sync-log", *argv)[0], 1)
                self.assertEqual(self.read("sync-log.md"), text)
        code, out, err = self.cli("sync-log", "--main", main, "--merged-main", "no", "--tests", "FAIL", "--question", DEC)
        self.assertEqual(code, 0, err)
        self.assertEqual(len(self.read("sync-log.md").split("\n")), 4)

    def test_merged_refusals_write_nothing(self):  # MG2-MG6, MG17
        text = self.read("merged.md")
        good = ("MERGED pr=7 head=%s merge=%s merged_by=u at=2026-11-01T10:00:00Z final=no stream=a block=A1 approval=host"
                % ("1" * 40, "2" * 40))
        for name, line in (("prose", "hello"), ("checkpoint", "CHECKPOINT x"), ("no block", good.replace(" block=A1", "")),
                           ("no stream", good.replace(" stream=a", "")), ("unknown stream", good.replace("stream=a", "stream=zz")),
                           ("two lines", good + "\n" + good), ("leading space", " " + good), ("fails merged_errors", good)):
            with self.subTest(name):
                code, out, err = self.cli("merged", "--line", line)
                self.assertEqual((code, out), (1, ""))
                self.assertEqual(self.read("merged.md"), text)
        self.assertEqual(self.cli("merged", "--line", good, "--line", good)[0], 1)
        self.assertEqual(self.clean(), "")

    def test_checks_before_io(self):  # PG7: an argv error never reaches git
        with mock.patch("gates.lib.gitinfo._run", side_effect=AssertionError("git ran")):
            self.assertEqual(self.cli("status", "a", "--used", "x")[0], 1)
            self.assertEqual(self.cli("sync-log", "--main", "short", "--merged-main", "no", "--tests", "PASS")[0], 1)


class GitConfigIgnored(After):
    """PG14: colour and abbreviation settings change nothing."""

    def setUp(self):
        super().setUp()
        for k, v in (("color.ui", "always"), ("color.diff", "always"), ("core.abbrev", "7")):
            git(self.work, "config", k, v)

    def test_status_and_request_under_colour_config(self):
        self.assertEqual(self.cli("status", "a", "--used", "4")[0], 0)
        rid = self.new_request()
        self.assertRegex(rid, r"^R-")


if __name__ == "__main__":
    unittest.main()
