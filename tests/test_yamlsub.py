"""Tests for the strict YAML subset (gates.lib.yamlsub), through its public API."""
import enum
import os
import random
import tempfile
import unittest

from gates.lib.yamlsub import EmitError, YamlError, emit, load, parse


def _dq_text(s):
    return '"' + s + '"\n'


def _load_bytes(data, shown="x.yml"):
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "f.yml")
        with open(p, "wb") as fh:
            fh.write(data)
        return load(p, shown)


class _FsPath:
    """An os.PathLike whose __fspath__ returns an arbitrary value."""

    def __init__(self, value):
        self.value = value

    def __fspath__(self):
        return self.value


class TestParse(unittest.TestCase):
    def test_unicode_whitespace_line_is_not_blank_or_comment(self):
        """N2: kills an argument-less strip() in the blank/comment skip."""
        self.assertEqual(parse("\xa0\n"), "\xa0")
        self.assertEqual(parse("\xa0# c\n"), "\xa0# c")
        self.assertEqual(parse("\u3000\n"), "\u3000")
        with self.assertRaises(YamlError) as cm:
            parse("a: 1\n\u3000\n")
        self.assertEqual(cm.exception.line, 2)

    def test_mapping_sequence_and_scalars(self):
        text = "a: 1\nb: [x, \"y z\"]\nc:\n  - k: v\n    n: null\nd: |\n  line1\n  line2\n"
        self.assertEqual(parse(text), {"a": 1, "b": ["x", "y z"], "c": [{"k": "v", "n": None}], "d": "line1\nline2\n"})

    def test_ambiguous_plain_scalars_are_strings(self):
        for s in ["yes", "no", "on", "off", "2026-10-31", "1.0", "0.1.0", "007", "True", "NULL"]:
            self.assertEqual(parse(f"k: {s}\n"), {"k": s}, s)
            self.assertEqual(parse(emit({"k": s})), {"k": s}, s)

    def test_typed_scalars(self):
        text = "a: true\nb: false\nc: null\nd: ~\ne:\nf: 0\ng: -12\nh: 10\ni: -0\n"
        self.assertEqual(parse(text), {"a": True, "b": False, "c": None, "d": None, "e": None,
                                       "f": 0, "g": -12, "h": 10, "i": 0})

    def test_quoted_scalars_stay_strings(self):
        self.assertEqual(parse("a: 'true'\nb: \"1\"\nc: 'it''s'\nd: \"q\\\"\\\\\\n\\t\\u00e9\"\n"),
                         {"a": "true", "b": "1", "c": "it's", "d": "q\"\\\n\t\u00e9"})

    def test_quoted_keys(self):
        self.assertEqual(parse("'a b': 1\n\"c: d\": 2\n'<<': 3\n"), {"a b": 1, "c: d": 2, "<<": 3})

    def test_sequence_at_parent_indent(self):
        self.assertEqual(parse("a:\n- 1\n- 2\n"), {"a": [1, 2]})
        self.assertEqual(parse("a:\n- 1\nb: 2\n"), {"a": [1], "b": 2})

    def test_sequence_variants(self):
        self.assertEqual(parse("- a\n- - b\n  - c\n- k: v\n  l:\n  - 1\n-\n  - z\n- \n"),
                         ["a", ["b", "c"], {"k": "v", "l": [1]}, ["z"], None])
        self.assertEqual(parse("- |\n  x\n  y\n- |-\n  z\n"), ["x\ny\n", "z"])

    def test_flow_sequences(self):
        self.assertEqual(parse("a: []\nb: [1, true, 'x, y', \"z\" ] # c\nc: [ ]\n"),
                         {"a": [], "b": [1, True, "x, y", "z"], "c": []})

    def test_block_scalars(self):
        self.assertEqual(parse("a: |-\n  x\n   y\n\n  z\nb: 1\n"), {"a": "x\n y\n\nz", "b": 1})
        self.assertEqual(parse("a: |\n  x\n\n\nb: 1\n"), {"a": "x\n", "b": 1})
        self.assertEqual(parse("a: | # note\n  x\n"), {"a": "x\n"})
        self.assertEqual(parse("a: |\nb: 1\n"), {"a": "", "b": 1})
        # indentation is taken from the first content line
        self.assertEqual(parse("a: |\n    x\n      y\n"), {"a": "x\n  y\n"})
        # a comment-looking line is content inside the block
        self.assertEqual(parse("a: |\n  # c\n  x\n"), {"a": "# c\nx\n"})
        # a dedented comment ends the block
        self.assertEqual(parse("a: |\n  x\n# c\nb: 1\n"), {"a": "x\n", "b": 1})

    def test_block_scalar_in_sequence_mapping(self):
        self.assertEqual(parse("- k: |\n    t\n  m: 1\n"), [{"k": "t\n", "m": 1}])

    def test_comments_and_empty_document(self):
        self.assertEqual(parse("# only\n\n"), None)
        self.assertEqual(parse(""), None)
        self.assertEqual(parse("a: b # note\nc: 'd # not'\n"), {"a": "b", "c": "d # not"})
        self.assertEqual(parse("a: b#not\n"), {"a": "b#not"})
        self.assertEqual(parse("a:   # c\n  b: 1\n"), {"a": {"b": 1}})

    def test_top_level_scalars(self):
        self.assertEqual(parse("hello\n"), "hello")
        self.assertEqual(parse("12\n"), 12)
        self.assertEqual(parse("[]\n"), [])
        self.assertEqual(parse("|\n  a\n  b\n"), "a\nb\n")

    def test_colon_without_space_is_not_a_key(self):
        self.assertEqual(parse("a: http://x.y/z\n"), {"a": "http://x.y/z"})

    def test_key_order_is_preserved(self):
        self.assertEqual(list(parse("z: 1\na: 2\nm: 3\n")), ["z", "a", "m"])

    def test_crlf_and_bom_accepted(self):
        self.assertEqual(_load_bytes(b"\xef\xbb\xbfa: 1\r\nb: 2\r\n"), {"a": 1, "b": 2})

    def test_load_without_bom(self):
        self.assertEqual(_load_bytes(b"a: \xc3\xa9\n"), {"a": "\u00e9"})

    def test_invalid_utf8_names_file(self):
        with self.assertRaises(YamlError) as cm:
            _load_bytes(b"a: \xff\n", "state/x.yml")
        self.assertIn("state/x.yml", str(cm.exception))
        self.assertIn("not valid UTF-8", str(cm.exception))
        self.assertEqual(cm.exception.line, 0)

    def test_load_parse_error_names_file(self):
        with self.assertRaises(YamlError) as cm:
            _load_bytes(b"a: 1\na: 2\n", "cfg/y.yml")
        self.assertEqual(cm.exception.line, 2)
        self.assertIn("cfg/y.yml", cm.exception.reason)
        self.assertEqual(str(cm.exception), "line 2: " + cm.exception.reason)

    def test_error_str_format(self):
        e = YamlError(4, "boom")
        self.assertEqual((e.line, e.reason, str(e)), (4, "boom", "line 4: boom"))


