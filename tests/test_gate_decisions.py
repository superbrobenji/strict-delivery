"""Tests of gates/gate_decisions.py through main() on real fixture repositories (Task 1c.1 input-domain table:
rows A, R, C, O, J). Expected lines are written by hand from the fixture text."""
import contextlib
import io
import json
import os
import subprocess
import sys
import unittest
from unittest import mock

from gates import __main__ as gates_main
from gates import gate_decisions
from gates.lib import schema
from tests.helpers import GitIsolatedTestCase, commit_all, git, make_repo, minimal_config, write_record

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_S = schema.load_schema(os.path.join(schema.SCHEMAS_DIR, "decision.yml"))
TAG = "%s/%d" % (_S.kind, _S.version)  # Q-2a1-3: the tag comes from the schema file
_FS = schema.load_schema(os.path.join(schema.SCHEMAS_DIR, "finding.yml"))
FTAG = "%s/%d" % (_FS.kind, _FS.version)  # Q-2a1-3: a finding row's tag, from the finding schema file
DEC = ".strict-delivery/state/decisions"
CATS = ["schema", "store", "base", "landed", "refs", "open-ref", "scan"]
ID = "DEC-20261031-k3f9"
OID = "DEC-20261031-m4n5"   # the open decision
ID3 = "DEC-20261031-p6q7"
ID4 = "DEC-20261031-r8s9"
OPT = {"label": "yes", "cost": "none"}
OPT2 = {"label": "no", "cost": "some"}
AT = {"at": "b2c3d4e", "by": "who@example.invalid"}
W = {"at": "a1b2c3d", "by": "who@example.invalid", "reason": "asked twice"}


def row(id_, status="open", **kw):
    r = {"schema": TAG, "id": id_, "status": status, "class": "scope", "question": "Keep X?",
         "options": [OPT, OPT2], "asked_at": "a1b2c3d", "asked_by": "agent", "topics": ["ids"],
         "applies_to": ["src/*"], "checked_against": [], "effect": "one-off"}
    if status == "answered":
        r.update(answer="Yes", answered_at=AT)
    if status == "withdrawn":
        r.update(withdrawn=W)
    r.update(kw)
    return {k: v for k, v in r.items() if v is not None}


def lasting(id_, **kw):
    return row(id_, "answered", **{**dict(effect="lasting", rule="Keep X.", landed_in=["CLAUDE.md"]), **kw})


def passes(*cats):
    return "".join("PASS decisions.%s\n" % c for c in cats)


