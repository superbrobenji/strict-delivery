"""``context.load_text(text, rel, cfg)`` (request F-20261125-a2wx): validates the already-read bytes of the context file
exactly as ``context.load`` validates the bytes it reads; ``load`` = read + ``load_text``. Expected values are written
by hand; today's ``load`` texts (measured before the change, including the doubled ``<rel>: <rel>: `` prefix of a YAML
error) are pinned by literal."""
import builtins
import collections.abc
import copy
import errno
import inspect
import os
import pathlib
import random
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


class SFmtOther(str):       # __format__ gives a different str
    def __format__(self, spec):
        return "fmt.yml"


class SFmtNonStr(str):      # __format__ gives a non-str
    def __format__(self, spec):
        return 5            # type: ignore


class SFmtRaises(str):      # __format__ raises
    def __format__(self, spec):
        raise KeyError("fmtboom")


class FmtText(str):         # a str subclass with its own __format__
    def __format__(self, spec):
        return "fmt.yml"


class SStrFmtSub(str):      # __str__ gives an instance of a subclass that has its own __format__
    def __str__(self):
        return FmtText("x.yml")


class SRadd(str):           # overrides neither __str__ nor __format__, but os.path.join uses its __radd__
    def __radd__(self, other):
        return other + "radd/" + str.__str__(self)


class SFspath(str):         # os.path.join may call its __fspath__
    def __fspath__(self):
        return "elsewhere.yml"


class SAttr(str):           # a plain subclass whose instance carries an attribute that shadows a str method
    def __new__(cls, value):
        inst = str.__new__(cls, value)
        inst.startswith = lambda *args, **kwargs: False
        return inst


class FspathStr:            # not a str; os.path.join accepts it as a path
    def __init__(self, p):
        self.p = p

    def __fspath__(self):
        return self.p


class FspathBytes(FspathStr):   # os.path.join refuses to mix its bytes with a str root
    def __fspath__(self):
        return self.p.encode()


SCHEMA_ERR = ": schema: expected context/1, got context/2; run /strict-delivery:upgrade"


