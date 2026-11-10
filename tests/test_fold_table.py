"""Tests for the frozen case-fold and normalization data (gates.lib.fold_table; owner decision U1 (a) of 2026-11-10,
plan Task P2.1, Task U1 input-domain table rows F1-F11 and W1).

Every expected value is written here by hand, or measured from the interpreter's own ``str.casefold`` and
``unicodedata`` (never read back from the file under test), and every test runs on both test interpreters (3.9.6,
Unicode 13.0.0, the generating database, and 3.13, Unicode 15.1.0). The 40 code points below are the ones whose
``str.casefold`` differs between the two: each is unassigned at 13.0.0, so the table (13.0.0) folds it to itself.
"""
import ast
import contextlib
import hashlib
import importlib
import io
import pathlib
import unicodedata
import unittest

UNIDATA = unicodedata.unidata_version
# SHA-256 of the bytes of gates/lib/fold_table.py, as generated once by /usr/bin/python3 (3.9.6).
FILE_SHA256 = "f324ca5445c58bc26ca1a980449ab5d7a3329be1a2383ec0e56f903b7e55ccf4"

# The 40 code points whose str.casefold differs between Python 3.9.6 (Unicode 13.0.0) and Python 3.13 (15.1.0),
# written out by hand: U+2C2F, U+A7C0, U+A7D0, U+A7D6, U+A7D8, U+10570..U+1057A, U+1057C..U+1058A, U+1058C..U+10592,
# U+10594 and U+10595.
FORTY = ([0x2C2F, 0xA7C0, 0xA7D0, 0xA7D6, 0xA7D8]
         + list(range(0x10570, 0x1057B)) + list(range(0x1057C, 0x1058B)) + list(range(0x1058C, 0x10593))
         + [0x10594, 0x10595])
# What Python 3.13 folds each of the 40 to: the Vithkuqi capitals fold 0x27 up, the others to the small letter.
FORTY_TARGET_313 = {0x2C2F: 0x2C5F, 0xA7C0: 0xA7C1, 0xA7D0: 0xA7D1, 0xA7D6: 0xA7D7, 0xA7D8: 0xA7D9}
FORTY_TARGET_313.update({cp: cp + 0x27 for cp in FORTY if cp >= 0x10570})

# str.isspace at Unicode 13.0.0, which is also what 3.13 answers: U+0009-U+000D, U+001C-U+001F, U+0020, U+0085,
# U+00A0, U+1680, U+2000-U+200A, U+2028, U+2029, U+202F, U+205F, U+3000.
ISSPACE = (list(range(0x09, 0x0E)) + list(range(0x1C, 0x21)) + [0x85, 0xA0, 0x1680] + list(range(0x2000, 0x200B))
           + [0x2028, 0x2029, 0x202F, 0x205F, 0x3000])

CASE_METHODS = ("lower", "casefold", "upper", "swapcase", "title", "capitalize")


def ft():
    """The module under test, imported per test so that every other test here runs while it is missing."""
    return importlib.import_module("gates.lib.fold_table")


def source():
    return pathlib.Path(ft().__file__).read_bytes()


def needs_13(test):
    return unittest.skipUnless(UNIDATA == "13.0.0", "needs the generating database, Unicode 13.0.0")(test)


class ListTests(unittest.TestCase):
    def test_the_forty_list(self):
        self.assertEqual(len(FORTY), 40)
        self.assertEqual(len(set(FORTY)), 40)
        self.assertEqual(sorted(FORTY), FORTY)
        self.assertEqual(sorted(FORTY_TARGET_313), FORTY)