class TestRefuse(unittest.TestCase):
    def _refuse(self, text, line, fragment=None):
        with self.assertRaises(YamlError) as cm:
            parse(text)
        self.assertEqual(cm.exception.line, line, str(cm.exception))
        if fragment:
            self.assertIn(fragment, cm.exception.reason)

    def test_anchor(self):
        self._refuse("a: 1\nb: &x 2\n", 2, "anchor")

    def test_alias(self):
        self._refuse("a: *x\n", 1, "alias")

    def test_tag(self):
        self._refuse("a: !!str x\n", 1, "tag")

    def test_merge_key(self):
        self._refuse("a: 1\n<<: b\n", 2, "merge")

    def test_duplicate_key(self):
        self._refuse("a: 1\nb: 2\na: 3\n", 3, "duplicate key 'a'")

    def test_duplicate_key_nested(self):
        self._refuse("- k: 1\n  k: 2\n", 2, "duplicate key 'k'")

    def test_tab_indent(self):
        self._refuse("a:\n\t- 1\n", 2, "tab")

    def test_flow_mapping(self):
        self._refuse("a: {b: 1}\n", 1, "flow mapping")

    def test_folded_scalar(self):
        self._refuse("a: >\n  x\n", 1, "folded")

    def test_document_markers(self):
        self._refuse("---\na: 1\n", 1, "marker")
        self._refuse("a: 1\n...\n", 2, "marker")
        self._refuse("a: 1\n--- \nb: 2\n", 2, "marker")

    def test_inconsistent_indentation(self):
        self._refuse("a:\n    b: 1\n  c: 2\n", 3, "indent")
        self._refuse("a: 1\n  b: 2\n", 2, "indent")
        self._refuse("- a\n - b\n", 2, "indent")

    def test_other_indicators(self):
        for ch in "%@`":
            self._refuse(f"a: {ch}x\n", 1, "may not start")
        self._refuse("a: ,x\n", 1)
        self._refuse("a: ]\n", 1)
        self._refuse("a: - x\n", 1)

    def test_block_scalar_headers(self):
        self._refuse("a: |+\n  x\n", 1, "block scalar")
        self._refuse("a: |2\n  x\n", 1, "block scalar")
        self._refuse("a: |x\n  x\n", 1, "block scalar")

    def test_quoting_errors(self):
        self._refuse("a: 'x\n", 1, "unterminated")
        self._refuse("a: \"x\n", 1, "unterminated")
        self._refuse("a: \"x\" y\n", 1, "after")
        self._refuse("a: \"\\q\"\n", 1, "escape")
        self._refuse("a: \"\\u12\"\n", 1, "escape")
        self._refuse("a: \"\\u+123\"\n", 1, "escape")
        self._refuse("a: \"\\ud800\"\n", 1, "surrogate")

    def test_flow_errors(self):
        self._refuse("a: [1, 2\n", 1, "unterminated")
        self._refuse("a: [1,, 2]\n", 1)
        self._refuse("a: [1, 2,]\n", 1)
        self._refuse("a: [[1]]\n", 1)
        self._refuse("a: [{x: 1}]\n", 1)
        self._refuse("a: [x: 1]\n", 1)
        self._refuse("a: [1] z\n", 1)

    def test_flow_plain_scalar_with_space_is_a_string(self):
        self.assertEqual(parse("a: [1 2, b c]\n"), {"a": ["1 2", "b c"]})

    def test_block_header_as_key_is_refused(self):
        self._refuse("|: x\n", 1)

    def test_structure_errors(self):
        self._refuse("a: 1\nplain\n", 2, "key")
        self._refuse("a: b: c\n", 1)
        self._refuse("a: b:\n", 1)
        self._refuse("a:\n  plain\n", 2)
        self._refuse(": x\n", 1, "empty key")
        self._refuse("a: 1\n- b\n", 2)
        self._refuse("- a\nb: 1\n", 2)
        self._refuse("hello\nworld\n", 2)

    def test_control_characters(self):
        self._refuse("a: 1\r\nb: 2\n", 1, "control")
        self._refuse("a: \x00\n", 1, "control")

    def test_integer_too_large(self):
        self._refuse("a: " + "9" * 5000 + "\n", 1, "integer")

    def test_nesting_too_deep(self):
        text = "".join("- " * 1 for _ in range(300)) + "x\n"
        self._refuse(text, 1, "deep")