class LoadRelSubclass(Base):
    """RS: ``load`` with a ``paths.context`` that is an instance of a ``str`` subclass (RS-s): every such member, on every
    path, is refused with a ``TypeError`` naming ``rel`` and the type before anything is looked up or read; an exact
    ``str`` is passed on unchanged (RS-x); every other non-str value is refused the same way, with ``rel must be str``
    (RS-n). The expected values are written by hand."""
    REFUSED = "rel: a str subclass is refused, got %s"

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
                 ("nonutf8", NON_UTF8[0], REL), ("missing", None, "nothing.yml"))
        for label, data, name in paths:
            with self.subTest(member=cls.__name__, path=label):
                self.assertEqual(self.via_load(cls, data, name), want[label])

    def test_exact_str_reaches_load_text_unchanged(self):  # RS-x: the same object, no conversion
        self.put(TAG)
        cfg = copy.deepcopy(self.cfg)
        with mock.patch.object(context, "load_text", wraps=load_text) as spy:
            self.assertEqual(load(self.root, cfg), ROW)
        self.assertEqual(spy.call_count, 1)
        self.assertIs(spy.call_args[0][1], cfg["paths"]["context"])
        self.assertEqual(spy.call_args[0][1], REL)

    MEMBERS = (  # RS-s: a plain; b __str__ other str, c non-str, d a str subclass, e raises; f __format__ other str,
        ("a", S), ("b", SOther), ("c", SNonStr), ("d", SSubText), ("e", SRaises),   # g non-str, h raises; i __str__ gives
        ("f", SFmtOther), ("g", SFmtNonStr), ("h", SFmtRaises), ("i", SStrFmtSub),   # a subclass with its own __format__;
        ("radd", SRadd), ("fspath", SFspath), ("attr", SAttr))   # other dunders; an instance attribute over a str method

    def test_every_str_subclass_is_refused(self):  # RS-s: every member, every path, the same text
        for _, cls in self.MEMBERS:
            err = ("TypeError", self.REFUSED % cls.__name__)
            self.check(cls, {"valid": err, "schema": err, "yaml": err, "nonutf8": err, "missing": err})

    def refused_untouched(self, value, want):
        """``load`` with ``paths.context`` = ``value`` raises ``TypeError(want)`` and no use of ``value`` happened: no
        ``os.path.join`` call received it (every join call is recorded; the real join runs, so ``_need_root`` and
        ``_require_toplevel`` keep working), and ``lexists``, the read and ``load_text`` were never called."""
        cfg = copy.deepcopy(self.cfg)
        cfg["paths"]["context"] = value
        with mock.patch.object(yamlsub, "_read_regular_file", side_effect=AssertionError("read")) as rd, \
                mock.patch.object(context.os.path, "lexists", side_effect=AssertionError("lexists")) as lx, \
                mock.patch.object(context, "load_text", side_effect=AssertionError("load_text")) as lt, \
                mock.patch.object(context.os.path, "join", wraps=os.path.join) as jn:
            with self.assertRaises(TypeError) as cm:
                load(self.root, cfg)
        self.assertEqual(str(cm.exception), want)
        self.assertEqual((rd.call_count, lx.call_count, lt.call_count), (0, 0, 0))
        self.assertEqual([c for c in jn.call_args_list if any(a is value for a in c.args)], [])

    def test_join_recorder_sees_rel(self):  # the recorder of refused_untouched works: an exact str is joined
        self.put(TAG)
        cfg = copy.deepcopy(self.cfg)
        with mock.patch.object(context.os.path, "join", wraps=os.path.join) as jn:
            self.assertEqual(load(self.root, cfg), ROW)
        rel = cfg["paths"]["context"]
        self.assertEqual([c for c in jn.call_args_list if any(a is rel for a in c.args)], [mock.call(self.root, REL)])

    def test_every_str_subclass_is_refused_before_any_read(self):  # RS-s, G1: nothing is joined, looked up or read
        self.put(TAG)
        for letter, cls in self.MEMBERS:
            with self.subTest(member=letter):
                self.refused_untouched(cls(REL), self.REFUSED % cls.__name__)

    NONSTR = "rel must be str, got %s"

    def test_non_str_rel_is_refused_before_any_read(self):  # RS-n, G2 (F-20261126-8g9c): refused at the guard, nothing used
        # was test_non_str_rel_is_unchanged: None, 5, bytearray, 1.5, ["a"] expected "join() argument must be str, bytes,
        # or os.PathLike object, not '<type>'" and bytes "Can't mix strings and bytes in path components"; now all
        # of them, and the PathLike members added, expect "rel must be str, got <type>" with no call of join (with rel),
        # lexists, the read or load_text
        self.put(TAG)
        for value, name in ((None, "NoneType"), (5, "int"), (bytearray(b"x"), "bytearray"), (1.5, "float"),
                            (["a"], "list"), (REL.encode(), "bytes"), (pathlib.PurePosixPath(REL), "PurePosixPath"),
                            (pathlib.PureWindowsPath(REL), "PureWindowsPath"), (pathlib.Path(REL), "PosixPath"),
                            (FspathStr(REL), "FspathStr"), (FspathBytes(REL), "FspathBytes")):
            with self.subTest(value=name):
                self.refused_untouched(value, self.NONSTR % name)

    def test_generated_rel_types_refused_before_any_read(self):  # G4: seeded generated classes and instances
        rng = random.Random(20261128)
        self.put(TAG)
        results = (REL, REL.encode(), 5, None, SubText(REL), "")

        def method(r):
            def f(self, *args):
                if r is None:
                    raise ValueError("boom")
                return r
            return f
        bases = ((object, lambda c: c()), (int, lambda c: c(5)), (float, lambda c: c(1.5)),
                 (bytes, lambda c: c(b"x")), (bytearray, lambda c: c(b"x")), (list, lambda c: c(["a"])),
                 (tuple, lambda c: c(("a",))), (dict, lambda c: c({"a": 1})),
                 (pathlib.PurePosixPath, lambda c: c(REL)), (str, lambda c: c(REL)))
        seen_str = 0
        for i in range(240):
            base, make = bases[rng.randrange(len(bases))] if i >= 10 else bases[i]   # every base at least once
            attrs = {}
            for name in ("__fspath__", "__str__", "__format__"):
                if rng.random() < 0.5:
                    attrs[name] = method(rng.choice(results))
            cls = type("G%d%s" % (i, base.__name__.capitalize()), (base,), attrs)
            want = (self.REFUSED if base is str else self.NONSTR) % cls.__name__
            seen_str += base is str
            with self.subTest(case=i, cls=cls.__name__):
                self.refused_untouched(make(cls), want)
        self.assertGreater(seen_str, 0)

    def test_load_takes_exact_types(self):  # X1 (owner Q-RS4-1 (A)): exact str root, exact dict cfg and cfg["paths"]
        class SR(str):
            pass

        class DC(dict):
            pass

        class Map(collections.abc.Mapping):     # a Mapping that is not a dict; any use of it is a failure
            def __getitem__(self, k):
                raise AssertionError("used")

            def __iter__(self):
                raise AssertionError("used")

            def __len__(self):
                raise AssertionError("used")
        self.put(TAG)
        self.assertIs(type(self.cfg), dict)             # config.load, the only source of both callers, gives plain dicts
        self.assertIs(type(self.cfg["paths"]), dict)
        self.assertEqual(load(self.root, self.cfg), ROW)
        for root in (SR(self.root), self.root.encode(), None, ""):
            with self.subTest(root=type(root).__name__), self.assertRaises(GateError) as cm:
                load(root, self.cfg)
            self.assertEqual(str(cm.exception), "root must be a string")
        for cfg in (DC(self.cfg), Map(), None):
            with self.subTest(cfg=type(cfg).__name__), self.assertRaises(TypeError) as cm:
                load(self.root, cfg)
            self.assertEqual(str(cm.exception), "cfg must be dict, got %s" % type(cfg).__name__)
        for paths in (DC(self.cfg["paths"]), Map(), None, [("context", REL)]):
            cfg = dict(self.cfg)
            cfg["paths"] = paths
            with self.subTest(paths=type(paths).__name__), self.assertRaises(TypeError) as cm:
                load(self.root, cfg)
            self.assertEqual(str(cm.exception), "cfg.paths must be dict, got %s" % type(paths).__name__)
        with self.assertRaises(GateError) as cm:        # the root checks run first, whatever cfg is
            load("", None)
        self.assertEqual(str(cm.exception), "root must be a string")

    def test_missing_keys_stay_key_errors(self):  # invariant of the replaced line: cfg["paths"]["context"] unchanged
        for cfg, key in (({}, "paths"), ({"paths": {}}, "context")):
            with self.subTest(key=key), self.assertRaises(KeyError) as cm:
                load(self.root, cfg)
            self.assertEqual(cm.exception.args, (key,))

    def test_digit_rel_same_on_both(self):  # V1: no int() on the text; 4300 and 4301 digits give one text
        for n in (4300, 4301):
            rel = "9" * n
            cfg = copy.deepcopy(self.cfg)
            cfg["paths"]["context"] = rel
            with self.subTest(n=n), self.assertRaises(GateError) as cm:
                load(self.root, cfg)
            self.assertEqual(str(cm.exception), rel + ": missing; run /strict-delivery:init")

    def test_version_dependent_rel_same_on_both(self):  # V2: U+2C2F is Cn on 3.9 and Lu on 3.13
        rel = "Ⱟ.yml"
        cfg = copy.deepcopy(self.cfg)
        cfg["paths"]["context"] = rel
        with self.assertRaises(GateError) as cm:
            load(self.root, cfg)
        self.assertEqual(str(cm.exception), rel + ": missing; run /strict-delivery:init")

    def test_changed_lines_name_no_unicode_tables(self):  # V3
        for fn in (load,):
            src = inspect.getsource(fn)
            for word in ("unicodedata", "isprintable", "BaseExceptionGroup", "splitlines", ".lower("):
                with self.subTest(fn=fn.__name__, word=word):
                    self.assertNotIn(word, src)

    def test_load_text_still_refuses_subclass(self):  # T4 unchanged: load_text itself is not widened
        for _, cls in self.MEMBERS:
            with self.subTest(cls=cls.__name__), self.assertRaises(TypeError) as cm:
                load_text(TAG, cls(REL), self.cfg)
            self.assertEqual(str(cm.exception), "rel must be str, got %s" % cls.__name__)


