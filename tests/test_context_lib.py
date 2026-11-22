"""Task 5a.1: ``gates/schemas/context.yml`` and ``gates/lib/context.py`` (plan 5111-5195; domain table 5a.1 with its
binding controller decisions). Expected values are written by hand from the plan and the table."""
import copy
import os
import stat
import sys
import tempfile
import unittest
from unittest import mock

from gates.lib import config, context, dispatch, gitinfo, migrations, schema
from gates.lib.context import (HANDOFFS, KINDS, PLACEHOLDERS, absolute, context_errors, handoff_reads, kind_of, load,
                               required, split, values_for)
from gates.lib.result import GateError
from tests.helpers import GitIsolatedTestCase, commit_all, git, make_repo, minimal_config, within, write_record

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CTX_TAG = "context/%d" % migrations.current_version("context")  # fixtures take the tag from the schema (plan P:32)
CTX_TAGB = CTX_TAG.encode()
CFG = copy.deepcopy(config.DEFAULTS)
CFG["ids"] = dict(config.DEFAULTS["ids"])
ROW = {"schema": CTX_TAG}
PLAN = "2026-10-31-strict-delivery-framework"
HANDOFF_PATH = ".strict-delivery/state/plans/p/handoff.md"


def E(p, **kw):
    d = {"path": p, "why": "w"}
    d.update(kw)
    return d


CTX = {"schema": CTX_TAG,
       "every": [E("{paths.decisions}/in-force.md")],
       "kinds": {"plan": [E("{paths.plan_state}/{plan}/handoff.md")]},
       "roles": {"task_reviewer": [E("{brief}")]}}


def write(path, data=b"", mode="wb"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, mode) as fh:
        fh.write(data)
    return path


