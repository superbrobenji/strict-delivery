"""Tests of gates/lib/profiles.py and of the profile merge and ``overrides`` in config.load (Task 4a.2).

Expected values are written by hand from the plan (P:4243-4312, the binding decisions D1-D14, D-Q1 to D-Q3 of its
input-domain table); the rows are named by their table ids (PR, FW, NM, FS, VA, RT, FL, PK, M, OV, LM, RP, V). The
profile directory of a row that needs another one is a fixture framework directory (``plugin.framework_dir`` patched);
the real ``profiles/`` is only read."""
import builtins
import contextlib
import copy
import inspect
import os
import signal
import stat
import subprocess
import sys
import unittest
from unittest import mock

from gates import run_all
from gates.lib import config, plugin, profiles, schema, yamlsub
from gates.lib.result import GateError
from gates.lib.yamlsub import emit
from tests.helpers import GitIsolatedTestCase, make_repo, minimal_config

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HAS_BEG = hasattr(builtins, "BaseExceptionGroup")
ROLES = ["final_verifier", "exception_reviewer"]
DEC = "DEC-20261111-abcd"
CONFIG_PATH = ".strict-delivery/config.yml"
HEAD = "schema: profile/1\nprofile: %s\ndefaults:\n  top_tier_roles: [final_verifier, exception_reviewer]\n"
TEXT = {
    "light": HEAD % "light" + "policy:\n",
    "standard": HEAD % "standard" + "policy:\n  block:\n    max_tasks: 5\n",
    "strict": HEAD % "strict" + "policy:\n  block:\n    max_tasks: 3\n",
}
GOOD = TEXT["strict"]


class S(str):
    """A str subclass."""


class FwCase(GitIsolatedTestCase):
    """A fixture framework directory ``self.fw`` holding profiles/."""

    def setUp(self):
        super().setUp()
        self.fw = os.path.join(self.tmp, "fw")
        os.makedirs(os.path.join(self.fw, "profiles"))

    def put(self, name, text, fw=None):
        path = os.path.join(fw or self.fw, "profiles", name + ".yml")
        data = text if isinstance(text, bytes) else text.encode("utf-8")
        with open(path, "wb") as fh:
            fh.write(data)
        return path

    def put_all(self):
        for n in profiles.PROFILES:
            self.put(n, TEXT[n])

    def refused(self, *needles, name="strict", framework="default", **_):
        fw = self.fw if framework == "default" else framework
        with self.assertRaises(GateError) as e:
            profiles.load(name, fw)
        for n in needles:
            self.assertIn(n, str(e.exception))
        self.assertNotIn(self.tmp, str(e.exception))
        return str(e.exception)

    def text_refused(self, text, *needles):
        self.put("strict", text)
        return self.refused(*needles)


