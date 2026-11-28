"""Tests for gates.lib.tipread (Task 5b.3, table task-5b.3-domain.md rows F26, F27, FH4, FH6, FH7, FK1-FK3, R4-1,
R4-1b, R4-1d, R4-2, R4-2b, R5-1, R5-2, R5-H, R5-K, R6-1, R6-2)."""
import os
import posixpath
import random
import sys
import tempfile
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
        # R5-K: an interrupt (and, where the interpreter has it, a BaseExceptionGroup) from each git call of each public
        # function propagates; the calls are named as gitinfo._run names them
        errors = [KeyboardInterrupt] + ([BaseExceptionGroup] if sys.version_info >= (3, 11) else [])  # noqa: F821
        real = gitinfo._run
        for fn, arg, names in ((tipread.show_file, "a.md", ("rev-parse --show-toplevel", "ls-tree", "cat-file blob")),
                               (tipread.is_file, "a.md", ("rev-parse --show-toplevel", "ls-tree")),
                               (tipread.entries, "", ("rev-parse --show-toplevel", "ls-tree"))):
            for name in names:
                for error in errors:
                    with self.subTest(fn=fn.__name__, call=name, error=error.__name__):
                        def raising(root, run_name, args, **kw):
                            if run_name == name:
                                raise error if error is KeyboardInterrupt else error("g", [KeyboardInterrupt()])
                            return real(root, run_name, args, **kw)
                        with mock.patch.object(gitinfo, "_run", side_effect=raising) as run:
                            with self.assertRaises(error):
                                fn(self.work, REF, arg)
                        self.assertIn(name, [c[0][1] for c in run.call_args_list])
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
        self.assertIn(("040000", "tree", "d"), tipread.entries(self.work, REF, ""))  # "" lists the root
        # git ls-tree never globs, with or without --literal-pathspecs: this pins that, not the flag (the flag is
        # pinned by MagicNames: the pathspec-magic names of R6-2, which only a literal pathspec reads as names)
        self.assertEqual(tipread.entries(self.work, REF, "[d]"), [])
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
        with self.subTest("non-UTF-8 name"):  # a listed name that is not UTF-8 is refused, as by ls_tree_entries
            set_entry(self.work, REF, "d/b\udcff.md", "regular", "t\n")
            with self.assertRaises(GateError) as cm:
                tipread.entries(self.work, REF, "d")
            self.assertEqual(str(cm.exception), "git ls-tree gave output that is not valid UTF-8")
            # R5-2 (F-20261126-g6un): show_file and is_file decode no sibling name (test_sibling_name_not_utf8)
            self.assertEqual(tipread.show_file(self.work, REF, "d/a.md"), "t\n")

    def test_entries_replace_view(self):  # R4-1b: the replacement's tree is listed, as by gitinfo.ls_tree at 9b3a1c6
        c1 = set_entry(self.work, REF, "d/a.md", "regular", "t\n")
        git(self.work, "update-ref", "refs/heads/repl", git(self.work, "rev-parse", c1 + "^"))
        c2 = set_entry(self.work, "refs/heads/repl", "d/a.md", "symlink", "t\n")
        self.assertEqual(tipread.entries(self.work, c1, "d"), [("100644", "blob", "d/a.md")])
        git(self.work, "replace", c1, c2)
        self.assertEqual(tipread.entries(self.work, c1, "d"), [("120000", "blob", "d/a.md")])
        self.assertEqual(gitinfo.ls_tree(self.work, c1, "d"), [])  # main's call: the replacement holds no regular file


class S(str):
    """A ``str`` subclass: refused wherever an exact ``str`` is asked for (owner Q-RS4-1 (A))."""


