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
        if isinstance(self.value, BaseException):
            raise self.value
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

    def test_tab_after_separator_whatever_follows(self):
        """U1 (owner): a tab right after ':' or '-', or in the whitespace after them, is refused with the
        line whatever follows: a value, a comment or the end of the line."""
        for tail in ["\t", " \t", "  \t", "\t ", " \t ", " \t# c", "  \t # c", "\t# c", " \t#\tc"]:
            self._refuse("x: 1\nk:" + tail + "\n", 2)
            self._refuse("x: 1\n\"k\":" + tail + "\n", 2)
            self._refuse("x: 1\nk:" + tail + "\n  j: 1\n", 2)
            self._refuse("- x\n-" + tail + "\n", 2)
            self._refuse("- x\n- k:" + tail + "\n", 2)
            self._refuse("- x\n- -" + tail + "\n", 2)
            self._refuse("k:\n  - x\n  -" + tail + "\n", 3)
        # a tab after the value, or inside a comment, is not after the separator
        self.assertEqual(parse("k: v\t\n"), {"k": "v"})
        self.assertEqual(parse("k: # c\t\n"), {"k": None})
        self.assertEqual(parse("- v \t\n"), ["v"])
        self.assertEqual(parse("- # c\t\n"), [None])
        self.assertEqual(parse("k: |\t\n  x\n"), {"k": "x\n"})

    def test_tab_in_leading_whitespace_of_a_value(self):
        """D5: a tab anywhere in the whitespace between ': ' or '- ' and the value is refused."""
        for value in ["v", "'v'", '"v"', "[v]", "|\n  v", "1"]:
            for lead in [" \t", "  \t", " \t ", " \t\t"]:
                self._refuse("x: 1\nk:" + lead + value + "\n", 2)
                self._refuse("- x\n-" + lead + value + "\n", 2)
                self._refuse("- x\n- k:" + lead + value + "\n", 2)
                self._refuse("x: 1\n\"k\":" + lead + value + "\n", 2)
                self._refuse("x:\n  - - y\n  - -" + lead + value + "\n", 3)

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
                _FsPath(RuntimeError("boom")),  # __fspath__ raising RuntimeError
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

    def test_load_fspath_keyboardinterrupt_and_systemexit_escape(self):
        for exc in (KeyboardInterrupt, SystemExit):
            with self.assertRaises(exc):
                load(_FsPath(exc()), "state/m.yml")

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
        # The regular file is replaced by a FIFO between load's stat and open.
        import subprocess
        import sys
        with tempfile.TemporaryDirectory() as d:
            good = os.path.join(d, "a.yml")
            with open(good, "wb") as fh:
                fh.write(b"a: 1\n")
            fifo = os.path.join(d, "f.yml")
            os.mkfifo(fifo)
            code = (
                "import os, sys\n"
                "from gates.lib.yamlsub import YamlError, load\n"
                "real_stat = os.stat\n"
                "def stat_then_swap(p, *a, **k):\n"
                "    st = real_stat(p, *a, **k)\n"
                "    if p == sys.argv[1]:\n"
                "        os.replace(sys.argv[2], sys.argv[1])\n"
                "    return st\n"
                "os.stat = stat_then_swap\n"
                "try:\n"
                "    print('RETURNED', load(sys.argv[1], 'state/m.yml'))\n"
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

P2_CHARS = [" ", "\t", "\xa0", "\u3000", "\u2028", "\u2029", "\x85", "\u200b", "\ufeff"]
P2_UNICODE = P2_CHARS[2:]  # not YAML whitespace: content in every position
P3_CHARS = [chr(c) for c in range(0x20) if c not in (0x09, 0x0A)] + ["\x7f", "\ud800", "\udfff"]


def _refused(test, text, line, fragment=None):
    with test.assertRaises(YamlError, msg=repr(text)) as cm:
        parse(text)
    test.assertEqual(cm.exception.line, line, repr(text) + " " + str(cm.exception))
    if fragment is not None:
        test.assertIn(fragment, cm.exception.reason, repr(text))


class TestDomain(unittest.TestCase):
    """One test per row of task-1a.1-domain.md (P1-P12, E1-E6); L rows are in TestLoadDomain."""

    def test_p1_argument_type(self):
        class S(str):
            pass

        self.assertEqual(parse(S("a: [x]\nb: c\n")), {"a": ["x"], "b": "c"})
        v = parse(S("k: v\n"))
        self.assertIs(type(next(iter(v))), str)
        self.assertIs(type(v["k"]), str)
        # owner ruling D1: any non-str argument raises TypeError, never YamlError
        for bad in (b"a: 1\n", bytearray(b"a: 1\n"), None, 5, 1.5, ["a: 1"]):
            with self.assertRaises(TypeError, msg=repr(bad)) as cm:
                parse(bad)
            self.assertNotIsInstance(cm.exception, YamlError, repr(bad))

    def test_p2_characters_in_values_are_content(self):
        for c in P2_CHARS:
            for text, want in [(f"k: a{c}b\n", {"k": f"a{c}b"}), (f"- a{c}b\n", [f"a{c}b"]), (f"a{c}b\n", f"a{c}b"),
                               (f"k: 'a{c}b'\n", {"k": f"a{c}b"}), (f'k: "a{c}b"\n', {"k": f"a{c}b"}),
                               (f"k: '{c}'\n", {"k": c}), (f'k: "{c}"\n', {"k": c})]:
                self.assertEqual(parse(text), want, repr(text))
        for c in P2_UNICODE:  # also leading and trailing: not stripped as whitespace
            for text, want in [(f"k: {c}x\n", {"k": c + "x"}), (f"k: x{c}\n", {"k": "x" + c}),
                               (f"k: {c}\n", {"k": c}), (f"k: x{c} # n\n", {"k": "x" + c})]:
                self.assertEqual(parse(text), want, repr(text))
        # spaces around a plain scalar and a tab after it are separators, not content
        self.assertEqual(parse("k:   x \t\n"), {"k": "x"})
        # a tab in the whitespace before a value is refused with the line (D5)
        _refused(self, "x: 1\nk:  \t x \t\n", 2, "tab")

    def test_p3_refused_characters_with_line(self):
        for c in P3_CHARS:
            for text, line in [(f"k: a{c}b\n", 1), (f"x: 1\nk{c}: 1\n", 2), (f"x: 1\ny: 2\nk: [a{c}]\n", 3),
                               (f"k: |\n  a\n  b{c}\n", 3), (f"k: 1 # c{c}\n", 1), (f"k: '{c}'\n", 1),
                               (f'k: "{c}"\n', 1), (f"# {c}\n", 1)]:
                _refused(self, text, line, "control character")
        # a bare CR is refused through load too (only CRLF is normalised)
        with self.assertRaises(YamlError) as cm:
            _load_bytes(b"a: 1\nb: x\ry\n", "s.yml")
        self.assertEqual((cm.exception.line, cm.exception.reason), (2, "s.yml: control character not allowed"))

    def test_p4_characters_in_keys_flow_block_and_comments(self):
        for c in P2_UNICODE + [" "]:
            self.assertEqual(parse(f"a{c}b: 1\n"), {f"a{c}b": 1}, repr(c))
            self.assertEqual(parse(f"'{c}': 1\n"), {c: 1}, repr(c))
            self.assertEqual(parse(f"k: [a{c}b, '{c}']\n"), {"k": [f"a{c}b", c]}, repr(c))
            self.assertEqual(parse(f"k: |\n  a{c}b\n  x{c}\n"), {"k": f"a{c}b\nx{c}\n"}, repr(c))
            self.assertEqual(parse(f"k: 1 # a{c}b\n# {c}\n"), {"k": 1}, repr(c))
        for c in P2_UNICODE:
            self.assertEqual(parse(f"{c}a: 1\n"), {c + "a": 1}, repr(c))
            self.assertEqual(parse(f"k: [{c}x, x{c}]\n"), {"k": [c + "x", "x" + c]}, repr(c))
            self.assertEqual(parse(f"k: |\n  {c}x\n"), {"k": c + "x\n"}, repr(c))
        # tab: content inside keys, flow items, block-scalar lines and comments
        self.assertEqual(parse("a\tb: 1\n"), {"a\tb": 1})
        self.assertEqual(parse("k: [a\tb]\n"), {"k": ["a\tb"]})
        self.assertEqual(parse("k: |\n  a\tb\n"), {"k": "a\tb\n"})
        self.assertEqual(parse("k: 1 # a\tb\n"), {"k": 1})

    def test_p5_character_after_each_indicator(self):
        ok = [
            # ':' then space / end of line: separator; NBSP or another indicator: content
            ("k: v\n", {"k": "v"}), ("k:\n", {"k": None}), ("k: a:\xa0b\n", {"k": "a:\xa0b"}),
            ("k:\xa0v\n", "k:\xa0v"), ("k: a::b\n", {"k": "a::b"}), ("k: a:-b\n", {"k": "a:-b"}),
            ("k: a:#b\n", {"k": "a:#b"}), ("k: a:,b\n", {"k": "a:,b"}), ("k: a:[b\n", {"k": "a:[b"}),
            # '-' then space / end of line: item; NBSP or another indicator: content
            ("- v\n", ["v"]), ("-\n", [None]), ("-\xa0v\n", "-\xa0v"), ("--v\n", "--v"), ("k: -#\n", {"k": "-#"}),
            ("k: -,\n", {"k": "-,"}), ("k: -|\n", {"k": "-|"}), ("- - v\n", [["v"]]),
            # ',' in a flow sequence
            ("k: [a, b]\n", {"k": ["a", "b"]}), ("k: [a,b]\n", {"k": ["a", "b"]}), ("k: [a,\xa0b]\n", {"k": ["a", "\xa0b"]}),
            ("k: [a,-b]\n", {"k": ["a", "-b"]}), ("k: [a,:b]\n", {"k": ["a", ":b"]}), ("k: [a,'b']\n", {"k": ["a", "b"]}),
            # '#': a comment only after whitespace; anything may follow it
            ("k: v # c\n", {"k": "v"}), ("k: v #\n", {"k": "v"}), ("k: v #\tc\n", {"k": "v"}),
            ("k: v #\xa0c\n", {"k": "v"}), ("k: v ##\n", {"k": "v"}), ("k: v#c\n", {"k": "v#c"}),
            # '|' and '|-' then space or end of line
            ("k: |\n  x\n", {"k": "x\n"}), ("k: | \n  x\n", {"k": "x\n"}), ("k: |- \n  x\n", {"k": "x"}),
            ("k: | # c\n  x\n", {"k": "x\n"}),
            # owner ruling D2: a tab after '#', '|' or '|-' is accepted
            ("k: v #\t\n", {"k": "v"}), ("- v #\tc\n", ["v"]), ("k: 'v' #\tc\n", {"k": "v"}), ("k: [v] #\tc\n", {"k": ["v"]}),
            ("k: |\t\n  x\n", {"k": "x\n"}), ("k: |-\t\n  x\n", {"k": "x"}), ("k: |\t# c\n  x\n", {"k": "x\n"}),
            ("k: |-\t#\tc\n  x\n", {"k": "x"}), ("- |\t\n  x\n", ["x\n"]), ("|-\t\n x\n", "x"),
        ]
        for text, want in ok:
            self.assertEqual(parse(text), want, repr(text))
        refused = [
            ("k:\tv\n", "tab"), ("-\tv\n", "tab"), ("k: [a,\tb]\n", "tab"), ("k: [a\t, b]\n", "tab"),
            ("k: [a,,b]\n", "empty scalar"), ("k: [a,]\n", "trailing comma"), ("k: [a,\n", "unterminated"),
            ("k: |\xa0\n  x\n", "block scalar header"), ("k: |-\xa0\n  x\n", "block scalar header"),
            ("k: |#\n  x\n", "block scalar header"), ("k: ||\n  x\n", "block scalar header"),
            ("k: |--\n  x\n", "block scalar header"), ("k: -:\n", "':' followed by whitespace"),
            # ' #' starts a comment outside quotes, in a flow sequence too
            ("k: [a, #b]\n", "comment"), ("k: [ #b]\n", "comment"), ("k: [a #b]\n", "comment"),
            ("k: [a,\t#b]\n", "tab"),
            # owner ruling D5: a tab anywhere in the whitespace between ': ' or '- ' and the value
            ("k: \tv\n", "tab"), ("k:  \tv\n", "tab"), ("k: \t v\n", "tab"),
            ("k: \t|\n  x\n", "tab"), ("k: \t[v]\n", "tab"), ("k: \t'v'\n", "tab"),
            # owner ruling U1: whatever follows, a comment or the end of the line included
            ("k:\t\n", "tab"), ("k: \t\n", "tab"), ("k: \t# c\n", "tab"),
        ]
        for text, fragment in refused:
            _refused(self, "x: 1\n" + text, 2, fragment)
        for text in ["- \tv\n", "-  \tv\n", "- \t v\n", "- k: \tv\n", "- \t|\n  x\n", "- \t[v]\n",
                     "-\t\n", "- \t\n", "- \t# c\n", "- k:\t\n"]:
            _refused(self, "- y\n" + text, 2, "tab")

    def test_comment_start_in_every_position(self):
        """Q-yamlsub-1 (owner): ' #' starts a comment outside quoted scalars and block-scalar bodies."""
        for text, want in [
            ("k: v #c\n", {"k": "v"}), ("k: v\t#c\n", {"k": "v"}), ("k: #c\n", {"k": None}), ("k: a #b: c\n", {"k": "a"}),
            ("- v #c\n", ["v"]), ("- #c\n", [None]), ("- k: v #c\n", [{"k": "v"}]), ("- - v #c\n", [["v"]]),
            ("k: 'v' #c\n", {"k": "v"}), ('"k": "v" #c\n', {"k": "v"}), ("k: [a, b] #c\n", {"k": ["a", "b"]}),
            ("k: | #c\n  x\n", {"k": "x\n"}), ("k: |- #c\n  x\n", {"k": "x"}), ("v #c\n", "v"), ("a #b: c\n", "a"),
            ("'a' #b: c\n", "a"), ("k:\n  #c\n  j: 1 #c\n", {"k": {"j": 1}}), ("k: #c\n  - x\n", {"k": ["x"]}),
            ("- #c\n  - x\n", [["x"]]), ("k: |\n  x\n #c\nj: 1\n", {"k": "x\n", "j": 1}),
        ]:
            self.assertEqual(parse(text), want, repr(text))
        # in a flow sequence: a comment, which a flow line cannot hold, so refused with the line
        for text in ["k: [a, #b]\n", "k: [ #b]\n", "k: [a #b]\n", "k: [a #b, c]\n", "k: ['a' #b]\n", "k: [a, b #c]\n"]:
            _refused(self, "x: 1\n" + text, 2)
        # inside quoted scalars and block-scalar bodies ' #' is content
        for text, want in [
            ("k: 'a #b'\n", {"k": "a #b"}), ('k: "a #b"\n', {"k": "a #b"}), ("k: ['a #b', \"c #d\"]\n", {"k": ["a #b", "c #d"]}),
            ("'a #b': c\n", {"a #b": "c"}), ("k: |\n  a #b\n  #c\n", {"k": "a #b\n#c\n"}), ("k: |-\n  a #b\n", {"k": "a #b"}),
            ("- |\n  x #y\n   #z\n", ["x #y\n #z\n"]), ("k: |\n  a\t#b\n", {"k": "a\t#b\n"}),
        ]:
            self.assertEqual(parse(text), want, repr(text))
        # emit relies on the body case: such a string is written as a block scalar and loads back identical
        self.assertEqual(emit({"k": "a #b\nc\n"}), "k: |\n  a #b\n  c\n")
        self.assertEqual(_load_bytes(emit({"k": "a #b\nc\n"}).encode("utf-8")), {"k": "a #b\nc\n"})

    def test_p6_plain_scalar_first_character(self):
        bad = {"&": "anchor", "*": "alias", "!": "tag", "{": "flow mapping", ">": "folded"}
        bad.update({c: f"may not start with {c!r}" for c in "%@`,]}"})
        for c, fragment in bad.items():
            for text in [f"k: {c}x\n", f"- {c}x\n", f"{c}x\n", f"{c}x: 1\n", f"k: {c}\n"]:
                _refused(self, "x: 1\n" + text if not text.startswith("- ") else "- y\n" + text, 2, fragment)
            if c not in ",]":
                _refused(self, f"k: [y, {c}x]\n", 1, fragment)
        for c in "-?":  # followed by space or end of line: refused; by anything else: plain
            for text in [f"k: {c}\n", f"k: {c} x\n"]:
                _refused(self, text, 1, "may not start with")
        _refused(self, "k: :\n", 1, "':' followed by whitespace")
        _refused(self, "k: : x\n", 1, "':' followed by whitespace")
        for c in "-?:":
            for text, want in [(f"k: {c}x\n", {"k": c + "x"}), (f"- {c}x\n", [c + "x"]), (f"{c}x\n", c + "x"),
                               (f"{c}x: 1\n", {c + "x": 1}), (f"k: [{c}x]\n", {"k": [c + "x"]})]:
                self.assertEqual(parse(text), want, repr(text))
        # '#' and '|' starting a flow item are refused with the line, like the other indicators (D4)
        for text in ["k: [#x]\n", "k: [a,#x]\n", "k: [|y]\n", "k: [ |y]\n", "k: [a, |y]\n", "k: [a,|]\n",
                     "k: [#]\n", "k: [|]\n", "k: [#\"q\"]\n", "- [#x]\n", "[|y]\n"]:
            _refused(self, "x: 1\n" + text if not text.startswith(("-", "[")) else text, 2 if text.startswith("k") else 1,
                     "may not start with")
        # inside an item they stay content
        self.assertEqual(parse("k: [a#x, a|y, '#x', \"|y\"]\n"), {"k": ["a#x", "a|y", "#x", "|y"]})

    def test_p7_scalar_resolution(self):
        cases = {"true": True, "false": False, "null": None, "~": None, "0": 0, "-0": 0, "007": "007",
                 "1.0": "1.0", "yes": "yes", "2026-10-31": "2026-10-31", "0x1F": "0x1F", "True": "True",
                 "+1": "+1", "12": 12, "-12": -12}
        for s, want in cases.items():
            self.assertEqual(parse(f"k: {s}\n"), {"k": want}, s)
            self.assertIs(type(parse(f"k: {s}\n")["k"]), type(want), s)
            self.assertEqual(parse(f"k: [{s}]\n"), {"k": [want]}, s)
            self.assertEqual(parse(f"k: '{s}'\n"), {"k": s}, s)
        self.assertEqual(parse("k:\n"), {"k": None})
        self.assertEqual(parse("k: ''\n"), {"k": ""})
        self.assertEqual(parse("k: " + "9" * 1000 + "\n"), {"k": int("9" * 1000)})
        self.assertEqual(parse("k: -" + "9" * 999 + "\n"), {"k": -int("9" * 999)})
        _refused(self, "x: 1\nk: " + "9" * 1001 + "\n", 2, "integer too large")
        _refused(self, "k: [-" + "9" * 1000 + "]\n", 1, "integer too large")

    def test_p8_nesting_depth(self):
        def text(n, kind, leaf):
            # n containers; the innermost is a mapping {'k': leaf}; leaf '[]' adds one level
            lines = []
            for i in range(n - 1):
                if kind == "list" or (kind == "mixed" and i % 2 == 0):
                    lines.append(" " * (2 * i) + "-")
                else:
                    lines.append(" " * (2 * i) + "k:")
            lines.append(" " * (2 * (n - 1)) + "k: " + leaf)
            return "\n".join(lines) + "\n"

        for kind in ("list", "dict", "mixed"):
            for leaf, extra in (("x", 0), ("[]", 1)):
                for n in (49, 50, 51):
                    t = text(n - extra, kind, leaf)
                    if n <= 50:
                        self.assertIsNotNone(parse(t), (kind, leaf, n))
                    else:
                        _refused(self, t, n - extra, "nesting too deep")
        self.assertEqual(parse("- " * 49 + "[]\n"), TestEmitMatchesParser._nest(49, [], "list"))
        _refused(self, "- " * 50 + "[]\n", 1, "nesting too deep")
        _refused(self, "- " * 51 + "x\n", 1, "nesting too deep")
        self.assertEqual(parse("- " * 50 + "x\n"), TestEmitMatchesParser._nest(50, "x", "list"))

    def test_p9_indentation(self):
        self.assertEqual(parse("a:\n  b: 1\n  c:\n    - 2\n"), {"a": {"b": 1, "c": [2]}})
        self.assertEqual(parse("a:\n- 1\n- 2\nb: 3\n"), {"a": [1, 2], "b": 3})
        self.assertEqual(parse("- a:\n  - 1\n"), [{"a": [1]}])
        _refused(self, "a:\n    b: 1\n  c: 2\n", 3, "indentation")
        _refused(self, "a: 1\n  b: 2\n", 2, "indentation")
        _refused(self, "- a\n - b\n", 2, "indentation")
        _refused(self, "- k: 1\n   j: 2\n", 2, "indentation")
        _refused(self, "a:\n\t- 1\n", 2, "tab in indentation")
        _refused(self, "a:\n  b: 1\n \tc: 2\n", 3, "tab in indentation")
        _refused(self, "a:\n  x\n", 2, "expected a mapping or a sequence")

    def test_p10_block_scalars(self):
        self.assertEqual(parse("k: |\n  a\n  b\n"), {"k": "a\nb\n"})
        self.assertEqual(parse("k: |-\n  a\n  b\n"), {"k": "a\nb"})
        self.assertEqual(parse("k: |\n\n  \n  a\n"), {"k": "\n\na\n"})
        self.assertEqual(parse("k: |\n  a\n# c\nj: 1\n"), {"k": "a\n", "j": 1})
        self.assertEqual(parse("k: |\n  a\n  # c\n"), {"k": "a\n# c\n"})
        self.assertEqual(_load_bytes(b"k: |\r\n  a\r\n  b\r\nj: 1\r\n"), {"k": "a\nb\n", "j": 1})
        _refused(self, "x: 1\nk: |+\n  a\n", 2, "block scalar header")
        _refused(self, "x: 1\nk: >\n  a\n", 2, "folded")
        _refused(self, "x: 1\nk: >-\n  a\n", 2, "folded")
        _refused(self, "k: |\n    \n  a\n", 2, "blank line indented deeper")
        _refused(self, "k: |\n  a\n \t\n  b\n", 3, "tab in indentation")
        _refused(self, "k: |\n  a\r\n  b\n", 2, "control character")

    def test_p11_document_structure(self):
        self.assertIsNone(parse(""))
        self.assertIsNone(parse("\n\n"))
        self.assertIsNone(parse("# c\n  # d\n"))
        self.assertEqual(parse("hello\n"), "hello")
        self.assertEqual(parse("12\n"), 12)
        self.assertEqual(parse("'q'\n"), "q")
        self.assertEqual(parse("|\n  x\n"), "x\n")
        self.assertEqual(parse("[a]\n"), ["a"])
        for text, line in [("---\na: 1\n", 1), ("a: 1\n---\n", 2), ("a: 1\n...\n", 2), ("--- a\n", 1),
                           ("a: 1\n---\nb: 2\n", 2), ("a: 1\n...\n---\nb: 2\n", 2)]:
            _refused(self, text, line, "document markers")
        _refused(self, "a\nb\n", 2, "second node")
        _refused(self, "- a\nb: 1\n", 2)

    def test_p12_duplicates_and_keys(self):
        _refused(self, "a: 1\nb: 2\na: 3\n", 3, "duplicate key 'a'")
        _refused(self, "a: 1\n'a': 2\n", 2, "duplicate key 'a'")
        _refused(self, 'a: 1\n"a": 2\n', 2, "duplicate key 'a'")
        _refused(self, "a: 1\n<<: 2\n", 2, "merge keys")
        _refused(self, "a:\n  <<: 2\n", 2, "merge keys")
        self.assertEqual(parse("'<<': 1\n"), {"<<": 1})
        self.assertEqual(parse('"<<": 1\n'), {"<<": 1})
        for k in ("1", "-3", "true", "null", "~"):
            v = parse(f"{k}: x\n")
            self.assertEqual(v, {k: "x"}, k)
            self.assertIs(type(next(iter(v))), str)
        _refused(self, "1: a\n'1': b\n", 2, "duplicate key '1'")

    def test_e1_value_type(self):
        for v in ({"a": 1}, ["a"], "a", 1, True, False, None):
            self.assertEqual(parse(emit(v)), v, repr(v))

        class D(dict):
            pass

        class Color(enum.IntEnum):
            R = 1

        for bad in (D(a=1), Color.R, 1.5, (1,), b"x", {1: "a"}, {("k",): 1}, bytearray(b"x"), set(), object()):
            with self.assertRaises(EmitError, msg=repr(bad)):
                emit(bad)
            with self.assertRaises(EmitError, msg=repr(bad)):
                emit({"k": [bad]})

    def test_e2_output_position(self):
        # one value per position that needs quoting there and is plain elsewhere
        bom, mark = "\ufeffx", "--- a"
        self.assertEqual(emit(bom), '"\\ufeffx"\n')                       # top-level
        self.assertEqual(emit({bom: 1}), '"\\ufeffx": 1\n')                # first key of the file
        self.assertEqual(emit({"a": 1, bom: 2}), f"a: 1\n{bom}: 2\n")      # later column-0 key
        self.assertEqual(emit({"a": 1, mark: 2}), f'a: 1\n"{mark}": 2\n')  # later column-0 key
        self.assertEqual(emit({"p": {mark: 1}}), f"p:\n  {mark}: 1\n")     # nested key
        self.assertEqual(emit([{mark: 1}]), f"- {mark}: 1\n")              # '- k:' key
        self.assertEqual(emit({"k": bom}), f"k: {bom}\n")                  # value
        self.assertEqual(emit([mark]), f"- {mark}\n")                      # list item
        self.assertEqual(emit(mark), f'"{mark}"\n')                        # top-level marker
        self.assertEqual(emit({"k": [mark, "a b"]}), f"k:\n  - {mark}\n  - a b\n")  # items (no flow form emitted)
        for v in ({"k": "x: y"}, ["x: y"], {"x: y": 1}, "x: y"):
            self.assertIn('"x: y"', emit(v), repr(v))

    def test_e3_string_content_through_a_file(self):
        values = []
        for c in P2_CHARS:
            values += [c, "a" + c + "b", c + "x", "x" + c, c * 3]
        values += [c for c in P3_CHARS if not 0xD800 <= ord(c) <= 0xDFFF]
        values += ["a\nb", "a\n", "a\n\n", "a\n\n\n", "\n", "\n\n", " lead", "trail ", " both ", "", "\r\n", "x\r"]
        for s in values:
            for v in (s, {"k": s}, [s], {s: 1}, [{"k": s, s: 2}] if s != "k" else [s]):
                self.assertEqual(_load_bytes(emit(v).encode("utf-8")), v, repr(v))
        for s in ("\ud800", "a\udfffb"):
            for v in (s, {"k": s}, {s: 1}, [s]):
                with self.assertRaises(EmitError, msg=repr(v)):
                    emit(v)

    def test_e4_limits(self):
        for kind in ("list", "dict", "mixed"):
            for leaf, lv in (("x", 0), ([], 1)):
                ok = TestEmitMatchesParser._nest(50 - lv, leaf, kind)
                self.assertEqual(_load_bytes(emit(ok).encode()), ok, (kind, leaf))
                with self.assertRaises(EmitError, msg=(kind, leaf)):
                    emit(TestEmitMatchesParser._nest(51 - lv, leaf, kind))
        for n in (10 ** 999, -(10 ** 998)):  # 1000 characters
            self.assertEqual(len(str(n)), 1000)
            self.assertEqual(_load_bytes(emit({"k": n}).encode()), {"k": n})
        for n in (10 ** 1000, -(10 ** 999)):  # 1001 characters
            with self.assertRaises(EmitError):
                emit({"k": n})

    E5_CORPUS_SHA256 = "f3ae93fb4cb0dd8ad8591a0eb12e9f77e52e3faf5f9c96ce9ab1858dc20dc618"

    def _e5_corpus(self):
        return TestEmit.CORPUS + [10 ** 999, TestEmitMatchesParser._nest(50, "x", "mixed")] + [
            {"k" + c: c, "l": [c + "x", "x" + c]} for c in P2_CHARS + P3_CHARS[:5]]

    def test_e5_emit_is_byte_identical_across_interpreters(self):
        import hashlib
        h = hashlib.sha256()
        for v in self._e5_corpus():
            h.update(emit(v).encode("utf-8") + b"\0")
        # Pinned digest: the same on python3.9 and python3.13, so both suites pass only if emit agrees.
        self.assertEqual(h.hexdigest(), self.E5_CORPUS_SHA256)

    def test_e6_canonical(self):
        for v in self._e5_corpus():
            text = emit(v)
            self.assertEqual(emit(_load_bytes(text.encode("utf-8"))), text, repr(v))


def _open_fds():
    """The set of this process's open file descriptors, from /dev/fd (no upper bound)."""
    fds = {int(n) for n in os.listdir("/dev/fd")}
    return {fd for fd in fds if _fd_open(fd)}  # drops listdir's own, now closed, fd


def _fd_open(fd):
    try:
        os.fstat(fd)
    except OSError:
        return False
    return True


class TestLoadResources(unittest.TestCase):
    """L4 / N4: every refusal path in load releases every fd it opened."""

    def _swap_after_stat(self, target, swap, restore, calls=50):
        """Call load(target) `calls` times; os.stat swaps target right after load's stat."""
        from unittest import mock
        real_stat = os.stat

        def stat_then_swap(p, *a, **k):
            st = real_stat(p, *a, **k)
            if p == target:
                swap()
            return st

        before = _open_fds()
        reasons = set()
        for _ in range(calls):
            with mock.patch.object(os, "stat", stat_then_swap):
                with self.assertRaises(YamlError) as cm:
                    load(target, "state/m.yml")
            restore()
            self.assertEqual(cm.exception.line, 0)
            self.assertIn("state/m.yml", cm.exception.reason)
            reasons.add(cm.exception.reason)
        self.assertEqual(_open_fds() - before, set())
        return reasons

    def test_path_swapped_to_directory_after_stat_leaks_no_fd(self):
        with tempfile.TemporaryDirectory() as d:
            good = os.path.join(d, "a.yml")
            aside = os.path.join(d, "aside.yml")
            with open(good, "wb") as fh:
                fh.write(b"a: 1\n")

            def swap():
                os.rename(good, aside)
                os.mkdir(good)

            def restore():
                os.rmdir(good)
                os.rename(aside, good)

            reasons = self._swap_after_stat(good, swap, restore)
            self.assertEqual(reasons, {"state/m.yml: cannot read file (not a regular file)"})

    def test_file_larger_than_one_read_loads_whole(self):
        lines = [f"k{i}: {'v' * 90}" for i in range(3000)]  # about 290 KB
        data = ("\n".join(lines) + "\n").encode()
        self.assertGreater(len(data), 4 * (1 << 16))
        v = _load_bytes(data)
        self.assertEqual(len(v), 3000)
        self.assertEqual(v["k2999"], "v" * 90)

    def test_close_failure_is_a_yamlerror_and_the_fd_is_released(self):
        from unittest import mock
        with tempfile.TemporaryDirectory() as d:
            good = os.path.join(d, "a.yml")
            with open(good, "wb") as fh:
                fh.write(b"a: 1\n")
            real_close = os.close
            seen = []

            def close_then_fail(fd):
                seen.append(fd)
                real_close(fd)
                raise OSError(5, "Input/output error")

            before = _open_fds()
            with mock.patch.object(os, "close", close_then_fail):
                with self.assertRaises(YamlError) as cm:
                    load(good, "state/m.yml")
            self.assertEqual(cm.exception.line, 0)
            self.assertEqual(cm.exception.reason, "state/m.yml: cannot read file (Input/output error)")
            self.assertEqual(len(seen), 1)
            self.assertEqual(_open_fds() - before, set())

    def test_read_failure_releases_the_fd(self):
        from unittest import mock
        with tempfile.TemporaryDirectory() as d:
            good = os.path.join(d, "a.yml")
            with open(good, "wb") as fh:
                fh.write(b"a: 1\n")
            before = _open_fds()
            for exc in (OSError(5, "Input/output error"), KeyboardInterrupt()):
                with mock.patch.object(os, "read", side_effect=exc):
                    with self.assertRaises(type(exc)) if isinstance(exc, KeyboardInterrupt) \
                            else self.assertRaises(YamlError):
                        load(good, "state/m.yml")
            self.assertEqual(_open_fds() - before, set())


_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Child for the FIFO rows (L2, L3, L4): run in a subprocess so a regression that opens a FIFO
# cannot hang the suite. It prints one line per case: name, distinct reasons, fds leaked.
_FIFO_CHILD = r"""
import os, sys
sys.path.insert(0, sys.argv[1])
from gates.lib.yamlsub import YamlError, load
d = sys.argv[2]
good, fifo, link = (os.path.join(d, n) for n in ("a.yml", "f.yml", "link.yml"))
aside = os.path.join(d, "aside.yml")
def fds():
    return {fd for fd in map(int, os.listdir("/dev/fd")) if _open(fd)}
def _open(fd):
    try:
        os.fstat(fd)
        return True
    except OSError:
        return False
real_stat = os.stat
def race(p, *a, **k):
    st = real_stat(p, *a, **k)
    if p == good:
        os.rename(good, aside)
        os.rename(fifo, good)
    return st
def restore():
    os.rename(good, fifo)
    os.rename(aside, good)
for name, path, swap in (("fifo", fifo, False), ("symlink-to-fifo", link, False), ("race-to-fifo", good, True)):
    before, reasons = fds(), set()
    for _ in range(50):
        if swap:
            os.stat = race
        try:
            load(path, "state/m.yml")
            reasons.add("RETURNED")
        except YamlError as e:
            reasons.add("%d %s" % (e.line, e.reason))
        finally:
            os.stat = real_stat
        if swap:
            restore()
    print(name, sorted(reasons), len(fds() - before))
"""


class TestLoadDomain(unittest.TestCase):
    """Rows L1-L6 of task-1a.1-domain.md."""

    SHOWN = "state/m.yml"

    def _refused(self, path, calls=1):
        before = _open_fds()
        for _ in range(calls):
            with self.assertRaises(YamlError, msg=repr(path)) as cm:
                load(path, self.SHOWN)
            self.assertEqual(cm.exception.line, 0, repr(path))
            self.assertTrue(cm.exception.reason.startswith(self.SHOWN + ": "), cm.exception.reason)
        self.assertEqual(_open_fds() - before, set(), repr(path))  # L4
        return cm.exception.reason

    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.d = self._dir.name
        self.good = os.path.join(self.d, "a.yml")
        with open(self.good, "wb") as fh:
            fh.write(b"a: 1\n")

    def tearDown(self):
        self._dir.cleanup()

    def test_l1_path_types(self):
        import pathlib
        for path in (self.good, self.good.encode(), pathlib.Path(self.good), _FsPath(self.good),
                     _FsPath(self.good.encode())):
            self.assertEqual(load(path, self.SHOWN), {"a": 1}, repr(path))
        for path in (True, False, None, 1.5, ["a"], object(), _FsPath(3), _FsPath(None), _FsPath(1.5),
                     _FsPath(RuntimeError("boom")), _FsPath(ValueError("v")), _FsPath(OSError(2, "x"))):
            self.assertIn("invalid path", self._refused(path, 50), repr(path))
        r, w = os.pipe()  # an int is never read as a descriptor, nor closed
        try:
            os.write(w, b"a: 1\n")
            self.assertIn("invalid path: TypeError", self._refused(r, 50))
            os.fstat(r)
        finally:
            os.close(r)
            os.close(w)

    def test_l2_path_kinds(self):
        import socket
        sock_path = os.path.join(self.d, "s.sock")
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            s.bind(sock_path)
            loop = os.path.join(self.d, "loop.yml")
            os.symlink(loop, loop)
            cases = [
                (os.path.join(self.d, "missing.yml"), "No such file"), (self.d, "not a regular file"),
                (sock_path, "not a regular file"), (os.devnull, "not a regular file"),
                ("a\0b", "invalid path: ValueError"), (b"a\0b", "invalid path: ValueError"),
                ("\ud800x", "invalid path: UnicodeEncodeError"), ("x" * 5000, "too long"),
                (os.path.join(self.d, "n" * 300), "too long"), (os.path.join(self.good, "x"), "Not a directory"),
                (loop, "symbolic links"),
            ]
            for path, fragment in cases:
                self.assertIn(fragment, self._refused(path, 50), repr(path))
        finally:
            s.close()
        if os.geteuid() == 0:
            self.skipTest("root bypasses file permissions")
        os.chmod(self.good, 0)
        try:
            self.assertIn("Permission denied", self._refused(self.good, 50))
        finally:
            os.chmod(self.good, 0o600)
        sub = os.path.join(self.d, "sub")
        os.mkdir(sub)
        inner = os.path.join(sub, "b.yml")
        with open(inner, "wb") as fh:
            fh.write(b"a: 1\n")
        os.chmod(sub, 0)
        try:
            self.assertIn("Permission denied", self._refused(inner, 50))
        finally:
            os.chmod(sub, 0o700)

    def test_l2_l3_l4_fifo_cases_never_block_and_leak_nothing(self):
        import subprocess
        import sys
        fifo = os.path.join(self.d, "f.yml")
        os.mkfifo(fifo)
        os.symlink(fifo, os.path.join(self.d, "link.yml"))
        try:
            r = subprocess.run([sys.executable, "-c", _FIFO_CHILD, _ROOT, self.d],
                               capture_output=True, text=True, timeout=30)
        except subprocess.TimeoutExpired:
            self.fail("load() blocked on a FIFO")
        self.assertEqual(r.returncode, 0, r.stderr)
        want = "['0 state/m.yml: cannot read file (not a regular file)'] 0"
        self.assertEqual(r.stdout.splitlines(),
                         [f"fifo {want}", f"symlink-to-fifo {want}", f"race-to-fifo {want}"])

    def _race(self, swap, restore):
        from unittest import mock
        real_stat = os.stat

        def stat_then_swap(p, *a, **k):
            st = real_stat(p, *a, **k)
            if p == self.good:
                swap()
            return st

        before = _open_fds()
        reasons = set()
        for _ in range(50):
            with mock.patch.object(os, "stat", stat_then_swap):
                with self.assertRaises(YamlError) as cm:
                    load(self.good, self.SHOWN)
            restore()
            self.assertEqual(cm.exception.line, 0)
            reasons.add(cm.exception.reason)
        self.assertEqual(_open_fds() - before, set())
        return reasons

    def test_l3_race_between_stat_and_open(self):
        aside = os.path.join(self.d, "aside.yml")

        def to_dir():
            os.rename(self.good, aside)
            os.mkdir(self.good)

        def from_dir():
            os.rmdir(self.good)
            os.rename(aside, self.good)

        def to_devnull():
            os.rename(self.good, aside)
            os.symlink(os.devnull, self.good)

        def from_link():
            os.unlink(self.good)
            os.rename(aside, self.good)

        def removed():
            os.rename(self.good, aside)

        def back():
            os.rename(aside, self.good)

        nrf = {self.SHOWN + ": cannot read file (not a regular file)"}
        self.assertEqual(self._race(to_dir, from_dir), nrf)
        self.assertEqual(self._race(to_devnull, from_link), nrf)
        self.assertEqual(self._race(removed, back), {self.SHOWN + ": cannot read file (No such file or directory)"})

    def test_l4_decode_and_parse_errors_leak_nothing(self):
        for data, line, reason in ((b"a: \xff\n", 0, "not valid UTF-8"), (b"a: 1\na: 2\n", 2, "duplicate key 'a'")):
            with open(self.good, "wb") as fh:
                fh.write(data)
            before = _open_fds()
            for _ in range(50):
                with self.assertRaises(YamlError) as cm:
                    load(self.good, self.SHOWN)
                self.assertEqual((cm.exception.line, cm.exception.reason), (line, f"{self.SHOWN}: {reason}"))
            self.assertEqual(_open_fds() - before, set())

    def test_l5_encoding(self):
        def load_data(data):
            with open(self.good, "wb") as fh:
                fh.write(data)
            return load(self.good, self.SHOWN)

        self.assertEqual(load_data(b"\xef\xbb\xbfa: 1\n"), {"a": 1})
        self.assertEqual(load_data(b"\xef\xbb\xbf\xef\xbb\xbfa: 1\n"), {"﻿a": 1})  # only one is stripped
        self.assertEqual(load_data(b"a: 1\nb: \xef\xbb\xbfx\n"), {"a": 1, "b": "﻿x"})
        self.assertEqual(load_data(b"a: 1\r\nb: 2\r\n"), {"a": 1, "b": 2})
        self.assertEqual(load_data(b"\xef\xbb\xbf"), None)
        for data, line, reason in ((b"a: 1\nb: x\ry\n", 2, "control character not allowed"),
                                   (b"a: 1\r", 1, "control character not allowed"),
                                   (b"a: \xff\n", 0, "not valid UTF-8"), (b"\xff\xfea\x00", 0, "not valid UTF-8"),
                                   (b"\xfe\xff\x00a", 0, "not valid UTF-8"), (b"a: \xed\xa0\x80\n", 0, "not valid UTF-8")):
            with self.assertRaises(YamlError, msg=repr(data)) as cm:
                load_data(data)
            self.assertEqual((cm.exception.line, cm.exception.reason), (line, f"{self.SHOWN}: {reason}"), repr(data))

    def test_l6_interrupts_escape_unchanged(self):
        from unittest import mock
        for exc_type in (KeyboardInterrupt, SystemExit):
            exc = exc_type()
            with self.assertRaises(exc_type) as cm:
                load(_FsPath(exc), self.SHOWN)
            self.assertIs(cm.exception, exc)
            for target in ("stat", "open", "fstat", "read"):
                exc = exc_type()
                before = _open_fds()
                with mock.patch.object(os, target, side_effect=exc):
                    with self.assertRaises(exc_type, msg=target) as cm:
                        load(self.good, self.SHOWN)
                self.assertIs(cm.exception, exc, target)
                self.assertEqual(_open_fds() - before, set(), target)


class _DocGen:
    """Builds a document line by line together with the value it must parse to (T2 oracle).

    The rules here are the generator's own reading of the brief and the ruled grammar; they
    never call parse or emit. Alphabet (per value, owner ruling Q-yamlsub-2): every P2 character;
    each P5 indicator (':', '- ', ',', '#', '|', '|-') followed by space, tab, end of line, NBSP
    and another indicator; every P6 first character, '- ' and '? ' included; the P10 block forms
    with leading, whitespace-only, over-indented and tabbed blank lines; CRLF through load.
    """
    LETTERS = "abcxyz"
    UNI = ["\xa0", "　", " ", " ", "\x85", "​", "﻿"]  # P2 minus space and tab
    INNER = list("-?'\"&*!|>%@`.") + ["#"]  # never first; '#' only after a non-blank
    BAD_START = "&*!{>%@`,]}"

    def __init__(self, rnd):
        self.r = rnd
        self.lines = []  # [text, tags]; tags: dict with 'sep', 'item', 'bhead', 'val' column indexes

    # ---- scalars
    def plain(self, flow=False):
        r = self.r
        first = r.choice([r.choice(self.LETTERS), r.choice(self.UNI), r.choice("-?:") + r.choice(self.LETTERS),
                          r.choice("-?:") + r.choice(self.UNI)])  # P5/P6: '-', '?', ':' then NBSP etc.: plain
        out = [first]
        for _ in range(r.randint(0, 6)):
            k = r.random()
            if k < 0.3:
                out.append(r.choice(self.LETTERS + "019"))
            elif k < 0.5:
                out.append(r.choice(self.UNI))
            elif k < 0.65:
                out.append(r.choice([" ", "\t"] if not flow else [" ", "  ", "\t"]) + r.choice(self.LETTERS))
            elif k < 0.75:
                # P5: ':' then a non-blank (letter, NBSP and friends, another indicator) is content
                out.append(":" + r.choice([r.choice(self.LETTERS), r.choice(self.UNI),
                                           r.choice("-:#" if flow else "-:#,[") + r.choice(self.LETTERS)]))
            else:
                c = r.choice(self.INNER)
                out.append(c)
        return "".join(out)

    def any_str(self):
        r = self.r
        pool = list(self.LETTERS) + self.UNI + [" ", "\t", "\n", ":", "#", "-", "'", '"', "\\", ",", "[", "]",
                                                 "{", "|", ">", "\x01", "\x1f", "\x7f", "\r", "&", "?"]
        return "".join(r.choice(pool) for _ in range(r.randint(0, 6)))

    @staticmethod
    def dq(s, literal_tab):
        out = []
        for c in s:
            if c == "\\":
                out.append("\\\\")
            elif c == '"':
                out.append('\\"')
            elif c == "\n":
                out.append("\\n")
            elif c == "\t":
                out.append("\t" if literal_tab else "\\t")
            elif ord(c) < 0x20 or c == "\x7f":
                out.append("\\u%04X" % ord(c))
            else:
                out.append(c)
        return '"' + "".join(out) + '"'

    def scalar(self, flow=False):
        """(text, value) for a one-line scalar."""
        r = self.r
        k = r.random()
        if k < 0.08:
            return r.choice(["null", "~"]), None
        if k < 0.14:
            b = r.random() < 0.5
            return ("true" if b else "false"), b
        if k < 0.22:
            n = r.choice([0, 7, -3, 12345, -(10 ** 20)])
            return str(n), n
        if k < 0.6:
            s = self.plain(flow)
            return s, s
        s = self.any_str()
        if k < 0.8 and not any(c in s for c in "\n\r\x01\x1f\x7f"):
            return "'" + s.replace("'", "''") + "'", s
        return self.dq(s, r.random() < 0.5), s

    def comment(self, after_indicator=False):
        """'' or a trailing comment; right after ':' or '-' it must start with a space (F2)."""
        r = self.r
        if r.random() < 0.6:
            return ""
        body = "".join(r.choice(self.UNI + list(self.LETTERS) + [" ", "\t", "#", ":", "-", "|"]) for _ in range(4))
        # after '- ' a tab is refused (TestTabSeparators.test_tab_after_dash), so never ' \t' there
        return r.choice([" ", "  "] if after_indicator else [" ", "  ", "\t", " \t"]) + "#" + body

    # ---- nodes
    def add(self, text, **tags):
        self.lines.append([text, tags])

    def maybe_noise(self):
        r = self.r
        if r.random() < 0.15:
            # a blank line of at most one space: never deeper than a block scalar's content indent,
            # where it would be content (TestBlockScalarBlankLines)
            self.add(r.choice(["", " ", "# " + r.choice(self.UNI) + "\t#"]))

    def block_str(self):
        """(header, body lines, value) for a | or |- block scalar; '' marks a blank line.

        Leading blank lines are allowed (P10); the last line is content. A body line holding
        ' #' stays content (Q-yamlsub-1)."""
        r = self.r
        lines = [""] * (r.randint(1, 2) if r.random() < 0.25 else 0)
        n = r.randint(1, 4)
        for i in range(n):
            if 0 < i < n - 1 and r.random() < 0.2:
                lines.append("")
                continue
            first = r.choice(list(self.LETTERS) + self.UNI + ["#", "-", "'", "&", ":"])
            rest = "".join(r.choice(list(self.LETTERS) + self.UNI + [" ", "\t", "#", " #", ": ", "|"])
                           for _ in range(r.randint(0, 5)))
            lines.append(first + rest if i == 0 or r.random() < 0.7 else "  " + first + rest)
        if r.random() < 0.5:
            return "|", lines, "\n".join(lines) + "\n"
        return "|-", lines, "\n".join(lines)

    def block_body(self, body, ci):
        """Add the body lines at content indent ci; a blank line is '' or at most ci spaces."""
        for ln in body:
            self.add(" " * ci + ln if ln else " " * self.r.choice([0, 0, self.r.randint(0, ci)]))

    def value_after(self, prefix, indent, depth, tags):
        """Emit the line starting with prefix ('k:' or '-') and the value after it; return the value."""
        r = self.r
        k = r.random()
        if depth >= 4 or k < 0.45:
            text, v = self.scalar()
            sp = r.choice([" ", "  "])
            self.add(prefix + sp + text + self.comment(), val=len(prefix) + len(sp), ws=len(prefix), **tags)
            return v
        if k < 0.55:
            items = [self.scalar(flow=True) for _ in range(r.randint(0, 3))]
            sep = r.choice([", ", ",", " , "])
            text = "[" + sep.join(t for t, _ in items) + "]"
            base = len(prefix) + 1
            starts, ends, commas, at = [], [], [], base + 1  # columns of each item start and end, each ','
            for n, (t, _) in enumerate(items):
                starts.append(at)
                ends.append(at + len(t))
                if n + 1 < len(items):
                    commas.append(at + len(t) + sep.index(","))
                at += len(t) + len(sep)
            self.add(prefix + " " + text + self.comment(), val=base, ws=len(prefix),
                     flow=(starts or [base + 1], commas, bool(items), ends), **tags)
            return [v for _, v in items]
        if k < 0.65:
            header, body, v = self.block_str()
            ci = indent + r.randint(1, 3)
            # P5: '|' / '|-' then space, tab or end of line, before an optional comment
            self.add(prefix + " " + header + r.choice(["", "", " ", "\t", " \t"]) + self.comment(),
                     val=len(prefix) + 1, ws=len(prefix), bhead=len(prefix) + 1, bbody=(ci, len(body)), **tags)
            self.block_body(body, ci)
            return v
        if k < 0.7:
            self.add(prefix + self.comment(True), **tags)  # empty value
            return None
        self.add(prefix + self.comment(True), **tags)
        child = indent + r.randint(1, 3)
        if r.random() < 0.5:
            return self.mapping(child, depth + 1)
        if prefix.endswith(":") and r.random() < 0.4:
            child = indent  # sequence at the parent key's indent
        return self.sequence(child, depth + 1)

    def key(self):
        r = self.r
        k = r.random()
        if k < 0.7:
            while True:
                s = self.plain()
                if s != "<<":
                    return s, s
        s = self.any_str().replace("\n", "")
        s = "".join(c for c in s if c not in "\r\x01\x1f\x7f")
        if k < 0.85:
            return "'" + s.replace("'", "''") + "'", s
        return self.dq(s, False), s

    def mapping(self, indent, depth, first_prefix=None):
        r = self.r
        out = {}
        for n in range(r.randint(1, 3)):
            ktext, kv = self.key()
            if kv in out:
                continue
            if n == 0 and first_prefix is not None:
                lead = first_prefix
            else:
                self.maybe_noise()
                lead = " " * indent
            out[kv] = self.value_after(lead + ktext + ":", indent, depth,
                                       {"key": len(lead), "sep": len(lead) + len(ktext)})
        return out

    def sequence(self, indent, depth, first_prefix=None):
        r = self.r
        out = []
        for n in range(r.randint(1, 3)):
            lead = first_prefix if (n == 0 and first_prefix is not None) else " " * indent
            if n or first_prefix is None:
                self.maybe_noise()
            k = r.random()
            if depth < 4 and k < 0.25:
                gap = r.choice([" ", "   "])
                out.append(self.mapping(indent + 1 + len(gap), depth + 1, lead + "-" + gap))
                self.lines[-1][1].setdefault("item", None)
                continue
            if depth < 4 and k < 0.35:
                out.append(self.sequence(indent + 2, depth + 1, lead + "- "))
                continue
            out.append(self.value_after(lead + "-", indent, depth, {"item": len(lead)}))
        return out

    def document(self):
        r = self.r
        k = r.random()
        if k < 0.45:
            v = self.mapping(0, 1)
        elif k < 0.85:
            v = self.sequence(0, 1)
        elif k < 0.92:
            text, v = self.scalar()
            self.add(text + self.comment(), val=0)
        else:
            header, body, v = self.block_str()
            self.add(header + self.r.choice(["", " ", "\t"]), val=0, bhead=0, bbody=(2, len(body)))
            self.block_body(body, 2)
        self.maybe_noise()
        return "\n".join(t for t, _ in self.lines) + self.r.choice(["", "\n"]), v

    def refusal(self):
        """Mutate one line so the document must be refused; return (text, line, reason fragment or None)."""
        r = self.r
        idx = r.randrange(len(self.lines))
        text, tags = self.lines[idx]
        kinds = ["ctl"]
        if text and tags.get("sep") is not None and text[tags["sep"] + 1:tags["sep"] + 2] == " ":
            kinds.append("tabsep")
        if tags.get("item") is not None and text[tags["item"] + 1:tags["item"] + 2] == " ":
            kinds.append("tabdash")
        if tags.get("bhead") is not None:
            kinds.append("bhead")
        if tags.get("val") is not None:
            kinds.append("badval")
        if tags.get("key") is not None:
            kinds.append("badkey")
        lead = tags.get("ws") is not None and (tags.get("sep") is not None or tags.get("item") is not None)
        if lead:
            kinds += ["tablead", "indstart"]  # D5; P6 '- ' / '? ' / ': ' starts
        if tags.get("flow") is not None:
            kinds += ["flowcomment", "tabcomma", "flowstart"]
        if tags.get("bbody") is not None:
            kinds += ["bdeep", "btab"]
        kind = r.choice(kinds)
        fragment = None
        if kind == "ctl":
            c = r.choice([chr(i) for i in range(0x20) if i not in (9, 10)] + ["\x7f", "\ud800", "\r"])
            p = r.randint(0, len(text))
            text = text[:p] + c + text[p:]
        elif kind == "tabsep":
            p = tags["sep"]
            text, fragment = text[:p + 1] + "\t" + text[p + 2:], "tab"
        elif kind == "tabdash":
            p = tags["item"]
            text, fragment = text[:p + 1] + "\t" + text[p + 2:], "tab"
        elif kind == "bhead":
            p = tags["bhead"]
            text = text[:p] + r.choice([">", "|+", "|2", ">-"]) + text[p + (2 if text[p:p + 2] == "|-" else 1):]
        elif kind == "tablead":  # a tab anywhere in the whitespace between ':'/'-' and the value
            p = r.randint(tags["ws"] + 1, tags["val"])
            text, fragment = text[:p] + "\t" + text[p:], "tab"
        elif kind == "indstart":
            ind = r.choice(["- ", "? ", ": "] if tags.get("sep") is not None else ["? ", ": "])
            text = text[:tags["val"]] + ind + text[tags["val"]:]
        elif kind == "flowcomment":  # ' #' in a flow sequence starts a comment, which it cannot hold
            p = r.choice(tags["flow"][0] + tags["flow"][3])  # before an item, or after one
            text = text[:p] + " #" + r.choice(self.LETTERS) + text[p:]
            # after a quoted item the '#' is where ',' or ']' must be
            fragment = "comment" if text[p - 1] not in "'\"" else None
        elif kind == "tabcomma" and tags["flow"][1]:
            p = r.choice(tags["flow"][1]) + 1
            text, fragment = text[:p] + "\t" + text[p:], "tab"
        elif kind == "flowstart" and tags["flow"][2]:  # D4: '#' or '|' first in a flow item
            p, c = r.choice(tags["flow"][0]), r.choice("#|")
            fragment = "comment" if c == "#" and text[p - 1] == " " else "may not start with"
            text = text[:p] + c + text[p:]
        elif kind in ("bdeep", "btab"):  # P10: an over-indented leading blank line, a tab in a blank line
            ci, nbody = tags["bbody"]
            if kind == "bdeep":
                at, ln, fragment = idx + 1, " " * (ci + r.randint(1, 2)), "deeper"
            else:
                at, fragment = idx + 1 + r.randint(0, nbody), "tab"
                ln = r.choice(["\t", " \t", "\t ", " " * ci + "\t"])
            self.lines.insert(at, [ln, {}])
            return "\n".join(t for t, _ in self.lines) + "\n", at + 1, fragment
        elif kind in ("tabcomma", "flowstart"):  # no ',' or no item on this flow line: a control character
            text = text[:1] + "\x01" + text[1:]
        else:
            p = tags["val"] if kind == "badval" else tags["key"]
            text = text[:p] + r.choice(self.BAD_START) + text[p:]
        self.lines[idx][0] = text
        return "\n".join(t for t, _ in self.lines) + "\n", idx + 1, fragment


class TestOracle(unittest.TestCase):
    """T2: documents generated with their expected value; refusals with their line."""

    def test_oracle_fuzz(self):
        rnd = random.Random(20261031)
        accepted = refused = 0
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "crlf.yml")
            for _ in range(1500):
                g = _DocGen(rnd)
                text, want = g.document()
                self.assertEqual(parse(text), want, repr(text))
                # the same document with CRLF line ends (and maybe a BOM) through load
                data = text.replace("\n", "\r\n").encode("utf-8")
                if text.startswith("\ufeff") or rnd.random() < 0.3:
                    data = b"\xef\xbb\xbf" + data  # load strips exactly one leading BOM
                with open(p, "wb") as fh:
                    fh.write(data)
                self.assertEqual(load(p, "crlf.yml"), want, repr(data))
                accepted += 1
                bad, line, fragment = g.refusal()
                with self.assertRaises(YamlError, msg=repr(bad)) as cm:
                    parse(bad)
                self.assertEqual(cm.exception.line, line, repr(bad) + " " + str(cm.exception))
                if fragment is not None:
                    self.assertIn(fragment, cm.exception.reason, repr(bad))
                refused += 1
        self.assertEqual((accepted, refused), (1500, 1500))

    def test_oracle_round_trip_through_a_file(self):
        rnd = random.Random(31102026)
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "rt.yml")
            for _ in range(600):
                _, v = _DocGen(rnd).document()
                text = emit(v)
                with open(p, "wb") as fh:
                    fh.write(text.encode("utf-8"))
                self.assertEqual(load(p, "rt.yml"), v, repr(v))
                self.assertEqual(emit(load(p, "rt.yml")), text, repr(v))


if __name__ == "__main__":
    unittest.main()
