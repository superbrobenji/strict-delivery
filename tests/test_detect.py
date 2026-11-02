"""Tests for gates.lib.detect: package.json and Makefile detection, through detect() on real files.

Expected values are written out literally. The Makefile verdicts follow the whitelist of Task C1.1
(owner Q-C11rr-3 and the controller rulings under it); detect() never runs make. A comment that
cites make 3.81 for a case is one reproduced with `make -n` in a scratch directory.
"""
import errno
import os
import pathlib
import stat
import tempfile
import unittest
from unittest import mock

from gates.lib import detect as detect_mod
from gates.lib.detect import SLOTS, Detection, Problem, Proposal, detect
from gates.lib.result import GateError


def snapshot(root: str) -> dict:
    """Bytes (files), link target (symlinks) and mtime_ns of every entry under root, read independently of detect."""
    out = {}
    for dirpath, dirnames, filenames in os.walk(root):
        for n in dirnames + filenames:
            p = os.path.join(dirpath, n)
            st = os.lstat(p)
            if stat.S_ISLNK(st.st_mode):
                content = os.readlink(p)
            elif stat.S_ISREG(st.st_mode):
                content = pathlib.Path(p).read_bytes()
            else:
                content = None
            out[os.path.relpath(p, root)] = (stat.S_IFMT(st.st_mode), content, st.st_mtime_ns)
    return out


class Base(unittest.TestCase):
    def setUp(self) -> None:
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.tmp = os.path.realpath(td.name)

    def write(self, name: str, content, root=None) -> str:
        path = os.path.join(root or self.tmp, name)
        data = content if isinstance(content, bytes) else content.encode("utf-8")
        with open(path, "wb") as fh:
            fh.write(data)
        return path

    def rules(self, makefile: str, name: str = "Makefile") -> list:
        """(slot, command, source) of the proposals from a directory holding only this Makefile."""
        with tempfile.TemporaryDirectory() as d:
            self.write(name, makefile, root=d)
            res = detect(d)
        self.assertEqual(res.problems, ())
        return [(p.slot, p.command, p.source) for p in res.proposals]


class RootTests(Base):
    def test_empty_dir_proposes_nothing(self):  # O4
        self.assertEqual(detect(self.tmp), Detection((), ()))

    def test_root_missing_file_or_dangling_symlink(self):  # D1
        f = self.write("afile", "x")
        os.symlink(os.path.join(self.tmp, "gone"), os.path.join(self.tmp, "dangling"))
        for name in ("nope", "afile", "dangling"):
            with self.subTest(name=name):
                root = os.path.join(self.tmp, name)
                with self.assertRaises(GateError) as cm:
                    detect(root)
                self.assertEqual(str(cm.exception), root + ": not a directory")
        self.assertEqual(f, os.path.join(self.tmp, "afile"))

    def test_root_symlink_to_directory_is_read_through(self):  # D2
        real = os.path.join(self.tmp, "real")
        os.mkdir(real)
        self.write("Makefile", "test:\n", root=real)
        link = os.path.join(self.tmp, "link")
        os.symlink(real, link)
        self.assertEqual(detect(link).proposals, (Proposal("test", "make test", "Makefile:1 test"),))

    @unittest.skipIf(os.geteuid() == 0, "root ignores file modes")
    def test_root_unreadable(self):  # D3
        d = os.path.join(self.tmp, "locked")
        os.mkdir(d)
        os.chmod(d, 0)
        self.addCleanup(os.chmod, d, 0o700)
        with self.assertRaises(GateError) as cm:
            detect(d)
        self.assertEqual(str(cm.exception), d + ": cannot read (Permission denied)")

    @unittest.skipIf(os.geteuid() == 0, "root ignores file modes")
    def test_root_readable_but_not_searchable(self):  # D3 (F-C11r-1): mode 0o400 lists but cannot examine any entry
        d = os.path.join(self.tmp, "readonly")
        os.mkdir(d)
        self.write("Makefile", "test:\n", root=d)
        for mode in (0o400, 0o600, 0o000, 0o200):
            with self.subTest(mode=oct(mode)):
                os.chmod(d, mode)
                self.addCleanup(os.chmod, d, 0o700)
                with self.assertRaises(GateError) as cm:
                    detect(d)
                self.assertEqual(str(cm.exception), d + ": cannot read (Permission denied)")
        os.chmod(d, 0o100)  # search without read: listing fails
        with self.assertRaises(GateError) as cm:
            detect(d)
        self.assertEqual(str(cm.exception), d + ": cannot read (Permission denied)")

    def test_root_argument_type(self):  # D4
        self.write("Makefile", "test:\n")
        for value, tname in ((self.tmp.encode(), "bytes"), (pathlib.Path(self.tmp), "PosixPath"), (None, "NoneType"),
                             (0, "int"), (True, "bool")):
            with self.subTest(type=tname):
                with self.assertRaises(GateError) as cm:
                    detect(value)
                self.assertEqual(str(cm.exception), "root must be a str, not " + tname)

    def test_root_str_subclass_refused(self):  # D4
        class S(str):
            pass
        with self.assertRaises(GateError) as cm:
            detect(S(self.tmp))
        self.assertEqual(str(cm.exception), "root must be a str, not S")

    def test_only_files_directly_in_root_are_read(self):  # D5
        sub = os.path.join(self.tmp, "app")
        os.mkdir(sub)
        self.write("package.json", '{"scripts": {"test": "jest"}}', root=sub)
        self.write("Makefile", "test:\n", root=sub)
        self.assertEqual(detect(self.tmp), Detection((), ()))

    def test_no_git_needed(self):  # D5: no .git, and git absent from PATH
        self.write("Makefile", "lint:\n")
        with mock.patch.dict(os.environ, {"PATH": ""}):
            self.assertEqual(detect(self.tmp).proposals, (Proposal("lint", "make lint", "Makefile:1 lint"),))

    def test_slots_constant(self):
        self.assertEqual(SLOTS, ("test", "test_one", "lint", "build"))

    def test_return_types_and_frozen(self):  # O7
        self.write("package.json", '{"scripts": {"test": "a"}}')
        self.write("Makefile", "build:\n")
        d = detect(self.tmp)
        self.assertIs(type(d), Detection)
        self.assertIs(type(d.proposals), tuple)
        self.assertIs(type(d.problems), tuple)
        for p in d.proposals:
            self.assertIs(type(p), Proposal)
            self.assertIn(p.slot, SLOTS)
        with self.assertRaises(Exception):
            d.proposals = ()
        with self.assertRaises(Exception):
            d.proposals[0].slot = "lint"
        with self.assertRaises(Exception):
            Problem("a", "b").reason = "c"


class PackageJsonTests(Base):
    def test_package_json_scripts(self):  # J16, J14, J15
        self.write("package.json", '{"scripts": {"test": "jest", "lint": "eslint .", "build": "tsc", "start": "node x"}}')
        self.assertEqual(detect(self.tmp).proposals, (
            Proposal("test", "npm run test", "package.json scripts.test"),
            Proposal("lint", "npm run lint", "package.json scripts.lint"),
            Proposal("build", "npm run build", "package.json scripts.build")))

    def test_slot_order_not_file_order(self):  # J16
        self.write("package.json", '{"scripts": {"build": "b", "lint": "l", "test": "t"}}')
        self.assertEqual([p.slot for p in detect(self.tmp).proposals], ["test", "lint", "build"])

    def test_lockfiles_do_not_change_command(self):  # J15
        self.write("package.json", '{"scripts": {"test": "jest"}}')
        for lock in ("yarn.lock", "pnpm-lock.yaml"):
            with self.subTest(lock=lock):
                self.write(lock, "")
                self.assertEqual(detect(self.tmp).proposals, (Proposal("test", "npm run test", "package.json scripts.test"),))

    def test_script_value_content_irrelevant(self):  # J13
        self.write("package.json", '{"scripts": {"test": "rm -rf /", "lint": "jest\\n--x"}}')
        self.assertEqual([p.command for p in detect(self.tmp).proposals], ["npm run test", "npm run lint"])

    def test_script_names_exact_only(self):  # J14
        self.write("package.json", '{"scripts": {"Test": "a", "start": "b", "test:unit": "c", "test_one": "d", "LINT": "e"}}')
        self.assertEqual(detect(self.tmp), Detection((), ()))

    def test_absent_scripts_is_nothing(self):  # J10
        self.write("package.json", '{"name": "x"}')
        self.assertEqual(detect(self.tmp), Detection((), ()))

    def test_package_json_absent(self):  # J1
        self.write("other.json", "{}")
        self.assertEqual(detect(self.tmp), Detection((), ()))

    def test_package_json_bad_shapes_are_problems(self):  # J6 J7 J8 J9 J10
        cases = [
            ("empty", "", "not valid JSON"),
            ("open brace", "{", "not valid JSON"),
            ("trailing garbage", '{"scripts": {}} x', "not valid JSON"),
            ("list", "[]", "top level is not an object"),
            ("string", '"x"', "top level is not an object"),
            ("null", "null", "top level is not an object"),
            ("scripts list", '{"scripts": []}', "scripts is not an object"),
            ("scripts null", '{"scripts": null}', "scripts is not an object"),
            ("scripts string", '{"scripts": "x"}', "scripts is not an object"),
            ("not utf-8", b"\xff", "not valid UTF-8"),
            ("not utf-8 in string", b'{"scripts": {"test": "\xff"}}', "not valid UTF-8"),
            ("dup top", '{"a":1,"a":2}', "duplicate key"),
            ("dup top with usable", '{"scripts": {"test": "t"}, "scripts": {}}', "duplicate key"),
            ("dup in scripts", '{"scripts": {"test": "a", "test": "b"}}', "duplicate key"),
            ("dup in unrelated nested", '{"x": {"y": {"k": 1, "k": 2}}, "scripts": {"test": "t"}}', "duplicate key"),
            ("dup in list element", '{"x": [{"k": 1, "k": 2}], "scripts": {"test": "t"}}', "duplicate key"),
            ("deeply nested", "[" * 100000, "not valid JSON"),
        ]
        for label, content, reason in cases:
            with self.subTest(label):
                self.write("package.json", content)
                d = detect(self.tmp)
                self.assertEqual(d, Detection((), (Problem("package.json", reason),)))

    def test_json_constants_nan_infinity_refused(self):  # F-C11r-4 / Q-C11r-5: npm run fails on these
        for lit in ("NaN", "Infinity", "-Infinity"):
            for shape in ('{"scripts": {"test": "t"}, "x": %s}', '{"scripts": {"test": %s}}', '{"x": [%s]}'):
                with self.subTest(lit=lit, shape=shape):
                    self.write("package.json", shape % lit)
                    self.assertEqual(detect(self.tmp), Detection((), (Problem("package.json", "not valid JSON"),)))

    def test_json_huge_numbers_same_on_every_interpreter(self):  # F-C11r-4 / Q-C11r-5
        for label, num in (("5000-digit int", "9" * 5000), ("negative", "-" + "9" * 5000), ("float", "1" * 5000 + ".5"),
                           ("1e999", "1e999"), ("-1e999", "-1e999"), ("plain", "12")):
            with self.subTest(label):
                self.write("package.json", '{"scripts": {"test": "echo ran"}, "x": %s}' % num)
                self.assertEqual(detect(self.tmp).proposals, (Proposal("test", "npm run test", "package.json scripts.test"),))

    def test_number_script_value_is_not_a_script(self):  # J11 with the number hooks: 1, 1.5, 1e999 are not str
        for num in ("1", "1.5", "1e999", "-0"):
            with self.subTest(num):
                self.write("package.json", '{"scripts": {"test": %s}}' % num)
                self.assertEqual(detect(self.tmp), Detection((), ()))

    def test_bom_is_accepted(self):  # J6
        self.write("package.json", b'\xef\xbb\xbf{"scripts": {"build": "tsc"}}')
        self.assertEqual(detect(self.tmp).proposals, (Proposal("build", "npm run build", "package.json scripts.build"),))

    def test_script_value_not_usable_is_skipped(self):  # J11 J12
        for label, raw in (("int", "1"), ("empty", '""'), ("spaces", '"  "'), ("tab newline", '"\\t\\n"'), ("space", '" "'),
                           ("unicode space", '"\\u00a0\\u2003"'), ("null", "null"), ("list", '["a"]'), ("object", '{"a": 1}'),
                           ("bool", "true")):
            with self.subTest(label):
                self.write("package.json", '{"scripts": {"test": %s, "lint": "eslint", "build": "tsc"}}' % raw)
                d = detect(self.tmp)
                self.assertEqual(d, Detection((Proposal("lint", "npm run lint", "package.json scripts.lint"),
                                               Proposal("build", "npm run build", "package.json scripts.build")), ()))

    def test_package_json_symlink_refused(self):  # J2
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        target = self.write("real.json", '{"scripts": {"test": "jest"}}', root=outside.name)
        for label, tgt in (("file", target), ("dir", outside.name), ("dangling", os.path.join(outside.name, "gone"))):
            with self.subTest(label):
                link = os.path.join(self.tmp, "package.json")
                if os.path.lexists(link):
                    os.unlink(link)
                os.symlink(tgt, link)
                self.assertEqual(detect(self.tmp), Detection((), (Problem("package.json", "symlink; not read"),)))

    def test_symlink_target_never_opened(self):  # J2
        os.symlink("/definitely/not/here", os.path.join(self.tmp, "package.json"))
        real_open = os.open
        seen = []

        def spy(path, *a, **k):
            seen.append(path)
            return real_open(path, *a, **k)
        with mock.patch("os.open", spy):
            detect(self.tmp)
        self.assertEqual(seen, [])

    def test_package_json_directory_and_fifo(self):  # J3
        p = os.path.join(self.tmp, "package.json")
        os.mkdir(p)
        self.assertEqual(detect(self.tmp), Detection((), (Problem("package.json", "not a regular file"),)))
        os.rmdir(p)
        os.mkfifo(p)
        self.assertEqual(detect(self.tmp), Detection((), (Problem("package.json", "not a regular file"),)))

    @unittest.skipIf(os.geteuid() == 0, "root ignores file modes")
    def test_package_json_unreadable(self):  # J4
        p = self.write("package.json", '{"scripts": {"test": "t"}}')
        os.chmod(p, 0)
        self.assertEqual(detect(self.tmp), Detection((), (Problem("package.json", "Permission denied"),)))

    def _swap_to_fifo_and_check(self, name: str):
        """lstat sees a regular file while the path is a FIFO: the open must not block, the descriptor must be closed."""
        decoy = self.write("decoy.txt", "x", root=tempfile.mkdtemp(dir=self.tmp))
        fifo = os.path.join(self.tmp, name)
        os.mkfifo(fifo)
        real_lstat = os.lstat

        def fake_lstat(path, *a, **k):
            return real_lstat(decoy if path == fifo else path, *a, **k)
        opened, closed = [], []
        real_open, real_close = os.open, os.close

        def spy_open(path, *a, **k):
            fd = real_open(path, *a, **k)
            opened.append(fd)
            return fd

        def spy_close(fd):
            closed.append(fd)
            return real_close(fd)
        with mock.patch("os.lstat", fake_lstat), mock.patch("os.open", spy_open), mock.patch("os.close", spy_close):
            res = detect(self.tmp)
        self.assertEqual(len(opened), 1)
        self.assertEqual(closed, opened)
        return res

    def test_package_json_swapped_to_fifo(self):  # J5
        self.assertEqual(self._swap_to_fifo_and_check("package.json"),
                         Detection((), (Problem("package.json", "not a regular file"),)))

    def test_read_error_closes_descriptor(self):  # J5, N6: a failure while reading
        self.write("package.json", '{"scripts": {"test": "t"}}')
        opened, closed = [], []
        real_open, real_close = os.open, os.close

        def spy_open(path, *a, **k):
            fd = real_open(path, *a, **k)
            opened.append(fd)
            return fd

        def spy_close(fd):
            closed.append(fd)
            return real_close(fd)

        def boom(fd, n):
            raise OSError(5, "Input/output error")
        with mock.patch("os.open", spy_open), mock.patch("os.close", spy_close), mock.patch("os.read", boom):
            res = detect(self.tmp)
        self.assertEqual(res, Detection((), (Problem("package.json", "Input/output error"),)))
        self.assertEqual(closed, opened)
        self.assertEqual(len(opened), 1)

    def test_large_file_read_in_chunks(self):  # reads past one chunk
        pad = " " * (3 << 16)
        self.write("package.json", '{"scripts": {"test": "t"}' + pad + "}")
        self.assertEqual(detect(self.tmp).proposals, (Proposal("test", "npm run test", "package.json scripts.test"),))


