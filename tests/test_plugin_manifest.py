"""Tests of the plugin manifests and gates/lib/plugin.py (Task 3d.1 input-domain rows M, V, R, K, S) and of
``COMMANDS["hook"]`` (rows H). Expected texts are written by hand from the plan and the controller decisions D1-D10;
the plugin functions run on fixture directories, the hook command through ``python3 -m gates hook`` in a subprocess on
a copy of the ``gates`` package (with and without a ``gates/hook.py`` fixture), never on the real tree."""
import builtins
import contextlib
import importlib.machinery
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from gates import __main__ as gates_main
from gates.lib import config, plugin
from gates.lib.result import GateError
from tests import prose_check

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P = ".claude-plugin/plugin.json"
DESCRIPTION = "Strict delivery process for agent-built software: roles, gates and hooks that verify every change."
HAS_BEG = hasattr(builtins, "BaseExceptionGroup")
# the V2 rows (version text), shared with tests/test_run_all.py so that no row can be missed there (F-3d1-R1-2)
V2_ROWS = ["0.0.0 ", " 0.0.0", "0.0.0\n", "v0.1.0", "0.1", "0.1.0.0", "0.01.0", "00.1.0", "0.1.0-rc1",
           "0.1.0+b", "１.0.0", "٠.0.0", "1.2.3٠", "-1.0.0", "1..0", "1.0.", "", "x.y.z", "0.0.0\x00"]
NOT_FINITE = "a number that is not finite is not allowed"   # row M4 (decision P4)
# the M4 bodies that are non-finite numbers (decision P4), shared with tests/test_run_all.py
NOT_FINITE_BODIES = [b'{"a": 1e400}', b'{"a": -1e400}', b'{"a": [1e400]}', b'{"a": {"b": -1e400}}',
                     b'{"a": 1E999}', b'{"a": 1.5e400}', b'{"a": 1e309}']


def read(rel):
    with open(os.path.join(REPO, *rel.split("/")), encoding="utf-8") as fh:
        return fh.read()


def real_manifest():
    return json.loads(read(P))


def marketplace():
    return json.loads(read(".claude-plugin/marketplace.json"))


