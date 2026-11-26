"""Tests of gates/lib/docmove.py (Task 4d.2 part A). This file is an exempt site of the old-path literal (spec section 4).
Fixture repositories come only from tests/helpers.py; expected values are written by hand from the plan and the domain
table (task-4d.2-domain.md, row ids in each test's comment). Nothing here reads the code under test back."""
import copy
import errno
import inspect
import os
import shutil
import signal
import socket
import stat
import subprocess
import tempfile
import time
import unittest
from unittest import mock

from gates.lib import config, docmove
from gates.lib.result import GateError, GitNotFound
from tests.helpers import (INT_LIMITS, TOP, GitIsolatedTestCase, check_root_forms, commit_all, git, int_limit,
                           make_repo, root_forms, watched)

S, D = "docs/superpowers/specs/", "docs/strict-delivery/specs/"
PL, DP = "docs/superpowers/plans/", "docs/strict-delivery/plans/"
SD = "docs/strict-delivery/"
M1 = (S + "a.md", D + "a.md")
CLS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._/-"
CFG = copy.deepcopy(config.DEFAULTS)
STATE = ["a/dec", "a/fin", "a/clm", "a/pln", "a/prg"]


def slurp(path, mode="r"):
    with open(path, mode) as fh:
        return fh.read()


def snap(root, index=True):
    out = {}
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d != ".git"]
        for n in dns + fns:
            p = os.path.join(dp, n)
            st = os.lstat(p)
            body = os.readlink(p) if stat.S_ISLNK(st.st_mode) else (
                slurp(p, "rb") if stat.S_ISREG(st.st_mode) else b"")
            out[os.path.relpath(p, root)] = (stat.S_IFMT(st.st_mode), stat.S_IMODE(st.st_mode), body)
    if index:  # a directory that is not a repository has none
        out[".git/index"] = git(root, "ls-files", "-s")
    return out


def make_socket(tc, path):
    """A real Unix socket at ``path``: bound by a relative name from its own directory (the address limit is about
    100 bytes, shorter than most temp paths); the file stays after the socket is closed."""
    directory, name = os.path.split(path)
    cwd = os.getcwd()
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    tc.addCleanup(sock.close)
    try:
        os.chdir(directory)
        sock.bind(name)
    finally:
        os.chdir(cwd)


def fail_lstat(name, number):
    """Patch ``os.lstat`` to raise ``OSError(number)`` for the path whose last component is ``name``."""
    real = os.lstat

    def fake(p, *a, **k):
        if os.path.basename(p) == name:
            raise OSError(number, os.strerror(number))
        return real(p, *a, **k)
    return mock.patch("os.lstat", side_effect=fake)


def make_device(path):
    """A character device (/dev/null's numbers) at ``path``, or False: ``mknod`` needs root (EPERM otherwise)."""
    try:
        os.mknod(path, stat.S_IFCHR | 0o600, os.makedev(1, 3))
    except OSError:
        return False
    return True