class MakefileNameTests(Base):
    def test_each_name_alone(self):  # N1, R18
        for name in ("GNUmakefile", "makefile", "Makefile"):
            with self.subTest(name=name):
                self.assertEqual(self.rules("x = 1\n\ny:\ntest:\n", name=name), [("test", "make test", name + ":4 test")])

    def test_gnu_make_file_precedence(self):  # N2
        self.write("GNUmakefile", "test:\n")
        self.write("Makefile", "lint:\n")
        self.assertEqual(detect(self.tmp), Detection((Proposal("test", "make test", "GNUmakefile:1 test"),), ()))

    def test_makefile_lower_precedes_upper(self):  # N2 (on a case-insensitive filesystem these are one file; skip then)
        self.write("makefile", "test:\n")
        if os.path.exists(os.path.join(self.tmp, "Makefile")):
            self.skipTest("case-insensitive filesystem")
        self.write("Makefile", "lint:\n")
        self.assertEqual(detect(self.tmp), Detection((Proposal("test", "make test", "makefile:1 test"),), ()))

    def test_spelling_follows_directory_listing(self):  # N3 (real filesystem, whatever its case rule)
        self.write("Makefile", "test:\n")
        self.assertEqual(detect(self.tmp).proposals, (Proposal("test", "make test", "Makefile:1 test"),))

    def test_spelling_on_case_insensitive_filesystem(self):  # N3, simulated: lstat of any case finds the entry
        self.write("Makefile", "test:\n")
        real_lstat = os.lstat

        def ci_lstat(path, *a, **k):
            d, base = os.path.split(path)
            if d == self.tmp:
                for e in os.listdir(d):
                    if e.lower() == base.lower():
                        return real_lstat(os.path.join(d, e), *a, **k)
            return real_lstat(path, *a, **k)
        with mock.patch("os.lstat", ci_lstat):
            res = detect(self.tmp)
        self.assertEqual(res, Detection((Proposal("test", "make test", "Makefile:1 test"),), ()))

    def test_spelling_when_only_lowercase_present_simulated(self):  # N3
        self.write("makefile", "test:\n")
        real_lstat = os.lstat

        def ci_lstat(path, *a, **k):
            d, base = os.path.split(path)
            if d == self.tmp:
                for e in os.listdir(d):
                    if e.lower() == base.lower():
                        return real_lstat(os.path.join(d, e), *a, **k)
            return real_lstat(path, *a, **k)
        with mock.patch("os.lstat", ci_lstat):
            res = detect(self.tmp)
        self.assertEqual(res, Detection((Proposal("test", "make test", "makefile:1 test"),), ()))

    def test_first_existing_makefile_name_not_regular(self):  # N4 N5
        later = "test:\n"
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        real = self.write("real.mk", later, root=outside.name)
        gnu = os.path.join(self.tmp, "GNUmakefile")

        def link_file():
            os.symlink(real, gnu)

        def link_dangling():
            os.symlink(os.path.join(outside.name, "gone"), gnu)

        for label, make, reason in (("symlink to file", link_file, "symlink; not read"),
                                    ("dangling symlink", link_dangling, "symlink; not read"),
                                    ("directory", lambda: os.mkdir(gnu), "not a regular file"),
                                    ("fifo", lambda: os.mkfifo(gnu), "not a regular file")):
            with self.subTest(label):
                make()
                self.write("Makefile", later)
                self.write("makefile", later) if not os.path.exists(os.path.join(self.tmp, "Makefile")) else None
                d = detect(self.tmp)
                self.assertEqual(d, Detection((), (Problem("GNUmakefile", reason),)))
                if os.path.isdir(gnu) and not os.path.islink(gnu):
                    os.rmdir(gnu)
                else:
                    os.unlink(gnu)

    def test_middle_name_not_regular_blocks_later(self):  # N5
        os.mkdir(os.path.join(self.tmp, "makefile"))
        if not os.path.isdir(os.path.join(self.tmp, "Makefile")):
            self.write("Makefile", "test:\n")
        else:
            self.skipTest("case-insensitive filesystem")
        self.assertEqual(detect(self.tmp), Detection((), (Problem("makefile", "not a regular file"),)))

    def test_fifo_never_blocks(self):  # N5
        os.mkfifo(os.path.join(self.tmp, "Makefile"))
        self.assertEqual(detect(self.tmp), Detection((), (Problem("Makefile", "not a regular file"),)))

    @unittest.skipIf(os.geteuid() == 0, "root ignores file modes")
    def test_makefile_unreadable(self):  # N6
        p = self.write("Makefile", "test:\n")
        os.chmod(p, 0)
        self.assertEqual(detect(self.tmp), Detection((), (Problem("Makefile", "Permission denied"),)))

    def test_makefile_swapped_to_fifo(self):  # N6
        self.assertEqual(self._swap("Makefile"), Detection((), (Problem("Makefile", "not a regular file"),)))

    def _swap(self, name):
        return PackageJsonTests._swap_to_fifo_and_check(self, name)

    def test_makefile_not_utf8(self):  # N7
        self.write("Makefile", b"test:\n\t@echo \xff\n")
        self.assertEqual(detect(self.tmp), Detection((), (Problem("Makefile", "not valid UTF-8"),)))

    def test_makefile_utf8_content_ok(self):  # N7
        self.write("Makefile", "# caf\u00e9\ntest:\n\t@echo \u00e9\n")
        self.assertEqual(detect(self.tmp).proposals, (Proposal("test", "make test", "Makefile:2 test"),))

    def test_bom_makefile_first_line_is_unsupported(self):  # U+FEFF is not a blank, comment, assignment or target
        with tempfile.TemporaryDirectory() as d:
            self.write("Makefile", "\ufefftest:\n", root=d)
            self.assertEqual(detect(d), Detection((), (Problem("Makefile", "unsupported line 1: " + MakefileRuleTests.OTHER),)))

    def test_first_makefile_without_slot_targets_hides_later_ones(self):  # N2 (F-C11r-3a): make reads GNUmakefile only
        self.write("GNUmakefile", "all:\n\t@echo a\n")
        self.write("Makefile", "test:\n")
        self.assertEqual(detect(self.tmp), Detection((), ()))
        self.write("makefile", "lint:\n")
        self.assertEqual(detect(self.tmp), Detection((), ()))

    def test_exact_spelling_preferred_over_case_folded(self):  # N3 (F-C11r-3b): both spellings listed
        self.write("GNUmakefile", "test:\n")
        with mock.patch("os.listdir", return_value=["gnumakefile", "GNUmakefile"]):
            self.assertEqual(detect(self.tmp), Detection((Proposal("test", "make test", "GNUmakefile:1 test"),), ()))
        with mock.patch("os.listdir", return_value=["GNUmakefile", "gnumakefile"]):
            self.assertEqual(detect(self.tmp), Detection((Proposal("test", "make test", "GNUmakefile:1 test"),), ()))

    def test_directory_and_fifo_never_opened(self):  # J3 N5 (F-C11r-3c): refused on lstat, before any open
        for name in ("package.json", "Makefile"):
            os.mkfifo(os.path.join(self.tmp, name))
        seen = []
        real_open = os.open

        def spy_fifo(path, *a, **k):
            seen.append(path)
            return real_open(path, *a, **k)
        with mock.patch("os.open", spy_fifo):
            res = detect(self.tmp)
        self.assertEqual(seen, [])
        self.assertEqual(res.problems, (Problem("package.json", "not a regular file"), Problem("Makefile", "not a regular file")))
        for name in ("package.json", "Makefile"):
            p = os.path.join(self.tmp, name)
            os.unlink(p)
            os.mkdir(p)
        seen = []
        real_open = os.open

        def spy(path, *a, **k):
            seen.append(path)
            return real_open(path, *a, **k)
        with mock.patch("os.open", spy):
            detect(self.tmp)
        self.assertEqual(seen, [])

    def test_lstat_failure_is_a_problem(self):  # J4 N6: lstat fails with something other than ENOENT
        self.write("package.json", "{}")
        self.write("GNUmakefile", "test:\n")
        real_lstat = os.lstat

        def deny(path, *a, **k):
            if os.path.basename(path) in ("package.json", "GNUmakefile"):
                raise PermissionError(13, "Permission denied")
            return real_lstat(path, *a, **k)
        with mock.patch("os.lstat", deny):
            res = detect(self.tmp)
        self.assertEqual(res, Detection((), (Problem("package.json", "Permission denied"),
                                             Problem("GNUmakefile", "Permission denied"))))

    def test_makefile_vanishing_after_probe(self):  # N6: present at the probe, gone at the read
        self.write("Makefile", "test:\n")
        real_lstat = os.lstat
        calls = []

        def vanish(path, *a, **k):
            if os.path.basename(path).lower() == "makefile":
                calls.append(path)
                if len(calls) > 1:
                    raise FileNotFoundError(2, "No such file or directory")
            return real_lstat(path, *a, **k)
        with mock.patch("os.lstat", vanish):
            res = detect(self.tmp)
        self.assertEqual(res, Detection((), (Problem("Makefile", "No such file or directory"),)))


