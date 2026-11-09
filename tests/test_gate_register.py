"""Tests of gates/gate_register.py through main() on real fixture repositories (Task 1c.2 input-domain table:
rows A, R, C, P, J and the refresh rows C14-C16, A4). Expected lines are written by hand from the fixture text;
the report-scan generator computes its expected ids with a tokeniser of its own."""
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
from gates import gate_register
from gates.lib import decisions, schema
from gates.lib.yamlsub import emit
from tests.helpers import GitIsolatedTestCase, commit_all, git, make_repo, minimal_config, write_record

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_FS = schema.load_schema(os.path.join(schema.SCHEMAS_DIR, "finding.yml"))
FTAG = "%s/%d" % (_FS.kind, _FS.version)  # Q-2a1-3: the tag comes from the schema file
DTAG = "decision/%d" % decisions._schema().version  # Global Constraints "Test fixtures"
FIND = ".strict-delivery/state/findings"
DEC = ".strict-delivery/state/decisions"
REV = "docs/strict-delivery/reviews"
REPORT = REV + "/p/r.md"
# review-report has no schema file yet: Task 6E.1 ships gates/schemas/review-report.yml (Global Constraints
# "Test fixtures": one named constant per kind with no schema file, its comment naming the shipping task).
TAGLINE = "<!-- schema: review-report/1 -->"
CATS = ["schema", "store", "base", "transition", "evidence", "epic", "report"]
F = "F-20261031-k3f9"
F2 = "F-20261031-m4n5"
F3 = "F-20261031-p6q7"
UNKNOWN = "F-20261031-zzzz"
UNKNOWN2 = "F-20261031-yyyy"
G = "DEC-20261031-k3f9"
G2 = "DEC-20261031-m4n5"
SHA = "a1b2c3d"
PATHS_OF = {"open": ["open"], "planned": ["open", "planned"], "in-progress": ["open", "planned", "in-progress"],
            "fixed-unpinned": ["open", "planned", "in-progress", "fixed-unpinned"],
            "pinned": ["open", "planned", "in-progress", "pinned"], "deferred": ["open", "deferred"],
            "closed": ["open", "closed"], "merged": ["open", "planned", "in-progress", "pinned", "merged"]}


def hist(*statuses):
    return [{"status": s, "sha": SHA, "by": "agent"} for s in statuses]


def frow(id_, status="open", **kw):
    """A finding row at ``status`` with a legal history; resolved rows carry ``resolved_by: p`` and cite
    ``src/x.py`` as evidence."""
    r = {"schema": FTAG, "id": id_, "status": status, "source": "review", "severity": "HIGH", "class": "bug",
         "siblings": [], "cites": [{"file": "src/x.py", "lines": "1-2", "sha": SHA}], "repro": None,
         "owner": {"kind": "plan", "plan": "p", "task": "1a.2"}, "pin": None, "ruling": None, "evidence": [],
         "history": hist(*PATHS_OF[status])}
    if status in ("closed", "merged"):
        r.update(resolved_by="p", evidence=["src/x.py"])
    r.update(kw)
    return {k: v for k, v in r.items() if v is not ...}


def drow(id_, status="answered", **kw):
    r = {"schema": DTAG, "id": id_, "status": status, "class": "scope", "question": "Keep X?",
         "options": [{"label": "yes", "cost": "none"}, {"label": "no", "cost": "some"}], "asked_at": SHA,
         "asked_by": "agent", "topics": [], "applies_to": [], "checked_against": [], "effect": "one-off"}
    if status == "answered":
        r.update(answer="Yes", answered_at={"at": SHA, "by": "who@example.invalid"})
    if status == "withdrawn":
        r.update(withdrawn={"at": SHA, "by": "who@example.invalid", "reason": "asked twice"})
    r.update(kw)
    return {k: v for k, v in r.items() if v is not ...}


def grant(id_, status="answered", plan="p", **kw):
    return drow(id_, status, **{"class": "merge-grant", "plan": plan, **kw})


def passes(*cats):
    return "".join("PASS register.%s\n" % c for c in cats)


