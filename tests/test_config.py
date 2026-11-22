"""Tests for the config loader (gates.lib.config), on fixture repositories made by make_repo."""
import ast
import contextlib
import copy
import io
import os
import stat
import unittest
from unittest import mock

from gates.lib import config, migrations, yamlsub
from gates.lib.result import GateError, Result, gate_args, run_gate
from gates.lib.yamlsub import emit
from tests.helpers import (E128, INT_LIMITS, TOP, GitIsolatedTestCase, check_root_forms, int_limit, make_repo,
                           minimal_config, root_forms)

MISSING = ".strict-delivery/config.yml: missing; run /strict-delivery:init"

# Written independently of config.DEFAULTS (from the brief), so the loader is compared with a second copy.
OWNER_ONLY = ["triage", "spec-direction", "scope", "merge-grant", "model-policy", "issue-close",
              "rule-override", "profile-override", "program-create", "stream-ownership", "stream-merge",
              "request-dispute", "program-close"]
EXPECTED = {
    "schema": minimal_config()["schema"],  # the tag of minimal_config() is tested by test_minimal_config_is_current
    "framework_version": "0.0.0",
    "profile": "strict",
    "paths": {
        "state": ".strict-delivery/state",
        "decisions": ".strict-delivery/state/decisions",
        "findings": ".strict-delivery/state/findings",
        "claims": ".strict-delivery/state/claims",
        "plan_state": ".strict-delivery/state/plans",
        "programs": ".strict-delivery/state/programs",
        "playbooks": ".strict-delivery/playbooks",
        "receipts": ".strict-delivery/receipts",
        "context": ".strict-delivery/context.yml",
        "architecture": "docs/strict-delivery/architecture.md",
        "index": "docs/strict-delivery/INDEX.md",
        "specs": "docs/strict-delivery/specs",
        "plans": "docs/strict-delivery/plans",
        "reviews": "docs/strict-delivery/reviews",
    },
    "ids": {"decision": "DEC", "finding": "F", "claim": "C", "request": "R"},
    "base_branch": "main",
    "decisions": {"scan": ["docs/**", "CLAUDE.md", ".strict-delivery/playbooks/**"]},
    "models": {"tiers": {"tier1": "haiku", "tier2": "sonnet", "tier3": "opus"}},
    "drift": {"estimate_factor_pct": 150},
    "decision_classes": {"owner_only": OWNER_ONLY},
    # Written by hand from the plan (Task 2c.2 Produces, owner answers Q-PP-14, Q-COST-1, Q-RD-8, Q-RD-10, Q-RD-11).
    "merge": {"mode": "host"},
    "reviews": {"small": {"max_lines": 150, "max_files": 4,
                          "exclude": [".strict-delivery/**", ".github/workflows/**", ".claude/**", "CLAUDE.md"],
                          "tier": "tier2"}},
    "context": {"max_lines": 2000, "max_bytes": 100000},
    # Written by hand from the plan (Task 4a.2: the strict profile, P:4265-4267), not read from profiles/.
    "top_tier_roles": ["final_verifier", "exception_reviewer"],
    "block": {"max_tasks": 3},
}
TAG = minimal_config()["schema"]


def expected(**changes):
    """EXPECTED with dotted-key changes applied, e.g. expected(**{"paths.state": "x"})."""
    out = copy.deepcopy(EXPECTED)
    for dotted, value in changes.items():
        node = out
        parts = dotted.split("__")
        for p in parts[:-1]:
            node = node[p]
        node[parts[-1]] = value
    return out


class ConfigCase(GitIsolatedTestCase):
    def setUp(self):
        super().setUp()
        self.root = make_repo(self.work)
        self.path = os.path.join(self.root, ".strict-delivery", "config.yml")

    def put(self, cfg):
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write(emit(cfg))

    def put_bytes(self, data):
        with open(self.path, "wb") as fh:
            fh.write(data)

    def with_extra(self, extra, drop=()):
        cfg = minimal_config()
        cfg.update(extra)
        for k in drop:
            del cfg[k]
        self.put(cfg)
        return config.load(self.root)

    def refused(self, extra, *needles, drop=()):
        with self.assertRaises(GateError) as e:
            self.with_extra(extra, drop)
        msg = str(e.exception)
        for n in needles:
            self.assertIn(n, msg)
        self.assertNotIn(self.root, msg)
        return msg

    def refused_text(self, text, *needles):
        self.put_bytes(text if isinstance(text, bytes) else text.encode("utf-8"))
        with self.assertRaises(GateError) as e:
            config.load(self.root)
        for n in needles:
            self.assertIn(n, str(e.exception))
        return str(e.exception)


class DefaultsTest(ConfigCase):
    def test_defaults_merged(self):  # C19
        cfg = config.load(self.root)
        self.assertEqual(cfg, EXPECTED)
        self.assertEqual(cfg["paths"]["decisions"], ".strict-delivery/state/decisions")
        self.assertIn("program-close", cfg["decision_classes"]["owner_only"])
        self.assertEqual(cfg["models"]["tiers"]["tier2"], "sonnet")
        self.assertEqual(cfg["drift"]["estimate_factor_pct"], 150)
        self.assertNotIn("tier4", cfg["models"]["tiers"])  # Q-rev2-1

    def test_base_branch_and_scan_defaults(self):  # OQ-4, OQ-10
        cfg = config.load(self.root)
        self.assertEqual(cfg["base_branch"], "main")
        self.assertEqual(cfg["decisions"]["scan"], ["docs/**", "CLAUDE.md", ".strict-delivery/playbooks/**"])

    def test_config_path_constant(self):
        self.assertEqual(config.CONFIG_PATH, ".strict-delivery/config.yml")

    def test_defaults_never_mutated_across_calls(self):
        before = copy.deepcopy(config.DEFAULTS)
        cfg = config.load(self.root)
        cfg["paths"]["state"] = "mutated"
        cfg["decisions"]["scan"].append("mutated")
        cfg["decision_classes"]["owner_only"].append("mutated")
        cfg["models"]["tiers"]["tier9"] = "mutated"
        self.assertEqual(config.DEFAULTS, before)
        self.assertEqual(config.load(self.root), EXPECTED)
        self.with_extra({"paths": {"state": "x/y"}, "decision_classes": {"owner_only": ["hardware"]},
                         "decisions": {"scan": ["a"]}, "models": {"tiers": {"tier1": "z"}}})
        self.assertEqual(config.DEFAULTS, before)
        self.assertEqual(config.DEFAULTS["decision_classes"]["owner_only"], OWNER_ONLY)

    def test_mapping_merges_key_by_key_list_replaces(self):
        cfg = self.with_extra({"paths": {"state": "x/y"}, "decisions": {"scan": ["only/**"]},
                               "models": {"tiers": {"tier2": "other"}}})
        want = expected(**{"paths__state": "x/y", "decisions__scan": ["only/**"]})
        want["models"]["tiers"]["tier2"] = "other"
        self.assertEqual(cfg, want)

    def test_file_value_scalar_replaces(self):
        cfg = self.with_extra({"base_branch": "develop", "drift": {"estimate_factor_pct": 200}})
        self.assertEqual(cfg, expected(base_branch="develop", drift__estimate_factor_pct=200))

    def test_root_argument(self):  # C20
        sub = os.path.join(self.root, "sub")
        os.mkdir(sub)
        self.assertEqual(config.load(self.root), EXPECTED)
        for root, want in ((sub, TOP), (os.path.join(self.root, "nope"), E128), (self.path, E128)):
            with self.subTest(root=root):
                with self.assertRaises(GateError) as e:
                    config.load(root)
                self.assertEqual(str(e.exception), want)


class FileKindTest(ConfigCase):
    def test_missing_config_names_init(self):  # C1, Review Focus 5
        os.remove(self.path)
        with self.assertRaises(GateError) as e:
            config.load(self.root)
        self.assertEqual(str(e.exception), MISSING)

    def test_missing_config_through_run_gate(self):
        for root in (self.root, os.path.join(self.tmp, "plain-nongit")):
            os.makedirs(root, exist_ok=True)
            if root == self.root:
                os.remove(self.path)

            def check(args, r=root):
                config.load(gate_args("x").parse_args(args).root)
                return Result("x", [])
            import contextlib
            import io
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = run_gate("x", check, ["--root", root])
            self.assertEqual(code, 1)
            want = MISSING if root == self.root else E128  # a non-repository root is refused first (Q-1bfin-2)
            self.assertEqual(out.getvalue(), "FAIL x.input: " + want + "\n")
            self.assertNotIn("Traceback", err.getvalue())

    def test_directory_fifo_and_symlinks(self):
        os.remove(self.path)
        os.mkdir(self.path)
        self.assertIn(config.CONFIG_PATH, self.refused_text_dir())
        os.rmdir(self.path)
        os.mkfifo(self.path)
        self.assertIn(config.CONFIG_PATH, self.refused_text_dir())
        os.remove(self.path)
        fifo = os.path.join(self.tmp, "fifo")
        os.mkfifo(fifo)
        os.symlink(fifo, self.path)
        self.assertIn(config.CONFIG_PATH, self.refused_text_dir())
        os.remove(self.path)
        os.symlink(os.path.join(self.tmp, "dangling"), self.path)
        self.assertIn(config.CONFIG_PATH, self.refused_text_dir())

    def refused_text_dir(self):
        with self.assertRaises(GateError) as e:
            config.load(self.root)
        self.assertNotEqual(str(e.exception), MISSING)
        self.assertNotIn(self.root, str(e.exception))
        return str(e.exception)

    def test_symlink_to_regular_file_is_read(self):
        real = os.path.join(self.tmp, "real.yml")
        os.rename(self.path, real)
        os.symlink(real, self.path)
        self.assertEqual(config.load(self.root), EXPECTED)

    @unittest.skipIf(os.geteuid() == 0, "root can read mode 000")
    def test_unreadable(self):
        os.chmod(self.path, 0)
        self.addCleanup(os.chmod, self.path, stat.S_IRUSR | stat.S_IWUSR)
        self.assertIn(config.CONFIG_PATH, self.refused_text_dir())


class YamlContentTest(ConfigCase):
    def test_yaml_error_names_file_and_line(self):  # C2
        msg = self.refused_text("a: [1\n", ".strict-delivery/config.yml", "line 1")
        self.assertNotIn(self.root, msg)
        msg = self.refused_text("schema: %s\nframework_version: '0'\n\tprofile: strict\n" % TAG,
                                ".strict-delivery/config.yml", "line 3")

    def test_bom_and_crlf_are_read(self):
        data = emit(minimal_config()).encode("utf-8")
        self.put_bytes(b"\xef\xbb\xbf" + data)
        self.assertEqual(config.load(self.root), EXPECTED)
        self.put_bytes(data.replace(b"\n", b"\r\n"))
        self.assertEqual(config.load(self.root), EXPECTED)

    def test_not_utf8_names_file(self):
        self.refused_text(b"schema: \xff\n", ".strict-delivery/config.yml")

    def test_empty_and_comment_only_refused(self):
        for text in ("", "# only a comment\n", "\n\n"):
            with self.subTest(text=text):
                self.refused_text(text, ".strict-delivery/config.yml", "mapping")

    def test_top_level_type(self):  # C3
        for text in ("- a\n- b\n", "just text\n", "42\n", "true\n", "[a]\n", '"s"\n'):
            with self.subTest(text=text):
                self.refused_text(text, "mapping")
        self.put(minimal_config())
        self.assertEqual(config.load(self.root), EXPECTED)