class MakefileRuleTests(Base):
    """The Makefile reader is a whitelist (owner Q-C11rr-3): every physical line must be blank, a comment, a
    simple assignment, a rule with literal targets, or a recipe line after a rule. Any other line gives no
    proposals and one Problem naming the first such line."""

    BACKSLASH = "line ends in a backslash"
    RECIPE = "recipe line before the first rule"
    ASSIGN = "assignment after the colon"
    SEMI = "';' after the colon"
    COLON_BS = "backslash after the colon"
    DIRECTIVE = "directive line"
    SECOND_COLON = "second ':' after the colon"
    MIXED = "target defined with both ':' and '::'"
    OTHER = "not a blank, comment, assignment, rule or recipe line"

    def refused(self, makefile, line: int, reason: str, name: str = "Makefile"):
        """detect() on a directory holding only this Makefile: no proposals and exactly the named Problem."""
        with tempfile.TemporaryDirectory() as d:
            self.write(name, makefile, root=d)
            res = detect(d)
        self.assertEqual(res, Detection((), (Problem(name, "unsupported line %d: %s" % (line, reason)),)),
                         msg=repr(makefile))

    # ---- the five accepted forms

    def test_blank_and_whitespace_only_lines(self):  # form 1
        self.assertEqual(self.rules("\n  \n\t\n \t \n\r\ntest:\n\n   \n"), [("test", "make test", "Makefile:6 test")])
        self.assertEqual(self.rules(""), [])
        self.assertEqual(self.rules("\n\n"), [])

    def test_comment_lines(self):  # form 2
        self.assertEqual(self.rules("# test:\n  # test:\n \t# test:\n#\n##build:\n"), [])

    def test_simple_assignments(self):  # form 3: NAME op value, op one of = := ?= +=, spaces around op optional
        for mk in ("test=x\n", "test:=x\n", "test := x\n", "test ?= x\n", "test += x\n", "test?=x\n", "test+=x\n",
                   "  test := x\n", " \ttest := x\n", "_a.b-c9 = $(X) # c\n", "build =\n", "lint= a b c\n", "T = test\n"):
            with self.subTest(mk=mk):
                self.assertEqual(self.rules(mk), [])

    def test_plain_rules(self):  # form 4
        for line in ("test:", "test::", "test: dep", "test : x", "test:dep", "test\t:\tx", "test:\t", "test::dep", "test: a b c",
                     "test: | order", "test: dep # a comment", "test: # only a comment", "test:#c"):
            with self.subTest(line=line):
                self.assertEqual(self.rules(line + "\n\t@echo ran\n"), [("test", "make test", "Makefile:1 test")])

    def test_several_targets_one_line(self):
        self.assertEqual(self.rules("\nbuild test:\n"), [("test", "make test", "Makefile:2 test"),
                                                        ("build", "make build", "Makefile:2 build")])
        self.assertEqual(self.rules("a  \t b lint   c: x\n"), [("lint", "make lint", "Makefile:1 lint")])

    def test_rule_after_leading_blanks(self):  # a leading space (then any blanks) is skipped; a leading tab is a recipe line
        for mk in ("  test:\n", " \ttest:\n", " \t \ttest:\n"):
            with self.subTest(mk=mk):
                self.assertEqual(self.rules(mk), [("test", "make test", "Makefile:1 test")])

    def test_literal_target_characters(self):  # targets are [A-Za-z0-9_.-]+ (owner Q-C11r4-0)
        self.assertEqual(self.rules("out.test.o: a\n.PHONY: test\nsub-dir.lint: x\n_b: y\n.build:\n"), [])
        self.assertEqual(self.rules("a.b.c-d_e9: x\nlint:\n"), [("lint", "make lint", "Makefile:2 lint")])

    def test_names_must_match_exactly(self):
        self.assertEqual(self.rules("tests:\ntest-all:\nretest:\ntest_one:\nTest:\nbuilds:\nsub.test:\n"), [])

    def test_recipe_lines_after_a_rule(self):  # form 5; recipe text is free
        self.assertEqual(self.rules("test:\n\t@echo $(X) a=b; c $$ # d\n\t\n\t# note\n"), [("test", "make test", "Makefile:1 test")])
        self.assertEqual(self.rules("all:\n\ttest:\n\tlint:\n\tdefine D\n\tinclude x\n"), [])

    def test_recipe_context_survives_blank_and_comment_lines(self):
        self.assertEqual(self.rules("all:\n\n# c\n  # d\n\t@echo\n\n\t@echo\ntest:\n"), [("test", "make test", "Makefile:8 test")])

    def test_assignment_ends_recipe_context(self):
        self.refused("all:\nx = 1\n\t@echo\n", 3, self.RECIPE)

    def test_rule_restores_recipe_context(self):
        self.assertEqual(self.rules("all:\nx = 1\nb:\n\t@echo\ntest:\n"), [("test", "make test", "Makefile:5 test")])

    def test_crlf(self):
        self.assertEqual(self.rules("test:\r\n\t@echo ran\r\n"), [("test", "make test", "Makefile:1 test")])
        self.assertEqual(self.rules("x = 1\r\n# c\r\n\r\nlint: a\r\n"), [("lint", "make lint", "Makefile:4 lint")])

    def test_no_final_newline(self):
        self.assertEqual(self.rules("a:\ntest:"), [("test", "make test", "Makefile:2 test")])
        self.assertEqual(self.rules("test: a # c"), [("test", "make test", "Makefile:1 test")])

    def test_duplicate_definition(self):
        self.assertEqual(self.rules("a:\ntest:\nb:\nc:\ntest: x\n\t@echo\n"), [("test", "make test", "Makefile:2 test")])
        self.assertEqual(self.rules("test::\ntest:: x\n"), [("test", "make test", "Makefile:1 test")])

    def test_makefile_rules(self):
        mk = "VAR := test\n.PHONY: test\nbuild test: dep\n\t@echo\nlint:: x\n  check:\n# lint:\n"
        self.assertEqual(self.rules(mk), [("test", "make test", "Makefile:3 test"), ("lint", "make lint", "Makefile:5 lint"),
                                          ("build", "make build", "Makefile:3 build")])

    def test_line_numbers_are_physical_lines(self):
        self.assertEqual(self.rules("\n\n\n# c\n\nx = 1\n\ntest:\n"), [("test", "make test", "Makefile:8 test")])

    def test_directive_word_is_never_a_target(self):  # controller ruling R2 reverses "include: is a plain target"
        for mk, n in (("include:\n", 1), ("export: x\n", 1), ("override:\n", 1), ("test export:\n", 1),
                      ("export test:\n", 1), ("test include: x\n", 1), ("a b private:\n", 1), ("test: include\nvpath:\n", 2)):
            with self.subTest(mk=mk):
                self.refused(mk, n, self.DIRECTIVE)
        self.assertEqual(self.rules("test: include export\n"), [("test", "make test", "Makefile:1 test")])  # words after the colon are text

    def test_target_characters_include_digits_and_upper_case(self):
        self.assertEqual(self.rules("py3.9-Test_2.x1: y\nlint:\n"), [("lint", "make lint", "Makefile:2 lint")])

    def test_special_characters_in_a_trailing_comment_are_ignored(self):  # text after the first `#` is not examined
        self.assertEqual(self.rules("test: dep # a=b; c \\ d\n"), [("test", "make test", "Makefile:1 test")])

    def test_every_directive_word_is_refused_in_every_position(self):  # R2
        for word in ("export", "unexport", "override", "private", "vpath", "include", "-include", "sinclude", "undefine",
                     "define", "endef", "ifdef", "ifndef", "ifeq", "ifneq", "else", "endif"):
            for mk in (word + " test:\n", word + ":\n", word + " :\n", word + " ::\n", word + " :=x\n", word + " ?=x\n",
                       word + " += x\n", word + "=x\n", word + "?=x\n", word + "\n", "  " + word + " x\n", "test " + word + ":\n",
                       word + "\tx\n", word + ":=x\n", word + "+=x\n", word + "!=x\n", "a " + word + " b:\n"):
                with self.subTest(word=word, mk=mk):
                    self.refused(mk, 1, self.DIRECTIVE)

    def test_words_that_only_start_like_a_directive_word_are_ordinary(self):
        self.assertEqual(self.rules("included:\nexports = 1\ndefined: x\ntest-include:\nlint:\n"),
                         [("lint", "make lint", "Makefile:5 lint")])

    def test_blanks_before_the_assignment_operator(self):  # a space or a tab, in any mix
        for mk in ("X\t= 1\n", "X \t:= 1\n", "X\t\t?= 1\n", "X\t+=1\n"):
            with self.subTest(mk=mk):
                self.assertEqual(self.rules(mk + "test:\n"), [("test", "make test", "Makefile:2 test")])

    # ---- refused constructs: no proposals, one Problem, the first such line wins

    def test_refused_define_endef(self):
        for mk, n in (("define D\ntest:\nendef\n", 1), ("test:\ndefine D\nendef\n", 2), ("override define D\n", 1),
                      ("endef\n", 1), ("define D\ntest:\n", 1), ("export define D\n", 1), ("  define D\n", 1)):
            with self.subTest(mk=mk):
                self.refused(mk, n, self.DIRECTIVE)

    def test_refused_conditionals(self):
        for mk, n in (("ifeq (a,b)\ntest:\nendif\n", 1), ("ifneq (a,b)\n", 1), ("ifdef X\n", 1), ("ifndef X\n", 1),
                      ("test:\nelse\n", 2), ("endif\n", 1), ("ifeq ($(A),b)\ntest:\nelse\nlint:\nendif\n", 1),
                      ("else ifdef X\n", 1)):
            with self.subTest(mk=mk):
                self.refused(mk, n, self.DIRECTIVE)

    def test_refused_directives(self):  # the first word is a directive word, whatever follows (controller ruling R2)
        for mk in ("include x.mk\n", "-include x.mk\n", "sinclude x.mk\n", "include test:\n", "-include test:\n",
                   "sinclude test:\n", "export test:\n", "unexport test:\n", "override test:\n", "private test:\n",
                   "undefine test:\n", "include a:b\n", "  export test:\n", "export X\n", "export X = 1\n", "export X := 1\n",
                   "unexport X\n", "override X = 1\n", "private X = 1\n", "vpath %.c src\n", "vpath test: x\n", "undefine X\n",
                   "include:\n", "include :\n", "export: x\n", "override:\n", "vpath :\n", "export ::\n", "-include :\n"):
            with self.subTest(mk=mk):
                self.refused(mk, 1, self.DIRECTIVE)

    def test_refused_target_specific_variables(self):
        for mk in ("test: X = 1\n", "test: X := 1\n", "test: X += 1\n", "test: X ?= 1\n", "test: X != 1\n", "test: a=b\n",
                   "test:: X = 1\n", "test: export X = 1\n", "test: override X = 1\n", "build test: X = 1\n",
                   "test: $(Y:%.c=%.o)\n", "test ::= x\n", "test::=x\n", "test :::= x\n"):
            with self.subTest(mk=mk):
                self.refused(mk, 1, self.ASSIGN)

    def test_refused_other_assignment_operators(self):
        for mk in ("test != x\n", "x !=y\n", "$(X) = 1\n"):
            with self.subTest(mk=mk):
                self.refused(mk, 1, self.OTHER)

    def test_refused_semicolon_after_colon(self):  # a recipe on the rule line
        for mk in ("test: ; echo ran\n", "test:; echo\n", "test: dep ; FOO=1 echo\n", "a b: x;\n"):
            with self.subTest(mk=mk):
                self.refused(mk, 1, self.SEMI)

    def test_refused_backslashes(self):
        for mk, n, reason in (("x \\\ntest:\n", 1, self.BACKSLASH), ("test: \\\n", 1, self.BACKSLASH),
                              ("test: \\", 1, self.BACKSLASH), ("# c \\\ntest:\n", 1, self.BACKSLASH),
                              ("all:\n\t@echo a \\\ntest:\n", 2, self.BACKSLASH), ("x = 1 \\\\\ntest:\n", 1, self.BACKSLASH),
                              ("x = 1\\\n", 1, self.BACKSLASH), ("test: a\\;b\n", 1, self.COLON_BS),
                              ("test: a\\#b=c\n", 1, self.COLON_BS), ("test: a \\ b\n", 1, self.COLON_BS),
                              ("test: dep # c \\\n", 1, self.BACKSLASH), ("test:\\\r\n", 1, self.BACKSLASH)):
            with self.subTest(mk=mk):
                self.refused(mk, n, reason)

    def test_refused_tab_led_line_before_the_first_rule(self):
        for mk, n in (("\ttest:\n", 1), ("x = 1\n\ttest:\n", 2), ("# c\n\n\t@echo a\n", 3), ("\t# c\n", 1),
                      ("\tdefine D\n", 1), ("x = 1\n\t@echo\ntest:\n", 2)):
            with self.subTest(mk=mk):
                self.refused(mk, n, self.RECIPE)

    def test_refused_non_literal_targets(self):
        for mk in ("$(T):\n", "%:\n", "%.o: %.c\n", "test $(X):\n", "${T}:\n", "a$$b:\n", "test%:\n", "(x):\n", "a,b:\n",
                   "\"test\":\n"):
            with self.subTest(mk=mk):
                self.refused(mk, 1, self.OTHER)

    def test_refused_anything_unmatched(self):
        for mk in ("foo\n", "a b c\n", "test\n", ":\n", ": x\n", "test x\n", "x\u00a0test:\n", "\ufefftest:\n",
                   "$@\n", "@echo\n", "1 = 2\n"):
            with self.subTest(mk=mk):
                self.refused(mk, 1, self.OTHER)

    # ---- fix round 4 (owner Q-C11r4-0 (a)): fail closed, one Problem naming the first offending line

    CONTROL = "control character"
    MAKEFLAGS = "assignment to MAKEFLAGS or MFLAGS"
    CALL = "make function call"
    # Unicode general category Cc, minus TAB and LF (LF ends the line): U+0000-U+0008, U+000B-U+001F, U+007F-U+009F.
    CC = [chr(c) for c in range(0x00, 0x20) if chr(c) not in "\t\n"] + [chr(c) for c in range(0x7F, 0xA0)]

    def test_control_character_set_is_unicode_cc(self):  # the expected set, derived independently of detect
        import unicodedata
        self.assertEqual(self.CC, [chr(c) for c in range(0x110000)
                                   if unicodedata.category(chr(c)) == "Cc" and chr(c) not in "\t\n"])

    def test_refused_control_characters(self):  # F-C11r4-4: every Cc character except TAB, in every line form
        for ch in [c for c in self.CC if c != "\r"]:  # CR: test_carriage_return_only_before_line_feed
            for mk, n in ((ch + "test:\n", 1), ("all:\n# c" + ch + "\ntest:\n", 2), ("all:\nX = 1" + ch + "\ntest:\n", 2),
                          ("all: a" + ch + "\ntest:\n", 1), ("test:\n\t@echo ran" + ch + "\n\tendif\n", 2), ("test:" + ch, 1),
                          ("test:\n" + ch + "\n", 2), ("test:\n \t" + ch + "\n", 2), ("x" + ch + "test:\n", 1),
                          ("test" + ch + ":\n", 1), ("test:\n\n\n" + ch, 4)):
                with self.subTest(ch=hex(ord(ch)), mk=mk):
                    self.refused(mk, n, self.CONTROL)

    def test_carriage_return_only_before_line_feed(self):  # F-C11r4-4: a CR is allowed only directly before LF
        for mk, n in (("test:\r", 1), ("test:\r\r\n", 1), ("a\rtest:\n", 1), ("test:\n\t@echo \r x\n", 2),
                      ("# c\r\n\r", 2), ("\rtest:\n", 1), ("test:\r \n", 1), ("x = 1\r\n# a\rb\r\n", 2)):
            with self.subTest(mk=mk):
                self.refused(mk, n, self.CONTROL)
        self.assertEqual(self.rules("x = 1\r\n# c\r\n\t\r\ntest:\r\n\t@echo\r\n"), [("test", "make test", "Makefile:4 test")])

    def test_characters_next_to_the_control_range_are_not_control(self):  # U+0020, U+007E, U+00A0, U+00AD, U+2028, U+FEFF
        for ch in (" ", "~", "\u00a0", "\u00ad", "\u2028", "\ufeff", "\u200b"):
            with self.subTest(ch=hex(ord(ch))):
                self.assertEqual(self.rules("# a" + ch + "b\ntest:\n\t@echo " + ch + "\n"),
                                 [("test", "make test", "Makefile:2 test")])

    def test_control_character_first_offending_line_wins(self):
        self.refused("include x\n\x00\n", 1, self.DIRECTIVE)
        self.refused("\x00\ninclude x\n", 1, self.CONTROL)
        self.refused("test:\nlint:\n# \x00\nX := $(shell y)\n", 3, self.CONTROL)
        self.refused("test: \x00\\\n", 1, self.CONTROL)  # the control check comes first within a line
        self.refused("X := $(shell \x00)\n", 1, self.CONTROL)
        self.refused("X := $(shell x) \\\n", 1, self.BACKSLASH)  # order within a line: control, backslash, call

    def test_refused_slash_in_a_target(self):  # F-C11r4-1: targets are [A-Za-z0-9_.-]+, so `./test` is refused
        for mk, n in (("./test:\n", 1), ("test:\n\t@echo ran\n./test::\n\t@echo ran2\n", 3), ("./test::\ntest:\n", 1),
                      ("././test::\n", 1), ("out/test.o: a\n", 1), ("sub-dir/lint: x\n", 1), ("/test:\n", 1),
                      ("test/:\n", 1), ("a b/c:\n", 1), ("test ./x:\n", 1), ("lint:\nsub/test:\n", 2), ("a/b.c-d_e: x\n", 1),
                      ("./build:\n", 1), ("  ./test:\n", 1), ("x/:: y\n", 1), ("./test lint:\n", 1), ("a/b c d:\n", 1),
                      ("a b/c d::\n", 1)):
            with self.subTest(mk=mk):
                self.refused(mk, n, self.OTHER)

    # Characters outside [A-Za-z0-9_.-] other than the blanks, `/` (above), `=`, `:` and `#` (below), and the control
    # characters (test_refused_control_characters); non-ASCII letters and digits included.
    BAD_TARGET_CHARS = ("+", "$", "%", "*", "?", "~", "@", "!", ",", "(", ")", "[", "]", "{", "}", "<", ">", "|", "&",
                        "^", "`", "'", '"', ";", "\\", "\u00e9", "\u00df", "\u03a9", "\u0663", "\uff21", "\u00a0")

    def test_refused_target_characters(self):  # F-C11r4r-2: every target character class outside [A-Za-z0-9_.-]
        for ch in self.BAD_TARGET_CHARS:
            for mk in ("a%sb test:\n" % ch, "test a%sb:\n" % ch, "a%sb:\n" % ch, "%stest:\n" % ch, "test%s:\n" % ch,
                       "test%s::\n" % ch, "  a b%sc lint:\n" % ch, "lint:\ntest%s:\n" % ch):
                with self.subTest(ch=ch, mk=mk):
                    self.refused(mk, mk.count("\n"), self.OTHER)
        for mk in ("a#b test:\n", "test a#b:\n", "a#b:\n", "test#:\n", "test a=b:\n", "=test:\n", "x a=b:\n"):
            with self.subTest(mk=mk):
                self.refused(mk, 1, self.OTHER)
        for mk in ("a:b test:\n", "a:b:\n", "test a:b:\n"):  # `:` inside a name: the text after the first colon holds a second
            with self.subTest(mk=mk):
                self.refused(mk, 1, self.SECOND_COLON)
        self.assertEqual(self.rules("#test:\na=b test:\n"), [])  # a comment and an assignment, not targets

    def test_slash_after_the_colon_is_text(self):  # prerequisites are not targets
        self.assertEqual(self.rules("test: src/a.c ./b /c\n\t@echo ./x\n"), [("test", "make test", "Makefile:1 test")])

    def test_refused_makeflags_assignment(self):  # F-C11r4-3: any operator, any value, any position
        for name in ("MAKEFLAGS", "MFLAGS"):
            for op in ("=", ":=", "?=", "+="):
                for mk, n in (("%s %s -q\ntest:\n\t@echo ran\n" % (name, op), 1), ("%s%s-t\ntest:\n" % (name, op), 1),
                              ("test:\n\t@echo\n%s\t%s q\n" % (name, op), 3), ("  %s %s\n" % (name, op), 1),
                              ("test:\n %s %s --question\n" % (name, op), 2)):
                    with self.subTest(mk=mk):
                        self.refused(mk, n, self.MAKEFLAGS)

    def test_names_next_to_makeflags_are_ordinary(self):
        self.assertEqual(self.rules("makeflags = -q\nMAKEFLAGSX = -q\nXMAKEFLAGS = -q\nMAKEFLAGS_ = -q\nMFLAGS2 += -t\n"
                                    "Mflags = -q\nX = MAKEFLAGS\nMAKEFLAGS:\nMFLAGS: x\ntest: MAKEFLAGS\n"),
                         [("test", "make test", "Makefile:10 test")])

    def test_refused_make_function_calls(self):  # F-C11r4-2: $(f ...) or ${f ...} for the eight names, on any line
        for fn in ("eval", "error", "shell", "file", "call", "value", "info", "warning"):
            for o, c in (("(", ")"), ("{", "}")):
                ref = "$" + o + fn + " x" + c
                for mk, n in (("X := %s\ntest:\n" % ref, 1), ("X = %s\ntest:\n" % ref, 1), ("X :=\nX += %s\ntest:\n" % ref, 2),
                              ("X ?= a %s b\n" % ref, 1), ("test: %s\n" % ref, 1), ("test:\n\t@echo %s\n" % ref, 2),
                              ("# %s\ntest:\n" % ref, 1), ("X := $(foo %s)\n" % ref, 1), ("X := $%s\n" % ref, 1),
                              ("X := $" + o + fn + c + "\n", 1), ("X := $" + o + fn + "\tx" + c + "\n", 1),
                              ("X := $" + o + fn + "," + c + "\n", 1), ("test:\nlint:\n  # %s\n" % ref, 3),
                              ("include %s\n" % ref, 1), ("X := $" + o + fn, 1),
                              # the name ends at any character but an ASCII letter, ASCII digit, `_` or `-`
                              # (controller ruling D-C11r4r-1 (a) under owner Q-C11r4-0)
                              ("X = $" + o + fn + ".x" + c + "\ntest:\n", 1), ("X = $" + o + fn + "é x" + c + "\n", 1),
                              ("X = $" + o + fn + "٣ x" + c + "\n", 1), ("X = $" + o + fn + "ß" + c + "\n", 1),
                              ("X = $" + o + fn + "Ａ x" + c + "\n", 1), ("X = $" + o + fn + "/x" + c + "\n", 1),
                              ("X = $" + o + fn + ":x" + c + "\n", 1), ("X = $" + o + fn + "$(Y)" + c + "\n", 1)):
                    with self.subTest(mk=mk):
                        self.refused(mk, n, self.CALL)

    def test_references_that_are_not_the_eight_calls_are_ordinary(self):
        mk = ("CC = cc\nX := $(CC) ${CC} $(SHELL) $(evaluate x) $(infos) $(shell_x) $(shell-x y) $(filter a,b)\n"
              "Z = $(infoX y) ${evalA} $(shell2 x) $(callB) ${error9 x} $(warningZ)\n"
              "Y = $(Shell x) $( shell x) $(sh$(E)ell x) shell x $shell (eval x) {info x} $(errors) ${values x}\n"
              "test: $(CC) $(foreach a,b,c)\n\t@echo $(CC) $(firstword a) $(origin x) $(warnings)\n")
        self.assertEqual(self.rules(mk), [("test", "make test", "Makefile:5 test")])

    def test_repository_state_is_not_examined(self):  # F-C11r4-5 out of scope (owner Q-C11r4-0 (a)): no repo-state checks
        os.mkdir(os.path.join(self.tmp, "test"))
        self.write("lint", "x")
        self.write("Makefile", "test:\n\t@echo ran\nlint:\n")
        self.assertEqual(detect(self.tmp), Detection((Proposal("test", "make test", "Makefile:1 test"),
                                                      Proposal("lint", "make lint", "Makefile:3 lint")), ()))

    def test_refused_second_colon_in_the_rule_text(self):  # controller ruling R3
        for mk in ("test ::: x\n", "test: a:b\n", "test :: : x\n", "test: x%: y\n", "test: %: y\n", "test:: a: b\n", "a: b: c\n"):
            with self.subTest(mk=mk):
                self.refused(mk, 1, self.SECOND_COLON)

    def test_second_colon_in_a_trailing_comment_is_ignored(self):
        self.assertEqual(self.rules("test: dep # a: b\n"), [("test", "make test", "Makefile:1 test")])

    def test_refused_target_with_both_single_and_double_colon(self):  # R3: the Problem names the second line
        for mk, n in (("test:\ntest::\n", 2), ("test::\ntest:\n", 2), ("a:\nb::\nc:\nb: x\n", 4), ("a b:\nc a::\n", 2),
                      ("test:\n\t@echo\n\nlint:\nbuild: x\nbuild:: y\n", 6)):
            with self.subTest(mk=mk):
                self.refused(mk, n, self.MIXED)

    def test_same_colon_kind_repeated_is_accepted(self):
        self.assertEqual(self.rules("a b:\nb c:\nx::\nx::\ntest:: \n"), [("test", "make test", "Makefile:5 test")])

    def test_first_unsupported_line_wins_and_hides_earlier_proposals(self):
        self.refused("test:\nlint:\ninclude x.mk\nbuild: X = 1\n", 3, self.DIRECTIVE)
        self.refused("lint:\nbuild: X = 1\nifdef X\n", 2, self.ASSIGN)
        self.refused("\n\ntest: ; x\n", 3, self.SEMI)

    def test_refusal_names_the_spelled_file(self):
        self.refused("include x\n", 1, self.DIRECTIVE, name="GNUmakefile")
        self.refused("include x\n", 1, self.DIRECTIVE, name="makefile")

    def test_reason_never_echoes_makefile_text(self):  # the reason is escaped once by Result.render; no user text in it
        with tempfile.TemporaryDirectory() as d:
            self.write("Makefile", "SECRET_TOKEN_123\n", root=d)
            p = detect(d).problems[0]
        self.assertNotIn("SECRET", p.reason)

    def test_problem_does_not_hide_package_json(self):
        self.write("package.json", '{"scripts": {"test": "t"}}')
        self.write("Makefile", "define D\n")
        self.assertEqual(detect(self.tmp), Detection((Proposal("test", "npm run test", "package.json scripts.test"),),
                                                     (Problem("Makefile", "unsupported line 1: " + self.DIRECTIVE),)))