class ShapeTests(unittest.TestCase):
    def test_fold_table_shape(self):  # F1, F2
        m = ft()
        self.assertEqual(sorted(n for n in vars(m) if not n.startswith("__")), ["CCC", "COMPOSE", "DECOMP", "FOLD"])

        def ok(cp):
            return type(cp) is int and 0 <= cp <= 0x10FFFF and not 0xD800 <= cp <= 0xDFFF

        self.assertIs(type(m.FOLD), dict)
        for k, v in m.FOLD.items():
            self.assertTrue(ok(k) and type(v) is str and 1 <= len(v) <= 3 and v != chr(k), k)
            self.assertTrue(all(ok(ord(c)) for c in v), k)
        self.assertIs(type(m.DECOMP), dict)
        for k, v in m.DECOMP.items():
            self.assertTrue(ok(k) and type(v) is tuple and len(v) in (1, 2) and all(ok(x) for x in v), k)
        self.assertIs(type(m.CCC), dict)
        for k, v in m.CCC.items():
            self.assertTrue(ok(k) and type(v) is int and 1 <= v <= 254, k)
        self.assertIs(type(m.COMPOSE), dict)
        for k, v in m.COMPOSE.items():
            self.assertTrue(type(k) is tuple and len(k) == 2 and ok(k[0]) and ok(k[1]) and ok(v), k)

    def test_fold_table_spot_rows(self):  # F2: hand-written entries
        m = ft()
        self.assertEqual(m.FOLD[0x41], "a")
        self.assertEqual(m.FOLD[0xDF], "ss")
        self.assertEqual(m.FOLD[0x130], "i\u0307")
        self.assertEqual(m.FOLD[0x3C2], "\u03c3")
        self.assertEqual(m.FOLD[0x212A], "k")
        self.assertEqual(m.FOLD[0x1E9E], "ss")
        self.assertEqual(m.FOLD[0xFB03], "ffi")
        self.assertNotIn(0x61, m.FOLD)
        self.assertNotIn(0x2C2F, m.FOLD)  # unassigned at 13.0.0
        self.assertEqual(m.DECOMP[0xC0], (0x41, 0x300))
        self.assertEqual(m.DECOMP[0x2126], (0x3A9,))
        self.assertEqual(m.CCC[0x301], 230)
        self.assertEqual(m.CCC[0x316], 220)
        self.assertEqual(m.COMPOSE[(0x41, 0x301)], 0xC1)

    def test_fold_table_sorted(self):  # F3
        tree = ast.parse(source().decode("ascii"))
        assigns = [n for n in tree.body if isinstance(n, ast.Assign)]
        self.assertEqual([a.targets[0].id for a in assigns], ["FOLD", "DECOMP", "CCC", "COMPOSE"])
        self.assertEqual(len(tree.body), 5)  # the docstring and the four assignments
        for a in assigns:
            keys = [ast.literal_eval(k) for k in a.value.keys]
            self.assertEqual(keys, sorted(keys), a.targets[0].id)
            self.assertEqual(len(keys), len(set(keys)), a.targets[0].id)

    def test_fold_table_pinned(self):  # F4
        self.assertEqual(hashlib.sha256(source()).hexdigest(), FILE_SHA256)

    def test_fold_table_header(self):  # F5: the first comment block only
        text = source().decode("ascii")
        header = []
        for line in text.split("\n"):
            if not line.startswith("#"):
                break
            header.append(line)
        block = "\n".join(header)
        for word in ("GENERATED", "DO NOT EDIT BY HAND", "Unicode 13.0.0", "3.9.6", "/usr/bin/python3"):
            self.assertIn(word, block)
        self.assertTrue(text.startswith("# GENERATED FILE. DO NOT EDIT BY HAND.\n"))

    def test_fold_table_header_generator_reproduces_the_file(self):  # F5: the verbatim generator, run, is the body
        text = source().decode("ascii")
        lines = [l for l in text.split("\n") if l.startswith("#     ") or l == "#"]
        gen = "\n".join(l[6:] for l in lines if l.startswith("#     ")) + "\n"
        self.assertIn("import unicodedata", gen)
        self.assertIn("emit(\"COMPOSE\"", gen)
        if UNIDATA != "13.0.0":
            self.skipTest("the generator asserts Unicode 13.0.0; it runs on the generating interpreter")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            exec(compile(gen, "<generator>", "exec"), {"__name__": "gen"})
        self.assertTrue(text.endswith(out.getvalue()))
        self.assertTrue(out.getvalue().startswith("FOLD = {\n"))

    def test_fold_table_pure(self):  # F6, G4
        data = source()
        data.decode("ascii")
        tree = ast.parse(data.decode("ascii"))
        self.assertEqual([n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))], [])
        self.assertEqual([n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.Call, ast.Lambda))], [])
        self.assertEqual([n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)], [])
        self.assertNotIn("unicodedata", "\n".join(l for l in data.decode("ascii").split("\n")
                                                   if not l.startswith("#")))