class ExactTypes(GitIsolatedTestCase):
    """R5-1 (F-20261126-yyqv): every parameter of ``show_file``, ``is_file`` and ``entries`` takes an exact ``str``; a
    ``str`` subclass, ``bytes``, ``None`` or an ``int`` is refused with a named GateError before any git call. The
    texts are written by hand from row R5-1 (``root``, ``ref`` and ``directory`` keep their texts)."""

    def setUp(self):
        super().setUp()
        make_repo(self.work)
        set_entry(self.work, REF, P, "regular", "one\n")

    def test_exact_types(self):
        with self.subTest("exact str accepted"):
            self.assertEqual(tipread.show_file(self.work, REF, P), "one\n")
            self.assertIs(tipread.is_file(self.work, REF, P), True)
            self.assertEqual(tipread.entries(self.work, REF, "d"), [("100644", "blob", P)])
        values = (("str subclass", S), ("bytes", lambda v: v.encode("utf-8")), ("None", lambda v: None),
                  ("int", lambda v: 1))
        texts = {"root": "root must be a string", "ref": "ref must be a non-empty string",
                 "path": "path must be a string", "directory": "directory must be a string"}
        for fn, last, good in ((tipread.show_file, "path", P), (tipread.is_file, "path", P),
                               (tipread.entries, "directory", "d")):
            for i, param in enumerate(("root", "ref", last)):
                for label, make in values:
                    with self.subTest(fn=fn.__name__, param=param, value=label):
                        args = [self.work, REF, good]
                        args[i] = make(args[i])
                        with mock.patch.object(gitinfo, "_run", side_effect=AssertionError("git called")):
                            with self.assertRaises(GateError) as cm:
                                fn(*args)
                        self.assertEqual(str(cm.exception), texts[param])


SIB = "b\udcff.md"  # git is given the bytes b"b\xff.md" (os.fsencode, as for every argument): a name that is not UTF-8
NONUTF8 = "not valid UTF-8"  # the expected value "gitinfo.show's refusal of a regular blob that is not UTF-8"


def put_raw(root: str, ref: str, name: str, mode: str, data: bytes) -> None:
    """Commit onto ``ref`` one entry ``name`` with ``mode`` and blob ``data`` through a throwaway index (a symlink whose
    name is not UTF-8: ``set_entry`` writes the link target from the name as UTF-8 text)."""
    with tempfile.TemporaryDirectory() as td:
        env = {"GIT_INDEX_FILE": os.path.join(td, "index")}
        blob = os.path.join(td, "blob")
        with open(blob, "wb") as fh:
            fh.write(data)
        sha = git(root, "hash-object", "-w", blob, env=env)
        git(root, "read-tree", ref, env=env)
        git(root, "update-index", "--add", "--cacheinfo", "%s,%s,%s" % (mode, sha, name), env=env)
        git(root, "update-ref", ref, git(root, "commit-tree", git(root, "write-tree", env=env), "-p", ref, "-m", "raw"))