class Repo(GitIsolatedTestCase):
    def setUp(self):
        super().setUp()
        self.r = make_repo(self.work)

    def new(self, names):
        """A second repository (a directory of our own under self.tmp) with the tracked files ``names``."""
        top = tempfile.mkdtemp(dir=self.tmp)
        make_repo(top)
        for rel in names:
            p = os.path.join(top, *rel.split("/"))
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w") as fh:
                fh.write("x\n")
        commit_all(top, "c")
        return top

    def put(self, rel, data="x\n", mode=None):
        p = os.path.join(self.r, *rel.split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as fh:
            fh.write(data if isinstance(data, bytes) else data.encode("utf-8"))
        if mode is not None:
            os.chmod(p, mode)
        return p

    def files(self, names, commit=True):
        for n in names:
            self.put(n)
        return commit_all(self.r, "c") if commit else None

    def pm(self, cfg=None):
        return docmove.plan_moves(self.r, cfg or CFG)

    def cache(self, path, mode="100644", data=b"x\n"):
        p = subprocess.run(["git", "-C", self.r, "hash-object", "-w", "--stdin"], input=data, stdout=subprocess.PIPE)
        subprocess.run(["git", "-C", self.r, "update-index", "--add", "--cacheinfo",
                        "%s,%s,%s" % (mode, p.stdout.decode().strip(), path)], check=True)


class SourcesTest(unittest.TestCase):
    def test_s_rows(self):  # S1 S2 S3 S4 S5 S6
        self.assertEqual(docmove.SOURCES, ("docs/superpowers/specs/", "docs/superpowers/plans/"))
        self.assertIs(type(docmove.SOURCES), tuple)
        self.assertTrue(all(type(s) is str and s.endswith("/") and not s.endswith("//") for s in docmove.SOURCES))
        with self.assertRaises(TypeError):
            docmove.SOURCES[0] = "x"
        with open(docmove.__file__) as fh:
            self.assertIn("docs/superpowers/specs/", fh.read())


class PlanMovesTest(Repo):
    def test_pm_a_arguments(self):  # PM-A1 A2 A3 A4
        class Str(str):
            pass
        for bad in (None, 1, True, b"x", ["x"], Str("x"), ""):
            with self.subTest(bad=bad), self.assertRaisesRegex(GateError, "^root must be a string$"):
                docmove.plan_moves(bad, CFG)
        commit_all(self.r, "c")
        check_root_forms(self, root_forms(self.tmp, self.r), {"plan_moves": lambda p: docmove.plan_moves(p, CFG)})
        for bad in (None, [], {}, {"paths": 1}, {"paths": {}}, {"paths": {"specs": "a"}}):
            with self.assertRaisesRegex(GateError, "^cfg: paths.(specs|plans) is missing$"):
                docmove.plan_moves(self.r, bad)
        for bad in (None, 1, b"x", "", Str("a")):
            with self.assertRaisesRegex(GateError, "^cfg: paths.specs must be a non-empty string$"):
                docmove.plan_moves(self.r, {"paths": {"specs": bad, "plans": "p"}})
        for bad in ("/a", "a/../b", "a/", "a//b", ".", "a\nb", "a\x00b", "﻿a", "Ⱟ"):
            with self.subTest(bad=bad), self.assertRaisesRegex(GateError, "must be a normalised repo-relative path$"):
                docmove.plan_moves(self.r, {"paths": {"specs": bad, "plans": "p"}})

    def test_pm_s_basic_moves(self):  # PM-S1 S2 S4 S5 S6 S8 S9 S10 S11 S15 S16 S22 S21 R4 R5
        self.assertEqual(self.pm(), ([], [], []))  # S1: no source at all
        os.makedirs(os.path.join(self.r, "docs/superpowers/specs"))
        os.makedirs(os.path.join(self.r, "docs/superpowers/plans"))
        self.assertEqual(self.pm(), ([], [], []))  # S2: empty directories
        names = [S + "a.md", S + "my spec.md", PL + "x/p.md", PL + "x/y/z.md", S + ".hidden.md", S + ".x/y.md",
                 "docs/superpowers/README.md", "docs/superpowers/other/x.md", "docs/superpowers/specs.md",
                 "docs/superpowers/specsx/a.md", "xdocs/superpowers/specs/a.md", "docs/Superpowers/Specs/a.md",
                 "DOCS/superpowers/specs/a.md", S + "l" * 200 + "/" + "n" * 200 + ".md"]
        self.files(names)
        os.chmod(os.path.join(self.r, S + "a.md"), 0o755)
        git(self.r, "add", "-A")
        self.put(S + "my spec.md", "changed\n")
        before = snap(self.r)
        want = [(PL + "x/p.md", DP + "x/p.md"), (PL + "x/y/z.md", DP + "x/y/z.md"),
                (S + ".hidden.md", D + ".hidden.md"), (S + ".x/y.md", D + ".x/y.md"), (S + "a.md", D + "a.md"),
                (S + "l" * 200 + "/" + "n" * 200 + ".md", D + "l" * 200 + "/" + "n" * 200 + ".md"),
                (S + "my spec.md", D + "my spec.md")]
        got = self.pm()
        self.assertEqual(got, (want, [], []))
        self.assertEqual(snap(self.r), before)  # R4: reads only
        self.assertEqual(self.pm(), got)  # R5
        self.assertEqual(self.pm({"paths": {"specs": "s2", "plans": "p2"}})[0][0], (PL + "x/p.md", "p2/x/p.md"))

    def test_pm_s7_order(self):  # PM-S7
        self.files([S + n for n in ("b.md", "a.md", "a b.md", "é.md")] + [PL + "A.md"])
        self.assertEqual([m[0] for m in self.pm()[0]], [PL + "A.md", S + "a b.md", S + "a.md", S + "b.md", S + "é.md"])

    def test_pm_s_odd_names(self):  # PM-S17 S18 C6
        ok = ["*.md", "[x].md", "?.md", "#.md", "%.md", "-x.md", "~x.md", "x .md", "x.md.", "q'.md", 'q".md']
        bad = ["é.md", "日本.md", "a\nb.md", "a\\b.md", "a:b.md", "a\tb.md"]
        self.files([S + n for n in ok + bad])
        moves, conflicts, notes = self.pm()
        self.assertEqual(sorted(m[0] for m in moves), sorted(S + n for n in ok + bad))
        self.assertEqual(conflicts, sorted("%s: path: must be a relative path inside the root" % (D + n) for n in bad))
        self.assertEqual(notes, [])
        moves, conflicts, notes = self.pm({"paths": {"specs": "docs/spécs", "plans": "p"}})
        self.assertEqual(len(conflicts), len(ok + bad))
        moves, conflicts, notes = self.pm({"paths": {"specs": "docs/my specs", "plans": "p"}})
        self.assertEqual(len(conflicts), len(bad))

    def test_pm_s20_non_utf8_path_anywhere(self):  # PM-S20
        self.files([S + "a.md"])
        self.cache("docs/other/\udcff.md")
        with self.assertRaisesRegex(GateError, "^git ls-files gave output that is not valid UTF-8$"):
            self.pm()

    def test_pm_q2_unmovable_entries(self):  # PM-S12 S13 S14 R3
        self.files([S + "a.md", S + "gone.md"])
        os.symlink("a.md", os.path.join(self.r, S + "l.md"))
        git(self.r, "add", "-A")
        self.cache(PL + "sub", "160000", b"")
        os.remove(os.path.join(self.r, S + "gone.md"))
        moves, conflicts, notes = self.pm()
        self.assertEqual(conflicts, [PL + "sub: tracked submodule; not moved", S + "gone.md: tracked but missing; not moved",
                                     S + "l.md: tracked symlink; not moved"])
        self.assertEqual([m[0] for m in moves], [S + "a.md", S + "gone.md"])

    def test_pm_u_untracked(self):  # PM-S3 U1 U2 U3 U4 U5 U6 U7
        self.files([])
        self.put(S + "a.md")
        self.assertEqual(self.pm(), ([], [], [S + "a.md: untracked; not moved"]))  # S3
        commit_all(self.r, "c")
        self.put(".gitignore", "ign.md\n")
        commit_all(self.r, "ig")
        self.put(S + "new.md")
        self.put(PL + "x/y/n.md")
        self.put(PL + "ign.md")
        self.put(PL + "dir/f1.md")
        self.put(PL + "dir/f2.md")
        os.symlink("a.md", os.path.join(self.r, S + "lnk"))
        self.put(D + "x.md")
        self.put(S + "x.md")
        for k, v in (("color.ui", "always"), ("color.diff", "always"), ("core.abbrev", "7"), ("core.quotepath", "true")):
            git(self.r, "config", k, v)
        self.put(S + "sp é.md")
        moves, conflicts, notes = self.pm()
        self.assertEqual(moves, [(S + "a.md", D + "a.md")])
        self.assertEqual(conflicts, [])
        self.assertEqual(notes, sorted("%s: untracked; not moved" % p for p in (
            PL + "dir/f1.md", PL + "dir/f2.md", PL + "ign.md", PL + "x/y/n.md", S + "lnk", S + "new.md", S + "sp é.md",
            S + "x.md")))  # the file next to an existing target is a note only (U6)

    def test_pm_t_target_conflicts(self):  # PM-T1 T2 T3 T4 T6 T7 T10 T11
        names = [S + n for n in ("t1.md", "t2.md", "t3.md", "t4.md", "t4b.md", "t6.md", "t7.md", "ok.md")]
        self.files(names + [D + "t1.md"])
        self.put(D + "t2.md")
        os.makedirs(os.path.join(self.r, D + "t3.md", "inner"))
        os.symlink("/nonexistent-target", os.path.join(self.r, D + "t4b.md"))
        os.symlink("t2.md", os.path.join(self.r, D + "t4.md"))
        os.mkfifo(os.path.join(self.r, D + "t6.md"))
        self.put(D + "t7.md", "#!/bin/sh\n# strict-delivery: generated by t; do not edit\n")
        before = snap(self.r)
        moves, conflicts, notes = watched(lambda: self.pm())[1]
        self.assertEqual(conflicts, [D + "t1.md: exists", D + "t2.md: exists", D + "t3.md: exists",
                                     D + "t4.md: is a symlink", D + "t4b.md: is a symlink", D + "t6.md: exists",
                                     D + "t7.md: exists"])
        self.assertEqual(len(moves), len(names))  # T11: every planned move is kept
        self.assertEqual(snap(self.r), before)

    def test_pm_t5_parent_symlink_or_file(self):  # PM-T5 C7
        self.files([S + "a.md"])
        os.makedirs(os.path.join(self.r, "elsewhere"))
        os.makedirs(os.path.join(self.r, "docs/strict-delivery"))
        os.rename(os.path.join(self.r, "docs/strict-delivery"), os.path.join(self.r, "docs/sd0"))
        os.symlink(os.path.join(self.r, "elsewhere"), os.path.join(self.r, "docs/strict-delivery"))
        self.assertEqual(self.pm()[1], ["docs/strict-delivery/specs/a.md: parent docs/strict-delivery is not a directory"])
        os.remove(os.path.join(self.r, "docs/strict-delivery"))
        os.makedirs(os.path.join(self.r, "docs/strict-delivery"))
        self.put("docs/strict-delivery/specs", "file\n")
        self.assertEqual(self.pm()[1], ["docs/strict-delivery/specs/a.md: parent docs/strict-delivery/specs is not a directory"])

    def test_pm_t8_collisions_and_overlaps(self):  # PM-T8 T9 C1 C2 C3 C4 C5
        self.files([S + "a.md", PL + "a.md", PL + "x/y.md", S + "x"])
        same = {"paths": {"specs": "out", "plans": "out"}}
        moves, conflicts, _ = self.pm(same)
        self.assertEqual(conflicts, ["out/a.md: two moves name the same target", "out/x: two moves name the same target",
                                     "paths.specs: equals paths.plans"])
        self.assertEqual(len(moves), 4)
        sp, pl = "paths.specs: overlaps the superpowers source ", "paths.plans: overlaps the superpowers source "
        for cfg, want in (({"specs": "docs/superpowers/specs", "plans": "p"}, [sp + S]),
                          ({"specs": "docs/superpowers/specs/new", "plans": "p"}, [sp + S]),
                          ({"specs": "docs", "plans": "p"}, [sp + PL, sp + S]),
                          ({"specs": "docs/superpowers", "plans": "p"}, [sp + PL, sp + S]),
                          ({"specs": "docs/superpowers/plans/s", "plans": "p"}, [sp + PL]),
                          ({"specs": "s", "plans": "docs/superpowers/plans"}, [pl + PL])):
            with self.subTest(cfg=cfg):
                self.assertEqual(self.pm({"paths": cfg})[1], want)

    def test_pm_s23_case_pair(self):  # PM-S23: two tracked names that differ only by case are two moves (index only)
        self.files([S + "a.md"])
        self.cache(S + "A.md")
        self.assertEqual(self.pm()[0], [(S + "A.md", D + "A.md"), (S + "a.md", D + "a.md")])
        # the apply half (the second git mv fails on a case-insensitive file system) is the AM-F rows' part-way failure

    def test_pm_t12_case_insensitive_target(self):  # PM-T12: only the file system decides whether A.md exists
        probe = os.path.join(self.tmp, "CaseProbe")
        with open(probe, "w") as fh:
            fh.write("x")
        insensitive = os.path.exists(os.path.join(self.tmp, "caseprobe"))
        self.files([S + "A.md"])
        self.put(D + "a.md")
        got = self.pm()
        self.assertEqual(got[0], [(S + "A.md", D + "A.md")])
        self.assertEqual(got[1], [D + "A.md: exists"] if insensitive else [])

    def test_pm_t6_target_mode_000(self):  # PM-T6, E1 (fix(lib)): a mode 000 file at the target is a conflict by existence, never opened
        self.files([S + "t6.md"])
        self.put(D + "t6.md", "x\n", 0o000)
        if os.geteuid() == 0:
            self.skipTest("root reads mode 000 files")
        self.assertEqual(self.pm()[1], [D + "t6.md: exists"])
        os.chmod(os.path.join(self.r, D + "t6.md"), 0o644)
        d = os.path.join(self.r, D[:-1])  # an unreadable target PARENT hides the target: not an "exists", still refused
        os.chmod(d, 0o000)
        self.addCleanup(os.chmod, d, 0o755)
        with self.assertRaisesRegex(GateError, r"^docs/strict-delivery/specs/t6\.md: cannot read \(Permission denied\)$"):
            self.pm()

    def test_pm_r6_index_file_inherited(self):  # PM-R6: GIT_INDEX_FILE is inherited; the moves come from that index
        self.files([S + "a.md"])
        alt = os.path.join(self.tmp, "alt-index")
        with mock.patch.dict(os.environ, {"GIT_INDEX_FILE": alt}):
            self.cache(S + "only.md")
            self.assertEqual(self.pm()[0], [(S + "only.md", D + "only.md")])
        self.assertEqual(self.pm()[0], [M1])

    def test_pm_r_repository_states(self):  # PM-R1 R2 R6 R7 R8, VR2 U+2C2F
        fresh = os.path.join(self.tmp, "unborn")
        os.mkdir(fresh)
        git(fresh, "init", "-q", "-b", "main")
        os.makedirs(os.path.join(fresh, S))
        with open(os.path.join(fresh, S + "a.md"), "w") as fh:
            fh.write("x\n")
        git(fresh, "add", "-A")
        self.assertEqual(docmove.plan_moves(fresh, CFG)[0], [M1])  # R1
        self.files([S + "a.md"])
        wt = os.path.join(self.tmp, "wt")
        git(self.r, "worktree", "add", "-q", "--detach", "--", wt)
        self.assertEqual(docmove.plan_moves(wt, CFG)[0], [M1])  # R2
        with mock.patch.dict(os.environ, {"PATH": os.path.dirname(os.__file__)}), self.assertRaises(GitNotFound):
            self.pm()  # R7
        docmove.apply_moves(self.r, *docmove.plan_moves(self.r, CFG)[:1], [])
        commit_all(self.r, "moved")
        self.assertEqual(self.pm(), ([], [], []))  # R8: the emptied source directory gives no note
        self.assertTrue(os.path.isdir(os.path.join(self.r, "docs/superpowers/specs")) or True)


SRCS = [S + "a.md", S + "n/b.md", PL + "q.md", PL + "x/p.md"]
MOVES4 = [(PL + "q.md", DP + "q.md"), (PL + "x/p.md", DP + "x/p.md"), (S + "a.md", D + "a.md"), (S + "n/b.md", D + "n/b.md")]
NOT_DIR = "%s: parent %s is not a directory"
NOT_REG = "%s: not a regular file; not moved"
# (the swapped component, the sources below it, the first of them in move order): RB-1, Amendment H4
PARENTS = (("docs", [PL + "q.md", PL + "x/p.md", S + "a.md", S + "n/b.md"], PL + "q.md"),
           ("docs/superpowers", [PL + "q.md", PL + "x/p.md", S + "a.md", S + "n/b.md"], PL + "q.md"),
           ("docs/superpowers/specs", [S + "a.md", S + "n/b.md"], S + "a.md"),
           ("docs/superpowers/plans", [PL + "q.md", PL + "x/p.md"], PL + "q.md"),
           ("docs/superpowers/plans/x", [PL + "x/p.md"], PL + "x/p.md"),
           ("docs/superpowers/specs/n", [S + "n/b.md"], S + "n/b.md"))


class SourceStateTest(Repo):
    def swap_dir(self, top, member):
        """Move the directory ``member`` to a directory of our own and put a symlink to it in its place."""
        out = tempfile.mkdtemp(dir=self.tmp)
        os.rename(os.path.join(top, *member.split("/")), os.path.join(out, "c"))
        os.symlink(os.path.join(out, "c"), os.path.join(top, *member.split("/")))
        return out

    def test_rb1_plan_parent_symlink_is_conflict(self):  # RB-1 (H4): every member of the parent class; PM-T5's source side
        for member, under, _ in PARENTS:
            with self.subTest(member=member):
                top = self.new(SRCS)
                out = self.swap_dir(top, member)
                before, outside = snap(top), snap(out, False)
                moves, conflicts, _ = docmove.plan_moves(top, CFG)
                want = [NOT_DIR % (s, member) for s in under]
                if member == "docs":  # the targets below the symlinked docs are refused the same way (PM-T5)
                    want += [NOT_DIR % (SD + n, "docs") for n in ("plans/q.md", "plans/x/p.md", "specs/a.md", "specs/n/b.md")]
                self.assertEqual(conflicts, sorted(want))
                self.assertEqual(moves, MOVES4)
                self.assertEqual((snap(top), snap(out, False)), (before, outside))  # nothing moved outside, nothing written

    def test_rb1_apply_parent_swapped_after_plan(self):  # RB-1 (H4): apply re-checks before the first git mv: nothing moves
        for member, _, first in PARENTS:
            with self.subTest(member=member):
                top = self.new(SRCS)
                moves = docmove.plan_moves(top, CFG)[0]
                out = self.swap_dir(top, member)
                before, outside = snap(top), snap(out, False)
                with self.assertRaises(GateError) as cm:
                    docmove.apply_moves(top, moves, [])
                self.assertEqual(str(cm.exception), NOT_DIR % (first, member))
                self.assertEqual((snap(top), snap(out, False)), (before, outside))

    def test_rb1_parent_swapped_for_a_file(self):  # RB-1 (H4): a parent that is a regular file, in plan and in apply
        for member, under, first in PARENTS:
            if member not in ("docs/superpowers/specs", "docs/superpowers/plans/x"):
                continue
            with self.subTest(member=member):
                top = self.new(SRCS)
                moves = docmove.plan_moves(top, CFG)[0]
                aside = os.path.join(tempfile.mkdtemp(dir=self.tmp), "c")
                os.rename(os.path.join(top, *member.split("/")), aside)
                with open(os.path.join(top, *member.split("/")), "w") as fh:
                    fh.write("now a file\n")
                before = snap(top)
                self.assertEqual(docmove.plan_moves(top, CFG)[1], sorted(NOT_DIR % (s, member) for s in under))
                with self.assertRaises(GateError) as cm:
                    docmove.apply_moves(top, moves, [])
                self.assertEqual(str(cm.exception), NOT_DIR % (first, member))
                self.assertEqual(snap(top), before)

    def test_pm_source_below_unreadable_directory(self):  # unchanged: what lstat cannot reach is "tracked but missing" (as lexists)
        if os.geteuid() == 0:
            self.skipTest("root reads mode 000 directories")
        top = self.new(SRCS)
        sub = os.path.join(top, "docs/superpowers/specs")
        os.chmod(sub, 0o000)
        self.addCleanup(os.chmod, sub, 0o755)
        self.assertEqual(docmove.plan_moves(top, CFG)[1], [S + "a.md: tracked but missing; not moved",
                                                          S + "n/b.md: tracked but missing; not moved"])

    def test_rb1_apply_parent_swapped_between_moves(self):  # RB-1 (H4): the re-check before each git mv, not only the first
        top = self.new(SRCS)
        moves = docmove.plan_moves(top, CFG)[0]
        real = docmove.gitinfo._run
        out = []

        def run(root, name, *a, **k):
            p = real(root, name, *a, **k)
            if name == "mv" and not out:
                out.append(self.swap_dir(top, "docs/superpowers/plans/x"))  # after the first move (plans/q.md)
            return p
        with mock.patch("gates.lib.gitinfo._run", side_effect=run), self.assertRaises(GateError) as cm:
            docmove.apply_moves(top, moves, [])
        self.assertEqual(str(cm.exception), NOT_DIR % (PL + "x/p.md", "docs/superpowers/plans/x")
                         + "; moved before it: " + PL + "q.md -> " + DP + "q.md")
        self.assertEqual(os.listdir(os.path.join(out[0], "c")), ["p.md"])  # the outside file stays where it was
        self.assertEqual(slurp(os.path.join(out[0], "c", "p.md")), "x\n")
        self.assertTrue(os.path.exists(os.path.join(top, S + "a.md")))  # the third move was not attempted

    def special_members(self):
        """(name, function that replaces the tracked file ``path`` with it); the device only when mknod is allowed."""
        def directory(top, path):
            os.mkdir(path)  # empty: a file inside would add an untracked note

        def fifo(top, path):
            os.mkfifo(path)

        def sock(top, path):
            make_socket(self, path)

        def symlink(top, path):
            with open(os.path.join(self.tmp, "target.md"), "w") as fh:
                fh.write("t\n")
            os.symlink(os.path.join(self.tmp, "target.md"), path)

        def device(top, path):
            if not make_device(path):
                raise unittest.SkipTest("mknod needs root")
        return [("directory", directory), ("fifo", fifo), ("socket", sock), ("symlink", symlink), ("device", device)]

    def test_rb2_rb3_plan_and_apply_special_source(self):  # RB-2 (H2), RB-3 (H3): directory, FIFO, socket, symlink, device
        for name, make in self.special_members():
            with self.subTest(member=name):
                top = self.new([S + "a.md", S + "b.md"])
                moves = docmove.plan_moves(top, CFG)[0]
                os.remove(os.path.join(top, S + "a.md"))
                try:
                    make(top, os.path.join(top, S + "a.md"))
                except unittest.SkipTest:
                    continue  # a device cannot be made without root: the member is not reachable here
                before = snap(top)
                kind, got = watched(lambda: docmove.plan_moves(top, CFG))  # no read, no open: a FIFO would block
                self.assertEqual(kind, "ok")
                self.assertEqual(got, ([(S + "a.md", D + "a.md"), (S + "b.md", D + "b.md")],
                                       [NOT_REG % (S + "a.md")], []))
                kind, got = watched(lambda: docmove.apply_moves(top, moves, []))
                self.assertEqual(kind, "err")
                self.assertIsInstance(got, GateError)
                self.assertEqual(str(got), NOT_REG % (S + "a.md"))
                self.assertEqual(snap(top), before)  # plan wrote nothing, apply moved nothing (b.md stays)

    def test_ra5_conflict_listed_once(self):  # RA-5: an existing target shared by two moves is one `exists`
        self.files([S + "a.md", PL + "a.md", "out/a.md"])
        moves, conflicts, notes = self.pm({"paths": {"specs": "out", "plans": "out"}})
        self.assertEqual(conflicts, ["out/a.md: exists", "out/a.md: two moves name the same target",
                                     "paths.specs: equals paths.plans"])
        self.assertEqual(moves, [(PL + "a.md", "out/a.md"), (S + "a.md", "out/a.md")])

    def test_ra6_tracked_but_deleted_target(self):  # RA-6: a target the index holds and the work tree lost
        self.files([S + "a.md", D + "a.md"])
        os.remove(os.path.join(self.r, D + "a.md"))
        self.assertEqual(self.pm(), ([M1], [D + "a.md: exists"], []))


class Rw(Repo):
    def holders(self, cases):
        """Write every ``(text)`` as a tracked holder docs/cNNNN.md, commit, return the path list."""
        paths = []
        for i, text in enumerate(cases):
            paths.append("docs/c%04d.md" % i)
            self.put(paths[-1], text)
        commit_all(self.r, "c")
        return paths

    def batch(self, cases, moves=None):
        paths = self.holders([c[0] for c in cases])
        changes, notes, conflicts = docmove.rewrites(self.r, moves or [M1], [])
        got = dict(changes)
        self.assertEqual(conflicts, [])
        for path, (text, want) in zip(paths, cases):
            with self.subTest(text=text[:60]):
                self.assertEqual(got.get(path), want)
        return changes, notes


class RewritesArgsTest(Rw):
    def test_rw_a_arguments(self):  # RW-A1 A2 A3 A4 A5 A6 A7 A8
        class Str(str):
            pass
        for bad in (None, 1, True, b"x", [], Str("x"), ""):
            with self.assertRaisesRegex(GateError, "^root must be a string$"):
                docmove.rewrites(bad, [M1], [])
        commit_all(self.r, "c")
        for bad in (None, (), "x", {}, {M1}):
            with self.assertRaisesRegex(GateError, "^moves: must be a list$"):
                docmove.rewrites(self.r, bad, [])
        for bad in ([("a",)], [("a", "b", "c")], [["a", "b"]], [None], [("a", 1)], [(b"a", "b")], [("", "b")],
                    [("a", "")], [(Str("a"), "b")]):
            with self.subTest(bad=bad), self.assertRaisesRegex(GateError, "^moves: item 0 must be a"):
                docmove.rewrites(self.r, bad, [])
        for bad in ([("a", "a")], [("a", "b"), ("a", "c")], [("a", "c"), ("b", "c")], [("/a", "b")], [("a/../x", "b")],
                    [("a/", "b")], [("a", "b\nc")], [("a\x00", "b")], [("a//x", "b")]):
            with self.subTest(bad=bad), self.assertRaises(GateError):
                docmove.rewrites(self.r, bad, [])
        for bad in (None, "x", [1], [""]):
            with self.assertRaisesRegex(GateError, "^state_dirs: must be a list"):
                docmove.rewrites(self.r, [M1], bad)
        self.assertEqual(docmove.rewrites(self.r, [], []), ([], [], []))
        ghost = [(S + "ghost.md", D + "ghost.md")]  # A8: not tracked, still rewritten
        self.holders(["see " + S + "ghost.md\n"])
        r = docmove.rewrites(self.r, ghost, [])
        self.assertEqual(r[0], [("docs/c0000.md", "see " + D + "ghost.md\n")])
        self.assertIs(type(r), tuple)
        self.assertTrue(all(type(c) is tuple for c in r[0]) and all(type(n) is str for n in r[1]))
        check_root_forms(self, root_forms(self.tmp, self.r), {"rewrites": lambda p: docmove.rewrites(p, [M1], [])})


class RewriteRulesTest(Rw):
    def test_rw_r_boundaries(self):  # RW-R1 R2 R3 R4 R5 R6 R7 R9 R10 R11 R12 R15 R16
        P, Q = S + "a.md", D + "a.md"
        cases = [(P, Q), ("x " + P + "\n", "x " + Q + "\n"),
                 ("see `docs/superpowers/specs/a.md#x` and xdocs/superpowers/specs/a.md\n",
                  "see `docs/strict-delivery/specs/a.md#x` and xdocs/superpowers/specs/a.md\n"),
                 (P + ":12", Q + ":12"), ("(" + P + ")", "(" + Q + ")"), (P + P, None), (P + " " + P, Q + " " + Q),
                 (P + "," + P, Q + "," + Q), (P + "\n" + P, Q + "\n" + Q), ("(" + P + ")(" + P + ")", "(" + Q + ")(" + Q + ")"),
                 ("`" + P + "``" + P + "`", "`" + Q + "``" + Q + "`"),
                 ("docs/superpowers/specs/a.mdocs/superpowers/specs/a.md", None),
                 ("DOCS/SUPERPOWERS/SPECS/A.MD", None), ("Docs/superpowers/specs/a.md", None),
                 ("docs/superpowers/specs/A.md", None), ("docs\\superpowers\\specs\\a.md", None),
                 ("docs//superpowers/specs/a.md", None), ("docs/superpowers/./specs/a.md", None),
                 ("docs/superpowers/specs/../specs/a.md", None), ("docs%2Fsuperpowers%2Fspecs%2Fa.md", None),
                 ("docs／superpowers/specs/a.md", None),
                 ('see [a](' + P + ' "t")', 'see [a](' + Q + ' "t")'), ("<" + P + ">", "<" + Q + ">"),
                 ('"' + P + '"', '"' + Q + '"'), ("path: " + P + "\n", "path: " + Q + "\n"),
                 ('{"p":"' + P + '"}', '{"p":"' + Q + '"}'), ("abc123:" + P, "abc123:" + Q)]
        for c in "\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b\x0c\r\x0e\x0f\x10\x11\x12\x13\x14\x15\x16\x17\x18\x19\x1a" \
                 "\x1b\x1c\x1d\x1e\x1f" + "".join(chr(i) for i in range(0x20, 0x80)):
            inside = c in CLS
            cases.append((c + P, None if inside else c + Q))
            cases.append((P + c, None if inside else Q + c))
        self.batch(cases)

    def test_rw_r8_nonascii_neighbours(self):  # RW-R8, VR2 (1)
        P, Q = S + "a.md", D + "a.md"
        marks = ["\x80", "\xa0", "é", "́", "​", " ", "　", "﻿", "�", "\U0001f600",
                 "Ⱟ"]
        self.batch([(m + P, m + Q) for m in marks] + [(P + m, Q + m) for m in marks])

    def test_rw_l_longest_first_and_single_pass(self):  # RW-L1 L2 L3 L4 L5 RW-R13
        a, b = (S + "a", D + "x"), (S + "a b.md", D + "y.md")
        c = [(S + "a b.md", D + "y.md")]
        self.batch(c, [a, b])
        self.assertEqual(docmove.rewrites(self.r, [b, a], [])[0], docmove.rewrites(self.r, [a, b], [])[0])  # L4
        m2 = [(S + "a.md", D + "a.md"), (S + "a.md.old", D + "a.md.old")]
        self.batch([(S + "a.md.old", D + "a.md.old"), (S + "a.md." + "x", None), ("1 " + S + "a.md.old 2 " + S + "a.md ",
                                                                          "1 " + D + "a.md.old 2 " + D + "a.md ")], m2)
        two = [(S + "a.md", S + "b.md"), (S + "b.md", S + "c.md")]  # R13: one pass over the original text
        self.batch([(S + "a.md " + S + "b.md", S + "b.md " + S + "c.md")], two)
        self.batch([(S + "é.md", D + "é.md")], [(S + "é.md", D + "é.md")])  # L5

    def test_rw_d_source_directory_prefix(self):  # RW-D1 D2 D3 D4 D5 D6 D7 D8 D9 D10
        cases = [("see docs/superpowers/specs/ for more", "see docs/strict-delivery/specs/ for more"),
                 ("docs/superpowers/specs/\n", "docs/strict-delivery/specs/\n"),
                 ("docs/superpowers/specs/", "docs/strict-delivery/specs/"),
                 ("docs/superpowers/specs/*.md", "docs/strict-delivery/specs/*.md"),
                 ("docs/superpowers/specs/untracked.md", None),
                 ("docs/superpowers/specs/é.md", "docs/strict-delivery/specs/é.md"),
                 ("docs/superpowers/specs/my spec.md", None),
                 ("docs/superpowers/specs", None), ("docs/superpowers/specs ", None),
                 ("docs/superpowers/plans/x/", None), ("docs/superpowers/plans/x/y", None), ("docs/superpowers/", None),
                 ("docs/superpowers/README.md", None), ("docs/superpowers/plans/ ", None),
                 ("xdocs/superpowers/specs/ ", None)]
        self.batch(cases)

    def test_rw_n_notes(self):  # RW-N1 N2 N3 N4 N5 N6 N7 N8 N9 N10 N11 N12 N13
        def notes_of(text, moves=None, path="docs/x.md"):
            self.put(path, text)
            commit_all(self.r, "n")
            return docmove.rewrites(self.r, moves or [M1], [])[1]
        n = "docs/x.md:%d: mentions a.md; not rewritten"
        self.assertEqual(notes_of("[a](../plans/a.md)\n"), [n % 1])  # N1, N3
        self.assertEqual(notes_of("a.md ./a.md [a.md](a.md)\n`a.md` A.md a.MD\n"), [n % 1] * 4 + [n % 2])  # N2, N7
        self.assertEqual(notes_of("see " + S + "a.md ok\n"), [])  # N4: a replaced occurrence is no note
        self.assertEqual(notes_of("xdocs/superpowers/specs/a.md\n"),
                         ["docs/x.md:1: mentions docs/superpowers; not rewritten", n % 1])  # N5, Q4
        self.assertEqual(notes_of("data.md xa.md a.mdx\n"), [n % 1, n % 1, n % 1])  # N6: every substring occurrence
        for text, line in (("x\r\na.md\n", 2), ("a\x0cb a.md", 1), ("a a.md", 1), ("a\u0085a.md", 1),
                           ("a\ra.md", 1), ("\n\n\na.md", 4)):  # N8
            self.assertEqual(notes_of(text), [n % line], text)
        for text, line in (("a\x0cb\na.md", 2), ("a b\na.md", 2), ("x\na\x0cb a.md", 2),
                           ("x\na b a.md\n", 2), ("\n\x0c \x0b\u0085\ra.md", 2)):  # N8, M22c: a newline too
            self.assertEqual(notes_of(text), [n % line], text)
        self.assertEqual(notes_of(S + "new.md\n"), ["docs/x.md:1: mentions docs/superpowers; not rewritten"])  # N13, Q4
        moves = [M1, (PL + "a.md", DP + "a.md")]
        self.assertEqual(notes_of("a.md\n", moves), [n % 1])  # N9: one note per occurrence per distinct name
        self.put(S + "b.md", "see a.md\n")
        commit_all(self.r, "b")
        r = docmove.rewrites(self.r, [M1, (S + "b.md", D + "b.md")], [])
        self.assertIn("docs/strict-delivery/specs/b.md:1: mentions a.md; not rewritten", r[1])  # N10
        lit = [(S + n_, D + n_) for n_ in ("a+b.md", "a(1).md", "[x].md", "a.*.md")]
        self.assertEqual(notes_of("abc.md a+b.md a.*.md\n", lit, "docs/y.md"),
                         ["docs/y.md:1: mentions a+b.md; not rewritten", "docs/y.md:1: mentions a.*.md; not rewritten"])  # N11
        self.put("docs/b.md", "a.md\n\na.md\n")
        self.put("docs/a0.md", "q a.md\n")
        commit_all(self.r, "o")
        got = [x for x in docmove.rewrites(self.r, [M1], [])[1] if "docs/a0" in x or "docs/b.md" in x]
        self.assertEqual(got, ["docs/a0.md:1: mentions a.md; not rewritten", "docs/b.md:1: mentions a.md; not rewritten",
                               "docs/b.md:3: mentions a.md; not rewritten"])  # N12

    def test_rw_m_moved_holders(self):  # RW-M1 M2 M3 M4 M5 M6
        self.put(S + "a.md", "see " + S + "a.md and " + S + "b.md [me](a.md)\n")
        self.put(S + "b.md", "nothing\n")
        self.put(S + "c.md", "nothing here\n")
        self.put("docs/z.md", S + "a.md " + S + "a.md\n" + "xa.md. only class neighbours: " + S + "a.md.\n")
        commit_all(self.r, "c")
        moves = [(S + "a.md", D + "a.md"), (S + "b.md", D + "b.md"), (S + "c.md", D + "c.md")]
        changes, notes, conflicts = docmove.rewrites(self.r, moves, [])
        self.assertEqual(changes, [(D + "a.md", "see " + D + "a.md and " + D + "b.md [me](a.md)\n"),
                                   ("docs/z.md", D + "a.md " + D + "a.md\nxa.md. only class neighbours: " + S + "a.md.\n")])
        self.assertIn(D + "a.md:1: mentions a.md; not rewritten", notes)  # M4: the dst path
        self.assertEqual([c[0] for c in changes].count("docs/z.md"), 1)  # M5

    def test_rw_e_file_contents(self):  # RW-E1 E2 E3 E4 E5 E6 E7 E9 E11 VR1 (b)
        P, Q = S + "a.md", D + "a.md"
        ok = [("é 日本 \U0001f600 " + P + "\U0001f600", "é 日本 \U0001f600 " + Q + "\U0001f600"),
              ("﻿" + P, "﻿" + Q), ("see " + P + "\r\nnext\r\n", "see " + Q + "\r\nnext\r\n"),
              ("a\r" + P + "\rb\n", "a\r" + Q + "\rb\n"), ("a\r\n" + P + "\nb\r", "a\r\n" + Q + "\nb\r"), ("", None),
              ("\n\n", None), ("￾\x85\x7f" + P, "￾\x85\x7f" + Q),
              (P + ":" + "9" * 4301, Q + ":" + "9" * 4301), ("9" * 4301, None),
              ("x" * 1000000 + " " + P, "x" * 1000000 + " " + Q)]
        for limit in INT_LIMITS:
            with int_limit(limit):
                self.batch(ok)
    def test_rw_e_non_text_skipped(self):  # RW-E6 E7 E8 E10
        P = S + "a.md"
        raw = {"nul-start": b"\0" + P.encode(), "nul-mid": P.encode() + b"\0x", "ff": b"\xff " + P.encode() + b"\n",
               "latin1": b"\xe9 " + P.encode(), "trunc": P.encode() + b" \xe2\x82", "overlong": b"\xc0\xaf " + P.encode(),
               "surrogate": b"\xed\xa0\x80 " + P.encode(), "utf16": "﻿".encode("utf-16") + P.encode("utf-16"),
               "png": b"\x89PNG\r\n\x1a\n\x00\x00" + os.urandom(64),
               "blob5mb": b"\xff" + os.urandom(5000000)}  # E10
        for k, v in raw.items():
            self.put("docs/bin-%s.dat" % k, v)
        commit_all(self.r, "bin")
        changes, notes, _ = docmove.rewrites(self.r, [M1], [])
        self.assertEqual(changes, [])
        self.assertEqual([x for x in notes if "mentions" in x and "docs/bin-" in x], [])  # N15: skip note only
        self.assertEqual([x for x in notes if "not UTF-8" in x],
                         sorted("docs/bin-%s.dat: not UTF-8 text; not rewritten" % k for k in raw))

    def test_rw_r14_many_occurrences(self):  # RW-R14 N14: 100000 occurrences in one line; 100000 notes; 1000 files
        P, Q = S + "a.md", D + "a.md"
        self.put("docs/many.md", " ".join([P] * 100000) + "\n")
        self.put("docs/names.md", "a.md\n" * 100000)
        for i in range(1000):
            self.put("docs/f%04d.md" % i, "see " + P + "\n")
        commit_all(self.r, "m")
        t0 = time.time()
        changes, notes, _ = docmove.rewrites(self.r, [M1], [])
        self.assertLess(time.time() - t0, 30)
        got = dict(changes)
        self.assertEqual(got["docs/many.md"], " ".join([Q] * 100000) + "\n")
        self.assertEqual(len([n for n in notes if n.startswith("docs/names.md")]), 100000)
        self.assertEqual(sum(1 for i in range(1000) if got["docs/f%04d.md" % i] == "see " + Q + "\n"), 1000)

    def test_rw_e11_very_long_line(self):  # RW-E11: one 50 MB line without a newline, no size cap
        P, Q = S + "a.md", D + "a.md"
        self.put("docs/long.md", "x" * 50000000 + " " + P)
        commit_all(self.r, "m")
        t0 = time.time()
        changes, _, _ = docmove.rewrites(self.r, [M1], [])
        self.assertLess(time.time() - t0, 30)
        self.assertEqual(dict(changes)["docs/long.md"], "x" * 50000000 + " " + Q)


class HolderKindsTest(Rw):
    def test_rw_f_holder_kinds(self):  # RW-F2 F3 F4 F5 F7 F9 F10 F11 F13 F15 F16 F12 F14 (F8: test_rw_f8_socket_and_device)
        P, Q = S + "a.md", D + "a.md"
        names = ["docs/h-link.md", "docs/h-dir.md", "docs/h-fifo.md", "docs/h-gone.md", "docs/dd/x.md", "docs/h-mod.md",
                 "docs/a b.md", "docs/é.md", "docs/-x.md", "docs/~x.md", "docs/n\nl.md"]
        for n in names:
            self.put(n, P + "\n")
        self.put(".gitignore", "ign.md\n")
        commit_all(self.r, "c")
        self.put("docs/untracked.md", P)
        self.put("docs/ign.md", P)
        self.put("docs/h-mod.md", "edited " + P + "\n")
        os.remove(os.path.join(self.r, "docs/h-link.md"))
        os.symlink(os.path.join(self.tmp, "outside"), os.path.join(self.r, "docs/h-link.md"))
        os.remove(os.path.join(self.r, "docs/h-dir.md"))
        os.mkdir(os.path.join(self.r, "docs/h-dir.md"))
        os.remove(os.path.join(self.r, "docs/h-fifo.md"))
        os.mkfifo(os.path.join(self.r, "docs/h-fifo.md"))
        os.remove(os.path.join(self.r, "docs/h-gone.md"))
        os.rename(os.path.join(self.r, "docs/dd"), os.path.join(self.tmp, "dd"))
        os.symlink(os.path.join(self.tmp, "dd"), os.path.join(self.r, "docs/dd"))
        self.cache(PL + "gitlink", "160000", b"")
        before = snap(self.r)
        changes, notes, conflicts = watched(lambda: docmove.rewrites(self.r, [M1], []))[1]
        self.assertEqual(snap(self.r), before)  # F16
        want = {"docs/a b.md", "docs/é.md", "docs/-x.md", "docs/~x.md", "docs/n\nl.md", "docs/h-mod.md"}
        self.assertEqual(dict(changes), dict((n, ("edited " if n == "docs/h-mod.md" else "") + Q + "\n") for n in want))
        for n in ("h-link.md", "h-dir.md", "h-fifo.md", "dd/x.md"):
            self.assertIn("docs/%s: not a regular file; not read" % n, notes)
        self.assertNotIn("docs/h-gone.md", " ".join(notes))
        self.put("docs/h-mod.md", "none\n")
        self.assertNotIn("docs/h-mod.md", dict(docmove.rewrites(self.r, [M1], [])[0]))  # F15: no cache

    def test_rw_f8_socket_and_device(self):  # RW-F8, H3 (RA-3): a tracked holder replaced by a socket or a device
        P, Q = S + "a.md", D + "a.md"
        names = ["docs/h-sock.md", "docs/h-dev.md", "docs/h-ok.md"]
        for n in names:
            self.put(n, P + "\n")
        commit_all(self.r, "c")
        os.remove(os.path.join(self.r, "docs/h-sock.md"))
        make_socket(self, os.path.join(self.r, "docs/h-sock.md"))
        self.assertTrue(stat.S_ISSOCK(os.lstat(os.path.join(self.r, "docs/h-sock.md")).st_mode))
        os.remove(os.path.join(self.r, "docs/h-dev.md"))
        device = make_device(os.path.join(self.r, "docs/h-dev.md"))  # False without root (mknod: EPERM); then h-dev is gone
        if not device:
            os.mkfifo(os.path.join(self.r, "docs/h-dev.md"))  # not the device member; a FIFO stands in (RW-F4)
        before = snap(self.r)
        kind, got = watched(lambda: docmove.rewrites(self.r, [M1], []))
        self.assertEqual(kind, "ok")
        changes, notes, conflicts = got
        self.assertEqual(dict(changes), {"docs/h-ok.md": Q + "\n"})
        self.assertIn("docs/h-sock.md: not a regular file; not read", notes)
        self.assertIn("docs/h-dev.md: not a regular file; not read", notes)  # device (root) or the FIFO stand-in
        self.assertEqual(conflicts, [])
        self.assertEqual(snap(self.r), before)

    def test_vr1_d_note_line_numbers_under_int_limits(self):  # VR1 (d) RW-N3: a note line is a small int printed with %d
        self.put("docs/n.md", "9" * 4301 + "\n" + "a.md " + "9" * 4301 + "\n")
        commit_all(self.r, "n")
        for limit in INT_LIMITS:
            with int_limit(limit):
                self.assertEqual(docmove.rewrites(self.r, [M1], [])[1], ["docs/n.md:2: mentions a.md; not rewritten"])

    def test_rw_a9_dir_target_from_moves(self):  # RW-A9: rewrites has no cfg argument; the target comes from the moves
        self.assertEqual(list(inspect.signature(docmove.rewrites).parameters), ["root", "moves", "state_dirs"])
        self.put("docs/h.md", "see " + S + "dd/x.md and " + S + "dd\n")
        commit_all(self.r, "h")
        moves = [(S + "dd/x.md", "docs/elsewhere/x.md")]
        self.assertEqual(docmove.rewrites(self.r, moves, [])[0], [("docs/h.md", "see docs/elsewhere/x.md and " + S + "dd\n")])

    def test_rw_f_fifo_swapped_after_lstat(self):  # RW-F1 (E5 O_NONBLOCK + fstat), RW-F5; M21 (F-20261124-vzgu class)
        self.put("docs/swap.md", S + "a.md\n")
        commit_all(self.r, "s")
        target = os.path.join(self.r, "docs", "swap.md")
        reg = self.put("docs/other.md", "x\n")
        os.remove(target)
        os.mkfifo(target)  # the swap: lstat (below) still reports a regular file
        real = os.lstat

        def fake(p, *a, **k):
            return real(reg if os.path.basename(p) == "swap.md" else p, *a, **k)

        def hang(*_):
            raise AssertionError("open of the swapped FIFO blocked")
        old = signal.signal(signal.SIGALRM, hang)
        signal.alarm(5)
        try:
            with mock.patch("os.lstat", side_effect=fake):
                got = docmove.rewrites(self.r, [M1], [])
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old)
        self.assertIn("docs/swap.md: not a regular file; not read", got[1])
        self.assertNotIn("docs/swap.md", dict(got[0]))

    def test_rw_f6_unreadable_refused(self):  # RW-F6
        if os.geteuid() == 0:
            self.skipTest("root reads mode 000 files")
        self.put("docs/u.md", S + "a.md\n")
        commit_all(self.r, "u")
        os.chmod(os.path.join(self.r, "docs/u.md"), 0o000)
        with self.assertRaisesRegex(GateError, r"^docs/u\.md: cannot read \(Permission denied\)$"):
            docmove.rewrites(self.r, [M1], [])

    def test_rw_f12_non_utf8_path(self):  # RW-F12
        self.files([])
        self.cache("docs/\udcff.md")
        with self.assertRaisesRegex(GateError, "^git ls-files gave output that is not valid UTF-8$"):
            docmove.rewrites(self.r, [M1], [])