# ---------------------------------------------------------------- PM: the path matrix of load's read of <root>/<rel>
# Verdicts typed by hand from the docstrings of load ("a GateError for a missing file ... and one listing every problem")
# and yamlsub._read_regular_file ("The bytes of the regular file at path; any problem is a YamlError naming shown";
# "Anything but a regular file ... is refused"; a missing or non-directory parent is the OSError's strerror).
# Cells the docstrings do not settle, pinned as observed (reported as Decision needed): a symlink to a regular file at
# the target, and a holder that is a symlink to a directory, are followed (os.stat and lstat follow / resolve them).
ROW2 = {"schema": "context/1", "every": []}
MISSING = REL + ": missing; run /strict-delivery:init"
TARGET_STATES = ("absent", "file", "dir", "symlink-in", "symlink-out", "fifo")
HOLDER_STATES = ("absent", "file", "dir", "symlink-file-in", "symlink-file-out", "fifo", "symlink-dir-in",
                 "symlink-dir-out")


def cant(why):
    return ("err", REL + ": " + REL + ": cannot read file (" + why + ")")


NOTREG = cant("not a regular file")
GONE = cant("No such file or directory")
NOTDIR = cant("Not a directory")
ROWOK = ("ok", ROW)
ROW2OK = ("ok", ROW2)
GATE_MISSING = ("err", MISSING)
CELLS = (
    # (role, state, moment, verdict)
    ("target", "absent", "check", GATE_MISSING), ("target", "file", "check", ROWOK),
    ("target", "dir", "check", NOTREG), ("target", "symlink-in", "check", ROWOK),
    ("target", "symlink-out", "check", ROWOK), ("target", "fifo", "check", NOTREG),
    ("target", "name-0xff", "check", ROWOK),
    ("target", "absent", "between", GONE), ("target", "file", "between", ROW2OK),
    ("target", "dir", "between", NOTREG), ("target", "symlink-in", "between", ROW2OK),
    ("target", "symlink-out", "between", ROW2OK), ("target", "fifo", "between", NOTREG),
    ("holder", "absent", "check", GATE_MISSING), ("holder", "file", "check", GATE_MISSING),
    ("holder", "dir", "check", ROWOK), ("holder", "symlink-file-in", "check", GATE_MISSING),
    ("holder", "symlink-file-out", "check", GATE_MISSING), ("holder", "fifo", "check", GATE_MISSING),
    ("holder", "symlink-dir-in", "check", ROWOK), ("holder", "symlink-dir-out", "check", ROWOK),
    ("holder", "name-0xff", "check", ROWOK),
    ("holder", "absent", "between", GONE), ("holder", "file", "between", NOTDIR),
    ("holder", "dir", "between", ROW2OK), ("holder", "symlink-file-in", "between", NOTDIR),
    ("holder", "symlink-file-out", "between", NOTDIR), ("holder", "fifo", "between", NOTDIR),
    ("holder", "symlink-dir-in", "between", ROW2OK), ("holder", "symlink-dir-out", "between", ROW2OK),
)


