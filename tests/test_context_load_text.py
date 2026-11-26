"""``context.load_text(text, rel, cfg)`` (request F-20261125-a2wx): validates the already-read bytes of the context file
exactly as ``context.load`` validates the bytes it reads; ``load`` = read + ``load_text``. Expected values are written
by hand; today's ``load`` texts (measured before the change, including the doubled ``<rel>: <rel>: `` prefix of a YAML
error) are pinned by literal."""
import builtins
import copy
import os
import sys
import tempfile
import unittest
from unittest import mock

from gates.lib import config, context, schema, yamlsub
from gates.lib.context import load, load_text
from gates.lib.result import GateError
from tests.helpers import GitIsolatedTestCase, git, make_repo

REL = ".strict-delivery/context.yml"
TAG = b"schema: context/1\n"
ROW = {"schema": "context/1"}
CTX_TEXT = (b"schema: context/1\nevery:\n  - path: '{paths.decisions}/in-force.md'\n    why: w\n"
            b"kinds:\n  plan:\n    - path: '{paths.plan_state}/{plan}/handoff.md'\n      why: w\n"
            b"roles:\n  task_reviewer:\n    - path: '{brief}'\n      why: w\n")
CTX = {"schema": "context/1",
       "every": [{"path": "{paths.decisions}/in-force.md", "why": "w"}],
       "kinds": {"plan": [{"path": "{paths.plan_state}/{plan}/handoff.md", "why": "w"}]},
       "roles": {"task_reviewer": [{"path": "{brief}", "why": "w"}]}}
P = REL + ": " + REL + ": "          # today's prefix of a YAML error: rel, then the reason that already names rel
YAML_ERRORS = (
    (b"every: [a\n", P + "unterminated flow sequence (line 1)"),
    (b"every:\n\t- a\n", P + "tab in indentation (line 2)"),
    (b"schema: a\nschema: b\n", P + "duplicate key 'schema' (line 2)"),
    (b"a: &x 1\n", P + "anchors are not supported (line 1)"),
    (b"a: {b: 1}\n", P + "flow mappings are not supported (line 1)"),
    (b"---\na: 1\n", P + "document markers are not supported (line 1)"),
    (b"a: \0\n", P + "control character not allowed (line 1)"),
)
NON_UTF8 = (b"schema: \xff\n", P + "not valid UTF-8")
EVERY = (b"schema: context/1\nextra: 1\nkinds:\n  nope: []\nevery:\n  - path: a\n    why: w\n    ref: x\n"
         b"  - path: \"../b\"\n    why: w\n    lines: 9-3\nroles:\n  nobody:\n    - path: c\n      why: w\n")
ROLES = ("program_controller, stream_controller, controller, implementer, implementer_transcription, task_reviewer, "
         "final_reviewer, final_verifier, exception_reviewer, audit_reviewer, audit_verifier, investigator, "
         "plan_writer, plan_reviewer, drafter")
EVERY_ERR = (REL + ": every.0.ref: unknown key; kinds.nope: unknown key; extra: unknown key; every.1.path: path "
             "'../b' must not hold '..'; every.1.lines: lines '9-3': b must not be less than a; roles.nobody: not a "
             "role (the roles are " + ROLES + ")")
ENTRY = b"schema: context/1\nevery:\n  - path: a\n    why: w\n    lines: %s\n"


class Base(GitIsolatedTestCase):
    def setUp(self):
        super().setUp()
        self.root = make_repo(self.work)
        self.cfg = config.load(self.root)
        self.path = os.path.join(self.root, REL)

    def lt(self, data, rel=REL):
        return load_text(data, rel, self.cfg)

    def lt_err(self, data, rel=REL):
        with self.assertRaises(GateError) as cm:
            self.lt(data, rel)
        return str(cm.exception)

    def put(self, data):
        with open(self.path, "wb") as fh:
            fh.write(data)

    def verdict_load(self, data):
        self.put(data)
        try:
            return ("ok", load(self.root, self.cfg))
        except GateError as e:
            return ("err", str(e))

    def verdict_text(self, data):
        try:
            return ("ok", self.lt(data, self.cfg["paths"]["context"]))
        except GateError as e:
            return ("err", str(e))


