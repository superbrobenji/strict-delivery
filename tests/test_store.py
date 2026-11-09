"""Tests for the one-file-per-record store (gates.lib.store) on real directories and real git repositories.
Expected suffix lists and file contents are written out per scenario, not derived from the code under test."""
import contextlib
import inspect
import io
import os
import stat
import subprocess
import unittest
from unittest import mock

from gates.lib import config, decisions, migrations, schema, store as store_mod, yamlsub
from gates.lib.result import GateError, Result, repo_root, run_check, run_gate
from gates.lib.store import Record, Store, base_errors, store_errors
from tests.helpers import (TOP, GitIsolatedTestCase, check_root_forms, commit_all, git, make_repo, root_forms,
                           write_record)

DIR = ".strict-delivery/state/decisions"
FDIR = ".strict-delivery/state/findings"
A = "DEC-20261031-k3f9"
B = "DEC-20261031-m4n5"
C = "DEC-20261031-p6q7"
FID = "F-20261031-k3f9"
FID2 = "F-20261031-m4n5"
DTAG = "decision/%d" % decisions._schema().version  # Global Constraints "Test fixtures"


def row(id_, status="open", **more):
    r = {"schema": DTAG, "id": id_, "status": status}
    r.update(more)
    return r


def resolved(r):
    return r.get("status") in ("resolved", "closed", "merged")


def never(r):
    return False


def always(r):
    return True


def cfg_for(tmp):
    return {"paths": dict(config.DEFAULTS["paths"]), "ids": dict(config.DEFAULTS["ids"])}


def read_bytes(path):
    with open(path, "rb") as fh:
        return fh.read()


class Base(GitIsolatedTestCase):
    def setUp(self):
        super().setUp()
        self.cfg = cfg_for(self.tmp)
        self.n = 0

    def newroot(self):
        self.n += 1
        root = os.path.join(self.tmp, "case%d" % self.n)
        os.mkdir(root)
        git(root, "init", "-q", "-b", "main")  # Store refuses a root that is not a top level (Q-1bfin-2)
        return root

    def newstore(self, root=None, kind="decision"):
        root = root or self.newroot()
        return root, Store(root, kind, self.cfg)

    def ls(self, root):
        return [n for n in os.listdir(root) if n != ".git"]  # the fixture root is a repository

    def mkdir(self, root, rel=DIR):
        path = os.path.join(root, rel)
        os.makedirs(path, exist_ok=True)
        return path

    def writefile(self, root, name, text, rel=DIR):
        path = os.path.join(self.mkdir(root, rel), name)
        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        return path

    def chmod(self, path, mode):
        old = stat.S_IMODE(os.stat(path).st_mode)
        self.addCleanup(os.chmod, path, old)
        os.chmod(path, mode)


class LoadTest(Base):
    def test_missing_dir_is_empty_store(self):  # S1
        root, s = self.newstore()
        self.assertEqual(s.load(), [])

    def test_file_where_dir_should_be_refused(self):  # S1
        root, s = self.newstore()
        os.makedirs(os.path.join(root, ".strict-delivery/state"))
        self.writefile(root, "decisions", "x\n", rel=".strict-delivery/state")
        for fn in (s.load, lambda: s.create(row(A)), lambda: s.replace(row(A))):
            with self.assertRaises(GateError) as cm:
                fn()
            self.assertIn(DIR + ": is not a directory", str(cm.exception))

    def test_parent_that_is_a_file_refused(self):  # S1
        root, s = self.newstore()
        self.writefile(root, "state", "x\n", rel=".strict-delivery")
        with self.assertRaises(GateError) as cm:
            s.load()
        self.assertIn(".strict-delivery/state: is not a directory", str(cm.exception))
        self.assertIn(DIR, str(cm.exception))

    def test_unreadable_dir_refused_naming_it(self):  # S1
        root, s = self.newstore()
        path = self.mkdir(root)
        self.chmod(path, 0)
        with self.assertRaises(GateError) as cm:
            s.load()
        self.assertIn(DIR, str(cm.exception))

    def symlinked(self, where):
        """A root whose register path holds a symlink at ``where`` ("leaf" or "parent"); returns
        (root, store, the symlinked repo-relative path, the real target directory)."""
        root, s = self.newstore()
        target = os.path.join(root, "elsewhere")
        os.makedirs(os.path.join(target, "decisions") if where == "parent" else target)
        if where == "leaf":
            os.makedirs(os.path.join(root, ".strict-delivery/state"))
            os.symlink(target, os.path.join(root, DIR))
            return root, s, DIR, target
        os.makedirs(os.path.join(root, ".strict-delivery"))
        os.symlink(target, os.path.join(root, ".strict-delivery/state"))
        return root, s, ".strict-delivery/state", target

    def test_symlinked_register_path_refused_by_load(self):  # S1 (owner Q-1a3r-1)
        for where in ("leaf", "parent", "top"):
            with self.subTest(where):
                if where == "top":
                    root, s = self.newstore()
                    elsewhere = os.path.join(root, "elsewhere", "state", "decisions")
                    os.makedirs(elsewhere)
                    os.symlink(os.path.join(root, "elsewhere"), os.path.join(root, ".strict-delivery"))
                    link = ".strict-delivery"
                else:
                    root, s, link, _ = self.symlinked(where)
                with self.assertRaises(GateError) as cm:
                    s.load()
                self.assertIn(link + ": is a symlink; register paths must be real directories", str(cm.exception))

    def test_symlinked_register_path_refused_by_create_and_writes_nothing(self):  # S1, S5 (owner Q-1a3r-1)
        for where in ("leaf", "parent"):
            with self.subTest(where):
                root, s, link, target = self.symlinked(where)
                before = sorted(os.walk(root))
                with self.assertRaises(GateError) as cm:
                    s.create(row(A))
                self.assertIn(link + ": is a symlink", str(cm.exception))
                self.assertEqual(sorted(os.walk(root)), before)
                for dirpath, _, files in os.walk(target):
                    self.assertEqual(files, [])

    def test_symlinked_register_path_refused_by_replace(self):  # S1, S6 (owner Q-1a3r-1)
        for where in ("leaf", "parent"):
            with self.subTest(where):
                root, s, link, target = self.symlinked(where)
                write_record(target, "decisions/%s.yml" % A if where == "parent" else "%s.yml" % A, row(A))
                with self.assertRaises(GateError) as cm:
                    s.replace(row(A, "resolved"))
                self.assertIn(link + ": is a symlink", str(cm.exception))

    def test_dangling_symlink_and_unreadable_parent_refused_by_load_create_replace(self):  # S1 dimensions
        root, s = self.newstore()
        os.makedirs(os.path.join(root, ".strict-delivery/state"))
        os.symlink(os.path.join(root, "nowhere"), os.path.join(root, DIR))
        for fn in (s.load, lambda: s.create(row(A)), lambda: s.replace(row(A))):
            with self.assertRaises(GateError) as cm:
                fn()
            self.assertIn(DIR + ": is a symlink", str(cm.exception))
        root, s = self.newstore()
        self.mkdir(root)
        self.chmod(os.path.join(root, ".strict-delivery"), 0)
        for fn in (s.load, lambda: s.create(row(A)), lambda: s.replace(row(A))):
            with self.assertRaises(GateError) as cm:
                fn()
            self.assertIn(DIR, str(cm.exception))

    def test_symlink_above_the_repo_root_is_not_checked(self):  # Q-1a3r-1: only components inside the repo
        root, s = self.newstore()
        alias = os.path.join(self.tmp, "alias")
        os.symlink(root, alias)
        via = Store(alias, "decision", self.cfg)
        via.create(row(A))
        self.assertEqual([r.id for r in via.load()], [A])
        self.assertEqual([r.id for r in s.load()], [A])

    def test_loads_records_sorted_with_relative_file(self):  # S2
        root, s = self.newstore()
        write_record(root, "%s/%s.yml" % (DIR, B), row(B))
        write_record(root, "%s/%s.yml" % (DIR, A), row(A, "resolved"))
        got = s.load()
        self.assertEqual([r.id for r in got], [A, B])
        self.assertEqual([r.file for r in got], ["%s/%s.yml" % (DIR, A), "%s/%s.yml" % (DIR, B)])
        self.assertEqual(got[0].row, row(A, "resolved"))
        self.assertIsInstance(got[0], Record)

    def test_load_skips_index_yml_and_in_force_md(self):  # S2
        root, s = self.newstore()
        write_record(root, "%s/%s.yml" % (DIR, A), row(A))
        self.writefile(root, "index.yml", "a: [1\n")
        self.writefile(root, "in-force.md", "<!-- schema: in-force/1 -->\n")
        self.assertEqual([r.id for r in s.load()], [A])

    def test_every_other_entry_refused_naming_it(self):  # S2 (owner Q-1a3-3, Q-1a3-4)
        def regular_symlink(root):
            self.writefile(root, "real.txt", "id: x\n")
            os.symlink("real.txt", os.path.join(root, DIR, A + ".yml"))

        def fifo_symlink(root):
            os.mkfifo(os.path.join(root, DIR, "fifo"))
            os.symlink("fifo", os.path.join(root, DIR, A + ".yml"))

        def fifo(root):
            os.mkfifo(os.path.join(root, DIR, A + ".yml"))

        def subdir(root):
            os.mkdir(os.path.join(root, DIR, "sub"))

        def subdir_yml(root):
            os.mkdir(os.path.join(root, DIR, "x.yml"))

        def dangling(root):
            os.symlink("nowhere", os.path.join(root, DIR, A + ".yml"))

        cases = {
            "yaml-extension": ("x.yaml", lambda r: self.writefile(r, "x.yaml", "a: 1\n")),
            "gitkeep": (".gitkeep", lambda r: self.writefile(r, ".gitkeep", "")),
            "hidden-yml": (".x.yml", lambda r: self.writefile(r, ".x.yml", "a: 1\n")),
            "bare-dot-yml": (".yml", lambda r: self.writefile(r, ".yml", "a: 1\n")),
            "txt": ("notes.txt", lambda r: self.writefile(r, "notes.txt", "hi\n")),
            "subdir": ("sub", subdir),
            "subdir-named-yml": ("x.yml", subdir_yml),
            "symlink-to-regular": (A + ".yml", regular_symlink),
            "symlink-to-fifo": (A + ".yml", fifo_symlink),
            "dangling-symlink": (A + ".yml", dangling),
            "fifo": (A + ".yml", fifo),
        }
        for name, (shown, make) in cases.items():
            with self.subTest(name):
                root, s = self.newstore()
                self.mkdir(root)
                make(root)
                with self.assertRaises(GateError) as cm:
                    s.load()
                self.assertIn(shown, str(cm.exception))

    def test_content_cases(self):  # S3
        bad = {
            "yaml-error": "a: [1\n",
            "top-level-list": "- a\n- b\n",
            "scalar": "just text\n",
            "empty": "",
            "comment-only": "# nothing\n",
            "invalid-utf8": "x",
        }
        for name, text in bad.items():
            with self.subTest(name):
                root, s = self.newstore()
                path = self.writefile(root, A + ".yml", text)
                if name == "invalid-utf8":
                    with open(path, "wb") as fh:
                        fh.write(b"id: \xff\n")
                with self.assertRaises(GateError) as cm:
                    s.load()
                self.assertIn(A + ".yml", str(cm.exception))

    def test_bom_and_crlf_are_read(self):  # S3
        root, s = self.newstore()
        path = os.path.join(self.mkdir(root), A + ".yml")
        with open(path, "wb") as fh:
            fh.write(b"\xef\xbb\xbfschema: " + DTAG.encode() + b"\r\nid: " + A.encode() + b"\r\nstatus: open\r\n")
        self.assertEqual([r.row for r in s.load()], [row(A)])

    def test_load_does_not_validate_fields(self):  # brief: the store never validates fields
        root, s = self.newstore()
        write_record(root, "%s/%s.yml" % (DIR, A), {"anything": [1, 2]})
        got = s.load()
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0].row, {"anything": [1, 2]})
        self.assertIsNone(got[0].id)

    def test_findings_store_uses_findings_dir_and_prefix(self):
        root, s = self.newstore(kind="finding")
        write_record(root, "%s/%s.yml" % (FDIR, FID), row(FID))
        write_record(root, "%s/%s.yml" % (DIR, A), row(A))
        self.assertEqual([r.id for r in s.load()], [FID])
        self.assertEqual(s.path_for(FID), "%s/%s.yml" % (FDIR, FID))

    def test_unknown_kind_refused(self):
        with self.assertRaises(GateError):
            Store(self.newroot(), "claim", self.cfg)