def run_argv(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = gate_decisions.main(argv)
    return out.getvalue(), code


class Base(GitIsolatedTestCase):
    def build(self, rows=(), files=None, cfg=None, commit=True):
        root = make_repo(self.work, cfg)
        for r in rows:
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

    def run_(self, *args, root=None):
        return run_argv(["--root", root or self.work] + list(args))

    def lines(self, *args):
        return self.run_(*args)[0].splitlines()

    def input_fail(self, out, code, needle=""):
        self.assertEqual(code, 1)
        self.assertEqual(len(out.splitlines()), 1, out)
        self.assertTrue(out.startswith("FAIL decisions.input: "), out)
        self.assertIn(needle, out)

    def other_branch(self):
        git(self.work, "checkout", "-q", "-b", "feat")


CLAUDE = "rules: %s %s\n" % (ID, ID3)


class ArgvTests(Base):  # A1-A11
    def test_a1_root_absent_cwd_and_env(self):  # A1
        root = self.build()
        old = os.getcwd()
        self.addCleanup(os.chdir, old)
        os.chdir(root)
        out, code = run_argv([])
        self.assertEqual((out, code), (passes(*CATS), 0))
        os.chdir(old)
        with mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": root}):
            self.assertEqual(run_argv([]), (passes(*CATS), 0))
        with mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": os.path.join(root, "nope")}):
            self.input_fail(*run_argv([]), "CLAUDE_PROJECT_DIR is not a directory")
        os.mkdir(os.path.join(root, "sub"))
        with mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": os.path.join(root, "sub")}):
            self.input_fail(*run_argv([]), "top level")

    def test_a2_root_forms_ok(self):  # A2
        root = self.build()
        link = os.path.join(self.tmp, "link")
        os.symlink(root, link)
        wt = os.path.join(self.tmp, "wt")
        git(root, "worktree", "add", "-q", "-b", "wtb", wt)
        for r in (root + "/", link, wt):
            self.assertEqual(run_argv(["--root", r]), (passes(*CATS), 0), r)

    def test_a2_root_forms_refused(self):  # A2
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
            out, code = run_argv(["--root", r])
            self.input_fail(out, code, "/strict-delivery:init")

    def test_a3_root_twice(self):  # A3
        root = self.build()
        for argv in (["--root", root, "--root", root], ["--root", root, "--root=" + root],
                     ["--ro", root, "--root", root]):
            self.input_fail(*run_argv(argv), "invalid arguments: --root given more than once")

    def test_a4_base_values(self):  # A4
        root = self.build()
        sha = git(root, "rev-parse", "HEAD")
        for b in ("main", "HEAD", sha):
            self.assertEqual(self.run_("--base", b), (passes(*CATS), 0), b)
        for argv, needle in ((["--base="], ""), (["--base=-x"], ""), (["--base=^x"], ""),
                             (["--base", "nosuchref"], ""), (["--base", "a" * 41], ""),
                             (["--base"], "expected one argument")):
            self.input_fail(*self.run_(*argv), needle)

    def test_a4_absent_ref_is_one_input_line(self):  # M1
        root = self.build([lasting(ID)], {"CLAUDE.md": "nothing\n"})  # other categories hold failures
        out, code = self.run_("--base", "nosuchref")
        self.input_fail(out, code)

    def test_a4_default_base_is_config_base_branch(self):  # A4
        cfg = {**minimal_config(), "base_branch": "trunk"}
        self.build(cfg=cfg)
        self.input_fail(*self.run_())
        git(self.work, "branch", "trunk")
        self.assertEqual(self.run_(), (passes(*CATS), 0))

    def test_a5_base_twice(self):  # A5
        self.build()
        for argv in (["--base", "a", "--base", "b"], ["--base", "a", "--base=b"], ["--ba", "a", "--base", "b"]):
            self.input_fail(*self.run_(*argv), "--base given more than once")

    def test_a6_base_abbreviation(self):  # A6
        self.build()
        self.assertEqual(self.run_("--ba", "main"), (passes(*CATS), 0))

    def test_a7_json_position(self):  # A7
        root = self.build()
        out, code = run_argv(["--json", "--root", root])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["gate"], "decisions")
        self.input_fail(*run_argv(["--root", root, "--json"]), "unrecognized arguments: --json")
        out, code = run_argv(["--json", "--json", "--root", root])  # the first is the flag, the second is refused
        self.assertEqual(code, 1)
        self.assertEqual([ln["id"] for ln in json.loads(out)["lines"]], ["decisions.input"])
        self.assertIn("unrecognized arguments: --json", out)

    def test_a8_unknown_positional_help(self):  # A8
        root = self.build()
        for argv in (["--foo"], ["extra"]):
            self.input_fail(*run_argv(["--root", root] + argv), "invalid arguments:")
        for h in ("-h", "--help"):
            self.input_fail(*run_argv([h]), "help requested; no gate was run")

    def test_a9_main_reads_sys_argv(self):  # A9
        root = self.build()
        with mock.patch.object(sys, "argv", ["prog", "--root", root]):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(gate_decisions.main(), 0)
            self.assertEqual(out.getvalue(), passes(*CATS))
        self.assertEqual(gate_decisions.PRODUCES, ())

    def test_a10_config(self):  # A10
        make_repo(self.work)
        cfgp = os.path.join(self.work, ".strict-delivery/config.yml")
        with open(cfgp, "w") as fh:
            fh.write("a: [\n")
        self.input_fail(*self.run_())
        write_record(self.work, ".strict-delivery/config.yml", {**minimal_config(), "base_branch": 1})
        self.input_fail(*self.run_(), "base_branch")

    def test_a10_missing_config_is_input_fail(self):
        git(self.work, "init", "-q", "-b", "main")
        out, code = self.run_()
        self.assertTrue(out.startswith("FAIL decisions.input:"), out)
        self.assertIn("/strict-delivery:init", out)
        self.assertEqual(code, 1)

    def test_a10_config_read_from_root_not_checkout(self):  # A10
        self.build(cfg={**minimal_config(), "decisions": {"scan": []}},
                   files={"docs/a.md": OID + "\n"}, rows=[row(OID)])
        self.assertEqual(self.run_(), (passes(*CATS), 0))  # the repository under test, not this checkout

    def test_a11_dispatcher(self):  # A11
        root = self.build()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = gates_main.main(["check", "decisions", "--root", root])
        self.assertEqual((out.getvalue(), code), (passes(*CATS), 0))
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(gates_main.main(["check", "--json", "decisions"]), 2)
        self.assertIn("usage", err.getvalue())
        p = subprocess.run([sys.executable, "-m", "gates", "check", "decisions", "--root", root], cwd=REPO,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual((p.stdout.decode(), p.returncode), (passes(*CATS), 0))


class RepoStateTests(Base):  # R1-R5
    def test_empty_registers_pass_every_category(self):  # R1
        self.build()
        out, code = self.run_()
        for c in CATS:
            self.assertIn("PASS decisions." + c, out)
        self.assertEqual((out, code), (passes(*CATS), 0))

    def test_decisions_dir_with_generated_files_only(self):  # R1
        self.build(files={DEC + "/index.yml": "x: 1\n", DEC + "/in-force.md": "# x\n"})
        self.assertEqual(self.run_(), (passes(*CATS), 0))

    def test_r2_unborn_head(self):
        git(self.work, "init", "-q", "-b", "main")
        write_record(self.work, ".strict-delivery/config.yml", minimal_config())
        self.input_fail(*self.run_())

    def test_r2_detached_head(self):
        root = self.build([row(ID)])
        git(root, "checkout", "-q", "--detach")
        self.assertEqual(self.run_(), (passes(*CATS), 0))

    def test_r2_shallow_without_merge_base(self):
        src = self.build([row(ID)])
        self.other_branch()
        git(src, "commit", "-q", "--allow-empty", "-m", "f1")
        git(src, "checkout", "-q", "main")
        git(src, "commit", "-q", "--allow-empty", "-m", "m1")
        clone = os.path.join(self.tmp, "clone")
        git(self.tmp, "clone", "-q", "--depth", "1", "--no-single-branch", "file://" + src, clone)
        git(clone, "checkout", "-q", "feat")
        self.input_fail(*run_argv(["--root", clone]))

    def test_r2_base_equals_head_uncommitted_deletion(self):
        root = self.build([row(ID)])
        os.rename(os.path.join(root, DEC, ID + ".yml"), os.path.join(self.tmp, "away.yml"))
        out, code = self.run_("--base", "HEAD")
        self.assertIn("FAIL decisions.base.deleted.%s: %s/%s.yml exists on HEAD; records on the base branch are "
                      "never deleted\n" % (ID, DEC, ID), out)
        self.assertEqual(code, 1)

    def test_r3_finding_file_in_decisions_dir(self):
        finding = {"schema": FTAG, "id": "F-20261031-k3f9"}
        write_record(make_repo(self.work), DEC + "/F-20261031-k3f9.yml", finding)
        commit_all(self.work, "f")
        out, code = self.run_()
        f = DEC + "/F-20261031-k3f9.yml"
        self.assertIn("FAIL decisions.store.id.%s: " % f, out)
        self.assertTrue(any(ln.startswith("FAIL decisions.schema.%s: " % f) for ln in out.splitlines()), out)
        self.assertNotIn("PASS decisions.store", out)
        self.assertNotIn("PASS decisions.schema", out)
        self.assertEqual(code, 1)

    def test_r4_register_layout_is_input_fail(self):
        for name, make in (("x.yaml", lambda p: open(p, "w").close()), (".gitkeep", lambda p: open(p, "w").close()),
                           ("sub", os.mkdir), ("lnk.yml", lambda p: os.symlink("/dev/null", p)),
                           ("fifo.yml", os.mkfifo)):
            with self.subTest(name):
                self.work = os.path.join(self.tmp, "w_" + name.replace(".", "_"))
                os.mkdir(self.work)
                root = self.build([row(ID)])
                make(os.path.join(root, DEC, name))
                out, code = self.run_(root=root)
                self.input_fail(out, code, DEC + "/" + name)

    def test_r4_directory_is_a_symlink_or_a_file(self):
        root = self.build()
        os.makedirs(os.path.join(root, ".strict-delivery/state"))
        os.symlink(self.tmp, os.path.join(root, DEC))
        self.input_fail(*self.run_(), DEC)

    def test_r4_directory_is_a_file(self):
        self.build(files={DEC: "not a directory\n"})
        self.input_fail(*self.run_(), DEC + ": is not a directory")

    def test_r4_parent_is_a_symlink(self):
        root = self.build()
        real = os.path.join(self.tmp, "state")
        os.makedirs(os.path.join(real, "decisions"))
        os.makedirs(os.path.join(root, ".strict-delivery"), exist_ok=True)
        os.symlink(real, os.path.join(root, ".strict-delivery/state"))
        self.input_fail(*self.run_(), ".strict-delivery/state: is a symlink")

    def test_r4_record_yaml_error_or_non_mapping(self):
        root = self.build()
        self.put(DEC + "/" + ID + ".yml", "a: [\n")
        self.input_fail(*self.run_(), ID)
        self.put(DEC + "/" + ID + ".yml", "- a\n")
        self.input_fail(*self.run_(), "top level must be a mapping")

    def test_r5_record_without_usable_id_is_keyed_by_file(self):  # Q-1c1-1
        bad = row("ignored")
        for i, bid in enumerate((None, 1, "nonsense")):
            r = dict(bad)
            if bid is None:
                del r["id"]
            else:
                r["id"] = bid
            r["class"] = "zzz"
            write_record(self.build(commit=False) if i == 0 else self.work, "%s/x%d.yml" % (DEC, i), r)
        commit_all(self.work, "x")
        out, code = self.run_()
        for i in range(3):
            f = "%s/x%d.yml" % (DEC, i)
            self.assertIn("FAIL decisions.schema.%s: class: zzz is not in decision_classes.owner_only\n" % f, out)
            self.assertIn("FAIL decisions.store.id.%s: " % f, out)
        self.assertEqual(code, 1)

    def test_r5_duplicate_id_in_two_files_is_keyed_by_file(self):  # Q-1c1-1
        r = lasting(ID, landed_in=["README.md"])
        root = self.build(files={"README.md": ID})
        for n in ("a", "b"):
            write_record(root, "%s/%s.yml" % (DEC, n), r)
        commit_all(root, "dup")
        out, _ = self.run_()
        for n in ("a", "b"):
            f = "%s/%s.yml" % (DEC, n)
            self.assertIn("FAIL decisions.landed.%s: landed_in: README.md is not a playbook" % f, out)
        self.assertIn("FAIL decisions.store.duplicate.%s: " % ID, out)
        self.assertNotIn("decisions.landed.%s:" % ID, out)


class CategoryTests(Base):  # C1-C12
    def test_c1_schema_one_line_per_error(self):
        r = row(ID, question=None, **{"class": "zzz"})
        self.build([r])
        out, code = self.run_()
        ls = [ln for ln in out.splitlines() if ln.startswith("FAIL decisions.schema." + ID + ":")]
        self.assertEqual(len(ls), 2, out)
        self.assertTrue(any("question" in ln for ln in ls))
        self.assertIn("FAIL decisions.schema.%s: class: zzz is not in decision_classes.owner_only\n" % ID, out)
        self.assertNotIn("PASS decisions.schema", out)
        self.assertEqual(code, 1)

    def test_c1_wrong_tag_and_status_matrix(self):
        self.build([row(ID, schema=FTAG)])
        self.assertIn("FAIL decisions.schema.%s: schema: expected %s, got %s\n" % (ID, TAG, FTAG), self.run_()[0])

    def test_c1_answered_without_answer(self):
        self.build([row(ID, "answered", answer=None)])
        out, _ = self.run_()
        self.assertTrue(any(ln.startswith("FAIL decisions.schema.%s: answer" % ID) for ln in out.splitlines()), out)

    def test_c2_store_errors(self):
        root = self.build()
        write_record(root, DEC + "/DEC-20261031-AAAA.yml", row("DEC-20261031-aaaa"))  # name differs by case only
        write_record(root, DEC + "/" + ID + ".yml", row(ID))
        write_record(root, DEC + "/DEC-20261031-bbbb.yml", row(ID))
        write_record(root, DEC + "/DEC-20261031-cccc.yml", row(ID))
        commit_all(root, "x")
        out, _ = self.run_()
        self.assertIn("FAIL decisions.store.name.%s/DEC-20261031-AAAA.yml: " % DEC, out)
        self.assertIn("FAIL decisions.store.name.%s/DEC-20261031-bbbb.yml: " % DEC, out)
        self.assertIn("FAIL decisions.store.duplicate.%s: id %s appears in 3 files" % (ID, ID), out)
        self.assertNotIn("PASS decisions.store", out)

    def test_c3_deleted_base_decision_fails(self):  # Review Focus 1
        for status in ("open", "answered", "withdrawn"):
            with self.subTest(status):
                self.work = os.path.join(self.tmp, "w_" + status)
                os.mkdir(self.work)
                r = lasting(ID) if status == "answered" else row(ID, status)
                root = self.build([r], {"CLAUDE.md": CLAUDE})
                git(root, "rm", "-q", "%s/%s.yml" % (DEC, ID))
                out, code = self.run_("--base", "HEAD")
                self.assertIn("FAIL decisions.base.deleted.%s: %s/%s.yml exists on HEAD; records on the base "
                              "branch are never deleted\n" % (ID, DEC, ID), out)
                self.assertNotIn("PASS decisions.base", out)
                self.assertEqual(code, 1)

    def test_c3_rename_is_a_deletion(self):
        root = self.build([row(ID)])
        git(root, "mv", "%s/%s.yml" % (DEC, ID), "%s/%s.yml" % (DEC, ID3))
        out, _ = self.run_()
        self.assertIn("FAIL decisions.base.deleted.%s: " % ID, out)

    def test_c3_dropped_by_rebase_like_history(self):
        root = self.build()
        self.other_branch()
        write_record(root, "%s/%s.yml" % (DEC, ID), row(ID))
        commit_all(root, "add")
        git(root, "checkout", "-q", "main")
        git(root, "merge", "-q", "--ff-only", "feat")
        git(root, "checkout", "-q", "-b", "g")
        git(root, "rm", "-q", "%s/%s.yml" % (DEC, ID))
        commit_all(root, "drop")
        self.assertIn("FAIL decisions.base.deleted.%s: " % ID, self.run_()[0])

    def test_c4_edited_answered_decision_fails_with_remedy(self):  # Review Focus 2
        root = self.build([lasting(ID)], {"CLAUDE.md": CLAUDE})
        write_record(root, "%s/%s.yml" % (DEC, ID), lasting(ID, answer="Typo fix"))
        out, code = self.run_()
        line = [ln for ln in out.splitlines() if ln.startswith("FAIL decisions.base.immutable." + ID + ":")]
        self.assertEqual(len(line), 1, out)
        self.assertIn("supersedes: " + ID, line[0])
        self.assertEqual(code, 1)

    def test_c4_open_edit_ok_withdrawn_edit_fails_same_value_ok(self):
        root = self.build([row(ID), row(ID3, "withdrawn")])
        write_record(root, "%s/%s.yml" % (DEC, ID), row(ID, question="Changed?"))
        write_record(root, "%s/%s.yml" % (DEC, ID3), row(ID3, "withdrawn"))  # re-emitted, same parsed value
        self.assertEqual(self.run_(), (passes(*CATS), 0))
        write_record(root, "%s/%s.yml" % (DEC, ID3), row(ID3, "withdrawn", question="Changed?"))
        self.assertIn("FAIL decisions.base.immutable.%s: " % ID3, self.run_()[0])

    def test_c4_one_vs_true_is_immutable(self):
        root = self.build([row(ID, "withdrawn", flag=1)])
        write_record(root, "%s/%s.yml" % (DEC, ID), row(ID, "withdrawn", flag=True))
        self.assertIn("FAIL decisions.base.immutable.%s: " % ID, self.run_()[0])

    def test_c5_collision_with_base_tip(self):
        root = self.build()
        self.other_branch()
        write_record(root, "%s/%s.yml" % (DEC, ID), row(ID))
        write_record(root, "%s/%s.yml" % (DEC, ID3), row(ID3))
        commit_all(root, "feat")
        git(root, "checkout", "-q", "main")
        write_record(root, "%s/%s.yml" % (DEC, ID), row(ID, question="Other?"))
        write_record(root, "%s/%s.yml" % (DEC, ID3), row(ID3))  # same content: a cherry-pick
        commit_all(root, "main")
        git(root, "checkout", "-q", "feat")
        out, code = self.run_()
        self.assertIn("FAIL decisions.base.collision.%s: id %s already exists on main; mint a new id\n" % (ID, ID), out)
        self.assertNotIn("collision." + ID3, out)
        self.assertEqual(code, 1)

    def test_c6_default_base_is_merge_base_with_main(self):
        root = self.build([row(ID)])
        self.other_branch()
        git(root, "rm", "-q", "%s/%s.yml" % (DEC, ID))
        commit_all(root, "del")
        out, code = self.run_()
        self.assertIn("FAIL decisions.base.deleted.%s: " % ID, out)
        self.assertEqual(code, 1)

    def test_c7_unparsable_base_side_record_is_input_fail(self):
        root = self.build()
        self.put(DEC + "/" + ID + ".yml", "a: [\n")
        commit_all(root, "bad")
        self.other_branch()
        write_record(root, "%s/%s.yml" % (DEC, ID), row(ID))
        self.input_fail(*self.run_(), "main:" + DEC + "/" + ID + ".yml")

    def test_c7_non_record_entries_at_base_ignored(self):
        root = self.build(files={DEC + "/notes.txt": "x", DEC + "/x.yaml": "x"})
        git(root, "rm", "-q", DEC + "/notes.txt", DEC + "/x.yaml")
        self.assertEqual(self.run_("--base", "HEAD"), (passes(*CATS), 0))

    def test_c9_lasting_landed_in_must_cite_id(self):
        self.build([lasting(ID)], {"CLAUDE.md": "nothing here\n"})
        out, code = self.run_()
        self.assertIn("FAIL decisions.landed.%s: landed_in: CLAUDE.md does not contain the decision id %s\n"
                      % (ID, ID), out)
        self.assertNotIn("PASS decisions.landed", out)
        self.assertEqual(code, 1)

    def test_c9_good_cites_and_anchor_pass(self):
        self.build([lasting(ID, landed_in=["CLAUDE.md#anything"])], {"CLAUDE.md": CLAUDE})
        self.assertEqual(self.run_(), (passes(*CATS), 0))

    def test_c9_landed_in_spec_fails(self):
        spec = "docs/strict-delivery/specs/x.md"
        self.build([lasting(ID, landed_in=[spec])], {spec: ID})
        out, code = self.run_()
        self.assertIn("FAIL decisions.landed.%s: " % ID, out)
        self.assertIn("is a spec", out)
        self.assertEqual(code, 1)

    def test_c9_landed_in_outside_allow_list_fails(self):  # OQ-9
        self.build([lasting(ID, landed_in=["README.md"])], {"README.md": ID})
        out, _ = self.run_()
        self.assertIn("FAIL decisions.landed.%s: landed_in: README.md is not a playbook, CLAUDE.md or "
                      "architecture.md\n" % ID, out)

    def test_c9_untracked_cite_fails(self):
        self.build([lasting(ID)], {"CLAUDE.md": CLAUDE}, commit=False)
        git(self.work, "add", "-A")
        git(self.work, "reset", "-q", "--", "CLAUDE.md")
        git(self.work, "commit", "-q", "-m", "x")
        self.assertIn("landed_in: CLAUDE.md is not a tracked regular file", self.run_()[0])

    def test_c9_cite_replaced_by_symlink_or_not_utf8(self):
        root = self.build([lasting(ID)], {"CLAUDE.md": CLAUDE})
        os.rename(os.path.join(root, "CLAUDE.md"), os.path.join(self.tmp, "c.md"))
        os.symlink(os.path.join(self.tmp, "c.md"), os.path.join(root, "CLAUDE.md"))
        self.assertIn("FAIL decisions.landed.%s: landed_in: CLAUDE.md cannot be read" % ID, self.run_()[0])
        os.unlink(os.path.join(root, "CLAUDE.md"))
        self.put("CLAUDE.md", b"\xff\xfe " + ID.encode())
        self.assertIn("cannot be read as a UTF-8 regular file (not valid UTF-8)", self.run_()[0])

    def test_c9_tracked_cite_deleted_in_working_tree(self):
        root = self.build([lasting(ID)], {"CLAUDE.md": CLAUDE})
        os.rename(os.path.join(root, "CLAUDE.md"), os.path.join(self.tmp, "c.md"))
        out, code = self.run_()
        self.assertIn("FAIL decisions.landed.%s: landed_in: CLAUDE.md cannot be read as a UTF-8 regular file "
                      "(No such file or directory)\n" % ID, out)
        self.assertNotIn("PASS decisions.landed", out)
        self.assertEqual(code, 1)

    def test_c10_staged_cite_counts_as_tracked(self):
        root = self.build([lasting(ID)], commit=False)
        self.put("CLAUDE.md", CLAUDE)
        git(root, "add", "-A")
        self.assertEqual(self.run_(), (passes(*CATS), 0))

    def test_c10_tracked_symlink_cite_fails(self):
        root = self.build([lasting(ID)], {"real.md": CLAUDE}, commit=False)
        os.symlink("real.md", os.path.join(root, "CLAUDE.md"))
        commit_all(root, "x")
        self.assertIn("FAIL decisions.landed.%s: landed_in: CLAUDE.md is not a tracked regular file" % ID,
                      self.run_()[0])

    def test_c11_supersedes_open_decision_fails_refs(self):
        self.build([row(OID), row(ID, "answered", supersedes=OID)])
        out, code = self.run_()
        self.assertIn("FAIL decisions.refs.supersedes.%s: supersedes: %s is not answered\n" % (ID, OID), out)
        self.assertEqual(code, 1)

    def test_c11_other_ref_errors(self):
        self.build([row(ID, "answered", supersedes=ID), row(ID3, "answered", supersedes=ID4),
                    row(ID4, "answered", supersedes=ID3),
                    row(OID, "answered", checked_against=["DEC-20261031-zzzz"]),
                    row("DEC-20261031-2222", "answered"), row("DEC-20261031-3333", "answered", supersedes="DEC-20261031-2222"),
                    row("DEC-20261031-4444", "answered", supersedes="DEC-20261031-2222"),
                    row("DEC-20261031-5555", supersedes="DEC-20261031-6666")])
        out, _ = self.run_()
        self.assertIn("a supersedes cycle", out)
        for needle in ("decisions.refs.supersedes.%s: supersedes: a decision cannot supersede itself" % ID,
                       "decisions.refs.supersedes.%s: " % ID3,
                       "decisions.refs.checked.%s: checked_against: no record for DEC-20261031-zzzz" % OID,
                       "decisions.refs.fork.DEC-20261031-2222: ",
                       "decisions.refs.supersedes.DEC-20261031-5555: supersedes: DEC-20261031-6666 has no record"):
            self.assertIn("FAIL " + needle, out)

    def test_c11_withdrawn_superseder_of_withdrawn_target_ok(self):
        self.build([row(ID, "withdrawn"), row(ID3, "withdrawn", supersedes=ID)])
        self.assertIn("PASS decisions.refs", self.run_()[0])

    def test_c12_malformed_rows_still_run_every_category(self):
        r = lasting(ID, supersedes="DEC-20261031-zzzz", landed_in=["README.md"], question=None)
        self.build([r], {"README.md": ID})
        out, code = self.run_()
        for cat in ("schema", "landed", "refs"):
            self.assertRegex(out, r"FAIL decisions\.%s\." % cat)
        self.assertIn("PASS decisions.store", out)
        self.assertEqual(code, 1)


def case_files():
    """docs/ files with an open id at known places: name -> (content bytes, expected 1-based lines)."""
    o = OID.encode()
    return {
        "start": (o + b"\n", [1]),
        "end_no_newline": (b"a\n b " + o, [2]),
        "fence": (b"x\n```\n" + o + b"\n```\n", [3]),
        "punct": (b"\n\n(" + o + b"),\n", [3]),
        "ext": (o + b".yml", [1]),
        "nonascii_before": ("é".encode() + o, [1]),
        "twice": (o + b" " + o + b"\n", [1, 1]),
        "crlf": (b"a\r\n" + o + b"\r\n", [2]),
        "lone_cr": (b"a\r" + o + b"\n", [1]),
        "vt_ff": (b"a\x0b" + o + b"\n\x0c" + o, [1, 2]),
        "u2028": ("a ".encode() + o + b"\n" + o, [1, 2]),
        "bom": (b"\xef\xbb\xbf" + o, [1]),
        "binary": (b"\x89PNG\r\n\x1a\n\x00\xff\xfe" + o + b"\xfe", [3]),
        "bad_utf8": (b"\xff\xfe\n" + o, [2]),
        "longer_after": (o + b"a", []),
        "longer_before_x": (b"X" + o, []),
        "longer_before_us": (b"_" + o, []),
        "longer_before_dash": (b"-" + o, []),
        "longer_before_digit": (b"9" + o, []),
        "longer_after_dash": (o + b"-", []),
        "longer_after_us": (o + b"_", []),
        "longer_after_digit": (o + b"9", []),
        "empty": (b"", []),
        "bad_utf8_no_id": (b"\xff\xfe", []),
    }


class OpenRefTests(Base):  # O1-O16
    def test_empty_registers_no_scan_hits(self):
        self.build(files={"docs/a.md": "nothing\n"})
        self.assertEqual(self.run_(), (passes(*CATS), 0))

    def test_open_ref_in_docs_fails(self):
        self.build([row(OID)], {"docs/a.md": "l1\nl2\nsee " + OID + " now\n"})
        out, code = self.run_()
        self.assertIn("FAIL decisions.open-ref.docs/a.md:3: docs/a.md:3 references unanswered " + OID
                      + "; the human answers it first\n", out)
        self.assertNotIn("PASS decisions.open-ref", out)
        self.assertIn("PASS decisions.scan", out)
        self.assertEqual(code, 1)

    def test_o7_o8_o10_o11_positions_and_kinds(self):
        cases = case_files()
        files = {"docs/%s.md" % k: v[0] for k, v in cases.items()}
        self.build([row(OID)], files)
        out, _ = self.run_()
        got = {}
        for ln in out.splitlines():
            if ln.startswith("FAIL decisions.open-ref."):
                head = ln[len("FAIL decisions.open-ref."):].split(": ", 1)[0]
                f, n = head.rsplit(":", 1)
                got.setdefault(f, []).append(int(n))
        for k, (_, expected) in cases.items():
            self.assertEqual(got.get("docs/%s.md" % k, []), expected, k)
        self.assertIn("PASS decisions.scan", out)  # binary and invalid UTF-8 are scanned, not failed (Q-1c1-2)

    def test_o11_large_file(self):
        self.build([row(OID)], {"docs/big.md": b"x" * 10_000_000 + b"\n" + OID.encode()})
        self.assertIn("FAIL decisions.open-ref.docs/big.md:2: ", self.run_()[0])

    def test_o9_order_and_two_ids_on_a_line(self):
        self.build([row(OID), row(ID3)], {"docs/b.md": OID + "\n", "docs/a.md": "%s %s\n%s\n" % (ID3, OID, ID3)})
        got = [ln.split(": ", 1)[0] for ln in self.lines() if ln.startswith("FAIL decisions.open-ref")]
        self.assertEqual(got, ["FAIL decisions.open-ref.docs/a.md:1", "FAIL decisions.open-ref.docs/a.md:1",
                               "FAIL decisions.open-ref.docs/a.md:2", "FAIL decisions.open-ref.docs/b.md:1"])
        out = self.run_()[0]
        self.assertLess(out.index("references unanswered " + ID3), out.index("references unanswered " + OID))

    def test_o1_only_open_ids_with_valid_form(self):
        rows = [row(ID, "answered"), row(ID3, "withdrawn"), row(ID4, "answered"),
                row("DEC-20261031-2222", "answered", supersedes=ID4)]
        write_record(make_repo(self.work), DEC + "/bad.yml", row("bad-id"))
        for r in rows:
            write_record(self.work, "%s/%s.yml" % (DEC, r["id"]), r)
        self.put("docs/a.md", " ".join([ID, ID3, ID4, "bad-id"]) + "\n")
        commit_all(self.work, "x")
        out, _ = self.run_()
        self.assertIn("PASS decisions.open-ref", out)
        self.assertIn("FAIL decisions.store.id.%s/bad.yml" % DEC, out)

    def test_answered_ref_passes(self):
        self.build([row(ID, "answered")], {"docs/a.md": ID + "\n"})
        self.assertEqual(self.run_(), (passes(*CATS), 0))

    def test_open_ref_in_untracked_or_ignored_file_ignored(self):
        root = self.build([row(OID)], {".gitignore": "docs/gen.md\n"})
        self.put("docs/gen.md", OID)
        self.put("docs/new.md", OID)
        git(root, "add", ".gitignore")
        self.assertEqual(self.run_()[0].count("FAIL"), 0)
        self.assertIn("PASS decisions.open-ref", self.run_()[0])

    def test_o2_globs(self):
        files = {"docs/x/y/z.md": OID, "docs": "", "CLAUDE.md": OID, "sub/CLAUDE.md": OID, "src/a.md": OID,
                 ".strict-delivery/playbooks/x.md": OID}
        files.pop("docs")
        self.build([row(OID)], files)
        got = sorted(ln.split(":")[0][len("FAIL decisions.open-ref."):] for ln in self.lines()
                     if ln.startswith("FAIL decisions.open-ref"))
        self.assertEqual(got, [".strict-delivery/playbooks/x.md", "CLAUDE.md", "docs/x/y/z.md"])

    def test_open_ref_in_playbook_fails(self):
        self.build([row(OID)], {".strict-delivery/playbooks/x.md": OID + "\n"})
        self.assertIn(".strict-delivery/playbooks/x.md:1 references unanswered " + OID, self.run_()[0])

    def test_o3_custom_empty_and_double_match(self):
        cfg = {**minimal_config(), "decisions": {"scan": ["src/*.py", "src/a.*"]}}
        self.build([row(OID)], {"src/a.py": OID, "docs/a.md": OID}, cfg=cfg)
        out = self.run_()[0]
        self.assertEqual(out.count("FAIL decisions.open-ref.src/a.py:1"), 1)
        self.assertNotIn("docs/a.md", out)

    def test_o3_scan_empty_list(self):
        cfg = {**minimal_config(), "decisions": {"scan": []}}
        self.build([row(OID)], {"docs/a.md": OID}, cfg=cfg)
        self.assertEqual(self.run_(), (passes(*CATS), 0))

    def test_o4_state_dirs_excluded(self):
        files = {".strict-delivery/state/plans/p/handoff.md": "open_decisions: [%s]\n" % OID,
                 ".strict-delivery/state2/x.md": OID + "\n", ".strict-delivery/state": "x"}
        files.pop(".strict-delivery/state")
        cfg = {**minimal_config(), "decisions": {"scan": [".strict-delivery/**"]}}
        self.build([row(OID, checked_against=[ID3]), row(ID3, "answered", checked_against=[OID])], files, cfg=cfg)
        out = self.run_()[0]
        self.assertIn("FAIL decisions.open-ref..strict-delivery/state2/x.md:1: ", out)
        self.assertEqual(out.count("FAIL decisions.open-ref"), 1, out)

    def test_o4_custom_state_path(self):
        cfg = {**minimal_config(), "paths": {"state": "docs/st"}}
        self.build([row(OID)], {"docs/st/x.md": OID, "docs/st2/x.md": OID}, cfg=cfg)
        out = self.run_()[0]
        self.assertIn("FAIL decisions.open-ref.docs/st2/x.md:1: ", out)
        self.assertNotIn("docs/st/x.md", out)

    def test_o6_working_tree_content_is_read(self):
        root = self.build([row(OID)], {"docs/a.md": "clean\n", "docs/b.md": OID + "\n"})
        self.put("docs/a.md", OID + "\n")
        self.put("docs/b.md", "clean\n")
        out = self.run_()[0]
        self.assertIn("FAIL decisions.open-ref.docs/a.md:1", out)
        self.assertNotIn("docs/b.md", out)

    def _scan_fail(self, out, code, f="docs/x.md"):
        self.assertIn("FAIL decisions.scan.%s: " % f, out)
        self.assertNotIn("PASS decisions.scan", out)
        self.assertNotIn("PASS decisions.open-ref", out)
        self.assertEqual(code, 1)

    def test_o12_deleted_directory_symlink_and_parent_symlink(self):
        root = self.build([row(OID)], {"docs/x.md": "a\n", "docs/sub/y.md": "a\n"})
        away = os.path.join(self.tmp, "away")
        os.mkdir(away)
        os.rename(os.path.join(root, "docs/x.md"), os.path.join(away, "x.md"))
        self._scan_fail(*self.run_())
        os.mkdir(os.path.join(root, "docs/x.md"))
        self._scan_fail(*self.run_())
        os.rmdir(os.path.join(root, "docs/x.md"))
        self.put("../real.md", OID)
        os.symlink(os.path.join(self.tmp, "real.md"), os.path.join(root, "docs/x.md"))
        out, code = self.run_()
        self._scan_fail(out, code)
        self.assertNotIn("references unanswered", out)  # never followed
        os.unlink(os.path.join(root, "docs/x.md"))
        self.put("docs/x.md", "a\n")
        os.rename(os.path.join(root, "docs/sub"), os.path.join(away, "sub"))
        os.symlink(os.path.join(away, "sub"), os.path.join(root, "docs/sub"))
        self._scan_fail(*self.run_(), f="docs/sub/y.md")

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root reads everything")
    def test_o12_permission_denied(self):
        root = self.build([row(OID)], {"docs/x.md": "a\n"})
        os.chmod(os.path.join(root, "docs/x.md"), 0)
        self.addCleanup(os.chmod, os.path.join(root, "docs/x.md"), 0o644)
        self._scan_fail(*self.run_())

    def test_o13_tracked_symlink_not_scanned(self):
        root = self.build([row(OID)], {"docs/a.md": OID + "\n"}, commit=False)
        os.symlink("a.md", os.path.join(root, "docs/link.md"))
        commit_all(root, "x")
        out = self.run_()[0]
        self.assertEqual(out.count("FAIL decisions.open-ref"), 1)
        self.assertIn("docs/a.md:1", out)
        self.assertIn("PASS decisions.scan", out)

    def test_o14_scan_fails_without_open_decisions(self):
        root = self.build(files={"docs/x.md": "a\n"})
        os.rename(os.path.join(root, "docs/x.md"), os.path.join(self.tmp, "x.md"))
        self._scan_fail(*self.run_())

    def test_j2_file_names_with_backslash_and_newline_are_escaped_once(self):
        self.build([row(OID)], {"docs/a\\b.md": OID, "docs/c\nd.md": OID})
        out = self.run_()[0]
        self.assertIn("FAIL decisions.open-ref.docs/a\\\\b.md:1: docs/a\\\\b.md:1 references", out)
        self.assertIn("FAIL decisions.open-ref.docs/c\\nd.md:1: docs/c\\nd.md:1 references", out)
        self.assertEqual(len(out.splitlines()), out.count("\n"))

    def test_j2_cite_with_newline_and_backslash_is_escaped_once(self):
        self.build([lasting(ID, landed_in=["CLAUDE.md\nx\\y"])], {"CLAUDE.md": CLAUDE})
        out = self.run_()[0]
        self.assertIn("FAIL decisions.landed.%s: landed_in: CLAUDE.md\\nx\\\\y is not a normalised repo-relative "
                      "path with an optional non-empty #anchor\n" % ID, out)
        self.assertEqual(len(out.splitlines()), out.count("\n"))

    @unittest.skip("Task 1c0.1 (block/b1c, PR-1c0) not on this branch: decisions.landed_errors escapes map/list "
                   "cites once only from there")
    def test_j2_map_and_list_cite_escaped_once(self):
        self.build([lasting(ID, landed_in=[{"a": "b\nc"}, ["a\\b"]])], {"CLAUDE.md": CLAUDE})
        out = self.run_()[0]
        self.assertIn("FAIL decisions.landed.%s: landed_in: {a: b\\nc} is not a string\n" % ID, out)
        self.assertIn("FAIL decisions.landed.%s: landed_in: [a\\\\b] is not a string\n" % ID, out)
        self.assertEqual(len(out.splitlines()), out.count("\n"))


class OutputTests(Base):  # J1, J3
    def test_json_output_shape(self):
        self.build([row(OID)], {"docs/a.md": OID})
        text, code = run_argv(["--json", "--root", self.work])
        doc = json.loads(text)
        plain = self.run_()[0].splitlines()
        self.assertEqual(code, 1)
        self.assertEqual(sorted(doc), ["gate", "lines", "ok"])
        self.assertEqual((doc["gate"], doc["ok"]), ("decisions", False))
        rendered = ["PASS " + ln["id"] if ln["status"] == "PASS" else "FAIL %s: %s" % (ln["id"], ln["reason"])
                    for ln in doc["lines"]]
        self.assertEqual(rendered, plain)

    def test_exit_codes(self):
        self.build()
        self.assertEqual(self.run_()[1], 0)
        self.assertEqual(run_argv(["--root", os.path.join(self.tmp, "nope")])[1], 1)


if __name__ == "__main__":
    unittest.main()