class TempDirCase(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.dir = os.path.realpath(td.name)


class SchemaFile(unittest.TestCase):
    def setUp(self):
        self.s = schema.load_schema(os.path.join(schema.SCHEMAS_DIR, "context.yml"))

    def test_context_schema_loads(self):  # S1
        self.assertEqual((self.s.kind, self.s.version, self.s.format, self.s.files),
                         ("context", 1, "yaml", [{"path": "context"}]))

    def test_context_schema_fields(self):  # S2
        self.assertEqual(list(self.s.fields), ["schema", "every", "kinds", "roles"])
        self.assertTrue(self.s.fields["schema"].get("required", True))
        for k in ("every", "kinds", "roles"):
            self.assertIs(self.s.fields[k]["required"], False)

    def test_kinds_fields_equal_KINDS(self):  # S3
        self.assertEqual(tuple(self.s.fields["kinds"]["fields"]), KINDS)

    def test_entry_spec_everywhere(self):  # S4
        want = {"type": "map", "fields": {"path": {"type": "str"}, "lines": {"type": "str", "required": False},
                                          "why": {"type": "str"}}}
        self.assertEqual(self.s.fields["every"]["items"], want)
        for k in KINDS:
            self.assertEqual(self.s.fields["kinds"]["fields"][k]["items"], want)
            self.assertIs(self.s.fields["kinds"]["fields"][k]["required"], False)
        self.assertEqual(self.s.fields["roles"]["type"], "any-map")

    def v(self, row):
        return schema.validate(self.s, row, CFG)

    def test_minimal_row_valid(self):  # S5
        self.assertEqual(self.v(ROW), [])

    def test_schema_tag_errors(self):  # S6
        self.assertEqual(self.v({}), ["schema: expected context/1, got (missing)"])
        self.assertEqual(self.v({"schema": "config/2"}), ["schema: expected context/1, got config/2"])
        self.assertEqual(self.v({"schema": "context/2"}),
                         ["schema: expected context/1, got context/2; run /strict-delivery:upgrade"])
        for bad in (1, "context/1 ", "context/0"):
            self.assertTrue(self.v({"schema": bad})[0].startswith("schema: expected context/1"), bad)

    def test_top_level_not_mapping(self):  # S7
        for bad in ([], None, "x"):
            self.assertEqual(self.v(bad), ["top level: must be a mapping"])

    def test_unknown_top_key(self):  # S8
        for k in ("extra", "Every", "receipts"):
            self.assertEqual(self.v({**ROW, k: []}), ["%s: unknown key" % k])

    def test_every_shapes(self):  # S9
        self.assertEqual(self.v({**ROW, "every": None}), ["every: must not be null"])
        self.assertEqual(self.v({**ROW, "every": []}), [])
        self.assertEqual(self.v({**ROW, "every": "a"}), ["every: must be a list"])
        self.assertEqual(self.v({**ROW, "every": {}}), ["every: must be a list"])

    def test_kinds_keys(self):  # S10
        self.assertEqual(self.v({**ROW, "kinds": None}), ["kinds: must not be null"])
        self.assertEqual(self.v({**ROW, "kinds": []}), ["kinds: must be a mapping"])
        for k in ("nope", "stream-a-block", "Plan", "plan "):
            self.assertEqual(self.v({**ROW, "kinds": {k: []}}), ["kinds.%s: unknown key" % k])

    def test_roles_values_checked(self):  # S11 / D-Q1(b): the schema takes any map; context_errors checks the values
        self.assertEqual(self.v({**ROW, "roles": None}), ["roles: must not be null"])
        self.assertEqual(self.v({**ROW, "roles": []}), ["roles: must be a mapping"])
        self.assertEqual(self.v({**ROW, "roles": {"implementer": 5}}), [])
        self.assertEqual(context_errors({**ROW, "roles": {"implementer": 5}}, CFG),
                         ["roles.implementer: must be a list of entries"])

    def test_bare_string_entry_refused(self):  # S12
        self.assertEqual(self.v({**ROW, "every": ["a"]}), ["every.0: must be a mapping"])

    def test_ref_key_refused(self):  # S13
        self.assertEqual(self.v({**ROW, "every": [E("a", ref="stream:x")]}), ["every.0.ref: unknown key"])
        self.assertTrue(context_errors({**ROW, "every": [{"path": "a", "why": "w", "ref": "stream:x"}]}, CFG))

    def test_why_rules(self):  # S14, PD4
        self.assertEqual(self.v({**ROW, "every": [{"path": "a"}]}), ["every.0.why: required key is missing"])
        self.assertEqual(self.v({**ROW, "every": [{"path": "a", "why": ""}]}), ["every.0.why: must be a non-empty string"])
        self.assertEqual(self.v({**ROW, "every": [{"path": "a", "why": 5}]}), ["every.0.why: must be a non-empty string"])
        for bad in (" ", "x\ny", "x\ry", "x\0y", "x\ty"):
            self.assertEqual(self.v({**ROW, "every": [{"path": "a", "why": bad}]}), [], repr(bad))  # the schema passes them
            self.assertTrue(any("why" in e for e in context_errors({**ROW, "every": [{"path": "a", "why": bad}]}, CFG)),
                            repr(bad))
        self.assertEqual(context_errors({**ROW, "every": [{"path": "a", "why": "an e-acute \u00e9"}]}, CFG), [])

    def test_path_type_errors(self):  # S15
        for bad, want in (({"why": "w"}, "required key is missing"), ({"path": "", "why": "w"}, "must be a non-empty string"),
                          ({"path": 5, "why": "w"}, "must be a non-empty string"),
                          ({"path": True, "why": "w"}, "must be a non-empty string"),
                          ({"path": None, "why": "w"}, "must not be null")):
            self.assertEqual(self.v({**ROW, "every": [bad]}), ["every.0.path: " + want], bad)

    def test_lines_type_errors(self):  # S16
        for bad, want in ((3, "must be a non-empty string"), ("", "must be a non-empty string"),
                          (None, "must not be null"), ([], "must be a non-empty string")):
            self.assertEqual(self.v({**ROW, "every": [E("a", lines=bad)]}), ["every.0.lines: " + want], bad)

    def test_lines_plain_scalar_is_str(self):  # S17, S18
        from gates.lib import yamlsub
        self.assertEqual(yamlsub.parse("lines: 3-9\nb: 3-end\nc: 3\n"), {"lines": "3-9", "b": "3-end", "c": 3})
        with self.assertRaises(yamlsub.YamlError):
            yamlsub.parse("path: {plan}/x\n")

    def test_unquoted_brace_is_yaml_error(self):  # S18
        from gates.lib import yamlsub
        with self.assertRaises(yamlsub.YamlError) as cm:
            yamlsub.parse("every:\n  - path: {plan}/x\n")
        self.assertEqual(cm.exception.line, 2)


class KindOf(unittest.TestCase):
    def test_constants(self):  # K9
        self.assertEqual(KINDS, ("plan", "program", "program-controller", "stream-block", "sync"))
        self.assertEqual(PLACEHOLDERS, ("plan", "program", "stream", "brief", "integration"))
        self.assertEqual(len(CFG["paths"]), 14)

    def test_kind_of_each_kind(self):  # K1
        for k in KINDS:
            self.assertEqual(kind_of(k), (k, None))

    def test_stream_kind_normalised(self):  # K2
        for name, sid in (("stream-docs-block", "docs"), ("stream-a-block", "a"), ("stream-a-b-block", "a-b"),
                          ("stream-0-block", "0"), ("stream-block-block", "block")):
            self.assertEqual(kind_of(name), ("stream-block", sid))
        with self.assertRaises(ValueError):
            kind_of("stream-A-block")

    def test_kind_of_bad_stream_id(self):  # K3
        for bad in ("stream--block", "stream--a-block", "stream-A-block", "stream-a_b-block", "stream-a b-block",
                    "stream-\u00e9-block", "stream-\u0663-block", "stream-a\n-block", "stream-a-block\n"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                kind_of(bad)

    def test_kind_of_reserved_ids(self):  # K4 / PD7
        self.assertEqual(kind_of("stream-integration-block"), ("stream-block", "integration"))
        self.assertEqual(kind_of("stream-records-block"), ("stream-block", "records"))

    def test_kind_of_near_names(self):  # K5
        for bad in ("stream-a", "block", "stream-block-", "-stream-a-block", "stream-a-block-x", "Plan", "PLAN", "plan ",
                    " plan", "programs", ""):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                kind_of(bad)

    def test_kind_of_wrong_types(self):  # K6
        class S(str):
            pass
        for bad in (None, 5, True, ["plan"], b"plan", S("plan")):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                kind_of(bad)

    def test_kind_of_long_id(self):  # K7
        self.assertEqual(kind_of("stream-" + "a" * 100000 + "-block"), ("stream-block", "a" * 100000))

    def test_kind_of_error_names_kinds(self):  # K8
        with self.assertRaises(ValueError) as cm:
            kind_of("nope")
        for k in KINDS:
            self.assertIn(k, str(cm.exception))


def errs(entries, key="every", **kw):
    return context_errors({**ROW, key: entries, **kw}, CFG)


class ContextErrors(unittest.TestCase):
    def test_each_placeholder_accepted(self):  # PH1
        paths = ["{plan}/a", "{program}/a", "{stream}/a", "{brief}", "{integration}/a"]
        paths += ["{paths.%s}/a" % k for k in CFG["paths"]]
        for p in paths:
            with self.subTest(p=p):
                self.assertEqual(errs([E(p)]), [])

    def test_unknown_placeholder_refused(self):  # PH2
        self.assertTrue(any("{x}" in e for e in context_errors({**ROW, "every": ["{x}/a"]}, CFG)))
        for p in ("{x}/a", "{Plan}/a", "{ plan }/a", "{plan }/a", "{}/a", "{paths}/a", "{paths.}/a", "{paths.a.b}/a"):
            with self.subTest(p=p):
                got = errs([E(p)])
                self.assertEqual(len(got), 1)
                self.assertIn("unknown placeholder", got[0])

    def test_unknown_paths_key(self):  # PH3
        for p in ("{paths.nokey}/a", "{paths.Plans}/a"):
            self.assertIn("unknown placeholder", errs([E(p)])[0])

    def test_unmatched_brace(self):  # PH4
        for p in ("{", "a{", "}", "a}", "{{plan}}", "{plan}}", "}}", "{plan", "{pl{an}}"):
            with self.subTest(p=p):
                got = errs([E(p)])
                self.assertEqual(len(got), 1)
                self.assertIn("unmatched brace", got[0])

    def test_unmatched_brace_open_inside_open(self):  # PH4, FR-2: an open brace inside an open placeholder
        for p, sentence in (("{a{b}", "path '{a{b}' has an unmatched brace"),
                            ("x{y{plan}", "path 'x{y{plan}' has an unmatched brace"),
                            ("{a{b}/c", "path '{a{b}/c' has an unmatched brace")):
            with self.subTest(p=p):
                got = errs([E(p)])
                self.assertEqual(len(got), 1)
                self.assertIn(sentence, got[0])
                self.assertNotIn("unknown placeholder", got[0])

    def test_two_placeholders(self):  # PH5
        for p in ("{paths.plans}/{plan}.md", "{plan}{plan}", "{paths.plans}{paths.specs}"):
            self.assertEqual(errs([E(p)]), [], p)

    def test_integration_only_first(self):  # PH6
        self.assertEqual(errs([E("{integration}/a")]), [])
        for p in ("a/{integration}/b", "{plan}/{integration}", "{integration}/{integration}", "x{integration}"):
            self.assertIn("{integration} may stand only first", errs([E(p)])[0], p)
        self.assertIn("alone", errs([E("{integration}")])[0])  # PD9

    def test_brief_only_alone(self):  # PH7
        self.assertEqual(errs([E("{brief}")]), [])
        for p in ("x/{brief}", "{brief}/x", "{brief}{brief}", "docs/{brief}.md"):
            self.assertIn("{brief} may stand only alone", errs([E(p)])[0], p)

    def test_normalised_relative_path(self):  # PH8
        for p, word in (("../x", ".."), ("a/../b", ".."), ("/x", "relative"), ("a//b", "normalised"),
                        ("./a", "normalised"), ("a/./b", "normalised"), ("a/", "normalised"), (".", "empty"),
                        ("{paths.plans}/../a", "..")):
            with self.subTest(p=p):
                got = errs([E(p)])
                self.assertEqual(len(got), 1)
                self.assertIn(word, got[0])
        self.assertIn("non-empty", errs([E("")])[0])
        self.assertTrue(any(".." in e for e in context_errors({**ROW, "every": ["{paths.plans}/../a"]}, CFG)))

    def test_path_characters(self):  # PH9
        for p in ("a\0b", "a\nb", "a\rb", "a\tb", "a\u0085b", "a\u2028b", "a\x7fb", "a\ud800b", "a\u2c2fb", "a\u0870b",
                  "a\U0001fae8b"):
            with self.subTest(p=p):
                self.assertIn("not printable", errs([E(p)])[0])
        self.assertEqual(errs([E("caf\u00e9.md")]), [])  # PD4: non-ASCII printable accepted

    def test_long_path(self):  # PH10
        for p in ("a" * 5000, "{" * 100000, "9" * 4301):
            got = errs([E(p)])
            self.assertEqual(len(got) if len(p) > 4096 else 0, 1 if len(p) > 4096 else 0)
        self.assertEqual(errs([E("9" * 4000)]), [])

    def test_backslash(self):  # PH11 / PD4
        self.assertEqual(errs([E("a\\b"), E("C:/x")]), [])

    def test_bare_entry_refused_not_raised(self):  # PH12
        got = errs(["a", None, 5, [], {"x": 1}])
        self.assertIn("an entry is a map", got[0])
        self.assertIn("'a'", got[0])
        self.assertEqual(sum("an entry is a map" in e for e in got[:4]), 4)

        class S(str):
            def __str__(self):
                raise AssertionError("subclass method run")
        self.assertIn("an entry is a map", errs([S("a")])[0])

    def test_entry_keys(self):  # PH13
        self.assertEqual(errs([E("a", ref="x")]), ["every.0.ref: unknown key"])
        self.assertEqual(errs([E("a", Path="x")]), ["every.0.Path: unknown key"])
        self.assertEqual(errs([{"path": "a"}]), ["every.0.why: required key is missing"])
        self.assertEqual(errs([{"why": "w"}]), ["every.0.path: required key is missing"])
        self.assertEqual(errs([E("a", lines=5)]), ["every.0.lines: must be a non-empty string"])
        self.assertEqual(errs([E("a", why="")]), ["every.0.why: must be a non-empty string"])

    def test_role_key_must_be_a_role(self):  # PH14
        self.assertTrue(any("roles" in e for e in context_errors({**ROW, "roles": {"nobody": ["a"]}}, CFG)))
        for r in dispatch.ROLES:
            self.assertEqual(context_errors({**ROW, "roles": {r: [E("a")]}}, CFG), [], r)
        for bad in ("nobody", "Task_Reviewer", "task_reviewer ", "", "stream-block", 5):
            got = context_errors({**ROW, "roles": {bad: [E("a")]}}, CFG)
            self.assertEqual(len(got), 1, bad)
            self.assertIn("not a role", got[0])

    def test_roles_value_shape(self):  # PH15
        for bad in (5, None, {}):
            self.assertEqual(context_errors({**ROW, "roles": {"implementer": bad}}, CFG),
                             ["roles.implementer: must be a list of entries"])
        self.assertEqual(context_errors({**ROW, "roles": {"implementer": []}}, CFG), [])
        got = context_errors({**ROW, "roles": {"implementer": ["a"]}}, CFG)
        self.assertIn("roles.implementer.0: an entry is a map", got[0])
        got = context_errors({**ROW, "roles": {"implementer": [E("a", ref="x"), E("../b", lines="9-3")]}}, CFG)
        self.assertEqual(len(got), 3)

    def test_duplicates_within_a_list(self):  # PH16
        self.assertEqual(errs([E("a"), E("a")]), ["every.1: 'a' listed twice"])
        self.assertEqual(errs([E("a", lines="1-2"), E("a", lines="1-2")]), ["every.1: 'a' listed twice with lines 1-2"])
        self.assertEqual(errs([E("a", lines="1-2"), E("a", lines="3-4")]), [])
        self.assertEqual(errs([E("a"), E("a", lines="1-end")]), [])
        self.assertEqual(context_errors({**ROW, "every": [E("a")], "kinds": {"plan": [E("a")]}}, CFG), [])
        self.assertEqual(context_errors({**ROW, "kinds": {"plan": [E("a"), E("a")]}}, CFG), ["kinds.plan.1: 'a' listed twice"])
        self.assertEqual(context_errors({**ROW, "roles": {"implementer": [E("a"), E("a")]}}, CFG),
                         ["roles.implementer.1: 'a' listed twice"])

    def test_bad_ranges_refused(self):  # PH17
        for bad in ("9-3", "0-1", "01-2", "3", "3-", "-end", "a-b", " 3-9", "3-9 ", "3-END", "3-End", "3--9", "3 - 9",
                    "1-0", "end-end", "3-9-12", "\u0663-\u0669", "\uff13-\uff19", "3-\n9", "1-01"):
            with self.subTest(bad=bad):
                got = errs([E("a", lines=bad)])
                self.assertEqual(len(got), 1)
                self.assertIn("lines", got[0])
                self.assertIn("every.0", got[0])
        for good in ("1-1", "3-9", "3-end", "10-10", "1-end"):
            self.assertEqual(errs([E("a", lines=good)]), [], good)
        self.assertTrue(any("lines" in e for e in context_errors({**ROW, "every": [{"path": "a", "lines": "9-3", "why": "w"}]}, CFG)))

    def test_lines_digit_limit(self):  # PH18, VN1
        n = dispatch.MAX_DIGITS
        self.assertEqual(errs([E("a", lines="1-" + "9" * n)]), [])
        self.assertEqual(errs([E("a", lines="1-" + "9" * (n + 1))])[0][:16], "every.0.lines: l")
        for k in (4300, 4301):
            self.assertEqual(len(errs([E("a", lines="1-" + "9" * k)])), 1)
            self.assertEqual(len(errs([E("a", lines="9" * k + "-end")])), 1)
        self.assertEqual(errs([E("a", lines="9" * n + "-" + "9" * n)]), [])
        self.assertEqual(len(errs([E("a", lines="9" * n + "-" + "8" * n)])), 1)

    def test_context_errors_non_dict(self):  # PH19
        for bad in (None, [], "x", 5):
            self.assertEqual(context_errors(bad, CFG), ["context: must be a mapping"])

    def test_context_errors_cfg_without_key(self):  # PH20
        self.assertIn("unknown placeholder", context_errors({**ROW, "every": [E("{paths.plans}/a")]}, {})[0])
        self.assertIn("unknown placeholder", context_errors({**ROW, "every": [E("{paths.plans}/a")]}, {"paths": {}})[0])
        self.assertEqual(context_errors(ROW, {}), [])

    def test_context_errors_pure(self):  # PH21
        with mock.patch("builtins.open", side_effect=AssertionError("read")), \
                mock.patch("subprocess.run", side_effect=AssertionError("git")):
            self.assertEqual(context_errors(CTX, CFG), [])

    def test_wrong_shapes_do_not_raise(self):  # PD3
        self.assertEqual(context_errors({**ROW, "every": 5, "kinds": [], "roles": 5}, CFG), [])
        self.assertEqual(context_errors({**ROW, "kinds": {"plan": 5, "nope": [E("../a")]}}, CFG), [])


class Required(unittest.TestCase):
    def test_required_orders_every_kind_role(self):  # R1
        self.assertEqual([e["path"] for e, _ in required(CTX, "plan", "task_reviewer", {})],
                         ["{paths.decisions}/in-force.md", "{paths.plan_state}/{plan}/handoff.md", "{brief}"])

    def test_handoff_extras_appended_last(self):  # R2
        got = required(CTX, "plan", None, {}, [{"path": "docs/x.md", "lines": "3-9", "why": "w"}])
        self.assertEqual(got[-1], ({"path": "docs/x.md", "lines": "3-9", "why": "w"}, "docs/x.md"))

    def test_required_missing_sections(self):  # R3
        self.assertEqual(required({"schema": CTX_TAG}, "plan", "implementer", {}), [])
        self.assertEqual(len(required({"every": [E("a")]}, "sync", None, {})), 1)

    def test_required_role_none(self):  # R4
        self.assertEqual(len(required(CTX, "plan", None, {})), 2)

    def test_required_role_without_list(self):  # R5
        self.assertEqual(len(required(CTX, "plan", "implementer", {})), 2)
        self.assertEqual(len(required(CTX, "plan", "nobody", {})), 2)

    def test_required_unknown_kind(self):  # R6 / PD12
        with self.assertRaises(ValueError):
            required(CTX, "nope", None, {})

    def test_required_raw_stream_kind(self):  # R7
        with self.assertRaises(ValueError):
            required(CTX, "stream-docs-block", None, {})

    def test_required_dedup_across_lists(self):  # R8
        ctx = {"every": [E("a")], "kinds": {"plan": [E("a"), E("b")]}, "roles": {"implementer": [E("b"), E("c")]}}
        got = required(ctx, "plan", "implementer", {}, [E("c"), E("d"), E("d")])
        self.assertEqual([e["path"] for e, _ in got], ["a", "b", "c", "d"])

    def test_required_same_path_different_lines(self):  # R9
        ctx = {"every": [E("a", lines="1-2"), E("a", lines="3-4"), E("a")]}
        self.assertEqual([e.get("lines") for e, _ in required(ctx, "plan", None, {})], ["1-2", "3-4", None])

    def test_required_distinct_spellings_kept(self):  # R10
        ctx = {"every": [E("{paths.plans}/{plan}.md"), E("docs/strict-delivery/plans/x.md")]}
        self.assertEqual(len(required(ctx, "plan", None, {"plan": "x"})), 2)

    def test_unresolved_placeholder_kept(self):  # R11
        got = required(CTX, "plan", None, {}, cfg=CFG)
        self.assertIn(("{paths.plan_state}/{plan}/handoff.md", None), [(e["path"], r) for e, r in got])
        self.assertIn(("{paths.decisions}/in-force.md", ".strict-delivery/state/decisions/in-force.md"),
                      [(e["path"], r) for e, r in got])
        self.assertEqual(required(CTX, "plan", None, {})[0][1], ".strict-delivery/state/decisions/in-force.md")

    def test_each_placeholder_unresolved(self):  # R12 / PD13
        ctx = {"every": [E("{plan}/a"), E("{program}/a"), E("{stream}/a"), E("{brief}"), E("{integration}/a"),
                         E("{integration}/{program}/s")]}
        got = required(ctx, "plan", None, {})
        self.assertEqual([r for _, r in got], [None] * 6)
        self.assertEqual([context.needs(e["path"], {}) for e, _ in got], ["plan", "program", "stream", "brief",
                                                                          "integration", "integration"])
        self.assertEqual(context.needs("{integration}/{program}/s", {"integration": "/i"}), "program")
        self.assertIsNone(context.needs("{paths.plans}/a", {}))

    def test_required_value_types(self):  # R13 / PD14
        for v in ("", None):
            self.assertIsNone(required(CTX, "plan", None, {"plan": v})[1][1])
        with self.assertRaises(ValueError):
            required(CTX, "plan", None, {"plan": 5})

    def test_required_extra_values_ignored(self):  # R14
        self.assertEqual(required(CTX, "plan", None, {"plan": "x", "other": "y"}, cfg=CFG)[1][1],
                         ".strict-delivery/state/plans/x/handoff.md")

    def test_required_resolved_text(self):  # R15
        ctx = {"every": [E("{paths.plans}/{plan}.md"), E("{brief}"), E("{integration}/a")]}
        got = required(ctx, "plan", None, {"plan": PLAN, "brief": "b/x.md", "integration": "/abs/i"}, cfg=CFG)
        self.assertEqual([r for _, r in got], ["docs/strict-delivery/plans/%s.md" % PLAN, "b/x.md", "/abs/i/a"])
        cfg = copy.deepcopy(CFG)
        cfg["paths"]["plans"] = "other/plans"
        self.assertEqual(required(ctx, "plan", None, {"plan": "p"}, cfg=cfg)[0][1], "other/plans/p.md")

    def test_required_no_reexpansion(self):  # R16
        ctx = {"every": [E("{plan}/{stream}")]}
        got = required(ctx, "plan", None, {"plan": "{stream}", "stream": "s"})
        self.assertEqual(got[0][1], "{stream}/s")

    def test_required_wrong_types(self):  # R17
        for args in (([], "plan", None, {}), (CTX, 5, None, {}), (CTX, "plan", None, []), (CTX, "plan", None, {}, "x"),
                     (CTX, "plan", 5, {})):
            with self.subTest(args=args), self.assertRaises(ValueError):
                required(*args)

    def test_required_no_mutation(self):  # R18
        ctx, extras = copy.deepcopy(CTX), [E("z")]
        before = copy.deepcopy((ctx, extras))
        required(ctx, "plan", "task_reviewer", {"plan": "x"}, extras)
        self.assertEqual((ctx, extras), before)

    def test_this_repository_context_resolves_for_plan(self):  # R19, RP3 (plan 5178-5179)
        row = load(REPO, config.load(REPO))
        self.assertTrue(all(r is not None for _, r in required(row, "plan", None, {"plan": PLAN})))

    def test_resolve(self):
        self.assertEqual(context.resolve("{paths.plans}/{plan}.md", {"plan": "p"}), "docs/strict-delivery/plans/p.md")
        self.assertIsNone(context.resolve("{plan}", {}))


class Handoffs(GitIsolatedTestCase):
    def setUp(self):
        super().setUp()
        self.root = make_repo(self.work)
        self.cfg = config.load(self.root)
        self.h = os.path.join(self.work, "h.md")

    def valid(self, extra=""):
        return ("---\nschema: handoff/1\nplan: p\nspec:\n  - s.md\nbranch: b\nhead: aaaaaaa\nbase: bbbbbbb\nledger: l.md\n"
                "resume: r\nblock: b\nnext_task: t\nfindings_in_flight: []\nopen_decisions: []\nrulings: 0\ngrant: null\n"
                "live_subagents: []\nrole: controller\nbudget:\n  tokens: 1\n  minutes: 1\nworktrees:\n  - path: w\n"
                "    branch: b\n    head: aaaaaaa\n    porcelain: \"\"\nskills:\n  - s\nledger_from: 2\nbatch_cut: null\n"
                "questions: []\n" + extra + "---\nbody\n")

    def put(self, text):
        write(self.h, text.encode("utf-8"))

    def test_handoffs_constant(self):  # H1
        self.assertEqual(HANDOFFS, {"plan": "{paths.plan_state}/{plan}/handoff.md",
                                    "stream-block": "{paths.plan_state}/{plan}/handoff.md"})

    def test_handoff_reads_absent_field(self):  # H2
        self.put(self.valid())
        self.assertEqual(handoff_reads(self.h, self.cfg), [])

    def test_handoff_reads_empty(self):  # H3
        self.put(self.valid("required_reads: []\n"))
        self.assertEqual(handoff_reads(self.h, self.cfg), [])

    def test_handoff_reads_entries(self):  # H4
        self.put(self.valid("required_reads:\n  - path: docs/a.md\n    why: wa\n  - path: docs/b.md\n    lines: 3-9\n    why: wb\n"))
        self.assertEqual(handoff_reads(self.h, self.cfg), [{"path": "docs/a.md", "why": "wa"},
                                                           {"path": "docs/b.md", "lines": "3-9", "why": "wb"}])

    def test_handoff_reads_missing(self):  # H5
        with self.assertRaises(GateError) as cm:
            handoff_reads(self.h, self.cfg)
        self.assertIn(self.h, str(cm.exception))

    def test_handoff_reads_file_states(self):  # H6 / PD15
        os.mkdir(self.h)
        with self.assertRaises(GateError):
            handoff_reads(self.h, self.cfg)
        os.rmdir(self.h)
        real = write(os.path.join(self.work, "real.md"), self.valid().encode())
        os.symlink(real, self.h)
        with self.assertRaises(GateError) as cm:
            handoff_reads(self.h, self.cfg)
        self.assertIn("not a regular file", str(cm.exception))
        os.unlink(self.h)
        os.mkfifo(self.h)
        with self.assertRaises(GateError) as cm:
            within(lambda: handoff_reads(self.h, self.cfg))  # a hang fails by name (FR-1), never by a timeout
        self.assertEqual(str(cm.exception), "%s: not a regular file" % self.h)

    def test_handoff_reads_failing_front_matter(self):  # H7
        for text in ("no front matter\n", "---\nschema: handoff/1\n", "---\nschema: handoff/1\nextra: 1\n---\n",
                     "---\nschema: config/2\n---\n"):
            self.put(text)
            with self.subTest(text=text), self.assertRaises(GateError) as cm:
                handoff_reads(self.h, self.cfg)
            self.assertIn(self.h, str(cm.exception))

    def test_handoff_reads_encoding(self):  # H8
        for data in (b"\xef\xbb\xbf" + self.valid().encode(), self.valid().replace("\n", "\r\n").encode(),
                     b"---\nschema: \xff\n---\n"):
            write(self.h, data)
            with self.assertRaises(GateError):
                handoff_reads(self.h, self.cfg)

    def test_handoff_reads_item_rules(self):  # H9 / PD4
        for item in ("  - path: ../x\n    why: w\n", "  - path: /etc/passwd\n    why: w\n",
                     "  - path: a\n    lines: 9-3\n    why: w\n", "  - path: a\n    lines: 01-2\n    why: w\n",
                     "  - path: a\n    lines: 1-" + "9" * 601 + "\n    why: w\n",
                     "  - path: a\n    why: w\n  - path: a\n    why: w\n"):
            self.put(self.valid("required_reads:\n" + item))
            with self.subTest(item=item), self.assertRaises(GateError) as cm:
                handoff_reads(self.h, self.cfg)
            self.assertIn("required_reads.", str(cm.exception))

    def test_handoff_reads_large_body(self):  # H10
        self.put(self.valid("required_reads:\n  - path: a\n    why: w\n").replace("body\n", "x\n" * 2_500_000))
        self.assertEqual(handoff_reads(self.h, self.cfg), [{"path": "a", "why": "w"}])

    def test_handoff_reads_wrong_type(self):  # H11
        for v in ("x", "null"):
            self.put(self.valid("required_reads: %s\n" % v))
            with self.assertRaises(GateError):
                handoff_reads(self.h, self.cfg)

    def test_handoff_reads_body_dashes(self):  # H12
        self.put(self.valid("required_reads:\n  - path: a\n    why: w\n").replace("body\n", "body\n---\nrequired_reads: x\n"))
        self.assertEqual(handoff_reads(self.h, self.cfg), [{"path": "a", "why": "w"}])


class Split(TempDirCase):
    LIM = {"context": {"max_lines": 2000, "max_bytes": 100000}}

    def f(self, data, name="f.txt"):
        return write(os.path.join(self.dir, name), data)

    def lim(self, ml=2000, mb=100000):
        return {"context": {"max_lines": ml, "max_bytes": mb}}

    def test_split_within_limits(self):  # SP1
        self.assertEqual(split(self.f(b"x\n" * 10), "3-9", self.LIM), [(3, 9)])

    def test_split_end_and_limits(self):  # SP2
        self.assertEqual(split(self.f(b"x\n" * 4500), "1-end", self.LIM), [(1, 2000), (2001, 4000), (4001, 4500)])

    def test_split_exactly_max_lines(self):  # SP3
        self.assertEqual(split(self.f(b"x\n" * 2000), "1-end", self.LIM), [(1, 2000)])

    def test_split_one_over(self):  # SP4
        self.assertEqual(split(self.f(b"x\n" * 2001), None, self.LIM), [(1, 2000), (2001, 2001)])

    def test_split_max_bytes_first(self):  # SP5: 66 x 1500 = 99000, 67 x 1500 = 100500
        self.assertEqual(split(self.f((b"x" * 1499 + b"\n") * 100), "1-end", self.LIM), [(1, 66), (67, 100)])

    def test_split_exactly_max_bytes(self):  # SP6
        self.assertEqual(split(self.f(b"x" * 9 + b"\n" + b"y" * 9 + b"\n"), "1-end", self.lim(2000, 20)), [(1, 2)])
        self.assertEqual(split(self.f(b"x" * 9 + b"\n" + b"y" * 10 + b"\n", "g"), "1-end", self.lim(2000, 20)),
                         [(1, 1), (2, 2)])

    def test_split_long_line_own_chunk(self):  # SP7
        data = b"a\n" * 4 + b"x" * 149999 + b"\n" + b"b\n" * 3
        self.assertEqual(split(self.f(data), "1-end", self.LIM), [(1, 4), (5, 5), (6, 8)])

    def test_split_consecutive_long_lines(self):  # SP8
        self.assertEqual(split(self.f((b"x" * 149999 + b"\n") * 3), "1-end", self.LIM), [(1, 1), (2, 2), (3, 3)])

    def test_split_no_final_newline(self):  # SP9
        p = self.f(b"x\ny")
        self.assertEqual(split(p, "2-end", self.LIM), [(2, 2)])
        self.assertEqual(split(p, "1-end", self.LIM), [(1, 2)])
        self.assertEqual(split(p, "1-end", self.lim(2000, 3)), [(1, 2)])  # 2 + 1 bytes: the last line has no terminator
        self.assertEqual(split(self.f(b"abc", "g"), None, self.lim(2000, 3)), [(1, 1)])

    def test_split_final_newline(self):  # SP10
        self.assertEqual(split(self.f(b"x\ny\n"), "1-end", self.LIM), [(1, 2)])
        with self.assertRaises(GateError):
            split(self.f(b"x\ny\n"), "3-3", self.LIM)

    def test_split_empty_file(self):  # SP11 / D-Q3 (A)
        p = self.f(b"")
        for lines in (None, "1-end", "1-1"):
            with self.subTest(lines=lines), self.assertRaises(GateError) as cm:
                split(p, lines, self.LIM)
            self.assertIn("past the end", str(cm.exception))

    def test_split_blank_lines(self):  # SP12
        self.assertEqual(split(self.f(b"\n\n\n"), "1-end", self.lim(2)), [(1, 2), (3, 3)])

    def test_split_past_end_refused(self):  # SP13
        p = self.f(b"x\n" * 10)
        for lines in ("3-11", "11-11", "11-end", "3-9999999"):
            with self.subTest(lines=lines), self.assertRaises(GateError) as cm:
                split(p, lines, self.LIM)
            self.assertIn("past the end", str(cm.exception))
            self.assertIn(lines, str(cm.exception))
            self.assertIn("10", str(cm.exception))

    def test_split_b_is_last_line(self):  # SP14
        self.assertEqual(split(self.f(b"x\n" * 10), "3-10", self.LIM), [(3, 10)])

    def test_split_single_line(self):  # SP15
        self.assertEqual(split(self.f(b"x\n" * 10), "4-4", self.LIM), [(4, 4)])

    def test_split_bad_lines_refused(self):  # SP16 / PD2
        p = self.f(b"x\n" * 10)
        for bad in ("9-3", "0-1", "3", "abc", ""):
            with self.subTest(bad=bad), self.assertRaises(GateError):
                split(p, bad, self.LIM)

    def test_split_crlf(self):  # SP17
        p = self.f(b"abc\r\nabc\r\nabc\r\n")
        self.assertEqual(split(p, "1-end", self.LIM), [(1, 3)])
        self.assertEqual(split(p, "1-end", self.lim(2000, 10)), [(1, 2), (3, 3)])  # 5 bytes a line with its CRLF

    def test_split_lone_cr(self):  # SP18
        self.assertEqual(split(self.f(b"a\rb\rc"), "1-end", self.LIM), [(1, 1)])

    def test_split_unicode_line_separators_not_lines(self):  # SP19
        text = "a\u2028b\x0bc\x0cd\x1ce\x85f\u2c2fg".encode("utf-8")
        self.assertEqual(split(self.f(text), "1-end", self.LIM), [(1, 1)])

    def test_split_binary_bytes(self):  # SP20
        self.assertEqual(split(self.f(b"\xff\n\x00\n\xef\xbb\xbfx\n"), "1-end", self.LIM), [(1, 3)])

    def test_split_path_states(self):  # SP21
        for p in (os.path.join(self.dir, "none"), self.dir):
            with self.assertRaises(GateError):
                split(p, None, self.LIM)
        real = self.f(b"x\n")
        os.symlink(real, os.path.join(self.dir, "l"))
        with self.assertRaises(GateError):
            split(os.path.join(self.dir, "l"), None, self.LIM)
        os.symlink(os.path.join(self.dir, "gone"), os.path.join(self.dir, "d"))
        with self.assertRaises(GateError):
            split(os.path.join(self.dir, "d"), None, self.LIM)
        os.mkfifo(os.path.join(self.dir, "q"))
        with self.assertRaises(GateError) as cm:
            within(lambda: split(os.path.join(self.dir, "q"), None, self.LIM))  # a hang fails by name (FR-1)
        self.assertEqual(str(cm.exception), "%s: not a regular file" % os.path.join(self.dir, "q"))

    def test_split_minimum_limits(self):  # SP22
        self.assertEqual(split(self.f(b"a\nb\nc\n"), "1-end", self.lim(1, 100)), [(1, 1), (2, 2), (3, 3)])
        self.assertEqual(split(self.f(b"ab\nc\n", "g"), "1-end", self.lim(10, 1)), [(1, 1), (2, 2)])

    def test_split_bad_limits(self):  # SP23 / PD17
        p = self.f(b"x\n")
        for bad in (0, -1, True, "5", None):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                split(p, None, self.lim(bad))
            with self.assertRaises(ValueError):
                split(p, None, self.lim(5, bad))
        with self.assertRaises(ValueError):
            split(p, None, {})

    def test_split_large_file(self):  # SP24
        got = split(self.f(b"x\n" * 1_000_000), "1-end", self.LIM)
        self.assertEqual(len(got), 500)
        self.assertEqual((got[0], got[-1]), ((1, 2000), (998001, 1000000)))

    def test_split_digit_cap(self):  # SP26, VN1
        p = self.f(b"x\n")
        for k in (601, 4300, 4301):
            with self.subTest(k=k), self.assertRaises(GateError) as cm:
                split(p, "1-" + "9" * k, self.LIM)
            self.assertIn("lines", str(cm.exception))

    def test_split_wrong_types(self):  # SP27
        for args in ((5, None, self.LIM), (self.f(b"x\n"), 3, self.LIM), (self.f(b"x\n"), None, [])):
            with self.subTest(args=args), self.assertRaises(ValueError):
                split(*args)


class Values(GitIsolatedTestCase):
    P = "20261101-x"

    def setUp(self):
        super().setUp()
        self.root = make_repo(self.work)
        self.cfg = config.load(self.root)
        self.wt = os.path.join(self.tmp, "w")

    def program(self, name=None, worktrees="../w", branch=None):
        name = name or self.P
        base = ".strict-delivery/state/programs/%s" % name
        git(self.root, "checkout", "-q", "-b", branch or name + "/integration")
        write_record(self.root, base + "/streams.yml", {
            "schema": "streams/1", "program": name, "plan": "p.md", "specs": [], "worktrees": worktrees,
            "streams": [], "shared": []})
        for n, head in (("status.md", "status/1"), ("sync-log.md", "sync-log/1"), ("merged.md", "merged-log/1")):
            write(os.path.join(self.root, base, n), ("<!-- schema: %s -->\n" % head).encode())
        commit_all(self.root, "program")
        git(self.root, "checkout", "-q", "main")

    def test_values_only_given(self):  # V1
        self.assertEqual(values_for(self.root, self.cfg, "plan", plan="p"), {"plan": "p"})
        self.assertEqual(values_for(self.root, self.cfg, "plan", plan="p", program=None, stream="", brief=None), {"plan": "p"})

    def test_integration_resolved_from_main_worktree(self):  # V2
        self.program()
        self.assertEqual(values_for(self.root, self.cfg, "program", program=self.P),
                         {"program": self.P, "integration": os.path.realpath(self.wt + "/" + self.P + "/integration")})

    def test_values_program_without_integration_branch(self):  # V3
        with self.assertRaises(GateError):
            values_for(self.root, self.cfg, "program", program=self.P)

    def test_values_bad_program_name(self):  # V4
        for bad in ("x", "../x", "20261101-X", "20261101-x\n", 5):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                values_for(self.root, self.cfg, "program", program=bad)
        self.assertEqual(values_for(self.root, self.cfg, "program", program=""), {})
        self.assertEqual(values_for(self.root, self.cfg, "program", program=None), {})

    def test_values_bad_worktrees(self):  # V5
        self.program(worktrees="inside")
        with self.assertRaises(GateError):
            values_for(self.root, self.cfg, "program", program=self.P)

    def test_values_from_linked_root(self):  # V6
        self.program()
        linked = os.path.join(self.tmp, "linked")
        git(self.root, "worktree", "add", "-q", linked, "-b", "other")
        self.assertEqual(values_for(linked, self.cfg, "program", program=self.P)["integration"],
                         os.path.realpath(self.wt + "/" + self.P + "/integration"))

    def test_values_stream_from_kind(self):  # V7
        self.assertEqual(values_for(self.root, self.cfg, "stream-docs-block"), {"stream": "docs"})

    def test_values_stream_disagrees(self):  # V8
        with self.assertRaises(ValueError):
            values_for(self.root, self.cfg, "stream-docs-block", stream="b")

    def test_values_stream_agrees(self):  # V9
        self.assertEqual(values_for(self.root, self.cfg, "stream-docs-block", stream="docs"), {"stream": "docs"})

    def test_values_stream_block_with_stream(self):  # V10
        self.assertEqual(values_for(self.root, self.cfg, "stream-block", stream="x"), {"stream": "x"})

    def test_values_stream_on_other_kinds(self):  # V11
        self.assertEqual(values_for(self.root, self.cfg, "plan", plan="p", stream="x"), {"plan": "p", "stream": "x"})

    def test_values_grammar(self):  # V12 / D-Q4
        for bad in ("../x", "/x", "a/b", "a b", "A", "a\n", "a\0", "a" * 4301 + "\u00e9", "\u00e9", "a\n"):
            for k in ("plan", "stream"):
                with self.subTest(k=k, bad=bad), self.assertRaises(ValueError):
                    values_for(self.root, self.cfg, "plan", **{k: bad})
        self.assertEqual(values_for(self.root, self.cfg, "plan", plan=PLAN), {"plan": PLAN})
        for bad in ("a\n", "a\0", "x" * 4097, "a\u2c2fb", 5):
            with self.subTest(brief=bad), self.assertRaises(ValueError):
                values_for(self.root, self.cfg, "plan", brief=bad)
        self.assertEqual(values_for(self.root, self.cfg, "plan", brief="../x/b.md"), {"brief": "../x/b.md"})
        self.assertEqual(values_for(self.root, self.cfg, "plan", brief="x" * 4096), {"brief": "x" * 4096})
        self.assertEqual(values_for(self.root, self.cfg, "plan", plan="", brief=""), {})

    def test_values_tag_named_like_branch(self):  # V13 / PD6
        self.program()
        git(self.root, "tag", self.P + "/integration", "main")  # a tag of the branch's name points at a commit without the program
        self.assertEqual(values_for(self.root, self.cfg, "program", program=self.P)["program"], self.P)

    def test_values_program_on_plan_kind(self):  # V14 / PD18
        with self.assertRaises(GateError):
            values_for(self.root, self.cfg, "plan", program=self.P)

    def test_values_root_forms(self):  # V15
        for bad in ("", None, 5):
            with self.assertRaises(GateError) as cm:
                values_for(bad, self.cfg, "plan")
            self.assertEqual(str(cm.exception), "root must be a string")

    def test_values_brief_as_given(self):  # V16
        self.assertEqual(values_for(self.root, self.cfg, "plan", brief="x/b.md"), {"brief": "x/b.md"})

    def test_values_unknown_kind(self):
        with self.assertRaises(ValueError):
            values_for(self.root, self.cfg, "nope")


class Absolute(GitIsolatedTestCase):
    def setUp(self):
        super().setUp()
        self.root = make_repo(self.work)

    def test_absolute_relative(self):  # A1
        self.assertEqual(absolute(self.root, "docs/a.md"), os.path.realpath(self.work) + "/docs/a.md")

    def test_absolute_symlinked_root(self):  # A2, VN6
        link = os.path.join(self.tmp, "rl")
        os.symlink(self.work, link)
        self.assertEqual(absolute(link, "docs/a.md"), os.path.realpath(self.work) + "/docs/a.md")

    def test_absolute_relative_brief_not_cwd(self):  # A3
        old = os.getcwd()
        self.addCleanup(os.chdir, old)
        os.chdir(self.tmp)
        self.assertEqual(absolute(self.root, "b.md"), os.path.realpath(self.work) + "/b.md")

    def test_absolute_absolute_brief(self):  # A4, A5
        self.assertEqual(absolute(self.root, self.tmp + "/x/b.md"), os.path.realpath(self.tmp) + "/x/b.md")
        link = os.path.join(self.tmp, "al")
        os.symlink(self.tmp, link)
        self.assertEqual(absolute(self.root, link + "/i/a"), os.path.realpath(self.tmp) + "/i/a")

    def test_absolute_symlinked_file(self):  # A6
        write(os.path.join(self.work, "elsewhere/real.md"), b"x")
        os.makedirs(os.path.join(self.work, "docs"))
        os.symlink("../elsewhere/real.md", os.path.join(self.work, "docs/l.md"))
        self.assertEqual(absolute(self.root, "docs/l.md"), os.path.realpath(self.work) + "/elsewhere/real.md")

    def test_absolute_symlinked_dir(self):  # A7
        os.makedirs(os.path.join(self.work, "other"))
        os.symlink("other", os.path.join(self.work, "docs"))
        self.assertEqual(absolute(self.root, "docs/a.md"), os.path.realpath(self.work) + "/other/a.md")

    def test_absolute_nonexistent(self):  # A8
        self.assertEqual(absolute(self.root, "docs/none.md"), os.path.realpath(self.work) + "/docs/none.md")

    def test_absolute_dotdot(self):  # A9
        self.assertEqual(absolute(self.root, "a/../../b"), os.path.realpath(self.tmp) + "/b")

    def test_absolute_nul_refused_earlier(self):  # A10, VN4
        with self.assertRaises(GateError):
            absolute(self.root, "a\0b")

    def test_absolute_root_forms(self):  # A11
        for bad in ("", None):
            with self.assertRaises(GateError):
                absolute(bad, "a")
        with self.assertRaises(GateError):
            absolute(self.tmp, "a")  # not a repository

    def test_absolute_wrong_types(self):  # A12
        for bad in (None, 5):
            with self.assertRaises(ValueError):
                absolute(self.root, bad)

    def test_absolute_trailing_slash(self):  # A13
        self.assertEqual(absolute(self.root, "docs/"), os.path.realpath(self.work) + "/docs")


class Load(GitIsolatedTestCase):
    def setUp(self):
        super().setUp()
        self.root = make_repo(self.work)
        self.cfg = config.load(self.root)
        self.path = os.path.join(self.root, ".strict-delivery/context.yml")

    def put(self, text):
        write(self.path, text.encode("utf-8"))

    def err(self):
        with self.assertRaises(GateError) as cm:
            load(self.root, self.cfg)
        return str(cm.exception)

    def test_load_valid(self):  # L1
        self.put(("schema: " + CTX_TAG + "\n"))
        self.assertEqual(load(self.root, self.cfg), {"schema": CTX_TAG})
        write_record(self.root, ".strict-delivery/context.yml", CTX)
        self.assertEqual(load(self.root, self.cfg), CTX)

    def test_missing_file_names_init(self):  # L2
        self.assertIn("/strict-delivery:init", self.err())

    def test_load_directory(self):  # L3
        os.mkdir(self.path)
        got = self.err()
        self.assertIn("not a regular file", got)
        self.assertNotIn("init", got)

    def test_load_symlink(self):  # L4
        write(os.path.join(self.root, "real.yml"), (b"schema: " + CTX_TAGB + b"\n"))
        os.symlink("../real.yml", self.path)
        self.assertEqual(load(self.root, self.cfg), {"schema": CTX_TAG})

    def test_load_dangling_symlink(self):  # L5
        os.symlink("gone.yml", self.path)
        got = self.err()
        self.assertIn("cannot read file", got)
        self.assertNotIn("init", got)

    def test_load_fifo(self):  # L6
        os.mkfifo(self.path)
        with self.assertRaises(GateError) as cm:
            within(lambda: load(self.root, self.cfg))  # a hang fails by name (FR-1)
        self.assertIn("not a regular file", str(cm.exception))

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root reads everything")
    def test_load_unreadable(self):  # L7
        self.put(("schema: " + CTX_TAG + "\n"))
        os.chmod(self.path, 0)
        self.addCleanup(os.chmod, self.path, stat.S_IRUSR | stat.S_IWUSR)
        self.assertIn("Permission denied", self.err())

    def test_load_empty(self):  # L8
        for text in ("", "# x\n"):
            self.put(text)
            self.assertIn("top level: must be a mapping", self.err())

    def test_load_yaml_errors(self):  # L9
        for text in ("every: [a\n", "every:\n\t- a\n", "schema: a\nschema: b\n", "a: &x 1\n", "a: {b: 1}\n", "---\na: 1\n",
                     "a: \0\n"):
            self.put(text)
            with self.subTest(text=text):
                self.assertRegex(self.err(), r"\(line \d+\)")
        write(self.path, b"schema: \xff\n")
        self.assertNotIn("(line", self.err())

    def test_load_bom_crlf(self):  # L10 / PD11
        write(self.path, (b"\xef\xbb\xbfschema: " + CTX_TAGB + b"\n"))
        self.assertEqual(load(self.root, self.cfg), {"schema": CTX_TAG})
        write(self.path, (b"schema: " + CTX_TAGB + b"\r\nevery: []\r\n"))
        self.assertEqual(load(self.root, self.cfg), {"schema": CTX_TAG, "every": []})

    def test_load_schema_tag(self):  # L11
        for tag, want in (("config/2", "got config/2"), ("context/2", "got context/2")):
            self.put("schema: %s\n" % tag)
            self.assertIn("schema: expected context/1, " + want, self.err())
        self.put("every: []\n")
        self.assertIn("got (missing)", self.err())

    def test_load_unknown_key(self):  # L12
        self.put(("schema: " + CTX_TAG + "\nextra: 1\n"))
        self.assertIn("extra: unknown key", self.err())

    def test_load_lists_every_problem(self):  # L13
        self.put(('schema: ' + CTX_TAG + '\nextra: 1\nkinds:\n  nope: []\nevery:\n  - path: a\n    why: w\n    ref: x\n'
                 '  - path: "../b"\n    why: w\n    lines: 9-3\nroles:\n  nobody:\n    - path: c\n      why: w\n'))
        got = self.err()
        for want in ("extra: unknown key", "kinds.nope: unknown key", "every.0.ref: unknown key", "every.1.path:",
                     "every.1.lines:", "roles.nobody: not a role"):
            self.assertIn(want, got)
        self.assertEqual(got.count("every.0.ref: unknown key"), 1)
        self.assertLess(got.index("extra: unknown key"), got.index("every.1.path:"))  # schema errors, then context_errors
        self.assertEqual(got.count("\n"), 0)

    def test_load_bare_string_listed_once(self):  # PD3, PD10
        self.put(("schema: " + CTX_TAG + "\nevery:\n  - a\n"))
        got = self.err()
        self.assertEqual(got.count("every.0"), 1)

    def test_load_without_schema_file(self):  # L14
        self.put(("schema: " + CTX_TAG + "\n"))
        with tempfile.TemporaryDirectory() as empty, mock.patch.object(schema, "SCHEMAS_DIR", empty):
            self.assertIn("context.yml", self.err())

    def test_load_root_forms(self):  # L15
        self.put(("schema: " + CTX_TAG + "\n"))
        for bad in ("", None, 5):
            with self.assertRaises(GateError) as cm:
                load(bad, self.cfg)
            self.assertEqual(str(cm.exception), "root must be a string")
        os.mkdir(os.path.join(self.root, "sub"))
        for bad in (os.path.join(self.root, "sub"), self.tmp):
            with self.assertRaises(GateError):
                load(bad, self.cfg)
        git(self.root, "add", "-A")
        git(self.root, "commit", "-qm", "ctx")
        linked = os.path.join(self.tmp, "linked")
        git(self.root, "worktree", "add", "-q", linked, "-b", "other")
        self.assertEqual(load(linked, self.cfg), {"schema": CTX_TAG})
        os.unlink(os.path.join(linked, ".strict-delivery/context.yml"))
        write(os.path.join(linked, ".strict-delivery/context.yml"), (b"schema: " + CTX_TAGB + b"\nevery: []\n"))
        self.assertEqual(load(linked, self.cfg), {"schema": CTX_TAG, "every": []})  # its own checkout

    def test_load_custom_context_path(self):  # L16
        cfg = copy.deepcopy(self.cfg)
        cfg["paths"]["context"] = "elsewhere/c.yml"
        write(os.path.join(self.root, "elsewhere/c.yml"), (b"schema: " + CTX_TAGB + b"\nevery: []\n"))
        self.assertEqual(load(self.root, cfg), {"schema": CTX_TAG, "every": []})

    def test_load_large(self):  # L17
        self.put(("schema: " + CTX_TAG + "\n") + "# c\n" * 1_300_000)
        self.assertEqual(load(self.root, self.cfg), {"schema": CTX_TAG})

    def test_load_int_lines(self):  # L18
        self.put(("schema: " + CTX_TAG + "\nevery:\n  - path: a\n    why: w\n    lines: 3\n"))
        self.assertIn("every.0.lines: must be a non-empty string", self.err())
        self.put(("schema: " + CTX_TAG + "\nevery:\n  - path: a\n    why: w\n    lines: %s\n") % ("9" * 1001))
        self.assertIn("integer too large", self.err())

    def test_load_fresh_object(self):  # L19
        self.put(("schema: " + CTX_TAG + "\nevery: []\n"))
        a = load(self.root, self.cfg)
        a["every"].append(1)
        self.assertEqual(load(self.root, self.cfg), {"schema": CTX_TAG, "every": []})


class RepositoryFile(unittest.TestCase):
    def setUp(self):
        self.cfg = config.load(REPO)
        self.row = load(REPO, self.cfg)

    def test_repository_context_file_valid(self):  # RP1
        s = schema.load_schema(os.path.join(schema.SCHEMAS_DIR, "context.yml"))
        self.assertEqual(schema.validate(s, self.row, self.cfg), [])

    def test_repository_context_file_errors_empty(self):  # RP2
        self.assertEqual(context_errors(self.row, self.cfg), [])

    def test_repository_context_program_needs_values(self):  # RP4
        got = required(self.row, "program", None, {}, cfg=self.cfg)
        self.assertEqual([r for _, r in got][1:], [None])
        self.assertEqual(context.needs(got[1][0]["path"], {}), "integration")

    def test_repository_context_roles_known(self):  # RP5
        self.assertEqual(sorted(self.row["roles"]), ["exception_reviewer", "final_reviewer", "final_verifier",
                                                     "task_reviewer"])
        for r in self.row["roles"]:
            self.assertIn(r, dispatch.ROLES)

    def test_repository_context_entries_resolve_and_exist(self):  # RP6 (plan :5149: "every entry resolves for `plan`")
        # Every entry resolves, and every resolved path exists, except the per-effort files (the plan's cleanup step
        # deletes them, plan :21) and the generated in-force.md: the exempt set is the per-effort directory
        # <paths.plan_state>/<plan>/ and <paths.decisions>/in-force.md, never a list of the current entries (FR-4, R2-1).
        per_effort = self.cfg["paths"]["plan_state"] + "/" + PLAN + "/"
        generated = self.cfg["paths"]["decisions"] + "/in-force.md"
        vals = {"plan": PLAN}
        got = required(self.row, "plan", "task_reviewer", {**vals, "brief": "CLAUDE.md"}, cfg=self.cfg)
        self.assertTrue(got)
        for e, r in got:
            with self.subTest(path=e["path"]):
                self.assertIsInstance(r, str)
                self.assertFalse(os.path.isabs(r), r)
                self.assertEqual(os.path.normpath(r), r)
                self.assertNotIn("..", r.split("/"))
                self.assertFalse("{" in r or "}" in r, r)
                if not (r.startswith(per_effort) or r == generated):
                    self.assertTrue(os.path.isfile(os.path.join(REPO, r)), r)

    def test_repository_context_why_single_line(self):  # RP9
        entries = list(self.row["every"]) + [e for v in self.row["kinds"].values() for e in v] \
            + [e for v in self.row["roles"].values() for e in v]
        self.assertEqual(len(entries), 21)
        for e in entries:
            self.assertTrue(all(0x20 <= ord(c) <= 0x7E for c in e["why"]), e)
            self.assertNotIn("lines", e)


class VersionRows(unittest.TestCase):
    def test_unicode_version_independent(self):  # VN2
        for c in ("\u2c2f", "\u0870", "\U0001fae8"):
            self.assertIn("not printable", errs([E("a%sb" % c)])[0])
        for c in ("\u0663", "\uff13"):
            self.assertEqual(len(errs([E("a", lines="%s-9" % c)])), 1)
        for c in ("\u00a0", "\u2028", "\u0085"):
            self.assertIn("not printable", errs([E("a%sb" % c)])[0])
        self.assertEqual(errs([E("a", why="x\u2c2fy")]), ["every.0.why: must be one line of printable text"])

    def test_exception_groups_not_referenced(self):  # VN3
        for rel in ("gates/lib/context.py", "gates/tools/context_cli.py"):
            with open(os.path.join(REPO, rel), encoding="utf-8") as fh:
                text = fh.read()
            self.assertNotIn("ExceptionGroup", text)
            self.assertNotIn("except*", text)

    def test_nul_refused_before_filesystem(self):  # VN4
        self.assertIn("not printable", errs([E("a\0b")])[0])
        with self.assertRaises(GateError):
            split("a\0b", None, {"context": {"max_lines": 1, "max_bytes": 1}})

    def test_git_calls_only_through_gitinfo(self):  # VN5
        for rel in ("gates/lib/context.py", "gates/tools/context_cli.py"):
            with open(os.path.join(REPO, rel), encoding="utf-8") as fh:
                text = fh.read()
            self.assertNotIn("subprocess", text)

    def test_banned_calls_absent(self):  # VN2: no Unicode-table dependent str method
        for rel in ("gates/lib/context.py", "gates/tools/context_cli.py"):
            with open(os.path.join(REPO, rel), encoding="utf-8") as fh:
                text = fh.read()
            for banned in (".lower(", ".casefold(", ".isprintable(", ".isidentifier(", ".isalnum(", ".isdigit(",
                           ".splitlines(", "\\w", "\\d", "\\s"):
                self.assertNotIn(banned, text, (rel, banned))


if __name__ == "__main__":
    unittest.main()