class RequiredKeysTest(ConfigCase):
    def test_only_three_keys_required(self):  # C4, OQ-1
        for key in ("schema", "framework_version", "profile"):
            with self.subTest(key=key):
                self.refused({}, key, drop=(key,))
        self.assertEqual(self.with_extra({}), EXPECTED)

    def test_bad_schema_tags_refused(self):  # C5, T3: the hint exactly when a str config/<n>, n without a leading 0
        hint = "; run /strict-delivery:upgrade"
        # (value, hint expected). config/0 and config/01 do not match gate_schema's tag rule (schema._TAG), so no hint
        # (divergence from D2's regex text, which admits config/0, disclosed in the report).
        cases = [("config/1", True), ("config/3", True), ("config/10", True), ("config/0", False),
                 ("config/01", False), ("decision/2", False), (TAG + " ", False), ("Config/2", False),
                 (1, False), (None, False), (True, False), ([TAG], False), ({"a": 1}, False), ("", False)]
        for value, want_hint in cases:
            with self.subTest(value=value):
                msg = self.refused({"schema": value}, ".strict-delivery/config.yml: schema: must be '%s'" % TAG)
                self.assertEqual(msg.endswith(hint), want_hint, msg)
                self.assertEqual(msg, ".strict-delivery/config.yml: schema: must be '%s'%s"
                                 % (TAG, hint if want_hint else ""))
        self.assertEqual(self.with_extra({"schema": TAG}), EXPECTED)

    def test_config_1_refused_with_upgrade_hint(self):  # T2: old-version refusal test, the old tag is its subject
        with self.assertRaises(GateError) as e:
            self.with_extra({"schema": "config/1"})
        self.assertEqual(str(e.exception),
                         ".strict-delivery/config.yml: schema: must be 'config/2'; run /strict-delivery:upgrade")

    def test_config_tag_matches_schema_version(self):  # T4, D4: config.py cannot import schema at load
        self.assertEqual(TAG, "config/%d" % migrations.current_version("config"))
        self.assertEqual(config.CONFIG_TAG, TAG)

    def test_config_schema_is_version_2(self):  # S1
        self.assertEqual(migrations.current_version("config"), 2)

    def test_minimal_config_is_current(self):  # H1: the tag of minimal_config() is this test's subject
        self.assertEqual(minimal_config()["schema"], "config/2")

    def test_framework_version(self):  # C6
        for ok in ("0.0.0", "abc", "1.2.3-rc1"):
            with self.subTest(ok=ok):
                self.assertEqual(self.with_extra({"framework_version": ok})["framework_version"], ok)
        for bad in ("", 1, None, True, ["0"], {"a": 1}):
            with self.subTest(bad=bad):
                self.refused({"framework_version": bad}, "framework_version")

    def test_profile(self):  # C7
        for ok in ("light", "standard", "strict"):
            with self.subTest(ok=ok):
                self.assertEqual(self.with_extra({"profile": ok})["profile"], ok)
        for bad in ("Strict", " strict", "strict ", "loose", "", 1, None, True, ["strict"], {"a": 1}):
            with self.subTest(bad=bad):
                self.refused({"profile": bad}, "profile")

    def test_unknown_top_level_key_refused(self):  # C8, OQ-16
        for key, value in (("owner", {"handle": "x"}), ("profle", "strict"), ("Paths", {"state": "x"}),
                           ("owner", "someone"), ("", "x"), ("extra key", 1)):
            with self.subTest(key=key):
                self.refused({key: value}, "unknown key '%s'" % key)

    def test_unknown_key_is_escaped_once_in_the_gate_line(self):  # F-1a-fin-3, Q-1a-fin-3
        for extra, text in (({"a\nb": 1}, "a\\nb"), ({"paths": {"x\ny": "z"}}, "paths.x\\ny")):
            with self.subTest(extra=extra):
                cfg = minimal_config()
                cfg.update(extra)
                self.put(cfg)
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    code = run_gate("x", lambda a: config.load(self.root) and Result("x", []), [])
                self.assertEqual(code, 1)
                out = buf.getvalue()
                self.assertEqual(len(out.splitlines()), 1)
                self.assertIn("unknown key '%s'" % text, out)
                self.assertNotIn("\\\\n", out)

    def test_not_yet_landed_keys_accepted_unchecked(self):  # C18
        # Task 4a.3: roles, rulings, dispatch and budgets are typed now (TypedReadersTest); these stay unchecked
        extra = {"commands": {"test": "make test"}, "top_tier_roles": [""], "top_tier_fallback": True}
        cfg = self.with_extra(extra)
        want = copy.deepcopy(EXPECTED)
        want.update(extra)
        self.assertEqual(cfg, want)


class MappingKeysTest(ConfigCase):
    def test_default_mapping_given_non_mapping(self):  # C9
        for key in ("paths", "ids", "decisions", "decision_classes", "models", "drift"):
            for value in ("x", [], None, 1, True, ["a"]):
                with self.subTest(key=key, value=value):
                    self.refused({key: value}, key)
        for value in ("x", [], None, 1):
            with self.subTest(key="models.tiers", value=value):
                self.refused({"models": {"tiers": value}}, "models.tiers")

    def test_unknown_key_inside_read_mapping(self):  # C10, owner Q-1a2-1
        cases = [({"paths": {"stat": "x"}}, "paths.stat"), ({"ids": {"width": 4}}, "ids.width"),
                 ({"decisions": {"foo": 1}}, "decisions.foo"),
                 ({"decision_classes": {"extra": ["a"]}}, "decision_classes.extra"),
                 ({"drift": {"foo": 1}}, "drift.foo"), ({"models": {"foo": 1}}, "models.foo")]
        for extra, name in cases:
            with self.subTest(name=name):
                self.refused(extra, name)

    def test_extra_tier_name_kept(self):
        cfg = self.with_extra({"models": {"tiers": {"tier9": "x"}}})
        self.assertEqual(cfg["models"]["tiers"], {"tier1": "haiku", "tier2": "sonnet", "tier3": "opus",
                                                  "tier9": "x"})


class PathsTest(ConfigCase):
    def test_paths_must_be_relative_normalised(self):  # C11
        for bad in ("/abs", "a/../b", "..", "../a", "./a", "a//b", "a/", "", 1, None, True, ["a"],
                    "a/./b", "a/..", "/", "//x", ".", "./", "a/."):
            with self.subTest(bad=bad):
                self.refused({"paths": {"state": bad}}, "paths.state")

    def test_paths_refuse_non_printable(self):  # C11, owner Q-1a2r-3
        bad = ["a\x00b", "a\nb", "a\tb", "a\rb", "\x01", "a\x1fb", "a\x7fb", "a\x85b", "a\u2028b",
               "a\u200bb", "a\U000e0001b", "\x00"]
        for v in bad:
            with self.subTest(bad=v):
                self.refused({"paths": {"state": v}}, "paths.state")
        for key in EXPECTED["paths"]:
            with self.subTest(key=key):
                self.refused({"paths": {key: "x\x00y"}}, "paths." + key)

    def test_each_paths_key_is_checked(self):
        for key in EXPECTED["paths"]:
            with self.subTest(key=key):
                self.refused({"paths": {key: "/abs"}}, "paths." + key)

    def test_valid_override_replaces_that_key_only(self):
        cfg = self.with_extra({"paths": {"state": "x/y", "plans": "p", "index": "a b/c.md"}})
        self.assertEqual(cfg, expected(paths__state="x/y", paths__plans="p", paths__index="a b/c.md"))
        cfg = self.with_extra({"paths": {"state": "..x", "context": "é/ü.yml"}})
        self.assertEqual(cfg["paths"]["state"], "..x")
        self.assertEqual(cfg["paths"]["context"], "é/ü.yml")


class IdsTest(ConfigCase):
    def test_ids_only_prefixes(self):  # C12, OQ-2
        cfg = self.with_extra({"ids": {"decision": "X"}})
        self.assertEqual(cfg["ids"], {"decision": "X", "finding": "F", "claim": "C", "request": "R"})
        with self.assertRaises(GateError) as e:
            self.with_extra({"ids": {"width": 4}})
        self.assertIn("ids.width", str(e.exception))

    def test_each_prefix_overridden(self):
        for kind in ("decision", "finding", "claim", "request"):
            with self.subTest(kind=kind):
                self.assertEqual(self.with_extra({"ids": {kind: "ZZ"}})["ids"][kind], "ZZ")
        cfg = self.with_extra({"ids": {"decision": "F", "finding": "DEC"}})  # a swap keeps them distinct
        self.assertEqual((cfg["ids"]["decision"], cfg["ids"]["finding"]), ("F", "DEC"))

    def test_bad_prefix_values(self):
        for bad in ("dec", "", "D1", "D-", "A\n", " A", "A ", "É", 1, None, True, ["A"], "a"):
            with self.subTest(bad=bad):
                self.refused({"ids": {"decision": bad}}, "ids.decision")

    def test_shared_prefix_refused(self):  # R-rev5-1
        for ids in ({"decision": "F"}, {"finding": "DEC"}, {"claim": "R"}, {"request": "C"},
                    {"decision": "Q", "claim": "Q"}):
            with self.subTest(ids=ids):
                msg = self.refused({"ids": ids}, "ids")
                self.assertIn("distinct", msg)


class ScalarKeysTest(ConfigCase):
    def test_base_branch(self):  # C13
        for ok in ("main", "develop", "release/1.0"):
            with self.subTest(ok=ok):
                self.assertEqual(self.with_extra({"base_branch": ok})["base_branch"], ok)
        for bad in ("", 1, None, True, ["main"], {"a": 1}):
            with self.subTest(bad=bad):
                self.refused({"base_branch": bad}, "base_branch")

    def test_base_branch_over_long_hex_run(self):  # C13, F-1a2r-6, Q-1a2r-8
        for ok in ("a" * 40, "A" * 40, "release-" + "0" * 40, "x" + "f" * 40 + "-y", "a" * 40 + "/" + "b" * 40, "main", "feat/12345"):
            with self.subTest(ok=ok):
                self.assertEqual(self.with_extra({"base_branch": ok})["base_branch"], ok)
        mixed = "aB" * 20 + "c"
        for bad in ("a" * 41, "F" * 41, mixed, "a" * 60, "release-" + "0" * 41 + "-x", "x" + mixed, mixed + "z"):
            with self.subTest(bad=bad):
                self.refused({"base_branch": bad}, "base_branch", "40 hex digits in a row", "gitinfo")

    def test_decisions_scan(self):  # C14
        self.assertEqual(self.with_extra({"decisions": {"scan": []}})["decisions"]["scan"], [])
        self.assertEqual(self.with_extra({"decisions": {"scan": ["docs/**"]}})["decisions"]["scan"],
                         ["docs/**"])
        for bad in ([""], [1], "docs/**", None, ["a", ""], ["a", None], [["a"]], 1, [True]):
            with self.subTest(bad=bad):
                self.refused({"decisions": {"scan": bad}}, "decisions.scan")

    def test_models_tiers_values(self):  # C16
        self.assertEqual(self.with_extra({"models": {"tiers": {"tier4": "x"}}})["models"]["tiers"]["tier4"],
                         "x")
        cfg = self.with_extra({"models": {"tiers": {"tier2": "other"}}})
        self.assertEqual(cfg["models"]["tiers"], {"tier1": "haiku", "tier2": "other", "tier3": "opus"})
        for tier in ("tier1", "tier2", "tier3", "tier4", "tier9"):
            for bad in ("", 1, None, True, ["x"], {"a": 1}):
                with self.subTest(tier=tier, bad=bad):
                    self.refused({"models": {"tiers": {tier: bad}}}, "models.tiers." + tier)

    def test_drift_estimate_factor(self):  # C17
        for ok in (150, 200, 1, 10 ** 12):
            with self.subTest(ok=ok):
                self.assertEqual(self.with_extra({"drift": {"estimate_factor_pct": ok}})["drift"],
                                 {"estimate_factor_pct": ok})
        for bad in (0, -5, True, False, "1.5", 1.5 if False else "150", None, [150], {"a": 1}):
            with self.subTest(bad=bad):
                self.refused({"drift": {"estimate_factor_pct": bad}}, "drift.estimate_factor_pct")
        self.put_bytes(("schema: %s\nframework_version: '0'\nprofile: strict\n" % TAG).encode("ascii")
                       + b"drift:\n  estimate_factor_pct: 1.5\n")
        with self.assertRaises(GateError) as e:
            config.load(self.root)
        self.assertIn("drift.estimate_factor_pct", str(e.exception))