class LoadText(Base):
    def test_valid(self):  # LT-valid (T1, L1)
        self.assertEqual(self.lt(TAG), ROW)
        self.assertEqual(self.lt(CTX_TEXT), CTX)

    def test_fresh(self):  # LT-fresh (L19)
        a = self.lt(TAG + b"every: []\n")
        a["every"].append(1)
        self.assertEqual(self.lt(TAG + b"every: []\n"), {"schema": "context/1", "every": []})

    def test_text_types(self):  # LT-text-types (T2)
        class B(bytes):
            pass
        for v, name in (("schema: context/1\n", "str"), (bytearray(TAG), "bytearray"), (memoryview(TAG), "memoryview"),
                        (None, "NoneType"), (5, "int"), (B(TAG), "B")):
            with self.subTest(type=name), mock.patch.object(yamlsub, "parse") as parse:
                with self.assertRaises(TypeError) as cm:
                    load_text(v, REL, self.cfg)
                self.assertIn("text", str(cm.exception))
                self.assertIn(name, str(cm.exception))
                parse.assert_not_called()

    def test_rel(self):  # LT-rel (T3)
        self.assertEqual(self.lt(TAG, ""), ROW)
        self.assertEqual(self.lt_err(b"", "a b/é.yml"), "a b/é.yml: top level: must be a mapping")
        self.assertEqual(self.lt_err(b"", ""), ": top level: must be a mapping")
        self.assertEqual(self.lt_err(b"a: &x 1\n", "r.yml"), "r.yml: r.yml: anchors are not supported (line 1)")
        self.assertEqual(self.lt_err(b"\xff", "r.yml"), "r.yml: r.yml: not valid UTF-8")

    def test_rel_types(self):  # LT-rel-types (T4)
        class S(str):
            pass
        for v, name in ((None, "NoneType"), (REL.encode(), "bytes"), (5, "int"), (S(REL), "S")):
            with self.subTest(type=name), mock.patch.object(yamlsub, "parse") as parse:
                with self.assertRaises(TypeError) as cm:
                    load_text(TAG, v, self.cfg)
                self.assertIn("rel", str(cm.exception))
                self.assertIn(name, str(cm.exception))
                parse.assert_not_called()

    def test_empty(self):  # LT-empty (L8)
        for data in (b"", b"# x\n"):
            self.assertEqual(self.lt_err(data), REL + ": top level: must be a mapping")

    def test_yaml(self):  # LT-yaml (L9, H6)
        for data, want in YAML_ERRORS:
            with self.subTest(data=data):
                self.assertEqual(self.lt_err(data), want)
        self.assertEqual(self.lt_err(NON_UTF8[0]), NON_UTF8[1])
        self.assertNotIn("(line", NON_UTF8[1])

    def test_bom_crlf(self):  # LT-bom-crlf (L10)
        self.assertEqual(self.lt(b"\xef\xbb\xbf" + TAG), ROW)
        self.assertEqual(self.lt(b"schema: context/1\r\nevery: []\r\n"), {"schema": "context/1", "every": []})
        self.assertEqual(self.lt_err(b"\xef\xbb\xbf\xef\xbb\xbf" + TAG),
                         REL + ": schema: expected context/1, got (missing)")

    def test_tag(self):  # LT-tag (L11)
        self.assertEqual(self.lt_err(b"schema: config/2\n"), REL + ": schema: expected context/1, got config/2")
        self.assertEqual(self.lt_err(b"schema: context/2\n"),
                         REL + ": schema: expected context/1, got context/2; run /strict-delivery:upgrade")
        self.assertEqual(self.lt_err(b"every: []\n"), REL + ": schema: expected context/1, got (missing)")

    def test_unknown(self):  # LT-unknown (L12)
        self.assertEqual(self.lt_err(TAG + b"extra: 1\n"), REL + ": extra: unknown key")

    def test_every(self):  # LT-every (L13)
        got = self.lt_err(EVERY)
        self.assertEqual(got, EVERY_ERR)
        self.assertEqual(got.count("\n"), 0)

    def test_bare(self):  # LT-bare (PD3)
        got = self.lt_err(TAG + b"every:\n  - a\n")
        self.assertEqual(got, REL + ": every.0: must be a mapping")
        self.assertEqual(got.count("every.0"), 1)

    def test_no_schema(self):  # LT-no-schema (L14)
        with tempfile.TemporaryDirectory() as empty, mock.patch.object(schema, "SCHEMAS_DIR", empty):
            self.assertIn("context.yml", self.lt_err(TAG))

    def test_large(self):  # LT-large (L17)
        self.assertEqual(self.lt(TAG + b"# c\n" * 1_300_000), ROW)

    def test_int_lines(self):  # LT-int-lines (L18)
        self.assertEqual(self.lt_err(ENTRY % b"3"), REL + ": every.0.lines: must be a non-empty string")
        self.assertEqual(self.lt_err(ENTRY % (b"9" * 1001)), P + "integer too large (line 5)")

    def test_pc1_digits(self):  # LT-pc1-digits (PC1a)
        for n in (4300, 4301):
            with self.subTest(n=n):
                got = self.lt_err(ENTRY % (b"'" + b"9" * n + b"'"))
                self.assertTrue(got.startswith(REL + ": every.0.lines: lines '999"), got[:80])
                self.assertTrue(got.endswith("(decimal, at most 600 digits)"), got[-80:])
                self.assertNotIn("int", got.replace("(decimal", ""))
        # an unquoted 4301-digit integer is refused by the parser, not converted
        self.assertEqual(self.lt_err(ENTRY % (b"9" * 4301)), P + "integer too large (line 5)")

    def test_pc1_unicode(self):  # LT-pc1-unicode (PC1b)
        data = ("schema: context/1\nevery:\n  - path: a\n    why: x\U0001fae8y\n").encode("utf-8")
        self.assertEqual(self.lt_err(data), REL + ": every.0.why: must be one line of printable text")

    def test_pc1_beg(self):  # LT-pc1-beg (PC1c)
        if sys.version_info >= (3, 11):
            exc = BaseExceptionGroup("g", [KeyboardInterrupt()])  # noqa: F821
            self.assertIs(type(exc), BaseExceptionGroup)  # noqa: F821  # not the ExceptionGroup that ValueError members make
        else:
            self.assertFalse(hasattr(builtins, "BaseExceptionGroup"))

            class Group(BaseException):
                pass
            exc = Group("g")
            exc.exceptions = (KeyboardInterrupt(),)   # the group shape of 3.11+
        self.assertNotIsInstance(exc, Exception)
        self.assertEqual(len(exc.exceptions), 1)
        self.assertIs(type(exc.exceptions[0]), KeyboardInterrupt)
        with mock.patch.object(yamlsub, "parse", side_effect=exc):
            with self.assertRaises(type(exc)) as cm:
                self.lt(TAG)
        self.assertIs(cm.exception, exc)


