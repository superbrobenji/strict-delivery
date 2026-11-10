"""Tests of gates/gate_claims.py (plan Task 2a.3) through ``gate_claims.main`` on real fixture repositories.

Row ids in comments refer to the Task 2a.3 input-domain table (revision 1, filled copy task-2a.3-domain-filled.md).
Blob ids in fixtures are read from git by the test (``hash-object``), never from ``gitinfo.blob_id``. Expected lines
are written out literally. ``GATES["claims"]`` (row R1) is registered (order rule O3 met at the f6b703a merge)."""
import builtins
import contextlib
import io
import json
import os
import sys
import unicodedata
import unittest
from unittest import mock

from gates import __main__ as gates_main
from gates import gate_claims
from gates.lib import claims as claims_lib, gitinfo, migrations
from tests.helpers import TOP, GitIsolatedTestCase, commit_all, git, make_repo, minimal_config, write_record

TAG = "claim/%d" % migrations.current_version("claim")
CID = "C-20261031-k3f9"
CID2 = "C-20261031-m4n5"
CDIR = ".strict-delivery/state/claims"
FILE = CDIR + "/docs--a.yml"
ALL_PASS = ("PASS claims.schema\nPASS claims.store\nPASS claims.document\nPASS claims.stale\n"
            "PASS claims.base\n")