class TestEmit(unittest.TestCase):
    CORPUS = [
        None, True, False, 0, 7, -3, "", "x", "a: b", "a #b", "-lead", "- x", "-", "'q'", '"q"',
        "tab\there", "two\nlines", "two\nlines\n", "\n", "end\n\n", "lead\n x", " lead", "trail ",
        "unicode \u00e9\u4e2d", "x:", ":x", "?", "? x", "#c", "a#b", "---", "...", "<<", "true", "null",
        "~", "12", "-0", "[a]", "{a}", "&a", "*a", "!a", ">", "|", "%", "@", "`", "back\\slash",
        "\r\n", "nbsp\u00a0x", "ctl\x01", "\ufeffbom", "ok\n  indented\nmore\n",
        [], [1, [], {"a": None}], [[1, 2], [3]], [[], [[]]], ["a: b", "c"],
        {"a": 1}, {"a": []}, {"a": [{"k": "v", "n": [1, 2], "m": {"x": "y"}}, {"z": 0}]},
        {"a b": 1, "c: d": 2, "": 3, "true": 4, "1": 5, "#k": 6, "<<": 7, "- x": 8, "multi\nkey": 9},
        {"s": "line1\nline2\n", "t": "line1\nline2", "u": "x\n\ny", "v": ["m\nn\n", "o\np"]},
        {"a": {"b": {"c": {"d": [1, {"e": "f"}]}}}},
        [{"k": "multi\nline\n", "j": 1}, {"k": "x"}],
        {"a": None, "b": [None, True]},
    ]

    def test_round_trip_corpus(self):
        self.assertGreaterEqual(len(self.CORPUS), 30)
        for v in self.CORPUS:
            text = emit(v)
            self.assertTrue(text.endswith("\n") and not text.endswith("\n\n"), repr(v))
            self.assertEqual(parse(text), v, repr(v) + " -> " + repr(text))
            self.assertEqual(emit(parse(text)), text, repr(v))

    def test_canonical_text(self):
        self.assertEqual(emit({"a": 1, "b": [], "c": [{"k": "v", "n": None}], "d": "x\ny\n", "e": "x\ny", "f": "p q"}),
                         "a: 1\nb: []\nc:\n  - k: v\n    n: null\nd: |\n  x\n  y\ne: |-\n  x\n  y\nf: p q\n")
        self.assertEqual(emit({"a": ["x", "y"], "b": {"c": True}}), "a:\n  - x\n  - y\nb:\n  c: true\n")
        self.assertEqual(emit("hi"), "hi\n")
        self.assertEqual(emit([]), "[]\n")
        self.assertEqual(emit(None), "null\n")

    def test_quoting_rules(self):
        self.assertEqual(emit({"k": "12"}), 'k: "12"\n')
        self.assertEqual(emit({"k": "true"}), 'k: "true"\n')
        self.assertEqual(emit({"k": "a: b"}), 'k: "a: b"\n')
        self.assertEqual(emit({"k": "a\tb"}), 'k: a\tb\n')
        self.assertEqual(emit({"k": "\ta"}), 'k: "\\ta"\n')
        self.assertEqual(emit({"k": "a\t"}), 'k: "a\\t"\n')
        self.assertEqual(emit({"k": "two\n\n"}), 'k: "two\\n\\n"\n')
        self.assertEqual(emit({"k": "True"}), "k: True\n")

    def test_emit_refuses_float_and_empty_dict(self):
        for bad in [1.5, {}, {"a": {}}, [{}], {1: "x"}, {None: 1}, (1, 2), {1, 2}, b"x", [1.0],
                    "lone\ud800", {"a\udc00": 1}]:
            with self.assertRaises(EmitError, msg=repr(bad)):
                emit(bad)
        self.assertTrue(issubclass(EmitError, ValueError))

    def test_emit_refuses_deep_nesting_and_huge_int(self):
        v = []
        for _ in range(300):
            v = [v]
        with self.assertRaises(EmitError):
            emit(v)
        with self.assertRaises(EmitError):
            emit(10 ** 5000)

    def test_fuzz_never_crashes(self):
        rnd = random.Random(1)
        tokens = ["a:", "b: 1", "k: v", "- x", "- k: v", "-", "- - y", "[a, 'b']", "[]", "|", "|-", "k: |", "k: |-",
                  "# c", "'q'", "\"d\\n\"", "&x", "*y", "!t", "{a: 1}", ">", "---", "\t", "yes", "null", "~",
                  "1", "-2", "", "z: [1, \"2\"]", "'it''s'", "x: y # c", "q:", "- |", "a: 'x: y'", "<<: m",
                  "\"u\\u00e9\"", "t: true", "0", "007", "a b: c", "plain text", "- 'x'", "  deeper"]
        accepted = 0
        for _ in range(2000):
            lines = []
            for _ in range(rnd.randint(0, 8)):
                lines.append(" " * rnd.choice([0, 0, 0, 1, 2, 2, 4, 6]) + rnd.choice(tokens))
            text = "\n".join(lines) + rnd.choice(["", "\n"])
            try:
                v = parse(text)
            except YamlError:
                continue
            accepted += 1
            try:
                out = emit(v)
            except EmitError:
                self.fail(f"accepted value not emittable: {text!r} -> {v!r}")
            self.assertEqual(parse(out), v, repr(text))
            self.assertEqual(emit(parse(out)), out, repr(text))
        self.assertGreater(accepted, 100)


