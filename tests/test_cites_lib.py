"""Tests for the cite library (gates.lib.cites): extraction, lowercase, slugify, anchors, resolution, and the two frozen
tables. Expected values are written here (github-slugger 2.0.0 fixtures, the frozen Unicode 13.0.0 case table), not
derived from the code under test."""
import ast
import dataclasses
import hashlib
import pathlib
import sys
import unicodedata
import unittest

from gates.lib import case_table, cites, slug_table
from gates.lib.cites import Cite, anchors, extract, lowercase, number_repeats, problem, slugify

TABLE_SHA256 = "1af71c6876ad0341fc2550fb347218e790e26b6e05022c29818bd530e975e0ad"
VERDICT_SHA256 = "1e74d3aead4367260822a28fefe88aae7e8d1f8f08ac4cb68cdb852995200bfd"
CASE_TABLE_SHA256 = "ed4381372f893a5f8ae953f095f52bbe8f11f76d5e9346bd1cec11bec09a15ff"
LOWER_SHA256 = "f364d1ca036a14eafd06621641360296cb23686fdac2d27d811a2c71518b7a13"

# github-slugger 2.0.0, test/fixtures.json: cases 0-42, 45, 55 and 68, in file order, through one slugger.
SLUGGER_FIXTURES = [('alpha', 'alpha'), ('alpha', 'alpha-1'), ('bravoCharlieDelta', 'bravocharliedelta'), ('__proto__', '__proto__'),
    ('__proto__', '__proto__-1'), ('hasOwnProperty', 'hasownproperty'), ('echo', 'echo'), ('echo', 'echo-1'), ('echo 1', 'echo-1-1'),
    ('echo-1', 'echo-1-2'), ('echo', 'echo-2'), ('foxtrot-1', 'foxtrot-1'), ('foxtrot', 'foxtrot'), ('foxtrot', 'foxtrot-2'),
    ('heading with a - dash', 'heading-with-a---dash'), ('heading with an _ underscore', 'heading-with-an-_-underscore'),
    ('heading with a period.txt', 'heading-with-a-periodtxt'),
    ('exchange.bind_headers(exchange, routing [, bindCallback])', 'exchangebind_headersexchange-routing--bindcallback'), (' ', '-'), (' a', '-a'),
    ('a ', 'a-'), (' a ', '-a-'), ('-a-', '-a--1'), ('apostrophe\u2019s should be trimmed', 'apostrophes-should-be-trimmed'), ('golf', 'golf'),
    ('golf', 'golf-1'), ('golf', 'golf-2'), ('I \u2665 unicode', 'i--unicode'), ('dash-dash', 'dash-dash'), ('en\u2013dash', 'endash'),
    ('em\u2013dash', 'emdash'), ('\U0001f604 unicode emoji', '-unicode-emoji'), ('\U0001f604-\U0001f604 unicode emoji', '--unicode-emoji'),
    ('\U0001f604_\U0001f604 unicode emoji', '_-unicode-emoji'), ('\U0001f604 - an emoji', '---an-emoji'),
    (':smile: - a gemoji', 'smile---a-gemoji'), ('\u041f\u0440\u0438\u0432\u0435\u0442', '\u043f\u0440\u0438\u0432\u0435\u0442'),
    ('\u041f\u0440\u043e\u0444\u0438\u043b\u0438 \u043f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u0442\u0435\u043b\u0435\u0439', '\u043f\u0440\u043e\u0444\u0438\u043b\u0438-\u043f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u0442\u0435\u043b\u0435\u0439'),
    ('\u041f\u0440\u0438\u0432\u0435\u0442 non-latin \u4f60\u597d', '\u043f\u0440\u0438\u0432\u0435\u0442-non-latin-\u4f60\u597d'),
    (':ok: No underscore', 'ok-no-underscore'), (':ok_hand: Single', 'ok_hand-single'),
    (':ok_hand::hatched_chick: Two in a row with no spaces', 'ok_handhatched_chick-two-in-a-row-with-no-spaces'),
    (':ok_hand: :hatched_chick: Two in a row', 'ok_hand-hatched_chick-two-in-a-row'),
    ('a_ \u203f \u2040 \u2054 \ufe33 \ufe34 \ufe4d \ufe4e \ufe4f \uff3fb', 'a_-\u203f-\u2040-\u2054-\ufe33-\ufe34-\ufe4d-\ufe4e-\ufe4f-\uff3fb'),
    ('a\u2028b', 'ab'), ('a\u2029b', 'ab-1')]


def shape(cs):
    """(path, start, end, anchor) of each cite."""
    return [(c.path, c.start, c.end, c.anchor) for c in cs]


def files_reader(files):
    return lambda p: files.get(p)


FILES = {
    "a/b.py": "1\n2\n3",
    "a/nl.py": "1\n2\n3\n",
    "a/empty.py": "",
    "a/blank.py": "\n",
    "a/crlf.py": "a\r\nb\r\n",
    "a/c.md": "# Intro\n## Intro\n```\n# hidden\n```\nTitle\n=====\n# `Code` and, Punct!\n# Ünï\n",
    "a/B.MD": "# x\n",
    "a/bad.py": "ok \udcff\n",
    "a/bad.md": "# x \udc80\n",
    "a/deleted.py": None,
    "a(b).md": "# p\n",
    "d/x y.md": "# z\n",
    "README": "x\n",
}
TRACKED = frozenset(FILES)
READ = files_reader(FILES)


def one(token_text, doc="d/a.md"):
    cs = extract(doc, token_text)
    assert len(cs) == 1, cs
    return cs[0]


def prob(token_text, tracked=TRACKED, read=READ, doc="d/a.md"):
    return problem(one(token_text, doc), tracked, read)