# ------------------------------------------------------------------------------------------------------ PR
class ConstantTest(unittest.TestCase):
    def test_profiles_constant(self):  # PR1
        self.assertIs(type(profiles.PROFILES), tuple)
        self.assertEqual(profiles.PROFILES, ("light", "standard", "strict"))
        self.assertTrue(all(type(p) is str for p in profiles.PROFILES))

    def test_profiles_match_config_enum(self):  # PR2
        self.assertEqual(config._PROFILES, ("light", "standard", "strict"))

    def test_profiles_match_profile_schema(self):  # PR3
        sch = schema.load_schema(os.path.join(REPO, "gates", "schemas", "profile.yml"))
        self.assertEqual(tuple(sch.fields["profile"]["values"]), ("light", "standard", "strict"))

    def test_profiles_match_run_all(self):  # PR4
        self.assertEqual(set(run_all.PROFILE_GATES), {"light", "standard", "strict"})

    def test_profiles_imports_without_cycle(self):  # E16, mutant 21
        for mod in ("profiles", "config", "schema"):
            with self.subTest(mod=mod):
                p = subprocess.run([sys.executable, "-c", "import gates.lib.%s" % mod], cwd=REPO,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                self.assertEqual(p.returncode, 0, p.stderr.decode())


# ------------------------------------------------------------------------------------------------------ FW
class FrameworkArgTest(FwCase):
    def test_default_framework_is_plugin_framework_dir(self):  # FW1
        self.put_all()
        self.put("strict", TEXT["strict"].replace("max_tasks: 3", "max_tasks: 8"))
        with mock.patch.object(plugin, "framework_dir", return_value=self.fw):
            self.assertEqual(profiles.load("strict")["policy"], {"block": {"max_tasks": 8}})
            self.assertEqual(profiles.load("strict", None)["policy"], {"block": {"max_tasks": 8}})
        self.assertEqual(profiles.load("strict")["policy"], {"block": {"max_tasks": 3}})  # the real one

    def test_framework_argument_fixture_dir(self):  # FW2
        self.put_all()
        self.assertEqual(profiles.load("standard", self.fw)["policy"], {"block": {"max_tasks": 5}})
        self.assertEqual(profiles.load("light", self.fw), {"defaults": {"top_tier_roles": ROLES}, "policy": {}})
        self.assertFalse(os.path.exists(os.path.join(self.fw, "gates")))  # profile.yml is the installed one (D4)

    def test_framework_without_profiles_dir(self):  # FW3
        empty = os.path.join(self.tmp, "empty")
        os.mkdir(empty)
        self.refused("profiles/strict.yml", framework=empty)

    def test_profiles_dir_is_a_file(self):  # FW4
        fw = os.path.join(self.tmp, "fw2")
        os.mkdir(fw)
        with open(os.path.join(fw, "profiles"), "w") as fh:
            fh.write("x")
        self.refused("profiles/strict.yml", framework=fw)

    def test_profiles_dir_symlink_refused(self):  # FW5
        self.put_all()
        fw = os.path.join(self.tmp, "fw3")
        os.mkdir(fw)
        os.symlink(os.path.join(self.fw, "profiles"), os.path.join(fw, "profiles"))
        self.refused("profiles/strict.yml", "symlink", framework=fw)

    def test_profiles_dir_unreadable(self):  # FW6
        if os.geteuid() == 0:
            self.skipTest("root reads everything")
        self.put_all()
        d = os.path.join(self.fw, "profiles")
        os.chmod(d, 0)
        self.addCleanup(os.chmod, d, 0o755)
        self.refused("profiles/strict.yml")

    def test_framework_wrong_types(self):  # FW7
        self.put_all()
        with mock.patch.object(os, "lstat", side_effect=AssertionError("filesystem touched")):
            for bad in (5, True, b"x", ["x"], {}, os.path.join, S("x"), 1.5):
                with self.subTest(bad=bad):
                    with self.assertRaises(GateError):
                        profiles.load("strict", bad)

    def test_framework_pathlib_refused(self):  # FW7
        import pathlib
        with self.assertRaises(GateError):
            profiles.load("strict", pathlib.Path(self.fw))

    def test_framework_empty_or_nul(self):  # FW8
        for bad in ("", "a\x00b"):
            with self.subTest(bad=bad):
                msg = self.refused(framework=bad)
                self.assertNotIn("\x00", msg)

    def test_framework_relative_path(self):  # FW9
        self.put_all()
        old = os.getcwd()
        os.chdir(self.tmp)
        self.addCleanup(os.chdir, old)
        self.assertEqual(profiles.load("strict", "fw")["policy"], {"block": {"max_tasks": 3}})

    def test_framework_path_forms(self):  # FW10
        fw = os.path.join(self.tmp, "fw-é")
        os.makedirs(os.path.join(fw, "profiles"))
        self.put("strict", GOOD, fw)
        self.assertEqual(profiles.load("strict", fw)["policy"], {"block": {"max_tasks": 3}})
        self.refused("profiles/strict.yml", framework="/" + "a" * 4097)

    def test_framework_through_symlink_ok(self):  # FW11
        self.put_all()
        link = os.path.join(self.tmp, "link")
        os.symlink(self.fw, link)
        self.assertEqual(profiles.load("strict", link)["policy"], {"block": {"max_tasks": 3}})

    def test_default_framework_ignores_cwd(self):  # FW12
        old = os.getcwd()
        os.chdir(self.tmp)
        self.addCleanup(os.chdir, old)
        with mock.patch.dict(os.environ, {"CLAUDE_PLUGIN_ROOT": self.fw}):
            self.assertEqual(profiles.load("strict")["policy"], {"block": {"max_tasks": 3}})


# ------------------------------------------------------------------------------------------------------ NM
class NameTest(FwCase):
    def test_each_profile_loads(self):  # NM1
        for n in profiles.PROFILES:
            with self.subTest(name=n):
                self.assertEqual(profiles.load(n)["defaults"], {"top_tier_roles": ROLES})

    def test_unknown_name_refused(self):  # NM2
        self.put_all()
        self.put("loose", GOOD.replace("profile: strict", "profile: loose"))
        for n in ("loose", "heavy", ""):
            with self.subTest(name=n):
                self.refused("must be one of light, standard, strict", name=n)
        self.assertEqual(profiles.load("strict", self.fw)["policy"]["block"], {"max_tasks": 3})

    def test_name_exact_match_only(self):  # NM3, V4
        self.put_all()
        for n in ("Strict", "STRICT", " strict", "strict ", "strict\n", "strict\r", "İ", "\u212a"):
            with self.subTest(name=n):
                self.refused("must be one of light, standard, strict", name=n)

    def test_name_path_traversal_refused(self):  # NM4
        self.put_all()
        with mock.patch.object(os, "lstat", side_effect=AssertionError("filesystem touched")):
            for n in ("../strict", "strict/../light", "a/b", "/etc/passwd", "strict.yml", "strict\x00", "..", "."):
                with self.subTest(name=n):
                    with self.assertRaises(GateError):
                        profiles.load(n, self.fw)

    def test_name_nonascii_nul_long(self):  # NM5
        for n in ("stríct", "İ", "strict" * 1000, "\x00", "\ufeffstrict"):
            with self.subTest(name=n[:8]):
                msg = self.refused(name=n)
                self.assertNotIn("\x00", msg)
                self.assertNotIn("\n", msg)

    def test_name_wrong_types(self):  # NM6
        self.put_all()
        for n in (None, 5, True, b"strict", ["strict"], {"a": 1}, S("strict")):
            with self.subTest(name=n):
                with self.assertRaises(GateError) as e:
                    profiles.load(n, self.fw)
                self.assertIn("must be one of light, standard, strict", str(e.exception))

    def test_profile_field_differs(self):  # NM7, VA11
        self.put("strict", GOOD.replace("profile: strict", "profile: light"))
        msg = self.refused("profiles/strict.yml: profile: 'light' does not match the file name 'strict'")
        self.assertEqual(msg.count("profiles/strict.yml"), 1)
        self.put("light", TEXT["strict"])
        self.refused("profile: 'strict' does not match the file name 'light'", name="light")
        self.put("standard", TEXT["strict"])
        self.refused("profile: 'strict' does not match the file name 'standard'", name="standard")


# ------------------------------------------------------------------------------------------------------ FS
class FileStateTest(FwCase):
    def test_profile_file_missing_fails_closed(self):  # FS1
        self.refused("profiles/strict.yml: file is missing")

    def test_file_state_regular(self):  # FS2
        self.put("strict", GOOD)
        self.assertEqual(profiles.load("strict", self.fw), {"defaults": {"top_tier_roles": ROLES},
                                                           "policy": {"block": {"max_tasks": 3}}})

    def test_file_state_directory(self):  # FS3
        os.mkdir(os.path.join(self.fw, "profiles", "strict.yml"))
        self.refused("profiles/strict.yml: file is not a regular file")

    def test_file_state_symlink_refused(self):  # FS4
        real = self.put("real", GOOD)
        os.symlink(real, os.path.join(self.fw, "profiles", "strict.yml"))
        self.refused("profiles/strict.yml: file is a symlink")

    def test_file_state_dangling_symlink(self):  # FS5
        os.symlink(os.path.join(self.fw, "nowhere"), os.path.join(self.fw, "profiles", "strict.yml"))
        self.refused("profiles/strict.yml: file is a symlink")

    def test_file_state_fifo_does_not_block(self):  # FS6
        os.mkfifo(os.path.join(self.fw, "profiles", "strict.yml"))

        def boom(*a):
            raise AssertionError("profiles.load blocked on a FIFO")
        old = signal.signal(signal.SIGALRM, boom)
        self.addCleanup(signal.signal, signal.SIGALRM, old)
        signal.alarm(20)
        self.addCleanup(signal.alarm, 0)
        self.refused("profiles/strict.yml: file is not a regular file")

    def test_file_state_unreadable(self):  # FS7
        if os.geteuid() == 0:
            self.skipTest("root reads everything")
        path = self.put("strict", GOOD)
        os.chmod(path, 0)
        self.addCleanup(os.chmod, path, 0o644)
        self.refused("profiles/strict.yml", "Permission denied")

    def test_file_state_empty(self):  # FS8
        self.text_refused("", "profiles/strict.yml: top level: must be a mapping")

    def test_file_state_comment_only(self):  # FS9
        for t in ("# c\n", "\n\n"):
            with self.subTest(text=t):
                self.text_refused(t, "profiles/strict.yml: top level: must be a mapping")

    def test_file_state_not_utf8(self):  # FS10
        self.text_refused(b"schema: \xff\n", "profiles/strict.yml: not valid UTF-8")

    def test_file_state_bom_and_crlf(self):  # FS11
        want = {"defaults": {"top_tier_roles": ROLES}, "policy": {"block": {"max_tasks": 3}}}
        self.put("strict", b"\xef\xbb\xbf" + GOOD.encode())
        self.assertEqual(profiles.load("strict", self.fw), want)
        self.put("strict", GOOD.replace("\n", "\r\n"))
        self.assertEqual(profiles.load("strict", self.fw), want)

    def test_file_state_yaml_error_has_line(self):  # FS12
        for t in ("a: [1\n", "schema: profile/1\n\tx: 1\n", "defaults: {a: 1}\n"):
            with self.subTest(text=t):
                self.text_refused(t, "profiles/strict.yml: ", "(line ")

    def test_file_state_duplicate_key(self):  # FS13
        self.text_refused(GOOD + "policy:\n", "profiles/strict.yml: ", "duplicate key", "(line ")

    def test_refusals_name_relative_file_only(self):  # FS15
        os.mkdir(os.path.join(self.fw, "profiles", "light.yml"))
        self.refused("profiles/light.yml", name="light")
        self.refused("profiles/standard.yml", name="standard")  # missing
        for t in ("", b"\xff", "a: [1\n", GOOD.replace("profile: strict", "profile: light")):
            self.put("strict", t)
            self.assertTrue(self.refused().startswith("profiles/strict.yml: "))

    def test_refusals_leave_no_descriptor_open(self):  # FS16
        def count():
            return len(os.listdir("/dev/fd"))
        before = count()
        os.mkdir(os.path.join(self.fw, "profiles", "light.yml"))
        for t in ("", b"\xff", "a: [1\n", GOOD + "policy:\n", GOOD.replace("max_tasks: 3", "max_tasks: 0")):
            self.put("strict", t)
            self.refused()
        self.refused(name="light")
        self.assertEqual(count(), before)


# ------------------------------------------------------------------------------------------------------ VA, RT
class ValidationTest(FwCase):
    def check(self, text, *needles, name="strict"):
        self.put(name, text)
        return self.refused("profiles/%s.yml: " % name, *needles, name=name)

    def test_load_schema_tag(self):  # VA1
        for tag, needle in (("profile/2", "run /strict-delivery:upgrade"), ("profile/0", "expected profile/1"),
                            ("config/2", "expected profile/1"), ("'profile/1 '", "expected profile/1")):
            with self.subTest(tag=tag):
                self.check(GOOD.replace("profile/1", tag), "schema: expected profile/1, got", needle)
        self.check(GOOD.replace("schema: profile/1\n", ""), "schema: expected profile/1, got (missing)")

    def test_load_unknown_keys(self):  # VA2
        for text, key in ((GOOD + "extra: 1\n", "extra"),
                          (GOOD.replace("defaults:\n", "defaults:\n  extra: 1\n"), "defaults.extra"),
                          (GOOD.replace("policy:\n", "policy:\n  extra: 1\n"), "policy.extra"),
                          (GOOD + "  block:\n    max_tasks: 3\n", "")):
            if key:
                with self.subTest(key=key):
                    self.check(text, "%s: unknown key" % key)
        self.check(GOOD.replace("max_tasks: 3\n", "max_tasks: 3\n    extra: 1\n"), "policy.block.extra: unknown key")

    def test_load_required_keys(self):  # VA3
        for drop, key in (("profile: strict\n", "profile"), ("defaults:\n  top_tier_roles: [final_verifier, "
                                                            "exception_reviewer]\n", "defaults"),
                          ("policy:\n  block:\n    max_tasks: 3\n", "policy")):
            with self.subTest(key=key):
                self.check(GOOD.replace(drop, ""), "%s: required key is missing" % key)

    def test_load_max_tasks_zero(self):  # VA4
        self.check(GOOD.replace("max_tasks: 3", "max_tasks: 0"), "policy.block.max_tasks: must be at least 1")

    def test_load_max_tasks_bool(self):  # VA5
        for v in ("true", "false"):
            with self.subTest(v=v):
                self.check(GOOD.replace("max_tasks: 3", "max_tasks: " + v), "policy.block.max_tasks: must be an integer")

    def test_load_max_tasks_str(self):  # VA6
        for v in ('"3"', "'3'"):
            with self.subTest(v=v):
                self.check(GOOD.replace("max_tasks: 3", "max_tasks: " + v), "policy.block.max_tasks: must be an integer")

    def test_load_max_tasks_values(self):  # VA7
        self.put("strict", GOOD.replace("max_tasks: 3", "max_tasks: 1"))
        self.assertEqual(profiles.load("strict", self.fw)["policy"], {"block": {"max_tasks": 1}})
        self.check(GOOD.replace("max_tasks: 3", "max_tasks: -1"), "must be at least 1")
        for v in ("2.5", "null", "[3]", '""', "07", "[]"):
            with self.subTest(v=v):
                self.check(GOOD.replace("max_tasks: 3", "max_tasks: " + v), "policy.block.max_tasks")

    def test_load_defaults_shape(self):  # VA8
        ok = GOOD.replace("[final_verifier, exception_reviewer]", "[]")
        self.put("strict", ok)
        self.assertEqual(profiles.load("strict", self.fw)["defaults"], {"top_tier_roles": []})
        for v in ('[""]', "[1]", '"x"', "null"):
            with self.subTest(v=v):
                self.check(GOOD.replace("[final_verifier, exception_reviewer]", v), "defaults.top_tier_roles")
        for v in ('""', "3", "null"):
            with self.subTest(fallback=v):
                self.check(GOOD.replace("defaults:\n", "defaults:\n  top_tier_fallback: %s\n" % v),
                           "defaults.top_tier_fallback")

    def test_load_policy_shape(self):  # VA9
        self.check(GOOD.replace("block:\n    max_tasks: 3", "block: [1]"), "policy.block")
        self.check(GOOD.replace("policy:\n  block:\n    max_tasks: 3\n", "policy: [1]\n"), "policy")
        self.check(GOOD.replace("policy:\n  block:\n    max_tasks: 3\n", "policy: 3\n"), "policy")
        self.put("strict", GOOD.replace("  block:\n    max_tasks: 3\n", ""))
        self.assertEqual(profiles.load("strict", self.fw)["policy"], {})  # policy: with no value is {} (D-Q1)
        self.check(GOOD.replace("block:\n    max_tasks: 3", "block:"), "policy.block")

    def test_none_defaults_still_refused(self):  # D-Q1 narrowed: only policy maps None to {}
        self.check(GOOD.replace("defaults:\n  top_tier_roles: [final_verifier, exception_reviewer]\n", "defaults:\n"),
                   "defaults")

    def test_load_profile_enum(self):  # VA10
        for v in ("loose", "Strict", "3", "null"):
            with self.subTest(v=v):
                self.check(GOOD.replace("profile: strict", "profile: " + v), "profile: ")

    def test_load_reports_all_schema_errors(self):  # VA12
        msg = self.check(GOOD + "extra: 1\nother: 2\n", "extra: unknown key; other: unknown key")
        self.assertEqual(msg.count("profiles/strict.yml"), 1)

    def test_load_max_tasks_digit_cap(self):  # VA13, V1
        for digits, ok in ((600, True), (601, False), (1000, False), (1001, False), (4300, False), (4301, False)):
            with self.subTest(digits=digits):
                text = GOOD.replace("max_tasks: 3", "max_tasks: " + "7" * digits)
                self.put("strict", text)
                if ok:
                    self.assertEqual(profiles.load("strict", self.fw)["policy"]["block"]["max_tasks"], int("7" * 600))
                else:
                    msg = self.refused("profiles/strict.yml: ")
                    self.assertTrue("at most 600 digits" in msg or "integer too large" in msg, msg)
                    self.assertNotIn("Exceeds", msg)

    def test_load_max_tasks_600_digits(self):  # RT4
        self.put("strict", GOOD.replace("max_tasks: 3", "max_tasks: " + "7" * 600))
        self.assertEqual(profiles.load("strict", self.fw)["policy"]["block"]["max_tasks"] >= 10 ** 599, True)

    def test_load_returns_defaults_and_policy_only(self):  # RT1
        self.assertEqual(profiles.load("strict"), {"defaults": {"top_tier_roles": ["final_verifier",
                                                                                  "exception_reviewer"]},
                                                   "policy": {"block": {"max_tasks": 3}}})

    def test_load_returns_fresh_objects(self):  # RT2
        a = profiles.load("strict")
        a["defaults"]["top_tier_roles"].append("x")
        a["policy"]["block"]["max_tasks"] = 99
        self.assertEqual(profiles.load("strict"), {"defaults": {"top_tier_roles": ROLES},
                                                   "policy": {"block": {"max_tasks": 3}}})

    def test_load_returns_plain_types(self):  # RT3
        r = profiles.load("strict")
        self.assertIs(type(r), dict)
        self.assertIs(type(r["defaults"]), dict)
        self.assertIs(type(r["defaults"]["top_tier_roles"]), list)
        self.assertTrue(all(type(x) is str for x in r["defaults"]["top_tier_roles"]))
        self.assertIs(type(r["policy"]["block"]["max_tasks"]), int)


# ------------------------------------------------------------------------------------------------------ FL
def read_bytes(rel):
    with open(os.path.join(REPO, *rel.split("/")), "rb") as fh:
        return fh.read()


class FilesTest(unittest.TestCase):
    def test_profile_files_literal(self):  # FL1-FL4
        self.assertEqual([profiles.load(p)["policy"] for p in profiles.PROFILES],
                         [{}, {"block": {"max_tasks": 5}}, {"block": {"max_tasks": 3}}])
        for p in profiles.PROFILES:
            self.assertEqual(profiles.load(p)["defaults"], {"top_tier_roles": ["final_verifier", "exception_reviewer"]})

    def test_profile_files_hold_only_ruled_keys(self):  # FL5
        for p in profiles.PROFILES:
            doc = yamlsub.load(os.path.join(REPO, "profiles", p + ".yml"), p)
            self.assertEqual(sorted(doc), ["defaults", "policy", "profile", "schema"])
            self.assertEqual(list(doc["defaults"]), ["top_tier_roles"])

    def test_profiles_dir_is_exactly_three_regular_files(self):  # FL6
        d = os.path.join(REPO, "profiles")
        self.assertEqual(sorted(os.listdir(d)), ["light.yml", "standard.yml", "strict.yml"])
        for n in os.listdir(d):
            self.assertTrue(stat.S_ISREG(os.lstat(os.path.join(d, n)).st_mode))

    def test_profile_files_validate(self):  # FL7
        sch = schema.load_schema(os.path.join(REPO, "gates", "schemas", "profile.yml"))
        for p in profiles.PROFILES:
            doc = yamlsub.load(os.path.join(REPO, "profiles", p + ".yml"), p)
            if doc["policy"] is None:
                doc["policy"] = {}
            self.assertEqual(schema.validate(sch, doc, {}), [])
            self.assertEqual(doc["profile"], p)

    def test_profile_files_golden_text(self):  # FL8
        for p in profiles.PROFILES:
            self.assertEqual(read_bytes("profiles/%s.yml" % p), TEXT[p].encode("utf-8"))
            self.assertFalse(read_bytes("profiles/%s.yml" % p).startswith(b"\xef\xbb\xbf"))
            self.assertNotIn(b"\r", read_bytes("profiles/%s.yml" % p))
            self.assertNotIn(b"#", read_bytes("profiles/%s.yml" % p))

    def test_gate_schema_green_with_profiles_dir(self):  # FL9
        p = subprocess.run([sys.executable, "-m", "gates", "check", "schema"], cwd=REPO, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE)
        self.assertEqual(p.returncode, 0, p.stdout.decode() + p.stderr.decode())
        self.assertFalse(os.path.exists(os.path.join(REPO, "gates", "schemas", "light.yml")))


# ------------------------------------------------------------------------------------------------------ PK
class PolicyKeysTest(unittest.TestCase):
    def pk(self, policy):
        return profiles.policy_keys({"defaults": {}, "policy": policy})

    def test_policy_keys_block_max_tasks(self):  # PK1
        self.assertEqual(self.pk({"block": {"max_tasks": 3}}), frozenset({"block.max_tasks"}))

    def test_policy_keys_empty(self):  # PK2
        self.assertIs(type(self.pk({})), frozenset)
        self.assertEqual(self.pk({}), frozenset())

    def test_policy_keys_nesting(self):  # PK3
        self.assertEqual(self.pk({"a": 1}), {"a"})
        self.assertEqual(self.pk({"a": {"b": 1}}), {"a.b"})
        self.assertEqual(self.pk({"a": {"b": {"c": 1}}}), {"a.b.c"})

    def test_policy_keys_several(self):  # PK4
        self.assertEqual(self.pk({"block": {"max_tasks": 3, "other": 1}, "x": {"y": 2}}),
                         {"block.max_tasks", "block.other", "x.y"})

    def test_policy_keys_empty_nested(self):  # PK5
        self.assertEqual(self.pk({"block": {}}), frozenset())

    def test_policy_keys_leaf_types(self):  # PK6
        self.assertEqual(self.pk({"a": True, "b": None, "c": [{"d": 1}], "e": "s", "f": 1}), {"a", "b", "c", "e", "f"})

    def test_policy_keys_deep(self):  # PK7
        node = {"k": 1}
        for _ in range(4999):
            node = {"k": node}
        (key,) = self.pk(node)
        self.assertEqual(key, ".".join(["k"] * 5000))

    def test_policy_keys_bad_keys(self):  # PK8
        for pol in ({1: 2}, {"a": {None: 1}}, {True: 1}):
            with self.subTest(pol=pol):
                with self.assertRaises(ValueError):
                    self.pk(pol)

    def test_policy_keys_key_grammar(self):  # PK9
        for k in ("a.b", "", "a b", "é", "a\n", "A", "1a", "a-b"):
            with self.subTest(key=k):
                with self.assertRaises(ValueError):
                    self.pk({k: 1})

    def test_policy_keys_wrong_types(self):  # PK10
        class D(dict):
            pass
        for bad in (None, [], "x", 5, True, D(policy={})):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    profiles.policy_keys(bad)
        for bad in (None, [], "x", 5, True, D()):
            with self.subTest(policy=bad):
                with self.assertRaises(ValueError):
                    self.pk(bad)
        with self.assertRaises(ValueError):
            self.pk({"a": D(b=1)})

    def test_policy_keys_missing_policy(self):  # PK11
        for bad in ({"defaults": {}}, {}):
            with self.assertRaises(ValueError):
                profiles.policy_keys(bad)

    def test_policy_keys_no_mutation(self):  # PK12
        preset = {"defaults": {"top_tier_roles": ["a"]}, "policy": {"block": {"max_tasks": 3}, "x": {"y": []}}}
        before = copy.deepcopy(preset)
        profiles.policy_keys(preset)
        self.assertEqual(preset, before)

    def test_policy_keys_types(self):  # PK13
        r = self.pk({"block": {"max_tasks": 3}})
        self.assertIs(type(r), frozenset)
        self.assertTrue(all(type(k) is str for k in r))

    def test_policy_keys_of_real_profiles(self):  # PK14
        self.assertEqual([profiles.policy_keys(profiles.load(p)) for p in profiles.PROFILES],
                         [frozenset(), frozenset({"block.max_tasks"}), frozenset({"block.max_tasks"})])

    def test_limits_not_a_policy_key(self):  # LM2
        for p in profiles.PROFILES:
            self.assertFalse([k for k in profiles.policy_keys(profiles.load(p)) if k.startswith("limits")])


# ------------------------------------------------------------------------------------------------------ M, OV
class MergeCase(GitIsolatedTestCase):
    def setUp(self):
        super().setUp()
        self.root = make_repo(self.work)
        self.path = os.path.join(self.root, CONFIG_PATH)

    def write(self, extra=None, drop=()):
        cfg = dict(minimal_config(), **(extra or {}))
        for k in drop:
            del cfg[k]
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write(emit(cfg))

    def write_raw(self, extra_text, base=None):
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write(emit(base or minimal_config()) + extra_text)

    def load(self, extra=None, **kw):
        self.write(extra, **kw)
        return config.load(self.root)

    def load_data(self, extra, base=None):
        """config.load with the parsed config document injected (the subset cannot write ``{}``)."""
        data = dict(base or minimal_config(), **extra)
        real = yamlsub.load
        with mock.patch.object(yamlsub, "load",
                               side_effect=lambda p, s: copy.deepcopy(data) if s == CONFIG_PATH else real(p, s)):
            return config.load(self.root)

    def refused(self, extra, *needles, data=False, **kw):
        with self.assertRaises(GateError) as e:
            (self.load_data(extra) if data else self.load(extra, **kw))
        msg = str(e.exception)
        for n in needles:
            self.assertIn(n, msg)
        self.assertNotIn(self.root, msg)
        return msg

    def refused_raw(self, text, *needles):
        self.write_raw(text)
        with self.assertRaises(GateError) as e:
            config.load(self.root)
        for n in needles:
            self.assertIn(n, str(e.exception))
        return str(e.exception)

    def fw_case(self, files, sub="fw"):
        fw = os.path.join(self.tmp, sub)
        os.makedirs(os.path.join(fw, "profiles"))
        for n, t in files.items():
            with open(os.path.join(fw, "profiles", n + ".yml"), "w") as fh:
                fh.write(t)
        p = mock.patch.object(plugin, "framework_dir", return_value=fw)
        p.start()
        self.addCleanup(p.stop)
        return fw


def ovr(key, value, decision=DEC):
    return {"overrides": {key: {"value": value, "decision": decision}}}


class MergeTest(MergeCase):
    def test_profile_selects_preset(self):  # M1, M31-M33
        self.assertEqual(self.load({"profile": "light"}).get("block"), None)
        self.assertEqual(self.load({"profile": "standard"})["block"], {"max_tasks": 5})
        self.assertEqual(self.load({"profile": "strict"})["block"], {"max_tasks": 3})

    def test_strict_policy_applied(self):  # M31
        self.assertEqual(self.load()["block"], {"max_tasks": 3})

    def test_standard_policy_applied(self):  # M32
        self.assertEqual(self.load({"profile": "standard"})["block"], {"max_tasks": 5})

    def test_light_policy_applied_nothing(self):  # M33
        self.assertNotIn("block", self.load({"profile": "light"}))

    def test_profile_absent_still_refused(self):  # M2
        self.refused({}, ".strict-delivery/config.yml: profile: required key is missing", drop=("profile",))

    def test_unknown_profile_refused_before_profile_read(self):  # M3
        self.fw_case({})  # no profile file at all: the profile name is refused first
        for v in ("Strict", " strict", "loose", "", 1, None, True, ["strict"]):
            with self.subTest(v=v):
                self.assertEqual(self.refused({"profile": v}),
                                 ".strict-delivery/config.yml: profile: must be one of light, standard, strict")
        self.assertEqual(self.refused({"profile": {"a": 1}}),
                         ".strict-delivery/config.yml: profile: must be one of light, standard, strict")

    def test_profile_file_missing_fails_closed(self):  # M4
        self.fw_case({"light": TEXT["light"]})
        self.refused({}, "profiles/strict.yml")

    def test_profile_file_missing_fails_closed_through_a_gate(self):  # M4: a gate in a subprocess
        import shutil
        copy_dir = os.path.join(self.tmp, "copy")
        shutil.copytree(os.path.join(REPO, "gates"), os.path.join(copy_dir, "gates"),
                        ignore=shutil.ignore_patterns("__pycache__"))
        os.makedirs(os.path.join(copy_dir, "profiles"))
        env = dict(os.environ, PYTHONPATH=copy_dir)
        p = subprocess.run([sys.executable, "-m", "gates", "check", "schema", "--root", self.root], cwd=copy_dir,
                           env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out = p.stdout.decode() + p.stderr.decode()
        self.assertEqual(p.returncode, 1, out)
        self.assertIn("FAIL", out)
        self.assertIn("profiles/strict.yml", out)

    def test_profile_errors_propagate(self):  # M5
        base = TEXT["strict"]
        for i, text in enumerate(("", "a: [1\n", base + "extra: 1\n", base.replace("max_tasks: 3", "max_tasks: 0"),
                                  base.replace("profile: strict", "profile: light"))):
            with self.subTest(text=text):
                self.fw_case({"strict": text}, sub="fw%d" % i)
                msg = self.refused({}, "profiles/strict.yml: ")
                self.assertFalse(msg.startswith(".strict-delivery/config.yml"))

    def test_root_profiles_dir_never_read(self):  # M6
        os.makedirs(os.path.join(self.root, "profiles"))
        with open(os.path.join(self.root, "profiles", "strict.yml"), "w") as fh:
            fh.write(TEXT["strict"].replace("max_tasks: 3", "max_tasks: 99"))
        self.assertEqual(self.load()["block"]["max_tasks"], 3)

    def test_step1_errors_before_profile_read(self):  # M7
        self.fw_case({})
        self.refused({"bogus": 1}, "unknown key 'bogus'")

    def test_load_signature_unchanged(self):  # M8
        sig = inspect.signature(config.load)
        self.assertEqual(list(sig.parameters), ["root"])
        self.assertEqual(sig.parameters["root"].default, inspect.Parameter.empty)
        self.assertIn(str(sig).replace("'", ""), ("(root: str) -> dict",))

    def test_profile_defaults_fill_omitted_keys(self):  # M9
        self.assertEqual(self.load()["top_tier_roles"], ROLES)
        self.assertNotIn("top_tier_fallback", self.load())

    def test_file_wins_over_profile_defaults(self):  # M10
        self.assertEqual(self.load({"top_tier_roles": ["x"]})["top_tier_roles"], ["x"])

    def test_file_default_keys_unchecked_as_before(self):  # M11
        for v in ([""], "x", 5, None, []):
            with self.subTest(v=v):
                self.assertEqual(self.load({"top_tier_roles": v})["top_tier_roles"], v)
        self.assertIs(self.load({"top_tier_fallback": True})["top_tier_fallback"], True)

    def test_profile_top_tier_fallback_default(self):  # M12
        self.fw_case({"strict": TEXT["strict"].replace("defaults:\n", "defaults:\n  top_tier_fallback: tier2\n")})
        self.assertEqual(self.load()["top_tier_fallback"], "tier2")
        self.assertEqual(self.load({"top_tier_fallback": "tier3"})["top_tier_fallback"], "tier3")

    def test_profile_default_empty_list(self):  # M13
        self.fw_case({"light": TEXT["light"].replace("[final_verifier, exception_reviewer]", "[]")})
        self.assertEqual(self.load({"profile": "light"})["top_tier_roles"], [])

    def test_profile_defaults_not_aliased(self):  # M14
        a = self.load()
        a["top_tier_roles"].append("x")
        a["block"]["max_tasks"] = 99
        b = self.load()
        self.assertEqual(b["top_tier_roles"], ROLES)
        self.assertEqual(b["block"], {"max_tasks": 3})
        self.assertNotIn("top_tier_roles", config.DEFAULTS)
        self.assertNotIn("block", config.DEFAULTS)

    def test_defaults_never_mutated_by_profile_merge(self):  # M15
        before = copy.deepcopy(config.DEFAULTS)
        for p in profiles.PROFILES:
            self.load({"profile": p})
            self.load({"profile": p, "block": {"max_tasks": 4}} if p == "light" else {"profile": p})  # 4a.3: typed
        self.assertEqual(config.DEFAULTS, before)

    def test_repo_top_tier_roles_equals_profile_default(self):  # M16
        cfg = config.load(REPO)
        self.assertEqual(cfg["top_tier_roles"], ROLES)

    def test_file_null_default_key_wins(self):  # M17
        self.write_raw("top_tier_roles:\n")
        self.assertIsNone(config.load(self.root)["top_tier_roles"])

    # ---- step 3
    def test_policy_key_in_file_refused(self):  # M20
        self.assertEqual(self.refused({"block": {"max_tasks": 4}}),
                         ".strict-delivery/config.yml: block.max_tasks: preset by profile strict; change it under "
                         "overrides with the authorising decision")

    def test_policy_key_same_value_refused(self):  # M21
        self.refused({"block": {"max_tasks": 3}}, "block.max_tasks: preset by profile strict")

    def test_policy_key_refusal_per_profile(self):  # M22
        cfg = self.load({"profile": "light", "block": {"max_tasks": 4}})
        self.assertEqual(cfg["block"], {"max_tasks": 4})
        self.refused({"profile": "standard", "block": {"max_tasks": 4}}, "block.max_tasks: preset by profile standard")

    def test_refusal_names_the_profile(self):  # M23
        for p in ("standard", "strict"):
            self.refused({"profile": p, "block": {"max_tasks": 4}}, "preset by profile %s;" % p)

    def test_policy_key_among_others(self):  # M24
        msg = self.refused({"block": {"max_tasks": 4, "other": 1}}, "block.max_tasks: preset by profile")
        self.assertNotIn("block.other", msg)

    def test_empty_block_in_file_accepted(self):  # M25
        self.assertEqual(self.load_data({"block": {}})["block"], {"max_tasks": 3})

    def test_block_other_subkey_untouched(self):  # M26, M34; Task 4a.3 (ST9): the typed reader refuses it
        self.refused({"block": {"other": 1}}, ".strict-delivery/config.yml: unknown key 'block.other'")

    def test_policy_merges_into_block_mapping(self):  # M34; Task 4a.3 (ST9): the typed reader refuses it
        self.refused({"profile": "standard", "block": {"other": 1}},
                     ".strict-delivery/config.yml: unknown key 'block.other'")

    def test_block_non_mapping_refused_when_preset(self):  # M27
        for p in ("strict", "standard"):
            for v in ([1, 2], 5, "x", None, True):
                with self.subTest(p=p, v=v):
                    self.refused({"profile": p, "block": v}, ".strict-delivery/config.yml: block: must be a mapping")
        for v in ([1, 2], 5, "x", None, True):  # Task 4a.3 (ST9, BL3): the same text under light
            with self.subTest(light=v):
                self.refused({"profile": "light", "block": v}, ".strict-delivery/config.yml: block: must be a mapping")

    def test_dotted_top_level_key_unknown(self):  # M28
        self.write_raw("block.max_tasks: 4\n")
        with self.assertRaises(GateError) as e:
            config.load(self.root)
        self.assertEqual(str(e.exception), ".strict-delivery/config.yml: unknown key 'block.max_tasks'")

    def test_policy_key_case_variants(self):  # M29
        self.refused({"Block": {"max_tasks": 4}}, "unknown key 'Block'")
        self.refused({"block": {"Max_tasks": 4}}, ".strict-delivery/config.yml: unknown key 'block.Max_tasks'")  # 4a.3

    def test_policy_refusal_precedes_schema_tag(self):  # M30
        msg = self.refused({"schema": "config/1", "block": {"max_tasks": 4}}, "preset by profile strict")
        self.assertNotIn("upgrade", msg)
        self.assertIn("run /strict-delivery:upgrade", self.refused({"schema": "config/1"}))

    def test_override_applies_value(self):  # M35, OV20
        self.assertEqual(self.load(ovr("block.max_tasks", 4))["block"]["max_tasks"], 4)
        self.assertEqual(self.load(dict(ovr("block.max_tasks", 9), profile="standard"))["block"]["max_tasks"], 9)

    def test_block_check_is_4a3s(self):  # M41; Task 4a.3 (ST9): the typed block reader now exists
        self.assertEqual(self.load()["block"], {"max_tasks": 3})
        self.refused({"profile": "light", "block": {"max_tasks": 0}},
                     ".strict-delivery/config.yml: block.max_tasks: must be an integer of at least 1")

    def test_bad_ids_prefix_with_overrides_is_gateerror(self):  # M42
        self.refused(dict(ovr("block.max_tasks", 4), ids={"decision": 5}), "ids.decision: must be a prefix of capital "
                                                                           "letters A-Z")
        self.refused(dict(ovr("block.max_tasks", 4), ids={"decision": ["x"]}), "ids.decision")

    def test_light_adds_only_top_tier_roles(self):  # M43
        light = self.load({"profile": "light"})
        self.assertIs(type(light), dict)
        keys = set(light) - {"schema", "framework_version", "profile", "paths", "ids", "base_branch", "decisions",
                             "models", "drift", "decision_classes", "merge", "reviews", "context"}
        self.assertEqual(keys, {"top_tier_roles"})

    def test_load_reads_only_expected_files(self):  # M44
        seen = []
        real_open, real_os_open = builtins.open, os.open
        roots = (self.root, os.path.join(REPO, "profiles"), os.path.join(REPO, "gates", "schemas"))

        def watch(p):
            if isinstance(p, str) and p.startswith(roots):
                seen.append(p)

        def fake_open(p, *a, **k):
            watch(p)
            return real_open(p, *a, **k)

        def fake_os_open(p, *a, **k):
            watch(p)
            return real_os_open(p, *a, **k)
        self.write()
        with mock.patch.object(builtins, "open", fake_open), mock.patch.object(os, "open", fake_os_open):
            config.load(self.root)
        self.assertEqual(set(seen), {self.path, os.path.join(REPO, "profiles", "strict.yml"),
                                     os.path.join(REPO, "gates", "schemas", "profile.yml")})

    def test_this_repo_config_loads(self):  # FL10, RP1
        self.assertEqual(config.load(REPO)["block"]["max_tasks"], 3)

    def test_repo_config_unchanged_by_this_task(self):  # RP2: the file still holds its own top_tier_roles
        with open(os.path.join(REPO, CONFIG_PATH), encoding="utf-8") as fh:
            self.assertIn("top_tier_roles: [final_verifier, exception_reviewer]", fh.read())

    def test_exception_groups_propagate(self):  # V3
        if not HAS_BEG:
            self.skipTest("no BaseExceptionGroup before Python 3.11")
        for exc in (BaseExceptionGroup("x", [KeyboardInterrupt()]), ExceptionGroup("x", [ValueError()])):
            real = yamlsub.load
            calls = []

            def fake(p, s, exc=exc):
                calls.append(s)
                if s != CONFIG_PATH:
                    raise exc
                return real(p, s)
            self.write()
            with mock.patch.object(yamlsub, "load", side_effect=fake):
                with self.assertRaises(type(exc)):
                    config.load(self.root)
                with self.assertRaises(type(exc)):
                    profiles.load("strict")
            self.assertTrue(any(c.startswith("profiles/") for c in calls))


class OverridesTest(MergeCase):
    def bad(self, extra, *needles, **kw):
        return self.refused(extra, ".strict-delivery/config.yml: overrides", *needles, **kw)

    def test_no_overrides_by_default(self):  # OV1
        self.assertNotIn("overrides", self.load())

    def test_overrides_not_a_mapping(self):  # OV2
        for v in (3, "x", True, [1], [], None):
            with self.subTest(v=v):
                self.assertEqual(self.refused({"overrides": v}, data=True),
                                 ".strict-delivery/config.yml: overrides: must be a mapping")

    def test_overrides_empty_mapping(self):  # OV3
        self.assertEqual(self.load_data({"overrides": {}})["overrides"], {})

    def test_override_entry_not_a_mapping(self):  # OV4
        for v in (4, None, [4], "x"):
            with self.subTest(v=v):
                self.assertEqual(self.refused({"overrides": {"block.max_tasks": v}}, data=True),
                                 ".strict-delivery/config.yml: overrides.block.max_tasks: must be a mapping")

    def test_override_missing_value(self):  # OV5
        self.assertEqual(self.refused({"overrides": {"block.max_tasks": {"decision": DEC}}}),
                         ".strict-delivery/config.yml: overrides.block.max_tasks.value: required key is missing")

    def test_override_missing_decision(self):  # OV6
        self.assertEqual(self.refused({"overrides": {"block.max_tasks": {"value": 4}}}),
                         ".strict-delivery/config.yml: overrides.block.max_tasks.decision: required key is missing")

    def test_override_empty_entry(self):  # OV7
        self.assertEqual(self.refused({"overrides": {"block.max_tasks": {}}}, data=True),
                         ".strict-delivery/config.yml: overrides.block.max_tasks.value: required key is missing")

    def test_override_extra_key(self):  # OV8
        self.assertEqual(self.refused({"overrides": {"block.max_tasks": {"value": 4, "decision": DEC, "note": "x"}}}),
                         ".strict-delivery/config.yml: overrides.block.max_tasks.note: unknown key")

    def test_override_entry_key_spelling(self):  # OV9
        for k in ("Value", "value ", "Decision", "value\n"):
            with self.subTest(k=k):
                entry = {"value": 4, "decision": DEC}
                entry[k] = entry.pop("value" if k.lower().startswith("value") else "decision")
                self.bad({"overrides": {"block.max_tasks": entry}}, "block.max_tasks.")

    def test_override_value_kind(self):  # OV10
        for v in (4, "x", True, ["a", "b"]):
            with self.subTest(v=v):  # the shape rule passes; the key's own rule decides (only ints pass block.max_tasks)
                out = None
                try:
                    out = self.load(dict(ovr("limits.max_children.session", v)))
                except GateError as e:
                    out = str(e)
                if v == 4:
                    self.assertEqual(out["limits"]["max_children"]["session"], 4)
                else:
                    self.assertIn("overrides.limits.max_children.session.value", out)
        for v in ({"a": 1}, None):
            with self.subTest(v=v):
                self.assertEqual(self.refused(ovr("block.max_tasks", v), data=True),
                                 ".strict-delivery/config.yml: overrides.block.max_tasks.value: must be a scalar or a "
                                 "list")

    def test_override_duplicate_key(self):  # OV11
        self.refused_raw("overrides:\n  block.max_tasks:\n    value: 4\n    decision: %s\n  block.max_tasks:\n"
                         "    value: 5\n    decision: %s\n" % (DEC, DEC), "duplicate key", "(line ")

    def test_two_overrides_both_applied(self):  # OV12
        cfg = self.load({"overrides": {"block.max_tasks": {"value": 4, "decision": DEC},
                                       "limits.max_depth": {"value": 2, "decision": DEC}}})
        self.assertEqual((cfg["block"]["max_tasks"], cfg["limits"]["max_depth"]), (4, 2))

    def test_overrides_kept_as_written(self):  # OV13
        want = {"block.max_tasks": {"value": 4, "decision": DEC}, "limits.max_depth": {"value": 2, "decision": DEC}}
        cfg = self.load({"overrides": want})
        self.assertEqual(cfg["overrides"], want)
        self.assertEqual(list(cfg["overrides"]), ["block.max_tasks", "limits.max_depth"])

    def test_many_overrides_first_failure_named(self):  # OV14
        ov = {"limits.max_children.r%d" % i: {"value": 2, "decision": DEC} for i in range(1000)}
        self.assertEqual(len(self.load({"overrides": ov})["limits"]["max_children"]), 1000)
        ov["limits.max_children.r500"]["value"] = 0
        ov["limits.max_children.r700"]["value"] = 0
        self.bad({"overrides": ov}, "overrides.limits.max_children.r500.value")

    # ---- the key
    def test_override_policy_key_under_light_refused(self):  # OV21
        self.bad(dict(ovr("block.max_tasks", 4), profile="light"), "not a policy key of profile light")

    def test_override_of_non_policy_key_refused(self):  # OV22
        self.assertIn("overrides.paths.state", self.refused(ovr("paths.state", "x")))

    def test_override_non_policy_keys_refused(self):  # OV23
        for k in ("profile", "top_tier_roles", "merge.mode", "models.tiers.tier1", "decision_classes.owner_only",
                  "schema", "overrides", "overrides.x"):
            with self.subTest(k=k):
                self.bad(ovr(k, "x"), "overrides.%s:" % k)

    def test_override_policy_key_prefix_refused(self):  # OV24
        self.bad(ovr("block", 4), "overrides.block:")

    def test_override_policy_key_suffix_refused(self):  # OV25
        for k in ("block.max_tasks.x", "block.max_tasks."):
            with self.subTest(k=k):
                self.bad(ovr(k, 4), "overrides.%s:" % k)

    def test_limits_override_allowed(self):  # OV26, LM3
        cfg = self.load(ovr("limits.max_children.stream_controller", 2))
        self.assertEqual(cfg["limits"], {"max_children": {"stream_controller": 2}})
        for k in ("limits.max_depth", "limits.max_concurrent", "limits.max_children.session"):
            with self.subTest(k=k):
                node = self.load(ovr(k, 4))["limits"]
                for seg in k.split(".")[1:]:
                    node = node[seg]
                self.assertEqual(node, 4)

    def test_limits_override_unknown_keys_refused(self):  # OV27
        for k in ("limits.max_kids", "limits.max_children", "limits", "limits.", "limits.max_depth.x",
                  "limits.max_children.", "limits.max_children.a.b", "limits.max_children..a", "limitsX.max_depth"):
            with self.subTest(k=k):
                self.bad(ovr(k, 2), "overrides.%s:" % k)

    def test_limits_override_role_grammar(self):  # OV28
        for role in ("Impl", "1x", "a-b", "é", "a b", "a\n", "A", "a" * 300 + "!"):
            with self.subTest(role=role[:10]):
                self.bad(ovr("limits.max_children." + role, 2), "overrides.limits.max_children.")
        self.assertEqual(self.load(ovr("limits.max_children." + "a" * 300, 2))["limits"]["max_children"],
                         {"a" * 300: 2})

    def test_override_key_grammar(self):  # OV29
        for k in ("", " ", ".x", "x.", "a..b", "a b", "BLOCK.max_tasks", "block.max_tasks ", "block.max_tasks\n",
                  "block.max_tasks\r", "block.max_tasks\x00", "\ufeffblock.max_tasks", "block\uff0emax_tasks",
                  "b" * 5000):
            with self.subTest(k=k[:20]):
                msg = self.refused(ovr(k, 4), data=True)
                self.assertIn(".strict-delivery/config.yml: overrides.", msg)
                self.assertNotIn("\n", msg)
                self.assertNotIn("\x00", msg)
                self.assertNotIn("\ufeff", msg)

    def test_override_non_str_key_injected(self):  # OV30
        self.refused({"overrides": {1: {"value": 4, "decision": DEC}}}, "overrides.1:", data=True)

    def test_override_into_non_mapping_node_is_gateerror(self):  # OV31
        self.assertEqual(self.refused(dict(ovr("limits.max_depth", 2), limits=5)),
                         ".strict-delivery/config.yml: limits: must be a mapping")
        self.assertEqual(self.refused(dict(ovr("limits.max_children.x", 2), limits={"max_children": [1]})),
                         ".strict-delivery/config.yml: limits.max_children: must be a mapping")

    # ---- the value
    def test_override_policy_value_valid(self):  # OV40
        for v in (1, 4, 5, 7 * 10 ** 0):
            self.assertEqual(self.load(ovr("block.max_tasks", v))["block"]["max_tasks"], v)
        self.write_raw("overrides:\n  block.max_tasks:\n    value: %s\n    decision: %s\n" % ("7" * 600, DEC))
        self.assertEqual(config.load(self.root)["block"]["max_tasks"], int("7" * 600))

    def test_override_value_fails_key_check(self):  # OV41
        for v in (0, -1, True, False, "3", "4", 2.5, None, [3], {"a": 1}, ""):
            with self.subTest(v=v):
                self.refused(ovr("block.max_tasks", v), "overrides.block.max_tasks.value: ", data=True)
        self.assertEqual(self.refused(ovr("block.max_tasks", 0)),
                         ".strict-delivery/config.yml: overrides.block.max_tasks.value: must be at least 1")
        self.assertEqual(self.refused(ovr("block.max_tasks", "3")),
                         ".strict-delivery/config.yml: overrides.block.max_tasks.value: must be an integer")

    def test_override_value_digit_caps(self):  # OV42, V1
        for digits in (601, 1000, 1001, 4300, 4301):
            with self.subTest(digits=digits):
                for key in ("block.max_tasks", "limits.max_depth", "limits.max_children.x"):
                    self.write_raw("overrides:\n  %s:\n    value: %s\n    decision: %s\n" % (key, "7" * digits, DEC))
                    with self.assertRaises(GateError) as e:
                        config.load(self.root)
                    msg = str(e.exception)
                    self.assertTrue("at most 600 digits" in msg or "integer too large" in msg, msg)
                    self.assertNotIn("Exceeds", msg)
                    self.assertNotIn("7777", msg)

    def test_limits_override_value_check(self):  # OV43
        for key in ("limits.max_depth", "limits.max_concurrent"):
            for v in (1, 4):
                self.assertEqual(self.load(ovr(key, v))["limits"][key.split(".")[1]], v)
            for v in (0, -1, True, "4", None, [2]):
                with self.subTest(key=key, v=v):
                    self.refused(ovr(key, v), "overrides.%s.value: " % key, data=True)

    def test_limits_override_max_children_value(self):  # OV44
        key = "limits.max_children.stream_controller"
        for v in (1, 2):
            self.assertEqual(self.load(ovr(key, v))["limits"]["max_children"]["stream_controller"], v)
        for v in (0, True, "2", [2], None):
            with self.subTest(v=v):
                self.refused(ovr(key, v), "overrides.%s.value: " % key, data=True)

    def test_override_errors_precede_validate_errors(self):  # the plan's order: step 5 before step 6
        self.refused(dict(ovr("block.max_tasks", 0), drift={"estimate_factor_pct": 0}),
                     "overrides.block.max_tasks.value")

    def test_override_equal_to_preset_accepted(self):  # OV45
        self.assertEqual(self.load(ovr("block.max_tasks", 3))["block"]["max_tasks"], 3)

    def test_override_loosening_accepted_here(self):  # OV46
        self.assertEqual(self.load(ovr("block.max_tasks", 99))["block"]["max_tasks"], 99)

    def test_override_wins_over_direct_limits(self):  # OV48, LM4
        cfg = self.load(dict(ovr("limits.max_children.stream_controller", 2),
                             limits={"max_children": {"stream_controller": 4}}))
        self.assertEqual(cfg["limits"]["max_children"]["stream_controller"], 2)
        self.assertEqual(self.load(ovr("block.max_tasks", 4))["block"]["max_tasks"], 4)

    # ---- the decision
    def test_override_decision_valid(self):  # OV50
        self.assertEqual(self.load(ovr("block.max_tasks", 4, DEC))["block"]["max_tasks"], 4)

    def test_override_decision_uses_configured_prefix(self):  # OV51
        self.assertEqual(self.load(dict(ovr("block.max_tasks", 4, "SD-20261111-abcd"),
                                        ids={"decision": "SD"}))["block"]["max_tasks"], 4)
        self.refused(dict(ovr("block.max_tasks", 4, DEC), ids={"decision": "SD"}),
                     "overrides.block.max_tasks.decision: id does not match the form; expected SD-<YYYYMMDD>-<xxxx>")

    def test_override_decision_malformed(self):  # OV52
        for d in ("", "F-20261111-abcd", "dec-20261111-abcd", "DEC-20261111-ABCD", "DEC-20261111-abc0",
                  "DEC-20261301-abcd", "DEC-20261111-abcd\n", "DEC-２０２６1111-abcd", "DEC-20261111-abcd ",
                  "DEC-20261111-abc\ua7c0"):
            with self.subTest(d=d):
                msg = self.refused(ovr("block.max_tasks", 4, d), data=True)
                self.assertIn(".strict-delivery/config.yml: overrides.block.max_tasks.decision: id ", msg)
                self.assertNotIn("\n", msg)

    def test_override_decision_wrong_types(self):  # OV53
        for d in (None, 5, True, [DEC], {"a": 1}):
            with self.subTest(d=d):
                self.refused(ovr("block.max_tasks", 4, d), "overrides.block.max_tasks.decision: id is not a string (",
                             data=True)

    def test_override_decision_long(self):  # OV54
        self.refused(ovr("block.max_tasks", 4, "DEC-" + "9" * 100000), "overrides.block.max_tasks.decision: id does "
                     "not match the form")

    def test_override_decision_not_looked_up(self):  # OV55
        self.assertEqual(self.load(ovr("block.max_tasks", 4, "DEC-20990101-zzzz"))["block"]["max_tasks"], 4)

    def test_override_same_decision_twice(self):  # OV56
        cfg = self.load({"overrides": {"block.max_tasks": {"value": 4, "decision": DEC},
                                       "limits.max_depth": {"value": 2, "decision": DEC}}})
        self.assertEqual(cfg["limits"]["max_depth"], 2)

    # ---- limits, two routes
    def test_direct_limits_still_allowed(self):  # LM1
        self.assertEqual(self.load({"limits": {"max_depth": 4}})["limits"]["max_depth"], 4)

    def test_limits_both_routes_different_keys(self):  # LM5
        cfg = self.load(dict(ovr("limits.max_concurrent", 2), limits={"max_depth": 4}))
        self.assertEqual(cfg["limits"], {"max_depth": 4, "max_concurrent": 2})

    def test_limits_merged_validates(self):  # LM6
        self.assertEqual(self.load(ovr("limits.max_depth", 3))["limits"], {"max_depth": 3})

    def test_invalid_direct_limits_with_override(self):  # LM7
        self.refused(dict(ovr("limits.max_depth", 4), limits={"max_depth": 0}),
                     ".strict-delivery/config.yml: limits.max_depth: must be an integer of at least 1")

    def test_limits_override_merges_into_direct_mapping(self):  # LM8
        cfg = self.load(dict(ovr("limits.max_children.b", 2), limits={"max_children": {"a": 1}}))
        self.assertEqual(cfg["limits"]["max_children"], {"a": 1, "b": 2})


class VersionTest(unittest.TestCase):
    def test_names_and_keys_are_unicode_version_independent(self):  # V2
        for ch in ("\ua7c0", "\U0001fae8"):
            with self.subTest(ch=ascii(ch)):
                with self.assertRaises(GateError):
                    profiles.load("strict" + ch)
                with self.assertRaises(GateError):
                    profiles.load(ch)


if __name__ == "__main__":
    unittest.main()
