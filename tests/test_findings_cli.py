"""Tests for ``findings new | move`` (Task 1d.2) through the production path ``findings_cli.main(argv)`` on temp git
repositories. Records are read back with ``Store.load``; expected values are written by hand from the plan (Task 1d.2,
Task 1b.3), the spec (7.2, 13a) and the block 1d decisions (D-1..D-10, D-19..D-21), never read from the code under
test. Row ids (A1.., N1.., M1.., E1..) are those of the task's input-domain table."""
import contextlib
import datetime
import io
import os
import stat
import sys
import unittest
from unittest import mock

from gates import __main__ as gates_main
from gates import gate_register, gate_schema, producers
from gates.lib import config, decisions, findings, ids
from gates.lib.store import Store
from gates.tools import findings_cli
from tests.helpers import GitIsolatedTestCase, commit_all, git, make_repo, minimal_config, write_record

FTAG = "finding/%d" % findings._schema().version  # Global Constraints "Test fixtures"
DTAG = "decision/%d" % decisions._schema().version
FDIR = ".strict-delivery/state/findings"
DDIR = ".strict-delivery/state/decisions"
REVIEW = "docs/strict-delivery/reviews/p/r.md"
TRANSCRIPT = ".strict-delivery/state/plans/p/mutations/t.txt"
D_OK = "DEC-20261031-k3f9"      # answered, class scope
D_OPEN = "DEC-20261031-m4n5"    # open
D_GRANT = "DEC-20261031-p6q7"   # answered merge-grant
D_WD = "DEC-20261031-r8s9"      # withdrawn
F_OTHER = "F-20261031-k3f9"
STATUSES = ["open", "planned", "in-progress", "fixed-unpinned", "pinned", "deferred", "closed", "merged"]
PATHS_OF = {"open": ["open"], "planned": ["open", "planned"], "in-progress": ["open", "planned", "in-progress"],
            "fixed-unpinned": ["open", "planned", "in-progress", "fixed-unpinned"],
            "pinned": ["open", "planned", "in-progress", "pinned"], "deferred": ["open", "deferred"],
            "closed": ["open", "closed"], "merged": ["open", "planned", "in-progress", "pinned", "merged"]}
# The M3 matrix of the domain table, rows from, columns to (A accepted, T transition, M merged, R resolved).
MATRIX = {
    "open":           "TATTTAAM",
    "planned":        "ATATTATM",
    "in-progress":    "TATAATTM",
    "fixed-unpinned": "TTTTATTM",
    "pinned":         "TTTTTTAM",
    "deferred":       "AATTTTTM",
    "closed":         "RRRRRRRM",
    "merged":         "RRRRRRRM",
}
TEXT_ONLY = "(only U+0020-U+007E)"
TOKEN_ONLY = "(only U+0021-U+007E)"


def dec(id_, status="answered", **over):
    row = {"schema": DTAG, "id": id_, "status": status, "class": "scope", "question": "Keep X?",
           "options": [{"label": "yes", "cost": "none"}, {"label": "no", "cost": "some"}],
           "asked_at": "a1b2c3d", "asked_by": "agent", "topics": [], "applies_to": [], "checked_against": [],
           "effect": "one-off"}
    if status == "answered":
        row.update({"answer": "Yes", "answered_at": {"at": "a1b2c3d", "by": "who"}})
    if status == "withdrawn":
        row["withdrawn"] = {"at": "a1b2c3d", "by": "who", "reason": "dup"}
    row.update(over)
    return row


class FixedRng:
    """Draws the given suffixes in turn (D-6: tests patch ``findings_cli._rng``)."""

    def __init__(self, *suffixes):
        self.chars = list("".join(suffixes))

    def choice(self, seq):
        return self.chars.pop(0)