class OrderAndEffectTests(Base):
    def test_several_sources_and_slots(self):  # O1
        self.write("package.json", '{"scripts": {"build": "b", "test": "t"}}')
        self.write("Makefile", "build:\ntest:\nlint:\n")
        self.assertEqual(detect(self.tmp), Detection((
            Proposal("test", "npm run test", "package.json scripts.test"),
            Proposal("build", "npm run build", "package.json scripts.build"),
            Proposal("test", "make test", "Makefile:2 test"),
            Proposal("lint", "make lint", "Makefile:3 lint"),
            Proposal("build", "make build", "Makefile:1 build")), ()))

    def test_problem_in_one_source_keeps_the_other(self):  # O2
        self.write("package.json", "{")
        self.write("Makefile", "test:\n")
        self.assertEqual(detect(self.tmp), Detection((Proposal("test", "make test", "Makefile:1 test"),),
                                                     (Problem("package.json", "not valid JSON"),)))
        self.write("package.json", '{"scripts": {"lint": "l"}}')
        self.write("Makefile", b"\xff")
        self.assertEqual(detect(self.tmp), Detection((Proposal("lint", "npm run lint", "package.json scripts.lint"),),
                                                     (Problem("Makefile", "not valid UTF-8"),)))

    def test_problems_in_source_order(self):  # O2
        self.write("package.json", "[]")
        self.write("Makefile", b"\xff")
        self.assertEqual(detect(self.tmp).problems, (Problem("package.json", "top level is not an object"),
                                                     Problem("Makefile", "not valid UTF-8")))

    def test_test_one_never_proposed(self):  # O3 / DC-2
        self.write("package.json", '{"scripts": {"test": "a", "test_one": "b", "lint": "c", "build": "d"}}')
        self.write("Makefile", "test_one:\ntest:\nlint:\nbuild:\n")
        res = detect(self.tmp)
        self.assertEqual(len(res.proposals), 6)
        self.assertTrue(all(p.slot != "test_one" for p in res.proposals))

    def test_detect_has_no_side_effects(self):  # O5 O6
        self.write("package.json", '{"scripts": {"test": "t"}}')
        self.write("Makefile", "test:\n")
        os.symlink("package.json", os.path.join(self.tmp, "link"))
        os.mkfifo(os.path.join(self.tmp, "fifo"))
        os.mkdir(os.path.join(self.tmp, "sub"))
        before = snapshot(self.tmp)
        with mock.patch("subprocess.run") as run, mock.patch("os.system") as system, \
                mock.patch("subprocess.Popen") as popen:
            detect(self.tmp)
        self.assertEqual(snapshot(self.tmp), before)
        self.assertFalse(run.called or system.called or popen.called)

    def test_no_side_effects_on_problem_paths(self):  # O5
        self.write("package.json", "{")
        os.mkfifo(os.path.join(self.tmp, "GNUmakefile"))
        before = snapshot(self.tmp)
        detect(self.tmp)
        self.assertEqual(snapshot(self.tmp), before)

    def test_module_has_no_subprocess_import(self):
        self.assertFalse(hasattr(detect_mod, "subprocess"))