class TestUnicodeWhitespaceIsContent(unittest.TestCase):
    """F1: only space and tab are YAML whitespace; other Unicode whitespace is content."""
    CHARS = ["\xa0", "\u3000", "\x85", "\u2028", "\u2029", "\u1680", "\u2003"]

    def test_plain_values(self):
        for c in self.CHARS:
            for text, want in [(f"a: {c}x\n", c + "x"), (f"a: x{c}\n", "x" + c), (f"a: {c}\n", c),
                               (f"a: x{c}y # note\n", "x" + c + "y")]:
                self.assertEqual(parse(text), {"a": want}, repr(text))

    def test_keys(self):
        for c in self.CHARS:
            self.assertEqual(parse(f"a{c}: 1\n"), {"a" + c: 1}, repr(c))
            self.assertEqual(parse(f"{c}a: 1\n"), {c + "a": 1}, repr(c))

    def test_flow_items(self):
        for c in self.CHARS:
            self.assertEqual(parse(f"[{c}a, b{c}, {c}]\n"), [c + "a", "b" + c, c], repr(c))

    def test_after_quoted_scalar_is_refused(self):
        for c in self.CHARS:
            with self.assertRaises(YamlError, msg=repr(c)):
                parse(f"a: 'x'{c}\n")

    def test_block_scalar_lines(self):
        for c in self.CHARS:
            # an unindented Unicode-whitespace line is content of the document, not a blank line
            with self.assertRaises(YamlError, msg=repr(c)):
                parse(f"k: |\n  a\n{c}\n  b\n")
            self.assertEqual(parse(f"k: |\n  a\n  {c}\n  b\n"), {"k": f"a\n{c}\nb\n"}, repr(c))

    def test_round_trip(self):
        for c in self.CHARS:
            for v in [c, c + "x", "x" + c, {"k" + c: c}, [c], {"k": f"a\n{c}\nb\n"}]:
                self.assertEqual(parse(emit(v)), v, repr(v))

    def test_c1_is_not_a_refused_control_character(self):
        self.assertEqual(parse("a: \x85\n"), {"a": "\x85"})