class Base(GitIsolatedTestCase):
    def setUp(self):
        super().setUp()
        self.root = make_repo(self.work)
        for rel, text in ((REVIEW, "review\n"), (TRANSCRIPT, "t\n"), ("src/a.py", "a\n"), ("notes.txt", "n\n"),
                          ("docs/strict-delivery/plans/x.md", "x\n")):
            self.write(rel, text)
        for d in (dec(D_OK), dec(D_OPEN, "open"), dec(D_GRANT, **{"class": "merge-grant", "plan": "p"}),
                  dec(D_WD, "withdrawn")):
            write_record(self.root, "%s/%s.yml" % (DDIR, d["id"]), d)
        self.sha = commit_all(self.root, "fixture")
        self.today = ids.utc_today().strftime("%Y%m%d")

    # ------------------------------------------------------------ helpers

    def write(self, rel, text):
        path = os.path.join(self.root, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)

    def run_main(self, fn, args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = fn(args)
        return code, out.getvalue(), err.getvalue()

    def cli(self, sub, *args, root=None):
        return self.run_main(findings_cli.main, [sub] + list(args) + ["--root", root or self.root])

    NEW = ("--source", "review", "--severity", "HIGH", "--class", "bug", "--owner-kind", "plan", "--plan", "p",
           "--task", "1d.2", "--by", "controller")

    def new_args(self, **over):
        """The NEW argv with flags replaced (value None drops the flag)."""
        pairs = dict(zip(self.NEW[::2], self.NEW[1::2]))
        for k, v in over.items():
            pairs["--" + k.replace("_", "-")] = v
        out = []
        for k, v in pairs.items():
            if v is not None:
                out += [k, v]
        return out

    def new(self, *extra, **over):
        return self.new_raw(*(self.new_args(**over) + list(extra)))

    def new_raw(self, *args):
        """``new`` with exactly ``args``; it must succeed and print only the id."""
        code, out, err = self.cli("new", *args)
        self.assertEqual((code, err), (0, ""), out)
        self.assertEqual(out.count("\n"), 1)
        return out.strip()

    def cfg(self):
        return config.load(self.root)

    def rec(self, id_):
        return {r.id: r.row for r in Store(self.root, "finding", self.cfg()).load()}[id_]

    def fids(self):
        return sorted(r.id for r in Store(self.root, "finding", self.cfg()).load())

    def snapshot(self):
        """Every file under the root except .git (dotfiles and temp files included), with its bytes."""
        out = {}
        for dirpath, dirnames, filenames in os.walk(self.root):
            if ".git" in dirnames and dirpath == self.root:
                dirnames.remove(".git")
            for name in filenames:
                p = os.path.join(dirpath, name)
                with open(p, "rb") as fh:
                    out[os.path.relpath(p, self.root)] = fh.read()
        return out

    def refused(self, sub, *args, code=1, has=None, root=None):
        """The call exits ``code``, prints nothing on stdout and changes no file; returns stderr."""
        before = self.snapshot()
        got, out, err = self.cli(sub, *args, root=root)
        self.assertEqual(got, code, err)
        self.assertEqual(out, "")
        self.assertEqual(self.snapshot(), before)
        if has is not None:
            self.assertIn(has, err)
        if code == 1:
            self.assertEqual(err.count("\n"), 1, err)
            self.assertTrue(err.startswith("findings %s: " % sub), err)
        return err

    def stored(self, status, id_=F_OTHER, **over):
        """Write a valid finding row at ``status`` by hand and return its id."""
        row = {"schema": FTAG, "id": id_, "status": status, "source": "review", "severity": "HIGH",
               "class": "bug", "siblings": [], "cites": [], "repro": None,
               "owner": {"kind": "plan", "plan": "p", "task": "1d.2"}, "pin": None, "ruling": None,
               "evidence": [], "history": [{"status": s, "sha": self.sha, "by": "agent"} for s in PATHS_OF[status]]}
        if status in ("pinned", "closed", "merged"):
            row["evidence"] = ["%s:%s" % (self.sha, REVIEW)]
        if status in ("pinned", "merged"):
            row["pin"] = {"test": "t", "transcript": "%s:%s" % (self.sha, TRANSCRIPT)}
        if status == "deferred":
            row["ruling"] = D_OK
        if status in ("closed", "merged"):
            row["resolved_by"] = "p"
        row.update(over)
        write_record(self.root, "%s/%s.yml" % (FDIR, id_), row)
        return id_

    def to_flags(self, to):
        """The flags a move to ``to`` needs to be accepted (M4-M8)."""
        if to == "closed":
            return ["--resolved-by", "p", "--evidence", self.sha]
        if to == "deferred":
            return ["--ruling", D_OK]
        if to == "pinned":
            return ["--pin-test", "t", "--pin-transcript", "%s:%s" % (self.sha, TRANSCRIPT),
                    "--evidence", "%s:%s" % (self.sha, REVIEW)]
        return []

    def move(self, id_, to, *extra):
        code, out, err = self.cli("move", id_, "--to", to, "--by", "controller", *extra)
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(out, id_ + "\n")


# ================================================================ A: argv, dispatcher, root, config

class TestArgv(Base):
    def test_a1_dispatcher(self):
        code, out, err = self.run_main(gates_main.main, ["findings", "new"] + self.new_args() + ["--root", self.root])
        self.assertEqual(code, 0, err)
        self.assertEqual(self.fids(), [out.strip()])
        self.assertIn("findings", gates_main.COMMANDS)
        for argv in (["findings"], ["findings", "foo"], ["findings", "-h"], ["findings", "new", "-h"],
                     ["findings", "move", "-h"]):
            with self.subTest(argv=argv):
                before = self.snapshot()
                code, out, err = self.run_main(gates_main.main, argv)
                self.assertEqual((code, out), (2, ""))
                self.assertIn("usage: findings", err)
                self.assertEqual(self.snapshot(), before)

    def test_a2_argv_forms(self):
        with mock.patch.object(sys, "argv", ["findings_cli.py", "new"] + self.new_args() + ["--root", self.root]):
            code, out, err = self.run_main(lambda a: findings_cli.main(), None)
        self.assertEqual(code, 0, err)
        code, out2, err = self.run_main(findings_cli.main, tuple(["new"] + self.new_args() + ["--root", self.root]))
        self.assertEqual(code, 0, err)
        self.assertEqual(self.fids(), sorted([out.strip(), out2.strip()]))

    def test_a3_produces(self):
        self.assertEqual(findings_cli.PRODUCES, ("finding",))
        self.assertEqual(producers.PRODUCER_MODULES[-1], "gates.tools.findings_cli")

    def test_a4_each_required_flag_missing(self):
        for flag in ("source", "severity", "class", "owner_kind", "by"):
            with self.subTest(flag=flag):
                self.refused("new", *self.new_args(**{flag: None}), code=2, has="required")
        F = self.stored("open")
        for args in (["--to", "planned"], ["--by", "c"], []):
            with self.subTest(args=args):
                self.refused("move", F, *args, code=2, has="required")
        self.refused("move", "--to", "planned", "--by", "c", code=2, has="required")

    def test_a5_single_valued_flag_repeated(self):
        for flag, v in (("--source", "a"), ("--severity", "LOW"), ("--class", "c"), ("--owner-kind", "plan"),
                        ("--plan", "p"), ("--task", "t"), ("--number", "1"), ("--parent", F_OTHER),
                        ("--by", "w"), ("--root", self.root)):
            with self.subTest(flag=flag):
                self.refused("new", *(self.new_args() + [flag, v, flag, v]), code=2, has="%s given more than once" % flag)
        F = self.stored("open")
        for flag, v in (("--to", "planned"), ("--by", "w"), ("--ruling", D_OK), ("--pin-test", "t"),
                        ("--pin-transcript", "x"), ("--resolved-by", "p"), ("--root", self.root)):
            with self.subTest(flag=flag):
                args = ["--to", "planned", "--by", "c", flag, v, flag, v]
                self.refused("move", F, *args, code=2, has="%s given more than once" % flag)

    def test_a6_repeatable_flags(self):
        for n in (0, 1, 3):
            with self.subTest(cites=n):
                cites = ["src/a.py:%d@%s" % (i + 1, self.sha) for i in range(n)]
                f = self.new(*[x for c in cites for x in ("--cite", c)])
                self.assertEqual(self.rec(f)["cites"],
                                 [{"file": "src/a.py", "lines": str(i + 1), "sha": self.sha} for i in range(n)])
        ev = [self.sha, "%s:%s" % (self.sha, REVIEW), "notes.txt"]
        for n in (1, 3):
            with self.subTest(evidence=n):
                F = self.stored("open", id_="F-20261031-m%d%d%d" % (n + 2, n + 2, n + 2))
                self.move(F, "closed", "--resolved-by", "p", *[x for e in ev[:n] for x in ("--evidence", e)])
                self.assertEqual(self.rec(F)["evidence"], ev[:n])
        F = self.stored("open", id_="F-20261031-zzzz")
        self.move(F, "planned")
        self.assertEqual(self.rec(F)["evidence"], [])

    def test_a7_each_flag_empty(self):
        for flag in ("source", "class", "by", "task"):
            with self.subTest(flag=flag):
                self.refused("new", *self.new_args(**{flag: ""}), has="--%s: must not be empty" % flag)
        self.refused("new", "--source=", *self.new_args(source=None), has="--source: must not be empty")
        self.refused("new", *self.new_args(plan=""), has="--plan: must match")
        self.refused("new", *self.new_args(severity=""), has="--severity: must be one of")
        self.refused("new", *self.new_args(owner_kind=""), has="--owner-kind: must be one of")
        self.refused("new", *self.new_args(owner_kind="issue", plan=None, task=None, number=""), has="--number")
        self.refused("new", *self.new_args(parent=""), has="--parent: must not be empty")
        self.refused("new", *self.new_args(), "--cite", "", has="--cite 1: must not be empty")
        F = self.stored("open")
        mv = ("move", F, "--to", "closed", "--by", "c", "--resolved-by", "p")
        self.refused(*mv, "--evidence", "", has="--evidence 1: must not be empty")
        self.refused("move", F, "--to", "planned", "--by", "", has="--by: must not be empty")
        self.refused("move", F, "--to", "", "--by", "c", has="--to: must be one of")
        self.refused("move", F, "--to", "closed", "--by", "c", "--resolved-by", "", "--evidence", self.sha,
                     has="--resolved-by: must not be empty")
        self.refused("move", F, "--to", "deferred", "--by", "c", "--ruling", "", has="--ruling: must not be empty")
        self.refused("move", F, "--to", "pinned", "--by", "c", "--pin-test", "", "--pin-transcript", "x",
                     has="--pin-test: must not be empty")
        self.refused("move", F, "--to", "pinned", "--by", "c", "--pin-test", "t", "--pin-transcript", "",
                     has="--pin-transcript: must not be empty")
        self.refused("move", "", "--to", "planned", "--by", "c", has="ID: must not be empty")

    def test_a8_a9_dash_values(self):
        self.refused("new", *self.new_args(source="-x"), code=2, has="expected one argument")
        f = self.new_raw("--source=-x", "--class=a=b", *self.new_args(source=None, **{"class": None}))
        self.assertEqual((self.rec(f)["source"], self.rec(f)["class"]), ("-x", "a=b"))

    def test_a10_abbreviations(self):
        args = self.new_args(severity=None) + ["--sev", "LOW"]
        f = self.new_raw(*args)
        self.assertEqual(self.rec(f)["severity"], "LOW")
        self.refused("new", *self.new_args(), "--p", "x", code=2, has="ambiguous option")
        self.refused("new", *self.new_args(), "--ro", self.root, code=2, has="--root given more than once")

    def test_a11_unknown_flag_and_extra_positional(self):
        self.refused("new", *self.new_args(), "--foo", "x", code=2)
        self.refused("new", *self.new_args(), "extra", code=2)
        F = self.stored("open")
        self.refused("move", F, F, "--to", "planned", "--by", "c", code=2)

    def test_a12_root(self):
        args = ["new"] + self.new_args()
        with mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": self.root}):
            code, out, err = self.run_main(findings_cli.main, args)
        self.assertEqual(code, 0, err)
        plain = os.path.join(self.tmp, "plain")
        os.mkdir(plain)
        sub = os.path.join(self.root, "src")
        for name, root, has in (("missing", os.path.join(self.tmp, "nope"), "/strict-delivery:init"),
                                ("file", os.path.join(self.root, "notes.txt"), "/strict-delivery:init"),
                                ("plain", plain, "/strict-delivery:init"),
                                ("subdirectory", sub, "root must be the repository top level")):
            with self.subTest(root=name):
                self.refused("new", *self.new_args(), root=root, has=has)
                self.refused("move", F_OTHER, "--to", "planned", "--by", "c", root=root, has=has)
        with mock.patch.dict(os.environ, {"PATH": self.tmp}):
            self.refused("new", *self.new_args(), has="git")

    def test_a13_config(self):
        os.chmod(self.root, 0o755)
        cfgpath = os.path.join(self.root, ".strict-delivery", "config.yml")
        with open(cfgpath, "w", encoding="utf-8") as fh:
            fh.write("schema: [\n")
        self.refused("new", *self.new_args(), has="config.yml")
        cfg = minimal_config()
        cfg["ids"] = {"finding": "XF"}
        write_record(self.root, ".strict-delivery/config.yml", cfg)
        f = self.new()
        self.assertEqual(ids.id_problem(f, "XF"), "")
        self.assertTrue(f.startswith("XF-"))

    def test_a13_config_missing(self):
        git(self.root, "rm", "-q", ".strict-delivery/config.yml")
        self.refused("new", *self.new_args(), has=".strict-delivery/config.yml: missing; run /strict-delivery:init")

    def test_a14_git_state(self):
        git(self.root, "checkout", "-q", "--detach")
        f = self.new()
        self.assertEqual(self.rec(f)["history"][0]["sha"], self.sha)
        git(self.root, "checkout", "-q", "--orphan", "unborn")
        self.refused("new", *self.new_args(), has="git rev-parse HEAD failed (exit 128)")
        self.refused("move", f, "--to", "planned", "--by", "c", has="git rev-parse HEAD failed (exit 128)")

    def test_a15_write_failures_leave_nothing(self):
        F = self.stored("open")
        commit_all(self.root, "f")
        d = os.path.join(self.root, *FDIR.split("/"))
        os.chmod(d, 0o555)
        self.addCleanup(os.chmod, d, 0o755)
        self.refused("new", *self.new_args(), has="cannot create")
        self.refused("move", F, "--to", "planned", "--by", "c", has="cannot write")
        self.assertEqual(git(self.root, "status", "--porcelain", "--untracked-files=all"), "")


# ================================================================ N: new

class TestNew(Base):
    def test_n1_owner_kind_combinations(self):
        values = {"--plan": "p", "--task": "1d.2", "--number": "7"}
        accepted = {("plan", ("--plan", "--task")): {"kind": "plan", "plan": "p", "task": "1d.2"},
                    ("issue", ("--number",)): {"kind": "issue", "number": 7},
                    ("roadmap", ("--plan",)): {"kind": "roadmap", "plan": "p"}}
        subsets = [(), ("--plan",), ("--task",), ("--number",), ("--plan", "--task"), ("--plan", "--number"),
                   ("--task", "--number"), ("--plan", "--task", "--number")]
        for kind in ("plan", "issue", "roadmap", "PLAN", "other", ""):
            for sub in subsets:
                with self.subTest(kind=kind, flags=sub):
                    args = self.new_args(owner_kind=kind, plan=None, task=None)
                    for flag in sub:
                        args += [flag, values[flag]]
                    if (kind, sub) in accepted:
                        f = self.new_raw(*args)
                        self.assertEqual(self.rec(f)["owner"], accepted[(kind, sub)])
                    else:
                        self.refused("new", *args)

    def test_n1_plan_owner_needs_task(self):  # plan test_new_plan_owner_needs_task, F7
        self.refused("new", *self.new_args(task=None), has="owner.task")

    def test_n2_number(self):
        ok = {"1": 1, "42": 42, "9" * 1000: int("9" * 1000)}
        bad = ["0", "-1", "abc", "1.0", "+5", " 5", "5_0", "05", "0x5", "٥", "\U00016AC1", "9" * 1001,
               "9" * 4300, "9" * 4301, "５"]
        base = self.new_args(owner_kind="issue", plan=None, task=None)
        for v, want in ok.items():
            with self.subTest(v=v[:8]):
                f = self.new_raw(*base, "--number=" + v)
                self.assertEqual(self.rec(f)["owner"]["number"], want)
        for v in bad:
            with self.subTest(v=v[:8]):
                self.refused("new", *base, "--number=" + v,
                             has="--number: must be a positive decimal integer of at most 1000 ASCII digits")

    def test_n3_n4_number_skeleton_same_bytes_on_every_interpreter(self):
        base = self.new_args(owner_kind="issue", plan=None, task=None)
        want = "findings new: --number: must be a positive decimal integer of at most 1000 ASCII digits\n"
        for v in ("9" * 4300, "9" * 4301, "\U00016AC1", "٥", "５"):
            with self.subTest(v=v[:8]):
                self.assertEqual(self.refused("new", *base, "--number=" + v), want)

    def test_n5_severity(self):
        for sev in ("CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"):
            with self.subTest(sev=sev):
                self.assertEqual(self.rec(self.new(severity=sev))["severity"], sev)
        for sev in ("low", "Low", "critical", "URGENT", ""):
            with self.subTest(sev=sev):
                self.refused("new", *self.new_args(severity=sev),
                             has="--severity: must be one of CRITICAL, HIGH, MEDIUM, LOW, INFO")

    def test_n6_n14_free_text(self):
        for flag in ("source", "class", "by"):
            for v in ("plain text", "a: b", "# x", "~!@{}[]"):
                with self.subTest(flag=flag, v=v):
                    row = self.rec(self.new(**{flag: v}))
                    got = row["history"][0]["by"] if flag == "by" else row[flag]
                    self.assertEqual(got, v)
            for v, cp in (("a\nb", "U+000A"), ("a\tb", "U+0009"), ("a\x00b", "U+0000"), ("a\x7fb", "U+007F"),
                          ("a\x85b", "U+0085"), ("aౝ", "U+0C5D"), ("a\U0001F6DD", "U+1F6DD"),
                          ("é", "U+00E9")):
                with self.subTest(flag=flag, cp=cp):
                    self.refused("new", *self.new_args(**{flag: v}), has="--%s: %s is not allowed %s"
                                 % (flag, cp, TEXT_ONLY))
            for v in (" a", "a ", " "):
                with self.subTest(flag=flag, v=v):
                    self.refused("new", *self.new_args(**{flag: v}),
                                 has="--%s: must not start or end with a space" % flag)
        long = "x" * 10000
        self.assertEqual(self.rec(self.new(**{"class": long}))["class"], long)

    def test_n7_text_skeleton_same_bytes_on_every_interpreter(self):
        for v in ("aౝ", "- aౝ"):
            with self.subTest(v=v):
                self.assertEqual(self.refused("new", *self.new_args(**{"class": v})),
                                 "findings new: --class: U+0C5D is not allowed (only U+0020-U+007E)\n")

    def test_n8_plan_and_task(self):
        for v in ("p", "2026-10-31-x", "a.b_c"):
            with self.subTest(plan=v):
                self.assertEqual(self.rec(self.new(plan=v))["owner"]["plan"], v)
        for v in ("a/b", "a b", "P", ".x", "é", "_a"):
            with self.subTest(plan=v):
                self.refused("new", *self.new_args(plan=v), has="--plan: must match [a-z0-9][a-z0-9._-]*")
        self.assertEqual(self.rec(self.new(task="Task 1d.2"))["owner"]["task"], "Task 1d.2")
        self.refused("new", *self.new_args(task="é"), has="--task: U+00E9 is not allowed")

    def test_n9_cite_forms(self):
        s, full = self.sha[:12], self.sha
        ok = {"src/a.py:10@" + s: ("src/a.py", "10", s), "src/a.py:10-20@" + full: ("src/a.py", "10-20", full),
              "a@b.py:1@" + s: ("a@b.py", "1", s), "a:b.py:1@" + s: ("a:b.py", "1", s),
              "src/a.py:5-5@" + s: ("src/a.py", "5-5", s)}
        for v, (file, lines, sha) in ok.items():
            with self.subTest(v=v):
                f = self.new("--cite", v)
                self.assertEqual(self.rec(f)["cites"], [{"file": file, "lines": lines, "sha": sha}])
        form, path = "expected FILE:LINES@SHA", "FILE must be a normalised repo-relative path"
        lines_bad, commit = "LINES must be N or N-M (1 to 9 digits each)", "is not a commit (7-40 lowercase hex)"
        bad = {"src/a.py10" + s: form, "src/a.py@" + s: form, "src/a.py:10": form,
               "src/a.py:@" + s: lines_bad, ":10@" + s: path, "src/a.py:10@": commit,
               "src/a.py:10@" + s.upper(): commit, "src/a.py:10@" + s[:6]: commit,
               "src/a.py:10@" + full + "a": commit, "src/a.py:10@HEAD": commit, "src/a.py:10@" + "f" * 12: commit,
               "/abs:1@" + s: path, "../x:1@" + s: path, "./a:1@" + s: path, "a//b:1@" + s: path,
               "src/a.py:0@" + s: lines_bad, "src/a.py:01@" + s: lines_bad, "src/a.py:1-@" + s: lines_bad,
               "src/a.py:20-10@" + s: "LINES start is after its end", "src/a.py:1 @" + s: "U+0020",
               "src/a.py:1\x00@" + s: "U+0000", "src/a.py:" + "9" * 10 + "@" + s: lines_bad}
        for v, has in bad.items():
            with self.subTest(v=v[:30]):
                self.refused("new", *self.new_args(), "--cite", "src/a.py:1@" + s, "--cite", v,
                             has="--cite 2: " if has != "U+0020" else "--cite 2: U+0020 is not allowed " + TOKEN_ONLY)
                self.refused("new", *self.new_args(), "--cite", v, has=has)
        self.refused("new", *self.new_args(), "--cite", "src/a.py:1@" + s, "--cite", "src/a.py:1@" + s,
                     has="--cite: src/a.py:1@%s given more than once" % s)  # D-10

    def test_n10_n11_cite_lines_skeleton_same_bytes_on_every_interpreter(self):
        s = self.sha[:12]
        cases = {"9" * 4300: "findings new: --cite 1: LINES must be N or N-M (1 to 9 digits each)\n",
                 "9" * 4301: "findings new: --cite 1: LINES must be N or N-M (1 to 9 digits each)\n",
                 "١٠": "findings new: --cite 1: U+0661 is not allowed (only U+0021-U+007E)\n",
                 "\U00016AC1": "findings new: --cite 1: U+16AC1 is not allowed (only U+0021-U+007E)\n"}
        for lines, want in cases.items():
            with self.subTest(lines=lines[:6]):
                self.assertEqual(self.refused("new", *self.new_args(), "--cite", "a.py:%s@%s" % (lines, s)), want)

    def test_n12_parent(self):
        f = self.new()
        self.assertNotIn("parent", self.rec(f))
        child = self.new(parent=f)
        self.assertEqual(self.rec(child)["parent"], f)
        closed = self.stored("closed")
        commit_all(self.root, "closed parent")
        self.refused("new", *self.new_args(parent=closed), has="parent: %s is resolved but this finding is not"
                     % closed)
        self.refused("new", *self.new_args(parent="F-20261031-zzzz"), has="parent: F-20261031-zzzz has no record")
        for bad in ("F-2026-xx", D_OK):
            with self.subTest(parent=bad):
                self.refused("new", *self.new_args(parent=bad), has="parent:")
        # an epic error already in the tree is not the new row's: new still writes (only introduced errors refuse)
        self.stored("open", id_="F-20261031-m4n5", parent=closed)
        self.assertNotIn("parent", self.rec(self.new()))
        self_id = "F-%s-wxyz" % self.today
        with mock.patch.object(findings_cli, "_rng", FixedRng("wxyz")):
            self.refused("new", *self.new_args(parent=self_id), has="parent: a finding cannot be its own parent")

    def test_n13_n15_written_record_shape(self):
        f = self.new("--cite", "src/a.py:1-2@" + self.sha)
        head = git(self.root, "rev-parse", "HEAD")
        self.assertEqual(len(head), 40)
        want = {"schema": FTAG, "id": f, "status": "open", "source": "review", "severity": "HIGH", "class": "bug",
                "siblings": [], "cites": [{"file": "src/a.py", "lines": "1-2", "sha": self.sha}], "repro": None,
                "owner": {"kind": "plan", "plan": "p", "task": "1d.2"}, "pin": None, "ruling": None, "evidence": [],
                "history": [{"status": "open", "sha": head, "by": "controller"}]}
        row = self.rec(f)
        self.assertEqual(row, want)
        self.assertEqual(list(row), list(want))
        self.assertEqual(self.rec(self.new())["cites"], [])

    def test_n16_minting(self):
        self.assertFalse(os.path.exists(os.path.join(self.root, *FDIR.split("/"))))
        f = self.new()  # the findings directory is created
        self.assertEqual(ids.id_problem(f, "F"), "")
        self.assertEqual(f.split("-")[1], self.today)
        taken = "F-%s-k3f9" % self.today
        self.stored("open", id_=taken)
        with mock.patch.object(findings_cli, "_rng", FixedRng("k3f9", "m4n5")):
            got = self.new()
        self.assertEqual(got, "F-%s-m4n5" % self.today)
        self.assertEqual(self.rec(got)["id"], got)

    def test_n16_mint_uses_utc_date(self):
        with mock.patch.object(ids, "utc_today", return_value=datetime.date(2030, 2, 28)):
            f = self.new()
        self.assertTrue(f.startswith("F-20300228-"))

    def test_n17_store_states(self):
        self.new()
        d = os.path.join(self.root, *FDIR.split("/"))
        cases = [("bad.yml", "a: [\n", "line"), ("x.txt", "x\n", "not a regular file named <id>.yml")]
        for name, text, has in cases:
            with self.subTest(name=name):
                path = os.path.join(d, name)
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(text)
                self.refused("new", *self.new_args(), has=has)
                os.rename(path, os.path.join(self.tmp, name))  # moved out of the tree
        other = os.path.join(self.tmp, "real")
        os.rename(d, other)
        os.symlink(other, d)
        self.refused("new", *self.new_args(), has="is a symlink")

    def test_n17_decisions_dir_missing(self):
        root = os.path.join(self.tmp, "bare")
        os.mkdir(root)
        make_repo(root)
        code, out, err = self.cli("new", *self.new_args(), root=root)
        self.assertEqual((code, err), (0, ""))

    def test_n18_render_refusal_and_regenerate_failure(self):
        self.stored("open", severity="URGENT")
        self.refused("new", *self.new_args(), has="severity")
        os.rename(os.path.join(self.root, *FDIR.split("/"), F_OTHER + ".yml"), os.path.join(self.tmp, "x.yml"))
        os.makedirs(os.path.join(self.root, *FDIR.split("/"), "index.yml"))
        code, out, err = self.cli("new", *self.new_args())
        f = out.strip()
        self.assertEqual(code, 1)
        self.assertEqual(out, f + "\n")
        self.assertEqual(self.fids(), [f])
        self.assertEqual(err, "findings new: %s written; indexes not regenerated: %s/index.yml: is a directory; "
                              "run python3 -m gates index\n" % (f, FDIR))

    def test_n19_output_and_regenerate(self):
        code, out, err = self.cli("new", *self.new_args())
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(out, self.fids()[0] + "\n")
        idx = os.path.join(self.root, *FDIR.split("/"), "index.yml")
        with open(idx, encoding="utf-8") as fh:
            self.assertIn(self.fids()[0], fh.read())


# ================================================================ M: move

class TestMove(Base):
    def test_m1_id(self):
        self.refused("move", "F-20261031-zzzz", "--to", "planned", "--by", "c", has="no finding F-20261031-zzzz")
        for bad in ("F-x", D_OK):
            with self.subTest(id=bad):
                self.refused("move", bad, "--to", "planned", "--by", "c", has="cannot use id %s" % bad)
        self.refused("move", "-x", "--to", "planned", "--by", "c", code=2)

    def test_m2_to_values(self):
        F = self.stored("open")
        for v in ("Open", "done", ""):
            with self.subTest(to=v):
                self.refused("move", F, "--to", v, "--by", "c", has="--to: must be one of open, planned, "
                             "in-progress, fixed-unpinned, pinned, deferred, closed, merged")

    def check_cell(self, frm, to, verdict, F):
        args = ("move", F, "--to", to, "--by", "controller") + tuple(self.to_flags(to))
        if verdict == "A":
            before = self.rec(F)
            code, out, err = self.cli(*args)
            self.assertEqual((code, out, err), (0, F + "\n", ""))
            after = self.rec(F)
            self.assertEqual(after["status"], to)
            self.assertEqual(after["history"], before["history"] + [
                {"status": to, "sha": git(self.root, "rev-parse", "HEAD"), "by": "controller"}])
        else:
            has = {"T": "%s -> %s is not a legal transition" % (frm, to),
                   "M": "--to merged: merged is set only by the cleanup step",
                   "R": "%s is %s: a resolved finding is never changed" % (F, frm)}[verdict]
            self.refused(*args, has=has)

    def test_m3_matrix_all_64_pairs(self):
        ids_ = {s: "F-20261031-%s" % ("abcdefgh"[i] * 4) for i, s in enumerate(STATUSES[:-1])}
        for s, i in ids_.items():
            self.stored(s, id_=i)
        commit_all(self.root, "rows")
        for frm in STATUSES[:-1]:
            for j, to in enumerate(STATUSES):
                with self.subTest(frm=frm, to=to):
                    F = ids_[frm]
                    path = os.path.join(self.root, *FDIR.split("/"), F + ".yml")
                    with open(path, "rb") as fh:
                        orig = fh.read()
                    self.check_cell(frm, to, MATRIX[frm][j], F)
                    with open(path, "wb") as fh:  # back to the from-state for the next column
                        fh.write(orig)

    def test_m3_matrix_merged_row(self):  # a hand-written merged row (never valid): R, and M for --to merged
        F = self.stored("merged")
        for j, to in enumerate(STATUSES):
            with self.subTest(to=to):
                self.check_cell("merged", to, MATRIX["merged"][j], F)

    def test_m3_plan_lifecycle_to_closed(self):  # plan test_move_through_lifecycle_to_closed
        f = self.new()
        for to in ("planned", "in-progress", "pinned", "closed"):
            self.move(f, to, *self.to_flags(to))
        row = self.rec(f)
        self.assertEqual([h["status"] for h in row["history"]], ["open", "planned", "in-progress", "pinned", "closed"])
        self.assertEqual(row["resolved_by"], "p")

    def test_m4_resolved_by(self):
        F = self.stored("open")
        self.refused("move", F, "--to", "closed", "--by", "c", "--evidence", self.sha,
                     has="--resolved-by: required with --to closed")
        for to in ("planned", "deferred"):
            with self.subTest(to=to):
                self.refused("move", F, "--to", to, "--by", "c", "--resolved-by", "p", *self.to_flags(to)[:2],
                             has="--resolved-by is given only with --to closed")
        for v in ("a/b", "a b"):
            with self.subTest(v=v):
                self.refused("move", F, "--to", "closed", "--by", "c", "--resolved-by", v, "--evidence", self.sha,
                             has="resolved_by: must not contain '/' or whitespace")

    def test_m5_evidence_forms(self):
        F = self.stored("open")
        commit_all(self.root, "row")
        tree = git(self.root, "rev-parse", "HEAD^{tree}")
        blob = git(self.root, "rev-parse", "HEAD:notes.txt")
        ok = [self.sha, self.sha[:12], "%s:%s" % (self.sha, REVIEW), "notes.txt", "src/a.py"]
        bad = {tree: "is not a commit", blob: "is not a commit", "f" * 12: "is not a commit",
               "%s:missing.txt" % self.sha: "is not a regular file", "%s:src" % self.sha: "is not a regular file",
               "untracked.txt": "is not a tracked regular file", "/abs": "normalised", "../x": "normalised",
               "a#b": "normalised", FDIR + "/x.yml": "is a finding record; cite it as <sha>:<path>",
               "docs/strict-delivery/specs/s.md": "cleaned", "docs/strict-delivery/plans/x.md": "cleaned",
               TRANSCRIPT: "cleaned", REVIEW: "cleaned", ".strict-delivery/state/programs/p.md": "cleaned",
               ".strict-delivery/state/claims/c.yml": "cleaned"}
        for e in ok:
            with self.subTest(e=e):
                path = os.path.join(self.root, *FDIR.split("/"), F + ".yml")
                with open(path, "rb") as fh:
                    orig = fh.read()
                self.move(F, "closed", "--resolved-by", "p", "--evidence", e)
                self.assertEqual(self.rec(F)["evidence"], [e])
                with open(path, "wb") as fh:
                    fh.write(orig)
        for e, has in bad.items():
            with self.subTest(e=e):
                self.refused("move", F, "--to", "closed", "--by", "c", "--resolved-by", "p", "--evidence", e,
                             has=has)
        self.refused("move", F, "--to", "closed", "--by", "c", "--resolved-by", "p", "--evidence", "né",
                     has="--evidence 1: U+00E9 is not allowed " + TOKEN_ONLY)

    def test_m5_plain_review_path_refused(self):  # plan test_move_plain_review_path_evidence_refused, OQ-15
        F = self.stored("open")
        self.refused("move", F, "--to", "closed", "--by", "c", "--resolved-by", "p", "--evidence", REVIEW,
                     has="is under docs/strict-delivery/reviews, which is cleaned")

    def test_m5_plain_findings_path_refused(self):  # plan test_move_plain_findings_path_evidence_refused, Q-plan-5
        F = self.stored("open")
        self.refused("move", F, "--to", "closed", "--by", "c", "--resolved-by", "p", "--evidence",
                     "%s/%s.yml" % (FDIR, F), has="is a finding record")

    def test_m6_evidence_appends(self):
        F = self.stored("pinned")
        commit_all(self.root, "row")
        self.move(F, "closed", "--resolved-by", "p", "--evidence", "notes.txt", "--evidence", self.sha)
        self.assertEqual(self.rec(F)["evidence"], ["%s:%s" % (self.sha, REVIEW), "notes.txt", self.sha])
        G = self.stored("open", id_="F-20261031-m4n5")
        self.refused("move", G, "--to", "closed", "--by", "c", "--resolved-by", "p",
                     has="evidence: a closed finding needs at least one entry")
        H = self.stored("in-progress", id_="F-20261031-p6q7", evidence=[self.sha])
        self.refused("move", H, "--to", "pinned", "--by", "c", "--pin-test", "t", "--pin-transcript",
                     "%s:%s" % (self.sha, TRANSCRIPT), "--evidence", "%s:%s" % (self.sha, REVIEW),
                     "--evidence", self.sha, has="--evidence: %s given more than once" % self.sha)

    def test_m7_pin(self):
        F = self.stored("in-progress")
        review = ["--evidence", "%s:%s" % (self.sha, REVIEW)]
        tr = "%s:%s" % (self.sha, TRANSCRIPT)
        self.refused("move", F, "--to", "pinned", "--by", "c", *review, has="pin: a pinned finding needs a pin")
        self.refused("move", F, "--to", "pinned", "--by", "c", "--pin-test", "t", *review,
                     has="--pin-test and --pin-transcript go together")
        self.refused("move", F, "--to", "pinned", "--by", "c", "--pin-transcript", tr, *review,
                     has="--pin-test and --pin-transcript go together")
        self.refused("move", F, "--to", "fixed-unpinned", "--by", "c", "--pin-test", "t", "--pin-transcript", tr,
                     has="--pin-test and --pin-transcript are given only with --to pinned")
        self.refused("move", F, "--to", "pinned", "--by", "c", "--pin-test", "t", "--pin-transcript", tr,
                     has="evidence: a pinned finding needs a review report")
        other = ".strict-delivery/state/plans/q/mutations/t.txt"
        self.write(other, "t\n")
        sha2 = commit_all(self.root, "q")
        for t, has in ((TRANSCRIPT, "pin.transcript: must be <sha>:<normalised repo-relative path>"),
                       ("%s:%s" % (sha2, other), "must be under .strict-delivery/state/plans/p/mutations/"),
                       ("%s:notes.txt" % sha2, "must be under")):
            with self.subTest(t=t):
                self.refused("move", F, "--to", "pinned", "--by", "c", "--pin-test", "t", "--pin-transcript", t,
                             *review, has=has)
        self.refused("move", F, "--to", "pinned", "--by", "c", "--pin-test", "té", "--pin-transcript", tr,
                     *review, has="--pin-test: U+00E9 is not allowed")
        self.move(F, "pinned", "--pin-test", "tests.test_x.T.test_y", "--pin-transcript", tr, *review)
        self.assertEqual(self.rec(F)["pin"], {"test": "tests.test_x.T.test_y", "transcript": tr})
        G = self.stored("in-progress", id_="F-20261031-m4n5", owner={"kind": "issue", "number": 3})
        self.move(G, "pinned", "--pin-test", "t", "--pin-transcript", "%s:%s" % (sha2, other), *review)
        H = self.stored("in-progress", id_="F-20261031-p6q7", owner={"kind": "roadmap", "plan": "p"})
        self.refused("move", H, "--to", "pinned", "--by", "c", "--pin-test", "t", "--pin-transcript",
                     "%s:notes.txt" % sha2, *review, has="must be under .strict-delivery/state/plans/<plan>/mutations/")

    def test_m8_ruling(self):  # plan test_move_deferred_needs_answered_ruling
        F = self.stored("open")
        self.refused("move", F, "--to", "deferred", "--by", "c", has="ruling: a deferred finding needs a ruling")
        for d, has in ((D_OPEN, "is not an answered, valid decision of a class other than merge-grant"),
                       (D_WD, "is not an answered"), (D_GRANT, "is not an answered"),
                       ("DEC-20261031-zzzz", "ruling: no decision record for DEC-20261031-zzzz"),
                       ("DEC-x", "ruling:")):
            with self.subTest(ruling=d):
                self.refused("move", F, "--to", "deferred", "--by", "c", "--ruling", d, has=has)
        self.refused("move", F, "--to", "planned", "--by", "c", "--ruling", D_OK,
                     has="--ruling is given only with --to deferred")
        newer = "DEC-20261031-wxyz"
        write_record(self.root, "%s/%s.yml" % (DDIR, newer), dec(newer, supersedes=D_OK))
        self.move(F, "deferred", "--ruling", D_OK)  # superseded but answered (Q-1b3-1 (a))
        self.assertEqual(self.rec(F)["ruling"], D_OK)
        self.move(F, "open")
        self.assertEqual(self.rec(F)["ruling"], D_OK)  # kept when leaving deferred (D-21)
        self.move(F, "deferred", "--ruling", newer)
        self.assertEqual(self.rec(F)["ruling"], newer)

    def test_m9_m10_history_and_fields(self):
        F = self.stored("in-progress", cites=[{"file": "src/a.py", "lines": "1", "sha": self.sha}])
        before = self.rec(F)
        head = commit_all(self.root, "row")
        tr = "%s:%s" % (self.sha, TRANSCRIPT)
        self.move(F, "pinned", "--pin-test", "t", "--pin-transcript", tr, "--evidence", "%s:%s" % (self.sha, REVIEW))
        want = dict(before)
        want.update({"status": "pinned", "pin": {"test": "t", "transcript": tr},
                     "evidence": ["%s:%s" % (self.sha, REVIEW)],
                     "history": before["history"] + [{"status": "pinned", "sha": head, "by": "controller"}]})
        self.assertEqual(self.rec(F), want)
        self.move(F, "closed", "--resolved-by", "plan-x", "--evidence", self.sha)
        want2 = dict(want)
        want2.update({"status": "closed", "resolved_by": "plan-x", "evidence": want["evidence"] + [self.sha],
                      "history": want["history"] + [{"status": "closed", "sha": head, "by": "controller"}]})
        self.assertEqual(self.rec(F), want2)

    def test_m11_epic_and_validation_order(self):
        P = self.stored("pinned")
        C = self.stored("open", id_="F-20261031-m4n5", parent=P)
        commit_all(self.root, "epic")
        self.refused("move", P, "--to", "closed", "--by", "c", "--resolved-by", "p",
                     has="parent: %s is resolved but this finding is not" % P)
        self.move(C, "closed", "--resolved-by", "p", "--evidence", self.sha)
        self.move(P, "closed", "--resolved-by", "p")

    def test_m12_resolved_or_invalid_stored_record(self):  # plan test_move_resolved_record_refused
        F = self.stored("closed")
        self.refused("move", F, "--to", "open", "--by", "c", has="%s is closed: a resolved finding is never changed" % F)
        G = self.stored("open", id_="F-20261031-m4n5", severity="URGENT")
        self.refused("move", G, "--to", "planned", "--by", "c", has="severity")
        H = self.stored("open", id_="F-20261031-p6q7")
        write_record(self.root, "%s/%s.yml" % (FDIR, H), dict(self.rec(H), status=["open"]))  # non-string status
        self.refused("move", H, "--to", "planned", "--by", "c", has="-> planned is not a legal transition")
        write_record(self.root, "%s/%s.yml" % (FDIR, H), dict(self.rec(H), status="open", evidence="x"))
        self.refused("move", H, "--to", "planned", "--by", "c")  # non-list evidence: refused (render), no crash

    def test_m12_stored_illegal_history_refused(self):  # the updated row's whole history is checked (D-21)
        F = self.stored("planned")
        row = self.rec(F)
        row["history"] = [{"status": s, "sha": self.sha, "by": "agent"} for s in ("open", "in-progress", "planned")]
        write_record(self.root, "%s/%s.yml" % (FDIR, F), row)
        self.refused("move", F, "--to", "in-progress", "--by", "c",
                     has="history.1.status: open -> in-progress is not a legal transition")

    def test_m12_to_merged_refused(self):  # plan test_move_to_merged_refused, OQ-6
        for status in ("closed", "pinned"):
            with self.subTest(status=status):
                F = self.stored(status, id_="F-20261031-%s" % ("m4n5" if status == "closed" else "p6q7"))
                self.refused("move", F, "--to", "merged", "--by", "c", "--resolved-by", "p", has="cleanup step")

    def test_m13_store_git_regenerate(self):
        F = self.stored("open")
        commit_all(self.root, "row")
        os.makedirs(os.path.join(self.root, *FDIR.split("/"), "index.yml"))
        code, out, err = self.cli("move", F, "--to", "planned", "--by", "c")
        self.assertEqual((code, out), (1, F + "\n"))
        self.assertEqual(err, "findings move: %s written; indexes not regenerated: %s/index.yml: is a directory; "
                              "run python3 -m gates index\n" % (F, FDIR))
        self.assertEqual(self.rec(F)["status"], "planned")
        bad = os.path.join(self.root, *FDIR.split("/"), "bad.yml")
        with open(bad, "w", encoding="utf-8") as fh:
            fh.write("a: [\n")
        self.refused("move", F, "--to", "open", "--by", "c", has="line")

    def test_m14_output(self):
        F = self.stored("open")
        code, out, err = self.cli("move", F, "--to", "planned", "--by", "c")
        self.assertEqual((code, out, err), (0, F + "\n", ""))

    def test_m13_render_refusal_before_write(self):  # D-7: another record the index refuses blocks the move
        F = self.stored("open")
        self.stored("open", id_="F-20261031-m4n5", severity="URGENT")
        self.refused("move", F, "--to", "planned", "--by", "c",
                     has="F-20261031-m4n5.yml: severity: must be one of CRITICAL, HIGH, MEDIUM, LOW, INFO")


# ================================================================ E: end state, skeleton

class TestEnd(Base):
    def test_e1_gates_pass_after_cli_lifecycle(self):  # plan test_gates_pass_after_cli_lifecycle
        f = self.new("--cite", "src/a.py:1@" + self.sha)
        for to in ("planned", "in-progress", "pinned", "closed"):
            self.move(f, to, *self.to_flags(to))
        g = self.new(owner_kind="issue", plan=None, task=None, number="5")
        self.move(g, "deferred", "--ruling", D_OK)
        commit_all(self.root, "records")
        for gate in (gate_register, gate_schema):
            with self.subTest(gate=gate.__name__):
                res = gate.check(["--root", self.root])
                self.assertTrue(res.ok(), res.render(False))

    def test_e2_e3_no_version_sensitive_names_in_the_module(self):
        with open(findings_cli.__file__, encoding="utf-8") as fh:
            src = fh.read()
        for name in ("ExceptionGroup", "isdigit", "isdecimal", "isnumeric", "isalnum", "isspace", "isprintable",
                     "casefold", ".lower(", ".upper(", "unicodedata", "\\d", "\\w", "\\s"):
            with self.subTest(name=name):
                self.assertNotIn(name, src)


# ================================================================ D-32: duplicates compare referents (F-1d2-r1)

class TestDuplicateReferents(Base):
    """D-10 as settled by D-32: one referent under two spellings is a duplicate (exit 1, nothing written); the
    exact-text duplicate still refuses; distinct referents are accepted, in argv order, stored as typed."""

    def second_commit(self):
        self.write("src/b.py", "b\n")
        return commit_all(self.root, "second")

    def closing(self, F, *evidence):
        return ["move", F, "--to", "closed", "--by", "c", "--resolved-by", "p"] + \
            [x for e in evidence for x in ("--evidence", e)]

    def test_d32_cite_same_referent_refused(self):
        s7, s12, full = self.sha[:7], self.sha[:12], self.sha
        pairs = [("src/a.py:1@" + s7, "src/a.py:1@" + full), ("src/a.py:1@" + full, "src/a.py:1@" + s12),
                 ("src/a.py:1@" + s7, "src/a.py:1@" + s12), ("src/a.py:3@" + s7, "src/a.py:3-3@" + s7),
                 ("src/a.py:3-3@" + s7, "src/a.py:3@" + full), ("src/a.py:2-4@" + s12, "src/a.py:2-4@" + full),
                 ("src/a.py:1@" + s7, "src/a.py:1@" + s7)]
        for a, b in pairs:
            with self.subTest(a=a, b=b):
                self.refused("new", *self.new_args(), "--cite", a, "--cite", b,
                             has="--cite: %s given more than once" % b)
        self.refused("new", *self.new_args(), "--cite", "src/a.py:1@" + s7, "--cite", "src/a.py:2@" + s7,
                     "--cite", "src/a.py:1-1@" + full, has="--cite: src/a.py:1-1@%s given more than once" % full)

    def test_d32_cite_distinct_referents_kept_as_typed(self):
        sha2 = self.second_commit()
        s7 = self.sha[:7]
        groups = [["src/a.py:1@" + s7, "src/a.py:2@" + self.sha], ["src/a.py:1@" + s7, "src/a.py:1-2@" + s7],
                  ["src/a.py:1@" + s7, "src/b.py:1@" + s7], ["src/a.py:1@" + s7, "src/a.py:1@" + sha2[:7]],
                  ["src/a.py:2-3@" + self.sha, "src/a.py:2@" + s7, "src/a.py:3-3@" + s7]]
        for cites in groups:
            with self.subTest(cites=cites):
                f = self.new(*[x for c in cites for x in ("--cite", c)])
                want = []
                for c in cites:
                    rest, _, sha = c.rpartition("@")
                    file, _, lines = rest.rpartition(":")
                    want.append({"file": file, "lines": lines, "sha": sha})
                self.assertEqual(self.rec(f)["cites"], want)

    def test_d32_evidence_same_referent_refused(self):
        F = self.stored("open")
        commit_all(self.root, "row")
        s7, s12, full = self.sha[:7], self.sha[:12], self.sha
        pairs = [(s7, full), (full, s12), (s7, s12), ("%s:notes.txt" % s7, "%s:notes.txt" % full),
                 ("%s:notes.txt" % full, "%s:notes.txt" % s12), (full, full), ("notes.txt", "notes.txt")]
        path = os.path.join(self.root, *FDIR.split("/"), F + ".yml")
        with open(path, "rb") as fh:
            orig = fh.read()
        for a, b in pairs:
            with self.subTest(a=a, b=b):
                try:
                    self.refused(*self.closing(F, a, b), has="--evidence: %s given more than once" % b)
                finally:  # keep each pair independent of an earlier wrong accept
                    with open(path, "wb") as fh:
                        fh.write(orig)

    def test_d32_evidence_same_referent_as_stored_refused(self):
        s7, full = self.sha[:7], self.sha
        P = self.stored("pinned")  # evidence [<full>:REVIEW]
        H = self.stored("in-progress", id_="F-20261031-p6q7", evidence=[full])
        commit_all(self.root, "rows")
        self.refused(*self.closing(P, "%s:%s" % (s7, REVIEW)),
                     has="--evidence: %s:%s given more than once" % (s7, REVIEW))
        self.refused("move", H, "--to", "pinned", "--by", "c", "--pin-test", "t", "--pin-transcript",
                     "%s:%s" % (full, TRANSCRIPT), "--evidence", "%s:%s" % (full, REVIEW), "--evidence", s7,
                     has="--evidence: %s given more than once" % s7)

    def test_d32_evidence_distinct_referents_kept_as_typed(self):
        F = self.stored("open")
        sha2 = self.second_commit()
        s7 = self.sha[:7]
        path = os.path.join(self.root, *FDIR.split("/"), F + ".yml")
        with open(path, "rb") as fh:
            orig = fh.read()
        groups = [[s7, "%s:notes.txt" % s7], ["%s:notes.txt" % s7, "%s:src/a.py" % self.sha],
                  [s7, sha2[:7]], ["notes.txt", "%s:notes.txt" % s7], ["%s:src/a.py" % s7, "%s:src/a.py" % sha2]]
        for ev in groups:
            with self.subTest(ev=ev):
                self.move(F, "closed", "--resolved-by", "p", *[x for e in ev for x in ("--evidence", e)])
                self.assertEqual(self.rec(F)["evidence"], ev)
                with open(path, "wb") as fh:
                    fh.write(orig)
        P = self.stored("pinned", id_="F-20261031-m4n5")
        self.move(P, "closed", "--resolved-by", "p", "--evidence", s7)
        self.assertEqual(self.rec(P)["evidence"], ["%s:%s" % (self.sha, REVIEW), s7])

    def test_d32_stored_duplicates_unchanged(self):
        """Invariant of the replaced code: a stored exact-text duplicate refuses any move; a stored pair of one
        referent under two spellings is not compared with itself (D-32 names argv-vs-argv and argv-vs-stored)."""
        full = self.sha
        A = self.stored("open", evidence=[full, full])
        B = self.stored("open", id_="F-20261031-m4n5", evidence=[full, full[:7]])
        commit_all(self.root, "rows")
        self.refused("move", A, "--to", "planned", "--by", "c", has="--evidence: %s given more than once" % full)
        self.move(B, "planned")
        C = self.stored("open", id_="F-20261031-p6q7", evidence=[5])  # hand-written non-string entry
        commit_all(self.root, "row C")
        self.refused("move", C, "--to", "planned", "--by", "c")

    def test_d32_only_sha_forms_are_resolved(self):
        """A plain path is compared as typed even when git could read it as a commit, and a bare ``<sha>:`` is
        not the sha: both reach the evidence validator instead of the duplicate check."""
        F = self.stored("open")
        commit_all(self.root, "row")
        self.refused(*self.closing(F, "HEAD", "HEAD^{commit}"), has="evidence.0: HEAD is not a tracked regular file")
        s7 = self.sha[:7]
        self.refused(*self.closing(F, s7, s7 + ":"), has="evidence.1:  is not a normalised repo-relative path")

    def test_d32_skeleton_rows_same_bytes_on_every_interpreter(self):
        s7 = self.sha[:7]
        for lines, cp in (("9" * 4300, None), ("9" * 4301, None), ("\U00016AC1", 0x16AC1), ("١٠", 0x661)):
            with self.subTest(lines=lines[:6]):
                want = ("findings new: --cite 2: LINES must be N or N-M (1 to 9 digits each)\n" if cp is None
                        else "findings new: --cite 2: U+%04X is not allowed (only U+0021-U+007E)\n" % cp)
                self.assertEqual(self.refused("new", *self.new_args(), "--cite", "a.py:1@" + s7,
                                              "--cite", "a.py:%s@%s" % (lines, s7)), want)
        F = self.stored("open")
        commit_all(self.root, "row")
        n4300, n4301 = "9" * 4300, "9" * 4301
        for e, want in ((n4300, "evidence.1: %s is not a tracked regular file" % n4300),
                        (n4301, "evidence.1: %s is not a tracked regular file" % n4301),
                        (n4300 + ":notes.txt", "evidence.1: %s:notes.txt is not a tracked regular file" % n4300),
                        ("\U00016AC1", "--evidence 2: U+16AC1 is not allowed (only U+0021-U+007E)"),
                        ("١٠", "--evidence 2: U+0661 is not allowed (only U+0021-U+007E)")):
            with self.subTest(e=e[:6]):
                self.assertEqual(self.refused(*self.closing(F, s7, e)), "findings move: %s\n" % want)


if __name__ == "__main__":
    unittest.main()
