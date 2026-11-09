"""Tests of gates/tools/index.py through render, regenerate and main on real fixture repositories (Task 1c.3
input-domain table: rows A, G, F, T, D, W, I). Expected file texts are written out by hand; ``rows`` parses table
rows with its own splitter that honours ``\\|``; ``parse`` is ``yamlsub.parse``."""
import contextlib
import copy
import html.entities
import io
import os
import re
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from gates import __main__ as gates_main
from gates import gate_decisions, gate_schema, producers
from gates.lib import config, schema, yamlsub
from gates.lib.result import GateError
from gates.lib.store import Store
from gates.tools import index
from tests.helpers import GitIsolatedTestCase, commit_all, git, make_repo, minimal_config, write_record

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEC = ".strict-delivery/state/decisions"
FIN = ".strict-delivery/state/findings"
DEC_INDEX = DEC + "/index.yml"
F_INDEX = FIN + "/index.yml"
IN_FORCE = DEC + "/in-force.md"
INDEX_MD = "docs/strict-delivery/INDEX.md"
ARCH = "docs/strict-delivery/architecture.md"
ORDER = [DEC_INDEX, F_INDEX, IN_FORCE, INDEX_MD]
SHA = "a1b2c3d"
OPTS = [{"label": "yes", "cost": "none"}, {"label": "no", "cost": "some"}]

DA, DB, DC, DD = "DEC-20261031-a2b3", "DEC-20261031-c4d5", "DEC-20261031-e6f7", "DEC-20261031-g8h9"
DE, DF, DG, DH = "DEC-20261031-j2k3", "DEC-20261031-m4n5", "DEC-20261031-p6q7", "DEC-20261031-r8s9"
DI, DJ = "DEC-20261031-t2u3", "DEC-20261031-v4w5"
FA, FB, FC, FD = "F-20261031-a2b3", "F-20261031-c4d5", "F-20261031-e6f7", "F-20261031-g8h9"
FE, FF, FG, FH = "F-20261031-j2k3", "F-20261031-m4n5", "F-20261031-p6q7", "F-20261031-r8s9"
PATHS_OF = {"open": ["open"], "planned": ["open", "planned"], "in-progress": ["open", "planned", "in-progress"],
            "fixed-unpinned": ["open", "planned", "in-progress", "fixed-unpinned"],
            "pinned": ["open", "planned", "in-progress", "pinned"], "deferred": ["open", "deferred"],
            "closed": ["open", "closed"], "merged": ["open", "planned", "in-progress", "pinned", "merged"]}


def _tag(kind):  # Q-2a1-3: a tag comes from its schema file
    s = schema.load_schema(os.path.join(schema.SCHEMAS_DIR, kind + ".yml"))
    return "%s/%d" % (s.kind, s.version)


def dec(id_, status="answered", **over):
    r = {"schema": _tag("decision"), "id": id_, "status": status, "class": "scope", "question": "Keep X?",
         "options": OPTS, "asked_at": SHA, "asked_by": "agent", "topics": ["ids"], "applies_to": [],
         "checked_against": [], "effect": "one-off"}
    if status == "answered":
        r.update(answer="Yes", answered_at={"at": SHA, "by": "who@example.invalid"})
    if status == "withdrawn":
        r["withdrawn"] = {"at": SHA, "by": "who@example.invalid", "reason": "asked twice"}
    r.update(over)
    return {k: v for k, v in r.items() if v is not None}


def lasting(id_, **over):
    return dec(id_, **{**dict(effect="lasting", rule="rule text", landed_in=["CLAUDE.md"]), **over})


def grant(id_):
    return dec(id_, **{"class": "merge-grant", "plan": "p"})


def fnd(id_, status="open", **over):
    r = {"schema": "finding/1", "id": id_, "status": status, "source": "review", "severity": "HIGH",
         "class": "bug", "siblings": [], "cites": [], "repro": None,
         "owner": {"kind": "plan", "plan": "p", "task": "1a.2"}, "pin": None, "ruling": None, "evidence": [],
         "history": [{"status": s, "sha": SHA, "by": "agent"} for s in PATHS_OF[status]]}
    if status in ("closed", "merged"):
        r["resolved_by"] = "p"
    r.update(over)
    return r


def parse(text):
    return yamlsub.parse(text)


def entries(text, key):
    """The index's list, keyed by id (owner Q-1c3-1 (a): a list of entries sorted by id)."""
    return {e["id"]: e for e in parse(text)[key]}


def split_row(line):
    """Cells of one table row; ``\\|`` is a literal pipe, any other ``|`` a separator."""
    cells, cur, i = [], [], 0
    while i < len(line):
        if line[i] == "\\" and line[i + 1:i + 2] == "|":
            cur.append("|")
            i += 2
            continue
        if line[i] == "|":
            cells.append("".join(cur))
            cur = []
        else:
            cur.append(line[i])
        i += 1
    cells.append("".join(cur))
    return [c.strip() for c in cells[1:-1]]


def rows(md):
    lines = md.split("\n")
    first = next(i for i, ln in enumerate(lines) if ln.startswith("|"))
    return [split_row(ln) for ln in lines[first + 2:] if ln.startswith("|")]


def headings(md):
    return [ln for ln in md.split("\n") if ln.startswith("## ")]


INFORCE_HEAD = ("<!-- schema: in-force/1 -->\n# In-force decisions (generated; do not edit)\n\n"
                "| id | topics | rule | landed_in |\n|---|---|---|---|\n")
SEV_ZERO = "- CRITICAL: 0\n- HIGH: 0\n- MEDIUM: 0\n- LOW: 0\n- INFO: 0\n"
EMPTY_FILES = {
    DEC_INDEX: "schema: decision-index/1\ndecisions: []\n",
    F_INDEX: "schema: finding-index/1\nfindings: []\n",
    IN_FORCE: INFORCE_HEAD,
    INDEX_MD: ("<!-- schema: overview/1 -->\n\n## Architecture\nnone\n\n## Open findings\n" + SEV_ZERO
               + "\n## In-force decisions\n0 in force: "
               "[in\\-force\\.md](<\\.\\.\\/\\.\\.\\/\\.strict\\-delivery\\/state\\/decisions\\/in\\-force\\.md>)\n"),
}