def triples(res: Detection) -> list:
    return [(p.slot, p.command, p.source) for p in res.proposals]


EXPECTED = {
    "Cargo.toml": [("test", "cargo test", "Cargo.toml"), ("build", "cargo build", "Cargo.toml")],
    "go.mod": [("test", "go test ./...", "go.mod"), ("build", "go build ./...", "go.mod")],
    "mvnw": [("test", "./mvnw test", "mvnw"), ("build", "./mvnw package", "mvnw")],
    "gradlew": [("test", "./gradlew test", "gradlew"), ("build", "./gradlew build", "gradlew")],
}
WRAPPERS = ("mvnw", "gradlew")
DENIED = "Permission denied"


def spy_open(seen: list):
    real_open = os.open

    def spy(path, *a, **k):
        seen.append(path)
        return real_open(path, *a, **k)
    return mock.patch("os.open", spy)


class SourcesTests(Base):
    def test_sources_constant(self):  # S1
        self.assertEqual(detect_mod.SOURCES, ("package.json", "Makefile", "Cargo.toml", "go.mod", "mvnw", "gradlew",
                                              "pyproject.toml"))
        self.assertIs(type(detect_mod.SOURCES), tuple)

    def test_readers_follow_sources(self):  # S2: detect reads through one label -> reader table
        self.assertEqual(tuple(detect_mod._READERS), detect_mod.SOURCES)

    def test_detect_calls_readers_in_sources_order(self):  # S2 through detect()
        calls = []

        def spy(label):
            def read(root, listing):
                calls.append(label)
                return (), ()
            return read
        table = {label: spy(label) for label in detect_mod.SOURCES}
        with mock.patch.object(detect_mod, "_READERS", table):
            detect(self.tmp)
        self.assertEqual(calls, list(detect_mod.SOURCES))