class ExtractFencesTest(unittest.TestCase):
    def test_fenced_lines_skipped(self):
        self.assertEqual(extract("a.md", "```\n`x/y.py:1`\n```\n~~~~\n`x/y.py:2`\n~~~~\n"), [])

    def test_fence_closers(self):
        cite = "`x/y.py:1`\n"
        for text in ("```\n" + cite + "~~~\n" + cite,          # tildes do not close backticks
                     "```\n" + cite + "``\n" + cite,           # a shorter run does not close
                     "~~~~\n" + cite + "~~~\n" + cite,
                     "```\n" + cite):                          # unclosed: runs to the end
            self.assertEqual(extract("a.md", text), [], repr(text))
        self.assertEqual([c.line for c in extract("a.md", "   ```\n" + cite + "   ```\n" + cite + "```\n" + cite)], [4])
        self.assertEqual(len(extract("a.md", "```\n" + cite + "`````\n" + cite)), 1)     # a longer run closes
        self.assertEqual(len(extract("a.md", "~~~\n" + cite + "~~~~~\n" + cite)), 1)
        self.assertEqual(len(extract("a.md", "``\n" + cite)), 1)                         # two backticks are not a fence

    def test_fence_indentation(self):
        cite = "`x/y.py:1`\n"
        self.assertEqual(extract("a.md", "   ```\n" + cite + "```\n"), [])               # three spaces: a fence
        for opener in ("    ```", "\t```", "> ```", "- ```"):
            self.assertEqual(len(extract("a.md", opener + "\n" + cite)), 1, opener)

    def test_fence_info_string_and_closer_text(self):
        cite = "`x/y.py:1`\n"
        # Q-C21-3 (a): a backtick opener whose info string holds a backtick is not a fence, so the next line is scanned
        self.assertEqual(len(extract("a.md", "```x`y` \n" + cite)), 1)
        self.assertEqual(extract("a.md", "~~~x`y\n" + cite + "~~~\n"), [])                 # tilde info strings may hold backticks
        self.assertEqual(extract("a.md", "```\n" + cite + "``` x\n" + cite)[0].line, 4)    # a closer may carry text
        self.assertEqual(len(extract("a.md", "```\n" + cite + "``` x\n" + cite)), 1)

    def test_scanned_as_prose(self):
        for text in ("    `x/y.py:1`\n", "<!-- `x/y.py:1` -->\n", "<pre>\n`x/y.py:1`\n</pre>\n"):
            self.assertEqual(len(extract("a.md", text)), 1, text)

    def test_empty_text(self):
        self.assertEqual(extract("a.md", ""), [])
        self.assertEqual(extract("a.md", "\n"), [])

    def test_line_numbers_and_split_on_lf_only(self):
        cs = extract("a.md", "x\n\n`x/y.py:1`\n`x/y.py:2`")
        self.assertEqual([c.line for c in cs], [3, 4])
        for sep in ("\x0b", "\x0c", "\x1c", "\x85", "\u2028", "\r"):
            cs = extract("a.md", "a" + sep + "b\n`x/y.py:1`\n")
            self.assertEqual([c.line for c in cs], [2], repr(sep))

    def test_crlf_equals_lf(self):
        lf = "# A #\n```\n`x/y.py:1`\n```\n`x/y.py:2` [t](b.md#c \"T\")\n"
        crlf = lf.replace("\n", "\r\n")
        self.assertEqual(extract("d/a.md", crlf), extract("d/a.md", lf))
        self.assertEqual(len(extract("d/a.md", lf)), 2)
        self.assertEqual(anchors(crlf), anchors(lf))
        self.assertEqual(anchors("# A #\r\n"), frozenset({"a"}))
        self.assertEqual(extract("a.md", "x\r\n`x/y.py:1`\r\n")[0].token, "`x/y.py:1`")


class ExtractSpansTest(unittest.TestCase):
    def test_link_inside_code_span_not_a_cite(self):
        for text in ('`[t](b.md#c "T")`\n', '``[t](b.md#c)``\n', '``[t](b.md#c "T")``\n', 'x ```[t](b.md#c)```\n'):
            self.assertEqual(extract("d/a.md", text), [], text)
        self.assertEqual([(c.path, c.anchor) for c in extract("d/a.md", "`x [t](b.md#c)\n")], [("d/b.md", "c")])

    def test_span_pairing(self):
        self.assertEqual(shape(extract("a.md", "`a/b.py:1`\n")), [("a/b.py", 1, None, None)])
        self.assertEqual(extract("a.md", "``a/b.py:1``\n"), [])
        self.assertEqual(extract("a.md", "`` `a/b.py:1` ``\n"), [])               # a double span holding backticks
        self.assertEqual(extract("a.md", "` `` a/b.py:1 `a/b.py:2`\n"), [])           # the first ` pairs with the third run
        self.assertEqual(shape(extract("a.md", "``a `b/c.py:3`\n")), [("b/c.py", 3, None, None)])   # unmatched run is literal
        self.assertEqual(extract("a.md", "```a/b.py:1``\n"), [])

    def test_span_across_lines_is_literal(self):
        self.assertEqual(extract("a.md", "`a/b.py:1\n`\n"), [])
        self.assertEqual(len(extract("a.md", "`\n`a/b.py:1`\n")), 1)
        self.assertEqual([c.path for c in extract("d/a.md", "x ` [t](b.md#c)\ny ` z\n")], ["d/b.md"])

    def test_backslash_before_backtick_has_no_effect(self):
        self.assertEqual(shape(extract("a.md", "\\`a/b.py:1`\n")), [("a/b.py", 1, None, None)])

    def test_link_around_span(self):
        cs = extract("d/a.md", "[`a/b.py:3`](x.md#y)\n")
        self.assertEqual([(c.token, c.path) for c in cs], [("`a/b.py:3`", "a/b.py"), ("x.md#y", "d/x.md")])

    def test_order_by_line_then_column(self):
        cs = extract("d/a.md", "[t](x.md#y) `a/b.py:1`\n`a/b.py:2` [t](z.md#w)\n")
        self.assertEqual([c.token for c in cs], ["x.md#y", "`a/b.py:1`", "`a/b.py:2`", "z.md#w"])
        self.assertEqual([c.line for c in cs], [1, 1, 2, 2])


