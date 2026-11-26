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
from gates.lib import config, programs, schema, yamlsub
from gates.lib.result import GateError
from gates.lib.store import Store
from gates.tools import decisions_cli, index
from tests.helpers import (INT_LIMITS, GitIsolatedTestCase, cached_history, commit_all, git, int_limit, make_repo,
                           minimal_config, write_record)
from tests.test_cleanup_lib import mline

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
    r = {"schema": _tag("finding"), "id": id_, "status": status, "source": "review", "severity": "HIGH",
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
    INDEX_MD: ("<!-- schema: overview/2 -->\n\n## Architecture\nnone\n\n## Specs and plans\n### Todo\nnone\n"
               "### In progress\nnone\n### Done\nnone\n\n## Live programs\nnone\n\n## Open findings\n" + SEV_ZERO
               + "\n## In-force decisions\n0 in force: "
               "[in\\-force\\.md](<\\.\\.\\/\\.\\.\\/\\.strict\\-delivery\\/state\\/decisions\\/in\\-force\\.md>)\n"),
}


class Base(GitIsolatedTestCase):
    def build(self, decs=(), fins=(), files=None, cfg=None, commit=True):
        """A fresh fixture repository under self.tmp, made self.work (nothing is ever deleted)."""
        self.n = getattr(self, "n", 0) + 1
        self.work = os.path.join(self.tmp, "w%d" % self.n)
        os.mkdir(self.work)

        def make(root):  # built once per process and copied (row F11: no test here reads dates, the reflog or mtimes)
            make_repo(root, cfg)
            c = config.load(root)
            for r in decs:
                write_record(root, "%s/%s.yml" % (c["paths"]["decisions"], r["id"]), r)
            for r in fins:
                write_record(root, "%s/%s.yml" % (c["paths"]["findings"], r["id"]), r)
            for rel, data in (files or {}).items():
                self.put(rel, data, root)
            if commit:
                commit_all(root, "fixture")
        root, _ = cached_history(("test_index.build", repr((decs, fins, files, cfg, commit))), self.work, make)
        self.cfg = config.load(root)
        return root

    def put(self, rel, data, root=None):
        path = os.path.join(root or self.work, rel)
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