class MeasuredTests(unittest.TestCase):
    """The table against the interpreter's own data, over every code point."""

    def test_fold_matches_casefold(self):  # F7 (3.9.6), F8 (3.13)
        fold = ft().FOLD
        differ = [cp for cp in range(0x110000) if fold.get(cp, chr(cp)) != chr(cp).casefold()]
        if UNIDATA == "13.0.0":
            self.assertEqual(differ, [])
        elif UNIDATA == "15.1.0":
            self.assertEqual(differ, FORTY)
            for cp in FORTY:
                with self.subTest(hex(cp)):
                    self.assertNotIn(cp, fold)
                    self.assertEqual(chr(cp).casefold(), chr(FORTY_TARGET_313[cp]))
        else:
            self.skipTest("measured on Unicode 13.0.0 and 15.1.0 only, not %s" % UNIDATA)

    @needs_13
    def test_decomp_matches_unicodedata_13(self):  # F9
        decomp = ft().DECOMP
        want = {}
        for cp in range(0x110000):
            d = unicodedata.decomposition(chr(cp))
            if d and not d.startswith("<"):
                want[cp] = tuple(int(x, 16) for x in d.split())
        self.assertEqual(decomp, want)
        self.assertEqual([cp for cp in decomp if 0xAC00 <= cp <= 0xD7A3], [])
        self.assertEqual(len(decomp), 2061)

    @needs_13
    def test_ccc_matches_unicodedata_13(self):  # F10
        ccc = ft().CCC
        for cp in range(0x110000):
            if ccc.get(cp, 0) != unicodedata.combining(chr(cp)):
                self.fail(hex(cp))
        self.assertEqual([cp for cp in ccc if ccc[cp] == 0], [])

    @needs_13
    def test_compose_matches_unicodedata_13(self):  # F11
        m = ft()
        for (a, b), c in m.COMPOSE.items():
            if unicodedata.normalize("NFC", chr(a) + chr(b)) != chr(c):
                self.fail((hex(a), hex(b)))
        composed = set(m.COMPOSE.values())
        for cp, d in m.DECOMP.items():
            if len(d) == 2 and cp not in composed:
                if unicodedata.normalize("NFC", chr(cp)) == chr(cp):
                    self.fail(hex(cp))
        for cp, d in m.DECOMP.items():
            if len(d) == 2 and cp in composed:
                self.assertEqual(m.COMPOSE[d], cp)
        self.assertEqual(m.COMPOSE[(0x41, 0x301)], 0xC1)
        self.assertNotIn((0x308, 0x301), m.COMPOSE)  # U+0344: a non-starter decomposition
        self.assertIn(0x344, m.DECOMP)
        self.assertNotIn(0x958, composed)  # composition exclusion
        self.assertIn(0x958, m.DECOMP)
        self.assertIn(0x2126, m.DECOMP)  # singleton
        self.assertNotIn(0x2126, composed)
        self.assertEqual(len(m.COMPOSE), 941)


class IsspaceTests(unittest.TestCase):
    def test_isspace_same_on_both(self):  # W1
        got = [cp for cp in range(0x110000) if chr(cp).isspace()]
        self.assertEqual(got, ISSPACE)
        self.assertEqual(len(ISSPACE), 29)


if __name__ == "__main__":
    unittest.main()