class ExtractBacktickTest(unittest.TestCase):
    def test_backtick_line_and_anchor_forms(self):
        cs = extract("docs/a.md", "see `gates/x.py:3` and `docs/b.md#intro` and `path#anchor` and `abc1234:docs/b.md`\n")
        self.assertEqual([(c.path, c.start, c.anchor) for c in cs], [("gates/x.py", 3, None), ("docs/b.md", None, "intro")])
        self.assertEqual(shape(extract("a.md", "`gates/x.py:3-5`\n")), [("gates/x.py", 3, 5, None)])

    def test_placeholders_and_non_paths(self):
        for tok in ("path#anchor", "path:3", "<path>:<line>", "abc1234:docs/b.md", "Makefile:3", "LICENSE#x", "https://x/y#z",
                    "abc1234:12"):
            self.assertEqual(extract("a.md", "`%s`\n" % tok), [], tok)

    def test_whitespace(self):
        for tok in (" a/b.py:1 ", "a b.md:1", "a/b.py:1\xa0", "a/b\u3000.py:1", "a/b.py :1", "a/b.py:1 x"):
            self.assertEqual(extract("a.md", "`%s`\n" % tok), [], repr(tok))

    def test_partial_matches(self):
        for tok in ("a/b.py:", "a/b.py:1-", "a/b.md#x#y", "a/b.py:\u0663", "a/b.py:1-2-3", "a/b.py:-1", "a/b.py"):
            self.assertEqual(extract("a.md", "`%s`\n" % tok), [], repr(tok))

    def test_zero_and_leading_zero_are_cites(self):
        self.assertEqual(shape(extract("a.md", "`a/b.py:01` `a/b.py:0` `a/b.py:1-01`\n")),
                         [("a/b.py", 1, None, None), ("a/b.py", 0, None, None), ("a/b.py", 1, 1, None)])

    def test_empty_anchor(self):
        self.assertEqual(shape(extract("a.md", "`a/c.md#`\n")), [("a/c.md", None, None, "")])

    def test_path_taken_as_written(self):
        for p in ("./a.md", "a//b.md", "a/", "../x.py", "/abs.md", "a/../b.py"):
            self.assertEqual(one("`%s:1`\n" % p).path, p)

    def test_nfc_cite_against_nfd_tracked_file(self):       # row B10: exact string compare, no normalisation
        nfc, nfd = "docs/café.md", "docs/café.md"
        self.assertEqual(prob("`%s:1`\n" % nfc, tracked=frozenset({nfd}), read=lambda p: "x\n"), "%s: not a tracked file" % nfc)
        self.assertEqual(prob("`%s:1`\n" % nfc, tracked=frozenset({nfc}), read=lambda p: "x\n"), "")

    def test_unicode_path(self):
        self.assertEqual(one("`docs/caf\u00e9.md:1`\n").path, "docs/caf\u00e9.md")

    def test_token_and_fields(self):
        c = one('`gates/x.py:9`')
        self.assertEqual((c.doc, c.line, c.token, c.path, c.start, c.end, c.anchor), ("d/a.md", 1, "`gates/x.py:9`", "gates/x.py", 9, None, None))
        c = one("`a/b.md#x`")
        self.assertEqual((c.start, c.end, c.anchor), (None, None, "x"))

    def test_cite_is_frozen(self):
        with self.assertRaises(dataclasses.FrozenInstanceError):
            one("`a/b.py:1`").line = 5