class CachedKeyTests(Base):
    """F-20261126-yga8, row F11: every part of the ``cached_history`` key of ``Base.build`` (decs, fins, files, cfg,
    commit) is pinned: two builds that differ only in that part get different histories (a key without the part
    would hand the second call the first call's history)."""

    def fingerprint(self, root):
        data = {}
        for base, dirs, names in os.walk(root):
            dirs[:] = [d for d in dirs if d != ".git"]
            for n in names:
                with open(os.path.join(base, n), "rb") as fh:
                    data[os.path.relpath(os.path.join(base, n), root)] = fh.read()
        return (data, git(root, "status", "--porcelain", "--untracked-files=all"), git(root, "rev-list", "--count", "HEAD"))

    def differ(self, a, b):
        one = self.fingerprint(self.build(**a))
        two = self.fingerprint(self.build(**b))
        self.assertNotEqual(one, two)
        self.assertEqual(self.fingerprint(self.build(**a)), one)  # each call alone is stable

    def test_key_part_decs(self):
        self.differ({"decs": [dec("Q-AAA-1")]}, {"decs": [dec("Q-BBB-1")]})

    def test_key_part_fins(self):
        self.differ({"fins": [fnd("F-20260101-aaaa")]}, {"fins": [fnd("F-20260101-bbbb")]})

    def test_key_part_files(self):
        self.differ({"files": {"a.txt": "a\n"}}, {"files": {"b.txt": "b\n"}})

    def test_key_part_cfg(self):
        self.differ({"cfg": None}, {"cfg": {**minimal_config(), "decision_classes": {"owner_only": ["hardware"]}}})

    def test_key_part_commit(self):
        rows = [fnd("F-20260101-aaaa")]
        self.differ({"fins": rows, "commit": True}, {"fins": rows, "commit": False})


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
        self.assertEqual(err.getvalue(), "usage: python3 -m gates <command> [args]\ncommands: check, claims, context, continue, decisions, findings, githook, githooks, hook, index, loopstats, program, questions, receipt, run_all\n")


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
        self.assertEqual(headings(files[INDEX_MD]), ["## Architecture", "## Specs and plans", "## Live programs",
                                                     "## Open findings", "## In-force decisions"])
        self.assertEqual(files[INDEX_MD].splitlines()[0], "<!-- schema: overview/2 -->")

    def test_F8_overview_text(self):
        self.build(decs=[lasting(DA), lasting(DB)], fins=[fnd(FB, severity="LOW", **{"class": "leak"}),
                                                          fnd(FA, "planned"), fnd(FC, "closed")],
                   files={ARCH: "# Title\n\n## Layers\ntext\n### Deep\n## Data flow\n"})
        self.assertEqual(self.render()[INDEX_MD], (
            "<!-- schema: overview/2 -->\n\n## Architecture\n[architecture\\.md](<architecture\\.md>)\n- Layers\n"
            "- Data flow\n\n## Specs and plans\n### Todo\nnone\n### In progress\nnone\n### Done\nnone\n\n"
            "## Live programs\nnone\n\n## Open findings\n- CRITICAL: 0\n- HIGH: 1\n- MEDIUM: 0\n- LOW: 1\n- INFO: 0\n"
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
        self.assertIn("## Architecture\n%s\n\n## Specs" % mdlink("architecture.md", "architecture.md"),
                      self.render()[INDEX_MD])
        self.put(ARCH, "## Architecture\n## Open findings\n")
        md = self.render()[INDEX_MD]
        self.assertIn("- Architecture\n- Open findings\n", md)
        self.assertEqual(headings(md),
                         ["## Architecture", "## Specs and plans", "## Live programs", "## Open findings",
                          "## In-force decisions"])

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
                          ("in-force", 1, "markdown"), ("overview", 2, "markdown")])
        self.assertEqual(loaded["decision-index"].files, [{"dir": "decisions", "glob": "index.yml"}])
        self.assertEqual(loaded["finding-index"].files, [{"dir": "findings", "glob": "index.yml"}])
        self.assertEqual(loaded["in-force"].files, [{"dir": "decisions", "glob": "in-force.md"}])
        self.assertEqual(loaded["overview"].files, [{"path": "index"}])
        self.assertEqual(loaded["in-force"].table, ["id", "topics", "rule", "landed_in"])
        self.assertEqual(loaded["overview"].headings,
                         ["## Architecture", "## Specs and plans", "## Live programs", "## Open findings",
                          "## In-force decisions"])
        self.assertEqual((loaded["in-force"].first_line, loaded["overview"].first_line),
                         ("<!-- schema: in-force/1 -->", "<!-- schema: overview/2 -->"))
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
        self.assertEqual(schema.validate(s, {"schema": _tag("decision-index"), "decisions": [good]}, self.cfg_d()), [])
        self.assertEqual(schema.validate(s, {"schema": _tag("decision-index"), "decisions": [
            dict(good, status="closed", extra=1)]}, self.cfg_d()),
            ["decisions.0.status: must be one of open, answered, withdrawn, superseded", "decisions.0.extra: unknown key"])
        f = schema.load_schema(os.path.join(schema.SCHEMAS_DIR, "finding-index.yml"))
        fgood = {"id": FA, "file": "x", "status": "merged", "severity": "INFO", "owner": "issue:3"}
        self.assertEqual(schema.validate(f, {"schema": _tag("finding-index"), "findings": [fgood]}, self.cfg_d()), [])
        self.assertEqual(schema.validate(f, {"schema": _tag("finding-index"), "findings": [dict(fgood, id=DA)]},
                                         self.cfg_d())[0][:14], "findings.0.id:")
        self.assertEqual(schema.validate(f, {"schema": _tag("finding-index")}, self.cfg_d()),
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
        self.assertEqual(headings(files[INDEX_MD]),
                         ["## Architecture", "## Specs and plans", "## Live programs", "## Open findings",
                          "## In-force decisions"])
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
        self.put(INDEX_MD, "<!-- schema: %s -->\n## Architecture\n" % _tag("overview"))
        self.put(DEC_INDEX, "schema: %s\n" % _tag("decision-index"))
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
        # RG7: a pending id printed by "Pending owner questions:" is in INDEX.md, which is ignored, so not reported
        git(root, "checkout", "-q", "-b", PNAME + "/integration")
        d = "%s/%s" % (PROGS, PNAME)
        streams = {"schema": "streams/1", "program": PNAME, "streams": [{"id": "a", "plan": PLANS + "/a-plan.md"}]}
        self.put(d + "/streams.yml", yamlsub.emit(streams))
        self.put(d + "/status.md", status_page([{"pending decisions": DB}]))
        self.put(d + "/sync-log.md", "log\n")
        self.put(d + "/merged.md", "log\n")
        commit_all(root, "program")
        git(root, "checkout", "-q", "main")
        index.regenerate(root, self.cfg)
        self.assertIn("- %s: Keep X?\n" % DB, self.read(INDEX_MD))
        commit_all(root, "a careless git add -A")  # adds INDEX.md unless .gitignore ignores it
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            gate_decisions.main(["--root", root])
        fails = [ln for ln in out.getvalue().splitlines() if ln.startswith("FAIL decisions.open-ref.")]
        self.assertEqual(fails, ["FAIL decisions.open-ref.%s:1: %s:1 references unanswered %s; the human answers "
                                 "it first" % (ARCH, ARCH, DB)])


    def test_render_loads_the_repository_itself(self):
        # every tracked handoff, program and status file of this tree is read by render; one that does not load
        # refuses every command that re-renders the index (5b.1 review 1, HIGH)
        files = index.render(REPO, config.load(REPO))
        self.assertIn(INDEX_MD, files)




# ------------------------------------------------ Task 5b.1: overview/2 (rows SC, RN, PL, SP, LP, HI, RG, SK)

PLANS = "docs/strict-delivery/plans"
SPECS = "docs/strict-delivery/specs"
PS = ".strict-delivery/state/plans"
PROGS = ".strict-delivery/state/programs"
PNAME = "20261101-x"
INTEG = PNAME + "/integration"
RID, RID2 = "R-20261105-a2b3", "R-20261105-c4d5"
PD1, PD2, PD3 = "DEC-20261105-bn3p", "DEC-20261105-j2k3", "DEC-20261105-m4n5"
LABELS = ("Open requests:", "Pending owner questions:")
SROW = {"stream": "a", "block": "5a", "branch": "b", "worktree": "w", "next task": "t", "estimate": "10", "used": "3",
        "status": "running", "blockers": "none", "pending decisions": "none", "delivers": "d"}
SEV5 = "- CRITICAL: 0\n- HIGH: 0\n- MEDIUM: 0\n- LOW: 0\n- INFO: 0\n"
IFLINK = ("[in\\-force\\.md](<\\.\\.\\/\\.\\.\\/\\.strict\\-delivery\\/state\\/decisions\\/in\\-force\\.md>)")
NONE_PROGRAM_TAIL = "\n## Open findings\n" + SEV5 + "\n## In-force decisions\n0 in force: " + IFLINK + "\n"
LEDGER_HEAD = "<!-- schema: ledger/1 -->\n"


def status_page(rows):
    h = programs.STATUS_HEADERS
    lines = ["| " + " | ".join(h) + " |", "|" + "|".join("---" for _ in h) + "|"]
    for r in rows:
        d = dict(SROW, **r)
        lines.append("| " + " | ".join(str(d[k]).replace("|", "\\|") for k in h) + " |")
    return "\n".join(lines) + "\n"


def sect(md, label):
    """The lines under ``label`` up to the next heading, label or blank line (own splitter)."""
    out, on = [], False
    for ln in md.split("\n"):
        if on and (ln == "" or ln.startswith("## ") or ln.startswith("### ") or ln in LABELS):
            break
        if on:
            out.append(ln)
        elif ln == label:
            on = True
    return out


def ho_text(block="2a", spec=None, plan="p"):
    row = {"schema": "handoff/1", "plan": plan, "block": block}
    if spec is not None:
        row["spec"] = spec
    return "---\n" + yamlsub.emit(row) + "---\nbody\n"


def req(rid=RID, status="open", need="x", frm="a", to="b"):
    return {"schema": "request/1", "id": rid, "from_stream": frm, "to_stream": to, "files": ["x"], "need": need,
            "status": status}


class Ov(Base):
    def ov(self, **kw):
        cfg = minimal_config()
        cfg["merge"] = {"mode": "controller"}
        cfg.update(kw.pop("cfg", {}))
        root = self.build(cfg=cfg, **kw)
        for k, v in (("color.ui", "always"), ("color.diff", "always"), ("core.abbrev", "7")):
            git(root, "config", k, v)
        return root

    def idx(self):
        return self.render()[INDEX_MD]

    def commit(self, msg="c"):
        return commit_all(self.work, msg)

    def plan(self, name, text="plan\n"):
        self.put("%s/%s" % (PLANS, name), text)

    def program(self, name=PNAME, rows=None, requests=(), streams=None, files=None, status=None, stext="log\n"):
        git(self.work, "checkout", "-q", "-b", name + "/integration")
        d = "%s/%s" % (PROGS, name)
        s = streams if streams is not None else {"schema": "streams/1", "program": name,
                                                 "streams": [{"id": "a", "plan": PLANS + "/a-plan.md"}]}
        self.put(d + "/streams.yml", s if type(s) is str else yamlsub.emit(s))
        self.put(d + "/status.md", status if status is not None else status_page(rows if rows is not None else [{}]))
        self.put(d + "/sync-log.md", stext)
        self.put(d + "/merged.md", stext)
        for r in requests:
            self.put("%s/requests/%s.yml" % (d, r["id"]), yamlsub.emit(r))
        for rel, t in (files or {}).items():
            self.put(rel, t)
        self.commit("program " + name)
        git(self.work, "checkout", "-q", "main")

    def merged(self, slug="d", how="no-ff", final="yes", ledger=True, files=None):
        r = self.work
        git(r, "checkout", "-q", "-b", "t-" + slug, "main")
        self.plan(slug + ".md")
        self.put("%s/%s/notes.md" % (PS, slug), "notes\n")
        # merged_errors: the merge must touch the plan's state folder
        for k, v in (files or {}).items():
            self.put(k, v)
        head = commit_all(r, "work " + slug)
        git(r, "checkout", "-q", "main")
        if how == "no-ff":
            git(r, "merge", "-q", "--no-ff", "-m", "Merge " + slug, "t-" + slug)
        else:
            git(r, "merge", "-q", "--squash", "t-" + slug)
            git(r, "commit", "-q", "-m", "squash " + slug)
        merge = git(r, "rev-parse", "HEAD")
        if ledger:
            self.put("%s/%s/ledger.md" % (PS, slug), LEDGER_HEAD + mline(head, merge, final=final) + "\n")
            self.commit("ledger " + slug)
        return head, merge

    def sec(self, label):
        return sect(self.idx(), label)


class Overview2(Ov):
    # ---- SC, RN
    def test_overview_2_headings(self):  # RN1, SC3
        self.ov(decs=[lasting(DA)], fins=[fnd(FA)], files={ARCH: "# T\n## One\n"})
        md = self.idx()
        self.assertEqual(headings(md), ["## Architecture", "## Specs and plans", "## Live programs", "## Open findings",
                                        "## In-force decisions"])
        self.assertEqual(md.splitlines()[0], "<!-- schema: overview/2 -->")

    def test_overview_1_file_fails_schema_until_index(self):  # SC4, RG2
        root = self.ov()
        self.put(INDEX_MD, EMPTY_FILES[INDEX_MD].replace("overview/2", "overview/1"))
        res = gate_schema.check(["--root", root]).render(False)
        self.assertIn("FAIL schema.overview.%s: first line: expected '<!-- schema: overview/2 -->'" % INDEX_MD, res)
        index.regenerate(root, self.cfg)
        self.assertTrue(gate_schema.check(["--root", root]).ok())

    def test_no_overview_migration_registered(self):  # SC5
        from gates.lib import migrations
        self.assertNotIn(("overview", 1), migrations.MIGRATIONS)
        row = {"schema": "overview/1", "k": 1}
        self.assertEqual(migrations.migrate("overview", dict(row)), row)

    def test_schema_version_only_in_schema_file(self):  # SC7
        hits = []
        for base, _, names in os.walk(os.path.join(REPO, "gates")):
            for n in names:
                if n.endswith((".py", ".yml")):
                    with open(os.path.join(base, n), encoding="utf-8") as fh:
                        if "overview/1" in fh.read():
                            hits.append(os.path.relpath(os.path.join(base, n), REPO))
        self.assertEqual(hits, [])
        from gates.lib import migrations
        self.assertEqual(migrations.current_version("overview"), 2)

    def test_empty_sections_say_none(self):  # RN3, PL1, LP1
        self.ov()
        self.assertEqual(self.idx(), EMPTY_FILES[INDEX_MD])
        for lab in ("### Todo", "### In progress", "### Done"):
            self.assertEqual(self.sec(lab), ["none"], lab)
        self.assertEqual(self.sec("## Live programs"), ["none"])

    def test_plans_none(self):  # PL1
        self.ov(files={PLANS + "/.gitkeep": ""})
        for lab in ("### Todo", "### In progress", "### Done"):
            self.assertEqual(self.sec(lab), ["none"], lab)

    def test_plan_states(self):  # RN4, PL2, PL3
        self.ov(files={PLANS + "/t.md": "p\n", PLANS + "/p.md": "p\n", PS + "/p/handoff.md": ho_text("2a")})
        self.assertEqual(self.sec("### Todo"), ["- " + PLANS + "/t.md"])
        self.assertEqual(self.sec("### In progress"), ["- " + PLANS + "/p.md (block 2a)"])
        self.assertEqual(self.sec("### Done"), ["none"])
        lines = self.idx().split("\n")
        at = lines.index("## Specs and plans")
        self.assertEqual(lines[at + 1:at + 2] + [x for x in lines[at:] if x.startswith("### ")][:3],
                         ["### Todo", "### Todo", "### In progress", "### Done"])

    def test_no_content_line_is_a_heading(self):  # RN5, LP10
        evil = "## x"
        self.ov(files={PLANS + "/a-plan.md": "p\n", PS + "/a-plan/handoff.md": ho_text(evil),
                       SPECS + "/s.md": "s\n", PLANS + "/x\n## Evil.md": "p\n"})
        self.commit("evil")
        self.program(rows=[dict(block=evil, stream="a", status=evil, blockers=evil, used=evil, estimate=evil,
                                **{"pending decisions": PD1, "delivers": evil})],
                     requests=[req(need="n\n## evil\x00", frm="a", to="b")],
                     files={DEC + "/%s.yml" % PD1: yamlsub.emit(dec(PD1, "open", question="which?\n## h"))})
        md = self.idx()
        self.assertEqual(headings(md), ["## Architecture", "## Specs and plans", "## Live programs", "## Open findings",
                                        "## In-force decisions"])
        for ln in md.split("\n"):
            if ln and not ln.startswith("## "):
                self.assertTrue(ln.startswith(("- ", "### ", "none", "Open requests:", "Pending owner questions:",
                                               "<!--", "[", "0 in force")), repr(ln))
        self.assertIn("- a | ## x | ## x | used ## x of ## x | blockers ## x | pending " + PD1, md)
        self.assertIn("- %s a -> b open: n\\n## evil\\x00" % RID, md)
        self.assertIn("- %s: which?\\n## h" % PD1, md)

    def test_regenerate_is_idempotent(self):  # RN6, RN7
        root = self.ov(files={PLANS + "/t.md": "p\n", SPECS + "/s.md": "s\n"})
        self.program(requests=[req()])
        self.assertEqual(self.render(), self.render())
        a = [self.read(p) for p in index.regenerate(root, self.cfg)]
        b = [self.read(p) for p in index.regenerate(root, self.cfg)]
        self.assertEqual(a, b)

    def test_overview_2_bytes_are_the_hand_written_text(self):  # RN8, LP6, LP13, LP18
        self.ov(decs=[lasting(DA)], fins=[fnd(FA)], files={
            PLANS + "/t.md": "p\n", PLANS + "/a-plan.md": "p\n", PLANS + "/p.md": "p\n", PLANS + "/d.md": "p\n",
            SPECS + "/s.md": "s\n", SPECS + "/z.md": "s\n", PS + "/p/handoff.md": ho_text("2a", [SPECS + "/s.md"])})
        git(self.work, "rm", "-q", PLANS + "/d.md")
        self.commit("rm d")
        rows = [dict(stream="a", block="5a", estimate="10", used="3", **{"pending decisions": PD1}),
                dict(stream="b", block="6b", estimate="5", used="0", status="blocked", blockers=RID)]
        self.program(rows=rows, requests=[req(), req(RID2, "done")],
                     files={DEC + "/%s.yml" % PD1: yamlsub.emit(dec(PD1, "open", question="which?"))})
        expected = (
            "<!-- schema: overview/2 -->\n\n## Architecture\nnone\n\n## Specs and plans\n### Todo\n"
            "- %(P)s/t.md\n- %(S)s/z.md\n### In progress\n- %(P)s/a-plan.md (program 20261101-x, stream a, block 5a)\n"
            "- %(P)s/p.md (block 2a)\n- %(S)s/s.md\n### Done\n- %(P)s/d.md (merge not recorded)\n\n"
            "## Live programs\n### 20261101-x\n- a | 5a | running | used 3 of 10 | blockers none | pending %(D)s\n"
            "- b | 6b | blocked | used 0 of 5 | blockers %(R)s | pending none\nOpen requests:\n"
            "- %(R)s a -> b open: x\nPending owner questions:\n- %(D)s: which?\n\n## Open findings\n"
            "- CRITICAL: 0\n- HIGH: 1\n- MEDIUM: 0\n- LOW: 0\n- INFO: 0\n- %(F)s (HIGH, open): bug\n\n"
            "## In-force decisions\n1 in force: %(L)s\n") % {"P": PLANS, "S": SPECS, "D": PD1, "R": RID, "F": FA,
                                                             "L": IFLINK}
        self.assertEqual(self.idx(), expected)

    def test_render_writes_nothing_overview_2(self):  # RN9
        self.ov(files={PLANS + "/t.md": "p\n"})
        self.program()
        before = subprocess.run(["find", self.work, "-not", "-path", "*/.git/*", "-ls"], stdout=subprocess.PIPE)
        self.render()
        self.assert_nothing_written()
        self.assertEqual(git(self.work, "status", "--porcelain", "--untracked-files=all"), "")
        self.assertEqual(before.returncode, 0)

    def test_render_first_failure_is_the_register(self):  # RN10
        self.ov(decs=[dec(DA, **{"class": "nonsense"})])
        self.program(streams="not: [valid")
        self.refused(DA + ".yml")

    def test_render_unloadable_inputs_are_gate_errors(self):  # RN11, LP16, LP32, LP33
        self.ov(files={PLANS + "/p.md": "p\n", PS + "/p/handoff.md": "garbage\n"})
        self.refused(PS + "/p/handoff.md")
        git(self.work, "rm", "-q", PS + "/p/handoff.md")
        self.commit("rm ho")
        self.program(streams="a: [")
        self.refused(PROGS + "/%s/streams.yml" % PNAME)

    def test_render_consumers_refuse_on_unloadable_program(self):  # RN12, RG5
        root = self.ov()
        self.program(streams="a: [")
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            code = decisions_cli.main(["ask", "--class", "scope", "--question", "Keep?", "--option", "yes::none",
                                       "--option", "no::some", "--recommend", "yes", "--effect", "one-off",
                                       "--by", "me", "--root", root])
        self.assertEqual(code, 1)
        self.assertIn("streams.yml", err.getvalue())
        self.assertEqual(os.listdir(os.path.join(root, *DEC.split("/"))) if os.path.isdir(os.path.join(
            root, *DEC.split("/"))) else [], [])
        out, errs, code = run_main(["--root", root])
        self.assertEqual((out, code), ("", 1))
        self.assertTrue(errs.startswith("index: ") and "streams.yml" in errs, errs)

    def test_main_refusal_for_unloadable_program(self):  # RG5
        root = self.ov(files={PLANS + "/t.md": "p\n"})
        out, err, code = run_main(["--root", root])
        self.assertEqual((out, err, code), (WRITTEN, "", 0))
        self.program(streams="a: [")
        out, err, code = run_main(["--root", root])
        self.assertEqual((out, code), ("", 1))
        self.assertTrue(err.startswith("index: ") and "streams.yml" in err, err)

    def test_render_unborn_head(self):  # RN13, HI2
        self.work = os.path.join(self.tmp, "unborn")
        os.mkdir(self.work)
        git(self.work, "init", "-q", "-b", "main")
        self.put(".strict-delivery/config.yml", yamlsub.emit(dict(minimal_config(), merge={"mode": "controller"})))
        self.put(PLANS + "/t.md", "p\n")
        self.put(SPECS + "/s.md", "s\n")
        self.cfg = config.load(self.work)
        md = self.idx()
        self.assertEqual(self.sec("### Todo"), ["- " + PLANS + "/t.md", "- " + SPECS + "/s.md"])
        self.assertEqual(self.sec("### Done"), ["none"])
        self.assertEqual(self.sec("## Live programs"), ["none"])
        self.assertIn("<!-- schema: overview/2 -->", md)

    # ---- PL
    def test_stream_plan_in_progress_from_status_row(self):  # PL4
        self.ov(files={PLANS + "/a-plan.md": "p\n"})
        self.program(rows=[dict(stream="a", block="5a")])
        self.assertEqual(self.sec("### In progress"),
                         ["- %s/a-plan.md (program %s, stream a, block 5a)" % (PLANS, PNAME)])
        self.assertEqual(self.sec("### Todo"), ["none"])

    def test_program_plan_in_progress(self):  # PL5, Q9
        self.ov(files={PLANS + "/pp.md": "p\n"})
        self.program(streams={"schema": "streams/1", "program": PNAME, "plan": PLANS + "/pp.md",
                              "streams": [{"id": "a"}]})
        self.assertEqual(self.sec("### In progress"), ["- %s/pp.md (program %s)" % (PLANS, PNAME)])

    def test_stream_plan_without_status_row(self):  # PL6, Q9
        self.ov(files={PLANS + "/a-plan.md": "p\n"})
        self.program(rows=[dict(stream="b")])
        self.assertEqual(self.sec("### In progress"), ["- %s/a-plan.md (program %s, stream a)" % (PLANS, PNAME)])

    def test_stream_plan_file_absent_not_listed(self):  # PL7
        self.ov()
        self.program()
        self.assertEqual(self.sec("### In progress"), ["none"])
        self.assertEqual(self.sec("### Todo"), ["none"])

    def test_plan_named_twice_listed_once(self):  # PL8, Q9
        self.ov(files={PLANS + "/s.md": "p\n", PS + "/s/handoff.md": ho_text("3c", plan="s")})
        st = lambda n: {"schema": "streams/1", "program": n, "streams": [{"id": "a", "plan": PLANS + "/s.md"},
                                                                          {"id": "b", "plan": PLANS + "/s.md"}]}
        self.program("20261101-x", streams=st("20261101-x"))
        self.program("20261101-y", streams=st("20261101-y"))
        self.assertEqual(self.sec("### In progress"), ["- %s/s.md (block 3c)" % PLANS])  # handoff form wins
        git(self.work, "rm", "-q", PS + "/s/handoff.md")
        self.commit("rm")
        self.assertEqual(self.sec("### In progress"),
                         ["- %s/s.md (program 20261101-x, stream a, block 5a)" % PLANS])

    def test_plan_with_final_merge_is_done_cleanup_pending(self):  # PL9
        self.ov()
        head, merge = self.merged("d")
        self.assertEqual(self.sec("### Done"), ["- %s/d.md (merged %s; cleanup pending)" % (PLANS, merge)])
        self.assertEqual(merge, git(self.work, "log", "--merges", "--first-parent", "-1", "--format=%H", "main"))
        self.assertEqual((self.sec("### Todo"), self.sec("### In progress")), (["none"], ["none"]))

    def test_done_wins_over_handoff(self):  # PL10
        self.ov()
        head, merge = self.merged("d")
        self.put(PS + "/d/handoff.md", ho_text("2a", plan="d"))
        self.commit("ho")
        self.assertEqual(self.sec("### Done"), ["- %s/d.md (merged %s; cleanup pending)" % (PLANS, merge)])
        self.assertEqual(self.sec("### In progress"), ["none"])

    def test_plan_between_work_pr_and_cleanup_pr_reads_in_progress(self):  # PL11, HI6
        self.ov()
        head, merge = self.merged("d", final="no")
        self.put(PS + "/d/handoff.md", ho_text("9z", plan="d"))
        self.commit("ho")
        self.assertEqual(self.sec("### In progress"), ["- %s/d.md (block 9z)" % PLANS])
        git(self.work, "checkout", "-q", "-b", "cleanup/d")
        self.put(PS + "/d/ledger.md", LEDGER_HEAD + mline(head, merge) + "\n")
        self.commit("final line")
        self.assertEqual(self.sec("### Done"), ["- %s/d.md (merged %s; cleanup pending)" % (PLANS, merge)])
        git(self.work, "checkout", "-q", "main")
        self.assertEqual(self.sec("### In progress"), ["- %s/d.md (block 9z)" % PLANS])

    def test_head_is_cleanup_branch_vs_main(self):  # HI6, PL16
        self.ov()
        head, merge = self.merged("d")
        git(self.work, "checkout", "-q", "-b", "cleanup/d")
        git(self.work, "rm", "-q", PLANS + "/d.md", PS + "/d/ledger.md")
        self.commit("cleanup")
        self.assertEqual(self.sec("### Done"), ["- %s/d.md (merged %s)" % (PLANS, merge)])

    def test_deleted_plan_done_with_merge_commit(self):  # PL16
        self.ov()
        head, merge = self.merged("d")
        git(self.work, "rm", "-q", PLANS + "/d.md", PS + "/d/ledger.md")
        self.commit("cleanup")
        self.assertIn("- %s/d.md (merged %s)" % (PLANS, merge), self.sec("### Done"))

    def test_final_no_only_is_todo(self):  # PL12
        self.ov()
        self.merged("n", final="no")
        self.assertEqual(self.sec("### Todo"), ["- %s/n.md" % PLANS])
        self.assertEqual(self.sec("### Done"), ["none"])

    def test_final_no_only_with_handoff_in_progress(self):  # PL13
        self.ov()
        self.merged("n", final="no")
        self.put(PS + "/n/handoff.md", ho_text("4d", plan="n"))
        self.commit("ho")
        self.assertEqual(self.sec("### In progress"), ["- %s/n.md (block 4d)" % PLANS])

    def test_unverifiable_final_line_is_not_done(self):  # PL14
        for how in ("squash", "other-head"):
            with self.subTest(how):
                self.ov()
                if how == "squash":
                    self.merged("d", how="squash")
                else:
                    head, merge = self.merged("d", ledger=False)
                    other = git(self.work, "rev-parse", "main~1")
                    self.put(PS + "/d/ledger.md", LEDGER_HEAD + mline(other, merge) + "\n")
                    self.commit("ledger")
                self.assertEqual(self.sec("### Done"), ["none"])
                self.assertEqual(self.sec("### Todo"), ["- %s/d.md" % PLANS])

    def test_base_branch_missing_means_not_done(self):  # PL15
        self.ov()
        self.merged("d")
        git(self.work, "checkout", "-q", "-b", "trunk")
        git(self.work, "branch", "-q", "-D", "main")
        self.assertEqual(self.sec("### Done"), ["none"])
        self.assertEqual(self.sec("### Todo"), ["- %s/d.md" % PLANS])

    def test_deleted_plan_merge_not_recorded(self):  # PL17
        self.ov(files={PLANS + "/d.md": "p\n"})
        git(self.work, "rm", "-q", PLANS + "/d.md")
        self.commit("rm")
        self.assertEqual(self.sec("### Done"), ["- %s/d.md (merge not recorded)" % PLANS])

    def test_deleted_then_readded_present_wins(self):  # PL18
        self.ov(files={PLANS + "/a.md": "p\n"})
        git(self.work, "rm", "-q", PLANS + "/a.md")
        self.commit("rm")
        self.plan("a.md")
        self.commit("add")
        self.assertEqual((self.sec("### Todo"), self.sec("### Done")), (["- %s/a.md" % PLANS], ["none"]))

    def test_readded_uncommitted_present_wins(self):  # PL19
        self.ov(files={PLANS + "/b.md": "p\n"})
        git(self.work, "rm", "-q", PLANS + "/b.md")
        self.commit("rm")
        self.plan("b.md")
        self.assertEqual((self.sec("### Todo"), self.sec("### Done")), (["- %s/b.md" % PLANS], ["none"]))

    def test_plan_removed_uncommitted(self):  # PL20, PL21, Q15
        self.ov(files={PLANS + "/t.md": "p\n"})
        os.unlink(os.path.join(self.work, PLANS, "t.md"))
        for lab in ("### Todo", "### In progress", "### Done"):
            self.assertEqual(self.sec(lab), ["none"], lab)
        git(self.work, "rm", "-q", "--cached", PLANS + "/t.md")
        self.assertEqual(self.sec("### Done"), ["none"])

    test_plan_removed_staged = test_plan_removed_uncommitted

    def test_deletion_only_by_merge_commit_not_listed(self):  # PL22
        self.ov(files={PLANS + "/m.md": "p\n"})
        git(self.work, "checkout", "-q", "-b", "side")
        self.put("other.txt", "o\n")
        self.commit("side")
        git(self.work, "checkout", "-q", "main")
        self.put("other2.txt", "o\n")
        self.commit("main")
        git(self.work, "merge", "-q", "--no-ff", "--no-commit", "side")
        git(self.work, "rm", "-q", PLANS + "/m.md")
        git(self.work, "commit", "-q", "-m", "evil merge")
        self.assertEqual([self.sec(l) for l in ("### Todo", "### In progress", "### Done")], [["none"]] * 3)

    def test_non_md_not_a_plan(self):  # PL23
        self.ov(files={PLANS + "/b.txt": "x", PLANS + "/.keep": "", PLANS + "/notes.md.bak": "x",
                       PLANS + "/gone.txt": "x"})
        git(self.work, "rm", "-q", PLANS + "/gone.txt")
        self.commit("rm")
        self.assertEqual([self.sec(l) for l in ("### Todo", "### In progress", "### Done")], [["none"]] * 3)

    def test_nested_md_not_a_plan(self):  # PL24
        self.ov(files={PLANS + "/x/n.md": "p", PLANS + "/x/y/z.md": "p", PLANS + "/dir.md/in.md": "p",
                       PLANS + "/gone/n.md": "p", PS + "/n/handoff.md": ho_text(plan="n")})
        git(self.work, "rm", "-q", PLANS + "/gone/n.md")
        self.commit("rm")
        self.assertEqual([self.sec(l) for l in ("### Todo", "### In progress", "### Done")], [["none"]] * 3)

    def test_plan_file_kinds(self):  # PL25
        self.ov(files={PLANS + "/a.md": "p\n"})
        os.symlink("a.md", os.path.join(self.work, PLANS, "link.md"))
        os.mkdir(os.path.join(self.work, PLANS, "dir.md"))
        os.mkfifo(os.path.join(self.work, PLANS, "fifo.md"))
        self.assertEqual(self.sec("### Todo"), ["- %s/a.md" % PLANS])

    def test_plan_file_name_shapes(self):  # PL26, PL27, Q3, Q6
        names = ["Up_Per.md", "a.b.md", "é.md", ".md", ".hidden.md", "a b.md", "A.md", "a-.md", "-a.md",
                 "a\nb.md", "x\n## Evil.md", "d.md.md", "n" * 251 + ".md"]
        self.ov()
        for n in names:
            self.plan(n)
        self.commit("names")
        got = self.sec("### Todo")
        esc = lambda s: s.replace("\\", "\\\\").replace("\n", "\\n")
        self.assertEqual(got, ["- " + esc("%s/%s" % (PLANS, n)) for n in sorted(names)])
        self.assertEqual(headings(self.idx()), ["## Architecture", "## Specs and plans", "## Live programs",
                                                "## Open findings", "## In-force decisions"])
        for n in (".md", "Up_Per.md"):  # no slug: never in progress through a handoff
            self.put(PS + "/%s/handoff.md" % n[:-3], ho_text())
        self.assertEqual(self.sec("### In progress"), ["none"])

    def test_plan_entries_sorted_by_path(self):  # PL28, SK2
        names = ["B.md", "a.md", "Z.md", "é.md", "a-b.md", "ab.md", "Ꟁ.md", "aࡰ.md"]
        self.ov()
        for n in names:
            self.plan(n)
        got = self.sec("### Todo")
        raw = [PLANS + "/" + n for n in sorted(names)]
        esc = lambda s: s.replace(chr(0x870), "\\u0870").replace(chr(0xa7c0), "\\ua7c0")  # unassigned in UCD 13
        self.assertEqual(got, ["- " + esc(r) for r in raw])

    def test_unicode_same_on_both(self):  # SK2
        self.ov(files={PLANS + "/p.md": "p\n", PS + "/p/handoff.md": ho_text("aࡰb Ꟁ")})
        self.program(requests=[req(need="n\u0085  ࡰꟀ")],
                     files={DEC + "/%s.yml" % PD1: yamlsub.emit(dec(PD1, "open", question="qࡰꟀ"))},
                     rows=[dict(blockers="bࡰꟀ", **{"pending decisions": PD1})])
        md = self.idx()
        self.assertIn("- %s/p.md (block a\\u0870b \\ua7c0)" % PLANS, md)
        self.assertIn("a -> b open: n\\x85\\u2028\\xa0\\u0870\\ua7c0", md)
        self.assertIn("- %s: q\\u0870\\ua7c0" % PD1, md)
        self.assertIn("blockers b\\u0870\\ua7c0 |", md)

    def test_handoff_that_does_not_load_names_the_file(self):  # PL29
        h = os.path.join(self.tmp, "h")
        kinds = {"directory": None, "symlink": "link", "empty": b"", "non-utf8": b"---\n\xff\n---\n",
                 "crlf": b"---\r\nblock: 1\r\n---\r\n", "bom": b"\xef\xbb\xbf---\nblock: 1\n---\n",
                 "bad-yaml": b"---\nblock: [\n---\n", "two-keys": b"---\nblock: a\nblock: b\n---\n",
                 "list": b"---\n- a\n---\n", "no-close": b"---\nblock: a\n"}
        for k, v in kinds.items():
            with self.subTest(k):
                self.ov(files={PLANS + "/p.md": "p\n"})
                path = os.path.join(self.work, PS, "p", "handoff.md")
                os.makedirs(os.path.dirname(path))
                if v is None:
                    os.mkdir(path)
                elif v == "link":
                    os.symlink(h, path)
                else:
                    with open(path, "wb") as fh:
                        fh.write(v)
                self.refused(PS + "/p/handoff.md")

    def test_handoff_block_forms(self):  # PL30, Q8, SK1 (b)
        raw = lambda b: "---\nschema: handoff/1\nblock: %s\n---\n" % b
        forms = {"absent": "---\nschema: handoff/1\n---\n", "int": raw("5"), "list": raw("[a]"), "empty": raw('""'),
                 "digits-1001": raw("1" * 1001), "digits-4301": raw("1" * 4301), "digits-1000": raw("1" * 1000),
                 "digits-600": raw("1" * 600), "null": raw("null"), "bool": raw("true")}
        for lim in INT_LIMITS:
            for k, v in forms.items():
                with self.subTest(k, limit=lim), int_limit(lim):
                    self.ov(files={PLANS + "/p.md": "p\n", PS + "/p/handoff.md": v})
                    self.refused(PS + "/p/handoff.md")
        for lim in INT_LIMITS:
            with self.subTest("quoted-4301", limit=lim), int_limit(lim):
                self.ov(files={PLANS + "/p.md": "p\n", PS + "/p/handoff.md": raw('"%s"' % ("1" * 4301))})
                self.assertEqual(self.sec("### In progress"), ["- %s/p.md (block %s)" % (PLANS, "1" * 4301)])

    def test_digit_limits_same_on_both(self):  # SK1 (a)
        for lim in INT_LIMITS:
            for n in (600, 4300, 4301):
                with self.subTest(n, limit=lim), int_limit(lim):
                    self.ov()
                    self.program(rows=[dict(estimate="9" * n, used="8" * n)])
                    self.assertIn("used %s of %s" % ("8" * n, "9" * n), self.sec("### " + PNAME)[0])

    def test_handoff_block_is_escaped(self):  # PL31
        for block, shown in (("a\nb", "a\\nb"), ("a\\b", "a\\\\b"), ("## h", "## h")):
            with self.subTest(block):
                self.ov(files={PLANS + "/p.md": "p\n", PS + "/p/handoff.md": ho_text(block)})
                self.assertEqual(self.sec("### In progress"), ["- %s/p.md (block %s)" % (PLANS, shown)])

    def test_handoff_found_by_folder_not_plan_field(self):  # PL32
        self.ov(files={PLANS + "/p.md": "p\n", PS + "/p/handoff.md": ho_text("2a", plan="other")})
        self.assertEqual(self.sec("### In progress"), ["- %s/p.md (block 2a)" % PLANS])

    def test_unreadable_ledger_names_the_file(self):  # PL33
        self.ov(files={PLANS + "/d.md": "p\n"})
        led = os.path.join(self.work, PS, "d", "ledger.md")
        os.makedirs(led)
        self.refused(PS + "/d/ledger.md")

    def test_crlf_ledger_not_done(self):  # PL34
        self.ov()
        head, merge = self.merged("d", ledger=False)
        self.put(PS + "/d/ledger.md", (LEDGER_HEAD + mline(head, merge) + "\n").replace("\n", "\r\n"))
        self.commit("crlf")
        self.assertEqual(self.sec("### Done"), ["none"])

    def test_paths_plans_from_cfg(self):  # PL35
        self.ov(cfg={"paths": {"plans": "plans2"}}, files={"plans2/t.md": "p\n", PLANS + "/u.md": "p\n"})
        self.assertEqual(self.sec("### Todo"), ["- plans2/t.md"])

    def test_paths_plans_bad_values_refused(self):  # PL35
        self.ov()
        for bad in ("../x", "a//b", "/abs", "x/", "./x", ""):
            with self.subTest(bad):
                cfg = copy.deepcopy(self.cfg)
                cfg["paths"]["plans"] = bad
                with self.assertRaises(GateError):
                    index.render(self.work, cfg)

    def test_final_merge_called_once_per_plan(self):  # PL36
        self.ov(files={PLANS + "/p%d.md" % i: "p\n" for i in range(12)})
        from gates.lib import cleanup
        calls = []
        real = cleanup.final_merge
        with mock.patch.object(cleanup, "final_merge", lambda *a: calls.append(a[2]) or real(*a)):
            self.render()
        self.assertEqual(sorted(calls), sorted("p%d" % i for i in range(12)))

    def test_plan_states_cross_check_with_git(self):  # oracle PL1-PL28
        files = {PLANS + "/t%d.md" % i: "p\n" for i in range(5)}
        files.update({PLANS + "/g%d.md" % i: "p\n" for i in range(3)})
        self.ov(files=files)
        git(self.work, "rm", "-q", PLANS + "/g0.md", PLANS + "/g1.md")
        self.commit("rm")
        todo = sorted(l for l in git(self.work, "ls-files", PLANS).split("\n"))
        gone = sorted(set(git(self.work, "log", "--diff-filter=D", "--name-only", "--format=", "--", PLANS).split())
                      - set(todo))
        self.assertEqual(self.sec("### Todo"), ["- " + t for t in todo])
        self.assertEqual(self.sec("### Done"), ["- %s (merge not recorded)" % g for g in gone])

    # ---- SP
    def test_spec_named_by_working_tree_handoff(self):  # SP1
        self.ov(files={SPECS + "/s.md": "s\n", PS + "/p/handoff.md": ho_text("2a", [SPECS + "/s.md"])})
        self.assertEqual(self.sec("### In progress"), ["- " + SPECS + "/s.md"])
        self.assertEqual(self.sec("### Todo"), ["none"])

    def test_spec_naming_a_plan_path_lists_it_once(self):  # F1 (review 1), PL8
        # precedence within a section: done > in progress > todo (PL10, D-5b-Q4)
        self.ov(files={PLANS + "/t.md": "p\n", PLANS + "/g.md": "p\n"})
        git(self.work, "rm", "-q", PLANS + "/g.md")
        self.commit("rm")
        self.put(PS + "/p/handoff.md", ho_text("2a", [PLANS + "/t.md", PLANS + "/g.md"]))
        self.assertEqual(self.sec("### Todo"), ["none"])
        self.assertEqual(self.sec("### In progress"), ["- %s/t.md" % PLANS])
        self.assertEqual(self.sec("### Done"), ["- %s/g.md (merge not recorded)" % PLANS])

    def test_named_plan_keeps_its_in_progress_line(self):  # F-20261124-6hdc (review 2), plan :5330, PL4, PL5
        # a plan that a handoff spec also names keeps the plan loop's suffix: the stream form, the program form
        # and the own-handoff block form (the handoff form wins over the program form, Q9)
        self.ov(files={PLANS + "/a-plan.md": "p\n", PLANS + "/pp.md": "p\n", PLANS + "/p.md": "p\n"})
        self.program(rows=[dict(stream="a", block="5a")],
                     streams={"schema": "streams/1", "program": PNAME, "plan": PLANS + "/pp.md",
                              "streams": [{"id": "a", "plan": PLANS + "/a-plan.md"}]})
        self.put(PS + "/p/handoff.md", ho_text("2a", [PLANS + "/a-plan.md", PLANS + "/pp.md", PLANS + "/p.md"]))
        self.assertEqual(self.sec("### In progress"),
                         ["- %s/a-plan.md (program %s, stream a, block 5a)" % (PLANS, PNAME),
                          "- %s/p.md (block 2a)" % PLANS,
                          "- %s/pp.md (program %s)" % (PLANS, PNAME)])
        self.assertEqual(self.sec("### Todo"), ["none"])

    def test_filled_overview_2_validates_against_its_schema(self):  # SC2, F2 (review 1)
        self.ov(decs=[dec(PD1, "open", question="which?")],
                files={PLANS + "/t.md": "p\n", PLANS + "/p.md": "p\n", PLANS + "/g.md": "p\n",
                       SPECS + "/s.md": "s\n", SPECS + "/u.md": "s\n",
                       PS + "/p/handoff.md": ho_text("2a", [SPECS + "/s.md"])})
        git(self.work, "rm", "-q", PLANS + "/g.md")
        self.commit("rm")
        self.program(rows=[{"pending decisions": PD1}], requests=[req()])
        md = self.idx()
        self.assertIn("- %s: which?" % PD1, md)
        self.assertIn("- %s/t.md" % PLANS, md)
        self.assertIn("(block 2a)", md)
        self.assertTrue(any(RID in ln for ln in md.split("\n")))
        s = schema.load_schema(os.path.join(schema.SCHEMAS_DIR, "overview.yml"))
        self.assertEqual(schema.validate_markdown(s, md), [])

    def test_spec_named_by_stream_handoff_at_tip(self):  # SP2, LP35
        self.ov(files={SPECS + "/s.md": "s\n"})
        self.program()
        git(self.work, "checkout", "-q", "-b", PNAME + "/a/main")
        self.put(PS + "/a-plan/handoff.md", ho_text("1a", [SPECS + "/s.md"], plan="a-plan"))
        self.commit("stream handoff")
        git(self.work, "checkout", "-q", "main")
        self.assertEqual(self.sec("### In progress"), ["- " + SPECS + "/s.md"])
        self.assertEqual(self.sec("### Todo"), ["none"])

    def test_stream_branch_forms(self):  # LP35
        self.ov(files={SPECS + "/s.md": "s\n"})
        self.program()
        self.assertEqual(self.sec("### Todo"), ["- " + SPECS + "/s.md"])  # no stream branch
        git(self.work, "checkout", "-q", "-b", PNAME + "/a/main")
        self.commit("no handoff")
        git(self.work, "checkout", "-q", "main")
        self.assertEqual(self.sec("### Todo"), ["- " + SPECS + "/s.md"])  # branch, no file
        git(self.work, "checkout", "-q", PNAME + "/a/main")
        self.put(PS + "/a-plan/handoff.md", "garbage\n")
        self.commit("bad")
        git(self.work, "checkout", "-q", "main")
        self.refused("refs/heads/%s/a/main:%s/a-plan/handoff.md" % (PNAME, PS))

    def test_spec_named_by_none_is_todo(self):  # SP3
        self.ov(files={SPECS + "/z.md": "s\n"})
        self.assertEqual(self.sec("### Todo"), ["- " + SPECS + "/z.md"])

    def test_spec_deleted_is_done(self):  # SP4
        self.ov(files={SPECS + "/d.md": "s\n"})
        git(self.work, "rm", "-q", SPECS + "/d.md")
        self.commit("rm")
        self.assertEqual(self.sec("### Done"), ["- " + SPECS + "/d.md"])

    def test_spec_missing_file_listed_as_given(self):  # SP5
        self.ov(files={PS + "/p/handoff.md": ho_text("2a", [SPECS + "/missing.md"])})
        self.assertEqual(self.sec("### In progress"), ["- " + SPECS + "/missing.md"])

    def test_spec_named_and_deleted(self):  # SP6, Q4
        self.ov(files={SPECS + "/d.md": "s\n"})
        git(self.work, "rm", "-q", SPECS + "/d.md")
        self.put(PS + "/p/handoff.md", ho_text("2a", [SPECS + "/d.md"]))
        self.commit("rm")
        self.assertEqual((self.sec("### In progress"), self.sec("### Done")), (["- " + SPECS + "/d.md"], ["none"]))

    def test_spec_named_twice_listed_once(self):  # SP7
        self.ov(files={SPECS + "/s.md": "s\n", PS + "/p/handoff.md": ho_text("2a", [SPECS + "/s.md", SPECS + "/s.md"]),
                       PS + "/q/handoff.md": ho_text("2a", [SPECS + "/s.md"], plan="q")})
        self.assertEqual(self.sec("### In progress"), ["- " + SPECS + "/s.md"])

    def test_spec_name_forms(self):  # SP8, Q4
        names = ["docs/other.md", SPECS + "/x/y.md", "./" + SPECS + "/s.md", "s.md", "a\nb.md"]
        self.ov(files={PS + "/p/handoff.md": ho_text("2a", names)})
        esc = lambda s: s.replace("\n", "\\n")
        self.assertEqual(self.sec("### In progress"), ["- " + esc(n) for n in sorted(names)])
        self.ov(files={PS + "/p/handoff.md": ho_text("2a", [])})
        self.assertEqual(self.sec("### In progress"), ["none"])

    def test_spec_file_kinds(self):  # SP9
        self.ov(files={SPECS + "/a.txt": "x", SPECS + "/sub/b.md": "x", SPECS + "/ok.md": "x"})
        os.symlink("ok.md", os.path.join(self.work, SPECS, "l.md"))
        os.mkdir(os.path.join(self.work, SPECS, "d.md"))
        self.assertEqual(self.sec("### Todo"), ["- " + SPECS + "/ok.md"])

    def test_handoff_spec_forms(self):  # SP10, Q8
        raw = lambda s: "---\nschema: handoff/1\nblock: 2a\nspec: %s\n---\n" % s
        for k, v in {"str": "a.md", "ints": "[1, 2]", "null-item": "[null]", "nested": "[[a.md]]",
                     "int": "5", "map": "{a: b}"}.items():
            with self.subTest(k):
                self.ov(files={PS + "/p/handoff.md": raw(v)})
                self.refused(PS + "/p/handoff.md")
        self.ov(files={PS + "/p/handoff.md": raw("[]")})
        self.assertEqual(self.sec("### In progress"), ["none"])  # no plan file p.md: handoff alone names nothing

    def test_program_specs_list(self):  # SP11, Q4
        self.ov(files={SPECS + "/s.md": "s\n"})
        self.program(streams={"schema": "streams/1", "program": PNAME, "specs": [SPECS + "/s.md"],
                              "streams": [{"id": "a"}]})
        self.assertEqual(self.sec("### Todo"), ["- " + SPECS + "/s.md"])

    def test_spec_names_escaped(self):  # SP12
        self.ov(files={PS + "/p/handoff.md": ho_text("2a", ["## x\n## yࡰ.md"])})
        self.assertEqual(self.sec("### In progress"), ["- ## x\\n## y\\u0870.md"])
        self.assertEqual(len(headings(self.idx())), 5)

    def test_spec_entries_sorted(self):  # SP13
        self.ov(files={SPECS + "/%s" % n: "s\n" for n in ("B.md", "a.md", "é.md")})
        self.assertEqual(self.sec("### Todo"), ["- %s/%s" % (SPECS, n) for n in ("B.md", "a.md", "é.md")])

    # ---- LP
    def test_live_programs_none(self):  # LP1, LP34
        self.ov()
        self.assertEqual(self.sec("## Live programs"), ["none"])
        git(self.work, "branch", INTEG)  # a branch whose tip holds no program folder
        self.assertEqual(self.sec("## Live programs"), ["none"])

    test_integration_branch_without_folder_not_live = test_live_programs_none

    def test_live_programs_two_sorted(self):  # LP2
        self.ov()
        self.program("20261101-x")
        self.program("20261101-a")
        lines = [l for l in self.idx().split("\n") if l.startswith("### 2026")]
        self.assertEqual(lines, ["### 20261101-a", "### 20261101-x"])

    def test_program_read_at_integration_tip(self):  # LP3
        self.ov()
        self.program(rows=[dict(stream="a", used="7")])
        self.assertFalse(os.path.exists(os.path.join(self.work, PROGS, PNAME)))
        self.assertEqual(self.sec("### " + PNAME)[0],
                         "- a | 5a | running | used 7 of 10 | blockers none | pending none")

    def test_program_tip_wins_over_working_tree(self):  # LP4
        self.ov()
        self.program(rows=[dict(used="7")])
        self.put("%s/%s/status.md" % (PROGS, PNAME), status_page([dict(used="1")]))
        self.put("%s/%s/streams.yml" % (PROGS, PNAME), "garbage: [")
        self.assertIn("used 7 of 10", self.sec("### " + PNAME)[0])

    def test_stray_branch_names_skipped(self):  # LP5, LP36
        self.ov()
        self.program()
        for b in ("x/y/integration", "Bad_Name/integration", PNAME + "/a/extra/integration"):
            git(self.work, "branch", b, INTEG)
        self.assertEqual([l for l in self.idx().split("\n") if l.startswith("### 2")], ["### " + PNAME])

    def test_render_on_program_branch(self):  # LP36
        self.ov()
        self.program()
        git(self.work, "checkout", "-q", INTEG)
        self.assertEqual([l for l in self.idx().split("\n") if l.startswith("### 2")], ["### " + PNAME])

    def test_status_row_line(self):  # LP6
        self.ov()
        self.program(rows=[dict(stream="a", block="5a", status="running", used="3", estimate="10")])
        self.assertEqual(self.sec("### " + PNAME)[0],
                         "- a | 5a | running | used 3 of 10 | blockers none | pending none")

    def test_status_row_order(self):  # LP7, Q13
        self.ov()
        self.program(rows=[dict(stream="b"), dict(stream="a")])
        self.assertEqual([l[:5] for l in self.sec("### " + PNAME)[:2]], ["- b |", "- a |"])

    def test_status_cell_pipe(self):  # LP8
        self.ov()
        self.program(rows=[dict(stream="a|b", blockers="R|x")])
        line = self.sec("### " + PNAME)[0]
        self.assertEqual(line, "- a|b | 5a | running | used 3 of 10 | blockers R|x | pending none")

    def test_delivers_cell_not_printed(self):  # LP9, Q5
        self.ov()
        self.program(rows=[dict(delivers="a|b ## x")])
        md = self.idx()
        self.assertNotIn("a|b", md)
        self.assertEqual(len(self.sec("### " + PNAME)[0].split(" | ")), 6)

    def test_newline_in_need_and_question(self):  # LP11
        self.ov()
        self.program(requests=[req(need="n\n## evil")], rows=[{"pending decisions": PD1}],
                     files={DEC + "/%s.yml" % PD1: yamlsub.emit(dec(PD1, "open", question="which?\n## h"))})
        md = self.idx()
        self.assertIn("- %s a -> b open: n\\n## evil\n" % RID, md)
        self.assertIn("- %s: which?\\n## h\n" % PD1, md)
        self.assertEqual(len(headings(md)), 5)

    def test_non_printables_escaped_same_on_both(self):  # LP12
        self.ov()
        self.program(requests=[req(need="a\rb\tc\u0085d e f\\g")])
        self.assertIn("open: a\\rb\\tc\\x85d\\u2028e\\xa0f\\\\g\n", self.idx())

    def test_live_program_requests_and_questions(self):  # LP13, LP18
        ids = {"open": "R-20261105-a2b3", "accepted": "R-20261105-c4d5", "disputed": "R-20261105-e6f7",
               "done": "R-20261105-g8h9", "withdrawn": "R-20261105-j2k3"}
        self.ov()
        self.program(requests=[req(i, s, need="need " + s) for s, i in ids.items()], rows=[{"pending decisions": PD1}],
                     files={DEC + "/%s.yml" % PD1: yamlsub.emit(dec(PD1, "open", question="which?"))})
        self.assertEqual(self.sec("Open requests:"), [
            "- %s a -> b open: need open" % ids["open"], "- %s a -> b accepted: need accepted" % ids["accepted"],
            "- %s a -> b disputed: need disputed" % ids["disputed"]])
        self.assertEqual(self.sec("Pending owner questions:"), ["- %s: which?" % PD1])

    def test_requests_none(self):  # LP14
        self.ov()
        self.program(requests=[req(status="done")])
        self.assertEqual(self.sec("Open requests:"), ["none"])
        self.assertEqual(self.sec("Pending owner questions:"), ["none"])

    def test_request_order(self):  # LP15
        self.ov()
        self.program(requests=[req(RID2), req(RID)])
        self.assertEqual([l[:17] for l in self.sec("Open requests:")], ["- " + RID, "- " + RID2])

    def test_program_that_does_not_load_names_the_file(self):  # LP16
        base = "%s/%s" % (PROGS, PNAME)
        cases = {"bom": ("streams.yml", "﻿schema: streams/1\n"), "cr": ("status.md", "a\r\nb\n"),
                 "not-mapping": ("streams.yml", "- a\n"), "stray-request": ("requests/stray.txt", "x\n")}
        for k, (rel, text) in cases.items():
            with self.subTest(k):
                self.ov()
                self.program(files={"%s/%s" % (base, rel): text})
                self.refused("%s/%s" % (base, rel))

    def test_request_row_fields(self):  # LP17, Q14
        bad = {"need": req(need=5), "status": req(status="paused"), "from": {k: v for k, v in req().items()
                                                                              if k != "from_stream"}}
        for k, row in bad.items():
            with self.subTest(k):
                self.ov()
                self.program(requests=[row])
                self.refused("%s/%s/requests/%s.yml" % (PROGS, PNAME, RID))

    def test_pending_id_answered_or_withdrawn_has_no_open_record(self):  # LP19
        self.ov()
        self.program(rows=[{"pending decisions": "%s,%s" % (PD1, PD2)}], files={
            DEC + "/%s.yml" % PD1: yamlsub.emit(dec(PD1, "answered")), DEC + "/%s.yml" % PD2:
                yamlsub.emit(dec(PD2, "withdrawn"))})
        self.assertEqual(self.sec("Pending owner questions:"), ["- %s: no open record" % PD1,
                                                                "- %s: no open record" % PD2])

    def test_pending_id_without_record(self):  # LP20
        self.ov()
        self.program(rows=[{"pending decisions": PD3}])
        self.assertEqual(self.sec("Pending owner questions:"), ["- %s: no open record" % PD3])

    def test_pending_questions_from_integration_tip(self):  # LP21, LP24
        self.ov(decs=[dec(PD1, "open", question="tree")])
        self.program(rows=[{"pending decisions": PD1}],
                     files={DEC + "/%s.yml" % PD1: yamlsub.emit(dec(PD1, "answered"))})
        self.assertEqual(self.sec("Pending owner questions:"), ["- %s: no open record" % PD1])

    test_decision_records_read_at_ref_not_working_tree = test_pending_questions_from_integration_tip

    def test_decision_folder_stray_name_at_ref(self):  # LP25
        self.ov()
        self.program(rows=[{"pending decisions": PD1}], files={DEC + "/stray.txt": "x\n"})
        self.refused("refs/heads/%s:%s/stray.txt: not a regular file named <id>.yml" % (INTEG, DEC))

    def test_pending_cell_forms(self):  # LP22, LP23
        self.ov()
        self.program(rows=[{"pending decisions": "none"}])
        self.assertEqual(self.sec("Pending owner questions:"), ["none"])
        self.program("20261101-y", rows=[dict(stream="a", **{"pending decisions": "%s,%s,%s" % (PD2, PD1, PD2)}),
                                         dict(stream="b", **{"pending decisions": PD1})])
        self.assertEqual([l for l in self.idx().split("\n") if l.startswith("- DEC-")],
                         ["- %s: no open record" % PD2, "- %s: no open record" % PD1])
        for bad in ("", PD1 + ", " + PD2, "not-an-id"):
            with self.subTest(bad):
                self.ov()
                self.program(rows=[{"pending decisions": bad}])
                self.refused(PROGS + "/%s/status.md" % PNAME)

    test_pending_id_listed_once = test_pending_cell_forms

    def test_status_page_shapes(self):  # LP26
        self.ov()
        short = status_page([{}]) + "| a | 5a | b |\n"
        self.program(status=short)
        self.refused(PROGS + "/%s/status.md:" % PNAME)
        for k, page in {"wrong-header": "| x | y |\n|---|---|\n| 1 | 2 |\n", "empty": "", "indent":
                        status_page([{}]).replace("\n| a", "\n | a")}.items():
            with self.subTest(k):
                self.ov()
                self.program(status=page)
                self.assertEqual(self.sec("### " + PNAME)[0], "none")
        self.ov()
        self.program(rows=[dict(stream="a"), dict(stream="a"), dict(stream="zz")])
        self.assertEqual(len([l for l in self.sec("### " + PNAME) if l.startswith("- ")]), 3)

    def test_status_page_crlf_refused(self):  # LP27
        self.ov()
        self.program(status=status_page([{}]).replace("\n", "\r\n"))
        self.refused(PROGS + "/%s/status.md" % PNAME)

    def test_status_numbers_passed_as_text(self):  # LP28
        self.ov()
        self.program(rows=[dict(used="-1", estimate="1.5"), dict(used="x", estimate="")])
        self.assertEqual(self.sec("### " + PNAME)[:2][0].split(" | ")[3], "used -1 of 1.5")
        self.assertEqual(self.sec("### " + PNAME)[1].split(" | ")[3], "used x of ")

    def test_status_cell_as_given(self):  # LP29, LP30
        self.ov()
        self.program(rows=[dict(status="paused", blockers="a,b"), dict(status="", blockers="not an id")])
        l = self.sec("### " + PNAME)
        self.assertEqual((l[0].split(" | ")[2], l[0].split(" | ")[4]), ("paused", "blockers a,b"))
        self.assertEqual((l[1].split(" | ")[2], l[1].split(" | ")[4]), ("", "blockers not an id"))

    def test_program_heading_is_a_valid_name(self):  # LP31
        self.ov()
        self.program()
        self.assertIn("### " + PNAME, self.idx())

    def test_program_unparseable_streams_names_file(self):  # LP32
        for k, text in {"yaml": "a: [", "list": "- a\n", "empty": ""}.items():
            with self.subTest(k):
                self.ov()
                self.program(streams=text)
                self.refused("%s/%s/streams.yml" % (PROGS, PNAME))

    def test_program_missing_text_names_file(self):  # LP33
        self.ov()
        self.program()
        git(self.work, "checkout", "-q", INTEG)
        git(self.work, "rm", "-q", "%s/%s/sync-log.md" % (PROGS, PNAME))
        self.commit("rm")
        git(self.work, "checkout", "-q", "main")
        self.refused("sync-log.md")

    # ---- HI
    def test_one_commit_repository(self):  # HI1
        self.work = os.path.join(self.tmp, "one")
        os.mkdir(self.work)
        git(self.work, "init", "-q", "-b", "main")
        git(self.work, "config", "user.email", "f@example.invalid")
        git(self.work, "config", "user.name", "F")
        self.put(".strict-delivery/config.yml", yamlsub.emit(minimal_config()))
        self.plan("t.md")
        commit_all(self.work, "root")
        self.cfg = config.load(self.work)
        self.assertEqual(self.sec("### Todo"), ["- %s/t.md" % PLANS])
        self.assertEqual(self.sec("### Done"), ["none"])

    def test_shallow_clone_deleted_plans_unknown(self):  # HI3, HI4, Q17
        self.ov(files={PLANS + "/old.md": "p\n"})
        git(self.work, "rm", "-q", PLANS + "/old.md")
        self.commit("rm old")
        self.plan("mid.md")
        self.commit("add mid")
        git(self.work, "rm", "-q", PLANS + "/mid.md")
        self.commit("rm mid")
        self.put("z.txt", "z")
        self.commit("tail")
        clone = os.path.join(self.tmp, "shallow")
        git(self.tmp, "clone", "-q", "--depth", "3", "file://" + self.work, clone)
        git(clone, "config", "user.email", "f@example.invalid")
        git(clone, "config", "user.name", "F")
        self.work = clone
        self.cfg = config.load(clone)
        self.assertEqual(self.sec("### Done"), ["- %s/mid.md (merge not recorded)" % PLANS])  # old.md is cut off

    test_shallow_clone_sees_recent_deletions = test_shallow_clone_deleted_plans_unknown

    def test_detached_head(self):  # HI5
        self.ov(files={PLANS + "/t.md": "p\n"})
        git(self.work, "checkout", "-q", "--detach")
        self.assertEqual(self.sec("### Todo"), ["- %s/t.md" % PLANS])

    def test_renamed_plan_old_name_done(self):  # HI7
        self.ov(files={PLANS + "/a.md": "p\n"})
        git(self.work, "mv", PLANS + "/a.md", PLANS + "/b.md")
        self.commit("mv")
        self.assertEqual(self.sec("### Done"), ["- %s/a.md (merge not recorded)" % PLANS])
        self.assertEqual(self.sec("### Todo"), ["- %s/b.md" % PLANS])

    def test_render_with_git_index_file_env(self):  # HI8
        self.ov(files={PLANS + "/t.md": "p\n"})
        with mock.patch.dict(os.environ, {"GIT_INDEX_FILE": os.path.join(self.tmp, "other-index")}):
            self.assertEqual(self.sec("### Todo"), ["- %s/t.md" % PLANS])

    def test_render_with_git_color_config(self):  # HI10
        self.ov(files={PLANS + "/t.md": "p\n"})
        git(self.work, "config", "color.ui", "always")
        git(self.work, "config", "core.abbrev", "7")
        head, merge = self.merged("d")
        self.assertEqual(self.sec("### Done"), ["- %s/d.md (merged %s; cleanup pending)" % (PLANS, merge)])

    # ---- RG
    def test_overview_1_file_overwritten(self):  # RG1
        root = self.ov()
        for rel in ORDER:
            self.put(rel, "<!-- schema: overview/1 -->\nold\n" if rel == INDEX_MD else "old\n")
        index.regenerate(root, self.cfg)
        self.assertEqual(self.read(INDEX_MD), EMPTY_FILES[INDEX_MD])
        self.assertTrue(self.read(INDEX_MD).startswith("<!-- schema: overview/2 -->"))
        self.assertTrue(gate_schema.check(["--root", root]).ok())

    test_gate_schema_fails_on_overview_1_until_index = test_overview_1_file_fails_schema_until_index

    def test_regenerate_writes_nothing_on_refusal(self):  # RG4
        root = self.ov()
        self.program(streams="a: [")
        with self.assertRaises(GateError):
            index.regenerate(root, self.cfg)
        self.assert_nothing_written()

    # ---- SK guards
    def test_no_exception_group_names_in_index(self):  # SK3
        with open(os.path.join(REPO, "gates", "tools", "index.py"), encoding="utf-8") as fh:
            src = fh.read()
        for word in ("ExceptionGroup", "isprintable", "casefold", "unicodedata", ".lower(", ".upper(", ".title("):
            self.assertNotIn(word, src, word)
        self.assertIsNone(re.search(r"\bint\(", src))


if __name__ == "__main__":
    unittest.main()