class PathMatrix(Base):
    def setup_cell(self, role, state, content, sb):
        """Put the ``role`` (the target file or its holder directory) of ``sb`` into ``state``; the previous thing at
        that path is renamed into the sandbox's trash, never deleted."""
        holder = os.path.join(sb["root"], ".strict-delivery")
        target = os.path.join(holder, "context.yml")
        where = holder if role == "holder" else target
        if os.path.lexists(where):
            sb["n"] += 1
            os.rename(where, os.path.join(sb["trash"], "n%d" % sb["n"]))

        def write(p, data):
            with open(p, "wb") as fh:
                fh.write(data)

        def dir_with_target(p):
            os.mkdir(p)
            write(os.path.join(p, "context.yml"), content)
        if state == "absent":
            return
        if role == "target":
            if not os.path.isdir(holder):
                os.mkdir(holder)
            if state == "file":
                write(target, content)
            elif state == "dir":
                os.mkdir(target)
            elif state in ("symlink-in", "symlink-out"):
                real = os.path.join(sb["root"] if state == "symlink-in" else sb["other"], "real.yml")
                write(real, content)
                os.symlink(real, target)
            elif state == "fifo":
                os.mkfifo(target)
            return
        if state == "file":
            write(holder, b"x")
        elif state == "dir":
            dir_with_target(holder)
        elif state in ("symlink-file-in", "symlink-file-out"):
            real = os.path.join(sb["root"] if state.endswith("-in") else sb["other"], "realfile")
            write(real, b"x")
            os.symlink(real, holder)
        elif state == "fifo":
            os.mkfifo(holder)
        elif state in ("symlink-dir-in", "symlink-dir-out"):
            real = os.path.join(sb["root"] if state.endswith("-in") else sb["other"], "altdir")
            dir_with_target(real)
            os.symlink(real, holder)

    def run_cell(self, role, state, moment, want):
        top = tempfile.mkdtemp(dir=self.work)
        root = os.path.join(top, "repo")
        os.mkdir(root)
        make_repo(root)
        sb = {"root": root, "other": os.path.join(top, "other"), "trash": os.path.join(top, "trash"), "n": 0}
        os.mkdir(sb["other"])
        os.mkdir(sb["trash"])
        cfg = copy.deepcopy(self.cfg)
        content = TAG
        if state == "name-0xff":                    # a name holding byte 0xff, built with os.fsdecode
            try:
                broot = os.fsencode(root)
                if role == "holder":
                    rel_b = b".strict-delivery\xff/context.yml"
                    os.rename(os.path.join(broot, b".strict-delivery"), os.path.join(broot, b".strict-delivery\xff"))
                else:
                    rel_b = b".strict-delivery/context\xff.yml"
                    os.rename(os.path.join(broot, b".strict-delivery/context.yml"), os.path.join(broot, rel_b))
            except OSError as e:
                if e.errno == errno.EILSEQ:
                    self.skipTest("APFS refuses non-UTF-8 names (EILSEQ)")
                raise
            cfg["paths"]["context"] = os.fsdecode(rel_b)
        else:
            with open(os.path.join(root, REL), "wb") as fh:
                fh.write(TAG)
            if moment == "check":
                self.setup_cell(role, state, TAG, sb)
        real_read = yamlsub._read_regular_file
        done = []

        def swap(path, shown):
            if shown == REL and not done:           # not the schema loader's own read
                done.append(1)
                self.setup_cell(role, state, TAG + b"every: []\n", sb)
            return real_read(path, shown)
        try:
            with mock.patch.object(yamlsub, "_read_regular_file", side_effect=swap if moment == "between" else real_read):
                return ("ok", load(root, cfg))
        except GateError as e:
            return ("err", str(e))

    def test_generated_path_matrix_load(self):  # PM, H1-H7: every cell, seeded order
        cells = list(CELLS)
        random.Random(20261128).shuffle(cells)
        self.assertEqual(len(cells), 30)
        for role, state, moment, want in cells:
            with self.subTest(role=role, state=state, moment=moment):
                self.assertEqual(self.run_cell(role, state, moment, want), want)


if __name__ == "__main__":
    unittest.main()