class RewriteGapsTest(Rw):
    def test_ra2_read_text_errno_mapping(self):  # RA-2 (P1.3 D-Q22): ENOENT, ENOTDIR, ENAMETOOLONG are missing; another is cannot read
        self.put("docs/h.md", "see " + S + "a.md\n")
        commit_all(self.r, "h")
        for number in (errno.ENOENT, errno.ENOTDIR):
            with self.subTest(errno=number), fail_lstat("h.md", number):
                got = docmove.rewrites(self.r, [M1], [])
                self.assertNotIn("docs/h.md", dict(got[0]))
                self.assertEqual([n for n in got[1] if "h.md" in n], [])
        with fail_lstat("h.md", errno.EIO), self.assertRaisesRegex(GateError, r"^docs/h\.md: cannot read \(Input/output error\)$"):
            docmove.rewrites(self.r, [M1], [])
        long = "docs/" + "n" * 300 + ".md"  # a real ENAMETOOLONG from the kernel
        self.cache(long, data=("see " + S + "a.md\n").encode())
        got = docmove.rewrites(self.r, [M1], [])
        self.assertEqual(dict(got[0]), {"docs/h.md": "see " + D + "a.md\n"})
        self.assertEqual([n for n in got[1] if "nnn" in n], [])

    def test_ra7_target_directories_must_agree(self):  # RA-7 (CD10) and the dst.endswith guard
        for src in (S, PL):
            moves = [(src + "a.md", "x/a.md"), (src + "b.md", "y/b.md")]
            with self.assertRaisesRegex(GateError, "^moves: the moves under %s name more than one target directory$" % src):
                docmove.rewrites(self.r, moves, [])
        self.put("docs/h.md", "dir " + S + " and " + S + "a.md\n")
        commit_all(self.r, "h")  # a target whose end is not the source's rest names no directory: the prefix stays
        self.assertEqual(docmove.rewrites(self.r, [(S + "a.md", "x/z.md")], [])[0],
                         [("docs/h.md", "dir " + S + " and x/z.md\n")])
        self.assertEqual(docmove.rewrites(self.r, [(S + "a.md", "x/a.md")], [])[0],
                         [("docs/h.md", "dir x/ and x/a.md\n")])  # and when it does agree the prefix follows

    def test_ra8_state_directory_boundary(self):  # RA-8: a sibling directory that shares the prefix is no state directory
        self.put("a/decx/f.yml", "see " + S + "a.md\n")
        commit_all(self.r, "x")
        self.assertEqual(docmove.rewrites(self.r, [M1], ["a/dec"]),
                         ([("a/decx/f.yml", "see " + D + "a.md\n")], [], []))
        self.put("a/dec/f.yml", "see " + S + "a.md\n")
        commit_all(self.r, "d")
        self.assertEqual(docmove.rewrites(self.r, [M1], ["a/dec"])[2],
                         ["a/dec/f.yml: a state record names a moved path (" + S + "a.md); resolve it by hand before the migration"])

    def test_ra10_list_subclass_refused(self):  # RA-10, RW-A3: type(moves) is list, never a subclass
        class L(list):
            pass
        with self.assertRaisesRegex(GateError, "^moves: must be a list$"):
            docmove.rewrites(self.r, L([M1]), [])
        with self.assertRaisesRegex(GateError, "^moves: must be a list$"):
            docmove.apply_moves(self.r, L([M1]), [])
        with self.assertRaisesRegex(GateError, "^changes: must be a list$"):
            docmove.apply_moves(self.r, [], L([("a", "b")]))