class Parity(Base):
    def test_parity(self):  # LT-parity (P)
        inputs = [TAG, CTX_TEXT, TAG + b"every: []\n", b"", b"# x\n", b"\xef\xbb\xbf" + TAG,
                  b"schema: context/1\r\nevery: []\r\n", b"\xef\xbb\xbf\xef\xbb\xbf" + TAG,
                  b"schema: config/2\n", b"schema: context/2\n", b"every: []\n", TAG + b"extra: 1\n", EVERY,
                  TAG + b"every:\n  - a\n", ENTRY % b"3", ENTRY % (b"9" * 1001), ENTRY % (b"'" + b"9" * 4301 + b"'"),
                  NON_UTF8[0], TAG + b"# c\n" * 1_300_000] + [d for d, _ in YAML_ERRORS]
        for data in inputs:
            with self.subTest(data=data[:60]):
                self.assertEqual(self.verdict_text(data), self.verdict_load(data))

    def test_parity_literal(self):  # today's load texts pinned by literal
        self.assertEqual(self.verdict_load(EVERY), ("err", EVERY_ERR))
        self.assertEqual(self.verdict_load(CTX_TEXT), ("ok", CTX))
        self.assertEqual(self.verdict_load(NON_UTF8[0]), ("err", NON_UTF8[1]))

    def test_one_read(self):  # LT-one-read (R2)
        self.put(TAG)
        real = yamlsub._read_regular_file
        with mock.patch.object(yamlsub, "_read_regular_file", wraps=real) as rd:
            self.assertEqual(load(self.root, self.cfg), ROW)
        ctx_calls = [c for c in rd.call_args_list if c.args[1] == REL]  # the schema loader reads its own file too
        self.assertEqual(ctx_calls, [mock.call(self.path, REL)])

    def test_load_calls_load_text_with_rel(self):  # the read bytes and rel reach load_text
        self.put(TAG)
        with mock.patch.object(context, "load_text", return_value={"schema": "x"}) as lt:
            self.assertEqual(load(self.root, self.cfg), {"schema": "x"})
        lt.assert_called_once_with(TAG, REL, self.cfg)

    def test_h4_parent_symlink(self):  # LT-h4: today's verdict (the symlinked parent is followed)
        sd = os.path.join(self.root, ".strict-delivery")
        os.rename(sd, os.path.join(self.root, "altdir"))
        os.symlink("altdir", sd)
        self.put(TAG)
        self.assertEqual(load(self.root, self.cfg), ROW)

    def test_h6_name(self):  # LT-h6-name
        cfg = copy.deepcopy(self.cfg)
        cfg["paths"]["context"] = "else where/é c.yml"
        os.makedirs(os.path.join(self.root, "else where"))
        with open(os.path.join(self.root, "else where/é c.yml"), "wb") as fh:
            fh.write(TAG + b"every: []\n")
        self.assertEqual(load(self.root, cfg), {"schema": "context/1", "every": []})

    def test_h7_outside(self):  # LT-h7: today's verdict pinned
        cfg = copy.deepcopy(self.cfg)
        cfg["paths"]["context"] = "../outside.yml"
        with open(os.path.join(os.path.dirname(self.root), "outside.yml"), "wb") as fh:
            fh.write(TAG)
        try:
            got = ("ok", load(self.root, cfg))
        except GateError as e:
            got = ("err", str(e))
        self.assertEqual(got, ("ok", ROW))


