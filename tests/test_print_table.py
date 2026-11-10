"""Tests for the frozen printable table (gates.lib.print_table; plan Task 1d2.1, owner Q-RCp-2 (a)).

Every expected value is written here by hand from Python 3.9.6's ``str.isprintable`` (Unicode 13.0.0), never read
back from the table, and every test runs on both test interpreters (3.9.6 and 3.13). U+0C5D (Unicode 14.0, in the
BMP) and U+1FAE0 (Unicode 15.0) are not printable at 13.0.0 and printable on 3.13, so each site test below fails on
3.13 when its call site still uses the interpreter's own ``str.isprintable``.
"""
import ast
import glob
import hashlib
import importlib
import os
import pathlib
import unicodedata
import unittest

from gates.lib import config, decisions, result, schema, yamlsub
from gates.lib.result import GateError

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
N, W = "ౝ", "\U0001FAE0"  # Unicode 14.0 (BMP) and 15.0: non-printable at 13.0
# SHA-256 of the 0..0x10FFFF verdict string ('1' printable, '0' not, one ASCII character per code point), measured
# with /usr/bin/python3 3.9.6's own chr(cp).isprintable(), independently of print_table; 143680 printable.
VERDICT_SHA256 = "d4dc5dafc72dc62e179bef4905c604b9e8628af022fd813538a9dc0b9a1c9c76"
PRINTABLE_COUNT = 143680

CASES = {"a": True, " ": True, "~": True, "": True, "\x00": False, "\x1f": False, "\x7f": False, "\x85": False,
         "\xa0": False, "\U0001FAD6": True, W: False, N: False, "\U0001F6DD": False, "\udc80": False,
         "": False, "\U0002FFFE": False, "\U0010FFFF": False}


def pt():
    """The module under test, imported per test so that every other test here runs while it is missing."""
    return importlib.import_module("gates.lib.print_table")


class CodePointTests(unittest.TestCase):
    def test_cases(self):  # CP1-CP10, A1, A2
        for s, want in CASES.items():
            with self.subTest(repr(s)):
                self.assertIs(pt().is_printable(s), want)

    def test_mixed(self):  # A3
        for s, want in (("ab", True), ("a\x00b", False), ("a" + W, False), ("\U0001FAD6a", True)):
            with self.subTest(repr(s)):
                self.assertIs(pt().is_printable(s), want)

    def test_str_subclass(self):  # A4: the characters decide, never the subclass's own methods
        class Liar(str):
            def isprintable(self):
                return not str.isprintable(self)

            def __iter__(self):
                return iter("a")

            def __getitem__(self, i):
                return "a"

            def __len__(self):
                return 1

        self.assertIs(pt().is_printable(Liar("a\x00")), False)
        self.assertIs(pt().is_printable(Liar("a" + N)), False)
        self.assertIs(pt().is_printable(Liar("ab")), True)
        self.assertIs(pt().is_printable(Liar("")), True)

    def test_non_str_refused(self):  # A5; the type is read with type(), never __class__
        class Fake:
            __class__ = str

        for v in (b"a", bytearray(b"a"), None, 1, ["a"], Fake()):
            with self.subTest(repr(v)), self.assertRaises(TypeError) as cm:
                pt().is_printable(v)
            self.assertEqual(str(cm.exception), "is_printable() argument must be str, not %s" % type(v).__name__)

    def test_every_code_point(self):  # CP11, K2
        is_printable = pt().is_printable
        verdict = "".join("1" if is_printable(chr(cp)) else "0" for cp in range(0x110000))
        self.assertEqual(verdict.count("1"), PRINTABLE_COUNT)
        self.assertEqual(hashlib.sha256(verdict.encode("ascii")).hexdigest(), VERDICT_SHA256)
        if unicodedata.unidata_version == "13.0.0":  # the generating database: also compare directly
            bad = [hex(cp) for cp in range(0x110000) if is_printable(chr(cp)) is not chr(cp).isprintable()]
            self.assertEqual(bad, [])


