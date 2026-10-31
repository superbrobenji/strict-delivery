"""Tests for the config loader (gates.lib.config), on fixture repositories made by make_repo."""
import copy
import os
import stat
import unittest

from gates.lib import config
from gates.lib.result import GateError, Result, gate_args, run_gate
from gates.lib.yamlsub import emit
from tests.helpers import GitIsolatedTestCase, make_repo, minimal_config

MISSING = ".strict-delivery/config.yml: missing; run /strict-delivery:init"

# Written independently of config.DEFAULTS (from the brief), so the loader is compared with a second copy.
OWNER_ONLY = ["triage", "spec-direction", "scope", "merge-grant", "model-policy", "issue-close",
              "finding-class", "rule-override", "program-create", "stream-ownership", "stream-merge",
              "request-dispute", "program-close"]
EXPECTED = {
    "schema": "config/1",
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
}


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
        for root in (sub, os.path.join(self.root, "nope"), self.path):
            with self.subTest(root=root):
                with self.assertRaises(GateError) as e:
                    config.load(root)
                self.assertEqual(str(e.exception), MISSING)


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
            self.assertEqual(out.getvalue(), "FAIL x.input: " + MISSING + "\n")
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
        msg = self.refused_text("schema: config/1\nframework_version: '0'\n\tprofile: strict\n",
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

    def test_schema_values(self):  # C5
        for value in ("config/2", "decision/1", "config/1 ", "Config/1", 1, None, True, ["config/1"],
                      {"a": 1}):
            with self.subTest(value=value):
                self.refused({"schema": value}, "schema")
        self.assertEqual(self.with_extra({"schema": "config/1"}), EXPECTED)

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
                self.refused({key: value}, "unknown key " + repr(key))

    def test_not_yet_landed_keys_accepted_unchecked(self):  # C18
        extra = {"commands": {"test": "make test"}, "roles": 5, "block": [1, 2], "rulings": None,
                 "dispatch": "x", "budgets": {"a": {"b": 1}}, "overrides": [], "top_tier_roles": [""],
                 "top_tier_fallback": True}
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
                    "a/./b", "a/..", "/", "//x"):
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
        self.put_bytes(b"schema: config/1\nframework_version: '0'\nprofile: strict\n"
                       b"drift:\n  estimate_factor_pct: 1.5\n")
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


if __name__ == "__main__":
    unittest.main()