INIT = "FAIL claims.input: git rev-parse --show-toplevel failed (exit 128); run /strict-delivery:init\n"
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run_argv(argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
        code = gate_claims.main(argv)
    return buf.getvalue(), code


def run(root, *args):
    """Plan Step 1: ``out, code = run(root, *args)`` calls ``gate_claims.main``; a leading ``--json`` stays first."""
    args = list(args)
    if args[:1] == ["--json"]:
        return run_argv(["--json", "--root", root] + args[1:])
    return run_argv(["--root", root] + args)


def write(root, rel, text):
    path = os.path.join(root, *rel.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)


def claim(cid, blob, path="src/x.txt", lines="1", **kw):
    c = {"id": cid, "text": "x holds", "cites": [{"path": path, "lines": lines, "blob": blob}],
         "direct": "grep -n x %s" % path, "contradiction": "grep -c y %s" % path, "by": "implementer"}
    c.update(kw)
    return c


class GateCase(GitIsolatedTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.root = make_repo(self.work)

    def blob(self, rel):
        return git(self.root, "hash-object", "--", rel)

    def seed(self, doc="docs/a.md", claims_=None, commit=True):
        """docs/a.md and src/x.txt committed; a claim file for ``doc`` citing src/x.txt with its blob."""
        write(self.root, doc, "# A\n")
        write(self.root, "src/x.txt", "x\n")
        if claims_ is None:
            claims_ = [claim(CID, self.blob("src/x.txt"))]
        rel = CDIR + "/" + doc[:-3].replace("/", "--") + ".yml"
        write_record(self.root, rel, {"schema": TAG, "document": doc, "claims": claims_})
        if commit:
            commit_all(self.root, "seed")
        return rel


# ------------------------------------------------------------------------------------------------ argv (A)

class ArgvTests(GateCase):
    def test_empty_register_passes_every_category(self):  # G2; plan Step 1
        out, code = run(self.root)
        for c in ["schema", "store", "document", "stale", "base"]:
            self.assertIn("PASS claims." + c, out)
        self.assertEqual((out, code), (ALL_PASS, 0))

    def test_A1_no_args_reads_project_dir_and_cwd(self):
        self.seed()
        with mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": self.root}):
            self.assertEqual(run_argv([]), (ALL_PASS, 0))
        old = os.getcwd()
        os.chdir(self.root)
        self.addCleanup(os.chdir, old)
        self.assertEqual(run_argv([]), (ALL_PASS, 0))
        os.chdir(self.tmp)  # contradiction: outside any repository the root check fails
        self.assertEqual(run_argv([]), (INIT, 1))

    def test_A2_A3_missing_or_non_repo_root(self):
        self.assertEqual(run(os.path.join(self.tmp, "missing")), (INIT, 1))
        plain = os.path.join(self.tmp, "plain")
        os.mkdir(plain)
        self.assertEqual(run(plain), (INIT, 1))

    def test_A2_git_missing_has_no_init_hint(self):
        with mock.patch.object(gitinfo, "toplevel", side_effect=gitinfo.GitNotFound("git not found on PATH; "
                                                                                    "install git")):
            self.assertEqual(run(self.root), ("FAIL claims.input: git not found on PATH; install git\n", 1))

    def test_A4_subdirectory_root(self):
        os.makedirs(os.path.join(self.root, "docs"))
        self.assertEqual(run(os.path.join(self.root, "docs")), ("FAIL claims.input: %s\n" % TOP, 1))

    def test_A5_repeated_root(self):
        want = ("FAIL claims.input: invalid arguments: --root given more than once\n", 1)
        self.assertEqual(run_argv(["--root", self.root, "--root", self.root]), want)
        self.assertEqual(run_argv(["--root=" + self.root, "--ro", self.root]), want)

    def test_A6_repeated_base(self):
        want = ("FAIL claims.input: invalid arguments: --base given more than once\n", 1)
        self.assertEqual(run(self.root, "--base", "main", "--base", "main"), want)
        self.assertEqual(run(self.root, "--base=main", "--ba", "main"), want)

    def test_A7_base_defaults_to_config_base_branch(self):
        cfg = minimal_config()
        cfg["base_branch"] = "trunk"
        write_record(self.root, ".strict-delivery/config.yml", cfg)
        commit_all(self.root, "trunk config")
        self.assertEqual(run(self.root), ("FAIL claims.input: git merge-base failed (exit 128)\n", 1))
        git(self.root, "branch", "trunk")
        self.assertEqual(run(self.root), (ALL_PASS, 0))
        self.assertEqual(run(self.root, "--base", "main"), (ALL_PASS, 0))

    def test_A8_absent_base_ref_is_the_only_line(self):
        self.seed()
        self.assertEqual(run(self.root, "--base", "no-such-ref"),
                         ("FAIL claims.input: git merge-base failed (exit 128)\n", 1))
        self.assertEqual(run(self.root, "--base", "main"), (ALL_PASS, 0))

    def test_A9_refused_base_forms(self):
        cases = [("--base=-x", "ref must not start with '-'"), ("--base=^main", "ref must not start with '^'"),
                 ("--base=" + "a" * 41, "ref must not hold more than 40 hex digits in a row")]
        for arg, reason in cases:
            with self.subTest(arg=arg):
                self.assertEqual(run(self.root, arg), ("FAIL claims.input: %s\n" % reason, 1))

    def test_A10_base_without_common_history(self):
        git(self.root, "checkout", "-q", "--orphan", "other")
        commit_all(self.root, "orphan")
        self.assertEqual(run(self.root), ("FAIL claims.input: git merge-base failed (exit 1)\n", 1))

    def test_json_output_shape(self):  # A11
        out, code = run(self.root, "--json")
        want = {"gate": "claims", "ok": True, "lines": [
            {"status": "PASS", "id": "claims." + c, "reason": ""}
            for c in ("schema", "store", "document", "stale", "base")]}
        self.assertEqual((json.loads(out), code), (want, 0))
        out, code = run_argv(["--json"] + ["--root", os.path.join(self.tmp, "missing")])
        self.assertEqual(json.loads(out)["lines"][0]["id"], "claims.input")
        self.assertEqual(code, 1)

    def test_A12_json_not_first(self):
        self.assertEqual(run(self.root, "--json", "x")[1], 1)
        self.assertEqual(run_argv(["--root", self.root, "--json"]),
                         ("FAIL claims.input: invalid arguments: unrecognized arguments: --json\n", 1))

    def test_A13_unknown_flag_and_help(self):
        self.assertEqual(run(self.root, "--x"),
                         ("FAIL claims.input: invalid arguments: unrecognized arguments: --x\n", 1))
        self.assertEqual(run(self.root, "-h"), ("FAIL claims.input: help requested; no gate was run\n", 1))

    def test_A14_main_none_reads_sys_argv(self):
        with mock.patch.object(sys, "argv", ["gate_claims", "--root", self.root]):
            self.assertEqual(run_argv(None), (ALL_PASS, 0))
        with mock.patch.object(sys, "argv", ["gate_claims", "--root", self.root, "--x"]):
            self.assertEqual(run_argv(None)[1], 1)

    def test_A15_R1_registered_through_main(self):
        # Row R1 (order rule O3 met: block/sd1 merged main f6b703a with PR-1d): `python3 -m gates check claims` runs
        # gate_claims through the production dispatch, with the same stdout and exit code as gate_claims.main.
        self.assertEqual(gates_main.GATES["claims"], "gates.gate_claims")
        err = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            self.assertEqual(gates_main.main(["check", "nope"]), 2)
        self.assertEqual(err.getvalue(), "usage: python3 -m gates check <gate> [args]\n"
                                         "gates: cites, claims, decisions, register, schema\n")

        def via_main(args):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
                code = gates_main.main(["check", "claims"] + args)
            return buf.getvalue(), code

        plain, js = ["--root", self.root], ["--json", "--root", self.root]
        self.seed()
        self.assertEqual(via_main(plain), (ALL_PASS, 0))
        self.assertEqual(via_main(plain), run_argv(plain))
        out, code = via_main(js)
        self.assertEqual((json.loads(out), code), ({"gate": "claims", "ok": True, "lines": [
            {"status": "PASS", "id": "claims." + c, "reason": ""}
            for c in ("schema", "store", "document", "stale", "base")]}, 0))
        self.assertEqual((out, code), run_argv(js))
        old = self.blob("src/x.txt")
        write(self.root, "src/x.txt", "changed\n")  # the failing fixture: the cited file changed, the claim did not
        now = self.blob("src/x.txt")
        out, code = via_main(plain)
        self.assertEqual(code, 1)
        self.assertIn("FAIL claims.stale.%s: cites.0: src/x.txt has blob %s; the claim records %s\n"
                      % (CID, now, old), out)
        self.assertEqual((out, code), run_argv(plain))
        out, code = via_main(js)
        doc = json.loads(out)
        self.assertEqual((doc["gate"], doc["ok"], code), ("claims", False, 1))
        self.assertIn(("FAIL", "claims.stale." + CID), [(ln["status"], ln["id"]) for ln in doc["lines"]])
        self.assertEqual((out, code), run_argv(js))


# ------------------------------------------------------------------------------------------------ repository (G)

class RepositoryTests(GateCase):
    def test_missing_config_is_input_fail(self):  # G1
        git(self.root, "rm", "-q", ".strict-delivery/config.yml")
        out, code = run(self.root)
        self.assertTrue(out.startswith("FAIL claims.input:"))
        self.assertEqual((out, code),
                         ("FAIL claims.input: .strict-delivery/config.yml: missing; run /strict-delivery:init\n", 1))

    def test_G3_empty_claims_directory(self):
        os.makedirs(os.path.join(self.root, *CDIR.split("/")))
        self.assertEqual(run(self.root), (ALL_PASS, 0))

    def test_G4_non_yml_entry_is_input_fail(self):
        write(self.root, CDIR + "/x.md", "x\n")
        self.assertEqual(run(self.root), (
            "FAIL claims.input: %s/x.md: not a regular file named <document slug>.yml\n" % CDIR, 1))

    def test_G4_decision_file_is_a_schema_failure(self):
        write_record(self.root, CDIR + "/DEC-20261031-k3f9.yml",
                     {"schema": "decision/2", "id": "DEC-20261031-k3f9", "status": "open"})
        out, code = run(self.root)
        self.assertEqual(code, 1)
        self.assertIn("FAIL claims.schema.%s/DEC-20261031-k3f9.yml: " % CDIR, out)
        self.assertNotIn("PASS claims.schema", out)
        self.assertIn("PASS claims.store\nPASS claims.document\nPASS claims.stale\nPASS claims.base\n", out)

    def test_G5_symlinked_claims_directory(self):
        os.makedirs(os.path.join(self.root, ".strict-delivery", "real"))
        os.makedirs(os.path.join(self.root, ".strict-delivery", "state"))
        os.symlink(os.path.join(self.root, ".strict-delivery", "real"), os.path.join(self.root, *CDIR.split("/")))
        self.assertEqual(run(self.root), (
            "FAIL claims.input: %s: is a symlink; the claims directory must be a real directory\n" % CDIR, 1))

    def test_G6_repository_without_commits(self):
        fresh = os.path.join(self.tmp, "fresh")
        os.mkdir(fresh)
        git(fresh, "init", "-q", "-b", "main")
        write_record(fresh, ".strict-delivery/config.yml", minimal_config())
        self.assertEqual(run(fresh), ("FAIL claims.input: git merge-base failed (exit 128)\n", 1))

    def test_G7_config_errors(self):
        cfg = minimal_config()
        cfg["nope"] = 1
        write_record(self.root, ".strict-delivery/config.yml", cfg)
        self.assertEqual(run(self.root),
                         ("FAIL claims.input: .strict-delivery/config.yml: unknown key 'nope'\n", 1))
        cfg = minimal_config()
        cfg["base_branch"] = ""
        write_record(self.root, ".strict-delivery/config.yml", cfg)
        self.assertEqual(run(self.root), (
            "FAIL claims.input: .strict-delivery/config.yml: base_branch: must be a non-empty string\n", 1))

    def test_G8_base_is_head(self):
        self.seed()
        self.assertEqual(git(self.root, "rev-parse", "--abbrev-ref", "HEAD"), "main")
        self.assertEqual(run(self.root), (ALL_PASS, 0))


# ------------------------------------------------------------------------------------------------ categories

class SchemaTests(GateCase):
    def test_S1_one_line_per_file_errors_joined(self):
        row = {"schema": TAG, "document": "docs/a.md", "claims": [claim(CID, "XYZ", lines="0")], "extra": 1}
        del row["claims"][0]["direct"]
        row["claims"][0]["cites"][0]["lines"] = "5-1"
        self.seed()
        write_record(self.root, FILE, row)
        out, code = run(self.root)
        lines = [ln for ln in out.splitlines() if ln.startswith("FAIL claims.schema.")]
        self.assertEqual(len(lines), 1, out)
        self.assertTrue(lines[0].startswith("FAIL claims.schema.%s: " % FILE), lines)
        for part in ("extra: unknown key", "claims.0.direct: required key is missing",
                     "claims.0.cites.0.lines: must be <n> or <first>-<last>",
                     "claims.0.cites.0.blob: must be 7 to 40 lowercase hex digits"):
            self.assertIn(part, lines[0])
        self.assertIn("; ", lines[0])
        self.assertNotIn("PASS claims.schema", out)
        self.assertEqual(code, 1)

    def test_S1_each_class_fails(self):
        self.seed()
        cases = {
            "missing": lambda r: r["claims"][0].pop("by"),
            "type": lambda r: r.__setitem__("document", 1),
            "empty": lambda r: r.__setitem__("claims", []),
            "unknown": lambda r: r.__setitem__("x", "y"),
            "blob": lambda r: r["claims"][0]["cites"][0].__setitem__("blob", "A" * 40),
            "lines": lambda r: r["claims"][0]["cites"][0].__setitem__("lines", "01"),
            "document": lambda r: r.__setitem__("document", "docs/a.txt"),
        }
        for name, mutate in cases.items():
            with self.subTest(name):
                row = {"schema": TAG, "document": "docs/a.md", "claims": [claim(CID, self.blob("src/x.txt"))]}
                mutate(row)
                write_record(self.root, FILE, row)
                out, code = run(self.root)
                self.assertIn("FAIL claims.schema.%s: " % FILE, out)
                self.assertNotIn("PASS claims.schema", out)
                self.assertEqual(code, 1)

    def test_S1_lines_in_file_order(self):
        self.seed()
        self.seed(doc="docs/b.md", claims_=[claim(CID2, "0" * 40)])
        for rel in (FILE, CDIR + "/docs--b.yml"):
            write(self.root, rel, "schema: claim/9\n")
        out, code = run(self.root)
        up = ": schema: expected %s, got claim/9; run /strict-delivery:upgrade\n" % TAG
        self.assertTrue(out.startswith("FAIL claims.schema.%s%sFAIL claims.schema.%s/docs--b.yml%s"
                                       % (FILE, up, CDIR, up)), out)

    def test_S2_clean(self):
        self.seed()
        self.assertEqual(run(self.root), (ALL_PASS, 0))

    def test_S3_wrong_schema_tag(self):
        self.seed()
        up = "; run /strict-delivery:upgrade"
        for tag, hint in (("claim/2", up), ("decision/2", ""), ("claim/1" + "0" * 4300, up)):
            with self.subTest(tag=tag[:12]):
                write_record(self.root, FILE, {"schema": tag, "document": "docs/a.md",
                                               "claims": [claim(CID, self.blob("src/x.txt"))]})
                out, code = run(self.root)
                want = "FAIL claims.schema.%s: schema: expected %s, got %s%s\n" % (FILE, TAG, tag, hint)
                self.assertTrue(out.startswith(want), out[:200])
                self.assertEqual(code, 1)


class StoreTests(GateCase):
    def test_T1_file_name_differs_from_slug(self):
        rel = self.seed()
        os.rename(os.path.join(self.root, rel), os.path.join(self.root, CDIR, "x.yml"))
        out, code = run(self.root)
        self.assertIn("FAIL claims.store.name.%s/x.yml: file name x.yml differs from docs--a.yml, the slug of the "
                      "document docs/a.md\n" % CDIR, out)
        self.assertNotIn("PASS claims.store", out)
        self.assertEqual(code, 1)

    def test_T2_bad_id(self):
        self.seed(claims_=[claim("C-20261031-K3F9", "0" * 40)], commit=False)
        write_record(self.root, FILE, {"schema": TAG, "document": "docs/a.md",
                                       "claims": [claim("C-20261031-K3F9", self.blob("src/x.txt"))]})
        out, code = run(self.root)
        self.assertIn("FAIL claims.store.id.%s: C-20261031-K3F9: " % FILE, out)
        self.assertEqual(code, 1)

    def test_T3_duplicate_id_across_files(self):
        self.seed()
        self.seed(doc="docs/b.md")
        out, code = run(self.root)
        fb = CDIR + "/docs--b.yml"
        why = "claims.0.id: id %s appears 2 times: %s, %s" % (CID, FILE, fb)
        # F-R1-1 (ruling 1): a repeated id is not unique, so each line names the claim file.
        self.assertIn("FAIL claims.store.duplicate.%s: %s\nFAIL claims.store.duplicate.%s: %s\n"
                      % (FILE, why, fb, why), out)
        self.assertNotIn("duplicate." + CID, out)
        self.assertEqual(code, 1)

    def test_T3_duplicate_id_within_one_file(self):  # F-R1-1
        b = "0" * 40
        self.seed(claims_=[claim(CID, b), claim(CID, b)])
        out, code = run(self.root)
        why = "id %s appears 2 times: %s, %s" % (CID, FILE, FILE)
        self.assertIn("FAIL claims.store.duplicate.%s: claims.0.id: %s; claims.1.id: %s\n" % (FILE, why, why), out)
        self.assertEqual(code, 1)

    def test_F_R1_2_store_lines_sorted_by_suffix(self):
        rel = self.seed(claims_=[claim("bad", "0" * 40)])
        os.rename(os.path.join(self.root, rel), os.path.join(self.root, CDIR, "aaa.yml"))
        out, _ = run(self.root)
        store = [ln.split(": ", 1)[0] for ln in out.splitlines() if ln.startswith("FAIL claims.store.")]
        self.assertEqual(store, ["FAIL claims.store.id.%s/aaa.yml" % CDIR, "FAIL claims.store.name.%s/aaa.yml" % CDIR])

    def test_F_R1_1_colon_in_file_name_is_encoded(self):
        self.seed()
        write(self.root, CDIR + "/a: b%.yml", "schema: claim/9\n")
        out, _ = run(self.root)
        self.assertIn("FAIL claims.schema.%s/a%%3A b%%25.yml: schema: expected %s, got claim/9" % (CDIR, TAG), out)

    def test_T4_prefix_from_config(self):
        cfg = minimal_config()
        cfg["ids"] = {"claim": "CL"}
        write_record(self.root, ".strict-delivery/config.yml", cfg)
        self.seed(claims_=[claim("CL-20261031-k3f9", "0" * 40)], commit=False)
        write_record(self.root, FILE, {"schema": TAG, "document": "docs/a.md",
                                       "claims": [claim("CL-20261031-k3f9", self.blob("src/x.txt"))]})
        commit_all(self.root, "cl")
        self.assertEqual(run(self.root), (ALL_PASS, 0))
        write_record(self.root, FILE, {"schema": TAG, "document": "docs/a.md",
                                       "claims": [claim("CL-20261031-k3f9", self.blob("src/x.txt")),
                                                  claim(CID, self.blob("src/x.txt"))]})
        out, code = run(self.root)
        self.assertIn("FAIL claims.store.id.%s: %s: " % (FILE, CID), out)
        self.assertEqual(code, 1)

    def test_T5_clean(self):
        self.seed()
        self.assertIn("PASS claims.store\n", run(self.root)[0])


class DocumentTests(GateCase):
    def test_D1_untracked_document(self):
        self.seed(doc="docs/new.md", commit=False)
        git(self.root, "add", "src/x.txt", CDIR)
        out, code = run(self.root)
        self.assertIn("FAIL claims.document.%s/docs--new.yml: document docs/new.md is not a tracked file\n" % CDIR,
                      out)
        self.assertEqual(code, 1)

    def test_D2_D3_cited_path_untracked_joined(self):
        self.seed()
        write(self.root, "src/y.txt", "y\n")
        write(self.root, "docs/b.md", "b\n")
        write_record(self.root, CDIR + "/docs--b.yml", {"schema": TAG, "document": "docs/b.md",
                                                         "claims": [claim(CID2, self.blob("src/y.txt"),
                                                                          path="src/y.txt")]})
        out, code = run(self.root)
        self.assertIn("FAIL claims.document.%s/docs--b.yml: document docs/b.md is not a tracked file; claim %s: "
                      "cited path src/y.txt is not a tracked file\n" % (CDIR, CID2), out)
        self.assertEqual(code, 1)

    def test_D2_symlink_cite(self):
        self.seed(commit=False)
        os.symlink("x.txt", os.path.join(self.root, "src", "l.txt"))
        commit_all(self.root, "link")
        write_record(self.root, FILE, {"schema": TAG, "document": "docs/a.md",
                                       "claims": [claim(CID, git(self.root, "rev-parse", "HEAD:src/l.txt"),
                                                        path="src/l.txt")]})
        out, code = run(self.root)
        self.assertIn("FAIL claims.document.%s: claim %s: cited path src/l.txt is not a tracked file\n"
                      % (FILE, CID), out)
        self.assertEqual(code, 1)

    def test_D4_clean(self):
        self.seed()
        self.assertIn("PASS claims.document\n", run(self.root)[0])


class StaleTests(GateCase):
    def test_E1_unchanged_cite(self):
        self.seed()
        self.assertIn("PASS claims.stale\n", run(self.root)[0])

    def test_stale_claim_fails(self):  # E2
        self.seed()
        old = self.blob("src/x.txt")
        write(self.root, "src/x.txt", "changed\n")
        now = self.blob("src/x.txt")
        out, code = run(self.root)
        self.assertIn("FAIL claims.stale." + CID, out)
        self.assertEqual(code, 1)
        self.assertIn("FAIL claims.stale.%s: cites.0: src/x.txt has blob %s; the claim records %s\n"
                      % (CID, now, old), out)

    def test_cited_file_and_claim_changed_together_pass(self):  # E3; F-B2p-1, Q-B2plan-4 (a)
        self.seed()
        write(self.root, "src/x.txt", "changed\n")
        write_record(self.root, FILE, {"schema": TAG, "document": "docs/a.md",
                                       "claims": [claim(CID, self.blob("src/x.txt"))]})
        git(self.root, "add", "-A")
        out, code = run(self.root)
        self.assertIn("PASS claims.stale", out)
        self.assertEqual((out, code), (ALL_PASS, 0))

    def test_E4_cite_deleted(self):
        self.seed()
        git(self.root, "rm", "-q", "src/x.txt")
        out, code = run(self.root)
        self.assertIn("FAIL claims.stale.%s: cites.0: src/x.txt is absent or untracked\n" % CID, out)
        self.assertIn("FAIL claims.document.%s: claim %s: cited path src/x.txt is not a tracked file\n"
                      % (FILE, CID), out)
        self.assertEqual(code, 1)

    def test_E5_several_stale_cites_one_line(self):
        write(self.root, "src/y.txt", "y\n")
        self.seed(commit=False)
        c = claim(CID, self.blob("src/x.txt"))
        c["cites"].append({"path": "src/y.txt", "blob": self.blob("src/y.txt")})
        write_record(self.root, FILE, {"schema": TAG, "document": "docs/a.md", "claims": [c]})
        commit_all(self.root, "two cites")
        write(self.root, "src/x.txt", "x2\n")
        write(self.root, "src/y.txt", "y2\n")
        out, code = run(self.root)
        stale = [ln for ln in out.splitlines() if ln.startswith("FAIL claims.stale.")]
        self.assertEqual(len(stale), 1, out)
        self.assertIn("cites.0: src/x.txt has blob ", stale[0])
        self.assertIn("; cites.1: src/y.txt has blob ", stale[0])

    def test_E5_duplicate_id_stale_in_two_files_names_each_file(self):  # F-R1-1
        self.seed()
        self.seed(doc="docs/b.md")
        old = self.blob("src/x.txt")
        write(self.root, "src/x.txt", "x2\n")
        why = "claims.0.cites.0: src/x.txt has blob %s; the claim records %s" % (self.blob("src/x.txt"), old)
        out, code = run(self.root)
        stale = [ln for ln in out.splitlines() if ln.startswith("FAIL claims.stale.")]
        self.assertEqual(stale, ["FAIL claims.stale.%s: %s" % (FILE, why),
                                 "FAIL claims.stale.%s/docs--b.yml: %s" % (CDIR, why)])

    def test_F_R1_1_same_id_twice_in_one_file_keeps_indexes(self):
        b0, b1 = "0" * 40, "1" * 40
        self.seed(claims_=[claim(CID, b0), claim(CID, b1)])
        now = self.blob("src/x.txt")
        out, _ = run(self.root)
        self.assertIn("FAIL claims.stale.%s: claims.0.cites.0: src/x.txt has blob %s; the claim records %s; "
                      "claims.1.cites.0: src/x.txt has blob %s; the claim records %s\n" % (FILE, now, b0, now, b1), out)

    def test_F_R1_1_invalid_id_names_the_file(self):
        for cid in ("C x: y", "bad"):
            with self.subTest(cid=cid):
                self.seed(claims_=[claim(cid, "0" * 40)])
                out, _ = run(self.root)
                self.assertIn("FAIL claims.stale.%s: claims.0.cites.0: src/x.txt has blob " % FILE, out)
                self.assertNotIn("claims.stale." + cid, out)

    def test_F_R1_1_index_counts_every_item(self):  # a non-mapping item keeps its place in claims.<i>
        self.seed(claims_=["x", claim("bad", "0" * 40), claim([1], "0" * 40)])
        out, code = run(self.root)
        self.assertIn("FAIL claims.stale.%s: claims.1.cites.0: src/x.txt has blob " % FILE, out)
        self.assertFalse(out.startswith("FAIL claims.input"), out[:200])
        self.assertEqual(code, 1)

    def test_F_R1_1_valid_unique_id_names_the_id(self):  # invariant: the replaced code's id line stays
        self.seed()
        write(self.root, "src/x.txt", "x2\n")
        self.assertIn("FAIL claims.stale.%s: cites.0: src/x.txt has blob " % CID, run(self.root)[0])

    def test_E6_document_under_specs_is_not_exempt(self):
        doc = "docs/strict-delivery/specs/x.md"
        self.seed(doc=doc)
        write(self.root, "src/x.txt", "changed\n")
        out, code = run(self.root)
        self.assertIn("FAIL claims.stale.%s: cites.0: src/x.txt has blob " % CID, out)
        self.assertEqual(code, 1)

    def test_E7_base_does_not_change_staleness(self):
        self.seed()
        git(self.root, "checkout", "-q", "-b", "feat")
        write(self.root, "src/x.txt", "changed\n")
        a = [ln for ln in run(self.root)[0].splitlines() if "stale" in ln]
        b = [ln for ln in run(self.root, "--base", "feat")[0].splitlines() if "stale" in ln]
        self.assertEqual(a, b)
        self.assertTrue(a[0].startswith("FAIL claims.stale." + CID))


class BaseTests(GateCase):
    def branch(self):
        git(self.root, "checkout", "-q", "-b", "feat")

    def test_deleted_claim_file_fails(self):  # B1
        self.seed()
        self.branch()
        git(self.root, "rm", "-q", FILE)
        commit_all(self.root, "drop claim file")
        out, code = run(self.root)
        self.assertIn("FAIL claims.base.deleted.", out)
        self.assertEqual((out, code), (
            "PASS claims.schema\nPASS claims.store\nPASS claims.document\nPASS claims.stale\n"
            "FAIL claims.base.deleted.%s: %s exists on main and its document docs/a.md is kept; claim files are "
            "never deleted\n" % (FILE, FILE), 1))

    def test_B2_deleted_with_document(self):
        self.seed()
        self.branch()
        git(self.root, "rm", "-q", FILE, "docs/a.md")
        commit_all(self.root, "drop both")
        self.assertEqual(run(self.root), (ALL_PASS, 0))

    def test_B3_removed_id(self):
        write(self.root, "src/x.txt", "x\n")
        self.seed(claims_=[claim(CID, self.blob("src/x.txt")), claim(CID2, self.blob("src/x.txt"))])
        self.branch()
        write_record(self.root, FILE, {"schema": TAG, "document": "docs/a.md",
                                       "claims": [claim(CID, self.blob("src/x.txt"))]})
        out, code = run(self.root)
        self.assertIn("FAIL claims.base.removed.%s: %s was in %s on main and is in no claim file now; claim ids are "
                      "never removed\n" % (CID2, CID2, FILE), out)
        self.assertEqual(code, 1)

    def test_B4_collision(self):
        self.seed()
        self.branch()
        git(self.root, "checkout", "-q", "main")
        b = self.blob("src/x.txt")
        write_record(self.root, FILE, {"schema": TAG, "document": "docs/a.md",
                                       "claims": [claim(CID, b), claim(CID2, b, text="on main")]})
        commit_all(self.root, "main adds")
        git(self.root, "checkout", "-q", "feat")
        write_record(self.root, FILE, {"schema": TAG, "document": "docs/a.md",
                                       "claims": [claim(CID, b), claim(CID2, b, text="on feat")]})
        out, code = run(self.root)
        self.assertIn("FAIL claims.base.collision.%s: id %s already exists on main with other content; mint a new "
                      "id\n" % (CID2, CID2), out)
        self.assertEqual(code, 1)
        write_record(self.root, FILE, {"schema": TAG, "document": "docs/a.md",
                                       "claims": [claim(CID, b), claim(CID2, b, text="on main")]})
        self.assertEqual(run(self.root), (ALL_PASS, 0))

    def collide(self, *texts):
        """main adds CID2 ("on main") after feat branched; feat then holds CID plus one CID2 per text."""
        self.seed()
        self.branch()
        git(self.root, "checkout", "-q", "main")
        b = self.blob("src/x.txt")
        write_record(self.root, FILE, {"schema": TAG, "document": "docs/a.md",
                                       "claims": [claim(CID, b), claim(CID2, b, text="on main")]})
        commit_all(self.root, "main adds")
        git(self.root, "checkout", "-q", "feat")
        write_record(self.root, FILE, {"schema": TAG, "document": "docs/a.md",
                                       "claims": [claim(CID, b)] + [claim(CID2, b, text=t) for t in texts]})
        return run(self.root)

    WHY2 = "id %s already exists on main with other content; mint a new id" % CID2

    def test_F_R1_1_collision_of_a_repeated_id_names_files(self):  # all occurrences differ from the tip
        out, _ = self.collide("f1", "f2")
        self.assertIn("FAIL claims.base.collision.%s: claims.1.id: %s; claims.2.id: %s\n"
                      % (FILE, self.WHY2, self.WHY2), out)
        self.assertNotIn("collision." + CID2, out)

    def test_F_R2_1_occurrence_equal_to_tip_is_not_blamed(self):
        out, code = self.collide("on main", "f2")
        self.assertIn("FAIL claims.base.collision.%s: claims.2.id: %s\n" % (FILE, self.WHY2), out)
        self.assertNotIn("claims.1.id: " + self.WHY2, out)
        self.assertEqual(code, 1)

    def test_F_R2_1_all_occurrences_equal_to_tip(self):
        out, code = self.collide("on main", "on main")
        self.assertIn("PASS claims.base\n", out)
        self.assertIn("FAIL claims.store.duplicate.%s: " % FILE, out)  # the run still fails on the duplicate
        self.assertEqual(code, 1)

    def test_F_R2_1_unattributable_collision_fails_closed(self):
        # If the library reports a collision that no single occurrence reproduces, every occurrence is named.
        real = claims_lib.base_errors
        calls = []

        def fake(root, cfg, files, base):
            out = real(root, cfg, files, base)
            calls.append(len(files))
            if len(calls) == 1:
                out.append(("collision." + CID2, self.WHY2))
            return out
        with mock.patch.object(claims_lib, "base_errors", side_effect=fake):
            out, code = self.collide("on main", "on main")
        self.assertIn("FAIL claims.base.collision.%s: claims.1.id: %s; claims.2.id: %s\n"
                      % (FILE, self.WHY2, self.WHY2), out)
        self.assertEqual(code, 1)

    def test_F_R1_1_removed_invalid_id_names_the_base_file(self):
        write(self.root, "src/x.txt", "x\n")
        self.seed(claims_=[claim(CID, self.blob("src/x.txt")), claim("C x: y", self.blob("src/x.txt"))])
        self.branch()
        write_record(self.root, FILE, {"schema": TAG, "document": "docs/a.md",
                                       "claims": [claim(CID, self.blob("src/x.txt"))]})
        out, _ = run(self.root)
        self.assertIn("FAIL claims.base.removed.%s: C x: y was in %s on main and is in no claim file now; claim ids "
                      "are never removed\n" % (FILE, FILE), out)

    def test_F_R1_2_base_lines_sorted_by_suffix(self):
        cid3 = "C-20261031-p6q7"
        write(self.root, "src/x.txt", "x\n")
        b = self.blob("src/x.txt")
        self.seed(claims_=[claim(CID, b), claim(cid3, b)])
        self.branch()
        git(self.root, "checkout", "-q", "main")
        write_record(self.root, FILE, {"schema": TAG, "document": "docs/a.md",
                                       "claims": [claim(CID, b), claim(cid3, b), claim(CID2, b, text="on main")]})
        commit_all(self.root, "main adds")
        git(self.root, "checkout", "-q", "feat")
        write_record(self.root, FILE, {"schema": TAG, "document": "docs/a.md",
                                       "claims": [claim(CID, b), claim(CID2, b, text="on feat")]})
        out, _ = run(self.root)
        ids = [ln.split(": ", 1)[0] for ln in out.splitlines() if ln.startswith("FAIL claims.base.")]
        self.assertEqual(ids, ["FAIL claims.base.collision." + CID2, "FAIL claims.base.removed." + cid3])

    def test_B5_unparsable_row_at_merge_base(self):
        write(self.root, FILE, "schema: [\n")
        commit_all(self.root, "broken")
        self.branch()
        self.seed()
        out, code = run(self.root)
        self.assertTrue(out.startswith("FAIL claims.input: main:%s (at the merge base): " % FILE), out)
        self.assertEqual(out.count("\n"), 1)
        self.assertEqual(code, 1)

    def test_B6_base_without_claims_directory(self):
        self.branch()
        self.seed()
        self.assertEqual(run(self.root), (ALL_PASS, 0))

    def test_B7_lib_rows_under_the_gate(self):
        # 2a.2 B6 (id moved), B11 (non-yml at mb ignored), B12 (changed content), B14 (malformed row at mb).
        write(self.root, CDIR + "/README.md", "r\n")
        write_record(self.root, CDIR + "/docs--m.yml", {"schema": TAG, "document": "docs/m.md", "claims": 3})
        write(self.root, "docs/m.md", "m\n")
        self.seed()
        self.branch()
        git(self.root, "rm", "-q", CDIR + "/README.md")
        b = self.blob("src/x.txt")
        write_record(self.root, CDIR + "/docs--m.yml",
                     {"schema": TAG, "document": "docs/m.md", "claims": [claim(CID, b, text="changed")]})
        write_record(self.root, FILE, {"schema": TAG, "document": "docs/a.md", "claims": [claim(CID2, b)]})
        self.assertEqual(run(self.root), (ALL_PASS, 0))

    def test_B7_document_absent_at_merge_base(self):  # 2a.2 B3
        self.seed(doc="docs/n.md", commit=False)
        git(self.root, "add", "-A")
        git(self.root, "rm", "-q", "--cached", "docs/n.md")
        git(self.root, "commit", "-q", "-m", "claim without tracked doc")  # docs/n.md stays on disk, untracked
        self.branch()
        git(self.root, "rm", "-q", CDIR + "/docs--n.yml")
        out, _ = run(self.root)
        self.assertIn("FAIL claims.base.deleted.%s/docs--n.yml: " % CDIR, out)


# ------------------------------------------------------------------------------------------------ hooks, commands

class HookTests(GateCase):
    def alt_index(self, *paths):
        alt = os.path.join(self.root, ".git", "alt")
        git(self.root, "read-tree", "HEAD", env={"GIT_INDEX_FILE": alt})
        git(self.root, "add", *paths, env={"GIT_INDEX_FILE": alt})
        return alt

    def test_H1_alternate_index_is_read(self):
        self.seed(commit=False)
        git(self.root, "add", "src/x.txt", CDIR)
        git(self.root, "commit", "-q", "-m", "without doc")
        alt = self.alt_index("docs/a.md")
        with mock.patch.dict(os.environ, {"GIT_INDEX_FILE": alt}):
            self.assertEqual(run(self.root), (ALL_PASS, 0))
        out, code = run(self.root)
        self.assertIn("FAIL claims.document.%s: document docs/a.md is not a tracked file\n" % FILE, out)

    def test_H2_relative_index_from_other_cwd(self):
        self.seed(commit=False)
        git(self.root, "add", "src/x.txt", CDIR)
        git(self.root, "commit", "-q", "-m", "without doc")
        self.alt_index("docs/a.md")
        old = os.getcwd()
        os.chdir(self.tmp)
        self.addCleanup(os.chdir, old)
        with mock.patch.dict(os.environ, {"GIT_INDEX_FILE": ".git/alt"}):
            self.assertEqual(run(self.root), (ALL_PASS, 0))

    def test_H3_hook_git_dir_ignored(self):
        self.seed()
        with mock.patch.dict(os.environ, {"GIT_DIR": os.path.join(self.tmp, "bogus"),
                                          "GIT_WORK_TREE": self.tmp}):
            self.assertEqual(run(self.root), (ALL_PASS, 0))

    def test_H4_staged_cite_in_hook_index(self):
        self.seed()
        write(self.root, "src/x.txt", "changed\n")
        write_record(self.root, FILE, {"schema": TAG, "document": "docs/a.md",
                                       "claims": [claim(CID, self.blob("src/x.txt"))]})
        alt = self.alt_index("src/x.txt", FILE)
        with mock.patch.dict(os.environ, {"GIT_INDEX_FILE": alt}):
            self.assertEqual(run(self.root), (ALL_PASS, 0))


class CommandTests(GateCase):
    def test_commands_never_run(self):  # X1
        self.seed()
        for stale in (False, True):
            with self.subTest(stale=stale):
                write_record(self.root, FILE, {"schema": TAG, "document": "docs/a.md", "claims": [
                    claim(CID, "0" * 40 if stale else self.blob("src/x.txt"), direct="touch ran",
                          contradiction="touch ran2", text="$(touch ran3)")]})
                out, code = run(self.root)
                self.assertEqual(code, 1 if stale else 0, out)
                for name in ("ran", "ran2", "ran3"):
                    for where in (self.root, os.getcwd()):
                        self.assertFalse(os.path.exists(os.path.join(where, name)))

    def test_X2_produces_nothing(self):
        self.assertEqual(gate_claims.PRODUCES, ())


# ------------------------------------------------------------------------------------------------ PC1 skeleton (K)

class SkeletonTests(GateCase):
    def test_K1_single_number_lines_digits(self):
        for n in (4300, 4301):
            with self.subTest(n=n):
                self.seed(claims_=[claim(CID, "0" * 40)], commit=False)
                write_record(self.root, FILE, {"schema": TAG, "document": "docs/a.md",
                                               "claims": [claim(CID, self.blob("src/x.txt"),
                                                                lines="1" + "0" * (n - 1))]})
                self.assertIn("PASS claims.schema\n", run(self.root)[0])

    def test_K2_range_bound_digits(self):  # F1 fixed in 2a.2 r1: identical on 3.9 and 3.13
        self.seed()
        b = self.blob("src/x.txt")
        write_record(self.root, FILE, {"schema": TAG, "document": "docs/a.md",
                                       "claims": [claim(CID, b, lines="1-1" + "0" * 4300)]})
        self.assertEqual(run(self.root), (ALL_PASS, 0))
        write_record(self.root, FILE, {"schema": TAG, "document": "docs/a.md",
                                       "claims": [claim(CID, b, lines="1" + "0" * 4300 + "-1")]})
        out, code = run(self.root)
        self.assertIn("FAIL claims.schema.%s: claims.0.cites.0.lines: must be <n> or <first>-<last>: positive "
                      "decimals without a leading zero, first <= last\n" % FILE, out)
        self.assertEqual(code, 1)

    def test_K3_base_row_tag_digits(self):  # F2 fixed in 2a.2 r1: identical on 3.9 and 3.13
        for n in (4300, 4301):
            with self.subTest(n=n):
                tmp = os.path.join(self.tmp, "k3-%d" % n)
                os.mkdir(tmp)
                root = make_repo(tmp)
                write(root, "docs/a.md", "# A\n")
                write(root, "src/x.txt", "x\n")
                b = git(root, "hash-object", "--", "src/x.txt")
                write_record(root, FILE, {"schema": "claim/1" + "0" * (n - 1), "document": "docs/a.md",
                                          "claims": [claim(CID, b)]})
                commit_all(root, "big tag")
                git(root, "checkout", "-q", "-b", "feat")
                write_record(root, FILE, {"schema": TAG, "document": "docs/a.md", "claims": [claim(CID, b)]})
                self.assertEqual(run(root), (ALL_PASS, 0))

    def test_K4_plain_yaml_integer_too_large(self):
        self.seed()
        for n in (4300, 4301):
            with self.subTest(n=n):
                write(self.root, FILE, "schema: %s\ndocument: docs/a.md\nclaims:\n  - id: %s\n    text: t\n"
                      "    cites:\n      - path: src/x.txt\n        lines: 1%s\n        blob: %s\n"
                      "    direct: d\n    contradiction: c\n    by: b\n"
                      % (TAG, CID, "0" * (n - 1), self.blob("src/x.txt")))
                out, code = run(self.root)
                self.assertTrue(out.startswith("FAIL claims.input: "), out[:80])
                self.assertIn("integer too large (line 8)\n", out)
                self.assertEqual(code, 1)

    def test_K5_id_date_is_checked_without_int(self):
        self.seed(claims_=[claim("C-20261399-k3f9", "0" * 40)], commit=False)
        write_record(self.root, FILE, {"schema": TAG, "document": "docs/a.md",
                                       "claims": [claim("C-20261399-k3f9", self.blob("src/x.txt"))]})
        out, code = run(self.root)
        self.assertIn("FAIL claims.store.id.%s: C-20261399-k3f9: " % FILE, out)
        self.assertEqual(code, 1)

    def test_K7_no_case_mapping_on_the_gate_path(self):
        for rel in ("gates/gate_claims.py", "gates/lib/claims.py", "gates/lib/gitinfo.py", "gates/lib/schema.py",
                    "gates/lib/ids.py"):
            with self.subTest(rel), open(os.path.join(REPO, rel), encoding="utf-8") as fh:
                text = fh.read()
            for word in (".lower(", ".upper(", "casefold", "unicodedata"):
                self.assertNotIn(word, text, rel)

    def test_K6_K8_printable_follows_the_interpreter(self):
        # Until Task 1d2.1 (owner Q-RCp-2 (a)) pins isprintable to Unicode 13.0.0, each interpreter's own verdict.
        ver = unicodedata.unidata_version
        if ver not in ("13.0.0", "15.1.0"):
            self.skipTest("Unicode %s: no recorded verdict" % ver)
        doc = "docs/a\U0001F6DD.md"
        write(self.root, "src/x.txt", "x\n")
        rel = CDIR + "/docs--a\U0001F6DD.yml"
        write_record(self.root, rel, {"schema": TAG, "document": doc,
                                      "claims": [claim(CID, self.blob("src/x.txt"))]})
        commit_all(self.root, "emoji")
        out, code = run(self.root)
        self.assertEqual(code, 1)
        if ver == "13.0.0":
            self.assertIn("FAIL claims.schema.%s/docs--a\\U0001f6dd.yml: document: must be a normalised "
                          "repo-relative path with no '#'\n" % CDIR, out)
            self.assertIn("document docs/a\\U0001f6dd.md is not a tracked file\n", out)
        else:
            self.assertIn("PASS claims.schema\n", out)
            self.assertIn("document docs/a\U0001F6DD.md is not a tracked file\n", out)

    @unittest.skipIf(not hasattr(builtins, "BaseExceptionGroup"), "BaseExceptionGroup present: False (Python < 3.11)")
    def test_K9_exception_groups(self):
        eg = builtins.ExceptionGroup("g", [ValueError()])
        with mock.patch.object(gitinfo, "tracked_files", side_effect=eg):
            self.assertEqual(run(self.root),
                             ("FAIL claims.input: ExceptionGroup: g (1 sub-exception)\n", 1))
        beg = builtins.BaseExceptionGroup("g", [KeyboardInterrupt()])
        with mock.patch.object(gitinfo, "tracked_files", side_effect=beg):
            with self.assertRaises(builtins.BaseExceptionGroup):
                run(self.root)


BLOB_F = "f" * 40


class IndexCopyTests(GateCase):
    """Owner Q-2a2r4-1 (a); class: index copies per gate run (rows E8-E11). ``gitinfo.blob_ids`` and
    ``shutil.copy2`` (how the index is copied) are wrapped so the real calls still run, and counted."""

    def gate(self):
        import shutil
        with mock.patch.object(gitinfo, "blob_ids", wraps=gitinfo.blob_ids) as b, \
                mock.patch.object(shutil, "copy2", wraps=shutil.copy2) as c:
            out, code = run(self.root)
        return out, code, b, c.call_count

    def test_E8_zero_claim_files(self):
        out, code, b, copies = self.gate()
        self.assertEqual((out, code), (ALL_PASS, 0))
        self.assertEqual((b.call_count, b.call_args.args[1], copies), (1, [], 0))

    def test_E8_one_file_one_item(self):
        self.seed()
        out, code, b, copies = self.gate()
        self.assertEqual((out, code), (ALL_PASS, 0))
        self.assertEqual((b.call_count, b.call_args.args[1], copies), (1, ["src/x.txt"], 1))

    def test_E9_several_files_several_items(self):
        write(self.root, "src/x.txt", "x\n")
        write(self.root, "src/y.txt", "y\n")
        write(self.root, "src/z.txt", "z\n")
        write(self.root, "docs/b.md", "# B\n")
        bx, by = self.blob("src/x.txt"), self.blob("src/y.txt")
        two = claim(CID2, by, path="src/y.txt")
        two["cites"].append({"path": "src/x.txt", "blob": BLOB_F})
        self.seed(claims_=[claim(CID, bx), two], commit=False)
        write_record(self.root, CDIR + "/docs--b.yml", {"schema": TAG, "document": "docs/b.md", "claims": [
            claim("C-20261031-p6q7", self.blob("src/z.txt"), path="src/z.txt"), claim("C-20261031-r8s9", bx)]})
        commit_all(self.root, "two files")
        out, code, b, copies = self.gate()
        self.assertIn("FAIL claims.stale.%s: cites.1: src/x.txt has blob %s; the claim records %s\n"
                      % (CID2, bx, BLOB_F), out)
        self.assertEqual(code, 1)
        self.assertEqual((b.call_count, copies), (1, 1))
        self.assertEqual(b.call_args.args[1], ["src/x.txt", "src/y.txt", "src/z.txt"])  # each once

    def test_E10_untracked_and_absent_cites(self):
        write(self.root, "src/x.txt", "x\n")
        self.seed(claims_=[claim(CID, self.blob("src/x.txt"), path="src/none.txt"),
                           claim(CID2, self.blob("src/x.txt"), path="src/new.txt")], commit=False)
        write(self.root, "src/new.txt", "x\n")  # present, untracked
        git(self.root, "add", "--", "docs/a.md", "src/x.txt", FILE)
        git(self.root, "commit", "-q", "-m", "seed")
        out, code, b, copies = self.gate()
        self.assertIn("FAIL claims.stale.%s: cites.0: src/none.txt is absent or untracked\n" % CID, out)
        self.assertIn("FAIL claims.stale.%s: cites.0: src/new.txt is absent or untracked\n" % CID2, out)
        self.assertEqual((b.call_count, b.call_args.args[1], copies), (1, [], 0))

    def test_E10_map_missing_path_is_input_fail(self):  # fail closed through main (Decision, owner delegation)
        self.seed()
        with mock.patch.object(gitinfo, "blob_ids", return_value={}):
            out, code = run(self.root)
        self.assertEqual((out, code), ("FAIL claims.input: stale: no blob id for src/x.txt in the given map\n", 1))

    def test_E11_large_claim_file_gives_verdicts(self):  # 2a.2 review 5 F1 through main: 6000 paths of 204 chars
        os.makedirs(os.path.join(self.root, "c"))
        rels = []
        for i in range(6000):
            rel = "c/%04d" % i + "x" * 198
            with open(os.path.join(self.root, "c", rel[2:]), "w", encoding="utf-8") as fh:
                fh.write("%d\n" % i)
            rels.append(rel)
        git(self.root, "config", "gc.auto", "0")  # no detached auto-gc writing into .git during cleanup
        git(self.root, "config", "maintenance.auto", "false")
        write(self.root, "docs/a.md", "# A\n")
        commit_all(self.root, "many")
        staged = {}
        for line in git(self.root, "ls-files", "-s", "--", "c").split("\n"):
            head, _, p = line.partition("\t")
            staged[p] = head.split(" ")[1]  # the real index after commit_all's git add
        c = claim(CID, BLOB_F, path=rels[0])
        c["cites"] = [{"path": p, "blob": staged[p]} for p in rels]
        c["cites"][17]["blob"] = BLOB_F
        write_record(self.root, FILE, {"schema": TAG, "document": "docs/a.md", "claims": [c]})
        commit_all(self.root, "claims")
        out, code, b, copies = self.gate()
        self.assertEqual((out, code), (
            "PASS claims.schema\nPASS claims.store\nPASS claims.document\n"
            "FAIL claims.stale.%s: cites.17: %s has blob %s; the claim records %s\nPASS claims.base\n"
            % (CID, rels[17], staged[rels[17]], BLOB_F), 1))
        self.assertEqual((b.call_count, copies), (1, 1))


class TipCopiesTests(GateCase):
    """F-R3-1 (review 3); class: per-occurrence collision attribution by the tip's copies of the id (rows N13-N16).
    main adds CID2 after feat branched, once per ``tip`` text (``tip2``: copies in a second claim file)."""

    WHY2 = "id %s already exists on main with other content; mint a new id" % CID2

    def fresh(self, name):
        sub = os.path.join(self.tmp, name)
        os.mkdir(sub)
        self.root = make_repo(sub)

    def collide(self, tip, feat, tip2=()):
        self.seed()
        git(self.root, "branch", "feat")
        b = self.blob("src/x.txt")
        write_record(self.root, FILE, {"schema": TAG, "document": "docs/a.md",
                                       "claims": [claim(CID, b)] + [claim(CID2, b, text=t) for t in tip]})
        if tip2:
            write(self.root, "docs/b.md", "# B\n")
            write_record(self.root, CDIR + "/docs--b.yml", {"schema": TAG, "document": "docs/b.md",
                                                            "claims": [claim(CID2, b, text=t) for t in tip2]})
        commit_all(self.root, "main adds")
        git(self.root, "checkout", "-q", "feat")
        write_record(self.root, FILE, {"schema": TAG, "document": "docs/a.md",
                                       "claims": [claim(CID, b)] + [claim(CID2, b, text=t) for t in feat]})
        out, _ = run(self.root)
        return [ln for ln in out.splitlines() if ln.startswith(("FAIL claims.base", "PASS claims.base"))]

    def test_N13_equal_tip_copies(self):
        for name, feat, want in (("same", ["m"], ["PASS claims.base"]),
                                 ("other", ["f"], ["FAIL claims.base.collision.%s: %s" % (CID2, self.WHY2)])):
            with self.subTest(name):
                self.fresh("n13-" + name)
                self.assertEqual(self.collide(["m", "m"], feat), want)

    def test_N14_different_tip_copies(self):  # equal to one copy, differing from another: collides
        for feat in ("m1", "m2", "f"):
            with self.subTest(feat):
                self.fresh("n14-" + feat)
                self.assertEqual(self.collide(["m1", "m2"], [feat]),
                                 ["FAIL claims.base.collision.%s: %s" % (CID2, self.WHY2)])

    def test_N15_repeated_occurrences(self):
        self.fresh("n15-equal")
        self.assertEqual(self.collide(["m", "m"], ["m", "f"]),
                         ["FAIL claims.base.collision.%s: claims.2.id: %s" % (FILE, self.WHY2)])
        self.fresh("n15-differ")
        self.assertEqual(self.collide(["m1", "m2"], ["m1", "m2"]),
                         ["FAIL claims.base.collision.%s: claims.1.id: %s; claims.2.id: %s"
                          % (FILE, self.WHY2, self.WHY2)])

    def test_N16_tip_copies_in_two_files(self):
        self.fresh("n16-same")
        self.assertEqual(self.collide(["m"], ["m"], tip2=["m"]), ["PASS claims.base"])
        self.fresh("n16-other")
        self.assertEqual(self.collide(["m"], ["m"], tip2=["n"]),
                         ["FAIL claims.base.collision.%s: %s" % (CID2, self.WHY2)])


if __name__ == "__main__":
    unittest.main()