class FixtureCase(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.tmp = os.path.realpath(td.name)
        self._n = 0

    def fixture_dir(self, data, raw=False):
        """A framework directory whose plugin.json holds ``data`` (an object dumped as JSON, or bytes when raw)."""
        self._n += 1
        d = os.path.join(self.tmp, "fw%d" % self._n)
        os.makedirs(os.path.join(d, ".claude-plugin"))
        body = data if raw else json.dumps(data).encode("utf-8")
        with open(os.path.join(d, ".claude-plugin", "plugin.json"), "wb") as fh:
            fh.write(body)
        return d

    def with_key(self, key, value):
        m = real_manifest()
        m[key] = value
        return self.fixture_dir(m)

    def without_key(self, key):
        m = real_manifest()
        del m[key]
        return self.fixture_dir(m)

    def refused(self, fn, d, text):
        with self.assertRaises(GateError) as cm:
            fn(d)
        self.assertEqual(str(cm.exception), text)


class ShapeTest(unittest.TestCase):
    ALLOWED_KEYS = ["name", "version", "description", "author", "license", "repository", "dependencies"]

    def test_plugin_manifest_shape(self):  # K1, D3
        m = real_manifest()
        self.assertEqual(sorted(m), sorted(self.ALLOWED_KEYS))
        self.assertEqual(m["name"], "strict-delivery")
        self.assertEqual(m["author"], {"name": "Benjamin Swanepoel"})
        self.assertEqual(m["license"], "MIT")
        self.assertEqual(m["repository"], "https://github.com/superbrobenji/strict-delivery")
        self.assertEqual(m["description"], DESCRIPTION)
        self.assertNotIn("hooks", m)
        self.assertNotIn("skills", m)

    def test_marketplace_shape(self):  # K1, D3
        k = marketplace()
        self.assertEqual(sorted(k), sorted(["name", "owner", "plugins", "allowCrossMarketplaceDependenciesOn"]))
        self.assertEqual(k["name"], "strict-delivery")
        self.assertEqual(k["owner"], {"name": "Benjamin Swanepoel"})
        self.assertEqual(k["allowCrossMarketplaceDependenciesOn"], ["claude-plugins-official"])
        self.assertEqual(len(k["plugins"]), 1)
        entry = k["plugins"][0]
        self.assertEqual(sorted(entry), sorted(["name", "source", "version", "description"]))
        self.assertEqual((entry["name"], entry["source"], entry["description"]),
                         ("strict-delivery", "./", DESCRIPTION))

    def test_files_are_two_space_json_with_trailing_newline_ascii(self):  # D3
        for rel in (P, ".claude-plugin/marketplace.json"):
            with self.subTest(rel=rel):
                with open(os.path.join(REPO, *rel.split("/")), "rb") as fh:
                    raw = fh.read()
                text = raw.decode("ascii")
                self.assertTrue(text.endswith("}\n"))
                self.assertEqual(text, json.dumps(json.loads(text), indent=2) + "\n")

    def test_versions_agree(self):  # K1; controller ruling; spec 15
        v = plugin.version(REPO)
        self.assertEqual(v, "0.0.0")
        self.assertEqual(v, marketplace()["plugins"][0]["version"])
        self.assertEqual(v, config.load(REPO)["framework_version"])

    def test_dependency_declared(self):  # K3; spec 3; Q-B3plan-5 (a)
        self.assertEqual(real_manifest()["dependencies"], [{"name": "superpowers", "marketplace": "claude-plugins-official"}])

    def test_no_forbidden_strings(self):  # K2
        text = json.dumps(without_repository(real_manifest()), indent=2) + "\n" + read(".claude-plugin/marketplace.json")
        self.assertEqual(prose_check.forbidden_hits(text), [])

    def test_forbidden_check_skips_only_repository(self):  # K2; F-docs2-4
        m = real_manifest()
        m["description"] = "see superbrobenji"
        hits = prose_check.forbidden_hits(json.dumps(without_repository(m), indent=2) + "\n")
        self.assertEqual([h[0] for h in hits], ["owner-handle"])
        # the real repository value names the owner and is skipped; a handle in description is a hit
        self.assertIn("superbrobenji", real_manifest()["repository"])
        self.assertEqual(prose_check.forbidden_hits(json.dumps(without_repository(real_manifest()), indent=2)), [])
        # only that one field is skipped: the same handle in another field is still a hit
        m = real_manifest()
        m["author"] = {"name": "superbrobenji"}
        self.assertNotEqual(prose_check.forbidden_hits(json.dumps(without_repository(m), indent=2)), [])


def without_repository(m):
    m = dict(m)
    m.pop("repository", None)
    return m


class FrameworkDirTest(unittest.TestCase):
    def test_framework_dir_is_the_parent_of_the_gates_package(self):  # D4
        d = plugin.framework_dir()
        self.assertEqual(d, REPO)
        self.assertTrue(os.path.isabs(d))
        self.assertTrue(os.path.isfile(os.path.join(d, "gates", "__init__.py")))
        # no cwd or environment lookup: a changed cwd and a decoy variable change nothing
        with mock.patch.dict(os.environ, {"CLAUDE_PLUGIN_ROOT": "/nonexistent"}):
            cwd = os.getcwd()
            try:
                os.chdir(tempfile.gettempdir())
                self.assertEqual(plugin.framework_dir(), REPO)
            finally:
                os.chdir(cwd)


class ManifestTest(FixtureCase):
    def test_manifest_reads_the_real_file(self):
        self.assertEqual(plugin.manifest(REPO), real_manifest())

    def test_m1_file_absent(self):  # M1
        d = os.path.join(self.tmp, "a")
        os.makedirs(os.path.join(d, ".claude-plugin"))
        self.refused(plugin.manifest, d, P + ": cannot be read (FileNotFoundError)")

    def test_m1_directory_at_the_path(self):  # M1
        d = os.path.join(self.tmp, "b")
        os.makedirs(os.path.join(d, ".claude-plugin", "plugin.json"))
        self.refused(plugin.manifest, d, P + ": is not a regular file")

    def test_m1_plugin_dir_absent(self):  # M1
        d = os.path.join(self.tmp, "c")
        os.mkdir(d)
        self.refused(plugin.manifest, d, P + ": cannot be read (FileNotFoundError)")
        self.refused(plugin.manifest, os.path.join(self.tmp, "nodir"), P + ": cannot be read (FileNotFoundError)")

    def test_m1_plugin_dir_is_a_file(self):  # M1
        d = os.path.join(self.tmp, "e")
        os.mkdir(d)
        with open(os.path.join(d, ".claude-plugin"), "w") as fh:
            fh.write("x")
        self.refused(plugin.manifest, d, P + ": cannot be read (NotADirectoryError)")

    def test_m2_bytes(self):  # M2
        self.refused(plugin.manifest, self.fixture_dir(b'{"a": "\xff"}', raw=True), P + ": is not valid UTF-8")
        self.refused(plugin.manifest, self.fixture_dir(b'\xef\xbb\xbf{"a": 1}', raw=True), P + ": is not valid JSON")
        self.refused(plugin.manifest, self.fixture_dir(b"", raw=True), P + ": is not valid JSON")

    def test_m3_json(self):  # M3
        self.refused(plugin.manifest, self.fixture_dir(b'{"a": ', raw=True), P + ": is not valid JSON")
        for body in (b'["a"]', b'"a"', b"null", b"7", b"true", b"1.5"):
            with self.subTest(body=body):
                self.refused(plugin.manifest, self.fixture_dir(body, raw=True), P + ": the top level must be an object")

    def test_m3_duplicate_keys(self):  # M3
        self.refused(plugin.manifest, self.fixture_dir(b'{"a": 1, "a": 2}', raw=True), P + ": duplicate key 'a'")
        self.refused(plugin.manifest, self.fixture_dir(b'{"a": {"b": 1, "b": 2}}', raw=True),
                     P + ": duplicate key 'b'")
        self.refused(plugin.manifest, self.fixture_dir(b'{"a": [{"c": 1, "c": 1}]}', raw=True),
                     P + ": duplicate key 'c'")

    def test_m4_constants(self):  # M4
        for const in ("NaN", "Infinity", "-Infinity"):
            for body in ('{"a": %s}', '{"a": [%s]}', '{"a": {"b": %s}}'):
                with self.subTest(const=const, body=body):
                    self.refused(plugin.manifest, self.fixture_dir((body % const).encode(), raw=True),
                                 P + ": the constant %s is not allowed" % const)

    def test_m4_non_finite_numbers(self):  # M4 (decision P4)
        for body in NOT_FINITE_BODIES:
            with self.subTest(body=body):
                self.refused(plugin.manifest, self.fixture_dir(body, raw=True), P + ": " + NOT_FINITE)

    def test_m4_finite_numbers_are_accepted(self):  # M4 invariant: only a non-finite value is refused
        d = self.fixture_dir(b'{"a": 1e300, "b": -1.5e-300, "c": 0.0, "d": 1E5, "e": [2.5], "f": -0.0}', raw=True)
        self.assertEqual(sorted(plugin.manifest(d)), ["a", "b", "c", "d", "e", "f"])
        self.assertEqual(plugin.manifest(d)["a"], 1e300)

    def test_f1_framework_dir_argument(self):  # F1 (decision U1): checked before any filesystem call
        class S(str):
            pass
        rows = [(None, "None"), (5, "5"), (b"/tmp", "b'/tmp'"), (["x"], "[x]"), (S("/tmp"), "/tmp"),
                ("a\x00b", "a\\x00b"), ("\x00", "\\x00"), ("\U0001fae0\x00", "\\U0001fae0\\x00"),
                ("/tmp/ౝ\x00", "/tmp/\\u0c5d\\x00"), (True, "True"), (1.5, "1.5"), (("x",), "[x]"),
                (S("a\x00b"), "a\\x00b")]
        for fn in (plugin.manifest, plugin.version, plugin.repository_url, plugin.repository_slug):
            for value, shown in rows:
                with self.subTest(fn=fn.__name__, value=shown):
                    with mock.patch.object(plugin.os, "stat", side_effect=AssertionError("stat")), \
                            mock.patch("gates.lib.plugin.open", create=True, side_effect=AssertionError("open")):
                        self.refused(fn, value, "framework_dir %s is not a str without a NUL character" % shown)

    def test_m5_nesting(self):  # M5
        d = self.fixture_dir(b"[" * 100000, raw=True)
        with self.assertRaises(GateError) as cm:
            plugin.manifest(d)
        self.assertIn(str(cm.exception), (P + ": nesting is too deep", P + ": is not valid JSON"))
        d = self.fixture_dir(b'{"a": ' + b"[" * 100000 + b"]" * 100000 + b"}", raw=True)
        self.refused(plugin.manifest, d, P + ": nesting is too deep")

    def test_s1_integer_digits(self):  # S1
        ok = self.fixture_dir(b'{"a": %s}' % (b"1" * 4300), raw=True)
        self.assertEqual(sorted(plugin.manifest(ok)), ["a"])
        neg = self.fixture_dir(b'{"a": -%s}' % (b"1" * 4300), raw=True)
        self.assertEqual(sorted(plugin.manifest(neg)), ["a"])
        self.refused(plugin.manifest, self.fixture_dir(b'{"a": %s}' % (b"1" * 4301), raw=True),
                     P + ": an integer of more than 4300 digits is not allowed")
        self.refused(plugin.manifest, self.fixture_dir(b'{"a": [%s]}' % (b"1" * 4301), raw=True),
                     P + ": an integer of more than 4300 digits is not allowed")

    def test_s1_integer_digits_whatever_the_interpreter_limit(self):  # S1
        script = os.path.join(self.tmp, "probe.py")
        with open(script, "w") as fh:
            fh.write("import sys\nfrom gates.lib import plugin\nfrom gates.lib.result import GateError\n"
                     "for d in sys.argv[1:]:\n    try:\n        plugin.manifest(d)\n        print('ok')\n"
                     "    except GateError as e:\n        print(e)\n")
        ok = self.fixture_dir(b'{"a": %s}' % (b"1" * 4300), raw=True)
        bad = self.fixture_dir(b'{"a": %s}' % (b"1" * 4301), raw=True)
        for limit in ("0", "640"):
            with self.subTest(limit=limit):
                env = dict(os.environ, PYTHONPATH=REPO, PYTHONINTMAXSTRDIGITS=limit)
                p = subprocess.run([sys.executable, script, ok, bad], env=env, cwd=self.tmp, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE)
                self.assertEqual(p.stderr, b"")
                self.assertEqual(p.stdout.decode(),
                                 "ok\n" + P + ": an integer of more than 4300 digits is not allowed\n")

    @unittest.skipUnless(HAS_BEG, "BaseExceptionGroup present: False (Python < 3.11)")
    def test_s3_base_exception_group_in_read_propagates(self):  # S3
        d = self.fixture_dir({"a": 1})
        with mock.patch("gates.lib.plugin.open", create=True,
                        side_effect=BaseExceptionGroup("g", [KeyboardInterrupt()])):
            with self.assertRaises(BaseExceptionGroup):
                plugin.manifest(d)

    def test_s3_plain_baseexception_in_read_propagates(self):  # S3 (the 3.9 form)
        class Odd(BaseException):
            pass
        d = self.fixture_dir({"a": 1})
        with mock.patch("gates.lib.plugin.open", create=True, side_effect=Odd()):
            with self.assertRaises(Odd):
                plugin.manifest(d)
        with mock.patch("gates.lib.plugin.open", create=True, side_effect=KeyboardInterrupt()):
            with self.assertRaises(KeyboardInterrupt):
                plugin.manifest(d)


class VersionTest(FixtureCase):
    def test_v1_value(self):  # V1
        class S(str):
            pass
        self.refused(plugin.version, self.without_key("version"), P + ": version is missing")
        for value, shown in (("", ""), (0, "0"), (True, "True"), (None, "None"), (["0.0.0"], "[0.0.0]")):
            with self.subTest(value=value):
                d = self.with_key("version", value)
                if value == "":
                    self.refused(plugin.version, d, P + ": version  is not of the form X.Y.Z")
                else:
                    self.refused(plugin.version, d, P + ": version must be a string, got " + shown)
        # a str subclass cannot come out of json.loads; it enters through a patched manifest
        with mock.patch.object(plugin, "manifest", return_value={"version": S("0.0.0")}):
            self.refused(plugin.version, "x", P + ": version must be a string, got 0.0.0")
        self.refused(plugin.version, self.with_key("version", 10 ** 30),
                     P + ": version must be a string, got 1" + "0" * 30)

    def test_v1_value_nested_deeper_than_the_render_cap_is_named_by_type(self):  # V1
        deep = "x"
        for _ in range(60):
            deep = [deep]
        self.refused(plugin.version, self.with_key("version", deep), P + ": version must be a string, got list")
        self.refused(plugin.repository_url, self.with_key("repository", deep),
                     P + ": repository must be a string, got list")

    def test_strict_semver_only(self):  # V2
        for v in V2_ROWS:
            with self.subTest(version=v):
                with self.assertRaises(GateError) as cm:
                    plugin.version(self.with_key("version", v))
                self.assertEqual(str(cm.exception), P + ": version %s is not of the form X.Y.Z" % v)

    def test_v3_accepted(self):  # V3
        for v in ("0.0.0", "1.2.3", "10.20.30", "0.10.0"):
            with self.subTest(version=v):
                got = plugin.version(self.with_key("version", v))
                self.assertIs(type(got), str)
                self.assertEqual(got, v)
        self.assertEqual(plugin.version(REPO), "0.0.0")

    def test_s1_long_version_text_is_accepted_without_int(self):  # S1
        for n in (4300, 4301):
            with self.subTest(digits=n):
                v = "1" * n + ".0.0"
                self.assertEqual(plugin.version(self.with_key("version", v)), v)

    def test_s2_unicode_version_text_refused(self):  # S2
        for ch in ("\U0001fae0", "\u0c5d", "\u2c2f"):
            with self.subTest(cp=ord(ch)):
                v = "1.0.0" + ch
                self.refused(plugin.version, self.with_key("version", v), P + ": version %s is not of the form X.Y.Z" % v)

    def test_constants(self):
        self.assertEqual(plugin.VERSION.pattern, r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\Z")
        self.assertEqual(plugin.REPOSITORY.pattern,
                         r"https://github\.com/([A-Za-z0-9-]+)/([A-Za-z0-9._-]+?)(\.git)?\Z")


class RepositoryTest(FixtureCase):
    def test_r1_value(self):  # R1
        class S(str):
            pass
        for fn in (plugin.repository_url, plugin.repository_slug):
            with self.subTest(fn=fn.__name__):
                self.refused(fn, self.without_key("repository"), P + ": repository is missing")
                self.refused(fn, self.with_key("repository", ""), P + ": repository  is not https://github.com/<owner>/<name>")
                self.refused(fn, self.with_key("repository", 5), P + ": repository must be a string, got 5")
                self.refused(fn, self.with_key("repository", None), P + ": repository must be a string, got None")
                with mock.patch.object(plugin, "manifest", return_value={"repository": S("https://github.com/o/n")}):
                    self.refused(fn, "x", P + ": repository must be a string, got https://github.com/o/n")

    def test_r2_text(self):  # R2
        rows = ["https://github.com/o /n", "http://github.com/o/n", "https://gitlab.com/o/n", "https://github.com/o/n/",
                "https://github.com/o_x/n", "https://github.com/o", "https://github.com/o/n?x", "HTTPS://github.com/o/n",
                "https://www.github.com/o/n", "https://github.com/o/n\n", " https://github.com/o/n",
                "https://github.com/o/n.git.git/", "https://github.com/\uff4f/n", "https://github.com//n",
                "https://github.com/o/n.git ", "https://github.com/o/n#f", "git@github.com:o/n.git",
                "https://github.com/o/n\u0660", "https://github.com/o/n\U0001fae0", "https://github.com/o/\u0c5d",
                "https://github.com/o/\u2c2f"]
        for v in rows:
            for fn in (plugin.repository_url, plugin.repository_slug):
                with self.subTest(repository=v, fn=fn.__name__):
                    self.refused(fn, self.with_key("repository", v),
                                 P + ": repository %s is not https://github.com/<owner>/<name>" % v)

    def test_r4_name_made_only_of_dots_is_refused(self):  # R4 (decision, item 6): narrows the plan's REPOSITORY regex
        for v in ("https://github.com/o/.", "https://github.com/o/..", "https://github.com/o/...",
                  "https://github.com/o/...git", "https://github.com/o/..git", "https://github.com/o/....",
                  "https://github.com/o/....git", "https://github.com/o/......................"):
            for fn in (plugin.repository_url, plugin.repository_slug):
                with self.subTest(repository=v, fn=fn.__name__):
                    self.refused(fn, self.with_key("repository", v),
                                 P + ": repository %s is not https://github.com/<owner>/<name>" % v)

    def test_r5_owner_starting_or_ending_with_a_dash_is_refused(self):  # R5 (decision, item 6)
        for v in ("https://github.com/-/n", "https://github.com/-o/n", "https://github.com/o-/n",
                  "https://github.com/--/n", "https://github.com/-o-/n", "https://github.com/o--/n.git"):
            for fn in (plugin.repository_url, plugin.repository_slug):
                with self.subTest(repository=v, fn=fn.__name__):
                    self.refused(fn, self.with_key("repository", v),
                                 P + ": repository %s is not https://github.com/<owner>/<name>" % v)

    def test_r4_r5_accepted_neighbours(self):  # R4/R5: the narrowing refuses nothing else
        rows = [("https://github.com/o-1/n", "o-1/n"), ("https://github.com/a-b/n", "a-b/n"),
                ("https://github.com/o/a.b", "o/a.b"), ("https://github.com/o/n.x_y", "o/n.x_y"),
                ("https://github.com/o/.github", "o/.github"), ("https://github.com/o/.a", "o/.a"),
                ("https://github.com/o/a..b", "o/a..b"), ("https://github.com/o/..a", "o/..a"),
                ("https://github.com/o/a.", "o/a."), ("https://github.com/o/.git", "o/.git"),
                ("https://github.com/o/-", "o/-"), ("https://github.com/o/_", "o/_"),
                ("https://github.com/1/n", "1/n"), ("https://github.com/O/N.git", "O/N")]
        for text, slug in rows:
            with self.subTest(repository=text):
                d = self.with_key("repository", text)
                self.assertEqual(plugin.repository_url(d), text)
                self.assertEqual(plugin.repository_slug(d), slug)

    def test_repository_readers(self):  # R3; F-B3p-19 (i)
        self.assertEqual(plugin.repository_url(REPO), real_manifest()["repository"])
        self.assertEqual(plugin.repository_slug(REPO), "superbrobenji/strict-delivery")
        rows = [("https://github.com/o/n", "https://github.com/o/n", "o/n"),
                ("https://github.com/o/n.git", "https://github.com/o/n.git", "o/n"),
                ("https://github.com/o-1/n.x_y", "https://github.com/o-1/n.x_y", "o-1/n.x_y"),
                ("https://github.com/O/N-1", "https://github.com/O/N-1", "O/N-1")]
        for text, url, slug in rows:
            with self.subTest(repository=text):
                d = self.with_key("repository", text)
                self.assertEqual(plugin.repository_url(d), url)
                self.assertEqual(plugin.repository_slug(d), slug)
                self.assertIs(type(plugin.repository_url(d)), str)
                self.assertIs(type(plugin.repository_slug(d)), str)
        self.assertEqual(plugin.repository_slug(self.with_key("repository", "https://github.com/o/n.git")), "o/n")


class ForbiddenCharTest(unittest.TestCase):
    def test_manifest_content_has_no_unlisted_character(self):
        for rel in (P, ".claude-plugin/marketplace.json"):
            self.assertEqual(prose_check.char_refusals(read(rel)), [])


# ---------------------------------------------------------------- hook command (rows H)

GATES_SRC = os.path.join(REPO, "gates")


class HookCase(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.tmp = os.path.realpath(td.name)
        self.copy = os.path.join(self.tmp, "copy")
        os.mkdir(self.copy)
        shutil.copytree(GATES_SRC, os.path.join(self.copy, "gates"),
                        ignore=shutil.ignore_patterns("__pycache__", "hook.py"))

    def hook_file(self, body):
        with open(os.path.join(self.copy, "gates", "hook.py"), "w", encoding="utf-8") as fh:
            fh.write(body)

    def run_hook(self, *argv):
        env = dict(os.environ, PYTHONPATH="", PYTHONDONTWRITEBYTECODE="1")
        p = subprocess.run([sys.executable, "-m", "gates", "hook"] + list(argv), cwd=self.copy, env=env,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return p.returncode, p.stdout.decode("utf-8"), p.stderr.decode("utf-8")


class HookCommandTest(HookCase):
    def test_hook_command_fails_closed_when_absent(self):  # H2
        self.assertFalse(os.path.exists(os.path.join(self.copy, "gates", "hook.py")))
        self.assertEqual(self.run_hook("PreToolUse"), (2, "", "FAIL hook.missing: gates.hook is not installed\n"))
        self.assertEqual(self.run_hook(), (2, "", "FAIL hook.missing: gates.hook is not installed\n"))

    def test_h1_present_exit_code_and_args_pass_through(self):  # H1
        for code in (0, 2, 7):
            with self.subTest(code=code):
                self.hook_file("import sys\n\ndef main(args):\n    sys.stdout.write(repr(args))\n    return %d\n" % code)
                self.assertEqual(self.run_hook("PreToolUse", "--x", ""), (code, "['PreToolUse', '--x', '']", ""))
        self.assertEqual(self.run_hook(), (7, "[]", ""))

    def test_h3_hook_imports_a_missing_module(self):  # H3
        self.hook_file("import nosuchmod_x\n\ndef main(args):\n    return 0\n")
        self.assertEqual(self.run_hook("PreToolUse"), (2, "", "FAIL hook.import: nosuchmod_x\n"))

    def test_h4_hook_raises_not_found_for_itself_with_the_file_present(self):  # H4
        self.hook_file("raise ModuleNotFoundError('x', name='gates.hook')\n")
        self.assertEqual(self.run_hook(), (2, "", "FAIL hook.import: gates.hook\n"))
        self.hook_file("raise ImportError('x', name='gates.hook')\n")
        self.assertEqual(self.run_hook(), (2, "", "FAIL hook.import: gates.hook\n"))

    def test_h5_other_import_failures(self):  # H5
        rows = [("raise ImportError('x')\n", "ImportError"), ("def (:\n", "SyntaxError"),
                ("raise RuntimeError('x')\n", "RuntimeError"), ("raise ValueError('x')\n", "ValueError"),
                ("raise ImportError('x', name='')\n", "ImportError"),
                ("raise ImportError('x', name=5)\n", "ImportError"),
                ("raise ModuleNotFoundError('x')\n", "ModuleNotFoundError"),
                ("1 / 0\n", "ZeroDivisionError")]
        for body, name in rows:
            with self.subTest(body=body):
                self.hook_file(body)
                self.assertEqual(self.run_hook("PreToolUse"), (2, "", "FAIL hook.import: %s\n" % name))

    def test_r1_1_import_error_name_with_a_raising_eq_fails_closed(self):  # F-3d1-R1-1
        bodies = [
            "class N:\n    def __eq__(self, o):\n        raise RuntimeError('eq')\n    __hash__ = None\n"
            "raise ImportError('x', name=N())\n",
            "class N(str):\n    def __eq__(self, o):\n        raise RuntimeError('eq')\n    __hash__ = None\n"
            "raise ImportError('x', name=N('gates.hook'))\n",
            "class N(str):\n    def __eq__(self, o):\n        raise RuntimeError('eq')\n    __hash__ = None\n"
            "raise ImportError('x', name=N('other'))\n",
            "class N:\n    pass\nraise ImportError('x', name=N())\n",
            "class N(str):\n    pass\nraise ImportError('x', name=N('gates.hook'))\n",
            "class N(str):\n    pass\nraise ImportError('x', name=N('other'))\n",
        ]
        for body in bodies:
            with self.subTest(body=body):
                self.hook_file(body)
                self.assertEqual(self.run_hook("PreToolUse"), (2, "", "FAIL hook.import: ImportError\n"))
        self.hook_file("class N:\n    def __eq__(self, o):\n        raise RuntimeError('eq')\n    __hash__ = None\n"
                       "raise ModuleNotFoundError('x', name=N())\n")
        self.assertEqual(self.run_hook(), (2, "", "FAIL hook.import: ModuleNotFoundError\n"))

    def test_p1_systemexit_at_import_fails_closed(self):  # decision P1: plan :3266 "(fail closed)"
        for body in ("raise SystemExit(0)\n", "raise SystemExit(1)\n", "raise SystemExit()\n", "raise SystemExit(None)\n",
                     "import sys\nsys.exit('x')\n", "raise SystemExit(3)\n", "class E(SystemExit):\n    pass\nraise E(0)\n"):
            with self.subTest(body=body):
                self.hook_file(body)
                self.assertEqual(self.run_hook("PreToolUse"), (2, "", "FAIL hook.import: SystemExit\n"
                                                               if "class E" not in body else
                                                               "FAIL hook.import: E\n"))

    def test_main_own_exceptions_and_exits_stay_the_hooks_contract(self):  # invariant of the replaced code
        self.hook_file("def main(args):\n    raise SystemExit(5)\n")
        self.assertEqual(self.run_hook(), (5, "", ""))
        self.hook_file("def main(args):\n    raise SystemExit(0)\n")
        self.assertEqual(self.run_hook(), (0, "", ""))
        self.hook_file("def main(args):\n    raise RuntimeError('boom')\n")
        code, out, err = self.run_hook()
        self.assertEqual((code, out), (1, ""))
        self.assertIn("RuntimeError: boom", err)

    def test_h6_no_callable_main(self):  # H6
        for body in ("x = 1\n", "main = 3\n", "main = None\n", "def __getattr__(n):\n    raise RuntimeError(n)\n"):
            with self.subTest(body=body):
                self.hook_file(body)
                self.assertEqual(self.run_hook(), (2, "", "FAIL hook.import: gates.hook has no callable main\n"))

    def test_h8_registration(self):  # H8
        self.assertIn("hook", gates_main.COMMANDS)
        p = subprocess.run([sys.executable, "-m", "gates"], cwd=REPO, env=dict(os.environ, PYTHONPATH=REPO),
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual((p.returncode, p.stdout, p.stderr.decode()),
                         (2, b"", "usage: python3 -m gates <command> [args]\n"
                                  "commands: check, decisions, findings, hook, index, run_all\n"))

    def test_s2_unicode_in_an_import_error_name_is_escaped_the_same_on_both(self):  # S2
        rows = [("\U0001fae0", "\\U0001fae0"), ("\u0c5d", "\\u0c5d"), ("\u2c2f", "\\u2c2f"), ("a\nb", "a\\nb"),
                ("a\\b", "a\\\\b")]
        for ch, esc in rows:
            with self.subTest(cp=ord(ch[0])):
                self.hook_file("raise ImportError('x', name=%r)\n" % ("m" + ch))
                self.assertEqual(self.run_hook(), (2, "", "FAIL hook.import: m%s\n" % esc))


class FakeLoader:
    def __init__(self, exc):
        self.exc = exc

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        raise self.exc


class FakeFinder:
    def __init__(self, exc):
        self.exc = exc

    def find_spec(self, name, path=None, target=None):
        if name == "gates.hook":
            return importlib.machinery.ModuleSpec(name, FakeLoader(self.exc))
        return None


class HookInProcessTest(unittest.TestCase):
    def call_with_import_raising(self, exc):
        sys.modules.pop("gates.hook", None)
        self.addCleanup(sys.modules.pop, "gates.hook", None)
        finder = FakeFinder(exc)
        sys.meta_path.insert(0, finder)
        self.addCleanup(sys.meta_path.remove, finder)
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                gates_main.main(["hook", "PreToolUse"])
            finally:
                self.assertEqual((out.getvalue(), err.getvalue()), ("", ""))

    def test_h7_non_exception_baseexception_propagates(self):  # H7
        class Odd(BaseException):
            pass
        for exc in (KeyboardInterrupt(), Odd(), GeneratorExit()):
            with self.subTest(exc=type(exc).__name__):
                with self.assertRaises(type(exc)):
                    self.call_with_import_raising(exc)

    @unittest.skipUnless(HAS_BEG, "BaseExceptionGroup present: False (Python < 3.11)")
    def test_s3_base_exception_group_at_import_propagates(self):  # S3
        with self.assertRaises(BaseExceptionGroup):
            self.call_with_import_raising(BaseExceptionGroup("g", [KeyboardInterrupt()]))

    @unittest.skipUnless(HAS_BEG, "ExceptionGroup present: False (Python < 3.11)")
    def test_s3_exception_group_at_import_fails_closed(self):  # S3
        sys.modules.pop("gates.hook", None)
        self.addCleanup(sys.modules.pop, "gates.hook", None)
        finder = FakeFinder(ExceptionGroup("g", [ValueError()]))
        sys.meta_path.insert(0, finder)
        self.addCleanup(sys.meta_path.remove, finder)
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            self.assertEqual(gates_main.main(["hook"]), 2)
        self.assertEqual((out.getvalue(), err.getvalue()), ("", "FAIL hook.import: ExceptionGroup\n"))

    def test_s3_plain_baseexception_at_import_propagates(self):  # S3 (the 3.9 form)
        class Odd(BaseException):
            pass
        with self.assertRaises(Odd):
            self.call_with_import_raising(Odd())

    def test_absent_needs_the_error_to_name_gates_hook(self):  # D7: both halves of the test
        sys.modules.pop("gates.hook", None)
        self.addCleanup(sys.modules.pop, "gates.hook", None)

        class Finder:
            calls = 0

            def find_spec(self, name, path=None, target=None):
                if name == "gates.hook":
                    Finder.calls += 1
                    if Finder.calls == 1:      # the import fails naming another module; the later lookup finds none
                        raise ModuleNotFoundError("other", name="foo")
                return None
        finder = Finder()
        sys.meta_path.insert(0, finder)
        self.addCleanup(sys.meta_path.remove, finder)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(gates_main.main(["hook"]), 2)
        self.assertEqual(err.getvalue(), "FAIL hook.import: foo\n")

    def test_find_spec_raising_is_not_absent(self):  # D7: the lookup raising an Exception shows nothing
        sys.modules.pop("gates.hook", None)
        self.addCleanup(sys.modules.pop, "gates.hook", None)

        class Finder:
            def find_spec(self, name, path=None, target=None):
                if name == "gates.hook":
                    raise ModuleNotFoundError("gone", name="gates.hook")
                return None
        finder = Finder()
        sys.meta_path.insert(0, finder)
        self.addCleanup(sys.meta_path.remove, finder)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(gates_main.main(["hook"]), 2)
        self.assertEqual(err.getvalue(), "FAIL hook.import: gates.hook\n")


if __name__ == "__main__":
    unittest.main()