class ExtractLinkTest(unittest.TestCase):
    def test_link_relative_to_doc(self):
        cs = extract("docs/specs/a.md", "[x](../plans/p.md#task-1) [y](#local) [z](https://h/p#q) ![i](img.png#a)\n")
        self.assertEqual([(c.path, c.anchor) for c in cs], [("docs/plans/p.md", "task-1"), ("docs/specs/a.md", "local")])
        self.assertEqual([(c.path, c.anchor) for c in extract("a.md", "[x](b.md#c) [y](./d/../e.md#f) [z](g/#h)\n")],
                         [("b.md", "c"), ("e.md", "f"), ("g", "h")])

    def test_link_title_and_angle_destination(self):
        cs = extract("d/a.md", '[t](b.md#c "T") [t](b.md#c \'T\') [t](b.md#c (T)) [t](<x y.md#z>) [t](p(1).md#q)\n')
        self.assertEqual([(c.path, c.anchor) for c in cs], [("d/b.md", "c")] * 3 + [("d/x y.md", "z"), ("d/p(1).md", "q")])
        cs = extract("d/a.md", '[t](  b.md#c\t"T"  ) [t](<a b.md#c> "T") [t](<#a>)\n')
        self.assertEqual([(c.path, c.anchor) for c in cs], [("d/b.md", "c"), ("d/a b.md", "c"), ("d/a.md", "a")])

    def test_link_forms_that_are_not_cites(self):
        for text in ('[t](b.md#c "T)\n', '[t](b.md#c x)\n', '[t](<b<.md#c>)\n', '[t](b.md#c\n"T")\n', '[t](<b.md#c\n>)\n',
                     '[t]\n(b.md#c)\n', '[t] (b.md#c)\n', '[t](<a.md#c>x)\n', '[t](a(b.md#c)\n',
                     '[t](b.md)\n', '[t]()\n', '[t](<>)\n', '[t](b.md#c \'T)\n', '[t](b.md#c (T)\n',
                     '[t](b.md#c\x01)\n', ')[t](<b.md#c)\n', '[t](<a.md#c>"T")\n', '[t](<a.md#c>(T))\n','[t](b.md#c "T" x)\n'):
            self.assertEqual(extract("d/a.md", text), [], repr(text))

    def test_non_ascii_space_stays_in_bare_destination(self):      # owner Q-C2VR2-2 (a): only ASCII ends the run
        hand = [0x85, 0xA0, 0x1680] + list(range(0x2000, 0x200B)) + [0x2028, 0x2029, 0x202F, 0x205F, 0x3000]
        self.assertEqual(len(hand), 19)
        table = [cp for cp in range(0x80, sys.maxunicode + 1) if chr(cp).isspace()]
        for cps in (hand, table):
            for cp in cps:
                tok = "b.md#x" + chr(cp) + "y"
                cs = extract("a.md", "[t](" + tok + ")\n")
                self.assertEqual([(c.token, c.path, c.anchor) for c in cs], [(tok, "b.md", "x" + chr(cp) + "y")], hex(cp))
        cs = extract("a.md", "[t](a.md#b 'T')\n")
        self.assertEqual([(c.token, c.anchor) for c in cs], [("a.md#b 'T'", "b 'T'")])

    def test_ascii_whitespace_and_controls_end_bare_destination(self):     # 0x00-0x20, 0x7f: then "y" is no title
        for cp in list(range(0x00, 0x21)) + [0x7F]:
            self.assertEqual(extract("a.md", "[t](b.md#x" + chr(cp) + "y)\n"), [], hex(cp))

    def test_backslash_forms_are_read_literally(self):     # owner Q-C21r-1 (b)
        for text in ('\\![t](b.md#c)\n', '[t](b.md#c "a\\"b")\n', "[t](b.md#c 'a\\'b')\n", '[t](b.md#c (a\\)b))\n'):
            cs = extract("d/a.md", text)
            self.assertEqual([(c.token, c.path, c.anchor) for c in cs], [("b.md#c", "d/b.md", "c")], text)
        for dest in ("a\\)b.md#c", "a\\(b.md#c"):
            c = one("[t](%s)\n" % dest)
            self.assertEqual((c.token, c.path), (dest, "d/" + dest.split("#")[0]))
            self.assertEqual(problem(c, frozenset({"d/a)b.md", "d/a(b.md"}), READ), "d/%s: not a tracked file" % dest.split("#")[0])
        self.assertEqual(extract("d/a.md", '[t](b.md#c "a\\")\n'), [])               # the escaped quote leaves the title open
        self.assertEqual(extract("d/a.md", '![t](b.md#c)\n'), [])                    # a plain image is still not a cite
        for text in ('[t](a\\)\n', '[t](a\\ b.md#c)\n', '[t](a\\\x7fb.md#c)\n', '[t](#a\\'):    # backslash then space, DEL, end of line
            self.assertEqual(extract("d/a.md", text), [], repr(text))
        self.assertEqual([c.token for c in extract("d/a.md", '[t](b.md#c "a\\\\")\n')], ["b.md#c"])    # literal backslash pair
        self.assertEqual([c.token for c in extract("d/a.md", '[t](b.md#c "\\"\\"x")\n')], ["b.md#c"])   # two escapes in a row

    # Known limits (owner Q-C21r-2 (c)): these pin today's behaviour, so a change is deliberate.
    def test_known_limit_s1_escaped_backtick_pairs_with_a_later_one(self):
        self.assertEqual(extract("d/a.md", "\\`x [t](b.md#c) `y`\n"), [])
        self.assertEqual(len(extract("d/a.md", "\\`x [t](b.md#c)\n")), 1)             # no later backtick: the link is found

    def test_known_limit_s2_escaped_gt_in_angle_destination(self):
        self.assertEqual(extract("d/a.md", "[t](<a\\>b.md#c>)\n"), [])

    def test_known_limit_s3_escaped_lt_in_angle_destination(self):
        self.assertEqual(extract("d/a.md", "[t](<a\\<b.md#c>)\n"), [])

    def test_non_link_things(self):
        for text in ("[m](mailto:a@b)\n", "![i](img.png#a)\n", "[a][b]\n", "[b]: x.md#y\n", "<https://x#y>\n", '<a href="x.md#y">\n',
                     "[t](C:/x.md#a)\n", "[t](a+b:x#y)\n", "[z](https://h/p#q)\n", "bare path:3 and x.md#y\n"):
            self.assertEqual(extract("d/a.md", text), [], text)

    def test_cite_token_text(self):
        cs = extract("d/a.md", '`gates/x.py:9` [s](b.md#nope "T") [u](<x%20y.md#z>)\n')
        self.assertEqual([c.token for c in cs], ["`gates/x.py:9`", "b.md#nope", "x%20y.md#z"])
        self.assertEqual(cs[2].path, "d/x y.md")

    def test_link_backslash_fails_closed(self):
        c = one("[t](b\\_c.md#x)\n")
        self.assertEqual(c.path, "d/b\\_c.md")
        self.assertIn("not a tracked file", problem(c, frozenset({"d/b_c.md"}), READ))

    def test_link_text_forms(self):
        self.assertEqual(len(extract("d/a.md", "[](b.md#c)\n")), 1)
        self.assertEqual(len(extract("d/a.md", "[a [b] c](x.md#y)\n")), 1)
        self.assertEqual(len(extract("d/a.md", "[a\\]](x.md#y)\n")), 1)
        self.assertEqual(extract("d/a.md", "a ](x.md#y)\n"), [])
        cs = extract("d/a.md", "[![i](p.png)](b.md#c)\n")
        self.assertEqual([c.token for c in cs], ["b.md#c"])

    def test_percent_decoding(self):
        for dest, path in (("x%20y.md#a", "d/x y.md"), ("x%2Fy.md#a", "d/x/y.md"), ("%2E%2E/x.md#a", "x.md"),
                           ("%zz.md#a", "d/%zz.md"), ("%ff.md#a", "d/%ff.md"), ("a%00.md#a", "d/a\x00.md"), ("a%2.md#a", "d/a%2.md"),
                           ("a%20%zz.md#a", "d/a%20%zz.md"), ("a%zz%20.md#a", "d/a%zz%20.md"),
                           ("caf%C3%A9.md#a", "d/caf\u00e9.md")):
            self.assertEqual(one("[t](%s)\n" % dest).path, path, dest)
        self.assertEqual(one("[t](b.md#caf%C3%A9)\n").anchor, "caf%C3%A9")            # the anchor is not decoded
        self.assertEqual(one("[t](b.md#x#y)\n").anchor, "x#y")

    def test_absolute_and_climbing_paths(self):
        for dest in ("/abs.md#a", "//host/x#y", "%2Fabs.md#a", "../../out.md#a"):
            c = one("[x](%s)\n" % dest, doc="a.md")
            self.assertIn("outside the repository", problem(c, TRACKED, READ), dest)
        self.assertEqual(one("[x](../a.md#a)\n", doc="d/a.md").path, "a.md")
        self.assertEqual(one("[x](../../a.md#a)\n", doc="a.md").path, "../../a.md")

    def test_balanced_parentheses(self):
        self.assertEqual(one("[t](a(b).md#c)\n").token, "a(b).md#c")


