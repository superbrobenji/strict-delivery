"""Tests for gates.lib.detect: package.json and Makefile detection, through detect() on real files.

Expected values are written out literally. The Makefile verdicts for each rule-line form are the
results of GNU Make 3.81 (`make -n test` on a one-rule Makefile) recorded in Task C1.1; detect()
never runs make.
"""
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

    def test_bom_makefile_first_line_is_not_a_rule(self):  # GNU Make 3.81: `\ufefftest:` -> "No rule to make target `test'"
        self.assertEqual(self.rules("\ufefftest:\n"), [])

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
    def test_makefile_rules(self):  # R1 R2 R4 R6
        mk = "VAR := test\n.PHONY: test\nbuild test: dep\n\t@echo\nlint:: x\n  check:\n# lint:\n"
        self.assertEqual(self.rules(mk), [("test", "make test", "Makefile:3 test"), ("lint", "make lint", "Makefile:5 lint"),
                                          ("build", "make build", "Makefile:3 build")])

    def test_plain_rules(self):  # R1: GNU Make 3.81 rc 0 (or rc 2 naming the target as a rule)
        for line in ("test:", "test::", "test: dep", "test : x", "test:dep", "test\t:\tx", "test:\t"):
            with self.subTest(line=line):
                self.assertEqual(self.rules(line + "\n\t@echo ran\n"), [("test", "make test", "Makefile:1 test")])

    def test_several_targets_one_line(self):  # R2
        self.assertEqual(self.rules("\nbuild test:\n"), [("test", "make test", "Makefile:2 test"),
                                                        ("build", "make build", "Makefile:2 build")])

    def test_other_slot_names(self):
        self.assertEqual(self.rules("lint:\nbuild:\n"), [("lint", "make lint", "Makefile:1 lint"),
                                                         ("build", "make build", "Makefile:2 build")])

    def test_names_must_match_exactly(self):  # R7 variants: only literal test, lint, build
        self.assertEqual(self.rules("tests:\ntest-all:\nretest:\ntest_one:\nTest:\nbuilds:\n"), [])

    def test_makefile_variable_and_recipe_lines_are_not_rules(self):  # R3 R4 R5 R6: GNU Make 3.81 rc 2 on each
        for mk in ("test=x\n", "test:=x\n", "test := x\n", "test ?= x\n", "test += x\n", "test != x\n",
                   "test ::= x\n", "test::=x\n", "test :::= x\n", "  test := x\n", "  # test:\n", "# test:\n",
                   "\ttest:\n", "x = 1\n\ttest:\n", "all:\n\ttest:\n", "all:\n\t@echo a \\\ntest:\n",
                   "define D\ntest:\nendef\n", ".PHONY: test\n", "$(T):\n", "%:\n", "test.o:\n", "T = test\n$(T):\n",
                   "build ?= x\n", "lint = a\n"):
            with self.subTest(mk=mk):
                self.assertEqual(self.rules(mk), [])

    def test_makefile_rule_after_leading_blanks(self):  # R4: GNU Make 3.81 rc 0, `ran`
        for mk in ("  test:\n\t@echo ran\n", " \ttest:\n\t@echo ran\n", " \t \ttest:\n\t@echo ran\n"):
            with self.subTest(mk=mk):
                self.assertEqual(self.rules(mk), [("test", "make test", "Makefile:1 test")])

    def test_tab_first_is_recipe_even_after_rule(self):  # R5
        self.assertEqual(self.rules("all:\n\ttest:\n\tlint:\n"), [])

    def test_continued_rule_line_joins(self):  # R8 R10: `make test` runs this target
        self.assertEqual(self.rules("x \\\ntest:\n\t@echo ran\n"), [("test", "make test", "Makefile:1 test")])

    def test_continuation_leading_whitespace_and_chain(self):  # R10
        self.assertEqual(self.rules("\nx \\\n \t  lint \\\n    build:\n"),
                         [("lint", "make lint", "Makefile:2 lint"), ("build", "make build", "Makefile:2 build")])
        # GNU Make 3.81: `x\` then `test:` joins to `x test:`, and `make test` runs
        self.assertEqual(self.rules("x\\\ntest:\n\t@echo ran\n"), [("test", "make test", "Makefile:1 test")])

    def test_continuation_odd_backslashes_only(self):  # GNU Make 3.81: `x = 1 \\` then `test:` runs test
        self.assertEqual(self.rules("x = 1 \\\\\ntest:\n\t@echo ran\n"), [("test", "make test", "Makefile:2 test")])
        self.assertEqual(self.rules("x = 1 \\\\\\\ntest:\n\t@echo ran\n"), [])  # three: continuation

    def test_continued_recipe_line_stays_recipe(self):  # R9: `make test` finds no rule
        self.assertEqual(self.rules("all:\n\t@echo a \\\ntest:\n"), [])
        self.assertEqual(self.rules("all:\n\t@echo a \\\n\ttest:\n"), [])

    def test_continued_comment_swallows_next_line(self):  # GNU Make 3.81: `# c \` then `test:` is a comment
        self.assertEqual(self.rules("# c \\\ntest:\n"), [])

    def test_continuation_at_end_of_file(self):  # R11: 3.81 reads `test: \` as target test, prerequisite `\`
        self.assertEqual(self.rules("test: \\"), [("test", "make test", "Makefile:1 test")])
        self.assertEqual(self.rules("x\ntest: \\\n"), [("test", "make test", "Makefile:2 test")])

    def test_define_endef(self):  # R12
        self.assertEqual(self.rules("define D\ntest:\nendef\nlint:\n"), [("lint", "make lint", "Makefile:4 lint")])

    def test_define_variants_and_nesting(self):  # R12: 3.81 reads `override define` and nested defines like define
        self.assertEqual(self.rules("override define D\ntest:\nendef\nlint:\n"), [("lint", "make lint", "Makefile:4 lint")])
        self.assertEqual(self.rules("define D\ndefine E\nendef\ntest:\nendef\nbuild:\n"),
                         [("build", "make build", "Makefile:6 build")])
        self.assertEqual(self.rules("  define D\ntest:\n  endef\nlint:\n"), [("lint", "make lint", "Makefile:4 lint")])
        self.assertEqual(self.rules("define D # c\ntest:\nendef # c\nlint:\n"), [("lint", "make lint", "Makefile:4 lint")])

    def test_define_names_are_not_prefixes(self):
        # `defined:` / `endefs:` are ordinary targets and never open or close a define
        self.assertEqual(self.rules("defined:\ntest:\nendefs:\nlint:\n"),
                         [("test", "make test", "Makefile:2 test"), ("lint", "make lint", "Makefile:4 lint")])

    def test_non_literal_target_groups_are_not_rules(self):  # R7: the target group admits literal names only
        for mk in ("test $X:\n", "build $(X) test:\n", "test %:\n", ".x test:\n", "#x test:\n", "test = a:\n", "$X test:\n", "%x test:\n", "a=b test:\n"):
            with self.subTest(mk=mk):
                self.assertEqual(self.rules(mk), [])

    def test_define_body_lines_that_only_start_like_endef(self):
        self.assertEqual(self.rules("define D\nendefs:\ntest:\nendef\nlint:\n"), [("lint", "make lint", "Makefile:5 lint")])

    def test_tab_led_define_and_endef_follow_make_381(self):  # F-C11r-2: each verdict is `make -n test` on 3.81
        cases = [
            ("tab endef inside a body does not close", "define D\n\tendef\ntest:\n\t@echo ran\nendef\n", []),
            ("tab define before any rule opens", "\tdefine D\ntest:\n\t@echo ran\nendef\nlint:\n", [("lint", "Makefile:5 lint")]),
            ("tab define after an assignment opens", "x = 1\n\tdefine D\ntest:\n\t@echo ran\nendef\n", []),
            ("tab define in a recipe is a recipe line", "all:\n\tdefine D\ntest:\n\t@echo ran\n", [("test", "Makefile:3 test")]),
            ("tab define after blank and comment lines in a recipe", "all:\n\n# c\n\tdefine D\ntest:\n\t@echo ran\n",
             [("test", "Makefile:5 test")]),
            ("tab define after an include opens", "all:\ninclude /dev/null\n\tdefine D\ntest:\n\t@echo ran\nendef\n", []),
            ("tab define after a conditional stays a recipe line", "all:\nifdef X\nendif\n\tdefine D\ntest:\n\t@echo ran\n",
             [("test", "Makefile:5 test")]),
            ("tab define in a body does not nest", "define D\n\tdefine E\nendef\ntest:\n\t@echo ran\n", [("test", "Makefile:4 test")]),
            ("space then tab endef closes", "define D\n \tendef\ntest:\n\t@echo ran\n", [("test", "Makefile:3 test")]),
            ("space then tab define opens", " \tdefine D\ntest:\n\t@echo ran\nendef\nlint:\n", [("lint", "Makefile:5 lint")]),
            ("override define does not nest in a body", "define D\noverride define E\nendef\ntest:\n\t@echo ran\n",
             [("test", "Makefile:4 test")]),
            ("export define is not a define", "export define D\ntest:\n", [("test", "Makefile:2 test")]),
            ("private define is not a define", "private define D\ntest:\n", [("test", "Makefile:2 test")]),
            ("rule then assignment then tab define", "all:\nx = 1\n\tdefine D\ntest:\nendef\n", []),
            ("tab-led blank line outside a recipe opens nothing", "\t\ntest:\n\t@echo ran\n", [("test", "Makefile:2 test")]),
            ("a define does not end the recipe context", "all:\ndefine D\nendef\n\tdefine E\ntest:\n\t@echo ran\nendef\n",
             [("test", "Makefile:5 test")]),
            ("assignment with a later colon ends the recipe context", "all:\nx = a:b\n\tdefine D\ntest:\n\t@echo ran\nendef\n", []),
            ("colon-equals ends the recipe context", "all:\nx := 1\n\tdefine D\ntest:\n\t@echo ran\nendef\n", []),
            ("double-colon rule keeps recipe context", "all::\n\tdefine D\ntest:\n", [("test", "Makefile:3 test")]),
        ]
        for label, mk, expect in cases:
            with self.subTest(label):
                self.assertEqual(self.rules(mk), [(sl, "make " + sl, src) for sl, src in expect])

    def test_target_specific_variables_and_directives_are_not_rules(self):  # Q-C11r-1 (b): make 3.81 rc 2 "No rule"
        for mk in ("test: X = 1\n", "test: X := 1\n", "test: X += 1\n", "test: X ?= 1\n", "test: X != 1\n", "test: a=b\n",
                   "test:: X = 1\n", "test: export X = 1\n", "test: override X = 1\n", "export test:\n", "unexport test:\n",
                   "override test:\n", "private test:\n", "vpath test: x\n", "include test:\n", "-include test:\n",
                   "sinclude test:\n", "undefine test:\n", "  export test:\n", "build test: X = 1\n"):
            with self.subTest(mk=mk):
                self.assertEqual(self.rules(mk), [])

    def test_target_specific_variable_does_not_hide_the_real_rule(self):  # source cites the rule line
        self.assertEqual(self.rules("test: X = 1\ntest:\n\t@echo ran\n"), [("test", "make test", "Makefile:2 test")])

    def test_equals_after_semicolon_or_comment_is_not_an_assignment(self):  # make 3.81 rc 0 on `test: ; FOO=1 echo ran`
        for mk in ("test: ; FOO=1 echo ran\n", "test: dep # a=b\n", "test: dep ; a=b\n"):
            with self.subTest(mk=mk):
                self.assertEqual(self.rules(mk), [("test", "make test", "Makefile:1 test")])

    def test_directive_names_only_matter_as_first_word(self):  # a target called like a directive, and slots after one
        self.assertEqual(self.rules("include:\ntest: include\nbuild export:\n"),
                         [("test", "make test", "Makefile:2 test"), ("build", "make build", "Makefile:3 build")])

    def test_conditionals_do_not_hide_rules(self):  # Q-C11r-2 (a): targets inside ifeq/ifdef are proposed
        self.assertEqual(self.rules("ifeq (a,b)\ntest:\nelse\nlint:\nendif\n"),
                         [("test", "make test", "Makefile:2 test"), ("lint", "make lint", "Makefile:4 lint")])

    def test_define_without_endef_skips_rest(self):  # R13: 3.81 stops with "missing `endef'"
        self.assertEqual(self.rules("define D\ntest:\nlint:\n"), [])

    def test_crlf(self):  # R14
        self.assertEqual(self.rules("test:\r\n\t@echo ran\r\n"), [("test", "make test", "Makefile:1 test")])
        self.assertEqual(self.rules("x \\\r\ntest:\r\n\t@echo ran\r\n"), [("test", "make test", "Makefile:1 test")])
        self.assertEqual(self.rules("all:\r\n\t@echo a \\\r\ntest:\r\n"), [])
        self.assertEqual(self.rules("test := x\r\n"), [])

    def test_no_final_newline(self):  # R15
        self.assertEqual(self.rules("a:\ntest:"), [("test", "make test", "Makefile:2 test")])

    def test_duplicate_definition(self):  # R16
        self.assertEqual(self.rules("a:\ntest:\nb:\nc:\ntest::\n\t@echo\n"), [("test", "make test", "Makefile:2 test")])

    def test_line_splitting_on_newline_only(self):  # R17: 3.81 finds no rule `test` after \f or U+00A0
        self.assertEqual(self.rules("x\x0ctest:\n"), [])
        self.assertEqual(self.rules("x\u00a0test:\n"), [])
        self.assertEqual(self.rules("a\x0c\ntest:\n"), [("test", "make test", "Makefile:2 test")])
        self.assertEqual(self.rules("a\u2028b\u0085c\x1c\ntest:\n"), [("test", "make test", "Makefile:2 test")])
        self.assertEqual(self.rules("# x\x0b\x0c\u2028\ntest:\n"), [("test", "make test", "Makefile:2 test")])

    def test_lone_cr_is_not_a_line_end(self):
        self.assertEqual(self.rules("a\rtest:\n"), [])

    def test_empty_makefile(self):
        self.assertEqual(self.rules(""), [])


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


if __name__ == "__main__":
    unittest.main()