class SiblingNames(GitIsolatedTestCase):
    """R5-2 (F-20261126-g6un): the verdict of ``show_file`` and ``is_file`` depends only on the entry's own kind and
    bytes; a sibling whose name is not UTF-8 (or holds a tab or a newline), in the entry's folder or at the root, changes
    nothing. Expected values written by hand from row R5-2; for every regular and absent case they are the values of
    ``gitinfo.show`` / ``gitinfo.blob_exists``, unchanged since edb6aa7, which the test also asserts (the blame run)."""

    def setUp(self):
        super().setUp()
        make_repo(self.work)

    SIBLINGS = (("non-UTF-8 regular", SIB, "regular"), ("non-UTF-8 symlink", SIB, "symlink"),
                ("non-UTF-8 tree", SIB, "tree"), ("tab", "b\tx.md", "regular"), ("newline", "b\nx.md", "regular"))
    # (entry kind, show_file, is_file)
    ENTRIES = (("regular", "one\n", True), ("executable", "one\n", True), ("non-utf8", NONUTF8, True),
               ("absent", None, False), ("symlink", REFUSED, REFUSED), ("tree", REFUSED, REFUSED),
               ("gitlink", REFUSED, REFUSED))

    def expect(self, fn, path: str, want, text: str = "") -> None:
        if want in (REFUSED, NONUTF8) or text:
            with self.assertRaises(GateError) as cm:
                fn(self.work, REF, path)
            self.assertEqual(str(cm.exception), text or (refusal(REF, path) if want == REFUSED else path + ": " + NONUTF8))
        elif type(want) is bool:
            self.assertIs(fn(self.work, REF, path), want)
        else:
            self.assertEqual(fn(self.work, REF, path), want)

    def test_sibling_name_not_utf8(self):
        for folder in ("d", ""):
            path = posixpath.join(folder, "a.md")
            for label, name, kind in self.SIBLINGS:
                sib = posixpath.join(folder, name)
                if kind == "symlink":
                    put_raw(self.work, REF, sib, "120000", b"keep.md")
                else:
                    set_entry(self.work, REF, sib, kind, "s\n")
                for entry, shown, exists in self.ENTRIES:
                    with self.subTest(folder=folder or "<root>", sibling=label, entry=entry):
                        set_entry(self.work, REF, path, entry, "one\n")
                        self.expect(tipread.show_file, path, shown)
                        self.expect(tipread.is_file, path, exists)
                        if shown != REFUSED:  # the edb6aa7 verdict (gitinfo.py is unchanged since edb6aa7)
                            self.expect(gitinfo.show, path, shown)
                            self.expect(gitinfo.blob_exists, path, exists)
                if not folder:
                    with self.subTest(folder="<root>", sibling=label, entry="the empty path"):  # R2-3: names no file
                        self.assertIsNone(tipread.show_file(self.work, REF, ""))
                        self.assertIs(tipread.is_file(self.work, REF, ""), False)
                set_entry(self.work, REF, sib, "absent")

    def test_kind_read_lists_the_entry_only(self):  # R5-2: the kind read lists `path` itself, never its folder
        set_entry(self.work, REF, "d/" + SIB, "regular", "s\n")
        set_entry(self.work, REF, P, "regular", "one\n")
        real = gitinfo._run
        for fn, want, reads in ((tipread.show_file, "one\n", 2), (tipread.is_file, True, 1)):
            with self.subTest(fn.__name__):
                with mock.patch.object(gitinfo, "_run", side_effect=real) as run:
                    self.assertEqual(fn(self.work, REF, P), want)
                # the kind read, then (show_file) gitinfo.show's own listing of the same entry
                self.assertEqual([c[0][2] for c in run.call_args_list if c[0][1] == "ls-tree"],
                                 [["ls-tree", "-z", "--full-tree", REF, "--", P]] * reads)

    def test_path_not_utf8(self):  # the path itself holds bytes that are not UTF-8: gitinfo.show's verdict at edb6aa7
        set_entry(self.work, REF, "d/" + SIB, "regular", "s\n")
        cases = (("names a regular entry", "d/" + SIB, "git ls-tree gave output that is not valid UTF-8"),
                 ("names a symlink entry", "d/" + SIB, "git ls-tree gave output that is not valid UTF-8"),
                 ("not encodable", "d/b\ud800.md", "git ls-tree failed: unusable argument"),
                 ("names no entry", "d/zz\udcfe.md", ""))
        for label, path, text in cases:
            with self.subTest(label):
                if label == "names a symlink entry":
                    put_raw(self.work, REF, path, "120000", b"keep.md")
                for fn, absent in ((tipread.show_file, None), (tipread.is_file, False),
                                   (gitinfo.show, None), (gitinfo.blob_exists, False)):
                    self.expect(fn, path, absent, text)


def outcome(fn, *args) -> tuple:
    """``("ok", value)`` or ``("err", GateError text)`` of one call: two sides that both raise are compared by text."""
    try:
        return ("ok", fn(*args))
    except GateError as e:
        return ("err", str(e))


def put_many(root: str, ref: str, base: str, entries: list) -> None:
    """Point ``ref`` at one commit on ``base`` holding every ``(name, mode, data)`` of ``entries`` (a throwaway index,
    names passed to ``update-index --cacheinfo`` as they are: no pathspec parsing)."""
    with tempfile.TemporaryDirectory() as td:
        env = {"GIT_INDEX_FILE": os.path.join(td, "index")}
        git(root, "read-tree", base, env=env)
        for i, (name, mode, data) in enumerate(entries):
            blob = os.path.join(td, "blob%d" % i)
            with open(blob, "wb") as fh:
                fh.write(data)
            sha = git(root, "hash-object", "-w", blob, env=env)
            git(root, "update-index", "--add", "--cacheinfo", "%s,%s,%s" % (mode, sha, name), env=env)
        git(root, "update-ref", ref, git(root, "commit-tree", git(root, "write-tree", env=env), "-p", base, "-m", "raw"))