class S(str):
    pass


class SOther(str):          # __str__ gives a different exact str
    def __str__(self):
        return "other.yml"


class SNonStr(str):         # __str__ gives a non-str
    def __str__(self):
        return 5            # type: ignore


class SubText(str):
    pass


class SSubText(str):        # __str__ gives a str subclass instance
    def __str__(self):
        return SubText("sub.yml")


class SRaises(str):         # __str__ raises
    def __str__(self):
        raise ValueError("boom")


SCHEMA_ERR = ": schema: expected context/1, got context/2; run /strict-delivery:upgrade"


class LoadRelSubclass(Base):
    """R-sub: ``load`` with a ``str``-subclass ``paths.context``: the pre-request ``load`` (origin/main, measured by a
    scratch script on both interpreters) formatted ``rel`` with ``%s`` only; the expected values are written by hand."""

    def via_load(self, cls, data, name=REL):
        cfg = copy.deepcopy(self.cfg)
        cfg["paths"]["context"] = cls(name)
        if data is not None:
            self.put(data)
        try:
            return ("ok", load(self.root, cfg))
        except GateError as e:
            return ("err", str(e))
        except Exception as e:
            return (type(e).__name__, str(e))

    def check(self, cls, want):
        paths = (("valid", TAG, REL), ("schema", b"schema: context/2\n", REL), ("yaml", b"every: [a\n", REL),
                 ("missing", None, "nothing.yml"))
        for label, data, name in paths:
            with self.subTest(member=cls.__name__, path=label):
                self.assertEqual(self.via_load(cls, data, name), want[label])

    def test_plain_subclass(self):  # R-sub-a
        self.check(S, {"valid": ("ok", ROW),
                       "schema": ("err", REL + SCHEMA_ERR),
                       "yaml": ("err", REL + ": " + REL + ": unterminated flow sequence (line 1)"),
                       "missing": ("err", "nothing.yml: missing; run /strict-delivery:init")})

    def test_str_gives_other_exact_str(self):  # R-sub-b
        self.check(SOther, {"valid": ("ok", ROW),
                            "schema": ("err", "other.yml" + SCHEMA_ERR),
                            "yaml": ("err", "other.yml: other.yml: unterminated flow sequence (line 1)"),
                            "missing": ("err", "other.yml: missing; run /strict-delivery:init")})

    def test_str_gives_non_str(self):  # R-sub-c: refused with a TypeError on every path (controller's decision)
        err = ("TypeError", "__str__ returned non-string (type int)")
        self.check(SNonStr, {"valid": err, "schema": err, "yaml": err, "missing": err})

    def test_str_gives_str_subclass(self):  # R-sub-d: a member found by the class check
        self.check(SSubText, {"valid": ("ok", ROW),
                              "schema": ("err", "sub.yml" + SCHEMA_ERR),
                              "yaml": ("err", "sub.yml: sub.yml: unterminated flow sequence (line 1)"),
                              "missing": ("err", "sub.yml: missing; run /strict-delivery:init")})

    def test_str_raises(self):  # R-sub-e: a member found by the class check; the __str__'s own error on every path
        err = ("ValueError", "boom")
        self.check(SRaises, {"valid": err, "schema": err, "yaml": err, "missing": err})

    def test_load_text_still_refuses_subclass(self):  # T4 unchanged: load_text itself is not widened
        for cls in (S, SOther, SNonStr, SSubText, SRaises):
            with self.subTest(cls=cls.__name__), self.assertRaises(TypeError) as cm:
                load_text(TAG, cls(REL), self.cfg)
            self.assertEqual(str(cm.exception), "rel must be str, got %s" % cls.__name__)


if __name__ == "__main__":
    unittest.main()
