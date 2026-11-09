"""Tests for gates.gate_cites through its production entry point, main(), on real git fixture repositories."""
import contextlib
import io
import json
import os
import unittest
from unittest import mock

from gates import gate_cites
from tests.helpers import GitIsolatedTestCase, commit_all, git, make_repo, minimal_config, write_record

DEC = ".strict-delivery/state/decisions"
DEC_ID = "DEC-20261031-k3f9"
DEC_ID2 = "DEC-20261031-m4n5"
PB = ".strict-delivery/playbooks/p.md"
CATS = ["doc", "line", "anchor", "landed"]


def put(root, rel, text, binary=False):
    path = os.path.join(root, *rel.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if binary:
        with open(path, "wb") as fh:
            fh.write(text)
    else:
        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
    return path


def dec(id_=DEC_ID, status="answered", **more):
    r = {"schema": "decision/1", "id": id_, "status": status}
    r.update(more)
    return r


class CitesCase(GitIsolatedTestCase):
    def setUp(self):
        super().setUp()
        self.root = make_repo(self.work)

    def run_gate(self, *args):
        out = io.StringIO()
        err = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = gate_cites.main(list(args))
        return out.getvalue(), code

    def run_root(self, *args):
        return self.run_gate("--root", self.root, *args)

    def add(self, rel, text):
        put(self.root, rel, text)
        git(self.root, "add", "--", rel)

    def lines(self, out):
        return out.splitlines()


class TestDocsAndCategories(CitesCase):
    def test_empty_repo_passes_every_category(self):  # D1
        out, code = self.run_root()
        self.assertEqual(out, "".join("PASS cites.%s\n" % c for c in CATS))
        self.assertEqual(code, 0)

    def test_produces_empty(self):  # A8
        self.assertEqual(gate_cites.PRODUCES, ())

    def test_broken_line_cite_fails(self):  # L2
        self.add("gates/x.py", "a\nb\nc\n")
        self.add("docs/a.md", "ok\n`gates/x.py:9`\n")
        out, code = self.run_root()
        self.assertIn("FAIL cites.line.docs/a.md:2: `gates/x.py:9`: gates/x.py: line 9 is past the end (3 lines)\n", out)
        self.assertIn("PASS cites.anchor\n", out)
        self.assertNotIn("PASS cites.line", out)
        self.assertEqual(code, 1)

    def test_broken_anchor_fails(self):  # L4
        self.add("docs/b.md", "# b\n")
        self.add("docs/a.md", "[s](b.md#nope)\n")
        out, code = self.run_root()
        self.assertIn("FAIL cites.anchor.docs/a.md:1: b.md#nope: docs/b.md: no heading with anchor #nope\n", out)
        self.assertEqual(code, 1)

    def test_backtick_anchor_cite_is_anchor_category(self):  # L1
        self.add("docs/b.md", "# b\n")
        self.add("docs/a.md", "see `docs/b.md#zz`\n")
        out, code = self.run_root()
        self.assertIn("FAIL cites.anchor.docs/a.md:1: `docs/b.md#zz`: docs/b.md: no heading with anchor #zz\n", out)
        self.assertIn("PASS cites.line\n", out)

    def test_pass_when_all_resolve(self):  # L6
        self.add("docs/b.md", "# Hello There\n")
        self.add("gates/x.py", "1\n2\n3\n")
        self.add("docs/a.md", "`gates/x.py:2-3` and [s](b.md#hello-there) and [t](#top)\n\n# Top\n")
        out, code = self.run_root()
        self.assertEqual(out, "".join("PASS cites.%s\n" % c for c in CATS))
        self.assertEqual(code, 0)

    def test_line_reasons_pass_through(self):  # L3
        self.add("gates/x.py", "1\n2\n3\n")
        self.add("u.txt", "x\n")
        put(self.root, "untracked.py", "x\n")
        self.add("docs/a.md", "`gates/x.py:02` `gates/x.py:3-2` `untracked.py:1` `../x.py:1` `gates/x.py:1-9`\n")
        out, code = self.run_root()
        for reason in ("gates/x.py: line numbers start at 1 and have no leading zero",
                       "gates/x.py: range end 2 is before start 3",
                       "untracked.py: not a tracked file",
                       "../x.py: outside the repository",
                       "gates/x.py: line 9 is past the end (3 lines)"):
            self.assertIn(reason + "\n", out)
        self.assertEqual(len([ln for ln in self.lines(out) if ln.startswith("FAIL cites.line.")]), 5)

    def test_anchor_reasons(self):  # L5
        self.add("docs/b.txt", "x\n")
        self.add("docs/b.md", "# b\n")
        self.add("docs/a.md", "[a](b.txt#x) [b](b.md#) [c](/x.md#a) [d](../../up.md#b)\n")
        out, code = self.run_root()
        self.assertIn("docs/b.txt: anchor on a non-markdown file\n", out)
        self.assertIn("docs/b.md: empty anchor\n", out)
        self.assertIn("/x.md: outside the repository\n", out)
        self.assertIn("../up.md: outside the repository\n", out)

    def test_several_cites_in_column_order_no_dedupe(self):  # L7
        self.add("docs/a.md", "`n/a.py:1` `n/b.py:1` `n/a.py:1`\n")
        out, code = self.run_root()
        got = [ln for ln in self.lines(out) if ln.startswith("FAIL cites.line.")]
        self.assertEqual(got, [
            "FAIL cites.line.docs/a.md:1: `n/a.py:1`: n/a.py: not a tracked file",
            "FAIL cites.line.docs/a.md:1: `n/b.py:1`: n/b.py: not a tracked file",
            "FAIL cites.line.docs/a.md:1: `n/a.py:1`: n/a.py: not a tracked file"])

    def test_placeholders_and_examples_are_not_cites(self):  # L8
        self.add("docs/a.md", "`path#anchor` ``n/a.py:1`` `n/a.py:1 x`\n```\n`n/a.py:1`\n```\n")
        out, code = self.run_root()
        self.assertEqual(code, 0)

    def test_ordering_doc_then_line_and_category_order(self):  # L9
        self.add("docs/b.md", "`n/z.py:1`\n")
        self.add("a.md", "`n/z.py:1`\n")
        self.add("docs/a.md", "x\n`n/z.py:1`\n" + "x\n" * 7 + "`n/z.py:1`\n")
        out, code = self.run_root()
        ids = [ln.split(": ")[0] for ln in self.lines(out) if ln.startswith("FAIL")]
        self.assertEqual(ids, ["FAIL cites.line.a.md:1", "FAIL cites.line.docs/a.md:2",
                               "FAIL cites.line.docs/a.md:10", "FAIL cites.line.docs/b.md:1"])
        order = [ln.split(" ")[1].split(".")[1].rstrip(":") for ln in self.lines(out)]
        self.assertEqual(order, ["doc", "line", "line", "line", "line", "anchor", "landed"])
        # after the failing line category, the rest pass
        self.assertEqual(self.lines(out)[0], "PASS cites.doc")

    def test_untracked_doc_ignored(self):  # D2
        put(self.root, "u.md", "`n/z.py:1`\n")
        out, code = self.run_root()
        self.assertIn("PASS cites.line\n", out)
        self.assertIn("PASS cites.anchor\n", out)
        self.assertEqual(code, 0)

    def test_uppercase_and_other_extensions_not_scanned(self):  # D2
        self.add("README.MD", "`n/z.py:1`\n")
        self.add("x.markdown", "`n/z.py:1`\n")
        out, code = self.run_root()
        self.assertEqual(code, 0)

    def test_force_tracked_ignored_and_state_docs_are_scanned(self):  # D2
        put(self.root, ".gitignore", "g.md\n")
        put(self.root, "g.md", "`n/z.py:1`\n")
        git(self.root, "add", "-f", "g.md")
        self.add(".strict-delivery/state/ledger.md", "`n/y.py:1`\n")
        out, code = self.run_root()
        self.assertIn("FAIL cites.line.g.md:1:", out)
        self.assertIn("FAIL cites.line..strict-delivery/state/ledger.md:1:", out)

    def test_tracked_doc_deleted_in_worktree(self):  # D4
        self.add("docs/a.md", "`n/z.py:1`\n")
        os.remove(os.path.join(self.root, "docs/a.md"))
        out, code = self.run_root()
        self.assertIn("FAIL cites.doc.docs/a.md: tracked but missing from the working tree\n", out)
        self.assertIn("PASS cites.line\n", out)  # L10: its cites are not scanned
        self.assertIn("PASS cites.anchor\n", out)
        self.assertIn("PASS cites.landed\n", out)
        self.assertEqual(code, 1)

    def test_doc_not_utf8(self):  # D7
        put(self.root, "docs/a.md", b"`n/z.py:1` \xff\n", binary=True)
        git(self.root, "add", "docs/a.md")
        out, code = self.run_root()
        self.assertIn("FAIL cites.doc.docs/a.md: not UTF-8\n", out)
        self.assertIn("PASS cites.line\n", out)
        self.assertEqual(code, 1)

    def test_doc_bom_crlf_empty_no_final_newline(self):  # D7
        put(self.root, "bom.md", "﻿`n/z.py:1`\n")
        put(self.root, "crlf.md", "x\r\n`n/z.py:1`\r\n")
        put(self.root, "empty.md", "")
        put(self.root, "nonl.md", "`n/z.py:1`")
        git(self.root, "add", "-A")
        out, code = self.run_root()
        for doc, n in (("bom.md", 1), ("crlf.md", 2), ("nonl.md", 1)):
            self.assertIn("FAIL cites.line.%s:%d:" % (doc, n), out)
        self.assertNotIn("empty.md", out)

    def test_doc_path_text_escaped_once(self):  # D8
        self.add("docs/a b:cé.md", "`n/z.py:1`\n")
        out, code = self.run_root()
        self.assertIn("FAIL cites.line.docs/a b:cé.md:1: ", out)
        self.add("docs/back\\slash.md", "`n/z.py:1`\n")
        out, code = self.run_root()
        self.assertIn("FAIL cites.line.docs/back\\\\slash.md:1: ", out)
        self.assertNotIn("\\\\\\\\", out)

    def test_doc_symlink_in_worktree_not_followed(self):  # D5
        self.add("docs/a.md", "x\n")
        commit_all(self.root, "c")
        os.remove(os.path.join(self.root, "docs/a.md"))
        put(self.root, "real.txt", "`n/z.py:1`\n")
        os.symlink("../real.txt", os.path.join(self.root, "docs/a.md"))
        out, code = self.run_root()
        self.assertIn("FAIL cites.doc.docs/a.md: tracked but missing from the working tree\n", out)
        self.assertEqual(code, 1)

    def test_doc_directory_in_worktree(self):  # D5
        self.add("docs/a.md", "x\n")
        commit_all(self.root, "c")
        os.remove(os.path.join(self.root, "docs/a.md"))
        os.mkdir(os.path.join(self.root, "docs/a.md"))
        out, code = self.run_root()
        self.assertIn("FAIL cites.doc.docs/a.md: tracked but missing from the working tree\n", out)

    def test_doc_under_symlinked_parent(self):  # D5
        self.add("docs/a.md", "x\n")
        commit_all(self.root, "c")
        os.rename(os.path.join(self.root, "docs"), os.path.join(self.root, "realdocs"))
        os.symlink("realdocs", os.path.join(self.root, "docs"))
        out, code = self.run_root()
        self.assertIn("FAIL cites.doc.docs/a.md: tracked but missing from the working tree\n", out)

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root reads mode 000 files")
    def test_unreadable_doc_fails_whole_run(self):  # D6, Q-C22-1 (a)
        path = put(self.root, "docs/a.md", "x\n")
        git(self.root, "add", "docs/a.md")
        os.chmod(path, 0)
        self.addCleanup(os.chmod, path, 0o644)
        out, code = self.run_root()
        self.assertTrue(out.startswith("FAIL cites.input: docs/a.md: cannot read ("), out)
        self.assertEqual(len(self.lines(out)), 1)
        self.assertEqual(code, 1)

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root reads mode 000 files")
    def test_unreadable_target_fails_whole_run(self):  # T7, Q-C22-1 (a)
        path = put(self.root, "gates/x.py", "x\n")
        git(self.root, "add", "gates/x.py")
        self.add("docs/a.md", "`gates/x.py:1`\n")
        os.chmod(path, 0)
        self.addCleanup(os.chmod, path, 0o644)
        out, code = self.run_root()
        self.assertTrue(out.startswith("FAIL cites.input: gates/x.py: cannot read ("), out)
        self.assertEqual(len(self.lines(out)), 1)


class TestTreeRead(CitesCase):
    def test_doc_and_target_added_together_pass(self):  # T1
        self.add("gates/x.py", "1\n2\n")
        self.add("docs/a.md", "`gates/x.py:2`\n")
        out, code = self.run_root()
        self.assertIn("PASS cites.line\n", out)
        self.assertEqual(code, 0)

    def test_target_deleted_in_worktree_fails(self):  # T2
        self.add("gates/x.py", "1\n")
        self.add("docs/a.md", "`gates/x.py:1`\n")
        commit_all(self.root, "c")
        os.remove(os.path.join(self.root, "gates/x.py"))
        out, code = self.run_root()
        self.assertIn("gates/x.py: tracked but missing from the working tree", out)
        self.assertEqual(code, 1)

    def test_worktree_differs_from_index_reads_worktree(self):  # T3
        self.add("gates/x.py", "1\n2\n3\n")
        self.add("docs/a.md", "`gates/x.py:9`\n")
        put(self.root, "gates/x.py", "1\n2\n3\n4\n5\n6\n7\n8\n9\n")
        out, code = self.run_root()
        self.assertEqual(code, 0, out)

    def test_cite_to_untracked_and_submodule_like_target(self):  # T4
        put(self.root, "gates/u.py", "1\n")
        self.add("docs/a.md", "`gates/u.py:1`\n")
        out, code = self.run_root()
        self.assertIn("gates/u.py: not a tracked file\n", out)
        git(self.root, "update-index", "--add", "--cacheinfo", "160000,%s,sub.d" % ("1" * 40))
        put(self.root, "docs/a.md", "`sub.d:1`\n")
        out, code = self.run_root()
        self.assertIn("sub.d: not a tracked file\n", out)

    def test_target_symlink_in_worktree_not_followed(self):  # T5
        self.add("gates/x.py", "1\n")
        self.add("docs/a.md", "`gates/x.py:1`\n")
        commit_all(self.root, "c")
        os.remove(os.path.join(self.root, "gates/x.py"))
        put(self.root, "other.py", "1\n")
        os.symlink("../other.py", os.path.join(self.root, "gates/x.py"))
        out, code = self.run_root()
        self.assertIn("gates/x.py: tracked but missing from the working tree", out)

    def test_target_directory_and_symlinked_parent(self):  # T5
        self.add("gates/x.py", "1\n")
        self.add("docs/a.md", "`gates/x.py:1`\n")
        commit_all(self.root, "c")
        os.rename(os.path.join(self.root, "gates"), os.path.join(self.root, "g2"))
        os.symlink("g2", os.path.join(self.root, "gates"))
        out, code = self.run_root()
        self.assertIn("gates/x.py: tracked but missing from the working tree", out)
        os.remove(os.path.join(self.root, "gates"))
        os.makedirs(os.path.join(self.root, "gates/x.py"))
        out, code = self.run_root()
        self.assertIn("gates/x.py: tracked but missing from the working tree", out)

    def test_tracked_symlink_doc_not_scanned(self):  # D3
        put(self.root, "notes.txt", "`gates/x.py:9`\n")
        os.symlink("../notes.txt", os.path.join(self.root, "l.md"))
        os.makedirs(os.path.join(self.root, "docs"))
        os.symlink("../notes.txt", os.path.join(self.root, "docs/l.md"))
        git(self.root, "add", "-A")
        out, code = self.run_root()
        self.assertIn("PASS cites.line\n", out)
        self.assertNotIn("docs/l.md", out)
        self.assertEqual(code, 0)

    def test_untracked_symlink_doc_ignored(self):  # D3
        put(self.root, "notes.txt", "`gates/x.py:9`\n")
        os.symlink("notes.txt", os.path.join(self.root, "u.md"))
        out, code = self.run_root()
        self.assertEqual(code, 0)

    def test_submodule_entry_named_md_not_a_doc(self):  # D3
        git(self.root, "update-index", "--add", "--cacheinfo", "160000,%s,s.md" % ("1" * 40))
        out, code = self.run_root()
        self.assertEqual(code, 0, out)

    def test_cite_to_tracked_symlink_fails(self):  # T4
        put(self.root, "notes.txt", "# x\n")
        os.makedirs(os.path.join(self.root, "docs"))
        os.symlink("../notes.txt", os.path.join(self.root, "docs/l.md"))
        git(self.root, "add", "-A")
        self.add("docs/a.md", "`docs/l.md#x`\n")
        out, code = self.run_root()
        self.assertIn("docs/l.md: not a tracked file", out)
        self.assertEqual(code, 1)

    def test_target_not_utf8_bom_crlf(self):  # T6
        put(self.root, "docs/bad.md", b"# t\n\xff\n", binary=True)
        put(self.root, "docs/bom.md", "﻿# Title\n")
        put(self.root, "docs/crlf.md", "# Title\r\n")
        git(self.root, "add", "-A")
        self.add("docs/a.md", "[a](bad.md#t) [b](bom.md#title) [c](crlf.md#title)\n")
        out, code = self.run_root()
        self.assertIn("docs/bad.md: not UTF-8\n", out)
        self.assertIn("docs/bom.md: no heading with anchor #title\n", out)
        self.assertNotIn("crlf.md: no heading", out)

    def test_unmerged_path_is_tracked(self):  # T8
        base = commit_all(self.root, "base")
        git(self.root, "checkout", "-q", "-b", "side")
        put(self.root, "gates/x.py", "1\n")
        commit_all(self.root, "side")
        git(self.root, "checkout", "-q", "main")
        put(self.root, "gates/x.py", "1\n2\n")
        commit_all(self.root, "main")
        git(self.root, "merge", "side", check=False)
        self.assertIn("gates/x.py", git(self.root, "diff", "--name-only", "--diff-filter=U"))
        put(self.root, "gates/x.py", "1\n2\n")
        put(self.root, "docs/a.md", "`gates/x.py:2`\n")
        git(self.root, "add", "docs/a.md")
        out, code = self.run_root()
        self.assertNotIn("not a tracked file", out)
        self.assertEqual(code, 0, out)

    def test_case_differs(self):  # T9
        self.add("docs/a.md", "x\n")
        self.add("docs/b.md", "`Docs/A.md:1`\n")
        out, code = self.run_root()
        self.assertIn("Docs/A.md: not a tracked file\n", out)


class TestRecords(CitesCase):
    def setUp(self):
        super().setUp()
        self.add(PB, "# Present\n")

    def record(self, row, id_=DEC_ID):
        write_record(self.root, "%s/%s.yml" % (DEC, id_), row)

    def test_none_and_empty_directory(self):  # R1
        out, code = self.run_root()
        self.assertIn("PASS cites.landed\n", out)
        os.makedirs(os.path.join(self.root, DEC))
        out, code = self.run_root()
        self.assertEqual(code, 0)

    def test_without_anchor_passes(self):  # R2
        self.record(dec())
        self.record(dec(DEC_ID2, landed_in=[]), DEC_ID2)
        self.record(dec("DEC-20261031-p6q7", landed_in=["CLAUDE.md"]), "DEC-20261031-p6q7")
        out, code = self.run_root()
        self.assertIn("PASS cites.landed\n", out)
        self.assertEqual(code, 0)

    def test_landed_in_anchor_checked(self):  # R3
        self.record(dec(landed_in=[PB + "#missing"]))
        out, code = self.run_root()
        self.assertIn("FAIL cites.landed.%s: %s#missing: %s: no heading with anchor #missing\n" % (DEC_ID, PB, PB), out)
        self.assertNotIn("PASS cites.landed", out)
        self.assertEqual(code, 1)

    def test_anchor_present_passes(self):  # R4
        self.record(dec(landed_in=[PB + "#present"]))
        out, code = self.run_root()
        self.assertIn("PASS cites.landed\n", out)
        self.assertEqual(code, 0)

    def test_entry_parsing(self):  # R5
        self.add("docs/p.md", "# A\n")
        self.add("p q.md", "# a\n")
        self.add("p%20q.md", "# a\n")
        self.add("p.md", "# a\n")
        self.record(dec(landed_in=["docs/p.md#a", "p q.md#a", "p%20q.md#a", "p.md#a#b"]))
        out, code = self.run_root()
        failed = [ln for ln in self.lines(out) if ln.startswith("FAIL cites.landed.")]
        self.assertEqual(failed, ["FAIL cites.landed.%s: p.md#a#b: p.md: no heading with anchor #a#b" % DEC_ID])

    def test_target_problems(self):  # R6
        put(self.root, "u.md", "# a\n")
        self.add("x.txt", "x\n")
        self.record(dec(landed_in=["u.md#a", "../o.md#a", "x.txt#a", "nope.md#a"]))
        out, code = self.run_root()
        for reason in ("u.md: not a tracked file", "../o.md: outside the repository",
                       "x.txt: anchor on a non-markdown file", "nope.md: not a tracked file"):
            self.assertIn(": " + reason + "\n", out)
        os.remove(os.path.join(self.root, "x.txt"))
        out, code = self.run_root()
        self.assertIn("x.txt: tracked but missing from the working tree\n", out)

    def test_allow_list_not_this_gates_business(self):  # R7
        self.add("README.md", "# a\n")
        self.record(dec(landed_in=["README.md#a", "README.md#b"]))
        out, code = self.run_root()
        self.assertEqual([ln for ln in self.lines(out) if ln.startswith("FAIL")],
                         ["FAIL cites.landed.%s: README.md#b: README.md: no heading with anchor #b" % DEC_ID])

    def test_every_status_is_checked(self):  # R8
        for i, st in enumerate(("open", "withdrawn", "answered", "superseded")):
            id_ = "DEC-20261031-a%03d" % i
            self.record(dec(id_, st, landed_in=[PB + "#bad"]), id_)
        out, code = self.run_root()
        self.assertEqual(len([ln for ln in self.lines(out) if ln.startswith("FAIL cites.landed.")]), 4)

    def test_malformed_landed_in(self):  # R9
        self.record(dec(landed_in=PB + "#present"))
        self.record(dec(DEC_ID2, landed_in=[1, {"a": "b"}, "p.md#", "./p.md#a"]), DEC_ID2)
        out, code = self.run_root()
        self.assertIn("FAIL cites.landed.%s: landed_in: must be a list of cites\n" % DEC_ID, out)
        self.assertIn("FAIL cites.landed.%s: 1: is not a string\n" % DEC_ID2, out)
        self.assertIn("FAIL cites.landed.%s: {a: b}: is not a string\n" % DEC_ID2, out)
        self.assertIn("FAIL cites.landed.%s: p.md#: p.md: not a tracked file\n" % DEC_ID2, out)
        self.assertIn("FAIL cites.landed.%s: ./p.md#a: ./p.md: not a tracked file\n" % DEC_ID2, out)

    def test_record_id_in_line_id(self):  # R10
        row = dec(landed_in=[PB + "#bad"])
        del row["id"]
        self.record(row, "DEC-20261031-zzzz")
        out, code = self.run_root()
        self.assertIn("FAIL cites.landed.%s/DEC-20261031-zzzz.yml: " % DEC, out)
        row["id"] = 5
        self.record(row, "DEC-20261031-zzzz")
        out, code = self.run_root()
        self.assertIn("FAIL cites.landed.%s/DEC-20261031-zzzz.yml: " % DEC, out)

    def test_duplicate_ids_one_line_each(self):  # R10
        self.record(dec(landed_in=[PB + "#bad1"]), DEC_ID)
        self.record(dec(landed_in=[PB + "#bad2"]), DEC_ID2)
        write_record(self.root, "%s/%s.yml" % (DEC, DEC_ID2), dec(DEC_ID, landed_in=[PB + "#bad2"]))
        out, code = self.run_root()
        got = [ln for ln in self.lines(out) if ln.startswith("FAIL cites.landed.%s:" % DEC_ID)]
        self.assertEqual(len(got), 2)

    def test_record_does_not_load(self):  # R11
        put(self.root, DEC + "/%s.yml" % DEC_ID, "a: [\n")
        out, code = self.run_root()
        self.assertTrue(out.startswith("FAIL cites.input: "), out)
        self.assertEqual(len(self.lines(out)), 1)
        self.assertEqual(code, 1)

    def test_stray_file_and_list_toplevel(self):  # R11
        put(self.root, DEC + "/foo.txt", "x\n")
        out, code = self.run_root()
        self.assertTrue(out.startswith("FAIL cites.input: ") and len(self.lines(out)) == 1, out)
        os.remove(os.path.join(self.root, DEC, "foo.txt"))
        put(self.root, DEC + "/%s.yml" % DEC_ID, "- a\n")
        out, code = self.run_root()
        self.assertTrue(out.startswith("FAIL cites.input: ") and len(self.lines(out)) == 1, out)

    def test_decisions_directory_symlink(self):  # R11
        os.makedirs(os.path.join(self.root, ".strict-delivery/state"), exist_ok=True)
        os.makedirs(os.path.join(self.root, "elsewhere"))
        os.symlink("../../elsewhere", os.path.join(self.root, DEC))
        out, code = self.run_root()
        self.assertTrue(out.startswith("FAIL cites.input: ") and len(self.lines(out)) == 1, out)

    def test_untracked_record_is_checked(self):  # R12
        self.record(dec(landed_in=[PB + "#bad"]))
        self.assertEqual(git(self.root, "status", "--porcelain", "--untracked-files=all").count(DEC_ID), 1)
        out, code = self.run_root()
        self.assertIn("FAIL cites.landed.%s:" % DEC_ID, out)

    def test_record_ordering(self):  # R13
        self.record(dec(DEC_ID2, landed_in=[PB + "#b2", PB + "#a2"]), DEC_ID2)
        self.record(dec(landed_in=[PB + "#z1", PB + "#y1"]), DEC_ID)
        out, code = self.run_root()
        got = [ln.split(": ")[1] for ln in self.lines(out) if ln.startswith("FAIL")]
        self.assertEqual(got, [PB + "#z1", PB + "#y1", PB + "#b2", PB + "#a2"])


class TestArgv(CitesCase):
    def test_missing_config_names_init(self):  # A3
        git(self.root, "rm", "-q", "--cached", ".strict-delivery/config.yml")
        os.remove(os.path.join(self.root, ".strict-delivery/config.yml"))
        out, code = self.run_root()
        self.assertTrue(out.startswith("FAIL cites.input:") and "/strict-delivery:init" in out, out)
        self.assertEqual(code, 1)

    def test_config_errors(self):  # A3
        put(self.root, ".strict-delivery/config.yml", "a: [\n")
        out, code = self.run_root()
        self.assertTrue(out.startswith("FAIL cites.input:") and len(self.lines(out)) == 1, out)
        write_record(self.root, ".strict-delivery/config.yml", dict(minimal_config(), bogus=1))
        out, code = self.run_root()
        self.assertIn("unknown key 'bogus'", out)

    def test_json_first(self):  # A4
        self.add("docs/a.md", "`n/z.py:1`\n")
        out, code = self.run_gate("--json", "--root", self.root)
        data = json.loads(out)
        self.assertEqual(data["gate"], "cites")
        self.assertFalse(data["ok"])
        self.assertIn({"status": "FAIL", "id": "cites.line.docs/a.md:1",
                       "reason": "`n/z.py:1`: n/z.py: not a tracked file"}, data["lines"])
        self.assertEqual(code, 1)

    def test_json_output_shape(self):  # A4
        out, code = self.run_gate("--json", "--root", self.root)
        data = json.loads(out)
        self.assertEqual([ln["id"] for ln in data["lines"]], ["cites." + c for c in CATS])
        self.assertTrue(data["ok"])

    def test_json_later_refused(self):  # A4
        out, code = self.run_gate("--root", self.root, "--json")
        self.assertEqual(out, "FAIL cites.input: invalid arguments: unrecognized arguments: --json\n")
        self.assertEqual(code, 1)

    def test_unknown_flag_and_help(self):  # A5
        out, code = self.run_gate("--root", self.root, "--bogus")
        self.assertEqual(out, "FAIL cites.input: invalid arguments: unrecognized arguments: --bogus\n")
        out, code = self.run_gate("--help")
        self.assertEqual(out, "FAIL cites.input: help requested; no gate was run\n")

    def test_root_not_a_repo_and_missing(self):  # A2
        empty = os.path.join(self.tmp, "empty")
        os.mkdir(empty)
        out, code = self.run_gate("--root", empty)
        self.assertTrue(out.startswith("FAIL cites.input: ") and "run /strict-delivery:init" in out, out)
        out, code = self.run_gate("--root", os.path.join(self.tmp, "nope"))
        self.assertTrue(out.startswith("FAIL cites.input: ") and "run /strict-delivery:init" in out, out)

    def test_root_subdirectory_and_empty(self):  # A2
        os.mkdir(os.path.join(self.root, "sub"))
        out, code = self.run_gate("--root", os.path.join(self.root, "sub"))
        self.assertIn("root must be the repository top level", out)
        out, code = self.run_gate("--root", "")
        self.assertTrue(out.startswith("FAIL cites.input: "), out)
        self.assertEqual(code, 1)

    def test_root_linked_worktree_and_relative(self):  # A2
        commit_all(self.root, "c")
        wt = os.path.join(self.tmp, "wt")
        git(self.root, "worktree", "add", "-q", "-b", "other", wt)
        out, code = self.run_gate("--root", wt)
        self.assertEqual(code, 0, out)
        cwd = os.getcwd()
        self.addCleanup(os.chdir, cwd)
        os.chdir(self.root)
        out, code = self.run_gate("--root", ".")
        self.assertEqual(code, 0, out)

    def test_default_root_cwd_and_env(self):  # A1
        cwd = os.getcwd()
        self.addCleanup(os.chdir, cwd)
        os.chdir(self.root)
        out, code = self.run_gate()
        self.assertEqual(code, 0, out)
        os.chdir(self.tmp)
        with mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": self.root}):
            out, code = self.run_gate()
            self.assertEqual(code, 0, out)
        with mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": os.path.join(self.tmp, "nope")}):
            out, code = self.run_gate()
            self.assertEqual(out, "FAIL cites.input: CLAUDE_PROJECT_DIR is not a directory\n")
        out, code = self.run_gate()  # cwd is not a repo
        self.assertTrue(out.startswith("FAIL cites.input: ") and "/strict-delivery:init" in out, out)

    def test_root_error_before_config_error(self):  # A7
        empty = os.path.join(self.tmp, "empty")
        os.mkdir(empty)
        out, code = self.run_gate("--root", empty)
        self.assertNotIn("config.yml", out)

    def test_root_twice_refused(self):  # A6
        out, code = self.run_gate("--root", self.root, "--root", self.root)
        self.assertEqual(out, "FAIL cites.input: invalid arguments: --root given more than once\n")


class TestFixRound1(CitesCase):
    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root searches mode 000 directories")
    def test_unsearchable_parent_fails_whole_run(self):  # Q-C22-1 (a), lstat branch
        self.add("docs/a.md", "x\n")
        d = os.path.join(self.root, "docs")
        os.chmod(d, 0)
        self.addCleanup(os.chmod, d, 0o755)
        out, code = self.run_root()
        self.assertTrue(out.startswith("FAIL cites.input: docs/a.md: cannot read ("), out)
        self.assertEqual(len(self.lines(out)), 1)
        self.assertEqual(code, 1)

    def test_git_not_found_gets_no_init_hint(self):
        with mock.patch.dict(os.environ, {"PATH": ""}):
            out, code = self.run_root()
        self.assertEqual(out, "FAIL cites.input: git not found on PATH; install git\n")
        self.assertEqual(code, 1)

    def test_not_utf8_at_each_bound_of_the_byte_range(self):
        for i, byte in enumerate((b"\x80", b"\x81", b"\xbf", b"\xfe", b"\xff")):
            put(self.root, "docs/b%d.md" % i, b"x " + byte + b"\n", binary=True)
        git(self.root, "add", "-A")
        out, code = self.run_root()
        got = [ln for ln in self.lines(out) if ln.startswith("FAIL")]
        self.assertEqual(got, ["FAIL cites.doc.docs/b%d.md: not UTF-8" % i for i in range(5)])


class TestLoopControl(CitesCase):
    def test_anchorless_landed_entry_does_not_end_the_list(self):
        self.add(PB, "# Present\n")
        write_record(self.root, "%s/%s.yml" % (DEC, DEC_ID), dec(landed_in=["CLAUDE.md", PB + "#bad"]))
        out, code = self.run_root()
        self.assertIn("FAIL cites.landed.%s: %s#bad: " % (DEC_ID, PB), out)
        self.assertEqual(code, 1)

    def test_missing_doc_does_not_end_the_doc_loop(self):
        self.add("a.md", "x\n")
        self.add("b.md", "`b.md:9`\n")
        os.remove(os.path.join(self.root, "a.md"))
        out, code = self.run_root()
        self.assertIn("FAIL cites.doc.a.md: tracked but missing from the working tree\n", out)
        self.assertIn("FAIL cites.line.b.md:1: `b.md:9`: b.md: line 9 is past the end (1 lines)\n", out)


class TestThisRepository(unittest.TestCase):
    def test_this_repository_passes(self):  # E1
        top = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = gate_cites.main(["--root", top])
        self.assertEqual(code, 0, out.getvalue())


if __name__ == "__main__":
    unittest.main()