class PathCreateReplaceTest(Base):
    BAD_IDS = ["../x", "a/b", "DEC-20261031-K3F9", "", "DEC-20261031-k3f9/", "/etc/passwd", "DEC-20260230-k3f9",
               "F-20261031-k3f9", 7, None, True, b"DEC-20261031-k3f9"]

    def test_path_for_valid_id(self):  # S4
        _, s = self.newstore()
        self.assertEqual(s.path_for(A), "%s/%s.yml" % (DIR, A))

    def test_path_for_refuses_bad_ids(self):  # S4
        _, s = self.newstore()
        for bad in self.BAD_IDS:
            with self.subTest(repr(bad)):
                with self.assertRaises(GateError):
                    s.path_for(bad)

    def test_create_and_replace_refuse_bad_ids_before_touching_disk(self):  # S4
        for bad in self.BAD_IDS + [object()]:
            with self.subTest(repr(bad)):
                root, s = self.newstore()
                for fn in (s.create, s.replace):
                    with self.assertRaises(GateError):
                        fn({"id": bad})
                self.assertEqual(self.ls(root), [])  # not even the register directory

    def test_create_and_replace_refuse_missing_id_and_non_dict(self):  # S4
        root, s = self.newstore()
        for fn in (s.create, s.replace):
            for r in ({}, {"status": "open"}, [], None, "x"):
                with self.assertRaises(GateError):
                    fn(r)
        self.assertEqual(self.ls(root), [])

    def test_create_writes_exactly_emit_bytes_and_parents(self):  # S5, S7
        root, s = self.newstore()
        r = row(A, note="two\nlines\n", items=["a", "b"], n=3, flag=True)
        rel = s.create(r)
        self.assertEqual(rel, "%s/%s.yml" % (DIR, A))
        with open(os.path.join(root, rel), "rb") as fh:
            self.assertEqual(fh.read(), yamlsub.emit(r).encode("utf-8"))
        with open(os.path.join(root, rel), "rb") as fh:
            self.assertEqual(
                fh.read(),
                b"schema: " + DTAG.encode() + b"\nid: " + A.encode() + b"\nstatus: open\nnote: |\n  two\n  lines\n"
                b"items:\n  - a\n  - b\nn: 3\nflag: true\n")
        self.assertEqual([x.row for x in s.load()], [r])

    def test_create_refuses_existing(self):  # S5
        root, s = self.newstore()
        s.create(row(A))
        with self.assertRaises(GateError) as cm:
            s.create(row(A, "resolved"))
        self.assertIn(A, str(cm.exception))
        self.assertEqual([x.row for x in s.load()], [row(A)])

    def test_create_is_exclusive_even_for_a_dangling_symlink(self):  # S5: a racing creator
        root, s = self.newstore()
        self.mkdir(root)
        target = os.path.join(root, "target")
        os.symlink(target, os.path.join(root, DIR, A + ".yml"))
        with self.assertRaises(GateError):
            s.create(row(A))
        self.assertFalse(os.path.lexists(target))

    def test_create_opens_with_exclusive_mode(self):  # S5
        root, s = self.newstore()
        modes = []
        real = open

        def spy(path, mode="r", *a, **kw):
            modes.append(mode)
            return real(path, mode, *a, **kw)
        with mock.patch.object(store_mod, "open", spy, create=True):
            s.create(row(A))
        self.assertEqual(modes, ["x"])

    def test_create_unwritable_dir_refused_naming_path(self):  # S5
        root, s = self.newstore()
        path = self.mkdir(root)
        self.chmod(path, 0o500)
        with self.assertRaises(GateError) as cm:
            s.create(row(A))
        self.assertIn(DIR, str(cm.exception))
        self.chmod(path, 0o700)
        self.assertEqual(os.listdir(path), [])

    def test_create_cannot_make_parents_refused(self):  # S5
        root, s = self.newstore()
        self.writefile(root, "state", "x\n", rel=".strict-delivery")
        with self.assertRaises(GateError) as cm:
            s.create(row(A))
        self.assertIn(DIR, str(cm.exception))

    def test_create_unemittable_row_leaves_disk_untouched(self):  # S5
        root, s = self.newstore()
        with self.assertRaises(GateError):
            s.create({"id": A, "x": object()})
        self.assertEqual(self.ls(root), [])

    def test_create_write_failure_removes_the_partial_file(self):  # S5
        root, s = self.newstore()
        real = os.fsync

        with mock.patch.object(store_mod.os, "fsync", side_effect=OSError(28, "No space left on device")):
            with self.assertRaises(GateError):
                s.create(row(A))
        self.assertEqual(os.listdir(os.path.join(root, DIR)), [])
        self.assertIs(os.fsync, real)

    def test_replace_rewrites_existing(self):  # S6, S7
        root, s = self.newstore()
        s.create(row(A))
        new = row(A, "resolved", extra="x")
        self.assertEqual(s.replace(new), "%s/%s.yml" % (DIR, A))
        with open(os.path.join(root, DIR, A + ".yml"), "rb") as fh:
            self.assertEqual(fh.read(), yamlsub.emit(new).encode("utf-8"))
        self.assertEqual(os.listdir(os.path.join(root, DIR)), [A + ".yml"])

    def test_replace_refuses_missing(self):  # S6
        root, s = self.newstore()
        with self.assertRaises(GateError) as cm:
            s.replace(row(A))
        self.assertIn(A, str(cm.exception))
        self.assertEqual(self.ls(root), [])
        self.mkdir(root)
        with self.assertRaises(GateError):
            s.replace(row(A))
        self.assertEqual(os.listdir(os.path.join(root, DIR)), [])

    def test_replace_refuses_non_regular_target(self):  # S6
        root, s = self.newstore()
        self.mkdir(root)
        self.writefile(root, "real.txt", "x: 1\n")
        os.symlink("real.txt", os.path.join(root, DIR, A + ".yml"))
        os.mkdir(os.path.join(root, DIR, B + ".yml"))
        for i in (A, B):
            with self.assertRaises(GateError):
                s.replace(row(i))
        with open(os.path.join(root, DIR, "real.txt")) as fh:
            self.assertEqual(fh.read(), "x: 1\n")

    def test_replace_writes_temp_in_same_dir_then_os_replace(self):  # S6
        root, s = self.newstore()
        s.create(row(A))
        calls = []
        real = os.replace

        def spy(src, dst):
            calls.append((src, dst, os.path.exists(src)))
            return real(src, dst)
        with mock.patch.object(store_mod.os, "replace", spy):
            s.replace(row(A, "resolved"))
        self.assertEqual(len(calls), 1)
        src, dst, existed = calls[0]
        d = os.path.join(root, DIR)
        self.assertEqual(os.path.dirname(src), d)
        self.assertEqual(dst, os.path.join(d, A + ".yml"))
        self.assertNotEqual(src, dst)
        self.assertTrue(existed)

    def test_replace_error_removes_temp_and_keeps_original(self):  # S6
        root, s = self.newstore()
        s.create(row(A))
        before = read_bytes(os.path.join(root, DIR, A + ".yml"))
        with mock.patch.object(store_mod.os, "replace", side_effect=OSError(5, "boom")):
            with self.assertRaises(GateError):
                s.replace(row(A, "resolved"))
        self.assertEqual(os.listdir(os.path.join(root, DIR)), [A + ".yml"])
        self.assertEqual(read_bytes(os.path.join(root, DIR, A + ".yml")), before)

    def test_replace_write_error_removes_temp(self):  # S6
        root, s = self.newstore()
        s.create(row(A))
        with mock.patch.object(store_mod.os, "fsync", side_effect=OSError(28, "No space left on device")):
            with self.assertRaises(GateError):
                s.replace(row(A, "resolved"))
        self.assertEqual(os.listdir(os.path.join(root, DIR)), [A + ".yml"])

    def test_replace_unwritable_dir_refused_naming_path(self):  # S6
        root, s = self.newstore()
        s.create(row(A))
        path = os.path.join(root, DIR)
        self.chmod(path, 0o500)
        with self.assertRaises(GateError) as cm:
            s.replace(row(A, "resolved"))
        self.assertIn(DIR, str(cm.exception))
        self.chmod(path, 0o700)
        self.assertEqual([x.row for x in s.load()], [row(A)])

    def test_replace_keeps_file_mode(self):  # S6
        root, s = self.newstore()
        s.create(row(A))
        os.chmod(os.path.join(root, DIR, A + ".yml"), 0o640)
        s.replace(row(A, "resolved"))
        self.assertEqual(stat.S_IMODE(os.stat(os.path.join(root, DIR, A + ".yml")).st_mode), 0o640)

    def test_replace_unemittable_row_keeps_original(self):  # S6
        root, s = self.newstore()
        s.create(row(A))
        with self.assertRaises(GateError):
            s.replace({"id": A, "x": object()})
        self.assertEqual(os.listdir(os.path.join(root, DIR)), [A + ".yml"])
        self.assertEqual([x.row for x in s.load()], [row(A)])