class ToolchainTests(Base):
    def put(self, name: str, content="", mode=None, root=None) -> str:
        path = self.write(name, content, root=root)
        if mode is None:
            mode = 0o755 if name in WRAPPERS else 0o644
        os.chmod(path, mode)
        return path

    def test_toolchain_sources(self):  # T2, T12: empty file, exact commands, test before build, no lint, no test_one
        for name, expected in EXPECTED.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as d:
                self.put(name, "", root=d)
                res = detect(d)
                self.assertEqual(res.problems, ())
                self.assertEqual(triples(res), expected)

    def test_absent(self):  # T1
        self.assertEqual(detect(self.tmp), Detection((), ()))

    def test_content_never_examined(self):  # T3
        contents = (b"\xff", b"\x00\x00", "[workspace]\n", "no module line\n", b"\xef\xbb\xbf", "x" * 200000)
        for name, expected in EXPECTED.items():
            for content in contents:
                with self.subTest(name=name, content=repr(content)[:20]), tempfile.TemporaryDirectory() as d:
                    self.put(name, content, root=d)
                    self.assertEqual(detect(d), Detection(tuple(Proposal(*t) for t in expected), ()))

    def test_symlink_is_a_problem_and_never_opened(self):  # T4
        for name in EXPECTED:
            for kind in ("file", "dir", "dangling"):
                with self.subTest(name=name, kind=kind), tempfile.TemporaryDirectory() as d:
                    target = os.path.join(d, "target")
                    if kind == "file":
                        self.write("target", "x", root=d)
                    elif kind == "dir":
                        os.mkdir(target)
                    os.symlink(target, os.path.join(d, name))
                    seen = []
                    with spy_open(seen):
                        res = detect(d)
                    self.assertEqual(seen, [])
                    self.assertEqual(res, Detection((), (Problem(name, "symlink; not read"),)))

    def test_directory_and_fifo_never_opened(self):  # T5
        for name in EXPECTED:
            for kind in ("dir", "fifo"):
                with self.subTest(name=name, kind=kind), tempfile.TemporaryDirectory() as d:
                    p = os.path.join(d, name)
                    if kind == "dir":
                        os.mkdir(p)
                    else:
                        os.mkfifo(p)
                    seen = []
                    with spy_open(seen):
                        res = detect(d)
                    self.assertEqual(seen, [])
                    self.assertEqual(res, Detection((), (Problem(name, "not a regular file"),)))

    @unittest.skipIf(os.geteuid() == 0, "root ignores file modes")
    def test_unreadable_is_a_problem(self):  # T6
        for name in EXPECTED:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as d:
                p = self.put(name, "x", mode=0o000, root=d)
                self.assertEqual(detect(d), Detection((), (Problem(name, DENIED),)))

    def test_lstat_failure_is_a_problem(self):  # T6: lstat fails with another OSError
        for name in EXPECTED:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as d:
                self.put(name, "x", root=d)
                real_lstat = os.lstat

                def deny(path, *a, **k):
                    if os.path.basename(path) == name:
                        raise PermissionError(13, DENIED)
                    return real_lstat(path, *a, **k)
                with mock.patch("os.lstat", deny):
                    res = detect(d)
                self.assertEqual(res, Detection((), (Problem(name, DENIED),)))

    def test_read_error_closes_descriptor(self):  # T6: the descriptor is closed on every path
        for name in EXPECTED:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as d:
                self.put(name, "x", root=d)
                opened, closed = [], []
                real_open, real_close = os.open, os.close

                def spy_o(path, *a, **k):
                    fd = real_open(path, *a, **k)
                    opened.append(fd)
                    return fd

                def spy_c(fd):
                    closed.append(fd)
                    return real_close(fd)

                def boom(fd, n):
                    raise OSError(5, "Input/output error")
                with mock.patch("os.open", spy_o), mock.patch("os.close", spy_c), mock.patch("os.read", boom):
                    res = detect(d)
                self.assertEqual(res, Detection((), (Problem(name, "Input/output error"),)))
                self.assertEqual(len(opened), 1)
                self.assertEqual(opened, closed)

    def test_wrapper_execute_bit(self):  # T7 (owner Q-C12-2 (a))
        for name in WRAPPERS:
            for mode, ok in ((0o644, False), (0o600, False), (0o755, True), (0o744, True), (0o700, True), (0o655, True),
                             (0o645, True), (0o641, True), (0o444, False)):
                with self.subTest(name=name, mode=oct(mode)), tempfile.TemporaryDirectory() as d:
                    p = self.put(name, "x", mode=mode, root=d)
                    want = Detection(tuple(Proposal(*t) for t in EXPECTED[name]), ()) if ok \
                        else Detection((), (Problem(name, "not executable"),))
                    self.assertEqual(detect(d), want)

    def test_non_wrappers_need_no_execute_bit(self):  # T7
        for name in ("Cargo.toml", "go.mod"):
            with self.subTest(name=name):
                self.put(name, "", mode=0o600)
                self.assertEqual(len(detect(self.tmp).proposals), 2)
                os.unlink(os.path.join(self.tmp, name))

    def test_kind_is_reported_before_the_mode(self):  # T7
        os.symlink("nowhere", os.path.join(self.tmp, "mvnw"))
        os.mkdir(os.path.join(self.tmp, "gradlew"), 0o600)
        self.assertEqual(detect(self.tmp).problems, (Problem("mvnw", "symlink; not read"),
                                                     Problem("gradlew", "not a regular file")))

    def test_case_variants_are_nothing(self):  # T8, P18 (owner Q-C12-3 (a)): the exact spelling in the listing only
        for v in ("cargo.toml", "GO.MOD", "Mvnw", "GRADLEW", "PyProject.toml"):
            with self.subTest(name=v):
                self.put(v, "[tool.ruff]\n", mode=0o755)
                self.assertEqual(detect(self.tmp), Detection((), ()))
                os.unlink(os.path.join(self.tmp, v))

    def test_case_variants_are_nothing_on_a_case_insensitive_filesystem(self):  # T8, P18, simulated
        for v in ("cargo.toml", "GO.MOD", "Mvnw", "GRADLEW", "PyProject.toml"):
            self.put(v, "[tool.ruff]\n", mode=0o755)
        real_lstat = os.lstat

        def ci_lstat(path, *a, **k):
            d, base = os.path.split(path)
            if d == self.tmp:
                for e in os.listdir(d):
                    if e.lower() == base.lower():
                        return real_lstat(os.path.join(d, e), *a, **k)
            return real_lstat(path, *a, **k)
        with mock.patch("os.lstat", ci_lstat):
            self.assertEqual(detect(self.tmp), Detection((), ()))

    def test_package_json_case_variants_are_nothing(self):  # U1 (owner Q-C12r-2 (a))
        for v in ("Package.json", "PACKAGE.JSON", "package.JSON"):
            with self.subTest(name=v), tempfile.TemporaryDirectory() as d:
                self.put(v, '{"scripts": {"test": "t"}}', root=d)
                self.assertEqual(detect(d), Detection((), ()))

    def test_package_json_case_variant_on_a_case_insensitive_filesystem(self):  # U1, simulated
        self.put("Package.json", '{"scripts": {"test": "t"}}')
        real_lstat = os.lstat

        def ci_lstat(path, *a, **k):
            d, base = os.path.split(path)
            if d == self.tmp:
                for e in os.listdir(d):
                    if e.lower() == base.lower():
                        return real_lstat(os.path.join(d, e), *a, **k)
            return real_lstat(path, *a, **k)
        with mock.patch("os.lstat", ci_lstat):
            self.assertEqual(detect(self.tmp), Detection((), ()))

    def test_sub_directory_only(self):  # T9, O5
        for rel in ("crates/a/Cargo.toml", "svc/go.mod", "x/mvnw", "y/gradlew", "z/pyproject.toml", "packages/a/package.json",
                    "m/Makefile"):
            sub = os.path.join(self.tmp, os.path.dirname(rel))
            os.makedirs(sub, exist_ok=True)
            self.put(os.path.basename(rel), "[tool.ruff]\ntest:\n", root=sub)
        self.assertEqual(detect(self.tmp), Detection((), ()))

    def test_other_toolchain_files_are_not_sources(self):  # T10
        for name in ("Cargo.lock", "go.work", "go.sum", "pom.xml", "build.gradle", "settings.gradle.kts", "setup.py",
                     "setup.cfg", "tox.ini", "pytest.ini", "ruff.toml", ".ruff.toml", "mvnw.cmd", "gradlew.bat"):
            self.put(name, "[tool.ruff]\n[pytest]\n")
        os.makedirs(os.path.join(self.tmp, ".mvn"))
        self.assertEqual(detect(self.tmp), Detection((), ()))

    def test_windows_wrappers_alone_not_proposed(self):  # W1
        self.put("mvnw.cmd", "")
        self.assertEqual(detect(self.tmp).proposals, ())
        self.put("gradlew.bat", "")
        self.assertEqual(detect(self.tmp), Detection((), ()))

    def test_windows_wrapper_beside_the_posix_one(self):  # W2
        for posix, win in (("mvnw", "mvnw.cmd"), ("gradlew", "gradlew.bat")):
            with self.subTest(name=posix), tempfile.TemporaryDirectory() as d:
                self.put(posix, "", root=d)
                self.put(win, "", root=d)
                self.assertEqual(detect(d), Detection(tuple(Proposal(*t) for t in EXPECTED[posix]), ()))

    def test_windows_wrapper_of_odd_kind_never_examined(self):  # W3
        for posix, win in (("mvnw", "mvnw.cmd"), ("gradlew", "gradlew.bat")):
            for kind in ("symlink", "dir", "fifo"):
                for beside in (False, True):
                    with self.subTest(name=win, kind=kind, beside=beside), tempfile.TemporaryDirectory() as d:
                        p = os.path.join(d, win)
                        if kind == "symlink":
                            os.symlink(os.path.join(d, "gone"), p)
                        elif kind == "dir":
                            os.mkdir(p)
                        else:
                            os.mkfifo(p)
                        if beside:
                            self.put(posix, "", root=d)
                        seen = []
                        with spy_open(seen):
                            res = detect(d)
                        self.assertNotIn(p, seen)
                        want = tuple(Proposal(*t) for t in EXPECTED[posix]) if beside else ()
                        self.assertEqual(res, Detection(want, ()))

    def test_vanished_after_the_listing(self):  # F3: listed, gone by the read
        for name in EXPECTED:
            with self.subTest(name=name):
                with mock.patch("os.listdir", lambda root: [name]):
                    res = detect(self.tmp)
                self.assertEqual(res, Detection((), (Problem(name, "No such file or directory"),)))

    def test_mode_check_failure_is_a_problem(self):  # F3: the execute-bit lstat fails after _fetch succeeded
        for name in WRAPPERS:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as d:
                self.put(name, "x", root=d)
                real_lstat = os.lstat
                calls = []

                def second_fails(path, *a, **k):
                    if os.path.basename(path) == name:
                        calls.append(path)
                        if len(calls) > 1:
                            raise PermissionError(13, DENIED)
                    return real_lstat(path, *a, **k)
                with mock.patch("os.lstat", second_fails):
                    res = detect(d)
                self.assertEqual(res, Detection((), (Problem(name, DENIED),)))

    def test_wrapper_support_files_not_required(self):  # T11
        self.put("mvnw", "")
        self.put("gradlew", "")
        self.assertEqual(len(detect(self.tmp).proposals), 4)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, ".mvn")))


def py_test(n: int) -> Proposal:
    return Proposal("test", "python3 -m pytest", "pyproject.toml:%d tool.pytest.ini_options" % n)


def py_lint(n: int) -> Proposal:
    return Proposal("lint", "ruff check .", "pyproject.toml:%d tool.ruff" % n)


PY_STRING = "unsupported line %d: multi-line string"
PY_BOM = Problem("pyproject.toml", "unsupported line 1: byte order mark")