class LowercaseSlugifyTest(unittest.TestCase):
    def test_slugify_github_rule(self):
        self.assertEqual(slugify("Task 1a.2: result contract, config loader, git helpers"), "task-1a2-result-contract-config-loader-git-helpers")
        self.assertEqual(slugify("`gate_cites` and \u00dcn\u00efcode"), "gate_cites-and-\u00fcn\u00efcode")
        for heading, slug in [("Cafe\u0301 nfd", "cafe\u0301-nfd"), ("\u0939\u093f\u0928\u094d\u0926\u0940", "\u0939\u093f\u0928\u094d\u0926\u0940"),
                              ("x\u00b2 term", "x-term"), ("\u00bd", ""), ("a\u203fb", "a\u203fb"), ("\u24b6 circled", "\u24d0-circled"),
                              ("\u216b roman", "\u217b-roman"), ("\u039f\u0394\u039f\u03a3", "\u03bf\u03b4\u03bf\u03c2"),
                              ("\U0001f604 emoji", "-emoji"), ("a\tb", "ab"), ("a\u00a0b", "ab"), (" a ", "-a-"), (" ", "-"),
                              ("\ud800", "\ud800")]:
            with self.subTest(heading=heading):
                self.assertEqual(slugify(heading), slug)

    def test_inline_markup_is_raw_text(self):
        for heading, slug in [("`x`", "x"), ("_a_", "_a_"), ("**b**", "b"), ("[l](u)", "lu"), ("&amp;", "amp")]:
            self.assertEqual(slugify(heading), slug)

    def test_github_slugger_fixtures(self):
        self.assertEqual(number_repeats([slugify(i) for i, _ in SLUGGER_FIXTURES]), [e for _, e in SLUGGER_FIXTURES])

    def test_slugify_case_table_cases(self):
        for heading, slug in [("\u039f\u0394\u039f\u03a3", "\u03bf\u03b4\u03bf\u03c2"),
                              ("\u039f\u0394\u039f\u03a3 \u039a\u0391\u0399", "\u03bf\u03b4\u03bf\u03c2-\u03ba\u03b1\u03b9"),
                              ("\u039f\u03a3\u039f", "\u03bf\u03c3\u03bf"), ("\u03a3", "\u03c3"), ("\u0391'\u03a3", "\u03b1\u03c2"),
                              ("\u0391\u00b2\u03a3", "\u03b1\u03c3"), ("\u0391\u03a3\u00b2", "\u03b1\u03c2"),
                              ("\u0130", "i\u0307"), ("\u0130stanbul", "i\u0307stanbul"),
                              ("\U00010570\u03a3", "\u03c3"), ("\ua7cb", ""), ("\ua7dc", "")]:
            self.assertEqual(slugify(heading), slug, heading)

    def test_lowercase_cases(self):
        for text, low in [("", ""), ("\ud800", "\ud800"), ("ABC", "abc"), ("\u0130", "i\u0307"), ("\u03a3", "\u03c3"),
                          ("\u0391\u03a3", "\u03b1\u03c2"), ("\u03a3\u0391", "\u03c3\u03b1"), ("\u0391\u03a3\u0391", "\u03b1\u03c3\u03b1"),
                          ("\u0391\u03a3.", "\u03b1\u03c2."), ("\u0391'\u03a3'\u0391", "\u03b1'\u03c3'\u03b1"),
                          ("\u0391\u03a3\u03a3", "\u03b1\u03c3\u03c2")]:
            self.assertEqual(lowercase(text), low, text)

    def test_case_ignorable_and_cased_wins_while_skipping(self):
        # U+02B0 is both Cased and Case_Ignorable in Unicode 13.0.0 (U+00AA and U+00BA are Cased only): skipped, not counted as the cased neighbour
        self.assertTrue(cites._in_ranges(0x2B0, case_table.CASED_RANGES) and cites._in_ranges(0x2B0, case_table.CASE_IGNORABLE_RANGES))
        self.assertEqual(lowercase("\u02b0\u03a3"), "\u02b0\u03c3")          # skipped: nothing cased before
        self.assertEqual(lowercase("\u0391\u03a3\u02b0"), "\u03b1\u03c2\u02b0")   # skipped: nothing cased after
        self.assertEqual(lowercase("\u0391\u02b0\u03a3"), "\u03b1\u02b0\u03c2")

    def test_slugify_does_not_use_unicodedata(self):
        for mod in (cites, slug_table, case_table):
            text = pathlib.Path(mod.__file__).read_text(encoding="utf-8")
            tree = ast.parse(text)
            names = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
            names |= {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
            self.assertNotIn("unicodedata", names)
            self.assertNotIn("unicodedata", text)

    def test_slugify_does_not_use_str_lower(self):
        methods = ("lower", "casefold", "upper", "swapcase", "title", "capitalize")
        for mod in (cites, case_table):
            tree = ast.parse(pathlib.Path(mod.__file__).read_text(encoding="utf-8"))
            self.assertEqual([n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute) and n.attr in methods], [], mod.__name__)

    def test_strip_verdict_is_the_same_on_every_interpreter(self):
        rows = "\n".join("%X:%s" % (cp, cites.slugify(chr(cp)).encode("utf-8", "surrogatepass").hex()) for cp in range(0x110000))
        self.assertEqual(hashlib.sha256(rows.encode()).hexdigest(), VERDICT_SHA256)

    def test_lowercase_is_the_same_on_every_interpreter(self):
        same_version = unicodedata.unidata_version == "13.0.0"
        rows = []
        for cp in range(0x110000):
            if 0xD800 <= cp <= 0xDFFF:
                continue
            x = chr(cp)
            for s in (x, x + "\u03a3", "a" + x + "\u03a3", "a\u03a3" + x):
                low = cites.lowercase(s)
                if same_version and low != s.lower():
                    self.fail(hex(cp))
                rows.append(low)
        self.assertEqual(hashlib.sha256("\n".join(rows).encode("utf-8")).hexdigest(), LOWER_SHA256)

    def test_kept_classes(self):
        for ch in ("\ud800", "\udfff", "\u203f", "\u2160", "\u24b6", "\U0001f130", "\U0001f189", "-", "_"):
            self.assertEqual(len(slugify(ch)), 1, hex(ord(ch)))
        so = [c for lo, hi in ((0x24B6, 0x24E9), (0x1F130, 0x1F149), (0x1F150, 0x1F169), (0x1F170, 0x1F189)) for c in range(lo, hi + 1)]
        self.assertEqual(len(so), 130)
        self.assertTrue(all(slugify(chr(c)) != "" for c in so))


