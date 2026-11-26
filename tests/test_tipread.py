"""Tests for gates.lib.tipread (Task 5b.3, table task-5b.3-domain.md rows F26, F27, FH4, FH6, FH7, FK1-FK3, R4-1,
R4-1b, R4-1d, R4-2, R4-2b)."""
import os
import unittest
from unittest import mock

from gates.lib import gitinfo, tipread
from gates.lib.result import GateError
from tests.helpers import GitIsolatedTestCase, git, make_repo
from tests.tipkinds import BAD_KINDS, refusal, set_entry

REF = "refs/heads/main"


class ShowFile(GitIsolatedTestCase):
    def setUp(self):
        super().setUp()
        make_repo(self.work)

    def test_show_file_entry_kinds(self):  # F26, FH6, FH7, FK2
        for name in ("a/b.md", "odd\nname.md", "ࡰ/x.md"):
            with self.subTest("regular " + name):
                set_entry(self.work, REF, name, "regular", "hello\n")
                self.assertEqual(tipread.show_file(self.work, REF, name), "hello\n")
        with self.subTest("executable"):
            set_entry(self.work, REF, "run.sh", "executable", "go\n")
            self.assertEqual(tipread.show_file(self.work, REF, "run.sh"), "go\n")
        with self.subTest("absent"):
            self.assertIsNone(tipread.show_file(self.work, REF, "nothing/here.md"))
        for name in ("a/b.md", "odd\nname.md", "ࡰ/x.md"):
            for kind, _ in BAD_KINDS:
                with self.subTest("%s %s" % (kind, "odd-name" if name != "a/b.md" else "plain")):
                    set_entry(self.work, REF, name, kind, "hello\n")
                    with self.assertRaises(GateError) as cm:
                        tipread.show_file(self.work, REF, name)
                    self.assertEqual(str(cm.exception), refusal(REF, name))
        with self.subTest("non-utf8"):
            set_entry(self.work, REF, "bad.md", "non-utf8")
            with self.assertRaises(GateError) as cm:
                tipread.show_file(self.work, REF, "bad.md")
            self.assertEqual(str(cm.exception), "bad.md: not valid UTF-8")
        for path in ("../x", "/abs", "a//b", "a/../b"):
            with self.subTest("dotdot " + path):
                with self.assertRaises(GateError):
                    tipread.show_file(self.work, REF, path)

    def test_show_file_empty_path_is_absent(self):  # R2-3: the empty path (the root) names no file: None, no refusal
        self.assertIsNone(tipread.show_file(self.work, REF, ""))

    def test_show_file_parent_symlink_absent(self):  # FH4
        set_entry(self.work, REF, "d", "symlink", "x\n")  # d -> a regular file; below it nothing exists
        self.assertIsNone(tipread.show_file(self.work, REF, "d/handoff.md"))

    def test_show_file_digit_names(self):  # FK1
        for n in (4300, 4301):
            with self.subTest(n):
                name = "9" * n + ".yml"
                set_entry(self.work, REF, name, "regular", "t\n")
                self.assertEqual(tipread.show_file(self.work, REF, name), "t\n")
                set_entry(self.work, REF, name, "symlink", "t\n")
                with self.assertRaises(GateError) as cm:
                    tipread.show_file(self.work, REF, name)
                self.assertEqual(str(cm.exception), refusal(REF, name))

    def test_show_file_propagates_keyboard_interrupt(self):  # FK3
        set_entry(self.work, REF, "a.md", "regular")
        with mock.patch.object(gitinfo, "_run", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                tipread.show_file(self.work, REF, "a.md")
        with open(tipread.__file__, encoding="utf-8") as fh:
            src = fh.read()
        for word in ("except", "BaseException", "casefold", "isprintable", "unicodedata", ".lower(", "int("):
            code = [ln for ln in src.split("\n") if not ln.lstrip().startswith(("#", '"""'))]
            body = "\n".join(code[code.index("def show_file(root: str, ref: str, path: str) -> Optional[str]:"):])
            if word == "except":
                self.assertEqual(body.count("except UnicodeDecodeError"), body.count("except"))
            else:
                self.assertNotIn(word, body)

    def test_show_file_changed_while_read(self):  # R2-2: the listing gave a regular entry, then show found none
        for mode_kind in ("regular", "executable"):
            with self.subTest(mode_kind):
                set_entry(self.work, REF, "a/b.md", mode_kind, "hello\n")
                with mock.patch.object(gitinfo, "show", return_value=None) as show:
                    with self.assertRaises(GateError) as cm:
                        tipread.show_file(self.work, REF, "a/b.md")
                self.assertEqual(str(cm.exception), "refs/heads/main:a/b.md: changed while it was being read")
                self.assertEqual(show.call_count, 1)
        with self.subTest("absent is not this refusal"):  # no entry: None before any show call
            with mock.patch.object(gitinfo, "show", return_value=None) as show:
                self.assertIsNone(tipread.show_file(self.work, REF, "nothing/here.md"))
            self.assertEqual(show.call_count, 0)
        with self.subTest("non-regular is the other refusal"):  # the kind is refused before show is called
            set_entry(self.work, REF, "p.md", "symlink", "hello\n")
            with mock.patch.object(gitinfo, "show", return_value=None) as show:
                with self.assertRaises(GateError) as cm:
                    tipread.show_file(self.work, REF, "p.md")
            self.assertEqual(str(cm.exception), refusal(REF, "p.md"))
            self.assertEqual(show.call_count, 0)

    def test_show_file_propagates_keyboard_interrupt_from_show(self):  # R2-K: an interrupt in the read of the regular entry
        set_entry(self.work, REF, "a.md", "regular")
        with mock.patch.object(gitinfo, "show", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                tipread.show_file(self.work, REF, "a.md")

    def test_show_file_matches_the_entry_by_exact_name(self):  # R2-3: a sibling or a prefix of the path is not the entry
        set_entry(self.work, REF, "d/ab.md", "symlink", "x\n")
        set_entry(self.work, REF, "d/b.md", "regular", "right\n")
        self.assertEqual(tipread.show_file(self.work, REF, "d/b.md"), "right\n")
        self.assertIsNone(tipread.show_file(self.work, REF, "d/a.md"))
        self.assertIsNone(tipread.show_file(self.work, REF, "d/ab"))
        with self.assertRaises(GateError) as cm:
            tipread.show_file(self.work, REF, "d/ab.md")
        self.assertEqual(str(cm.exception), refusal(REF, "d/ab.md"))

    def test_show_contract_unchanged(self):  # F27: gitinfo.show keeps returning None for a non-regular entry
        for kind, _ in BAD_KINDS:
            with self.subTest(kind):
                set_entry(self.work, REF, "p.md", kind)
                self.assertIsNone(gitinfo.show(self.work, REF, "p.md"))
                self.assertEqual(gitinfo.ls_tree(self.work, REF, ""), [])  # ls_tree hides the non-regular entry
        set_entry(self.work, REF, "p.md", "regular", "q\n")
        self.assertEqual(gitinfo.show(self.work, REF, "p.md"), "q\n")

    def test_show_file_validations_kept(self):  # R4-1d: every input the helper refused at 87b80fc is refused the same way
        set_entry(self.work, REF, "a.md", "regular", "t\n")
        os.makedirs(os.path.join(self.work, "sub"))
        for label, root, ref, path, want in validation_cases(self.work, self.tmp):
            with self.subTest(label):
                with self.assertRaises(GateError) as cm:
                    tipread.show_file(root, ref, path)
                self.assertEqual(str(cm.exception), want)


P = "d/a.md"
REFUSED = "refused"  # the expected value "refused by name" (tipkinds.refusal at the ref read)


def validation_cases(work: str, tmp: str) -> list:
    """(label, root, ref, path, error text) for each validation of the replaced call (R4-1d), texts written by hand."""
    return [("dotdot path", work, REF, "../x", "ls-tree: path must not hold a '..' segment"),
            ("empty segment", work, REF, "a//b", "ls-tree: path must be a normalised repo-relative path (no '.', empty "
                                                 "segment, leading or trailing '/')"),
            ("empty root", "", REF, "a.md", "root must be a string"),
            ("bytes root", work.encode(), REF, "a.md", "root must be a string"),
            ("empty ref", work, "", "a.md", "ref must be a non-empty string"),
            ("bytes ref", work, b"main", "a.md", "ref must be a non-empty string"),
            ("dash ref", work, "-p", "a.md", "ref must not start with '-'"),
            ("caret ref", work, "^main", "a.md", "ref must not start with '^'"),
            ("long hex ref", work, "a" * 41, "a.md", "ref must not hold more than 40 hex digits in a row"),
            ("subdirectory root", os.path.join(work, "sub"), REF, "a.md",
             "git rev-parse --show-toplevel: root must be the repository top level"),
            ("not a repository", tmp, REF, "a.md", "git rev-parse --show-toplevel failed (exit 128)"),
            ("unknown ref", work, "refs/heads/nothing", "a.md", "git ls-tree failed (exit 128)")]


class ReplaceView(GitIsolatedTestCase):
    """R4-1, R4-2b (F-20261126-a826): the kind and the blob are read in ONE view, the replace-honoured view of
    ``gitinfo.show`` on main; real ``git replace`` fixtures, expected values written by hand from row R4-1."""

    def setUp(self):
        super().setUp()
        make_repo(self.work)

    def pair(self, kind1: str, text1: str, kind2: str, text2: str) -> tuple:
        """c1 on main with ``P`` as ``kind1``, and c2 (same parent, ``P`` as ``kind2``) on a side ref; (c1, c2)."""
        c1 = set_entry(self.work, REF, P, kind1, text1)
        git(self.work, "update-ref", "refs/heads/repl", git(self.work, "rev-parse", c1 + "^"))
        return c1, set_entry(self.work, "refs/heads/repl", P, kind2, text2)

    def check(self, fn, ref: str, want) -> None:
        if want == REFUSED:
            with self.assertRaises(GateError) as cm:
                fn(self.work, ref, P)
            self.assertEqual(str(cm.exception), refusal(ref, P))
        elif type(want) is bool:
            self.assertIs(fn(self.work, ref, P), want)
        else:
            self.assertEqual(fn(self.work, ref, P), want)

    # (label, c1 kind, c2 kind, show_file with `git replace c1 c2`, show_file without a replace ref (control))
    CASES = (("a regular dropped", "regular", "absent", None, "one\n"),
             ("b regular added", "absent", "regular", "two\n", None),
             ("c content changed", "regular", "regular", "two\n", "one\n"),
             ("d symlink made regular", "symlink", "regular", "two\n", REFUSED),
             ("e regular made symlink", "regular", "symlink", REFUSED, "one\n"),
             ("f regular made tree", "regular", "tree", REFUSED, "one\n"))

    def run_cases(self, fn, value) -> None:
        for label, kind1, kind2, replaced, control in self.CASES:
            with self.subTest(label):
                c1, c2 = self.pair(kind1, "one\n", kind2, "two\n")
                self.check(fn, c1, value(control))
                git(self.work, "replace", c1, c2)
                try:
                    self.check(fn, c1, value(replaced))
                    if fn is tipread.show_file and replaced != REFUSED:  # = gitinfo.show (unchanged since edb6aa7)
                        self.assertEqual(gitinfo.show(self.work, c1, P), replaced)
                finally:
                    git(self.work, "replace", "-d", c1)

    def test_show_file_one_view_under_replace(self):  # R4-1
        self.run_cases(tipread.show_file, lambda want: want)

    def test_is_file_one_view_under_replace(self):  # R4-2b: the probe reads the same view
        self.run_cases(tipread.is_file, lambda want: {None: False, "one\n": True, "two\n": True, REFUSED: REFUSED}[want])


class IsFile(GitIsolatedTestCase):
    """R4-2 (F-20261126-swwg): the mode-only existence probe of F28/F29 never reads or decodes the blob, as
    ``gitinfo.blob_exists`` on main."""

    def setUp(self):
        super().setUp()
        make_repo(self.work)

    def test_is_file_entry_kinds(self):
        for kind in ("regular", "executable", "non-utf8"):
            with self.subTest(kind):
                set_entry(self.work, REF, P, kind, "t\n")
                real = gitinfo._run
                with mock.patch.object(gitinfo, "_run", side_effect=real) as run, \
                        mock.patch.object(gitinfo, "show", side_effect=AssertionError("blob read")):
                    self.assertIs(tipread.is_file(self.work, REF, P), True)
                self.assertEqual([c for c in run.call_args_list if "cat-file" in str(c)], [])
        with self.subTest("absent"):
            set_entry(self.work, REF, P, "absent")
            self.assertIs(tipread.is_file(self.work, REF, P), False)
        with self.subTest("parent symlink"):  # FH4: git does not follow a tree symlink, so nothing is below it
            set_entry(self.work, REF, "s", "symlink", "x\n")
            self.assertIs(tipread.is_file(self.work, REF, "s/a.md"), False)
        for kind, _ in BAD_KINDS:
            with self.subTest(kind):
                set_entry(self.work, REF, P, kind, "t\n")
                with self.assertRaises(GateError) as cm:
                    tipread.is_file(self.work, REF, P)
                self.assertEqual(str(cm.exception), refusal(REF, P))

    def test_is_file_validations(self):  # R4-1d for the probe: the same refusals as show_file
        set_entry(self.work, REF, "a.md", "regular", "t\n")
        os.makedirs(os.path.join(self.work, "sub"))
        for label, root, ref, path, want in validation_cases(self.work, self.tmp):
            with self.subTest(label):
                with self.assertRaises(GateError) as cm:
                    tipread.is_file(root, ref, path)
                self.assertEqual(str(cm.exception), want)


class Entries(GitIsolatedTestCase):
    """R4-1b, R4-1d: ``tipread.entries`` lists as ``gitinfo.ls_tree_entries`` does (the same checks and parse), in the
    replace-honoured view."""

    def setUp(self):
        super().setUp()
        make_repo(self.work)

    def test_entries_validations(self):
        os.makedirs(os.path.join(self.work, "sub"))
        for label, root, ref, _, want in validation_cases(self.work, self.tmp)[2:]:
            with self.subTest(label):
                with self.assertRaises(GateError) as cm:
                    tipread.entries(root, ref, "d")
                self.assertEqual(str(cm.exception), want)
        for label, directory, want in (("bytes directory", b"d", "directory must be a string"),
                                       ("dotdot directory", "../d", "ls-tree: directory must not hold a '..' segment"),
                                       ("slash directory", "d/", "ls-tree: directory must be a normalised repo-relative "
                                                                 "path (no '.', empty segment, leading or trailing '/')")):
            with self.subTest(label):
                with self.assertRaises(GateError) as cm:
                    tipread.entries(self.work, REF, directory)
                self.assertEqual(str(cm.exception), want)

    def test_entries_listing(self):
        set_entry(self.work, REF, "d/a.md", "regular", "t\n")
        set_entry(self.work, REF, "d/x", "gitlink")
        self.assertEqual(tipread.entries(self.work, REF, "d"),
                         [("100644", "blob", "d/a.md"), ("160000", "commit", "d/x")])
        self.assertEqual(tipread.entries(self.work, REF, "nothing"), [])
        with self.subTest("unreadable entry"):  # a listing line that is not <mode> <type> <id>\t<path>
            real = gitinfo._run

            def bad_listing(root, name, args, **kw):
                done = real(root, name, args, **kw)
                if name == "ls-tree":
                    done.stdout = b"100644 blob\td/a.md\0"
                return done
            with mock.patch.object(gitinfo, "_run", side_effect=bad_listing):
                with self.assertRaises(GateError) as cm:
                    tipread.entries(self.work, REF, "d")
            self.assertEqual(str(cm.exception), "git ls-tree gave an entry that cannot be read")
        with self.subTest("non-UTF-8 name"):  # a sibling whose name is not UTF-8 is refused, as by ls_tree_entries
            set_entry(self.work, REF, "d/b\udcff.md", "regular", "t\n")
            with self.assertRaises(GateError) as cm:
                tipread.show_file(self.work, REF, "d/a.md")
            self.assertEqual(str(cm.exception), "git ls-tree gave output that is not valid UTF-8")

    def test_entries_replace_view(self):  # R4-1b: the replacement's tree is listed, as by gitinfo.ls_tree at 9b3a1c6
        c1 = set_entry(self.work, REF, "d/a.md", "regular", "t\n")
        git(self.work, "update-ref", "refs/heads/repl", git(self.work, "rev-parse", c1 + "^"))
        c2 = set_entry(self.work, "refs/heads/repl", "d/a.md", "symlink", "t\n")
        self.assertEqual(tipread.entries(self.work, c1, "d"), [("100644", "blob", "d/a.md")])
        git(self.work, "replace", c1, c2)
        self.assertEqual(tipread.entries(self.work, c1, "d"), [("120000", "blob", "d/a.md")])
        self.assertEqual(gitinfo.ls_tree(self.work, c1, "d"), [])  # main's call: the replacement holds no regular file


if __name__ == "__main__":
    unittest.main()
