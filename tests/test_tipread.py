"""Tests for gates.lib.tipread.show_file (Task 5b.3, table task-5b.3-domain.md rows F26, F27, FH4, FH6, FH7, FK1-FK3)."""
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

    def test_show_contract_unchanged(self):  # F27: gitinfo.show keeps returning None for a non-regular entry
        for kind, _ in BAD_KINDS:
            with self.subTest(kind):
                set_entry(self.work, REF, "p.md", kind)
                self.assertIsNone(gitinfo.show(self.work, REF, "p.md"))
                self.assertEqual(gitinfo.ls_tree(self.work, REF, ""), [])  # ls_tree hides the non-regular entry
        set_entry(self.work, REF, "p.md", "regular", "q\n")
        self.assertEqual(gitinfo.show(self.work, REF, "p.md"), "q\n")


if __name__ == "__main__":
    unittest.main()