def run_argv(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = gate_register.main(argv)
    return out.getvalue(), code


def fpath(id_):
    return "%s/%s.yml" % (FIND, id_)


def _write(path, text):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def _read(path):
    with open(path, "rb") as fh:
        return fh.read()


SRC = {"src/x.py": "x\n"}


class Base(GitIsolatedTestCase):
    def build(self, findings=(), decs=(), files=None, cfg=None, commit=True):
        root = make_repo(self.work, cfg)
        for r in findings:
            write_record(root, fpath(r["id"]), r)
        for r in decs:
            write_record(root, "%s/%s.yml" % (DEC, r["id"]), r)
        for rel, data in (files or {}).items():
            self.put(rel, data)
        if commit:
            commit_all(root, "fixture")
        return root

    def put(self, rel, data):
        path = os.path.join(self.work, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(data if isinstance(data, bytes) else data.encode("utf-8"))

    def fresh(self, name):
        self.work = os.path.join(self.tmp, "w_" + re.sub(r"[^0-9A-Za-z]", "_", name))
        os.mkdir(self.work)

    def run_(self, *args, root=None):
        return run_argv(["--root", root or self.work] + list(args))

    def input_fail(self, out, code, needle=""):
        self.assertEqual(code, 1)
        self.assertEqual(len(out.splitlines()), 1, out)
        self.assertTrue(out.startswith("FAIL register.input: "), out)
        self.assertIn(needle, out)

    def other_branch(self):
        git(self.work, "checkout", "-q", "-b", "feat")

    def cat_lines(self, out, cat):
        return [ln for ln in out.splitlines() if ln.startswith("FAIL register.%s." % cat)]


# ---------------------------------------------------------------- A: argv, root, config

class ArgvTests(Base):  # A1-A4
    def test_a1_root_absent_cwd_and_env(self):  # A1 (1c.1 A1)
        root = self.build()
        old = os.getcwd()
        self.addCleanup(os.chdir, old)
        os.chdir(root)
        self.assertEqual(run_argv([]), (passes(*CATS), 0))
        os.chdir(old)
        with mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": root}):
            self.assertEqual(run_argv([]), (passes(*CATS), 0))
        with mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": os.path.join(root, "nope")}):
            self.input_fail(*run_argv([]), "CLAUDE_PROJECT_DIR is not a directory")
        os.mkdir(os.path.join(root, "sub"))
        with mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": os.path.join(root, "sub")}):
            self.input_fail(*run_argv([]), "top level")

    def test_a1_root_forms_ok(self):  # A1 (1c.1 A2)
        root = self.build()
        link = os.path.join(self.tmp, "link")
        os.symlink(root, link)
        wt = os.path.join(self.tmp, "wt")
        git(root, "worktree", "add", "-q", "-b", "wtb", wt)
        for r in (root + "/", link, wt):
            self.assertEqual(run_argv(["--root", r]), (passes(*CATS), 0), r)

    def test_a1_root_forms_refused(self):  # A1 (1c.1 A2)
        root = self.build()
        os.mkdir(os.path.join(root, "sub"))
        self.input_fail(*run_argv(["--root", os.path.join(root, "sub")]), "top level")
        plain = os.path.join(self.tmp, "plain")
        os.mkdir(plain)
        bare = os.path.join(self.tmp, "bare")
        git(self.tmp, "init", "-q", "--bare", bare)
        afile = os.path.join(self.tmp, "afile")
        self.put("../afile", "x")
        for r in (os.path.join(self.tmp, "missing"), afile, plain, bare):
            self.input_fail(*run_argv(["--root", r]), "/strict-delivery:init")

    def test_a1_root_twice(self):  # A1 (1c.1 A3)
        root = self.build()
        for argv in (["--root", root, "--root", root], ["--root", root, "--root=" + root],
                     ["--ro", root, "--root", root]):
            self.input_fail(*run_argv(argv), "invalid arguments: --root given more than once")

    def test_a1_base_values(self):  # A1 (1c.1 A4)
        root = self.build()
        sha = git(root, "rev-parse", "HEAD")
        for b in ("main", "HEAD", sha):
            self.assertEqual(self.run_("--base", b), (passes(*CATS), 0), b)
        for argv, needle in ((["--base="], ""), (["--base=-x"], ""), (["--base=^x"], ""),
                             (["--base", "nosuchref"], ""), (["--base", "a" * 41], ""),
                             (["--base"], "expected one argument")):
            self.input_fail(*self.run_(*argv), needle)

    def test_a1_default_base_is_config_base_branch(self):  # A1 (1c.1 A4)
        self.build(cfg={**minimal_config(), "base_branch": "trunk"})
        self.input_fail(*self.run_())
        git(self.work, "branch", "trunk")
        self.assertEqual(self.run_(), (passes(*CATS), 0))

    def test_a1_base_twice_and_abbreviation(self):  # A1 (1c.1 A5, A6); _Once
        self.build()
        for argv in (["--base", "a", "--base", "b"], ["--base", "a", "--base=b"], ["--ba", "a", "--base", "b"]):
            self.input_fail(*self.run_(*argv), "--base given more than once")
        self.assertEqual(self.run_("--ba", "main"), (passes(*CATS), 0))

    def test_a1_json_position(self):  # A1 (1c.1 A7)
        root = self.build()
        out, code = run_argv(["--json", "--root", root])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["gate"], "register")
        self.input_fail(*run_argv(["--root", root, "--json"]), "unrecognized arguments: --json")
        out, code = run_argv(["--json", "--json", "--root", root])
        self.assertEqual(code, 1)
        self.assertEqual([ln["id"] for ln in json.loads(out)["lines"]], ["register.input"])

    def test_a1_unknown_positional_help(self):  # A1 (1c.1 A8)
        root = self.build()
        for argv in (["--foo"], ["extra"]):
            self.input_fail(*run_argv(["--root", root] + argv), "invalid arguments:")
        for h in ("-h", "--help"):
            self.input_fail(*run_argv([h]), "help requested; no gate was run")

    def test_a1_main_reads_sys_argv(self):  # A1 (1c.1 A9)
        root = self.build()
        with mock.patch.object(sys, "argv", ["prog", "--root", root]):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(gate_register.main(), 0)
            self.assertEqual(out.getvalue(), passes(*CATS))
        self.assertEqual(gate_register.PRODUCES, ())

    def test_a1_dispatcher(self):  # A1 (1c.1 A11)
        root = self.build()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = gates_main.main(["check", "register", "--root", root])
        self.assertEqual((out.getvalue(), code), (passes(*CATS), 0))
        p = subprocess.run([sys.executable, "-m", "gates", "check", "register", "--root", root], cwd=REPO,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual((p.stdout.decode(), p.returncode), (passes(*CATS), 0))

    def test_a4_registration_usage(self):  # A4
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(gates_main.main(["check"]), 2)
        self.assertEqual(err.getvalue(), "usage: python3 -m gates check <gate> [args]\n"
                                         "gates: cites, decisions, register, schema\n")
        self.assertEqual(gates_main.GATES["register"], "gates.gate_register")

    def test_a2_config_invalid(self):  # A2
        make_repo(self.work)
        with open(os.path.join(self.work, ".strict-delivery/config.yml"), "w") as fh:
            fh.write("a: [\n")
        self.input_fail(*self.run_())
        write_record(self.work, ".strict-delivery/config.yml", {**minimal_config(), "base_branch": 1})
        self.input_fail(*self.run_(), "base_branch")

    def test_missing_config_is_input_fail(self):  # A2, Review Focus 5
        git(self.work, "init", "-q", "-b", "main")
        out, code = self.run_()
        self.assertTrue(out.startswith("FAIL register.input:"), out)
        self.assertIn("/strict-delivery:init", out)
        self.assertEqual(code, 1)
        self.assertEqual(len(out.splitlines()), 1)

    def test_a2_config_read_from_root(self):  # A2: the repository under test's config, not this checkout's
        cfg = {**minimal_config(), "paths": {"reviews": "rev"}}
        self.build(cfg=cfg, files={"rev/r.md": TAGLINE + "\n" + UNKNOWN + "\n",
                                   REPORT: TAGLINE + "\n" + F2 + "\n"})
        out, code = self.run_()
        self.assertIn("FAIL register.report.rev/r.md: %s is not in the register\n" % UNKNOWN, out)
        self.assertNotIn(REPORT, out)
        self.assertEqual(code, 1)

    def test_a3_unborn_head(self):  # A3
        git(self.work, "init", "-q", "-b", "main")
        write_record(self.work, ".strict-delivery/config.yml", minimal_config())
        self.input_fail(*self.run_())

    def test_a3_shallow_without_merge_base(self):  # A3
        src = self.build([frow(F)])
        self.other_branch()
        git(src, "commit", "-q", "--allow-empty", "-m", "f1")
        git(src, "checkout", "-q", "main")
        git(src, "commit", "-q", "--allow-empty", "-m", "m1")
        clone = os.path.join(self.tmp, "clone")
        git(self.tmp, "clone", "-q", "--depth", "1", "--no-single-branch", "file://" + src, clone)
        git(clone, "checkout", "-q", "feat")
        self.input_fail(*run_argv(["--root", clone]))

    def test_a3_absent_base_ref_is_one_input_line(self):  # A3: other categories hold failures too
        self.build([frow(F, history=[])])
        self.input_fail(*self.run_("--base", "nosuchref"))


# ---------------------------------------------------------------- R: repository states

class RepoStateTests(Base):  # R1-R5
    def test_empty_registers_pass(self):  # R1, plan test
        for name, files, mk in (("absent", {}, None), ("empty", {}, FIND),
                                ("index-only", {FIND + "/index.yml": "x: 1\n"}, None)):
            with self.subTest(name):
                self.fresh(name)
                root = self.build(files=files, commit=False)
                if mk:
                    os.makedirs(os.path.join(root, mk))
                commit_all(root, "x")
                out, code = self.run_()
                for c in CATS:
                    self.assertIn("PASS register." + c, out)
                self.assertEqual((out, code), (passes(*CATS), 0))
                self.assertFalse(os.path.exists(os.path.join(root, DEC)))
                self.assertFalse(os.path.exists(os.path.join(root, REV)))

    def test_decision_file_in_findings_dir_fails(self):  # R2, plan test
        f = FIND + "/" + G + ".yml"
        root = self.build()
        write_record(root, f, drow(G))
        commit_all(root, "x")
        out, code = self.run_()
        self.assertIn("FAIL register.store.id.%s: " % f, out)
        self.assertTrue(any(ln.startswith("FAIL register.schema.%s: " % f) for ln in out.splitlines()), out)
        self.assertNotIn("PASS register.store", out)
        self.assertEqual(code, 1)

    def test_r3_findings_layout_is_input_fail(self):  # R3
        for name, make in (("x.yaml", lambda p: open(p, "w").close()), (".gitkeep", lambda p: open(p, "w").close()),
                           ("sub", os.mkdir), ("lnk.yml", lambda p: os.symlink("/dev/null", p)),
                           ("fifo.yml", os.mkfifo)):
            with self.subTest(name):
                self.fresh(name)
                root = self.build([frow(F)])
                make(os.path.join(root, FIND, name))
                self.input_fail(*self.run_(root=root), FIND + "/" + name)

    def test_r3_unparsable_or_non_mapping_record(self):  # R3
        self.build([frow(F)])
        self.put(fpath(F), "a: [\n")
        self.input_fail(*self.run_(), F)
        self.put(fpath(F), "- a\n")
        self.input_fail(*self.run_(), "top level must be a mapping")

    def test_r3_findings_dir_is_symlink_or_file(self):  # R3
        root = self.build()
        os.makedirs(os.path.join(root, ".strict-delivery/state"))
        os.symlink(self.tmp, os.path.join(root, FIND))
        self.input_fail(*self.run_(), FIND + ": is a symlink")
        os.unlink(os.path.join(root, FIND))
        self.put(FIND, "x\n")
        self.input_fail(*self.run_(), FIND + ": is not a directory")

    def test_r4_decisions_layout_is_input_fail(self):  # R4: grants and rulings need the decision store
        for name, make in (("x.yaml", lambda p: open(p, "w").close()), ("sub", os.mkdir),
                           ("lnk.yml", lambda p: os.symlink("/dev/null", p)), ("fifo.yml", os.mkfifo),
                           ("bad.yml", lambda p: _write(p, "a: [\n")),
                           ("list.yml", lambda p: _write(p, "- a\n"))):
            with self.subTest(name):
                self.fresh(name)
                root = self.build([frow(F)], [drow(G)])
                make(os.path.join(root, DEC, name))
                self.input_fail(*self.run_(root=root), DEC + "/" + name)

    def test_r5_record_without_usable_id_is_keyed_by_file(self):  # R5, Q-1c1-1 (a)
        root = self.build(commit=False)
        for i, bid in enumerate((..., 1, "nonsense", "F-20261399-k3f9")):
            write_record(root, "%s/x%d.yml" % (FIND, i), frow("x", id=bid, history=[]))
        commit_all(root, "x")
        out, code = self.run_()
        for i in range(4):
            f = "%s/x%d.yml" % (FIND, i)
            self.assertIn("FAIL register.transition.%s: history: must be a non-empty list\n" % f, out)
            self.assertIn("FAIL register.store.id.%s: " % f, out)
            self.assertTrue(any(ln.startswith("FAIL register.schema.%s: " % f) for ln in out.splitlines()), out)
        self.assertEqual(code, 1)

    def test_r5_duplicate_id_in_two_files_is_keyed_by_file(self):  # R5, Q-1c1-1 (a)
        root = self.build()
        for n in ("a", "b"):
            write_record(root, "%s/%s.yml" % (FIND, n), frow(F, history=[]))
        commit_all(root, "dup")
        out, _ = self.run_()
        for n in ("a", "b"):
            self.assertIn("FAIL register.transition.%s/%s.yml: history: must be a non-empty list\n" % (FIND, n), out)
        self.assertIn("FAIL register.store.duplicate.%s: id %s appears in 2 files" % (F, F), out)
        self.assertNotIn("register.transition.%s:" % F, out)


# ---------------------------------------------------------------- C: categories

class SchemaStoreTests(Base):  # C1, C2
    def test_c1_schema_one_line_per_error(self):
        self.build([frow(F, severity="ZZZ", source=...)])
        out, code = self.run_()
        ls = self.cat_lines(out, "schema")
        self.assertEqual(len(ls), 2, out)
        self.assertTrue(all(ln.startswith("FAIL register.schema.%s: " % F) for ln in ls), ls)
        self.assertTrue(any("severity" in ln for ln in ls) and any("source" in ln for ln in ls), ls)
        self.assertNotIn("PASS register.schema", out)
        self.assertEqual(code, 1)

    def test_c1_wrong_tag(self):
        self.build([frow(F, schema=DTAG)])
        self.assertIn("FAIL register.schema.%s: schema: expected %s, got %s\n" % (F, FTAG, DTAG), self.run_()[0])

    def test_closed_without_resolved_by_fails_schema(self):  # C1, plan test
        self.build([frow(F, "closed", resolved_by=...)], files=SRC)
        out, code = self.run_()
        self.assertIn("FAIL register.schema.%s: resolved_by" % F, out)
        self.assertEqual(code, 1)

    def test_c1_merged_status_and_merged_history_entry(self):  # C1, OQ-6
        self.build([frow(F, "merged")], files=SRC)
        out, _ = self.run_()
        self.assertIn("FAIL register.schema.%s: status: merged is set only by the cleanup step\n" % F, out)
        self.assertIn("FAIL register.schema.%s: history.4.status: merged is set only by the cleanup step\n" % F, out)

    def test_c2_store_errors(self):
        root = self.build()
        write_record(root, FIND + "/F-20261031-AAAA.yml", frow("F-20261031-aaaa"))
        write_record(root, fpath(F), frow(F))
        write_record(root, FIND + "/F-20261031-bbbb.yml", frow(F))
        commit_all(root, "x")
        out, _ = self.run_()
        self.assertIn("FAIL register.store.name.%s/F-20261031-AAAA.yml: " % FIND, out)
        self.assertIn("FAIL register.store.name.%s/F-20261031-bbbb.yml: " % FIND, out)
        self.assertIn("FAIL register.store.duplicate.%s: id %s appears in 2 files" % (F, F), out)
        self.assertNotIn("PASS register.store", out)


DELETED = "FAIL register.base.deleted.%s: %s exists on %s; records on the base branch are never deleted\n"


class BaseTests(Base):  # C3-C7
    def test_deleted_open_finding_fails(self):  # C3, Review Focus 1, plan test
        for status in ("open", "planned", "in-progress", "fixed-unpinned", "pinned", "deferred"):
            with self.subTest(status):
                self.fresh(status)
                root = self.build([frow(F, status)])
                git(root, "rm", "-q", fpath(F))
                out, code = self.run_("--base", "HEAD")
                self.assertIn(DELETED % (F, fpath(F), "HEAD"), out)
                self.assertNotIn("PASS register.base", out)
                self.assertEqual(code, 1)

    def test_c3_deleted_on_branch_names_default_base(self):  # C3: the merge base with main
        root = self.build([frow(F)])
        self.other_branch()
        git(root, "rm", "-q", fpath(F))
        commit_all(root, "del")
        self.assertIn(DELETED % (F, fpath(F), "main"), self.run_()[0])

    def test_deleted_resolved_finding_needs_grant(self):  # C4, OQ-5, Q-1b3-1, plan test
        cases = (("no grant", [], frow(F, "closed"), True),
                 ("answered grant for resolved_by", [grant(G)], frow(F, "closed"), False),
                 ("merged row with grant", [grant(G)], frow(F, "merged"), False),
                 ("grant for another plan", [grant(G, plan="other")], frow(F, "closed"), True),
                 ("grant open", [grant(G, "open")], frow(F, "closed"), True),
                 ("grant withdrawn", [grant(G, "withdrawn")], frow(F, "closed"), True),
                 ("grant answered but invalid", [grant(G, answer=...)], frow(F, "closed"), True),
                 ("not a grant", [drow(G, plan="p")], frow(F, "closed"), True),
                 ("superseded grant", [grant(G), drow(G2, supersedes=G)], frow(F, "closed"), False),
                 ("resolved_by missing", [grant(G)], frow(F, "closed", resolved_by=...), True))
        for name, decs, finding, fails in cases:
            with self.subTest(name):
                self.fresh(name)
                root = self.build([finding], decs, files=SRC)
                git(root, "rm", "-q", fpath(F))
                out, _ = self.run_("--base", "HEAD")
                if fails:
                    self.assertIn(DELETED % (F, fpath(F), "HEAD"), out)
                else:
                    self.assertNotIn("register.base.deleted." + F, out)
                    self.assertIn("PASS register.base\n", out)

    def test_c5_grant_only_in_working_tree_counts(self):  # C5
        root = self.build([frow(F, "closed")], files=SRC)
        self.other_branch()
        write_record(root, "%s/%s.yml" % (DEC, G), grant(G))  # untracked, working tree only
        git(root, "rm", "-q", fpath(F))
        out, _ = self.run_()
        self.assertNotIn("register.base.deleted." + F, out)
        self.assertIn("PASS register.base\n", out)

    def test_edited_resolved_finding_fails_immutable(self):  # C6, plan test
        root = self.build([frow(F, "closed")], files=SRC)
        write_record(root, fpath(F), frow(F, "closed", **{"class": "typo fixed"}))
        out, code = self.run_()
        self.assertIn("FAIL register.base.immutable.%s: resolved records are immutable; record the change as a new "
                      "finding\n" % F, out)
        self.assertEqual(code, 1)

    def test_c6_open_edit_and_same_value_pass(self):  # C6, Q-1a3-5
        root = self.build([frow(F), frow(F2, "closed")], files=SRC)
        write_record(root, fpath(F), frow(F, severity="LOW"))
        self.put(fpath(F2), emit(frow(F2, "closed")).replace("\n", "\r\n"))  # same parsed value, other bytes
        self.assertEqual(self.run_(), (passes(*CATS), 0))

    def test_closed_to_merged_refused(self):  # C6, OQ-6, M4, plan test
        root = self.build([frow(F, "closed")], files=SRC)
        write_record(root, fpath(F), frow(F, "merged", history=hist("open", "closed", "merged")))
        out, code = self.run_()
        line = [ln for ln in out.splitlines() if ln.startswith("FAIL register.schema.%s:" % F)]
        self.assertIn("FAIL register.schema.%s: status: merged is set only by the cleanup step" % F, line)
        self.assertTrue(all("cleanup step" in ln for ln in line), line)
        self.assertIn("FAIL register.base.immutable.%s: " % F, out)
        self.assertEqual(code, 1)

    def test_c7_collision_with_base_tip(self):  # C7 (1c.1 C5)
        root = self.build()
        self.other_branch()
        write_record(root, fpath(F), frow(F))
        write_record(root, fpath(F2), frow(F2))
        commit_all(root, "feat")
        git(root, "checkout", "-q", "main")
        write_record(root, fpath(F), frow(F, severity="LOW"))
        write_record(root, fpath(F2), frow(F2))
        commit_all(root, "main")
        git(root, "checkout", "-q", "feat")
        out, code = self.run_()
        self.assertIn("FAIL register.base.collision.%s: id %s already exists on main; mint a new id\n" % (F, F), out)
        self.assertNotIn("collision." + F2, out)
        self.assertEqual(code, 1)

    def test_c7_unparsable_base_side_record_is_input_fail(self):  # C7 (1c.1 C7)
        root = self.build()
        self.put(fpath(F), "a: [\n")
        commit_all(root, "bad")
        self.other_branch()
        write_record(root, fpath(F), frow(F))
        self.input_fail(*self.run_(), "main:" + fpath(F))

    def test_c7_non_record_entries_at_base_ignored(self):  # C7 (1c.1 C7: non-record names)
        root = self.build(files={FIND + "/notes.txt": "x", FIND + "/x.yaml": "x"})
        git(root, "rm", "-q", FIND + "/notes.txt", FIND + "/x.yaml")
        self.assertEqual(self.run_("--base", "HEAD"), (passes(*CATS), 0))

    def commit_entry(self, kind, rel):
        """Commit ``rel`` as a ``kind`` entry: a symlink (mode 120000) to the closed finding record ``src/real.yml``,
        or a gitlink (mode 160000) to HEAD. Staged by name: ``commit_all`` would stage the absent gitlink's
        deletion."""
        if kind == "symlink":
            os.makedirs(os.path.join(self.work, FIND), exist_ok=True)
            os.symlink("../../../src/real.yml", os.path.join(self.work, rel))
            git(self.work, "add", "--", rel)
        else:
            sha = git(self.work, "rev-parse", "HEAD")
            git(self.work, "update-index", "--add", "--cacheinfo", "160000,%s,%s" % (sha, rel))
        git(self.work, "commit", "-q", "-m", kind)
        self.assertIn({"symlink": "120000 blob ", "gitlink": "160000 commit "}[kind],
                      git(self.work, "ls-tree", "HEAD", "--", rel))

    def drop_entry(self, rel):
        git(self.work, "rm", "-q", "--cached", "--", rel)
        if os.path.lexists(os.path.join(self.work, rel)):
            os.unlink(os.path.join(self.work, rel))

    def test_c7_symlink_and_gitlink_record_entries_at_base_ignored(self):  # C7 (1c.1 C7), F-1c2-r1
        real = {"src/real.yml": emit(frow(F, "closed"))}
        for kind in ("symlink", "gitlink"):
            with self.subTest(kind=kind, at="merge base, deleted on the branch"):
                self.fresh(kind + "_deleted")
                self.build(files=real)
                self.commit_entry(kind, fpath(F))
                self.other_branch()
                self.drop_entry(fpath(F))
                git(self.work, "commit", "-q", "-m", "drop")
                self.assertEqual(self.run_(), (passes(*CATS), 0))
            with self.subTest(kind=kind, at="merge base, a regular record in its place on the branch"):
                self.fresh(kind + "_replaced")
                self.build(files=real)
                self.commit_entry(kind, fpath(F))
                self.other_branch()
                self.drop_entry(fpath(F))
                write_record(self.work, fpath(F), frow(F))
                git(self.work, "add", "--", fpath(F))
                git(self.work, "commit", "-q", "-m", "regular")
                self.assertEqual(self.run_(), (passes(*CATS), 0))
            with self.subTest(kind=kind, at="base tip only, the same id added on the branch"):
                self.fresh(kind + "_tip")
                self.build(files=real)
                self.other_branch()
                write_record(self.work, fpath(F), frow(F))
                commit_all(self.work, "feat")
                git(self.work, "checkout", "-q", "main")
                self.commit_entry(kind, fpath(F))
                git(self.work, "checkout", "-q", "feat")
                self.assertEqual(self.run_(), (passes(*CATS), 0))

    def test_c7_unparsable_record_only_at_base_tip_is_input_fail(self):  # C7 (1c.1 C7: the tip)
        root = self.build()
        self.other_branch()
        write_record(root, fpath(F), frow(F))
        commit_all(root, "feat")
        git(root, "checkout", "-q", "main")
        self.put(fpath(F2), "a: [\n")
        commit_all(root, "bad at tip")
        git(root, "checkout", "-q", "feat")
        out, code = self.run_()
        self.input_fail(out, code, "main:" + fpath(F2) + ": ")
        self.assertNotIn("(at the merge base)", out)

    def test_c7_schema_version_only_change_is_immutable(self):  # C7 (1c.1 C8): no migration is registered
        root = self.build([frow(F, "closed")], files=SRC)
        write_record(root, fpath(F), frow(F, "closed", schema="%s/%d" % (_FS.kind, _FS.version + 1)))
        out, code = self.run_()
        self.assertIn("FAIL register.base.immutable.%s: resolved records are immutable; record the change as a new "
                      "finding\n" % F, out)
        self.assertEqual(code, 1)


class TransitionTests(Base):  # C8
    def test_illegal_transition_fails(self):  # plan test
        self.build([frow(F, "pinned", history=hist("open", "pinned"))])
        out, code = self.run_()
        self.assertIn("FAIL register.transition.%s: history.1.status: open -> pinned is not a legal transition\n" % F,
                      out)
        self.assertNotIn("PASS register.transition", out)
        self.assertEqual(code, 1)

    def test_c8_transition_rows(self):
        cases = (("first not open", dict(status="planned", history=hist("planned")),
                  ["history.0.status: the first entry must be open, got planned"]),
                 ("empty", dict(history=[]), ["history: must be a non-empty list"]),
                 ("missing", dict(history=...), ["history: must be a non-empty list"]),
                 ("last differs", dict(status="planned", history=hist("open")),
                  ["status: planned differs from the last history entry (open)"]),
                 ("non-str status", dict(history=[{"status": 1, "sha": SHA, "by": "a"}]),
                  ["history.0.status: must be a status string"]))
        for name, kw, errs in cases:
            with self.subTest(name):
                self.fresh(name)
                self.build([frow(F, **kw)])
                ls = self.cat_lines(self.run_()[0], "transition")
                self.assertEqual(ls, ["FAIL register.transition.%s: %s" % (F, e) for e in errs])


class EvidenceTests(Base):  # C9-C11, C14-C16
    def ev(self, out):
        return self.cat_lines(out, "evidence")

    def test_c9_evidence_rows(self):
        reviews_plain = REV + "/p/r.md"
        cases = (
            ("closed no entry", [frow(F, "closed", evidence=[])], [],
             ["evidence: a closed finding needs at least one entry"]),
            ("pinned without pin or report", [frow(F, "pinned")], [],
             ["pin: a pinned finding needs a pin",
              "evidence: a pinned finding needs a review report cited as <sha>:%s/<plan>/<file>" % REV]),
            ("deferred without ruling", [frow(F, "deferred")], [],
             ["ruling: a deferred finding needs a ruling naming an answered decision"]),
            ("ruling names a grant", [frow(F, "deferred", ruling=G)], [grant(G)],
             ["ruling: %s is not an answered, valid decision of a class other than merge-grant" % G]),
            ("ruling unknown", [frow(F, "deferred", ruling=G2)], [grant(G)],
             ["ruling: no decision record for %s" % G2]),
            ("sha not a commit", [frow(F, evidence=["abcdef1"])], [], ["evidence.0: abcdef1 is not a commit"]),
            ("plain path under findings", [frow(F, evidence=[fpath(F2)])], [],
             ["evidence.0: %s is a finding record; cite it as <sha>:<path>" % fpath(F2)]),
            ("plain path under reviews", [frow(F, evidence=[reviews_plain])], [],
             ["evidence.0: %s is under %s, which is cleaned; cite it as <sha>:<path>" % (reviews_plain, REV)]),
            ("untracked plain path", [frow(F, evidence=["src/nope.py"])], [],
             ["evidence.0: src/nope.py is not a tracked regular file"]),
        )
        for name, finds, decs, errs in cases:
            with self.subTest(name):
                self.fresh(name)
                self.build(finds, decs, files=SRC)
                out, code = self.run_()
                self.assertEqual(self.ev(out), ["FAIL register.evidence.%s: %s" % (F, e) for e in errs])
                self.assertEqual(code, 1)

    def test_c9_good_ruling_and_transcript_location(self):
        root = self.build(files={"other/t.txt": "t\n", ".strict-delivery/state/plans/p/mutations/t.txt": "t\n"})
        sha = git(root, "rev-parse", "HEAD")
        self.put(REV + "/p/r.md", "review\n")
        sha2 = commit_all(root, "r")
        rep = "%s:%s/p/r.md" % (sha2, REV)
        good = frow(F, "pinned", evidence=[rep], pin={"test": "t", "transcript":
                                                      sha + ":.strict-delivery/state/plans/p/mutations/t.txt"})
        bad = frow(F2, "pinned", evidence=[rep], pin={"test": "t", "transcript": sha + ":other/t.txt"})
        write_record(root, fpath(F), good)
        write_record(root, fpath(F2), bad)
        write_record(root, fpath(F3), frow(F3, "deferred", ruling=G))
        write_record(root, "%s/%s.yml" % (DEC, G), drow(G))
        commit_all(root, "f")
        out, _ = self.run_()
        self.assertEqual(self.ev(out), ["FAIL register.evidence.%s: pin.transcript: other/t.txt must be under "
                                        ".strict-delivery/state/plans/p/mutations/" % F2])

    def unchanged_setup(self, base_bytes=None):
        root = self.build([frow(F, "closed")], files=SRC)
        if base_bytes is not None:
            self.put(fpath(F), base_bytes)
            commit_all(root, "base form")
        self.other_branch()
        git(root, "rm", "-q", "src/x.py")
        commit_all(root, "drop the cited file")
        return root

    def test_evidence_unchecked_when_unchanged(self):  # C14, M2, plan test
        crlf = b"\xef\xbb\xbf" + emit(frow(F, "closed")).replace("\n", "\r\n").encode("utf-8")
        reordered = dict(reversed(list(frow(F, "closed").items())))
        for name, base_bytes, tree in (("same", None, None), ("bom-crlf-at-merge-base", crlf, frow(F, "closed")),
                                       ("key-order", None, reordered)):
            with self.subTest(name):
                self.fresh(name)
                root = self.unchanged_setup(base_bytes)
                if tree is not None:
                    write_record(root, fpath(F), tree)
                    self.assertNotEqual(_read(os.path.join(root, fpath(F))),
                                        git(root, "show", "main:" + fpath(F)).encode() + b"\n")
                out, code = self.run_()
                self.assertNotIn("register.evidence." + F, out)
                self.assertEqual((out, code), (passes(*CATS), 0))

    def test_evidence_checked_when_changed(self):  # C15, M2, plan test
        line = "FAIL register.evidence.%s: evidence.0: src/x.py is not a tracked regular file" % F
        for name, base_kw, tree_kw in (("edited", {}, {"class": "other"}),
                                       ("type-only", {"review_round": 1}, {"review_round": True})):
            with self.subTest(name):
                self.fresh(name)
                root = self.build([frow(F, "closed", **base_kw)], files=SRC)
                self.other_branch()
                git(root, "rm", "-q", "src/x.py")
                write_record(root, fpath(F), frow(F, "closed", **tree_kw))
                commit_all(root, "edit")
                out, code = self.run_()
                self.assertEqual(self.ev(out), [line])
                self.assertEqual(code, 1)
        with self.subTest("new-on-branch"):
            self.fresh("new")
            root = self.build(files=SRC)
            self.other_branch()
            git(root, "rm", "-q", "src/x.py")
            write_record(root, fpath(F), frow(F, "closed"))
            commit_all(root, "new")
            out, code = self.run_()
            self.assertEqual(self.ev(out), [line])
            self.assertIn("PASS register.base\n", out)

    def test_c10_rename_counts_as_new(self):  # C10: matched by file path
        root = self.build([frow(F, "closed")], files=SRC)
        self.other_branch()
        git(root, "rm", "-q", "src/x.py")
        git(root, "mv", fpath(F), FIND + "/x.yml")
        commit_all(root, "rename")
        out, _ = self.run_()
        self.assertIn("FAIL register.evidence.%s: evidence.0: src/x.py is not a tracked regular file\n" % F, out)

    def test_c10_open_unchanged_still_checked(self):  # C10: an unresolved row's plain path is always checked
        root = self.build([frow(F, evidence=["src/x.py"])], files=SRC)
        self.other_branch()
        git(root, "rm", "-q", "src/x.py")
        commit_all(root, "drop")
        self.assertEqual(self.ev(self.run_()[0]),
                         ["FAIL register.evidence.%s: evidence.0: src/x.py is not a tracked regular file" % F])

    def test_c11_staged_counts_symlink_does_not(self):  # C11
        root = self.build([frow(F, evidence=["src/x.py"]), frow(F2, evidence=["src/l.py"])], commit=False)
        self.put("src/x.py", "x\n")
        os.symlink("x.py", os.path.join(root, "src/l.py"))
        git(root, "add", "-A")  # staged, not committed
        out, _ = self.run_()
        self.assertEqual(self.ev(out),
                         ["FAIL register.evidence.%s: evidence.0: src/l.py is not a tracked regular file" % F2])

    def test_c16_merge_base_row_unreadable_is_input_fail(self):  # C16
        for name, data, needle in (("unparsable", "a: [\n", ""),
                                   ("non-mapping", "- a\n", "the top level must be a mapping"),
                                   ("not utf-8", b"\xff\xfe\n", fpath(F) + ": not valid UTF-8")):
            with self.subTest(name):
                self.fresh(name)
                root = self.build()
                self.put(fpath(F), data)
                commit_all(root, "bad at base")
                self.other_branch()
                write_record(root, fpath(F), frow(F))
                self.input_fail(*self.run_(), "main:%s (at the merge base): %s" % (fpath(F), needle))

    def test_c16_helpers_directly(self):  # C16 through the store helpers the gate calls
        from gates.lib import config, store
        root = self.build([frow(F, "closed")], files=SRC)
        cfg = config.load(root)
        st = store.Store(root, "finding", cfg)
        at = store._merge_base_rows(root, st.directory, "main")
        self.assertEqual(sorted(at), [fpath(F)])
        cur = st.load()[0]
        self.assertIs(store._row_changed(cur, at, "finding"), False)
        self.assertIs(store._row_changed(store.Record(F, {**cur.row, "review_round": 1}, cur.file), at, "finding"),
                      True)
        self.assertIs(store._row_changed(store.Record(F, cur.row, FIND + "/y.yml"), at, "finding"), True)
        from gates.lib.result import GateError
        with self.assertRaisesRegex(GateError, "^the base ref must be a string$"):
            store._merge_base_rows(root, st.directory, 1)
        os.mkdir(os.path.join(root, "sub"))
        with self.assertRaisesRegex(GateError, "top level"):
            store._merge_base_rows(os.path.join(root, "sub"), st.directory, "main")
        with self.assertRaisesRegex(GateError, "top level"):  # the root check runs first (Q-1a-fin-1)
            store._merge_base_rows(os.path.join(root, "sub"), st.directory, 1)
        self.put(fpath(F), "- a\n")
        commit_all(root, "non-mapping at the base")
        with self.assertRaisesRegex(GateError, "^main:%s \\(at the merge base\\): the top level must be a mapping$"
                                    % re.escape(fpath(F))):
            store._merge_base_rows(root, st.directory, "main")


class EpicTests(Base):  # C12, M1
    def test_c12_epic_rows(self):
        cases = (("self parent", [frow(F, parent=F)], ["parent.%s: parent: a finding cannot be its own parent" % F]),
                 ("missing parent, open child", [frow(F, parent=F2)],
                  ["parent.%s: parent: %s has no record" % (F, F2)]),
                 ("missing parent, resolved child", [frow(F, "closed", parent=F2)], []),
                 ("cycle", [frow(F, parent=F2), frow(F2, parent=F)],
                  ["parent.%s: parent: %s leads back to %s: a parent cycle" % (F, F2, F),
                   "parent.%s: parent: %s leads back to %s: a parent cycle" % (F2, F, F2)]),
                 ("resolved parent, unresolved child", [frow(F, parent=F2), frow(F2, "closed")],
                  ["epic.%s: parent: %s is resolved but this finding is not" % (F, F2)]))
        for name, finds, errs in cases:
            with self.subTest(name):
                self.fresh(name)
                self.build(finds, files=SRC)
                out, code = self.run_()
                self.assertEqual(self.cat_lines(out, "epic"), ["FAIL register.epic." + e for e in errs])
                self.assertEqual("PASS register.epic\n" in out, not errs)


class MalformedTests(Base):  # C13
    def test_c13_every_category_runs_over_a_malformed_row(self):
        self.build([frow(F, "closed", severity="ZZZ", history=hist("open", "pinned"), evidence=[], parent=F)])
        out, code = self.run_()
        for cat in ("schema", "transition", "evidence", "epic"):
            self.assertRegex(out, r"FAIL register\.%s\.(parent\.)?%s" % (cat, F))
        for cat in ("store", "base", "report"):
            self.assertIn("PASS register.%s\n" % cat, out)
        self.assertEqual(code, 1)


# ---------------------------------------------------------------- P: review-report scan

ALPHA = "23456789abcdefghijkmnpqrstuvwxyz"
SHAPE = re.compile(("F-[0-9]{8}-[%s]{4}" % ALPHA).encode())


def oracle_unknown(data, known):
    """Expected unknown ids of a tagged report: split on every byte outside [0-9A-Za-z_-], keep tokens of the
    id shape that are not known, first occurrence order."""
    out = []
    for tok in re.split(rb"[^0-9A-Za-z_-]+", data):
        if SHAPE.fullmatch(tok) and tok.decode() not in known and tok.decode() not in out:
            out.append(tok.decode())
    return out


def unknown_line(rel, id_):
    return "FAIL register.report.%s: %s is not in the register" % (rel, id_)


class ReportTests(Base):  # P1-P9
    def rep(self, out):
        return self.cat_lines(out, "report")

    def test_report_cites_unknown_finding(self):  # P4, OQ-18, plan test
        self.build([frow(F)], files={REPORT: TAGLINE + "\nsee %s and %s\n" % (F, UNKNOWN)})
        out, code = self.run_()
        self.assertIn("FAIL register.report.docs/strict-delivery/reviews/p/r.md: F-20261031-zzzz is not in the "
                      "register", out)
        self.assertEqual(self.rep(out), [unknown_line(REPORT, UNKNOWN)])
        self.assertNotIn("PASS register.report", out)
        self.assertEqual(code, 1)

    def test_report_whole_token_match(self):  # P4, I6, plan test
        self.build([frow(F)], files={REPORT: TAGLINE + "\nXF-20261031-k3f9 F-20261031-k3f9a F-20261031-zzzza "
                                              "xF-20261031-zzzz F-20261031-zzzz_ F-20261031-zzzz-\n"})
        out, code = self.run_()
        self.assertIn("PASS register.report", out)
        self.assertEqual((out, code), (passes(*CATS), 0))

    def test_untagged_report_ignored(self):  # P3, plan test
        for name, head in (("line 2", "\n" + TAGLINE), ("bom", "\N{ZERO WIDTH NO-BREAK SPACE}" + TAGLINE),
                           ("version 0", TAGLINE.replace("/1", "/0"))):
            with self.subTest(name):
                self.fresh(name)
                self.build(files={REPORT: head + "\n" + UNKNOWN + "\n"})
                out, code = self.run_()
                self.assertIn("PASS register.report", out)
                self.assertEqual((out, code), (passes(*CATS), 0))

    def test_crlf_report_is_checked(self):  # P3, Q-1c2-1 (a), plan test
        self.build(files={REPORT: (TAGLINE + "\r\n" + UNKNOWN + "\r\n").encode()})
        out, code = self.run_()
        self.assertIn("FAIL register.report.docs/strict-delivery/reviews/p/r.md: F-20261031-zzzz is not in the "
                      "register", out)
        self.assertEqual(code, 1)

    def test_p3_first_line_generator(self):  # P3: every first-line variant, expected verdict by hand
        body = ("\n%s\n" % UNKNOWN).encode()
        t = TAGLINE.encode()
        variants = (("exact", t + body, True), ("v12", t.replace(b"/1 ", b"/12 ") + body, True),
                    ("v9", t.replace(b"/1 ", b"/9 ") + body, True),
                    ("v0", t.replace(b"/1 ", b"/0 ") + body, False), ("v01", t.replace(b"/1 ", b"/01 ") + body, False),
                    ("no version", t.replace(b"/1 ", b"/ ") + body, False),
                    ("trailing space", t + b" " + body, False), ("leading space", b" " + t + body, False),
                    ("line 2", b"\n" + t + body, False), ("bom", b"\xef\xbb\xbf" + t + body, False),
                    ("crlf", t + body.replace(b"\n", b"\r\n"), True), ("two cr", t + b"\r\r" + body, False),
                    ("other kind", t.replace(b"review-report", b"review-reports") + body, False),
                    ("empty", b"", False))
        files = {"%s/%02d.md" % (REV, i): data for i, (_, data, _) in enumerate(variants)}
        self.build(files=files)
        out, _ = self.run_()
        want = [unknown_line("%s/%02d.md" % (REV, i), UNKNOWN) for i, (_, _, checked) in enumerate(variants) if checked]
        self.assertEqual(self.rep(out), want)
        self.build_only_line()

    def build_only_line(self):  # a tagged report of one line with no newline: a report with no ids
        self.fresh("only")
        self.build(files={REPORT: TAGLINE})
        self.assertEqual(self.run_(), (passes(*CATS), 0))

    def test_p4_p6_id_generator(self):  # P4, P6 against the independent tokeniser
        known = {F, F2}
        pieces = [F, UNKNOWN, "F-20261031-k3f9a", "XF-20261031-k3f9", "DEC-20261031-zzzz", "F-20261031-ZZZZ",
                  "F-20261399-k3f9", "F-20261031-l0o1", F2, UNKNOWN2, "F-2026103-zzzz", "F-20261031-zzz"]
        layouts = {"start": "{}\n", "end": "x {}", "fence": "```\n{}\n```\n", "cell": "| a | {} |\n",
                   "link": "[x]({}) [{}](#y)\n", "punct": "({}).,;\n", "tab": "\t{}\t\n", "nonascii": "é{}é\n"}
        files, want = {}, []
        for lname, layout in sorted(layouts.items()):
            for i, piece in enumerate(pieces):
                rel = "%s/%s/%02d.md" % (REV, lname, i)
                data = (TAGLINE + "\n" + layout.replace("{}", piece)).encode("utf-8")
                files[rel] = data
        self.build([frow(F), frow(F2, "closed")], files={**files, **SRC})
        for rel in sorted(files):
            want.extend(unknown_line(rel, u) for u in oracle_unknown(files[rel].split(b"\n", 1)[1], known))
        out, code = self.run_()
        self.assertEqual(self.rep(out), want)
        self.assertEqual(sorted({ln.rsplit(": ", 1)[1].split()[0] for ln in want}), ["F-20261031-yyyy",
                                                                                   "F-20261031-zzzz",
                                                                                   "F-20261399-k3f9"])
        self.assertEqual(code, 1)

    def test_p4_record_with_unusable_id_is_not_known(self):  # P4: a token failing id_problem fails closed
        root = self.build(files={REPORT: TAGLINE + "\nF-20261399-k3f9\n"})
        write_record(root, FIND + "/x.yml", frow("F-20261399-k3f9"))
        commit_all(root, "x")
        self.assertEqual(self.rep(self.run_()[0]), [unknown_line(REPORT, "F-20261399-k3f9")])

    def test_p5_occurrences(self):  # P5
        a, b, c = REV + "/b.md", REV + "/a/x.md", REV + "/c.md"
        self.build(files={a: "%s\n%s %s\n%s\n" % (TAGLINE, UNKNOWN, UNKNOWN, UNKNOWN),
                          b: "%s\n%s %s %s\n" % (TAGLINE, UNKNOWN2, UNKNOWN, UNKNOWN2),
                          c: "%s\n%s\n" % (TAGLINE, UNKNOWN)})
        self.assertEqual(self.rep(self.run_()[0]), [unknown_line(b, UNKNOWN2), unknown_line(b, UNKNOWN),
                                                    unknown_line(a, UNKNOWN), unknown_line(c, UNKNOWN)])

    def test_p1_which_files(self):  # P1
        body = TAGLINE + "\n" + UNKNOWN + "\n"
        root = self.build(files={REV + "/a/b/c/deep.md": body, "docs/strict-delivery/reviews2/r.md": body,
                                 "docs/other.md": body, ".gitignore": "ign.md\n", "real.md": body}, commit=False)
        os.symlink("../../../real.md", os.path.join(root, REV + "/a/lnk.md"))
        commit_all(root, "x")
        self.put(REV + "/untracked.md", body)
        self.put(REV + "/ign.md", body)
        self.assertEqual(git(root, "status", "--porcelain", "--untracked-files=all"), "?? %s/untracked.md" % REV)
        self.assertEqual(self.rep(self.run_()[0]), [unknown_line(REV + "/a/b/c/deep.md", UNKNOWN)])

    def test_p2_reviews_directory_missing(self):  # P2
        self.build([frow(F)])
        self.assertFalse(os.path.exists(os.path.join(self.work, REV)))
        self.assertIn("PASS register.report\n", self.run_()[0])

    def test_p1_reviews_path_is_itself_a_file(self):  # P1: "equal to or under paths.reviews + '/'"
        cfg = {**minimal_config(), "paths": {"reviews": "docs/rev.md"}}
        self.build(cfg=cfg, files={"docs/rev.md": TAGLINE + "\n" + UNKNOWN + "\n",
                                   "docs/rev.mdx": TAGLINE + "\n" + UNKNOWN + "\n"})
        self.assertEqual(self.rep(self.run_()[0]), [unknown_line("docs/rev.md", UNKNOWN)])

    def test_p7_binary_and_invalid_utf8(self):  # P7, Q-1c1-2 (a)
        self.build(files={REV + "/bin.png": b"\x89PNG\r\n\x1a\n\x00\xff" + UNKNOWN.encode(),
                          REV + "/bad.md": TAGLINE.encode() + b"\n\xff\xfe " + UNKNOWN.encode() + b"\xff\n"})
        self.assertEqual(self.rep(self.run_()[0]), [unknown_line(REV + "/bad.md", UNKNOWN)])

    def test_p8_unreadable_tracked_report(self):  # P8: fail closed, no PASS register.report
        for name, make, why in (
                ("deleted", lambda p: os.rename(p, p + ".away"), "No such file or directory"),
                ("directory", lambda p: (os.unlink(p), os.mkdir(p)), "not a regular file"),
                ("symlink", lambda p: (os.unlink(p), os.symlink("/dev/null", p)), "not a regular file"),
                ("parent symlink", None, "a parent is not a real directory")):
            with self.subTest(name):
                self.fresh(name)
                root = self.build(files={REPORT: TAGLINE + "\n" + F + "\n"})
                p = os.path.join(root, REPORT)
                if make is None:
                    d = os.path.join(root, REV, "p")
                    os.rename(d, os.path.join(self.tmp, name + "_away"))
                    os.symlink(os.path.join(self.tmp, name + "_away"), d)
                else:
                    make(p)
                out, code = self.run_()
                self.assertEqual(self.rep(out), ["FAIL register.report.%s: cannot read the file (%s)" % (REPORT, why)])
                self.assertNotIn("PASS register.report", out)
                self.assertEqual(code, 1)

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root reads everything")
    def test_p8_permission_denied(self):  # P8
        root = self.build(files={REPORT: TAGLINE + "\n"})
        p = os.path.join(root, REPORT)
        os.chmod(p, 0)
        self.addCleanup(os.chmod, p, 0o644)
        self.assertEqual(self.rep(self.run_()[0]),
                         ["FAIL register.report.%s: cannot read the file (Permission denied)" % REPORT])

    def test_p9_working_tree_content_is_read(self):  # P9
        root = self.build([frow(F)], files={REPORT: TAGLINE + "\n" + F + "\n"})
        self.assertIn("PASS register.report\n", self.run_()[0])
        self.put(REPORT, TAGLINE + "\n" + UNKNOWN + "\n")
        self.assertEqual(self.rep(self.run_()[0]), [unknown_line(REPORT, UNKNOWN)])
        self.put(REPORT, "untagged now\n" + UNKNOWN + "\n")
        self.assertIn("PASS register.report\n", self.run_(root=root)[0])

    def test_p9_custom_finding_prefix(self):  # P4 with ids.finding from config
        cfg = {**minimal_config(), "ids": {"finding": "FX"}}
        self.build(cfg=cfg, files={REPORT: TAGLINE + "\nFX-20261031-zzzz F-20261031-zzzz\n"})
        self.assertEqual(self.rep(self.run_()[0]), [unknown_line(REPORT, "FX-20261031-zzzz")])


# ---------------------------------------------------------------- J: output

class OutputTests(Base):  # J1
    def test_json_output_shape(self):
        self.build(files={REPORT: TAGLINE + "\n" + UNKNOWN + "\n"})
        text, code = run_argv(["--json", "--root", self.work])
        doc = json.loads(text)
        plain = self.run_()[0].splitlines()
        self.assertEqual(code, 1)
        self.assertEqual(sorted(doc), ["gate", "lines", "ok"])
        self.assertEqual((doc["gate"], doc["ok"]), ("register", False))
        rendered = ["PASS " + ln["id"] if ln["status"] == "PASS" else "FAIL %s: %s" % (ln["id"], ln["reason"])
                    for ln in doc["lines"]]
        self.assertEqual(rendered, plain)

    def test_j1_file_name_escaped_once(self):
        self.build(files={REV + "/a\nb\\c.md": TAGLINE + "\n" + UNKNOWN + "\n"})
        out = self.run_()[0]
        self.assertIn("FAIL register.report.%s/a\\nb\\\\c.md: %s is not in the register\n" % (REV, UNKNOWN), out)
        self.assertEqual(len(out.splitlines()), out.count("\n"))

    def test_exit_codes(self):
        self.build()
        self.assertEqual(self.run_()[1], 0)
        self.assertEqual(run_argv(["--root", os.path.join(self.tmp, "nope")])[1], 1)


if __name__ == "__main__":
    unittest.main()