class AliasPaths(GitIsolatedTestCase):
    """R6-1 (F-20261127-e5h5): a ``str`` whose ``os.fsencode`` bytes differ from its UTF-8 reading (a surrogate alias)
    names no entry, even when an entry has those bytes: the entry's decoded name is not ``path``. ``show_file`` gives
    ``None`` and ``is_file`` False (``gitinfo.show`` / ``blob_exists`` at edb6aa7, which compare the decoded name with
    ``path``), for a regular, symlink, tree and gitlink entry, and for an alias in the file name, in a folder component
    or in both. Expected values are written by hand from row R6-1 (the bytes of each alias are written out below); the
    test also asserts ``gitinfo`` (unchanged since edb6aa7, Amendment 1)."""

    # (label, the entry's own path, its kind, the alias path: the same bytes as surrogates)
    CASES = (
        ("regular, alias in the file name", "d/é.md", "regular", "d/\udcc3\udca9.md"),  # e-acute = c3 a9
        ("executable, alias in the file name", "d/ë.md", "executable", "d/\udcc3\udcab.md"),  # c3 ab
        ("symlink, alias in the file name", "d/è.md", "symlink", "d/\udcc3\udca8.md"),  # c3 a8
        ("tree, alias in the entry's own name", "d/ì", "tree", "d/\udcc3\udcac"),  # c3 ac
        ("gitlink, alias in the entry's own name", "d/í", "gitlink", "d/\udcc3\udcad"),  # c3 ad
        ("regular, alias in a folder component", "d/ê/x.md", "regular", "d/\udcc3\udcaa/x.md"),  # c3 aa
        ("regular, aliases in the folder and the file name", "d/ï/ð.md", "regular",
         "d/\udcc3\udcaf/\udcc3\udcb0.md"),  # c3 af, c3 b0
        ("regular, three-byte alias", "d/ࡰ.md", "regular", "d/\udce0\udca1\udcb0.md"),  # U+0870 = e0 a1 b0
        ("regular, alias in the first component only", "ñ/y.md", "regular", "\udcc3\udcb1/y.md"),  # c3 b1
    )

    def setUp(self):
        super().setUp()
        make_repo(self.work)
        for _, path, kind, _ in self.CASES:
            self.put(path, kind)
        self.put("d/a.md", "regular")

    def put(self, path: str, kind: str) -> None:
        mode = {"regular": "100644", "executable": "100755", "symlink": "120000", "tree": "100644",
                "gitlink": "160000"}[kind]
        put_raw(self.work, REF, path + "/inner" if kind == "tree" else path, mode,
                b"keep.md" if kind == "symlink" else b"text of " + path.encode("utf-8") + b"\n")

    def check(self, fn, path: str, want=None, text: str = "") -> None:
        got = outcome(fn, self.work, REF, path)
        self.assertEqual(got, ("err", text) if text else ("ok", want), "%s %s" % (fn.__name__, ascii(path)))

    def test_alias_names_no_entry(self):
        for label, real, kind, alias in self.CASES:
            with self.subTest(label):
                self.assertNotEqual(alias, real)  # guards the fixture: the alias holds the bytes of the real name
                self.assertEqual(os.fsencode(alias), real.encode("utf-8"))
                for fn, absent in ((tipread.show_file, None), (tipread.is_file, False),
                                   (gitinfo.show, None), (gitinfo.blob_exists, False)):
                    self.check(fn, alias, absent)
                if kind in ("regular", "executable"):  # the entry itself is still read, by its own name
                    self.check(tipread.show_file, real, "text of %s\n" % real)
                    self.check(tipread.is_file, real, True)
                else:  # a symlink, tree or gitlink is still refused by its own name
                    for fn in (tipread.show_file, tipread.is_file):
                        self.check(fn, real, text=refusal(REF, real))
        with self.subTest("a path below an aliased tree"):
            for fn, absent in ((tipread.show_file, None), (tipread.is_file, False)):
                self.check(fn, "d/\udcc3\udcac/inner", absent)

    def test_entries_of_an_alias_directory(self):  # sibling member: entries compares no name; main's ls_tree_entries lists it
        want = [("100644", "blob", "d/ê/x.md")]  # git is given the bytes of d/ea-circumflex/: its listing
        for fn in (tipread.entries, gitinfo.ls_tree_entries):
            self.assertEqual(outcome(fn, self.work, REF, "d/\udcc3\udcaa"), ("ok", want), fn.__module__ + fn.__name__)

    def test_round_5_members_keep_their_verdicts(self):  # R5-2 and D1: the path itself holds bytes that are not UTF-8
        put_raw(self.work, REF, "d/b\udcff.md", "100644", b"s\n")
        for path, text in (("d/b\udcff.md", "git ls-tree gave output that is not valid UTF-8"),  # main's refusal
                           ("d/b\ud800.md", "git ls-tree failed: unusable argument"),  # main's refusal
                           ("d/zz\udcfe.md", "")):  # no entry: None / False
            for fn, absent in ((tipread.show_file, None), (tipread.is_file, False),
                               (gitinfo.show, None), (gitinfo.blob_exists, False)):
                with self.subTest(ascii(path), fn=fn.__name__):
                    self.check(fn, path, absent, text)