class StoreErrorsTest(unittest.TestCase):
    def rec(self, id_, file=None, r=None):
        file = file or "%s/%s.yml" % (DIR, id_)
        return Record(id_, r if r is not None else {"id": id_}, file)

    def test_clean_records_have_no_errors(self):
        self.assertEqual(store_errors([self.rec(A), self.rec(B)], "DEC"), [])
        self.assertEqual(store_errors([], "DEC"), [])

    def test_invalid_id_each_class(self):  # E1
        bads = ["DEC-20261031-K3F9", "DEC-20260230-k3f9", "F-20261031-k3f9", "DEC-20261031-k3f", 7, True, "",
                " " + A]
        for bad in bads:
            with self.subTest(repr(bad)):
                rec = self.rec(bad, file="%s/%s.yml" % (DIR, A))
                got = store_errors([rec], "DEC")
                suffixes = [s for s, _ in got]
                self.assertIn("id." + rec.file, suffixes)
                reason = dict(got)["id." + rec.file]
                self.assertEqual(reason, __import__("gates.lib.ids", fromlist=["x"]).id_problem(bad, "DEC"))
                self.assertIn("23456789abcdefghijkmnpqrstuvwxyz", reason)

    def test_missing_id(self):  # E1
        rec = Record(None, {"status": "open"}, "%s/%s.yml" % (DIR, A))
        self.assertIn("id." + rec.file, [s for s, _ in store_errors([rec], "DEC")])

    def test_name_mismatch(self):  # E2
        file = "%s/%s.yml" % (DIR, B)
        got = store_errors([self.rec(A, file=file)], "DEC")
        self.assertEqual([s for s, _ in got], ["name." + file])
        self.assertIn(B + ".yml", got[0][1])
        self.assertIn(A, got[0][1])

    def test_name_differs_only_in_case(self):  # E2
        file = "%s/%s.yml" % (DIR, A.upper())
        got = store_errors([self.rec(A, file=file)], "DEC")
        self.assertEqual([s for s, _ in got], ["name." + file])

    def test_name_equal_no_error(self):  # E2
        self.assertEqual(store_errors([self.rec(A)], "DEC"), [])

    def test_duplicate_id_lists_files(self):  # E3
        fa, fb, fc = ("%s/%s.yml" % (DIR, n) for n in ("a-copy", "b-copy", "c-copy"))
        two = store_errors([self.rec(A, fa), self.rec(A, fb)], "DEC")
        dups = [(s, r) for s, r in two if s.startswith("duplicate.")]
        self.assertEqual([s for s, _ in dups], ["duplicate." + A])
        self.assertIn(fa, dups[0][1])
        self.assertIn(fb, dups[0][1])
        three = store_errors([self.rec(A, fa), self.rec(A, fb), self.rec(A, fc), self.rec(B)], "DEC")
        dups = [(s, r) for s, r in three if s.startswith("duplicate.")]
        self.assertEqual([s for s, _ in dups], ["duplicate." + A])
        for f in (fa, fb, fc):
            self.assertIn(f, dups[0][1])
        self.assertNotIn(B, dups[0][1])

    def test_unhashable_or_non_str_ids_do_not_crash_duplicates(self):  # E1/E3
        recs = [Record([1], {"id": [1]}, "%s/x1.yml" % DIR), Record([1], {"id": [1]}, "%s/x2.yml" % DIR)]
        suffixes = [s for s, _ in store_errors(recs, "DEC")]
        self.assertIn("id.%s/x1.yml" % DIR, suffixes)
        self.assertFalse([s for s in suffixes if s.startswith("duplicate.")])


class GitCase(Base):
    """A repository on branch main with an open and a resolved decision, then a feature branch forked from it."""

    def setUp(self):
        super().setUp()
        self.root = make_repo(self.work)
        self.cfg = config.load(self.root)
        self.store = Store(self.root, "decision", self.cfg)

    def put(self, id_, r=None, rel=DIR):
        return write_record(self.root, "%s/%s.yml" % (rel, id_), r if r is not None else row(id_))

    def seed(self):
        self.put(A, row(A, "open"))
        self.put(B, row(B, "resolved", note="x"))
        commit_all(self.root, "seed")

    def fork(self):
        git(self.root, "checkout", "-q", "-b", "feature")

    def errs(self, base="main", is_resolved=resolved, may_delete=never, store=None):
        return base_errors(self.root, store or self.store, base, is_resolved, may_delete)

    def suffixes(self, **kw):
        return sorted(s for s, _ in self.errs(**kw))