class TablesTest(unittest.TestCase):
    def test_slug_table_shape(self):
        t = slug_table.STRIP_RANGES
        self.assertTrue(isinstance(t, tuple) and all(isinstance(p, tuple) and len(p) == 2 for p in t))
        self.assertEqual(len(t), 736)
        self.assertEqual(sum(e - s + 1 for s, e in t), 977500)
        self.assertTrue(all(type(s) is int and type(e) is int and 0 <= s <= e <= 0x10FFFF for s, e in t))
        self.assertTrue(all(t[i][1] + 1 < t[i + 1][0] for i in range(len(t) - 1)))

    def test_slug_table_is_not_hand_edited(self):
        self.assertEqual(hashlib.sha256(repr(slug_table.STRIP_RANGES).encode()).hexdigest(), TABLE_SHA256)

    def test_case_table_shape(self):
        low = case_table.LOWER
        self.assertTrue(type(low) is dict and len(low) == 1393 and list(low) == sorted(low))
        self.assertTrue(all(type(k) is int and 0 <= k <= 0x10FFFF and type(v) is str and v and v != chr(k) for k, v in low.items()))
        self.assertEqual([k for k, v in low.items() if len(v) != 1], [0x130])
        self.assertEqual(low[0x130], "i\u0307")
        self.assertEqual(low[0x3A3], "\u03c3")
        for t, n, total in ((case_table.CASED_RANGES, 141, 4286), (case_table.CASE_IGNORABLE_RANGES, 410, 2413)):
            self.assertTrue(isinstance(t, tuple) and len(t) == n and sum(e - s + 1 for s, e in t) == total)
            self.assertTrue(all(type(p) is tuple and len(p) == 2 and type(p[0]) is int and type(p[1]) is int and 0 <= p[0] <= p[1] <= 0x10FFFF for p in t))
            self.assertTrue(all(t[i][1] + 1 < t[i + 1][0] for i in range(len(t) - 1)))

    def test_case_table_is_not_hand_edited(self):
        lower = tuple((k, tuple(ord(c) for c in v)) for k, v in sorted(case_table.LOWER.items()))
        canon = repr((lower, case_table.CASED_RANGES, case_table.CASE_IGNORABLE_RANGES))
        self.assertEqual(hashlib.sha256(canon.encode()).hexdigest(), CASE_TABLE_SHA256)

    def test_generated_files_are_ascii_with_header(self):
        for mod in (slug_table, case_table):
            data = pathlib.Path(mod.__file__).read_bytes()
            data.decode("ascii")
            self.assertTrue(data.startswith(b"# GENERATED FILE. DO NOT EDIT BY HAND."))


class AnchorsTest(unittest.TestCase):
    def test_repeat_numbering_skips_taken_slugs(self):
        self.assertEqual(number_repeats(["a", "a-1", "a"]), ["a", "a-1", "a-2"])
        self.assertEqual(number_repeats(["a", "a", "a-1"]), ["a", "a-1", "a-1-1"])
        self.assertEqual(anchors("# a\n# a-1\n# a\n"), frozenset({"a", "a-1", "a-2"}))

    def test_number_repeats_edges(self):
        self.assertEqual(number_repeats([]), [])
        self.assertEqual(number_repeats(["", "", ""]), ["", "-1", "-2"])
        src = ["a", "a"]
        out = number_repeats(src)
        self.assertEqual(src, ["a", "a"])
        self.assertIsNot(out, src)

    def test_duplicate_headings_numbered(self):
        self.assertEqual(anchors("# A\n## A\n### A\n"), frozenset({"a", "a-1", "a-2"}))

    def test_heading_levels(self):
        self.assertEqual(anchors("# a\n## b\n### c\n#### d\n##### e\n###### f\n"), frozenset("abcdef"))
        for text in ("####### a\n", "#a\n", "#\ta\n", " # a\n", "  # a\n", "   # a\n", "> # a\n", "- # a\n", "\ufeff# a\n", "#\n"):
            self.assertEqual(anchors(text), frozenset(), repr(text))

    def test_closing_sequence_and_spaces(self):
        for text, slug in (("# a #\n", "a"), ("# a ##  \n", "a"), ("#   a\n", "a"), ("# a#\n", "a"), ("# #\n", ""), ("# \n", ""), ("# a # b\n", "a--b"), ("# a #b\n", "a-b"),
                           ("#  a b  \n", "a-b"), ("# `Code` and, Punct!\n", "code-and-punct"), ("# \u00dcn\u00ef\n", "\u00fcn\u00ef")):
            self.assertEqual(anchors(text), frozenset({slug}), repr(text))

    def test_tab_before_closing_sequence(self):            # F-VR2-2: [ \t]+#+\Z with a tab in the run before the #s
        for text in ("# a \t#\n", "# a \t##\n", "# a\t #\n", "# a\t#\n", "# a \t \t#\n", "# a\t\t###\n"):
            self.assertEqual(anchors(text), frozenset({"a"}), repr(text))
        for text in ("# a#\n", "# a #\n", "# a\v#\n"):   # controls: no blank before the #s, a space, a \v (not a blank)
            self.assertEqual(anchors(text), frozenset({"a"}), repr(text))

    def test_fences_and_setext(self):
        self.assertEqual(anchors("```\n# a\n```\nb\n===\nc\n---\n"), frozenset())
        self.assertEqual(anchors("~~~\n# a\n"), frozenset())