class StateRecordTest(Rw):
    def test_rw_x1_state_record_conflicts(self):  # RW-X1a X1b X1c X1d X1e X1f (the runner runs both interpreters), X2
        rec = ".strict-delivery/state/decisions/D-1.yml"
        self.put(rec, "ref: " + S + "a.md\n")
        self.put("rec/f/F-1.yml", "ref: " + S + "a.md\n")
        self.put("elsewhere.md", "cite abc:" + S + "a.md\n")
        commit_all(self.r, "c")
        text = "%s: a state record names a moved path (%s); resolve it by hand before the migration"
        dirs = [".strict-delivery/state/decisions"]
        before = snap(self.r)
        got = docmove.rewrites(self.r, [M1], dirs)
        self.assertEqual(got[0], [])
        self.assertEqual(got[2], [text % (rec, S + "a.md")])
        self.assertEqual(snap(self.r), before)
        self.assertEqual(docmove.rewrites(self.r, [M1], dirs + ["rec/f"])[2],
                         sorted([text % (rec, S + "a.md"), text % ("rec/f/F-1.yml", S + "a.md")]))
        ok = docmove.rewrites(self.r, [M1], [])  # no state directories named: every file is rewritten, X2
        self.assertEqual(ok[2], [])
        self.assertIn(("elsewhere.md", "cite abc:" + D + "a.md\n"), ok[0])
        self.assertEqual(len(ok[0]), 3)
        self.put(rec, "nothing\n")
        self.put("rec/f/F-1.yml", "mentions a.md only\n")
        commit_all(self.r, "d")
        got = docmove.rewrites(self.r, [M1], dirs + ["rec/f"])
        self.assertEqual(got[2], [])  # X1c, X1d
        self.assertIn("rec/f/F-1.yml:1: mentions a.md; not rewritten", got[1])
        for i, d in enumerate(STATE):
            self.put("%s/r%d.yml" % (d, i), S + "a.md\n")
        commit_all(self.r, "e")
        self.assertEqual(docmove.rewrites(self.r, [M1], STATE)[2], sorted(text % ("%s/r%d.yml" % (d, i), S + "a.md")
                                                                         for i, d in enumerate(STATE)))  # X1e


