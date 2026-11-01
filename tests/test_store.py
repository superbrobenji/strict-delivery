"""Tests for the one-file-per-record store (gates.lib.store) on real directories and real git repositories.
Expected suffix lists and file contents are written out per scenario, not derived from the code under test."""
import os
import stat
import subprocess
import unittest
from unittest import mock

from gates.lib import config, store as store_mod, yamlsub
from gates.lib.result import GateError
from gates.lib.store import Record, Store, base_errors, store_errors
from tests.helpers import GitIsolatedTestCase, commit_all, git, make_repo, write_record

DIR = ".strict-delivery/state/decisions"
FDIR = ".strict-delivery/state/findings"
A = "DEC-20261031-k3f9"
B = "DEC-20261031-m4n5"
C = "DEC-20261031-p6q7"
FID = "F-20261031-k3f9"
FID2 = "F-20261031-m4n5"


def row(id_, status="open", **more):
    r = {"schema": "decision/1", "id": id_, "status": status}
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
        return root

    def newstore(self, root=None, kind="decision"):
        root = root or self.newroot()
        return root, Store(root, kind, self.cfg)

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
        with self.assertRaises(GateError) as cm:
            s.load()
        self.assertIn(DIR, str(cm.exception))

    def test_parent_that_is_a_file_refused(self):  # S1
        root, s = self.newstore()
        self.writefile(root, "state", "x\n", rel=".strict-delivery")
        with self.assertRaises(GateError) as cm:
            s.load()
        self.assertIn(DIR, str(cm.exception))

    def test_unreadable_dir_refused_naming_it(self):  # S1
        root, s = self.newstore()
        path = self.mkdir(root)
        self.chmod(path, 0)
        with self.assertRaises(GateError) as cm:
            s.load()
        self.assertIn(DIR, str(cm.exception))

    def test_symlinked_dir_refused(self):  # S1 (controller call: a symlinked register directory is refused)
        root, s = self.newstore()
        target = os.path.join(root, "elsewhere")
        os.mkdir(target)
        os.makedirs(os.path.join(root, ".strict-delivery/state"))
        os.symlink(target, os.path.join(root, DIR))
        with self.assertRaises(GateError) as cm:
            s.load()
        self.assertIn(DIR, str(cm.exception))

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
            fh.write(b"\xef\xbb\xbfschema: decision/1\r\nid: " + A.encode() + b"\r\nstatus: open\r\n")
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
                self.assertEqual(os.listdir(root), [])  # not even the register directory

    def test_create_and_replace_refuse_missing_id_and_non_dict(self):  # S4
        root, s = self.newstore()
        for fn in (s.create, s.replace):
            for r in ({}, {"status": "open"}, [], None, "x"):
                with self.assertRaises(GateError):
                    fn(r)
        self.assertEqual(os.listdir(root), [])

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
                b"schema: decision/1\nid: " + A.encode() + b"\nstatus: open\nnote: |\n  two\n  lines\n"
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
        self.assertEqual(os.listdir(root), [])

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
        self.assertEqual(os.listdir(root), [])
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
        for bad in ("a" * 41, "main" + "0" * 41, "-x", "--help", "", None, 7, b"main"):
            with self.subTest(repr(bad)):
                with self.assertRaises(GateError):
                    self.errs(base=bad)

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
            "schema: decision/1\n"
        )
        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        self.assertNotEqual(read_bytes(path), yamlsub.emit(row(B, "resolved", note="x")).encode())
        self.assertEqual(self.errs(), [])

    def test_type_change_with_equal_python_value_is_a_change(self):  # B5: 1 vs true vs 1.0 differ as parsed values
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
        self.put(B, {"schema": "decision/1", "id": B, "status": "resolved"})
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

    def test_same_content_cherry_pick_is_no_collision(self):  # B7
        self.diverge(row(C, note="same"), row(C, note="same"))
        self.assertEqual(self.errs(), [])

    def test_same_parsed_content_different_bytes_is_no_collision(self):  # B7 (parsed comparison, as B5)
        self.diverge(row(C, note="same"), row(C, note="same"))
        with open(os.path.join(self.root, DIR, C + ".yml"), "w", encoding="utf-8", newline="") as fh:
            fh.write("# c\nstatus: open\nnote: 'same'\nid: %s\nschema: decision/1\n" % C)
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
            fh.write(b"\xef\xbb\xbfschema: decision/1\r\nid: " + A.encode() + b"\r\nstatus: resolved\r\n")
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


if __name__ == "__main__":
    unittest.main()