class ProblemTest(unittest.TestCase):
    def test_line_bounds(self):
        self.assertEqual(prob("`a/b.py:3`"), "")
        self.assertEqual(prob("`a/b.py:4`"), "a/b.py: line 4 is past the end (3 lines)")
        self.assertEqual(prob("`a/nl.py:3`"), "")
        self.assertEqual(prob("`a/nl.py:4`"), "a/nl.py: line 4 is past the end (3 lines)")
        self.assertEqual(prob("`a/empty.py:1`"), "a/empty.py: line 1 is past the end (0 lines)")
        self.assertEqual(prob("`a/blank.py:1`"), "")
        self.assertEqual(prob("`a/blank.py:2`"), "a/blank.py: line 2 is past the end (1 lines)")
        self.assertEqual(prob("`a/crlf.py:2`"), "")
        self.assertEqual(prob("`a/crlf.py:3`"), "a/crlf.py: line 3 is past the end (2 lines)")
        self.assertEqual(prob("`a/b.py:99999999999999999999`"), "a/b.py: line 99999999999999999999 is past the end (3 lines)")

    def test_zero_leading_zero_and_ranges(self):
        msg = "a/b.py: line numbers start at 1 and have no leading zero"
        for tok in ("`a/b.py:0`", "`a/b.py:01`", "`a/b.py:1-01`", "`a/b.py:0-2`", "`a/b.py:00`"):
            self.assertEqual(prob(tok), msg, tok)
        self.assertEqual(prob("`a/b.py:3-1`"), "a/b.py: range end 1 is before start 3")
        self.assertEqual(prob("`a/b.py:1-1`"), "")
        self.assertEqual(prob("`a/b.py:1-3`"), "")
        self.assertEqual(prob("`a/b.py:2-9`"), "a/b.py: line 9 is past the end (3 lines)")
        self.assertEqual(prob("`a/b.py:4-9`"), "a/b.py: line 4 is past the end (3 lines)")

    def test_target_kinds(self):
        self.assertEqual(prob("`x/untracked.md#a`"), "x/untracked.md: not a tracked file")
        self.assertIn("outside the repository", problem(extract("a.md", "[x](../../out.md#a)\n")[0], TRACKED, READ))
        self.assertEqual(prob("`a/b.py#x`"), "a/b.py: anchor on a non-markdown file")
        self.assertEqual(prob("`a/c.md#`"), "a/c.md: empty anchor")
        self.assertEqual(prob("`a/b.py:1`", read=lambda p: None), "a/b.py: tracked but missing from the working tree")
        self.assertEqual(prob("`a/deleted.py:1`"), "a/deleted.py: tracked but missing from the working tree")

    def test_anchor_matching(self):
        self.assertEqual(prob("`a/c.md#intro`"), "")
        self.assertEqual(prob("`a/c.md#intro-1`"), "")
        self.assertEqual(prob("`a/c.md#Intro`"), "a/c.md: no heading with anchor #Intro")
        self.assertEqual(prob("`a/c.md#hidden`"), "a/c.md: no heading with anchor #hidden")
        self.assertEqual(prob("`a/c.md#title`"), "a/c.md: no heading with anchor #title")
        self.assertEqual(prob("`a/c.md#code-and-punct`"), "")
        self.assertEqual(prob("`a/c.md#\u00fcn\u00ef`"), "")
        self.assertEqual(prob("`a/B.MD#x`"), "a/B.MD: anchor on a non-markdown file")
        self.assertEqual(prob("[t](c.md#intro-1)", doc="a/z.md"), "")
        self.assertEqual(prob("[t](#intro)", doc="a/c.md"), "")
        self.assertEqual(prob("[t](c.md#nope)", doc="a/z.md"), "a/c.md: no heading with anchor #nope")
        self.assertEqual(prob("[t](b.md#x#y)", doc="a/z.md"), "a/b.md: not a tracked file")

    def test_path_forms(self):
        for p in ("./a/b.py", "a//b.py", "a/b.py/", "a/../a/b.py", "A/b.py"):
            self.assertEqual(prob("`%s:1`" % p), "%s: not a tracked file" % p, p)
        for p in ("/abs.md", "../x.py", "a/../../x.py", ".."):
            self.assertEqual(prob("`%s:1`" % p, tracked=frozenset({p}), read=lambda q: "x\n"), "%s: outside the repository" % p, p)
        self.assertEqual(prob("`a(b).md#p`"), "")
        self.assertEqual(prob("[t](<x y.md#z>)"), "")
        self.assertEqual(prob("`a/b.py:1`", tracked=frozenset()), "a/b.py: not a tracked file")

    def test_outside_is_checked_before_tracked_and_read(self):
        def boom(p):
            raise AssertionError("read called")
        self.assertEqual(prob("`../x.py:1`", tracked=frozenset(), read=boom), "../x.py: outside the repository")
        self.assertEqual(prob("`x/y.py:1`", tracked=frozenset(), read=boom), "x/y.py: not a tracked file")

    def test_not_utf8(self):
        self.assertEqual(prob("`a/bad.py:1`"), "a/bad.py: not UTF-8")
        self.assertEqual(prob("`a/bad.md#x`"), "a/bad.md: not UTF-8")
        self.assertEqual(prob("`a/bad.py#x`"), "a/bad.py: not UTF-8")           # before the non-markdown check
        self.assertEqual(prob("`a/bad.py:9`"), "a/bad.py: not UTF-8")           # before the past-the-end check

    def test_read_error_propagates(self):
        def bad(p):
            raise OSError("boom")
        with self.assertRaises(OSError):
            prob("`a/b.py:1`", read=bad)

    def test_check_order_for_a_line_cite(self):
        self.assertEqual(prob("`a/b.py:0-9`"), "a/b.py: line numbers start at 1 and have no leading zero")
        self.assertEqual(prob("`a/b.py:9-5`"), "a/b.py: range end 5 is before start 9")

    def test_tracked_symlink_is_not_tracked(self):
        # tracked_files lists only regular files, so a symlink path is absent from `tracked`
        self.assertEqual(prob("`a/link.py:1`"), "a/link.py: not a tracked file")

    def test_returns_cite_type(self):
        self.assertIsInstance(one("`a/b.py:1`"), Cite)