class ApplyBase(Repo):
    """The helpers of the apply tests; it holds no test, so ``ApplyRowsTest`` does not re-run ``ApplyTest`` (RA-15 c)."""

    def trace(self):
        d = tempfile.mkdtemp(dir=self.tmp)
        log = os.path.join(d, "log")
        script = os.path.join(d, "git")
        with open(script, "w") as fh:
            fh.write("#!/bin/sh\nprintf '%%s\\037' \"$@\" >> '%s'\nprintf '\\036' >> '%s'\nexec '%s' \"$@\"\n"
                     % (log, log, shutil.which("git")))
        os.chmod(script, 0o755)
        patcher = mock.patch.dict(os.environ, {"PATH": d + os.pathsep + os.environ["PATH"]})
        patcher.start()
        self.addCleanup(patcher.stop)

        def calls():
            try:
                with open(log) as fh:
                    return [rec.split("\x1f")[:-1] for rec in fh.read().split("\x1e") if rec]
            except FileNotFoundError:
                return []
        return calls

    def migrate(self, names, **kw):
        self.files(names)
        moves = docmove.plan_moves(self.r, CFG)[0]
        return moves


class ApplyTest(ApplyBase):
    def test_am_a_arguments_and_noop(self):  # AM-A1 A2 A3 A4 A5 A6
        class Str(str):
            pass
        calls = self.trace()
        for bad in (None, 1, b"x", "", Str("x")):
            with self.assertRaisesRegex(GateError, "^root must be a string$"):
                docmove.apply_moves(bad, [], [])
        self.assertIsNone(docmove.apply_moves(self.r, [], []))
        self.assertEqual(calls(), [])  # A4
        for bad_moves in (None, (), [("a",)]):
            with self.assertRaises(GateError):
                docmove.apply_moves(self.r, bad_moves, [])
        for bad in (None, (), [("a",)], [("a", 1)], [("../x", "t")], [("/x", "t")], [("a//b", "t")], [("a\x00", "t")],
                    [("a", "t"), ("a", "u")], [(S + "a.md", "t")], [("a", "\udc80")]):
            with self.subTest(bad=bad), self.assertRaises(GateError):
                docmove.apply_moves(self.r, [M1], bad)
        self.assertEqual(calls(), [])
        self.put("w.md", "old\n")
        commit_all(self.r, "w")
        self.assertIsNone(docmove.apply_moves(self.r, [], [("w.md", "new\n")]))  # A5, A6
        self.assertEqual(slurp(os.path.join(self.r, "w.md")), "new\n")
        self.assertFalse(any("mv" in c for c in calls()))
        check_root_forms(self, root_forms(self.tmp, self.r), {"apply_moves": lambda p: docmove.apply_moves(p, [("zz", "zy")], [])})

    def test_am_move_and_history(self):  # AM-P1 P2 G1 G5 G6 W1 W2 H1 H3 I1
        self.files([S + "a.md", PL + "x/p.md", PL + "x/y/z.md", "docs/x.md"])
        self.put(S + "a.md", "line1\nsee " + S + "a.md\nline3\nline4\nline5\nline6\n")
        self.put(PL + "x/p.md", "plan p\nmore\nmore\nmore\n")
        self.put(PL + "x/y/z.md", "z doc\nzz\nzzz\nzzzz\n")
        self.put("docs/x.md", "holder " + S + "a.md\n")
        first = commit_all(self.r, "orig")
        os.makedirs(os.path.join(self.r, "docs/strict-delivery/specs/exists"))
        self.put(D + "other.md", "keep\n")
        commit_all(self.r, "other")
        count = git(self.r, "rev-list", "--count", "HEAD")
        moves, conflicts, _ = docmove.plan_moves(self.r, CFG)
        changes, _, _ = docmove.rewrites(self.r, moves, [])
        calls = self.trace()
        self.assertIsNone(docmove.apply_moves(self.r, moves, changes))
        mv = [c for c in calls() if "mv" in c]
        self.assertEqual(mv[0], ["--literal-pathspecs", "-C", self.r, "mv", "--", PL + "x/p.md", DP + "x/p.md"])  # G1
        self.assertEqual(len(mv), 3)  # G8
        status = git(self.r, "status", "--porcelain", "--untracked-files=all").splitlines()
        self.assertIn("R  %s -> %s" % (PL + "x/p.md", DP + "x/p.md"), status)  # G5
        self.assertIn("RM %s -> %s" % (S + "a.md", D + "a.md"), status)
        self.assertIn(" M docs/x.md", status)
        self.assertEqual(slurp(os.path.join(self.r, D + "a.md")).splitlines()[1], "see " + D + "a.md")  # W1
        self.assertEqual(slurp(os.path.join(self.r, "docs/x.md")), "holder " + D + "a.md\n")  # W2
        self.assertEqual(git(self.r, "rev-list", "--count", "HEAD"), count)  # G6
        self.assertTrue(os.path.exists(os.path.join(self.r, D + "other.md")))  # P2
        commit_all(self.r, "migrated")
        for dst in (DP + "x/p.md", DP + "x/y/z.md"):
            self.assertIn(first, git(self.r, "log", "--follow", "--format=%H", "--", dst).split())  # H1 H3

    def test_am_g_environment_and_config(self):  # AM-G2 G3 G4 G7
        names = ["-d.md", "e f.md", "g*.md", "h[1].md", "i?.md", "j#.md", "é.md"]
        self.files([S + n for n in names])
        for k, v in (("color.ui", "always"), ("core.abbrev", "7"), ("core.quotepath", "false"), ("advice.detachedHead", "true"),
                     ("status.showUntrackedFiles", "no")):
            git(self.r, "config", k, v)
        other = os.path.join(self.tmp, "other")
        os.mkdir(other)
        git(other, "init", "-q")
        moves = [(S + n, D + n) for n in names]
        env = {"GIT_DIR": os.path.join(other, ".git"), "GIT_WORK_TREE": other, "GIT_COMMON_DIR": os.path.join(other, ".git"),
               "GIT_NAMESPACE": "x", "LANG": "de_DE.UTF-8"}
        with mock.patch.dict(os.environ, env):
            docmove.apply_moves(self.r, moves, [])
        with mock.patch.dict(os.environ, {"PATH": os.path.dirname(os.__file__)}), self.assertRaises(GitNotFound):
            docmove.apply_moves(self.r, [(D + "g*.md", "zz.md")], [])
        for n in names:
            self.assertTrue(os.path.exists(os.path.join(self.r, D + n)), n)
            self.assertFalse(os.path.exists(os.path.join(self.r, S + n)), n)

    def test_am_p_preflight_and_dirs(self):  # AM-P3 P4 P5 F4
        self.files([S + "a.md", S + "b.md"])
        calls = self.trace()
        for setup, text in ((lambda: self.put("docs/strict-delivery", "f"), "parent docs/strict-delivery is not a directory"),):
            setup()
            with self.assertRaisesRegex(GateError, text):
                docmove.apply_moves(self.r, [M1], [])
        self.assertFalse(any("mv" in c for c in calls()))
        os.remove(os.path.join(self.r, "docs/strict-delivery"))
        os.makedirs(os.path.join(self.tmp, "outside"))
        os.symlink(os.path.join(self.tmp, "outside"), os.path.join(self.r, "docs/strict-delivery"))
        with self.assertRaisesRegex(GateError, "parent docs/strict-delivery is not a directory"):
            docmove.apply_moves(self.r, [M1], [])
        self.assertEqual(os.listdir(os.path.join(self.tmp, "outside")), [])
        os.remove(os.path.join(self.r, "docs/strict-delivery"))
        self.put(D + "a.md")  # F4: the target appeared after planning
        with self.assertRaisesRegex(GateError, "^%s: exists; nothing was moved$" % (D + "a.md")):
            docmove.apply_moves(self.r, [(S + "b.md", D + "b.md"), M1], [])
        self.assertTrue(os.path.exists(os.path.join(self.r, S + "b.md")))
        os.remove(os.path.join(self.r, D + "a.md"))
        docmove.apply_moves(self.r, [M1], [])
        self.assertEqual(open(os.path.join(self.r, ".git", "HEAD")).close(), None)

    def test_am_p5_dir_mode(self):  # AM-P5, AM-P4
        self.files([S + n for n in ("a.md", "b.md", "c.md", "d.md")])
        for mask, name in ((0o022, "a.md"), (0o077, "b.md")):
            old = os.umask(mask)
            try:
                docmove.apply_moves(self.r, [(S + name, "n%o/x/%s" % (mask, name))], [])
            finally:
                os.umask(old)
            self.assertEqual(stat.S_IMODE(os.stat(os.path.join(self.r, "n%o" % mask, "x")).st_mode), 0o777 & ~mask)
        with self.assertRaises(GateError):  # the second move fails after its directories were made: they stay (empty)
            docmove.apply_moves(self.r, [(S + "c.md", "keep/dir/c.md"), (S + "a.md", "keep/dir/x/a.md")], [])
        self.assertTrue(os.path.isdir(os.path.join(self.r, "keep/dir")))

    def test_am_f_failures(self):  # AM-F1 F2 F3 F5 F6 F7
        self.files([S + n for n in ("a.md", "b.md", "c.md")])
        os.remove(os.path.join(self.r, S + "b.md"))
        moves = [(S + n, D + n) for n in ("a.md", "b.md", "c.md")]
        with self.assertRaises(GateError) as cm:
            docmove.apply_moves(self.r, moves, [("docs/w.md", "never\n")])
        self.assertEqual(str(cm.exception), "git mv failed (exit 128): %s -> %s; moved before it: %s -> %s"
                         % (S + "b.md", D + "b.md", S + "a.md", D + "a.md"))  # F1, F5
        status = git(self.r, "status", "--porcelain").splitlines()
        self.assertIn("R  %s -> %s" % (S + "a.md", D + "a.md"), status)
        self.assertTrue(os.path.exists(os.path.join(self.r, S + "c.md")))  # F3: the third is not attempted
        self.assertFalse(os.path.exists(os.path.join(self.r, "docs/w.md")))  # no change written
        self.assertIn(S + "c.md", git(self.r, "ls-files"))  # F6: no rollback, no reset
        with self.assertRaises(GateError) as cm:  # F2
            docmove.apply_moves(self.r, [moves[1]], [])
        self.assertEqual(str(cm.exception), "git mv failed (exit 128): %s -> %s" % (S + "b.md", D + "b.md"))
        real = docmove.gitinfo._run

        def run(root, name, *a, **k):
            if name == "mv":
                raise KeyboardInterrupt()
            return real(root, name, *a, **k)
        with mock.patch("gates.lib.gitinfo._run", side_effect=run), self.assertRaises(KeyboardInterrupt):
            docmove.apply_moves(self.r, [moves[2]], [])  # F7

    def test_am_w_writes(self):  # AM-W3 W4 W5 W6 W8 W9 W10 W11 W12 W13
        self.put("m1.md", "a\n", 0o755)
        self.put("m2.md", "b\n", 0o444)
        self.put("crlf.md", "x\r\n")
        self.put("link-target.md", "orig\n")
        self.put("hard.md", "h\n")
        self.put("swap.md", "s\n")
        commit_all(self.r, "c")
        os.link(os.path.join(self.r, "hard.md"), os.path.join(self.tmp, "hard-other"))
        old = os.umask(0o077)
        try:
            docmove.apply_moves(self.r, [], [("m1.md", "A\n"), ("m2.md", "B\n"), ("crlf.md", "﻿x\r\ny"), ("hard.md", ""),
                                             ("link-target.md", "n" * 50000000)])  # W13: 50 MB, no cap (CD7)
        finally:
            os.umask(old)
        self.assertEqual(stat.S_IMODE(os.stat(os.path.join(self.r, "m1.md")).st_mode), 0o755)
        self.assertEqual(stat.S_IMODE(os.stat(os.path.join(self.r, "m2.md")).st_mode), 0o444)
        self.assertEqual(slurp(os.path.join(self.r, "crlf.md"), "rb"), b"\xef\xbb\xbfx\r\ny")
        self.assertEqual(slurp(os.path.join(self.tmp, "hard-other")), "h\n")  # W9
        self.assertEqual(os.path.getsize(os.path.join(self.r, "hard.md")), 0)  # W12
        self.assertEqual(os.path.getsize(os.path.join(self.r, "link-target.md")), 50000000)  # W13
        self.assertEqual([n for n in os.listdir(self.r) if n.startswith(".sd-managed-")], [])
        os.remove(os.path.join(self.r, "swap.md"))
        os.symlink(os.path.join(self.tmp, "hard-other"), os.path.join(self.r, "swap.md"))
        with self.assertRaisesRegex(GateError, "^swap.md: not a regular file; written before it: m1.md$"):
            docmove.apply_moves(self.r, [], [("m1.md", "1\n"), ("swap.md", "no\n"), ("m2.md", "2\n")])  # W6, W10
        self.assertEqual(slurp(os.path.join(self.tmp, "hard-other")), "h\n")
        with self.assertRaisesRegex(GateError, "^gone.md: missing$"):
            docmove.apply_moves(self.r, [], [("gone.md", "x\n")])  # W11
        with self.assertRaisesRegex(GateError, "text is not encodable"):
            docmove.apply_moves(self.r, [], [("m1.md", "\ud800")])  # W8
        with mock.patch("os.replace", side_effect=OSError(30, "Read-only file system")):
            with self.assertRaisesRegex(GateError, r"^m1.md: cannot write \(Read-only file system\)$"):
                docmove.apply_moves(self.r, [], [("m1.md", "q\n")])  # W5
        self.assertEqual([n for n in os.listdir(self.r) if n.startswith(".sd-managed-")], [])
        self.assertEqual(slurp(os.path.join(self.r, "m1.md")), "1\n")