class TestTabSeparators(unittest.TestCase):
    """F2: a tab used as a separator after ':', '-' or ',' is refused with a line."""

    def _refuse(self, text, line):
        with self.assertRaises(YamlError, msg=repr(text)) as cm:
            parse(text)
        self.assertEqual(cm.exception.line, line, str(cm.exception))
        self.assertIn("tab", cm.exception.reason)

    def test_tab_after_colon(self):
        self._refuse("a:\t1\n", 1)
        self._refuse("x: 1\na:\t1\n", 2)
        self._refuse("- a:\t1\n", 1)
        self._refuse("k:\n  - a:\t1\n", 2)
        self._refuse("\"a\":\t1\n", 1)
        self._refuse("k: a:\tb\n", 1)

    def test_tab_after_dash(self):
        self._refuse("-\t1\n", 1)
        self._refuse("- a\n-\tb\n", 2)
        self._refuse("k:\n-\ta\n", 2)
        self._refuse("k: -\ta\n", 1)
        self._refuse("- \ta\n", 1)

    def test_tab_in_flow_sequence(self):
        self._refuse("[1,\t2]\n", 1)
        self._refuse("[\t1]\n", 1)
        self._refuse("k: [1\t, 2]\n", 1)
        self._refuse("k: [1, 2\t]\n", 1)

    def test_tab_inside_scalars_is_content(self):
        self.assertEqual(parse("a: x\ty\n"), {"a": "x\ty"})
        self.assertEqual(parse("a: \"x\\ty\"\n"), {"a": "x\ty"})
        self.assertEqual(parse("a: [x\ty]\n"), {"a": ["x\ty"]})
        self.assertEqual(parse("a: 1 \t# c\n"), {"a": 1})


class TestBlockScalarBlankLines(unittest.TestCase):
    """F3: leading blank-line indentation rule and tabs in blank lines."""

    def test_over_indented_leading_blank_line_refused(self):
        with self.assertRaises(YamlError) as cm:
            parse("k: |\n     \n  a\n")
        self.assertEqual(cm.exception.line, 2)

    def test_leading_blank_line_within_indent_is_empty(self):
        self.assertEqual(parse("k: |\n  \n\n  a\n"), {"k": "\n\na\n"})

    def test_tab_in_blank_line_refused_not_dropped(self):
        for text, line in [("k: |\n  a\n \t\n  b\n", 3), ("k: |\n  a\n  \t\n  b\n", 3),
                           ("k: |\n\t\n  a\n", 2), ("k: |\n  a\n\t\n", 3)]:
            with self.assertRaises(YamlError, msg=repr(text)) as cm:
                parse(text)
            self.assertEqual(cm.exception.line, line, repr(text))

    def test_deeper_blank_line_after_content_is_preserved(self):
        self.assertEqual(parse("k: |\n  a\n    \n  b\n"), {"k": "a\n  \nb\n"})