class LineNumberDigitCountTest(unittest.TestCase):
    """F-C2fin2-1: a line number of any digit count gives one verdict on every Python 3.9+; CPython 3.11+ limits int()
    of a decimal string to 4300 digits by default, so no int() of a cite's whole digit run may happen past that.
    Expected values are built from the digit text and powers of ten, never by converting the digit run."""

    PAST = "a/b.py: line %s is past the end (3 lines)"

    def test_start_digit_count(self):  # ND1
        for n in (1, 4300, 4301, 10000):
            digits = "9" * n
            c = one("`a/b.py:%s`" % digits)
            self.assertEqual((c.start, c.end), (10 ** n - 1, None), n)
            self.assertEqual(problem(c, TRACKED, READ), self.PAST % digits, n)
        self.assertEqual(prob("`a/b.py:3`"), "")
        self.assertEqual(prob("`a/b.py:%s`" % ("1" + "0" * 4300)), self.PAST % ("1" + "0" * 4300))

    def test_range_end_digit_count(self):  # ND2
        big, bigger = "9" * 4301, "9" * 4302
        c = one("`a/b.py:1-%s`" % big)
        self.assertEqual((c.start, c.end), (1, 10 ** 4301 - 1))
        self.assertEqual(problem(c, TRACKED, READ), self.PAST % big)
        c = one("`a/b.py:%s-%s`" % (big, bigger))
        self.assertEqual((c.start, c.end), (10 ** 4301 - 1, 10 ** 4302 - 1))
        self.assertEqual(problem(c, TRACKED, READ), self.PAST % big)
        self.assertEqual(prob("`a/b.py:%s-%s`" % (bigger, big)), "a/b.py: range end %s is before start %s" % (big, bigger))
        self.assertEqual(prob("`a/b.py:%s-1`" % big), "a/b.py: range end 1 is before start %s" % big)
        self.assertEqual(prob("`a/b.py:%s-%s`" % (big, big)), self.PAST % big)
        self.assertEqual(prob("`a/b.py:%s-%s`" % ("1" + "0" * 4301, "9" * 4301)),
                         "a/b.py: range end %s is before start %s" % ("9" * 4301, "1" + "0" * 4301))

    def test_leading_zeros(self):  # ND3
        msg = "a/b.py: line numbers start at 1 and have no leading zero"
        padded = "0" * 4400 + "2"
        self.assertEqual(one("`a/b.py:0003`").start, 3)
        self.assertEqual(one("`a/b.py:%s`" % padded).start, 2)
        self.assertEqual(one("`a/b.py:1-%s`" % padded).end, 2)
        for tok in ("0003", padded, "1-" + padded, padded + "-3", "0" + "9" * 4301):
            self.assertEqual(prob("`a/b.py:%s`" % tok), msg, tok[:8])

    def test_zero_and_end_before_start(self):  # ND4
        msg = "a/b.py: line numbers start at 1 and have no leading zero"
        for tok in ("0", "0" * 4301, "0-3", "5-0", "5-" + "0" * 4301):
            self.assertEqual(prob("`a/b.py:%s`" % tok), msg, tok[:8])
        self.assertEqual(one("`a/b.py:%s`" % ("0" * 4301)).start, 0)
        self.assertEqual(prob("`a/b.py:5-3`"), "a/b.py: range end 3 is before start 5")
        self.assertEqual(prob("`a/b.py:05-3`"), msg)
        self.assertEqual(prob("`a/b.py:%s-3`" % ("5" * 4301)), "a/b.py: range end 3 is before start %s" % ("5" * 4301))

    def test_percent_escape_is_two_hex_digits(self):  # ND5: cites.py _PERCENT bounds the int(.., 16) argument
        self.assertEqual(cites._PERCENT.pattern, r"%([0-9A-Fa-f]{2})")
        self.assertEqual([len(m.group(1)) for m in cites._PERCENT.finditer("%" + "f" * 5000 + "%41")], [2, 2])
        long_hex = "a" * 5000
        c = one("[t](%%41%s.md#x)" % long_hex)
        self.assertEqual(c.path, "d/A%s.md" % long_hex)

    @unittest.skipUnless(hasattr(sys, "set_int_max_str_digits"), "no int string-conversion limit on this interpreter")
    def test_lowest_conversion_limit(self):  # ND1/ND7 under PYTHONINTMAXSTRDIGITS=640, the lowest limit CPython accepts
        self.addCleanup(sys.set_int_max_str_digits, sys.get_int_max_str_digits())
        sys.set_int_max_str_digits(640)
        for n in (641, 4300, 5000):
            self.assertTrue(one("`a/b.py:%s`" % ("9" * n)).start == 10 ** n - 1, n)
            self.assertTrue(prob("`a/b.py:1-%s`" % ("9" * n)) == self.PAST % ("9" * n), n)

    def test_verdict_text_never_converts_the_digit_run(self):  # ND7: %d of a 4301-digit int raises on 3.11+
        c = Cite("d/a.md", 1, "`a/b.py:%s`" % ("9" * 4301), "a/b.py", 10 ** 4301 - 1, None, None)
        self.assertEqual(problem(c, TRACKED, READ), self.PAST % ("9" * 4301))
        # a Cite built by hand whose token is not a line cite still prints its own numbers
        self.assertEqual(problem(Cite("d/a.md", 1, "x", "a/b.py", 9, None, None), TRACKED, READ), self.PAST % "9")
        self.assertEqual(problem(Cite("d/a.md", 1, "x", "a/b.py", 2, 8, None), TRACKED, READ), self.PAST % "8")
        self.assertEqual(problem(Cite("d/a.md", 1, "x", "a/b.py", 3, 1, None), TRACKED, READ), "a/b.py: range end 1 is before start 3")


class ExtractLoopControlTest(unittest.TestCase):
    """A non-matching item must not end the scan of the later items on the same line."""

    def tokens(self, text):
        return [c.token for c in extract("d/x.md", text)]

    def test_longer_backtick_run_does_not_end_the_line(self):
        self.assertEqual(self.tokens("``x`` `a/b.py:1`"), ["`a/b.py:1`"])

    def test_non_cite_span_does_not_end_the_line(self):
        self.assertEqual(self.tokens("`a b` `a/b.py:1`"), ["`a/b.py:1`"])

    def test_path_without_slash_or_dot_does_not_end_the_line(self):
        self.assertEqual(self.tokens("`ab:1` `a/b.py:1`"), ["`a/b.py:1`"])

    def test_unparsable_destination_does_not_end_the_line(self):
        self.assertEqual(self.tokens("[a](b.md#c x) [b](c.md#d)"), ["c.md#d"])

    def test_non_cite_destination_does_not_end_the_line(self):
        self.assertEqual(self.tokens("[a](https://x#y) [b](c.md#d)"), ["c.md#d"])


if __name__ == "__main__":
    unittest.main()