class OwnerOnlyTest(ConfigCase):
    def test_owner_only_merges_as_union(self):  # C15, Q-plan-1
        cfg = self.with_extra({"decision_classes": {"owner_only": ["hardware"]}})
        self.assertEqual(set(cfg["decision_classes"]["owner_only"]),
                         set(config.DEFAULTS["decision_classes"]["owner_only"]) | {"hardware"})
        self.assertEqual(cfg["decision_classes"]["owner_only"], OWNER_ONLY + ["hardware"])

    def test_union_order_and_no_repeats(self):
        cfg = self.with_extra({"decision_classes": {"owner_only": [
            "hardware", "triage", "zeta", "hardware", "alpha", "program-close"]}})
        self.assertEqual(cfg["decision_classes"]["owner_only"], OWNER_ONLY + ["hardware", "zeta", "alpha"])

    def test_default_restated_and_cannot_drop(self):
        cfg = self.with_extra({"decision_classes": {"owner_only": ["triage"]}})
        self.assertEqual(cfg["decision_classes"]["owner_only"], OWNER_ONLY)
        cfg = self.with_extra({"decision_classes": {"owner_only": ["hardware"]}})
        for slug in OWNER_ONLY:
            self.assertIn(slug, cfg["decision_classes"]["owner_only"])

    def test_absent_gives_defaults(self):
        self.assertEqual(self.with_extra({})["decision_classes"]["owner_only"], OWNER_ONLY)

    def test_owner_only_bad_values(self):
        for bad in ("triage", [], [1], [""], None, [None], [True], ["a", ""], ["a", 1], [["x"]], 5):
            with self.subTest(bad=bad):
                self.refused({"decision_classes": {"owner_only": bad}}, "decision_classes.owner_only")

    def test_empty_decision_classes_mapping_is_not_possible_but_none_is_refused(self):
        self.refused({"decision_classes": None}, "decision_classes")



class RootGuardTest(ConfigCase):
    """Q-1bfin-2 (a): config.load refuses a root that is not the top level before reading anything (C1-C3, O6)."""

    def test_subdirectory_root_refused_everywhere(self):  # T1-T12, T15
        forms = root_forms(self.tmp, self.root)
        check_root_forms(self, forms, {"load": config.load})

    def test_accepted_forms_load_the_same_config(self):  # T3, T5, T9
        for name, path, verdict in root_forms(self.tmp, self.root):
            if verdict == "ok" and name != "nested":
                with self.subTest(form=name):
                    self.assertEqual(config.load(path), EXPECTED)

    def test_subdirectory_of_a_tree_with_a_config_is_not_read_from_the_top_level(self):  # C1
        sub = os.path.join(self.root, "sub")
        os.mkdir(sub)
        with mock.patch("gates.lib.config.yamlsub.load", side_effect=AssertionError("config read")):
            with self.assertRaises(GateError) as e:
                config.load(sub)
        self.assertEqual(str(e.exception), TOP)

    def test_subdirectory_with_its_own_config_is_refused(self):  # C2
        sub = os.path.join(self.root, "sub")
        os.mkdir(sub)
        os.makedirs(os.path.join(sub, ".strict-delivery"))
        with open(os.path.join(sub, ".strict-delivery", "config.yml"), "w", encoding="utf-8") as fh:
            fh.write(emit(minimal_config()))
        with self.assertRaises(GateError) as e:
            config.load(sub)
        self.assertEqual(str(e.exception), TOP)

    def test_root_check_comes_before_the_missing_config_text(self):  # O6
        os.remove(self.path)
        sub = os.path.join(self.root, "sub")
        os.mkdir(sub)
        plain = os.path.join(self.tmp, "plain-nongit")
        os.mkdir(plain)
        for root, want in ((sub, TOP), (plain, E128), (self.root, MISSING)):
            with self.subTest(root=root):
                with self.assertRaises(GateError) as e:
                    config.load(root)
                self.assertEqual(str(e.exception), want)


REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ALL_KEYS_19 = ("schema", "framework_version", "profile", "commands", "paths", "ids", "models", "roles",
               "top_tier_roles", "top_tier_fallback", "decision_classes", "block", "rulings", "dispatch",
               "budgets", "drift", "overrides", "base_branch", "decisions")
DEFAULT_EXCLUDE = [".strict-delivery/**", ".github/workflows/**", ".claude/**", "CLAUDE.md"]
# This repository's list: the four defaults and L:406's categories (plan P:2001), written by hand.
REPO_EXCLUDE = [".strict-delivery/**", ".github/workflows/**", ".claude/**", "CLAUDE.md", "gates/lib/**",
                "gates/schemas/**", "gates/gate_schema.py", "gates/hook.py", "gates/hooks/**", "hooks/**",
                "gates/gate_dispatch.py", "gates/__main__.py", "gates/producers.py", "gates/run_all.py"]
NOT_INT_AT_LEAST_1 = (0, -1, True, False, "2", "2.5", None, [2], {"a": 1})