class TableTests(unittest.TestCase):
    def test_table_shape(self):  # T1, T2: sorted, disjoint, merged, int pairs inside 0..0x10FFFF
        p = pt().PRINTABLE
        self.assertIs(type(p), tuple)
        self.assertTrue(all(type(x) is tuple and len(x) == 2 and type(x[0]) is int and type(x[1]) is int for x in p))
        self.assertTrue(all(0 <= a <= b <= 0x10FFFF for a, b in p))
        self.assertTrue(all(p[i][1] + 1 < p[i + 1][0] for i in range(len(p) - 1)))
        self.assertEqual(sum(b - a + 1 for a, b in p), PRINTABLE_COUNT)

    def test_generated_file_header(self):  # the header names the generating interpreter and database
        data = pathlib.Path(pt().__file__).read_bytes()
        text = data.decode("ascii")
        self.assertTrue(text.startswith("# GENERATED FILE. DO NOT EDIT BY HAND.\n"))
        for word in ("/usr/bin/python3", "Python 3.9.6", "unicodedata.unidata_version 13.0.0"):
            self.assertIn(word, text)

    def test_skeleton_no_exception_group(self):  # K3
        text = pathlib.Path(pt().__file__).read_text(encoding="ascii")
        tree = ast.parse(text)
        imports = [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
        imports += [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
        self.assertEqual(imports, ["bisect"])
        self.assertNotIn("ExceptionGroup", text)
        raised = [n.exc.func.id for n in ast.walk(tree) if isinstance(n, ast.Raise)]
        self.assertEqual(raised, ["TypeError"])
        self.assertEqual([n for n in ast.walk(tree) if isinstance(n, (ast.Try, ast.ExceptHandler))], [])

    def test_skeleton_digit_runs(self):  # K1: numeric text at and past the int() digit limit
        for n in (4300, 4301):
            d = "1" * n
            with self.subTest(n=n):
                self.assertIs(pt().is_printable(d), True)
                self.assertEqual(result.safe_text(d), d)
                self.assertIs(schema._path_ok(d), True)
                text = yamlsub.emit({"k": d})
                self.assertEqual(text, 'k: "%s"\n' % d)
                self.assertEqual(yamlsub.parse(text), {"k": d})


class SiteTests(unittest.TestCase):
    """One test per call site; the output is 3.9.6's on both interpreters (K2)."""

    def test_site_result_safe_text(self):  # result.py:39 (safe_text); the golden output of spec 14
        self.assertEqual(result.safe_text("id" + W), "id\\U0001fae0")
        self.assertEqual(result.safe_text("id" + N), "id\\u0c5d")

    def test_site_config_check_path(self):  # config.py:87 (_check_path)
        for v in ("a" + N, "a" + W):
            with self.subTest(repr(v)), self.assertRaises(GateError):
                config._check_path("paths.x", v)

    def test_site_schema_path_ok(self):  # schema.py:246 (_path_ok)
        self.assertIs(schema._path_ok("a" + N), False)
        self.assertIs(schema._path_ok("a" + W), False)

    def test_site_decisions_cite_anchor(self):  # decisions.py:157 (_cite_problem) (the path part passes, so only the anchor decides)
        for c in (N, W):
            with self.subTest(repr(c)):
                self.assertEqual(decisions._cite_problem("docs/a.md#x" + c),
                                 "is not a normalised repo-relative path with an optional non-empty #anchor")

    def test_site_yamlsub_dq(self):  # yamlsub.py:573 (_dq) (a leading space forces the double-quoted form)
        self.assertEqual(yamlsub.emit({"k": " a" + N}), 'k: " a\\u0c5d"\n')

    def test_site_yamlsub_block_form(self):  # yamlsub.py:587 (_block_form) (W is above U+FFFF, so _dq at :573 leaves it raw)
        self.assertEqual(yamlsub.emit({"k": "a\nb" + W + "\n"}), 'k: "a\\nb\U0001fae0\\n"\n')

    def test_no_isprintable_call_left(self):  # S8: attribute uses only; print_table's header may name the method
        hits = []
        for f in sorted(glob.glob(os.path.join(REPO, "gates", "**", "*.py"), recursive=True)):
            with open(f, encoding="utf-8") as fh:
                tree = ast.parse(fh.read(), f)
            hits += ["%s:%d" % (os.path.relpath(f, REPO), n.lineno) for n in ast.walk(tree)
                     if isinstance(n, ast.Attribute) and n.attr == "isprintable"]
        self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main()