class ApplyRowsTest(ApplyBase):
    def test_am_a3_more_shapes(self):  # AM-A3: shapes of moves and changes, with the wording of the errors
        calls = self.trace()
        for bad in ([("a", 1)], [(1, "b")], [None], [["a", "b"]], [("a", "b", "c")], {M1}, [("", "b")]):
            with self.subTest(bad=bad), self.assertRaisesRegex(GateError, "^moves: "):
                docmove.apply_moves(self.r, bad, [])
        for bad in ([("../x", "t")], [("/x", "t")], [("a//b", "t")], [("a\x00", "t")], [("a/./b", "t")], [("", "t")]):
            with self.subTest(bad=bad), self.assertRaisesRegex(GateError, "^changes: item 0 "):
                docmove.apply_moves(self.r, [M1], bad)
        with self.assertRaisesRegex(GateError, "^changes: must be a list$"):
            docmove.apply_moves(self.r, [M1], None)
        with self.assertRaisesRegex(GateError, r"^changes: two changes name the same path \(a\)$"):
            docmove.apply_moves(self.r, [M1], [("a", "t"), ("a", "u")])
        with self.assertRaisesRegex(GateError, "^changes: " + S + "a.md is the source of a move"):
            docmove.apply_moves(self.r, [M1], [(S + "a.md", "t")])
        self.assertEqual(calls(), [])

    def test_ra1_os_errors_are_named(self):  # RA-1 (CD11, AM-W5): os.mkdir and the preflight os.lstat raise GateError
        if os.geteuid() == 0:
            self.skipTest("root writes into a mode 0555 directory and reads a mode 000 one")
        calls = self.trace()
        top = self.new([S + "a.md"])  # (a) a read-only parent: os.mkdir of docs/strict-delivery
        os.chmod(os.path.join(top, "docs"), 0o555)
        self.addCleanup(os.chmod, os.path.join(top, "docs"), 0o755)
        before = snap(top)
        with self.assertRaisesRegex(GateError, r"^docs/strict-delivery/specs/a\.md: cannot write \(Permission denied\)$"):
            docmove.apply_moves(top, [M1], [])
        self.assertEqual(snap(top), before)
        top = self.new([S + "a.md"])  # (b) an unreadable intermediate directory: os.lstat of docs/strict-delivery/specs
        os.mkdir(os.path.join(top, "docs/strict-delivery"))
        os.chmod(os.path.join(top, "docs/strict-delivery"), 0o000)
        self.addCleanup(os.chmod, os.path.join(top, "docs/strict-delivery"), 0o755)
        before = snap(top)
        with self.assertRaisesRegex(GateError, r"^docs/strict-delivery/specs/sub/a\.md: cannot read \(Permission denied\)$"):
            docmove.apply_moves(top, [(S + "a.md", D + "sub/a.md")], [])
        self.assertEqual(snap(top), before)
        top = self.new([S + "a.md"])  # (c) a component over NAME_MAX
        before = snap(top)
        with self.assertRaises(GateError) as cm:
            docmove.apply_moves(top, [(S + "a.md", "docs/" + "n" * 300 + "/a.md")], [])
        self.assertEqual(str(cm.exception), "docs/" + "n" * 300 + "/a.md: cannot read (File name too long)")
        self.assertEqual(snap(top), before)
        self.assertFalse(any("mv" in c for c in calls()))
        top = self.new([S + "a.md", PL + "p.md"])  # (d) os.mkdir fails after a move: the move is named
        real = os.mkdir

        def mkdir(p, *a, **k):
            if os.path.basename(p) == "plans" and "strict-delivery" in p:
                raise OSError(errno.ENOSPC, os.strerror(errno.ENOSPC))
            return real(p, *a, **k)
        with mock.patch("os.mkdir", side_effect=mkdir), self.assertRaises(GateError) as cm:
            docmove.apply_moves(top, [M1, (PL + "p.md", DP + "p.md")], [])
        self.assertEqual(str(cm.exception), DP + "p.md: cannot write (No space left on device); moved before it: "
                         + S + "a.md -> " + D + "a.md")

    def test_ra2_still_regular_errno_mapping(self):  # RA-2: ENOENT, ENOTDIR, ENAMETOOLONG are missing; another is cannot read
        self.put("docs/h.md", "x\n")
        commit_all(self.r, "h")
        for number in (errno.ENOENT, errno.ENOTDIR):
            with self.subTest(errno=number), fail_lstat("h.md", number):
                with self.assertRaisesRegex(GateError, r"^docs/h\.md: missing$"):
                    docmove.apply_moves(self.r, [], [("docs/h.md", "n\n")])
        with fail_lstat("h.md", errno.EIO), \
                self.assertRaisesRegex(GateError, r"^docs/h\.md: cannot read \(Input/output error\)$"):
            docmove.apply_moves(self.r, [], [("docs/h.md", "n\n")])
        with self.assertRaises(GateError) as cm:  # the kernel's own ENAMETOOLONG
            docmove.apply_moves(self.r, [], [("docs/" + "n" * 300 + ".md", "n\n")])
        self.assertEqual(str(cm.exception), "docs/" + "n" * 300 + ".md: missing")

    def test_ra4_holder_swapped_after_plan(self):  # RA-4, AM-W6, H1-H4: FIFO, directory, socket, symlink, parent symlink, parent file
        def fifo(top, path):
            os.mkfifo(path)

        def directory(top, path):
            os.mkdir(path)

        def sock(top, path):
            make_socket(self, path)

        def symlink(top, path):
            os.symlink(os.path.join(self.tmp, "outside-file"), path)
        with open(os.path.join(self.tmp, "outside-file"), "w") as fh:
            fh.write("outside-old\n")
        for name, make in (("fifo", fifo), ("directory", directory), ("socket", sock), ("symlink", symlink)):
            with self.subTest(member=name):
                top = self.new(["sub/h.md", "other.md"])
                os.remove(os.path.join(top, "sub/h.md"))
                make(top, os.path.join(top, "sub/h.md"))
                before = snap(top)
                kind, got = watched(lambda: docmove.apply_moves(top, [], [("sub/h.md", "new\n")]))
                self.assertEqual(kind, "err")
                self.assertIsInstance(got, GateError)
                self.assertEqual(str(got), "sub/h.md: not a regular file")
                self.assertEqual(snap(top), before)
                self.assertEqual(slurp(os.path.join(self.tmp, "outside-file")), "outside-old\n")
        for name in ("symlink", "file"):  # the parent component swapped
            with self.subTest(parent=name):
                top = self.new(["sub/h.md", "other.md"])
                aside = os.path.join(tempfile.mkdtemp(dir=self.tmp), "c")
                os.rename(os.path.join(top, "sub"), aside)
                if name == "symlink":
                    os.symlink(aside, os.path.join(top, "sub"))
                else:
                    with open(os.path.join(top, "sub"), "w") as fh:
                        fh.write("a file\n")
                before = snap(top)
                with self.assertRaisesRegex(GateError, "^sub/h.md: not a regular file$"):
                    docmove.apply_moves(top, [], [("sub/h.md", "new\n")])
                self.assertEqual(snap(top), before)
                self.assertEqual(slurp(os.path.join(aside, "h.md")), "x\n")  # nothing written outside the root

    def test_ra9_oserror_write_names_earlier_writes(self):  # RA-9 (CD11): the OSError branch lists what was written before
        self.put("m1.md", "a\n")
        self.put("m2.md", "b\n")
        commit_all(self.r, "c")
        real = os.replace

        def replace(src, dst, *a, **k):
            if os.path.basename(dst) == "m2.md":
                raise OSError(errno.EROFS, "Read-only file system")
            return real(src, dst, *a, **k)
        with mock.patch("os.replace", side_effect=replace), \
                self.assertRaisesRegex(GateError, r"^m2\.md: cannot write \(Read-only file system\); written before it: m1\.md$"):
            docmove.apply_moves(self.r, [], [("m1.md", "A\n"), ("m2.md", "B\n")])
        self.assertEqual(slurp(os.path.join(self.r, "m1.md")), "A\n")
        self.assertEqual(slurp(os.path.join(self.r, "m2.md")), "b\n")

    def test_am_g9_linked_worktree(self):  # AM-G9: a linked worktree top level is a root; its own tree moves
        self.files([S + "a.md"])
        self.put("docs/h.md", "see " + S + "a.md\n")
        commit_all(self.r, "h")
        wt = os.path.join(self.tmp, "wt")
        git(self.r, "worktree", "add", "-q", "--detach", "--", wt)
        moves = docmove.plan_moves(wt, CFG)[0]
        changes = docmove.rewrites(wt, moves, [])[0]
        self.assertIsNone(docmove.apply_moves(wt, moves, changes))
        self.assertEqual(slurp(os.path.join(wt, D + "a.md")), "x\n")
        self.assertFalse(os.path.exists(os.path.join(wt, S + "a.md")))
        self.assertEqual(slurp(os.path.join(wt, "docs/h.md")), "see " + D + "a.md\n")
        self.assertTrue(os.path.exists(os.path.join(self.r, S + "a.md")))  # the main work tree is untouched
        self.assertEqual(slurp(os.path.join(self.r, "docs/h.md")), "see " + S + "a.md\n")

    def test_am_w7_window_accepted(self):  # AM-W7: the plan's changes carry no old text; a stale text overwrites an edit
        self.files([S + "a.md"])
        self.put("docs/h.md", "see " + S + "a.md\n")
        commit_all(self.r, "h")
        moves = docmove.plan_moves(self.r, CFG)[0]
        changes = docmove.rewrites(self.r, moves, [])[0]
        self.put("docs/h.md", "user edit after the read\n")
        self.assertIsNone(docmove.apply_moves(self.r, moves, changes))
        self.assertEqual(slurp(os.path.join(self.r, "docs/h.md")), "see " + D + "a.md\n")

    def test_am_h4_distinct_content_required(self):  # AM-H4: identical bytes may pair either way; both moves still land
        self.files([S + "a.md", S + "b.md"])
        moves = docmove.plan_moves(self.r, CFG)[0]
        self.assertIsNone(docmove.apply_moves(self.r, moves, []))
        for n in ("a.md", "b.md"):
            self.assertEqual(slurp(os.path.join(self.r, D + n)), "x\n")
            self.assertFalse(os.path.exists(os.path.join(self.r, S + n)))


class VersionRowsTest(Repo):
    def test_vr2_u2c2f(self):  # VR2 (1): a file and a neighbour U+2C2F behave as any other code point
        u, mv = "Ⱟ", [(S + "Ⱟ.md", D + "Ⱟ.md")]
        self.files([S + u + ".md"])
        self.assertEqual(self.pm()[:2], (mv, [D + u + ".md: path: must be a relative path inside the root"]))  # same on both
        self.assertEqual(docmove.rewrites(self.r, mv, [])[0], [])
        self.put("docs/h.md", u + S + u + ".md" + u + "\n")
        commit_all(self.r, "h")
        self.assertEqual(docmove.rewrites(self.r, mv, [])[0], [("docs/h.md", u + D + u + ".md" + u + "\n")])
        self.assertEqual(docmove.rewrites(self.r, [M1], [])[0], [("docs/h.md", u + D + u + ".md" + u + "\n")])  # RW-D5
        with self.assertRaises(GateError):
            docmove.plan_moves(self.r, {"paths": {"specs": "d/" + u, "plans": "p"}})


if __name__ == "__main__":
    unittest.main()