class PyprojectTests(Base):
    def run_text(self, text) -> Detection:
        with tempfile.TemporaryDirectory() as d:
            self.write("pyproject.toml", text, root=d)
            return detect(d)

    def test_pyproject_headers(self):  # P4, P5, P13: the plan's example
        res = self.run_text('[project]\nname = "x"\n  [tool.pytest.ini_options]\n[tool.ruff.lint]\n')
        self.assertEqual(res, Detection((py_test(3), py_lint(4)), ()))

    def test_pyproject_trailing_comment_and_repeated_header(self):  # P11, P12, P13: the plan's example
        res = self.run_text('[tool.ruff]  # lint\n[tool.ruff.lint]\n[tool.pytest.ini_options] \t\n')
        self.assertEqual(res, Detection((py_test(3), py_lint(1)), ()))
        self.assertEqual(self.run_text("[tool.ruff] x\n"), Detection((), ()))

    def test_file_kinds(self):  # P1
        self.assertEqual(detect(self.tmp), Detection((), ()))
        for kind, reason in (("symlink", "symlink; not read"), ("dir", "not a regular file"), ("fifo", "not a regular file")):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as d:
                p = os.path.join(d, "pyproject.toml")
                if kind == "symlink":
                    self.write("t", "[tool.ruff]\n", root=d)
                    os.symlink(os.path.join(d, "t"), p)
                elif kind == "dir":
                    os.mkdir(p)
                else:
                    os.mkfifo(p)
                seen = []
                with spy_open(seen):
                    res = detect(d)
                self.assertEqual(seen, [])
                self.assertEqual(res, Detection((), (Problem("pyproject.toml", reason),)))

    @unittest.skipIf(os.geteuid() == 0, "root ignores file modes")
    def test_unreadable(self):  # P1
        p = self.write("pyproject.toml", "[tool.ruff]\n")
        os.chmod(p, 0)
        self.assertEqual(detect(self.tmp), Detection((), (Problem("pyproject.toml", DENIED),)))

    def test_encoding(self):  # P2
        self.assertEqual(self.run_text(b"\xff[tool.ruff]\n"), Detection((), (Problem("pyproject.toml", "not valid UTF-8"),)))
        self.assertEqual(self.run_text("# caf\u00e9 \u00ef\n[tool.ruff]\n").proposals, (py_lint(2),))
        self.assertEqual(self.run_text("\ufeff[tool.ruff]\n"), Detection((), (PY_BOM,)))
        self.assertEqual(self.run_text("\ufeff[project]\n"), Detection((), (PY_BOM,)))

    def test_vanished_after_the_listing(self):  # F3
        with mock.patch("os.listdir", lambda root: ["pyproject.toml"]):
            res = detect(self.tmp)
        self.assertEqual(res, Detection((), (Problem("pyproject.toml", "No such file or directory"),)))

    def test_comment_control_characters_make_the_file_unsupported(self):  # F1 (owner Q-C12r-1 (a))
        cases = (
            ("[tool.ruff] # x\r", 1),  # a lone CR at the end of the file
            ("[tool.ruff] #\\x00\n", 1),
            ("[tool.ruff] #a\rb\n", 1),
            ("[tool.pytest.ini_options]#\\x01\n", 1),
            ("x = 1\n[tool.ruff] # a\\x7fb\n", 2),
            ("x = 1\n[tool.ruff] # a\\u0085b\n", 2),
            ("x = 1\n[tool.ruff] # a\\u009fb\n", 2),
            ("x = 1\n[tool.ruff] # a\\x1fb\n", 2),
            ("x = 1\n[tool.ruff] # a\\x08b\n", 2),
            ("x = 1\n[tool.ruff] # a\\x0bb\n", 2),
            ("x = 1\n[tool.ruff] # a\\x0cb\n", 2),
            ("[tool.ruff.lint] # \\x00\n[tool.ruff]\n", 1),
            ("[tool.ruff]\n[tool.pytest.ini_options] # \\x00\n", 2),  # also after an earlier good header
        )
        for text, line in cases:
            text = text.encode("ascii").decode("unicode_escape") if "\\" in text else text
            with self.subTest(text=text):
                self.assertEqual(self.run_text(text),
                                 Detection((), (Problem("pyproject.toml", "unsupported line %d: control character" % line),)))

    def test_comment_characters_that_are_allowed(self):  # F1: TAB, U+00A0, U+2028, U+00AD are not Cc; CRLF is the line end
        for tail in ("# a\tb", "#\t", "# \u00a0 \u2028 \u00ad \ufeff", "# \u00e9"):
            with self.subTest(tail=repr(tail)):
                self.assertEqual(self.run_text("[tool.ruff] " + tail + "\n"), Detection((py_lint(1),), ()))
        self.assertEqual(self.run_text("[tool.ruff] # a\r\n"), Detection((py_lint(1),), ()))

    def test_control_characters_elsewhere_still_not_examined(self):  # F1 scope: only a matched header's comment
        text = '[project]\nname = "x" # \x00\n# \x01\n[tool.ruff] x \x00\n[tool.ruffx] # \x00\n[tool.ruff]\n'
        self.assertEqual(self.run_text(text), Detection((py_lint(6),), ()))

    def test_empty_and_no_header(self):  # P3
        for text in ("", '[project]\nname = "x"\n', "\n\n"):
            with self.subTest(text=text):
                self.assertEqual(self.run_text(text), Detection((), ()))

    def test_lint_header_forms(self):  # P5, P6
        for header in ("[tool.ruff]", "[tool.ruff.lint]", "[tool.ruff.lint.isort]", "[tool.ruff.lint.per-file-ignores]",
                       "[tool.ruff.x_1]", "[tool.ruff.A-b.c9]", "[tool.ruff.formatx]", "[tool.ruff.lint.format]"):
            with self.subTest(header=header):
                self.assertEqual(self.run_text("x = 1\n" + header + "\n"), Detection((py_lint(2),), ()))

    def test_headers_not_matched(self):  # P6, P8, P9
        for header in ("[tool.ruff.]", '[tool.ruff."q"]', "[tool.ruff.l\u00efnt]", "[tool.ruff..lint]", "[tool.ruffx]",
                       "[tool.ruff.lint.]", "[tool.Ruff]", "[Tool.ruff]", "[tool.ruff-x]", "[tool.pytest]",
                       "[tool.pytest.ini_optionsx]", "[tool.pytest.ini_options.x]", "[tool.pytest.INI_options]",
                       "[[tool.ruff]]", "[[tool.pytest.ini_options]]", '["tool".pytest.ini_options]', '[tool."ruff"]',
                       "[ tool.ruff ]", "[tool . ruff]", "[ tool.pytest.ini_options]", "[tool.ruff ]",
                       "[tool.pytest.ini_options ]", "[tool.ruff", "tool.ruff]", "[tool.ruff]]", "[[tool.ruff]",
                       "x = [tool.ruff]", "[tool.ruff.lint] = 1", "[tool.ruff]=1"):
            with self.subTest(header=header):
                self.assertEqual(self.run_text(header + "\n"), Detection((), ()))

    def test_ruff_format_alone_gives_no_lint(self):  # P7 (owner Q-C12-5 (a))
        for text in ("[tool.ruff.format]\n", "[tool.ruff.format.x]\n", "[tool.ruff.format]\n[tool.ruff.format.y]\n"):
            with self.subTest(text=text):
                self.assertEqual(self.run_text(text), Detection((), ()))
        self.assertEqual(self.run_text("[tool.ruff.format]\n[tool.ruff.lint]\n"), Detection((py_lint(2),), ()))
        self.assertEqual(self.run_text("[tool.ruff.format]\n[tool.ruff]\n"), Detection((py_lint(2),), ()))
        self.assertEqual(self.run_text("[tool.ruff.format]\n[tool.pytest.ini_options]\n"), Detection((py_test(2),), ()))

    def test_leading_whitespace(self):  # P10
        for lead, ok in (("", True), ("  ", True), ("\t", True), (" \t", True), ("\t \t ", True), ("\u00a0", False),
                         ("\u3000", False), ("\f", False), ("\v", False)):
            for header, want in (("[tool.pytest.ini_options]", py_test(1)), ("[tool.ruff]", py_lint(1))):
                with self.subTest(lead=repr(lead), header=header):
                    self.assertEqual(self.run_text(lead + header + "\n"), Detection((want,) if ok else (), ()))

    def test_after_the_bracket(self):  # P11
        good = ("", "  \t", " ", "  # lint", "# x", "#x", "\t# x", "  #", "# [tool.pytest.ini_options]", "# \u00e9 \u2603")
        bad = (" x", "\f", "\u00a0", "x", "\v", " ,", "[", "\u00a0#", "=1", " .x", "\u2003")
        for tail in good:
            with self.subTest(tail=repr(tail)):
                self.assertEqual(self.run_text("[tool.ruff]" + tail + "\n"), Detection((py_lint(1),), ()))
        for tail in bad:
            with self.subTest(tail=repr(tail)):
                self.assertEqual(self.run_text("[tool.ruff]" + tail + "\n"), Detection((), ()))

    def test_line_ends(self):  # P11
        self.assertEqual(self.run_text("[tool.ruff]\r\n[tool.pytest.ini_options]\r\n"), Detection((py_test(2), py_lint(1)), ()))
        self.assertEqual(self.run_text("[tool.ruff]\r\n"), Detection((py_lint(1),), ()))
        self.assertEqual(self.run_text("[tool.ruff]"), Detection((py_lint(1),), ()))  # no final newline
        self.assertEqual(self.run_text("[tool.ruff]\r"), Detection((), ()))  # a lone CR at the end of the file
        self.assertEqual(self.run_text("[tool.ruff]\r\r\n"), Detection((), ()))  # only one CR belongs to the line end
        self.assertEqual(self.run_text("[tool.ruff]\rx\n"), Detection((), ()))
        self.assertEqual(self.run_text("a = 1\r\n\r\n[tool.ruff]  # c\r\n"), Detection((py_lint(3),), ()))

    def test_repeated_headers_first_wins(self):  # P12
        self.assertEqual(self.run_text("[tool.ruff]\n[tool.ruff.lint]\n"), Detection((py_lint(1),), ()))
        self.assertEqual(self.run_text("[tool.ruff.lint]\n[tool.ruff]\n"), Detection((py_lint(1),), ()))
        self.assertEqual(self.run_text("[tool.pytest.ini_options]\n[tool.pytest.ini_options]\n"), Detection((py_test(1),), ()))
        self.assertEqual(self.run_text("x\n\n[tool.pytest.ini_options]\ny\n[tool.pytest.ini_options]\n"),
                         Detection((py_test(3),), ()))

    def test_slot_order(self):  # P13
        self.assertEqual(self.run_text("[tool.ruff]\n[tool.pytest.ini_options]\n"), Detection((py_test(2), py_lint(1)), ()))

    def test_triple_quotes_anywhere_are_unsupported(self):  # P14, P15 (owner Q-C12-1 (a)): one Problem, no proposals
        cases = (
            ('"""\n[tool.pytest.ini_options]\n"""\n', 1),
            ("'''\n[tool.pytest.ini_options]\n'''\n", 1),
            ('[tool.ruff]\nx = """\n[tool.pytest.ini_options]\n"""\n', 2),
            ("[tool.ruff]\n\nx = '''\n[tool.pytest.ini_options]\n'''\n", 3),
            ("a = '\"\"\"'\n[tool.ruff]\n", 1),
            ('# """\n[tool.ruff]\n', 1),
            ('x = """\n\'\'\'\n"""\n[tool.ruff]\n', 1),
            ('x = """\n\\"""\n"""\n', 1),
            ('x = """a""""\n[tool.ruff]\n', 1),
            ('[tool.ruff]\nx = """never closed\n', 2),
            ('description = """x"""\n[tool.ruff]\n', 1),
            ("description = '''x'''\n[tool.ruff]\n", 1),
            ("[tool.ruff]\nk = 1\n'''", 3),
            ('"" "\n[tool.ruff]\n', None),  # not a triple quote
            ('x = ""\n[tool.ruff]\n', None),
            ("x = ''\n[tool.ruff]\n", None),
            ('x = "a" "b"\n[tool.ruff]\n', None),
        )
        for text, line in cases:
            with self.subTest(text=text):
                if line is None:
                    self.assertEqual(self.run_text(text), Detection((py_lint(2),), ()))
                else:
                    self.assertEqual(self.run_text(text), Detection((), (Problem("pyproject.toml", PY_STRING % line),)))

    def test_first_triple_quote_line_is_reported_with_crlf(self):  # P15
        res = self.run_text('a = 1\r\nb = """x"""\r\nc = \'\'\'y\'\'\'\r\n[tool.ruff]\r\n')
        self.assertEqual(res, Detection((), (Problem("pyproject.toml", PY_STRING % 2),)))

    def test_header_form_line_in_array_is_matched(self):  # P16: knowing divergence, the reader does not validate TOML
        self.assertEqual(self.run_text("x = [\n[tool.ruff]\n]\n"), Detection((py_lint(2),), ()))
        try:
            import tomllib
        except ImportError:
            return
        with self.assertRaises(tomllib.TOMLDecodeError):
            tomllib.loads("x = [\n[tool.ruff]\n]\n")

    def test_other_lines_not_examined(self):  # P17
        text = 'a = "\u00e9\u2603"\nb = ???\n\x01\n[tool.ruff]\n=\n\x7f\n'
        self.assertEqual(self.run_text(text), Detection((py_lint(4),), ()))

    def test_tomllib_oracle(self):  # P11 oracle, 3.11+ only (detect never imports tomllib)
        try:
            import tomllib
        except ImportError:
            self.skipTest("no tomllib")
        for text in ("  [tool.ruff]  # lint\n", "\t[tool.pytest.ini_options]\t\n", "[tool.ruff]# x\n", "[tool.ruff]\r\n",
                     "[tool.ruff.lint]\n"):
            with self.subTest(text=text):
                tomllib.loads(text)
        for text in ("[tool.ruff]\f\n", "[tool.ruff]\r", "\u00a0[tool.ruff]\n", "[tool.ruff] x\n", "\ufeff[tool.ruff]\n"):
            with self.subTest(text=text):
                with self.assertRaises(tomllib.TOMLDecodeError):
                    tomllib.loads(text)