class BaseErrorsRefTest(GitCase):
    def test_absent_ref_is_gate_error(self):  # B1
        self.seed()
        with self.assertRaises(GateError):
            self.errs(base="no-such-ref")

    def test_bad_base_values_refused(self):  # B1
        self.seed()
        for bad in ("a" * 41, "main" + "0" * 41, "-x", "--help", "^main", "^HEAD", "", None, 7, b"main"):
            with self.subTest(repr(bad)):
                with self.assertRaises(GateError):
                    self.errs(base=bad)
        with self.assertRaises(GateError) as e:  # F-1a-ver-2: refused by rule, not by git's failure
            self.errs(base="^main")
        self.assertEqual(str(e.exception), "ref must not start with '^'")

    def test_over_long_hex_refused_even_when_a_ref_exists(self):  # B1
        self.seed()
        name = "b" * 41
        git(self.root, "branch", name)
        with self.assertRaises(GateError):
            self.errs(base=name)

    def test_base_equal_to_head(self):  # B1
        self.seed()
        self.assertEqual(self.suffixes(base="HEAD"), [])
        self.assertEqual(self.suffixes(base="main"), [])

    def test_base_equal_to_head_sees_working_tree_deletion(self):  # B1, B8, Review Focus 1
        self.seed()
        git(self.root, "rm", "-q", "--", "%s/%s.yml" % (DIR, A))
        errs = self.errs(base="HEAD")
        self.assertEqual([s for s, _ in errs], ["deleted." + A])

    def test_branch_behind_head(self):  # B1
        self.seed()
        self.fork()
        self.put(C)
        commit_all(self.root, "feature adds C")
        self.assertEqual(self.suffixes(), [])

    def test_base_ahead_of_merge_base(self):  # B1
        self.seed()
        self.fork()
        git(self.root, "checkout", "-q", "main")
        self.put(C)
        commit_all(self.root, "main adds C")
        git(self.root, "checkout", "-q", "feature")
        self.assertEqual(self.suffixes(), [])

    def test_shallow_clone_without_merge_base(self):  # B1
        self.seed()
        self.fork()
        self.put(C)
        commit_all(self.root, "feature")
        git(self.root, "checkout", "-q", "main")
        self.put(B, row(B, "resolved", note="y"))
        commit_all(self.root, "main moves")
        clone = os.path.join(self.tmp, "clone")
        subprocess.run(["git", "clone", "-q", "--depth", "1", "--no-local", "--branch", "feature",
                        "file://" + self.root, clone], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        git(clone, "fetch", "-q", "--depth", "1", "origin", "main:main")
        s = Store(clone, "decision", self.cfg)
        with self.assertRaises(GateError):
            base_errors(clone, s, "main", resolved, never)

    def test_base_without_directory(self):  # B2
        self.fork()
        self.assertEqual(self.suffixes(), [])
        self.put(A)
        self.assertEqual(self.suffixes(), [])  # nothing at base: nothing deleted, nothing resolved, no collision

    def test_directory_absent_at_merge_base_present_at_tip(self):  # B2
        self.fork()
        git(self.root, "checkout", "-q", "main")
        self.put(A)
        commit_all(self.root, "main creates dir")
        git(self.root, "checkout", "-q", "feature")
        self.assertEqual(self.suffixes(), [])

    def test_directory_absent_at_tip_present_at_merge_base(self):  # B2
        self.seed()
        self.fork()
        git(self.root, "checkout", "-q", "main")
        git(self.root, "rm", "-q", "-r", "--", DIR)
        commit_all(self.root, "main removes the records")
        git(self.root, "checkout", "-q", "feature")
        self.assertEqual(self.suffixes(), [])


class BaseErrorsChangeTest(GitCase):
    def setUp(self):
        super().setUp()
        self.seed()
        self.fork()

    def test_unchanged_branch(self):
        self.assertEqual(self.errs(), [])

    def test_deleted_base_record_fails(self):  # B3, Review Focus 1
        git(self.root, "rm", "-q", "--", "%s/%s.yml" % (DIR, A))
        commit_all(self.root, "delete A")
        errs = self.errs()
        self.assertEqual([s for s, _ in errs], ["deleted." + A])
        self.assertEqual(errs[0][1], "%s/%s.yml exists on main; records on the base branch are never deleted"
                         % (DIR, A))

    def test_deleted_resolved_record_is_only_deleted(self):  # B3
        git(self.root, "rm", "-q", "--", "%s/%s.yml" % (DIR, B))
        self.assertEqual(self.suffixes(), ["deleted." + B])

    def test_may_delete_allows_and_gets_base_row(self):  # B3
        git(self.root, "rm", "-q", "--", "%s/%s.yml" % (DIR, A))
        seen = []

        def allow(r):
            seen.append(r)
            return True
        self.assertEqual(self.errs(may_delete=allow), [])
        self.assertEqual(seen, [row(A, "open")])

    def test_may_delete_decides_per_row(self):  # B3
        git(self.root, "rm", "-q", "--", "%s/%s.yml" % (DIR, A), "%s/%s.yml" % (DIR, B))
        self.assertEqual(self.suffixes(may_delete=lambda r: r["id"] == A), ["deleted." + B])

    def test_may_delete_not_asked_for_kept_records(self):  # B3
        asked = []
        self.errs(may_delete=lambda r: asked.append(r) or False)
        self.assertEqual(asked, [])

    def test_uncommitted_deletion(self):  # B8
        os.remove(os.path.join(self.root, DIR, A + ".yml"))
        self.assertEqual(self.suffixes(), ["deleted." + A])

    def test_deletion_checked_at_merge_base(self):  # B3: record added on base tip after the fork
        git(self.root, "checkout", "-q", "main")
        self.put(C)
        commit_all(self.root, "main adds C")
        git(self.root, "checkout", "-q", "feature")
        self.assertFalse(os.path.exists(os.path.join(self.root, DIR, C + ".yml")))
        self.assertEqual(self.errs(), [])

    def test_renamed_record_is_deleted_plus_new(self):  # B4
        git(self.root, "mv", "%s/%s.yml" % (DIR, A), "%s/%s.yml" % (DIR, C))
        commit_all(self.root, "rename")
        self.assertEqual(self.suffixes(), ["deleted." + A])
        recs = self.store.load()
        self.assertIn("name.%s/%s.yml" % (DIR, C), [s for s, _ in store_errors(recs, "DEC")])

    def test_open_change_is_not_flagged(self):  # B5
        self.put(A, row(A, "open", note="edited"))
        self.assertEqual(self.errs(), [])

    def test_resolved_change_is_immutable(self):  # B5
        self.put(B, row(B, "resolved", note="edited"))
        errs = self.errs()
        self.assertEqual([s for s, _ in errs], ["immutable." + B])
        self.assertEqual(errs[0][1], "resolved records are immutable; record the change as a new decision "
                         "with supersedes: " + B)

    def test_open_and_resolved_changed_together(self):  # B5
        self.put(A, row(A, "open", note="edited"))
        self.put(B, row(B, "resolved", note="edited"))
        self.assertEqual(self.suffixes(), ["immutable." + B])

    def test_open_at_merge_base_becoming_resolved_is_not_a_change(self):  # B5: resolution is judged at mb
        self.put(A, row(A, "resolved"))
        self.assertEqual(self.errs(), [])

    def test_resolved_record_with_different_bytes_same_value_is_not_a_change(self):  # B5 owner Q-1a3-5
        path = os.path.join(self.root, DIR, B + ".yml")
        text = (
            "# a comment the emitter would drop\n"
            "note: 'x'\n"
            "status: \"resolved\"\n"
            "id: " + B + "\r\n"
            "schema: " + DTAG + "\n"
        )
        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        self.assertNotEqual(read_bytes(path), yamlsub.emit(row(B, "resolved", note="x")).encode())
        self.assertEqual(self.errs(), [])

    def test_type_change_with_equal_python_value_is_a_change(self):  # B5 (owner Q-1a3r-2): 1 vs true differ
        self.put(B, row(B, "resolved", n=1))
        commit_all(self.root, "n=1")
        git(self.root, "checkout", "-q", "main")
        git(self.root, "merge", "-q", "--ff-only", "feature")
        git(self.root, "checkout", "-q", "-b", "second")
        self.put(B, row(B, "resolved", n=True))
        self.assertEqual(self.suffixes(), ["immutable." + B])

    def test_list_order_change_is_a_change(self):  # B5
        self.put(B, row(B, "resolved", items=["a", "b"]))
        commit_all(self.root, "items")
        git(self.root, "checkout", "-q", "main")
        git(self.root, "merge", "-q", "--ff-only", "feature")
        git(self.root, "checkout", "-q", "-b", "second")
        self.put(B, row(B, "resolved", items=["b", "a"]))
        self.assertEqual(self.suffixes(), ["immutable." + B])

    def test_nested_value_change_is_a_change(self):  # B5
        self.put(B, row(B, "resolved", answered={"by": "x", "at": "abc"}))
        commit_all(self.root, "nested")
        git(self.root, "checkout", "-q", "main")
        git(self.root, "merge", "-q", "--ff-only", "feature")
        git(self.root, "checkout", "-q", "-b", "second")
        self.put(B, row(B, "resolved", answered={"by": "x", "at": "abd"}))
        self.assertEqual(self.suffixes(), ["immutable." + B])

    def test_key_added_or_removed_is_a_change(self):  # B5
        self.put(B, row(B, "resolved", note="x", extra="y"))
        self.assertEqual(self.suffixes(), ["immutable." + B])
        self.put(B, {"schema": DTAG, "id": B, "status": "resolved"})
        self.assertEqual(self.suffixes(), ["immutable." + B])

    def test_uncommitted_edit_of_resolved_record(self):  # B8
        self.put(B, row(B, "resolved", note="edited"))
        self.assertEqual(self.suffixes(), ["immutable." + B])

    def test_is_resolved_gets_row_at_merge_base(self):  # B5
        seen = []

        def spy(r):
            seen.append(r["id"])
            return r["status"] == "resolved"
        self.put(A, row(A, "resolved"))  # resolved only in the working tree
        self.assertEqual([s for s, _ in self.errs(is_resolved=spy)], [])
        self.assertEqual(sorted(seen), [A, B])


class BaseErrorsFindingTest(GitCase):
    def test_closed_finding_changed_to_merged_is_immutable(self):  # B5, spec 7.2 exception is the cleanup step's
        store = Store(self.root, "finding", self.cfg)
        self.put(FID, {"schema": "finding/1", "id": FID, "status": "closed"}, rel=FDIR)
        self.put(FID2, {"schema": "finding/1", "id": FID2, "status": "open"}, rel=FDIR)
        commit_all(self.root, "findings")
        self.fork()
        self.put(FID, {"schema": "finding/1", "id": FID, "status": "merged"}, rel=FDIR)
        self.put(FID2, {"schema": "finding/1", "id": FID2, "status": "closed"}, rel=FDIR)
        errs = base_errors(self.root, store, "main", lambda r: r["status"] in ("closed", "merged"), never)
        self.assertEqual([s for s, _ in errs], ["immutable." + FID])
        self.assertEqual(errs[0][1], "resolved records are immutable; record the change as a new finding")

    def test_deleted_finding_uses_may_delete(self):  # B3
        store = Store(self.root, "finding", self.cfg)
        self.put(FID, {"schema": "finding/1", "id": FID, "status": "closed"}, rel=FDIR)
        commit_all(self.root, "finding")
        self.fork()
        git(self.root, "rm", "-q", "--", "%s/%s.yml" % (FDIR, FID))
        self.assertEqual([s for s, _ in base_errors(self.root, store, "main", resolved, never)],
                         ["deleted." + FID])
        self.assertEqual(base_errors(self.root, store, "main", resolved, always), [])


class BaseErrorsCollisionTest(GitCase):
    def setUp(self):
        super().setUp()
        self.seed()
        self.fork()

    def diverge(self, branch_row, main_row, branch_file=None):
        self.put(C, branch_row) if branch_file is None else write_record(self.root, branch_file, branch_row)
        commit_all(self.root, "feature adds C")
        git(self.root, "checkout", "-q", "main")
        self.put(C, main_row)
        commit_all(self.root, "main adds C")
        git(self.root, "checkout", "-q", "feature")

    def test_collision_with_base(self):  # B7
        self.diverge(row(C, note="branch"), row(C, note="main"))
        errs = self.errs()
        self.assertEqual([s for s, _ in errs], ["collision." + C])
        self.assertEqual(errs[0][1], "id %s already exists on main; mint a new id" % C)

    def test_one_vs_true_is_a_collision(self):  # B7 (owner Q-1a3r-2): type-strict like B5
        self.diverge(row(C, n=1), row(C, n=True))
        self.assertEqual(self.suffixes(), ["collision." + C])

    def test_one_of_several_differing_tip_rows_is_a_collision(self):  # F-1a3r-2: the id is in two files at the tip
        self.put(C, row(C, note="same"))
        commit_all(self.root, "feature adds C")
        git(self.root, "checkout", "-q", "main")
        self.put(C, row(C, note="same"))
        write_record(self.root, "%s/other.yml" % DIR, row(C, note="different"))
        commit_all(self.root, "main has C twice")
        git(self.root, "checkout", "-q", "feature")
        self.assertEqual(self.suffixes(), ["collision." + C])

    def test_same_content_cherry_pick_is_no_collision(self):  # B7
        self.diverge(row(C, note="same"), row(C, note="same"))
        self.assertEqual(self.errs(), [])

    def test_same_parsed_content_different_bytes_is_no_collision(self):  # B7 (parsed comparison, as B5)
        self.diverge(row(C, note="same"), row(C, note="same"))
        with open(os.path.join(self.root, DIR, C + ".yml"), "w", encoding="utf-8", newline="") as fh:
            fh.write("# c\nstatus: open\nnote: 'same'\nid: %s\nschema: %s\n" % (C, DTAG))
        self.assertEqual(self.errs(), [])

    def test_collision_is_against_tip_not_merge_base(self):  # B7
        self.diverge(row(C, note="branch"), row(C, note="main"))
        git(self.root, "checkout", "-q", "main")
        git(self.root, "rm", "-q", "--", "%s/%s.yml" % (DIR, C))
        commit_all(self.root, "main drops C")
        git(self.root, "checkout", "-q", "feature")
        self.assertEqual(self.errs(), [])

    def test_collision_in_another_file_name(self):  # B7: the id is the row's, wherever its file is
        self.diverge(row(C, note="branch"), row(C, note="main"), branch_file="%s/other.yml" % DIR)
        self.assertEqual(self.suffixes(), ["collision." + C])

    def test_id_present_at_merge_base_is_not_added(self):  # B7
        self.put(A, row(A, "open", note="changed"))
        commit_all(self.root, "A edited")
        git(self.root, "checkout", "-q", "main")
        self.put(A, row(A, "open", note="main edit"))
        commit_all(self.root, "main edits A")
        git(self.root, "checkout", "-q", "feature")
        self.assertEqual(self.errs(), [])

    def test_collision_check_sees_uncommitted_new_record(self):  # B7, B8
        git(self.root, "checkout", "-q", "main")
        self.put(C, row(C, note="main"))
        commit_all(self.root, "main adds C")
        git(self.root, "checkout", "-q", "feature")
        self.put(C, row(C, note="branch"))
        self.assertEqual(self.suffixes(), ["collision." + C])


class BaseErrorsContentTest(GitCase):
    def test_unparsable_record_at_merge_base_refused(self):  # B6
        write_record(self.root, "%s/x.yml" % DIR, row(A))
        with open(os.path.join(self.root, DIR, "bad.yml"), "w") as fh:
            fh.write("a: [1\n")
        commit_all(self.root, "bad at mb")
        self.fork()
        os.remove(os.path.join(self.root, DIR, "bad.yml"))
        with self.assertRaises(GateError) as cm:
            self.errs()
        self.assertIn("main:%s/bad.yml" % DIR, str(cm.exception))

    def test_unparsable_record_only_at_merge_base_refused(self):  # B6, F-1a3r-1: gone from the tip and the branch
        self.seed()
        with open(os.path.join(self.root, DIR, "bad.yml"), "w") as fh:
            fh.write("a: [1\n")
        commit_all(self.root, "bad at mb")
        self.fork()
        git(self.root, "checkout", "-q", "main")
        git(self.root, "rm", "-q", "--", "%s/bad.yml" % DIR)
        commit_all(self.root, "main drops bad")
        git(self.root, "checkout", "-q", "feature")
        git(self.root, "rm", "-q", "--", "%s/bad.yml" % DIR)
        commit_all(self.root, "feature drops bad")
        with self.assertRaises(GateError) as cm:
            self.errs()
        self.assertIn("main:%s/bad.yml (at the merge base)" % DIR, str(cm.exception))

    def test_base_side_symlink_and_non_record_entries_are_ignored(self):  # B9 (owner Q-1a3r-3)
        self.seed()
        os.symlink("%s.yml" % A, os.path.join(self.root, DIR, "%s.yml" % C))
        for name in (".x.yml", "x.yaml"):
            with open(os.path.join(self.root, DIR, name), "w") as fh:
                fh.write("a: [1\n")
        commit_all(self.root, "symlink record and junk at the base")
        self.fork()
        git(self.root, "rm", "-q", "--", "%s/%s.yml" % (DIR, C), "%s/.x.yml" % DIR, "%s/x.yaml" % DIR)
        self.assertEqual(self.errs(), [])

    def test_base_side_gitlink_entries_are_ignored(self):  # B9 (owner Q-1a3r-3), F-1a3rr-1: mode 160000
        self.seed()
        sha = git(self.root, "rev-parse", "HEAD")
        path = "%s/%s.yml" % (DIR, C)
        git(self.root, "update-index", "--add", "--cacheinfo", "160000,%s,%s" % (sha, path))
        git(self.root, "commit", "-q", "-m", "gitlink record at the base")
        self.assertIn("160000 commit", git(self.root, "ls-tree", "HEAD", "--", path))
        self.fork()
        self.assertEqual(self.errs(), [])
        git(self.root, "rm", "-q", "--cached", "--", path)
        self.assertEqual(self.errs(), [])

    def test_unparsable_record_at_base_tip_refused(self):  # B6
        self.seed()
        self.fork()
        git(self.root, "checkout", "-q", "main")
        with open(os.path.join(self.root, DIR, "bad.yml"), "w") as fh:
            fh.write("a: [1\n")
        commit_all(self.root, "bad at tip")
        git(self.root, "checkout", "-q", "feature")
        with self.assertRaises(GateError) as cm:
            self.errs()
        self.assertIn("main:%s/bad.yml" % DIR, str(cm.exception))

    def test_non_mapping_record_at_base_refused(self):  # B6
        self.seed()
        for text in ("- a\n", "plain\n", ""):
            with self.subTest(text):
                git(self.root, "checkout", "-q", "main")
                with open(os.path.join(self.root, DIR, "odd.yml"), "w") as fh:
                    fh.write(text)
                commit_all(self.root, "odd")
                git(self.root, "checkout", "-q", "-B", "feature", "HEAD~1")
                with self.assertRaises(GateError) as cm:
                    self.errs()
                self.assertIn("main:%s/odd.yml" % DIR, str(cm.exception))
                git(self.root, "checkout", "-q", "main")
                git(self.root, "reset", "-q", "--hard", "HEAD~1")

    def test_non_record_files_at_base_are_ignored(self):  # B2/B6: index.yml, hidden and other-extension files
        self.seed()
        self.fork()
        git(self.root, "checkout", "-q", "main")
        for name in ("index.yml", ".gitkeep", "x.yaml", "in-force.md", ".x.yml"):
            with open(os.path.join(self.root, DIR, name), "w") as fh:
                fh.write("a: [1\n")
        commit_all(self.root, "extras at the base tip")
        git(self.root, "checkout", "-q", "feature")
        self.assertEqual(self.suffixes(), [])

    def test_base_record_with_bom_and_crlf_is_read(self):  # B6: read like Store.load reads
        self.mkdir(self.root)
        with open(os.path.join(self.root, DIR, A + ".yml"), "wb") as fh:
            fh.write(b"\xef\xbb\xbfschema: " + DTAG.encode() + b"\r\nid: " + A.encode() + b"\r\nstatus: resolved\r\n")
        commit_all(self.root, "bom")
        self.fork()
        self.assertEqual(self.errs(), [])
        self.put(A, row(A, "resolved"))   # same parsed value, other bytes
        self.assertEqual(self.errs(), [])

    def test_unloadable_working_tree_is_refused(self):  # B8
        self.seed()
        self.fork()
        with open(os.path.join(self.root, DIR, "bad.yml"), "w") as fh:
            fh.write("a: [1\n")
        with self.assertRaises(GateError) as cm:
            self.errs()
        self.assertIn("bad.yml", str(cm.exception))

    def test_git_called_through_gitinfo_only(self):  # constraint: no direct git call from the store
        self.seed()
        self.fork()
        import gates.lib.store as m
        self.assertFalse(hasattr(m, "subprocess"))



class RootGuardTest(GitIsolatedTestCase):
    """Q-1bfin-2 (a): Store(...) refuses a root that is not the top level (so load, create and replace, which
    need a Store, inherit it); O4 (task 1c0.1)."""

    def setUp(self):
        super().setUp()
        self.root = make_repo(self.work)
        self.cfg = config.load(self.root)

    def test_subdirectory_root_refused_everywhere(self):  # T1-T12, T15
        forms = root_forms(self.tmp, self.root)
        check_root_forms(self, forms, {"Store": lambda r: Store(r, "decision", self.cfg),
                                       "Store finding": lambda r: Store(r, "finding", self.cfg)})

    def test_accepted_forms_give_a_working_store(self):  # T3, T5, T9
        forms = dict((n, p) for n, p, v in root_forms(self.tmp, self.root) if v == "ok")
        for name in ("top", "top/", "link", "link/", "worktree"):
            with self.subTest(form=name):
                s = Store(forms[name], "decision", self.cfg)
                self.assertEqual(s.load(), [])
                self.assertEqual(s.path_for(A), "%s/%s.yml" % (DIR, A))

    def test_root_check_comes_before_kind_and_config_checks(self):  # O4
        sub = os.path.join(self.root, "sub")
        os.mkdir(sub)
        for kind, cfg in (("widget", self.cfg), ("decision", {}), ("claim", {})):
            with self.subTest(kind=kind, cfg=cfg):
                with self.assertRaises(GateError) as e:
                    Store(sub, kind, cfg)
                self.assertEqual(str(e.exception), TOP)
        with self.assertRaises(GateError) as e:
            Store(self.root, "widget", self.cfg)
        self.assertEqual(str(e.exception), "store kind must be 'decision' or 'finding'")


class BaseErrorsStoreRootTest(GitCase):
    """U-1bfin-1: base_errors refuses a Store that belongs to another root (B1-B8, O7)."""

    def setUp(self):
        super().setUp()
        self.seed()
        self.fork()
        git(self.root, "rm", "-q", "--", "%s/%s.yml" % (DIR, A))
        commit_all(self.root, "delete A")

    def clone(self, name="clone"):
        dest = os.path.join(self.tmp, name)
        subprocess.run(["git", "clone", "-q", "--branch", "feature", self.root, dest], check=True,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        git(dest, "fetch", "-q", "origin", "main:main")
        return dest

    def no_history_reads(self):
        boom = AssertionError("git history read before the store check")
        return mock.patch.multiple("gates.lib.store.gitinfo", merge_base=mock.Mock(side_effect=boom),
                                   ls_tree=mock.Mock(side_effect=boom), show=mock.Mock(side_effect=boom))

    def test_same_root(self):  # B1
        self.assertEqual(self.suffixes(), ["deleted." + A])

    def test_symlink_to_the_same_root_is_accepted_both_ways(self):  # B2
        link = os.path.join(self.tmp, "alias")
        os.symlink(self.root, link)
        for given, held in ((self.root, link), (link, self.root), (link + "/", self.root)):
            with self.subTest(given=given, held=held):
                errs = base_errors(given, Store(held, "decision", self.cfg), "main", resolved, never)
                self.assertEqual([s for s, _ in errs], ["deleted." + A])

    def test_another_clone_is_refused_before_any_history_is_read(self):  # B3
        clone = self.clone()
        foreign = Store(clone, "decision", self.cfg)
        with self.no_history_reads(), self.assertRaises(GateError) as e:
            base_errors(self.root, foreign, "main", resolved, never)
        self.assertEqual(str(e.exception), "base_errors: the store's root %s is not the root given %s"
                         % (clone, self.root))
        # the clone's own store with the clone's own root is accepted
        self.assertEqual([s for s, _ in base_errors(clone, foreign, "main", resolved, never)], ["deleted." + A])

    def test_linked_worktree_is_refused(self):  # B4
        wt = os.path.join(self.tmp, "wt")
        git(self.root, "worktree", "add", "-q", "--detach", wt)
        with self.no_history_reads(), self.assertRaises(GateError) as e:
            base_errors(self.root, Store(wt, "decision", self.cfg), "main", resolved, never)
        self.assertIn("is not the root given", str(e.exception))

    def test_subdirectory_store_is_refused_at_construction(self):  # B5
        sub = os.path.join(self.root, "pkg")
        os.mkdir(sub)
        with self.assertRaises(GateError) as e:
            Store(sub, "decision", self.cfg)
        self.assertEqual(str(e.exception), TOP)

    def test_store_root_gone_at_check_time_is_a_gate_error(self):  # B6
        clone = self.clone()
        foreign = Store(clone, "decision", self.cfg)
        os.rename(clone, clone + ".moved")
        with self.no_history_reads(), self.assertRaises(GateError) as e:
            base_errors(self.root, foreign, "main", resolved, never)
        self.assertEqual(str(e.exception), "base_errors: the store's root %s is not the root given %s"
                         % (clone, self.root))

    def test_samefile_oserror_counts_as_not_the_same(self):  # B6: the first call is the root check
        with mock.patch("gates.lib.store.os.path.samefile", side_effect=[True, OSError("boom")]):
            with self.no_history_reads(), self.assertRaises(GateError) as e:
                self.errs()
        self.assertIn("is not the root given", str(e.exception))

    def test_not_a_store_is_a_gate_error(self):  # B7
        for bogus in (None, {}, {"root": self.root}, "store", object()):
            with self.subTest(store=repr(bogus)):
                with self.no_history_reads(), self.assertRaises(GateError) as e:
                    base_errors(self.root, bogus, "main", resolved, never)
                self.assertIn("is not the root given", str(e.exception))

    def test_message_with_a_newline_in_the_root_renders_once(self):  # B8
        clone = self.clone("cl\none")
        out = run_check("x", lambda a: base_errors(self.root, Store(clone, "decision", self.cfg), "main",
                                                   resolved, never), []).render(False)
        self.assertEqual(out, "FAIL x.input: base_errors: the store's root %s is not the root given %s\n"
                         % (clone.replace("\n", "\\n"), self.root))

    def test_order_root_then_store_then_base(self):  # O7
        sub = os.path.join(self.root, "pkg")
        os.mkdir(sub)
        clone = self.clone()
        foreign = Store(clone, "decision", self.cfg)
        with self.assertRaises(GateError) as e:
            base_errors(sub, foreign, 5, resolved, never)
        self.assertEqual(str(e.exception), TOP)
        with self.assertRaises(GateError) as e:
            base_errors(self.root, foreign, 5, resolved, never)
        self.assertIn("is not the root given", str(e.exception))
        with self.assertRaises(GateError) as e:
            base_errors(self.root, self.store, 5, resolved, never)
        self.assertEqual(str(e.exception), "the base ref must be a string")


if __name__ == "__main__":
    unittest.main()


class NonToplevelRootTest(GitCase):
    """F-1a-fin-1 (owner Q-1a-fin-1): a root that is not the git top level is refused, never read as empty."""

    def setUp(self):
        super().setUp()
        self.seed()
        self.fork()
        git(self.root, "rm", "-q", "--", "%s/%s.yml" % (DIR, A))
        commit_all(self.root, "delete A")
        self.sub = os.path.join(self.root, "pkg")
        os.mkdir(self.sub)

    def test_top_level_root_still_reports_the_deletion(self):
        self.assertEqual(self.suffixes(), ["deleted." + A])

    def test_explicit_subdirectory_root_is_refused(self):
        with self.assertRaises(GateError) as e:
            base_errors(self.sub, Store(self.sub, "decision", self.cfg), "main", resolved, never)
        self.assertIn("git rev-parse --show-toplevel", str(e.exception))
        self.assertIn("top level", str(e.exception))
        self.assertNotIn(self.root, str(e.exception))

    def test_claude_project_dir_subdirectory_gate_line(self):
        buf = io.StringIO()
        with mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": self.sub}), contextlib.redirect_stdout(buf):
            root = repo_root()
            run_gate("x", lambda a: base_errors(root, Store(root, "decision", self.cfg), "main", resolved, never)
                     and Result("x", []), [])
        self.assertTrue(buf.getvalue().startswith("FAIL x.input: git rev-parse --show-toplevel"), buf.getvalue())

    def test_symlinked_alias_of_top_level_is_accepted(self):
        alias = os.path.join(self.tmp, "alias")
        os.symlink(self.root, alias)
        errs = base_errors(alias, Store(alias, "decision", self.cfg), "main", resolved, never)
        self.assertEqual([s for s, _ in errs], ["deleted." + A])


class EscapeOnceTest(Base):
    """F-1a-fin-3 (owner Q-1a-fin-3): text is escaped once, by Result.render."""

    def test_id_with_newline_in_cannot_use_id(self):
        _, st = self.newstore()
        buf = io.StringIO()

        def check(args):
            st.path_for("x\ny")
        with contextlib.redirect_stdout(buf):
            run_gate("x", check, [])
        out = buf.getvalue()
        self.assertEqual(len(out.splitlines()), 1)
        self.assertTrue(out.startswith("FAIL x.input: cannot use id x\\ny: "), out)
        self.assertNotIn("\\\\n", out)

    def test_store_errors_name_reason_with_newline_id(self):
        errs = store_errors([Record("a\nb", {"id": "a\nb"}, "d/c.yml")], "DEC")
        name = [r for s, r in errs if s.startswith("name.")][0]
        res = Result("x", [])
        res.fail("x.store." + [s for s, _ in errs if s.startswith("name.")][0], name)
        line = res.render(False).splitlines()
        self.assertEqual(len(line), 1)
        self.assertTrue(line[0].endswith("differs from the record id a\\nb"), line[0])


class UnusableStoreRootTest(GitCase):
    """F-v2-2, owner Q-VER2-2 (a): a store.root or root that os.path.samefile rejects (TypeError, ValueError or
    OSError) is refused with the same GateError as a root that is not the same file (plan :504)."""

    WANT = "base_errors: the store's root %s is not the root given %s"
    # (the root, as the reason renders it, the exception os.path.samefile raises for it)
    BAD = ((None, "None", TypeError), (1.5, "1.5", TypeError), (["x"], "[x]", TypeError),
           ("a\0b", "a\0b", ValueError), (b"a\0b", "b'a\0b'", ValueError), (-1, "-1", OSError))

    def no_history_reads(self):
        boom = AssertionError("git history read before the store check")
        return mock.patch.multiple("gates.lib.store.gitinfo", merge_base=mock.Mock(side_effect=boom),
                                   ls_tree=mock.Mock(side_effect=boom), show=mock.Mock(side_effect=boom))

    def test_each_bad_value_is_one_samefile_rejects(self):  # the dimension is what the rows say it is
        for bad, _, exc in self.BAD:
            with self.subTest(root=repr(bad)), self.assertRaises(exc):
                os.path.samefile(bad, self.root)

    def test_a_store_root_set_afterwards_is_a_gate_error(self):  # F-v2-2
        self.seed()
        for bad, shown, _ in self.BAD:
            with self.subTest(root=repr(bad)):
                s = Store(self.root, "decision", self.cfg)
                s.root = bad
                with self.no_history_reads(), self.assertRaises(GateError) as e:
                    base_errors(self.root, s, "main", resolved, never)
                self.assertEqual(str(e.exception), self.WANT % (shown, self.root))

    def test_through_run_check_it_is_the_input_fail_line(self):  # F-v2-2
        s = Store(self.root, "decision", self.cfg)
        s.root = None
        out = run_check("x", lambda a: base_errors(self.root, s, "main", resolved, never), []).render(False)
        self.assertEqual(out, "FAIL x.input: " + self.WANT % ("None", self.root) + "\n")

    # Owner Q-R16R-1 (a): an int too large for a file descriptor makes samefile raise OverflowError
    HUGE = ((2 ** 100, str(2 ** 100)), (-(2 ** 100), str(-(2 ** 100))))

    def test_a_huge_int_is_one_samefile_rejects_with_overflow(self):  # Q-R16R-1 (a)
        for bad, _ in self.HUGE:
            with self.subTest(root=repr(bad)), self.assertRaises(OverflowError):
                os.path.samefile(bad, self.root)

    def test_a_huge_int_store_root_is_a_gate_error(self):  # Q-R16R-1 (a)
        self.seed()
        for bad, shown in self.HUGE:
            with self.subTest(root=repr(bad)):
                s = Store(self.root, "decision", self.cfg)
                s.root = bad
                with self.no_history_reads(), self.assertRaises(GateError) as e:
                    base_errors(self.root, s, "main", resolved, never)
                self.assertEqual(str(e.exception), self.WANT % (shown, self.root))

    def test_a_huge_int_store_root_through_run_check(self):  # Q-R16R-1 (a)
        for bad, shown in self.HUGE:
            with self.subTest(root=repr(bad)):
                s = Store(self.root, "decision", self.cfg)
                s.root = bad
                out = run_check("x", lambda a: base_errors(self.root, s, "main", resolved, never), []).render(False)
                self.assertEqual(out, "FAIL x.input: " + self.WANT % (shown, self.root) + "\n")


OLD = "decision/1"  # exempt literal (Global Constraints "Test fixtures"): these tests are about an old version
ANSWER = {"class": "scope", "answer": "Yes", "rule": "Keep X."}


def v1(id_, status="answered", **more):
    return {**row(id_, status, **ANSWER, **more), "schema": OLD}


def v2(id_, status="answered", **more):
    return row(id_, status, **ANSWER, **more)


class BaseErrorsMigrateTest(GitCase):
    """Task 2a.1: rows at the merge base and at the tip of base are migrated before comparing (F-1, spec 7.2);
    a tree row equal to its base row before or after migration is unchanged (owner Q-2a1-2 (a))."""

    def mb_errs(self, base_row, tree_row, is_resolved=decisions.is_resolved, may_delete=never):
        """``base_row`` committed on main, ``tree_row`` in the working tree (None: deleted); base HEAD."""
        self.put(A, base_row)
        commit_all(self.root, "base")
        if tree_row is None:
            os.remove(os.path.join(self.root, DIR, A + ".yml"))
        else:
            self.put(A, tree_row)
        return base_errors(self.root, self.store, "HEAD", is_resolved, may_delete)

    def tip_errs(self, tip_row, branch_row):
        """main and feature fork from the fixture commit; main adds ``tip_row`` as C, feature ``branch_row``."""
        self.fork()
        self.put(C, branch_row)
        commit_all(self.root, "feature adds C")
        git(self.root, "checkout", "-q", "main")
        self.put(C, tip_row)
        commit_all(self.root, "main adds C")
        git(self.root, "checkout", "-q", "feature")
        return base_errors(self.root, self.store, "main", decisions.is_resolved, never)

    def test_fixture_tags(self):  # the fixtures are what the rows name: an old and the current version
        self.assertEqual(migrations.migrate("decision", v1(A)), v2(A))
        self.assertNotEqual(OLD, DTAG)

    def test_migrated_answered_record_is_not_immutable(self):  # B1, F-1
        errs = self.mb_errs(v1(A), v2(A))
        self.assertFalse(any(s.startswith("immutable.") for s, _ in errs))
        self.assertEqual(errs, [])
        self.assertEqual(self.mb_errs(v1(A, "withdrawn"), v2(A, "withdrawn")), [])

    def test_migrated_and_edited_record_is_immutable(self):  # B2
        errs = self.mb_errs(v1(A), {**v2(A), "answer": "No"})
        self.assertIn("immutable." + A, [s for s, _ in errs])
        self.assertEqual(errs, [("immutable." + A, "resolved records are immutable; record the change as a new "
                                 "decision with supersedes: " + A)])

    def test_migrated_with_overrides_added_is_immutable(self):  # B3, spec 7.2
        self.assertEqual([s for s, _ in self.mb_errs(v1(A), {**v2(A), "overrides": "SD-R2"})], ["immutable." + A])

    def test_unmigrated_edited_record_is_immutable(self):  # B2: a change without migration is still a change
        self.assertEqual([s for s, _ in self.mb_errs(v1(A), {**v1(A), "answer": "No"})], ["immutable." + A])

    def test_open_record_changed_is_not_immutable(self):  # B4
        self.assertEqual(self.mb_errs(v1(A, "open"), {**v2(A, "open"), "answer": "No"}), [])

    def test_malformed_base_tag_compared_as_it_stands(self):  # B5: unmigratable, fail closed
        bad = {**v1(A), "schema": "decision/01"}
        cases = (("changed", {**bad, "answer": "No"}, ["immutable." + A]),
                 ("tag only", {**bad, "schema": DTAG}, ["immutable." + A]),
                 ("unchanged", bad, []))
        for name, tree, want in cases:
            with self.subTest(name):
                self.assertEqual([s for s, _ in self.mb_errs(bad, tree)], want)

    def test_unmigrated_tree_row_equal_to_base_is_unchanged(self):  # B6, B9; owner Q-2a1-2 (a)
        with self.subTest("merge-base"):
            errs_mb = self.mb_errs(v1(A), v1(A))
            self.assertFalse(any(s.startswith("immutable.") for s, _ in errs_mb))
            self.assertEqual(errs_mb, [])
        with self.subTest("tip"):
            errs_tip = self.tip_errs(v2(C), v1(C))
            self.assertFalse(any(s.startswith("collision.") for s, _ in errs_tip))
            self.assertEqual(errs_tip, [])

    def test_migrated_tip_row_is_no_collision(self):  # B7
        errs = self.tip_errs(v1(C), v2(C))
        self.assertFalse(any(s.startswith("collision.") for s, _ in errs))
        self.assertEqual(errs, [])

    def test_collision_after_migration(self):  # B8: a real difference is a collision whatever the versions
        for name, tip, branch in (("v1 tip", v1(C, note="main"), v2(C, note="branch")),
                                  ("v2 tip", v2(C, note="main"), v1(C, note="branch")),
                                  ("both v2", v2(C, note="main"), v2(C, note="branch"))):
            with self.subTest(name):
                errs = self.tip_errs(tip, branch)
                self.assertEqual(errs, [("collision." + C, "id %s already exists on main; mint a new id" % C)])
                git(self.root, "checkout", "-q", "main")
                git(self.root, "reset", "-q", "--hard", "HEAD~1")
                git(self.root, "branch", "-q", "-D", "feature")

    def test_deleted_gets_unmigrated_base_row(self):  # B10
        seen = []

        def spy(r):
            seen.append(r)
            return False
        errs = self.mb_errs(v1(A), None, may_delete=spy)
        self.assertEqual(seen, [v1(A)])
        self.assertEqual(errs, [("deleted." + A, "%s/%s.yml exists on HEAD; records on the base branch are never "
                                 "deleted" % (DIR, A))])

    def test_is_resolved_gets_migrated_base_row(self):  # B11
        seen = []

        def spy(r):
            seen.append(r)
            return decisions.is_resolved(r)
        self.assertEqual(self.mb_errs(v1(A), {**v2(A), "answer": "No"}, is_resolved=spy),
                         [("immutable." + A, "resolved records are immutable; record the change as a new decision "
                           "with supersedes: " + A)])
        self.assertEqual(seen, [v2(A)])

    def test_finding_store_migrates_with_its_own_kind(self):  # B12
        fstore = Store(self.root, "finding", self.cfg)
        ftag = "finding/%d" % migrations.current_version("finding")
        closed = {"schema": ftag, "id": FID, "status": "closed"}
        self.put(FID, closed, rel=FDIR)
        commit_all(self.root, "finding")
        fres = lambda r: r["status"] in ("closed", "merged")
        self.assertEqual(base_errors(self.root, fstore, "HEAD", fres, never), [])
        self.put(FID, {**closed, "status": "merged"}, rel=FDIR)
        self.assertEqual([s for s, _ in base_errors(self.root, fstore, "HEAD", fres, never)], ["immutable." + FID])
        # a step registered for findings is applied to finding rows (the store's kind, not a fixed one)
        cur = migrations.current_version("finding")

        def step(r):
            return {**r, "schema": "finding/%d" % (cur + 1)}
        real = migrations.current_version
        with mock.patch.dict(migrations.MIGRATIONS, {("finding", cur): step}), \
                mock.patch.object(migrations, "current_version",
                                  side_effect=lambda k: cur + 1 if k == "finding" else real(k)):
            self.put(FID, {**closed, "schema": "finding/%d" % (cur + 1)}, rel=FDIR)
            self.assertEqual(base_errors(self.root, fstore, "HEAD", fres, never), [])
            self.put(FID, {**closed, "schema": "finding/%d" % (cur + 1), "status": "merged"}, rel=FDIR)
            self.assertEqual([s for s, _ in base_errors(self.root, fstore, "HEAD", fres, never)],
                             ["immutable." + FID])

    def test_finding_kind_on_every_migrate_call(self):  # B12: tree rows and tip rows migrate with the store's kind
        fstore = Store(self.root, "finding", self.cfg)
        cur = migrations.current_version("finding")
        old = {"schema": "finding/%d" % cur, "id": FID, "status": "closed"}
        new = {**old, "schema": "finding/%d" % (cur + 1)}
        fres = lambda r: r["status"] in ("closed", "merged")
        real = migrations.current_version

        def run(base):
            with mock.patch.dict(migrations.MIGRATIONS, {("finding", cur): lambda r: {**r, "schema": new["schema"]}}), \
                    mock.patch.object(migrations, "current_version",
                                      side_effect=lambda k: cur + 1 if k == "finding" else real(k)):
                return base_errors(self.root, fstore, base, fres, never)
        self.put(FID, new, rel=FDIR)
        commit_all(self.root, "finding at the new version")
        self.put(FID, old, rel=FDIR)  # merge base: the tree row is older than the base row
        self.assertEqual(run("HEAD"), [])
        self.put(FID, new, rel=FDIR)
        self.fork()
        for name, tip, branch in (("tip old", old, new), ("tip new", new, old)):
            with self.subTest(name):
                self.put(FID2, {**branch, "id": FID2}, rel=FDIR)
                commit_all(self.root, "feature adds FID2")
                git(self.root, "checkout", "-q", "main")
                self.put(FID2, {**tip, "id": FID2}, rel=FDIR)
                commit_all(self.root, "main adds FID2")
                git(self.root, "checkout", "-q", "feature")
                self.assertEqual(run("main"), [])
                git(self.root, "reset", "-q", "--hard", "HEAD~1")
                git(self.root, "checkout", "-q", "main")
                git(self.root, "reset", "-q", "--hard", "HEAD~1")
                git(self.root, "checkout", "-q", "feature")

    def test_code_point_whose_category_changed(self):  # PC1-U: U+1F6DC is Cn in Unicode 13 (3.9), So in 15.1 (3.13)
        ch = "\U0001F6DC"
        cases = (("migrated, same text", v2(A, note=ch), []),
                 ("unmigrated, same text", v1(A, note=ch), []),
                 ("migrated, other code point", v2(A, note="\U0001F6DD"), ["immutable." + A]))
        for name, tree, want in cases:
            with self.subTest(name):
                self.assertEqual([s for s, _ in self.mb_errs(v1(A, note=ch), tree)], want)

    def test_signature_and_order(self):  # B13, L1: signature unchanged; root and store-root checks first
        self.assertEqual(list(inspect.signature(base_errors).parameters),
                         ["root", "store", "base", "is_resolved", "may_delete"])
        self.put(A, v1(A))
        commit_all(self.root, "base")
        sub = os.path.join(self.root, "pkg")
        os.mkdir(sub)
        foreign = Store(self.clone(), "decision", self.cfg)
        with mock.patch.object(migrations, "migrate", side_effect=AssertionError("migrate called")):
            with self.assertRaises(GateError) as e:
                base_errors(sub, self.store, "HEAD", decisions.is_resolved, never)
            self.assertEqual(str(e.exception), TOP)
            with self.assertRaises(GateError) as e:
                base_errors(self.root, foreign, "HEAD", decisions.is_resolved, never)
            self.assertIn("is not the root given", str(e.exception))
            with self.assertRaisesRegex(AssertionError, "migrate called"):  # reached once both checks pass
                base_errors(self.root, self.store, "HEAD", decisions.is_resolved, never)

    def clone(self):
        dest = os.path.join(self.tmp, "clone")
        git(self.tmp, "clone", "-q", "--", self.root, dest)
        return dest

    def test_schema_error_from_migrate_passes_through(self):  # B14
        self.put(A, v1(A))
        commit_all(self.root, "base")
        broken = os.path.join(self.tmp, "schemas")
        os.mkdir(broken)
        with open(os.path.join(broken, "decision.yml"), "w", encoding="utf-8") as fh:
            fh.write("version: [\n")
        with mock.patch.object(schema, "SCHEMAS_DIR", broken):
            with self.assertRaises(schema.SchemaError):
                base_errors(self.root, self.store, "HEAD", decisions.is_resolved, never)


class RowChangedMigrateTest(GitIsolatedTestCase):
    """Store fix round 1 F1 (Q-2a1s-1 (a)): ``_row_changed`` compares rows as ``base_errors`` does, after
    migrating both sides with the store's kind; driven through ``gate_register.main`` with a finding step
    patched in (no finding step exists yet)."""
    LINE = "FAIL register.evidence.%s: evidence.0: src/x.py is not a tracked regular file"

    def setUp(self):
        super().setUp()
        from tests import test_gate_register as tgr
        self.tgr = tgr
        self.cur = migrations.current_version("finding")
        self.old = "finding/%d" % self.cur
        self.new = "finding/%d" % (self.cur + 1)

    def patched(self):
        real = migrations.current_version
        stack = contextlib.ExitStack()
        stack.enter_context(mock.patch.dict(migrations.MIGRATIONS,
                                            {("finding", self.cur): lambda r: {**r, "schema": self.new}}))
        stack.enter_context(mock.patch.object(migrations, "current_version",
                                              side_effect=lambda k: self.cur + 1 if k == "finding" else real(k)))
        return stack

    def evidence(self, name, base_row, tree_row):
        """``base_row`` (a closed finding citing src/x.py) on main; on the branch src/x.py is removed and the
        row is ``tree_row``. The ``register.evidence`` lines of the gate, run with the finding step."""
        tgr = self.tgr
        work = os.path.join(self.tmp, name)
        os.mkdir(work)
        root = make_repo(work)
        write_record(root, tgr.fpath(tgr.F), base_row)
        write_record(root, "src/x.py", "x")
        commit_all(root, "fixture")
        git(root, "checkout", "-q", "-b", "feat")
        git(root, "rm", "-q", "src/x.py")
        write_record(root, tgr.fpath(tgr.F), tree_row)
        commit_all(root, "branch")
        with self.patched():
            out, _ = tgr.run_argv(["--root", root])
        return [ln for ln in out.splitlines() if ln.startswith("FAIL register.evidence.")]

    def test_migrated_but_equal_finding_is_not_changed(self):  # F1 (a)
        row = self.tgr.frow(self.tgr.F, "closed")
        cases = (("migrated", self.old, {**row, "schema": self.new}),
                 ("unmigrated-equal", self.old, {**row, "schema": self.old}),
                 ("tree-older", self.new, {**row, "schema": self.old}))
        for name, base_tag, tree in cases:
            with self.subTest(name):
                self.assertEqual(self.evidence(name, {**row, "schema": base_tag}, tree), [])

    def test_migrated_and_edited_finding_is_changed(self):  # F1 (b)
        row = self.tgr.frow(self.tgr.F, "closed")
        for name, tree in (("migrated-edited", {**row, "schema": self.new, "class": "other"}),
                           ("migrated-type-only", {**row, "schema": self.new, "review_round": True})):
            with self.subTest(name):
                base = {**row, "review_round": 1} if name == "migrated-type-only" else row
                self.assertEqual(self.evidence(name, {**base, "schema": self.old}, tree),
                                 [self.LINE % self.tgr.F])

    def test_invariants_of_the_replaced_comparison(self):  # I1-I5, through the helper as gate_register calls it
        r = {"schema": self.old, "id": FID, "status": "closed", "n": 1}
        f = FDIR + "/%s.yml" % FID
        at = {f: r}
        with self.patched():
            for name, rec, want in (
                    ("I1 missing at the merge base", Record(FID, r, f), True),
                    ("I2 identical", Record(FID, dict(r), f), False),
                    ("I3 a field changed", Record(FID, {**r, "n": 2}, f), True),
                    ("I4 renamed", Record(FID, r, FDIR + "/y.yml"), True),
                    ("I5 type-strict", Record(FID, {**r, "n": True}, f), True)):
                with self.subTest(name):
                    got = store_mod._row_changed(rec, {} if name.startswith("I1") else at, "finding")
                    self.assertIs(got, want)