class TestEmitMatchesParser(unittest.TestCase):
    """F4, F5, F6 and R8."""

    @staticmethod
    def _nest(n, leaf, kind):
        v = leaf
        for i in range(n):
            v = [v] if kind == "list" or (kind == "mixed" and i % 2 == 0) else {"k": v}
        return v

    def test_depth_boundary_matches_parser(self):
        for kind in ("list", "dict", "mixed"):
            for leaf in ("x", [], None, "a\nb\n"):
                depth_leaf = 1 if leaf == [] else 0
                ok = self._nest(50 - depth_leaf, leaf, kind)
                self.assertEqual(parse(emit(ok)), ok, (kind, leaf))
                with self.assertRaises(EmitError, msg=(kind, leaf)):
                    emit(self._nest(51 - depth_leaf, leaf, kind))

    def test_parser_refuses_exactly_what_emit_refuses_at_the_boundary(self):
        too_deep = "- " * 50 + "[]\n"
        with self.assertRaises(YamlError):
            parse(too_deep)
        self.assertEqual(parse("- " * 49 + "[]\n"), self._nest(49, [], "list"))

    def test_emit_refuses_subclasses(self):
        class Color(enum.IntEnum):
            R = 1

        class MyInt(int):
            pass

        class MyStr(str):
            pass

        class MyBool(int):
            pass

        class MyDict(dict):
            pass

        class MyList(list):
            pass

        for bad in [Color.R, MyInt(3), MyStr("x"), MyBool(1), MyDict(a=1), MyList([1]),
                    {"a": Color.R}, [MyStr("x")], {MyStr("k"): 1}]:
            with self.assertRaises(EmitError, msg=repr(bad)):
                emit(bad)

    def test_plain_when_it_reparses(self):
        for s in ["?x", ":x", "a\tb", "-x", "<<x", "a:b", "a#b", "x ]", "}x"[1:], "it's", "\u2028x", "\xa0x"]:
            self.assertEqual(emit({"k": s}), f"k: {s}\n", repr(s))
            self.assertEqual(emit([s]), f"- {s}\n", repr(s))
            self.assertEqual(emit(s), f"{s}\n", repr(s))
        for s in ["?x", ":x", "a:b", "a#b"]:
            self.assertEqual(emit({s: 1}), f"{s}: 1\n", repr(s))

    def test_quoted_when_it_would_not_reparse(self):
        for s in ["", "?", "? x", "- x", "-", "-\tx", "&a", "*a", "!a", "|", ">", "{a}", "[a]", "%", "@", "`", ",x",
                  "]", "}", "'q'", '"q"', "#c", "a #b", "a: b", "a:", " a", "a ", "\ta", "a\t", "true", "false", "null",
                  "~", "0", "-12", "\x01", "\r", "\x7f"]:
            self.assertEqual(emit({"k": s})[:4], 'k: "', repr(s))
        for s in ["<<", "", "a: b", "- x"]:
            self.assertEqual(emit({s: 1})[0], '"', repr(s))

    def test_quoting_matches_parser_exhaustively_on_short_strings(self):
        alphabet = ["a", " ", "\t", ":", "-", "?", "#", "[", "'", "~", "1"]
        import itertools
        for n in range(1, 4):
            for combo in itertools.product(alphabet, repeat=n):
                s = "".join(combo)
                for v in ({"k": s}, [s], s, {s: 1}):
                    self.assertEqual(parse(emit(v)), v, repr(v))
                for text, plain, want in [(emit({"k": s}), "k: " + s + "\n", {"k": s}),
                                          (emit([s]), "- " + s + "\n", [s]),
                                          (emit(s), s + "\n", s)]:
                    if text == plain:
                        continue
                    try:  # quoted or block: the plain form must not have worked
                        plain_ok = parse(plain) == want
                    except YamlError:
                        plain_ok = False
                    self.assertFalse(plain_ok and "\n" not in s, (repr(s), text))

    def test_document_markers_quoted_only_where_they_would_not_reparse(self):
        for m in ["---", "...", "--- a", "... a"]:
            self.assertEqual(emit({"k": m}), f"k: {m}\n", m)
            self.assertEqual(emit([m]), f"- {m}\n", m)
            self.assertEqual(emit(m), _dq_text(m), m)
            want_key = f"{m}: 1\n" if " " not in m else f'"{m}": 1\n'
            self.assertEqual(emit({m: 1}), want_key, m)

    def test_written_file_loads_back_identical(self):
        """N1: every transformation load() applies (BOM strip, CRLF) is covered by the quoting decision."""
        values = ["\ufeffx", "\ufeff", "x\ufeff", "a\ufeffb", "\r", "a\rb", "a\r\nb", "\r\n", "x\r\ny\r\n",
                  {"\ufeffa": 1}, {"a": "\ufeffx"}, ["\ufeffx"], {"a": {"\ufeffb": "\ufeff"}},
                  {"k": "a\r\nb"}, ["\r\nz\n"], {"\r": 1}]
        for v in values:
            data = emit(v).encode("utf-8")
            self.assertEqual(_load_bytes(data), v, repr(v))

    def test_leading_bom_is_quoted_top_level_key_and_first_value(self):
        self.assertEqual(emit("\ufeffx"), '"\\ufeffx"\n')
        self.assertEqual(emit({"\ufeffa": 1}), '"\\ufeffa": 1\n')
        self.assertEqual(emit({"a": "\ufeffx"}), "a: \ufeffx\n")
        self.assertEqual(emit("a\ufeffx"), "a\ufeffx\n")

    def test_key_quoting_uses_the_keys_real_context(self):
        """N3: BOM matters only at byte 0, '--- ' only at column 0."""
        bom, d1, d2 = "\ufeffb", "--- a", "... a"
        # BOM: quoted only as the very first key of the file
        self.assertEqual(emit({"x": 1, bom: 2}), f"x: 1\n{bom}: 2\n")
        self.assertEqual(emit({bom: 1, "x": 2}), f'"\\ufeffb": 1\nx: 2\n')
        self.assertEqual(emit({"p": {bom: 1}}), f"p:\n  {bom}: 1\n")
        self.assertEqual(emit([{bom: 1}]), f"- {bom}: 1\n")
        # marker-looking keys: quoted only at column 0
        for m in (d1, d2):
            self.assertEqual(emit({m: 1}), f'"{m}": 1\n')
            self.assertEqual(emit({"x": 1, m: 2}), f'x: 1\n"{m}": 2\n')
            self.assertEqual(emit({"p": {m: 1}}), f"p:\n  {m}: 1\n")
            self.assertEqual(emit([{"x": 1, m: 2}]), f"- x: 1\n  {m}: 2\n")
            self.assertEqual(emit([{m: 1}]), f"- {m}: 1\n")
        # key "k" at column 0 after another key (probe must not collide with the key itself)
        self.assertEqual(emit({"j": 1, "k": 2}), "j: 1\nk: 2\n")

    def test_key_contexts_load_back_identical(self):
        keys = ["\ufeffb", "--- a", "... a", "---", "...", "k", "j", "a: b", "- x"]
        for k in keys:
            for v in [{k: 1}, {"x": 1, k: 2}, {k: 1, "x": 2}, {"p": {k: 1}}, {"p": {"x": 1, k: 2}},
                      [{k: 1}], [{"x": 1, k: 2}], [{"p": [{k: 1}]}], {"k": 1, k: 2}, {"j": 1, k: 2}]:
                self.assertEqual(_load_bytes(emit(v).encode("utf-8")), v, repr(v))

    def test_fuzz_emit_file_load(self):
        rnd = random.Random(7)
        atoms = ["a", "k", "j", "x", "\ufeff", "\ufeffb", "---", "...", "--- a", "... a", "a: b", "- x", "#", "\t",
                 " ", "", "1", "true", "\r", "\r\n", "\n", "'", '"', "\xa0", "?", ":"]

        def atom():
            return "".join(rnd.choice(atoms) for _ in range(rnd.randint(0, 3)))

        def gen(depth):
            r = rnd.random()
            if depth > 3 or r < 0.3:
                return rnd.choice([None, True, 0, 5, atom(), atom()])
            if r < 0.65:
                return {atom(): gen(depth + 1) for _ in range(rnd.randint(1, 3))}
            return [gen(depth + 1) for _ in range(rnd.randint(0, 3))]

        for _ in range(3000):
            v = gen(0)
            try:
                text = emit(v)
            except EmitError:
                continue
            self.assertEqual(_load_bytes(text.encode("utf-8")), v, repr(v))
            self.assertEqual(emit(parse(text)), text, repr(v))

    def test_load_missing_and_directory(self):
        with tempfile.TemporaryDirectory() as d:
            for path in (os.path.join(d, "missing.yml"), d):
                with self.assertRaises(YamlError, msg=path) as cm:
                    load(path, "state/m.yml")
                self.assertIn("state/m.yml", str(cm.exception))
                self.assertEqual(cm.exception.line, 0)

    def _assert_load_refused(self, path):
        with self.assertRaises(YamlError, msg=repr(path)) as cm:
            load(path, "state/m.yml")
        self.assertIn("state/m.yml", str(cm.exception))
        self.assertEqual(cm.exception.line, 0)

    def test_load_bad_path_values_fail_closed(self):
        # R8-b: every problem obtaining the bytes is a YamlError naming shown.
        with tempfile.TemporaryDirectory() as d:
            good = os.path.join(d, "a.yml")
            with open(good, "wb") as fh:
                fh.write(b"a: 1\n")
            bad = [
                "a\0b", b"a\0b",          # embedded NUL (ValueError)
                "\ud800",                  # unencodable str (UnicodeEncodeError)
                None, 1.5, ["a"], object(),  # not str/bytes/PathLike (TypeError)
                "x" * 5000,                 # ENAMETOOLONG
                os.path.join(d, "n" * 300),  # ENAMETOOLONG on one component
                os.path.join(good, "x"),    # ENOTDIR
                _FsPath(3), _FsPath(None),  # PathLike yielding a non-path (TypeError)
                _FsPath("a\0b"),            # PathLike yielding NUL (ValueError)
            ]
            loop = os.path.join(d, "loop.yml")
            os.symlink(loop, loop)
            bad.append(loop)                # ELOOP
            for path in bad:
                self._assert_load_refused(path)
            # An int is not a path: open() would read it as a file descriptor.
            r, w = os.pipe()
            try:
                os.write(w, b"a: 1\n")
                os.close(w)
                self._assert_load_refused(r)
                os.fstat(r)  # still open: load did not adopt and close it
            finally:
                os.close(r)
            # Valid path types still load.
            import pathlib
            for path in (good, good.encode(), pathlib.Path(good)):
                self.assertEqual(load(path, "state/m.yml"), {"a": 1})

    def test_load_permission_denied(self):
        if os.geteuid() == 0:
            self.skipTest("root bypasses file permissions")
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "a.yml")
            with open(p, "wb") as fh:
                fh.write(b"a: 1\n")
            os.chmod(p, 0)
            try:
                self._assert_load_refused(p)
            finally:
                os.chmod(p, 0o600)

    def test_load_fifo_refused_without_blocking(self):
        # Run in a subprocess so a regression that opens the FIFO cannot hang.
        import subprocess
        import sys
        with tempfile.TemporaryDirectory() as d:
            fifo = os.path.join(d, "f.yml")
            os.mkfifo(fifo)
            link = os.path.join(d, "link.yml")
            os.symlink(fifo, link)
            code = (
                "import sys\n"
                "from gates.lib.yamlsub import YamlError, load\n"
                "try:\n"
                "    load(sys.argv[1], 'state/m.yml')\n"
                "except YamlError as e:\n"
                "    print(e.line, e.reason)\n"
            )
            root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            for path in (fifo, link):
                try:
                    r = subprocess.run(
                        [sys.executable, "-c", code, path], cwd=root,
                        capture_output=True, text=True, timeout=10,
                    )
                except subprocess.TimeoutExpired:
                    self.fail(f"load() blocked on a FIFO: {path}")
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertTrue(r.stdout.startswith("0 state/m.yml: "), r.stdout)

    def test_load_never_opens_a_non_regular_file(self):
        # Both openers are spies that raise, so a regression fails, never hangs.
        import builtins
        from unittest import mock
        with tempfile.TemporaryDirectory() as d:
            fifo = os.path.join(d, "f.yml")
            os.mkfifo(fifo)
            for path in (fifo, d, os.devnull):
                with mock.patch.object(os, "open", side_effect=AssertionError("opened")) as spy, \
                        mock.patch.object(builtins, "open", side_effect=AssertionError("opened")) as bspy:
                    self._assert_load_refused(path)
                spy.assert_not_called()
                bspy.assert_not_called()

    def test_load_path_swapped_to_fifo_after_stat_does_not_block(self):
        # A PathLike naming a regular file at stat time and a FIFO at open time.
        import subprocess
        import sys
        with tempfile.TemporaryDirectory() as d:
            good = os.path.join(d, "a.yml")
            with open(good, "wb") as fh:
                fh.write(b"a: 1\n")
            fifo = os.path.join(d, "f.yml")
            os.mkfifo(fifo)
            code = (
                "import sys\n"
                "from gates.lib.yamlsub import YamlError, load\n"
                "class Swap:\n"
                "    def __init__(self):\n"
                "        self.names = [sys.argv[1], sys.argv[2]]\n"
                "    def __fspath__(self):\n"
                "        return self.names.pop(0) if len(self.names) > 1 else self.names[0]\n"
                "try:\n"
                "    print('RETURNED', load(Swap(), 'state/m.yml'))\n"
                "except YamlError as e:\n"
                "    print(e.line, e.reason)\n"
            )
            root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            try:
                r = subprocess.run(
                    [sys.executable, "-c", code, good, fifo], cwd=root,
                    capture_output=True, text=True, timeout=10,
                )
            except subprocess.TimeoutExpired:
                self.fail("load() blocked on a FIFO swapped in after stat")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(r.stdout, "0 state/m.yml: cannot read file (not a regular file)\n")


if __name__ == "__main__":
    unittest.main()