class OrderTests(Base):
    def all_seven(self, root=None):
        root = root or self.tmp
        self.write("package.json", '{"scripts": {"test": "t", "lint": "l", "build": "b"}}', root=root)
        self.write("Makefile", "test:\nlint:\nbuild:\n", root=root)
        for name in ("Cargo.toml", "go.mod", "mvnw", "gradlew"):
            self.write(name, "", root=root)
            os.chmod(os.path.join(root, name), 0o755 if name in WRAPPERS else 0o644)
        self.write("pyproject.toml", "[tool.ruff]\n[tool.pytest.ini_options]\n", root=root)

    def test_full_source_order(self):  # O1, O2, O4
        self.all_seven()
        res = detect(self.tmp)
        self.assertEqual(res.problems, ())
        self.assertEqual([p.source.split(" ")[0].split(":")[0] for p in res.proposals],
                         ["package.json"] * 3 + ["Makefile"] * 3 + ["Cargo.toml"] * 2 + ["go.mod"] * 2 + ["mvnw"] * 2
                         + ["gradlew"] * 2 + ["pyproject.toml"] * 2)
        self.assertEqual(triples(res), [
            ("test", "npm run test", "package.json scripts.test"), ("lint", "npm run lint", "package.json scripts.lint"),
            ("build", "npm run build", "package.json scripts.build"),
            ("test", "make test", "Makefile:1 test"), ("lint", "make lint", "Makefile:2 lint"),
            ("build", "make build", "Makefile:3 build"),
            ("test", "cargo test", "Cargo.toml"), ("build", "cargo build", "Cargo.toml"),
            ("test", "go test ./...", "go.mod"), ("build", "go build ./...", "go.mod"),
            ("test", "./mvnw test", "mvnw"), ("build", "./mvnw package", "mvnw"),
            ("test", "./gradlew test", "gradlew"), ("build", "./gradlew build", "gradlew"),
            ("test", "python3 -m pytest", "pyproject.toml:2 tool.pytest.ini_options"),
            ("lint", "ruff check .", "pyproject.toml:1 tool.ruff")])
        self.assertEqual(len([p for p in res.proposals if p.slot == "test"]), 7)
        self.assertTrue(all(p.slot != "test_one" for p in res.proposals))  # O4

    def test_problems_in_several_sources(self):  # O3
        self.write("go.mod", "")
        os.symlink("go.mod", os.path.join(self.tmp, "Cargo.toml"))
        self.write("pyproject.toml", b"\xff")
        res = detect(self.tmp)
        self.assertEqual(res.proposals, (Proposal("test", "go test ./...", "go.mod"), Proposal("build", "go build ./...", "go.mod")))
        self.assertEqual(res.problems, (Problem("Cargo.toml", "symlink; not read"),
                                        Problem("pyproject.toml", "not valid UTF-8")))

    def test_root_checks_run_before_any_source(self):  # O6
        real = os.path.join(self.tmp, "real")
        os.mkdir(real)
        self.all_seven(real)
        link = os.path.join(self.tmp, "link")
        os.symlink(real, link)
        self.assertEqual(detect(link), detect(real))
        self.assertEqual(len(detect(link).proposals), 16)
        for bad in (os.path.join(self.tmp, "nope"), self.tmp.encode()):
            with self.subTest(root=bad), self.assertRaises(GateError):
                detect(bad)

    def test_no_side_effects_with_every_source(self):  # O7
        self.all_seven()
        os.mkdir(os.path.join(self.tmp, "sub"))
        before = snapshot(self.tmp)
        with mock.patch("subprocess.run") as run, mock.patch("os.system") as system, mock.patch("subprocess.Popen") as popen:
            detect(self.tmp)
        self.assertEqual(snapshot(self.tmp), before)
        self.assertFalse(run.called or system.called or popen.called)

    def test_no_side_effects_on_problem_paths(self):  # O7: T4 T5 T7 P2
        os.symlink("x", os.path.join(self.tmp, "Cargo.toml"))
        os.mkdir(os.path.join(self.tmp, "go.mod"))
        os.mkfifo(os.path.join(self.tmp, "gradlew"))
        self.write("mvnw", "x")
        os.chmod(os.path.join(self.tmp, "mvnw"), 0o644)
        self.write("pyproject.toml", b"\xff")
        before = snapshot(self.tmp)
        res = detect(self.tmp)
        self.assertEqual(len(res.problems), 5)
        self.assertEqual(snapshot(self.tmp), before)

    def test_return_types(self):  # O8
        self.all_seven()
        res = detect(self.tmp)
        self.assertIs(type(res.proposals), tuple)
        self.assertIs(type(res.problems), tuple)
        commands = {"npm run test", "npm run lint", "npm run build", "make test", "make lint", "make build", "cargo test",
                    "cargo build", "go test ./...", "go build ./...", "./mvnw test", "./mvnw package", "./gradlew test",
                    "./gradlew build", "python3 -m pytest", "ruff check ."}
        for p in res.proposals:
            self.assertIs(type(p), Proposal)
            self.assertIn(p.slot, SLOTS)
            self.assertIn(p.command, commands)

    def test_monorepo_subdir_not_read(self):  # O5
        os.makedirs(os.path.join(self.tmp, "packages", "a"))
        self.write("package.json", '{"scripts": {"test": "t"}}', root=os.path.join(self.tmp, "packages", "a"))
        self.assertEqual(detect(self.tmp), Detection((), ()))


class MakefileAsciiNameTests(Base):
    """K1 (owner Q-C12-4 (a)): the Makefile name match compares ASCII case only."""

    def probe(self, name: str):
        """detect() on a directory holding only `name`, with lstat simulating a case-insensitive filesystem."""
        with tempfile.TemporaryDirectory() as d:
            self.write(name, "test:\n", root=d)
            real_lstat = os.lstat

            def ci_lstat(path, *a, **k):
                dd, base = os.path.split(path)
                if dd == d:
                    for e in os.listdir(dd):
                        if e.lower() == base.lower():
                            return real_lstat(os.path.join(dd, e), *a, **k)
                return real_lstat(path, *a, **k)
            with mock.patch("os.lstat", ci_lstat):
                return detect(d)

    def test_kelvin_sign_name_is_not_the_makefile(self):  # K1: str.lower() folds U+212A to k
        self.assertEqual("ma\u212aefile".lower(), "makefile")  # the premise: why a str.lower() match accepted it
        self.assertEqual(self.probe("ma\u212aefile"), Detection((), (Problem("makefile", "name not ASCII"),)))

    def test_kelvin_sign_in_the_other_probes(self):  # K1
        self.assertEqual(self.probe("GNUma\u212aefile"), Detection((), (Problem("GNUmakefile", "name not ASCII"),)))
        self.assertEqual(self.probe("Ma\u212aefile"), Detection((), (Problem("makefile", "name not ASCII"),)))

    def test_lstat_failure_on_the_probe_keeps_the_probe_name(self):  # F2: found=False keeps C1.1's fall-back to the probe
        real_lstat = os.lstat

        def deny(path, *a, **k):
            if os.path.basename(path) == "GNUmakefile":
                raise OSError(5, "Input/output error")
            return real_lstat(path, *a, **k)
        with mock.patch("os.lstat", deny):
            res = detect(self.tmp)
        self.assertEqual(res, Detection((), (Problem("GNUmakefile", "Input/output error"),)))

    def test_other_non_ascii_name_is_not_the_makefile(self):  # K1
        self.assertEqual(self.probe("Makefile\u0307"), Detection((), ()))

    def test_ascii_case_variant_still_found(self):  # K1: ASCII case folding stays
        self.assertEqual(self.probe("MAKEFILE"), Detection((Proposal("test", "make test", "MAKEFILE:1 test"),), ()))


class VanishedAndSwappedTests(Base):
    """Block C1 verifier F-C1ver-1 and F-C1ver-2."""

    SOURCES_READ = {"package.json": "{}", "Makefile": "test:\n", "Cargo.toml": "", "go.mod": "", "mvnw": "", "gradlew": "",
                    "pyproject.toml": "[tool.ruff]\n"}

    def test_every_listed_source_gone_by_the_read_is_a_problem(self):  # F-C1ver-1
        for name in (n for n in self.SOURCES_READ if n != "Makefile"):  # the Makefile is probed by lstat (N6 test covers its vanish)
            with self.subTest(name=name), tempfile.TemporaryDirectory() as d:
                with mock.patch("os.listdir", lambda root: [name]):
                    res = detect(d)
                self.assertEqual(res, Detection((), (Problem(name, "No such file or directory"),)))

    def test_symlink_swapped_in_after_the_lstat_is_not_followed(self):  # F-C1ver-2: O_NOFOLLOW in _read_regular
        eloop = os.strerror(errno.ELOOP)
        for name, content in self.SOURCES_READ.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as outside, tempfile.TemporaryDirectory() as d:
                target = os.path.join(outside, "secret")
                with open(target, "w") as fh:
                    fh.write(content)
                os.chmod(target, 0o755)
                os.symlink(target, os.path.join(d, name))
                real_lstat = os.lstat

                def lie(path, *a, **k):  # lstat reports the regular file; the path is a symlink by the time it is opened
                    if os.path.dirname(path) == d and os.path.basename(path) == name:
                        return real_lstat(target, *a, **k)
                    return real_lstat(path, *a, **k)
                with mock.patch("os.lstat", lie):
                    res = detect(d)
                self.assertEqual(res.proposals, ())
                self.assertEqual(res.problems, (Problem(name, eloop),))


if __name__ == "__main__":
    unittest.main()