class MagicNames(GitIsolatedTestCase):
    """R6-2 (F-20261127-fv4m): an entry named with pathspec magic is read literally (``--literal-pathspecs``), by
    ``show_file``, ``is_file`` and ``entries``. Without the flag git parses ``:(top)r.md``, ``:/r.md``... as magic
    (mutant S22): the entry reads as absent, or the listing is another folder's. The plain entries ``r.md`` and
    ``d/other.md`` give a non-literal read something else to find."""

    FORMS = (":(top)", ":(literal)", ":(glob)", ":(icase)", ":(exclude)", ":(attr:x)", ":/", ":!", ":^", ":")

    def setUp(self):
        super().setUp()
        make_repo(self.work)
        # the names: each form + "r.md" (":/" is the folder ":" holding r.md; ":" + "r.md" is git's empty short magic)
        entries = [("r.md", "100644", b"plain\n"), ("d/other.md", "100644", b"other\n")]
        entries += [(form + "r.md", "100644", ("magic " + form + "\n").encode()) for form in self.FORMS]
        entries += [(":/s.md", "120000", b"r.md"), (":(top)t/inner", "100644", b"t\n"),
                    (":/d/a.md", "100644", b"in :/d\n"), (":(top)e/a.md", "100644", b"in :(top)e\n"),
                    (":!f/a.md", "100644", b"in :!f\n"), ("e/other.md", "100644", b"e\n"),
                    ("f/other.md", "100644", b"f\n")]
        put_many(self.work, REF, git(self.work, "rev-parse", REF), entries)

    def test_magic_names_read_literally(self):
        for form in self.FORMS:
            path = form + "r.md"
            for fn, want in ((tipread.show_file, "magic " + form + "\n"), (tipread.is_file, True),
                             (gitinfo.show, "magic " + form + "\n"), (gitinfo.blob_exists, True)):
                with self.subTest(path, fn=fn.__name__):
                    self.assertEqual(outcome(fn, self.work, REF, path), ("ok", want))
        with self.subTest("symlink named :/s.md"):  # the existing refusal of a non-regular entry
            for fn in (tipread.show_file, tipread.is_file):
                self.assertEqual(outcome(fn, self.work, REF, ":/s.md"), ("err", refusal(REF, ":/s.md")))
        with self.subTest("tree named :(top)t"):
            for fn in (tipread.show_file, tipread.is_file):
                self.assertEqual(outcome(fn, self.work, REF, ":(top)t"), ("err", refusal(REF, ":(top)t")))
        with self.subTest("a magic name that is no entry"):  # ":(top)zz.md" read as top-level "zz.md" is no entry either
            self.assertEqual(outcome(tipread.show_file, self.work, REF, ":(top)zz.md"), ("ok", None))
            self.assertEqual(outcome(tipread.is_file, self.work, REF, ":(top)zz.md"), ("ok", False))

    def test_bare_colon_entry(self):  # an entry named exactly ":" (the folder ":" of setUp holds the other names)
        git(self.work, "update-ref", "refs/heads/bare", git(self.work, "rev-parse", REF + "^"))
        put_raw(self.work, "refs/heads/bare", ":", "100644", b"colon\n")
        self.assertEqual(outcome(tipread.show_file, self.work, "refs/heads/bare", ":"), ("ok", "colon\n"))
        self.assertEqual(outcome(tipread.is_file, self.work, "refs/heads/bare", ":"), ("ok", True))
        self.assertEqual(outcome(gitinfo.show, self.work, "refs/heads/bare", ":"), ("ok", "colon\n"))

    def test_entries_of_a_magic_folder(self):
        for directory, want in ((":/d", [("100644", "blob", ":/d/a.md")]),  # the folder ":" holding "d", not top-level "d"
                                (":(top)e", [("100644", "blob", ":(top)e/a.md")]),  # not the top-level "e"
                                (":!f", [("100644", "blob", ":!f/a.md")])):  # not "everything but f"
            with self.subTest(directory):
                self.assertEqual(tipread.entries(self.work, REF, directory), want)