class Base(GitIsolatedTestCase):
    def build(self, decs=(), fins=(), files=None, cfg=None, commit=True):
        """A fresh fixture repository under self.tmp, made self.work (nothing is ever deleted)."""
        self.n = getattr(self, "n", 0) + 1
        self.work = os.path.join(self.tmp, "w%d" % self.n)
        os.mkdir(self.work)
        root = make_repo(self.work, cfg)
        c = config.load(root)
        for r in decs:
            write_record(root, "%s/%s.yml" % (c["paths"]["decisions"], r["id"]), r)
        for r in fins:
            write_record(root, "%s/%s.yml" % (c["paths"]["findings"], r["id"]), r)
        for rel, data in (files or {}).items():
            self.put(rel, data)
        if commit:
            commit_all(root, "fixture")
        self.cfg = config.load(root)
        return root

    def put(self, rel, data):
        path = os.path.join(self.work, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(data if isinstance(data, bytes) else data.encode("utf-8"))

    def render(self):
        return index.render(self.work, self.cfg)

    def read(self, rel):
        with open(os.path.join(self.work, rel), "rb") as fh:
            return fh.read().decode("utf-8")

    def refused(self, needle, fn=None):
        with self.assertRaises(GateError) as cm:
            (fn or self.render)()
        self.assertIn(needle, str(cm.exception))
        return str(cm.exception)

    def assert_nothing_written(self):
        for rel in ORDER:
            self.assertFalse(os.path.lexists(os.path.join(self.work, rel)), rel)


def run_main(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = index.main(argv)
    return out.getvalue(), err.getvalue(), code


WRITTEN = "".join(p + "\n" for p in ORDER)


# ---------------------------------------------------------------- A: root, argv, config

class RootArgvConfig(Base):
    def test_A1_root_forms_accepted(self):
        root = self.build()
        link = os.path.join(self.tmp, "link")
        os.symlink(root, link)
        wt = os.path.join(self.tmp, "wt")
        git(root, "worktree", "add", "-q", "-b", "wtb", wt)
        for r in (root, root + "/", link, wt):
            self.assertEqual(index.render(r, self.cfg), EMPTY_FILES, r)

    def test_A1_root_forms_refused_first(self):
        root = self.build()
        os.mkdir(os.path.join(root, "sub"))
        plain = os.path.join(self.tmp, "plain")
        os.mkdir(plain)
        bare = os.path.join(self.tmp, "bare")
        git(self.tmp, "init", "-q", "--bare", bare)
        for r in (os.path.join(root, "sub"), os.path.join(self.tmp, "missing"), plain, bare):
            for fn in (index.render, index.regenerate):
                with self.assertRaises(GateError, msg=r):
                    fn(r, self.cfg)
        self.assertEqual(os.listdir(os.path.join(root, "sub")), [])  # nothing written in the subdirectory
        with mock.patch.object(Store, "load", side_effect=AssertionError("registers read before the root check")):
            with self.assertRaises(GateError) as cm:
                index.render(os.path.join(root, "sub"), self.cfg)
        self.assertIn("top level", str(cm.exception))

    def test_A2_main_root_forms_and_output(self):
        root = self.build()
        self.assertEqual(run_main(["--root", root]), (WRITTEN, "", 0))
        self.assertEqual(self.read(DEC_INDEX), EMPTY_FILES[DEC_INDEX])
        old = os.getcwd()
        self.addCleanup(os.chdir, old)
        os.chdir(root)
        self.assertEqual(run_main([]), (WRITTEN, "", 0))
        os.chdir(old)
        other = os.path.join(self.tmp, "other")
        os.mkdir(other)
        make_repo(other)
        with mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": other}):
            self.assertEqual(run_main([]), (WRITTEN, "", 0))
        self.assertTrue(os.path.isfile(os.path.join(other, INDEX_MD)))
        with mock.patch.object(sys, "argv", ["prog", "--root", root]):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(index.main(), 0)
        self.assertEqual(out.getvalue(), WRITTEN)

    def test_A2_main_usage_errors_exit_2(self):
        root = self.build()
        for argv in (["--root", root, "--root", root], ["--root", root, "--root=" + root], ["--foo"],
                     ["--root", root, "extra"], ["-h"], ["--help"], ["--root"]):
            out, err, code = run_main(argv)
            self.assertEqual((out, code), ("", 2), argv)
            self.assertIn("usage: index", err, argv)
        self.assert_nothing_written()

    def test_A2_main_refusal_exit_1(self):
        root = self.build()
        os.mkdir(os.path.join(root, "sub"))
        out, err, code = run_main(["--root", os.path.join(root, "sub")])
        self.assertEqual((out, code), ("", 1))
        self.assertTrue(err.startswith("index: ") and err.endswith("\n") and err.count("\n") == 1, err)
        self.assertIn("top level", err)
        plain = os.path.join(self.tmp, "plain")
        os.mkdir(plain)
        out, err, code = run_main(["--root", plain])
        self.assertEqual((out, code), ("", 1))
        self.assertTrue(err.startswith("index: git rev-parse --show-toplevel") and
                        err.endswith("; run /strict-delivery:init\n"), err)
        with mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": os.path.join(root, "nope")}):
            self.assertEqual(run_main([]), ("", "index: CLAUDE_PROJECT_DIR is not a directory\n", 1))
        self.put(FIN + "/notes.txt", "x")
        out, err, code = run_main(["--root", root])
        self.assertEqual((out, code), ("", 1))
        self.assertIn(FIN + "/notes.txt", err)
        self.assert_nothing_written()

    def test_A2_main_refusal_reason_escaped_once(self):
        root = self.build(files={FIN + "/a\nb": "x"})
        out, err, code = run_main(["--root", root])
        self.assertEqual((out, code), ("", 1))
        self.assertIn(FIN + "/a\\nb", err)
        self.assertEqual(err.count("\n"), 1)

    def test_A3_config_missing_invalid_and_from_root(self):
        git(self.work, "init", "-q", "-b", "main")
        out, err, code = run_main(["--root", self.work])
        self.assertEqual((out, code), ("", 1))
        self.assertIn("/strict-delivery:init", err)
        self.put(".strict-delivery/config.yml", "a: [\n")
        out, err, code = run_main(["--root", self.work])
        self.assertEqual((out, code), ("", 1))
        self.assertIn(".strict-delivery/config.yml", err)
        cfg = {**minimal_config(), "paths": {"index": "out/IDX.md"}}
        write_record(self.work, ".strict-delivery/config.yml", cfg)
        out, err, code = run_main(["--root", self.work])  # the target root's config, not this checkout's
        self.assertEqual((out, err, code), ("".join(p + "\n" for p in ORDER[:3] + ["out/IDX.md"]), "", 0))
        self.assertTrue(os.path.isfile(os.path.join(self.work, "out/IDX.md")))

    def test_A4_paths_from_cfg(self):
        cfg = {**minimal_config(), "paths": {"decisions": "reg/d", "findings": "reg/f", "index": "out/deep/IDX.md",
                                              "architecture": "arch/A.md"}}
        self.build(decs=[lasting(DA)], fins=[fnd(FA)], cfg=cfg, files={"arch/A.md": "## One\n"})
        files = self.render()
        self.assertEqual(list(files), ["reg/d/index.yml", "reg/f/index.yml", "reg/d/in-force.md", "out/deep/IDX.md"])
        self.assertEqual(entries(files["reg/d/index.yml"], "decisions")[DA]["file"], "reg/d/%s.yml" % DA)
        self.assertEqual(entries(files["reg/f/index.yml"], "findings")[FA]["file"], "reg/f/%s.yml" % FA)
        self.assertIn(mdlink("A.md", "../../arch/A.md") + "\n- One\n", files["out/deep/IDX.md"])
        self.assertIn("1 in force: %s\n" % mdlink("in-force.md", "../../reg/d/in-force.md"), files["out/deep/IDX.md"])

    def test_A4_colliding_output_paths_refused(self):
        cfg = {**minimal_config(), "paths": {"index": DEC + "/in-force.md"}}
        self.build(cfg=cfg)
        self.refused("two generated files")
        self.refused("two generated files", lambda: index.regenerate(self.work, self.cfg))
        self.assertFalse(os.path.lexists(os.path.join(self.work, DEC_INDEX)))

    def test_A5_dispatcher(self):
        root = self.build()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(gates_main.main(["index", "--root", root]), 0)
        self.assertEqual(out.getvalue(), WRITTEN)
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        p = subprocess.run([sys.executable, "-m", "gates", "index", "--root", root], cwd=REPO, env=env,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual((p.stdout.decode(), p.stderr, p.returncode), (WRITTEN, b"", 0))
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(gates_main.main(["bogus"]), 2)
        self.assertEqual(err.getvalue(), "usage: python3 -m gates <command> [args]\ncommands: check, decisions, index\n")


# ---------------------------------------------------------------- G: registers

class Registers(Base):
    def test_G1_missing_and_empty_directories(self):
        self.build()
        self.assertEqual(self.render(), EMPTY_FILES)
        os.makedirs(os.path.join(self.work, DEC))
        self.assertEqual(self.render(), EMPTY_FILES)
        os.makedirs(os.path.join(self.work, FIN))
        self.assertEqual(self.render(), EMPTY_FILES)
        self.build(decs=[lasting(DA)])
        files = self.render()
        self.assertEqual(files[F_INDEX], EMPTY_FILES[F_INDEX])  # findings directory missing, decisions present
        self.build(fins=[fnd(FA)])
        self.assertEqual(self.render()[DEC_INDEX], EMPTY_FILES[DEC_INDEX])  # the reverse

    def test_G2_layout_refused(self):
        self.build()
        self.put(DEC + "/notes.txt", "x")
        self.refused(DEC + "/notes.txt: not a regular file named <id>.yml")
        self.refused(DEC + "/notes.txt", lambda: index.regenerate(self.work, self.cfg))
        self.assert_nothing_written()
        self.build()
        self.put(DEC + "/%s.yml" % DA, "a: [\n")
        self.refused(DEC + "/%s.yml" % DA)
        self.build()
        real = os.path.join(self.tmp, "realfin")
        os.mkdir(real)
        os.makedirs(os.path.join(self.work, ".strict-delivery/state"))
        os.symlink(real, os.path.join(self.work, FIN))
        self.refused(FIN + ": is a symlink")
        self.refused(FIN + ": is a symlink", lambda: index.regenerate(self.work, self.cfg))
        self.assertEqual(os.listdir(real), [])
        self.assertFalse(os.path.lexists(os.path.join(self.work, DEC_INDEX)))

    def test_G3_malformed_records_refused(self):  # owner Q-1c3-3 (a)
        bad = fnd(FA)
        del bad["severity"]
        self.build(fins=[bad])
        self.refused(FIN + "/%s.yml: severity: required key is missing" % FA)
        self.refused(FIN + "/%s.yml" % FA, lambda: index.regenerate(self.work, self.cfg))
        self.assert_nothing_written()
        self.build(fins=[fnd(FA, owner="plan:p")])
        self.refused(FIN + "/%s.yml: owner: must be a mapping" % FA)
        self.build(decs=[dec(DA, topics="ids")])
        self.refused(DEC + "/%s.yml: topics: must be a list" % DA)

    def test_G3_bad_id_and_duplicate_refused(self):
        self.build()
        write_record(self.work, DEC + "/DEC-20261031-K3F9.yml", dec("DEC-20261031-K3F9"))
        self.refused(DEC + "/DEC-20261031-K3F9.yml: id: id does not match the form; expected DEC-<YYYYMMDD>-<xxxx>")
        self.build()
        write_record(self.work, DEC + "/%s.yml" % DA, dec(DA))
        write_record(self.work, DEC + "/%s.yml" % DB, dec(DA))  # a second file holding the id DA
        self.refused(DEC + "/%s.yml: file name %s.yml differs from the record id %s" % (DB, DB, DA))
        self.assert_nothing_written()

    def test_G3_duplicate_reason(self):
        self.build()
        write_record(self.work, DEC + "/%s.yml" % DA, dec(DA))
        write_record(self.work, DEC + "/%s.yml" % DB, dec(DA))
        with mock.patch("gates.tools.index.store_errors",
                        return_value=[("duplicate." + DA, "id %s appears in 2 files: x, y" % DA)]):
            self.assertEqual(self.refused("appears"), "id %s appears in 2 files: x, y" % DA)

    def test_index_lists_every_record(self):  # G4
        decs = [dec(DA, "open"), lasting(DB), dec(DC), dec(DD, "withdrawn"), lasting(DE),
                lasting(DF, supersedes=DE), grant(DG)]
        statuses = ["open", "planned", "in-progress", "fixed-unpinned", "pinned", "deferred", "closed"]
        ids_ = [FA, FB, FC, FD, FE, FF, FG]
        fins = [fnd(i, s) for i, s in zip(ids_, statuses)]
        fins[5]["ruling"] = DB
        self.build(decs=decs, fins=fins)
        files = self.render()
        self.assertEqual(set(entries(files[DEC_INDEX], "decisions")), {DA, DB, DC, DD, DE, DF, DG})
        self.assertEqual(set(entries(files[F_INDEX], "findings")), set(ids_))
        self.assertEqual({i: e["status"] for i, e in entries(files[F_INDEX], "findings").items()},
                         dict(zip(ids_, statuses)))
        self.assertEqual({i: e["status"] for i, e in entries(files[DEC_INDEX], "decisions").items()},
                         {DA: "open", DB: "answered", DC: "answered", DD: "withdrawn", DE: "superseded",
                          DF: "answered", DG: "answered"})

    def test_G4_merged_finding_refused(self):  # findings.validate refuses status merged (OQ-6); Q-1c3-3 (a)
        self.build(fins=[fnd(FH, "merged")])
        self.refused(FIN + "/%s.yml: status: merged is set only by the cleanup step" % FH)

    def test_superseded_status_in_decision_index(self):  # G5
        decs = [lasting(DA), lasting(DB, supersedes=DA), lasting(DC, supersedes=DB),
                lasting(DD), dec(DE, "open", supersedes=DD),
                lasting(DF), dec(DG, "withdrawn", supersedes=DF)]
        self.build(decs=decs)
        got = {i: e["status"] for i, e in entries(self.render()[DEC_INDEX], "decisions").items()}
        self.assertEqual(got, {DA: "superseded", DB: "superseded", DC: "answered", DD: "answered", DE: "open",
                               DF: "answered", DG: "withdrawn"})

    def test_G6_withdrawn_target_keeps_status(self):
        self.build(decs=[dec(DA, "withdrawn"), lasting(DB, supersedes=DA), dec(DC, "open"),
                         lasting(DD, supersedes=DC)])
        got = {i: e["status"] for i, e in entries(self.render()[DEC_INDEX], "decisions").items()}
        self.assertEqual(got, {DA: "withdrawn", DB: "answered", DC: "open", DD: "answered"})

    def test_in_force_md_excludes_superseded_grants_one_off(self):  # G7
        LASTING = DH
        lasting_grant = dec(DG, **{"class": "merge-grant", "plan": "p", "effect": "lasting", "rule": "r",
                                   "landed_in": ["CLAUDE.md"]})
        self.build(decs=[lasting(LASTING), dec(DA), lasting_grant, lasting(DB), lasting(DC, supersedes=DB, rule="new"),
                         dec(DD, "open"), dec(DE, "withdrawn")])
        got = rows(self.render()[IN_FORCE])
        self.assertEqual(got, [[DC, "ids", "new", "CLAUDE.md"], [LASTING, "ids", "rule text", "CLAUDE.md"]])
        self.build(decs=[lasting(DH), dec(DA), grant(DG), dec(DB, effect="one-off"), dec(DD, "open"),
                         lasting(DC, supersedes=DH)])
        self.assertEqual(rows(self.render()[IN_FORCE]), [[DC, "ids", "rule text", "CLAUDE.md"]])


# ---------------------------------------------------------------- F: shapes of the four files

class Shapes(Base):
    def test_F1_decision_index_text(self):
        self.build(decs=[lasting(DA, topics=[]), dec(DB, "open", topics=["a", "b"])])
        self.assertEqual(self.render()[DEC_INDEX], (
            "schema: decision-index/1\n"
            "decisions:\n"
            "  - id: %s\n    file: %s/%s.yml\n    status: answered\n    class: scope\n    topics: []\n"
            "  - id: %s\n    file: %s/%s.yml\n    status: open\n    class: scope\n    topics:\n      - a\n      - b\n"
        ) % (DA, DEC, DA, DB, DEC, DB))

    def test_F2_empty_registers_emit_empty_lists(self):  # owner Q-1c3-1 (a)
        self.build()
        files = self.render()
        self.assertEqual(parse(files[DEC_INDEX]), {"schema": _tag("decision-index"), "decisions": []})
        self.assertEqual(parse(files[F_INDEX]), {"schema": _tag("finding-index"), "findings": []})
        self.assertEqual(files[DEC_INDEX], "schema: decision-index/1\ndecisions: []\n")

    def test_finding_owner_rendered_as_one_string(self):  # F3
        F_PLAN, F_ISSUE, F_ROADMAP = FA, FB, FC
        self.build(fins=[fnd(F_PLAN), fnd(F_ISSUE, owner={"kind": "issue", "number": 3}),
                         fnd(F_ROADMAP, owner={"kind": "roadmap", "plan": "p"})])
        got = entries(self.render()[F_INDEX], "findings")
        self.assertEqual([got[f]["owner"] for f in (F_PLAN, F_ISSUE, F_ROADMAP)], ["plan:p/1a.2", "issue:3", "roadmap:p"])

    def test_F4_finding_index_text(self):
        self.build(fins=[fnd(FA, severity="LOW"), fnd(FB, "closed", owner={"kind": "issue", "number": 12})])
        self.assertEqual(self.render()[F_INDEX], (
            "schema: finding-index/1\n"
            "findings:\n"
            "  - id: %s\n    file: %s/%s.yml\n    status: open\n    severity: LOW\n    owner: plan:p/1a.2\n"
            "  - id: %s\n    file: %s/%s.yml\n    status: closed\n    severity: HIGH\n    owner: issue:12\n"
        ) % (FA, FIN, FA, FB, FIN, FB))

    def test_in_force_first_lines(self):  # F5, I8
        self.build(decs=[lasting(DA)])
        files = self.render()
        self.assertEqual(files[IN_FORCE].splitlines()[:2],
                         ["<!-- schema: in-force/1 -->", "# In-force decisions (generated; do not edit)"])

    def test_F5_in_force_layout(self):
        self.build()
        self.assertEqual(self.render()[IN_FORCE], INFORCE_HEAD)
        self.build(decs=[lasting(DA), lasting(DB, rule=None, topics=[])])
        self.assertEqual(self.render()[IN_FORCE], INFORCE_HEAD + "| %s | ids | rule text | CLAUDE.md |\n"
                         "| %s |  |  | CLAUDE.md |\n" % (DA, DB))

    def test_in_force_rule_column(self):  # F6, OQ-12, I2
        self.build(decs=[lasting(DA)])
        files = self.render()
        self.build(decs=[lasting(DA, rule=None)])
        no_rule_files = self.render()
        self.assertEqual(rows(files[IN_FORCE])[0][2], "rule text")
        self.assertEqual(rows(no_rule_files[IN_FORCE])[0][2], "")

    def test_F7_topics_and_landed_in_lists(self):
        pb = ".strict-delivery/playbooks/a.md"
        self.build(decs=[lasting(DA, topics=[]), lasting(DB, topics=["one"]),
                         lasting(DC, topics=["z", "a", "m"], landed_in=["CLAUDE.md", pb, ARCH + "#x"])])
        self.assertEqual(rows(self.render()[IN_FORCE]), [
            [DA, "", "rule text", "CLAUDE.md"], [DB, "one", "rule text", "CLAUDE.md"],
            [DC, "z, a, m", "rule text", "CLAUDE.md, %s, %s#x" % (pb, ARCH)]])

    def test_overview_sections(self):  # F8, OQ-13
        self.build(decs=[lasting(DA)], fins=[fnd(FA)], files={ARCH: "# T\n## One\n"})
        files = self.render()
        self.assertEqual(headings(files[INDEX_MD]), ["## Architecture", "## Open findings", "## In-force decisions"])
        self.assertEqual(files[INDEX_MD].splitlines()[0], "<!-- schema: overview/1 -->")

    def test_F8_overview_text(self):
        self.build(decs=[lasting(DA), lasting(DB)], fins=[fnd(FB, severity="LOW", **{"class": "leak"}),
                                                          fnd(FA, "planned"), fnd(FC, "closed")],
                   files={ARCH: "# Title\n\n## Layers\ntext\n### Deep\n## Data flow\n"})
        self.assertEqual(self.render()[INDEX_MD], (
            "<!-- schema: overview/1 -->\n\n## Architecture\n[architecture\\.md](<architecture\\.md>)\n- Layers\n"
            "- Data flow\n\n## Open findings\n- CRITICAL: 0\n- HIGH: 1\n- MEDIUM: 0\n- LOW: 1\n- INFO: 0\n"
            "- %s (HIGH, planned): bug\n- %s (LOW, open): leak\n\n## In-force decisions\n"
            "2 in force: [in\\-force\\.md](<\\.\\.\\/\\.\\.\\/\\.strict\\-delivery\\/state\\/decisions\\/in\\-force\\.md>)\n")
            % (FA, FB))

    def test_F9_architecture_forms(self):
        self.build()
        self.assertIn("## Architecture\nnone\n", self.render()[INDEX_MD])
        self.put(ARCH, "# T\n```\n## In fence\n```\nno headings\n")
        self.assertIn("## Architecture\n%s\n- In fence\n\n" % mdlink("architecture.md", "architecture.md"),
                      self.render()[INDEX_MD])
        self.put(ARCH, "# T\nno headings\n### three\n##two\n")
        self.assertIn("## Architecture\n%s\n\n## Open" % mdlink("architecture.md", "architecture.md"),
                      self.render()[INDEX_MD])
        self.put(ARCH, "## Architecture\n## Open findings\n")
        md = self.render()[INDEX_MD]
        self.assertIn("- Architecture\n- Open findings\n", md)
        self.assertEqual(headings(md), ["## Architecture", "## Open findings", "## In-force decisions"])

    def test_F9_architecture_refused(self):
        self.build(files={ARCH: b"## \xff\n"})
        self.refused(ARCH + ": cannot be read as a UTF-8 regular file (not valid UTF-8)")
        self.build()
        os.makedirs(os.path.join(self.work, ARCH))
        self.refused(ARCH + ": cannot be read as a UTF-8 regular file (not a regular file)")
        self.build(files={"real.md": "## X\n"})
        os.makedirs(os.path.join(self.work, "docs/strict-delivery"))
        os.symlink(os.path.join(self.work, "real.md"), os.path.join(self.work, ARCH))
        self.refused(ARCH + ": cannot be read as a UTF-8 regular file (not a regular file)")
        self.refused(ARCH, lambda: index.regenerate(self.work, self.cfg))
        self.assert_nothing_written()
        self.build(files={"realdocs/architecture.md": "## X\n"})
        os.makedirs(os.path.join(self.work, "docs"))
        os.symlink(os.path.join(self.work, "realdocs"), os.path.join(self.work, "docs/strict-delivery"))
        self.refused(ARCH + ": cannot be read as a UTF-8 regular file (a parent is not a real directory)")
        self.build(files={"docs/strict-delivery": "a file"})  # a parent that is a regular file
        self.refused(ARCH + ": cannot be read as a UTF-8 regular file (a parent is not a real directory)")

    def test_F10_link_targets_in_angle_brackets(self):  # owner Q-1c3-R1 (a): CommonMark [text](<path>)
        self.build(cfg={**minimal_config(), "paths": {"architecture": "docs/my arch.md",
                                                      "index": "docs/out dir/INDEX.md"}},
                   files={"docs/my arch.md": "## H\n"})
        md = self.render()["docs/out dir/INDEX.md"]
        self.assertIn("\n[my arch\\.md](<\\.\\.\\/my arch\\.md>)\n- H\n", md)  # a space is copied as it is
        self.assertIn("\n0 in force: %s\n" % mdlink("in-force.md", "../../%s/in-force.md" % DEC), md)

    def test_F10_link_destinations_escaped(self):  # owner Q-1c3-F1-1 (a): \, < and >
        arch = "a\\/x<y>.md"       # a directory named 'a\' holding 'x<y>.md'
        dec_dir = "r\\/d<1>"       # the in-force link goes through 'r\' and 'd<1>'
        self.build(cfg={**minimal_config(), "paths": {"architecture": arch, "decisions": dec_dir,
                                                      "index": "docs/IN\\<DEX>.md"}},
                   files={arch: "## H\n"})
        md = self.render()["docs/IN\\<DEX>.md"]
        lines = md.split("\n")
        arch_line = lines[lines.index("## Architecture") + 1]
        force_line = next(ln for ln in lines if ln.startswith("0 in force: "))
        self.assertEqual(arch_line, "[x\\<y\\>\\.md](<\\.\\.\\/a\\\\\\/x\\<y\\>\\.md>)")
        self.assertEqual(force_line, "0 in force: [in\\-force\\.md](<\\.\\.\\/r\\\\\\/d\\<1\\>\\/in\\-force\\.md>)")
        self.assertEqual(commonmark_link(arch_line), ("x<y>.md", "../" + arch))
        self.assertEqual(commonmark_link(force_line), ("in-force.md", "../" + dec_dir + "/in-force.md"))
        self.assertTrue(os.path.isfile(os.path.normpath(os.path.join(self.work, "docs", commonmark_link(arch_line)[1]))))

    def test_F10_all_punctuation_in_text_and_destination(self):  # Q-1c3-RR2-1 (a), Q-1c3-F2-1 (a), spec D30
        name = "n" + P31 + REFS + "e.md"         # a file name: 31 punctuation characters, references, ], spaces
        arch = "a b/" + name                     # its destination also crosses a '/': all 32
        dec_dir = "d" + P31 + REFS + "/x"
        here = "docs/i" + P31 + " &amp;"
        self.build(cfg={**minimal_config(), "paths": {"architecture": arch, "decisions": dec_dir,
                                                      "index": here + "/INDEX.md"}},
                   files={arch: "## H\n"})
        lines = self.render()[here + "/INDEX.md"].split("\n")
        arch_line = lines[lines.index("## Architecture") + 1]
        force_line = next(ln for ln in lines if ln.startswith("0 in force: "))
        self.assertTrue(set(PUNCT) <= set("../../" + arch) and set(P31) <= set(name))
        self.assertEqual(commonmark_link(arch_line), (name, "../../" + arch))
        self.assertEqual(commonmark_link(force_line), ("in-force.md", "../../" + dec_dir + "/in-force.md"))
        self.assertEqual(arch_line, mdlink(name, "../../" + arch))
        self.assertTrue(os.path.isfile(os.path.normpath(os.path.join(self.work, here, commonmark_link(arch_line)[1]))))

    def test_F10_character_reference_in_path(self):  # F-1c3-RR2-1's reproducer
        for arch in ("docs/a&#60;b.md", "docs/a&amp;b.md", "docs/a&#x3C;b.md"):
            self.build(cfg={**minimal_config(), "paths": {"architecture": arch, "index": "docs/INDEX.md"}},
                       files={arch: "## H\n"})
            lines = self.render()["docs/INDEX.md"].split("\n")
            line = lines[lines.index("## Architecture") + 1]
            self.assertEqual(commonmark_link(line), (posix_base(arch), posix_base(arch)), arch)
            old = "[%s](<%s>)" % (md_esc(posix_base(arch)), posix_base(arch))  # a round-2 destination: & unescaped
            self.assertNotEqual(commonmark_link(old)[1], posix_base(arch), arch)  # the reader sees section 2.5

    def test_F10_md_link_all_32_in_the_text(self):  # '/' cannot be in a file name; the text rule is the same
        line = index._md_link(PUNCT + REFS, PUNCT + REFS)
        self.assertEqual(line, mdlink(PUNCT + REFS, PUNCT + REFS))
        self.assertEqual(commonmark_link(line), (PUNCT + REFS, PUNCT + REFS))

    def test_F10_links_relative_to_index(self):
        for idx, arch, want_arch, want_inf in (
                ("INDEX.md", "docs/a.md", "docs/a.md", DEC + "/in-force.md"),
                ("docs/strict-delivery/INDEX.md", "docs/strict-delivery/architecture.md", "architecture.md",
                 "../../" + DEC + "/in-force.md"),
                ("docs/x/INDEX.md", "docs/y/arch.md", "../y/arch.md", "../../" + DEC + "/in-force.md"),
                (".strict-delivery/state/o/I.md", "A.md", "../../../A.md", "../decisions/in-force.md"),
                (DEC + "/in-force.md/I.md", "A.md", "../../../../A.md", "../in-force.md")):  # a start component
            # equal to the link's last one: the last component is never consumed as a common prefix
            self.build(cfg={**minimal_config(), "paths": {"index": idx, "architecture": arch}},
                       files={arch: "## H\n"})
            md = self.render()[idx]
            self.assertIn(mdlink(posix_base(arch), want_arch) + "\n- H\n", md)
            self.assertIn("0 in force: %s\n" % mdlink("in-force.md", want_inf), md)

    def test_F11_open_findings_counts_and_lines(self):
        self.build(fins=[fnd(FA, "closed"), fnd(FB, "closed", severity="CRITICAL")])
        self.assertIn("## Open findings\n" + SEV_ZERO + "\n## In-force", self.render()[INDEX_MD])
        sev = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]
        fins = [fnd(i, s, severity=v) for i, s, v in zip([FA, FB, FC, FD, FE], ["open", "pinned", "deferred",
                                                                                "in-progress", "fixed-unpinned"], sev)]
        fins[2]["ruling"] = DA
        fins.append(fnd(FF, severity="HIGH"))
        fins.append(fnd(FG, "closed", severity="HIGH"))
        self.build(decs=[dec(DA)], fins=fins)
        self.assertIn("## Open findings\n- CRITICAL: 1\n- HIGH: 2\n- MEDIUM: 1\n- LOW: 1\n- INFO: 1\n"
                      "- %s (CRITICAL, open): bug\n- %s (HIGH, pinned): bug\n- %s (MEDIUM, deferred): bug\n"
                      "- %s (LOW, in-progress): bug\n- %s (INFO, fixed-unpinned): bug\n- %s (HIGH, open): bug\n\n"
                      % (FA, FB, FC, FD, FE, FF), self.render()[INDEX_MD])

    def test_F12_in_force_count(self):
        self.build(decs=[lasting(DA), lasting(DB), lasting(DC, supersedes=DB), dec(DD)])
        self.assertIn("## In-force decisions\n2 in force: %s\n" % mdlink("in-force.md", "../../%s/in-force.md" % DEC),
                      self.render()[INDEX_MD])

    def test_F13_schema_files(self):
        loaded = {k: schema.load_schema(os.path.join(schema.SCHEMAS_DIR, k + ".yml"))
                  for k in ("decision-index", "finding-index", "in-force", "overview")}
        self.assertEqual([(s.kind, s.version, s.format) for s in loaded.values()],
                         [("decision-index", 1, "yaml"), ("finding-index", 1, "yaml"),
                          ("in-force", 1, "markdown"), ("overview", 1, "markdown")])
        self.assertEqual(loaded["decision-index"].files, [{"dir": "decisions", "glob": "index.yml"}])
        self.assertEqual(loaded["finding-index"].files, [{"dir": "findings", "glob": "index.yml"}])
        self.assertEqual(loaded["in-force"].files, [{"dir": "decisions", "glob": "in-force.md"}])
        self.assertEqual(loaded["overview"].files, [{"path": "index"}])
        self.assertEqual(loaded["in-force"].table, ["id", "topics", "rule", "landed_in"])
        self.assertEqual(loaded["overview"].headings, ["## Architecture", "## Open findings", "## In-force decisions"])
        self.assertEqual((loaded["in-force"].first_line, loaded["overview"].first_line),
                         ("<!-- schema: in-force/1 -->", "<!-- schema: overview/1 -->"))
        self.assertEqual(index.PRODUCES, ("decision-index", "finding-index", "in-force", "overview"))

    def test_rendered_files_validate_against_their_schemas(self):  # F13
        self.build(decs=[lasting(DA), dec(DB, "open"), lasting(DC, supersedes=DA), dec(DD, "withdrawn")],
                   fins=[fnd(FA), fnd(FB, "closed"), fnd(FC, owner={"kind": "issue", "number": 3})],
                   files={ARCH: "## A\n"})
        files = self.render()
        self.build()
        empty = self.render()
        kinds = {DEC_INDEX: "decision-index", F_INDEX: "finding-index", IN_FORCE: "in-force", INDEX_MD: "overview"}
        for f in (files, empty):
            for rel, kind in kinds.items():
                s = schema.load_schema(os.path.join(schema.SCHEMAS_DIR, kind + ".yml"))
                if s.format == "yaml":
                    self.assertEqual(schema.validate(s, parse(f[rel]), self.cfg), [], rel)
                else:
                    self.assertEqual(schema.validate_markdown(s, f[rel]), [], rel)

    def test_F13_index_schemas_reject_bad_entries(self):
        s = schema.load_schema(os.path.join(schema.SCHEMAS_DIR, "decision-index.yml"))
        good = {"id": DA, "file": "x", "status": "superseded", "class": "scope", "topics": []}
        self.assertEqual(schema.validate(s, {"schema": "decision-index/1", "decisions": [good]}, self.cfg_d()), [])
        self.assertEqual(schema.validate(s, {"schema": "decision-index/1", "decisions": [
            dict(good, status="closed", extra=1)]}, self.cfg_d()),
            ["decisions.0.status: must be one of open, answered, withdrawn, superseded", "decisions.0.extra: unknown key"])
        f = schema.load_schema(os.path.join(schema.SCHEMAS_DIR, "finding-index.yml"))
        fgood = {"id": FA, "file": "x", "status": "merged", "severity": "INFO", "owner": "issue:3"}
        self.assertEqual(schema.validate(f, {"schema": "finding-index/1", "findings": [fgood]}, self.cfg_d()), [])
        self.assertEqual(schema.validate(f, {"schema": "finding-index/1", "findings": [dict(fgood, id=DA)]},
                                         self.cfg_d())[0][:14], "findings.0.id:")
        self.assertEqual(schema.validate(f, {"schema": "finding-index/1"}, self.cfg_d()),
                         ["findings: required key is missing"])

    def cfg_d(self):
        return copy.deepcopy(config.DEFAULTS)


def posix_base(p):
    return p.rsplit("/", 1)[-1]


PUNCT = "!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~"  # CommonMark 0.31 section 2.1: the 32 ASCII punctuation characters
P31 = PUNCT.replace("/", "")                    # those a file name can hold
REFS = " &#60; &amp; &#x3C; ] "                 # character references, an unmatched ] and spaces
_DEC_REF = re.compile(r"&#([0-9]{1,7});")
_HEX_REF = re.compile(r"&#[xX]([0-9a-fA-F]{1,6});")
_NAMED_REF = re.compile(r"&([A-Za-z][A-Za-z0-9]*);")


def md_esc(s):
    """The expected escaped form: a backslash before each of the 32 (owner Q-1c3-RR2-1 (a), Q-1c3-F2-1 (a))."""
    return "".join("\\" + c if c in PUNCT else c for c in s)


def mdlink(text, dest):
    return "[%s](<%s>)" % (md_esc(text), md_esc(dest))


def _reference(s, i):
    """CommonMark 0.31 section 2.5 at ``s[i] == "&"``: ``(decoded, length)`` of an entity reference (an HTML5 entity
    name, from ``html.entities.html5``) or a decimal or hexadecimal numeric character reference, else None. A
    numeric reference to 0, a surrogate or a value past U+10FFFF decodes to U+FFFD."""
    for pat, base in ((_DEC_REF, 10), (_HEX_REF, 16)):
        m = pat.match(s, i)
        if m:
            n = int(m.group(1), base)
            ok = 0 < n <= 0x10FFFF and not 0xD800 <= n <= 0xDFFF
            return (chr(n) if ok else "�"), m.end() - i
    m = _NAMED_REF.match(s, i)
    if m and m.group(1) + ";" in html.entities.html5:
        return html.entities.html5[m.group(1) + ";"], m.end() - i
    return None


def _read_part(s, i, end, is_text):
    out = []
    while True:
        if i >= len(s):
            raise ValueError("unterminated link: %r" % s)
        c = s[i]
        if c == "\\" and s[i + 1:i + 2] and s[i + 1] in PUNCT:  # section 2.4: the escaped character, literally
            out.append(s[i + 1])
            i += 2
            continue
        if c == "&":  # section 2.5
            ref = _reference(s, i)
            out.append(ref[0] if ref else c)
            i += ref[1] if ref else 1
            continue
        if c == end:
            return "".join(out), i
        if c in "\n\r":
            raise ValueError("a line ending inside a link: %r" % s)
        if is_text and c in PUNCT:
            raise ValueError("unescaped %r in link text could start other inline markup: %r" % (c, s))
        if not is_text and c == "<":
            raise ValueError("unescaped < in a pointy-bracket destination: %r" % s)
        out.append(c)
        i += 1


def commonmark_link(line):
    """``(text, destination)`` of the first inline link ``[text](<dest>)`` in ``line``, read by the CommonMark 0.31
    rules for the subset index.py writes: section 2.4 (a backslash before one of the 32 ASCII punctuation
    characters is that character, taken literally; any other backslash is literal), section 2.5 (entity and
    numeric character references are decoded, in the text and in the destination) and section 6.3 (a ``<...>``
    destination holds no line ending and no unescaped ``<`` or ``>``; the text ends at the first unescaped ``]``).
    Unescaped ASCII punctuation other than ``&`` in the text could start brackets, emphasis, code spans or raw HTML,
    which this reader does not model: it raises ValueError there instead of guessing. Written from the spec text,
    independent of index.py."""
    text, i = _read_part(line, line.index("[") + 1, "]", True)
    if line[i:i + 3] != "](<":
        raise ValueError("not an inline link with a <...> destination: %r" % line)
    dest, i = _read_part(line, i + 3, ">", False)
    if line[i:i + 2] != ">)":
        raise ValueError("not an inline link: %r" % line)
    return text, dest


class CommonMarkReader(unittest.TestCase):  # the oracle itself, on spec-style examples
    def test_escapes_and_destination(self):
        self.assertEqual(commonmark_link("[a](<b c>)"), ("a", "b c"))
        self.assertEqual(commonmark_link("[a](<b\\>c>)")[1], "b>c")
        self.assertEqual(commonmark_link("[a](<b\\\\c>)")[1], "b\\c")
        self.assertEqual(commonmark_link("[a](<b\\qc>)")[1], "b\\qc")  # not punctuation: the backslash stays
        self.assertEqual(commonmark_link("[a](<a\\/b>)")[1], "a/b")  # '/' is punctuation: the backslash goes
        self.assertEqual(commonmark_link("x: [\\]\\[\\*](<z>)"), ("][*", "z"))
        for bad in ("[a](<b<c>)", "[a](<b>c>)", "[a*b](<c>)", "[a]b](<c>)", "[a](b)", "[a](<b"):
            with self.assertRaises(ValueError, msg=bad):
                commonmark_link(bad)

    def test_character_references(self):  # section 2.5
        for src, want in (("a&#60;b", "a<b"), ("a&amp;b", "a&b"), ("a&#x3C;b", "a<b"), ("a&#X3c;b", "a<b"),
                          ("a&lt;b", "a<b"), ("&bogus;", "&bogus;"), ("&#0;", "�"), ("&#xD800;", "�"),
                          ("&#12345678;", "&#12345678;"), ("a & b", "a & b"), ("\\&#60;", "&#60;"),
                          ("\\&amp;", "&amp;")):
            self.assertEqual(commonmark_link("[t](<%s>)" % src)[1], want, src)
        self.assertEqual(commonmark_link("[x&#60;y&amp;](<z>)")[0], "x<y&")


# ---------------------------------------------------------------- T: text in rendered values

class Text(Base):
    def test_cell_pipe_escaped(self):  # T1
        pb = ".strict-delivery/playbooks/a|b.md"
        self.build(decs=[lasting(DA, rule="a|b", topics=["x|y"], landed_in=[pb])])
        files = self.render()
        self.assertIn("a\\|b", files[IN_FORCE])
        self.assertIn("| %s | x\\|y | a\\|b | .strict-delivery/playbooks/a\\|b.md |\n" % DA, files[IN_FORCE])
        self.assertEqual(rows(files[IN_FORCE]), [[DA, "x|y", "a|b", pb]])

    def test_T2_newlines(self):  # owner Q-1c3-2 (a)
        self.build(decs=[lasting(DA, rule="a\nb", topics=["t\r\nu", "v\rw"])],
                   fins=[fnd(FA, **{"class": "x\n## y\r\nz\rq"})], files={ARCH: "## Head\r\n## Two\n"})
        files = self.render()
        self.assertIn("| %s | t<br>u, v<br>w | a<br>b | CLAUDE.md |\n" % DA, files[IN_FORCE])
        self.assertIn("- %s (HIGH, open): x ## y z q\n" % FA, files[INDEX_MD])
        self.assertIn("- Head \n- Two\n", files[INDEX_MD])
        self.assertEqual(headings(files[INDEX_MD]), ["## Architecture", "## Open findings", "## In-force decisions"])
        self.assertEqual(len(rows(files[IN_FORCE])), 1)
        self.assertEqual(entries(files[DEC_INDEX], "decisions")[DA]["topics"], ["t\r\nu", "v\rw"])

    def test_T3_backtick_hash_backslash_unchanged(self):
        self.build(decs=[lasting(DA, rule="`x` a\\b", topics=["# x"])], fins=[fnd(FA, **{"class": "# `c` \\d"})])
        files = self.render()
        self.assertIn("| %s | # x | `x` a\\b | CLAUDE.md |\n" % DA, files[IN_FORCE])
        self.assertIn("- %s (HIGH, open): # `c` \\d\n" % FA, files[INDEX_MD])

    def test_T4_unicode(self):
        self.build(decs=[lasting(DA, rule="r\u00e9gle \U0001d11e", topics=["\u00fcber"])],
                   fins=[fnd(FA, **{"class": "\u2603"})], files={ARCH: "## \u00c9tat\n"})
        index.regenerate(self.work, self.cfg)
        with open(os.path.join(self.work, IN_FORCE), "rb") as fh:
            self.assertIn(("| %s | \u00fcber | r\u00e9gle \U0001d11e | CLAUDE.md |\n" % DA).encode("utf-8"), fh.read())
        with open(os.path.join(self.work, INDEX_MD), "rb") as fh:
            data = fh.read()
        self.assertIn("- \u00c9tat\n".encode("utf-8"), data)
        self.assertIn(("- %s (HIGH, open): \u2603\n" % FA).encode("utf-8"), data)
        self.assertEqual(entries(self.read(DEC_INDEX), "decisions")[DA]["topics"], ["\u00fcber"])

    def test_T5_yaml_significant_text(self):
        topics = ["a: b", "#x", "- x", '"q"', "true", "1", "null"]
        self.build(decs=[dec(DA, topics=topics, **{"class": "scope"})])
        got = entries(self.render()[DEC_INDEX], "decisions")[DA]
        self.assertEqual(got["topics"], topics)
        self.assertEqual([type(t) for t in got["topics"]], [str] * len(topics))


# ---------------------------------------------------------------- D: ordering and determinism

class Determinism(Base):
    def test_D1_sorted_by_id_whatever_the_load_order(self):
        self.build(decs=[lasting(DC), lasting(DA), dec(DB, "open")],
                   fins=[fnd(FC), fnd(FA, severity="LOW"), fnd(FB)])
        real = Store.load

        def reversed_load(store):
            return list(reversed(real(store)))

        with mock.patch.object(Store, "load", reversed_load):
            files = self.render()
        self.assertEqual([e["id"] for e in parse(files[DEC_INDEX])["decisions"]], [DA, DB, DC])
        self.assertEqual([e["id"] for e in parse(files[F_INDEX])["findings"]], [FA, FB, FC])
        self.assertEqual([r[0] for r in rows(files[IN_FORCE])], [DA, DC])
        md = files[INDEX_MD]
        self.assertLess(md.index(FA), md.index(FB))
        self.assertLess(md.index(FB), md.index(FC))

    def test_regenerate_is_idempotent(self):  # D2
        self.build(decs=[lasting(DA), dec(DB, "open")], fins=[fnd(FA)], files={ARCH: "## A\n"})

        def read_all(paths):
            out = {}
            for p in paths:
                with open(os.path.join(self.work, p), "rb") as fh:
                    out[p] = fh.read()
            return out

        root, cfg = self.work, self.cfg
        first = read_all(index.regenerate(root, cfg))
        self.assertEqual(read_all(index.regenerate(root, cfg)), first)
        self.assertEqual(first, {k: v.encode("utf-8") for k, v in index.render(root, cfg).items()})

    def test_D2_bytes_are_the_hand_written_text(self):  # one interpreter per run of the test command
        self.build()
        index.regenerate(self.work, self.cfg)
        for rel, text in EMPTY_FILES.items():
            with open(os.path.join(self.work, rel), "rb") as fh:
                self.assertEqual(fh.read(), text.encode("utf-8"), rel)


# ---------------------------------------------------------------- W: writing

class Writing(Base):
    def test_W1_parent_directories_created(self):
        self.build(cfg={**minimal_config(), "paths": {"index": "a/b/c/INDEX.md"}})
        self.assertFalse(os.path.lexists(os.path.join(self.work, DEC)))
        index.regenerate(self.work, self.cfg)
        for rel in (DEC_INDEX, F_INDEX, IN_FORCE, "a/b/c/INDEX.md"):
            self.assertTrue(stat.S_ISREG(os.lstat(os.path.join(self.work, rel)).st_mode), rel)

    OTHER_ARCH = {**minimal_config(), "paths": {"architecture": "arch.md"}}  # so render does not read docs/

    def test_W2_symlinked_parent_of_index_refused(self):
        self.build(cfg=self.OTHER_ARCH)
        real = os.path.join(self.tmp, "realdocs")
        os.mkdir(real)
        os.makedirs(os.path.join(self.work, "docs"))
        os.symlink(real, os.path.join(self.work, "docs/strict-delivery"))
        self.refused("docs/strict-delivery: is a symlink", lambda: index.regenerate(self.work, self.cfg))
        self.assertEqual(os.listdir(real), [])
        for rel in ORDER[:3]:
            self.assertFalse(os.path.lexists(os.path.join(self.work, rel)), rel)

    def test_W2_output_symlink_replaced_not_followed(self):
        self.build()
        os.makedirs(os.path.join(self.work, DEC))
        target = os.path.join(self.tmp, "target.yml")
        with open(target, "w") as fh:
            fh.write("keep\n")
        os.symlink(target, os.path.join(self.work, DEC_INDEX))
        index.regenerate(self.work, self.cfg)
        self.assertTrue(stat.S_ISREG(os.lstat(os.path.join(self.work, DEC_INDEX)).st_mode))
        self.assertEqual(self.read(DEC_INDEX), EMPTY_FILES[DEC_INDEX])
        with open(target) as fh:
            self.assertEqual(fh.read(), "keep\n")

    def test_W3_output_is_a_fifo(self):  # owner Q-1c3-RR1 (a), as Store.replace
        self.build()
        os.makedirs(os.path.join(self.work, "docs/strict-delivery"))
        os.mkfifo(os.path.join(self.work, INDEX_MD))
        self.refused(INDEX_MD + ": is not a regular file", lambda: index.regenerate(self.work, self.cfg))
        self.assertTrue(stat.S_ISFIFO(os.lstat(os.path.join(self.work, INDEX_MD)).st_mode))
        for rel in ORDER[:3]:
            self.assertFalse(os.path.lexists(os.path.join(self.work, rel)), rel)
        out, err, code = run_main(["--root", self.work])
        self.assertEqual((out, err, code), ("", "index: %s: is not a regular file\n" % INDEX_MD, 1))

    def test_W3_output_is_a_directory(self):
        self.build()
        os.makedirs(os.path.join(self.work, INDEX_MD))
        self.refused(INDEX_MD + ": is a directory", lambda: index.regenerate(self.work, self.cfg))
        for rel in ORDER[:3]:
            self.assertFalse(os.path.lexists(os.path.join(self.work, rel)), rel)

    def test_W3_parent_is_a_regular_file(self):
        self.build(cfg=self.OTHER_ARCH)
        self.put("docs/strict-delivery", "a file")
        self.refused("docs/strict-delivery: is not a directory", lambda: index.regenerate(self.work, self.cfg))
        for rel in ORDER[:3]:
            self.assertFalse(os.path.lexists(os.path.join(self.work, rel)), rel)

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root writes everywhere")
    def test_W3_read_only_parent(self):
        self.build()
        d = os.path.join(self.work, "docs/strict-delivery")
        os.makedirs(d)
        os.chmod(d, 0o555)
        self.addCleanup(os.chmod, d, 0o755)
        self.refused(INDEX_MD + ": cannot write", lambda: index.regenerate(self.work, self.cfg))
        self.assertEqual(os.listdir(d), [])
        self.build()
        p = os.path.join(self.work, "docs")
        os.makedirs(p)
        os.chmod(p, 0o555)
        self.addCleanup(os.chmod, p, 0o755)
        self.refused("docs/strict-delivery: cannot create the directory",
                     lambda: index.regenerate(self.work, self.cfg))

    def test_W4_failed_replace_leaves_old_file_and_no_temp(self):
        self.build()
        index.regenerate(self.work, self.cfg)
        write_record(self.work, DEC + "/%s.yml" % DA, lasting(DA))
        real = os.replace

        def fail_on_in_force(src, dst):
            if dst.endswith("in-force.md"):
                raise OSError(28, "No space left on device")
            return real(src, dst)

        with mock.patch("gates.tools.index.os.replace", fail_on_in_force):
            self.refused(IN_FORCE + ": cannot write (No space left on device)",
                         lambda: index.regenerate(self.work, self.cfg))
        self.assertEqual(self.read(IN_FORCE), INFORCE_HEAD)  # the old file, whole
        self.assertEqual(sorted(os.listdir(os.path.join(self.work, DEC))), sorted(["%s.yml" % DA, "index.yml",
                                                                                   "in-force.md"]))
        with mock.patch("gates.tools.index.os.fsync", side_effect=OSError(5, "Input/output error")):
            self.refused(DEC_INDEX + ": cannot write (Input/output error)",
                         lambda: index.regenerate(self.work, self.cfg))
        self.assertEqual(sorted(os.listdir(os.path.join(self.work, DEC))), sorted(["%s.yml" % DA, "index.yml",
                                                                                   "in-force.md"]))
        self.assertEqual(Store(self.work, "decision", self.cfg).load()[0].id, DA)  # no temp left to break load

    def test_W4_fdopen_failure_leaves_no_temp(self):
        self.build()
        os.makedirs(os.path.join(self.work, DEC))
        fds = []
        real_mkstemp = tempfile.mkstemp

        def mkstemp(**kw):
            fd, path = real_mkstemp(**kw)
            fds.append(fd)
            return fd, path

        with mock.patch("gates.tools.index.os.fdopen", side_effect=OSError(24, "Too many open files")), \
                mock.patch("gates.tools.index.tempfile.mkstemp", mkstemp):
            self.refused(DEC_INDEX + ": cannot write (Too many open files)",
                         lambda: index.regenerate(self.work, self.cfg))
        self.assertEqual(os.listdir(os.path.join(self.work, DEC)), [])
        self.assertEqual(len(fds), 1)
        with self.assertRaises(OSError):  # the descriptor was closed
            os.fstat(fds[0])

    def test_W4_emit_failure_refused(self):
        self.build()
        with mock.patch("gates.tools.index.yamlsub.emit", side_effect=yamlsub.EmitError("nesting too deep")):
            self.refused(DEC_INDEX + ": cannot emit (nesting too deep)")
            self.refused(DEC_INDEX + ": cannot emit", lambda: index.regenerate(self.work, self.cfg))
        self.assert_nothing_written()

    def umask(self, mask):
        old = os.umask(mask)
        self.addCleanup(os.umask, old)

    def mode(self, rel):
        return stat.S_IMODE(os.lstat(os.path.join(self.work, rel)).st_mode)

    def test_W6_existing_file_keeps_its_mode(self):  # owner Q-1c3-R2 (b), as Store.replace
        self.umask(0o077)
        root = self.build()
        index.regenerate(root, self.cfg)
        for want in (0o644, 0o600, 0o640):
            for rel in ORDER:
                os.chmod(os.path.join(root, rel), want)
            self.assertEqual(run_main(["--root", root]), (WRITTEN, "", 0))
            self.assertEqual([self.mode(rel) for rel in ORDER], [want] * 4, oct(want))

    def test_W6_new_file_takes_the_umask(self):  # owner Q-1c3-R2 (b), as Store.create
        for mask, want in ((0o022, 0o644), (0o077, 0o600), (0o002, 0o664)):
            self.umask(mask)
            root = self.build()
            self.assertEqual(run_main(["--root", root]), (WRITTEN, "", 0))
            self.assertEqual([self.mode(rel) for rel in ORDER], [want] * 4, oct(mask))
            self.assertEqual(os.umask(mask), mask)  # the umask is left as it was

    def test_W6_replaced_symlink_takes_the_umask(self):
        self.umask(0o022)
        self.build()
        os.makedirs(os.path.join(self.work, DEC))
        target = os.path.join(self.tmp, "target.yml")
        with open(target, "w") as fh:
            fh.write("keep\n")
        os.chmod(target, 0o600)
        os.symlink(target, os.path.join(self.work, DEC_INDEX))
        index.regenerate(self.work, self.cfg)
        self.assertEqual(self.mode(DEC_INDEX), 0o644)
        self.assertEqual(stat.S_IMODE(os.stat(target).st_mode), 0o600)

    def test_W6_unreadable_target_refused(self):
        self.build()
        real = os.lstat

        def lstat(p, *a, **kw):
            if p.endswith("INDEX.md"):
                raise OSError(13, "Permission denied")
            return real(p, *a, **kw)

        with mock.patch("gates.tools.index._check_target"), mock.patch("gates.tools.index.os.lstat", lstat):
            self.refused(INDEX_MD + ": cannot read (Permission denied)", lambda: index.regenerate(self.work, self.cfg))
        self.assertFalse(os.path.lexists(os.path.join(self.work, INDEX_MD)))

    def test_W5_return_value(self):
        self.build()
        self.assertEqual(index.regenerate(self.work, self.cfg), ORDER)


# ---------------------------------------------------------------- I: repository integration

class Integration(Base):
    def test_generated_paths_ignored_in_this_repo(self):  # I1
        cfg = config.load(REPO)
        p = cfg["paths"]
        paths = [p["decisions"] + "/index.yml", p["findings"] + "/index.yml", p["decisions"] + "/in-force.md",
                 p["index"]]
        self.assertEqual(paths, ORDER)
        for rel in paths:
            r = subprocess.run(["git", "check-ignore", "-q", "--", rel], cwd=REPO)
            self.assertEqual(r.returncode, 0, rel)
        with open(os.path.join(REPO, ".gitignore"), encoding="utf-8") as fh:
            lines = fh.read().splitlines()
        for rel in sorted(ORDER):
            self.assertIn(rel, lines)

    def test_I2_producers_registry(self):
        self.assertIn("gates.tools.index", producers.PRODUCER_MODULES)
        self.assertTrue({"decision-index", "finding-index", "in-force", "overview"} <= schema.produced_kinds())

    def test_gate_schema_skips_absent_generated(self):  # I2, OQ-17
        root = self.build(decs=[lasting(DA)], fins=[fnd(FA)])
        res = gate_schema.check(["--root", root])
        self.assertTrue(res.ok(), res.render(False))
        for k in ("decision-index", "finding-index", "in-force", "overview"):
            self.assertIn("PASS schema.%s\n" % k, res.render(False))
        index.regenerate(root, self.cfg)
        res = gate_schema.check(["--root", root])
        self.assertTrue(res.ok(), res.render(False))
        self.put(INDEX_MD, "<!-- schema: overview/1 -->\n## Architecture\n")
        self.put(DEC_INDEX, "schema: decision-index/1\n")
        res = gate_schema.check(["--root", root]).render(False)
        self.assertIn("FAIL schema.overview.%s: headings:" % INDEX_MD, res)
        self.assertIn("FAIL schema.decision-index.%s: decisions: required key is missing" % DEC_INDEX, res)

    def test_I3_regenerated_tree_stays_clean_and_green(self):
        with open(os.path.join(REPO, ".gitignore"), encoding="utf-8") as fh:
            ignore = fh.read()
        root = self.build(decs=[lasting(DA, landed_in=["CLAUDE.md"]), dec(DB, "open")], fins=[fnd(FA)],
                          files={".gitignore": ignore, "CLAUDE.md": "rule %s\n" % DA, ARCH: "## A\n"})
        index.regenerate(root, self.cfg)
        self.assertEqual(git(root, "status", "--porcelain", "--untracked-files=all"), "")
        self.assertTrue(gate_schema.check(["--root", root]).ok())
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = gate_decisions.main(["--root", root])
        self.assertEqual(code, 0, out.getvalue())

    def test_I4_generated_files_and_other_gates(self):
        with open(os.path.join(REPO, ".gitignore"), encoding="utf-8") as fh:
            ignore = fh.read()
        root = self.build(decs=[dec(DB, "open")], files={".gitignore": ignore, ARCH: "## About %s\n" % DB})
        index.regenerate(root, self.cfg)
        self.assertIn("- About %s\n" % DB, self.read(INDEX_MD))
        self.assertEqual([r.id for r in Store(root, "decision", self.cfg).load()], [DB])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            gate_decisions.main(["--root", root])
        fails = [ln for ln in out.getvalue().splitlines() if ln.startswith("FAIL decisions.open-ref.")]
        self.assertEqual(fails, ["FAIL decisions.open-ref.%s:1: %s:1 references unanswered %s; the human answers "
                                 "it first" % (ARCH, ARCH, DB)])


if __name__ == "__main__":
    unittest.main()