class Config2Test(ConfigCase):
    """Task 2c.2: limits, merge, escape_cost, reviews and context (rows L, M, E, R, C, D, V)."""

    def raw(self, body):
        """Load a config file made of the minimal config plus the raw text ``body`` (for values emit cannot write)."""
        self.put_bytes(emit(minimal_config()).encode("utf-8") + body.encode("utf-8"))
        return config.load(self.root)

    def refused_raw(self, body, *needles):
        with self.assertRaises(GateError) as e:
            self.raw(body)
        for n in needles:
            self.assertIn(n, str(e.exception))
        return str(e.exception)

    def with_data(self, extra):
        """``config.load`` of the minimal config plus ``extra`` with the parsed document injected: the YAML subset
        cannot write an empty mapping (``emit`` refuses it; ``{}`` is a flow mapping, refused), so the rows that
        hold ``{}`` reach the validator only this way."""
        data = dict(minimal_config(), **extra)
        real = yamlsub.load  # only the config file is replaced: config.load also reads profiles/<p>.yml (Task 4a.2)

        def fake(path, shown):
            return data if shown == config.CONFIG_PATH else real(path, shown)
        with mock.patch.object(yamlsub, "load", side_effect=fake):
            return config.load(self.root)

    def unknown(self, extra, dotted):
        msg = self.refused(extra, "unknown key '%s'" % dotted)
        self.assertEqual(msg, ".strict-delivery/config.yml: unknown key '%s'" % dotted)

    def bad(self, extra, dotted, reason=None):
        msg = self.refused(extra, ".strict-delivery/config.yml: %s: " % dotted)
        if reason is not None:
            self.assertEqual(msg, ".strict-delivery/config.yml: %s: %s" % (dotted, reason))

    # ---- D rows
    def test_config_keys_gain_new_keys(self):  # D2
        self.assertEqual(set(config.CONFIG_KEYS), set(ALL_KEYS_19) | {"limits", "merge", "escape_cost", "reviews",
                                                                      "context"})
        self.assertEqual(len(config.CONFIG_KEYS), 24)

    def test_unknown_top_level_near_misses(self):  # D3
        for key in ("limit", "review", "escape-cost", "Merge"):
            with self.subTest(key=key):
                self.refused({key: 1}, "unknown key '%s'" % key)

    def test_defaults_not_mutated_by_new_keys(self):  # D1
        before = copy.deepcopy(config.DEFAULTS)
        self.with_extra({"reviews": {"small": {"exclude": ["x/**"], "max_lines": 9}}, "merge": {"mode": "controller"},
                         "context": {"max_lines": 5}})
        self.assertEqual(config.DEFAULTS, before)
        self.put(minimal_config())
        cfg = config.load(self.root)
        self.assertEqual(cfg["reviews"], EXPECTED["reviews"])
        self.assertEqual(cfg["merge"], {"mode": "host"})
        cfg["reviews"]["small"]["exclude"].append("mutated")
        cfg["context"]["max_lines"] = 1
        self.assertEqual(config.DEFAULTS, before)
        self.assertEqual(config.DEFAULTS["reviews"]["small"]["exclude"], DEFAULT_EXCLUDE)
        self.assertEqual(config.DEFAULTS["merge"], {"mode": "host"})
        self.assertEqual(config.DEFAULTS["context"], {"max_lines": 2000, "max_bytes": 100000})
        self.assertNotIn("limits", config.DEFAULTS)
        self.assertNotIn("escape_cost", config.DEFAULTS)

    # ---- limits
    def test_no_limits_by_default(self):  # L1, Q-H2
        cfg = config.load(self.root)
        self.assertNotIn("limits", cfg)
        self.assertEqual(cfg.get("limits", {}), {})

    def test_limits_accepted_and_checked(self):  # L2, L3, L4, L6
        cfg = self.with_extra({"limits": {"max_children": {"stream_controller": 4}}})
        self.assertEqual(cfg["limits"]["max_children"]["stream_controller"], 4)
        self.assertEqual(cfg["limits"], {"max_children": {"stream_controller": 4}})
        self.assertEqual(self.with_data({"limits": {}})["limits"], {})  # L2: {} only through injection
        self.assertEqual(self.with_extra({"limits": {"max_children": {"stream_controller": 4}, "max_depth": 3,
                                                     "max_concurrent": 20}})["limits"],
                         {"max_children": {"stream_controller": 4}, "max_depth": 3, "max_concurrent": 20})
        for value in (3, [1], "x", None, True):
            with self.subTest(value=value):
                self.bad({"limits": value}, "limits", "must be a mapping")
        self.unknown({"limits": {"max_kids": 2}}, "limits.max_kids")

    def test_max_children_shape_only(self):  # L5, L7-L11, L14
        """Q-2c2-1 (a): only the shape is checked here. yamlsub gives only ``str`` mapping keys (measured: its
        mapping parser builds keys from scalar text; ``git grep -n 'dict\\[' gates/lib/yamlsub.py`` shows no int key
        path), so no non-str-key path is written."""
        mc = lambda v: {"limits": {"max_children": v}}  # noqa: E731
        for value in (3, ["a"], "x", None, True):
            with self.subTest(value=value):
                self.bad(mc(value), "limits.max_children", "must be a mapping")
        self.assertEqual(self.with_extra(mc({"implementor": 2}))["limits"]["max_children"], {"implementor": 2})
        self.assertEqual(self.with_extra(mc({"session": 1}))["limits"]["max_children"], {"session": 1})
        self.assertEqual(self.with_data(mc({}))["limits"], {"max_children": {}})
        self.bad(mc({"": 2}), "limits.max_children", "keys must be non-empty strings")
        for bad in NOT_INT_AT_LEAST_1:
            with self.subTest(bad=bad):
                self.bad(mc({"stream_controller": bad}), "limits.max_children.stream_controller",
                         "must be an integer of at least 1")
        self.assertEqual(self.with_extra(mc({"a": 1, "b": 2}))["limits"]["max_children"], {"a": 1, "b": 2})
        big = "9" * 600                                  # the 600-digit cap (I6); 601 or more is refused, tested above
        self.assertEqual(self.raw("limits:\n  max_children:\n    a: %s\n" % big)["limits"]["max_children"],
                         {"a": int(big)})

    def test_limits_depth_concurrent_checked(self):  # L12, L13
        for key in ("max_depth", "max_concurrent"):
            self.assertNotIn(key, self.with_data({"limits": {}})["limits"])
            for ok in (1, 5):
                with self.subTest(key=key, ok=ok):
                    self.assertEqual(self.with_extra({"limits": {key: ok}})["limits"], {key: ok})
            big = "9" * 600                              # the 600-digit cap (I6); 601 or more is refused, tested above
            self.assertEqual(self.raw("limits:\n  %s: %s\n" % (key, big))["limits"], {key: int(big)})
            for bad in NOT_INT_AT_LEAST_1:
                with self.subTest(key=key, bad=bad):
                    self.bad({"limits": {key: bad}}, "limits." + key, "must be an integer of at least 1")

    # ---- merge
    def test_merge_mode_default_and_checked(self):  # M1-M6
        self.assertEqual(config.load(self.root)["merge"]["mode"], "host")
        for mode in ("controller", "host"):
            with self.subTest(mode=mode):
                self.assertEqual(self.with_extra({"merge": {"mode": mode}})["merge"], {"mode": mode})
        for bad in ("auto", "Host", "", 1, True, None, ["host"]):
            with self.subTest(bad=bad):
                self.bad({"merge": {"mode": bad}}, "merge.mode", "must be one of host, controller")
        for value in ("host", ["mode"], 1, None, True):
            with self.subTest(value=value):
                self.bad({"merge": value}, "merge", "must be a mapping")
        self.unknown({"merge": {"mode": "host", "by": "me"}}, "merge.by")
        self.assertEqual(self.with_data({"merge": {}})["merge"], {"mode": "host"})

    # ---- escape_cost
    def test_escape_cost_optional_and_checked(self):  # E1-E7
        sev = ("CRITICAL", "HIGH", "MEDIUM", "LOW")
        self.assertNotIn("escape_cost", config.load(self.root))
        for given in ({"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0},
                      {"CRITICAL": 8, "HIGH": 4, "MEDIUM": 2, "LOW": 1}):
            with self.subTest(given=given):
                self.assertEqual(self.with_extra({"escape_cost": given})["escape_cost"], given)
        full = {"CRITICAL": 8, "HIGH": 4, "MEDIUM": 2, "LOW": 1}
        for left_out in sev:
            with self.subTest(left_out=left_out):
                self.bad({"escape_cost": {k: v for k, v in full.items() if k != left_out}},
                         "escape_cost." + left_out, "required key is missing")
        self.unknown({"escape_cost": dict(full, INFO=1)}, "escape_cost.INFO")
        self.unknown({"escape_cost": dict(full, critical=1)}, "escape_cost.critical")
        for s in sev:
            for bad in (-1, True, False, "2", None, [1]):
                with self.subTest(sev=s, bad=bad):
                    self.bad({"escape_cost": dict(full, **{s: bad})}, "escape_cost." + s,
                             "must be an integer of at least 0")
        for value in (3, ["a"], "x", None):
            with self.subTest(value=value):
                self.bad({"escape_cost": value}, "escape_cost", "must be a mapping")
        with self.assertRaises(GateError) as e:
            self.with_data({"escape_cost": {}})
        self.assertEqual(str(e.exception), ".strict-delivery/config.yml: escape_cost.CRITICAL: required key is missing")

    # ---- reviews
    def test_reviews_small_defaults_and_checked(self):  # R1-R5, R12, R13
        cfg = config.load(self.root)
        self.assertEqual(cfg["reviews"], {"small": {
            "max_lines": 150, "max_files": 4, "exclude": [".strict-delivery/**", ".github/workflows/**", ".claude/**",
                                                         "CLAUDE.md"], "tier": "tier2"}})
        got = self.with_extra({"reviews": {"small": {"max_lines": 10}}})["reviews"]["small"]
        self.assertEqual(got, {"max_lines": 10, "max_files": 4, "exclude": DEFAULT_EXCLUDE, "tier": "tier2"})
        for extra in ({"reviews": {}}, {"reviews": {"small": {}}}):
            with self.subTest(extra=extra):
                self.assertEqual(self.with_data(extra)["reviews"], EXPECTED["reviews"])
        self.assertEqual(self.with_extra({"reviews": {"small": {"max_files": 1}}})["reviews"]["small"]["max_files"], 1)
        for key in ("max_lines", "max_files"):
            for bad in (0, -1, True, False, "4", "1.5", None):
                with self.subTest(key=key, bad=bad):
                    self.bad({"reviews": {"small": {key: bad}}}, "reviews.small." + key,
                             "must be an integer of at least 1")
        self.unknown({"reviews": {"extra": 1}}, "reviews.extra")
        self.unknown({"reviews": {"small": {"extra": 1}}}, "reviews.small.extra")
        for value in (1, ["a"], "x", None):
            with self.subTest(value=value):
                self.bad({"reviews": value}, "reviews", "must be a mapping")
        for value in (1, ["a"], "x", None):
            with self.subTest(small=value):
                self.bad({"reviews": {"small": value}}, "reviews.small", "must be a mapping")

    def test_reviews_small_exclude_checked(self):  # R6-R9
        ex = lambda v: {"reviews": {"small": {"exclude": v}}}  # noqa: E731
        for value in ("x", 3, {"a": "b"}, None):
            with self.subTest(value=value):
                self.bad(ex(value), "reviews.small.exclude")
        for item in ("", 3, None, "../x", "a/../x", "/x", ".", "./x", "a//b", "a\x07b", "[z-a]", "a/.", "x/"):
            with self.subTest(item=item):
                self.bad(ex([item]), "reviews.small.exclude")
        self.assertEqual(self.with_extra(ex([]))["reviews"]["small"]["exclude"], [])
        self.assertEqual(self.with_extra(ex(["docs/**"]))["reviews"]["small"]["exclude"], ["docs/**"])
        self.assertEqual(self.with_extra(ex(["a/*.py", "[ab]c", "CLAUDE.md"]))["reviews"]["small"]["exclude"],
                         ["a/*.py", "[ab]c", "CLAUDE.md"])

    def test_reviews_small_tier_checked(self):  # R10, R11
        for tier in ("tier1", "tier2", "tier3", "tier4"):
            with self.subTest(tier=tier):
                self.assertEqual(self.with_extra({"reviews": {"small": {"tier": tier}}})["reviews"]["small"]["tier"],
                                 tier)
        for bad in ("tier5", "tier0", 2, "Tier2", "", True, None):
            with self.subTest(bad=bad):
                self.bad({"reviews": {"small": {"tier": bad}}}, "reviews.small.tier",
                         "must be one of tier1, tier2, tier3, tier4")

    # ---- context
    def test_context_split_keys_checked(self):  # C1-C6
        self.assertEqual(config.load(self.root)["context"], {"max_lines": 2000, "max_bytes": 100000})
        self.assertEqual(self.with_extra({"context": {"max_lines": 50}})["context"],
                         {"max_lines": 50, "max_bytes": 100000})
        self.assertEqual(self.with_extra({"context": {"max_bytes": 7}})["context"],
                         {"max_lines": 2000, "max_bytes": 7})
        for key in ("max_lines", "max_bytes"):
            for bad in (0, -1, True, False, "9", None):
                with self.subTest(key=key, bad=bad):
                    self.bad({"context": {key: bad}}, "context." + key, "must be an integer of at least 1")
        self.unknown({"context": {"extra": 1}}, "context.extra")
        for value in (1, ["a"], "x"):
            with self.subTest(value=value):
                self.bad({"context": value}, "context", "must be a mapping")
        cfg = self.with_extra({"paths": {"context": "x/c.yml"}, "context": {"max_lines": 3}})
        self.assertEqual((cfg["paths"]["context"], cfg["context"]["max_lines"]), ("x/c.yml", 3))
        # paths.context alone leaves the top-level context at its defaults
        self.assertEqual(self.with_extra({"paths": {"context": "x/c.yml"}})["context"],
                         {"max_lines": 2000, "max_bytes": 100000})

    # ---- this repository
    def test_repo_config_excludes(self):  # G5: this repository's reviews.small.exclude, plan P:2001
        cfg = config.load(REPO)
        self.assertEqual(cfg["reviews"]["small"]["exclude"], REPO_EXCLUDE)
        self.assertEqual(len(REPO_EXCLUDE), 14)
        self.assertEqual(cfg["schema"], TAG)

    # ---- version rows
    def test_new_int_keys_digit_limits(self):  # I6, K1 (G1-G4 class): 600 digits accepted, 601 or more refused
        """One cap of 600 digits on every integer key config/2 reads, whatever PYTHONINTMAXSTRDIGITS is. Texts of 601
        to 1000 digits reach the key check when the interpreter converts them and name the key; under the limit 640
        yamlsub's own conversion refuses texts of 641 or more digits first, and texts of 1001 or more digits are always
        refused there (yamlsub.MAX_INT_CHARS): a GateError either way, never the interpreter's own message."""
        cases = (("limits.max_depth", "limits:\n  max_depth: %s\n", lambda c: c["limits"]["max_depth"]),
                 ("limits.max_concurrent", "limits:\n  max_concurrent: %s\n", lambda c: c["limits"]["max_concurrent"]),
                 ("limits.max_children.controller", "limits:\n  max_children:\n    controller: %s\n",
                  lambda c: c["limits"]["max_children"]["controller"]),
                 ("escape_cost.LOW", "escape_cost:\n  CRITICAL: 1\n  HIGH: 1\n  MEDIUM: 1\n  LOW: %s\n",
                  lambda c: c["escape_cost"]["LOW"]),
                 ("escape_cost.CRITICAL", "escape_cost:\n  CRITICAL: %s\n  HIGH: 1\n  MEDIUM: 1\n  LOW: 1\n",
                  lambda c: c["escape_cost"]["CRITICAL"]),
                 ("reviews.small.max_lines", "reviews:\n  small:\n    max_lines: %s\n",
                  lambda c: c["reviews"]["small"]["max_lines"]),
                 ("reviews.small.max_files", "reviews:\n  small:\n    max_files: %s\n",
                  lambda c: c["reviews"]["small"]["max_files"]),
                 ("context.max_lines", "context:\n  max_lines: %s\n", lambda c: c["context"]["max_lines"]),
                 ("context.max_bytes", "context:\n  max_bytes: %s\n", lambda c: c["context"]["max_bytes"]))
        too_large = r"\A\.strict-delivery/config\.yml: integer too large \(line [0-9]+\)\Z"
        for lim in INT_LIMITS:
            with int_limit(lim):
                for key, template, get in cases:
                    for digits in (600, 601, 1000, 1001, 4300, 4301):
                        with self.subTest(limit=lim, key=key, digits=digits):
                            body = template % ("7" * digits)
                            if digits == 600:
                                self.assertEqual(get(self.raw(body)), int("7" * digits))
                            elif digits > 1000 or (lim == 640 and digits > 640):
                                self.assertRegex(self.refused_raw(body), too_large)
                            else:
                                self.assertEqual(self.refused_raw(body),
                                                 ".strict-delivery/config.yml: %s: must be an integer of at most 600 "
                                                 "digits" % key)

    def test_new_int_keys_non_ascii_digits(self):  # K2: no isdigit/isdecimal decides; U+1FAE8 is So on 3.13, Cn on 3.9
        for lim in INT_LIMITS:
            with int_limit(lim):
                for text in ("٥", "５", "\U0001FAE8", "5٥"):
                    with self.subTest(limit=lim, text=text):
                        self.assertEqual(self.refused_raw("limits:\n  max_depth: %s\n" % text),
                                         ".strict-delivery/config.yml: limits.max_depth: must be an integer of at "
                                         "least 1")

    def test_new_int_keys_digit_cap_no_conversion(self):  # I6: the cap reads the number without str() or int() of text
        for lim in INT_LIMITS:
            with int_limit(lim):
                for key, data in (("limits.max_depth", {"limits": {"max_depth": 10 ** 600}}),
                                  ("escape_cost.HIGH", {"escape_cost": {"CRITICAL": 1, "HIGH": 10 ** 700,
                                                                        "MEDIUM": 1, "LOW": 1}})):
                    with self.subTest(limit=lim, key=key):
                        with self.assertRaises(GateError) as e:
                            self.with_data(data)
                        self.assertEqual(str(e.exception), ".strict-delivery/config.yml: %s: must be an integer of at "
                                         "most 600 digits" % key)
                with self.subTest(limit=lim, key="largest accepted"):
                    self.assertEqual(self.with_data({"limits": {"max_depth": 10 ** 600 - 1}})["limits"]["max_depth"],
                                     10 ** 600 - 1)

    def test_new_keys_unicode_version_independent(self):  # V2, PC1 skeleton row
        """Measured on 3.9 (Unicode 13) and 3.13: yamlsub accepts a key holding U+0870 (assigned in Unicode 14) and
        one holding U+1FAE8 (assigned in 15), written plain, quoted or as a ``\\u`` escape, with the same verdict on
        both interpreters. The table row expected U+0870 refused; the measured verdict is accepted (reported)."""
        astral = "\U0001FAE8"
        cfg = self.raw('limits:\n  max_children:\n    "%s": 2\n' % astral)
        self.assertEqual(cfg["limits"]["max_children"], {astral: 2})
        for text in ('"a\\u0870"', "a\u0870", '"a\u0870"'):
            with self.subTest(text=text):
                cfg = self.raw("limits:\n  max_children:\n    %s: 2\n" % text)
                self.assertEqual(cfg["limits"]["max_children"], {"a\u0870": 2})

    def test_exception_groups_propagate(self):  # V3, PC1 skeleton row
        import builtins
        beg = getattr(builtins, "BaseExceptionGroup", None)
        eg = getattr(builtins, "ExceptionGroup", None)
        if beg is None:
            self.skipTest("BaseExceptionGroup is absent on this interpreter (3.9)")
        for exc in (beg("x", [KeyboardInterrupt()]), eg("x", [ValueError()])):
            with self.subTest(exc=type(exc).__name__):
                with mock.patch.object(yamlsub, "load", side_effect=exc):
                    with self.assertRaises(beg) as cm:
                        config.load(self.root)
                self.assertIs(cm.exception, exc)


PFX = ".strict-delivery/config.yml: "
GRAMMAR = "keys must be role ids of [a-z][a-z0-9_]*"
INT1 = "must be an integer of at least 1"
DIG = "must be an integer of at most 600 digits"
PROMPT_REASON = "must be a normalised repo-relative path ending in .md"
TIER_REASON = "must be one of tier1, tier2, tier3, tier4"
ENTRY = {"prompt": "p.md", "min_tier": "tier2"}
DEC_ID = "DEC-20261111-abcd"
FRAMEWORK_ROLES = ("program_controller", "stream_controller", "controller", "implementer",
                   "implementer_transcription", "task_reviewer", "final_reviewer", "final_verifier",
                   "exception_reviewer", "audit_reviewer", "audit_verifier", "investigator", "plan_writer",
                   "plan_reviewer", "drafter")
FIVE = ("roles", "budgets", "block", "rulings", "dispatch")
LEAF = {"block": "max_tasks", "rulings": "max_per_block", "dispatch": "max_prompt_chars"}
VALID_ALL = {"roles": {"doc_writer": {"prompt": "playbooks/doc.md", "min_tier": "tier2"}},
             "budgets": {"controller": {"tokens": 5000, "minutes": 30}},
             "block": {"max_tasks": 4}, "rulings": {"max_per_block": 2}, "dispatch": {"max_prompt_chars": 20000}}


class SubStr(str):
    pass


class SubDict(dict):
    pass


class TypedReadersTest(ConfigCase):
    """Task 4a.3: the typed readers of roles, budgets, block, rulings and dispatch; rows K, RO, RE, RP, RT, BU, BL, ER,
    IX, V of .superpowers/sdd/2026-10-31-strict-delivery-framework/task-4a.3-domain.md. Every expected value is written
    by hand from the plan (P:4323-4336) and the table's binding decisions."""

    def light(self, extra):
        return dict({"profile": "light"}, **extra)

    def ok(self, extra):
        return self.with_extra(self.light(extra))

    def raw(self, body, profile="light"):
        self.put_bytes(emit(dict(minimal_config(), profile=profile)).encode("utf-8") + body.encode("utf-8"))
        return config.load(self.root)

    def raw_refused(self, body, profile="light"):
        with self.assertRaises(GateError) as e:
            self.raw(body, profile)
        return str(e.exception)

    def inj(self, extra, profile="light"):
        """config.load with the parsed document injected (the YAML subset cannot write ``{}`` or a non-str key)."""
        data = dict(minimal_config(), profile=profile, **extra)
        real = yamlsub.load

        def fake(path, shown):
            return copy.deepcopy(data) if shown == config.CONFIG_PATH else real(path, shown)
        with mock.patch.object(yamlsub, "load", side_effect=fake):
            return config.load(self.root)

    def inj_refused(self, extra, profile="light"):
        with self.assertRaises(GateError) as e:
            self.inj(extra, profile)
        return str(e.exception)

    def bad(self, extra, key, reason):
        msg = self.refused(self.light(extra))
        self.assertEqual(msg, "%s%s: %s" % (PFX, key, reason))

    def unknown(self, extra, dotted):
        msg = self.refused(self.light(extra))
        self.assertEqual(msg, "%sunknown key '%s'" % (PFX, dotted))

    def injected_bad(self, extra, text):
        self.assertEqual(self.inj_refused(extra), PFX + text)

    def roles(self, key, entry=None):
        return {"roles": {key: dict(ENTRY) if entry is None else entry}}

    def prompt(self, p):
        return self.roles("x", {"prompt": p, "min_tier": "tier2"})

    def prompt_refused(self, p):
        msg = self.refused(self.light(self.prompt(p)))
        self.assertTrue(msg.startswith(PFX + "roles.x.prompt: must be a "), msg)
        self.assertEqual(len(msg.splitlines()), 1)
        return msg

    # ---- K rows
    def test_five_keys_absent_by_default(self):  # K1
        for p, block in (("light", None), ("standard", {"max_tasks": 5}), ("strict", {"max_tasks": 3})):
            with self.subTest(profile=p):
                cfg = self.with_extra({"profile": p})
                for k in ("roles", "budgets", "rulings", "dispatch"):
                    self.assertNotIn(k, cfg)
                self.assertEqual(cfg.get("block"), block)
        for k in FIVE:
            self.assertNotIn(k, config.DEFAULTS)

    def test_five_keys_empty_mapping_accepted(self):  # K2, BL9, BU5
        for k in FIVE:
            with self.subTest(key=k):
                self.assertEqual(self.inj({k: {}})[k], {})
        self.assertEqual(self.inj({"block": {}}, "strict")["block"], {"max_tasks": 3})
        self.assertEqual(self.inj({"budgets": {"controller": {}}})["budgets"], {"controller": {}})

    def test_five_keys_not_a_mapping(self):  # K3
        for k in FIVE:
            for v in (None, 5, True, "x", "", [], ["a"], [{"a": 1}]):
                with self.subTest(key=k, value=v):
                    self.bad({k: v}, k, "must be a mapping")

    def test_block_not_a_mapping_any_profile(self):  # BL3, IX3: the same text for every profile
        for p in ("light", "standard", "strict"):
            for v in ([1, 2], 5, "x", None, True):
                with self.subTest(profile=p, value=v):
                    msg = self.refused({"profile": p, "block": v})
                    self.assertEqual(msg, PFX + "block: must be a mapping")

    def test_five_keys_exact_dict_only(self):  # K4
        import collections
        for k in FIVE:
            for v in (SubStr("x"), collections.OrderedDict(), SubDict(), collections.OrderedDict(a=1)):
                with self.subTest(key=k, value=type(v).__name__):
                    self.injected_bad({k: v}, "%s: must be a mapping" % k)

    def test_five_keys_unknown_subkey(self):  # K5, BL8
        for extra, dotted in (({"block": {"max_task": 3}}, "block.max_task"),
                              ({"block": {"Max_tasks": 3}}, "block.Max_tasks"),
                              ({"block": {"other": 1}}, "block.other"),
                              ({"block": {"max_tasks": 3, "other": 1}}, "block.other"),
                              ({"rulings": {"max": 1}}, "rulings.max"),
                              ({"rulings": {"x": 1}}, "rulings.x"),
                              ({"dispatch": {"max_prompt_char": 1}}, "dispatch.max_prompt_char"),
                              ({"dispatch": {"x": 1}}, "dispatch.x")):
            with self.subTest(extra=extra):
                self.unknown(extra, dotted)

    def test_block_unknown_subkey(self):  # BL8, ST9: 4a.2 accepted these before this reader
        self.assertEqual(self.refused({"profile": "light", "block": {"other": 1}}),
                         PFX + "unknown key 'block.other'")
        self.assertEqual(self.refused({"profile": "light", "block": {"Max_tasks": 4}}),
                         PFX + "unknown key 'block.Max_tasks'")
        for p in ("strict", "standard"):  # step 3 does not see 'other'; the reader refuses it after the merge
            with self.subTest(profile=p):
                self.assertEqual(self.refused({"profile": p, "block": {"other": 1}}),
                                 PFX + "unknown key 'block.other'")

    def test_five_keys_case_variants_unknown_top_level(self):  # K6
        for k in ("Roles", "ROLES", "Block", "block ", "roles.x", "block.max_tasks", "Budgets", "rulings ", "Dispatch"):
            with self.subTest(key=k):
                self.assertEqual(self.refused({"profile": "light", k: {"a": 1}}), "%sunknown key '%s'" % (PFX, k))

    def test_five_keys_int_value_wrong_shape(self):  # K7
        for k, leaf in LEAF.items():
            for v in ({"n": 3}, [1], {"a": 1}):
                with self.subTest(key=k, value=v):
                    self.bad({k: {leaf: v}}, "%s.%s" % (k, leaf), INT1)

    def test_five_keys_check_order(self):  # K8, D5: roles, budgets, block, rulings, dispatch
        self.bad({"roles": 5, "block": [1], "dispatch": 5}, "roles", "must be a mapping")
        self.bad({"roles": 5, "budgets": 5}, "roles", "must be a mapping")
        self.bad({"budgets": 5, "block": [1], "dispatch": 5}, "budgets", "must be a mapping")
        self.bad({"block": [1], "rulings": 5, "dispatch": 5}, "block", "must be a mapping")
        self.bad({"rulings": 5, "dispatch": 5}, "rulings", "must be a mapping")
        self.bad({"dispatch": 5}, "dispatch", "must be a mapping")
        for _ in range(2):  # ER9: the same text twice
            self.bad({"roles": 5, "block": [1]}, "roles", "must be a mapping")

    def test_roles_shape_accepted(self):  # K9, planned Step 1
        cfg = self.ok({"roles": {"doc_writer": {"prompt": "playbooks/doc.md", "min_tier": "tier2"}}})
        self.assertEqual(cfg["roles"]["doc_writer"]["min_tier"], "tier2")
        self.assertEqual(cfg["roles"], {"doc_writer": {"prompt": "playbooks/doc.md", "min_tier": "tier2"}})

    def test_all_five_keys_valid_light(self):  # K9
        cfg = self.ok(VALID_ALL)
        for k in FIVE:
            self.assertEqual(cfg[k], VALID_ALL[k])

    def test_five_keys_not_aliased(self):  # K10
        a = self.ok(VALID_ALL)
        a["roles"]["doc_writer"]["prompt"] = "mutated.md"
        a["budgets"]["controller"]["tokens"] = 1
        b = self.ok(VALID_ALL)
        self.assertEqual(b["roles"]["doc_writer"]["prompt"], "playbooks/doc.md")
        self.assertEqual(b["budgets"]["controller"]["tokens"], 5000)
        for k in FIVE:
            self.assertNotIn(k, config.DEFAULTS)

    def test_five_keys_values_unchanged_by_validation(self):  # K11, RO14
        extra = {"roles": {"zeta": dict(ENTRY), "alpha": {"min_tier": "tier3", "prompt": "a/b.md"}},
                 "budgets": {"plan_writer": {"minutes": 3, "tokens": 5}, "controller": {"tokens": 7}}}
        cfg = self.ok(extra)
        self.assertEqual(list(cfg["roles"]), ["zeta", "alpha"])
        self.assertEqual(list(cfg["roles"]["alpha"]), ["min_tier", "prompt"])
        self.assertEqual(list(cfg["budgets"]), ["plan_writer", "controller"])
        self.assertEqual(cfg["roles"], extra["roles"])
        self.assertEqual(cfg["budgets"], extra["budgets"])

    # ---- RO rows
    def test_roles_id_accepted(self):  # RO1, RO2, RO15, RO10
        for key in ("x", "doc_writer", "a1", "x_", "a_b_c", "a" + "b" * 199, "a" * 5000, "a" * 100000,
                    "session", "program_controller"):
            with self.subTest(key=key[:20], n=len(key)):
                self.assertEqual(list(self.ok(self.roles(key))["roles"]), [key])

    def test_roles_framework_id_shape_passes(self):  # RO2: config does not know dispatch.ROLES; gate_dispatch refuses
        for key in FRAMEWORK_ROLES:
            with self.subTest(key=key):
                self.assertIn(key, self.ok(self.roles(key))["roles"])

    def test_roles_id_refusals(self):  # RO3-RO7
        for key in ("X", "Doc_writer", "xY", "DOC", "1x", "_x", "9", "_", "a-b", "a.b", "a b", "a/b", "a:b", "x!",
                    "x,y", "", " x", "x ", "x\t"):
            with self.subTest(key=key):
                self.assertEqual(self.refused(self.light(self.roles(key))), "%sroles: %s" % (PFX, GRAMMAR))

    def test_roles_id_newline_nul_refused(self):  # RO8: re.match(...$) would accept "x\n"
        for key in ("x\n", "x\r", "x\x00", "\ufeffx", "x\u2028", "\nx"):
            with self.subTest(key=key):
                msg = self.refused(self.light(self.roles(key)))
                self.assertEqual(msg, "%sroles: %s" % (PFX, GRAMMAR))
                self.assertEqual(len(msg.splitlines()), 1)

    def test_roles_id_non_ascii_refused(self):  # RO9
        for key in ("\u00e9", "x\u00e9", "\uff58", "k\u212a", "\u0131", "\u0445", "\ua7c0", "\U0001fae8", "x\u0661"):
            with self.subTest(key=key):
                self.assertEqual(self.refused(self.light(self.roles(key))), "%sroles: %s" % (PFX, GRAMMAR))

    def test_roles_non_str_id_injected(self):  # RO11, RO12
        for key in (1, None, True, ("a",), SubStr("x")):
            with self.subTest(key=repr(key)):
                self.injected_bad({"roles": {key: dict(ENTRY)}}, "roles: " + GRAMMAR)

    def test_roles_duplicate_id(self):  # RO13
        msg = self.raw_refused("roles:\n  x:\n    prompt: a.md\n    min_tier: tier2\n  x:\n    prompt: b.md\n"
                               "    min_tier: tier2\n")
        self.assertIn("duplicate key 'x'", msg)

    def test_roles_many_ids(self):  # RO16
        roles = {"r%d" % i: dict(ENTRY) for i in range(1000)}
        self.assertEqual(len(self.ok({"roles": roles})["roles"]), 1000)

    # ---- RE rows
    def test_roles_entry_not_a_mapping(self):  # RE1
        for v in (None, 5, "p.md", ["p.md"], True):
            with self.subTest(value=v):
                self.assertEqual(self.refused(self.light({"roles": {"x": v}})), PFX + "roles.x: must be a mapping")
        self.injected_bad({"roles": {"x": SubDict(ENTRY)}}, "roles.x: must be a mapping")

    def test_roles_entry_empty(self):  # RE2: D-Q2 (A) both keys required
        self.injected_bad({"roles": {"x": {}}}, "roles.x.prompt: required key is missing")

    def test_roles_entry_missing_key(self):  # RE3
        self.bad({"roles": {"x": {"min_tier": "tier2"}}}, "roles.x.prompt", "required key is missing")
        self.bad({"roles": {"x": {"prompt": "p.md"}}}, "roles.x.min_tier", "required key is missing")

    def test_roles_entry_unknown_key(self):  # RE4
        for extra in ({"extra": 1}, {"Prompt": "x"}, {"model": "opus"}):
            with self.subTest(extra=extra):
                self.unknown({"roles": {"x": dict(ENTRY, **extra)}}, "roles.x." + list(extra)[0])
        self.unknown({"roles": {"x": {"prompts": "p.md", "min_tier": "tier2"}}}, "roles.x.prompts")

    def test_roles_entry_check_order(self):  # RE5, D5: unknown key first, then values; prompt before min_tier
        self.unknown({"roles": {"x": {"prompt": "p.txt", "extra": 1, "min_tier": "tier9"}}}, "roles.x.extra")
        self.bad({"roles": {"x": {"prompt": "p.txt", "min_tier": "tier9"}}}, "roles.x.prompt", PROMPT_REASON)

    def test_roles_same_prompt_two_ids(self):  # RE6
        cfg = self.ok({"roles": {"a": dict(ENTRY), "b": dict(ENTRY)}})
        self.assertEqual(cfg["roles"]["a"], cfg["roles"]["b"])

    # ---- RP rows
    def test_roles_prompt_accepted(self):  # RP1, RP11, RP15, RP17
        for p in ("p.md", "a/b/c.md", "playbooks/doc_writer.md", ".strict-delivery/prompts/x.md", "P.md",
                  "\u00e9.md", "p\u0301.md", "\u65e5\u672c.md", "missing/none.md", "x" * 5000 + ".md",
                  "x" * 100000 + ".md", "a/.hidden.md", "p.md.md"):
            with self.subTest(prompt=p[:30], n=len(p)):
                self.assertEqual(self.ok(self.prompt(p))["roles"]["x"]["prompt"], p)

    def test_roles_prompt_refusals(self):  # RP2-RP6, RP8: the plan's values and the normalisation sweep
        for p in ("../p.md", "a/../b.md", "a/..", "..", "/p.md", "/", "//p.md", "a//b.md", "p.txt", "p", "p.md.txt",
                  "p.markdown", "md", "p.md ", "p.md\n", "", "./p.md", "a/./b.md", "p.md/", "a/b/../c.md", "a/b/./",
                  "."):
            with self.subTest(prompt=p):
                self.prompt_refused(p)

    def test_roles_prompt_suffix_case(self):  # RP7
        for p in ("p.MD", "p.Md", "p.mD"):
            with self.subTest(prompt=p):
                self.bad(self.prompt(p), "roles.x.prompt", PROMPT_REASON)

    def test_roles_prompt_suffix_message(self):  # RP5: the exact wording for a clean path with a wrong suffix
        for p in ("p.txt", "p", "p.markdown", "md"):
            with self.subTest(prompt=p):
                self.bad(self.prompt(p), "roles.x.prompt", PROMPT_REASON)

    def test_roles_prompt_backslash(self):  # RP9, D-Q4 (B)
        for p in ("a\\b.md", "\\p.md", "a\\\\b.md", "p\\.md"):
            with self.subTest(prompt=p):
                self.bad(self.prompt(p), "roles.x.prompt", PROMPT_REASON)

    def test_roles_prompt_control_chars(self):  # RP10
        for p in ("a\x00b.md", "a\nb.md", "a\rb.md", "a\tb.md", "\x7f.md", "\u0085.md"):
            with self.subTest(prompt=p):
                self.assertNotIn(p, self.prompt_refused(p))

    def test_roles_prompt_non_ascii(self):  # RP11: printable non-ASCII stays accepted (D-Q4 (B)); NBSP is a space
        for p in ("\u00e9.md", "\u65e5\u672c.md"):
            with self.subTest(prompt=p):
                self.assertIn("x", self.ok(self.prompt(p))["roles"])
        for p in ("\u00a0p.md", "p\u00a0.md", "\u3000p.md"):
            with self.subTest(prompt=p):
                self.prompt_refused(p)

    def test_roles_prompt_unicode_table_frozen(self):  # RP12, V2: the frozen table decides, on both interpreters
        for p in ("\ua7c0.md", "\U0001fae8.md"):
            with self.subTest(prompt=p):
                msg = self.refused(self.light(self.prompt(p)))
                self.assertEqual(msg, PFX + "roles.x.prompt: must be a non-empty normalised repo-relative path of "
                                 "printable characters")

    def test_roles_prompt_dot_md_only(self):  # RP13, D-Q4 (B)
        for p in (".md", "a/.md", "a/b/.md"):
            with self.subTest(prompt=p):
                self.bad(self.prompt(p), "roles.x.prompt", PROMPT_REASON)

    def test_roles_prompt_whitespace(self):  # RP14, D-Q4 (B): any space
        for p in (" p.md", "p .md", "a b/c.md", "a/ b.md", "p.md ", "\tp.md"):
            with self.subTest(prompt=p):
                self.prompt_refused(p)

    def test_roles_prompt_length(self):  # RP15, D-Q3 (A): no cap
        for n in (5000, 100000):
            with self.subTest(n=n):
                p = "x" * n + ".md"
                self.assertEqual(self.ok(self.prompt(p))["roles"]["x"]["prompt"], p)

    def test_roles_prompt_wrong_type(self):  # RP16
        for p in (5, True, None, ["p.md"], {"a": "b"}):
            with self.subTest(prompt=p):
                self.prompt_refused(p)
        msg = self.inj_refused(self.prompt(SubStr("p.md")))
        self.assertTrue(msg.startswith(PFX + "roles.x.prompt: must be a "), msg)

    def test_roles_prompt_existence_not_checked(self):  # RP17
        cfg = self.ok(self.prompt("missing/none.md"))
        self.assertEqual(cfg["roles"]["x"]["prompt"], "missing/none.md")
        self.assertFalse(os.path.exists(os.path.join(self.root, "missing")))

    # ---- RT rows
    def test_roles_min_tier_each_accepted(self):  # RT1
        for t in ("tier1", "tier2", "tier3", "tier4"):
            with self.subTest(tier=t):
                self.assertEqual(self.ok(self.roles("x", {"prompt": "p.md", "min_tier": t}))["roles"]["x"]["min_tier"],
                                 t)

    def test_roles_min_tier_tier4_without_model(self):  # RT9
        cfg = self.ok(self.roles("x", {"prompt": "p.md", "min_tier": "tier4"}))
        self.assertNotIn("tier4", cfg["models"]["tiers"])
        self.assertEqual(cfg["roles"]["x"]["min_tier"], "tier4")

    def test_roles_min_tier_refusals(self):  # RT2-RT5, RT7, RT8
        for t in ("tier5", "tier0", "tier10", "tier01", 3, "3", 1, True, None, "Tier2", "TIER2", "tier 2", "tier2 ",
                  " tier2", "tier2\n", "tier-2", "t2", ["tier2"], {"a": "tier2"}, "opus", "sonnet",
                  "claude-sonnet-5-5", ""):
            with self.subTest(tier=t):
                self.bad(self.roles("x", {"prompt": "p.md", "min_tier": t}), "roles.x.min_tier", TIER_REASON)

    def test_roles_min_tier_non_ascii(self):  # RT6
        for t in ("tier\u0662", "tier\uff12", "t\u0131er2", "tier2\u00a0"):
            with self.subTest(tier=t):
                self.bad(self.roles("x", {"prompt": "p.md", "min_tier": t}), "roles.x.min_tier", TIER_REASON)

    def test_roles_min_tier_float_and_str_subclass(self):  # RT3: 3.0 (injected), a str subclass of a valid tier
        self.injected_bad({"roles": {"x": {"prompt": "p.md", "min_tier": 3.0}}}, "roles.x.min_tier: " + TIER_REASON)
        self.injected_bad({"roles": {"x": {"prompt": "p.md", "min_tier": SubStr("tier2")}}},  # D6: exact str only
                          "roles.x.min_tier: " + TIER_REASON)

    # ---- BU rows
    def test_budgets_framework_role_keys(self):  # BU1
        for role in FRAMEWORK_ROLES:
            with self.subTest(role=role):
                self.assertEqual(self.ok({"budgets": {role: {"tokens": 5, "minutes": 3}}})["budgets"],
                                 {role: {"tokens": 5, "minutes": 3}})

    def test_budgets_unknown_role_shape_only(self):  # BU2
        cfg = self.ok({"budgets": {"doc_writer": {"tokens": 5}, "nobody": {"minutes": 1}}})
        self.assertEqual(cfg["budgets"], {"doc_writer": {"tokens": 5}, "nobody": {"minutes": 1}})
        cfg = self.ok({"roles": self.roles("doc_writer")["roles"], "budgets": {"doc_writer": {"tokens": 5}}})
        self.assertEqual(cfg["budgets"], {"doc_writer": {"tokens": 5}})

    def test_budgets_key_grammar(self):  # BU3, D-Q1 (A)
        for key in ("X", "1x", "a-b", "a.b", "", "x\n", " x", "\uff58", "k\u212a", "\ua7c0", "Controller", "a b"):
            with self.subTest(key=key):
                msg = self.refused(self.light({"budgets": {key: {"tokens": 5}}}))
                self.assertEqual(msg, "%sbudgets: %s" % (PFX, GRAMMAR))
        for key in (1, None, SubStr("x")):
            with self.subTest(key=repr(key)):
                self.injected_bad({"budgets": {key: {"tokens": 5}}}, "budgets: " + GRAMMAR)
        self.assertIn("a" * 5000, self.ok({"budgets": {"a" * 5000: {"tokens": 5}}})["budgets"])

    def test_budgets_entry_not_a_mapping(self):  # BU4
        for v in (5, None, [1], "5", True):
            with self.subTest(value=v):
                self.bad({"budgets": {"controller": v}}, "budgets.controller", "must be a mapping")
        self.injected_bad({"budgets": {"controller": SubDict()}}, "budgets.controller: must be a mapping")

    def test_budgets_entry_empty(self):  # BU5
        self.assertEqual(self.inj({"budgets": {"controller": {}}})["budgets"]["controller"], {})

    def test_budgets_unknown_entry_key(self):  # BU6
        for entry, k in (({"tokens": 5, "max": 3}, "max"), ({"token": 5}, "token"), ({"Tokens": 5}, "Tokens"),
                         ({"tokens": 5, "minutes": 3, "extra": 1}, "extra")):
            with self.subTest(entry=entry):
                self.unknown({"budgets": {"controller": entry}}, "budgets.controller." + k)

    def test_budgets_tokens_valid(self):  # BU7, BU9
        for f in ("tokens", "minutes"):
            for v in (1, 5000, 10 ** 599):
                with self.subTest(field=f, value=v):
                    self.assertEqual(self.ok({"budgets": {"controller": {f: v}}})["budgets"]["controller"][f], v)

    NOT_INT = (0, -1, True, False, "5", "2.5", "5.0", None, [5], {"a": 1}, "", "07", "1_000", "0x10", "+5", " 5")

    def test_budgets_tokens_refusals(self):  # BU8, BU13
        for f in ("tokens", "minutes"):
            for v in self.NOT_INT:
                with self.subTest(field=f, value=v):
                    self.bad({"budgets": {"controller": {f: v}}}, "budgets.controller.%s" % f, INT1)
        self.injected_bad({"budgets": {"controller": {"tokens": 2.5}}}, "budgets.controller.tokens: " + INT1)

    def test_budgets_minutes_values(self):  # BU9
        self.bad({"budgets": {"controller": {"minutes": 0}}}, "budgets.controller.minutes", INT1)
        self.assertEqual(self.ok({"budgets": {"controller": {"minutes": 30}}})["budgets"]["controller"],
                         {"minutes": 30})

    def test_budgets_both_keys(self):  # BU10, D5: tokens before minutes
        self.assertEqual(self.ok({"budgets": {"c": {"tokens": 5, "minutes": 3}}})["budgets"]["c"],
                         {"tokens": 5, "minutes": 3})
        self.bad({"budgets": {"c": {"tokens": 0, "minutes": 3}}}, "budgets.c.tokens", INT1)
        self.bad({"budgets": {"c": {"tokens": 5, "minutes": 0}}}, "budgets.c.minutes", INT1)
        self.bad({"budgets": {"c": {"minutes": 0, "tokens": 0}}}, "budgets.c.tokens", INT1)

    def test_budgets_duplicate_role(self):  # BU12
        self.assertIn("duplicate key 'controller'", self.raw_refused(
            "budgets:\n  controller:\n    tokens: 1\n  controller:\n    tokens: 2\n"))

    # ---- BL rows
    def test_block_rulings_dispatch_ints_valid(self):  # BL1, BL10, BL12
        for k, leaf in LEAF.items():
            for v in (1, 2, 4, 5, 100000, 10 ** 599, 1000000):
                with self.subTest(key=k, value=v):
                    self.assertEqual(self.ok({k: {leaf: v}})[k], {leaf: v})

    def test_block_rulings_dispatch_ints(self):  # BL2, BL4, BL5, BL6, planned Step 1
        bad = (0, -1, -10 ** 30, True, False, "5", "2.5", "5.0", "07", "1_000", "0x10", "+5", None, [3],
               {"a": 1}, "", " 5")
        for k, leaf in LEAF.items():
            for v in bad:
                with self.subTest(key=k, value=v):
                    self.bad({k: {leaf: v}}, "%s.%s" % (k, leaf), INT1)
            with self.subTest(key=k, value="float"):
                self.injected_bad({k: {leaf: 2.5}}, "%s.%s: %s" % (k, leaf, INT1))

    def test_block_rulings_dispatch_digit_caps(self):  # BL7: 600 accepted, 601 and 10**700 refused
        for k, leaf in LEAF.items():
            with self.subTest(key=k):
                self.assertEqual(self.ok({k: {leaf: 10 ** 600 - 1}})[k][leaf], 10 ** 600 - 1)
                self.bad({k: {leaf: 10 ** 600}}, "%s.%s" % (k, leaf), DIG)
                self.bad({k: {leaf: 10 ** 700}}, "%s.%s" % (k, leaf), DIG)

    def test_block_value_is_shape_only(self):  # BL10
        self.assertEqual(self.ok({"block": {"max_tasks": 1}})["block"], {"max_tasks": 1})
        self.assertEqual(self.ok({"rulings": {"max_per_block": 1000000}})["rulings"], {"max_per_block": 1000000})

    def test_no_preset_for_rulings_dispatch_budgets(self):  # BL11
        for p in ("light", "standard", "strict"):
            cfg = self.with_extra({"profile": p})
            for k in ("rulings", "dispatch", "budgets", "roles"):
                self.assertNotIn(k, cfg)

    def test_light_block_max_tasks_direct_typed(self):  # IX9
        self.assertEqual(self.ok({"block": {"max_tasks": 4}})["block"], {"max_tasks": 4})
        self.bad({"block": {"max_tasks": 0}}, "block.max_tasks", INT1)

    # ---- IX rows
    def test_typed_block_accepts_applied_override(self):  # IX4, IX11
        ovr = {"overrides": {"block.max_tasks": {"value": 4, "decision": DEC_ID}}}
        for p in ("strict", "standard"):
            with self.subTest(profile=p):
                self.assertEqual(self.with_extra(dict(ovr, profile=p))["block"], {"max_tasks": 4})

    def test_override_bad_value_names_the_override_not_the_block(self):  # IX5, IX6
        for v in (0, -1, True, "3", None, [3]):
            with self.subTest(value=v):
                msg = self.refused({"overrides": {"block.max_tasks": {"value": v, "decision": DEC_ID}}})
                self.assertTrue(msg.startswith(PFX + "overrides.block.max_tasks.value: "), msg)
        msg = self.refused({"overrides": {"block.max_tasks": {"value": 10 ** 600, "decision": DEC_ID}}})
        self.assertEqual(msg, PFX + "overrides.block.max_tasks.value: " + DIG)

    def test_policy_key_in_file_precedes_typed_readers(self):  # IX1, IX2, K8
        for p in ("strict", "standard"):
            with self.subTest(profile=p):
                msg = self.refused({"profile": p, "block": {"max_tasks": 4, "other": 1}, "roles": 5})
                self.assertEqual(msg, "%sblock.max_tasks: preset by profile %s; change it under overrides with the "
                                 "authorising decision" % (PFX, p))

    def test_override_of_five_keys_non_policy_refused(self):  # IX8
        for key in ("rulings.max_per_block", "dispatch.max_prompt_chars", "budgets.controller.tokens",
                    "roles.x.min_tier"):
            with self.subTest(key=key):
                msg = self.refused({"overrides": {key: {"value": 1, "decision": DEC_ID}}})
                self.assertEqual(msg, "%soverrides.%s: not a policy key of profile strict and not a limits key"
                                 % (PFX, key))

    # ---- ER rows
    def test_typed_readers_error_form(self):  # ER1, ER2, ER5 (refused() asserts the root path is absent)
        cases = (("roles.x.prompt", self.roles("x", {"prompt": "p.txt", "min_tier": "tier2"})),
                 ("roles.x.min_tier", self.roles("x", {"prompt": "p.md", "min_tier": "tier5"})),
                 ("budgets.controller.tokens", {"budgets": {"controller": {"tokens": 0}}}),
                 ("block.max_tasks", {"block": {"max_tasks": 0}}),
                 ("rulings.max_per_block", {"rulings": {"max_per_block": 0}}),
                 ("dispatch.max_prompt_chars", {"dispatch": {"max_prompt_chars": 0}}),
                 ("roles", {"roles": 5}), ("block", {"block": 5}))
        for key, extra in cases:
            with self.subTest(key=key):
                self.assertTrue(self.refused(self.light(extra)).startswith("%s%s: " % (PFX, key)))

    def test_typed_readers_raise_only_gateerror(self):  # ER3
        junk = (None, 5, True, "x", "", [], [1], {}, {"a": 1}, {"a": {}}, {"a": {"prompt": 5}}, 2.5, SubStr("x"),
                SubDict(), {1: 2}, {None: {}}, {("a",): 1}, {"x": {"prompt": {}, "min_tier": []}},
                {"x": {"tokens": [], "minutes": {}}}, {"max_tasks": [], "max_per_block": {}})
        for k in FIVE:
            for v in junk:
                with self.subTest(key=k, value=repr(v)[:40]):
                    try:
                        self.inj({k: copy.deepcopy(v)})
                    except GateError:
                        pass

    def test_typed_readers_message_one_line(self):  # ER4: ids and keys never reach the line raw
        for bad in ("x\ny", "x\x00", "\ufeffx", "x\ud800", "x\r\n", "x\u2028y"):
            for extra in ({"roles": {bad: dict(ENTRY)}}, {"budgets": {bad: {"tokens": 1}}},
                          {"block": {bad: 1}}, {"rulings": {bad: 1}}, {"dispatch": {bad: 1}},
                          {"roles": {"x": dict(ENTRY, **{bad: 1})}}, {"budgets": {"c": {bad: 1}}}):
                with self.subTest(bad=bad, extra=str(extra)[:30]):
                    msg = self.inj_refused(extra)
                    self.assertEqual(len(msg.splitlines()), 1)
                    for ch in ("\n", "\r", "\x00", "\ufeff", "\ud800", "\u2028"):
                        self.assertNotIn(ch, msg)

    def test_typed_readers_no_value_echo(self):  # ER7
        for extra in ({"block": {"max_tasks": 10 ** 700}}, {"budgets": {"c": {"tokens": "x" * 5000}}},
                      self.roles("x", {"prompt": "q" * 5000 + ".txt", "min_tier": "tier2"}),
                      self.roles("x", {"prompt": "p.md", "min_tier": "z" * 5000})):
            with self.subTest(extra=str(extra)[:30]):
                msg = self.refused(self.light(extra))
                self.assertLess(len(msg), 200)
                for frag in ("7" * 10, "x" * 10, "q" * 10, "z" * 10):
                    self.assertNotIn(frag, msg)

    def test_unknown_key_shape_matches_limits(self):  # ER6, D7
        self.assertEqual(self.refused(self.light({"limits": {"x": 1}})), PFX + "unknown key 'limits.x'")
        self.assertEqual(self.refused(self.light({"block": {"x": 1}})), PFX + "unknown key 'block.x'")

    def test_typed_readers_run_after_existing_checks(self):  # ER8
        self.assertEqual(self.refused({"profile": "light", "roles": 5, "zzz": 1}), PFX + "unknown key 'zzz'")
        msg = self.refused({"profile": "light", "roles": 5, "schema": "config/9"})
        self.assertTrue(msg.startswith(PFX + "schema: "), msg)
        msg = self.refused({"profile": "light", "roles": 5, "context": {"max_lines": 0}})
        self.assertEqual(msg, PFX + "context.max_lines: " + INT1)

    # ---- V rows
    def test_typed_readers_digit_caps(self):  # V1, BU11, BL7: 600 accepted, 601-1000 named, over 1000 by yamlsub
        cases = (("budgets.controller.tokens", "budgets:\n  controller:\n    tokens: %s\n",
                  lambda c: c["budgets"]["controller"]["tokens"]),
                 ("budgets.controller.minutes", "budgets:\n  controller:\n    minutes: %s\n",
                  lambda c: c["budgets"]["controller"]["minutes"]),
                 ("block.max_tasks", "block:\n  max_tasks: %s\n", lambda c: c["block"]["max_tasks"]),
                 ("rulings.max_per_block", "rulings:\n  max_per_block: %s\n",
                  lambda c: c["rulings"]["max_per_block"]),
                 ("dispatch.max_prompt_chars", "dispatch:\n  max_prompt_chars: %s\n",
                  lambda c: c["dispatch"]["max_prompt_chars"]))
        too_large = r"\A\.strict-delivery/config\.yml: integer too large \(line [0-9]+\)\Z"
        for lim in INT_LIMITS:
            with int_limit(lim):
                for key, template, get in cases:
                    for digits in (600, 601, 1000, 1001, 4300, 4301):
                        with self.subTest(limit=lim, key=key, digits=digits):
                            body = template % ("7" * digits)
                            if digits == 600:
                                self.assertEqual(get(self.raw(body)), int("7" * digits))
                            elif digits > 1000 or (lim == 640 and digits > 640):
                                self.assertRegex(self.raw_refused(body), too_large)
                            else:
                                self.assertEqual(self.raw_refused(body), "%s%s: %s" % (PFX, key, DIG))

    def test_typed_readers_unicode_same_on_both(self):  # V2: hand-written verdicts, identical on 3.9 and 3.13
        for key in ("\ua7c0", "\ua7c1", "\U0001fae8", "\uff58", "k\u212a", "x\u00e9"):
            with self.subTest(key=key):
                self.assertEqual(self.refused(self.light(self.roles(key))), "%sroles: %s" % (PFX, GRAMMAR))
        for p in ("\ua7c0.md", "\U0001fae8.md"):
            with self.subTest(prompt=p):
                self.assertTrue(self.refused(self.light(self.prompt(p)))
                                .startswith(PFX + "roles.x.prompt: must be a non-empty normalised"))
        for t in ("tier\u0662", "tier\uff12"):
            with self.subTest(tier=t):
                self.bad(self.roles("x", {"prompt": "p.md", "min_tier": t}), "roles.x.min_tier", TIER_REASON)

    def test_typed_readers_catch_nothing(self):  # V3: no try statement in any new typed reader (ast, not source text)
        readers = ("_validate", "_role_keys", "_entry_keys", "_validate_prompt", "_validate_roles",
                   "_validate_budgets", "_validate_int_map")
        with open(config.__file__, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        funcs = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
        kinds = tuple(k for k in (ast.Try, getattr(ast, "TryStar", None)) if k is not None)
        for name in readers:
            self.assertIn(name, funcs)
            with self.subTest(reader=name):
                self.assertEqual([n.lineno for n in ast.walk(funcs[name]) if isinstance(n, kinds)], [])
        self.assertIn("load", funcs)  # the one try in load(): yamlsub.YamlError, as before this task
        self.assertEqual(sum(isinstance(n, kinds) for n in ast.walk(tree)), 1)


class ProfileOverrideClassTest(ConfigCase):
    """Task 4a.3: ``profile-override`` is a default owner-only class, after ``rule-override`` (rows OC, decision D8)."""

    def test_profile_override_is_default_owner_only(self):  # OC1, OC2, Q-B4plan-4 (a)
        got = config.load(self.root)["decision_classes"]["owner_only"]
        self.assertIn("profile-override", got)
        self.assertEqual(got, OWNER_ONLY)
        self.assertEqual(got.index("profile-override"), got.index("rule-override") + 1)
        self.assertEqual(len(got), 13)
        self.assertEqual(config.DEFAULTS["decision_classes"]["owner_only"], OWNER_ONLY)

    def test_owner_only_union_with_profile_override(self):  # OC4
        for given in (["profile-override"], ["hardware", "profile-override"], ["profile-override", "hardware"]):
            with self.subTest(given=given):
                cfg = self.with_extra({"decision_classes": {"owner_only": given}})
                want = OWNER_ONLY + (["hardware"] if "hardware" in given else [])
                self.assertEqual(cfg["decision_classes"]["owner_only"], want)

    def test_profile_override_cannot_be_dropped(self):  # OC6
        for given in (["hardware"], ["triage"], ["rule-override", "zeta"]):
            with self.subTest(given=given):
                got = self.with_extra({"decision_classes": {"owner_only": given}})["decision_classes"]["owner_only"]
                self.assertIn("profile-override", got)
                self.assertEqual(got.count("profile-override"), 1)

    def test_profile_override_near_names_are_other_classes(self):  # OC9
        near = ["profile-overrides", "Profile-Override", "profile_override", "profile-override "]
        got = self.with_extra({"decision_classes": {"owner_only": near}})["decision_classes"]["owner_only"]
        self.assertEqual(got, OWNER_ONLY + near)

    def test_decisions_validate_accepts_profile_override(self):  # OC10: the class is known to decisions.validate
        from gates.lib import decisions
        cfg = config.load(self.root)
        tag = "decision/%d" % migrations.current_version("decision")
        missing = "class: %s is not in decision_classes.owner_only"
        self.assertNotIn(missing % "profile-override", decisions.validate({"schema": tag, "class": "profile-override"},
                                                                          cfg))
        self.assertIn(missing % "bogus", decisions.validate({"schema": tag, "class": "bogus"}, cfg))  # contradiction


if __name__ == "__main__":
    unittest.main()