class GeneratedPaths(GitIsolatedTestCase):
    """R6-1 / R6-2 generated-input test (owner answer (a), 2026-11-26). The class: a repo-relative path, as ``show_file``
    and ``is_file`` take it, whose 1-3 segments are built of 1-3 tokens each from: plain ASCII; UTF-8 letters (U+00E9,
    U+00EA, U+0870); lone surrogates whose ``os.fsencode`` bytes are valid UTF-8 (the alias of a letter) and lone
    surrogates whose bytes are not (``\\udcff``, and ``\\ud800``, which git cannot be given); a tab; and, for half of
    the paths, a pathspec-magic prefix of R6-2. Per case a random subset of 1-3 entries (regular, executable, symlink,
    tree, gitlink; names are the bytes of drawn paths, not the unencodable ones) is committed in one commit, then each
    entry's path, its alias forms (every non-ASCII letter, or a random subset, written as its surrogate bytes) and two
    fresh paths are read through ``show_file`` / ``is_file``. The expectation is modelled from the entry bytes alone
    (no tipread code): an exact name gives the text / True (regular) or the refusal (non-regular); an alias or a
    missing name gives None / False; a name whose bytes are not UTF-8 or that git cannot be given give the
    ``gitinfo`` refusal. For every regular, absent and refused-by-gitinfo case ``gitinfo.show`` /
    ``blob_exists`` (unchanged since edb6aa7) are asserted equal, and two sides that raise are compared by text."""

    SEED = 20261128
    CASES = 80
    LETTERS = ("é", "ê", "ࡰ")
    ALIASES = ("\udcc3\udca9", "\udcc3\udcaa", "\udce0\udca1\udcb0")  # the bytes of the three letters, as surrogates
    LONE = ("\udcff", "\ud800")
    MAGIC = (":(top)", ":(literal)", ":(glob)", ":(icase)", ":(exclude)", ":(attr:x)", ":/", ":!", ":^", ":")
    KINDS = ("regular", "executable", "symlink", "tree", "gitlink")
    MODES = {"regular": "100644", "executable": "100755", "symlink": "120000", "tree": "100644", "gitlink": "160000"}

    @classmethod
    def token(cls, rng) -> str:
        pick = rng.randrange(10)
        if pick < 4:
            return rng.choice(("a", "b", "x", "md"))
        if pick < 6:
            return rng.choice(cls.LETTERS)
        if pick < 8:
            return rng.choice(cls.ALIASES)
        return rng.choice(cls.LONE) if pick == 8 else "\t"

    @classmethod
    def draw_path(cls, rng) -> str:
        segs = ["".join(cls.token(rng) for _ in range(1 + rng.randrange(3))) for _ in range(1 + rng.randrange(3))]
        return (rng.choice(cls.MAGIC) if rng.randrange(2) == 0 else "") + "/".join(segs)

    @classmethod
    def alias(cls, path: str, rng, every: bool) -> str:
        """``path`` with each non-ASCII letter (every one, or each with chance 1/2) written as its surrogate bytes."""
        return "".join("".join(chr(0xdc00 + b) for b in c.encode("utf-8"))
                       if c in cls.LETTERS and (every or rng.randrange(2)) else c for c in path)

    @staticmethod
    def clash(a: bytes, b: bytes) -> bool:
        return a == b or a.startswith(b + b"/") or b.startswith(a + b"/")

    def model(self, kinds: dict, texts: dict, path: str) -> tuple:
        """(class, tipread outcome, gitinfo outcome or None for 'not asserted') of ``path`` from the entry bytes alone."""
        try:
            raw = os.fsencode(path)
        except UnicodeEncodeError:
            err = ("err", "git ls-tree failed: unusable argument")
            return "unusable", err, err
        kind = kinds.get(raw)
        if kind is None:
            return "absent", ("ok", None), ("ok", None)
        try:
            raw.decode("utf-8")
        except UnicodeDecodeError:
            err = ("err", "git ls-tree gave output that is not valid UTF-8")
            return "not-utf8", err, err
        if any(0xd800 <= ord(c) <= 0xdfff for c in path):  # an alias: the decoded name is not path
            return "alias-" + ("regular" if kind in ("regular", "executable") else kind), ("ok", None), ("ok", None)
        if kind in ("regular", "executable"):
            return "exact-regular", ("ok", texts[raw]), ("ok", texts[raw])
        return "exact-" + kind, ("err", refusal(self.ref, path)), None  # gitinfo.show gives None for these (not asserted)

    def test_generated_paths(self):
        print("GeneratedPaths seed=%d cases=%d" % (self.SEED, self.CASES), file=sys.stderr)
        rng = random.Random(self.SEED)
        make_repo(self.work)
        base = git(self.work, "rev-parse", REF)
        seen = {}
        for case in range(self.CASES):
            self.ref = "refs/heads/case%d" % case
            kinds, texts, entries, leaves, paths = {}, {}, [], [], []
            for _ in range(1 + rng.randrange(3)):
                path, kind = self.draw_path(rng), rng.choice(self.KINDS)
                try:
                    raw = os.fsencode(path)
                except UnicodeEncodeError:  # git cannot be given this name: it is only ever read, never an entry
                    paths.append(path)
                    continue
                leaf = raw + b"/inner" if kind == "tree" else raw
                if any(self.clash(leaf, other) for other in leaves):
                    paths.append(path)
                    continue
                leaves.append(leaf)
                kinds[raw] = kind
                texts[raw] = "text %d\n" % len(leaves)
                for cut in range(1, len(leaf.split(b"/"))):  # the folders above the entry are trees
                    kinds.setdefault(b"/".join(leaf.split(b"/")[:cut]), "tree")
                entries.append((os.fsdecode(leaf), self.MODES[kind],
                                b"keep.md" if kind == "symlink" else texts[raw].encode()))
                paths += [path, self.alias(path, rng, True), self.alias(path, rng, False)]
            paths += [self.draw_path(rng), self.draw_path(rng)]
            put_many(self.work, self.ref, base, entries)
            for path in dict.fromkeys(paths):
                cls, want, want_git = self.model(kinds, texts, path)
                seen[cls] = seen.get(cls, 0) + 1
                if path.startswith(":") and cls == "exact-regular":
                    seen["magic-regular"] = seen.get("magic-regular", 0) + 1
                if "\t" in path and cls == "exact-regular":
                    seen["tab-regular"] = seen.get("tab-regular", 0) + 1
                with self.subTest(case=case, path=ascii(path)):
                    self.assertEqual(outcome(tipread.show_file, self.work, self.ref, path), want)
                    self.assertEqual(outcome(tipread.is_file, self.work, self.ref, path),
                                     want if want[0] == "err" else ("ok", want[1] is not None))
                    if want_git is not None:  # the edb6aa7 verdicts (gitinfo.py is unchanged since edb6aa7)
                        self.assertEqual(outcome(gitinfo.show, self.work, self.ref, path), want_git)
                        self.assertEqual(outcome(gitinfo.blob_exists, self.work, self.ref, path),
                                         want_git if want_git[0] == "err" else ("ok", want_git[1] is not None))
        print("GeneratedPaths classes %s" % sorted(seen.items()), file=sys.stderr)
        for cls in ("absent", "unusable", "not-utf8", "exact-regular", "exact-symlink", "exact-tree", "exact-gitlink",
                    "alias-regular", "alias-symlink", "alias-tree", "alias-gitlink", "magic-regular", "tab-regular"):
            self.assertGreater(seen.get(cls, 0), 0, "the generator drew no case of class " + cls)


if __name__ == "__main__":
    unittest.main()
